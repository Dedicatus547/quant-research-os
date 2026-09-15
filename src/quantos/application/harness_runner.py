"""Frozen, non-interactive Codex SDK runner for the P10 synthetic spike."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from quantos.application.harness_spike import (
    CodexExecCapture,
    build_harness_spike_report_v2,
)
from quantos.artifacts.store import atomic_write_bytes, publish_directory
from quantos.contracts.agent import (
    AgentCapability,
    AgentCapabilityPolicy,
    AgentRole,
    AgentRunManifest,
    AgentRunManifestV2,
    AgentRunSpec,
    AgentRunSpecV2,
    AgentUsage,
    HarnessAttemptRecord,
    ToolInteractionDigest,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    CodexHarnessSpikeReport,
    CodexHarnessSpikeSpec,
    HarnessCapability,
    HarnessCapabilitySpikeReportV2,
    HarnessCapabilitySpikeSpecV2,
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessMcpServer,
    HarnessRuntimePolicy,
    HarnessTerminalError,
)
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter

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
    report: CodexHarnessSpikeReport | HarnessCapabilitySpikeReportV2
    manifest: AgentRunManifest | AgentRunManifestV2
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
    spec = HarnessCapabilitySpikeSpecV2(
        spike_id="p10-codex-sdk-20260915",
        execution_request_hash=request.content_hash,
        dataset_hash="a" * 64,
        mcp_server_name="quantosP10",
        mcp_tool_name="dataset_describe",
        max_transcript_bytes=request.max_transcript_bytes,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        required_capabilities=tuple(sorted(HarnessCapability, key=str)),
        input_hashes=inputs.all_input_hashes,
    )
    run_spec = _sdk_run_spec(inputs, request, spec)
    started_at = datetime.now(UTC)
    execution = CodexSdkAdapter().execute(request)
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
    if terminal is None and proposal_hash is None:
        terminal = HarnessTerminalError(
            kind=HarnessErrorKind.OUTPUT_INVALID,
            message_hash=sha256_bytes(b"P10 normalized output has no proposal"),
        )
    manifest = AgentRunManifestV2(
        run_spec_hash=run_spec.content_hash,
        provider_model_identifier=MODEL_IDENTIFIER,
        sdk_version=runtime.sdk_version if runtime else None,
        runtime_version=runtime.runtime_version if runtime else None,
        normalizer_hash=_normalizer_hash(),
        requested_policy_hash=request.runtime_policy.content_hash,
        effective_policy_hash=request.runtime_policy.content_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        interactions=interactions,
        input_hashes=inputs.all_input_hashes,
        output_proposal_hashes=((proposal_hash,) if proposal_hash else ()),
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=(
            sha256_bytes(execution.provider_transcript)
            if execution.provider_transcript is not None
            else None
        ),
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
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE", "SYNTHETIC_CAPABILITY_SPIKE"),
        started_at=started_at,
        completed_at=completed_at,
    )
    report = build_harness_spike_report_v2(
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
        report=report,
        transcript=execution.normalized_transcript,
        run_spec=run_spec,
    )
    return HarnessRunResult(
        report=report,
        manifest=manifest,
        report_path=report_path,
        manifest_path=manifest_path,
        spec_path=spec_path,
        transcript_path=transcript_path,
        process_return_code=0 if terminal is None else 1,
    )


def _sdk_request(inputs: FrozenSpikeInputs) -> HarnessExecutionRequest:
    environment = tuple(
        HarnessEnvironmentVariable(name=cast(Any, name), value=value)
        for name, value in sorted(_SHELL_ENVIRONMENT.items())
    )
    return HarnessExecutionRequest(
        run_id="p10-codex-sdk-20260915",
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
    spike: HarnessCapabilitySpikeSpecV2,
) -> AgentRunSpecV2:
    configuration_hash = sha256_bytes(canonical_json_bytes(model_configuration_payload(inputs)))
    return AgentRunSpecV2(
        run_id="p10-codex-sdk-20260915",
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
    spec: HarnessCapabilitySpikeSpecV2,
    run_spec: AgentRunSpecV2,
    manifest: AgentRunManifestV2,
    report: HarnessCapabilitySpikeReportV2,
    transcript: bytes,
) -> tuple[Path, Path, Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".p10-sdk-", dir=output_root))
    destination = output_root / f"sha256-{report.content_hash}"
    try:
        atomic_write_bytes(staging / "agent-events.jsonl", transcript)
        atomic_write_bytes(staging / "agent-run-manifest.json", manifest.canonical_bytes())
        atomic_write_bytes(staging / "agent-run-spec.json", run_spec.canonical_bytes())
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


def safe_result_summary(result: HarnessRunResult) -> dict[str, object]:
    return {
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
