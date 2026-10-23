"""Bounded offline rules for two issuers' retained merger/dividend PDFs.

These rules derive notice terms from original bytes. They do not prove account
holdings, receipt of a dividend, historical vendor vintages or complete coverage.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from quantos.contracts.base import sha256_bytes

# Reuse the existing immutable-byte cache without changing the frozen lifecycle API.
from quantos.data.lifecycle_sources import _pdf_pages  # pyright: ignore[reportPrivateUsage]

_COMPANIES = {
    "600837.SH": ("601211.SH", "国泰君安", "海通证券"),
    "601989.SH": ("600150.SH", "中国船舶", "中国重工"),
}
_DIVIDEND_COMPANIES = {
    "600837.SH": "海通证券股份有限公司",
    "601989.SH": "中国船舶重工股份有限公司",
}
_DATE = r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}"


def _normalize(text: str) -> str:
    # Remove only a standalone leading PDF page number, to reconnect page breaks.
    text = re.sub(r"\A\s*[0-9]+[ \t]*\r?\n", "", text, count=1)
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _doubled(text: str) -> str:
    return "".join(character * 2 for character in text)


@dataclass(frozen=True)
class _Document:
    raw_hash: str
    pages: tuple[str, ...]
    text: str

    @classmethod
    def read(cls, raw: bytes) -> _Document:
        if not raw.startswith(b"%PDF-"):
            raise ValueError("source must be actual PDF bytes")
        # The shared cache is keyed by actual immutable bytes, never pages.json.
        pages = tuple(_normalize(page) for page in _pdf_pages(raw))
        if not pages or not any(pages):
            raise ValueError("source PDF contains no extractable text")
        return cls(sha256_bytes(raw), pages, "".join(pages))

    def matches(self, pattern: str) -> list[re.Match[str]]:
        matches = list(re.finditer(pattern, self.text))
        if not matches:
            raise ValueError("required explicit source clause is missing")
        return matches

    def span(self, match: re.Match[str]) -> dict[str, Any]:
        position = 0
        physical_pages: list[int] = []
        for index, page in enumerate(self.pages, start=1):
            end = position + len(page)
            if match.start() < end and match.end() > position:
                physical_pages.append(index)
            position = end
        return {
            "physical_page": physical_pages[0],
            "physical_pages": physical_pages,
            "normalized_text": match.group(0),
            "normalized_text_sha256": sha256_bytes(match.group(0).encode("utf-8")),
        }

    def exact(self, text: str, *, doubled_header: bool = False) -> re.Match[str]:
        variants = [re.escape(text)]
        if doubled_header:
            variants.append(re.escape(_doubled(text)))
        return self.matches("(?:" + "|".join(variants) + ")")[0]


def _issuer(document: _Document, instrument_id: str) -> re.Match[str]:
    expected_code = instrument_id[:6]
    headers = document.matches(
        r"证券代码:([0-9]{6})(?![0-9])|证证券券代代码码::([0-9]{12})(?![0-9])"
    )
    for header in headers:
        if header.group(1) is not None:
            code = header.group(1)
        else:
            doubled_code = header.group(2)
            if any(doubled_code[i] != doubled_code[i + 1] for i in range(0, 12, 2)):
                raise ValueError("PDF issuer header contains an invalid doubled security code")
            code = doubled_code[::2]
        if code != expected_code:
            raise ValueError("PDF issuer headers disagree with the expected security")
    return headers[0]


def _decimal(value: str) -> str:
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("source monetary value or ratio is invalid")
    return format(number.normalize(), "f")


def derive_merger_rule(raw: bytes, instrument_id: str) -> dict[str, Any]:
    """Derive exchange registration, integer allocation and retained dividend terms."""
    if instrument_id not in _COMPANIES:
        raise ValueError("unsupported merger instrument")
    issuer_id, issuer_name, old_name = _COMPANIES[instrument_id]
    document = _Document.read(raw)
    identity = _issuer(document, issuer_id)
    document.exact("换股实施公告", doubled_header=True)
    document.exact(
        issuer_name + "证券股份有限公司"
        if issuer_id == "601211.SH"
        else "中国船舶工业股份有限公司",
        doubled_header=True,
    )
    old_share = old_name + ("A股" if instrument_id == "600837.SH" else "")
    new_share = issuer_name + ("A股" if instrument_id == "600837.SH" else "")
    issuer_share_pattern = r"(?:本公司|国泰君安)A股" if instrument_id == "600837.SH" else "中国船舶"
    registration = document.matches(
        r"换股实施股权登记日为(?P<year>[0-9]{4})年(?P<month>[0-9]{1,2})月"
        r"(?P<day>[0-9]{1,2})日,换股实施股权登记日收市后登记在册的"
        + re.escape(old_name)
        + (r"(?:全体)?A股股东" if instrument_id == "600837.SH" else r"(?:全体)?股东")
        + "持有的"
        + re.escape(old_share)
        + r"股票将按照1:(?P<ratio>[0-9]+\.[0-9]+)"
        + "的比例转换为"
        + issuer_share_pattern
        + "股票"
    )
    values = {
        (
            date(int(m["year"]), int(m["month"]), int(m["day"])).isoformat(),
            _decimal(m["ratio"]),
        )
        for m in registration
    }
    if len(values) != 1:
        raise ValueError("merger registration date or ratio is ambiguous")
    record_date, ratio = next(iter(values))
    if Decimal(ratio) <= 0:
        raise ValueError("merger exchange ratio must be positive")
    shareholder = "A股股东" if instrument_id == "600837.SH" else "股东"
    fractional = document.matches(
        re.escape(old_name)
        + ("A股" if instrument_id == "600837.SH" else "")
        + "换股股东取得的"
        + re.escape(new_share)
        + "股票应当为整数,如其所持有的"
        + re.escape(old_share)
        + "股票数量乘以换股比例后的数额不是整数,则按照其小数点后尾数大小排序,向每一位"
        + shareholder
        + "依次发放一股,直至实际换股数与计划发行股数一致。"
        + "如遇尾数相同者多于剩余股数时则采取计算机系统随机发放的方式,"
        + "直至实际换股数与计划发行股数一致。"
    )
    unclaimed = document.matches(
        "对于在"
        + re.escape(old_share)
        + "股票终止上市前已经派发,但因被冻结或因未办理指定交易等原因所导致的"
        + re.escape(old_share)
        + "股东未领取的现金红利,"
        + ("公司" if instrument_id == "600837.SH" else issuer_name)
        + r"将申请按照证券代码\("
        + instrument_id[:6]
        + r"\)、红利权数量和红利派发价格均不变的处理原则,继续委托"
        + r"(?:中国证券登记结算有限责任公司上海分公司\(以下简称[“\"]中国结算上海分公司[”\"]\)"
        + r"|中国结算上海分公司)代理发放。"
    )
    return {
        "schema_version": "merger-entitlement-source-rule/v1",
        "parser_rule": "explicit-two-merger-registration-and-retained-rights/v1",
        "instrument_id": instrument_id,
        "issuer_instrument_id": issuer_id,
        "source_sha256": document.raw_hash,
        "record_date": record_date,
        "ratio": ratio,
        "registration_basis": "CLOSE_REGISTERED_OLD_SHARES",
        "fractional_rule": "INTEGER_SHARES_REMAINDER_RANK_RANDOM_TIES",
        "unclaimed_dividends_preserved": True,
        "source_spans": {
            "issuer": document.span(identity),
            "registration": document.span(registration[0]),
            "fractional": document.span(fractional[0]),
            "unclaimed_dividend": document.span(unclaimed[0]),
        },
        "normalization": "NFKC_REMOVE_WHITESPACE_AND_LEADING_STANDALONE_PAGE_NUMBER/v1",
        "limited_scope": "NOTICE_TERMS_ONLY_NO_ACCOUNT_ELIGIBILITY_OR_SETTLEMENT_PROOF",
    }


def derive_dividend_rule(raw: bytes, instrument_id: str) -> dict[str, Any]:
    """Derive one declared A-share distribution; payment dates are notice terms."""
    if instrument_id not in _DIVIDEND_COMPANIES:
        raise ValueError("unsupported dividend instrument")
    document = _Document.read(raw)
    identity = _issuer(document, instrument_id)
    document.exact(_DIVIDEND_COMPANIES[instrument_id], doubled_header=True)
    document.exact("权益分派实施公告", doubled_header=True)
    # This row shape requires the explicit unused last-trading-date column.
    dates = document.matches(
        r"A股(?P<record>" + _DATE + r")[-—](?P<ex>" + _DATE + r")(?P<pay>" + _DATE + r")(?![0-9])"
    )
    date_values = {
        tuple(
            date(*(int(part) for part in m[field].split("/"))).isoformat()
            for field in ("record", "ex", "pay")
        )
        for m in dates
    }
    if len(date_values) != 1:
        raise ValueError("dividend record, ex or payment date is ambiguous")
    record_date, ex_date, pay_date = next(iter(date_values))
    if not record_date < ex_date or pay_date < record_date:
        raise ValueError("dividend source dates are inconsistent")
    amounts = document.matches(
        r"(?:A股每股现金红利|每股派发现金红利)(?:人民币)?"
        r"(?P<amount>[0-9]+(?:\.[0-9]+)?)元\(含税\)"
    )
    amount_values = {_decimal(m["amount"]) for m in amounts}
    if len(amount_values) != 1:
        raise ValueError("dividend tax-inclusive per-share amount is ambiguous")
    registration = document.matches(
        r"截至股权登记日下午上海证券交易所收市后,在中国证券登记结算有限责任公司"
        r"上海分公司\(以下简称[“\"]?中国结算上海分公司[”\"]?\)登记在册的"
        r"本公司全体(?:A股)?股东"
    )
    return {
        "schema_version": "dividend-entitlement-source-rule/v1",
        "parser_rule": "explicit-two-issuer-A-share-distribution/v1",
        "instrument_id": instrument_id,
        "source_sha256": document.raw_hash,
        "record_date": record_date,
        "ex_date": ex_date,
        "pay_date": pay_date,
        "cash_div_tax": next(iter(amount_values)),
        "registration_basis": "CLOSE_REGISTERED_OLD_SHARES",
        "coverage": "NOT_ESTABLISHED",
        "paid_evidence": False,
        "source_spans": {
            "issuer": document.span(identity),
            "dates": document.span(dates[0]),
            "amount": document.span(amounts[0]),
            "registration": document.span(registration[0]),
        },
        "normalization": "NFKC_REMOVE_WHITESPACE_AND_LEADING_STANDALONE_PAGE_NUMBER/v1",
        "limited_scope": "SINGLE_NOTICE_TERMS_NO_ACCOUNT_RECEIPT_OR_COMPLETE_COVERAGE_PROOF",
    }
