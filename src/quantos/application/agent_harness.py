"""Harness-neutral execution observations and local Agent runtime port."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from pydantic import ValidationError

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    AgentEvent,
    AgentEventKind,
    HarnessExecutionRequest,
    HarnessRuntimeIdentity,
    HarnessRuntimeIdentityV2,
    HarnessTerminalError,
)


class HarnessCaptureError(ValueError):
    """Raised when normalized events cannot form a safe execution capture."""


@dataclass(frozen=True)
class CommandObservation:
    sequence: int
    command: str
    output: str
    exit_code: int | None
    event_hash: str


@dataclass(frozen=True)
class ToolCallObservation:
    sequence: int
    server: str
    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object] | None
    error: object | None
    status: str
    event_hash: str


@dataclass(frozen=True)
class HarnessCapture:
    attempt_index: int
    transcript: bytes
    transcript_hash: str
    transcript_size_bytes: int
    event_count: int
    event_hashes: tuple[str, ...]
    thread_ids: tuple[str, ...]
    turn_started: bool
    turn_completed: bool
    turn_failed: bool
    commands: tuple[CommandObservation, ...]
    tool_calls: tuple[ToolCallObservation, ...]
    agent_messages: tuple[str, ...]
    usage: Mapping[str, int]
    approval_requested: bool


@dataclass(frozen=True)
class HarnessAttemptResult:
    capture: HarnessCapture
    runtime: HarnessRuntimeIdentity | HarnessRuntimeIdentityV2 | None
    terminal_error: HarnessTerminalError | None
    provider_transcript: bytes | None


@dataclass(frozen=True)
class HarnessExecutionResult:
    attempts: tuple[HarnessAttemptResult, ...]

    def __post_init__(self) -> None:
        if not self.attempts or [item.capture.attempt_index for item in self.attempts] != list(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("harness execution attempts must be nonempty and contiguous")

    @property
    def capture(self) -> HarnessCapture:
        return self.attempts[-1].capture

    @property
    def runtime(self) -> HarnessRuntimeIdentity | HarnessRuntimeIdentityV2 | None:
        return self.attempts[-1].runtime

    @property
    def terminal_error(self) -> HarnessTerminalError | None:
        return self.attempts[-1].terminal_error

    @property
    def provider_transcript(self) -> bytes | None:
        transcripts = [
            item.provider_transcript
            for item in self.attempts
            if item.provider_transcript is not None
        ]
        if not transcripts:
            return None
        return b"".join(transcripts)

    @property
    def normalized_transcript(self) -> bytes:
        return b"".join(item.capture.transcript for item in self.attempts)

    @property
    def normalized_transcript_hash(self) -> str:
        return sha256_bytes(self.normalized_transcript)


class LocalAgentHarness(Protocol):
    def execute(self, request: HarnessExecutionRequest) -> HarnessExecutionResult: ...


def serialize_agent_events(events: tuple[AgentEvent, ...]) -> bytes:
    return b"".join(event.canonical_bytes() + b"\n" for event in events)


def parse_agent_events(payload: bytes, *, max_bytes: int) -> tuple[AgentEvent, ...]:
    if not payload or len(payload) > max_bytes:
        raise HarnessCaptureError("normalized transcript is empty or exceeds its bound")
    events: list[AgentEvent] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        try:
            events.append(AgentEvent.model_validate_json(line))
        except (ValidationError, json.JSONDecodeError) as error:
            raise HarnessCaptureError("normalized transcript event is invalid") from error
    return tuple(events)


def captures_from_agent_events(
    events: tuple[AgentEvent, ...], *, max_bytes: int
) -> tuple[HarnessCapture, ...]:
    if not events:
        raise HarnessCaptureError("normalized transcript contains no events")
    grouped: list[list[AgentEvent]] = []
    for event in events:
        if event.attempt > len(grouped):
            if event.attempt != len(grouped) + 1:
                raise HarnessCaptureError("normalized attempts are not contiguous")
            grouped.append([])
        grouped[event.attempt - 1].append(event)
    captures = tuple(
        capture_from_agent_events(tuple(group), max_bytes=max_bytes) for group in grouped
    )
    if sum(item.transcript_size_bytes for item in captures) > max_bytes:
        raise HarnessCaptureError("combined normalized transcript exceeds its bound")
    return captures


def capture_from_agent_events(events: tuple[AgentEvent, ...], *, max_bytes: int) -> HarnessCapture:
    if not events:
        raise HarnessCaptureError("normalized transcript contains no events")
    attempt_index = events[0].attempt
    for expected, event in enumerate(events, start=1):
        if event.attempt != attempt_index or event.sequence != expected:
            raise HarnessCaptureError("normalized event sequence is not contiguous")
    transcript = serialize_agent_events(events)
    if len(transcript) > max_bytes:
        raise HarnessCaptureError("normalized transcript exceeds its bound")

    commands: list[CommandObservation] = []
    tools: list[ToolCallObservation] = []
    thread_ids: list[str] = []
    messages: list[str] = []
    usage: dict[str, int] = {}
    turn_started = False
    turn_completed = False
    turn_failed = False
    approval_requested = False
    event_hashes: list[str] = []

    for event in events:
        payload = event.payload
        event_hash = event.content_hash
        event_hashes.append(event_hash)
        if event.kind is AgentEventKind.THREAD_STARTED:
            thread_id = payload.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id:
                raise HarnessCaptureError("thread event is invalid")
            thread_ids.append(thread_id)
        elif event.kind is AgentEventKind.TURN_STARTED:
            turn_started = True
        elif event.kind is AgentEventKind.TURN_COMPLETED:
            turn_completed = True
        elif event.kind is AgentEventKind.TURN_FAILED:
            turn_failed = True
        elif event.kind is AgentEventKind.APPROVAL_REQUESTED:
            approval_requested = True
        elif event.kind in {AgentEventKind.COMMAND_COMPLETED, AgentEventKind.COMMAND_FAILED}:
            command = payload.get("command")
            output = payload.get("output", "")
            exit_code = payload.get("exit_code")
            if (
                not isinstance(command, str)
                or not isinstance(output, str)
                or (exit_code is not None and not isinstance(exit_code, int))
            ):
                raise HarnessCaptureError("command event is invalid")
            commands.append(
                CommandObservation(event.sequence, command, output, exit_code, event_hash)
            )
        elif event.kind in {AgentEventKind.TOOL_COMPLETED, AgentEventKind.TOOL_FAILED}:
            server = payload.get("server")
            tool = payload.get("tool")
            arguments = payload.get("arguments")
            result = payload.get("result")
            status = payload.get("status")
            if (
                not isinstance(server, str)
                or not isinstance(tool, str)
                or not isinstance(arguments, dict)
                or (result is not None and not isinstance(result, dict))
                or not isinstance(status, str)
            ):
                raise HarnessCaptureError("tool event is invalid")
            typed_arguments = _string_mapping(
                cast(dict[object, object], arguments), label="tool arguments"
            )
            typed_result = (
                _string_mapping(cast(dict[object, object], result), label="tool result")
                if result is not None
                else None
            )
            tools.append(
                ToolCallObservation(
                    sequence=event.sequence,
                    server=server,
                    tool=tool,
                    arguments=typed_arguments,
                    result=typed_result,
                    error=payload.get("error"),
                    status=status,
                    event_hash=event_hash,
                )
            )
        elif event.kind is AgentEventKind.AGENT_MESSAGE:
            message = payload.get("text")
            if not isinstance(message, str):
                raise HarnessCaptureError("Agent message event is invalid")
            messages.append(message)
        elif event.kind is AgentEventKind.USAGE:
            candidate = payload.get("usage")
            if not isinstance(candidate, dict):
                raise HarnessCaptureError("usage event is invalid")
            untyped_usage = cast(Mapping[object, object], candidate)
            if not all(
                isinstance(key, str) and isinstance(value, int) and value >= 0
                for key, value in untyped_usage.items()
            ):
                raise HarnessCaptureError("usage event is invalid")
            usage = cast(dict[str, int], candidate)

    return HarnessCapture(
        attempt_index=attempt_index,
        transcript=transcript,
        transcript_hash=sha256_bytes(transcript),
        transcript_size_bytes=len(transcript),
        event_count=len(events),
        event_hashes=tuple(event_hashes),
        thread_ids=tuple(thread_ids),
        turn_started=turn_started,
        turn_completed=turn_completed,
        turn_failed=turn_failed,
        commands=tuple(commands),
        tool_calls=tuple(tools),
        agent_messages=tuple(messages),
        usage=usage,
        approval_requested=approval_requested,
    )


def make_agent_event(
    *,
    sequence: int,
    kind: AgentEventKind,
    provider_event_type: str,
    payload: dict[str, object],
    attempt: int = 1,
) -> AgentEvent:
    return AgentEvent(
        attempt=attempt,
        sequence=sequence,
        kind=kind,
        provider_event_type=provider_event_type,
        payload=payload,
        payload_hash=sha256_bytes(canonical_json_bytes(payload)),
    )


def _string_mapping(value: dict[object, object], *, label: str) -> Mapping[str, object]:
    mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise HarnessCaptureError(f"{label} is invalid")
    return cast(Mapping[str, object], mapping)
