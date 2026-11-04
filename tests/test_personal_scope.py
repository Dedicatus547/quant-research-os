"""Finite scope arithmetic/refusal fixtures; fake wait files confer no native proof."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from quantos.application.personal_forward_authority import (
    PersonalForwardAuthority,
    forward_operation_identity,
)
from quantos.application.personal_strategy_authority import PersonalStrategyAuthority
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import (
    PersonalExecutionPolicy,
    PersonalForwardScope,
    PersonalResearchScope,
    PersonalStrategy,
    PreparedStrategyStudy,
    StrategyStudyRequest,
)
from quantos.infrastructure.hosted_storage import HASH_ENV, LEASE_ENV


def prepared(key="one"):
    spec = PersonalStrategy.model_validate(
        {
            "score": {
                "expression_id": "close",
                "nodes": [{"node_id": "p", "operator": "field", "field_name": "adjusted_close"}],
                "output_node_id": "p",
            }
        }
    )
    request = StrategyStudyRequest.model_validate(
        {
            "idempotency_key": key,
            "brief": "Scope unit fixture",
            "proposal": {"session_id": "synthetic-fixture"},
            "dataset_id": "fixture",
            "start_date": "2024-01-03",
            "end_date": "2024-01-05",
            "warmup_start": "2024-01-02",
            "candidates": [
                {"candidate_id": "main", "role": "main", "hypothesis": "fixture", "strategy": spec}
            ],
        }
    )
    return PreparedStrategyStudy(
        request=request,
        code_hash="c" * 64,
        dataset_hash="a" * 64,
        strategy_hashes={"main": spec.content_hash},
        policy_hash=PersonalExecutionPolicy().content_hash,
        readiness="READY_FOR_AUTHORIZATION",
        gaps=(),
        resolved={},
    )


def setup(tmp_path, *, forward=False, max_attempts=3, expired=False):
    item, approval = prepared(), b"Synthetic scope boundary fixtures only."
    common = {
        "purpose": "SYNTHETIC_ENGINEERING",
        "policy_hash": item.policy_hash,
        "runtime_hash": item.code_hash,
        "start_date": item.request.start_date,
        "end_date": item.request.end_date,
        "wall_seconds": 10,
        "growth_bytes": 1000,
        "expires_at": datetime(2020 if expired else 2099, 1, 1, tzinfo=UTC),
        "approval_evidence_sha256": sha256_bytes(approval),
    }
    checks = []
    if forward:
        scope = PersonalForwardScope(
            **common,
            strategy_hash=item.strategy_hashes["main"],
            allowed_dataset_hashes=(item.dataset_hash,),
            max_observations=3,
            max_native_steps=3,
        )
        authority = PersonalForwardAuthority(
            tmp_path, scope, approval, resource_check=lambda s: checks.append(s.content_hash)
        )
    else:
        scope = PersonalResearchScope(
            **common,
            dataset_hash=item.dataset_hash,
            allowed_strategy_hashes=tuple(item.strategy_hashes.values()),
            max_attempts=max_attempts,
            max_native_accounts=3,
        )
        authority = PersonalStrategyAuthority(
            tmp_path, scope, approval, resource_check=lambda s: checks.append(s.content_hash)
        )
    return authority, item, checks


def lease(tmp_path, monkeypatch, name="one", *, code=0, waited=True, namespace=True, cleanup=True):
    """Write explicit fixture proof shapes; no actual lease or process is asserted."""
    root = tmp_path / ("fixture-supervisor-" + name)
    root.mkdir()
    policy_hash = "f" * 64
    (root / "prelaunch.json").write_bytes(
        canonical_json_bytes(
            {
                "stage": "matrix",
                "policy_hash": policy_hash,
                "expected_new_bytes": 1000,
                "argv_hash": "e" * 64,
            }
        )
    )
    exit_path = root / "exit.json"
    exit_path.write_bytes(
        canonical_json_bytes(
            {
                "stage": "matrix",
                "policy_hash": policy_hash,
                "return_code": code,
                "waitpid_observed": waited,
                "namespace_exit_observed": namespace,
                "cleanup_verified": cleanup,
                "process_scope": "PID_NAMESPACE_WRAPPER",
                "failure": None,
            }
        )
    )
    monkeypatch.setenv(LEASE_ENV, str(root))
    monkeypatch.setenv(HASH_ENV, policy_hash)
    return {"path": str(exit_path), "sha256": sha256_bytes(exit_path.read_bytes())}


def test_success_wait_releases_only_unused_limits_and_next_attempt_has_remaining_budget(
    tmp_path, monkeypatch
):
    authority, first, checks = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch)
    assert authority.reserve(first, "synthetic") == authority.scope.content_hash
    original = authority.reservation(first.content_hash)
    assert original["wall_limit_seconds"] == 10 and original["growth_limit_bytes"] == 1000
    assert authority.reserve(first, "synthetic") == authority.scope.content_hash
    assert authority.status()["attempted_denominator"] == 1
    authority.record(
        first.content_hash, "SUCCEEDED", {"outcome_hash": "d" * 64}, wall_seconds=1, growth_bytes=50
    )
    assert authority.remaining_limits()["state"] == "UNSETTLED"
    with pytest.raises(PermissionError, match="unsettled"):
        authority.reserve(prepared("two"), "synthetic")
    limits = authority.settle(
        first.content_hash, "SUCCEEDED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    assert limits["wall_seconds"] == 8 and limits["growth_bytes"] == 900
    assert (
        limits["observed_used_wall_seconds"] == 2
        and limits["retained_reservation_wall_seconds"] == 0
    )
    assert limits["admissible"] is True
    assert (
        authority.settle(
            first.content_hash, "SUCCEEDED", wall_seconds=2, growth_bytes=100, exit_reference=proof
        )
        == limits
    )
    lease(tmp_path, monkeypatch, "two")
    second = prepared("two")
    authority.reserve(second, "synthetic")
    assert authority.reservation(second.content_hash)["wall_limit_seconds"] == 8
    assert authority.reservation(second.content_hash)["growth_limit_bytes"] == 900
    assert authority.status()["reserved_native_accounts"] == 2
    assert len(checks) == 3  # initial, duplicate source/resource recheck, second reservation


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "UNKNOWN"])
def test_failures_keep_unused_reservations_separate_from_actual_usage(tmp_path, monkeypatch, state):
    authority, item, _ = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch, code=0 if state == "FAILED" else 124)
    authority.reserve(item, "synthetic")
    authority.record(item.content_hash, state, {}, wall_seconds=1, growth_bytes=100)
    limits = authority.settle(
        item.content_hash, state, wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    assert limits["observed_used_wall_seconds"] == 2
    assert limits["observed_retained_output_bytes"] == 100
    assert limits["retained_reservation_wall_seconds"] == 8
    assert limits["retained_reservation_growth_bytes"] == 900
    assert limits["wall_seconds"] == limits["growth_bytes"] == 0
    assert limits["admissible"] is False
    assert authority.reservation(item.content_hash)["settlement"]["supervisor_return_code"] == (
        0 if state == "FAILED" else 124
    )
    with pytest.raises(PermissionError):
        authority.reserve(prepared("next"), "synthetic")


@pytest.mark.parametrize(
    "fault", ["wrong-run", "wrong-hash", "no-wait", "no-namespace", "no-cleanup", "failed-exit"]
)
def test_missing_or_mismatched_actual_exit_never_releases_resource_limits(
    tmp_path, monkeypatch, fault
):
    authority, item, _ = setup(tmp_path)
    proof = lease(
        tmp_path,
        monkeypatch,
        code=1 if fault == "failed-exit" else 0,
        waited=fault != "no-wait",
        namespace=fault != "no-namespace",
        cleanup=fault != "no-cleanup",
    )
    authority.reserve(item, "synthetic")
    if fault == "wrong-run":
        proof = lease(tmp_path, monkeypatch, "different")
    if fault == "wrong-hash":
        proof = {**proof, "sha256": "0" * 64}
    with pytest.raises((PermissionError, ArtifactIntegrityError)):
        authority.settle(
            item.content_hash, "SUCCEEDED", wall_seconds=1, growth_bytes=50, exit_reference=proof
        )
    assert authority.remaining_limits()["pending"] == [item.content_hash]
    assert authority.remaining_limits()["observed_used_wall_seconds"] == 0


def test_absent_measurements_remain_reserved_and_settled_measurements_cannot_be_rewritten(
    tmp_path, monkeypatch
):
    authority, item, _ = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    limits = authority.settle(
        item.content_hash, "SUCCEEDED", wall_seconds=None, growth_bytes=None, exit_reference=proof
    )
    assert limits["pending"] == [item.content_hash]
    assert limits["retained_reservation_wall_seconds"] == 10
    authority.settle(
        item.content_hash, "SUCCEEDED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    with pytest.raises(ArtifactIntegrityError, match="rewritten"):
        authority.settle(
            item.content_hash, "SUCCEEDED", wall_seconds=1, growth_bytes=100, exit_reference=proof
        )


def test_resource_overrun_is_retained_as_observed_and_stops_the_scope(tmp_path, monkeypatch):
    authority, item, _ = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    limits = authority.settle(
        item.content_hash, "SUCCEEDED", wall_seconds=11, growth_bytes=1100, exit_reference=proof
    )
    assert limits["overrun"] is True and limits["state"] == "STOPPED"
    assert limits["observed_used_wall_seconds"] == 11
    assert limits["observed_retained_output_bytes"] == 1100
    assert limits["wall_seconds"] == limits["growth_bytes"] == 0


def test_stop_is_normal_closed_authority_and_does_not_refund_or_reactivate(tmp_path, monkeypatch):
    authority, item, _ = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    authority.settle(
        item.content_hash, "SUCCEEDED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    stopped = authority.stop("Enough evidence for this finite question")
    assert authority.stop("duplicate STOP") == stopped
    assert stopped["remaining_limits"]["wall_seconds"] == 8
    assert stopped["remaining_limits"]["pending"] == []
    assert stopped["remaining_limits"]["admissible"] is False
    with pytest.raises(PermissionError, match="stopped"):
        authority.reserve(prepared("next"), "synthetic")


def test_forward_shared_identity_and_total_scope_limits_cover_observe_then_account(
    tmp_path, monkeypatch
):
    authority, item, checks = setup(tmp_path, forward=True)
    payload = {"observation_id": "1" * 64, "day": "2024-01-03", "dataset_id": "fixture"}
    identity = forward_operation_identity("observe", payload)
    assert identity == forward_operation_identity(
        "observation_observe",
        {**payload, "recompute": False, "observed_at": "irrelevant receipt time"},
    )
    assert identity != forward_operation_identity("observe", {**payload, "recompute": True})
    common = {
        "strategy_hash": item.strategy_hashes["main"],
        "policy_hash": item.policy_hash,
        "runtime_hash": item.code_hash,
        "dataset_hash": item.dataset_hash,
        "day": date(2024, 1, 3),
        "kind": "synthetic",
    }
    proof = lease(tmp_path, monkeypatch)
    authority.authorize(**common, operation="observe", operation_identity=identity)
    authority.authorize(**common, operation="observe", operation_identity=identity)
    authority.record(
        "observe", identity, "EMITTED", {"record_hash": "2" * 64}, wall_seconds=1, growth_bytes=50
    )
    assert len([e for e in authority.status()["events"] if e["kind"] == "RESERVED"]) == 1
    limits = authority.settle(
        "observe", identity, "EMITTED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    assert limits["wall_seconds"] == 8 and limits["growth_bytes"] == 900
    step = forward_operation_identity(
        "shadow_advance",
        {
            "shadow_id": "3" * 64,
            "execution_date": "2024-01-04",
            "observation_record_hash": "2" * 64,
            "execution_dataset_id": "fixture",
        },
    )
    lease(tmp_path, monkeypatch, "account")
    authority.authorize(
        **{**common, "day": date(2024, 1, 4)}, operation="shadow_advance", operation_identity=step
    )
    assert authority.reservation(step)["wall_limit_seconds"] == 8
    assert len(checks) == 3


def test_scope_and_last_event_tampering_are_rejected_without_changing_old_records(
    tmp_path, monkeypatch
):
    authority, item, _ = setup(tmp_path)
    lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    row = next((authority.root / "events").iterdir())
    original = row.read_bytes()
    data = json.loads(original)
    data["detail"]["wall_limit_seconds"] = 1
    row.write_bytes(canonical_json_bytes(data))
    with pytest.raises(ArtifactIntegrityError, match="content changed"):
        authority.remaining_limits()


def test_missing_live_resource_checker_cannot_create_reservation_or_an_exit(tmp_path):
    authority, item, _ = setup(tmp_path)
    authority.resource_check = None
    with pytest.raises(PermissionError, match="resource dispatcher"):
        authority.reserve(item, "synthetic")
    assert authority.status()["attempted_denominator"] == 0


def test_new_reservation_requires_a_real_lease_binding_even_with_a_callback(tmp_path, monkeypatch):
    authority, item, checks = setup(tmp_path)
    monkeypatch.delenv(LEASE_ENV, raising=False)
    monkeypatch.delenv(HASH_ENV, raising=False)
    with pytest.raises(PermissionError, match="live supervisor lease"):
        authority.reserve(item, "synthetic")
    assert len(checks) == 1
    assert authority.status()["attempted_denominator"] == 0


def test_attempt_count_exhaustion_still_stops_when_resource_headroom_remains(tmp_path, monkeypatch):
    authority, item, _ = setup(tmp_path, max_attempts=1)
    proof = lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    limits = authority.settle(
        item.content_hash, "SUCCEEDED", wall_seconds=2, growth_bytes=100, exit_reference=proof
    )
    assert limits["wall_seconds"] == 8 and limits["remaining_attempts"] == 0
    assert limits["admissible"] is False
    with pytest.raises(PermissionError, match="budget exhausted"):
        authority.reserve(prepared("over-count"), "synthetic")
    assert authority.status()["state"] == "STOPPED"


def test_forward_body_record_is_idempotent_and_cannot_settle_another_operation(
    tmp_path, monkeypatch
):
    authority, item, _ = setup(tmp_path, forward=True)
    payload = {"observation_id": "1" * 64, "day": "2024-01-03", "dataset_id": "fixture"}
    identity = forward_operation_identity("observe", payload)
    proof = lease(tmp_path, monkeypatch)
    authority.authorize(
        strategy_hash=item.strategy_hashes["main"],
        policy_hash=item.policy_hash,
        runtime_hash=item.code_hash,
        dataset_hash=item.dataset_hash,
        day=date(2024, 1, 3),
        kind="synthetic",
        operation="observe",
        operation_identity=identity,
    )
    for _ in range(2):
        authority.record(
            "observe",
            identity,
            "EMITTED",
            {"record_hash": "2" * 64},
            wall_seconds=1,
            growth_bytes=50,
        )
    assert len([e for e in authority.status()["events"] if e["kind"] == "RESULT"]) == 1
    assert authority.remaining_limits()["remaining_observations"] == 2
    assert authority.remaining_limits()["remaining_native_steps"] == 3
    with pytest.raises(ValueError, match="differs"):
        authority.settle(
            "shadow_advance",
            identity,
            "SUCCEEDED",
            wall_seconds=2,
            growth_bytes=100,
            exit_reference=proof,
        )


def test_measurement_domain_is_finite_and_whole_volume_is_not_exact_task_growth(
    tmp_path, monkeypatch
):
    authority, item, _ = setup(tmp_path)
    proof = lease(tmp_path, monkeypatch)
    authority.reserve(item, "synthetic")
    for wall, growth in ((float("nan"), 0), (-1, 0), (1, -1), (1, 1.5)):
        with pytest.raises(ValueError):
            authority.settle(
                item.content_hash,
                "SUCCEEDED",
                wall_seconds=wall,
                growth_bytes=growth,
                exit_reference=proof,
            )
    with pytest.raises(ValueError, match="whole-volume"):
        authority.settle(
            item.content_hash,
            "SUCCEEDED",
            wall_seconds=1,
            growth_bytes=50,
            exit_reference=proof,
            growth_measurement="WHOLE_VOLUME_DIFFERENCE",
        )
    assert authority.remaining_limits()["pending"] == [item.content_hash]
