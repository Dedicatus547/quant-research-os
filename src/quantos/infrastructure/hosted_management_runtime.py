"""Private RAM authorization and exact snapshots for fixed management workers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, opened_directory
from quantos.contracts.hosted_deployment import HostedServiceConfiguration
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_verification import (
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def snapshot_management_authority(phase: str, authority: Path, channel: Path) -> None:
    inventory = raw_inventory(authority)
    target = channel / "snapshots" / phase / "authority"
    with opened_directory(target, create=True):
        pass
    for item in inventory.files:
        atomic_write_bytes(target / item.logical_path, read_relative(authority, item.logical_path))
    verify_raw_inventory(target, inventory)


def management_python_flags() -> dict[str, object]:
    return {
        name: getattr(sys.flags, name)
        for name in (
            "isolated",
            "ignore_environment",
            "no_user_site",
            "safe_path",
            "hash_randomization",
        )
    }


def capture_restart_capabilities(
    configuration: HostedServiceConfiguration,
) -> tuple[tuple[int, bytes], ...]:
    """Capture one-use service descriptors into RAM, never into evidence or logs."""
    values: list[tuple[int, bytes]] = []
    for index, principal in enumerate(configuration.principals):
        if principal.capability_fd != 100 + index:
            raise ArtifactIntegrityError("fixed private service descriptor differs")
        value = os.pread(principal.capability_fd, 33, 0)
        if len(value) != 32:
            raise ArtifactIntegrityError("fixed private service capability length differs")
        values.append((principal.capability_fd, value))
    return tuple(values)


def restore_restart_capabilities(values: tuple[tuple[int, bytes], ...]) -> None:
    """Recreate only the configured private slots before a fresh fixed bootstrap."""
    for target, value in values:
        descriptor = private_memory_fd("management-service-capability")
        try:
            os.write(descriptor, value)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if descriptor != target:
                os.dup2(descriptor, target, inheritable=False)
        finally:
            if descriptor != target:
                os.close(descriptor)
