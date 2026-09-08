"""Contracts for isolated exchange-announcement acquisition and publication."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceRecord,
    EvidenceUsePermission,
    ExtractedTextArtifact,
)
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef, validate_logical_path


class ExchangeVenue(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"


class PublicationTimePrecision(StrEnum):
    SECOND = "SECOND"
    DATE = "DATE"
    UNKNOWN = "UNKNOWN"


class CompletenessUnit(StrEnum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    ANNOUNCEMENT_GROUP = "ANNOUNCEMENT_GROUP"


class ExtractionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EvidenceCollectionSpec(CanonicalContract):
    schema_version: Literal["evidence-collection-spec/v1"] = "evidence-collection-spec/v1"
    collection_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    venues: tuple[ExchangeVenue, ...]
    start_date: date
    end_date: date
    page_size: PositiveInt = Field(default=25, le=50)
    max_announcements: PositiveInt = Field(default=5_000, le=25_000)
    security_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    title_keyword: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("venues")
    @classmethod
    def venues_are_nonempty_sorted_unique(
        cls, value: tuple[ExchangeVenue, ...]
    ) -> tuple[ExchangeVenue, ...]:
        if not value or value != tuple(sorted(set(value), key=str)):
            raise ValueError("venues must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def date_range_is_bounded(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date cannot follow end_date")
        if (self.end_date - self.start_date).days > 31:
            raise ValueError("one evidence collection may cover at most 32 calendar days")
        return self


class EvidenceCollectorPolicy(CanonicalContract):
    schema_version: Literal["evidence-collector-policy/v1"] = "evidence-collector-policy/v1"
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    user_agent: str = Field(min_length=10, max_length=300)
    requests_per_minute: PositiveInt = Field(le=120)
    max_attempts: PositiveInt = Field(default=3, le=10)
    retry_min_seconds: float = Field(default=1.0, ge=0, le=60)
    retry_max_seconds: float = Field(default=8.0, ge=0, le=300)
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_response_bytes: PositiveInt = Field(default=52_428_800, le=104_857_600)
    allowed_hosts: tuple[str, ...]
    collector_version: str = Field(min_length=1, max_length=200)

    @field_validator("allowed_hosts")
    @classmethod
    def hosts_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("allowed_hosts must be nonempty, sorted, and unique")
        if any(not host or "/" in host or ":" in host for host in value):
            raise ValueError("allowed_hosts must contain bare host names")
        return value

    @model_validator(mode="after")
    def retry_range_is_ordered(self) -> Self:
        if self.retry_min_seconds > self.retry_max_seconds:
            raise ValueError("retry_min_seconds cannot exceed retry_max_seconds")
        return self


class EvidenceAvailabilityPolicy(CanonicalContract):
    schema_version: Literal["evidence-availability-policy/v1"] = "evidence-availability-policy/v1"
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    source_timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    date_only_available_at_end_of_day: Literal[True] = True
    unknown_time_requires_next_trading_session: Literal[True] = True
    venue_permissions: dict[ExchangeVenue, EvidenceUsePermission]
    venue_license_ids: dict[ExchangeVenue, str]
    limitations: tuple[str, ...] = ()

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("limitations must be sorted and unique")
        return value

    @model_validator(mode="after")
    def venue_maps_are_complete(self) -> Self:
        expected = set(ExchangeVenue)
        if set(self.venue_permissions) != expected or set(self.venue_license_ids) != expected:
            raise ValueError("availability policy must cover every supported venue")
        if any(not value for value in self.venue_license_ids.values()):
            raise ValueError("venue license identifiers must be nonempty")
        return self


class EvidenceParserConfig(CanonicalContract):
    schema_version: Literal["evidence-parser-config/v1"] = "evidence-parser-config/v1"
    config_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    normalize_unicode: Literal["NFC"] = "NFC"
    newline: Literal["LF"] = "LF"
    page_separator: Literal["\n\f\n"] = "\n\f\n"
    strip_trailing_space: Literal[True] = True
    allow_empty_text: Literal[True] = True


class EvidencePublicationSpec(CanonicalContract):
    schema_version: Literal["evidence-publication-spec/v1"] = "evidence-publication-spec/v1"
    availability_policy: EvidenceAvailabilityPolicy
    parser_config: EvidenceParserConfig
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)


class EvidenceHttpRequest(CanonicalContract):
    schema_version: Literal["evidence-http-request/v1"] = "evidence-http-request/v1"
    sequence: PositiveInt
    venue: ExchangeVenue
    purpose: Literal["DISCOVERY", "DOCUMENT"]
    method: Literal["GET", "POST"]
    url: str = Field(min_length=1, max_length=4096)
    body_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    content_type: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def body_semantics_match_method(self) -> Self:
        if self.method == "GET" and (self.body_hash is not None or self.content_type is not None):
            raise ValueError("GET requests cannot bind a body")
        if self.method == "POST" and (self.body_hash is None or self.content_type is None):
            raise ValueError("POST requests require a body hash and content type")
        return self


class EvidenceHttpResponseMetadata(CanonicalContract):
    schema_version: Literal["evidence-http-response-metadata/v1"] = (
        "evidence-http-response-metadata/v1"
    )
    request_hash: str = Field(pattern=SHA256_PATTERN)
    status_code: int = Field(ge=100, le=599)
    fetched_at: datetime
    observed_at: datetime
    media_type: str = Field(min_length=1, max_length=200)
    encoding: str | None = Field(default=None, min_length=1, max_length=80)
    content_length: NonNegativeInt
    body_hash: str = Field(pattern=SHA256_PATTERN)
    etag: str | None = Field(default=None, max_length=500)
    last_modified: str | None = Field(default=None, max_length=500)
    attempt_count: PositiveInt

    @model_validator(mode="after")
    def timestamps_are_ordered_and_aware(self) -> Self:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.fetched_at, self.observed_at)
        ):
            raise ValueError("response timestamps must be timezone-aware")
        if self.fetched_at > self.observed_at:
            raise ValueError("fetched_at cannot follow observed_at")
        return self


class AnnouncementCandidate(CanonicalContract):
    schema_version: Literal["announcement-candidate/v1"] = "announcement-candidate/v1"
    venue: ExchangeVenue
    source_id: str = Field(min_length=1, max_length=200)
    publisher: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    source_locator: str = Field(min_length=1, max_length=4096)
    document_url: str = Field(min_length=1, max_length=4096)
    publication_value: str | None = Field(default=None, max_length=80)
    publication_precision: PublicationTimePrecision
    entity_refs: tuple[str, ...]
    revision_kind: Literal["ORIGINAL"] = "ORIGINAL"

    @field_validator("entity_refs")
    @classmethod
    def entities_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("candidate entity_refs must be sorted and unique")
        return value


class EvidenceCompletenessWitness(CanonicalContract):
    schema_version: Literal["evidence-completeness-witness/v1"] = "evidence-completeness-witness/v1"
    venue: ExchangeVenue
    query_hash: str = Field(pattern=SHA256_PATTERN)
    unit: CompletenessUnit
    reported_total: NonNegativeInt
    collected_total: NonNegativeInt
    page_count: NonNegativeInt
    page_item_counts: tuple[NonNegativeInt, ...]
    complete: bool
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def outcome_matches_counts(self) -> Self:
        if self.page_count != len(self.page_item_counts):
            raise ValueError("page count does not match page evidence")
        if sum(self.page_item_counts) != self.collected_total:
            raise ValueError("collected total does not match page evidence")
        if self.complete != (self.reported_total == self.collected_total):
            raise ValueError("completeness outcome does not match source count")
        if self.reported_total > 0 and self.page_count == 0:
            raise ValueError("nonempty result requires page evidence")
        return self


class EvidenceFile(CanonicalContract):
    schema_version: Literal["evidence-file/v1"] = "evidence-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt
    media_type: str = Field(min_length=1, max_length=200)

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class StagedAnnouncement(CanonicalContract):
    schema_version: Literal["staged-announcement/v1"] = "staged-announcement/v1"
    candidate: AnnouncementCandidate
    discovery_request_hash: str = Field(pattern=SHA256_PATTERN)
    discovery_response_metadata_hash: str = Field(pattern=SHA256_PATTERN)
    document_request: EvidenceHttpRequest
    document_response: EvidenceHttpResponseMetadata
    raw_file: EvidenceFile

    @model_validator(mode="after")
    def raw_bindings_match(self) -> Self:
        if self.document_response.request_hash != self.document_request.content_hash:
            raise ValueError("document response does not bind its request")
        if (
            self.raw_file.sha256 != self.document_response.body_hash
            or self.raw_file.size_bytes != self.document_response.content_length
        ):
            raise ValueError("raw file does not bind document response")
        return self


class EvidenceStagingManifest(CanonicalContract):
    schema_version: Literal["evidence-staging-manifest/v1"] = "evidence-staging-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"staging_hash"})

    staging_hash: str = Field(pattern=SHA256_PATTERN)
    collection_spec_hash: str = Field(pattern=SHA256_PATTERN)
    collector_policy_hash: str = Field(pattern=SHA256_PATTERN)
    collector_version: str = Field(min_length=1, max_length=200)
    started_at: datetime
    completed_at: datetime
    discovery_requests: tuple[EvidenceHttpRequest, ...]
    discovery_responses: tuple[EvidenceHttpResponseMetadata, ...]
    completeness: tuple[EvidenceCompletenessWitness, ...]
    announcements: tuple[StagedAnnouncement, ...]
    files: tuple[EvidenceFile, ...]

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.started_at, self.completed_at)
        ):
            raise ValueError("staging timestamps must be timezone-aware")
        if self.started_at > self.completed_at:
            raise ValueError("staging timestamps are reversed")
        if not self.completeness or not all(item.complete for item in self.completeness):
            raise ValueError("staging publication requires complete source witnesses")
        sequences = [item.sequence for item in self.discovery_requests]
        sequences.extend(item.document_request.sequence for item in self.announcements)
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise ValueError("staging requests must have unique contiguous sequences")
        request_hashes = tuple(item.content_hash for item in self.discovery_requests)
        response_request_hashes = tuple(item.request_hash for item in self.discovery_responses)
        if request_hashes != response_request_hashes:
            raise ValueError("discovery responses must bind ordered discovery requests")
        paths = [item.logical_path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("staging files must be sorted by unique logical path")
        identities = [
            (item.candidate.venue, item.candidate.source_id) for item in self.announcements
        ]
        if identities != sorted(set(identities), key=lambda item: (str(item[0]), item[1])):
            raise ValueError("staged announcements must be sorted and unique")
        if self.staging_hash != self.content_hash:
            raise ValueError("staging_hash does not match manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        collection_spec_hash: str,
        collector_policy_hash: str,
        collector_version: str,
        started_at: datetime,
        completed_at: datetime,
        discovery_requests: tuple[EvidenceHttpRequest, ...],
        discovery_responses: tuple[EvidenceHttpResponseMetadata, ...],
        completeness: tuple[EvidenceCompletenessWitness, ...],
        announcements: tuple[StagedAnnouncement, ...],
        files: tuple[EvidenceFile, ...],
    ) -> Self:
        values = {
            "collection_spec_hash": collection_spec_hash,
            "collector_policy_hash": collector_policy_hash,
            "collector_version": collector_version,
            "started_at": started_at,
            "completed_at": completed_at,
            "discovery_requests": discovery_requests,
            "discovery_responses": discovery_responses,
            "completeness": completeness,
            "announcements": announcements,
            "files": files,
        }
        payload = {"schema_version": "evidence-staging-manifest/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            staging_hash=digest,
            collection_spec_hash=collection_spec_hash,
            collector_policy_hash=collector_policy_hash,
            collector_version=collector_version,
            started_at=started_at,
            completed_at=completed_at,
            discovery_requests=discovery_requests,
            discovery_responses=discovery_responses,
            completeness=completeness,
            announcements=announcements,
            files=files,
        )


class PublishedEvidenceItem(CanonicalContract):
    schema_version: Literal["published-evidence-item/v1"] = "published-evidence-item/v1"
    candidate: AnnouncementCandidate
    evidence: EvidenceRecord
    raw_ref: ArtifactRef
    extraction_status: ExtractionStatus
    extracted_text: ExtractedTextArtifact | None = None
    text_ref: ArtifactRef | None = None
    extraction_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def extraction_fields_match_status(self) -> Self:
        success_fields = self.extracted_text is not None and self.text_ref is not None
        if self.extraction_status is ExtractionStatus.SUCCEEDED:
            if not success_fields or self.extraction_reason is not None:
                raise ValueError("successful extraction requires text evidence only")
        elif success_fields or self.extraction_reason is None:
            raise ValueError("failed extraction requires only a stable reason")
        if self.raw_ref.sha256 != self.evidence.raw_bytes_hash:
            raise ValueError("raw reference does not bind evidence")
        if (
            self.extracted_text is not None
            and self.text_ref is not None
            and (
                self.extracted_text.evidence_hash != self.evidence.content_hash
                or self.extracted_text.text_hash != self.text_ref.sha256
            )
        ):
            raise ValueError("text reference does not bind extracted text")
        return self


class EvidenceStoreManifest(CanonicalContract):
    schema_version: Literal["evidence-store-manifest/v1"] = "evidence-store-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"store_hash"})

    store_hash: str = Field(pattern=SHA256_PATTERN)
    staging_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    publication_spec_hash: str = Field(pattern=SHA256_PATTERN)
    staging_completed_at: datetime
    items: tuple[PublishedEvidenceItem, ...]
    files: tuple[EvidenceFile, ...]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if (
            self.staging_completed_at.tzinfo is None
            or self.staging_completed_at.utcoffset() is None
        ):
            raise ValueError("staging_completed_at must be timezone-aware")
        paths = [item.logical_path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("store files must be sorted by unique logical path")
        identities = [(item.candidate.venue, item.candidate.source_id) for item in self.items]
        if identities != sorted(set(identities), key=lambda item: (str(item[0]), item[1])):
            raise ValueError("published evidence items must be sorted and unique")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("store limitations must be sorted and unique")
        if self.store_hash != self.content_hash:
            raise ValueError("store_hash does not match manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        staging_manifest_hash: str,
        publication_spec_hash: str,
        staging_completed_at: datetime,
        items: tuple[PublishedEvidenceItem, ...],
        files: tuple[EvidenceFile, ...],
        limitations: tuple[str, ...],
    ) -> Self:
        values = {
            "staging_manifest_hash": staging_manifest_hash,
            "publication_spec_hash": publication_spec_hash,
            "staging_completed_at": staging_completed_at,
            "items": items,
            "files": files,
            "limitations": limitations,
        }
        payload = {"schema_version": "evidence-store-manifest/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            store_hash=digest,
            staging_manifest_hash=staging_manifest_hash,
            publication_spec_hash=publication_spec_hash,
            staging_completed_at=staging_completed_at,
            items=items,
            files=files,
            limitations=limitations,
        )
