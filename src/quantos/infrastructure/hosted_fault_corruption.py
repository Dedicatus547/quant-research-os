"""Finite disk corruption fixtures and exact byte plans; no research input knobs."""

from __future__ import annotations

import os
import stat
from datetime import timedelta
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, opened_directory
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedCheckpoint, HostedJournalEntry
from quantos.infrastructure.hosted_fault_cases import CORRUPTION_FAULT_WINDOWS
from quantos.infrastructure.hosted_store import HostedStoreSnapshot
from quantos.infrastructure.hosted_verification import read_relative


def corruption_plan(name: str, state: HostedStoreSnapshot) -> tuple[tuple[str, bytes], ...]:
    """Derive every changed byte from a verified, complete native starting state."""
    if name not in CORRUPTION_FAULT_WINDOWS:
        raise ValueError("unknown fixed corruption fixture")
    if (
        len(state.requests) != 1
        or any(receipt.outcome != "EXHAUSTED" for receipt in state.receipts)
        or state.terminals
        or state.budget.used_unique_submissions != 0
    ):
        raise ArtifactIntegrityError("corruption fixture requires one unaccepted native request")
    request = state.requests[0]
    prefix = f"protocol/campaigns/{state.spec.campaign_hash}"
    kind = CORRUPTION_FAULT_WINDOWS[name].point
    next_sequence = len(state.journal) + 1

    def intent(sequence: int, previous: str, ordinal: int) -> HostedJournalEntry:
        return HostedJournalEntry(
            campaign_hash=state.spec.campaign_hash,
            sequence=sequence,
            previous_hash=previous,
            operation_id=sha256_bytes(f"{name}:{ordinal}".encode()),
            operation_kind="REGISTER",
            phase="INTENT",
            recorded_at=state.spec.started_at,
            publications=state.journal[0].publications,
        )

    def journal_path(sequence: int, data: bytes) -> str:
        return f"{prefix}/journal/{sequence:08d}-{sha256_bytes(data)}.json"

    if kind == "journal_fragment":
        data = b"{"
        return ((journal_path(next_sequence, data), data),)
    if kind == "wrong_sequence":
        entry = intent(next_sequence + 1, state.journal_head_hash, 1)
        data = entry.canonical_bytes()
        return ((journal_path(next_sequence, data), data),)
    if kind == "double_pending":
        first = intent(next_sequence, state.journal_head_hash, 1)
        second = intent(next_sequence + 1, first.content_hash, 2)
        return tuple(
            (journal_path(entry.sequence, entry.canonical_bytes()), entry.canonical_bytes())
            for entry in (first, second)
        )
    if kind == "orphan_artifact":
        orphan = HostedCheckpoint(
            request_hash=request.content_hash,
            campaign_hash=state.spec.campaign_hash,
            transport_ordinal=request.transport_ordinal,
            recorded_at=state.spec.started_at + timedelta(seconds=1),
        )
        return ((f"{prefix}/objects/{orphan.content_hash}.json", orphan.canonical_bytes()),)
    return ((f"{prefix}/objects/{request.content_hash}.json", request.canonical_bytes() + b"\n"),)


def apply_corruption_fixture(name: str, authority: Path, state: HostedStoreSnapshot) -> None:
    """Management-only deliberate damage, with the original before snapshot retained."""
    for logical, data in corruption_plan(name, state):
        if name != "corruption-changed_artifact":
            atomic_write_bytes(authority / logical, data)
            continue
        # This one negative requires altering an existing original artifact. Keep
        # no-follow, regular-file and single-link checks even in the fixture.
        if read_relative(authority, logical) != state.requests[0].canonical_bytes():
            raise ArtifactIntegrityError("corruption source request bytes differ")
        with opened_directory((authority / logical).parent) as parent:
            fd = os.open(Path(logical).name, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ArtifactIntegrityError("unsafe corruption fixture file")
                os.ftruncate(fd, 0)
                offset = 0
                while offset < len(data):
                    written = os.write(fd, data[offset:])
                    if written <= 0:
                        raise ArtifactIntegrityError("corruption fixture short write")
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)


def expected_corruption_error(name: str) -> str:
    if name not in CORRUPTION_FAULT_WINDOWS:
        raise ValueError("unknown fixed corruption fixture")
    return "ValueError" if name == "corruption-journal_fragment" else "ArtifactIntegrityError"
