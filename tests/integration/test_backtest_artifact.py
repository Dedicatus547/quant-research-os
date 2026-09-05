from __future__ import annotations

import importlib
import json
from datetime import date, datetime
from pathlib import Path
from struct import pack, unpack
from subprocess import CompletedProcess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quantos.application import resolve_experiment
from quantos.backtest import QlibBacktestService, verify_backtest_artifact
from quantos.config import load_yaml_contract
from quantos.contracts.backtest import QlibBacktestConfig
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import OperatorDelayPolicy
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.contracts.signal import SignalRow
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data import qlib_view
from quantos.data.qlib_view import QlibViewBuilder
from quantos.data.snapshot import SyntheticSnapshotBuilder
from quantos.integrations.qlib import QLIB_COMMIT, QLIB_VERSION, OfficialQlibTools
from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    QlibResearchError,
    build_pit_evidence_collection,
)

ROOT = Path(__file__).parents[2]
BACKTEST_FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_backtest_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SERVICE = importlib.import_module("quantos.backtest.service")
SIGNAL_SERVICE = importlib.import_module("quantos.research.qlib.signal")


class _Metric:
    def __init__(self, values: dict[str, float]) -> None:
        self._values = values

    def to_dict(self) -> dict[str, float]:
        return self._values


class _OrderIndicator:
    def __init__(self, qlib_id: str = "SH600000") -> None:
        self.data = {
            name: _Metric({qlib_id: value})
            for name, value in {
                "amount": 100000.0,
                "deal_amount": 100000.0,
                "trade_dir": 1.0,
                "trade_price": 5.0,
                "trade_value": 500000.0,
                "trade_cost": 250.0,
                "ffr": 1.0,
            }.items()
        }


class _IndicatorHistory:
    def __init__(self, timestamp: pd.Timestamp, qlib_id: str = "SH600000") -> None:
        self.order_indicator_his = {timestamp: _OrderIndicator(qlib_id)}


class _Position:
    def __init__(self, qlib_id: str = "SH600000") -> None:
        self.position = {
            qlib_id: {
                "amount": 100000.0,
                "price": 5.0,
                "weight": 500000.0 / 999750.0,
            },
            "cash": 499750.0,
            "now_account_value": 999750.0,
        }


def _schedule() -> DecisionSchedule:
    return DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 15, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 15, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 15, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )


def _raw_qlib_result(
    qlib_id: str = "SH600000",
) -> tuple[dict[str, object], dict[str, object]]:
    timestamp = pd.Timestamp("2024-01-08")
    report = pd.DataFrame(
        [[999750.0, 0.0, 500000.0, 0.5, 250.0, 0.00025, 500000.0, 499750.0, 0.001]],
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
        [[1.0, 0.0, 0.0, 100000.0, 500000.0, 1.0]],
        index=pd.DatetimeIndex([timestamp]),
        columns=["ffr", "pa", "pos", "deal_amount", "value", "count"],
    )
    return (
        {"1day": (report, {timestamp: _Position(qlib_id)})},
        {"1day": (trade, _IndicatorHistory(timestamp, qlib_id))},
    )


