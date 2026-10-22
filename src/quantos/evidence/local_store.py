"""Publish verified local bytes as a separate Evidence Store format.

Existing HTTP publisher/verifier and permission/admission gates stay unchanged.
The retained extraction is rebound, never rerun. fetched_at denotes a newly
observed local file read and is explicitly qualified in the EvidenceRecord.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from quantos.application.evidence_mcp import EvidenceBinding, EvidenceMcpService
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, regular_tree_files
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceAvailabilityKind,
    EvidenceCitation,
    EvidenceCitationRequest,
    EvidenceRecord,
    EvidenceRevisionKind,
    EvidenceSourceKind,
    EvidenceUsePermission,
    ExtractedTextArtifact,
)
from quantos.contracts.evidence_acquisition import EvidenceFile
from quantos.contracts.local_evidence import (
    LocalEvidenceStoreManifest,
    LocalImportPolicy,
    LocalPublishedEvidence,
    LocalReadReceipt,
)
from quantos.contracts.refs import ArtifactRef


@dataclass(frozen=True)
class LocalImportSource:
    sample_id: str
    raw_path: str
    raw_sha256: str
    text_path: str
    text_sha256: str
    page_map_path: str
    source_declaration: dict[str, Any]
    parser_origin: dict[str, Any]
    company_group: str
    predecessor_sample_id: str | None = None
    use_permission: EvidenceUsePermission = EvidenceUsePermission.UNKNOWN


def _ref(path: Path, root: Path, kind: str, media: str) -> ArtifactRef:
    data = path.read_bytes()
    return ArtifactRef(
        kind=kind,
        logical_path=path.relative_to(root).as_posix(),
        sha256=sha256_bytes(data),
        size_bytes=len(data),
        media_type=media,
    )


def publish_local_evidence_store(
    project: Path, output_root: Path, sources: list[LocalImportSource], policy: LocalImportPolicy
) -> Path:
    if not sources or len({s.sample_id for s in sources}) != len(sources):
        raise ValueError("empty/duplicate local sources")
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.is_symlink():
        raise ValueError("local store output is a symlink")
    # Durable partial import is intentionally retained if any later step fails.
    stage = Path(tempfile.mkdtemp(prefix=".local-import-", dir=output_root))
    atomic_write_bytes(stage / "import-policy.json", policy.canonical_bytes())
    remaining = {s.sample_id: s for s in sources}
    completed: dict[str, LocalPublishedEvidence] = {}
    while remaining:
        ready = [
            s
            for s in remaining.values()
            if s.predecessor_sample_id is None or s.predecessor_sample_id in completed
        ]
        if not ready:
            raise ValueError("local predecessor missing or cyclic")
        for source in sorted(ready, key=lambda s: s.sample_id):
            item_root = stage / "items" / source.sample_id
            started = datetime.now(UTC)
            raw = confined_regular_file(project, source.raw_path).read_bytes()
            ended = datetime.now(UTC)
            text_bytes = confined_regular_file(project, source.text_path).read_bytes()
            page_bytes = confined_regular_file(project, source.page_map_path).read_bytes()
            if (
                sha256_bytes(raw) != source.raw_sha256
                or sha256_bytes(text_bytes) != source.text_sha256
            ):
                raise ValueError("retained local source identity mismatch")
            text = text_bytes.decode("utf-8")
            page_data = json.loads(page_bytes)
            if (
                page_data["text_sha256"] != source.text_sha256
                or not page_data["physical_page_map_available"]
            ):
                raise ValueError("local page map identity/readiness mismatch")
            declaration = canonical_json_bytes(source.source_declaration)
            origin = canonical_json_bytes(source.parser_origin)
            receipt = LocalReadReceipt(
                sample_id=source.sample_id,
                source_path=source.raw_path,
                expected_raw_hash=source.raw_sha256,
                observed_raw_hash=sha256_bytes(raw),
                observed_size=len(raw),
                read_started_at=started,
                read_completed_at=ended,
                source_declaration_hash=sha256_bytes(declaration),
                parser_origin_hash=sha256_bytes(origin),
            )
            predecessor = (
                completed[source.predecessor_sample_id].evidence.content_hash
                if source.predecessor_sample_id
                else None
            )
            code = source.company_group
            entities = (
                (code + (".SH" if code.startswith("6") else ".SZ"),)
                if len(code) == 6 and code.isdigit()
                else ()
            )
            limitations = tuple(
                sorted(
                    {
                        "FETCHED_AT_IS_NEW_LOCAL_READ_NOT_REMOTE_DOWNLOAD",
                        "SOURCE_URL_AND_DATES_USER_REPORTED_NOT_AUTHENTICATED",
                        "HISTORICAL_AVAILABILITY_UNKNOWN",
                        "REVISION_HISTORY_INCOMPLETE_LOCAL_LINEAGE_ONLY",
                        "SOURCE_PERMISSION_NOT_UPGRADED_BY_USER_LABEL_APPROVAL",
                    }
                )
            )
            evidence = EvidenceRecord(
                evidence_id=source.sample_id,
                source_kind=EvidenceSourceKind.EXCHANGE_ANNOUNCEMENT,
                source_locator=source.source_declaration["source_locator"],
                publisher=source.source_declaration["publisher"],
                retrieval_request_hash=receipt.content_hash,
                retrieval_response_metadata_hash=receipt.content_hash,
                raw_bytes_hash=sha256_bytes(raw),
                raw_size_bytes=len(raw),
                media_type="application/pdf",
                fetched_at=started,
                observed_at=ended,
                published_at=None,
                available_at=None,
                availability_kind=EvidenceAvailabilityKind.UNKNOWN,
                availability_policy_hash=policy.content_hash,
                revision_kind=EvidenceRevisionKind.REVISION
                if predecessor
                else EvidenceRevisionKind.ORIGINAL,
                predecessor_evidence_hash=predecessor,
                collector_version="quantos-local-file-import/v1",
                license_id="source-rights-unknown-see-local-declaration",
                use_permission=source.use_permission,
                entity_refs=entities,
                limitations=limitations,
            )
            extracted = ExtractedTextArtifact(
                evidence_hash=evidence.content_hash,
                raw_bytes_hash=evidence.raw_bytes_hash,
                text_hash=source.text_sha256,
                character_count=len(text),
                page_count=len(page_data["pages"]),
                parser_name=source.parser_origin["parser_name"],
                parser_version=source.parser_origin["parser_version"],
                parser_config_hash=sha256_bytes(origin),
                code_commit_hash=policy.code_commit_hash,
                runtime_fingerprint_hash=sha256_bytes(origin),
                limitations=(
                    "IMPORT_COMMIT_RECORDS_REBINDING_NOT_ORIGINAL_EXTRACTION",
                    "RETAINED_EXTRACTION_REUSED_NOT_RERUN",
                ),
            )
            contents = {
                "raw.pdf": raw,
                "text.txt": text_bytes,
                "pages.json": page_bytes,
                "read-receipt.json": receipt.canonical_bytes(),
                "source-declaration.json": declaration,
                "parser-origin.json": origin,
                "evidence.json": evidence.canonical_bytes(),
                "extracted-text.json": extracted.canonical_bytes(),
            }
            for name, data in contents.items():
                atomic_write_bytes(item_root / name, data)
            item = LocalPublishedEvidence(
                sample_id=source.sample_id,
                evidence=evidence,
                extracted_text=extracted,
                raw_ref=_ref(item_root / "raw.pdf", stage, "evidence-raw", "application/pdf"),
                text_ref=_ref(
                    item_root / "text.txt", stage, "extracted-text", "text/plain; charset=utf-8"
                ),
                page_map_ref=_ref(
                    item_root / "pages.json", stage, "pdf-page-map", "application/json"
                ),
                receipt_ref=_ref(
                    item_root / "read-receipt.json", stage, "local-read-receipt", "application/json"
                ),
                source_declaration_ref=_ref(
                    item_root / "source-declaration.json",
                    stage,
                    "source-declaration",
                    "application/json",
                ),
                parser_origin_ref=_ref(
                    item_root / "parser-origin.json",
                    stage,
                    "retained-parser-origin",
                    "application/json",
                ),
                physical_pdf_pages=len(page_data["pages"]),
                company_group=source.company_group,
            )
            atomic_write_bytes(item_root / "item.json", item.canonical_bytes())
            completed[source.sample_id] = item
            del remaining[source.sample_id]
    files = tuple(
        EvidenceFile(
            logical_path=p.relative_to(stage).as_posix(),
            sha256=sha256_bytes(p.read_bytes()),
            size_bytes=p.stat().st_size,
            media_type="application/pdf"
            if p.suffix == ".pdf"
            else "text/plain"
            if p.suffix == ".txt"
            else "application/json",
        )
        for p in sorted(regular_tree_files(stage))
    )
    manifest = LocalEvidenceStoreManifest.create(
        import_policy_hash=policy.content_hash,
        imported_at=datetime.now(UTC),
        items=tuple(completed[k] for k in sorted(completed)),
        files=files,
    )
    # The hash excludes store_hash; the stored envelope must include it.
    atomic_write_bytes(
        stage / "manifest.json", canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    destination = output_root / ("sha256-" + manifest.store_hash)
    if destination.exists():
        raise ValueError("local store destination already exists")
    stage.rename(destination)
    verify_local_evidence_store(destination)
    return destination


def verify_local_evidence_store(path: Path) -> LocalEvidenceStoreManifest:
    manifest = LocalEvidenceStoreManifest.model_validate_json(
        confined_regular_file(path, "manifest.json").read_bytes()
    )
    if path.name != "sha256-" + manifest.store_hash:
        raise ValueError("local store directory/hash mismatch")
    actual = {
        p.relative_to(path).as_posix()
        for p in regular_tree_files(path)
        if p.name != "manifest.json"
    }
    declared = {f.logical_path for f in manifest.files}
    expected = {"import-policy.json"}
    for item in manifest.items:
        expected.update(
            "items/" + item.sample_id + "/" + name
            for name in [
                "raw.pdf",
                "text.txt",
                "pages.json",
                "read-receipt.json",
                "source-declaration.json",
                "parser-origin.json",
                "evidence.json",
                "extracted-text.json",
                "item.json",
            ]
        )
    if actual != declared or declared != expected:
        raise ValueError("local store exact-file set mismatch")
    policy = LocalImportPolicy.model_validate_json(
        confined_regular_file(path, "import-policy.json").read_bytes()
    )
    if policy.content_hash != manifest.import_policy_hash:
        raise ValueError("local import policy binding mismatch")
    for file in manifest.files:
        data = confined_regular_file(path, file.logical_path).read_bytes()
        if sha256_bytes(data) != file.sha256 or len(data) != file.size_bytes:
            raise ValueError("local store file identity mismatch")
    by_evidence = {i.evidence.content_hash: i for i in manifest.items}
    for item in manifest.items:
        prefix = "items/" + item.sample_id + "/"
        if (
            LocalPublishedEvidence.model_validate_json(
                confined_regular_file(path, prefix + "item.json").read_bytes()
            )
            != item
        ):
            raise ValueError("local stored item differs from manifest")
        for name, contract, wanted in [
            ("evidence.json", EvidenceRecord, item.evidence),
            ("extracted-text.json", ExtractedTextArtifact, item.extracted_text),
        ]:
            if (
                contract.model_validate_json(
                    confined_regular_file(path, prefix + name).read_bytes()
                )
                != wanted
            ):
                raise ValueError("local stored contract differs from manifest")
        refs = {i.logical_path: i for i in manifest.files}
        for ref in [
            item.raw_ref,
            item.text_ref,
            item.page_map_ref,
            item.receipt_ref,
            item.source_declaration_ref,
            item.parser_origin_ref,
        ]:
            f = refs[ref.logical_path]
            if f.sha256 != ref.sha256 or f.size_bytes != ref.size_bytes:
                raise ValueError("local artifact reference mismatch")
        receipt = LocalReadReceipt.model_validate_json(
            confined_regular_file(path, item.receipt_ref.logical_path).read_bytes()
        )
        if (
            receipt.sample_id != item.sample_id
            or receipt.observed_raw_hash != item.evidence.raw_bytes_hash
            or receipt.observed_size != item.evidence.raw_size_bytes
            or receipt.content_hash != item.evidence.retrieval_request_hash
            or receipt.content_hash != item.evidence.retrieval_response_metadata_hash
            or receipt.source_declaration_hash != item.source_declaration_ref.sha256
            or receipt.parser_origin_hash != item.parser_origin_ref.sha256
            or receipt.read_started_at != item.evidence.fetched_at
            or receipt.read_completed_at != item.evidence.observed_at
            or item.evidence.availability_kind.value != "UNKNOWN"
            or item.evidence.available_at is not None
        ):
            raise ValueError("local receipt/evidence semantics mismatch")
        if (
            item.evidence.predecessor_evidence_hash
            and item.evidence.predecessor_evidence_hash not in by_evidence
        ):
            raise ValueError("local predecessor not in store")
        text = confined_regular_file(path, item.text_ref.logical_path).read_text()
        pages = json.loads(confined_regular_file(path, item.page_map_ref.logical_path).read_bytes())
        if (
            sha256_bytes(text.encode()) != item.extracted_text.text_hash
            or len(text) != item.extracted_text.character_count
            or pages["text_sha256"] != item.extracted_text.text_hash
            or len(pages["pages"]) != item.physical_pdf_pages
        ):
            raise ValueError("local text/page metadata mismatch")
        for page in pages["pages"]:
            a, b = page["char_start"], page["char_end"]
            if a is not None and not 0 <= a <= b <= len(text):
                raise ValueError("local physical page range invalid")
    return manifest


def local_binding(path: Path, item: LocalPublishedEvidence) -> EvidenceBinding:
    return EvidenceBinding(
        item.evidence,
        item.extracted_text,
        confined_regular_file(path, item.text_ref.logical_path).read_text(),
    )


def local_citation(
    binding: EvidenceBinding, pages: dict[str, Any], start: int, end: int
) -> EvidenceCitation:
    physical = [
        p["pdf_page"]
        for p in pages["pages"]
        if p["char_start"] is not None and start < p["char_end"] and end > p["char_start"]
    ]
    if not physical:
        raise ValueError("citation has no physical PDF page")
    return cast(
        EvidenceCitation,
        EvidenceMcpService({binding.evidence.content_hash: binding}).call(
            "evidence.cite",
            canonical_json_bytes(
                EvidenceCitationRequest(
                    evidence_hash=binding.evidence.content_hash,
                    extracted_text_hash=binding.extracted_text.content_hash,
                    page=physical[0],
                    char_start=start,
                    char_end=end,
                    expected_text=binding.text[start:end],
                )
            ),
        ),
    )
