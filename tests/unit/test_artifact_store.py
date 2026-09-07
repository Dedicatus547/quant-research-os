from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from quantos.artifacts import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    ImmutableEventWriter,
    atomic_write_bytes,
    publish_directory,
    verify_file,
)
from quantos.contracts import EventType, ImmutableEvent


def test_atomic_write_is_idempotent_but_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    digest = atomic_write_bytes(target, b"first")

    assert atomic_write_bytes(target, b"first") == digest
    with pytest.raises(ArtifactConflictError):
        atomic_write_bytes(target, b"second")
    assert target.read_bytes() == b"first"


def test_atomic_write_never_overwrites_under_concurrent_writers(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"

    def publish(payload: bytes) -> str:
        try:
            atomic_write_bytes(target, payload)
        except ArtifactConflictError:
            return "conflict"
        return "published"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(publish, (bytes([index]) for index in range(8))))

    assert outcomes.count("published") == 1
    assert outcomes.count("conflict") == 7
    assert target.read_bytes() in {bytes([index]) for index in range(8)}


def test_verify_file_detects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    digest = atomic_write_bytes(target, b"trusted")
    target.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        verify_file(target, digest)


def test_verify_file_and_directory_publish_reject_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"trusted")
    linked = tmp_path / "linked"
    linked.symlink_to(outside)
    with pytest.raises(ArtifactIntegrityError, match="regular file"):
        verify_file(linked, __import__("hashlib").sha256(b"trusted").hexdigest())

    staging = tmp_path / "staging-linked"
    staging.mkdir()
    (staging / "payload").symlink_to(outside)
    with pytest.raises(ArtifactIntegrityError, match="symbolic link"):
        publish_directory(staging, tmp_path / "published-linked")


def test_publish_directory_uses_immutable_destination(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "published" / "sha256-abc"

    publish_directory(staging, destination)

    assert not staging.exists()
    assert (destination / "manifest.json").read_text(encoding="utf-8") == "{}"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    with pytest.raises(ArtifactConflictError):
        publish_directory(replacement, destination)


def test_publish_directory_serializes_concurrent_writers(tmp_path: Path) -> None:
    destination = tmp_path / "published" / "sha256-race"
    staging_roots: list[Path] = []
    for index in range(8):
        staging = tmp_path / f"staging-{index}"
        staging.mkdir()
        (staging / "payload").write_bytes(bytes([index]))
        staging_roots.append(staging)

    def publish(staging: Path) -> str:
        try:
            publish_directory(staging, destination)
        except ArtifactConflictError:
            return "conflict"
        return "published"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(publish, staging_roots))

    assert outcomes.count("published") == 1
    assert outcomes.count("conflict") == 7
    assert (destination / "payload").read_bytes() in {bytes([index]) for index in range(8)}


def test_event_writer_is_hashed_idempotent_and_readable(tmp_path: Path) -> None:
    writer = ImmutableEventWriter(tmp_path / "events")
    event = ImmutableEvent(
        event_id=UUID("12345678-1234-5678-1234-567812345678"),
        aggregate_id="experiment-001",
        event_type=EventType.OOS_ACCESSED,
        occurred_at=datetime(2024, 1, 2, tzinfo=UTC),
        payload={"split": "out_of_sample"},
    )

    first = writer.append(event)
    second = writer.append(event)

    assert first == second
    assert writer.read(first) == event


def test_event_writer_rejects_conflicting_event_id(tmp_path: Path) -> None:
    writer = ImmutableEventWriter(tmp_path / "events")
    base = ImmutableEvent(
        event_id=UUID("12345678-1234-5678-1234-567812345678"),
        aggregate_id="experiment-001",
        event_type=EventType.OOS_ACCESSED,
        occurred_at=datetime(2024, 1, 2, tzinfo=UTC),
        payload={"split": "out_of_sample"},
    )
    writer.append(base)

    with pytest.raises(ArtifactConflictError):
        writer.append(base.model_copy(update={"payload": {"split": "changed"}}))
