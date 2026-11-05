"""Finite initial forward-study acquisition using the existing snapshot pipeline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes, sha256_file, verify_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.snapshot import DEFAULT_SYNTHETIC_ENDPOINTS, SnapshotBuildSpec
from quantos.data.tushare.acquisition import (
    RequestLedgerEntry,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
    plan_tushare_requests,
)
from quantos.data.tushare.capabilities import TushareSnapshotSource
from quantos.data.tushare.forward_calendar import DiscardProviderOutput
from quantos.data.tushare.snapshot import LiveTushareSnapshotBuilder


def acquire(
    root: Path,
    sessions: list[date],
    membership_start: date,
    *,
    reuse_root: Path | None = None,
    successor_dataset_id: str | None = None,
    initial_bridge_sessions: int = 1,
) -> dict[str, Any]:
    maximum = 160 if successor_dataset_id else 80
    if initial_bridge_sessions not in (1, 2):
        raise ValueError("initial bridge is bounded to one or two actual sessions")
    if not 1 <= len(sessions) <= maximum or sorted(set(sessions)) != sessions:
        raise ValueError("acquisition requires bounded explicit actual sessions")
    if membership_start != sessions[0]:
        raise ValueError("membership source dates must remain inside the snapshot range")
    credential = os.environ.get("TUSHARE_TOKEN", "")
    if not credential:
        raise ValueError("credential unavailable")
    root.mkdir(parents=True, exist_ok=False)
    spec = SnapshotBuildSpec.model_validate(
        {
            "dataset_id": successor_dataset_id or "hs300-forward-initial-20261104-v1",
            "source_kind": "TUSHARE",
            "provider": "tushare-pro",
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "required_endpoints": DEFAULT_SYNTHETIC_ENDPOINTS,
            "normalizer_version": "quantos-tushare-historical-index-union-normalizer/v2",
            "availability_policy_id": "cn-daily-conservative/v1",
        }
    )
    base = plan_tushare_requests(spec, sessions)
    if successor_dataset_id is not None:
        if reuse_root is None:
            raise ValueError("daily successor requires its retained acquisition parent")
        parent_spec = SnapshotBuildSpec.model_validate_json((reuse_root / "spec.json").read_bytes())
        parent_plan = TushareRequestPlan.model_validate_json(
            (reuse_root / "plan.json").read_bytes()
        )
        new_sessions = [day for day in sessions if day > parent_spec.end_date]
        if (
            parent_spec.start_date != spec.start_date
            or len(new_sessions) != initial_bridge_sessions
            or new_sessions[-1] != spec.end_date
            or parent_plan.build_spec_hash != parent_spec.content_hash
        ):
            raise ValueError(
                "successor must append its bounded actual sessions to the fixed origin"
            )
        delta_spec = spec.model_copy(
            update={"start_date": parent_spec.end_date + timedelta(days=1)}
        )
        delta_plan = plan_tushare_requests(delta_spec, new_sessions)
        retained = list(parent_plan.requests)
        shapes = {(r.endpoint, tuple(sorted(r.params.items()))) for r in retained}
        for request in delta_plan.requests:
            if (request.endpoint, tuple(sorted(request.params.items()))) in shapes:
                continue
            retained.append(request.model_copy(update={"sequence": len(retained) + 1}))
        base = TushareRequestPlan(build_spec_hash=spec.content_hash, requests=tuple(retained))
    requests: list[TushareRequest] = []
    for request in base.requests:
        if request.endpoint == "index_weight" and successor_dataset_id is None:
            request = request.model_copy(
                update={
                    "params": {**request.params, "start_date": membership_start.strftime("%Y%m%d")}
                }
            )
        requests.append(request)
    plan = TushareRequestPlan(build_spec_hash=spec.content_hash, requests=tuple(requests))
    policy = TushareExecutionPolicy(
        policy_id="hs300-forward-initial-single-attempt/v1", requests_per_minute=60, max_attempts=1
    )
    for name, document in (("spec", spec), ("plan", plan), ("policy", policy)):
        atomic_write_bytes(root / f"{name}.json", document.canonical_bytes())
    reused: list[dict[str, str]] = []
    if reuse_root is not None:
        parent = TushareRequestPlan.model_validate_json((reuse_root / "plan.json").read_bytes())
        parent_hashes = {r.content_hash for r in parent.requests}
        for request in plan.requests:
            if request.content_hash not in parent_hashes:
                continue
            if successor_dataset_id is not None and request.endpoint == "stock_basic":
                continue
            checkpoint = Path("checkpoints") / f"sha256-{request.content_hash}.json"
            entry = RequestLedgerEntry.model_validate_json((reuse_root / checkpoint).read_bytes())
            if entry.request_hash != request.content_hash:
                raise ValueError("reused checkpoint identity differs")
            verify_file(reuse_root / entry.response_logical_path, entry.response_sha256)
            for relative in (checkpoint, Path(entry.response_logical_path)):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(reuse_root / relative, target)
            reused.append(
                {"request_hash": request.content_hash, "response_sha256": entry.response_sha256}
            )
        atomic_write_bytes(
            root / "reuse.json",
            canonical_json_bytes(
                {
                    "parent_plan_hash": parent.content_hash,
                    "parent_exit_sha256": sha256_file(reuse_root / "exit.json"),
                    "parent_root": str(reuse_root.resolve()),
                    "reused": reused,
                }
            ),
        )
    allowed = {
        (r.endpoint, ",".join(r.fields), tuple(sorted(r.params.items()))) for r in plan.requests
    }
    if successor_dataset_id is not None and len(plan.requests) - len(reused) > 20:
        raise ValueError("daily price acquisition exceeds its bounded request allocation")
    attempts = 0
    failure = "INITIALIZATION_FAILED"

    class SafeClient:
        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            nonlocal attempts, failure
            if (api_name, fields, tuple(sorted(kwargs.items()))) not in allowed or attempts >= len(
                plan.requests
            ):
                failure = "REQUEST_SCOPE_REJECTED"
                raise RuntimeError(failure)
            attempts += 1
            atomic_write_bytes(
                root / "attempts" / f"{attempts:04d}.json",
                canonical_json_bytes(
                    {"endpoint": api_name, "params": kwargs, "started_at": datetime.now(UTC)}
                ),
            )
            failure = "PROVIDER_UNAVAILABLE"
            with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
                try:
                    frame: Any = source.query(api_name, fields=fields, **kwargs)
                except Exception:
                    raise RuntimeError("provider detail suppressed") from None
            failure = "RESPONSE_REJECTED"
            columns = fields.split(",")
            if (
                not isinstance(frame, pd.DataFrame)
                or list(frame.columns) != columns
                or len(frame) > 10000
                or credential in frame.to_json()
            ):
                raise RuntimeError(failure)
            values = {name: frame[name].tolist() for name in columns}
            if any(
                type(v) not in (str, int, float, type(None)) for col in values.values() for v in col
            ):
                raise RuntimeError(failure)
            return pd.DataFrame(values, columns=columns)

    try:
        with redirect_stdout(DiscardProviderOutput()), redirect_stderr(DiscardProviderOutput()):
            source = TushareSnapshotSource(credential).client
        ledger = TusharePlanExecutor(SafeClient(), policy).execute(plan, root)
        failure = "SNAPSHOT_VALIDATION_FAILED"
        snapshot = LiveTushareSnapshotBuilder().build(spec, plan, ledger, root, root / "snapshots")
        result = {
            "status": "SUCCEEDED",
            "snapshot": snapshot.reference.model_dump(mode="json"),
            "request_attempts": attempts,
            "reused_requests": len(reused),
            "received_at": datetime.now(UTC),
        }
    except Exception as error:
        result = {"status": "FAILED", "reason": failure, "request_attempts": attempts}
        report = getattr(error, "quality_report", None)
        if report is not None:
            atomic_write_bytes(root / "quality-report.json", report.canonical_bytes())
    atomic_write_bytes(root / "exit.json", canonical_json_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--membership-start", type=date.fromisoformat, required=True)
    parser.add_argument("--reuse-root", type=Path)
    parser.add_argument("--successor-dataset-id")
    parser.add_argument("--initial-bridge-sessions", type=int, default=1)
    args = parser.parse_args()
    result = acquire(
        args.root,
        [date.fromisoformat(x) for x in json.loads(args.sessions.read_bytes())],
        args.membership_start,
        reuse_root=args.reuse_root,
        successor_dataset_id=args.successor_dataset_id,
        initial_bridge_sessions=args.initial_bridge_sessions,
    )
    print(canonical_json_bytes(result).decode())
    raise SystemExit(0 if result["status"] == "SUCCEEDED" else 1)
