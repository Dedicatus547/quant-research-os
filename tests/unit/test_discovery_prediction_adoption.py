"""Bounded immutable-adoption rejection checks; no market data or native execution."""

from types import SimpleNamespace
from typing import ClassVar

import pytest

from quantos.application import discovery_prediction_adoption as adoption
from quantos.artifacts.store import sha256_file
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.discovery_prediction_adoption import (
    PredictionEvidenceAdoption,
    RetainedPredictionEvidence,
)
from quantos.contracts.status import ValidationVerdict


def test_original_receipt_rehashes_actual_bytes(tmp_path):
    path = tmp_path / "exit.json"
    path.write_bytes(b'{"actual_exit":0}')
    reference = PredictionFileSource(path=str(path), sha256=sha256_file(path))
    assert adoption._original_json(reference)["actual_exit"] == 0
    path.write_bytes(b'{"actual_exit":1}')
    with pytest.raises(ValueError, match="ADOPTION_ORIGINAL_HASH_MISMATCH"):
        adoption._original_json(reference)


def test_adoption_contract_rejects_duplicate_retained_requests():
    reference = PredictionFileSource(path="/original", sha256="a" * 64)
    item = RetainedPredictionEvidence(
        execution_request_hash="b" * 64, evidence_root="/evidence", manifest_hash="c" * 64
    )
    fields = {
        name: reference
        for name in PredictionEvidenceAdoption.model_fields
        if name.startswith("prior_") or name == "comparison_policy"
    }
    with pytest.raises(ValueError, match="ordered unique"):
        PredictionEvidenceAdoption(**fields, retained=(item, item))


@pytest.fixture
def original_probe(tmp_path, monkeypatch):
    native = tmp_path / "sha256-identity"
    (native / "sig_analysis").mkdir(parents=True)
    refs = []
    for name in (
        "pred.pkl",
        "label.pkl",
        "metrics.json",
        "sig_analysis/ic.pkl",
        "sig_analysis/ric.pkl",
    ):
        path = native / name
        path.write_bytes(name.encode())
        refs.append(PredictionFileSource(path=str(path), sha256=sha256_file(path)))
    split = native / "model-data-splits.json"
    split.write_bytes(b"split")
    view = tmp_path / "view"
    (view / "calendars").mkdir(parents=True)
    (view / "calendars/day.txt").write_text("2020-01-02\n")
    bindings = dict(
        snapshot_hash="snapshot",
        qlib_view_hash="view",
        research_policy_hash="policy",
        code_commit_hash="commit",
        lockfile_hash="lock",
        qlib_version="qlib",
    )
    expression = SimpleNamespace(content_hash="expression")
    request = SimpleNamespace(
        **bindings,
        content_hash="request",
        execution_identity="identity",
        authoring_hash="authoring",
        candidate=SimpleNamespace(expression=expression),
    )
    resolved = SimpleNamespace(
        **bindings,
        content_hash="resolved",
        expression=expression,
        pit_audit_evidence_hash="pit",
        strategy=SimpleNamespace(universe_index="index"),
    )
    receipt = SimpleNamespace(content_hash="receipt", request=request)
    evidence = SimpleNamespace(
        execution_request_hash="request",
        original_outcome_hash="outcome",
        original_receipt_hash="receipt",
        model_split_hash=sha256_file(split),
        signal_hash="signal",
        profile_hash="profile",
        verifier_identity_hash="verifier",
        pit_evidence_hash="pit",
        native_sources=refs,
    )
    source = SimpleNamespace(
        request="request",
        outcome="outcome",
        receipt="receipt",
        resolved="resolved",
        research_policy="policy",
        workflow_reservation="reservation",
        workflow_completion="completion",
        management_exit="exit",
        model_split_sha256=sha256_file(split),
        signal_hash="signal",
        signal_path=str(tmp_path),
        native_root=str(native),
        qlib_view_path=str(view),
    )
    profile = SimpleNamespace(**bindings, content_hash="profile", verifier_identity_hash="verifier")
    gates = [SimpleNamespace(gate_id=g, verdict=ValidationVerdict.PASS) for g in adoption.PITGateId]

    class Pit:
        content_hash = "pit"
        snapshot_hash = "snapshot"
        expression_spec_hash = "expression"
        universe_index = "index"
        bundles: ClassVar = [SimpleNamespace(gates=gates)]

    originals = {
        "request": request,
        "outcome": SimpleNamespace(content_hash="outcome"),
        "receipt": receipt,
        "resolved": resolved,
    }
    monkeypatch.setattr(adoption, "_contract", lambda ref, _: originals[ref])
    monkeypatch.setattr(
        adoption, "_research_policy", lambda _: SimpleNamespace(content_hash="policy")
    )
    monkeypatch.setattr(adoption, "_raw_json", lambda _: {})
    monkeypatch.setattr(adoption, "_verify_source_code", lambda *_: None)
    monkeypatch.setattr(adoption, "PITCrossSectionEvidenceCollection", Pit)
    monkeypatch.setattr(adoption, "load_pit_artifact_evidence", lambda _: Pit())
    monkeypatch.setattr(
        adoption,
        "verify_signal_artifact",
        lambda _: SimpleNamespace(
            artifact_hash="signal",
            resolved_experiment_hash="resolved",
            snapshot_hash="snapshot",
            qlib_view_hash="view",
            source_expression_or_model_hash="expression",
        ),
    )
    monkeypatch.setattr(adoption, "verify_model_data_split", lambda *_, **__: None)
    return source, evidence, profile, SimpleNamespace(content_hash="authoring"), native, gates


