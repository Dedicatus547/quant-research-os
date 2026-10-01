"""Actual fork recovery of finite transport/research budgets on functional inputs.

Configuration and bootstrap are explicit doubles; no installed or Qlib execution
identity or Q06 qualification is implied by these process observations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_budget_cases import _base
from test_hosted_campaign import _service, _spec

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.autonomous import P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
from quantos.infrastructure import hosted_budget_probe as probe
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES, budget_case_specs
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import raw_inventory


def _exercise(root: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    research, transport = budget_case_specs(case, *_base())
    limits = {
        name: getattr(research, name)
        for name in (
            "max_trials",
            "max_distinct_candidates",
            "max_agent_runs",
            "max_executions",
            "max_validation_rounds",
            "max_compute_seconds",
        )
    }
    inputs = _inputs(root / "functional-inputs", **limits)
    # Build fresh campaign/events/selection through the fixture's native governor
    # instead of changing identities after construction. The probe checks the
    # recipe id on its frozen input double; actual service budget remains native.
    bundle = SimpleNamespace(research_budget=research)
    profile_hash = "d" * 64
    spec = _spec(inputs).model_copy(
        update={
            "hosted_budget": transport,
            "selection_finalization_profile_hash": (
                P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash
            ),
        }
    )
    authority, channel = root / "authority", root / "channel"
    authority.mkdir()
    channel.mkdir()
    configuration = SimpleNamespace(
        business_configuration_hash="b" * 64,
        principals=(SimpleNamespace(capability_fd=100),),
    )
    values = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": configuration,
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
    }

    def hydrate(_profile):
        fd = private_memory_fd("synthetic-budget-capability")
        try:
            os.write(fd, b"S" * 32)
            os.lseek(fd, 0, os.SEEK_SET)
            if fd != 100:
                os.dup2(fd, 100, inheritable=False)
        finally:
            if fd != 100:
                os.close(fd)

    def boot(_profile, *, protocol_clock, authority_root, channel_root):
        assert _profile == profile_hash and authority_root == authority and channel_root == channel
        assert consume_capability_fd(100) == b"S" * 32
        service = _service(
            authority, inputs, spec, selection_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
        )
        service.protocol = HostedProtocolService(
            service.protocol.store,
            clock=protocol_clock,
            verify_inputs=service.verify_registered_inputs,
        )
        return SimpleNamespace(application=service)

    monkeypatch.setattr(probe, "hydrate_service_capabilities", hydrate)
    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda _root, _hash, cls: values[cls.__name__]
    )
    monkeypatch.setattr(probe, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: spec)
    probe.run_budget_probe(profile_hash, case, authority_root=authority, channel_root=channel)
    observation = json.loads((channel / "negative-observation.json").read_bytes())
    assert observation["qualification_eligibility"] == "NOT_QUALIFIED"
    assert len(observation["process_exits"]) == 3
    assert len({item["pid"] for item in observation["process_exits"]}) == 3
    assert all(item["exit_code"] == 0 for item in observation["process_exits"])
    states = [
        json.loads((channel / f"process-records/{phase}.json").read_bytes())
        for phase in ("exercise", "recovery-1", "recovery-2")
    ]
    assert all(item["parent_pid"] == os.getpid() for item in states)
    assert len({item["result_json"]["status"]["reason"] for item in states}) == 1
    assert states[0]["result_json"]["status"]["reason"] == HOSTED_BUDGET_CASES[case].expected_reason
    assert all(
        item["execute_calls"] == item["workflow_calls"] == item["network_attempts"] == []
        for item in states
    )
    assert raw_inventory(authority) == raw_inventory(channel / "snapshots/after-exercise/authority")
    state = HostedProtocolStore(authority / "protocol").snapshot(spec.campaign_hash, recover=False)
    assert state.budget.used_requests <= transport.max_requests
    assert state.budget.used_unique_submissions <= transport.max_unique_submissions
    for item in states:
        if item["result_json"]["over_cap_hashes"]:
            assert len(item["result_json"]["over_cap_hashes"]) == 32
            assert len(set(item["result_json"]["over_cap_hashes"])) == 1


@pytest.mark.fresh_offline_process
def test_all_nonexecution_budget_recipes_keep_recovery_and_over_cap_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for case, recipe in HOSTED_BUDGET_CASES.items():
        if recipe.native_execution or recipe.action == "native_candidate":
            continue
        with monkeypatch.context() as scoped:
            _exercise(tmp_path / case, scoped, case)
