"""Native-expression and bounded synthetic-source checks, without dump or accounts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalExpression, PersonalStrategy
from quantos.research.personal_signal import (
    compile_strategy_signal,
    load_strategy_signal,
    strategy_gaps,
)
from quantos.research.qlib.personal_expression import (
    expression_dependencies,
    required_history,
    translate_personal_expression,
)


def expr(nodes=None, output="x", lag=0, field="adjusted_close"):
    return PersonalExpression.model_validate(
        {
            "expression_id": "synthetic",
            "nodes": nodes or [{"node_id": "x", "operator": "field", "field_name": field}],
            "output_node_id": output,
            "input_lag_trading_days": lag,
        }
    )


def engine(monkeypatch, data):
    """Inject synthetic field leaves; Qlib's own parser and operators compute values."""
    from qlib.config import C
    from qlib.data.base import Feature
    from qlib.data.cache import H
    from qlib.data.data import LocalExpressionProvider
    from qlib.data.ops import register_all_ops

    register_all_ops(C)
    H.clear()

    def leaf(self, instrument, start_index, end_index, *args):
        return pd.Series(np.asarray(data[instrument][self._name], dtype=np.float32)).loc[
            start_index:end_index
        ]

    monkeypatch.setattr(Feature, "_load_internal", leaf)
    return LocalExpressionProvider(), H


def native_values(monkeypatch, expression, values):
    provider, cache = engine(monkeypatch, {"STUB": values})
    cache.clear()
    return provider.get_expression_instance(translate_personal_expression(expression)).load(
        "STUB", 0, len(values["close"]) - 1, "day"
    )


def test_native_boolean_unknowns_zero_divisors_and_full_rolling_windows(monkeypatch):
    nodes = [
        {"node_id": "x", "operator": "field", "field_name": "adjusted_close"},
        {"node_id": "zero", "operator": "constant", "value": 0},
        {"node_id": "positive", "operator": "gt", "inputs": ["x", "zero"]},
        {"node_id": "inverse", "operator": "not", "inputs": ["positive"]},
    ]
    values = {"close": [np.nan, 0.0, 2.0, np.inf]}
    result = native_values(monkeypatch, expr(nodes, "inverse"), values)
    np.testing.assert_allclose(result, [np.nan, 1.0, 0.0, np.nan], equal_nan=True)
    nodes.append({"node_id": "either", "operator": "or", "inputs": ["positive", "inverse"]})
    np.testing.assert_allclose(
        native_values(monkeypatch, expr(nodes, "either"), values),
        [np.nan, 1, 1, np.nan],
        equal_nan=True,
    )
    nodes = [
        nodes[0],
        {"node_id": "zero", "operator": "constant", "value": 0},
        {"node_id": "ratio", "operator": "divide", "inputs": ["x", "zero"]},
    ]
    assert native_values(monkeypatch, expr(nodes, "ratio"), {"close": [1, 2, 3]}).isna().all()
    rolling = expr(
        [nodes[0], {"node_id": "mean", "operator": "rolling_mean", "inputs": ["x"], "window": 3}],
        "mean",
    )
    np.testing.assert_allclose(
        native_values(monkeypatch, rolling, {"close": [1, 2, 3, np.nan, 5, 6, 7]}),
        [np.nan, np.nan, 2, np.nan, np.nan, np.nan, 6],
        equal_nan=True,
    )


def test_dependency_offsets_include_implicit_constant_lag_once():
    expression = expr(
        [
            {"node_id": "x", "operator": "field", "field_name": "amount_cny"},
            {"node_id": "ret", "operator": "return", "inputs": ["x"], "window": 3},
        ],
        "ret",
        lag=2,
    )
    assert expression_dependencies(expression) == {"amount_cny": (2, 5)}
    assert required_history(expression) == 5
    assert translate_personal_expression(expression).startswith("Ref(")
    assert expression_dependencies(
        expr([{"node_id": "constant", "operator": "constant", "value": 1}], "constant", lag=1)
    ) == {"adjusted_close": (1,)}


