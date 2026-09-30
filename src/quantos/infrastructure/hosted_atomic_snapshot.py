"""Explicit safe forensic copies, distinct from original physical authority.

Each alias gets separate copied bytes. The original inode/link facts remain a
separate immutable record; copies never stand in for canonical source authority.
"""

from __future__ import annotations

import os
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, opened_directory
from quantos.contracts.hosted_qualification import HostedQualificationFile, HostedRawInventory
from quantos.infrastructure.hosted_atomic_forensics import (
    HostedAtomicForensicInventory,
    atomic_forensic_inventory,
)
from quantos.infrastructure.hosted_verification import (
    directory_inventory,
    raw_inventory,
    read_relative,
)


def forensic_byte_view(facts: HostedAtomicForensicInventory) -> HostedRawInventory:
    """Describe bytes only; this does not assert single-link canonical authority."""
    return HostedRawInventory(
        files=tuple(
            HostedQualificationFile(
                logical_path=file.logical_path, sha256=file.sha256, size_bytes=file.size_bytes
            )
            for file in facts.files
        )
    )


def _ancestor_identities(descriptor: int) -> frozenset[tuple[int, int]]:
    """Read pinned physical ancestry, including bind aliases, without mutation."""
    current = os.dup(descriptor)
    seen: set[tuple[int, int]] = set()
    try:
        for _ in range(1024):
            metadata = os.fstat(current)
            identity = metadata.st_dev, metadata.st_ino
            if identity in seen:
                return frozenset(seen)
            seen.add(identity)
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = parent
        raise ArtifactIntegrityError("atomic snapshot physical ancestry exceeds limit")
    finally:
        os.close(current)


def _require_disjoint_outputs(authority: Path, channel: Path, outputs: tuple[Path, ...]) -> None:
    """Reject overlap before creating any copied directory or sidecar."""
    source = authority.absolute()
    with opened_directory(source) as source_fd:
        metadata = os.fstat(source_fd)
        source_identity = metadata.st_dev, metadata.st_ino
        source_ancestors = _ancestor_identities(source_fd)
        for output in (channel, *outputs):
            destination = output.absolute()
            if destination.is_relative_to(source) or source.is_relative_to(destination):
                raise ArtifactIntegrityError("atomic snapshot source and outputs must be disjoint")
            # Pin every already existing component with O_NOFOLLOW. The nearest
            # existing parent bounds fresh children; no mkdir happens here.
            existing = destination
            while not existing.exists() and not existing.is_symlink():
                existing = existing.parent
            with opened_directory(existing) as destination_fd:
                destination_metadata = os.fstat(destination_fd)
                destination_identity = destination_metadata.st_dev, destination_metadata.st_ino
                if (
                    source_identity in _ancestor_identities(destination_fd)
                    or destination_identity in source_ancestors
                ):
                    raise ArtifactIntegrityError("atomic snapshot physical source/output alias")


def snapshot_atomic_authority(
    phase: str,
    authority: Path,
    channel: Path,
    *,
    target_path: str,
    expected_bytes: bytes,
    window: str,
) -> HostedAtomicForensicInventory:
    """Copy exact finite publication bytes without changing any original link."""
    if phase not in ("crashed", "recovered", "after"):
        raise ValueError("unknown fixed atomic snapshot phase")
    target = channel / "snapshots" / phase / "authority"
    _require_disjoint_outputs(
        authority,
        channel,
        (target, channel / "phase-forensics", channel / "phase-inventories"),
    )
    if target.exists() or target.is_symlink():
        raise ArtifactIntegrityError("atomic forensic snapshot requires a fresh retained root")
    facts = atomic_forensic_inventory(
        authority, target_path=target_path, expected_bytes=expected_bytes, window=window
    )
    with opened_directory(target, create=True):
        pass
    for directory in facts.directories:
        if directory.logical_path:
            with opened_directory(target / directory.logical_path, create=True):
                pass
    for file in facts.files:
        # Link2 is allowed only for the proven same-inode native publication pair.
        # No general reader is relaxed: its exact bytes were independently hashed
        # above against the native publication, so the safe copy is derived from it.
        data = (
            expected_bytes if file.link_count == 2 else read_relative(authority, file.logical_path)
        )
        atomic_write_bytes(target / file.logical_path, data, expected_sha256=file.sha256)
    if (
        raw_inventory(target) != forensic_byte_view(facts)
        or directory_inventory(target)
        != tuple(item.logical_path for item in facts.directories if item.logical_path)
        or facts
        != atomic_forensic_inventory(
            authority, target_path=target_path, expected_bytes=expected_bytes, window=window
        )
    ):
        raise ArtifactIntegrityError("atomic forensic snapshot source or copied bytes changed")
    atomic_write_bytes(channel / "phase-forensics" / f"{phase}.json", facts.canonical_bytes())
    atomic_write_bytes(
        channel / "phase-inventories" / f"{phase}.json", forensic_byte_view(facts).canonical_bytes()
    )
    return facts
