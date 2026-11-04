"""Complete Qlib Account continuation with durable per-session publication.

Only orchestration and native state export live here. Qlib Simulator/Exchange/
Account perform every order, fill, balance and report update. No pickle is loaded.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalExecutionPolicy, PersonalStrategy
from quantos.research.personal_native import native_config


class UnknownNativeStep(RuntimeError):
    """Started native execution has no durable state: reconciliation required."""


class NativePersonalSession:
    def __init__(
        self,
        root: Path,
        *,
        strategy: PersonalStrategy,
        policy: PersonalExecutionPolicy,
        runtime_hash: str,
        benchmark: str = "SH000300",
    ) -> None:
        self.root = root.absolute()
        self.strategy = strategy
        self.policy = policy
        self.runtime_hash = runtime_hash
        self.benchmark = benchmark
        self.identity = {
            "schema_version": "personal-native-session/v1",
            "strategy_hash": strategy.content_hash,
            "policy_hash": policy.content_hash,
            "runtime_hash": runtime_hash,
            "benchmark": benchmark,
        }
        with exclusive_directory_lock(self.root):
            path = self.root / "session.json"
            if path.exists():
                if self._read_json("session.json") != self.identity:
                    raise ArtifactIntegrityError("native session dependencies changed")
            else:
                atomic_write_bytes(path, canonical_json_bytes(self.identity))

    def _read_json(self, logical: str) -> dict[str, Any]:
        return json.loads(confined_regular_file(self.root, logical).read_bytes())

    def _inventory(self) -> list[dict[str, Any]]:
        directory = self.root / "steps"
        if not directory.exists():
            return []
        previous: str | None = None
        entries: list[dict[str, Any]] = []
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_dir():
                raise ArtifactIntegrityError("unsafe native step path")
            receipt_path = path / "completed.json"
            if not receipt_path.exists():
                self._reconcile(path)
            receipt = self._read_json(f"steps/{path.name}/completed.json")
            if (
                receipt["previous_checkpoint_hash"] != previous
                or receipt["session"] != self.identity
            ):
                raise ArtifactIntegrityError("native checkpoint chain changed")
            if entries and receipt["execution_date"] <= entries[-1]["execution_date"]:
                raise ArtifactIntegrityError("native checkpoint time order changed")
            for name, digest in receipt["files"].items():
                verify_file(confined_regular_file(path, name), digest)
            previous = sha256_bytes(canonical_json_bytes(receipt))
            entries.append(receipt)
        return entries

    def _reconcile(self, path: Path) -> None:
        # An executed native step is published from its retained state, never re-executed.
        staged = path / "executed.json"
        if not staged.exists():
            raise UnknownNativeStep(
                "native step began without complete durable state; do not replay"
            )
        receipt = self._read_json(f"steps/{path.name}/executed.json")
        if receipt["session"] != self.identity or receipt["execution_date"] != path.name:
            raise ArtifactIntegrityError("staged native receipt identity changed")
        for name, digest in receipt["files"].items():
            verify_file(confined_regular_file(path, name), digest)
        atomic_write_bytes(path / "completed.json", canonical_json_bytes(receipt))

    def status(self) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            try:
                entries = self._inventory()
            except UnknownNativeStep:
                return {
                    **self.identity,
                    "state": "UNKNOWN",
                    "completed_sessions": None,
                    "last_execution_date": None,
                    "checkpoint_hash": None,
                    "reason": (
                        "Native step intent lacks a durable executed state; reconcile, never replay"
                    ),
                    "validation_verdict": "NOT_EVALUATED",
                }
        return {
            **self.identity,
            "completed_sessions": len(entries),
            "last_execution_date": entries[-1]["execution_date"] if entries else None,
            "checkpoint_hash": sha256_bytes(canonical_json_bytes(entries[-1])) if entries else None,
            "state": "ACTIVE",
            "validation_verdict": "NOT_EVALUATED",
        }

    def native_state(self) -> dict[str, Any] | None:
        from quantos.research.native_state import decode_native_state

        with exclusive_directory_lock(self.root):
            entries = self._inventory()
            if not entries:
                return None
            last = entries[-1]
            raw = confined_regular_file(
                self.root, f"steps/{last['execution_date']}/state.native.json"
            ).read_bytes()
            return decode_native_state(raw)

    def advance(
        self,
        binding: Any,
        signal: pd.DataFrame,
        signal_hash: str,
        day: date,
        *,
        continuous_compatible: bool,
        observation_hash: str,
        fault_after_native_export: bool = False,
    ) -> dict[str, Any]:
        """One actual trading session. fault hook is local engineering only, never MCP."""
        from quantos.research.native_state import decode_native_state, encode_native_state
        from quantos.research.personal_signal import dataset_binding_hash, verified_panel

        if not continuous_compatible:
            raise ValueError("snapshot units/history revised; native continuation must stop")
        frame = verified_panel(binding)
        sessions = sorted(frame.trade_date.unique())
        if day not in sessions or sessions.index(day) == 0:
            raise ValueError("non-session or previous signal session missing")
        prior_signal_day = sessions[sessions.index(day) - 1]
        if pd.Timestamp(prior_signal_day) not in signal.index.get_level_values("datetime"):
            raise ValueError("next-session signal missing; no stale carry-forward")
        with exclusive_directory_lock(self.root):
            entries = self._inventory()
            if binding.manifest.kind == "market":
                # Check the full actual account lifetime; an old completed event
                # before a fresh-cash account began is not a carried entitlement.
                first = date.fromisoformat(entries[0]["execution_date"]) if entries else day
                self._market_boundary(binding, day, start=first)
            previous = sha256_bytes(canonical_json_bytes(entries[-1])) if entries else None
            for entry in entries:
                if entry["execution_date"] == str(day):
                    if (
                        entry["dataset_hash"] != dataset_binding_hash(binding)
                        or entry["signal_hash"] != signal_hash
                    ):
                        raise ArtifactIntegrityError("duplicate day has different bound inputs")
                    return {**entry, "idempotent_reuse": True}
            if (
                entries
                and sessions[sessions.index(day) - 1].isoformat() != entries[-1]["execution_date"]
            ):
                raise ValueError("native continuity has a missing or reordered session")
            state: Any = None
            if entries:
                last_day = entries[-1]["execution_date"]
                state = decode_native_state(
                    confined_regular_file(
                        self.root, f"steps/{last_day}/state.native.json"
                    ).read_bytes()
                )
                if state["processed_date"] != last_day:
                    raise ArtifactIntegrityError("native state clock disagrees")
            step = self.root / "steps" / day.isoformat()
            step.mkdir(parents=True)
            fixed = {
                "execution_date": day.isoformat(),
                "dataset_hash": dataset_binding_hash(binding),
                "snapshot_hash": binding.manifest.snapshot_hash,
                "view_hash": binding.manifest.qlib_view_hash,
                "previous_snapshot_hash": entries[-1]["snapshot_hash"] if entries else None,
                "previous_checkpoint_hash": previous,
                "signal_hash": signal_hash,
                "observation_hash": observation_hash,
                "session": self.identity,
            }
            atomic_write_bytes(
                step / "started.json",
                canonical_json_bytes({**fixed, "started_at": datetime.now(UTC)}),
            )
            qlib: Any = importlib.import_module("qlib")
            qlib.init(provider_uri=str(binding.provider_root), region="cn", kernels=1)
            native: Any = importlib.import_module("qlib.backtest")
            config = native_config(
                binding, self.strategy, self.policy, signal, str(day), str(day), self.benchmark
            )
            config["strategy"]["kwargs"]["signal"] = signal
            strategy, executor = native.get_strategy_executor(
                strategy=config["strategy"], executor=config["executor"], **config["backtest"]
            )
            if state is not None:
                # Fresh executor construction called Account.reset. Restore the complete
                # Account into that same shared object AFTER infrastructure binding. No
                # account reset follows this: both strategy/executor see the restored object.
                executor.trade_account.__dict__.clear()
                executor.trade_account.__dict__.update(state["account"].__dict__)
                # Native benchmark initialization only refreshes its input series;
                # it does not clear accounts/returns/costs/turnover/history. Supply
                # only the prefix available in this newly bound view.
                benchmark_config = {
                    "benchmark": self.benchmark,
                    "start_time": entries[0]["execution_date"],
                    "end_time": str(day),
                }
                executor.trade_account.benchmark_config = benchmark_config
                executor.trade_account.portfolio_metrics.init_bench(
                    freq="day", benchmark_config=benchmark_config
                )
                strategy.last_rebalance_date = state["strategy_state"]["last_rebalance_date"]
                strategy.last_plan = state["strategy_state"]["last_plan"]
                executor.deal_day = state["executor_state"]["deal_day"]
                executor.dealt_order_amount = state["executor_state"]["dealt_order_amount"]
            executor.reset(start_time=str(day), end_time=str(day))
            strategy.reset(level_infra=executor.get_level_infra())
            decision = strategy.generate_trade_decision(
                state["last_execute_result"] if state else None
            )
            result = executor.execute(decision)
            strategy.post_exe_step(result)
            account = executor.trade_account
            state = {
                "account": account,
                "processed_date": str(day),
                "strategy_state": {
                    "last_rebalance_date": strategy.last_rebalance_date,
                    "last_plan": strategy.last_plan,
                },
                "executor_state": {
                    "deal_day": executor.deal_day,
                    "dealt_order_amount": executor.dealt_order_amount,
                },
                "last_execute_result": result,
            }
            atomic_write_bytes(step / "state.native.json", encode_native_state(state))
            atomic_write_bytes(
                step / "decision.native.json", encode_native_state(decision.get_decision())
            )
            atomic_write_bytes(step / "fills.native.json", encode_native_state(result))
            atomic_write_bytes(step / "targets.json", canonical_json_bytes(strategy.last_plan))
            receipt = {
                **fixed,
                "files": {
                    p.name: sha256_file(p)
                    for p in (
                        step / "state.native.json",
                        step / "decision.native.json",
                        step / "fills.native.json",
                        step / "targets.json",
                    )
                },
                "run_status": "SUCCEEDED",
                "validation_verdict": "NOT_EVALUATED",
                "native_clock": "EOD; no pending native order across sessions",
                "native_sell_restrictions": (
                    "Qlib Position settlement and Exchange; no full exchange T+1 qualification"
                ),
                "completed_at": datetime.now(UTC),
            }
            atomic_write_bytes(step / "executed.json", canonical_json_bytes(receipt))
            if fault_after_native_export:
                raise InterruptedError(
                    "engineering interruption after native export, before publication"
                )
            atomic_write_bytes(step / "completed.json", canonical_json_bytes(receipt))
            return receipt

    @staticmethod
    def _market_boundary(binding: Any, day: date, *, start: date | None = None) -> None:
        from quantos.research.personal_native import require_supported_market_period

        require_supported_market_period(binding, str(day), start=str(start) if start else None)
