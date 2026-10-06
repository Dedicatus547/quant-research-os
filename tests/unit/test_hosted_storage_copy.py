"""Small offline copies prove clone policy, isolation and complete tree verification."""

from __future__ import annotations

import errno
import os
import stat
import zipfile
from pathlib import Path

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted_deployment import HostedChannelPolicy, HostedClientConfiguration
from quantos.infrastructure import hosted_storage_copy as storage
from quantos.infrastructure.hosted_deployment import freeze_python_install, install_inventory
from quantos.infrastructure.hosted_regression_runtime import (
    COVERAGE_PTH,
    expected_ci_runtime,
    prepare_ci_runtime_contents,
)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "empty").mkdir(parents=True)
    (source / "package").mkdir()
    (source / "package/module.py").write_bytes(b"frozen bytes\n")
    (source / "launcher").write_bytes(b"native fixture\n")
    (source / "launcher").chmod(0o500)
    (source / "empty").chmod(0o750)
    source.chmod(0o750)
    return source


def _clone(destination: int, request: int, source: int) -> None:
    """Tiny ioctl double copies independent bytes; never claims filesystem support."""
    assert request == storage.FICLONE
    os.lseek(source, 0, os.SEEK_SET)
    while chunk := os.read(source, 1024):
        assert os.write(destination, chunk) == len(chunk)


def _unsupported(destination: int, request: int, source: int) -> None:
    raise OSError(errno.EOPNOTSUPP, "fixture filesystem has no reflink")


def test_verified_clone_preserves_empty_directories_modes_hashes_and_inode_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(storage.fcntl, "ioctl", _clone)
    report = storage.copy_tree_verified(source, target)
    assert report.reflink_files == 2
    assert report.physical_files == report.physical_bytes == 0
    assert report.logical_bytes == len(b"frozen bytes\nnative fixture\n")
    assert target.joinpath("empty").is_dir()
    for relative in ("", "empty", "package", "launcher", "package/module.py"):
        assert stat.S_IMODE((target / relative).stat().st_mode) == stat.S_IMODE(
            (source / relative).stat().st_mode
        )
    original = source / "package/module.py"
    copied = target / "package/module.py"
    assert copied.stat().st_ino != original.stat().st_ino
    assert copied.stat().st_nlink == original.stat().st_nlink == 1
    copied.write_bytes(b"modified destination")
    assert original.read_bytes() == b"frozen bytes\n"


@pytest.mark.parametrize("code", [errno.EOPNOTSUPP, errno.ENOTTY, errno.EXDEV, errno.EINVAL])
def test_unsupported_clone_fails_closed_without_authorized_physical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    source = _source(tmp_path)

    def unavailable(destination: int, request: int, original: int) -> None:
        raise OSError(code, "fixture unsupported clone")

    monkeypatch.setattr(storage.fcntl, "ioctl", unavailable)
    with pytest.raises(storage.ReflinkUnavailable, match="explicit disk budget guard"):
        storage.copy_tree_verified(source, tmp_path / "target")
    assert (tmp_path / "target/launcher").stat().st_size == 0
    assert (source / "launcher").read_bytes() == b"native fixture\n"


def test_fallback_guard_authorizes_every_file_before_bytes_and_reports_physical_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)
    charged: list[int] = []

    def budget(length: int) -> None:
        relative = ("launcher", "package/module.py")[len(charged)]
        assert (target / relative).stat().st_size == 0
        charged.append(length)

    report = storage.copy_tree_verified(source, target, before_physical_copy=budget)
    assert charged == [len(b"native fixture\n"), len(b"frozen bytes\n")]
    assert report.reflink_files == 0
    assert report.physical_files == 2
    assert report.logical_bytes == report.physical_bytes == sum(charged)
    monkeypatch.setattr(storage.fcntl, "ioctl", _clone)
    cloned = storage.copy_tree_verified(source, tmp_path / "cloned")
    assert cloned.inventory_hash == report.inventory_hash


def test_budget_rejection_happens_before_physical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)

    def budget(length: int) -> None:
        raise ArtifactIntegrityError("physical disk budget exhausted")

    with pytest.raises(ArtifactIntegrityError, match="budget exhausted"):
        storage.copy_tree_verified(source, tmp_path / "target", before_physical_copy=budget)
    assert (tmp_path / "target/launcher").stat().st_size == 0


