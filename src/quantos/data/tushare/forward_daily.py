"""Bounded daily acquisition; every subsequent research operation stays offline."""

from __future__ import annotations

import copy
import json
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence_acquisition import (
    EvidenceCollectionSpec,
    EvidenceHttpRequest,
    ExchangeVenue,
)
from quantos.data.forward_action_coverage import ACTION_TITLE, assess_actions
from quantos.data.forward_calendar import extend_qlib_calendar
from quantos.data.forward_catalog import build_forward_catalog
from quantos.data.qlib_view import QlibViewBuilder
from quantos.data.tushare.forward_dividends import acquire as acquire_dividends
from quantos.data.tushare.forward_snapshot import acquire as acquire_snapshot
from quantos.evidence.collector import PreparedHttpRequest, UrllibHttpClient
from quantos.evidence.sources import SseAnnouncementSource, SzseAnnouncementSource


def acquire_day(campaign: dict[str, Any], previous: dict[str, Any], day: date) -> dict[str, Any]:
    root = Path(campaign["root"])
    output = root / "days" / str(day)
    output.mkdir(parents=True, exist_ok=False)

    def ref(path: Path) -> dict[str, str]:
        return {"path": str(path.resolve().relative_to(root)), "sha256": sha256_file(path)}

    def write(path: Path, value: Any) -> None:
        atomic_write_bytes(path, canonical_json_bytes(value))

    parent_end = date.fromisoformat(previous["day"])
    sessions = [
        date.fromisoformat(value) for value in campaign["calendar_sessions"] if value <= str(day)
    ]
    bridge = 2 if str(day) == campaign["signal_dates"][0] else 1
    acquisition = output / "prices"
    price_result = acquire_snapshot(
        acquisition,
        sessions,
        sessions[0],
        reuse_root=Path(previous["acquisition_root"]),
        successor_dataset_id="hs300-forward-" + day.strftime("%Y%m%d") + "-v1",
        initial_bridge_sessions=bridge,
    )
    if price_result["status"] != "SUCCEEDED":
        raise RuntimeError("daily snapshot acquisition failed; retained parent is not replayed")
    digest = price_result["snapshot"]["sha256"]
    snapshot = acquisition / "snapshots" / ("sha256-" + digest)
    dividends = acquire_dividends(output / "dividends", snapshot, digest)
    attempts = price_result["request_attempts"] + dividends["request_attempts"]
    if dividends["completed_securities"] != dividends["expected_securities"]:
        raise RuntimeError("daily dividend inventory incomplete")
    inputs = copy.deepcopy(previous["action_inputs"])
    inputs["snapshot_end_date"] = str(day)
    inputs["membership"] = ref(snapshot / "canonical/index_membership.parquet")
    inputs["dividends"] = []
    for item in dividends["results"]:
        folder = output / "dividends" / item["instrument_id"]
        if not (folder / "provider-response.json").is_file():
            raise RuntimeError("daily dividend response unavailable")
        inputs["dividends"].append(
            {
                "instrument_id": item["instrument_id"],
                "source": ref(folder / "provider-response.json"),
                "receipt": ref(folder / "exit.json"),
            }
        )

    client = UrllibHttpClient(
        (
            "query.sse.com.cn",
            "www.szse.cn",
            "disc.static.szse.cn",
            "big5.sse.com.cn",
            "www.sse.com.cn",
            "static.cninfo.com.cn",
        )
    )
    last_http = time.monotonic()

    def send(request: PreparedHttpRequest, folder: Path, *, document: bool = False) -> Any:
        nonlocal attempts, last_http
        if attempts >= 500:
            raise RuntimeError("daily acquisition attempt budget exhausted")
        time.sleep(max(0, 1.05 - (time.monotonic() - last_http)))
        last_http = time.monotonic()
        attempts += 1
        write(folder / "request.json", request.contract.canonical_payload())
        write(
            folder / "attempt.json",
            {
                "started_at": datetime.now(UTC),
                "total_daily_attempt": attempts,
                "max_bytes": 8388608 if document else 1048576,
            },
        )
        response = client.send(
            request, timeout_seconds=20, max_response_bytes=8388608 if document else 1048576
        )
        atomic_write_bytes(folder / ("raw.pdf" if document else "response.bin"), response.body)
        if response.status_code != 200:
            raise RuntimeError("official source HTTP response rejected")
        metadata = {
            "http_status": response.status_code,
            "received_at": response.observed_at,
            "sha256": sha256_bytes(response.body),
        }
        if document:
            metadata.update(
                url=request.contract.url,
                source_sha256=metadata["sha256"],
                status="RETAINED_NOT_ADMITTED",
                request_attempts=1,
            )
        write(folder / ("exit.json" if document else "response.json"), metadata)
        return response

    candidates: list[dict[str, Any]] = []
    for source in (SseAnnouncementSource(), SzseAnnouncementSource()):
        collection = EvidenceCollectionSpec(
            collection_id="forward-daily",
            venues=(source.venue,),
            start_date=parent_end + timedelta(days=1),
            end_date=day,
            page_size=50,
            max_announcements=25000,
        )
        folder = output / "announcements" / str(source.venue)
        write(folder / "spec.json", collection.canonical_payload())
        pages: list[dict[str, Any]] = []
        for number in range(1, 501):
            request = source.build_request(collection, page=number, sequence=number)
            page_folder = folder / f"page-{number:03d}"
            response = send(
                PreparedHttpRequest(
                    contract=request.contract, body=request.body, headers=request.headers
                ),
                page_folder,
            )
            page = source.parse_page(response.body, collection, page=number)
            item: dict[str, Any] = ref(page_folder / "response.bin")
            item["receipt"] = ref(page_folder / "response.json")
            pages.append(item)
            candidates.extend(candidate.model_dump(mode="json") for candidate in page.candidates)
            # A zero-result interval still has one retained HTTP response.
            if number >= max(1, page.total_pages):
                break
        inputs["announcement_inventories"].append(
            {"venue": str(source.venue), "spec": ref(folder / "spec.json"), "pages": pages}
        )

    # The frozen raw baseline contains all issuers. If the historical membership
    # union grows, assess_actions will reject any missing old original explicitly.
    pool = {item["instrument_id"] for item in dividends["results"]}
    for candidate in candidates:
        if not set(candidate["entity_refs"]) & pool or not re.search(
            ACTION_TITLE, candidate["title"]
        ):
            continue
        identity = candidate["source_id"]
        if identity in inputs["documents"]:
            continue
        folder = output / "documents" / sha256_bytes(identity.encode())
        request = EvidenceHttpRequest(
            sequence=attempts + 1,
            venue=ExchangeVenue(candidate["venue"]),
            purpose="DOCUMENT",
            method="GET",
            url=candidate["document_url"],
        )
        send(PreparedHttpRequest(contract=request, body=None, headers=()), folder, document=True)
        inputs["documents"][identity] = {
            "pdf": ref(folder / "raw.pdf"),
            "receipt": ref(folder / "exit.json"),
        }
    write(output / "action-inputs.json", inputs)
    assessment = assess_actions(root, inputs)
    write(output / "action-assessment.json", assessment)
    qlib_source = Path(campaign["qlib_source_root"])
    built = QlibViewBuilder().build(snapshot, output / "qlib-views", qlib_source)
    view = extend_qlib_calendar(
        built.path,
        Path(campaign["calendar_root"]),
        campaign["calendar_ledger_hash"],
        date.fromisoformat(campaign["execution_dates"][-1]),
        output / "forward-views",
        qlib_source,
    )
    catalog = build_forward_catalog(snapshot, view, output / "catalog")
    result = {
        "day": str(day),
        "acquisition_root": str(acquisition),
        "snapshot_hash": digest,
        "catalog": catalog,
        "action_inputs": inputs,
        "assessment": assessment,
        "request_attempts": attempts,
        "received_at": datetime.now(UTC),
    }
    write(output / "acquisition-result.json", result)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        acquire_day(
            json.loads(args.campaign.read_bytes()),
            json.loads(args.previous.read_bytes()),
            args.day,
        )
    except Exception as error:
        # Provider exception text is never a durable diagnostic channel.
        print(
            canonical_json_bytes({"state": "FAILED", "error_type": type(error).__name__}).decode()
        )
        raise SystemExit(1) from None
