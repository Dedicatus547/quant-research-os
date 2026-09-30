"""Manager provenance and stopped-channel guards; these are component tests only."""

from __future__ import annotations

import os
import subprocess
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_manager import (
    _observe_namespace_child,
    start_managed_service,
    stop_managed_service,
    verify_wheel_provenance,
)


@pytest.mark.parametrize("mutation", [None, "changed", "missing", "extra", "duplicate"])
def test_wheel_must_match_tracked_checkout(tmp_path: Path, mutation: str | None) -> None:
    workspace = tmp_path / "source"
    source = workspace / "src/quantos"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"VERSION = 'frozen'\n")
    subprocess.run(("git", "init", "--quiet", str(workspace)), check=True)
    subprocess.run(("git", "-C", str(workspace), "add", "src"), check=True)
    wheel = tmp_path / "project.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        if mutation != "missing":
            archive.writestr(
                "quantos/__init__.py",
                b"changed" if mutation == "changed" else (source / "__init__.py").read_bytes(),
            )
        if mutation == "extra":
            archive.writestr("quantos/plugin.py", b"untrusted")
        if mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("quantos/__init__.py", b"replacement")
    if mutation is None:
        verify_wheel_provenance(workspace, wheel)
    else:
        with pytest.raises(ArtifactIntegrityError, match="wheel project"):
            verify_wheel_provenance(workspace, wheel)


def test_stop_preserves_bootstrap_and_rejects_unexpected_channel_entry(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    channel.mkdir()
    (tmp_path / "evidence").mkdir()
    observation = b'{"source":"actual-service-bootstrap"}'
    (channel / "bootstrap-observation.json").write_bytes(observation)
    process = subprocess.Popen(("/bin/sleep", "60"))
    deployment = SimpleNamespace(
        paths=SimpleNamespace(channel=channel), capability=b"q" * 32, root=tmp_path
    )
    stop_managed_service(deployment, process)
    assert process.poll() is not None
    assert list(channel.iterdir()) == []
    assert [path.read_bytes() for path in (tmp_path / "evidence").iterdir()] == [observation]
    (channel / "unexpected").write_bytes(b"retain this evidence")
    process = subprocess.Popen(("/bin/sleep", "60"))
    with pytest.raises(ArtifactIntegrityError, match="unexpected"):
        stop_managed_service(deployment, process)
    assert (channel / "unexpected").read_bytes() == b"retain this evidence"


@pytest.mark.parametrize("entry", ["quantos.sock", "bootstrap-observation.json", "unknown"])
def test_start_cannot_reuse_stale_channel_attestation(tmp_path: Path, entry: str) -> None:
    channel = tmp_path / "channel"
    channel.mkdir()
    saved = channel / entry
    saved.write_bytes(b"old service evidence")
    deployment = SimpleNamespace(paths=SimpleNamespace(channel=channel))
    with pytest.raises(ArtifactIntegrityError, match="empty stopped channel"):
        start_managed_service(deployment)
    assert saved.read_bytes() == b"old service evidence"


def test_manager_observes_kernel_child_identity_and_rejects_wrong_binding() -> None:
    descriptor = private_memory_fd("test-manager-container-info")
    command = ("/usr/bin/sleep", "30")
    process = subprocess.Popen(
        (
            "/usr/bin/bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--info-fd",
            str(descriptor),
            *command,
        ),
        pass_fds=(descriptor,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not os.pread(descriptor, 4096, 0):
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        # info is emitted before exec; wait until the exact child command appears.
        while True:
            try:
                observation = _observe_namespace_child(process.pid, descriptor, command)
                break
            except ArtifactIntegrityError:
                assert time.monotonic() < deadline
                time.sleep(0.05)
        assert observation["wrapper_pid"] == process.pid
        assert observation["service_command"] == command
        assert (
            observation["service_executable_hash"]
            == __import__("hashlib").sha256(Path("/usr/bin/sleep").read_bytes()).hexdigest()
        )
        assert observation["service_namespace_identities"] != {
            name: os.readlink(f"/proc/self/ns/{name}") for name in ("net", "pid", "mnt", "user")
        }
        with pytest.raises(ArtifactIntegrityError, match="command differs"):
            _observe_namespace_child(process.pid, descriptor, ("/usr/bin/unapproved",))
        with pytest.raises(ArtifactIntegrityError, match="launched wrapper child"):
            _observe_namespace_child(os.getpid(), descriptor, command)
    finally:
        process.terminate()
        process.wait(timeout=10)
        os.close(descriptor)
