"""Product composition guards; synthetic authorities never grant native execution."""

from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from tests.test_personal_research import service

from quantos.application.personal_product import PersonalProductServices, personal_product
from quantos.application.personal_strategy_authority import ScopeReservationMissing
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.forward import PersonalForwardScopeV2
from quantos.research.personal_signal import dataset_binding_hash


@pytest.fixture
def core():
    # Cited memory requires the product root to be inside its repository.
    scratch = Path(__file__).resolve().parents[1] / ".pytest_cache"
    scratch.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="product-boundaries-", dir=scratch) as directory:
        yield service(Path(directory))


@pytest.fixture
def product(core):
    shadow_plan = {"strategy_hash": "d" * 64, "policy_hash": "e" * 64}
    scope = PersonalForwardScopeV2(
        purpose="SYNTHETIC_ENGINEERING",
        strategy_hash="d" * 64,
        policy_hash="e" * 64,
        runtime_hash="f" * 64,
        allowed_dataset_hashes=(dataset_binding_hash(core.catalog["fixture"]),),
        start_date=date(2024, 2, 1),
        end_date=date(2024, 2, 16),
        max_observations=2,
        max_native_steps=2,
        wall_seconds=10,
        growth_bytes=1000,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        approval_evidence_sha256="0" * 64,
        max_dataset_successors=1,
        observation_id="1" * 64,
        shadow_id=sha256_bytes(canonical_json_bytes(shadow_plan)),
        per_job_wall_seconds=10,
        per_job_growth_bytes=1000,
    )
    calls = []
    authority = SimpleNamespace(
        scope=scope,
        authorize=lambda **kwargs: calls.append(kwargs) or "synthetic-reservation",
        reservation=lambda _: {"settled": False},
        record=lambda *args: calls.append(args),
    )
    app = PersonalProductServices(core, forward_authority=authority)
    return SimpleNamespace(
        app=app, core=core, authority=authority, calls=calls, shadow_plan=shadow_plan
    )


def observation_context(product, **changes):
    manifest = product.core.catalog["fixture"].manifest
    return {
        "observation_id": "1" * 64,
        "dataset_id": "fixture",
        "plan": {
            "observation_id": "1" * 64,
            "strategy_hash": "d" * 64,
            "policy_hash": "e" * 64,
            **changes,
        },
        "input": {
            "dataset_manifest_hash": manifest.content_hash,
            "dataset_binding_hash": dataset_binding_hash(product.core.catalog["fixture"]),
            "kind": "synthetic",
        },
        "day": "2024-02-05",
    }


def test_same_strategy_cannot_substitute_another_frozen_observation(product):
    authorize = product.app.observations.authorizer
    with pytest.raises(PermissionError, match="outside the frozen forward scope"):
        authorize(observation_context(product, observation_id="2" * 64))
    assert product.calls == []
    assert authorize(observation_context(product)) == "synthetic-reservation"
    recorded = product.calls[0]
    assert recorded["operation"] == "observe"
    assert recorded["dataset_hash"] == dataset_binding_hash(product.core.catalog["fixture"])
    assert recorded["runtime_hash"] == product.app.runtime_hash


def test_same_strategy_cannot_substitute_another_shadow_account(product):
    payload = {
        "dataset_hash": dataset_binding_hash(product.core.catalog["fixture"]),
        "execution_date": "2024-02-06",
        "observation_record_hash": "3" * 64,
    }
    authorize = product.app.shadow.authorizer
    with pytest.raises(PermissionError, match="outside the frozen forward scope"):
        authorize({**product.shadow_plan, "different_origin": True}, "shadow_advance", payload)
    assert product.calls == []
    assert authorize(product.shadow_plan, "shadow_advance", payload) == "synthetic-reservation"
    assert product.calls[0]["day"] == date(2024, 2, 6)
    assert product.calls[0]["kind"] == "synthetic"


@pytest.mark.parametrize("operation", ["observation_observe", "shadow_advance"])
@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "UNKNOWN"])
def test_in_process_result_never_invents_a_supervisor_exit(product, operation, state):
    payload = (
        {"observation_id": "1" * 64, "day": "2024-02-05", "dataset_id": "fixture"}
        if operation == "observation_observe"
        else {
            "shadow_id": product.authority.scope.shadow_id,
            "execution_date": "2024-02-06",
            "observation_record_hash": "3" * 64,
            "execution_dataset_id": "fixture",
        }
    )
    result = (
        {"status": "EMITTED" if state == "SUCCEEDED" else state}
        if operation == "observation_observe"
        else {"native_receipt": {"run_status": state}}
    )
    product.app.record_forward_result(operation, payload, result)
    record = product.calls[0]
    assert record[2] == state
    assert record[3]["result_hash"] == sha256_bytes(canonical_json_bytes(result))
    assert record[3]["measurement"] == (
        "IN_PROCESS_COMPLETION_ONLY; supervisor exit settled by dispatcher"
    )
    assert "exit_reference" not in record[3]


@pytest.mark.parametrize("reservation", ["missing", "settled", "empty"])
def test_result_without_open_reservation_does_not_spend_or_reopen_scope(product, reservation):
    def lookup(_identity):
        if reservation == "missing":
            raise ScopeReservationMissing("synthetic absent reservation")
        return {"settled": True} if reservation == "settled" else None

    product.authority.reservation = lookup
    product.app.record_forward_result(
        "observation_observe",
        {"observation_id": "1" * 64, "day": "2024-02-05", "dataset_id": "fixture"},
        {"status": "EMITTED"},
    )
    assert product.calls == []


def test_cached_product_does_not_grant_scope_and_recovery_does_not_reissue(core):
    app = personal_product(core)
    assert personal_product(core) is app
    assert app.scope_status() == {
        "research": None,
        "forward": None,
        "execution_permission_from_tool_arguments": False,
    }
    with pytest.raises(ValueError, match="no configured bounded scope"):
        app.stop("forward", "synthetic stop")
    core.status = lambda _: {"state": "UNKNOWN"}
    core.results = lambda _: {"rows": []}
    report = app.reconcile("synthetic-task")
    assert report["state"] == "UNKNOWN"
    assert report["reissued"] is False
    assert report["real_exit_invented"] is False
    assert "reconciliation" in report["next_action"]
    assert app.runtime_hash
    assert core.repo_root == Path(__file__).resolve().parents[1]
