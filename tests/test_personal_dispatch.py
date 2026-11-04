"""Dispatcher/worker boundary fixtures; simulated exits are not namespace proof."""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from quantos.application import personal_dispatch as dispatch
from quantos.application.personal_forward_authority import forward_operation_identity
from quantos.application.personal_server_config import (
    PersonalScopeRegistration,
    PersonalServerConfigV5,
)
from quantos.application.personal_strategy_authority import ScopeReservationMissing
from quantos.artifacts.store import ArtifactError, ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalForwardScope, PersonalResearchScope
from quantos.infrastructure.hosted_storage import LEASE_ENV, StoragePolicy, StorageRejected


class FixtureGuard:
    """No host/quota acceptance: tests inject this guard and a simulated supervisor."""

    def __init__(self, policy):
        self.policy = policy
        self.policy_hash = sha256_bytes(policy.canonical_bytes())
        self.checks = []
        self.leases = 0

    def check(self, estimate=0):
        self.checks.append(estimate)
        return {}

    def require_lease(self):
        self.leases += 1


class FixtureAuthority:
    """Budget API simulation only; no real process/scope qualification is inferred."""

    def __init__(self, scope):
        self.scope = scope
        self.entries = {}
        self.settlements = []
        self.stopped = False

    def remaining_limits(self):
        charged_wall = sum(e.get("charged_wall", e["wall"]) for e in self.entries.values())
        charged_growth = sum(e.get("charged_growth", e["growth"]) for e in self.entries.values())
        pending = [key for key, value in self.entries.items() if not value["settled"]]
        wall = max(0, self.scope.wall_seconds - charged_wall)
        growth = max(0, self.scope.growth_bytes - charged_growth)
        result = {
            "timeout_seconds": math.floor(wall),
            "wall_seconds": wall,
            "growth_bytes": growth,
            "pending": pending,
            "admissible": wall > 0 and growth > 0 and not pending and not self.stopped,
        }
        if isinstance(self.scope, PersonalResearchScope):
            result.update(
                remaining_attempts=self.scope.max_attempts - len(self.entries),
                remaining_native_accounts=self.scope.max_native_accounts - len(self.entries),
            )
        else:
            result.update(
                remaining_observations=self.scope.max_observations
                - sum(e["operation"] == "observe" for e in self.entries.values()),
                remaining_native_steps=self.scope.max_native_steps
                - sum(e["operation"] == "shadow_advance" for e in self.entries.values()),
            )
        return result

    def admit_worker(self, request, run):
        operation = request["operation"]
        if operation == "observation_recover":
            return
        identity = (
            request["payload"]["task_id"]
            if operation == "research_execute"
            else forward_operation_identity(operation, request["payload"])
        )
        limits = self.remaining_limits()
        self.entries[identity] = {
            "supervisor_lease": str(run),
            "settled": False,
            "wall": limits["wall_seconds"],
            "growth": limits["growth_bytes"],
            "operation": "observe" if operation == "observation_observe" else operation,
        }

    def reservation(self, identity):
        if identity not in self.entries:
            raise ScopeReservationMissing("identity has no trusted reservation in this scope")
        return self.entries[identity]

    def settle(self, *args, **kwargs):
        identity, state = args[-2:]
        entry = self.reservation(identity)
        assert kwargs["exit_scope"] == "SUPERVISOR_PROCESS_WAIT"
        assert kwargs["growth_measurement"] == "OWNED_RETAINED_LOGICAL_BYTES"
        reference = kwargs["exit_reference"]
        assert reference["path"] == str(Path(entry["supervisor_lease"]) / "exit.json")
        assert sha256_bytes(Path(reference["path"]).read_bytes()) == reference["sha256"]
        if entry["settled"]:
            assert entry["settlement"] == (args, kwargs)
            return self.remaining_limits()
        self.settlements.append((args, kwargs))
        if kwargs["wall_seconds"] is None or kwargs["growth_bytes"] is None:
            return self.remaining_limits()
        normal = state in {"SUCCEEDED", "EMITTED", "ABSTAIN", "MISSING", "STOPPED"}
        entry.update(
            settled=True,
            settlement=(args, kwargs),
            charged_wall=kwargs["wall_seconds"]
            if normal
            else max(kwargs["wall_seconds"], entry["wall"]),
            charged_growth=kwargs["growth_bytes"]
            if normal
            else max(kwargs["growth_bytes"], entry["growth"]),
        )
        if state in {"UNKNOWN", "CANCELLED", "STOPPED"}:
            self.stopped = True
        return self.remaining_limits()


