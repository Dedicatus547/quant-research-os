"""Offline, explicit parsers for retained official lifecycle source facts.

These limited rules bind structural dates and conservative account stop windows.
They do not infer announcement sentiment, alpha, trading foresight or settlement.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
from pypdf import PdfReader

from quantos.artifacts.store import confined_regular_file
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hs300_lifecycle import LifecycleFactBundle


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def parse_exchange_delisting(raw: bytes, *, expected_code: str) -> dict[str, str]:
    """Require the actual issuer code and explicit exchange termination sentence."""
    parser = _Text()
    parser.feed(raw.decode("utf-8"))
    normalized = re.sub(r"\s+", "", "".join(parser.parts))
    if f"证券代码\uff1a{expected_code}" not in normalized:
        raise ValueError("official delisting source does not identify the expected security")
    pattern = r"决定自(\d{4})年(\d{1,2})月(\d{1,2})日起终止其股票在本所上市交易"
    matches = list(re.finditer(pattern, normalized))
    dates = {date(*(int(part) for part in match.groups())) for match in matches}
    if len(dates) != 1:
        raise ValueError("official delisting effective date is missing or ambiguous")
    return {
        "instrument_id": expected_code + ".SH",
        "delist_date": next(iter(dates)).isoformat(),
        "parser_rule": "explicit_exchange_termination_sentence/v1",
        "source_span": matches[0].group(0),
    }


@lru_cache(maxsize=8)
def _pdf_pages(raw: bytes) -> tuple[str, ...]:
    """Cache only immutable source bytes, never an mtime or a producer's PASS flag."""
    return tuple(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)


