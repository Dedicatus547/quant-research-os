"""Harness capability-spike contracts; no Agent SDK or runtime dependency."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.evidence import LOGICAL_ID_PATTERN
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ReasonCode


class HarnessCapability(StrEnum):
    FAILURE_RECOVERY = "FAILURE_RECOVERY"
    MCP = "MCP"
    PERMISSION_DENIAL = "PERMISSION_DENIAL"
    PROPOSAL_BOUNDARY = "PROPOSAL_BOUNDARY"
    SANDBOX = "SANDBOX"
    SKILLS = "SKILLS"
    THREAD = "THREAD"
    TRANSCRIPT = "TRANSCRIPT"
    USAGE = "USAGE"


class HarnessDecision(StrEnum):
    GO = "GO"
    NO_GO = "NO_GO"


class CodexHarnessSpikeSpec(CanonicalContract):
    schema_version: Literal["codex-harness-spike-spec/v1"] = "codex-harness-spike-spec/v1"
    spike_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    provider_model_identifier: str = Field(min_length=1, max_length=200)
    model_snapshot_immutable: Literal[False] = False
    model_reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"]
    codex_cli_version: str = Field(pattern=r"^codex-cli [0-9]+\.[0-9]+\.[0-9]+$")
    sandbox_mode: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    command_network_allowed: Literal[False] = False
    login_shell_allowed: Literal[False] = False
    shell_environment: tuple[str, ...]
    mcp_server_name: Literal["quantosP10"] = "quantosP10"
    mcp_tool_name: Literal["dataset_describe"] = "dataset_describe"
    capability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    instruction_hashes: tuple[str, ...]
    task_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    mcp_server_hash: str = Field(pattern=SHA256_PATTERN)
    mcp_tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    output_schema_hash: str = Field(pattern=SHA256_PATTERN)
    manual_baseline_hash: str = Field(pattern=SHA256_PATTERN)
    write_probe_hash: str = Field(pattern=SHA256_PATTERN)
    required_capabilities: tuple[HarnessCapability, ...]
    max_transcript_bytes: PositiveInt
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt

    @field_validator("shell_environment")
    @classmethod
    def environment_is_exact_and_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != ("LANG", "PATH", "TZ"):
            raise ValueError("P10 shell environment must be the frozen minimal key set")
        return value

    @field_validator("instruction_hashes")
    @classmethod
    def instructions_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("instruction hashes must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("instruction hash is invalid")
        return value

    @field_validator("required_capabilities")
    @classmethod
    def capabilities_are_complete(
        cls, value: tuple[HarnessCapability, ...]
    ) -> tuple[HarnessCapability, ...]:
        expected = tuple(sorted(HarnessCapability, key=str))
        if value != expected:
            raise ValueError("P10 must evaluate every frozen hard capability exactly once")
        return value


class HarnessCapabilityCheck(CanonicalContract):
    schema_version: Literal["harness-capability-check/v1"] = "harness-capability-check/v1"
    capability: HarnessCapability
    passed: bool
    evidence_hashes: tuple[str, ...]
    detail: str = Field(min_length=1, max_length=1000)
    reason_code: ReasonCode | None = None

    @field_validator("evidence_hashes")
    @classmethod
    def evidence_is_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("capability evidence must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("capability evidence hash is invalid")
        return value

    @model_validator(mode="after")
    def outcome_matches_reason(self) -> Self:
        if self.passed == (self.reason_code is not None):
            raise ValueError("failed capability requires a reason; passed capability forbids one")
        return self


class CodexHarnessSpikeReport(CanonicalContract):
    schema_version: Literal["codex-harness-spike-report/v1"] = "codex-harness-spike-report/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})
    spike_spec_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    transcript_hash: str = Field(pattern=SHA256_PATTERN)
    raw_transcript_retained: bool
    checks: tuple[HarnessCapabilityCheck, ...]
    decision: HarnessDecision
    limitations: tuple[str, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("spike report timestamp must be timezone-aware")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @model_validator(mode="after")
    def decision_matches_complete_matrix(self) -> Self:
        capabilities = [item.capability for item in self.checks]
        if capabilities != sorted(set(capabilities), key=str) or set(capabilities) != set(
            HarnessCapability
        ):
            raise ValueError("report must contain one sorted check per frozen capability")
        if (self.decision is HarnessDecision.GO) != all(item.passed for item in self.checks):
            raise ValueError("harness decision does not match hard capability checks")
        return self
