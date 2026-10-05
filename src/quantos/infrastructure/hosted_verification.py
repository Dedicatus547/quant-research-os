#!/usr/bin/env python3
"""Read-only, fail-closed verifier for host-mediated qualification bundles."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from collections import defaultdict
from importlib.machinery import SourceFileLoader
from importlib.util import cache_from_source
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.backtest import BacktestArtifactManifest
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import CampaignTrial
from quantos.contracts.event_research import EventSignalArtifactManifest
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedCampaignReport,
    HostedCampaignSpec,
    HostedCheckpoint,
    HostedJournalEntry,
    HostedRequestTerminalReceipt,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
    HostedSubmissionReceipt,
    HostObservation,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import (
    HOSTED_ACCEPTANCE_SHA256,
    HOSTED_CONTRACT_SHA256,
    HOSTED_FREEZE_SHA256,
    HOSTED_QUALIFICATION_CASES,
    HostedPrincipalProjection,
    HostedQualificationCase,
    HostedQualificationFile,
    HostedQualificationGate,
    HostedQualificationManifest,
    HostedQualificationVerification,
    HostedRawInventory,
)
from quantos.contracts.ledger import ResearchLedgerSnapshot
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.refs import validate_logical_path
from quantos.contracts.research_result import ResearchResultManifest
from quantos.contracts.signal import SignalArtifactManifest
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.validation import ValidationReport

if TYPE_CHECKING:
    from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources

ROOT = Path(__file__).resolve().parents[3]
MAX_BUNDLE_FILES = 100_000
MAX_SINGLE_FILE_BYTES = 16 * 1024**3
MAX_INVENTORY_BYTES = 128 * 1024**3
MAX_TYPED_BYTES = 16_777_216
# A complete source index includes the full fault matrix, live authority and
# seven replay/tamper roots. This is not a protocol payload limit.
MAX_MANAGER_EXPORT_BYTES = 33_554_432
_CONTRACTS: dict[str, type[CanonicalContract]] = {
    "hosted-campaign-spec/v1": HostedCampaignSpec,
    "hosted-budget-journal-fact/v1": HostedBudgetJournalFact,
    "hosted-agent-request/v1": HostedAgentRequest,
    "hosted-agent-response/v1": HostedAgentResponse,
    "hosted-observation/v1": HostObservation,
    "hosted-agent-exchange/v1": HostedAgentExchange,
    "hosted-submission-receipt/v1": HostedSubmissionReceipt,
    "hosted-request-terminal-receipt/v1": HostedRequestTerminalReceipt,
    "hosted-checkpoint/v1": HostedCheckpoint,
    "hosted-research-budget-fact/v1": HostedResearchBudgetFact,
    "hosted-research-step-intent/v1": HostedResearchStepIntent,
    "hosted-campaign-report/v1": HostedCampaignReport,
    "autonomous-execution-result/v2": AutonomousExecutionResult,
    "campaign-trial/v1": CampaignTrial,
}
_C11_PROJECTION_TYPES: dict[str, type[CanonicalContract]] = {
    "signal-artifact-manifest/v2": SignalArtifactManifest,
    "backtest-artifact-manifest/v1": BacktestArtifactManifest,
    "research-result-manifest/v1": ResearchResultManifest,
    "qlib-view-manifest/v1": QlibViewManifest,
    "data-snapshot-manifest/v1": DataSnapshotManifest,
    "research-ledger-snapshot/v1": ResearchLedgerSnapshot,
    "event-signal-artifact-manifest/v1": EventSignalArtifactManifest,
}


class HostedQualificationError(RuntimeError):
    """A raw or semantic qualification binding is absent or invalid."""


def _regular_bytes(fd: int, *, max_bytes: int = MAX_TYPED_BYTES) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise HostedQualificationError("qualification file is not a unique regular file")
    if before.st_size > max_bytes:
        raise HostedQualificationError("qualification file exceeds its byte cap")
    pieces: list[bytes] = []
    remaining = max_bytes + 1
    while True:
        data = os.read(fd, min(1_048_576, remaining))
        if not data:
            break
        pieces.append(data)
        remaining -= len(data)
        if remaining <= 0:
            raise HostedQualificationError("qualification file exceeds its byte cap")
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise HostedQualificationError("qualification file changed during read")
    return b"".join(pieces)


def _regular_digest(fd: int) -> tuple[str, int]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise HostedQualificationError("qualification file is not a unique regular file")
    if before.st_size > MAX_SINGLE_FILE_BYTES:
        raise HostedQualificationError("qualification file exceeds inventory byte cap")
    hasher = hashlib.sha256()
    length = 0
    while chunk := os.read(fd, 1_048_576):
        hasher.update(chunk)
        length += len(chunk)
        if length > MAX_SINGLE_FILE_BYTES:
            raise HostedQualificationError("qualification file exceeds inventory byte cap")
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or length != after.st_size:
        raise HostedQualificationError("qualification file changed during inventory")
    return hasher.hexdigest(), length


def read_relative(root: Path, logical_path: str, *, max_bytes: int = MAX_TYPED_BYTES) -> bytes:
    """Read through pinned directory descriptors; reject traversal, aliases and special files."""
    parts = validate_logical_path(logical_path).split("/")
    with opened_directory(root) as root_fd:
        parent = os.dup(root_fd)
        try:
            for segment in parts[:-1]:
                child = os.open(
                    segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                os.close(parent)
                parent = child
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            try:
                return _regular_bytes(descriptor, max_bytes=max_bytes)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)


def digest_relative(root: Path, logical_path: str) -> tuple[str, int]:
    """Stream an anchored original file; do not buffer large research artifacts."""
    parts = validate_logical_path(logical_path).split("/")
    with opened_directory(root) as root_fd:
        parent = os.dup(root_fd)
        try:
            for segment in parts[:-1]:
                child = os.open(
                    segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                os.close(parent)
                parent = child
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            try:
                return _regular_digest(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)


def directory_inventory(root: Path) -> tuple[str, ...]:
    """Include empty directories through pinned descriptors; reject unsafe entries."""
    directories: list[str] = []
    entries = 0

    def walk(directory_fd: int, prefix: str) -> None:
        nonlocal entries
        with os.scandir(directory_fd) as iterator:
            names = sorted(item.name for item in iterator)
        for name in names:
            entries += 1
            if entries > MAX_BUNDLE_FILES:
                raise HostedQualificationError("directory inventory entry cap exceeded")
            logical = f"{prefix}/{name}" if prefix else name
            validate_logical_path(logical)
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                        raise HostedQualificationError("directory changed during inventory")
                    directories.append(logical)
                    walk(child, logical)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise HostedQualificationError("directory inventory has an unsafe entry")

    with opened_directory(root) as descriptor:
        walk(descriptor, "")
    return tuple(sorted(directories))


def raw_inventory(root: Path) -> HostedRawInventory:
    """Inventory every file using descriptor-anchored traversal; no symlink follow."""
    files: list[HostedQualificationFile] = []
    total_bytes = 0

    def walk(directory_fd: int, prefix: str) -> None:
        nonlocal total_bytes
        with os.scandir(directory_fd) as iterator:
            names = sorted(item.name for item in iterator)
        for name in names:
            logical = f"{prefix}/{name}" if prefix else name
            validate_logical_path(logical)
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                try:
                    walk(child, logical)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
                )
                try:
                    digest, length = _regular_digest(descriptor)
                finally:
                    os.close(descriptor)
                total_bytes += length
                if len(files) >= MAX_BUNDLE_FILES or total_bytes > MAX_INVENTORY_BYTES:
                    raise HostedQualificationError("qualification inventory exceeds fixed limits")
                files.append(
                    HostedQualificationFile(logical_path=logical, sha256=digest, size_bytes=length)
                )
            else:
                raise HostedQualificationError("qualification tree contains an unsafe object")

    with opened_directory(root) as directory_fd:
        walk(directory_fd, "")
    return HostedRawInventory(files=tuple(sorted(files, key=lambda item: item.logical_path)))


def verify_raw_inventory(root: Path, expected: HostedRawInventory) -> None:
    if raw_inventory(root) != expected:
        raise HostedQualificationError("raw authority inventory differs from its manifest")


def c11_manifest_projection(data: bytes, *, logical_path: str | None = None) -> tuple[str, bytes]:
    """Project only validated C11 authority manifests' top-level created_at."""
    payload = strict_json_object(data, max_bytes=16_777_216)
    schema = payload.get("schema_version")
    if not isinstance(schema, str) or schema not in _C11_PROJECTION_TYPES:
        raise HostedQualificationError("C11 projection schema is not allowlisted")
    if "created_at" not in payload:
        raise HostedQualificationError("C11 authority manifest has no top-level created_at")
    authority = _C11_PROJECTION_TYPES[schema].model_validate(payload)
    if canonical_json_bytes(authority.model_dump(mode="python")) != data:
        raise HostedQualificationError("C11 authority manifest is not canonical")
    # Ledger snapshots have no embedded self-hash: bind the derived content hash
    # to their verified content-addressed path. Other types validate embedded hashes.
    if isinstance(authority, ResearchLedgerSnapshot) and (
        logical_path is None or Path(logical_path).name != f"sha256-{authority.content_hash}.json"
    ):
        raise HostedQualificationError("C11 Ledger snapshot path/content binding is absent")
    if not isinstance(authority, ResearchLedgerSnapshot) and (
        logical_path is None
        or Path(logical_path).name != "manifest.json"
        or Path(logical_path).parent.name != f"sha256-{authority.content_hash}"
    ):
        raise HostedQualificationError("C11 manifest directory/content binding is absent")
    # Nested dates remain untouched.
    projected = canonical_json_bytes(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    return schema, projected


def compare_principal_roots(
    root_a: Path, root_b: Path, inventory_a: HostedRawInventory, inventory_b: HostedRawInventory
) -> tuple[HostedPrincipalProjection, ...]:
    """Compare exact paths/raw inventories and record every permitted C11 projection."""
    verify_raw_inventory(root_a, inventory_a)
    verify_raw_inventory(root_b, inventory_b)
    return _compare_principal_files(root_a, root_b, inventory_a, inventory_b)


def compare_verified_principal_roots(
    root_a: Path,
    root_b: Path,
    raw_a: HostedRawInventory,
    raw_b: HostedRawInventory,
    principal_a: HostedRawInventory,
    principal_b: HostedRawInventory,
    *,
    allowed_projection_paths: frozenset[str],
) -> tuple[HostedPrincipalProjection, ...]:
    """Compare business-derived subsets while retaining both complete raw inventories."""
    verify_raw_inventory(root_a, raw_a)
    verify_raw_inventory(root_b, raw_b)
    for principal, raw in ((principal_a, raw_a), (principal_b, raw_b)):
        full = _file_map(raw)
        if not principal.files or any(
            full.get(item.logical_path) != item for item in principal.files
        ):
            raise HostedQualificationError(
                "principal inventory is not a subset of verified raw bytes"
            )
    return _compare_principal_files(
        root_a, root_b, principal_a, principal_b, allowed_projection_paths=allowed_projection_paths
    )


def _compare_principal_files(
    root_a: Path,
    root_b: Path,
    inventory_a: HostedRawInventory,
    inventory_b: HostedRawInventory,
    *,
    allowed_projection_paths: frozenset[str] | None = None,
) -> tuple[HostedPrincipalProjection, ...]:
    files_a, files_b = _file_map(inventory_a), _file_map(inventory_b)
    if set(files_a) != set(files_b):
        raise HostedQualificationError("independent principal file sets differ")
    projected: list[HostedPrincipalProjection] = []
    for logical_path in sorted(files_a):
        a, b = files_a[logical_path], files_b[logical_path]
        if a.sha256 == b.sha256 and a.size_bytes == b.size_bytes:
            continue
        if allowed_projection_paths is not None and logical_path not in allowed_projection_paths:
            raise HostedQualificationError(
                "differing file is not a verified C11 authority manifest"
            )
        schema_a, projection_a = c11_manifest_projection(
            read_relative(root_a, logical_path), logical_path=logical_path
        )
        schema_b, projection_b = c11_manifest_projection(
            read_relative(root_b, logical_path), logical_path=logical_path
        )
        if schema_a != schema_b or projection_a != projection_b:
            raise HostedQualificationError("independent principal authority differs")
        projected.append(
            HostedPrincipalProjection(
                logical_path=logical_path,
                authority_schema=schema_a,
                root_a_raw_hash=a.sha256,
                root_b_raw_hash=b.sha256,
                projected_hash=sha256_bytes(projection_a),
            )
        )
    return tuple(projected)


def _typed(data: bytes) -> CanonicalContract:
    schema = strict_json_object(data, max_bytes=16_777_216).get("schema_version")
    if not isinstance(schema, str) or schema not in _CONTRACTS:
        raise HostedQualificationError("unknown hosted authority schema")
    return parse_hosted_contract(data, _CONTRACTS[schema], max_bytes=16_777_216)


def verify_protocol_root(root: Path, campaign_hash: str) -> tuple[str, ...]:
    """Independently reconcile journal bytes, typed objects and protocol budgets."""
    inventory = raw_inventory(root)
    journal_files = tuple(
        file
        for file in inventory.files
        if file.logical_path.startswith(f"campaigns/{campaign_hash}/journal/")
    )
    object_files = tuple(
        file
        for file in inventory.files
        if file.logical_path.startswith(f"campaigns/{campaign_hash}/objects/")
    )
    spec_files = tuple(file for file in inventory.files if file.logical_path.startswith("specs/"))
    if not journal_files or not object_files or not spec_files:
        raise HostedQualificationError("hosted protocol authority is incomplete")
    entries: list[HostedJournalEntry] = []
    planned: dict[str, bytes] = {}
    for number, file in enumerate(journal_files, start=1):
        entry = parse_hosted_contract(
            read_relative(root, file.logical_path, max_bytes=16_777_216),
            HostedJournalEntry,
            max_bytes=16_777_216,
        )
        expected_path = f"campaigns/{campaign_hash}/journal/{number:08d}-{entry.content_hash}.json"
        if file.logical_path != expected_path or entry.sequence != number:
            raise HostedQualificationError("hosted journal path, hash or order differs")
        if entry.campaign_hash != campaign_hash or entry.previous_hash != (
            entries[-1].content_hash if entries else None
        ):
            raise HostedQualificationError("hosted journal campaign or predecessor differs")
        if number == 1 and (entry.phase != "INTENT" or entry.operation_kind != "REGISTER"):
            raise HostedQualificationError("hosted journal registration is missing")
        if number > 1:
            previous = entries[-1]
            if entry.phase == previous.phase:
                raise HostedQualificationError("hosted journal phases do not alternate")
            if entry.phase == "COMPLETE" and (
                entry.operation_id != previous.operation_id
                or entry.operation_kind != previous.operation_kind
                or entry.recorded_at != previous.recorded_at
                or entry.artifact_hashes
                != tuple(item.artifact_hash for item in previous.publications)
            ):
                raise HostedQualificationError("hosted journal completion conflicts with intent")
        if entry.phase == "INTENT":
            for publication in entry.publications:
                data = publication.canonical_json.encode("utf-8")
                if planned.setdefault(publication.artifact_hash, data) != data:
                    raise HostedQualificationError(
                        "hosted artifact hash rebound to different bytes"
                    )
        entries.append(entry)
    if entries[-1].phase != "COMPLETE":
        raise HostedQualificationError("hosted root needs recovery before qualification")
    objects: dict[str, CanonicalContract] = {}
    for file in object_files:
        name = file.logical_path.rsplit("/", 1)[-1]
        if not name.endswith(".json") or len(name) != 69:
            raise HostedQualificationError("unexpected hosted authority object path")
        digest = name[:-5]
        data = read_relative(root, file.logical_path, max_bytes=16_777_216)
        if digest not in planned or sha256_bytes(data) != digest or planned[digest] != data:
            raise HostedQualificationError("hosted object differs from journal publication")
        objects[digest] = _typed(data)
    if set(objects) != set(planned):
        raise HostedQualificationError("hosted journal and object file sets disagree")
    specs = tuple(item for item in objects.values() if isinstance(item, HostedCampaignSpec))
    if len(specs) != 1 or specs[0].campaign_hash != campaign_hash:
        raise HostedQualificationError("hosted spec identity is invalid")
    spec = specs[0]
    if (
        f"specs/{spec.content_hash}.json" not in {file.logical_path for file in spec_files}
        or read_relative(root, f"specs/{spec.content_hash}.json") != spec.canonical_bytes()
    ):
        raise HostedQualificationError("registered hosted spec bytes differ")
    budgets = tuple(item for item in objects.values() if isinstance(item, HostedBudgetJournalFact))
    requests = tuple(item for item in objects.values() if isinstance(item, HostedAgentRequest))
    receipts = tuple(item for item in objects.values() if isinstance(item, HostedSubmissionReceipt))
    exchanges = tuple(item for item in objects.values() if isinstance(item, HostedAgentExchange))
    if not budgets:
        raise HostedQualificationError("hosted request reservations disagree")
    ordered_budgets = sorted(
        budgets, key=lambda item: (item.used_requests, item.used_unique_submissions)
    )
    final_budget = ordered_budgets[-1]
    if len(requests) != final_budget.used_requests:
        raise HostedQualificationError("hosted request reservations disagree")
    previous_budget: HostedBudgetJournalFact | None = None
    for budget in ordered_budgets:
        if (
            budget.campaign_hash != campaign_hash
            or budget.hosted_spec_hash != spec.content_hash
            or budget.previous_hash != (previous_budget.content_hash if previous_budget else None)
            or budget.used_requests > spec.hosted_budget.max_requests
            or budget.used_unique_submissions > spec.hosted_budget.max_unique_submissions
            or any(
                count.used_submissions > spec.hosted_budget.max_submissions_per_request
                for count in budget.request_submissions
            )
        ):
            raise HostedQualificationError("hosted budget chain or caps disagree")
        if previous_budget is None:
            if budget.used_requests or budget.used_unique_submissions:
                raise HostedQualificationError("hosted initial budget is nonempty")
        elif (
            budget.used_requests - previous_budget.used_requests,
            budget.used_unique_submissions - previous_budget.used_unique_submissions,
        ) not in ((1, 0), (0, 1)):
            raise HostedQualificationError("hosted budget transition is invalid")
        previous_budget = budget
    if tuple(sorted(request.transport_ordinal for request in requests)) != tuple(
        range(1, len(requests) + 1)
    ):
        raise HostedQualificationError("hosted request ordinals are incomplete")
    by_request = {request.content_hash: request for request in requests}
    by_exchange = {exchange.content_hash: exchange for exchange in exchanges}
    for request in requests:
        reservation = objects.get(request.budget_reservation_hash)
        if (
            request.campaign_hash != campaign_hash
            or request.hosted_spec_hash != spec.content_hash
            or request.candidate_manifest_hash != spec.candidate_manifest_hash
            or not isinstance(reservation, HostedBudgetJournalFact)
            or reservation.used_requests != request.transport_ordinal
        ):
            raise HostedQualificationError("hosted request frozen bindings disagree")
        checkpoint = HostedCheckpoint(
            request_hash=request.content_hash,
            campaign_hash=campaign_hash,
            transport_ordinal=request.transport_ordinal,
            recorded_at=request.issued_at,
        )
        if objects.get(checkpoint.content_hash) != checkpoint:
            raise HostedQualificationError("hosted request checkpoint is absent")
    counted: dict[str, set[tuple[bool, str]]] = defaultdict(set)
    for receipt in receipts:
        if (
            receipt.campaign_hash != campaign_hash
            or not isinstance(objects.get(receipt.budget_before_hash), HostedBudgetJournalFact)
            or not isinstance(objects.get(receipt.budget_after_hash), HostedBudgetJournalFact)
        ):
            raise HostedQualificationError("hosted receipt budget binding is invalid")
        if receipt.request_hash is None:
            if receipt.outcome != "EXHAUSTED":
                raise HostedQualificationError("unbound hosted receipt is not exhaustion")
            continue
        request = by_request.get(receipt.request_hash)
        if receipt.outcome == "EXHAUSTED":
            if (
                request is None
                or receipt.attempt_identity != request.attempt_identity
                or receipt.budget_before_hash != receipt.budget_after_hash
                or receipt.submission_bytes_hash is not None
                or receipt.observed_prefix_hash is not None
                or receipt.observed_bytes != 0
            ):
                raise HostedQualificationError("hosted exhaustion receipt is invalid")
            continue
        digest = receipt.submission_bytes_hash if receipt.complete else receipt.observed_prefix_hash
        if (
            request is None
            or receipt.attempt_identity != request.attempt_identity
            or digest is None
        ):
            raise HostedQualificationError("hosted receipt request/digest binding is invalid")
        identity = (receipt.complete, digest)
        if identity in counted[receipt.request_hash]:
            raise HostedQualificationError("duplicate unique submission was charged")
        counted[receipt.request_hash].add(identity)
        if receipt.outcome == "ACCEPTED":
            exchange = by_exchange.get(cast(str, receipt.accepted_exchange_hash))
            response = objects.get(cast(str, receipt.submission_bytes_hash))
            if (
                exchange is None
                or not isinstance(response, HostedAgentResponse)
                or exchange.request_hash != receipt.request_hash
                or exchange.response_hash != response.content_hash
                or exchange.proposal_hash != response.proposal_hash
                or exchange.host_observation_hash != response.host_observation.content_hash
                or objects.get(exchange.host_observation_hash) != response.host_observation
                or exchange.authenticated_principal != receipt.authenticated_principal
                or response.request_hash != request.content_hash
                or response.campaign_hash != campaign_hash
                or response.context_pack_hash != request.context_pack_hash
                or response.transport_ordinal != request.transport_ordinal
                or response.attempt_identity != request.attempt_identity
            ):
                raise HostedQualificationError("hosted accepted exchange does not bind response")
    if sum(len(items) for items in counted.values()) != final_budget.used_unique_submissions:
        raise HostedQualificationError("hosted unique submissions disagree with budget")
    return tuple(sorted(objects))


def _file_map(inventory: HostedRawInventory) -> dict[str, HostedQualificationFile]:
    return {item.logical_path: item for item in inventory.files}


def verify_case(
    bundle: Path, case: HostedQualificationCase, *, sources: HostedVerifiedSources | None = None
) -> HostedQualificationGate:
    hashes: set[str] = set()
    if not case.roots or not case.evidence_paths:
        return HostedQualificationGate(
            case_id=case.case_id,
            verdict="NOT_EVALUATED",
            reason="REQUIRED_CASE_EVIDENCE_UNAVAILABLE",
        )
    try:
        for logical in case.evidence_paths:
            hashes.add(sha256_bytes(read_relative(bundle, logical)))
        if case.case_id == "Q05":
            # Empty prelaunch roots and explicit forensic corruption/atomic
            # copies are not ordinary complete canonical protocol snapshots.
            # Their finite predicate binds every original phase and distinguishes
            # unsafe intermediates before invoking any native canonical reader.
            if any(not root.logical_path.startswith("cases/Q05/") for root in case.roots):
                raise HostedQualificationError("Q05 root escaped its registered scope")
            if sources is None:
                return HostedQualificationGate(
                    case_id="Q05",
                    verdict="NOT_EVALUATED",
                    reason="ORIGINAL_MANAGER_SOURCE_UNAVAILABLE",
                    checked_artifact_hashes=tuple(sorted(hashes)),
                )
            from quantos.infrastructure.hosted_fault_verification import verify_q05

            hashes.update(verify_q05(bundle, case, sources))
            return HostedQualificationGate(
                case_id="Q05",
                verdict="PASS",
                reason="ORIGINAL_SCENARIO_AUTHORITY_VERIFIED",
                checked_artifact_hashes=tuple(sorted(hashes)),
            )
        for root in case.roots:
            prefix = f"{root.logical_path}/"
            if not (
                prefix.startswith(f"cases/{case.case_id}/")
                or (case.case_id in {"Q09", "Q10"} and prefix.startswith("replay/"))
                or (case.case_id == "Q11" and prefix.startswith("live/"))
            ):
                raise HostedQualificationError("case root escaped its registered scope")
            inventory_bytes = read_relative(bundle, root.raw_inventory_path, max_bytes=16_777_216)
            inventory = HostedRawInventory.model_validate_json(inventory_bytes)
            if inventory.canonical_bytes() != inventory_bytes:
                raise HostedQualificationError("raw authority inventory is not canonical")
            verify_raw_inventory(bundle / root.logical_path, inventory)
            hashes.add(sha256_bytes(inventory_bytes))
            if not _file_map(inventory):
                raise HostedQualificationError("authority root has no files")
            hashes.update(
                verify_protocol_root(bundle / root.logical_path / "protocol", root.campaign_hash)
            )
            if sources is not None:
                sources.root_origin(root, inventory)
        if sources is not None and case.case_id == "Q07":
            from quantos.infrastructure.hosted_security_verification import (
                verify_deployment_security,
            )

            checked = set(verify_deployment_security(sources.deployment))
            exported_hashes = {item.sha256 for item in sources.files.values()}
            if not checked <= exported_hashes:
                raise HostedQualificationError("Q07 manager evidence export is incomplete")
            hashes.update(checked)
            return HostedQualificationGate(
                case_id=case.case_id,
                verdict="PASS",
                reason="ACTUAL_MANAGED_ISOLATION_VERIFIED",
                checked_artifact_hashes=tuple(sorted(hashes)),
            )
        if sources is not None and case.case_id in {
            "Q01",
            "Q02",
            "Q03",
            "Q04",
            "Q06",
            "Q08",
            "Q09",
            "Q10",
            "Q11",
            "Q12",
        }:
            from quantos.infrastructure.hosted_case_predicates import verify_q01, verify_q11
            from quantos.infrastructure.hosted_negative_origin import (
                verify_q02,
                verify_q03,
                verify_q04,
                verify_q08,
            )
            from quantos.infrastructure.hosted_q06_verification import verify_q06
            from quantos.infrastructure.hosted_regression_verification import verify_q12
            from quantos.infrastructure.hosted_replay_verification import verify_q09, verify_q10

            predicate = {
                "Q01": verify_q01,
                "Q02": verify_q02,
                "Q03": verify_q03,
                "Q04": verify_q04,
                "Q06": verify_q06,
                "Q08": verify_q08,
                "Q09": verify_q09,
                "Q10": verify_q10,
                "Q11": verify_q11,
                "Q12": verify_q12,
            }[case.case_id]
            hashes.update(predicate(bundle, case, sources))
            return HostedQualificationGate(
                case_id=case.case_id,
                verdict="PASS",
                reason="ORIGINAL_SCENARIO_AUTHORITY_VERIFIED",
                checked_artifact_hashes=tuple(sorted(hashes)),
            )
    except (
        ArtifactIntegrityError,
        OSError,
        ValueError,
        ValidationError,
        RuntimeError,
        KeyError,
        TypeError,
    ):
        return HostedQualificationGate(
            case_id=case.case_id,
            verdict="FAIL",
            reason="RAW_OR_TYPED_AUTHORITY_INVALID",
            checked_artifact_hashes=tuple(sorted(hashes)),
        )
    # Protocol integrity alone cannot prove a scenario's process/network/model claims.
    return HostedQualificationGate(
        case_id=case.case_id,
        verdict="NOT_EVALUATED",
        reason="ORIGINAL_MANAGER_SOURCE_UNAVAILABLE"
        if sources is None
        else "SCENARIO_PREDICATE_UNAVAILABLE",
        checked_artifact_hashes=tuple(sorted(hashes)),
    )


def verify_staging(
    bundle: Path,
    cases: tuple[HostedQualificationCase, ...],
    *,
    sources: HostedVerifiedSources | None = None,
) -> HostedQualificationVerification:
    if tuple(case.case_id for case in cases) != HOSTED_QUALIFICATION_CASES:
        raise HostedQualificationError("qualification case registry is incomplete")
    gates = tuple(verify_case(bundle, case, sources=sources) for case in cases)
    return HostedQualificationVerification(
        gates=gates,
        eligibility=(
            "ELIGIBLE_FOR_HM09_REVIEW"
            if all(gate.verdict == "PASS" for gate in gates)
            else "NOT_QUALIFIED"
        ),
    )


def verify_bundle(bundle: Path, *, manager_root: Path | None = None) -> HostedQualificationManifest:
    manifest_bytes = read_relative(bundle, "qualification-manifest.json", max_bytes=16_777_216)
    manifest = HostedQualificationManifest.model_validate_json(manifest_bytes)
    if (
        manifest.canonical_bytes() != manifest_bytes
        or bundle.name != f"sha256-{manifest.qualification_hash}"
    ):
        raise HostedQualificationError("qualification manifest bytes or path disagree")
    inventory = raw_inventory(bundle)
    actual = _file_map(inventory)
    expected = {item.logical_path: item for item in manifest.files}
    if set(actual) != set(expected) | {"qualification-manifest.json"}:
        raise HostedQualificationError("qualification exact-file set differs from manifest")
    for path, file in expected.items():
        if actual[path] != file:
            raise HostedQualificationError("qualification file hash or length differs")
    sources = None
    if manager_root is not None:
        from quantos.infrastructure.hosted_qualification_sources import verify_manager_export

        sources = verify_manager_export(bundle, manifest, manager_root)
        verify_loaded_project_installation(sources)
    frozen_root = sources.deployment.paths.provenance if sources is not None else ROOT
    frozen = (
        ("docs/hosted/hosted-contract-v1.md", HOSTED_CONTRACT_SHA256),
        ("docs/hosted/hosted-acceptance-v1.md", HOSTED_ACCEPTANCE_SHA256),
        ("docs/hosted/hm02-freeze-manifest.json", HOSTED_FREEZE_SHA256),
    )
    for path, digest in frozen:
        if sha256_bytes(read_relative(frozen_root, path)) != digest:
            raise HostedQualificationError("frozen hosted contract bytes changed")
    result = verify_staging(bundle, manifest.case_records, sources=sources)
    verify_runtime_binding(bundle, manifest, result)
    if sources is not None:
        verify_loaded_project_installation(sources)
    result_bytes = read_relative(bundle, "verifier-result.json", max_bytes=16_777_216)
    if (
        result.canonical_bytes() != result_bytes
        or sha256_bytes(result_bytes) != manifest.verifier_result_hash
    ):
        raise HostedQualificationError("independent verifier result differs from saved result")
    return manifest


def verify_runtime_binding(
    bundle: Path,
    manifest: HostedQualificationManifest,
    result: HostedQualificationVerification,
) -> None:
    """Bind the outer identity to canonical runtime bytes and verified native reports."""
    encoded = read_relative(bundle, "deployment/runtime-fingerprint.json")
    fingerprint = RuntimeFingerprint.model_validate_json(encoded)
    if (
        fingerprint.canonical_bytes() != encoded
        or fingerprint.content_hash != manifest.runtime_fingerprint_hash
    ):
        raise HostedQualificationError("qualification runtime fingerprint differs")
    if next(gate for gate in result.gates if gate.case_id == "Q11").verdict != "PASS":
        return
    reports: list[ValidationReport] = []
    for root in next(case for case in manifest.case_records if case.case_id == "Q11").roots:
        inventory = HostedRawInventory.model_validate_json(
            read_relative(bundle, root.raw_inventory_path)
        )
        for item in inventory.files:
            if not item.logical_path.endswith("/manifest.json"):
                continue
            data = read_relative(bundle / root.logical_path, item.logical_path)
            payload = strict_json_object(data, max_bytes=MAX_TYPED_BYTES)
            if payload.get("schema_version") != "validation-report/v2":
                continue
            reports.append(ValidationReport.model_validate_json(data))
    if not reports or any(
        report.runtime_fingerprint_hash != fingerprint.content_hash for report in reports
    ):
        raise HostedQualificationError(
            "qualification runtime differs from verified native validation"
        )


def verify_loaded_project_installation(sources: HostedVerifiedSources) -> None:
    """Formal verification uses source-only imports in the fixed native installation.

    Checking only disk .py bytes cannot attest executed code: CPython may load an
    older timestamp-valid .pyc. The native entrypoint disables writing and routes
    all cache reads to an initially empty private tmpfs prefix before initialization.
    Formal verification rejects any existing cache for a loaded project module.
    """
    installed = {item.relative_path: item.bytes_hash for item in sources.deployment.install.files}
    install_root = Path("/install")
    native = "python-seeded"
    prefix = "/tmp/quantos-disabled-bytecode-cache"
    if (
        sys.executable != str(install_root / native)
        or sha256_bytes(read_relative(install_root, native)) != installed.get(native)
        or Path(prefix).exists()
        or Path(prefix).is_symlink()
        or sys.pycache_prefix != prefix
        or sys.dont_write_bytecode is not True
        or sys.flags.optimize != 0
        or sys.flags.isolated != 1
        or sys.flags.ignore_environment != 1
        or sys.flags.no_user_site != 1
        or sys.flags.safe_path is not True
        or sys.flags.hash_randomization != 0
        or any(
            path.startswith("python/lib/python3.11/site-packages/quantos/")
            and path.endswith(".pyc")
            for path in installed
        )
    ):
        raise HostedQualificationError(
            "formal verifier requires the frozen source-only interpreter"
        )
    for name, module in tuple(sys.modules.items()):
        if name == "__main__":
            name = getattr(getattr(module, "__spec__", None), "name", name)
        if name != "quantos" and not name.startswith("quantos."):
            continue
        filename = getattr(module, "__file__", None)
        if not isinstance(filename, str) or not filename.endswith(".py"):
            raise HostedQualificationError("formal verifier loaded an unbound project module")
        source = Path(filename)
        relative = "python/lib/python3.11/site-packages/" + name.replace(".", "/")
        relative += "/__init__.py" if source.name == "__init__.py" else ".py"
        loader = getattr(module, "__loader__", None)
        spec = getattr(module, "__spec__", None)
        cached = getattr(module, "__cached__", None)
        if (
            source != install_root / relative
            or type(loader) is not SourceFileLoader
            or loader.path != str(source)
            or getattr(spec, "origin", None) != str(source)
            or not isinstance(cached, str)
            or cached != cache_from_source(str(source))
            or not cached.startswith(prefix + "/")
            or Path(cached).exists()
            or Path(cached).is_symlink()
            or sha256_bytes(read_relative(install_root, relative)) != installed.get(relative)
        ):
            raise HostedQualificationError("formal verifier differs from the frozen source imports")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--manager-root", type=Path, help="original trusted deployment root, supplied independently"
    )
    args = parser.parse_args()
    manifest = verify_bundle(args.bundle, manager_root=args.manager_root)
    from quantos.infrastructure.hosted_qualification_sources import verify_manager_export

    sources = (
        verify_manager_export(args.bundle, manifest, args.manager_root)
        if args.manager_root
        else None
    )
    result = verify_staging(args.bundle, manifest.case_records, sources=sources)
    print(
        canonical_json_bytes(
            {"qualification_hash": manifest.qualification_hash, "eligibility": result.eligibility}
        ).decode("utf-8")
    )


if __name__ == "__main__":
    main()
