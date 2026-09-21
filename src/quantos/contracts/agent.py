"""Harness-independent proposal, capability, and AgentRun contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.evidence import LOGICAL_ID_PATTERN, EvidenceCitation, ProposedAttribute
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import StrategyAuthoringSpec, ThresholdComparison
from quantos.contracts.status import RunStatus


def _sorted_unique_hashes(value: tuple[str, ...], *, allow_empty: bool = True) -> tuple[str, ...]:
    if (not allow_empty and not value) or value != tuple(sorted(set(value))):
        raise ValueError("hash references must be sorted and unique")
    if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
        raise ValueError("hash reference is invalid")
    return value


class ExpectedDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NON_MONOTONIC = "NON_MONOTONIC"


class FalsificationCriterion(CanonicalContract):
    schema_version: Literal["falsification-criterion/v1"] = "falsification-criterion/v1"
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    comparison: ThresholdComparison
    threshold: float
    segment: Literal["VALIDATION", "SEALED_CONFIRMATION"]


class ObservationProposal(CanonicalContract):
    schema_version: Literal["observation-proposal/v1"] = "observation-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    statement: str = Field(min_length=1, max_length=10_000)
    citations: tuple[EvidenceCitation, ...]
    limitations: tuple[str, ...] = ()

    @field_validator("citations")
    @classmethod
    def citations_are_required(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        if not value:
            raise ValueError("observation proposal requires evidence citations")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value


class HypothesisProposal(CanonicalContract):
    schema_version: Literal["hypothesis-proposal/v1"] = "hypothesis-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    observation_hashes: tuple[str, ...]
    claim: str = Field(min_length=1, max_length=10_000)
    mechanism: str = Field(min_length=1, max_length=10_000)
    evidence_citations: tuple[EvidenceCitation, ...]
    expected_direction: ExpectedDirection
    confounders: tuple[str, ...] = ()
    falsification: tuple[FalsificationCriterion, ...]
    inherited_contamination: tuple[str, ...] = ()

    @field_validator("observation_hashes")
    @classmethod
    def observations_are_bound(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value, allow_empty=False)

    @field_validator("evidence_citations", "falsification")
    @classmethod
    def evidence_and_falsification_are_nonempty(
        cls, value: tuple[object, ...]
    ) -> tuple[object, ...]:
        if not value:
            raise ValueError("hypothesis requires evidence and falsification conditions")
        return value

    @field_validator("confounders")
    @classmethod
    def confounders_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("confounders must be sorted and unique")
        return value

    @field_validator("inherited_contamination")
    @classmethod
    def contamination_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)


class RegisteredFeatureRef(CanonicalContract):
    schema_version: Literal["registered-feature-ref/v1"] = "registered-feature-ref/v1"
    field_name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    source_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    availability_policy_hash: str = Field(pattern=SHA256_PATTERN)


class FactorProposalSpec(CanonicalContract):
    schema_version: Literal["factor-proposal/v1"] = "factor-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    hypothesis_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    factor_template_hash: str = Field(pattern=SHA256_PATTERN)
    parameters: tuple[ProposedAttribute, ...]
    expression: SafeQlibExpressionSpec
    registered_features: tuple[RegisteredFeatureRef, ...]
    rationale: str = Field(min_length=1, max_length=10_000)
    limitations: tuple[str, ...] = ()

    @field_validator("parameters")
    @classmethod
    def parameters_are_nonempty_sorted(
        cls, value: tuple[ProposedAttribute, ...]
    ) -> tuple[ProposedAttribute, ...]:
        names = [item.name for item in value]
        if not names or names != sorted(set(names)):
            raise ValueError("factor parameters must be nonempty, sorted, and unique")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @model_validator(mode="after")
    def every_field_is_registered(self) -> Self:
        registered = [item.field_name for item in self.registered_features]
        if registered != sorted(set(registered)):
            raise ValueError("registered features must be sorted and unique")
        used = {
            node.field_name
            for node in self.expression.nodes
            if node.operator is SafeQlibOperator.FIELD
        }
        if set(registered) != used:
            raise ValueError("factor proposal must bind every expression field exactly once")
        return self


class CampaignSegment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    SEALED_CONFIRMATION = "SEALED_CONFIRMATION"


class ExperimentProposalSpec(CanonicalContract):
    schema_version: Literal["experiment-proposal/v1"] = "experiment-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    factor_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    segment: CampaignSegment
    evaluation_start: date
    evaluation_end: date
    strategy: StrategyAuthoringSpec
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    feature_artifact_hashes: tuple[str, ...] = ()

    @field_validator("feature_artifact_hashes")
    @classmethod
    def feature_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)

    @model_validator(mode="after")
    def evaluation_range_is_ordered(self) -> Self:
        if self.evaluation_start > self.evaluation_end:
            raise ValueError("proposal evaluation range is reversed")
        return self


class InterpretationProposal(CanonicalContract):
    schema_version: Literal["interpretation-proposal/v1"] = "interpretation-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    validation_report_hash: str = Field(pattern=SHA256_PATTERN)
    summary: str = Field(min_length=1, max_length=20_000)
    findings: tuple[str, ...]
    next_question: str | None = Field(default=None, min_length=1, max_length=10_000)
    inherited_contamination: tuple[str, ...] = ()

    @field_validator("findings")
    @classmethod
    def findings_are_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("interpretation proposal requires findings")
        return value

    @field_validator("inherited_contamination")
    @classmethod
    def contamination_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)


class AgentCapability(StrEnum):
    DATASET_DESCRIBE = "dataset.describe"
    DATASET_FIELDS = "dataset.fields"
    EVIDENCE_CITE = "evidence.cite"
    EVIDENCE_GET = "evidence.get"
    EVIDENCE_SEARCH = "evidence.search"
    EXPERIMENT_REQUEST_EXECUTION = "experiment.request_execution"
    EXPERIMENT_RESOLVE = "experiment.resolve"
    JOB_GET = "job.get"
    PROPOSAL_SUBMIT_EXPERIMENT = "proposal.submit_experiment"
    PROPOSAL_SUBMIT_FACTOR = "proposal.submit_factor"
    PROPOSAL_SUBMIT_HYPOTHESIS = "proposal.submit_hypothesis"
    REGISTRY_GET = "registry.get"
    REGISTRY_SEARCH = "registry.search"
    RESEARCH_SEARCH_LEDGER = "research.search_ledger"
    VALIDATION_GET = "validation.get"


class AgentCapabilityPolicy(CanonicalContract):
    schema_version: Literal["agent-capability-policy/v1"] = "agent-capability-policy/v1"
    policy_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    capabilities: tuple[AgentCapability, ...]
    max_payload_bytes: PositiveInt
    max_payload_depth: PositiveInt
    max_payload_nodes: PositiveInt
    max_string_bytes: PositiveInt
    max_requests: PositiveInt
    environment_allowlist: tuple[Literal["LANG", "LC_ALL", "LC_CTYPE", "TZ"], ...] = ()
    network_allowed: Literal[False] = False
    authority_filesystem_allowed: Literal[False] = False
    direct_cli_allowed: Literal[False] = False

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_nonempty_sorted(
        cls, value: tuple[AgentCapability, ...]
    ) -> tuple[AgentCapability, ...]:
        if not value or list(value) != sorted(set(value), key=str):
            raise ValueError("capabilities must be nonempty, sorted, and unique")
        return value

    @field_validator("environment_allowlist")
    @classmethod
    def environment_is_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("environment allowlist must be sorted and unique")
        return value


class AgentRole(StrEnum):
    FORMALIZER = "FORMALIZER"
    RESEARCHER = "RESEARCHER"
    REVIEWER = "REVIEWER"


class AgentRunSpec(CanonicalContract):
    schema_version: Literal["agent-run-spec/v1"] = "agent-run-spec/v1"
    run_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    role: AgentRole
    capability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    requested_model_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hashes: tuple[str, ...] = ()
    ledger_snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    input_artifact_hashes: tuple[str, ...] = ()

    @field_validator("instruction_hashes")
    @classmethod
    def instruction_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value, allow_empty=False)

    @field_validator("evidence_hashes", "input_artifact_hashes")
    @classmethod
    def optional_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)


class ToolInteractionDigest(CanonicalContract):
    schema_version: Literal["tool-interaction-digest/v1"] = "tool-interaction-digest/v1"
    sequence: PositiveInt
    capability: AgentCapability
    request_hash: str = Field(pattern=SHA256_PATTERN)
    response_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    succeeded: bool

    @model_validator(mode="after")
    def response_matches_outcome(self) -> Self:
        if self.succeeded != (self.response_hash is not None):
            raise ValueError("tool outcome and response hash disagree")
        return self


class AgentUsage(CanonicalContract):
    schema_version: Literal["agent-usage/v1"] = "agent-usage/v1"
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt = 0
    tool_calls: NonNegativeInt
    retry_count: NonNegativeInt


class AgentRunManifest(CanonicalContract):
    schema_version: Literal["agent-run-manifest/v1"] = "agent-run-manifest/v1"
    run_spec_hash: str = Field(pattern=SHA256_PATTERN)
    provider_thread_id: str = Field(min_length=1, max_length=500)
    provider_model_identifier: str = Field(min_length=1, max_length=500)
    model_snapshot_immutable: bool
    model_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    harness_identifier: str = Field(min_length=1, max_length=500)
    sandbox_policy_hash: str = Field(pattern=SHA256_PATTERN)
    permission_policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    interactions: tuple[ToolInteractionDigest, ...]
    input_hashes: tuple[str, ...]
    output_proposal_hashes: tuple[str, ...] = ()
    transcript_hash: str = Field(pattern=SHA256_PATTERN)
    usage: AgentUsage
    run_status: RunStatus
    failure_reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    limitations: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime
    process_return_code: int | None = None
    process_stderr_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("instruction_hashes", "input_hashes", "output_proposal_hashes")
    @classmethod
    def hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @field_validator("interactions")
    @classmethod
    def interactions_are_contiguous(
        cls, value: tuple[ToolInteractionDigest, ...]
    ) -> tuple[ToolInteractionDigest, ...]:
        if [item.sequence for item in value] != list(range(1, len(value) + 1)):
            raise ValueError("tool interactions must use contiguous sequence numbers")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AgentRun timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def run_outcome_is_consistent(self) -> Self:
        if self.run_status is RunStatus.SUCCEEDED:
            if self.failure_reason_code is not None or not self.output_proposal_hashes:
                raise ValueError("successful Agent run requires proposal output and no failure")
        elif self.failure_reason_code is None or self.output_proposal_hashes:
            raise ValueError("failed Agent run requires a reason and no proposal authority")
        if self.usage.tool_calls != len(self.interactions):
            raise ValueError("usage tool-call count does not match interactions")
        if not self.instruction_hashes or not self.input_hashes:
            raise ValueError("Agent run must bind instructions and inputs")
        if self.started_at > self.completed_at:
            raise ValueError("Agent run timestamps are reversed")
        if not self.model_snapshot_immutable and "MODEL_IDENTIFIER_NOT_IMMUTABLE" not in (
            self.limitations
        ):
            raise ValueError("mutable model identifier limitation must be explicit")
        return self


class AgentRunSpecV2(CanonicalContract):
    schema_version: Literal["agent-run-spec/v2"] = "agent-run-spec/v2"
    run_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    role: AgentRole
    capability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    requested_model_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    requested_runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    transcript_policy_hash: str = Field(pattern=SHA256_PATTERN)
    retry_budget_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hashes: tuple[str, ...] = ()
    ledger_snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    input_artifact_hashes: tuple[str, ...] = ()

    @field_validator("instruction_hashes")
    @classmethod
    def instruction_hashes_are_sorted_v2(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value, allow_empty=False)

    @field_validator("evidence_hashes", "input_artifact_hashes")
    @classmethod
    def optional_hashes_are_sorted_v2(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)


class AgentRunSpecV3(CanonicalContract):
    """SDK run specification with v3 manifest provenance semantics."""

    schema_version: Literal["agent-run-spec/v3"] = "agent-run-spec/v3"
    run_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    role: AgentRole
    capability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    requested_model_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    requested_runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    transcript_policy_hash: str = Field(pattern=SHA256_PATTERN)
    retry_budget_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hashes: tuple[str, ...] = ()
    ledger_snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    input_artifact_hashes: tuple[str, ...] = ()

    @field_validator("instruction_hashes")
    @classmethod
    def instruction_hashes_are_sorted_v3(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value, allow_empty=False)

    @field_validator("evidence_hashes", "input_artifact_hashes")
    @classmethod
    def optional_hashes_are_sorted_v3(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)


class HarnessAttemptRecord(CanonicalContract):
    schema_version: Literal["harness-attempt-record/v1"] = "harness-attempt-record/v1"
    attempt_index: PositiveInt
    provider_thread_id: str | None = Field(default=None, max_length=500)
    event_stream_hash: str = Field(pattern=SHA256_PATTERN)
    usage: AgentUsage
    terminal_error_kind: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    terminal_error_message_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    error_retryable: bool = False
    produced_proposal_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    started_at: datetime
    completed_at: datetime

    @field_validator("started_at", "completed_at")
    @classmethod
    def attempt_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("harness attempt timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def attempt_outcome_is_consistent(self) -> Self:
        if self.started_at > self.completed_at:
            raise ValueError("harness attempt timestamps are reversed")
        has_error = self.terminal_error_kind is not None
        if has_error != (self.terminal_error_message_hash is not None):
            raise ValueError("harness attempt error kind and message hash must appear together")
        if has_error and self.produced_proposal_hash is not None:
            raise ValueError("failed harness attempt cannot produce a proposal")
        if self.error_retryable and not has_error:
            raise ValueError("successful harness attempt cannot be retryable")
        return self


class AgentRunManifestV2(CanonicalContract):
    schema_version: Literal["agent-run-manifest/v2"] = "agent-run-manifest/v2"
    run_spec_hash: str = Field(pattern=SHA256_PATTERN)
    provider_model_identifier: str = Field(min_length=1, max_length=500)
    model_snapshot_immutable: Literal[False] = False
    adapter_identifier: Literal["openai-codex-python-sdk"] = "openai-codex-python-sdk"
    sdk_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    runtime_version: str | None = Field(default=None, min_length=1, max_length=500)
    protocol_identifier: Literal["codex-app-server-jsonrpc-v2"] = "codex-app-server-jsonrpc-v2"
    normalizer_identifier: Literal["quantos-codex-normalizer/v1"] = "quantos-codex-normalizer/v1"
    normalizer_hash: str = Field(pattern=SHA256_PATTERN)
    requested_policy_hash: str = Field(pattern=SHA256_PATTERN)
    effective_policy_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    interactions: tuple[ToolInteractionDigest, ...]
    input_hashes: tuple[str, ...]
    output_proposal_hashes: tuple[str, ...] = ()
    normalized_transcript_hash: str = Field(pattern=SHA256_PATTERN)
    provider_transcript_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_transcript_retention_reason: str | None = Field(default=None, max_length=500)
    attempts: tuple[HarnessAttemptRecord, ...]
    aggregate_usage: AgentUsage
    run_status: RunStatus
    failure_reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    limitations: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime

    @property
    def usage(self) -> AgentUsage:
        """Compatibility view for consumers that only need aggregate usage."""

        return self.aggregate_usage

    @field_validator("instruction_hashes", "input_hashes", "output_proposal_hashes")
    @classmethod
    def manifest_hashes_are_sorted_v2(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted_v2(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def manifest_timestamps_are_aware_v2(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AgentRun timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def manifest_outcome_is_consistent_v2(self) -> Self:
        if self.started_at > self.completed_at:
            raise ValueError("AgentRun timestamps are reversed")
        if not self.attempts or [item.attempt_index for item in self.attempts] != list(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("harness attempts must be nonempty and contiguous")
        if any(
            item.terminal_error_kind is None or not item.error_retryable
            for item in self.attempts[:-1]
        ):
            raise ValueError("only retryable failed attempts may precede the terminal attempt")
        proposals = tuple(
            item.produced_proposal_hash
            for item in self.attempts
            if item.produced_proposal_hash is not None
        )
        if len(proposals) > 1 or proposals != self.output_proposal_hashes:
            raise ValueError("manifest proposal hashes do not match harness attempts")
        if self.run_status is RunStatus.SUCCEEDED:
            if self.failure_reason_code is not None or len(proposals) != 1:
                raise ValueError("successful Agent run requires one proposal and no failure")
            if self.sdk_version is None or self.runtime_version is None:
                raise ValueError("successful Agent run requires SDK and runtime identity")
            if self.attempts[-1].produced_proposal_hash is None:
                raise ValueError("only the final harness attempt may produce a proposal")
        elif self.failure_reason_code is None or proposals:
            raise ValueError("failed Agent run requires a reason and no proposal")
        elif self.attempts[-1].terminal_error_kind is None:
            raise ValueError("failed Agent run requires a terminal attempt error")
        expected_usage = AgentUsage(
            input_tokens=sum(item.usage.input_tokens for item in self.attempts),
            output_tokens=sum(item.usage.output_tokens for item in self.attempts),
            cached_input_tokens=sum(item.usage.cached_input_tokens for item in self.attempts),
            tool_calls=sum(item.usage.tool_calls for item in self.attempts),
            retry_count=max(0, len(self.attempts) - 1),
        )
        if self.aggregate_usage != expected_usage:
            raise ValueError("aggregate usage does not match harness attempts")
        if self.aggregate_usage.tool_calls != len(self.interactions):
            raise ValueError("usage tool-call count does not match interactions")
        if not self.instruction_hashes or not self.input_hashes:
            raise ValueError("Agent run must bind instructions and inputs")
        if not self.model_snapshot_immutable and "MODEL_IDENTIFIER_NOT_IMMUTABLE" not in (
            self.limitations
        ):
            raise ValueError("mutable model identifier limitation must be explicit")
        if (self.provider_transcript_hash is None) == (
            self.provider_transcript_retention_reason is None
        ):
            raise ValueError("provider transcript hash or non-retention reason is required")
        return self


class AgentRunManifestV3(CanonicalContract):
    """Agent run provenance that never equates requested and effective policy."""

    schema_version: Literal["agent-run-manifest/v3"] = "agent-run-manifest/v3"
    run_spec_hash: str = Field(pattern=SHA256_PATTERN)
    provider_model_identifier: str = Field(min_length=1, max_length=500)
    model_snapshot_immutable: Literal[False] = False
    adapter_identifier: Literal["openai-codex-python-sdk"] = "openai-codex-python-sdk"
    sdk_distribution: Literal["openai-codex"] = "openai-codex"
    sdk_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    runtime_distribution: Literal["openai-codex-cli-bin"] = "openai-codex-cli-bin"
    runtime_package_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    runtime_version: str | None = Field(default=None, min_length=1, max_length=500)
    runtime_binary_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    protocol_identifier: Literal["codex-app-server-jsonrpc-v2"] = "codex-app-server-jsonrpc-v2"
    normalizer_identifier: Literal["quantos-codex-normalizer/v1"] = "quantos-codex-normalizer/v1"
    normalizer_hash: str = Field(pattern=SHA256_PATTERN)
    requested_policy_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_runtime_config_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    capability_observation_hash: str = Field(pattern=SHA256_PATTERN)
    attested_policy_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    interactions: tuple[ToolInteractionDigest, ...]
    input_hashes: tuple[str, ...]
    output_proposal_hashes: tuple[str, ...] = ()
    normalized_transcript_hash: str = Field(pattern=SHA256_PATTERN)
    provider_transcript_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    provider_transcript_retention_reason: str | None = Field(default=None, max_length=500)
    attempts: tuple[HarnessAttemptRecord, ...]
    aggregate_usage: AgentUsage
    run_status: RunStatus
    failure_reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    limitations: tuple[str, ...] = ()
    started_at: datetime
    completed_at: datetime

    @property
    def usage(self) -> AgentUsage:
        return self.aggregate_usage

    @field_validator("instruction_hashes", "input_hashes", "output_proposal_hashes")
    @classmethod
    def manifest_hashes_are_sorted_v3(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique_hashes(value)

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted_v3(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @field_validator("started_at", "completed_at")
    @classmethod
    def manifest_timestamps_are_aware_v3(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AgentRun timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def manifest_outcome_is_consistent_v3(self) -> Self:
        if self.started_at > self.completed_at:
            raise ValueError("AgentRun timestamps are reversed")
        if not self.attempts or [item.attempt_index for item in self.attempts] != list(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("harness attempts must be nonempty and contiguous")
        if any(
            item.terminal_error_kind is None or not item.error_retryable
            for item in self.attempts[:-1]
        ):
            raise ValueError("only retryable failed attempts may precede the terminal attempt")
        proposals = tuple(
            item.produced_proposal_hash
            for item in self.attempts
            if item.produced_proposal_hash is not None
        )
        if len(proposals) > 1 or proposals != self.output_proposal_hashes:
            raise ValueError("manifest proposal hashes do not match harness attempts")
        if self.run_status is RunStatus.SUCCEEDED:
            if self.failure_reason_code is not None or len(proposals) != 1:
                raise ValueError("successful Agent run requires one proposal and no failure")
            if (
                self.sdk_version is None
                or self.runtime_package_version is None
                or self.runtime_version is None
                or self.runtime_binary_hash is None
            ):
                raise ValueError("successful Agent run requires exact SDK and runtime identity")
            if self.attempts[-1].produced_proposal_hash is None:
                raise ValueError("only the final harness attempt may produce a proposal")
        elif self.failure_reason_code is None or proposals:
            raise ValueError("failed Agent run requires a reason and no proposal")
        elif self.attempts[-1].terminal_error_kind is None:
            raise ValueError("failed Agent run requires a terminal attempt error")
        expected_usage = AgentUsage(
            input_tokens=sum(item.usage.input_tokens for item in self.attempts),
            output_tokens=sum(item.usage.output_tokens for item in self.attempts),
            cached_input_tokens=sum(item.usage.cached_input_tokens for item in self.attempts),
            tool_calls=sum(item.usage.tool_calls for item in self.attempts),
            retry_count=max(0, len(self.attempts) - 1),
        )
        if self.aggregate_usage != expected_usage:
            raise ValueError("aggregate usage does not match harness attempts")
        if self.aggregate_usage.tool_calls != len(self.interactions):
            raise ValueError("usage tool-call count does not match interactions")
        if not self.instruction_hashes or not self.input_hashes:
            raise ValueError("Agent run must bind instructions and inputs")
        if "MODEL_IDENTIFIER_NOT_IMMUTABLE" not in self.limitations:
            raise ValueError("mutable model identifier limitation must be explicit")
        unattested = self.attested_policy_hash is None
        limitation_present = "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED" in self.limitations
        if unattested != limitation_present:
            raise ValueError("policy attestation and limitation disagree")
        if self.attested_policy_hash is not None and self.resolved_runtime_config_hash is None:
            raise ValueError("policy attestation requires resolved runtime configuration")
        if (self.provider_transcript_hash is None) == (
            self.provider_transcript_retention_reason is None
        ):
            raise ValueError("provider transcript hash or non-retention reason is required")
        return self
