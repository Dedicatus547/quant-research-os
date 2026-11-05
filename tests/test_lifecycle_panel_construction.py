"""Offline structural panel transforms; synthetic sources confer no market qualification."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.hs300_lifecycle import LifecycleFactBundle
from quantos.research import hs300_lifecycle_data as data


@pytest.fixture
def tables(tmp_path, monkeypatch):
    days = [date(2024, 1, day) for day in (2, 3, 4)]
    codes = ["600000.SH", "000001.SZ"]
    timestamp = datetime(2024, 1, 2, 16, tzinfo=UTC)
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (tmp_path / "manifest.json").write_text("synthetic transform fixture")
    tables = {
        "calendar": pd.DataFrame({"trade_date": days, "is_open": True}),
        "bars": pd.DataFrame(
            [
                {
                    "instrument_id": code,
                    "trade_date": day,
                    "close": 10.0,
                    "volume_shares": 200.0,
                    "amount_cny": 2000.0,
                    "available_at": timestamp,
                }
                for code in codes
                for day in days
                if (code == codes[0] and day < days[-1]) or (code == codes[1] and day > days[0])
            ]
        ),
        "benchmark_bars": pd.DataFrame(
            [
                {
                    "benchmark_id": "000300.SH",
                    "trade_date": day,
                    "close": 100.0,
                    "volume_shares": 1000.0,
                    "amount_cny": 100000.0,
                    "available_at": timestamp,
                }
                for day in days
            ]
        ),
        "index_membership": pd.DataFrame(
            [
                {
                    "index_id": "000300.SH",
                    "instrument_id": code,
                    "effective_from": days[0],
                    "effective_to": days[-1],
                    "available_from": days[0],
                    "available_at": timestamp,
                }
                for code in codes
            ]
        ),
        "instruments": pd.DataFrame(
            [
                {"instrument_id": codes[0], "list_date": date(2000, 1, 1), "delist_date": days[-1]},
                {"instrument_id": codes[1], "list_date": days[1], "delist_date": None},
            ]
        ),
        "st_status": pd.DataFrame(
            {"trade_date": [days[1]], "instrument_id": [codes[0]], "available_at": [timestamp]}
        ),
        "suspensions": pd.DataFrame(
            {"trade_date": [days[1]], "instrument_id": [codes[0]], "available_at": [timestamp]}
        ),
    }
    tables["adjustment_factors"] = tables["bars"][
        ["instrument_id", "trade_date", "available_at"]
    ].assign(adjustment_factor=2.0)
    source = tmp_path / "synthetic-source.json"
    source.write_text('{"purpose":"synthetic lifecycle transform only"}')
    facts = LifecycleFactBundle(
        coverage_start=days[0],
        coverage_end=days[-1],
        source_vintage="synthetic",
        sources=(
            {
                "source_id": "fixture",
                "kind": "SYNTHETIC_FIXTURE",
                "logical_path": source.name,
                "sha256": sha256_file(source),
                "observed_at": timestamp,
            },
        ),
        securities=tuple(
            {**row, "source_ids": ["fixture"]} for row in tables["instruments"].to_dict("records")
        ),
        events=(
            {
                "event_id": "delisted",
                "instrument_id": codes[0],
                "boundary_date": days[-1],
                "event_type": "DELISTING",
                "source_ids": ["fixture"],
            },
        ),
    )
    lifecycle = tmp_path / "lifecycle.json"
    lifecycle.write_bytes(facts.canonical_bytes())
    snapshot = SimpleNamespace(start_date=days[0], end_date=days[-1], snapshot_hash="a" * 64)
    monkeypatch.setattr(
        data,
        "verify_hs300_origins",
        lambda *args, **kwargs: (
            snapshot,
            SimpleNamespace(view_hash="b" * 64),
            {"synthetic": sha256_file(source)},
        ),
    )

    def build():
        for name, frame in tables.items():
            frame.to_parquet(canonical / (name + ".parquet"), index=False)
        return data.build_hs300_lifecycle_panel(
            tmp_path,
            tmp_path,
            expected_snapshot_hash="a" * 64,
            expected_view_hash="b" * 64,
            lifecycle_path=lifecycle,
            expected_lifecycle_hash=facts.content_hash,
            warmup_start=days[0],
            end_date=days[-1],
        )

    return SimpleNamespace(
        tables=tables,
        days=days,
        facts=facts,
        path=lifecycle,
        source=source,
        build=build,
        snapshot=snapshot,
    )


def test_structural_absence_preserves_membership_and_does_not_anticipate_delisting(tables):
    panel, provenance = tables.build()
    stocks = panel[panel.qlib_id != "SH000300"].set_index(["trade_date", "qlib_id"])
    assert len(panel) == 9 and stocks.is_member.all()
    before = stocks.loc[(tables.days[1], "SH600000")]
    after = stocks.loc[(tables.days[-1], "SH600000")]
    unlisted = stocks.loc[(tables.days[0], "SZ000001")]
    assert before.is_listed and before.close == 20 and before.volume == 100
    assert before.is_st and before.is_suspended
    assert not after.is_listed and after.lifecycle_state == "DELISTED" and pd.isna(after.close)
    assert not unlisted.is_listed and unlisted.lifecycle_state == "PRE_LISTING"
    assert provenance["structural_member_rows"] == provenance["structural_missing_bar_rows"] == 2
    assert provenance["membership_rows_preserved"] == 6
    assert provenance["lifecycle_role"] == "STRUCTURAL_ONLY_NO_ANTICIPATORY_EXIT"


@pytest.mark.parametrize(
    "attack,match",
    [
        ("coverage", "source coverage"),
        ("calendar", "coverage missing"),
        ("instrument", "instrument lifecycle"),
        ("bars_duplicate", "duplicate lifecycle"),
        ("factors_duplicate", "duplicate lifecycle"),
        ("factor_missing", "factor missing"),
        ("factor_zero", "factor missing"),
        ("membership_overlap", "overlapping"),
        ("bar_missing", "observations missing"),
        ("benchmark_missing", "benchmark session"),
    ],
)
def test_missing_or_contradictory_sources_cannot_become_structural_absence(tables, attack, match):
    frames = tables.tables
    if attack == "coverage":
        tables.snapshot.end_date = tables.days[0]
    elif attack == "calendar":
        frames["calendar"]["is_open"] = False
    elif attack == "instrument":
        frames["instruments"].loc[0, "delist_date"] = tables.days[1]
    elif attack.endswith("duplicate"):
        name = "bars" if attack.startswith("bars") else "adjustment_factors"
        frames[name] = pd.concat([frames[name], frames[name].iloc[:1]])
    elif attack == "factor_missing":
        frames["adjustment_factors"] = frames["adjustment_factors"].iloc[1:]
    elif attack == "factor_zero":
        frames["adjustment_factors"].loc[0, "adjustment_factor"] = 0
    elif attack == "membership_overlap":
        frames["index_membership"] = pd.concat([frames["index_membership"]] * 2)
    elif attack == "bar_missing":
        frames["bars"] = frames["bars"].iloc[1:]
    else:
        frames["benchmark_bars"] = frames["benchmark_bars"].iloc[1:]
    with pytest.raises(ValueError, match=match):
        tables.build()


def test_lifecycle_fact_identity_and_source_bytes_are_both_required(tables):
    assert data.load_lifecycle_facts(tables.path, tables.facts.content_hash) == tables.facts
    with pytest.raises(ValueError, match="manifest hash"):
        data.load_lifecycle_facts(tables.path, "b" * 64)
    tables.source.write_text("revised source")
    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        data.load_lifecycle_facts(tables.path, tables.facts.content_hash)
