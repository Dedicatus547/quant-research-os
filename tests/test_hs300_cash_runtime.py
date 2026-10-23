"""Cash-specific admission and locked-proof scope; no scientific execution."""

from datetime import date
from types import SimpleNamespace

import pytest

from quantos.contracts.cash_option_proof import ContinuousCashOptionRule
from quantos.contracts.hs300_cash import BoundArtifact, CashRuntimePolicy
from quantos.contracts.hs300_lifecycle import (
    NativeBoundaryObservation,
    NativeBoundaryOrder,
    NativeBoundaryPolicy,
    UnsupportedAccountEvent,
)
from quantos.research.hs300_cash_runtime import (
    CashRuntimeBoundaryTopKStrategy,
    evaluate_cash_boundary,
)
from quantos.research.hs300_native_boundary import NativeAccountBoundaryStop


def event(**changes):
    return UnsupportedAccountEvent.model_validate(
        {
            "event_id": "cash-window",
            "instrument_id": "600001.SH",
            "boundary_date": date(2024, 2, 8),
            "entitlement_window_start": date(2024, 2, 5),
            "event_type": "CASH_OPTION",
            "source_ids": ("official",),
            **changes,
        }
    )


def rule():
    return ContinuousCashOptionRule(
        instrument_id="600001.SH",
        source_id="official",
        source_sha256="a" * 64,
        window_start=date(2024, 2, 5),
        window_end=date(2024, 2, 8),
        physical_pages=(3,),
    )


def observation(**changes):
    return NativeBoundaryObservation.model_validate(
        {
            "session": date(2024, 2, 5),
            "native_classes_verified": True,
            "fresh_cash_no_initial_holdings_no_external_flow": True,
            "sequential_history_complete": True,
            "all_holdings": {},
            "previous_unfilled_orders": (),
            "current_generated_orders": (),
            "ever_held_or_filled": ("SH600001",),
            "pending_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
            **changes,
        }
    )


def evaluate(observed=None, *, phase="generated", target=None, locked=None, source_event=None):
    return evaluate_cash_boundary(
        source_event or event(),
        observed or observation(),
        rule(),
        phase=phase,
        actual_target={} if target is None else target,
        locked_proof_hash=locked,
    )


def test_zero_requires_actual_generation_and_keeps_native_rights_unknown():
    before = evaluate(phase="before")
    assert before["status"] == "PENDING_ACTUAL_GENERATION"
    assert before["rights_conclusion"] == "UNPROVEN"
    generated = evaluate()
    assert generated["status"] == "CLEARED_DERIVED_CASH_INELIGIBILITY"
    assert generated["rights_conclusion"] == "DERIVED_THIS_CASH_RIGHT_ZERO"
    assert generated["native_rights_observability"] == "UNAVAILABLE_IN_QLIB_0_9_7"
    assert not generated["covers_merger_or_delisting"]
    missing = evaluate_cash_boundary(
        event(),
        observation(),
        rule(),
        phase="generated",
        actual_target=None,
        locked_proof_hash=None,
    )
    assert missing["status"] == "HARD_STOP_UNKNOWN"


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"all_holdings": {"SH600001": 200}}, "HARD_STOP_EXPOSURE"),
        ({"all_holdings": {"SH600001": 0}}, "HARD_STOP_EXPOSURE"),
        ({"observed_pending_rights": ("SH600001",)}, "HARD_STOP_EXPOSURE"),
        ({"sequential_history_complete": False}, "HARD_STOP_UNKNOWN"),
        ({"previous_unfilled_orders": None}, "HARD_STOP_UNKNOWN"),
        ({"pending_rights_observability": "OBSERVABLE"}, "HARD_STOP_UNKNOWN"),
    ],
)
def test_known_exposure_or_missing_history_cannot_be_inferred_zero(changes, status):
    assert evaluate(observation(**changes))["status"] == status


def test_actual_target_and_generated_order_support_stop_before_lock():
    assert evaluate(target={"SH600001": 0.1})["status"] == "HARD_STOP_EXPOSURE"
    native = NativeBoundaryOrder(qlib_id="SH600001", amount=200, deal_amount=0, direction=1)
    assert (
        evaluate(observation(current_generated_orders=(native,)))["status"] == "HARD_STOP_EXPOSURE"
    )
    assert (
        evaluate(observation(previous_unfilled_orders=(native,)))["status"] == "HARD_STOP_EXPOSURE"
    )
    assert evaluate(source_event=event(source_ids=("different",)))["status"] == "HARD_STOP_UNKNOWN"
    assert evaluate(observation(session=date(2024, 2, 9)))["status"] == "HARD_STOP_UNKNOWN"


def test_locked_cash_zero_survives_later_purchase_but_never_known_rights_or_history_gap():
    later = observation(session=date(2024, 2, 9), all_holdings={"SH600001": 200})
    assert evaluate(later, target={"SH600001": 0.1}, locked="b" * 64)["status"] == (
        "CLEARED_DERIVED_CASH_INELIGIBILITY"
    )
    assert (
        evaluate(
            later.model_copy(update={"observed_pending_rights": ("SH600001",)}), locked="b" * 64
        )["status"]
        == "HARD_STOP_EXPOSURE"
    )
    assert (
        evaluate(later.model_copy(update={"sequential_history_complete": False}), locked="b" * 64)[
            "status"
        ]
        == "HARD_STOP_UNKNOWN"
    )


def test_cash_lock_never_exempts_generic_boundary_and_records_before_stopping(tmp_path):
    strategy = object.__new__(CashRuntimeBoundaryTopKStrategy)
    strategy._cash_rules = {"600001.SH": rule()}
    strategy._cash_locked = {"cash-window": "b" * 64}
    strategy._actual_target = {"SH600001": 0.1}
    strategy._cash_runtime_hashes = {}
    strategy._boundary_root = tmp_path
    strategy._facts = SimpleNamespace(policy=NativeBoundaryPolicy(), content_hash="c" * 64)
    account = SimpleNamespace(
        current_position={"native": "fixture"},
        get_portfolio_metrics=lambda: {},
        get_trade_indicator=lambda: {},
    )
    strategy.common_infra = SimpleNamespace(get=lambda _: account)
    with pytest.raises(NativeAccountBoundaryStop, match="merger"):
        strategy._cash_boundaries(
            [event(event_id="merger", event_type="MERGER_EXCHANGE")],
            observation(all_holdings={"SH600001": 200}),
            "before",
        )
    assert (tmp_path / "2024-02-05-before.json").exists()
    assert len(list(tmp_path.glob("*-partial-*.pkl"))) == 3
    assert BoundArtifact(path="original.json", sha256="a" * 64).schema_version
    assert CashRuntimePolicy().merger_and_delisting == "UNCHANGED_V1_HARD_BOUNDARIES"
