"""Verify a fixed reuse partition without minting new execution receipts for old work."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from quantos.application.autonomous_execution import AutonomousExecutionReceipt
from quantos.artifacts.store import confined_regular_file, sha256_file
from quantos.contracts.autonomous import AutonomousExecutionRequest, AutonomousExecutionResult
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryBatch, DiscoverySubtask
from quantos.contracts.discovery_evaluation import ScientificEvaluationDeclaration
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.discovery_scientific_adoption import (
    ScientificAdoptedOrigin,
    ScientificAdoptionPlan,
    ScientificSourceDependencyAdoption,
)
from quantos.contracts.refs import validate_logical_path
from quantos.research.qlib.expression import translate_safe_expression

if TYPE_CHECKING:
    from quantos.application.discovery_execution import DiscoveryExecutionService

_C = TypeVar("_C", bound=CanonicalContract)
_NATIVE_FILES = {
    "pred.pkl",
    "label.pkl",
    "model-data-splits.json",
    "sig_analysis/ic.pkl",
    "sig_analysis/ric.pkl",
}


@dataclass(frozen=True)
class ScientificVerifiedAdoption:
    new_subtask_hashes: tuple[str, ...]
    origins: tuple[ScientificAdoptedOrigin, ...]
    source_requests: tuple[AutonomousExecutionRequest, ...]


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _read(reference: PredictionFileSource, *, cap: int = 16 << 20) -> bytes:
    path = Path(reference.path).absolute()
    _require(path.resolve() == path, "SCIENTIFIC_ORIGIN_PATH_ALIAS")
    source = confined_regular_file(path.parent, path.name)
    _require(source.stat().st_size <= cap, "SCIENTIFIC_ORIGIN_METADATA_LIMIT")
    data = source.read_bytes()
    _require(sha256_bytes(data) == reference.sha256, "SCIENTIFIC_ORIGIN_HASH_MISMATCH")
    return data


def _contract(reference: PredictionFileSource, kind: type[_C]) -> _C:
    raw = _read(reference)
    value = kind.model_validate_json(raw)
    _require(value.canonical_bytes() == raw, "SCIENTIFIC_ORIGIN_NOT_CANONICAL")
    return value


def _metadata(reference: PredictionFileSource) -> dict[str, object]:
    raw = _read(reference)
    decoded: object = json.loads(raw)
    _require(isinstance(decoded, dict), "SCIENTIFIC_ORIGIN_METADATA_INVALID")
    value = cast(dict[str, object], decoded)
    _require(canonical_json_bytes(value) == raw, "SCIENTIFIC_ORIGIN_NOT_CANONICAL")
    return value


def required_scientific_dependency_paths(workspace: Path) -> tuple[str, ...]:
    """Bind the actual scientific engines and their frozen scientific contract surfaces."""
    roots = (
        "src/quantos/research/qlib",
        "src/quantos/data",
        "src/quantos/integrations/qlib",
        "src/quantos/backtest",
        "src/quantos/validation",
        "src/quantos/artifacts",
    )
    paths = {
        path.relative_to(workspace).as_posix()
        for root in roots
        for path in (workspace / root).rglob("*.py")
    }
    paths.update(
        f"src/quantos/contracts/{name}.py"
        for name in (
            "base",
            "autonomous",
            "cost",
            "enumeration",
            "pit",
            "research",
            "research_execution",
            "research_result",
            "snapshot",
            "status",
            "validation",
            "refs",
            "campaign",
            "model_data_split",
            "qlib_view",
            "native_adoption",
        )
    )
    paths.update(
        f"src/quantos/application/{name}.py"
        for name in (
            "pit",
            "data_qualified_release",
            "specs",
            "schedules",
            "enumeration",
            "provenance",
        )
    )
    paths.add("uv.lock")
    _require(bool(paths), "SCIENTIFIC_DEPENDENCY_SET_EMPTY")
    return tuple(sorted(paths))


def _dependencies(adoption: ScientificSourceDependencyAdoption) -> None:
    old, new = Path(adoption.original_workspace), Path(adoption.evaluation_workspace)
    for workspace, capsule_ref, inventory_ref, commit in (
        (
            old,
            adoption.original_capsule,
            adoption.original_inventory,
            adoption.original_source_commit,
        ),
        (
            new,
            adoption.evaluation_capsule,
            adoption.evaluation_inventory,
            adoption.evaluation_source_commit,
        ),
    ):
        capsule, inventory = _metadata(capsule_ref), _metadata(inventory_ref)
        _require(
            workspace.is_absolute()
            and workspace.resolve() == workspace
            and capsule.get("workspace") == str(workspace)
            and capsule.get("actual_commit") == commit
            and capsule.get("lockfile_hash") == adoption.lockfile_hash
            and capsule.get("source_inventory_hash") == inventory_ref.sha256
            and inventory.get("schema_version") == "post-hm-source-inventory/v1",
            "SCIENTIFIC_SOURCE_CAPSULE_BINDING_MISMATCH",
        )
    entries = {item.logical_path: item for item in adoption.scientific_files}
    _require(len(entries) == len(adoption.scientific_files), "SCIENTIFIC_DEPENDENCY_DUPLICATE")
    required = set(required_scientific_dependency_paths(old)) | set(
        required_scientific_dependency_paths(new)
    )
    _require(required <= set(entries), "SCIENTIFIC_DEPENDENCIES_INCOMPLETE")
    for logical, entry in entries.items():
        validate_logical_path(logical)
        _require(
            entry.source_hash
            == entry.evaluation_hash
            == sha256_file(confined_regular_file(old, logical))
            == sha256_file(confined_regular_file(new, logical)),
            "SCIENTIFIC_DEPENDENCY_CHANGED",
        )


def verify_scientific_adoption_plan(
    service: DiscoveryExecutionService,
) -> ScientificVerifiedAdoption:
    """Verify actual origin bindings and dependency equivalence, not a self-reported PASS.

    Native files are hash checked here without parsing. Data/PIT/split/statistic
    revalidation remains mandatory at successor prediction publication/consumption.
    An old source-incomplete outcome remains an unscored historical failure.
    """
    declaration = service.evaluation_declaration
    _require(
        isinstance(declaration, ScientificEvaluationDeclaration), "SCIENTIFIC_DECLARATION_REQUIRED"
    )
    declaration = cast(ScientificEvaluationDeclaration, declaration)
    _require(
        declaration.scientific_adoption_plan_hash is not None, "SCIENTIFIC_ADOPTION_PLAN_REQUIRED"
    )
    plan = _contract(
        PredictionFileSource(
            path=str(service.output_root / "scientific-adoption-plan.json"),
            sha256=cast(str, declaration.scientific_adoption_plan_hash),
        ),
        ScientificAdoptionPlan,
    )
    adoption = service.scientific_dependency_adoption
    _require(adoption is not None, "SCIENTIFIC_DEPENDENCY_ADOPTION_REQUIRED")
    adoption = cast(ScientificSourceDependencyAdoption, adoption)
    wrapper = service.sequential_batch
    _require(
        wrapper is not None
        and plan.original_sequential_batch_hash == wrapper.content_hash
        and plan.original_batch_hash == service.batch.content_hash
        and plan.scientific_dependency_adoption_hash == adoption.content_hash,
        "SCIENTIFIC_ADOPTION_PLAN_BINDING_MISMATCH",
    )
    _dependencies(adoption)
    tasks = {item.content_hash: item for item in service.batch.subtasks}
    _require(
        set(plan.new_subtask_hashes) | {item.target_subtask_hash for item in plan.origins}
        == set(tasks),
        "SCIENTIFIC_ADOPTION_COHORT_INCOMPLETE",
    )
    requests: list[AutonomousExecutionRequest] = []
    for origin in plan.origins:
        source_task = _contract(origin.source_subtask, DiscoverySubtask)
        source_batch = _contract(origin.source_design, DiscoveryBatch)
        request = _contract(origin.source_request, AutonomousExecutionRequest)
        outcome = _contract(origin.source_outcome, AutonomousExecutionResult)
        receipt = _contract(origin.source_receipt, AutonomousExecutionReceipt)
        expected_outcome = receipt.outcome.model_copy(
            update={
                "execution_artifact_hash": receipt.content_hash,
                "evidence_hashes": tuple(
                    sorted(set((*receipt.outcome.evidence_hashes, receipt.content_hash)))
                ),
            }
        )
        target = tasks[origin.target_subtask_hash]
        old_expr, new_expr = request.candidate.expression, target.manifest.candidates[0].expression
        old_translation, new_translation = (
            translate_safe_expression(old_expr),
            translate_safe_expression(new_expr),
        )
        design = service.batch.design
        _require(
            source_task.content_hash == origin.source_subtask_hash
            and source_task in source_batch.subtasks
            and request.family_hash == source_task.family.content_hash
            and request.candidate_manifest_hash == source_task.manifest.content_hash
            and request.candidate == source_task.manifest.candidates[0]
            and request.candidate_structural_expression_hash
            == target.manifest.candidates[0].structural_expression_hash
            and old_translation.output_expression == new_translation.output_expression
            and old_translation.output_name == new_translation.output_name
            and old_translation.qlib_version == new_translation.qlib_version == request.qlib_version
            and old_expr.input_lag_trading_days == new_expr.input_lag_trading_days
            and request.snapshot_hash == design.snapshot_hash
            and request.qlib_view_hash == design.qlib_view_hash
            and request.code_commit_hash == adoption.original_source_commit
            and request.lockfile_hash == adoption.lockfile_hash
            and source_batch.design.research_policy == design.research_policy
            and source_batch.design.validation_policy == design.validation_policy
            and source_batch.design.cost_policy == design.cost_policy
            and source_batch.design.backtest_policy == design.backtest_policy
            and source_batch.design.authoring.model_dump(exclude={"expression"})
            == design.authoring.model_dump(exclude={"expression"})
            and receipt.request == request
            and outcome.request_hash == request.content_hash
            and outcome.execution_artifact_hash == receipt.content_hash
            and outcome == expected_outcome,
            "SCIENTIFIC_REUSE_ORIGIN_DIFFERS",
        )
        task_root = Path(origin.source_task_root)
        _require(
            Path(origin.source_request.path) == task_root / "request.json"
            and Path(origin.source_outcome.path) == task_root / "outcome.json"
            and Path(origin.source_receipt.path)
            == task_root / "execution-records/identities" / f"{request.execution_identity}.json",
            "SCIENTIFIC_ORIGIN_LAYOUT_DIFFERS",
        )
        if origin.source_native_root is not None:
            native = Path(origin.source_native_root)
            _require(
                native
                == task_root
                / "executions"
                / request.execution_identity
                / "qlib-workflow/native-records"
                / f"sha256-{request.execution_identity}",
                "SCIENTIFIC_NATIVE_LAYOUT_DIFFERS",
            )
            _require(
                {str(Path(item.path).relative_to(native)) for item in origin.native_files}
                == _NATIVE_FILES,
                "SCIENTIFIC_NATIVE_FILE_SET_DIFFERS",
            )
            for reference in origin.native_files:
                _require(
                    sha256_file(
                        confined_regular_file(native, str(Path(reference.path).relative_to(native)))
                    )
                    == reference.sha256,
                    "SCIENTIFIC_NATIVE_HASH_MISMATCH",
                )
        else:
            _require(
                not origin.native_files
                and str(outcome.outcome) == "EXECUTION_FAILED"
                and outcome.research_result_hash is None,
                "SCIENTIFIC_MISSING_NATIVE_ORIGIN_DIFFERS",
            )
        requests.append(request)
    return ScientificVerifiedAdoption(plan.new_subtask_hashes, plan.origins, tuple(requests))
