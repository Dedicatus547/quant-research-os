"""Real process exits around the immutable openat/file/directory fsync primitive."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_campaign import _service, _spec

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_fixture_frames import duplicate_frame
from quantos.infrastructure.hosted_store import HostedProtocolStore

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


@pytest.mark.parametrize(
    "window", ("file_fsynced", "file_linked", "file_published", "directory_fsynced")
)
def test_fresh_spec_registration_rejects_unfinished_publication_without_repair(
    tmp_path: Path, window: str
) -> None:
    spec = _spec(_inputs(tmp_path / "inputs"))
    root = tmp_path / "protocol"
    pid = os.fork()
    if pid == 0:

        def stop(point: str) -> None:
            if point == f"spec_{window}":
                os._exit(73)

        HostedProtocolStore(root, fault_hook=stop).register_spec(spec)
        os._exit(1)
    observed, status = os.waitpid(pid, 0)
    assert observed == pid and os.waitstatus_to_exitcode(status) == 73

    def physical_files():
        return tuple(
            (path.name, path.stat().st_ino, path.stat().st_nlink, sha256_bytes(path.read_bytes()))
            for path in sorted((root / "specs").iterdir())
        )

    original = physical_files()
    fresh = HostedProtocolStore(root)
    if window in ("file_fsynced", "file_linked"):
        with pytest.raises(ArtifactIntegrityError, match=r"spec|hard-link|one link"):
            fresh.register_spec(spec)
        with pytest.raises(ArtifactIntegrityError, match=r"spec|hard-link|one link"):
            fresh.spec(spec.content_hash)
    else:
        assert fresh.register_spec(spec) == spec.content_hash
        assert fresh.spec(spec.content_hash) == spec
    assert physical_files() == original


@pytest.mark.parametrize("domain", ("journal", "object"))
@pytest.mark.parametrize(
    "window", ("file_fsynced", "file_linked", "file_published", "directory_fsynced")
)
def test_partial_native_registration_checks_disk_before_recovery_writes(
    tmp_path: Path, domain: str, window: str
) -> None:
    spec = _spec(_inputs(tmp_path / "inputs"))
    root = tmp_path / "protocol"
    pid = os.fork()
    if pid == 0:

        def stop(point: str) -> None:
            if point == f"{domain}_{window}":
                os._exit(73)

        service = HostedProtocolService(
            HostedProtocolStore(root, fault_hook=stop),
            verify_inputs=lambda _: None,
            clock=lambda: spec.started_at,
        )
        service.register(spec)
        service.start(spec.content_hash)
        os._exit(1)
    observed, status = os.waitpid(pid, 0)
    assert observed == pid and os.waitstatus_to_exitcode(status) == 73

    def physical_tree():
        return tuple(
            (
                path.relative_to(root).as_posix(),
                path.stat().st_ino,
                path.stat().st_nlink,
                sha256_bytes(path.read_bytes()) if path.is_file() else None,
            )
            for path in sorted(root.rglob("*"))
        )

    original = physical_tree()
    fresh = HostedProtocolService(
        HostedProtocolStore(root), verify_inputs=lambda _: None, clock=lambda: spec.started_at
    )
    if window in ("file_fsynced", "file_linked"):
        with pytest.raises(ArtifactIntegrityError):
            fresh.start(spec.content_hash)
        assert physical_tree() == original
    else:
        status = fresh.start(spec.content_hash)
        recovered = physical_tree()
        assert fresh.start(spec.content_hash) == status
        assert physical_tree() == recovered


@pytest.mark.parametrize("shared_with_pending", (False, True))
def test_missing_old_complete_object_rejects_before_finishing_new_intent(
    tmp_path: Path, shared_with_pending: bool
) -> None:
    inputs = _inputs(tmp_path / "inputs")
    spec = _spec(inputs)
    authority = tmp_path / "authority"
    application = _service(authority, inputs, spec)
    application.start(spec.content_hash)
    request = application.pending(spec.campaign_hash)
    assert request is not None
    initial = application.protocol.store.snapshot(spec.campaign_hash, recover=False)
    pid = os.fork()
    if pid == 0:

        def stop(point: str) -> None:
            if point == "intent_published":
                os._exit(73)

        fresh = HostedProtocolStore(authority / "protocol", fault_hook=stop)
        if shared_with_pending:
            # Store-only controlled publication shares exactly the old spec
            # object; this is not a native business or qualification fixture.
            with fresh.campaign_lock(spec.campaign_hash) as descriptor:
                fresh.commit_locked(
                    descriptor,
                    campaign_hash=spec.campaign_hash,
                    operation_id="f" * 64,
                    operation_kind="BUSINESS",
                    recorded_at=spec.started_at,
                    artifacts=(spec,),
                )
        else:
            protocol = HostedProtocolService(fresh, clock=lambda: spec.started_at)
            protocol.submit(
                request.content_hash, duplicate_frame(request, "accepted"), "native.test"
            )
        os._exit(1)
    observed, status = os.waitpid(pid, 0)
    assert observed == pid and os.waitstatus_to_exitcode(status) == 73
    assert initial.journal[0].publications[0].artifact_hash == spec.content_hash
    objects = authority / "protocol/campaigns" / spec.campaign_hash / "objects"
    (objects / f"{spec.content_hash}.json").unlink()
    original = tuple(
        (path.relative_to(authority), path.read_bytes())
        for path in sorted(authority.rglob("*"))
        if path.is_file()
    )
    with pytest.raises(ArtifactIntegrityError, match="completed publication is missing"):
        HostedProtocolStore(authority / "protocol").snapshot(spec.campaign_hash, recover=True)
    assert original == tuple(
        (path.relative_to(authority), path.read_bytes())
        for path in sorted(authority.rglob("*"))
        if path.is_file()
    )
