"""Contracts for a rebuildable Qlib derived-data view."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path


class InstrumentCodeMapping(CanonicalContract):
    schema_version: Literal["instrument-code-mapping/v1"] = "instrument-code-mapping/v1"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    qlib_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")

    @model_validator(mode="after")
    def mapping_is_reversible(self) -> Self:
        expected = f"{self.instrument_id[-2:]}{self.instrument_id[:6]}"
        if self.qlib_id != expected:
            raise ValueError("Qlib instrument mapping is not reversible")
        return self


class QlibViewSpec(CanonicalContract):
    schema_version: Literal["qlib-view-spec/v1"] = "qlib-view-spec/v1"
    source_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    dump_bin_sha256: str = Field(pattern=SHA256_PATTERN)
    health_check_sha256: str = Field(pattern=SHA256_PATTERN)
    frequency: Literal["day"] = "day"
    include_fields: tuple[str, ...] = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "factor",
        "change",
        "limit_buy",
        "limit_sell",
        "is_st",
    )
    adjustment_formula: Literal[
        "adjusted_ohlc=raw_ohlc*adj_factor;adjusted_volume=raw_volume/adj_factor"
    ] = "adjusted_ohlc=raw_ohlc*adj_factor;adjusted_volume=raw_volume/adj_factor"
    suspension_policy: Literal["suspended_ohlcv_as_nan"] = "suspended_ohlcv_as_nan"
    price_limit_policy: Literal["qlib_exchange_tuple_fields=($limit_buy,$limit_sell)"] = (
        "qlib_exchange_tuple_fields=($limit_buy,$limit_sell)"
    )
    historical_universe_sidecar: Literal["sidecars/historical-universe.parquet"] = (
        "sidecars/historical-universe.parquet"
    )
    tradability_sidecar: Literal["sidecars/tradability.parquet"] = "sidecars/tradability.parquet"
    mappings: tuple[InstrumentCodeMapping, ...]

    @field_validator("include_fields")
    @classmethod
    def fields_are_locked_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expected = (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "factor",
            "change",
            "limit_buy",
            "limit_sell",
            "is_st",
        )
        if value != expected:
            raise ValueError("Qlib v0.1 include_fields must use the locked field order")
        return value

    @field_validator("mappings")
    @classmethod
    def mappings_are_sorted_and_unique(
        cls, value: tuple[InstrumentCodeMapping, ...]
    ) -> tuple[InstrumentCodeMapping, ...]:
        if not value:
            raise ValueError("Qlib mappings cannot be empty")
        instrument_ids = [item.instrument_id for item in value]
        qlib_ids = [item.qlib_id for item in value]
        if instrument_ids != sorted(instrument_ids):
            raise ValueError("Qlib mappings must be sorted by instrument_id")
        if len(instrument_ids) != len(set(instrument_ids)) or len(qlib_ids) != len(set(qlib_ids)):
            raise ValueError("Qlib mappings must be collision-free")
        return value


class ConverterInputDigest(CanonicalContract):
    schema_version: Literal["converter-input-digest/v1"] = "converter-input-digest/v1"
    qlib_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    sha256: str = Field(pattern=SHA256_PATTERN)
    row_count: NonNegativeInt


class QlibViewFile(CanonicalContract):
    schema_version: Literal["qlib-view-file/v1"] = "qlib-view-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class QlibSemanticSample(CanonicalContract):
    schema_version: Literal["qlib-semantic-sample/v1"] = "qlib-semantic-sample/v1"
    qlib_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    trade_date: date
    field: str = Field(min_length=1)
    expected: float
    actual: float
    absolute_tolerance: float = Field(default=1e-6, ge=0)
    passed: bool

    @model_validator(mode="after")
    def outcome_matches_values(self) -> Self:
        if self.passed != (abs(self.expected - self.actual) <= self.absolute_tolerance):
            raise ValueError("semantic sample outcome does not match values")
        return self


class QlibViewManifest(CanonicalContract):
    schema_version: Literal["qlib-view-manifest/v1"] = "qlib-view-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"view_hash", "created_at"})

    view_hash: str = Field(pattern=SHA256_PATTERN)
    source_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    dump_bin_sha256: str = Field(pattern=SHA256_PATTERN)
    health_check_sha256: str = Field(pattern=SHA256_PATTERN)
    converter_inputs: tuple[ConverterInputDigest, ...]
    files: tuple[QlibViewFile, ...]
    health_check_passed: bool
    semantic_samples: tuple[QlibSemanticSample, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        paths = [item.logical_path for item in self.files]
        input_ids = [item.qlib_id for item in self.converter_inputs]
        if not self.files or paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("Qlib view files must be nonempty, sorted, and unique")
        if input_ids != sorted(input_ids) or len(input_ids) != len(set(input_ids)):
            raise ValueError("converter inputs must be sorted and unique")
        if not self.health_check_passed or not self.semantic_samples:
            raise ValueError("Qlib view requires health and semantic evidence")
        if not all(sample.passed for sample in self.semantic_samples):
            raise ValueError("all Qlib semantic samples must pass")
        if self.view_hash != self.content_hash:
            raise ValueError("view_hash does not match manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        source_snapshot_hash: str,
        view_spec_hash: str,
        qlib_version: str,
        qlib_source_commit: str,
        dump_bin_sha256: str,
        health_check_sha256: str,
        converter_inputs: tuple[ConverterInputDigest, ...],
        files: tuple[QlibViewFile, ...],
        health_check_passed: bool,
        semantic_samples: tuple[QlibSemanticSample, ...],
        created_at: datetime,
    ) -> Self:
        payload = {
            "schema_version": "qlib-view-manifest/v1",
            "source_snapshot_hash": source_snapshot_hash,
            "view_spec_hash": view_spec_hash,
            "qlib_version": qlib_version,
            "qlib_source_commit": qlib_source_commit,
            "dump_bin_sha256": dump_bin_sha256,
            "health_check_sha256": health_check_sha256,
            "converter_inputs": converter_inputs,
            "files": files,
            "health_check_passed": health_check_passed,
            "semantic_samples": semantic_samples,
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            view_hash=digest,
            source_snapshot_hash=source_snapshot_hash,
            view_spec_hash=view_spec_hash,
            qlib_version=qlib_version,
            qlib_source_commit=qlib_source_commit,
            dump_bin_sha256=dump_bin_sha256,
            health_check_sha256=health_check_sha256,
            converter_inputs=converter_inputs,
            files=files,
            health_check_passed=health_check_passed,
            semantic_samples=semantic_samples,
            created_at=created_at,
        )