@pytest.fixture
def source(tmp_path, monkeypatch):
    days = pd.bdate_range("2024-01-02", periods=8)
    codes = ["SH000300", "SH600001", "SZ300001"]
    rows = []
    for code in codes:
        for i, day in enumerate(days):
            rows.append(
                {
                    "trade_date": day.date(),
                    "qlib_id": code,
                    "close": 100 + i if code == "SH000300" else 10 + i,
                    "volume": 1000 + 100 * i,
                    "amount_cny": 42_000_000.0 + 1000 * i,
                    "is_member": code != "SH000300",
                    "is_st": False,
                    "is_suspended": False,
                    "is_listed": True,
                    "available_at": day.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=16),
                }
            )
    frame = pd.DataFrame(rows)
    cache_values = {
        code: {
            column: frame.loc[frame.qlib_id == code, column].to_numpy()
            for column in ("close", "volume", "amount_cny")
        }
        for code in codes
    }
    provider, cache = engine(monkeypatch, cache_values)
    calls = []

    def features(instruments, fields, start_time, end_time, freq):
        calls.append({"fields": fields, "start": start_time, "end": end_time})
        cache.clear()
        parts = []
        for code in instruments:
            columns = {
                field: provider.get_expression_instance(field)
                .load(code, 0, len(days) - 1, "day")
                .to_numpy(dtype=np.float32)
                for field in fields
            }
            part = pd.DataFrame(columns, index=days)
            part.index.name = "datetime"
            parts.append(part)
        result = pd.concat(parts, keys=instruments, names=["instrument", "datetime"])
        stamps = result.index.get_level_values("datetime")
        return result.loc[(stamps >= pd.Timestamp(start_time)) & (stamps <= pd.Timestamp(end_time))]

    import quantos.research.personal_signal as signal

    monkeypatch.setattr(signal, "D", SimpleNamespace(features=features))
    monkeypatch.setattr(signal, "qlib", SimpleNamespace(init=lambda **kw: None))
    root = tmp_path / "source"
    root.mkdir()
    provider_root = root / "provider"
    (provider_root / "calendars").mkdir(parents=True)
    (provider_root / "calendars/day.txt").write_text(
        "\n".join(day.date().isoformat() for day in days) + "\n"
    )
    for code in codes:
        directory = provider_root / "features" / code.lower()
        directory.mkdir(parents=True)
        for field in ("close", "volume", "amount_cny"):
            (directory / (field + ".day.bin")).write_bytes(
                b"synthetic-leaf-stub-not-an-executable-Qlib-cache"
            )
    panel = root / "panel.parquet"
    proof = root / "pit.json"
    proof.write_bytes(b'{"scope":"synthetic-source-unit-test"}')
    binding = SimpleNamespace(
        manifest=None, provider_root=provider_root, panel_path=panel, pit_evidence_path=proof
    )

    def refresh(data=frame):
        data.to_parquet(panel, index=False)
        inventory = {
            p.relative_to(provider_root).as_posix(): sha256_file(p)
            for p in provider_root.rglob("*")
            if p.is_file()
        }
        binding.manifest = SimpleNamespace(
            kind="synthetic",
            panel_sha256=sha256_file(panel),
            pit_evidence_hash=sha256_file(proof),
            qlib_files=inventory,
            source_vintage="synthetic",
            snapshot_hash="a" * 64,
            qlib_view_hash="b" * 64,
            content_hash=sha256_bytes(
                canonical_json_bytes({"panel": sha256_file(panel), "files": inventory})
            ),
        )

    refresh()
    return SimpleNamespace(
        binding=binding,
        frame=frame,
        refresh=refresh,
        days=days,
        codes=codes,
        calls=calls,
        cache_values=cache_values,
    )


def gaps(source, strategy=None, start=None):
    return strategy_gaps(
        source.binding,
        strategy or PersonalStrategy(score=expr()),
        start or source.days[4].date(),
        source.days[-1].date(),
        source.days[0].date(),
        "SH000300",
    )


def test_prepare_checks_raw_cache_once_amount_in_cny_and_warmup(source):
    strategy = PersonalStrategy(score=expr(field="amount_cny"))
    missing, detail = gaps(source, strategy)
    assert missing == []
    assert detail["source_validation"] == "VERIFIED_PANEL_PIT_AND_RAW_CACHE_VALUES"
    assert len(source.calls) == 1
    assert source.calls[0]["fields"] == ["$close", "$volume", "$amount_cny"]
    assert (
        source.frame.iloc[0].amount_cny != source.frame.iloc[0].close * source.frame.iloc[0].volume
    )
    long = PersonalStrategy(
        score=expr(
            [
                {"node_id": "x", "operator": "field", "field_name": "adjusted_close"},
                {"node_id": "r", "operator": "return", "inputs": ["x"], "window": 5},
            ],
            "r",
        )
    )
    assert any("WARMUP_INSUFFICIENT" in gap for gap in gaps(source, long)[0])


