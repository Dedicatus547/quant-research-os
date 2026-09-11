from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.application import data_qualified_release as release
from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import RunStatus, StrategyStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.contracts.validation import GateSeverity

ROOT = Path(__file__).parents[2]


def _configs() -> tuple[
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
    CostPolicy,
    BacktestPolicy,
]:
    return (
        load_yaml_contract(
            ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
            ExperimentAuthoringSpec,
        ),
        load_yaml_contract(ROOT / "configs" / "research" / "policy_v1.yaml", ResearchPolicy),
        load_yaml_contract(
            ROOT / "configs" / "validation" / "research_candidate_v1.yaml",
            ValidationPolicy,
        ),
        load_yaml_contract(ROOT / "configs" / "backtest" / "cost_v1.yaml", CostPolicy),
        load_yaml_contract(ROOT / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy),
    )


def _schedule(year: int) -> DecisionSchedule:
    signal_date = date(year, 6, 26)
    return DecisionSchedule(
        signal_time=datetime.combine(signal_date, time(16), tzinfo=UTC),
        signal_available_at=datetime.combine(signal_date, time(16, 1), tzinfo=UTC),
        decision_time=datetime.combine(signal_date, time(16, 10), tzinfo=UTC),
        execution_time=datetime.combine(signal_date + timedelta(days=1), time(9, 30), tzinfo=UTC),
    )


def test_subperiod_schedule_projection_excludes_cross_boundary_execution() -> None:
    inside = _schedule(2017)
    boundary_signal = date(2017, 12, 29)
    crosses_end = DecisionSchedule(
        signal_time=datetime.combine(boundary_signal, time(16), tzinfo=UTC),
        signal_available_at=datetime.combine(boundary_signal, time(16, 1), tzinfo=UTC),
        decision_time=datetime.combine(boundary_signal, time(16, 10), tzinfo=UTC),
        execution_time=datetime.combine(date(2018, 1, 2), time(9, 30), tzinfo=UTC),
    )

    selected = release._schedules_within_subperiod(
        (inside, crosses_end),
        start=date(2015, 1, 1),
        end=date(2017, 12, 31),
    )

    assert selected == (inside,)


def _variant(tmp_path: Path, value: int = 1) -> release._Variant:
    digest = f"{value:064x}"
    return release._Variant(
        resolved=SimpleNamespace(),  # type: ignore[arg-type]
        evidence=SimpleNamespace(),  # type: ignore[arg-type]
        signal_path=tmp_path / "signals" / f"sha256-{digest}",
        signal_hash=digest,
        backtest_path=tmp_path / "backtests" / f"sha256-{digest}",
        backtest_hash=digest,
    )


def _pipeline(tmp_path: Path, *, verdict: ValidationVerdict) -> release._Pipeline:
    digest = "a" * 64
    return release._Pipeline(
        run_root=tmp_path,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
        runtime_fingerprint_hash="3" * 64,
        snapshot_hash="4" * 64,
        view_path=tmp_path / "qlib" / f"sha256-{digest}",
        view_hash="5" * 64,
        qlib_version="0.9.7",
        qlib_source_commit="6" * 40,
        baseline=_variant(tmp_path),
        validation_path=tmp_path / "validation" / f"sha256-{digest}",
        validation_hash="7" * 64,
        validation_verdict=verdict,
        robustness_case_count=16,
    )


def test_variant_build_binds_compact_evidence_and_delegates_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoring, research_policy, validation_policy, cost, backtest_policy = _configs()
    schedule = _schedule(2024)
    built: dict[str, object] = {}

    def compact(*_args: object, **kwargs: object) -> object:
        expression = kwargs["expression"]
        evidence = SimpleNamespace(
            expression_spec_hash=expression.content_hash,  # type: ignore[union-attr]
            bundles=(SimpleNamespace(schedule=schedule),),
            content_hash="8" * 64,
        )
        built["evidence"] = evidence
        return evidence

    class SignalBuilder:
        def build(
            self, resolved: object, evidence: object, *_args: object, **_kwargs: object
        ) -> object:
            assert evidence is built["evidence"]
            assert resolved.pit_audit_evidence_hash == "8" * 64  # type: ignore[union-attr]
            return SimpleNamespace(
                path=tmp_path / "signals" / f"sha256-{'9' * 64}",
                manifest=SimpleNamespace(artifact_hash="9" * 64),
            )

    class BacktestService:
        def run(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                path=tmp_path / "backtests" / f"sha256-{'a' * 64}",
                manifest=SimpleNamespace(result_hash="a" * 64),
            )

    monkeypatch.setattr(release, "build_compact_pit_evidence_collection", compact)
    monkeypatch.setattr(release, "FactorSignalArtifactBuilder", SignalBuilder)
    monkeypatch.setattr(release, "QlibBacktestService", BacktestService)
    cache: dict[tuple[str, str], object] = {}

    result = release._build_variant(
        authoring=authoring,
        research_policy=research_policy,
        validation_policy=validation_policy,
        cost_policy=cost,
        backtest_policy=backtest_policy,
        snapshot_path=tmp_path / f"sha256-{'b' * 64}",
        snapshot_hash="b" * 64,
        view_path=tmp_path / f"sha256-{'c' * 64}",
        view_hash="c" * 64,
        view_version="0.9.7",
        view_spec_hash="d" * 64,
        schedules=(schedule,),
        output_root=tmp_path,
        workspace=ROOT,
        commit_hash="1" * 40,
        lockfile_hash="2" * 64,
        evidence_cache=cache,  # type: ignore[arg-type]
    )

    assert result.signal_hash == "9" * 64
    assert result.backtest_hash == "a" * 64
    assert cache


