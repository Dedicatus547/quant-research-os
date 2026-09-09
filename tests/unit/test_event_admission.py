from datetime import UTC, date, datetime

import pytest

from quantos.application import EventFeatureAdmissionError, build_event_feature_artifact
from quantos.contracts import (
    AdmissionCheck,
    AdmissionReviewerKind,
    EventFeatureAdmissionRecord,
    EventFeatureRow,
    EvidenceAvailabilityKind,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    EvidenceRevisionKind,
    EvidenceSourceKind,
    EvidenceUsePermission,
    ExtractedTextArtifact,
    ReasonCode,
    TradingSessionResolution,
    sha256_bytes,
)

NOW = datetime(2026, 1, 5, 9, tzinfo=UTC)
TEXT = "0123456789"
SNAPSHOT_HASH = "1" * 64
RESOLVER_HASH = "e" * 64


def _chain(
    *, admitted: bool = True, unknown: bool = False
) -> tuple[
    EvidenceRecord,
    ExtractedTextArtifact,
    EvidenceExtractionProposal,
    EventFeatureAdmissionRecord,
]:
    evidence = EvidenceRecord(
        evidence_id="ev-001",
        source_kind=EvidenceSourceKind.STRUCTURED_FIXTURE,
        source_locator="fixture://evidence/001",
        publisher="fixture",
        retrieval_request_hash="1" * 64,
        retrieval_response_metadata_hash="2" * 64,
        raw_bytes_hash="3" * 64,
        raw_size_bytes=10,
        media_type="text/plain",
        encoding="utf-8",
        published_at=NOW,
        fetched_at=NOW,
        observed_at=NOW,
        available_at=None if unknown else NOW,
        availability_kind=(
            EvidenceAvailabilityKind.UNKNOWN if unknown else EvidenceAvailabilityKind.PROVEN
        ),
        availability_policy_hash="4" * 64,
        revision_kind=EvidenceRevisionKind.ORIGINAL,
        collector_version="fixture/1",
        license_id="fixture/1",
        use_permission=EvidenceUsePermission.RESEARCH_ALLOWED,
        entity_refs=("600000.SH",),
    )
    text = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash=sha256_bytes(TEXT.encode()),
        character_count=len(TEXT),
        parser_name="fixture",
        parser_version="1",
        parser_config_hash="6" * 64,
        code_commit_hash="7" * 40,
        runtime_fingerprint_hash="8" * 64,
    )
    citation = EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=text.content_hash,
        char_start=0,
        char_end=10,
        cited_text_hash=sha256_bytes(TEXT.encode()),
    )
    proposal = EvidenceExtractionProposal(
        proposal_id="extract-001",
        agent_run_hash="a" * 64,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=text.content_hash,
        event_label="share_repurchase",
        entity_refs=("600000.SH",),
        proposed_event_time=NOW,
        citations=(citation,),
    )
    check = AdmissionCheck(
        check_id="semantic-benchmark",
        passed=admitted,
        evidence_hashes=tuple(sorted((evidence.content_hash, proposal.content_hash))),
        reason="fixture admission outcome",
    )
    admission = EventFeatureAdmissionRecord(
        extraction_proposal_hash=proposal.content_hash,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=text.content_hash,
        admission_policy_hash="b" * 64,
        reviewer_kind=AdmissionReviewerKind.DETERMINISTIC_BENCHMARK,
        reviewer_evidence_hash="c" * 64,
        checks=(check,),
        admitted=admitted,
    )
    return evidence, text, proposal, admission


def _row(
    *, entity: str = "600000.SH", event_time: datetime = NOW, available_at: datetime = NOW
) -> EventFeatureRow:
    return EventFeatureRow(
        entity_ref=entity,
        event_label="share_repurchase",
        event_time=event_time,
        available_at=available_at,
        effective_trade_date=date(2026, 1, 5),
    )


def _resolution(evidence: EvidenceRecord, *, entity: str = "600000.SH") -> TradingSessionResolution:
    return TradingSessionResolution(
        snapshot_hash=SNAPSHOT_HASH,
        resolver_policy_hash=RESOLVER_HASH,
        calendar_file_hash="2" * 64,
        instrument_file_hash="3" * 64,
        evidence_hash=evidence.content_hash,
        evidence_available_at=NOW,
        entity_ref=entity,
        exchange="SSE" if entity.endswith(".SH") else "SZSE",
        effective_trade_date=date(2026, 1, 5),
    )


