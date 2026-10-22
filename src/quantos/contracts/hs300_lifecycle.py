"""Versioned structural lifecycle facts and bounded native event policy.

Facts explain security existence and account-event boundaries. They are never
historical alpha features or evidence that a trader could anticipate an event.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.personal_research import (
    HS300DailyProfile,
    HS300DatasetManifest,
    HS300StudyRequest,
    PersonalCandidate,
)
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path


class LifecycleSourceArtifact(CanonicalContract):
    schema_version: Literal["hs300-lifecycle-source/v1"] = "hs300-lifecycle-source/v1"
    source_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    kind: Literal[
        "TUSHARE_PRO",
        "OFFICIAL_EXCHANGE",
        "OFFICIAL_COMPANY",
        "SYNTHETIC_FIXTURE",
        "DERIVATION_SPEC",
    ]
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    observed_at: datetime
    published_at: datetime | None = None
    url: str | None = None

    @field_validator("logical_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_logical_path(value)

    @model_validator(mode="after")
    def aware_times(self) -> Self:
        if self.observed_at.tzinfo is None or (
            self.published_at is not None and self.published_at.tzinfo is None
        ):
            raise ValueError("lifecycle source times must be timezone-aware")
        return self


class SecurityLifecycleFact(CanonicalContract):
    schema_version: Literal["hs300-security-lifecycle/v1"] = "hs300-security-lifecycle/v1"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    list_date: date
    delist_date: date | None = None
    source_ids: tuple[str, ...] = Field(min_length=1)
    use: Literal["STRUCTURAL_EXISTENCE_ONLY_NOT_A_SIGNAL"] = (
        "STRUCTURAL_EXISTENCE_ONLY_NOT_A_SIGNAL"
    )

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.delist_date is not None and self.delist_date <= self.list_date:
            raise ValueError("delisting must follow listing")
        return self


class UnsupportedAccountEvent(CanonicalContract):
    schema_version: Literal["hs300-unsupported-account-event/v1"] = (
        "hs300-unsupported-account-event/v1"
    )
    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    boundary_date: date
    event_type: Literal["DELISTING", "MERGER_EXCHANGE", "CASH_OPTION", "OTHER_UNSUPPORTED"]
    source_ids: tuple[str, ...] = Field(min_length=1)
    related_instrument_ids: tuple[str, ...] = ()
    entitlement_window_start: date | None = None
    native_accounting: Literal["UNSUPPORTED_HARD_BOUNDARY"] = "UNSUPPORTED_HARD_BOUNDARY"

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.entitlement_window_start is not None
            and self.entitlement_window_start > self.boundary_date
        ):
            raise ValueError("entitlement window cannot begin after its account boundary")
        return self


class NativeBoundaryPolicy(CanonicalContract):
    schema_version: Literal["hs300-native-boundary-policy/v1"] = "hs300-native-boundary-policy/v1"
    event_policy: Literal["HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"] = (
        "HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"
    )
    check_phase: Literal["BEFORE_FIRST_UNSUPPORTED_SESSION_DECISION"] = (
        "BEFORE_FIRST_UNSUPPORTED_SESSION_DECISION"
    )
    unknown_state: Literal["HARD_STOP_NOT_EVALUATED"] = "HARD_STOP_NOT_EVALUATED"
    rights_without_native_ledger: Literal["STOP_UNLESS_COMPLETE_NEVER_EXPOSED_NATIVE_HISTORY"] = (
        "STOP_UNLESS_COMPLETE_NEVER_EXPOSED_NATIVE_HISTORY"
    )
    accounting: Literal["NO_PROJECT_CASH_SWAP_OR_POSITION_ADJUSTMENT"] = (
        "NO_PROJECT_CASH_SWAP_OR_POSITION_ADJUSTMENT"
    )
    zero_exposure_requires: tuple[str, ...] = (
        "fresh_cash_no_initial_holdings_no_external_flow",
        "exact_daily_synchronous_SimulatorExecutor_OrderGenWOInteract",
        "complete_sequential_native_account_observation_since_start",
        "all_positions_and_previous_unfilled_and_current_generated_orders_observed",
        "affected_instruments_never_held_and_never_filled",
    )


class NativeBoundaryOrder(CanonicalContract):
    schema_version: Literal["hs300-native-boundary-order/v1"] = "hs300-native-boundary-order/v1"
    qlib_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    amount: float = Field(ge=0)
    deal_amount: float = Field(ge=0)
    direction: Literal[0, 1]


class NativeBoundaryObservation(CanonicalContract):
    schema_version: Literal["hs300-native-boundary-observation/v1"] = (
        "hs300-native-boundary-observation/v1"
    )
    session: date
    native_classes_verified: bool
    fresh_cash_no_initial_holdings_no_external_flow: bool
    sequential_history_complete: bool
    all_holdings: dict[str, float] | None
    previous_unfilled_orders: tuple[NativeBoundaryOrder, ...] | None
    current_generated_orders: tuple[NativeBoundaryOrder, ...] | None
    ever_held_or_filled: tuple[str, ...]
    pending_rights_observability: Literal["UNAVAILABLE_IN_QLIB_0_9_7", "OBSERVABLE"]
    observed_pending_rights: tuple[str, ...] | None = None
    native_source_hashes: dict[str, str] = Field(default_factory=dict)


class NativeBoundaryDecision(CanonicalContract):
    schema_version: Literal["hs300-native-boundary-decision/v1"] = (
        "hs300-native-boundary-decision/v1"
    )
    event_id: str
    observation_hash: str = Field(pattern=SHA256_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal["CLEARED_ZERO_EXPOSURE", "HARD_STOP_EXPOSURE", "HARD_STOP_UNKNOWN"]
    rights_conclusion: Literal[
        "OBSERVED_EMPTY", "OBSERVED_EXPOSURE", "NOT_INCURRED_BY_COMPLETE_NATIVE_HISTORY", "UNKNOWN"
    ]
    reasons: tuple[str, ...]


class LifecycleFactBundle(CanonicalContract):
    schema_version: Literal["hs300-lifecycle-facts/v1"] = "hs300-lifecycle-facts/v1"
    coverage_start: date
    coverage_end: date
    source_vintage: Literal["historical_non_vintage", "synthetic"]
    sources: tuple[LifecycleSourceArtifact, ...] = Field(min_length=1)
    securities: tuple[SecurityLifecycleFact, ...] = Field(min_length=1)
    events: tuple[UnsupportedAccountEvent, ...]
    policy: NativeBoundaryPolicy = Field(default_factory=NativeBoundaryPolicy)
    derivation_source_id: str | None = None

    @model_validator(mode="after")
    def identities(self) -> Self:
        if self.coverage_start > self.coverage_end:
            raise ValueError("lifecycle coverage is reversed")
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("duplicate lifecycle source identity")
        if self.source_vintage == "historical_non_vintage" and not any(
            source.source_id == self.derivation_source_id and source.kind == "DERIVATION_SPEC"
            for source in self.sources
        ):
            raise ValueError("market lifecycle facts require a bound deterministic derivation spec")
        if len({fact.instrument_id for fact in self.securities}) != len(self.securities):
            raise ValueError("duplicate security lifecycle fact")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("duplicate lifecycle event identity")
        for fact in (*self.securities, *self.events):
            if not set(fact.source_ids) <= source_ids:
                raise ValueError("lifecycle fact references an unbound source")
        for fact in self.securities:
            if (
                fact.delist_date is not None
                and self.coverage_start <= fact.delist_date <= self.coverage_end
                and not any(
                    event.instrument_id == fact.instrument_id
                    and event.boundary_date <= fact.delist_date
                    for event in self.events
                )
            ):
                raise ValueError("delisted security needs an explicit native account boundary")
        return self


class HS300LifecycleProfile(HS300DailyProfile):
    schema_version: Literal["hs300-daily-trend-tushare-lifecycle/v1"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "hs300-daily-trend-tushare-lifecycle/v1"
    )
    lifecycle_feature_role: Literal["STRUCTURAL_ONLY_NO_ANTICIPATORY_EXIT"] = (
        "STRUCTURAL_ONLY_NO_ANTICIPATORY_EXIT"
    )
    native_event_policy: Literal["HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"] = (
        "HARD_STOP_EXPOSED_ARM_RETAIN_ALL_SEVEN"
    )


class HS300LifecycleStudyRequest(HS300StudyRequest):
    schema_version: Literal["personal-study-request/v4"] = "personal-study-request/v4"  # pyright: ignore[reportIncompatibleVariableOverride]
    profile: HS300LifecycleProfile = Field(default_factory=HS300LifecycleProfile)  # pyright: ignore[reportIncompatibleVariableOverride]


class HS300LifecycleDatasetManifest(HS300DatasetManifest):
    schema_version: Literal["personal-dataset/v3"] = "personal-dataset/v3"  # pyright: ignore[reportIncompatibleVariableOverride]
    lifecycle_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    lifecycle_source_hashes: dict[str, str]
    native_boundary_policy_hash: str = Field(pattern=SHA256_PATTERN)


class PreparedHS300LifecycleStudy(CanonicalContract):
    schema_version: Literal["personal-study-prepared/v3"] = "personal-study-prepared/v3"
    request: HS300LifecycleStudyRequest
    dataset_manifest: HS300LifecycleDatasetManifest | None
    code_hash: str = Field(pattern=SHA256_PATTERN)
    candidates: tuple[PersonalCandidate, ...]
    readiness: Literal["READY_FOR_AUTHORIZATION", "BLOCKED"]
    gaps: tuple[str, ...]
    validation_verdict: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    rationale: str
    comparison_scope: str
    limits: tuple[str, ...]

    @model_validator(mode="after")
    def fixed_denominator(self) -> Self:
        expected = (
            ("main", "main", None),
            ("classic", "classic", None),
            *((f"random-{seed}", "random", seed) for seed in (17, 41, 73, 101, 137)),
        )
        if tuple((item.candidate_id, item.role, item.seed) for item in self.candidates) != expected:
            raise ValueError("lifecycle study requires the complete fixed seven-arm denominator")
        if self.readiness == "READY_FOR_AUTHORIZATION" and self.gaps:
            raise ValueError("lifecycle study with unresolved gaps cannot be ready")
        return self
