"""Successor hosted generation identities; no future research campaign dependency."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, PositiveInt, model_validator

from quantos.contracts.base import sha256_bytes
from quantos.contracts.discovery import (
    GenerationRequest,
    GenerationReservation,
    SequentialGenerationAttempt,
    SequentialGenerationPolicy,
)
from quantos.contracts.hosted import Hash, HostedContract, HostObservation, Identity


class HostedGenerationRequest(HostedContract):
    schema_version: Literal["hosted-generation-request/v1"] = "hosted-generation-request/v1"
    profile: Literal["hm-discovery/v1"] = "hm-discovery/v1"
    generation_request: GenerationRequest
    reservation: GenerationReservation
    design_hash: Hash
    configuration_hash: Hash
    deployment_profile_hash: Hash
    proposal_schema_hash: Hash
    input_hashes: tuple[Hash, ...]
    projection_object_hashes: tuple[Hash, ...]
    max_response_bytes: PositiveInt = Field(default=65_536, le=65_536)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def generation_bindings_agree(self) -> Self:
        request = self.generation_request
        if (
            request.method != "LLM"
            or request.design_hash != self.design_hash
            or request.configuration_hash != self.configuration_hash
            or self.reservation.request_hash != request.content_hash
            or self.reservation.ordinal > request.max_attempts
            or not {self.design_hash, request.content_hash, self.reservation.content_hash}.issubset(
                self.input_hashes
            )
            or not set(self.input_hashes).issubset(self.projection_object_hashes)
            or not set(request.input_hashes).issubset(self.input_hashes)
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("hosted generation request bindings disagree")
        for hashes in (self.input_hashes, self.projection_object_hashes):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError("hosted generation projection hashes must be sorted unique")
        return self


class HostedGenerationResponse(HostedContract):
    schema_version: Literal["hosted-generation-response/v1"] = "hosted-generation-response/v1"
    profile: Literal["hm-discovery/v1"] = "hm-discovery/v1"
    request_hash: Hash
    design_hash: Hash
    reservation_hash: Hash
    proposal_json: str = Field(max_length=65_536)
    proposal_hash: Hash
    host_observation: HostObservation

    @model_validator(mode="after")
    def raw_proposal_is_bound(self) -> Self:
        if len(self.proposal_json.encode("utf-8")) > 65_536 or self.proposal_hash != sha256_bytes(
            self.proposal_json.encode("utf-8")
        ):
            raise ValueError("hosted generation raw proposal hash differs")
        return self


class HostedGenerationProjectionFact(HostedContract):
    schema_version: Literal["hosted-generation-projection-fact/v1"] = (
        "hosted-generation-projection-fact/v1"
    )
    source: Literal["TRUSTED_PROJECTION_MANAGER"] = "TRUSTED_PROJECTION_MANAGER"
    phase: Literal["PRE_LAUNCH"] = "PRE_LAUNCH"
    design_hash: Hash
    request_hash: Hash
    reservation_hash: Hash
    deployment_profile_hash: Hash
    host_instance: Identity
    initial_projection_inventory_hash: Hash
    projection_inventory_hash: Hash


class HostedGenerationSourceReceipt(HostedContract):
    schema_version: Literal["hosted-generation-source-receipt/v1"] = (
        "hosted-generation-source-receipt/v1"
    )
    profile: Literal["hm-discovery/v1"] = "hm-discovery/v1"
    authenticated_principal: Identity
    request_hash: Hash
    response_hash: Hash
    reservation_hash: Hash
    launcher_record_hash: Hash
    projection_fact_hash: Hash
    isolation_hash: Hash
    launch_prelaunch_hash: Hash
    launch_completion_hash: Hash
    design_hash: Hash
    proposal_hash: Hash
    configuration_hash: Hash
    deployment_profile_hash: Hash
    recorded_at: datetime
    qualification: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class HostedGenerationOrigin(HostedContract):
    """Management-owned original locations; no permission is conferred by these paths."""

    schema_version: Literal["hosted-generation-origin/v1"] = "hosted-generation-origin/v1"
    manager_root: str = Field(min_length=1, max_length=4096)
    evidence_root: str = Field(min_length=1, max_length=4096)
    authenticated_principal: Identity
    request_hash: Hash
    response_hash: Hash
    source_receipt_hash: Hash
    configuration_hash: Hash
    deployment_profile_hash: Hash


class HostedSequentialGenerationRequest(HostedContract):
    schema_version: Literal["hosted-sequential-generation-request/v2"] = (
        "hosted-sequential-generation-request/v2"
    )
    profile: Literal["hm-discovery-sequential/v2"] = "hm-discovery-sequential/v2"
    policy: SequentialGenerationPolicy
    attempt: SequentialGenerationAttempt
    generation_request: GenerationRequest
    reservation: GenerationReservation
    design_hash: Hash
    configuration_hash: Hash
    deployment_profile_hash: Hash
    proposal_schema_hash: Hash
    input_hashes: tuple[Hash, ...]
    projection_object_hashes: tuple[Hash, ...]
    max_response_bytes: PositiveInt = Field(default=65_536, le=65_536)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def generation_bindings_agree(self) -> Self:
        request = self.generation_request
        if (
            request.method != "LLM"
            or request.design_hash != self.design_hash
            or request.configuration_hash != self.configuration_hash
            or self.reservation.request_hash != request.content_hash
            or self.reservation.ordinal > request.max_attempts
            or not {self.design_hash, request.content_hash, self.reservation.content_hash}.issubset(
                self.input_hashes
            )
            or not set(self.input_hashes).issubset(self.projection_object_hashes)
            or not set(request.input_hashes).issubset(self.input_hashes)
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("hosted generation request bindings disagree")
        for hashes in (self.input_hashes, self.projection_object_hashes):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError("hosted generation projection hashes must be sorted unique")
        if (
            self.policy.design_hash != self.design_hash
            or request.content_hash not in self.policy.request_hashes
            or self.attempt.reservation != self.reservation
            or self.attempt.history.method != request.method
            or self.attempt.history.policy_hash != self.policy.content_hash
            or not {
                self.policy.content_hash,
                self.attempt.content_hash,
                self.attempt.history.content_hash,
            }.issubset(self.input_hashes)
        ):
            raise ValueError("hosted sequential policy/history bindings disagree")
        return self


class HostedSequentialGenerationOrigin(HostedContract):
    """Management-owned original locations; no permission is conferred by these paths."""

    schema_version: Literal["hosted-sequential-generation-origin/v2"] = (
        "hosted-sequential-generation-origin/v2"
    )
    manager_root: str = Field(min_length=1, max_length=4096)
    evidence_root: str = Field(min_length=1, max_length=4096)
    authenticated_principal: Identity
    request_hash: Hash
    response_hash: Hash
    source_receipt_hash: Hash
    configuration_hash: Hash
    deployment_profile_hash: Hash

    generation_root: str = Field(min_length=1, max_length=4096)
    attempt_hash: Hash
