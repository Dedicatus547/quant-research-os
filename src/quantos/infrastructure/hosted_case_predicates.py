"""Mechanical scenario predicates over verified original management observations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedCampaignStatus,
    HostedResearchBudgetFact,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_business_verification import (
    verify_hosted_business_root,
    verify_q11_research_predicate,
)
from quantos.infrastructure.hosted_qualification_sources import (
    HostedVerifiedSources,
    verify_original_live_source,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, read_relative


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def verify_q01(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    _require(len(case.roots) == 2, "Q01 requires both original authority snapshots")
    observations: list[tuple[bytes, dict[str, object]]] = []
    for path in case.evidence_paths:
        data = read_relative(bundle, path)
        try:
            payload = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        if payload.get("schema_version") == "hosted-manager-suspend-restart/v1":
            observations.append((data, payload))
    _require(len(observations) == 1, "Q01 original restart observation is missing or ambiguous")
    data, fact = observations[0]
    _require(
        fact.get("deployment_profile_hash") == sources.deployment.profile.content_hash,
        "Q01 restart deployment differs",
    )
    before = HostedRawInventory.model_validate(fact["before_inventory"])
    after = HostedRawInventory.model_validate(fact["after_inventory"])
    _require(before == after, "Q01 readonly queries mutated authority")
    for root in case.roots:
        raw = read_relative(bundle, root.raw_inventory_path)
        _require(HostedRawInventory.model_validate_json(raw) == before, "Q01 snapshots differ")
    root = case.roots[0]
    state = HostedProtocolStore(bundle / root.logical_path / "protocol").snapshot(
        root.campaign_hash, recover=False
    )
    _require(len(state.requests) == 1, "Q01 lacks exactly one request")
    request = state.requests[0]
    pending = fact["pending_before"]
    _require(isinstance(pending, dict), "Q01 pending identity is absent")
    pending_object = cast(dict[str, object], pending)
    if pending_object.get("schema_version") == "hosted-agent-request/v1":
        _require(HostedAgentRequest.model_validate(pending) == request, "Q01 pending bytes changed")
    else:
        summary = pending_object
        _require(
            set(summary) == {"status", "campaign_hash", "request_hash", "expires_at"}
            and summary.get("status") == "PENDING"
            and summary.get("campaign_hash") == request.campaign_hash
            and summary.get("request_hash") == request.content_hash
            and isinstance(summary.get("expires_at"), str)
            and datetime.fromisoformat(cast(str, summary["expires_at"])) == request.expires_at,
            "Q01 pending identity differs from original request bytes",
        )
    _require(
        state.spec == sources.deployment.spec
        and state.requests == (request,)
        and state.budget.used_requests == 1
        and state.budget.used_unique_submissions == 0
        and all(
            receipt.outcome == "EXHAUSTED"
            and receipt.observed_bytes == 0
            and receipt.submission_bytes_hash is None
            and receipt.observed_prefix_hash is None
            and receipt.budget_before_hash == receipt.budget_after_hash
            for receipt in state.receipts
        )
        and not state.terminals,
        "Q01 suspension request/reservation differs",
    )
    research = tuple(
        HostedResearchBudgetFact.model_validate_json(raw)
        for raw in state.artifacts.values()
        if strict_json_object(raw, max_bytes=16_777_216).get("schema_version")
        == "hosted-research-budget-fact/v1"
    )
    _require(
        len(research) == 1
        and research[0].phase == "INITIAL"
        and research[0].used_trials == 0
        and research[0].used_executions == 0
        and research[0].used_compute_units == 0,
        "Q01 deterministic business was charged while suspended",
    )
    queries = fact.get("queries")
    _require(
        isinstance(queries, list) and len(cast(list[object], queries)) == 6,
        "Q01 repeated query sequence absent",
    )
    statuses: list[HostedCampaignStatus] = []
    for index, query in enumerate(cast(list[object], queries)):
        if index % 3 == 0:
            _require(query == pending, "Q01 pending bytes changed")
        else:
            status = HostedCampaignStatus.model_validate(query)
            _require(
                status.state == "WAITING_FOR_AGENT"
                and status.report_hash is None
                and status.protocol.request_hash == request.content_hash
                and status.hosted_spec_hash == state.spec.content_hash
                and status.protocol.budget_hash == state.budget.content_hash
                and status.protocol.journal_head_hash == state.journal_head_hash
                and status.research_budget_hash == research[0].content_hash,
                "Q01 status/resume changed suspended bindings",
            )
            statuses.append(status)
    _require(all(status == statuses[0] for status in statuses), "Q01 statuses differ")
    before_pid, after_pid = fact.get("before_wrapper_pid"), fact.get("after_wrapper_pid")
    _require(
        type(before_pid) is int and type(after_pid) is int and before_pid != after_pid,
        "Q01 did not restart in a different managed process",
    )
    observed: set[int] = set()
    for path in case.evidence_paths:
        source = sources.files[path].source_path
        if source.startswith("evidence/service-start-"):
            start = strict_json_object(read_relative(bundle, path), max_bytes=65536)
            child = start.get("manager_child_observation")
            if isinstance(child, dict):
                child_fact = cast(dict[str, object], child)
                if type(child_fact.get("wrapper_pid")) is int:
                    observed.add(cast(int, child_fact["wrapper_pid"]))
    _require(
        before_pid in observed and after_pid in observed, "Q01 real child origins were not exported"
    )
    return (sha256_bytes(data), request.content_hash, research[0].content_hash)


def verify_q11(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    _require(len(case.roots) == 1, "Q11 requires one complete live authority")
    root = case.roots[0]
    inventory = HostedRawInventory.model_validate_json(
        read_relative(bundle, root.raw_inventory_path)
    )
    _require(
        sources.root_origin(root, inventory) == sources.deployment.paths.authority,
        "Q11 root is not the original live authority",
    )
    checked = set(verify_original_live_source(sources))
    _require(
        checked <= {item.sha256 for item in sources.files.values()},
        "Q11 original model sources were not fully exported",
    )
    facts = verify_hosted_business_root(
        bundle / root.logical_path,
        sources.deployment.bundle,
        deployment_profile_hash=sources.deployment.profile.content_hash,
        input_root=sources.deployment.root / "inputs",
        provenance_workspace=sources.deployment.paths.provenance,
    )
    verify_q11_research_predicate(facts)
    checked.update(facts.artifact_hashes)
    return tuple(sorted(checked))
