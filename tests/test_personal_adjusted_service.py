"""Adjusted-unit service authority boundaries; no market or native execution."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.application.personal_server_config import (
    CatalogRegistrationV4,
    HS300AdjustedExecutionAuthorization,
    HS300CashExecutionAuthorization,
    PersonalServerConfigV4,
    make_trusted_service,
)
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hs300_adjusted import (
    AdjustedUnitFactBundle,
    AdjustedUnitPolicy,
    FixedNativeQuoteBinding,
    HS300AdjustedDatasetManifest,
)
from test_personal_cash_service import _cash_setup
from test_personal_lifecycle_service import REPO


def _adjusted_setup(tmp_path, monkeypatch):
    from quantos.research import hs300_adjusted_runtime

    service, config, path, old_manifest, request = _cash_setup(tmp_path, monkeypatch)
    observed = []

    def verify(binding):
        observed.append(binding)
        assert binding.adjusted_facts_path == tmp_path / "adjusted-facts.json"
        assert binding.manifest.adjusted_facts.content_hash == facts.content_hash

    monkeypatch.setattr(hs300_adjusted_runtime, "verify_hs300_adjusted_binding", verify)
    facts = AdjustedUnitFactBundle.model_validate(
        {
            "vendor_semantics_source_ids": ["vendor-109", "vendor-146"],
            "official_sources": [
                *(
                    {
                        "source_id": f"vendor-{document}",
                        "kind": "OFFICIAL_COMPANY",
                        "logical_path": f"vendor-{document}.html",
                        "sha256": "7" * 64,
                        "observed_at": "2026-11-01T00:00:00Z",
                        "url": f"https://tushare.pro/document/2?doc_id={document}",
                    }
                    for document in ("109", "146")
                ),
                {
                    "source_id": "issuer-fixture",
                    "kind": "OFFICIAL_COMPANY",
                    "logical_path": "issuer.pdf",
                    "sha256": "1" * 64,
                    "observed_at": "2026-11-01T00:00:00Z",
                },
            ],
            "dividends": [
                {
                    "instrument_id": "600837.SH",
                    "source_id": "issuer-fixture",
                    "source_rule_sha256": "2" * 64,
                    "record_date": "2023-07-27",
                    "ex_date": "2023-07-28",
                    "pay_date": "2023-07-28",
                    "cash_div_tax": "0.21",
                }
            ],
            "mergers": [
                {
                    "instrument_id": "600837.SH",
                    "issuer_instrument_id": "601211.SH",
                    "source_id": "issuer-fixture",
                    "source_rule_sha256": "3" * 64,
                    "record_date": "2025-03-03",
                    "ratio": "0.62",
                    "boundary_date": "2025-02-06",
                    "event_ids": ["issuer-fixture-merger"],
                }
            ],
        }
    )
    facts_path = tmp_path / "adjusted-facts.json"
    facts_path.write_bytes(facts.canonical_bytes())
    manifest = HS300AdjustedDatasetManifest.model_validate(
        {
            **old_manifest.model_dump(),
            "schema_version": "personal-dataset/v5",
            "adjusted_facts": facts,
            "adjusted_unit_policy_hash": AdjustedUnitPolicy().content_hash,
            "adjusted_runtime_source_hashes": {"quote-loader": "4" * 64},
            "future_quote_binding": FixedNativeQuoteBinding(
                qlib_view_hash=old_manifest.qlib_view_hash,
                calendar_sha256="5" * 64,
                quote_files={"features/sh600837/close.day.bin": "6" * 64},
                sessions_by_instrument={"600837.SH": ("2025-02-06", "2025-03-03")},
            ),
        }
    )
    manifest_path = tmp_path / "adjusted-manifest.json"
    manifest_path.write_bytes(manifest.canonical_bytes())
    registration = CatalogRegistrationV4.model_validate(
        {
            **config.catalog[0].model_dump(),
            "schema_version": "personal-catalog-registration/v4",
            "manifest_path": manifest_path,
            "manifest_sha256": sha256_bytes(manifest.canonical_bytes()),
            "adjusted_facts_path": facts_path,
        }
    )
    config = PersonalServerConfigV4(
        product_root=service.root, repo_root=REPO, catalog=(registration,)
    )
    path.write_bytes(config.canonical_bytes())
    request = {**request, "schema_version": "personal-study-request/v6"}
    return make_trusted_service(service.root, REPO), config, path, manifest, request, observed


def test_adjusted_prepare_verifies_bindings_and_reloads_without_authority(tmp_path, monkeypatch):
    from quantos.application.hs300_worker import _read_prepared
    from quantos.research import hs300_adjusted_runtime, hs300_cash_runtime

    service, _, _, _, request, observed = _adjusted_setup(tmp_path, monkeypatch)
    prepared = service.prepare(request)
    task = prepared["task_id"]
    assert len(observed) == 1
    assert prepared["schema_version"] == "personal-study-prepared/v5"
    assert prepared["request"]["profile"]["schema_version"].endswith("/v3")
    assert prepared["readiness"] == "READY_FOR_AUTHORIZATION"
    assert len(prepared["candidates"]) == 7
    assert _read_prepared(service._prepared(task).canonical_bytes()).content_hash == task
    assert make_trusted_service(service.root, REPO).status(task)["state"] == "PREPARED"
    with pytest.raises(PermissionError, match="server-side"):
        service.execute(task)
    assert all(row["metrics"] is None for row in service.results(task)["rows"])
    with pytest.raises(ValueError, match="versions disagree"):
        service.prepare({**request, "schema_version": "personal-study-request/v5"})

    def missing_signal(*args):
        raise ValueError("old signal identity changed")

    monkeypatch.setattr(hs300_cash_runtime, "verify_reused_signal_bindings", missing_signal)
    with pytest.raises(ValueError, match="signal identity"):
        service.prepare(request)
    monkeypatch.setattr(hs300_cash_runtime, "verify_reused_signal_bindings", lambda *args: {})

    def missing_facts(binding):
        raise ValueError("adjusted fact original changed")

    monkeypatch.setattr(hs300_adjusted_runtime, "verify_hs300_adjusted_binding", missing_facts)
    blocked = service.prepare({**request, "idempotency_key": "missing-adjusted-facts"})
    assert blocked["readiness"] == "BLOCKED"
    with pytest.raises(PermissionError, match="blocked"):
        service.execute(blocked["task_id"])


@pytest.mark.parametrize(
    "mismatch", ["legacy-grant", "facts", "policy", "runtime", "quote", "guard"]
)
def test_adjusted_grant_binds_every_new_identity_before_preflight(tmp_path, monkeypatch, mismatch):
    from quantos.application import hs300_worker

    service, config, path, manifest, request, _ = _adjusted_setup(tmp_path, monkeypatch)
    task = service.prepare(request)["task_id"]
    item = service._prepared(task)
    approval = tmp_path / "approval.txt"
    approval.write_text("Service fixture; no scientific or native execution.")
    fields = dict(
        prepared_hash=task,
        code_hash=item.code_hash,
        dataset_manifest_hash=manifest.content_hash,
        profile_hash=item.request.profile.content_hash,
        candidate_ids=tuple(c.candidate_id for c in item.candidates),
        approval_evidence_path=approval,
        approval_evidence_sha256=sha256_bytes(approval.read_bytes()),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        storage_policy_path=tmp_path / "policy.json",
        storage_policy_hash="a" * 64,
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
    if mismatch == "legacy-grant":
        grant = HS300CashExecutionAuthorization(**fields)
    else:
        values = {
            "adjusted_unit_policy_hash": manifest.adjusted_unit_policy_hash,
            "adjusted_facts_hash": manifest.adjusted_facts.content_hash,
            "adjusted_runtime_source_hashes": manifest.adjusted_runtime_source_hashes,
            "future_quote_binding_hash": manifest.future_quote_binding.content_hash,
        }
        field = {
            "facts": "adjusted_facts_hash",
            "policy": "adjusted_unit_policy_hash",
            "runtime": "adjusted_runtime_source_hashes",
            "quote": "future_quote_binding_hash",
        }.get(mismatch)
        if field:
            values[field] = {"changed": "e" * 64} if mismatch == "runtime" else "e" * 64
        grant = HS300AdjustedExecutionAuthorization(**fields, **values)
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
            assert mismatch == "guard", "changed identity must not reach resource preflight"
            raise PermissionError("fixture storage gate")

    monkeypatch.setattr(hs300_worker, "GuardedHS300Executor", DeniedGuard)
    active = make_trusted_service(service.root, REPO)
    with pytest.raises((ValidationError, PermissionError)):
        active.execute(task)
    assert active.status(task)["state"] == "PREPARED"
