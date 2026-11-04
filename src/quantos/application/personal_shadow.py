"""Frozen observations to a complete native daily Qlib account.

The trusted authorizer and dispatcher are injected by local operator config.
Neither an observation nor its strategy proposal grants account execution rights.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantos.application.personal_observation import (
    SnapshotArrivalV2,
    corporate_actions_supported,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalExecutionPolicy, PersonalStrategy
from quantos.research.personal_session import NativePersonalSession
from quantos.research.personal_signal import load_strategy_signal, verified_panel


class PersonalShadowService:
    def __init__(
        self, root: Path, observations: Any, *, runtime_hash: str, authorizer: Any = None
    ) -> None:
        self.root = root.absolute()
        self.observations = observations
        self.runtime_hash = runtime_hash
        self.authorizer = authorizer

    def _plan(self, shadow_id: str) -> dict[str, Any]:
        if re.fullmatch(r"[0-9a-f]{64}", shadow_id) is None:
            raise ValueError("shadow_id must be an explicit content hash")
        plan = json.loads(
            confined_regular_file(self.root, f"shadow-accounts/{shadow_id}/plan.json").read_bytes()
        )
        if sha256_bytes(canonical_json_bytes(plan)) != shadow_id:
            raise ArtifactIntegrityError("native shadow plan identity differs")
        return plan

    def _session(self, shadow_id: str, plan: dict[str, Any]) -> NativePersonalSession:
        if plan["runtime_hash"] != self.runtime_hash:
            raise PermissionError("native account dependency change requires an explicit migration")
        return NativePersonalSession(
            self.root / "shadow-accounts" / shadow_id / "native",
            strategy=PersonalStrategy.model_validate(plan["strategy"]),
            policy=PersonalExecutionPolicy.model_validate(plan["policy"]),
            runtime_hash=self.runtime_hash,
            benchmark=plan["benchmark"],
        )

    def prepare(self, observation_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        observation = self.observations.plan(observation_id)
        request = observation["request"]
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end:
            raise ValueError("account observation period reversed")
        arrival = self.observations.metadata.get(request["dataset_id"])
        if isinstance(arrival, SnapshotArrivalV2) and start != arrival.fresh_account_start:
            raise PermissionError("source assessment is bound to a different fresh account start")
        calendar = [date.fromisoformat(d) for d in observation["calendar_sessions"]]
        if start not in calendar or end not in calendar or calendar.index(start) == 0:
            raise ValueError(
                "native account scope requires actual sessions and preceding signal day"
            )
        required = [calendar[i - 1] for i in range(calendar.index(start), calendar.index(end) + 1)]
        if not set(required) <= set(date.fromisoformat(d) for d in request["planned_dates"]):
            raise ValueError("observation plan does not cover account signal sessions")
        plan = {
            "schema_version": "personal-shadow-plan/v1",
            "observation_id": observation_id,
            "strategy": request["strategy"],
            "policy": request["policy"],
            "strategy_hash": observation["strategy_hash"],
            "policy_hash": observation["policy_hash"],
            "benchmark": request["benchmark"],
            "start_date": str(start),
            "end_date": str(end),
            "runtime_hash": self.runtime_hash,
            "initialization": "native fresh cash; no position import",
            "engineering_scope": "daily vendor-adjusted units; no independent dividend cash ledger",
        }
        shadow_id = sha256_bytes(canonical_json_bytes(plan))
        atomic_write_bytes(
            self.root / "shadow-accounts" / shadow_id / "plan.json", canonical_json_bytes(plan)
        )
        return {
            "shadow_id": shadow_id,
            "state": "NOT_STARTED",
            "plan": plan,
            "authorization_configured": self.authorizer is not None,
            "validation_verdict": "NOT_EVALUATED",
        }

    def advance(
        self,
        shadow_id: str,
        execution_date: str,
        observation_record_hash: str,
        execution_dataset_id: str,
    ) -> dict[str, Any]:
        plan = self._plan(shadow_id)
        day = date.fromisoformat(execution_date)
        if (
            not date.fromisoformat(plan["start_date"])
            <= day
            <= date.fromisoformat(plan["end_date"])
        ):
            raise PermissionError("execution date outside frozen account scope")
        record = self.observations.record(plan["observation_id"], observation_record_hash)
        if record["status"] not in {"EMITTED", "ABSTAIN"} or record["after_the_fact"]:
            raise PermissionError(
                "native account requires a contemporaneous emitted/abstain artifact"
            )
        if not record["continuous_compatible"]:
            raise PermissionError("observation snapshot revision stops continuous account")
        binding = self.observations.catalog.get(execution_dataset_id)
        if binding is None:
            raise ValueError("execution dataset not registered")
        arrival = self.observations.metadata.get(execution_dataset_id)
        if arrival is None or not corporate_actions_supported(arrival, day):
            raise PermissionError("execution snapshot arrival or corporate action state unknown")
        if isinstance(
            arrival, SnapshotArrivalV2
        ) and arrival.fresh_account_start != date.fromisoformat(plan["start_date"]):
            raise PermissionError("execution assessment changed the fresh account origin")
        calendar = [
            pd.Timestamp(x).date()
            for x in pd.read_csv(binding.provider_root / "calendars/day.txt", header=None)[0]
        ]
        if (
            day not in calendar
            or calendar.index(day) == 0
            or str(calendar[calendar.index(day) - 1]) != record["day"]
        ):
            raise ValueError(
                "account execution is not the next actual session after the frozen signal"
            )
        # Reuse read-only panel identities; newly arriving execution quotes may not
        # rewrite already issued signals, factors, membership or units.
        old_data = self.observations.record(plan["observation_id"], observation_record_hash)
        old_input = self.observations.input_manifest(old_data["input_hash"])
        previous_binding = self.observations.catalog[old_input["dataset_id"]]
        previous_calendar = [
            pd.Timestamp(x).date()
            for x in pd.read_csv(previous_binding.provider_root / "calendars/day.txt", header=None)[
                0
            ]
        ]
        if [d for d in previous_calendar if str(d) <= record["day"]] != [
            d for d in calendar if str(d) <= record["day"]
        ]:
            raise PermissionError("execution snapshot changes historical calendar prefix")
        if previous_binding.manifest.kind != binding.manifest.kind:
            raise PermissionError("native account cannot cross synthetic and market data")
        if binding.manifest.snapshot_hash != record["snapshot_hash"] and (
            arrival.previous_snapshot_hash != record["snapshot_hash"]
        ):
            raise PermissionError(
                "execution snapshot predecessor is not the frozen signal snapshot"
            )
        old = verified_panel(previous_binding)
        new = verified_panel(binding)
        boundary = date.fromisoformat(record["day"])
        keys = ["trade_date", "qlib_id"]
        old = old.loc[old.trade_date <= boundary].set_index(keys).sort_index()
        new = new.loc[new.trade_date <= boundary].set_index(keys).sort_index()
        if isinstance(arrival, SnapshotArrivalV2):
            from quantos.application.forward_continuity import align_historical_prefix

            new = align_historical_prefix(old, new)
        if not old.index.equals(new.index):
            raise PermissionError("execution snapshot changes historical universe or session keys")
        for frame in (old, new):
            if isinstance(arrival, SnapshotArrivalV2):
                from quantos.application.forward_continuity import source_observable_factors

                if not source_observable_factors(frame):
                    raise PermissionError("execution snapshot units/factors unknown")
                continue
            if (
                "adjustment_factor" not in frame
                or not np.isfinite(np.asarray(frame["adjustment_factor"], dtype=float)).all()
                or (frame["adjustment_factor"] <= 0).any()
            ):
                raise PermissionError("execution snapshot units/factors unknown")
        for column in ("close", "volume", "adjustment_factor", "amount_cny"):
            if (
                column not in old
                or column not in new
                or not np.allclose(old[column], new[column], rtol=1e-12, atol=1e-12, equal_nan=True)
            ):
                raise PermissionError(
                    "execution snapshot changes historical prices/units or lacks factors"
                )
        for column in ("is_member", "is_st", "is_suspended", "available_at"):
            if not old[column].equals(new[column]):
                raise PermissionError("execution snapshot changes historical PIT inputs")
        for column in ("is_listed", "lifecycle_state"):
            if (column in old) != (column in new) or (
                column in old and not old[column].equals(new[column])
            ):
                raise PermissionError("execution snapshot changes historical lifecycle inputs")
        if self.authorizer is None:
            raise PermissionError("no trusted native shadow advance authorization")
        from quantos.research.personal_signal import dataset_binding_hash

        authority = self.authorizer(
            plan,
            "shadow_advance",
            {
                "execution_date": execution_date,
                "dataset_hash": dataset_binding_hash(binding),
                "snapshot_hash": binding.manifest.snapshot_hash,
                "observation_record_hash": observation_record_hash,
            },
        )
        if not authority:
            raise PermissionError("native shadow advance not authorized")
        _, signal = load_strategy_signal(
            Path(record["signal"]["directory"]), record["signal"]["artifact_hash"]
        )
        with exclusive_directory_lock(self.root / "shadow-accounts" / shadow_id):
            stopped = self.root / "shadow-accounts" / shadow_id / "stop.json"
            if stopped.exists():
                raise PermissionError("native shadow account has stopped")
            session = self._session(shadow_id, plan)
            if session.status()["completed_sessions"] == 0 and execution_date != plan["start_date"]:
                raise ValueError("first native execution must equal frozen account start")
            result = session.advance(
                binding,
                signal,
                record["signal"]["artifact_hash"],
                day,
                continuous_compatible=True,
                observation_hash=observation_record_hash,
            )
        return {
            "shadow_id": shadow_id,
            "native_receipt": result,
            "validation_verdict": "NOT_EVALUATED",
        }

    def status(self, shadow_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("native holdings page requires offset>=0 and limit<=100")
        plan = self._plan(shadow_id)
        session = self._session(shadow_id, plan)
        result = session.status()
        stopped = self.root / "shadow-accounts" / shadow_id / "stop.json"
        state = session.native_state() if result["state"] != "UNKNOWN" else None
        account: Any = None if state is None else state["account"]
        holdings: list[dict[str, Any]] = []
        report_row: dict[str, Any] | None = None
        codes = [] if account is None else sorted(account.current_position.get_stock_list())

        def finite(value: Any) -> float | None:
            number = float(value)
            return number if math.isfinite(number) else None

        if account is not None:
            report = account.get_portfolio_metrics()[0]
            if not report.empty:
                report_row = {str(k): finite(v) for k, v in report.iloc[-1].items()}
            for code in codes[offset : offset + limit]:
                native = account.current_position
                holdings.append(
                    {
                        "instrument": code,
                        "adjusted_quantity": finite(native.get_stock_amount(code)),
                        "adjusted_price": finite(native.get_stock_price(code)),
                        "native_holding_sessions": native.get_stock_count(code, bar="day"),
                    }
                )
        return {
            "shadow_id": shadow_id,
            "plan": plan,
            "native": result,
            "state": "STOPPED" if stopped.exists() else result["state"],
            "native_cash_cny": finite(account.get_cash()) if account else None,
            "native_latest_report": report_row,
            "holdings": holdings,
            "holdings_count": len(codes),
            "next_offset": offset + len(holdings) if offset + len(holdings) < len(codes) else None,
            "validation_verdict": "NOT_EVALUATED",
        }

    def stop(self, shadow_id: str, reason: str) -> dict[str, Any]:
        self._plan(shadow_id)
        if not reason.strip() or len(reason) > 4000:
            raise ValueError("STOP requires a bounded reason")
        with exclusive_directory_lock(self.root / "shadow-accounts" / shadow_id):
            atomic_write_bytes(
                self.root / "shadow-accounts" / shadow_id / "stop.json",
                canonical_json_bytes({"reason": reason}),
            )
        return self.status(shadow_id)