def test_only_admitted_extraction_can_build_qualified_event_feature() -> None:
    evidence, text, proposal, admission = _chain()

    artifact = build_event_feature_artifact(
        evidence,
        text,
        proposal,
        admission,
        TEXT,
        (_row(),),
        (_resolution(evidence),),
        entity_resolver_policy_hash="d" * 64,
        trading_day_resolver_policy_hash="e" * 64,
        source_snapshot_hash=SNAPSHOT_HASH,
        code_commit_hash="f" * 40,
        runtime_fingerprint_hash="0" * 64,
    )

    assert artifact.evidence_hash == evidence.content_hash
    assert artifact.admission_record_hash == admission.content_hash
    assert artifact.extraction_proposal_hash == proposal.content_hash


def test_rejected_or_unknown_evidence_never_becomes_executable_feature() -> None:
    evidence, text, proposal, admission = _chain(admitted=False)
    with pytest.raises(EventFeatureAdmissionError) as rejected:
        build_event_feature_artifact(
            evidence,
            text,
            proposal,
            admission,
            TEXT,
            (_row(),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert rejected.value.reason_code is ReasonCode.ADMISSION_REJECTED

    evidence, text, proposal, admission = _chain(unknown=True)
    with pytest.raises(EventFeatureAdmissionError) as unknown:
        build_event_feature_artifact(
            evidence,
            text,
            proposal,
            admission,
            TEXT,
            (_row(),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert unknown.value.reason_code is ReasonCode.UNKNOWN_AVAILABILITY


def test_admission_rechecks_lineage_entity_label_and_availability() -> None:
    evidence, text, proposal, admission = _chain()
    broken = admission.model_copy(update={"extraction_proposal_hash": "0" * 64})
    with pytest.raises(EventFeatureAdmissionError) as mismatch:
        build_event_feature_artifact(
            evidence,
            text,
            proposal,
            broken,
            TEXT,
            (_row(),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    with pytest.raises(EventFeatureAdmissionError) as escaped:
        build_event_feature_artifact(
            evidence,
            text,
            proposal,
            admission,
            TEXT,
            (_row(entity="000001.SZ"),),
            (_resolution(evidence, entity="000001.SZ"),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert escaped.value.reason_code is ReasonCode.LOOK_AHEAD

    with pytest.raises(EventFeatureAdmissionError) as wrong_time:
        build_event_feature_artifact(
            evidence,
            text,
            proposal,
            admission,
            TEXT,
            (_row(event_time=NOW.replace(hour=8)),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert wrong_time.value.reason_code is ReasonCode.LOOK_AHEAD


def test_admission_rejects_unlicensed_evidence_and_out_of_range_citations() -> None:
    evidence, text, proposal, admission = _chain()
    restricted = evidence.model_copy(update={"use_permission": EvidenceUsePermission.RESTRICTED})
    with pytest.raises(EventFeatureAdmissionError) as unlicensed:
        build_event_feature_artifact(
            restricted,
            text,
            proposal,
            admission,
            TEXT,
            (_row(),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert unlicensed.value.reason_code is ReasonCode.ADMISSION_REJECTED

    citation = proposal.citations[0].model_copy(update={"char_end": 11})
    escaped_proposal = proposal.model_copy(update={"citations": (citation,)})
    escaped_admission = admission.model_copy(
        update={"extraction_proposal_hash": escaped_proposal.content_hash}
    )
    with pytest.raises(EventFeatureAdmissionError) as escaped:
        build_event_feature_artifact(
            evidence,
            text,
            escaped_proposal,
            escaped_admission,
            TEXT,
            (_row(),),
            (_resolution(evidence),),
            entity_resolver_policy_hash="d" * 64,
            trading_day_resolver_policy_hash="e" * 64,
            source_snapshot_hash=SNAPSHOT_HASH,
            code_commit_hash="f" * 40,
            runtime_fingerprint_hash="0" * 64,
        )
    assert escaped.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
