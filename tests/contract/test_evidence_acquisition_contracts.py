from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    CompletenessUnit,
    EvidenceAvailabilityPolicy,
    EvidenceCollectionSpec,
    EvidenceCollectorPolicy,
    EvidenceCompletenessWitness,
    EvidenceFile,
    EvidenceHttpRequest,
    EvidenceHttpResponseMetadata,
    EvidenceParserConfig,
    EvidencePublicationSpec,
    EvidenceUsePermission,
    ExchangeVenue,
)

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def test_p12_policies_are_bounded_and_hashable() -> None:
    collection = EvidenceCollectionSpec(
        collection_id="repurchase-2025-01-02",
        venues=(ExchangeVenue.SSE, ExchangeVenue.SZSE),
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        page_size=25,
        max_announcements=2_000,
    )
    collector = EvidenceCollectorPolicy(
        policy_id="exchange-announcements/v1",
        user_agent="quant-research-os-evidence-collector/0.1 (+offline-research)",
        requests_per_minute=30,
        allowed_hosts=(
            "big5.sse.com.cn",
            "disc.static.szse.cn",
            "query.sse.com.cn",
            "www.szse.cn",
        ),
        collector_version="quantos-evidence-collector/0.1",
    )
    availability = EvidenceAvailabilityPolicy(
        policy_id="exchange-announcement-availability/v1",
        venue_permissions={
            ExchangeVenue.SSE: EvidenceUsePermission.RESEARCH_ALLOWED,
            ExchangeVenue.SZSE: EvidenceUsePermission.UNKNOWN,
        },
        venue_license_ids={
            ExchangeVenue.SSE: "sse-legal-statement/noncommercial/2026-09-08",
            ExchangeVenue.SZSE: "szse-copyright-disclaimer/unknown/2026-09-08",
        },
        limitations=("SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED",),
    )
    publication = EvidencePublicationSpec(
        availability_policy=availability,
        parser_config=EvidenceParserConfig(config_id="deterministic-text/v1"),
        code_commit_hash="a" * 40,
        runtime_fingerprint_hash="b" * 64,
    )

    assert collection.content_hash
    assert collector.content_hash
    assert publication.content_hash

    with pytest.raises(ValidationError, match="32 calendar days"):
        EvidenceCollectionSpec(
            collection_id="unbounded",
            venues=(ExchangeVenue.SSE,),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 1),
        )
    with pytest.raises(ValidationError, match="bare host names"):
        EvidenceCollectorPolicy.model_validate(
            {
                **collector.model_dump(mode="python"),
                "allowed_hosts": ("https://www.sse.com.cn",),
            }
        )
    with pytest.raises(ValidationError, match="retry_min_seconds"):
        EvidenceCollectorPolicy.model_validate(
            {
                **collector.model_dump(mode="python"),
                "retry_min_seconds": 10,
                "retry_max_seconds": 1,
            }
        )
    with pytest.raises(ValidationError, match="cover every supported venue"):
        EvidenceAvailabilityPolicy.model_validate(
            {
                **availability.model_dump(mode="python"),
                "venue_permissions": {"SSE": "RESEARCH_ALLOWED"},
            }
        )


def test_request_response_and_completeness_contracts_fail_closed() -> None:
    request = EvidenceHttpRequest(
        sequence=1,
        venue=ExchangeVenue.SZSE,
        purpose="DISCOVERY",
        method="POST",
        url="https://www.szse.cn/api/disc/announcement/annList",
        body_hash="a" * 64,
        content_type="application/json",
    )
    response = EvidenceHttpResponseMetadata(
        request_hash=request.content_hash,
        status_code=200,
        fetched_at=NOW,
        observed_at=NOW,
        media_type="application/json",
        content_length=2,
        body_hash="b" * 64,
        attempt_count=1,
    )
    witness = EvidenceCompletenessWitness(
        venue=ExchangeVenue.SZSE,
        query_hash="c" * 64,
        unit=CompletenessUnit.ANNOUNCEMENT,
        reported_total=0,
        collected_total=0,
        page_count=1,
        page_item_counts=(0,),
        complete=True,
        reason="official count explicitly reports zero",
    )

    assert response.request_hash == request.content_hash
    assert witness.complete
    with pytest.raises(ValidationError, match="outcome does not match"):
        EvidenceCompletenessWitness.model_validate(
            {**witness.model_dump(mode="python"), "reported_total": 1}
        )
    with pytest.raises(ValidationError, match="GET requests cannot bind"):
        EvidenceHttpRequest(
            sequence=2,
            venue=ExchangeVenue.SSE,
            purpose="DISCOVERY",
            method="GET",
            url="https://query.sse.com.cn/example",
            body_hash="d" * 64,
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidenceHttpResponseMetadata.model_validate(
            {
                **response.model_dump(mode="python"),
                "fetched_at": NOW.replace(tzinfo=None),
            }
        )
    with pytest.raises(ValidationError, match="page count"):
        EvidenceCompletenessWitness.model_validate(
            {**witness.model_dump(mode="python"), "page_count": 2}
        )
    with pytest.raises(ValidationError, match="collected total"):
        EvidenceCompletenessWitness.model_validate(
            {**witness.model_dump(mode="python"), "collected_total": 1, "reported_total": 1}
        )
    with pytest.raises(ValidationError, match="safe relative POSIX path"):
        EvidenceFile(
            logical_path="../escape",
            sha256="e" * 64,
            size_bytes=1,
            media_type="application/octet-stream",
        )
