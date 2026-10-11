#!/usr/bin/env python3
"""Freeze selected working source into a new durable, independently committed capsule."""

from __future__ import annotations

import argparse
import ast
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from quantos.artifacts.store import (  # noqa: E402
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
    opened_directory,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import LEASE_ENV, configured_guard  # noqa: E402
from quantos.security import validate_secret_free  # noqa: E402

_ROOT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "AGENTS.md",
    ".gitignore",
    "docs/guides/implementation-discipline.md",
)
_EXCLUDED_DIRECTORIES = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".pyright",
        "node_modules",
    }
)
_FORBIDDEN_NAMES = frozenset({"auth.json", "credentials.json", "id_rsa", "id_ed25519"})
_FILE_CAP = 16 << 20


def _excluded(path: Path) -> bool:
    return (
        path.name in _EXCLUDED_DIRECTORIES
        or path.name in _FORBIDDEN_NAMES
        or path.name.startswith(".env")
        or path.suffix in {".pyc", ".pyo", ".pem", ".key"}
    )


def source_files(source: Path) -> tuple[Path, ...]:
    """Exact explicit roots; reject unsafe nodes even if their names would be excluded."""
    if source.absolute() != source.resolve(strict=True):
        raise ArtifactIntegrityError("source workspace must have a canonical plain path")
    files: list[Path] = []
    for name in _ROOT_FILES:
        files.append(confined_regular_file(source, name))
    for name in ("src", "scripts"):
        directory = source / name
        with opened_directory(directory):
            pass
        pending = [directory]
        while pending:
            parent = pending.pop()
            for child in sorted(parent.iterdir()):
                mode = child.lstat().st_mode
                if child.is_symlink() or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise ArtifactIntegrityError("source tree contains an unsafe filesystem object")
                if _excluded(child):
                    continue
                if stat.S_ISDIR(mode):
                    pending.append(child)
                else:
                    if child.stat().st_nlink != 1:
                        raise ArtifactIntegrityError("source tree contains a hard-link alias")
                    files.append(child)
    return tuple(sorted(files))


def growth_estimate(files: tuple[Path, ...]) -> dict[str, int]:
    sizes = [path.stat().st_size for path in files]
    if any(size > _FILE_CAP for size in sizes):
        raise ArtifactIntegrityError("source file exceeds the bounded capsule scope")
    total, largest = sum(sizes), max(sizes, default=0)
    # Worktree + Git index/object growth + worst-case incompressible objects,
    # largest atomic-write temporary, inventory and 32MiB Git/evidence slack.
    estimate = ((3 * total + largest + (32 << 20) + (1 << 20) - 1) >> 20) << 20
    return {
        "source_files": len(files),
        "source_bytes": total,
        "largest_source_file_bytes": largest,
        "expected_new_bytes": estimate,
    }


def _read(source: Path, relative: str) -> bytes:
    path = confined_regular_file(source, relative)
    if path.stat().st_nlink != 1:
        raise ArtifactIntegrityError("source file has a hard-link alias")
    with path.open("rb") as stream:
        data = stream.read(_FILE_CAP + 1)
    if len(data) > _FILE_CAP:
        raise ArtifactIntegrityError("source file exceeds its bound")
    return data


def _secret_scan(relative: str, data: bytes) -> None:
    text = data.decode("utf-8")
    if relative.endswith(".py"):
        # Inspect decoded literals, so scanners' own prefix examples such as
        # b"Bearer " are not mistaken for credentials including Python quotes.
        tree = ast.parse(text)
        literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    literals.append(node.value)
                elif isinstance(node.value, bytes):
                    literals.append(node.value.decode("utf-8", errors="replace"))
    else:
        literals = [text]
    for literal in literals:
        for offset in range(0, len(literal), 60_000):
            validate_secret_free(
                literal[max(0, offset - 4096) : offset + 60_000], file_name=Path(relative).name
            )


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("/usr/bin/git", "-C", str(root), *args),
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        },
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip()


