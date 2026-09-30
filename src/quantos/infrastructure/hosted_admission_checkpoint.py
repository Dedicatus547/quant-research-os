"""Native, read-only admission checkpoint verification without campaign finalization."""

from __future__ import annotations

from pathlib import Path

from quantos.application.autonomous import AutonomousProposalEvidence, autonomous_trial_event_id
from quantos.contracts.campaign import CampaignTrial, ResearchCampaignEvent, TrialOutcome
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentRequest,
    HostedAgentResponse,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
    strict_json_object,
)
from quantos.infrastructure.hosted_business_verification import build_verified_business_orchestrator
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError


def verify_native_admission_checkpoint(
    authority: Path, request: HostedAgentRequest, sources: HostedVerifiedSources
) -> tuple[CampaignTrial, HostedResearchBudgetFact, tuple[str, ...]]:
    deployment = sources.deployment
    bundle = deployment.bundle
    state, orchestrator, events = build_verified_business_orchestrator(
        authority,
        bundle,
        deployment_profile_hash=deployment.profile.content_hash,
        input_root=deployment.paths.offline_inputs,
        provenance_workspace=deployment.paths.provenance,
    )
    ordered = dict.fromkeys(
        publication.artifact_hash for entry in state.journal for publication in entry.publications
    )
    budgets: list[HostedResearchBudgetFact] = []
    steps: list[HostedResearchStepIntent] = []
    for digest in ordered:
        schema = strict_json_object(state.artifacts[digest], max_bytes=16_777_216).get(
            "schema_version"
        )
        if schema == "hosted-campaign-report/v1":
            raise HostedQualificationError("admission checkpoint contains a campaign final report")
        if schema == "hosted-research-budget-fact/v1":
            budgets.append(state.artifact(digest, HostedResearchBudgetFact))
        elif schema == "hosted-research-step-intent/v1":
            steps.append(state.artifact(digest, HostedResearchStepIntent))
    if len(steps) != 2 or tuple(step.phase for step in steps) != ("PREPARED", "COMPLETED"):
        raise HostedQualificationError("admission checkpoint lacks exactly one completed step")
    prepared_step, completed = steps
    if (
        completed.previous_intent_hash != prepared_step.content_hash
        or completed.execution_result_hash is not None
        or prepared_step.execution_request is not None
        or completed.trial_hash is None
        or any(
            getattr(completed, field) != getattr(prepared_step, field)
            for field in (
                "campaign_hash",
                "request_hash",
                "hosted_exchange_hash",
                "candidate_hash",
                "trial_idempotency_key",
                "execution_request",
                "budget_reservation_hash",
                "event_time",
            )
        )
    ):
        raise HostedQualificationError("admission checkpoint step bindings differ")
    trial = state.artifact(completed.trial_hash, CampaignTrial)
    if len(events) != len(bundle.initial_events) + 1:
        raise HostedQualificationError("admission checkpoint has unrelated campaign events")
    event = events[-1]
    if (
        not isinstance(event, ResearchCampaignEvent)
        or event.trial != trial
        or event.event_id != autonomous_trial_event_id(trial)
        or event.occurred_at != prepared_step.event_time
        or prepared_step.event_time
        != orchestrator.next_event_time(
            state.spec.started_at, events[:-1], bundle.initial_ledger_snapshot
        )
    ):
        raise HostedQualificationError("admission checkpoint trial event differs")
    receipt = state.accepted_receipt(request.content_hash)
    if receipt is None or receipt.accepted_exchange_hash != prepared_step.hosted_exchange_hash:
        raise HostedQualificationError("admission checkpoint has no corresponding accepted receipt")
    exchange = state.artifact(prepared_step.hosted_exchange_hash, HostedAgentExchange)
    response = state.artifact(exchange.response_hash, HostedAgentResponse)
    evidence = AutonomousProposalEvidence(
        request.business_request,
        response.proposal_json,
        response.proposal_hash,
        exchange.content_hash,
        "HOSTED_EXCHANGE",
    )
    prepared = orchestrator.prepare_trial(
        evidence, events=events[:-1], event_time=prepared_step.event_time
    )
    if (
        prepared_step.campaign_hash != request.campaign_hash
        or prepared_step.request_hash != request.content_hash
        or prepared.execution_request is not None
        or prepared.terminal_outcome != TrialOutcome.SCHEMA_INVALID
        or prepared.idempotency_key != prepared_step.trial_idempotency_key
        or prepared.candidate.content_hash != prepared_step.candidate_hash
        or trial != orchestrator.finish_trial(prepared, None, events=events[:-1])
    ):
        raise HostedQualificationError(
            "admission checkpoint differs from native proposal admission"
        )
    if tuple(budget.phase for budget in budgets) != ("INITIAL", "RESERVED", "SETTLED"):
        raise HostedQualificationError("admission checkpoint budget chronology differs")
    initial, reserved, settled = budgets
    projection = orchestrator.governor.project(bundle.campaign, bundle.research_budget, events)
    if (
        initial.campaign_hash != request.campaign_hash
        or initial.hosted_spec_hash != state.spec.content_hash
        or initial.recorded_at != state.spec.started_at
        or initial.used_trials != 0
        or initial.used_executions != 0
        or initial.used_compute_units != 0
        or initial.used_validation_rounds != 0
        or initial.candidate_hashes
        or initial.previous_hash is not None
        or initial.request_hash is not None
        or prepared_step.budget_reservation_hash != reserved.content_hash
    ):
        raise HostedQualificationError("admission checkpoint initial/reserved budget differs")
    previous = initial
    for budget in (reserved, settled):
        if (
            budget.recorded_at != prepared_step.event_time
            or budget.previous_hash != previous.content_hash
            or budget.campaign_hash != request.campaign_hash
            or budget.hosted_spec_hash != state.spec.content_hash
            or budget.request_hash != request.content_hash
            or budget.used_trials != projection.trial_count
            or budget.used_executions != projection.execution_count
            or budget.used_compute_units != projection.compute_seconds
            or budget.used_validation_rounds != projection.validation_round_count
            or budget.candidate_hashes != (trial.candidate_hash,)
        ):
            raise HostedQualificationError(
                "admission checkpoint budget differs from native event accounting"
            )
        previous = budget
    ledger = orchestrator.ledger_service.verify(
        bundle.ledger_id, created_at=prepared_step.event_time
    )
    orchestrator.require_initial_snapshot_prefix(ledger)
    if set(ledger.node_object_hashes) != {
        *bundle.initial_ledger_snapshot.node_object_hashes,
        trial.content_hash,
    }:
        raise HostedQualificationError("admission checkpoint has unrelated Ledger objects")
    terminal = state.terminal(request.content_hash)
    if (
        terminal is None
        or terminal.outcome != "STEP_COMPLETED"
        or terminal.recorded_at != prepared_step.event_time
        or terminal.authenticated_principal != "service"
        or terminal.business_artifact_hashes
        != tuple(
            sorted(
                (
                    trial.content_hash,
                    event.content_hash,
                    ledger.content_hash,
                    completed.content_hash,
                )
            )
        )
    ):
        raise HostedQualificationError("admission checkpoint terminal references differ")
    return trial, settled, tuple(event.content_hash for event in events)
