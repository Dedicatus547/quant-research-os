"""Complete offline Data-qualified P3-P7 release orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid5

from quantos.application.provenance import capture_code_provenance
from quantos.application.schedules import resolve_weekly_decision_schedules
from quantos.application.specs import resolve_experiment
from quantos.artifacts.store import atomic_write_bytes
from quantos.backtest import QlibBacktestService
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.events import EventType
from quantos.contracts.pit import OperatorDelayPolicy, SafeQlibOperator
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ExpressionAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.research_execution import PITCrossSectionEvidenceCollection
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import RunStatus, StrategyStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.contracts.validation import GateSeverity
from quantos.data import QlibViewBuilder, verify_snapshot
from quantos.registry import RegistryService
from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    build_compact_pit_evidence_collection,
    subset_compact_pit_evidence,
)
from quantos.validation import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationRunLocators,
    ValidationService,
    verify_validation_report,
)

_RELEASE_NAMESPACE = UUID("dc320c33-6358-5cdb-ab91-6b3b33423336")
_LEGACY_OPERATOR_DELAYS = (
    OperatorDelayPolicy(
        policy_id="qlib-return-delay-60s/v1",
        operator=SafeQlibOperator.RETURN,
        delay_seconds=60,
    ),
)


def _operator_delays(authoring: ExperimentAuthoringSpec) -> tuple[OperatorDelayPolicy, ...]:
    if isinstance(authoring.expression, ExpressionAuthoringSpec):
        return _LEGACY_OPERATOR_DELAYS
    operators = sorted(
        {
            node.operator
            for node in authoring.expression.nodes
            if node.operator is not SafeQlibOperator.FIELD
        },
        key=str,
    )
    return tuple(
        OperatorDelayPolicy(
            policy_id=f"qlib-{operator.value}-delay/v1",
            operator=operator,
            delay_seconds=60 if operator is SafeQlibOperator.RETURN else 0,
        )
        for operator in operators
    )


def _parameter_window(authoring: ExperimentAuthoringSpec) -> int:
    if isinstance(authoring.expression, ExpressionAuthoringSpec):
        return authoring.expression.window
    windows = [node.window for node in authoring.expression.nodes if node.window is not None]
    if len(windows) != 1:
        raise ValueError("parameter stability requires exactly one windowed DAG node")
    return windows[0]


@dataclass(frozen=True)
class _Variant:
    resolved: ResolvedExperimentSpec
    evidence: PITCrossSectionEvidenceCollection
    signal_path: Path
    signal_hash: str
    backtest_path: Path
    backtest_hash: str


@dataclass(frozen=True)
class _Pipeline:
    run_root: Path
    code_commit_hash: str
    lockfile_hash: str
    runtime_fingerprint_hash: str
    snapshot_hash: str
    view_path: Path
    view_hash: str
    qlib_version: str
    qlib_source_commit: str
    baseline: _Variant
    validation_path: Path
    validation_hash: str
    validation_verdict: ValidationVerdict
    robustness_case_count: int


@dataclass(frozen=True)
class _RegisteredPipeline:
    pipeline: _Pipeline
    experiment_manifest_hash: str
    registry_index_hash: str
    strategy_status: StrategyStatus


def _schedules_within_subperiod(
    schedules: tuple[DecisionSchedule, ...],
    *,
    start: date,
    end: date,
) -> tuple[DecisionSchedule, ...]:
    """Keep only schedules whose decision and execution both belong to the period."""

    return tuple(
        schedule
        for schedule in schedules
        if start <= schedule.decision_time.date() <= end
        and start <= schedule.execution_time.date() <= end
    )


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
    selected_window = window or _parameter_window(baseline)
    if isinstance(baseline.expression, ExpressionAuthoringSpec):
        expression["window"] = selected_window
    else:
        nodes = list(expression["nodes"])
        windowed = [index for index, node in enumerate(nodes) if node.get("window") is not None]
        if len(windowed) != 1:
            raise ValueError("parameter stability requires exactly one windowed DAG node")
        nodes[windowed[0]] = {**nodes[windowed[0]], "window": selected_window}
        expression["nodes"] = nodes
    strategy["top_k"] = top_k or baseline.strategy.top_k
    payload["expression"] = expression
    payload["strategy"] = strategy
    return ExperimentAuthoringSpec.model_validate(payload)


def _scaled_cost(baseline: CostPolicy, multiplier: float) -> CostPolicy:
    return CostPolicy.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "policy_id": f"{baseline.policy_id}-stress-{multiplier:.1f}x",
            "open_cost_rate": baseline.open_cost_rate * multiplier,
            "close_cost_rate": baseline.close_cost_rate * multiplier,
            "minimum_cost_cny": baseline.minimum_cost_cny * multiplier,
        }
    )


def _schedule_hash(schedules: tuple[DecisionSchedule, ...]) -> str:
    return sha256_bytes(
        canonical_json_bytes([item.model_dump(mode="python") for item in schedules])
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
    evidence_cache: dict[tuple[str, str], PITCrossSectionEvidenceCollection],
    evidence_override: PITCrossSectionEvidenceCollection | None = None,
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
    cache_key = (provisional.expression.content_hash, _schedule_hash(schedules))
    evidence = evidence_override or evidence_cache.get(cache_key)
    if evidence is None:
        evidence = build_compact_pit_evidence_collection(
            snapshot_path,
            view_path,
            expected_snapshot_hash=snapshot_hash,
            expected_view_hash=view_hash,
            universe_index=provisional.strategy.universe_index,
            expression=provisional.expression,
            operator_delays=_operator_delays(authoring),
            schedules=schedules,
        )
    if (
        evidence.expression_spec_hash != provisional.expression.content_hash
        or tuple(bundle.schedule for bundle in evidence.bundles) != schedules
    ):
        raise ValueError("PIT evidence override does not match the variant expression and schedule")
    evidence_cache[cache_key] = evidence
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
        evidence=evidence,
        signal_path=signal.path,
        signal_hash=signal.manifest.artifact_hash,
        backtest_path=backtest.path,
        backtest_hash=backtest.manifest.result_hash,
    )


def _run_pipeline(
    *,
    snapshot_path: Path,
    qlib_source: Path,
    run_root: Path,
    workspace: Path,
    authoring: ExperimentAuthoringSpec,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    base_cost: CostPolicy,
    backtest_policy: BacktestPolicy,
    release_time: datetime,
    validation_event_id: UUID,
) -> _Pipeline:
    provenance = capture_code_provenance(workspace)
    snapshot = verify_snapshot(snapshot_path)
    if snapshot.source_kind is not SnapshotSourceKind.TUSHARE:
        raise ValueError("Data-qualified release requires source_kind=TUSHARE")
    if "SYNTHETIC_DATA_NOT_LIVE_EVIDENCE" in snapshot.limitations:
        raise ValueError("synthetic limitations cannot enter a Data-qualified release")
    view = QlibViewBuilder().build(snapshot_path, run_root / "qlib-views", qlib_source)
    schedules = resolve_weekly_decision_schedules(
        view.path,
        expected_view_hash=view.manifest.view_hash,
        evaluation_start=authoring.evaluation_start,
        evaluation_end=authoring.evaluation_end,
    )
    evidence_cache: dict[tuple[str, str], PITCrossSectionEvidenceCollection] = {}

    def build_variant(
        variant_authoring: ExperimentAuthoringSpec,
        cost_policy: CostPolicy,
        variant_schedules: tuple[DecisionSchedule, ...],
        *,
        evidence_override: PITCrossSectionEvidenceCollection | None = None,
    ) -> _Variant:
        return _build_variant(
            authoring=variant_authoring,
            research_policy=research_policy,
            validation_policy=validation_policy,
            cost_policy=cost_policy,
            backtest_policy=backtest_policy,
            snapshot_path=snapshot_path,
            snapshot_hash=snapshot.snapshot_hash,
            view_path=view.path,
            view_hash=view.manifest.view_hash,
            view_version=view.manifest.qlib_version,
            view_spec_hash=view.manifest.view_spec_hash,
            schedules=variant_schedules,
            output_root=run_root,
            workspace=workspace,
            commit_hash=provenance.commit_hash,
            lockfile_hash=provenance.lockfile_hash,
            evidence_cache=evidence_cache,
            evidence_override=evidence_override,
        )

    baseline = build_variant(authoring, base_cost, schedules)

    cost_variants: dict[float, _Variant] = {1.0: baseline}
    for multiplier in validation_policy.cost_stress_multipliers:
        if multiplier != 1.0:
            cost_variants[multiplier] = build_variant(
                authoring,
                _scaled_cost(base_cost, multiplier),
                schedules,
            )

    parameter_variants: dict[tuple[int, int], _Variant] = {}
    for window in validation_policy.parameter_windows:
        for top_k in validation_policy.parameter_top_k:
            key = (window, top_k)
            if key == (_parameter_window(authoring), authoring.strategy.top_k):
                parameter_variants[key] = baseline
            else:
                parameter_variants[key] = build_variant(
                    _variant_authoring(authoring, window=window, top_k=top_k),
                    base_cost,
                    schedules,
                )

    subperiod_variants: dict[str, _Variant] = {}
    for period in validation_policy.subperiods:
        period_schedules = _schedules_within_subperiod(
            schedules,
            start=period.start,
            end=period.end,
        )
        period_evidence = subset_compact_pit_evidence(baseline.evidence, period_schedules)
        subperiod_variants[period.period_id] = build_variant(
            _variant_authoring(
                authoring,
                evaluation_start=period.start,
                evaluation_end=period.end,
            ),
            base_cost,
            period_schedules,
            evidence_override=period_evidence,
        )

    reproduction = QlibBacktestService().run(
        baseline.resolved,
        baseline.signal_path,
        view.path,
        base_cost,
        backtest_policy,
        run_root / "reproduction-backtests",
        workspace=workspace,
    )
    locators = ValidationRunLocators(
        snapshot_path=snapshot_path,
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
        run_root / "validation",
        run_root / "events",
        workspace=workspace,
        canonical=True,
        now=release_time,
        event_id=validation_event_id,
    )
    report = verify_validation_report(validation.path)
    hard_gates_passed = all(
        gate.verdict is ValidationVerdict.PASS
        for gate in report.gates
        if gate.severity is GateSeverity.HARD
    )
    if (
        report.run_status is not RunStatus.SUCCEEDED
        or report.verdict not in {ValidationVerdict.PASS, ValidationVerdict.REJECT}
        or not hard_gates_passed
        or report.reproducibility is None
        or not report.reproducibility.passed
    ):
        raise RuntimeError("Data-qualified validation failed an engineering acceptance gate")
    return _Pipeline(
        run_root=run_root,
        code_commit_hash=provenance.commit_hash,
        lockfile_hash=provenance.lockfile_hash,
        runtime_fingerprint_hash=report.runtime_fingerprint_hash,
        snapshot_hash=snapshot.snapshot_hash,
        view_path=view.path,
        view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_source_commit=view.manifest.qlib_source_commit,
        baseline=baseline,
        validation_path=validation.path,
        validation_hash=report.report_hash,
        validation_verdict=report.verdict,
        robustness_case_count=len(report.robustness_cases),
    )


def _register_pipeline(
    pipeline: _Pipeline,
    *,
    snapshot_path: Path,
    authoring: ExperimentAuthoringSpec,
    strategy_id: str,
    release_time: datetime,
) -> _RegisteredPipeline:
    registry = RegistryService(pipeline.run_root / "registry")
    registration = registry.register_experiment(
        pipeline.validation_path,
        event_root=pipeline.run_root / "events",
        snapshot_path=snapshot_path,
        qlib_view_path=pipeline.view_path,
        signal_path=pipeline.baseline.signal_path,
        registered_at=release_time,
    )
    version = registry.register_strategy(
        strategy_id,
        authoring.strategy.content_hash,
        version=1,
        occurred_at=release_time,
    )
    version = registry.append_strategy_event(
        strategy_id,
        1,
        EventType.VALIDATION_STARTED,
        authoring.experiment_id,
        occurred_at=release_time,
    )
    if pipeline.validation_verdict is ValidationVerdict.PASS:
        version = registry.append_strategy_event(
            strategy_id,
            1,
            EventType.VALIDATION_PASSED,
            authoring.experiment_id,
            occurred_at=release_time,
        )
        version = registry.append_strategy_event(
            strategy_id,
            1,
            EventType.STRATEGY_VERSION_VALIDATED,
            authoring.experiment_id,
            occurred_at=release_time,
        )
    else:
        version = registry.append_strategy_event(
            strategy_id,
            1,
            EventType.VALIDATION_REJECTED,
            authoring.experiment_id,
            occurred_at=release_time,
        )
    index = registry.verify()
    expected_status = (
        StrategyStatus.VALIDATED
        if pipeline.validation_verdict is ValidationVerdict.PASS
        else StrategyStatus.REJECTED
    )
    if (
        registration.manifest.snapshot_source_kind is not SnapshotSourceKind.TUSHARE
        or version.status is not expected_status
        or len(index.experiments) != 1
        or len(index.strategies) != 1
    ):
        raise RuntimeError("Data-qualified registry projection is inconsistent")
    return _RegisteredPipeline(
        pipeline=pipeline,
        experiment_manifest_hash=registration.manifest.manifest_hash,
        registry_index_hash=index.index_hash,
        strategy_status=version.status,
    )


def run_data_qualified_release(
    *,
    snapshot_path: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
    authoring: ExperimentAuthoringSpec,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    base_cost: CostPolicy,
    backtest_policy: BacktestPolicy,
    strategy_id: str = "hs300-momentum",
    release_time: datetime | None = None,
) -> dict[str, object]:
    """Run two independent real-data pipelines and retain PASS or REJECT evidence."""

    timestamp = (release_time or datetime.now(UTC)).astimezone(UTC)
    event_id = uuid5(
        _RELEASE_NAMESPACE,
        f"{verify_snapshot(snapshot_path).snapshot_hash}:{authoring.content_hash}:{timestamp.isoformat()}",
    )
    registered: list[_RegisteredPipeline] = []
    for name in ("run-a", "run-b"):
        pipeline = _run_pipeline(
            snapshot_path=snapshot_path,
            qlib_source=qlib_source,
            run_root=output_root / name,
            workspace=workspace,
            authoring=authoring,
            research_policy=research_policy,
            validation_policy=validation_policy,
            base_cost=base_cost,
            backtest_policy=backtest_policy,
            release_time=timestamp,
            validation_event_id=event_id,
        )
        registered.append(
            _register_pipeline(
                pipeline,
                snapshot_path=snapshot_path,
                authoring=authoring,
                strategy_id=strategy_id,
                release_time=timestamp,
            )
        )
    first, second = registered
    exact_pipeline_fields = (
        "code_commit_hash",
        "lockfile_hash",
        "runtime_fingerprint_hash",
        "snapshot_hash",
        "view_hash",
        "qlib_version",
        "qlib_source_commit",
        "validation_hash",
        "validation_verdict",
        "robustness_case_count",
    )
    if (
        any(
            getattr(first.pipeline, field) != getattr(second.pipeline, field)
            for field in exact_pipeline_fields
        )
        or first.pipeline.baseline.signal_hash != second.pipeline.baseline.signal_hash
        or first.pipeline.baseline.backtest_hash != second.pipeline.baseline.backtest_hash
        or first.experiment_manifest_hash != second.experiment_manifest_hash
        or first.registry_index_hash != second.registry_index_hash
        or first.strategy_status is not second.strategy_status
    ):
        raise RuntimeError("independent Data-qualified release pipelines did not reproduce")
    report: dict[str, object] = {
        "schema_version": "data-qualified-release-report/v1",
        "status": "PASS",
        "release_track": "DATA_QUALIFIED",
        "source_kind": SnapshotSourceKind.TUSHARE,
        "data_qualified": True,
        "code_commit_hash": first.pipeline.code_commit_hash,
        "lockfile_hash": first.pipeline.lockfile_hash,
        "runtime_fingerprint_hash": first.pipeline.runtime_fingerprint_hash,
        "snapshot_hash": first.pipeline.snapshot_hash,
        "qlib_view_hash": first.pipeline.view_hash,
        "qlib_version": first.pipeline.qlib_version,
        "qlib_source_commit": first.pipeline.qlib_source_commit,
        "signal_artifact_hash": first.pipeline.baseline.signal_hash,
        "backtest_result_hash": first.pipeline.baseline.backtest_hash,
        "validation_report_hash": first.pipeline.validation_hash,
        "validation_verdict": first.pipeline.validation_verdict,
        "experiment_manifest_hash": first.experiment_manifest_hash,
        "registry_index_hash": first.registry_index_hash,
        "strategy_status": first.strategy_status,
        "robustness_case_count": first.pipeline.robustness_case_count,
        "independent_release_pipelines": 2,
        "principal_hashes_byte_exact": True,
        "limitations": ["SINGLE_SOURCE_NON_VINTAGE"],
    }
    atomic_write_bytes(output_root / "report.json", canonical_json_bytes(report))
    return report
