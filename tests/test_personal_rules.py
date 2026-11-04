"""Small rule decisions over real Qlib Position; native05 owns fill/continuity proof.

The weekly test injects a proposed native Order stream and date input only. It
does not implement an exchange, account or execution simulator.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError
from qlib.backtest.decision import Order, TradeDecisionWO
from qlib.backtest.position import Position
from qlib.backtest.utils import CommonInfrastructure, LevelInfrastructure
from qlib.contrib.strategy.signal_strategy import WeightStrategyBase

from quantos.backtest.personal_strategy import PersonalRuleStrategy
from quantos.contracts.personal_strategy import PersonalStrategy

A, B, C, D = "SH600001", "SH600002", "SZ000001", "SH600003"


def specification(**changes):
    value = {
        "score": {
            "expression_id": "close",
            "nodes": [{"node_id": "p", "operator": "field", "field_name": "adjusted_close"}],
            "output_node_id": "p",
        },
        "top_k": 2,
        "risk_degree": 0.8,
        "max_weight": 0.5,
    }
    value.update(changes)
    return PersonalStrategy.model_validate(value)


def strategy(**changes):
    signal = pd.Series(
        [1.0],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-08"), A)], names=["datetime", "instrument"]
        ),
    )
    rule = PersonalRuleStrategy(
        specification=specification(**changes).model_dump(mode="json"), signal=signal
    )
    rule._scheduled = True
    return rule


def position(*held, age=0):
    current = Position(
        cash=10_000, position_dict={code: {"amount": 200.0, "price": 10.0} for code in held}
    )
    for code in held:
        current.update_stock_count(code, bar="day", count=age)
    return current


def targets(rule, scores, current=None):
    return rule.generate_target_weight_position(
        pd.Series(scores, dtype=float),
        position() if current is None else current,
        pd.Timestamp("2024-01-09"),
        pd.Timestamp("2024-01-09"),
    )


@pytest.mark.parametrize("direction,expected", [("descending", [B, C]), ("ascending", [A, B])])
@pytest.mark.parametrize("reverse", [False, True])
def test_rank_direction_and_instrument_ties_do_not_depend_on_input_order(
    direction, expected, reverse
):
    values = [(C, 2.0), (A, 1.0), (D, float("nan")), (B, 2.0)]
    if reverse:
        values.reverse()
    selected = targets(strategy(rank_direction=direction), dict(values))
    assert list(selected) == expected
    assert selected == dict.fromkeys(expected, 0.4)


def test_fixed_slots_leave_unfilled_slots_as_cash_and_empty_signal_is_empty():
    rule = strategy(top_k=4, risk_degree=0.8, max_weight=0.3)
    selected = targets(rule, {A: 3.0, B: 2.0})
    assert selected == {A: 0.2, B: 0.2}
    assert 1 - sum(selected.values()) == pytest.approx(0.6)
    assert targets(rule, {A: float("nan")}) == {}


def test_individual_cap_preserves_cash_and_native_ordergen_has_no_second_risk_multiplier():
    rule = strategy(top_k=2, risk_degree=0.9, max_weight=0.1)
    assert targets(rule, {A: 3.0, B: 2.0}) == {A: 0.1, B: 0.1}
    assert rule.get_risk_degree(0) == 1.0


def test_explicit_weights_apply_to_selected_names_without_renormalizing():
    rule = strategy(top_k=3, risk_degree=0.7, max_weight=0.3, target_weights={A: 0.15, B: 0.25})
    selected = targets(rule, {A: 3.0, B: 2.0, C: 1.0})
    assert selected == {A: 0.15, B: 0.25}
    assert 1 - sum(selected.values()) == pytest.approx(0.6)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_weight": 0.1, "target_weights": {A: 0.2}},
        {"risk_degree": 0.5, "max_weight": 0.3, "target_weights": {A: 0.3, B: 0.3}},
        {"target_weights": {"../../position": 0.1}},
    ],
)
def test_explicit_weight_bounds_are_contract_rejections(changes):
    with pytest.raises(ValidationError, match="bounds"):
        specification(**changes)


def test_rank_buffer_retains_actual_holding_inside_buffer_then_replaces_outside():
    current = position(C)
    scores = {A: 3.0, B: 2.0, C: 1.0}
    assert set(targets(strategy(rank_buffer=0), scores, current)) == {A, B}
    buffered = strategy(rank_buffer=1)
    assert list(targets(buffered, scores, current)) == [C, A]
    assert current.get_stock_amount(C) == 200.0  # A target proposal never mutates native holdings.
    outside = targets(buffered, {A: 4.0, B: 3.0, D: 2.0, C: 1.0}, current)
    assert set(outside) == {A, B}


def test_eligibility_exit_overrides_even_a_wide_rank_buffer():
    current = position(C, age=1)
    rule = strategy(rank_buffer=20)
    assert set(targets(rule, {A: 3.0, B: 2.0, C: float("nan")}, current)) == {A, B}
    assert rule.last_plan["forced_exits"] == [C]


@pytest.mark.parametrize("age,expected", [(2, {A, B}), (3, {B, C})])
def test_max_native_holding_age_takes_priority_over_rank_and_buffer(age, expected):
    current = position(A, age=age)
    rule = strategy(rank_buffer=20, max_holding_sessions=3)
    assert set(targets(rule, {A: 3.0, B: 2.0, C: 1.0}, current)) == expected
    assert rule.last_plan["forced_exits"] == ([A] if age == 3 else [])
    assert set(targets(strategy(max_holding_sessions=None), {A: 3.0, B: 2.0}, current)) == {A, B}


@pytest.mark.parametrize("native_trade_value,remaining", [(0.0, 200.0), (500.0, 150.0)])
def test_unfilled_or_partial_native_sale_remains_held_and_is_requested_out_again(
    native_trade_value, remaining
):
    current = position(A, age=3)
    rule = strategy(top_k=1, max_holding_sessions=3, rank_buffer=20)
    assert set(targets(rule, {A: 3.0, B: 2.0}, current)) == {B}
    assert rule.last_plan["forced_exits"] == [A]
    # Feed a fixed observed outcome to Qlib's own update path, without computing
    # a fill, fee, cash balance or exchange rule in project/test code.
    order = Order(A, 200, Order.SELL, pd.Timestamp("2024-01-09"), pd.Timestamp("2024-01-09"))
    current.update_order(order, trade_val=native_trade_value, cost=0, trade_price=10)
    assert current.check_stock(A) and current.get_stock_amount(A) == remaining
    current.add_count_all("day")
    assert current.get_stock_count(A, bar="day") == 4
    assert set(targets(rule, {A: 3.0, B: 2.0}, current)) == {B}
    assert rule.last_plan["forced_exits"] == [A]


class CalendarInput:
    """An explicit date input for strategy scheduling, not an exchange calendar."""

    def __init__(self, day):
        self.day = pd.Timestamp(day)

    def get_trade_step(self):
        return 0

    def get_step_time(self, step=None, shift=0):
        return self.day, self.day + pd.Timedelta(hours=23)


@pytest.mark.parametrize(
    "day,last_rebalance,scheduled",
    [
        ("2024-01-09", "2024-01-08", False),
        ("2024-01-16", "2024-01-08", True),  # first actual session can be Tuesday
        ("2024-01-02", "2023-12-29", True),
        ("2024-01-09", None, True),
    ],
)
def test_weekly_schedule_uses_native_positions_and_keeps_only_forced_exits_between_rebalances(
    monkeypatch, day, last_rebalance, scheduled
):
    current = position(A, B, age=1)
    rule = strategy(rebalance="weekly_first_session", top_k=1)
    rule.last_rebalance_date = last_rebalance
    calendar = CalendarInput(day)
    rule.reset_level_infra(LevelInfrastructure(trade_calendar=calendar))
    rule.reset_common_infra(
        CommonInfrastructure(trade_account=SimpleNamespace(current_position=current))
    )

    def proposed_orders(self, execute_result=None):
        self.generate_target_weight_position(
            pd.Series({A: 1.0, B: float("nan"), C: 3.0}),
            self.trade_position,
            calendar.day,
            calendar.day,
        )
        return TradeDecisionWO(
            [
                Order(A, 200, Order.SELL, calendar.day, calendar.day),
                Order(B, 200, Order.SELL, calendar.day, calendar.day),
                Order(C, 200, Order.BUY, calendar.day, calendar.day),
            ],
            self,
        )

    monkeypatch.setattr(WeightStrategyBase, "generate_trade_decision", proposed_orders)
    decision = rule.generate_trade_decision()
    orders = decision.get_decision()
    assert rule.last_plan["scheduled"] is scheduled
    if scheduled:
        assert len(orders) == 3 and rule.last_rebalance_date == day
    else:
        assert [(o.stock_id, o.direction) for o in orders] == [(B, Order.SELL)]
        assert rule.last_plan["target_weights"] is None
        assert rule.last_plan["effective_action"] == "HOLD_ACTUAL_POSITIONS_EXCEPT_FORCED_EXITS"
        assert rule.last_rebalance_date == last_rebalance
    assert set(current.get_stock_list()) == {A, B}
