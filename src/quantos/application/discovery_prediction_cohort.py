"""Fixed cross-origin prediction cohort using unchanged single-origin evidence verifiers."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import cast

from quantos.application.discovery_execution import DiscoveryExecutionService
from quantos.application.discovery_generation_report import generation_counts_from_verified_batch
from quantos.application.discovery_prediction import (
    prediction_verifier_identity,
    verify_prediction_evidence,
)
from quantos.artifacts.store import confined_regular_file, sha256_file
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_evaluation import ScientificEvaluationDeclaration
from quantos.contracts.discovery_prediction import (
    PredictionEvaluationProfile,
    PredictionEvidence,
    PredictionFileSource,
    PredictionImportSource,
)
from quantos.contracts.discovery_prediction_cohort import (
    ScientificPredictionCohort,
    ScientificPredictionCohortRepair,
    ScientificPredictionOrigin,
    ScientificPredictionPolicy,
)


def _require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def policy_from_design(reference: PredictionFileSource) -> ScientificPredictionPolicy:
    """Adopt the author's pre-result policy bytes; no thresholds are inferred."""
    path = confined_regular_file(Path(reference.path).absolute().parent, Path(reference.path).name)
    _require(path.stat().st_size <= 65_536, "COMPARISON_DESIGN_LIMIT")
    raw = path.read_bytes()
    _require(sha256_bytes(raw) == reference.sha256, "COMPARISON_DESIGN_HASH_MISMATCH")
    decoded: object = json.loads(raw)
    _require(isinstance(decoded, dict), "COMPARISON_DESIGN_INVALID")
    value = cast(dict[str, object], decoded)
    _require(
        value.get("schema_version") == "post-hm-scientific-comparison-design/v1"
        and value.get("new_llm_calls_authorized") is False
        and value.get("tests_authorized") is False
        and value.get("sealed_confirmation_authorized") is False,
        "COMPARISON_DESIGN_SCOPE_DIFFERS",
    )
    return ScientificPredictionPolicy.model_validate(
        {
            "source_design": reference,
            "original_sequential_batch_hash": value["original_sequential_batch_hash"],
            "min_defined_fraction": value["minimum_defined_fraction"],
            "min_common_days": value["minimum_common_days"],
            "meaningful_llm_increment": value["required_meaningful_llm_increment"],
            "max_llm_entry_wall_seconds": value["acceptable_five_entry_llm_wall_seconds"],
            "max_new_science_wall_seconds": value[
                "acceptable_new_scientific_management_wall_seconds"
            ],
            "adopted_origin_count": value["adopted_historical_origins"],
            "new_execution_count": value["new_candidate_executions"],
            "max_compute_units": value["max_compute_units"],
            "expected_growth_bytes": value["expected_complete_growth_bytes"],
        }
    )


def cohort_verifier_identity() -> dict[str, object]:
    package = Path(__file__).resolve().parents[1]
    workspace = package.parents[1]
    names = (
        Path(__file__).resolve(),
        package / "contracts/discovery_prediction_cohort.py",
        package / "application/discovery_scientific_adoption.py",
        package / "contracts/discovery_scientific_adoption.py",
        package / "application/discovery_generation_report.py",
        workspace / "scripts/post_hm_scientific_prediction.py",
    )
    return {
        "schema_version": "scientific-prediction-cohort-verifier/v1",
        "rule": "ACTUAL_ORIGIN_PROFILES_GLOBAL_COMMON_DATE_RANK_IC/v1",
        "single_origin_verifier": prediction_verifier_identity(),
        "dependencies": [
            {"path": str(path.relative_to(workspace)), "sha256": sha256_file(path)}
            for path in names
        ],
    }


