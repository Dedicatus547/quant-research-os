"""Deterministic governance for pre-frozen research campaigns."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn
from uuid import UUID

from quantos.application.enumeration import (
    CandidateEnumerationError,
    exact_expression_hash,
    structural_expression_hash,
    verify_candidate_enumeration_manifest,
)
from quantos.contracts.agent import CampaignSegment, ExperimentProposalSpec, InterpretationProposal
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    CampaignLifecycleStatus,
    CampaignTrial,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSnapshot,
    ResearchCampaignSpec,
    ResearchFamilySpec,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionPlan,
    CampaignSelectionReport,
    CampaignSelectionVerdict,
)
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.status import ReasonCode


class CampaignGovernanceError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


CampaignChainEvent = ResearchCampaignEvent | CampaignSelectionEvent


def _raise(reason_code: ReasonCode, message: str) -> NoReturn:
    raise CampaignGovernanceError(reason_code, message)


class ResearchCampaignGovernor:
    """Validate and extend an immutable campaign event chain."""

    def __init__(
        self,
        family: ResearchFamilySpec,
        template: ResearchFactorTemplateSpec,
        manifest: CandidateEnumerationManifest,
    ) -> None:
        try:
            verify_candidate_enumeration_manifest(family, template, manifest)
        except CandidateEnumerationError as error:
            raise CampaignGovernanceError(error.reason_code, str(error)) from error
        self.family = family
        self.manifest = manifest
        self.candidate_hashes = frozenset(item.content_hash for item in manifest.candidates)

    def project(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
    ) -> ResearchCampaignSnapshot:
        if campaign.family_hash != self.family.content_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the frozen family")
        if campaign.budget_hash != budget.content_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the supplied budget")
        status = CampaignLifecycleStatus.DRAFT
        previous_hash: str | None = None
        previous_time: datetime | None = None
        trials: list[CampaignTrial] = []
        event_hashes: list[str] = []
        idempotency: dict[str, str] = {}
        sealed_accessed = False
        plan_event: CampaignSelectionEvent | None = None
        selection_event: CampaignSelectionEvent | None = None
        for expected_sequence, event in enumerate(events, start=1):
            if (
                event.campaign_hash != campaign.content_hash
                or event.sequence != expected_sequence
                or event.previous_event_hash != previous_hash
            ):
                _raise(ReasonCode.EVENT_CHAIN_INVALID, "campaign event chain is inconsistent")
            if previous_time is not None and event.occurred_at < previous_time:
                _raise(ReasonCode.EVENT_CHAIN_INVALID, "campaign event time moved backwards")
            if status is CampaignLifecycleStatus.CLOSED:
                _raise(ReasonCode.CAMPAIGN_CLOSED, "closed campaign cannot accept events")
            if isinstance(event, CampaignSelectionEvent):
                if status is not CampaignLifecycleStatus.ACTIVE:
                    _raise(ReasonCode.STATE_TRANSITION_INVALID, "campaign must be activated first")
                if event.event_type is CampaignSelectionEventType.PLAN_FROZEN:
                    if (
                        plan_event is not None
                        or selection_event is not None
                        or expected_sequence != 2
                        or not isinstance(events[0], ResearchCampaignEvent)
                        or events[0].event_type is not CampaignEventType.ACTIVATED
                    ):
                        _raise(
                            ReasonCode.STATE_TRANSITION_INVALID,
                            "selection plan must be frozen immediately after activation",
                        )
                    plan_event = event
                elif event.event_type is CampaignSelectionEventType.SELECTION_FROZEN:
                    if plan_event is None or selection_event is not None or sealed_accessed:
                        _raise(
                            ReasonCode.STATE_TRANSITION_INVALID,
                            "selection requires one prior plan and must precede sealed access",
                        )
                    if event.selection_plan_hash != plan_event.selection_plan_hash:
                        _raise(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "selection freeze does not bind the frozen plan",
                        )
                    selection_event = event
                previous_hash = event.content_hash
                previous_time = event.occurred_at
                event_hashes.append(event.content_hash)
                continue

            if event.event_type is CampaignEventType.ACTIVATED:
                if status is not CampaignLifecycleStatus.DRAFT:
                    _raise(ReasonCode.STATE_TRANSITION_INVALID, "campaign is already active")
                status = CampaignLifecycleStatus.ACTIVE
            elif status is not CampaignLifecycleStatus.ACTIVE:
                _raise(ReasonCode.STATE_TRANSITION_INVALID, "campaign must be activated first")
            elif event.event_type in {
                CampaignEventType.TRIAL_RECORDED,
                CampaignEventType.OOS_ACCESSED,
            }:
                if (
                    selection_event is not None
                    and event.event_type is CampaignEventType.TRIAL_RECORDED
                ):
                    _raise(
                        ReasonCode.STATE_TRANSITION_INVALID,
                        "no development or validation trial may follow campaign selection",
                    )
                trial = event.trial
                if trial is None:  # contract validation already enforces this
                    _raise(ReasonCode.SCHEMA_INVALID, "campaign trial payload is missing")
                self._require_candidate(trial)
                existing = idempotency.get(trial.idempotency_key)
                if existing is not None and existing != trial.content_hash:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "idempotency key binds two trials")
                if existing is not None:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "trial was appended more than once")
                idempotency[trial.idempotency_key] = trial.content_hash
                trials.append(trial)
                if event.event_type is CampaignEventType.OOS_ACCESSED:
                    if plan_event is not None and (
                        selection_event is None
                        or selection_event.selected_candidate_hash != trial.candidate_hash
                    ):
                        _raise(
                            ReasonCode.OOS_POLICY_VIOLATION,
                            "sealed trial must bind the frozen selected candidate",
                        )
                    if sealed_accessed:
                        _raise(
                            ReasonCode.OOS_ALREADY_ACCESSED,
                            "sealed confirmation was already accessed",
                        )
                    sealed_accessed = True
                    status = CampaignLifecycleStatus.CLOSED
            elif event.event_type is CampaignEventType.CLOSED:
                status = CampaignLifecycleStatus.CLOSED
            previous_hash = event.content_hash
            previous_time = event.occurred_at
            event_hashes.append(event.content_hash)
            self._enforce_budget(budget, trials, sealed_accessed)

        contamination = set(campaign.inherited_contamination)
        if sealed_accessed:
            contamination.add(campaign.content_hash)
        return ResearchCampaignSnapshot(
            campaign_hash=campaign.content_hash,
            status=status,
            source_event_hashes=tuple(event_hashes),
            trial_count=len(trials),
            distinct_candidate_count=len({item.candidate_hash for item in trials}),
            agent_run_count=len(
                {item.agent_run_hash for item in trials if item.agent_run_hash is not None}
            ),
            execution_count=sum(item.execution_requested for item in trials),
            validation_round_count=sum(
                item.segment is CampaignSegment.VALIDATION for item in trials
            ),
            compute_seconds=sum(item.compute_seconds for item in trials),
            sealed_confirmation_accessed=sealed_accessed,
            contamination_hashes=tuple(sorted(contamination)),
        )

    def activate(
        self,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        if campaign.family_hash != family.content_hash or family != self.family:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the supplied family")
        if budget.max_distinct_candidates > family.declared_candidate_count:
            _raise(
                ReasonCode.SCHEMA_INVALID,
                "candidate budget exceeds the pre-frozen family search space",
            )
        snapshot = self.project(campaign, budget, events)
        if snapshot.status is not CampaignLifecycleStatus.DRAFT:
            _raise(ReasonCode.STATE_TRANSITION_INVALID, "only a draft campaign can activate")
        return self._event(
            campaign,
            events,
            event_id=event_id,
            occurred_at=occurred_at,
            event_type=CampaignEventType.ACTIVATED,
            reason="pre-frozen campaign activated",
        )

    def record_trial(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        self._require_candidate(trial)
        snapshot = self.project(campaign, budget, events)
        if snapshot.status is not CampaignLifecycleStatus.ACTIVE:
            _raise(ReasonCode.CAMPAIGN_CLOSED, "campaign does not accept another trial")
        if trial.segment is CampaignSegment.SEALED_CONFIRMATION:
            _raise(ReasonCode.OOS_POLICY_VIOLATION, "sealed trial requires one-time OOS access")
        existing = self._idempotent_trial(events, trial)
        if existing is not None:
            return existing
        event = self._event(
            campaign,
            events,
            event_id=event_id,
            occurred_at=occurred_at,
            event_type=CampaignEventType.TRIAL_RECORDED,
            trial=trial,
        )
        self.project(campaign, budget, (*events, event))
        return event

    def record_selection_trial(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        selection_plan: CampaignSelectionPlan,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        """Record a trial on the P14c path only after the matching plan is frozen."""

        plan_events = [
            event
            for event in events
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
        ]
        if (
            len(plan_events) != 1
            or plan_events[0].selection_plan_hash != selection_plan.content_hash
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "P14c trial requires the unique matching SelectionPlanFrozen event",
            )
        return self.record_trial(
            campaign,
            budget,
            events,
            trial,
            event_id=event_id,
            occurred_at=occurred_at,
        )

    def access_sealed_confirmation(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        if any(
            isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
            for event in events
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "P14c sealed access must use the report-verifying CampaignSelectionService",
            )
        return self._access_sealed_confirmation(
            campaign,
            budget,
            events,
            trial,
            event_id=event_id,
            occurred_at=occurred_at,
        )

    def _access_verified_selection_confirmation(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        plans = [
            event
            for event in events
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
        ]
        selections = [
            event
            for event in events
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.SELECTION_FROZEN
        ]
        if (
            len(plans) != 1
            or len(selections) != 1
            or selections[0].selection_plan_hash != plans[0].selection_plan_hash
            or selections[0].selected_candidate_hash != trial.candidate_hash
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "verified sealed access must bind the unique frozen selected candidate",
            )
        return self._access_sealed_confirmation(
            campaign,
            budget,
            events,
            trial,
            event_id=event_id,
            occurred_at=occurred_at,
        )

    def _access_sealed_confirmation(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        self._require_candidate(trial)
        snapshot = self.project(campaign, budget, events)
        if snapshot.sealed_confirmation_accessed:
            _raise(ReasonCode.OOS_ALREADY_ACCESSED, "sealed confirmation is one-time")
        if snapshot.status is not CampaignLifecycleStatus.ACTIVE:
            _raise(ReasonCode.CAMPAIGN_CLOSED, "campaign cannot access sealed confirmation")
        if trial.segment is not CampaignSegment.SEALED_CONFIRMATION:
            _raise(ReasonCode.SCHEMA_INVALID, "OOS access requires a sealed-confirmation trial")
        event = self._event(
            campaign,
            events,
            event_id=event_id,
            occurred_at=occurred_at,
            event_type=CampaignEventType.OOS_ACCESSED,
            trial=trial,
        )
        self.project(campaign, budget, (*events, event))
        return event

    def close(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        *,
        event_id: UUID,
        occurred_at: datetime,
        reason: str,
    ) -> ResearchCampaignEvent:
        snapshot = self.project(campaign, budget, events)
        if snapshot.status is not CampaignLifecycleStatus.ACTIVE:
            _raise(ReasonCode.CAMPAIGN_CLOSED, "only an active campaign can close")
        return self._event(
            campaign,
            events,
            event_id=event_id,
            occurred_at=occurred_at,
            event_type=CampaignEventType.CLOSED,
            reason=reason,
        )

    @staticmethod
    def authorize_proposal(
        campaign: ResearchCampaignSpec,
        snapshot: ResearchCampaignSnapshot,
        proposal: ExperimentProposalSpec,
    ) -> None:
        if proposal.campaign_hash != campaign.content_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "proposal does not bind its campaign")
        if snapshot.status is not CampaignLifecycleStatus.ACTIVE:
            _raise(ReasonCode.CAMPAIGN_CLOSED, "campaign is not active")
        if (
            proposal.snapshot_hash != campaign.snapshot_hash
            or proposal.qlib_view_hash != campaign.qlib_view_hash
            or proposal.feature_artifact_hashes != campaign.feature_artifact_hashes
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "proposal inputs differ from campaign inputs")
        segment = {
            CampaignSegment.DEVELOPMENT: campaign.development,
            CampaignSegment.VALIDATION: campaign.validation,
            CampaignSegment.SEALED_CONFIRMATION: campaign.sealed_confirmation,
        }[proposal.segment]
        if proposal.evaluation_start < segment.start or proposal.evaluation_end > segment.end:
            _raise(ReasonCode.OOS_POLICY_VIOLATION, "proposal escapes its frozen segment")
        if proposal.segment is CampaignSegment.SEALED_CONFIRMATION:
            _raise(ReasonCode.OOS_POLICY_VIOLATION, "sealed proposal requires one-time access")

    def authorize_factor(self, family: ResearchFamilySpec, proposal: object) -> None:
        from quantos.contracts.agent import FactorProposalSpec

        if not isinstance(proposal, FactorProposalSpec):
            _raise(ReasonCode.SCHEMA_INVALID, "factor proposal contract is invalid")
        operators = {node.operator for node in proposal.expression.nodes}
        if (
            family != self.family
            or self.manifest.family_hash != family.content_hash
            or self.manifest.factor_template_hash != family.factor_template_hash
            or proposal.hypothesis_hash != family.hypothesis_hash
            or proposal.family_hash != family.content_hash
            or proposal.factor_template_hash != family.factor_template_hash
            or not operators.issubset(family.allowed_operators)
        ):
            _raise(
                ReasonCode.SCHEMA_INVALID,
                "factor proposal escapes its frozen research family",
            )
        proposed = canonical_json_bytes(
            tuple((item.name, item.value) for item in proposal.parameters)
        )
        matches = [
            candidate
            for candidate in self.manifest.candidates
            if canonical_json_bytes(tuple((item.name, item.value) for item in candidate.parameters))
            == proposed
        ]
        if len(matches) != 1:
            _raise(
                ReasonCode.SCHEMA_INVALID,
                "factor proposal does not identify one frozen candidate",
            )
        candidate = matches[0]
        if (
            exact_expression_hash(proposal.expression) != candidate.exact_expression_hash
            or structural_expression_hash(proposal.expression)
            != candidate.structural_expression_hash
        ):
            _raise(ReasonCode.SCHEMA_INVALID, "factor proposal expression differs from candidate")

    def _require_candidate(self, trial: CampaignTrial) -> None:
        if trial.candidate_hash not in self.candidate_hashes:
            _raise(ReasonCode.SCHEMA_INVALID, "trial candidate is outside the frozen manifest")

    @staticmethod
    def require_interpretation_contamination(
        snapshot: ResearchCampaignSnapshot, proposal: InterpretationProposal
    ) -> None:
        required = set(snapshot.contamination_hashes)
        if not required.issubset(proposal.inherited_contamination):
            _raise(
                ReasonCode.CONTAMINATION_REQUIRED,
                "interpretation does not inherit sealed-result contamination",
            )

    @staticmethod
    def authorize_child_campaign(
        parent: ResearchCampaignSpec,
        parent_snapshot: ResearchCampaignSnapshot,
        child: ResearchCampaignSpec,
    ) -> None:
        required = set(parent_snapshot.contamination_hashes)
        if child.parent_campaign_hash != parent.content_hash or not required.issubset(
            child.inherited_contamination
        ):
            _raise(
                ReasonCode.CONTAMINATION_REQUIRED,
                "child campaign does not preserve parent lineage and contamination",
            )
        if parent_snapshot.sealed_confirmation_accessed and (
            child.snapshot_hash == parent.snapshot_hash
            or child.sealed_confirmation.start <= parent.sealed_confirmation.end
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "post-confirmation child requires a new snapshot and unexposed future window",
            )

    @staticmethod
    def _enforce_budget(
        budget: ResearchBudgetSpec,
        trials: list[CampaignTrial],
        sealed_accessed: bool,
    ) -> None:
        usage = {
            "trials": len(trials),
            "distinct candidates": len({item.candidate_hash for item in trials}),
            "Agent runs": len(
                {item.agent_run_hash for item in trials if item.agent_run_hash is not None}
            ),
            "executions": sum(item.execution_requested for item in trials),
            "validation rounds": sum(item.segment is CampaignSegment.VALIDATION for item in trials),
            "compute seconds": sum(item.compute_seconds for item in trials),
            "sealed accesses": int(sealed_accessed),
        }
        limits = {
            "trials": budget.max_trials,
            "distinct candidates": budget.max_distinct_candidates,
            "Agent runs": budget.max_agent_runs,
            "executions": budget.max_executions,
            "validation rounds": budget.max_validation_rounds,
            "compute seconds": budget.max_compute_seconds,
            "sealed accesses": budget.max_sealed_confirmation_accesses,
        }
        if any(usage[key] > limits[key] for key in usage):
            _raise(ReasonCode.RESEARCH_BUDGET_EXCEEDED, "research campaign budget exceeded")

    @staticmethod
    def _idempotent_trial(
        events: tuple[CampaignChainEvent, ...], trial: CampaignTrial
    ) -> ResearchCampaignEvent | None:
        matches = [
            event
            for event in events
            if isinstance(event, ResearchCampaignEvent)
            and event.trial is not None
            and event.trial.idempotency_key == trial.idempotency_key
        ]
        if not matches:
            return None
        if len(matches) != 1 or matches[0].trial != trial:
            _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "idempotency key conflicts")
        return matches[0]

    @staticmethod
    def _event(
        campaign: ResearchCampaignSpec,
        events: tuple[CampaignChainEvent, ...],
        *,
        event_id: UUID,
        occurred_at: datetime,
        event_type: CampaignEventType,
        trial: CampaignTrial | None = None,
        reason: str | None = None,
    ) -> ResearchCampaignEvent:
        return ResearchCampaignEvent(
            event_id=event_id,
            campaign_hash=campaign.content_hash,
            sequence=len(events) + 1,
            event_type=event_type,
            occurred_at=occurred_at,
            previous_event_hash=events[-1].content_hash if events else None,
            trial=trial,
            reason=reason,
        )

    def freeze_selection_plan(
        self,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        manifest: CandidateEnumerationManifest,
        events: tuple[CampaignChainEvent, ...],
        plan: CampaignSelectionPlan,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> CampaignSelectionEvent:
        """Reject direct plan claims; use CampaignSelectionService.freeze_plan."""

        del campaign, family, budget, manifest, events, plan, event_id, occurred_at
        _raise(
            ReasonCode.OOS_POLICY_VIOLATION,
            "selection plan must be frozen through a verifying CampaignSelectionService",
        )

    def _freeze_verified_plan(
        self,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        manifest: CandidateEnumerationManifest,
        events: tuple[CampaignChainEvent, ...],
        plan: CampaignSelectionPlan,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> CampaignSelectionEvent:
        """Append a service-verified preregistration immediately after activation.

        Legacy v1 chains remain projectable. A chain becomes selection-authoritative only
        when this event is present before its first trial.
        """

        snapshot = self.project(campaign, budget, events)
        if snapshot.status is not CampaignLifecycleStatus.ACTIVE or len(events) != 1:
            _raise(
                ReasonCode.STATE_TRANSITION_INVALID,
                "selection plan must follow activation before any other campaign event",
            )
        activation = events[0]
        if not isinstance(activation, ResearchCampaignEvent) or (
            activation.event_type is not CampaignEventType.ACTIVATED
        ):
            _raise(ReasonCode.STATE_TRANSITION_INVALID, "campaign activation event is missing")
        if campaign.multiple_testing_policy.value != "PREFROZEN_FINITE_FAMILY":
            _raise(ReasonCode.SCHEMA_INVALID, "campaign policy is not a pre-frozen finite family")
        if (
            campaign.family_hash != family.content_hash
            or family != self.family
            or budget.content_hash != campaign.budget_hash
            or manifest != self.manifest
            or plan.campaign_hash != campaign.content_hash
            or plan.family_hash != family.content_hash
            or plan.budget_hash != budget.content_hash
            or plan.candidate_manifest_hash != manifest.content_hash
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "selection plan bindings do not match campaign")
        event = CampaignSelectionEvent(
            event_id=event_id,
            campaign_hash=campaign.content_hash,
            sequence=len(events) + 1,
            event_type=CampaignSelectionEventType.PLAN_FROZEN,
            occurred_at=occurred_at,
            previous_event_hash=activation.content_hash,
            selection_plan_hash=plan.content_hash,
        )
        self.project(campaign, budget, (*events, event))
        return event

    def freeze_selection(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        report: CampaignSelectionReport,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> CampaignSelectionEvent:
        """Reject direct report claims; use CampaignSelectionService.freeze_selection.

        This governor does not have the artifact roots needed to recompute a report. Its
        public entry point therefore cannot grant selection authority from a self-hashed
        object alone. The selection service verifies the immutable artifact and calls the
        private event constructor below.
        """

        del campaign, budget, events, report, event_id, occurred_at
        _raise(
            ReasonCode.OOS_POLICY_VIOLATION,
            "selection must be frozen through a report-verifying CampaignSelectionService",
        )

    def _freeze_verified_selection(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[CampaignChainEvent, ...],
        report: CampaignSelectionReport,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> CampaignSelectionEvent:
        """Create the event after the selection service has recomputed the artifact."""

        snapshot = self.project(campaign, budget, events)
        plans = [
            event
            for event in events
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
        ]
        if (
            snapshot.status is not CampaignLifecycleStatus.ACTIVE
            or len(plans) != 1
            or report.verdict is not CampaignSelectionVerdict.SELECTED
            or report.run_status.value != "SUCCEEDED"
            or report.selected_candidate_hash is None
            or report.campaign_hash != campaign.content_hash
            or report.selection_plan_hash != plans[0].selection_plan_hash
            or report.source_event_hashes != tuple(event.content_hash for event in events)
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "selection freeze requires one recomputed selected report for the event prefix",
            )
        event = CampaignSelectionEvent(
            event_id=event_id,
            campaign_hash=campaign.content_hash,
            sequence=len(events) + 1,
            event_type=CampaignSelectionEventType.SELECTION_FROZEN,
            occurred_at=occurred_at,
            previous_event_hash=events[-1].content_hash,
            selection_plan_hash=plans[0].selection_plan_hash,
            selection_report_hash=report.report_hash,
            selected_candidate_hash=report.selected_candidate_hash,
        )
        self.project(campaign, budget, (*events, event))
        return event
