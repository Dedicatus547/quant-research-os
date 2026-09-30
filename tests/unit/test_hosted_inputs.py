"""Management loader rejects filesystem aliases before reading frozen bytes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from quantos.application.hosted_inputs import _publish_seed_file, _read_file, _verify_file
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted_inputs import HostedFrozenInputFile


def test_frozen_input_reader_accepts_only_exact_regular_bytes(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    nested = root / "nested"
    nested.mkdir(parents=True)
    data = b"frozen-input\n"
    (nested / "source.json").write_bytes(data)
    item = HostedFrozenInputFile(
        logical_path="nested/source.json", sha256=sha256_bytes(data), size_bytes=len(data)
    )
    assert _verify_file(root, item) == data
    changed = item.model_copy(update={"sha256": "a" * 64})
    with pytest.raises(ArtifactIntegrityError, match="inventory"):
        _verify_file(root, changed)
    with pytest.raises(ArtifactIntegrityError, match="byte cap"):
        _read_file(root, item.logical_path, max_bytes=len(data) - 1)


def test_frozen_input_reader_rejects_path_aliases(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    root.mkdir()
    original = root / "source.json"
    original.write_bytes(b"source")
    (root / "alias.json").symlink_to(original)
    os.link(original, root / "hardlink.json")
    (root / "directory-alias").symlink_to(root, target_is_directory=True)

    for name in ("alias.json", "hardlink.json", "directory-alias/source.json"):
        with pytest.raises(ArtifactIntegrityError):
            _read_file(root, name, max_bytes=100)
    with pytest.raises(ArtifactIntegrityError, match="invalid frozen input relative path"):
        _read_file(root, "../source.json", max_bytes=100)


def test_seed_materialization_is_physically_idempotent_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    data = b"frozen-seed"
    item = HostedFrozenInputFile(
        logical_path="objects/seed.json", sha256=sha256_bytes(data), size_bytes=len(data)
    )
    _publish_seed_file(tmp_path, item, data)

    def metadata():
        return tuple(
            (
                str(path.relative_to(tmp_path)),
                tuple(
                    getattr(path.stat(), field)
                    for field in (
                        "st_dev",
                        "st_ino",
                        "st_nlink",
                        "st_mode",
                        "st_uid",
                        "st_gid",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                ),
            )
            for path in (tmp_path, *sorted(tmp_path.rglob("*")))
        )

    before = metadata()
    _publish_seed_file(tmp_path, item, data)
    assert metadata() == before
    with pytest.raises(ArtifactIntegrityError, match="frozen input"):
        _publish_seed_file(tmp_path, item, data + b"changed")
    assert metadata() == before


@pytest.mark.parametrize("alias", ("symlink", "hardlink", "directory_symlink"))
def test_seed_materialization_rejects_aliases_before_any_publication(
    tmp_path: Path, alias: str
) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    original = tmp_path / "original.json"
    original.write_bytes(b"frozen-seed")
    target = root / "objects"
    if alias == "directory_symlink":
        target.symlink_to(tmp_path, target_is_directory=True)
        logical = "objects/original.json"
    else:
        target.mkdir()
        logical = "objects/seed.json"
        if alias == "symlink":
            (root / logical).symlink_to(original)
        else:
            os.link(original, root / logical)
    item = HostedFrozenInputFile(
        logical_path=logical, sha256=sha256_bytes(b"frozen-seed"), size_bytes=11
    )
    before = original.stat(), root.stat(), target.lstat(), tuple(root.iterdir())
    with pytest.raises(ArtifactIntegrityError):
        _publish_seed_file(root, item, b"frozen-seed")
    assert before == (original.stat(), root.stat(), target.lstat(), tuple(root.iterdir()))
