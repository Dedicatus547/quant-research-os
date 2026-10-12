"""Explicit successor evaluation of retained proposals, with no new generation."""

from __future__ import annotations

import json
from typing import Literal, Self, cast

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from quantos.contracts.autonomous import AutonomousExecutionBindings
from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class DiscoveryEvaluationDeclaration(CanonicalContract):
    schema_version: Literal["discovery-evaluation-declaration/v1"] = (
        "discovery-evaluation-declaration/v1"
    )
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_design_hash: str = Field(pattern=SHA256_PATTERN)
    original_generation_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    bindings: AutonomousExecutionBindings
    max_compute_units: PositiveInt
    source_adoption_record_hash: str = Field(pattern=SHA256_PATTERN)
    reason: Literal["DECLARED_CALENDAR_PURGE_CORRECTION"] = "DECLARED_CALENDAR_PURGE_CORRECTION"
    interpretation: Literal["RETROSPECTIVE_EXPLORATORY"] = "RETROSPECTIVE_EXPLORATORY"
    exposure_history_append: tuple[str, ...]
    no_new_generation: Literal[True] = True
    sealed_confirmation_accessed: Literal[False] = False

    @model_validator(mode="after")
    def exposure_is_explicit(self) -> Self:
        if not self.exposure_history_append or any(
            not item.strip() or len(item) > 4096 for item in self.exposure_history_append
        ):
            raise ValueError("successor evaluation must append actual exposure history")
        return self


class ScientificExecutionAuthorization(CanonicalContract):
    """Management-retained actual user authorization, independent of the generation cap."""

    schema_version: Literal["discovery-scientific-authorization/v1"] = (
        "discovery-scientific-authorization/v1"
    )
    user_instruction: str = Field(min_length=1, max_length=16_384)
    original_sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_execution_authorized: Literal[True] = True
    no_new_generation: Literal[True] = True
    sealed_confirmation_accessed: Literal[False] = False


class ScientificSchedulingCutoff(CanonicalContract):
    """New science scheduling authority; no fabricated predecessor run or process exit."""

    schema_version: Literal["discovery-scientific-scheduling-cutoff/v1"] = (
        "discovery-scientific-scheduling-cutoff/v1"
    )
    original_sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_design_hash: str = Field(pattern=SHA256_PATTERN)
    authorization_hash: str = Field(pattern=SHA256_PATTERN)
    old_generation_scheduling_permitted: Literal[False] = False
    new_generation_permitted: Literal[False] = False
    sealed_confirmation_permitted: Literal[False] = False


class ScientificEvaluationBudget(CanonicalContract):
    """New bounded workload authority; prior consumed commitments provide no balance."""

    schema_version: Literal["discovery-scientific-budget/v1"] = "discovery-scientific-budget/v1"
    full_batch_compute_units: PositiveInt
    new_execution_compute_units: NonNegativeInt
    max_compute_units: PositiveInt
    max_distinct_candidates: PositiveInt
    max_new_candidate_executions: NonNegativeInt
    max_failed_task_resumes: Literal[1] = 1
    accounting_scope: Literal["NEW_SCIENTIFIC_EXECUTION_ONLY"] = "NEW_SCIENTIFIC_EXECUTION_ONLY"
    historical_balance_transferred: Literal[False] = False

    @model_validator(mode="after")
    def fresh_bounds_agree(self) -> Self:
        if (
            self.new_execution_compute_units > self.full_batch_compute_units
            or self.new_execution_compute_units > self.max_compute_units
            or self.max_new_candidate_executions > self.max_distinct_candidates
        ):
            raise ValueError("independent scientific budget bounds disagree")
        return self


class ScientificEvaluationDeclaration(CanonicalContract):
    """Evaluate frozen proposals under explicit new authority; do not amend their design."""

    schema_version: Literal["discovery-scientific-evaluation-declaration/v2"] = (
        "discovery-scientific-evaluation-declaration/v2"
    )
    original_sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_generation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_design_hash: str = Field(pattern=SHA256_PATTERN)
    original_generation_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_generation_source_declaration_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_source_declaration_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    authorization_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_scheduling_cutoff_hash: str = Field(pattern=SHA256_PATTERN)
    budget: ScientificEvaluationBudget
    bindings: AutonomousExecutionBindings
    # v2 binds its independent scientific dependency adoption. Retained whole-task
    # predictions bind a separate origin plan and keep their original identities.
    source_adoption_record_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    original_scientific_source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    scientific_adoption_plan_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reason: Literal["AUTHORIZED_SCIENCE_FROM_FROZEN_SEQUENTIAL_GENERATION"] = (
        "AUTHORIZED_SCIENCE_FROM_FROZEN_SEQUENTIAL_GENERATION"
    )
    interpretation: Literal["RETROSPECTIVE_EXPLORATORY"] = "RETROSPECTIVE_EXPLORATORY"
    exposure_history_append: tuple[str, ...]
    no_new_generation: Literal[True] = True
    sealed_confirmation_accessed: Literal[False] = False

    @property
    def max_compute_units(self) -> int:
        return self.budget.max_compute_units

    @model_validator(mode="after")
    def science_authority_is_explicit(self) -> Self:
        if not self.exposure_history_append or any(
            not item.strip() or len(item) > 4096 for item in self.exposure_history_append
        ):
            raise ValueError("scientific evaluation must append actual exposure history")
        if (self.source_adoption_record_hash is None) != (
            self.original_scientific_source_commit is None
        ):
            raise ValueError("stage adoption requires its actual scientific source commit")
        return self


def parse_discovery_evaluation_declaration(
    data: bytes,
) -> DiscoveryEvaluationDeclaration | ScientificEvaluationDeclaration:
    """Explicit schema dispatch, preserving all old v1 validation and canonical bytes."""
    if len(data) > 2_097_152:
        raise ValueError("evaluation declaration exceeds its byte bound")
    value: object = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("evaluation declaration must be an object")
    version = cast(dict[str, object], value).get("schema_version")
    if version == "discovery-evaluation-declaration/v1":
        declaration = DiscoveryEvaluationDeclaration.model_validate_json(data)
    elif version == "discovery-scientific-evaluation-declaration/v2":
        declaration = ScientificEvaluationDeclaration.model_validate_json(data)
    else:
        raise ValueError("unsupported evaluation declaration schema")
    if declaration.canonical_bytes() != data:
        raise ValueError("evaluation declaration must use canonical bytes")
    return declaration
