"""Public contracts for immutable canonical data snapshots."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.status import ReasonCode


class SnapshotSourceKind(StrEnum):
    TUSHARE = "TUSHARE"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class DataQualityRule(StrEnum):
    SCHEMA = "SCHEMA"
    PRIMARY_KEY = "PRIMARY_KEY"
    DATE_RANGE = "DATE_RANGE"
    TEMPORAL_ORDER = "TEMPORAL_ORDER"
    OHLC = "OHLC"
    NONNEGATIVE_TRADING_VALUES = "NONNEGATIVE_TRADING_VALUES"
    POSITIVE_ADJUSTMENT_FACTOR = "POSITIVE_ADJUSTMENT_FACTOR"
    INDEX_WEIGHT_TOTAL = "INDEX_WEIGHT_TOTAL"
    INSTRUMENT_REFERENCE = "INSTRUMENT_REFERENCE"
    CALENDAR_REFERENCE = "CALENDAR_REFERENCE"
    RAW_CANONICAL_RECONCILIATION = "RAW_CANONICAL_RECONCILIATION"
    INSTRUMENT_LIFECYCLE = "INSTRUMENT_LIFECYCLE"
    MEMBERSHIP_INTERVAL = "MEMBERSHIP_INTERVAL"
    SPARSE_STATUS_SEMANTICS = "SPARSE_STATUS_SEMANTICS"
    PRICE_LIMIT_BOUNDS = "PRICE_LIMIT_BOUNDS"


class SnapshotBuildSpec(CanonicalContract):
    schema_version: Literal["snapshot-build-spec/v1"] = "snapshot-build-spec/v1"
    dataset_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    source_kind: SnapshotSourceKind
    provider: str = Field(min_length=1)
    start_date: date
    end_date: date
    required_endpoints: tuple[str, ...]
    normalizer_version: str = Field(min_length=1)
    availability_policy_id: str = Field(min_length=1)

    @field_validator("required_endpoints")
    @classmethod
    def endpoints_are_stable_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("required_endpoints cannot be empty")
        if any(not endpoint.strip() for endpoint in value):
            raise ValueError("required_endpoints cannot contain blank values")
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def date_range_is_ordered(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        return self


class DataQualityPolicy(CanonicalContract):
    schema_version: Literal["data-quality-policy/v1"] = "data-quality-policy/v1"
    policy_id: str = Field(min_length=1)
    index_weight_total: float = Field(default=100.0, gt=0)
    index_weight_absolute_tolerance: float = Field(default=0.01, ge=0)
    allowed_st_types: tuple[str, ...] = ("ST", "*ST")
    allowed_suspend_types: tuple[str, ...] = ("S",)

    @field_validator("allowed_st_types", "allowed_suspend_types")
    @classmethod
    def allowed_status_values_are_unique_and_nonempty(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not value or any(not item for item in value) or len(value) != len(set(value)):
            raise ValueError("allowed status values must be nonempty and unique")
        return value


class QualityGateResult(CanonicalContract):
    schema_version: Literal["quality-gate-result/v1"] = "quality-gate-result/v1"
    rule: DataQualityRule
    passed: bool
    checked_rows: NonNegativeInt
    reason_code: ReasonCode | None = None
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def reason_matches_outcome(self) -> Self:
        if self.passed and self.reason_code is not None:
            raise ValueError("passing gate cannot have a reason_code")
        if not self.passed and self.reason_code is None:
            raise ValueError("failing gate must have a reason_code")
        return self


class DataQualityReport(CanonicalContract):
    schema_version: Literal["data-quality-report/v1"] = "data-quality-report/v1"
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    passed: bool
    gates: tuple[QualityGateResult, ...]

    @model_validator(mode="after")
    def summary_matches_gates(self) -> Self:
        if not self.gates:
            raise ValueError("quality report must contain gates")
        if self.passed != all(gate.passed for gate in self.gates):
            raise ValueError("quality report summary does not match its gates")
        return self


class ColumnManifest(CanonicalContract):
    schema_version: Literal["column-manifest/v1"] = "column-manifest/v1"
    name: str = Field(min_length=1)
    arrow_type: str = Field(min_length=1)
    nullable: bool


class SnapshotFileManifest(CanonicalContract):
    schema_version: Literal["snapshot-file-manifest/v1"] = "snapshot-file-manifest/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt
    media_type: str = Field(min_length=1)
    table_name: str | None = None
    row_count: NonNegativeInt | None = None
    min_date: date | None = None
    max_date: date | None = None
    columns: tuple[ColumnManifest, ...] = ()

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)

    @model_validator(mode="after")
    def table_metadata_is_complete(self) -> Self:
        table_fields = (self.table_name, self.row_count)
        if any(value is not None for value in table_fields) and not all(
            value is not None for value in table_fields
        ):
            raise ValueError("table_name and row_count must be provided together")
        if (self.min_date is None) != (self.max_date is None):
            raise ValueError("min_date and max_date must be provided together")
        if self.min_date is not None and self.max_date is not None:
            if self.min_date > self.max_date:
                raise ValueError("min_date cannot be after max_date")
            if self.table_name is None:
                raise ValueError("date range requires table metadata")
        return self


class DataSnapshotManifest(CanonicalContract):
    schema_version: Literal["data-snapshot-manifest/v1"] = "data-snapshot-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"snapshot_hash", "created_at"})

    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_id: str = Field(min_length=1)
    source_kind: SnapshotSourceKind
    provider: str = Field(min_length=1)
    start_date: date
    end_date: date
    build_spec_hash: str = Field(pattern=SHA256_PATTERN)
    quality_policy_hash: str = Field(pattern=SHA256_PATTERN)
    quality_report_hash: str = Field(pattern=SHA256_PATTERN)
    normalizer_version: str = Field(min_length=1)
    files: tuple[SnapshotFileManifest, ...]
    limitations: tuple[str, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot be after end_date")
        if not self.files:
            raise ValueError("snapshot manifest must contain files")
        paths = [item.logical_path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("manifest files must be sorted by unique logical_path")
        if self.snapshot_hash != self.content_hash:
            raise ValueError("snapshot_hash does not match manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        source_kind: SnapshotSourceKind,
        provider: str,
        start_date: date,
        end_date: date,
        build_spec_hash: str,
        quality_policy_hash: str,
        quality_report_hash: str,
        normalizer_version: str,
        files: tuple[SnapshotFileManifest, ...],
        limitations: tuple[str, ...],
        created_at: datetime,
    ) -> Self:
        """Create a self-hashed manifest without weakening validation on loaded manifests."""

        payload = {
            "schema_version": "data-snapshot-manifest/v1",
            "dataset_id": dataset_id,
            "source_kind": source_kind,
            "provider": provider,
            "start_date": start_date,
            "end_date": end_date,
            "build_spec_hash": build_spec_hash,
            "quality_policy_hash": quality_policy_hash,
            "quality_report_hash": quality_report_hash,
            "normalizer_version": normalizer_version,
            "files": files,
            "limitations": limitations,
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            snapshot_hash=digest,
            dataset_id=dataset_id,
            source_kind=source_kind,
            provider=provider,
            start_date=start_date,
            end_date=end_date,
            build_spec_hash=build_spec_hash,
            quality_policy_hash=quality_policy_hash,
            quality_report_hash=quality_report_hash,
            normalizer_version=normalizer_version,
            files=files,
            limitations=limitations,
            created_at=created_at,
        )


class SnapshotDiff(CanonicalContract):
    schema_version: Literal["snapshot-diff/v1"] = "snapshot-diff/v1"
    left_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    right_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    changed_paths: tuple[str, ...]
    row_count_changes: tuple[str, ...]
    schema_changes: tuple[str, ...]
    unchanged_file_count: NonNegativeInt
    changed_file_count: NonNegativeInt


DEFAULT_SYNTHETIC_ENDPOINTS: tuple[str, ...] = (
    "adj_factor",
    "daily",
    "index_daily",
    "index_weight",
    "stock_basic",
    "stock_st",
    "stk_limit",
    "suspend_d",
    "trade_cal",
)

DEFAULT_NORMALIZER_VERSION = "quantos-tushare-historical-index-union-normalizer/v2"
