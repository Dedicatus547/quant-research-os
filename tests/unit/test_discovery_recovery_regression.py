"""Bounded offline recovery contracts; synthetic stages never grant science authority."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_offline_regression import frozen_store

from quantos.application import autonomous_execution as native
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.discovery_execution import DiscoveryExecutionService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_adoption import DiscoveryEvaluationSourceAdoption
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration


@pytest.fixture
def staged(design, durable):
    store, batch = frozen_store(design, durable / "generation")
    service = DiscoveryExecutionService(
        batch=batch,
        generation_root=store.root,
        snapshot_path=durable / "no-snapshot",
        qlib_view_path=durable / "no-view",
        output_root=durable / "execution",
        workspace=durable,
    )
    request = service.task_request(batch.subtasks[0].content_hash)
    adapter = object.__new__(native.QuantosResearchExecutionAdapter)
    adapter.output_root = durable / "stages"
    adapter.workspace = durable
    adapter._discovery_runtime_hash = "a" * 64
    return SimpleNamespace(
        adapter=adapter, request=request, service=service, store=store, batch=batch
    )


def run_stage(f, build, verify, *, inputs=None, recover=None):
    return f.adapter._discovery_stage(
        f.request,
        "synthetic-stage",
        inputs or {"dependency": "b" * 64},
        build,
        verify,
        recover,
    )


def test_stage_reuse_verifies_originals_and_changed_inputs_build_separately(staged):
    f = staged
    calls = []
    outputs = {"artifact_hash": "c" * 64}

    def build():
        calls.append("build")
        return outputs

    def verify(value):
        assert value == outputs
        calls.append("verify")
        return value

    assert run_stage(f, build, verify) == outputs
    assert run_stage(f, build, verify) == outputs
    assert calls == ["build", "verify", "verify"]
    run_stage(f, build, verify, inputs={"dependency": "d" * 64})
    assert calls.count("build") == 2
    for path in f.adapter.output_root.rglob("completion.json"):
        record = json.loads(path.read_bytes())
        assert record["status"] == "SUCCEEDED" and record["process_exit"] is None
        assert record["wall_seconds"] >= 0


def test_interrupted_stage_adopts_only_after_reservation_without_invented_time(staged):
    f = staged

    def interrupted():
        raise RuntimeError("unit interruption")

    with pytest.raises(RuntimeError):
        run_stage(f, interrupted, lambda x: x)
    failed = next(f.adapter.output_root.rglob("completion.json"))
    original = failed.read_bytes()
    recovered = {"artifact_hash": "c" * 64}
    assert run_stage(f, interrupted, lambda x: x, recover=lambda: recovered) == recovered
    assert failed.read_bytes() == original
    completion = sorted(f.adapter.output_root.rglob("completion.json"))[-1]
    record = json.loads(completion.read_bytes())
    assert record["status"] == "ADOPTED"
    assert record["wall_seconds"] is record["cpu_seconds"] is record["process_exit"] is None
    assert run_stage(f, interrupted, lambda x: x) == recovered


@pytest.mark.parametrize("damage", ["checkpoint", "reservation", "symlink", "output"])
def test_completed_stage_never_trusts_damaged_checkpoint_or_output(staged, damage):
    f = staged
    output = {"artifact_hash": "c" * 64}
    run_stage(f, lambda: output, lambda x: x)
    root = f.adapter.output_root / "execution-checkpoints" / f.request.execution_identity
    checkpoint = next(root.glob("synthetic-stage/sha256-*.json"))
    reservation = next(root.rglob("reservation.json"))
    if damage == "checkpoint":
        checkpoint.write_bytes(checkpoint.read_bytes() + b"\n")
    elif damage == "reservation":
        reservation.write_bytes(b"{}")
    elif damage == "symlink":
        content = checkpoint.read_bytes()
        target = root / "copied.json"
        target.write_bytes(content)
        checkpoint.unlink()
        checkpoint.symlink_to(target)

    def verify(value):
        if damage == "output":
            raise ArtifactIntegrityError("retained output changed")
        return value

    with pytest.raises((ArtifactIntegrityError, AutonomousOrchestrationError)):
        run_stage(f, lambda: pytest.fail("damaged authority must not rebuild"), verify)


def test_failed_reservation_cannot_be_rebound_and_new_stage_verifies_provenance(
    staged, monkeypatch
):
    f = staged

    def fail():
        raise RuntimeError("failed synthetic stage")

    with pytest.raises(RuntimeError):
        run_stage(f, fail, lambda x: x)
    path = next(f.adapter.output_root.rglob("reservation.json"))
    path.write_bytes(b"{}")
    with pytest.raises(AutonomousOrchestrationError, match="reservation"):
        run_stage(f, lambda: pytest.fail("must reject"), lambda x: x)
    f.adapter._discovery_runtime_hash = None
    checked = []
    monkeypatch.setattr(native, "verify_code_provenance", lambda *a, **kw: checked.append(kw))
    monkeypatch.setattr(
        native, "capture_runtime_fingerprint", lambda: SimpleNamespace(content_hash="f" * 64)
    )
    run_stage(f, lambda: {"result": "e" * 64}, lambda x: x, inputs={"new": True})
    assert checked == [
        {
            "expected_commit_hash": f.request.code_commit_hash,
            "expected_lockfile_hash": f.request.lockfile_hash,
        }
    ]


def successor(f):
    bindings = f.batch.design.bindings.model_copy(
        update={"code_commit_hash": "e" * 40, "execution_policy_hash": "f" * 64}
    )
    adoption = DiscoveryEvaluationSourceAdoption(
        original_batch_hash=f.batch.content_hash,
        original_design_hash=f.batch.design.content_hash,
        original_source_commit=f.batch.design.bindings.code_commit_hash,
        evaluation_source_commit=bindings.code_commit_hash,
        lockfile_hash=bindings.lockfile_hash,
        evaluation_execution_policy_hash=bindings.execution_policy_hash,
        original_workspace=str(f.service.workspace),
        original_capsule_hash="a" * 64,
        evaluation_capsule_hash="b" * 64,
        source_delta_record_hash="c" * 64,
        supersession_cutoff_hash="d" * 64,
        variants=(),
    )
    declaration = DiscoveryEvaluationDeclaration(
        original_batch_hash=f.batch.content_hash,
        original_design_hash=f.batch.design.content_hash,
        original_generation_source_commit=f.batch.design.bindings.code_commit_hash,
        bindings=bindings,
        max_compute_units=f.batch.design.max_compute_units,
        source_adoption_record_hash=adoption.content_hash,
        exposure_history_append=("Synthetic regression; no sealed data accessed.",),
    )
    return adoption, declaration


def create_successor(f, root, adoption, declaration):
    atomic_write_bytes(root / "source-adoption.json", adoption.canonical_bytes())
    return DiscoveryExecutionService(
        batch=f.batch,
        generation_root=f.store.root,
        snapshot_path=f.service.snapshot_path,
        qlib_view_path=f.service.qlib_view_path,
        output_root=root,
        workspace=f.service.workspace,
        evaluation_declaration=declaration,
    )


def test_explicit_successor_keeps_old_proposals_and_requires_its_saved_authority(staged):
    f = staged
    adoption, declaration = successor(f)
    service = create_successor(f, f.service.workspace / "successor", adoption, declaration)
    service._save_evaluation_authority()
    assert service.evaluation_metadata()["no_new_generation"] is True
    assert service.evaluation_metadata()["original_batch_hash"] == f.batch.content_hash
    assert service.evaluation_metadata()["sealed_confirmation_accessed"] is False
    request = service.task_request(f.batch.subtasks[0].content_hash)
    assert request.code_commit_hash == declaration.bindings.code_commit_hash
    assert request.candidate == f.request.candidate
    assert (
        create_successor(f, service.output_root, adoption, declaration).quote() == service.quote()
    )
    (service.output_root / "evaluation-authority.json").write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError, match="different declaration"):
        create_successor(f, service.output_root, adoption, declaration)


@pytest.mark.parametrize(
    "damage", ["batch", "design", "commit", "budget", "lock", "source", "orphan"]
)
def test_successor_rejects_scientific_dependency_or_authority_substitution(staged, damage):
    f = staged
    adoption, declaration = successor(f)
    root = f.service.workspace / "successor"
    if damage in ("batch", "design"):
        declaration = declaration.model_copy(update={"original_" + damage + "_hash": "f" * 64})
    elif damage == "commit":
        declaration = declaration.model_copy(update={"bindings": f.batch.design.bindings})
    elif damage == "budget":
        declaration = declaration.model_copy(
            update={"max_compute_units": f.batch.design.max_compute_units + 1}
        )
    elif damage == "lock":
        declaration = declaration.model_copy(
            update={"bindings": declaration.bindings.model_copy(update={"lockfile_hash": "e" * 64})}
        )
    elif damage == "source":
        adoption = adoption.model_copy(update={"original_capsule_hash": "f" * 64})
    else:
        atomic_write_bytes(root / "batch.json", b"{}")
    with pytest.raises(ArtifactIntegrityError):
        create_successor(f, root, adoption, declaration)


@pytest.mark.parametrize(
    "reserved,estimated", [(4096, 1024), (1024, 4096), (True, 1024), (4096, False)]
)
def test_storage_authority_cannot_exceed_the_original_entire_job_reservation(
    staged, monkeypatch, reserved, estimated
):
    from quantos.application import discovery_execution as execution
    from quantos.infrastructure.hosted_storage import StorageRejected

    f = staged
    root = f.service.workspace / "synthetic-lease"
    atomic_write_bytes(
        root / "prelaunch.json", canonical_json_bytes({"expected_new_bytes": reserved})
    )
    monkeypatch.setenv(execution.LEASE_ENV, str(root))
    checked = []
    guard = SimpleNamespace(
        policy_hash="a" * 64,
        require_root=lambda p: checked.append(p),
        require_lease=lambda: checked.append("lease"),
        check=lambda n: {"synthetic_available": 8192},
    )
    monkeypatch.setattr(execution, "configured_guard", lambda: guard)
    if type(reserved) is int and type(estimated) is int and reserved >= estimated:
        observed, facts = f.service._storage_authority(estimated)
        assert observed is guard and facts["lease_reserved_new_bytes"] == reserved
        assert facts["growth_scope"] == "ENTIRE_BATCH_AND_ALL_CONCURRENT_LEASE_CHILDREN"
        assert facts["lease_prelaunch_hash"] == sha256_bytes((root / "prelaunch.json").read_bytes())
    else:
        with pytest.raises(StorageRejected):
            f.service._storage_authority(estimated)


def test_adapter_inspection_is_cached_and_creates_no_task_authority(staged, monkeypatch):
    from quantos.application import discovery_execution as execution

    f = staged
    constructed = []

    class ReadonlyAdapter:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def inspect_completed_execution(self, request):
            return None

    monkeypatch.setattr(execution, "QuantosResearchExecutionAdapter", ReadonlyAdapter)
    task = f.batch.subtasks[0].content_hash
    assert f.service.inspect_completed_execution(task) is None
    assert f.service.inspect_completed_execution(task) is None
    assert len(constructed) == 1
    assert constructed[0]["discovery_stage_recovery"] is True
    assert not f.service.output_root.exists()
    with pytest.raises(ValueError):
        f.service.task_request("f" * 64)


@pytest.mark.parametrize("damage", [None, "reservation", "completion", "measurement", "recovery"])
def test_unfinished_task_costs_stay_unknown_and_tampering_cannot_reset_budget(staged, damage):
    f = staged
    service = f.service
    key = f.batch.subtasks[0].content_hash
    request = f.request
    root = service._task_root(key) / "attempts/00000001"
    reservation = {
        "schema_version": "discovery-execution-attempt-reservation/v1",
        "batch_hash": f.batch.content_hash,
        "subtask_hash": key,
        "request_hash": request.content_hash,
        "execution_identity": request.execution_identity,
        "ordinal": 1,
    }
    atomic_write_bytes(root / "reservation.json", canonical_json_bytes(reservation))
    if damage is None:
        state = service.task_state(key, inspection=None)
        assert state["status"] == "UNFINISHED" and state["wall_seconds"] is None
        assert state["attempt_count"] == 1 and state["observed_cpu_seconds"] is None
        return
    if damage == "reservation":
        reservation["request_hash"] = "f" * 64
        (root / "reservation.json").write_bytes(canonical_json_bytes(reservation))
    elif damage == "recovery":
        atomic_write_bytes(
            service.output_root / "recovery-reservations" / key / "00000002.json",
            canonical_json_bytes({"ordinal": True}),
        )
    else:
        completed = {
            "request_hash": request.content_hash,
            "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
            "status": "FAILED",
            "wall_seconds": True if damage == "measurement" else 1.0,
            "cpu_seconds": 0.0,
        }
        if damage == "completion":
            completed["request_hash"] = "f" * 64
        atomic_write_bytes(root / "completion.json", canonical_json_bytes(completed))
    with pytest.raises(ArtifactIntegrityError):
        service.task_state(key, inspection=None)


@pytest.mark.parametrize(
    "damage",
    [
        "json-kind",
        "noncanonical",
        "inspection",
        "cross-task",
        "recovery-binding",
        "unreserved-recovery",
    ],
)
def test_readonly_execution_records_require_exact_types_tasks_and_recovery_charge(staged, damage):
    from quantos.application import discovery_execution as execution
    from quantos.contracts.autonomous import AutonomousExecutionResult

    f = staged
    service = f.service
    key = f.batch.subtasks[0].content_hash
    if damage in ("json-kind", "noncanonical"):
        path = service.workspace / "bad-record.json"
        atomic_write_bytes(path, b"[]" if damage == "json-kind" else b"{}\n")
        with pytest.raises(ArtifactIntegrityError):
            execution._read_json(path)
        return
    if damage == "inspection":
        with pytest.raises(ValueError):
            service.task_state(key, inspection=object())
        return
    if damage == "cross-task":
        changed = f.request.model_copy(update={"family_hash": "f" * 64})
        outcome = AutonomousExecutionResult(
            request_hash=changed.content_hash,
            outcome="PIT_REJECT",
            execution_requested=False,
            compute_seconds=0,
        )
        inspection = execution.DiscoveryExecutionInspection(changed, outcome, SimpleNamespace())
        with pytest.raises(ArtifactIntegrityError):
            service.task_state(key, inspection=inspection)
        return
    if damage == "recovery-binding":
        path = service.output_root / "recovery-reservations" / key / "00000002.json"
        atomic_write_bytes(path, canonical_json_bytes({"ordinal": 2}))
        with pytest.raises(ArtifactIntegrityError):
            service._recovery_reservations()
    else:
        for ordinal in (1, 2):
            reservation = {
                "schema_version": "discovery-execution-attempt-reservation/v1",
                "batch_hash": f.batch.content_hash,
                "subtask_hash": key,
                "request_hash": f.request.content_hash,
                "execution_identity": f.request.execution_identity,
                "ordinal": ordinal,
            }
            atomic_write_bytes(
                service._task_root(key) / "attempts" / f"{ordinal:08d}" / "reservation.json",
                canonical_json_bytes(reservation),
            )
        with pytest.raises(ArtifactIntegrityError, match="compute reservation"):
            service._attempt_records(key)
