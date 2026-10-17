"""Explicit adaptive successor. Legacy Discovery and SDK contracts are unchanged."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from quantos.contracts.agent import AgentRunSpecV3
from quantos.contracts.autonomous import AutonomousExecutionRequest
from quantos.contracts.base import CanonicalContract
from quantos.contracts.campaign import ResearchBudgetSpec, ResearchCampaignSpec
from quantos.contracts.discovery import (
    DiscoveryCompositionDesign,
    DiscoveryDesign,
    DiscoverySubtask,
)
from quantos.contracts.harness import HarnessExecutionRequest
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.refs import SHA256_PATTERN

Hash = Annotated[str, Field(pattern=SHA256_PATTERN)]


class AdaptiveLimits(CanonicalContract):
    schema_version: Literal["adaptive-limits/v1"] = "adaptive-limits/v1"
    sdk_decisions: PositiveInt = Field(le=2)
    new_candidates: PositiveInt = Field(le=2)
    scientific_executions: PositiveInt = Field(le=2)
    compute_units: PositiveInt
    wall_seconds: PositiveInt
    storage_growth_bytes: PositiveInt
    automatic_sdk_retries: Literal[0] = 0
    unknown_reissues: Literal[0] = 0
    scientific_restarts: Literal[0] = 0
    sealed_accesses: Literal[0] = 0


class AdaptiveSdkProfile(CanonicalContract):
    schema_version: Literal["adaptive-sdk-profile/v1"] = "adaptive-sdk-profile/v1"
    runtime_candidate_id: Literal["openai-codex-0.162.1-gpt61-fr03"] = (
        "openai-codex-0.162.1-gpt61-fr03"
    )
    sdk_version: Literal["0.162.1"] = "0.162.1"
    runtime_package_version: Literal["0.162.1"] = "0.162.1"
    runtime_binary_hash: Hash
    model: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
    reasoning_effort: Literal["medium"] = "medium"
    timeout_seconds: PositiveInt = 900
    max_input_tokens: PositiveInt = 50000
    max_output_tokens: PositiveInt = 4096
    max_transcript_bytes: Literal[262144] = 262144
    max_normalized_transcript_bytes: Literal[65536] = 65536
    max_raw_response_bytes: Literal[16384] = 16384


class AdaptiveResearchSpec(CanonicalContract):
    schema_version: Literal["bounded-adaptive-research/v1"] = "bounded-adaptive-research/v1"
    task_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,99}$")
    design: Annotated[
        DiscoveryDesign | DiscoveryCompositionDesign, Field(discriminator="schema_version")
    ]
    limits: AdaptiveLimits
    sdk: AdaptiveSdkProfile
    workspace: str
    snapshot_path: str
    qlib_view_path: str
    output_root: str
    sdk_cwd: str
    initial_structural_hashes: tuple[Hash, ...] = ()
    context: str = Field(min_length=1, max_length=8000)
    context_source_hashes: tuple[Hash, ...]
    egress: Literal["OPENAI_CODEX_PROJECTED_CONTEXT_AST_FEEDBACK_ONLY"] = (
        "OPENAI_CODEX_PROJECTED_CONTEXT_AST_FEEDBACK_ONLY"
    )
    interpretation: Literal["RETROSPECTIVE_ADAPTIVE_EXPLORATION_NO_SELECTION_CLAIM"] = (
        "RETROSPECTIVE_ADAPTIVE_EXPLORATION_NO_SELECTION_CLAIM"
    )

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.limits.new_candidates > self.limits.scientific_executions:
            raise ValueError("candidate limit exceeds execution limit")
        if not self.context_source_hashes:
            raise ValueError("context must bind explicit source originals")
        for hashes in (self.context_source_hashes, self.initial_structural_hashes):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError("hash inventories must be sorted and unique")
        return self


class AdaptiveDecision(CanonicalContract):
    schema_version: Literal["adaptive-decision/v1"] = "adaptive-decision/v1"
    action: Literal["PROPOSE", "STOP"]
    hypothesis: str = Field(min_length=1, max_length=2000)
    expression: SafeQlibExpressionSpec | None
    parent_proposal_hash: Hash | None
    feedback_hashes: tuple[Hash, ...]
    source_hashes: tuple[Hash, ...]
    rationale: str = Field(min_length=1, max_length=2000)
    expected_checks: tuple[Literal["PIT", "QLIB", "VALIDATION"], ...]

    @model_validator(mode="after")
    def branch(self) -> Self:
        if (self.action == "PROPOSE") != (self.expression is not None):
            raise ValueError("PROPOSE requires AST; STOP forbids AST")
        if self.action == "PROPOSE" and self.expected_checks != ("PIT", "QLIB", "VALIDATION"):
            raise ValueError("all existing scientific checks are mandatory")
        if self.action == "STOP" and self.expected_checks:
            raise ValueError("STOP has no execution checks")
        if self.feedback_hashes != tuple(sorted(set(self.feedback_hashes))):
            raise ValueError("feedback references must be sorted and unique")
        return self


class AdaptiveDecisionRequest(CanonicalContract):
    schema_version: Literal["adaptive-decision-request/v1"] = "adaptive-decision-request/v1"
    task_hash: Hash
    ordinal: PositiveInt
    previous_event_hash: Hash
    parent_proposal_hash: Hash | None
    feedback_hashes: tuple[Hash, ...]
    exposure_hash: Hash
    prompt: str = Field(max_length=100000)


class AdaptiveSdkReservation(CanonicalContract):
    schema_version: Literal["adaptive-sdk-reservation/v1"] = "adaptive-sdk-reservation/v1"
    request_hash: Hash
    task_hash: Hash
    execution_request: HarnessExecutionRequest
    run_spec: AgentRunSpecV3


class AdaptiveChild(CanonicalContract):
    schema_version: Literal["adaptive-child/v1"] = "adaptive-child/v1"
    task_hash: Hash
    decision_hash: Hash
    capture_hash: Hash
    legacy_agent_run_hash_meaning: Literal["ADAPTIVE_SDK_RESPONSE_HASH_NOT_AGENT_RUN"] = (
        "ADAPTIVE_SDK_RESPONSE_HASH_NOT_AGENT_RUN"
    )
    ordinal: PositiveInt
    quote_units: PositiveInt
    subtask: DiscoverySubtask
    campaign: ResearchCampaignSpec
    budget: ResearchBudgetSpec
    request: AutonomousExecutionRequest


class AdaptiveEvent(CanonicalContract):
    schema_version: Literal["adaptive-event/v1"] = "adaptive-event/v1"
    task_hash: Hash
    ordinal: PositiveInt
    previous_hash: Hash | None
    kind: Literal[
        "ACTIVATED",
        "DECISION_RESERVED",
        "DECISION_CAPTURED",
        "CHILD_RESERVED",
        "SCIENCE_STARTED",
        "SCIENCE_SETTLED",
        "STOPPED",
        "CANCELLED",
    ]
    reference_hash: Hash
    units: NonNegativeInt = 0
    occurred_at: datetime

    @model_validator(mode="after")
    def aware(self) -> Self:
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be aware")
        return self
