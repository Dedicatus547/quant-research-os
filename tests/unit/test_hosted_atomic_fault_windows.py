"""Real process exits around the immutable openat/file/directory fsync primitive."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import sha256_bytes

_CHILD = """
import os, sys
from quantos.artifacts.store import atomic_write_bytes_at
root, window = sys.argv[1:]
descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
def stop(point):
    if point == window:
        os._exit(73)
atomic_write_bytes_at(descriptor, 'published.json', b'frozen-publication-fixture', fault_hook=stop)
raise SystemExit(1)
"""


@pytest.mark.parametrize(
    "window", ("file_fsynced", "file_linked", "file_published", "directory_fsynced")
)
def test_each_file_directory_boundary_preserves_physical_failure(
    tmp_path: Path, window: str
) -> None:
    completed = subprocess.run(
        (sys.executable, "-c", _CHILD, str(tmp_path), window),
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 73
    assert completed.stdout == completed.stderr == b""
    files = sorted(tmp_path.iterdir())
    target = tmp_path / "published.json"
    temporary = [path for path in files if path.name.startswith(".publish-")]
    assert all(path.read_bytes() == b"frozen-publication-fixture" for path in files)
    if window == "file_fsynced":
        assert len(temporary) == 1 and not target.exists()
        assert temporary[0].stat().st_nlink == 1
    elif window == "file_linked":
        assert len(temporary) == 1
        assert temporary[0].stat().st_ino == target.stat().st_ino
        assert target.stat().st_nlink == 2
        with (
            opened_directory(tmp_path) as descriptor,
            pytest.raises(ArtifactIntegrityError, match=r"hard-link|regular"),
        ):
            read_regular_bytes_at(descriptor, target.name, max_bytes=1024)
    else:
        assert not temporary and len(files) == 1
        assert target.stat().st_nlink == 1
        original = target.stat().st_dev, target.stat().st_ino, target.read_bytes()

        def reject_duplicate_mutation(_point: str) -> None:
            pytest.fail("existing immutable publication entered a new write window")

        with opened_directory(tmp_path) as descriptor:
            assert atomic_write_bytes_at(
                descriptor,
                target.name,
                b"frozen-publication-fixture",
                fault_hook=reject_duplicate_mutation,
            ) == sha256_bytes(b"frozen-publication-fixture")
        assert (target.stat().st_dev, target.stat().st_ino, target.read_bytes()) == original


def test_normal_publication_observes_ordered_fsync_boundaries(tmp_path: Path) -> None:
    observed: list[str] = []
    with opened_directory(tmp_path) as descriptor:
        atomic_write_bytes_at(descriptor, "published.json", b"{}", fault_hook=observed.append)
        assert read_regular_bytes_at(descriptor, "published.json", max_bytes=2) == b"{}"
    assert observed == ["file_fsynced", "file_linked", "file_published", "directory_fsynced"]
    assert os.stat(tmp_path / "published.json").st_nlink == 1
