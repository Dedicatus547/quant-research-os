import csv
import json
from pathlib import Path


def test_fixture_is_explicitly_synthetic_and_internally_consistent() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
    manifest = json.loads((root / "manifest.json").read_bytes())
    with (root / "bars.csv").open(encoding="utf-8", newline="") as stream:
        bars = list(csv.DictReader(stream))
    with (root / "adj_factor.csv").open(encoding="utf-8", newline="") as stream:
        factors = list(csv.DictReader(stream))
    with (root / "stock_basic.csv").open(encoding="utf-8", newline="") as stream:
        instruments = list(csv.DictReader(stream))
    with (root / "trade_cal.csv").open(encoding="utf-8", newline="") as stream:
        calendar = list(csv.DictReader(stream))
    with (root / "index_daily.csv").open(encoding="utf-8", newline="") as stream:
        benchmark = list(csv.DictReader(stream))

    assert manifest["synthetic"] is True
    assert manifest["redistributable"] is True
    assert len(bars) == len(factors) == 7
    assert len(instruments) == 2
    assert len(calendar) == 8
    assert len(benchmark) == 4
    assert {row["exchange"] for row in calendar} == {"SSE", "SZSE"}
    assert {(row["ts_code"], row["trade_date"]) for row in bars} == {
        (row["ts_code"], row["trade_date"]) for row in factors
    }
    for row in bars:
        assert float(row["low"]) <= float(row["open"]) <= float(row["high"])
        assert float(row["low"]) <= float(row["close"]) <= float(row["high"])


def test_backtest_fixture_spans_signal_execution_and_following_session() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "synthetic_backtest_snapshot"
    manifest = json.loads((root / "manifest.json").read_bytes())
    with (root / "bars.csv").open(encoding="utf-8", newline="") as stream:
        bars = list(csv.DictReader(stream))
    with (root / "adj_factor.csv").open(encoding="utf-8", newline="") as stream:
        factors = list(csv.DictReader(stream))
    with (root / "trade_cal.csv").open(encoding="utf-8", newline="") as stream:
        calendar = list(csv.DictReader(stream))

    assert manifest["synthetic"] is True
    assert manifest["date_range"]["end"] == "2024-01-09"
    assert {(row["ts_code"], row["trade_date"]) for row in bars} == {
        (row["ts_code"], row["trade_date"]) for row in factors
    }
    sz_sessions = {
        row["cal_date"] for row in calendar if row["exchange"] == "SZSE" and row["is_open"] == "1"
    }
    assert {"20240105", "20240108", "20240109"}.issubset(sz_sessions)
    assert any(row["ts_code"] == "000001.SZ" and row["trade_date"] == "20240108" for row in bars)
