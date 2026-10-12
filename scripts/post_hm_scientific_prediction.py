#!/usr/bin/env python3
"""Guarded cross-origin prediction preparation, adoption and independent comparison."""

from __future__ import annotations

import argparse
import json
import re
import resource
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter, process_time
from typing import TypeVar, cast

from quantos.application.autonomous_execution import (
    require_durable_execution_root,
)
from quantos.application.discovery_execution import DiscoveryExecutionService
from quantos.application.discovery_prediction import (
    publish_prediction_evidence,
    validate_prediction_output_root,
)
from quantos.application.discovery_prediction_cohort import (
    bounded_prediction_rejection,
    compare_scientific_prediction_cohort,
    policy_from_design,
    prepare_scientific_prediction_cohort_repair,
    verify_scientific_prediction_cohort,
    verify_scientific_prediction_cohort_repair,
)
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, sha256_file
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import SequentialDiscoveryBatch
from quantos.contracts.discovery_evaluation import ScientificEvaluationDeclaration
from quantos.contracts.discovery_prediction import PredictionFileSource, PredictionImportSource
from quantos.contracts.discovery_prediction_cohort import (
    ScientificPredictionCohort,
    ScientificPredictionCohortRepair,
)
from quantos.infrastructure.hosted_storage import configured_guard

_C = TypeVar("_C", bound=CanonicalContract)


def _ref(path: Path) -> PredictionFileSource:
    path = confined_regular_file(path.absolute().parent, path.name)
    return PredictionFileSource(path=str(path), sha256=sha256_file(path))


def _bytes(path: Path, expected_hash: str) -> bytes:
    path = confined_regular_file(path.absolute().parent, path.name)
    if path.stat().st_size > 16 << 20:
        raise ValueError("INPUT_BYTE_LIMIT")
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_hash:
        raise ValueError("INPUT_HASH_MISMATCH")
    return raw


def _contract(path: Path, expected_hash: str, model: type[_C]) -> _C:
    raw = _bytes(path, expected_hash)
    value = model.model_validate_json(raw)
    if value.canonical_bytes() != raw:
        raise ValueError("INPUT_NOT_CANONICAL")
    return value


def _object(path: Path, expected_hash: str) -> dict[str, object]:
    raw = _bytes(path, expected_hash)
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("INPUT_OBJECT_REQUIRED")
    value = cast(dict[str, object], decoded)
    if canonical_json_bytes(value) != raw:
        raise ValueError("INPUT_NOT_CANONICAL")
    return value


def _service(args: argparse.Namespace) -> DiscoveryExecutionService:
    wrapper = _contract(
        args.generation_root / "frozen.json", args.generation_hash, SequentialDiscoveryBatch
    )
    declaration = _contract(
        args.declaration, args.declaration_hash, ScientificEvaluationDeclaration
    )
    return DiscoveryExecutionService(
        batch=wrapper.batch,
        sequential_batch=wrapper,
        generation_root=args.generation_root,
        snapshot_path=args.snapshot,
        qlib_view_path=args.view,
        output_root=args.execution_root,
        workspace=args.workspace,
        evaluation_declaration=declaration,
    )


def _cohort(
    args: argparse.Namespace, service: DiscoveryExecutionService
) -> ScientificPredictionCohort:
    cohort = _contract(args.cohort, args.cohort_hash, ScientificPredictionCohort)
    verify_scientific_prediction_cohort(service, cohort)
    repair = _contract(
        args.cohort_repair, args.cohort_repair_hash, ScientificPredictionCohortRepair
    )
    verify_scientific_prediction_cohort_repair(service, cohort, repair)
    return cohort


