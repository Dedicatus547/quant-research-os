from __future__ import annotations

import importlib
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quantos.backtest import normalize_qlib_outputs, reconcile_backtest_output
from quantos.backtest.service import translate_backtest_config_schedule_hash
from quantos.contracts.backtest import QlibBacktestConfig
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.research.qlib import QlibResearchError

SHANGHAI = ZoneInfo("Asia/Shanghai")
SERVICE = importlib.import_module("quantos.backtest.service")


class _Metric:
    def __init__(self, values: dict[str, float]) -> None:
        self._values = values

    def to_dict(self) -> dict[str, float]:
        return self._values


class _OrderIndicator:
    def __init__(self, metrics: dict[str, dict[str, float]]) -> None:
        self.data = {name: _Metric(values) for name, values in metrics.items()}


class _IndicatorHistory:
    def __init__(self, history: dict[pd.Timestamp, _OrderIndicator]) -> None:
        self.order_indicator_his = history


class _Position:
    def __init__(self, position: dict[str, object]) -> None:
        self.position = position


def _schedule() -> DecisionSchedule:
    return DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 15, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 15, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 15, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )


def _config() -> QlibBacktestConfig:
    schedule = _schedule()
    return QlibBacktestConfig(
        resolved_experiment_hash="1" * 64,
        signal_artifact_hash="2" * 64,
        snapshot_hash="3" * 64,
        qlib_view_hash="4" * 64,
        qlib_version="0.9.7",
        cost_policy_hash="5" * 64,
        backtest_policy_hash="6" * 64,
        start_date=date(2024, 1, 8),
        end_date=date(2024, 1, 8),
        exchange_start_date=date(2024, 1, 5),
        exchange_codes=("SH600000",),
        signal_dates=(date(2024, 1, 5),),
        execution_dates=(date(2024, 1, 8),),
        decision_schedule_hash=translate_backtest_config_schedule_hash((schedule,)),
        benchmark="SH000300",
        initial_cash_cny=1000.0,
        top_k=1,
        max_weight=0.5,
        open_cost_rate=0.001,
        close_cost_rate=0.002,
        minimum_cost_cny=5.0,
        volume_threshold=("current", "$volume*0.1"),
    )


