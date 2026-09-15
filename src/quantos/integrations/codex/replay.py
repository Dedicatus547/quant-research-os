"""Schema-driven replay dispatch for SDK v2 and immutable CLI v1 transcripts."""

from __future__ import annotations

from quantos.application.agent_harness import (
    HarnessCapture,
    captures_from_agent_events,
    parse_agent_events,
)
from quantos.integrations.codex.legacy_v1 import CodexExecCapture, parse_codex_exec_jsonl


class UnsupportedHarnessArtifact(ValueError):
    """Raised when a transcript schema has no frozen decoder."""


def replay_harness_capture(
    manifest_schema_version: str,
    transcript: bytes,
    *,
    max_bytes: int,
) -> HarnessCapture | CodexExecCapture:
    if manifest_schema_version == "agent-run-manifest/v2":
        return captures_from_agent_events(
            parse_agent_events(transcript, max_bytes=max_bytes), max_bytes=max_bytes
        )[-1]
    if manifest_schema_version == "agent-run-manifest/v1":
        return parse_codex_exec_jsonl(transcript, max_bytes=max_bytes)
    raise UnsupportedHarnessArtifact(
        f"unsupported AgentRun manifest schema: {manifest_schema_version!r}"
    )
