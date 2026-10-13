"""Read-only admission of fixed-model prediction evidence for discovery batches.

This derived report neither changes strategy verdicts nor invokes P14c selection.
All original proposal attempts remain in its denominator, including duplicates.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from quantos.application.discovery_admission import verify_discovery_batch
from quantos.contracts.autonomous import (
    AutonomousExecutionBindings,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
)
from quantos.contracts.discovery import DiscoveryBatch, DiscoveryCompositionDesign
from quantos.contracts.pit import PITGateId
from quantos.contracts.research import ResearchPolicy, ResolvedExperimentSpec
from quantos.contracts.research_execution import PITCrossSectionEvidenceCollection
from quantos.contracts.research_result import (
    P14dqNativeLabelExportAudit,
    ResearchResultSeriesRow,
    ResearchResultSourceFile,
    ResearchResultValueRow,
)
from quantos.contracts.snapshot import DataQualityReport
from quantos.contracts.status import RunStatus, ValidationVerdict
from quantos.contracts.validation import ValidationGateId
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.research.qlib.model_split import verify_model_data_split
from quantos.research.qlib.pit_evidence import (
    build_pit_evidence_collection,
    load_pit_artifact_evidence,
    verify_compact_pit_evidence,
)
from quantos.research.qlib.result import (
    research_result_verification_scope,
    verify_p14dq_native_label_audit,
    verify_research_result,
)
from quantos.research.qlib.signal import verify_signal_artifact
from quantos.validation import verify_validation_report

if TYPE_CHECKING:
    from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
    from quantos.application.discovery_execution import DiscoveryExecutionService


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


_Row = TypeVar("_Row", ResearchResultValueRow, ResearchResultSeriesRow)
_UNPURGED_DISCOVERY_CODE = "dc8d5b67babf86332fb3802fb4fe783c6aec56a8"


def _load_rows(path: Path, model: type[_Row]) -> tuple[_Row, ...]:
    payload = json.loads(path.read_bytes())
    _require(isinstance(payload, list), "RESULT_ROWS_INVALID")
    return tuple(model.model_validate(item) for item in payload)


def _verified_data_calendar(
    batch: DiscoveryBatch, adapter: QuantosResearchExecutionAdapter
) -> tuple[date, ...]:
    snapshot = verify_snapshot(adapter.snapshot_path)
    view = verify_qlib_view(adapter.qlib_view_path)
    quality = DataQualityReport.model_validate_json(
        (adapter.snapshot_path / "quality-report.json").read_bytes()
    )
    _require(
        snapshot.snapshot_hash == batch.design.snapshot_hash
        and view.view_hash == batch.design.qlib_view_hash
        and view.source_snapshot_hash == snapshot.snapshot_hash
        and quality.content_hash == snapshot.quality_report_hash
        and quality.passed,
        "DATA_IDENTITY_OR_QUALITY_REJECTED",
    )
    calendar = tuple(
        date.fromisoformat(line)
        for line in (adapter.qlib_view_path / "calendars" / "day.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    )
    _require(bool(calendar) and calendar == tuple(sorted(set(calendar))), "CALENDAR_INVALID")
    test = batch.design.research_policy.test
    evaluation_calendar = tuple(day for day in calendar if test.start <= day <= test.end)
    _require(bool(evaluation_calendar), "TEST_CALENDAR_EMPTY")
    return calendar


def _verified_model_splits(
    native_root: Path,
    resolved: ResolvedExperimentSpec,
    policy: ResearchPolicy,
    calendar: tuple[date, ...],
    source_files: tuple[ResearchResultSourceFile, ...],
) -> dict[str, object]:
    """Reuse the actual model-input audit, including calendar cutoffs and source origins."""
    splits = verify_model_data_split(
        native_root / "model-data-splits.json",
        resolved=resolved,
        research_policy=policy,
        calendar=calendar,
        source_files=source_files,
    )
    return {
        "purge_evidence_status": "VERIFIED_CALENDAR_SESSION_PURGE",
        "model_data_splits_hash": splits.content_hash,
        "model_data_splits_calendar_hash": splits.calendar_hash,
        "effective_train_end": splits.train.effective.end.isoformat(),
        "effective_validation_end": splits.valid.effective.end.isoformat(),
        "effective_model_data_splits": splits.model_dump(mode="json"),
        "purge_limitations": [],
    }


def _prediction_evidence(
    batch: DiscoveryBatch,
    request: AutonomousExecutionRequest,
    outcome: AutonomousExecutionResult,
    adapter: QuantosResearchExecutionAdapter,
    view_calendar: tuple[date, ...],
    evaluation_bindings: AutonomousExecutionBindings,
    require_split_evidence: bool,
) -> dict[str, object]:
    """Reuse artifact verifiers, then check the comparison-specific prerequisites."""
    _require(outcome.research_result_hash is not None, "NO_RESEARCH_RESULT")
    result_path = adapter.research_results_root / f"sha256-{outcome.research_result_hash}"
    result = verify_research_result(result_path)
    resolved = ResolvedExperimentSpec.model_validate_json(
        (result_path / "resolved-experiment.json").read_bytes()
    )
    policy = ResearchPolicy.model_validate_json((result_path / "research-policy.json").read_bytes())
    design = batch.design
    calendar = tuple(day for day in view_calendar if policy.test.start <= day <= policy.test.end)
    _require(
        result.artifact_hash == outcome.research_result_hash
        and result.snapshot_hash == design.snapshot_hash == request.snapshot_hash
        and result.qlib_view_hash == design.qlib_view_hash == request.qlib_view_hash
        and result.expression_spec_hash == request.candidate.expression.content_hash
        and policy == design.research_policy
        and resolved.research_policy_hash == policy.content_hash
        and resolved.validation_policy_hash == design.validation_policy.content_hash
        and resolved.cost_policy_hash == design.cost_policy.content_hash
        and resolved.backtest_policy_hash == design.backtest_policy.content_hash
        and resolved.code_commit_hash == evaluation_bindings.code_commit_hash
        and resolved.lockfile_hash == evaluation_bindings.lockfile_hash
        and request.code_commit_hash == evaluation_bindings.code_commit_hash
        and request.execution_policy_hash == evaluation_bindings.execution_policy_hash
        and resolved.evaluation_start == policy.test.start == request.segment_start
        and resolved.evaluation_end == policy.test.end == request.segment_end
        and result.label_expression
        == f"Ref($close,-{policy.label_horizon_trading_sessions})/$close-1"
        and result.label_horizon_trading_sessions == policy.label_horizon_trading_sessions,
        "PREDICTION_DESIGN_BINDING_MISMATCH",
    )
    native_root = (
        adapter.output_root
        / "executions"
        / request.execution_identity
        / "qlib-workflow"
        / "native-records"
        / f"sha256-{request.execution_identity}"
    )
    split_facts: dict[str, object] = {
        "purge_evidence_status": "NOT_VERIFIED_NO_EFFECTIVE_SPLIT_ORIGINAL",
    }
    if evaluation_bindings.code_commit_hash == _UNPURGED_DISCOVERY_CODE:
        split_facts.update(
            {
                "purge_evidence_status": "DECLARED_PURGE_NOT_APPLIED_IN_ORIGINAL_03",
                "purge_limitations": [
                    "Original source03 declared five-session purge but used untrimmed train/valid "
                    "segments; cross-boundary forward labels can influence fitting/early stopping. "
                    "Frozen prediction and validation flags retain their original predicate scope."
                ],
            }
        )
    if require_split_evidence:
        split_facts.update(
            _verified_model_splits(
                native_root, resolved, policy, view_calendar, result.source_files
            )
        )

    # The model prediction and expression-driven portfolio are different objects.
    # The signal is used here only to verify the executed feature's PIT lineage.
    signal_path = (
        adapter.output_root
        / "executions"
        / request.execution_identity
        / "baseline"
        / "signals"
        / f"sha256-{result.signal_artifact_hash}"
    )
    signal = verify_signal_artifact(signal_path)
    evidence = load_pit_artifact_evidence(signal_path / "pit-evidence.json")
    _require(
        signal.artifact_hash == result.signal_artifact_hash
        and signal.resolved_experiment_hash == resolved.content_hash
        and evidence.content_hash == resolved.pit_audit_evidence_hash
        and evidence.snapshot_hash == design.snapshot_hash
        and evidence.expression_spec_hash == request.candidate.expression.content_hash
        and evidence.universe_index == design.authoring.strategy.universe_index,
        "PIT_BINDING_MISMATCH",
    )
    if isinstance(evidence, PITCrossSectionEvidenceCollection):
        verify_compact_pit_evidence(evidence, adapter.snapshot_path, adapter.qlib_view_path)
    else:
        # Reuse the canonical snapshot audit; a serialized PASS alone is insufficient.
        first = evidence.bundles[0].items[0].request
        rebuilt = build_pit_evidence_collection(
            adapter.snapshot_path,
            adapter.qlib_view_path,
            expected_snapshot_hash=design.snapshot_hash,
            expected_view_hash=design.qlib_view_hash,
            universe_index=evidence.universe_index,
            expression=request.candidate.expression,
            operator_delays=first.operator_delays,
            schedules=tuple(bundle.schedule for bundle in evidence.bundles),
        )
        _require(rebuilt == evidence, "PIT_SOURCE_REPRODUCTION_MISMATCH")
    if isinstance(evidence, PITCrossSectionEvidenceCollection):
        gate_sets = [bundle.gates for bundle in evidence.bundles]
    else:
        gate_sets = [item.report.gates for bundle in evidence.bundles for item in bundle.items]
    _require(
        all(
            tuple(gate.gate_id for gate in gates) == tuple(PITGateId)
            and all(gate.verdict is ValidationVerdict.PASS for gate in gates)
            for gates in gate_sets
        ),
        "PIT_HARD_GATE_REJECTED",
    )

    predictions = _load_rows(result_path / "predictions.json", ResearchResultValueRow)
    labels = _load_rows(result_path / "labels.json", ResearchResultValueRow)
    keys = [(item.trade_date, item.qlib_instrument_id) for item in predictions]
    label_keys = [(item.trade_date, item.qlib_instrument_id) for item in labels]
    _require(
        bool(keys)
        and keys == sorted(set(keys))
        and keys == label_keys
        and tuple(sorted({item.trade_date for item in predictions})) == calendar
        and all(math.isfinite(item.value) for item in (*predictions, *labels)),
        "PREDICTION_LABEL_KEYS_OR_TEST_COVERAGE_MISMATCH",
    )
    ic = _load_rows(result_path / "ic-series.json", ResearchResultSeriesRow)
    rank_ic = _load_rows(result_path / "rank-ic-series.json", ResearchResultSeriesRow)
    _require(
        tuple(item.trade_date for item in ic) == calendar
        and tuple(item.trade_date for item in rank_ic) == calendar
        and all(math.isfinite(item.value) for item in (*ic, *rank_ic)),
        "IC_SERIES_TEST_COVERAGE_MISMATCH",
    )

    # Reuse the established finite-pair export audit, including explicit native
    # NaN-label omissions. No new projection or imputation rule is introduced.
    audit_matches: list[Path] = []
    for audit_path in sorted(
        (adapter.output_root / "research-result-audits").glob("sha256-*.json")
    ):
        saved_audit = P14dqNativeLabelExportAudit.model_validate_json(audit_path.read_bytes())
        if saved_audit.research_result_hash == result.artifact_hash:
            audit_matches.append(audit_path)
    _require(len(audit_matches) == 1, "REQUIRED_NATIVE_LABEL_AUDIT_UNAVAILABLE")
    audit = verify_p14dq_native_label_audit(result_path, native_root, audit_matches[0], calendar)
    _require(audit.audit_hash in outcome.evidence_hashes, "NATIVE_LABEL_AUDIT_RECEIPT_MISMATCH")
    metrics = {metric.name: metric.value for metric in result.metrics}
    for name, series in (("IC", ic), ("Rank IC", rank_ic)):
        mean = math.fsum(item.value for item in series) / len(series)
        _require(
            math.isclose(
                metrics[name],
                mean,
                abs_tol=design.validation_policy.reproducibility_absolute_tolerance,
                rel_tol=design.validation_policy.reproducibility_relative_tolerance,
            ),
            "IC_SUMMARY_SERIES_MISMATCH",
        )
    return {
        **split_facts,
        "prediction_analyzable": True,
        "prediction_reason": "VERIFIED_FIXED_MODEL_TEST_PREDICTIONS",
        "primary_value": metrics[design.primary_metric],
        "research_result_hash": result.artifact_hash,
        "prediction_content_hash": result.prediction_content_hash,
        "label_content_hash": result.label_content_hash,
        "rank_ic_content_hash": result.rank_ic_content_hash,
        "pit_evidence_hash": evidence.content_hash,
        "evaluated_object": "LGBModel test prediction/label",
        "test_session_count": len(calendar),
        "prediction_pair_count": len(keys),
        "native_label_export_audit_hash": audit.audit_hash,
        "native_pair_count": audit.raw_pair_count,
        "omitted_nan_label_count": audit.omitted_nan_label_count,
    }


def _known_total(values: list[object]) -> int | float | None:
    """Missing measurements remain unknown rather than silently becoming zero."""
    return (
        None
        if not values or any(value is None for value in values)
        else sum(cast(int | float, value) for value in values)
    )


def build_discovery_comparison(
    batch: DiscoveryBatch, execution_service: DiscoveryExecutionService
) -> dict[str, object]:
    """Inspect retained executions; perform no generation, repair, or scientific run."""
    with research_result_verification_scope():
        return _build_discovery_comparison(batch, execution_service)


def _build_discovery_comparison(
    batch: DiscoveryBatch, execution_service: DiscoveryExecutionService
) -> dict[str, object]:
    verify_discovery_batch(batch)
    _require(execution_service.batch == batch, "EXECUTION_SERVICE_BATCH_MISMATCH")
    evaluation_bindings = execution_service.evaluation_bindings
    evaluation_metadata = execution_service.evaluation_metadata()
    require_split_evidence = execution_service.evaluation_declaration is not None
    exposure_append = (
        []
        if execution_service.evaluation_declaration is None
        else list(execution_service.evaluation_declaration.exposure_history_append)
    )
    requests = {item.content_hash: item for item in batch.requests}
    responses = {item.content_hash: item for item in batch.responses}
    tasks: dict[str, dict[str, object]] = {}
    data_calendars: dict[tuple[Path, Path], tuple[date, ...]] = {}
    for subtask in batch.subtasks:
        facts: dict[str, object] = {
            "subtask_hash": subtask.content_hash,
            "execution_status": "NOT_EXECUTED",
            "execution_reason": "NO_COMPLETED_EXECUTION",
            "execution_outcome": None,
            "original_verdict": None,
            "validation_pass": False,
            "prediction_analyzable": False,
            "prediction_reason": "NO_VERIFIED_PREDICTION_EVIDENCE",
            "primary_value": None,
            "p14c_selectable": False,
            "p14c_reason": "NOT_EVALUATED_NO_P14C_SELECTION_IN_DISCOVERY",
            "deterministic_budget_units": None,
            "wall_seconds": None,
            "cpu_seconds": None,
            "recovery_reserved_compute_units": None,
        }
        inspected = None
        try:
            inspected = execution_service.inspect_completed_execution(subtask.content_hash)
            if inspected is not None:
                request, outcome, adapter = inspected.request, inspected.outcome, inspected.adapter
                _require(
                    request.family_hash == subtask.family.content_hash
                    and request.candidate_manifest_hash == subtask.manifest.content_hash
                    and request.candidate == subtask.manifest.candidates[0]
                    and outcome.request_hash == request.content_hash,
                    "SUBTASK_EXECUTION_BINDING_MISMATCH",
                )
                facts.update(
                    {
                        "execution_status": "COMPLETED",
                        "execution_reason": "VERIFIED_EXECUTION_RECEIPT",
                        "execution_request_hash": request.content_hash,
                        "execution_receipt_hash": outcome.execution_artifact_hash,
                        "execution_outcome": outcome.outcome.value,
                        "deterministic_budget_units": outcome.compute_seconds,
                        "failure_reason_code": None
                        if outcome.failure_reason_code is None
                        else outcome.failure_reason_code.value,
                    }
                )
                if outcome.validation_report_hash is not None:
                    report = verify_validation_report(
                        adapter.output_root
                        / "validation"
                        / f"sha256-{outcome.validation_report_hash}"
                    )
                    facts.update(
                        {
                            "validation_report_hash": report.report_hash,
                            "original_verdict": report.verdict.value,
                            "original_run_status": report.run_status.value,
                            "validation_pass": report.run_status is RunStatus.SUCCEEDED
                            and report.verdict is ValidationVerdict.PASS,
                            "original_gates": [
                                gate.model_dump(mode="json") for gate in report.gates
                            ],
                            "original_limitations": list(report.limitations),
                        }
                    )
                    required = {
                        ValidationGateId.G0_SCHEMA_REFERENCE,
                        ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
                        ValidationGateId.G2_PIT_LINEAGE,
                    }
                    _require(
                        all(
                            gate.verdict is ValidationVerdict.PASS
                            for gate in report.gates
                            if gate.gate_id in required
                        ),
                        "PREDICTION_PREREQUISITE_VALIDATION_GATE_REJECTED",
                    )
                _require(outcome.research_result_hash is not None, "NO_RESEARCH_RESULT")
                key = (adapter.snapshot_path, adapter.qlib_view_path)
                if key not in data_calendars:
                    data_calendars[key] = _verified_data_calendar(batch, adapter)
                facts.update(
                    _prediction_evidence(
                        batch,
                        request,
                        outcome,
                        adapter,
                        data_calendars[key],
                        evaluation_bindings,
                        require_split_evidence,
                    )
                )
        except Exception as error:
            # A corrupted/missing original cannot remove an attempt from the report.
            # Exception messages can contain paths/runtime details; retain only type
            # and project-owned comparison reason codes, never raw log text.
            facts["prediction_reason"] = (
                str(error)
                if type(error) is ValueError and str(error).isidentifier() and str(error).isupper()
                else "EVIDENCE_VERIFICATION_FAILED"
            )
            facts["verification_error_type"] = type(error).__name__
            if facts["execution_status"] == "NOT_EXECUTED":
                facts["execution_status"] = "UNVERIFIED"
                facts["execution_reason"] = "EXECUTION_RECEIPT_VERIFICATION_FAILED"
        try:
            state = execution_service.task_state(subtask.content_hash, inspection=inspected)
            if facts["execution_status"] != "UNVERIFIED":
                facts["execution_status"] = state["status"]
                if state["reason"] is not None:
                    facts["execution_reason"] = state["reason"]
            facts.update(
                {
                    "execution_attempt_count": state["attempt_count"],
                    "wall_seconds": state["wall_seconds"],
                    "cpu_seconds": state["cpu_seconds"],
                    "observed_wall_seconds": state["observed_wall_seconds"],
                    "observed_cpu_seconds": state["observed_cpu_seconds"],
                    "measurements_complete": state["measurements_complete"],
                    "recovery_reserved_compute_units": state["recovery_reserved_compute_units"],
                    "cpu_measurement_scope": "CALLING_PROCESS",
                    "child_cpu_seconds": None,
                }
            )
        except Exception as error:
            facts["cost_measurement_reason"] = "EXECUTION_COST_RECORD_VERIFICATION_FAILED"
            facts["cost_verification_error_type"] = type(error).__name__
        tasks[subtask.content_hash] = facts

    batch_costs: dict[str, object] = {
        "attempt_count": None,
        "wall_seconds": None,
        "cpu_seconds": None,
        "observed_wall_seconds": None,
        "observed_cpu_seconds": None,
        "measurements_complete": False,
        "cpu_measurement_scope": "CALLING_PROCESS",
        "child_cpu_seconds": None,
        "recovery_reserved_compute_units": None,
        "quoted_full_batch_compute_units": None,
    }
    try:
        batch_costs.update(execution_service.batch_state())
    except Exception as error:
        batch_costs["measurement_reason"] = "BATCH_COST_RECORD_VERIFICATION_FAILED"
        batch_costs["verification_error_type"] = type(error).__name__

    rows: list[dict[str, object]] = []
    for mapping in batch.mappings:
        response = None if mapping.response_hash is None else responses.get(mapping.response_hash)
        row: dict[str, object] = {
            "method": requests[mapping.request_hash].method,
            "request_hash": mapping.request_hash,
            "reservation_hash": mapping.reservation_hash,
            "response_hash": mapping.response_hash,
            "status": mapping.status,
            "reason": mapping.reason,
            "subtask_hash": mapping.subtask_hash,
            "duplicate": mapping.status == "DUPLICATE",
            "producer": None if response is None else response.producer,
            "generation_wall_seconds": None if response is None else response.wall_seconds,
            "generation_usage_input_units": None
            if response is None
            else response.usage_input_units,
            "generation_usage_output_units": None
            if response is None
            else response.usage_output_units,
            "generation_monetary_cost": None if response is None else response.monetary_cost,
            "prediction_analyzable": False,
            "prediction_reason": "NO_ADMITTED_CANDIDATE",
            "primary_value": None,
            "original_verdict": None,
            "validation_pass": False,
            "p14c_selectable": False,
            "p14c_reason": "NOT_EVALUATED_NO_P14C_SELECTION_IN_DISCOVERY",
        }
        if mapping.subtask_hash is not None:
            row.update(tasks[mapping.subtask_hash])
        row["generation_provenance"] = (
            "UNFINISHED"
            if response is None
            else "HOSTED_HANDOFF_BOUND_ORIGINALS"
            if response.producer == "HOSTED_HANDOFF"
            else "SDK_CAPTURE_BOUND_ORIGINALS"
            if response.producer == "SDK_CAPTURE"
            else "OFFLINE_IMPORT_NO_VERIFIED_LLM_CALL"
            if response.producer == "OFFLINE_IMPORT"
            else "CAPTURE_REJECTED_NO_GENERATION_PROVENANCE"
            if response.producer == "CAPTURE_REJECTED"
            else "DETERMINISTIC_BASELINE"
        )
        row["generation_limitations"] = (
            ["ENTRYPOINT_QUALIFICATION_NOT_INFERRED"]
            if response is not None and response.producer in {"SDK_CAPTURE", "HOSTED_HANDOFF"}
            else []
        )
        if isinstance(batch.design, DiscoveryCompositionDesign):
            expression = mapping.expression
            if mapping.subtask_hash is not None:
                expression = next(
                    t.manifest.candidates[0].expression
                    for t in batch.subtasks
                    if t.content_hash == mapping.subtask_hash
                )
            row["composition_role"] = (
                "interaction"
                if expression and expression.nodes[-1].operator.value in ("divide", "multiply")
                else "nested_constituent"
                if expression and len(expression.nodes) > 2
                else "simple_constituent"
                if expression
                else "unparsed"
            )
            row["parameter_stability_node_id"] = (
                next((n.node_id for n in expression.nodes if n.window is not None), None)
                if expression
                else None
            )
        rows.append(row)

    methods: list[dict[str, object]] = []
    for request in batch.requests:
        method_rows = [row for row in rows if row["method"] == request.method]
        analyzed_subtasks = {
            cast(str, row["subtask_hash"]): cast(float, row["primary_value"])
            for row in method_rows
            if row["prediction_analyzable"]
        }
        values = list(analyzed_subtasks.values())
        methods.append(
            {
                "method": request.method,
                "reserved_attempts": len(method_rows),
                "evaluation_opportunities": request.max_attempts,
                "unreserved_opportunities": request.max_attempts - len(method_rows),
                "unique_admitted": sum(row["status"] == "ADMITTED" for row in method_rows),
                "duplicates": sum(bool(row["duplicate"]) for row in method_rows),
                "runtime_handoff_responses": sum(
                    row["producer"] == "HOSTED_HANDOFF" for row in method_rows
                ),
                "sdk_capture_responses": sum(
                    row["producer"] == "SDK_CAPTURE" for row in method_rows
                ),
                "capture_rejected_responses": sum(
                    row["producer"] == "CAPTURE_REJECTED" for row in method_rows
                ),
                "offline_import_responses": sum(
                    row["producer"] == "OFFLINE_IMPORT" for row in method_rows
                ),
                "actual_provider_call_count": None,
                "analyzable_unique": len(values),
                "best_observed_primary_value": max(values) if values else None,
                "generation_wall_seconds": _known_total(
                    [row["generation_wall_seconds"] for row in method_rows]
                ),
                "generation_monetary_cost": _known_total(
                    [row["generation_monetary_cost"] for row in method_rows]
                ),
                "generation_usage_input_units": _known_total(
                    [row["generation_usage_input_units"] for row in method_rows]
                ),
                "generation_usage_output_units": _known_total(
                    [row["generation_usage_output_units"] for row in method_rows]
                ),
            }
        )
    if isinstance(batch.design, DiscoveryCompositionDesign):
        for method in methods:
            method_rows = [r for r in rows if r["method"] == method["method"]]
            values_by_subtask = {
                cast(str, r["subtask_hash"]): cast(float, r["primary_value"])
                for r in method_rows
                if r["prediction_analyzable"]
            }
            method["primary_value_distribution"] = sorted(values_by_subtask.values())
            method["effective_output_rate"] = len(values_by_subtask) / cast(
                int, method["evaluation_opportunities"]
            )
            method["constituent_distributions"] = {
                role: sorted(
                    {
                        cast(str, r["subtask_hash"]): cast(float, r["primary_value"])
                        for r in method_rows
                        if r["prediction_analyzable"] and r.get("composition_role") == role
                    }.values()
                )
                for role in ("interaction", "nested_constituent", "simple_constituent")
            }
    limitations = [
        "RETROSPECTIVE_EXPLORATORY: actual exposure history remains binding; "
        "no independent confirmation.",
        "SINGLE_SOURCE_NON_VINTAGE: no historical vendor-vintage PIT claim.",
        "Fixed LGBModel prediction Rank IC is not expression score IC or portfolio profitability.",
        "P14c selection, sealed confirmation and Registry promotion are not evaluated.",
        "Unknown costs are unavailable, not zero; no unconditional economic superiority claim.",
        "Shared candidate execution costs are counted once per subtask; "
        "duplicate rows reuse evidence and do not add evaluations.",
        "Each method's observed values deduplicate its own subtask identities; "
        "cross-method overlaps share evidence and do not establish statistical superiority.",
        "Batch wall/CPU totals include common execution verification and overlap task/stage "
        "measurements; those totals must not be added together.",
        "CPU measurements cover the calling process; child-process CPU is unavailable.",
        "Recovery compute reservations are separate from immutable receipt compute units "
        "and are not measured elapsed seconds.",
    ]
    if any(row["method"] == "LLM" and row["producer"] == "OFFLINE_IMPORT" for row in rows):
        limitations.append(
            "OFFLINE_IMPORT is captured text, not verified evidence of an actual LLM call."
        )
    if any(row["producer"] == "SDK_CAPTURE" for row in rows):
        limitations.append(
            "ENTRYPOINT_QUALIFICATION_NOT_INFERRED: SDK_CAPTURE binds captured SDK "
            "requests, events and declared Safe DSL output or failure; "
            "it does not grant Hosted or entrypoint qualification."
        )
    if any(row["producer"] == "HOSTED_HANDOFF" for row in rows):
        limitations.append(
            "ENTRYPOINT_QUALIFICATION_NOT_INFERRED: Hosted source receipts bind launcher "
            "originals with qualification NOT_EVALUATED; no legacy global qualification is adopted."
        )
    if evaluation_bindings.code_commit_hash == _UNPURGED_DISCOVERY_CODE:
        limitations.append(
            "DECLARED_PURGE_NOT_APPLIED_IN_ORIGINAL_03: declared five-session purge was not "
            "applied to training/validation. These frozen flags remain their original predicates; "
            "results do not establish purged independent OOS evaluation."
        )
    elif not require_split_evidence:
        limitations.append(
            "EFFECTIVE_MODEL_SPLITS_NOT_VERIFIED: policy hash equality alone does not establish "
            "that the declared purge was applied."
        )
    composition_metadata: dict[str, object] = {}
    if isinstance(batch.design, DiscoveryCompositionDesign):
        composition_metadata = {
            "discovery_profile": batch.design.profile_id,
            "candidate_grammar": batch.design.candidate_grammar,
            "baseline_sampling": batch.design.baseline_sampling,
            "template_order": batch.design.template_order,
            "parameter_stability_rule": batch.design.parameter_stability_rule,
        }
        limitations.append(
            "FIRST_WINDOW_SENSITIVITY_ONLY: other window sensitivities are not tested; "
            "singleton reports do not correct the generated search."
        )
    return {
        **composition_metadata,
        "schema_version": "discovery-comparison/v1",
        "batch_hash": batch.content_hash,
        "design_hash": batch.design.content_hash,
        "original_generation_batch_hash": batch.content_hash,
        "original_generation_design_hash": batch.design.content_hash,
        "original_generation_code_identity": batch.design.bindings.code_commit_hash,
        "actual_evaluation_code_identity": evaluation_bindings.code_commit_hash,
        "actual_evaluation_bindings": evaluation_bindings.model_dump(mode="json"),
        "evaluation_identity": execution_service.evaluation_identity,
        "evaluation_declaration": None
        if execution_service.evaluation_declaration is None
        else execution_service.evaluation_declaration.model_dump(mode="json"),
        "evaluation": evaluation_metadata,
        "primary_metric": batch.design.primary_metric,
        "direction": batch.design.direction,
        "interpretation": batch.design.interpretation,
        "evaluated_object": "fixed LGBModel test prediction/label",
        "original_generation_exposure_history": list(batch.design.exposure_history),
        "evaluation_exposure_history_append": exposure_append,
        "exposure_history": [*batch.design.exposure_history, *exposure_append],
        "research_policy": batch.design.research_policy.model_dump(mode="json"),
        "rows": rows,
        "methods": methods,
        "costs": {
            "deterministic_budget_units": _known_total(
                [task["deterministic_budget_units"] for task in tasks.values()]
            ),
            "deterministic_budget_limit": execution_service.max_compute_units,
            "original_design_compute_budget_limit": batch.design.max_compute_units,
            "evaluation_budget_reduction_from_original_design": (
                batch.design.max_compute_units - execution_service.max_compute_units
            ),
            "budget_unit_semantics": "frozen workload policy units; "
            "compute_seconds is not elapsed seconds. Full-plan quotes and recovery reservations "
            "are commitments, not measured spent work; receipt units and stage observations "
            "retain their own scope. Prior evaluation roots are not added to this evaluation.",
            "recorded_deterministic_budget_units": sum(
                cast(int, task["deterministic_budget_units"])
                for task in tasks.values()
                if task["deterministic_budget_units"] is not None
            ),
            "recovery_reserved_compute_units": batch_costs["recovery_reserved_compute_units"],
            "quoted_full_batch_compute_units": batch_costs["quoted_full_batch_compute_units"],
            "execution_wall_seconds": batch_costs["wall_seconds"],
            "execution_cpu_seconds": batch_costs["cpu_seconds"],
            "recorded_execution_wall_seconds": batch_costs["observed_wall_seconds"],
            "recorded_execution_cpu_seconds": batch_costs["observed_cpu_seconds"],
            "batch_attempt_count": batch_costs["attempt_count"],
            "execution_measurements_complete": batch_costs["measurements_complete"],
            "cpu_measurement_scope": batch_costs["cpu_measurement_scope"],
            "child_cpu_seconds": batch_costs["child_cpu_seconds"],
            "batch_measurement_reason": batch_costs.get("measurement_reason"),
            "batch_measurement_error_type": batch_costs.get("verification_error_type"),
            "measurement_scope": "retained batch attempts including common verification; "
            "task/stage measurements overlap; report reading/verification time unavailable",
            "task_measurements": [
                {
                    field: task.get(field)
                    for field in (
                        "subtask_hash",
                        "execution_attempt_count",
                        "wall_seconds",
                        "cpu_seconds",
                        "observed_wall_seconds",
                        "observed_cpu_seconds",
                        "measurements_complete",
                        "cpu_measurement_scope",
                        "child_cpu_seconds",
                        "recovery_reserved_compute_units",
                        "cost_measurement_reason",
                        "cost_verification_error_type",
                    )
                }
                for task in tasks.values()
            ],
            "storage_bytes": None,
            "human_preparation_seconds": None,
            "human_intervention_seconds": None,
            "one_time_engineering_seconds": None,
            "generation_by_method": methods,
            "unique_execution_subtasks": len(tasks),
            "allocation": "shared candidate execution counted once by subtask; "
            "no invented per-method split",
        },
        "limitations": limitations,
    }
