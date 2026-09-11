"""Immutable export of Qlib SignalRecord and SigAnaRecord outputs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path


class ResearchResultValueRow(CanonicalContract):
    schema_version: Literal["research-result-value-row/v1"] = "research-result-value-row/v1"
    trade_date: date
    qlib_instrument_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    value: float


class ResearchResultSeriesRow(CanonicalContract):
    schema_version: Literal["research-result-series-row/v1"] = "research-result-series-row/v1"
    trade_date: date
    value: float


class ResearchResultMetric(CanonicalContract):
    schema_version: Literal["research-result-metric/v1"] = "research-result-metric/v1"
    name: Literal["IC", "ICIR", "Rank IC", "Rank ICIR"]
    value: float


class ResearchResultSourceFile(CanonicalContract):
    schema_version: Literal["research-result-source-file/v1"] = "research-result-source-file/v1"
    logical_path: Literal[
        "label.pkl", "metrics.json", "pred.pkl", "sig_analysis/ic.pkl", "sig_analysis/ric.pkl"
    ]
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt


class ResearchResultArtifactFile(CanonicalContract):
    schema_version: Literal["research-result-artifact-file/v1"] = "research-result-artifact-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class ResearchResultManifest(CanonicalContract):
    """Content-addressed, deterministic adapter over Qlib-native record outputs."""

    schema_version: Literal["research-result-manifest/v1"] = "research-result-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"artifact_hash", "created_at"})

    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str = Field(pattern=SHA256_PATTERN)
    signal_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_run_id: str = Field(min_length=1)
    segment: Literal["test"] = "test"
    label_expression: str = Field(min_length=1)
    label_horizon_trading_sessions: PositiveInt
    prediction_row_count: PositiveInt
    label_row_count: PositiveInt
    ic_row_count: PositiveInt
    rank_ic_row_count: PositiveInt
    prediction_content_hash: str = Field(pattern=SHA256_PATTERN)
    label_content_hash: str = Field(pattern=SHA256_PATTERN)
    ic_content_hash: str = Field(pattern=SHA256_PATTERN)
    rank_ic_content_hash: str = Field(pattern=SHA256_PATTERN)
    metrics: tuple[ResearchResultMetric, ...]
    source_files: tuple[ResearchResultSourceFile, ...]
    files: tuple[ResearchResultArtifactFile, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("metrics")
    @classmethod
    def metrics_are_exact_and_ordered(
        cls, value: tuple[ResearchResultMetric, ...]
    ) -> tuple[ResearchResultMetric, ...]:
        if tuple(item.name for item in value) != ("IC", "ICIR", "Rank IC", "Rank ICIR"):
            raise ValueError("ResearchResult requires ordered Qlib IC and Rank IC summaries")
        return value

    @field_validator("source_files")
    @classmethod
    def sources_are_exact_and_ordered(
        cls, value: tuple[ResearchResultSourceFile, ...]
    ) -> tuple[ResearchResultSourceFile, ...]:
        expected = (
            "label.pkl",
            "metrics.json",
            "pred.pkl",
            "sig_analysis/ic.pkl",
            "sig_analysis/ric.pkl",
        )
        if tuple(item.logical_path for item in value) != expected:
            raise ValueError("ResearchResult source file set is incomplete")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact_and_ordered(
        cls, value: tuple[ResearchResultArtifactFile, ...]
    ) -> tuple[ResearchResultArtifactFile, ...]:
        expected = (
            "ic-series.json",
            "labels.json",
            "predictions.json",
            "rank-ic-series.json",
            "research-policy.json",
            "resolved-experiment.json",
        )
        if tuple(item.logical_path for item in value) != expected:
            raise ValueError("ResearchResult artifact file set is incomplete")
        return value

    @model_validator(mode="after")
    def artifact_hash_matches_payload(self) -> Self:
        if self.artifact_hash != self.content_hash:
            raise ValueError("artifact_hash does not match ResearchResult manifest content")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {"schema_version": "research-result-manifest/v1", **values}
        payload.pop("artifact_hash", None)
        payload.pop("created_at", None)
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls.model_validate({"artifact_hash": digest, **values})
