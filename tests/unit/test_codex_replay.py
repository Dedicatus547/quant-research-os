from __future__ import annotations

import pytest

from quantos.application.agent_harness import make_agent_event, serialize_agent_events
from quantos.contracts import AgentEventKind, canonical_json_bytes
from quantos.integrations.codex.legacy_v1 import CodexExecCapture
from quantos.integrations.codex.replay import (
    UnsupportedHarnessArtifact,
    replay_harness_capture,
)


def test_replay_dispatches_v2_by_manifest_schema_not_filename() -> None:
    transcript = serialize_agent_events(
        (
            make_agent_event(
                sequence=1,
                kind=AgentEventKind.ATTEMPT_STARTED,
                provider_event_type="quantos.attempt.started",
                payload={"attempt": 1},
            ),
        )
    )

    capture = replay_harness_capture("agent-run-manifest/v2", transcript, max_bytes=10_000)

    assert capture.event_count == 1


def test_replay_dispatches_historical_v1_without_sdk() -> None:
    transcript = (
        canonical_json_bytes({"type": "thread.started", "thread_id": "legacy-thread"}) + b"\n"
    )

    capture = replay_harness_capture("agent-run-manifest/v1", transcript, max_bytes=10_000)

    assert isinstance(capture, CodexExecCapture)
    assert capture.thread_ids == ("legacy-thread",)


def test_replay_rejects_unknown_schema_instead_of_guessing() -> None:
    with pytest.raises(UnsupportedHarnessArtifact, match="unsupported"):
        replay_harness_capture("agent-run-manifest/v99", b"{}\n", max_bytes=10_000)
