"""Bounded host-mediated orchestration over existing deterministic research services."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from quantos.application.autonomous import (
    AutonomousCampaignOrchestrator,
    AutonomousProposalEvidence,
    autonomous_trial_event_id,
)
from quantos.application.campaigns import CampaignChainEvent
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError, exclusive_directory_lock
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    SDK_BOUNDED_FINALIZATION_PROFILE,
    AutonomousAgentRequest,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import CampaignEventType, CampaignTrial, ResearchCampaignEvent
from quantos.contracts.campaign_selection import CampaignSelectionEvent, CampaignSelectionEventType
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedCampaignReport,
    HostedCampaignSpec,
    HostedCampaignStatus,
    HostedProtocolStatus,
    HostedRequestTerminalReceipt,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
    HostedSubmissionReceipt,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.sdk_producer import SdkCampaignSpec
from quantos.infrastructure.hosted_store import AUTHORITY_BYTE_CAP, HostedStoreSnapshot


class HostedExecutionPort(Protocol):
    def execution_compute_charge(self, request: AutonomousExecutionRequest) -> int: ...

    def verified_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None: ...


@dataclass(frozen=True)
class HostedCampaignInputs:
    """Service management registration; never accepted from the research channel.

    Each new service process reconstructs this object from its frozen configuration.
    The mandatory callback must bottom-up verify snapshot/view, policy and input bytes;
    functional test doubles do not establish production or live qualification.
    """

    orchestrator: AutonomousCampaignOrchestrator
    initial_events: tuple[CampaignChainEvent, ...]
    verify_frozen_inputs: Callable[[HostedCampaignSpec], None]


@dataclass(frozen=True)
class HostedResearchFacts:
    budgets: tuple[HostedResearchBudgetFact, ...]
    steps: tuple[HostedResearchStepIntent, ...]
    reports: tuple[HostedCampaignReport, ...]


def hosted_business_operation_id(campaign_hash: str, kind: str, identity: object) -> str:
    return sha256_bytes(
        canonical_json_bytes({"campaign": campaign_hash, "kind": kind, "id": identity})
    )


class HostedCampaignApplicationService:
    """One application boundary for CLI/channel; no runtime or accounting engine.

    ``business_lock_root`` and typed registrations are trusted service configuration.
    Protocol frame scanning (including deployment capability scanning) is supplied to
    the shared ``HostedProtocolService`` and retains its bounded rejection accounting.
    """

    def __init__(
        self,
        protocol: HostedProtocolService,
        *,
        business_lock_root: Path,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.protocol = protocol
        self._lock_root = business_lock_root
        self._fault_hook = fault_hook
        self._inputs: dict[str, HostedCampaignInputs] = {}
        self._specs: dict[str, HostedCampaignSpec] = {}

    def _fault(self, point: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)

    def register_inputs(self, spec: HostedCampaignSpec, inputs: HostedCampaignInputs) -> str:
        """Management-only registration; host APIs accept hashes and bytes only."""
        self._check_bindings(spec, inputs)
        previous = self._specs.get(spec.campaign_hash)
        if previous is not None and previous != spec:
            raise ArtifactIntegrityError("campaign has another registered hosted spec")
        self._inputs[spec.campaign_hash] = inputs
        self._specs[spec.campaign_hash] = spec
        return self.protocol.register(spec)

    @staticmethod
    def _check_bindings(spec: HostedCampaignSpec, inputs: HostedCampaignInputs) -> None:
        o = inputs.orchestrator
        if isinstance(spec, SdkCampaignSpec) and (
            o.agent_run_policy.harness_identifier != "openai-codex-python-sdk"
            or o.agent_run_policy.provider_model_identifier != spec.sdk_profile.model
            or o.agent_run_policy.model_snapshot_immutable
        ):
            raise ArtifactIntegrityError("SDK producer requires explicit SDK agent policy")
        if isinstance(spec, SdkCampaignSpec) and (
            o.agent_run_policy.instruction_hashes
            != tuple(sorted(set(spec.sdk_profile.instruction_hashes)))
            or o.agent_run_policy.skill_hash != spec.sdk_profile.skill_hash
        ):
            raise ArtifactIntegrityError("SDK instructions differ from frozen agent policy")
        selection_plan = o.selection_service.plan
        bindings = (
            (
                spec.contract_hash,
                "14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df",
            ),
            (
                spec.acceptance_hash,
                "e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e",
            ),
            (spec.campaign.content_hash, o.campaign.content_hash),
            (spec.research_budget.content_hash, o.budget.content_hash),
            (spec.campaign.family_hash, o.family.content_hash),
            (spec.candidate_manifest_hash, o.manifest.content_hash),
            (spec.factor_template_hash, o.template.content_hash),
            (spec.campaign.ledger_snapshot_hash, o.initial_ledger_snapshot.content_hash),
            (spec.selection_plan_hash, selection_plan.content_hash if selection_plan else None),
            (
                spec.selection_finalization_profile_hash,
                o.selection_finalization_profile.content_hash,
            ),
            (spec.execution_bindings.content_hash, o.execution_bindings.content_hash),
            (spec.search_policy_hash, o.search_policy.content_hash),
            (spec.context_budget_policy_hash, o.context_budget.content_hash),
            (spec.campaign_policy_hash, o.campaign_policy.content_hash),
            (spec.agent_run_policy_hash, o.agent_run_policy.content_hash),
            (
                spec.requested_model_configuration_hash,
                o.agent_run_policy.requested_model_configuration_hash,
            ),
        )
        if any(expected != actual for expected, actual in bindings):
            raise ArtifactIntegrityError(
                "registered business inputs differ from frozen hosted spec"
            )
        o.governor.project(o.campaign, o.budget, inputs.initial_events)
        o.require_frozen_plan(inputs.initial_events)

    def verify_registered_inputs(self, spec: HostedCampaignSpec) -> None:
        """Callback for the protocol service's mandatory start/resume reverifier."""
        inputs = self._registered(spec.campaign_hash)
        if self._specs[spec.campaign_hash] != spec:
            raise ArtifactIntegrityError("hosted spec differs from management registration")
        self._check_bindings(spec, inputs)
        inputs.verify_frozen_inputs(spec)
        o = inputs.orchestrator
        events = o.event_store.load(o.governor, o.campaign, o.budget) or inputs.initial_events
        o.require_initial_snapshot_prefix(o.current_ledger_snapshot(spec.started_at, events))

    def _registered(self, campaign_hash: str) -> HostedCampaignInputs:
        try:
            return self._inputs[campaign_hash]
        except KeyError as error:
            raise ArtifactIntegrityError(
                "campaign is not registered in service configuration"
            ) from error

    def registered_spec(self, campaign_hash: str) -> HostedCampaignSpec:
        """Management-only identity for the independently bootstrapped authorization map."""
        self._registered(campaign_hash)
        return self._specs[campaign_hash]

    def _lock(self, campaign_hash: str) -> AbstractContextManager[None]:
        import re

        if re.fullmatch(SHA256_PATTERN, campaign_hash) is None:
            raise ArtifactIntegrityError("invalid hosted campaign identity")
        return exclusive_directory_lock(self._lock_root / campaign_hash)

    def start(self, spec_hash: str) -> HostedCampaignStatus:
        spec = self.protocol.store.spec(spec_hash)
        self.verify_registered_inputs(spec)
        with self._lock(spec.campaign_hash):
            self.protocol.start(spec_hash)
            return self._advance(spec.campaign_hash)

    def execution_storage_roots(self, campaign_hash: str) -> tuple[Path, ...]:
        """Management-only roots for the existing physical-volume reservation guard."""
        from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter

        execution = self._registered(campaign_hash).orchestrator.execution_port
        if not isinstance(execution, QuantosResearchExecutionAdapter):
            raise ArtifactIntegrityError("production SDK execution requires existing Qlib adapter")
        return (
            self.protocol.store.root,
            self._lock_root,
            execution.output_root,
            execution.snapshot_path,
            execution.qlib_view_path,
        )

    def pending(self, campaign_hash: str) -> HostedAgentRequest | None:
        self._registered(campaign_hash)
        return self.protocol.pending(campaign_hash)

    def submit(
        self, request_hash: str, response_bytes: bytes, authenticated_principal: str
    ) -> HostedSubmissionReceipt:
        # Submission itself is the shared protocol operation. Resume performs business
        # admission; acceptance does not confer model/runtime qualification.
        campaign_hash = self.protocol.store.locate_request(request_hash)
        self._registered(campaign_hash)
        return self.protocol.submit(request_hash, response_bytes, authenticated_principal)

    def cancel(
        self, request_hash: str, authenticated_principal: str
    ) -> HostedRequestTerminalReceipt:
        campaign_hash = self.protocol.store.locate_request(request_hash)
        self._registered(campaign_hash)
        return self.protocol.cancel(request_hash, authenticated_principal)

    def resume(self, campaign_hash: str) -> HostedCampaignStatus:
        self._registered(campaign_hash)
        with self._lock(campaign_hash):
            self.protocol.resume(campaign_hash)
            return self._advance(campaign_hash)

    def status(self, campaign_hash: str) -> HostedCampaignStatus:
        self._registered(campaign_hash)
        state = self.protocol.store.snapshot(campaign_hash)
        return self.project_status(state, self.protocol.status(campaign_hash))

    @staticmethod
    def project_status(
        state: HostedStoreSnapshot, protocol: HostedProtocolStatus
    ) -> HostedCampaignStatus:
        """Pure projection shared by status and read-only evidence verification."""
        facts = HostedCampaignApplicationService.verify_research_facts(state)
        report = facts.reports[-1] if facts.reports else None
        status: str = (
            report.state
            if report
            else (
                "EXECUTION_PENDING"
                if protocol.state == "RESPONSE_ACCEPTED"
                else "WAITING_FOR_AGENT"
                if protocol.state == "READY"
                else protocol.state
            )
        )
        return HostedCampaignStatus(
            campaign_hash=state.spec.campaign_hash,
            hosted_spec_hash=state.spec.content_hash,
            protocol=protocol,
            state=status,
            research_budget_hash=facts.budgets[-1].content_hash if facts.budgets else None,
            report_hash=report.content_hash if report else None,
            reason=report.reason if report else None,
        )

    @staticmethod
    def verify_research_facts(state: HostedStoreSnapshot) -> HostedResearchFacts:
        budgets: list[HostedResearchBudgetFact] = []
        steps: list[HostedResearchStepIntent] = []
        reports: list[HostedCampaignReport] = []
        seen: set[str] = set()
        for entry in state.journal:
            for publication in entry.publications:
                digest = publication.artifact_hash
                if digest in seen:
                    continue
                seen.add(digest)
                data = state.artifacts[digest]
                schema = strict_json_object(data, max_bytes=AUTHORITY_BYTE_CAP).get(
                    "schema_version"
                )
                if schema == "hosted-research-budget-fact/v1":
                    budgets.append(
                        parse_hosted_contract(
                            data, HostedResearchBudgetFact, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-research-step-intent/v1":
                    steps.append(
                        parse_hosted_contract(
                            data, HostedResearchStepIntent, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-campaign-report/v1":
                    reports.append(
                        parse_hosted_contract(
                            data, HostedCampaignReport, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
        previous = None
        reserved_requests: set[str] = set()
        for budget in budgets:
            if (
                budget.campaign_hash != state.spec.campaign_hash
                or budget.hosted_spec_hash != state.spec.content_hash
                or budget.previous_hash != (previous.content_hash if previous else None)
                or (previous is None) != (budget.phase == "INITIAL")
                or budget.used_trials > state.spec.research_budget.max_trials
                or len(budget.candidate_hashes) > state.spec.research_budget.max_distinct_candidates
                or budget.used_executions > state.spec.research_budget.max_executions
                or budget.used_validation_rounds > state.spec.research_budget.max_validation_rounds
                or budget.used_compute_units > state.spec.research_budget.max_compute_seconds
            ):
                raise ArtifactIntegrityError("hosted research budget facts conflict")
            if previous is None:
                if budget.request_hash is not None:
                    raise ArtifactIntegrityError("initial research budget has a request")
            elif budget.phase == "RESERVED":
                if (
                    previous.phase not in ("INITIAL", "SETTLED")
                    or budget.request_hash is None
                    or budget.request_hash in reserved_requests
                    or budget.used_trials != previous.used_trials + 1
                    or not set(previous.candidate_hashes).issubset(budget.candidate_hashes)
                    or len(set(budget.candidate_hashes) - set(previous.candidate_hashes)) > 1
                    or budget.used_executions - previous.used_executions not in (0, 1)
                    or budget.used_validation_rounds - previous.used_validation_rounds not in (0, 1)
                    or budget.used_compute_units < previous.used_compute_units
                ):
                    raise ArtifactIntegrityError("research reservation transition conflicts")
                reserved_requests.add(budget.request_hash)
            elif budget.phase in ("SETTLED", "UNCERTAIN") and (
                previous.phase != "RESERVED"
                or budget.request_hash != previous.request_hash
                or budget.used_trials != previous.used_trials
                or budget.candidate_hashes != previous.candidate_hashes
                or budget.used_validation_rounds != previous.used_validation_rounds
                or previous.used_executions - budget.used_executions not in (0, 1)
                or budget.used_compute_units > previous.used_compute_units
                or (
                    budget.phase == "UNCERTAIN"
                    and (
                        budget.used_executions != previous.used_executions
                        or budget.used_compute_units != previous.used_compute_units
                    )
                )
            ):
                raise ArtifactIntegrityError("research settlement transition conflicts")
            previous = budget
        by_request: dict[str, HostedResearchStepIntent] = {}
        for step in steps:
            request = state.request(step.request_hash)
            accepted = state.accepted_receipt(step.request_hash)
            prior = by_request.get(step.request_hash)
            if (
                step.campaign_hash != state.spec.campaign_hash
                or accepted is None
                or accepted.accepted_exchange_hash != step.hosted_exchange_hash
                or step.previous_intent_hash != (prior.content_hash if prior else None)
                or (prior is None) != (step.phase == "PREPARED")
                or request.candidate_manifest_hash != state.spec.candidate_manifest_hash
            ):
                raise ArtifactIntegrityError("hosted research step chain conflicts")
            reservation = state.artifact(step.budget_reservation_hash, HostedResearchBudgetFact)
            if reservation.phase != "RESERVED" or reservation.request_hash != step.request_hash:
                raise ArtifactIntegrityError("research step reservation does not match request")
            if prior is not None:
                immutable_fields = (
                    "campaign_hash",
                    "request_hash",
                    "hosted_exchange_hash",
                    "candidate_hash",
                    "trial_idempotency_key",
                    "execution_request",
                    "budget_reservation_hash",
                    "event_time",
                )
                if any(getattr(step, x) != getattr(prior, x) for x in immutable_fields):
                    raise ArtifactIntegrityError("hosted prepared step was rebound")
                if (prior.phase, step.phase) not in (
                    ("PREPARED", "STARTED"),
                    ("PREPARED", "COMPLETED"),
                    ("STARTED", "COMPLETED"),
                ):
                    raise ArtifactIntegrityError("hosted step phase transition is invalid")
            if step.phase == "COMPLETED":
                trial = state.artifact(cast(str, step.trial_hash), CampaignTrial)
                if (
                    trial.idempotency_key != step.trial_idempotency_key
                    or trial.agent_run_hash != step.hosted_exchange_hash
                    or trial.candidate_hash != step.candidate_hash
                ):
                    raise ArtifactIntegrityError("hosted completed trial identity conflicts")
                if step.execution_result_hash is not None:
                    result = state.artifact(step.execution_result_hash, AutonomousExecutionResult)
                    if (
                        step.execution_request is None
                        or result.request_hash != step.execution_request.content_hash
                    ):
                        raise ArtifactIntegrityError("completed execution result request conflicts")
                settlements = tuple(
                    fact
                    for fact in budgets
                    if fact.phase == "SETTLED" and fact.request_hash == step.request_hash
                )
                baseline = state.artifact(
                    cast(str, reservation.previous_hash), HostedResearchBudgetFact
                )
                if len(settlements) != 1 or (
                    settlements[0].used_executions
                    != baseline.used_executions + int(trial.execution_requested)
                    or settlements[0].used_compute_units
                    != baseline.used_compute_units + trial.compute_seconds
                ):
                    raise ArtifactIntegrityError("trial does not reconcile research settlement")
            by_request[step.request_hash] = step
        if reserved_requests != {step.request_hash for step in steps if step.phase == "PREPARED"}:
            raise ArtifactIntegrityError("research reservation lacks its prepared step")
        if len(reports) > 1:
            raise ArtifactIntegrityError("hosted campaign has conflicting final reports")
        for report in reports:
            if (
                report.hosted_spec_hash != state.spec.content_hash
                or report.campaign_hash != state.spec.campaign_hash
            ):
                raise ArtifactIntegrityError("hosted final report binding conflicts")
            state.artifact(report.research_budget_hash, HostedResearchBudgetFact)
        return HostedResearchFacts(tuple(budgets), tuple(steps), tuple(reports))

    def _publish(
        self,
        state: HostedStoreSnapshot,
        kind: str,
        identity: object,
        at: datetime,
        artifacts: tuple[CanonicalContract, ...],
    ) -> HostedStoreSnapshot:
        return self.protocol.publish_business(
            state.spec.campaign_hash,
            operation_id=hosted_business_operation_id(state.spec.campaign_hash, kind, identity),
            recorded_at=at,
            artifacts=artifacts,
            expected_journal_head_hash=state.journal_head_hash,
        )

    def _events(self, inputs: HostedCampaignInputs) -> tuple[CampaignChainEvent, ...]:
        o = inputs.orchestrator
        return o.event_store.seed(inputs.initial_events, o.governor, o.campaign, o.budget)

    def _evidence(self, state: HostedStoreSnapshot) -> tuple[AutonomousProposalEvidence, ...]:
        result: list[AutonomousProposalEvidence] = []
        for request in state.requests:
            exchange = self.protocol.accepted_exchange(request.content_hash)
            if exchange is not None:
                bound_request, response, run = exchange
                result.append(
                    AutonomousProposalEvidence(
                        bound_request.business_request,
                        response.proposal_json,
                        response.proposal_hash,
                        run.content_hash,
                        run.provenance_kind,
                    )
                )
        return tuple(result)

    def _advance(self, campaign_hash: str) -> HostedCampaignStatus:
        inputs = self._registered(campaign_hash)
        o = inputs.orchestrator
        state = self.protocol.store.snapshot(campaign_hash, recover=True)
        self.verify_registered_inputs(state.spec)
        facts = self.verify_research_facts(state)
        if facts.reports:
            self._verify_report(state, facts.reports[-1], inputs)
            return self.status(campaign_hash)
        events = self._events(inputs)
        ledger = o.current_ledger_snapshot(state.spec.started_at, events)
        o.require_initial_snapshot_prefix(ledger)
        events, ledger = o.reconcile_ledger(
            events,
            ledger,
            state.spec.started_at,
            hosted_evidence=self._evidence(state),
        )
        projection = o.governor.project(o.campaign, o.budget, events)
        if not facts.budgets:
            initial = HostedResearchBudgetFact(
                campaign_hash=campaign_hash,
                hosted_spec_hash=state.spec.content_hash,
                previous_hash=None,
                operation_id=hosted_business_operation_id(
                    campaign_hash, "RESEARCH_INITIAL", state.spec.content_hash
                ),
                request_hash=None,
                phase="INITIAL",
                used_trials=projection.trial_count,
                candidate_hashes=tuple(
                    sorted(
                        {
                            event.trial.candidate_hash
                            for event in events
                            if isinstance(event, ResearchCampaignEvent) and event.trial
                        }
                    )
                ),
                used_executions=projection.execution_count,
                used_validation_rounds=projection.validation_round_count,
                used_compute_units=projection.compute_seconds,
                recorded_at=state.spec.started_at,
            )
            state = self._publish(
                state,
                "RESEARCH_INITIAL",
                state.spec.content_hash,
                state.spec.started_at,
                (initial,),
            )
            self._fault("research_initial")
            facts = self.verify_research_facts(state)
        request = state.active_request
        if request is not None and state.accepted_receipt(request.content_hash) is not None:
            if not self._consume(state, facts, inputs, events, request):
                return self.status(campaign_hash)
            state = self.protocol.store.snapshot(campaign_hash)
            facts = self.verify_research_facts(state)
            events = self._events(inputs)
        stop = o.stopping_reason(o.governor.project(o.campaign, o.budget, events), events)
        protocol_status = self.protocol.status(campaign_hash)
        if stop is not None:
            return self._finalize(
                state,
                inputs,
                events,
                "COMPLETED" if stop.value == "ALL_CANDIDATES_TERMINAL" else "EXHAUSTED",
                stop.value,
            )
        if protocol_status.state in ("CANCELLED", "EXPIRED", "EXHAUSTED"):
            return self._finalize(
                state,
                inputs,
                events,
                cast("FinalState", protocol_status.state),
                f"PROTOCOL_{protocol_status.state}",
            )
        if state.active_request is None and state.requests:
            previous_exchange = self.protocol.accepted_exchange(state.requests[-1].content_hash)
            proposal = (
                o.parse_proposal_bytes(previous_exchange[1].proposal_json)
                if previous_exchange
                else None
            )
            if (
                proposal is not None
                and proposal.request_stop
                and o.campaign_policy.allow_agent_requested_manual_close
                and o.campaign.stopping_rule.value == "BUDGET_EXHAUSTED_OR_MANUAL_CLOSE"
            ):
                return self._finalize(
                    state, inputs, events, "EXHAUSTED", "MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY"
                )
        if state.active_request is None:
            ledger = o.current_ledger_snapshot(state.spec.started_at, events)
            event_time = o.next_event_time(state.spec.started_at, events, ledger)
            ledger = o.current_ledger_snapshot(event_time, events)
            request, pack = o.build_agent_request(
                ledger,
                o.access_scope(ledger),
                o.governor.project(o.campaign, o.budget, events),
                events,
            )
            # Transport admission recognizes every frozen candidate, including a
            # known repeat. Existing business admission accounts such a repeat as
            # DUPLICATE_CANDIDATE; the governor still determines remaining work.
            request = AutonomousAgentRequest.model_validate(
                request.model_copy(
                    update={
                        "candidate_options": tuple(
                            sorted(o.manifest.candidates, key=lambda item: item.content_hash)
                        )
                    }
                ).model_dump(mode="python")
            )
            if len(request.canonical_bytes()) > o.campaign_policy.max_agent_request_bytes:
                raise ArtifactIntegrityError(
                    "hosted business request exceeds frozen campaign byte cap"
                )
            self.protocol.issue(
                state.spec.content_hash,
                request,
                projection_object_hashes=tuple(
                    sorted({pack.content_hash, request.proposal_schema_hash})
                ),
            )
            self._fault("request_checkpoint")
        return self.status(campaign_hash)

    def projection_object_bytes(self, campaign_hash: str, object_hash: str) -> bytes:
        """Management-only export of the pending request's two approved projections."""
        request = self.pending(campaign_hash)
        if request is None or object_hash not in request.projection_object_hashes:
            raise ArtifactIntegrityError("object is outside the pending request projection")
        if object_hash == request.context_pack_hash:
            data = request.business_request.context_pack.canonical_bytes()
        elif object_hash == request.proposal_schema_hash:
            data = request.business_request.allowed_proposal_schema_json.encode("utf-8")
        else:
            raise ArtifactIntegrityError("unsupported projection object")
        if sha256_bytes(data) != object_hash:
            raise ArtifactIntegrityError("projection object bytes differ from request identity")
        return data

    def _consume(
        self,
        state: HostedStoreSnapshot,
        facts: HostedResearchFacts,
        inputs: HostedCampaignInputs,
        events: tuple[CampaignChainEvent, ...],
        request: HostedAgentRequest,
    ) -> bool:
        o = inputs.orchestrator
        exchange = self.protocol.accepted_exchange(request.content_hash)
        if exchange is None:
            raise ArtifactIntegrityError("accepted business exchange is missing")
        _, response, run = exchange
        evidence = AutonomousProposalEvidence(
            request.business_request,
            response.proposal_json,
            response.proposal_hash,
            run.content_hash,
            run.provenance_kind,
        )
        prior = next(
            (step for step in reversed(facts.steps) if step.request_hash == request.content_hash),
            None,
        )
        trial_recorded = any(
            isinstance(event, ResearchCampaignEvent)
            and event.trial is not None
            and event.trial.agent_run_hash == run.content_hash
            for event in events
        )
        if (
            not trial_recorded
            and o.current_ledger_snapshot(state.spec.started_at, events).content_hash
            != request.business_request.context_pack.ledger_snapshot_hash
        ):
            raise ArtifactIntegrityError("pending request Ledger was changed without its trial")
        event_time = (
            prior.event_time
            if prior
            else o.next_event_time(state.spec.started_at, events, o.initial_ledger_snapshot)
        )
        # The committed trial may already be in events after a crash; prepare against
        # the event prefix before this request to preserve its original execution identity.
        prefix = tuple(
            event
            for event in events
            if not (
                isinstance(event, ResearchCampaignEvent)
                and event.trial
                and event.trial.agent_run_hash == run.content_hash
            )
        )
        prepared = o.prepare_trial(evidence, events=prefix, event_time=event_time)
        if prior is None:
            before = facts.budgets[-1]
            execution = prepared.execution_request
            charge = self._execution_port(o).execution_compute_charge(execution) if execution else 0
            if isinstance(charge, bool) or charge < 0:
                raise ArtifactIntegrityError("execution workload quote is invalid")
            candidates = tuple(sorted({*before.candidate_hashes, prepared.candidate.content_hash}))
            reserved = HostedResearchBudgetFact(
                campaign_hash=state.spec.campaign_hash,
                hosted_spec_hash=state.spec.content_hash,
                previous_hash=before.content_hash,
                operation_id=hosted_business_operation_id(
                    state.spec.campaign_hash, "RESERVE", request.content_hash
                ),
                request_hash=request.content_hash,
                phase="RESERVED",
                used_trials=before.used_trials + 1,
                candidate_hashes=candidates,
                used_executions=before.used_executions + int(execution is not None),
                used_validation_rounds=before.used_validation_rounds
                + int(o.campaign_policy.trial_segment is CampaignSegment.VALIDATION),
                used_compute_units=before.used_compute_units + charge,
                recorded_at=event_time,
            )
            budget = o.budget
            if (
                reserved.used_trials > budget.max_trials
                or len(candidates) > budget.max_distinct_candidates
                or reserved.used_executions > budget.max_executions
                or reserved.used_validation_rounds > budget.max_validation_rounds
                or reserved.used_compute_units > budget.max_compute_seconds
            ):
                self._finalize(state, inputs, events, "EXHAUSTED", "RESEARCH_RESERVATION_EXHAUSTED")
                return False
            prior = HostedResearchStepIntent(
                campaign_hash=state.spec.campaign_hash,
                request_hash=request.content_hash,
                hosted_exchange_hash=run.content_hash,
                candidate_hash=prepared.candidate.content_hash,
                trial_idempotency_key=prepared.idempotency_key,
                execution_request=execution,
                budget_reservation_hash=reserved.content_hash,
                phase="PREPARED",
                previous_intent_hash=None,
                event_time=event_time,
            )
            state = self._publish(
                state, "PREPARED", request.content_hash, event_time, (reserved, prior)
            )
            self._fault("prepared")
        if (
            prior.execution_request != prepared.execution_request
            or prior.trial_idempotency_key != prepared.idempotency_key
        ):
            raise ArtifactIntegrityError("prepared business request differs after recovery")
        result = None
        if prior.phase == "COMPLETED":
            trial = state.artifact(cast(str, prior.trial_hash), CampaignTrial)
            if prior.execution_request is not None:
                result = self._execution_port(o).verified_completed_execution(
                    prior.execution_request
                )
                if result is None or result.content_hash != prior.execution_result_hash:
                    raise ArtifactIntegrityError(
                        "completed hosted execution receipt changed or disappeared"
                    )
            if trial != o.finish_trial(prepared, result, events=prefix):
                raise ArtifactIntegrityError("completed hosted trial differs from verified receipt")
        else:
            execution = prior.execution_request
            if execution is not None:
                if prior.phase == "STARTED":
                    result = self._execution_port(o).verified_completed_execution(execution)
                    if result is None:
                        before = self.verify_research_facts(state).budgets[-1]
                        uncertain = before.model_copy(
                            update={
                                "previous_hash": before.content_hash,
                                "operation_id": hosted_business_operation_id(
                                    state.spec.campaign_hash, "UNCERTAIN", request.content_hash
                                ),
                                "phase": "UNCERTAIN",
                            }
                        )
                        state = self._publish(
                            state, "UNCERTAIN", request.content_hash, event_time, (uncertain,)
                        )
                        self._finalize(
                            state, inputs, events, "RECOVERY_REQUIRED", "EXECUTION_UNCERTAIN"
                        )
                        return False
                else:
                    started = prior.model_copy(
                        update={"phase": "STARTED", "previous_intent_hash": prior.content_hash}
                    )
                    state = self._publish(
                        state, "STARTED", request.content_hash, event_time, (started,)
                    )
                    prior = started
                    self._fault("started")
                    result = o.execution_port.execute(execution)
                    self._fault("execution_receipt")
                if result.execution_artifact_hash is None:
                    raise ArtifactIntegrityError(
                        "hosted execution lacks a verified completion receipt"
                    )
            trial = o.finish_trial(prepared, result, events=prefix)
            before = self.verify_research_facts(state).budgets[-1]
            reserved = state.artifact(prior.budget_reservation_hash, HostedResearchBudgetFact)
            baseline = state.artifact(cast(str, reserved.previous_hash), HostedResearchBudgetFact)
            settled = before.model_copy(
                update={
                    "previous_hash": before.content_hash,
                    "operation_id": hosted_business_operation_id(
                        state.spec.campaign_hash, "SETTLE", request.content_hash
                    ),
                    "phase": "SETTLED",
                    "used_executions": baseline.used_executions + int(trial.execution_requested),
                    "used_compute_units": baseline.used_compute_units + trial.compute_seconds,
                }
            )
            if settled.used_compute_units > reserved.used_compute_units:
                raise ArtifactIntegrityError("execution exceeds frozen workload reservation")
            completed = prior.model_copy(
                update={
                    "phase": "COMPLETED",
                    "previous_intent_hash": prior.content_hash,
                    "trial_hash": trial.content_hash,
                    "execution_result_hash": result.content_hash if result else None,
                }
            )
            artifacts: tuple[CanonicalContract, ...] = (trial, settled, completed)
            if result is not None:
                artifacts = (result, *artifacts)
            state = self._publish(state, "COMPLETED", request.content_hash, event_time, artifacts)
            prior = completed
            self._fault("completed_intent")
        event = o.governor.record_trial(
            o.campaign,
            o.budget,
            events,
            trial,
            event_id=autonomous_trial_event_id(trial),
            occurred_at=event_time,
        )
        events = o.event_store.append(event, o.governor, o.campaign, o.budget)
        self._fault("trial_event")
        snapshot = o.current_ledger_snapshot(event_time, events)
        _, snapshot = o.reconcile_ledger(
            events, snapshot, event_time, hosted_evidence=self._evidence(state)
        )
        self._fault("ledger")
        terminal = HostedRequestTerminalReceipt(
            request_hash=request.content_hash,
            campaign_hash=state.spec.campaign_hash,
            outcome="STEP_COMPLETED",
            reason="RESEARCH_STEP_RECONCILED",
            authenticated_principal="service",
            recorded_at=event_time,
            business_artifact_hashes=tuple(
                sorted(
                    {
                        trial.content_hash,
                        event.content_hash,
                        snapshot.content_hash,
                        prior.content_hash,
                    }
                )
            ),
        )
        self._publish(state, "STEP_COMPLETED", request.content_hash, event_time, (terminal,))
        self._fault("step_completed")
        return True

    @staticmethod
    def _execution_port(o: AutonomousCampaignOrchestrator) -> HostedExecutionPort:
        port = o.execution_port
        if not callable(getattr(port, "execution_compute_charge", None)) or not callable(
            getattr(port, "verified_completed_execution", None)
        ):
            raise ArtifactIntegrityError(
                "execution port lacks hosted recovery and workload verification"
            )
        return cast(HostedExecutionPort, port)

    def _finalize(
        self,
        state: HostedStoreSnapshot,
        inputs: HostedCampaignInputs,
        events: tuple[CampaignChainEvent, ...],
        final_state: FinalState,
        reason: str,
    ) -> HostedCampaignStatus:
        o = inputs.orchestrator
        trials = tuple(
            event.trial
            for event in events
            if isinstance(event, ResearchCampaignEvent) and event.trial is not None
        )
        all_candidates = tuple(sorted(item.content_hash for item in o.manifest.candidates))
        attempted = tuple(sorted({trial.candidate_hash for trial in trials}))
        incomplete_dq_stop = self.is_incomplete_dq_stop(o, events, final_state)
        selection_hash = None
        run_status: Literal["SUCCEEDED", "FAILED"] = "FAILED"
        verdict: Literal["SELECTED", "NO_SELECTION", "NOT_EVALUATED"] = "NOT_EVALUATED"
        if final_state != "RECOVERY_REQUIRED" and not incomplete_dq_stop:
            selection, events, ledger, _, _ = o.selection_evidence_handoff(
                events, hosted_evidence=self._evidence(state)
            )
            selection_hash = selection.report_hash
            if final_state == "COMPLETED" and selection.run_status.value == "SUCCEEDED":
                run_status = "SUCCEEDED"
                verdict = cast(Literal["SELECTED", "NO_SELECTION"], selection.verdict.value)
            self._fault("selection_ledger")
        else:
            ledger = o.current_ledger_snapshot(state.spec.started_at, events)
        budget = self.verify_research_facts(state).budgets[-1]
        report = HostedCampaignReport(
            campaign_hash=state.spec.campaign_hash,
            hosted_spec_hash=state.spec.content_hash,
            candidate_manifest_hash=o.manifest.content_hash,
            candidate_hashes=all_candidates,
            attempted_candidate_hashes=attempted,
            remaining_candidate_hashes=tuple(x for x in all_candidates if x not in attempted),
            request_hashes=tuple(x.content_hash for x in state.requests),
            hosted_exchange_hashes=tuple(x.agent_run_hash for x in self._evidence(state)),
            trial_hashes=tuple(x.content_hash for x in trials),
            campaign_event_hashes=tuple(x.content_hash for x in events),
            initial_ledger_snapshot_hash=o.initial_ledger_snapshot.content_hash,
            final_ledger_snapshot_hash=ledger.content_hash,
            protocol_budget_hash=state.budget.content_hash,
            research_budget_hash=budget.content_hash,
            selection_report_hash=selection_hash,
            state=final_state,
            reason=reason,
            research_run_status=run_status,
            research_verdict=verdict,
            limitations=self.report_limitations(
                incomplete_dq_stop, sdk=isinstance(state.spec, SdkCampaignSpec)
            ),
            recorded_at=o.next_event_time(state.spec.started_at, events, ledger),
        )
        self._publish(state, "FINAL_REPORT", state.spec.content_hash, report.recorded_at, (report,))
        self._fault("final_report")
        return self.status(state.spec.campaign_hash)

    @staticmethod
    def is_incomplete_dq_stop(
        orchestrator: AutonomousCampaignOrchestrator,
        events: tuple[CampaignChainEvent, ...],
        final_state: str,
    ) -> bool:
        """A bounded stop can report missing candidates without invoking selection.

        The existing DQ preselection verifier still requires its full denominator.
        This is a failed hosted accounting report, never a P14c result or Q11 pass.
        """
        return (
            orchestrator.selection_finalization_profile
            in (P14DQ_REPORT_ONLY_FINALIZATION_PROFILE, SDK_BOUNDED_FINALIZATION_PROFILE)
            and final_state in ("CANCELLED", "EXPIRED", "EXHAUSTED")
            and {
                event.trial.candidate_hash
                for event in events
                if isinstance(event, ResearchCampaignEvent) and event.trial is not None
            }
            != {candidate.content_hash for candidate in orchestrator.manifest.candidates}
        )

    @staticmethod
    def report_limitations(
        incomplete_dq_stop: bool = False, *, sdk: bool = False
    ) -> tuple[str, ...]:
        base = (
            "HOST_INTERNAL_USAGE_UNAVAILABLE",
            "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "NOT_LIVE_OR_DEPLOYMENT_QUALIFICATION",
        )
        if sdk:
            base = SDK_BOUNDED_FINALIZATION_PROFILE.limitations
        return (
            (*base, "P14DQ_INCOMPLETE_DENOMINATOR_SELECTION_NOT_PERFORMED")
            if incomplete_dq_stop
            else base
        )

    def _verify_report(
        self, state: HostedStoreSnapshot, report: HostedCampaignReport, inputs: HostedCampaignInputs
    ) -> None:
        o = inputs.orchestrator
        events = o.event_store.load(o.governor, o.campaign, o.budget)
        incomplete_dq_stop = self.is_incomplete_dq_stop(o, events, report.state)
        if report.limitations != self.report_limitations(
            incomplete_dq_stop, sdk=isinstance(state.spec, SdkCampaignSpec)
        ) or (
            incomplete_dq_stop
            and (
                report.selection_report_hash is not None
                or report.research_run_status != "FAILED"
                or report.research_verdict != "NOT_EVALUATED"
            )
        ):
            raise ArtifactIntegrityError("incomplete DQ stop claims selection or different limits")
        ledger = o.current_ledger_snapshot(report.recorded_at, events)
        if (
            tuple(event.content_hash for event in events) != report.campaign_event_hashes
            or ledger.content_hash != report.final_ledger_snapshot_hash
            or report.candidate_hashes
            != tuple(sorted(x.content_hash for x in o.manifest.candidates))
        ):
            raise ArtifactIntegrityError("hosted final report authority has changed")
        trials = tuple(
            event.trial
            for event in events
            if isinstance(event, ResearchCampaignEvent) and event.trial is not None
        )
        if report.trial_hashes != tuple(trial.content_hash for trial in trials):
            raise ArtifactIntegrityError("final report trial inventory differs")
        evidence_by_run = {item.agent_run_hash: item for item in self._evidence(state)}
        for step in self.verify_research_facts(state).steps:
            if step.phase != "COMPLETED":
                continue
            trial = state.artifact(cast(str, step.trial_hash), CampaignTrial)
            indexes = tuple(
                index
                for index, event in enumerate(events)
                if isinstance(event, ResearchCampaignEvent) and event.trial == trial
            )
            if len(indexes) != 1:
                raise ArtifactIntegrityError("completed step lacks exactly one campaign event")
            prefix = events[: indexes[0]]
            prepared = o.prepare_trial(
                evidence_by_run[step.hosted_exchange_hash],
                events=prefix,
                event_time=step.event_time,
            )
            if prepared.execution_request != step.execution_request:
                raise ArtifactIntegrityError("final step execution identity differs")
            result = None
            if step.execution_request is not None:
                result = self._execution_port(o).verified_completed_execution(
                    step.execution_request
                )
                if result is None or result.content_hash != step.execution_result_hash:
                    raise ArtifactIntegrityError("final execution receipt changed or disappeared")
            if trial != o.finish_trial(prepared, result, events=prefix):
                raise ArtifactIntegrityError("final trial differs from verified execution outcome")
        if report.selection_report_hash is not None:
            path = o.selection_artifact_root / f"sha256-{report.selection_report_hash}"
            # P14c verifier uses its existing report publication layout.
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
            o.selection_service.verify_report(path, prefix)


FinalState = Literal["COMPLETED", "CANCELLED", "EXPIRED", "EXHAUSTED", "RECOVERY_REQUIRED"]
StatusState = Literal[
    "WAITING_FOR_AGENT",
    "EXECUTION_PENDING",
    "STEP_COMPLETED",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
    "EXHAUSTED",
    "RECOVERY_REQUIRED",
]
