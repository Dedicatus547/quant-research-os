"""Trusted configuration rechecks and cited feedback; synthetic receipts only."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from quantos.application import personal_product as module
from quantos.application import personal_server_config as server
from quantos.application.personal_observation import SnapshotArrival
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.personal_strategy import (
    PersonalResearchScope,
    PreparedStrategyStudy,
    StrategyStudyRequest,
)
from quantos.infrastructure import hosted_storage
from test_personal_complete import request
from test_personal_product_boundaries import core as core
from test_personal_product_boundaries import product as product


@pytest.fixture
def configured(product, monkeypatch):
    core = product.core
    root = core.root
    root.mkdir(parents=True, exist_ok=True)
    approval = root / "synthetic-approval.txt"
    approval.write_text("Unit test scope; no real execution authority")
    forward = product.authority.scope.model_copy(
        update={"approval_evidence_sha256": sha256_file(approval)}
    )
    research = PersonalResearchScope(
        purpose="SYNTHETIC_ENGINEERING",
        dataset_hash=forward.allowed_dataset_hashes[0],
        policy_hash=forward.policy_hash,
        runtime_hash=forward.runtime_hash,
        allowed_strategy_hashes=(forward.strategy_hash,),
        start_date=forward.start_date,
        end_date=forward.end_date,
        max_attempts=2,
        max_native_accounts=2,
        wall_seconds=10,
        growth_bytes=1000,
        expires_at=forward.expires_at,
        approval_evidence_sha256=sha256_file(approval),
    )
    policy = root / "policy.json"
    policy.write_text(
        json.dumps(
            {key: str(root) for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file")}
        )
    )
    scopes = {}
    for name, scope in (("forward", forward), ("research", research)):
        path = root / (name + ".json")
        path.write_bytes(scope.canonical_bytes())
        scopes[name + "_scope"] = server.PersonalScopeRegistration(
            scope_path=path,
            scope_sha256=sha256_file(path),
            approval_evidence_path=approval,
            storage_policy_path=policy,
            storage_policy_sha256=sha256_file(policy),
        )
    evidence = root / "source.json"
    evidence.write_text('{"synthetic":true}')
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    arrival = SnapshotArrival(
        acquired_at=moment,
        source_visible_at=moment,
        received_at=moment,
        evidence_sha256=sha256_file(evidence),
        corporate_actions="KNOWN_NONE_IN_SCOPE",
    )
    metadata = root / "arrival.json"
    metadata.write_bytes(arrival.canonical_bytes())
    registration = server.SnapshotArrivalRegistration(
        dataset_id="fixture",
        metadata_path=metadata,
        metadata_sha256=sha256_file(metadata),
        evidence_path=evidence,
    )
    config = server.PersonalServerConfigV6(
        product_root=root, repo_root=core.repo_root, snapshot_arrivals=(registration,), **scopes
    )
    config_path = root / "config.json"
    config_path.write_bytes(config.canonical_bytes())
    calls = []

    class Guard:
        def __init__(self, policy):
            assert policy.evidence_root == root

        def check(self, amount):
            calls.append(("capacity", amount))

        def require_lease(self):
            calls.append(("lease",))

    monkeypatch.setattr(hosted_storage, "StoragePolicy", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(hosted_storage, "StorageGuard", Guard)
    return SimpleNamespace(core=core, config=config, path=config_path, calls=calls)


@pytest.mark.parametrize("worker_mode", [True, False])
def test_configured_authority_rechecks_exact_inputs_and_active_lease(configured, worker_mode):
    f = configured
    module.configure_personal_product(f.core, f.config, f.path, worker_mode=worker_mode)
    product = module.personal_product(f.core)
    assert product.observations.metadata["fixture"].corporate_actions == "KNOWN_NONE_IN_SCOPE"
    assert (product.dispatcher is None) == worker_mode
    for authority in (product.forward_authority, f.core.strategy_authority):
        authority.resource_check(authority.scope)
    assert f.calls == [("capacity", 1000), ("lease",)] * 2
    changed = f.config.model_copy(update={"forward_scope": None})
    f.path.write_bytes(changed.canonical_bytes())
    with pytest.raises(PermissionError, match="config changed"):
        product.forward_authority.resource_check(product.forward_authority.scope)
    assert len(f.calls) == 4


@pytest.mark.parametrize(
    "attack", ["scope", "approval", "policy", "arrival", "duplicate", "unknown"]
)
def test_config_tampering_cannot_reuse_prior_in_memory_authority(configured, attack):
    f = configured
    config = f.config
    if attack in {"duplicate", "unknown"}:
        registration = config.snapshot_arrivals[0]
        arrivals = (
            (registration, registration)
            if attack == "duplicate"
            else (registration.model_copy(update={"dataset_id": "unregistered"}),)
        )
        config = config.model_copy(update={"snapshot_arrivals": arrivals})
        with pytest.raises(ValueError, match="unique dataset"):
            module.configure_personal_product(f.core, config, f.path, worker_mode=True)
        return
    module.configure_personal_product(f.core, config, f.path, worker_mode=True)
    authority = module.personal_product(f.core).forward_authority
    path = {
        "scope": config.forward_scope.scope_path,
        "approval": config.forward_scope.approval_evidence_path,
        "policy": config.forward_scope.storage_policy_path,
        "arrival": config.snapshot_arrivals[0].metadata_path,
    }[attack]
    path.write_text("changed")
    with pytest.raises((ValueError, ArtifactIntegrityError)):
        if attack == "arrival":
            module.configure_personal_product(f.core, config, f.path, worker_mode=True)
        else:
            authority.resource_check(authority.scope)
    assert not f.calls


@pytest.fixture
def feedback(core):
    study_request = StrategyStudyRequest.model_validate(request(core.catalog["fixture"]))
    prepared = PreparedStrategyStudy(
        request=study_request,
        code_hash="a" * 64,
        dataset_hash="b" * 64,
        strategy_hashes={c.candidate_id: c.strategy.content_hash for c in study_request.candidates},
        policy_hash=study_request.policy.content_hash,
        readiness="READY_FOR_AUTHORIZATION",
        gaps=(),
        resolved={},
    )
    task = prepared.content_hash
    receipt = core.root / "tasks" / task / "execution/price/receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"run_status":"FAILED","metrics":null,"synthetic":true}')
    result = {
        "state": "FAILED",
        "rows": [
            {"candidate_id": "price", "receipt_sha256": sha256_file(receipt)},
            {"candidate_id": "reverse"},
        ],
        "event": {"at": "2024-02-15T00:00:00Z"},
        "limits": ["Synthetic missing metrics"],
    }
    core._prepared = lambda _: prepared
    core.results = lambda _: result
    return SimpleNamespace(
        core=core, product=module.personal_product(core), task=task, receipt=receipt, result=result
    )


def test_feedback_cites_original_failure_and_null_metrics_without_promoting_prose(feedback):
    f = feedback
    result = f.product.feedback(f.task, "Synthetic interpretation", "STOP", "No native result")
    raw = json.loads((f.core.repo_root / result["reference"]["path"]).read_bytes())
    assert [o["value"] for o in raw["observations"]] == ["FAILED", None]
    assert raw["draft"]["tags"][-1] == "engineering"
    assert raw["draft"]["annotations"][0]["kind"] == "MODEL_INTERPRETATION"
    assert raw["qualification_granted"] is False and raw["new_execution"] is False
    assert f.product.feedback(f.task, "Synthetic interpretation", "STOP", "No native result")[
        "reused"
    ]


@pytest.mark.parametrize(
    "attack,match",
    [
        ("pending", "settled terminal"),
        ("absent", "no completed"),
        ("tamper", "identity"),
        ("legacy", "retained v6"),
    ],
)
def test_feedback_requires_settled_originals(feedback, attack, match):
    f = feedback
    if attack == "pending":
        f.result["state"] = "RUNNING"
    elif attack == "absent":
        f.result["rows"] = []
    elif attack == "tamper":
        f.receipt.write_text('{"run_status":"SUCCEEDED","metrics":{}}')
    else:
        f.core._prepared = lambda _: None
    with pytest.raises((ValueError, ArtifactIntegrityError), match=match):
        f.product.feedback(f.task, "Synthetic interpretation", "STOP", "No native result")
