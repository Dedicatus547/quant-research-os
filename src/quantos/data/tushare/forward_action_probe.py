"""Two bounded acquisition probes; transport success never grants event coverage."""

from __future__ import annotations

import argparse
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.data.tushare.acquisition import (
    AcquisitionLimiter,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource
from quantos.data.tushare.dividend_acquisition import FIELDS, PRIMARY_KEY
from quantos.data.tushare.forward_calendar import DiscardProviderOutput


def probe(root: Path, day: date, credential: str, *, client: Any = None) -> dict[str, Any]:
    if not credential or day >= datetime.now(UTC).date():
        raise ValueError("credential and a completed historical date required")
    root.mkdir(parents=True, exist_ok=False)
    requests = (
        TushareRequest(
            sequence=1,
            endpoint="dividend",
            params={"ann_date": day.strftime("%Y%m%d")},
            fields=FIELDS,
            primary_key=PRIMARY_KEY,
        ),
        TushareRequest(
            sequence=1,
            endpoint="anns_d",
            params={"ann_date": day.strftime("%Y%m%d")},
            fields=("ann_date", "ts_code", "name", "title", "url", "rec_time"),
            primary_key=("ts_code", "url"),
        ),
    )
    results = [
        acquire_action_request(root / request.endpoint, request, credential, client=client)
        for request in requests
    ]
    summary = {
        "results": results,
        "coverage_granted": False,
        "request_attempts": sum(r["request_attempts"] for r in results),
    }
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(summary))
    return summary


def acquire_action_request(
    target: Path,
    request: TushareRequest,
    credential: str,
    *,
    client: Any = None,
    limiter: AcquisitionLimiter | None = None,
) -> dict[str, Any]:
    policy = TushareExecutionPolicy(
        policy_id="forward-action-single-request/v1", requests_per_minute=60, max_attempts=1
    )
    spec = {"purpose": "PERMISSION_PROBE_ONLY", "request": request.model_dump(mode="json")}
    plan = TushareRequestPlan(
        build_spec_hash=sha256_bytes(canonical_json_bytes(spec)), requests=(request,)
    )
    for name, value in (
        ("spec", canonical_json_bytes(spec)),
        ("plan", plan.canonical_bytes()),
        ("policy", policy.canonical_bytes()),
    ):
        atomic_write_bytes(target / f"{name}.json", value)
    attempts = 0
    failure = "INITIALIZATION_FAILED"

    class SafeClient:
        def __init__(
            self, bound_request: TushareRequest, bound_target: Path, bound_source: Any
        ) -> None:
            self.request = bound_request
            self.target = bound_target
            self.source = bound_source

        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            nonlocal attempts, failure
            if (
                api_name != self.request.endpoint
                or fields != ",".join(self.request.fields)
                or kwargs != self.request.params
                or attempts
            ):
                raise RuntimeError("outside probe scope")
            attempts += 1
            atomic_write_bytes(
                self.target / "attempt.json",
                canonical_json_bytes(
                    {"endpoint": api_name, "params": kwargs, "started_at": datetime.now(UTC)}
                ),
            )
            failure = "PROVIDER_UNAVAILABLE"
            with (
                redirect_stdout(DiscardProviderOutput()),
                redirect_stderr(DiscardProviderOutput()),
            ):
                try:
                    frame = self.source.query(api_name, fields=fields, **kwargs)
                except Exception as error:
                    message = str(error).lower()
                    if any(s in message for s in ("权限", "积分", "permission", "unauthorized")):
                        failure = "PERMISSION_DENIED"
                    elif any(s in message for s in ("频次", "rate limit", "frequency")):
                        failure = "RATE_LIMITED"
                    raise RuntimeError("provider detail suppressed") from None
            failure = "RESPONSE_REJECTED"
            if (
                not isinstance(frame, pd.DataFrame)
                or tuple(frame.columns) != self.request.fields
                or len(frame) > 2000
                or credential in frame.to_json()
            ):
                raise RuntimeError(failure)
            values = {name: frame[name].tolist() for name in self.request.fields}
            if any(
                type(v) not in (str, int, float, type(None))
                for column in values.values()
                for v in column
            ):
                raise RuntimeError(failure)
            clean = pd.DataFrame(values, columns=list(self.request.fields))
            atomic_write_bytes(
                self.target / "provider-response.json",
                clean.to_json(orient="split", index=False).encode(),
            )
            failure = "SHARED_RESPONSE_VALIDATION_FAILED"
            return clean

    try:
        with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
            source = client if client is not None else TushareSnapshotSource(credential).client
        ledger = TusharePlanExecutor(
            SafeClient(request, target, source), policy, limiter=limiter
        ).execute(plan, target)
        result: dict[str, Any] = {
            "endpoint": request.endpoint,
            "status": "ACQUIRED_NOT_ADMITTED",
            "ledger_hash": ledger.content_hash,
            "rows": ledger.entries[0].response_row_count,
            "possible_truncation": ledger.entries[0].response_row_count >= 2000,
        }
    except Exception as error:
        result = {
            "endpoint": request.endpoint,
            "status": "FAILED",
            "reason": failure,
            "error_class": type(error).__name__,
        }
    result.update(request_attempts=attempts, received_at=datetime.now(UTC))
    atomic_write_bytes(target / "exit.json", canonical_json_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    print(
        canonical_json_bytes(
            probe(args.root, args.day, os.environ.get("TUSHARE_TOKEN", ""))
        ).decode()
    )
