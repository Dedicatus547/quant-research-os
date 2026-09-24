"""Harness-neutral contracts for the bounded P14d autonomous control plane."""

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from typing import Literal, Self, cast

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.agent import (
    AgentRole,
    AgentRunManifest,
    AgentRunSpec,
    CampaignSegment,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ResearchBudgetSpec, TrialOutcome
from quantos.contracts.enumeration import ResearchCandidateParameter, ResearchCandidateSpec
from quantos.contracts.ledger import ResearchContextAgentBinding, ResearchContextPack
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ReasonCode


class AutonomousLoopState(StrEnum):
    FAILED = "FAILED"
    READY = "READY"
    READY_FOR_SEALED_CONFIRMATION = "READY_FOR_SEALED_CONFIRMATION"
    RUNNING = "RUNNING"
    SELECTION_COMPLETE = "SELECTION_COMPLETE"
    SELECTION_READY = "SELECTION_READY"
    STOPPED = "STOPPED"


P14DQ_LIMITATIONS = (
    "DQ_EXACT_SNAPSHOT_VIEW_LINEAGE_ONLY",
    "DQ_LIVE_AGENT_RUNTIME_NOT_QUALIFIED",
    "DQ_NO_ALPHA_OR_PROFITABILITY_CLAIM",
    "DQ_NO_OOS_ACCESSED",
    "DQ_NO_UNRESTRICTED_AUTONOMOUS_RESEARCH",
    "DQ_SCRIPTED_REPLAY_AGENT_ONLY",
    "DQ_SEALED_CONFIRMATION_NOT_EXECUTED",
    "FR_03_NO_GO",
    "SINGLE_SOURCE_NON_VINTAGE",
)

_P14D_DEFAULT_LIMITATIONS = (
    "FR03_NO_GO_LIVE_AGENT_RUNTIME_NOT_USED",
    "P14D_A_OFFLINE_ORCHESTRATION_EVIDENCE_ONLY",
    "P14D_B_DOUBLE_ROOT_QUALIFICATION_PENDING",
    "REAL_MARKET_CONCLUSION_NOT_ESTABLISHED",
)


class AutonomousSelectionFinalizationProfile(CanonicalContract):
    """Frozen selected-report handoff policy for the autonomous campaign runner."""

    schema_version: Literal["autonomous-selection-finalization-profile/v1"] = (
        "autonomous-selection-finalization-profile/v1"
    )
    profile_id: Literal["p14d-default/v1", "p14dq-report-only/v1"]
    selected_action: Literal["FREEZE_SELECTION", "CLOSE_REPORT_ONLY"]
    selected_state: Literal[
        AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
        AutonomousLoopState.SELECTION_COMPLETE,
    ]
    no_selection_state: Literal[AutonomousLoopState.SELECTION_COMPLETE] = (
        AutonomousLoopState.SELECTION_COMPLETE
    )
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def profile_is_frozen(self) -> Self:
        expected = {
            "p14d-default/v1": (
                "FREEZE_SELECTION",
                AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
                _P14D_DEFAULT_LIMITATIONS,
            ),
            "p14dq-report-only/v1": (
                "CLOSE_REPORT_ONLY",
                AutonomousLoopState.SELECTION_COMPLETE,
                P14DQ_LIMITATIONS,
            ),
        }[self.profile_id]
        if (self.selected_action, self.selected_state, self.limitations) != expected:
            raise ValueError("autonomous selection finalization profile is not frozen")
        if self.no_selection_state is not AutonomousLoopState.SELECTION_COMPLETE:
            raise ValueError("autonomous no-selection finalization must close the campaign")
        return self


AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE = AutonomousSelectionFinalizationProfile(
    profile_id="p14d-default/v1",
    selected_action="FREEZE_SELECTION",
    selected_state=AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
    limitations=_P14D_DEFAULT_LIMITATIONS,
)

P14DQ_REPORT_ONLY_FINALIZATION_PROFILE = AutonomousSelectionFinalizationProfile(
    profile_id="p14dq-report-only/v1",
    selected_action="CLOSE_REPORT_ONLY",
    selected_state=AutonomousLoopState.SELECTION_COMPLETE,
    limitations=P14DQ_LIMITATIONS,
)


class AutonomousStoppingReason(StrEnum):
    ALL_CANDIDATES_TERMINAL = "ALL_CANDIDATES_TERMINAL"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY = "MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY"
    NO_REMAINING_ELIGIBLE_CANDIDATES = "NO_REMAINING_ELIGIBLE_CANDIDATES"


class AutonomousCampaignPolicy(CanonicalContract):
    """Frozen per-campaign context, segment, and manual-stop policy."""

    schema_version: Literal["autonomous-campaign-policy/v1"] = "autonomous-campaign-policy/v1"
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    context_query: str = Field(min_length=1, max_length=4096)
    readable_campaign_hashes: tuple[str, ...]
    trial_segment: Literal[CampaignSegment.DEVELOPMENT, CampaignSegment.VALIDATION]
    allow_agent_requested_manual_close: bool = False
    max_agent_request_bytes: PositiveInt = 262_144

    @field_validator("readable_campaign_hashes")
    @classmethod
    def readable_campaigns_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("readable campaign hashes must be sorted unique SHA-256 values")
        return value


class AutonomousAgentRunPolicy(CanonicalContract):
    """Agent provenance bindings supplied by the caller and echoed into each AgentRun."""

    schema_version: Literal["autonomous-agent-run-policy/v1"] = "autonomous-agent-run-policy/v1"
    capability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    requested_model_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    skill_hash: str = Field(pattern=SHA256_PATTERN)
    sandbox_policy_hash: str = Field(pattern=SHA256_PATTERN)
    permission_policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    harness_identifier: str = Field(min_length=1, max_length=500)
    provider_model_identifier: str = Field(min_length=1, max_length=500)
    model_snapshot_immutable: bool

    @field_validator("instruction_hashes")
    @classmethod
    def instructions_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("instruction hashes must be nonempty, sorted, and unique")
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("instruction hash is invalid")
        return value


class AutonomousBudgetView(CanonicalContract):
    """Read-only budget projection exposed to one Agent invocation."""

    schema_version: Literal["autonomous-budget-view/v1"] = "autonomous-budget-view/v1"
    max_trials: PositiveInt
    used_trials: NonNegativeInt
    remaining_trials: NonNegativeInt
    max_agent_runs: PositiveInt
    used_agent_runs: NonNegativeInt
    remaining_agent_runs: NonNegativeInt
    max_distinct_candidates: PositiveInt
    used_distinct_candidates: NonNegativeInt
    remaining_distinct_candidates: NonNegativeInt
    max_executions: PositiveInt
    used_executions: NonNegativeInt
    remaining_executions: NonNegativeInt
    max_validation_rounds: PositiveInt
    used_validation_rounds: NonNegativeInt
    remaining_validation_rounds: NonNegativeInt
    max_compute_seconds: PositiveInt
    used_compute_seconds: NonNegativeInt
    remaining_compute_seconds: NonNegativeInt

    @model_validator(mode="after")
    def remaining_values_reconcile(self) -> Self:
        pairs = (
            (self.max_trials, self.used_trials, self.remaining_trials),
            (self.max_agent_runs, self.used_agent_runs, self.remaining_agent_runs),
            (
                self.max_distinct_candidates,
                self.used_distinct_candidates,
                self.remaining_distinct_candidates,
            ),
            (self.max_executions, self.used_executions, self.remaining_executions),
            (
                self.max_validation_rounds,
                self.used_validation_rounds,
                self.remaining_validation_rounds,
            ),
            (self.max_compute_seconds, self.used_compute_seconds, self.remaining_compute_seconds),
        )
        if any(maximum - used != remaining for maximum, used, remaining in pairs):
            raise ValueError("remaining budget values do not reconcile")
        return self

    @classmethod
    def from_usage(
        cls,
        budget: ResearchBudgetSpec,
        *,
        trials: int,
        agent_runs: int,
        distinct_candidates: int,
        executions: int,
        validation_rounds: int,
        compute_seconds: int,
    ) -> AutonomousBudgetView:
        values = (
            (budget.max_trials, trials),
            (budget.max_agent_runs, agent_runs),
            (budget.max_distinct_candidates, distinct_candidates),
            (budget.max_executions, executions),
            (budget.max_validation_rounds, validation_rounds),
            (budget.max_compute_seconds, compute_seconds),
        )
        remaining = tuple(max(0, maximum - used) for maximum, used in values)
        return cls(
            max_trials=budget.max_trials,
            used_trials=trials,
            remaining_trials=remaining[0],
            max_agent_runs=budget.max_agent_runs,
            used_agent_runs=agent_runs,
            remaining_agent_runs=remaining[1],
            max_distinct_candidates=budget.max_distinct_candidates,
            used_distinct_candidates=distinct_candidates,
            remaining_distinct_candidates=remaining[2],
            max_executions=budget.max_executions,
            used_executions=executions,
            remaining_executions=remaining[3],
            max_validation_rounds=budget.max_validation_rounds,
            used_validation_rounds=validation_rounds,
            remaining_validation_rounds=remaining[4],
            max_compute_seconds=budget.max_compute_seconds,
            used_compute_seconds=compute_seconds,
            remaining_compute_seconds=remaining[5],
        )


class AutonomousAgentRequest(CanonicalContract):
    """Bounded Agent input; no paths, secrets, or authority controls are representable."""

    schema_version: Literal["autonomous-agent-request/v1"] = "autonomous-agent-request/v1"
    campaign_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    relevant_policy_hashes: tuple[str, ...]
    run_ordinal: PositiveInt
    allowed_proposal_schema_json: str = Field(min_length=2, max_length=65_536)
    proposal_schema_hash: str = Field(pattern=SHA256_PATTERN)
    budget: AutonomousBudgetView
    context_pack: ResearchContextPack
    context_binding: ResearchContextAgentBinding
    candidate_options: tuple[ResearchCandidateSpec, ...]
    agent_run_spec: AgentRunSpec

    @field_validator("relevant_policy_hashes")
    @classmethod
    def policies_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("relevant policy hashes must be nonempty, sorted, and unique")
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("relevant policy hash is invalid")
        return value

    @field_validator("candidate_options")
    @classmethod
    def candidate_options_are_ordered(
        cls, value: tuple[ResearchCandidateSpec, ...]
    ) -> tuple[ResearchCandidateSpec, ...]:
        hashes = [item.content_hash for item in value]
        if hashes != sorted(set(hashes)):
            raise ValueError("candidate options must be hash ordered and unique")
        return value

    @model_validator(mode="after")
    def all_bindings_agree(self) -> Self:
        try:
            proposal_schema: object = json.loads(self.allowed_proposal_schema_json)
            if not isinstance(proposal_schema, dict):
                raise ValueError("allowed proposal schema must be a JSON object")
            schema_bytes = canonical_json_bytes(cast(dict[str, object], proposal_schema))
        except (TypeError, ValueError) as error:
            raise ValueError("allowed proposal schema is not canonical JSON") from error
        expected_binding = ResearchContextAgentBinding(
            campaign_hash=self.context_pack.campaign_hash,
            context_pack_hash=self.context_pack.content_hash,
            ledger_snapshot_hash=self.context_pack.ledger_snapshot_hash,
            search_policy_hash=self.context_pack.search_policy_hash,
            access_scope_hash=self.context_pack.access_scope_hash,
            context_budget_policy_hash=self.context_pack.context_budget_policy_hash,
            search_request_hash=self.context_pack.search_request_hash,
            search_result_hash=self.context_pack.search_result_hash,
        )
        if (
            self.context_pack.campaign_hash != self.campaign_hash
            or self.context_pack.ledger_snapshot_hash != self.context_binding.ledger_snapshot_hash
            or self.context_pack.content_hash != self.context_binding.context_pack_hash
            or self.context_binding != expected_binding
            or self.agent_run_spec.campaign_hash != self.campaign_hash
            or self.agent_run_spec.ledger_snapshot_hash != self.context_pack.ledger_snapshot_hash
            or self.agent_run_spec.role is not AgentRole.RESEARCHER
            or schema_bytes.decode("utf-8") != self.allowed_proposal_schema_json
            or sha256_bytes(schema_bytes) != self.proposal_schema_hash
            or not set(self.relevant_policy_hashes).issubset(
                self.agent_run_spec.input_artifact_hashes
            )
        ):
            raise ValueError("autonomous Agent request bindings disagree")
        if not self.candidate_options:
            raise ValueError("Agent request requires at least one frozen candidate option")
        if any(item.family_hash != self.family_hash for item in self.candidate_options):
            raise ValueError("Agent request candidate option escapes the frozen family")
        return self


class AutonomousCandidateProposal(CanonicalContract):
    """Proposal-only candidate reference with no execution or verdict fields."""

    schema_version: Literal["autonomous-candidate-proposal/v1"] = "autonomous-candidate-proposal/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    parameters: tuple[ResearchCandidateParameter, ...]
    expression: SafeQlibExpressionSpec
    exact_expression_hash: str = Field(pattern=SHA256_PATTERN)
    structural_expression_hash: str = Field(pattern=SHA256_PATTERN)
    rationale: str = Field(min_length=1, max_length=10_000)
    request_stop: bool = False

    @field_validator("parameters")
    @classmethod
    def parameters_are_ordered(
        cls, value: tuple[ResearchCandidateParameter, ...]
    ) -> tuple[ResearchCandidateParameter, ...]:
        names = [item.name for item in value]
        if not names or names != sorted(set(names)):
            raise ValueError("candidate proposal parameters must be sorted and unique")
        return value


class AutonomousAgentResponse(CanonicalContract):
    """Immutable AgentRun manifest plus exact UTF-8 proposal bytes."""

    schema_version: Literal["autonomous-agent-response/v1"] = "autonomous-agent-response/v1"
    invocation_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_spec_hash: str = Field(pattern=SHA256_PATTERN)
    manifest: AgentRunManifest
    proposal_bytes: str = Field(min_length=1, max_length=262_144)
    proposal_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def proposal_hash_and_run_binding_match(self) -> Self:
        encoded = self.proposal_bytes.encode("utf-8")
        if sha256_bytes(encoded) != self.proposal_hash:
            raise ValueError("proposal bytes do not match proposal_hash")
        if (
            self.manifest.run_spec_hash != self.agent_run_spec_hash
            or self.manifest.output_proposal_hashes != (self.proposal_hash,)
            or self.manifest.run_status.value != "SUCCEEDED"
        ):
            raise ValueError("AgentRun manifest does not bind one successful proposal")
        return self


class AutonomousAgentExchangeArtifact(CanonicalContract):
    """Replay unit binding one exact request to one exact AgentRun response."""

    schema_version: Literal["autonomous-agent-exchange/v1"] = "autonomous-agent-exchange/v1"
    request: AutonomousAgentRequest
    response: AutonomousAgentResponse

    @model_validator(mode="after")
    def exchange_is_bound(self) -> Self:
        if (
            self.response.invocation_hash != self.request.content_hash
            or self.response.agent_run_spec_hash != self.request.agent_run_spec.content_hash
        ):
            raise ValueError("Agent exchange response does not bind its immutable request")
        return self


class AutonomousExecutionBindings(CanonicalContract):
    """Frozen hashes and dataset identity shared by orchestration and its execution adapter."""

    schema_version: Literal["autonomous-execution-bindings/v1"] = "autonomous-execution-bindings/v1"
    dataset_id: str = Field(min_length=1, max_length=500)
    authoring_hash: str = Field(pattern=SHA256_PATTERN)
    execution_policy_hash: str = Field(pattern=SHA256_PATTERN)
    pit_policy_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1, max_length=100)