def _source_index(
    args: argparse.Namespace, cohort: ScientificPredictionCohort
) -> dict[str, PredictionImportSource]:
    index = _object(args.source_index, args.source_index_hash)
    if index.get("cohort_hash") != cohort.content_hash:
        raise ValueError("SOURCE_INDEX_COHORT_DIFFERS")
    sources: dict[str, PredictionImportSource] = {}
    seen: set[str] = set()
    origins = {item.target_subtask_hash: item for item in cohort.origins}
    for entry in cast(list[dict[str, object]], index["entries"]):
        key = str(entry["target_subtask_hash"])
        if key in seen or key not in origins:
            raise ValueError("SOURCE_INDEX_TARGET_DIFFERS")
        seen.add(key)
        if entry.get("source_path") is not None:
            source = _contract(
                Path(str(entry["source_path"])), str(entry["source_hash"]), PredictionImportSource
            )
            if source.request.sha256 != origins[key].actual_request.content_hash:
                raise ValueError("SOURCE_INDEX_ACTUAL_REQUEST_DIFFERS")
            sources[key] = source
    if seen != set(origins):
        raise ValueError("SOURCE_INDEX_DENOMINATOR_INCOMPLETE")
    return sources


def _assemble(
    args: argparse.Namespace, service: DiscoveryExecutionService, cohort: ScientificPredictionCohort
) -> dict[str, object]:
    adoption = service.scientific_verified_adoption()
    dependency = service.scientific_dependency_adoption
    assert adoption is not None and dependency is not None
    old = {origin.target_subtask_hash: origin for origin in adoption.origins}
    policy_path = args.output_root / "research-policy.json"
    atomic_write_bytes(policy_path, service.batch.design.research_policy.canonical_bytes())
    # This is an explicit successor projection of the frozen wrapper's policy,
    # not a file purported to have existed in the historical failed execution.
    projected_policy = _ref(policy_path)
    entries: list[dict[str, object]] = []
    for origin in cohort.origins:
        key, request = origin.target_subtask_hash, origin.actual_request
        entry: dict[str, object] = {
            "target_subtask_hash": key,
            "source_path": None,
            "source_hash": None,
            "status": "SOURCE_MISSING",
        }
        entries.append(entry)
        if key in old:
            adopted = old[key]
            if adopted.source_native_root is None:
                entry["reason"] = "HISTORICAL_NATIVE_UNAVAILABLE"
                continue
            task, native = Path(adopted.source_task_root), Path(adopted.source_native_root)
            req_ref, outcome_ref, receipt_ref = (
                adopted.source_request,
                adopted.source_outcome,
                adopted.source_receipt,
            )
            capsule, inventory = dependency.original_capsule, dependency.original_inventory
            workspace, policy_ref = dependency.original_workspace, adopted.source_design
            exit_ref = PredictionFileSource(
                path=str(args.historical_management_exit.absolute()),
                sha256=args.historical_management_exit_hash,
            )
        else:
            task = service.output_root / "tasks" / key
            native = (
                task
                / "executions"
                / request.execution_identity
                / "qlib-workflow/native-records"
                / f"sha256-{request.execution_identity}"
            )
            if not native.is_dir() or not (task / "outcome.json").is_file():
                entry["reason"] = "NEW_NATIVE_OR_OUTCOME_UNAVAILABLE"
                continue
            candidates = (
                task / "execution-requests" / f"{request.execution_identity}.json",
                task / "request.json",
            )
            request_path = next(
                (p for p in candidates if p.is_file() and sha256_file(p) == request.content_hash),
                None,
            )
            if request_path is None:
                raise ValueError("NEW_ACTUAL_REQUEST_ORIGINAL_MISSING")
            req_ref, outcome_ref = _ref(request_path), _ref(task / "outcome.json")
            outcome = _contract(
                Path(outcome_ref.path), outcome_ref.sha256, AutonomousExecutionResult
            )
            if outcome.execution_artifact_hash is None:
                raise ValueError("NEW_ACTUAL_RECEIPT_HASH_MISSING")
            receipt_paths = (
                task
                / "execution-record-artifacts"
                / f"sha256-{outcome.execution_artifact_hash}.json",
                task / "execution-records/identities" / f"{request.execution_identity}.json",
            )
            receipt_path = next(
                (
                    p
                    for p in receipt_paths
                    if p.is_file() and sha256_file(p) == outcome.execution_artifact_hash
                ),
                None,
            )
            if receipt_path is None:
                raise ValueError("NEW_ACTUAL_RECEIPT_ORIGINAL_MISSING")
            receipt_ref = _ref(receipt_path)
            capsule, inventory = dependency.evaluation_capsule, dependency.evaluation_inventory
            workspace, policy_ref = dependency.evaluation_workspace, projected_policy
            exit_ref = PredictionFileSource(
                path=str(args.new_management_exit.absolute()), sha256=args.new_management_exit_hash
            )
        split = native / "model-data-splits.json"
        if not split.is_file():
            entry["reason"] = "ACTUAL_MODEL_SPLIT_UNAVAILABLE"
            continue
        audit = _object(split, sha256_file(split))
        reservations = sorted(
            (task / "execution-checkpoints" / request.execution_identity / "workflow").glob(
                "*/attempts/*/reservation.json"
            )
        )
        selected: Path | None = None
        for path in reservations:
            reservation = _object(path, sha256_file(path))
            inputs = cast(dict[str, object], reservation.get("inputs", {}))
            if (
                reservation.get("request_hash") == request.content_hash
                and inputs.get("resolved_hash") == audit.get("resolved_spec_hash")
                and (path.parent / "completion.json").is_file()
            ):
                selected = path
        if selected is None:
            entry["reason"] = "ACTUAL_WORKFLOW_RESERVATION_UNAVAILABLE"
            continue
        reservation = _object(selected, sha256_file(selected))
        inputs = cast(dict[str, object], reservation["inputs"])
        signal_hash = str(inputs["signal_hash"])
        signal = (
            task
            / "executions"
            / request.execution_identity
            / "baseline/signals"
            / f"sha256-{signal_hash}"
        )
        source = PredictionImportSource(
            request=req_ref,
            outcome=outcome_ref,
            receipt=receipt_ref,
            resolved=_ref(signal / "resolved-experiment.json"),
            research_policy=policy_ref,
            workflow_reservation=_ref(selected),
            workflow_completion=_ref(selected.parent / "completion.json"),
            management_exit=exit_ref,
            source_capsule=capsule,
            source_inventory=inventory,
            source_workspace=workspace,
            native_root=str(native),
            model_split_sha256=sha256_file(split),
            snapshot_path=str(args.snapshot.absolute()),
            qlib_view_path=str(args.view.absolute()),
            signal_path=str(signal),
            signal_hash=signal_hash,
        )
        source_path = args.output_root / "sources" / f"{key}.json"
        atomic_write_bytes(source_path, source.canonical_bytes())
        entry.update(
            source_path=str(source_path.absolute()),
            source_hash=source.content_hash,
            status="DESCRIPTOR_ASSEMBLED_NOT_QUALIFICATION",
        )
    result: dict[str, object] = {
        "schema_version": "scientific-prediction-source-index/v1",
        "cohort_hash": cohort.content_hash,
        "projected_policy_origin_wrapper_hash": cohort.sequential_batch_hash,
        "entries": entries,
    }
    atomic_write_bytes(args.output_root / "source-index.json", canonical_json_bytes(result))
    return result


