"""Acquire two bounded dividend snapshots; all later interpretation is offline.

Each security receives one all-history request with no pagination or retry.
Successful transport does not establish historical coverage or vendor vintages.
"""

from __future__ import annotations

import argparse
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.data.tushare.acquisition import (
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource

SECURITIES = ("600837.SH", "601989.SH")
ROW_CAP = 2000
FIELDS = (
    "ts_code",
    "end_date",
    "ann_date",
    "div_proc",
    "stk_div",
    "stk_bo_rate",
    "stk_co_rate",
    "cash_div",
    "cash_div_tax",
    "record_date",
    "ex_date",
    "pay_date",
    "div_listdate",
    "imp_ann_date",
    "base_date",
    "base_share",
)
PRIMARY_KEY = ("ts_code", "end_date", "ann_date", "div_proc")


class _DiscardOutput(io.TextIOBase):
    """Discard SDK console output without retaining possible credential text."""

    def write(self, text: str) -> int:
        return len(text)


def _classify(error: Exception) -> str:
    # Inspect only in memory. Never include provider messages or URLs in evidence.
    message = str(error).lower()
    if any(term in message for term in ("权限", "积分", "permission", "unauthorized")):
        return "PERMISSION_DENIED"
    if any(term in message for term in ("频次", "rate limit", "frequency")):
        return "RATE_LIMITED"
    if any(term in type(error).__name__.lower() for term in ("connect", "timeout", "proxy", "ssl")):
        return "TRANSPORT_UNAVAILABLE"
    return "PROVIDER_UNAVAILABLE"


class _SafeClient:
    def __init__(self, source: TushareSnapshotSource, credential: str) -> None:
        self._source = source
        self._credential = credential
        self.classification = "UNCLASSIFIED"
        self.attempt_count = 0
        self.response_rows: int | None = None

    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        self.classification = "UNCLASSIFIED"
        self.response_rows = None
        if (
            api_name != "dividend"
            or fields != ",".join(FIELDS)
            or kwargs.get("ts_code") not in SECURITIES
            or kwargs.get("limit") != str(ROW_CAP)
            or set(kwargs) != {"ts_code", "limit"}
            or self.attempt_count >= len(SECURITIES)
        ):
            self.classification = "REQUEST_OUTSIDE_BOUND"
            raise RuntimeError("request outside fixed acquisition scope")
        self.attempt_count += 1
        try:
            with redirect_stdout(_DiscardOutput()), redirect_stderr(_DiscardOutput()):
                frame: Any = self._source.client.query(api_name, fields=fields, **kwargs)
        except Exception as error:
            self.classification = _classify(error)
            raise RuntimeError("provider detail suppressed") from None
        # Check the entire returned frame before the shared executor can persist it.
        if not isinstance(frame, pd.DataFrame):
            self.classification = "SCHEMA_INVALID"
            raise RuntimeError("unexpected provider response type")
        if self._credential in frame.to_json():
            self.classification = "SECRET_RESPONSE_REJECTED"
            raise RuntimeError("unsafe provider response rejected")
        self.response_rows = len(frame)
        if len(frame) > ROW_CAP:
            self.classification = "RESPONSE_ROW_CAP_EXCEEDED"
            raise RuntimeError("provider response exceeds fixed row cap")
        if tuple(frame.columns) != FIELDS:
            self.classification = "SCHEMA_INVALID"
            raise RuntimeError("provider response differs from locked fields")
        if bool(frame.duplicated(subset=list(PRIMARY_KEY)).any()):
            self.classification = "DUPLICATE_PRIMARY_KEY"
            raise RuntimeError("provider response has duplicate primary keys")
        if not frame.empty and not bool(frame["ts_code"].eq(str(kwargs["ts_code"])).all()):
            self.classification = "SECURITY_MISMATCH"
            raise RuntimeError("provider response security differs from request")
        # Arrow preserves DataFrame.attrs in Parquet metadata. Reconstruct only
        # the locked ordinary scalar values so provider attrs, axis names and
        # extension-array metadata can never reach the shared writer.
        values = {field: frame[field].tolist() for field in FIELDS}
        for column in values.values():
            for value in column:
                if type(value) not in (str, int, float, type(None)):
                    self.classification = "SCHEMA_INVALID"
                    raise RuntimeError("provider response contains a non-scalar value")
                if isinstance(value, str) and self._credential in value:
                    self.classification = "SECRET_RESPONSE_REJECTED"
                    raise RuntimeError("unsafe provider response rejected")
        frame = pd.DataFrame(values, columns=FIELDS)
        frame.attrs.clear()
        frame.index.name = None
        frame.columns.name = None
        self.classification = "RESPONSE_RECEIVED"
        return frame


def acquire(root: Path) -> dict[str, Any]:
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=False)
    specification: dict[str, Any] = {
        "schema_version": "hs300-dividend-acquisition-spec/v1",
        "securities": SECURITIES,
        "endpoint": "dividend",
        "date_scope": "all history returned for each fixed security; no date filter",
        "maximum_requests": 2,
        "maximum_attempts_each": 1,
        "maximum_response_rows_each": ROW_CAP,
        "pagination": False,
        "fields": FIELDS,
        "primary_key": PRIMARY_KEY,
        "authorization": "user 2026-10-23 merger entitlement implementation and missing data",
        "external_disclosure": (
            "fixed security codes, row limit and fields to inherited Tushare service"
        ),
        "new_payment_or_account_switch": False,
        "coverage_rule": (
            "empty or capped responses are UNKNOWN; history needs offline corroboration"
        ),
        "historical_vendor_vintage": False,
    }
    atomic_write_bytes(root / "specification.json", canonical_json_bytes(specification))
    policy = TushareExecutionPolicy(
        policy_id="dividend-two-securities-20261023/v1",
        requests_per_minute=10,
        max_attempts=1,
    )
    atomic_write_bytes(root / "policy.json", policy.canonical_bytes())
    cases: list[tuple[Path, TushareRequestPlan]] = []
    for index, code in enumerate(SECURITIES, start=1):
        case = root / f"request-{index:02d}"
        case.mkdir()
        request = TushareRequest(
            sequence=1,
            endpoint="dividend",
            params={"ts_code": code, "limit": str(ROW_CAP)},
            fields=FIELDS,
            primary_key=PRIMARY_KEY,
        )
        plan = TushareRequestPlan(
            build_spec_hash=sha256_bytes(canonical_json_bytes(specification)),
            requests=(request,),
        )
        atomic_write_bytes(case / "plan.json", plan.canonical_bytes())
        cases.append((case, plan))
    atomic_write_bytes(
        root / "plan.json",
        canonical_json_bytes(
            {
                "schema_version": "hs300-dividend-acquisition-plan-index/v1",
                "plans": [
                    {"logical_path": f"{case.name}/plan.json", "sha256": plan.content_hash}
                    for case, plan in cases
                ],
            }
        ),
    )
    token = os.environ.get("TUSHARE_TOKEN")
    client: _SafeClient | None = None
    executor: TusharePlanExecutor | None = None
    blocked_reason = "CREDENTIAL_UNAVAILABLE"
    if token:
        try:
            with redirect_stdout(_DiscardOutput()), redirect_stderr(_DiscardOutput()):
                source = TushareSnapshotSource(token)
                client = _SafeClient(source, token)
                executor = TusharePlanExecutor(client, policy)
        except Exception as error:
            blocked_reason = _classify(error)
    outcomes: list[dict[str, Any]] = []
    stop_reason: str | None = None
    for case, plan in cases:
        request = plan.requests[0]
        started = datetime.now(UTC)
        outcome: dict[str, Any] = {"coverage": "UNKNOWN", "attempt_count": 0}
        if client is None or executor is None:
            outcome.update(status="BLOCKED", reason=blocked_reason)
        elif stop_reason is not None:
            outcome.update(status="NOT_ATTEMPTED", reason=stop_reason)
        else:
            previous_attempts = client.attempt_count
            try:
                ledger = executor.execute(plan, case)
                rows = ledger.entries[0].response_row_count
                outcome.update(
                    status="SUCCEEDED",
                    ledger_hash=ledger.content_hash,
                    response_rows=rows,
                    response_sha256=ledger.entries[0].response_sha256,
                    response_logical_path=ledger.entries[0].response_logical_path,
                    coverage=("UNKNOWN" if rows in (0, ROW_CAP) else "NOT_ESTABLISHED"),
                    reason=("EMPTY_RESPONSE" if rows == 0 else "ROW_CAP_REACHED")
                    if rows in (0, ROW_CAP)
                    else "RESPONSE_BELOW_CAP_REQUIRES_OFFLINE_CORROBORATION",
                )
            except KeyboardInterrupt:
                outcome.update(status="FAILED", reason="INTERRUPTED")
                stop_reason = "PRIOR_INTERRUPTION"
            except Exception:
                outcome.update(
                    status="FAILED",
                    reason=(
                        client.classification
                        if client.classification not in {"UNCLASSIFIED", "RESPONSE_RECEIVED"}
                        else "ACQUISITION_FAILED"
                    ),
                    response_rows=client.response_rows,
                )
                if client.classification == "TRANSPORT_UNAVAILABLE":
                    stop_reason = "PRIOR_TRANSPORT_UNAVAILABLE"
            outcome["attempt_count"] = client.attempt_count - previous_attempts
        outcome.update(
            endpoint="dividend",
            ts_code=request.params["ts_code"],
            request_hash=request.content_hash,
            plan_hash=plan.content_hash,
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        atomic_write_bytes(case / "exit.json", canonical_json_bytes(outcome))
        outcomes.append(outcome)
    result = {
        "schema_version": "hs300-dividend-acquisition-exit/v1",
        "status": "COMPLETE" if all(o["status"] == "SUCCEEDED" for o in outcomes) else "INCOMPLETE",
        "coverage": "UNKNOWN",
        "request_count": sum(o["attempt_count"] for o in outcomes),
        "requests": outcomes,
        "historical_vendor_vintage": False,
    }
    if all(o["status"] == "BLOCKED" for o in outcomes):
        result["status"] = "BLOCKED"
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical_json_bytes(acquire(args.root)).decode())


if __name__ == "__main__":
    main()
