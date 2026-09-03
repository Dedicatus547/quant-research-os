from __future__ import annotations

import importlib
from datetime import date, datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quantos.application import resolve_experiment
from quantos.backtest import QlibBacktestService
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import OperatorDelayPolicy
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    HardGateId,
    ResearchPolicy,
    ResearchSegment,
    ResolvedExperimentSpec,
    ValidationPolicy,
    ValidationSubperiod,
)
from quantos.contracts.status import RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.data import QlibViewBuilder, SyntheticSnapshotBuilder, qlib_view
from quantos.integrations.qlib import QLIB_COMMIT, QLIB_VERSION, OfficialQlibTools
from quantos.research.qlib import FactorSignalArtifactBuilder, build_pit_evidence_collection
from quantos.validation import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationError,
    ValidationRunLocators,
    ValidationService,
    verify_validation_report,
)

ROOT = Path(__file__).parents[2]
FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_backtest_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")
BACKTEST_SERVICE = importlib.import_module("quantos.backtest.service")
SIGNAL_SERVICE = importlib.import_module("quantos.research.qlib.signal")


class _Metric:
    def __init__(self, values: dict[str, float]) -> None:
        self._values = values

    def to_dict(self) -> dict[str, float]:
        return self._values


class _OrderIndicator:
    def __init__(self, fee: float) -> None:
        self.data = {
            name: _Metric({"SZ000001": value})
            for name, value in {
                "amount": 40000.0,
                "deal_amount": 40000.0,
                "trade_dir": 1.0,
                "trade_price": 12.5,
                "trade_value": 500000.0,
                "trade_cost": fee,
                "ffr": 1.0,
            }.items()
        }


class _IndicatorHistory:
    def __init__(self, timestamp: pd.Timestamp, fee: float) -> None:
        self.order_indicator_his = {timestamp: _OrderIndicator(fee)}


class _Position:
    def __init__(self, fee: float) -> None:
        account = 1_000_000.0 - fee
        self.position = {
            "SZ000001": {
                "amount": 40000.0,
                "price": 12.5,
                "weight": 500000.0 / account,
            },
            "cash": 500000.0 - fee,
            "now_account_value": account,
        }