def pure_cohort_prepare(
    service: DiscoveryExecutionService,
    *,
    policy: ScientificPredictionPolicy,
    expected_dates: tuple[date, ...],
) -> ScientificPredictionCohort:
    """Freeze actual origins without parsing native files or executing data/PIT work.

    The caller's service must already have verified generation and its reuse plan.
    Single-code v1 profiles stay separate; no target receipt replaces an old origin.
    """
    declaration = service.evaluation_declaration
    adoption = service.scientific_verified_adoption()
    dependency = service.scientific_dependency_adoption
    wrapper = service.sequential_batch
    _require(
        isinstance(declaration, ScientificEvaluationDeclaration)
        and adoption is not None
        and dependency is not None
        and wrapper is not None,
        "VERIFIED_SCIENTIFIC_ADOPTION_REQUIRED",
    )
    declaration = cast(ScientificEvaluationDeclaration, declaration)
    assert adoption is not None and dependency is not None and wrapper is not None
    _require(policy_from_design(policy.source_design) == policy, "FROZEN_COMPARISON_POLICY_DIFFERS")
    _require(
        sum(request.max_attempts for request in service.batch.requests) == 15,
        "FROZEN_FIFTEEN_OPPORTUNITIES_REQUIRED",
    )
    _require(
        policy.original_sequential_batch_hash == wrapper.content_hash
        and declaration.original_sequential_batch_hash == wrapper.content_hash
        and declaration.scientific_adoption_plan_hash is not None
        and policy.new_execution_count == len(adoption.new_subtask_hashes)
        and policy.adopted_origin_count == len(adoption.origins)
        and policy.max_compute_units == declaration.budget.max_compute_units,
        "FROZEN_SCIENTIFIC_COHORT_COUNTS_OR_AUTHORITY_DIFFERS",
    )
    _require(
        len(adoption.origins) == len(adoption.source_requests), "ADOPTION_REQUEST_PAIRING_INVALID"
    )
    old = {
        origin.target_subtask_hash: (origin, request)
        for origin, request in zip(adoption.origins, adoption.source_requests, strict=True)
    }
    new = set(adoption.new_subtask_hashes)
    tasks = {task.content_hash: task for task in service.batch.subtasks}
    _require(set(old) | new == set(tasks) and not set(old) & new, "COHORT_PARTITION_INCOMPLETE")
    actual = {key: old[key][1] if key in old else service.task_request(key) for key in tasks}
    group_keys: dict[tuple[str, str, str], list[str]] = {}
    design = service.batch.design
    for key, request in actual.items():
        expected_code = (
            dependency.original_source_commit
            if key in old
            else declaration.bindings.code_commit_hash
        )
        _require(
            request.code_commit_hash == expected_code
            and request.snapshot_hash == declaration.snapshot_hash == design.snapshot_hash
            and request.qlib_view_hash == declaration.qlib_view_hash == design.qlib_view_hash
            and request.research_policy_hash == design.research_policy.content_hash
            and request.lockfile_hash == declaration.bindings.lockfile_hash
            and request.qlib_version == declaration.bindings.qlib_version
            and request.segment_start == design.research_policy.test.start
            and request.segment_end == design.research_policy.test.end
            and request.candidate_structural_expression_hash
            == tasks[key].manifest.candidates[0].structural_expression_hash,
            "ACTUAL_ORIGIN_SCIENTIFIC_TUPLE_DIFFERS",
        )
        group_keys.setdefault(
            (request.code_commit_hash, request.lockfile_hash, request.qlib_version), []
        ).append(key)
    verifier_hash = sha256_bytes(canonical_json_bytes(prediction_verifier_identity()))
    profile_by_target: dict[str, PredictionEvaluationProfile] = {}
    for (code, lock, qlib_version), keys in group_keys.items():
        profile = PredictionEvaluationProfile(
            verifier_identity_hash=verifier_hash,
            execution_request_hashes=tuple(sorted(actual[key].content_hash for key in keys)),
            expected_dates=expected_dates,
            snapshot_hash=design.snapshot_hash,
            qlib_view_hash=design.qlib_view_hash,
            research_policy_hash=design.research_policy.content_hash,
            code_commit_hash=code,
            lockfile_hash=lock,
            qlib_version=qlib_version,
            min_defined_fraction=policy.min_defined_fraction,
            min_common_days=policy.min_common_days,
        )
        profile_by_target.update({key: profile for key in keys})
    profiles = {profile.content_hash: profile for profile in profile_by_target.values()}
    return ScientificPredictionCohort(
        sequential_batch_hash=wrapper.content_hash,
        scientific_declaration_hash=declaration.content_hash,
        scientific_adoption_plan_hash=cast(str, declaration.scientific_adoption_plan_hash),
        scientific_dependency_adoption_hash=dependency.content_hash,
        cohort_verifier_identity_hash=sha256_bytes(
            canonical_json_bytes(cohort_verifier_identity())
        ),
        policy=policy,
        expected_dates=expected_dates,
        profiles=tuple(profiles[key] for key in sorted(profiles)),
        origins=tuple(
            ScientificPredictionOrigin(
                target_subtask_hash=key,
                source_subtask_hash=old[key][0].source_subtask_hash if key in old else key,
                mode="REUSED_HISTORICAL_ORIGIN" if key in old else "NEW_SCIENTIFIC_EXECUTION",
                actual_request=actual[key],
                prediction_profile_hash=profile_by_target[key].content_hash,
            )
            for key in sorted(tasks)
        ),
    )


