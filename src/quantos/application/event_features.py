"""Deterministic P13 admission, market-session resolution, and publication."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from pydantic import ValidationError

from quantos.application.admission import EventFeatureAdmissionError, build_event_feature_artifact
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    publish_directory,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.event_research import (
    EventFeatureAdmissionPolicySpec,
    EventFeatureArtifactFile,
    EventFeatureArtifactManifest,
    TradingSessionResolution,
    TradingSessionResolverPolicy,
)
from quantos.contracts.evidence import (
    AdmissionCheck,
    EventFeatureAdmissionRecord,
    EventFeatureArtifact,
    EventFeatureRow,
    EvidenceAvailabilityKind,
    EvidenceExtractionProposal,
    EvidenceRecord,
    EvidenceUsePermission,
    ExtractedTextArtifact,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.status import ReasonCode
from quantos.data.snapshot import SnapshotBuildError, verify_snapshot


class EventFeatureError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class EventFeatureBuildResult:
    reference: ArtifactRef
    manifest: EventFeatureArtifactManifest
    feature: EventFeatureArtifact
    path: Path


class FrozenEventFeatureAdmissionPolicy:
    """Admit only proposals that exactly match a human-frozen benchmark case."""

    def __init__(self, spec: EventFeatureAdmissionPolicySpec) -> None:
        self.spec = spec
        self._cases = {item.evidence_hash: item for item in spec.cases}

    @property
    def policy_hash(self) -> str:
        return self.spec.content_hash

    def evaluate(
        self,
        evidence: EvidenceRecord,
        extracted_text: ExtractedTextArtifact,
        extracted_text_content: str,
        proposal: EvidenceExtractionProposal,
    ) -> EventFeatureAdmissionRecord:
        case = self._cases.get(evidence.content_hash)
        bindings = (
            evidence.content_hash,
            extracted_text.content_hash,
            proposal.content_hash,
        )
        evidence_hashes = tuple(sorted(bindings))
        text_matches = (
            sha256_bytes(extracted_text_content.encode("utf-8")) == extracted_text.text_hash
            and len(extracted_text_content) == extracted_text.character_count
        )
        citations_match_text = text_matches and all(
            citation.char_start is not None
            and citation.char_end is not None
            and citation.char_end <= len(extracted_text_content)
            and sha256_bytes(
                extracted_text_content[citation.char_start : citation.char_end].encode("utf-8")
            )
            == citation.cited_text_hash
            for citation in proposal.citations
        )
        source_matches = (
            extracted_text.evidence_hash == evidence.content_hash
            and proposal.evidence_hash == evidence.content_hash
            and proposal.extracted_text_hash == extracted_text.content_hash
        )
        checks = [
            AdmissionCheck(
                check_id="availability-qualified",
                passed=(
                    evidence.availability_kind is not EvidenceAvailabilityKind.UNKNOWN
                    and evidence.available_at is not None
                    and proposal.proposed_event_time is not None
                ),
                evidence_hashes=evidence_hashes,
                reason="source availability and proposed event time are qualified",
            ),
            AdmissionCheck(
                check_id="benchmark-case-present",
                passed=case is not None,
                evidence_hashes=evidence_hashes,
                reason="source has one frozen benchmark expectation",
            ),
            AdmissionCheck(
                check_id="citation-text-exact",
                passed=citations_match_text,
                evidence_hashes=evidence_hashes,
                reason="all citations bind exact character ranges and text hashes",
            ),
            AdmissionCheck(
                check_id="research-use-permitted",
                passed=evidence.use_permission is EvidenceUsePermission.RESEARCH_ALLOWED,
                evidence_hashes=evidence_hashes,
                reason="source policy explicitly permits research use",
            ),
            AdmissionCheck(
                check_id="source-lineage-exact",
                passed=source_matches,
                evidence_hashes=evidence_hashes,
                reason="proposal and extracted text bind the immutable EvidenceRecord",
            ),
        ]
        exact = case is not None and (
            case.extracted_text_hash == extracted_text.content_hash
            and case.event_label == proposal.event_label
            and case.entity_refs == proposal.entity_refs
            and case.event_time == proposal.proposed_event_time
            and case.citations == proposal.citations
            and case.attributes == proposal.attributes
            and case.entity_refs == evidence.entity_refs
        )
        checks.append(
            AdmissionCheck(
                check_id="semantic-benchmark-exact",
                passed=exact,
                evidence_hashes=evidence_hashes,
                reason="proposal exactly matches the frozen reviewed event semantics",
            )
        )
        ordered = tuple(sorted(checks, key=lambda item: item.check_id))
        reviewer_hash = case.content_hash if case is not None else self.spec.content_hash
        return EventFeatureAdmissionRecord(
            extraction_proposal_hash=proposal.content_hash,
            evidence_hash=evidence.content_hash,
            extracted_text_hash=extracted_text.content_hash,
            admission_policy_hash=self.spec.content_hash,
            reviewer_kind=self.spec.reviewer_kind,
            reviewer_evidence_hash=reviewer_hash,
            checks=ordered,
            admitted=all(item.passed for item in ordered),
        )


def _snapshot_file_hash(manifest: DataSnapshotManifest, logical_path: str) -> str:
    matches = [item.sha256 for item in manifest.files if item.logical_path == logical_path]
    if len(matches) != 1:
        raise EventFeatureError(
            ReasonCode.SOURCE_INCOMPLETE,
            f"snapshot does not bind required file: {logical_path}",
        )
    return matches[0]


def resolve_trading_sessions(
    evidence: EvidenceRecord,
    snapshot_path: Path,
    policy: TradingSessionResolverPolicy,
) -> tuple[TradingSessionResolution, ...]:
    """Resolve each admitted entity to the strict next open market session."""

    if evidence.available_at is None:
        raise EventFeatureError(
            ReasonCode.UNKNOWN_AVAILABILITY,
            "event availability is required before trading-session resolution",
        )
    try:
        snapshot = verify_snapshot(snapshot_path)
    except SnapshotBuildError as error:
        raise EventFeatureError(error.reason_code, str(error)) from None
    calendar_hash = _snapshot_file_hash(snapshot, policy.calendar_table)
    instrument_hash = _snapshot_file_hash(snapshot, policy.instrument_table)
    calendar_path = confined_regular_file(snapshot_path, policy.calendar_table)
    instruments_path = confined_regular_file(snapshot_path, policy.instrument_table)
    verify_file(calendar_path, calendar_hash)
    verify_file(instruments_path, instrument_hash)
    instrument_rows = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        instruments_path, columns=["instrument_id", "exchange"]
    ).to_pylist()
    exchanges = {
        cast(str, row["instrument_id"]): cast(str, row["exchange"]) for row in instrument_rows
    }
    local_date = evidence.available_at.astimezone(ZoneInfo(policy.source_timezone)).date()
    if local_date < snapshot.start_date or local_date > snapshot.end_date:
        raise EventFeatureError(
            ReasonCode.SOURCE_INCOMPLETE,
            "event availability falls outside the frozen snapshot range",
        )
    rows = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        calendar_path, columns=["exchange", "trade_date", "is_open"]
    ).to_pylist()
    open_dates: dict[str, list[date]] = {}
    for row in rows:
        if row["is_open"] is True and cast(date, row["trade_date"]) > local_date:
            open_dates.setdefault(cast(str, row["exchange"]), []).append(
                cast(date, row["trade_date"])
            )
    resolved: list[TradingSessionResolution] = []
    for entity_ref in evidence.entity_refs:
        exchange = exchanges.get(entity_ref)
        if exchange not in {"SSE", "SZSE"}:
            raise EventFeatureError(
                ReasonCode.SOURCE_INCOMPLETE,
                "event entity does not resolve in the frozen market snapshot",
            )
        candidates = sorted(set(open_dates.get(exchange, [])))
        if not candidates:
            raise EventFeatureError(
                ReasonCode.SOURCE_INCOMPLETE,
                "snapshot has no open session after event availability",
            )
        if (candidates[0] - local_date).days > policy.max_calendar_gap_days:
            raise EventFeatureError(
                ReasonCode.SOURCE_INCOMPLETE,
                "next open session exceeds the frozen resolver gap bound",
            )
        resolved.append(
            TradingSessionResolution(
                snapshot_hash=snapshot.snapshot_hash,
                resolver_policy_hash=policy.content_hash,
                calendar_file_hash=calendar_hash,
                instrument_file_hash=instrument_hash,
                evidence_hash=evidence.content_hash,
                evidence_available_at=evidence.available_at,
                entity_ref=entity_ref,
                exchange=cast(Literal["SSE", "SZSE"], exchange),
                effective_trade_date=candidates[0],
            )
        )
    return tuple(sorted(resolved, key=lambda item: item.entity_ref))


def _artifact_files(root: Path) -> tuple[EventFeatureArtifactFile, ...]:
    return tuple(
        EventFeatureArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in regular_tree_files(root)
        if path.name != "manifest.json"
    )


def publish_event_feature_artifact(
    *,
    evidence: EvidenceRecord,
    extracted_text: ExtractedTextArtifact,
    extracted_text_content: str,
    proposal: EvidenceExtractionProposal,
    admission_policy: FrozenEventFeatureAdmissionPolicy,
    resolver_policy: TradingSessionResolverPolicy,
    snapshot_path: Path,
    output_root: Path,
    code_commit_hash: str,
    runtime_fingerprint_hash: str,
    limitations: tuple[str, ...] = (),
) -> EventFeatureBuildResult:
    """Qualify and atomically publish an immutable EventFeatureArtifact."""

    admission = admission_policy.evaluate(
        evidence, extracted_text, extracted_text_content, proposal
    )
    if not admission.admitted:
        raise EventFeatureError(
            ReasonCode.ADMISSION_REJECTED,
            "proposal did not pass the frozen event-feature admission benchmark",
        )
    event_time = proposal.proposed_event_time
    available_at = evidence.available_at
    if event_time is None or available_at is None:
        raise EventFeatureError(
            ReasonCode.UNKNOWN_AVAILABILITY,
            "qualified event time and availability are required",
        )
    resolutions = resolve_trading_sessions(evidence, snapshot_path, resolver_policy)
    rows = tuple(
        EventFeatureRow(
            entity_ref=item.entity_ref,
            event_label=proposal.event_label,
            event_time=event_time,
            available_at=available_at,
            effective_trade_date=item.effective_trade_date,
            attributes=proposal.attributes,
        )
        for item in resolutions
    )
    snapshot = verify_snapshot(snapshot_path)
    try:
        feature = build_event_feature_artifact(
            evidence,
            extracted_text,
            proposal,
            admission,
            extracted_text_content,
            rows,
            resolutions,
            entity_resolver_policy_hash=resolver_policy.content_hash,
            trading_day_resolver_policy_hash=resolver_policy.content_hash,
            source_snapshot_hash=snapshot.snapshot_hash,
            code_commit_hash=code_commit_hash,
            runtime_fingerprint_hash=runtime_fingerprint_hash,
            limitations=limitations,
        )
    except EventFeatureAdmissionError as error:
        raise EventFeatureError(error.reason_code, str(error)) from None
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".event-feature-", dir=output_root))
    try:
        payloads = {
            "admission-policy.json": admission_policy.spec.canonical_bytes(),
            "admission-record.json": admission.canonical_bytes(),
            "evidence.json": evidence.canonical_bytes(),
            "extracted-text.json": extracted_text.canonical_bytes(),
            "extraction-proposal.json": proposal.canonical_bytes(),
            "feature.json": feature.canonical_bytes(),
            "resolver-policy.json": resolver_policy.canonical_bytes(),
            "trading-session-resolutions.json": canonical_json_bytes(
                [item.model_dump(mode="python") for item in resolutions]
            ),
        }
        for name, payload in payloads.items():
            atomic_write_bytes(temporary / name, payload)
        manifest = EventFeatureArtifactManifest.create(
            feature_hash=feature.content_hash,
            evidence_hash=evidence.content_hash,
            extracted_text_hash=extracted_text.content_hash,
            extraction_proposal_hash=proposal.content_hash,
            admission_record_hash=admission.content_hash,
            admission_policy_hash=admission_policy.policy_hash,
            resolver_policy_hash=resolver_policy.content_hash,
            resolution_hashes=feature.trading_session_resolution_hashes,
            snapshot_hash=snapshot.snapshot_hash,
            files=_artifact_files(temporary),
        )
        atomic_write_bytes(
            temporary / "manifest.json",
            canonical_json_bytes(manifest.model_dump(mode="python")),
        )
        destination = output_root / f"sha256-{manifest.artifact_hash}"
        if destination.exists():
            existing = verify_event_feature_artifact(destination)
            if existing != manifest:
                raise EventFeatureError(
                    ReasonCode.DUPLICATE_ID_CONFLICT,
                    "existing event feature artifact differs from rebuild",
                )
            shutil.rmtree(temporary)
        else:
            publish_directory(temporary, destination)
        verified = verify_event_feature_artifact(destination)
        encoded = (destination / "manifest.json").read_bytes()
        return EventFeatureBuildResult(
            reference=ArtifactRef(
                kind="event-feature",
                sha256=verified.artifact_hash,
                size_bytes=len(encoded),
                media_type="application/json",
                logical_path=destination.name,
            ),
            manifest=verified,
            feature=feature,
            path=destination,
        )
    except EventFeatureError:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    except (OSError, ValueError, ArtifactConflictError, ArtifactIntegrityError) as error:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise EventFeatureError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event feature publication failed deterministic verification",
        ) from error


def verify_event_feature_artifact(path: Path) -> EventFeatureArtifactManifest:
    try:
        manifest = EventFeatureArtifactManifest.model_validate_json(
            confined_regular_file(path, "manifest.json").read_bytes()
        )
        if path.name != f"sha256-{manifest.artifact_hash}":
            raise ValueError("event feature directory does not bind manifest hash")
        actual = {
            item.relative_to(path).as_posix()
            for item in regular_tree_files(path)
            if item.name != "manifest.json"
        }
        expected = {item.logical_path for item in manifest.files}
        if actual != expected:
            raise ValueError("event feature exact-file set disagrees")
        for item in manifest.files:
            target = confined_regular_file(path, item.logical_path)
            verify_file(target, item.sha256)
            if target.stat().st_size != item.size_bytes:
                raise ValueError("event feature file size disagrees")
        evidence = EvidenceRecord.model_validate_json((path / "evidence.json").read_bytes())
        extracted = ExtractedTextArtifact.model_validate_json(
            (path / "extracted-text.json").read_bytes()
        )
        proposal = EvidenceExtractionProposal.model_validate_json(
            (path / "extraction-proposal.json").read_bytes()
        )
        policy = EventFeatureAdmissionPolicySpec.model_validate_json(
            (path / "admission-policy.json").read_bytes()
        )
        admission = EventFeatureAdmissionRecord.model_validate_json(
            (path / "admission-record.json").read_bytes()
        )
        resolver = TradingSessionResolverPolicy.model_validate_json(
            (path / "resolver-policy.json").read_bytes()
        )
        feature = EventFeatureArtifact.model_validate_json((path / "feature.json").read_bytes())
        raw_resolutions = json.loads((path / "trading-session-resolutions.json").read_bytes())
        resolutions = tuple(
            TradingSessionResolution.model_validate(item) for item in raw_resolutions
        )
        if (
            evidence.content_hash != manifest.evidence_hash
            or extracted.content_hash != manifest.extracted_text_hash
            or proposal.content_hash != manifest.extraction_proposal_hash
            or policy.content_hash != manifest.admission_policy_hash
            or admission.content_hash != manifest.admission_record_hash
            or resolver.content_hash != manifest.resolver_policy_hash
            or feature.content_hash != manifest.feature_hash
            or feature.source_snapshot_hash != manifest.snapshot_hash
            or tuple(sorted(item.content_hash for item in resolutions))
            != manifest.resolution_hashes
            or feature.trading_session_resolution_hashes != manifest.resolution_hashes
        ):
            raise ValueError("event feature authority bindings disagree")
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError):
        raise EventFeatureError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event feature artifact failed exact-file or hash verification",
        ) from None
    return manifest