@pytest.mark.parametrize(
    "issue",
    [
        "future",
        "unknown",
        "naive",
        "dependency_future",
        "member_session",
        "entire_session",
        "non_session",
        "field_missing",
        "amount_mapping",
        "raw_mismatch",
    ],
)
def test_prepare_rejects_time_grid_field_and_value_gaps_early(source, issue):
    data = source.frame.copy()
    strategy = PersonalStrategy(score=expr(field="amount_cny"))
    if issue == "future":
        data.loc[0, "available_at"] += pd.Timedelta(days=1)
    elif issue == "unknown":
        data.loc[0, "available_at"] = pd.NaT
    elif issue == "naive":
        data["available_at"] = data.available_at.astype(str)
        data.loc[0, "available_at"] = "2024-01-02 16:00:00"
    elif issue == "dependency_future":
        data["factor_available_at"] = data.available_at
        data.loc[8, "factor_available_at"] += pd.Timedelta(days=1)
    elif issue == "member_session":
        data = data.drop(index=10)
    elif issue == "entire_session":
        data = data.loc[data.trade_date != source.days[2].date()]
    elif issue == "non_session":
        assert gaps(source, start=date(2024, 1, 6))[0]
        return
    elif issue == "field_missing":
        data = data.drop(columns="amount_cny")
    elif issue == "amount_mapping":
        (source.binding.provider_root / "features/sh600001/amount_cny.day.bin").unlink()
    elif issue == "raw_mismatch":
        data.loc[8, "amount_cny"] += 1_000_000
    source.refresh(data)
    assert gaps(source, strategy)[0]
    if issue not in {"raw_mismatch"}:
        assert source.calls == []


def test_signal_input_lag_market_gate_membership_nulls_and_readback(source, tmp_path):
    nodes = [
        {"node_id": "x", "operator": "field", "field_name": "adjusted_close"},
        {"node_id": "threshold", "operator": "constant", "value": 103},
        {"node_id": "open", "operator": "gt", "inputs": ["x", "threshold"]},
    ]
    strategy = PersonalStrategy(score=expr(lag=1), market_condition=expr(nodes, "open"))
    data = source.frame.copy()
    data.loc[
        (data.qlib_id == "SZ300001") & (data.trade_date < source.days[6].date()), "is_member"
    ] = False
    source.refresh(data)
    artifact, native = compile_strategy_signal(
        source.binding,
        strategy,
        source.days[0].date(),
        source.days[-1].date(),
        tmp_path / "signal",
        "f" * 64,
    )
    assert len(source.calls) == 1
    assert (
        native.loc[(source.days[0], "SH600001"), "score"]
        != native.loc[(source.days[0], "SH600001"), "score"]
    )
    assert np.isnan(native.loc[(source.days[3], "SH600001"), "score"])
    assert native.loc[(source.days[4], "SH600001"), "score"] == 13
    assert np.isnan(native.loc[(source.days[5], "SZ300001"), "score"])
    assert native.loc[(source.days[6], "SZ300001"), "score"] == 15
    loaded_artifact, loaded = load_strategy_signal(tmp_path / "signal", artifact.content_hash)
    assert loaded_artifact == artifact
    pd.testing.assert_frame_equal(native, loaded)
    assert str(loaded.index.levels[0].dtype) == "datetime64[ns]"
    rows = pd.read_parquet(tmp_path / "signal/signals.parquet")
    assert rows.score.isna().any()
    assert not rows.loc[~rows.tradable, "score_valid"].any()
    assert artifact.input_lag == "expression_once"
    assert artifact.execution_lag == "native_previous_actual_session_once"


def test_signal_reuse_never_overwrites_and_tamper_rejects(source, tmp_path):
    strategy = PersonalStrategy(score=expr())
    directory = tmp_path / "signal"
    artifact, native = compile_strategy_signal(
        source.binding, strategy, source.days[0].date(), source.days[-1].date(), directory, "f" * 64
    )
    originals = {p.name: p.read_bytes() for p in directory.iterdir()}
    artifact2, again = compile_strategy_signal(
        source.binding, strategy, source.days[0].date(), source.days[-1].date(), directory, "f" * 64
    )
    assert artifact2 == artifact
    pd.testing.assert_frame_equal(native, again)
    assert len(source.calls) == 1
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == originals
    with pytest.raises(ValueError, match="binding changed"):
        compile_strategy_signal(
            source.binding,
            strategy,
            source.days[0].date(),
            source.days[-1].date(),
            directory,
            "e" * 64,
        )
    (directory / "signals.parquet").write_bytes(originals["signals.parquet"] + b"tampered")
    with pytest.raises(ValueError, match="identity"):
        load_strategy_signal(directory, artifact.content_hash)


def test_submicrosecond_availability_is_rounded_forward(source, tmp_path):
    source.frame["available_at"] += pd.Timedelta(nanoseconds=1)
    source.refresh()
    artifact, _ = compile_strategy_signal(
        source.binding,
        PersonalStrategy(score=expr()),
        source.days[0].date(),
        source.days[-1].date(),
        tmp_path / "rounded",
        "f" * 64,
    )
    load_strategy_signal(tmp_path / "rounded", artifact.content_hash)
    rows = pd.read_parquet(tmp_path / "rounded/signals.parquet")
    assert rows.iloc[0].available_at >= source.frame.iloc[0].available_at
    assert rows.iloc[0].available_at.microsecond == 1
