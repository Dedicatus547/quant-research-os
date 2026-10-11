"""Origin-preserving adoption declarations for one explicit successor evaluation."""

from typing import Literal

from pydantic import Field

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class DiscoveryAdoptedVariant(CanonicalContract):
    schema_version: Literal["discovery-adopted-variant/v1"] = "discovery-adopted-variant/v1"
    subtask_hash: str = Field(pattern=SHA256_PATTERN)
    stage: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$")
    request_path: str = Field(min_length=1)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    signal_path: str = Field(min_length=1)
    signal_hash: str = Field(pattern=SHA256_PATTERN)
    signal_checkpoint_path: str = Field(min_length=1)
    signal_checkpoint_hash: str = Field(pattern=SHA256_PATTERN)
    pit_path: str = Field(min_length=1)
    pit_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_path: str | None = None
    backtest_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    backtest_checkpoint_path: str | None = None
    backtest_checkpoint_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class DiscoveryEvaluationSourceAdoption(CanonicalContract):
    schema_version: Literal["discovery-evaluation-source-adoption/v1"] = (
        "discovery-evaluation-source-adoption/v1"
    )
    original_batch_hash: str = Field(pattern=SHA256_PATTERN)
    original_design_hash: str = Field(pattern=SHA256_PATTERN)
    original_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluation_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_execution_policy_hash: str = Field(pattern=SHA256_PATTERN)
    original_workspace: str = Field(min_length=1)
    original_capsule_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_capsule_hash: str = Field(pattern=SHA256_PATTERN)
    source_delta_record_hash: str = Field(pattern=SHA256_PATTERN)
    supersession_cutoff_hash: str = Field(pattern=SHA256_PATTERN)
    unchanged_scientific_inputs: Literal[True] = True
    model_predictions_recomputed: Literal[True] = True
    original_qualification_transferred: Literal[False] = False
    native_science_origin_preserved: Literal[True] = True
    variants: tuple[DiscoveryAdoptedVariant, ...]
