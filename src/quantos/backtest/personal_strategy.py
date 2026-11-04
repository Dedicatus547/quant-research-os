"""Personal rules expressed through Qlib's native target/order strategy.

All balances, age counters, fills and sell restrictions come from native Position
and Exchange. Targets are proposals; an unfilled exit remains an actual holding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pandas as pd
from qlib.backtest.decision import TradeDecisionWO  # pyright: ignore[reportMissingTypeStubs]
from qlib.contrib.strategy.signal_strategy import (  # pyright: ignore[reportMissingTypeStubs]
    WeightStrategyBase,
)

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.personal_strategy import PersonalStrategy


class PersonalRuleStrategy(WeightStrategyBase):  # pyright: ignore[reportUntypedBaseClass]
    def __init__(
        self, *, specification: dict[str, Any], trace_root: str | None = None, **kwargs: Any
    ) -> None:
        self.spec = PersonalStrategy.model_validate(specification)
        self.last_rebalance_date: str | None = None
        self.last_plan: dict[str, Any] = {}
        self.trace_root = None if trace_root is None else Path(trace_root)
        if self.trace_root is not None and not self.trace_root.is_absolute():
            raise ValueError("native strategy trace root must be operator-bound and absolute")
        # Native OrderGen must not multiply risk a second time.
        cast(Any, super()).__init__(risk_degree=1.0, **kwargs)

    def generate_trade_decision(self, execute_result: Any = None) -> Any:
        step = self.trade_calendar.get_trade_step()
        start, _ = self.trade_calendar.get_step_time(step)
        self._scheduled = (
            self.spec.rebalance == "daily"
            or self.last_rebalance_date is None
            or (pd.Timestamp(self.last_rebalance_date).isocalendar()[:2] != start.isocalendar()[:2])
        )
        decision = cast(Any, super()).generate_trade_decision(execute_result)
        if self.last_plan.get("execution_date") != str(start.date()):
            self.last_plan = {
                "execution_date": str(start.date()),
                "scheduled": self._scheduled,
                "actual_held_before": self.trade_position.get_stock_list(),
                "eligible_ranked": None,
                "target_weights": None,
                "forced_exits": [],
                "effective_action": "NO_SIGNAL_NO_DECISION",
            }
        if self._scheduled:
            self.last_rebalance_date = str(start.date())
        else:
            forced = set(self.last_plan.get("forced_exits", []))
            # Reuse native sizing; between weekly schedules attempt forced exits only.
            decision = TradeDecisionWO(
                [o for o in decision.get_decision() if o.stock_id in forced and o.direction == 0],
                self,
            )
            self.last_plan["rank_proposal_weights"] = self.last_plan.get("target_weights")
            self.last_plan["target_weights"] = None
            self.last_plan["effective_action"] = "HOLD_ACTUAL_POSITIONS_EXCEPT_FORCED_EXITS"
        self.last_plan["orders_generated"] = [
            {
                "instrument": order.stock_id,
                "amount": order.amount,
                "direction": int(order.direction),
            }
            for order in decision.get_decision()
        ]
        if self.trace_root is not None:
            atomic_write_bytes(
                self.trace_root / f"{start.date()}.json", canonical_json_bytes(self.last_plan)
            )
        return decision

    def generate_target_weight_position(
        self,
        score: Any,
        current: Any,
        trade_start_time: Any,
        trade_end_time: Any,
    ) -> dict[str, float]:
        del trade_end_time
        values = score.iloc[:, 0] if isinstance(score, pd.DataFrame) else score
        ranked = values.dropna().rename("score").rename_axis("instrument").reset_index()
        ranked = ranked.sort_values(
            ["score", "instrument"],
            ascending=[self.spec.rank_direction == "ascending", True],
            kind="mergesort",
        )
        codes = [str(c) for c in ranked["instrument"]]
        held = list(current.get_stock_list())
        forced = [
            c
            for c in held
            if c not in codes
            or (
                self.spec.max_holding_sessions is not None
                and current.get_stock_count(c, bar="day") >= self.spec.max_holding_sessions
            )
        ]
        allowed = [c for c in codes if c not in forced]
        buffered = set(allowed[: self.spec.top_k + self.spec.rank_buffer])
        retained = [c for c in allowed if c in held and c in buffered]
        selected = retained[: self.spec.top_k]
        selected += [c for c in allowed if c not in selected][: self.spec.top_k - len(selected)]
        if self.spec.target_weights is None:
            # Fixed slot weights: too few candidates leave cash; never renormalize.
            weight = min(self.spec.risk_degree / self.spec.top_k, self.spec.max_weight)
            targets = dict.fromkeys(selected, weight)
        else:
            targets = {
                c: self.spec.target_weights[c] for c in selected if c in self.spec.target_weights
            }
        self.last_plan = {
            "execution_date": str(pd.Timestamp(trade_start_time).date()),
            "scheduled": self._scheduled,
            "eligible_ranked": codes,
            "actual_held_before": held,
            "forced_exits": forced,
            "target_weights": targets,
            "rule_priority": self.spec.rule_priority,
        }
        return targets
