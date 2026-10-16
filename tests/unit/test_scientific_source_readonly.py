"""Source adoption checks on tiny synthetic files; no execution or qualification."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_prediction_cohort_reporting import cohort_probe as cohort_probe

from quantos.application import discovery_scientific_adoption as adoption
from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_prediction import PredictionFileSource


def pin(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("hash", "SCIENTIFIC_ORIGIN_HASH_MISMATCH"),
        ("limit", "SCIENTIFIC_ORIGIN_METADATA_LIMIT"),
        ("alias", "SCIENTIFIC_ORIGIN_PATH_ALIAS"),
        ("json", "SCIENTIFIC_ORIGIN_METADATA_INVALID"),
        ("canonical", "SCIENTIFIC_ORIGIN_NOT_CANONICAL"),
    ],
)
def test_origin_metadata_checks_actual_bytes_and_paths(tmp_path, damage, reason):
    reference = pin(tmp_path / "original.json", canonical_json_bytes({"source": "fixture"}))
    if damage == "hash":
        (tmp_path / "original.json").write_bytes(b"{}")
    elif damage == "limit":
        with pytest.raises(ValueError, match=reason):
            adoption._read(reference, cap=1)
        return
    elif damage == "alias":
        alias = tmp_path / "alias.json"
        alias.symlink_to(reference.path)
        reference = reference.model_copy(update={"path": str(alias)})
    else:
        reference = pin(
            tmp_path / "original.json", b"[]" if damage == "json" else b'{"source": "fixture"}\n'
        )
    with pytest.raises(ValueError, match=reason):
        adoption._metadata(reference)


@pytest.mark.parametrize("damage", [None, "source", "incomplete", "duplicate", "capsule"])
def test_scientific_dependencies_require_both_actual_source_trees(tmp_path, damage):
    old, new = tmp_path / "original", tmp_path / "evaluation"
    old.mkdir()
    new.mkdir()
    names = adoption.required_scientific_dependency_paths(old)
    entries = []
    refs = []
    for workspace, commit in ((old, "1" * 40), (new, "2" * 40)):
        for name in names:
            pin(workspace / name, b"synthetic offline source\n")
        inv = pin(
            workspace / "inventory.json",
            canonical_json_bytes({"schema_version": "post-hm-source-inventory/v1"}),
        )
        capsule = pin(
            workspace / "capsule.json",
            canonical_json_bytes(
                {
                    "workspace": str(workspace),
                    "actual_commit": commit,
                    "lockfile_hash": "a" * 64,
                    "source_inventory_hash": inv.sha256,
                }
            ),
        )
        refs.append((capsule, inv))
    for name in names:
        digest = sha256_file(old / name)
        entries.append(
            SimpleNamespace(logical_path=name, source_hash=digest, evaluation_hash=digest)
        )
    source = SimpleNamespace(
        original_workspace=str(old),
        evaluation_workspace=str(new),
        original_source_commit="1" * 40,
        evaluation_source_commit="2" * 40,
        original_capsule=refs[0][0],
        original_inventory=refs[0][1],
        evaluation_capsule=refs[1][0],
        evaluation_inventory=refs[1][1],
        lockfile_hash="a" * 64,
        scientific_files=tuple(entries),
    )
    adoption._dependencies(source)
    if damage is None:
        return
    if damage == "source":
        (new / names[0]).write_bytes(b"changed science")
    elif damage == "incomplete":
        source.scientific_files = source.scientific_files[1:]
    elif damage == "duplicate":
        source.scientific_files += source.scientific_files[:1]
    else:
        source.evaluation_source_commit = "3" * 40
    with pytest.raises(ValueError, match="SCIENTIFIC_"):
        adoption._dependencies(source)


def test_missing_scientific_declaration_never_becomes_execution_authority():
    with pytest.raises(ValueError, match="SCIENTIFIC_DECLARATION_REQUIRED"):
        adoption.verify_scientific_adoption_plan(SimpleNamespace(evaluation_declaration=None))


@pytest.mark.parametrize(
    "native,damage",
    [
        (False, None),
        (True, None),
        (True, "native"),
        (False, "request"),
        (False, "cohort"),
        (False, "authority"),
    ],
)
def test_adopted_task_keeps_exact_receipt_and_never_reexecutes(
    staged, cohort_probe, tmp_path, monkeypatch, native, damage
):
    from test_prediction_cohort_reporting import write_reference

    from quantos.application.autonomous_execution import AutonomousExecutionReceipt
    from quantos.contracts.autonomous import AutonomousExecutionResult
    from quantos.contracts.discovery_scientific_adoption import (
        ScientificAdoptedOrigin,
        ScientificAdoptionPlan,
    )

    f, p = staged, cohort_probe
    task = f.batch.subtasks[0]
    request = f.service.task_request(task.content_hash)
    task_root = tmp_path / "old-task"
    failure = AutonomousExecutionResult(
        request_hash=request.content_hash,
        outcome="EXECUTION_FAILED",
        execution_requested=True,
        compute_seconds=18,
    )
    receipt = AutonomousExecutionReceipt(request=request, outcome=failure)
    outcome = failure.model_copy(
        update={
            "execution_artifact_hash": receipt.content_hash,
            "evidence_hashes": (receipt.content_hash,),
        }
    )
    native_root = (
        task_root
        / "executions"
        / request.execution_identity
        / "qlib-workflow/native-records"
        / ("sha256-" + request.execution_identity)
    )
    files = (
        tuple(
            pin(native_root / name, b"synthetic native bytes only")
            for name in sorted(adoption._NATIVE_FILES)
        )
        if native
        else ()
    )
    origin = ScientificAdoptedOrigin(
        target_subtask_hash=task.content_hash,
        source_subtask_hash=task.content_hash,
        source_request=write_reference(task_root / "request.json", request),
        source_outcome=write_reference(task_root / "outcome.json", outcome),
        source_receipt=write_reference(
            task_root / "execution-records/identities" / (request.execution_identity + ".json"),
            receipt,
        ),
        source_subtask=write_reference(tmp_path / "subtask.json", task),
        source_design=write_reference(tmp_path / "batch.json", f.batch),
        source_task_root=str(task_root),
        source_native_root=str(native_root) if native else None,
        native_files=files,
    )
    dependency = SimpleNamespace(
        content_hash="f" * 64,
        original_source_commit=request.code_commit_hash,
        lockfile_hash=request.lockfile_hash,
    )
    remaining = tuple(t.content_hash for t in f.batch.subtasks[1:])
    plan = ScientificAdoptionPlan(
        original_sequential_batch_hash=p.service.sequential_batch.content_hash,
        original_batch_hash=f.batch.content_hash,
        scientific_dependency_adoption_hash=dependency.content_hash,
        new_subtask_hashes=remaining,
        origins=(origin,),
    )
    root = tmp_path / "successor"
    write_reference(root / "scientific-adoption-plan.json", plan)
    declaration = p.service.evaluation_declaration.model_copy(
        update={"scientific_adoption_plan_hash": plan.content_hash}
    )
    service = SimpleNamespace(
        evaluation_declaration=declaration,
        output_root=root,
        scientific_dependency_adoption=dependency,
        sequential_batch=p.service.sequential_batch,
        batch=f.batch,
    )
    # Dependency verification has its own real two-tree tests above. This scope
    # tests task/receipt/native-byte binding, never data/PIT or a science verdict.
    monkeypatch.setattr(adoption, "_dependencies", lambda _: None)
    before = Path(origin.source_outcome.path).read_bytes()
    if damage == "native":
        Path(files[0].path).write_bytes(b"changed")
    elif damage == "request":
        dependency.original_source_commit = "0" * 40
    elif damage == "cohort":
        service.batch = f.batch.model_copy(update={"subtasks": ()})
    elif damage == "authority":
        service.scientific_dependency_adoption = None
    if damage:
        with pytest.raises(ValueError, match="SCIENTIFIC_"):
            adoption.verify_scientific_adoption_plan(service)
    else:
        result = adoption.verify_scientific_adoption_plan(service)
        assert result.source_requests == (request,) and result.origins == (origin,)
        assert result.new_subtask_hashes == remaining
        assert Path(origin.source_outcome.path).read_bytes() == before
        assert outcome.research_result_hash is None and outcome.validation_report_hash is None
