"""Deterministic decision schedules resolved from a verified Qlib calendar."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.research.qlib.universe import QlibResearchError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def weekly_decision_schedules(
    calendar: Sequence[date],
    *,
    evaluation_start: date,
    evaluation_end: date,
) -> tuple[DecisionSchedule, ...]:
    """Resolve final-session-of-week signals and next-session executions.

    The v1 operational schedule computes after the canonical 15:30 availability
    boundary, allows one minute for the locked expression operator delay, makes
    the decision at 16:10, and delegates execution to the next 09:30 session.
    """

    sessions = tuple(calendar)
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise ValueError("calendar must be nonempty, sorted, and unique")
    if evaluation_start > evaluation_end:
        raise ValueError("evaluation range is invalid")

    schedules: list[DecisionSchedule] = []
    for position, signal_date in enumerate(sessions[:-1]):
        execution_date = sessions[position + 1]
        if not evaluation_start <= signal_date <= evaluation_end:
            continue
        if execution_date.isocalendar()[:2] == signal_date.isocalendar()[:2]:
            continue
        schedules.append(
            DecisionSchedule(
                signal_time=datetime.combine(signal_date, time(16, 0), tzinfo=SHANGHAI),
                signal_available_at=datetime.combine(signal_date, time(16, 1), tzinfo=SHANGHAI),
                decision_time=datetime.combine(signal_date, time(16, 10), tzinfo=SHANGHAI),
                execution_time=datetime.combine(execution_date, time(9, 30), tzinfo=SHANGHAI),
            )
        )
    if not schedules:
        raise ValueError("evaluation range has no complete weekly decision schedule")
    return tuple(schedules)


def resolve_weekly_decision_schedules(
    view_path: Path,
    *,
    expected_view_hash: str,
    evaluation_start: date,
    evaluation_end: date,
) -> tuple[DecisionSchedule, ...]:
    """Resolve schedules only after the Qlib view and its calendar verify."""

    try:
        manifest = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if manifest.view_hash != expected_view_hash:
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "schedule view hash does not match the verified Qlib view",
        )
    try:
        calendar = tuple(
            date.fromisoformat(line.strip())
            for line in (view_path / "calendars" / "day.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
        return weekly_decision_schedules(
            calendar,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "verified Qlib calendar cannot resolve the weekly decision schedule",
        ) from error
