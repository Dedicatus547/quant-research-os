"""Unit origin-receipt checks on synthetic native bytes; no scientific verdict transfer."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import run_stage, successor
from test_discovery_recovery_regression import staged as staged

from quantos.application import autonomous_execution as native
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_adoption import DiscoveryAdoptedVariant
from quantos.contracts.native_adoption import AdoptedNativeFile, NativeArtifactAdoptionReceipt


@pytest.fixture
def adoption(staged, monkeypatch):
    f = staged
    old = f.request
    f.original_request = old
    f.request = old.model_copy(update={"code_commit_hash": "e" * 40})
    request_path = f.service.workspace / "old-request.json"
    atomic_write_bytes(request_path, old.canonical_bytes())
    pit_path = f.service.workspace / "original-pit.json"
    atomic_write_bytes(pit_path, b'{"scope":"synthetic-native-bytes"}')
    pit_hash = sha256_bytes(pit_path.read_bytes())
    f.request = old
    run_stage(f, lambda: {"signal_hash": "b" * 64}, lambda x: x)
    checkpoint = next((f.adapter.output_root / "execution-checkpoints").rglob("sha256-*.json"))
    # Origin stage names and checkpoints are exact, even in this synthetic unit fixture.
    stage_root = checkpoint.parent
    renamed = stage_root.with_name("baseline-signal")
    stage_root.rename(renamed)
    import json

    checkpoint = renamed / checkpoint.name
    value = json.loads(checkpoint.read_bytes())
    value["stage"] = "baseline-signal"
    reservation = next(renamed.rglob("reservation.json"))
    saved = json.loads(reservation.read_bytes())
    saved["stage"] = "baseline-signal"
    reservation.write_bytes(canonical_json_bytes(saved))
    value["reservation_hash"] = sha256_bytes(reservation.read_bytes())
    checkpoint.write_bytes(canonical_json_bytes(value))
    completion = reservation.parent / "completion.json"
    saved = json.loads(completion.read_bytes())
    saved["checkpoint_hash"] = sha256_bytes(checkpoint.read_bytes())
    completion.write_bytes(canonical_json_bytes(saved))
    f.request = old.model_copy(update={"code_commit_hash": "e" * 40})
    origin = DiscoveryAdoptedVariant(
        subtask_hash=f.adapter.output_root.name
        if len(f.adapter.output_root.name) == 64
        else "a" * 64,
        stage="baseline",
        request_path=str(request_path),
        request_hash=old.content_hash,
        signal_path=str(f.service.workspace / "original-signal"),
        signal_hash="b" * 64,
        signal_checkpoint_path=str(checkpoint),
        signal_checkpoint_hash=sha256_bytes(checkpoint.read_bytes()),
        pit_path=str(pit_path),
        pit_hash=pit_hash,
    )
    adopted, _ = successor(f)
    f.adapter.output_root = f.service.workspace / origin.subtask_hash
    f.adapter.discovery_source_adoption = adopted.model_copy(update={"variants": (origin,)})
    f.origin = origin
    f.old_signal = SimpleNamespace(artifact_hash=origin.signal_hash, pit_evidence_hash=pit_hash)
    f.new_signal = SimpleNamespace(artifact_hash="c" * 64, resolved_experiment_hash=None)
    monkeypatch.setattr(
        native,
        "verify_signal_artifact",
        lambda p: f.old_signal if p == f.service.workspace / "original-signal" else f.new_signal,
    )
    authoring = f.batch.design.authoring.model_copy(update={"expression": old.candidate.expression})
    f.old_resolved = native.resolve_experiment(
        authoring,
        snapshot_hash=old.snapshot_hash,
        qlib_view_hash=old.qlib_view_hash,
        qlib_version=old.qlib_version,
        qlib_view_spec_hash="a" * 64,
        pit_audit_evidence_hash=pit_hash,
        research_policy_hash=old.research_policy_hash,
        validation_policy_hash=old.validation_policy_hash,
        cost_policy_hash=old.cost_policy_hash,
        backtest_policy_hash=old.backtest_policy_hash,
        code_commit_hash=old.code_commit_hash,
        lockfile_hash=old.lockfile_hash,
    )
    f.new_resolved = f.old_resolved.model_copy(
        update={"code_commit_hash": f.request.code_commit_hash}
    )
    f.new_signal.resolved_experiment_hash = f.new_resolved.content_hash
    f.old_path = f.service.workspace / "original-signal"
    f.new_path = (
        f.adapter.output_root
        / "executions"
        / f.request.execution_identity
        / "baseline/signals"
        / ("sha256-" + "c" * 64)
    )
    for path, resolved in ((f.old_path, f.old_resolved), (f.new_path, f.new_resolved)):
        atomic_write_bytes(path / "resolved-experiment.json", resolved.canonical_bytes())
        atomic_write_bytes(path / "native.csv", b"synthetic unchanged bytes\n")
    receipt = NativeArtifactAdoptionReceipt(
        artifact_kind="FACTOR_SIGNAL",
        source_adoption_record_hash=f.adapter.discovery_source_adoption.content_hash,
        original_artifact_hash=origin.signal_hash,
        adopted_artifact_hash="c" * 64,
        original_resolved_hash=f.old_resolved.content_hash,
        adopted_resolved_hash=f.new_resolved.content_hash,
        scientific_origin_commit=old.code_commit_hash,
        adoption_commit=f.request.code_commit_hash,
        lockfile_hash=old.lockfile_hash,
        native_files=(
            AdoptedNativeFile(
                logical_path="native.csv",
                bytes_hash=sha256_bytes((f.old_path / "native.csv").read_bytes()),
                size_bytes=(f.old_path / "native.csv").stat().st_size,
            ),
        ),
        metadata_rebindings=("code_commit_hash",),
        adopted_at=datetime.now(UTC),
    )
    f.receipt = receipt
    f.receipt_path = (
        f.adapter.output_root / "native-adoptions" / ("sha256-" + receipt.content_hash + ".json")
    )
    atomic_write_bytes(f.receipt_path, receipt.canonical_bytes())
    return f


def test_native_adoption_reproduces_originals_without_transferring_parent_qualification(adoption):
    f = adoption
    f.adapter._verify_adoption_origin(f.request, f.origin)
    assert f.adapter._native_adoption_hashes(f.request) == (f.receipt.content_hash,)
    assert f.receipt.new_scientific_execution is False
    assert f.receipt.parent_execution_status == "NOT_ASSERTED"
    assert f.receipt.original_stage_status == "SUCCEEDED"


@pytest.mark.parametrize(
    "damage", ["request", "science", "checkpoint", "completion", "pit", "relative", "absent"]
)
def test_origin_adoption_rejects_missing_changed_or_failed_originals(adoption, damage):
    f = adoption
    origin = f.origin
    if damage == "request":
        from pathlib import Path

        Path(origin.request_path).write_bytes(b"{}")
    elif damage == "science":
        f.request = f.request.model_copy(update={"snapshot_hash": "f" * 64})
    elif damage == "checkpoint":
        origin = origin.model_copy(update={"signal_checkpoint_hash": "f" * 64})
    elif damage == "completion":
        from pathlib import Path

        path = next(Path(origin.signal_checkpoint_path).parent.rglob("completion.json"))
        import json

        value = json.loads(path.read_bytes())
        value["status"] = "FAILED"
        path.write_bytes(canonical_json_bytes(value))
    elif damage == "pit":
        f.old_signal.pit_evidence_hash = "f" * 64
    elif damage == "relative":
        origin = origin.model_copy(update={"request_path": "relative.json"})
    else:
        f.adapter.discovery_source_adoption = None
    with pytest.raises((AutonomousOrchestrationError, ArtifactIntegrityError, ValueError)):
        f.adapter._verify_adoption_origin(f.request, origin)


@pytest.mark.parametrize(
    "damage", ["bytes", "symlink", "receipt", "identity", "resolved", "ambiguous", "missing"]
)
def test_native_receipt_requires_exact_authority_and_unchanged_scientific_bytes(adoption, damage):
    f = adoption
    if damage == "bytes":
        (f.new_path / "native.csv").write_bytes(b"changed")
    elif damage == "symlink":
        path = f.new_path / "native.csv"
        path.unlink()
        path.symlink_to(f.old_path / "native.csv")
    elif damage == "receipt":
        f.receipt_path.write_bytes(f.receipt_path.read_bytes() + b"\n")
    elif damage == "identity":
        f.request = f.request.model_copy(update={"code_commit_hash": "f" * 40})
    elif damage == "resolved":
        f.new_signal.resolved_experiment_hash = "f" * 64
    elif damage == "ambiguous":
        path = f.new_path.parent / ("sha256-" + "d" * 64)
        atomic_write_bytes(path / "resolved-experiment.json", f.new_resolved.canonical_bytes())
    else:
        f.receipt_path.unlink()
        atomic_write_bytes(f.new_path / "manifest.json", b"{}")
    with pytest.raises((AutonomousOrchestrationError, ArtifactIntegrityError, ValueError)):
        f.adapter._native_adoption_hashes(f.request)
