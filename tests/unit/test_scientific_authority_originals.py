"""Independent scientific scope requires its retained authorization and source capsules."""

from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged

from quantos.application import discovery_execution as module
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_evaluation import (
    ScientificEvaluationDeclaration,
    ScientificExecutionAuthorization,
    ScientificSchedulingCutoff,
)


@pytest.fixture
def authority(staged):
    f = staged
    service = f.service
    root = service.output_root
    root.mkdir(parents=True, exist_ok=True)
    wrapper = SimpleNamespace(content_hash="a" * 64, policy=SimpleNamespace(content_hash="b" * 64))
    service.sequential_batch = wrapper
    authorization = ScientificExecutionAuthorization(
        user_instruction="Synthetic engineering only; never execute",
        original_sequential_batch_hash=wrapper.content_hash,
    )
    cutoff = ScientificSchedulingCutoff(
        original_sequential_batch_hash=wrapper.content_hash,
        original_batch_hash=f.batch.content_hash,
        original_design_hash=f.batch.design.content_hash,
        authorization_hash=authorization.content_hash,
    )
    bindings = f.batch.design.bindings.model_copy(update={"code_commit_hash": "f" * 40})
    capsules = [
        {
            "schema_version": "post-hm-source-capsule/v1",
            "actual_commit": commit,
            "lockfile_hash": bindings.lockfile_hash,
        }
        for commit in (f.batch.design.bindings.code_commit_hash, bindings.code_commit_hash)
    ]
    charge = module.quote_discovery_workload(f.batch)
    declaration = ScientificEvaluationDeclaration(
        original_sequential_batch_hash=wrapper.content_hash,
        original_generation_policy_hash=wrapper.policy.content_hash,
        original_batch_hash=f.batch.content_hash,
        original_design_hash=f.batch.design.content_hash,
        original_generation_source_commit=f.batch.design.bindings.code_commit_hash,
        original_generation_source_declaration_hash=sha256_bytes(canonical_json_bytes(capsules[0])),
        evaluation_source_declaration_hash=sha256_bytes(canonical_json_bytes(capsules[1])),
        snapshot_hash=f.batch.design.snapshot_hash,
        qlib_view_hash=f.batch.design.qlib_view_hash,
        authorization_hash=authorization.content_hash,
        scientific_scheduling_cutoff_hash=cutoff.content_hash,
        budget={
            "full_batch_compute_units": charge,
            "new_execution_compute_units": charge,
            "max_compute_units": charge,
            "max_distinct_candidates": len(f.batch.subtasks),
            "max_new_candidate_executions": len(f.batch.subtasks),
        },
        bindings=bindings,
        exposure_history_append=("Synthetic offline scope test only",),
    )
    originals = {
        "scientific-authorization.json": authorization.canonical_bytes(),
        "scientific-scheduling-cutoff.json": cutoff.canonical_bytes(),
        "original-generation-source.json": canonical_json_bytes(capsules[0]),
        "evaluation-source.json": canonical_json_bytes(capsules[1]),
    }
    for name, raw in originals.items():
        (root / name).write_bytes(raw)
    service.evaluation_declaration = declaration
    service._scientific_verified_adoption = None
    return f


@pytest.mark.parametrize(
    "attack",
    [
        "valid",
        "authorization",
        "cutoff",
        "generation_source",
        "evaluation_source",
        "wrapper",
        "snapshot",
        "budget",
        "reduced",
        "adoption",
    ],
)
def test_scientific_evaluation_cannot_rebind_old_authority_or_silently_reduce_work(
    authority, attack
):
    f = authority
    service = f.service
    declaration = service.evaluation_declaration
    names = {
        "authorization": "scientific-authorization.json",
        "cutoff": "scientific-scheduling-cutoff.json",
        "generation_source": "original-generation-source.json",
        "evaluation_source": "evaluation-source.json",
    }
    if attack in names:
        import json

        path = service.output_root / names[attack]
        value = json.loads(path.read_bytes())
        key = (
            "user_instruction"
            if attack == "authorization"
            else "original_batch_hash"
            if attack == "cutoff"
            else "actual_commit"
        )
        value[key] = (
            "changed" if attack == "authorization" else "0" * (40 if "source" in attack else 64)
        )
        path.write_bytes(canonical_json_bytes(value))
    elif attack == "wrapper":
        service.sequential_batch = None
    elif attack == "snapshot":
        service.evaluation_declaration = declaration.model_copy(update={"snapshot_hash": "f" * 64})
    elif attack == "budget":
        service.evaluation_declaration = declaration.model_copy(
            update={
                "budget": declaration.budget.model_copy(update={"full_batch_compute_units": 99999})
            }
        )
    elif attack == "reduced":
        service.evaluation_declaration = declaration.model_copy(
            update={
                "budget": declaration.budget.model_copy(
                    update={"new_execution_compute_units": 0, "max_new_candidate_executions": 0}
                )
            }
        )
    elif attack == "adoption":
        (service.output_root / "scientific-adoption-plan.json").write_bytes(b"{}")
        service.evaluation_declaration = declaration.model_copy(
            update={"scientific_adoption_plan_hash": "f" * 64}
        )
    if attack == "valid":
        service._verify_evaluation_declaration()
        assert service.scientific_new_subtasks() == f.batch.subtasks
        assert service.scientific_execution_subtask_hashes() == tuple(
            x.content_hash for x in f.batch.subtasks
        )
    else:
        with pytest.raises(ArtifactIntegrityError):
            service._verify_evaluation_declaration()


@pytest.mark.parametrize(
    "attack", ["valid", "duplicate", "unknown", "count", "compute", "declaration"]
)
def test_adoption_subset_must_equal_its_independent_new_work_budget(authority, monkeypatch, attack):
    from quantos.application import discovery_scientific_adoption as adoption

    f = authority
    service = f.service
    keys = tuple(task.content_hash for task in f.batch.subtasks)
    if attack == "duplicate":
        keys *= 2
    elif attack == "unknown":
        keys = ("f" * 64,)
    elif attack in {"count", "compute"}:
        budget = service.evaluation_declaration.budget.model_copy(
            update={
                "max_new_candidate_executions"
                if attack == "count"
                else "new_execution_compute_units": 0
            }
        )
        service.evaluation_declaration = service.evaluation_declaration.model_copy(
            update={"budget": budget}
        )
    elif attack == "declaration":
        service.evaluation_declaration = None
    expected = SimpleNamespace(new_subtask_hashes=keys)
    monkeypatch.setattr(adoption, "verify_scientific_adoption_plan", lambda _: expected)
    if attack == "valid":
        service._verify_scientific_adoption()
        assert service.scientific_verified_adoption() is expected
        assert service.scientific_execution_subtask_hashes() == keys
    else:
        with pytest.raises(ArtifactIntegrityError):
            service._verify_scientific_adoption()
        assert service.scientific_verified_adoption() is None
