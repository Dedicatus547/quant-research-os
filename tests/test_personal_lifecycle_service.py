"""Lifecycle service and grant boundaries only; no market/native backtest execution."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.application.personal_research import PersonalResearchService
from quantos.application.personal_server_config import (
    CatalogRegistrationV2,
    HS300ExecutionAuthorization,
    HS300LifecycleExecutionAuthorization,
    PersonalServerConfigV2,
    make_trusted_service,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hs300_lifecycle import HS300LifecycleDatasetManifest

REPO = Path(__file__).resolve().parents[1]


def _request():
    return {
        "schema_version": "personal-study-request/v4",
        "idempotency_key": "lifecycle-fixture",
        "brief": "Lifecycle structural classification; native boundary hard stop",
        "proposal": {"session_id": "engineering-fixture-only"},
        "dataset_id": "lifecycle-fixture",
        "start_date": "2023-01-09",
        "end_date": "2025-12-29",
    }


def _setup(tmp_path, monkeypatch):
    from quantos.research import hs300_lifecycle_data

    monkeypatch.setattr(
        hs300_lifecycle_data, "verify_hs300_lifecycle_binding", lambda binding: None
    )
    monkeypatch.setattr(PersonalResearchService, "_code_hash", lambda self, **kwargs: "f" * 64)
    manifest = HS300LifecycleDatasetManifest(
        dataset_id="lifecycle-fixture",
        kind="synthetic",
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        panel_sha256="c" * 64,
        pit_evidence_hash="d" * 64,
        warmup_start=date(2022, 11, 1),
        start_date=date(2023, 1, 9),
        end_date=date(2025, 12, 29),
        market_source="SYNTHETIC_FIXTURE",
        source_vintage="synthetic",
        exposure="synthetic",
        qlib_files={"calendars/day.txt": "e" * 64},
        snapshot_manifest_sha256="f" * 64,
        view_manifest_sha256="a" * 64,
        lifecycle_manifest_hash="b" * 64,
        lifecycle_source_hashes={"structural-source": "c" * 64},
        native_boundary_policy_hash="d" * 64,
    )
    root = tmp_path / "product"
    root.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes())
    config = PersonalServerConfigV2(
        product_root=root,
        repo_root=REPO,
        catalog=(
            CatalogRegistrationV2(
                manifest_path=manifest_path,
                manifest_sha256=sha256_bytes(manifest_path.read_bytes()),
                provider_root=tmp_path,
                panel_path=tmp_path / "panel.parquet",
                pit_evidence_path=tmp_path / "pit.json",
                lifecycle_path=tmp_path / "lifecycle.json",
            ),
        ),
    )
    path = root / "server-config.json"
    path.write_bytes(config.canonical_bytes())
    return make_trusted_service(root, REPO), config, path, manifest


def test_lifecycle_ready_is_unobserved_and_never_authorized(tmp_path, monkeypatch):
    from quantos.application.hs300_worker import _read_prepared

    service, _, _, _ = _setup(tmp_path, monkeypatch)
    prepared = service.prepare(_request())
    task = prepared["task_id"]
    assert prepared["readiness"] == "READY_FOR_AUTHORIZATION"
    assert prepared["schema_version"] == "personal-study-prepared/v3"
    assert service.prepare(_request())["task_id"] == task
    assert _read_prepared(service._prepared(task).canonical_bytes()).content_hash == task
    original = (service.root / "tasks" / task / "prepared.json").read_bytes()
    with pytest.raises(ValidationError):
        service.prepare({**_request(), "approved": True})
    with pytest.raises(ValueError, match="versions disagree"):
        service.prepare({**_request(), "schema_version": "personal-study-request/v3"})
    with pytest.raises(PermissionError, match="server-side"):
        service.execute(task)
    results = service.results(task)
    assert results["planned_denominator"] == 7
    assert all(row["native_boundary_status"] == "NOT_OBSERVED" for row in results["rows"])
    assert all(row["boundary_receipts"] is None for row in results["rows"])
    assert not service.capabilities()["execution_authorization_configured"]
    service.cancel(task)
    assert service.execute(task)["state"] == "CANCELLED"
    assert (service.root / "tasks" / task / "prepared.json").read_bytes() == original


def test_lifecycle_source_failure_stays_blocked(tmp_path, monkeypatch):
    from quantos.research import hs300_lifecycle_data

    service, _, _, _ = _setup(tmp_path, monkeypatch)

    def missing(binding):
        raise ValueError("missing source original")

    monkeypatch.setattr(hs300_lifecycle_data, "verify_hs300_lifecycle_binding", missing)
    prepared = service.prepare(_request())
    assert prepared["readiness"] == "BLOCKED"
    with pytest.raises(PermissionError, match="blocked"):
        service.execute(prepared["task_id"])


@pytest.mark.parametrize("mismatch", ["legacy-grant", "bundle", "sources", "policy", "guard"])
def test_lifecycle_exact_grant_and_preflight(tmp_path, monkeypatch, mismatch):
    from quantos.application import hs300_worker

    service, config, path, manifest = _setup(tmp_path, monkeypatch)
    task = service.prepare(_request())["task_id"]
    prepared = service._prepared(task)
    approval = tmp_path / "approval.txt"
    approval.write_text("Engineering fixture only; no real seven-account execution.")
    fields = dict(
        prepared_hash=task,
        code_hash=prepared.code_hash,
        dataset_manifest_hash=manifest.content_hash,
        profile_hash=prepared.request.profile.content_hash,
        candidate_ids=tuple(c.candidate_id for c in prepared.candidates),
        approval_evidence_path=approval,
        approval_evidence_sha256=sha256_bytes(approval.read_bytes()),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        storage_policy_path=tmp_path / "policy.json",
        storage_policy_hash="a" * 64,
        wall_seconds=1,
        growth_bytes=1,
    )
    if mismatch == "legacy-grant":
        grant = HS300ExecutionAuthorization(**fields)
    else:
        grant = HS300LifecycleExecutionAuthorization(
            **fields,
            lifecycle_manifest_hash="e" * 64
            if mismatch == "bundle"
            else manifest.lifecycle_manifest_hash,
            lifecycle_source_hashes={"changed": "e" * 64}
            if mismatch == "sources"
            else manifest.lifecycle_source_hashes,
            native_boundary_policy_hash="e" * 64
            if mismatch == "policy"
            else manifest.native_boundary_policy_hash,
        )
    grant_path = tmp_path / "grant.json"
    grant_path.write_bytes(grant.canonical_bytes())
    config = config.model_copy(
        update={
            "authorization_path": grant_path,
            "authorization_sha256": sha256_bytes(grant_path.read_bytes()),
        }
    )
    path.write_bytes(config.canonical_bytes())

    class DeniedGuard:
        def __init__(self, *args, **kwargs):
            pass

        def preflight(self, prepared):
            assert mismatch == "guard", "mismatched grant must not reach resource preflight"
            raise PermissionError("fixture guard denies")

    monkeypatch.setattr(hs300_worker, "GuardedHS300Executor", DeniedGuard)
    active = make_trusted_service(service.root, REPO)
    with pytest.raises((ValidationError, PermissionError)):
        active.execute(task)
    assert active.status(task)["state"] == "PREPARED"


def test_lifecycle_failed_native_boundary_remains_in_full_denominator(tmp_path, monkeypatch):
    from quantos.artifacts.store import ArtifactIntegrityError

    service, _, _, _ = _setup(tmp_path, monkeypatch)

    def fixture_executor(prepared, output, cancelled):
        directory = output / "main"
        directory.mkdir()
        boundary = canonical_json_bytes(
            {"status": "HARD_STOP_EXPOSURE", "native_observation": True}
        )
        (directory / "boundary.json").write_bytes(boundary)
        receipt = {
            "prepared_hash": prepared.content_hash,
            "candidate_id": "main",
            "run_status": "FAILED",
            "metrics": None,
            "native_boundary_status": "HARD_STOP_EXPOSURE",
            "native_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
            "boundary_receipts": [{"filename": "boundary.json", "sha256": sha256_bytes(boundary)}],
            "partial_native_artifacts": {},
            "files": {"boundary.json": sha256_bytes(boundary)},
        }
        raw = canonical_json_bytes(receipt)
        (directory / "receipt.json").write_bytes(raw)
        return {
            "prepared_hash": prepared.content_hash,
            "run_status": "FAILED",
            "receipts": [
                {"candidate_id": "main", "run_status": "FAILED", "receipt_hash": sha256_bytes(raw)}
            ],
        }

    service._executor = fixture_executor
    service._authorizer = lambda prepared: "fixture-only-no-real-execution"
    task = service.prepare(_request())["task_id"]
    assert service.execute(task)["state"] == "FAILED"
    results = service.results(task)
    assert results["planned_denominator"] == 7
    assert results["succeeded_denominator"] == 0
    assert results["rows"][0]["native_boundary_status"] == "HARD_STOP_EXPOSURE"
    assert all(row["native_boundary_status"] == "NOT_OBSERVED" for row in results["rows"][1:])
    (service.root / "tasks" / task / "execution" / "main" / "boundary.json").write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError):
        service.results(task)
