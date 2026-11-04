"""Explicit canonical field mapping and Qlib's native amount input adapter.

Qlib 0.9.7 (MIT) still evaluates every expression and performs all native trading.
Old bins are never changed. This provider only supplies the canonical CNY field.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from qlib.data.data import Cal, LocalFeatureProvider  # pyright: ignore[reportMissingTypeStubs]

from quantos.artifacts.store import confined_regular_file, verify_file

CANONICAL_PROFILE = "canonical-personal-fields/v1"
_PRICES = ("open", "high", "low", "close")
_RTOL = _ATOL = 1e-12


def _code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 8
        and value[:2] in {"SH", "SZ"}
        and value[2:].isdigit()
    )


def _boolean(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_))


def _unknown_time(value: Any) -> bool:
    return bool(cast(Any, pd).isna(value)) or pd.Timestamp(value).tzinfo is None


def _days(values: Sequence[Any]) -> list[date]:
    days: list[date] = []
    for value in values:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is not None or stamp != stamp.normalize():
            raise ValueError("CANONICAL_FIELDS_UNKNOWN_OR_INTRADAY_DATE")
        days.append(stamp.date())
    return days


def _times(values: Any, days: list[date]) -> Any:
    if any(_unknown_time(value) for value in values):
        raise ValueError("CANONICAL_FIELDS_UNKNOWN_SOURCE_TIME")
    stamps: Any = cast(Any, pd).to_datetime(values, utc=True, errors="raise", format="mixed")
    cutoffs: Any = pd.DatetimeIndex(days).tz_localize("Asia/Shanghai") + pd.Timedelta(
        hours=23, minutes=59
    )
    if (np.asarray(stamps) > np.asarray(cutoffs.tz_convert("UTC"))).any() or (
        stamps > pd.Timestamp.now(tz="UTC")
    ).any():
        raise ValueError("CANONICAL_FIELDS_FUTURE_SOURCE_TIME")
    return stamps


def _source(binding: Any, table: str, key: str, ids: list[str], days: list[date]) -> Any:
    logical = f"canonical/{table}.parquet"
    expected = binding.manifest.source_files.get(logical)
    if expected is None or binding.snapshot_path is None:
        raise ValueError("CANONICAL_FIELDS_SOURCE_BINDING_MISSING")
    path = confined_regular_file(binding.snapshot_path, logical)
    verify_file(path, expected)
    columns = [key, "trade_date", "available_at"] + (
        ["adjustment_factor"]
        if table == "adjustment_factors"
        else [*_PRICES, "volume_shares", "amount_cny"]
    )
    if not ids:
        return pd.DataFrame(columns=[*columns, "_day", "qlib_id"])
    data: Any = (
        cast(Any, pq)
        .read_table(
            path,
            columns=columns,
            filters=[("trade_date", "in", sorted(set(days))), (key, "in", ids)],
        )
        .to_pandas()
    )
    data["_day"] = _days(list(data.trade_date))
    data["qlib_id"] = data[key].str[-2:] + data[key].str[:6]
    if not data.qlib_id.map(_code).all() or data.duplicated(["_day", "qlib_id"]).any():
        raise ValueError("CANONICAL_FIELDS_DUPLICATE_OR_INVALID_SOURCE_KEY")
    data["available_at"] = _times(data.available_at, list(data._day))
    numeric = (
        ["adjustment_factor"]
        if table == "adjustment_factors"
        else [*_PRICES, "volume_shares", "amount_cny"]
    )
    for column in numeric:
        values: Any = cast(Any, pd).to_numeric(data[column], errors="coerce")
        if not np.isfinite(values.to_numpy(dtype=float)).all() or (
            (values <= 0).any() if column in {*_PRICES, "adjustment_factor"} else (values < 0).any()
        ):
            raise ValueError("CANONICAL_FIELDS_INVALID_VALUE_OR_FACTOR")
        data[column] = values
    return data


def augment_canonical_fields(binding: Any, frame: pd.DataFrame) -> pd.DataFrame:
    """Enrich a verified market panel without replacing its immutable originals.

    Explicit inactive/listed-false or suspended gaps stay null, including their
    absent source clocks. The caller retains member/status availability and must
    check per-field clocks for actual values and required rows.
    """
    profile = getattr(binding, "field_mapping_profile", "native-bins/v1")
    if profile == "native-bins/v1":
        return frame
    if profile != CANONICAL_PROFILE:
        raise ValueError("UNKNOWN_PERSONAL_FIELD_MAPPING_PROFILE")
    if binding.manifest.kind != "market":
        return frame  # Synthetic fields must exist in the fixture, never fabricated.
    required = {
        "trade_date",
        "qlib_id",
        "close",
        "volume",
        "amount_cny",
        "is_member",
        "is_listed",
        "is_suspended",
    }
    if not required <= set(frame.columns) or frame.empty:
        raise ValueError("CANONICAL_FIELDS_PANEL_SHAPE_MISSING")
    out: Any = frame.reset_index(drop=True).copy(deep=True)
    days = _days(list(out.trade_date))
    if not out.qlib_id.map(_code).all():
        raise ValueError("CANONICAL_FIELDS_INVALID_INSTRUMENT_MAPPING")
    for column in ("is_member", "is_listed", "is_suspended"):
        if not out[column].map(_boolean).all():
            raise ValueError("CANONICAL_FIELDS_UNKNOWN_STATUS")
    keys = pd.MultiIndex.from_arrays([days, out.qlib_id], names=["_day", "qlib_id"])
    if keys.has_duplicates:
        raise ValueError("CANONICAL_FIELDS_DUPLICATE_PANEL_KEY")
    benchmarks = set(binding.manifest.benchmarks)
    codes = sorted(set(out.qlib_id))
    stock_ids = [code[2:] + "." + code[:2] for code in codes if code not in benchmarks]
    index_ids = [code[2:] + "." + code[:2] for code in codes if code in benchmarks]
    bars = _source(binding, "bars", "instrument_id", stock_ids, days).set_index(["_day", "qlib_id"])
    factors = _source(binding, "adjustment_factors", "instrument_id", stock_ids, days).set_index(
        ["_day", "qlib_id"]
    )
    index = _source(binding, "benchmark_bars", "benchmark_id", index_ids, days).set_index(
        ["_day", "qlib_id"]
    )
    if not bars.index.isin(factors.index).all():
        raise ValueError("CANONICAL_FIELDS_BAR_FACTOR_MISSING")
    factor_for_bars: Any = factors.adjustment_factor.reindex(bars.index)
    for column in _PRICES:
        bars[column] = bars[column] * factor_for_bars
    bars["volume"] = bars.volume_shares / factor_for_bars
    index["volume"] = index.volume_shares
    observed: Any = pd.concat([bars, index], axis=0).reindex(keys)
    all_factors: Any = pd.concat(
        [
            factors[["adjustment_factor", "available_at"]],
            index[["available_at"]].assign(adjustment_factor=1.0),
        ],
        axis=0,
    ).reindex(keys)
    required_rows: Any = (
        out.is_member & out.is_listed & ~out.is_suspended
    ).to_numpy() | out.qlib_id.isin(benchmarks).to_numpy()
    if (
        observed.loc[required_rows, "close"].isna().any()
        or all_factors.loc[required_rows, "adjustment_factor"].isna().any()
    ):
        raise ValueError("CANONICAL_FIELDS_REQUIRED_SOURCE_MISSING")
    for column in ("close", "volume", "amount_cny"):
        original = cast(Any, pd).to_numeric(out[column], errors="coerce").to_numpy(dtype=float)
        canonical = (
            cast(Any, pd).to_numeric(observed[column], errors="coerce").to_numpy(dtype=float)
        )
        if not np.isclose(original, canonical, rtol=_RTOL, atol=_ATOL, equal_nan=True).all():
            raise ValueError("CANONICAL_FIELDS_PANEL_SOURCE_DISAGREEMENT:" + column)
    for column in ("open", "high", "low", "adjustment_factor"):
        source: Any = all_factors[column] if column == "adjustment_factor" else observed[column]
        if (
            column in out
            and not np.isclose(
                cast(Any, pd).to_numeric(out[column], errors="coerce").to_numpy(dtype=float),
                cast(Any, pd).to_numeric(source, errors="coerce").to_numpy(dtype=float),
                rtol=_RTOL,
                atol=_ATOL,
                equal_nan=True,
            ).all()
        ):
            raise ValueError("CANONICAL_FIELDS_EXISTING_DERIVATIVE_DISAGREEMENT")
        out[column] = source.to_numpy()
    # Index joins are positional back into the original order, including nulls.
    out["available_at_bar"] = list(observed.available_at)
    out["available_at_factor"] = list(all_factors.available_at)
    combined: Any = pd.concat([observed.available_at, all_factors.available_at], axis=1).max(axis=1)
    for column in (*_PRICES, "volume"):
        out[column + "_available_at"] = list(combined.where(observed[column].notna()))
    out["amount_cny_available_at"] = list(observed.available_at)
    out["adjustment_factor_available_at"] = list(all_factors.available_at)
    out.index = frame.index.copy()
    return cast(pd.DataFrame, out)


class CanonicalAmountFeatureProvider(LocalFeatureProvider):  # pyright: ignore[reportUntypedBaseClass]
    """One trusted raw field, with Qlib calendar indexes and native operators."""

    def __init__(
        self,
        *,
        frame: pd.DataFrame,
        calendar_sessions: Sequence[Any],
        remote: bool = False,
        backend: dict[str, Any] | None = None,
    ) -> None:
        if remote:
            raise ValueError("CANONICAL_AMOUNT_OFFLINE_ONLY")
        cast(Any, super()).__init__(remote=False, backend={} if backend is None else backend)
        days = _days(calendar_sessions)
        if not days or days != sorted(set(days)):
            raise ValueError("CANONICAL_AMOUNT_CALENDAR_MUST_BE_COMPLETE_ORDERED_UNIQUE")
        self.calendar_sessions = tuple(days)
        required = {"trade_date", "qlib_id", "amount_cny", "is_suspended"}
        if not required <= set(frame.columns) or frame.empty:
            raise ValueError("CANONICAL_AMOUNT_INPUT_FIELDS_MISSING")
        data: Any = frame[list(required)].copy(deep=True)
        data["_day"] = _days(list(data.trade_date))
        if not data.qlib_id.map(_code).all() or data.duplicated(["_day", "qlib_id"]).any():
            raise ValueError("CANONICAL_AMOUNT_DUPLICATE_OR_UNKNOWN_INSTRUMENT")
        if not data.is_suspended.map(_boolean).all():
            raise ValueError("CANONICAL_AMOUNT_UNKNOWN_SUSPENSION")
        indexes = {day: index for index, day in enumerate(days)}
        if not set(data._day) <= set(indexes):
            raise ValueError("CANONICAL_AMOUNT_SESSION_OUTSIDE_FROZEN_CALENDAR")
        values = cast(Any, pd).to_numeric(data.amount_cny, errors="coerce").to_numpy(dtype=float)
        if np.isinf(values).any() or (values[np.isfinite(values)] < 0).any():
            raise ValueError("CANONICAL_AMOUNT_INVALID_CNY_VALUE")
        data["_value"] = np.where(data.is_suspended, np.nan, values).astype(np.float32)
        if np.isinf(data["_value"].to_numpy()).any():
            raise ValueError("CANONICAL_AMOUNT_BINARY32_OVERFLOW")
        self._amount: dict[str, Any] = {}
        for instrument, group in data.groupby("qlib_id", sort=True):
            self._amount[str(instrument)] = pd.Series(
                group["_value"].to_numpy(copy=True),
                index=pd.Index([indexes[day] for day in group._day], dtype="int64"),
                dtype=np.float32,
            ).sort_index()

    def feature(
        self, instrument: Any, field: Any, start_index: Any, end_index: Any, freq: Any
    ) -> Any:
        if freq != "day":
            raise ValueError("CANONICAL_AMOUNT_DAILY_ONLY")
        if str(field) != "$amount_cny":
            return cast(Any, super()).feature(instrument, field, start_index, end_index, freq)
        if not _code(instrument) or instrument not in self._amount:
            raise ValueError("CANONICAL_AMOUNT_INSTRUMENT_NOT_IN_TRUSTED_FRAME")
        if isinstance(start_index, (bool, np.bool_)) or isinstance(end_index, (bool, np.bool_)):
            raise ValueError("CANONICAL_AMOUNT_INDEX_OUTSIDE_FROZEN_CALENDAR")
        if not isinstance(start_index, Integral) or not isinstance(end_index, Integral):
            raise ValueError("CANONICAL_AMOUNT_INDEX_OUTSIDE_FROZEN_CALENDAR")
        start, end = int(start_index), int(end_index)
        if not 0 <= start <= end < len(self.calendar_sessions):
            raise ValueError("CANONICAL_AMOUNT_INDEX_OUTSIDE_FROZEN_CALENDAR")
        native: Any = cast(Any, Cal).calendar(freq="day", future=False)
        if not np.array_equal(
            np.asarray(native, dtype="datetime64[ns]"),
            np.asarray(self.calendar_sessions, dtype="datetime64[ns]"),
        ):
            raise ValueError("CANONICAL_AMOUNT_NATIVE_CALENDAR_BINDING_CHANGED")
        return self._amount[instrument].reindex(pd.RangeIndex(start, end + 1)).copy()
