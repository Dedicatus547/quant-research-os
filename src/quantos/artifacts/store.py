"""Single-writer, content-addressed filesystem primitives."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
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
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise ArtifactIntegrityError("artifact file is unavailable") from error
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise ArtifactIntegrityError("artifact path must be a regular file, not a link")
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

        try:
            # A hard link is an atomic create-if-absent operation.  Unlike a
            # pre-check followed by os.replace, it cannot overwrite a winner
            # racing us between those two operations.
            os.link(temporary_path, path)
        except FileExistsError:
            if sha256_file(path) == digest:
                return digest
            raise ArtifactConflictError(f"immutable target already exists: {path}") from None
        temporary_path.unlink()
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


def _regular_tree(root: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    try:
        root_mode = root.lstat().st_mode
    except OSError as error:
        raise ArtifactIntegrityError("artifact root is unavailable") from error
    if root.is_symlink() or not stat.S_ISDIR(root_mode):
        raise ArtifactIntegrityError("artifact root must be a real directory")
    files: list[Path] = []
    directories: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda item: item.name)
        except OSError as error:
            raise ArtifactIntegrityError("artifact tree cannot be enumerated") from error
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                raise ArtifactIntegrityError("artifact tree contains a symbolic link")
            if entry.is_dir(follow_symlinks=False):
                directories.append(path)
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise ArtifactIntegrityError("artifact tree contains a non-regular object")
    return tuple(sorted(files)), tuple(sorted(directories))


def regular_tree_files(root: Path) -> tuple[Path, ...]:
    """List a tree while rejecting symlinks and non-regular filesystem objects."""

    files, _ = _regular_tree(root)
    return files


def confined_regular_file(root: Path, logical_path: str) -> Path:
    """Resolve an existing logical file without following any symbolic link."""

    from quantos.contracts.refs import validate_logical_path

    relative = Path(validate_logical_path(logical_path))
    if root.is_symlink() or not root.is_dir():
        raise ArtifactIntegrityError("artifact root must be a real directory")
    root_resolved = root.resolve(strict=True)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise ArtifactIntegrityError("artifact logical path is unavailable") from error
        if current.is_symlink():
            raise ArtifactIntegrityError("artifact logical path contains a symbolic link")
        if current != root / relative and not stat.S_ISDIR(mode):
            raise ArtifactIntegrityError("artifact logical path parent is not a directory")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as error:
        raise ArtifactIntegrityError("artifact logical path escaped its root") from error
    if not resolved.is_file():
        raise ArtifactIntegrityError("artifact logical path is not a regular file")
    return resolved


@contextmanager
def exclusive_directory_lock(path: Path) -> Generator[None, None, None]:
    """Serialize a multi-file authority mutation without creating lock artifacts."""

    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ArtifactIntegrityError("writer lock root must be a real directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        flock(descriptor, LOCK_EX)
        yield
    finally:
        flock(descriptor, LOCK_UN)
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    files, directories = _regular_tree(root)
    for path in files:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    for path in sorted(directories, reverse=True):
        _fsync_directory(path)
    _fsync_directory(root)


def publish_directory(staging: Path, destination: Path) -> None:
    """Publish a staged directory atomically on the same filesystem."""

    if not staging.is_dir():
        raise ArtifactError(f"staging directory does not exist: {staging}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if staging.stat().st_dev != destination.parent.stat().st_dev:
        raise ArtifactError("staging and destination must be on the same filesystem")
    _fsync_tree(staging)
    with exclusive_directory_lock(destination.parent):
        if destination.exists() or destination.is_symlink():
            raise ArtifactConflictError(f"immutable destination already exists: {destination}")
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
        path = confined_regular_file(self._root, reference.logical_path)
        verify_file(path, reference.sha256)
        raw = json.loads(path.read_bytes())
        return StoredEvent.model_validate(raw).event
