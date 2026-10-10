#!/usr/bin/env python3
"""Bounded real supervisor crash probe, isolated from every existing job lease.

The sole injected fault delays the real namespace pin callback before G release.
No capacity, process, wait result, namespace identity or original exit is replaced.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_storage as storage
from quantos.infrastructure.hosted_regression_runtime import native_pidfd_kill, native_pidfd_open

CHILD_ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
ESTIMATE = 4 << 20


def _write(path: Path, encoded: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise storage.StorageRejected("CRASH_PROBE_RECORD_ALREADY_EXISTS")
    atomic_write_bytes(path, encoded)


def _save(path: Path, value: dict[str, Any]) -> None:
    _write(path, canonical_json_bytes(value))


def _read(path: Path) -> dict[str, Any]:
    encoded = path.read_bytes()
    if len(encoded) > 16384:
        raise storage.StorageRejected("CRASH_PROBE_RECORD_TOO_LARGE")
    return json.loads(encoded)


def _guard(args: argparse.Namespace) -> storage.StorageGuard:
    if args.policy is None or args.policy_sha256 is None:
        raise storage.StorageRejected("CRASH_PROBE_EXPLICIT_POLICY_REQUIRED")
    os.environ[storage.POLICY_ENV] = str(args.policy.absolute())
    os.environ[storage.HASH_ENV] = args.policy_sha256
    return storage.configured_guard()


def _payload_argv(marker: Path) -> tuple[str, ...]:
    return (sys.executable, "-B", str(Path(__file__).resolve()), "--payload-marker", str(marker))


def _payload(marker: Path) -> int:
    if not marker.is_absolute() or marker.name != "payload-marker.bin":
        raise storage.StorageRejected("CRASH_PROBE_MARKER_INVALID")
    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        encoded = bytes(1024)
        while encoded:
            encoded = encoded[os.write(descriptor, encoded) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    time.sleep(0.2)
    return 0


def _supervisor(args: argparse.Namespace) -> int:
    guard = _guard(args)
    scope = guard.policy.evidence_root
    pin_hook = "_namespace_pidfd"
    original_pin = cast(Callable[[int, int], int | None], getattr(storage, pin_hook))

    def delayed_pin(wrapper: int, info_fd: int) -> int | None:
        descriptor = original_pin(wrapper, info_fd)
        if descriptor is None:
            return None
        try:
            info: dict[str, Any] = json.loads(os.pread(info_fd, 4096, 0))
            _save(
                scope / "before-g.json",
                {
                    "schema_version": "hosted-storage-before-g/v1",
                    "supervisor_pid": os.getpid(),
                    "wrapper_pid": wrapper,
                    "namespace_init_pid": info["child-pid"],
                    "pid_namespace": info["pid-namespace"],
                    "policy_hash": guard.policy_hash,
                    "real_namespace_pidfd_opened": True,
                    "fault": "DELAY_BEFORE_G_RELEASE",
                    "validation": "NOT_EVALUATED",
                    "qualification_eligibility": "NOT_QUALIFIED",
                },
            )
            # A failed controller cannot eventually authorize the payload.
            time.sleep(10)
            raise storage.StorageRejected("CRASH_PROBE_DELAY_EXPIRED")
        finally:
            os.close(descriptor)

    setattr(storage, pin_hook, delayed_pin)
    storage.supervise_storage_job(
        guard,
        _payload_argv(scope / "payload-marker.bin"),
        stage="deployment",
        expected_new_bytes=ESTIMATE,
    )
    return 0


def _identity_pidfd(pid: int, parent: int, namespace: str | None = None) -> int:
    descriptor = native_pidfd_open(pid)
    try:
        rows = dict(
            line.split(":", 1)
            for line in Path(f"/proc/{pid}/status").read_text().splitlines()
            if ":" in line
        )
        if int(rows["PPid"].strip()) != parent:
            raise storage.StorageRejected("CRASH_PROBE_PARENT_UNBOUND")
        if namespace is not None and (
            os.readlink(f"/proc/{pid}/ns/pid") != namespace
            or namespace == os.readlink("/proc/self/ns/pid")
        ):
            raise storage.StorageRejected("CRASH_PROBE_NAMESPACE_UNBOUND")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _exited(descriptor: int, deadline: float, maximum_wait: float) -> bool:
    return bool(
        select.select([descriptor], [], [], max(0, min(maximum_wait, deadline - time.monotonic())))[
            0
        ]
    )


def _controller(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + 20
    base = _guard(args)
    base.check(ESTIMATE)
    storage.require_bounded_bwrap()
    root = base.policy.evidence_root / f"crash-probe-{time.time_ns()}-{os.getpid()}"
    base.require_root(root)
    root.mkdir(mode=0o700)
    scope = root / "independent-scope"
    scope.mkdir(mode=0o700)
    policy = replace(
        base.policy, evidence_root=scope, poll_seconds=0.1, terminate_grace_seconds=0.2
    )
    guard = storage.StorageGuard(policy)
    policy_path = root / "crash-policy.json"
    _write(policy_path, policy.canonical_bytes())
    _save(
        root / "preflight.json",
        {
            "schema_version": "hosted-storage-crash-probe/v1",
            "requested_policy_hash": base.policy_hash,
            "scope_policy_hash": guard.policy_hash,
            "scope": str(scope),
            "maximum_seconds": 20,
            "payload_maximum_bytes": 1024,
            "validation": "NOT_EVALUATED",
            "qualification_eligibility": "NOT_QUALIFIED",
        },
    )
    process = subprocess.Popen(
        (
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--supervisor",
            "--policy",
            str(policy_path),
            "--policy-sha256",
            guard.policy_hash,
        ),
        env=CHILD_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    supervisor_fd = native_pidfd_open(process.pid)
    wrapper_fd: int | None = None
    namespace_fd: int | None = None
    waited_code: int | None = None
    namespace_exited = False
    wrapper_exited = False
    cleanup_signal_needed = False
    failure: str | None = None
    blocked_retry: str | None = None
    original_run: Path | None = None
    before_g_seen = False
    marker = scope / "payload-marker.bin"
    try:
        ready = scope / "before-g.json"
        ready_deadline = min(deadline, time.monotonic() + 6)
        while not ready.exists() and process.poll() is None and time.monotonic() < ready_deadline:
            time.sleep(0.01)
        if not ready.exists():
            raise storage.StorageRejected("CRASH_PROBE_BEFORE_G_NOT_OBSERVED")
        fact = _read(ready)
        if fact["supervisor_pid"] != process.pid or fact["policy_hash"] != guard.policy_hash:
            raise storage.StorageRejected("CRASH_PROBE_SUPERVISOR_UNBOUND")
        wrapper_fd = _identity_pidfd(int(fact["wrapper_pid"]), process.pid)
        namespace_fd = _identity_pidfd(
            int(fact["namespace_init_pid"]),
            int(fact["wrapper_pid"]),
            f"pid:[{fact['pid_namespace']}]",
        )
        before_g_seen = True
        if marker.exists():
            raise storage.StorageRejected("CRASH_PROBE_PAYLOAD_STARTED_BEFORE_G")
        owner_path = scope / "storage-control/lease.lock"
        original_owner = owner_path.read_bytes()
        original_run = Path(json.loads(original_owner)["run"])
        if original_run.parent != scope / "storage-control":
            raise storage.StorageRejected("CRASH_PROBE_RUN_UNBOUND")
        native_pidfd_kill(supervisor_fd)
        waited_code = process.wait(timeout=min(3, max(0.001, deadline - time.monotonic())))
        namespace_exited = _exited(namespace_fd, deadline, 3)
        if not namespace_exited:
            cleanup_signal_needed = True
            native_pidfd_kill(namespace_fd)
            _exited(namespace_fd, deadline, 2)
        wrapper_exited = _exited(wrapper_fd, deadline, 3)
        before_retry = set((scope / "storage-control").glob("run-*"))
        try:
            storage.supervise_storage_job(
                guard, _payload_argv(marker), stage="deployment", expected_new_bytes=ESTIMATE
            )
        except storage.StorageRejected as error:
            blocked_retry = str(error)
        unchanged = (
            owner_path.read_bytes() == original_owner
            and set((scope / "storage-control").glob("run-*")) == before_retry
        )
        if not unchanged:
            failure = "CRASH_PROBE_RETRY_MUTATED_UNRESOLVED_LEASE"
    except storage.StorageRejected as error:
        failure = str(error)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        failure = "CRASH_PROBE_OBSERVATION_UNAVAILABLE"
    finally:
        if process.poll() is None:
            native_pidfd_kill(supervisor_fd)
        if waited_code is None:
            try:
                waited_code = process.wait(timeout=min(3, max(0.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                failure = failure or "CRASH_PROBE_SUPERVISOR_WAIT_UNOBSERVED"
        if namespace_fd is not None and not _exited(namespace_fd, deadline, 0):
            cleanup_signal_needed = True
            native_pidfd_kill(namespace_fd)
            _exited(namespace_fd, deadline, 1)
        for descriptor in (namespace_fd, wrapper_fd, supervisor_fd):
            if descriptor is not None:
                os.close(descriptor)
    original_exit_present = original_run is not None and (original_run / "exit.json").exists()
    verified = (
        before_g_seen
        and waited_code == -signal.SIGKILL
        and namespace_exited
        and wrapper_exited
        and not cleanup_signal_needed
        and not marker.exists()
        and not original_exit_present
        and blocked_retry == "STORAGE_PREVIOUS_JOB_UNRECONCILED"
        and failure is None
    )
    _save(
        root / "crash-result.json",
        {
            "schema_version": "hosted-storage-crash-result/v1",
            "scope_policy_hash": guard.policy_hash,
            "verified": verified,
            "failure": failure,
            "before_g_observed": before_g_seen,
            "supervisor_pid": process.pid,
            "supervisor_actual_wait_return_code": waited_code,
            "supervisor_wait_observed": waited_code is not None,
            "wrapper_exit_observed": wrapper_exited,
            "namespace_exit_observed_before_controller_cleanup": namespace_exited,
            "controller_namespace_cleanup_signal_needed": cleanup_signal_needed,
            "payload_marker_exists": marker.exists(),
            "original_exit_present": original_exit_present,
            "original_supervisor_run": str(original_run) if original_run is not None else None,
            "same_scope_retry_rejection": blocked_retry,
            "validation": "NOT_EVALUATED",
            "qualification_eligibility": "NOT_QUALIFIED",
        },
    )
    print("CRASH_PROBE_VERIFIED" if verified else "CRASH_PROBE_INCOMPLETE")
    print(str(root))
    return 0 if verified else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha256")
    parser.add_argument("--supervisor", action="store_true")
    parser.add_argument("--payload-marker", type=Path)
    args = parser.parse_args()
    try:
        if args.payload_marker is not None:
            return _payload(args.payload_marker)
        return _supervisor(args) if args.supervisor else _controller(args)
    except storage.StorageRejected as error:
        print(str(error))
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("CRASH_PROBE_OBSERVATION_UNAVAILABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
