"""Bounded pre-campaign generation and retrospective comparison, independent of runtimes."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, NonNegativeInt, PositiveInt, TypeAdapter, model_validator

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


class _DiscoveryDesignInputs(CanonicalContract):
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


class DiscoveryDesign(_DiscoveryDesignInputs):
    schema_version: Literal["discovery-design/v1"] = "discovery-design/v1"
    profile_id: Literal["singleton-full-chain/v1"] = "singleton-full-chain/v1"
    candidate_grammar: Literal["field-window-optional-ratio-abs/v1"] = (
        "field-window-optional-ratio-abs/v1"
    )


class DiscoveryCompositionDesign(_DiscoveryDesignInputs):
    """Finite successor: legacy design bytes and interpretation stay unchanged."""

    schema_version: Literal["discovery-design/v3"] = "discovery-design/v3"
    profile_id: Literal["bounded-price-composition/v1"] = "bounded-price-composition/v1"
    candidate_grammar: Literal["price-return-volatility-trend/v1"] = (
        "price-return-volatility-trend/v1"
    )
    allowed_windows: tuple[PositiveInt, ...] = (1, 5, 10, 20, 60)
    max_nodes: PositiveInt = Field(default=8, le=8)
    max_depth: PositiveInt = Field(default=4, le=4)
    evaluation_opportunities_per_method: PositiveInt = Field(default=3, le=555)
    parameter_stability_rule: Literal["first-window-node/v1"] = "first-window-node/v1"
    baseline_sampling: Literal["structural-uniform-without-replacement/v1"] = (
        "structural-uniform-without-replacement/v1"
    )
    template_order: Literal["composition-component-round-robin/v1"] = (
        "composition-component-round-robin/v1"
    )

    @model_validator(mode="after")
    def composition_capabilities_are_bounded(self) -> Self:
        permitted = {
            SafeQlibOperator.FIELD,
            SafeQlibOperator.RETURN,
            SafeQlibOperator.ROLLING_MEAN,
            SafeQlibOperator.ROLLING_STD,
            SafeQlibOperator.DIVIDE,
            SafeQlibOperator.MULTIPLY,
        }
        if not set(self.allowed_operators).issubset(permitted):
            raise ValueError("composition profile permits only bounded price operators")
        if not {SafeQlibOperator.FIELD, SafeQlibOperator.RETURN}.issubset(self.allowed_operators):
            raise ValueError("composition profile requires field and return")
        if not self.allowed_windows or not set(self.allowed_windows).issubset({1, 5, 10, 20, 60}):
            raise ValueError("composition windows must use the finite profile set")
        if self.max_nodes < 2 or self.max_depth < 2:
            raise ValueError("composition profile must permit a return component")
        return self


DiscoveryDesignContract = DiscoveryCompositionDesign | DiscoveryDesign


class DiscoveryDesignReader:
    @staticmethod
    def model_validate(value: object) -> DiscoveryDesignContract:
        return TypeAdapter[DiscoveryDesignContract](DiscoveryDesignContract).validate_python(value)

    @staticmethod
    def model_validate_json(value: str | bytes) -> DiscoveryDesignContract:
        return TypeAdapter[DiscoveryDesignContract](DiscoveryDesignContract).validate_json(value)


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
    design: DiscoveryDesignContract
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


class SequentialGenerationPolicy(CanonicalContract):
    """Explicit successor policy; the v1 design and base requests remain unchanged."""

    schema_version: Literal["discovery-sequential-policy/v2"] = "discovery-sequential-policy/v2"
    profile: Literal["hm-discovery-sequential/v2"] = "hm-discovery-sequential/v2"
    design_hash: str = Field(pattern=SHA256_PATTERN)
    request_hashes: tuple[str, str, str]
    history_rule: Literal["same-method-static-prefix/v1"] = "same-method-static-prefix/v1"
    unfinished_rule: Literal["successor-reservation-seals-missing-response/v1"] = (
        "successor-reservation-seals-missing-response/v1"
    )
    template_rule: Literal["return-mean-std-rank-round-robin/v1"] = (
        "return-mean-std-rank-round-robin/v1"
    )
    random_rule: Literal["shared-space-without-replacement/v1"] = (
        "shared-space-without-replacement/v1"
    )
    random_seed: Literal[1729] = 1729
    max_attempts_per_method: PositiveInt = Field(default=5, le=5)

    @model_validator(mode="after")
    def identities_are_explicit(self) -> Self:
        if len(set(self.request_hashes)) != 3 or any(
            len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
            for item in self.request_hashes
        ):
            raise ValueError("policy requires three distinct SHA256 base request identities")
        return self


class CompositionGenerationPolicy(CanonicalContract):
    design_hash: str = Field(pattern=SHA256_PATTERN)
    request_hashes: tuple[str, str, str]
    history_rule: Literal["same-method-static-prefix/v1"] = "same-method-static-prefix/v1"
    unfinished_rule: Literal["successor-reservation-seals-missing-response/v1"] = (
        "successor-reservation-seals-missing-response/v1"
    )
    schema_version: Literal["discovery-sequential-policy/v3"] = "discovery-sequential-policy/v3"
    profile: Literal["composition-discovery-sequential/v1"] = "composition-discovery-sequential/v1"
    template_rule: Literal["composition-component-round-robin/v1"] = (
        "composition-component-round-robin/v1"
    )
    random_rule: Literal["structural-uniform-without-replacement/v1"] = (
        "structural-uniform-without-replacement/v1"
    )
    random_seed: NonNegativeInt = 1729
    max_attempts_per_method: PositiveInt = 3

    @model_validator(mode="after")
    def identities_are_explicit(self) -> Self:
        if len(set(self.request_hashes)) != 3 or any(
            len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
            for item in self.request_hashes
        ):
            raise ValueError("policy requires three distinct SHA256 request identities")
        return self


SequentialPolicyContract = CompositionGenerationPolicy | SequentialGenerationPolicy


class SequentialPolicyReader:
    @staticmethod
    def model_validate_json(value: str | bytes) -> SequentialPolicyContract:
        return TypeAdapter[SequentialPolicyContract](SequentialPolicyContract).validate_json(value)

    @staticmethod
    def model_validate(value: object) -> SequentialPolicyContract:
        return TypeAdapter[SequentialPolicyContract](SequentialPolicyContract).validate_python(
            value
        )


class SequentialHistoryEntry(CanonicalContract):
    schema_version: Literal["discovery-sequential-history-entry/v1"] = (
        "discovery-sequential-history-entry/v1"
    )
    reservation_hash: str = Field(pattern=SHA256_PATTERN)
    ordinal: PositiveInt
    response_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    status: Literal["ADMITTED", "DUPLICATE", "PARSE_FAILED", "REJECTED", "UNFINISHED", "FAILED"]
    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")
    expression: SafeQlibExpressionSpec | None = None
    structural_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)


class SequentialGenerationHistory(CanonicalContract):
    schema_version: Literal["discovery-sequential-history/v1"] = "discovery-sequential-history/v1"
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    method: Literal["TEMPLATE", "RANDOM", "LLM"]
    entries: tuple[SequentialHistoryEntry, ...]

    @model_validator(mode="after")
    def prefix_is_contiguous(self) -> Self:
        if tuple(item.ordinal for item in self.entries) != tuple(range(1, len(self.entries) + 1)):
            raise ValueError("history must contain the entire earlier method prefix")
        return self


class SequentialGenerationAttempt(CanonicalContract):
    schema_version: Literal["discovery-sequential-attempt/v2"] = "discovery-sequential-attempt/v2"
    reservation: GenerationReservation
    history: SequentialGenerationHistory

    @model_validator(mode="after")
    def prefix_binds_reservation(self) -> Self:
        if (
            self.reservation.request_hash != self.history.request_hash
            or self.reservation.ordinal != len(self.history.entries) + 1
        ):
            raise ValueError("attempt history differs from its reserved prefix")
        return self


class SequentialLaunchSource(CanonicalContract):
    """Management pointers only; they confer no access or assertion of a model call."""

    schema_version: Literal["discovery-sequential-launch-source/v1"] = (
        "discovery-sequential-launch-source/v1"
    )
    request_hash: str = Field(pattern=SHA256_PATTERN)
    reservation_hash: str = Field(pattern=SHA256_PATTERN)
    manager_root: str = Field(min_length=1, max_length=4096)
    evidence_root: str = Field(min_length=1, max_length=4096)
    job_root: str = Field(min_length=1, max_length=4096)
    authenticated_principal: str = Field(min_length=1, max_length=200)


class SequentialLaunchObservation(CanonicalContract):
    """Freeze only observed originals; a missing capture is unknown, never zero calls."""

    schema_version: Literal["discovery-sequential-launch-observation/v1"] = (
        "discovery-sequential-launch-observation/v1"
    )
    source_hash: str = Field(pattern=SHA256_PATTERN)
    reservation_hash: str = Field(pattern=SHA256_PATTERN)
    job_prelaunch_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    job_completion_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    launch_prelaunch_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    launch_completion_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    launcher_record_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    unobserved_semantics: Literal["UNKNOWN_AT_FREEZE"] = "UNKNOWN_AT_FREEZE"


class SequentialDiscoveryBatch(CanonicalContract):
    schema_version: Literal["discovery-sequential-batch/v2"] = "discovery-sequential-batch/v2"
    policy: SequentialPolicyContract
    batch: DiscoveryBatch
    attempts: tuple[SequentialGenerationAttempt, ...]
    launch_sources: tuple[SequentialLaunchSource, ...] = ()
    launch_observations: tuple[SequentialLaunchObservation, ...] = ()

    @model_validator(mode="after")
    def successor_bindings_agree(self) -> Self:
        if isinstance(self.batch.design, DiscoveryCompositionDesign) != isinstance(
            self.policy, CompositionGenerationPolicy
        ):
            raise ValueError("sequential design and policy profiles differ")
        if (
            self.policy.design_hash != self.batch.design.content_hash
            or self.policy.request_hashes
            != tuple(item.content_hash for item in self.batch.requests)
            or tuple(item.reservation for item in self.attempts) != self.batch.reservations
            or any(item.history.policy_hash != self.policy.content_hash for item in self.attempts)
            or len({item.reservation_hash for item in self.launch_sources})
            != len(self.launch_sources)
            or any(
                not any(
                    reservation.content_hash == source.reservation_hash
                    and reservation.request_hash == source.request_hash
                    for reservation in self.batch.reservations
                )
                for source in self.launch_sources
            )
            or tuple(item.source_hash for item in self.launch_observations)
            != tuple(item.content_hash for item in self.launch_sources)
            or tuple(item.reservation_hash for item in self.launch_observations)
            != tuple(item.reservation_hash for item in self.launch_sources)
        ):
            raise ValueError("sequential batch policy or attempt bindings disagree")
        return self
