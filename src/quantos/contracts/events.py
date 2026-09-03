"""Minimal immutable event envelope used before the registry exists."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN


class EventType(StrEnum):
    OOS_ACCESSED = "OOSAccessed"
    STRATEGY_CREATED = "StrategyCreated"
    VALIDATION_STARTED = "ValidationStarted"
    VALIDATION_REJECTED = "ValidationRejected"
    VALIDATION_PASSED = "ValidationPassed"
    STRATEGY_VERSION_VALIDATED = "StrategyVersionValidated"


class ImmutableEvent(CanonicalContract):
    schema_version: Literal["event/v1"] = "event/v1"
    event_id: UUID
    aggregate_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime
    payload: dict[str, JsonValue]
    previous_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value