def setup(tmp_path, monkeypatch, *, mode="success", expired=False):
    repo = tmp_path / "repository"
    root = repo / "artifacts/product"
    evidence = repo / "artifacts/hosted-evidence"
    evidence.mkdir(parents=True)
    root.mkdir()
    config_root = tmp_path / "operator-config"
    config_root.mkdir()
    policy = StoragePolicy(
        evidence_root=evidence,
        scratch_root=tmp_path / "scratch",
        host_volume=tmp_path / "volume",
        vhd_file=tmp_path / "volume/disk.vhdx",
        linux_reserve_bytes=1 << 30,
        host_reserve_bytes=1 << 30,
        scratch_quota_bytes=64 << 20,
    )
    policy_path = config_root / "policy.json"
    policy_path.write_bytes(policy.canonical_bytes())
    approval = config_root / "approval.txt"
    approval.write_bytes(b"Synthetic dispatcher fixtures only; no real execution.")
    expiry = datetime(2020 if expired else 2099, 1, 1, tzinfo=UTC)
    common = {
        "purpose": "SYNTHETIC_ENGINEERING",
        "policy_hash": "b" * 64,
        "runtime_hash": "c" * 64,
        "start_date": "2024-01-03",
        "end_date": "2024-01-05",
        "expires_at": expiry,
        "approval_evidence_sha256": sha256_bytes(approval.read_bytes()),
    }
    research = PersonalResearchScope(
        **common,
        dataset_hash="a" * 64,
        allowed_strategy_hashes=("d" * 64,),
        max_attempts=2,
        max_native_accounts=4,
        wall_seconds=3,
        growth_bytes=8 << 20,
    )
    forward = PersonalForwardScope(
        **common,
        strategy_hash="d" * 64,
        allowed_dataset_hashes=("a" * 64,),
        max_observations=3,
        max_native_steps=3,
        wall_seconds=5,
        growth_bytes=10 << 20,
    )

    def registration(name, scope):
        path = config_root / (name + ".json")
        path.write_bytes(scope.canonical_bytes())
        return PersonalScopeRegistration(
            scope_path=path,
            scope_sha256=sha256_bytes(path.read_bytes()),
            approval_evidence_path=approval,
            storage_policy_path=policy_path,
            storage_policy_sha256=sha256_bytes(policy_path.read_bytes()),
        )

    config = PersonalServerConfigV5(
        product_root=root,
        repo_root=repo,
        research_scope=registration("research", research),
        forward_scope=registration("forward", forward),
    )
    config_path = config_root / "server.json"
    config_path.write_bytes(config.canonical_bytes())
    monkeypatch.setattr(dispatch, "StorageGuard", FixtureGuard)
    monkeypatch.setattr(dispatch, "require_bounded_bwrap", lambda: None)
    calls = []
    authorities = {
        "research_execute": FixtureAuthority(research),
        "forward": FixtureAuthority(forward),
    }
    fake_core = SimpleNamespace(
        strategy_authority=authorities["research_execute"],
        product_services=SimpleNamespace(forward_authority=authorities["forward"]),
        _prepared=lambda task: SimpleNamespace(candidates=(None,)),
    )
    monkeypatch.setattr(
        dispatch.PersonalResourceDispatcher, "_trusted_core", lambda self: fake_core
    )

    def supervisor(guard, argv, *, stage, expected_new_bytes, run_observer):
        calls.append({"argv": argv, "stage": stage, "growth": expected_new_bytes})
        assert stage == "matrix"
        assert argv[:3] == ("/usr/bin/timeout", "--signal=TERM", "--kill-after=10")
        assert (
            "-I" in argv
            and "-B" in argv
            and argv[argv.index("-m") + 1] == "quantos.personal_worker"
        )
        command_path = Path(argv[argv.index("--command") + 1])
        command = json.loads(command_path.read_bytes())
        assert argv[3] == str(command["request"]["wall_seconds"])
        command_hash = argv[-1]
        assert sha256_bytes(command_path.read_bytes()) == command_hash
        run = guard.policy.evidence_root / "storage-control" / f"run-123-{len(calls)}"
        run.mkdir(parents=True)
        run_observer(run)
        if mode == "prelaunch-failure":
            atomic_write_bytes(
                run / "exit.json",
                canonical_json_bytes(
                    {
                        "stage": stage,
                        "policy_hash": guard.policy_hash,
                        "return_code": None,
                        "waitpid_observed": False,
                        "cleanup_verified": True,
                        "launch_attempted": False,
                    }
                ),
            )
            raise StorageRejected("STORAGE_HOST_HEADROOM")
        atomic_write_bytes(
            run / "prelaunch.json",
            canonical_json_bytes(
                {
                    "stage": stage,
                    "policy_hash": guard.policy_hash,
                    "argv_hash": sha256_bytes(canonical_json_bytes(argv)),
                    "expected_new_bytes": expected_new_bytes,
                }
            ),
        )
        atomic_write_bytes(run / "namespace.json", canonical_json_bytes({"child-pid": 17}))
        authority = authorities[
            "research_execute"
            if command["request"]["operation"] == "research_execute"
            else "forward"
        ]
        authority.admit_worker(command["request"], run)
        if mode == "unknown":
            raise RuntimeError("private supervisor message must not be saved")
        code = 23 if mode in {"failure", "pit"} else 0
        atomic_write_bytes(
            run / "exit.json",
            canonical_json_bytes(
                {
                    "stage": stage,
                    "policy_hash": guard.policy_hash,
                    "return_code": code,
                    "waitpid_observed": True,
                    "cleanup_verified": True,
                    "namespace_exit_observed": True,
                    "process_scope": "PID_NAMESPACE_WRAPPER",
                    "failure": None,
                }
            ),
        )
        attempt = command_path.parent
        if mode == "pit":
            atomic_write_bytes(
                attempt / "worker-failure.json",
                canonical_json_bytes(
                    {
                        "job_id": command["request_hash"],
                        "command_hash": command_hash,
                        "reason_code": "PIT_HARD_REJECTION",
                        "error_type": "ValueError",
                    }
                ),
            )
        if code:
            raise StorageRejected("STORAGE_JOB_FAILED")
        if mode != "missing-result":
            operation = command["request"]["operation"]
            output = {"state": "CANCELLED" if mode == "cancelled" else "SUCCEEDED", "fixture": True}
            if operation == "observation_observe":
                output = {"status": "EMITTED", "fixture": True}
            elif operation == "shadow_advance":
                output = {"native_receipt": {"run_status": "SUCCEEDED"}, "fixture": True}
            atomic_write_bytes(
                attempt / "worker-result.json",
                canonical_json_bytes(
                    {
                        "job_id": command["request_hash"],
                        "command_hash": command_hash,
                        "operation": command["request"]["operation"],
                        "result": output,
                    }
                ),
            )
        return run

    monkeypatch.setattr(dispatch, "supervise_storage_job", supervisor)
    client = dispatch.PersonalResourceDispatcher(root, repo, config_path)
    client.fixture_authorities = authorities
    return client, calls, config, policy


