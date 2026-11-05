"""Explicit successor admissions for a finite, unchanged forward budget."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.personal_strategy import PersonalForwardScope
from quantos.contracts.refs import SHA256_PATTERN


class ForwardDatasetAdmission(CanonicalContract):
    schema_version: Literal["forward-dataset-admission/v1"] = "forward-dataset-admission/v1"
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    previous_dataset_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    previous_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    arrival_hash: str = Field(pattern=SHA256_PATTERN)
    end_date: date


class PersonalForwardScopeV2(PersonalForwardScope):
    schema_version: Literal["personal-forward-scope/v2"] = "personal-forward-scope/v2"  # pyright: ignore[reportIncompatibleVariableOverride]
    max_dataset_successors: int = Field(ge=1, le=61)
    initial_bridge_sessions: int = Field(default=1, ge=1, le=2)
    observation_id: str = Field(pattern=SHA256_PATTERN)
    shadow_id: str = Field(pattern=SHA256_PATTERN)
    wall_seconds: int = Field(gt=0, le=86400)
    growth_bytes: int = Field(gt=0, le=16 * 1024**3)
    per_job_wall_seconds: int = Field(gt=0, le=1800)
    per_job_growth_bytes: int = Field(gt=0, le=8 * 1024**3)
    dataset_admission_policy: Literal["EXPLICIT_CONTIGUOUS_SNAPSHOT_CHAIN"] = (
        "EXPLICIT_CONTIGUOUS_SNAPSHOT_CHAIN"
    )

    @model_validator(mode="after")
    def one_origin(self) -> Self:
        if len(self.allowed_dataset_hashes) != 1:
            raise ValueError("successor scope requires exactly one explicit origin dataset")
        return self


def parse_forward_scope(raw: bytes) -> PersonalForwardScope:
    import json

    version = json.loads(raw).get("schema_version")
    model = (
        PersonalForwardScopeV2 if version == "personal-forward-scope/v2" else PersonalForwardScope
    )
    return model.model_validate_json(raw)
