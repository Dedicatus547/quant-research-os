"""Verify known malformed proposal trials with the existing native business verifier."""

from __future__ import annotations

from pathlib import Path

from quantos.contracts.agent import CampaignSegment
from quantos.contracts.base import sha256_bytes
from quantos.contracts.campaign import CampaignTrial, TrialOutcome
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import HostedQualificationFile
from quantos.contracts.ledger import ResearchLedgerEventV2
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)


def verify_business_admission_fixture(
    before_root: Path,
    after_root: Path,
    request: HostedAgentRequest,
    submitted: bytes,
    receipt_hash: str,
    report_hash: object,
    cancellation_hash: object,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    """Transport acceptance must resolve to one schema-invalid trial and zero execution."""
    before_raw, after_raw = raw_inventory(before_root), raw_inventory(after_root)
    for root in (before_root, after_root):
        verify_protocol_root(root / "protocol", request.campaign_hash)
    before = HostedProtocolStore(before_root / "protocol").snapshot(
        request.campaign_hash, recover=False
    )
    after = HostedProtocolStore(after_root / "protocol").snapshot(
        request.campaign_hash, recover=False
    )
    original_files = {item.logical_path: item for item in after_raw.files}
    if any(original_files.get(item.logical_path) != item for item in before_raw.files):
        raise HostedQualificationError("business fixture replaced original authority")
    receipt = after.accepted_receipt(request.content_hash)
    if (
        before.accepted_receipt(request.content_hash) is not None
        or receipt is None
        or receipt.content_hash != receipt_hash
        or receipt.accepted_exchange_hash is None
    ):
        raise HostedQualificationError("business fixture has no unique accepted handoff")
    from quantos.contracts.hosted import HostedAgentExchange

    exchange = after.artifact(receipt.accepted_exchange_hash, HostedAgentExchange)
    response = after.artifact(exchange.response_hash, HostedAgentResponse)
    if response.canonical_bytes() != submitted:
        raise HostedQualificationError("business fixture accepted different proposal bytes")
    deployment = sources.deployment
    if report_hash is not None:
        raise HostedQualificationError("Q04 admission fixtures must retain the native checkpoint")
    from quantos.infrastructure.hosted_admission_checkpoint import (
        verify_native_admission_checkpoint,
    )

    trial, budget, event_hashes = verify_native_admission_checkpoint(after_root, request, sources)
    artifact_hashes = tuple(after.artifacts)
    candidate = request.business_request.candidate_options[0]
    checks = {
        "TRIAL_CANDIDATE": trial.candidate_hash == candidate.content_hash,
        "TRIAL_SCHEMA_INVALID": trial.outcome == TrialOutcome.SCHEMA_INVALID,
        "ONE_TRIAL": budget.used_trials == 1,
        "ZERO_EXECUTION": budget.used_executions == 0,
        "ZERO_COMPUTE": budget.used_compute_units == 0,
        "VALIDATION_SEGMENT_CHARGE": budget.used_validation_rounds
        == int(trial.segment == CampaignSegment.VALIDATION),
        "BUDGET_CANDIDATE": budget.candidate_hashes == (candidate.content_hash,),
        "FROZEN_SPEC": before.spec == after.spec,
        "ORIGINAL_REQUEST": after.requests[:1] == (request,),
        "ONE_SUBMISSION": after.budget.used_unique_submissions == 1,
    }
    for name, satisfied in checks.items():
        if not satisfied:
            raise HostedQualificationError("business admission accounting differs: " + name)
    if len(after.requests) == 2:
        terminal = after.terminal(after.requests[1].content_hash)
        if (
            terminal is None
            or terminal.outcome != "CANCELLED"
            or terminal.content_hash != cancellation_hash
        ):
            raise HostedQualificationError("business fixture final cancellation is unbound")
    elif len(after.requests) != 1 or cancellation_hash is not None:
        raise HostedQualificationError("business fixture issued unexpected requests")
    # A valid referenced trial is insufficient if unrelated files were added.
    # Attribute the full raw delta to protocol publication, the verified event
    # chain, and the native Ledger node for the invalid trial.
    expected = {item.logical_path: item for item in before_raw.files}

    def include(path: str, data: bytes) -> None:
        item = HostedQualificationFile(
            logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        if expected.get(path, item) != item:
            raise HostedQualificationError("business admission replaced a published file")
        expected[path] = item

    if after.journal[: len(before.journal)] != before.journal:
        raise HostedQualificationError("business admission replaced protocol history")
    for entry in after.journal[len(before.journal) :]:
        include(
            f"protocol/campaigns/{request.campaign_hash}/journal/{entry.sequence:08d}-{entry.content_hash}.json",
            entry.canonical_bytes(),
        )
        for publication in entry.publications:
            include(
                f"protocol/campaigns/{request.campaign_hash}/objects/{publication.artifact_hash}.json",
                publication.canonical_json.encode(),
            )
    runtime = f"business/{request.campaign_hash}"
    expected_nodes: set[str] = set()
    for sequence, digest in enumerate(event_hashes, 1):
        path = f"{runtime}/campaign-events/{sequence:08d}-sha256-{digest}.json"
        data = read_relative(after_root, path)
        if sha256_bytes(data) != digest:
            raise HostedQualificationError("business admission event bytes differ")
        include(path, data)
        payload = strict_json_object(data, max_bytes=16_777_216)
        event_trial = payload.get("trial")
        if event_trial is not None:
            if CampaignTrial.model_validate(event_trial) != trial:
                raise HostedQualificationError("business admission event trial differs")
            expected_nodes.add(f"campaign-trial-{digest}")
    objects = {trial.content_hash: trial.canonical_bytes()}
    observed_nodes: set[str] = set()
    for item in after_raw.files:
        if item.logical_path in expected or not item.logical_path.startswith(
            runtime + "/ledger/events/"
        ):
            continue
        data = read_relative(after_root, item.logical_path)
        event = ResearchLedgerEventV2.model_validate_json(data)
        reference = event.object_ref
        if (
            event.node_id not in expected_nodes
            or event.node_id in observed_nodes
            or event.ledger_id != deployment.bundle.ledger_id
            or reference.object_hash not in objects
            or reference.source_domain != "quantos-autonomous"
            or reference.media_type != "application/json"
            or reference.campaign_hash != request.campaign_hash
            or reference.access.value != "CAMPAIGN_INTERNAL"
            or data != event.canonical_bytes()
            or item.logical_path
            != (
                f"{runtime}/ledger/events/{event.ledger_id}/"
                f"{event.sequence:020d}-{event.event_id}.json"
            )
        ):
            raise HostedQualificationError("business admission added an unrelated Ledger node")
        observed_nodes.add(event.node_id)
        include(item.logical_path, data)
        include(
            f"{runtime}/ledger/objects/quantos-autonomous/sha256-{reference.object_hash}.json",
            objects[reference.object_hash],
        )
    if observed_nodes != expected_nodes or expected != original_files:
        raise HostedQualificationError("business admission has an unattributed raw file delta")
    verify_raw_inventory(before_root, before_raw)
    verify_raw_inventory(after_root, after_raw)
    return tuple(
        sorted(
            {
                *artifact_hashes,
                receipt_hash,
                before_raw.content_hash,
                after_raw.content_hash,
            }
        )
    )
