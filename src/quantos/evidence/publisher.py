"""Network-denied publisher for immutable raw and deterministically parsed evidence."""

from __future__ import annotations

import html.parser
import io
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    publish_directory,
    regular_tree_files,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceAvailabilityKind,
    EvidenceRecord,
    EvidenceRevisionKind,
    EvidenceSourceKind,
    EvidenceUsePermission,
    ExtractedTextArtifact,
)
from quantos.contracts.evidence_acquisition import (
    AnnouncementCandidate,
    EvidenceFile,
    EvidencePublicationSpec,
    EvidenceStoreManifest,
    ExtractionStatus,
    PublicationTimePrecision,
    PublishedEvidenceItem,
    StagedAnnouncement,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode
from quantos.evidence.staging import EvidenceStagingError, verify_evidence_staging


class EvidencePublicationError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class EvidenceStoreResult:
    reference: ArtifactRef
    manifest: EvidenceStoreManifest
    path: Path


@dataclass(frozen=True)
class _ParsedText:
    text: str
    page_count: int
    parser_name: str
    parser_version: str
    limitations: tuple[str, ...]


class _VisibleHtmlParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style"}:
            self._hidden_depth += 1
        elif self._hidden_depth == 0 and tag.casefold() in {"br", "div", "p", "tr", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif self._hidden_depth == 0 and tag.casefold() in {"div", "p", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            self.parts.append(data)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip() + ("\n" if any(lines) else "")


def _extract_text(raw: bytes, media_type: str, encoding: str | None) -> _ParsedText:
    normalized_media = media_type.casefold().split(";", 1)[0].strip()
    if normalized_media == "application/pdf" or raw.startswith(b"%PDF-"):
        reader = PdfReader(io.BytesIO(raw), strict=False)
        pages = tuple((page.extract_text() or "") for page in reader.pages)
        text = _normalize_text("\n\f\n".join(pages))
        limitations = () if text else ("NO_MACHINE_READABLE_TEXT",)
        return _ParsedText(
            text=text,
            page_count=len(pages),
            parser_name="pypdf",
            parser_version=version("pypdf"),
            limitations=limitations,
        )
    if normalized_media == "text/plain":
        text = _normalize_text(raw.decode(encoding or "utf-8", errors="strict"))
        return _ParsedText(
            text=text,
            page_count=1,
            parser_name="python-text-decoder",
            parser_version="3.11",
            limitations=() if text else ("NO_MACHINE_READABLE_TEXT",),
        )
    if normalized_media in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleHtmlParser()
        parser.feed(raw.decode(encoding or "utf-8", errors="strict"))
        parser.close()
        text = _normalize_text("".join(parser.parts))
        return _ParsedText(
            text=text,
            page_count=1,
            parser_name="python-html.parser",
            parser_version="3.11",
            limitations=() if text else ("NO_MACHINE_READABLE_TEXT",),
        )
    raise ValueError("unsupported deterministic text media type")


def _publication_time(
    candidate: AnnouncementCandidate,
) -> tuple[datetime | None, datetime | None, EvidenceAvailabilityKind, tuple[str, ...]]:
    if candidate.publication_precision is PublicationTimePrecision.UNKNOWN:
        return None, None, EvidenceAvailabilityKind.UNKNOWN, ("UNKNOWN_PUBLICATION_TIME",)
    if candidate.publication_value is None:
        raise ValueError("qualified publication precision requires a source value")
    timezone = ZoneInfo("Asia/Shanghai")
    if candidate.publication_precision is PublicationTimePrecision.DATE:
        published_date = datetime.strptime(candidate.publication_value, "%Y-%m-%d").date()
        value = datetime.combine(published_date, time.max, tzinfo=timezone)
        return (
            value,
            value,
            EvidenceAvailabilityKind.CONSERVATIVE,
            ("DATE_ONLY_PUBLICATION_TIME", "NEXT_TRADING_SESSION_REQUIRED"),
        )
    value = datetime.fromisoformat(candidate.publication_value)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone)
    return value, value, EvidenceAvailabilityKind.PROVEN, ()


def _evidence_file(path: Path, root: Path, media_type: str) -> EvidenceFile:
    payload = path.read_bytes()
    return EvidenceFile(
        logical_path=path.relative_to(root).as_posix(),
        sha256=sha256_bytes(payload),
        size_bytes=len(payload),
        media_type=media_type,
    )


def _artifact_ref(kind: str, file: EvidenceFile) -> ArtifactRef:
    return ArtifactRef(
        kind=kind,
        sha256=file.sha256,
        size_bytes=file.size_bytes,
        media_type=file.media_type,
        logical_path=file.logical_path,
    )


class EvidencePublisher:
    """Verify collector staging, then publish raw and derived evidence offline."""

    def publish(
        self,
        staging_path: Path,
        output_root: Path,
        publication_spec: EvidencePublicationSpec,
    ) -> EvidenceStoreResult:
        try:
            staging_manifest = verify_evidence_staging(staging_path)
        except EvidenceStagingError as error:
            raise EvidencePublicationError(error.reason_code, str(error)) from None
        output_root.mkdir(parents=True, exist_ok=True)
        if output_root.is_symlink() or not output_root.is_dir():
            raise EvidencePublicationError(
                ReasonCode.PATH_BOUNDARY_VIOLATION, "evidence output root must be a real directory"
            )
        temporary = Path(tempfile.mkdtemp(prefix=".evidence-publish-", dir=output_root))
        items: list[PublishedEvidenceItem] = []
        store_limitations: set[str] = set(publication_spec.availability_policy.limitations)
        try:
            atomic_write_bytes(
                temporary / "publication-spec.json", publication_spec.canonical_bytes()
            )
            for staged in staging_manifest.announcements:
                item, limitations = self._publish_item(
                    staged,
                    staging_path,
                    temporary,
                    publication_spec,
                    collector_version=staging_manifest.collector_version,
                )
                items.append(item)
                store_limitations.update(limitations)
            bound_media_types = {
                reference.logical_path: reference.media_type
                for item in items
                for reference in (item.raw_ref, item.text_ref)
                if reference is not None
            }
            files = tuple(
                sorted(
                    (
                        _evidence_file(
                            path,
                            temporary,
                            bound_media_types.get(
                                path.relative_to(temporary).as_posix(), _media_type(path)
                            ),
                        )
                        for path in regular_tree_files(temporary)
                    ),
                    key=lambda item: item.logical_path,
                )
            )
            manifest = EvidenceStoreManifest.create(
                staging_manifest_hash=staging_manifest.staging_hash,
                publication_spec_hash=publication_spec.content_hash,
                staging_completed_at=staging_manifest.completed_at,
                items=tuple(items),
                files=files,
                limitations=tuple(sorted(store_limitations)),
            )
            atomic_write_bytes(
                temporary / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = output_root / f"sha256-{manifest.store_hash}"
            if destination.exists():
                existing = verify_evidence_store(destination)
                if existing.store_hash != manifest.store_hash:
                    raise EvidencePublicationError(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "existing evidence store does not match rebuilt output",
                    )
                shutil.rmtree(temporary)
                manifest = existing
            else:
                publish_directory(temporary, destination)
                manifest = verify_evidence_store(destination)
            encoded = (destination / "manifest.json").read_bytes()
            return EvidenceStoreResult(
                reference=ArtifactRef(
                    kind="evidence-store",
                    sha256=manifest.store_hash,
                    size_bytes=len(encoded),
                    media_type="application/json",
                    logical_path=destination.name,
                ),
                manifest=manifest,
                path=destination,
            )
        except EvidencePublicationError:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        except Exception as error:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise EvidencePublicationError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "evidence publication failed deterministic verification",
            ) from error

    def _publish_item(
        self,
        staged: StagedAnnouncement,
        staging_path: Path,
        output_root: Path,
        spec: EvidencePublicationSpec,
        *,
        collector_version: str,
    ) -> tuple[PublishedEvidenceItem, tuple[str, ...]]:
        raw_path = confined_regular_file(staging_path, staged.raw_file.logical_path)
        verify_file(raw_path, staged.raw_file.sha256)
        raw = raw_path.read_bytes()
        try:
            published_at, available_at, availability_kind, temporal_limits = _publication_time(
                staged.candidate
            )
        except ValueError:
            raise EvidencePublicationError(
                ReasonCode.EVIDENCE_RESPONSE_INVALID,
                "source publication time failed the frozen policy parser",
            ) from None
        permission = spec.availability_policy.venue_permissions[staged.candidate.venue]
        limitations = set(temporal_limits)
        limitations.update(spec.availability_policy.limitations)
        if permission is not EvidenceUsePermission.RESEARCH_ALLOWED:
            limitations.add("LICENSE_PERMISSION_NOT_RESEARCH_ALLOWED")
        if published_at is not None and published_at > staged.document_response.fetched_at:
            raise EvidencePublicationError(
                ReasonCode.UNKNOWN_AVAILABILITY,
                "source publication time follows the document fetch observation",
            )
        evidence_id = f"{staged.candidate.venue.value.lower()}-{staged.candidate.content_hash[:24]}"
        item_root = output_root / "items" / evidence_id
        raw_suffix = {
            "application/pdf": ".pdf",
            "application/xhtml+xml": ".html",
            "text/html": ".html",
            "text/plain": ".txt",
        }.get(staged.raw_file.media_type.casefold().split(";", 1)[0].strip(), ".bin")
        published_raw_path = item_root / f"raw{raw_suffix}"
        atomic_write_bytes(
            published_raw_path, raw, expected_sha256=staged.document_response.body_hash
        )
        raw_file = _evidence_file(published_raw_path, output_root, staged.raw_file.media_type)
        evidence = EvidenceRecord(
            evidence_id=evidence_id,
            source_kind=EvidenceSourceKind.EXCHANGE_ANNOUNCEMENT,
            source_locator=staged.candidate.source_locator,
            publisher=staged.candidate.publisher,
            retrieval_request_hash=staged.document_request.content_hash,
            retrieval_response_metadata_hash=staged.document_response.content_hash,
            raw_bytes_hash=staged.raw_file.sha256,
            raw_size_bytes=staged.raw_file.size_bytes,
            media_type=staged.raw_file.media_type,
            encoding=staged.document_response.encoding,
            published_at=published_at,
            fetched_at=staged.document_response.fetched_at,
            observed_at=staged.document_response.observed_at,
            available_at=available_at,
            availability_kind=availability_kind,
            availability_policy_hash=spec.availability_policy.content_hash,
            revision_kind=EvidenceRevisionKind.ORIGINAL,
            collector_version=collector_version,
            license_id=spec.availability_policy.venue_license_ids[staged.candidate.venue],
            use_permission=permission,
            entity_refs=staged.candidate.entity_refs,
            limitations=tuple(sorted(limitations)),
        )
        atomic_write_bytes(item_root / "evidence.json", evidence.canonical_bytes())

        try:
            parsed = _extract_text(
                raw, staged.raw_file.media_type, staged.document_response.encoding
            )
        except Exception:
            limitations.add("TEXT_EXTRACTION_FAILED")
            item = PublishedEvidenceItem(
                candidate=staged.candidate,
                evidence=evidence,
                raw_ref=_artifact_ref("evidence-raw", raw_file),
                extraction_status=ExtractionStatus.FAILED,
                extraction_reason=ReasonCode.EVIDENCE_TEXT_EXTRACTION_FAILED.value,
            )
        else:
            text_bytes = parsed.text.encode("utf-8")
            text_path = item_root / "text.txt"
            atomic_write_bytes(text_path, text_bytes)
            text_file = _evidence_file(text_path, output_root, "text/plain; charset=utf-8")
            extracted = ExtractedTextArtifact(
                evidence_hash=evidence.content_hash,
                raw_bytes_hash=evidence.raw_bytes_hash,
                text_hash=text_file.sha256,
                character_count=len(parsed.text),
                page_count=parsed.page_count,
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                parser_config_hash=spec.parser_config.content_hash,
                code_commit_hash=spec.code_commit_hash,
                runtime_fingerprint_hash=spec.runtime_fingerprint_hash,
                limitations=parsed.limitations,
            )
            atomic_write_bytes(item_root / "extracted-text.json", extracted.canonical_bytes())
            limitations.update(parsed.limitations)
            item = PublishedEvidenceItem(
                candidate=staged.candidate,
                evidence=evidence,
                raw_ref=_artifact_ref("evidence-raw", raw_file),
                extraction_status=ExtractionStatus.SUCCEEDED,
                extracted_text=extracted,
                text_ref=_artifact_ref("extracted-text", text_file),
            )
        atomic_write_bytes(item_root / "item.json", item.canonical_bytes())
        return item, tuple(sorted(limitations))


def _media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".pdf":
        return "application/pdf"
    if path.suffix == ".txt":
        return "text/plain; charset=utf-8"
    if path.suffix in {".htm", ".html"}:
        return "text/html"
    return "application/octet-stream"


def verify_evidence_store(path: Path) -> EvidenceStoreManifest:
    """Verify exact files, content hashes, and item bindings in an Evidence Store."""

    try:
        manifest_path = confined_regular_file(path, "manifest.json")
        manifest = EvidenceStoreManifest.model_validate_json(manifest_path.read_bytes())
        if path.name != f"sha256-{manifest.store_hash}":
            raise ValueError("evidence store directory does not bind manifest hash")
        actual = {
            item.relative_to(path).as_posix()
            for item in regular_tree_files(path)
            if item.name != "manifest.json"
        }
        manifested = {item.logical_path for item in manifest.files}
        conceptual = {"publication-spec.json"}
        for item in manifest.items:
            item_root = f"items/{item.evidence.evidence_id}"
            conceptual.update(
                {
                    f"{item_root}/evidence.json",
                    f"{item_root}/item.json",
                    item.raw_ref.logical_path,
                }
            )
            if item.extracted_text is not None and item.text_ref is not None:
                conceptual.update({f"{item_root}/extracted-text.json", item.text_ref.logical_path})
        if actual != manifested or manifested != conceptual:
            raise ValueError("evidence store exact-file set does not match manifest")
        for item in manifest.files:
            target = confined_regular_file(path, item.logical_path)
            verify_file(target, item.sha256)
            if target.stat().st_size != item.size_bytes:
                raise ValueError("evidence store file size does not match manifest")
        publication_spec = EvidencePublicationSpec.model_validate_json(
            confined_regular_file(path, "publication-spec.json").read_bytes()
        )
        if publication_spec.content_hash != manifest.publication_spec_hash:
            raise ValueError("publication spec hash does not match store manifest")
        files_by_path = {item.logical_path: item for item in manifest.files}
        for item in manifest.items:
            item_root = f"items/{item.evidence.evidence_id}"
            stored_item = PublishedEvidenceItem.model_validate_json(
                confined_regular_file(path, f"{item_root}/item.json").read_bytes()
            )
            stored_evidence = EvidenceRecord.model_validate_json(
                confined_regular_file(path, f"{item_root}/evidence.json").read_bytes()
            )
            if stored_item != item or stored_evidence != item.evidence:
                raise ValueError("stored evidence item does not match store manifest")
            raw = confined_regular_file(path, item.raw_ref.logical_path)
            verify_file(raw, item.evidence.raw_bytes_hash)
            raw_file = files_by_path[item.raw_ref.logical_path]
            if (
                raw_file.sha256 != item.raw_ref.sha256
                or raw_file.size_bytes != item.raw_ref.size_bytes
                or raw_file.media_type != item.raw_ref.media_type
            ):
                raise ValueError("raw reference does not match store file manifest")
            if item.extracted_text is not None and item.text_ref is not None:
                stored_text = ExtractedTextArtifact.model_validate_json(
                    confined_regular_file(path, f"{item_root}/extracted-text.json").read_bytes()
                )
                if stored_text != item.extracted_text:
                    raise ValueError("stored extracted text does not match store manifest")
                text_file = files_by_path[item.text_ref.logical_path]
                if (
                    text_file.sha256 != item.text_ref.sha256
                    or text_file.size_bytes != item.text_ref.size_bytes
                    or text_file.media_type != item.text_ref.media_type
                ):
                    raise ValueError("text reference does not match store file manifest")
                text = confined_regular_file(path, item.text_ref.logical_path)
                verify_file(text, item.extracted_text.text_hash)
    except (OSError, ValueError, ArtifactIntegrityError):
        raise EvidencePublicationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "evidence store failed exact-file or hash verification",
        ) from None
    return manifest
