"""Cited derived research memory, indexed by the existing history catalog.

These records describe original evidence. They grant neither execution permission nor
scientific qualification; free-text explanations always remain model annotations.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from pydantic import Field, model_validator

from quantos.application.personal_evidence import explicit_root
from quantos.artifacts.store import (
    atomic_write_bytes_at,
    confined_regular_file,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.security.artifact_secrets import validate_secret_free

if TYPE_CHECKING:
    from quantos.application.personal_history import PersonalHistoryService

MEMORY_ORIGIN = "DERIVED_MEMORY_REFERENCES_NOT_NEW_VALIDATION"
MAX_SOURCE_BYTES = 2 * 1024**2
MAX_TOTAL_SOURCE_BYTES = 8 * 1024**2
MAX_RECORD_BYTES = 256 * 1024


class MemoryNotAvailableError(ValueError):
    """A record or one of its sources cannot be used at the requested time."""


def aware_time(value: str | datetime) -> datetime:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("memory time must include a timezone")
    return stamp.astimezone(UTC)


class MemorySource(CanonicalContract):
    schema_version: Literal["personal-memory-source/v1"] = "personal-memory-source/v1"
    source_id: str = Field(pattern=r"[a-z0-9_-]{1,64}")
    path: str = Field(max_length=2048)
    sha256: str = Field(pattern=SHA256_PATTERN)
    available_at: datetime | None = None
    scope: Literal["ORIGINAL_RESULT", "DERIVED_DIAGNOSTIC", "REPORT_ONLY", "AUXILIARY"]
    format: Literal["JSON", "TEXT"] = "JSON"

    @model_validator(mode="after")
    def bounded_source(self) -> MemorySource:
        validate_logical_path(self.path)
        if any("sealed" in part.casefold() for part in Path(self.path).parts):
            raise ValueError("sealed evidence is outside memory scope")
        if self.available_at is not None:
            aware_time(self.available_at)
        return self


class MemoryObservation(CanonicalContract):
    schema_version: Literal["personal-memory-observation/v1"] = "personal-memory-observation/v1"
    name: str = Field(min_length=1, max_length=160)
    source_id: str = Field(pattern=r"[a-z0-9_-]{1,64}")
    pointer: str = Field(max_length=512)
    definition: str = Field(min_length=1, max_length=2000)


class MemoryAnnotation(CanonicalContract):
    schema_version: Literal["personal-memory-annotation/v1"] = "personal-memory-annotation/v1"
    kind: Literal["MODEL_INTERPRETATION", "ENGINEERING_EXPERIENCE"]
    text: str = Field(min_length=1, max_length=4000)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=16)


class MemoryDraft(CanonicalContract):
    schema_version: Literal["personal-memory-draft/v1"] = "personal-memory-draft/v1"
    record_id: str = Field(pattern=r"[a-z0-9_-]{1,96}")
    label: str = Field(min_length=1, max_length=240)
    hypothesis: str = Field(min_length=1, max_length=4000)
    expectation: str = Field(min_length=1, max_length=4000)
    universe: str = Field(min_length=1, max_length=1000)
    period: str = Field(min_length=1, max_length=1000)
    data_scenario: str = Field(min_length=1, max_length=2000)
    cost_scenario: str = Field(min_length=1, max_length=2000)
    tags: tuple[str, ...] = Field(min_length=1, max_length=16)
    sources: tuple[MemorySource, ...] = Field(min_length=1, max_length=16)
    observations: tuple[MemoryObservation, ...] = Field(min_length=1, max_length=64)
    annotations: tuple[MemoryAnnotation, ...] = Field(default=(), max_length=16)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=16)
    invalidation_conditions: tuple[str, ...] = Field(default=(), max_length=16)
    unanswered_questions: tuple[str, ...] = Field(default=(), max_length=16)
    recommendation: Literal["CONTINUE", "STOP", "UNDECIDED"] = "UNDECIDED"
    recommendation_reason: str = Field(min_length=1, max_length=4000)
    revises_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def cited_and_bounded(self) -> MemoryDraft:
        ids = {source.source_id for source in self.sources}
        if len(ids) != len(self.sources):
            raise ValueError("memory source IDs must be unique")
        if any(item.source_id not in ids for item in self.observations) or any(
            not set(item.source_ids) <= ids for item in self.annotations
        ):
            raise ValueError("memory statements must cite declared sources")
        if len(set(self.tags)) != len(self.tags) or any(
            re.fullmatch(r"[a-z0-9_-]{1,64}", tag) is None for tag in self.tags
        ):
            raise ValueError("memory tags must be unique bounded logical labels")
        text_items = self.uncertainties + self.invalidation_conditions + self.unanswered_questions
        if any(not 1 <= len(text) <= 2000 for text in text_items):
            raise ValueError("memory uncertainty text exceeds limits")
        return self


class MemoryRecord(CanonicalContract):
    schema_version: Literal["personal-research-memory/v1"] = "personal-research-memory/v1"
    draft: MemoryDraft
    recorded_at: datetime
    observations: tuple[dict[str, Any], ...]
    authority: Literal["DERIVED_REFERENCES_ORIGINALS_REMAIN_AUTHORITY"] = (
        "DERIVED_REFERENCES_ORIGINALS_REMAIN_AUTHORITY"
    )
    qualification_granted: Literal[False] = False
    new_execution: Literal[False] = False

    @model_validator(mode="after")
    def aware_record_time(self) -> MemoryRecord:
        aware_time(self.recorded_at)
        if any(
            source.available_at is not None and source.available_at > self.recorded_at
            for source in self.draft.sources
        ):
            raise ValueError("memory record predates its source availability")
        return self


def json_pointer(value: Any, pointer: str) -> Any:
    """Resolve a bounded RFC 6901 pointer; no code or expression evaluation."""
    if pointer == "":
        return value
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("invalid memory JSON pointer")
    try:
        for part in pointer[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if re.fullmatch(r"0|[1-9][0-9]*", key) is None:
                    raise ValueError("invalid memory array index")
                value = cast(list[Any], value)[int(key)]
            elif isinstance(value, dict):
                value = cast(dict[str, Any], value)[key]
            else:
                raise ValueError("memory pointer enters a scalar")
    except (KeyError, IndexError) as error:
        raise ValueError("memory pointer is missing from original") from error
    return value


class PersonalMemoryService:
    """Append derived JSON and reuse history-catalog/v1 for discovery.

    The local clock stamps first publication. Draft timestamps cannot backdate a
    record; unknown source availability is excluded from an explicit as_of query.
    """

    def __init__(
        self, root: Path, repo_root: Path, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.root = explicit_root(root)
        self.repo_root = explicit_root(repo_root)
        self.root.relative_to(self.repo_root)
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)

    def _history(self) -> PersonalHistoryService:
        from quantos.application.personal_history import PersonalHistoryService

        return PersonalHistoryService(self.root, self.repo_root)

    def _values(
        self, draft: MemoryDraft, as_of: datetime | None = None
    ) -> tuple[dict[str, Any], ...]:
        documents: dict[str, Any] = {}
        total = 0
        for source in draft.sources:
            if as_of is not None and (source.available_at is None or source.available_at > as_of):
                raise MemoryNotAvailableError("memory source availability unknown or after as_of")
            path = confined_regular_file(self.repo_root, source.path)
            with opened_directory(path.parent) as directory:
                raw = read_regular_bytes_at(directory, path.name, max_bytes=MAX_SOURCE_BYTES)
            total += len(raw)
            if total > MAX_TOTAL_SOURCE_BYTES or sha256_bytes(raw) != source.sha256:
                raise ValueError("memory source identity or read budget disagrees")
            documents[source.source_id] = json.loads(raw) if source.format == "JSON" else None
        values: list[dict[str, Any]] = []
        for item in draft.observations:
            if documents[item.source_id] is None:
                raise ValueError("text reports cannot be represented as JSON facts")
            value = json_pointer(documents[item.source_id], item.pointer)
            if len(canonical_json_bytes(value)) > 32_768:
                raise ValueError("memory observation exceeds bounded output")
            values.append({**item.model_dump(mode="json"), "value": value})
        return tuple(values)

    def read_entry(self, entry: dict[str, Any], as_of: datetime | None = None) -> MemoryRecord:
        path = confined_regular_file(self.repo_root, entry["path"])
        with opened_directory(path.parent) as directory:
            raw = read_regular_bytes_at(directory, path.name, max_bytes=MAX_RECORD_BYTES)
        if sha256_bytes(raw) != entry["sha256"]:
            raise ValueError("memory record identity disagrees")
        record = MemoryRecord.model_validate_json(raw)
        if record.canonical_bytes() != raw or record.draft.record_id != entry["record_id"]:
            raise ValueError("memory record or index binding disagrees")
        if as_of is not None and record.recorded_at > as_of:
            raise MemoryNotAvailableError("memory record is after as_of")
        actual = self._values(record.draft, as_of)
        if canonical_json_bytes(actual) != canonical_json_bytes(record.observations):
            raise ValueError("memory observations disagree with cited originals")
        return record

    def append(self, value: dict[str, Any] | MemoryDraft) -> dict[str, Any]:
        draft = value if isinstance(value, MemoryDraft) else MemoryDraft.model_validate(value)
        validate_secret_free(draft.model_dump(mode="json"), file_name="memory-draft.json")
        now = aware_time(self.clock())
        if any(
            source.available_at is not None and source.available_at > now
            for source in draft.sources
        ):
            raise ValueError("memory cannot cite a future source")
        self.root.mkdir(parents=True, exist_ok=True)
        relative = self.root.relative_to(self.repo_root)
        with exclusive_directory_lock(self.root):
            entries = self._history().entries()
            existing = next((e for e in entries if e["record_id"] == draft.record_id), None)
            if existing is not None:
                record = self.read_entry(existing)
                if record.draft != draft:
                    raise ValueError("memory ID is immutable; append an explicit revision")
                return {
                    "reference": existing,
                    "record": record.model_dump(mode="json"),
                    "reused": True,
                }
            if len(entries) >= 100:
                raise ValueError("history catalog exceeds bounded record count")
            if draft.revises_hash is not None and not any(
                e["sha256"] == draft.revises_hash and e["origin"] == MEMORY_ORIGIN for e in entries
            ):
                raise ValueError("memory revision must name an indexed predecessor")
            if draft.revises_hash is not None:
                predecessor = next(e for e in entries if e["sha256"] == draft.revises_hash)
                self.read_entry(predecessor)
            observations = self._values(draft)
            records_root = self.root / "history-derived"
            # Request-addressed immutable file recovers a crash after record publication
            # and before index publication, keeping the original server timestamp.
            name = f"request-{draft.content_hash}.json"
            with opened_directory(records_root, create=True) as directory:
                try:
                    os.stat(name, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    record = MemoryRecord(draft=draft, recorded_at=now, observations=observations)
                    raw = record.canonical_bytes()
                    if len(raw) > MAX_RECORD_BYTES:
                        raise ValueError("memory record exceeds byte limit") from None
                    validate_secret_free(
                        record.model_dump(mode="json"), file_name="memory-record.json"
                    )
                    atomic_write_bytes_at(directory, name, raw)
                else:
                    raw = read_regular_bytes_at(directory, name, max_bytes=MAX_RECORD_BYTES)
                    record = MemoryRecord.model_validate_json(raw)
                    if (
                        record.canonical_bytes() != raw
                        or record.draft != draft
                        or canonical_json_bytes(record.observations)
                        != canonical_json_bytes(observations)
                    ):
                        raise ValueError("unindexed memory record disagrees with original request")
            entry = {
                "record_id": draft.record_id,
                "label": draft.label,
                "path": (relative / "history-derived" / name).as_posix(),
                "sha256": sha256_bytes(raw),
                "origin": MEMORY_ORIGIN,
            }
            index = canonical_json_bytes(
                {"schema_version": "personal-history-catalog/v1", "records": [*entries, entry]}
            )
            if len(index) > 128_000:
                raise ValueError("history catalog exceeds byte limit")
            with opened_directory(self.root) as directory:
                temp = f".memory-index-{uuid4().hex}"
                atomic_write_bytes_at(directory, temp, index)
                os.replace(temp, "history-catalog.json", src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            return {"reference": entry, "record": record.model_dump(mode="json"), "reused": False}

    def read(self, record_id: str, as_of: str | None = None) -> dict[str, Any]:
        stamp = aware_time(as_of) if as_of is not None else None
        entry = next(
            (
                e
                for e in self._history().entries()
                if e["record_id"] == record_id and e["origin"] == MEMORY_ORIGIN
            ),
            None,
        )
        if entry is None:
            raise ValueError("memory record is not in the explicit history catalog")
        record = self.read_entry(entry, stamp)
        return {
            "reference": entry,
            "original": record.model_dump(mode="json"),
            "adoption": "DERIVED_REFERENCES_NO_NEW_VALIDATION_OR_EXECUTION",
        }

    def diagnostic_report(self, record_id: str, as_of: str | None = None) -> dict[str, Any]:
        """Return a bounded, reverified report; annotation prose grants no qualification."""
        retained = self.read(record_id, as_of)
        record = MemoryRecord.model_validate(retained["original"])
        draft = record.draft
        return {
            "reference": retained["reference"],
            "hypothesis": draft.hypothesis,
            "expectation": draft.expectation,
            "scope": {
                "universe": draft.universe,
                "period": draft.period,
                "data_scenario": draft.data_scenario,
                "cost_scenario": draft.cost_scenario,
            },
            "observations": list(record.observations),
            "source_references": [source.model_dump(mode="json") for source in draft.sources],
            "annotations": [item.model_dump(mode="json") for item in draft.annotations],
            "uncertainties": list(draft.uncertainties),
            "invalidation_conditions": list(draft.invalidation_conditions),
            "unanswered_questions": list(draft.unanswered_questions),
            "recommendation": draft.recommendation,
            "recommendation_reason": draft.recommendation_reason,
            "qualification_granted": False,
            "new_execution": False,
            "adoption": retained["adoption"],
        }

    def search(
        self,
        query: str = "",
        limit: int = 20,
        *,
        tags: tuple[str, ...] = (),
        as_of: str | None = None,
    ) -> dict[str, Any]:
        return self._history().search(query=query, limit=limit, tags=tags, as_of=as_of)
