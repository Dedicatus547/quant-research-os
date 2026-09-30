"""Versioned, runtime-independent host-mediated protocol contracts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Self, TypeVar, cast

from pydantic import (
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)

from quantos.contracts.autonomous import (
    AutonomousAgentRequest,
    AutonomousExecutionBindings,
    AutonomousExecutionRequest,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ResearchBudgetSpec, ResearchCampaignSpec
from quantos.contracts.refs import SHA256_PATTERN

Hash = Annotated[str, Field(pattern=SHA256_PATTERN)]
Identity = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}$")]
ContractT = TypeVar("ContractT", bound=CanonicalContract)
REQUEST_BYTE_CAP = 1_048_576
RESPONSE_BYTE_CAP = 262_144


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise ValueError("nonfinite JSON number")


def strict_json_object(data: bytes, *, max_bytes: int) -> dict[str, object]:
    """Bounded UTF-8 JSON parsing; error messages never include submitted values."""
    if len(data) > max_bytes:
        raise ValueError("JSON byte cap exceeded")
    try:
        value: object = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_nonfinite,
        )
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        encoded = canonical_json_bytes(cast(dict[str, object], value))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid bounded JSON object") from error
    if encoded != data:
        raise ValueError("JSON must use canonical bytes")
    return cast(dict[str, object], value)


def parse_hosted_contract(data: bytes, cls: type[ContractT], *, max_bytes: int) -> ContractT:
    value = strict_json_object(data, max_bytes=max_bytes)
    try:
        # CanonicalContract's before validator puts nested JSON into Python mode.
        # Decode canonical dates/arrays through existing contracts, then require
        # byte equality: scalar coercions, stripped strings and inserted defaults
        # cannot survive this comparison.
        contract = cls.model_validate(value)
        if contract.canonical_bytes() != data:
            raise ValueError("contract must use canonical bytes")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid hosted contract") from error
    return contract


class HostedContract(CanonicalContract):
    # Proposal and journal payload strings must retain every original UTF-8 byte.
    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        validate_default=True,
    )

    @field_validator("*", mode="after")
    @classmethod
    def aware_timestamps(cls, value: object) -> object:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("hosted timestamps must be timezone-aware")
        return value


class HostedBudgetPolicy(HostedContract):
    schema_version: Literal["hosted-budget-policy/v1"] = "hosted-budget-policy/v1"
    max_requests: PositiveInt
    max_unique_submissions: PositiveInt
    max_submissions_per_request: PositiveInt
    max_response_bytes: int = Field(gt=0, le=RESPONSE_BYTE_CAP)
    max_proposal_bytes: int = Field(gt=0, le=RESPONSE_BYTE_CAP)
    max_request_bytes: int = Field(gt=0, le=REQUEST_BYTE_CAP)
    request_ttl_seconds: PositiveInt
    reissue: Literal[False] = False


class HostedCampaignSpec(HostedContract):
    schema_version: Literal["hosted-campaign-spec/v1"] = "hosted-campaign-spec/v1"
    profile: Literal["hm-mvp/v1"] = "hm-mvp/v1"
    campaign: ResearchCampaignSpec
    research_budget: ResearchBudgetSpec
    hosted_budget: HostedBudgetPolicy
    candidate_manifest_hash: Hash
    factor_template_hash: Hash
    selection_plan_hash: Hash
    selection_finalization_profile_hash: Hash
    execution_bindings: AutonomousExecutionBindings
    search_policy_hash: Hash
    context_budget_policy_hash: Hash
    campaign_policy_hash: Hash
    agent_run_policy_hash: Hash
    requested_model_configuration_hash: Hash
    deployment_profile_hash: Hash
    contract_hash: Hash
    acceptance_hash: Hash
    started_at: datetime

    @model_validator(mode="after")
    def budget_binding(self) -> Self:
        if self.campaign.budget_hash != self.research_budget.content_hash:
            raise ValueError("hosted campaign research budget binding disagrees")
        if self.hosted_budget.max_requests > self.research_budget.max_agent_runs:
            raise ValueError("hosted request cap exceeds research agent allowance")
        return self

    @property
    def campaign_hash(self) -> str:
        return self.campaign.content_hash

    @property
    def frozen_input_hashes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(
                    (
                        self.campaign_hash,
                        self.campaign.family_hash,
                        self.campaign.budget_hash,
                        self.campaign.ledger_snapshot_hash,
                        self.campaign.snapshot_hash,
                        self.campaign.qlib_view_hash,
                        *self.campaign.evidence_hashes,
                        *self.campaign.feature_artifact_hashes,
                        self.candidate_manifest_hash,
                        self.factor_template_hash,
                        self.selection_plan_hash,
                        self.selection_finalization_profile_hash,
                        self.execution_bindings.content_hash,
                        self.search_policy_hash,
                        self.context_budget_policy_hash,
                        self.campaign_policy_hash,
                        self.agent_run_policy_hash,
                        self.requested_model_configuration_hash,
                        self.deployment_profile_hash,
                        self.contract_hash,
                        self.acceptance_hash,
                        self.hosted_budget.content_hash,
                    )
                )
            )
        )


class HostedRequestSubmissionCount(HostedContract):
    schema_version: Literal["hosted-request-submission-count/v1"] = (
        "hosted-request-submission-count/v1"
    )
    transport_ordinal: PositiveInt
    used_submissions: NonNegativeInt


class HostedBudgetJournalFact(HostedContract):
    schema_version: Literal["hosted-budget-journal-fact/v1"] = "hosted-budget-journal-fact/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    operation_id: Hash
    previous_hash: Hash | None
    used_requests: NonNegativeInt
    used_unique_submissions: NonNegativeInt
    request_submissions: tuple[HostedRequestSubmissionCount, ...]
    recorded_at: datetime

    @model_validator(mode="after")
    def counts_agree(self) -> Self:
        if (
            tuple(x.transport_ordinal for x in self.request_submissions)
            != tuple(range(1, self.used_requests + 1))
            or sum(x.used_submissions for x in self.request_submissions)
            != self.used_unique_submissions
        ):
            raise ValueError("hosted budget counters disagree")
        return self


class HostedAgentRequest(HostedContract):
    schema_version: Literal["hosted-agent-request/v1"] = "hosted-agent-request/v1"
    profile: Literal["hm-mvp/v1"] = "hm-mvp/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    transport_ordinal: PositiveInt
    business_request: AutonomousAgentRequest
    business_request_hash: Hash
    context_pack_hash: Hash
    candidate_manifest_hash: Hash
    input_hashes: tuple[Hash, ...]
    policy_hashes: tuple[Hash, ...]
    budget_reservation_hash: Hash
    proposal_schema_hash: Hash
    max_request_bytes: int = Field(gt=0, le=REQUEST_BYTE_CAP)
    max_response_bytes: int = Field(gt=0, le=RESPONSE_BYTE_CAP)
    max_proposal_bytes: int = Field(gt=0, le=RESPONSE_BYTE_CAP)
    attempt_identity: Hash
    projection_object_hashes: tuple[Hash, ...]
    issued_at: datetime
    expires_at: datetime

    @field_validator("input_hashes", "policy_hashes", "projection_object_hashes")
    @classmethod
    def sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("hosted hash lists must be sorted unique")
        return values

    @model_validator(mode="after")
    def bindings_agree(self) -> Self:
        business = self.business_request
        if (
            business.campaign_hash != self.campaign_hash
            or business.content_hash != self.business_request_hash
            or business.context_pack.content_hash != self.context_pack_hash
            or business.candidate_manifest_hash != self.candidate_manifest_hash
            or business.proposal_schema_hash != self.proposal_schema_hash
            or self.policy_hashes != business.relevant_policy_hashes
            or not set(business.agent_run_spec.input_artifact_hashes).issubset(self.input_hashes)
            or self.context_pack_hash not in self.projection_object_hashes
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("hosted request bindings disagree")
        return self


class HostReportedUsage(HostedContract):
    schema_version: Literal["hosted-reported-usage/v1"] = "hosted-reported-usage/v1"
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cost_microunits: NonNegativeInt | None = None
    unavailable_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def missing_usage_is_explicit(self) -> Self:
        if (
            any(x is None for x in (self.input_tokens, self.output_tokens, self.cost_microunits))
            and not self.unavailable_reason
        ):
            raise ValueError("missing hosted usage requires a reason")
        return self


class HostObservation(HostedContract):
    schema_version: Literal["hosted-observation/v1"] = "hosted-observation/v1"
    source: Literal["HOST_REPORTED"] = "HOST_REPORTED"
    requested_configuration_hash: Hash
    reported_model_identifier: str | None = Field(default=None, max_length=500)
    reported_reasoning_effort: str | None = Field(default=None, max_length=100)
    reported_permission_pass: bool | None = None
    reported_usage: HostReportedUsage
    transcript_hash: Hash | None = None
    immutable_model_snapshot: str | None = Field(default=None, max_length=500)
    external_evidence_hashes: tuple[Hash, ...] = Field(default=(), max_length=32)
    unavailable_reasons: tuple[str, ...] = Field(min_length=1, max_length=32)

    @field_validator("unavailable_reasons")
    @classmethod
    def reasons_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not x or len(x.encode("utf-8")) > 500 for x in value):
            raise ValueError("hosted unavailable reason exceeds bound")
        return value

    @model_validator(mode="after")
    def limitations_are_explicit(self) -> Self:
        # A self-report cannot attest any of these facts, even when it supplies values.
        required = {
            "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "HOST_INTERNAL_USAGE_UNAVAILABLE",
        }
        if self.transcript_hash is None:
            required.add("HOST_TRANSCRIPT_UNAVAILABLE")
        if not required.issubset(self.unavailable_reasons):
            raise ValueError("missing hosted observation limitations")
        return self


class HostedAgentResponse(HostedContract):
    schema_version: Literal["hosted-agent-response/v1"] = "hosted-agent-response/v1"
    request_hash: Hash
    campaign_hash: Hash
    transport_ordinal: PositiveInt
    context_pack_hash: Hash
    attempt_identity: Hash
    proposal_json: str = Field(min_length=1)
    proposal_hash: Hash
    host_observation: HostObservation

    @model_validator(mode="after")
    def proposal_bytes_agree(self) -> Self:
        try:
            encoded = self.proposal_json.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("proposal must be UTF-8") from error
        if len(encoded) > RESPONSE_BYTE_CAP or sha256_bytes(encoded) != self.proposal_hash:
            raise ValueError("hosted proposal bytes disagree")
        return self


class HostedAgentExchange(HostedContract):
    schema_version: Literal["hosted-agent-exchange/v1"] = "hosted-agent-exchange/v1"
    provenance_kind: Literal["HOSTED_EXCHANGE"] = "HOSTED_EXCHANGE"
    request_hash: Hash
    response_hash: Hash
    proposal_hash: Hash
    authenticated_principal: Identity
    host_observation_hash: Hash


class HostedSubmissionReceipt(HostedContract):
    schema_version: Literal["hosted-submission-receipt/v1"] = "hosted-submission-receipt/v1"
    campaign_hash: Hash
    request_hash: Hash | None
    submission_bytes_hash: Hash | None
    observed_prefix_hash: Hash | None = None
    observed_bytes: NonNegativeInt
    complete: bool
    attempt_identity: Hash | None
    outcome: Literal["ACCEPTED", "REJECTED", "CONFLICT", "EXHAUSTED"]
    reason: Identity
    accepted_exchange_hash: Hash | None = None
    budget_before_hash: Hash
    budget_after_hash: Hash
    recorded_at: datetime
    authenticated_principal: Identity

    @model_validator(mode="after")
    def digest_and_outcome_agree(self) -> Self:
        if (
            (self.complete and self.observed_prefix_hash is not None)
            or (not self.complete and self.submission_bytes_hash is not None)
            or (self.outcome == "ACCEPTED" and self.accepted_exchange_hash is None)
            or (self.outcome != "ACCEPTED" and self.accepted_exchange_hash is not None)
        ):
            raise ValueError("hosted receipt digest/outcome disagree")
        return self


class HostedRequestTerminalReceipt(HostedContract):
    schema_version: Literal["hosted-request-terminal-receipt/v1"] = (
        "hosted-request-terminal-receipt/v1"
    )
    request_hash: Hash
    campaign_hash: Hash
    outcome: Literal["CANCELLED", "EXPIRED", "CANCEL_REJECTED", "STEP_COMPLETED"]
    reason: Identity
    authenticated_principal: Identity
    recorded_at: datetime
    business_artifact_hashes: tuple[Hash, ...] = ()


class HostedCheckpoint(HostedContract):
    schema_version: Literal["hosted-checkpoint/v1"] = "hosted-checkpoint/v1"
    request_hash: Hash
    campaign_hash: Hash
    transport_ordinal: PositiveInt
    state: Literal["WAITING_FOR_AGENT"] = "WAITING_FOR_AGENT"
    recorded_at: datetime


class HostedPublication(HostedContract):
    schema_version: Literal["hosted-publication/v1"] = "hosted-publication/v1"
    artifact_hash: Hash
    canonical_json: str

    @model_validator(mode="after")
    def artifact_bytes_agree(self) -> Self:
        encoded = self.canonical_json.encode("utf-8")
        strict_json_object(encoded, max_bytes=4 * REQUEST_BYTE_CAP)
        if sha256_bytes(encoded) != self.artifact_hash:
            raise ValueError("hosted publication hash disagrees")
        return self


class HostedJournalEntry(HostedContract):
    schema_version: Literal["hosted-journal-entry/v1"] = "hosted-journal-entry/v1"
    campaign_hash: Hash
    sequence: PositiveInt
    previous_hash: Hash | None
    operation_id: Hash
    phase: Literal["INTENT", "COMPLETE"]
    operation_kind: Literal["REGISTER", "ISSUE", "SUBMIT", "TERMINATE", "BUSINESS"]
    recorded_at: datetime
    publications: tuple[HostedPublication, ...] = ()
    artifact_hashes: tuple[Hash, ...] = ()

    @model_validator(mode="after")
    def phase_fields_agree(self) -> Self:
        if self.phase == "INTENT" and (not self.publications or self.artifact_hashes):
            raise ValueError("hosted intent requires fixed publications")
        if self.phase == "COMPLETE" and (self.publications or not self.artifact_hashes):
            raise ValueError("hosted completion requires artifact hashes")
        return self


class HostedExecutionIntent(HostedContract):
    schema_version: Literal["hosted-execution-intent/v1"] = "hosted-execution-intent/v1"
    campaign_hash: Hash
    request_hash: Hash
    hosted_exchange_hash: Hash
    candidate_hash: Hash
    trial_hash: Hash
    execution_identity: Hash
    execution_request_hash: Hash
    budget_reservation_hash: Hash
    phase: Literal["PREPARED", "STARTED"]
    previous_intent_hash: Hash | None
    recorded_at: datetime


class HostedProtocolStatus(HostedContract):
    schema_version: Literal["hosted-protocol-status/v1"] = "hosted-protocol-status/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    request_hash: Hash | None
    state: Literal[
        "READY",
        "WAITING_FOR_AGENT",
        "RESPONSE_ACCEPTED",
        "STEP_COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "EXHAUSTED",
    ]
    projected_expiration: bool
    budget_hash: Hash
    used_requests: NonNegativeInt
    used_unique_submissions: NonNegativeInt
    journal_head_hash: Hash


class HostedResearchBudgetFact(HostedContract):
    """Durable existing research-policy reservation and verified settlement."""

    schema_version: Literal["hosted-research-budget-fact/v1"] = "hosted-research-budget-fact/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    previous_hash: Hash | None
    operation_id: Hash
    request_hash: Hash | None
    phase: Literal["INITIAL", "RESERVED", "SETTLED", "UNCERTAIN"]
    used_trials: NonNegativeInt
    candidate_hashes: tuple[Hash, ...]
    used_executions: NonNegativeInt
    used_validation_rounds: NonNegativeInt
    used_compute_units: NonNegativeInt
    recorded_at: datetime

    @field_validator("candidate_hashes")
    @classmethod
    def candidates_are_sorted(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("research budget candidates must be sorted unique")
        return values


class HostedResearchStepIntent(HostedContract):
    """Freeze trial identity before the natural execution outcome is known."""

    schema_version: Literal["hosted-research-step-intent/v1"] = "hosted-research-step-intent/v1"
    campaign_hash: Hash
    request_hash: Hash
    hosted_exchange_hash: Hash
    candidate_hash: Hash
    trial_idempotency_key: Hash
    execution_request: AutonomousExecutionRequest | None
    budget_reservation_hash: Hash
    phase: Literal["PREPARED", "STARTED", "COMPLETED"]
    previous_intent_hash: Hash | None
    event_time: datetime
    trial_hash: Hash | None = None
    execution_result_hash: Hash | None = None

    @model_validator(mode="after")
    def phase_bindings_agree(self) -> Self:
        if (
            (self.phase == "PREPARED" and self.previous_intent_hash is not None)
            or (self.phase != "PREPARED" and self.previous_intent_hash is None)
            or (self.phase == "STARTED" and self.execution_request is None)
            or (self.phase == "COMPLETED" and self.trial_hash is None)
            or (self.phase != "COMPLETED" and self.trial_hash is not None)
        ):
            raise ValueError("research step phase bindings disagree")
        if self.execution_request is not None and (
            self.execution_request.campaign_hash != self.campaign_hash
            or self.execution_request.agent_run_hash != self.hosted_exchange_hash
            or self.execution_request.candidate.content_hash != self.candidate_hash
        ):
            raise ValueError("research step execution bindings disagree")
        return self


class HostedCampaignReport(HostedContract):
    schema_version: Literal["hosted-campaign-report/v1"] = "hosted-campaign-report/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    provenance_kind: Literal["HOSTED_EXCHANGE"] = "HOSTED_EXCHANGE"
    candidate_manifest_hash: Hash
    candidate_hashes: tuple[Hash, ...]
    attempted_candidate_hashes: tuple[Hash, ...]
    remaining_candidate_hashes: tuple[Hash, ...]
    request_hashes: tuple[Hash, ...]
    hosted_exchange_hashes: tuple[Hash, ...]
    trial_hashes: tuple[Hash, ...]
    campaign_event_hashes: tuple[Hash, ...]
    initial_ledger_snapshot_hash: Hash
    final_ledger_snapshot_hash: Hash
    protocol_budget_hash: Hash
    research_budget_hash: Hash
    selection_report_hash: Hash | None
    state: Literal["COMPLETED", "CANCELLED", "EXPIRED", "EXHAUSTED", "RECOVERY_REQUIRED"]
    reason: Identity
    research_run_status: Literal["SUCCEEDED", "FAILED"]
    research_verdict: Literal["SELECTED", "NO_SELECTION", "NOT_EVALUATED"]
    qualification_eligibility: Literal["NOT_QUALIFIED"] = "NOT_QUALIFIED"
    limitations: tuple[str, ...]
    recorded_at: datetime

    @model_validator(mode="after")
    def complete_denominator(self) -> Self:
        all_candidates = set(self.candidate_hashes)
        attempted = set(self.attempted_candidate_hashes)
        remaining = set(self.remaining_candidate_hashes)
        if (
            len(all_candidates) != len(self.candidate_hashes)
            or attempted & remaining
            or attempted | remaining != all_candidates
            or self.candidate_hashes != tuple(sorted(all_candidates))
            or self.attempted_candidate_hashes != tuple(sorted(attempted))
            or self.remaining_candidate_hashes != tuple(sorted(remaining))
            or (self.research_run_status == "SUCCEEDED" and remaining)
            or (self.research_run_status == "FAILED" and self.research_verdict != "NOT_EVALUATED")
        ):
            raise ValueError("hosted report denominator or verdict is inconsistent")
        return self


class HostedCampaignStatus(HostedContract):
    schema_version: Literal["hosted-campaign-status/v1"] = "hosted-campaign-status/v1"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    protocol: HostedProtocolStatus
    state: Literal[
        "WAITING_FOR_AGENT",
        "EXECUTION_PENDING",
        "STEP_COMPLETED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "EXHAUSTED",
        "RECOVERY_REQUIRED",
    ]
    research_budget_hash: Hash | None
    report_hash: Hash | None
    reason: Identity | None
