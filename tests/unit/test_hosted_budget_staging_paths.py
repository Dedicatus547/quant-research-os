"""Actual write-boundary alias rejection before any budget staging publication."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes_at
from quantos.infrastructure.hosted_budget_deployment import stage_managed_budget_deployment
from quantos.infrastructure.hosted_budget_staging_paths import (
    pinned_budget_staging_parent,
    require_staging_parent_identity,
)
from quantos.infrastructure.hosted_verification import directory_inventory, raw_inventory

ROLES = (
    "authority",
    "channel",
    "inputs",
    "config",
    "initial-projection",
    "provenance",
    "evidence",
    "install",
)


@pytest.mark.parametrize("mode", ("named-root", "different-cwd", "nonempty", "regular-fd"))
def test_prepared_stage_root_requires_empty_matching_directory_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from quantos.infrastructure import hosted_manager as manager

    identity = object()
    monkeypatch.setattr(manager, "capture_code_provenance", lambda _: identity)
    monkeypatch.setattr(manager, "verify_wheel_provenance", lambda *_: None)
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "pinned"
    directory.mkdir()
    if mode == "nonempty":
        (directory / "immutable-canary").write_bytes(b"existing bytes")
    if mode != "different-cwd":
        monkeypatch.chdir(directory)
    if mode == "regular-fd":
        (directory / "regular").write_bytes(b"not a directory")
        descriptor = os.open(directory / "regular", os.O_RDONLY | os.O_NOFOLLOW)
    else:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    before = raw_inventory(tmp_path), directory_inventory(tmp_path)
    try:
        with pytest.raises(ArtifactIntegrityError, match="prepared management staging"):
            manager.stage_hosted_deployment(
                Path("named") if mode == "named-root" else Path("."),
                tmp_path,
                SimpleNamespace(code_provenance=identity),
                {},
                tmp_path,
                wheel=tmp_path,
                base_python=tmp_path,
                dependency_site=tmp_path,
                codex_binary=tmp_path,
                launcher_configuration=SimpleNamespace(),
                prepared_root_fd=descriptor,
            )
        assert (raw_inventory(tmp_path), directory_inventory(tmp_path)) == before
    finally:
        os.close(descriptor)


def _parent(root: Path) -> SimpleNamespace:
    for role in ROLES:
        path = root / role
        path.mkdir()
        (path / "nested").mkdir()
        (path / "nested/canary").write_bytes(b"immutable protected bytes")
    return SimpleNamespace(
        root=root,
        paths=SimpleNamespace(
            authority=root / "authority",
            channel=root / "channel",
            offline_inputs=root / "inputs",
            configuration=root / "config",
            projection=root / "initial-projection",
            provenance=root / "provenance",
            install=root / "install",
        ),
    )


def _facts(root: Path) -> tuple[object, ...]:
    facts: list[object] = []
    for role in ROLES:
        path = root / role
        facts.extend((raw_inventory(path), directory_inventory(path)))
        for entry in (path, *sorted(path.rglob("*"))):
            info = entry.lstat()
            facts.append(
                (
                    str(entry),
                    info.st_dev,
                    info.st_ino,
                    info.st_nlink,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
            )
    return tuple(facts)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("level", ("qualification-deployments", "Q06"))
def test_actual_budget_stage_rejects_existing_ancestor_alias_before_writes(
    tmp_path: Path, role: str, level: str
) -> None:
    parent = _parent(tmp_path)
    alias = tmp_path / "qualification-deployments"
    if level == "Q06":
        alias.mkdir()
        alias /= "Q06"
    alias.symlink_to(tmp_path / role, target_is_directory=True)
    before = _facts(tmp_path)
    with pytest.raises(ArtifactIntegrityError, match="ancestor alias"):
        stage_managed_budget_deployment(
            parent,
            "request_submissions",
            tmp_path,
            base_python=tmp_path / "never-build",
            dependency_site=tmp_path / "never-read",
        )
    assert _facts(tmp_path) == before
    assert not (tmp_path / role / "request_submissions").exists()


def test_renamed_parent_descriptor_keeps_writes_out_of_retargeted_authority(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    with pinned_budget_staging_parent(parent) as (pinned, evidence_fd):
        q06 = tmp_path / "qualification-deployments/Q06"
        q06.rename(tmp_path / "original-staging-inode")
        q06.symlink_to(tmp_path / "authority", target_is_directory=True)
        before = _facts(tmp_path)
        pid = os.fork()
        if pid == 0:
            os.fchdir(pinned)
            Path("request_submissions").mkdir()
            Path("request_submissions/component-canary").write_bytes(b"pinned cwd")
            os._exit(0)
        observed, status = os.waitpid(pid, 0)
        assert observed == pid and os.waitstatus_to_exitcode(status) == 0
        assert _facts(tmp_path) == before
        assert (
            tmp_path / "original-staging-inode/request_submissions/component-canary"
        ).read_bytes()
        with pytest.raises(ArtifactIntegrityError):
            require_staging_parent_identity(parent, pinned)
        # Evidence publication uses its original fd even if the directory label moves.
        (tmp_path / "evidence").rename(tmp_path / "original-evidence-inode")
        (tmp_path / "evidence").symlink_to(tmp_path / "authority", target_is_directory=True)
        authority_before = (
            raw_inventory(tmp_path / "authority"),
            directory_inventory(tmp_path / "authority"),
        )
        atomic_write_bytes_at(evidence_fd, "component-evidence.json", b"pinned evidence")
        assert (
            raw_inventory(tmp_path / "authority"),
            directory_inventory(tmp_path / "authority"),
        ) == authority_before
        assert (
            tmp_path / "original-evidence-inode/component-evidence.json"
        ).read_bytes() == b"pinned evidence"


def test_new_case_basename_replacement_cannot_redirect_its_pinned_cwd(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    with pinned_budget_staging_parent(parent) as (staging_fd, _evidence):
        os.mkdir("request_submissions", mode=0o700, dir_fd=staging_fd)
        case_fd = os.open(
            "request_submissions",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=staging_fd,
        )
        try:
            case = tmp_path / "qualification-deployments/Q06/request_submissions"
            moved = case.with_name("original-case-inode")
            case.rename(moved)
            case.symlink_to(tmp_path / "authority", target_is_directory=True)
            before = _facts(tmp_path)
            pid = os.fork()
            if pid == 0:
                os.fchdir(case_fd)
                Path("inputs").mkdir()
                Path("inputs/component-canary").write_bytes(b"pinned case cwd")
                os._exit(0)
            observed, status = os.waitpid(pid, 0)
            assert observed == pid and os.waitstatus_to_exitcode(status) == 0
            assert _facts(tmp_path) == before
            assert (moved / "inputs/component-canary").read_bytes() == b"pinned case cwd"
        finally:
            os.close(case_fd)
