"""Actual empty directory topology and unsafe entries are not invisible evidence."""

import os
from pathlib import Path

import pytest

from quantos.infrastructure import hosted_verification as verification
from quantos.infrastructure.hosted_management_runtime import snapshot_management_authority
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    directory_inventory,
    raw_inventory,
)


def test_snapshot_preserves_empty_directory_topology_and_file_bytes(tmp_path: Path) -> None:
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    (authority / "empty/nested").mkdir(parents=True)
    (authority / "populated").mkdir()
    (authority / "populated/artifact.json").write_bytes(b"{}")
    channel.mkdir()
    before = raw_inventory(authority)
    expected = ("empty", "empty/nested", "populated")
    assert directory_inventory(authority) == expected
    snapshot_management_authority("before", authority, channel)
    saved = channel / "snapshots/before/authority"
    assert raw_inventory(saved) == before == raw_inventory(authority)
    assert directory_inventory(saved) == expected == directory_inventory(authority)
    (saved / "unrecorded-empty").mkdir()
    assert raw_inventory(saved) == before
    assert directory_inventory(saved) != expected


@pytest.mark.parametrize("kind", ("directory_symlink", "file_symlink", "hardlink", "fifo"))
def test_directory_inventory_rejects_unsafe_entries(tmp_path: Path, kind: str) -> None:
    (tmp_path / "data").write_bytes(b"frozen")
    if kind == "directory_symlink":
        (tmp_path / "nested").mkdir()
        (tmp_path / "unsafe").symlink_to(tmp_path / "nested", target_is_directory=True)
    elif kind == "file_symlink":
        (tmp_path / "unsafe").symlink_to(tmp_path / "data")
    elif kind == "hardlink":
        os.link(tmp_path / "data", tmp_path / "unsafe")
    else:
        os.mkfifo(tmp_path / "unsafe")
    with pytest.raises(HostedQualificationError, match="unsafe entry"):
        directory_inventory(tmp_path)


def test_directory_inventory_bounds_empty_directory_fanout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(3):
        (tmp_path / str(index)).mkdir()
    monkeypatch.setattr(verification, "MAX_BUNDLE_FILES", 2)
    with pytest.raises(HostedQualificationError, match="entry cap"):
        directory_inventory(tmp_path)
