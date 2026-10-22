"""Read-only event-boundary checks around native Qlib target generation.

This module never settles an entitlement, swaps a security, values a merger or
edits an account. Unknown or exposed event state stops only that candidate arm.
"""

from __future__ import annotations

import importlib
import math
import pickle
from pathlib import Path
from typing import Any, cast

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.backtest.strategy import FullReplacementTopKStrategy
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_lifecycle import (
    NativeBoundaryDecision,
    NativeBoundaryObservation,
    NativeBoundaryOrder,
    NativeBoundaryPolicy,
    UnsupportedAccountEvent,
)
from quantos.research.hs300_lifecycle_data import load_lifecycle_facts


class NativeAccountBoundaryStop(RuntimeError):
    reason_code = "UNSUPPORTED_NATIVE_ACCOUNT_EVENT"


def native_boundary_runtime_identity() -> dict[str, str]:
    modules = (
        "qlib.backtest.account",
        "qlib.backtest.position",
        "qlib.backtest.executor",
        "qlib.backtest.decision",
        "qlib.contrib.strategy.order_generator",
    )
    return {
        name: sha256_file(Path(cast(Any, importlib.import_module(name)).__file__))
        for name in modules
    }


def _qlib_id(instrument_id: str) -> str:
    return instrument_id[-2:] + instrument_id[:6]


def event_check_start(event: UnsupportedAccountEvent) -> Any:
    return min(event.boundary_date, event.entitlement_window_start or event.boundary_date)


def evaluate_native_boundary(
    event: UnsupportedAccountEvent,
    observation: NativeBoundaryObservation,
    policy: NativeBoundaryPolicy,
) -> NativeBoundaryDecision:
    """Determine admissibility from observations, never calculate an entitlement."""
    affected = {_qlib_id(code) for code in (event.instrument_id, *event.related_instrument_ids)}
    reasons: list[str] = []
    unknown = (
        not observation.native_classes_verified
        or not observation.fresh_cash_no_initial_holdings_no_external_flow
        or not observation.sequential_history_complete
        or observation.all_holdings is None
        or observation.previous_unfilled_orders is None
        or observation.current_generated_orders is None
    )
    if unknown:
        reasons.append("native account, history, holdings or order observation is incomplete")
    holdings = observation.all_holdings or {}
    exposed = any(code in affected and amount != 0 for code, amount in holdings.items())
    if any(not math.isfinite(amount) for amount in holdings.values()):
        unknown = True
        reasons.append("nonfinite native holding amount")
    if exposed:
        reasons.append("an affected native holding is nonzero")
    for orders, label in (
        (observation.previous_unfilled_orders, "previous unfilled native order"),
        (observation.current_generated_orders, "current generated native order"),
    ):
        if orders is not None and any(
            order.qlib_id in affected and order.amount > order.deal_amount for order in orders
        ):
            exposed = True
            reasons.append(label + " exposes an affected security")
    rights: Any = "UNKNOWN"
    if observation.pending_rights_observability == "OBSERVABLE":
        if observation.observed_pending_rights is None:
            unknown = True
        elif affected.intersection(observation.observed_pending_rights):
            exposed, rights = True, "OBSERVED_EXPOSURE"
            reasons.append("native observable pending rights expose an affected security")
        else:
            rights = "OBSERVED_EMPTY"
    elif not unknown and not affected.intersection(observation.ever_held_or_filled):
        rights = "NOT_INCURRED_BY_COMPLETE_NATIVE_HISTORY"
    else:
        unknown = True
        reasons.append(
            "native rights ledger is unavailable and a never-exposed history is unproven"
        )
    status: Any = (
        "HARD_STOP_EXPOSURE"
        if exposed
        else ("HARD_STOP_UNKNOWN" if unknown else "CLEARED_ZERO_EXPOSURE")
    )
    return NativeBoundaryDecision(
        event_id=event.event_id,
        observation_hash=observation.content_hash,
        policy_hash=policy.content_hash,
        status=status,
        rights_conclusion=rights,
        reasons=tuple(reasons),
    )


def _native_order(order: Any) -> NativeBoundaryOrder:
    return NativeBoundaryOrder(
        qlib_id=order.stock_id,
        amount=float(order.amount),
        deal_amount=float(order.deal_amount),
        direction=cast(Any, int(order.direction)),
    )


