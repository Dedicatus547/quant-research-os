"""Manager capture guards with a process double; no syscall/CLI qualification."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_deployment import _policy

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure import hosted_manager as manager
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    HostedNamespacePaths,
    install_inventory,
)
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory
from quantos.security import SecretArtifactRejected


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Process doubles establish capture composition, never a real storage quota.
    monkeypatch.setattr(manager, "storage_checkpoint", lambda *_: None)


def _deployment(root: Path):
    paths = HostedNamespacePaths(
        **{
            name: root / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "configuration",
                "provenance",
                "offline_inputs",
            )
        }
    )
    for path in vars(paths).values():
        path.mkdir(parents=True)
    (root / "evidence").mkdir()
    probe = "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_probe.py"
    program = paths.install / probe
    program.parent.mkdir(parents=True)
    program.write_bytes(b"synthetic probe identity, never executed")
    (paths.projection / "canary").write_bytes(b"immutable projection")
    config_bytes = b'{"synthetic":true}'
    config_hash = sha256_bytes(config_bytes)
    (paths.configuration / f"sha256-{config_hash}.json").write_bytes(config_bytes)
    for logical in (
        "business/campaign/campaign-events/event.json",
        "business/campaign/ledger/snapshot.json",
    ):
        path = paths.authority / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"immutable business canary")
    installed, projected = install_inventory(paths.install), install_inventory(paths.projection)
    descriptor, bpf = manager.source_seccomp_filter()
    os.close(descriptor)
    return SimpleNamespace(
        root=root,
        paths=paths,
        capability=b"c" * 32,
        install=installed,
        initial_projection=projected,
        configuration=SimpleNamespace(content_hash=config_hash, policy=_policy()),
        profile=SimpleNamespace(
            content_hash="a" * 64,
            configuration_hash=config_hash,
            install_inventory_hash=installed.content_hash,
            mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
            seccomp_bpf_hash=sha256_bytes(bpf),
        ),
        bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash="b" * 64)),
        spec=SimpleNamespace(content_hash="d" * 64),
    )


@pytest.mark.parametrize(
    "operation", ("start", "pending", "request-export", "status", "submit", "resume", "cancel")
)
@pytest.mark.parametrize("damage", (None, "exit", "nonobject", "duplicate_keys", "capability"))
def test_restricted_cli_capture_binds_fixed_arguments_and_closes_all_private_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, damage: str | None
) -> None:
    deployment = _deployment(tmp_path)
    calls, descriptors = [], []
    body = b'{"proposal":"synthetic"}' if operation == "submit" else None

    def run(argv, *, pass_fds, **kwargs):
        calls.append(argv)
        descriptors.extend(pass_fds)
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        assert (
            kwargs["timeout"]
            == deployment.configuration.policy.operation_reply_timeout_ms / 1000 + 30
        )
        assert any(os.pread(fd, 32, 0) == deployment.capability for fd in pass_fds)
        if body is not None:
            assert any(os.pread(fd, len(body), 0) == body for fd in pass_fds)
        output = (
            b"[]"
            if damage == "nonobject"
            else b'{"x":1,"x":2}'
            if damage == "duplicate_keys"
            else canonical_json_bytes({"observed": deployment.capability.hex()})
            if damage == "capability"
            else b'{"observed":"synthetic-cli-result"}'
        )
        return subprocess.CompletedProcess(argv, int(damage == "exit"), output, b"")

    monkeypatch.setattr(manager.subprocess, "run", run)
    before = raw_inventory(tmp_path)
    arguments = dict(
        response_bytes=body, request_hash="e" * 64 if operation in ("submit", "cancel") else None
    )
    if damage is None:
        value = manager.restricted_client_call(deployment, operation, **arguments)
        assert value == {"observed": "synthetic-cli-result"}
        argv = calls[0]
        assert "--unshare-all" in argv and "--share-net" in argv
        assert argv[argv.index("quantos.infrastructure.hosted_host") + 1 :][:2] == (
            "hosted",
            operation,
        )
        if operation == "start":
            assert argv[argv.index("--spec") + 1] == deployment.spec.content_hash
        if operation == "request-export":
            assert argv[argv.index("--output") + 1] == "/tmp/hosted-request.json"
        if operation == "submit":
            assert argv[argv.index("--response") + 1] == "/tmp/hosted-response.json"
    else:
        with pytest.raises((ArtifactIntegrityError, SecretArtifactRejected, ValueError)):
            manager.restricted_client_call(deployment, operation, **arguments)
    assert calls and descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert raw_inventory(tmp_path) == before


@pytest.mark.parametrize(
    "operation,kwargs",
    (("exec", {}), ("submit", {}), ("cancel", {}), ("submit", {"request_hash": "e" * 64})),
)
def test_invalid_client_operation_or_missing_frame_never_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kwargs: dict
) -> None:
    deployment = _deployment(tmp_path)
    monkeypatch.setattr(manager.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("launch"))
    before = raw_inventory(tmp_path)
    with pytest.raises(ValueError):
        manager.restricted_client_call(deployment, operation, **kwargs)
    assert before == raw_inventory(tmp_path)


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "exit",
        "framing",
        "schema",
        "authority",
        "configuration",
        "projection",
        "installation",
        "trusted_source",
        "capability",
    ),
)
def test_probe_capture_rejects_side_effects_and_never_promotes_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    deployment = _deployment(tmp_path)
    descriptors = []

    def run(argv, *, pass_fds, **kwargs):
        descriptors.extend(pass_fds)
        assert kwargs["timeout"] == 30
        assert len(pass_fds) == 3
        context = json.loads(os.pread(pass_fds[2], 4096, 0))
        assert context["campaign_hash"] == deployment.bundle.campaign.content_hash
        assert context["event_path"].startswith("/authority/business/")
        assert context["ledger_path"].startswith("/authority/business/")
        if damage in ("authority", "configuration", "projection", "installation", "trusted_source"):
            root = (
                deployment.paths.authority
                if damage == "authority"
                else deployment.paths.configuration
                if damage == "configuration"
                else deployment.paths.projection
                if damage == "projection"
                else deployment.paths.install
                if damage == "installation"
                else deployment.root / "evidence"
            )
            (root / "process-mutation").write_bytes(b"unexpected child write")
        output = canonical_json_bytes(
            {
                "schema_version": "untrusted/v1"
                if damage == "schema"
                else "hosted-deployment-probe-observation/v1",
                "synthetic": True,
                **({"capability": deployment.capability.hex()} if damage == "capability" else {}),
            }
        )
        return subprocess.CompletedProcess(
            argv, int(damage == "exit"), output + (b"" if damage == "framing" else b"\n"), b""
        )

    monkeypatch.setattr(manager.subprocess, "run", run)
    if damage is None:
        encoded = manager.probe_managed_deployment(deployment)
        value = json.loads(encoded)
        assert value["qualification_eligibility"] == "NOT_QUALIFIED"
        assert value["authority_before_inventory"] == value["authority_after_inventory"]
        assert value["actual_observation"]["synthetic"] is True
        assert (tmp_path / "evidence/deployment-probes.json").read_bytes() == encoded
    else:
        with pytest.raises(
            (ArtifactIntegrityError, HostedQualificationError, SecretArtifactRejected)
        ):
            manager.probe_managed_deployment(deployment)
        assert not (tmp_path / "evidence/deployment-probes.json").exists()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
