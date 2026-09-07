"""Harness-independent evidence, extraction, and admission contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN

LOGICAL_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
INSTRUMENT_PATTERN = r"^[0-9]{6}\.(SH|SZ)$"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return value


def _sorted_unique(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be sorted and unique")
    return values


class EvidenceSourceKind(StrEnum):
    EXCHANGE_ANNOUNCEMENT = "EXCHANGE_ANNOUNCEMENT"
    STRUCTURED_FIXTURE = "STRUCTURED_FIXTURE"


class EvidenceAvailabilityKind(StrEnum):
    PROVEN = "PROVEN"
    CONSERVATIVE = "CONSERVATIVE"
    UNKNOWN = "UNKNOWN"


class EvidenceRevisionKind(StrEnum):
    ORIGINAL = "ORIGINAL"
    REVISION = "REVISION"
    SUPERSESSION = "SUPERSESSION"
    RETRACTION = "RETRACTION"


class EvidenceUsePermission(StrEnum):
    RESEARCH_ALLOWED = "RESEARCH_ALLOWED"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class EvidenceRecord(CanonicalContract):
    """Immutable source metadata; raw bytes live in a content-addressed store."""

    schema_version: Literal["evidence-record/v1"] = "evidence-record/v1"
    evidence_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    source_kind: EvidenceSourceKind
    source_locator: str = Field(min_length=1, max_length=2048)
    publisher: str = Field(min_length=1, max_length=200)
    retrieval_request_hash: str = Field(pattern=SHA256_PATTERN)
    retrieval_response_metadata_hash: str = Field(pattern=SHA256_PATTERN)
    raw_bytes_hash: str = Field(pattern=SHA256_PATTERN)
    raw_size_bytes: NonNegativeInt
    media_type: str = Field(min_length=1, max_length=200)
    encoding: str | None = Field(default=None, min_length=1, max_length=80)
    published_at: datetime | None = None
    fetched_at: datetime
    observed_at: datetime
    available_at: datetime | None = None
    availability_kind: EvidenceAvailabilityKind
    availability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    revision_kind: EvidenceRevisionKind = EvidenceRevisionKind.ORIGINAL
    predecessor_evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    collector_version: str = Field(min_length=1, max_length=200)
    license_id: str = Field(min_length=1, max_length=200)
    use_permission: EvidenceUsePermission
    entity_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    _timestamps_are_aware = field_validator(
        "published_at", "fetched_at", "observed_at", "available_at"
    )(_aware)

    @field_validator("entity_refs")
    @classmethod
    def entities_are_supported_and_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _sorted_unique(value, label="entity_refs")
        if any(re.fullmatch(INSTRUMENT_PATTERN, item) is None for item in value):
            raise ValueError("entity_refs contain an unsupported instrument identifier")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value, label="limitations")

    @model_validator(mode="after")
    def temporal_and_revision_semantics_are_valid(self) -> Self:
        if self.published_at is not None and self.published_at > self.fetched_at:
            raise ValueError("published_at cannot follow fetched_at")
        if self.fetched_at > self.observed_at:
            raise ValueError("fetched_at cannot follow observed_at")
        if self.availability_kind is EvidenceAvailabilityKind.UNKNOWN:
            if self.available_at is not None:
                raise ValueError("unknown availability cannot claim available_at")
        elif self.available_at is None:
            raise ValueError("qualified availability requires available_at")
        if (
            self.published_at is not None
            and self.available_at is not None
            and self.available_at < self.published_at
        ):
            raise ValueError("available_at cannot precede published_at")
        has_predecessor = self.predecessor_evidence_hash is not None
        if (self.revision_kind is EvidenceRevisionKind.ORIGINAL) == has_predecessor:
            raise ValueError("revision lineage does not match revision_kind")
        return self


class ExtractedTextArtifact(CanonicalContract):
    schema_version: Literal["extracted-text-artifact/v1"] = "extracted-text-artifact/v1"
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    raw_bytes_hash: str = Field(pattern=SHA256_PATTERN)
    text_hash: str = Field(pattern=SHA256_PATTERN)
    character_count: NonNegativeInt
    page_count: PositiveInt | None = None
    parser_name: str = Field(min_length=1, max_length=100)
    parser_version: str = Field(min_length=1, max_length=100)
    parser_config_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    limitations: tuple[str, ...] = ()

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value, label="limitations")


class EvidenceCitation(CanonicalContract):
    schema_version: Literal["evidence-citation/v1"] = "evidence-citation/v1"
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    page: PositiveInt | None = None
    char_start: NonNegativeInt | None = None
    char_end: PositiveInt | None = None
    cited_text_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def location_is_present_and_ordered(self) -> Self:
        char_range = self.char_start is not None or self.char_end is not None
        if self.page is None and not char_range:
            raise ValueError("citation requires a page or character range")
        if char_range and (self.char_start is None or self.char_end is None):
            raise ValueError("citation character range must be complete")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_start >= self.char_end
        ):
            raise ValueError("citation character range is empty or reversed")
        return self


class ProposedAttribute(CanonicalContract):
    schema_version: Literal["proposed-attribute/v1"] = "proposed-attribute/v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: str | int | float | bool


class EvidenceExtractionProposal(CanonicalContract):
    schema_version: Literal["evidence-extraction-proposal/v1"] = "evidence-extraction-proposal/v1"
    proposal_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    event_label: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    entity_refs: tuple[str, ...]
    proposed_event_time: datetime | None = None
    citations: tuple[EvidenceCitation, ...]
    attributes: tuple[ProposedAttribute, ...] = ()
    limitations: tuple[str, ...] = ()

    _event_time_is_aware = field_validator("proposed_event_time")(_aware)

    @field_validator("entity_refs")
    @classmethod
    def entities_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("extraction proposal requires an entity")
        _sorted_unique(value, label="entity_refs")
        if any(re.fullmatch(INSTRUMENT_PATTERN, item) is None for item in value):
            raise ValueError("entity_refs contain an unsupported instrument identifier")
        return value

    @field_validator("citations")
    @classmethod
    def citations_are_nonempty(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        if not value:
            raise ValueError("extraction proposal requires source citations")
        return value

    @field_validator("attributes")
    @classmethod
    def attributes_are_unique(
        cls, value: tuple[ProposedAttribute, ...]
    ) -> tuple[ProposedAttribute, ...]:
        names = [item.name for item in value]
        if names != sorted(set(names)):
            raise ValueError("proposal attributes must be sorted and unique")
        return value

    @model_validator(mode="after")
    def citations_bind_the_proposed_source(self) -> Self:
        if any(
            item.evidence_hash != self.evidence_hash
            or item.extracted_text_hash != self.extracted_text_hash
            for item in self.citations
        ):
            raise ValueError("proposal citations must bind its evidence and extracted text")
        return self


class AdmissionReviewerKind(StrEnum):
    DETERMINISTIC_BENCHMARK = "DETERMINISTIC_BENCHMARK"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"


class AdmissionCheck(CanonicalContract):
    schema_version: Literal["event-feature-admission-check/v1"] = "event-feature-admission-check/v1"
    check_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    passed: bool
    evidence_hashes: tuple[str, ...]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("evidence_hashes")
    @classmethod
    def hashes_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("admission evidence hashes must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("admission evidence hash is invalid")
        return value


class EventFeatureAdmissionRecord(CanonicalContract):
    schema_version: Literal["event-feature-admission-record/v1"] = (
        "event-feature-admission-record/v1"
    )
    extraction_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    admission_policy_hash: str = Field(pattern=SHA256_PATTERN)
    reviewer_kind: AdmissionReviewerKind
    reviewer_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    checks: tuple[AdmissionCheck, ...]
    admitted: bool

    @model_validator(mode="after")
    def outcome_matches_checks(self) -> Self:
        ids = [item.check_id for item in self.checks]
        if not ids or ids != sorted(set(ids)):
            raise ValueError("admission checks must be nonempty, sorted, and unique")
        if self.admitted != all(item.passed for item in self.checks):
            raise ValueError("admission outcome does not match checks")
        return self


class EventFeatureRow(CanonicalContract):
    schema_version: Literal["event-feature-row/v1"] = "event-feature-row/v1"
    entity_ref: str = Field(pattern=INSTRUMENT_PATTERN)
    event_label: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    event_time: datetime
    available_at: datetime
    effective_trade_date: date
    attributes: tuple[ProposedAttribute, ...] = ()

    _timestamps_are_aware = field_validator("event_time", "available_at")(_aware)

    @model_validator(mode="after")
    def event_is_available_after_it_occurs(self) -> Self:
        if self.available_at < self.event_time:
            raise ValueError("event feature cannot be available before the event")
        names = [item.name for item in self.attributes]
        if names != sorted(set(names)):
            raise ValueError("event feature attributes must be sorted and unique")
        return self


class EventFeatureArtifact(CanonicalContract):
    schema_version: Literal["event-feature-artifact/v1"] = "event-feature-artifact/v1"
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    extracted_text_hash: str = Field(pattern=SHA256_PATTERN)
    extraction_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    admission_record_hash: str = Field(pattern=SHA256_PATTERN)
    admission_policy_hash: str = Field(pattern=SHA256_PATTERN)
    entity_resolver_policy_hash: str = Field(pattern=SHA256_PATTERN)
    trading_day_resolver_policy_hash: str = Field(pattern=SHA256_PATTERN)
    availability_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    rows: tuple[EventFeatureRow, ...]
    limitations: tuple[str, ...] = ()

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value, label="limitations")

    @field_validator("rows")
    @classmethod
    def rows_are_nonempty_sorted_unique(
        cls, value: tuple[EventFeatureRow, ...]
    ) -> tuple[EventFeatureRow, ...]:
        keys = [(item.effective_trade_date, item.entity_ref, item.event_label) for item in value]
        if not keys or keys != sorted(set(keys)):
            raise ValueError("event feature rows must be nonempty, sorted, and unique")
        return value
