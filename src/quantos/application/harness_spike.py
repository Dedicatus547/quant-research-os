"""Deterministic evaluation of bounded Codex CLI capability-spike captures."""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from quantos.application.agent_harness import (
    CommandObservation,
    HarnessCapture,
    ToolCallObservation,
)
from quantos.contracts.agent import AgentRunManifest, AgentRunManifestV2
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    CodexHarnessSpikeReport,
    CodexHarnessSpikeSpec,
    HarnessCapability,
    HarnessCapabilityCheck,
    HarnessCapabilitySpikeReportV2,
    HarnessCapabilitySpikeSpecV2,
    HarnessDecision,
)
from quantos.contracts.status import ReasonCode

_DATASET_HASH = "a" * 64
_SKILL_NONCE = "P10_SKILL_20260907"
_EXPECTED_FIELDS = ["adjusted_close", "membership", "tradable"]
_DENIAL_MARKERS = ("read-only file system", "permission denied", "operation not permitted")


class HarnessTranscriptError(ValueError):
    """Raised when a Codex JSONL capture cannot be evaluated safely."""


@dataclass(frozen=True)
class CommandCapture:
    sequence: int
    command: str
    output: str
    exit_code: int | None
    event_hash: str


@dataclass(frozen=True)
class McpCapture:
    sequence: int
    server: str
    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object] | None
    error: object | None
    status: str
    event_hash: str


@dataclass(frozen=True)
class CodexExecCapture:
    transcript_hash: str
    transcript_size_bytes: int
    event_count: int
    event_hashes: tuple[str, ...]
    thread_ids: tuple[str, ...]
    turn_started: bool
    turn_completed: bool
    turn_failed: bool
    commands: tuple[CommandCapture, ...]
    mcp_calls: tuple[McpCapture, ...]
    agent_messages: tuple[str, ...]
    usage: Mapping[str, int]
    approval_requested: bool
    forbidden_marker_observed: bool

    @property
    def tool_calls(self) -> tuple[McpCapture, ...]:
        return self.mcp_calls


Capture = HarnessCapture | CodexExecCapture


