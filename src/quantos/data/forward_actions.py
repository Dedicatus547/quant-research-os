"""Offline comparison of retained dividend variants, without granting admission.

Raw-ledger failures stay failed. Agreement on event fields does not establish
publication vintage, completeness, cash entitlement, or absence of other actions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from quantos.contracts.base import canonical_json_bytes, sha256_bytes

KEY_FIELDS = ("ts_code", "end_date", "ann_date", "div_proc")
EVENT_FIELDS = (
    "record_date",
    "ex_date",
    "pay_date",
    "div_listdate",
    "stk_div",
    "stk_bo_rate",
    "stk_co_rate",
    "cash_div",
    "cash_div_tax",
)


def compare_dividend_variants(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not set(KEY_FIELDS + EVENT_FIELDS).issubset(row):
            raise ValueError("required dividend fields missing")
        groups[tuple(row[key] for key in KEY_FIELDS)].append(dict(row))
    result: list[dict[str, Any]] = []
    for key, variants in groups.items():
        if len(variants) < 2:
            continue
        hashes = [sha256_bytes(canonical_json_bytes(row)) for row in variants]
        distinct = len(set(hashes))
        fields = sorted({field for row in variants for field in row})
        differences = [
            field
            for field in fields
            if len({canonical_json_bytes(row.get(field)) for row in variants}) > 1
        ]
        event_agrees = not set(differences).intersection(EVENT_FIELDS)
        if distinct == 1:
            classification = "EXACT_DUPLICATE"
        elif key[3] != "实施":
            classification = "NON_IMPLEMENTED_VARIANTS_NOT_ORDERED"
        elif event_agrees:
            classification = "IMPLEMENTED_EVENT_FIELDS_AGREE_METADATA_DIFFERS"
        else:
            classification = "IMPLEMENTED_EVENT_FIELDS_CONFLICT"
        result.append(
            {
                "key": dict(zip(KEY_FIELDS, key, strict=True)),
                "source_row_indices": [
                    i for i, row in enumerate(rows) if tuple(row[k] for k in KEY_FIELDS) == key
                ],
                "row_hashes": hashes,
                "different_fields": differences,
                "classification": classification,
                "event_fields_agree": event_agrees,
                "versions_ordered": False,
            }
        )
    return {
        "schema_version": "dividend-variant-comparison/v1",
        "groups": result,
        "input_rows": len(rows),
        "coverage_granted": False,
        "historical_vintage_established": False,
        "raw_failure_reclassified": False,
    }


def derive_szse_cash_notice(raw: bytes, instrument_id: str) -> dict[str, Any]:
    """Parse explicit ordinary cash notice terms; never infer complete coverage.

    Cash per participating share differs from an ex-price reference adjusted for
    excluded treasury shares. Only the explicit gross distribution clause is used.
    Payment is a scheduled depository payment, not proof of receipt by every holder.
    """
    from quantos.research.merger_entitlement_sources import (
        _Document,  # pyright: ignore[reportPrivateUsage]
        _issuer,  # pyright: ignore[reportPrivateUsage]
    )

    if re.fullmatch(r"[0-9]{6}\.SZ", instrument_id) is None:
        raise ValueError("SZSE issuer required")
    document = _Document.read(raw)
    identity = _issuer(document, instrument_id)
    title = document.matches(r"(?:权益分派|分红派息)实施公告")[0]
    no_stock = document.matches(r"不送红股,不以公积金转增股本|不进行送股或以公积金转增股本")[0]
    positive_stock = re.finditer(
        r"(?:每(?:10)?股)?(?:送红股|转增(?:股本|股份)?)([0-9]+(?:\.[0-9]+)?)股",
        document.text,
    )
    if any(Decimal(match[1]) > 0 for match in positive_stock):
        raise ValueError("notice contains conflicting stock distribution terms")
    gross = document.matches(r"每10股派([0-9]+(?:\.[0-9]+)?)元人民币现金\(含税")
    amounts = {Decimal(match[1]) / 10 for match in gross}
    if len(amounts) != 1 or next(iter(amounts)) <= 0:
        raise ValueError("gross distribution amount is ambiguous or invalid")
    date_pattern = r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日"

    def one_date(prefix: str, suffix: str = "") -> tuple[date, dict[str, Any]]:
        matches = document.matches(prefix + date_pattern + suffix)
        dates = {date(*(int(match[i]) for i in (1, 2, 3))) for match in matches}
        if len(dates) != 1:
            raise ValueError("notice date is ambiguous")
        return next(iter(dates)), document.span(matches[0])

    record, record_span = one_date(r"股权登记日为:")
    ex, ex_span = one_date(r"除权除息日为:")
    pay, pay_span = one_date(
        r"现金红利将于", r"通过股东托管证券公司\(或其他托管机构\)直接划入其资金账户"
    )
    if not record < ex or pay < record:
        raise ValueError("notice date order is invalid")
    return {
        "schema_version": "forward-szse-cash-notice/v1",
        "instrument_id": instrument_id,
        "source_sha256": document.raw_hash,
        "record_date": record.isoformat(),
        "ex_date": ex.isoformat(),
        "scheduled_depository_pay_date": pay.isoformat(),
        "cash_div_tax": format(next(iter(amounts)).normalize(), "f"),
        "stock_distribution": "EXPLICIT_NONE_IN_THIS_NOTICE",
        "spans": {
            "issuer": document.span(identity),
            "title": document.span(title),
            "no_stock": document.span(no_stock),
            "gross_cash": document.span(gross[0]),
            "record": record_span,
            "ex": ex_span,
            "scheduled_payment": pay_span,
        },
        "coverage_granted": False,
        "payment_observed": False,
        "historical_vintage_established": False,
    }


def derive_sse_cash_notice(raw: bytes, instrument_id: str) -> dict[str, Any]:
    """Explicit SSE A-share cash/date table, retaining the original parser boundary."""
    from quantos.research.merger_entitlement_sources import (
        _Document,  # pyright: ignore[reportPrivateUsage]
        _issuer,  # pyright: ignore[reportPrivateUsage]
    )

    if re.fullmatch(r"[0-9]{6}\.SH", instrument_id) is None:
        raise ValueError("SSE issuer required")
    document = _Document.read(raw)
    identity = _issuer(document, instrument_id)
    title = document.matches(r"(?:权益分派|分红派息)实施公告")[0]
    header = document.matches(r"股份类别股权登记日最后交易日除权\(息\)日现金红利发放日")[0]
    date_pattern = r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}"
    matches = document.matches(
        r"A股(" + date_pattern + r")[-—](" + date_pattern + r")(" + date_pattern + r")(?![0-9])"
    )
    values = {
        tuple(date(*(int(p) for p in m[i].split("/"))).isoformat() for i in (1, 2, 3))
        for m in matches
    }
    cash = document.matches(r"每股派发现金红利(?:人民币)?([0-9]+(?:\.[0-9]+)?)元\(含税\)")
    amounts = {Decimal(m[1]) for m in cash}
    if len(values) != 1 or len(amounts) != 1 or next(iter(amounts)) <= 0:
        raise ValueError("SSE cash terms are ambiguous or invalid")
    record, ex, pay = next(iter(values))
    if not record < ex or pay < record:
        raise ValueError("SSE notice date order is invalid")
    return {
        "schema_version": "forward-sse-cash-notice/v1",
        "instrument_id": instrument_id,
        "source_sha256": document.raw_hash,
        "record_date": record,
        "ex_date": ex,
        "scheduled_depository_pay_date": pay,
        "cash_div_tax": format(next(iter(amounts)).normalize(), "f"),
        "spans": {
            "issuer": document.span(identity),
            "title": document.span(title),
            "header": document.span(header),
            "dates": document.span(matches[0]),
            "cash": document.span(cash[0]),
        },
        "coverage_granted": False,
        "payment_observed": False,
        "historical_vintage_established": False,
    }
