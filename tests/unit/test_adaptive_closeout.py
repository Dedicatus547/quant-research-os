"""Read-only closure counterexamples, entirely offline synthetic captures."""
# ruff: noqa: F811

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_adaptive_feedback import FakeAdapter, report_fixture
from test_adaptive_runtime import Harness, Science, case, runtime  # noqa: F401

from quantos.application.adaptive_closeout import closeout_adaptive
from quantos.application.adaptive_execution import AdaptiveExecutionPort
from quantos.application.adaptive_runtime import AdaptiveRuntime
from quantos.application.adaptive_sdk import AdaptiveSdkProducer
from quantos.application.adaptive_store import AdaptiveStore, read, save
from quantos.application.agent_harness import capture_from_agent_events
from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.notification_projection import normalize_provider_events


def audit_path(spec, label):
    return Path(spec.output_root).parent / label


def test_first_stop_closeout_is_readonly_and_never_science(case, monkeypatch):
    spec, producer, science, harness, _ = case
    harness.actions = [None]
    runtime(case).run()
    before = {str(p): sha256_file(p) for p in Path(spec.output_root).rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("closeout attempted an authority mutation or external operation")

    monkeypatch.setattr(producer, "complete", forbidden)
    monkeypatch.setattr(producer, "launch", forbidden)
    monkeypatch.setattr(science, "execute", forbidden)
    monkeypatch.setattr(AdaptiveStore, "initialize", forbidden)
    monkeypatch.setattr(AdaptiveStore, "append", forbidden)
    for label in ("audit-one", "audit-two"):
        result = closeout_adaptive(
            spec, audit_path(spec, label), producer=producer, execution=science
        )
        assert result["input_stable"]
        assert result["qualification"] == "NOT_QUALIFIED"
        assert result["issues"] == []
        for name in (
            "new_proposal",
            "scientific_completion",
            "decision_after_feedback",
            "complete_chain",
        ):
            assert result["observations"][name]["status"] == "NOT_OBSERVED"
    assert before == {
        str(p): sha256_file(p) for p in Path(spec.output_root).rglob("*") if p.is_file()
    }
    assert len(harness.calls) == 1
    assert science.calls == []


@pytest.mark.parametrize(
    "damage", ["missing_response", "duplicate_event", "wrong_request_task", "missing_exit"]
)
def test_incomplete_or_conflicting_capture_never_claims_chain(case, damage):
    spec, producer, science, harness, _ = case
    harness.actions = [None]
    runtime(case).run()
    store = AdaptiveStore(spec)
    if damage == "missing_response":
        next((Path(spec.output_root) / "sdk").glob("*/response.json")).unlink()
    elif damage == "missing_exit":
        # The synthetic harness has no host exit observation; absence stays unknown.
        for path in (Path(spec.output_root) / "sdk").glob("*/sdk-process-exit.json"):
            path.unlink()
    elif damage == "duplicate_event":
        event = store.events()[1]
        store.append(event.kind, event.reference_hash, event.occurred_at)
    else:
        request_event = store.events()[1]
        path = store.root / "objects" / f"{request_event.reference_hash}.json"
        encoded = read(path).replace(spec.content_hash.encode(), b"f" * 64)
        path.write_bytes(encoded)
    result = closeout_adaptive(
        spec, audit_path(spec, "damaged"), producer=producer, execution=science
    )
    assert result["observations"]["complete_chain"]["status"] != "OBSERVED"
    assert result["unknown_usage"] is None


def test_output_cannot_be_in_input_tree(case):
    spec = case[0]
    with pytest.raises(ValueError, match="separate trees"):
        closeout_adaptive(spec, Path(spec.output_root) / "audit")


def test_historical_inventory_keeps_original_denominator(case):
    spec, producer, science, harness, _ = case
    harness.actions = [None]
    runtime(case).run()
    root = Path(spec.output_root)
    inventory = audit_path(spec, "prior") / "inventory.json"
    files = [
        {"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]
    save(inventory, {"files": files})
    result = closeout_adaptive(
        spec,
        audit_path(spec, "inventory-audit"),
        inventory=inventory,
        producer=producer,
        execution=science,
    )
    assert result["input_stable"] and not result["issues"]
    assert (
        len(
            __import__("json").loads(
                read(audit_path(spec, "inventory-audit") / "input-inventory.json")
            )["files"]
        )
        == len(files) + 1
    )


class EchoHarness(Harness):
    def execute(self, request):
        result = super().execute(request)
        provider = [json.loads(line) for line in result.provider_transcript.splitlines()]
        provider.insert(
            0,
            {
                "method": "item/completed",
                "payload": {
                    "thread_id": "foreign-thread"
                    if getattr(self, "damage", None) == "foreign_thread"
                    else "thread-test",
                    "turn_id": "foreign-turn"
                    if getattr(self, "damage", None) == "foreign_turn"
                    else "turn-test",
                    "item": {
                        "type": "userMessage",
                        "content": [{"type": "text", "text": request.prompt}],
                    },
                },
            },
        )
        for event in provider:
            item = event.get("payload", {}).get("item", {})
            if item.get("type") == "agentMessage":
                raw = json.loads(item["text"])
                raw["rationale"] = "Own task feedback REJECT justifies stopping."
                if getattr(self, "damage", None) == "bypass_rationale":
                    raw["rationale"] = "We bypass budget discussion and stop here."
                item["text"] = canonical_json_bytes(raw).decode()
        capture = capture_from_agent_events(
            normalize_provider_events(provider, thread_id="thread-test"), max_bytes=65536
        )
        attempt = replace(
            result.attempts[0],
            capture=capture,
            provider_transcript=b"".join(canonical_json_bytes(p) + b"\n" for p in provider),
            qualification_observations={
                "host_process_exit": {
                    "schema_version": "sdk-host-process-exit/v1",
                    "spawned": True,
                    "wait_observed": True,
                    "return_code": 0,
                }
            },
        )
        return replace(result, attempts=(attempt,))


class InspectAdapter(FakeAdapter):
    def inspect_completed_execution(self, request):
        if self.outcome.execution_artifact_hash != "b" * 64:
            raise ValueError("synthetic receipt original differs")
        if self.outcome.request_hash != request.content_hash:
            raise ValueError("synthetic receipt request differs")
        return self.outcome


class CompletedScience(Science):
    def __init__(self, spec, kind):
        super().__init__()
        self.spec, self.kind = spec, kind

    def execute(self, child):
        report = report_fixture("PASS" if self.kind == "pass" else "REJECT").model_copy(
            update={
                "validation_policy_hash": child.request.validation_policy_hash,
                "research_policy_hash": child.request.research_policy_hash,
                "snapshot_hash": child.request.snapshot_hash,
                "qlib_view_hash": child.request.qlib_view_hash,
            }
        )
        adapter = InspectAdapter(
            child.request,
            report=report if self.kind in {"valid", "pass"} else None,
            failure_kind=None if self.kind in {"valid", "pass"} else "EXECUTION_FAILED",
        )
        adapter.output_root = (
            Path(self.spec.output_root) / "children" / child.content_hash / "execution"
        )
        adapter.outcome = adapter.outcome.model_copy(update={"compute_seconds": child.quote_units})
        if adapter.failure is not None:
            save(
                adapter.output_root
                / "execution-failures"
                / f"sha256-{adapter.failure.content_hash}.json",
                adapter.failure,
            )
        self.adapters[child.content_hash] = adapter
        self.calls.append(child.content_hash)
        job = adapter.output_root.parent / "job"
        save(
            job / "process-exit.json",
            {
                "task_hash": self.spec.content_hash,
                "child_hash": child.content_hash,
                "request_hash": child.request.content_hash,
                "outcome": "EXITED",
                "exit_code": 0,
            },
        )
        save(
            job / "child-exit.json",
            {
                "request_hash": child.request.content_hash,
                "outcome_hash": adapter.outcome.content_hash,
                "exit_code": 0,
            },
        )
        return adapter.outcome

    def process_exit(self, child):
        return AdaptiveExecutionPort.process_exit(self, child)


def completed_chain(case, monkeypatch, kind="valid", damage=None, two_proposals=False):
    spec, _, _, _, expressions = case
    harness = EchoHarness(spec, [expressions[0], expressions[1] if two_proposals else None])
    harness.damage = damage
    producer, science = AdaptiveSdkProducer(spec, harness), CompletedScience(spec, kind)
    AdaptiveRuntime(spec, producer, science).run()
    reports = {a.report.content_hash: a.report for a in science.adapters.values() if a.report}
    monkeypatch.setattr(
        "quantos.application.adaptive_closeout.verify_validation_report",
        lambda path: reports[path.name.removeprefix("sha256-")],
    )
    root = Path(spec.output_root)
    operator = root / "operator/operation-0001"
    guard = root.parent / "synthetic-guard"
    save(guard / "policy.json", {"scope": "OFFLINE_SYNTHETIC"})
    policy_hash = sha256_file(guard / "policy.json")
    command = [
        "offline-synthetic",
        "--spec-sha256",
        spec.content_hash,
        "--operator-operation",
        str(operator),
    ]
    if damage == "legacy_double_operation":
        command = command[:-2]
        (root / "operator/operation-0002").mkdir(parents=True)
    argv = ["offline-guard", "--policy-sha256", policy_hash, "--", *command]
    save(operator / "prelaunch.json", {"task_hash": spec.content_hash, "argv": argv})
    save(
        operator / "process-exit.json",
        {"task_hash": spec.content_hash, "actual_exit": 0, "observed_by": "PARENT_SUBPROCESS_WAIT"},
    )
    save(root / "operations/offline/process-exit.json", {"actual_exit": 0})
    save(
        guard / "prelaunch.json",
        {
            "argv_hash": sha256_bytes(canonical_json_bytes(command)),
            "policy_hash": policy_hash,
            "expected_new_bytes": spec.limits.storage_growth_bytes,
        },
    )
    save(
        guard / "exit.json",
        {
            "policy_hash": policy_hash,
            "return_code": 0,
            "execution": "SUCCEEDED",
            "cleanup_verified": True,
            "namespace_exit_observed": True,
            "waitpid_observed": True,
        },
    )
    return (
        producer,
        science,
        {"operator": operator / "process-exit.json", "guard": guard / "exit.json"},
    )


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "receipt",
        "cross_task_feedback",
        "second_response",
        "scientific_exit",
        "execution_failure",
        "guard_binding",
        "legacy_double_operation",
        "foreign_thread",
        "foreign_turn",
        "bypass_rationale",
    ],
)
def test_two_step_offline_chain_requires_actual_bound_originals(case, monkeypatch, damage):
    spec = case[0]
    producer, science, exits = completed_chain(
        case,
        monkeypatch,
        "failure"
        if damage == "execution_failure"
        else "pass"
        if damage == "bypass_rationale"
        else "valid",
        damage=damage,
    )
    root = Path(spec.output_root)
    if damage == "receipt":
        adapter = next(iter(science.adapters.values()))
        adapter.outcome = adapter.outcome.model_copy(update={"execution_artifact_hash": "f" * 64})
    elif damage == "cross_task_feedback":
        event = next(e for e in AdaptiveStore(spec).events() if e.kind == "SCIENCE_SETTLED")
        path = root / "objects" / f"{event.reference_hash}.json"
        path.write_bytes(read(path).replace(spec.content_hash.encode(), b"f" * 64))
    elif damage == "second_response":
        second = sorted(
            producer.root.glob("*/request.json"), key=lambda p: json.loads(read(p))["ordinal"]
        )[1]
        (second.parent / "response.json").unlink()
    elif damage == "scientific_exit":
        next((root / "children").glob("*/job/process-exit.json")).unlink()
    elif damage == "guard_binding":
        (exits["guard"].parent / "prelaunch.json").write_bytes(
            canonical_json_bytes({"argv_hash": "f" * 64})
        )
    result = closeout_adaptive(
        spec,
        audit_path(spec, "two-step-audit"),
        producer=producer,
        execution=science,
        exit_paths=exits,
    )
    if damage is None:
        assert not result["issues"]
        assert result["observations"]["complete_chain"]["status"] == "OBSERVED"
        assert result["observations"]["revision"]["status"] == "NOT_OBSERVED"
    else:
        assert result["observations"]["complete_chain"]["status"] != "OBSERVED"
    if damage == "execution_failure":
        assert result["observations"]["science_independent_exit"]["status"] == "OBSERVED"
        assert result["observations"]["scientific_completion"]["status"] == "NOT_OBSERVED"
        assert result["observations"]["science_execution_failure"]["status"] == "OBSERVED"


def test_completed_revision_chain_can_end_at_frozen_decision_budget(case, monkeypatch):
    spec = case[0]
    producer, science, exits = completed_chain(case, monkeypatch, two_proposals=True)
    result = closeout_adaptive(
        spec,
        audit_path(spec, "budget-complete"),
        producer=producer,
        execution=science,
        exit_paths=exits,
    )
    assert not result["issues"]
    assert result["observations"]["budget_stop"]["status"] == "OBSERVED"
    assert result["observations"]["revision"]["status"] == "OBSERVED"
    assert result["observations"]["normal_stop"]["status"] == "NOT_OBSERVED"
    assert result["observations"]["complete_chain"]["status"] == "OBSERVED"
    assert len(science.calls) == 2
