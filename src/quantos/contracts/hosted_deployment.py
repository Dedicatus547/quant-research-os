"""Pure deployment, channel and external observation identities; no runtime imports."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.hosted import Hash, HostedContract, Identity


class HostedFileIdentity(HostedContract):
    schema_version: Literal["hosted-file-identity/v1"] = "hosted-file-identity/v1"
    relative_path: str = Field(min_length=1, max_length=1024)
    bytes_hash: Hash
    size_bytes: int = Field(ge=0)
    mode: int = Field(ge=0, le=0o777)

    @field_validator("relative_path")
    @classmethod
    def confined_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or str(path) != value or "\\" in value:
            raise ValueError("inventory requires a normalized relative path")
        return value


class HostedInstallInventory(HostedContract):
    schema_version: Literal["hosted-install-inventory/v1"] = "hosted-install-inventory/v1"
    files: tuple[HostedFileIdentity, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sorted_files(self) -> Self:
        names = tuple(x.relative_path for x in self.files)
        if names != tuple(sorted(set(names))):
            raise ValueError("inventory files must be sorted and unique")
        return self


class HostedChannelPolicy(HostedContract):
    schema_version: Literal["hosted-channel-policy/v1"] = "hosted-channel-policy/v1"
    header_byte_cap: int = Field(gt=0, le=4096)
    response_byte_cap: int = Field(gt=0, le=262144)
    reply_byte_cap: int = Field(gt=0, le=1_052_672)
    io_timeout_ms: int = Field(gt=0, le=60000)
    operation_reply_timeout_ms: int = Field(gt=0, le=3_600_000)
    max_connections: int = Field(gt=0, le=32)
    max_total_connections: int = Field(gt=0, le=100000)
    listen_backlog: int = Field(gt=0, le=32)
    capability_bytes: Literal[32] = 32
    requests_per_connection: Literal[1] = 1


class HostedClientConfiguration(HostedContract):
    schema_version: Literal["hosted-client-configuration/v1"] = "hosted-client-configuration/v1"
    socket_path: str = Field(min_length=1, max_length=107)
    policy: HostedChannelPolicy


class HostedPrincipalConfiguration(HostedContract):
    schema_version: Literal["hosted-principal-configuration/v1"] = (
        "hosted-principal-configuration/v1"
    )
    principal: Identity
    host_instance: Identity
    uid: int = Field(ge=0)
    gid: int = Field(ge=0)
    campaign_hashes: tuple[Hash, ...] = Field(min_length=1, max_length=32)
    capability_fd: int = Field(ge=3, le=1024)


class HostedCampaignAuthorization(HostedContract):
    schema_version: Literal["hosted-campaign-authorization/v1"] = "hosted-campaign-authorization/v1"
    campaign_hash: Hash


class HostedServiceConfiguration(HostedContract):
    schema_version: Literal["hosted-service-configuration/v1"] = "hosted-service-configuration/v1"
    application_factory: Literal["p14dq-frozen/v1"] = "p14dq-frozen/v1"
    business_configuration_hash: Hash
    protocol_root: Literal["/authority/protocol"] = "/authority/protocol"
    business_lock_root: Literal["/authority/business-locks"] = "/authority/business-locks"
    socket_path: Literal["/channel/quantos.sock"] = "/channel/quantos.sock"
    configuration_root: Literal["/config"] = "/config"
    policy: HostedChannelPolicy
    principals: tuple[HostedPrincipalConfiguration, ...] = Field(min_length=1, max_length=32)
    campaigns: tuple[HostedCampaignAuthorization, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def fixed_authorizations(self) -> Self:
        campaigns = tuple(x.campaign_hash for x in self.campaigns)
        if len(set(campaigns)) != len(campaigns) or len(
            {x.capability_fd for x in self.principals}
        ) != len(self.principals):
            raise ValueError("service authorization registrations must be unique")
        allowed = {x.campaign_hash for x in self.campaigns}
        if any(not set(x.campaign_hashes).issubset(allowed) for x in self.principals):
            raise ValueError("principal authorization must use registered campaign identities")
        return self


class HostedChannelRequest(HostedContract):
    schema_version: Literal["hosted-channel-request/v1"] = "hosted-channel-request/v1"
    operation: Literal["start", "pending", "status", "submit", "resume", "cancel"]
    campaign_hash: Hash
    target_hash: Hash


class HostedDeploymentProfile(HostedContract):
    schema_version: Literal["hosted-deployment-profile/v2"] = "hosted-deployment-profile/v2"
    profile: Literal["hm-isolated-service/v1"] = "hm-isolated-service/v1"
    architecture: Literal["x86_64"] = "x86_64"
    operating_system: str = Field(min_length=1, max_length=200)
    kernel_release: str = Field(min_length=1, max_length=200)
    libc: str = Field(min_length=1, max_length=200)
    python_version: str = Field(pattern=r"^3\.11\.[0-9]+$")
    python_initialization: Literal["PYCONFIG_ISOLATED_HASH_SEED_ZERO/v1"] = (
        "PYCONFIG_ISOLATED_HASH_SEED_ZERO/v1"
    )
    python_hash_seed: Literal[0] = 0
    exact_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    lock_hash: Hash
    wheel_hash: Hash
    install_inventory_hash: Hash
    provenance_inventory_hash: Hash
    configuration_hash: Hash
    projection_inventory_hash: Hash
    bwrap_binary_hash: Hash
    os_inventory_hash: Hash
    mount_policy_hash: Hash
    libseccomp_binary_hash: Hash
    bwrap_version: str = Field(min_length=1, max_length=100)
    seccomp_bpf_hash: Hash
    cli_binary_hash: Hash
    cli_version: Literal["0.158.0"] = "0.158.0"
    model_configuration_hash: Hash
    extraction_rule_hash: Hash
    service_network: Literal["UNSHARED_OFFLINE"] = "UNSHARED_OFFLINE"
    host_network: Literal["PROPOSAL_ONLY_SHARED"] = "PROPOSAL_ONLY_SHARED"
    host_proc: Literal["EMPTY_READ_ONLY_TMPFS"] = "EMPTY_READ_ONLY_TMPFS"
    service_import: Literal["ISOLATED_FROZEN_PYTHON"] = "ISOLATED_FROZEN_PYTHON"
    channel_authentication: Literal["PEERCRED_AND_MEMORY_CAPABILITY"] = (
        "PEERCRED_AND_MEMORY_CAPABILITY"
    )
    authority_path: Literal["/authority"] = "/authority"
    install_path: Literal["/install"] = "/install"
    provenance_path: Literal["/provenance"] = "/provenance"
    projection_path: Literal["/projection"] = "/projection"
    configuration_path: Literal["/config"] = "/config"
    channel_path: Literal["/channel"] = "/channel"
    policy: HostedChannelPolicy


class HostedLauncherConfiguration(HostedContract):
    schema_version: Literal["hosted-launcher-configuration/v1"] = "hosted-launcher-configuration/v1"
    model: Literal["gpt-6-sol", "gpt-6.1-sol"] = "gpt-6-sol"
    reasoning_effort: Literal["high"] = "high"
    output_byte_cap: int = Field(gt=0, le=4_194_304)
    proposal_byte_cap: int = Field(gt=0, le=262144)
    runtime_timeout_seconds: int = Field(gt=0, le=3600)
    extraction_rule: Literal["codex-jsonl-single-final/v1"] = "codex-jsonl-single-final/v1"
    permission_observation: Literal["REQUESTED_ONLY_NOT_EFFECTIVE_ATTESTATION"] = (
        "REQUESTED_ONLY_NOT_EFFECTIVE_ATTESTATION"
    )


class HostedProjectionFact(HostedContract):
    schema_version: Literal["hosted-projection-fact/v1"] = "hosted-projection-fact/v1"
    source: Literal["TRUSTED_PROJECTION_MANAGER"] = "TRUSTED_PROJECTION_MANAGER"
    phase: Literal["PRE_LAUNCH"] = "PRE_LAUNCH"
    campaign_hash: Hash
    hosted_spec_hash: Hash
    deployment_profile_hash: Hash
    request_hash: Hash
    host_instance: Identity
    initial_projection_inventory_hash: Hash
    projection_inventory_hash: Hash


class HostedMountObservation(HostedContract):
    schema_version: Literal["hosted-mount-observation/v1"] = "hosted-mount-observation/v1"
    source: Literal["TRUSTED_PRE_LAUNCH_BWRAP_PROBE"] = "TRUSTED_PRE_LAUNCH_BWRAP_PROBE"
    request_hash: Hash
    deployment_profile_hash: Hash
    projection_inventory_hash: Hash
    projection_readonly: Literal[True] = True
    install_readonly: Literal[True] = True
    channel_readonly: Literal[True] = True
    proc_empty: Literal[True] = True
    observed_uid: int = Field(ge=0)
    observed_gid: int = Field(ge=0)


class HostedLauncherRecord(HostedContract):
    schema_version: Literal["hosted-launcher-record/v2"] = "hosted-launcher-record/v2"
    source: Literal["TRUSTED_EXTERNAL_LAUNCHER"] = "TRUSTED_EXTERNAL_LAUNCHER"
    deployment_profile_hash: Hash
    host_instance: Identity
    request_hash: Hash
    projection_inventory_hash: Hash
    projection_fact_hash: Hash
    executable_hash: Hash
    executable_version: str = Field(min_length=1, max_length=100)
    configuration_hash: Hash
    argv_hash: Hash
    prompt_hash: Hash
    isolation_observation_hash: Hash
    raw_output_hash: Hash | None
    raw_output_complete: bool
    diagnostic_output_hash: Hash | None
    proposal_hash: Hash | None
    proposal_bytes: int = Field(ge=0, le=262144)
    actual_model_identifier: str | None = Field(default=None, max_length=200)
    started_at: datetime
    terminated_at: datetime
    exit_code: int | None
    outcome: Literal["CAPTURED", "REJECTED", "TIMED_OUT", "OUTPUT_LIMIT"]
    reason: Identity
    transcript_scope: Literal["CLI_EVENT_OBSERVATION_NOT_PROVIDER_INTERNAL_TRANSCRIPT"] = (
        "CLI_EVENT_OBSERVATION_NOT_PROVIDER_INTERNAL_TRANSCRIPT"
    )
    unavailable_reasons: tuple[Identity, ...]

    @model_validator(mode="after")
    def complete_capture(self) -> Self:
        if self.terminated_at < self.started_at:
            raise ValueError("launcher terminal time precedes start")
        if self.outcome == "CAPTURED" and (
            self.exit_code != 0
            or self.proposal_hash is None
            or self.raw_output_hash is None
            or not self.raw_output_complete
        ):
            raise ValueError("captured source requires successful exit and proposal")
        return self