def test_complete_tree_is_reserved_before_first_physical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)
    reserved: list[int] = []

    def reserve(size: int) -> None:
        assert (target / "launcher").stat().st_size == 0
        reserved.append(size)

    report = storage.copy_tree_verified(source, target, reserve_physical_copy=reserve)
    assert reserved == [len(b"frozen bytes\nnative fixture\n")]
    assert report.physical_bytes == reserved[0]
    assert report.physical_files == 2


def test_tree_reservation_rejection_prevents_all_physical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "target"
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)

    def reserve(size: int) -> None:
        raise ArtifactIntegrityError("tree exceeds available capacity")

    with pytest.raises(ArtifactIntegrityError, match="available capacity"):
        storage.copy_tree_verified(source, target, reserve_physical_copy=reserve)
    assert (target / "launcher").stat().st_size == 0
    assert not (target / "package/module.py").exists()


def test_growing_source_never_writes_more_than_the_guard_authorized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original"
    source.write_bytes(b"bounded bytes")
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)
    charged: list[int] = []

    def budget(length: int) -> None:
        charged.append(length)
        source.write_bytes(b"X" * 4096)

    with pytest.raises(ArtifactIntegrityError, match="source grew"):
        storage.copy_file_verified(source, tmp_path / "target", before_physical_copy=budget)
    assert charged == [len(b"bounded bytes")]
    assert (tmp_path / "target").stat().st_size <= charged[0]


@pytest.mark.parametrize("kind", ["symlink", "directory_symlink", "hardlink", "fifo"])
def test_unsafe_source_entries_rejected_before_creating_destination(
    tmp_path: Path, kind: str
) -> None:
    source = _source(tmp_path)
    unsafe = source / "unsafe"
    if kind == "symlink":
        unsafe.symlink_to(source / "launcher")
    elif kind == "directory_symlink":
        unsafe.symlink_to(source / "package", target_is_directory=True)
    elif kind == "hardlink":
        os.link(source / "launcher", unsafe)
    else:
        os.mkfifo(unsafe)
    with pytest.raises(ArtifactIntegrityError, match="symlink, alias or special"):
        storage.copy_tree_verified(source, tmp_path / "target")
    assert not (tmp_path / "target").exists()


def test_source_change_and_corrupt_clone_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)

    def mutate(destination: int, request: int, original: int) -> None:
        _clone(destination, request, original)
        (source / "launcher").chmod(0o600)
        (source / "launcher").write_bytes(b"source changed\n")

    monkeypatch.setattr(storage.fcntl, "ioctl", mutate)
    with pytest.raises(ArtifactIntegrityError, match="source changed"):
        storage.copy_tree_verified(source, tmp_path / "mutated")

    def corrupt(destination: int, request: int, original: int) -> None:
        _clone(destination, request, original)
        os.pwrite(destination, b"X", 0)

    monkeypatch.setattr(storage.fcntl, "ioctl", corrupt)
    with pytest.raises(ArtifactIntegrityError, match="copied bytes or mode"):
        storage.copy_tree_verified(source, tmp_path / "corrupt")


def test_permission_failure_never_triggers_physical_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    charged: list[int] = []

    def denied(destination: int, request: int, original: int) -> None:
        raise PermissionError(errno.EACCES, "fixture permission denial")

    monkeypatch.setattr(storage.fcntl, "ioctl", denied)
    with pytest.raises(PermissionError):
        storage.copy_tree_verified(source, tmp_path / "target", before_physical_copy=charged.append)
    assert not charged


