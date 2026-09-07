"""Fail-closed interface between extraction proposals and qualified event features."""

from __future__ import annotations

from typing import Protocol

from quantos.contracts.evidence import (
    EventFeatureAdmissionRecord,
    EventFeatureArtifact,
    EventFeatureRow,
    EvidenceAvailabilityKind,
    EvidenceExtractionProposal,
    EvidenceRecord,
    EvidenceUsePermission,
    ExtractedTextArtifact,
)
from quantos.contracts.status import ReasonCode


class EventFeatureAdmissionPolicy(Protocol):
    """Implemented only by a frozen deterministic benchmark or human-review adapter."""

    @property
    def policy_hash(self) -> str: ...

    def evaluate(
        self,
        evidence: EvidenceRecord,
        extracted_text: ExtractedTextArtifact,
        proposal: EvidenceExtractionProposal,
    ) -> EventFeatureAdmissionRecord: ...


class EventFeatureAdmissionError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def build_event_feature_artifact(
    evidence: EvidenceRecord,
    extracted_text: ExtractedTextArtifact,
    proposal: EvidenceExtractionProposal,
    admission: EventFeatureAdmissionRecord,
    rows: tuple[EventFeatureRow, ...],
    *,
    entity_resolver_policy_hash: str,
    trading_day_resolver_policy_hash: str,
    code_commit_hash: str,
    runtime_fingerprint_hash: str,
    limitations: tuple[str, ...] = (),
) -> EventFeatureArtifact:
    """Construct a qualified feature only after every immutable binding is rechecked."""

    if evidence.availability_kind is EvidenceAvailabilityKind.UNKNOWN:
        raise EventFeatureAdmissionError(
            ReasonCode.UNKNOWN_AVAILABILITY,
            "evidence with unknown availability cannot become an executable feature",
        )
    if evidence.use_permission is not EvidenceUsePermission.RESEARCH_ALLOWED:
        raise EventFeatureAdmissionError(
            ReasonCode.ADMISSION_REJECTED,
            "evidence license does not permit research use",
        )
    if (
        extracted_text.evidence_hash != evidence.content_hash
        or extracted_text.raw_bytes_hash != evidence.raw_bytes_hash
        or proposal.evidence_hash != evidence.content_hash
        or proposal.extracted_text_hash != extracted_text.content_hash
        or admission.evidence_hash != evidence.content_hash
        or admission.extracted_text_hash != extracted_text.content_hash
        or admission.extraction_proposal_hash != proposal.content_hash
    ):
        raise EventFeatureAdmissionError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "evidence, extraction, proposal, and admission bindings disagree",
        )
    if any(
        (
            item.page is not None
            and extracted_text.page_count is not None
            and item.page > extracted_text.page_count
        )
        or (item.char_end is not None and item.char_end > extracted_text.character_count)
        for item in proposal.citations
    ):
        raise EventFeatureAdmissionError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "proposal citation escapes the frozen extracted text",
        )
    if not admission.admitted:
        raise EventFeatureAdmissionError(
            ReasonCode.ADMISSION_REJECTED,
            "extraction proposal did not pass the frozen admission policy",
        )
    if not rows:
        raise EventFeatureAdmissionError(
            ReasonCode.SOURCE_INCOMPLETE, "admitted feature rows are missing"
        )
    if proposal.proposed_event_time is None:
        raise EventFeatureAdmissionError(
            ReasonCode.SOURCE_INCOMPLETE,
            "executable event feature requires a deterministically reviewable event time",
        )
    proposed_entities = set(proposal.entity_refs)
    if (
        any(
            row.entity_ref not in proposed_entities
            or row.event_label != proposal.event_label
            or row.event_time != proposal.proposed_event_time
            or row.attributes != proposal.attributes
            or evidence.available_at is None
            or row.available_at < evidence.available_at
            for row in rows
        )
        or {row.entity_ref for row in rows} != proposed_entities
    ):
        raise EventFeatureAdmissionError(
            ReasonCode.LOOK_AHEAD,
            "event feature rows escape admitted entity, label, or availability evidence",
        )
    return EventFeatureArtifact(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted_text.content_hash,
        extraction_proposal_hash=proposal.content_hash,
        admission_record_hash=admission.content_hash,
        admission_policy_hash=admission.admission_policy_hash,
        entity_resolver_policy_hash=entity_resolver_policy_hash,
        trading_day_resolver_policy_hash=trading_day_resolver_policy_hash,
        availability_policy_hash=evidence.availability_policy_hash,
        code_commit_hash=code_commit_hash,
        runtime_fingerprint_hash=runtime_fingerprint_hash,
        rows=rows,
        limitations=limitations,
    )
