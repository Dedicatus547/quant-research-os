"""Typed contracts for the restricted Quant Research MCP surface."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict


def _hashes(value: tuple[str, ...], *, nonempty: bool = False) -> tuple[str, ...]:
    if (nonempty and not value) or value != tuple(sorted(set(value))):
        raise ValueError("hashes must be sorted and unique")
    if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
        raise ValueError("hash is invalid")
    return value


class DatasetLookupRequest(CanonicalContract):
    schema_version: Literal["dataset-lookup-request/v1"] = "dataset-lookup-request/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)


class DatasetDescription(CanonicalContract):
    schema_version: Literal["dataset-description/v1"] = "dataset-description/v1"
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    source_kind: SnapshotSourceKind
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quality_report_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1, max_length=100)
    limitations: tuple[str, ...]


class DatasetFieldKind(StrEnum):
    ADJUSTED_PRICE = "ADJUSTED_PRICE"
    QLIB_DERIVED_VIEW = "QLIB_DERIVED_VIEW"


class DatasetFieldDescriptor(CanonicalContract):
    schema_version: Literal["dataset-field-descriptor/v1"] = "dataset-field-descriptor/v1"
    field_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    field_kind: DatasetFieldKind
    source_artifact_hash: str = Field(pattern=SHA256_PATTERN)


class DatasetFieldCatalog(CanonicalContract):
    schema_version: Literal["dataset-field-catalog/v1"] = "dataset-field-catalog/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    fields: tuple[DatasetFieldDescriptor, ...]

    @field_validator("fields")
    @classmethod
    def fields_are_nonempty_sorted(
        cls, value: tuple[DatasetFieldDescriptor, ...]
    ) -> tuple[DatasetFieldDescriptor, ...]:
        names = [item.field_name for item in value]
        if not names or names != sorted(set(names)):
            raise ValueError("dataset fields must be nonempty, sorted, and unique")
        return value


class ExperimentResolutionRequest(CanonicalContract):
    schema_version: Literal["experiment-resolution-request/v1"] = "experiment-resolution-request/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    observation_hash: str = Field(pattern=SHA256_PATTERN)
    hypothesis_hash: str = Field(pattern=SHA256_PATTERN)
    factor_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    experiment_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_hashes: tuple[str, ...]
    input_hashes: tuple[str, ...]

    @field_validator("agent_run_hashes", "input_hashes")
    @classmethod
    def references_are_bound(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value, nonempty=True)

    @model_validator(mode="after")
    def envelope_is_complete(self) -> Self:
        required = {
            self.observation_hash,
            self.hypothesis_hash,
            self.factor_proposal_hash,
            self.experiment_proposal_hash,
            self.campaign_hash,
            self.family_hash,
            self.budget_hash,
            *self.agent_run_hashes,
        }
        if not required.issubset(self.input_hashes):
            raise ValueError("resolution request omits frozen input hashes")
        return self


class ExperimentResolutionReceipt(CanonicalContract):
    schema_version: Literal["experiment-resolution-receipt/v1"] = "experiment-resolution-receipt/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    compiled_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    authoring_spec_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_bound(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value, nonempty=True)


class McpWriteAuditEvent(CanonicalContract):
    schema_version: Literal["mcp-write-audit-event/v1"] = "mcp-write-audit-event/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    sequence: Literal[1] = 1
    capability: Literal["experiment.resolve", "experiment.request_execution"]
    request_hash: str = Field(pattern=SHA256_PATTERN)
    response_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_hashes: tuple[str, ...]
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]

    @field_validator("agent_run_hashes", "input_hashes")
    @classmethod
    def audit_hashes_are_bound(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value, nonempty=True)


class ExperimentExecutionRequest(CanonicalContract):
    schema_version: Literal["experiment-execution-request/v1"] = "experiment-execution-request/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    compiled_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]
    timeout_seconds: PositiveInt

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_bound(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _hashes(value, nonempty=True)

    @model_validator(mode="after")
    def envelope_is_complete(self) -> Self:
        required = {
            self.compiled_proposal_hash,
            self.agent_run_hash,
            self.campaign_hash,
            self.budget_hash,
        }
        if not required.issubset(self.input_hashes):
            raise ValueError("execution request omits authority input hashes")
        return self


class ExecutionJobState(StrEnum):
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    TIMED_OUT = "TIMED_OUT"


class ExecutionOutcome(CanonicalContract):
    """Trusted deterministic executor output; never accepted from an Agent payload."""

    schema_version: Literal["execution-outcome/v1"] = "execution-outcome/v1"
    run_status: RunStatus
    validation_verdict: ValidationVerdict
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    registry_manifest_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    registry_index_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    compute_seconds: NonNegativeInt
    reason_code: ReasonCode | None = None

    @model_validator(mode="after")
    def authority_result_is_consistent(self) -> Self:
        hashes = (
            self.validation_report_hash,
            self.registry_manifest_hash,
            self.registry_index_hash,
        )
        if self.run_status is RunStatus.FAILED:
            if self.validation_verdict is not ValidationVerdict.NOT_EVALUATED or any(hashes):
                raise ValueError("failed execution must be NOT_EVALUATED without authority hashes")
            if self.reason_code is None:
                raise ValueError("failed execution requires a reason code")
        elif self.validation_verdict is ValidationVerdict.NOT_EVALUATED or not all(hashes):
            raise ValueError("successful execution requires final immutable authority hashes")
        elif self.reason_code is not None:
            raise ValueError("successful execution cannot carry a failure reason")
        return self


class ExecutionJobReceipt(CanonicalContract):
    schema_version: Literal["execution-job-receipt/v1"] = "execution-job-receipt/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    job_id: str = Field(pattern=SHA256_PATTERN)
    compiled_proposal_hash: str = Field(pattern=SHA256_PATTERN)


class ExecutionJobEvent(CanonicalContract):
    schema_version: Literal["execution-job-event/v1"] = "execution-job-event/v1"
    job_id: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    sequence: PositiveInt
    state: ExecutionJobState
    outcome: ExecutionOutcome | None = None
    reason_code: ReasonCode | None = None

    @model_validator(mode="after")
    def event_matches_state(self) -> Self:
        if self.state is ExecutionJobState.SUCCEEDED:
            if self.outcome is None or self.outcome.run_status is not RunStatus.SUCCEEDED:
                raise ValueError("successful job event requires successful execution evidence")
        elif self.state is ExecutionJobState.FAILED:
            if self.outcome is None or self.outcome.run_status is not RunStatus.FAILED:
                raise ValueError("failed job event requires failed execution evidence")
        elif self.outcome is not None:
            raise ValueError("nonterminal execution event cannot include an outcome")
        if self.state in {ExecutionJobState.CANCELLED, ExecutionJobState.TIMED_OUT}:
            if self.reason_code is None:
                raise ValueError("cancelled/timed-out job requires a reason code")
        elif self.reason_code is not None:
            raise ValueError("only cancelled/timed-out job events carry a direct reason")
        return self


class ExecutionJob(CanonicalContract):
    schema_version: Literal["execution-job/v1"] = "execution-job/v1"
    job_id: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    compiled_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    state: ExecutionJobState
    event_hashes: tuple[str, ...]
    outcome: ExecutionOutcome | None = None

    @field_validator("event_hashes")
    @classmethod
    def events_are_ordered_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("job must bind a nonempty unique event chain")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("job event hash is invalid")
        return value

    @model_validator(mode="after")
    def projection_matches_terminal_state(self) -> Self:
        terminal = self.state in {ExecutionJobState.FAILED, ExecutionJobState.SUCCEEDED}
        if terminal != (self.outcome is not None):
            raise ValueError("job outcome and terminal state disagree")
        return self


class JobLookupRequest(CanonicalContract):
    schema_version: Literal["job-lookup-request/v1"] = "job-lookup-request/v1"
    job_id: str = Field(pattern=SHA256_PATTERN)


class ValidationLookupRequest(CanonicalContract):
    schema_version: Literal["validation-lookup-request/v1"] = "validation-lookup-request/v1"
    validation_report_hash: str = Field(pattern=SHA256_PATTERN)


class RegistryResourceKind(StrEnum):
    EXPERIMENT = "EXPERIMENT"
    STRATEGY = "STRATEGY"


class RegistryGetRequest(CanonicalContract):
    schema_version: Literal["registry-get-request/v1"] = "registry-get-request/v1"
    resource_kind: RegistryResourceKind
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: PositiveInt | None = None

    @model_validator(mode="after")
    def version_matches_kind(self) -> Self:
        if (self.resource_kind is RegistryResourceKind.STRATEGY) != (self.version is not None):
            raise ValueError("strategy lookup requires an explicit version only")
        return self


class RegistrySearchRequest(CanonicalContract):
    schema_version: Literal["registry-search-request/v1"] = "registry-search-request/v1"
    experiment_id_prefix: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    strategy_id_prefix: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    limit: PositiveInt = Field(default=20, le=100)


class RegistrySearchHit(CanonicalContract):
    schema_version: Literal["registry-search-hit/v1"] = "registry-search-hit/v1"
    resource_kind: RegistryResourceKind
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: PositiveInt | None = None
    artifact_hash: str = Field(pattern=SHA256_PATTERN)


class RegistrySearchResult(CanonicalContract):
    schema_version: Literal["registry-search-result/v1"] = "registry-search-result/v1"
    registry_index_hash: str = Field(pattern=SHA256_PATTERN)
    hits: tuple[RegistrySearchHit, ...]
    truncated: bool
