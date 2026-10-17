"""New successor risk windows. Every SDK/science observation here is simulated."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from test_adaptive_feedback import FakeAdapter

from quantos.application.adaptive_execution import quote_expression
from quantos.application.adaptive_runtime import AdaptiveRuntime
from quantos.application.adaptive_sdk import AdaptiveSdkProducer, parse_decision
from quantos.application.adaptive_store import save
from quantos.application.agent_harness import (
    HarnessAttemptResult,
    HarnessExecutionResult,
    capture_from_agent_events,
)
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
)
from quantos.application.discovery_baselines import baseline_expression_space
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.adaptive import (
    AdaptiveDecision,
    AdaptiveDecisionRequest,
    AdaptiveResearchSpec,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.harness import HarnessRuntimeIdentityV2
from quantos.integrations.codex.notification_projection import normalize_provider_events


class Harness:
    def __init__(self, spec, actions):
        self.spec, self.actions = spec, actions
        self.calls = []
        self.crash = False

    def execute(self, request):
        self.calls.append(request)
        if self.crash:
            raise RuntimeError("simulated interruption after SDK intent")
        context = json.loads(request.prompt.split("Context:\n", 1)[1])
        expression = self.actions[len(self.calls) - 1]
        raw = canonical_json_bytes(
            AdaptiveDecision(
                action="PROPOSE" if expression is not None else "STOP",
                hypothesis="offline hypothesis",
                expression=expression,
                parent_proposal_hash=context["parent_proposal_hash"],
                feedback_hashes=tuple(x["feedback_hash"] for x in context["feedback"]),
                source_hashes=tuple(context["source_hashes"]),
                rationale="Evidence supports this offline branch.",
                expected_checks=("PIT", "QLIB", "VALIDATION") if expression is not None else (),
            )
        ).decode()
        provider = (
            {
                "method": "turn/started",
                "payload": {
                    "thread_id": "thread-test",
                    "turn": {"id": "turn-test", "status": "inProgress", "error": None},
                },
            },
            {
                "method": "item/completed",
                "payload": {"item": {"type": "agentMessage", "phase": "final_answer", "text": raw}},
            },
            {
                "method": "thread/tokenUsage/updated",
                "payload": {
                    "token_usage": {
                        "last": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2}
                    }
                },
            },
            {
                "method": "turn/completed",
                "payload": {
                    "thread_id": "thread-test",
                    "turn": {"id": "turn-test", "status": "completed", "error": None},
                },
            },
        )
        capture = capture_from_agent_events(
            normalize_provider_events(provider, thread_id="thread-test"), max_bytes=65536
        )
        return HarnessExecutionResult(
            attempts=(
                HarnessAttemptResult(
                    capture=capture,
                    runtime=HarnessRuntimeIdentityV2(
                        sdk_version="0.162.1",
                        runtime_package_version="0.162.1",
                        runtime_version="0.162.1",
                        runtime_binary_hash=self.spec.sdk.runtime_binary_hash,
                    ),
                    terminal_error=None,
                    provider_transcript=b"".join(canonical_json_bytes(p) + b"\n" for p in provider),
                ),
            )
        )


class Science:
    def __init__(self):
        self.adapters = {}
        self.calls = []
        self.hook = lambda _: None

    def verify_inputs(self):
        """The synthetic port deliberately opens no market inputs."""

    def adapter(self, child):
        return self.adapters[child.content_hash]

    def execute(self, child):
        self.calls.append(child.content_hash)
        adapter = FakeAdapter(child.request, failure_kind="EXECUTION_FAILED")
        adapter.outcome = adapter.outcome.model_copy(update={"compute_seconds": child.quote_units})
        self.adapters[child.content_hash] = adapter
        self.hook(child)
        return adapter.outcome

    def reconcile(self, child):
        adapter = self.adapters.get(child.content_hash)
        return adapter.outcome if adapter else None

    def process_exit(self, child):
        return None


@pytest.fixture
def case():
    root = Path(__file__).parents[2] / "artifacts/adaptive-test-authority" / uuid4().hex
    root.mkdir(parents=True)
    cwd = root / "empty"
    cwd.mkdir()
    design = json.loads(
        (Path(__file__).parents[1] / "fixtures/discovery_composition/design.json").read_bytes()
    )
    spec = AdaptiveResearchSpec(
        task_id="offline-adaptive-risk",
        design=design,
        limits={
            "sdk_decisions": 2,
            "new_candidates": 2,
            "scientific_executions": 2,
            "compute_units": 100,
            "wall_seconds": 3600,
            "storage_growth_bytes": 64 << 20,
        },
        sdk={"runtime_binary_hash": "a" * 64},
        workspace=str(Path(__file__).parents[2]),
        snapshot_path=str(root / "no-snapshot"),
        qlib_view_path=str(root / "no-view"),
        output_root=str(root / "task"),
        sdk_cwd=str(cwd),
        context="Offline synthetic protocol fixture.",
        context_source_hashes=("b" * 64,),
    )
    expressions = baseline_expression_space(spec.design)
    harness = Harness(spec, [expressions[0], expressions[1]])
    producer = AdaptiveSdkProducer(spec, harness)
    science = Science()
    return spec, producer, science, harness, expressions


def runtime(case, **kwargs):
    return AdaptiveRuntime(*case[:3], **kwargs)


def interrupt(point):
    def fault(actual):
        if actual == point:
            raise RuntimeError("simulated " + point)

    return fault


def test_two_new_ast_attempts_with_feedback_and_parent_budget(case):
    result = runtime(case).run()
    assert len(case[3].calls) == len(case[2].calls) == 2
    assert result["stop_reason"] == "DECISION_BUDGET_EXHAUSTED"
    assert result["opportunities"]["sdk_decisions"]["used"] == 2
    assert result["consumed_units"] == sum(quote_expression(case[0], e) for e in case[4][:2])
    assert result["reserved_units"] == 0
    assert all(
        x["run_status"] == "FAILED" and x["verdict"] == "NOT_EVALUATED" for x in result["feedback"]
    )
    context = json.loads(case[3].calls[1].prompt.split("Context:\n")[1])
    assert (
        context["feedback"][0]["projection"]["receipt_hash"]
        == result["feedback"][0]["receipt_hash"]
    )
    assert runtime(case).run() == result
    assert len(case[3].calls) == len(case[2].calls) == 2


def test_stop_is_not_forced_to_generate(case):
    case[3].actions = [None]
    result = runtime(case).run()
    assert result["stop_reason"] == "MODEL_STOP"
    assert len(case[3].calls) == 1 and not case[2].calls


def test_feedback_can_lead_to_stop_without_summary_call(case):
    case[3].actions[1] = None
    result = runtime(case).run()
    assert result["stop_reason"] == "MODEL_STOP" and len(result["feedback"]) == 1
    assert len(case[3].calls) == 2 and len(case[2].calls) == 1


@pytest.mark.parametrize(
    "point",
    [
        "decision_reserved",
        "capture_complete",
        "decision_submitted",
        "child_reserved",
        "science_complete",
        "science_settled",
    ],
)
def test_completed_boundaries_resume_without_repeating_effects(case, point):
    with pytest.raises(RuntimeError, match="simulated"):
        runtime(case, fault=interrupt(point)).run()
    result = runtime(case).run()
    assert result["stop_reason"] == "DECISION_BUDGET_EXHAUSTED"
    assert len(case[3].calls) == len(case[2].calls) == 2


def test_unknown_never_reissues_and_stays_in_denominator(case):
    case[3].crash = True
    with pytest.raises(RuntimeError):
        runtime(case).run()
    result = runtime(case).run()
    assert result["stop_reason"] == "UNKNOWN"
    assert result["opportunities"]["sdk_decisions"]["used"] == 1
    assert len(case[3].calls) == 1 and not case[2].calls
    runtime(case).run(receipt_only=True)
    assert len(case[3].calls) == 1


def test_started_without_complete_result_never_reexecutes(case):
    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("science_started")).run()
    result = runtime(case).run()
    assert result["stop_reason"] == "RECOVERY_REQUIRED"
    assert result["reserved_units"] > 0 and result["consumed_units"] == 0
    assert not case[2].calls and len(case[3].calls) == 1


def test_receipt_only_cannot_start_reserved_child_or_new_sdk(case):
    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("child_reserved")).run()
    result = runtime(case).run(receipt_only=True)
    assert result["reserved_units"] > 0 and not case[2].calls
    assert len(case[3].calls) == 1


def test_cancel_during_inflight_science_blocks_next_call(case):
    case[2].hook = lambda _: runtime(case).cancel()
    result = runtime(case).run()
    assert result["stop_reason"] == "CANCELLED"
    assert len(case[3].calls) == len(case[2].calls) == 1
    assert result["consumed_units"] > 0 and result["reserved_units"] == 0


def test_expiry_after_capture_blocks_science_but_allows_submit(case):
    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("capture_complete")).run()
    result = runtime(case, clock=lambda: datetime.now(UTC) + timedelta(hours=2)).run()
    assert result["stop_reason"] == "EXPIRED" and not case[2].calls
    assert len(case[3].calls) == 1


def test_duplicate_ast_does_not_reset_parent_budget(case):
    case[3].actions[1] = case[3].actions[0]
    result = runtime(case).run()
    assert result["stop_reason"] == "DUPLICATE_AST"
    assert len(case[2].calls) == 1 and len(case[3].calls) == 2


def test_second_request_restart_reverifies_feedback_original(case):
    count = 0

    def fault(point):
        nonlocal count
        if point == "decision_reserved":
            count += 1
            if count == 2:
                raise RuntimeError("second reservation")

    with pytest.raises(RuntimeError):
        runtime(case, fault=fault).run()
    next(iter(case[2].adapters.values())).outcome = None
    with pytest.raises(ArtifactIntegrityError, match="original missing"):
        runtime(case).run()
    assert len(case[3].calls) == 1


def test_unreserved_producer_cannot_launch_even_with_new_request_hash(case):
    r = runtime(case)
    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("decision_reserved")).run()
    e = next(e for e in r.store.events() if e.kind == "DECISION_RESERVED")
    request = r.store.get(e.reference_hash, AdaptiveDecisionRequest)
    for changed in [
        request.model_copy(update={"prompt": "different"}),
        request.model_copy(update={"ordinal": 2}),
    ]:
        with pytest.raises(ArtifactIntegrityError, match="parent reservation"):
            case[1].launch(changed)
    assert not case[3].calls


def test_malformed_decision_is_not_coerced(case):
    with pytest.raises(ValueError):
        parse_decision(b'{"action":"STOP"}', case[0])


def test_parent_unit_quote_insufficient_stops_before_science(case):
    spec = case[0].model_copy(
        update={"limits": case[0].limits.model_copy(update={"compute_units": 1})}
    )
    case = (spec, AdaptiveSdkProducer(spec, case[3]), case[2], case[3], case[4])
    case[3].spec = spec
    result = runtime(case).run()
    assert result["stop_reason"] == "PARENT_BUDGET_EXHAUSTED" and not case[2].calls


def test_retained_outcome_receipt_publication_never_enters_pipeline(case, monkeypatch):
    from quantos.application.adaptive_execution import freeze_child

    decision = AdaptiveDecision(
        action="PROPOSE",
        hypothesis="offline",
        expression=case[4][0],
        parent_proposal_hash=None,
        feedback_hashes=(),
        source_hashes=("b" * 64,),
        rationale="offline",
        expected_checks=("PIT", "QLIB", "VALIDATION"),
    )
    child = freeze_child(case[0], decision, "c" * 64, 1)
    fake = FakeAdapter(child.request, failure_kind="EXECUTION_FAILED")
    outcome = fake.outcome.model_copy(
        update={
            "compute_seconds": child.quote_units,
            "execution_artifact_hash": None,
            "evidence_hashes": (fake.failure.content_hash,),
        }
    )
    adapter = object.__new__(QuantosResearchExecutionAdapter)
    adapter.output_root = Path(case[0].output_root) / "retained"
    adapter.discovery_stage_recovery = True
    adapter.retain_completed_outcome = True
    monkeypatch.setattr(adapter, "_verify_request", lambda _: None)
    monkeypatch.setattr(adapter, "_deterministic_compute_charge", lambda _: child.quote_units)
    verified = []
    monkeypatch.setattr(adapter, "_verify_receipt", lambda r: verified.append(r.content_hash))
    monkeypatch.setattr(adapter, "execute", lambda _: pytest.fail("must never execute"))
    assert adapter.reconcile_completed_outcome(child.request) is None
    original = AutonomousExecutionReceipt(request=child.request, outcome=outcome)
    path = adapter.output_root / "completed-outcomes" / f"{child.request.execution_identity}.json"
    save(path, original)
    result = adapter.reconcile_completed_outcome(child.request)
    assert result.execution_artifact_hash == original.content_hash
    assert adapter.reconcile_completed_outcome(child.request) == result
    assert read_bytes(path) == original.canonical_bytes() and verified


def read_bytes(path):
    return path.read_bytes()


@pytest.mark.parametrize("damage", ["feedback", "parent", "source", "outside_grammar"])
def test_decision_scope_rejects_forged_or_outside_proposals(case, damage, monkeypatch):
    from quantos.application import adaptive_sdk

    original = adaptive_sdk.parse_decision

    def altered(raw, spec):
        decision = original(raw, spec)
        updates = {
            "feedback": {"feedback_hashes": ("f" * 64,)},
            "parent": {"parent_proposal_hash": "f" * 64},
            "source": {"source_hashes": ("f" * 64,)},
            "outside_grammar": {
                "expression": decision.expression.model_copy(
                    update={
                        "nodes": tuple(
                            n.model_copy(update={"window": 2}) if n.window is not None else n
                            for n in decision.expression.nodes
                        )
                    }
                )
            },
        }
        return decision.model_copy(update=updates[damage])

    monkeypatch.setattr(adaptive_sdk, "parse_decision", altered)
    result = runtime(case).run()
    assert result["stop_reason"] in {
        "DECISION_SOURCE_OR_FEEDBACK_REJECTED",
        "STATIC_ADMISSION_REJECTED",
    }
    assert len(case[3].calls) == 1 and not case[2].calls


def test_abrupt_process_exit_leaves_unknown_without_reissue(case):
    import os
    import subprocess
    import sys

    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("decision_reserved")).run()
    r = runtime(case)
    event = next(e for e in r.store.events() if e.kind == "DECISION_RESERVED")
    request = r.store.get(event.reference_hash, AdaptiveDecisionRequest)
    root = Path(case[0].output_root)
    save(root / "abrupt-request.json", request)
    code = """import os,sys
