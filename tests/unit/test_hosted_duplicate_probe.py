"""Actual fork/barrier with functional inputs; never installed or live qualification."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import NOW, _inputs
from test_hosted_campaign import _service, _spec

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.hosted import HostedSubmissionReceipt
from quantos.infrastructure import hosted_duplicate_probe as probe
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.mark.parametrize("case", ("accepted", "rejected"))
def test_actual_barrier_receipt_resume_and_cap_reuse(
    tmp_path: Path, monkeypatch, case: str
) -> None:
    inputs = _inputs(tmp_path / "functional-inputs")
    spec = _spec(inputs, submissions=2)
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    channel.mkdir()
    bundle = SimpleNamespace(
        campaign=inputs.campaign,
        hosted_recipe=SimpleNamespace(started_at=NOW, hosted_budget=spec.hosted_budget),
    )

    def boot(_profile: str, *, protocol_clock, authority_root: Path, channel_root: Path):
        assert authority_root == authority and channel_root == channel
        service = _service(authority, inputs, spec)
        service.protocol = HostedProtocolService(
            service.protocol.store,
            clock=protocol_clock,
            verify_inputs=service.verify_registered_inputs,
        )
        return SimpleNamespace(application=service)

    values = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": SimpleNamespace(business_configuration_hash="b" * 64),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
    }
    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(probe, "hydrate_service_capabilities", lambda _: None)
    monkeypatch.setattr(probe, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: spec)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda _root, _hash, cls: values[cls.__name__]
    )
    probe.run_duplicate_probe("d" * 64, case, authority_root=authority, channel_root=channel)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    assert observation["qualification_eligibility"] == "NOT_QUALIFIED"
    assert len(observation["process_exits"]) == 6
    assert len({item["pid"] for item in observation["process_exits"]}) == 6
    assert all(item["exit_code"] == 0 for item in observation["process_exits"])
    records = {
        path.stem: json.loads(path.read_bytes())
        for path in (channel / "process-records").glob("*.json")
    }
    assert all(item["parent_pid"] == os.getpid() for item in records.values())
    assert all(records[phase]["barrier"] for phase in ("submit-1", "submit-2"))
    assert all(records[phase]["fresh_application_bootstrap"] for phase in ("resume-1", "resume-2"))
    locks = {tuple(item["lock_before"]) for item in records.values()} | {
        tuple(item["lock_after"]) for item in records.values()
    }
    assert len(locks) == 1
    assert all(
        item["execute_calls"] == item["workflow_calls"] == item["network_attempts"] == []
        for item in records.values()
    )
    assert records["resume-2"]["before_inventory"] == records["resume-2"]["after_inventory"]
    assert records["repeat"]["before_inventory"] == records["repeat"]["after_inventory"]
    assert records["late-repeat"]["before_inventory"] == records["late-repeat"]["after_inventory"]
    receipts = [
        HostedSubmissionReceipt.model_validate(records[phase]["result_json"])
        for phase in ("submit-1", "submit-2", "repeat", "late-repeat")
    ]
    assert len(set(item.content_hash for item in receipts)) == 1
    assert receipts[0].outcome == ("ACCEPTED" if case == "accepted" else "REJECTED")
    state = HostedProtocolStore(authority / "protocol").snapshot(
        inputs.campaign.content_hash, recover=False
    )
    assert state.budget.used_unique_submissions == 2
    assert state.budget.request_submissions[0].used_submissions == 2
    trials = [
        json.loads(data)
        for data in state.artifacts.values()
        if json.loads(data).get("schema_version") == "campaign-trial/v1"
    ]
    assert len(trials) == int(case == "accepted")
    if trials:
        assert trials[0]["outcome"] == "SCHEMA_INVALID"
        assert trials[0]["execution_requested"] is False
    else:
        assert raw_inventory(channel / "snapshots/after-submit/authority") == raw_inventory(
            channel / "snapshots/after-business/authority"
        )
    original = raw_inventory(authority)
    assert probe._snapshot("late-copy", authority, channel) is None
    assert raw_inventory(authority) == original
