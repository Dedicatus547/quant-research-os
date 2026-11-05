"""Finite acquisition jobs using the existing host-volume guard and global lease."""

from __future__ import annotations

import fcntl
import json
import os
import resource
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from quantos.artifacts.store import atomic_write_bytes, verify_file
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure.hosted_storage import StorageGuard, StoragePolicy


def retained_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def acquire_job(plan: dict[str, Any], plan_path: Path, previous: Path, day: str) -> None:
    root = Path(plan["root"])
    jobs = root / "acquisition-jobs"
    jobs.mkdir(exist_ok=True)
    prior_jobs = sorted(jobs.iterdir())
    used_wall = plan["initial_wall_charge_seconds"]
    for prior in prior_jobs:
        result = json.loads((prior / "exit.json").read_bytes())
        if (
            not result["cleanup_verified"]
            or result["actual_return_code"] != 0
            or result.get("failure") is not None
        ):
            raise PermissionError("failed/unknown acquisition requires explicit reconciliation")
        used_wall += result["wall_seconds"]
    if len(prior_jobs) >= 61 or used_wall >= plan["acquisition_wall_seconds"]:
        raise PermissionError("finite acquisition budget exhausted")
    # Reserve 500 attempts for each daily job, including a failed or killed one.
    # This conservative ceiling cannot refund partially observed network attempts.
    if plan["initial_attempt_charge"] + 500 * (len(prior_jobs) + 1) > 40000:
        raise PermissionError("campaign acquisition attempt ceiling exhausted")
    policy_path = Path(plan["storage_policy"]["path"])
    verify_file(policy_path, plan["storage_policy"]["sha256"])
    policy = json.loads(policy_path.read_bytes())
    for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
        policy[key] = Path(policy[key])
    guard = StorageGuard(StoragePolicy(**policy))
    capacity = guard.check(32 * 1024**3)
    control = guard.policy.evidence_root / "storage-control"
    descriptor = os.open(control / "lease.lock", os.O_RDWR | os.O_NOFOLLOW)
    process: subprocess.Popen[bytes] | None = None
    code: int | None = None
    failure: str | None = None
    started = time.monotonic()
    run: Path | None = None
    job: Path | None = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = json.loads(os.pread(descriptor, 16384, 0))
        if not json.loads((Path(old["run"]) / "exit.json").read_bytes())["cleanup_verified"]:
            raise PermissionError("preceding host lease cleanup is unverified")
        job = jobs / day
        job.mkdir(exist_ok=False)
        run = control / f"run-forward-acquisition-{time.time_ns()}"
        run.mkdir()
        os.ftruncate(descriptor, 0)
        os.write(
            descriptor, canonical_json_bytes({"run": str(run), "policy_hash": guard.policy_hash})
        )
        os.fsync(descriptor)
        limit = min(1800, plan["acquisition_wall_seconds"] - used_wall)
        argv = [
            plan["python"],
            "-B",
            "-m",
            "quantos.data.tushare.forward_daily",
            "--campaign",
            str(plan_path),
            "--previous",
            str(previous),
            "--day",
            day,
        ]
        prelaunch = {
            "argv": argv,
            "policy_hash": guard.policy_hash,
            "initial_capacity": capacity,
            "expected_new_bytes": 32 * 1024**3,
            "wall_limit_seconds": limit,
            "attempts_reserved": 500,
            "used_wall_seconds_with_initial_charge": used_wall,
            "scope": "ACQUISITION_PROCESS_GROUP_NOT_EXECUTION_QUALIFICATION",
        }
        atomic_write_bytes(run / "prelaunch.json", canonical_json_bytes(prelaunch))
        atomic_write_bytes(
            job / "prelaunch.json", canonical_json_bytes({**prelaunch, "control_run": str(run)})
        )
        env = dict(os.environ)
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            env[key] = "1"

        def limits() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
            os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])

        before = retained_size(root)
        with (job / "process.log").open("xb") as output:
            process = subprocess.Popen(
                argv,
                cwd=plan["repo_root"],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                preexec_fn=limits,
                start_new_session=True,
            )
            while process.poll() is None:
                guard.check(32 * 1024**3)
                size = retained_size(root)
                acquisition_size = size - sum(
                    retained_size(Path(arm["product_root"])) for arm in plan["arms"]
                )
                if size - before > 8 * 1024**3 or acquisition_size > 16 * 1024**3:
                    raise RuntimeError("acquisition retained growth ceiling")
                if time.monotonic() - started > limit:
                    raise TimeoutError("acquisition wall budget")
                time.sleep(2)
            code = process.wait()
    except BaseException as error:
        failure = type(error).__name__
    finally:
        cleanup = True
        if process is not None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
            try:
                os.killpg(process.pid, 0)
                cleanup = False
            except ProcessLookupError:
                pass
        result = {
            "actual_return_code": code,
            "wall_seconds": time.monotonic() - started,
            "failure": failure,
            "waitpid_observed": process is not None,
            "cleanup_verified": cleanup,
            "qualification_eligibility": "NOT_QUALIFIED",
        }
        if run is not None:
            atomic_write_bytes(run / "exit.json", canonical_json_bytes(result))
        if job is not None:
            atomic_write_bytes(job / "exit.json", canonical_json_bytes(result))
        os.close(descriptor)
    if code != 0 or failure is not None or not cleanup:
        raise RuntimeError("acquisition did not finish cleanly; inspect retained exit")
