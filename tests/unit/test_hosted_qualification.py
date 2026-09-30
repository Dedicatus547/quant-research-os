"""Independent hosted verifier refuses missing evidence and malformed raw authorities."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_hosted_protocol import _fixture

from quantos.contracts.hosted_qualification import HostedQualificationCase
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    verify_case,
    verify_protocol_root,
    verify_raw_inventory,
)


def test_protocol_verifier_recomputes_accepted_receipt_and_budget(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = raw_inventory(fixture.root)
    receipt = fixture.service.submit(
        fixture.request.content_hash, fixture.response.canonical_bytes(), "host"
    )
    assert receipt.outcome == "ACCEPTED"
    identities = verify_protocol_root(fixture.root, fixture.spec.campaign_hash)
    assert receipt.content_hash in identities
    repeated = fixture.service.submit(
        fixture.request.content_hash, fixture.response.canonical_bytes(), "host"
    )
    assert repeated == receipt
    assert verify_protocol_root(fixture.root, fixture.spec.campaign_hash) == identities
    with pytest.raises(HostedQualificationError, match="inventory"):
        verify_raw_inventory(fixture.root, before)
    target = fixture.root / "campaigns" / fixture.spec.campaign_hash / "objects"
    path = target / f"{fixture.response.content_hash}.json"
    path.write_bytes(path.read_bytes().replace(b'"source":"HOST_REPORTED"', b'"source":"FAKE"'))
    with pytest.raises(HostedQualificationError):
        verify_protocol_root(fixture.root, fixture.spec.campaign_hash)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_raw_inventory_refuses_aliases_and_special_files(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    path = root / "file.json"
    path.write_bytes(b"immutable")
    if kind == "symlink":
        (root / "alias").symlink_to(path)
    elif kind == "hardlink":
        os.link(path, root / "alias")
    else:
        os.mkfifo(root / "fifo")
    with pytest.raises(HostedQualificationError):
        raw_inventory(root)


def test_producer_cannot_award_pass_or_qualify_empty_case(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        HostedQualificationCase.model_validate({"case_id": "Q11", "verdict": "PASS"})
    result = verify_case(tmp_path, HostedQualificationCase(case_id="Q11"))
    assert result.verdict == "NOT_EVALUATED"
