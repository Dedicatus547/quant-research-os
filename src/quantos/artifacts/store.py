"""Single-writer, content-addressed filesystem primitives."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.events import ImmutableEvent
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef


class ArtifactError(RuntimeError):
    """Base error for artifact publication and verification."""


class ArtifactConflictError(ArtifactError):
    """Raised when an immutable target already contains different bytes."""


class ArtifactIntegrityError(ArtifactError):
    """Raised when content does not match its expected digest."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, expected_sha256: str | None = None) -> str:
    """Atomically publish immutable bytes and return their SHA-256 digest."""

    digest = sha256_bytes(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ArtifactIntegrityError("payload does not match expected SHA-256")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        if path.exists():
            if sha256_file(path) == digest:
                temporary_path.unlink()
                return digest
            raise ArtifactConflictError(f"immutable target already exists: {path}")

        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
        return digest
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: object) -> str:
    return atomic_write_bytes(path, canonical_json_bytes(payload))


def verify_file(path: Path, expected_sha256: str) -> None:
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ArtifactIntegrityError(
            f"artifact hash mismatch: expected {expected_sha256}, got {actual_sha256}"
        )


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        _fsync_directory(path)
    _fsync_directory(root)


def publish_directory(staging: Path, destination: Path) -> None:
    """Publish a staged directory atomically on the same filesystem."""

    if not staging.is_dir():
        raise ArtifactError(f"staging directory does not exist: {staging}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if staging.stat().st_dev != destination.parent.stat().st_dev:
        raise ArtifactError("staging and destination must be on the same filesystem")
    if destination.exists():
        raise ArtifactConflictError(f"immutable destination already exists: {destination}")

    _fsync_tree(staging)
    os.replace(staging, destination)
    _fsync_directory(destination.parent)


class StoredEvent(CanonicalContract):
    schema_version: Literal["stored-event/v1"] = "stored-event/v1"
    event: ImmutableEvent
    event_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def event_hash_matches(self) -> Self:
        if self.event_hash != self.event.content_hash:
            raise ValueError("event_hash does not match event content")
        return self


def _safe_segment(value: str) -> str:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ArtifactError("event aggregate_id must be a single safe path segment")
    return value


class ImmutableEventWriter:
    """Append immutable events without introducing a registry or database."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def append(self, event: ImmutableEvent) -> ArtifactRef:
        aggregate_id = _safe_segment(event.aggregate_id)
        relative_path = Path(aggregate_id) / f"{event.event_id}.json"
        stored = StoredEvent(event=event, event_hash=event.content_hash)
        encoded = stored.canonical_bytes()
        digest = atomic_write_bytes(self._root / relative_path, encoded)
        return ArtifactRef(
            kind="event",
            sha256=digest,
            size_bytes=len(encoded),
            media_type="application/json",
            logical_path=relative_path.as_posix(),
        )

    def read(self, reference: ArtifactRef) -> ImmutableEvent:
        path = self._root / reference.logical_path
        verify_file(path, reference.sha256)
        raw = json.loads(path.read_bytes())
        return StoredEvent.model_validate(raw).event
