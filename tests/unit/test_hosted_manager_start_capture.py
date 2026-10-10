"""Startup capture with explicit socket/process/namespace observation doubles.

Real private memfds and cleanup run. These records cannot establish OS isolation.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_hosted_manager_client_capture import _deployment

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_manager as manager
from quantos.security import SecretArtifactRejected


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Socket/process doubles establish cleanup behavior, never a production storage quota.
    monkeypatch.setattr(manager, "storage_checkpoint", lambda *_: None)


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "occupied",
        "spawn",
        "secret",
        "early_exit",
        "timeout",
        "observation",
        "kill",
        "socket",
        "bind",
        "listen",
        "connect",
        "information_fd",
        "close_bind",
        "close_observation",
        "close_success",
    ),
)
def test_startup_closes_capability_and_information_fds_and_reaps_failures(
    tmp_path, monkeypatch, damage
):
    deployment = _deployment(tmp_path)
    descriptors = []
    events = []
    memory = manager.private_memory_fd

    def allocate(name):
        if name == "service-container-information" and damage == "information_fd":
            raise OSError("synthetic information FD allocation failure")
        fd = memory(name)
        descriptors.append(fd)
        return fd

    monkeypatch.setattr(manager, "private_memory_fd", allocate)

    class Listener:
        def bind(self, address):
            if damage in ("bind", "close_bind"):
                raise OSError("synthetic bind failure")
            assert address == ("127.0.0.1", 0)

        def listen(self, count):
            if damage == "listen":
                raise OSError("synthetic listen failure")
            assert count == 2

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def accept(self):
            return (SimpleNamespace(close=lambda: events.append("control_closed")), None)

        def close(self):
            events.append("listener_closed")
            if damage in ("close_bind", "close_observation", "close_success"):
                raise OSError("synthetic listener close failure")

    def listener(*args):
        if damage == "socket":
            raise OSError("synthetic socket allocation failure")
        return Listener()

    monkeypatch.setattr(manager.socket, "socket", listener)

    def connect(*args, **kwargs):
        if damage == "connect":
            raise OSError("synthetic control connection failure")
        return contextlib.nullcontext()

    monkeypatch.setattr(manager.socket, "create_connection", connect)

    class Process:
        pid = 12345

        def poll(self):
            return 7 if damage == "early_exit" else None

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

        def wait(self, timeout):
            events.append(("wait", timeout))
            if damage == "kill" and "kill" not in events:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            return 0

    process = Process()

    def popen(argv, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        assert kwargs["start_new_session"] is True
        start = argv.index("/install/python-seeded")
        assert argv[start:] == (
            "/install/python-seeded",
            "-m",
            "quantos.infrastructure.hosted_service",
            "--profile-hash",
            deployment.profile.content_hash,
            "--network-probe-port",
            "43210",
        )
        assert any(os.pread(fd, 32, 0) == deployment.capability for fd in kwargs["pass_fds"])
        if damage == "spawn":
            raise OSError("synthetic spawn failure")
        if damage != "timeout":
            (deployment.paths.channel / "quantos.sock").write_bytes(b"synthetic socket marker")
            (deployment.paths.channel / "bootstrap-observation.json").write_bytes(
                canonical_json_bytes(
                    {
                        "synthetic_component": True,
                        "value": deployment.capability.hex() if damage == "secret" else "safe",
                    }
                )
            )
        return process

    monkeypatch.setattr(manager.subprocess, "Popen", popen)

    def observe(*args):
        if damage in ("observation", "kill", "close_observation"):
            raise ArtifactIntegrityError("synthetic observation failure")
        return {"synthetic_namespace_double": True}

    monkeypatch.setattr(manager, "_observe_namespace_child", observe)
    if damage == "timeout":
        ticks = iter((0, 121))
        monkeypatch.setattr(
            manager, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda n: None)
        )
    if damage == "occupied":
        (deployment.paths.channel / "retained").write_bytes(b"original retained channel")
    if damage is None:
        assert manager.start_managed_service(deployment) is process
        assert "terminate" not in events and "kill" not in events
        records = tuple((tmp_path / "evidence").glob("service-start-*.json"))
        assert len(records) == 1 and b"NOT_QUALIFIED" in records[0].read_bytes()
    else:
        with pytest.raises((ArtifactIntegrityError, OSError, SecretArtifactRejected)):
            manager.start_managed_service(deployment)
        records = tuple((tmp_path / "evidence").glob("service-start-*.json"))
        if damage == "close_success":
            assert len(records) == 1 and b"NOT_QUALIFIED" in records[0].read_bytes()
            assert "terminate" in events and ("wait", 10) in events
        else:
            assert not records
        if damage not in (
            "occupied",
            "spawn",
            "early_exit",
            "socket",
            "bind",
            "listen",
            "connect",
            "information_fd",
            "close_bind",
        ):
            assert "terminate" in events and ("wait", 10) in events
        if damage == "kill":
            assert "kill" in events and events.count(("wait", 10)) == 2
        if damage == "occupied":
            assert (
                deployment.paths.channel / "retained"
            ).read_bytes() == b"original retained channel"
    leaked = []
    for fd in descriptors:
        try:
            os.fstat(fd)
        except OSError:
            pass
        else:
            leaked.append(fd)
            os.close(fd)
    assert leaked == []
    if damage not in ("occupied", "socket", "information_fd"):
        assert events.count("listener_closed") == 1


@pytest.mark.parametrize("damage", (None, "write", "partial", "seek"))
def test_private_memory_staging_closes_its_real_descriptor_on_failure(monkeypatch, damage):
    payload = b"synthetic memory value; never provider authentication"
    descriptors = []
    allocate = manager.private_memory_fd
    original_write = manager.os.write
    original_seek = manager.os.lseek

    def memory(name):
        fd = allocate(name)
        descriptors.append(fd)
        return fd

    def write(fd, data):
        if data == payload:
            if damage == "write":
                raise OSError("synthetic write failure")
            if damage == "partial":
                return original_write(fd, data[:-1])
        return original_write(fd, data)

    def seek(fd, offset, whence):
        if damage == "seek" and fd in descriptors:
            raise OSError("synthetic seek failure")
        return original_seek(fd, offset, whence)

    with monkeypatch.context() as patch:
        patch.setattr(manager, "private_memory_fd", memory)
        patch.setattr(manager.os, "write", write)
        patch.setattr(manager.os, "lseek", seek)
        if damage is None:
            fd = manager._memory(payload, "synthetic-component-memory")
            try:
                assert os.pread(fd, len(payload) + 1, 0) == payload
                assert os.lseek(fd, 0, os.SEEK_CUR) == 0
                assert not os.get_inheritable(fd)
            finally:
                os.close(fd)
        else:
            with pytest.raises((ArtifactIntegrityError, OSError)):
                manager._memory(payload, "synthetic-component-memory")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


@pytest.mark.parametrize("close_error", (False, True))
def test_readiness_cleanup_keeps_ownership_of_a_real_child(tmp_path, monkeypatch, close_error):
    """A real child proves reaping; startup networking and readiness are doubles."""
    deployment = _deployment(tmp_path)
    descriptors = []
    children = []
    memory = manager.private_memory_fd
    original_popen = subprocess.Popen

    def allocate(name):
        descriptor = memory(name)
        descriptors.append(descriptor)
        return descriptor

    class Listener:
        def bind(self, address):
            pass

        def listen(self, count):
            pass

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def accept(self):
            return (SimpleNamespace(close=lambda: None), None)

        def close(self):
            if close_error:
                raise OSError("synthetic listener close failure")

    def start_child(*args, **kwargs):
        child = original_popen(
            (sys.executable, "-I", "-B", "-c", "import time; time.sleep(3600)"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        children.append(child)
        return child

    monkeypatch.setattr(manager, "private_memory_fd", allocate)
    monkeypatch.setattr(manager.socket, "socket", lambda *args: Listener())
    monkeypatch.setattr(
        manager.socket, "create_connection", lambda *a, **k: contextlib.nullcontext()
    )
    monkeypatch.setattr(manager, "namespace_command", lambda *a, **k: ("synthetic-control",))
    monkeypatch.setattr(manager.subprocess, "Popen", start_child)
    monkeypatch.setattr(manager, "_wait_for_managed_service", lambda _d, process, *args: process)
    try:
        if close_error:
            with pytest.raises(OSError, match="synthetic listener close failure"):
                manager.start_managed_service(deployment)
            assert len(children) == 1
            # Inspect before poll/wait: the implementation must already have reaped it.
            assert children[0].returncode is not None
        else:
            process = manager.start_managed_service(deployment)
            assert process is children[0] and process.poll() is None
        assert not tuple((tmp_path / "evidence").glob("service-start-*.json"))
        assert len(descriptors) == 2
        for descriptor in descriptors:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
