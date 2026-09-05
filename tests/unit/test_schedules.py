from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from quantos.application import schedules
from quantos.application.schedules import (
    resolve_weekly_decision_schedules,
    weekly_decision_schedules,
)
from quantos.contracts.status import ReasonCode
from quantos.data.qlib_view import QlibViewBuildError
from quantos.research.qlib import QlibResearchError


def test_weekly_schedule_uses_final_session_and_next_open() -> None:
    calendar = (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 12),
        date(2024, 1, 15),
    )

    schedules = weekly_decision_schedules(
        calendar,
        evaluation_start=date(2024, 1, 1),
        evaluation_end=date(2024, 1, 31),
    )

    assert [item.signal_time.date() for item in schedules] == [
        date(2024, 1, 5),
        date(2024, 1, 12),
    ]
    assert [item.execution_time.date() for item in schedules] == [
        date(2024, 1, 8),
        date(2024, 1, 15),
    ]
    assert schedules[0].signal_time.hour == 16
    assert schedules[0].signal_available_at.minute == 1
    assert schedules[0].decision_time.minute == 10
    assert schedules[0].execution_time.hour == 9
    assert schedules[0].execution_time.minute == 30


def test_weekly_schedule_rejects_unordered_or_incomplete_calendars() -> None:
    with pytest.raises(ValueError, match="sorted"):
        weekly_decision_schedules(
            (date(2024, 1, 5), date(2024, 1, 4)),
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 1, 31),
        )


def test_schedule_resolver_verifies_bound_view_and_calendar(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view_hash = "a" * 64
    view = tmp_path / f"sha256-{view_hash}"
    calendar = view / "calendars"
    calendar.mkdir(parents=True)
    (calendar / "day.txt").write_text("2024-01-04\n2024-01-05\n2024-01-08\n", encoding="utf-8")
    monkeypatch.setattr(
        schedules, "verify_qlib_view", lambda _path: SimpleNamespace(view_hash=view_hash)
    )

    resolved = resolve_weekly_decision_schedules(
        view,
        expected_view_hash=view_hash,
        evaluation_start=date(2024, 1, 1),
        evaluation_end=date(2024, 1, 31),
    )
    assert resolved[0].signal_time.date() == date(2024, 1, 5)

    with pytest.raises(QlibResearchError) as mismatch:
        resolve_weekly_decision_schedules(
            view,
            expected_view_hash="b" * 64,
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 1, 31),
        )
    assert mismatch.value.reason_code is ReasonCode.SNAPSHOT_HASH_MISMATCH

    (calendar / "day.txt").write_text("invalid\n", encoding="utf-8")
    with pytest.raises(QlibResearchError) as corrupted:
        resolve_weekly_decision_schedules(
            view,
            expected_view_hash=view_hash,
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 1, 31),
        )
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    def fail_verification(_path) -> object:
        raise QlibViewBuildError(ReasonCode.ARTIFACT_CORRUPTED, "invalid view")

    monkeypatch.setattr(schedules, "verify_qlib_view", fail_verification)
    with pytest.raises(QlibResearchError) as invalid_view:
        resolve_weekly_decision_schedules(
            view,
            expected_view_hash=view_hash,
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 1, 31),
        )
    assert invalid_view.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
    with pytest.raises(ValueError, match="no complete"):
        weekly_decision_schedules(
            (date(2024, 1, 5),),
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 1, 31),
        )
    with pytest.raises(ValueError, match="evaluation range"):
        weekly_decision_schedules(
            (date(2024, 1, 5), date(2024, 1, 8)),
            evaluation_start=date(2024, 2, 1),
            evaluation_end=date(2024, 1, 1),
        )
