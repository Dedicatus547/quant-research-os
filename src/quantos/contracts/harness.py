"""Harness capability-spike contracts; no Agent SDK or runtime dependency."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
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


class AgentEventKind(StrEnum):
    AGENT_MESSAGE = "AGENT_MESSAGE"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    ATTEMPT_COMPLETED = "ATTEMPT_COMPLETED"
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    COMMAND_COMPLETED = "COMMAND_COMPLETED"
    COMMAND_FAILED = "COMMAND_FAILED"
    COMMAND_STARTED = "COMMAND_STARTED"
    HARNESS_ERROR = "HARNESS_ERROR"
    THREAD_STARTED = "THREAD_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    TOOL_STARTED = "TOOL_STARTED"
    TURN_COMPLETED = "TURN_COMPLETED"
    TURN_FAILED = "TURN_FAILED"
    TURN_STARTED = "TURN_STARTED"
    USAGE = "USAGE"


class HarnessErrorKind(StrEnum):
    AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    INTERRUPTED = "INTERRUPTED"
    MCP_FAILED = "MCP_FAILED"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    OVERLOADED = "OVERLOADED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PROTOCOL_UNSUPPORTED = "PROTOCOL_UNSUPPORTED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    RUNTIME_MISMATCH = "RUNTIME_MISMATCH"
    TIMEOUT = "TIMEOUT"
    TRANSPORT_CLOSED = "TRANSPORT_CLOSED"
    TRANSPORT_START_FAILED = "TRANSPORT_START_FAILED"
    UNKNOWN = "UNKNOWN"


class HarnessEnvironmentVariable(CanonicalContract):
    schema_version: Literal["harness-environment-variable/v1"] = "harness-environment-variable/v1"
    name: Literal["LANG", "PATH", "TZ"]
    value: str = Field(min_length=1, max_length=4096)


class HarnessRuntimePolicy(CanonicalContract):
    schema_version: Literal["harness-runtime-policy/v1"] = "harness-runtime-policy/v1"
    host_environment: tuple[HarnessEnvironmentVariable, ...]
    child_environment: tuple[HarnessEnvironmentVariable, ...]
    shell_environment: tuple[HarnessEnvironmentVariable, ...]
    sandbox_mode: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    shell_tool_enabled: bool
    login_shell_allowed: Literal[False] = False
    network_allowed: Literal[False] = False
    history_persistence: Literal["none"] = "none"

    @field_validator("host_environment", "child_environment", "shell_environment")
    @classmethod
    def environment_is_exact(
        cls, value: tuple[HarnessEnvironmentVariable, ...]
    ) -> tuple[HarnessEnvironmentVariable, ...]:
        names = [item.name for item in value]
        if names != sorted(set(names)):
            raise ValueError("harness environment must be sorted and unique")
        return value


class HarnessMcpServer(CanonicalContract):
    schema_version: Literal["harness-mcp-server/v1"] = "harness-mcp-server/v1"
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    command: str = Field(min_length=1, max_length=4096)
    args: tuple[str, ...] = ()
    enabled_tools: tuple[str, ...]
    required: Literal[True] = True
    implementation_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)

    @field_validator("enabled_tools")
    @classmethod
    def tools_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("MCP enabled tools must be nonempty, sorted, and unique")
        return value


class HarnessExecutionRequest(CanonicalContract):
    schema_version: Literal["harness-execution-request/v1"] = "harness-execution-request/v1"
    run_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    cwd: str = Field(min_length=1, max_length=4096)
    prompt: str = Field(min_length=1, max_length=200_000)
    model: str = Field(min_length=1, max_length=200)
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"]
    runtime_policy: HarnessRuntimePolicy
    mcp_servers: tuple[HarnessMcpServer, ...]
    output_schema_json: str | None = Field(default=None, max_length=200_000)
    timeout_seconds: PositiveInt
    max_transcript_bytes: PositiveInt
    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_attempts: int = Field(default=1, ge=1, le=3)

    @field_validator("mcp_servers")
    @classmethod
    def servers_are_sorted_unique(
        cls, value: tuple[HarnessMcpServer, ...]
    ) -> tuple[HarnessMcpServer, ...]:
        names = [item.name for item in value]
        if names != sorted(set(names)):
            raise ValueError("MCP servers must be sorted and unique")
        return value

    @field_validator("output_schema_json")
    @classmethod
    def output_schema_is_an_object(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            schema = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("harness output schema is invalid JSON") from error
        if not isinstance(schema, dict):
            raise ValueError("harness output schema must be a JSON object")
        return value


class HarnessRuntimeIdentity(CanonicalContract):
    schema_version: Literal["harness-runtime-identity/v1"] = "harness-runtime-identity/v1"
    adapter: Literal["openai-codex-python-sdk"] = "openai-codex-python-sdk"
    sdk_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    runtime_version: str = Field(min_length=1, max_length=500)
    protocol: Literal["codex-app-server-jsonrpc-v2"] = "codex-app-server-jsonrpc-v2"
    normalizer_version: Literal["quantos-codex-normalizer/v1"] = "quantos-codex-normalizer/v1"


class HarnessTerminalError(CanonicalContract):
    schema_version: Literal["harness-terminal-error/v1"] = "harness-terminal-error/v1"
    kind: HarnessErrorKind
    message_hash: str = Field(pattern=SHA256_PATTERN)
    retryable: bool = False


class AgentEvent(CanonicalContract):
    schema_version: Literal["quantos-agent-event/v1"] = "quantos-agent-event/v1"
    attempt: PositiveInt
    sequence: PositiveInt
    kind: AgentEventKind
    provider_event_type: str = Field(min_length=1, max_length=500)
    payload: dict[str, object]
    payload_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def payload_hash_matches(self) -> Self:
        if sha256_bytes(canonical_json_bytes(self.payload)) != self.payload_hash:
            raise ValueError("Agent event payload hash does not match")
        return self


AgentEventV1 = AgentEvent


class HarnessCapabilitySpikeSpecV2(CanonicalContract):
    schema_version: Literal["agent-harness-spike-spec/v2"] = "agent-harness-spike-spec/v2"
    spike_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    execution_request_hash: str = Field(pattern=SHA256_PATTERN)
    required_capabilities: tuple[HarnessCapability, ...]
    input_hashes: tuple[str, ...]

    @field_validator("required_capabilities")
    @classmethod
    def capabilities_are_complete_v2(
        cls, value: tuple[HarnessCapability, ...]
    ) -> tuple[HarnessCapability, ...]:
        expected = tuple(sorted(HarnessCapability, key=str))
        if value != expected:
            raise ValueError("P10 v2 must evaluate every frozen hard capability exactly once")
        return value

    @field_validator("input_hashes")
    @classmethod
    def hashes_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("P10 v2 input hashes must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("P10 v2 input hash is invalid")
        return value


class HarnessCapabilitySpikeReportV2(CanonicalContract):
    schema_version: Literal["agent-harness-spike-report/v2"] = "agent-harness-spike-report/v2"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})
    spike_spec_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    transcript_hash: str = Field(pattern=SHA256_PATTERN)
    checks: tuple[HarnessCapabilityCheck, ...]
    decision: HarnessDecision
    limitations: tuple[str, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_is_aware_v2(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("spike report timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def decision_matches_checks_v2(self) -> Self:
        capabilities = [item.capability for item in self.checks]
        if capabilities != sorted(set(capabilities), key=str) or set(capabilities) != set(
            HarnessCapability
        ):
            raise ValueError("report must contain one sorted check per frozen capability")
        if (self.decision is HarnessDecision.GO) != all(item.passed for item in self.checks):
            raise ValueError("harness decision does not match hard capability checks")
        return self
