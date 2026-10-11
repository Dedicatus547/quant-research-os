"""Explicit successor evaluation of retained proposals, with no new generation."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator

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
