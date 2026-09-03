"""Minimal target-weight strategy; Qlib owns orders, exchange, and accounting."""

from __future__ import annotations

from typing import Any

import pandas as pd
from qlib.contrib.strategy.signal_strategy import (  # pyright: ignore[reportMissingTypeStubs]
    WeightStrategyBase,
)


class FullReplacementTopKStrategy(  # pyright: ignore[reportUntypedBaseClass]
    WeightStrategyBase
):
    """Return deterministic equal target weights only when Qlib supplies a signal."""

    def __init__(self, *, topk: int, max_weight: float, **kwargs: Any) -> None:
        if topk <= 0:
            raise ValueError("topk must be positive")
        if not 0 < max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")
        super().__init__(**kwargs)  # pyright: ignore[reportUnknownMemberType]
        self.topk = topk
        self.max_weight = max_weight

    def generate_target_weight_position(
        self,
        score: pd.Series[float] | pd.DataFrame,
        current: object,
        trade_start_time: pd.Timestamp,
        trade_end_time: pd.Timestamp,
    ) -> dict[str, float]:
        del current, trade_start_time, trade_end_time
        values = score.iloc[:, 0] if isinstance(score, pd.DataFrame) else score
        ranked = (
            values.dropna()
            .rename("score")
            .rename_axis("instrument")
            .reset_index()
            .assign(instrument=lambda frame: frame["instrument"].astype(str))
            .sort_values(
                ["score", "instrument"],
                ascending=[False, True],
                kind="mergesort",
            )
        )
        selected = [str(value) for value in ranked["instrument"].head(self.topk)]
        if not selected:
            return {}
        weight = min(1.0 / len(selected), self.max_weight)
        return {instrument: weight for instrument in selected}
