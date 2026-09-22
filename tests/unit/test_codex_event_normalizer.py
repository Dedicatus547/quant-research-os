from __future__ import annotations

import pytest

from quantos.application.agent_harness import capture_from_agent_events
from quantos.contracts import AgentEventKind
from quantos.integrations.codex.event_normalizer import (
    CodexEventNormalizationError,
    normalize_provider_events,
)


def _provider_events() -> list[dict[str, object]]:
    return [
        {
            "method": "turn/started",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"id": "turn-1", "status": "inProgress", "error": None},
            },
        },
        {
            "method": "item/completed",
            "payload": {
                "item": {
                    "type": "mcpToolCall",
                    "server": "fixture",
                    "tool": "read",
                    "arguments": {"hash": "a" * 64},
                    "result": {"structured_content": {"ok": True}},
                    "error": None,
                    "status": "completed",
                }
            },
        },
        {
            "method": "item/completed",
            "payload": {"item": {"type": "agentMessage", "phase": "final_answer", "text": "{}"}},
        },
        {
            "method": "thread/tokenUsage/updated",
            "payload": {
                "token_usage": {
                    "last": {
                        "input_tokens": 10,
                        "cached_input_tokens": 4,
                        "output_tokens": 2,
                    }
                }
            },
        },
        {
            "method": "turn/completed",
            "payload": {
                "thread_id": "thread-1",
                "turn": {"id": "turn-1", "status": "completed", "error": None},
            },
        },
    ]


def test_provider_events_normalize_to_replayable_transport_neutral_capture() -> None:
    events = normalize_provider_events(_provider_events(), thread_id="thread-1")
    capture = capture_from_agent_events(events, max_bytes=100_000)

    assert events[0].kind is AgentEventKind.ATTEMPT_STARTED
    assert events[-1].kind is AgentEventKind.ATTEMPT_COMPLETED
    assert capture.thread_ids == ("thread-1",)
    assert capture.tool_calls[0].tool == "read"
    assert capture.agent_messages == ("{}",)
    assert capture.usage == {
        "cached_input_tokens": 4,
        "input_tokens": 10,
        "output_tokens": 2,
    }


def _command_event(
    method: str,
    *,
    item_id: str = "command-1",
    turn_id: str = "turn-1",
    status: str,
    exit_code: int | None,
    output: str = "",
) -> dict[str, object]:
    return {
        "method": method,
        "payload": {
            "thread_id": "thread-1",
            "turn_id": turn_id,
            "item": {
                "id": item_id,
                "type": "commandExecution",
                "command": "/usr/bin/pwd",
                "aggregated_output": output,
                "exit_code": exit_code,
                "status": status,
            },
        },
    }


def test_command_events_preserve_and_match_provider_lifecycle_identity() -> None:
    provider = _provider_events()
    provider[1:1] = [
        _command_event("item/started", status="inProgress", exit_code=None),
        _command_event("item/completed", status="completed", exit_code=0, output="/fixture\n"),
    ]

    capture = capture_from_agent_events(
        normalize_provider_events(provider, thread_id="thread-1"), max_bytes=100_000
    )

    assert capture.command_started_count == 1
    assert capture.command_terminal_count == 1
    assert capture.command_lifecycle_integrity is True
    assert len(capture.command_lifecycles) == 1
    lifecycle = capture.command_lifecycles[0]
    assert lifecycle.item_id == "command-1"
    assert lifecycle.thread_id == "thread-1"
    assert lifecycle.turn_id == "turn-1"
    assert lifecycle.exit_code == 0


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_start",
        "duplicate_terminal",
        "orphan",
        "cross_turn",
        "paired_wrong_thread",
        "paired_wrong_turn",
        "command_mismatch",
        "missing_identity",
    ],
)
def test_command_lifecycle_identity_defects_fail_closed(defect: str) -> None:
    start = _command_event("item/started", status="inProgress", exit_code=None)
    completed = _command_event(
        "item/completed", status="completed", exit_code=0, output="/fixture\n"
    )
    if defect == "duplicate_start":
        command_events = [start, start, completed]
    elif defect == "duplicate_terminal":
        command_events = [start, completed, completed]
    elif defect == "orphan":
        command_events = [completed]
    elif defect == "cross_turn":
        command_events = [
            start,
            _command_event(
                "item/completed",
                turn_id="turn-2",
                status="completed",
                exit_code=0,
            ),
        ]
    elif defect in {"paired_wrong_thread", "paired_wrong_turn"}:
        command_events = [start, completed]
        for event in command_events:
            payload = event["payload"]
            assert isinstance(payload, dict)
            if defect == "paired_wrong_thread":
                payload["thread_id"] = "thread-other"
            else:
                payload["turn_id"] = "turn-other"
    elif defect == "command_mismatch":
        changed = _command_event("item/completed", status="completed", exit_code=0)
        item = changed["payload"]["item"]  # type: ignore[index]
        assert isinstance(item, dict)
        item["command"] = "/usr/bin/true"
        command_events = [start, changed]
    else:
        payload = start["payload"]
        assert isinstance(payload, dict)
        item = payload["item"]
        assert isinstance(item, dict)
        item.pop("id")
        command_events = [start, completed]
    provider = _provider_events()
    provider[1:1] = command_events

    capture = capture_from_agent_events(
        normalize_provider_events(provider, thread_id="thread-1"), max_bytes=100_000
    )

    assert capture.command_lifecycle_integrity is False
    assert capture.command_lifecycles == ()


@pytest.mark.parametrize(
    "event",
    [
        {"method": "future/unknown", "payload": {}},
        {"method": "item/started", "payload": {"item": {"type": "futureItem"}}},
        {"method": "item/completed", "payload": {"item": {"type": "futureItem"}}},
        {"method": "turn/started", "payload": {}},
    ],
)
def test_unknown_or_malformed_provider_events_fail_closed(event: dict[str, object]) -> None:
    with pytest.raises(CodexEventNormalizationError):
        normalize_provider_events([event], thread_id="thread-1")
