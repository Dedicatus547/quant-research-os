"""Tampered management observations; synthetic records never attest deployment."""

from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    HostedNamespacePaths,
    install_inventory,
    namespace_command,
)
from quantos.infrastructure.hosted_security_verification import verify_deployment_security
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


def _observations(tmp_path: Path):
    root = tmp_path / "synthetic-manager"
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
    evidence = root / "evidence"
    evidence.mkdir()
    atomic_write_bytes(evidence / "trusted-source-fixture.json", b"{}")
    probe = "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_probe.py"
    atomic_write_bytes(paths.install / probe, b"synthetic probe identity, never executed")
    atomic_write_bytes(
        paths.install / "python-seeded", b"synthetic native identity, never executed"
    )
    atomic_write_bytes(paths.configuration / "configuration.json", b"{}")
    atomic_write_bytes(paths.projection / "request.json", b"{}")
    atomic_write_bytes(paths.authority / "business/campaign/campaign-events/event.json", b"{}")
    atomic_write_bytes(paths.authority / "business/campaign/ledger/snapshot.json", b"{}")
    installed = install_inventory(paths.install)
    projected = install_inventory(paths.projection)
    profile = SimpleNamespace(
        content_hash="a" * 64,
        install_inventory_hash=installed.content_hash,
        projection_inventory_hash=projected.content_hash,
        seccomp_bpf_hash="b" * 64,
        mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
    )
    principal = SimpleNamespace(uid=501, gid=502)
    deployment = SimpleNamespace(
        root=root,
        paths=paths,
        install=installed,
        initial_projection=projected,
        profile=profile,
        spec=SimpleNamespace(content_hash="c" * 64),
        configuration=SimpleNamespace(principals=(principal,)),
    )
    flags = {
        "isolated": 1,
        "ignore_environment": 1,
        "no_user_site": 1,
        "safe_path": True,
        "hash_randomization": 0,
    }
    namespaces = {name: f"{name}:[20]" for name in ("net", "pid", "mnt", "user")}
    security = ["CapEff:\t0000000000000000", "Uid:\t501 501 501 501", "Gid:\t502 502 502 502"]
    mounts = {
        **{name: "ro" for name in ("/install", "/projection", "/config", "/inputs", "/provenance")},
        "/authority": "rw",
        "/channel": "rw",
    }
    bootstrap = {
        "deployment_profile_hash": profile.content_hash,
        "python_flags": flags,
        "python_hash_seed_environment": "0",
        "python_executable": "/install/python-seeded",
        "module_path": (
            "/install/python/lib/python3.11/site-packages/quantos/infrastructure/hosted_service.py"
        ),
        "uid": principal.uid,
        "gid": principal.gid,
        "network_namespace": namespaces["net"],
        "network_probe_port": 12345,
        "network_probe": {"connected": False, "errno": errno.ENETUNREACH},
        "namespace_identities": namespaces,
        "process_security": security,
        "mountinfo": "\n".join(
            f"10 1 0:1 / {name} {mode} - tmpfs tmpfs {mode}" for name, mode in mounts.items()
        ),
    }
    command = (
        "/install/python-seeded",
        "-m",
        "quantos.infrastructure.hosted_service",
        "--profile-hash",
        profile.content_hash,
        "--network-probe-port",
        "12345",
    )
    start = {
        "deployment_profile_hash": profile.content_hash,
        "hosted_spec_hash": deployment.spec.content_hash,
        "manager_network_control_connected": True,
        "manager_network_namespace": "net:[10]",
        "manager_namespace_identities": {name: f"{name}:[10]" for name in namespaces},
        "network_probe_port": 12345,
        "argv": namespace_command(
            "service",
            paths,
            command,
            service_capability_fds=(7,),
            info_fd=8,
            mount_policy_hash=profile.mount_policy_hash,
        ),
        "manager_child_observation": {
            "service_command": command,
            "service_executable_hash": sha256_bytes(b"synthetic native identity, never executed"),
            "service_namespace_identities": namespaces,
            "wrapper_pid": 100,
            "init_pid": 101,
            "service_pid": 102,
            "service_process_security": security,
        },
    }
    denied = (
        "WRITE_AUTHORITY",
        "WRITE_EVENT",
        "WRITE_LEDGER",
        "WRITE_INSTALL",
        "WRITE_LAUNCHER",
        "WRITE_CLI",
        "WRITE_PYTHON",
        "WRITE_CONFIG",
        "WRITE_PROVENANCE",
        "WRITE_PROJECTION",
        "WRITE_CHANNEL",
        "WRITE_TRUSTED_SOURCE",
        "READ_SEALED",
        "READ_VENDOR_CREDENTIAL",
        "READ_MANAGER_HOME",
        "READ_SERVICE_CAPABILITY",
        "READ_PARENT_FD",
        "READ_PARENT_ROOT",
        "READ_TRUSTED_SOURCE",
        "READ_PROJECTION_PARENT_SEALED",
        "READ_ABSOLUTE_INPUTS",
        "READ_OWN_PROC_FD",
    )
    rows = [{"name": name, "opened": False, "errno": errno.EACCES} for name in denied]
    rows += [
        {"name": name, "return": -1, "errno": errno.EPERM}
        for name in (
            "PTRACE_PARENT",
            "PROCESS_VM_PARENT",
            "UNSHARE_ESCAPE",
            "PIDFD_GETFD_ESCAPE",
            "SETNS_ESCAPE",
        )
    ]
    rows += [
        {"name": name, "channel_returned": False} for name in ("WRONG_CAPABILITY", "WRONG_CAMPAIGN")
    ]
    rows += [
        {"name": name, "channel_returned": True}
        for name in ("AUTHORIZED_QUERY", *(f"CHANNEL_RACE_QUERY_{i}" for i in range(8)))
    ]
    rows += [
        {"name": name, "changed": False, "errno": errno.EROFS}
        for name in (
            "CHANNEL_SYMLINK",
            "CHANNEL_HARDLINK",
            "CHANNEL_FIFO",
            "CHANNEL_UNLINK",
            "CHANNEL_REPLACE",
        )
    ]
    rows += [
        {"name": "CHANNEL_CONCURRENT_RACE", "attempts": [errno.EROFS] * 128},
        {"name": "MANAGEMENT_API_ESCAPE", "closed_without_reply": True},
        {
            "name": "IMPORT_CANARY",
            "files_present": True,
            "unisolated_control_found": True,
            "isolated_child_found": False,
            "found": False,
        },
        {"name": "PROC_CONTENT", "entries": []},
        {"name": "SECCOMP_MODE", "mode": 2},
        *(
            {"name": "READ_ONLY_MOUNT:" + name, "read_only": True}
            for name in ("/install", "/projection", "/channel", "/proc")
        ),
    ]
    argv = namespace_command(
        "host",
        paths,
        ("/install/python-seeded", "-m", "quantos.infrastructure.hosted_probe"),
        seccomp_fd=6,
        mount_policy_hash=profile.mount_policy_hash,
    )
    index = argv.index("/install/python-seeded")
    argv = (
        *argv[:index],
        "--perms",
        "0600",
        "--file",
        "7",
        "/tmp/hosted-client-capability",
        "--perms",
        "0600",
        "--file",
        "8",
        "/tmp/hosted-probe.json",
        *argv[index:],
    )
    inventory = raw_inventory(paths.authority).model_dump(mode="json")
    fact = {
        "schema_version": "hosted-manager-deployment-probe/v1",
        "deployment_profile_hash": profile.content_hash,
        "hosted_spec_hash": deployment.spec.content_hash,
        "install_inventory_hash": installed.content_hash,
        "seccomp_bpf_hash": profile.seccomp_bpf_hash,
        "probe_program_hash": sha256_bytes(b"synthetic probe identity, never executed"),
        "argv": argv,
        "authority_before_inventory": inventory,
        "authority_after_inventory": inventory,
        "existing_event_path": "business/campaign/campaign-events/event.json",
        "existing_ledger_path": "business/campaign/ledger/snapshot.json",
        "configuration_inventory": raw_inventory(paths.configuration).model_dump(mode="json"),
        "projection_inventory": raw_inventory(paths.projection).model_dump(mode="json"),
        "trusted_source_inventory": raw_inventory(evidence).model_dump(mode="json"),
        "actual_observation": {
            "uid": principal.uid,
            "gid": principal.gid,
            "python_executable": "/install/python-seeded",
            "module_path": "/install/" + probe,
            "python_flags": flags,
            "results": rows,
        },
    }
    return deployment, fact, start, bootstrap


