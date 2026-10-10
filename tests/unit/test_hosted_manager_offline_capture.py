"""Stopped-manager exports and offline argv capture with explicit process doubles.

These synthetic file roots exercise copying and rejection; they grant no installed
source, namespace, live, replay, or qualification evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_hosted_manager_client_capture import _deployment

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_manager as manager
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory
from quantos.security import SecretArtifactRejected


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic stopped-source fixtures never establish a mounted storage quota.
    monkeypatch.setattr(manager, "storage_checkpoint", lambda *_: None)


def _source(deployment):
    roots = {
        "protocol": deployment.paths.authority / "protocol",
        "evidence": deployment.root / "evidence",
        "request-projections": deployment.root / "request-projections",
    }
    for name, root in roots.items():
        root.mkdir(exist_ok=True)
        (root / "canary.json").write_bytes(canonical_json_bytes({"fixture": name}))
    return roots


@pytest.mark.parametrize("damage", (None, "occupied", "running", "secret", "changed_source"))
def test_live_source_export_requires_stopped_service_and_exact_bounded_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    deployment = _deployment(tmp_path / "manager")
    roots = _source(deployment)
    destination = tmp_path / "saved"
    if damage == "occupied":
        destination.mkdir()
    elif damage == "running":
        (deployment.paths.channel / "service.sock").write_bytes(b"fixture")
    elif damage == "secret":
        (roots["protocol"] / "canary.json").write_bytes(deployment.capability)
    elif damage == "changed_source":
        from quantos.infrastructure import hosted_verification as verification

        original = verification.read_relative

        def changed(root, logical, **kwargs):
            data = original(root, logical, **kwargs)
            return data + b"changed" if root == roots["protocol"] else data

        monkeypatch.setattr(verification, "read_relative", changed)
    before = {name: raw_inventory(root) for name, root in roots.items()}
    if damage is None:
        digest = manager.export_live_source(deployment, destination)
        assert raw_inventory(destination).content_hash == digest
        for name, inventory in before.items():
            assert raw_inventory(destination / name) == inventory
        records = list((deployment.root / "evidence").glob("source-export-*.json"))
        assert len(records) == 1
        record = json.loads(records[0].read_bytes())
        assert record["qualification_eligibility"] == "NOT_QUALIFIED"
        assert record["hosted_spec_hash"] == deployment.spec.content_hash
    else:
        with pytest.raises((ArtifactIntegrityError, SecretArtifactRejected)):
            manager.export_live_source(deployment, destination)
        assert not list((deployment.root / "evidence").glob("source-export-*.json"))
    for name in ("protocol", "request-projections"):
        assert raw_inventory(roots[name]) == before[name]


@pytest.mark.parametrize("mode", ("RECEIPT_REUSE", "REEXECUTE"))
@pytest.mark.parametrize(
    "damage",
    (None, "exit", "bad_observation", "changed_source", "running", "wrong_hash", "occupied_target"),
)
def test_offline_manager_retains_original_failure_and_copies_saved_protocol_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, damage: str | None
) -> None:
    deployment = _deployment(tmp_path / "manager")
    source = tmp_path / "saved"
    (source / "protocol").mkdir(parents=True)
    (source / "protocol" / "canary.json").write_bytes(b'{"fixture":true}')
    program = (
        deployment.paths.install
        / "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_offline.py"
    )
    program.write_bytes(b"synthetic offline program identity, never executed")
    deployment.install = install_inventory(deployment.paths.install)
    original = raw_inventory(source)
    target = tmp_path / "reexecute" if mode == "REEXECUTE" else None
    if damage == "running":
        (deployment.paths.channel / "service.sock").write_bytes(b"fixture")
    elif damage == "occupied_target":
        if target is None:
            target = tmp_path / "unpermitted-reuse-target"
        target.mkdir()
    descriptors, calls = [], []

    def run(argv, *, pass_fds, **kwargs):
        descriptors.extend(pass_fds)
        calls.append(argv)
        assert os.pread(pass_fds[0], 32, 0) == deployment.capability
        assert kwargs["timeout"] == 7200
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        assert "--unshare-all" in argv and "--share-net" not in argv
        assert argv[argv.index("--mode") + 1] == mode
        assert argv[argv.index("--source-inventory-hash") + 1] == original.content_hash
        authority = target / "authority" if target is not None else deployment.paths.authority
        if mode == "REEXECUTE":
            assert raw_inventory(authority / "saved-protocol") == raw_inventory(source / "protocol")
        observation = {
            "mode": "WRONG" if damage == "bad_observation" else mode,
            "model_source_inventory_hash": original.content_hash,
            "deployment_profile_hash": deployment.profile.content_hash,
        }
        (authority / "offline-observation.json").write_bytes(canonical_json_bytes(observation))
        if damage == "changed_source":
            (source / "protocol" / "canary.json").write_bytes(b"changed")
        return subprocess.CompletedProcess(argv, int(damage == "exit"))

    monkeypatch.setattr(manager.subprocess, "run", run)
    arguments = dict(mode=mode, target=target)
    digest = "0" * 64 if damage == "wrong_hash" else original.content_hash
    if damage is None:
        result = manager.run_managed_offline(deployment, source, digest, **arguments)
        assert result == (
            target / "authority" if target is not None else deployment.paths.authority
        )
    else:
        with pytest.raises((ArtifactIntegrityError, HostedQualificationError, ValueError)):
            manager.run_managed_offline(deployment, source, digest, **arguments)
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    records = list((deployment.root / "evidence").glob("offline-run-*.json"))
    assert bool(records) == (damage in {None, "exit", "bad_observation"})
    if records:
        record = json.loads(records[0].read_bytes())
        assert record["qualification_eligibility"] == "NOT_QUALIFIED"
        assert record["return_code"] == int(damage == "exit")
    if damage in {"running", "wrong_hash", "occupied_target"}:
        assert calls == []
    if damage != "changed_source":
        assert raw_inventory(source) == original
