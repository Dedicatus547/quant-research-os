"""Frozen P14c campaign selection inputs, accounting, and verdict contracts.

These schemas contain no statistical execution or external service dependencies.
The method and cross-artifact verification rules are specified in
docs/p14c-selection-contract.md.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ReasonCode, RunStatus


def _unique_hashes(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError("hash references must be unique")
    return value


class MultipleTestingPolicySpec(CanonicalContract):
    """One-sided mean Rank IC, centered circular blocks, and Holm over the full family."""

    schema_version: Literal["multiple-testing-policy/v1"] = "multiple-testing-policy/v1"
    method: Literal["HOLM_CIRCULAR_BLOCK_BOOTSTRAP_V1"] = "HOLM_CIRCULAR_BLOCK_BOOTSTRAP_V1"
    alpha: float = Field(default=0.05, ge=0.05, le=0.05)
    bootstrap_replicates: Literal[9999] = 9999
    block_length: Literal[5] = 5
    minimum_sessions: Literal[40] = 40
    random_stream: Literal["SHA256_COUNTER_U64_REJECTION_V1"] = "SHA256_COUNTER_U64_REJECTION_V1"
    seed: str = Field(pattern=SHA256_PATTERN)
    null_hypothesis: Literal["ORIENTED_MEAN_RANK_IC_LE_ZERO"] = "ORIENTED_MEAN_RANK_IC_LE_ZERO"
    family_denominator: Literal["ALL_ENUMERATED_CANDIDATES"] = "ALL_ENUMERATED_CANDIDATES"


class SelectionPolicySpec(CanonicalContract):
    schema_version: Literal["selection-policy/v1"] = "selection-policy/v1"
    multiple_testing_policy_hash: str = Field(pattern=SHA256_PATTERN)
    direction: Literal["POSITIVE", "NEGATIVE"]
    primary_statistic: Literal["MEAN_DAILY_RANK_IC"] = "MEAN_DAILY_RANK_IC"
    evaluation_segment: Literal["VALIDATION"] = "VALIDATION"
    calendar_source: Literal["QLIB_VIEW_TRADING_CALENDAR"] = "QLIB_VIEW_TRADING_CALENDAR"
    max_selected: Literal[1] = 1
    tie_breaker: Literal["ADJUSTED_P_THEN_MEAN_THEN_CANDIDATE_HASH"] = (
        "ADJUSTED_P_THEN_MEAN_THEN_CANDIDATE_HASH"
    )
    empirical_redundancy: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class CampaignSelectionPlan(CanonicalContract):
    """Must be frozen in the event chain before the first trial."""

    schema_version: Literal["campaign-selection-plan/v1"] = "campaign-selection-plan/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    multiple_testing_policy_hash: str = Field(pattern=SHA256_PATTERN)
    selection_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_calendar_hash: str = Field(pattern=SHA256_PATTERN)


class SelectionCalendar(CanonicalContract):
    schema_version: Literal["selection-calendar/v1"] = "selection-calendar/v1"
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    start: date
    end: date
    trading_dates: tuple[date, ...]

    @model_validator(mode="after")
    def dates_match_range(self) -> Self:
        if (
            self.start > self.end
            or not self.trading_dates
            or self.trading_dates != tuple(sorted(set(self.trading_dates)))
            or self.trading_dates[0] < self.start
            or self.trading_dates[-1] > self.end
        ):
            raise ValueError("selection calendar requires unique ordered in-range dates")
        return self


class CampaignSelectionEventType(StrEnum):
    PLAN_FROZEN = "SelectionPlanFrozen"
    SELECTION_FROZEN = "SelectionFrozen"


class CampaignSelectionEvent(CanonicalContract):
    """A new event schema preserves the already frozen campaign-event/v1 bytes."""

    schema_version: Literal["campaign-selection-event/v1"] = "campaign-selection-event/v1"
    event_id: UUID
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    sequence: PositiveInt
    event_type: CampaignSelectionEventType
    occurred_at: datetime
    previous_event_hash: str = Field(pattern=SHA256_PATTERN)
    selection_plan_hash: str = Field(pattern=SHA256_PATTERN)
    selection_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    selected_candidate_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("occurred_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selection event timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def payload_matches_type(self) -> Self:
        has_selection = (
            self.selection_report_hash is not None and self.selected_candidate_hash is not None
        )
        if self.event_type is CampaignSelectionEventType.PLAN_FROZEN and (
            self.selection_report_hash is not None or self.selected_candidate_hash is not None
        ):
            raise ValueError("plan freeze cannot carry selection output")
        if self.event_type is CampaignSelectionEventType.SELECTION_FROZEN and not has_selection:
            raise ValueError("selection freeze requires report and candidate hashes")
        return self


class CandidateDispositionKind(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NO_VALIDATION_RESULT = "NO_VALIDATION_RESULT"
    NONPASS_VALIDATION = "NONPASS_VALIDATION"
    NOT_RUN_BUDGET = "NOT_RUN_BUDGET"
    NOT_RUN_MANUAL_CLOSE = "NOT_RUN_MANUAL_CLOSE"


class CandidateSelectionDisposition(CanonicalContract):
    schema_version: Literal["candidate-selection-disposition/v1"] = (
        "candidate-selection-disposition/v1"
    )
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    kind: CandidateDispositionKind
    trial_event_hashes: tuple[str, ...] = ()
    validation_trial_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    research_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("trial_event_hashes")
    @classmethod
    def trials_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_hashes(value)

    @model_validator(mode="after")
    def eligibility_has_one_result(self) -> Self:
        if self.kind is CandidateDispositionKind.ELIGIBLE:
            if (
                self.validation_trial_event_hash is None
                or self.validation_trial_event_hash not in self.trial_event_hashes
                or self.research_result_hash is None
            ):
                raise ValueError("eligible candidate requires one bound validation result")
        elif self.validation_trial_event_hash is not None or self.research_result_hash is not None:
            raise ValueError("ineligible candidate cannot carry a selected validation result")
        if (
            self.kind
            in {
                CandidateDispositionKind.NOT_RUN_BUDGET,
                CandidateDispositionKind.NOT_RUN_MANUAL_CLOSE,
            }
            and self.trial_event_hashes
        ):
            raise ValueError("an unrun candidate cannot carry trials")
        return self


class CampaignTrialEvidenceBinding(CanonicalContract):
    schema_version: Literal["campaign-trial-evidence-binding/v1"] = (
        "campaign-trial-evidence-binding/v1"
    )
    event_hash: str = Field(pattern=SHA256_PATTERN)
    trial_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    research_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class CandidateSelectionScore(CanonicalContract):
    schema_version: Literal["candidate-selection-score/v1"] = "candidate-selection-score/v1"
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    oriented_mean_rank_ic: float
    raw_p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float = Field(ge=0, le=1)
    observation_count: PositiveInt
    bootstrap_exceedances: NonNegativeInt


class CampaignSelectionVerdict(StrEnum):
    SELECTED = "SELECTED"
    NO_SELECTION = "NO_SELECTION"
    NOT_EVALUATED = "NOT_EVALUATED"


class CampaignSelectionReport(CanonicalContract):
    schema_version: Literal["campaign-selection-report/v1"] = "campaign-selection-report/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"report_hash"})

    report_hash: str = Field(pattern=SHA256_PATTERN)
    selection_plan_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    multiple_testing_policy_hash: str = Field(pattern=SHA256_PATTERN)
    selection_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_calendar_hash: str = Field(pattern=SHA256_PATTERN)
    source_event_hashes: tuple[str, ...]
    trial_bindings: tuple[CampaignTrialEvidenceBinding, ...]
    candidate_dispositions: tuple[CandidateSelectionDisposition, ...]
    scores: tuple[CandidateSelectionScore, ...]
    run_status: RunStatus
    verdict: CampaignSelectionVerdict
    selected_candidate_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reason_code: ReasonCode | None = None
    limitations: tuple[str, ...] = ()

    @field_validator("source_event_hashes")
    @classmethod
    def events_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("selection report requires a frozen event prefix")
        return _unique_hashes(value)

    @field_validator("trial_bindings")
    @classmethod
    def bindings_are_unique(
        cls, value: tuple[CampaignTrialEvidenceBinding, ...]
    ) -> tuple[CampaignTrialEvidenceBinding, ...]:
        if len({item.event_hash for item in value}) != len(value):
            raise ValueError("trial evidence must bind each event once")
        return value

    @field_validator("candidate_dispositions")
    @classmethod
    def dispositions_are_ordered(
        cls, value: tuple[CandidateSelectionDisposition, ...]
    ) -> tuple[CandidateSelectionDisposition, ...]:
        hashes = [item.candidate_hash for item in value]
        if hashes != sorted(set(hashes)):
            raise ValueError("candidate dispositions must be hash-ordered and unique")
        return value

    @field_validator("scores")
    @classmethod
    def scores_are_ordered(
        cls, value: tuple[CandidateSelectionScore, ...]
    ) -> tuple[CandidateSelectionScore, ...]:
        hashes = [item.candidate_hash for item in value]
        if hashes != sorted(set(hashes)):
            raise ValueError("candidate scores must be hash-ordered and unique")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_ordered(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @model_validator(mode="after")
    def verdict_matches_payload(self) -> Self:
        if self.report_hash != self.content_hash:
            raise ValueError("selection report hash does not match its payload")
        eligible = {
            item.candidate_hash
            for item in self.candidate_dispositions
            if item.kind is CandidateDispositionKind.ELIGIBLE
        }
        scored = {item.candidate_hash for item in self.scores}
        if self.verdict is CampaignSelectionVerdict.NOT_EVALUATED:
            if self.scores:
                raise ValueError("failed selection cannot publish partial scores")
        elif scored != eligible:
            raise ValueError("each eligible candidate requires exactly one score")
        if self.verdict is CampaignSelectionVerdict.SELECTED:
            if (
                self.run_status is not RunStatus.SUCCEEDED
                or self.selected_candidate_hash not in eligible
                or self.reason_code is not None
            ):
                raise ValueError("selected verdict requires one eligible candidate")
        elif self.verdict is CampaignSelectionVerdict.NO_SELECTION:
            if (
                self.run_status is not RunStatus.SUCCEEDED
                or self.selected_candidate_hash is not None
                or self.reason_code is not None
                or not eligible
            ):
                raise ValueError("no-selection verdict requires evaluated candidates")
        elif (
            self.run_status is not RunStatus.FAILED
            or self.selected_candidate_hash is not None
            or self.reason_code is None
        ):
            raise ValueError("not-evaluated verdict requires a failure reason")
        return self