def test_single_file_can_be_renamed_and_cannot_overwrite_or_follow_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(storage.fcntl, "ioctl", _clone)
    destination = tmp_path / "codex"
    report = storage.copy_file_verified(source / "launcher", destination)
    assert report.reflink_files == 1
    assert destination.read_bytes() == (source / "launcher").read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o500
    with pytest.raises(FileExistsError):
        storage.copy_file_verified(source / "launcher", destination)
    link = tmp_path / "link"
    link.symlink_to(source / "launcher")
    with pytest.raises(OSError):
        storage.copy_file_verified(link, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_real_small_kernel_copy_reports_actual_method_and_remains_independent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.write_bytes(b"tiny offline kernel clone check\n")
    charged: list[int] = []
    copied = tmp_path / "copied"
    report = storage.copy_file_verified(source, copied, before_physical_copy=charged.append)
    assert report.reflink_files + report.physical_files == 1
    assert report.physical_bytes == sum(charged)
    assert report.physical_files == len(charged)
    assert copied.stat().st_ino != source.stat().st_ino
    copied.write_bytes(b"destination mutation")
    assert source.read_bytes() == b"tiny offline kernel clone check\n"


def test_overlapping_source_and_destination_are_rejected(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(ArtifactIntegrityError, match="overlap"):
        storage.copy_tree_verified(source, source / "copy")
    assert not (source / "copy").exists()


def test_replaced_source_pathname_is_rejected_even_with_pinned_original_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original"
    source.write_bytes(b"frozen bytes")

    def replace_path(destination: int, request: int, original: int) -> None:
        _clone(destination, request, original)
        source.rename(tmp_path / "old-original")
        source.write_bytes(b"frozen bytes")

    monkeypatch.setattr(storage.fcntl, "ioctl", replace_path)
    with pytest.raises(ArtifactIntegrityError, match=r"source.*changed"):
        storage.copy_file_verified(source, tmp_path / "target")


def test_freeze_install_routes_prefix_dependencies_and_binary_through_budgeted_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _source(tmp_path)
    dependencies = tmp_path / "dependencies"
    (dependencies / "package").mkdir(parents=True)
    (dependencies / "package/__init__.py").write_bytes(b"package fixture")
    (dependencies / "module.py").write_bytes(b"module fixture")
    (dependencies / "unsafe.pth").write_bytes(b"forbidden import hook")
    codex = tmp_path / "vendor-codex"
    codex.write_bytes(b"CLI fixture")
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("quantos/__init__.py", b"frozen wheel fixture")
    charged: list[int] = []
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)
    destination = tmp_path / "install"
    inventory = freeze_python_install(
        destination,
        wheel=wheel,
        base_python=base,
        dependency_site=dependencies,
        codex_binary=codex,
        client_configuration=HostedClientConfiguration(
            socket_path="/channel/quantos.sock",
            policy=HostedChannelPolicy(
                header_byte_cap=4096,
                response_byte_cap=262144,
                reply_byte_cap=1052672,
                io_timeout_ms=100,
                operation_reply_timeout_ms=2000,
                max_connections=2,
                max_total_connections=20,
                listen_backlog=2,
            ),
        ),
        before_physical_copy=charged.append,
    )
    assert inventory == install_inventory(destination)
    assert charged == [
        len(b"native fixture\nfrozen bytes\nmodule fixturepackage fixtureCLI fixture"),
    ]
    assert not (destination / "python/lib/python3.11/site-packages/unsafe.pth").exists()
    assert (destination / "codex").read_bytes() == codex.read_bytes()


def test_ci_prefix_routes_copy_through_guard_and_keeps_expected_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    from quantos.contracts.base import sha256_bytes

    install = tmp_path / "install"
    site = install / "python/lib/python3.11/site-packages"
    metadata = site / "coverage-7.16.0.dist-info"
    metadata.mkdir(parents=True)
    digest = (
        base64.urlsafe_b64encode(bytes.fromhex(sha256_bytes(COVERAGE_PTH))).rstrip(b"=").decode()
    )
    (metadata / "RECORD").write_text(f"a1_coverage.pth,sha256={digest},{len(COVERAGE_PTH)}\n")
    (site / "module.py").write_bytes(b"module fixture")
    node = tmp_path / "node"
    node.write_bytes(b"\x7fELFtiny fixture")
    target = tmp_path / "runtime"
    target.mkdir()
    monkeypatch.chdir(target)
    monkeypatch.setattr(storage.fcntl, "ioctl", _unsupported)
    charged: list[int] = []
    expected = expected_ci_runtime(install_inventory(install))
    declaration = prepare_ci_runtime_contents(
        install, expected, node, before_physical_copy=charged.append
    )
    assert install_inventory(target / ".venv") == expected
    assert sum(charged) == sum(item.size_bytes for item in install_inventory(install).files)
    assert declaration["runtime_inventory_hash"] == expected.content_hash
