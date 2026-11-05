"""Malformed native outputs are execution failures, never zero-return observations."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from test_backtest_service import _raw_outputs

from quantos.backtest import service as backtest
from quantos.contracts.status import ReasonCode
from quantos.research.qlib import QlibResearchError


@pytest.mark.parametrize("value", [None, "not-a-number", float("inf"), float("nan"), object()])
def test_invalid_required_metrics_fail_and_optional_metrics_remain_missing(value):
    with pytest.raises(QlibResearchError) as error:
        backtest._finite_float(value)
    assert error.value.reason_code == ReasonCode.QLIB_EXECUTION_FAILED
    assert backtest._finite_float(value, nullable=True) is None
    assert backtest._finite_float(SimpleNamespace(metric=1.5)) == 1.5


@pytest.mark.parametrize("attack", ["shape", "unmapped", "fields", "factor"])
def test_position_export_requires_native_shape_mapping_and_asof_factor(attack):
    value = SimpleNamespace(position={"SH600000": {"amount": 100, "price": 5, "weight": 0.5}})
    mappings = {"SH600000": "600000.SH"}
    factors = {"SH600000": ((date(2024, 1, 5),), (1.0,))}
    if attack == "shape":
        value.position = None
    elif attack == "unmapped":
        mappings = {}
    elif attack == "fields":
        value.position["SH600000"] = []
    else:
        factors = {}
    with pytest.raises(QlibResearchError, match=r"(unknown shape|mapped canonically|incomplete)"):
        backtest._normalize_positions({pd.Timestamp("2024-01-08"): value}, mappings, factors)


@pytest.mark.parametrize(
    "attack", ["history", "data", "converter", "mapping", "required", "instrument", "factor"]
)
def test_order_export_cannot_substitute_unknown_fields_or_units(attack):
    def metric(value):
        return SimpleNamespace(to_dict=lambda: {"sh600000": value})

    data = {"amount": metric(100), "deal_amount": metric(40), "trade_dir": metric(1)}
    order = SimpleNamespace(data=data)
    history = SimpleNamespace(order_indicator_his={pd.Timestamp("2024-01-08"): order})
    mappings = {"SH600000": "600000.SH"}
    factors = {(date(2024, 1, 8), "SH600000"): 1.0}
    if attack == "history":
        history.order_indicator_his = None
    elif attack == "data":
        order.data = None
    elif attack == "converter":
        data["amount"] = None
    elif attack == "mapping":
        data["amount"] = SimpleNamespace(to_dict=lambda: [])
    elif attack == "required":
        data.pop("trade_dir")
    elif attack == "instrument":
        mappings = {}
    else:
        factors = {}
    with pytest.raises(QlibResearchError):
        backtest._normalize_order_indicators(history, mappings, factors)


@pytest.mark.parametrize("shape", [None, "columns", "empty"])
def test_native_risk_interface_changes_are_not_accepted_as_zero_metrics(monkeypatch, shape):
    report = pd.DataFrame({"return": [0.1], "bench": [0.0], "cost": [0.01]})
    analysis = (
        None if shape is None else pd.DataFrame({"changed" if shape == "columns" else "risk": []})
    )
    monkeypatch.setattr(backtest, "_QLIB_RISK_ANALYSIS", lambda *args, **kwargs: analysis)
    with pytest.raises(QlibResearchError, match="Qlib risk analysis"):
        backtest._normalize_risk_metrics(report)


@pytest.mark.parametrize("attack", ["empty", "duplicate", "column", "frequency", "indicator"])
def test_native_daily_report_schema_is_frozen(attack):
    portfolio, indicators = _raw_outputs()
    report, positions = portfolio["1day"]
    if attack == "empty":
        portfolio["1day"] = report.iloc[:0], positions
    elif attack == "duplicate":
        portfolio["1day"] = pd.concat([report, report]), positions
    elif attack == "column":
        portfolio["1day"] = report.drop(columns="cash"), positions
    elif attack == "frequency":
        portfolio["day"] = portfolio.pop("1day")
    else:
        frame, history = indicators["1day"]
        indicators["1day"] = frame.drop(columns="ffr"), history
    with pytest.raises(QlibResearchError):
        backtest.normalize_qlib_outputs(
            portfolio,
            indicators,
            inverse_mappings={"SH600000": "600000.SH"},
            factors={(date(2024, 1, 8), "SH600000"): 1.0},
        )
