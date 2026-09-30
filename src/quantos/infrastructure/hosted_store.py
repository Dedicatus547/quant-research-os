"""POSIX, append-only hosted authority with replayable publication intents."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Literal, TypeVar

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import CanonicalContract, sha256_bytes
from quantos.contracts.hosted import (
    REQUEST_BYTE_CAP,
    HostedAgentExchange,
    HostedAgentRequest,
    HostedBudgetJournalFact,
    HostedCampaignSpec,
    HostedCheckpoint,
    HostedJournalEntry,
    HostedPublication,
    HostedRequestTerminalReceipt,
    HostedSubmissionReceipt,
    parse_hosted_contract,
    strict_json_object,
)

ContractT = TypeVar("ContractT", bound=CanonicalContract)
AUTHORITY_BYTE_CAP = 16 * REQUEST_BYTE_CAP
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_JOURNAL = re.compile(r"([0-9]{8})-([0-9a-f]{64})\.json\Z")


def _hash(value: str) -> str:
    if _HASH.fullmatch(value) is None:
        raise ValueError("explicit SHA-256 identity required")
    return value


@contextmanager
def _child(parent: int, name: str, *, create: bool = False) -> Generator[int, None, None]:
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ArtifactIntegrityError("unsafe authority directory segment")
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except OSError as error:
        raise ArtifactIntegrityError("unsafe or missing authority directory") from error
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _names(directory_fd: int) -> tuple[str, ...]:
    with os.scandir(directory_fd) as entries:
        names = tuple(sorted(x.name for x in entries))
    for name in names:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ArtifactIntegrityError("authority contains an unsafe file or hard-link alias")
    return names


@dataclass(frozen=True)
class HostedStoreSnapshot:
    spec: HostedCampaignSpec
    journal: tuple[HostedJournalEntry, ...]
    artifacts: dict[str, bytes]
    budget: HostedBudgetJournalFact
    requests: tuple[HostedAgentRequest, ...]
    receipts: tuple[HostedSubmissionReceipt, ...]
    terminals: tuple[HostedRequestTerminalReceipt, ...]

    @property
    def journal_head_hash(self) -> str:
        return self.journal[-1].content_hash

    def artifact(self, digest: str, cls: type[ContractT]) -> ContractT:
        try:
            return parse_hosted_contract(
                self.artifacts[_hash(digest)], cls, max_bytes=AUTHORITY_BYTE_CAP
            )
        except (KeyError, ValueError) as error:
            raise ArtifactIntegrityError("hosted artifact is missing or invalid") from error

    def request(self, digest: str) -> HostedAgentRequest:
        return self.artifact(digest, HostedAgentRequest)

    def accepted_receipt(self, request_hash: str) -> HostedSubmissionReceipt | None:
        accepted = tuple(
            x for x in self.receipts if x.request_hash == request_hash and x.outcome == "ACCEPTED"
        )
        if len(accepted) > 1:
            raise ArtifactIntegrityError("multiple hosted acceptances")
        return accepted[0] if accepted else None

    def terminal(self, request_hash: str) -> HostedRequestTerminalReceipt | None:
        terminals = tuple(
            x
            for x in self.terminals
            if x.request_hash == request_hash and x.outcome != "CANCEL_REJECTED"
        )
        if len(terminals) > 1:
            raise ArtifactIntegrityError("multiple hosted terminal facts")
        return terminals[0] if terminals else None

    @property
    def active_request(self) -> HostedAgentRequest | None:
        active = tuple(x for x in self.requests if self.terminal(x.content_hash) is None)
        if len(active) > 1:
            raise ArtifactIntegrityError("campaign has multiple active requests")
        return active[0] if active else None


class HostedProtocolStore:
    """Service-owned fixed root; callers never choose artifact paths.

    Journal intents are authority. Recovery completes their exact publications before
    accepting a mutation. Read-only snapshots never create a completion or checkpoint.
    """

    def __init__(
        self,
        root: Path,
        *,
        fault_hook: Callable[[str], None] | None = None,
        verify_journal_entry: Callable[[object], None] | None = None,
    ) -> None:
        self._root = root.absolute()
        self._fault_hook = fault_hook
        self._verify_journal_entry = verify_journal_entry
        with opened_directory(self._root, create=True) as root_fd:
            for name in ("specs", "campaigns"):
                with _child(root_fd, name, create=True):
                    pass

    def _fault(self, point: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)

    @staticmethod
    def _require_spec_names(directory_fd: int) -> None:
        # A process can exit after fsync but before link/unlink. Such temporary
        # files are evidence of an unfinished publication, never silent cleanup
        # candidates or a reason to create a second authoritative spec.
        if any(
            not name.endswith(".json") or _HASH.fullmatch(name[:-5]) is None
            for name in _names(directory_fd)
        ):
            raise ArtifactIntegrityError("unexpected hosted spec artifact")

    def register_spec(self, spec: HostedCampaignSpec) -> str:
        with opened_directory(self._root) as root_fd, _child(root_fd, "specs") as specs_fd:
            flock(specs_fd, LOCK_EX)
            try:
                self._require_spec_names(specs_fd)
                atomic_write_bytes_at(
                    specs_fd,
                    f"{spec.content_hash}.json",
                    spec.canonical_bytes(),
                    fault_hook=lambda point: self._fault("spec_" + point),
                )
            finally:
                flock(specs_fd, LOCK_UN)
        return spec.content_hash

    def spec(self, spec_hash: str) -> HostedCampaignSpec:
        with opened_directory(self._root) as root_fd, _child(root_fd, "specs") as specs_fd:
            flock(specs_fd, LOCK_EX)
            try:
                self._require_spec_names(specs_fd)
                data = read_regular_bytes_at(
                    specs_fd, f"{_hash(spec_hash)}.json", max_bytes=REQUEST_BYTE_CAP
                )
            finally:
                flock(specs_fd, LOCK_UN)
        value = parse_hosted_contract(data, HostedCampaignSpec, max_bytes=REQUEST_BYTE_CAP)
        if value.content_hash != spec_hash:
            raise ArtifactIntegrityError("hosted spec hash mismatch")
        return value

    def verify_spec_registration(self, expected: HostedCampaignSpec) -> None:
        """Read-only bootstrap preflight before any business materialization.

        Empty registration is permitted only for a genuinely fresh spec store.
        Unfinished temporary publications and any unrelated registration reject
        before the loader can touch the retained business tree.
        """
        with opened_directory(self._root) as root_fd, _child(root_fd, "specs") as specs_fd:
            flock(specs_fd, LOCK_EX)
            try:
                self._require_spec_names(specs_fd)
                names = _names(specs_fd)
                if not names:
                    return
                name = f"{expected.content_hash}.json"
                if names != (name,):
                    raise ArtifactIntegrityError("unexpected hosted spec registration")
                data = read_regular_bytes_at(specs_fd, name, max_bytes=REQUEST_BYTE_CAP)
                if data != expected.canonical_bytes():
                    raise ArtifactIntegrityError(
                        "hosted registered spec differs from frozen inputs"
                    )
            finally:
                flock(specs_fd, LOCK_UN)

    @contextmanager
    def campaign_lock(
        self, campaign_hash: str, *, create: bool = False
    ) -> Generator[int, None, None]:
        """Lock a stable directory inode. No deletable/recreated lock file exists."""
        identity = _hash(campaign_hash)
        with (
            opened_directory(self._root) as root_fd,
            _child(root_fd, "campaigns") as parent_fd,
            _child(parent_fd, identity, create=create) as campaign_fd,
        ):
            flock(campaign_fd, LOCK_EX)
            try:
                before = os.fstat(campaign_fd)
                current = os.stat(identity, dir_fd=parent_fd, follow_symlinks=False)
                if (before.st_ino, before.st_dev) != (current.st_ino, current.st_dev):
                    raise ArtifactIntegrityError("campaign lock directory was replaced")
                for name in ("objects", "journal"):
                    with _child(campaign_fd, name, create=create):
                        pass
                yield campaign_fd
                current = os.stat(identity, dir_fd=parent_fd, follow_symlinks=False)
                if (before.st_ino, before.st_dev) != (current.st_ino, current.st_dev):
                    raise ArtifactIntegrityError("campaign lock directory was replaced")
            finally:
                flock(campaign_fd, LOCK_UN)

    def _journal(self, campaign_fd: int) -> tuple[HostedJournalEntry, ...]:
        with _child(campaign_fd, "journal") as journal_fd:
            entries: list[HostedJournalEntry] = []
            for sequence, name in enumerate(_names(journal_fd), start=1):
                match = _JOURNAL.fullmatch(name)
                if match is None or int(match[1]) != sequence:
                    raise ArtifactIntegrityError("hosted journal sequence is invalid")
                data = read_regular_bytes_at(journal_fd, name, max_bytes=AUTHORITY_BYTE_CAP)
                entry = parse_hosted_contract(
                    data, HostedJournalEntry, max_bytes=AUTHORITY_BYTE_CAP
                )
                if entry.sequence != sequence or entry.content_hash != match[2]:
                    raise ArtifactIntegrityError("hosted journal hash/sequence mismatch")
                previous = entries[-1].content_hash if entries else None
                if entry.previous_hash != previous:
                    raise ArtifactIntegrityError("hosted journal previous hash mismatch")
                if entries:
                    if entry.campaign_hash != entries[0].campaign_hash:
                        raise ArtifactIntegrityError("hosted journal campaign mismatch")
                    prior = entries[-1]
                    if prior.phase == entry.phase or (
                        entry.phase == "COMPLETE"
                        and (
                            entry.operation_id != prior.operation_id
                            or entry.operation_kind != prior.operation_kind
                            or entry.recorded_at != prior.recorded_at
                            or entry.artifact_hashes
                            != tuple(x.artifact_hash for x in prior.publications)
                        )
                    ):
                        raise ArtifactIntegrityError("hosted journal intent/completion mismatch")
                elif entry.phase != "INTENT" or entry.operation_kind != "REGISTER":
                    raise ArtifactIntegrityError("hosted journal registration missing")
                if entry.phase == "INTENT" and any(
                    x.operation_id == entry.operation_id for x in entries if x.phase == "INTENT"
                ):
                    raise ArtifactIntegrityError("hosted operation identity duplicated")
                entries.append(entry)
        return tuple(entries)

    def _append(self, campaign_fd: int, entry: HostedJournalEntry) -> None:
        if self._verify_journal_entry is not None:
            self._verify_journal_entry(entry)
        with _child(campaign_fd, "journal") as journal_fd:
            atomic_write_bytes_at(
                journal_fd,
                f"{entry.sequence:08d}-{entry.content_hash}.json",
                entry.canonical_bytes(),
                fault_hook=lambda point: self._fault("journal_" + point),
            )

    def _publish(self, campaign_fd: int, publication: HostedPublication) -> None:
        with _child(campaign_fd, "objects") as objects_fd:
            atomic_write_bytes_at(
                objects_fd,
                f"{publication.artifact_hash}.json",
                publication.canonical_json.encode("utf-8"),
                fault_hook=lambda point: self._fault("object_" + point),
            )

    def _finish(self, campaign_fd: int, intent: HostedJournalEntry) -> None:
        for publication in intent.publications:
            self._publish(campaign_fd, publication)
            self._fault("artifact_published")
        self._append(
            campaign_fd,
            HostedJournalEntry(
                campaign_hash=intent.campaign_hash,
                sequence=intent.sequence + 1,
                previous_hash=intent.content_hash,
                operation_id=intent.operation_id,
                phase="COMPLETE",
                operation_kind=intent.operation_kind,
                recorded_at=intent.recorded_at,
                artifact_hashes=tuple(x.artifact_hash for x in intent.publications),
            ),
        )
        self._fault("completion_published")

    def recover_locked(self, campaign_fd: int) -> None:
        journal = self._journal(campaign_fd)
        if not journal or journal[-1].phase == "INTENT":
            # Reconcile every existing object before completing an INTENT. An
            # orphan temporary file or changed publication must not be detected
            # only after recovery has already written objects and a completion.
            expected = {
                publication.artifact_hash: publication.canonical_json.encode("utf-8")
                for entry in journal
                for publication in entry.publications
            }
            required = {
                digest
                for entry in journal
                if entry.phase == "COMPLETE"
                for digest in entry.artifact_hashes
            }
            existing: set[str] = set()
            with _child(campaign_fd, "objects") as objects_fd:
                for name in _names(objects_fd):
                    if not name.endswith(".json") or _HASH.fullmatch(name[:-5]) is None:
                        raise ArtifactIntegrityError("unexpected hosted authority artifact")
                    data = read_regular_bytes_at(objects_fd, name, max_bytes=AUTHORITY_BYTE_CAP)
                    digest = name[:-5]
                    if sha256_bytes(data) != digest or expected.get(digest) != data:
                        raise ArtifactIntegrityError("hosted artifact hash or publication mismatch")
                    existing.add(digest)
            if not required.issubset(existing):
                raise ArtifactIntegrityError("hosted completed publication is missing")
        if journal and journal[-1].phase == "INTENT":
            if self._verify_journal_entry is not None:
                self._verify_journal_entry(journal[-1])
            self._finish(campaign_fd, journal[-1])
        if journal:
            self.snapshot_locked(campaign_fd)

    def has_journal_locked(self, campaign_fd: int) -> bool:
        return bool(self._journal(campaign_fd))

    def commit_locked(
        self,
        campaign_fd: int,
        *,
        campaign_hash: str,
        operation_id: str,
        operation_kind: Literal["REGISTER", "ISSUE", "SUBMIT", "TERMINATE", "BUSINESS"],
        recorded_at: datetime,
        artifacts: tuple[CanonicalContract, ...],
    ) -> None:
        self.recover_locked(campaign_fd)
        journal = self._journal(campaign_fd)
        if any(x.operation_id == operation_id for x in journal):
            raise ArtifactIntegrityError("hosted operation identity already committed")
        intent = HostedJournalEntry(
            campaign_hash=campaign_hash,
            sequence=len(journal) + 1,
            previous_hash=journal[-1].content_hash if journal else None,
            operation_id=operation_id,
            operation_kind=operation_kind,
            phase="INTENT",
            recorded_at=recorded_at,
            publications=tuple(
                HostedPublication(
                    artifact_hash=x.content_hash, canonical_json=x.canonical_bytes().decode("utf-8")
                )
                for x in artifacts
            ),
        )
        self._append(campaign_fd, intent)
        self._fault("intent_published")
        self._finish(campaign_fd, intent)

    def snapshot_locked(self, campaign_fd: int) -> HostedStoreSnapshot:
        journal = self._journal(campaign_fd)
        if not journal or journal[-1].phase != "COMPLETE":
            raise ArtifactIntegrityError("hosted protocol recovery required")
        expected = {
            x.artifact_hash: x.canonical_json.encode("utf-8")
            for entry in journal
            for x in entry.publications
        }
        artifacts: dict[str, bytes] = {}
        with _child(campaign_fd, "objects") as objects_fd:
            for name in _names(objects_fd):
                if not name.endswith(".json") or _HASH.fullmatch(name[:-5]) is None:
                    raise ArtifactIntegrityError("unexpected hosted authority artifact")
                digest = name[:-5]
                data = read_regular_bytes_at(objects_fd, name, max_bytes=AUTHORITY_BYTE_CAP)
                if sha256_bytes(data) != digest or expected.get(digest) != data:
                    raise ArtifactIntegrityError("hosted artifact hash or publication mismatch")
                artifacts[digest] = data
        if set(artifacts) != set(expected):
            raise ArtifactIntegrityError("hosted published artifact is missing")
        specs: list[HostedCampaignSpec] = []
        budgets: list[HostedBudgetJournalFact] = []
        requests: list[HostedAgentRequest] = []
        receipts: list[HostedSubmissionReceipt] = []
        terminals: list[HostedRequestTerminalReceipt] = []
        # Intent order, not directory enumeration, defines fact order.
        seen: set[str] = set()
        for entry in journal:
            for publication in entry.publications:
                if publication.artifact_hash in seen:
                    continue
                seen.add(publication.artifact_hash)
                data = artifacts[publication.artifact_hash]
                schema = strict_json_object(data, max_bytes=AUTHORITY_BYTE_CAP).get(
                    "schema_version"
                )
                if schema == "hosted-campaign-spec/v1":
                    specs.append(
                        parse_hosted_contract(
                            data, HostedCampaignSpec, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-budget-journal-fact/v1":
                    budgets.append(
                        parse_hosted_contract(
                            data, HostedBudgetJournalFact, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-agent-request/v1":
                    requests.append(
                        parse_hosted_contract(
                            data, HostedAgentRequest, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-submission-receipt/v1":
                    receipts.append(
                        parse_hosted_contract(
                            data, HostedSubmissionReceipt, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
                elif schema == "hosted-request-terminal-receipt/v1":
                    terminals.append(
                        parse_hosted_contract(
                            data, HostedRequestTerminalReceipt, max_bytes=AUTHORITY_BYTE_CAP
                        )
                    )
        if len(specs) != 1 or not budgets:
            raise ArtifactIntegrityError("hosted registration facts missing or conflicting")
        spec = specs[0]
        if spec.campaign_hash != journal[0].campaign_hash:
            raise ArtifactIntegrityError("hosted spec/journal campaign mismatch")
        previous: HostedBudgetJournalFact | None = None
        for budget in budgets:
            if (
                budget.campaign_hash != spec.campaign_hash
                or budget.hosted_spec_hash != spec.content_hash
                or budget.previous_hash != (previous.content_hash if previous else None)
                or budget.used_requests > spec.hosted_budget.max_requests
                or budget.used_unique_submissions > spec.hosted_budget.max_unique_submissions
                or any(
                    x.used_submissions > spec.hosted_budget.max_submissions_per_request
                    for x in budget.request_submissions
                )
            ):
                raise ArtifactIntegrityError("hosted budget journal binding/cap mismatch")
            if previous is not None:
                delta = (
                    budget.used_requests - previous.used_requests,
                    budget.used_unique_submissions - previous.used_unique_submissions,
                )
                if delta not in ((1, 0), (0, 1)):
                    raise ArtifactIntegrityError("hosted budget reservation transition invalid")
            elif budget.used_requests or budget.used_unique_submissions:
                raise ArtifactIntegrityError("hosted initial budget is not empty")
            previous = budget
        if tuple(x.transport_ordinal for x in requests) != tuple(range(1, len(requests) + 1)):
            raise ArtifactIntegrityError("hosted request ordinals duplicated or discontinuous")
        if len(requests) != budgets[-1].used_requests:
            raise ArtifactIntegrityError("hosted request reservations disagree")
        snapshot = HostedStoreSnapshot(
            spec,
            journal,
            artifacts,
            budgets[-1],
            tuple(requests),
            tuple(receipts),
            tuple(terminals),
        )
        for request in requests:
            if (
                request.campaign_hash != spec.campaign_hash
                or request.hosted_spec_hash != spec.content_hash
                or request.candidate_manifest_hash != spec.candidate_manifest_hash
            ):
                raise ArtifactIntegrityError("hosted request spec binding mismatch")
            reservation = snapshot.artifact(
                request.budget_reservation_hash, HostedBudgetJournalFact
            )
            if reservation.used_requests != request.transport_ordinal:
                raise ArtifactIntegrityError("hosted request reservation ordinal mismatch")
            checkpoint = HostedCheckpoint(
                request_hash=request.content_hash,
                campaign_hash=spec.campaign_hash,
                transport_ordinal=request.transport_ordinal,
                recorded_at=request.issued_at,
            )
            snapshot.artifact(checkpoint.content_hash, HostedCheckpoint)
            accepted = snapshot.accepted_receipt(request.content_hash)
            terminal = snapshot.terminal(request.content_hash)
            if terminal and terminal.outcome in ("CANCELLED", "EXPIRED") and accepted:
                raise ArtifactIntegrityError("accepted hosted request has cancellation/expiry")
        for receipt in receipts:
            if receipt.campaign_hash != spec.campaign_hash:
                raise ArtifactIntegrityError("hosted receipt campaign mismatch")
            snapshot.artifact(receipt.budget_before_hash, HostedBudgetJournalFact)
            snapshot.artifact(receipt.budget_after_hash, HostedBudgetJournalFact)
            if receipt.request_hash is not None:
                request = snapshot.request(receipt.request_hash)
                if receipt.attempt_identity != request.attempt_identity:
                    raise ArtifactIntegrityError("hosted receipt attempt mismatch")
            if receipt.accepted_exchange_hash is not None:
                exchange = snapshot.artifact(receipt.accepted_exchange_hash, HostedAgentExchange)
                if (
                    exchange.request_hash != receipt.request_hash
                    or exchange.response_hash != receipt.submission_bytes_hash
                    or exchange.authenticated_principal != receipt.authenticated_principal
                ):
                    raise ArtifactIntegrityError("hosted exchange/receipt mismatch")
                response_data = artifacts.get(exchange.response_hash)
                if response_data is None:
                    raise ArtifactIntegrityError("accepted hosted response missing")
        _ = snapshot.active_request
        return snapshot

    def snapshot(self, campaign_hash: str, *, recover: bool = False) -> HostedStoreSnapshot:
        with self.campaign_lock(campaign_hash) as campaign_fd:
            if recover:
                self.recover_locked(campaign_fd)
            return self.snapshot_locked(campaign_fd)

    def locate_request(self, request_hash: str) -> str:
        identity = _hash(request_hash)
        with (
            opened_directory(self._root) as root_fd,
            _child(root_fd, "campaigns") as parent_fd,
            os.scandir(parent_fd) as entries,
        ):
            campaigns = tuple(sorted(x.name for x in entries))
        for campaign in campaigns:
            _hash(campaign)
            snapshot = self.snapshot(campaign, recover=True)
            if any(x.content_hash == identity for x in snapshot.requests):
                return campaign
        raise ArtifactIntegrityError("hosted request is not registered")