def freeze(source: Path, destination: Path) -> dict[str, object]:
    destination = destination.absolute()
    if (
        ".." in destination.parts
        or destination.is_relative_to(Path("/tmp"))
        or destination.is_relative_to(Path("/var/tmp"))
        or destination.is_relative_to(source / "src")
        or destination.is_relative_to(source / "scripts")
    ):
        raise ArtifactIntegrityError("source capsule requires an independent durable destination")
    guard = configured_guard()
    guard.require_root(destination)
    guard.require_lease()
    files = source_files(source)
    growth = growth_estimate(files)
    capacity = guard.check(growth["expected_new_bytes"])
    lease_name = os.environ.get(LEASE_ENV)
    if lease_name is None:
        raise ArtifactIntegrityError("source capsule requires its existing supervised lease")
    prelaunch = json.loads(confined_regular_file(Path(lease_name), "prelaunch.json").read_bytes())
    if prelaunch.get("expected_new_bytes", -1) < growth["expected_new_bytes"]:
        raise ArtifactIntegrityError("source capsule exceeds the supervised growth reservation")
    original_head = _git(source, "rev-parse", "HEAD")
    with exclusive_directory_lock(destination):
        if any(destination.iterdir()):
            raise ArtifactIntegrityError("source capsule destination is not empty")
        atomic_write_bytes(
            destination / "started.json",
            canonical_json_bytes(
                {
                    "schema_version": "post-hm-source-freeze-start/v1",
                    "workspace": str(source),
                    "original_workspace_head": original_head,
                    "growth": growth,
                    "capacity": capacity,
                    "storage_policy_hash": guard.policy_hash,
                }
            ),
        )
        try:
            workspace = destination / "workspace"
            with opened_directory(workspace, create=True):
                pass
            inventory: list[dict[str, object]] = []
            for path in files:
                relative = path.relative_to(source).as_posix()
                data = _read(source, relative)
                _secret_scan(relative, data)
                digest = sha256_bytes(data)
                target = workspace / relative
                with opened_directory(target.parent, create=True):
                    pass
                atomic_write_bytes(target, data, expected_sha256=digest)
                mode = stat.S_IMODE(path.stat().st_mode)
                os.chmod(target, 0o755 if mode & 0o111 else 0o644)
                if sha256_bytes(_read(source, relative)) != digest:
                    raise ArtifactIntegrityError("source bytes changed during capsule copy")
                inventory.append(
                    {
                        "path": relative,
                        "bytes_hash": digest,
                        "size_bytes": len(data),
                        "executable": bool(mode & 0o111),
                    }
                )
            if source_files(source) != files or _git(source, "rev-parse", "HEAD") != original_head:
                raise ArtifactIntegrityError("source workspace identities changed during freeze")
            for entry in inventory:
                relative = cast(str, entry["path"])
                if (
                    sha256_bytes(_read(source, relative)) != entry["bytes_hash"]
                    or sha256_bytes(_read(workspace, relative)) != entry["bytes_hash"]
                ):
                    raise ArtifactIntegrityError("source inventory changed before local commit")
            _git(workspace, "-c", "init.templateDir=", "init", "--initial-branch=source-capsule")
            for key, value in (
                ("user.name", "QuantOS research source snapshot"),
                ("user.email", "source-snapshot@quantos.local"),
                ("commit.gpgsign", "false"),
                ("core.hooksPath", "/dev/null"),
                ("core.autocrlf", "false"),
                ("core.fsync", "all"),
            ):
                _git(workspace, "config", "--local", key, value)
            # Force only the inspected explicit inventory, independent of copied ignore rules.
            _git(workspace, "add", "-f", "--", *(cast(str, entry["path"]) for entry in inventory))
            _git(workspace, "commit", "-m", "Freeze post-HM research source snapshot")
            commit = _git(workspace, "rev-parse", "HEAD")
            lock = sha256_bytes(_read(workspace, "uv.lock"))
            from quantos.application.provenance import verify_code_provenance

            provenance = verify_code_provenance(
                workspace, expected_commit_hash=commit, expected_lockfile_hash=lock
            )
            for entry in inventory:
                relative = cast(str, entry["path"])
                if sha256_bytes(_read(source, relative)) != entry["bytes_hash"]:
                    raise ArtifactIntegrityError("source bytes changed before capsule completion")
            atomic_write_bytes(
                destination / "source-inventory.json",
                canonical_json_bytes(
                    {
                        "schema_version": "post-hm-source-inventory/v1",
                        "files": inventory,
                    }
                ),
            )
            receipt: dict[str, object] = {
                "schema_version": "post-hm-source-capsule/v1",
                "workspace": str(workspace),
                "original_workspace_head": original_head,
                "actual_commit": commit,
                "lockfile_hash": lock,
                "source_inventory_hash": sha256_bytes(
                    (destination / "source-inventory.json").read_bytes()
                ),
                "code_provenance": provenance.model_dump(mode="json"),
                "growth": growth,
                "source_bytes_verified_before_after": True,
                "original_git_modified": False,
            }
            atomic_write_bytes(destination / "capsule.json", canonical_json_bytes(receipt))
            return receipt
        except Exception as error:
            atomic_write_bytes(
                destination / "failure.json",
                canonical_json_bytes(
                    {
                        "schema_version": "post-hm-source-freeze-failure/v1",
                        "failure_type": type(error).__name__,
                        "failure_message_hash": sha256_bytes(str(error).encode()),
                        "workspace_is_accepted": False,
                    }
                ),
            )
            raise ArtifactIntegrityError(
                "source capsule freeze failed; durable failure retained"
            ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REPO)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--print-growth", action="store_true")
    args = parser.parse_args()
    source = args.source.absolute()
    if args.print_growth:
        print(json.dumps(growth_estimate(source_files(source)), sort_keys=True))
        return
    if args.destination is None:
        parser.error("freeze requires a new durable destination")
    print(json.dumps(freeze(source, args.destination), sort_keys=True))


if __name__ == "__main__":
    main()
