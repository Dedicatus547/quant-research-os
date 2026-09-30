"""Read-only hosted business verification using existing Qlib/Validation/Ledger/P14c."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quantos.application.autonomous import (
    AutonomousCampaignOrchestrator,
    AutonomousProposalEvidence,
    CampaignEventStore,
)
from quantos.application.campaign_selection import CampaignSelectionService
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.application.hosted_inputs import (
    HostedProposalOnlyDriver,
    build_hosted_execution_adapter,
)
from quantos.application.ledger import ResearchLedgerService
from quantos.contracts.campaign import CampaignEventType, CampaignTrial, ResearchCampaignEvent
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionReport,
    CandidateDispositionKind,
)
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentResponse,
    HostedCampaignReport,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
)
from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs, derive_hosted_campaign_spec
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import GateSeverity, ValidationGateId, ValidationReport
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    verify_protocol_root,
    verify_raw_inventory,
)
from quantos.validation import verify_validation_report


@dataclass(frozen=True)
class HostedVerifiedBusiness:
    report: HostedCampaignReport
    selection: CampaignSelectionReport | None
    validation_reports: tuple[ValidationReport, ...]
    execution_identities: tuple[str, ...]
    artifact_hashes: tuple[str, ...]


def verify_hosted_business_root(
    authority: Path,
    bundle: HostedFrozenBusinessInputs,
    *,
    deployment_profile_hash: str,
    input_root: Path,
    provenance_workspace: Path,
) -> HostedVerifiedBusiness:
    """Verify complete authority without creating, repairing, executing or accepting it."""
    inventory = raw_inventory(authority)
    campaign = bundle.campaign.content_hash
    verify_protocol_root(authority / "protocol", campaign)
    state = HostedProtocolStore(authority / "protocol").snapshot(campaign, recover=False)
    expected_spec = derive_hosted_campaign_spec(
        bundle, deployment_profile_hash=deployment_profile_hash
    )
    if state.spec.canonical_bytes() != expected_spec.canonical_bytes():
        raise HostedQualificationError("business spec differs from frozen bundle/deployment")
    runtime = authority / "business" / campaign
    execution = build_hosted_execution_adapter(
        bundle,
        input_root=input_root,
        runtime_root=runtime,
        provenance_workspace=provenance_workspace,
    )
    governor = ResearchCampaignGovernor(bundle.family, bundle.template, bundle.manifest)
    events = CampaignEventStore(runtime / "campaign-events").load(
        governor, bundle.campaign, bundle.research_budget
    )
    if events[: len(bundle.initial_events)] != bundle.initial_events:
        raise HostedQualificationError("business initial event prefix differs")
    selection = CampaignSelectionService(
        bundle.campaign,
        bundle.family,
        bundle.research_budget,
        bundle.template,
        bundle.manifest,
        bundle.multiple_testing_policy,
        bundle.selection_policy,
        input_root / bundle.qlib_view_directory,
        (execution.research_results_root,),
        plan=bundle.selection_plan,
    )
    ledger = ResearchLedgerService(runtime / "ledger")
    orchestrator = AutonomousCampaignOrchestrator(
        campaign=bundle.campaign,
        family=bundle.family,
        budget=bundle.research_budget,
        template=bundle.template,
        manifest=bundle.manifest,
        initial_ledger_snapshot=bundle.initial_ledger_snapshot,
        ledger_service=ledger,
        ledger_id=bundle.ledger_id,
        search_policy=bundle.search_policy,
        context_budget=bundle.context_budget,
        campaign_policy=bundle.campaign_policy,
        agent_run_policy=bundle.agent_run_policy,
        agent_driver=HostedProposalOnlyDriver(),
        execution_port=execution,
        exchange_root=runtime / "legacy-exchanges-unused",
        event_root=runtime / "campaign-events",
        selection_service=selection,
        selection_artifact_root=runtime / "selection-reports",
        autonomous_report_root=runtime / "legacy-loop-reports-unused",
        execution_bindings=bundle.execution_bindings,
        selection_finalization_profile=bundle.selection_finalization_profile,
    )
    publications = dict.fromkeys(
        publication.artifact_hash for entry in state.journal for publication in entry.publications
    )
    # Publication order is authority; hash-sorted object filenames are not chronology.
    budgets: list[HostedResearchBudgetFact] = []
    steps: list[HostedResearchStepIntent] = []
    reports: list[HostedCampaignReport] = []
    for digest in publications:
        data = state.artifacts[digest]
        if b'"schema_version":"hosted-research-budget-fact/v1"' in data:
            budgets.append(state.artifact(digest, HostedResearchBudgetFact))
        elif b'"schema_version":"hosted-research-step-intent/v1"' in data:
            steps.append(state.artifact(digest, HostedResearchStepIntent))
        elif b'"schema_version":"hosted-campaign-report/v1"' in data:
            reports.append(state.artifact(digest, HostedCampaignReport))
    if len(reports) != 1 or not budgets or budgets[0].phase != "INITIAL":
        raise HostedQualificationError("business final report or initial budget is absent")
    report = reports[0]
    if (
        report.hosted_spec_hash != state.spec.content_hash
        or report.campaign_hash != campaign
        or report.protocol_budget_hash != state.budget.content_hash
        or report.research_budget_hash != budgets[-1].content_hash
        or report.request_hashes != tuple(request.content_hash for request in state.requests)
        or report.campaign_event_hashes != tuple(event.content_hash for event in events)
        or report.initial_ledger_snapshot_hash != bundle.initial_ledger_snapshot.content_hash
        or report.candidate_manifest_hash != bundle.manifest.content_hash
        or report.candidate_hashes
        != tuple(sorted(candidate.content_hash for candidate in bundle.manifest.candidates))
    ):
        raise HostedQualificationError("business final report bindings disagree")
    final_ledger = ledger.verify(bundle.ledger_id, created_at=report.recorded_at)
    orchestrator.require_initial_snapshot_prefix(final_ledger)
    if final_ledger.content_hash != report.final_ledger_snapshot_hash:
        raise HostedQualificationError("business final Ledger differs")
    trials = tuple(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    if report.trial_hashes != tuple(trial.content_hash for trial in trials):
        raise HostedQualificationError("business trial denominator differs")
    if report.attempted_candidate_hashes != tuple(sorted({t.candidate_hash for t in trials})):
        raise HostedQualificationError("business attempted candidate denominator differs")
    by_request = {request.content_hash: request for request in state.requests}
    latest: dict[str, HostedResearchStepIntent] = {}
    validations: list[ValidationReport] = []
    executions: list[str] = []
    for step in steps:
        previous = latest.get(step.request_hash)
        if (
            step.campaign_hash != campaign
            or step.previous_intent_hash != (previous.content_hash if previous else None)
            or (previous is None and step.phase != "PREPARED")
            or (
                previous is not None
                and (
                    step.phase != ("COMPLETED" if previous.phase == "STARTED" else "STARTED")
                    and not (
                        previous.phase == "PREPARED"
                        and step.phase == "COMPLETED"
                        and step.execution_request is None
                    )
                )
            )
        ):
            raise HostedQualificationError("business step phase chain differs")
        if previous is not None and any(
            getattr(step, name) != getattr(previous, name)
            for name in (
                "request_hash",
                "hosted_exchange_hash",
                "candidate_hash",
                "trial_idempotency_key",
                "execution_request",
                "budget_reservation_hash",
                "event_time",
            )
        ):
            raise HostedQualificationError("business step immutable bindings changed")
        latest[step.request_hash] = step
        if step.phase != "COMPLETED":
            continue
        if step.trial_hash is None:
            raise HostedQualificationError("completed step lacks trial identity")
        trial = state.artifact(step.trial_hash, CampaignTrial)
        indexes = [
            index
            for index, event in enumerate(events)
            if isinstance(event, ResearchCampaignEvent) and event.trial == trial
        ]
        if len(indexes) != 1:
            raise HostedQualificationError("completed step lacks one trial event")
        exchange = state.artifact(step.hosted_exchange_hash, HostedAgentExchange)
        response = state.artifact(exchange.response_hash, HostedAgentResponse)
        request = by_request[step.request_hash]
        evidence = AutonomousProposalEvidence(
            request.business_request,
            response.proposal_json,
            response.proposal_hash,
            exchange.content_hash,
            "HOSTED_EXCHANGE",
        )
        prefix = events[: indexes[0]]
        prepared = orchestrator.prepare_trial(evidence, events=prefix, event_time=step.event_time)
        if (
            prepared.execution_request != step.execution_request
            or prepared.idempotency_key != step.trial_idempotency_key
            or prepared.candidate.content_hash != step.candidate_hash
        ):
            raise HostedQualificationError("business proposal/trial/execution binding differs")
        outcome = None
        if step.execution_request is not None:
            outcome = execution.inspect_completed_execution(step.execution_request)
            if outcome is None or outcome.content_hash != step.execution_result_hash:
                raise HostedQualificationError("business execution receipt/result differs")
            executions.append(step.execution_request.execution_identity)
            if outcome.validation_report_hash is not None:
                validations.append(
                    verify_validation_report(
                        execution.output_root
                        / "validation"
                        / f"sha256-{outcome.validation_report_hash}"
                    )
                )
        if trial != orchestrator.finish_trial(prepared, outcome, events=prefix):
            raise HostedQualificationError("business trial differs from verified native outcome")
    projection = governor.project(bundle.campaign, bundle.research_budget, events)
    final_budget = budgets[-1]
    if (
        final_budget.used_trials != projection.trial_count
        or final_budget.used_executions != projection.execution_count
        or final_budget.used_validation_rounds != projection.validation_round_count
        or final_budget.used_compute_units != projection.compute_seconds
        or final_budget.candidate_hashes != report.attempted_candidate_hashes
    ):
        raise HostedQualificationError("business final reservation/event accounting differs")
    previous_budget: HostedResearchBudgetFact | None = None
    for budget in budgets:
        if (
            budget.campaign_hash != campaign
            or budget.hosted_spec_hash != state.spec.content_hash
            or budget.previous_hash != (previous_budget.content_hash if previous_budget else None)
            or budget.used_trials > bundle.research_budget.max_trials
            or budget.used_executions > bundle.research_budget.max_executions
            or budget.used_compute_units > bundle.research_budget.max_compute_seconds
            or budget.used_validation_rounds > bundle.research_budget.max_validation_rounds
            or len(budget.candidate_hashes) > bundle.research_budget.max_distinct_candidates
        ):
            raise HostedQualificationError("business budget chain or cap differs")
        previous_budget = budget
    p14c = None
    if report.selection_report_hash is not None:
        prefix = events
        if events and (
            (
                isinstance(events[-1], ResearchCampaignEvent)
                and events[-1].event_type is CampaignEventType.CLOSED
            )
            or (
                isinstance(events[-1], CampaignSelectionEvent)
                and events[-1].event_type is CampaignSelectionEventType.SELECTION_FROZEN
            )
        ):
            prefix = events[:-1]
        p14c = selection.verify_report(
            runtime / "selection-reports" / f"sha256-{report.selection_report_hash}", prefix
        )
    verify_raw_inventory(authority, inventory)
    return HostedVerifiedBusiness(
        report, p14c, tuple(validations), tuple(sorted(executions)), tuple(sorted(state.artifacts))
    )


def verify_q11_research_predicate(facts: HostedVerifiedBusiness) -> str:
    """Return the frozen natural-result classification; never grant overall qualification."""
    if (
        facts.report.remaining_candidate_hashes
        or len(facts.execution_identities) != len(facts.report.candidate_hashes)
        or len(facts.validation_reports) != len(facts.report.candidate_hashes)
        or facts.selection is None
    ):
        raise HostedQualificationError("Q11 complete candidate execution denominator is absent")
    rejected = False
    for report in facts.validation_reports:
        if report.run_status is not RunStatus.SUCCEEDED or not report.canonical:
            raise HostedQualificationError("Q11 native execution or canonical validation failed")
        for gate in report.gates:
            expected_severity = (
                GateSeverity.HARD
                if gate.gate_id
                in (
                    ValidationGateId.G0_SCHEMA_REFERENCE,
                    ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
                    ValidationGateId.G2_PIT_LINEAGE,
                    ValidationGateId.G9_REPRODUCIBILITY,
                    ValidationGateId.G10_ARTIFACT_INTEGRITY,
                )
                else GateSeverity.SOFT
            )
            if gate.severity is not expected_severity:
                raise HostedQualificationError("Q11 validation gate severity differs")
            if gate.verdict is ValidationVerdict.PASS:
                continue
            if (
                gate.gate_id is ValidationGateId.G5_OUT_OF_SAMPLE
                and gate.severity is GateSeverity.SOFT
                and gate.verdict is ValidationVerdict.REJECT
                and gate.reason_code is ReasonCode.SOFT_THRESHOLD_NOT_MET
            ):
                rejected = True
            else:
                raise HostedQualificationError("Q11 reject is outside frozen G5 soft exception")
        expected = (
            ValidationVerdict.REJECT
            if any(gate.verdict is ValidationVerdict.REJECT for gate in report.gates)
            else ValidationVerdict.PASS
        )
        if report.verdict is not expected:
            raise HostedQualificationError("Q11 validation aggregate differs from eleven gates")
    if rejected:
        if (
            facts.selection.run_status is not RunStatus.FAILED
            or facts.selection.verdict.value != "NOT_EVALUATED"
            or facts.selection.reason_code is not ReasonCode.SOURCE_INCOMPLETE
            or facts.selection.selected_candidate_hash is not None
            or any(
                item.kind is not CandidateDispositionKind.NONPASS_VALIDATION
                for item in facts.selection.candidate_dispositions
            )
        ):
            raise HostedQualificationError("Q11 P14c soft-reject natural result differs")
        return "COMPLETE_ADMISSIBLE_SOFT_REJECT"
    return "COMPLETE_VALIDATION_PASS"
