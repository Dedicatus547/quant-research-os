"""Lossless native-state transport with explicit executable-type and size rejection."""

from __future__ import annotations

import copy
import json
from collections import OrderedDict, defaultdict

import numpy as np
import pandas as pd
import pytest

from quantos.research.native_state import MAX_BYTES, decode_native_state, encode_native_state


def native_account():
    from qlib.backtest.account import Account
    from qlib.backtest.decision import Order, OrderDir

    clock = pd.Timestamp("2024-02-01")
    account = Account(init_cash=1000, benchmark_config={"benchmark": None})
    order = Order("SH600001", 100, OrderDir.BUY, clock, clock)
    order.deal_amount = 40  # Native API input exercises a partially filled order's state.
    order.factor = 1.0
    account.update_order(order, 400.0, 0.5, 10.0)
    account.current_position.add_count_all("day")
    account.hist_positions[clock] = copy.deepcopy(account.current_position)
    account.portfolio_metrics.update_portfolio_metrics_record(
        trade_start_time=clock,
        account_value=999.5,
        cash=599.5,
        return_rate=0.0,
        total_turnover=400.0,
        turnover_rate=0.4,
        total_cost=0.5,
        cost_rate=0.0005,
        stock_value=400.0,
        bench_value=0.0,
    )
    account.indicator.update_order_indicators([(order, 400.0, 0.5, 10.0)])
    account.indicator.record(clock)
    return account, order


def test_complete_native_account_report_history_aliases_and_order_roundtrip():
    account, order = native_account()
    value = {
        "account": account,
        "position_alias": account.current_position,
        "accum_alias": account.accum_info,
        "last_execute_result": [(order, 400.0, 0.5, 10.0)],
        "executor_day_state": {"trade_step": 1, "dealt_order_amount": defaultdict(float)},
        "strategy_state": {"held_since": {"SH600001": 0}, "target": {"SH600001": 0.4}},
    }
    raw = encode_native_state(value)
    decoded = decode_native_state(raw)
    restored = decoded["account"]
    assert restored.current_position is decoded["position_alias"]
    assert restored.accum_info is decoded["accum_alias"]
    assert restored.get_cash() == account.get_cash()
    assert restored.current_position.position == account.current_position.position
    assert vars(restored.accum_info) == vars(account.accum_info)
    assert restored.hist_positions.keys() == account.hist_positions.keys()
    assert (
        restored.hist_positions[pd.Timestamp("2024-02-01")].position
        == account.hist_positions[pd.Timestamp("2024-02-01")].position
    )
    pd.testing.assert_frame_equal(
        restored.get_portfolio_metrics()[0], account.get_portfolio_metrics()[0]
    )
    assert (
        restored.indicator.order_indicator_his.keys()
        == account.indicator.order_indicator_his.keys()
    )
    native_metric = restored.indicator.order_indicator_his[pd.Timestamp("2024-02-01")].data[
        "deal_amount"
    ]
    np.testing.assert_array_equal(native_metric.data, [40.0])
    assert native_metric.index.tolist() == ["SH600001"]
    assert decoded["last_execute_result"][0][0].deal_amount == 40.0
    assert decoded["last_execute_result"][0][0].amount == 100
    # Re-encoding precedes defaultdict access, which itself inserts a new native key.
    assert encode_native_state(decoded) == raw
    assert decoded["executor_day_state"]["dealt_order_amount"]["unknown"] == 0.0


def test_pandas_axes_duplicate_columns_and_extension_values():
    index = pd.MultiIndex.from_product(
        [["A", "B"], pd.date_range("2024-01-01", periods=2)], names=["instrument", "datetime"]
    )
    frame = pd.DataFrame(np.arange(8).reshape(4, 2), index=index, columns=["same", "same"])
    timezone_index = pd.date_range("2024-01-01", periods=3, tz="Asia/Shanghai", name="clock")
    values = {
        "frame": frame,
        "benchmark": pd.Series([0.0, np.nan, 0.1], index=timezone_index, name="return"),
        "nullable": pd.Series([1, pd.NA, 3], dtype="Int64"),
        "object_index": pd.Index(["A", "B"], name="code"),
        "range_index": pd.RangeIndex(2, 9, 2, name="n"),
        "stamp": pd.Timestamp("2024-01-01 16:00:00.123456789", tz="Asia/Shanghai"),
    }
    restored = decode_native_state(encode_native_state(values))
    pd.testing.assert_frame_equal(restored["frame"], frame)
    pd.testing.assert_series_equal(restored["benchmark"], values["benchmark"])
    pd.testing.assert_series_equal(restored["nullable"], values["nullable"])
    pd.testing.assert_index_equal(restored["object_index"], values["object_index"])
    pd.testing.assert_index_equal(restored["range_index"], values["range_index"])
    assert restored["stamp"] == values["stamp"]
    assert str(restored["stamp"].tz) == "Asia/Shanghai"


