"""Explicit metadata projection before the unchanged frozen v2 normalizer.

This layer does not grant qualification or change unknown-event rejection. The
complete provider stream remains the original; only the v2 input is projected.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import AgentEvent
from quantos.integrations.codex import event_normalizer as frozen

IDENTIFIER = "codex-moderation-metadata-projection/v1"
METHOD = "turn/moderationMetadata"
USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens")


def source_hash(events: Sequence[Mapping[str, object]]) -> str:
    base = sha256_bytes(Path(frozen.__file__).read_bytes())
    if not any(event.get("method") == METHOD for event in events):
        return base
    return sha256_bytes(
        canonical_json_bytes(
            {
                "projection_identifier": IDENTIFIER,
                "projection_hash": sha256_bytes(Path(__file__).read_bytes()),
                "frozen_normalizer_hash": base,
            }
        )
    )


def provider_events(transcript: bytes | None) -> tuple[Mapping[str, object], ...]:
    if not transcript:
        return ()
    return tuple(cast(Mapping[str, object], json.loads(line)) for line in transcript.splitlines())


def _blocked(value: object) -> bool:
    if isinstance(value, dict):
        body = cast(dict[str, object], value)
        if "is_blocked" in body and type(body["is_blocked"]) is not bool:
            raise frozen.CodexEventNormalizationError("moderation block flag is invalid")
        return body.get("is_blocked") is True or any(_blocked(v) for v in body.values())
    if isinstance(value, list):
        return any(_blocked(v) for v in cast(list[object], value))
    return False


def normalize_provider_events(
    events: Sequence[Mapping[str, object]], *, thread_id: str, attempt: int = 1
) -> tuple[AgentEvent, ...]:
    if not any(event.get("method") == METHOD for event in events):
        return frozen.normalize_provider_events(events, thread_id=thread_id, attempt=attempt)
    projected: list[Mapping[str, object]] = []
    active_turn: str | None = None
    for event in events:
        method, payload = event.get("method"), event.get("payload")
        if not isinstance(payload, dict):
            raise frozen.CodexEventNormalizationError("provider event envelope is invalid")
        body = cast(dict[str, object], payload)
        if method in {"turn/started", "turn/completed"}:
            raw_turn = body.get("turn")
            turn = cast(dict[str, object], raw_turn) if isinstance(raw_turn, dict) else {}
            if (
                body.get("thread_id") != thread_id
                or not isinstance(turn.get("id"), str)
                or not turn.get("id")
            ):
                raise frozen.CodexEventNormalizationError("projected turn identity is invalid")
            turn_id = cast(str, turn["id"])
            if method == "turn/started":
                if active_turn is not None:
                    raise frozen.CodexEventNormalizationError("projected turns overlap")
                active_turn = turn_id
            else:
                if active_turn != turn_id:
                    raise frozen.CodexEventNormalizationError("projected terminal turn differs")
                active_turn = None
        if method == METHOD:
            if (
                set(body) != {"metadata", "thread_id", "turn_id"}
                or body.get("thread_id") != thread_id
                or active_turn is None
                or body.get("turn_id") != active_turn
                or not isinstance(body.get("metadata"), dict)
            ):
                raise frozen.CodexEventNormalizationError("moderation metadata identity is invalid")
            if _blocked(body["metadata"]):
                raise frozen.CodexEventNormalizationError("provider moderation reports blocking")
            continue
        projected.append(event)
    return frozen.normalize_provider_events(projected, thread_id=thread_id, attempt=attempt)


def observe_usage(events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Observe retained usage even if normalization failed; never repair a capture.

    One request has one turn. Use the last snapshot, not a sum of cumulative
    notifications. Missing, malformed or unattributable usage is not zero.
    """
    starts = [event.get("payload") for event in events if event.get("method") == "turn/started"]
    snapshots = [
        event.get("payload")
        for event in events
        if event.get("method") == "thread/tokenUsage/updated"
    ]
    result: dict[str, object] = {
        "status": "UNAVAILABLE",
        "usage": None,
        "notifications": len(snapshots),
        "unit": "TOKENS",
    }
    if not snapshots:
        return result
    try:
        if len(starts) != 1 or not isinstance(starts[0], dict):
            raise ValueError
        start = cast(dict[str, object], starts[0])
        turn = start["turn"]
        if not isinstance(turn, dict):
            raise ValueError
        turn = cast(dict[str, object], turn)
        thread_id, turn_id = start.get("thread_id"), turn.get("id")
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(turn_id, str)
            or not turn_id
        ):
            raise ValueError
        usage: dict[str, int] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                raise ValueError
            snapshot = cast(dict[str, object], snapshot)
            if snapshot.get("thread_id") != thread_id or snapshot.get("turn_id") != turn_id:
                raise ValueError
            token_usage = snapshot["token_usage"]
            if not isinstance(token_usage, dict):
                raise ValueError
            token_usage = cast(dict[str, object], token_usage)
            if not isinstance(token_usage.get("last"), dict):
                raise ValueError
            last = cast(dict[str, object], token_usage["last"])
            if any(
                type(last.get(key)) is not int or cast(int, last[key]) < 0 for key in USAGE_KEYS
            ):
                raise ValueError
            # Reuse the protocol scan view's count naming for validated numeric
            # counters. Arbitrary credential-shaped keys are never exempted.
            usage = {key.replace("tokens", "count"): cast(int, last[key]) for key in USAGE_KEYS}
        result.update(status="OBSERVED", usage=usage, thread_id=thread_id, turn_id=turn_id)
    except (KeyError, TypeError, ValueError):
        result["status"] = "INVALID_OR_UNATTRIBUTABLE"
    return result
