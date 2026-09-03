from __future__ import annotations

import pandas as pd
import pytest

from quantos.backtest import FullReplacementTopKStrategy


def _strategy(*, topk: int = 2, max_weight: float = 0.6) -> FullReplacementTopKStrategy:
    signal = pd.Series(
        [0.0],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-02"), "SH600000")],
            names=["datetime", "instrument"],
        ),
    )
    return FullReplacementTopKStrategy(
        signal=signal,
        topk=topk,
        max_weight=max_weight,
        risk_degree=1.0,
    )


def test_target_weights_are_full_replacement_equal_and_tie_stable() -> None:
    strategy = _strategy()
    scores = pd.Series(
        {"SZ000001": 0.5, "SH600001": 0.8, "SH600000": 0.8, "SH600002": float("nan")}
    )

    target = strategy.generate_target_weight_position(
        scores,
        current=object(),
        trade_start_time=pd.Timestamp("2024-01-03"),
        trade_end_time=pd.Timestamp("2024-01-03"),
    )

    assert target == {"SH600000": 0.5, "SH600001": 0.5}


def test_target_weight_cap_preserves_cash_and_invalid_config_is_rejected() -> None:
    strategy = _strategy(topk=1, max_weight=0.03)
    target = strategy.generate_target_weight_position(
        pd.DataFrame({"score": [1.0]}, index=["SH600000"]),
        current=object(),
        trade_start_time=pd.Timestamp("2024-01-03"),
        trade_end_time=pd.Timestamp("2024-01-03"),
    )
    assert target == {"SH600000": 0.03}

    with pytest.raises(ValueError, match="positive"):
        _strategy(topk=0)
    with pytest.raises(ValueError, match="max_weight"):
        _strategy(max_weight=2.0)
