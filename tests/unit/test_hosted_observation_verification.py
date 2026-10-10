"""Self-report admission is transport-only; all fixtures are synthetic."""

import shutil
from pathlib import Path

import pytest
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.infrastructure.hosted_fixture_frames import (
    HOST_OBSERVATION_CASES,
    HOST_OBSERVATION_SCHEMA_REJECTIONS,
    host_observation_frame,
)
from quantos.infrastructure.hosted_negative_verification import (
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


@pytest.mark.parametrize("case", HOST_OBSERVATION_CASES)
@pytest.mark.parametrize("mutation", [None, "business", "bytes", "extra_protocol"])
def test_self_report_transition_keeps_budget_and_deterministic_root(
    tmp_path: Path, case: str, mutation: str | None
):
    f = _fixture(tmp_path / "fixture")
    authority = tmp_path / "authority"
    shutil.copytree(f.root, authority / "protocol")
    (authority / "business-canary").write_bytes(b"no execution or trial")
    service = HostedProtocolService(
        HostedProtocolStore(authority / "protocol"), clock=f.clock, verify_inputs=lambda _: None
    )
    raw = host_observation_frame(f.request, case)
    before = tmp_path / "before"
    shutil.copytree(authority, before)
    receipt = service.submit(f.request.content_hash, raw, "synthetic.host")
    kind = "schema_invalid" if case in HOST_OBSERVATION_SCHEMA_REJECTIONS else "source_unattested"
    assert receipt.outcome == ("REJECTED" if kind == "schema_invalid" else "ACCEPTED")
    assert service.submit(f.request.content_hash, raw, "synthetic.host") == receipt
    if mutation == "business":
        (authority / "business-canary").write_bytes(b"unexpected deterministic side effect")
    elif mutation == "bytes":
        raw += b" "
    elif mutation == "extra_protocol":
        (authority / "protocol/unpublished").write_bytes(b"unpublished")
    inventories = raw_inventory(before), raw_inventory(authority)
    if mutation is None:
        assert verify_negative_submission_transition(
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
