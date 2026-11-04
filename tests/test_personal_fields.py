"""Four-symbol field mapping and actual Qlib features; no account or acquisition."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import qlib
from qlib.data import D
from qlib.data.storage.file_storage import FileFeatureStorage

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.research.personal_fields import (
    CANONICAL_PROFILE,
    CanonicalAmountFeatureProvider,
    augment_canonical_fields,
)

CODES = ("SH600001", "SH600002", "SZ000001", "SH000300")
DAYS = tuple(pd.bdate_range("2024-01-02", periods=8).date)


def source_fixture(tmp_path):
    root = tmp_path / "snapshot/canonical"
    root.mkdir(parents=True)
    bars, factors, benchmark, rows = [], [], [], []
    for stock, code in enumerate(CODES):
        for index, day in enumerate(DAYS):
            quote = 10 + stock + index
            base = {
                "trade_date": day,
                "open": float(quote),
                "close": quote + 0.2,
                "high": quote + 0.5,
                "low": quote - 0.4,
                "volume_shares": 1000 + index * 100 + stock,
                "amount_cny": 12345.67 + index * 333 + stock * 101,
                "available_at": pd.Timestamp(day).tz_localize("Asia/Shanghai")
                + pd.Timedelta(hours=16),
            }
            factor = 1.0 if code == "SH000300" else (2.0 if index < 4 else 2.5)
            if code == "SH000300":
                benchmark.append({**base, "benchmark_id": "000300.SH"})
            else:
                identifier = code[2:] + "." + code[:2]
                bars.append({**base, "instrument_id": identifier})
                factors.append(
                    {
                        "instrument_id": identifier,
                        "trade_date": day,
                        "adjustment_factor": factor,
                        "available_at": base["available_at"] + pd.Timedelta(minutes=30),
                    }
                )
            rows.append(
                {
                    "trade_date": day,
                    "qlib_id": code,
                    "close": base["close"] * factor,
                    "volume": base["volume_shares"] / factor,
                    "amount_cny": base["amount_cny"],
                    "is_member": code != "SH000300",
                    "is_listed": True,
                    "is_suspended": False,
                    "available_at": base["available_at"] + pd.Timedelta(hours=1),
                }
            )
    tables = {
        "bars": pd.DataFrame(bars),
        "adjustment_factors": pd.DataFrame(factors),
        "benchmark_bars": pd.DataFrame(benchmark),
    }
    hashes = {}
    for name, table in tables.items():
        path = root / (name + ".parquet")
        table.to_parquet(path, index=False)
        hashes["canonical/" + path.name] = sha256_file(path)
    binding = SimpleNamespace(
        field_mapping_profile=CANONICAL_PROFILE,
        snapshot_path=root.parent,
        manifest=SimpleNamespace(kind="market", benchmarks=("SH000300",), source_files=hashes),
    )
    return binding, pd.DataFrame(rows), tables


def rewrite_fixture(binding, tables, name):
    path = binding.snapshot_path / "canonical" / (name + ".parquet")
    tables[name].to_parquet(path, index=False)
    binding.manifest.source_files["canonical/" + path.name] = sha256_file(path)


def test_canonical_ohlc_factor_units_source_clocks_and_input_originals(tmp_path):
    binding, frame, _ = source_fixture(tmp_path)
    frame.index = pd.RangeIndex(100, 100 + len(frame))
    original = frame.copy(deep=True)
    out = augment_canonical_fields(binding, frame)
    pd.testing.assert_frame_equal(frame, original)
    assert out.index.equals(frame.index)
    first = out.iloc[0]
    assert first["open"] == 20 and first["high"] == 21 and first["low"] == 19.2
    assert first["adjustment_factor"] == 2 and first["volume"] == 500
    assert first["amount_cny"] == 12345.67
    assert first["amount_cny"] != first["close"] * first["volume"]
    assert first["open_available_at"] == first["available_at_factor"]
    assert first["amount_cny_available_at"] == first["available_at_bar"]
    bench = out.loc[out.qlib_id == "SH000300"].iloc[0]
    assert bench["adjustment_factor"] == 1 and bench["open"] == 13
    assert bench["volume"] == 1003


def test_old_profile_and_synthetic_input_are_not_remapped_or_padded(tmp_path):
    binding, frame, _ = source_fixture(tmp_path)
    binding.field_mapping_profile = "native-bins/v1"
    binding.snapshot_path = None
    assert augment_canonical_fields(binding, frame) is frame
    binding.field_mapping_profile = CANONICAL_PROFILE
    binding.manifest.kind = "synthetic"
    assert augment_canonical_fields(binding, frame) is frame
    assert "open" not in frame


@pytest.mark.parametrize(
    "fault",
    [
        "close",
        "volume",
        "amount_cny",
        "factor",
        "duplicate",
        "missing",
        "unknown-time",
        "future-time",
    ],
)
def test_canonical_mapping_rejects_source_disagreement_and_invalid_origin(tmp_path, fault):
    binding, frame, tables = source_fixture(tmp_path)
    if fault in {"close", "volume", "amount_cny"}:
        frame.loc[0, fault] += 1
    elif fault == "factor":
        tables["adjustment_factors"].loc[0, "adjustment_factor"] = 0
        rewrite_fixture(binding, tables, "adjustment_factors")
    elif fault == "duplicate":
        tables["bars"] = pd.concat([tables["bars"], tables["bars"].iloc[:1]], ignore_index=True)
        rewrite_fixture(binding, tables, "bars")
    elif fault == "missing":
        tables["bars"] = tables["bars"].iloc[1:]
        rewrite_fixture(binding, tables, "bars")
    elif fault == "unknown-time":
        tables["bars"]["available_at"] = tables["bars"].available_at.dt.tz_localize(None)
        rewrite_fixture(binding, tables, "bars")
    elif fault == "future-time":
        tables["bars"].loc[0, "available_at"] += pd.Timedelta(days=1)
        rewrite_fixture(binding, tables, "bars")
    with pytest.raises(ValueError, match="CANONICAL_FIELDS"):
        augment_canonical_fields(binding, frame)


def test_hash_tamper_rejects_before_parsing_the_source(tmp_path):
    binding, frame, _ = source_fixture(tmp_path)
    (binding.snapshot_path / "canonical/bars.parquet").write_bytes(b"changed")
    with pytest.raises(ArtifactIntegrityError):
        augment_canonical_fields(binding, frame)


def test_structural_absence_keeps_null_values_and_does_not_invent_source_clocks(tmp_path):
    binding, frame, tables = source_fixture(tmp_path)
    day = DAYS[0]
    for name in ("bars", "adjustment_factors"):
        table = tables[name]
        tables[name] = table.loc[
            ~((table.instrument_id == "600001.SH") & (table.trade_date == day))
        ]
        rewrite_fixture(binding, tables, name)
    frame.loc[0, "is_listed"] = False
    frame.loc[0, ["close", "volume", "amount_cny"]] = np.nan
    out = augment_canonical_fields(binding, frame)
    assert pd.isna(out.loc[0, "open"]) and pd.isna(out.loc[0, "adjustment_factor"])
    assert pd.isna(out.loc[0, "available_at_bar"]) and pd.isna(out.loc[0, "available_at_factor"])
    assert out.loc[0, "available_at"] == frame.loc[0, "available_at"]


def configure_provider(provider, frame, *, calendar_sessions=DAYS):
    qlib.init(
        provider_uri=str(provider),
        region="cn",
        kernels=1,
        clear_mem_cache=True,
        feature_provider={
            "class": "CanonicalAmountFeatureProvider",
            "module_path": "quantos.research.personal_fields",
            "kwargs": {"frame": frame, "calendar_sessions": calendar_sessions},
        },
    )


def native_fixture(tmp_path):
    binding, frame, _ = source_fixture(tmp_path)
    provider = tmp_path / "provider"
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars/day.txt").write_text("\n".join(str(day) for day in DAYS) + "\n")
    qlib.init(provider_uri=str(provider), region="cn", kernels=1, clear_mem_cache=True)
    # Reuse Qlib's public storage writer for tiny fallback-price fixtures; no
    # custom bin dumper, old cache modification or snapshot relabelling.
    for code in CODES:
        (provider / "features" / code.lower()).mkdir(parents=True)
        values = frame.loc[frame.qlib_id == code, "close"].to_numpy(dtype=np.float32)
        FileFeatureStorage(code, "close", "day", provider_uri=str(provider)).write(values, index=0)
    return binding, frame, provider


def test_actual_qlib_features_evaluate_amount_ref_mean_and_delegate_native_price(tmp_path):
    binding, frame, provider = native_fixture(tmp_path)
    files = {
        p.relative_to(provider).as_posix(): sha256_file(p)
        for p in provider.rglob("*")
        if p.is_file()
    }
    configured = frame.copy(deep=True)
    configured.loc[
        (configured.qlib_id == CODES[1]) & (configured.trade_date == DAYS[3]), "is_suspended"
    ] = True
    configure_provider(provider, configured)
    fields = ["$amount_cny", "Ref($amount_cny,1)", "Mean($amount_cny,2)", "$close"]
    actual = D.features(list(CODES), fields, str(DAYS[0]), str(DAYS[-1]), freq="day", disk_cache=0)
    assert len(actual) == 32
    assert pd.isna(actual.loc[(CODES[1], pd.Timestamp(DAYS[3])), "$amount_cny"])
    first, second = np.float32(frame.iloc[0].amount_cny), np.float32(frame.iloc[1].amount_cny)
    row = actual.loc[(CODES[0], pd.Timestamp(DAYS[1]))]
    assert row["$amount_cny"] == second
    assert row["Ref($amount_cny,1)"] == first
    assert row["Mean($amount_cny,2)"] == np.float32((float(first) + float(second)) / 2)
    assert row["$close"] == np.float32(frame.iloc[1]["close"])
    assert actual["$amount_cny"].dtype == np.float32
    assert files == {
        p.relative_to(provider).as_posix(): sha256_file(p)
        for p in provider.rglob("*")
        if p.is_file()
    }
    actual.to_parquet(tmp_path / "native-features-observed.parquet")
    (tmp_path / "native-origin.json").write_text(
        json.dumps(
            {
                "source_kind": "SYNTHETIC_FIXTURE",
                "symbols": list(CODES),
                "sessions": 8,
                "source_files": binding.manifest.source_files,
                "untouched_native_price_files": files,
                "profile": CANONICAL_PROFILE,
            },
            indent=2,
        )
        + "\n"
    )


def test_reinitializing_with_new_frozen_frame_does_not_reuse_old_amount_values(tmp_path):
    _, frame, provider = native_fixture(tmp_path)
    configure_provider(provider, frame)
    first = D.features(
        [CODES[0]], ["$amount_cny"], str(DAYS[1]), str(DAYS[1]), freq="day", disk_cache=0
    ).iloc[0, 0]
    revised = frame.copy(deep=True)
    revised["amount_cny"] += 1_000_000
    configure_provider(provider, revised)
    second = D.features(
        [CODES[0]], ["$amount_cny"], str(DAYS[1]), str(DAYS[1]), freq="day", disk_cache=0
    ).iloc[0, 0]
    assert second == np.float32(frame.iloc[1].amount_cny + 1_000_000)
    assert first != second


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "unknown-code",
        "unknown-date",
        "naive-calendar-time",
        "negative",
        "unknown-suspension",
    ],
)
def test_provider_constructor_rejects_unknown_mapping_and_status(tmp_path, fault):
    _, frame, _ = source_fixture(tmp_path)
    calendar = DAYS
    if fault == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif fault == "unknown-code":
        frame.loc[0, "qlib_id"] = "600001.SH"
    elif fault == "unknown-date":
        frame.loc[0, "trade_date"] = pd.Timestamp("2024-01-13").date()
    elif fault == "naive-calendar-time":
        calendar = [pd.Timestamp(DAYS[0]) + pd.Timedelta(hours=1), *DAYS[1:]]
    elif fault == "negative":
        frame.loc[0, "amount_cny"] = -1
    elif fault == "unknown-suspension":
        frame["is_suspended"] = frame.is_suspended.astype("boolean")
        frame.loc[0, "is_suspended"] = None
    with pytest.raises(ValueError, match="CANONICAL"):
        CanonicalAmountFeatureProvider(frame=frame, calendar_sessions=calendar)


def test_provider_integer_indexes_and_native_calendar_binding_are_explicit(tmp_path):
    _, frame, provider = native_fixture(tmp_path)
    configure_provider(provider, frame)
    adapter = CanonicalAmountFeatureProvider(frame=frame, calendar_sessions=DAYS)
    values = adapter.feature(CODES[0], "$amount_cny", 1, 3, "day")
    assert list(values.index) == [1, 2, 3] and values.dtype == np.float32
    for start, end in ((-1, 1), (0, 8), (0.5, 1)):
        with pytest.raises(ValueError, match="INDEX_OUTSIDE"):
            adapter.feature(CODES[0], "$amount_cny", start, end, "day")
    with pytest.raises(ValueError, match="DAILY_ONLY"):
        adapter.feature(CODES[0], "$amount_cny", 0, 1, "1min")
    with pytest.raises(ValueError, match="INSTRUMENT"):
        adapter.feature("SH600009", "$amount_cny", 0, 1, "day")
    shifted = CanonicalAmountFeatureProvider(
        frame=frame.loc[frame.trade_date != DAYS[0]], calendar_sessions=DAYS[1:]
    )
    with pytest.raises(ValueError, match="NATIVE_CALENDAR_BINDING"):
        shifted.feature(CODES[0], "$amount_cny", 1, 3, "day")
