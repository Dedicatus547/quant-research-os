"""Historical universe resolution from a verified Qlib view sidecar."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq

from quantos.contracts.research_execution import (
    HistoricalUniverseMember,
    HistoricalUniverseResolution,
)
from quantos.contracts.status import ReasonCode
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view


class QlibResearchError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def resolve_historical_universe(
    view_path: Path,
    *,
    expected_view_hash: str,
    expected_snapshot_hash: str,
    index_id: str,
    as_of_date: date,
    decision_time: datetime,
) -> HistoricalUniverseResolution:
    """Resolve only intervals effective and available at the requested decision time."""

    try:
        manifest = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if (
        manifest.view_hash != expected_view_hash
        or manifest.source_snapshot_hash != expected_snapshot_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "Qlib view or source snapshot hash does not match the resolved experiment",
        )
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise QlibResearchError(ReasonCode.SCHEMA_INVALID, "decision_time must be timezone-aware")
    if decision_time.date() != as_of_date:
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID, "decision_time date must equal as_of_date"
        )
    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        view_path / "sidecars" / "historical-universe.parquet"
    ).to_pylist()
    selected = [
        row
        for row in table
        if row["index_id"] == index_id
        and cast(date, row["effective_from"]) <= as_of_date <= cast(date, row["effective_to"])
        and cast(datetime, row["available_at"]) <= decision_time
    ]
    members = tuple(
        HistoricalUniverseMember(
            instrument_id=cast(str, row["instrument_id"]),
            qlib_id=cast(str, row["qlib_id"]),
            weight_percent=cast(float, row["weight_percent"]),
        )
        for row in sorted(selected, key=lambda item: cast(str, item["instrument_id"]))
    )
    if not members:
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "no historical universe is both effective and available at decision_time",
        )
    return HistoricalUniverseResolution(
        qlib_view_hash=manifest.view_hash,
        source_snapshot_hash=manifest.source_snapshot_hash,
        index_id=index_id,
        as_of_date=as_of_date,
        decision_time=decision_time,
        members=members,
    )


def resolve_historical_universe_spans(
    view_path: Path,
    *,
    expected_view_hash: str,
    expected_snapshot_hash: str,
    index_id: str,
    sessions: Sequence[date],
    decision_times: Sequence[datetime],
) -> dict[str, tuple[tuple[date, date], ...]]:
    """Resolve verified index membership into Qlib date spans over frozen sessions.

    Membership and availability are intersected with the supplied monotonic session and
    decision-time sequences. The returned spans are merged per Qlib identifier and preserve
    reentry gaps, so Qlib's native instrument date-range filter applies historical membership.
    """

    try:
        manifest = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if (
        manifest.view_hash != expected_view_hash
        or manifest.source_snapshot_hash != expected_snapshot_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "Qlib view or source snapshot hash does not match the resolved experiment",
        )
    ordered_sessions = tuple(sessions)
    ordered_decisions = tuple(decision_times)
    if (
        not ordered_sessions
        or ordered_sessions != tuple(sorted(set(ordered_sessions)))
        or len(ordered_sessions) != len(ordered_decisions)
        or any(
            decision.tzinfo is None or decision.utcoffset() is None or decision.date() != session
            for session, decision in zip(ordered_sessions, ordered_decisions, strict=True)
        )
        or ordered_decisions != tuple(sorted(ordered_decisions))
    ):
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "universe span sessions and decision times must be aligned and monotonic",
        )
    try:
        view_calendar = {
            date.fromisoformat(line.strip())
            for line in (view_path / "calendars" / "day.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "verified Qlib calendar could not be read"
        ) from error
    if any(session not in view_calendar for session in ordered_sessions):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "universe span sessions escape the verified Qlib calendar",
        )

    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        view_path / "sidecars" / "historical-universe.parquet"
    )
    spans_by_instrument: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for raw_row in table.to_pylist():
        row = cast(dict[str, object], raw_row)
        if row["index_id"] != index_id:
            continue
        effective_start = cast(date, row["effective_from"])
        effective_end = cast(date, row["effective_to"])
        available_at = cast(datetime, row["available_at"])
        start = max(
            bisect_left(ordered_sessions, effective_start),
            bisect_left(ordered_decisions, available_at),
        )
        end = bisect_right(ordered_sessions, effective_end)
        if start >= end:
            continue
        member = HistoricalUniverseMember(
            instrument_id=cast(str, row["instrument_id"]),
            qlib_id=cast(str, row["qlib_id"]),
            weight_percent=cast(float, row["weight_percent"]),
        )
        spans_by_instrument[member.qlib_id].append((start, end - 1))

    resolved: dict[str, tuple[tuple[date, date], ...]] = {}
    for instrument, spans in sorted(spans_by_instrument.items()):
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                raise QlibResearchError(
                    ReasonCode.SCHEMA_INVALID,
                    "historical universe contains overlapping membership intervals",
                )
            if merged and start == merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        resolved[instrument] = tuple(
            (ordered_sessions[start], ordered_sessions[end]) for start, end in merged
        )
    if not resolved:
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "historical universe has no effective and available members in the session range",
        )
    return resolved
