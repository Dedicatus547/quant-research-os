#!/usr/bin/env python3
"""Run two independent, native-Qlib synthetic P6 validation pipelines."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantos.application import capture_code_provenance, resolve_experiment
from quantos.backtest import QlibBacktestService
from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import OperatorDelayPolicy
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.data import QlibViewBuilder, SyntheticSnapshotBuilder
from quantos.research.qlib import FactorSignalArtifactBuilder, build_pit_evidence_collection
from quantos.validation import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationRunLocators,
    ValidationService,
    verify_validation_report,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class _Variant:
    resolved: ResolvedExperimentSpec
    signal_path: Path
    signal_hash: str
    backtest_path: Path
    backtest_hash: str


@dataclass(frozen=True)
class _PipelineResult:
    code_commit_hash: str
    lockfile_hash: str
    runtime_fingerprint_hash: str
    snapshot_hash: str
    qlib_view_hash: str
    qlib_version: str
    qlib_source_commit: str
    baseline_signal_hash: str
    baseline_backtest_hash: str
    report_hash: str
    report_path: Path
    robustness_case_count: int


def _variant_authoring(
    baseline: ExperimentAuthoringSpec,
    *,
    window: int | None = None,
    top_k: int | None = None,
    evaluation_start: date | None = None,
    evaluation_end: date | None = None,
) -> ExperimentAuthoringSpec:
    payload = baseline.model_dump(mode="python")
    payload["evaluation_start"] = evaluation_start or baseline.evaluation_start
    payload["evaluation_end"] = evaluation_end or baseline.evaluation_end
    expression = dict(payload["expression"])
    strategy = dict(payload["strategy"])
    expression["window"] = window or baseline.expression.window
    strategy["top_k"] = top_k or baseline.strategy.top_k
    payload["expression"] = expression
    payload["strategy"] = strategy
    return ExperimentAuthoringSpec.model_validate(payload)


def _scaled_cost(baseline: CostPolicy, multiplier: float) -> CostPolicy:
    return CostPolicy.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "policy_id": f"synthetic_validation_cost_{multiplier:.1f}x_v1",
            "open_cost_rate": baseline.open_cost_rate * multiplier,
            "close_cost_rate": baseline.close_cost_rate * multiplier,
            "minimum_cost_cny": baseline.minimum_cost_cny * multiplier,
        }
    )


def _build_variant(
    *,
    authoring: ExperimentAuthoringSpec,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    cost_policy: CostPolicy,
    backtest_policy: BacktestPolicy,
    snapshot_path: Path,
    snapshot_hash: str,
    view_path: Path,
    view_hash: str,
    view_version: str,
    view_spec_hash: str,
    schedules: tuple[DecisionSchedule, ...],
    output_root: Path,
    workspace: Path,
    commit_hash: str,
    lockfile_hash: str,
) -> _Variant:
    provisional = resolve_experiment(
        authoring,
        snapshot_hash=snapshot_hash,
        qlib_view_hash=view_hash,
        qlib_version=view_version,
        qlib_view_spec_hash=view_spec_hash,
        pit_audit_evidence_hash="0" * 64,
        research_policy_hash=research_policy.content_hash,
        validation_policy_hash=validation_policy.content_hash,
        cost_policy_hash=cost_policy.content_hash,
        backtest_policy_hash=backtest_policy.content_hash,
        code_commit_hash=commit_hash,
        lockfile_hash=lockfile_hash,
    )
    evidence = build_pit_evidence_collection(
        snapshot_path,
        view_path,
        expected_snapshot_hash=snapshot_hash,
        expected_view_hash=view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=provisional.expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="synthetic-validation-return-delay-60s/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=schedules,
    )
    resolved = ResolvedExperimentSpec.model_validate(
        provisional.model_copy(
            update={"pit_audit_evidence_hash": evidence.content_hash}
        ).model_dump(mode="python")
    )
    signal = FactorSignalArtifactBuilder().build(
        resolved,
        evidence,
        view_path,
        output_root / "signals",
        workspace=workspace,
    )
    backtest = QlibBacktestService().run(
        resolved,
        signal.path,
        view_path,
        cost_policy,
        backtest_policy,
        output_root / "backtests",
        workspace=workspace,
    )
    return _Variant(
        resolved=resolved,
        signal_path=signal.path,
        signal_hash=signal.manifest.artifact_hash,
        backtest_path=backtest.path,
        backtest_hash=backtest.manifest.result_hash,
    )


def _run_pipeline(
    *,
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
    authoring: ExperimentAuthoringSpec,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    base_cost: CostPolicy,
    backtest_policy: BacktestPolicy,
) -> _PipelineResult:
    provenance = capture_code_provenance(workspace)
    snapshot = SyntheticSnapshotBuilder().build(fixture_root, output_root / "snapshots")
    if snapshot.manifest.source_kind is not SnapshotSourceKind.SYNTHETIC_FIXTURE:
        raise ValueError("P6 feasibility accepts only an explicit synthetic fixture")
    view = QlibViewBuilder().build(snapshot.path, output_root / "qlib-views", qlib_source)
    schedule = DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 16, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 16, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )
    common = {
        "research_policy": research_policy,
        "validation_policy": validation_policy,
        "backtest_policy": backtest_policy,
        "snapshot_path": snapshot.path,
        "snapshot_hash": snapshot.manifest.snapshot_hash,
        "view_path": view.path,
        "view_hash": view.manifest.view_hash,
        "view_version": view.manifest.qlib_version,
        "view_spec_hash": view.manifest.view_spec_hash,
        "schedules": (schedule,),
        "output_root": output_root,
        "workspace": workspace,
        "commit_hash": provenance.commit_hash,
        "lockfile_hash": provenance.lockfile_hash,
    }
    baseline = _build_variant(authoring=authoring, cost_policy=base_cost, **common)

    cost_variants: dict[float, _Variant] = {1.0: baseline}
    for multiplier in validation_policy.cost_stress_multipliers:
        if multiplier != 1.0:
            cost_variants[multiplier] = _build_variant(
                authoring=authoring,
                cost_policy=_scaled_cost(base_cost, multiplier),
                **common,
            )

    parameter_variants: dict[tuple[int, int], _Variant] = {}
    for window in validation_policy.parameter_windows:
        for top_k in validation_policy.parameter_top_k:
            key = (window, top_k)
            if key == (authoring.expression.window, authoring.strategy.top_k):
                parameter_variants[key] = baseline
            else:
                parameter_variants[key] = _build_variant(
                    authoring=_variant_authoring(authoring, window=window, top_k=top_k),
                    cost_policy=base_cost,
                    **common,
                )

    subperiod_variants: dict[str, _Variant] = {}
    for period in validation_policy.subperiods:
        subperiod_variants[period.period_id] = _build_variant(
            authoring=_variant_authoring(
                authoring,
                evaluation_start=period.start,
                evaluation_end=period.end,
            ),
            cost_policy=base_cost,
            **common,
        )

    reproduction = QlibBacktestService().run(
        baseline.resolved,
        baseline.signal_path,
        view.path,
        base_cost,
        backtest_policy,
        output_root / "reproduction-backtests",
        workspace=workspace,
    )
    locators = ValidationRunLocators(
        snapshot_path=snapshot.path,
        qlib_view_path=view.path,
        signal_path=baseline.signal_path,
        baseline_backtest_path=baseline.backtest_path,
        reproduction_backtest_path=reproduction.path,
        cost_stress=tuple(
            CostStressLocator(
                multiplier=multiplier,
                signal_path=cost_variants[multiplier].signal_path,
                backtest_path=cost_variants[multiplier].backtest_path,
            )
            for multiplier in validation_policy.cost_stress_multipliers
        ),
        parameter_stability=tuple(
            ParameterStabilityLocator(
                window=window,
                top_k=top_k,
                signal_path=parameter_variants[(window, top_k)].signal_path,
                backtest_path=parameter_variants[(window, top_k)].backtest_path,
            )
            for window in validation_policy.parameter_windows
            for top_k in validation_policy.parameter_top_k
        ),
        subperiods=tuple(
            SubperiodLocator(
                period_id=period.period_id,
                start=period.start,
                end=period.end,
                signal_path=subperiod_variants[period.period_id].signal_path,
                backtest_path=subperiod_variants[period.period_id].backtest_path,
            )
            for period in validation_policy.subperiods
        ),
    )
    validation = ValidationService().run(
        authoring,
        validation_policy,
        research_policy,
        locators,
        output_root / "validation",
        output_root / "events",
        workspace=workspace,
        canonical=True,
    )
    verified = verify_validation_report(validation.path)
    if (
        verified.run_status is not RunStatus.SUCCEEDED
        or verified.verdict is not ValidationVerdict.PASS
        or not all(gate.verdict is ValidationVerdict.PASS for gate in verified.gates)
        or verified.reproducibility is None
        or not verified.reproducibility.passed
    ):
        raise RuntimeError("native-Qlib P6 validation did not pass every G0-G10 gate")
    return _PipelineResult(
        code_commit_hash=provenance.commit_hash,
        lockfile_hash=provenance.lockfile_hash,
        runtime_fingerprint_hash=verified.runtime_fingerprint_hash,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_source_commit=view.manifest.qlib_source_commit,
        baseline_signal_hash=baseline.signal_hash,
        baseline_backtest_hash=baseline.backtest_hash,
        report_hash=verified.report_hash,
        report_path=validation.path,
        robustness_case_count=len(verified.robustness_cases),
    )


def run(
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
    authoring_path: Path,
    research_policy_path: Path,
    validation_policy_path: Path,
    cost_policy_path: Path,
    backtest_policy_path: Path,
) -> dict[str, object]:
    """Execute two independent full P6 runs and compare their immutable hashes."""

    authoring = load_yaml_contract(authoring_path, ExperimentAuthoringSpec)
    research_policy = load_yaml_contract(research_policy_path, ResearchPolicy)
    validation_policy = load_yaml_contract(validation_policy_path, ValidationPolicy)
    base_cost = load_yaml_contract(cost_policy_path, CostPolicy)
    backtest_policy = load_yaml_contract(backtest_policy_path, BacktestPolicy)
    first = _run_pipeline(
        fixture_root=fixture_root,
        qlib_source=qlib_source,
        output_root=output_root / "run-a",
        workspace=workspace,
        authoring=authoring,
        research_policy=research_policy,
        validation_policy=validation_policy,
        base_cost=base_cost,
        backtest_policy=backtest_policy,
    )
    second = _run_pipeline(
        fixture_root=fixture_root,
        qlib_source=qlib_source,
        output_root=output_root / "run-b",
        workspace=workspace,
        authoring=authoring,
        research_policy=research_policy,
        validation_policy=validation_policy,
        base_cost=base_cost,
        backtest_policy=backtest_policy,
    )
    exact_fields = (
        "code_commit_hash",
        "lockfile_hash",
        "runtime_fingerprint_hash",
        "snapshot_hash",
        "qlib_view_hash",
        "qlib_version",
        "qlib_source_commit",
        "baseline_signal_hash",
        "baseline_backtest_hash",
        "report_hash",
        "robustness_case_count",
    )
    if any(getattr(first, field) != getattr(second, field) for field in exact_fields):
        raise RuntimeError("independent native-Qlib P6 runs did not reproduce exact hashes")
    return {
        "schema_version": "validation-feasibility-report/v1",
        "status": "PASS",
        "source_kind": SnapshotSourceKind.SYNTHETIC_FIXTURE,
        "code_commit_hash": first.code_commit_hash,
        "lockfile_hash": first.lockfile_hash,
        "runtime_fingerprint_hash": first.runtime_fingerprint_hash,
        "snapshot_hash": first.snapshot_hash,
        "qlib_view_hash": first.qlib_view_hash,
        "qlib_version": first.qlib_version,
        "qlib_source_commit": first.qlib_source_commit,
        "authoring_spec_hash": authoring.content_hash,
        "research_policy_hash": research_policy.content_hash,
        "validation_policy_hash": validation_policy.content_hash,
        "cost_policy_hash": base_cost.content_hash,
        "backtest_policy_hash": backtest_policy.content_hash,
        "signal_artifact_hash": first.baseline_signal_hash,
        "backtest_result_hash": first.baseline_backtest_hash,
        "validation_report_hash": first.report_hash,
        "validation_report_paths": [str(first.report_path), str(second.report_path)],
        "robustness_case_count": first.robustness_case_count,
        "gates": [f"G{index}" for index in range(11)],
        "full_pipeline_double_run_hash_equal": True,
        "native_qlib_components": [
            "dump_bin.py",
            "check_data_health.py",
            "Qlib expression provider",
            "WeightStrategyBase",
            "OrderGenWOInteract",
            "Exchange",
            "SimulatorExecutor",
            "Position",
            "risk_analysis",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("tests/fixtures/synthetic_backtest_snapshot"),
    )
    parser.add_argument("--qlib-source", type=Path, default=Path(".tools/qlib-0.9.7"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/feasibility/validation-p6"),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--authoring",
        type=Path,
        default=Path("configs/research/synthetic_validation_experiment_v1.yaml"),
    )
    parser.add_argument(
        "--research-policy",
        type=Path,
        default=Path("configs/research/synthetic_validation_policy_v1.yaml"),
    )
    parser.add_argument(
        "--validation-policy",
        type=Path,
        default=Path("configs/validation/synthetic_engineering_v1.yaml"),
    )
    parser.add_argument(
        "--cost-policy",
        type=Path,
        default=Path("configs/backtest/cost_v1.yaml"),
    )
    parser.add_argument(
        "--backtest-policy",
        type=Path,
        default=Path("configs/backtest/policy_v1.yaml"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.fixture_root,
                args.qlib_source,
                args.output_root,
                args.workspace,
                args.authoring,
                args.research_policy,
                args.validation_policy,
                args.cost_policy,
                args.backtest_policy,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
