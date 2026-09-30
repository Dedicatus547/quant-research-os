"""Management loader rejects filesystem aliases before reading frozen bytes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from quantos.application.hosted_inputs import _read_file, _verify_file
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
