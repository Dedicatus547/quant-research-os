"""Read-only predicates for actual manager-origin namespace observations."""

from __future__ import annotations

import errno
from pathlib import Path
from typing import cast

from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import HostedRawInventory
from quantos.infrastructure.hosted_deployment import install_inventory, namespace_command
from quantos.infrastructure.hosted_manager import HostedManagedDeployment
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def _unchanged_prefix(root: Path, inventory: HostedRawInventory) -> None:
    """Later immutable publications may be added; every captured file must still match."""
    actual = {item.logical_path: item for item in raw_inventory(root).files}
    for item in inventory.files:
        _require(actual.get(item.logical_path) == item, "captured immutable source changed")


def _argv(value: object) -> tuple[str, ...]:
    _require(isinstance(value, list), "Q07 manager argv is absent")
    elements = cast(list[object], value)
    _require(all(isinstance(element, str) for element in elements), "Q07 argv types differ")
    return tuple(cast(list[str], elements))


def _file_descriptor(argv: tuple[str, ...], destination: str) -> int:
    matches = [index for index, value in enumerate(argv) if value == destination]
    _require(len(matches) == 1, "Q07 descriptor destination differs")
    index = matches[0]
    _require(index > 1 and argv[index - 2] == "--file", "Q07 private descriptor was not staged")
    descriptor = int(argv[index - 1])
    _require(3 <= descriptor < 1_048_576, "Q07 descriptor is invalid")
    return descriptor