def _fake_backtest(**kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
    exchange = cast(dict[str, object], kwargs["exchange_kwargs"])
    fee = 500000.0 * cast(float, exchange["open_cost"])
    account = 1_000_000.0 - fee
    timestamp = pd.Timestamp("2024-01-08")
    report = pd.DataFrame(
        [[account, 0.0, 500000.0, 0.5, fee, fee / 1_000_000.0, 500000.0, 500000.0 - fee, 0.001]],
        index=pd.DatetimeIndex([timestamp], name="datetime"),
        columns=[
            "account",
            "return",
            "total_turnover",
            "turnover",
            "total_cost",
            "cost",
            "value",
            "cash",
            "bench",
        ],
    )
    trade = pd.DataFrame(
        [[1.0, 0.0, 0.0, 40000.0, 500000.0, 1.0]],
        index=pd.DatetimeIndex([timestamp]),
        columns=["ffr", "pa", "pos", "deal_amount", "value", "count"],
    )
    return (
        {"1day": (report, {timestamp: _Position(fee)})},
        {"1day": (trade, _IndicatorHistory(timestamp, fee))},
    )


def _fake_tools(tmp_path: Path) -> OfficialQlibTools:
    source = tmp_path / "qlib-source"
    source.mkdir()
    dump = source / "dump_bin.py"
    health = source / "check_data_health.py"
    dump.touch()
    health.touch()
    return OfficialQlibTools(
        source,
        dump,
        health,
        QLIB_COMMIT,
        QLIB_VERSION,
        "a" * 64,
        "b" * 64,
    )


def _build_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    official = _fake_tools(tmp_path)
    monkeypatch.setattr(qlib_view, "verify_official_qlib_tools", lambda _path: official)

    def fake_run(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if "dump_all" in command:
            qlib_root = Path(command[command.index("--qlib_dir") + 1])
            (qlib_root / "calendars").mkdir(parents=True)
            (qlib_root / "calendars" / "day.txt").write_text(
                "2024-01-02\n2024-01-03\n2024-01-04\n2024-01-05\n2024-01-08\n2024-01-09\n",
                encoding="utf-8",
            )
            return CompletedProcess(command, 0, stdout="dumped")
        if "check_data" in command:
            return CompletedProcess(command, 0, stdout="healthy")
        if "-c" in command:
            values = {"SZ000001": 12.1, "SH000300": 3320.0, "SH600000": 10.2}
            return CompletedProcess(command, 0, stdout=f"QUANTOS_SAMPLE={values[command[-2]]}\n")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    view = QlibViewBuilder().build(snapshot.path, tmp_path / "views", official.source_root)
    return snapshot, view


def _policies() -> tuple[ResearchPolicy, ValidationPolicy, CostPolicy, BacktestPolicy]:
    research = ResearchPolicy(
        policy_id="synthetic-validation-research-v1",
        train=ResearchSegment(start=date(2023, 12, 1), end=date(2023, 12, 15)),
        validation=ResearchSegment(start=date(2023, 12, 20), end=date(2024, 1, 4)),
        test=ResearchSegment(start=date(2024, 1, 5), end=date(2024, 1, 9)),
        purge_trading_days=1,
        label_horizon_trading_sessions=1,
        random_seed=7,
        num_threads=1,
        num_boost_round=2,
        early_stopping_rounds=1,
    )
    validation = ValidationPolicy(
        policy_id="synthetic-validation-v1",
        hard_gates=tuple(HardGateId),
        minimum_oos_observations=1,
        parameter_windows=(1,),
        parameter_top_k=(1,),
        subperiods=(
            ValidationSubperiod(
                period_id="synthetic-2024",
                start=date(2024, 1, 2),
                end=date(2024, 1, 9),
            ),
        ),
        minimum_subperiod_observations=1,
    )
    cost = CostPolicy(
        policy_id="synthetic-cost-v1",
        open_cost_rate=0.0005,
        close_cost_rate=0.0015,
        minimum_cost_cny=5.0,
        trade_unit_shares=100,
        volume_limit_fraction=0.1,
    )
    backtest = BacktestPolicy(
        policy_id="synthetic-backtest-v1",
        benchmark="SH000300",
        initial_cash_cny=1_000_000.0,
    )
    return research, validation, cost, backtest


def test_synthetic_validation_e2e_passes_all_gates_and_detects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    research, validation, base_cost, backtest_policy = _policies()
    authoring = ExperimentAuthoringSpec.model_validate(
        {
            "experiment_id": "synthetic-validation-e2e-v1",
            "evaluation_start": "2024-01-02",
            "evaluation_end": "2024-01-09",
            "expression": {
                "expression_id": "momentum_1d",
                "operator": "return",
                "field": "adjusted_close",
                "window": 1,
            },
            "strategy": {"universe_index": "000300.SH", "top_k": 1},
        }
    )
    schedule = DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 16, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 16, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )
    provisional = resolve_experiment(
        authoring,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_view_spec_hash=view.manifest.view_spec_hash,
        pit_audit_evidence_hash="0" * 64,
        research_policy_hash=research.content_hash,
        validation_policy_hash=validation.content_hash,
        cost_policy_hash=base_cost.content_hash,
        backtest_policy_hash=backtest_policy.content_hash,
        code_commit_hash="4" * 40,
        lockfile_hash="5" * 64,
    )
    evidence = build_pit_evidence_collection(
        snapshot.path,
        view.path,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=provisional.expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="synthetic-return-delay/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=(schedule,),
    )
    monkeypatch.setattr(SIGNAL_SERVICE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        SIGNAL_SERVICE,
        "_execute_expression",
        lambda *_args, **_kwargs: {"SZ000001": 0.012},
    )
    monkeypatch.setattr(BACKTEST_SERVICE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(BACKTEST_SERVICE.qlib, "init", lambda **_kwargs: None)
    monkeypatch.setattr(BACKTEST_SERVICE, "_QLIB_BACKTEST", _fake_backtest)
    monkeypatch.setattr(
        BACKTEST_SERVICE,
        "_factor_lookup",
        lambda *_args: {(date(2024, 1, 8), "SZ000001"): 1.0},
    )

    variants: dict[float, tuple[object, object, ResolvedExperimentSpec, CostPolicy]] = {}
    for multiplier in validation.cost_stress_multipliers:
        cost = CostPolicy.model_validate(
            {
                **base_cost.model_dump(mode="python"),
                "policy_id": f"synthetic-cost-{multiplier:.1f}x-v1",
                "open_cost_rate": base_cost.open_cost_rate * multiplier,
                "close_cost_rate": base_cost.close_cost_rate * multiplier,
                "minimum_cost_cny": base_cost.minimum_cost_cny * multiplier,
            }
        )
        resolved = ResolvedExperimentSpec.model_validate(
            resolve_experiment(
                authoring,
                snapshot_hash=snapshot.manifest.snapshot_hash,
                qlib_view_hash=view.manifest.view_hash,
                qlib_version=view.manifest.qlib_version,
                qlib_view_spec_hash=view.manifest.view_spec_hash,
                pit_audit_evidence_hash=evidence.content_hash,
                research_policy_hash=research.content_hash,
                validation_policy_hash=validation.content_hash,
                cost_policy_hash=cost.content_hash,
                backtest_policy_hash=backtest_policy.content_hash,
                code_commit_hash="4" * 40,
                lockfile_hash="5" * 64,
            ).model_dump(mode="python")
        )
        signal = FactorSignalArtifactBuilder().build(
            resolved,
            evidence,
            view.path,
            tmp_path / "signals",
        )
        backtest = QlibBacktestService().run(
            resolved,
            signal.path,
            view.path,
            cost,
            backtest_policy,
            tmp_path / "backtests",
        )
        variants[multiplier] = (signal, backtest, resolved, cost)

    baseline_signal, baseline_backtest, baseline_resolved, baseline_cost = variants[1.0]
    reproduced = QlibBacktestService().run(
        baseline_resolved,
        baseline_signal.path,
        view.path,
        baseline_cost,
        backtest_policy,
        tmp_path / "reproduction",
    )
    locators = ValidationRunLocators(
        snapshot_path=snapshot.path,
        qlib_view_path=view.path,
        signal_path=baseline_signal.path,
        baseline_backtest_path=baseline_backtest.path,
        reproduction_backtest_path=reproduced.path,
        cost_stress=tuple(
            CostStressLocator(
                multiplier=multiplier,
                signal_path=variants[multiplier][0].path,
                backtest_path=variants[multiplier][1].path,
            )
            for multiplier in validation.cost_stress_multipliers
        ),
        parameter_stability=(
            ParameterStabilityLocator(
                window=1,
                top_k=1,
                signal_path=baseline_signal.path,
                backtest_path=baseline_backtest.path,
            ),
        ),
        subperiods=(
            SubperiodLocator(
                period_id="synthetic-2024",
                start=date(2024, 1, 2),
                end=date(2024, 1, 9),
                signal_path=baseline_signal.path,
                backtest_path=baseline_backtest.path,
            ),
        ),
    )

    first = ValidationService().run(
        authoring,
        validation,
        research,
        locators,
        tmp_path / "validation",
        tmp_path / "events",
        canonical=False,
    )
    repeated = ValidationService().run(
        authoring,
        validation,
        research,
        locators,
        tmp_path / "validation",
        tmp_path / "events",
        canonical=False,
    )

    assert first.path == repeated.path
    assert first.report.run_status is RunStatus.SUCCEEDED
    assert first.report.verdict is ValidationVerdict.PASS
    assert all(gate.verdict is ValidationVerdict.PASS for gate in first.report.gates)
    assert first.report.oos_access_event is not None
    assert len(first.report.robustness_cases) == 5
    assert first.report.reproducibility is not None
    assert first.report.reproducibility.exact_content_hash is True
    assert verify_validation_report(first.path) == first.report
    assert len(tuple((tmp_path / "events").rglob("*.json"))) == 2

    policy_path = first.path / "validation-policy.json"
    policy_bytes = policy_path.read_bytes()
    policy_path.write_bytes(b"tampered")
    with pytest.raises(ValidationError):
        verify_validation_report(first.path)
    policy_path.write_bytes(policy_bytes)
    runtime_path = first.path / "runtime-fingerprint.json"
    runtime_bytes = runtime_path.read_bytes()
    runtime_path.write_bytes(b"tampered")
    with pytest.raises(ValidationError):
        verify_validation_report(first.path)
    runtime_path.write_bytes(runtime_bytes)
    report_path = first.path / "report.json"
    report_path.write_bytes(report_path.read_bytes() + b"\n")
    with pytest.raises(ValidationError, match="not canonical"):
        verify_validation_report(first.path)