def test_frozen_dispatch_uses_exact_scope_budget_and_replays_without_second_launch(
    tmp_path, monkeypatch
):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    payload = {"task_id": "a" * 64}
    result = client("research_execute", payload)
    assert result == {"state": "SUCCEEDED", "fixture": True}
    assert client("research_execute", payload) == result
    assert len(calls) == 1 and calls[0]["growth"] == 8 << 20
    attempt = next((client.root / "jobs").glob("*/attempt-0001"))
    receipt = json.loads((attempt / "return.json").read_bytes())
    assert receipt["qualification_eligibility"] == "NOT_QUALIFIED"
    assert receipt["supervisor"]["namespace_sha256"]
    assert client.reconcile(attempt.parent.name) == result
    assert len(calls) == 1


def test_forward_operation_uses_forward_budget_and_only_fixed_payload_routes(tmp_path, monkeypatch):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    client(
        "observation_observe",
        {
            "observation_id": "1" * 64,
            "day": "2024-01-03",
            "dataset_id": "fixture",
            "observed_at": "2024-01-03T23:59:00+08:00",
        },
    )
    assert calls[0]["growth"] == 10 << 20
    with pytest.raises(ValueError, match="unsupported"):
        client("__getattribute__", {})
    for bad in (
        {"task_id": "a" * 64, "approved": True},
        {"task_id": "../../outside"},
        {"task_id": "a" * 64, "path": "/etc/passwd"},
    ):
        with pytest.raises(ValidationError):
            client("research_execute", bad)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "mode,code,reason",
    [
        ("failure", 23, "RESOURCE_SUPERVISOR_FAILED"),
        ("pit", 23, "PIT_HARD_REJECTION"),
        ("prelaunch-failure", None, "RESOURCE_SUPERVISOR_FAILED"),
    ],
)
def test_failures_keep_observed_exit_and_never_fabricate_unlaunched_exit(
    tmp_path, monkeypatch, mode, code, reason
):
    client, calls, _, _ = setup(tmp_path, monkeypatch, mode=mode)
    for _ in range(2):
        with pytest.raises(dispatch.PersonalDispatchFailure) as rejected:
            client("research_execute", {"task_id": "a" * 64})
        assert rejected.value.record["return_code"] == code
        assert rejected.value.reason_code == reason
    assert len(calls) == 1
    failure = next((client.root / "jobs").glob("*/attempt-0001/failure.json"))
    assert json.loads(failure.read_bytes())["validation_verdict"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("unknown", "SUPERVISOR_EXIT_UNOBSERVED"),
        ("missing-result", "WORKER_RESULT_UNOBSERVED_AFTER_SUPERVISOR_EXIT"),
    ],
)
def test_unknown_is_durable_and_does_not_relaunch(tmp_path, monkeypatch, mode, reason):
    client, calls, _, _ = setup(tmp_path, monkeypatch, mode=mode)
    first = client("research_execute", {"task_id": "a" * 64})
    assert first["state"] == "UNKNOWN" and first["reason_code"] == reason
    assert first["reissued"] is False and first["real_exit_invented"] is False
    assert client("research_execute", {"task_id": "a" * 64}) == first
    assert client.reconcile(first["job_id"]) == first
    assert len(calls) == 1
    diagnostic = next((client.root / "jobs").glob("*/attempt-0001/diagnostics/*.json"))
    assert json.loads(diagnostic.read_bytes()) == first
    for path in (client.root / "jobs").rglob("*.json"):
        assert b"private supervisor message" not in path.read_bytes()


