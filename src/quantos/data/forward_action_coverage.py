"""Offline source-scoped action checks for fresh native forward accounts.

The source inventory is finite, explicit and reproducible. This is not an
assertion that an issuer can never announce a later event or that a notice was
actually settled. New or ambiguous action candidates fail closed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from quantos.artifacts.store import confined_regular_file, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence_acquisition import EvidenceCollectionSpec
from quantos.data.forward_actions import (
    compare_dividend_variants,
    derive_sse_cash_notice,
    derive_szse_cash_notice,
)
from quantos.evidence.sources import SseAnnouncementSource, SzseAnnouncementSource

ACTION_TITLE = (
    r"权益分派|分红派息|吸收合并|现金选择权|换股|配股|送股|转增股本|"
    r"终止上市|退市|重整|拆细|合股|股份转换"
)


def assess_actions(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Recompute from bound originals; input cannot supply a PASS classification."""
    if spec.get("schema_version") != "forward-action-inputs/v1":
        raise ValueError("unsupported forward action inputs")
    start = date.fromisoformat(spec["fresh_account_start"])
    end = date.fromisoformat(spec["snapshot_end_date"])
    observed_files: dict[str, str] = {}
    receipt_times: list[datetime] = []

    def read(ref: dict[str, str]) -> bytes:
        path = confined_regular_file(root, ref["path"])
        raw = path.read_bytes()
        if sha256_bytes(raw) != ref["sha256"]:
            raise ValueError("action source original changed")
        observed_files[ref["path"]] = ref["sha256"]
        return raw

    def receipt(ref: dict[str, str]) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(read(ref))
        timestamp = datetime.fromisoformat(value["received_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > datetime.now(UTC):
            raise ValueError("source receipt clock missing or future")
        receipt_times.append(timestamp)
        return value

    from quantos.research.merger_entitlement_sources import (
        _Document,  # pyright: ignore[reportPrivateUsage]
    )

    historical_resolutions: dict[str, dict[str, Any]] = {}
    for resolution in spec.get("historical_restructures", []):
        code = resolution["instrument_id"]
        if code not in {"600221.SH", "600515.SH"}:
            raise ValueError("unsupported historical restructuring source rule")
        doc = _Document.read(read(resolution["pdf"]))
        if receipt(resolution["receipt"])["source_sha256"] != doc.raw_hash:
            raise ValueError("historical source receipt differs")
        doc.exact(("证券代码:" if code == "600221.SH" else "股票代码:") + code[:6])
        doc.matches(r"重整计划执行完毕(?:的)?公告")
        doc.exact("2021年12月31日")
        completion = doc.matches(
            r"(?:海南高院裁定确认|裁定确认)[^。]{1,140}重整计划[^。]{0,60}执行完毕"
        )[0]
        doc.matches(r"(?:已经完成|已完成)[^。]{0,120}股票转增及划转")
        if date(2021, 12, 31) >= start:
            raise ValueError("historical restructuring has not preceded fresh account")
        historical_resolutions[code] = {
            "period": "20210630",
            "source_sha256": doc.raw_hash,
            "completion": doc.span(completion),
        }

    merger_resolution: dict[str, Any] | None = None
    if spec.get("completed_merger"):
        resolution = spec["completed_merger"]
        doc = _Document.read(read(resolution["pdf"]))
        if receipt(resolution["receipt"])["source_sha256"] != doc.raw_hash:
            raise ValueError("merger source receipt differs")
        doc.exact("证券代码:601995")
        doc.exact("换股吸收合并东兴证券股份有限公司、信达证券股份有限公司")
        record = doc.matches(r"A股换股实施股权登记日为(\d{4})年(\d{1,2})月(\d{1,2})日")[0]
        listed = doc.matches(r"本次股票上市流通日期为(\d{4})年(\d{1,2})月(\d{1,2})日")[0]
        registration = doc.matches(
            r"新增A股股份登记手续已于(\d{4})年(\d{1,2})月(\d{1,2})日办理完毕"
        )[0]
        rights = doc.matches(r"异议股东收购请求权和现金选择权已实施完毕")[0]
        dates = [date(*(int(m[i]) for i in (1, 2, 3))) for m in (record, listed, registration)]
        if max(dates) >= start:
            raise ValueError("merger stock transition overlaps the fresh account")
        merger_resolution = {
            "source_sha256": doc.raw_hash,
            "record_date": str(dates[0]),
            "listing_date": str(dates[1]),
            "registration_date": str(dates[2]),
            "rights": doc.span(rights),
        }

    pool = set(
        cast(Any, pq)
        .read_table(BytesIO(read(spec["membership"])), columns=["instrument_id"])
        .column(0)
        .to_pylist()
    )
    if not pool or len(pool) > 350:
        raise ValueError("bounded explicit membership union required")
    if {item["instrument_id"] for item in spec["dividends"]} != pool:
        raise ValueError("dividend inventory must cover every historical member")
    vendor: dict[str, list[dict[str, Any]]] = {}
    unresolved: list[dict[str, str]] = []
    cash_facts: list[dict[str, Any]] = []
    for item in spec["dividends"]:
        receipt(item["receipt"])
        raw_vendor = read(item["source"])
        rows: list[dict[str, Any]]
        if item["source"]["path"].endswith(".parquet"):
            rows = cast(Any, pq).read_table(BytesIO(raw_vendor)).to_pylist()
        else:
            data = json.loads(raw_vendor)
            rows = [dict(zip(data["columns"], row, strict=True)) for row in data["data"]]
        if len(rows) >= 2000 or any(row["ts_code"] != item["instrument_id"] for row in rows):
            raise ValueError("dividend source truncated or wrong issuer")
        vendor[item["instrument_id"]] = rows
        for group in compare_dividend_variants(rows)["groups"]:
            if group["classification"] == "IMPLEMENTED_EVENT_FIELDS_CONFLICT":
                affected: list[dict[str, Any]] = [
                    rows[int(index)] for index in group["source_row_indices"]
                ]
                if any(
                    not row.get("record_date") or row["record_date"] >= start.strftime("%Y%m%d")
                    for row in affected
                ):
                    unresolved.append(
                        {
                            "instrument_id": item["instrument_id"],
                            "reason": "IMPLEMENTED_EVENT_FIELDS_CONFLICT",
                        }
                    )
        implemented = [row for row in rows if row["div_proc"] == "实施"]
        by_period = {row["end_date"] for row in implemented}
        for row in implemented:
            # Empty old rows remain visible. A dated event before a fresh cash
            # account cannot create an inherited entitlement for that account.
            dates = [row.get(key) for key in ("record_date", "ex_date", "pay_date", "div_listdate")]
            future = any(value and str(value) >= start.strftime("%Y%m%d") for value in dates)
            if not future:
                continue
            if any(
                Decimal(str(row.get(key) or 0)) != 0
                for key in ("stk_div", "stk_bo_rate", "stk_co_rate")
            ):
                unresolved.append(
                    {"instrument_id": item["instrument_id"], "reason": "FUTURE_STOCK_DISTRIBUTION"}
                )
            if not all(row.get(key) for key in ("record_date", "ex_date", "pay_date")):
                unresolved.append(
                    {
                        "instrument_id": item["instrument_id"],
                        "reason": "INCOMPLETE_FUTURE_EVENT_DATES",
                    }
                )
        for row in rows:
            if row["div_proc"] == "实施" or row["end_date"] in by_period:
                continue
            if row["end_date"] == historical_resolutions.get(item["instrument_id"], {}).get(
                "period"
            ):
                continue
            if any(
                Decimal(str(row.get(key) or 0)) > 0
                for key in ("stk_div", "stk_bo_rate", "stk_co_rate")
            ):
                unresolved.append(
                    {
                        "instrument_id": item["instrument_id"],
                        "reason": "UNRESOLVED_STOCK_PROPOSAL",
                        "period": row["end_date"],
                    }
                )

    candidates: list[dict[str, Any]] = []
    inventory_counts: dict[str, int] = {}
    coverage_end: dict[str, date] = {}
    all_source_ids: set[tuple[str, str]] = set()
    for inventory in spec["announcement_inventories"]:
        source = (
            SseAnnouncementSource() if inventory["venue"] == "SSE" else SzseAnnouncementSource()
        )
        collection = EvidenceCollectionSpec.model_validate_json(read(inventory["spec"]))
        venue = inventory["venue"]
        expected_start = (
            coverage_end[venue] + timedelta(days=1)
            if venue in coverage_end
            else date.fromisoformat(spec["announcement_start_date"])
        )
        if collection.start_date != expected_start or collection.end_date > end:
            raise ValueError("announcement chunks have a gap, overlap or future range")
        coverage_end[venue] = collection.end_date
        seen: set[str] = set()
        units = 0
        reported_total: int | None = None
        for index, ref in enumerate(inventory["pages"], 1):
            raw_page = read(ref)
            page_receipt = receipt(ref["receipt"])
            if (
                page_receipt["sha256"] != sha256_bytes(raw_page)
                or page_receipt["http_status"] != 200
            ):
                raise ValueError("announcement page receipt differs")
            page = source.parse_page(raw_page, collection, page=index)
            if reported_total is not None and page.reported_total != reported_total:
                raise ValueError("unstable announcement inventory total")
            reported_total = page.reported_total
            # Empty intervals require their original first response and receipt,
            # not an absent inventory or repeated empty pages.
            if max(1, page.total_pages) != len(inventory["pages"]):
                raise ValueError("incomplete announcement pagination")
            for candidate in page.candidates:
                if candidate.source_id in seen:
                    raise ValueError("duplicate announcement page or record")
                if (venue, candidate.source_id) in all_source_ids:
                    raise ValueError("duplicate announcement across chunks")
                all_source_ids.add((venue, candidate.source_id))
                seen.add(candidate.source_id)
                if set(candidate.entity_refs) & pool:
                    candidates.append(candidate.model_dump(mode="json"))
            units += page.collected_units
            if page.reported_total < units:
                raise ValueError("announcement total differs")
        if not inventory["pages"] or units != reported_total:
            raise ValueError("announcement metadata inventory incomplete")
        inventory_counts[venue] = inventory_counts.get(venue, 0) + units

    if coverage_end != {"SSE": end, "SZSE": end}:
        raise ValueError("both official venues must cover the complete declared date interval")

    documents = spec["documents"]
    classified: list[dict[str, str]] = []
    for candidate in candidates:
        if not re.search(ACTION_TITLE, candidate["title"]):
            continue
        identity, title = candidate["source_id"], candidate["title"]
        if identity not in documents:
            unresolved.append({"source_id": identity, "reason": "ACTION_ORIGINAL_MISSING"})
            continue
        doc = documents[identity]
        document_receipt = receipt(doc["receipt"])
        raw = read(doc["pdf"])
        if (
            document_receipt["url"] != candidate["document_url"]
            or document_receipt["source_sha256"] != sha256_bytes(raw)
            or document_receipt["http_status"] != 200
        ):
            raise ValueError("announcement original acquisition identity differs")
        instrument = next(code for code in candidate["entity_refs"] if code in pool)
        if re.search(r"(?:权益分派|分红派息)实施公告", title):
            publication = candidate["publication_value"][:10].replace("-", "")
            matches = [
                row
                for row in vendor[instrument]
                if row["div_proc"] == "实施"
                and (row.get("imp_ann_date") or row["ann_date"]) == publication
            ]
            if matches and all(
                row.get("record_date") and row["record_date"] < start.strftime("%Y%m%d")
                for row in matches
            ):
                classification = "RECORD_BEFORE_FRESH_ACCOUNT_NO_INHERITED_RIGHT"
            else:
                try:
                    fact = (
                        derive_sse_cash_notice
                        if instrument.endswith(".SH")
                        else derive_szse_cash_notice
                    )(raw, instrument)
                    matching = [
                        row
                        for row in matches
                        if row["record_date"] == fact["record_date"].replace("-", "")
                        and row["ex_date"] == fact["ex_date"].replace("-", "")
                        and row["pay_date"]
                        == fact["scheduled_depository_pay_date"].replace("-", "")
                        and Decimal(str(row["cash_div_tax"])) == Decimal(fact["cash_div_tax"])
                        and not any(
                            Decimal(str(row.get(k) or 0))
                            for k in ("stk_div", "stk_bo_rate", "stk_co_rate")
                        )
                    ]
                    if not matching:
                        raise ValueError("notice and vendor terms disagree")
                    cash_facts.append(fact)
                    classification = "ORDINARY_CASH_VENDOR_FACTOR_ONLY"
                except ValueError:
                    unresolved.append(
                        {
                            "source_id": identity,
                            "instrument_id": instrument,
                            "reason": "CASH_NOTICE_AMBIGUOUS_OR_DISAGREES",
                        }
                    )
                    continue
        elif re.search(r"(?:控股股东|持股5%以上股东).*可交换.*(?:债券|债)", title):
            classification = "SHAREHOLDER_EXCHANGEABLE_BOND_NOT_ISSUER_SHARE_CONVERSION"
        elif re.search(
            r"(?:权益分派|分红派息).*(?:回购价格|回购股份价格|股份回购价格)|(?:转债).*停止转股|(?:转债).*暂停转股",
            title,
        ):
            classification = "ISSUER_REPURCHASE_PRICE_OR_BOND_CONVERSION_NOTICE"
        elif (
            merger_resolution is not None
            and instrument in {"601995.SH", "601059.SH"}
            and "2026-10-13" <= candidate["publication_value"][:10] <= "2026-10-27"
            and re.search(r"换股|终止上市", title)
        ):
            doc = _Document.read(raw)
            doc.exact("证券代码:" + instrument[:6])
            doc.exact("信达证券")
            doc.matches(r"(?:中金公司|中国国际金融)")
            classification = "SOURCE_BOUND_MERGER_BEFORE_FRESH_ACCOUNT"
        elif "超额配股权失效" in title:
            doc = _Document.read(raw)
            doc.exact("证券代码:" + instrument[:6])
            doc.exact("公司并无亦不会根据超额配股权发行任何H股")
            doc.exact("本次超额配股权失效前后的股份无变动")
            classification = "H_SHARE_OVERALLOTMENT_EXPIRED_WITHOUT_SHARE_CHANGE"
        else:
            unresolved.append(
                {
                    "source_id": identity,
                    "instrument_id": instrument,
                    "reason": "OTHER_ACTION_REQUIRES_SOURCE_RULE",
                }
            )
            continue
        classified.append({"source_id": identity, "classification": classification})
    # A future implemented cash event must appear in the retained official feed.
    for instrument, rows in vendor.items():
        for row in rows:
            if (
                row["div_proc"] == "实施"
                and row.get("record_date")
                and row["record_date"] >= start.strftime("%Y%m%d")
                and not any(
                    fact["instrument_id"] == instrument
                    and fact["record_date"].replace("-", "") == row["record_date"]
                    for fact in cash_facts
                )
            ):
                unresolved.append(
                    {
                        "instrument_id": instrument,
                        "reason": "FUTURE_EVENT_OFFICIAL_TERMS_NOT_MATCHED",
                    }
                )
    return {
        "schema_version": "forward-action-assessment/v1",
        "status": "SUPPORTED_IN_DECLARED_SOURCE_SCOPE"
        if not unresolved
        else "UNSUPPORTED_OR_UNKNOWN",
        "snapshot_end_date": str(end),
        "fresh_account_start": str(start),
        "member_count": len(pool),
        "announcement_counts": inventory_counts,
        "pool_announcements": len(candidates),
        "classified": classified,
        "cash_facts": cash_facts,
        "historical_restructures": historical_resolutions,
        "completed_merger": merger_resolution,
        "unresolved": unresolved,
        "source_files": observed_files,
        "source_max_received_at": max(receipt_times).astimezone(UTC).isoformat(),
        "derivation_sha256": sha256_file(Path(__file__)),
        "input_spec_hash": sha256_bytes(canonical_json_bytes(spec)),
        "limitations": [
            "SOURCE_SCOPED_NOT_UNIVERSAL_ABSENCE_PROOF",
            "FRESH_CASH_NO_INHERITED_RIGHTS",
            "VENDOR_FACTOR_ONLY_NO_DIVIDEND_CASH_CREDIT",
            "NEW_OR_UNKNOWN_ACTION_HARD_STOP",
            "HISTORICAL_NON_VINTAGE",
        ],
    }
