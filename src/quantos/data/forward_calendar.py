"""Append observed exchange calendar dates to a distinct derived Qlib view.

Feature bins and their historical calendar positions remain byte-for-byte intact.
No future price, membership or status row is created.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quantos.artifacts.store import atomic_write_bytes, publish_directory, sha256_file, verify_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.qlib_view import QlibViewFile, QlibViewManifest
from quantos.data.qlib_view import verify_qlib_view
from quantos.data.tushare.acquisition import (
    TushareRequestLedger,
    TushareRequestPlan,
    load_acquired_rows,
)
from quantos.integrations.qlib import run_checked, verify_official_qlib_tools


def observed_calendar(root: Path, ledger_hash: str) -> dict[str, Any]:
    plan = TushareRequestPlan.model_validate_json((root / "plan.json").read_bytes())
    ledger = TushareRequestLedger.model_validate_json(
        (root / "request-ledgers" / f"sha256-{ledger_hash}.json").read_bytes()
    )
    if ledger.content_hash != ledger_hash or ledger.plan_hash != plan.content_hash:
        raise ValueError("calendar ledger identity disagrees")
    if len(plan.requests) != 2 or {
        (r.endpoint, r.params.get("exchange")) for r in plan.requests
    } != {("trade_cal", "SSE"), ("trade_cal", "SZSE")}:
        raise ValueError("calendar requires exactly the two exchange requests")
    exit_record = json.loads((root / "exit.json").read_bytes())
    if (
        exit_record.get("ledger_hash") != ledger_hash
        or exit_record.get("status") != "ACQUIRED_NOT_VALIDATED"
    ):
        raise ValueError("calendar acquisition did not complete")
    received = datetime.fromisoformat(exit_record["received_at"])
    if received.tzinfo is None or not max(
        e.completed_at for e in ledger.entries
    ) <= received <= datetime.now(UTC):
        raise ValueError("calendar receipt time unknown or future")
    raw = load_acquired_rows(plan, ledger, root)["trade_cal"]
    per_exchange: dict[str, dict[date, bool]] = {"SSE": {}, "SZSE": {}}
    for row in raw:
        day = datetime.strptime(row["cal_date"], "%Y%m%d").date()
        exchange = row["exchange"]
        if (
            exchange not in per_exchange
            or row["is_open"] not in ("0", "1")
            or day in per_exchange[exchange]
        ):
            raise ValueError("calendar contains invalid or duplicate sessions")
        per_exchange[exchange][day] = row["is_open"] == "1"
    if not per_exchange["SSE"] or per_exchange["SSE"] != per_exchange["SZSE"]:
        raise ValueError("exchange calendar schedules disagree")
    days = sorted(per_exchange["SSE"])
    if (days[-1] - days[0]).days + 1 != len(days):
        raise ValueError("calendar has unobserved date gaps")
    for request in plan.requests:
        if days[0].strftime("%Y%m%d") != request.params.get("start_date") or days[-1].strftime(
            "%Y%m%d"
        ) != request.params.get("end_date"):
            raise ValueError("calendar response does not cover its requested bounds")
    return {
        "ledger_hash": ledger_hash,
        "received_at": received,
        "open_sessions": tuple(d for d in days if per_exchange["SSE"][d]),
        "source_hashes": {e.response_logical_path: e.response_sha256 for e in ledger.entries},
    }


def extend_qlib_calendar(
    original: Path,
    calendar_root: Path,
    ledger_hash: str,
    through: date,
    output_root: Path,
    qlib_source_root: Path,
) -> Path:
    manifest = verify_qlib_view(original)
    calendar = observed_calendar(calendar_root, ledger_hash)
    old = [date.fromisoformat(x) for x in (original / "calendars/day.txt").read_text().splitlines()]
    observed = calendar["open_sessions"]
    if not old or through not in observed or through < old[-1]:
        raise ValueError("explicit future terminal session required")
    if tuple(d for d in observed if old[0] <= d <= old[-1]) != tuple(old):
        raise ValueError("observed schedule changes historical Qlib calendar positions")
    extended = old + [d for d in observed if old[-1] < d <= through]
    tools = verify_official_qlib_tools(qlib_source_root)
    if (
        tools.dump_bin_sha256 != manifest.dump_bin_sha256
        or tools.health_check_sha256 != manifest.health_check_sha256
    ):
        raise ValueError("Qlib tools differ from original view")
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".forward-calendar-", dir=output_root) as temp:
        stage = Path(temp) / "view"
        shutil.copytree(original, stage)
        (stage / "manifest.json").rename(stage / "original-view-manifest.json")
        (stage / "calendars/day.txt").rename(stage / "original-calendar.txt")
        atomic_write_bytes(
            stage / "calendars/day.txt", ("\n".join(str(d) for d in extended) + "\n").encode()
        )
        for item in manifest.files:
            if item.logical_path.endswith(".bin") or item.logical_path.startswith("instruments/"):
                verify_file(stage / item.logical_path, item.sha256)
        proof = {
            "schema_version": "qlib-forward-calendar-spec/v1",
            "original_view_hash": manifest.view_hash,
            "calendar_ledger_hash": ledger_hash,
            "calendar_received_at": calendar["received_at"],
            "calendar_source_hashes": calendar["source_hashes"],
            "last_observed_price_session": old[-1],
            "schedule_through": through,
            "future_prices_created": False,
            "adapter_sha256": sha256_file(Path(__file__)),
            "semantic_samples_adoption": (
                "unchanged feature bytes, instruments and historical calendar positions"
            ),
        }
        atomic_write_bytes(stage / "forward-calendar.json", canonical_json_bytes(proof))
        for relative in [
            "plan.json",
            "exit.json",
            f"request-ledgers/sha256-{ledger_hash}.json",
            *calendar["source_hashes"],
        ]:
            atomic_write_bytes(
                stage / "calendar-source" / relative, (calendar_root / relative).read_bytes()
            )
        health = run_checked(
            [sys.executable, str(tools.check_data_health), "--qlib_dir", str(stage), "check_data"]
        )
        atomic_write_bytes(
            stage / "forward-health.json",
            canonical_json_bytes(
                {
                    "actual_exit": health.returncode,
                    "health_check_sha256": tools.health_check_sha256,
                    "original_view_hash": manifest.view_hash,
                }
            ),
        )
        files = tuple(
            QlibViewFile(
                logical_path=p.relative_to(stage).as_posix(),
                sha256=sha256_file(p),
                size_bytes=p.stat().st_size,
            )
            for p in sorted(stage.rglob("*"))
            if p.is_file()
        )
        result = QlibViewManifest.create(
            source_snapshot_hash=manifest.source_snapshot_hash,
            view_spec_hash=manifest.view_spec_hash,
            qlib_version=manifest.qlib_version,
            qlib_source_commit=manifest.qlib_source_commit,
            dump_bin_sha256=manifest.dump_bin_sha256,
            health_check_sha256=manifest.health_check_sha256,
            converter_inputs=manifest.converter_inputs,
            files=files,
            health_check_passed=health.returncode == 0,
            semantic_samples=manifest.semantic_samples,
            created_at=datetime.now(UTC),
        )
        atomic_write_bytes(
            stage / "manifest.json", canonical_json_bytes(result.model_dump(mode="python"))
        )
        destination = output_root / f"sha256-{result.view_hash}"
        publish_directory(stage, destination)
        verify_qlib_view(destination)
    return destination
