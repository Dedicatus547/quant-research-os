"""Read-only decoder for immutable historical ``codex exec --json`` artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from quantos.contracts.base import canonical_json_bytes, sha256_bytes


class HarnessTranscriptError(ValueError):
    """Raised when a historical Codex JSONL capture cannot be decoded safely."""


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


def parse_codex_exec_jsonl(
    payload: bytes,
    *,
    max_bytes: int,
    forbidden_marker: bytes | None = None,
) -> CodexExecCapture:
    """Decode bounded v1 JSONL without logging text or environment values."""

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
        event = _string_mapping(value, label="Codex transcript event")
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
            item = _string_mapping(event.get("item"), label="completed item payload")
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
                    or not isinstance(status, str)
                ):
                    raise HarnessTranscriptError("MCP capture is invalid")
                typed_arguments = _string_mapping(arguments, label="MCP arguments")
                typed_result = (
                    _string_mapping(result, label="MCP result") if result is not None else None
                )
                mcp_calls.append(
                    McpCapture(
                        sequence=sequence,
                        server=server,
                        tool=tool,
                        arguments=typed_arguments,
                        result=typed_result,
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


def _string_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise HarnessTranscriptError(f"{label} is invalid")
    mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise HarnessTranscriptError(f"{label} is invalid")
    return cast(Mapping[str, object], mapping)


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
