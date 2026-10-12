"""Real immutable signal export/adoption on one typed synthetic row; no Qlib query."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_discovery_variant_regression import pit_fixture

from quantos.application.autonomous_execution import resolve_experiment
from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.signal import SignalArtifactManifest, SignalRow
from quantos.research.qlib import QlibResearchError
from quantos.research.qlib import signal as signal_module
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.pit_evidence import pit_transform_lineage_hash


@pytest.fixture
def original_signal(staged, monkeypatch):
    f = staged
    authoring, evidence, schedule = pit_fixture(f)
    old = resolve_experiment(
        authoring,
        snapshot_hash=f.request.snapshot_hash,
        qlib_view_hash=f.request.qlib_view_hash,
        qlib_version=f.request.qlib_version,
        qlib_view_spec_hash="a" * 64,
        pit_audit_evidence_hash=evidence.content_hash,
        research_policy_hash=f.request.research_policy_hash,
        validation_policy_hash=f.request.validation_policy_hash,
        cost_policy_hash=f.request.cost_policy_hash,
        backtest_policy_hash=f.request.backtest_policy_hash,
        code_commit_hash=f.request.code_commit_hash,
        lockfile_hash=f.request.lockfile_hash,
    )
    new = old.model_copy(update={"code_commit_hash": "e" * 40})
    row = SignalRow(
        instrument_id="600000.SH",
        signal_time=schedule.signal_time,
        decision_time=schedule.decision_time,
        available_at=evidence.bundles[0].output_temporal.available_at,
        score=0.5,
        tradable=True,
    )
    translation = translate_safe_expression(old.expression)
    staging = f.service.workspace / "synthetic-original"
    staging.mkdir()
    for name, payload in (
        ("resolved-experiment.json", old.canonical_bytes()),
        ("expression-translation.json", translation.canonical_bytes()),
        ("pit-evidence.json", evidence.canonical_bytes()),
    ):
        atomic_write_bytes(staging / name, payload)
    signal_module.write_signal_table((row,), staging / "signals.parquet")
    manifest = SignalArtifactManifest.create(
        resolved_experiment_hash=old.content_hash,
        source_expression_or_model_hash=old.expression.content_hash,
        snapshot_hash=old.snapshot_hash,
        qlib_version=old.qlib_version,
        qlib_view_spec_hash=old.qlib_view_spec_hash,
        qlib_view_hash=old.qlib_view_hash,
        qlib_run_id=None,
        pit_evidence_hash=evidence.content_hash,
        transform_lineage_hash=pit_transform_lineage_hash(evidence),
        expression_translation_hash=translation.content_hash,
        row_count=1,
        signal_start=schedule.signal_time,
        signal_end=schedule.signal_time,
        signal_content_hash=signal_module.signal_content_hash((row,)),
        files=signal_module._artifact_files(staging),
        created_at=datetime.now(UTC),
    )
    atomic_write_bytes(
        staging / "manifest.json", canonical_json_bytes(manifest.model_dump(mode="python"))
    )
    original = staging.with_name("sha256-" + manifest.artifact_hash)
    staging.rename(original)
    assert signal_module.verify_signal_artifact(original) == manifest
    checked = []
    monkeypatch.setattr(
        signal_module, "verify_code_provenance", lambda *a, **kw: checked.append(kw)
    )
    monkeypatch.setattr(
        signal_module, "_execute_expression", lambda *a: pytest.fail("adoption must not query Qlib")
    )
    return SimpleNamespace(
        old=old,
        new=new,
        original=original,
        manifest=manifest,
        root=f.service.workspace,
        checked=checked,
    )


def adopt(f, **updates):
    kwargs = dict(
        source_adoption_record_hash="f" * 64,
        source_workspace=f.root,
        workspace=f.root,
        adoption_root=f.root / "receipts",
        original_execution_status="SUCCEEDED",
    )
    kwargs.update(updates)
    return signal_module.FactorSignalArtifactBuilder().adopt_verified(
        f.new, f.original, f.root / "adopted", **kwargs
    )


def test_adoption_preserves_native_bytes_and_reuses_the_original_receipt(original_signal):
    f = original_signal
    old_bytes = (f.original / "signals.parquet").read_bytes()
    first = adopt(f)
    assert (first.path / "signals.parquet").read_bytes() == old_bytes
    assert first.manifest.resolved_experiment_hash == f.new.content_hash
    assert adopt(f) == first and len(tuple((f.root / "receipts").glob("sha256-*.json"))) == 1
    assert (f.original / "signals.parquet").read_bytes() == old_bytes
    assert {x["expected_commit_hash"] for x in f.checked} == {
        f.old.code_commit_hash,
        f.new.code_commit_hash,
    }


@pytest.mark.parametrize("damage", ["status", "bindings", "mutate-original", "receipt", "native"])
def test_adoption_rejects_changed_math_incomplete_origin_and_tampered_receipts(
    original_signal, damage
):
    f = original_signal
    kwargs = {}
    if damage == "status":
        kwargs["original_execution_status"] = "FAILED"
    elif damage == "bindings":
        f.new = f.new.model_copy(update={"cost_policy_hash": "d" * 64})
    elif damage == "mutate-original":
        kwargs["adoption_root"] = f.original / "receipts"
    elif damage == "receipt":
        adopt(f)
        path = next((f.root / "receipts").glob("sha256-*.json"))
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        first = adopt(f)
        (first.path / "signals.parquet").write_bytes(b"changed")
    with pytest.raises(QlibResearchError):
        adopt(f, **kwargs)
    assert sha256_file(f.original / "signals.parquet") == next(
        x.sha256 for x in f.manifest.files if x.logical_path == "signals.parquet"
    )


@pytest.mark.parametrize(
    "field", ["original_resolved_hash", "scientific_origin_commit", "lockfile_hash"]
)
def test_canonical_receipt_still_requires_exact_scientific_origin(original_signal, field):
    from quantos.contracts.native_adoption import NativeArtifactAdoptionReceipt

    f = original_signal
    adopt(f)
    path = next((f.root / "receipts").glob("sha256-*.json"))
    original = NativeArtifactAdoptionReceipt.model_validate_json(path.read_bytes())
    changed = original.model_copy(
        update={field: "d" * (40 if field == "scientific_origin_commit" else 64)}
    )
    path.unlink()
    atomic_write_bytes(
        path.with_name("sha256-" + changed.content_hash + ".json"), changed.canonical_bytes()
    )
    with pytest.raises(QlibResearchError, match="origin differs"):
        adopt(f)


def test_retained_destination_without_receipt_is_verified_before_republication(original_signal):
    f = original_signal
    first = adopt(f)
    next((f.root / "receipts").glob("sha256-*.json")).unlink()
    assert adopt(f).path == first.path
    assert (first.path / "signals.parquet").read_bytes() == (
        f.original / "signals.parquet"
    ).read_bytes()
