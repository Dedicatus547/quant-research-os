"""Read-only observation of retained adaptive evidence; never recovery or qualification."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from quantos.application.adaptive_execution import AdaptiveExecutionPort, freeze_child
from quantos.application.adaptive_feedback import build_feedback
from quantos.application.adaptive_runtime import AdaptiveRuntime
from quantos.application.adaptive_sdk import AdaptiveSdkProducer
from quantos.application.adaptive_store import AdaptiveStore, contract, read, save
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.autonomous_execution import require_durable_execution_root
from quantos.application.enumeration import structural_expression_hash
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.adaptive import (
    AdaptiveChild,
    AdaptiveDecision,
    AdaptiveDecisionRequest,
    AdaptiveResearchSpec,
)
from quantos.contracts.adaptive_feedback import AdaptiveFeedback
from quantos.contracts.autonomous import AutonomousExecutionFailureEvidence
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.status import RunStatus, ValidationVerdict
from quantos.contracts.validation import ValidationGateId
from quantos.validation import verify_validation_report


def _json(path: Path) -> dict[str, Any]:
    return json.loads(read(path))


def _identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactIntegrityError("closeout input must be a regular file")
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _prompt_echo(provider: list[dict[str, Any]], expected: str) -> bool:
    def turn_key(event: dict[str, Any]) -> tuple[Any, Any]:
        payload = event.get("payload", {})
        return payload.get("thread_id"), payload.get("turn", {}).get("id")

    starts = [turn_key(e) for e in provider if e.get("method") == "turn/started"]
    ends = [turn_key(e) for e in provider if e.get("method") == "turn/completed"]
    if len(starts) != 1 or starts != ends or not all(starts[0]):
        raise ArtifactIntegrityError("provider turn chronology is ambiguous")
    matched = False
    for event in provider:
        if event.get("method") not in {"item/started", "item/completed"}:
            continue
        item = event.get("payload", {}).get("item", {})
        if item.get("type") != "userMessage":
            continue
        content = item.get("content", [])
        if (
            isinstance(content, list)
            and content
            and all(x.get("type") == "text" for x in cast(list[dict[str, Any]], content))
            and "".join(x.get("text", "") for x in cast(list[dict[str, Any]], content)) == expected
        ):
            payload = event["payload"]
            if (payload.get("thread_id"), payload.get("turn_id")) != starts[0]:
                raise ArtifactIntegrityError("provider prompt echo belongs to another turn/thread")
            matched = True
    return matched


class _ReadOnlyFeedbackAdapter:
    """Reuse feedback predicates while selecting the existing inspection boundary."""

    def __init__(self, adapter: Any):
        self.adapter = adapter
        self.request = None
        self.outcome = None

    def verified_completed_execution(self, request: Any) -> Any:
        if self.request != request:
            self.outcome = self.adapter.inspect_completed_execution(request)
            self.request = request
        return self.outcome

    def verify_validation_report(self, digest: str) -> Any:
        if self.outcome is None or self.outcome.validation_report_hash != digest:
            raise ArtifactIntegrityError("report lacks inspected receipt")
        return verify_validation_report(
            self.adapter.output_root / "validation" / f"sha256-{digest}"
        )

    def verify_execution_failure(self, digest: str) -> Any:
        if self.outcome is None or digest not in self.outcome.evidence_hashes:
            raise ArtifactIntegrityError("failure lacks inspected receipt")
        path = self.adapter.output_root / "execution-failures" / f"sha256-{digest}.json"
        if not path.exists():
            return None
        evidence = contract(path, AutonomousExecutionFailureEvidence)
        if evidence.content_hash != digest:
            raise ArtifactIntegrityError("failure original identity differs")
        return evidence


def _refs(primary: str, secondary: str | None) -> list[str]:
    return [primary, secondary] if secondary is not None else [primary]


def _chain_delivered(
    observations: dict[str, dict[str, Any]],
    budget_terminated: bool,
    completed_count: int,
    started_count: int,
) -> bool:
    terminal = observations["normal_stop"]["status"] == "OBSERVED" or (
        budget_terminated and completed_count == started_count
    )
    return terminal and observations["task_delivery_exit"]["status"] == "OBSERVED"


def _verify_exits(
    spec: AdaptiveResearchSpec,
    root: Path,
    exit_paths: dict[str, Path],
    inventory: Path | None,
    observations: dict[str, dict[str, Any]],
    external_exits: dict[str, Any],
    observe: Callable[[str, list[str]], None],
) -> None:
    for name, path in exit_paths.items():
        if not path.exists():
            external_exits[name] = None
            continue
        record = _json(path)
        external_exits[name] = {"original": _identity(path), "record": record}
        if record.get("task_hash", spec.content_hash) != spec.content_hash:
            raise ArtifactIntegrityError("external process exit belongs to another task")
        if name == "observer":
            if record.get("wait_observed") is True and record.get("actual_exit") == 0:
                observe("observer_independent_exit", [str(path)])
        elif name == "operator":
            prelaunch = _json(path.parent / "prelaunch.json")
            if (
                record.get("task_hash") != spec.content_hash
                or prelaunch.get("task_hash") != spec.content_hash
            ):
                raise ArtifactIntegrityError("operator exit/prelaunch task binding differs")
            if (
                record.get("actual_exit") == 0
                and record.get("observed_by") == "PARENT_SUBPROCESS_WAIT"
            ):
                observe(
                    "operator_independent_exit",
                    [str(path), str(path.parent / "prelaunch.json")],
                )
        elif name == "guard":
            operator = exit_paths.get("operator")
            if operator is None:
                raise FileNotFoundError("guard requires the bound operator prelaunch")
            operator_pre = _json(operator.parent / "prelaunch.json")
            argv = operator_pre["argv"]
            command = argv[argv.index("--") + 1 :]
            if "--operator-operation" in command:
                operation = command[command.index("--operator-operation") + 1]
                if Path(operation) != operator.parent.resolve():
                    raise ArtifactIntegrityError("guard belongs to a different operator operation")
            elif inventory is None or len(list((root / "operator").glob("operation-*"))) != 1:
                raise FileNotFoundError("legacy guard lacks unique inventoried operator binding")
            guard_pre = _json(path.parent / "prelaunch.json")
            policy_digest = sha256_file(path.parent / "policy.json")
            if (
                operator_pre.get("task_hash") != spec.content_hash
                or command[command.index("--spec-sha256") + 1] != spec.content_hash
                or guard_pre.get("argv_hash") != sha256_bytes(canonical_json_bytes(command))
                or guard_pre.get("policy_hash") != policy_digest
                or record.get("policy_hash") != policy_digest
                or argv[argv.index("--policy-sha256") + 1] != policy_digest
                or guard_pre.get("expected_new_bytes") != spec.limits.storage_growth_bytes
            ):
                raise ArtifactIntegrityError("guard command, policy or reservation binding differs")
            if (
                record.get("return_code") == 0
                and record.get("execution") == "SUCCEEDED"
                and all(
                    record.get(k) is True
                    for k in ("cleanup_verified", "namespace_exit_observed", "waitpid_observed")
                )
            ):
                observe(
                    "guard_cleanup",
                    [
                        str(path),
                        str(path.parent / "prelaunch.json"),
                        str(path.parent / "policy.json"),
                    ],
                )
    for path in sorted((root / "operations").glob("*/process-exit.json")):
        if _json(path).get("actual_exit") == 0:
            observe("controller_exit", [str(path)])
    if (
        observations["operator_independent_exit"]["status"] == "OBSERVED"
        and observations["controller_exit"]["status"] == "OBSERVED"
        and observations["guard_cleanup"]["status"] == "OBSERVED"
    ):
        observe(
            "task_delivery_exit",
            observations["operator_independent_exit"]["originals"]
            + observations["controller_exit"]["originals"]
            + observations["guard_cleanup"]["originals"],
        )


def closeout_adaptive(
    spec: AdaptiveResearchSpec,
    output: Path,
    *,
    inventory: Path | None = None,
    exit_paths: dict[str, Path] | None = None,
    producer: AdaptiveSdkProducer | None = None,
    execution: AdaptiveExecutionPort | None = None,
) -> dict[str, Any]:
    """Observe a quiescent task into a separate new durable audit directory.

    An optional historical inventory is verified byte-for-byte, including its original
    denominator. The task tree is always independently inventoried before and after.
    Incomplete evidence lowers observations; corruption is reported as conflict.
    """
    root, output = Path(spec.output_root).resolve(), output.resolve()
    require_durable_execution_root(output)
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("closeout output and task input must be separate trees")
    if output.exists():
        raise ValueError("closeout requires a new output directory")
    if inventory is not None and output.is_relative_to(inventory.resolve().parent):
        raise ValueError("closeout output must be outside historical inventory tree")
    producer = producer or AdaptiveSdkProducer(spec)
    execution = execution or AdaptiveExecutionPort(spec)
    store = AdaptiveStore(spec)
    paths = set(root.rglob("*"))
    paths = {p for p in paths if p.is_file() or p.is_symlink()}
    exit_paths = exit_paths or {}
    paths.update(p.resolve() for p in exit_paths.values() if p.exists())
    for name, path in exit_paths.items():
        siblings = (
            ("prelaunch.json", "policy.json", "namespace.json")
            if name == "guard"
            else ("prelaunch.json",)
        )
        paths.update(
            path.parent / sibling for sibling in siblings if (path.parent / sibling).exists()
        )
    supplied: dict[str, Any] | None = None
    if inventory is not None:
        supplied = _json(inventory)
        paths.add(inventory.resolve())
        paths.update(Path(item["path"]) for item in supplied["files"])
    for p in paths:
        if p.resolve() == output or p.resolve().is_relative_to(output):
            raise ValueError("audit output cannot contain inventory inputs")
    before = [_identity(p) for p in sorted(paths)]
    observations: dict[str, dict[str, Any]] = {}

    def observe(name: str, refs: list[str], *, missing: str | None = None) -> None:
        item = observations.setdefault(
            name, {"status": "NOT_OBSERVED", "originals": [], "missing": []}
        )
        item["originals"] = sorted(set(item["originals"] + refs))
        if missing is None:
            item["status"] = "OBSERVED"
        elif missing not in item["missing"]:
            item["missing"].append(missing)

    names = (
        "new_proposal",
        "admission_freeze",
        "scientific_completion",
        "feedback_in_actual_input",
        "decision_after_feedback",
        "revision",
        "normal_stop",
        "budget_stop",
        "safety_block",
        "sdk_independent_exit",
        "science_independent_exit",
        "receipt",
        "complete_chain",
        "task_delivery_exit",
        "operator_independent_exit",
        "controller_exit",
        "guard_cleanup",
        "science_execution_failure",
    )
    for name in (*names, *(f"science_stage:{g.value}" for g in ValidationGateId)):
        observe(name, [], missing="No complete bound original observed")
    issues: list[dict[str, str]] = []
    summary: dict[str, Any] | None = None
    verified_feedback: dict[str, AdaptiveFeedback] = {}
    sdk_records: list[dict[str, Any]] = []
    external_exits: dict[str, Any] = {}
    stop_reason = None
    budget_terminated = False
    try:
        if supplied is not None:
            identities = {item["path"]: item for item in before}
            if len({item["path"] for item in supplied["files"]}) != len(supplied["files"]):
                raise ArtifactIntegrityError("duplicate inventory paths")
            for item in supplied["files"]:
                actual = identities[item["path"]]
                if any(actual[k] != item[k] for k in ("sha256", "bytes")):
                    raise ArtifactIntegrityError("historical inventory identity differs")
        if read(root / "spec.json") != spec.canonical_bytes():
            raise ArtifactIntegrityError("task spec original differs")
        _verify_exits(spec, root, exit_paths, inventory, observations, external_exits, observe)
        events = store.events()
        if events and (
            events[0].kind != "ACTIVATED"
            or sha256_file(root / "activation.json") != events[0].reference_hash
        ):
            raise ArtifactIntegrityError("activation identity differs")
        # status() only reads; its existing budget and cross-task predicates remain authority.
        summary = AdaptiveRuntime(spec, producer, execution).status()
        seen_events: set[tuple[str, str]] = set()
        terminal = False
        for event in events:
            identity = (event.kind, event.reference_hash)
            if (
                terminal
                or identity in seen_events
                or (event.kind == "ACTIVATED" and event.ordinal != 1)
            ):
                raise ArtifactIntegrityError("duplicate event or event after terminal stop")
            terminal = event.kind == "STOPPED"
            seen_events.add(identity)
        children: dict[str, AdaptiveChild] = {}
        started: set[str] = set()
        decisions: dict[str, tuple[AdaptiveDecision, str]] = {}
        previous: str | None = None
        requests: dict[str, AdaptiveDecisionRequest] = {}
        seen_structures = set(spec.initial_structural_hashes)
        new_decisions: set[str] = set()
        linked_next = False
        complete_science: set[str] = set()
        request_count = 0
        for event in events:
            ref = str(root / "objects" / f"{event.reference_hash}.json")
            if event.kind == "DECISION_RESERVED":
                request_count += 1
                if request_count != len(decisions) + 1:
                    raise ArtifactIntegrityError("new request precedes prior captured response")
                req = store.get(event.reference_hash, AdaptiveDecisionRequest)
                if (
                    req.task_hash != spec.content_hash
                    or req.ordinal != request_count
                    or req.previous_event_hash != event.previous_hash
                    or req.parent_proposal_hash != previous
                    or req.feedback_hashes != tuple(sorted(verified_feedback))
                ):
                    raise ArtifactIntegrityError(
                        "decision request task, chronology or feedback differs"
                    )
                payload = json.loads(req.prompt.split("Context:\n", 1)[1])
                expected_feedback = [
                    {"feedback_hash": f.content_hash, "projection": f.model_dump(mode="json")}
                    for f in verified_feedback.values()
                ]
                if (
                    payload.get("task_hash") != spec.content_hash
                    or payload.get("context") != spec.context
                    or payload.get("source_hashes") != list(spec.context_source_hashes)
                    or payload.get("parent_proposal_hash") != previous
                    or payload.get("feedback") != expected_feedback
                ):
                    raise ArtifactIntegrityError(
                        "actual request feedback/context projection differs"
                    )
                requests[req.content_hash] = req
            elif event.kind == "DECISION_CAPTURED":
                capture = _json(Path(ref))
                if sha256_file(Path(ref)) != event.reference_hash:
                    raise ArtifactIntegrityError("capture object identity differs")
                req = requests[capture["request_hash"]]
                if req.parent_proposal_hash != previous:
                    raise ArtifactIntegrityError("capture parent decision chronology differs")
                if req.content_hash in {value[1] for value in decisions.values()}:
                    raise ArtifactIntegrityError("duplicate captured request")
                decision, response_hash = producer.verify_capture(req)
                if (
                    decision.content_hash != capture["decision_hash"]
                    or response_hash != capture["response_hash"]
                    or store.get(decision.content_hash, AdaptiveDecision) != decision
                    or decision.parent_proposal_hash != req.parent_proposal_hash
                    or decision.feedback_hashes != req.feedback_hashes
                    or not decision.source_hashes
                    or not set(decision.source_hashes) <= set(spec.context_source_hashes)
                ):
                    raise ArtifactIntegrityError("decision capture or source bindings differ")
                d = producer.directory(req)
                provider = [
                    json.loads(line)
                    for line in read(
                        d / "provider-transcript.jsonl", spec.sdk.max_transcript_bytes
                    ).splitlines()
                    if line.strip()
                ]
                echo = _prompt_echo(provider, req.prompt)
                sdk_exit = (
                    _json(d / "sdk-process-exit.json")
                    if (d / "sdk-process-exit.json").exists()
                    else {}
                )
                exit_ok = (
                    sdk_exit.get("spawned") is True
                    and sdk_exit.get("wait_observed") is True
                    and sdk_exit.get("return_code") == 0
                )
                refs = [ref, str(d / "response.json"), str(d / "provider-transcript.jsonl")]
                sdk_records.append(
                    {
                        "request_hash": req.content_hash,
                        "response_hash": response_hash,
                        "prompt_echo": echo,
                        "independent_exit": sdk_exit or None,
                        "usage": _json(d / "response.json")["usage"],
                    }
                )
                if exit_ok:
                    observe("sdk_independent_exit", [str(d / "sdk-process-exit.json")])
                real = echo and exit_ok
                decisions[decision.content_hash] = (decision, req.content_hash)
                previous = decision.content_hash
                if req.feedback_hashes and real:
                    observe("feedback_in_actual_input", refs + list(req.feedback_hashes))
                    # Require a bound result in the rationale, beyond copied binding fields.
                    reasoning = decision.rationale.lower()
                    bound = any(
                        any(
                            re.search(
                                r"(?<![a-z0-9_])" + re.escape(value.lower()) + r"(?![a-z0-9_])",
                                reasoning,
                            )
                            is not None
                            for value in (
                                f.content_hash,
                                f.outcome.value,
                                f.verdict.value,
                                *(g.gate_id.value for g in f.gates),
                            )
                        )
                        for f in verified_feedback.values()
                    )
                    if bound:
                        observe("decision_after_feedback", refs)
                        linked_next = True
                if decision.expression is not None:
                    structural = structural_expression_hash(decision.expression)
                    if structural not in seen_structures and real:
                        observe("new_proposal", refs)
                        new_decisions.add(decision.content_hash)
                        if req.feedback_hashes and linked_next:
                            observe("revision", refs)
                    seen_structures.add(structural)
                stop_reason = "MODEL_STOP" if decision.action == "STOP" and real else None
            elif event.kind == "CHILD_RESERVED":
                child = store.get(event.reference_hash, AdaptiveChild)
                if child.decision_hash in {c.decision_hash for c in children.values()}:
                    raise ArtifactIntegrityError("one decision cannot reserve multiple children")
                decision, request_hash = decisions[child.decision_hash]
                capture = next(
                    _json(root / "objects" / f"{e.reference_hash}.json")
                    for e in events
                    if e.kind == "DECISION_CAPTURED"
                    and _json(root / "objects" / f"{e.reference_hash}.json")["request_hash"]
                    == request_hash
                )
                if (
                    child
                    != freeze_child(spec, decision, capture["response_hash"], len(children) + 1)
                    or event.units != child.quote_units
                ):
                    raise ArtifactIntegrityError("admission/frozen child differs")
                children[child.content_hash] = child
                observe("admission_freeze", [ref])
            elif event.kind == "SCIENCE_STARTED":
                if event.reference_hash not in children or event.reference_hash in started:
                    raise ArtifactIntegrityError("science start without unique frozen child")
                if event.units != children[event.reference_hash].quote_units:
                    raise ArtifactIntegrityError("science launch reservation units differ")
                started.add(event.reference_hash)
            elif event.kind == "SCIENCE_SETTLED":
                retained = store.get(event.reference_hash, AdaptiveFeedback)
                child = children[retained.child_hash]
                if retained.child_hash not in started:
                    raise ArtifactIntegrityError("science settlement without start")
                adapter = _ReadOnlyFeedbackAdapter(execution.adapter(child))
                outcome = adapter.verified_completed_execution(child.request)
                if outcome is None:
                    raise FileNotFoundError("saved science receipt missing")
                actual = build_feedback(
                    task_hash=spec.content_hash,
                    child_hash=child.content_hash,
                    request=child.request,
                    outcome=outcome,
                    adapter=cast(Any, adapter),
                    process_exit=execution.process_exit(child),
                )
                if actual != retained:
                    raise ArtifactIntegrityError(
                        "feedback differs from inspected scientific originals"
                    )
                verified_feedback[retained.content_hash] = retained
                observe("receipt", [ref, retained.receipt_hash])
                job = root / "children" / child.content_hash / "job"
                process = (
                    _json(job / "process-exit.json") if (job / "process-exit.json").exists() else {}
                )
                child_exit = (
                    _json(job / "child-exit.json") if (job / "child-exit.json").exists() else {}
                )
                exit_ok = (
                    process.get("outcome") == "EXITED"
                    and process.get("exit_code") == 0
                    and child_exit.get("exit_code") == 0
                    and child_exit.get("request_hash") == child.request.content_hash
                    and child_exit.get("outcome_hash") == outcome.content_hash
                )
                if exit_ok:
                    observe(
                        "science_independent_exit",
                        [str(job / "process-exit.json"), str(job / "child-exit.json")],
                    )
                    valid_science = (
                        retained.run_status is RunStatus.SUCCEEDED
                        and retained.verdict in {ValidationVerdict.PASS, ValidationVerdict.REJECT}
                    )
                    if valid_science:
                        observe("scientific_completion", [ref, retained.receipt_hash])
                    else:
                        observe("science_execution_failure", [ref, retained.receipt_hash])
                    if valid_science and child.decision_hash in new_decisions:
                        complete_science.add(retained.content_hash)
                    if retained.outcome.value == "PIT_REJECT":
                        observe(
                            "science_stage:G2_PIT_LINEAGE",
                            _refs(ref, retained.failure_evidence_hash),
                        )
                    for gate in retained.gates:
                        if gate.verdict is not ValidationVerdict.NOT_EVALUATED:
                            observe(
                                f"science_stage:{gate.gate_id.value}",
                                _refs(ref, retained.validation_report_hash),
                            )
            elif event.kind == "STOPPED":
                stop = _json(Path(ref))
                if sha256_file(Path(ref)) != event.reference_hash:
                    raise ArtifactIntegrityError("stop object identity differs")
                if stop.get("reason") == "MODEL_STOP" and stop_reason == "MODEL_STOP":
                    observe("normal_stop", [ref])
                elif stop.get("reason") == "DECISION_BUDGET_EXHAUSTED":
                    budget_terminated = True
                    observe("budget_stop", [ref])
                elif stop.get("reason") not in {None, "MODEL_STOP"}:
                    observe("safety_block", [ref])
        if (
            complete_science
            and linked_next
            and _chain_delivered(
                observations, budget_terminated, len(complete_science), len(started)
            )
        ):
            observe("complete_chain", sorted(complete_science))
    except (FileNotFoundError, KeyError) as error:
        issues.append({"kind": "MISSING_EVIDENCE", "detail": type(error).__name__})
    except (
        ValueError,
        TypeError,
        IndexError,
        ArtifactIntegrityError,
        AutonomousOrchestrationError,
    ) as error:
        issues.append({"kind": "CONFLICTING_EVIDENCE", "detail": type(error).__name__})
        for item in observations.values():
            item["status"] = "CONFLICTING_EVIDENCE"
    after_paths = {p for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    after = [_identity(p) for p in sorted(paths)]
    stable = before == after and after_paths == {p for p in paths if p.is_relative_to(root)}
    if not stable:
        issues.append({"kind": "CONFLICTING_EVIDENCE", "detail": "INPUT_INVENTORY_CHANGED"})
        for item in observations.values():
            item["status"] = "CONFLICTING_EVIDENCE"
    for item in observations.values():
        if item["status"] == "OBSERVED":
            item["missing"] = []
    result = {
        "schema_version": "adaptive-readonly-closeout/v1",
        "task_hash": spec.content_hash,
        "originating_code_commit": spec.design.bindings.code_commit_hash,
        "verifier_sources": [
            _identity(Path(__file__).with_name(name))
            for name in (
                "adaptive_closeout.py",
                "adaptive_sdk.py",
                "adaptive_feedback.py",
                "adaptive_runtime.py",
                "adaptive_execution.py",
                "adaptive_store.py",
            )
        ],
        "verifier_lockfile": _identity(Path(__file__).resolve().parents[3] / "uv.lock")
        if (Path(__file__).resolve().parents[3] / "uv.lock").exists()
        else None,
        "qualification": "NOT_QUALIFIED",
        "input_stable": stable,
        "observations": observations,
        "issues": issues,
        "budget_and_events": summary,
        "sdk_captures": sdk_records,
        "independent_exits": external_exits,
        "unknown_usage": None,
        "cash_or_subscription_balance": None,
        "scope": "Retained originals; offline fixtures do not prove real provider/science behavior",
        "not_proven": [
            "FEEDBACK_CAUSAL_QUALITY_IMPROVEMENT",
            "LONG_TERM_RELIABILITY",
            "HISTORICAL_VENDOR_VINTAGE_PIT",
        ],
        "input_inventory_hash": sha256_bytes(canonical_json_bytes(before)),
    }
    save(output / "input-inventory.json", {"files": before, "output_excluded": True})
    save(output / "result.json", result)
    report = (
        "# Adaptive read-only closeout\n\nQualification: NOT_QUALIFIED\n\n"
        + "\n".join(f"- {name}: {item['status']}" for name, item in observations.items())
        + "\n\nSee result.json for original identities and missing evidence.\n"
    )
    save(output / "report.md", report.encode())
    return result
