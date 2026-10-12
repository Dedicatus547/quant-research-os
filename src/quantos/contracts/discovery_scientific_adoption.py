"""Explicit origin-preserving reuse; neither a replacement receipt nor scientific PASS."""

import re
from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.refs import SHA256_PATTERN


class ScientificSourceFileEquality(CanonicalContract):
    schema_version: Literal["scientific-source-file-equality/v1"] = (
        "scientific-source-file-equality/v1"
    )
    logical_path: str = Field(min_length=1)
    source_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_hash: str = Field(pattern=SHA256_PATTERN)


class ScientificSourceDependencyAdoption(CanonicalContract):
    schema_version: Literal["scientific-source-dependency-adoption/v1"] = (
        "scientific-source-dependency-adoption/v1"
    )
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_design_hash: str = Field(pattern=SHA256_PATTERN)
    original_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluation_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_workspace: str = Field(min_length=1)
    evaluation_workspace: str = Field(min_length=1)
    original_capsule: PredictionFileSource
    original_inventory: PredictionFileSource
    evaluation_capsule: PredictionFileSource
    evaluation_inventory: PredictionFileSource
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_execution_policy_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_files: tuple[ScientificSourceFileEquality, ...]
    historical_models_retrained: Literal[False] = False
    new_task_model_predictions_recomputed: Literal[True] = True
    original_qualification_transferred: Literal[False] = False


class ScientificAdoptedOrigin(CanonicalContract):
    schema_version: Literal["scientific-adopted-origin/v1"] = "scientific-adopted-origin/v1"
    target_subtask_hash: str = Field(pattern=SHA256_PATTERN)
    source_subtask_hash: str = Field(pattern=SHA256_PATTERN)
    source_request: PredictionFileSource
    source_outcome: PredictionFileSource
    source_receipt: PredictionFileSource
    source_subtask: PredictionFileSource
    source_design: PredictionFileSource
    source_task_root: str = Field(min_length=1)
    source_native_root: str | None
    native_files: tuple[PredictionFileSource, ...]
    interpretation: Literal["ADOPTED_HISTORICAL_ORIGIN_UNCHANGED"] = (
        "ADOPTED_HISTORICAL_ORIGIN_UNCHANGED"
    )


class ScientificAdoptionPlan(CanonicalContract):
    schema_version: Literal["scientific-adoption-plan/v1"] = "scientific-adoption-plan/v1"
    original_sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_dependency_adoption_hash: str = Field(pattern=SHA256_PATTERN)
    new_subtask_hashes: tuple[str, ...]
    origins: tuple[ScientificAdoptedOrigin, ...]
    original_failures_preserved: Literal[True] = True
    new_receipts_for_adopted_origins: Literal[False] = False

    @model_validator(mode="after")
    def fixed_partition(self) -> Self:
        if self.new_subtask_hashes != tuple(sorted(set(self.new_subtask_hashes))) or any(
            not re.fullmatch(SHA256_PATTERN, value) for value in self.new_subtask_hashes
        ):
            raise ValueError("new execution tasks require ordered unique hashes")
        keys = tuple(item.target_subtask_hash for item in self.origins)
        if keys != tuple(sorted(set(keys))) or set(keys) & set(self.new_subtask_hashes):
            raise ValueError("adopted origins and new tasks must partition the fixed cohort")
        return self
