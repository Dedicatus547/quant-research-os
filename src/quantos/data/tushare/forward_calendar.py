"""Acquire a bounded, observed trading calendar without requesting future prices."""

from __future__ import annotations

import argparse
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.snapshot import SnapshotBuildSpec, SnapshotSourceKind
from quantos.data.tushare.acquisition import (
    TushareExecutionPolicy,
    TusharePlanExecutor,
    plan_tushare_calendar_requests,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource


class DiscardProviderOutput(io.TextIOBase):
    def write(self, text: str) -> int:
        return len(text)


def acquire_calendar(
    root: Path, start: date, end: date, credential: str, *, client: Any = None
) -> dict[str, Any]:
    """Two single-attempt requests; provider output and exceptions never get logged.

    The shared executor retains each completed response/checkpoint immediately.
    A future date in this calendar is a schedule, never a future observed price.
    """
    if not credential or not 0 <= (end - start).days <= 365:
        raise ValueError("credential or bounded calendar range unavailable")
    root.mkdir(parents=True, exist_ok=False)
    spec = SnapshotBuildSpec(
        dataset_id="hs300-forward-calendar",
        source_kind=SnapshotSourceKind.TUSHARE,
        provider="tushare-pro",
        start_date=start,
        end_date=end,
        required_endpoints=("trade_cal",),
        normalizer_version="calendar-only-no-prices/v1",
        availability_policy_id="actual-acquisition-time/v1",
    )
    plan = plan_tushare_calendar_requests(spec)
    policy = TushareExecutionPolicy(
        policy_id="forward-calendar-two-requests/v1", requests_per_minute=60, max_attempts=1
    )
    for name, document in (("spec", spec), ("plan", plan), ("policy", policy)):
        atomic_write_bytes(root / f"{name}.json", document.canonical_bytes())
    allowed = {
        (r.endpoint, ",".join(r.fields), tuple(sorted(r.params.items()))) for r in plan.requests
    }
    attempts = 0
    failure = "INITIALIZATION_FAILED"

    class SafeClient:
        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            nonlocal attempts, failure
            key = (api_name, fields, tuple(sorted(kwargs.items())))
            if key not in allowed or attempts >= 2:
                failure = "REQUEST_SCOPE_REJECTED"
                raise RuntimeError(failure)
            attempts += 1
            atomic_write_bytes(
                root / f"attempt-{attempts:02d}.json",
                canonical_json_bytes(
                    {"endpoint": api_name, "params": kwargs, "started_at": datetime.now(UTC)}
                ),
            )
            failure = "PROVIDER_UNAVAILABLE"
            with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
                try:
                    frame = source.query(api_name, fields=fields, **kwargs)
                except Exception:
                    raise RuntimeError("provider detail suppressed") from None
            failure = "RESPONSE_REJECTED"
            columns = fields.split(",")
            if (
                not isinstance(frame, pd.DataFrame)
                or list(frame.columns) != columns
                or len(frame) > 366
                or credential in frame.to_json()
                or frame.duplicated(["exchange", "cal_date"]).any()
            ):
                raise RuntimeError(failure)
            values = {name: frame[name].tolist() for name in columns}
            if any(
                type(value) not in (str, int, float, type(None))
                for column in values.values()
                for value in column
            ):
                raise RuntimeError(failure)
            # Reconstruct to discard provider attrs and index metadata before persistence.
            clean = pd.DataFrame(values, columns=columns)
            if not clean.empty and (
                not clean.exchange.eq(str(kwargs["exchange"])).all()
                or not clean.cal_date.between(
                    start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
                ).all()
                or not clean.is_open.astype(str).isin(["0", "1"]).all()
            ):
                raise RuntimeError(failure)
            return clean

    try:
        with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
            source = client if client is not None else TushareSnapshotSource(credential).client
        ledger = TusharePlanExecutor(SafeClient(), policy).execute(plan, root)
        result = {
            "status": "ACQUIRED_NOT_VALIDATED",
            "ledger_hash": ledger.content_hash,
            "request_attempts": attempts,
            "received_at": datetime.now(UTC),
            "future_prices_requested": False,
        }
    except Exception:
        result = {"status": "FAILED", "reason": failure, "request_attempts": attempts}
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    result = acquire_calendar(args.root, args.start, args.end, os.environ.get("TUSHARE_TOKEN", ""))
    print(canonical_json_bytes(result).decode())
    raise SystemExit(0 if result["status"] == "ACQUIRED_NOT_VALIDATED" else 1)


if __name__ == "__main__":
    main()
