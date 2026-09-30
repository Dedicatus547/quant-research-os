"""Offline accounting for bounded transport rejects; never live model evidence."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_hosted_protocol import _fixture, _mutate

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure.hosted_negative_verification import (
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


@pytest.mark.parametrize(
    "case",
    [
        "invalid_utf8",
        "duplicate_keys",
        "unknown_field",
        "noncanonical",
        "unknown_candidate",
        "oversized",
        "credential_like",
    ],
)
@pytest.mark.parametrize("mutation", [None, "business", "bytes", "extra_protocol"])
def test_bounded_rejects_reconcile_prefix_bytes_and_exact_disk_delta(
    tmp_path: Path, case: str, mutation: str | None
) -> None:
    f = _fixture(tmp_path / "component")
    authority = tmp_path / "authority"
    shutil.copytree(f.root, authority / "protocol")
    (authority / "deterministic-canary").write_bytes(b"no pipeline side effect")
    service = HostedProtocolService(
        HostedProtocolStore(authority / "protocol"), clock=f.clock, verify_inputs=lambda _: None
    )
    kind = "schema_invalid"
    if case == "invalid_utf8":
        raw = b"\xff"
    elif case == "duplicate_keys":
        raw = b'{"a":1,"a":2}'
    elif case == "unknown_field":
        raw = _mutate(f.response, unexpected="forbidden")
    elif case == "noncanonical":
        raw = b" " + f.response.canonical_bytes()
    elif case == "oversized":
        kind = case
        raw = b"x" * (f.request.max_response_bytes + 8000)
    else:
        kind = case
        proposal = canonical_json_bytes(
            {"candidate_hash": "0" * 64}
            if case == "unknown_candidate"
            else {
                "candidate_hash": f.request.business_request.candidate_options[0].content_hash,
                "api_key": "SYNTHETIC_CREDENTIAL_REJECTION_FIXTURE_ONLY",
            }
        ).decode()
        raw = _mutate(
            f.response, proposal_json=proposal, proposal_hash=sha256_bytes(proposal.encode())
        )
    before = tmp_path / "before"
    shutil.copytree(authority, before)
    receipt = service.submit(f.request.content_hash, raw, "bounded.fixture")
    assert receipt.outcome == "REJECTED"
    # Unique rejection writes only hashes/receipts; credential-like and oversized
    # payloads are not retained, even in the source observation.
    if case in ("credential_like", "oversized"):
        assert not any(raw[:200] in item.read_bytes() for item in authority.rglob("*.json"))
    assert service.submit(f.request.content_hash, raw, "bounded.fixture") == receipt
    if mutation == "business":
        (authority / "deterministic-canary").write_bytes(b"changed")
    elif mutation == "bytes":
        raw = f.response.canonical_bytes()
    elif mutation == "extra_protocol":
        (authority / "protocol/unknown-file").write_bytes(b"unpublished")
    inventories = raw_inventory(before), raw_inventory(authority)
    if mutation is None:
        assert receipt.content_hash in verify_negative_submission_transition(
            before,
            authority,
            campaign_hash=f.spec.campaign_hash,
            request_hash=f.request.content_hash,
            response_bytes=raw,
            receipt_hash=receipt.content_hash,
            kind=kind,
        )
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            verify_negative_submission_transition(
                before,
                authority,
                campaign_hash=f.spec.campaign_hash,
                request_hash=f.request.content_hash,
                response_bytes=raw,
                receipt_hash=receipt.content_hash,
                kind=kind,
            )
    assert inventories == (raw_inventory(before), raw_inventory(authority))
