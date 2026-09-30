"""Exact native protocol tuples, including expiration inside a first submission."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.hosted import HostedPublication, HostedRequestTerminalReceipt
from quantos.infrastructure.hosted_business_file_closure import _verify_native_protocol_publication
from quantos.infrastructure.hosted_lifecycle_verification import _verify_fixture_protocol_times
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _native_fixture(tmp_path: Path):
    f = _fixture(tmp_path / "functional-inputs")
    # The generic protocol fixture supplies only a ContextPack projection.
    # Native hosted requests bind both ContextPack and the frozen proposal schema.
    source = f.request
    f.root = tmp_path / "native-protocol"
    f.service = HostedProtocolService(
        HostedProtocolStore(f.root), clock=f.clock, verify_inputs=lambda _: None
    )
    f.service.register(f.spec)
    f.request = f.service.issue(
        f.spec.content_hash,
        source.business_request,
        projection_object_hashes=tuple(
            sorted({source.context_pack_hash, source.proposal_schema_hash})
        ),
    )
    f.response = f.response.model_copy(update={"request_hash": f.request.content_hash})
    return f


@pytest.mark.parametrize(
    "case", ("first-expired", "previous-expired", "previous-cancelled", "previous-accepted", "seen")
)
def test_native_expiration_and_prior_terminal_publications_are_read_only_verified(
    tmp_path: Path, case: str
) -> None:
    f = _native_fixture(tmp_path)
    if case == "previous-cancelled":
        f.service.cancel(f.request.content_hash, "fixture.host")
    elif case == "previous-accepted":
        f.service.submit(f.request.content_hash, f.response.canonical_bytes(), "fixture.host")
    elif case == "seen":
        f.service.submit(f.request.content_hash, b"{}", "fixture.host")
    f.clock.now = f.request.expires_at
    if case == "previous-expired":
        f.service.resume(f.spec.campaign_hash)
    # Unique malformed bytes still acquire the existing terminal/acceptance
    # rejection before schema parsing. This never invokes the business engine.
    f.service.submit(f.request.content_hash, b"[]", "fixture.host")
    state = f.service.store.snapshot(f.spec.campaign_hash, recover=False)
    before = raw_inventory(f.root)
    budget = None
    accepted: set[str] = set()
    terminated: set[str] = set()
    for entry in state.journal:
        if entry.phase == "INTENT":
            budget = _verify_native_protocol_publication(state, entry, budget, accepted, terminated)
    assert budget == state.budget
    assert terminated == ({f.request.content_hash} if case != "previous-accepted" else set())
    assert raw_inventory(f.root) == before


@pytest.mark.parametrize("mutation", ("principal", "reason", "time", "missing", "extra", "early"))
def test_first_expired_submit_rejects_changed_native_tuple(tmp_path: Path, mutation: str) -> None:
    f = _native_fixture(tmp_path)
    f.clock.now = f.request.expires_at
    f.service.submit(f.request.content_hash, b"[]", "fixture.host")
    state = f.service.store.snapshot(f.spec.campaign_hash, recover=False)
    intent = next(
        entry
        for entry in state.journal
        if entry.phase == "INTENT" and entry.operation_kind == "SUBMIT"
    )
    before = raw_inventory(f.root)
    prior = None
    accepted: set[str] = set()
    terminated: set[str] = set()
    for entry in state.journal:
        if entry == intent:
            break
        if entry.phase == "INTENT":
            prior = _verify_native_protocol_publication(state, entry, prior, accepted, terminated)
    publications = list(intent.publications)
    terminal = HostedRequestTerminalReceipt.model_validate_json(publications[1].canonical_json)
    if mutation in ("principal", "reason", "time"):
        values = {
            "principal": {"authenticated_principal": "fixture.host"},
            "reason": {"reason": "AUTHORIZED_CANCELLATION"},
            "time": {"recorded_at": terminal.recorded_at - timedelta(seconds=1)},
        }
        changed = terminal.model_copy(update=values[mutation])
        publications[1] = HostedPublication(
            artifact_hash=changed.content_hash, canonical_json=changed.canonical_bytes().decode()
        )
    elif mutation == "missing":
        publications.pop(1)
    elif mutation == "extra":
        publications.insert(1, publications[1])
    altered = intent.model_copy(
        update={
            "publications": tuple(publications),
            **(
                {"recorded_at": f.request.expires_at - timedelta(seconds=1)}
                if mutation == "early"
                else {}
            ),
        }
    )
    with pytest.raises(HostedQualificationError):
        _verify_native_protocol_publication(state, altered, prior, accepted, terminated)
    assert raw_inventory(f.root) == before


@pytest.mark.parametrize("offset", (-1, 0, 1))
def test_lifecycle_exact_ttl_cross_checks_actual_protocol_clock(
    tmp_path: Path, offset: int
) -> None:
    f = _native_fixture(tmp_path)
    f.clock.now = f.request.expires_at + timedelta(seconds=offset)
    f.service.submit(f.request.content_hash, f.response.canonical_bytes(), "lifecycle.fixture")
    state = f.service.store.snapshot(f.spec.campaign_hash, recover=False)
    before = raw_inventory(f.root)
    if offset:
        with pytest.raises(HostedQualificationError, match="clock"):
            _verify_fixture_protocol_times("ttl_unseen_response", state)
    else:
        _verify_fixture_protocol_times("ttl_unseen_response", state)
    assert raw_inventory(f.root) == before


def test_lifecycle_clock_metadata_cannot_hide_a_different_native_principal(tmp_path: Path) -> None:
    f = _native_fixture(tmp_path)
    f.clock.now = f.request.expires_at
    f.service.submit(f.request.content_hash, b"[]", "other.fixture")
    state = f.service.store.snapshot(f.spec.campaign_hash, recover=False)
    with pytest.raises(HostedQualificationError, match="principal"):
        _verify_fixture_protocol_times("ttl_unseen_response", state)