def autonomous_execution_identity(
    *,
    campaign_hash: str,
    family_hash: str,
    budget_hash: str,
    candidate_manifest_hash: str,
    candidate: ResearchCandidateSpec,
    snapshot_hash: str,
    qlib_view_hash: str,
    segment: CampaignSegment,
    segment_start: date,
    segment_end: date,
    trial_ordinal: int,
    bindings: AutonomousExecutionBindings,
) -> str:
    """Derive the stable identity for one frozen candidate execution."""

    return sha256_bytes(
        canonical_json_bytes(
            {
                "backtest_policy_hash": bindings.backtest_policy_hash,
                "authoring_hash": bindings.authoring_hash,
                "budget_hash": budget_hash,
                "campaign_hash": campaign_hash,
                "candidate_exact_expression_hash": candidate.exact_expression_hash,
                "candidate_hash": candidate.content_hash,
                "candidate_manifest_hash": candidate_manifest_hash,
                "candidate_structural_expression_hash": candidate.structural_expression_hash,
                "code_commit_hash": bindings.code_commit_hash,
                "cost_policy_hash": bindings.cost_policy_hash,
                "dataset_id": bindings.dataset_id,
                "execution_policy_hash": bindings.execution_policy_hash,
                "family_hash": family_hash,
                "lockfile_hash": bindings.lockfile_hash,
                "pit_policy_hash": bindings.pit_policy_hash,
                "qlib_version": bindings.qlib_version,
                "qlib_view_hash": qlib_view_hash,
                "research_policy_hash": bindings.research_policy_hash,
                "segment": segment,
                "segment_end": segment_end,
                "segment_start": segment_start,
                "snapshot_hash": snapshot_hash,
                "trial_ordinal": trial_ordinal,
                "validation_policy_hash": bindings.validation_policy_hash,
            }
        )
    )


