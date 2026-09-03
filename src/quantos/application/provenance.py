"""Canonical code and lockfile provenance verification."""

from __future__ import annotations

import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from quantos.artifacts.store import sha256_file
from quantos.contracts.provenance import (
    CodeProvenance,
    RuntimeFingerprint,
    RuntimePackageVersion,
)
from quantos.contracts.status import ReasonCode


class ProvenanceError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


RUNTIME_PACKAGES: tuple[str, ...] = (
    "lightgbm",
    "numpy",
    "pandas",
    "pyarrow",
    "pydantic",
    "pyqlib",
    "ruamel.yaml",
    "typer",
)


def capture_runtime_fingerprint() -> RuntimeFingerprint:
    """Capture deterministic runtime identity without environment variables or secrets."""

    packages: list[RuntimePackageVersion] = []
    try:
        for name in RUNTIME_PACKAGES:
            packages.append(RuntimePackageVersion(name=name, version=version(name)))
    except PackageNotFoundError as error:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            f"required runtime distribution is unavailable: {error.name}",
        ) from error
    libc_name, libc_version = platform.libc_ver()
    return RuntimeFingerprint(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        operating_system=platform.system(),
        operating_system_release=platform.release(),
        architecture=platform.machine(),
        libc=f"{libc_name}-{libc_version}" if libc_name else "unknown",
        packages=tuple(packages),
    )


def _git(workspace: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "workspace is not a usable Git repository",
        ) from error
    return completed.stdout.strip()


def verify_code_provenance(
    workspace: Path,
    *,
    expected_commit_hash: str,
    expected_lockfile_hash: str,
) -> CodeProvenance:
    """Require an exact clean Git checkout and the bound uv.lock bytes."""

    actual = capture_code_provenance(workspace)
    if actual.commit_hash != expected_commit_hash:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "resolved code commit does not match Git HEAD",
        )
    if actual.lockfile_hash != expected_lockfile_hash:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "resolved lockfile hash does not match uv.lock",
        )
    return actual


def capture_code_provenance(workspace: Path) -> CodeProvenance:
    """Capture the exact provenance of a clean repository root."""

    resolved_workspace = workspace.resolve()
    repository_root = Path(_git(resolved_workspace, "rev-parse", "--show-toplevel")).resolve()
    if repository_root != resolved_workspace:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "canonical workspace must be the Git repository root",
        )
    commit_hash = _git(resolved_workspace, "rev-parse", "HEAD")
    if _git(resolved_workspace, "status", "--porcelain", "--untracked-files=all"):
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "canonical Git worktree is not clean",
        )
    lockfile = resolved_workspace / "uv.lock"
    try:
        actual_lockfile_hash = sha256_file(lockfile)
    except OSError as error:
        raise ProvenanceError(
            ReasonCode.REPRODUCIBILITY_MISMATCH,
            "canonical uv.lock is unavailable",
        ) from error
    return CodeProvenance(
        commit_hash=commit_hash,
        lockfile_hash=actual_lockfile_hash,
        worktree_clean=True,
    )
