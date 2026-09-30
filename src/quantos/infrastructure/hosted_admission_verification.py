"""Verify known malformed proposal trials with the existing native business verifier."""

from __future__ import annotations

from pathlib import Path

from quantos.contracts.agent import CampaignSegment
from quantos.contracts.campaign import CampaignTrial, TrialOutcome
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostedResearchBudgetFact,
)
from quantos.infrastructure.hosted_business_verification import verify_hosted_business_root
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
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
    facts = verify_hosted_business_root(
        after_root,
        deployment.bundle,
        deployment_profile_hash=deployment.profile.content_hash,
        input_root=deployment.paths.offline_inputs,
        provenance_workspace=deployment.paths.provenance,
    )
    if (
        facts.report.content_hash != report_hash
        or len(facts.report.trial_hashes) != 1
        or facts.execution_identities
        or facts.validation_reports
    ):
        raise HostedQualificationError("business fixture has execution or wrong trial denominator")
    trial = after.artifact(facts.report.trial_hashes[0], CampaignTrial)
    budget = after.artifact(facts.report.research_budget_hash, HostedResearchBudgetFact)
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
        "REPORT_CANDIDATE": facts.report.attempted_candidate_hashes == (candidate.content_hash,),
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
            or facts.report.state != "CANCELLED"
        ):
            raise HostedQualificationError("business fixture final cancellation is unbound")
    elif len(after.requests) != 1 or cancellation_hash is not None:
        raise HostedQualificationError("business fixture issued unexpected requests")
    verify_raw_inventory(before_root, before_raw)
    verify_raw_inventory(after_root, after_raw)
    return tuple(
        sorted(
            {
                *facts.artifact_hashes,
                receipt_hash,
                facts.report.content_hash,
                before_raw.content_hash,
                after_raw.content_hash,
            }
        )
    )
