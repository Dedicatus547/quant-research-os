"""Recovery verifies retained Qlib label-export originals and full trial denominator."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_discovery_comparison_regression import predicted as predicted
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged

from quantos.application import autonomous_execution as module
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.contracts.campaign import CampaignEventType


@pytest.mark.parametrize(
    "attack", ["valid", "missing", "duplicate", "invalid", "native", "changed_verifier"]
)
def test_dq_recovery_rechecks_unique_audit_and_untouched_native_labels(
    predicted, monkeypatch, attack
):
    f = predicted
    adapter = f.adapter
    adapter.output_root = f.prediction_adapter.output_root
    adapter.qlib_view_path = f.service.qlib_view_path
    calendar = adapter.qlib_view_path / "calendars/day.txt"
    calendar.parent.mkdir(parents=True, exist_ok=True)
    calendar.write_text("\n".join(map(str, f.calendar)) + "\n")
    audit = next((adapter.output_root / "research-result-audits").glob("sha256-*.json"))
    if attack == "missing":
        audit.unlink()
    elif attack == "duplicate":
        (audit.parent / ("sha256-" + "f" * 64 + ".json")).write_bytes(audit.read_bytes())
    elif attack == "invalid":
        audit.write_bytes(b"{}")
    elif attack == "native":
        native = next((adapter.output_root / "executions").rglob("label.pkl"))
        native.write_bytes(b"changed original")
    elif attack == "changed_verifier":
        monkeypatch.setattr(module, "verify_p14dq_native_label_audit", lambda *args: None)
    if attack == "valid":
        verified = adapter._verify_dq_audit_for_request(f.request, f.built.manifest.artifact_hash)
        assert verified.audit_hash == f.built.export_audit_hash
        assert verified.raw_pair_count >= verified.exported_pair_count
    else:
        with pytest.raises(AutonomousOrchestrationError):
            adapter._verify_dq_audit_for_request(f.request, f.built.manifest.artifact_hash)


@pytest.mark.parametrize(
    "attack",
    [
        "valid",
        "profile",
        "missing_trial",
        "candidate",
        "missing_receipt",
        "receipt_hash",
        "outcome",
        "evidence",
    ],
)
def test_dq_selection_cannot_silently_drop_failed_trials_or_replace_evidence(staged, attack):
    f = staged
    adapter = f.adapter
    candidate = f.request.candidate
    adapter.p14dq_v2_profile = attack != "profile"
    adapter.manifest = SimpleNamespace(candidates=(candidate,))
    adapter._candidate_by_hash = {candidate.content_hash: candidate}
    marker = object()
    outcome = SimpleNamespace(outcome=marker, evidence_hashes=("b" * 64,))
    receipt = SimpleNamespace(request=f.request, content_hash="c" * 64, outcome=outcome)
    trial = SimpleNamespace(
        candidate_hash=candidate.content_hash, outcome=marker, evidence_hashes=("b" * 64, "c" * 64)
    )
    events = (SimpleNamespace(event_type=CampaignEventType.TRIAL_RECORDED, trial=trial),)
    if attack == "missing_trial":
        events = ()
    elif attack == "candidate":
        trial.candidate_hash = "f" * 64
    elif attack == "receipt_hash":
        trial.evidence_hashes = ("b" * 64,)
    elif attack == "outcome":
        trial.outcome = object()
    elif attack == "evidence":
        outcome.evidence_hashes = ("d" * 64,)
    adapter._receipt_paths = lambda: () if attack == "missing_receipt" else (Path("receipt.json"),)
    adapter._read_receipt = lambda _: receipt
    verified = []
    adapter._verify_receipt = verified.append
    if attack == "valid":
        adapter.verify_preselection_dq_trials(events)
        assert verified == [receipt]
    else:
        with pytest.raises(AutonomousOrchestrationError):
            adapter.verify_preselection_dq_trials(events)
        assert not verified
