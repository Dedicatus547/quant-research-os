"""Management loop over the existing SDK/protocol state machines; no research logic."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from quantos.artifacts.store import ArtifactIntegrityError, confined_regular_file
from quantos.contracts.agent import AgentRunManifestV3

TERMINAL = frozenset({"COMPLETED", "EXHAUSTED", "EXPIRED", "CANCELLED", "RECOVERY_REQUIRED"})


def runtime_summary(service: Any, producer: Any, spec: Any, reason: str) -> dict[str, Any]:
    snapshot = service.protocol.store.snapshot(spec.campaign_hash)
    facts = service.verify_research_facts(snapshot)
    state = service.status(spec.campaign_hash)
    report = facts.reports[-1] if facts.reports else None
    pending = service.pending(spec.campaign_hash)
    observed = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    missing_usage: list[str] = []
    for request in snapshot.requests:
        path = producer.root / spec.campaign_hash / request.content_hash / "agent-run-manifest.json"
        if not path.exists():
            missing_usage.append(request.content_hash)
            continue
        manifest = AgentRunManifestV3.model_validate_json(
            confined_regular_file(path.parent, path.name).read_bytes()
        )
        for name in observed:
            observed[name] += getattr(manifest.aggregate_usage, name)
    return {
        "schema_version": "agent-runtime-bounded-summary/v1",
        "campaign_hash": spec.campaign_hash,
        "spec_hash": spec.content_hash,
        "engineering_state": state.state,
        "stop_reason": reason,
        "research_run_status": report.research_run_status if report else "NOT_EVALUATED",
        "research_verdict": report.research_verdict if report else "NOT_EVALUATED",
        "qualification": "NOT_QUALIFIED",
        "report_hash": state.report_hash,
        "research_budget": facts.budgets[-1].model_dump(mode="json") if facts.budgets else None,
        "protocol_budget": snapshot.budget.model_dump(mode="json"),
        "launch_intents": len(
            tuple((producer.root / spec.campaign_hash).glob("*/launch-intent.json"))
        ),
        "sdk_observed_usage": observed,
        "requests_without_usage_manifest": missing_usage,
        "billing_limit": "REQUEST_OBSERVATION_ONLY_NOT_PROVIDER_BILLING_CAP",
        "pending_request_hash": pending.content_hash if pending else None,
        "producer_state": producer.status(pending, spec) if pending else None,
        "execution_result_hashes": sorted(
            {step.execution_result_hash for step in facts.steps if step.execution_result_hash}
        ),
        "originals": {
            "protocol_root": str(service.protocol.store.root),
            "producer_root": str(producer.root),
        },
    }


def reconcile_only(service: Any, spec: Any) -> Any:
    """Settle existing STARTED receipts; never reserve/dispatch fresh scientific work."""
    snapshot = service.protocol.store.snapshot(spec.campaign_hash)
    facts = service.verify_research_facts(snapshot)
    latest = {step.request_hash: step for step in facts.steps}
    # Refuse before resume can write STARTED or reserve a new trial.
    for request in snapshot.requests:
        if snapshot.accepted_receipt(request.content_hash) is not None:
            step = latest.get(request.content_hash)
            if step is None or (step.phase == "PREPARED" and step.execution_request is not None):
                raise ArtifactIntegrityError("receipt-only reconciliation would start fresh work")
    execution = service._registered(spec.campaign_hash).orchestrator.execution_port

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise ArtifactIntegrityError("receipt-only reconciliation forbids fresh execution")

    with patch.object(execution, "execute", forbidden):
        for step in latest.values():
            if step.phase == "COMPLETED" and step.execution_request is not None:
                result = execution.verified_completed_execution(step.execution_request)
                if result is None or result.content_hash != step.execution_result_hash:
                    raise ArtifactIntegrityError("completed execution receipt differs")
        return service.resume(spec.campaign_hash)


def run_bounded(
    service: Any,
    producer: Any,
    spec: Any,
    *,
    step: Callable[[], Any],
    checkpoint: Callable[[dict[str, Any]], None],
    clock_check: Callable[[], None],
) -> dict[str, Any]:
    """One bounded pass; UNKNOWN/FAILED/no progress stop without retry or reissue."""
    clock_check()
    state = service.start(spec.content_hash)
    checkpoint(runtime_summary(service, producer, spec, "STARTED"))
    for _ in range(spec.sdk_profile.max_launches + 1):
        clock_check()
        if state.state in TERMINAL:
            break
        pending = service.pending(spec.campaign_hash)
        if pending is not None:
            producer_state = producer.status(pending, spec)
            if producer_state in {"UNKNOWN", "FAILED"}:
                result = runtime_summary(service, producer, spec, producer_state)
                checkpoint(result)
                return result
        before = service.protocol.store.snapshot(spec.campaign_hash).journal
        state = step()
        result = runtime_summary(service, producer, spec, "STEP_COMPLETED")
        checkpoint(result)
        after = service.protocol.store.snapshot(spec.campaign_hash).journal
        if before == after and state.state not in TERMINAL:
            result["stop_reason"] = "NO_PROGRESS"
            checkpoint(result)
            return result
    reason = state.reason or state.state if state.state in TERMINAL else "STEP_BOUND"
    result = runtime_summary(service, producer, spec, reason)
    checkpoint(result)
    return result
