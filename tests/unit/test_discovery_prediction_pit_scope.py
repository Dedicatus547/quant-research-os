"""Critical scoped reuse checks without scientific execution or market fixtures."""

from types import SimpleNamespace
from typing import ClassVar

import pytest

from quantos.application import discovery_prediction as prediction
from quantos.contracts.status import ValidationVerdict


@pytest.fixture
def pit_probe(tmp_path, monkeypatch):
    signal_path = tmp_path / "signal"
    signal_path.mkdir()
    original = tmp_path / "snapshot-original"
    original.write_bytes(b"original")
    calls = {"data": 0, "signal": 0, "reproduction": 0}
    expression = SimpleNamespace(content_hash="expression")
    request = SimpleNamespace(
        content_hash="request",
        snapshot_hash="snapshot",
        qlib_view_hash="view",
        candidate=SimpleNamespace(expression=expression),
    )
    resolved = SimpleNamespace(
        content_hash="resolved",
        pit_audit_evidence_hash="evidence",
        qlib_view_spec_hash="view-spec",
        strategy=SimpleNamespace(universe_index="index"),
    )
    source = SimpleNamespace(
        content_hash="source",
        signal_path=str(signal_path),
        signal_hash="signal",
        snapshot_path=str(tmp_path),
        qlib_view_path=str(tmp_path),
    )

    class Evidence:
        content_hash = "evidence"
        snapshot_hash = "snapshot"
        expression_spec_hash = "expression"
        universe_index = "index"
        bundles: ClassVar = [
            SimpleNamespace(
                gates=[
                    SimpleNamespace(gate_id=gate, verdict=ValidationVerdict.PASS)
                    for gate in prediction.PITGateId
                ]
            )
        ]

    def data_verification(_):
        calls["data"] += 1
        if original.read_bytes() != b"original":
            raise ValueError("ACTUAL_ORIGINAL_HASH_MISMATCH")
        return SimpleNamespace(snapshot_hash="snapshot")

    def signal_verification(_):
        calls["signal"] += 1
        return SimpleNamespace(
            artifact_hash="signal",
            resolved_experiment_hash="resolved",
            snapshot_hash="snapshot",
            qlib_view_hash="view",
            source_expression_or_model_hash="expression",
        )

    def reproduce(*_):
        calls["reproduction"] += 1

    monkeypatch.setattr(prediction, "PITCrossSectionEvidenceCollection", Evidence)
    monkeypatch.setattr(prediction, "load_pit_artifact_evidence", lambda _: Evidence())
    monkeypatch.setattr(prediction, "verify_snapshot", data_verification)
    monkeypatch.setattr(
        prediction,
        "verify_qlib_view",
        lambda _: SimpleNamespace(
            view_hash="view",
            view_spec_hash="view-spec",
        ),
    )
    monkeypatch.setattr(prediction, "verify_signal_artifact", signal_verification)
    monkeypatch.setattr(prediction, "verify_compact_pit_evidence", reproduce)
    return source, request, resolved, original, calls, Evidence


def test_repeat_rehashes_but_reproduces_once_and_new_scope_replays(pit_probe):
    source, request, resolved, _, calls, _ = pit_probe
    with prediction.prediction_pit_verification_scope():
        prediction._verify_pit(source, request, resolved)
        with prediction.prediction_pit_verification_scope():
            prediction._verify_pit(source, request, resolved)
    assert calls == {"data": 2, "signal": 2, "reproduction": 1}
    with prediction.prediction_pit_verification_scope():
        prediction._verify_pit(source, request, resolved)
    prediction._verify_pit(source, request, resolved)
    assert calls == {"data": 4, "signal": 4, "reproduction": 3}


def test_cached_success_does_not_hide_same_path_original_mutation(pit_probe):
    source, request, resolved, original, calls, _ = pit_probe
    with prediction.prediction_pit_verification_scope():
        prediction._verify_pit(source, request, resolved)
        original.write_bytes(b"mutation")
        with pytest.raises(ValueError, match="ACTUAL_ORIGINAL_HASH_MISMATCH"):
            prediction._verify_pit(source, request, resolved)
    assert calls["reproduction"] == 1


def test_failures_are_never_cached(pit_probe, monkeypatch):
    source, request, resolved, _, calls, _ = pit_probe

    def failure(*_):
        calls["reproduction"] += 1
        raise ValueError("PIT_SOURCE_REPRODUCTION_MISMATCH")

    monkeypatch.setattr(prediction, "verify_compact_pit_evidence", failure)
    with prediction.prediction_pit_verification_scope():
        for _ in range(2):
            with pytest.raises(ValueError, match="PIT_SOURCE_REPRODUCTION_MISMATCH"):
                prediction._verify_pit(source, request, resolved)
    assert calls["reproduction"] == 2


def test_changed_binding_or_failed_gate_rejects_cached_success(pit_probe):
    source, request, resolved, _, calls, evidence = pit_probe
    with prediction.prediction_pit_verification_scope():
        prediction._verify_pit(source, request, resolved)
        resolved.content_hash = "different-resolved"
        with pytest.raises(ValueError, match="PIT_BINDING_MISMATCH"):
            prediction._verify_pit(source, request, resolved)
        resolved.content_hash = "resolved"
        evidence.bundles[0].gates[0].verdict = ValidationVerdict.REJECT
        with pytest.raises(ValueError, match="PIT_HARD_REJECTION"):
            prediction._verify_pit(source, request, resolved)
    assert calls["reproduction"] == 1
