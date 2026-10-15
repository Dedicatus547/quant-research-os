"""Small resource-management fixtures; simulated capacity is never a real quota.

Only short local children run. Mount and capacity observations are injected: these
tests cannot establish a mounted hard quota or hosted research qualification.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from quantos.infrastructure import hosted_storage as storage


@pytest.fixture
def guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[storage.StorageGuard]:
    # Production rejects /tmp evidence. Test capacity/mounts remain synthetic,
    # but the evidence path must reach the intended guard predicate on CI too.
    with TemporaryDirectory(
        prefix="storage-test-", dir=Path(__file__).parents[2] / "artifacts"
    ) as root:
        yield _guard(Path(root), tmp_path, monkeypatch)


def _guard(evidence: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> storage.StorageGuard:
    scratch, host = (tmp_path / name for name in ("scratch", "host"))
    for directory in (scratch, host):
        directory.mkdir()
    vhd = host / "bound.vhdx"
    vhd.write_bytes(b"synthetic binding, never a real VHD")
    policy = storage.StoragePolicy(
        evidence,
        scratch,
        host,
        vhd,
        storage.GIB,
        storage.GIB,
        8 << 20,
        poll_seconds=0.01,
        terminate_grace_seconds=0.04,
    )
    mounts = {evidence: ("ext4", evidence), scratch: ("tmpfs", scratch), host: ("drvfs", host)}
    monkeypatch.setattr(storage, "_mount", mounts.__getitem__)
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (8 << 20, 8 << 20, 4096)
            if path == scratch
            else (3 * storage.GIB, 4 * storage.GIB, 4096)
        ),
    )
    return storage.StorageGuard(policy)


def _child(source: str, *args: str) -> tuple[str, ...]:
    return (sys.executable, "-B", "-c", source, *args)


def _records(guard: storage.StorageGuard) -> list[tuple[Path, dict]]:
    return [
        (path.parent, json.loads(path.read_bytes()))
        for path in sorted((guard.policy.evidence_root / "storage-control").glob("run-*/exit.json"))
    ]


def _assert_reaped(record: dict) -> None:
    assert record["waitpid_observed"] is True
    with pytest.raises(ChildProcessError):
        os.waitpid(record["pid"], os.WNOHANG)


def test_host_headroom_is_required_even_when_linux_has_space(guard, monkeypatch):
    capacity = storage._capacity
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (storage.GIB - 1, 4 * storage.GIB, 4096)
            if path == guard.policy.host_volume
            else capacity(path)
        ),
    )
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_HOST_HEADROOM$"):
        guard.check()


@pytest.mark.parametrize(
    "path_name,code",
    [
        ("evidence_root", "STORAGE_LINUX_HEADROOM"),
        ("host_volume", "STORAGE_HOST_HEADROOM"),
    ],
)
def test_new_bytes_are_reserved_on_both_volumes(guard, monkeypatch, path_name, code):
    capacity = storage._capacity
    path = getattr(guard.policy, path_name)
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda candidate: (
            (storage.GIB + 999, 4 * storage.GIB, 4096) if candidate == path else capacity(candidate)
        ),
    )
    with pytest.raises(storage.StorageRejected, match=f"^{code}$"):
        guard.check(expected_new_bytes=1000)


def test_policy_reserves_cannot_be_less_than_one_gib(guard):
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_INVALID$"):
        replace(guard.policy, linux_reserve_bytes=storage.GIB - 1)


@pytest.mark.parametrize("missing", [storage.POLICY_ENV, storage.HASH_ENV])
def test_missing_explicit_policy_binding_fails_closed(tmp_path, monkeypatch, missing):
    monkeypatch.setenv(storage.POLICY_ENV, str(tmp_path / "absent-policy.json"))
    monkeypatch.setenv(storage.HASH_ENV, "a" * 64)
    monkeypatch.delenv(missing)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_UNAVAILABLE$"):
        storage.storage_checkpoint(tmp_path / "output", "deployment")
    assert not (tmp_path / "output").exists()


def test_policy_configuration_reads_only_non_secret_settings(guard, tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_bytes(guard.policy.canonical_bytes())
    allowed = {storage.POLICY_ENV: str(path), storage.HASH_ENV: guard.policy_hash}
    observed = []

    class RestrictedEnvironment:
        def get(self, key):
            assert key in allowed, "configuration must not inspect unrelated environment keys"
            observed.append(key)
            return allowed[key]

    monkeypatch.setattr(storage, "os", SimpleNamespace(environ=RestrictedEnvironment()))
    configured = storage.configured_guard()
    assert configured.policy_hash == guard.policy_hash
    assert observed == [storage.POLICY_ENV, storage.HASH_ENV]


def test_changed_policy_hash_is_rejected(guard, tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_bytes(guard.policy.canonical_bytes())
    monkeypatch.setenv(storage.POLICY_ENV, str(path))
    monkeypatch.setenv(storage.HASH_ENV, "f" * 64)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_HASH_MISMATCH$"):
        storage.configured_guard()


def test_temporary_evidence_is_rejected(guard):
    temporary = storage.StorageGuard(replace(guard.policy, evidence_root=Path("/tmp")))
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_EVIDENCE_TEMPORARY$"):
        temporary.validate_layout()


def test_evidence_and_output_symlink_escapes_are_rejected(guard, tmp_path):
    alias = tmp_path / "evidence-alias"
    alias.symlink_to(guard.policy.evidence_root, target_is_directory=True)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_PATH_ALIAS$"):
        storage.StorageGuard(replace(guard.policy, evidence_root=alias)).validate_layout()
    escaped = guard.policy.evidence_root / "escape"
    escaped.symlink_to(guard.policy.host_volume, target_is_directory=True)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_PATH_ALIAS$"):
        guard.require_root(escaped / "new-output")
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_OUTPUT_OUTSIDE_EVIDENCE$"):
        guard.require_root(guard.policy.host_volume / "new-output")


@pytest.mark.parametrize("filesystem,mounted_root", [("ext4", True), ("tmpfs", False)])
def test_scratch_directory_polling_does_not_establish_a_hard_quota(
    guard,
    monkeypatch,
    filesystem,
    mounted_root,
):
    mount = storage._mount
    monkeypatch.setattr(
        storage,
        "_mount",
        lambda path: (
            (filesystem, path if mounted_root else path.parent)
            if path == guard.policy.scratch_root
            else mount(path)
        ),
    )
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_SCRATCH_HARD_QUOTA_UNAVAILABLE$"):
        guard.validate_layout()


def test_mounted_scratch_total_cannot_exceed_declared_cap(guard, monkeypatch):
    capacity = storage._capacity
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (8 << 20, (8 << 20) + 1, 4096) if path == guard.policy.scratch_root else capacity(path)
        ),
    )
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_SCRATCH_QUOTA_EXCEEDS_POLICY$"):
        guard.validate_layout()


@pytest.mark.parametrize(
    "volume,code",
    [
        ("evidence_root", "STORAGE_LINUX_HEADROOM"),
        ("host_volume", "STORAGE_HOST_HEADROOM"),
    ],
)
def test_declining_capacity_aborts_child_and_retains_actual_failure(
    guard, monkeypatch, volume, code
):
    capacity = storage._capacity
    samples = 0

    def declining(path):
        nonlocal samples
        if path == getattr(guard.policy, volume):
            samples += 1
            return (3 * storage.GIB if samples < 3 else storage.GIB - 1, 4 * storage.GIB, 4096)
        return capacity(path)

    monkeypatch.setattr(storage, "_capacity", declining)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child("import time; time.sleep(5)"),
            stage="local-validation",
            expected_new_bytes=1024,
        )
    run, record = _records(guard)[0]
    assert samples >= 3 and record["failure"] == code
    assert record["execution"] == "FAILED" and record["validation"] == "NOT_EVALUATED"
    assert record["qualification_eligibility"] == "NOT_QUALIFIED"
    assert record["return_code"] != 0 and not (run / "record-reserve").exists()
    _assert_reaped(record)


def test_exceeding_new_byte_estimate_aborts_before_reserves_are_exhausted(guard, monkeypatch):
    capacity = storage._capacity
    samples = 0

    def growth(path):
        nonlocal samples
        if path == guard.policy.evidence_root:
            samples += 1
            return (3 * storage.GIB - (0 if samples == 1 else 1025), 4 * storage.GIB, 4096)
        return capacity(path)

    monkeypatch.setattr(storage, "_capacity", growth)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child("import time; time.sleep(5)"),
            stage="local-validation",
            expected_new_bytes=1024,
        )
    record = _records(guard)[0][1]
    assert record["failure"] == "STORAGE_ESTIMATE_EXCEEDED"
    _assert_reaped(record)


def test_fast_child_still_receives_post_exit_capacity_check(guard, monkeypatch):
    capacity = storage._capacity
    samples = 0
    real_popen = storage.subprocess.Popen

    def already_finished(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        process.wait(timeout=2)
        return process

    def post_exit_failure(path):
        nonlocal samples
        if path == guard.policy.host_volume:
            samples += 1
            return (3 * storage.GIB if samples == 1 else storage.GIB - 1, 4 * storage.GIB, 4096)
        return capacity(path)

    monkeypatch.setattr(storage.subprocess, "Popen", already_finished)
    monkeypatch.setattr(storage, "_capacity", post_exit_failure)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard, _child("pass"), stage="local-validation", expected_new_bytes=0
        )
    record = _records(guard)[0][1]
    assert samples == 3 and record["return_code"] == 0
    assert record["failure"] == "STORAGE_HOST_HEADROOM" and record["execution"] == "FAILED"
    _assert_reaped(record)


def test_nonzero_child_failure_is_preserved_and_records_do_not_capture_argv_or_output(guard):
    sentinel = "PRIVATE-CHILD-ARGUMENT-AND-OUTPUT"
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child(
                "import sys; print(sys.argv[1]); print(sys.argv[1], file=sys.stderr); sys.exit(7)",
                sentinel,
            ),
            stage="local-validation",
            expected_new_bytes=0,
        )
    run, record = _records(guard)[0]
    retained = {path.name: path.read_bytes() for path in run.iterdir()}
    assert record["return_code"] == 7 and record["execution"] == "FAILED"
    assert record["failure"] is None and record["validation"] == "NOT_EVALUATED"
    assert set(retained) == {"prelaunch.json", "exit.json", "policy.json"}
    assert record["process_scope"] == "LOCAL_DIRECT_CHILD"
    assert record["namespace_exit_observed"] is None and record["cleanup_verified"] is True
    assert all(sentinel.encode() not in data for data in retained.values())
    success = storage.supervise_storage_job(
        guard, _child("pass"), stage="local-validation", expected_new_bytes=0
    )
    assert success != run and all(
        (run / name).read_bytes() == data for name, data in retained.items()
    )
    _assert_reaped(record)


def test_exclusive_lease_rejects_a_concurrent_second_child(guard):
    ready = guard.policy.scratch_root / "ready"
    second = guard.policy.scratch_root / "second-child"
    outcomes = []

    def first_job():
        try:
            outcomes.append(
                storage.supervise_storage_job(
                    guard,
                    _child(
                        "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); "
                        "time.sleep(.3)",
                        str(ready),
                    ),
                    stage="local-validation",
                    expected_new_bytes=0,
                )
            )
        except BaseException as error:
            outcomes.append(error)

    worker = threading.Thread(target=first_job)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while not ready.exists() and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert ready.exists(), outcomes
        with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_ALREADY_RUNNING$"):
            storage.supervise_storage_job(
                guard,
                _child(
                    "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()",
                    str(second),
                ),
                stage="local-validation",
                expected_new_bytes=0,
            )
        assert not second.exists()
    finally:
        worker.join(timeout=3)
    assert not worker.is_alive() and len(outcomes) == 1 and isinstance(outcomes[0], Path)
    records = _records(guard)
    assert len(records) == 1 and records[0][1]["execution"] == "SUCCEEDED"
    _assert_reaped(records[0][1])


def test_child_ignoring_term_is_killed_and_waited(guard, monkeypatch):
    ready = guard.policy.scratch_root / "ignoring-term"
    capacity = storage._capacity
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (storage.GIB - 1, 4 * storage.GIB, 4096)
            if path == guard.policy.host_volume and ready.exists()
            else capacity(path)
        ),
    )
    start = time.monotonic()
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child(
                "import signal, pathlib, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "pathlib.Path(sys.argv[1]).touch(); time.sleep(5)",
                str(ready),
            ),
            stage="local-validation",
            expected_new_bytes=0,
        )
    record = _records(guard)[0][1]
    assert time.monotonic() - start < 2
    assert record["return_code"] == -signal.SIGKILL
    assert record["execution"] == "FAILED" and record["failure"] == "STORAGE_HOST_HEADROOM"
    _assert_reaped(record)


def test_checkpoint_requires_a_running_supervisor_lease(guard, monkeypatch):
    monkeypatch.setattr(storage, "configured_guard", lambda: guard)
    monkeypatch.delenv(storage.LEASE_ENV, raising=False)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_SUPERVISOR_UNAVAILABLE$"):
        storage.storage_checkpoint(guard.policy.evidence_root / "new-output", "deployment")
    assert not (guard.policy.evidence_root / "new-output").exists()


def test_completed_local_lease_cannot_authorize_a_formal_checkpoint(guard, monkeypatch):
    run = storage.supervise_storage_job(
        guard, _child("pass"), stage="local-validation", expected_new_bytes=0
    )
    monkeypatch.setattr(storage, "configured_guard", lambda: guard)
    monkeypatch.setenv(storage.LEASE_ENV, str(run))
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_LOCAL_LEASE_NOT_FORMAL$"):
        storage.storage_checkpoint(guard.policy.evidence_root / "new-output", "deployment")


def test_active_local_lease_is_rejected_for_formal_execution(guard, monkeypatch):
    control = guard.policy.evidence_root / "storage-control"
    run = control / "local-run"
    run.mkdir(parents=True)
    (run / "prelaunch.json").write_text(
        json.dumps(
            {
                "policy_hash": guard.policy_hash,
                "stage": "local-validation",
            }
        )
    )
    lock = os.open(control / "lease.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.write(lock, json.dumps({"run": str(run), "policy_hash": guard.policy_hash}).encode())
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setenv(storage.LEASE_ENV, str(run))
        with pytest.raises(storage.StorageRejected, match=r"^STORAGE_LOCAL_LEASE_NOT_FORMAL$"):
            guard.require_lease()
    finally:
        os.close(lock)


def test_inactive_formal_lease_is_still_rejected(guard, monkeypatch):
    control = guard.policy.evidence_root / "storage-control"
    run = control / "formal-lease-fixture"
    run.mkdir(parents=True)
    (run / "prelaunch.json").write_text(
        json.dumps(
            {
                "policy_hash": guard.policy_hash,
                "stage": "ci",
            }
        )
    )
    (control / "lease.lock").write_text(
        json.dumps({"run": str(run), "policy_hash": guard.policy_hash})
    )
    monkeypatch.setenv(storage.LEASE_ENV, str(run))
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_SUPERVISOR_NOT_RUNNING$"):
        guard.require_lease()


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_mount_execution_is_rejected_before_configuration_is_read(
    tmp_path, monkeypatch, version
):
    from quantos.infrastructure.hosted_deployment import (
        LEGACY_MOUNT_POLICY_BYTES,
        PRE_STORAGE_MOUNT_POLICY_BYTES,
    )

    def must_not_configure():
        pytest.fail("legacy mount execution must be rejected before storage configuration")

    monkeypatch.setattr(storage, "configured_guard", must_not_configure)
    policy = LEGACY_MOUNT_POLICY_BYTES if version == 1 else PRE_STORAGE_MOUNT_POLICY_BYTES
    with pytest.raises(
        storage.StorageRejected, match=r"^STORAGE_LEGACY_MOUNT_EXECUTION_FORBIDDEN$"
    ):
        storage.storage_checkpoint(
            tmp_path / "new-output", "deployment", 0, storage.sha256_bytes(policy)
        )
    assert not tuple(tmp_path.iterdir())


def test_current_mount_hash_still_requires_an_explicit_storage_policy(tmp_path, monkeypatch):
    from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES

    monkeypatch.delenv(storage.POLICY_ENV, raising=False)
    monkeypatch.delenv(storage.HASH_ENV, raising=False)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_UNAVAILABLE$"):
        storage.storage_checkpoint(
            tmp_path / "new-output", "deployment", 0, storage.sha256_bytes(MOUNT_POLICY_BYTES)
        )
    assert not tuple(tmp_path.iterdir())


def test_launcher_rejects_missing_policy_before_registering_auth_memory(tmp_path, monkeypatch):
    from quantos.infrastructure import hosted_launcher
    from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES

    monkeypatch.delenv(storage.POLICY_ENV, raising=False)
    monkeypatch.delenv(storage.HASH_ENV, raising=False)
    registrations = []
    monkeypatch.setattr(
        hosted_launcher, "register_model_auth_memory", lambda *args: registrations.append(args)
    )
    subject = hosted_launcher.TrustedCodexLauncher.__new__(hosted_launcher.TrustedCodexLauncher)
    subject.paths = SimpleNamespace(configuration=tmp_path / "configuration")
    subject.profile = SimpleNamespace(mount_policy_hash=storage.sha256_bytes(MOUNT_POLICY_BYTES))
    subject.evidence = SimpleNamespace(root=tmp_path, guard=object())
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_UNAVAILABLE$"):
        subject.capture(
            None,
            None,
            None,
            None,
            projection_fact_hash="a" * 64,
            host_instance="synthetic-host",
            model_auth_memory_fd=3,
        )
    assert registrations == [] and not tuple(tmp_path.iterdir())


def test_supervisor_builds_child_environment_without_reading_parent_environment(guard, monkeypatch):
    class ForbiddenEnvironment:
        def get(self, *_):
            pytest.fail("supervisor must not read arbitrary parent environment")

        def __iter__(self):
            pytest.fail("supervisor must not enumerate arbitrary parent environment")

    class OperatingSystem:
        environ = ForbiddenEnvironment()

        def __getattr__(self, key):
            return getattr(os, key)

    monkeypatch.setenv("STORAGE_FIXTURE_PARENT_ONLY", "synthetic-private-value")
    monkeypatch.setattr(storage, "os", OperatingSystem())
    run = storage.supervise_storage_job(
        guard,
        _child(
            "import os, sys; assert 'STORAGE_FIXTURE_PARENT_ONLY' not in os.environ; "
            "assert os.environ['TMPDIR'] == sys.argv[1]; "
            "assert os.environ['QUANTOS_STORAGE_POLICY_SHA256'] == sys.argv[2]",
            str(guard.policy.scratch_root),
            guard.policy_hash,
        ),
        stage="local-validation",
        expected_new_bytes=0,
    )
    record = json.loads((run / "exit.json").read_bytes())
    assert record["execution"] == "SUCCEEDED"
    _assert_reaped(record)


def test_prelaunch_capacity_failure_is_retained_without_starting_child(guard, monkeypatch):
    capacity = storage._capacity
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (storage.GIB - 1, 4 * storage.GIB, 4096)
            if path == guard.policy.host_volume
            else capacity(path)
        ),
    )
    marker = guard.policy.scratch_root / "must-not-start"
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_HOST_HEADROOM$"):
        storage.supervise_storage_job(
            guard,
            _child(
                "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()",
                str(marker),
            ),
            stage="local-validation",
            expected_new_bytes=0,
        )
    record = _records(guard)[0][1]
    assert not marker.exists() and record["pid"] is None and record["return_code"] is None
    assert record["waitpid_observed"] is False
    assert record["execution"] == "FAILED" and record["validation"] == "NOT_EVALUATED"


def test_interrupted_popen_keeps_cleanup_unknown_and_blocks_the_next_job(guard, monkeypatch):
    launches = 0

    def interrupted_launch(*args, **kwargs):
        nonlocal launches
        launches += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(storage.subprocess, "Popen", interrupted_launch)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child("pass"),
            stage="local-validation",
            expected_new_bytes=0,
        )
    run, record = _records(guard)[0]
    retained = (run / "exit.json").read_bytes()
    assert launches == 1 and record["launch_attempted"] is True
    assert record["pid"] is None and record["return_code"] is None
    assert record["waitpid_observed"] is False and record["cleanup_verified"] is False
    assert record["namespace_exit_observed"] is None
    assert record["failure"] == "STORAGE_SUPERVISOR_ERROR"
    assert record["execution"] == "FAILED" and record["validation"] == "NOT_EVALUATED"
    assert record["qualification_eligibility"] == "NOT_QUALIFIED"
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_PREVIOUS_JOB_UNREAPED$"):
        storage.supervise_storage_job(
            guard,
            _child("pass"),
            stage="local-validation",
            expected_new_bytes=0,
        )
    assert launches == 1 and len(_records(guard)) == 1
    assert (run / "exit.json").read_bytes() == retained


@pytest.mark.parametrize("prior_record", [{}, {"pid": None}], ids=["empty", "missing-cleanup"])
def test_previous_exit_without_explicit_cleanup_blocks_any_new_launch(
    guard, monkeypatch, prior_record
):
    control = guard.policy.evidence_root / "storage-control"
    previous = control / "previous-run"
    previous.mkdir(parents=True)
    (previous / "exit.json").write_text(json.dumps(prior_record))
    (control / "lease.lock").write_text(
        json.dumps(
            {
                "run": str(previous),
                "policy_hash": guard.policy_hash,
            }
        )
    )
    retained = (previous / "exit.json").read_bytes()
    owner = (control / "lease.lock").read_bytes()

    def must_not_launch(*args, **kwargs):
        pytest.fail("missing cleanup evidence cannot authorize a new child")

    monkeypatch.setattr(storage.subprocess, "Popen", must_not_launch)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_PREVIOUS_JOB_UNREAPED$"):
        storage.supervise_storage_job(
            guard,
            _child("pass"),
            stage="local-validation",
            expected_new_bytes=0,
        )
    assert (previous / "exit.json").read_bytes() == retained
    assert (control / "lease.lock").read_bytes() == owner
    assert set(control.iterdir()) == {previous, control / "lease.lock"}


def test_explicit_preflight_refusal_allows_a_new_job_after_capacity_recovers(guard, monkeypatch):
    capacity = storage._capacity
    monkeypatch.setattr(
        storage,
        "_capacity",
        lambda path: (
            (storage.GIB - 1, 4 * storage.GIB, 4096)
            if path == guard.policy.host_volume
            else capacity(path)
        ),
    )
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_HOST_HEADROOM$"):
        storage.supervise_storage_job(
            guard,
            _child("pass"),
            stage="local-validation",
            expected_new_bytes=0,
        )
    rejected_run, rejected = _records(guard)[0]
    retained = (rejected_run / "exit.json").read_bytes()
    assert rejected["pid"] is None and rejected["return_code"] is None
    assert rejected["launch_attempted"] is False and rejected["cleanup_verified"] is True
    assert rejected["waitpid_observed"] is False
    assert rejected["execution"] == "FAILED" and rejected["validation"] == "NOT_EVALUATED"
    monkeypatch.setattr(storage, "_capacity", capacity)
    succeeding_run = storage.supervise_storage_job(
        guard,
        _child("pass"),
        stage="local-validation",
        expected_new_bytes=0,
    )
    success = json.loads((succeeding_run / "exit.json").read_bytes())
    assert succeeding_run != rejected_run and len(_records(guard)) == 2
    assert success["execution"] == "SUCCEEDED" and success["cleanup_verified"] is True
    assert (rejected_run / "exit.json").read_bytes() == retained
    _assert_reaped(success)


def test_ci_capacity_callback_kills_and_reaps_a_real_short_child(tmp_path):
    from quantos.infrastructure.hosted_regression_capture import _check

    samples = 0

    def capacity():
        nonlocal samples
        samples += 1
        if samples > 1:
            raise storage.StorageRejected("STORAGE_HOST_HEADROOM")

    started = time.monotonic()
    pid, code, output, failure = _check(
        _child("import time; print('original-output', flush=True); time.sleep(5)"),
        workspace=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
        timeout=2,
        storage_check=capacity,
    )
    assert samples == 2 and failure == "CHECK_STORAGE_CAPACITY"
    assert code == -signal.SIGKILL and output == b"original-output\n"
    assert time.monotonic() - started < 2
    _assert_reaped({"pid": pid, "waitpid_observed": True})


def test_final_child_write_between_sampling_and_poll_cannot_be_reported_as_success(
    guard,
    monkeypatch,
):
    release = guard.policy.scratch_root / "release"
    final_write = guard.policy.scratch_root / "final-write"
    capacity = storage._capacity
    samples = 0

    def observe(path):
        nonlocal samples
        if path == guard.policy.evidence_root:
            samples += 1
            growth = 1025 if final_write.exists() else 0
            return 3 * storage.GIB - growth, 4 * storage.GIB, 4096
        return capacity(path)

    real_popen = storage.subprocess.Popen

    def child_finishes_inside_poll(*args, **kwargs):
        process = real_popen(*args, **kwargs)

        def poll_after_final_write():
            release.touch()
            return process.wait(timeout=2)

        process.poll = poll_after_final_write
        return process

    monkeypatch.setattr(storage, "_capacity", observe)
    monkeypatch.setattr(storage.subprocess, "Popen", child_finishes_inside_poll)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child(
                "import pathlib, sys, time; release=pathlib.Path(sys.argv[1]); "
                "exec('while not release.exists(): time.sleep(.005)'); "
                "pathlib.Path(sys.argv[2]).write_bytes(b'x')",
                str(release),
                str(final_write),
            ),
            stage="local-validation",
            expected_new_bytes=1024,
        )
    record = _records(guard)[0][1]
    assert samples == 3 and final_write.read_bytes() == b"x" and record["return_code"] == 0
    assert record["failure"] == "STORAGE_ESTIMATE_EXCEEDED" and record["execution"] == "FAILED"
    assert record["cleanup_verified"] is True
    _assert_reaped(record)


def test_failure_only_in_final_capacity_check_cannot_become_success(guard, monkeypatch):
    capacity = storage._capacity
    samples = 0

    def observe(path):
        nonlocal samples
        if path == guard.policy.host_volume:
            samples += 1
            return (storage.GIB - 1 if samples >= 3 else 3 * storage.GIB), 4 * storage.GIB, 4096
        return capacity(path)

    real_popen = storage.subprocess.Popen

    def already_finished(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        process.wait(timeout=2)
        return process

    monkeypatch.setattr(storage, "_capacity", observe)
    monkeypatch.setattr(storage.subprocess, "Popen", already_finished)
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_JOB_FAILED$"):
        storage.supervise_storage_job(
            guard,
            _child("pass"),
            stage="local-validation",
            expected_new_bytes=0,
        )
    record = _records(guard)[0][1]
    assert samples == 3 and record["return_code"] == 0
    assert record["failure"] == "STORAGE_HOST_HEADROOM" and record["execution"] == "FAILED"
    assert record["validation"] == "NOT_EVALUATED"
    _assert_reaped(record)


def test_stale_run_cannot_borrow_a_different_active_lease(guard, monkeypatch):
    control = guard.policy.evidence_root / "storage-control"
    control.mkdir()
    stale, active = control / "stale-run", control / "active-run"
    stale.mkdir()
    active.mkdir()
    (stale / "prelaunch.json").write_text(json.dumps({"policy_hash": guard.policy_hash}))
    lock = os.open(control / "lease.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.write(lock, json.dumps({"run": str(active), "policy_hash": guard.policy_hash}).encode())
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setenv(storage.LEASE_ENV, str(stale))
        with pytest.raises(storage.StorageRejected, match=r"^STORAGE_SUPERVISOR_UNBOUND$"):
            guard.require_lease()
    finally:
        os.close(lock)


@pytest.mark.parametrize("unfinished", ["absent-exit", "unverified-cleanup"])
def test_unreconciled_previous_job_blocks_any_new_child(guard, unfinished):
    control = guard.policy.evidence_root / "storage-control"
    previous = control / "previous-run"
    previous.mkdir(parents=True)
    owner = {"run": str(previous), "policy_hash": guard.policy_hash}
    (control / "lease.lock").write_text(json.dumps(owner))
    if unfinished == "unverified-cleanup":
        (previous / "exit.json").write_text(
            json.dumps({"pid": os.getpid(), "cleanup_verified": False})
        )
    marker = guard.policy.scratch_root / "never-started"
    expected = (
        "STORAGE_PREVIOUS_JOB_UNRECONCILED"
        if unfinished == "absent-exit"
        else "STORAGE_PREVIOUS_JOB_UNREAPED"
    )
    before = (control / "lease.lock").read_bytes()
    with pytest.raises(storage.StorageRejected, match=rf"^{expected}$"):
        storage.supervise_storage_job(
            guard,
            _child("import pathlib,sys; pathlib.Path(sys.argv[1]).touch()", str(marker)),
            stage="local-validation",
            expected_new_bytes=0,
        )
    assert not marker.exists() and not _records(guard)
    assert (control / "lease.lock").read_bytes() == before
    assert set(control.iterdir()) == {previous, control / "lease.lock"}


def test_unsupported_bwrap_rejects_formal_job_before_worker_launch(guard, monkeypatch):
    monkeypatch.setattr(storage, "_bwrap_size_support", lambda _: False)
    marker = guard.policy.scratch_root / "never-started"
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_BWRAP_HARD_QUOTA_UNAVAILABLE$"):
        storage.supervise_storage_job(
            guard,
            _child("import pathlib,sys; pathlib.Path(sys.argv[1]).touch()", str(marker)),
            stage="deployment",
            expected_new_bytes=0,
        )
    record = _records(guard)[0][1]
    assert not marker.exists() and record["pid"] is None and record["return_code"] is None
    assert record["failure"] == "STORAGE_BWRAP_HARD_QUOTA_UNAVAILABLE"
    assert record["execution"] == "FAILED" and record["validation"] == "NOT_EVALUATED"


@pytest.mark.parametrize("entry", ["deployment", "matrix", "ci", "export", "replay"])
def test_management_entry_points_reject_missing_policy_before_writes(tmp_path, monkeypatch, entry):
    from quantos.infrastructure import (
        hosted_budget_deployment,
        hosted_manager,
        hosted_regression_capture,
    )

    monkeypatch.delenv(storage.POLICY_ENV, raising=False)
    monkeypatch.delenv(storage.HASH_ENV, raising=False)
    output = tmp_path / "output"
    from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES

    deployment = SimpleNamespace(
        root=tmp_path,
        profile=SimpleNamespace(mount_policy_hash=storage.sha256_bytes(MOUNT_POLICY_BYTES)),
    )
    with pytest.raises(storage.StorageRejected, match=r"^STORAGE_POLICY_UNAVAILABLE$"):
        if entry == "deployment":
            hosted_manager.stage_hosted_deployment(
                output,
                tmp_path,
                None,
                {},
                tmp_path,
                wheel=tmp_path,
                base_python=tmp_path,
                dependency_site=tmp_path,
                codex_binary=tmp_path,
                launcher_configuration=None,
            )
        elif entry == "matrix":
            hosted_budget_deployment.stage_managed_budget_deployment(
                deployment,
                "request_submissions",
                tmp_path,
                base_python=tmp_path,
                dependency_site=tmp_path,
            )
        elif entry == "ci":
            hosted_regression_capture.run_managed_regression(deployment, tmp_path)
        elif entry == "export":
            hosted_manager.export_live_source(deployment, output)
        elif entry == "replay":
            hosted_manager.run_managed_offline(
                deployment,
                tmp_path,
                "a" * 64,
                mode="research",
                target=output,
            )
    assert not tuple(tmp_path.iterdir())
