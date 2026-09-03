"""Availability evidence and point-in-time schedule contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.status import ReasonCode


class AvailabilityEvidenceLevel(StrEnum):
    EXPLICIT_SOURCE_TIMESTAMP = "EXPLICIT_SOURCE_TIMESTAMP"
    DOCUMENTED_UPDATE_SCHEDULE = "DOCUMENTED_UPDATE_SCHEDULE"
    CONSERVATIVE_DERIVED = "CONSERVATIVE_DERIVED"
    OBSERVED_ONLY = "OBSERVED_ONLY"
    UNKNOWN = "UNKNOWN"


class TemporalPolicyError(ValueError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class TemporalMetadata(CanonicalContract):
    schema_version: Literal["temporal-metadata/v1"] = "temporal-metadata/v1"
    event_time: datetime
    known_at: datetime
    available_at: datetime
    observed_at: datetime
    evidence_level: AvailabilityEvidenceLevel
    policy_id: str

    @field_validator("event_time", "known_at", "available_at", "observed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_temporal_order(self) -> Self:
        if self.event_time > self.known_at:
            raise ValueError("known_at cannot precede event_time")
        if self.known_at > self.available_at:
            raise ValueError("available_at cannot precede known_at")
        if self.event_time > self.observed_at:
            raise ValueError("observed_at cannot precede event_time")
        if (
            self.evidence_level is AvailabilityEvidenceLevel.OBSERVED_ONLY
            and self.available_at < self.observed_at
        ):
            raise ValueError("OBSERVED_ONLY data cannot be available before observed_at")
        return self

    def assert_usable_at(self, decision_time: datetime) -> None:
        _require_aware(decision_time)
        if self.evidence_level is AvailabilityEvidenceLevel.UNKNOWN:
            raise TemporalPolicyError(
                ReasonCode.UNKNOWN_AVAILABILITY,
                "UNKNOWN availability cannot enter a canonical experiment",
            )
        if self.available_at > decision_time:
            raise TemporalPolicyError(
                ReasonCode.LOOK_AHEAD,
                "record is not available at decision_time",
            )


class DecisionSchedule(CanonicalContract):
    schema_version: Literal["decision-schedule/v1"] = "decision-schedule/v1"
    signal_time: datetime
    signal_available_at: datetime
    decision_time: datetime
    execution_time: datetime

    @field_validator("signal_time", "signal_available_at", "decision_time", "execution_time")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if not (
            self.signal_time <= self.signal_available_at <= self.decision_time < self.execution_time
        ):
            raise ValueError(
                "schedule must satisfy signal_time <= signal_available_at "
                "<= decision_time < execution_time"
            )
        return self