from pathlib import Path
from quantos.application.adaptive_store import contract
from quantos.application.adaptive_sdk import AdaptiveSdkProducer
from quantos.contracts.adaptive import AdaptiveResearchSpec,AdaptiveDecisionRequest
class ExitHarness:
    def execute(self,request): os._exit(91)
spec=contract(Path(sys.argv[1]),AdaptiveResearchSpec)
request=contract(Path(sys.argv[2]),AdaptiveDecisionRequest)
AdaptiveSdkProducer(spec,ExitHarness()).launch(request)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(root / "spec.json"), str(root / "abrupt-request.json")],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")},
    )
    save(
        root / "simulated-process-exit.json",
        {"actual_exit": completed.returncode, "scenario": "OFFLINE_FAKE_SDK_PROCESS_EXIT"},
    )
    assert completed.returncode == 91
    result = runtime(case).run()
    assert result["stop_reason"] == "UNKNOWN"
    assert not case[3].calls and not case[2].calls


def test_successor_scan_does_not_accept_untyped_hash_or_credential(case):
    root = Path(case[0].output_root)
    for value in (
        {"code_commit_hash": "a" * 40},
        {"api_key": "not-permitted"},
        {"schema_version": "adaptive-sdk-profile/v1", "max_input_tokens": "bad"},
    ):
        with pytest.raises(ValueError):
            save(root / "rejected.json", value)
        assert not (root / "rejected.json").exists()


