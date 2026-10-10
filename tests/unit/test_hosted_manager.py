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
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES, private_memory_fd
from quantos.infrastructure.hosted_manager import (
    _observe_namespace_child,
    run_managed_negative_case,
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
def test_start_cannot_reuse_stale_channel_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    from quantos.infrastructure import hosted_manager

    # This isolates stale-channel rejection from the independently tested storage guard.
    monkeypatch.setattr(hosted_manager, "storage_checkpoint", lambda *_: None)
    channel = tmp_path / "channel"
    channel.mkdir()
    saved = channel / entry
    saved.write_bytes(b"old service evidence")
    deployment = SimpleNamespace(
        root=tmp_path,
        paths=SimpleNamespace(channel=channel),
        profile=SimpleNamespace(mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES)),
    )
    with pytest.raises(ArtifactIntegrityError, match="empty stopped channel"):
        start_managed_service(deployment)
    assert saved.read_bytes() == b"old service evidence"


@pytest.mark.parametrize(
    "executable", ["/bin/false", "/bin/true", "/missing-worker-fixture", "/timeout-worker-fixture"]
)
def test_negative_worker_retains_prelaunch_and_failed_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, executable: str
) -> None:
    from quantos.contracts.hosted import strict_json_object
    from quantos.contracts.hosted_qualification import HostedRawInventory
    from quantos.infrastructure import hosted_manager
    from quantos.infrastructure.hosted_verification import raw_inventory

    # Synthetic workers exercise completion retention, never a real storage quota.
    monkeypatch.setattr(hosted_manager, "storage_checkpoint", lambda *_: None)

    channel, evidence = tmp_path / "channel", tmp_path / "evidence"
    channel.mkdir()
    evidence.mkdir()
    deployment = SimpleNamespace(
        root=tmp_path,
        paths=SimpleNamespace(channel=channel),
        profile=SimpleNamespace(
            content_hash="d" * 64,
            mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
        ),
        bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash="a" * 64)),
        install=SimpleNamespace(
            files=[
                SimpleNamespace(
                    relative_path="python/lib/python3.11/site-packages/quantos/infrastructure/hosted_negative_probe.py",
                    bytes_hash="b" * 64,
                )
            ]
        ),
        capability=b"non-secret-fixture-capability-12345678",
    )
    # Actual process failure tests durable management records. This substituted
    # namespace argv cannot count as an isolation or original qualification proof.
    monkeypatch.setattr(
        "quantos.infrastructure.hosted_manager.replace",
        lambda paths, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "quantos.infrastructure.hosted_manager.namespace_command",
        lambda *args, **kwargs: (
            ("/bin/sleep", "60") if executable == "/timeout-worker-fixture" else (executable,)
        ),
    )
    if executable == "/timeout-worker-fixture":
        actual_popen = subprocess.Popen

        def injected_wait_timeout(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = actual_popen(*args, **kwargs)
            actual_wait = process.wait

            def wait(timeout: float | None = None) -> int:
                if timeout == 300:
                    raise subprocess.TimeoutExpired("fixed-timeout-fixture", timeout)
                return actual_wait(timeout=timeout)

            monkeypatch.setattr(process, "wait", wait)
            return process

        monkeypatch.setattr(
            "quantos.infrastructure.hosted_manager.subprocess.Popen", injected_wait_timeout
        )
        monkeypatch.setattr(
            "quantos.infrastructure.hosted_manager._observe_namespace_child", lambda *args: {}
        )
    with pytest.raises((ArtifactIntegrityError, FileNotFoundError, subprocess.TimeoutExpired)):
        run_managed_negative_case(deployment, "campaign_hash")
    saved = raw_inventory(tmp_path)
    records = [
        strict_json_object(path.read_bytes(), max_bytes=16_777_216) for path in evidence.iterdir()
    ]
    prelaunch = next(
        record
        for record in records
        if record["schema_version"] == "hosted-manager-negative-prelaunch/v1"
    )
    if executable in ("/bin/false", "/bin/true"):
        completion = next(
            record
            for record in records
            if record["schema_version"] == "hosted-manager-negative-run/v1"
        )
        assert completion["return_code"] == (1 if executable.endswith("false") else 0)
        assert completion["observation_hash"] is None
        assert completion["manager_child_observation"] is None
        assert completion["qualification_eligibility"] == "NOT_QUALIFIED"
    else:
        assert not any(
            record["schema_version"] == "hosted-manager-negative-run/v1" for record in records
        )
        failure = next(
            record
            for record in records
            if record["schema_version"] == "hosted-manager-negative-invocation-failure/v1"
        )
        assert failure["error_type"] == (
            "FileNotFoundError" if executable == "/missing-worker-fixture" else "TimeoutExpired"
        )
        assert failure["completion_status"] == "NOT_OBSERVED"
        assert "return_code" not in failure
        assert (failure["wrapper_pid"] is None) == (executable == "/missing-worker-fixture")
        assert failure["qualification_eligibility"] == "NOT_QUALIFIED"
    assert not HostedRawInventory.model_validate(prelaunch["authority_before_inventory"]).files
    with pytest.raises(ArtifactIntegrityError, match="new retained root"):
        run_managed_negative_case(deployment, "campaign_hash")
    assert raw_inventory(tmp_path) == saved


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