def _run(args: argparse.Namespace, service: DiscoveryExecutionService) -> dict[str, object]:
    if args.command == "prepare":
        policy = policy_from_design(
            PredictionFileSource(path=str(args.policy.absolute()), sha256=args.policy_hash)
        )
        raw = _bytes(args.calendar, args.calendar_hash)
        dates = tuple(date.fromisoformat(line) for line in raw.decode().splitlines() if line)
        dates = tuple(
            day
            for day in dates
            if service.batch.design.research_policy.test.start
            <= day
            <= service.batch.design.research_policy.test.end
        )
        cohort, repair = prepare_scientific_prediction_cohort_repair(
            service,
            PredictionFileSource(
                path=str(args.predecessor_cohort.absolute()), sha256=args.predecessor_cohort_hash
            ),
        )
        if cohort.policy != policy or cohort.expected_dates != dates:
            raise ValueError("COHORT_REPAIR_POLICY_OR_CALENDAR_CHANGED")
        path = args.output_root / "cohort.json"
        atomic_write_bytes(path, cohort.canonical_bytes())
        repair_path = args.output_root / "cohort-repair.json"
        atomic_write_bytes(repair_path, repair.canonical_bytes())
        for profile in cohort.profiles:
            atomic_write_bytes(
                args.output_root / "profiles" / f"sha256-{profile.content_hash}.json",
                profile.canonical_bytes(),
            )
        return {
            "cohort_hash": cohort.content_hash,
            "path": str(path.absolute()),
            "candidate_count": len(cohort.origins),
            "cohort_repair_path": str(repair_path.absolute()),
            "cohort_repair_hash": repair.content_hash,
            "predecessor_cohort_hash": repair.predecessor_cohort.sha256,
        }
    cohort = _cohort(args, service)
    if args.command == "assemble":
        return _assemble(args, service, cohort)
    sources = _source_index(args, cohort)
    validate_prediction_output_root(args.operation_root, tuple(sources.values()))
    validate_prediction_output_root(args.output_root, tuple(sources.values()))
    if args.command == "import":
        profiles = {item.content_hash: item for item in cohort.profiles}
        results: list[dict[str, object]] = []
        for origin in cohort.origins:
            key = origin.target_subtask_hash
            result: dict[str, object] = {
                "target_subtask_hash": key,
                "artifact_path": None,
                "artifact_hash": None,
                "status": "SOURCE_MISSING",
            }
            if key in sources:
                try:
                    path = publish_prediction_evidence(
                        sources[key],
                        profiles[origin.prediction_profile_hash],
                        args.output_root / "evidence",
                        base_authoring=service.batch.design.authoring,
                    )
                    result.update(
                        artifact_path=str(path),
                        artifact_hash=path.name.removeprefix("sha256-"),
                        status="PUBLISHED_SUCCESSOR_EVIDENCE",
                    )
                except (OSError, ValueError, RuntimeError) as error:
                    result.update(
                        status="SOURCE_VERIFICATION_REJECTED",
                        reason=bounded_prediction_rejection(error),
                    )
            atomic_write_bytes(
                args.operation_root / "candidate-results" / f"{key}.json",
                canonical_json_bytes(result),
            )
            results.append(result)
        result = {
            "schema_version": "scientific-prediction-evidence-index/v1",
            "cohort_hash": cohort.content_hash,
            "entries": results,
        }
        atomic_write_bytes(args.output_root / "evidence-index.json", canonical_json_bytes(result))
        return result
    index = _object(args.evidence_index, args.evidence_index_hash)
    if index.get("cohort_hash") != cohort.content_hash:
        raise ValueError("EVIDENCE_INDEX_COHORT_DIFFERS")
    index_entries = cast(list[dict[str, object]], index["entries"])
    keys = [str(item["target_subtask_hash"]) for item in index_entries]
    if len(keys) != len(set(keys)) or set(keys) != {
        item.target_subtask_hash for item in cohort.origins
    }:
        raise ValueError("EVIDENCE_INDEX_DENOMINATOR_INCOMPLETE")
    references = {
        str(item["target_subtask_hash"]): (
            Path(str(item["artifact_path"])),
            str(item["artifact_hash"]),
        )
        for item in index_entries
        if item.get("artifact_path") is not None
    }
    report = compare_scientific_prediction_cohort(service, cohort, sources, references)
    repair = _contract(
        args.cohort_repair, args.cohort_repair_hash, ScientificPredictionCohortRepair
    )
    report["cohort_repair_hash"] = repair.content_hash
    report["predecessor_cohort_hash"] = repair.predecessor_cohort.sha256
    completion = _object(args.new_science_completion, args.new_science_completion_hash)
    prelaunch = _object(args.new_science_prelaunch, args.new_science_prelaunch_hash)
    provenance = cast(dict[str, object], prelaunch.get("science_provenance", {}))
    declaration = service.evaluation_declaration
    assert isinstance(declaration, ScientificEvaluationDeclaration)
    if not (
        completion.get("prelaunch_hash") == args.new_science_prelaunch_hash
        and prelaunch.get("evaluation_declaration_hash") == cohort.scientific_declaration_hash
        and prelaunch.get("batch_hash") == cohort.sequential_batch_hash
        and provenance.get("commit_hash") == declaration.bindings.code_commit_hash
    ):
        raise ValueError("NEW_SCIENCE_COST_ORIGIN_MISMATCH")
    report["new_science_management_observation"] = {
        "source": _ref(args.new_science_completion).model_dump(mode="python"),
        "wall_seconds": completion.get("wall_seconds"),
        "process_exit": completion.get("process_exit"),
        "scope": "NEW_SCIENCE_MANAGER_PARENT_NOT_SUM_OF_STAGE_SECONDS",
    }
    wall = completion.get("wall_seconds")
    report["new_science_wall_cost_status"] = (
        "UNAVAILABLE"
        if not isinstance(wall, int | float)
        else "WITHIN_FROZEN_CAP"
        if wall <= cohort.policy.max_new_science_wall_seconds
        else "EXCEEDS_FROZEN_CAP"
    )
    counts = cast(dict[str, object], report["generation_counts"])
    llm = next(
        item for item in cast(list[dict[str, object]], counts["methods"]) if item["method"] == "LLM"
    )
    entry_times = cast(dict[str, object], llm["management_entry_wall_seconds"])
    entry_wall = entry_times.get("total")
    report["llm_entry_wall_cost_observation"] = {
        "wall_seconds": entry_wall,
        "scope": "SUM_OF_FIVE_CONFIRMED_MODEL_ENTRY_WALL_TIMES",
    }
    report["llm_entry_wall_cost_status"] = (
        "UNAVAILABLE"
        if not isinstance(entry_wall, int | float)
        else "WITHIN_FROZEN_CAP"
        if entry_wall <= cohort.policy.max_llm_entry_wall_seconds
        else "EXCEEDS_FROZEN_CAP"
    )
    quality = report["quality_increment_status"]
    costs_known = (
        report["new_science_wall_cost_status"] != "UNAVAILABLE"
        and report["llm_entry_wall_cost_status"] != "UNAVAILABLE"
    )
    if quality == "UNAVAILABLE" or not costs_known:
        report["investment_verdict"] = "QUALITY_OR_WALL_COST_UNAVAILABLE_NO_EXPANSION_CONCLUSION"
    elif (
        quality == "MEETS_FROZEN_MEANINGFUL_DELTA"
        and report["new_science_wall_cost_status"]
        == report["llm_entry_wall_cost_status"]
        == "WITHIN_FROZEN_CAP"
    ):
        report["investment_verdict"] = (
            "SUPPORTS_NEXT_BOUNDED_VALIDATION_ON_OBSERVED_QUALITY_AND_WALL_COST;MONETARY_COST_UNKNOWN"
        )
    else:
        report["investment_verdict"] = (
            "PAUSE_EXPANDING_LLM_GENERATION_IN_THIS_SPACE;NO_GENERAL_INEFFECTIVENESS_CLAIM"
        )
    encoded = canonical_json_bytes(report)
    path = args.output_root / f"sha256-{sha256_bytes(encoded)}" / "report.json"
    atomic_write_bytes(path, encoded)
    return {"report_hash": sha256_bytes(encoded), "path": str(path.absolute())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "assemble", "import", "compare"))
    for name in (
        "generation-root",
        "execution-root",
        "workspace",
        "snapshot",
        "view",
        "declaration",
        "output-root",
        "operation-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("generation-hash", "declaration-hash"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--expected-new-bytes", type=int, required=True)
    for name in (
        "policy",
        "calendar",
        "cohort",
        "predecessor-cohort",
        "cohort-repair",
        "source-index",
        "evidence-index",
        "historical-management-exit",
        "new-management-exit",
        "new-science-completion",
        "new-science-prelaunch",
    ):
        parser.add_argument(f"--{name}", type=Path)
        parser.add_argument(f"--{name}-hash")
    args = parser.parse_args()
    required = {
        "prepare": ("policy", "calendar", "predecessor_cohort"),
        "assemble": (
            "cohort",
            "cohort_repair",
            "historical_management_exit",
            "new_management_exit",
        ),
        "import": ("cohort", "cohort_repair", "source_index"),
        "compare": (
            "cohort",
            "cohort_repair",
            "source_index",
            "evidence_index",
            "new_science_completion",
            "new_science_prelaunch",
        ),
    }[args.command]
    for name in required:
        if getattr(args, name) is None or getattr(args, name + "_hash") is None:
            parser.error(f"--{name.replace('_', '-')} and hash are required")
    output, operation = args.output_root.absolute(), args.operation_root.absolute()
    require_durable_execution_root(output)
    require_durable_execution_root(operation)
    validate_prediction_output_root(output, ())
    validate_prediction_output_root(operation, ())
    for original in (
        args.generation_root,
        args.execution_root,
        args.workspace,
        args.snapshot,
        args.view,
    ):
        if output.is_relative_to(original.absolute()) or operation.is_relative_to(
            original.absolute()
        ):
            raise ValueError("OUTPUT_OVERLAPS_ORIGINALS")
    if (operation / "prelaunch.json").exists():
        raise ValueError("OPERATION_ALREADY_RESERVED")
    if args.predecessor_cohort is not None and (
        output.is_relative_to(args.predecessor_cohort.absolute().parent)
        or operation.is_relative_to(args.predecessor_cohort.absolute().parent)
    ):
        raise ValueError("OUTPUT_OVERLAPS_PREDECESSOR_COHORT")
    wall, cpu = perf_counter(), process_time()
    atomic_write_bytes(
        operation / "prelaunch.json",
        canonical_json_bytes(
            {
                "schema_version": "scientific-prediction-operation/v1",
                "command": args.command,
                "cohort_hash": args.cohort_hash,
                "predecessor_cohort_hash": args.predecessor_cohort_hash,
                "cohort_repair_hash": args.cohort_repair_hash,
                "declaration_hash": args.declaration_hash,
                "generation_hash": args.generation_hash,
                "entrypoint_hash": sha256_file(Path(__file__)),
                "expected_new_bytes": args.expected_new_bytes,
                "started_at": datetime.now(UTC),
            }
        ),
    )
    returned = False
    code = 1
    try:
        guard = configured_guard()
        guard.require_root(output)
        guard.require_root(operation)
        guard.require_lease()
        atomic_write_bytes(
            operation / "capacity.json", canonical_json_bytes(guard.check(args.expected_new_bytes))
        )
        service = _service(args)
        result = _run(args, service)
        atomic_write_bytes(operation / "result.json", canonical_json_bytes(result))
        code, returned = 0, True
        print(json.dumps(result, default=str))
    except Exception as error:
        reason = str(error)
        safe = reason if re.fullmatch(r"[A-Z_]{1,120}", reason) else type(error).__name__
        atomic_write_bytes(
            operation / "failure.json", canonical_json_bytes({"status": "FAILED", "reason": safe})
        )
        returned = True
        print(json.dumps({"status": "FAILED", "reason": safe}))
    finally:
        atomic_write_bytes(
            operation / "completion.json",
            canonical_json_bytes(
                {
                    "schema_version": "scientific-prediction-operation-completion/v1",
                    "status": ("COMPLETED" if code == 0 else "FAILED")
                    if returned
                    else "INTERRUPTED_OR_UNCAUGHT",
                    "entrypoint_return_code": code if returned else None,
                    "process_exit_observation": "REQUIRES_OUTER_PROCESS_OBSERVER",
                    "wall_seconds": perf_counter() - wall,
                    "cpu_seconds": process_time() - cpu,
                    "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "ended_at": datetime.now(UTC),
                }
            ),
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