def verify_scientific_prediction_cohort(
    service: DiscoveryExecutionService,
    cohort: ScientificPredictionCohort,
) -> None:
    _require(
        pure_cohort_prepare(service, policy=cohort.policy, expected_dates=cohort.expected_dates)
        == cohort,
        "SCIENTIFIC_PREDICTION_COHORT_NOT_RECONSTRUCTED",
    )


def bounded_prediction_rejection(error: OSError | ValueError | RuntimeError) -> str:
    """Preserve engine error codes without exposing unrestricted exception text."""
    message = str(error)
    return message if re.fullmatch(r"[A-Z][A-Z0-9_]{1,95}", message) else type(error).__name__


def _repair_predecessor(reference: PredictionFileSource) -> ScientificPredictionCohort:
    path = confined_regular_file(Path(reference.path).parent, Path(reference.path).name)
    _require(path.stat().st_size <= 16 << 20, "PREDECESSOR_COHORT_SIZE_LIMIT")
    raw = path.read_bytes()
    _require(sha256_bytes(raw) == reference.sha256, "PREDECESSOR_COHORT_HASH_MISMATCH")
    predecessor = ScientificPredictionCohort.model_validate_json(raw)
    _require(predecessor.canonical_bytes() == raw, "PREDECESSOR_COHORT_NOT_CANONICAL")
    return predecessor


def _repair_scope(cohort: ScientificPredictionCohort) -> bytes:
    """Project only verifier identities and their consequent profile hashes away."""
    payload = cohort.model_dump(
        mode="python", exclude={"cohort_verifier_identity_hash", "profiles", "origins"}
    )
    profiles = {profile.content_hash: profile for profile in cohort.profiles}
    projected = {
        key: value.model_dump(mode="python", exclude={"verifier_identity_hash"})
        for key, value in profiles.items()
    }
    payload["profiles"] = sorted(
        canonical_json_bytes(value).decode() for value in projected.values()
    )
    payload["origins"] = [
        {
            **origin.model_dump(mode="python", exclude={"prediction_profile_hash"}),
            "profile_scientific_bindings": projected[origin.prediction_profile_hash],
        }
        for origin in cohort.origins
    ]
    return canonical_json_bytes(payload)


def prepare_scientific_prediction_cohort_repair(
    service: DiscoveryExecutionService,
    predecessor_reference: PredictionFileSource,
) -> tuple[ScientificPredictionCohort, ScientificPredictionCohortRepair]:
    """Keep the pre-score scientific scope; only the repaired verifier changes."""
    predecessor = _repair_predecessor(predecessor_reference)
    successor = pure_cohort_prepare(
        service, policy=predecessor.policy, expected_dates=predecessor.expected_dates
    )
    _require(_repair_scope(predecessor) == _repair_scope(successor), "COHORT_REPAIR_SCOPE_CHANGED")
    repair = ScientificPredictionCohortRepair(
        predecessor_cohort=predecessor_reference,
        successor_cohort_hash=successor.content_hash,
    )
    return successor, repair


