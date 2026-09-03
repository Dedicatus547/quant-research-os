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


def test_verify_file_detects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    digest = atomic_write_bytes(target, b"trusted")
    target.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        verify_file(target, digest)


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
