"""Offline successor distinguishing index membership, existence and tradability."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.parquet as pq

from quantos.artifacts.store import confined_regular_file, sha256_file, verify_file
from quantos.contracts.hs300_lifecycle import HS300LifecycleDatasetManifest, LifecycleFactBundle
from quantos.research.hs300_data import (
    HS300_PANEL_COLUMNS,
    compile_hs300_daily_signals,
    verify_hs300_origins,
)

LIFECYCLE_PANEL_COLUMNS = (*HS300_PANEL_COLUMNS, "is_listed", "lifecycle_state")


def load_lifecycle_facts(path: Path, expected_hash: str) -> LifecycleFactBundle:
    facts = LifecycleFactBundle.model_validate_json(path.read_bytes())
    if facts.content_hash != expected_hash:
        raise ValueError("lifecycle manifest hash disagrees")
    for source in facts.sources:
        verify_file(confined_regular_file(path.parent, source.logical_path), source.sha256)
    if facts.source_vintage != "synthetic":
        from quantos.data.lifecycle_sources import verify_lifecycle_source_values

        verify_lifecycle_source_values(facts, path.parent)
    return facts


def build_hs300_lifecycle_panel(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
    lifecycle_path: Path,
    expected_lifecycle_hash: str,
    warmup_start: date,
    end_date: date,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep post-delisting membership rows and their structural NaNs explicitly.

    Actual listing/delisting dates explain existence on that date only. They do
    not alter earlier prices, ranks, targets or announce an anticipatory exit.
    """
    snapshot, view, source_files = verify_hs300_origins(
        snapshot_path,
        view_path,
        expected_snapshot_hash=expected_snapshot_hash,
        expected_view_hash=expected_view_hash,
    )
    facts = load_lifecycle_facts(lifecycle_path, expected_lifecycle_hash)
    if not snapshot.start_date <= warmup_start <= end_date <= snapshot.end_date:
        raise ValueError("lifecycle panel dates exceed immutable source coverage")
    if not facts.coverage_start <= warmup_start <= end_date <= facts.coverage_end:
        raise ValueError("lifecycle facts do not cover panel dates")

    def read(name: str, *, dated: bool = True) -> Any:
        filters = (
            [("trade_date", ">=", warmup_start), ("trade_date", "<=", end_date)] if dated else None
        )
        return (
            cast(Any, pq)
            .read_table(snapshot_path / "canonical" / f"{name}.parquet", filters=filters)
            .to_pandas()
        )

    calendar = read("calendar")
    sessions = sorted(calendar.loc[calendar["is_open"], "trade_date"].unique())
    bars, factors, benchmark = read("bars"), read("adjustment_factors"), read("benchmark_bars")
    benchmark = benchmark.loc[benchmark["benchmark_id"] == "000300.SH"].copy()
    membership = read("index_membership", dated=False)
    membership = membership.loc[
        (membership["index_id"] == "000300.SH")
        & (membership["effective_to"] >= warmup_start)
        & (membership["effective_from"] <= end_date)
    ]
    instruments = read("instruments", dated=False).set_index("instrument_id")
    fact_by_id = {fact.instrument_id: fact for fact in facts.securities}
    names = sorted(set(bars["instrument_id"]) | set(membership["instrument_id"]))
    if not sessions or membership.empty or benchmark.empty or not set(names) <= set(fact_by_id):
        raise ValueError("SOURCE_INCOMPLETE: lifecycle sessions/member/security coverage missing")
    for code in names:
        fact = fact_by_id[code]
        row = instruments.loc[code]
        actual_delist = None if pd.isna(row["delist_date"]) else row["delist_date"]
        if fact.list_date != row["list_date"] or fact.delist_date != actual_delist:
            raise ValueError("lifecycle facts disagree with immutable instrument lifecycle")
    keys = ["trade_date", "instrument_id"]
    for data in (bars, factors):
        if data.duplicated(keys).any():
            raise ValueError("duplicate lifecycle source observation")
    joined = bars.merge(
        factors[[*keys, "adjustment_factor", "available_at"]],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_factor"),
    )
    if joined["adjustment_factor"].isna().any() or (joined["adjustment_factor"] <= 0).any():
        raise ValueError("SOURCE_INCOMPLETE: lifecycle adjustment factor missing or invalid")
    joined["close"] *= joined["adjustment_factor"]
    joined["volume"] = joined["volume_shares"] / joined["adjustment_factor"]
    joined["available_at"] = joined[["available_at", "available_at_factor"]].max(axis=1)
    dense = pd.MultiIndex.from_product([sessions, names], names=keys)
    frame = joined.set_index(keys).reindex(dense)
    member_rows = [
        (day, row.instrument_id, row.available_at)
        for row in membership.itertuples()
        for day in sessions
        if max(row.effective_from, row.available_from) <= day <= row.effective_to
    ]
    member_frame = pd.DataFrame(member_rows, columns=[*keys, "available_at"]).set_index(keys)
    if member_frame.index.duplicated().any():
        raise ValueError("overlapping lifecycle historical membership intervals")
    frame["is_member"] = frame.index.isin(member_frame.index)
    frame["available_at"] = pd.concat(
        [frame["available_at"], member_frame["available_at"].reindex(frame.index)], axis=1
    ).max(axis=1)
    for name, column in (("st_status", "is_st"), ("suspensions", "is_suspended")):
        status = read(name).groupby(keys)["available_at"].max()
        frame[column] = frame.index.isin(status.index)
        frame["available_at"] = pd.concat(
            [frame["available_at"], status.reindex(frame.index)], axis=1
        ).max(axis=1)
    dates = frame.index.get_level_values("trade_date")
    codes = frame.index.get_level_values("instrument_id")
    listing = [
        fact_by_id[code].list_date <= day
        and (fact_by_id[code].delist_date is None or day < fact_by_id[code].delist_date)
        for day, code in zip(dates, codes, strict=True)
    ]
    frame["is_listed"] = listing
    frame["lifecycle_state"] = [
        "LISTED" if listed else ("PRE_LISTING" if day < fact_by_id[code].list_date else "DELISTED")
        for day, code, listed in zip(dates, codes, listing, strict=True)
    ]
    required = frame["is_member"] & frame["is_listed"] & ~frame["is_suspended"]
    missing = frame.loc[required, ["close", "volume", "amount_cny", "available_at"]]
    if missing.isna().any().any():
        bad = missing[missing.isna().any(axis=1)]
        raise ValueError(
            f"SOURCE_INCOMPLETE: {len(bad)} listed unsuspended member observations missing; "
            f"first keys={list(bad.index[:10])}"
        )
    structural = frame.loc[frame["is_member"] & ~frame["is_listed"]]
    frame = frame.reset_index()
    frame["qlib_id"] = frame["instrument_id"].str[-2:] + frame["instrument_id"].str[:6]
    benchmark["qlib_id"] = "SH000300"
    benchmark["volume"] = benchmark["volume_shares"]
    benchmark["is_member"], benchmark["is_st"], benchmark["is_suspended"] = False, False, False
    benchmark["is_listed"], benchmark["lifecycle_state"] = True, "LISTED"
    if set(benchmark["trade_date"]) != set(sessions):
        raise ValueError("SOURCE_INCOMPLETE: lifecycle benchmark session coverage incomplete")
    panel = cast(
        pd.DataFrame,
        pd.concat(
            [frame[list(LIFECYCLE_PANEL_COLUMNS)], benchmark[list(LIFECYCLE_PANEL_COLUMNS)]],
            ignore_index=True,
        )
        .sort_values(["trade_date", "qlib_id"], kind="mergesort")
        .reset_index(drop=True),
    )
    provenance = {
        "schema_version": "hs300-lifecycle-panel-origin/v1",
        "kind": "market",
        "market_source": "TUSHARE_PRO",
        "snapshot_hash": snapshot.snapshot_hash,
        "qlib_view_hash": view.view_hash,
        "snapshot_manifest_sha256": sha256_file(snapshot_path / "manifest.json"),
        "view_manifest_sha256": sha256_file(view_path / "manifest.json"),
        "source_files": source_files,
        "adapter_sha256": sha256_file(Path(__file__)),
        "base_adapter_sha256": sha256_file(Path(__file__).with_name("hs300_data.py")),
        "lifecycle_manifest_hash": facts.content_hash,
        "lifecycle_source_hashes": {source.source_id: source.sha256 for source in facts.sources},
        "native_boundary_policy_hash": facts.policy.content_hash,
        "warmup_start": warmup_start.isoformat(),
        "end_date": end_date.isoformat(),
        "source_vintage": "historical_non_vintage",
        "structural_member_rows": len(structural),
        "structural_missing_bar_rows": int(structural["close"].isna().sum()),
        "membership_rows_preserved": int(frame["is_member"].sum()),
        "lifecycle_role": "STRUCTURAL_ONLY_NO_ANTICIPATORY_EXIT",
    }
    return panel, provenance


