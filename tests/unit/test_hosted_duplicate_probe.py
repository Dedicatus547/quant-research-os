"""Actual fork/barrier with functional inputs; never installed or live qualification."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import NOW, _inputs
from test_hosted_campaign import _service, _spec

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted import HostedSubmissionReceipt
from quantos.infrastructure import hosted_duplicate_probe as probe
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
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
        assert consume_capability_fd(100) == b"S" * 32
        service = _service(authority, inputs, spec)
        service.protocol = HostedProtocolService(
            service.protocol.store,
            clock=protocol_clock,
            verify_inputs=service.verify_registered_inputs,
        )
        return SimpleNamespace(application=service)

    values = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": SimpleNamespace(
            business_configuration_hash="b" * 64,
            principals=(SimpleNamespace(capability_fd=100),),
        ),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
    }
    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)

    def hydrate(_profile: str) -> None:
        descriptor = private_memory_fd("synthetic-test-service-capability")
        try:
            os.write(descriptor, b"S" * 32)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if descriptor != 100:
                os.dup2(descriptor, 100, inheritable=False)
        finally:
            if descriptor != 100:
                os.close(descriptor)

    monkeypatch.setattr(probe, "hydrate_service_capabilities", hydrate)
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


@dataclass(frozen=True)
class _PrivateFixturePrincipal:
    capability_fd: int


def test_private_restart_fd_reuses_ram_after_descriptor_consumption() -> None:
    descriptor = private_memory_fd("synthetic-private-restart-test")
    try:
        os.write(descriptor, b"S" * 32)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.dup2(descriptor, 100, inheritable=False)
        configuration = SimpleNamespace(principals=(_PrivateFixturePrincipal(100),))
        values = probe._capture_restart_capabilities(configuration)
        assert os.lseek(100, 0, os.SEEK_CUR) == 0
        assert consume_capability_fd(100) == b"S" * 32
        for _ in range(3):
            probe._restore_restart_capabilities(values)
            assert os.get_inheritable(100) is False
            assert os.lseek(100, 0, os.SEEK_CUR) == 0
            assert consume_capability_fd(100) == b"S" * 32
            with pytest.raises(OSError):
                os.fstat(100)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("size", (0, 31, 33))
def test_restart_capture_rejects_nonexact_private_descriptor(size: int) -> None:
    descriptor = private_memory_fd("synthetic-invalid-restart-test")
    try:
        os.write(descriptor, b"S" * size)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.dup2(descriptor, 100, inheritable=False)
        with pytest.raises(ArtifactIntegrityError, match="length"):
            probe._capture_restart_capabilities(
                SimpleNamespace(principals=(_PrivateFixturePrincipal(100),))
            )
        assert os.lseek(100, 0, os.SEEK_CUR) == 0
    finally:
        os.close(100)
        os.close(descriptor)


def test_restart_capture_rejects_changed_frozen_private_slot() -> None:
    with pytest.raises(ArtifactIntegrityError, match="descriptor"):
        probe._capture_restart_capabilities(
            SimpleNamespace(principals=(_PrivateFixturePrincipal(101),))
        )
