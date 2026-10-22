"""Explicit local-file provenance; no HTTP staging or research admission implied."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal, Self

from pydantic import Field, PositiveInt, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import EvidenceRecord, ExtractedTextArtifact
from quantos.contracts.evidence_acquisition import EvidenceFile
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef


class LocalReadReceipt(CanonicalContract):
    schema_version: Literal["local-evidence-read/v1"] = "local-evidence-read/v1"
    operation: Literal["READ_LOCAL_FILE"] = "READ_LOCAL_FILE"
    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    source_path: str
    expected_raw_hash: str = Field(pattern=SHA256_PATTERN)
    observed_raw_hash: str = Field(pattern=SHA256_PATTERN)
    observed_size: int = Field(ge=0)
    read_started_at: datetime
    read_completed_at: datetime
    source_declaration_hash: str = Field(pattern=SHA256_PATTERN)
    parser_origin_hash: str = Field(pattern=SHA256_PATTERN)
    remote_download_time_known: Literal[False] = False

    @model_validator(mode="after")
    def genuine_local_observation(self) -> Self:
        if any(
            t.tzinfo is None or t.utcoffset() is None
            for t in (self.read_started_at, self.read_completed_at)
        ):
            raise ValueError("local read times must be aware")
        if (
            self.read_started_at > self.read_completed_at
            or self.expected_raw_hash != self.observed_raw_hash
        ):
            raise ValueError("local receipt identity/time mismatch")
        return self


class LocalImportPolicy(CanonicalContract):
    schema_version: Literal["local-evidence-import-policy/v1"] = "local-evidence-import-policy/v1"
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    code_commit_hash: str = Field(pattern=r"^[a-f0-9]{40}$")
    importer_source_hash: str = Field(pattern=SHA256_PATTERN)
    adoption_record_hashes: tuple[str, ...]
    purpose: Literal["DOCUMENT_UNDERSTANDING_TEST"] = "DOCUMENT_UNDERSTANDING_TEST"
    research_admission_granted: Literal[False] = False
    source_permission_upgrade_allowed: Literal[False] = False
    availability_policy: Literal["UNKNOWN_NO_HISTORICAL_PIT_CLAIM"] = (
        "UNKNOWN_NO_HISTORICAL_PIT_CLAIM"
    )


class LocalPublishedEvidence(CanonicalContract):
    schema_version: Literal["local-published-evidence/v1"] = "local-published-evidence/v1"
    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    evidence: EvidenceRecord
    extracted_text: ExtractedTextArtifact
    raw_ref: ArtifactRef
    text_ref: ArtifactRef
    page_map_ref: ArtifactRef
    receipt_ref: ArtifactRef
    source_declaration_ref: ArtifactRef
    parser_origin_ref: ArtifactRef
    physical_pdf_pages: PositiveInt
    company_group: str

    @model_validator(mode="after")
    def bindings_agree(self) -> Self:
        if (
            self.raw_ref.sha256 != self.evidence.raw_bytes_hash
            or self.raw_ref.size_bytes != self.evidence.raw_size_bytes
            or self.extracted_text.evidence_hash != self.evidence.content_hash
            or self.extracted_text.raw_bytes_hash != self.evidence.raw_bytes_hash
            or self.extracted_text.text_hash != self.text_ref.sha256
            or self.extracted_text.page_count != self.physical_pdf_pages
        ):
            raise ValueError("local item binding mismatch")
        return self


class LocalEvidenceStoreManifest(CanonicalContract):
    schema_version: Literal["local-evidence-store-manifest/v1"] = "local-evidence-store-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"store_hash"})
    store_hash: str = Field(pattern=SHA256_PATTERN)
    import_policy_hash: str = Field(pattern=SHA256_PATTERN)
    imported_at: datetime
    items: tuple[LocalPublishedEvidence, ...]
    files: tuple[EvidenceFile, ...]

    @model_validator(mode="after")
    def exact_identity(self) -> Self:
        if self.imported_at.tzinfo is None or self.imported_at.utcoffset() is None:
            raise ValueError("import time must be aware")
        ids = [i.sample_id for i in self.items]
        paths = [f.logical_path for f in self.files]
        if not ids or ids != sorted(set(ids)) or paths != sorted(set(paths)):
            raise ValueError("local store items/files must be nonempty and unique/sorted")
        if self.store_hash != self.content_hash:
            raise ValueError("local store hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        import_policy_hash: str,
        imported_at: datetime,
        items: tuple[LocalPublishedEvidence, ...],
        files: tuple[EvidenceFile, ...],
    ) -> Self:
        values = dict(
            import_policy_hash=import_policy_hash,
            imported_at=imported_at,
            items=items,
            files=files,
        )
        payload = {"schema_version": "local-evidence-store-manifest/v1", **values}
        return cls(
            store_hash=sha256_bytes(canonical_json_bytes(payload)),
            import_policy_hash=import_policy_hash,
            imported_at=imported_at,
            items=items,
            files=files,
        )
