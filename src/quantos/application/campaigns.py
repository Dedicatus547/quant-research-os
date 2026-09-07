"""Deterministic governance for pre-frozen research campaigns."""

from __future__ import annotations

from datetime import datetime
from typing import NoReturn
from uuid import UUID

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
from quantos.contracts.status import ReasonCode


class CampaignGovernanceError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _raise(reason_code: ReasonCode, message: str) -> NoReturn:
    raise CampaignGovernanceError(reason_code, message)


class ResearchCampaignGovernor:
    """Validate and extend an immutable campaign event chain."""

    def project(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[ResearchCampaignEvent, ...],
    ) -> ResearchCampaignSnapshot:
        if campaign.budget_hash != budget.content_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign does not bind the supplied budget")
        status = CampaignLifecycleStatus.DRAFT
        previous_hash: str | None = None
        previous_time: datetime | None = None
        trials: list[CampaignTrial] = []
        event_hashes: list[str] = []
        idempotency: dict[str, str] = {}
        sealed_accessed = False
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
                trial = event.trial
                if trial is None:  # contract validation already enforces this
                    _raise(ReasonCode.SCHEMA_INVALID, "campaign trial payload is missing")
                existing = idempotency.get(trial.idempotency_key)
                if existing is not None and existing != trial.content_hash:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "idempotency key binds two trials")
                if existing is not None:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "trial was appended more than once")
                idempotency[trial.idempotency_key] = trial.content_hash
                trials.append(trial)
                if event.event_type is CampaignEventType.OOS_ACCESSED:
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
        events: tuple[ResearchCampaignEvent, ...],
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
        if campaign.family_hash != family.content_hash:
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
        events: tuple[ResearchCampaignEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
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

    def access_sealed_confirmation(
        self,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
        events: tuple[ResearchCampaignEvent, ...],
        trial: CampaignTrial,
        *,
        event_id: UUID,
        occurred_at: datetime,
    ) -> ResearchCampaignEvent:
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
        events: tuple[ResearchCampaignEvent, ...],
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

    @staticmethod
    def authorize_factor(family: ResearchFamilySpec, proposal: object) -> None:
        from quantos.contracts.agent import FactorProposalSpec

        if not isinstance(proposal, FactorProposalSpec):
            _raise(ReasonCode.SCHEMA_INVALID, "factor proposal contract is invalid")
        operators = {node.operator for node in proposal.expression.nodes}
        if (
            proposal.hypothesis_hash != family.hypothesis_hash
            or proposal.family_hash != family.content_hash
            or proposal.factor_template_hash != family.factor_template_hash
            or not operators.issubset(family.allowed_operators)
        ):
            _raise(
                ReasonCode.SCHEMA_INVALID,
                "factor proposal escapes its frozen research family",
            )
        proposed = {item.name: canonical_json_bytes(item.value) for item in proposal.parameters}
        allowed = {
            item.name: {canonical_json_bytes(value) for value in item.values}
            for item in family.parameter_space
        }
        if proposed.keys() != allowed.keys() or any(
            proposed[name] not in allowed[name] for name in proposed
        ):
            _raise(
                ReasonCode.SCHEMA_INVALID,
                "factor proposal parameters escape the frozen finite search space",
            )

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
        events: tuple[ResearchCampaignEvent, ...], trial: CampaignTrial
    ) -> ResearchCampaignEvent | None:
        matches = [
            event
            for event in events
            if event.trial is not None and event.trial.idempotency_key == trial.idempotency_key
        ]
        if not matches:
            return None
        if len(matches) != 1 or matches[0].trial != trial:
            _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "idempotency key conflicts")
        return matches[0]

    @staticmethod
    def _event(
        campaign: ResearchCampaignSpec,
        events: tuple[ResearchCampaignEvent, ...],
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