@pytest.mark.parametrize("target", ["config", "approval", "policy"])
def test_changed_trusted_inputs_reject_before_launch(tmp_path, monkeypatch, target):
    client, calls, config, _ = setup(tmp_path, monkeypatch)
    files = {
        "config": client.config_path,
        "approval": config.research_scope.approval_evidence_path,
        "policy": config.research_scope.storage_policy_path,
    }
    files[target].write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError):
        client("research_execute", {"task_id": "a" * 64})
    assert not calls


def test_expired_scope_and_root_alias_reject_without_new_authority(tmp_path, monkeypatch):
    client, calls, _, _ = setup(tmp_path / "expired", monkeypatch, expired=True)
    with pytest.raises(PermissionError, match="expired"):
        client("research_execute", {"task_id": "a" * 64})
    assert not calls
    live, live_calls, config, _ = setup(tmp_path / "alias", monkeypatch)
    alias = live.root.parent / "product-alias"
    alias.symlink_to(live.root, target_is_directory=True)
    changed = config.model_copy(update={"product_root": alias})
    live.config_path.write_bytes(changed.canonical_bytes())
    aliased = dispatch.PersonalResourceDispatcher(alias, live.repo_root, live.config_path)
    with pytest.raises(ArtifactIntegrityError, match="unsafe"):
        aliased("research_execute", {"task_id": "a" * 64})
    assert not live_calls


