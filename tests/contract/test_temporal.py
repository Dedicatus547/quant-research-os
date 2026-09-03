from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    AvailabilityEvidenceLevel,
    DecisionSchedule,
    ReasonCode,
    TemporalMetadata,
    TemporalPolicyError,
)

UTC = UTC


def test_temporal_metadata_is_usable_at_decision_time() -> None:
    metadata = TemporalMetadata(
        event_time=datetime(2024, 1, 2, 7, tzinfo=UTC),
        known_at=datetime(2024, 1, 2, 7, 1, tzinfo=UTC),
        available_at=datetime(2024, 1, 2, 7, 5, tzinfo=UTC),
        observed_at=datetime(2024, 1, 2, 8, tzinfo=UTC),
        evidence_level=AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED,
        policy_id="daily-close/v1",
    )

    metadata.assert_usable_at(datetime(2024, 1, 2, 7, 5, tzinfo=UTC))


def test_future_or_unknown_data_is_rejected_with_stable_reason() -> None:
    metadata = TemporalMetadata(
        event_time=datetime(2024, 1, 2, 7, tzinfo=UTC),
        known_at=datetime(2024, 1, 2, 7, tzinfo=UTC),
        available_at=datetime(2024, 1, 2, 8, tzinfo=UTC),
        observed_at=datetime(2024, 1, 2, 8, tzinfo=UTC),
        evidence_level=AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED,
        policy_id="daily-close/v1",
    )
    with pytest.raises(TemporalPolicyError) as captured:
        metadata.assert_usable_at(datetime(2024, 1, 2, 7, 59, tzinfo=UTC))
    assert captured.value.reason_code is ReasonCode.LOOK_AHEAD

    unknown = metadata.model_copy(update={"evidence_level": AvailabilityEvidenceLevel.UNKNOWN})
    with pytest.raises(TemporalPolicyError) as captured_unknown:
        unknown.assert_usable_at(datetime(2024, 1, 2, 9, tzinfo=UTC))
    assert captured_unknown.value.reason_code is ReasonCode.UNKNOWN_AVAILABILITY


def test_schedule_enforces_strictly_later_execution() -> None:
    signal_time = datetime(2024, 1, 2, 8, tzinfo=UTC)
    valid = DecisionSchedule(
        signal_time=signal_time,
        signal_available_at=signal_time,
        decision_time=signal_time + timedelta(minutes=1),
        execution_time=signal_time + timedelta(days=1),
    )
    assert valid.execution_time > valid.decision_time

    with pytest.raises(ValidationError, match="schedule must satisfy"):
        DecisionSchedule(
            signal_time=signal_time,
            signal_available_at=signal_time,
            decision_time=signal_time + timedelta(days=1),
            execution_time=signal_time + timedelta(days=1),
        )


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DecisionSchedule(
            signal_time=datetime(2024, 1, 2),
            signal_available_at=datetime(2024, 1, 2, tzinfo=UTC),
            decision_time=datetime(2024, 1, 3, tzinfo=UTC),
            execution_time=datetime(2024, 1, 4, tzinfo=UTC),
        )
