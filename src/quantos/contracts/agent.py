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
