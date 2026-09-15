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