def _raw_outputs() -> tuple[dict[str, object], dict[str, object]]:
    first = pd.Timestamp("2024-01-08")
    portfolio = pd.DataFrame(
        [
            [995.0, 0.0, 500.0, 0.5, 5.0, 0.005, 500.0, 495.0, 0.001],
        ],
        index=pd.DatetimeIndex([first], name="datetime"),
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
    positions = {
        first: _Position(
            {
                "SH600000": {
                    "amount": 100.0,
                    "price": 5.0,
                    "weight": 500.0 / 995.0,
                },
                "cash": 495.0,
                "now_account_value": 995.0,
            }
        )
    }
    trade_indicators = pd.DataFrame(
        [[1.0, 0.0, 0.0, 100.0, 500.0, 1.0]],
        index=pd.DatetimeIndex([first]),
        columns=["ffr", "pa", "pos", "deal_amount", "value", "count"],
    )
    order_indicator = _OrderIndicator(
        {
            "amount": {"SH600000": 100.0},
            "deal_amount": {"SH600000": 100.0},
            "trade_dir": {"SH600000": 1.0},
            "trade_price": {"SH600000": 5.0},
            "trade_value": {"SH600000": 500.0},
            "trade_cost": {"SH600000": 5.0},
            "ffr": {"SH600000": 1.0},
        }
    )
    return (
        {"1day": (portfolio, positions)},
        {"1day": (trade_indicators, _IndicatorHistory({first: order_indicator}))},
    )


def test_normalizer_uses_qlib_outputs_and_reconciles_six_invariants() -> None:
    raw_portfolio, raw_indicators = _raw_outputs()
    normalized = normalize_qlib_outputs(
        raw_portfolio,  # type: ignore[arg-type]
        raw_indicators,  # type: ignore[arg-type]
        inverse_mappings={"SH600000": "600000.SH"},
        factors={(date(2024, 1, 8), "SH600000"): 1.0},
    )

    assert normalized.order_indicators[0]["trade_direction"] == "BUY"
    assert normalized.order_indicators[0]["dealt_raw_shares"] == 100.0
    assert len(normalized.risk_metrics) == 10
    reconciliation = reconcile_backtest_output(normalized, _config(), (_schedule(),))
    assert [item.name for item in reconciliation.checks] == [
        "asset_identity",
        "cash_nonnegative",
        "position_value_and_weight",
        "return_cost_turnover_deltas",
        "temporal_schedule",
        "trade_unit_and_no_short",
    ]


def test_reconciler_rejects_qlib_accounting_mismatch() -> None:
    raw_portfolio, raw_indicators = _raw_outputs()
    normalized = normalize_qlib_outputs(
        raw_portfolio,  # type: ignore[arg-type]
        raw_indicators,  # type: ignore[arg-type]
        inverse_mappings={"SH600000": "600000.SH"},
        factors={(date(2024, 1, 8), "SH600000"): 1.0},
    )
    corrupted_rows = deepcopy(normalized.portfolio)
    corrupted_rows[0]["account"] = 996.0
    corrupted = normalized.__class__(
        portfolio=corrupted_rows,
        positions=normalized.positions,
        trade_indicators=normalized.trade_indicators,
        order_indicators=normalized.order_indicators,
        risk_metrics=normalized.risk_metrics,
    )

    with pytest.raises(QlibResearchError) as failed:
        reconcile_backtest_output(corrupted, _config(), (_schedule(),))
    assert failed.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED

    unexpected_positions = deepcopy(normalized.positions)
    unexpected_positions[0]["qlib_id"] = "SZ000001"
    unexpected_instrument = normalized.__class__(
        portfolio=normalized.portfolio,
        positions=unexpected_positions,
        trade_indicators=normalized.trade_indicators,
        order_indicators=normalized.order_indicators,
        risk_metrics=normalized.risk_metrics,
    )
    with pytest.raises(QlibResearchError, match="trade_unit_and_no_short"):
        reconcile_backtest_output(unexpected_instrument, _config(), (_schedule(),))


def test_schedule_gate_requires_next_session_and_weekly_final_session(tmp_path: Path) -> None:
    calendar = tmp_path / "calendars"
    calendar.mkdir()
    (calendar / "day.txt").write_text("2024-01-05\n2024-01-08\n2024-01-09\n", encoding="utf-8")
    SERVICE._validate_schedules((_schedule(),), tmp_path)

    skipped_session = _schedule().model_copy(
        update={"execution_time": datetime(2024, 1, 9, 9, 30, tzinfo=SHANGHAI)}
    )
    with pytest.raises(QlibResearchError, match="next Qlib trading session") as skipped:
        SERVICE._validate_schedules((skipped_session,), tmp_path)
    assert skipped.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION

    intraweek = DecisionSchedule(
        signal_time=datetime(2024, 1, 8, 15, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 8, 15, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 8, 15, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 9, 9, 30, tzinfo=SHANGHAI),
    )
    with pytest.raises(QlibResearchError, match="final trading session") as not_weekly_final:
        SERVICE._validate_schedules((intraweek,), tmp_path)
    assert not_weekly_final.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION


def test_signal_mapping_and_output_schema_drift_fail_closed() -> None:
    from quantos.contracts.signal import SignalRow

    schedule = _schedule()
    row = SignalRow(
        instrument_id="600000.SH",
        signal_time=schedule.signal_time,
        decision_time=schedule.decision_time,
        available_at=datetime(2024, 1, 5, 14, 59, tzinfo=SHANGHAI),
        score=1.0,
        tradable=True,
    )
    with pytest.raises(QlibResearchError) as missing_mapping:
        SERVICE._signal_series((row,), {})
    assert missing_mapping.value.reason_code is ReasonCode.SOURCE_INCOMPLETE

    raw_portfolio, raw_indicators = _raw_outputs()
    raw_portfolio["1day"][0]["unexpected"] = 1.0  # type: ignore[index]
    with pytest.raises(QlibResearchError) as schema_drift:
        normalize_qlib_outputs(
            raw_portfolio,  # type: ignore[arg-type]
            raw_indicators,  # type: ignore[arg-type]
            inverse_mappings={"SH600000": "600000.SH"},
            factors={(date(2024, 1, 8), "SH600000"): 1.0},
        )
    assert schema_drift.value.reason_code is ReasonCode.QLIB_EXECUTION_FAILED