class AutonomousExecutionRequest(CanonicalContract):
    """Frozen candidate request passed only to a deterministic research-service adapter."""

    schema_version: Literal["autonomous-execution-request/v2"] = "autonomous-execution-request/v2"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    trial_ordinal: PositiveInt
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    candidate: ResearchCandidateSpec
    candidate_exact_expression_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_structural_expression_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_id: str = Field(min_length=1, max_length=500)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    segment: Literal[CampaignSegment.DEVELOPMENT, CampaignSegment.VALIDATION]
    segment_start: date
    segment_end: date
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    execution_policy_hash: str = Field(pattern=SHA256_PATTERN)
    pit_policy_hash: str = Field(pattern=SHA256_PATTERN)
    authoring_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1, max_length=100)
    remaining_executions: NonNegativeInt
    remaining_validation_rounds: NonNegativeInt
    remaining_compute_seconds: NonNegativeInt

    @model_validator(mode="after")
    def execution_identity_and_candidate_bindings_match(self) -> Self:
        if (
            self.idempotency_key != self.execution_identity
            or self.candidate_exact_expression_hash != self.candidate.exact_expression_hash
            or self.candidate_structural_expression_hash
            != self.candidate.structural_expression_hash
            or self.segment_start > self.segment_end
        ):
            raise ValueError("autonomous execution identity or frozen bindings disagree")
        return self