class LifecycleBoundaryTopKStrategy(FullReplacementTopKStrategy):
    """Only inspect native state before/after the existing target/order generation."""

    def __init__(
        self,
        *,
        lifecycle_path: str,
        lifecycle_manifest_hash: str,
        boundary_root: str,
        expected_initial_cash_cny: float,
        **kwargs: Any,
    ) -> None:
        self._facts = load_lifecycle_facts(Path(lifecycle_path), lifecycle_manifest_hash)
        self._boundary_root = Path(boundary_root).absolute()
        self._boundary_root.mkdir(parents=True, exist_ok=True)
        self._expected_cash = expected_initial_cash_cny
        self._last_step = -1
        self._complete_history = True
        self._fresh_cash_proof = False
        self._ever_exposed: set[str] = set()
        self._native_hashes = native_boundary_runtime_identity()
        super().__init__(**kwargs)

    def _observation(
        self, step: int, session: Any, execute_result: Any, orders: Any
    ) -> NativeBoundaryObservation:
        account = cast(Any, self).common_infra.get("trade_account")
        executor = cast(Any, self).executor
        Position = cast(Any, importlib.import_module("qlib.backtest.position")).Position
        Account = cast(Any, importlib.import_module("qlib.backtest.account")).Account
        Simulator = cast(Any, importlib.import_module("qlib.backtest.executor")).SimulatorExecutor
        OrderGen = cast(
            Any, importlib.import_module("qlib.contrib.strategy.order_generator")
        ).OrderGenWOInteract
        valid_native = False
        holdings: dict[str, float] | None = None
        previous: tuple[NativeBoundaryOrder, ...] | None = None
        generated: tuple[NativeBoundaryOrder, ...] | None = None
        try:
            valid_native = (
                type(account) is Account
                and type(account.current_position) is Position
                and type(executor) is Simulator
                and executor.time_per_step == "day"
                and type(cast(Any, self).order_generator) is OrderGen
            )
            holdings = {
                str(code): float(amount)
                for code, amount in account.current_position.get_stock_amount_dict().items()
            }
            if any(not math.isfinite(amount) for amount in holdings.values()):
                holdings = None
                raise ValueError("nonfinite native holding state")
            self._ever_exposed.update(code for code, amount in holdings.items() if amount != 0)
            if step == 0:
                self._fresh_cash_proof = (
                    valid_native
                    and not holdings
                    and not account.get_hist_positions()
                    and float(account.get_cash()) == self._expected_cash
                    and float(account.init_cash) == self._expected_cash
                    and execute_result is None
                )
                previous = () if execute_result is None else None
            elif isinstance(execute_result, list):
                native_orders = tuple(
                    _native_order(item[0]) for item in cast(list[Any], execute_result)
                )
                previous = tuple(
                    order for order in native_orders if order.amount > order.deal_amount
                )
                self._ever_exposed.update(
                    order.qlib_id for order in native_orders if order.deal_amount != 0
                )
            if orders is not None:
                generated = tuple(_native_order(order) for order in orders)
        except (AttributeError, TypeError, ValueError, IndexError):
            self._complete_history = False
        if not valid_native or holdings is None or previous is None or generated is None:
            # Missing observations are permanent gaps in the lineage. A later
            # normal session cannot restore a never-exposed-since-start proof.
            self._complete_history = False
        return NativeBoundaryObservation(
            session=pd.Timestamp(session).date(),
            native_classes_verified=valid_native,
            fresh_cash_no_initial_holdings_no_external_flow=self._fresh_cash_proof,
            sequential_history_complete=self._complete_history,
            all_holdings=holdings,
            previous_unfilled_orders=previous,
            current_generated_orders=generated,
            ever_held_or_filled=tuple(sorted(self._ever_exposed)),
            pending_rights_observability="UNAVAILABLE_IN_QLIB_0_9_7",
            observed_pending_rights=None,
            native_source_hashes=self._native_hashes,
        )

    def _write_boundaries(
        self,
        events: list[UnsupportedAccountEvent],
        observation: NativeBoundaryObservation,
        phase: str,
    ) -> None:
        decisions = tuple(
            evaluate_native_boundary(event, observation, self._facts.policy) for event in events
        )
        destination = self._boundary_root / f"{observation.session.isoformat()}-{phase}.json"
        payload = {
            "schema_version": "hs300-native-boundary-receipt/v1",
            "events": {event.event_id: event.content_hash for event in events},
            "observation": observation,
            "decisions": decisions,
            "lifecycle_manifest_hash": self._facts.content_hash,
            "native_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
        }
        atomic_write_bytes(destination, canonical_json_bytes(payload))
        stopped = next(
            (decision for decision in decisions if decision.status != "CLEARED_ZERO_EXPOSURE"), None
        )
        if stopped is not None:
            account = cast(Any, self).common_infra.get("trade_account")
            # These are native read APIs/objects. Nothing is revalued or settled here.
            for name, value in (
                ("position", account.current_position),
                ("portfolio", account.get_portfolio_metrics()),
                ("indicator", account.get_trade_indicator()),
            ):
                atomic_write_bytes(
                    self._boundary_root / f"{observation.session.isoformat()}-partial-{name}.pkl",
                    pickle.dumps(value, protocol=4),
                )
            raise NativeAccountBoundaryStop(stopped.event_id)

    def generate_trade_decision(self, execute_result: Any = None) -> Any:
        calendar = cast(Any, self).trade_calendar
        step = int(calendar.get_trade_step())
        session, _ = calendar.get_step_time(step)
        if step != self._last_step + 1:
            self._complete_history = False
        pre = self._observation(step, session, execute_result, ())
        # An unsupported event opens a persistent validity boundary. A zero result
        # today never authorizes a later acquisition during its rights window.
        due = [
            event
            for event in self._facts.events
            if event_check_start(event) <= pd.Timestamp(session).date()
        ]
        # Exposed or unknown state stops before target generation. A candidate zero
        # state is rechecked with the actual native generated orders before execution.
        if due:
            self._write_boundaries(due, pre, "before")
        decision = cast(Any, super()).generate_trade_decision(execute_result)
        post = self._observation(step, session, execute_result, decision.get_decision())
        if due:
            self._write_boundaries(due, post, "generated")
        self._last_step = step
        return decision
