"""Offline construction of immutable canonical snapshots from the synthetic fixture."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.refs import DataSnapshotRef
from quantos.contracts.snapshot import (
    DEFAULT_NORMALIZER_VERSION,
    DEFAULT_SYNTHETIC_ENDPOINTS,
    ColumnManifest,
    DataQualityPolicy,
    DataQualityReport,
    DataQualityRule,
    DataSnapshotManifest,
    QualityGateResult,
    SnapshotBuildSpec,
    SnapshotDiff,
    SnapshotFileManifest,
    SnapshotSourceKind,
)
from quantos.contracts.status import ReasonCode

SHANGHAI = ZoneInfo("Asia/Shanghai")
RAW_FILES: Mapping[str, str] = {
    "stock_basic": "stock_basic.csv",
    "trade_cal": "trade_cal.csv",
    "daily": "bars.csv",
    "adj_factor": "adj_factor.csv",
    "index_daily": "index_daily.csv",
    "index_weight": "index_weight.csv",
    "stock_st": "stock_st.csv",
    "suspend_d": "suspend_d.csv",
    "stk_limit": "stk_limit.csv",
}


class SnapshotBuildError(RuntimeError):
    """Raised when a snapshot cannot be safely constructed or published."""

    def __init__(
        self,
        reason_code: ReasonCode,
        message: str,
        *,
        quality_report: DataQualityReport | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.quality_report = quality_report


@dataclass(frozen=True)
class SnapshotBuildResult:
    reference: DataSnapshotRef
    manifest: DataSnapshotManifest
    quality_report: DataQualityReport
    path: Path


def _read_csv(path: Path, required_columns: Sequence[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(required_columns):
                raise SnapshotBuildError(
                    ReasonCode.SCHEMA_INVALID,
                    f"{path.name} columns do not match the locked endpoint contract",
                )
            return [dict(row) for row in reader]
    except OSError as error:
        raise SnapshotBuildError(
            ReasonCode.SOURCE_INCOMPLETE, f"cannot read required source file: {path.name}"
        ) from error


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise SnapshotBuildError(ReasonCode.SCHEMA_INVALID, "invalid Tushare trade_date") from error


def _parse_float(value: str, field: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise SnapshotBuildError(
            ReasonCode.SCHEMA_INVALID, f"invalid numeric field: {field}"
        ) from error
    if not (-float("inf") < number < float("inf")):
        raise SnapshotBuildError(ReasonCode.SCHEMA_INVALID, f"non-finite numeric field: {field}")
    return number


def _volume_shares(value: str) -> int:
    try:
        shares = Decimal(value) * 100
    except InvalidOperation as error:
        raise SnapshotBuildError(ReasonCode.SCHEMA_INVALID, "invalid vol_hands") from error
    if shares != shares.to_integral_value():
        raise SnapshotBuildError(
            ReasonCode.SCHEMA_INVALID, "vol_hands does not map to whole shares"
        )
    return int(shares)


def _event_time(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time(15, 0), tzinfo=SHANGHAI)


def _available_at(trade_date: date) -> datetime:
    return datetime.combine(trade_date, time(15, 30), tzinfo=SHANGHAI)


def _temporal_payload(
    event_time: datetime,
    available_at: datetime,
    policy_id: str,
) -> dict[str, object]:
    return {
        "event_time": event_time,
        "known_at": available_at,
        "available_at": available_at,
        "observed_at": available_at,
        "availability_basis": "CONSERVATIVE_DERIVED",
        "availability_policy_id": policy_id,
    }


def _table(rows: Sequence[Mapping[str, object]], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist([dict(row) for row in rows], schema=schema)


def write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(  # pyright: ignore[reportUnknownMemberType]
        table,
        path,
        compression="zstd",
        data_page_version="1.0",
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )


def _columns(schema: pa.Schema) -> tuple[ColumnManifest, ...]:
    return tuple(
        ColumnManifest(
            name=field.name,
            arrow_type=str(field.type),  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
            nullable=field.nullable,
        )
        for field in schema  # pyright: ignore[reportUnknownVariableType]
    )


def _date_range(table: pa.Table) -> tuple[date | None, date | None]:
    if table.num_rows == 0 or "trade_date" not in table.column_names:
        return None, None
    values = cast(list[object | None], table["trade_date"].to_pylist())
    present: list[date] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, datetime):
            present.append(value.date())
        elif isinstance(value, date):
            present.append(value)
        elif isinstance(value, str):
            present.append(_parse_date(value))
        else:
            raise SnapshotBuildError(
                ReasonCode.SCHEMA_INVALID, "trade_date cannot be summarized in manifest"
            )
    return (min(present), max(present)) if present else (None, None)


def table_manifest(path: Path, root: Path, name: str, table: pa.Table) -> SnapshotFileManifest:
    min_date, max_date = _date_range(table)
    return SnapshotFileManifest(
        logical_path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        media_type="application/vnd.apache.parquet",
        table_name=name,
        row_count=table.num_rows,
        min_date=min_date,
        max_date=max_date,
        columns=_columns(table.schema),
    )


def plain_manifest(path: Path, root: Path, media_type: str) -> SnapshotFileManifest:
    return SnapshotFileManifest(
        logical_path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        media_type=media_type,
    )


def _schemas() -> dict[str, pa.Schema]:
    timestamp = pa.timestamp("us", tz="Asia/Shanghai")
    temporal = [
        pa.field("event_time", timestamp, nullable=False),
        pa.field("known_at", timestamp, nullable=False),
        pa.field("available_at", timestamp, nullable=False),
        pa.field("observed_at", timestamp, nullable=False),
        pa.field("availability_basis", pa.string(), nullable=False),
        pa.field("availability_policy_id", pa.string(), nullable=False),
    ]
    identity = [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
    ]
    return {
        "instruments": pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("symbol", pa.string(), nullable=False),
                pa.field("name", pa.string(), nullable=False),
                pa.field("exchange", pa.string(), nullable=False),
                pa.field("list_status", pa.string(), nullable=False),
                pa.field("list_date", pa.date32(), nullable=False),
                pa.field("delist_date", pa.date32(), nullable=True),
            ]
        ),
        "calendar": pa.schema(
            [
                pa.field("exchange", pa.string(), nullable=False),
                pa.field("trade_date", pa.date32(), nullable=False),
                pa.field("is_open", pa.bool_(), nullable=False),
                pa.field("pretrade_date", pa.date32(), nullable=False),
            ]
        ),
        "bars": pa.schema(
            [
                *identity,
                pa.field("open", pa.float64(), nullable=False),
                pa.field("high", pa.float64(), nullable=False),
                pa.field("low", pa.float64(), nullable=False),
                pa.field("close", pa.float64(), nullable=False),
                pa.field("pre_close", pa.float64(), nullable=False),
                pa.field("volume_shares", pa.int64(), nullable=False),
                pa.field("amount_cny", pa.float64(), nullable=False),
                *temporal,
            ]
        ),
        "adjustment_factors": pa.schema(
            [
                *identity,
                pa.field("adjustment_factor", pa.float64(), nullable=False),
                *temporal,
            ]
        ),
        "benchmark_bars": pa.schema(
            [
                pa.field("benchmark_id", pa.string(), nullable=False),
                pa.field("trade_date", pa.date32(), nullable=False),
                pa.field("open", pa.float64(), nullable=False),
                pa.field("high", pa.float64(), nullable=False),
                pa.field("low", pa.float64(), nullable=False),
                pa.field("close", pa.float64(), nullable=False),
                pa.field("pre_close", pa.float64(), nullable=False),
                pa.field("volume_shares", pa.int64(), nullable=False),
                pa.field("amount_cny", pa.float64(), nullable=False),
                *temporal,
            ]
        ),
        "index_membership": pa.schema(
            [
                pa.field("index_id", pa.string(), nullable=False),
                *identity,
                pa.field("effective_from", pa.date32(), nullable=False),
                pa.field("effective_to", pa.date32(), nullable=False),
                pa.field("available_from", pa.date32(), nullable=False),
                pa.field("weight_percent", pa.float64(), nullable=False),
                *temporal,
            ]
        ),
        "st_status": pa.schema(
            [*identity, pa.field("type", pa.string(), nullable=False), *temporal]
        ),
        "suspensions": pa.schema(
            [
                *identity,
                pa.field("suspend_type", pa.string(), nullable=False),
                pa.field("suspend_timing", pa.string(), nullable=True),
                *temporal,
            ]
        ),
        "price_limits": pa.schema(
            [
                *identity,
                pa.field("pre_close", pa.float64(), nullable=False),
                pa.field("up_limit", pa.float64(), nullable=False),
                pa.field("down_limit", pa.float64(), nullable=False),
                *temporal,
            ]
        ),
    }


def normalize_tushare_tables(
    raw: Mapping[str, list[dict[str, str]]], spec: SnapshotBuildSpec
) -> dict[str, pa.Table]:
    """Normalize provider-shaped rows shared by synthetic and future live acquisition."""

    schemas = _schemas()
    bars: list[dict[str, object]] = []
    for row in raw["daily"]:
        trade_date = _parse_date(row["trade_date"])
        bars.append(
            {
                "instrument_id": row["ts_code"],
                "trade_date": trade_date,
                "open": _parse_float(row["open"], "open"),
                "high": _parse_float(row["high"], "high"),
                "low": _parse_float(row["low"], "low"),
                "close": _parse_float(row["close"], "close"),
                "pre_close": _parse_float(row["pre_close"], "pre_close"),
                "volume_shares": _volume_shares(row["vol"]),
                "amount_cny": _parse_float(row["amount"], "amount") * 1000,
                **_temporal_payload(
                    _event_time(trade_date),
                    _available_at(trade_date),
                    spec.availability_policy_id,
                ),
            }
        )

    factors: list[dict[str, object]] = []
    for row in raw["adj_factor"]:
        trade_date = _parse_date(row["trade_date"])
        factors.append(
            {
                "instrument_id": row["ts_code"],
                "trade_date": trade_date,
                "adjustment_factor": _parse_float(row["adj_factor"], "adj_factor"),
                **_temporal_payload(
                    _event_time(trade_date),
                    _available_at(trade_date),
                    spec.availability_policy_id,
                ),
            }
        )

    instruments: list[dict[str, object]] = []
    for row in raw["stock_basic"]:
        instruments.append(
            {
                "instrument_id": row["ts_code"],
                "symbol": row["symbol"],
                "name": row["name"],
                "exchange": row["exchange"],
                "list_status": row["list_status"],
                "list_date": _parse_date(row["list_date"]),
                "delist_date": _parse_date(row["delist_date"]) if row["delist_date"] else None,
            }
        )

    calendar_rows: list[dict[str, object]] = []
    for row in raw["trade_cal"]:
        is_open = row["is_open"] == "1"
        if row["is_open"] not in {"0", "1"}:
            raise SnapshotBuildError(ReasonCode.SCHEMA_INVALID, "trade_cal is_open must be 0 or 1")
        calendar_rows.append(
            {
                "exchange": row["exchange"],
                "trade_date": _parse_date(row["cal_date"]),
                "is_open": is_open,
                "pretrade_date": _parse_date(row["pretrade_date"]),
            }
        )
    open_calendar = sorted(
        {cast(date, row["trade_date"]) for row in calendar_rows if row["is_open"] is True}
    )

    benchmarks: list[dict[str, object]] = []
    for row in raw["index_daily"]:
        trade_date = _parse_date(row["trade_date"])
        benchmarks.append(
            {
                "benchmark_id": row["ts_code"],
                "trade_date": trade_date,
                "open": _parse_float(row["open"], "index open"),
                "high": _parse_float(row["high"], "index high"),
                "low": _parse_float(row["low"], "index low"),
                "close": _parse_float(row["close"], "index close"),
                "pre_close": _parse_float(row["pre_close"], "index pre_close"),
                "volume_shares": _volume_shares(row["vol"]),
                "amount_cny": _parse_float(row["amount"], "index amount") * 1000,
                **_temporal_payload(
                    _event_time(trade_date),
                    _available_at(trade_date),
                    spec.availability_policy_id,
                ),
            }
        )

    memberships: list[dict[str, object]] = []
    membership_dates = sorted({_parse_date(row["trade_date"]) for row in raw["index_weight"]})
    effective_to_by_date: dict[date, date] = {}
    for position, effective_from in enumerate(membership_dates):
        if position + 1 < len(membership_dates):
            next_effective = membership_dates[position + 1]
            prior_sessions = [
                session for session in open_calendar if effective_from <= session < next_effective
            ]
            if not prior_sessions:
                raise SnapshotBuildError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "index membership snapshots do not resolve to a bounded trading interval",
                )
            effective_to_by_date[effective_from] = prior_sessions[-1]
        else:
            final_sessions = [
                session for session in open_calendar if effective_from <= session <= spec.end_date
            ]
            effective_to_by_date[effective_from] = (
                final_sessions[-1] if final_sessions else spec.end_date
            )
    for row in raw["index_weight"]:
        effective_from = _parse_date(row["trade_date"])
        future_sessions = [session for session in open_calendar if session > effective_from]
        available_from = (
            future_sessions[0] if future_sessions else effective_from + timedelta(days=1)
        )
        memberships.append(
            {
                "index_id": row["index_code"],
                "instrument_id": row["con_code"],
                "trade_date": effective_from,
                "effective_from": effective_from,
                "effective_to": effective_to_by_date[effective_from],
                "available_from": available_from,
                "weight_percent": _parse_float(row["weight"], "weight"),
                **_temporal_payload(
                    _event_time(effective_from),
                    datetime.combine(available_from, time(9, 0), tzinfo=SHANGHAI),
                    spec.availability_policy_id,
                ),
            }
        )

    def sparse(endpoint: str, source_name: str, canonical_name: str) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for row in raw[endpoint]:
            trade_date = _parse_date(row["trade_date"])
            normalized.append(
                {
                    "instrument_id": row["ts_code"],
                    "trade_date": trade_date,
                    canonical_name: row[source_name],
                    **_temporal_payload(
                        _event_time(trade_date),
                        _available_at(trade_date),
                        spec.availability_policy_id,
                    ),
                }
            )
        return normalized

    limits: list[dict[str, object]] = []
    for row in raw["stk_limit"]:
        trade_date = _parse_date(row["trade_date"])
        limits.append(
            {
                "instrument_id": row["ts_code"],
                "trade_date": trade_date,
                "pre_close": _parse_float(row["pre_close"], "limit pre_close"),
                "up_limit": _parse_float(row["up_limit"], "up_limit"),
                "down_limit": _parse_float(row["down_limit"], "down_limit"),
                **_temporal_payload(
                    _event_time(trade_date),
                    _available_at(trade_date),
                    spec.availability_policy_id,
                ),
            }
        )

    return {
        "instruments": _table(instruments, schemas["instruments"]),
        "calendar": _table(calendar_rows, schemas["calendar"]),
        "bars": _table(bars, schemas["bars"]),
        "adjustment_factors": _table(factors, schemas["adjustment_factors"]),
        "benchmark_bars": _table(benchmarks, schemas["benchmark_bars"]),
        "index_membership": _table(memberships, schemas["index_membership"]),
        "st_status": _table(sparse("stock_st", "type", "type"), schemas["st_status"]),
        "suspensions": _table(
            [
                {
                    **item,
                    "suspend_timing": raw_row["suspend_timing"] or None,
                }
                for item, raw_row in zip(
                    sparse("suspend_d", "suspend_type", "suspend_type"),
                    raw["suspend_d"],
                    strict=True,
                )
            ],
            schemas["suspensions"],
        ),
        "price_limits": _table(limits, schemas["price_limits"]),
    }


class _Gates:
    def __init__(self) -> None:
        self.results: list[QualityGateResult] = []

    def check(
        self,
        rule: DataQualityRule,
        condition: bool,
        checked_rows: int,
        detail: str,
        reason: ReasonCode = ReasonCode.SCHEMA_INVALID,
    ) -> None:
        self.results.append(
            QualityGateResult(
                rule=rule,
                passed=condition,
                checked_rows=checked_rows,
                reason_code=None if condition else reason,
                detail=detail,
            )
        )


def _unique(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> bool:
    values = [tuple(row[key] for key in keys) for row in rows]
    return len(values) == len(set(values))


def evaluate_snapshot_quality(
    raw: Mapping[str, list[dict[str, str]]],
    tables: Mapping[str, pa.Table],
    spec: SnapshotBuildSpec,
    policy: DataQualityPolicy,
) -> DataQualityReport:
    rows = {name: table.to_pylist() for name, table in tables.items()}
    gates = _Gates()
    total_rows = sum(len(value) for value in rows.values())
    gates.check(DataQualityRule.SCHEMA, True, total_rows, "all locked Arrow schemas constructed")

    primary_keys = {
        "instruments": ("instrument_id",),
        "calendar": ("exchange", "trade_date"),
        "bars": ("instrument_id", "trade_date"),
        "adjustment_factors": ("instrument_id", "trade_date"),
        "benchmark_bars": ("benchmark_id", "trade_date"),
        "index_membership": ("index_id", "instrument_id", "trade_date"),
        "st_status": ("instrument_id", "trade_date"),
        "suspensions": ("instrument_id", "trade_date"),
        "price_limits": ("instrument_id", "trade_date"),
    }
    unique = all(_unique(rows[name], keys) for name, keys in primary_keys.items())
    gates.check(
        DataQualityRule.PRIMARY_KEY,
        unique,
        sum(len(rows[name]) for name in primary_keys),
        "endpoint primary keys are unique",
    )

    dated = [
        row
        for name, table_rows in rows.items()
        if name != "instruments"
        for row in table_rows
        if "trade_date" in row
    ]
    in_range = all(
        spec.start_date <= cast(date, row["trade_date"]) <= spec.end_date for row in dated
    )
    gates.check(DataQualityRule.DATE_RANGE, in_range, len(dated), "all records are in build range")

    temporal = [row for table_rows in rows.values() for row in table_rows if "event_time" in row]
    temporal_order = all(
        cast(datetime, row["event_time"])
        <= cast(datetime, row["known_at"])
        <= cast(datetime, row["available_at"])
        and cast(datetime, row["event_time"]) <= cast(datetime, row["observed_at"])
        and row["availability_basis"] != "UNKNOWN"
        and bool(row["availability_policy_id"])
        for row in temporal
    )
    gates.check(
        DataQualityRule.TEMPORAL_ORDER,
        temporal_order,
        len(temporal),
        "temporal order and availability evidence are valid",
        ReasonCode.LOOK_AHEAD,
    )

    bars = rows["bars"]
    benchmark_bars = rows["benchmark_bars"]
    all_bars = [*bars, *benchmark_bars]
    ohlc_valid = all(
        cast(float, row["low"])
        <= min(cast(float, row["open"]), cast(float, row["close"]))
        <= max(cast(float, row["open"]), cast(float, row["close"]))
        <= cast(float, row["high"])
        and cast(float, row["pre_close"]) > 0
        for row in all_bars
    )
    gates.check(DataQualityRule.OHLC, ohlc_valid, len(all_bars), "OHLC bounds are valid")
    nonnegative = all(
        cast(int, row["volume_shares"]) >= 0 and cast(float, row["amount_cny"]) >= 0
        for row in all_bars
    )
    gates.check(
        DataQualityRule.NONNEGATIVE_TRADING_VALUES,
        nonnegative,
        len(all_bars),
        "volume and amount are nonnegative",
    )

    factors = rows["adjustment_factors"]
    positive = all(cast(float, row["adjustment_factor"]) > 0 for row in factors)
    gates.check(
        DataQualityRule.POSITIVE_ADJUSTMENT_FACTOR,
        positive,
        len(factors),
        "adjustment factors are positive",
    )

    memberships = rows["index_membership"]
    totals: dict[tuple[str, date], float] = {}
    for row in memberships:
        key = (cast(str, row["index_id"]), cast(date, row["trade_date"]))
        totals[key] = totals.get(key, 0.0) + cast(float, row["weight_percent"])
    weights_ok = bool(totals) and all(
        abs(total - policy.index_weight_total) <= policy.index_weight_absolute_tolerance
        for total in totals.values()
    )
    gates.check(
        DataQualityRule.INDEX_WEIGHT_TOTAL,
        weights_ok,
        len(memberships),
        "index weights sum to policy target",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    membership_intervals: dict[tuple[str, str], list[tuple[date, date]]] = {}
    for row in memberships:
        key = (cast(str, row["index_id"]), cast(str, row["instrument_id"]))
        membership_intervals.setdefault(key, []).append(
            (cast(date, row["effective_from"]), cast(date, row["effective_to"]))
        )
    intervals_valid = True
    for intervals in membership_intervals.values():
        ordered = sorted(intervals)
        intervals_valid = intervals_valid and all(start <= end for start, end in ordered)
        intervals_valid = intervals_valid and all(
            left_end < right_start for (_, left_end), (right_start, _) in pairwise(ordered)
        )
    gates.check(
        DataQualityRule.MEMBERSHIP_INTERVAL,
        bool(membership_intervals) and intervals_valid,
        len(memberships),
        "membership intervals are ordered, bounded, and non-overlapping",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    statuses_valid = all(
        cast(str, row["type"]) in policy.allowed_st_types for row in rows["st_status"]
    ) and all(
        cast(str, row["suspend_type"]) in policy.allowed_suspend_types
        for row in rows["suspensions"]
    )
    gates.check(
        DataQualityRule.SPARSE_STATUS_SEMANTICS,
        statuses_valid,
        len(rows["st_status"]) + len(rows["suspensions"]),
        "sparse status rows use endpoint-specific allowed values",
    )

    limits_valid = all(
        0
        < cast(float, row["down_limit"])
        < cast(float, row["pre_close"])
        < cast(float, row["up_limit"])
        for row in rows["price_limits"]
    )
    gates.check(
        DataQualityRule.PRICE_LIMIT_BOUNDS,
        limits_valid,
        len(rows["price_limits"]),
        "price-limit bounds surround a positive pre-close",
    )

    instruments = {cast(str, row["instrument_id"]) for row in rows["instruments"]}
    instrument_rows = {cast(str, row["instrument_id"]): row for row in rows["instruments"]}
    referenced = [
        cast(str, row["instrument_id"])
        for name in (
            "bars",
            "adjustment_factors",
            "index_membership",
            "st_status",
            "suspensions",
            "price_limits",
        )
        for row in rows[name]
    ]
    gates.check(
        DataQualityRule.INSTRUMENT_REFERENCE,
        all(item in instruments for item in referenced),
        len(referenced),
        "all table instruments resolve to instruments.parquet",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    lifecycle_status_valid = all(
        cast(str, row["list_status"]) in {"L", "D", "P"}
        and (row["list_status"] != "D" or row["delist_date"] is not None)
        and (row["list_status"] != "L" or row["delist_date"] is None)
        for row in rows["instruments"]
    )
    lifecycle_dates_valid = all(
        cast(str, row["instrument_id"]) in instrument_rows
        and cast(date, instrument_rows[cast(str, row["instrument_id"])]["list_date"])
        <= cast(date, row["trade_date"])
        and (
            instrument_rows[cast(str, row["instrument_id"])]["delist_date"] is None
            or cast(date, row["trade_date"])
            <= cast(
                date,
                instrument_rows[cast(str, row["instrument_id"])]["delist_date"],
            )
        )
        for name in (
            "bars",
            "adjustment_factors",
            "index_membership",
            "st_status",
            "suspensions",
            "price_limits",
        )
        for row in rows[name]
    )
    gates.check(
        DataQualityRule.INSTRUMENT_LIFECYCLE,
        lifecycle_status_valid and lifecycle_dates_valid,
        len(rows["instruments"]) + len(referenced),
        "market rows fall within explicit listing and delisting lifecycles",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    calendar_sessions = {
        (cast(str, row["exchange"]), cast(date, row["trade_date"]))
        for row in rows["calendar"]
        if row["is_open"] is True
    }
    instrument_exchange = {
        cast(str, row["instrument_id"]): cast(str, row["exchange"]) for row in rows["instruments"]
    }

    def market_exchange(row: Mapping[str, object]) -> str | None:
        instrument_id = row.get("instrument_id")
        if isinstance(instrument_id, str):
            return instrument_exchange.get(instrument_id)
        benchmark_id = row.get("benchmark_id")
        if isinstance(benchmark_id, str):
            return "SSE" if benchmark_id.endswith(".SH") else "SZSE"
        return None

    market_rows = [
        row
        for name in (
            "bars",
            "adjustment_factors",
            "benchmark_bars",
            "st_status",
            "suspensions",
            "price_limits",
        )
        for row in rows[name]
    ]
    membership_calendar_valid = all(
        (
            "SSE" if cast(str, row["index_id"]).endswith(".SH") else "SZSE",
            cast(date, row["trade_date"]),
        )
        in calendar_sessions
        for row in rows["index_membership"]
    )
    gates.check(
        DataQualityRule.CALENDAR_REFERENCE,
        membership_calendar_valid
        and all(
            (market_exchange(row), cast(date, row["trade_date"])) in calendar_sessions
            for row in market_rows
        ),
        len(market_rows) + len(rows["index_membership"]),
        "all market records resolve to an open session on the owning exchange",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    benchmark_ids = {cast(str, row["benchmark_id"]) for row in benchmark_bars}
    gates.check(
        DataQualityRule.INSTRUMENT_REFERENCE,
        all(cast(str, row["index_id"]) in benchmark_ids for row in memberships),
        len(memberships),
        "all index memberships resolve to benchmark_bars.parquet",
        ReasonCode.SOURCE_INCOMPLETE,
    )

    bar_keys = {(row["instrument_id"], row["trade_date"]) for row in bars}
    factor_keys = {(row["instrument_id"], row["trade_date"]) for row in factors}
    reconciliation = (
        len(raw["stock_basic"]) == len(rows["instruments"])
        and len(raw["trade_cal"]) == len(rows["calendar"])
        and len(raw["daily"]) == len(bars)
        and len(raw["adj_factor"]) == len(factors)
        and len(raw["index_daily"]) == len(benchmark_bars)
        and len(raw["index_weight"]) == len(memberships)
        and len(raw["stock_st"]) == len(rows["st_status"])
        and len(raw["suspend_d"]) == len(rows["suspensions"])
        and len(raw["stk_limit"]) == len(rows["price_limits"])
        and bar_keys == factor_keys
    )
    gates.check(
        DataQualityRule.RAW_CANONICAL_RECONCILIATION,
        reconciliation,
        sum(len(value) for value in raw.values()),
        "raw endpoint rows reconcile to canonical rows",
        ReasonCode.SOURCE_INCOMPLETE,
    )
    results = tuple(gates.results)
    return DataQualityReport(
        policy_hash=policy.content_hash,
        passed=all(result.passed for result in results),
        gates=results,
    )


def _request_ledger(raw: Mapping[str, list[dict[str, str]]], fixture_root: Path) -> pa.Table:
    rows = [
        {
            "endpoint": endpoint,
            "request_sequence": sequence,
            "response_row_count": len(raw[endpoint]),
            "response_sha256": sha256_file(fixture_root / RAW_FILES[endpoint]),
            "network_used": False,
        }
        for sequence, endpoint in enumerate(sorted(RAW_FILES), start=1)
    ]
    schema = pa.schema(
        [
            pa.field("endpoint", pa.string(), nullable=False),
            pa.field("request_sequence", pa.int32(), nullable=False),
            pa.field("response_row_count", pa.int64(), nullable=False),
            pa.field("response_sha256", pa.string(), nullable=False),
            pa.field("network_used", pa.bool_(), nullable=False),
        ]
    )
    return _table(rows, schema)


def _load_fixture(fixture_root: Path) -> tuple[SnapshotBuildSpec, dict[str, list[dict[str, str]]]]:
    try:
        fixture_manifest = json.loads((fixture_root / "manifest.json").read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotBuildError(
            ReasonCode.SOURCE_INCOMPLETE, "synthetic fixture manifest is unavailable or invalid"
        ) from error
    if fixture_manifest.get("synthetic") is not True:
        raise SnapshotBuildError(
            ReasonCode.SCHEMA_INVALID, "fixture must explicitly declare synthetic=true"
        )
    date_range = fixture_manifest.get("date_range")
    if not isinstance(date_range, dict):
        raise SnapshotBuildError(ReasonCode.SCHEMA_INVALID, "fixture date_range is invalid")
    spec = SnapshotBuildSpec(
        dataset_id=cast(str, fixture_manifest["dataset_id"]),
        source_kind=SnapshotSourceKind.SYNTHETIC_FIXTURE,
        provider="synthetic-tushare-shape",
        start_date=date.fromisoformat(cast(str, date_range["start"])),
        end_date=date.fromisoformat(cast(str, date_range["end"])),
        required_endpoints=DEFAULT_SYNTHETIC_ENDPOINTS,
        normalizer_version=DEFAULT_NORMALIZER_VERSION,
        availability_policy_id="synthetic-close-plus-30m/v1",
    )
    contracts = {
        "stock_basic": (
            "ts_code",
            "symbol",
            "name",
            "exchange",
            "list_status",
            "list_date",
            "delist_date",
        ),
        "trade_cal": ("exchange", "cal_date", "is_open", "pretrade_date"),
        "daily": (
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
        ),
        "adj_factor": ("ts_code", "trade_date", "adj_factor"),
        "index_daily": (
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
        ),
        "index_weight": ("index_code", "con_code", "trade_date", "weight"),
        "stock_st": ("ts_code", "trade_date", "type"),
        "suspend_d": ("ts_code", "trade_date", "suspend_type", "suspend_timing"),
        "stk_limit": ("ts_code", "trade_date", "pre_close", "up_limit", "down_limit"),
    }
    raw = {
        endpoint: _read_csv(fixture_root / RAW_FILES[endpoint], columns)
        for endpoint, columns in contracts.items()
    }
    return spec, raw


def verify_snapshot(path: Path) -> DataSnapshotManifest:
    """Validate a published manifest and every immutable file it references."""

    try:
        payload = json.loads((path / "manifest.json").read_bytes())
        manifest = DataSnapshotManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SnapshotBuildError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH, "snapshot manifest is invalid"
        ) from error
    if path.name != f"sha256-{manifest.snapshot_hash}":
        raise SnapshotBuildError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH, "snapshot directory does not match snapshot hash"
        )
    expected_paths = {item.logical_path for item in manifest.files}
    actual_paths = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise SnapshotBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "snapshot file set does not match manifest"
        )
    for item in manifest.files:
        try:
            verify_file(path / item.logical_path, item.sha256)
        except (OSError, ValueError, ArtifactIntegrityError) as error:
            raise SnapshotBuildError(
                ReasonCode.ARTIFACT_CORRUPTED,
                f"snapshot file failed verification: {item.logical_path}",
            ) from error
    return manifest


def diff_snapshots(left: DataSnapshotManifest, right: DataSnapshotManifest) -> SnapshotDiff:
    """Compare manifest hashes, schemas, and row counts without scanning Parquet rows."""

    left_files = {item.logical_path: item for item in left.files}
    right_files = {item.logical_path: item for item in right.files}
    all_paths = sorted(set(left_files) | set(right_files))
    changed_paths = tuple(
        path
        for path in all_paths
        if path not in left_files
        or path not in right_files
        or left_files[path].sha256 != right_files[path].sha256
    )
    common_tables = sorted(
        path
        for path in set(left_files) & set(right_files)
        if left_files[path].table_name is not None and right_files[path].table_name is not None
    )
    row_changes = tuple(
        f"{path}:{left_files[path].row_count}->{right_files[path].row_count}"
        for path in common_tables
        if left_files[path].row_count != right_files[path].row_count
    )
    schema_changes = tuple(
        path for path in common_tables if left_files[path].columns != right_files[path].columns
    )
    return SnapshotDiff(
        left_snapshot_hash=left.snapshot_hash,
        right_snapshot_hash=right.snapshot_hash,
        changed_paths=changed_paths,
        row_count_changes=row_changes,
        schema_changes=schema_changes,
        unchanged_file_count=len(all_paths) - len(changed_paths),
        changed_file_count=len(changed_paths),
    )


class SyntheticSnapshotBuilder:
    """Normalize the redistributable Tushare-shaped fixture without network access."""

    def __init__(self, policy: DataQualityPolicy | None = None) -> None:
        self._policy = policy or DataQualityPolicy(policy_id="default-synthetic-dq/v1")

    def build(self, fixture_root: Path, output_root: Path) -> SnapshotBuildResult:
        spec, raw = _load_fixture(fixture_root)
        tables = normalize_tushare_tables(raw, spec)
        report = evaluate_snapshot_quality(raw, tables, spec, self._policy)
        if not report.passed:
            reason = next(
                gate.reason_code
                for gate in report.gates
                if not gate.passed and gate.reason_code is not None
            )
            raise SnapshotBuildError(
                reason,
                "snapshot failed data-quality gates",
                quality_report=report,
            )

        output_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".snapshot-staging-", dir=output_root))
        try:
            files: list[SnapshotFileManifest] = []
            raw_root = staging / "raw"
            raw_root.mkdir()
            for filename in RAW_FILES.values():
                target = raw_root / filename
                shutil.copyfile(fixture_root / filename, target)
                files.append(plain_manifest(target, staging, "text/csv"))

            build_path = staging / "snapshot-build.json"
            atomic_write_bytes(build_path, spec.canonical_bytes())
            files.append(plain_manifest(build_path, staging, "application/json"))
            quality_path = staging / "quality-report.json"
            atomic_write_bytes(quality_path, report.canonical_bytes())
            files.append(plain_manifest(quality_path, staging, "application/json"))

            ledger = _request_ledger(raw, fixture_root)
            ledger_path = staging / "request-ledger.parquet"
            write_parquet(ledger, ledger_path)
            files.append(table_manifest(ledger_path, staging, "request_ledger", ledger))

            canonical_root = staging / "canonical"
            for name in sorted(tables):
                table = tables[name]
                path = canonical_root / f"{name}.parquet"
                write_parquet(table, path)
                files.append(table_manifest(path, staging, name, table))

            manifest = DataSnapshotManifest.create(
                dataset_id=spec.dataset_id,
                source_kind=spec.source_kind,
                provider=spec.provider,
                start_date=spec.start_date,
                end_date=spec.end_date,
                build_spec_hash=spec.content_hash,
                quality_policy_hash=self._policy.content_hash,
                quality_report_hash=report.content_hash,
                normalizer_version=spec.normalizer_version,
                files=tuple(sorted(files, key=lambda item: item.logical_path)),
                limitations=("SYNTHETIC_DATA_NOT_LIVE_EVIDENCE", "SINGLE_SOURCE_NON_VINTAGE"),
                created_at=datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )

            destination = output_root / f"sha256-{manifest.snapshot_hash}"
            if destination.exists():
                existing = verify_snapshot(destination)
                if existing.snapshot_hash != manifest.snapshot_hash:
                    raise ArtifactConflictError(
                        f"immutable destination already exists: {destination}"
                    )
                shutil.rmtree(staging)
                staging = destination
                manifest = existing
            else:
                publish_directory(staging, destination)
                staging = destination

            verified = verify_snapshot(staging)
            size_bytes = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
            reference = DataSnapshotRef(
                sha256=verified.snapshot_hash,
                size_bytes=size_bytes,
                media_type="application/vnd.quantos.snapshot+directory",
                logical_path=f"data/snapshots/{staging.name}",
            )
            return SnapshotBuildResult(reference, verified, report, staging)
        finally:
            if staging.exists() and staging.name.startswith(".snapshot-staging-"):
                shutil.rmtree(staging)
