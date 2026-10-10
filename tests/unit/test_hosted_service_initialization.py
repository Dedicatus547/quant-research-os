"""Actual protocol registration precedes readiness without issuing a host request."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from test_hosted_campaign import _fixture
from test_hosted_deployment import _policy

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure import hosted_service as entrypoint
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_service import HostedPrincipalGrant, HostedUnixService
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root


def _channel(fixture):  # type: ignore[no-untyped-def]
    return HostedUnixService(
        fixture.service,
        fixture.root / "not-started.sock",
        _policy(),
        (
            HostedPrincipalGrant(
                principal="component",
                host_instance="component-host",
                uid=1,
                gid=1,
                campaign_hashes=frozenset((fixture.spec.campaign_hash,)),
                capability=b"c" * 32,
            ),
        ),
        specs={fixture.spec.content_hash: fixture.spec.campaign_hash},
        requests={},
        publication_guard=KnownValueGuard(()),
    )


def test_startup_registers_zero_budget_and_only_business_start_issues_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    service = _channel(fixture)
    calls = []
    original = fixture.service.verify_registered_inputs

    def verify(spec):  # type: ignore[no-untyped-def]
        calls.append(spec.content_hash)
        return original(spec)

    monkeypatch.setattr(fixture.service, "verify_registered_inputs", verify)
    service.initialize_registered_protocols()
    state = fixture.service.protocol.store.snapshot(fixture.spec.campaign_hash, recover=False)
    assert [(entry.operation_kind, entry.phase) for entry in state.journal] == [
        ("REGISTER", "INTENT"),
        ("REGISTER", "COMPLETE"),
    ]
    assert state.requests == state.terminals == ()
    assert state.budget.used_requests == state.budget.used_unique_submissions == 0
    assert not (tmp_path / "executions").exists()
    verify_protocol_root(tmp_path / "protocol", fixture.spec.campaign_hash)
    before = raw_inventory(tmp_path)
    fixture.clock[0] += timedelta(days=1)
    service.initialize_registered_protocols()
    assert raw_inventory(tmp_path) == before
    assert calls == [fixture.spec.content_hash] * 2
    status = fixture.service.start(fixture.spec.content_hash)
    request = fixture.service.pending(fixture.spec.campaign_hash)
    assert status.state == "WAITING_FOR_AGENT"
    assert request is not None and request.issued_at == fixture.clock[0]
    assert request.expires_at > request.issued_at
    assert status.protocol.used_requests == 1


@pytest.mark.parametrize("invalid_inputs", [False, True])
def test_fixed_main_registers_before_probe_and_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_inputs: bool
) -> None:
    fixture = _fixture(tmp_path)
    service = _channel(fixture)
    calls = []
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["hosted-service", "--profile-hash", "a" * 64, "--network-probe-port", "9"],
    )
    monkeypatch.setattr(entrypoint, "_hydrate_service_capabilities", lambda _: None)
    monkeypatch.setattr(entrypoint, "bootstrap_hosted_service", lambda _: service)
    if invalid_inputs:

        def reject(spec):  # type: ignore[no-untyped-def]
            raise ArtifactIntegrityError("component frozen-input mismatch")

        monkeypatch.setattr(fixture.service, "verify_registered_inputs", reject)

    def probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        state = fixture.service.protocol.store.snapshot(fixture.spec.campaign_hash, recover=False)
        assert state.requests == () and state.budget.used_requests == 0
        calls.append("probe")
        return MagicMock()

    def publish(path, data):  # type: ignore[no-untyped-def]
        assert path == Path("/channel/bootstrap-observation.json")
        calls.append("readiness")

    monkeypatch.setattr(entrypoint.socket, "socket", probe)
    monkeypatch.setattr(entrypoint, "atomic_write_bytes", publish)
    monkeypatch.setattr(service, "serve", lambda: calls.append("serve"))
    before = raw_inventory(tmp_path)
    if invalid_inputs:
        with pytest.raises(ArtifactIntegrityError):
            entrypoint.main()
        assert calls == [] and raw_inventory(tmp_path) == before
    else:
        entrypoint.main()
        assert calls == ["probe", "readiness", "serve"]


@pytest.mark.parametrize("invalid_inputs", [False, True])
def test_bad_registration_or_failed_original_input_verifier_publishes_no_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_inputs: bool
) -> None:
    fixture = _fixture(tmp_path)
    service = _channel(fixture)
    if invalid_inputs:

        def reject(spec):  # type: ignore[no-untyped-def]
            raise ArtifactIntegrityError("component frozen-input mismatch")

        monkeypatch.setattr(fixture.service, "verify_registered_inputs", reject)
    else:
        service._specs = {"f" * 64: fixture.spec.campaign_hash}
    before = raw_inventory(tmp_path)
    with pytest.raises(ArtifactIntegrityError):
        service.initialize_registered_protocols()
    assert raw_inventory(tmp_path) == before
