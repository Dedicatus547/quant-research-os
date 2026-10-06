"""Check alias confinement and independent Python source normalization."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure import hosted_storage_copy
from quantos.infrastructure.hosted_python_prefix import normalize_python_prefix


def _prefix(root: Path) -> Path:
    source = root / "source"
    (source / "bin").mkdir(parents=True)
    (source / "lib/python3.11").mkdir(parents=True)
    (source / "bin/python3.11").write_bytes(b"fixture interpreter; never executed")
    (source / "lib/python3.11/runtime.py").write_bytes(b"fixture module")
    return source


def _tiny_budget(size: int) -> None:
    assert 0 <= size < 1024


def test_normalized_aliases_are_independent_files(tmp_path: Path) -> None:
    source = _prefix(tmp_path)
    (source / "bin/python3").symlink_to("python3.11")
    (source / "bin/python").symlink_to("python3")
    (source / "lib/runtime.py").symlink_to(source / "lib/python3.11/runtime.py")
    target = tmp_path / "normalized"
    report = normalize_python_prefix(source, target, before_physical_copy=_tiny_budget)
    assert report.source_before_after_equal
    assert len(report.aliases) == 3
    assert report.reflink_bytes + report.physical_bytes == report.logical_bytes
    assert report.reflink_files + report.physical_files == 5
    original = (source / "bin/python3.11").read_bytes()
    for name in ("python", "python3", "python3.11"):
        path = target / "bin" / name
        assert not path.is_symlink()
        assert path.stat().st_nlink == 1
        assert path.read_bytes() == original
    (target / "bin/python").write_bytes(b"changed independent file")
    assert (target / "bin/python3").read_bytes() == original
    assert (source / "bin/python3.11").read_bytes() == original


@pytest.mark.parametrize("damage", ("escape", "directory", "cycle", "hardlink", "fifo"))
def test_unsafe_sources_are_rejected_before_copy(tmp_path: Path, damage: str) -> None:
    source = _prefix(tmp_path)
    alias = source / "bin/unsafe"
    if damage == "escape":
        (tmp_path / "outside").write_bytes(b"outside canary")
        alias.symlink_to("../../outside")
    elif damage == "directory":
        alias.symlink_to("../lib/python3.11", target_is_directory=True)
    elif damage == "cycle":
        alias.symlink_to("unsafe")
    elif damage == "hardlink":
        os.link(source / "bin/python3.11", alias)
    else:
        os.mkfifo(alias)
    target = tmp_path / "normalized"
    with pytest.raises(ArtifactIntegrityError):
        normalize_python_prefix(source, target, before_physical_copy=_tiny_budget)
    assert not target.exists()


def test_alias_cannot_cross_a_directory_alias_then_backtrack(tmp_path: Path) -> None:
    source = _prefix(tmp_path)
    (source / "bin/dir-alias").symlink_to("../lib", target_is_directory=True)
    (source / "bin/python").symlink_to("dir-alias/../python3.11")
    with pytest.raises(ArtifactIntegrityError):
        normalize_python_prefix(source, tmp_path / "normalized", before_physical_copy=_tiny_budget)


def test_source_mutation_during_copy_retains_failed_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _prefix(tmp_path)
    target = tmp_path / "normalized"

    def unsupported(*args: object) -> None:
        raise OSError(errno.EOPNOTSUPP, "fixture: clone unavailable")

    monkeypatch.setattr(hosted_storage_copy.fcntl, "ioctl", unsupported)

    def mutate(size: int) -> None:
        _tiny_budget(size)
        path = source / "bin/python3.11"
        path.write_bytes(b"x" * path.stat().st_size)

    with pytest.raises(ArtifactIntegrityError):
        normalize_python_prefix(source, target, before_physical_copy=mutate)
    assert target.is_dir()