class AutonomousExecutionFailureEvidence(CanonicalContract):
    """Typed deterministic evidence for an expected PIT or execution-domain failure."""

    schema_version: Literal["autonomous-execution-failure/v1"] = "autonomous-execution-failure/v1"
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    reason_code: ReasonCode
    failure_kind: Literal["PIT_REJECTED", "EXECUTION_FAILED"]


class AutonomousExecutionResult(CanonicalContract):
    """Typed output from existing PIT/Qlib/Validation services, never from an Agent."""

    schema_version: Literal["autonomous-execution-result/v2"] = "autonomous-execution-result/v2"
    request_hash: str = Field(pattern=SHA256_PATTERN)
    outcome: Literal[
        TrialOutcome.EXECUTION_FAILED,
        TrialOutcome.HARD_REJECT,
        TrialOutcome.PASS,
        TrialOutcome.PIT_REJECT,
        TrialOutcome.SOFT_REJECT,
    ]
    execution_requested: bool
    compute_seconds: NonNegativeInt
    evidence_hashes: tuple[str, ...] = ()
    execution_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    research_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    failure_reason_code: ReasonCode | None = None

    @field_validator("evidence_hashes")
    @classmethod
    def evidence_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("execution evidence hashes must be sorted and unique")
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("execution evidence hash is invalid")
        return value

    @model_validator(mode="after")
    def execution_outcome_matches_requested_flag(self) -> Self:
        if self.execution_requested != (self.outcome is not TrialOutcome.PIT_REJECT):
            raise ValueError("PIT rejection and execution accounting disagree")
        if self.outcome is TrialOutcome.PASS and not self.evidence_hashes:
            raise ValueError("passing deterministic execution requires immutable evidence")
        if self.execution_artifact_hash is not None and (
            self.execution_artifact_hash not in self.evidence_hashes
        ):
            raise ValueError("execution artifact hash must be included in evidence hashes")
        if self.research_result_hash is not None and self.research_result_hash not in (
            self.evidence_hashes
        ):
            raise ValueError("ResearchResult hash must be included in evidence hashes")
        if self.validation_report_hash is not None and self.validation_report_hash not in (
            self.evidence_hashes
        ):
            raise ValueError("ValidationReport hash must be included in evidence hashes")
        return self


