"""Qualified event-feature and deterministic event-study contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    INSTRUMENT_PATTERN,
    AdmissionReviewerKind,
    EvidenceCitation,
    ProposedAttribute,
)
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.research import ResolvedStrategySpec
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule


def _sorted_unique_strings(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if value != tuple(sorted(set(value))):
        raise ValueError(f"{label} must be sorted and unique")
    return value


class EventFeatureBenchmarkCase(CanonicalContract):
    """One human-frozen expected extraction used by deterministic admission."""

    schema_version: Literal["event-feature-benchmark-case/v1"] = "event-feature-benchmark-case/v1"
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    event_label: Literal["share_repurchase"] = "share_repurchase"
    entity_refs: tuple[str, ...]
    event_time: datetime
    citations: tuple[EvidenceCitation, ...]
    attributes: tuple[ProposedAttribute, ...] = ()

    @field_validator("event_time")
    @classmethod
    def event_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("benchmark event_time must be timezone-aware")
        return value

    @field_validator("entity_refs")
    @classmethod
    def entities_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("benchmark case requires an entity")
        _sorted_unique_strings(value, "benchmark entities")
        if any(re.fullmatch(INSTRUMENT_PATTERN, item) is None for item in value):
            raise ValueError("benchmark case has an unsupported entity")
        return value

    @field_validator("citations")
    @classmethod
    def citations_are_verifiable(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        if not value or any(item.char_start is None or item.char_end is None for item in value):
            raise ValueError("benchmark citations require exact character ranges")
        keys = [(item.char_start, item.char_end, item.cited_text_hash) for item in value]
        if keys != sorted(set(keys)):
            raise ValueError("benchmark citations must be sorted and unique")
        return value

    @field_validator("attributes")
    @classmethod
    def attributes_are_sorted(
        cls, value: tuple[ProposedAttribute, ...]
    ) -> tuple[ProposedAttribute, ...]:
        names = [item.name for item in value]
        if names != sorted(set(names)):
            raise ValueError("benchmark attributes must be sorted and unique")
        return value

    @model_validator(mode="after")
    def citations_bind_source(self) -> Self:
        if any(
            item.evidence_hash != self.evidence_hash
            or item.extracted_text_hash != self.extracted_text_hash
            for item in self.citations
        ):
            raise ValueError("benchmark citations do not bind the benchmark source")
        return self


class EventFeatureAdmissionPolicySpec(CanonicalContract):
    schema_version: Literal["event-feature-admission-policy/v1"] = (
        "event-feature-admission-policy/v1"
    )
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    reviewer_kind: Literal[AdmissionReviewerKind.DETERMINISTIC_BENCHMARK] = (
        AdmissionReviewerKind.DETERMINISTIC_BENCHMARK
    )
    cases: tuple[EventFeatureBenchmarkCase, ...]
    reject_unknown_availability: Literal[True] = True
    require_research_permission: Literal[True] = True
    require_exact_entity_set: Literal[True] = True
    require_exact_citation_text: Literal[True] = True

    @field_validator("cases")
    @classmethod
    def cases_are_nonempty_sorted(
        cls, value: tuple[EventFeatureBenchmarkCase, ...]
    ) -> tuple[EventFeatureBenchmarkCase, ...]:
        keys = [(item.evidence_hash, item.case_id) for item in value]
        if not keys or keys != sorted(set(keys)):
            raise ValueError("benchmark cases must be nonempty, sorted, and unique")
        if len({item.evidence_hash for item in value}) != len(value):
            raise ValueError("one evidence object may map to only one benchmark case")
        return value


class TradingSessionResolverPolicy(CanonicalContract):
    schema_version: Literal["trading-session-resolver-policy/v1"] = (
        "trading-session-resolver-policy/v1"
    )
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    source_timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    effective_session: Literal["STRICT_NEXT_OPEN_SESSION"] = "STRICT_NEXT_OPEN_SESSION"
    max_calendar_gap_days: PositiveInt = Field(default=10, le=31)
    calendar_table: Literal["canonical/calendar.parquet"] = "canonical/calendar.parquet"
    instrument_table: Literal["canonical/instruments.parquet"] = "canonical/instruments.parquet"


class TradingSessionResolution(CanonicalContract):
    schema_version: Literal["trading-session-resolution/v1"] = "trading-session-resolution/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    resolver_policy_hash: str = Field(pattern=SHA256_PATTERN)
    calendar_file_hash: str = Field(pattern=SHA256_PATTERN)
    instrument_file_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_available_at: datetime
    entity_ref: str = Field(pattern=INSTRUMENT_PATTERN)
    exchange: Literal["SSE", "SZSE"]
    effective_trade_date: date

    @field_validator("evidence_available_at")
    @classmethod
    def available_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resolution availability must be timezone-aware")
        return value


class EventFeatureArtifactFile(CanonicalContract):
    schema_version: Literal["event-feature-artifact-file/v1"] = "event-feature-artifact-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class EventFeatureArtifactManifest(CanonicalContract):
    schema_version: Literal["event-feature-artifact-manifest/v1"] = (
        "event-feature-artifact-manifest/v1"
    )
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"artifact_hash"})

    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    feature_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    extraction_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    admission_record_hash: str = Field(pattern=SHA256_PATTERN)
    admission_policy_hash: str = Field(pattern=SHA256_PATTERN)
    resolver_policy_hash: str = Field(pattern=SHA256_PATTERN)
    resolution_hashes: tuple[str, ...]
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    files: tuple[EventFeatureArtifactFile, ...]

    @field_validator("resolution_hashes")
    @classmethod
    def resolutions_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("resolution hashes must be nonempty, sorted, and unique")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact(
        cls, value: tuple[EventFeatureArtifactFile, ...]
    ) -> tuple[EventFeatureArtifactFile, ...]:
        expected = [
            "admission-policy.json",
            "admission-record.json",
            "evidence.json",
            "extracted-text.json",
            "extraction-proposal.json",
            "feature.json",
            "resolver-policy.json",
            "trading-session-resolutions.json",
        ]
        if [item.logical_path for item in value] != expected:
            raise ValueError("event feature artifact file set does not match v1")
        return value

    @model_validator(mode="after")
    def hash_matches_payload(self) -> Self:
        if self.artifact_hash != self.content_hash:
            raise ValueError("event feature artifact hash does not match manifest content")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {"schema_version": "event-feature-artifact-manifest/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(artifact_hash=digest, **values)  # type: ignore[arg-type]


class EventSignalAlignmentPolicy(CanonicalContract):
    """Frozen PIT-safe alignment from event availability to the existing weekly Qlib path."""

    schema_version: Literal["event-signal-alignment-policy/v1"] = "event-signal-alignment-policy/v1"
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    alignment: Literal["FIRST_WEEK_END_ON_OR_AFTER_EFFECTIVE_SESSION"] = (
        "FIRST_WEEK_END_ON_OR_AFTER_EFFECTIVE_SESSION"
    )
    score: Literal["EVENT_COUNT"] = "EVENT_COUNT"
    signal_time: Literal["16:00:00"] = "16:00:00"
    signal_available_time: Literal["16:01:00"] = "16:01:00"
    decision_time: Literal["16:10:00"] = "16:10:00"
    execution_time: Literal["09:30:00"] = "09:30:00"
    execution_lag_trading_sessions: Literal[1] = 1
    max_alignment_lag_sessions: NonNegativeInt = Field(default=4, le=4)
    require_source_available_by_signal: Literal[True] = True
    tradability_policy: Literal["not_st_and_not_suspended/v1"] = "not_st_and_not_suspended/v1"


class EventSignalEvidenceItem(CanonicalContract):
    schema_version: Literal["event-signal-evidence-item/v1"] = "event-signal-evidence-item/v1"
    event_feature_row_hashes: tuple[str, ...]
    entity_ref: str = Field(pattern=INSTRUMENT_PATTERN)
    event_label: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    first_effective_trade_date: date
    last_effective_trade_date: date
    source_available_at: datetime
    schedule: DecisionSchedule
    score: PositiveInt

    @field_validator("event_feature_row_hashes")
    @classmethod
    def row_hashes_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not value
            or value != tuple(sorted(set(value)))
            or any(re.fullmatch(SHA256_PATTERN, item) is None for item in value)
        ):
            raise ValueError("event signal row hashes must be nonempty, sorted, and unique")
        return value

    @field_validator("source_available_at")
    @classmethod
    def source_availability_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event signal source availability must be timezone-aware")
        return value

    @model_validator(mode="after")
    def timing_and_score_are_consistent(self) -> Self:
        if self.first_effective_trade_date > self.last_effective_trade_date:
            raise ValueError("event signal effective date range is reversed")
        if self.last_effective_trade_date > self.schedule.signal_time.date():
            raise ValueError("event signal cannot precede an effective event session")
        if self.source_available_at > self.schedule.signal_time:
            raise ValueError("event signal source is unavailable at signal time")
        if self.score != len(self.event_feature_row_hashes):
            raise ValueError("event signal score must equal its exact event count")
        return self


class EventSignalEvidence(CanonicalContract):
    schema_version: Literal["event-signal-evidence/v1"] = "event-signal-evidence/v1"
    event_feature_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    event_feature_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    alignment_policy_hash: str = Field(pattern=SHA256_PATTERN)
    items: tuple[EventSignalEvidenceItem, ...]

    @field_validator("items")
    @classmethod
    def items_are_nonempty_sorted_unique(
        cls, value: tuple[EventSignalEvidenceItem, ...]
    ) -> tuple[EventSignalEvidenceItem, ...]:
        keys = [(item.schedule.signal_time, item.entity_ref, item.event_label) for item in value]
        if not keys or keys != sorted(set(keys)):
            raise ValueError("event signal evidence items must be nonempty, sorted, and unique")
        return value


class ResolvedEventExperimentSpec(CanonicalContract):
    """Hash-bound event experiment consumed only by the existing Qlib reference backtest."""

    schema_version: Literal["resolved-event-experiment/v1"] = "resolved-event-experiment/v1"
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    event_feature_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    event_signal_alignment_policy_hash: str = Field(pattern=SHA256_PATTERN)
    event_signal_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_start: date
    evaluation_end: date
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    strategy: ResolvedStrategySpec
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def range_and_strategy_are_supported(self) -> Self:
        if self.evaluation_start > self.evaluation_end:
            raise ValueError("event experiment evaluation range is reversed")
        return self


class EventSignalArtifactFile(CanonicalContract):
    schema_version: Literal["event-signal-artifact-file/v1"] = "event-signal-artifact-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class EventSignalArtifactManifest(CanonicalContract):
    """Signal artifact variant whose score lineage is an admitted EventFeature."""

    schema_version: Literal["event-signal-artifact-manifest/v1"] = (
        "event-signal-artifact-manifest/v1"
    )
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"artifact_hash", "created_at"})

    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str = Field(pattern=SHA256_PATTERN)
    event_feature_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    event_feature_hash: str = Field(pattern=SHA256_PATTERN)
    event_signal_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    event_signal_alignment_policy_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    row_count: PositiveInt
    signal_start: datetime
    signal_end: datetime
    signal_content_hash: str = Field(pattern=SHA256_PATTERN)
    files: tuple[EventSignalArtifactFile, ...]
    created_at: datetime

    @field_validator("signal_start", "signal_end", "created_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event signal manifest timestamps must be timezone-aware")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact(
        cls, value: tuple[EventSignalArtifactFile, ...]
    ) -> tuple[EventSignalArtifactFile, ...]:
        expected = [
            "event-feature-manifest.json",
            "event-feature.json",
            "event-signal-evidence.json",
            "event-signal-policy.json",
            "resolved-event-experiment.json",
            "signals.parquet",
        ]
        if [item.logical_path for item in value] != expected:
            raise ValueError("event signal artifact file set does not match v1")
        return value

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if self.signal_start > self.signal_end:
            raise ValueError("event signal start cannot follow end")
        if self.artifact_hash != self.content_hash:
            raise ValueError("event signal artifact hash does not match manifest content")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {
            "schema_version": "event-signal-artifact-manifest/v1",
            **{key: value for key, value in values.items() if key != "created_at"},
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(artifact_hash=digest, **values)  # type: ignore[arg-type]


class EventStudyMetric(StrEnum):
    EVENT_COUNT = "event_count"
    MEAN_ABNORMAL_RETURN = "mean_abnormal_return"
    MEAN_CAR = "mean_car"


class EventStudySpec(CanonicalContract):
    schema_version: Literal["event-study-spec/v1"] = "event-study-spec/v1"
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    event_feature_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    benchmark_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    window_start: int = Field(ge=0, le=20)
    window_end: PositiveInt = Field(le=60)
    metrics: tuple[EventStudyMetric, ...]

    @field_validator("metrics")
    @classmethod
    def metrics_are_supported_sorted(
        cls, value: tuple[EventStudyMetric, ...]
    ) -> tuple[EventStudyMetric, ...]:
        if not value or value != tuple(sorted(set(value), key=str)):
            raise ValueError("event-study metrics must be nonempty, sorted, and unique")
        if EventStudyMetric.EVENT_COUNT not in value:
            raise ValueError("event-study metrics must include event_count")
        return value

    @model_validator(mode="after")
    def window_is_ordered(self) -> Self:
        if self.window_start > self.window_end:
            raise ValueError("event-study window is reversed")
        return self


class EventStudyRow(CanonicalContract):
    schema_version: Literal["event-study-row/v1"] = "event-study-row/v1"
    entity_ref: str = Field(pattern=INSTRUMENT_PATTERN)
    event_trade_date: date
    window_start_date: date
    window_end_date: date
    stock_return: float
    benchmark_return: float
    abnormal_return: float
    cumulative_abnormal_return: float

    @model_validator(mode="after")
    def dates_and_arithmetic_are_valid(self) -> Self:
        if not self.event_trade_date <= self.window_start_date <= self.window_end_date:
            raise ValueError("event-study dates are not ordered")
        tolerance = 1e-12
        if abs(self.abnormal_return - (self.stock_return - self.benchmark_return)) > tolerance:
            raise ValueError("event-study abnormal return arithmetic disagrees")
        return self


class EventStudySummary(CanonicalContract):
    schema_version: Literal["event-study-summary/v1"] = "event-study-summary/v1"
    event_count: PositiveInt
    mean_abnormal_return: float | None = None
    mean_car: float | None = None


class EventStudyArtifactFile(CanonicalContract):
    schema_version: Literal["event-study-artifact-file/v1"] = "event-study-artifact-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class EventStudyArtifactManifest(CanonicalContract):
    schema_version: Literal["event-study-artifact-manifest/v1"] = "event-study-artifact-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"artifact_hash"})

    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    spec_hash: str = Field(pattern=SHA256_PATTERN)
    event_feature_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    event_feature_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    row_count: PositiveInt
    rows_hash: str = Field(pattern=SHA256_PATTERN)
    summary_hash: str = Field(pattern=SHA256_PATTERN)
    files: tuple[EventStudyArtifactFile, ...]

    @field_validator("files")
    @classmethod
    def files_are_exact(
        cls, value: tuple[EventStudyArtifactFile, ...]
    ) -> tuple[EventStudyArtifactFile, ...]:
        expected = [
            "event-feature-manifest.json",
            "event-study-rows.json",
            "event-study-spec.json",
            "event-study-summary.json",
        ]
        if [item.logical_path for item in value] != expected:
            raise ValueError("event-study artifact file set does not match v1")
        return value

    @model_validator(mode="after")
    def hash_matches_payload(self) -> Self:
        if self.artifact_hash != self.content_hash:
            raise ValueError("event-study artifact hash does not match manifest content")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {"schema_version": "event-study-artifact-manifest/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(artifact_hash=digest, **values)  # type: ignore[arg-type]


class P13BenchmarkBinding(CanonicalContract):
    """Hash binding for the human-frozen real P13 Evidence benchmark."""

    schema_version: Literal["p13-benchmark-binding/v1"] = "p13-benchmark-binding/v1"
    binding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    evidence_store_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    benchmark_policy_hash: str = Field(pattern=SHA256_PATTERN)


class P13QualificationBundle(CanonicalContract):
    """Immutable hash-only envelope for the complete P13 qualification attempt."""

    schema_version: Literal["p13-qualification-bundle/v1"] = "p13-qualification-bundle/v1"
    benchmark_binding_hash: str = Field(pattern=SHA256_PATTERN)
    qualification_report_hash: str = Field(pattern=SHA256_PATTERN)
    native_bridge_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    agent_run_manifest_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    admission_record_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    feature_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_study_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_signal_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    backtest_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reconciliation_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_view_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    independent_root_count: PositiveInt
    limitations: tuple[str, ...]

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(value, "P13 bundle limitations")


class P13QualificationReport(CanonicalContract):
    """Separate engineering completion from real-evidence qualification."""

    schema_version: Literal["p13-qualification-report/v1"] = "p13-qualification-report/v1"
    benchmark_policy_hash: str = Field(pattern=SHA256_PATTERN)
    benchmark_case_count: PositiveInt
    proposal_count: PositiveInt
    schema_valid_count: NonNegativeInt
    citation_accurate_count: NonNegativeInt
    admitted_count: NonNegativeInt
    pit_valid_count: NonNegativeInt
    duplicate_count: NonNegativeInt
    schema_valid_rate: float = Field(ge=0, le=1)
    citation_accuracy: float = Field(ge=0, le=1)
    admission_rate: float = Field(ge=0, le=1)
    pit_valid_rate: float = Field(ge=0, le=1)
    duplicate_rate: float = Field(ge=0, le=1)
    total_agent_tokens: NonNegativeInt
    offline_engineering_status: RunStatus
    offline_engineering_verdict: ValidationVerdict
    data_qualified_status: RunStatus
    data_qualified_verdict: ValidationVerdict
    data_qualified_reason: ReasonCode | None = None
    feature_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_study_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    limitations: tuple[str, ...]

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_strings(value, "P13 limitations")

    @model_validator(mode="after")
    def statuses_and_counts_are_consistent(self) -> Self:
        counts = (
            self.schema_valid_count,
            self.citation_accurate_count,
            self.admitted_count,
            self.pit_valid_count,
        )
        if (
            any(item > self.proposal_count for item in counts)
            or self.duplicate_count > self.proposal_count
        ):
            raise ValueError("P13 benchmark count exceeds proposal count")
        expected_rates = (
            self.schema_valid_count / self.proposal_count,
            self.citation_accurate_count / self.proposal_count,
            self.admitted_count / self.proposal_count,
            self.pit_valid_count / self.proposal_count,
            self.duplicate_count / self.proposal_count,
        )
        actual_rates = (
            self.schema_valid_rate,
            self.citation_accuracy,
            self.admission_rate,
            self.pit_valid_rate,
            self.duplicate_rate,
        )
        if any(
            abs(actual - expected) > 1e-12
            for actual, expected in zip(actual_rates, expected_rates, strict=True)
        ):
            raise ValueError("P13 benchmark rates do not match attempt counts")
        if self.offline_engineering_status is RunStatus.FAILED:
            if self.offline_engineering_verdict is not ValidationVerdict.NOT_EVALUATED:
                raise ValueError("failed offline engineering must be NOT_EVALUATED")
        elif self.offline_engineering_verdict is ValidationVerdict.NOT_EVALUATED:
            raise ValueError("successful offline engineering requires PASS or REJECT")
        if self.data_qualified_status is RunStatus.FAILED:
            if (
                self.data_qualified_verdict is not ValidationVerdict.NOT_EVALUATED
                or self.data_qualified_reason is None
            ):
                raise ValueError("failed data qualification requires NOT_EVALUATED and reason")
        elif (
            self.data_qualified_verdict is ValidationVerdict.NOT_EVALUATED
            or self.data_qualified_reason is not None
        ):
            raise ValueError("successful data qualification requires an evaluated verdict")
        return self
