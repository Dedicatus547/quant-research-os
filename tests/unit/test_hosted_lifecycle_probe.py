"""Actual fork/flock lifecycle controls on native functional campaign fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_campaign import _service, _spec

from quantos.contracts.autonomous import P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
from quantos.infrastructure import hosted_lifecycle_probe as probe
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root


@pytest.mark.parametrize("case", probe.HOSTED_LIFECYCLE_CASES)
def test_real_flock_orders_ttl_and_two_native_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    inputs = _inputs(tmp_path / "functional-inputs")
    spec = _spec(inputs).model_copy(
        update={
            "selection_finalization_profile_hash": (
                P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash
            )
        }
    )
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    channel.mkdir()

    def boot(_profile: str, *, protocol_clock, authority_root: Path, channel_root: Path):
        assert authority_root == authority and channel_root == channel
        assert consume_capability_fd(100) == b"S" * 32
        service = _service(
            authority,
            inputs,
            spec,
            clock=[protocol_clock()],
            selection_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
        )
        return SimpleNamespace(application=service)

    values = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": SimpleNamespace(
            business_configuration_hash="b" * 64,
            principals=(SimpleNamespace(capability_fd=100),),
        ),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": SimpleNamespace(campaign=inputs.campaign),
    }

    def hydrate(_profile: str) -> None:
        descriptor = private_memory_fd("functional-lifecycle-service-capability")
        try:
            os.write(descriptor, b"S" * 32)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if descriptor != 100:
                os.dup2(descriptor, 100, inheritable=False)
        finally:
            if descriptor != 100:
                os.close(descriptor)

    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(probe, "hydrate_service_capabilities", hydrate)
    monkeypatch.setattr(probe, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: spec)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda _root, _hash, cls: values[cls.__name__]
    )
    probe.run_lifecycle_probe("d" * 64, case, authority_root=authority, channel_root=channel)
    state = HostedProtocolStore(authority / "protocol").snapshot(spec.campaign_hash)
    facts = probe.HostedCampaignApplicationService.verify_research_facts(state)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    expected_trials = int(case == "submit_before_cancel")
    assert len(facts.reports[-1].trial_hashes) == expected_trials
    assert facts.reports[-1].state == ("EXPIRED" if case.startswith("ttl_") else "CANCELLED")
    assert facts.reports[-1].research_verdict == "NOT_EVALUATED"
    assert facts.reports[-1].selection_report_hash is None
    assert "HOST_INTERNAL_USAGE_UNAVAILABLE" in facts.reports[-1].limitations
    assert state.budget.used_unique_submissions == (2 if case == "ttl_seen_response" else 1)
    assert state.budget.used_requests == 1 + expected_trials
    assert all(item["exit_code"] == 0 for item in observation["process_exits"])
    assert len({item["pid"] for item in observation["process_exits"]}) == len(
        observation["process_exits"]
    )
    for item in observation["process_exits"]:
        record = json.loads((channel / f"process-records/{item['phase']}.json").read_bytes())
        assert record["pid"] == item["pid"] and record["parent_pid"] == os.getpid()
        assert (
            record["execute_calls"] == record["workflow_calls"] == record["network_attempts"] == []
        )
    barrier = observation["race_barrier"]
    if case.startswith(("cancel_", "submit_")):
        assert barrier["winner_native_intent_published"]
        assert barrier["loser_entered_native_flock"]
        assert barrier["inspector_nonblocking_flock_rejected"]
        assert barrier["loser_waitpid_before_release"] == [0, 0]
        receipts = {item.outcome for item in state.receipts}
        assert ("ACCEPTED" in receipts) == bool(expected_trials)
    else:
        assert barrier is None
        assert state.terminals[0].outcome == "EXPIRED"
        assert all(item.outcome in ("REJECTED", "EXHAUSTED") for item in state.receipts)
        assert (
            next(
                item
                for item in state.receipts
                if item.submission_bytes_hash == observation["response_hash"]
            ).reason
            == "REQUEST_EXPIRED"
        )
    recovery = json.loads((channel / "process-records/recovery-1.json").read_bytes())
    repeat = json.loads((channel / "process-records/recovery-2.json").read_bytes())
    assert recovery["result_hash"] == repeat["result_hash"]
    assert raw_inventory(channel / "snapshots/after-recovery/authority") == raw_inventory(authority)
    verify_protocol_root(authority / "protocol", spec.campaign_hash)


def test_unknown_lifecycle_case_rejects_before_loading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown fixed lifecycle"):
        probe.run_lifecycle_probe("d" * 64, "arbitrary-code", authority_root=tmp_path)