@pytest.mark.parametrize(
    "operation,payload,route",
    [
        (
            "observation_observe",
            {
                "observation_id": "a" * 64,
                "day": "2024-01-03",
                "dataset_id": "fixture",
                "observed_at": "2024-01-03T23:59:00+08:00",
            },
            "observe",
        ),
        ("observation_recover", {"observation_id": "a" * 64, "attempt_hash": "b" * 64}, "recover"),
        (
            "shadow_advance",
            {
                "shadow_id": "a" * 64,
                "execution_date": "2024-01-04",
                "observation_record_hash": "b" * 64,
                "execution_dataset_id": "fixture",
            },
            "advance",
        ),
    ],
)
def test_fixed_worker_routes_only_the_normalized_operation(operation, payload, route):
    from quantos.personal_worker import execute_worker_operation

    calls = []

    def called(**values):
        calls.append(values)
        return {"route": route}

    recorded = []
    product = SimpleNamespace(
        observations=SimpleNamespace(observe=called, recover=called),
        shadow=SimpleNamespace(advance=called),
        record_forward_result=lambda *args: recorded.append(args),
    )
    normalized = dispatch.dispatch_payload(operation, payload)
    assert execute_worker_operation(
        SimpleNamespace(product_services=product), operation, normalized
    ) == {"route": route}
    assert calls == [normalized]
    assert recorded == (
        [] if operation == "observation_recover" else [(operation, normalized, {"route": route})]
    )


@pytest.mark.parametrize("target", ["command", "result", "prelaunch", "exit", "namespace"])
def test_reconciliation_rejects_changed_committed_originals(tmp_path, monkeypatch, target):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    client("research_execute", {"task_id": "a" * 64})
    attempt = next((client.root / "jobs").glob("*/attempt-0001"))
    run = Path(json.loads((attempt / "supervisor-run.json").read_bytes())["path"])
    files = {
        "command": attempt / "command.json",
        "result": attempt / "worker-result.json",
        "prelaunch": run / "prelaunch.json",
        "exit": run / "exit.json",
        "namespace": run / "namespace.json",
    }
    files[target].write_bytes(b"{}")
    with pytest.raises((ArtifactError, ValueError, KeyError)):
        client.reconcile(attempt.parent.name)
    assert len(calls) == 1


def test_worker_checks_actual_lease_command_hash_and_fixed_python_before_core(
    tmp_path, monkeypatch
):
    client, _, _, policy = setup(tmp_path, monkeypatch)
    client("research_execute", {"task_id": "a" * 64})
    attempt = next((client.root / "jobs").glob("*/attempt-0001"))
    command_path = attempt / "command.json"
    command_hash = sha256_bytes(command_path.read_bytes())
    run = Path(json.loads((attempt / "supervisor-run.json").read_bytes())["path"])
    monkeypatch.setenv(LEASE_ENV, str(run))
    guard = FixtureGuard(policy)
    assert (
        dispatch.validate_worker_command(command_path, command_hash, guard)["request_hash"]
        == attempt.parent.name
    )
    assert guard.leases == 1
    prelaunch = json.loads((run / "prelaunch.json").read_bytes())
    prelaunch["argv_hash"] = "0" * 64
    (run / "prelaunch.json").write_bytes(canonical_json_bytes(prelaunch))
    with pytest.raises(PermissionError, match="actual resource-supervised"):
        dispatch.validate_worker_command(command_path, command_hash, guard)


