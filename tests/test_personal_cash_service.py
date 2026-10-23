"""Cash successor service boundaries; no market data or native execution."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.application.personal_server_config import (
    CatalogRegistrationV3,
    HS300CashExecutionAuthorization,
    PersonalServerConfigV3,
    make_trusted_service,
)
from quantos.contracts.base import sha256_bytes
from quantos.contracts.cash_option_proof import ContinuousCashOptionRule
from quantos.contracts.hs300_cash import (
    BoundArtifact,
    CashRuntimePolicy,
    ClassicOriginReuse,
    HS300CashDatasetManifest,
    SignalReuseSpec,
)
from test_personal_lifecycle_service import REPO, _request, _setup


def _cash_setup(tmp_path, monkeypatch):
    from quantos.research import hs300_cash_runtime

    service, config, path, old_manifest = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(hs300_cash_runtime, "verify_hs300_cash_binding", lambda binding: None)
    monkeypatch.setattr(hs300_cash_runtime, "verify_reused_signal_bindings", lambda *args: {})
    monkeypatch.setattr(
        hs300_cash_runtime,
        "verify_classic_origin",
        lambda *args: {
            "candidate_id": "classic",
            "run_status": "SUCCEEDED",
            "metrics": {"return": 0.01},
        },
    )
    rule = ContinuousCashOptionRule(
        instrument_id="600837.SH",
        source_id="fixture",
        source_sha256="a" * 64,
        window_start="2025-01-01",
        window_end="2025-01-02",
        physical_pages=(1,),
    )
    manifest = HS300CashDatasetManifest.model_validate(
        {
            **old_manifest.model_dump(),
            "schema_version": "personal-dataset/v4",
            "cash_rules": [rule],
            "cash_runtime_policy_hash": CashRuntimePolicy().content_hash,
            "native_source_hashes": {"native": "b" * 64},
        }
    )
    manifest_path = tmp_path / "cash-manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes())
    artifact = BoundArtifact(path="original.json", sha256="c" * 64)
    origin = ClassicOriginReuse(
        origin_root=str(tmp_path),
        prepared=artifact,
        receipt=artifact,
        outcome=artifact,
        dependencies=(artifact,),
        source_refs=(artifact,),
    )
    signals = SignalReuseSpec(
        origin_root=str(tmp_path),
        prepared=artifact,
        checkpoint=artifact,
        dependency_manifest=artifact,
        compiler_originals={"compiler": artifact},
        signal_files={"classic": artifact},
        compiler_dependency_hashes={"compiler": "d" * 64},
        panel_sha256=manifest.panel_sha256,
    )
    origin_path = tmp_path / "classic.json"
    origin_path.write_bytes(origin.canonical_bytes())
    signals_path = tmp_path / "signals.json"
    signals_path.write_bytes(signals.canonical_bytes())
    registration = CatalogRegistrationV3.model_validate(
        {
            **config.catalog[0].model_dump(),
            "schema_version": "personal-catalog-registration/v3",
            "manifest_path": manifest_path,
            "manifest_sha256": sha256_bytes(manifest.canonical_bytes()),
            "cash_rules_path": tmp_path / "cash-rules.json",
            "classic_origin_path": origin_path,
            "signal_reuse_spec_path": signals_path,
        }
    )
    cash_config = PersonalServerConfigV3(
        product_root=service.root,
        repo_root=REPO,
        catalog=(registration,),
    )
    path.write_bytes(cash_config.canonical_bytes())
    request = {**_request(), "schema_version": "personal-study-request/v5"}
    return make_trusted_service(service.root, REPO), cash_config, path, manifest, request


def test_cash_default_denied_persistent_and_unobserved(tmp_path, monkeypatch):
    from quantos.application.hs300_worker import _read_prepared

    service, _, _, _, request = _cash_setup(tmp_path, monkeypatch)
    prepared = service.prepare(request)
    task = prepared["task_id"]
    assert prepared["schema_version"] == "personal-study-prepared/v4"
    assert prepared["readiness"] == "READY_FOR_AUTHORIZATION"
    assert service.prepare(request)["task_id"] == task
    assert _read_prepared(service._prepared(task).canonical_bytes()).content_hash == task
    with pytest.raises(ValidationError):
        service.prepare({**request, "approved": True})
    with pytest.raises(PermissionError, match="server-side"):
        service.execute(task)
    assert all(
        row["native_boundary_status"] == "NOT_OBSERVED" for row in service.results(task)["rows"]
    )
    service.cancel(task)
    assert service.execute(task)["state"] == "CANCELLED"


def test_cash_origin_is_read_verified_without_rewriting_receipt(tmp_path, monkeypatch):
    service, _, _, _, request = _cash_setup(tmp_path, monkeypatch)
    task = service.prepare(request)["task_id"]
    prepared = service._prepared(task)

    def execute(item, output, cancelled):
        return {
            "prepared_hash": item.content_hash,
            "run_status": "FAILED",
            "receipts": [],
            "origin_reuse": [
                {"candidate_id": "classic", "origin_hash": item.origin_reuse[0].content_hash}
            ],
        }

    service._authorizer = lambda item: "fixture-only"
    service._executor = execute
    assert service.execute(task)["state"] == "FAILED"
    results = service.results(task)
    assert results["planned_denominator"] == 7
    assert results["reused_denominator"] == 1
    assert results["rows"][1]["run_status"] == "REUSED_ORIGIN"
    assert results["rows"][1]["origin_reuse"] == prepared.origin_reuse[0].model_dump(mode="json")
    assert results["rows"][0]["metrics"] is None
    assert not (service.root / "tasks" / task / "execution" / "classic").exists()
    from quantos.research import hs300_cash_runtime

    def changed(*args):
        raise ValueError("origin changed")

    monkeypatch.setattr(hs300_cash_runtime, "verify_classic_origin", changed)
    with pytest.raises(ValueError, match="origin changed"):
        service.results(task)


def test_cash_prepare_rejects_broken_signal_binding(tmp_path, monkeypatch):
    service, _, _, _, request = _cash_setup(tmp_path, monkeypatch)
    from quantos.research import hs300_cash_runtime

    def missing_original(*args):
        raise ValueError("missing original signal")

    monkeypatch.setattr(hs300_cash_runtime, "verify_reused_signal_bindings", missing_original)
    with pytest.raises(ValueError, match="missing original signal"):
        service.prepare(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_backtests", 7),
        ("wall_seconds", 3601),
        ("growth_bytes", 4 * 1024**3 + 1),
        ("validation_calls", 1),
    ],
)
def test_cash_grant_retains_hard_budget(tmp_path, monkeypatch, field, value):
    service, _, _, manifest, request = _cash_setup(tmp_path, monkeypatch)
    task = service.prepare(request)["task_id"]
    item = service._prepared(task)
    values = dict(
        prepared_hash=task,
        code_hash=item.code_hash,
        dataset_manifest_hash=manifest.content_hash,
        profile_hash=item.request.profile.content_hash,
        candidate_ids=tuple(c.candidate_id for c in item.candidates),
        approval_evidence_path=tmp_path / "approval",
        approval_evidence_sha256="a" * 64,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        storage_policy_path=tmp_path / "policy",
        storage_policy_hash="b" * 64,
        wall_seconds=3600,
        growth_bytes=4 * 1024**3,
        lifecycle_manifest_hash=manifest.lifecycle_manifest_hash,
        lifecycle_source_hashes=manifest.lifecycle_source_hashes,
        native_boundary_policy_hash=manifest.native_boundary_policy_hash,
        cash_runtime_policy_hash=manifest.cash_runtime_policy_hash,
        cash_rule_hashes=tuple(rule.content_hash for rule in manifest.cash_rules),
        native_source_hashes=manifest.native_source_hashes,
        classic_origin_hash=item.origin_reuse[0].content_hash,
        signal_reuse_hash=item.signal_reuse.content_hash,
    )
    values[field] = value
    with pytest.raises(ValidationError):
        HS300CashExecutionAuthorization(**values)
