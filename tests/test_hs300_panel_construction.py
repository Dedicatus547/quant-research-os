"""The legacy amount panel keeps actual sessions, membership availability and units."""

import pandas as pd
import pytest

from quantos.research import hs300_data as legacy
from quantos.research import hs300_lifecycle_data as lifecycle
from test_lifecycle_panel_construction import tables as tables


@pytest.fixture
def panel_source(tables, monkeypatch):
    f = tables
    # The predecessor has no structural lifecycle exception. Its membership
    # intervals must be independently valid for every required observation.
    membership = f.tables["index_membership"]
    membership.loc[0, "effective_to"] = f.days[1]
    membership.loc[1, "available_from"] = f.days[1]
    monkeypatch.setattr(legacy, "verify_hs300_origins", lifecycle.verify_hs300_origins)

    def build():
        root = f.path.parent
        for name, frame in f.tables.items():
            frame.to_parquet(root / "canonical" / (name + ".parquet"), index=False)
        return legacy.build_hs300_panel(
            root,
            root,
            expected_snapshot_hash="a" * 64,
            expected_view_hash="b" * 64,
            warmup_start=f.days[0],
            end_date=f.days[-1],
        )

    f.build = build
    return f


def test_legacy_panel_keeps_dense_missing_rows_and_canonical_amount(panel_source):
    f = panel_source
    panel, provenance = f.build()
    assert len(panel) == 9
    rows = panel.set_index(["trade_date", "qlib_id"])
    first = rows.loc[(f.days[0], "SZ000001")]
    last = rows.loc[(f.days[-1], "SH600000")]
    assert not first.is_member and pd.isna(first.close)
    assert not last.is_member and pd.isna(last.close)
    traded = rows.loc[(f.days[1], "SZ000001")]
    assert traded.close == 20 and traded.volume == 100 and traded.amount_cny == 2000
    assert provenance["amount_source"].startswith("canonical/bars.parquet:amount_cny")
    assert provenance["source_vintage"] == "historical_non_vintage"


@pytest.mark.parametrize(
    "attack,match",
    [
        ("coverage", "source coverage"),
        ("calendar", "sessions/membership"),
        ("members", "sessions/membership"),
        ("duplicate", "duplicate HS300"),
        ("factor_missing", "factor missing/invalid"),
        ("factor_zero", "factor missing/invalid"),
        ("overlap", "overlapping"),
        ("bar_missing", "observations missing"),
        ("benchmark", "benchmark session coverage"),
    ],
)
def test_legacy_panel_rejects_missing_required_inputs(panel_source, attack, match):
    f, tables = panel_source, panel_source.tables
    if attack == "coverage":
        f.snapshot.end_date = f.days[0]
    elif attack == "calendar":
        tables["calendar"]["is_open"] = False
    elif attack == "members":
        tables["index_membership"] = tables["index_membership"].iloc[:0]
    elif attack == "duplicate":
        tables["bars"] = pd.concat([tables["bars"], tables["bars"].iloc[:1]])
    elif attack == "factor_missing":
        tables["adjustment_factors"] = tables["adjustment_factors"].iloc[1:]
    elif attack == "factor_zero":
        tables["adjustment_factors"]["adjustment_factor"] = 0
    elif attack == "overlap":
        tables["index_membership"] = pd.concat([tables["index_membership"]] * 2)
    elif attack == "bar_missing":
        tables["bars"] = tables["bars"].iloc[1:]
    else:
        tables["benchmark_bars"] = tables["benchmark_bars"].iloc[1:]
    with pytest.raises(ValueError, match=match):
        f.build()