@pytest.mark.parametrize("fail", [False, True])
def test_worker_uses_worker_mode_and_saves_only_controlled_outcomes(tmp_path, monkeypatch, fail):
    from quantos import personal_worker
    from quantos.application import personal_server_config

    client, _, _, policy = setup(tmp_path, monkeypatch)
    client("research_execute", {"task_id": "a" * 64})
    attempt = next((client.root / "jobs").glob("*/attempt-0001"))
    (attempt / "worker-result.json").unlink()
    command_path = attempt / "command.json"
    command_hash = sha256_bytes(command_path.read_bytes())
    run = Path(json.loads((attempt / "supervisor-run.json").read_bytes())["path"])
    monkeypatch.setenv(LEASE_ENV, str(run))
    monkeypatch.setattr(personal_worker, "configured_guard", lambda: FixtureGuard(policy))
    received = []

    def execute(task_id):
        received.append(task_id)
        if fail:
            raise PermissionError("private authorization detail")
        return {"state": "FAILED", "validation_verdict": "NOT_EVALUATED"}

    def factory(*args, **kwargs):
        assert kwargs == {"worker_mode": True}
        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(personal_server_config, "make_trusted_service", factory)
    assert personal_worker.run_worker(command_path, command_hash) == int(fail)
    assert received == ["a" * 64]
    output = json.loads(
        (attempt / ("worker-failure.json" if fail else "worker-result.json")).read_bytes()
    )
    assert output["command_hash"] == command_hash
    assert b"private authorization detail" not in canonical_json_bytes(output)
    if fail:
        assert output["reason_code"] == "AUTHORIZATION_REJECTED"
    else:
        assert (
            output["result"]["state"] == "FAILED"
        )  # A returned strategy failure is not process exit 1.


def test_worker_rejects_unbound_command_without_inventing_an_output_receipt(tmp_path, monkeypatch):
    from quantos import personal_worker

    monkeypatch.setattr(
        sys, "argv", ["worker", "--command", str(tmp_path / "absent"), "--command-sha256", "0" * 64]
    )
    assert personal_worker.main() == 1
    assert not list(tmp_path.iterdir())


def test_success_settles_whole_job_and_next_attempt_uses_remaining_frozen_budget(
    tmp_path, monkeypatch
):
    client, calls, _, policy = setup(tmp_path, monkeypatch)
    first = {"task_id": "a" * 64}
    second = {"task_id": "b" * 64}
    client("research_execute", first)
    authority = client.fixture_authorities["research_execute"]
    settlement = authority.settlements[0][1]
    assert settlement["wall_seconds"] > 0
    assert settlement["growth_bytes"] > 0
    assert settlement["exit_reference"]["path"].endswith("/exit.json")
    assert settlement["growth_measurement"] == "OWNED_RETAINED_LOGICAL_BYTES"
    client("research_execute", second)
    assert len(calls) == 2
    assert int(calls[1]["argv"][3]) < int(calls[0]["argv"][3])
    assert 0 < calls[1]["growth"] < calls[0]["growth"]
    assert client("research_execute", first)["state"] == "SUCCEEDED"
    assert len(calls) == 2
    with pytest.raises(PermissionError, match="budget exhausted"):
        client("research_execute", {"task_id": "c" * 64})
    # Child validation adopts its frozen request, despite remaining limits now changing.
    attempt = Path(calls[1]["argv"][calls[1]["argv"].index("--command") + 1]).parent
    run = Path(json.loads((attempt / "supervisor-run.json").read_bytes())["path"])
    monkeypatch.setenv(LEASE_ENV, str(run))
    command_path = attempt / "command.json"
    command = dispatch.validate_worker_command(
        command_path, sha256_bytes(command_path.read_bytes()), FixtureGuard(policy)
    )
    assert command["request"]["complete_growth_bytes"] == calls[1]["growth"]


def test_observation_receipt_clock_cannot_create_a_second_dispatch_or_settlement(
    tmp_path, monkeypatch
):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    payload = {
        "observation_id": "1" * 64,
        "day": "2024-01-03",
        "dataset_id": "fixture",
        "observed_at": "2024-01-03T23:59:00+08:00",
    }
    first = client("observation_observe", payload)
    later = client("observation_observe", {**payload, "observed_at": "2024-01-04T00:00:00+08:00"})
    assert later == first
    assert len(calls) == 1
    assert len(client.fixture_authorities["forward"].entries) == 1
    assert len(client.fixture_authorities["forward"].settlements) == 1
    command = json.loads(
        Path(calls[0]["argv"][calls[0]["argv"].index("--command") + 1]).read_bytes()
    )
    assert command["request"]["payload"]["observed_at"] == "2024-01-03T15:59:00Z"