@pytest.mark.parametrize(
    "attack",
    (
        None,
        "program",
        "shared_network",
        "uid",
        "capability_reply",
        "authority_write",
        "short_race",
        "management_reply",
        "child_executable",
        "child_pid",
        "capabilities",
        "writable_install",
        "inherited_python",
        "network_connected",
        "configuration_changed",
        "install_changed",
        "authority_changed",
        "trusted_source_changed",
        "service_start_absent",
    ),
)
def test_security_origin_rejects_forged_boundary_observations_without_mutation(
    tmp_path: Path, attack: str | None
) -> None:
    deployment, fact, start, bootstrap = _observations(tmp_path)
    rows = {row["name"]: row for row in fact["actual_observation"]["results"]}
    if attack == "program":
        fact["probe_program_hash"] = "d" * 64
    elif attack == "shared_network":
        start["manager_namespace_identities"]["net"] = bootstrap["namespace_identities"]["net"]
    elif attack == "uid":
        fact["actual_observation"]["uid"] = 999
    elif attack == "capability_reply":
        rows["WRONG_CAPABILITY"]["channel_returned"] = True
    elif attack == "authority_write":
        rows["WRITE_AUTHORITY"]["opened"] = True
    elif attack == "short_race":
        rows["CHANNEL_CONCURRENT_RACE"]["attempts"].pop()
    elif attack == "management_reply":
        rows["MANAGEMENT_API_ESCAPE"]["closed_without_reply"] = False
    elif attack == "child_executable":
        start["manager_child_observation"]["service_executable_hash"] = "e" * 64
    elif attack == "child_pid":
        start["manager_child_observation"]["init_pid"] = 100
    elif attack == "capabilities":
        bootstrap["process_security"] = ["CapEff:\t0000000000000001"]
    elif attack == "writable_install":
        bootstrap["mountinfo"] = bootstrap["mountinfo"].replace("/install ro", "/install rw")
    elif attack == "inherited_python":
        bootstrap["python_flags"] = {**bootstrap["python_flags"], "isolated": 0}
    elif attack == "network_connected":
        bootstrap["network_probe"]["connected"] = True
    elif attack == "configuration_changed":
        (deployment.paths.configuration / "configuration.json").write_bytes(b'{"changed":true}')
    elif attack == "install_changed":
        (deployment.paths.install / "python-seeded").write_bytes(b"substituted interpreter")
    elif attack == "authority_changed":
        (deployment.paths.authority / "business/campaign/ledger/snapshot.json").write_bytes(
            b'{"changed":true}'
        )
    elif attack == "trusted_source_changed":
        (deployment.root / "evidence/trusted-source-fixture.json").write_bytes(b'{"changed":true}')
    bootstrap_bytes = canonical_json_bytes(bootstrap)
    start["bootstrap_observation_hash"] = sha256_bytes(bootstrap_bytes)
    atomic_write_bytes(
        deployment.root / "evidence" / sha256_bytes(bootstrap_bytes), bootstrap_bytes
    )
    start_bytes = canonical_json_bytes(start)
    if attack != "service_start_absent":
        atomic_write_bytes(deployment.root / "evidence/service-start-fixture.json", start_bytes)
    fact_bytes = canonical_json_bytes(fact)
    atomic_write_bytes(deployment.root / "evidence/deployment-probes.json", fact_bytes)
    before = raw_inventory(deployment.root)
    if attack is None:
        checked = verify_deployment_security(deployment)
        assert {
            sha256_bytes(fact_bytes),
            sha256_bytes(start_bytes),
            sha256_bytes(bootstrap_bytes),
        } <= set(checked)
    else:
        with pytest.raises(HostedQualificationError):
            verify_deployment_security(deployment)
    assert raw_inventory(deployment.root) == before