def verify_lifecycle_source_values(facts: LifecycleFactBundle, root: Path) -> None:
    """Recompute adopted structural values from actual originals without an LLM.

    The retained derivation spec selects fixed rules and sources; it cannot supply
    replacement dates or a PASS flag. Every security and unsupported event must
    be covered by one of the bounded deterministic rules below.
    """
    import json

    if facts.source_vintage == "synthetic":
        return
    source_by_id = {source.source_id: source for source in facts.sources}

    def raw(source_id: str) -> bytes:
        source = source_by_id[source_id]
        value = confined_regular_file(root, source.logical_path).read_bytes()
        if sha256_bytes(value) != source.sha256:
            raise ValueError("lifecycle derivation source bytes changed")
        return value

    def rows(source_id: str) -> list[dict[str, Any]]:
        return cast(Any, pq).read_table(BytesIO(raw(source_id))).to_pylist()

    if facts.derivation_source_id is None:
        raise ValueError("market lifecycle facts require a deterministic derivation spec")
    spec = json.loads(raw(facts.derivation_source_id))
    if spec.get("schema_version") != "hs300-lifecycle-derivation-spec/v1":
        raise ValueError("unknown lifecycle derivation spec")
    securities = {fact.instrument_id: fact for fact in facts.securities}
    events = {event.event_id: event for event in facts.events}
    for event in facts.events:
        if event.related_instrument_ids or (
            event.event_type != "CASH_OPTION" and event.entitlement_window_start is not None
        ):
            raise ValueError("lifecycle event contains unsupported unverified boundary fields")
    checked_securities: set[str] = set()
    checked_events: set[str] = set()
    for rule in spec["rules"]:
        name, source_id = rule["rule"], rule["source_id"]
        if name == "canonical-instrument-lifecycle/v1":
            for row in rows(source_id):
                code = row["instrument_id"]
                if code not in securities:
                    raise ValueError("lifecycle derivation lacks an original security")
                fact = securities[code]
                if (
                    source_id not in fact.source_ids
                    or fact.list_date != row["list_date"]
                    or fact.delist_date != row["delist_date"]
                ):
                    raise ValueError(
                        "lifecycle security dates do not match original instrument rows"
                    )
                checked_securities.add(code)
                for event in facts.events:
                    if event.instrument_id == code and event.event_type == "DELISTING":
                        if (
                            source_id not in event.source_ids
                            or event.boundary_date != fact.delist_date
                        ):
                            raise ValueError(
                                "delisting boundary does not match original instrument date"
                            )
                        checked_events.add(event.event_id)
        elif name == "official-exchange-delisting/v1":
            code = rule["instrument_id"]
            parsed = parse_exchange_delisting(raw(source_id), expected_code=code[:6])
            if parsed["delist_date"] != str(securities[code].delist_date):
                raise ValueError("official exchange and lifecycle delisting dates disagree")
        elif name == "official-cash-registration-window/v1":
            event = events[rule["event_id"]]
            pages = _pdf_pages(raw(source_id))
            normalized = re.sub(r"\s+", "", "".join(pages))
            if f"证券代码\uff1a{event.instrument_id[:6]}" not in normalized:
                raise ValueError("cash-option original PDF issuer identity disagrees")
            page = rule["physical_page"]
            if not isinstance(page, int) or not 1 <= page <= len(pages):
                raise ValueError("cash-option physical page is invalid")
            parsed = parse_cash_entitlement_window(
                pages[page - 1], expected_code=event.instrument_id[:6]
            )
            if (
                source_id not in event.source_ids
                or event.event_type != "CASH_OPTION"
                or str(event.entitlement_window_start) != parsed["window_start"]
                or str(event.boundary_date) != parsed["window_start"]
            ):
                raise ValueError("cash-option boundary does not match original registration window")
            checked_events.add(event.event_id)
        elif name == "vendor-continuous-terminal-suspension/v1":
            event = events[rule["event_id"]]
            dates = {
                datetime.strptime(row["trade_date"], "%Y%m%d").date()
                for row in rows(source_id)
                if row["ts_code"] == event.instrument_id and row["suspend_type"] == "S"
            }
            delist = securities[event.instrument_id].delist_date
            if not dates or delist is None:
                raise ValueError("terminal suspension source is incomplete")
            start = min(dates)
            expected = {
                row["trade_date"]
                for row in rows(rule["calendar_source_id"])
                if row["is_open"] and start <= row["trade_date"] < delist
            }
            if (
                source_id not in event.source_ids
                or dates != expected
                or event.event_type != "MERGER_EXCHANGE"
                or event.boundary_date != start
            ):
                raise ValueError("terminal suspension boundary does not match source sessions")
            checked_events.add(event.event_id)
        else:
            raise ValueError("unimplemented lifecycle derivation rule")
    if checked_securities != set(securities) or checked_events != set(events):
        raise ValueError("lifecycle facts contain unsupported unverified structural values")


def parse_cash_entitlement_window(page_text: str, *, expected_code: str) -> dict[str, str]:
    """Parse the explicit continuous-holding interval from the issuer's A-share notice.

    Callers separately verify issuer identity on the complete retained document;
    this page must explicitly describe the shareholder-registration interval.
    This returns an account validity boundary, never an eligibility/exit signal.
    """
    if not re.fullmatch(r"[0-9]{6}", expected_code):
        raise ValueError("invalid security code")
    normalized = re.sub(r"\s+", "", page_text)
    if "现金选择权" not in normalized or "股权登记日" not in normalized:
        raise ValueError("source page does not specify a cash-option registration interval")
    pattern = (
        r"即(\d{4})年(\d{1,2})月(\d{1,2})日至"
        r"(\d{4})年(\d{1,2})月(\d{1,2})日"
    )
    matches = list(re.finditer(pattern, normalized))
    pairs = {
        (date(*(int(p) for p in m.groups()[:3])), date(*(int(p) for p in m.groups()[3:])))
        for m in matches
    }
    if len(pairs) != 1:
        raise ValueError("cash-option registration interval is missing or ambiguous")
    start, end = next(iter(pairs))
    if start > end:
        raise ValueError("cash-option registration interval is reversed")
    return {
        "instrument_id": expected_code + ".SH",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "parser_rule": "explicit_cash_option_registration_interval/v1",
        "source_span": matches[0].group(0),
    }
