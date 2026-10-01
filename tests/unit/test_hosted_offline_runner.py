"""Offline runner composition with functional receipts, never scientific/source qualification."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_campaign import _fixture
from test_hosted_replay import _completed

from quantos.artifacts.store import ArtifactError, ArtifactIntegrityError
from quantos.infrastructure import hosted_offline as runner
from quantos.infrastructure.hosted_replay import SavedHostedProtocol
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory

DAMAGE_CASES = (
    None,
    "model_inventory",
    "protocol",
    "source_attestation",
    "network",
    "reuse_execution",
    "missing_execution",
    "changed_source",
    "occupied_target",
)


def _verify_offline_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, damage: str | None
) -> None:
    original = _completed(tmp_path / "functional-original")
    model_source = tmp_path / "model-source"
    shutil.copytree(original.root / "protocol", model_source / "protocol")
    (model_source / "evidence").mkdir()
    authority = tmp_path / "authority"
    authority.mkdir()
    source = authority / ("saved-protocol" if mode == "REEXECUTE" else "protocol")
    shutil.copytree(original.root / "protocol", source)
    source_before = raw_inventory(source)
    model_before = raw_inventory(model_source)
    identities = tuple(
        sorted(
            step.execution_request.execution_identity
            for step in original.service.verify_research_facts(
                original.service.protocol.store.snapshot(original.spec.campaign_hash)
            ).steps
            if step.phase == "COMPLETED" and step.execution_request is not None
        )
    )
    facts = SimpleNamespace(
        execution_identities=identities,
        report=SimpleNamespace(content_hash="f" * 64),
    )
    configurations = {
        "HostedDeploymentProfile": SimpleNamespace(
            configuration_hash="a" * 64,
            projection_inventory_hash="b" * 64,
            model_configuration_hash="c" * 64,
        ),
        "HostedServiceConfiguration": SimpleNamespace(business_configuration_hash="d" * 64),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="e" * 64),
        "HostedFrozenBusinessInputs": SimpleNamespace(campaign=original.inputs.campaign),
        "HostedInstallInventory": object(),
        "HostedLauncherConfiguration": object(),
    }
    mapping = {"/authority": authority, "/saved-evidence": model_source}
    monkeypatch.setattr(runner, "Path", lambda value: mapping.get(str(value), Path(value)))
    monkeypatch.setattr(
        runner, "read_hashed_configuration", lambda _path, _hash, cls: configurations[cls.__name__]
    )
    checked_responses = []

    def verify_response(self, response, **kwargs):
        # Deliberate source-gate double: no model evidence exists in this fixture.
        if damage == "source_attestation":
            raise ArtifactIntegrityError("synthetic attestation rejection")
        checked_responses.append(response.content_hash)

    monkeypatch.setattr(
        runner.TrustedLauncherEvidenceStore, "verify_response_source", verify_response
    )
    monkeypatch.setattr(runner, "hydrate_service_capabilities", lambda _hash: None)
    monkeypatch.setattr(runner, "verify_hosted_business_root", lambda *_args, **_kwargs: facts)
    # Scientific execution and Workflow are explicit composition doubles. The
    # native runner must still reject counts, mode violations and socket attempts.
    monkeypatch.setattr(runner.QuantosResearchExecutionAdapter, "execute", lambda *_args: None)
    monkeypatch.setattr(runner.QlibWorkflowResearchService, "run", lambda *_args, **_kwargs: None)
    service = original.service

    def boot(_hash, **kwargs):
        nonlocal service
        if mode == "REEXECUTE":
            fresh = _fixture(authority, max_trials=2, max_agent_runs=2, max_executions=2)
            service = fresh.service
            service.protocol._clock = kwargs["protocol_clock"]
            service.protocol.store._verify_journal_entry = kwargs["verify_journal_entry"]
        return SimpleNamespace(application=service)

    monkeypatch.setattr(runner, "bootstrap_hosted_service", boot)
    actual_replay = SavedHostedProtocol.run

    def effects():
        if damage == "network":
            socket.create_connection(("192.0.2.1", 9))
        if damage == "reuse_execution" or (mode == "REEXECUTE" and damage != "missing_execution"):
            for identity in identities:
                runner.QuantosResearchExecutionAdapter.execute(
                    object(), SimpleNamespace(execution_identity=identity)
                )
                runner.QlibWorkflowResearchService.run(object(), execution_identity=identity)
        if damage == "changed_source":
            (model_source / "changed-canary").write_bytes(b"unauthorized source mutation")

    if mode == "REEXECUTE":

        def replay(saved, application):
            effects()
            return actual_replay(saved, application)

        monkeypatch.setattr(SavedHostedProtocol, "run", replay)
    else:
        actual_resume = service.resume

        def resume(campaign):
            effects()
            return actual_resume(campaign)

        monkeypatch.setattr(service, "resume", resume)
    if damage == "protocol":
        (source / "unexpected").write_bytes(b"unbound protocol")
    elif damage == "occupied_target":
        (authority / "offline-observation.json").write_bytes(b"old observation")
    inventory_hash = "0" * 64 if damage == "model_inventory" else model_before.content_hash
    reject = (
        damage
        in {
            "model_inventory",
            "protocol",
            "source_attestation",
            "network",
            "changed_source",
            "occupied_target",
        }
        or (mode == "REEXECUTE" and damage == "missing_execution")
        or (mode == "RECEIPT_REUSE" and damage == "reuse_execution")
    )
    if reject:
        with pytest.raises((ArtifactError, HostedQualificationError, ValueError)):
            runner.run_offline("1" * 64, mode, inventory_hash)
    else:
        runner.run_offline("1" * 64, mode, inventory_hash)
        observation = json.loads((authority / "offline-observation.json").read_bytes())
        assert observation["mode"] == mode
        assert observation["qualification_eligibility"] == "NOT_QUALIFIED"
        assert observation["network_attempts"] == []
        assert tuple(sorted(observation["execute_calls"])) == (
            () if mode == "RECEIPT_REUSE" else identities
        )
        assert len(checked_responses) == 2
        assert raw_inventory(source) == source_before
        assert raw_inventory(model_source) == model_before


@pytest.mark.fresh_offline_process
def test_offline_runner_preserves_source_and_requires_mode_specific_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mode in ("RECEIPT_REUSE", "REEXECUTE"):
        for damage in DAMAGE_CASES:
            root = tmp_path / f"{mode}-{damage or 'unchanged'}"
            root.mkdir()
            with monkeypatch.context() as scenario:
                _verify_offline_case(root, scenario, mode, damage)


def test_arbitrary_offline_mode_cannot_load_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "read_hashed_configuration", lambda *_args: pytest.fail("load"))
    with pytest.raises(ValueError, match="unknown fixed offline mode"):
        runner.run_offline("a" * 64, "AUTO", "b" * 64)
