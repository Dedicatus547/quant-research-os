#!/usr/bin/env python3
"""Run the locked, offline Qlib P0 feasibility spike on synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import qlib
from qlib.backtest import backtest
from qlib.config import REG_CN
from qlib.contrib.model.gbdt import LGBModel
from qlib.data import D
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP
from qlib.workflow import R
from qlib.workflow.record_temp import SigAnaRecord, SignalRecord

from quantos.artifacts import atomic_write_bytes
from quantos.backtest import normalize_qlib_outputs, reconcile_backtest_output
from quantos.backtest.service import translate_backtest_config_schedule_hash
from quantos.contracts.backtest import QlibBacktestConfig
from quantos.contracts.temporal import DecisionSchedule
from quantos.integrations.qlib import QLIB_COMMIT, run_checked, verify_official_qlib_tools

SYMBOLS = ("SH600000", "SZ000001", "SH600001")
BENCHMARK = "SH000300"
ALL_INSTRUMENTS = (*SYMBOLS, BENCHMARK)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _verify_qlib_source(source_root: Path) -> tuple[Path, Path]:
    tools = verify_official_qlib_tools(source_root)
    return tools.dump_bin, tools.check_data_health


def _prepare_csv_files(root: Path, *, constraints: bool = False) -> pd.DatetimeIndex:
    root.mkdir(parents=True)
    # Qlib's daily trade calendar requires one following session to close the final step.
    dates = pd.bdate_range("2024-01-02", periods=17)
    for symbol_index, symbol in enumerate(ALL_INSTRUMENTS):
        step = np.arange(len(dates), dtype=float)
        close = 10.0 + symbol_index * 2.0 + step * (0.04 + symbol_index * 0.01)
        open_price = close - 0.02
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": open_price,
                "high": close + 0.08,
                "low": open_price - 0.08,
                "close": close,
                "volume": 100_000.0 + step * 1_000.0 + symbol_index * 10_000.0,
                "factor": 1.0,
                "change": pd.Series(close).pct_change(fill_method=None).fillna(0.0),
                "limit_buy": 0.0,
                "limit_sell": 0.0,
                "is_st": 0.0,
            }
        )
        if constraints and symbol == "SZ000001":
            frame.loc[9, "limit_buy"] = 1.0
        if constraints and symbol == "SH600001":
            frame.loc[14, "is_st"] = 1.0
        if constraints and symbol == "SH600000":
            frame.loc[15, ["open", "high", "low", "close", "volume"]] = np.nan
        frame.to_csv(root / f"{symbol.lower()}.csv", index=False)
    return dates


def _dump_with_official_tool(dump_script: Path, csv_dir: Path, qlib_dir: Path) -> str:
    result = run_checked(
        [
            sys.executable,
            str(dump_script),
            "dump_all",
            "--data_path",
            str(csv_dir),
            "--qlib_dir",
            str(qlib_dir),
            "--freq",
            "day",
            "--max_workers",
            "1",
            "--date_field_name",
            "date",
            "--include_fields",
            "open,high,low,close,volume,factor,change,limit_buy,limit_sell,is_st",
        ]
    )
    return result.stdout


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        with path.open("rb") as stream:
            hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    return hashes


def _query_and_backtest(qlib_dir: Path, dates: pd.DatetimeIndex) -> dict[str, object]:
    qlib.init(provider_uri=str(qlib_dir), region=REG_CN)
    queried = D.features(
        [SYMBOLS[0]],
        ["$close", "Ref($close, 1)"],
        start_time=dates[0],
        end_time=dates[-1],
        freq="day",
    )
    if queried.empty or queried["$close"].isna().all():
        raise RuntimeError("Qlib expression query produced no data")

    signal_index = pd.MultiIndex.from_product([dates, SYMBOLS], names=["datetime", "instrument"])
    scores = pd.Series(
        [
            float(((date_index + 1) * (symbol_index + 2)) % 11)
            for date_index in range(len(dates))
            for symbol_index in range(len(SYMBOLS))
        ],
        index=signal_index,
        name="score",
    )
    strategy = {
        "class": "FullReplacementTopKStrategy",
        "module_path": "quantos.backtest.strategy",
        "kwargs": {
            "signal": scores,
            "topk": 1,
            "max_weight": 0.5,
            "risk_degree": 1.0,
        },
    }
    executor = {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {
            "time_per_step": "day",
            "generate_portfolio_metrics": True,
            "trade_type": "serial",
            "settle_type": "None",
        },
    }
    portfolio, indicators = backtest(
        start_time=dates[1],
        end_time=dates[-2],
        strategy=strategy,
        executor=executor,
        benchmark=BENCHMARK,
        account=1_000_000,
        exchange_kwargs={
            "freq": "day",
            "codes": list(SYMBOLS),
            "deal_price": "open",
            "limit_threshold": ("$limit_buy+$is_st", "$limit_sell+$is_st"),
            "volume_threshold": {"all": ("current", "$volume*0.1")},
            "open_cost": 0.0005,
            "close_cost": 0.0015,
            "min_cost": 5.0,
            "trade_unit": 100,
        },
    )
    report, positions = portfolio["1day"]
    if report.empty or not positions:
        raise RuntimeError("Qlib tiny backtest produced no portfolio evidence")
    indicator_frame = indicators["1day"][0]
    inverse_mappings = {symbol: f"{symbol[2:]}.{symbol[:2]}" for symbol in SYMBOLS}
    factors = {(timestamp.date(), symbol): 1.0 for timestamp in dates for symbol in SYMBOLS}
    normalized = normalize_qlib_outputs(
        portfolio,
        indicators,
        inverse_mappings=inverse_mappings,
        factors=factors,
    )
    return {
        "query_rows": len(queried),
        "query_columns": list(queried.columns),
        "backtest_rows": len(report),
        "position_snapshots": len(positions),
        "indicator_rows": len(indicator_frame),
        "normalized_order_rows": len(normalized.order_indicators),
        "normalized_position_rows": len(normalized.positions),
        "normalized_risk_metric_rows": len(normalized.risk_metrics),
        "strategy_adapter": "FullReplacementTopKStrategy",
        "executor": "SimulatorExecutor",
        "exchange_limit_fields": ("$limit_buy+$is_st", "$limit_sell+$is_st"),
        "trade_unit_shares": 100,
    }


def _constraint_backtest(qlib_dir: Path, dates: pd.DatetimeIndex) -> dict[str, bool]:
    qlib.init(provider_uri=str(qlib_dir), region=REG_CN)
    signal_rows = (
        (3, "SH600000"),
        (8, "SZ000001"),
        (13, "SH600001"),
        (14, "SH600000"),
    )
    index: list[tuple[pd.Timestamp, str]] = []
    values: list[float] = []
    for date_index, selected in signal_rows:
        for symbol in SYMBOLS:
            index.append((dates[date_index], symbol))
            values.append(10.0 if symbol == selected else 0.0)
    scores = pd.Series(
        values,
        index=pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"]),
        name="score",
    )
    portfolio, indicators = backtest(
        start_time=dates[4],
        end_time=dates[15],
        strategy={
            "class": "FullReplacementTopKStrategy",
            "module_path": "quantos.backtest.strategy",
            "kwargs": {
                "signal": scores,
                "topk": 1,
                "max_weight": 0.002,
                "risk_degree": 1.0,
            },
        },
        executor={
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {
                "time_per_step": "day",
                "generate_portfolio_metrics": True,
                "trade_type": "serial",
                "settle_type": "None",
            },
        },
        benchmark=BENCHMARK,
        account=1_000_000,
        exchange_kwargs={
            "freq": "day",
            "codes": list(SYMBOLS),
            "start_time": dates[3],
            "end_time": dates[15],
            "deal_price": "open",
            "limit_threshold": ("$limit_buy+$is_st", "$limit_sell+$is_st"),
            "volume_threshold": {"all": ("current", "$volume*0.1")},
            "open_cost": 0.0005,
            "close_cost": 0.0015,
            "min_cost": 5.0,
            "trade_unit": 100,
        },
    )
    inverse_mappings = {symbol: f"{symbol[2:]}.{symbol[:2]}" for symbol in SYMBOLS}
    factors = {(timestamp.date(), symbol): 1.0 for timestamp in dates for symbol in SYMBOLS}
    normalized = normalize_qlib_outputs(
        portfolio,
        indicators,
        inverse_mappings=inverse_mappings,
        factors=factors,
    )
    schedules = tuple(
        DecisionSchedule(
            signal_time=datetime.combine(
                dates[signal_index].date(), datetime.min.time(), SHANGHAI
            ).replace(hour=15),
            signal_available_at=datetime.combine(
                dates[signal_index].date(), datetime.min.time(), SHANGHAI
            ).replace(hour=15, minute=1),
            decision_time=datetime.combine(
                dates[signal_index].date(), datetime.min.time(), SHANGHAI
            ).replace(hour=15, minute=10),
            execution_time=datetime.combine(
                dates[signal_index + 1].date(), datetime.min.time(), SHANGHAI
            ).replace(hour=9, minute=30),
        )
        for signal_index, _ in signal_rows
    )
    config = QlibBacktestConfig(
        resolved_experiment_hash="1" * 64,
        signal_artifact_hash="2" * 64,
        snapshot_hash="3" * 64,
        qlib_view_hash="4" * 64,
        qlib_version="0.9.7",
        cost_policy_hash="5" * 64,
        backtest_policy_hash="6" * 64,
        start_date=dates[4].date(),
        end_date=dates[15].date(),
        exchange_start_date=dates[3].date(),
        exchange_codes=tuple(sorted(SYMBOLS)),
        signal_dates=tuple(schedule.signal_time.date() for schedule in schedules),
        execution_dates=tuple(schedule.execution_time.date() for schedule in schedules),
        decision_schedule_hash=translate_backtest_config_schedule_hash(schedules),
        benchmark=BENCHMARK,
        initial_cash_cny=1_000_000,
        top_k=1,
        max_weight=0.002,
        open_cost_rate=0.0005,
        close_cost_rate=0.0015,
        minimum_cost_cny=5.0,
        volume_threshold=("current", "$volume*0.1"),
    )
    reconciliation = reconcile_backtest_output(normalized, config, schedules)
    orders = normalized.order_indicators
    order_keys = {(str(row["qlib_id"]), row["trade_date"]) for row in orders}
    expected_execution_dates = {dates[index + 1].date() for index, _ in signal_rows}
    nonzero_costs = [
        float(row["trade_cost"])
        for row in orders
        if row["trade_cost"] is not None and abs(float(row["trade_value"] or 0.0)) > 0
    ]
    checks = {
        "normal_order_present": ("SH600000", dates[4].date()) in order_keys,
        "non_rebalance_dates_have_no_orders": {row["trade_date"] for row in orders}.issubset(
            expected_execution_dates
        ),
        "limit_buy_blocks_selected_order": ("SZ000001", dates[9].date()) not in order_keys,
        "st_blocks_selected_order": ("SH600001", dates[14].date()) not in order_keys,
        "suspension_blocks_selected_order": ("SH600000", dates[15].date()) not in order_keys,
        "trade_unit_is_100_raw_shares": all(
            math.isclose(abs(float(row["dealt_raw_shares"])) % 100.0, 0.0, abs_tol=1e-8)
            for row in orders
        ),
        "minimum_commission_is_applied": any(
            math.isclose(value, 5.0, abs_tol=1e-8) for value in nonzero_costs
        ),
        "six_arithmetic_reconciliations_pass": len(reconciliation.checks) == 6,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Qlib constraint golden case failed: {checks}")
    return checks


def _workflow_record_spike(
    work_root: Path, dates: pd.DatetimeIndex, output_dir: Path
) -> dict[str, object]:
    recorder_root = work_root / "mlruns"
    uri = recorder_root.resolve().as_uri()
    handler = DataHandlerLP(
        start_time=dates[0],
        end_time=dates[-1],
        instruments=list(SYMBOLS),
        data_loader={
            "class": "QlibDataLoader",
            "module_path": "qlib.data.dataset.loader",
            "kwargs": {
                "config": {
                    "feature": [["($close/Ref($close,2)-1)"], ["momentum_2d"]],
                    "label": [["Ref($close,-1)/$close-1"], ["LABEL0"]],
                },
                "freq": "day",
            },
        },
        learn_processors=[{"class": "DropnaLabel"}],
    )
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": (dates[2], dates[7]),
            "valid": (dates[9], dates[11]),
            "test": (dates[13], dates[15]),
        },
    )
    model = LGBModel(
        loss="mse",
        learning_rate=0.05,
        max_depth=3,
        num_leaves=7,
        num_threads=1,
        seed=1729,
        feature_fraction_seed=1729,
        bagging_seed=1729,
        data_random_seed=1729,
        deterministic=True,
        force_col_wise=True,
        num_boost_round=20,
        early_stopping_rounds=5,
    )

    previous_file_store_setting = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
    previous_working_directory = Path.cwd()
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    # Qlib 0.9.7 creates its filesystem-store lock from a relative parsed URI path.
    # Keep that upstream quirk inside the disposable work tree instead of the repository.
    os.chdir(work_root)
    try:
        with R.start(experiment_name="quantos-p0", uri=uri):
            recorder = R.get_recorder()
            model.fit(dataset, verbose_eval=0)
            SignalRecord(model, dataset, recorder).generate()
            SigAnaRecord(recorder, ana_long_short=True).generate()
            run_id = recorder.id
        # R.start.__exit__ waits for Qlib's async metric logger before we export evidence.
        raw_metrics = {name: float(value) for name, value in recorder.list_metrics().items()}
        metrics = {name: value for name, value in raw_metrics.items() if math.isfinite(value)}
        omitted_nonfinite_metrics = tuple(
            sorted(name for name, value in raw_metrics.items() if not math.isfinite(value))
        )
        artifacts = sorted(recorder.list_artifacts())
        pred = recorder.load_object("pred.pkl")
    finally:
        os.chdir(previous_working_directory)
        if previous_file_store_setting is None:
            os.environ.pop("MLFLOW_ALLOW_FILE_STORE", None)
        else:
            os.environ["MLFLOW_ALLOW_FILE_STORE"] = previous_file_store_setting

    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_bytes = pred.to_csv().encode("utf-8")
    metrics_bytes = json.dumps(
        metrics, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    prediction_hash = atomic_write_bytes(output_dir / "predictions.csv", prediction_bytes)
    metrics_hash = atomic_write_bytes(output_dir / "metrics.json", metrics_bytes)
    shutil.rmtree(recorder_root)
    if recorder_root.exists():
        raise RuntimeError("local MLflow runtime directory was not removed")
    return {
        "run_id": run_id,
        "metric_names": sorted(metrics),
        "omitted_nonfinite_metric_names": omitted_nonfinite_metrics,
        "artifact_names": artifacts,
        "native_components": ("DatasetH", "LGBModel", "SignalRecord", "SigAnaRecord"),
        "label_horizon_trading_sessions": 1,
        "purged_boundary_sessions": (
            dates[8].date().isoformat(),
            dates[12].date().isoformat(),
        ),
        "prediction_rows": len(pred),
        "exported_prediction_hash": prediction_hash,
        "exported_metrics_hash": metrics_hash,
        "runtime_recorder_deleted_after_export": True,
        "mlflow_file_store_opt_in_required": True,
    }


def run(source_root: Path, output_dir: Path) -> dict[str, object]:
    dump_script, health_script = _verify_qlib_source(source_root)
    # Keep Qlib's asynchronous recorder locks outside the repository even when TMPDIR is remapped.
    with tempfile.TemporaryDirectory(prefix="quantos-qlib-spike-", dir="/tmp") as temporary:
        work_root = Path(temporary)
        csv_dir = work_root / "csv"
        dates = _prepare_csv_files(csv_dir)
        first_dir = work_root / "qlib-first"
        second_dir = work_root / "qlib-second"
        constraint_csv_dir = work_root / "constraint-csv"
        constraint_dates = _prepare_csv_files(constraint_csv_dir, constraints=True)
        constraint_dir = work_root / "qlib-constraints"
        _dump_with_official_tool(dump_script, csv_dir, first_dir)
        _dump_with_official_tool(dump_script, csv_dir, second_dir)
        _dump_with_official_tool(dump_script, constraint_csv_dir, constraint_dir)
        first_hashes = _tree_hashes(first_dir)
        second_hashes = _tree_hashes(second_dir)
        if first_hashes != second_hashes:
            raise RuntimeError("same-version official dump_bin output is not byte reproducible")
        health = run_checked(
            [sys.executable, str(health_script), "--qlib_dir", str(first_dir), "check_data"]
        )
        qlib_result = _query_and_backtest(first_dir, dates)
        workflow_result = _workflow_record_spike(work_root, dates, output_dir)
        qlib_result["golden_constraints"] = _constraint_backtest(constraint_dir, constraint_dates)

    report: dict[str, object] = {
        "schema_version": "qlib-feasibility-report/v1",
        "status": "PASS",
        "qlib_version": qlib.__version__,
        "qlib_source_commit": QLIB_COMMIT,
        "official_dump_bin_file_count": len(first_hashes),
        "same_version_file_hashes_equal": True,
        "data_health_exit_code": health.returncode,
        "qlib": qlib_result,
        "workflow": workflow_result,
        "known_limitations": [
            "pyqlib wheel omits scripts/dump_bin.py and scripts/check_data_health.py",
            (
                "Qlib target-weight precheck blocks both directions when either tuple limit "
                "field is set"
            ),
            "Qlib order indicators expose requested/dealt amounts but no stable reason-code field",
        ],
    }
    encoded = json.dumps(
        report, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    run_id = str(workflow_result["run_id"])
    atomic_write_bytes(output_dir / f"report-{run_id}.json", encoded)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qlib-source",
        type=Path,
        default=Path(".tools/qlib-0.9.7"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/feasibility/qlib-0.9.7"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.qlib_source, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
