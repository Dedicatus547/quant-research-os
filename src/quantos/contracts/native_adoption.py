"""Explicit origin receipts for verified native bytes, without a new scientific execution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, NonNegativeInt, field_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResolvedExperimentSpec,
    StrategyAuthoringSpec,
)


class AdoptedNativeFile(CanonicalContract):
    schema_version: Literal["adopted-native-file/v1"] = "adopted-native-file/v1"
    logical_path: str
    bytes_hash: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return validate_logical_path(value)


class NativeArtifactAdoptionReceipt(CanonicalContract):
    schema_version: Literal["native-artifact-adoption/v1"] = "native-artifact-adoption/v1"
    artifact_kind: Literal["FACTOR_SIGNAL", "QLIB_BACKTEST"]
    source_adoption_record_hash: str = Field(pattern=SHA256_PATTERN)
    original_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    adopted_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    original_resolved_hash: str = Field(pattern=SHA256_PATTERN)
    adopted_resolved_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_origin_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    adoption_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    original_stage_status: Literal["SUCCEEDED"] = "SUCCEEDED"
    parent_execution_status: Literal["NOT_ASSERTED"] = "NOT_ASSERTED"
    new_scientific_execution: Literal[False] = False
    native_files: tuple[AdoptedNativeFile, ...] = Field(min_length=1)
    metadata_rebindings: tuple[str, ...]
    adopted_at: datetime

    @field_validator("adopted_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adoption time must be timezone aware")
        return value


def verify_adoption_bindings(
    original: ResolvedExperimentSpec, adopted: ResolvedExperimentSpec
) -> None:
    """Allow source identity and explicitly reconstructed authoring labels only."""
    allowed = {"code_commit_hash", "experiment_id", "authoring_spec_hash"}
    if original.model_dump(exclude=allowed) != adopted.model_dump(exclude=allowed):
        raise ValueError("adoption changes mathematical or policy bindings")
    for resolved in (original, adopted):
        strategy = resolved.strategy.model_dump()
        strategy["schema_version"] = "strategy-authoring/v1"
        authoring = ExperimentAuthoringSpec(
            experiment_id=resolved.experiment_id,
            evaluation_start=resolved.evaluation_start,
            evaluation_end=resolved.evaluation_end,
            expression=resolved.expression,
            strategy=StrategyAuthoringSpec.model_validate(strategy),
        )
        if authoring.content_hash != resolved.authoring_spec_hash:
            raise ValueError("adoption authoring identity cannot be reconstructed")
