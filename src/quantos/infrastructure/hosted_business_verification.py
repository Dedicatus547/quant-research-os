"""Read-only hosted business verification using existing Qlib/Validation/Ledger/P14c."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from quantos.application.autonomous import (
    AutonomousCampaignOrchestrator,
    AutonomousProposalEvidence,
    CampaignEventStore,
    autonomous_trial_event_id,
)
from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.campaign_selection import CampaignSelectionService
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    hosted_business_operation_id,
)
from quantos.application.hosted_inputs import (
    HostedProposalOnlyDriver,
    build_hosted_execution_adapter,
)
from quantos.application.ledger import ResearchLedgerService
from quantos.backtest import verify_backtest_artifact
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import AutonomousExecutionResult
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
    strict_json_object,
)
from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs, derive_hosted_campaign_spec
from quantos.contracts.hosted_qualification import HostedRawInventory
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    GateSeverity,
    RobustnessKind,
    ValidationGateId,
    ValidationReport,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore, HostedStoreSnapshot
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    c11_manifest_projection,
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)
from quantos.research.qlib.signal import verify_signal_artifact
from quantos.research.qlib.universe import QlibResearchError
from quantos.validation import verify_validation_report


@dataclass(frozen=True)
class HostedVerifiedBusiness:
    report: HostedCampaignReport
    selection: CampaignSelectionReport | None
    validation_reports: tuple[ValidationReport, ...]
    execution_identities: tuple[str, ...]
    artifact_hashes: tuple[str, ...]


def c11_business_projection_paths(
    authority: Path, facts: HostedVerifiedBusiness, bundle: HostedFrozenBusinessInputs
) -> frozenset[str]:
    """Authorize native manifest paths from verified validation references and frozen variants.

    Unknown files with an otherwise valid C11 schema do not acquire a timestamp
    exception. They remain exact principal bytes in the two-root comparison.
    """
    prefix = f"business/{facts.report.campaign_hash}/execution"
    state = HostedProtocolStore(authority / "protocol").snapshot(
        facts.report.campaign_hash, recover=False
    )
    reports = {report.content_hash: report for report in facts.validation_reports}
    allowed: set[str] = set()
    for digest, raw in state.artifacts.items():
        if (
            strict_json_object(raw, max_bytes=16_777_216).get("schema_version")
            != "hosted-research-step-intent/v1"
        ):
            continue
        step = state.artifact(digest, HostedResearchStepIntent)
        if (
            step.phase != "COMPLETED"
            or step.execution_request is None
            or step.execution_result_hash is None
        ):
            continue
        outcome = state.artifact(step.execution_result_hash, AutonomousExecutionResult)
        if outcome.research_result_hash is not None:
            allowed.add(
                f"{prefix}/research-results/sha256-{outcome.research_result_hash}/manifest.json"
            )
        if outcome.validation_report_hash not in reports:
            continue
        report = reports[outcome.validation_report_hash]
        execution = f"{prefix}/executions/{step.execution_request.execution_identity}"
        allowed.update(
            (
                f"{execution}/baseline/signals/sha256-{report.signal_artifact_hash}/manifest.json",
                f"{execution}/baseline/backtests/sha256-{report.backtest_result_hash}/manifest.json",
            )
        )
        if report.reproducibility is not None:
            allowed.add(
                f"{execution}/reproduction/sha256-{report.reproducibility.right.sha256}/manifest.json"
            )
        for case in report.robustness_cases:
            variant: str | None = None
            if case.kind is RobustnessKind.COST_STRESS:
                for multiplier in bundle.validation_policy.cost_stress_multipliers:
                    if multiplier != 1.0 and case.case_id == f"cost-{multiplier:.1f}x":
                        variant = case.case_id
            elif case.kind is RobustnessKind.PARAMETER_STABILITY:
                for window in bundle.validation_policy.parameter_windows:
                    for top_k in bundle.validation_policy.parameter_top_k:
                        if case.case_id == f"window-{window}-topk-{top_k}" and not all(
                            ref.sha256 in {report.signal_artifact_hash, report.backtest_result_hash}
                            for ref in case.evidence
                        ):
                            variant = f"parameter-{window}-{top_k}"
            elif case.kind is RobustnessKind.SUBPERIOD and case.case_id in {
                period.period_id for period in bundle.validation_policy.subperiods
            }:
                variant = f"subperiod-{case.case_id}"
            if variant is not None:
                for ref in case.evidence:
                    directory = {"signal_artifact": "signals", "backtest_result": "backtests"}.get(
                        ref.kind
                    )
                    if directory is not None:
                        allowed.add(
                            f"{execution}/{variant}/{directory}/sha256-{ref.sha256}/manifest.json"
                        )
    for logical in sorted(allowed):
        c11_manifest_projection(read_relative(authority, logical), logical_path=logical)
        directory = authority / Path(logical).parent
        try:
            if "/signals/" in logical:
                manifest = verify_signal_artifact(directory)
                if directory.name != f"sha256-{manifest.content_hash}":
                    raise HostedQualificationError("referenced native signal hash differs")
            elif "/backtests/" in logical or "/reproduction/" in logical:
                backtest = verify_backtest_artifact(directory)
                if directory.name != f"sha256-{backtest.content_hash}":
                    raise HostedQualificationError("referenced native backtest hash differs")
        except (QlibResearchError, OSError, ValueError) as error:
            raise HostedQualificationError(
                "referenced native robustness artifact is invalid"
            ) from error
    return frozenset(allowed)


def principal_business_inventory(
    authority: Path, facts: HostedVerifiedBusiness
) -> tuple[HostedRawInventory, HostedRawInventory]:
    """Derive principal paths after bottom-up verification; bind runtime observations separately.

    Only the fixed offline instrumentation file and Qlib's mutable MLflow recorder
    trees beneath verified execution identities are runtime observations. Every other
    file, including unknown additions, remains principal and must compare exactly.
    """
    inventory = raw_inventory(authority)
    prefix = f"business/{facts.report.campaign_hash}/execution/executions/"
    runtime_prefixes = tuple(
        prefix + identity + "/qlib-workflow/mlflow-runtime/"
        for identity in facts.execution_identities
    )
    observations = tuple(
        item
        for item in inventory.files
        if item.logical_path == "offline-observation.json"
        or item.logical_path.startswith(runtime_prefixes)
    )
    excluded = {item.logical_path for item in observations}
    principal = tuple(item for item in inventory.files if item.logical_path not in excluded)
    if not principal:
        raise HostedQualificationError("verified business principal inventory is empty")
    return HostedRawInventory(files=principal), HostedRawInventory(files=observations)


def build_verified_business_orchestrator(
    authority: Path,
    bundle: HostedFrozenBusinessInputs,
    *,
    deployment_profile_hash: str,
    input_root: Path,
    provenance_workspace: Path,
) -> tuple[
    HostedStoreSnapshot,
    AutonomousCampaignOrchestrator,
    tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
]:
    """Read-only construction shared by complete and negative-checkpoint verification."""
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
    return state, orchestrator, events


def verify_native_business_steps(
    state: HostedStoreSnapshot,
    orchestrator: AutonomousCampaignOrchestrator,
    events: tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
    steps: tuple[HostedResearchStepIntent, ...],
) -> tuple[dict[str, HostedResearchStepIntent], tuple[ValidationReport, ...], tuple[str, ...]]:
    """Inspect native completion receipts without resume, publication or execution."""
    campaign = state.spec.campaign_hash
    execution = cast(QuantosResearchExecutionAdapter, orchestrator.execution_port)
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
        indexes = [
            index
            for index, event in enumerate(events)
            if isinstance(event, ResearchCampaignEvent)
            and event.trial is not None
            and event.trial.agent_run_hash == step.hosted_exchange_hash
        ]
        if len(indexes) > 1 or (step.phase == "COMPLETED" and len(indexes) != 1):
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
        prefix = events[: indexes[0]] if indexes else events
        prepared = orchestrator.prepare_trial(evidence, events=prefix, event_time=step.event_time)
        if (
            prepared.execution_request != step.execution_request
            or prepared.idempotency_key != step.trial_idempotency_key
            or prepared.candidate.content_hash != step.candidate_hash
            or step.event_time
            != orchestrator.next_event_time(
                state.spec.started_at, prefix, orchestrator.initial_ledger_snapshot
            )
        ):
            raise HostedQualificationError("business proposal/trial/execution binding differs")
        if step.phase != "COMPLETED":
            continue
        if step.trial_hash is None:
            raise HostedQualificationError("completed step lacks trial identity")
        trial = state.artifact(step.trial_hash, CampaignTrial)
        event = cast(ResearchCampaignEvent, events[indexes[0]])
        if (
            event.trial != trial
            or event.event_id != autonomous_trial_event_id(trial)
            or event.occurred_at != step.event_time
        ):
            raise HostedQualificationError("business trial native event identity/time differs")
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
    published_trials = {
        digest
        for digest, data in state.artifacts.items()
        if strict_json_object(data, max_bytes=16_777_216).get("schema_version")
        == "campaign-trial/v1"
    }
    recorded_trials = {
        event.trial.content_hash
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    }
    if published_trials != recorded_trials:
        raise HostedQualificationError("business has an unreferenced or unpublished trial")
    return latest, tuple(validations), tuple(executions)


def verify_native_business_budgets(
    state: HostedStoreSnapshot,
    orchestrator: AutonomousCampaignOrchestrator,
    events: tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
    initial_events: tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...],
    budgets: tuple[HostedResearchBudgetFact, ...],
    steps: tuple[HostedResearchStepIntent, ...],
    latest: dict[str, HostedResearchStepIntent],
    report: HostedCampaignReport | None,
) -> HostedResearchBudgetFact:
    """Inspect the existing native reservations/settlements at a checkpoint or report."""
    if not budgets:
        raise HostedQualificationError("business checkpoint has no initial budget")
    campaign = state.spec.campaign_hash
    execution = cast(QuantosResearchExecutionAdapter, orchestrator.execution_port)
    governor = orchestrator.governor
    projection = governor.project(orchestrator.campaign, orchestrator.budget, events)
    final_budget = budgets[-1]
    if final_budget.phase != "UNCERTAIN" and (
        final_budget.used_trials != projection.trial_count
        or final_budget.used_executions != projection.execution_count
        or final_budget.used_validation_rounds != projection.validation_round_count
        or final_budget.used_compute_units != projection.compute_seconds
        or final_budget.candidate_hashes
        != tuple(
            sorted(
                {
                    event.trial.candidate_hash
                    for event in events
                    if isinstance(event, ResearchCampaignEvent) and event.trial is not None
                }
            )
        )
    ):
        raise HostedQualificationError("business final reservation/event accounting differs")
    previous_budget: HostedResearchBudgetFact | None = None
    reservation_baseline: HostedResearchBudgetFact | None = None
    for budget in budgets:
        if (
            budget.campaign_hash != campaign
            or budget.hosted_spec_hash != state.spec.content_hash
            or budget.previous_hash != (previous_budget.content_hash if previous_budget else None)
            or budget.used_trials > orchestrator.budget.max_trials
            or budget.used_executions > orchestrator.budget.max_executions
            or budget.used_compute_units > orchestrator.budget.max_compute_seconds
            or budget.used_validation_rounds > orchestrator.budget.max_validation_rounds
            or len(budget.candidate_hashes) > orchestrator.budget.max_distinct_candidates
        ):
            raise HostedQualificationError("business budget chain or cap differs")
        budget_step = latest.get(str(budget.request_hash))
        native_kind = {
            "INITIAL": "RESEARCH_INITIAL",
            "RESERVED": "RESERVE",
            "SETTLED": "SETTLE",
            "UNCERTAIN": "UNCERTAIN",
        }.get(budget.phase)
        if (
            native_kind is None
            or budget.operation_id
            != hosted_business_operation_id(
                campaign,
                native_kind,
                state.spec.content_hash if budget.phase == "INITIAL" else budget.request_hash,
            )
            or budget.recorded_at
            != (
                state.spec.started_at
                if budget.phase == "INITIAL"
                else budget_step.event_time
                if budget_step is not None
                else None
            )
        ):
            raise HostedQualificationError("business native budget operation/time differs")
        if previous_budget is None:
            initial = governor.project(orchestrator.campaign, orchestrator.budget, initial_events)
            if (
                budget.phase != "INITIAL"
                or budget.request_hash is not None
                or budget.used_trials != initial.trial_count
                or budget.used_executions != initial.execution_count
                or budget.used_validation_rounds != initial.validation_round_count
                or budget.used_compute_units != initial.compute_seconds
                or budget.candidate_hashes
            ):
                raise HostedQualificationError("business initial budget differs from seed events")
        elif budget.phase == "RESERVED":
            prepared = next(
                (
                    step
                    for step in steps
                    if step.phase == "PREPARED"
                    and step.budget_reservation_hash == budget.content_hash
                ),
                None,
            )
            if prepared is None or previous_budget.phase not in ("INITIAL", "SETTLED"):
                raise HostedQualificationError("business reservation has no unique prepared step")
            charge = (
                execution.execution_compute_charge(prepared.execution_request)
                if prepared.execution_request is not None
                else 0
            )
            if (
                budget.request_hash != prepared.request_hash
                or budget.used_trials != previous_budget.used_trials + 1
                or budget.candidate_hashes
                != tuple(sorted({*previous_budget.candidate_hashes, prepared.candidate_hash}))
                or budget.used_executions
                != previous_budget.used_executions + int(prepared.execution_request is not None)
                or budget.used_validation_rounds
                != previous_budget.used_validation_rounds
                + int(orchestrator.campaign_policy.trial_segment is CampaignSegment.VALIDATION)
                or budget.used_compute_units != previous_budget.used_compute_units + charge
            ):
                raise HostedQualificationError("business reserved workload/denominator differs")
            reservation_baseline = previous_budget
        elif budget.phase in ("SETTLED", "UNCERTAIN"):
            if previous_budget.phase != "RESERVED" or reservation_baseline is None:
                raise HostedQualificationError("business settlement lacks an original reservation")
            if (
                budget.request_hash != previous_budget.request_hash
                or budget.used_trials != previous_budget.used_trials
                or budget.used_validation_rounds != previous_budget.used_validation_rounds
                or budget.candidate_hashes != previous_budget.candidate_hashes
            ):
                raise HostedQualificationError("business settlement refunded its denominator")
            if budget.phase == "UNCERTAIN":
                if (
                    budget.used_executions != previous_budget.used_executions
                    or budget.used_compute_units != previous_budget.used_compute_units
                    or report is None
                    or report.state != "RECOVERY_REQUIRED"
                    or report.reason != "EXECUTION_UNCERTAIN"
                ):
                    raise HostedQualificationError(
                        "business uncertain execution was refunded or continued"
                    )
            else:
                completed = latest.get(str(budget.request_hash))
                if (
                    completed is None
                    or completed.phase != "COMPLETED"
                    or completed.trial_hash is None
                ):
                    raise HostedQualificationError("business settlement lacks a completed trial")
                trial = state.artifact(completed.trial_hash, CampaignTrial)
                if (
                    budget.used_executions
                    != reservation_baseline.used_executions + int(trial.execution_requested)
                    or budget.used_compute_units
                    != reservation_baseline.used_compute_units + trial.compute_seconds
                    or budget.used_compute_units > previous_budget.used_compute_units
                ):
                    raise HostedQualificationError("business settled receipt workload differs")
        else:
            raise HostedQualificationError("business budget phase/order is invalid")
        previous_budget = budget
    return final_budget


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
    runtime = authority / "business" / campaign
    state, orchestrator, events = build_verified_business_orchestrator(
        authority,
        bundle,
        deployment_profile_hash=deployment_profile_hash,
        input_root=input_root,
        provenance_workspace=provenance_workspace,
    )
    selection, ledger = (
        orchestrator.selection_service,
        orchestrator.ledger_service,
    )
    # Reuse the application's pure chronology/accepted-exchange/reservation
    # checker before native inspection, including non-completed recovery steps.
    research = HostedCampaignApplicationService.verify_research_facts(state)
    budgets, steps, reports = research.budgets, research.steps, research.reports
    if len(reports) != 1 or not budgets or budgets[0].phase != "INITIAL":
        raise HostedQualificationError("business final report or initial budget is absent")
    report = reports[0]
    incomplete_dq_stop = HostedCampaignApplicationService.is_incomplete_dq_stop(
        orchestrator, events, report.state
    )
    if report.limitations != HostedCampaignApplicationService.report_limitations(
        incomplete_dq_stop
    ) or (
        incomplete_dq_stop
        and (
            report.selection_report_hash is not None
            or report.research_run_status != "FAILED"
            or report.research_verdict != "NOT_EVALUATED"
        )
    ):
        raise HostedQualificationError("business incomplete DQ stop claims selection or limits")
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
    latest, validations, executions = verify_native_business_steps(
        state, orchestrator, events, tuple(steps)
    )
    verify_native_business_budgets(
        state,
        orchestrator,
        events,
        bundle.initial_events,
        tuple(budgets),
        tuple(steps),
        latest,
        report,
    )
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
    facts = HostedVerifiedBusiness(
        report, p14c, tuple(validations), tuple(sorted(executions)), tuple(sorted(state.artifacts))
    )
    c11_business_projection_paths(authority, facts, bundle)
    verify_raw_inventory(authority, inventory)
    return facts


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
    passed_reports = sum(
        report.verdict is ValidationVerdict.PASS for report in facts.validation_reports
    )
    if rejected and passed_reports == 0:
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
    if facts.selection.run_status is not RunStatus.SUCCEEDED:
        raise HostedQualificationError("Q11 normal P14c result did not succeed")
    if rejected:
        return "COMPLETE_MIXED_VALIDATION_RESULTS"
    return "COMPLETE_VALIDATION_PASS"
