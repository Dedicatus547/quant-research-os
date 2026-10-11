"""Bounded pre-campaign generation and retrospective comparison, independent of runtimes."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, NonNegativeInt, PositiveInt, model_validator

from quantos.contracts.autonomous import AutonomousExecutionBindings
from quantos.contracts.base import CanonicalContract
from quantos.contracts.campaign import ResearchFamilySpec
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResearchSegment,
    ValidationPolicy,
)


class DiscoveryDesign(CanonicalContract):
    schema_version: Literal["discovery-design/v1"] = "discovery-design/v1"
    profile_id: Literal["singleton-full-chain/v1"] = "singleton-full-chain/v1"
    research_question: str = Field(min_length=1, max_length=4096)
    primary_metric: Literal["Rank IC"] = "Rank IC"
    direction: Literal["maximize"] = "maximize"
    interpretation: Literal["RETROSPECTIVE_EXPLORATORY"] = "RETROSPECTIVE_EXPLORATORY"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hashes: tuple[str, ...]
    context_hashes: tuple[str, ...]
    exposure_history: tuple[str, ...]
    authoring: ExperimentAuthoringSpec
    research_policy: ResearchPolicy
    sealed_confirmation: ResearchSegment
    validation_policy: ValidationPolicy
    cost_policy: CostPolicy
    backtest_policy: BacktestPolicy
    bindings: AutonomousExecutionBindings
    allowed_operators: tuple[SafeQlibOperator, ...]
    candidate_grammar: Literal["field-window-optional-ratio-abs/v1"] = (
        "field-window-optional-ratio-abs/v1"
    )
    allowed_windows: tuple[PositiveInt, ...] = (5, 10, 20)
    max_nodes: PositiveInt = 4
    evaluation_opportunities_per_method: PositiveInt = 5
    max_compute_units: PositiveInt
    max_execution_resumes_per_subtask: Literal[1] = 1
    max_output_bytes_per_attempt: PositiveInt = Field(default=65_536, le=65_536)

    @model_validator(mode="after")
    def frozen_inputs_agree(self) -> Self:
        bindings = self.bindings
        if (
            bindings.authoring_hash != self.authoring.content_hash
            or bindings.research_policy_hash != self.research_policy.content_hash
            or bindings.validation_policy_hash != self.validation_policy.content_hash
            or bindings.cost_policy_hash != self.cost_policy.content_hash
            or bindings.backtest_policy_hash != self.backtest_policy.content_hash
            or self.authoring.evaluation_start != self.research_policy.test.start
            or self.authoring.evaluation_end != self.research_policy.test.end
            or self.sealed_confirmation.start <= self.research_policy.test.end
        ):
            raise ValueError("discovery inputs and execution bindings disagree")
        for hashes in (self.evidence_hashes, self.context_hashes):
            if tuple(sorted(set(hashes))) != hashes or any(
                len(item) != 64 or any(c not in "0123456789abcdef" for c in item) for item in hashes
            ):
                raise ValueError("source hashes must be sorted unique SHA256 identities")
        if not self.evidence_hashes or not self.exposure_history:
            raise ValueError("evidence and actual exposure history must be declared")
        if self.allowed_windows != tuple(sorted(set(self.allowed_windows))):
            raise ValueError("windows must be sorted and unique")
        if not self.allowed_operators or self.allowed_operators != tuple(
            sorted(set(self.allowed_operators), key=str)
        ):
            raise ValueError("operators must be explicitly sorted and unique")
        return self


class GenerationRequest(CanonicalContract):
    schema_version: Literal["discovery-generation-request/v1"] = "discovery-generation-request/v1"
    design_hash: str = Field(pattern=SHA256_PATTERN)
    method: Literal["TEMPLATE", "RANDOM", "LLM"]
    max_attempts: PositiveInt = 5
    seed: NonNegativeInt | None = None
    model_identifier: str | None = Field(default=None, min_length=1, max_length=200)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    configuration_hash: str = Field(pattern=SHA256_PATTERN)
    prompt: str = Field(min_length=1, max_length=16_384)
    input_hashes: tuple[str, ...]

    @model_validator(mode="after")
    def method_configuration_is_explicit(self) -> Self:
        if self.method == "LLM":
            if (
                self.model_identifier is None
                or self.reasoning_effort is None
                or self.seed is not None
            ):
                raise ValueError("LLM requests need explicit model/effort and no invented seed")
        elif (
            self.seed is None
            or self.model_identifier is not None
            or self.reasoning_effort is not None
        ):
            raise ValueError("baseline requests need a seed and no model configuration")
        if self.input_hashes != tuple(sorted(set(self.input_hashes))) or any(
            len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
            for item in self.input_hashes
        ):
            raise ValueError("generation sources must be sorted unique SHA256 identities")
        return self


class GenerationReservation(CanonicalContract):
    schema_version: Literal["discovery-generation-reservation/v1"] = (
        "discovery-generation-reservation/v1"
    )
    request_hash: str = Field(pattern=SHA256_PATTERN)
    ordinal: PositiveInt
    revision_of: str | None = Field(default=None, pattern=SHA256_PATTERN)


class GenerationResponse(CanonicalContract):
    model_config = ConfigDict(str_strip_whitespace=False)
    schema_version: Literal["discovery-generation-response/v1"] = "discovery-generation-response/v1"
    reservation: GenerationReservation
    # Whitespace is part of the captured response identity.
    text: str = Field(max_length=65_536)
    producer: Literal[
        "BASELINE", "SDK_CAPTURE", "HOSTED_HANDOFF", "OFFLINE_IMPORT", "CAPTURE_REJECTED"
    ]
    agent_run_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    wall_seconds: float | None = Field(default=None, ge=0)
    usage_input_units: NonNegativeInt | None = None
    usage_output_units: NonNegativeInt | None = None
    monetary_cost: float | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,99}$")


class DiscoverySubtask(CanonicalContract):
    schema_version: Literal["discovery-subtask/v1"] = "discovery-subtask/v1"
    design_hash: str = Field(pattern=SHA256_PATTERN)
    template: ResearchFactorTemplateSpec
    family: ResearchFamilySpec
    manifest: CandidateEnumerationManifest


class ProposalMapping(CanonicalContract):
    schema_version: Literal["discovery-proposal-mapping/v1"] = "discovery-proposal-mapping/v1"
    request_hash: str = Field(pattern=SHA256_PATTERN)
    reservation_hash: str = Field(pattern=SHA256_PATTERN)
    response_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    status: Literal["ADMITTED", "DUPLICATE", "PARSE_FAILED", "REJECTED", "UNFINISHED", "FAILED"]
    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    expression: SafeQlibExpressionSpec | None = None
    subtask_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class DiscoveryBatch(CanonicalContract):
    schema_version: Literal["discovery-batch/v1"] = "discovery-batch/v1"
    design: DiscoveryDesign
    requests: tuple[GenerationRequest, ...]
    reservations: tuple[GenerationReservation, ...]
    responses: tuple[GenerationResponse, ...]
    mappings: tuple[ProposalMapping, ...]
    subtasks: tuple[DiscoverySubtask, ...]

    @model_validator(mode="after")
    def batch_has_one_request_per_method(self) -> Self:
        if tuple(item.method for item in self.requests) != ("LLM", "RANDOM", "TEMPLATE"):
            raise ValueError("batch must bind exactly one request for each comparison method")
        if any(item.design_hash != self.design.content_hash for item in self.requests):
            raise ValueError("generation request binds a different design")
        if len({item.content_hash for item in self.subtasks}) != len(self.subtasks):
            raise ValueError("batch subtasks must be unique")
        return self
