"""Management-only saved SUBMIT import; business authority is always regenerated."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import CanonicalContract
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedJournalEntry,
    HostedRequestTerminalReceipt,
    HostedSubmissionReceipt,
    HostObservation,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.infrastructure.hosted_store import (
    AUTHORITY_BYTE_CAP,
    HostedProtocolStore,
    HostedStoreSnapshot,
)
from quantos.infrastructure.hosted_verification import (
    raw_inventory,
    verify_protocol_root,
    verify_raw_inventory,
)

_SUBMIT_TYPES: dict[str, type[CanonicalContract]] = {
    "hosted-agent-response/v1": HostedAgentResponse,
    "hosted-observation/v1": HostObservation,
    "hosted-agent-exchange/v1": HostedAgentExchange,
    "hosted-budget-journal-fact/v1": HostedBudgetJournalFact,
    "hosted-submission-receipt/v1": HostedSubmissionReceipt,
}


@dataclass
class SavedHostedProtocol:
    """Verified immutable source plus a cursor used only by the offline manager.

    Its source contains historical business facts for comparison. Only the SUBMIT
    allowlist below may be published into the target. No host channel exposes this.
    """

    source: HostedStoreSnapshot
    observed_sequence: int = 0

    @classmethod
    def load(cls, root: Path, campaign_hash: str) -> SavedHostedProtocol:
        inventory = raw_inventory(root)
        verify_protocol_root(root, campaign_hash)
        source = HostedProtocolStore(root).snapshot(campaign_hash, recover=False)
        verify_raw_inventory(root, inventory)
        if any(entry.operation_kind == "TERMINATE" for entry in source.journal):
            raise ArtifactIntegrityError("saved replay does not support TERMINATE operations")
        for entry in source.journal:
            if entry.phase == "INTENT" and entry.operation_kind == "SUBMIT":
                cls._submission_artifacts(entry)
        return cls(source)

    @staticmethod
    def _submission_artifacts(entry: HostedJournalEntry) -> tuple[CanonicalContract, ...]:
        artifacts: list[CanonicalContract] = []
        for publication in entry.publications:
            data = publication.canonical_json.encode("utf-8")
            schema = strict_json_object(data, max_bytes=AUTHORITY_BYTE_CAP).get("schema_version")
            if not isinstance(schema, str) or schema not in _SUBMIT_TYPES:
                raise ArtifactIntegrityError("saved SUBMIT contains non-protocol publication")
            artifacts.append(
                parse_hosted_contract(data, _SUBMIT_TYPES[schema], max_bytes=AUTHORITY_BYTE_CAP)
            )
        receipts = [item for item in artifacts if isinstance(item, HostedSubmissionReceipt)]
        if len(receipts) != 1 or receipts[0].outcome == "EXHAUSTED":
            raise ArtifactIntegrityError("saved SUBMIT receipt is absent or unsupported")
        return tuple(artifacts)

    def verify_entry(self, value: object) -> None:
        """Check each generated entry against its exact original bytes before publication."""
        if not isinstance(value, HostedJournalEntry):
            raise ArtifactIntegrityError("replay journal entry has an unknown type")
        index = value.sequence - 1
        if index >= len(self.source.journal) or (
            value.canonical_bytes() != self.source.journal[index].canonical_bytes()
        ):
            raise ArtifactIntegrityError("replay generated journal differs from saved next entry")
        self.observed_sequence = value.sequence

    def clock(self) -> datetime:
        """Keep the active request's saved time; issue the next at its original anchor."""
        active: HostedAgentRequest | None = None
        for entry in self.source.journal[: self.observed_sequence]:
            for publication in entry.publications:
                data = publication.canonical_json.encode("utf-8")
                schema = strict_json_object(data, max_bytes=AUTHORITY_BYTE_CAP).get(
                    "schema_version"
                )
                if schema == "hosted-agent-request/v1":
                    active = parse_hosted_contract(
                        data, HostedAgentRequest, max_bytes=AUTHORITY_BYTE_CAP
                    )
                elif schema == "hosted-request-terminal-receipt/v1":
                    terminal = parse_hosted_contract(
                        data, HostedRequestTerminalReceipt, max_bytes=AUTHORITY_BYTE_CAP
                    )
                    if active is not None and terminal.request_hash == active.content_hash:
                        active = None
        if active is not None:
            return active.issued_at
        for entry in self.source.journal[self.observed_sequence :]:
            if entry.phase == "INTENT" and entry.operation_kind == "ISSUE":
                return entry.recorded_at
        return self.source.journal[-1].recorded_at

    def verify_prefix(self, target: HostedStoreSnapshot) -> None:
        if target.spec.canonical_bytes() != self.source.spec.canonical_bytes():
            raise ArtifactIntegrityError("replay spec differs from saved bytes")
        if len(target.journal) > len(self.source.journal) or any(
            generated.canonical_bytes() != saved.canonical_bytes()
            for generated, saved in zip(target.journal, self.source.journal, strict=False)
        ):
            raise ArtifactIntegrityError("replay prefix differs from original complete journal")
        self.observed_sequence = len(target.journal)

    def import_next_submission(self, store: HostedProtocolStore) -> bool:
        campaign = self.source.spec.campaign_hash
        with store.campaign_lock(campaign) as descriptor:
            # Existing target intents may recover their own exact publications only.
            store.recover_locked(descriptor)
            target = store.snapshot_locked(descriptor)
            self.verify_prefix(target)
            offset = len(target.journal)
            if offset == len(self.source.journal):
                return False
            entry = self.source.journal[offset]
            if entry.phase != "INTENT" or entry.operation_kind != "SUBMIT":
                return False
            artifacts = self._submission_artifacts(entry)
            receipt = next(item for item in artifacts if isinstance(item, HostedSubmissionReceipt))
            request = target.active_request
            if (
                request is None
                or receipt.request_hash != request.content_hash
                or receipt.attempt_identity != request.attempt_identity
                or receipt.budget_before_hash != target.budget.content_hash
            ):
                raise ArtifactIntegrityError(
                    "saved SUBMIT does not bind the target pending request"
                )
            store.commit_locked(
                descriptor,
                campaign_hash=campaign,
                operation_id=entry.operation_id,
                operation_kind="SUBMIT",
                recorded_at=entry.recorded_at,
                artifacts=artifacts,
            )
            self.verify_prefix(store.snapshot_locked(descriptor))
            return True

    def run(self, application: HostedCampaignApplicationService) -> HostedStoreSnapshot:
        """Independently run the normal application and import original transport facts."""
        campaign = self.source.spec.campaign_hash
        store = application.protocol.store
        application.start(self.source.spec.content_hash)
        while True:
            before = store.snapshot(campaign)
            self.verify_prefix(before)
            if len(before.journal) == len(self.source.journal):
                if before.artifacts != self.source.artifacts:
                    raise ArtifactIntegrityError("replay final protocol object set differs")
                return before
            if self.import_next_submission(store):
                continue
            application.resume(campaign)
            after = store.snapshot(campaign)
            self.verify_prefix(after)
            if len(after.journal) == len(before.journal):
                raise ArtifactIntegrityError(
                    "saved replay cannot advance the next original operation"
                )
