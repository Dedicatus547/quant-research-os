"""Offline verified feedback extraction and deterministic task reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from quantos.contracts.adaptive_feedback import (
    AdaptiveFeedback,
    AdaptiveGateFeedback,
    AdaptiveMetricFeedback,
    AdaptiveProcessExit,
)
from quantos.contracts.autonomous import AutonomousExecutionRequest, AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.research import SoftMetric
from quantos.contracts.status import RunStatus, ValidationVerdict

if TYPE_CHECKING:
    from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter


def build_feedback(
    *,
    task_hash: str,
    child_hash: str,
    request: AutonomousExecutionRequest,
    outcome: AutonomousExecutionResult,
    adapter: QuantosResearchExecutionAdapter,
    process_exit: dict[str, Any] | None = None,
) -> AdaptiveFeedback:
    """Reverify full originals before projecting; never execute or trust an input summary.

    The caller binds task/child to its immutable child reservation. The adapter binds
    the exact request, candidate, receipt, outcome and complete underlying originals.
    """
    if outcome.request_hash != request.content_hash:
        raise ValueError("feedback outcome belongs to another request")
    verified = adapter.verified_completed_execution(request)
    if verified is None or verified != outcome or outcome.execution_artifact_hash is None:
        raise ValueError("feedback requires an exact fully verified completion and receipt")
    report = None
    failure = None
    failure_hash = None
    if outcome.validation_report_hash is not None:
        report = adapter.verify_validation_report(outcome.validation_report_hash)
        if report is None or report.content_hash != outcome.validation_report_hash:
            raise ValueError("feedback ValidationReport original is missing or mismatched")
        if (
            report.validation_policy_hash != request.validation_policy_hash
            or report.research_policy_hash != request.research_policy_hash
            or report.snapshot_hash not in (None, request.snapshot_hash)
            or report.qlib_view_hash not in (None, request.qlib_view_hash)
        ):
            raise ValueError("feedback ValidationReport input bindings disagree")
    else:
        for digest in outcome.evidence_hashes:
            if digest == outcome.execution_artifact_hash:
                continue
            item = adapter.verify_execution_failure(digest)
            if item is not None:
                if failure is not None:
                    raise ValueError("feedback has ambiguous failure originals")
                failure, failure_hash = item, digest
        if failure is None or (
            failure.content_hash != failure_hash
            or failure.execution_identity != request.execution_identity
            or failure.request_hash != request.content_hash
            or failure.campaign_hash != request.campaign_hash
            or failure.candidate_hash != request.candidate.content_hash
            or failure.snapshot_hash != request.snapshot_hash
            or failure.reason_code != outcome.failure_reason_code
        ):
            raise ValueError("feedback failure original is missing or bound to different inputs")

    if report is not None:
        run_status, verdict = report.run_status, report.verdict
        expected = (
            {TrialOutcome.EXECUTION_FAILED}
            if run_status is RunStatus.FAILED
            else {TrialOutcome.PASS}
            if verdict is ValidationVerdict.PASS
            else {TrialOutcome.HARD_REJECT, TrialOutcome.SOFT_REJECT, TrialOutcome.PIT_REJECT}
        )
        if outcome.outcome not in expected:
            raise ValueError("feedback outcome disagrees with verified scientific status")
    elif failure is not None and failure.failure_kind == "PIT_REJECTED":
        if outcome.outcome is not TrialOutcome.PIT_REJECT:
            raise ValueError("PIT failure original disagrees with outcome")
        run_status, verdict = RunStatus.SUCCEEDED, ValidationVerdict.REJECT
    else:
        if outcome.outcome is not TrialOutcome.EXECUTION_FAILED:
            raise ValueError("execution failure original disagrees with outcome")
        run_status, verdict = RunStatus.FAILED, ValidationVerdict.NOT_EVALUATED

    metric_by_id = (
        {item.metric: item for item in report.metrics}
        if report is not None and run_status is RunStatus.SUCCEEDED
        else {}
    )
    return AdaptiveFeedback(
        task_hash=task_hash,
        child_hash=child_hash,
        campaign_hash=request.campaign_hash,
        request_hash=request.content_hash,
        candidate_hash=request.candidate.content_hash,
        candidate_exact_expression_hash=request.candidate_exact_expression_hash,
        candidate_structural_expression_hash=request.candidate_structural_expression_hash,
        execution_identity=request.execution_identity,
        outcome_hash=outcome.content_hash,
        receipt_hash=outcome.execution_artifact_hash,
        outcome=outcome.outcome,
        run_status=run_status,
        verdict=verdict,
        failure_reason_code=outcome.failure_reason_code,
        validation_report_hash=outcome.validation_report_hash,
        failure_evidence_hash=failure_hash,
        original_hashes=outcome.evidence_hashes,
        gates=tuple(
            AdaptiveGateFeedback(
                gate_id=item.gate_id, verdict=item.verdict, reason_code=item.reason_code
            )
            for item in report.gates
        )
        if report is not None
        else (),
        metrics=tuple(
            AdaptiveMetricFeedback(
                metric=metric,
                value=metric_by_id[metric].value if metric in metric_by_id else None,
                source_hash=metric_by_id[metric].source.sha256 if metric in metric_by_id else None,
            )
            for metric in SoftMetric
        ),
        missing_evidence=tuple(
            cast(Literal["VALIDATION_REPORT", "PROCESS_EXIT"], name)
            for name, missing in (
                ("VALIDATION_REPORT", report is None),
                ("PROCESS_EXIT", process_exit is None),
            )
            if missing
        ),
        process_exit=AdaptiveProcessExit.model_validate(process_exit)
        if process_exit is not None
        else None,
        compute_units=outcome.compute_seconds,
    )


def render_adaptive_report(summary: dict[str, Any]) -> str:
    """Render retained task facts without deriving qualification or calling a model.

    Missing fields remain JSON null. The caller supplies the reconciled ledger and
    complete opportunity denominator, including failed and unknown attempts.
    """
    fields = (
        ("Task", "task_hash"),
        ("Status", "status"),
        ("Stop reason", "stop_reason"),
        ("Feedback verification", "feedback_verification"),
        ("Opportunity denominator", "opportunities"),
        ("Consumed policy units", "consumed_units"),
        ("Reserved policy units", "reserved_units"),
        ("Feedback and originals", "feedback"),
        ("Unproven capabilities", "unproven_capabilities"),
    )
    lines = ["# Bounded adaptive research", ""]
    for label, key in fields:
        lines.append(f"{label}: {canonical_json_bytes(summary.get(key)).decode('utf-8')}")
    lines.extend(
        ("", "Original immutable evidence remains authority. Missing values are null.", "")
    )
    return "\n".join(lines)