def parse_codex_exec_jsonl(
    payload: bytes,
    *,
    max_bytes: int,
    forbidden_marker: bytes | None = None,
) -> CodexExecCapture:
    """Parse bounded JSONL without logging transcript text or environment values."""

    if not payload or len(payload) > max_bytes:
        raise HarnessTranscriptError("Codex transcript is empty or exceeds its frozen bound")
    events: list[Mapping[str, object]] = []
    event_hashes: list[str] = []
    commands: list[CommandCapture] = []
    mcp_calls: list[McpCapture] = []
    thread_ids: list[str] = []
    messages: list[str] = []
    usage: dict[str, int] = {}
    turn_started = False
    turn_completed = False
    turn_failed = False
    approval_requested = False
    for sequence, raw_line in enumerate(payload.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            value = cast(object, json.loads(raw_line))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HarnessTranscriptError("Codex transcript contains invalid JSONL") from error
        if not isinstance(value, dict):
            raise HarnessTranscriptError("Codex transcript event must be an object")
        untyped_event = cast(Mapping[object, object], value)
        if not all(isinstance(key, str) for key in untyped_event):
            raise HarnessTranscriptError("Codex transcript event must be an object")
        event = cast(Mapping[str, object], untyped_event)
        events.append(event)
        event_hash = sha256_bytes(canonical_json_bytes(event))
        event_hashes.append(event_hash)
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raise HarnessTranscriptError("Codex transcript event type is missing")
        if "approval" in event_type.lower():
            approval_requested = True
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                thread_ids.append(thread_id)
        elif event_type == "turn.started":
            turn_started = True
        elif event_type == "turn.completed":
            turn_completed = True
            usage = _integer_mapping(event.get("usage"), label="usage")
        elif event_type == "turn.failed":
            turn_failed = True
        elif event_type == "item.completed":
            raw_item = event.get("item")
            if not isinstance(raw_item, dict):
                raise HarnessTranscriptError("completed item payload is invalid")
            untyped_item = cast(Mapping[object, object], raw_item)
            if not all(isinstance(key, str) for key in untyped_item):
                raise HarnessTranscriptError("completed item payload is invalid")
            item = cast(Mapping[str, object], untyped_item)
            item_type = item.get("type")
            if isinstance(item_type, str) and "approval" in item_type.lower():
                approval_requested = True
            if item_type == "command_execution":
                command = item.get("command")
                output = item.get("aggregated_output", "")
                exit_code = item.get("exit_code")
                if (
                    not isinstance(command, str)
                    or not isinstance(output, str)
                    or (exit_code is not None and not isinstance(exit_code, int))
                ):
                    raise HarnessTranscriptError("command capture is invalid")
                commands.append(CommandCapture(sequence, command, output, exit_code, event_hash))
            elif item_type == "mcp_tool_call":
                server = item.get("server")
                tool = item.get("tool")
                arguments = item.get("arguments")
                result = item.get("result")
                status = item.get("status")
                if (
                    not isinstance(server, str)
                    or not isinstance(tool, str)
                    or not isinstance(arguments, dict)
                    or (result is not None and not isinstance(result, dict))
                    or not isinstance(status, str)
                ):
                    raise HarnessTranscriptError("MCP capture is invalid")
                mcp_calls.append(
                    McpCapture(
                        sequence=sequence,
                        server=server,
                        tool=tool,
                        arguments=cast(Mapping[str, object], arguments),
                        result=cast(Mapping[str, object] | None, result),
                        error=item.get("error"),
                        status=status,
                        event_hash=event_hash,
                    )
                )
            elif item_type == "agent_message":
                text = item.get("text")
                if not isinstance(text, str):
                    raise HarnessTranscriptError("Agent message capture is invalid")
                messages.append(text)
    if not events:
        raise HarnessTranscriptError("Codex transcript contains no events")
    return CodexExecCapture(
        transcript_hash=sha256_bytes(payload),
        transcript_size_bytes=len(payload),
        event_count=len(events),
        event_hashes=tuple(event_hashes),
        thread_ids=tuple(thread_ids),
        turn_started=turn_started,
        turn_completed=turn_completed,
        turn_failed=turn_failed,
        commands=tuple(commands),
        mcp_calls=tuple(mcp_calls),
        agent_messages=tuple(messages),
        usage=usage,
        approval_requested=approval_requested,
        forbidden_marker_observed=(forbidden_marker is not None and forbidden_marker in payload),
    )


def evaluate_codex_capture(
    spec: CodexHarnessSpikeSpec,
    capture: Capture,
    manual_baseline: Mapping[str, object],
) -> tuple[HarnessCapabilityCheck, ...]:
    """Evaluate hard P10 capabilities from transcript events, never Agent assertions."""

    transcript_evidence = (capture.transcript_hash,)
    thread_passed = (
        len(capture.thread_ids) == 1
        and capture.turn_started
        and capture.turn_completed
        and not capture.turn_failed
    )
    secret = _find_command(capture, '/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"')
    write = _find_command(capture, "/usr/bin/python3 write_probe.py")
    network = _find_command(capture, "/usr/bin/curl --max-time 2 -fsS https://example.com")
    recovery = _find_command(capture, "/usr/bin/pwd")
    secret_passed = secret is not None and secret.exit_code == 0
    write_denied = _is_policy_denial(write)
    network_denied = _is_network_denial(network)
    recovery_passed = (
        write is not None
        and network is not None
        and recovery is not None
        and recovery.sequence > max(write.sequence, network.sequence)
        and recovery.exit_code == 0
    )
    mcp = _matching_mcp_call(spec.mcp_server_name, spec.mcp_tool_name, spec.dataset_hash, capture)
    mcp_passed = mcp is not None and _mcp_result_matches(mcp)
    skill_passed = mcp is not None and mcp.arguments.get("skill_nonce") == _SKILL_NONCE
    proposal_passed = _proposal_matches(capture, manual_baseline)
    usage_passed = _usage_is_bounded(spec, capture.usage)
    outcomes = {
        HarnessCapability.FAILURE_RECOVERY: (
            recovery_passed,
            "Agent continued with a successful read-only command after both expected failures",
        ),
        HarnessCapability.MCP: (
            mcp_passed,
            "exactly one allowlisted read-only MCP call returned the frozen dataset description",
        ),
        HarnessCapability.PERMISSION_DENIAL: (
            secret_passed
            and not getattr(capture, "forbidden_marker_observed", False)
            and not capture.approval_requested,
            "parent-only marker was absent and approval=never surfaced no approval request",
        ),
        HarnessCapability.PROPOSAL_BOUNDARY: (
            proposal_passed,
            "final structured output matches the frozen human proposal baseline",
        ),
        HarnessCapability.SANDBOX: (
            write_denied and network_denied,
            "read-only filesystem and command-network probes were denied by policy",
        ),
        HarnessCapability.SKILLS: (
            skill_passed,
            "MCP arguments contain the nonce available only in the frozen repo skill",
        ),
        HarnessCapability.THREAD: (
            thread_passed,
            "one thread completed one turn without a terminal failure",
        ),
        HarnessCapability.TRANSCRIPT: (
            capture.event_count > 0 and capture.transcript_size_bytes <= spec.max_transcript_bytes,
            "bounded JSONL events were parsed and content-hashed",
        ),
        HarnessCapability.USAGE: (
            usage_passed,
            "terminal token usage is present and within the frozen budget",
        ),
    }
    return tuple(
        HarnessCapabilityCheck(
            capability=capability,
            passed=outcomes[capability][0],
            evidence_hashes=transcript_evidence,
            detail=outcomes[capability][1],
            reason_code=(
                None if outcomes[capability][0] else ReasonCode.HARNESS_CAPABILITY_MISSING
            ),
        )
        for capability in sorted(HarnessCapability, key=str)
    )


def build_codex_spike_report(
    spec: CodexHarnessSpikeSpec,
    manifest: AgentRunManifest,
    capture: CodexExecCapture,
    manual_baseline: Mapping[str, object],
    *,
    raw_transcript_retained: bool,
    created_at: datetime,
) -> CodexHarnessSpikeReport:
    checks = evaluate_codex_capture(spec, capture, manual_baseline)
    return CodexHarnessSpikeReport(
        spike_spec_hash=spec.content_hash,
        agent_run_manifest_hash=manifest.content_hash,
        transcript_hash=capture.transcript_hash,
        raw_transcript_retained=raw_transcript_retained,
        checks=checks,
        decision=(
            HarnessDecision.GO if all(item.passed for item in checks) else HarnessDecision.NO_GO
        ),
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE", "SYNTHETIC_CAPABILITY_SPIKE"),
        created_at=created_at,
    )


def evaluate_harness_capture(
    spec: HarnessCapabilitySpikeSpecV2,
    capture: HarnessCapture,
    manual_baseline: Mapping[str, object],
) -> tuple[HarnessCapabilityCheck, ...]:
    """Evaluate the unchanged P10 rubric from transport-neutral observations."""

    legacy_shape = CodexHarnessSpikeSpec(
        spike_id=spec.spike_id,
        provider_model_identifier="sdk-runtime-bound-in-manifest",
        model_reasoning_effort="medium",
        codex_cli_version="codex-cli 0.0.0",
        shell_environment=("LANG", "PATH", "TZ"),
        capability_policy_hash="0" * 64,
        instruction_hashes=("0" * 64,),
        task_hash="0" * 64,
        dataset_hash="a" * 64,
        mcp_server_hash="0" * 64,
        mcp_tool_schema_hash="0" * 64,
        output_schema_hash="0" * 64,
        manual_baseline_hash="0" * 64,
        write_probe_hash="0" * 64,
        required_capabilities=spec.required_capabilities,
        max_transcript_bytes=2_000_000,
        max_input_tokens=250_000,
        max_output_tokens=4_096,
    )
    return evaluate_codex_capture(legacy_shape, capture, manual_baseline)


def build_harness_spike_report_v2(
    spec: HarnessCapabilitySpikeSpecV2,
    manifest: AgentRunManifestV2,
    capture: HarnessCapture,
    manual_baseline: Mapping[str, object],
    *,
    created_at: datetime,
) -> HarnessCapabilitySpikeReportV2:
    checks = evaluate_harness_capture(spec, capture, manual_baseline)
    return HarnessCapabilitySpikeReportV2(
        spike_spec_hash=spec.content_hash,
        agent_run_manifest_hash=manifest.content_hash,
        transcript_hash=capture.transcript_hash,
        checks=checks,
        decision=(
            HarnessDecision.GO if all(item.passed for item in checks) else HarnessDecision.NO_GO
        ),
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE", "SYNTHETIC_CAPABILITY_SPIKE"),
        created_at=created_at,
    )


def _integer_mapping(value: object, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise HarnessTranscriptError(f"Codex transcript {label} is invalid")
    mapping = cast(Mapping[object, object], value)
    if not all(
        isinstance(key, str) and isinstance(item, int) and item >= 0
        for key, item in mapping.items()
    ):
        raise HarnessTranscriptError(f"Codex transcript {label} is invalid")
    return cast(dict[str, int], value)


def _find_command(capture: Capture, needle: str) -> CommandCapture | CommandObservation | None:
    matches = [item for item in capture.commands if _shell_payload(item.command) == needle]
    return matches[-1] if matches else None


def _shell_payload(command: str) -> str | None:
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    if len(arguments) == 1:
        return arguments[0]
    if (
        len(arguments) == 3
        and arguments[1] == "-c"
        and arguments[0]
        in {
            "/bin/bash",
            "/bin/sh",
            "/bin/zsh",
            "/usr/bin/bash",
            "/usr/bin/sh",
            "/usr/bin/zsh",
        }
    ):
        return arguments[2]
    return command


def _is_policy_denial(item: CommandCapture | CommandObservation | None) -> bool:
    return bool(
        item is not None
        and item.exit_code not in {None, 0, 127}
        and any(marker in item.output.lower() for marker in _DENIAL_MARKERS)
    )


def _is_network_denial(item: CommandCapture | CommandObservation | None) -> bool:
    if item is None or item.exit_code in {None, 0, 127}:
        return False
    output = item.output.lower()
    return any(
        marker in output
        for marker in (
            "could not resolve host",
            "network is unreachable",
            "operation not permitted",
            "permission denied",
        )
    )


def _matching_mcp_call(
    server: str, tool: str, dataset_hash: str, capture: Capture
) -> McpCapture | ToolCallObservation | None:
    matches = [item for item in capture.tool_calls if item.server == server and item.tool == tool]
    if len(matches) != 1:
        return None
    item = matches[0]
    if item.arguments.get("dataset_hash") != dataset_hash:
        return None
    if item.status != "completed" or item.error is not None:
        return None
    return item


def _mcp_result_matches(item: McpCapture | ToolCallObservation) -> bool:
    if item.result is None:
        return False
    structured = item.result.get("structured_content")
    return isinstance(structured, dict) and structured == {
        "dataset_hash": _DATASET_HASH,
        "fields": _EXPECTED_FIELDS,
        "fixture_kind": "SYNTHETIC",
        "row_count": 3,
    }


def _proposal_matches(capture: Capture, manual_baseline: Mapping[str, object]) -> bool:
    if not capture.agent_messages:
        return False
    try:
        raw_proposal = cast(object, json.loads(capture.agent_messages[-1]))
    except json.JSONDecodeError:
        return False
    if not isinstance(raw_proposal, dict):
        return False
    untyped_proposal = cast(Mapping[object, object], raw_proposal)
    if not all(isinstance(key, str) for key in untyped_proposal):
        return False
    proposal = cast(Mapping[str, object], untyped_proposal)
    return (
        canonical_json_bytes(proposal) == canonical_json_bytes(manual_baseline)
        and proposal.get("authority") == "AGENT_PROPOSAL"
        and proposal.get("verdict") is None
        and not {"status", "validation_verdict"}.intersection(proposal)
    )


def _usage_is_bounded(spec: CodexHarnessSpikeSpec, usage: Mapping[str, int]) -> bool:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    return bool(
        isinstance(input_tokens, int)
        and 0 < input_tokens <= spec.max_input_tokens
        and isinstance(output_tokens, int)
        and 0 < output_tokens <= spec.max_output_tokens
    )
