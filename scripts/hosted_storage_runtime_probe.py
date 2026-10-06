#!/usr/bin/env python3
"""Bounded real management probes; never research or qualification evidence.

Run only with an explicitly bound policy and a dedicated <=64 MiB scratch mount.
Successful and failed supervisor records remain in that policy's evidence root.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure.hosted_regression_runtime import native_pidfd_kill, native_pidfd_open
from quantos.infrastructure.hosted_storage import (
    HASH_ENV,
    POLICY_ENV,
    StorageGuard,
    StorageRejected,
    configured_guard,
    require_bounded_bwrap,
    storage_mount_identity,
    supervise_storage_job,
)

MIB = 1 << 20
MAX_SCRATCH = 64 * MIB
PRIVATE_TMP = 8 * MIB
JOB_ESTIMATE = 4 * MIB
CHILD_ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def _save(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise StorageRejected("RUNTIME_PROBE_RECORD_ALREADY_EXISTS")
    atomic_write_bytes(path, canonical_json_bytes(value))


def _read(path: Path) -> dict[str, Any]:
    encoded = path.read_bytes()
    if len(encoded) > 32768:
        raise StorageRejected("RUNTIME_PROBE_RECORD_TOO_LARGE")
    return json.loads(encoded)


def _capacity(path: Path) -> dict[str, int]:
    value = os.statvfs(path)
    return {
        "available_bytes": value.f_bavail * value.f_frsize,
        "total_bytes": value.f_blocks * value.f_frsize,
    }


def _argv(kind: str, case: Path, *extra: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--child",
        kind,
        "--case",
        str(case),
        *extra,
    )


def _fill_tmpfs(directory: Path, limit: int, facts: Path) -> None:
    before = _capacity(directory)
    filesystem, mount = storage_mount_identity(directory)
    if filesystem != "tmpfs" or mount != directory or before["total_bytes"] > limit:
        raise StorageRejected("RUNTIME_PROBE_TMPFS_CAP_UNBOUND")
    toy = directory / f"runtime-enospc-{os.getpid()}-{time.time_ns()}"
    toy.mkdir(mode=0o700)
    filename = toy / "owned-fill-only"
    descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    written = 0
    error_number = None
    try:
        chunk = bytes(MIB)
        while written <= limit:
            try:
                written += os.write(descriptor, chunk)
            except OSError as error:
                error_number = error.errno
                break
        at_limit = _capacity(directory)
    finally:
        os.close(descriptor)
        # Only these two newly created entries are ever removed.
        filename.unlink()
        toy.rmdir()
    if error_number != errno.ENOSPC or written > limit:
        raise StorageRejected("RUNTIME_PROBE_ENOSPC_NOT_OBSERVED")
    _save(
        facts,
        {
            "schema_version": "hosted-runtime-enospc/v1",
            "errno": error_number,
            "written_bytes": written,
            "before": before,
            "at_limit": at_limit,
            "after_cleanup": _capacity(directory),
            "owned_toy_removed": True,
            "validation": "NOT_EVALUATED",
            "qualification_eligibility": "NOT_QUALIFIED",
        },
    )


def _child(args: argparse.Namespace) -> int:
    case: Path | None = args.case
    if case is None or not case.is_absolute():
        raise StorageRejected("RUNTIME_PROBE_CASE_REQUIRED")
    if args.child == "leaf":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _save(
            case / "leaf-ready.json",
            {"pid_in_namespace": os.getpid(), "namespace": os.readlink("/proc/self/ns/pid")},
        )
        # A bounded self deadline provides cleanup even if the controller crashes.
        time.sleep(20)
        return 0
    if args.child == "chain":
        subprocess.Popen(
            _argv("leaf", case),
            env=CHILD_ENV,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return 0
    if args.child == "private-fill":
        _fill_tmpfs(Path("/tmp"), PRIVATE_TMP, case / "private-tmp.json")
        return 0
    guard = configured_guard()
    guard.require_root(case)
    guard.require_lease()
    guard.check()
    # Allow the real outer namespace init to be pinned before short child exits.
    time.sleep(guard.policy.poll_seconds + 0.2)
    if args.child == "scratch":
        _fill_tmpfs(guard.policy.scratch_root, MAX_SCRATCH, case / "scratch.json")
    elif args.child == "bwrap":
        result = subprocess.run(
            (
                "/usr/bin/bwrap",
                "--unshare-pid",
                "--die-with-parent",
                "--new-session",
                "--bind",
                "/",
                "/",
                "--dev-bind",
                "/dev",
                "/dev",
                "--proc",
                "/proc",
                "--size",
                str(PRIVATE_TMP),
                "--tmpfs",
                "/tmp",
                *_argv("private-fill", case),
            ),
            env=CHILD_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            raise StorageRejected("RUNTIME_PROBE_PRIVATE_TMP_FAILED")
    elif args.child == "descendant":
        subprocess.run(
            _argv("chain", case),
            env=CHILD_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=True,
        )
        deadline = time.monotonic() + 8
        while not (case / "release-driver").exists():
            if time.monotonic() > deadline:
                raise StorageRejected("RUNTIME_PROBE_RELEASE_TIMEOUT")
            time.sleep(0.01)
    elif args.child == "growth":
        toy = case / "retained-growth-toy.bin"
        descriptor = os.open(toy, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            remaining = memoryview(bytes(6 * MIB))
            while remaining:
                remaining = remaining[os.write(descriptor, remaining) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _save(
            case / "growth-written.json",
            {
                "written_bytes": toy.stat().st_size,
                "linux_after_fsync": _capacity(guard.policy.evidence_root),
            },
        )
        time.sleep(10)
    elif args.child in {"linux-threshold", "host-threshold"}:
        linux = args.child == "linux-threshold"
        path = guard.policy.evidence_root if linux else guard.policy.host_volume
        observed = _capacity(path)
        field = "linux_reserve_bytes" if linux else "host_reserve_bytes"
        policy = replace(guard.policy, **{field: observed["available_bytes"] + 4 * MIB})
        encoded = policy.canonical_bytes()
        atomic_write_bytes(case / "threshold-policy.json", encoded)
        expected = "STORAGE_LINUX_HEADROOM" if linux else "STORAGE_HOST_HEADROOM"
        try:
            StorageGuard(policy).check()
        except StorageRejected as error:
            if str(error) != expected:
                raise
            _save(
                case / "threshold.json",
                {
                    "schema_version": "hosted-runtime-threshold/v1",
                    "policy_hash": sha256_bytes(encoded),
                    "observed_before": observed,
                    "observed_after": _capacity(path),
                    "failure": expected,
                    "scope": "REAL_GUARD_CHECK_INSIDE_FORMAL_SUPERVISED_CHILD",
                    "disk_fill_bytes": 0,
                    "capacity_mocked": False,
                    "execution": "FAILED",
                    "validation": "NOT_EVALUATED",
                    "qualification_eligibility": "NOT_QUALIFIED",
                },
            )
            return 83
        raise StorageRejected("RUNTIME_PROBE_THRESHOLD_NOT_OBSERVED")
    else:
        raise StorageRejected("RUNTIME_PROBE_CHILD_INVALID")
    return 0


def _invoke(guard: StorageGuard, kind: str, case: Path) -> dict[str, Any]:
    control = guard.policy.evidence_root / "storage-control"
    before = set(control.glob("run-*"))
    started = time.monotonic()
    error = None
    try:
        supervise_storage_job(
            guard, _argv(kind, case), stage="deployment", expected_new_bytes=JOB_ESTIMATE
        )
    except StorageRejected as failure:
        error = str(failure)
    created = set(control.glob("run-*")) - before
    if len(created) != 1:
        return {"case": kind, "verified": False, "failure": "RUNTIME_PROBE_RUN_UNBOUND"}
    run = created.pop()
    record = _read(run / "exit.json")
    return {
        "case": kind,
        "supervisor_run": str(run),
        "supervisor_exit": record,
        "supervisor_error": error,
        "elapsed_seconds": time.monotonic() - started,
    }


def _formal_cleanup(result: dict[str, Any]) -> bool:
    record: dict[str, Any] = result.get("supervisor_exit", {})
    return (
        record.get("process_scope") == "PID_NAMESPACE_WRAPPER"
        and record.get("waitpid_observed") is True
        and record.get("namespace_exit_observed") is True
        and record.get("cleanup_verified") is True
    )


def _leaf_pidfd(fact: dict[str, Any]) -> int | None:
    # Read only PID/namespace identities. Never read cmdline, environ or credentials.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if os.readlink(entry / "ns/pid") != fact["namespace"]:
                continue
            row = next(
                line
                for line in (entry / "status").read_text().splitlines()
                if line.startswith("NSpid:")
            )
            if int(row.split()[-1]) != fact["pid_in_namespace"]:
                continue
            descriptor = native_pidfd_open(int(entry.name))
            if os.readlink(entry / "ns/pid") == fact["namespace"]:
                return descriptor
            os.close(descriptor)
        except (OSError, StopIteration, ValueError):
            continue
    return None


def _descendant(guard: StorageGuard, case: Path) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    worker = threading.Thread(target=lambda: outcomes.append(_invoke(guard, "descendant", case)))
    worker.start()
    descriptor = None
    exited = False
    try:
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and worker.is_alive():
            ready = case / "leaf-ready.json"
            if ready.exists():
                descriptor = _leaf_pidfd(_read(ready))
                if descriptor is not None:
                    break
            time.sleep(0.01)
        (case / "release-driver").touch(exist_ok=False)
        if descriptor is not None:
            exited = bool(select.select([descriptor], [], [], 3)[0])
            if not exited:
                native_pidfd_kill(descriptor)
                select.select([descriptor], [], [], 2)
    finally:
        if not (case / "release-driver").exists():
            (case / "release-driver").touch(exist_ok=False)
        worker.join(timeout=15)
        if descriptor is not None:
            os.close(descriptor)
    if worker.is_alive() or not outcomes:
        raise StorageRejected("RUNTIME_PROBE_SUPERVISOR_STILL_RUNNING")
    result = outcomes[0]
    result.update(
        {
            "detached_grandchild_pidfd_observed": descriptor is not None,
            "grandchild_exit_before_controller_cleanup": exited,
            "verified": exited
            and _formal_cleanup(result)
            and result.get("supervisor_exit", {}).get("execution") == "SUCCEEDED",
        }
    )
    return result


def _controller(args: argparse.Namespace) -> int:
    os.environ[POLICY_ENV] = str(args.policy.absolute())
    os.environ[HASH_ENV] = args.policy_sha256
    base = configured_guard()
    base.check(JOB_ESTIMATE)
    require_bounded_bwrap()
    if _capacity(base.policy.scratch_root)["total_bytes"] > MAX_SCRATCH:
        raise StorageRejected("RUNTIME_PROBE_SCRATCH_EXCEEDS_64_MIB")
    root = base.policy.evidence_root / f"runtime-probe-{time.time_ns()}-{os.getpid()}"
    base.require_root(root)
    root.mkdir(mode=0o700)
    # Every derived management policy is frozen/hash-bound in the supervisor record.
    guard = StorageGuard(replace(base.policy, poll_seconds=1.0, terminate_grace_seconds=1.0))
    _save(
        root / "preflight.json",
        {
            "schema_version": "hosted-storage-runtime-probe/v1",
            "requested_policy_hash": base.policy_hash,
            "probe_job_policy_hash": guard.policy_hash,
            "scratch_capacity": _capacity(base.policy.scratch_root),
            "scratch_mount_verified": True,
            "maximum_scratch_fill_bytes": MAX_SCRATCH,
            "maximum_private_tmp_fill_bytes": PRIVATE_TMP,
            "maximum_retained_growth_bytes": 6 * MIB,
            "capacity_mocked": False,
            "validation": "NOT_EVALUATED",
            "qualification_eligibility": "NOT_QUALIFIED",
        },
    )
    results: list[dict[str, Any]] = []
    for kind in ("scratch", "bwrap", "descendant", "growth", "linux-threshold", "host-threshold"):
        case = root / kind
        case.mkdir(mode=0o700)
        if kind == "descendant":
            result = _descendant(guard, case)
        else:
            job_guard = (
                StorageGuard(replace(guard.policy, poll_seconds=0.1)) if kind == "growth" else guard
            )
            result = _invoke(job_guard, kind, case)
            record: dict[str, Any] = result.get("supervisor_exit", {})
            verified = _formal_cleanup(result)
            if kind in {"scratch", "bwrap"}:
                facts = case / ("scratch.json" if kind == "scratch" else "private-tmp.json")
                verified = (
                    verified
                    and record.get("execution") == "SUCCEEDED"
                    and facts.exists()
                    and _read(facts).get("errno") == errno.ENOSPC
                )
            elif kind == "growth":
                toy = case / "retained-growth-toy.bin"
                result["retained_toy_bytes"] = toy.stat().st_size if toy.exists() else 0
                verified = (
                    verified
                    and record.get("failure") == "STORAGE_ESTIMATE_EXCEEDED"
                    and record.get("execution") == "FAILED"
                    and record.get("return_code") != 0
                    and result["retained_toy_bytes"] >= JOB_ESTIMATE
                    and result["elapsed_seconds"] < 8
                )
            else:
                facts = case / "threshold.json"
                expected = (
                    "STORAGE_LINUX_HEADROOM"
                    if kind == "linux-threshold"
                    else "STORAGE_HOST_HEADROOM"
                )
                verified = (
                    verified
                    and record.get("execution") == "FAILED"
                    and record.get("return_code") == 83
                    and facts.exists()
                    and _read(facts).get("failure") == expected
                )
            result["verified"] = bool(verified)
        _save(case / "probe-result.json", result)
        results.append(result)
        # Unverified cleanup never permits a subsequent job or hides a failure.
        if not _formal_cleanup(result):
            break
    complete = len(results) == 6 and all(result["verified"] for result in results)
    _save(
        root / "summary.json",
        {
            "schema_version": "hosted-storage-runtime-probe-summary/v1",
            "requested_policy_hash": base.policy_hash,
            "results": results,
            "all_required_observations_retained": complete,
            "validation": "NOT_EVALUATED",
            "qualification_eligibility": "NOT_QUALIFIED",
        },
    )
    print("RUNTIME_PROBE_COMPLETE" if complete else "RUNTIME_PROBE_INCOMPLETE")
    print(str(root))
    return 0 if complete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha256")
    parser.add_argument(
        "--child",
        choices=(
            "scratch",
            "bwrap",
            "private-fill",
            "descendant",
            "chain",
            "leaf",
            "growth",
            "linux-threshold",
            "host-threshold",
        ),
    )
    parser.add_argument("--case", type=Path)
    args = parser.parse_args()
    try:
        if args.child:
            return _child(args)
        if args.policy is None or args.policy_sha256 is None:
            parser.error("explicit --policy and --policy-sha256 are required")
        return _controller(args)
    except StorageRejected as error:
        print(str(error))
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("RUNTIME_PROBE_OBSERVATION_UNAVAILABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
