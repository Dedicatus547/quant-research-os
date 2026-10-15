"""Read-only comparison prerequisites on tiny synthetic records, no market execution."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_discovery_variant_regression import pit_fixture
from test_research_result import _inputs

from quantos.application import discovery_comparison as comparison
from quantos.application.autonomous_execution import resolve_experiment
from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes
from quantos.research.qlib import QlibResearchError
from quantos.research.qlib import result as native_result
from quantos.research.qlib.result import ResearchResultArtifactBuilder


@pytest.fixture
def predicted(staged, monkeypatch):
    f = staged
    authoring, evidence, _ = pit_fixture(f)
    adapter = SimpleNamespace(
        output_root=f.service.workspace / "tiny-records",
        snapshot_path=f.service.snapshot_path,
        qlib_view_path=f.service.qlib_view_path,
    )
    adapter.research_results_root = adapter.output_root / "research-results"
    native = (
        adapter.output_root
        / "executions"
        / f.request.execution_identity
        / "qlib-workflow/native-records"
        / ("sha256-" + f.request.execution_identity)
    )
    # Existing table fixture is copied in memory, not sourced from a provider.
    import shutil

    _, _, tiny_native = _inputs(f.service.workspace / "tables")
    shutil.copytree(tiny_native, native)
    resolved = resolve_experiment(
        authoring,
        snapshot_hash=f.request.snapshot_hash,
        qlib_view_hash=f.request.qlib_view_hash,
        qlib_version=f.request.qlib_version,
        qlib_view_spec_hash="a" * 64,
        pit_audit_evidence_hash=evidence.content_hash,
        research_policy_hash=f.batch.design.research_policy.content_hash,
        validation_policy_hash=f.batch.design.validation_policy.content_hash,
        cost_policy_hash=f.batch.design.cost_policy.content_hash,
        backtest_policy_hash=f.batch.design.backtest_policy.content_hash,
        code_commit_hash=f.request.code_commit_hash,
        lockfile_hash=f.request.lockfile_hash,
    )
    signal = SimpleNamespace(artifact_hash="b" * 64, resolved_experiment_hash=resolved.content_hash)
    monkeypatch.setattr(native_result, "verify_signal_artifact", lambda _: signal)
    monkeypatch.setattr(comparison, "verify_signal_artifact", lambda _: signal)
    monkeypatch.setattr(comparison, "load_pit_artifact_evidence", lambda _: evidence)
    monkeypatch.setattr(comparison, "verify_compact_pit_evidence", lambda *a: None)
    calendar = (date(2024, 1, 2), date(2024, 1, 3))
    built = ResearchResultArtifactBuilder().build(
        resolved,
        f.batch.design.research_policy,
        adapter.output_root / "synthetic-signal",
        native,
        adapter.research_results_root,
        qlib_run_id="synthetic-record-no-qlib-run",
        label_expression=f"Ref($close,-{f.batch.design.research_policy.label_horizon_trading_sessions})/$close-1",
        dq_calendar=calendar,
        dq_audit_root=adapter.output_root / "research-result-audits",
    )
    outcome = AutonomousExecutionResult(
        request_hash=f.request.content_hash,
        outcome="SOFT_REJECT",
        execution_requested=True,
        compute_seconds=1,
        research_result_hash=built.manifest.artifact_hash,
        evidence_hashes=tuple(sorted((built.export_audit_hash, built.manifest.artifact_hash))),
    )
    f.prediction_adapter, f.prediction_outcome = adapter, outcome
    f.built, f.calendar, f.resolved = built, calendar, resolved
    f.signal, f.pit = signal, evidence
    return f


def inspect_prediction(f):
    return comparison._prediction_evidence(
        f.batch,
        f.request,
        f.prediction_outcome,
        f.prediction_adapter,
        f.calendar,
        f.batch.design.bindings,
        False,
    )


def test_comparison_requires_native_pairs_and_keeps_model_portfolio_distinction(predicted):
    f = predicted
    facts = inspect_prediction(f)
    assert facts["primary_value"] == 0.35 and facts["prediction_pair_count"] == 4
    assert facts["test_session_count"] == 2 and facts["native_pair_count"] == 4
    assert facts["evaluated_object"] == "LGBModel test prediction/label"
    assert facts["purge_evidence_status"] == "DECLARED_PURGE_NOT_APPLIED_IN_ORIGINAL_03"
    assert facts["purge_limitations"]
    assert facts["omitted_nan_label_count"] == 0
    # This unit fixture mocks snapshot PIT verification; facts confer no live or scientific GO.


@pytest.mark.parametrize("damage", ["design", "pit", "calendar", "audit", "receipt", "rows"])
def test_comparison_refuses_source_or_prerequisite_drift(predicted, damage):
    f = predicted
    if damage == "design":
        f.request = f.request.model_copy(update={"snapshot_hash": "f" * 64})
    elif damage == "pit":
        f.signal.resolved_experiment_hash = "f" * 64
        f.pit = f.pit.model_copy(update={"expression_spec_hash": "f" * 64})
        # Select a mismatched PIT contract at the fake source-verifier boundary.
        from unittest.mock import patch

        with (
            patch.object(comparison, "load_pit_artifact_evidence", return_value=f.pit),
            pytest.raises(ValueError, match="PIT_BINDING_MISMATCH"),
        ):
            inspect_prediction(f)
        return
    elif damage == "calendar":
        f.calendar = (*f.calendar, date(2024, 1, 4))
    elif damage == "audit":
        f.built.export_audit_path.unlink()
    elif damage == "receipt":
        f.prediction_outcome = f.prediction_outcome.model_copy(update={"evidence_hashes": ()})
    else:
        (f.built.path / "predictions.json").write_bytes(b"[]")
    with pytest.raises((ValueError, QlibResearchError)):
        inspect_prediction(f)


@pytest.mark.parametrize("damage", [None, "identity", "order", "empty"])
def test_verified_calendar_needs_frozen_quality_identity_and_order(staged, monkeypatch, damage):
    f = staged
    adapter = SimpleNamespace(
        snapshot_path=f.service.workspace / "snap", qlib_view_path=f.service.workspace / "view"
    )
    design = f.batch.design
    quality = SimpleNamespace(content_hash="a" * 64, passed=True)
    monkeypatch.setattr(
        comparison, "DataQualityReport", SimpleNamespace(model_validate_json=lambda _: quality)
    )
    snapshot = SimpleNamespace(
        snapshot_hash=design.snapshot_hash, quality_report_hash=quality.content_hash
    )
    view = SimpleNamespace(
        view_hash=design.qlib_view_hash, source_snapshot_hash=design.snapshot_hash
    )
    monkeypatch.setattr(comparison, "verify_snapshot", lambda _: snapshot)
    monkeypatch.setattr(comparison, "verify_qlib_view", lambda _: view)
    atomic_write_bytes(
        adapter.snapshot_path / "quality-report.json", canonical_json_bytes({"scope": "synthetic"})
    )
    days = ("2024-01-02", "2024-01-03")
    if damage == "identity":
        quality.passed = False
    elif damage == "order":
        days = tuple(reversed(days))
    elif damage == "empty":
        days = ("2001-01-02",)
    atomic_write_bytes(
        adapter.qlib_view_path / "calendars/day.txt", ("\n".join(days) + "\n").encode()
    )
    if damage is None:
        assert comparison._verified_data_calendar(f.batch, adapter) == tuple(
            date.fromisoformat(d) for d in days
        )
    else:
        with pytest.raises(ValueError):
            comparison._verified_data_calendar(f.batch, adapter)


def test_legacy_comparison_rejects_v3_before_source_reconstruction(predicted, monkeypatch):
    from test_validation_field_study_pit import _evidence

    monkeypatch.setattr(
        comparison, "load_pit_artifact_evidence", lambda _: _evidence("v3", "3" * 64)
    )
    monkeypatch.setattr(
        comparison, "verify_compact_pit_evidence", lambda *_: pytest.fail("V3 reproduction")
    )
    with pytest.raises(ValueError, match="PIT_EXECUTION_PROFILE_MISMATCH"):
        inspect_prediction(predicted)
