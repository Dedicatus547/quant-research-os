"""Bounded supplemental snapshot acquisition for two retained lifecycle gaps.

This module alone contacts Tushare. Downstream lifecycle adaptation consumes the
immutable raw responses and request ledgers offline. Credentials and provider
exception text never enter retained evidence.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.data.tushare.acquisition import (
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource


def acquire(root: Path) -> dict[str, Any]:
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=False)
    specification: dict[str, Any] = {
        "schema_version": "hs300-lifecycle-acquisition-spec/v1",
        "securities": ["600837.SH", "601989.SH"],
        "maximum_requests": 6,
        "maximum_attempts_each": 1,
        "scope": "stock_basic, bounded suspension and announcement metadata only",
        "authorization": "user 2026-10-23 lifecycle implementation and missing-data acquisition",
        "external_disclosure": (
            "fixed security codes, dates and requested fields to inherited Tushare service"
        ),
        "new_payment_or_account_switch": False,
    }
    atomic_write_bytes(root / "specification.json", canonical_json_bytes(specification))
    policy = TushareExecutionPolicy(
        policy_id="lifecycle-two-securities-20261023/v1",
        requests_per_minute=10,
        max_attempts=1,
    )
    atomic_write_bytes(root / "policy.json", policy.canonical_bytes())
    requests: list[TushareRequest] = []
    for code in specification["securities"]:
        requests.append(
            TushareRequest(
                sequence=1,
                endpoint="stock_basic",
                params={"ts_code": code, "list_status": "D"},
                fields=(
                    "ts_code",
                    "symbol",
                    "name",
                    "exchange",
                    "list_status",
                    "list_date",
                    "delist_date",
                ),
                primary_key=("ts_code",),
            )
        )
    for code, start, end in (
        ("600837.SH", "20241201", "20250331"),
        ("601989.SH", "20250701", "20250930"),
    ):
        requests.append(
            TushareRequest(
                sequence=1,
                endpoint="suspend_d",
                params={"ts_code": code, "start_date": start, "end_date": end},
                fields=("ts_code", "trade_date", "suspend_type", "suspend_timing"),
                primary_key=("ts_code", "trade_date", "suspend_type", "suspend_timing"),
            )
        )
    for code, start, end in (
        ("600837.SH", "20250201", "20250331"),
        ("601989.SH", "20250701", "20250930"),
    ):
        requests.append(
            TushareRequest(
                sequence=1,
                endpoint="anns_d",
                params={"ts_code": code, "start_date": start, "end_date": end},
                fields=("ann_date", "ts_code", "name", "title", "url", "rec_time"),
                primary_key=("ts_code", "ann_date", "title", "url"),
            )
        )
    token = os.environ.get("TUSHARE_TOKEN")
    outcomes: list[dict[str, Any]] = []
    outcome: dict[str, Any]
    if not token:
        outcome = {"status": "BLOCKED", "reason": "CREDENTIAL_UNAVAILABLE", "request_count": 0}
        atomic_write_bytes(root / "exit.json", canonical_json_bytes(outcome))
        return outcome
    source = TushareSnapshotSource(token)

    class SafeClient:
        classification = "UNCLASSIFIED"

        def query(self, api_name: str, fields: str = "", **kwargs: object) -> Any:
            self.classification = "UNCLASSIFIED"
            try:
                frame = source.client.query(api_name, fields=fields, **kwargs)
            except Exception as error:
                # Classify in memory only. Never retain arbitrary provider text or URLs.
                message = str(error).lower()
                if any(term in message for term in ("权限", "积分", "permission", "unauthorized")):
                    self.classification = "PERMISSION_DENIED"
                elif any(term in message for term in ("频次", "rate limit", "frequency")):
                    self.classification = "RATE_LIMITED"
                elif any(
                    term in type(error).__name__.lower()
                    for term in ("connect", "timeout", "proxy", "ssl")
                ):
                    self.classification = "TRANSPORT_UNAVAILABLE"
                else:
                    self.classification = "PROVIDER_UNAVAILABLE"
                raise RuntimeError("provider detail suppressed") from None
            # Fail closed if a provider unexpectedly echoes a credential in tabular data.
            if token in frame.to_json():
                self.classification = "SECRET_RESPONSE_REJECTED"
                raise RuntimeError("unsafe provider response rejected")
            return frame

    client = SafeClient()
    executor = TusharePlanExecutor(client, policy)
    transport_failed = False
    for index, request in enumerate(requests, start=1):
        case = root / f"request-{index:02d}"
        case.mkdir()
        plan = TushareRequestPlan(
            build_spec_hash=sha256_bytes(canonical_json_bytes(specification)), requests=(request,)
        )
        atomic_write_bytes(case / "plan.json", plan.canonical_bytes())
        if transport_failed:
            outcome = {"status": "NOT_ATTEMPTED", "reason": "PRIOR_TRANSPORT_UNAVAILABLE"}
        else:
            started = datetime.now(UTC)
            try:
                ledger = executor.execute(plan, case)
                outcome = {
                    "status": "SUCCEEDED",
                    "ledger_hash": ledger.content_hash,
                    "response_rows": ledger.entries[0].response_row_count,
                    "response_sha256": ledger.entries[0].response_sha256,
                }
            except Exception as error:
                outcome = {
                    "status": "FAILED",
                    "reason": client.classification,
                    "error_type": type(error).__name__,
                }
                transport_failed = client.classification == "TRANSPORT_UNAVAILABLE"
            outcome.update({"started_at": started, "completed_at": datetime.now(UTC)})
        outcome.update({"endpoint": request.endpoint, "request_hash": request.content_hash})
        atomic_write_bytes(case / "exit.json", canonical_json_bytes(outcome))
        outcomes.append(outcome)
    result = {
        "status": "COMPLETE" if all(o["status"] == "SUCCEEDED" for o in outcomes) else "INCOMPLETE",
        "request_count": sum(o["status"] != "NOT_ATTEMPTED" for o in outcomes),
        "requests": outcomes,
        "historical_vendor_vintage": False,
    }
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical_json_bytes(acquire(args.root)).decode())


if __name__ == "__main__":
    main()
