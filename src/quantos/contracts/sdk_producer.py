"""Explicit SDK successors; all legacy hosted contracts retain their bytes."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, model_validator

from quantos.contracts.agent import AgentRunManifestV3, AgentRunSpecV3
from quantos.contracts.autonomous import SDK_BOUNDED_FINALIZATION_PROFILE
from quantos.contracts.base import sha256_bytes
from quantos.contracts.harness import HarnessExecutionRequest
from quantos.contracts.hosted import (
    Hash,
    HostedAgentExchange,
    HostedAgentRequest,
    HostedBudgetPolicy,
    HostedCampaignSpec,
    HostedContract,
)
from quantos.contracts.sdk_prompt import SDK_PROMPT_PROJECTION_HASH


class SdkProducerProfile(HostedContract):
    schema_version: Literal["sdk-producer-profile/v1"] = "sdk-producer-profile/v1"
    runtime_candidate_id: Literal["openai-codex-0.162.1-gpt61-fr03"] = (
        "openai-codex-0.162.1-gpt61-fr03"
    )
    sdk_version: Literal["0.162.1"] = "0.162.1"
    runtime_package_version: Literal["0.162.1"] = "0.162.1"
    runtime_binary_hash: Hash
    model: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
    reasoning_effort: Literal["medium"] = "medium"
    reasoning_summary: Literal["none"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    cwd: str = Field(min_length=1, max_length=4096)
    evidence_root: str = Field(min_length=1, max_length=4096)
    max_launches: PositiveInt
    max_attempts: Literal[1] = 1
    timeout_seconds: PositiveInt
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_transcript_bytes: int = Field(gt=0, le=65536)
    max_raw_response_bytes: int = Field(gt=0, le=16384)
    mapping_version: Literal["sdk-candidate-reference-map/v1"] = "sdk-candidate-reference-map/v1"
    requested_model_configuration_hash: Hash
    skill_hash: Hash
    instruction_hashes: tuple[Hash, ...] = Field(min_length=1)
    qualification: Literal["OFFLINE_PREPARATION_ONLY"] = "OFFLINE_PREPARATION_ONLY"


class SdkProducerProfileV2(SdkProducerProfile):
    """Explicit full-stream 128 KiB successor; v1 limits remain unchanged."""

    schema_version: Literal["sdk-producer-profile/v2"] = "sdk-producer-profile/v2"  # type: ignore[assignment]
    max_transcript_bytes: Literal[131072] = 131072  # type: ignore[assignment]
    max_normalized_transcript_bytes: Literal[65536] = 65536
    reasoning_summary: Literal["none"] = "none"  # type: ignore[assignment]


class SdkProducerProfileV3(SdkProducerProfile):
    """Explicit 256 KiB provider capture; previous profiles stay frozen."""

    schema_version: Literal["sdk-producer-profile/v3"] = "sdk-producer-profile/v3"  # type: ignore[assignment]
    max_transcript_bytes: Literal[262144] = 262144  # type: ignore[assignment]
    max_normalized_transcript_bytes: Literal[65536] = 65536
    reasoning_summary: Literal["none"] = "none"  # type: ignore[assignment]


class SdkProducerProfileV4(SdkProducerProfileV3):
    """Explicit bounded prompt successor; all V3 capture bounds are inherited."""

    schema_version: Literal["sdk-producer-profile/v4"] = "sdk-producer-profile/v4"  # type: ignore[assignment]
    prompt_projection_identifier: Literal["sdk-frozen-context-projection/v1"]
    prompt_projection_hash: Hash

    @model_validator(mode="after")
    def projection_policy_binding(self) -> Self:
        if self.prompt_projection_hash != SDK_PROMPT_PROJECTION_HASH:
            raise ValueError("SDK prompt projection policy hash differs")
        return self


class SdkHostedBudgetPolicyV3(HostedBudgetPolicy):
    """Explicit frame allowance; JSON escaping can still exceed this cap."""

    schema_version: Literal["sdk-hosted-budget-policy/v3"] = "sdk-hosted-budget-policy/v3"  # type: ignore[assignment]
    max_response_bytes: Literal[524288] = 524288  # type: ignore[assignment]


class SdkCampaignSpec(HostedCampaignSpec):
    schema_version: Literal["sdk-campaign-spec/v1"] = "sdk-campaign-spec/v1"  # type: ignore[assignment]
    profile: Literal["sdk-bounded/v1"] = "sdk-bounded/v1"  # type: ignore[assignment]
    sdk_profile: Annotated[
        SdkProducerProfile | SdkProducerProfileV2 | SdkProducerProfileV3 | SdkProducerProfileV4,
        Field(discriminator="schema_version"),
    ]
    hosted_budget: Annotated[
        HostedBudgetPolicy | SdkHostedBudgetPolicyV3, Field(discriminator="schema_version")
    ]

    @model_validator(mode="after")
    def sdk_budget_binding(self) -> Self:
        if isinstance(self.sdk_profile, SdkProducerProfileV3) != isinstance(
            self.hosted_budget, SdkHostedBudgetPolicyV3
        ):
            raise ValueError("SDK capture profile and frame budget versions disagree")
        if (
            self.selection_finalization_profile_hash
            != SDK_BOUNDED_FINALIZATION_PROFILE.content_hash
            or self.sdk_profile.max_launches != self.hosted_budget.max_requests
            or self.sdk_profile.requested_model_configuration_hash
            != self.requested_model_configuration_hash
        ):
            raise ValueError("SDK profile differs from frozen campaign allowance/configuration")
        return self

    @property
    def frozen_input_hashes(self) -> tuple[str, ...]:
        return tuple(sorted({*super().frozen_input_hashes, self.sdk_profile.content_hash}))


class SdkAgentRequest(HostedAgentRequest):
    schema_version: Literal["sdk-agent-request/v1"] = "sdk-agent-request/v1"  # type: ignore[assignment]
    profile: Literal["sdk-bounded/v1"] = "sdk-bounded/v1"  # type: ignore[assignment]
    sdk_profile_hash: Hash


class SdkAgentRequestV3(SdkAgentRequest):
    schema_version: Literal["sdk-agent-request/v3"] = "sdk-agent-request/v3"  # type: ignore[assignment]
    max_response_bytes: Literal[524288] = 524288  # type: ignore[assignment]


class SdkSemanticProposal(HostedContract):
    schema_version: Literal["sdk-candidate-reference/v1"] = "sdk-candidate-reference/v1"
    candidate_ref: str = Field(pattern=r"^candidate-[0-9a-f]{64}$")
    rationale: str = Field(min_length=1, max_length=10000)
    request_stop: bool


class SdkLaunchReservation(HostedContract):
    schema_version: Literal["sdk-launch-reservation/v1"] = "sdk-launch-reservation/v1"
    request_hash: Hash
    attempt_identity: Hash
    campaign_hash: Hash
    sdk_profile_hash: Hash
    execution_request: HarnessExecutionRequest
    run_spec: AgentRunSpecV3


class SdkAgentResponse(HostedContract):
    schema_version: Literal["sdk-agent-response/v1"] = "sdk-agent-response/v1"
    request_hash: Hash
    campaign_hash: Hash
    transport_ordinal: PositiveInt
    context_pack_hash: Hash
    attempt_identity: Hash
    sdk_profile_hash: Hash
    reservation: SdkLaunchReservation
    manifest: AgentRunManifestV3
    normalized_transcript: str = Field(max_length=65536)
    provider_transcript: str = Field(max_length=65536)
    raw_response: str = Field(max_length=16384)
    raw_response_hash: Hash
    mapping_version: Literal["sdk-candidate-reference-map/v1"] = "sdk-candidate-reference-map/v1"
    proposal_json: str = Field(min_length=1, max_length=262144)
    proposal_hash: Hash

    @model_validator(mode="after")
    def byte_bindings(self) -> Self:
        if (
            sha256_bytes(self.raw_response.encode("utf-8")) != self.raw_response_hash
            or sha256_bytes(self.proposal_json.encode("utf-8")) != self.proposal_hash
            or sha256_bytes(self.normalized_transcript.encode("utf-8"))
            != self.manifest.normalized_transcript_hash
            or sha256_bytes(self.provider_transcript.encode("utf-8"))
            != self.manifest.provider_transcript_hash
            or self.manifest.output_proposal_hashes != (self.raw_response_hash,)
            or self.manifest.run_spec_hash != self.reservation.run_spec.content_hash
            or self.manifest.run_status.value != "SUCCEEDED"
        ):
            raise ValueError("SDK original and mapped response bindings disagree")
        return self


class SdkAgentResponseV2(SdkAgentResponse):
    """Full provider originals at 128 KiB; normalized/semantic limits inherited."""

    schema_version: Literal["sdk-agent-response/v2"] = "sdk-agent-response/v2"  # type: ignore[assignment]
    provider_transcript: str = Field(max_length=131072)

    @model_validator(mode="after")
    def capture_byte_bounds(self) -> Self:
        if (
            len(self.provider_transcript.encode("utf-8")) > 131072
            or len(self.normalized_transcript.encode("utf-8")) > 65536
            or len(self.raw_response.encode("utf-8")) > 16384
        ):
            raise ValueError("SDK original exceeds its explicit capture version bound")
        return self


class SdkAgentResponseV3(SdkAgentResponse):
    """UTF-8 byte bounds are distinct from the complete JSON frame bound."""

    schema_version: Literal["sdk-agent-response/v3"] = "sdk-agent-response/v3"  # type: ignore[assignment]
    provider_transcript: str = Field(max_length=262144)

    @model_validator(mode="after")
    def capture_byte_bounds(self) -> Self:
        if (
            len(self.provider_transcript.encode("utf-8")) > 262144
            or len(self.normalized_transcript.encode("utf-8")) > 65536
            or len(self.raw_response.encode("utf-8")) > 16384
        ):
            raise ValueError("SDK original exceeds its explicit capture version bound")
        return self


def parse_sdk_response(data: bytes, *, max_bytes: int) -> SdkAgentResponse:
    from quantos.contracts.hosted import parse_hosted_contract, strict_json_object

    schema = strict_json_object(data, max_bytes=max_bytes).get("schema_version")
    if schema == "sdk-agent-response/v1":
        cls = SdkAgentResponse
    elif schema == "sdk-agent-response/v2":
        cls = SdkAgentResponseV2
    elif schema == "sdk-agent-response/v3":
        cls = SdkAgentResponseV3
    else:
        raise ValueError("unknown SDK capture response version")
    return parse_hosted_contract(data, cls, max_bytes=max_bytes)


class SdkAgentExchange(HostedAgentExchange):
    schema_version: Literal["sdk-agent-exchange/v1"] = "sdk-agent-exchange/v1"  # type: ignore[assignment]
    provenance_kind: Literal["SDK_EXCHANGE"] = "SDK_EXCHANGE"  # type: ignore[assignment]
    # Kept as a compatibility field name for the shared receipt protocol; this hash
    # binds the actual V3 manifest, never a HostObservation.
    manifest_hash: Hash
    sdk_profile_hash: Hash
    raw_response_hash: Hash
    mapping_version: Literal["sdk-candidate-reference-map/v1"] = "sdk-candidate-reference-map/v1"


def parse_campaign_spec(data: bytes, *, max_bytes: int) -> HostedCampaignSpec:
    from quantos.contracts.hosted import parse_hosted_contract, strict_json_object

    cls = (
        SdkCampaignSpec
        if strict_json_object(data, max_bytes=max_bytes).get("schema_version")
        == "sdk-campaign-spec/v1"
        else HostedCampaignSpec
    )
    return parse_hosted_contract(data, cls, max_bytes=max_bytes)


def parse_agent_request(data: bytes, *, max_bytes: int) -> HostedAgentRequest:
    from quantos.contracts.hosted import parse_hosted_contract, strict_json_object

    schema = strict_json_object(data, max_bytes=max_bytes).get("schema_version")
    if schema == "sdk-agent-request/v1":
        cls = SdkAgentRequest
    elif schema == "sdk-agent-request/v3":
        cls = SdkAgentRequestV3
    else:
        cls = HostedAgentRequest
    return parse_hosted_contract(data, cls, max_bytes=max_bytes)


def parse_agent_exchange(data: bytes, *, max_bytes: int) -> HostedAgentExchange:
    from quantos.contracts.hosted import parse_hosted_contract, strict_json_object

    cls = (
        SdkAgentExchange
        if strict_json_object(data, max_bytes=max_bytes).get("schema_version")
        == "sdk-agent-exchange/v1"
        else HostedAgentExchange
    )
    return parse_hosted_contract(data, cls, max_bytes=max_bytes)