def test_numpy_dtypes_missing_values_collections_and_mutable_cycles():
    original = {
        "array": np.array([[1.0, np.nan], [np.inf, -np.inf]], dtype=np.float32),
        "date_array": np.array(["2024-01-01", "NaT"], dtype="datetime64[ns]"),
        "string_array": np.array(["沪深", "A"], dtype="U4"),
        "object_array": np.array([None, pd.NA, pd.NaT, pd.Timestamp("2024-01-01")], dtype=object),
        "scalars": [np.float32(1.25), np.int64(4), np.str_("A"), np.datetime64("2024-01-01")],
        "nonfinite": (float("nan"), float("inf"), float("-inf")),
        "ordered": OrderedDict([(pd.Timestamp("2024-01-01"), 1)]),
        "set": {"B", "A"},
    }
    original["self"] = original
    restored = decode_native_state(encode_native_state(original))
    assert restored["self"] is restored
    for key in ("array", "date_array", "string_array"):
        np.testing.assert_array_equal(restored[key], original[key])
        assert restored[key].dtype == original[key].dtype
    assert restored["object_array"][1] is pd.NA
    assert restored["object_array"][2] is pd.NaT
    assert [type(v) for v in restored["scalars"]] == [type(v) for v in original["scalars"]]
    assert restored["set"] == {"A", "B"}
    assert np.isnan(restored["nonfinite"][0])
    assert restored["nonfinite"][1:] == (np.inf, -np.inf)


def test_unknown_classes_and_callable_factories_reject_without_reducers():
    class Unsafe:
        def __reduce__(self):
            raise AssertionError("Reducer must never run")

    with pytest.raises(ValueError, match="unsupported native state type"):
        encode_native_state(Unsafe())
    with pytest.raises(ValueError, match="factory"):
        encode_native_state(defaultdict(lambda: 0))
    with pytest.raises(ValueError):
        decode_native_state(b"\x80\x04pickle-is-not-json")


def mutate(raw, transform):
    payload = json.loads(raw)
    transform(payload)
    return json.dumps(payload).encode()


def test_class_names_and_state_fields_are_allowlisted():
    account, _ = native_account()
    raw = encode_native_state(account)
    with pytest.raises(ValueError, match="allowlist"):
        decode_native_state(mutate(raw, lambda p: p["nodes"][0].update(name="os.system")))
    payload = json.loads(raw)
    state_node = payload["nodes"][payload["nodes"][0]["state"]["ref"]]
    state_node["items"].append(["__reduce__", None])
    with pytest.raises(ValueError, match="state fields"):
        decode_native_state(json.dumps(payload).encode())
    with pytest.raises(ValueError, match="runtime"):
        decode_native_state(mutate(raw, lambda p: p["runtime"].update(pyqlib="9.9.9")))


def test_allocation_depth_and_integrity_bounds():
    raw = encode_native_state(np.ones(2))
    with pytest.raises(ValueError, match=r"dimension|allocation"):
        decode_native_state(mutate(raw, lambda p: p["nodes"][0].update(shape=[10**9])))
    with pytest.raises(ValueError, match="byte count"):
        decode_native_state(mutate(raw, lambda p: p["nodes"][0].update(shape=[3])))
    with pytest.raises(ValueError, match="dtype"):
        decode_native_state(mutate(raw, lambda p: p["nodes"][0].update(dtype="V16")))
    with pytest.raises(ValueError, match="fields"):
        decode_native_state(mutate(raw, lambda p: p["nodes"][0].update(ignored="extra")))
    with pytest.raises(ValueError, match="32 MiB"):
        decode_native_state(b" " * (MAX_BYTES + 1))
    nested = None
    for _ in range(130):
        nested = [nested]
    with pytest.raises(ValueError, match="depth"):
        encode_native_state(nested)
    bad_ref = json.loads(encode_native_state([1]))
    bad_ref["root"]["ref"] = -1
    with pytest.raises(ValueError, match="reference"):
        decode_native_state(json.dumps(bad_ref).encode())
    with pytest.raises(ValueError, match="duplicate"):
        decode_native_state(b'{"root":0,"root":1}')


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_timestamp_native_resolution_survives_order_and_index_keys(unit):
    from qlib.backtest.decision import Order, OrderDir

    stamp = pd.Timestamp("2024-02-01 09:30:00", tz="Asia/Shanghai").as_unit(unit)
    order = Order("SH600001", 100, OrderDir.BUY, stamp, stamp)
    restored = decode_native_state(encode_native_state({"order": order, "history": {stamp: 1}}))
    assert restored["order"].start_time.unit == unit
    assert restored["order"].end_time.unit == unit
    assert next(iter(restored["history"])).unit == unit
    assert restored["order"].start_time == stamp
