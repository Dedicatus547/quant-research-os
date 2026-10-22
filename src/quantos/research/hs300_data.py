"""Offline, source-bound HS300 panel adaptation; no acquisition or account engine."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from quantos.artifacts.store import confined_regular_file, sha256_file, verify_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_research import HS300DatasetManifest
from quantos.contracts.qlib_view import QlibViewManifest, QlibViewSpec
from quantos.contracts.snapshot import DataQualityReport, DataSnapshotManifest

SOURCE_TABLES = (
    "adjustment_factors",
    "bars",
    "benchmark_bars",
    "calendar",
    "index_membership",
    "instruments",
    "price_limits",
    "st_status",
    "suspensions",
)
HS300_PANEL_COLUMNS = (
    "trade_date",
    "qlib_id",
    "close",
    "volume",
    "amount_cny",
    "is_member",
    "is_st",
    "is_suspended",
    "available_at",
)


def verify_hs300_origins(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
) -> tuple[DataSnapshotManifest, QlibViewManifest, dict[str, str]]:
    """Adopt original canonical/health proofs without rerunning historical gates.

    Only consumed canonical tables and the original report are hashed here. Raw API
    payload reconciliation remains the original quality report's historical claim.
    The complete derived-cache inventory is verified by the executor before Qlib.
    """
    snapshot = DataSnapshotManifest.model_validate_json(
        confined_regular_file(snapshot_path, "manifest.json").read_bytes()
    )
    view = QlibViewManifest.model_validate_json(
        confined_regular_file(view_path, "manifest.json").read_bytes()
    )
    if (
        snapshot.snapshot_hash != expected_snapshot_hash
        or view.view_hash != expected_view_hash
        or view.source_snapshot_hash != snapshot.snapshot_hash
        or snapshot.source_kind != "TUSHARE"
        or snapshot.provider != "tushare-pro"
    ):
        raise ValueError("HS300 snapshot/view/source identity disagrees")
    spec_path = confined_regular_file(view_path, "view-spec.json")
    spec = QlibViewSpec.model_validate_json(spec_path.read_bytes())
    if (
        spec.content_hash != view.view_spec_hash
        or spec.source_snapshot_hash != snapshot.snapshot_hash
    ):
        raise ValueError("HS300 view specification disagrees")
    required = {f"canonical/{name}.parquet" for name in SOURCE_TABLES} | {"quality-report.json"}
    inventory = {item.logical_path: item for item in snapshot.files}
    if not required <= set(inventory):
        raise ValueError("SOURCE_INCOMPLETE: HS300 canonical source table missing")
    source_files = {logical: inventory[logical].sha256 for logical in sorted(required)}
    for logical, digest in source_files.items():
        verify_file(confined_regular_file(snapshot_path, logical), digest)
    quality = DataQualityReport.model_validate_json(
        confined_regular_file(snapshot_path, "quality-report.json").read_bytes()
    )
    if not quality.passed or quality.content_hash != snapshot.quality_report_hash:
        raise ValueError("HS300 original quality proof disagrees")
    return snapshot, view, source_files


def build_hs300_panel(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
    warmup_start: date,
    end_date: date,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build an immutable derivative from actual amount/availability/member rows.

    Dense session rows prevent a rolling window from silently skipping missing
    sessions. Inactive and explicitly suspended missing bars remain NaN; they
    cannot become a signal or an invented zero-amount observation.
    """
    snapshot, view, source_files = verify_hs300_origins(
        snapshot_path,
        view_path,
        expected_snapshot_hash=expected_snapshot_hash,
        expected_view_hash=expected_view_hash,
    )
    if not snapshot.start_date <= warmup_start <= end_date <= snapshot.end_date:
        raise ValueError("HS300 panel dates exceed immutable source coverage")

    def read(name: str, *, dated: bool = True) -> pd.DataFrame:
        filters = (
            [("trade_date", ">=", warmup_start), ("trade_date", "<=", end_date)] if dated else None
        )
        return cast(Any, pq).read_table(
            snapshot_path / "canonical" / f"{name}.parquet", filters=filters
        ).to_pandas()

    calendar = read("calendar")
    sessions = sorted(calendar.loc[calendar["is_open"], "trade_date"].unique())
    bars, factors, benchmark = read("bars"), read("adjustment_factors"), read("benchmark_bars")
    benchmark = benchmark.loc[benchmark["benchmark_id"] == "000300.SH"].copy()
    membership: Any = read("index_membership", dated=False)
    membership = membership.loc[
        (membership["index_id"] == "000300.SH")
        & (membership["effective_to"] >= warmup_start)
        & (membership["effective_from"] <= end_date)
    ]
    if not sessions or membership.empty or benchmark.empty:
        raise ValueError("SOURCE_INCOMPLETE: HS300 sessions/membership/benchmark missing")
    keys = ["trade_date", "instrument_id"]
    for data in (bars, factors):
        if data.duplicated(keys).any():
            raise ValueError("duplicate HS300 canonical observation")
    joined = bars.merge(
        factors[[*keys, "adjustment_factor", "available_at"]],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_factor"),
    )
    if joined["adjustment_factor"].isna().any() or (joined["adjustment_factor"] <= 0).any():
        raise ValueError("SOURCE_INCOMPLETE: canonical adjustment factor missing/invalid")
    joined["close"] *= joined["adjustment_factor"]
    joined["volume"] = joined["volume_shares"] / joined["adjustment_factor"]
    joined["available_at"] = joined[["available_at", "available_at_factor"]].max(axis=1)
    instruments = sorted(set(bars["instrument_id"]) | set(membership["instrument_id"]))
    dense = pd.MultiIndex.from_product([sessions, instruments], names=keys)
    frame = joined.set_index(keys).reindex(dense)
    frame["is_member"] = False
    frame["is_st"] = False
    frame["is_suspended"] = False
    # Expand bounded intervals once, then align availability as vectors. This avoids
    # hundreds of thousands of Python scalar DataFrame writes for the same projection.
    member_rows = [
        (day, row.instrument_id, row.available_at)
        for row in membership.itertuples()
        for day in sessions
        if max(row.effective_from, row.available_from) <= day <= row.effective_to
    ]
    member_frame = pd.DataFrame(member_rows, columns=[*keys, "available_at"]).set_index(keys)
    if member_frame.index.duplicated().any():
        raise ValueError("overlapping historical HS300 membership intervals")
    frame["is_member"] = frame.index.isin(member_frame.index)
    member_availability = member_frame["available_at"].reindex(frame.index)
    frame["available_at"] = pd.concat([frame["available_at"], member_availability], axis=1).max(
        axis=1
    )
    for name, column in (("st_status", "is_st"), ("suspensions", "is_suspended")):
        rows = read(name)
        status = rows.groupby(keys)["available_at"].max()
        frame[column] = frame.index.isin(status.index)
        frame["available_at"] = pd.concat(
            [frame["available_at"], status.reindex(frame.index)], axis=1
        ).max(axis=1)
    required = frame["is_member"] & ~frame["is_suspended"]
    if frame.loc[required, ["close", "volume", "amount_cny", "available_at"]].isna().any().any():
        missing = frame.loc[required, ["close", "volume", "amount_cny", "available_at"]]
        bad = missing[missing.isna().any(axis=1)]
        sample = [(str(day), str(code)) for day, code in bad.index[:10]]
        raise ValueError(
            f"SOURCE_INCOMPLETE: {len(bad)} unsuspended historical member observations missing; "
            f"first keys={sample}; missing columns={list(bad.columns[bad.isna().any()])}"
        )
    frame = frame.reset_index()
    frame["qlib_id"] = frame["instrument_id"].str[-2:] + frame["instrument_id"].str[:6]
    benchmark["qlib_id"] = "SH000300"
    benchmark["volume"] = benchmark["volume_shares"]
    benchmark["is_member"] = False
    benchmark["is_st"] = False
    benchmark["is_suspended"] = False
    if set(benchmark["trade_date"]) != set(sessions):
        raise ValueError("SOURCE_INCOMPLETE: benchmark session coverage is incomplete")
    panel = (
        pd.concat(
            [frame[list(HS300_PANEL_COLUMNS)], benchmark[list(HS300_PANEL_COLUMNS)]],
            ignore_index=True,
        )
        .sort_values(["trade_date", "qlib_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    provenance = {
        "schema_version": "hs300-panel-origin/v1",
        "kind": "market",
        "market_source": "TUSHARE_PRO",
        "snapshot_hash": snapshot.snapshot_hash,
        "qlib_view_hash": view.view_hash,
        "snapshot_manifest_sha256": sha256_file(snapshot_path / "manifest.json"),
        "view_manifest_sha256": sha256_file(view_path / "manifest.json"),
        "source_files": source_files,
        "adapter_sha256": sha256_file(Path(__file__)),
        "warmup_start": warmup_start.isoformat(),
        "end_date": end_date.isoformat(),
        "membership_policy": "conservative_next_session_0900_bounded_intervals",
        "source_vintage": "historical_non_vintage",
        "amount_source": (
            "canonical/bars.parquet:amount_cny; normalized CNY, no Qlib volume substitute"
        ),
        "signal_availability": (
            "max consumed bars/adjustment/member/status available_at, cutoff 23:59 Asia/Shanghai"
        ),
        "limits": [
            "Monthly membership intervals are conservative derived availability, "
            "not exact official daily effective dates",
            "Original snapshot quality/view health proofs are adopted at their original "
            "identities; no new historical matrix",
            "Sparse ST/suspension absence adopts the original snapshot "
            "normalization/quality policy",
        ],
    }
    return panel, provenance


def verify_hs300_binding(binding: Any) -> None:
    """Verify trusted server registration and exact originals, fail closed on stale proofs."""
    manifest = binding.manifest
    if not isinstance(manifest, HS300DatasetManifest):
        raise ValueError("HS300 dataset requires personal-dataset/v2")
    if binding.pit_evidence_path is None:
        raise ValueError("HS300 PIT source-binding original is missing")
    verify_file(binding.panel_path, manifest.panel_sha256)
    verify_file(binding.pit_evidence_path, manifest.pit_evidence_hash)
    proof = json.loads(binding.pit_evidence_path.read_bytes())
    if any(
        proof.get(key) != getattr(manifest, key)
        for key in (
            "kind",
            "snapshot_hash",
            "qlib_view_hash",
            "panel_sha256",
        )
    ):
        raise ValueError("HS300 PIT/panel/source binding disagrees")
    if manifest.kind == "synthetic":
        return
    snapshot_path = getattr(binding, "snapshot_path", None)
    if snapshot_path is None:
        raise ValueError("HS300 canonical snapshot original is missing")
    _snapshot, view, sources = verify_hs300_origins(
        snapshot_path,
        binding.provider_root,
        expected_snapshot_hash=manifest.snapshot_hash,
        expected_view_hash=manifest.qlib_view_hash,
    )
    if (
        sources != manifest.source_files
        or proof.get("source_files") != sources
        or proof.get("adapter_sha256") != sha256_file(Path(__file__))
        or proof.get("warmup_start") != manifest.warmup_start.isoformat()
        or proof.get("end_date") != manifest.end_date.isoformat()
        or proof.get("market_source") != "TUSHARE_PRO"
        or sha256_file(snapshot_path / "manifest.json") != manifest.snapshot_manifest_sha256
        or sha256_file(binding.provider_root / "manifest.json") != manifest.view_manifest_sha256
        or {item.logical_path: item.sha256 for item in view.files} != manifest.qlib_files
    ):
        raise ValueError("HS300 immutable origin or adapter proof changed")


def _hs300_sma20(values: Any) -> Any:
    return values.rolling(20, min_periods=20).mean()


def _hs300_momentum5(values: Any) -> Any:
    return values / values.shift(5) - 1


def _hs300_prior_amount5(values: Any) -> Any:
    return values.shift(1).rolling(5, min_periods=5).mean()


def compile_hs300_daily_signals(panel: pd.DataFrame, prepared: Any) -> dict[str, pd.DataFrame]:
    """Fixed daily amount-confirmed rules; native Qlib shifts these to next session."""
    from quantos.research.personal_qlib import PersonalPITError

    if set(panel.columns) != set(HS300_PANEL_COLUMNS):
        raise ValueError("panel fields must match HS300 daily panel/v1")
    frame: Any = panel.copy()
    frame["datetime"] = pd.to_datetime(frame.pop("trade_date"))
    if (
        frame.empty
        or frame["datetime"].dt.tz is not None
        or frame.duplicated(["datetime", "qlib_id"]).any()
    ):
        raise ValueError("HS300 daily dates/primary keys are invalid")
    for column in ("is_member", "is_st", "is_suspended"):
        if not all(isinstance(item, (bool, np.bool_)) for item in frame[column]):
            raise ValueError("unknown HS300 membership/status is not admissible")
    observed = (
        frame["close"].notna()
        | frame["is_member"]
        | (frame["qlib_id"] == prepared.request.benchmark)
    )
    available: Any = cast(Any, pd).to_datetime(frame.loc[observed, "available_at"], utc=True)
    cutoff = frame.loc[observed, "datetime"].dt.tz_localize("Asia/Shanghai") + pd.Timedelta(
        hours=23, minutes=59
    )
    if (
        available.isna().any()
        or (available > cutoff).any()
        or (available > pd.Timestamp.now(tz="UTC")).any()
    ):
        raise PersonalPITError("PIT hard rejection: HS300 input unavailable at signal cutoff")
    # Reject naive source timestamps even though pandas can localize them implicitly.
    if any(pd.Timestamp(item).tzinfo is None for item in frame.loc[observed, "available_at"]):
        raise PersonalPITError("PIT hard rejection: HS300 availability timezone missing")
    required = (frame["is_member"] & ~frame["is_suspended"]) | (
        frame["qlib_id"] == prepared.request.benchmark
    )
    numeric = frame.loc[required, ["close", "volume", "amount_cny"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        not np.isfinite(numeric).all().all()
        or (numeric["close"] <= 0).any()
        or (numeric[["volume", "amount_cny"]] < 0).any().any()
    ):
        raise PersonalPITError("PIT hard rejection: HS300 price/amount/volume missing or invalid")
    frame = frame.sort_values(["qlib_id", "datetime"], kind="mergesort")
    benchmark = frame[frame["qlib_id"] == prepared.request.benchmark].set_index("datetime")
    dates = sorted(benchmark.index.unique())
    names = sorted(frame.loc[frame["is_member"], "qlib_id"].unique())
    expected_dense = pd.MultiIndex.from_product([dates, names], names=["datetime", "instrument"])
    if not expected_dense.isin(frame.set_index(["datetime", "qlib_id"]).index).all():
        raise PersonalPITError("PIT hard rejection: dense HS300 sessions are incomplete")
    groups = frame.groupby("qlib_id", sort=False)
    frame["sma20"] = groups["close"].transform(_hs300_sma20)
    frame["momentum5"] = groups["close"].transform(_hs300_momentum5)
    frame["amount_ratio"] = frame["amount_cny"] / groups["amount_cny"].transform(
        _hs300_prior_amount5
    )
    benchmark = frame[frame["qlib_id"] == prepared.request.benchmark].set_index("datetime")
    regime = benchmark["close"] > benchmark["sma20"]
    trend = (
        frame["is_member"]
        & ~frame["is_st"]
        & ~frame["is_suspended"]
        & frame["datetime"].map(regime).fillna(False)
        & (frame["close"] > frame["sma20"])
        & (frame["volume"] > 0)
    )
    main = (
        trend
        & (frame["momentum5"] > 0)
        & (frame["amount_ratio"] >= prepared.request.profile.minimum_amount_ratio)
    )
    request = prepared.request
    if request.start_date is None or request.end_date is None:
        raise ValueError("HS300 execution dates are not bound")
    execution = [day for day in dates if request.start_date <= day.date() <= request.end_date]
    positions = {day: index for index, day in enumerate(dates)}
    if not execution or min(positions[day] for day in execution) < 20:
        raise ValueError("HS300 execution needs 20 prior complete session slots")
    signal_dates = [dates[positions[day] - 1] for day in execution]
    expected = pd.MultiIndex.from_product([signal_dates, names], names=["datetime", "instrument"])
    outputs: dict[str, pd.DataFrame] = {}
    for candidate in prepared.candidates:
        if candidate.role == "classic":
            score = (frame["close"] / frame["sma20"] - 1).where(trend)
        elif candidate.role == "main":
            score = frame["momentum5"].where(main)
        else:
            score = pd.Series(
                [
                    int(
                        sha256_bytes(
                            canonical_json_bytes((candidate.seed, row.datetime.date(), row.qlib_id))
                        )[:13],
                        16,
                    )
                    / 16**13
                    for row in frame.itertuples()
                ],
                index=frame.index,
            ).where(main)
        values = pd.Series(
            score.to_numpy(),
            index=pd.MultiIndex.from_arrays(
                [frame["datetime"], frame["qlib_id"]],
                names=["datetime", "instrument"],
            ),
        )
        output = values.reindex(expected).rename("score").to_frame()
        if np.isinf(output["score"]).any():
            raise ValueError("HS300 nonfinite signal")
        outputs[candidate.candidate_id] = output
    return outputs
