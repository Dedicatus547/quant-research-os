"""Pre-frozen research-family, budget, campaign, and lifecycle contracts."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from math import prod
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.agent import CampaignSegment
from quantos.contracts.base import CanonicalContract, canonical_json_bytes
from quantos.contracts.evidence import LOGICAL_ID_PATTERN
from quantos.contracts.pit import SafeQlibOperator
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import ResearchSegment

ParameterValue = str | int | float | bool


def _hashes(value: tuple[str, ...], *, nonempty: bool = False) -> tuple[str, ...]:
    if (nonempty and not value) or value != tuple(sorted(set(value))):
        raise ValueError("campaign hashes must be sorted and unique")
    if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
        raise ValueError("campaign hash reference is invalid")
    return value


class ParameterDimension(CanonicalContract):
    schema_version: Literal["research-parameter-dimension/v1"] = "research-parameter-dimension/v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    values: tuple[ParameterValue, ...]

    @field_validator("values")
    @classmethod
    def values_are_finite_and_unique(
        cls, value: tuple[ParameterValue, ...]
    ) -> tuple[ParameterValue, ...]:
        encoded = [canonical_json_bytes(item) for item in value]
        if not encoded or len(encoded) != len(set(encoded)):
            raise ValueError("parameter values must be nonempty and unique")
        return value


class ResearchFamilySpec(CanonicalContract):
    schema_version: Literal["research-family/v1"] = "research-family/v1"
    family_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    research_question: str = Field(min_length=1, max_length=20_000)
    hypothesis_hash: str = Field(pattern=SHA256_PATTERN)
    factor_template_hash: str = Field(pattern=SHA256_PATTERN)
    allowed_operators: tuple[SafeQlibOperator, ...]
    parameter_space: tuple[ParameterDimension, ...]
    declared_candidate_count: PositiveInt

    @field_validator("allowed_operators")
    @classmethod
    def operators_are_nonempty_sorted(
        cls, value: tuple[SafeQlibOperator, ...]
    ) -> tuple[SafeQlibOperator, ...]:
        if not value or list(value) != sorted(set(value), key=str):
            raise ValueError("allowed operators must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def finite_search_space_matches_declaration(self) -> Self:
        names = [item.name for item in self.parameter_space]
        if not names or names != sorted(set(names)):
            raise ValueError("parameter dimensions must be nonempty, sorted, and unique")
        count = prod(len(item.values) for item in self.parameter_space)
        if count != self.declared_candidate_count:
            raise ValueError("declared candidate count does not match the frozen parameter space")
        return self


class ResearchBudgetSpec(CanonicalContract):
    schema_version: Literal["research-budget/v1"] = "research-budget/v1"
    budget_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    max_trials: PositiveInt
    max_distinct_candidates: PositiveInt
    max_agent_runs: PositiveInt
    max_executions: PositiveInt
    max_validation_rounds: PositiveInt
    max_compute_seconds: PositiveInt
    max_sealed_confirmation_accesses: Literal[1] = 1

    @model_validator(mode="after")
    def internal_limits_are_consistent(self) -> Self:
        if self.max_distinct_candidates > self.max_trials:
            raise ValueError("distinct candidate budget cannot exceed trial budget")
        if self.max_executions > self.max_trials:
            raise ValueError("execution budget cannot exceed trial budget")
        if self.max_validation_rounds > self.max_executions:
            raise ValueError("validation budget cannot exceed execution budget")
        return self


class MultipleTestingPolicy(StrEnum):
    PREFROZEN_FINITE_FAMILY = "PREFROZEN_FINITE_FAMILY"


class CampaignStoppingRule(StrEnum):
    BUDGET_EXHAUSTED_OR_MANUAL_CLOSE = "BUDGET_EXHAUSTED_OR_MANUAL_CLOSE"


class ResearchCampaignSpec(CanonicalContract):
    schema_version: Literal["research-campaign/v1"] = "research-campaign/v1"
    campaign_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    research_question: str = Field(min_length=1, max_length=20_000)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hashes: tuple[str, ...]
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    feature_artifact_hashes: tuple[str, ...] = ()
    development: ResearchSegment
    validation: ResearchSegment
    sealed_confirmation: ResearchSegment
    multiple_testing_policy: MultipleTestingPolicy
    stopping_rule: CampaignStoppingRule
    parent_campaign_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    inherited_contamination: tuple[str, ...] = ()

    @field_validator("evidence_hashes")
    @classmethod
    def evidence_is_frozen(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value, nonempty=True)

    @field_validator("feature_artifact_hashes", "inherited_contamination")
    @classmethod
    def optional_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value)

    @model_validator(mode="after")
    def periods_and_lineage_are_valid(self) -> Self:
        periods = (self.development, self.validation, self.sealed_confirmation)
        if any(left.end >= right.start for left, right in pairwise(periods)):
            raise ValueError("campaign periods must be ordered, disjoint, and pre-frozen")
        if self.parent_campaign_hash is None and self.inherited_contamination:
            raise ValueError("root campaign cannot inherit contamination")
        if self.parent_campaign_hash is not None and not self.inherited_contamination:
            raise ValueError("child campaign must declare inherited contamination")
        return self


class TrialOutcome(StrEnum):
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    HARD_REJECT = "HARD_REJECT"
    PASS = "PASS"
    PIT_REJECT = "PIT_REJECT"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SOFT_REJECT = "SOFT_REJECT"


class CampaignTrial(CanonicalContract):
    schema_version: Literal["campaign-trial/v1"] = "campaign-trial/v1"
    trial_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    proposal_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    segment: CampaignSegment
    outcome: TrialOutcome
    agent_run_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    execution_requested: bool
    compute_seconds: NonNegativeInt = 0
    evidence_hashes: tuple[str, ...] = ()

    @field_validator("evidence_hashes")
    @classmethod
    def evidence_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value)

    @model_validator(mode="after")
    def outcome_matches_execution(self) -> Self:
        executed_outcomes = {
            TrialOutcome.EXECUTION_FAILED,
            TrialOutcome.HARD_REJECT,
            TrialOutcome.PASS,
            TrialOutcome.SOFT_REJECT,
        }
        if (self.outcome in executed_outcomes) != self.execution_requested:
            raise ValueError("trial outcome and execution accounting disagree")
        return self


class CampaignEventType(StrEnum):
    ACTIVATED = "CampaignActivated"
    CLOSED = "CampaignClosed"
    OOS_ACCESSED = "OOSAccessed"
    TRIAL_RECORDED = "CampaignTrialRecorded"


class ResearchCampaignEvent(CanonicalContract):
    schema_version: Literal["research-campaign-event/v1"] = "research-campaign-event/v1"
    event_id: UUID
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    sequence: PositiveInt
    event_type: CampaignEventType
    occurred_at: datetime
    previous_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    trial: CampaignTrial | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("campaign event timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def payload_matches_event_type(self) -> Self:
        if self.event_type in {CampaignEventType.TRIAL_RECORDED, CampaignEventType.OOS_ACCESSED}:
            if self.trial is None or self.reason is not None:
                raise ValueError("trial/OOS event requires only a trial payload")
        elif self.trial is not None or self.reason is None:
            raise ValueError("activation/close event requires only a reason")
        if self.event_type is CampaignEventType.OOS_ACCESSED:
            if self.trial is None or self.trial.segment is not CampaignSegment.SEALED_CONFIRMATION:
                raise ValueError("OOS access must bind a sealed-confirmation trial")
        elif self.trial is not None and self.trial.segment is CampaignSegment.SEALED_CONFIRMATION:
            raise ValueError("sealed-confirmation trials require OOSAccessed")
        return self


class CampaignLifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    DRAFT = "DRAFT"


class ResearchCampaignSnapshot(CanonicalContract):
    schema_version: Literal["research-campaign-snapshot/v1"] = "research-campaign-snapshot/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    status: CampaignLifecycleStatus
    source_event_hashes: tuple[str, ...]
    trial_count: NonNegativeInt
    distinct_candidate_count: NonNegativeInt
    agent_run_count: NonNegativeInt
    execution_count: NonNegativeInt
    validation_round_count: NonNegativeInt
    compute_seconds: NonNegativeInt
    sealed_confirmation_accessed: bool
    contamination_hashes: tuple[str, ...]

    @field_validator("source_event_hashes")
    @classmethod
    def event_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("campaign event hashes must be unique")
        return value

    @field_validator("contamination_hashes")
    @classmethod
    def contamination_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value)