def test_pipeline_builds_complete_robustness_grid_and_accepts_soft_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoring, research_policy, validation_policy, cost, backtest_policy = _configs()
    snapshot_path = tmp_path / f"sha256-{'a' * 64}"
    schedules = tuple(_schedule(year) for year in (2016, 2019, 2022, 2024))
    calls: list[object] = []

    monkeypatch.setattr(
        release,
        "capture_code_provenance",
        lambda _workspace: SimpleNamespace(commit_hash="1" * 40, lockfile_hash="2" * 64),
    )
    monkeypatch.setattr(
        release,
        "verify_snapshot",
        lambda _path: SimpleNamespace(
            snapshot_hash="a" * 64,
            source_kind=SnapshotSourceKind.TUSHARE,
            limitations=("SINGLE_SOURCE_NON_VINTAGE",),
        ),
    )

    class ViewBuilder:
        def build(self, *_args: object) -> object:
            return SimpleNamespace(
                path=tmp_path / "views" / f"sha256-{'b' * 64}",
                manifest=SimpleNamespace(
                    view_hash="b" * 64,
                    qlib_version="0.9.7",
                    view_spec_hash="c" * 64,
                    qlib_source_commit="d" * 40,
                ),
            )

    def build_variant(**_kwargs: object) -> release._Variant:
        result = _variant(tmp_path, len(calls) + 1)
        result = release._Variant(
            **{
                **result.__dict__,
                "evidence": SimpleNamespace(content_hash="e" * 64),
            }
        )
        calls.append(result)
        return result

    class BacktestService:
        def run(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(path=tmp_path / "repro" / f"sha256-{'f' * 64}")

    report = SimpleNamespace(
        run_status=RunStatus.SUCCEEDED,
        verdict=ValidationVerdict.REJECT,
        gates=(SimpleNamespace(severity=GateSeverity.HARD, verdict=ValidationVerdict.PASS),),
        reproducibility=SimpleNamespace(passed=True),
        runtime_fingerprint_hash="3" * 64,
        report_hash="4" * 64,
        robustness_cases=tuple(range(16)),
    )

    class Validator:
        def run(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(path=tmp_path / "validation" / f"sha256-{'4' * 64}")

    monkeypatch.setattr(release, "QlibViewBuilder", ViewBuilder)
    monkeypatch.setattr(release, "resolve_weekly_decision_schedules", lambda *_a, **_k: schedules)
    monkeypatch.setattr(release, "_build_variant", build_variant)
    monkeypatch.setattr(release, "subset_compact_pit_evidence", lambda evidence, _s: evidence)
    monkeypatch.setattr(release, "QlibBacktestService", BacktestService)
    monkeypatch.setattr(release, "ValidationService", Validator)
    monkeypatch.setattr(release, "verify_validation_report", lambda _path: report)

    pipeline = release._run_pipeline(
        snapshot_path=snapshot_path,
        qlib_source=tmp_path / "qlib-source",
        run_root=tmp_path / "run",
        workspace=ROOT,
        authoring=authoring,
        research_policy=research_policy,
        validation_policy=validation_policy,
        base_cost=cost,
        backtest_policy=backtest_policy,
        release_time=datetime(2026, 9, 5, tzinfo=UTC),
        validation_event_id=release.uuid5(release._RELEASE_NAMESPACE, "test"),
    )

    expected_variants = 1 + 2 + 8 + len(validation_policy.subperiods)
    assert len(calls) == expected_variants
    assert pipeline.validation_verdict is ValidationVerdict.REJECT
    assert pipeline.robustness_case_count == 16


def test_registration_and_double_run_report_preserve_rejected_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoring, research_policy, validation_policy, cost, backtest_policy = _configs()
    pipeline = _pipeline(tmp_path / "run", verdict=ValidationVerdict.REJECT)

    class Registry:
        def __init__(self, _root: Path) -> None:
            self.status = StrategyStatus.DRAFT

        def register_experiment(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                manifest=SimpleNamespace(
                    snapshot_source_kind=SnapshotSourceKind.TUSHARE,
                    manifest_hash="8" * 64,
                )
            )

        def register_strategy(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(status=self.status)

        def append_strategy_event(self, *_args: object, **_kwargs: object) -> object:
            event_type = _args[2]
            if event_type is release.EventType.VALIDATION_STARTED:
                self.status = StrategyStatus.VALIDATING
            elif event_type is release.EventType.VALIDATION_REJECTED:
                self.status = StrategyStatus.REJECTED
            elif event_type is release.EventType.STRATEGY_VERSION_VALIDATED:
                self.status = StrategyStatus.VALIDATED
            return SimpleNamespace(status=self.status)

        def verify(self) -> object:
            return SimpleNamespace(
                experiments=(object(),), strategies=(object(),), index_hash="9" * 64
            )

    monkeypatch.setattr(release, "RegistryService", Registry)
    registered = release._register_pipeline(
        pipeline,
        snapshot_path=tmp_path / f"sha256-{'4' * 64}",
        authoring=authoring,
        strategy_id="hs300-momentum",
        release_time=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert registered.strategy_status is StrategyStatus.REJECTED

    validated = release._register_pipeline(
        _pipeline(tmp_path / "validated", verdict=ValidationVerdict.PASS),
        snapshot_path=tmp_path / f"sha256-{'4' * 64}",
        authoring=authoring,
        strategy_id="hs300-momentum",
        release_time=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert validated.strategy_status is StrategyStatus.VALIDATED

    monkeypatch.setattr(
        release,
        "verify_snapshot",
        lambda _path: SimpleNamespace(snapshot_hash=pipeline.snapshot_hash),
    )
    monkeypatch.setattr(release, "_run_pipeline", lambda **_kwargs: pipeline)
    monkeypatch.setattr(release, "_register_pipeline", lambda *_a, **_k: registered)
    output = tmp_path / "release"
    output.mkdir()
    report = release.run_data_qualified_release(
        snapshot_path=tmp_path / f"sha256-{'4' * 64}",
        qlib_source=tmp_path / "qlib-source",
        output_root=output,
        workspace=ROOT,
        authoring=authoring,
        research_policy=research_policy,
        validation_policy=validation_policy,
        base_cost=cost,
        backtest_policy=backtest_policy,
        release_time=datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert report["data_qualified"] is True
    assert report["validation_verdict"] is ValidationVerdict.REJECT
    assert report["strategy_status"] is StrategyStatus.REJECTED
    assert (output / "report.json").is_file()


def test_helpers_change_only_requested_variant_fields() -> None:
    authoring, _research, _validation, cost, _backtest = _configs()
    variant = release._variant_authoring(authoring, window=25, top_k=60)
    stressed = release._scaled_cost(cost, 2.0)

    assert variant.expression.window == 25
    assert variant.strategy.top_k == 60
    assert variant.evaluation_start == authoring.evaluation_start
    assert stressed.open_cost_rate == cost.open_cost_rate * 2
    assert stressed.minimum_cost_cny == cost.minimum_cost_cny * 2


def test_data_qualified_helpers_preserve_a_single_window_generic_dag() -> None:
    authoring, *_rest = _configs()
    expression = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="absolute_delta",
        nodes=(
            SafeExpressionNode(
                node_id="price",
                operator=SafeQlibOperator.FIELD,
                field_name="adjusted_close",
            ),
            SafeExpressionNode(
                node_id="delta",
                operator=SafeQlibOperator.DELTA,
                inputs=("price",),
                window=2,
            ),
            SafeExpressionNode(node_id="output", operator=SafeQlibOperator.ABS, inputs=("delta",)),
        ),
        output_node_id="output",
    )
    generic = authoring.model_copy(update={"expression": expression})
    variant = release._variant_authoring(generic, window=5, top_k=60)

    assert isinstance(variant.expression, SafeQlibExpressionSpec)
    assert variant.expression.nodes[1].window == 5
    assert variant.expression.nodes[2].operator is SafeQlibOperator.ABS
    assert tuple(item.operator for item in release._operator_delays(variant)) == (
        SafeQlibOperator.ABS,
        SafeQlibOperator.DELTA,
    )
