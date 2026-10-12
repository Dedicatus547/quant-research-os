"""Bind successor prediction comparisons to the complete frozen proposal denominator."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from quantos.application.discovery_execution import DiscoveryExecutionService
from quantos.application.discovery_generation_report import generation_counts_from_verified_batch
from quantos.application.discovery_prediction import compare_prediction_evidence
from quantos.artifacts.store import sha256_file
from quantos.contracts.discovery_prediction import (
    PredictionEvaluationProfile,
    PredictionImportSource,
)


def build_discovery_prediction_comparison(
    service: DiscoveryExecutionService,
    profile: PredictionEvaluationProfile,
    sources: Mapping[str, PredictionImportSource],
    references: Mapping[str, tuple[Path, str]],
) -> dict[str, object]:
    """Verify originals through the prediction interface before assigning method results.

    The existing execution service reconstructs the exact singleton requests from
    generation originals. Its constructor performs no scientific execution. Missing
    native sources stay in both the candidate and opportunity denominators.
    """
    batch = service.batch
    request_by_subtask = {
        task.content_hash: service.task_request(task.content_hash) for task in batch.subtasks
    }
    if profile.execution_request_hashes != tuple(
        sorted(request.content_hash for request in request_by_subtask.values())
    ):
        raise ValueError("PREDICTION_COHORT_DIFFERS_FROM_FROZEN_SINGLETONS")
    bindings = service.evaluation_bindings
    if (
        profile.snapshot_hash != batch.design.snapshot_hash
        or profile.qlib_view_hash != batch.design.qlib_view_hash
        or profile.research_policy_hash != batch.design.research_policy.content_hash
        or profile.code_commit_hash != bindings.code_commit_hash
        or profile.lockfile_hash != bindings.lockfile_hash
        or profile.qlib_version != bindings.qlib_version
    ):
        raise ValueError("PREDICTION_PROFILE_DIFFERS_FROM_ACTUAL_EVALUATION")
    comparison = compare_prediction_evidence(
        profile, sources, references, base_authoring=batch.design.authoring
    )
    candidate_rows = cast(list[dict[str, object]], comparison["rows"])
    evidence_by_request = {cast(str, row["execution_request_hash"]): row for row in candidate_rows}
    method_by_request = {request.content_hash: request.method for request in batch.requests}
    rows: list[dict[str, object]] = []
    for mapping in batch.mappings:
        row: dict[str, object] = {
            "method": method_by_request[mapping.request_hash],
            "generation_request_hash": mapping.request_hash,
            "reservation_hash": mapping.reservation_hash,
            "response_hash": mapping.response_hash,
            "generation_status": mapping.status,
            "generation_reason": mapping.reason,
            "subtask_hash": mapping.subtask_hash,
            "execution_request_hash": None,
            "prediction_status": "NOT_EXECUTABLE",
            "prediction_reason": "NO_STATICALLY_ADMITTED_STRUCTURE",
            "primary_common_rank_ic_mean": None,
            "own_dates_rank_ic_mean_sensitivity": None,
            "original_execution_outcome": None,
            "original_failure_reason": None,
            "original_validation_report_hash": None,
            "p14c": "NOT_EVALUATED_BY_THIS_INTERFACE",
        }
        if mapping.subtask_hash is not None:
            request = request_by_subtask[mapping.subtask_hash]
            evidence_row = evidence_by_request[request.content_hash]
            row.update(evidence_row)
            row["prediction_status"] = evidence_row["status"]
            row["prediction_reason"] = evidence_row.get("reason")
        rows.append(row)

    methods: list[dict[str, object]] = []
    maxima: dict[str, float | None] = {}
    for request in batch.requests:
        method_rows = [row for row in rows if row["method"] == request.method]
        distinct = {
            cast(str, row["subtask_hash"]) for row in method_rows if row["subtask_hash"] is not None
        }
        # Shared structures have one verified execution and may belong to several methods.
        distinct_rows = [
            evidence_by_request[request_by_subtask[subtask_hash].content_hash]
            for subtask_hash in sorted(distinct)
        ]
        values = [
            cast(float, row["primary_common_rank_ic_mean"])
            for row in distinct_rows
            if row["primary_common_rank_ic_mean"] is not None
        ]
        best = max(values) if values else None
        maxima[request.method] = best
        methods.append(
            {
                "method": request.method,
                "granted_opportunities": request.max_attempts,
                "occupied_opportunities": len(method_rows),
                "unoccupied_opportunities": request.max_attempts - len(method_rows),
                "different_structures": len(distinct),
                "comparable_different_predictions": len(values),
                "generation_failures_or_unfinished": sum(
                    row["generation_status"] in ("FAILED", "UNFINISHED", "PARSE_FAILED", "REJECTED")
                    for row in method_rows
                ),
                "duplicates": sum(row["generation_status"] == "DUPLICATE" for row in method_rows),
                "highest_common_rank_ic_mean": best,
            }
        )
    delta = None
    if all(value is not None for value in maxima.values()):
        delta = cast(float, maxima["LLM"]) - max(
            cast(float, maxima["RANDOM"]), cast(float, maxima["TEMPLATE"])
        )
    return {
        "schema_version": "discovery-prediction-batch-comparison/v1",
        "method_comparison_rule": {
            "rule_id": "frozen-opportunities-best-common-rank-ic/v1",
            "implementation_hash": sha256_file(Path(__file__)),
        },
        "batch_hash": batch.content_hash,
        "sequential_batch_hash": None
        if service.sequential_batch is None
        else service.sequential_batch.content_hash,
        "profile_hash": profile.content_hash,
        "interpretation": profile.interpretation,
        "actual_evaluation": service.evaluation_metadata(),
        "primary_metric": "COMMON_DATE_FIXED_MODEL_DAILY_CROSS_SECTIONAL_RANK_IC_MEAN",
        "candidate_comparison": comparison,
        "generation_counts": None
        if service.sequential_batch is None
        else generation_counts_from_verified_batch(service.sequential_batch),
        "rows": rows,
        "methods": methods,
        "opportunity_denominator": sum(request.max_attempts for request in batch.requests),
        "occupied_opportunities": len(batch.mappings),
        "different_structure_denominator": len(batch.subtasks),
        "llm_minus_best_baseline": delta,
        "investment_verdict": "NOT_EVALUATED_REQUIRES_FROZEN_IMPROVEMENT_AND_COST_CRITERIA",
        "original_validation_and_p14c": "UNCHANGED",
        "limitations": [
            "RETROSPECTIVE_EXPLORATORY_ONLY",
            "OWN_DATE_MEANS_ARE_COVERAGE_SENSITIVITY_NOT_RANKING_VALUES",
            "MISSING_SCORES_ARE_NULL_NOT_ZERO",
            "SHARED_CANDIDATES_HAVE_ONE_EXECUTION_AND_MULTIPLE_METHOD_OWNERS",
            "NO_PROFITABILITY_OR_GENERAL_METHOD_SUPERIORITY_CLAIM",
        ],
    }


def render_discovery_prediction_comparison(report: dict[str, object]) -> str:
    """Present verified results without new evaluation or decisions."""
    lines = [
        "# Successor Discovery prediction comparison",
        "",
        f"Batch: `{report['batch_hash']}`; profile: `{report['profile_hash']}`.",
        f"Interpretation: {report['interpretation']}.",
        "",
        f"LLM minus best baseline: {report['llm_minus_best_baseline']}; "
        f"investment verdict: {report['investment_verdict']}.",
        "",
        "| Method | Granted / occupied | Different structures | Comparable | Best common Rank IC |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in cast(list[dict[str, object]], report["methods"]):
        lines.append(
            f"| {method['method']} | {method['granted_opportunities']} / "
            f"{method['occupied_opportunities']} | {method['different_structures']} | "
            f"{method['comparable_different_predictions']} | "
            f"{method['highest_common_rank_ic_mean']} |"
        )
    lines.extend(
        (
            "",
            "| Method | Reservation | Generation | Prediction | Common Rank IC | Outcome |",
            "|---|---|---|---|---:|---|",
        )
    )
    for row in cast(list[dict[str, object]], report["rows"]):
        lines.append(
            f"| {row['method']} | `{row['reservation_hash']}` | {row['generation_status']} | "
            f"{row['prediction_status']} | {row['primary_common_rank_ic_mean']} | "
            f"{row['original_execution_outcome']} |"
        )
    lines.extend(("", "Original Validation and P14c remain unchanged. Null is unavailable."))
    return "\n".join(lines) + "\n"