def verify_deployment_security(deployment: HostedManagedDeployment) -> tuple[str, ...]:
    """Recompute Q07 predicates from the original trusted manager root, never host claims.

    This checks the deployed boundary only. The full Q07 case still needs manager-origin
    export binding and the independent HM09 review; no qualification is granted here.
    """
    profile = deployment.profile
    _require(
        install_inventory(deployment.paths.install) == deployment.install
        and deployment.install.content_hash == profile.install_inventory_hash,
        "Q07 installation differs from frozen profile",
    )
    evidence = deployment.root / "evidence"
    data = read_relative(evidence, "deployment-probes.json", max_bytes=65536)
    fact = strict_json_object(data, max_bytes=65536)
    _require(
        fact.get("schema_version") == "hosted-manager-deployment-probe/v1"
        and fact.get("deployment_profile_hash") == profile.content_hash
        and fact.get("hosted_spec_hash") == deployment.spec.content_hash
        and fact.get("install_inventory_hash") == profile.install_inventory_hash
        and fact.get("seccomp_bpf_hash") == profile.seccomp_bpf_hash,
        "Q07 probe deployment bindings differ",
    )
    probe_path = "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_probe.py"
    probe_hash = next(
        item.bytes_hash for item in deployment.install.files if item.relative_path == probe_path
    )
    _require(fact.get("probe_program_hash") == probe_hash, "Q07 probe program differs")
    argv = _argv(fact.get("argv"))
    _require(argv.count("--seccomp") == 1, "Q07 source seccomp was not installed")
    seccomp_fd = int(argv[argv.index("--seccomp") + 1])
    capability_fd = _file_descriptor(argv, "/tmp/hosted-client-capability")
    context_fd = _file_descriptor(argv, "/tmp/hosted-probe.json")
    command = ("/install/python-seeded", "-m", "quantos.infrastructure.hosted_probe")
    expected = namespace_command(
        "host",
        deployment.paths,
        command,
        seccomp_fd=seccomp_fd,
        mount_policy_hash=profile.mount_policy_hash,
    )
    index = expected.index(command[0])
    expected = (
        *expected[:index],
        "--perms",
        "0600",
        "--file",
        str(capability_fd),
        "/tmp/hosted-client-capability",
        "--perms",
        "0600",
        "--file",
        str(context_fd),
        "/tmp/hosted-probe.json",
        *expected[index:],
    )
    _require(argv == expected, "Q07 actual research namespace argv differs")
    before = HostedRawInventory.model_validate(fact["authority_before_inventory"])
    after = HostedRawInventory.model_validate(fact["authority_after_inventory"])
    _require(before == after, "Q07 probe mutated authority")
    _unchanged_prefix(deployment.paths.authority, before)
    paths = {item.logical_path for item in before.files}
    for key, required in (
        ("existing_event_path", "/campaign-events/"),
        ("existing_ledger_path", "/ledger/"),
    ):
        value = fact.get(key)
        _require(
            isinstance(value, str) and required in value and value in paths,
            "Q07 canary did not exist",
        )
    verify_raw_inventory(
        deployment.paths.configuration,
        HostedRawInventory.model_validate(fact["configuration_inventory"]),
    )
    verify_raw_inventory(
        deployment.paths.projection, HostedRawInventory.model_validate(fact["projection_inventory"])
    )
    _require(
        install_inventory(deployment.paths.projection) == deployment.initial_projection
        and deployment.initial_projection.content_hash == profile.projection_inventory_hash,
        "Q07 initial projection differs",
    )
    _unchanged_prefix(evidence, HostedRawInventory.model_validate(fact["trusted_source_inventory"]))
    observation = fact["actual_observation"]
    _require(isinstance(observation, dict), "Q07 observation is absent")
    observation = cast(dict[str, object], observation)
    principal = deployment.configuration.principals[0]
    _require(
        observation.get("uid") == principal.uid and observation.get("gid") == principal.gid,
        "Q07 actual research identity differs",
    )
    _require(
        observation.get("python_executable") == "/install/python-seeded"
        and observation.get("module_path") == "/install/" + probe_path,
        "Q07 actual probe imports/executable differ",
    )
    flags = {
        "isolated": 1,
        "ignore_environment": 1,
        "no_user_site": 1,
        "safe_path": True,
        "hash_randomization": 0,
    }
    _require(observation.get("python_flags") == flags, "Q07 Python initialization differs")
    rows = observation.get("results")
    _require(
        isinstance(rows, list) and all(isinstance(row, dict) for row in cast(list[object], rows)),
        "Q07 rows are absent",
    )
    by_name = {row["name"]: row for row in cast(list[dict[str, object]], rows)}
    _require(len(by_name) == len(cast(list[object], rows)), "Q07 duplicate observations")
    files = (
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
    for name in files:
        row = by_name.get(name, {})
        _require(
            row.get("opened") is False
            and row.get("errno")
            in (errno.ENOENT, errno.EROFS, errno.EACCES, errno.EPERM, errno.ETXTBSY),
            "Q07 forbidden file access was granted or missing",
        )
    for name in (
        "PTRACE_PARENT",
        "PROCESS_VM_PARENT",
        "UNSHARE_ESCAPE",
        "PIDFD_GETFD_ESCAPE",
        "SETNS_ESCAPE",
    ):
        row = by_name.get(name, {})
        _require(
            row.get("return") == -1 and row.get("errno") == errno.EPERM,
            "Q07 escape syscall not denied",
        )
    for name in ("WRONG_CAPABILITY", "WRONG_CAMPAIGN"):
        _require(
            by_name.get(name, {}).get("channel_returned") is False,
            "Q07 unauthorized channel accepted",
        )
    for name in ("AUTHORIZED_QUERY", *(f"CHANNEL_RACE_QUERY_{index}" for index in range(8))):
        _require(
            by_name.get(name, {}).get("channel_returned") is True,
            "Q07 channel control/race query failed",
        )
    for name in (
        "CHANNEL_SYMLINK",
        "CHANNEL_HARDLINK",
        "CHANNEL_FIFO",
        "CHANNEL_UNLINK",
        "CHANNEL_REPLACE",
    ):
        row = by_name.get(name, {})
        _require(
            row.get("changed") is False
            and row.get("errno") in (errno.EROFS, errno.EACCES, errno.EXDEV),
            "Q07 channel path mutation allowed",
        )
    attempts = by_name.get("CHANNEL_CONCURRENT_RACE", {}).get("attempts")
    _require(
        isinstance(attempts, list)
        and len(cast(list[object], attempts)) == 128
        and all(
            value in (errno.EXDEV, errno.EROFS, errno.EACCES)
            for value in cast(list[object], attempts)
        ),
        "Q07 actual concurrent channel race was missing or allowed",
    )
    _require(
        by_name.get("MANAGEMENT_API_ESCAPE", {}).get("closed_without_reply") is True,
        "Q07 unrestricted operation was exposed",
    )
    canary = by_name.get("IMPORT_CANARY", {})
    _require(
        canary.get("files_present") is True
        and canary.get("unisolated_control_found") is True
        and canary.get("isolated_child_found") is False
        and canary.get("found") is False,
        "Q07 actual import isolation control failed",
    )
    _require(
        by_name.get("PROC_CONTENT", {}).get("entries") == []
        and by_name.get("SECCOMP_MODE", {}).get("mode") == 2,
        "Q07 proc/seccomp boundary differs",
    )
    for path in ("/install", "/projection", "/channel", "/proc"):
        _require(
            by_name.get("READ_ONLY_MOUNT:" + path, {}).get("read_only") is True,
            "Q07 mount is writable",
        )
    starts = sorted(path for path in evidence.iterdir() if path.name.startswith("service-start-"))
    _require(bool(starts), "Q07 service origin observation is absent")
    checked = {sha256_bytes(data), probe_hash}
    for path in starts:
        start_data = read_relative(evidence, path.name, max_bytes=65536)
        start = strict_json_object(start_data, max_bytes=65536)
        _require(
            start.get("deployment_profile_hash") == profile.content_hash
            and start.get("hosted_spec_hash") == deployment.spec.content_hash
            and start.get("manager_network_control_connected") is True,
            "Q07 manager service origin differs",
        )
        service_argv = _argv(start.get("argv"))
        service_fd = _file_descriptor(service_argv, "/tmp/hosted-service-capability-0")
        _require(service_argv.count("--info-fd") == 1, "Q07 container information was not captured")
        info_fd = int(service_argv[service_argv.index("--info-fd") + 1])
        _require(info_fd >= 3 and info_fd != service_fd, "Q07 container descriptor differs")
        service_command = (
            "/install/python-seeded",
            "-m",
            "quantos.infrastructure.hosted_service",
            "--profile-hash",
            profile.content_hash,
            "--network-probe-port",
            str(start.get("network_probe_port")),
        )
        _require(
            service_argv
            == namespace_command(
                "service",
                deployment.paths,
                service_command,
                service_capability_fds=(service_fd,),
                info_fd=info_fd,
                mount_policy_hash=profile.mount_policy_hash,
            ),
            "Q07 service namespace argv differs",
        )
        digest = start.get("bootstrap_observation_hash")
        _require(isinstance(digest, str), "Q07 bootstrap hash is absent")
        bootstrap_data = read_relative(evidence, cast(str, digest), max_bytes=65536)
        _require(sha256_bytes(bootstrap_data) == digest, "Q07 bootstrap bytes differ")
        bootstrap = strict_json_object(bootstrap_data, max_bytes=65536)
        _require(
            bootstrap.get("deployment_profile_hash") == profile.content_hash
            and bootstrap.get("python_flags") == flags
            and bootstrap.get("python_hash_seed_environment") == "0"
            and bootstrap.get("python_executable") == "/install/python-seeded"
            and bootstrap.get("module_path")
            == (
                "/install/python/lib/python3.11/site-packages/quantos/infrastructure/"
                "hosted_service.py"
            ),
            "Q07 service frozen initialization differs",
        )
        _require(
            bootstrap.get("uid") == principal.uid and bootstrap.get("gid") == principal.gid,
            "Q07 service identity differs",
        )
        _require(
            bootstrap.get("network_namespace") != start.get("manager_network_namespace")
            and bootstrap.get("network_probe_port") == start.get("network_probe_port"),
            "Q07 service network namespace/control differs",
        )
        network = bootstrap.get("network_probe")
        _require(
            isinstance(network, dict)
            and cast(dict[str, object], network).get("connected") is False
            and cast(dict[str, object], network).get("errno")
            in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH),
            "Q07 service can reach proposal network",
        )
        _require(
            isinstance(bootstrap.get("namespace_identities"), dict)
            and isinstance(bootstrap.get("mountinfo"), str)
            and isinstance(bootstrap.get("process_security"), list),
            "Q07 service namespace attestation incomplete",
        )
        namespaces = cast(dict[str, object], bootstrap["namespace_identities"])
        child_value = start.get("manager_child_observation")
        _require(isinstance(child_value, dict), "Q07 actual manager child observation is absent")
        child = cast(dict[str, object], child_value)
        native_hash = next(
            item.bytes_hash
            for item in deployment.install.files
            if item.relative_path == "python-seeded"
        )
        _require(
            child.get("service_command") == list(service_command)
            and child.get("service_executable_hash") == native_hash
            and child.get("service_namespace_identities") == namespaces
            and all(
                type(child.get(name)) is int and cast(int, child[name]) > 1
                for name in ("wrapper_pid", "init_pid", "service_pid")
            )
            and len({child.get(name) for name in ("wrapper_pid", "init_pid", "service_pid")}) == 3,
            "Q07 actual service child differs from frozen bootstrap",
        )
        child_security_value = child.get("service_process_security")
        _require(isinstance(child_security_value, list), "Q07 external child credentials absent")
        child_security = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in cast(list[str], child_security_value)
        }
        _require(
            child_security.get("CapEff") == "0000000000000000"
            and child_security.get("Uid", "").split() == [str(principal.uid)] * 4
            and child_security.get("Gid", "").split() == [str(principal.gid)] * 4,
            "Q07 external child credentials differ",
        )
        manager_namespaces = start.get("manager_namespace_identities")
        _require(isinstance(manager_namespaces, dict), "Q07 manager namespaces absent")
        for name in ("net", "pid", "mnt", "user"):
            _require(
                isinstance(namespaces.get(name), str)
                and namespaces.get(name) != cast(dict[str, object], manager_namespaces).get(name),
                "Q07 service namespace was inherited",
            )
        security = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in cast(list[str], bootstrap["process_security"])
        }
        _require(
            security.get("CapEff") == "0000000000000000", "Q07 service has effective capabilities"
        )
        mounts = {
            fields[4]: fields[5].split(",")
            for line in cast(str, bootstrap["mountinfo"]).splitlines()
            if len(fields := line.split()) >= 10
        }
        for path in ("/install", "/projection", "/config", "/inputs", "/provenance"):
            _require("ro" in mounts.get(path, []), "Q07 service immutable mount is writable")
        for path in ("/authority", "/channel"):
            _require("rw" in mounts.get(path, []), "Q07 service lacks its authority mount")
        checked.update((sha256_bytes(start_data), sha256_bytes(bootstrap_data)))
    return tuple(sorted(checked))
