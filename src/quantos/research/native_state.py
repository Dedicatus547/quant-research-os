"""Bounded, non-executable JSON state for fixed Qlib 0.9.7 native objects.

This is a serialization boundary, not account reconstruction or accounting. The
caller must authenticate the local checkpoint and its dependencies before use.
No pickle, dynamic imports, user classes, reducers or native state hooks run.
Native objects are restored without invoking their constructors.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import Any, cast

import numpy as np
import pandas as pd

MAX_BYTES = 32 * 1024**2
MAX_NODES = 200_000
MAX_DEPTH = 128
MAX_ARRAY_ELEMENTS = 2_000_000
SCHEMA = "qlib-native-state-json/v1"


def _classes() -> dict[str, type[Any]]:
    # Deliberately fixed imports. Serialized names never select modules or classes.
    from qlib.backtest.account import (  # pyright: ignore[reportMissingTypeStubs]
        Account,
        AccumulatedInfo,
    )
    from qlib.backtest.decision import Order  # pyright: ignore[reportMissingTypeStubs]
    from qlib.backtest.high_performance_ds import (  # pyright: ignore[reportMissingTypeStubs]
        NumpyOrderIndicator,
        PandasOrderIndicator,
        PandasSingleMetric,
        SingleMetric,
    )
    from qlib.backtest.position import Position  # pyright: ignore[reportMissingTypeStubs]
    from qlib.backtest.report import (  # pyright: ignore[reportMissingTypeStubs]
        Indicator,
        PortfolioMetrics,
    )
    from qlib.backtest.utils import TradeCalendarManager  # pyright: ignore[reportMissingTypeStubs]
    from qlib.log import QlibLogger  # pyright: ignore[reportMissingTypeStubs]
    from qlib.utils.index_data import (  # pyright: ignore[reportMissingTypeStubs]
        Index,
        MultiData,
        SingleData,
    )

    return {
        cls.__module__ + "." + cls.__name__: cls
        for cls in (
            Account,
            AccumulatedInfo,
            Order,
            Position,
            PortfolioMetrics,
            Indicator,
            NumpyOrderIndicator,
            PandasOrderIndicator,
            PandasSingleMetric,
            SingleMetric,
            SingleData,
            MultiData,
            Index,
            TradeCalendarManager,
            QlibLogger,
        )
    }


_FIELDS = {
    "Account": (
        "_pos_type _port_metr_enabled benchmark_config init_cash current_position "
        "accum_info portfolio_metrics hist_positions freq indicator"
    ),
    "AccumulatedInfo": "rtn cost to",
    "Order": "stock_id amount direction start_time end_time deal_amount factor",
    "Position": "_settle_type position init_cash",
    "PortfolioMetrics": (
        "accounts returns total_turnovers turnovers total_costs costs "
        "values cashes benches latest_pm_time freq benchmark_config bench"
    ),
    "Indicator": (
        "order_indicator_cls order_indicator_his order_indicator "
        "trade_indicator_his trade_indicator _trade_calendar"
    ),
    "NumpyOrderIndicator": "data logger",
    "PandasOrderIndicator": "data logger",
    "PandasSingleMetric": "metric",
    "SingleMetric": "metric",
    "SingleData": "data indices ndim",
    "MultiData": "data indices ndim",
    "Index": "idx_list index_map _is_sorted",
    "TradeCalendarManager": (
        "level_infra freq start_time end_time _calendar start_index end_index trade_len trade_step"
    ),
    "QlibLogger": "module_name _QlibLogger__level",
}
_FACTORIES: dict[str, Any] = {
    "none": None,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
}


_NODE_FIELDS = {
    "dict": "type items",
    "ordered_dict": "type items",
    "default_dict": "type items factory",
    "list": "type items",
    "tuple": "type items",
    "set": "type items",
    "frozenset": "type items",
    "timestamp": "type value timezone unit",
    "pandas_timedelta": "type value",
    "datetime": "type value fold",
    "date": "type value",
    "timedelta": "type days seconds microseconds",
    "ndarray": "type dtype shape",
    "numpy_scalar": "type dtype shape",
    "range_index": "type start stop step name",
    "multi_index": "type levels codes names sortorder",
    "datetime_index": "type data unit timezone name freq",
    "index": "type data name dtype",
    "series": "type data index name dtype",
    "dataframe": "type index columns data",
    "native": "type name state",
}


def _set_key(item: Any, depth: int = 0) -> bytes:
    if depth > MAX_DEPTH:
        raise ValueError("native set nesting exceeds depth bound")
    cls: type[Any] = cast(type[Any], type(item))
    if item is None or cls in (str, int, float, bool):
        return _json_bytes([cls.__name__, repr(item)])
    if cls in (pd.Timestamp, datetime, date):
        return _json_bytes([cls.__name__, item.isoformat()])
    if cls is tuple:
        return _json_bytes(["tuple", [_set_key(v, depth + 1).decode() for v in item]])
    raise ValueError("unsupported native set member type")


def _runtime() -> dict[str, str]:
    qlib_version = version("pyqlib")
    if qlib_version != "0.9.7":
        raise ValueError("native state supports fixed Qlib 0.9.7 only")
    return {"pyqlib": qlib_version, "pandas": pd.__version__, "numpy": np.__version__}


def _shape(value: Any, itemsize: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(cast(list[Any], value)) > 8:
        raise ValueError("native ndarray shape exceeds bounds")
    dimensions = cast(list[Any], value)
    if any(type(n) is not int or n < 0 or n > MAX_ARRAY_ELEMENTS for n in dimensions):
        raise ValueError("native ndarray dimension exceeds bounds")
    count = math.prod(dimensions)
    if count > MAX_ARRAY_ELEMENTS or count * itemsize > MAX_BYTES:
        raise ValueError("native ndarray allocation exceeds bounds")
    return tuple(dimensions)


def _dtype(value: Any) -> np.dtype[Any]:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid native ndarray dtype")
    if re.fullmatch(r"[<>=|]?[biufcmMOSUV][0-9]*(?:\[(?:ns|us|ms|s|m|h|D)\])?", value) is None:
        raise ValueError("unsupported native ndarray dtype")
    dtype = np.dtype(value)
    if dtype.fields is not None or dtype.kind not in "biufcmMOSU" or dtype.itemsize > 65536:
        raise ValueError("unsupported native ndarray dtype")
    return dtype


def _pandas_dtype(value: Any) -> Any:
    if value in {"Int64", "Int32", "Float64", "Float32", "boolean", "string"}:
        return value
    if isinstance(value, str) and re.fullmatch(
        r"datetime64\[(?:ns|us|ms|s), [A-Za-z0-9_+/:-]{1,64}\]", value
    ):
        return value
    if isinstance(value, str) and re.fullmatch(
        r"bool|object|(?:u?int|float|complex)(?:8|16|32|64|128)|(?:datetime64|timedelta64)\[(?:ns|us|ms|s|m|h|D)\]",
        value,
    ):
        return _dtype(np.dtype(value).str)
    return _dtype(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def encode_native_state(value: Any) -> bytes:
    """Encode native state and shared references; reject unsupported object graphs."""
    runtime = _runtime()
    classes = _classes()
    reverse = {cls: name for name, cls in classes.items()}
    from qlib.backtest.decision import OrderDir  # pyright: ignore[reportMissingTypeStubs]

    nodes: list[dict[str, Any]] = []
    memo: dict[int, int] = {}
    retained_objects: list[Any] = []
    seen = 0

    def encode(item: Any, depth: int = 0) -> Any:
        nonlocal seen
        seen += 1
        if seen > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("native state graph exceeds node/depth bounds")
        cls: type[Any] = cast(type[Any], type(item))
        if item is None or cls in (str, bool, int):
            if cls is str and len(cast(str, item)) > MAX_BYTES:
                raise ValueError("native string exceeds byte bound")
            if cls is int and cast(int, item).bit_length() > 256:
                raise ValueError("native integer exceeds bound")
            return item
        if cls is float:
            return (
                item
                if math.isfinite(item)
                else {"special_float": "nan" if math.isnan(item) else "inf" if item > 0 else "-inf"}
            )
        if item is pd.NaT:
            return {"special": "nat"}
        if item is pd.NA:
            return {"special": "na"}
        if cls is OrderDir:
            return {"order_direction": int(item)}
        if cls is type and item in reverse:
            return {"native_class": reverse[item]}
        if id(item) in memo:
            return {"ref": memo[id(item)]}
        node_id = len(nodes)
        memo[id(item)] = node_id
        retained_objects.append(item)
        node: dict[str, Any] = {}
        nodes.append(node)

        def descend(child: Any) -> Any:
            return encode(child, depth + 1)

        if cls in (dict, OrderedDict, defaultdict):
            node["type"] = (
                "dict" if cls is dict else "ordered_dict" if cls is OrderedDict else "default_dict"
            )
            if cls is defaultdict:
                factory = next(
                    (key for key, val in _FACTORIES.items() if item.default_factory is val), None
                )
                if factory is None:
                    raise ValueError("unsupported native defaultdict factory")
                node["factory"] = factory
            node["items"] = [[descend(key), descend(child)] for key, child in item.items()]
        elif cls in (list, tuple, set, frozenset):
            node["type"] = cls.__name__
            members = sorted(item, key=_set_key) if cls in (set, frozenset) else item
            node["items"] = [descend(child) for child in members]
        elif cls is pd.Timestamp:
            node.update(
                type="timestamp",
                value=int(item.asm8.view("i8")),
                timezone=str(item.tz) if item.tz is not None else None,
                unit=item.unit,
            )
        elif cls is pd.Timedelta:
            node.update(type="pandas_timedelta", value=item.value)
        elif cls is datetime:
            node.update(type="datetime", value=item.isoformat(), fold=item.fold)
        elif cls is date:
            node.update(type="date", value=item.isoformat())
        elif cls is timedelta:
            node.update(
                type="timedelta",
                days=item.days,
                seconds=item.seconds,
                microseconds=item.microseconds,
            )
        elif cls is np.ndarray or isinstance(item, np.generic):
            array: Any = cast(Any, item) if cls is np.ndarray else np.asarray(cast(Any, item))
            dtype = _dtype(array.dtype.str)
            _shape(list(array.shape), dtype.itemsize)
            node.update(
                type="ndarray" if cls is np.ndarray else "numpy_scalar",
                dtype=array.dtype.str,
                shape=list(array.shape),
            )
            if dtype.hasobject:
                node["items"] = [descend(child) for child in array.flat]
            else:
                node["data"] = base64.b64encode(array.tobytes(order="C")).decode("ascii")
        elif cls is pd.RangeIndex:
            node.update(
                type="range_index",
                start=item.start,
                stop=item.stop,
                step=item.step,
                name=descend(item.name),
            )
        elif cls is pd.MultiIndex:
            node.update(
                type="multi_index",
                levels=[descend(level) for level in item.levels],
                codes=[descend(np.asarray(code)) for code in item.codes],
                names=descend(list(item.names)),
                sortorder=item.sortorder,
            )
        elif cls is pd.DatetimeIndex:
            node.update(
                type="datetime_index",
                data=descend(item.asi8),
                unit=item.unit,
                timezone=str(item.tz) if item.tz is not None else None,
                name=descend(item.name),
                freq=item.freqstr,
            )
        elif cls is pd.Index:
            node.update(
                type="index",
                data=descend(item.to_numpy()),
                name=descend(item.name),
                dtype=item.dtype.str,
            )
        elif cls is pd.Series:
            _pandas_dtype(str(item.dtype))
            node.update(
                type="series",
                data=descend(item.to_numpy()),
                index=descend(item.index),
                name=descend(item.name),
                dtype=str(item.dtype),
            )
        elif cls is pd.DataFrame:
            node.update(
                type="dataframe",
                index=descend(item.index),
                columns=descend(item.columns),
                data=[descend(item.iloc[:, i]) for i in range(len(item.columns))],
            )
        elif cls in reverse:
            state = cast(dict[str, Any], object.__getattribute__(item, "__dict__"))
            if set(state) != set(_FIELDS[cls.__name__].split()):
                raise ValueError("native class state fields differ from fixed Qlib version")
            node.update(type="native", name=reverse[cls], state=descend(state))
        else:
            raise ValueError(
                "unsupported native state type: " + cls.__module__ + "." + cls.__name__
            )
        return {"ref": node_id}

    root = encode(value)
    raw = _json_bytes({"schema_version": SCHEMA, "runtime": runtime, "root": root, "nodes": nodes})
    if len(raw) > MAX_BYTES:
        raise ValueError("native state exceeds 32 MiB byte bound")
    return raw


def decode_native_state(raw: bytes) -> Any:
    """Decode only fixed native classes and bounded data, never executable inputs."""
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError("native state exceeds 32 MiB byte bound")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, val in items:
            if key in result:
                raise ValueError("duplicate native JSON field")
            result[key] = val
        return result

    def invalid_constant(_: str) -> Any:
        raise ValueError("nonfinite native JSON literal")

    try:
        envelope = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("invalid native state JSON") from error
    if not isinstance(envelope, dict):
        raise ValueError("native state envelope must be an object")
    payload = cast(dict[str, Any], envelope)
    if (
        set(payload) != {"schema_version", "runtime", "root", "nodes"}
        or payload["schema_version"] != SCHEMA
        or payload["runtime"] != _runtime()
    ):
        raise ValueError("native state schema or runtime identity differs")
    raw_nodes = payload["nodes"]
    if not isinstance(raw_nodes, list) or len(cast(list[Any], raw_nodes)) > MAX_NODES:
        raise ValueError("native state node count exceeds bounds")
    nodes = cast(list[Any], raw_nodes)
    classes = _classes()
    from qlib.backtest.decision import OrderDir  # pyright: ignore[reportMissingTypeStubs]

    decoded: dict[int, Any] = {}
    active: set[int] = set()
    seen = 0

    def decode(item: Any, depth: int = 0) -> Any:
        nonlocal seen
        seen += 1
        if seen > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("native state graph exceeds node/depth bounds")
        if item is None or type(item) in (str, bool, int, float):
            if type(item) is int and item.bit_length() > 256:
                raise ValueError("native integer exceeds bound")
            if type(item) is float and not math.isfinite(item):
                raise ValueError("nonfinite native literal must use an explicit tag")
            return item
        if not isinstance(item, dict) or len(cast(dict[str, Any], item)) != 1:
            raise ValueError("invalid native state reference")
        reference = cast(dict[str, Any], item)
        if "special_float" in reference:
            if reference["special_float"] not in {"nan", "inf", "-inf"}:
                raise ValueError("invalid native special float")
            return float(reference["special_float"])
        if "special" in reference:
            if reference["special"] not in {"nat", "na"}:
                raise ValueError("invalid native missing scalar")
            return pd.NaT if reference["special"] == "nat" else pd.NA
        if "order_direction" in reference:
            return OrderDir(reference["order_direction"])
        if "native_class" in reference:
            if reference["native_class"] not in classes:
                raise ValueError("native class is outside fixed allowlist")
            return classes[reference["native_class"]]
        number = reference.get("ref")
        if type(number) is not int or not 0 <= number < len(nodes):
            raise ValueError("native state reference escapes node table")
        if number in decoded:
            return decoded[number]
        if number in active:
            raise ValueError("unsupported circular immutable native value")
        active.add(number)
        raw_node = nodes[number]
        if not isinstance(raw_node, dict) or "type" not in raw_node:
            raise ValueError("invalid native node")
        node = cast(dict[str, Any], raw_node)
        kind = node["type"]
        if not isinstance(kind, str) or kind not in _NODE_FIELDS:
            raise ValueError("unknown native state node type")
        expected = set(_NODE_FIELDS[kind].split())
        if kind in {"ndarray", "numpy_scalar"}:
            expected.add("items" if _dtype(node.get("dtype")).hasobject else "data")
        # Earlier v1 engineering artifacts represented Timestamp as epoch ns.
        # Retain that reader; absence of unit cannot prove an original finer identity.
        if kind == "timestamp" and "unit" not in node:
            expected.remove("unit")
        if set(node) != expected:
            raise ValueError("native node fields differ from fixed schema")

        def descend(child: Any) -> Any:
            return decode(child, depth + 1)

        if kind in {"dict", "ordered_dict", "default_dict"}:
            if kind == "default_dict":
                if node.get("factory") not in _FACTORIES:
                    raise ValueError("unsupported native defaultdict factory")
                result: Any = defaultdict[Any, Any](_FACTORIES[node["factory"]])
            else:
                result = {} if kind == "dict" else OrderedDict[Any, Any]()
            decoded[number] = result
            for key, child in node["items"]:
                actual_key = descend(key)
                if actual_key in result:
                    raise ValueError("duplicate native dictionary key")
                result[actual_key] = descend(child)
        elif kind == "list":
            result = []
            decoded[number] = result
            result.extend(descend(child) for child in node["items"])
        elif kind in {"tuple", "set", "frozenset"}:
            children = [descend(child) for child in node["items"]]
            result = (
                tuple(children)
                if kind == "tuple"
                else set(children)
                if kind == "set"
                else frozenset(children)
            )
        elif kind == "timestamp":
            unit = node.get("unit", "ns")
            if unit not in {"s", "ms", "us", "ns"}:
                raise ValueError("unsupported native Timestamp unit")
            result = pd.Timestamp(
                node["value"], unit=unit, tz="UTC" if node["timezone"] is not None else None
            ).as_unit(unit)
            if node["timezone"] is not None:
                result = result.tz_convert(node["timezone"])
        elif kind == "pandas_timedelta":
            result = pd.Timedelta(node["value"], unit="ns")
        elif kind == "datetime":
            result = datetime.fromisoformat(node["value"]).replace(fold=node["fold"])
        elif kind == "date":
            result = date.fromisoformat(node["value"])
        elif kind == "timedelta":
            result = timedelta(
                days=node["days"], seconds=node["seconds"], microseconds=node["microseconds"]
            )
        elif kind in {"ndarray", "numpy_scalar"}:
            dtype = _dtype(node["dtype"])
            shape = _shape(node["shape"], dtype.itemsize)
            count = math.prod(shape)
            if dtype.hasobject:
                if len(node["items"]) != count:
                    raise ValueError("native object ndarray length disagrees")
                result = np.empty(shape, dtype=object)
                for i, child in enumerate(node["items"]):
                    result.flat[i] = descend(child)
            else:
                try:
                    binary = base64.b64decode(node["data"], validate=True)
                except (ValueError, binascii.Error) as error:
                    raise ValueError("invalid native ndarray bytes") from error
                if len(binary) != count * dtype.itemsize:
                    raise ValueError("native ndarray byte count disagrees")
                result = np.frombuffer(binary, dtype=dtype).reshape(shape).copy()
            if kind == "numpy_scalar":
                if shape:
                    raise ValueError("native scalar has non-scalar shape")
                result = result[()]
        elif kind == "range_index":
            start, stop, step = node["start"], node["stop"], node["step"]
            if (
                any(type(v) is not int for v in (start, stop, step))
                or step == 0
                or len(range(start, stop, step)) > MAX_ARRAY_ELEMENTS
            ):
                raise ValueError("native range index exceeds bounds")
            result = pd.RangeIndex(start=start, stop=stop, step=step, name=descend(node["name"]))
        elif kind == "multi_index":
            result = pd.MultiIndex(
                levels=[descend(v) for v in node["levels"]],
                codes=[descend(v) for v in node["codes"]],
                names=descend(node["names"]),
                sortorder=node["sortorder"],
                verify_integrity=True,
            )
        elif kind == "datetime_index":
            if node["unit"] not in {"ns", "us", "ms", "s"}:
                raise ValueError("unsupported native datetime unit")
            array = descend(node["data"])
            if type(array) is not np.ndarray or array.ndim != 1 or array.dtype.kind != "i":
                raise ValueError("native datetime index requires integer epoch values")
            result = pd.DatetimeIndex(
                cast(
                    Any, pd.to_datetime(array, unit=node["unit"], utc=node["timezone"] is not None)
                ),
                name=descend(node["name"]),
                freq=node["freq"],
            )
            if node["timezone"] is not None:
                result = result.tz_convert(node["timezone"])
        elif kind == "index":
            result = pd.Index(
                descend(node["data"]), name=descend(node["name"]), dtype=_dtype(node["dtype"])
            )
        elif kind == "series":
            result = pd.Series(
                descend(node["data"]),
                index=descend(node["index"]),
                name=descend(node["name"]),
                dtype=_pandas_dtype(node["dtype"]),
            )
        elif kind == "dataframe":
            columns = descend(node["columns"])
            index = descend(node["index"])
            series = [descend(child) for child in node["data"]]
            if len(series) != len(columns):
                raise ValueError("native frame column count disagrees")
            if len(series) * len(index) > MAX_ARRAY_ELEMENTS or any(
                not child.index.equals(index) for child in series
            ):
                raise ValueError("native frame allocation or indexes disagree")
            result = pd.concat(series, axis=1) if series else pd.DataFrame(index=index)
            result.index = index
            result.columns = columns
        elif kind == "native":
            name = node.get("name")
            if not isinstance(name, str):
                raise ValueError("invalid native class name")
            cls = classes.get(name)
            if cls is None:
                raise ValueError("native class is outside fixed allowlist")
            result = object.__new__(cls)
            decoded[number] = result
            state = descend(node["state"])
            if type(state) is not dict or set(cast(dict[str, Any], state)) != set(
                _FIELDS[cls.__name__].split()
            ):
                raise ValueError("native class state fields differ from fixed Qlib version")
            if cls.__name__ == "Indicator" and state["order_indicator_cls"] not in {
                classes["qlib.backtest.high_performance_ds.NumpyOrderIndicator"],
                classes["qlib.backtest.high_performance_ds.PandasOrderIndicator"],
            }:
                raise ValueError("native indicator factory is outside fixed allowlist")
            object.__getattribute__(result, "__dict__").update(state)
        else:
            raise ValueError("unknown native state node type")
        decoded[number] = result
        active.remove(number)
        return result

    try:
        result = decode(payload["root"])
    except (KeyError, TypeError, OverflowError, IndexError, RecursionError) as error:
        raise ValueError("malformed native state graph") from error
    if len(decoded) != len(nodes):
        raise ValueError("native state contains unreachable nodes")
    return result
