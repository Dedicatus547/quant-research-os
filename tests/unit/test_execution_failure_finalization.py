"""Offline management closure tests; fixture exits are not live evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_autonomous_campaign import _proposal
from test_hosted_campaign import _fixture, _response

import quantos.application.execution_failure_finalization as finalization
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
)
from quantos.application.hosted_campaign import HostedCampaignInputs
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.hosted import HostedResearchBudgetFact


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Authority durability is checked in production; pytest scratch is test only.
    monkeypatch.setattr(finalization, "require_durable_execution_root", lambda _: None)
    f = _fixture(tmp_path)
    adapter = object.__new__(QuantosResearchExecutionAdapter)
    adapter.output_root = tmp_path / "native-execution"
    monkeypatch.setattr(adapter, "_verify_request", lambda _: None)
    monkeypatch.setattr(adapter, "execution_compute_charge", lambda _: 1)
    calls = []

    def failed_execute(request):
        calls.append(request.execution_identity)
        adapter._reserve_trial_identity(request)
        raise RuntimeError("test-only retained controller failure")

    monkeypatch.setattr(adapter, "execute", failed_execute)
    o = f.inputs.orchestrator(tmp_path, (_proposal(f.inputs, 0),), execution=adapter)
    f.service.register_inputs(
        f.spec, HostedCampaignInputs(o, f.inputs.initial_events, lambda _: None)
    )
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    with pytest.raises(RuntimeError, match="test-only"):
        f.service.resume(f.spec.campaign_hash)
    state = f.service.protocol.store.snapshot(f.spec.campaign_hash, recover=False)
    facts = f.service.verify_research_facts(state)
    intent = next(item for item in facts.steps if item.phase == "STARTED")
    reservation = next(item for item in facts.budgets if item.phase == "RESERVED")
    baseline = state.artifact(reservation.previous_hash, HostedResearchBudgetFact)
    originals = tmp_path / "originals"
    paths = {}
    for name, item in (
        ("started_intent", intent),
        ("reservation", reservation),
        ("baseline", baseline),
    ):
        paths[f"{name}_path"] = originals / f"{name}.json"
        paths[f"{name}_hash"] = item.content_hash
        atomic_write_bytes(paths[f"{name}_path"], item.canonical_bytes())
    controller = tmp_path / "controller"
    controller.mkdir()
    exit_data = {
        "exit_code": 1,
        "error_class": "MlflowException",
        "finished_utc": "2026-10-13T06:21:54+00:00",
        "failure_frames": [
            {"filename": filename, "function": function}
            for filename, function in (
                ("autonomous_execution.py", "_execute_pipeline"),
                ("workflow.py", "run"),
                ("file_store.py", "create_run"),
                ("file_store.py", "set_tag"),
                ("file_store.py", "_get_run_info"),
            )
        ],
    }
    (controller / "exit.json").write_bytes(canonical_json_bytes(exit_data))
    (controller / "loaded.json").write_bytes(
        canonical_json_bytes(
            {"campaign_hash": f.spec.campaign_hash, "spec_hash": f.spec.content_hash}
        )
    )
    (controller / "request-1.json").write_bytes(request.canonical_bytes())
    (controller / "before-step-1.json").write_bytes(
        canonical_json_bytes({"request_hash": request.content_hash})
    )
    paths.update(
        controller_directory=controller,
        expected_exit_hash=sha256_bytes((controller / "exit.json").read_bytes()),
        expected_loaded_hash=sha256_bytes((controller / "loaded.json").read_bytes()),
        expected_controller_request_hash=request.content_hash,
        expected_management_source_hash=sha256_bytes(Path(finalization.__file__).read_bytes()),
    )
    return f, adapter, calls, paths, intent


def test_retained_failure_publishes_native_receipt_and_settles_without_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f, adapter, calls, kwargs, intent = _case(tmp_path, monkeypatch)
    original_bytes = {path: path.read_bytes() for path in (tmp_path / "originals").iterdir()}
    result = finalization.finalize_retained_mlflow_failure(adapter, **kwargs)
    assert result.outcome is TrialOutcome.EXECUTION_FAILED
    assert result.execution_requested and result.compute_seconds == 1
    assert result.research_result_hash is None and result.validation_report_hash is None
    assert adapter.inspect_completed_execution(intent.execution_request) == result
    assert finalization.finalize_retained_mlflow_failure(adapter, **kwargs) == result
    assert len(calls) == 1
    f.service.resume(f.spec.campaign_hash)
    state = f.service.protocol.store.snapshot(f.spec.campaign_hash, recover=False)
    facts = f.service.verify_research_facts(state)
    assert facts.budgets[-1].phase == "SETTLED"
    assert facts.budgets[-1].used_executions == 1
    assert facts.budgets[-1].used_compute_units == 1
    assert any(item.phase == "COMPLETED" and item.trial_hash for item in facts.steps)
    assert len(calls) == 1
    assert all(path.read_bytes() == encoded for path, encoded in original_bytes.items())


@pytest.mark.parametrize("change", ["hash", "exit", "frame", "campaign", "reservation"])
def test_recovery_rejects_mismatched_proofs_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _, adapter, calls, kwargs, _ = _case(tmp_path, monkeypatch)
    controller = kwargs["controller_directory"]
    if change == "hash":
        kwargs["expected_exit_hash"] = "0" * 64
    elif change in {"exit", "frame"}:
        path = controller / "exit.json"
        value = json.loads(path.read_bytes())
        if change == "exit":
            value["exit_code"] = 0
        else:
            value["failure_frames"] = value["failure_frames"][:-1]
        path.write_bytes(canonical_json_bytes(value))
        kwargs["expected_exit_hash"] = sha256_bytes(path.read_bytes())
    elif change == "campaign":
        path = controller / "loaded.json"
        value = json.loads(path.read_bytes())
        value["campaign_hash"] = "0" * 64
        path.write_bytes(canonical_json_bytes(value))
        kwargs["expected_loaded_hash"] = sha256_bytes(path.read_bytes())
    else:
        path = kwargs["reservation_path"]
        value = HostedResearchBudgetFact.model_validate_json(path.read_bytes())
        value = value.model_copy(update={"used_compute_units": 2})
        path.write_bytes(value.canonical_bytes())
        kwargs["reservation_hash"] = value.content_hash
    with pytest.raises(ArtifactIntegrityError):
        finalization.finalize_retained_mlflow_failure(adapter, **kwargs)
    assert not (adapter.output_root / "execution-records").exists()
    assert not (adapter.output_root / "execution-failures").exists()
    assert len(calls) == 1


def test_receipt_index_publication_recovers_without_second_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, adapter, calls, kwargs, _ = _case(tmp_path, monkeypatch)
    result = finalization.finalize_retained_mlflow_failure(adapter, **kwargs)
    index = (
        adapter.output_root
        / "execution-record-artifacts"
        / f"sha256-{result.execution_artifact_hash}.json"
    )
    index.unlink()
    assert finalization.finalize_retained_mlflow_failure(adapter, **kwargs) == result
    receipt = AutonomousExecutionReceipt.model_validate_json(index.read_bytes())
    assert receipt.content_hash == result.execution_artifact_hash
    assert len(calls) == 1


@pytest.mark.parametrize("tampered", [False, True])
def test_existing_failure_receipt_requires_original_management_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tampered: bool
) -> None:
    _, adapter, calls, kwargs, _ = _case(tmp_path, monkeypatch)
    result = finalization.finalize_retained_mlflow_failure(adapter, **kwargs)
    witness = next((adapter.output_root / "failure-finalizations").iterdir())
    encoded = witness.read_bytes()
    if tampered:
        witness.write_bytes(b"{}")
        with pytest.raises(ArtifactConflictError):
            finalization.finalize_retained_mlflow_failure(adapter, **kwargs)
        assert witness.read_bytes() == b"{}"
    else:
        witness.unlink()
        assert finalization.finalize_retained_mlflow_failure(adapter, **kwargs) == result
        assert witness.read_bytes() == encoded
    assert len(calls) == 1
