"""Bootstrap gate composition with synthetic runtime identities; never OS qualification."""

from __future__ import annotations

import io
import platform
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_campaign import _service, _spec
from test_hosted_deployment import _policy

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted_deployment import HostedClientConfiguration
from quantos.infrastructure import hosted_service as bootstrap
from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES, install_inventory
from quantos.infrastructure.hosted_launcher import EXTRACTION_RULE_BYTES
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "business_factory",
        "input_root",
        "policy",
        "socket",
        "campaign",
        "model_binding",
        "commit",
        "lock_binding",
        "projection",
        "extraction",
        "client",
        "provenance",
        "cli",
        "bwrap",
        "libseccomp",
        "os_inventory",
        "mount_policy",
        "seccomp",
        "os_version",
        "python_flags",
        "python_path",
        "module_path",
        "loader_spec",
        "extra_campaign",
    ),
)
def test_bootstrap_refuses_changed_frozen_bindings_before_channel_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    inputs = _inputs(tmp_path / "functional-inputs")
    spec = _spec(inputs)
    install, projection, provenance, authority, channel = (
        tmp_path / name for name in ("install", "projection", "provenance", "authority", "channel")
    )
    for path in (install, projection, provenance, authority, channel):
        path.mkdir()
    package = install / "python/lib/python3.11/site-packages/quantos"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"# synthetic frozen package\n")
    executable = install / "python/bin/python3"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic executable, never run")
    (install / "codex").write_bytes(b"synthetic CLI, never run")
    (provenance / "uv.lock").write_bytes(b"synthetic lock\n")
    (projection / "canary.json").write_bytes(b'{"synthetic":true}')
    policy = _policy()
    client = HostedClientConfiguration(socket_path="/channel/quantos.sock", policy=policy)
    (install / "hosted-client.json").write_bytes(client.canonical_bytes())
    inventory = install_inventory(install)
    initial = install_inventory(projection)
    profile = SimpleNamespace(
        content_hash=spec.deployment_profile_hash,
        configuration_hash="a" * 64,
        projection_inventory_hash=initial.content_hash,
        install_inventory_hash=inventory.content_hash,
        model_configuration_hash=spec.requested_model_configuration_hash,
        wheel_hash="b" * 64,
        extraction_rule_hash=sha256_bytes(EXTRACTION_RULE_BYTES),
        policy=policy,
        exact_commit="c" * 40,
        lock_hash=sha256_file(provenance / "uv.lock"),
        provenance_inventory_hash=install_inventory(provenance).content_hash,
        cli_binary_hash=sha256_file(install / "codex"),
        bwrap_binary_hash=sha256_file(Path("/usr/bin/bwrap")),
        libseccomp_binary_hash=sha256_file(Path("/lib/x86_64-linux-gnu/libseccomp.so.2").resolve()),
        os_inventory_hash=initial.content_hash,
        mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
        host_proc="FIXED_EXECUTABLE_HINT_READ_ONLY_TMPFS",
        seccomp_bpf_hash="pending",
        operating_system=platform.system(),
        kernel_release=platform.release(),
        libc=" ".join(platform.libc_ver()),
        python_version=platform.python_version(),
        bwrap_version="synthetic-bwrap-version",
        cli_version="synthetic-cli-version",
    )
    loader = SimpleNamespace(
        factory="quantos.application.hosted_inputs:load_hosted_campaign_application",
        input_root="/inputs",
        provenance_workspace="/provenance",
        business_root="/authority/business",
        business_inputs_hash="e" * 64,
    )
    principal = SimpleNamespace(
        capability_fd=100,
        principal="unit",
        host_instance="unit-host",
        uid=1,
        gid=1,
        campaign_hashes=(spec.campaign_hash,),
    )
    config = SimpleNamespace(
        business_configuration_hash="f" * 64,
        application_factory=loader.factory,
        policy=policy,
        configuration_root="/config",
        protocol_root="/authority/protocol",
        business_lock_root="/authority/business-locks",
        socket_path=client.socket_path,
        campaigns=(SimpleNamespace(campaign_hash=spec.campaign_hash),),
        principals=(principal,),
    )
    bundle = SimpleNamespace(
        campaign=inputs.campaign,
        hosted_recipe=SimpleNamespace(
            requested_model_configuration_hash=profile.model_configuration_hash
        ),
        code_provenance=SimpleNamespace(
            commit_hash=profile.exact_commit, lockfile_hash=profile.lock_hash
        ),
    )
    objects = {
        "HostedDeploymentProfile": profile,
        "HostedServiceConfiguration": config,
        "HostedBusinessLoaderConfiguration": loader,
        "HostedFrozenBusinessInputs": bundle,
        "HostedInstallInventory": None,
        "HostedLauncherConfiguration": SimpleNamespace(
            content_hash=profile.model_configuration_hash
        ),
    }

    def configuration(_root, selected_hash, cls):
        if cls.__name__ == "HostedInstallInventory":
            return initial if selected_hash == initial.content_hash else inventory
        return objects[cls.__name__]

    monkeypatch.setattr(bootstrap, "_hashed_configuration", configuration)
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("quantos/__init__.py", (package / "__init__.py").read_bytes())
    monkeypatch.setattr(bootstrap, "_hashed_wheel", lambda *_args: wheel.getvalue())
    monkeypatch.setattr(bootstrap, "system_runtime_inventory", lambda: initial)
    descriptor, filter_bytes = bootstrap.source_seccomp_filter()
    import os

    os.close(descriptor)
    profile.seccomp_bpf_hash = sha256_bytes(filter_bytes)
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            0,
            (
                profile.bwrap_version
                if argv[0] == "/usr/bin/bwrap"
                else f"codex-cli {profile.cli_version}"
            ).encode(),
        ),
    )
    flags = SimpleNamespace(
        isolated=1, ignore_environment=1, no_user_site=1, safe_path=True, hash_randomization=0
    )
    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(flags=flags, executable=str(executable)))
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(bootstrap, "__file__", str(package / "hosted_service.py"))
    monkeypatch.setattr(bootstrap, "consume_capability_fd", lambda _fd: b"c" * 32)
    from quantos.application import hosted_inputs as input_module

    calls = []

    def load(_loader, protocol, lock_root, **kwargs):
        calls.append("load")
        application = _service(authority, inputs, spec)
        if damage == "loader_spec":
            monkeypatch.setattr(
                application,
                "registered_spec",
                lambda _campaign: spec.model_copy(update={"deployment_profile_hash": "0" * 64}),
            )
        return application

    monkeypatch.setattr(input_module, "load_hosted_campaign_application", load)
    monkeypatch.setattr(
        "quantos.contracts.hosted_inputs.derive_hosted_campaign_spec",
        lambda *_args, **_kwargs: spec,
    )
    if damage in ("business_factory", "input_root"):
        setattr(loader, "factory" if damage == "business_factory" else damage, "untrusted")
    elif damage == "policy":
        config.policy = policy.model_copy(update={"max_connections": policy.max_connections + 1})
    elif damage == "socket":
        config.socket_path = "/untrusted/socket"
    elif damage == "campaign":
        config.campaigns = (SimpleNamespace(campaign_hash="0" * 64),)
    elif damage == "model_binding":
        bundle.hosted_recipe.requested_model_configuration_hash = "0" * 64
    elif damage in ("commit", "lock_binding"):
        setattr(
            bundle.code_provenance,
            "commit_hash" if damage == "commit" else "lockfile_hash",
            "0" * (40 if damage == "commit" else 64),
        )
    elif damage == "projection":
        (projection / "untrusted").write_bytes(b"changed")
    elif damage == "client":
        (install / "hosted-client.json").write_bytes(b"changed")
        inventory = install_inventory(install)
        profile.install_inventory_hash = inventory.content_hash
    elif damage in (
        "extraction",
        "provenance",
        "cli",
        "bwrap",
        "libseccomp",
        "os_inventory",
        "mount_policy",
        "seccomp",
    ):
        field = {
            "extraction": "extraction_rule_hash",
            "provenance": "provenance_inventory_hash",
            "cli": "cli_binary_hash",
            "bwrap": "bwrap_binary_hash",
            "libseccomp": "libseccomp_binary_hash",
            "os_inventory": "os_inventory_hash",
            "mount_policy": "mount_policy_hash",
            "seccomp": "seccomp_bpf_hash",
        }[damage]
        setattr(profile, field, "0" * 64)
    elif damage == "os_version":
        profile.python_version = "0.0.0"
    elif damage == "python_flags":
        flags.isolated = 0
    elif damage == "python_path":
        bootstrap.sys.executable = sys.executable
    elif damage == "module_path":
        monkeypatch.setattr(bootstrap, "__file__", __file__)
    elif damage == "extra_campaign":
        (authority / "protocol/campaigns/unregistered").mkdir(parents=True)
    before = raw_inventory(install), raw_inventory(projection), raw_inventory(provenance)
    kwargs = dict(
        configuration_root=tmp_path,
        install_root=install,
        initial_projection_root=projection,
        authority_root=authority,
        provenance_root=provenance,
        input_root=tmp_path,
        channel_root=channel,
    )
    if damage is None:
        service = bootstrap.bootstrap_hosted_service(profile.content_hash, **kwargs)
        assert service.socket_path == channel / "quantos.sock"
        assert (
            not service.ready.is_set()
            and service.application.registered_spec(spec.campaign_hash) == spec
        )
        assert calls == ["load"]
    else:
        with pytest.raises(ArtifactIntegrityError):
            bootstrap.bootstrap_hosted_service(profile.content_hash, **kwargs)
        assert calls == (["load"] if damage == "loader_spec" else [])
    assert not (channel / "quantos.sock").exists()
    assert before == (raw_inventory(install), raw_inventory(projection), raw_inventory(provenance))