def test_cancel_during_science_adapter_preparation_prevents_claim(case, monkeypatch):
    from types import SimpleNamespace

    from scripts import adaptive_research as cli

    with pytest.raises(RuntimeError):
        runtime(case, fault=interrupt("science_started")).run()
    r = runtime(case)
    event = next(e for e in r.store.events() if e.kind == "CHILD_RESERVED")
    from quantos.contracts.adaptive import AdaptiveChild

    child = r.store.get(event.reference_hash, AdaptiveChild)
    job = Path(case[0].output_root) / "children" / child.content_hash / "job"

    def prepare_adapter(child):
        runtime(case).cancel()
        return SimpleNamespace(execute=lambda _: pytest.fail("cancelled science must not execute"))

    monkeypatch.setattr(
        cli, "AdaptiveExecutionPort", lambda _: SimpleNamespace(adapter=prepare_adapter)
    )
    with pytest.raises(TimeoutError, match="during input preparation"):
        cli._execute_science_once(case[0], child, job)
    assert not (job / "science-claim.json").exists()


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_inputs_are_verified_and_limits_rechecked_before_sdk(case, action):
    def verify_inputs():
        if action == "reject":
            raise ArtifactIntegrityError("frozen data original invalid")
        runtime(case).cancel()

    case[2].verify_inputs = verify_inputs
    if action == "reject":
        with pytest.raises(ArtifactIntegrityError, match="original invalid"):
            runtime(case).run()
    else:
        assert runtime(case).run()["stop_reason"] == "CANCELLED"
    assert not case[3].calls and not case[2].calls
