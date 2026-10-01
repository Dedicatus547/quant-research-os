"""Scientific snapshot bytes use their observed size, keeping typed caps intact."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantos.infrastructure import hosted_management_runtime as runtime
from quantos.infrastructure.hosted_verification import (
    MAX_TYPED_BYTES,
    HostedQualificationError,
    directory_inventory,
    raw_inventory,
    read_relative,
)


def test_native_sized_scientific_export_copies_without_relaxing_typed_reader(
    tmp_path: Path,
) -> None:
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    data = b"x" * (MAX_TYPED_BYTES + 1)
    (authority / "predictions.json").write_bytes(data)
    (authority / "retained-empty-directory").mkdir()
    before = raw_inventory(authority), directory_inventory(authority)
    with pytest.raises(HostedQualificationError):
        read_relative(authority, "predictions.json")
    runtime.snapshot_management_authority("recovered", authority, channel)
    copied = channel / "snapshots/recovered/authority"
    assert (copied / "predictions.json").read_bytes() == data
    assert (raw_inventory(copied), directory_inventory(copied)) == before
    assert (raw_inventory(authority), directory_inventory(authority)) == before
    with pytest.raises(HostedQualificationError):
        read_relative(copied, "predictions.json")


def test_snapshot_detects_source_change_after_copy_and_retains_failed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    (authority / "original.json").write_bytes(b"immutable original bytes")
    original_writer = runtime.atomic_write_bytes

    def write_and_change_source(path: Path, data: bytes, *, expected_sha256: str) -> None:
        original_writer(path, data, expected_sha256=expected_sha256)
        (authority / "original.json").write_bytes(b"concurrent changed bytes")

    monkeypatch.setattr(runtime, "atomic_write_bytes", write_and_change_source)
    with pytest.raises(HostedQualificationError):
        runtime.snapshot_management_authority("recovered", authority, channel)
    assert (
        channel / "snapshots/recovered/authority/original.json"
    ).read_bytes() == b"immutable original bytes"
