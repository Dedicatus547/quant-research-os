"""Successor contracts for local, finite personal research; no execution dependencies."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class _HostSessionFields(CanonicalContract):
    session_id: str = Field(min_length=1, max_length=128)
    origin: Literal["outer-codex-session"] = "outer-codex-session"
    model_claim: str | None = Field(default=None, max_length=128)
    model_identity_authenticated: Literal[False] = False
    sdk_invocation: Literal[False] = False
    authority: Literal["PROPOSAL_ONLY"] = "PROPOSAL_ONLY"


class HostSessionProposal(_HostSessionFields):
    schema_version: Literal["host-session-proposal/v1"] = "host-session-proposal/v1"


class HostSessionProposalV2(_HostSessionFields):
    """Successor metadata; v1 canonical bytes remain readable byte-for-byte."""

    schema_version: Literal["host-session-proposal/v2"] = "host-session-proposal/v2"
    public_references: tuple[str, ...] = ()
    explanation: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def public_links(self) -> Self:
        if len(self.public_references) > 20:
            raise ValueError("at most 20 public references")
        for value in self.public_references:
            parsed = urlsplit(value)
            if (
                len(value) > 2048
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(
                    "public references must be bounded public HTTP(S) URLs without credentials"
                )
        return self


class DailyMainboardProfile(CanonicalContract):
    """One implemented strategy family, deliberately not a general strategy grammar."""

    schema_version: Literal["daily-mainboard-trend/v1"] = "daily-mainboard-trend/v1"
    market: Literal["CN_A_MAINBOARD_PIT"] = "CN_A_MAINBOARD_PIT"
    sector_source: Literal["THS"] = "THS"
    frequency: Literal["day"] = "day"
    signal_time: Literal["after_close"] = "after_close"
    execution_time: Literal["next_session_open"] = "next_session_open"
    rebalance: Literal["daily_target_replacement"] = "daily_target_replacement"
    trend_sessions: Literal[20] = 20
    momentum_sessions: Literal[5] = 5
    volume_sessions: Literal[5] = 5
    minimum_volume_ratio: float = Field(default=1.2, ge=1.2, le=1.2)
    sector_weight: float = Field(default=0.25, ge=0.25, le=0.25)
    top_k: int = Field(default=10, ge=1, le=50)
    max_weight: float = Field(default=0.10, gt=0, le=1)
    risk_degree: float = Field(default=0.9, gt=0, le=1)
    initial_cash_cny: float = Field(default=1_000_000, gt=0)
    buy_cost: float = Field(default=0.0003, ge=0, lt=0.1)
    sell_cost: float = Field(default=0.0008, ge=0, lt=0.1)
    minimum_cost_cny: float = Field(default=5, ge=0)
    volume_participation: float = Field(default=0.05, gt=0, le=0.1)
    holding_limit: Literal["none_while_selected"] = "none_while_selected"
    announcement_role: Literal["auxiliary_unvalidated_analysis"] = "auxiliary_unvalidated_analysis"
    intraday_heuristics: Literal["not_implemented_daily_strategy_is_distinct"] = (
        "not_implemented_daily_strategy_is_distinct"
    )


class _PersonalStudyFields(CanonicalContract):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    brief: str = Field(min_length=1, max_length=12000)
    dataset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    start_date: date | None = None
    end_date: date | None = None
    profile: DailyMainboardProfile = Field(default_factory=DailyMainboardProfile)
    benchmark: str = Field(default="SH000985", pattern=r"^(SH|SZ)[0-9]{6}$")
    evidence_hashes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def dates_valid(self) -> Self:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date exceeds end_date")
        import re

        if self.evidence_hashes != tuple(sorted(set(self.evidence_hashes))):
            raise ValueError("evidence references must be sorted and unique")
        if any(re.fullmatch(SHA256_PATTERN, value) is None for value in self.evidence_hashes):
            raise ValueError("evidence references must be SHA-256 identifiers")
        return self


class PersonalStudyRequest(_PersonalStudyFields):
    schema_version: Literal["personal-study-request/v1"] = "personal-study-request/v1"
    proposal: HostSessionProposal


class PersonalStudyRequestV2(_PersonalStudyFields):
    schema_version: Literal["personal-study-request/v2"] = "personal-study-request/v2"
    proposal: HostSessionProposalV2


class PersonalDatasetManifest(CanonicalContract):
    schema_version: Literal["personal-dataset/v1"] = "personal-dataset/v1"
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    kind: Literal["synthetic", "market"]
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    panel_sha256: str = Field(pattern=SHA256_PATTERN)
    pit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    start_date: date
    end_date: date
    all_mainboard_pit: bool
    ths_historical_membership: bool
    tradability_verified: bool
    source_vintage: Literal["synthetic", "historical_non_vintage", "vendor_vintage"]
    exposure: Literal["synthetic", "retrospective_exploration", "unexposed_evaluation"]
    benchmarks: tuple[str, ...]
    qlib_files: dict[str, str]

    @model_validator(mode="after")
    def manifest_valid(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("dataset dates are reversed")
        if self.kind == "market" and self.exposure == "synthetic":
            raise ValueError("market data cannot be synthetic evidence")
        if self.kind == "synthetic" and self.source_vintage != "synthetic":
            raise ValueError("synthetic data requires synthetic vintage")
        if not self.qlib_files:
            raise ValueError("explicit Qlib cache file hashes are required")
        import re

        from quantos.contracts.refs import validate_logical_path

        for path, digest in self.qlib_files.items():
            validate_logical_path(path)
            if re.fullmatch(SHA256_PATTERN, digest) is None:
                raise ValueError("invalid Qlib file digest")
        return self


class PersonalCandidate(CanonicalContract):
    schema_version: Literal["personal-candidate/v1"] = "personal-candidate/v1"
    candidate_id: str
    role: Literal["main", "classic", "random"]
    seed: int | None = None
    rule: str


class PreparedStudy(CanonicalContract):
    schema_version: Literal["personal-study-prepared/v1"] = "personal-study-prepared/v1"
    request: PersonalStudyRequestV2 | PersonalStudyRequest
    dataset_manifest: PersonalDatasetManifest | None
    code_hash: str = Field(pattern=SHA256_PATTERN)
    candidates: tuple[PersonalCandidate, ...]
    readiness: Literal["READY_FOR_AUTHORIZATION", "BLOCKED"]
    gaps: tuple[str, ...]
    validation_verdict: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    rationale: str
    comparison_scope: str
    limits: tuple[str, ...]


class PersonalTaskEvent(CanonicalContract):
    schema_version: Literal["personal-task-event/v1"] = "personal-task-event/v1"
    task_id: str = Field(pattern=SHA256_PATTERN)
    sequence: int = Field(ge=1)
    previous_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    state: Literal[
        "PREPARED", "RUNNING", "CANCEL_REQUESTED", "CANCELLED", "SUCCEEDED", "FAILED", "UNKNOWN"
    ]
    at: datetime
    detail: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def aware_time(self) -> Self:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("event time must be timezone-aware")
        return self


class HS300DailyProfile(CanonicalContract):
    """Explicit successor; the mainboard/THS and weekly contracts are unchanged."""

    schema_version: Literal["hs300-daily-trend-tushare/v1"] = "hs300-daily-trend-tushare/v1"
    market: Literal["CN_HS300_HISTORICAL_PIT"] = "CN_HS300_HISTORICAL_PIT"
    market_source: Literal["TUSHARE_PRO"] = "TUSHARE_PRO"
    universe_index: Literal["000300.SH"] = "000300.SH"
    frequency: Literal["day"] = "day"
    signal_time: Literal["after_close_2359_Asia_Shanghai"] = "after_close_2359_Asia_Shanghai"
    execution_time: Literal["next_session_open"] = "next_session_open"
    rebalance: Literal["daily_target_update"] = "daily_target_update"
    trend_sessions: Literal[20] = 20
    momentum_sessions: Literal[5] = 5
    amount_sessions: Literal[5] = 5
    minimum_amount_ratio: float = Field(default=1.2, ge=1.2, le=1.2, strict=True)
    top_k: Literal[10] = 10
    max_weight: float = Field(default=0.1, ge=0.1, le=0.1, strict=True)
    risk_degree: float = Field(default=0.9, ge=0.9, le=0.9, strict=True)
    initial_cash_cny: float = Field(default=1000000.0, ge=1000000.0, le=1000000.0, strict=True)
    buy_cost: float = Field(default=0.0005, ge=0.0005, le=0.0005, strict=True)
    sell_cost: float = Field(default=0.0015, ge=0.0015, le=0.0015, strict=True)
    minimum_cost_cny: float = Field(default=5.0, ge=5.0, le=5.0, strict=True)
    volume_participation: float = Field(default=0.1, ge=0.1, le=0.1, strict=True)
    trade_unit_shares: Literal[200] = 200
    cost_policy: Literal["fixed_all_in_scenario_not_historical_fee_reconstruction"] = (
        "fixed_all_in_scenario_not_historical_fee_reconstruction"
    )
    limit_policy: Literal["canonical_daily_limits_at_open_native_exchange"] = (
        "canonical_daily_limits_at_open_native_exchange"
    )
    lot_policy: Literal["uniform_200_share_scenario_no_exact_odd_lot_claim"] = (
        "uniform_200_share_scenario_no_exact_odd_lot_claim"
    )
    holding_limit: Literal["none_while_selected"] = "none_while_selected"
    settlement: Literal["one_target_decision_per_session_no_same_session_resale"] = (
        "one_target_decision_per_session_no_same_session_resale"
    )
    announcement_role: Literal["auxiliary_unvalidated_analysis"] = "auxiliary_unvalidated_analysis"


class HS300StudyRequest(CanonicalContract):
    # Independent successor avoids an invariant model-field override. The common
    # request fields and date/evidence predicates retain their original semantics.
    schema_version: Literal["personal-study-request/v3"] = "personal-study-request/v3"
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    brief: str = Field(min_length=1, max_length=12000)
    dataset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    start_date: date | None = None
    end_date: date | None = None
    proposal: HostSessionProposalV2
    profile: HS300DailyProfile = Field(default_factory=HS300DailyProfile)
    benchmark: Literal["SH000300"] = "SH000300"
    evidence_hashes: tuple[str, ...] = ()
    warmup_start: date = date(2022, 11, 1)

    @model_validator(mode="after")
    def dates_valid(self) -> Self:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date exceeds end_date")
        import re

        if self.evidence_hashes != tuple(sorted(set(self.evidence_hashes))):
            raise ValueError("evidence references must be sorted and unique")
        if any(re.fullmatch(SHA256_PATTERN, value) is None for value in self.evidence_hashes):
            raise ValueError("evidence references must be SHA-256 identifiers")
        return self

    @model_validator(mode="after")
    def warmup_valid(self) -> Self:
        if self.start_date is not None and self.warmup_start >= self.start_date:
            raise ValueError("warmup must precede evaluation")
        return self


class HS300DatasetManifest(CanonicalContract):
    schema_version: Literal["personal-dataset/v2"] = "personal-dataset/v2"
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    kind: Literal["synthetic", "market"]
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    panel_sha256: str = Field(pattern=SHA256_PATTERN)
    pit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    start_date: date
    end_date: date
    warmup_start: date
    market_source: Literal["TUSHARE_PRO", "SYNTHETIC_FIXTURE"]
    historical_hs300_membership: Literal[True] = True
    amount_cny_bound: Literal[True] = True
    tradability_verified: Literal[True] = True
    membership_policy: Literal["conservative_next_session_0900_bounded_intervals"] = (
        "conservative_next_session_0900_bounded_intervals"
    )
    source_vintage: Literal["synthetic", "historical_non_vintage"]
    exposure: Literal["synthetic", "retrospective_exploration"]
    benchmarks: tuple[Literal["SH000300"], ...] = ("SH000300",)
    qlib_files: dict[str, str]
    source_files: dict[str, str] = Field(default_factory=dict)
    snapshot_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    view_manifest_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def manifest_valid(self) -> Self:
        if not self.warmup_start < self.start_date <= self.end_date:
            raise ValueError("HS300 warmup/evaluation dates are invalid")
        expected = (
            ("TUSHARE_PRO", "historical_non_vintage", "retrospective_exploration")
            if self.kind == "market"
            else ("SYNTHETIC_FIXTURE", "synthetic", "synthetic")
        )
        if (self.market_source, self.source_vintage, self.exposure) != expected:
            raise ValueError("HS300 source/exposure binding disagrees")
        if not self.qlib_files or (self.kind == "market" and not self.source_files):
            raise ValueError("explicit source and Qlib file inventories are required")
        import re

        from quantos.contracts.refs import validate_logical_path

        for logical, digest in {**self.qlib_files, **self.source_files}.items():
            validate_logical_path(logical)
            if re.fullmatch(SHA256_PATTERN, digest) is None:
                raise ValueError("invalid HS300 file digest")
        return self


class PreparedHS300Study(CanonicalContract):
    schema_version: Literal["personal-study-prepared/v2"] = "personal-study-prepared/v2"
    request: HS300StudyRequest
    dataset_manifest: HS300DatasetManifest | None
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
        actual = tuple((item.candidate_id, item.role, item.seed) for item in self.candidates)
        if actual != expected:
            raise ValueError(
                "HS300 prepared study requires the complete fixed seven-arm denominator"
            )
        if self.readiness == "READY_FOR_AUTHORIZATION" and self.gaps:
            raise ValueError("HS300 study with unresolved gaps cannot be ready")
        return self
