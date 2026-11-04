"""Qlib Workflow/Record Templates for executable personal strategy candidates."""

from __future__ import annotations

import importlib
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pandas as pd
import qlib  # pyright: ignore[reportMissingTypeStubs]
from qlib.config import REG_CN  # pyright: ignore[reportMissingTypeStubs]
from qlib.workflow import R  # pyright: ignore[reportMissingTypeStubs]

from quantos.artifacts.store import atomic_write_bytes, regular_tree_files, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.personal_strategy import PersonalExecutionPolicy, PersonalStrategy
from quantos.research.personal_qlib import (
    _metrics,  # pyright: ignore[reportPrivateUsage]
    _native_order_rows,  # pyright: ignore[reportPrivateUsage]
)
from quantos.research.qlib.workflow import (
    _WORKFLOW_LOCK,  # pyright: ignore[reportPrivateUsage]
    _flush_recorder_logs,  # pyright: ignore[reportPrivateUsage]
    _workflow_tracking_runtime,  # pyright: ignore[reportPrivateUsage]
)


def native_config(
    binding: Any,
    strategy: PersonalStrategy,
    policy: PersonalExecutionPolicy,
    signal: pd.DataFrame,
    start: str,
    end: str,
    benchmark: str,
) -> dict[str, Any]:
    exchange: dict[str, Any] = {
        "freq": "day",
        "codes": sorted(set(signal.index.get_level_values("instrument")) | {benchmark}),
        "start_time": str(signal.index.get_level_values("datetime").min().date()),
        "end_time": end,
        "deal_price": "$open",
        "trade_unit": policy.trade_unit_shares,
        "open_cost": policy.buy_cost,
        "close_cost": policy.sell_cost,
        "min_cost": policy.minimum_cost_cny,
        "limit_threshold": ("$limit_buy+$is_st", "$limit_sell+$is_st"),
        "volume_threshold": ("current", f"$volume*{policy.volume_participation}"),
    }
    if binding.manifest.kind == "market":
        if binding.snapshot_path is None:
            raise ValueError("canonical open price limit source missing")
        exchange["subscribe_fields"] = ["$is_st"]
        exchange = {
            "exchange": {
                "class": "HS300OpenLimitExchange",
                "module_path": "quantos.research.hs300_exchange",
                "kwargs": {
                    **exchange,
                    "price_limits_path": str(
                        binding.snapshot_path / "canonical/price_limits.parquet"
                    ),
                    "price_limits_sha256": binding.manifest.source_files[
                        "canonical/price_limits.parquet"
                    ],
                },
            }
        }
    return {
        "strategy": {
            "class": "PersonalRuleStrategy",
            "module_path": "quantos.backtest.personal_strategy",
            "kwargs": {"signal": "<PRED>", "specification": strategy.model_dump(mode="json")},
        },
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
        },
        "backtest": {
            "start_time": start,
            "end_time": end,
            "account": policy.initial_cash_cny,
            "benchmark": benchmark,
            "exchange_kwargs": exchange,
        },
    }


def require_supported_market_period(binding: Any, end: str, *, start: str | None = None) -> None:
    """New strategies cannot inherit the legacy arms' zero-exposure proofs."""
    if binding.manifest.kind != "market":
        return
    from datetime import date

    from quantos.research.hs300_lifecycle_data import load_lifecycle_facts

    facts = load_lifecycle_facts(binding.lifecycle_path, binding.manifest.lifecycle_manifest_hash)
    for event in facts.events:
        boundary = event.entitlement_window_start or event.boundary_date
        if date.fromisoformat(end) >= boundary and (
            start is None or event.boundary_date >= date.fromisoformat(start)
        ):
            raise ValueError(
                "UNSUPPORTED_CORPORATE_ACTION: new strategy requires native lifecycle support"
            )


def execute_candidate(
    binding: Any,
    strategy: PersonalStrategy,
    policy: PersonalExecutionPolicy,
    signal: pd.DataFrame,
    start: str,
    end: str,
    benchmark: str,
    destination: Path,
) -> dict[str, Any]:
    """Runtime recorder is temporary authority; immutable exports are the evidence."""
    from quantos.research.native_state import encode_native_state

    require_supported_market_period(binding, end, start=start)
    destination = destination.absolute()
    config = native_config(binding, strategy, policy, signal, start, end, benchmark)
    config["strategy"]["kwargs"]["trace_root"] = str(destination / "targets")
    destination.mkdir(parents=True, exist_ok=True)
    runtime = destination / "runtime"
    runtime.mkdir()
    atomic_write_bytes(destination / "native-config.json", canonical_json_bytes(config))
    cast(Any, qlib).init(provider_uri=str(binding.provider_root), region=REG_CN, kernels=1)
    Record: Any = importlib.import_module("qlib.workflow.record_temp").PortAnaRecord
    exports: dict[str, str] = {}
    with _WORKFLOW_LOCK, _workflow_tracking_runtime(runtime, "frozen-field-study/v1") as uri:  # noqa: SIM117
        with R.start(experiment_name="personal-strategy-v7", uri=uri):
            recorder: Any = cast(Any, R).get_recorder()
            recorder.save_objects(**{"pred.pkl": signal, "label.pkl": None})
            Record(
                recorder, config=config, risk_analysis_freq=[], indicator_analysis_freq=[]
            ).generate()
            _flush_recorder_logs(recorder)
            objects: dict[str, Any] = {}
            for name in (
                "report_normal_1day.pkl",
                "positions_normal_1day.pkl",
                "indicators_normal_1day.pkl",
                "indicators_normal_1day_obj.pkl",
            ):
                value = recorder.load_object(f"portfolio_analysis/{name}")
                objects[name] = value
                path = destination / (name.removesuffix(".pkl") + ".native.json")
                atomic_write_bytes(path, encode_native_state(value))
                exports[path.name] = sha256_file(path)
            recorder_id = str(recorder.id)
    report: Any = objects["report_normal_1day.pkl"]
    orders = _native_order_rows(objects["indicators_normal_1day_obj.pkl"])
    for name, frame in (("portfolio.parquet", report), ("native-orders.parquet", orders)):
        stream = BytesIO()
        frame.to_parquet(stream)
        atomic_write_bytes(destination / name, stream.getvalue())
        exports[name] = sha256_file(destination / name)
    exports["native-config.json"] = sha256_file(destination / "native-config.json")
    for path in regular_tree_files(destination / "targets"):
        exports[path.relative_to(destination).as_posix()] = sha256_file(path)
    return {
        "run_status": "SUCCEEDED",
        "validation_verdict": "NOT_EVALUATED",
        "metrics": _metrics(report, objects["indicators_normal_1day.pkl"]),
        "files": exports,
        "recorder_id": recorder_id,
        "engine": "Qlib-0.9.7",
        "evidence_kind": binding.manifest.kind,
    }