def test_retained_native_mutation_rejected_without_reconstruction(original_probe):
    source, evidence, profile, authoring, native, _ = original_probe
    adoption._retained_originals(source, evidence, profile, authoring)
    (native / "pred.pkl").write_bytes(b"mutated original")
    with pytest.raises(ValueError, match="ADOPTION_NATIVE_ORIGINAL_CHANGED"):
        adoption._retained_originals(source, evidence, profile, authoring)


def test_retained_pit_failure_never_adopted(original_probe):
    source, evidence, profile, authoring, _, gates = original_probe
    gates[0].verdict = ValidationVerdict.REJECT
    with pytest.raises(ValueError, match="ADOPTION_PIT_HARD_REJECTION"):
        adoption._retained_originals(source, evidence, profile, authoring)


def test_adopted_comparison_keeps_missing_denominator_and_rejects_new_failure(monkeypatch):
    from datetime import date

    profile = SimpleNamespace(
        execution_request_hashes=("old", "new", "missing"),
        expected_dates=(date(2020, 1, 2),),
        min_defined_fraction=1.0,
        min_common_days=1,
        content_hash="profile",
        interpretation="research",
    )
    old = SimpleNamespace(
        daily=(),
        structural_expression_hash="expression",
        original_execution_outcome="EXECUTION_FAILED",
        original_failure_reason="SOURCE_INCOMPLETE",
        original_validation_report_hash=None,
    )
    monkeypatch.setattr(
        adoption, "adopt_prediction_evidence", lambda *_, **__: {"old": (old, "oldhash")}
    )
    calls = []

    def reject(*_, **__):
        calls.append("new")
        raise ValueError("NEW_ACTUAL_FILE_CHANGED")

    monkeypatch.setattr(adoption, "verify_prediction_evidence", reject)
    result = adoption.compare_with_adopted_prediction_evidence(
        SimpleNamespace(content_hash="adoption"),
        profile,
        {"new": SimpleNamespace(request=SimpleNamespace(sha256="new"))},
        {"new": (None, "newhash")},
        base_authoring=None,
    )
    assert calls == ["new"]
    assert result["request_denominator"] == 3
    assert result["missing_or_rejected_requests"] == 3
    assert [row["status"] for row in result["rows"]] == [
        "COVERAGE_REJECTED",
        "SOURCE_VERIFICATION_REJECTED",
        "SOURCE_MISSING",
    ]


def test_original_public_verify_still_rebuilds(monkeypatch, tmp_path):
    from quantos.application import discovery_prediction as original

    calls = []
    monkeypatch.setattr(
        original,
        "build_prediction_evidence",
        lambda *_, **__: calls.append("rebuilt") or "evidence",
    )
    monkeypatch.setattr(original, "_verify_saved", lambda *args: args[-1])
    assert (
        original.verify_prediction_evidence(
            tmp_path,
            expected_hash="hash",
            source=None,
            profile=None,
        )
        == "evidence"
    )
    assert calls == ["rebuilt"]


def test_prior_report_cannot_move_outside_completed_publication(tmp_path, monkeypatch):
    completed = tmp_path / "completed"
    completed.mkdir()
    profile_path = completed / "profile.json"
    profile_path.write_bytes(b"profile")
    forged_report = tmp_path / "other-publication.json"
    forged_report.write_bytes(b"report")
    receipt = SimpleNamespace(
        prior_profile="profile",
        prior_report=SimpleNamespace(path=str(forged_report)),
        prior_report_exit="exit",
        prior_cohort="cohort",
        comparison_policy="policy",
        prior_report_prelaunch="prelaunch",
        prior_configuration="configuration",
        retained=(),
    )
    monkeypatch.setattr(adoption, "_contract", lambda *_: None)
    monkeypatch.setattr(adoption, "_original_json", lambda _: {"actual_exit": 0})
    monkeypatch.setattr(
        adoption,
        "_raw_json",
        lambda key: {"report_output": str(completed)} if key == "configuration" else {},
    )
    with pytest.raises(ValueError, match="ADOPTION_OUTPUT_OUTSIDE_COMPLETED_REPORT"):
        adoption._prior_authority(receipt, None)
