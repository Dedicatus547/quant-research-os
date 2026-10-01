"""Native Ruff bytes are wheel-bound; no external mutable tool is executed."""

from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path

import pytest

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_deployment import _freeze_ruff_executable
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.mark.parametrize("case", ["valid", "hash", "size", "script", "duplicate", "symlink"])
def test_native_ruff_copy_requires_exact_installed_wheel_identity(
    tmp_path: Path, case: str
) -> None:
    site = tmp_path / "dependencies/lib/python3.11/site-packages"
    site.mkdir(parents=True)
    source = tmp_path / "dependencies/bin/ruff"
    executable = b"\x7fELFcomponent native tool, never executed"
    if case == "script":
        executable = b"#!/bin/sh\ncomponent tool, never executed"
    atomic_write_bytes(source, executable)
    digest = base64.urlsafe_b64encode(bytes.fromhex(sha256_bytes(executable))).rstrip(b"=")
    record = b"../../../bin/ruff,sha256=" + digest + b"," + str(len(executable)).encode() + b"\n"
    if case == "hash":
        record = record.replace(digest, b"incorrect")
    elif case == "size":
        record = record.replace(str(len(executable)).encode(), b"0")
    elif case == "duplicate":
        record *= 2
    elif case == "symlink":
        source.rename(source.with_name("other"))
        source.symlink_to("other")
    atomic_write_bytes(site / "ruff-0.16.5.dist-info/RECORD", record)
    before = raw_inventory(site)
    target = tmp_path / "frozen-python"
    shutil.copytree(site, target / "lib/python3.11/site-packages")
    if case != "valid":
        with pytest.raises(ArtifactIntegrityError):
            _freeze_ruff_executable(site, target)
        assert not (target / "bin/ruff").exists()
    else:
        _freeze_ruff_executable(site, target)
        assert (target / "bin/ruff").read_bytes() == executable
        assert (target / "bin/ruff").stat().st_mode & 0o777 == 0o500
        assert os.access(target / "bin/ruff", os.X_OK)
    assert raw_inventory(site) == before


def test_dependency_install_without_optional_ruff_is_not_given_an_external_tool(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    target = tmp_path / "frozen-python"
    (target / "lib/python3.11/site-packages").mkdir(parents=True)
    _freeze_ruff_executable(site, target)
    assert not (target / "bin/ruff").exists()


def test_native_tool_is_bound_to_already_copied_record_when_source_changes(tmp_path: Path) -> None:
    site = tmp_path / "dependencies/lib/python3.11/site-packages"
    source = tmp_path / "dependencies/bin/ruff"
    original = b"\x7fELForiginal wheel-bound component tool"
    replacement = b"\x7fELFchanged external component tool"
    atomic_write_bytes(source, original)

    def record(data: bytes) -> bytes:
        digest = base64.urlsafe_b64encode(bytes.fromhex(sha256_bytes(data))).rstrip(b"=")
        return b"../../../bin/ruff,sha256=" + digest + b"," + str(len(data)).encode() + b"\n"

    metadata = site / "ruff-0.16.5.dist-info/RECORD"
    atomic_write_bytes(metadata, record(original))
    target = tmp_path / "frozen-python"
    shutil.copytree(site, target / "lib/python3.11/site-packages")
    frozen = raw_inventory(target)
    # Simulate external dependency replacement after the metadata copy.
    source.write_bytes(replacement)
    metadata.write_bytes(record(replacement))
    with pytest.raises(ArtifactIntegrityError):
        _freeze_ruff_executable(site, target)
    assert not (target / "bin/ruff").exists()
    assert raw_inventory(target) == frozen
