"""Pinned, disjoint management staging paths; no writes precede alias checks."""

from __future__ import annotations

import os
import stat
from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
from quantos.infrastructure.hosted_manager import HostedManagedDeployment


def _directory_identities(fd: int, identities: set[tuple[int, int]], depth: int = 0) -> None:
    if depth > 128 or len(identities) > 100_000:
        raise ArtifactIntegrityError("budget protected directory bounds exceeded")
    info = os.fstat(fd)
    identity = info.st_dev, info.st_ino
    if identity in identities:
        return
    identities.add(identity)
    with os.scandir(fd) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ArtifactIntegrityError("budget protected tree contains a directory alias")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    _directory_identities(child, identities, depth + 1)
                finally:
                    os.close(child)


def _check_identity(fd: int, forbidden: set[tuple[int, int]]) -> None:
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) in forbidden:
        raise ArtifactIntegrityError("budget staging physically overlaps protected authority")


@contextmanager
def pinned_budget_staging_parent(
    parent: HostedManagedDeployment,
    *,
    family: str = "Q06",
) -> Generator[tuple[int, int], None, None]:
    """Keep the exact staging/evidence inode pinned for child cwd and openat writes."""
    if family not in {"Q06", "Q12"}:
        raise ValueError("unknown fixed management staging family")
    components = (
        ("qualification-deployments", "Q06") if family == "Q06" else ("qualification-checks",)
    )
    root = parent.root.absolute()
    with ExitStack() as stack:
        root_fd = stack.enter_context(opened_directory(root))
        forbidden: set[tuple[int, int]] = set()
        evidence_identity: tuple[int, int] | None = None
        paths = {
            root / name
            for name in (
                "authority",
                "channel",
                "inputs",
                "config",
                "initial-projection",
                "provenance",
                "evidence",
                "install",
            )
        } | {
            parent.paths.authority,
            parent.paths.channel,
            parent.paths.offline_inputs,
            parent.paths.configuration,
            parent.paths.projection,
            parent.paths.provenance,
            parent.paths.install,
        }
        for path in sorted(paths):
            if not path.exists() and not path.is_symlink():
                continue
            protected_fd = stack.enter_context(opened_directory(path))
            _directory_identities(protected_fd, forbidden)
            if path.absolute() == root / "evidence":
                info = os.fstat(protected_fd)
                evidence_identity = info.st_dev, info.st_ino
        _check_identity(root_fd, forbidden)
        # Inspect all existing fixed ancestors before creating even an empty prefix.
        current = os.dup(root_fd)
        try:
            for component in components:
                try:
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
                    )
                except FileNotFoundError:
                    break
                except OSError as error:
                    raise ArtifactIntegrityError(
                        "budget staging ancestor alias rejected"
                    ) from error
                os.close(current)
                current = child
                _check_identity(current, forbidden)
        finally:
            os.close(current)
        # Creation and all subsequent lookups use the previously pinned parent.
        current = os.dup(root_fd)
        try:
            for component in components:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
                try:
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current
                    )
                except OSError as error:
                    raise ArtifactIntegrityError("budget staging ancestor changed") from error
                os.close(current)
                current = child
                _check_identity(current, forbidden)
            try:
                os.mkdir("evidence", mode=0o700, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileExistsError:
                pass
            evidence_fd = os.open(
                "evidence", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
            )
            stack.callback(os.close, evidence_fd)
            info = os.fstat(evidence_fd)
            observed_identity = info.st_dev, info.st_ino
            if evidence_identity is not None:
                if observed_identity != evidence_identity:
                    raise ArtifactIntegrityError("budget evidence original inode changed")
            elif observed_identity in forbidden:
                raise ArtifactIntegrityError("budget evidence overlaps protected authority")
            yield current, evidence_fd
        finally:
            os.close(current)


def require_staging_parent_identity(
    parent: HostedManagedDeployment, pinned_fd: int, *, family: str = "Q06"
) -> None:
    """A renamed/retargeted path cannot be published as the original child source."""
    if family not in {"Q06", "Q12"}:
        raise ValueError("unknown fixed management staging family")
    logical = "qualification-deployments/Q06" if family == "Q06" else "qualification-checks"
    with opened_directory(parent.root / logical) as observed:
        expected_info, observed_info = os.fstat(pinned_fd), os.fstat(observed)
        if (expected_info.st_dev, expected_info.st_ino) != (
            observed_info.st_dev,
            observed_info.st_ino,
        ):
            raise ArtifactIntegrityError("budget staging original parent path changed")
