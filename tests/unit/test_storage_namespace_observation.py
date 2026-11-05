"""Parse synthetic mount/pid observations; no host qualification or namespace spawn."""

import json
import os
from pathlib import Path

import pytest

from quantos.infrastructure import hosted_regression_runtime as runtime
from quantos.infrastructure import hosted_storage as storage


@pytest.mark.parametrize(
    "attack",
    [
        "valid",
        "empty",
        "partial",
        "oversize",
        "malformed",
        "boolean_pid",
        "init",
        "missing",
        "parent",
        "namespace",
        "same_namespace",
        "gone",
    ],
)
def test_namespace_descriptor_requires_exact_parent_and_distinct_namespace(
    tmp_path, monkeypatch, attack
):
    value = {"child-pid": 12345, "pid-namespace": 999}
    if attack == "boolean_pid":
        value["child-pid"] = True
    elif attack == "init":
        value["child-pid"] = 1
    elif attack == "missing":
        value.pop("child-pid")
    raw = {
        "empty": b"",
        "partial": b'{"child-pid":',
        "oversize": b"x" * 4097,
        "malformed": b"oops}",
    }.get(attack, json.dumps(value).encode())
    source = tmp_path / "information"
    source.write_bytes(raw)
    descriptor = os.open(source, os.O_RDONLY)
    opened = []

    def pidfd(pid):
        assert pid == 12345
        result = os.open(source, os.O_RDONLY)
        opened.append(result)
        return result

    def status(path, *args, **kwargs):
        assert str(path) == "/proc/12345/status"
        if attack == "gone":
            raise FileNotFoundError
        return "Name:\tsynthetic\nPPid:\t" + ("99" if attack == "parent" else "111") + "\n"

    monkeypatch.setattr(runtime, "native_pidfd_open", pidfd)
    monkeypatch.setattr(Path, "read_text", status)
    monkeypatch.setattr(
        storage.os,
        "readlink",
        lambda p: (
            "pid:[999]"
            if attack == "same_namespace"
            else "pid:[998]"
            if attack == "namespace"
            else "pid:[777]"
            if p == "/proc/self/ns/pid"
            else "pid:[999]"
        ),
    )
    try:
        if attack in {"empty", "partial"}:
            assert storage._namespace_pidfd(111, descriptor) is None
        elif attack == "valid":
            result = storage._namespace_pidfd(111, descriptor)
            assert result == opened[0]
            os.close(result)
        else:
            with pytest.raises(storage.StorageRejected):
                storage._namespace_pidfd(111, descriptor)
            for result in opened:
                with pytest.raises(OSError):
                    os.fstat(result)
    finally:
        os.close(descriptor)


def test_mount_lookup_decodes_kernel_names_and_chooses_deepest_prefix(monkeypatch):
    lines = (
        "1 0 0:1 / / rw - ext4 none rw\n"
        "2 1 0:2 / /data/a\\040b rw - drvfs none rw\n"
        "3 2 0:3 / /data/a\\040b/scratch rw - tmpfs none rw\n"
    )
    monkeypatch.setattr(Path, "read_text", lambda _: lines)
    assert storage.storage_mount_identity(Path("/data/a b/scratch/new")) == (
        "tmpfs",
        Path("/data/a b/scratch"),
    )
    assert storage.storage_mount_identity(Path("/data/a b/archive")) == ("drvfs", Path("/data/a b"))
    monkeypatch.setattr(Path, "read_text", lambda _: "")
    with pytest.raises(storage.StorageRejected, match="MOUNT_UNAVAILABLE"):
        storage.storage_mount_identity(Path("/unavailable"))
