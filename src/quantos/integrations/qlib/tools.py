"""Verification boundary for official Qlib tools omitted from the wheel."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from quantos.artifacts.store import sha256_file

QLIB_REPOSITORY = "https://github.com/microsoft/qlib.git"
QLIB_TAG = "v0.9.7"
QLIB_VERSION = "0.9.7"
QLIB_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"


@dataclass(frozen=True)
class OfficialQlibTools:
    source_root: Path
    dump_bin: Path
    check_data_health: Path
    commit: str
    version: str
    dump_bin_sha256: str
    health_check_sha256: str


def run_checked(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a local tool with captured output and fail on nonzero exit."""

    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def verify_official_qlib_tools(source_root: Path) -> OfficialQlibTools:
    """Pin the installed wheel and official source checkout to the same reviewed release."""

    installed_version = version("pyqlib")
    if installed_version != QLIB_VERSION:
        raise RuntimeError(f"expected pyqlib {QLIB_VERSION}, got {installed_version}")
    actual_commit = run_checked(["git", "rev-parse", "HEAD"], cwd=source_root).stdout.strip()
    if actual_commit != QLIB_COMMIT:
        raise RuntimeError(f"expected Qlib commit {QLIB_COMMIT}, got {actual_commit}")
    tracked_changes = run_checked(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"], cwd=source_root
    ).stdout.strip()
    if tracked_changes:
        raise RuntimeError("locked Qlib source contains tracked working-tree changes")
    dump_script = source_root / "scripts" / "dump_bin.py"
    health_script = source_root / "scripts" / "check_data_health.py"
    if not dump_script.is_file() or not health_script.is_file():
        raise RuntimeError("locked Qlib source does not contain required official tools")
    for relative, script in (
        ("scripts/dump_bin.py", dump_script),
        ("scripts/check_data_health.py", health_script),
    ):
        committed_blob = run_checked(
            ["git", "rev-parse", f"{QLIB_COMMIT}:{relative}"], cwd=source_root
        ).stdout.strip()
        working_blob = run_checked(
            ["git", "hash-object", str(script.resolve())], cwd=source_root
        ).stdout.strip()
        if working_blob != committed_blob:
            raise RuntimeError(f"official Qlib tool differs from locked commit: {relative}")
    return OfficialQlibTools(
        source_root=source_root,
        dump_bin=dump_script,
        check_data_health=health_script,
        commit=actual_commit,
        version=installed_version,
        dump_bin_sha256=sha256_file(dump_script),
        health_check_sha256=sha256_file(health_script),
    )