def verify_scientific_prediction_cohort_repair(
    service: DiscoveryExecutionService,
    cohort: ScientificPredictionCohort,
    repair: ScientificPredictionCohortRepair,
) -> None:
    rebuilt, expected_repair = prepare_scientific_prediction_cohort_repair(
        service, repair.predecessor_cohort
    )
    _require(rebuilt == cohort and expected_repair == repair, "COHORT_REPAIR_NOT_RECONSTRUCTED")


def _execution_observations(
    service: DiscoveryExecutionService,
    cohort: ScientificPredictionCohort,
) -> dict[str, tuple[AutonomousExecutionResult | None, PredictionFileSource | None]]:
    adoption = service.scientific_verified_adoption()
    assert adoption is not None
    old = {origin.target_subtask_hash: origin for origin in adoption.origins}
    observations: dict[
        str, tuple[AutonomousExecutionResult | None, PredictionFileSource | None]
    ] = {}
    for origin in cohort.origins:
        key = origin.target_subtask_hash
        reference = old[key].source_outcome if key in old else None
        path = (
            Path(reference.path)
            if reference
            else service.output_root / "tasks" / key / "outcome.json"
        )
        if not path.is_file():
            observations[key] = (None, None)
            continue
        path = confined_regular_file(path.absolute().parent, path.name)
        _require(path.stat().st_size <= 1 << 20, "ACTUAL_OUTCOME_BYTE_LIMIT")
        raw = path.read_bytes()
        outcome = AutonomousExecutionResult.model_validate_json(raw)
        _require(
            outcome.canonical_bytes() == raw
            and outcome.request_hash == origin.actual_request.content_hash
            and (reference is None or reference.sha256 == outcome.content_hash),
            "ACTUAL_OUTCOME_ORIGIN_MISMATCH",
        )
        observations[key] = (
            outcome,
            PredictionFileSource(path=str(path), sha256=outcome.content_hash),
        )
    return observations


def _science_counts(
    cohort: ScientificPredictionCohort,
    observations: dict[str, tuple[AutonomousExecutionResult | None, PredictionFileSource | None]],
) -> dict[str, object]:
    counts: dict[str, object] = {}
    for mode, prefix in (
        ("NEW_SCIENTIFIC_EXECUTION", "new"),
        ("REUSED_HISTORICAL_ORIGIN", "historical"),
    ):
        selected = [
            observations[item.target_subtask_hash][0]
            for item in cohort.origins
            if item.mode == mode
        ]
        known = [item for item in selected if item is not None]
        counts[prefix] = {
            "frozen_candidate_count": len(selected),
            "observed_terminal_outcomes": len(known),
            "unknown_terminal_outcomes": len(selected) - len(known),
            "distinct_execution_requested": sum(item.execution_requested for item in known)
            if len(known) == len(selected)
            else None,
            "observed_execution_requested": sum(item.execution_requested for item in known)
            if known
            else None,
            "outcome_declared_budget_units_sum": sum(item.compute_seconds for item in known)
            if len(known) == len(selected)
            else None,
            "observed_budget_units": sum(item.compute_seconds for item in known) if known else None,
            "attempt_count": None,
            "resume_count": None,
            "attempt_scope": (
                "immutable request-bound outcome observations; "
                "full-run and recovery counts unavailable"
            ),
        }
    counts.update(historical_budget_recharged=False, provider_internal_calls=None)
    return counts


