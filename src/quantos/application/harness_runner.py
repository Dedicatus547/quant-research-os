"""Frozen, non-interactive Codex SDK runner for the P10 synthetic spike."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from quantos.application.agent_harness import (
    capture_from_agent_events,
    parse_agent_events,
)
from quantos.application.harness_spike import (
    CodexExecCapture,
    build_harness_spike_report_v3,
    build_p10_capability_observation_v2,
)
from quantos.artifacts.store import atomic_write_bytes, publish_directory, regular_tree_files
from quantos.contracts.agent import (
    AgentCapability,
    AgentCapabilityPolicy,
    AgentRole,
    AgentRunManifest,
    AgentRunManifestV2,
    AgentRunManifestV3,
    AgentRunSpec,
    AgentRunSpecV3,
    AgentUsage,
    HarnessAttemptRecord,
    ToolInteractionDigest,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    CodexHarnessSpikeReport,
    CodexHarnessSpikeSpec,
    HarnessCapability,
    HarnessCapabilityObservationV2,
    HarnessCapabilitySpikeReportV2,
    HarnessCapabilitySpikeReportV3,
    HarnessCapabilitySpikeSpecV3,
    HarnessDecision,
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessMcpServer,
    HarnessRuntimeIdentityV2,
    HarnessRuntimePolicy,
    HarnessTerminalError,
)
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.integrations.codex.event_normalizer import (
    NORMALIZER_IDENTIFIER,
    normalize_provider_events,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.integrations.codex.versioning import (
    CODEX_PROTOCOL_IDENTIFIER,
    CODEX_RUNTIME_DISTRIBUTION,
    CODEX_RUNTIME_PACKAGE_VERSION,
    CODEX_SDK_DISTRIBUTION,
    CODEX_SDK_VERSION,
)

CODEX_CLI_VERSION = "codex-cli 0.153.4"
MODEL_IDENTIFIER = "gpt-5.6-sol"
MODEL_REASONING_EFFORT = "medium"
SYNTHETIC_SECRET_MARKER = "p10-synthetic-parent-marker-20260907"
MAX_TRANSCRIPT_BYTES = 2_000_000
MAX_INPUT_TOKENS = 250_000
MAX_OUTPUT_TOKENS = 4_096
TIMEOUT_SECONDS = 900
_SHELL_ENVIRONMENT = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}


class HarnessRunnerError(RuntimeError):
    """Raised when the frozen harness invocation itself cannot be executed safely."""


class P10ArtifactVerificationError(HarnessRunnerError):
    """Raised when a retained Code Mode-aware P10 artifact cannot be replayed exactly."""


@dataclass(frozen=True)
class FrozenSpikeInputs:
    fixture_root: Path
    agents_hash: str
    skill_hash: str
    task_hash: str
    dataset_hash: str
    mcp_server_hash: str
    mcp_tool_schema_hash: str
    output_schema_hash: str
    manual_baseline_hash: str
    write_probe_hash: str
    manual_baseline: Mapping[str, object]
    task_text: str

    @property
    def instruction_hashes(self) -> tuple[str, ...]:
        return tuple(sorted((self.agents_hash, self.skill_hash, self.task_hash)))

    @property
    def all_input_hashes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.agents_hash,
                    self.skill_hash,
                    self.task_hash,
                    self.dataset_hash,
                    self.mcp_server_hash,
                    self.mcp_tool_schema_hash,
                    self.output_schema_hash,
                    self.manual_baseline_hash,
                    self.write_probe_hash,
                }
            )
        )


@dataclass(frozen=True)
class HarnessRunResult:
    report: (
        CodexHarnessSpikeReport | HarnessCapabilitySpikeReportV2 | HarnessCapabilitySpikeReportV3
    )
    manifest: AgentRunManifest | AgentRunManifestV2 | AgentRunManifestV3
    report_path: Path
    manifest_path: Path
    spec_path: Path
    transcript_path: Path
    process_return_code: int


def load_frozen_spike_inputs(fixture_root: Path) -> FrozenSpikeInputs:
    """Load the exact regular-file set that constitutes the frozen P10 task."""

    if fixture_root.is_symlink():
        raise HarnessRunnerError("frozen P10 fixture root cannot be a symbolic link")
    root = fixture_root.resolve(strict=True)
    paths = {
        "agents": root / "AGENTS.md",
        "skill": root / ".agents/skills/quantos-p10-probe/SKILL.md",
        "task": root / "task.md",
        "dataset": root / "dataset.json",
        "mcp_server": root / "mock_mcp_server.py",
        "mcp_tool_schema": root / "mcp_tool.schema.json",
        "output_schema": root / "output.schema.json",
        "manual_baseline": root / "manual_baseline.json",
        "write_probe": root / "write_probe.py",
    }
    payloads: dict[str, bytes] = {}
    expected_paths = {path.relative_to(root) for path in paths.values()}
    actual_paths: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise HarnessRunnerError("frozen P10 fixture contains a symbolic link")
        if path.is_file():
            actual_paths.add(path.relative_to(root))
        elif not path.is_dir():
            raise HarnessRunnerError("frozen P10 fixture contains a non-regular object")
    if actual_paths != expected_paths:
        raise HarnessRunnerError("frozen P10 fixture file set does not match the specification")
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise HarnessRunnerError(f"frozen P10 input is not a regular file: {name}")
        payloads[name] = path.read_bytes()
    try:
        baseline = cast(object, json.loads(payloads["manual_baseline"]))
        task_text = payloads["task"].decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HarnessRunnerError("frozen P10 text input is invalid") from error
    if not isinstance(baseline, dict):
        raise HarnessRunnerError("frozen P10 manual baseline must be a JSON object")
    untyped_baseline = cast(Mapping[object, object], baseline)
    if not all(isinstance(key, str) for key in untyped_baseline):
        raise HarnessRunnerError("frozen P10 manual baseline must be a JSON object")
    return FrozenSpikeInputs(
        fixture_root=root,
        agents_hash=sha256_bytes(payloads["agents"]),
        skill_hash=sha256_bytes(payloads["skill"]),
        task_hash=sha256_bytes(payloads["task"]),
        dataset_hash=sha256_bytes(payloads["dataset"]),
        mcp_server_hash=sha256_bytes(payloads["mcp_server"]),
        mcp_tool_schema_hash=sha256_bytes(payloads["mcp_tool_schema"]),
        output_schema_hash=sha256_bytes(payloads["output_schema"]),
        manual_baseline_hash=sha256_bytes(payloads["manual_baseline"]),
        write_probe_hash=sha256_bytes(payloads["write_probe"]),
        manual_baseline=cast(Mapping[str, object], untyped_baseline),
        task_text=task_text,
    )


def capability_policy() -> AgentCapabilityPolicy:
    return AgentCapabilityPolicy(
        policy_id="p10-codex-synthetic-read-only",
        capabilities=(AgentCapability.DATASET_DESCRIBE,),
        max_payload_bytes=64_000,
        max_payload_depth=8,
        max_payload_nodes=1_000,
        max_string_bytes=16_000,
        max_requests=1,
        environment_allowlist=("LANG", "TZ"),
    )


def model_configuration_payload(inputs: FrozenSpikeInputs) -> dict[str, object]:
    return {
        "approval_policy": "never",
        "codex_cli_version": CODEX_CLI_VERSION,
        "command_network_allowed": False,
        "ephemeral": True,
        "ignore_user_config": True,
        "login_shell_allowed": False,
        "mcp": {
            "command": "/usr/bin/python3",
            "enabled_tools": ["dataset_describe"],
            "implementation_hash": inputs.mcp_server_hash,
            "required": True,
            "server": "quantosP10",
            "tool_schema_hash": inputs.mcp_tool_schema_hash,
        },
        "model_identifier": MODEL_IDENTIFIER,
        "model_reasoning_effort": MODEL_REASONING_EFFORT,
        "output_schema_hash": inputs.output_schema_hash,
        "sandbox_mode": "read-only",
        "shell_environment": _SHELL_ENVIRONMENT,
    }


def sdk_model_configuration_payload(inputs: FrozenSpikeInputs) -> dict[str, object]:
    """Requested SDK configuration without legacy CLI identity."""

    return {
        "adapter_identifier": "openai-codex-python-sdk",
        "approval_policy": "never",
        "command_network_allowed": False,
        "ephemeral": True,
        "ignore_user_config": True,
        "login_shell_allowed": False,
        "mcp": {
            "command": "/usr/bin/python3",
            "enabled_tools": ["dataset_describe"],
            "implementation_hash": inputs.mcp_server_hash,
            "required": True,
            "server": "quantosP10",
            "tool_schema_hash": inputs.mcp_tool_schema_hash,
        },
        "model_identifier": MODEL_IDENTIFIER,
        "model_reasoning_effort": MODEL_REASONING_EFFORT,
        "output_schema_hash": inputs.output_schema_hash,
        "protocol_identifier": CODEX_PROTOCOL_IDENTIFIER,
        "runtime_distribution": CODEX_RUNTIME_DISTRIBUTION,
        "runtime_package_version": CODEX_RUNTIME_PACKAGE_VERSION,
        "sandbox_mode": "read-only",
        "sdk_distribution": CODEX_SDK_DISTRIBUTION,
        "sdk_version": CODEX_SDK_VERSION,
        "shell_environment": _SHELL_ENVIRONMENT,
        "shell_tool_enabled": True,
    }


def build_spike_spec(inputs: FrozenSpikeInputs) -> CodexHarnessSpikeSpec:
    policy = capability_policy()
    return CodexHarnessSpikeSpec(
        spike_id="p10-gpt-codex-20260907",
        provider_model_identifier=MODEL_IDENTIFIER,
        model_reasoning_effort=MODEL_REASONING_EFFORT,
        codex_cli_version=CODEX_CLI_VERSION,
        shell_environment=tuple(_SHELL_ENVIRONMENT),
        capability_policy_hash=policy.content_hash,
        instruction_hashes=inputs.instruction_hashes,
        task_hash=inputs.task_hash,
        dataset_hash="a" * 64,
        mcp_server_hash=inputs.mcp_server_hash,
        mcp_tool_schema_hash=inputs.mcp_tool_schema_hash,
        output_schema_hash=inputs.output_schema_hash,
        manual_baseline_hash=inputs.manual_baseline_hash,
        write_probe_hash=inputs.write_probe_hash,
        required_capabilities=tuple(sorted(HarnessCapability, key=str)),
        max_transcript_bytes=MAX_TRANSCRIPT_BYTES,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )


def build_agent_manifest(
    *,
    inputs: FrozenSpikeInputs,
    spec: CodexHarnessSpikeSpec,
    capture: CodexExecCapture,
    process_return_code: int,
    started_at: datetime,
    completed_at: datetime,
) -> AgentRunManifest:
    configuration = model_configuration_payload(inputs)
    configuration_hash = sha256_bytes(canonical_json_bytes(configuration))
    run_spec = AgentRunSpec(
        run_id="p10-codex-synthetic-run",
        role=AgentRole.RESEARCHER,
        capability_policy_hash=spec.capability_policy_hash,
        campaign_hash=sha256_bytes(canonical_json_bytes({"spike_spec": spec.content_hash})),
        requested_model_configuration_hash=configuration_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        input_artifact_hashes=inputs.all_input_hashes,
    )
    interactions = tuple(
        ToolInteractionDigest(
            sequence=index,
            capability=AgentCapability.DATASET_DESCRIBE,
            request_hash=sha256_bytes(canonical_json_bytes(call.arguments)),
            response_hash=(
                sha256_bytes(canonical_json_bytes(call.result))
                if call.status == "completed" and call.error is None and call.result is not None
                else None
            ),
            succeeded=(
                call.status == "completed" and call.error is None and call.result is not None
            ),
        )
        for index, call in enumerate(capture.mcp_calls, start=1)
    )
    output_hashes: tuple[str, ...] = ()
    execution_succeeded = (
        process_return_code == 0
        and capture.turn_started
        and capture.turn_completed
        and not capture.turn_failed
        and bool(capture.agent_messages)
    )
    if execution_succeeded:
        output_hashes = (sha256_bytes(capture.agent_messages[-1].encode("utf-8")),)
    usage = AgentUsage(
        input_tokens=capture.usage.get("input_tokens", 0),
        output_tokens=capture.usage.get("output_tokens", 0),
        cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
        tool_calls=len(interactions),
        retry_count=0,
    )
    return AgentRunManifest(
        run_spec_hash=run_spec.content_hash,
        provider_thread_id=(capture.thread_ids[-1] if capture.thread_ids else "UNAVAILABLE"),
        provider_model_identifier=MODEL_IDENTIFIER,
        model_snapshot_immutable=False,
        model_configuration_hash=configuration_hash,
        harness_identifier=CODEX_CLI_VERSION,
        sandbox_policy_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "command_network_allowed": False,
                    "login_shell_allowed": False,
                    "mode": "read-only",
                }
            )
        ),
        permission_policy_hash=sha256_bytes(canonical_json_bytes({"approval_policy": "never"})),
        runtime_policy_hash=sha256_bytes(
            canonical_json_bytes(
                {"shell_environment": _SHELL_ENVIRONMENT, "timeout_seconds": TIMEOUT_SECONDS}
            )
        ),
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        interactions=interactions,
        input_hashes=inputs.all_input_hashes,
        output_proposal_hashes=output_hashes,
        transcript_hash=capture.transcript_hash,
        usage=usage,
        run_status=RunStatus.SUCCEEDED if execution_succeeded else RunStatus.FAILED,
        failure_reason_code=(None if execution_succeeded else ReasonCode.HARNESS_EXECUTION_FAILED),
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE", "SYNTHETIC_CAPABILITY_SPIKE"),
        started_at=started_at,
        completed_at=completed_at,
    )


def publish_run_artifacts(
    output_root: Path,
    *,
    transcript: bytes,
    spec: CodexHarnessSpikeSpec,
    manifest: AgentRunManifest,
    report: CodexHarnessSpikeReport,
) -> tuple[Path, Path, Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".p10-", dir=output_root))
    destination = output_root / f"sha256-{report.content_hash}"
    try:
        transcript_path = staging / "codex-events.jsonl"
        manifest_path = staging / "agent-run-manifest.json"
        spec_path = staging / "harness-spike-spec.json"
        report_path = staging / "harness-spike-report.json"
        atomic_write_bytes(transcript_path, transcript, expected_sha256=report.transcript_hash)
        atomic_write_bytes(manifest_path, manifest.canonical_bytes())
        atomic_write_bytes(spec_path, spec.canonical_bytes(), expected_sha256=spec.content_hash)
        atomic_write_bytes(report_path, canonical_json_bytes(report))
        publish_directory(staging, destination)
    except Exception:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()
        raise
    return (
        destination / "harness-spike-report.json",
        destination / "agent-run-manifest.json",
        destination / "harness-spike-spec.json",
        destination / "codex-events.jsonl",
    )


def execute_codex_spike(fixture_root: Path, output_root: Path) -> HarnessRunResult:
    """Execute the canonical P10 path through the isolated official SDK adapter."""

    inputs = load_frozen_spike_inputs(fixture_root)
    request = _sdk_request(inputs)
    spec = _sdk_spike_spec(inputs, request)
    run_spec = _sdk_run_spec(inputs, request, spec)
    started_at = datetime.now(UTC)
    previous_secret = os.environ.get("P10_FORBIDDEN_SECRET")
    os.environ["P10_FORBIDDEN_SECRET"] = SYNTHETIC_SECRET_MARKER
    try:
        execution = CodexSdkAdapter().execute(request)
    finally:
        if previous_secret is None:
            os.environ.pop("P10_FORBIDDEN_SECRET", None)
        else:
            os.environ["P10_FORBIDDEN_SECRET"] = previous_secret
    completed_at = datetime.now(UTC)
    capture = execution.capture
    proposal_hash = (
        sha256_bytes(capture.agent_messages[-1].encode("utf-8"))
        if (
            execution.terminal_error is None
            and capture.turn_completed
            and not capture.turn_failed
            and capture.agent_messages
        )
        else None
    )
    calls = tuple(call for attempt in execution.attempts for call in attempt.capture.tool_calls)
    interactions = tuple(
        ToolInteractionDigest(
            sequence=index,
            capability=AgentCapability.DATASET_DESCRIBE,
            request_hash=sha256_bytes(canonical_json_bytes(call.arguments)),
            response_hash=(
                sha256_bytes(canonical_json_bytes(call.result))
                if call.status == "completed" and call.error is None and call.result is not None
                else None
            ),
            succeeded=call.status == "completed" and call.error is None and call.result is not None,
        )
        for index, call in enumerate(calls, start=1)
    )
    aggregate_usage = AgentUsage(
        input_tokens=sum(item.capture.usage.get("input_tokens", 0) for item in execution.attempts),
        output_tokens=sum(
            item.capture.usage.get("output_tokens", 0) for item in execution.attempts
        ),
        cached_input_tokens=sum(
            item.capture.usage.get("cached_input_tokens", 0) for item in execution.attempts
        ),
        tool_calls=len(interactions),
        retry_count=len(execution.attempts) - 1,
    )
    runtime = execution.runtime
    terminal = execution.terminal_error
    provider_transcript_hash = (
        sha256_bytes(execution.provider_transcript)
        if execution.provider_transcript is not None
        else None
    )
    observation = build_p10_capability_observation_v2(
        capture,
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_transcript_hash,
    )
    if terminal is None and proposal_hash is None:
        terminal = HarnessTerminalError(
            kind=HarnessErrorKind.OUTPUT_INVALID,
            message_hash=sha256_bytes(b"P10 normalized output has no proposal"),
        )
    manifest = AgentRunManifestV3(
        run_spec_hash=run_spec.content_hash,
        provider_model_identifier=MODEL_IDENTIFIER,
        sdk_version=runtime.sdk_version if runtime else None,
        runtime_package_version=(
            runtime.runtime_package_version
            if isinstance(runtime, HarnessRuntimeIdentityV2)
            else None
        ),
        runtime_version=runtime.runtime_version if runtime else None,
        runtime_binary_hash=(
            runtime.runtime_binary_hash if isinstance(runtime, HarnessRuntimeIdentityV2) else None
        ),
        protocol_identifier=CODEX_PROTOCOL_IDENTIFIER,
        normalizer_identifier=NORMALIZER_IDENTIFIER,
        normalizer_hash=_normalizer_hash(),
        requested_policy_hash=request.runtime_policy.content_hash,
        resolved_runtime_config_hash=None,
        capability_observation_hash=observation.content_hash,
        attested_policy_hash=None,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        interactions=interactions,
        input_hashes=inputs.all_input_hashes,
        output_proposal_hashes=((proposal_hash,) if proposal_hash else ()),
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_transcript_hash,
        provider_transcript_retention_reason=(
            None if execution.provider_transcript is not None else "SDK_HOST_UNAVAILABLE"
        ),
        attempts=tuple(
            HarnessAttemptRecord(
                attempt_index=item.capture.attempt_index,
                provider_thread_id=(
                    item.capture.thread_ids[-1] if item.capture.thread_ids else None
                ),
                event_stream_hash=item.capture.transcript_hash,
                usage=AgentUsage(
                    input_tokens=item.capture.usage.get("input_tokens", 0),
                    output_tokens=item.capture.usage.get("output_tokens", 0),
                    cached_input_tokens=item.capture.usage.get("cached_input_tokens", 0),
                    tool_calls=len(item.capture.tool_calls),
                    retry_count=0,
                ),
                terminal_error_kind=(
                    item.terminal_error.kind.value
                    if item.terminal_error
                    else (
                        terminal.kind.value if item is execution.attempts[-1] and terminal else None
                    )
                ),
                terminal_error_message_hash=(
                    item.terminal_error.message_hash
                    if item.terminal_error
                    else (
                        terminal.message_hash
                        if item is execution.attempts[-1] and terminal
                        else None
                    )
                ),
                error_retryable=(item.terminal_error.retryable if item.terminal_error else False),
                produced_proposal_hash=(proposal_hash if item is execution.attempts[-1] else None),
                started_at=started_at,
                completed_at=completed_at,
            )
            for item in execution.attempts
        ),
        aggregate_usage=aggregate_usage,
        run_status=RunStatus.SUCCEEDED if terminal is None else RunStatus.FAILED,
        failure_reason_code=(None if terminal is None else _failure_reason(terminal)),
        limitations=(
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "SYNTHETIC_CAPABILITY_SPIKE",
        ),
        started_at=started_at,
        completed_at=completed_at,
    )
    report = build_harness_spike_report_v3(
        spec,
        manifest,
        capture,
        inputs.manual_baseline,
        created_at=completed_at,
    )
    report_path, manifest_path, spec_path, transcript_path = _publish_sdk_run_artifacts(
        output_root,
        request=request,
        provider_transcript=execution.provider_transcript,
        spec=spec,
        manifest=manifest,
        observation=observation,
        report=report,
        transcript=execution.normalized_transcript,
        run_spec=run_spec,
    )
    del report_path, manifest_path, spec_path, transcript_path
    return verify_codex_spike_artifact(
        output_root / f"sha256-{report.content_hash}", inputs.fixture_root
    )


def _sdk_spike_spec(
    inputs: FrozenSpikeInputs, request: HarnessExecutionRequest
) -> HarnessCapabilitySpikeSpecV3:
    return HarnessCapabilitySpikeSpecV3(
        spike_id="p10-codex-sdk-code-mode-20260922",
        execution_request_hash=request.content_hash,
        parent_secret_marker_hash=sha256_bytes(SYNTHETIC_SECRET_MARKER.encode("utf-8")),
        dataset_hash="a" * 64,
        mcp_server_name="quantosP10",
        mcp_tool_name="dataset_describe",
        max_transcript_bytes=request.max_transcript_bytes,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        required_capabilities=tuple(sorted(HarnessCapability, key=str)),
        input_hashes=inputs.all_input_hashes,
    )


def _sdk_request(inputs: FrozenSpikeInputs) -> HarnessExecutionRequest:
    environment = tuple(
        HarnessEnvironmentVariable(name=cast(Any, name), value=value)
        for name, value in sorted(_SHELL_ENVIRONMENT.items())
    )
    return HarnessExecutionRequest(
        run_id="p10-codex-sdk-code-mode-20260922",
        cwd=str(inputs.fixture_root),
        prompt=inputs.task_text,
        model=MODEL_IDENTIFIER,
        reasoning_effort=MODEL_REASONING_EFFORT,
        runtime_policy=HarnessRuntimePolicy(
            host_environment=environment,
            child_environment=environment,
            shell_environment=environment,
            shell_tool_enabled=True,
        ),
        mcp_servers=(
            HarnessMcpServer(
                name="quantosP10",
                command="/usr/bin/python3",
                args=(str(inputs.fixture_root / "mock_mcp_server.py"),),
                enabled_tools=("dataset_describe",),
                implementation_hash=inputs.mcp_server_hash,
                tool_schema_hash=inputs.mcp_tool_schema_hash,
            ),
        ),
        output_schema_json=(inputs.fixture_root / "output.schema.json").read_text(encoding="utf-8"),
        timeout_seconds=TIMEOUT_SECONDS,
        total_timeout_seconds=TIMEOUT_SECONDS,
        max_transcript_bytes=MAX_TRANSCRIPT_BYTES,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )


def _sdk_run_spec(
    inputs: FrozenSpikeInputs,
    request: HarnessExecutionRequest,
    spike: HarnessCapabilitySpikeSpecV3,
) -> AgentRunSpecV3:
    configuration_hash = sha256_bytes(canonical_json_bytes(sdk_model_configuration_payload(inputs)))
    return AgentRunSpecV3(
        run_id="p10-codex-sdk-code-mode-20260922",
        role=AgentRole.RESEARCHER,
        capability_policy_hash=capability_policy().content_hash,
        campaign_hash=sha256_bytes(canonical_json_bytes({"spike_spec": spike.content_hash})),
        requested_model_configuration_hash=configuration_hash,
        requested_runtime_policy_hash=request.runtime_policy.content_hash,
        transcript_policy_hash=sha256_bytes(
            canonical_json_bytes({"max_bytes": request.max_transcript_bytes, "retain": True})
        ),
        retry_budget_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "max_attempts": request.max_attempts,
                    "retry_backoff_milliseconds": request.retry_backoff_milliseconds,
                    "total_timeout_seconds": request.total_timeout_seconds,
                }
            )
        ),
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        input_artifact_hashes=inputs.all_input_hashes,
    )


def _normalizer_hash() -> str:
    module_path = Path(__file__).parents[1] / "integrations/codex/event_normalizer.py"
    return sha256_bytes(module_path.read_bytes())


def _failure_reason(error: object) -> str:
    if error is None:
        return ReasonCode.HARNESS_OUTPUT_INVALID.value
    kind = cast(Any, error).kind.value
    mapping = {
        "AUTH_UNAVAILABLE": ReasonCode.HARNESS_AUTH_UNAVAILABLE,
        "CONFIGURATION_INVALID": ReasonCode.HARNESS_CONFIGURATION_INVALID,
        "INTERRUPTED": ReasonCode.HARNESS_INTERRUPTED,
        "MCP_FAILED": ReasonCode.HARNESS_MCP_FAILED,
        "OUTPUT_INVALID": ReasonCode.HARNESS_OUTPUT_INVALID,
        "OVERLOADED": ReasonCode.HARNESS_OVERLOADED,
        "PERMISSION_DENIED": ReasonCode.HARNESS_PERMISSION_DENIED,
        "PROTOCOL_UNSUPPORTED": ReasonCode.HARNESS_PROTOCOL_UNSUPPORTED,
        "QUOTA_EXHAUSTED": ReasonCode.HARNESS_QUOTA_EXHAUSTED,
        "RUNTIME_MISMATCH": ReasonCode.HARNESS_RUNTIME_MISMATCH,
        "TIMEOUT": ReasonCode.HARNESS_TIMEOUT,
        "TRANSPORT_CLOSED": ReasonCode.HARNESS_TRANSPORT_FAILED,
        "TRANSPORT_START_FAILED": ReasonCode.HARNESS_TRANSPORT_FAILED,
    }
    return mapping.get(kind, ReasonCode.HARNESS_EXECUTION_FAILED).value


def _publish_sdk_run_artifacts(
    output_root: Path,
    *,
    request: HarnessExecutionRequest,
    provider_transcript: bytes | None,
    spec: HarnessCapabilitySpikeSpecV3,
    run_spec: AgentRunSpecV3,
    manifest: AgentRunManifestV3,
    observation: HarnessCapabilityObservationV2,
    report: HarnessCapabilitySpikeReportV3,
    transcript: bytes,
) -> tuple[Path, Path, Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".p10-sdk-", dir=output_root))
    destination = output_root / f"sha256-{report.content_hash}"
    try:
        atomic_write_bytes(staging / "agent-events.jsonl", transcript)
        atomic_write_bytes(staging / "agent-run-manifest.json", manifest.canonical_bytes())
        atomic_write_bytes(staging / "agent-run-spec.json", run_spec.canonical_bytes())
        atomic_write_bytes(
            staging / "harness-capability-observation.json", observation.canonical_bytes()
        )
        atomic_write_bytes(staging / "harness-request.json", request.canonical_bytes())
        atomic_write_bytes(staging / "harness-spike-spec.json", spec.canonical_bytes())
        atomic_write_bytes(staging / "harness-spike-report.json", canonical_json_bytes(report))
        if provider_transcript is not None:
            atomic_write_bytes(staging / "provider-events.jsonl", provider_transcript)
        publish_directory(staging, destination)
    finally:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()
    return (
        destination / "harness-spike-report.json",
        destination / "agent-run-manifest.json",
        destination / "harness-spike-spec.json",
        destination / "agent-events.jsonl",
    )


def verify_codex_spike_artifact(run_path: Path, fixture_root: Path) -> HarnessRunResult:
    """Replay a Code Mode-aware P10 bundle without SDK auth, network, or a model call."""

    required = {
        "agent-events.jsonl",
        "agent-run-manifest.json",
        "agent-run-spec.json",
        "harness-capability-observation.json",
        "harness-request.json",
        "harness-spike-report.json",
        "harness-spike-spec.json",
    }
    try:
        files = regular_tree_files(run_path)
        names = {path.relative_to(run_path).as_posix() for path in files}
        if names not in (required, required | {"provider-events.jsonl"}):
            raise P10ArtifactVerificationError("retained P10 file set is not exact")
        payloads = {path.name: path.read_bytes() for path in files}
        inputs = load_frozen_spike_inputs(fixture_root)
        request = HarnessExecutionRequest.model_validate_json(payloads["harness-request.json"])
        expected_request = _sdk_request(inputs)
        if payloads["harness-request.json"] != expected_request.canonical_bytes():
            raise P10ArtifactVerificationError("retained P10 request does not match frozen inputs")
        spec = HarnessCapabilitySpikeSpecV3.model_validate_json(payloads["harness-spike-spec.json"])
        expected_spec = _sdk_spike_spec(inputs, request)
        if payloads["harness-spike-spec.json"] != expected_spec.canonical_bytes():
            raise P10ArtifactVerificationError("retained P10 spec does not match frozen inputs")
        run_spec = AgentRunSpecV3.model_validate_json(payloads["agent-run-spec.json"])
        expected_run_spec = _sdk_run_spec(inputs, request, spec)
        if payloads["agent-run-spec.json"] != expected_run_spec.canonical_bytes():
            raise P10ArtifactVerificationError("retained P10 run spec is invalid")
        manifest = AgentRunManifestV3.model_validate_json(payloads["agent-run-manifest.json"])
        observation = HarnessCapabilityObservationV2.model_validate_json(
            payloads["harness-capability-observation.json"]
        )
        report = HarnessCapabilitySpikeReportV3.model_validate_json(
            payloads["harness-spike-report.json"]
        )
        events = parse_agent_events(
            payloads["agent-events.jsonl"], max_bytes=request.max_transcript_bytes
        )
        capture = capture_from_agent_events(events, max_bytes=request.max_transcript_bytes)
    except P10ArtifactVerificationError:
        raise
    except (OSError, ValueError, ValidationError) as error:
        raise P10ArtifactVerificationError("retained P10 artifact is malformed") from error

    _verify_p10_secret_absence(payloads)
    provider_payload = payloads.get("provider-events.jsonl")
    provider_hash = sha256_bytes(provider_payload) if provider_payload is not None else None
    if provider_hash != manifest.provider_transcript_hash:
        raise P10ArtifactVerificationError("provider transcript binding is invalid")
    if provider_payload is None:
        if manifest.provider_transcript_retention_reason is None:
            raise P10ArtifactVerificationError("provider transcript retention reason is missing")
    elif manifest.run_status is RunStatus.SUCCEEDED:
        provider_events = _parse_provider_event_jsonl(provider_payload)
        if len(manifest.attempts) != 1 or not capture.thread_ids:
            raise P10ArtifactVerificationError(
                "P10 provider replay requires one identified attempt"
            )
        replay = capture_from_agent_events(
            normalize_provider_events(provider_events, thread_id=capture.thread_ids[-1]),
            max_bytes=request.max_transcript_bytes,
        )
        if replay.transcript != payloads["agent-events.jsonl"]:
            raise P10ArtifactVerificationError("provider and normalized transcripts disagree")

    proposal_hash = (
        sha256_bytes(capture.agent_messages[-1].encode("utf-8")) if capture.agent_messages else None
    )
    interactions = tuple(
        ToolInteractionDigest(
            sequence=index,
            capability=AgentCapability.DATASET_DESCRIBE,
            request_hash=sha256_bytes(canonical_json_bytes(call.arguments)),
            response_hash=(
                sha256_bytes(canonical_json_bytes(call.result))
                if call.status == "completed" and call.error is None and call.result is not None
                else None
            ),
            succeeded=call.status == "completed" and call.error is None and call.result is not None,
        )
        for index, call in enumerate(capture.tool_calls, start=1)
    )
    usage = AgentUsage(
        input_tokens=capture.usage.get("input_tokens", 0),
        output_tokens=capture.usage.get("output_tokens", 0),
        cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
        tool_calls=len(interactions),
        retry_count=0,
    )
    expected_observation = build_p10_capability_observation_v2(
        capture,
        normalized_transcript_hash=sha256_bytes(payloads["agent-events.jsonl"]),
        provider_transcript_hash=provider_hash,
    )
    expected_report = build_harness_spike_report_v3(
        spec,
        manifest,
        capture,
        inputs.manual_baseline,
        created_at=report.created_at,
    )
    attempt = manifest.attempts[0] if len(manifest.attempts) == 1 else None
    if (
        run_path.name != f"sha256-{report.content_hash}"
        or manifest.run_spec_hash != run_spec.content_hash
        or manifest.provider_model_identifier != MODEL_IDENTIFIER
        or manifest.sdk_version not in (None, CODEX_SDK_VERSION)
        or manifest.runtime_package_version not in (None, CODEX_RUNTIME_PACKAGE_VERSION)
        or (
            manifest.runtime_version is not None
            and manifest.runtime_version.partition(" ")[0] != CODEX_RUNTIME_PACKAGE_VERSION
        )
        or manifest.requested_policy_hash != request.runtime_policy.content_hash
        or manifest.normalizer_identifier != NORMALIZER_IDENTIFIER
        or manifest.normalizer_hash != _normalizer_hash()
        or manifest.instruction_hashes != inputs.instruction_hashes
        or manifest.skill_hash != inputs.skill_hash
        or manifest.tool_schema_hash != inputs.mcp_tool_schema_hash
        or manifest.input_hashes != inputs.all_input_hashes
        or manifest.normalized_transcript_hash != sha256_bytes(payloads["agent-events.jsonl"])
        or manifest.capability_observation_hash != observation.content_hash
        or payloads["harness-capability-observation.json"] != expected_observation.canonical_bytes()
        or manifest.interactions != interactions
        or manifest.aggregate_usage != usage
        or attempt is None
        or attempt.event_stream_hash != capture.transcript_hash
        or attempt.usage != usage
        or attempt.provider_thread_id != (capture.thread_ids[-1] if capture.thread_ids else None)
        or attempt.produced_proposal_hash != proposal_hash
        or report.agent_run_manifest_hash != manifest.content_hash
        or payloads["harness-spike-report.json"] != canonical_json_bytes(expected_report)
    ):
        raise P10ArtifactVerificationError("retained P10 evidence does not replay exactly")
    return HarnessRunResult(
        report=report,
        manifest=manifest,
        report_path=run_path / "harness-spike-report.json",
        manifest_path=run_path / "agent-run-manifest.json",
        spec_path=run_path / "harness-spike-spec.json",
        transcript_path=run_path / "agent-events.jsonl",
        process_return_code=0 if report.decision is HarnessDecision.GO else 1,
    )


def _parse_provider_event_jsonl(payload: bytes) -> tuple[Mapping[str, object], ...]:
    events: list[Mapping[str, object]] = []
    try:
        lines = payload.splitlines()
        for line in lines:
            item = cast(object, json.loads(line))
            if not isinstance(item, dict):
                raise ValueError("provider event is not an object")
            mapping = cast(Mapping[object, object], item)
            if not all(isinstance(key, str) for key in mapping):
                raise ValueError("provider event key is invalid")
            events.append(cast(Mapping[str, object], mapping))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise P10ArtifactVerificationError("provider transcript is invalid JSONL") from error
    if not events:
        raise P10ArtifactVerificationError("provider transcript is empty")
    return tuple(events)


def _verify_p10_secret_absence(payloads: Mapping[str, bytes]) -> None:
    markers = [SYNTHETIC_SECRET_MARKER.encode("utf-8")]
    markers.extend(
        value.encode("utf-8")
        for name, value in os.environ.items()
        if value and (name == "P10_FORBIDDEN_SECRET" or name.startswith("TUSHARE_"))
    )
    if any(marker in payload for marker in markers for payload in payloads.values()):
        raise P10ArtifactVerificationError("retained P10 artifact contains a prohibited secret")


def safe_result_summary(result: HarnessRunResult) -> dict[str, object]:
    summary: dict[str, object] = {
        "agent_run_manifest_hash": result.manifest.content_hash,
        "decision": result.report.decision,
        "failed_capabilities": [
            check.capability for check in result.report.checks if not check.passed
        ],
        "process_return_code": result.process_return_code,
        "report_hash": result.report.content_hash,
        "report_path": str(result.report_path),
        "spike_spec_hash": result.report.spike_spec_hash,
        "transcript_hash": result.report.transcript_hash,
    }
    observation_path = result.report_path.parent / "harness-capability-observation.json"
    if observation_path.is_file() and not observation_path.is_symlink():
        try:
            observation = HarnessCapabilityObservationV2.model_validate_json(
                observation_path.read_bytes()
            )
        except (OSError, ValidationError):
            pass
        else:
            failed = {check.capability for check in result.report.checks if not check.passed}
            if result.manifest.run_status is RunStatus.FAILED:
                classification = "QUALIFICATION_NOT_EVALUATED"
            elif result.report.decision is HarnessDecision.GO:
                classification = "P10_SDK_QUALIFIED"
            elif observation.matched_command_count == 0:
                classification = "LIVE_EXEC_NOT_OBSERVED"
            elif (
                not observation.command_lifecycle_integrity or observation.matched_command_count < 4
            ):
                classification = "LIVE_CODE_MODE_PARTIAL"
            elif HarnessCapability.SANDBOX in failed:
                classification = "POLICY_NOT_ATTESTED"
            else:
                classification = "P10_CAPABILITY_FAILED"
            summary.update(
                {
                    "classification": classification,
                    "code_mode_exec_initiated": observation.code_mode_exec_initiated,
                    "command_lifecycle_integrity": observation.command_lifecycle_integrity,
                    "matched_command_count": observation.matched_command_count,
                    "nested_exec_command_dispatched": (observation.nested_exec_command_dispatched),
                }
            )
    return summary
