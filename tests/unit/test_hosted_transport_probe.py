"""Run fixed transport recipes against real protocol state; never live source proof."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import NOW, _inputs
from test_hosted_campaign import _service, _spec
from test_hosted_launcher import _configuration

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.autonomous import P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
from quantos.infrastructure import hosted_negative_probe as probe
from quantos.infrastructure.hosted_fixture_frames import (
    BOUNDED_REJECTION_CASES,
    BUSINESS_REJECTION_CASES,
    HOST_OBSERVATION_CASES,
    HOST_OBSERVATION_SCHEMA_REJECTIONS,
    bounded_rejection_frame,
    host_observation_frame,
)
from quantos.infrastructure.hosted_negative_verification import (
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root

CASES = (
    tuple(("Q03", name) for name in probe.NEGATIVE_CASES)
    + tuple(("Q04", name) for name in (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES))
    + tuple(("Q08", name) for name in HOST_OBSERVATION_CASES)
)


def _verify_transport_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str, case: str
) -> None:
    inputs = _inputs(tmp_path / "functional-inputs")
    selection = P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
    spec = _spec(inputs).model_copy(
        update={"selection_finalization_profile_hash": selection.content_hash}
    )
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    channel.mkdir()
    bundle = SimpleNamespace(
        campaign=inputs.campaign, hosted_recipe=SimpleNamespace(started_at=NOW)
    )
    values = {
        "HostedDeploymentProfile": SimpleNamespace(
            configuration_hash="a" * 64, model_configuration_hash="e" * 64
        ),
        "HostedServiceConfiguration": SimpleNamespace(business_configuration_hash="b" * 64),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
        "HostedLauncherConfiguration": _configuration(),
    }
    application = []

    def boot(_profile: str, *, protocol_clock):
        clock = [protocol_clock()]
        service = _service(authority, inputs, spec, clock=clock, selection_profile=selection)
        service.protocol = HostedProtocolService(
            service.protocol.store,
            clock=protocol_clock,
            verify_inputs=service.verify_registered_inputs,
        )
        application.append(service)
        return SimpleNamespace(application=service)

    mapping = {"/authority": authority, "/channel": channel}
    monkeypatch.setattr(probe, "Path", lambda value: mapping.get(str(value), Path(value)))
    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(probe, "hydrate_service_capabilities", lambda _profile: None)
    monkeypatch.setattr(probe, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: spec)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda _root, _hash, cls: values[cls.__name__]
    )
    probe.run_transport_fixture("d" * 64, case, family)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    state = HostedProtocolStore(authority / "protocol").snapshot(spec.campaign_hash)
    receipt = next(
        item for item in state.receipts if item.content_hash == observation["receipt_hash"]
    )
    assert observation["qualification_eligibility"] == "NOT_QUALIFIED"
    assert observation["execute_calls"] == observation["workflow_calls"] == []
    assert observation["network_attempts"] == []
    assert observation["repeat_receipt_hash"] == receipt.content_hash
    assert not (authority / "executions").exists()
    assert state.budget.used_unique_submissions == (
        2 if case in ("expired", "cancelled", "conflict") else 1
    )
    verify_protocol_root(authority / "protocol", spec.campaign_hash)
    if family == "Q04" and case in BUSINESS_REJECTION_CASES:
        facts = application[0].verify_research_facts(state)
        completed = [step for step in facts.steps if step.phase == "COMPLETED"]
        assert len(completed) == 1
        assert completed[0].execution_request is None
        assert observation["business_report_hash"] is None
    else:
        before = channel / "before/authority"
        original = raw_inventory(before), raw_inventory(authority)
        request = state.requests[0]
        if family == "Q03":
            response = observation["response_json"].encode()
            kind = case
        elif family == "Q04":
            response = bounded_rejection_frame(request, case)
            kind = {
                "frame_byte_cap": "oversized",
                "unknown_candidate": "unknown_candidate",
                "credential_like": "credential_like",
            }.get(case, "schema_invalid")
        else:
            response = host_observation_frame(request, case)
            kind = (
                "schema_invalid"
                if case in HOST_OBSERVATION_SCHEMA_REJECTIONS
                else "source_unattested"
            )
        checked = verify_negative_submission_transition(
            before,
            authority,
            campaign_hash=spec.campaign_hash,
            request_hash=request.content_hash,
            response_bytes=response,
            receipt_hash=receipt.content_hash,
            kind=kind,
        )
        assert receipt.content_hash in checked
        assert original == (raw_inventory(before), raw_inventory(authority))
    if case == "source_model_conflict":
        assert observation["source_conflict_rejected"] is True


@pytest.mark.fresh_offline_process
def test_fixed_transport_probe_retains_real_receipts_and_zero_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One clean interpreter for the fixed offline matrix; each scenario has a
    # fresh authority and its own reverted configuration/port doubles.
    for family, case in CASES:
        root = tmp_path / f"{family}-{case}"
        root.mkdir()
        with monkeypatch.context() as scenario:
            _verify_transport_recipe(root, scenario, family, case)


@pytest.mark.parametrize("family,case", (("Q03", "shell"), ("Q11", "campaign_hash")))
def test_unknown_transport_recipe_cannot_bootstrap_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str, case: str
) -> None:
    monkeypatch.setattr(
        probe, "bootstrap_hosted_service", lambda *_args, **_kwargs: pytest.fail("boot")
    )
    with pytest.raises(ValueError, match="unknown fixed negative"):
        probe.run_transport_fixture("d" * 64, case, family)
    assert list(tmp_path.iterdir()) == []


def test_nonempty_authority_is_preserved_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    channel.mkdir()
    (authority / "canary").write_bytes(b"retain rejected original root")
    mapping = {"/authority": authority, "/channel": channel}
    monkeypatch.setattr(probe, "Path", lambda value: mapping.get(str(value), Path(value)))
    before = raw_inventory(authority)
    with pytest.raises(ArtifactIntegrityError, match="empty authority"):
        probe.run_transport_fixture("d" * 64, "campaign_hash", "Q03")
    assert raw_inventory(authority) == before