def test_backtest_service_publishes_idempotent_hash_bound_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authoring = load_yaml_contract(
        ROOT / "configs" / "research" / "hs300_momentum_v1.yaml",
        ExperimentAuthoringSpec,
    )
    cost = load_yaml_contract(ROOT / "configs" / "backtest" / "cost_v1.yaml", CostPolicy)
    policy = load_yaml_contract(ROOT / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy)
    resolved = resolve_experiment(
        authoring,
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        qlib_version="0.9.7",
        qlib_view_spec_hash="c" * 64,
        pit_audit_evidence_hash="d" * 64,
        research_policy_hash="e" * 64,
        validation_policy_hash="f" * 64,
        cost_policy_hash=cost.content_hash,
        backtest_policy_hash=policy.content_hash,
        code_commit_hash="1" * 40,
        lockfile_hash="2" * 64,
    )
    schedule = _schedule()
    signal_row = SignalRow(
        instrument_id="600000.SH",
        signal_time=schedule.signal_time,
        decision_time=schedule.decision_time,
        available_at=datetime(2024, 1, 5, 14, 59, tzinfo=SHANGHAI),
        score=0.1,
        tradable=True,
    )
    signal_manifest = SimpleNamespace(
        artifact_hash="3" * 64,
        resolved_experiment_hash=resolved.content_hash,
    )
    evidence = SimpleNamespace(bundles=(SimpleNamespace(schedule=schedule),))
    view = SimpleNamespace(
        view_hash=resolved.qlib_view_hash,
        source_snapshot_hash=resolved.snapshot_hash,
        qlib_version=resolved.qlib_version,
    )
    view_path = tmp_path / "view"
    (view_path / "calendars").mkdir(parents=True)
    (view_path / "calendars" / "day.txt").write_text("2024-01-05\n2024-01-08\n", encoding="utf-8")

    monkeypatch.setattr(SERVICE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(SERVICE, "verify_signal_artifact", lambda _path: signal_manifest)
    monkeypatch.setattr(
        SERVICE,
        "_read_signal_inputs",
        lambda _path: (resolved, evidence, (signal_row,)),
    )
    monkeypatch.setattr(SERVICE, "verify_qlib_view", lambda _path: view)
    monkeypatch.setattr(
        SERVICE,
        "_load_view_mappings",
        lambda _path: ({"600000.SH": "SH600000"}, {"SH600000": "600000.SH"}),
    )
    monkeypatch.setattr(SERVICE.qlib, "init", lambda **_kwargs: None)
    monkeypatch.setattr(SERVICE, "_QLIB_BACKTEST", lambda **_kwargs: _raw_qlib_result())
    monkeypatch.setattr(
        SERVICE,
        "_factor_lookup",
        lambda *_args: {(date(2024, 1, 8), "SH600000"): 1.0},
    )

    output_root = tmp_path / "backtests"
    first = QlibBacktestService().run(
        resolved,
        tmp_path / "signal",
        view_path,
        cost,
        policy,
        output_root,
    )
    repeated = QlibBacktestService().run(
        resolved,
        tmp_path / "signal",
        view_path,
        cost,
        policy,
        output_root,
    )

    assert first.path == repeated.path
    assert first.manifest == verify_backtest_artifact(first.path)
    assert first.manifest.signal_artifact_hash == signal_manifest.artifact_hash
    assert first.manifest.order_indicator_rows == 1
    assert first.manifest.position_rows == 1

    (first.path / "portfolio.parquet").write_bytes(b"tampered")
    with pytest.raises(QlibResearchError) as corrupted:
        verify_backtest_artifact(first.path)
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


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


def _build_verified_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    snapshot = SyntheticSnapshotBuilder().build(BACKTEST_FIXTURE, tmp_path / "snapshots")
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
            values = {
                key: unpack("<f", pack("<f", value))[0]
                for key, value in {
                    "SZ000001": 12.1,
                    "SH000300": 3320.0,
                    "SH600000": 10.2,
                }.items()
            }
            requests = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            actual = {item["qlib_id"]: values[item["qlib_id"]] for item in requests}
            return CompletedProcess(
                command, 0, stdout=f"QUANTOS_SAMPLES={json.dumps(actual, sort_keys=True)}\n"
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    view = QlibViewBuilder().build(snapshot.path, tmp_path / "views", official.source_root)
    return snapshot, view


def test_verified_signal_to_backtest_artifact_chain_binds_runtime_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_verified_view(tmp_path, monkeypatch)
    cost = load_yaml_contract(ROOT / "configs" / "backtest" / "cost_v1.yaml", CostPolicy)
    policy = load_yaml_contract(ROOT / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy)
    authoring = ExperimentAuthoringSpec.model_validate(
        {
            "experiment_id": "synthetic-backtest-chain-v1",
            "evaluation_start": "2024-01-02",
            "evaluation_end": "2024-01-05",
            "expression": {
                "expression_id": "momentum_1d",
                "operator": "return",
                "field": "adjusted_close",
                "window": 1,
            },
            "strategy": {"universe_index": "000300.SH", "top_k": 1},
        }
    )
    schedule = _schedule().model_copy(
        update={
            "signal_time": datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
            "signal_available_at": datetime(2024, 1, 5, 16, 1, tzinfo=SHANGHAI),
            "decision_time": datetime(2024, 1, 5, 16, 10, tzinfo=SHANGHAI),
        }
    )
    provisional = resolve_experiment(
        authoring,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_view_spec_hash=view.manifest.view_spec_hash,
        pit_audit_evidence_hash="0" * 64,
        research_policy_hash="1" * 64,
        validation_policy_hash="2" * 64,
        cost_policy_hash=cost.content_hash,
        backtest_policy_hash=policy.content_hash,
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
                policy_id="qlib-return-delay-60s/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=(schedule,),
    )
    resolved = provisional.model_copy(update={"pit_audit_evidence_hash": evidence.content_hash})
    monkeypatch.setattr(SIGNAL_SERVICE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        SIGNAL_SERVICE,
        "_execute_expression",
        lambda *_args, **_kwargs: {"SZ000001": 0.012244897959183598},
    )
    signal = FactorSignalArtifactBuilder().build(
        resolved,
        evidence,
        view.path,
        tmp_path / "signals",
    )

    captured: dict[str, object] = {}

    def fake_backtest(**kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
        captured.update(kwargs)
        return _raw_qlib_result("SZ000001")

    monkeypatch.setattr(SERVICE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(SERVICE.qlib, "init", lambda **_kwargs: None)
    monkeypatch.setattr(SERVICE, "_QLIB_BACKTEST", fake_backtest)
    monkeypatch.setattr(
        SERVICE,
        "_factor_lookup",
        lambda *_args: {(date(2024, 1, 8), "SZ000001"): 1.0},
    )
    result = QlibBacktestService().run(
        resolved,
        signal.path,
        view.path,
        cost,
        policy,
        tmp_path / "backtests",
    )

    assert verify_backtest_artifact(result.path) == result.manifest
    config = QlibBacktestConfig.model_validate_json(
        (result.path / "backtest-config.json").read_bytes()
    )
    assert config.exchange_codes == ("SZ000001",)
    assert captured["pos_type"] == "Position"
    exchange = captured["exchange_kwargs"]
    assert isinstance(exchange, dict)
    assert exchange["codes"] == ["SZ000001"]
    strategy = captured["strategy"]
    assert isinstance(strategy, dict)
    strategy_kwargs = strategy["kwargs"]
    assert isinstance(strategy_kwargs, dict)
    assert strategy_kwargs["order_generator_cls_or_obj"] is SERVICE._QLIB_ORDER_GENERATOR
