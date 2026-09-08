"""Official SSE/SZSE announcement discovery adapters.

These adapters parse only the bounded response fields needed to acquire raw
documents.  They do not normalize event meaning or call an LLM.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence_acquisition import (
    AnnouncementCandidate,
    CompletenessUnit,
    EvidenceCollectionSpec,
    EvidenceHttpRequest,
    ExchangeVenue,
    PublicationTimePrecision,
)

SSE_DISCOVERY_URL = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
SSE_DOCUMENT_ORIGIN = "https://static.sse.com.cn"
SZSE_DISCOVERY_URL = "https://www.szse.cn/api/disc/announcement/annList"
SZSE_DOCUMENT_ORIGIN = "https://disc.static.szse.cn"


class SourceResponseError(ValueError):
    """An official-source response did not satisfy the frozen parser schema."""


@dataclass(frozen=True)
class PreparedDiscoveryRequest:
    contract: EvidenceHttpRequest
    body: bytes | None
    headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DiscoveryPage:
    candidates: tuple[AnnouncementCandidate, ...]
    reported_total: int
    collected_units: int
    total_pages: int
    unit: CompletenessUnit


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceResponseError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SourceResponseError(f"{label} must be an array")
    return cast(list[Any], value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise SourceResponseError(f"{label} must be an integer")
    try:
        result = int(cast(Any, value))
    except (TypeError, ValueError) as error:
        raise SourceResponseError(f"{label} must be an integer") from error
    if result < 0:
        raise SourceResponseError(f"{label} cannot be negative")
    return result


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceResponseError(f"{label} must be a nonempty string")
    return value.strip()


def _instrument(value: str, suffix: str) -> tuple[str, ...]:
    return (f"{value}.{suffix}",) if len(value) == 6 and value.isdigit() else ()


class SseAnnouncementSource:
    venue = ExchangeVenue.SSE

    def build_request(
        self, spec: EvidenceCollectionSpec, *, page: int, sequence: int
    ) -> PreparedDiscoveryRequest:
        params = {
            "BULLETIN_TYPE": "",
            "COMPANY_CODE": "",
            "END_DATE": spec.end_date.isoformat(),
            "SECURITY_CODE": spec.security_code or "",
            "START_DATE": spec.start_date.isoformat(),
            "TITLE": spec.title_keyword or "",
            "isPagination": "true",
            "pageHelp.cacheSize": "1",
            "pageHelp.pageNo": str(page),
            "pageHelp.pageSize": str(spec.page_size),
        }
        url = f"{SSE_DISCOVERY_URL}?{urlencode(sorted(params.items()))}"
        contract = EvidenceHttpRequest(
            sequence=sequence,
            venue=self.venue,
            purpose="DISCOVERY",
            method="GET",
            url=url,
        )
        return PreparedDiscoveryRequest(
            contract=contract,
            body=None,
            headers=(
                ("Accept", "application/json"),
                ("Referer", "https://www.sse.com.cn/disclosure/listedinfo/announcement/"),
            ),
        )

    def parse_page(self, body: bytes, spec: EvidenceCollectionSpec, *, page: int) -> DiscoveryPage:
        try:
            root = _mapping(json.loads(body), "SSE response")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceResponseError("SSE response is not valid JSON") from error
        page_help = _mapping(root.get("pageHelp"), "SSE pageHelp")
        result = _sequence(root.get("result"), "SSE result")
        reported_total = _integer(page_help.get("total"), "SSE total")
        total_pages = _integer(page_help.get("pageCount"), "SSE pageCount")
        actual_page = _integer(page_help.get("pageNo"), "SSE pageNo")
        if actual_page != page:
            raise SourceResponseError("SSE response page number does not match request")
        expected_pages = math.ceil(reported_total / spec.page_size) if reported_total else 0
        if total_pages != expected_pages:
            raise SourceResponseError("SSE pageCount does not match total and page size")

        candidates: list[AnnouncementCandidate] = []
        for group_value in result:
            group = _sequence(group_value, "SSE announcement group")
            primary = [
                _mapping(item, "SSE announcement")
                for item in group
                if _mapping(item, "SSE announcement").get("ORG_FILE_TYPE") in (0, "0", None)
            ]
            if len(primary) != 1:
                raise SourceResponseError("SSE announcement group must have one primary document")
            item = primary[0]
            source_id = _required_string(item.get("ORG_BULLETIN_ID"), "SSE source id")
            relative_url = _required_string(item.get("URL"), "SSE document URL")
            if not relative_url.startswith("/"):
                raise SourceResponseError("SSE document URL must be root-relative")
            security_code = _required_string(item.get("SECURITY_CODE"), "SSE security code")
            published = _required_string(item.get("SSEDATE"), "SSE publication date")
            candidates.append(
                AnnouncementCandidate(
                    venue=self.venue,
                    source_id=source_id,
                    publisher="Shanghai Stock Exchange / listed issuer",
                    title=_required_string(item.get("TITLE"), "SSE title"),
                    source_locator=f"{SSE_DISCOVERY_URL}#{source_id}",
                    document_url=f"{SSE_DOCUMENT_ORIGIN}{relative_url}",
                    publication_value=published,
                    publication_precision=PublicationTimePrecision.DATE,
                    entity_refs=_instrument(security_code, "SH"),
                )
            )
        return DiscoveryPage(
            candidates=tuple(candidates),
            reported_total=reported_total,
            collected_units=len(result),
            total_pages=total_pages,
            unit=CompletenessUnit.ANNOUNCEMENT_GROUP,
        )


class SzseAnnouncementSource:
    venue = ExchangeVenue.SZSE

    def build_request(
        self, spec: EvidenceCollectionSpec, *, page: int, sequence: int
    ) -> PreparedDiscoveryRequest:
        payload: dict[str, object] = {
            "channelCode": ["listedNotice_disc"],
            "pageNum": page,
            "pageSize": spec.page_size,
            "seDate": [spec.start_date.isoformat(), spec.end_date.isoformat()],
        }
        if spec.security_code is not None:
            payload["stock"] = [spec.security_code]
        if spec.title_keyword is not None:
            payload["keyword"] = spec.title_keyword
        body = canonical_json_bytes(payload)
        contract = EvidenceHttpRequest(
            sequence=sequence,
            venue=self.venue,
            purpose="DISCOVERY",
            method="POST",
            url=SZSE_DISCOVERY_URL,
            body_hash=sha256_bytes(body),
            content_type="application/json",
        )
        return PreparedDiscoveryRequest(
            contract=contract,
            body=body,
            headers=(
                ("Accept", "application/json"),
                ("Content-Type", "application/json"),
                ("Referer", "https://www.szse.cn/disclosure/listed/notice/index.html"),
                ("X-Requested-With", "XMLHttpRequest"),
            ),
        )

    def parse_page(self, body: bytes, spec: EvidenceCollectionSpec, *, page: int) -> DiscoveryPage:
        try:
            root = _mapping(json.loads(body), "SZSE response")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceResponseError("SZSE response is not valid JSON") from error
        data = _sequence(root.get("data"), "SZSE data")
        reported_total = _integer(root.get("announceCount"), "SZSE announceCount")
        total_pages = math.ceil(reported_total / spec.page_size) if reported_total else 0
        candidates: list[AnnouncementCandidate] = []
        for value in data:
            item = _mapping(value, "SZSE announcement")
            source_id = _required_string(item.get("id"), "SZSE source id")
            relative_url = _required_string(item.get("attachPath"), "SZSE document URL")
            if not relative_url.startswith("/"):
                raise SourceResponseError("SZSE document URL must be root-relative")
            codes_value = item.get("secCode", [])
            codes = _sequence(codes_value, "SZSE security codes")
            entity_refs = tuple(
                sorted(
                    {
                        f"{code}.SZ"
                        for code in codes
                        if isinstance(code, str) and len(code) == 6 and code.isdigit()
                    }
                )
            )
            candidates.append(
                AnnouncementCandidate(
                    venue=self.venue,
                    source_id=source_id,
                    publisher="Shenzhen Stock Exchange / listed issuer",
                    title=_required_string(item.get("title"), "SZSE title"),
                    source_locator=f"{SZSE_DISCOVERY_URL}#{source_id}",
                    document_url=f"{SZSE_DOCUMENT_ORIGIN}{relative_url}",
                    publication_value=_required_string(
                        item.get("publishTime"), "SZSE publication time"
                    ),
                    publication_precision=PublicationTimePrecision.SECOND,
                    entity_refs=entity_refs,
                )
            )
        return DiscoveryPage(
            candidates=tuple(candidates),
            reported_total=reported_total,
            collected_units=len(data),
            total_pages=total_pages,
            unit=CompletenessUnit.ANNOUNCEMENT,
        )


SourceAdapter = SseAnnouncementSource | SzseAnnouncementSource


def source_for(venue: ExchangeVenue) -> SourceAdapter:
    if venue is ExchangeVenue.SSE:
        return SseAnnouncementSource()
    if venue is ExchangeVenue.SZSE:
        return SzseAnnouncementSource()
    raise AssertionError(f"unsupported venue: {venue}")