def verify_hs300_lifecycle_binding(binding: Any) -> None:
    manifest = binding.manifest
    if not isinstance(manifest, HS300LifecycleDatasetManifest) or binding.lifecycle_path is None:
        raise ValueError(
            "lifecycle dataset requires explicit successor manifest and facts original"
        )
    facts = load_lifecycle_facts(binding.lifecycle_path, manifest.lifecycle_manifest_hash)
    if (
        manifest.lifecycle_source_hashes
        != {source.source_id: source.sha256 for source in facts.sources}
        or manifest.native_boundary_policy_hash != facts.policy.content_hash
    ):
        raise ValueError("lifecycle source or native boundary policy binding disagrees")
    if not facts.coverage_start <= manifest.warmup_start <= manifest.end_date <= facts.coverage_end:
        raise ValueError("lifecycle fact coverage does not cover registered panel")
    verify_file(binding.panel_path, manifest.panel_sha256)
    if binding.pit_evidence_path is None:
        raise ValueError("lifecycle panel provenance original missing")
    verify_file(binding.pit_evidence_path, manifest.pit_evidence_hash)
    proof = json.loads(binding.pit_evidence_path.read_bytes())
    for name in (
        "kind",
        "snapshot_hash",
        "qlib_view_hash",
        "panel_sha256",
        "lifecycle_manifest_hash",
        "lifecycle_source_hashes",
        "native_boundary_policy_hash",
    ):
        if proof.get(name) != getattr(manifest, name):
            raise ValueError("lifecycle immutable provenance binding disagrees")
    if manifest.kind == "synthetic":
        if facts.source_vintage != "synthetic":
            raise ValueError("synthetic lifecycle dataset requires synthetic source facts")
        return
    if facts.source_vintage != "historical_non_vintage" or binding.snapshot_path is None:
        raise ValueError("market lifecycle source original or non-vintage identity missing")
    _snapshot, view, sources = verify_hs300_origins(
        binding.snapshot_path,
        binding.provider_root,
        expected_snapshot_hash=manifest.snapshot_hash,
        expected_view_hash=manifest.qlib_view_hash,
    )
    if (
        sources != manifest.source_files
        or proof.get("source_files") != sources
        or proof.get("adapter_sha256") != sha256_file(Path(__file__))
        or proof.get("base_adapter_sha256")
        != sha256_file(Path(__file__).with_name("hs300_data.py"))
        or {item.logical_path: item.sha256 for item in view.files} != manifest.qlib_files
        or sha256_file(binding.snapshot_path / "manifest.json") != manifest.snapshot_manifest_sha256
        or sha256_file(binding.provider_root / "manifest.json") != manifest.view_manifest_sha256
        or proof.get("warmup_start") != manifest.warmup_start.isoformat()
        or proof.get("end_date") != manifest.end_date.isoformat()
    ):
        raise ValueError("lifecycle origin or adapter proof changed")


def compile_hs300_lifecycle_signals(panel: pd.DataFrame, prepared: Any) -> dict[str, pd.DataFrame]:
    if set(panel.columns) != set(LIFECYCLE_PANEL_COLUMNS):
        raise ValueError("panel fields must match lifecycle successor daily panel/v1")
    # Keep the authoritative panel's member history intact. Only the local signal
    # eligibility projection intersects same-date existence, never future events.
    eligible: Any = panel[list(HS300_PANEL_COLUMNS)].copy()
    eligible["is_member"] = panel["is_member"] & panel["is_listed"]
    return compile_hs300_daily_signals(eligible, prepared)