class AutonomousLoopReport(CanonicalContract):
    """Derived orchestration evidence with no independent selection/sealed authority."""

    schema_version: Literal["autonomous-loop-report/v1"] = "autonomous-loop-report/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_policy_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_policy_hash: str = Field(pattern=SHA256_PATTERN)
    initial_ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    final_ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    agent_request_hashes: tuple[str, ...]
    agent_run_hashes: tuple[str, ...]
    agent_manifest_hashes: tuple[str, ...]
    context_pack_hashes: tuple[str, ...]
    proposal_hashes: tuple[str, ...]
    trial_event_hashes: tuple[str, ...]
    campaign_event_hashes: tuple[str, ...]
    final_campaign_event_hash: str = Field(pattern=SHA256_PATTERN)
    trial_count: NonNegativeInt
    agent_run_count: NonNegativeInt
    stopping_reason: AutonomousStoppingReason
    budget: AutonomousBudgetView
    selection_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    selection_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    state: AutonomousLoopState
    sealed_confirmation_authority: Literal[False] = False
    limitations: tuple[str, ...]

    @field_validator(
        "agent_request_hashes",
        "agent_run_hashes",
        "agent_manifest_hashes",
        "context_pack_hashes",
        "proposal_hashes",
        "trial_event_hashes",
        "campaign_event_hashes",
    )
    @classmethod
    def hash_lists_are_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("orchestration hash lists must contain SHA-256 values")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("orchestration limitations must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def counts_and_authority_reconcile(self) -> Self:
        if (
            self.trial_count != len(self.trial_event_hashes)
            or self.agent_run_count != len(self.agent_run_hashes)
            or len(self.agent_request_hashes) != self.agent_run_count
            or len(self.agent_manifest_hashes) != self.agent_run_count
            or len(self.context_pack_hashes) != self.agent_run_count
            or len(self.proposal_hashes) != self.agent_run_count
            or len(set(self.agent_request_hashes)) != self.agent_run_count
            or len(set(self.agent_run_hashes)) != self.agent_run_count
            or len(set(self.agent_manifest_hashes)) != self.agent_run_count
            or len(set(self.context_pack_hashes)) != self.agent_run_count
            or len(set(self.trial_event_hashes)) != self.trial_count
            or not self.campaign_event_hashes
            or self.final_campaign_event_hash != self.campaign_event_hashes[-1]
        ):
            raise ValueError("orchestration report counts do not reconcile with histories")
        if self.state is AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION and (
            self.selection_report_hash is None or self.selection_event_hash is None
        ):
            raise ValueError("sealed-confirmation readiness requires frozen P14c selection")
        if self.selection_report_hash is None and self.selection_event_hash is not None:
            raise ValueError("selection event cannot exist without a selection report")
        return self


__all__ = [
    "AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE",
    "P14DQ_LIMITATIONS",
    "P14DQ_REPORT_ONLY_FINALIZATION_PROFILE",
    "AutonomousAgentExchangeArtifact",
    "AutonomousAgentRequest",
    "AutonomousAgentResponse",
    "AutonomousAgentRunPolicy",
    "AutonomousBudgetView",
    "AutonomousCampaignPolicy",
    "AutonomousCandidateProposal",
    "AutonomousExecutionBindings",
    "AutonomousExecutionFailureEvidence",
    "AutonomousExecutionRequest",
    "AutonomousExecutionResult",
    "AutonomousLoopReport",
    "AutonomousLoopState",
    "AutonomousSelectionFinalizationProfile",
    "AutonomousStoppingReason",
]
