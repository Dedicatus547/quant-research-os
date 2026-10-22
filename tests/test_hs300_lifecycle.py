"""Bounded lifecycle separation and native zero/unknown/exposed event checks."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from quantos.contracts.hs300_lifecycle import (
    HS300LifecycleProfile,
    NativeBoundaryObservation,
    NativeBoundaryOrder,
    NativeBoundaryPolicy,
    UnsupportedAccountEvent,
)
from quantos.contracts.personal_research import PersonalCandidate
from quantos.research.hs300_data import compile_hs300_daily_signals
from quantos.research.hs300_lifecycle_data import compile_hs300_lifecycle_signals
from quantos.research.hs300_native_boundary import (
    LifecycleBoundaryTopKStrategy,
    evaluate_native_boundary,
    event_check_start,
)


def event():
    return UnsupportedAccountEvent(
        event_id="cash-option",
        instrument_id="600001.SH",
        boundary_date=date(2024, 2, 8),
        entitlement_window_start=date(2024, 2, 5),
        event_type="CASH_OPTION",
        source_ids=("official",),
    )


def observation(**updates):
    values = {
        "session": date(2024, 2, 5),
        "native_classes_verified": True,
        "fresh_cash_no_initial_holdings_no_external_flow": True,
        "sequential_history_complete": True,
        "all_holdings": {},
        "previous_unfilled_orders": (),
        "current_generated_orders": (),
        "ever_held_or_filled": (),
        "pending_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
    }
    values.update(updates)
    return NativeBoundaryObservation.model_validate(values)


def test_zero_never_exposed_can_continue_without_fabricating_native_rights():
    result = evaluate_native_boundary(event(), observation(), NativeBoundaryPolicy())
    assert result.status == "CLEARED_ZERO_EXPOSURE"
    assert result.rights_conclusion == "NOT_INCURRED_BY_COMPLETE_NATIVE_HISTORY"
    assert observation().pending_rights_observability == "UNAVAILABLE_IN_QLIB_0_9_7"
    assert observation().observed_pending_rights is None
    # An unrelated shareholder is not automatically a holder of the old security's rights.
    unrelated = observation(all_holdings={"SH600002": 200}, ever_held_or_filled=("SH600002",))
    assert (
        evaluate_native_boundary(event(), unrelated, NativeBoundaryPolicy()).status
        == "CLEARED_ZERO_EXPOSURE"
    )


@pytest.mark.parametrize(
    "values,status",
    [
        ({"all_holdings": {"SH600001": 200}}, "HARD_STOP_EXPOSURE"),
        ({"ever_held_or_filled": ("SH600001",)}, "HARD_STOP_UNKNOWN"),
        ({"all_holdings": None}, "HARD_STOP_UNKNOWN"),
        ({"previous_unfilled_orders": None}, "HARD_STOP_UNKNOWN"),
        ({"current_generated_orders": None}, "HARD_STOP_UNKNOWN"),
        ({"sequential_history_complete": False}, "HARD_STOP_UNKNOWN"),
    ],
)
def test_exposed_or_unobservable_state_is_never_zero(values, status):
    assert (
        evaluate_native_boundary(event(), observation(**values), NativeBoundaryPolicy()).status
        == status
    )


def test_earliest_rights_window_and_later_generated_order_are_checked():
    assert event_check_start(event()) == date(2024, 2, 5)
    order = NativeBoundaryOrder(qlib_id="SH600001", amount=200, deal_amount=0, direction=1)
    later = observation(session=date(2024, 2, 9), current_generated_orders=(order,))
    assert (
        evaluate_native_boundary(event(), later, NativeBoundaryPolicy()).status
        == "HARD_STOP_EXPOSURE"
    )
    assert HS300LifecycleProfile().lifecycle_feature_role == "STRUCTURAL_ONLY_NO_ANTICIPATORY_EXIT"


def test_membership_survives_delisting_without_anticipatory_signal_exit():
    rows = []
    for code in ("SH000300", "SH600001", "SH600002"):
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
    baseline = pd.DataFrame(rows)
    study = SimpleNamespace(
        request=SimpleNamespace(
            benchmark="SH000300",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 9),
            profile=HS300LifecycleProfile(),
        ),
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
    )
    original = compile_hs300_daily_signals(baseline, study)
    panel = baseline.copy()
    panel["is_listed"], panel["lifecycle_state"] = True, "LISTED"
    after = (panel["qlib_id"] == "SH600001") & (panel["trade_date"] >= date(2024, 2, 6))
    panel.loc[after, "is_listed"] = False
    panel.loc[after, "lifecycle_state"] = "DELISTED"
    panel.loc[after, ["close", "volume", "amount_cny"]] = float("nan")
    panel.loc[after, "available_at"] = None
    signals = compile_hs300_lifecycle_signals(panel, study)
    assert panel.loc[after, "is_member"].all()
    assert panel.loc[after, "close"].isna().all()
    for candidate_id in original:
        before = signals[candidate_id].index.get_level_values("datetime") < pd.Timestamp(
            "2024-02-06"
        )
        pd.testing.assert_frame_equal(
            signals[candidate_id].loc[before], original[candidate_id].loc[before]
        )
    assert (
        signals["main"].loc[("2024-02-06", "SH600001"), "score"]
        != signals["main"].loc[("2024-02-06", "SH600001"), "score"]
    )
    missing = panel.copy()
    missing.loc[
        (missing["qlib_id"] == "SH600002") & (missing["trade_date"] == date(2024, 2, 5)), "close"
    ] = float("nan")
    with pytest.raises(ValueError, match="PIT hard rejection"):
        compile_hs300_lifecycle_signals(missing, study)


def native_observer_fixture():
    from qlib.backtest.account import Account
    from qlib.backtest.executor import SimulatorExecutor
    from qlib.contrib.strategy.order_generator import OrderGenWOInteract

    # Native objects, no exchange/order execution, data query or account valuation.
    account = Account(init_cash=1_000_000, port_metr_enabled=False)
    executor = object.__new__(SimulatorExecutor)
    executor.time_per_step = "day"
    strategy = object.__new__(LifecycleBoundaryTopKStrategy)
    strategy.common_infra = SimpleNamespace(get=lambda name: account)
    strategy.level_infra = SimpleNamespace(get=lambda name: executor)
    strategy.order_generator = OrderGenWOInteract()
    strategy._expected_cash = 1_000_000
    strategy._complete_history = True
    strategy._fresh_cash_proof = False
    strategy._ever_exposed = set()
    strategy._native_hashes = {}
    return strategy, executor


@pytest.mark.parametrize("missing", ("previous_result", "native_class", "generated_orders"))
def test_one_missing_native_observation_permanently_breaks_history(missing):
    strategy, executor = native_observer_fixture()
    initial = strategy._observation(0, pd.Timestamp("2024-02-01"), None, ())
    assert initial.sequential_history_complete
    if missing == "native_class":
        executor.time_per_step = "week"
    broken = strategy._observation(
        1,
        pd.Timestamp("2024-02-02"),
        None if missing == "previous_result" else [],
        None if missing == "generated_orders" else (),
    )
    assert not broken.sequential_history_complete
    executor.time_per_step = "day"
    later = strategy._observation(2, pd.Timestamp("2024-02-05"), [], ())
    assert not later.sequential_history_complete
    assert (
        evaluate_native_boundary(event(), later, NativeBoundaryPolicy()).status
        == "HARD_STOP_UNKNOWN"
    )
