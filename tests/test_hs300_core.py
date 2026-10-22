"""Focused successor time, amount, universe and native constraint checks."""

from datetime import date

import pandas as pd
import pytest

from quantos.contracts.personal_research import (
    HS300DailyProfile,
    HS300StudyRequest,
    PersonalCandidate,
    PreparedHS300Study,
)
from quantos.research.hs300_data import compile_hs300_daily_signals


def prepared():
    return PreparedHS300Study(
        request=HS300StudyRequest(
            idempotency_key="hs300-core",
            brief="finite HS300 amount strategy",
            proposal={"session_id": "engineering", "schema_version": "host-session-proposal/v2"},
            warmup_start=date(2024, 1, 2),
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 9),
        ),
        dataset_manifest=None,
        code_hash="a" * 64,
        candidates=(
            PersonalCandidate(candidate_id="main", role="main", rule="fixed"),
            PersonalCandidate(candidate_id="classic", role="classic", rule="fixed"),
            *(
                PersonalCandidate(
                    candidate_id=f"random-{seed}", role="random", seed=seed, rule="fixed"
                )
                for seed in (17, 41, 73, 101, 137)
            ),
        ),
        readiness="BLOCKED",
        gaps=("fixture",),
        rationale="fixture",
        comparison_scope="7",
        limits=(),
    )


def panel():
    rows = []
    for code in ("SH000300", "SH688001", "SZ300001"):
        for index, day in enumerate(pd.bdate_range("2024-01-02", "2024-02-09")):
            rows.append(
                {
                    "trade_date": day.date(),
                    "qlib_id": code,
                    "close": 10 * 1.01**index,
                    "volume": 1_000_000.0,
                    "amount_cny": 10_000_000.0 * 1.2**index,
                    "is_member": code != "SH000300",
                    "is_st": False,
                    "is_suspended": False,
                    "available_at": day.tz_localize("Asia/Shanghai")
                    + pd.Timedelta(hours=15, minutes=30),
                }
            )
    return pd.DataFrame(rows)


def test_amount_signal_full_hs300_and_next_session():
    data, study = panel(), prepared()
    signal = compile_hs300_daily_signals(data, study)
    assert len(signal) == 7
    assert signal["main"]["score"].notna().all()  # STAR and ChiNext are admitted; volume is flat.
    assert signal["main"].index.get_level_values("datetime").min() == pd.Timestamp("2024-01-31")
    assert signal["main"].index.get_level_values("datetime").max() == pd.Timestamp("2024-02-08")
    assert not signal["random-17"].equals(signal["random-41"])
    data["amount_cny"] = 10_000_000.0
    rejected = compile_hs300_daily_signals(data, study)
    assert rejected["main"]["score"].isna().all()
    assert rejected["classic"]["score"].notna().all()


def test_availability_and_missing_session_hard_reject():
    data = panel()
    data.loc[0, "available_at"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="PIT hard rejection"):
        compile_hs300_daily_signals(data, prepared())
    data = panel()
    data = data.drop(
        data.index[(data["qlib_id"] == "SH688001") & (data["trade_date"] == date(2024, 1, 10))]
    )
    with pytest.raises(ValueError, match="dense HS300 sessions"):
        compile_hs300_daily_signals(data, prepared())


def test_consecutive_history_member_exit_and_target_weight():
    data = panel()
    day = date(2024, 1, 31)
    data.loc[(data["qlib_id"] == "SH688001") & (data["trade_date"] >= day), "is_member"] = False
    signals = compile_hs300_daily_signals(data, prepared())
    assert (
        signals["main"].loc[(str(day), "SH688001"), "score"]
        != signals["main"].loc[(str(day), "SH688001"), "score"]
    )
    from quantos.backtest.strategy import FullReplacementTopKStrategy

    strategy = object.__new__(FullReplacementTopKStrategy)
    strategy.topk, strategy.max_weight = 10, 0.1
    target = strategy.generate_target_weight_position(
        pd.Series([1.0, 1.0], index=["SZ300001", "SH688001"]), None, None, None
    )
    assert list(target) == ["SH688001", "SZ300001"]
    assert all(
        weight * HS300DailyProfile().risk_degree == pytest.approx(0.09)
        for weight in target.values()
    )


def test_open_limits_use_raw_factor_not_close_flags():
    from quantos.research.hs300_exchange import HS300OpenLimitExchange

    exchange = object.__new__(HS300OpenLimitExchange)
    index = pd.MultiIndex.from_tuples(
        [
            ("SH688001", pd.Timestamp("2024-02-01")),
            ("SZ300001", pd.Timestamp("2024-02-01")),
        ],
        names=["instrument", "datetime"],
    )
    exchange.quote_df = pd.DataFrame(
        {
            "$close": [20.0, 20.0],
            "$open": [22.0, 18.0],
            "$factor": [2.0, 2.0],
            "$is_st": [0.0, 0.0],
            "$limit_buy": [0.0, 0.0],
            "$limit_sell": [0.0, 0.0],
        },
        index=index,
    )
    exchange._canonical_limits = pd.DataFrame(
        {"up_limit": [11.0, 11.0], "down_limit": [9.0, 9.0]}, index=index
    )
    exchange._update_limit(("$limit_buy", "$limit_sell"))
    assert exchange.quote_df["limit_buy"].tolist() == [True, False]
    assert exchange.quote_df["limit_sell"].tolist() == [False, True]
    exchange.quote_df.loc[index[1], "$is_st"] = 1
    exchange._update_limit(("$limit_buy", "$limit_sell"))
    assert exchange.quote_df.loc[index[1], "limit_buy"]
