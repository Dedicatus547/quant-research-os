"""Recovery orchestration with typed synthetic PIT contracts and fake service boundaries.

These tests exercise reuse and refusal, never Qlib execution or scientific qualification.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged

from quantos.application import autonomous_execution as native
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.pit import PITGateId, PITGateResult
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceBundle,
    PITCrossSectionEvidenceCollection,
    PITMembershipSetEvidence,
    PITSourceSetEvidence,
    required_expression_observations,
)
from quantos.contracts.status import ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule, TemporalMetadata


def pit_fixture(f):
    expression = f.request.candidate.expression
    signal_time = datetime(2024, 3, 1, 15, tzinfo=UTC)
    schedule = DecisionSchedule(
        signal_time=signal_time,
        signal_available_at=signal_time + timedelta(minutes=1),
        decision_time=signal_time + timedelta(minutes=10),
        execution_time=signal_time + timedelta(days=1),
    )
    temporal = TemporalMetadata(
        event_time=signal_time,
        known_at=signal_time,
        available_at=signal_time,
        observed_at=signal_time,
        evidence_level="EXPLICIT_SOURCE_TIMESTAMP",
        policy_id="synthetic",
    )
    count = required_expression_observations(expression)
    sources = [
        PITSourceSetEvidence(
            table_name=table,
            logical_field_name="adjusted_close",
            source_field_name=field,
            expected_row_count=count,
            present_row_count=count,
            missing_row_count=0,
            row_set_hash="a" * 64,
            maximum_temporal=temporal,
        )
        for table, field in (("adjustment_factors", "adjustment_factor"), ("bars", "close"))
    ]
    bundle = PITCrossSectionEvidenceBundle(
        snapshot_hash=f.request.snapshot_hash,
        expression_spec_hash=expression.content_hash,
        universe_index=f.batch.design.authoring.strategy.universe_index,
        schedule=schedule,
        required_observations=count,
        source_window=tuple(
            (signal_time - timedelta(days=count - i - 1)).date() for i in range(count)
        ),
        members=("600000.SH",),
        source_sets=tuple(sources),
        membership_set=PITMembershipSetEvidence(
            row_count=1, row_set_hash="b" * 64, maximum_temporal=temporal
        ),
        output_temporal=temporal,
        gates=tuple(
            PITGateResult(gate_id=g, verdict=ValidationVerdict.PASS, detail="synthetic")
            for g in PITGateId
        ),
    )
    authoring = f.batch.design.authoring.model_copy(update={"expression": expression})
    evidence = PITCrossSectionEvidenceCollection(
        snapshot_hash=f.request.snapshot_hash,
        qlib_view_hash=f.request.qlib_view_hash,
        expression_spec_hash=expression.content_hash,
        expression=expression,
        operator_delays=native.research_operator_delays(authoring),
        universe_index=bundle.universe_index,
        bundles=(bundle,),
    )
    return authoring, evidence, schedule


@pytest.fixture
def variant(staged, monkeypatch):
    f = staged
    adapter = f.adapter
    design = f.batch.design
    adapter.discovery_source_adoption = None
    adapter._discovery_verified_pit_hashes = set()
    adapter.view = SimpleNamespace(qlib_version="0.9.7", view_spec_hash="a" * 64)
    adapter.research_policy = design.research_policy
    adapter.validation_policy = design.validation_policy
    adapter.backtest_policy = design.backtest_policy
    adapter.snapshot_path = f.service.snapshot_path
    adapter.qlib_view_path = f.service.qlib_view_path
    authoring, evidence, schedule = pit_fixture(f)
    f.authoring, f.evidence, f.schedules = authoring, evidence, (schedule,)
    f.destination = adapter.output_root / "executions" / f.request.execution_identity / "baseline"
    f.cache, f.signals, f.backtests, f.calls = {}, {}, {}, []

    class SignalBuilder:
        def build(self, resolved, pit, view, root, **kwargs):
            f.calls.append("signal")
            assert pit == evidence
            manifest = SimpleNamespace(artifact_hash="b" * 64)
            path = root / ("sha256-" + manifest.artifact_hash)
            atomic_write_bytes(path / "resolved-experiment.json", resolved.canonical_bytes())
            atomic_write_bytes(path / "pit-evidence.json", pit.canonical_bytes())
            f.signals[path] = manifest
            return SimpleNamespace(manifest=manifest)

    class BacktestService:
        def run(self, resolved, signal, view, cost, policy, root, **kwargs):
            f.calls.append("backtest")
            manifest = SimpleNamespace(
                result_hash="c" * 64,
                resolved_experiment_hash=resolved.content_hash,
                signal_artifact_hash="b" * 64,
                cost_policy_hash=cost.content_hash,
                backtest_policy_hash=policy.content_hash,
            )
            path = root / ("sha256-" + manifest.result_hash)
            atomic_write_bytes(path / "synthetic-record.json", b"{}")
            f.backtests[path] = manifest
            return SimpleNamespace(manifest=manifest)

    monkeypatch.setattr(native, "FactorSignalArtifactBuilder", SignalBuilder)
    monkeypatch.setattr(native, "QlibBacktestService", BacktestService)
    monkeypatch.setattr(native, "verify_signal_artifact", lambda p: f.signals[p])
    monkeypatch.setattr(native, "verify_backtest_artifact", lambda p: f.backtests[p])
    monkeypatch.setattr(
        native, "verify_compact_pit_evidence", lambda *a: f.calls.append("verify-pit")
    )

    def build_pit(*args, **kwargs):
        f.calls.append("pit")
        return evidence

    monkeypatch.setattr(native.release, "build_compact_pit_evidence_collection", build_pit)
    return f


def run_variant(f, override=None):
    return f.adapter._discovery_variant(
        f.request,
        f.authoring,
        f.batch.design.cost_policy,
        f.schedules,
        f.destination,
        f.cache,
        override,
    )


def test_variant_stage_checkpoints_reuse_all_outputs_without_scientific_reexecution(variant):
    f = variant
    first = run_variant(f)
    assert first.evidence == f.evidence and first.signal_hash == "b" * 64
    assert f.calls == ["pit", "signal", "backtest"]
    f.adapter._discovery_verified_pit_hashes.clear()
    assert run_variant(f) == first
    assert f.calls == ["pit", "signal", "backtest", "verify-pit"]
    assert len(tuple(f.adapter.output_root.rglob("reservation.json"))) == 3


@pytest.mark.parametrize("damage", ["signal", "resolved", "schedule", "backtest", "cost", "policy"])
def test_variant_recovered_originals_must_match_every_scientific_binding(variant, damage):
    f = variant
    result = run_variant(f)
    if damage == "signal":
        f.signals[result.signal_path].artifact_hash = "d" * 64
    elif damage == "resolved":
        changed = result.resolved.model_copy(update={"snapshot_hash": "d" * 64})
        (result.signal_path / "resolved-experiment.json").write_bytes(changed.canonical_bytes())
    elif damage == "schedule":
        changed = f.evidence.model_copy(
            update={
                "bundles": (
                    f.evidence.bundles[0].model_copy(
                        update={
                            "schedule": f.schedules[0].model_copy(
                                update={
                                    "execution_time": f.schedules[0].execution_time
                                    + timedelta(days=1)
                                }
                            )
                        }
                    ),
                )
            }
        )
        (result.signal_path / "pit-evidence.json").write_bytes(changed.canonical_bytes())
    else:
        field = {
            "backtest": "resolved_experiment_hash",
            "cost": "cost_policy_hash",
            "policy": "backtest_policy_hash",
        }[damage]
        setattr(f.backtests[result.backtest_path], field, "d" * 64)
    with pytest.raises((AutonomousOrchestrationError, ValueError)):
        run_variant(f)
    assert f.calls == ["pit", "signal", "backtest"]


@pytest.mark.parametrize("stage", ["baseline-signal", "baseline"])
def test_orphan_recovery_requires_unique_original_and_keeps_failed_attempt(variant, stage):
    f = variant
    result = run_variant(f)
    root = f.adapter.output_root / "execution-checkpoints" / f.request.execution_identity / stage
    next(root.glob("sha256-*.json")).unlink()  # Synthetic interruption after publishing an output.
    recovery = run_variant(f)
    assert recovery == result and f.calls == ["pit", "signal", "backtest"]
    import json

    completion = sorted(root.rglob("completion.json"))[-1]
    assert json.loads(completion.read_bytes())["status"] == "ADOPTED"
    next(root.glob("sha256-*.json")).unlink()
    directory = f.destination / ("signals" if stage.endswith("signal") else "backtests")
    (directory / ("sha256-" + "e" * 64)).mkdir()
    with pytest.raises(AutonomousOrchestrationError, match="ambiguous"):
        run_variant(f)
    assert f.calls == ["pit", "signal", "backtest"]


def test_pit_override_is_explicit_and_saved_originals_are_reverified(variant):
    f = variant
    first = run_variant(f, f.evidence)
    assert f.calls == ["signal", "backtest"]
    f.adapter._discovery_verified_pit_hashes.clear()
    assert run_variant(f, f.evidence) == first
    assert f.calls == ["signal", "backtest", "verify-pit"]


def test_variant_uses_declared_native_adoption_services_and_keeps_origin_outputs(
    variant, monkeypatch
):
    f = variant
    pit_path = f.service.workspace / "retained-pit.json"
    atomic_write_bytes(pit_path, f.evidence.canonical_bytes())
    origin = SimpleNamespace(
        stage="baseline",
        subtask_hash=f.adapter.output_root.name,
        pit_path=str(pit_path),
        signal_path=str(f.service.workspace / "retained-signal"),
        signal_hash="d" * 64,
        backtest_path=str(f.service.workspace / "retained-backtest"),
        backtest_hash="e" * 64,
    )
    adoption = SimpleNamespace(
        content_hash="f" * 64, variants=(origin,), original_workspace=str(f.service.workspace)
    )
    f.adapter.discovery_source_adoption = adoption
    monkeypatch.setattr(
        f.adapter, "_verify_adoption_origin", lambda *args: f.calls.append("origin-verified")
    )
    signal_base, backtest_base = native.FactorSignalArtifactBuilder, native.QlibBacktestService

    class AdoptingSignal(signal_base):
        def adopt_verified(self, resolved, source, root, **kwargs):
            assert kwargs["original_execution_status"] == "SUCCEEDED"
            assert kwargs["source_adoption_record_hash"] == adoption.content_hash
            f.calls.append("adopt-signal")
            return super().build(resolved, f.evidence, f.adapter.qlib_view_path, root)

    class AdoptingBacktest(backtest_base):
        def adopt_verified(
            self, resolved, old, old_signal, new_signal, cost, policy, root, **kwargs
        ):
            assert kwargs["original_execution_status"] == "SUCCEEDED"
            f.calls.append("adopt-backtest")
            return super().run(resolved, new_signal, f.adapter.qlib_view_path, cost, policy, root)

    monkeypatch.setattr(native, "FactorSignalArtifactBuilder", AdoptingSignal)
    monkeypatch.setattr(native, "QlibBacktestService", AdoptingBacktest)
    assert run_variant(f).signal_hash == "b" * 64
    assert "pit" not in f.calls and "adopt-signal" in f.calls and "adopt-backtest" in f.calls
    import json

    records = [json.loads(p.read_bytes()) for p in f.adapter.output_root.rglob("sha256-*.json")]
    outputs = [r.get("outputs", {}) for r in records]
    assert any(o.get("original_signal_hash") == origin.signal_hash for o in outputs)
    assert any(o.get("original_backtest_hash") == origin.backtest_hash for o in outputs)
    adoption.variants = (origin, origin)
    with pytest.raises(AutonomousOrchestrationError, match="ambiguous"):
        run_variant(f)
