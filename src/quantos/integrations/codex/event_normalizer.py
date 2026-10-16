"""Normalize Codex app-server notifications into QuantOS-owned events."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from quantos.application.agent_harness import make_agent_event
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    AgentEvent,
    AgentEventKind,
    HarnessErrorKind,
    HarnessTerminalError,
)

NORMALIZER_IDENTIFIER = "quantos-codex-normalizer/v2"
PROVIDER_FAILURE_NORMALIZER_IDENTIFIER = "quantos-codex-provider-failure-normalizer/v1"


class CodexEventNormalizationError(ValueError):
    """Raised when an SDK notification cannot be normalized without losing semantics."""


@dataclass(frozen=True)
class ProviderFailureNormalization:
    """A separate failure-only projection; never a v2 success qualification."""

    events: tuple[AgentEvent, ...]
    terminal_error: HarnessTerminalError
    observation: dict[str, object]


def normalize_provider_failure_events(
    provider_events: Sequence[Mapping[str, object]], *, thread_id: str, attempt: int = 1
) -> ProviderFailureNormalization | None:
    """Observe provider error codes without changing the frozen v2 replay entry.

    Error messages stay in the separately retained provider original; only their
    hashes enter this projection. Provider ``will_retry`` is an observation and
    never grants a new adapter attempt. Any provider error prevents proposal
    acceptance, including when another event contains a final agent message.
    """
    errors: list[tuple[str, dict[str, object]]] = []
    turns: list[tuple[str, dict[str, object]]] = []
    for raw in provider_events:
        method, payload = raw.get("method"), raw.get("payload")
        if method == "error":
            if not isinstance(payload, dict):
                raise CodexEventNormalizationError("provider error envelope is invalid")
            body = cast(dict[str, object], payload)
            if body.get("thread_id") != thread_id:
                raise CodexEventNormalizationError("provider error thread identity differs")
            if not isinstance(body.get("turn_id"), str) or not body.get("turn_id"):
                raise CodexEventNormalizationError("provider error turn identity is invalid")
            will_retry = body.get("will_retry")
            if not isinstance(will_retry, bool):
                raise CodexEventNormalizationError("provider error retry observation is invalid")
            errors.append(("error", _provider_error_observation(body, will_retry=will_retry)))
        elif method in {"turn/started", "turn/completed"} and isinstance(payload, dict):
            body = cast(dict[str, object], payload)
            turn_value = body.get("turn")
            if isinstance(turn_value, dict):
                turn = cast(dict[str, object], turn_value)
                turns.append((cast(str, method), body))
                if method == "turn/completed" and turn.get("status") == "failed" and not errors:
                    error = turn.get("error")
                    if isinstance(error, dict):
                        error = cast(dict[str, object], error)
                        errors.append(
                            (
                                cast(str, method),
                                _provider_error_observation(
                                    {
                                        "error": error,
                                        "thread_id": body.get("thread_id"),
                                        "turn_id": turn.get("id"),
                                    },
                                    will_retry=None,
                                ),
                            )
                        )
    if not errors:
        return None
    if not thread_id:
        raise CodexEventNormalizationError("provider thread id is missing")
    normalizer_hash = sha256_bytes(Path(__file__).read_bytes())
    for _, observation in errors:
        observation["normalizer_hash"] = normalizer_hash
        if observation.get("thread_id") != thread_id:
            raise CodexEventNormalizationError("provider error thread identity differs")
    turn_ids = {_required_mapping(body, "turn").get("id") for _, body in turns}
    if turns and any(item["turn_id"] not in turn_ids for _, item in errors):
        raise CodexEventNormalizationError("provider error turn identity differs")
    if any(body.get("thread_id") != thread_id for _, body in turns):
        raise CodexEventNormalizationError("provider turn thread identity differs")
    events: list[AgentEvent] = []

    def append(kind: AgentEventKind, provider_type: str, payload: dict[str, object]) -> None:
        events.append(
            make_agent_event(
                sequence=len(events) + 1,
                kind=kind,
                provider_event_type=provider_type,
                payload=payload,
                attempt=attempt,
            )
        )

    append(AgentEventKind.ATTEMPT_STARTED, "quantos.attempt.started", {"attempt": attempt})
    append(AgentEventKind.THREAD_STARTED, "sdk.thread_start.result", {"thread_id": thread_id})
    error_index = 0
    for raw in provider_events:
        method, body = raw.get("method"), raw.get("payload")
        if not isinstance(method, str) or not isinstance(body, dict):
            raise CodexEventNormalizationError("provider event envelope is invalid")
        body = cast(dict[str, object], body)
        if method == "error":
            append(AgentEventKind.HARNESS_ERROR, method, errors[error_index][1])
            error_index += 1
        elif method == "turn/started":
            payload = _turn_payload(body)
            # Keep error text solely in the separately retained provider original.
            payload["error"] = None
            append(AgentEventKind.TURN_STARTED, method, payload)
        elif method == "turn/completed":
            payload = _turn_payload(body)
            if error_index < len(errors) and errors[error_index][0] == method:
                append(AgentEventKind.HARNESS_ERROR, method, errors[error_index][1])
                error_index += 1
            payload["error"] = errors[-1][1]
            append(
                AgentEventKind.TURN_COMPLETED
                if payload["status"] == "completed"
                else AgentEventKind.TURN_FAILED,
                method,
                payload,
            )
        elif method in {"item/started", "item/completed"}:
            item = _required_mapping(body, "item")
            item_type = item.get("type")
            started = method == "item/started"
            if item_type == "commandExecution":
                append(
                    AgentEventKind.COMMAND_STARTED
                    if started
                    else (
                        AgentEventKind.COMMAND_COMPLETED
                        if item.get("status") == "completed"
                        else AgentEventKind.COMMAND_FAILED
                    ),
                    method,
                    _command_payload(item, body),
                )
            elif item_type == "mcpToolCall":
                append(
                    AgentEventKind.TOOL_STARTED
                    if started
                    else (
                        AgentEventKind.TOOL_COMPLETED
                        if item.get("status") == "completed" and item.get("error") is None
                        else AgentEventKind.TOOL_FAILED
                    ),
                    method,
                    _tool_payload(item),
                )
            elif item_type in {"agentMessage", "userMessage", "reasoning", "plan"}:
                continue
            else:
                raise CodexEventNormalizationError("unsupported provider failure item type")
        elif method == "thread/tokenUsage/updated":
            last_usage = _required_mapping(_required_mapping(body, "token_usage"), "last")
            append(
                AgentEventKind.USAGE,
                method,
                {
                    "usage": {
                        key: _required_nonnegative_int(last_usage, key)
                        for key in ("cached_input_tokens", "input_tokens", "output_tokens")
                    }
                },
            )
        elif "approval" in method.lower():
            append(AgentEventKind.APPROVAL_REQUESTED, method, {})
        elif method in _IGNORED_METHODS:
            continue
        else:
            raise CodexEventNormalizationError("unsupported provider failure event method")
    last = errors[-1][1]
    kind = _provider_error_kind(cast(str | None, last["provider_error_code"]))
    terminal = HarnessTerminalError(
        kind=kind, message_hash=cast(str, last["message_hash"]), retryable=False
    )
    append(
        AgentEventKind.ATTEMPT_FAILED,
        "quantos.attempt.failed",
        {
            "attempt": attempt,
            "error_kind": kind.value,
            "normalizer_identifier": PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
            "normalizer_hash": normalizer_hash,
        },
    )
    return ProviderFailureNormalization(
        events=tuple(events),
        terminal_error=terminal,
        observation={
            "schema_version": "codex-provider-failure-observation/v1",
            "normalizer_identifier": PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
            "normalizer_hash": last["normalizer_hash"],
            "projection": "FAILURE_ONLY",
            "retryable": False,
            "provider_errors": [item for _, item in errors],
        },
    )


def _provider_error_observation(
    body: Mapping[str, object], *, will_retry: bool | None
) -> dict[str, object]:
    error = _required_mapping(body, "error")
    message = error.get("message")
    if not isinstance(message, str):
        raise CodexEventNormalizationError("provider error message is invalid")
    code = error.get("codex_error_info")
    if code is not None and (
        not isinstance(code, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", code) is None
    ):
        # Retain the full structured error in the provider original. A complex
        # unknown enum is not reclassified as an unsupported event protocol.
        code = None
    return {
        "normalizer_identifier": PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
        "provider_error_code": code,
        "will_retry": will_retry,
        "retryable": False,
        "message_hash": sha256_bytes(message.encode("utf-8")),
        "message_bytes": len(message.encode("utf-8")),
        "provider_error_hash": sha256_bytes(canonical_json_bytes(error)),
        "thread_id": body.get("thread_id"),
        "turn_id": body.get("turn_id"),
    }


def _provider_error_kind(code: str | None) -> HarnessErrorKind:
    return {
        "serverOverloaded": HarnessErrorKind.OVERLOADED,
        "rateLimitExceeded": HarnessErrorKind.QUOTA_EXHAUSTED,
        "usageLimitExceeded": HarnessErrorKind.QUOTA_EXHAUSTED,
        "unauthorized": HarnessErrorKind.AUTH_UNAVAILABLE,
    }.get(code or "", HarnessErrorKind.UNKNOWN)


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
                append(AgentEventKind.COMMAND_STARTED, method, _command_payload(item, body))
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
                command = _command_payload(item, body)
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


def _command_payload(
    item: Mapping[str, object], envelope: Mapping[str, object]
) -> dict[str, object]:
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
    payload: dict[str, object] = {
        "command": command,
        "exit_code": exit_code,
        "output": output or "",
        "status": status,
    }
    identifiers = {
        "item_id": item.get("id"),
        "thread_id": envelope.get("thread_id", envelope.get("threadId")),
        "turn_id": envelope.get("turn_id", envelope.get("turnId")),
    }
    payload.update(
        {key: value for key, value in identifiers.items() if isinstance(value, str) and value}
    )
    return payload


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
