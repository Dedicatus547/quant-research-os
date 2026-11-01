"""Bounded predicate and effective-native-quote checks; no account execution."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.contracts.hs300_adjusted import FixedNativeQuoteBinding, ZeroHoldingMergerRule
from quantos.contracts.hs300_lifecycle import (
    NativeBoundaryObservation,
    NativeBoundaryOrder,
    UnsupportedAccountEvent,
)
from quantos.research.hs300_adjusted_runtime import (
    evaluate_adjusted_zero_boundary,
    verify_effective_native_quote,
)

HASH = "a" * 64


def merger() -> ZeroHoldingMergerRule:
    return ZeroHoldingMergerRule(
        instrument_id="600837.SH",
        issuer_instrument_id="601211.SH",
        source_id="official-merger",
        source_rule_sha256=HASH,
        record_date=date(2025, 3, 3),
        boundary_date=date(2025, 2, 6),
        ratio="0.62",
        event_ids=("merger",),
    )


def event() -> UnsupportedAccountEvent:
    return UnsupportedAccountEvent(
        event_id="merger",
        instrument_id="600837.SH",
        boundary_date=date(2025, 2, 6),
        event_type="MERGER_EXCHANGE",
        source_ids=("official-merger",),
    )


def observation(**changes: Any) -> NativeBoundaryObservation:
    values: dict[str, Any] = {
        "session": date(2025, 2, 6),
        "native_classes_verified": True,
        "fresh_cash_no_initial_holdings_no_external_flow": True,
        "sequential_history_complete": True,
        "all_holdings": {},
        "previous_unfilled_orders": (),
        "current_generated_orders": (),
        "ever_held_or_filled": ("SH600837",),
        "pending_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
        "observed_pending_rights": None,
    }
    values.update(changes)
    return NativeBoundaryObservation(**values)


@pytest.mark.parametrize(
    ("changes", "target", "proof", "expected"),
    [
        ({}, {}, HASH, "CLEARED_DERIVED_ZERO_MERGER_INPUT"),
        ({"all_holdings": {"SH600837": 1.0}}, {}, HASH, "HARD_STOP_EXPOSURE"),
        ({"sequential_history_complete": False}, {}, HASH, "HARD_STOP_UNKNOWN"),
        ({"fresh_cash_no_initial_holdings_no_external_flow": False}, {}, HASH, "HARD_STOP_UNKNOWN"),
        ({"current_generated_orders": None}, {}, HASH, "HARD_STOP_UNKNOWN"),
        ({}, None, HASH, "HARD_STOP_UNKNOWN"),
        ({}, {"SH600837": 0.0}, HASH, "HARD_STOP_EXPOSURE"),
        ({}, {}, None, "HARD_STOP_UNKNOWN"),
        ({"observed_pending_rights": ("SH600837",)}, {}, HASH, "HARD_STOP_EXPOSURE"),
        ({"pending_rights_observability": "OBSERVABLE"}, {}, HASH, "HARD_STOP_UNKNOWN"),
    ],
)
def test_source_bound_zero_is_derived_and_missing_or_exposed_stops(
    changes: dict[str, Any], target: dict[str, float] | None, proof: str | None, expected: str
) -> None:
    result = evaluate_adjusted_zero_boundary(
        event(),
        observation(**changes),
        merger(),
        phase="generated",
        actual_target=target,
        effective_quote_proof_hash=proof,
        facts_hash=HASH,
    )
    assert result["status"] == expected
    assert result["native_rights_observability"] == changes.get(
        "pending_rights_observability", "UNAVAILABLE_IN_QLIB_0_9_7"
    )
    assert result["future_account_eod_observed"] is False
    assert result["actual_dividend_payment_proven"] is False


def test_pending_native_order_and_before_phase_cannot_clear() -> None:
    order = NativeBoundaryOrder(qlib_id="SH600837", amount=1, deal_amount=0, direction=1)
    result = evaluate_adjusted_zero_boundary(
        event(),
        observation(previous_unfilled_orders=(order,)),
        merger(),
        phase="generated",
        actual_target={},
        effective_quote_proof_hash=HASH,
        facts_hash=HASH,
    )
    assert result["status"] == "HARD_STOP_EXPOSURE"
    result = evaluate_adjusted_zero_boundary(
        event(),
        observation(),
        merger(),
        phase="before",
        actual_target=None,
        effective_quote_proof_hash=HASH,
        facts_hash=HASH,
    )
    assert result["status"] == "PENDING_ACTUAL_GENERATION"


@pytest.mark.parametrize("invalid_amount", [float("nan"), float("inf")])
def test_nonfinite_observation_cannot_enter_canonical_proof(invalid_amount: float) -> None:
    # Production _observation converts nonfinite holdings to missing observation;
    # the frozen contract also rejects a directly supplied malformed observation
    # before it can enter the evaluator or acquire a canonical proof identity.
    with pytest.raises(ValidationError, match="finite"):
        observation(all_holdings={"SH600837": invalid_amount})


@pytest.mark.parametrize("mismatch", [False, True])
def test_actual_native_quote_accessor_is_checked_not_only_dataframe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: bool
) -> None:
    from qlib.backtest.account import Account
    from qlib.backtest.high_performance_ds import NumpyQuote
    from qlib.backtest.position import Position
    from qlib.config import C

    from quantos.research.hs300_exchange import HS300OpenLimitExchange

    # Exact native instances are assembled without invoking account/exchange
    # constructors, Simulator or fills. Only the real read-only quote APIs run.
    fields = ("open", "close", "factor", "volume", "change", "is_st")
    day = date(2025, 3, 3)
    calendar = [day, date(2025, 3, 4)]
    index = pd.MultiIndex.from_tuples(
        [("SH600837", pd.Timestamp(day))], names=["instrument", "datetime"]
    )
    frame = pd.DataFrame(float("nan"), index=index, columns=["$" + f for f in fields])
    exchange = HS300OpenLimitExchange.__new__(HS300OpenLimitExchange)
    exchange.freq = "day"
    exchange.extra_quote = None
    exchange.trade_w_adj_price = False
    exchange.quote_cls = NumpyQuote
    exchange.quote_df = frame
    quote_frame = frame.copy()
    if mismatch:
        quote_frame.loc[("SH600837", pd.Timestamp(day)), "$close"] = 1.0
    exchange.quote = NumpyQuote(quote_frame, "day")
    account = Account.__new__(Account)
    account.current_position = Position.__new__(Position)
    common = {"trade_exchange": exchange, "trade_account": account}
    strategy = SimpleNamespace(
        trade_exchange=exchange,
        executor=SimpleNamespace(trade_exchange=exchange),
        common_infra=common,
        _trade_exchange=None,
    )
    monkeypatch.setitem(C._config, "provider_uri", {"__DEFAULT_FREQ": str(tmp_path)})
    monkeypatch.setitem(C._config, "expression_cache", None)
    monkeypatch.setitem(C._config, "dataset_cache", None)
    binding = FixedNativeQuoteBinding(
        qlib_view_hash=HASH,
        calendar_sha256=HASH,
        quote_files={f"features/sh600837/{field}.day.bin": HASH for field in fields},
        sessions_by_instrument={"600837.SH": (day,)},
    )
    bins = {f"features/sh600837/{field}.day.bin": (0, (float("nan"),)) for field in fields}
    if mismatch:
        with pytest.raises(ValueError, match="effective quote differs"):
            verify_effective_native_quote(strategy, merger(), binding, tmp_path, (calendar, bins))
    else:
        result = verify_effective_native_quote(
            strategy, merger(), binding, tmp_path, (calendar, bins)
        )
        assert result["conclusion"] == "ACTUAL_NATIVE_QUOTE_NO_ACQUISITION_PATH"
