"""Normalize Codex app-server notifications into QuantOS-owned events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from quantos.application.agent_harness import make_agent_event
from quantos.contracts.harness import AgentEvent, AgentEventKind

NORMALIZER_IDENTIFIER = "quantos-codex-normalizer/v1"


class CodexEventNormalizationError(ValueError):
    """Raised when an SDK notification cannot be normalized without losing semantics."""


_IGNORED_METHODS = {
    "item/agentMessage/delta",
    "item/commandExecution/outputDelta",
    "item/fileChange/outputDelta",
    "item/mcpToolCall/progress",
    "item/plan/delta",
    "item/reasoning/summaryPartAdded",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/textDelta",
    "turn/diff/updated",
    "turn/plan/updated",
}


def normalize_provider_events(
    provider_events: Sequence[Mapping[str, object]], *, thread_id: str, attempt: int = 1
) -> tuple[AgentEvent, ...]:
    if not thread_id:
        raise CodexEventNormalizationError("provider thread id is missing")
    normalized: list[AgentEvent] = []

    def append(kind: AgentEventKind, provider_type: str, payload: dict[str, object]) -> None:
        normalized.append(
            make_agent_event(
                sequence=len(normalized) + 1,
                kind=kind,
                provider_event_type=provider_type,
                payload=payload,
                attempt=attempt,
            )
        )

    append(AgentEventKind.ATTEMPT_STARTED, "quantos.attempt.started", {"attempt": attempt})
    append(
        AgentEventKind.THREAD_STARTED,
        "sdk.thread_start.result",
        {"thread_id": thread_id},
    )
    terminal_seen = False
    for raw in provider_events:
        method = raw.get("method")
        payload = raw.get("payload")
        if not isinstance(method, str) or not isinstance(payload, dict):
            raise CodexEventNormalizationError("provider event envelope is invalid")
        body = cast(dict[str, object], payload)
        if method == "turn/started":
            append(AgentEventKind.TURN_STARTED, method, _turn_payload(body))
        elif method == "turn/completed":
            turn = _required_mapping(body, "turn")
            status = turn.get("status")
            kind = (
                AgentEventKind.TURN_COMPLETED
                if status == "completed"
                else AgentEventKind.TURN_FAILED
            )
            append(kind, method, _turn_payload(body))
            terminal_seen = True
        elif method == "item/started":
            item = _required_mapping(body, "item")
            item_type = item.get("type")
            if item_type == "commandExecution":
                append(AgentEventKind.COMMAND_STARTED, method, _command_payload(item))
            elif item_type == "mcpToolCall":
                append(AgentEventKind.TOOL_STARTED, method, _tool_payload(item))
            elif item_type in {"agentMessage", "userMessage", "reasoning", "plan"}:
                continue
            else:
                raise CodexEventNormalizationError(f"unsupported started item type: {item_type!r}")
        elif method == "item/completed":
            item = _required_mapping(body, "item")
            item_type = item.get("type")
            if item_type == "commandExecution":
                command = _command_payload(item)
                kind = (
                    AgentEventKind.COMMAND_COMPLETED
                    if item.get("status") == "completed"
                    else AgentEventKind.COMMAND_FAILED
                )
                append(kind, method, command)
            elif item_type == "mcpToolCall":
                tool = _tool_payload(item)
                kind = (
                    AgentEventKind.TOOL_COMPLETED
                    if item.get("status") == "completed" and item.get("error") is None
                    else AgentEventKind.TOOL_FAILED
                )
                append(kind, method, tool)
            elif item_type == "agentMessage":
                text = item.get("text")
                if not isinstance(text, str):
                    raise CodexEventNormalizationError("Agent message text is invalid")
                append(
                    AgentEventKind.AGENT_MESSAGE,
                    method,
                    {"phase": item.get("phase"), "text": text},
                )
            elif item_type in {"userMessage", "reasoning", "plan"}:
                continue
            else:
                raise CodexEventNormalizationError(
                    f"unsupported completed item type: {item_type!r}"
                )
        elif method == "thread/tokenUsage/updated":
            token_usage = _required_mapping(body, "token_usage")
            last = _required_mapping(token_usage, "last")
            usage = {
                "cached_input_tokens": _required_nonnegative_int(last, "cached_input_tokens"),
                "input_tokens": _required_nonnegative_int(last, "input_tokens"),
                "output_tokens": _required_nonnegative_int(last, "output_tokens"),
            }
            append(AgentEventKind.USAGE, method, {"usage": usage})
        elif "approval" in method.lower():
            append(AgentEventKind.APPROVAL_REQUESTED, method, {})
        elif method in _IGNORED_METHODS:
            continue
        else:
            raise CodexEventNormalizationError(f"unsupported provider event method: {method}")
    if not terminal_seen:
        raise CodexEventNormalizationError("provider stream has no terminal turn event")
    append(
        AgentEventKind.ATTEMPT_COMPLETED,
        "quantos.attempt.completed",
        {"attempt": attempt},
    )
    return tuple(normalized)


def _required_mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise CodexEventNormalizationError(f"provider {key} payload is invalid")
    return cast(dict[str, object], item)


def _required_nonnegative_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or item < 0:
        raise CodexEventNormalizationError(f"provider {key} usage is invalid")
    return item


def _turn_payload(body: Mapping[str, object]) -> dict[str, object]:
    turn = _required_mapping(body, "turn")
    turn_id = turn.get("id")
    status = turn.get("status")
    if not isinstance(turn_id, str) or not isinstance(status, str):
        raise CodexEventNormalizationError("provider turn payload is invalid")
    return {
        "error": turn.get("error"),
        "status": status,
        "thread_id": body.get("thread_id"),
        "turn_id": turn_id,
    }


def _command_payload(item: Mapping[str, object]) -> dict[str, object]:
    command = item.get("command")
    output = item.get("aggregated_output")
    exit_code = item.get("exit_code")
    status = item.get("status")
    if (
        not isinstance(command, str)
        or (output is not None and not isinstance(output, str))
        or (exit_code is not None and not isinstance(exit_code, int))
        or not isinstance(status, str)
    ):
        raise CodexEventNormalizationError("provider command payload is invalid")
    return {
        "command": command,
        "exit_code": exit_code,
        "output": output or "",
        "status": status,
    }


def _tool_payload(item: Mapping[str, object]) -> dict[str, object]:
    server = item.get("server")
    tool = item.get("tool")
    arguments = item.get("arguments")
    status = item.get("status")
    result = item.get("result")
    if (
        not isinstance(server, str)
        or not isinstance(tool, str)
        or not isinstance(arguments, dict)
        or not isinstance(status, str)
        or (result is not None and not isinstance(result, dict))
    ):
        raise CodexEventNormalizationError("provider MCP payload is invalid")
    return {
        "arguments": arguments,
        "error": item.get("error"),
        "result": result,
        "server": server,
        "status": status,
        "tool": tool,
    }
