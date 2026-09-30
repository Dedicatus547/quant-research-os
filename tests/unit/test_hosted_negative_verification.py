"""Semantic negative accounting fixtures, not original management process evidence."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from test_hosted_protocol import _fixture, _mutate

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.infrastructure.hosted_negative_verification import (
    NegativeSubmissionKind,
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory

_KINDS: tuple[NegativeSubmissionKind, ...] = (
    "campaign_hash",
    "transport_ordinal",
    "context_pack_hash",
    "request_hash",
    "attempt_identity",
    "expired",
    "cancelled",
    "conflict",
    "seen_bytes",
)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize(
    "mutation", [None, "business", "bytes", "extra_operation", "extra_protocol_file"]
)
def test_negative_transition_recomputes_bytes_budget_and_unchanged_business(
    tmp_path: Path,
    kind: NegativeSubmissionKind,
    mutation: str | None,
) -> None:
    f = _fixture(tmp_path)
    # A deterministic canary belongs to both snapshots and cannot be replaced or
    # silently omitted even though its filename is unrelated to protocol storage.
    (tmp_path / "business-canary").write_bytes(b"immutable deterministic evidence")
    authority = tmp_path / "authority"
    authority.mkdir()
    shutil.copytree(f.root, authority / "protocol")
    (authority / "business-canary").write_bytes((tmp_path / "business-canary").read_bytes())
    service = HostedProtocolService(
        HostedProtocolStore(authority / "protocol"), clock=f.clock, verify_inputs=lambda _: None
    )
    raw = f.response.canonical_bytes()
    if kind == "cancelled":
        service.cancel(f.request.content_hash, "negative.host")
    elif kind == "conflict":
        service.submit(f.request.content_hash, raw, "negative.host")
        raw = _mutate(f.response, transport_ordinal=2)
    elif kind == "seen_bytes":
        raw = b"{}"
        service.submit(f.request.content_hash, raw, "negative.host")
        service.cancel(f.request.content_hash, "negative.host")
        f.clock.now += timedelta(hours=1)
    elif kind not in ("expired",):
        raw = _mutate(f.response, **{kind: 2 if kind == "transport_ordinal" else "0" * 64})
    before = tmp_path / "before"
    shutil.copytree(authority, before)
    if kind == "expired":
        f.clock.now += timedelta(seconds=60)
    receipt = service.submit(f.request.content_hash, raw, "negative.host")
    if mutation == "business":
        (authority / "business-canary").write_bytes(b"replaced deterministic evidence")
    elif mutation == "bytes":
        raw = b"[]"
    elif mutation == "extra_operation":
        service.submit(f.request.content_hash, b'{"other":true}', "negative.host")
    elif mutation == "extra_protocol_file":
        (authority / "protocol" / "unrelated-capture").write_bytes(b"unpublished authority")
    snapshots = raw_inventory(before), raw_inventory(authority)
    arguments = {
        "campaign_hash": f.spec.campaign_hash,
        "request_hash": f.request.content_hash,
        "response_bytes": raw,
        "receipt_hash": receipt.content_hash,
        "kind": kind,
    }
    if mutation is None:
        checked = verify_negative_submission_transition(before, authority, **arguments)
        assert receipt.content_hash in checked
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            verify_negative_submission_transition(before, authority, **arguments)
    assert snapshots == (raw_inventory(before), raw_inventory(authority))


@pytest.mark.parametrize(
    "mutation", ["label", "two_bindings", "early_expiry", "absent_cancel", "old_receipt"]
)
def test_valid_authority_cannot_borrow_another_negative_case(
    tmp_path: Path,
    mutation: str,
) -> None:
    f = _fixture(tmp_path)
    before, after = tmp_path / "before", tmp_path / "after"
    shutil.copytree(f.root, before / "protocol")
    shutil.copytree(f.root, after / "protocol")
    service = HostedProtocolService(
        HostedProtocolStore(after / "protocol"), clock=f.clock, verify_inputs=lambda _: None
    )
    raw = _mutate(f.response, campaign_hash="0" * 64)
    kind: NegativeSubmissionKind = "campaign_hash"
    if mutation == "two_bindings":
        raw = _mutate(f.response, campaign_hash="0" * 64, transport_ordinal=2)
    elif mutation == "label":
        kind = "context_pack_hash"
    elif mutation == "early_expiry":
        kind = "expired"
    elif mutation == "absent_cancel":
        kind = "cancelled"
    receipt = service.submit(f.request.content_hash, raw, "negative.host")
    if mutation == "old_receipt":
        original = HostedProtocolStore(before / "protocol").snapshot(f.spec.campaign_hash)
        receipt = next(item for item in original.receipts if item.outcome == "EXHAUSTED")
    with pytest.raises((HostedQualificationError, ValueError)):
        verify_negative_submission_transition(
            before,
            after,
            campaign_hash=f.spec.campaign_hash,
            request_hash=f.request.content_hash,
            response_bytes=raw,
            receipt_hash=receipt.content_hash,
            kind=kind,
        )


def test_seen_accepted_response_preserves_original_acceptance_after_ttl_and_cancel(
    tmp_path: Path,
) -> None:
    f = _fixture(tmp_path, total=1, per_request=1)
    raw = f.response.canonical_bytes()
    receipt = f.service.submit(f.request.content_hash, raw, "negative.host")
    f.service.cancel(f.request.content_hash, "negative.host")
    f.clock.now += timedelta(hours=1)
    before = tmp_path / "before"
    shutil.copytree(f.root, before / "protocol")
    assert f.service.submit(f.request.content_hash, raw, "negative.host") == receipt
    after = tmp_path / "after"
    shutil.copytree(f.root, after / "protocol")
    assert receipt.content_hash in verify_negative_submission_transition(
        before,
        after,
        campaign_hash=f.spec.campaign_hash,
        request_hash=f.request.content_hash,
        response_bytes=raw,
        receipt_hash=receipt.content_hash,
        kind="seen_bytes",
    )
