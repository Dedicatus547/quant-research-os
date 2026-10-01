"""Real fork/fsync windows on functional inputs, never deployed qualification."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import _inputs, _proposal
from test_hosted_campaign import _DiskExecution, _spec

from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    HostedCampaignInputs,
)
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.infrastructure import hosted_atomic_probe as probe
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root


@pytest.mark.parametrize("case", tuple(probe.ATOMIC_FAULT_WINDOWS))
@pytest.mark.fresh_offline_process
def test_native_atomic_exit_and_two_fresh_boots_retain_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    inputs = _inputs(tmp_path / "functional-inputs")
    spec = _spec(inputs)
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    authority.mkdir()
    channel.mkdir()

    def boot(
        _profile: str,
        *,
        protocol_clock,
        authority_root: Path,
        channel_root: Path,
        protocol_fault_hook=None,
    ):
        assert authority_root == authority and channel_root == channel
        assert consume_capability_fd(100) == b"S" * 32
        holder: list[HostedCampaignApplicationService] = []
        protocol = HostedProtocolService(
            HostedProtocolStore(authority / "protocol", fault_hook=protocol_fault_hook),
            clock=protocol_clock,
            verify_inputs=lambda value: holder[0].verify_registered_inputs(value),
        )
        service = HostedCampaignApplicationService(
            protocol, business_lock_root=authority / "business-locks"
        )
        holder.append(service)
        orchestrator = inputs.orchestrator(
            authority,
            (_proposal(inputs, 0),),
            execution=_DiskExecution(authority / "executions"),
        )
        service.register_inputs(
            spec, HostedCampaignInputs(orchestrator, inputs.initial_events, lambda _: None)
        )
        if (authority / "protocol/campaigns" / spec.campaign_hash).exists():
            protocol.store.snapshot(spec.campaign_hash, recover=True)
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
        descriptor = private_memory_fd("functional-atomic-service-capability")
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
    probe.run_atomic_probe("d" * 64, case, authority_root=authority, channel_root=channel)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    rejected = probe.ATOMIC_FAULT_WINDOWS[case][1] in ("file_fsynced", "file_linked")
    exits = observation["process_exits"]
    assert [item["exit_code"] for item in exits] == ([73, 74, 74] if rejected else [73, 0, 0])
    assert len({item["pid"] for item in exits}) == 3
    records = {
        phase: json.loads((channel / "process-records" / f"{phase}.json").read_bytes())
        for phase in ("crash", "recovery-1", "recovery-2")
    }
    for exit_fact in exits:
        record = records[exit_fact["phase"]]
        assert record["pid"] == exit_fact["pid"]
        assert record["parent_pid"] == os.getpid()
        assert record["fresh_application_bootstrap"] is True
        assert (
            record["execute_calls"] == record["workflow_calls"] == record["network_attempts"] == []
        )
    assert (
        records["recovery-1"]["before_forensic_inventory"] == records["crash"]["forensic_inventory"]
    )
    assert (
        records["recovery-2"]["before_forensic_inventory"]
        == records["recovery-2"]["after_forensic_inventory"]
    )
    assert records["recovery-1"]["result_hash"] == records["recovery-2"]["result_hash"]
    assert observation["qualification_eligibility"] == "NOT_QUALIFIED"
    for phase in ("crashed", "recovered", "after"):
        facts = json.loads((channel / "phase-forensics" / f"{phase}.json").read_bytes())
        copied = raw_inventory(channel / "snapshots" / phase / "authority")
        assert tuple((f.logical_path, f.sha256, f.size_bytes) for f in copied.files) == tuple(
            (f["logical_path"], f["sha256"], f["size_bytes"]) for f in facts["files"]
        )
    if rejected:
        assert records["recovery-1"]["result_json"]["outcome"] == "REJECTED_ATOMIC_INTERMEDIATE"
        assert (
            records["crash"]["forensic_inventory"]
            == observation["authority_after_forensic_inventory"]
        )
    else:
        verify_protocol_root(authority / "protocol", spec.campaign_hash)


def test_unknown_atomic_window_rejects_before_loading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown fixed atomic"):
        probe.run_atomic_probe("d" * 64, "arbitrary-code", authority_root=tmp_path)
