"""Collect dividend records for an explicit immutable snapshot membership union."""

from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
from pyrate_limiter import Duration, Limiter, Rate  # pyright: ignore[reportMissingTypeStubs]

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.data.snapshot import verify_snapshot
from quantos.data.tushare.acquisition import (
    AcquisitionLimiter,
    TushareRequest,
    TushareRequestLedger,
    TushareRequestPlan,
    load_acquired_rows,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource
from quantos.data.tushare.dividend_acquisition import FIELDS, PRIMARY_KEY
from quantos.data.tushare.forward_action_probe import acquire_action_request
from quantos.data.tushare.forward_calendar import DiscardProviderOutput


def acquire(
    root: Path, snapshot: Path, expected_hash: str, reuse_root: Path | None = None
) -> dict[str, Any]:
    manifest = verify_snapshot(snapshot)
    if manifest.snapshot_hash != expected_hash:
        raise ValueError("snapshot identity differs")
    credential = os.environ.get("TUSHARE_TOKEN", "")
    if not credential:
        raise ValueError("credential unavailable")
    table = cast(Any, pq).read_table(snapshot / "canonical/index_membership.parquet")
    codes = sorted(set(table.column("instrument_id").to_pylist()))
    if not 1 <= len(codes) <= 350:
        raise ValueError("bounded initial membership union required")
    root.mkdir(parents=True, exist_ok=False)
    atomic_write_bytes(
        root / "scope.json",
        canonical_json_bytes(
            {
                "snapshot_hash": expected_hash,
                "instrument_ids": codes,
                "max_attempts": len(codes),
                "max_rows_per_security": 2000,
                "coverage_granted": False,
                "purpose": "dividend inventory only; excludes mergers and other events",
            }
        ),
    )
    results: list[dict[str, Any]] = []
    limiter = cast(AcquisitionLimiter, Limiter(Rate(60, Duration.MINUTE), raise_when_fail=False))
    with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
        client = TushareSnapshotSource(credential).client
    for code in codes:
        start = time.monotonic()
        request = TushareRequest(
            sequence=1,
            endpoint="dividend",
            params={"ts_code": code},
            fields=FIELDS,
            primary_key=PRIMARY_KEY,
        )
        if reuse_root is not None and (reuse_root / code / "exit.json").is_file():
            old_root = reuse_root / code
            old = json.loads((old_root / "exit.json").read_bytes())
            if old.get("reason") == "SHARED_RESPONSE_VALIDATION_FAILED":
                if not (old_root / "provider-response.json").is_file():
                    raise ValueError("failed provider response unavailable")
                result = {
                    **old,
                    "request_attempts": 0,
                    "retained_failure_from": str(old_root.resolve()),
                }
                atomic_write_bytes(root / code / "exit.json", canonical_json_bytes(result))
                results.append({"instrument_id": code, **result})
                continue
            if old["status"] == "ACQUIRED_NOT_ADMITTED":
                if "reused_from" in old:
                    origin = Path(old["reused_from"]).resolve()
                    if not origin.is_relative_to(reuse_root.resolve().parent):
                        raise ValueError("reuse origin outside campaign")
                    old_root = origin
                plan = TushareRequestPlan.model_validate_json((old_root / "plan.json").read_bytes())
                ledger = TushareRequestLedger.model_validate_json(
                    (
                        old_root / "request-ledgers" / f"sha256-{old['ledger_hash']}.json"
                    ).read_bytes()
                )
                if plan.requests != (request,) or ledger.content_hash != old["ledger_hash"]:
                    raise ValueError("reuse identity differs")
                load_acquired_rows(plan, ledger, old_root)
                result = {**old, "request_attempts": 0, "reused_from": str(old_root.resolve())}
                atomic_write_bytes(root / code / "exit.json", canonical_json_bytes(result))
                results.append({"instrument_id": code, **result})
                continue
        result = acquire_action_request(
            root / code, request, credential, limiter=limiter, client=client
        )
        results.append({"instrument_id": code, **result})
        if result.get("reason") in {"PERMISSION_DENIED", "RATE_LIMITED"}:
            break
        time.sleep(max(0, 1.05 - (time.monotonic() - start)))
    summary = {
        "snapshot_hash": expected_hash,
        "expected_securities": len(codes),
        "completed_securities": len(results),
        "results": results,
        "request_attempts": sum(r["request_attempts"] for r in results),
        "coverage_granted": False,
    }
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(summary))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-hash", required=True)
    parser.add_argument("--reuse-root", type=Path)
    args = parser.parse_args()
    result = acquire(args.root, args.snapshot, args.snapshot_hash, args.reuse_root)
    print(canonical_json_bytes({k: v for k, v in result.items() if k != "results"}).decode())
