"""Synthetic supervisor exits and reservations; no host qualification or network."""

import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import forward_acquisition_job as job


@pytest.fixture
def supervised(tmp_path, monkeypatch):
    control = tmp_path / "storage-control"
    control.mkdir()
    prior = control / "prior"
    prior.mkdir()
    (prior / "exit.json").write_bytes(canonical_json_bytes({"cleanup_verified": True}))
    lease = control / "lease.lock"
    lease.write_bytes(canonical_json_bytes({"run": str(prior)}))
    policy = tmp_path / "policy.json"
    policy.write_bytes(
        canonical_json_bytes(
            {
                key: str(tmp_path)
                for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file")
            }
        )
    )
    state = SimpleNamespace(
        ticks=0,
        code=0,
        spawned=[],
        killed=[],
        waits=0,
        capacity_checks=[],
        lingering=False,
        spawn_error=False,
        growth=False,
        timeout=False,
    )

    def clock():
        state.ticks += 1900 if state.timeout else 1
        return state.ticks

    class Guard:
        def __init__(self, value):
            self.policy, self.policy_hash = value, "a" * 64

        def check(self, amount):
            state.capacity_checks.append(amount)
            return {"synthetic_capacity": True}

    class Child:
        pid = 123456789

        def __init__(self, argv, **kwargs):
            if state.spawn_error:
                raise OSError("synthetic unavailable executable")
            self.polls = 0
            state.spawned.append((argv, kwargs))

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else state.code

        def wait(self):
            state.waits += 1
            return state.code

    def kill(pid, sig):
        assert pid == Child.pid
        state.killed.append(sig)
        if sig == 0 and not state.lingering:
            raise ProcessLookupError

    def size(path):
        if state.growth and state.spawned and path == tmp_path:
            return 9 * 1024**3
        return 0

    monkeypatch.setattr(job, "StoragePolicy", lambda **values: SimpleNamespace(**values))
    monkeypatch.setattr(job, "StorageGuard", Guard)
    monkeypatch.setattr(job.subprocess, "Popen", Child)
    monkeypatch.setattr(job.os, "killpg", kill)
    monkeypatch.setattr(job.time, "monotonic", clock)
    monkeypatch.setattr(job.time, "sleep", lambda _: None)
    monkeypatch.setattr(job, "retained_size", size)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    plan = {
        "root": str(tmp_path),
        "repo_root": str(tmp_path),
        "python": "/synthetic/python",
        "initial_wall_charge_seconds": 100,
        "acquisition_wall_seconds": 10000,
        "initial_attempt_charge": 10,
        "storage_policy": {"path": str(policy), "sha256": sha256_file(policy)},
        "arms": [{"product_root": str(tmp_path / "arm")}],
    }
    return tmp_path, plan, state, prior


def run(root, plan):
    job.acquire_job(plan, root / "plan.json", root / "previous.json", "2024-01-08")


def test_acquisition_reserves_budget_and_keeps_actual_process_exit(supervised):
    root, plan, state, _ = supervised
    run(root, plan)
    directory = root / "acquisition-jobs/2024-01-08"
    prelaunch = json.loads((directory / "prelaunch.json").read_bytes())
    result = json.loads((directory / "exit.json").read_bytes())
    assert prelaunch["attempts_reserved"] == 500
    assert prelaunch["used_wall_seconds_with_initial_charge"] == 100
    assert prelaunch["wall_limit_seconds"] == 1800
    assert result["actual_return_code"] == 0
    assert result["waitpid_observed"] and result["cleanup_verified"]
    assert result["qualification_eligibility"] == "NOT_QUALIFIED"
    assert result == json.loads((Path(prelaunch["control_run"]) / "exit.json").read_bytes())
    assert state.killed == [signal.SIGKILL, 0]
    assert state.waits == 2
    assert state.capacity_checks == [32 * 1024**3] * 2
    argv, options = state.spawned[0]
    assert argv[-2:] == ["--day", "2024-01-08"]
    assert options["start_new_session"]
    assert options["env"]["OPENBLAS_NUM_THREADS"] == "1"


@pytest.mark.parametrize("failure", ["exit", "spawn", "timeout", "growth", "lingering"])
def test_failed_acquisition_retains_actual_exit_and_never_reissues(supervised, failure):
    root, plan, state, _ = supervised
    if failure == "exit":
        state.code = 7
    elif failure == "spawn":
        state.spawn_error = True
    else:
        setattr(
            state,
            {"timeout": "timeout", "growth": "growth", "lingering": "lingering"}[failure],
            True,
        )
    with pytest.raises(RuntimeError, match="did not finish cleanly"):
        run(root, plan)
    result_path = root / "acquisition-jobs/2024-01-08/exit.json"
    raw = result_path.read_bytes()
    result = json.loads(raw)
    assert result["actual_return_code"] == (None if failure == "spawn" else state.code)
    assert result["waitpid_observed"] == (failure != "spawn")
    assert result["cleanup_verified"] == (failure != "lingering")
    assert (
        result["failure"]
        == {
            "exit": None,
            "spawn": "OSError",
            "timeout": "TimeoutError",
            "growth": "RuntimeError",
            "lingering": None,
        }[failure]
    )
    with pytest.raises(PermissionError, match="explicit reconciliation"):
        job.acquire_job(plan, root / "plan.json", root / "previous.json", "2024-01-09")
    assert len(state.spawned) == int(failure != "spawn")
    assert result_path.read_bytes() == raw


@pytest.mark.parametrize("boundary", ["prior", "wall", "attempts", "count", "lease"])
def test_budget_and_unverified_prior_cleanup_stop_before_spawn(supervised, boundary):
    root, plan, state, prior = supervised
    if boundary in {"prior", "count"}:
        for index in range(61 if boundary == "count" else 1):
            directory = root / "acquisition-jobs" / str(index)
            directory.mkdir(parents=True)
            (directory / "exit.json").write_bytes(
                canonical_json_bytes(
                    {
                        "actual_return_code": 0,
                        "cleanup_verified": boundary != "prior",
                        "wall_seconds": 1,
                    }
                )
            )
    elif boundary == "wall":
        plan["acquisition_wall_seconds"] = 100
    elif boundary == "attempts":
        plan["initial_attempt_charge"] = 39501
    else:
        (prior / "exit.json").write_bytes(canonical_json_bytes({"cleanup_verified": False}))
    with pytest.raises((PermissionError, RuntimeError)):
        run(root, plan)
    assert not state.spawned
    assert not (root / "acquisition-jobs/2024-01-08").exists()
