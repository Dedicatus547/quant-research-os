"""Physical management exits on functional inputs, never deployed qualification."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import NOW, _inputs
from test_hosted_campaign import _service, _spec

from quantos.infrastructure import hosted_fault_probe as probe
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_fault_cases import (
    ADMISSION_FAULT_WINDOWS,
    CORRUPTION_FAULT_WINDOWS,
    MANAGEMENT_FAULT_WINDOWS,
    PROTOCOL_FAULT_WINDOWS,
)
from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root


@pytest.mark.fresh_offline_process
def test_parent_timeout_retains_actual_killed_child_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError

    actual_fork = os.fork
    actual_sleep = time.sleep

    def stalled_child() -> int:
        pid = actual_fork()
        if pid == 0:
            actual_sleep(60)
            os._exit(99)
        return pid

    ticks = iter(range(0, 100_000, 1000))
    monkeypatch.setattr(probe.os, "fork", stalled_child)
    monkeypatch.setattr(
        probe,
        "time",
        SimpleNamespace(
            monotonic=lambda: next(ticks),
            sleep=actual_sleep,
        ),
    )
    with pytest.raises(ArtifactIntegrityError, match="fault child timeout"):
        test_fixed_window_physically_exits_and_two_fresh_boots_are_idempotent(
            tmp_path, monkeypatch, next(iter(PROTOCOL_FAULT_WINDOWS))
        )
    recorded = json.loads((tmp_path / "channel/process-records/crash-exit.json").read_bytes())
    assert recorded["phase"] == "crash" and recorded["exit_code"] == -signal.SIGKILL
    assert recorded["pid"] > os.getpid()
    with pytest.raises(ChildProcessError):
        os.waitpid(recorded["pid"], os.WNOHANG)
    assert not (tmp_path / "channel/negative-observation.json").exists()


@pytest.mark.parametrize(
    "case",
    tuple(PROTOCOL_FAULT_WINDOWS)
    + tuple(ADMISSION_FAULT_WINDOWS)
    + tuple(CORRUPTION_FAULT_WINDOWS),
)
@pytest.mark.fresh_offline_process
def test_fixed_window_physically_exits_and_two_fresh_boots_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
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

    def boot(
        _profile: str,
        *,
        protocol_clock,
        authority_root: Path,
        channel_root: Path,
        verify_journal_entry,
        protocol_fault_hook,
        business_fault_hook,
    ):
        assert authority_root == authority and channel_root == channel
        assert consume_capability_fd(100) == b"S" * 32
        service = _service(authority, inputs, spec, clock=[protocol_clock()])
        # Functional factory only; actual qualification must use production bootstrap.
        service.protocol.store._verify_journal_entry = verify_journal_entry
        service.protocol.store._fault_hook = protocol_fault_hook
        service._fault_hook = business_fault_hook
        if (authority / "protocol/campaigns" / spec.campaign_hash).exists():
            # Production bootstrap rejects malformed authority before constructing
            # its application. Exercise that same store parser in this factory.
            service.protocol.store.snapshot(spec.campaign_hash, recover=True)
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

    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(probe, "hydrate_service_capabilities", hydrate)
    monkeypatch.setattr(probe, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: spec)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda _root, _hash, cls: values[cls.__name__]
    )
    probe.run_fault_probe("d" * 64, case, authority_root=authority, channel_root=channel)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    exits = observation["process_exits"]
    assert [item["phase"] for item in exits] == ["crash", "recovery-1", "recovery-2"]
    corrupt = MANAGEMENT_FAULT_WINDOWS[case].corruption
    assert [item["exit_code"] for item in exits] == ([73, 74, 74] if corrupt else [73, 0, 0])
    assert len({item["pid"] for item in exits}) == 3
    records = {
        phase: json.loads((channel / "process-records" / f"{phase}.json").read_bytes())
        for phase in ("crash", "recovery-1", "recovery-2")
    }
    for item in exits:
        record = records[item["phase"]]
        assert item["pid"] == record["pid"]
        assert record["parent_pid"] == os.getpid()
        assert record["fresh_application_bootstrap"] is True
        assert (
            record["execute_calls"] == record["workflow_calls"] == record["network_attempts"] == []
        )
    assert records["crash"]["point"] == MANAGEMENT_FAULT_WINDOWS[case].point
    assert records["crash"]["occurrence"] == MANAGEMENT_FAULT_WINDOWS[case].occurrence
    assert records["crash"]["inventory"] == raw_inventory(
        channel / "snapshots/crashed/authority"
    ).model_dump(mode="json")
    assert records["recovery-1"]["before_inventory"] == records["crash"]["inventory"]
    assert records["recovery-1"]["result_hash"] == records["recovery-2"]["result_hash"]
    assert records["recovery-2"]["before_inventory"] == records["recovery-2"]["after_inventory"]
    assert raw_inventory(authority) == raw_inventory(channel / "snapshots/recovered/authority")
    assert raw_inventory(authority) == raw_inventory(channel / "snapshots/after/authority")
    if corrupt:
        assert records["recovery-1"]["result_json"]["outcome"] == "REJECTED_CORRUPT_AUTHORITY"
        assert (
            records["recovery-1"]["before_directories"]
            == records["recovery-2"]["after_directories"]
        )
        assert raw_inventory(authority) == raw_inventory(channel / "snapshots/crashed/authority")
    else:
        verify_protocol_root(authority / "protocol", spec.campaign_hash)
    assert observation["qualification_eligibility"] == "NOT_QUALIFIED"


def test_fault_registry_rejects_arbitrary_fault_code_before_loading(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown fixed fault"):
        probe.run_fault_probe("d" * 64, "arbitrary-code", authority_root=tmp_path)


def test_unexpected_failure_locations_do_not_export_messages_paths_or_locals() -> None:
    from quantos.contracts.base import canonical_json_bytes

    message_canary = "do-not-persist-exception-message"
    local_canary = "do-not-persist-frame-locals"

    def fail() -> None:
        retained_in_frame = local_canary
        assert retained_in_frame
        raise RuntimeError(message_canary)

    try:
        fail()
    except RuntimeError as error:
        locations = probe.failure_locations(error)
    assert locations and locations[-1]["function"] == "fail"
    assert all(set(location) == {"module", "function", "line"} for location in locations)
    encoded = canonical_json_bytes(locations)
    assert message_canary.encode() not in encoded and local_canary.encode() not in encoded
    assert __file__.encode() not in encoded


def test_unexpected_failure_locations_are_bounded_and_allow_no_traceback() -> None:
    def nested(depth: int) -> None:
        if depth:
            nested(depth - 1)
        else:
            raise RuntimeError("not exported")

    assert probe.failure_locations(RuntimeError("no frames")) == ()
    try:
        nested(60)
    except RuntimeError as error:
        assert len(probe.failure_locations(error)) == 32