def test_expiry_allows_only_bound_read_and_reconciliation(tmp_path, monkeypatch):
    from datetime import datetime as RealDatetime

    client, calls, _, _ = setup(tmp_path, monkeypatch)
    result = client("research_execute", {"task_id": "a" * 64})
    job = next((client.root / "jobs").iterdir())

    class FutureClock(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2100, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(dispatch, "datetime", FutureClock)
    assert client("research_execute", {"task_id": "a" * 64}) == result
    assert client.reconcile(job.name) == result
    with pytest.raises(PermissionError, match="expired"):
        client("research_execute", {"task_id": "b" * 64})
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["failure", "cancelled", "missing-result", "unknown"])
def test_unsuccessful_or_uncertain_attempt_never_refunds_unused_limits(tmp_path, monkeypatch, mode):
    client, calls, _, _ = setup(tmp_path, monkeypatch, mode=mode)
    try:
        client("research_execute", {"task_id": "a" * 64})
    except dispatch.PersonalDispatchFailure:
        assert mode == "failure"
    authority = client.fixture_authorities["research_execute"]
    assert authority.remaining_limits()["admissible"] is False
    assert authority.remaining_limits()["growth_bytes"] == 0
    assert authority.remaining_limits()["timeout_seconds"] == 0
    with pytest.raises(PermissionError):
        client("research_execute", {"task_id": "b" * 64})
    assert len(calls) == 1


def test_no_reservation_is_distinct_from_corrupt_reservation_and_keeps_real_usage(
    tmp_path, monkeypatch
):
    client, _, _, _ = setup(tmp_path / "absent", monkeypatch)
    authority = client.fixture_authorities["research_execute"]
    monkeypatch.setattr(authority, "admit_worker", lambda request, run: None)
    client("research_execute", {"task_id": "a" * 64})
    receipt = next((client.root / "jobs").glob("*/attempt-0001/return.json"))
    assert json.loads(receipt.read_bytes())["budget_settlement"]["state"] == "NOT_RESERVED"
    usage = json.loads((receipt.parent / "resource-usage.json").read_bytes())
    assert usage["wall_seconds"] > 0 and usage["growth_bytes"] > 0
    assert not authority.settlements

    bad, _, _, _ = setup(tmp_path / "corrupt", monkeypatch)
    bad_authority = bad.fixture_authorities["research_execute"]

    def corrupt(identity):
        raise ValueError("invalid journal JSON")

    monkeypatch.setattr(bad_authority, "reservation", corrupt)
    with pytest.raises(ValueError, match="invalid journal"):
        bad("research_execute", {"task_id": "a" * 64})
    assert not bad_authority.settlements


def test_missing_timing_retains_reservation_without_inventing_wall(tmp_path, monkeypatch):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    original_settle = client._settle

    def missing_timing(identity, request, attempt, guard):
        (attempt / "supervisor-returned.json").unlink(missing_ok=True)
        return original_settle(identity, request, attempt, guard)

    monkeypatch.setattr(client, "_settle", missing_timing)
    assert client("research_execute", {"task_id": "a" * 64})["state"] == "SUCCEEDED"
    usage = next((client.root / "jobs").glob("*/attempt-0001/resource-usage.json"))
    assert json.loads(usage.read_bytes())["wall_seconds"] is None
    assert client.fixture_authorities["research_execute"].remaining_limits()["pending"] == [
        "a" * 64
    ]
    with pytest.raises(PermissionError):
        client("research_execute", {"task_id": "b" * 64})
    assert len(calls) == 1


@pytest.mark.parametrize("target", ["usage", "baseline", "timing", "index"])
def test_frozen_admission_and_resource_proofs_are_integrity_checked(tmp_path, monkeypatch, target):
    client, calls, _, _ = setup(tmp_path, monkeypatch)
    client("research_execute", {"task_id": "a" * 64})
    attempt = next((client.root / "jobs").glob("*/attempt-0001"))
    paths = {
        "usage": attempt / "resource-usage.json",
        "baseline": attempt / "measurement-start.json",
        "timing": attempt / "supervisor-returned.json",
        "index": next((client.root / "dispatch-identities").glob("*.json")),
    }
    paths[target].write_bytes(b"{}")
    with pytest.raises((ArtifactError, PermissionError, ValueError, KeyError)):
        client("research_execute", {"task_id": "a" * 64})
    assert len(calls) == 1
