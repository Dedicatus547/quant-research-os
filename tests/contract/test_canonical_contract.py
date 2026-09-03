from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

import pytest
from pydantic import ValidationError

from quantos.contracts import CanonicalContract, canonical_json_bytes


class ExampleContract(CanonicalContract):
    schema_version: Literal["example/v1"] = "example/v1"
    name: str
    value: float = 1.0
    timestamp: datetime


def test_hash_is_stable_and_datetime_is_normalized_to_utc() -> None:
    first = ExampleContract(
        name="alpha",
        timestamp=datetime(2024, 1, 2, 8, tzinfo=UTC),
    )
    second = ExampleContract(
        timestamp=datetime(2024, 1, 2, 16, tzinfo=timezone(timedelta(hours=8))),
        value=1.0,
        name="alpha",
    )

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.content_hash == second.content_hash
    assert b'"value":1.0' in first.canonical_bytes()
    assert b"2024-01-02T08:00:00.000000Z" in first.canonical_bytes()


def test_contract_rejects_extra_fields_and_non_finite_numbers() -> None:
    with pytest.raises(ValidationError):
        ExampleContract(
            name="alpha",
            timestamp=datetime.now(UTC),
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        ExampleContract(
            name="alpha",
            timestamp=datetime.now(UTC),
            value=float("nan"),
        )


def test_canonical_json_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(ValueError, match="keys must be strings"):
        canonical_json_bytes({1: "invalid"})
