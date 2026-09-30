"""Read-only physical publication facts; never a canonical-authority reader.

Only a known native publication's temporary/target pair can have two links.
Canonical store, inventory and path readers retain their single-link rejection.
These facts cannot award qualification or turn copied bytes into authority.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Literal

from pydantic import Field, NonNegativeInt, field_validator

from quantos.application.hosted_protocol import (
    HostedProtocolService,
    hosted_protocol_operation_id,
)
from quantos.artifacts.store import opened_directory
from quantos.contracts.base import CanonicalContract, sha256_bytes
from quantos.contracts.hosted import (
    HostedBudgetJournalFact,
    HostedCampaignSpec,
    HostedJournalEntry,
    HostedPublication,
)
from quantos.contracts.refs import SHA256_PATTERN
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    validate_logical_path,
)

ATOMIC_WINDOWS = ("file_fsynced", "file_linked", "file_published", "directory_fsynced")
FORENSIC_ENTRY_CAP = 10_000
FORENSIC_FILE_CAP = 16_777_216
FORENSIC_TOTAL_CAP = 67_108_864
_TEMPORARY = re.compile(r"\.publish-[0-9a-f]{32}\Z")


class HostedForensicFile(CanonicalContract):
    schema_version: Literal["hosted-atomic-forensic-file/v1"] = "hosted-atomic-forensic-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt
    device: int
    inode: int
    link_count: int
    mode: int
    uid: int
    gid: int
    mtime_ns: int
    ctime_ns: int

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class HostedForensicDirectory(CanonicalContract):
    schema_version: Literal["hosted-atomic-forensic-directory/v1"] = (
        "hosted-atomic-forensic-directory/v1"
    )
    logical_path: str
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    mtime_ns: int
    ctime_ns: int


class HostedAtomicForensicInventory(CanonicalContract):
    schema_version: Literal["hosted-atomic-forensic-inventory/v1"] = (
        "hosted-atomic-forensic-inventory/v1"
    )
    evidence_kind: Literal["FORENSIC_ONLY_NOT_CANONICAL_AUTHORITY"] = (
        "FORENSIC_ONLY_NOT_CANONICAL_AUTHORITY"
    )
    qualification_eligibility: Literal["NOT_QUALIFIED"] = "NOT_QUALIFIED"
    target_path: str
    expected_publication_hash: str
    window: str
    files: tuple[HostedForensicFile, ...]
    directories: tuple[HostedForensicDirectory, ...]


def native_registration_publication(spec: HostedCampaignSpec, domain: str) -> tuple[str, bytes]:
    """Derive the first spec, REGISTER INTENT or object without touching a store."""
    if domain == "spec":
        return f"protocol/specs/{spec.content_hash}.json", spec.canonical_bytes()
    campaign = spec.campaign_hash
    if domain == "object":
        return (
            f"protocol/campaigns/{campaign}/objects/{spec.content_hash}.json",
            spec.canonical_bytes(),
        )
    if domain != "journal":
        raise ValueError("unknown fixed registration publication domain")
    op = hosted_protocol_operation_id(campaign, "REGISTER", spec.content_hash)
    budget = HostedBudgetJournalFact(
        campaign_hash=campaign,
        hosted_spec_hash=spec.content_hash,
        operation_id=op,
        previous_hash=None,
        used_requests=0,
        used_unique_submissions=0,
        request_submissions=(),
        recorded_at=spec.started_at,
    )
    exhausted = HostedProtocolService.project_exhaustion_receipt(
        spec, budget, None, spec.started_at
    )
    entry = HostedJournalEntry(
        campaign_hash=campaign,
        sequence=1,
        previous_hash=None,
        operation_id=op,
        operation_kind="REGISTER",
        phase="INTENT",
        recorded_at=spec.started_at,
        publications=tuple(
            HostedPublication(
                artifact_hash=item.content_hash, canonical_json=item.canonical_bytes().decode()
            )
            for item in (spec, budget, exhausted)
        ),
    )
    return (
        f"protocol/campaigns/{campaign}/journal/00000001-{entry.content_hash}.json",
        entry.canonical_bytes(),
    )


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _bounded_names(directory_fd: int, limit: int, message: str) -> list[str]:
    names: list[str] = []
    with os.scandir(directory_fd) as iterator:
        for item in iterator:
            if len(names) >= limit:
                raise HostedQualificationError(message)
            names.append(item.name)
    return sorted(names)


def atomic_forensic_inventory(
    root: Path, *, target_path: str, expected_bytes: bytes, window: str
) -> HostedAtomicForensicInventory:
    """Bind exact bytes and physical aliases in two stable descriptor walks.

    The caller supplies a fixed native publication, never a host-selected path.
    No parser, store constructor, recovery, publication or cleanup is invoked.
    """
    validate_logical_path(target_path)
    if window not in ATOMIC_WINDOWS or len(expected_bytes) > FORENSIC_FILE_CAP:
        raise ValueError("unknown or oversized fixed atomic publication")
    expected_hash = sha256_bytes(expected_bytes)
    target_parent = str(Path(target_path).parent)

    def capture() -> HostedAtomicForensicInventory:
        files: list[HostedForensicFile] = []
        directories: list[HostedForensicDirectory] = []
        entries = 0
        total = 0

        def walk(directory_fd: int, prefix: str) -> None:
            nonlocal entries, total
            before = os.fstat(directory_fd)
            directories.append(
                HostedForensicDirectory(
                    logical_path=prefix,
                    device=before.st_dev,
                    inode=before.st_ino,
                    mode=before.st_mode,
                    uid=before.st_uid,
                    gid=before.st_gid,
                    mtime_ns=before.st_mtime_ns,
                    ctime_ns=before.st_ctime_ns,
                )
            )
            names = _bounded_names(
                directory_fd, FORENSIC_ENTRY_CAP - entries, "atomic forensic entry cap exceeded"
            )
            # Reserve all immediate entries before descending into any child.
            # Already enumerated sibling names consume the same whole-tree cap.
            entries += len(names)
            for name in names:
                logical = f"{prefix}/{name}" if prefix else name
                validate_logical_path(logical)
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    child = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
                    )
                    try:
                        if _identity(metadata) != _identity(os.fstat(child)):
                            raise HostedQualificationError("atomic forensic directory changed")
                        walk(child, logical)
                    finally:
                        os.close(child)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise HostedQualificationError("atomic forensic tree contains unsafe object")
                temporary = _TEMPORARY.fullmatch(name) is not None
                publication = logical == target_path or (prefix == target_parent and temporary)
                if name.startswith(".publish-") and (not temporary or not publication):
                    raise HostedQualificationError("atomic forensic has unrelated temporary file")
                allowed_links = 2 if window == "file_linked" and publication else 1
                if metadata.st_nlink != allowed_links or metadata.st_size > FORENSIC_FILE_CAP:
                    raise HostedQualificationError("atomic forensic has unsafe alias or size")
                if total + metadata.st_size > FORENSIC_TOTAL_CAP:
                    raise HostedQualificationError("atomic forensic aggregate cap exceeded")
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
                )
                try:
                    opened = os.fstat(descriptor)
                    if _identity(opened) != _identity(metadata):
                        raise HostedQualificationError("atomic forensic file changed before read")
                    digest = hashlib.sha256()
                    length = 0
                    while chunk := os.read(descriptor, min(1_048_576, opened.st_size - length + 1)):
                        length += len(chunk)
                        if length > opened.st_size:
                            raise HostedQualificationError("atomic forensic file grew during read")
                        digest.update(chunk)
                    if (
                        _identity(opened) != _identity(os.fstat(descriptor))
                        or length != opened.st_size
                    ):
                        raise HostedQualificationError("atomic forensic file changed during read")
                finally:
                    os.close(descriptor)
                total += length
                if total > FORENSIC_TOTAL_CAP:
                    raise HostedQualificationError("atomic forensic aggregate cap exceeded")
                if publication and (
                    length != len(expected_bytes) or digest.hexdigest() != expected_hash
                ):
                    raise HostedQualificationError("atomic forensic publication bytes differ")
                files.append(
                    HostedForensicFile(
                        logical_path=logical,
                        sha256=digest.hexdigest(),
                        size_bytes=length,
                        device=opened.st_dev,
                        inode=opened.st_ino,
                        link_count=opened.st_nlink,
                        mode=opened.st_mode,
                        uid=opened.st_uid,
                        gid=opened.st_gid,
                        mtime_ns=opened.st_mtime_ns,
                        ctime_ns=opened.st_ctime_ns,
                    )
                )
            after_names = _bounded_names(
                directory_fd, len(names), "atomic forensic directory changed during walk"
            )
            if names != after_names or _identity(before) != _identity(os.fstat(directory_fd)):
                raise HostedQualificationError("atomic forensic directory changed during walk")

        with opened_directory(root) as descriptor:
            walk(descriptor, "")
        indexed = {file.logical_path: file for file in files}
        target = indexed.get(target_path)
        temporary_files = tuple(
            file
            for file in files
            if str(Path(file.logical_path).parent) == target_parent
            and _TEMPORARY.fullmatch(Path(file.logical_path).name)
        )
        if window in ("file_fsynced", "file_linked"):
            if len(temporary_files) != 1 or (target is not None) != (window == "file_linked"):
                raise HostedQualificationError("atomic forensic temporary/target shape differs")
            if target is not None and (target.device, target.inode) != (
                temporary_files[0].device,
                temporary_files[0].inode,
            ):
                raise HostedQualificationError(
                    "atomic forensic target does not share temporary inode"
                )
        elif temporary_files or target is None:
            raise HostedQualificationError("atomic forensic published shape differs")
        return HostedAtomicForensicInventory(
            target_path=target_path,
            expected_publication_hash=expected_hash,
            window=window,
            files=tuple(sorted(files, key=lambda item: item.logical_path)),
            directories=tuple(sorted(directories, key=lambda item: item.logical_path)),
        )

    first = capture()
    if capture() != first:
        raise HostedQualificationError("atomic forensic tree changed between captures")
    return first
