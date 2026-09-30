"""Saved transport import tests; disk test receipts never qualify real Qlib execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_hosted_campaign import _fixture, _response

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted import HostedJournalEntry, HostedPublication
from quantos.infrastructure.hosted_replay import SavedHostedProtocol
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _completed(root: Path):  # type: ignore[no-untyped-def]
    fixture = _fixture(root, max_trials=2, max_agent_runs=2, max_executions=2)
    fixture.service.start(fixture.spec.content_hash)
    for index in range(2):
        request = fixture.service.pending(fixture.spec.campaign_hash)
        assert request is not None
        if index == 0:
            rejected = fixture.service.submit(request.content_hash, b"invalid", "host")
            assert rejected.outcome == "REJECTED"
        accepted = fixture.service.submit(
            request.content_hash, _response(fixture, request, index), "host"
        )
        assert accepted.outcome == "ACCEPTED"
        fixture.service.resume(fixture.spec.campaign_hash)
    return fixture


def test_saved_submissions_preserve_rejections_and_independently_execute_two_roots(
    tmp_path: Path,
) -> None:
    original = _completed(tmp_path / "original")
    source_root = original.root / "protocol"
    before = raw_inventory(source_root)
    for name in ("fresh-a", "fresh-b"):
        target_root = tmp_path / name
        saved = SavedHostedProtocol.load(source_root, original.spec.campaign_hash)
        fresh = _fixture(target_root, max_trials=2, max_agent_runs=2, max_executions=2)
        assert fresh.spec == original.spec
        target = fresh.service
        target.protocol.store = HostedProtocolStore(
            target_root / "protocol", verify_journal_entry=saved.verify_entry
        )
        target.protocol._clock = saved.clock
        assert not (target_root / "executions").exists()
        completed = saved.run(target)
        assert completed.artifacts == saved.source.artifacts
        assert completed.journal == saved.source.journal
        assert (target_root / "executions/calls").read_text() == "2"
        assert completed.budget.used_unique_submissions == 3
        assert raw_inventory(source_root) == before
        # A second manager continuation reuses completed target receipts without execution.
        saved.run(target)
        assert (target_root / "executions/calls").read_text() == "2"


def test_changed_source_response_rejected_before_target_execution(tmp_path: Path) -> None:
    original = _completed(tmp_path / "original")
    snapshot = original.service.protocol.store.snapshot(original.spec.campaign_hash)
    response_hash = snapshot.accepted_receipt(snapshot.requests[0].content_hash)
    assert response_hash is not None and response_hash.submission_bytes_hash is not None
    path = (
        original.root
        / "protocol/campaigns"
        / original.spec.campaign_hash
        / "objects"
        / f"{response_hash.submission_bytes_hash}.json"
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(HostedQualificationError):
        SavedHostedProtocol.load(original.root / "protocol", original.spec.campaign_hash)


def test_generated_business_entry_must_match_next_full_bytes(tmp_path: Path) -> None:
    original = _completed(tmp_path / "original")
    saved = SavedHostedProtocol.load(original.root / "protocol", original.spec.campaign_hash)
    business = next(entry for entry in saved.source.journal if entry.operation_kind == "BUSINESS")
    changed = business.model_copy(update={"recorded_at": business.recorded_at.replace(year=2025)})
    with pytest.raises(ArtifactIntegrityError, match="next entry"):
        saved.verify_entry(changed)
    assert saved.observed_sequence == 0


def test_saved_submit_cannot_smuggle_business_publication(tmp_path: Path) -> None:
    original = _completed(tmp_path / "original")
    saved = SavedHostedProtocol.load(original.root / "protocol", original.spec.campaign_hash)
    intent = next(entry for entry in saved.source.journal if entry.operation_kind == "SUBMIT")
    publication = HostedPublication(
        artifact_hash=original.spec.content_hash,
        canonical_json=original.spec.canonical_bytes().decode(),
    )
    changed = HostedJournalEntry.model_validate(
        {**intent.model_dump(mode="python"), "publications": (publication,)}
    )
    with pytest.raises(ArtifactIntegrityError, match="non-protocol"):
        saved._submission_artifacts(changed)