def compare_scientific_prediction_cohort(
    service: DiscoveryExecutionService,
    cohort: ScientificPredictionCohort,
    sources: Mapping[str, PredictionImportSource],
    references: Mapping[str, tuple[Path, str]],
) -> dict[str, object]:
    """Independently revalidate every adopted/native origin before global comparison."""
    verify_scientific_prediction_cohort(service, cohort)
    origins = {item.target_subtask_hash: item for item in cohort.origins}
    _require(
        set(sources) <= set(origins) and set(references) <= set(origins), "UNDECLARED_TARGET_SOURCE"
    )
    profiles = {item.content_hash: item for item in cohort.profiles}
    rows: list[dict[str, object]] = []
    admitted: dict[str, PredictionEvidence] = {}
    execution_observations = _execution_observations(service, cohort)
    for key, origin in origins.items():
        row: dict[str, object] = {
            "target_subtask_hash": key,
            "source_subtask_hash": origin.source_subtask_hash,
            "actual_execution_request_hash": origin.actual_request.content_hash,
            "actual_execution_identity": origin.actual_request.execution_identity,
            "actual_code_commit_hash": origin.actual_request.code_commit_hash,
            "origin_mode": origin.mode,
            "status": "SOURCE_MISSING",
            "reason": "SOURCE_MISSING",
            "primary_common_rank_ic_mean": None,
            "own_dates_rank_ic_mean_sensitivity": None,
            "original_validation_report_hash": None,
        }
        outcome, outcome_ref = execution_observations[key]
        row.update(
            original_execution_outcome=None if outcome is None else str(outcome.outcome),
            original_failure_reason=None
            if outcome is None or outcome.failure_reason_code is None
            else str(outcome.failure_reason_code),
            original_validation_report_hash=None
            if outcome is None
            else outcome.validation_report_hash,
            actual_outcome_source=None
            if outcome_ref is None
            else outcome_ref.model_dump(mode="python"),
        )
        rows.append(row)
        if key not in sources:
            continue
        source = sources[key]
        if source.request.sha256 != origin.actual_request.content_hash:
            row.update(
                status="SOURCE_VERIFICATION_REJECTED", reason="ACTUAL_REQUEST_SOURCE_MISMATCH"
            )
            continue
        if key not in references:
            row.update(status="EVIDENCE_MISSING", reason="EVIDENCE_MISSING")
            continue
        try:
            path, expected_hash = references[key]
            evidence = verify_prediction_evidence(
                path,
                expected_hash=expected_hash,
                source=source,
                profile=profiles[origin.prediction_profile_hash],
                base_authoring=service.batch.design.authoring,
            )
        except (OSError, ValueError, RuntimeError) as error:
            row.update(
                status="SOURCE_VERIFICATION_REJECTED", reason=bounded_prediction_rejection(error)
            )
            continue
        values = [day.rank_ic.value for day in evidence.daily if day.rank_ic.value is not None]
        fraction = len(values) / len(cohort.expected_dates)
        row.update(
            status="COVERAGE_REJECTED",
            reason="DEFINED_FRACTION_BELOW_FROZEN_MINIMUM",
            defined_days=len(values),
            expected_days=len(cohort.expected_dates),
            defined_fraction=fraction,
            own_dates_rank_ic_mean_sensitivity=math.fsum(values) / len(values) if values else None,
            original_execution_outcome=evidence.original_execution_outcome,
            original_failure_reason=evidence.original_failure_reason,
            original_validation_report_hash=evidence.original_validation_report_hash,
            original_receipt_hash=evidence.original_receipt_hash,
        )
        if fraction >= cohort.policy.min_defined_fraction:
            row.update(status="COVERAGE_ADMITTED", reason="VERIFIED_ACTUAL_ORIGIN")
            admitted[key] = evidence
    labels = {
        next(item.sha256 for item in evidence.native_sources if Path(item.path).name == "label.pkl")
        for evidence in admitted.values()
    }
    label_comparable = len(labels) <= 1
    common = set(cohort.expected_dates)
    for evidence in admitted.values():
        common &= {day.trade_date for day in evidence.daily if day.rank_ic.value is not None}
    dates = tuple(sorted(common)) if admitted else ()
    available = bool(admitted) and label_comparable and len(dates) >= cohort.policy.min_common_days
    by_target = {cast(str, row["target_subtask_hash"]): row for row in rows}
    for key, evidence in admitted.items():
        row = by_target[key]
        if available:
            values = [
                cast(float, day.rank_ic.value) for day in evidence.daily if day.trade_date in common
            ]
            row["primary_common_rank_ic_mean"] = math.fsum(values) / len(values)
        else:
            row.update(
                status="COMMON_COMPARISON_UNAVAILABLE",
                reason="LABEL_SOURCE_MISMATCH"
                if not label_comparable
                else "COMMON_DAYS_BELOW_FROZEN_MINIMUM",
            )
    batch = service.batch
    method_by_request = {request.content_hash: request.method for request in batch.requests}
    opportunities: list[dict[str, object]] = []
    for mapping in batch.mappings:
        opportunity: dict[str, object] = {
            "method": method_by_request[mapping.request_hash],
            "generation_request_hash": mapping.request_hash,
            "reservation_hash": mapping.reservation_hash,
            "response_hash": mapping.response_hash,
            "generation_status": mapping.status,
            "generation_reason": mapping.reason,
            "target_subtask_hash": mapping.subtask_hash,
            "prediction_status": "NOT_EXECUTABLE",
            "primary_common_rank_ic_mean": None,
        }
        if mapping.subtask_hash is not None:
            opportunity.update(by_target[mapping.subtask_hash])
            opportunity["prediction_status"] = by_target[mapping.subtask_hash]["status"]
        opportunities.append(opportunity)
    methods: list[dict[str, object]] = []
    maxima: dict[str, float | None] = {}
    for request in batch.requests:
        selected = [item for item in opportunities if item["method"] == request.method]
        targets = {
            cast(str, item["target_subtask_hash"])
            for item in selected
            if item["target_subtask_hash"] is not None
        }
        values = [
            cast(float, by_target[key]["primary_common_rank_ic_mean"])
            for key in targets
            if by_target[key]["primary_common_rank_ic_mean"] is not None
        ]
        best = max(values) if values else None
        maxima[request.method] = best
        methods.append(
            {
                "method": request.method,
                "granted_opportunities": request.max_attempts,
                "occupied_opportunities": len(selected),
                "different_structures": len(targets),
                "comparable_different_predictions": len(values),
                "highest_common_rank_ic_mean": best,
            }
        )
    delta = (
        cast(float, maxima["LLM"])
        - max(cast(float, maxima["RANDOM"]), cast(float, maxima["TEMPLATE"]))
        if all(maxima.get(method) is not None for method in ("LLM", "RANDOM", "TEMPLATE"))
        else None
    )
    wrapper = service.sequential_batch
    assert wrapper is not None
    return {
        "schema_version": "scientific-prediction-cohort-comparison/v1",
        "cohort_hash": cohort.content_hash,
        "policy_hash": cohort.policy.content_hash,
        "interpretation": cohort.policy.interpretation,
        "candidate_rows": rows,
        "opportunity_rows": opportunities,
        "methods": methods,
        "candidate_denominator": len(cohort.origins),
        "opportunity_denominator": sum(request.max_attempts for request in batch.requests),
        "common_dates": [day.isoformat() for day in dates],
        "common_days": len(dates),
        "primary_comparison_status": "AVAILABLE" if available else "UNAVAILABLE",
        "llm_minus_best_baseline": delta,
        "quality_increment_status": "UNAVAILABLE"
        if delta is None
        else "MEETS_FROZEN_MEANINGFUL_DELTA"
        if delta >= cohort.policy.meaningful_llm_increment
        else "BELOW_FROZEN_MEANINGFUL_DELTA",
        "generation_counts": generation_counts_from_verified_batch(wrapper),
        "science_count_scope": _science_counts(cohort, execution_observations),
        "monetary_cost_criterion": cohort.policy.monetary_cost_criterion,
        "investment_verdict": "REQUIRES_BOUND_WALL_COST_OBSERVATIONS; NO_MONETARY_SUPERIORITY",
        "original_validation_and_p14c": "UNCHANGED",
    }
