"""Service-only successor checks: no data acquisition or native research execution."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.application.personal_research import PersonalDatasetBinding, PersonalResearchService
from quantos.application.personal_server_config import (
    CatalogRegistration,
    PersonalServerConfig,
    make_trusted_service,
)
from quantos.contracts.base import sha256_bytes
from quantos.contracts.personal_research import HS300DatasetManifest

REPO = Path(__file__).resolve().parents[1]


def _request():
    return {
        "schema_version": "personal-study-request/v3",
        "idempotency_key": "hs300-proposal",
        "brief": "沪深300/Tushare日频趋势与成交额确认",
        "proposal": {"session_id": "service-only-fixture"},
        "dataset_id": "hs300-fixture",
        "start_date": "2023-01-09",
        "end_date": "2025-12-29",
    }


def _manifest():
    return HS300DatasetManifest(
        dataset_id="hs300-fixture",
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
    )


def test_hs300_default_deny_and_exact_persistent_denominator(tmp_path, monkeypatch):
    from quantos.research import hs300_data

    monkeypatch.setattr(hs300_data, "verify_hs300_binding", lambda binding: None)
    monkeypatch.setattr(PersonalResearchService, "_code_hash", lambda self, **kwargs: "f" * 64)
    item = _manifest()
    service = PersonalResearchService(
        tmp_path, REPO, catalog={item.dataset_id: PersonalDatasetBinding(item, tmp_path, tmp_path)}
    )
    prepared = service.prepare(_request())
    assert prepared["schema_version"] == "personal-study-prepared/v2"
    assert prepared["readiness"] == "READY_FOR_AUTHORIZATION"
    assert prepared["request"]["profile"]["market"] == "CN_HS300_HISTORICAL_PIT"
    assert service.prepare(_request())["task_id"] == prepared["task_id"]
    with pytest.raises(ValidationError):
        service.prepare({**_request(), "approved": True})
    with pytest.raises(PermissionError, match="server-side"):
        service.execute(prepared["task_id"])
    assert service.status(prepared["task_id"])["state"] == "PREPARED"
    result = service.results(prepared["task_id"])
    assert result["planned_denominator"] == 7
    assert [row["seed"] for row in result["rows"] if row["role"] == "random"] == [
        17,
        41,
        73,
        101,
        137,
    ]
    assert all(row["metrics"] is None for row in result["rows"])
    original = (tmp_path / "tasks" / prepared["task_id"] / "prepared.json").read_bytes()
    service.cancel(prepared["task_id"])
    assert service.execute(prepared["task_id"])["state"] == "CANCELLED"
    assert (tmp_path / "tasks" / prepared["task_id"] / "prepared.json").read_bytes() == original


def test_server_config_registers_only_hashed_operator_catalog(tmp_path):
    root = tmp_path / "product"
    root.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(_manifest().canonical_bytes())
    config = PersonalServerConfig(
        product_root=root,
        repo_root=REPO,
        catalog=(
            CatalogRegistration(
                manifest_path=manifest_path,
                manifest_sha256=sha256_bytes(manifest_path.read_bytes()),
                provider_root=tmp_path,
                panel_path=tmp_path / "panel.parquet",
                pit_evidence_path=tmp_path / "pit.json",
            ),
        ),
    )
    (root / "server-config.json").write_bytes(config.canonical_bytes())
    service = make_trusted_service(root, REPO)
    assert service.capabilities()["execution_authorization_configured"] is False
    assert service.data_describe("hs300-fixture")["datasets"][0]["amount_cny_bound"] is True
    assert "provider_root" not in json.dumps(service.data_describe())
    with pytest.raises(ValueError, match="not registered"):
        service.data_describe("client-path")
    manifest_path.write_bytes(b"{}")
    with pytest.raises(Exception, match="hash"):
        make_trusted_service(root, REPO)
    with pytest.raises(ValidationError):
        PersonalServerConfig(product_root=root, repo_root=REPO, authorization_path=tmp_path)


def test_exact_grant_and_preflight_cannot_be_bypassed(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from quantos.application import hs300_worker
    from quantos.application.personal_server_config import HS300ExecutionAuthorization
    from quantos.research import hs300_data

    monkeypatch.setattr(hs300_data, "verify_hs300_binding", lambda binding: None)
    monkeypatch.setattr(PersonalResearchService, "_code_hash", lambda self, **kwargs: "f" * 64)
    manifest = _manifest()
    root = tmp_path / "product"
    root.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes())
    registration = CatalogRegistration(
        manifest_path=manifest_path,
        manifest_sha256=sha256_bytes(manifest_path.read_bytes()),
        provider_root=tmp_path,
        panel_path=tmp_path / "panel.parquet",
        pit_evidence_path=tmp_path / "pit.json",
    )
    config = PersonalServerConfig(product_root=root, repo_root=REPO, catalog=(registration,))
    config_path = root / "server-config.json"
    config_path.write_bytes(config.canonical_bytes())
    service = make_trusted_service(root, REPO)
    prepared_dict = service.prepare(_request())
    prepared = service._prepared(prepared_dict["task_id"])
    approval = tmp_path / "approval.txt"
    approval.write_text("Engineering fixture approval only; no real research execution.")
    grant = HS300ExecutionAuthorization(
        prepared_hash=prepared.content_hash,
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
    grant_path = tmp_path / "grant.json"
    grant_path.write_bytes(grant.canonical_bytes())
    config = config.model_copy(
        update={
            "authorization_path": grant_path,
            "authorization_sha256": sha256_bytes(grant_path.read_bytes()),
        }
    )
    config_path.write_bytes(config.canonical_bytes())

    class DeniedGuard:
        def __init__(self, *args, **kwargs):
            pass

        def preflight(self, prepared):
            raise PermissionError("fixture missing storage quota")

    monkeypatch.setattr(hs300_worker, "GuardedHS300Executor", DeniedGuard)
    authorized_service = make_trusted_service(root, REPO)
    with pytest.raises(PermissionError, match="missing storage quota"):
        authorized_service.execute(prepared.content_hash)
    assert authorized_service.status(prepared.content_hash)["state"] == "PREPARED"
    grant_path.write_bytes(b"{}")
    with pytest.raises(Exception, match="hash"):
        authorized_service.execute(prepared.content_hash)
    assert authorized_service.status(prepared.content_hash)["state"] == "PREPARED"


def test_namespace_worker_reads_state_without_host_pid_reconciliation(tmp_path, monkeypatch):
    import quantos.application.personal_research as module

    service = PersonalResearchService(tmp_path, REPO)
    task = service.prepare(_request())["task_id"]
    service._append(task, "RUNNING", {"pid": 12345, "process_identity": "host-owner"})
    # Inside the worker PID namespace, the live host parent is deliberately invisible.
    monkeypatch.setattr(module, "_process_identity", lambda pid: None)
    events = tmp_path / "tasks" / task / "events"
    before = {path.name: path.read_bytes() for path in events.iterdir()}
    assert service.worker_state(task) == "RUNNING"
    assert {path.name: path.read_bytes() for path in events.iterdir()} == before
    service._append(task, "CANCEL_REQUESTED", {"reason": "fixture"})
    assert service.worker_state(task) == "CANCEL_REQUESTED"
    assert len(list(events.iterdir())) == len(before) + 1


def test_worker_preserves_safe_pit_rejection_across_supervisor_failure(tmp_path, monkeypatch):
    import sys

    from quantos.application import hs300_worker
    from quantos.infrastructure.hosted_storage import StorageRejected
    from quantos.research.personal_qlib import PersonalPITError

    service = PersonalResearchService(tmp_path / "product", REPO)
    task = service.prepare(_request())["task_id"]
    prepared = service._prepared(task)
    output = service.root / "tasks" / task / "execution"
    output.mkdir()
    prepared_path = service.root / "tasks" / task / "prepared.json"
    config_path = tmp_path / "server-config.json"
    config_path.write_text("{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "worker",
            "--config",
            str(config_path),
            "--prepared",
            str(prepared_path),
            "--output",
            str(output),
        ],
    )

    def rejected(*args):
        raise PersonalPITError("unavailable-at-cutoff private detail")

    monkeypatch.setattr(hs300_worker, "_run_worker", rejected)
    assert hs300_worker.main() == 1
    failure_bytes = (output / "worker-failure.json").read_bytes()
    assert b"private detail" not in failure_bytes
    assert json.loads(failure_bytes)["reason_code"] == "PIT_HARD_REJECTION"

    executor = hs300_worker.GuardedHS300Executor(
        {},
        server_config_path=config_path,
        storage_policy_path=tmp_path / "policy.json",
        storage_policy_hash="a" * 64,
        wall_seconds=1,
        growth_bytes=1,
    )
    monkeypatch.setattr(executor, "preflight", lambda prepared: None)
    monkeypatch.setattr(executor, "_guard", lambda: object())

    def failed_supervision(*args, **kwargs):
        raise StorageRejected("STORAGE_JOB_FAILED")

    monkeypatch.setattr(hs300_worker, "supervise_storage_job", failed_supervision)
    with pytest.raises(hs300_worker.HS300WorkerFailure) as failure:
        executor(prepared, output, lambda: False)
    assert failure.value.reason_code == "PIT_HARD_REJECTION"


def test_results_export_hash_bound_full_comparison(tmp_path, monkeypatch):
    from quantos.artifacts.store import ArtifactIntegrityError
    from quantos.contracts.base import canonical_json_bytes
    from quantos.research import hs300_data

    monkeypatch.setattr(hs300_data, "verify_hs300_binding", lambda binding: None)
    monkeypatch.setattr(PersonalResearchService, "_code_hash", lambda self, **kwargs: "f" * 64)

    def incomplete_fixture(prepared, output, cancelled):
        comparison = {
            "prepared_hash": prepared.content_hash,
            "planned_denominator": 7,
            "rows": [
                {"candidate_id": candidate.candidate_id, "metrics": None}
                for candidate in prepared.candidates
            ],
        }
        raw = canonical_json_bytes(comparison)
        (output / "comparison.json").write_bytes(raw)
        return {
            "prepared_hash": prepared.content_hash,
            "run_status": "FAILED",
            "receipts": [],
            "comparison_sha256": sha256_bytes(raw),
        }

    manifest = _manifest()
    service = PersonalResearchService(
        tmp_path,
        REPO,
        catalog={manifest.dataset_id: PersonalDatasetBinding(manifest, tmp_path, tmp_path)},
        execution_authorizer=lambda prepared: "fixture-only",
        executor=incomplete_fixture,
    )
    task = service.prepare(_request())["task_id"]
    assert service.execute(task)["state"] == "FAILED"
    result = service.results(task)
    assert result["comparison"]["planned_denominator"] == 7
    assert result["comparison_sha256"] is not None
    (tmp_path / "tasks" / task / "execution" / "comparison.json").write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError, match="comparison hash"):
        service.results(task)
