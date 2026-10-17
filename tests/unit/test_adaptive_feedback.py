"""Feedback risk probes use typed fixtures and a fake verifier; no science or model."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.application.adaptive_feedback import build_feedback, render_adaptive_report
from quantos.contracts.adaptive_feedback import MAX_FEEDBACK_BYTES, AdaptiveFeedback
from quantos.contracts.autonomous import (
    AutonomousExecutionFailureEvidence,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
)
from quantos.contracts.enumeration import ResearchCandidateSpec
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    GateResult,
    ValidationArtifactFile,
    ValidationGateId,
    ValidationMetric,
    ValidationReport,
)

H = "a" * 64
RECEIPT = "b" * 64


def request_fixture():
    candidate = ResearchCandidateSpec(
        candidate_id=f"candidate-{H}",
        family_hash=H,
        factor_template_hash=H,
        parameters=({"name": "window", "value": 2},),
        expression={
            "expression_id": "probe",
            "nodes": ({"node_id": "price", "operator": "field", "field_name": "close"},),
            "output_node_id": "price",
        },
        exact_expression_hash=H,
        structural_expression_hash=H,
    )
    values = {
        name: H
        for name in (
            "idempotency_key",
            "execution_identity",
            "campaign_hash",
            "family_hash",
            "budget_hash",
            "candidate_manifest_hash",
            "candidate_exact_expression_hash",
            "candidate_structural_expression_hash",
            "snapshot_hash",
            "qlib_view_hash",
            "agent_run_hash",
            "execution_policy_hash",
            "pit_policy_hash",
            "authoring_hash",
            "research_policy_hash",
            "validation_policy_hash",
            "cost_policy_hash",
            "backtest_policy_hash",
            "lockfile_hash",
        )
    }
    return AutonomousExecutionRequest(
        **values,
        trial_ordinal=1,
        candidate=candidate,
        dataset_id="offline-probe",
        segment="DEVELOPMENT",
        segment_start=date(2020, 1, 1),
        segment_end=date(2020, 2, 1),
        code_commit_hash="a" * 40,
        qlib_version="0.9.7",
        remaining_executions=1,
        remaining_validation_rounds=1,
        remaining_compute_seconds=1,
    )


def report_fixture(verdict="REJECT", value=-0.2):
    source = ArtifactRef(
        kind="test", sha256=H, size_bytes=1, media_type="application/json", logical_path="test.json"
    )
    return ValidationReport.create(
        experiment_id="feedback-probe",
        authoring_spec_hash=H,
        validation_policy_hash=H,
        research_policy_hash=H,
        runtime_fingerprint_hash=H,
        snapshot_hash=H,
        qlib_view_hash=H,
        run_status=RunStatus.SUCCEEDED,
        verdict=ValidationVerdict(verdict),
        canonical=True,
        gates=tuple(
            GateResult(
                **{
                    "gate_id": gate,
                    "severity": "HARD",
                    "verdict": "REJECT" if verdict == "REJECT" and index == 2 else "PASS",
                    "reason_code": "LOOK_AHEAD" if verdict == "REJECT" and index == 2 else None,
                    "reason": "fixture",
                    "evidence": (source,),
                }
            )
            for index, gate in enumerate(ValidationGateId)
        ),
        metrics=(ValidationMetric(metric="rank_ic", value=value, source=source, detail="fixture"),),
        files=tuple(
            ValidationArtifactFile(logical_path=name, sha256=H, size_bytes=1)
            for name in (
                "authoring-spec.json",
                "research-policy.json",
                "runtime-fingerprint.json",
                "validation-policy.json",
            )
        ),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )


class FakeAdapter:
    def __init__(self, request, report=None, failure_kind=None):
        self.report = report
        self.failure = None
        self.calls = []
        if failure_kind is not None:
            self.failure = AutonomousExecutionFailureEvidence(
                execution_identity=request.execution_identity,
                request_hash=request.content_hash,
                campaign_hash=request.campaign_hash,
                candidate_hash=request.candidate.content_hash,
                snapshot_hash=request.snapshot_hash,
                failure_kind=failure_kind,
                reason_code="LOOK_AHEAD"
                if failure_kind == "PIT_REJECTED"
                else "QLIB_EXECUTION_FAILED",
            )
        original = report.content_hash if report else self.failure.content_hash
        self.outcome = AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=("PIT_REJECT" if failure_kind == "PIT_REJECTED" else "EXECUTION_FAILED")
            if failure_kind
            else ("PASS" if report.verdict.value == "PASS" else "HARD_REJECT"),
            execution_requested=failure_kind != "PIT_REJECTED",
            compute_seconds=7,
            execution_artifact_hash=RECEIPT,
            evidence_hashes=tuple(sorted((original, RECEIPT))),
            validation_report_hash=report.content_hash if report else None,
            failure_reason_code=self.failure.reason_code if self.failure else None,
        )

    def verified_completed_execution(self, request):
        self.calls.append("complete")
        return self.outcome

    def verify_validation_report(self, digest):
        self.calls.append("validation")
        return self.report

    def verify_execution_failure(self, digest):
        self.calls.append("failure")
        return self.failure if self.failure and self.failure.content_hash == digest else None


def feedback(request, adapter, **kwargs):
    return build_feedback(
        task_hash="c" * 64,
        child_hash="d" * 64,
        request=request,
        outcome=adapter.outcome,
        adapter=adapter,
        **kwargs,
    )


def test_verified_different_feedback_preserves_null_and_original_sources():
    request = request_fixture()
    rejected = FakeAdapter(request, report_fixture())
    passed = FakeAdapter(request, report_fixture("PASS", 0.3))
    left, right = feedback(request, rejected), feedback(request, passed)
    assert left.verdict.value == "REJECT" and right.verdict.value == "PASS"
    assert left.run_status.value == right.run_status.value == "SUCCEEDED"
    assert left.content_hash != right.content_hash
    assert left.metrics[1].value == -0.2 and right.metrics[1].value == 0.3
    assert left.metrics[0].value is None and left.metrics[0].source_hash is None
    assert left.metrics[1].source_hash == H
    assert left.gates[2].reason_code.value == "LOOK_AHEAD"
    assert left.receipt_hash == RECEIPT and left.request_hash == request.content_hash
    assert len(left.canonical_bytes()) <= MAX_FEEDBACK_BYTES
    assert AdaptiveFeedback.model_validate(left.model_dump()) == left
    assert rejected.calls == ["complete", "validation"]


@pytest.mark.parametrize(
    "kind,status,verdict",
    [
        ("PIT_REJECTED", "SUCCEEDED", "REJECT"),
        ("EXECUTION_FAILED", "FAILED", "NOT_EVALUATED"),
    ],
)
def test_failure_preserves_scientific_distinction(kind, status, verdict):
    request = request_fixture()
    adapter = FakeAdapter(request, failure_kind=kind)
    result = feedback(request, adapter)
    assert result.run_status.value == status and result.verdict.value == verdict
    assert all(item.value is None for item in result.metrics)
    assert result.failure_evidence_hash == adapter.failure.content_hash
    assert result.validation_report_hash is None
    assert result.missing_evidence == ("VALIDATION_REPORT", "PROCESS_EXIT")
    assert result.token_usage is None


@pytest.mark.parametrize(
    "fault", ["missing_receipt", "wrong_outcome", "missing_report", "wrong_policy"]
)
def test_requires_complete_receipt_and_originals(fault):
    request = request_fixture()
    adapter = FakeAdapter(request, report_fixture())
    original = adapter.outcome
    if fault == "missing_receipt":
        adapter.outcome = None
    elif fault == "wrong_outcome":
        adapter.outcome = original.model_copy(update={"compute_seconds": 8})
    elif fault == "missing_report":
        adapter.report = None
    else:
        adapter.report = report_fixture().model_copy(update={"validation_policy_hash": "f" * 64})
    with pytest.raises(ValueError):
        build_feedback(
            task_hash=H, child_hash=H, request=request, outcome=original, adapter=adapter
        )


@pytest.mark.parametrize("fault", ["request", "candidate", "missing"])
def test_failure_binding_and_missing_original_are_rejected(fault):
    request = request_fixture()
    adapter = FakeAdapter(request, failure_kind="EXECUTION_FAILED")
    if fault == "missing":
        adapter.failure = None
    else:
        key = "request_hash" if fault == "request" else "candidate_hash"
        adapter.failure = adapter.failure.model_copy(update={key: "e" * 64})
    with pytest.raises(ValueError):
        feedback(request, adapter)


def test_wrong_request_rejected_before_verifier():
    request = request_fixture()
    adapter = FakeAdapter(request, report_fixture())
    other = request.model_copy(update={"campaign_hash": "e" * 64})
    with pytest.raises(ValueError, match="another request"):
        feedback(other, adapter)
    assert adapter.calls == []


def test_exit_is_only_bounded_observation_and_report_is_deterministic():
    request = request_fixture()
    adapter = FakeAdapter(request, report_fixture())
    result = feedback(request, adapter, process_exit={"exit_code": 0, "evidence_hash": H})
    assert result.process_exit.authority == "UNVERIFIED_OBSERVATION"
    with pytest.raises(ValidationError):
        feedback(request, adapter, process_exit={"exit_code": 0, "raw_log": "forbidden"})
    summary = {
        "stop_reason": "MODEL_STOP",
        "opportunities": {"failed": 1, "unknown": 1},
        "consumed_units": 7,
        "reserved_units": 2,
        "feedback": [result.model_dump(mode="json")],
        "unproven_capabilities": ["REAL_MODEL_FEEDBACK_DECISION"],
    }
    rendered = render_adaptive_report(summary)
    assert rendered == render_adaptive_report(dict(reversed(tuple(summary.items()))))
    assert "Task: null" in rendered and "Reserved policy units: 2" in rendered
    assert "REAL_MODEL_FEEDBACK_DECISION" in rendered and result.receipt_hash in rendered
