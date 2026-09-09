from datetime import UTC, datetime

import pytest

from quantos.application import EvidenceBinding, EvidenceMcpError, EvidenceMcpService
from quantos.contracts import (
    EvidenceAgentView,
    EvidenceCitation,
    EvidenceCitationRequest,
    EvidenceExtractionDraft,
    EvidenceGetRequest,
    EvidenceRecord,
    EvidenceUsePermission,
    ExtractedTextArtifact,
    ReasonCode,
    canonical_json_bytes,
    sha256_bytes,
)

TEXT = "证券代码:600010\n股份回购进展公告\n\n累计回购股份。\n"


def _binding() -> EvidenceBinding:
    evidence = EvidenceRecord(
        evidence_id="sse-test",
        source_kind="EXCHANGE_ANNOUNCEMENT",
        source_locator="https://example.invalid/document",
        publisher="SSE",
        retrieval_request_hash="1" * 64,
        retrieval_response_metadata_hash="2" * 64,
        raw_bytes_hash="3" * 64,
        raw_size_bytes=1,
        media_type="application/pdf",
        published_at=datetime(2025, 8, 5, tzinfo=UTC),
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        available_at=datetime(2025, 8, 5, tzinfo=UTC),
        availability_kind="CONSERVATIVE",
        availability_policy_hash="4" * 64,
        collector_version="test",
        license_id="test",
        use_permission=EvidenceUsePermission.RESEARCH_ALLOWED,
        entity_refs=("600010.SH",),
    )
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash=sha256_bytes(TEXT.encode()),
        character_count=len(TEXT),
        page_count=2,
        parser_name="fixture",
        parser_version="1",
        parser_config_hash="5" * 64,
        code_commit_hash="6" * 40,
        runtime_fingerprint_hash="7" * 64,
    )
    return EvidenceBinding(evidence=evidence, extracted_text=extracted, text=TEXT)


def test_evidence_mcp_returns_path_free_spans_and_exact_citation() -> None:
    binding = _binding()
    service = EvidenceMcpService({binding.evidence.content_hash: binding})
    view = service.call(
        "evidence.get",
        canonical_json_bytes(EvidenceGetRequest(evidence_hash=binding.evidence.content_hash)),
    )
    assert isinstance(view, EvidenceAgentView)
    assert [(item.page, item.char_start, item.char_end) for item in view.spans] == [
        (1, 0, 11),
        (1, 12, 20),
        (2, 22, 29),
    ]
    text = "股份回购进展公告"
    citation = service.call(
        "evidence.cite",
        canonical_json_bytes(
            EvidenceCitationRequest(
                evidence_hash=binding.evidence.content_hash,
                extracted_text_hash=binding.extracted_text.content_hash,
                page=1,
                char_start=12,
                char_end=20,
                expected_text=text,
            )
        ),
    )
    assert isinstance(citation, EvidenceCitation)
    assert citation.cited_text_hash == sha256_bytes(text.encode())
    draft = EvidenceExtractionDraft(
        proposal_id="share-repurchase-test",
        evidence_hash=binding.evidence.content_hash,
        extracted_text_hash=binding.extracted_text.content_hash,
        event_label="share_repurchase",
        entity_refs=binding.evidence.entity_refs,
        proposed_event_time=binding.evidence.published_at,
        citations=(citation,),
        limitations=("AGENT_PROPOSAL",),
    )
    assert draft.authority == "AGENT_PROPOSAL"


def test_evidence_mcp_rejects_text_mismatch_and_request_overrun() -> None:
    binding = _binding()
    service = EvidenceMcpService({binding.evidence.content_hash: binding})
    request = EvidenceCitationRequest(
        evidence_hash=binding.evidence.content_hash,
        extracted_text_hash=binding.extracted_text.content_hash,
        page=1,
        char_start=12,
        char_end=20,
        expected_text="错误错误错误错误",
    )
    with pytest.raises(EvidenceMcpError) as mismatch:
        service.call("evidence.cite", canonical_json_bytes(request))
    assert mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    get_request = canonical_json_bytes(
        EvidenceGetRequest(evidence_hash=binding.evidence.content_hash)
    )
    service.call("evidence.get", get_request)
    service.call("evidence.get", get_request)
    with pytest.raises(EvidenceMcpError) as exhausted:
        service.call(
            "evidence.get",
            get_request,
        )
    assert exhausted.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED
