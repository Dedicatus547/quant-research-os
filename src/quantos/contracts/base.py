"""Deterministic contract serialization and hashing."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class CanonicalizationError(ValueError):
    """Raised when a value cannot enter the canonical JSON domain."""


def _normalize(value: Any) -> object:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CanonicalizationError("datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError("Decimal must be finite")
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("float must be finite")
        return value
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        mapping = cast(Mapping[object, object], value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical JSON object keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return [_normalize(item) for item in sequence]
    raise CanonicalizationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a value using the project's deterministic JSON encoding."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CanonicalContract(BaseModel):
    """Base for immutable, strict, content-addressable public contracts."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def schema_version_is_declared(cls, value: object) -> object:
        if "schema_version" not in cls.model_fields:
            raise ValueError("every concrete contract must declare schema_version")
        return value

    def canonical_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="python", exclude=set(self.hash_exclude_fields))
        normalized = _normalize(payload)
        if not isinstance(normalized, dict):  # pragma: no cover - model_dump is always a mapping
            raise CanonicalizationError("contract payload must be an object")
        return cast(dict[str, object], normalized)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_payload())

    @property
    def content_hash(self) -> str:
        return sha256_bytes(self.canonical_bytes())
