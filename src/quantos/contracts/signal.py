"""Immutable point-in-time signal artifact contracts."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN


class SignalRow(CanonicalContract):
    schema_version: Literal["signal-row/v2"] = "signal-row/v2"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    signal_time: datetime
    decision_time: datetime
    available_at: datetime
    score: float | None
    score_valid: bool = True
    tradable: bool

    @field_validator("signal_time", "decision_time", "available_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("signal timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def temporal_order_is_valid(self) -> Self:
        if not self.available_at <= self.signal_time <= self.decision_time:
            raise ValueError("signal row requires available_at <= signal_time <= decision_time")
        if self.score_valid != (self.score is not None):
            raise ValueError("score_valid must exactly describe score presence")
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("present signal scores must be finite")
        return self


class SignalArtifactFile(CanonicalContract):
    schema_version: Literal["signal-artifact-file/v1"] = "signal-artifact-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("logical_path must be a safe relative POSIX path")
        return path.as_posix()


class SignalInputHash(CanonicalContract):
    schema_version: Literal["signal-input-hash/v1"] = "signal-input-hash/v1"
    kind: Literal[
        "expression_translation",
        "pit_evidence",
        "qlib_view_cache",
        "qlib_view_spec",
        "resolved_experiment",
        "snapshot",
    ]
    sha256: str = Field(pattern=SHA256_PATTERN)


class SignalArtifactManifest(CanonicalContract):
    schema_version: Literal["signal-artifact-manifest/v2"] = "signal-artifact-manifest/v2"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"artifact_hash", "created_at"})

    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str = Field(pattern=SHA256_PATTERN)
    source_expression_or_model_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_run_id: str | None = Field(default=None, min_length=1)
    pit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    transform_lineage_hash: str = Field(pattern=SHA256_PATTERN)
    expression_translation_hash: str = Field(pattern=SHA256_PATTERN)
    tradability_policy: Literal["not_st_and_not_suspended/v1"] = "not_st_and_not_suspended/v1"
    input_hashes: tuple[SignalInputHash, ...]
    row_count: PositiveInt
    signal_start: datetime
    signal_end: datetime
    signal_schema: tuple[str, ...] = (
        "instrument_id:string:not_null",
        "signal_time:timestamp[us,Asia/Shanghai]:not_null",
        "decision_time:timestamp[us,Asia/Shanghai]:not_null",
        "available_at:timestamp[us,Asia/Shanghai]:not_null",
        "score:float64:nullable",
        "score_valid:bool:not_null",
        "tradable:bool:not_null",
    )
    signal_content_hash: str = Field(pattern=SHA256_PATTERN)
    files: tuple[SignalArtifactFile, ...]
    created_at: datetime

    @field_validator("signal_start", "signal_end", "created_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("manifest timestamps must be timezone-aware")
        return value

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_complete_and_sorted(
        cls, value: tuple[SignalInputHash, ...]
    ) -> tuple[SignalInputHash, ...]:
        kinds = [item.kind for item in value]
        required = {
            "expression_translation",
            "pit_evidence",
            "qlib_view_cache",
            "qlib_view_spec",
            "resolved_experiment",
            "snapshot",
        }
        if kinds != sorted(kinds) or set(kinds) != required or len(kinds) != len(required):
            raise ValueError("signal input hashes must be complete, sorted, and unique")
        return value

    @field_validator("signal_schema")
    @classmethod
    def schema_is_locked(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expected = (
            "instrument_id:string:not_null",
            "signal_time:timestamp[us,Asia/Shanghai]:not_null",
            "decision_time:timestamp[us,Asia/Shanghai]:not_null",
            "available_at:timestamp[us,Asia/Shanghai]:not_null",
            "score:float64:nullable",
            "score_valid:bool:not_null",
            "tradable:bool:not_null",
        )
        if value != expected:
            raise ValueError("signal_schema must match the locked v2 Arrow schema")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact_and_sorted(
        cls, value: tuple[SignalArtifactFile, ...]
    ) -> tuple[SignalArtifactFile, ...]:
        paths = [item.logical_path for item in value]
        expected = [
            "expression-translation.json",
            "pit-evidence.json",
            "resolved-experiment.json",
            "signals.parquet",
        ]
        if paths != expected:
            raise ValueError("signal artifact file set must match the locked v1 layout")
        return value

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if self.signal_start > self.signal_end:
            raise ValueError("signal_start cannot be after signal_end")
        expected_inputs = {
            "expression_translation": self.expression_translation_hash,
            "pit_evidence": self.pit_evidence_hash,
            "qlib_view_cache": self.qlib_view_hash,
            "qlib_view_spec": self.qlib_view_spec_hash,
            "resolved_experiment": self.resolved_experiment_hash,
            "snapshot": self.snapshot_hash,
        }
        if {item.kind: item.sha256 for item in self.input_hashes} != expected_inputs:
            raise ValueError("signal input hashes do not match manifest bindings")
        if self.artifact_hash != self.content_hash:
            raise ValueError("artifact_hash does not match signal manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        resolved_experiment_hash: str,
        source_expression_or_model_hash: str,
        snapshot_hash: str,
        qlib_version: str,
        qlib_view_spec_hash: str,
        qlib_view_hash: str,
        qlib_run_id: str | None,
        pit_evidence_hash: str,
        transform_lineage_hash: str,
        expression_translation_hash: str,
        row_count: int,
        signal_start: datetime,
        signal_end: datetime,
        signal_content_hash: str,
        files: tuple[SignalArtifactFile, ...],
        created_at: datetime,
    ) -> Self:
        input_hashes = (
            SignalInputHash(kind="expression_translation", sha256=expression_translation_hash),
            SignalInputHash(kind="pit_evidence", sha256=pit_evidence_hash),
            SignalInputHash(kind="qlib_view_cache", sha256=qlib_view_hash),
            SignalInputHash(kind="qlib_view_spec", sha256=qlib_view_spec_hash),
            SignalInputHash(kind="resolved_experiment", sha256=resolved_experiment_hash),
            SignalInputHash(kind="snapshot", sha256=snapshot_hash),
        )
        payload = {
            "schema_version": "signal-artifact-manifest/v2",
            "resolved_experiment_hash": resolved_experiment_hash,
            "source_expression_or_model_hash": source_expression_or_model_hash,
            "snapshot_hash": snapshot_hash,
            "qlib_version": qlib_version,
            "qlib_view_spec_hash": qlib_view_spec_hash,
            "qlib_view_hash": qlib_view_hash,
            "qlib_run_id": qlib_run_id,
            "pit_evidence_hash": pit_evidence_hash,
            "transform_lineage_hash": transform_lineage_hash,
            "expression_translation_hash": expression_translation_hash,
            "tradability_policy": "not_st_and_not_suspended/v1",
            "input_hashes": input_hashes,
            "row_count": row_count,
            "signal_start": signal_start,
            "signal_end": signal_end,
            "signal_schema": (
                "instrument_id:string:not_null",
                "signal_time:timestamp[us,Asia/Shanghai]:not_null",
                "decision_time:timestamp[us,Asia/Shanghai]:not_null",
                "available_at:timestamp[us,Asia/Shanghai]:not_null",
                "score:float64:nullable",
                "score_valid:bool:not_null",
                "tradable:bool:not_null",
            ),
            "signal_content_hash": signal_content_hash,
            "files": files,
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            artifact_hash=digest,
            resolved_experiment_hash=resolved_experiment_hash,
            source_expression_or_model_hash=source_expression_or_model_hash,
            snapshot_hash=snapshot_hash,
            qlib_version=qlib_version,
            qlib_view_spec_hash=qlib_view_spec_hash,
            qlib_view_hash=qlib_view_hash,
            qlib_run_id=qlib_run_id,
            pit_evidence_hash=pit_evidence_hash,
            transform_lineage_hash=transform_lineage_hash,
            expression_translation_hash=expression_translation_hash,
            input_hashes=input_hashes,
            row_count=row_count,
            signal_start=signal_start,
            signal_end=signal_end,
            signal_content_hash=signal_content_hash,
            files=files,
            created_at=created_at.astimezone(UTC),
        )
