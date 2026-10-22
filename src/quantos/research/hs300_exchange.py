"""Thin open-time constraint adapter over Qlib's unchanged Exchange implementation.

No order generation, matching, cash or position accounting is implemented here.
The original cache records close-time limit flags; the successor scenario needs
the canonical day's actual price limits applied to its open execution price.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from qlib.backtest.exchange import Exchange

from quantos.artifacts.store import verify_file


@lru_cache(maxsize=2)
def _bounded_limits(
    path: str,
    digest: str,
    start: str,
    end: str,
    codes: tuple[str, ...],
) -> pd.DataFrame:
    del digest  # Immutable digest is deliberately part of the cache identity.
    filters: list[tuple[str, str, Any]] = [
        ("trade_date", ">=", pd.Timestamp(start).date()),
        ("trade_date", "<=", pd.Timestamp(end).date()),
    ]
    if codes:
        filters.append(("instrument_id", "in", [f"{code[2:]}.{code[:2]}" for code in codes]))
    limits = cast(Any, pq).read_table(
        path, columns=["instrument_id", "trade_date", "up_limit", "down_limit"], filters=filters
    ).to_pandas()
    limits["instrument"] = limits["instrument_id"].str[-2:] + limits["instrument_id"].str[:6]
    limits["datetime"] = pd.to_datetime(limits["trade_date"])
    if limits.duplicated(["instrument", "datetime"]).any():
        raise ValueError("duplicate canonical daily price limits")
    return limits.set_index(["instrument", "datetime"])


class HS300OpenLimitExchange(Exchange):
    def __init__(self, *, price_limits_path: str, price_limits_sha256: str, **kwargs: Any) -> None:
        path = Path(price_limits_path)
        verify_file(path, price_limits_sha256)
        self._canonical_limits = _bounded_limits(
            str(path.absolute()),
            price_limits_sha256,
            str(kwargs["start_time"]),
            str(kwargs["end_time"]),
            tuple(sorted(kwargs.get("codes", ()))),
        )
        # Qlib loads this field with its own adjusted open/close/factor/volume quotes.
        kwargs["subscribe_fields"] = list(set(kwargs.get("subscribe_fields", ())) | {"$is_st"})
        cast(Any, super()).__init__(**kwargs)
        if self.trade_w_adj_price:
            raise ValueError("HS300 native raw-share lot scenario requires complete Qlib factors")

    def _update_limit(self, limit_threshold: Any) -> None:
        cast(Any, super())._update_limit(limit_threshold)
        quotes = self.quote_df
        limits = self._canonical_limits.reindex(quotes.index)
        suspended = quotes["$close"].isna()
        benchmark = quotes.index.get_level_values("instrument") == "SH000300"
        active = ~suspended & ~benchmark
        if limits.loc[active, ["up_limit", "down_limit"]].isna().any().any():
            raise ValueError("SOURCE_INCOMPLETE: native open execution price limits missing")
        factor = quotes["$factor"]
        if (~np.isfinite(factor[active])).any() or (factor[active] <= 0).any():
            raise ValueError("HS300 native raw-share lot scenario requires positive factors")
        raw_open = quotes["$open"] / factor
        unknown = quotes["$is_st"].isna() | raw_open.isna()
        blocked = suspended | benchmark | unknown | quotes["$is_st"].fillna(1).astype(bool)
        quotes["limit_buy"] = blocked | (raw_open >= limits["up_limit"] - 1e-7)
        quotes["limit_sell"] = blocked | (raw_open <= limits["down_limit"] + 1e-7)
