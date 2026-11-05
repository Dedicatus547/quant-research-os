"""Malformed checkpoint graphs must fail before native account restoration."""

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quantos.research import native_state as codec


def encoded(root, nodes=()):
    envelope = json.loads(codec.encode_native_state(None))
    envelope.update(root=root, nodes=list(nodes))
    return json.dumps(envelope).encode()


@pytest.mark.parametrize(
    "root,nodes,message",
    [
        (2**257, [], "integer exceeds"),
        ([], [], "invalid native state reference"),
        ({"special_float": "infinity"}, [], "special float"),
        ({"special": "missing"}, [], "missing scalar"),
        ({"native_class": "os.system"}, [], "allowlist"),
        ({"ref": True}, [{}], "escapes node table"),
        ({"ref": -1}, [{}], "escapes node table"),
        ({"ref": 1}, [{}], "escapes node table"),
        ({"ref": 0}, [[]], "invalid native node"),
        ({"ref": 0}, [{"type": "code"}], "unknown native state node"),
        ({"ref": 0}, [{"type": "tuple", "items": [{"ref": 0}]}], "circular immutable"),
        (
            {"ref": 0},
            [{"type": "dict", "items": [["x", 1], ["x", 2]]}],
            "duplicate native dictionary",
        ),
        ({"ref": 0}, [{"type": "default_dict", "factory": "os.system", "items": []}], "factory"),
        (
            {"ref": 0},
            [{"type": "timestamp", "value": 0, "unit": "D", "timezone": None}],
            "Timestamp unit",
        ),
        (
            {"ref": 0},
            [{"type": "ndarray", "dtype": "|O", "shape": [2], "items": [1]}],
            "object ndarray length",
        ),
        (
            {"ref": 0},
            [{"type": "ndarray", "dtype": "<f8", "shape": [1], "data": "!"}],
            "ndarray bytes",
        ),
        (
            {"ref": 0},
            [{"type": "numpy_scalar", "dtype": "|i1", "shape": [1], "data": "AA=="}],
            "non-scalar shape",
        ),
        (
            {"ref": 0},
            [{"type": "range_index", "start": 0, "stop": 2, "step": 0, "name": None}],
            "range index",
        ),
        (
            {"ref": 0},
            [
                {
                    "type": "datetime_index",
                    "data": None,
                    "unit": "D",
                    "timezone": None,
                    "name": None,
                    "freq": None,
                }
            ],
            "datetime unit",
        ),
        (
            {"ref": 0},
            [
                {
                    "type": "datetime_index",
                    "data": None,
                    "unit": "ns",
                    "timezone": None,
                    "name": None,
                    "freq": None,
                }
            ],
            "integer epoch",
        ),
        ({"ref": 0}, [{"type": "native", "name": None, "state": None}], "class name"),
        (None, [{"type": "list", "items": []}], "unreachable nodes"),
    ],
)
def test_malformed_checkpoint_nodes_are_rejected(root, nodes, message):
    with pytest.raises(ValueError, match=message):
        codec.decode_native_state(encoded(root, nodes))


@pytest.mark.parametrize(
    "raw,message",
    [
        (b"[]", "envelope"),
        (b"NaN", "nonfinite native JSON"),
        (b'{"x":1,"x":2}', "duplicate native JSON"),
    ],
)
def test_json_envelope_cannot_smuggle_nonfinite_or_duplicate_values(raw, message):
    with pytest.raises(ValueError, match=message):
        codec.decode_native_state(raw)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("shape", None, "shape exceeds"),
        ("shape", [1] * 9, "shape exceeds"),
        ("dtype", None, "invalid native ndarray dtype"),
        ("dtype", "|U100000", "unsupported native ndarray dtype"),
        ("shape", [100000, 100000], "allocation exceeds"),
    ],
)
def test_array_metadata_is_bounded_before_allocation(field, value, message):
    envelope = json.loads(codec.encode_native_state(np.zeros(1)))
    envelope["nodes"][0][field] = value
    with pytest.raises(ValueError, match=message):
        codec.decode_native_state(json.dumps(envelope).encode())


def test_temporal_and_nested_set_values_preserve_types_and_determinism():
    values = {
        "date": date(2024, 1, 1),
        "time": datetime(2024, 1, 1, fold=1),
        "delta": timedelta(days=1, seconds=3),
        "pandas_delta": pd.Timedelta(3, unit="ns"),
        "set": {date(2024, 1, 1), ("x", 1)},
        "frozen": frozenset({1, 2}),
    }
    raw = codec.encode_native_state(values)
    restored = codec.decode_native_state(raw)
    assert restored == values and restored["time"].fold == 1
    assert codec.encode_native_state(restored) == raw
    with pytest.raises(ValueError, match="set member"):
        codec.encode_native_state({frozenset({1})})


def test_checkpoint_graph_depth_and_node_limits_apply_to_decode(monkeypatch):
    raw = codec.encode_native_state([[[[1]]]])
    monkeypatch.setattr(codec, "MAX_DEPTH", 2)
    with pytest.raises(ValueError, match="node/depth"):
        codec.decode_native_state(raw)
    monkeypatch.setattr(codec, "MAX_NODES", 2)
    with pytest.raises(ValueError, match="node count"):
        codec.decode_native_state(raw)


@pytest.mark.parametrize("attack", ["column_count", "index"])
def test_frame_columns_and_index_cannot_be_relabelled_by_checkpoint(attack):
    raw = json.loads(codec.encode_native_state(pd.DataFrame({"value": [1, 2]})))
    frame = raw["nodes"][0]
    if attack == "column_count":
        frame["data"] = []
    else:
        series = raw["nodes"][frame["data"][0]["ref"]]
        node = dict(raw["nodes"][series["index"]["ref"]])
        node.update(start=2, stop=4)
        series["index"] = {"ref": len(raw["nodes"])}
        raw["nodes"].append(node)
    with pytest.raises(ValueError, match=r"(column count|indexes disagree)"):
        codec.decode_native_state(json.dumps(raw).encode())
