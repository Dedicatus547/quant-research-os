"""Management-only frozen deployment construction and restricted client execution."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import stat
import subprocess
import time
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    opened_directory,
    sha256_file,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedCampaignSpec,
    strict_json_object,
    unique_json_object_pairs,
)
from quantos.contracts.hosted_deployment import (
    HostedCampaignAuthorization,
    HostedChannelPolicy,
    HostedClientConfiguration,
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedPrincipalConfiguration,
    HostedServiceConfiguration,
)
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    HostedNamespacePaths,
    KnownValueGuard,
    freeze_python_install,
    install_inventory,
    namespace_command,
    private_memory_fd,
    source_seccomp_filter,
    system_runtime_inventory,
)
from quantos.infrastructure.hosted_launcher import EXTRACTION_RULE_BYTES


@dataclass(frozen=True)
class HostedManagedDeployment:
    root: Path
    paths: HostedNamespacePaths
    profile: HostedDeploymentProfile
    install: HostedInstallInventory
    initial_projection: HostedInstallInventory
    bundle: HostedFrozenBusinessInputs
    launcher_configuration: HostedLauncherConfiguration
    configuration: HostedServiceConfiguration
    host_instance: str
    capability: bytes = field(repr=False)

    @property
    def spec(self) -> HostedCampaignSpec:
        return derive_hosted_campaign_spec(
            self.bundle, deployment_profile_hash=self.profile.content_hash
        )


def _object(root: Path, value: CanonicalContract) -> None:
    atomic_write_bytes(root / f"sha256-{value.content_hash}.json", value.canonical_bytes())


def verify_wheel_provenance(workspace: Path, wheel: Path) -> None:
    """Every installed project member must be the exact clean checkout's tracked bytes."""
    from quantos.infrastructure.hosted_verification import read_relative

    tracked = (
        subprocess.run(
            ("git", "-C", str(workspace), "ls-files", "-z", "--", "src/quantos"),
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    expected = {
        path.removeprefix("src/"): read_relative(workspace, path) for path in tracked if path
    }
    if not expected:
        raise ArtifactIntegrityError("wheel provenance has no tracked project files")
    with zipfile.ZipFile(wheel) as archive:
        members = [
            member
            for member in archive.infolist()
            if member.filename.startswith("quantos/") and not member.is_dir()
        ]
        if len({member.filename for member in members}) != len(members) or {
            member.filename for member in members
        } != set(expected):
            raise ArtifactIntegrityError("wheel project members differ from exact checkout")
        for member in members:
            if (
                member.file_size != len(expected[member.filename])
                or archive.read(member) != expected[member.filename]
            ):
                raise ArtifactIntegrityError("wheel project bytes differ from exact checkout")


def stage_hosted_deployment(
    root: Path,
    workspace: Path,
    bundle: HostedFrozenBusinessInputs,
    frozen_objects: dict[str, bytes],
    seed_ledger: Path,
    *,
    wheel: Path,
    base_python: Path,
    dependency_site: Path,
    codex_binary: Path,
    launcher_configuration: HostedLauncherConfiguration,
    prepared_root_fd: int | None = None,
) -> HostedManagedDeployment:
    """Construct the reviewed B→L→C→I0→D graph before exposing any service/model."""
    provenance = capture_code_provenance(workspace)
    if provenance != bundle.code_provenance:
        raise ArtifactIntegrityError("business authoring differs from clean deployment provenance")
    verify_wheel_provenance(workspace, wheel)
    if prepared_root_fd is None:
        if root.exists() or root.is_symlink():
            raise ArtifactIntegrityError("deployment staging root already exists")
    else:
        if root != Path("."):
            raise ArtifactIntegrityError("prepared management staging requires its pinned cwd")
        expected = os.fstat(prepared_root_fd)
        with opened_directory(Path(".")) as observed_fd:
            observed = os.fstat(observed_fd)
            if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
                raise ArtifactIntegrityError("prepared management staging inode differs")
        if os.listdir(prepared_root_fd):
            raise ArtifactIntegrityError("prepared management staging requires an empty root")
    if (
        launcher_configuration.content_hash
        != bundle.hosted_recipe.requested_model_configuration_hash
    ):
        raise ArtifactIntegrityError("model configuration differs from frozen business recipe")
    if set(frozen_objects) != {item.logical_path for item in bundle.frozen_byte_objects}:
        raise ArtifactIntegrityError("business input file set differs")
    if prepared_root_fd is None:
        root.mkdir(parents=True, mode=0o700)
    for name in ("inputs", "config", "initial-projection", "authority", "channel", "evidence"):
        (root / name).mkdir(mode=0o700)
    inputs, config = root / "inputs", root / "config"
    _object(inputs, bundle)
    for item in bundle.frozen_byte_objects:
        data = frozen_objects[item.logical_path]
        if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
            raise ArtifactIntegrityError("frozen input bytes differ")
        atomic_write_bytes(inputs / item.logical_path, data)
    for relative in (bundle.snapshot_directory, bundle.qlib_view_directory):
        destination = inputs / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workspace / relative, destination, symlinks=False)
    seed = inputs / bundle.initial_ledger_directory
    seed.mkdir(parents=True)
    for item in bundle.initial_ledger_files:
        data = (seed_ledger / item.logical_path).read_bytes()
        if sha256_bytes(data) != item.sha256 or len(data) != item.size_bytes:
            raise ArtifactIntegrityError("seed Ledger bytes differ")
        atomic_write_bytes(seed / item.logical_path, data)
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--local",
            str(workspace),
            str(root / "provenance"),
        ],
        capture_output=True,
        check=False,
    )
    if clone.returncode:
        raise ArtifactIntegrityError("clean provenance clone failed")
    subprocess.run(
        [
            "git",
            "-C",
            str(root / "provenance"),
            "checkout",
            "--quiet",
            "--detach",
            provenance.commit_hash,
        ],
        check=True,
        capture_output=True,
    )
    if capture_code_provenance(root / "provenance") != provenance:
        raise ArtifactIntegrityError("provenance copy differs from exact source")
    policy = HostedChannelPolicy(
        header_byte_cap=4096,
        response_byte_cap=262144,
        reply_byte_cap=1_052_672,
        io_timeout_ms=10_000,
        operation_reply_timeout_ms=3_600_000,
        max_connections=8,
        max_total_connections=10000,
        listen_backlog=8,
    )
    capability = secrets.token_bytes(32)
    host_instance = "hm-mvp-research-host-v1"
    loader = HostedBusinessLoaderConfiguration(
        business_inputs_hash=bundle.content_hash,
        input_root="/inputs",
        provenance_workspace="/provenance",
        business_root="/authority/business",
    )
    service = HostedServiceConfiguration(
        business_configuration_hash=loader.content_hash,
        policy=policy,
        principals=(
            HostedPrincipalConfiguration(
                principal="hm-mvp-research-principal-v1",
                host_instance=host_instance,
                uid=os.getuid(),
                gid=os.getgid(),
                campaign_hashes=(bundle.campaign.content_hash,),
                capability_fd=100,
            ),
        ),
        campaigns=(HostedCampaignAuthorization(campaign_hash=bundle.campaign.content_hash),),
    )
    _object(config, loader)
    _object(config, service)
    public = HostedClientConfiguration(socket_path=service.socket_path, policy=policy)
    installation = freeze_python_install(
        root / "install",
        wheel=wheel,
        base_python=base_python,
        dependency_site=dependency_site,
        codex_binary=codex_binary,
        client_configuration=public,
    )
    native_source = Path(__file__).with_name("hosted_python.c")
    subprocess.run(
        [
            "/usr/bin/gcc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I" + str(base_python / "include/python3.11"),
            str(native_source),
            "-L" + str(root / "install/python/lib"),
            "-lpython3.11",
            "-Wl,-rpath,/install/python/lib",
            "-o",
            str(root / "install/python-seeded"),
        ],
        check=True,
        capture_output=True,
    )
    atomic_write_bytes(
        root / "install/python-initialization.json",
        canonical_json_bytes(
            {
                "schema_version": "hosted-python-initialization/v1",
                "source_hash": sha256_file(native_source),
                "compiler_hash": sha256_file(Path("/usr/bin/gcc").resolve(strict=True)),
                "compiler_flags": (
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-lpython3.11",
                    "-Wl,-rpath,/install/python/lib",
                ),
                "python_home": "/install/python",
                "initialization": "PYCONFIG_ISOLATED_HASH_SEED_ZERO/v1",
                "required_exec_environment": {"PYTHONHASHSEED": "0"},
                "binary_hash": sha256_file(root / "install/python-seeded"),
            }
        ),
    )
    installation = install_inventory(root / "install")
    _object(config, installation)
    static_bytes = bundle.manifest.canonical_bytes()
    atomic_write_bytes(root / "initial-projection" / bundle.manifest.content_hash, static_bytes)
    initial = install_inventory(root / "initial-projection")
    _object(config, initial)
    wheel_bytes = wheel.read_bytes()
    atomic_write_bytes(config / f"sha256-{sha256_bytes(wheel_bytes)}.whl", wheel_bytes)
    seccomp_fd, bpf = source_seccomp_filter()
    os.close(seccomp_fd)
    profile = HostedDeploymentProfile(
        operating_system=platform.system(),
        kernel_release=platform.release(),
        libc=" ".join(platform.libc_ver()),
        python_version=platform.python_version(),
        exact_commit=provenance.commit_hash,
        lock_hash=provenance.lockfile_hash,
        wheel_hash=sha256_bytes(wheel_bytes),
        install_inventory_hash=installation.content_hash,
        provenance_inventory_hash=install_inventory(root / "provenance").content_hash,
        configuration_hash=service.content_hash,
        projection_inventory_hash=initial.content_hash,
        bwrap_binary_hash=sha256_file(Path("/usr/bin/bwrap")),
        os_inventory_hash=system_runtime_inventory().content_hash,
        mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
        libseccomp_binary_hash=sha256_file(
            Path("/lib/x86_64-linux-gnu/libseccomp.so.2").resolve(strict=True)
        ),
        bwrap_version=subprocess.run(
            ["/usr/bin/bwrap", "--version"],
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip(),
        seccomp_bpf_hash=sha256_bytes(bpf),
        cli_binary_hash=sha256_file(codex_binary),
        model_configuration_hash=launcher_configuration.content_hash,
        extraction_rule_hash=sha256_bytes(EXTRACTION_RULE_BYTES),
        policy=policy,
    )
    _object(config, profile)
    _object(config, launcher_configuration)
    paths = HostedNamespacePaths(
        root / "install",
        root / "initial-projection",
        root / "channel",
        root / "authority",
        config,
        root / "provenance",
        inputs,
    )
    return HostedManagedDeployment(
        root,
        paths,
        profile,
        installation,
        initial,
        bundle,
        launcher_configuration,
        service,
        host_instance,
        capability,
    )


def _memory(data: bytes, name: str) -> int:
    descriptor = private_memory_fd(name)
    try:
        if os.write(descriptor, data) != len(data):
            raise ArtifactIntegrityError("private memory staging write is incomplete")
        os.lseek(descriptor, 0, os.SEEK_SET)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def read_managed_deployment(root: Path, profile_hash: str) -> HostedManagedDeployment:
    """Manager restarts an explicit frozen profile; a new capability remains in memory."""
    from quantos.infrastructure.hosted_service import read_hashed_configuration

    configuration_root = root / "config"
    profile = read_hashed_configuration(configuration_root, profile_hash, HostedDeploymentProfile)
    configuration = read_hashed_configuration(
        configuration_root, profile.configuration_hash, HostedServiceConfiguration
    )
    loader = read_hashed_configuration(
        configuration_root,
        configuration.business_configuration_hash,
        HostedBusinessLoaderConfiguration,
    )
    bundle = read_hashed_configuration(
        root / "inputs", loader.business_inputs_hash, HostedFrozenBusinessInputs
    )
    installation = read_hashed_configuration(
        configuration_root, profile.install_inventory_hash, HostedInstallInventory
    )
    initial = read_hashed_configuration(
        configuration_root, profile.projection_inventory_hash, HostedInstallInventory
    )
    launcher = read_hashed_configuration(
        configuration_root, profile.model_configuration_hash, HostedLauncherConfiguration
    )
    if len(configuration.principals) != 1 or len(configuration.campaigns) != 1:
        raise ArtifactIntegrityError("restarted manager requires the fixed single registration")
    if (
        bundle.code_provenance.commit_hash != profile.exact_commit
        or bundle.code_provenance.lockfile_hash != profile.lock_hash
        or launcher.content_hash != bundle.hosted_recipe.requested_model_configuration_hash
    ):
        raise ArtifactIntegrityError("restarted manager business/deployment binding differs")
    return HostedManagedDeployment(
        root,
        HostedNamespacePaths(
            root / "install",
            root / "initial-projection",
            root / "channel",
            root / "authority",
            configuration_root,
            root / "provenance",
            root / "inputs",
        ),
        profile,
        installation,
        initial,
        bundle,
        launcher,
        configuration,
        configuration.principals[0].host_instance,
        secrets.token_bytes(32),
    )


def stop_managed_service(
    deployment: HostedManagedDeployment, process: subprocess.Popen[bytes]
) -> None:
    """Preserve actual bootstrap output, then reconcile stopped mutable transport files."""
    from quantos.artifacts.store import opened_directory, read_regular_bytes_at

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    guard = KnownValueGuard((deployment.capability,))
    with opened_directory(deployment.paths.channel) as parent:
        for name in os.listdir(parent):
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if name == "bootstrap-observation.json":
                data = read_regular_bytes_at(parent, name, max_bytes=65536)
                guard(data)
                atomic_write_bytes(deployment.root / "evidence" / sha256_bytes(data), data)
                os.unlink(name, dir_fd=parent)
            elif name == "quantos.sock" and stat.S_ISSOCK(metadata.st_mode):
                os.unlink(name, dir_fd=parent)
            else:
                raise ArtifactIntegrityError("stopped channel has an unexpected entry")
        os.fsync(parent)


def start_managed_service(deployment: HostedManagedDeployment) -> subprocess.Popen[bytes]:
    # An old socket/observation must never attest a new child. Stop/forensic cleanup
    # is explicit; starting does not silently remove evidence from a crashed service.
    with opened_directory(deployment.paths.channel) as channel:
        if os.listdir(channel):
            raise ArtifactIntegrityError("service start requires an empty stopped channel")
    descriptor = _memory(deployment.capability, "service-capability")
    info_fd: int | None = None
    listener: socket.socket | None = None
    try:
        info_fd = private_memory_fd("service-container-information")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            control, _ = listener.accept()
            control.close()
        command = (
            "/install/python-seeded",
            "-m",
            "quantos.infrastructure.hosted_service",
            "--profile-hash",
            deployment.profile.content_hash,
            "--network-probe-port",
            str(port),
        )
        argv = namespace_command(
            "service",
            deployment.paths,
            command,
            service_capability_fds=(descriptor,),
            info_fd=info_fd,
            mount_policy_hash=deployment.profile.mount_policy_hash,
        )
        process = subprocess.Popen(
            argv,
            pass_fds=(descriptor, info_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
    except BaseException:
        try:
            if listener is not None:
                listener.close()
        finally:
            if info_fd is not None:
                os.close(info_fd)
        raise
    finally:
        os.close(descriptor)
    try:
        try:
            return _wait_for_managed_service(deployment, process, argv, port, command, info_fd)
        finally:
            try:
                listener.close()
            finally:
                os.close(info_fd)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        raise


def _observe_namespace_child(
    wrapper_pid: int, info_fd: int, command: tuple[str, ...]
) -> dict[str, object]:
    """Read the real child through the manager's proc, never a child-supplied PID."""
    data = os.pread(info_fd, 4097, 0)
    if len(data) > 4096:
        raise ArtifactIntegrityError("container information exceeded its bound")
    # bubblewrap emits pretty JSON, not our canonical contract serialization.
    info = strict_json_object(
        canonical_json_bytes(
            json.loads(data.decode("utf-8"), object_pairs_hook=unique_json_object_pairs)
        ),
        max_bytes=4096,
    )
    init_pid = info.get("child-pid")
    if type(init_pid) is not int or init_pid <= 1:
        raise ArtifactIntegrityError("container manager did not supply a child PID")
    init_status = Path(f"/proc/{init_pid}/status").read_text()
    fields = dict(line.split(":", 1) for line in init_status.splitlines() if ":" in line)
    if int(fields["PPid"].strip()) != wrapper_pid:
        raise ArtifactIntegrityError("container init is not the launched wrapper child")
    children = Path(f"/proc/{init_pid}/task/{init_pid}/children").read_text().split()
    if len(children) != 1 or not children[0].isdecimal():
        raise ArtifactIntegrityError("container did not launch exactly one fixed service")
    child_pid = int(children[0])
    proc = Path(f"/proc/{child_pid}")
    actual_command = tuple(
        part.decode() for part in (proc / "cmdline").read_bytes().split(b"\0") if part
    )
    if actual_command != command:
        raise ArtifactIntegrityError("manager-observed service command differs")
    status = (proc / "status").read_text()
    security = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if int(security["PPid"].strip()) != init_pid:
        raise ArtifactIntegrityError("manager-observed service parent differs")
    # proc's exe link is a kernel reference to the actual running image, not an
    # artifact traversal. Hash the opened image; no environment/memory is read.
    with (proc / "exe").open("rb") as executable:
        executable_hash = hashlib.file_digest(executable, "sha256").hexdigest()
    namespaces = {name: os.readlink(proc / "ns" / name) for name in ("net", "pid", "mnt", "user")}
    for name in ("net", "pid", "mnt"):
        if namespaces[name] != f"{name}:[{info.get(name + '-namespace')}]":
            raise ArtifactIntegrityError("container information and actual namespaces differ")
    return {
        "container_information": info,
        "wrapper_pid": wrapper_pid,
        "init_pid": init_pid,
        "service_pid": child_pid,
        "service_command": actual_command,
        "service_executable_hash": executable_hash,
        "service_namespace_identities": namespaces,
        "service_process_security": [
            line
            for line in status.splitlines()
            if line.startswith(("Uid:", "Gid:", "CapEff:", "NoNewPrivs:", "Seccomp:", "NSpid:"))
        ],
    }


def _wait_for_managed_service(
    deployment: HostedManagedDeployment,
    process: subprocess.Popen[bytes],
    argv: tuple[str, ...],
    port: int,
    command: tuple[str, ...],
    info_fd: int,
) -> subprocess.Popen[bytes]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ArtifactIntegrityError("frozen service failed before socket readiness")
        if (deployment.paths.channel / "quantos.sock").exists():
            from quantos.infrastructure.hosted_verification import read_relative

            bootstrap = read_relative(deployment.paths.channel, "bootstrap-observation.json")
            KnownValueGuard((deployment.capability,))(bootstrap)
            child = _observe_namespace_child(process.pid, info_fd, command)
            atomic_write_bytes(deployment.root / "evidence" / sha256_bytes(bootstrap), bootstrap)
            atomic_write_bytes(
                deployment.root / "evidence" / f"service-start-{sha256_bytes(bootstrap)}.json",
                canonical_json_bytes(
                    {
                        "schema_version": "hosted-manager-service-start/v1",
                        "deployment_profile_hash": deployment.profile.content_hash,
                        "hosted_spec_hash": deployment.spec.content_hash,
                        "argv": argv,
                        "manager_pid": os.getpid(),
                        "manager_network_namespace": os.readlink("/proc/self/ns/net"),
                        "manager_namespace_identities": {
                            name: os.readlink(f"/proc/self/ns/{name}")
                            for name in ("net", "pid", "mnt", "user")
                        },
                        "network_probe_port": port,
                        "manager_network_control_connected": True,
                        "bootstrap_observation_hash": sha256_bytes(bootstrap),
                        "manager_child_observation": child,
                        "qualification_eligibility": "NOT_QUALIFIED",
                    }
                ),
            )
            return process
        time.sleep(0.1)
    raise ArtifactIntegrityError("frozen service readiness timeout")


def restricted_client_call(
    deployment: HostedManagedDeployment,
    operation: str,
    *,
    projection_root: Path | None = None,
    response_bytes: bytes | None = None,
    request_hash: str | None = None,
) -> dict[str, object]:
    """Invoke the installed CLI as the actual restricted research subject."""
    if operation not in {
        "start",
        "pending",
        "request-export",
        "status",
        "submit",
        "resume",
        "cancel",
    }:
        raise ValueError("unsupported fixed host operation")
    arguments = [
        operation,
        "--campaign",
        deployment.bundle.campaign.content_hash,
        "--capability-fd",
        "100",
    ]
    if operation == "start":
        arguments += ["--spec", deployment.spec.content_hash]
    if operation == "request-export":
        arguments += ["--output", "/tmp/hosted-request.json"]
    if operation in {"submit", "cancel"}:
        if request_hash is None:
            raise ValueError("request identity is required")
        arguments += ["--request", request_hash]
    if operation == "submit":
        if response_bytes is None:
            raise ValueError("original response bytes are required")
        arguments += ["--response", "/tmp/hosted-response.json"]
    command = (
        "/install/python/bin/python3",
        "-I",
        "-m",
        "quantos.infrastructure.hosted_host",
        "hosted",
        *arguments,
    )
    paths = replace(deployment.paths, projection=projection_root or deployment.paths.projection)
    seccomp_fd, _ = source_seccomp_filter()
    capability_fd = _memory(deployment.capability, "client-capability")
    descriptors = [seccomp_fd, capability_fd]
    try:
        argv = namespace_command(
            "host",
            paths,
            command,
            seccomp_fd=seccomp_fd,
            mount_policy_hash=deployment.profile.mount_policy_hash,
        )
        insertion = argv.index(command[0])
        extra = ["--perms", "0600", "--file", str(capability_fd), "/tmp/hosted-client-capability"]
        if response_bytes is not None:
            body_fd = _memory(response_bytes, "host-response")
            descriptors.append(body_fd)
            extra += ["--perms", "0600", "--file", str(body_fd), "/tmp/hosted-response.json"]
        argv = (*argv[:insertion], *extra, *argv[insertion:])
        result = subprocess.run(
            argv,
            pass_fds=tuple(descriptors),
            capture_output=True,
            timeout=deployment.configuration.policy.operation_reply_timeout_ms / 1000 + 30,
            env={"PATH": "/usr/bin:/bin"},
        )
        KnownValueGuard((deployment.capability,))(result.stdout)
        if result.returncode:
            raise ArtifactIntegrityError("restricted host CLI operation failed")
        if len(result.stdout) > 1_052_672:
            raise ArtifactIntegrityError("restricted host CLI reply exceeds its byte cap")
        value = json.loads(
            result.stdout.decode("utf-8"), object_pairs_hook=unique_json_object_pairs
        )
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("restricted host CLI reply is not an object")
        return strict_json_object(
            canonical_json_bytes(cast(dict[str, object], value)), max_bytes=1_052_672
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def probe_managed_deployment(deployment: HostedManagedDeployment) -> bytes:
    """Observe actual restricted syscalls and retain safe output outside the host mount."""
    from quantos.infrastructure.hosted_verification import raw_inventory, verify_raw_inventory

    # Non-secret canaries exist in denied mounts. They are deliberately not credentials.
    atomic_write_bytes(deployment.paths.authority / "sealed-canary", b"sealed-source-canary")
    atomic_write_bytes(
        deployment.paths.configuration / "vendor-credential-canary",
        b"non-secret-vendor-credential-canary",
    )
    before = raw_inventory(deployment.paths.authority)
    event_path = next(
        (item.logical_path for item in before.files if "/campaign-events/" in item.logical_path),
        None,
    )
    ledger_path = next(
        (item.logical_path for item in before.files if "/ledger/" in item.logical_path), None
    )
    if event_path is None or ledger_path is None:
        raise ArtifactIntegrityError("actual probe requires existing event and Ledger canaries")
    install_before = install_inventory(deployment.paths.install)
    if (
        install_before != deployment.install
        or install_before.content_hash != deployment.profile.install_inventory_hash
        or install_inventory(deployment.paths.projection) != deployment.initial_projection
        or sha256_file(
            deployment.paths.configuration / f"sha256-{deployment.configuration.content_hash}.json"
        )
        != deployment.profile.configuration_hash
    ):
        raise ArtifactIntegrityError("probe source differs from frozen installation/configuration")
    atomic_write_bytes(
        deployment.root / "evidence/source-canary", b"nonsecret-trusted-source-canary"
    )
    source_before = raw_inventory(deployment.root / "evidence")
    configuration_before = raw_inventory(deployment.paths.configuration)
    projection_before = raw_inventory(deployment.paths.projection)
    source_fd, bpf = source_seccomp_filter()
    if sha256_bytes(bpf) != deployment.profile.seccomp_bpf_hash:
        os.close(source_fd)
        raise ArtifactIntegrityError("probe source seccomp differs from frozen profile")
    capability_fd = _memory(deployment.capability, "probe-capability")
    memory_canary = ctypes.create_string_buffer(b"nonsecret-manager-memory-canary")
    context_fd = _memory(
        canonical_json_bytes(
            {
                "manager_pid": os.getpid(),
                "memory_canary_address": ctypes.addressof(memory_canary),
                "campaign_hash": deployment.bundle.campaign.content_hash,
                "source_root": str(deployment.root),
                "event_path": "/authority/" + event_path,
                "ledger_path": "/authority/" + ledger_path,
            }
        ),
        "probe-context",
    )
    descriptors = (source_fd, capability_fd, context_fd)
    command = ("/install/python-seeded", "-m", "quantos.infrastructure.hosted_probe")
    try:
        argv = namespace_command(
            "host",
            deployment.paths,
            command,
            seccomp_fd=source_fd,
            mount_policy_hash=deployment.profile.mount_policy_hash,
        )
        index = argv.index(command[0])
        argv = (
            *argv[:index],
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
            *argv[index:],
        )
        result = subprocess.run(
            argv,
            pass_fds=descriptors,
            capture_output=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "/untrusted-canary"},
        )
        KnownValueGuard((deployment.capability,))(result.stdout)
        if result.returncode or len(result.stdout) > 65536:
            raise ArtifactIntegrityError("actual restricted deployment probe did not complete")
        if not result.stdout.endswith(b"\n"):
            raise ArtifactIntegrityError("actual deployment probe framing differs")
        observation = strict_json_object(result.stdout[:-1], max_bytes=65536)
        if observation.get("schema_version") != "hosted-deployment-probe-observation/v1":
            raise ArtifactIntegrityError("actual deployment probe returned another schema")
        verify_raw_inventory(deployment.paths.authority, before)
        verify_raw_inventory(deployment.root / "evidence", source_before)
        verify_raw_inventory(deployment.paths.configuration, configuration_before)
        verify_raw_inventory(deployment.paths.projection, projection_before)
        if install_inventory(deployment.paths.install) != install_before:
            raise ArtifactIntegrityError("actual deployment probe changed frozen installation")
        evidence = canonical_json_bytes(
            {
                "schema_version": "hosted-manager-deployment-probe/v1",
                "deployment_profile_hash": deployment.profile.content_hash,
                "hosted_spec_hash": deployment.spec.content_hash,
                "probe_program_hash": next(
                    item.bytes_hash
                    for item in deployment.install.files
                    if item.relative_path
                    == (
                        "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_probe.py"
                    )
                ),
                "authority_before_inventory": before.model_dump(mode="json"),
                "authority_after_inventory": raw_inventory(deployment.paths.authority).model_dump(
                    mode="json"
                ),
                "install_inventory_hash": install_before.content_hash,
                "actual_observation": observation,
                "configuration_inventory": configuration_before.model_dump(mode="json"),
                "projection_inventory": projection_before.model_dump(mode="json"),
                "trusted_source_inventory": source_before.model_dump(mode="json"),
                "argv": argv,
                "seccomp_bpf_hash": sha256_bytes(bpf),
                "manager_network_namespace": os.readlink("/proc/self/ns/net"),
                "existing_event_path": event_path,
                "existing_ledger_path": ledger_path,
                "qualification_eligibility": "NOT_QUALIFIED",
            }
        )
        KnownValueGuard((deployment.capability,))(evidence)
        atomic_write_bytes(deployment.root / "evidence/deployment-probes.json", evidence)
        return evidence
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def export_live_source(deployment: HostedManagedDeployment, destination: Path) -> str:
    """Export the stopped manager's original protocol/capture; never copy research results."""
    from quantos.infrastructure.hosted_verification import (
        raw_inventory,
        read_relative,
        verify_raw_inventory,
    )

    if destination.exists() or destination.is_symlink():
        raise ArtifactIntegrityError("offline source export already exists")
    if any(deployment.paths.channel.iterdir()):
        raise ArtifactIntegrityError("source export requires a stopped reconciled service")
    sources = {
        "protocol": deployment.paths.authority / "protocol",
        "evidence": deployment.root / "evidence",
        "request-projections": deployment.root / "request-projections",
    }
    inventories = {name: raw_inventory(path) for name, path in sources.items()}
    destination.mkdir(parents=True, mode=0o700)
    guard = KnownValueGuard((deployment.capability,))
    for name, source in sources.items():
        target = destination / name
        target.mkdir(mode=0o700)
        for item in inventories[name].files:
            data = read_relative(source, item.logical_path)
            guard(data)
            if len(data) != item.size_bytes or sha256_bytes(data) != item.sha256:
                raise ArtifactIntegrityError("live source changed during manager export")
            atomic_write_bytes(target / item.logical_path, data)
        verify_raw_inventory(source, inventories[name])
        verify_raw_inventory(target, inventories[name])
    inventory = raw_inventory(destination)
    atomic_write_bytes(
        deployment.root / "evidence" / f"source-export-{inventory.content_hash}.json",
        canonical_json_bytes(
            {
                "schema_version": "hosted-manager-source-export/v1",
                "deployment_profile_hash": deployment.profile.content_hash,
                "hosted_spec_hash": deployment.spec.content_hash,
                "source_inventory": inventory.model_dump(mode="json"),
                "source_roots": {
                    name: value.model_dump(mode="json") for name, value in inventories.items()
                },
                "qualification_eligibility": "NOT_QUALIFIED",
            }
        ),
    )
    return inventory.content_hash


def run_managed_offline(
    deployment: HostedManagedDeployment,
    source: Path,
    source_inventory_hash: str,
    *,
    mode: str,
    target: Path | None = None,
) -> Path:
    """Run the installed offline entrypoint in the real network-isolated service namespace."""
    from quantos.infrastructure.hosted_verification import (
        raw_inventory,
        read_relative,
        verify_raw_inventory,
    )

    if mode not in {"RECEIPT_REUSE", "REEXECUTE"}:
        raise ValueError("unknown offline management mode")
    if any(deployment.paths.channel.iterdir()):
        raise ArtifactIntegrityError("offline run requires the live service to be stopped")
    source_before = raw_inventory(source)
    if source_before.content_hash != source_inventory_hash:
        raise ArtifactIntegrityError("offline source differs from explicit inventory")
    paths = deployment.paths
    if mode == "REEXECUTE":
        if target is None or target.exists() or target.is_symlink():
            raise ArtifactIntegrityError("offline reexecution requires a new explicit root")
        target.mkdir(parents=True, mode=0o700)
        for name in ("authority", "channel"):
            (target / name).mkdir(mode=0o700)
        saved = target / "authority/saved-protocol"
        saved.mkdir(mode=0o700)
        inventory = raw_inventory(source / "protocol")
        for item in inventory.files:
            atomic_write_bytes(
                saved / item.logical_path, read_relative(source / "protocol", item.logical_path)
            )
        verify_raw_inventory(saved, inventory)
        paths = replace(paths, authority=target / "authority", channel=target / "channel")
    elif target is not None:
        raise ValueError("receipt reuse must use the original saved authority")
    descriptor = _memory(deployment.capability, "offline-service-capability")
    command = (
        "/install/python-seeded",
        "-m",
        "quantos.infrastructure.hosted_offline",
        "--profile-hash",
        deployment.profile.content_hash,
        "--mode",
        mode,
        "--source-inventory-hash",
        source_inventory_hash,
    )
    authority_before = raw_inventory(paths.authority)
    argv = namespace_command(
        "service",
        paths,
        command,
        service_capability_fds=(descriptor,),
        offline_source_root=source,
        mount_policy_hash=deployment.profile.mount_policy_hash,
    )
    prelaunch = canonical_json_bytes(
        {
            "schema_version": "hosted-manager-offline-prelaunch/v1",
            "invocation_identity": secrets.token_hex(16),
            "deployment_profile_hash": deployment.profile.content_hash,
            "mode": mode,
            "argv": argv,
            "source_root": str(source),
            "source_inventory_hash": source_inventory_hash,
            "authority_root": str(paths.authority),
            "authority_before_inventory": authority_before.model_dump(mode="json"),
            "qualification_eligibility": "NOT_QUALIFIED",
        }
    )
    KnownValueGuard((deployment.capability,))(prelaunch)
    prelaunch_hash = sha256_bytes(prelaunch)
    atomic_write_bytes(
        deployment.root / "evidence" / f"offline-prelaunch-{prelaunch_hash}.json", prelaunch
    )
    try:
        result = subprocess.run(
            argv,
            pass_fds=(descriptor,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=7200,
            env={"PATH": "/usr/bin:/bin"},
        )
    finally:
        os.close(descriptor)
    verify_raw_inventory(source, source_before)
    observation_hash: str | None = None
    if not result.returncode:
        observation = read_relative(paths.authority, "offline-observation.json", max_bytes=65536)
        KnownValueGuard((deployment.capability,))(observation)
        observation_hash = sha256_bytes(observation)
    program_path = "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_offline.py"
    record = canonical_json_bytes(
        {
            "schema_version": "hosted-manager-offline-run/v1",
            "prelaunch_hash": prelaunch_hash,
            "deployment_profile_hash": deployment.profile.content_hash,
            "campaign_hash": deployment.bundle.campaign.content_hash,
            "mode": mode,
            "argv": argv,
            "source_root": str(source),
            "source_inventory": source_before.model_dump(mode="json"),
            "authority_root": str(paths.authority),
            "authority_before_inventory": authority_before.model_dump(mode="json"),
            "authority_after_inventory": raw_inventory(paths.authority).model_dump(mode="json"),
            "return_code": result.returncode,
            "observation_hash": observation_hash,
            "offline_program_hash": next(
                item.bytes_hash
                for item in deployment.install.files
                if item.relative_path == program_path
            ),
            "qualification_eligibility": "NOT_QUALIFIED",
        }
    )
    KnownValueGuard((deployment.capability,))(record)
    atomic_write_bytes(
        deployment.root / "evidence" / ("offline-run-" + sha256_bytes(record) + ".json"), record
    )
    if result.returncode:
        raise ArtifactIntegrityError("installed offline pipeline failed; original roots retained")
    observation = read_relative(paths.authority, "offline-observation.json", max_bytes=65536)
    actual = strict_json_object(observation, max_bytes=65536)
    if (
        actual.get("mode") != mode
        or actual.get("model_source_inventory_hash") != source_inventory_hash
        or actual.get("deployment_profile_hash") != deployment.profile.content_hash
    ):
        raise ArtifactIntegrityError("offline observation differs from manager invocation")
    return paths.authority


def run_managed_negative_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Run one fixed installed transport fixture in a fresh offline namespace.

    It cannot submit to the live authority or read model credentials. The prelaunch,
    kernel process identity and completion remain original management evidence.
    """
    return _run_managed_transport_fixture(deployment, case, "Q03")


def run_managed_admission_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Run a fixed bounded-rejection fixture, unavailable to the research RPC."""
    return _run_managed_transport_fixture(deployment, case, "Q04")


def run_managed_observation_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Run a fixed self-report/source negative fixture without model authentication."""
    return _run_managed_transport_fixture(deployment, case, "Q08")


def run_managed_duplicate_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Capture fixed cross-process duplicate fixtures without exposing test operations."""
    return _run_managed_transport_fixture(deployment, case, "Q02")


def run_managed_fault_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Retain one fixed physical-exit window; this subset does not grant Q05."""
    return _run_managed_transport_fixture(deployment, case, "Q05")


def run_managed_lifecycle_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Capture a fixed offline Q06 lifecycle subset; never award the full Q06 gate."""
    from quantos.infrastructure.hosted_lifecycle_cases import HOSTED_LIFECYCLE_CASES

    if case not in HOSTED_LIFECYCLE_CASES:
        raise ValueError("unknown fixed lifecycle case")
    return _run_managed_transport_fixture(deployment, case, "Q06")


def run_managed_budget_case(deployment: HostedManagedDeployment, case: str) -> Path:
    """Capture one separately frozen finite budget variant; never grant full Q06."""
    from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES

    if case not in HOSTED_BUDGET_CASES:
        raise ValueError("unknown fixed budget case")
    if deployment.bundle.research_budget.budget_id != f"hm-q06-{case}-budget-v1":
        raise ArtifactIntegrityError("budget capture requires a separately frozen variant")
    return _run_managed_transport_fixture(deployment, case, "Q06")


def _run_managed_transport_fixture(
    deployment: HostedManagedDeployment, case: str, family: str
) -> Path:
    from quantos.infrastructure.hosted_atomic_forensics import (
        atomic_forensic_inventory,
        native_registration_publication,
    )
    from quantos.infrastructure.hosted_atomic_snapshot import forensic_byte_view
    from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
    from quantos.infrastructure.hosted_fault_cases import (
        ATOMIC_FAULT_WINDOWS,
        MANAGEMENT_FAULT_WINDOWS,
    )
    from quantos.infrastructure.hosted_fixture_frames import (
        BUSINESS_REJECTION_CASES,
        DUPLICATE_SUBMISSION_CASES,
        HOST_OBSERVATION_CASES,
    )
    from quantos.infrastructure.hosted_lifecycle_cases import HOSTED_LIFECYCLE_CASES
    from quantos.infrastructure.hosted_negative_probe import (
        BOUNDED_REJECTION_CASES,
        NEGATIVE_CASES,
    )
    from quantos.infrastructure.hosted_verification import raw_inventory, read_relative

    allowed = {
        "Q02": DUPLICATE_SUBMISSION_CASES,
        "Q03": NEGATIVE_CASES,
        "Q04": (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES),
        "Q05": (*MANAGEMENT_FAULT_WINDOWS, *ATOMIC_FAULT_WINDOWS),
        "Q06": (*HOSTED_LIFECYCLE_CASES, *HOSTED_BUDGET_CASES),
        "Q08": HOST_OBSERVATION_CASES,
    }
    if family not in allowed or case not in allowed[family]:
        raise ValueError("unknown fixed negative case")
    if (
        family == "Q06"
        and case in HOSTED_BUDGET_CASES
        and deployment.bundle.research_budget.budget_id != f"hm-q06-{case}-budget-v1"
    ):
        raise ArtifactIntegrityError("budget capture requires a separately frozen variant")
    if tuple(deployment.paths.channel.iterdir()):
        raise ArtifactIntegrityError("negative cases require a stopped live service")
    target = deployment.root / "qualification-cases" / family / case
    if target.exists() or target.is_symlink():
        raise ArtifactIntegrityError("negative case requires a new retained root")
    target.mkdir(parents=True, mode=0o700)
    for name in ("authority", "channel"):
        (target / name).mkdir(mode=0o700)
    paths = replace(deployment.paths, authority=target / "authority", channel=target / "channel")
    module = {
        "Q02": "hosted_duplicate_probe",
        "Q03": "hosted_negative_probe",
        "Q04": "hosted_admission_probe",
        "Q05": "hosted_fault_probe",
        "Q06": "hosted_lifecycle_probe",
        "Q08": "hosted_observation_probe",
    }[family]
    atomic = family == "Q05" and case in ATOMIC_FAULT_WINDOWS
    if family == "Q06" and case in HOSTED_BUDGET_CASES:
        module = "hosted_budget_probe"
    if atomic:
        module = "hosted_atomic_probe"
    program_path = f"python/lib/python3.11/site-packages/quantos/infrastructure/{module}.py"
    program_hash = next(
        item.bytes_hash for item in deployment.install.files if item.relative_path == program_path
    )
    guard = KnownValueGuard((deployment.capability,))
    descriptor = _memory(deployment.capability, "negative-service-capability")
    info_fd = private_memory_fd("negative-container-information")
    command = (
        "/install/python-seeded",
        "-m",
        "quantos.infrastructure." + module,
        "--profile-hash",
        deployment.profile.content_hash,
        "--case",
        case,
    )
    process: subprocess.Popen[bytes] | None = None
    child: dict[str, object] | None = None
    prelaunch_hash: str | None = None
    completion_written = False
    try:
        argv = namespace_command(
            "service",
            paths,
            command,
            service_capability_fds=(descriptor,),
            info_fd=info_fd,
            mount_policy_hash=deployment.profile.mount_policy_hash,
        )
        prelaunch = canonical_json_bytes(
            {
                "schema_version": "hosted-manager-negative-prelaunch/v1",
                "invocation_identity": secrets.token_hex(16),
                "case": case,
                "case_family": family,
                "deployment_profile_hash": deployment.profile.content_hash,
                "argv": argv,
                "authority_root": str(paths.authority),
                "authority_before_inventory": raw_inventory(paths.authority).model_dump(
                    mode="json"
                ),
                "program_hash": program_hash,
                "qualification_eligibility": "NOT_QUALIFIED",
            }
        )
        guard(prelaunch)
        prelaunch_hash = sha256_bytes(prelaunch)
        atomic_write_bytes(
            deployment.root / "evidence" / f"negative-prelaunch-{prelaunch_hash}.json", prelaunch
        )
        process = subprocess.Popen(
            argv,
            pass_fds=(descriptor, info_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while process.poll() is None and time.monotonic() < deadline:
            try:
                child = _observe_namespace_child(process.pid, info_fd, command)
                break
            except (ArtifactIntegrityError, OSError, ValueError):
                time.sleep(0.05)
        return_code = process.wait(
            timeout=(
                14400
                if family == "Q05"
                else 7200
                if (
                    family == "Q06"
                    and case in HOSTED_BUDGET_CASES
                    and HOSTED_BUDGET_CASES[case].native_execution
                )
                else 600
                if family in ("Q02", "Q06")
                else 300
            )
        )
        observation_hash: str | None = None
        observation_failure_type: str | None = None
        if return_code == 0:
            try:
                observation = read_relative(
                    paths.channel, "negative-observation.json", max_bytes=16_777_216
                )
                guard(observation)
                observation_hash = sha256_bytes(observation)
            except Exception as error:
                # Keep only a safe type name; arbitrary output/errors may contain
                # credentials. A zero exit without safe evidence is still a failure.
                observation_failure_type = type(error).__name__
        after_facts: dict[str, object] = {}
        if atomic:
            domain, window = ATOMIC_FAULT_WINDOWS[case]
            target_path, expected_bytes = native_registration_publication(deployment.spec, domain)
            facts = atomic_forensic_inventory(
                paths.authority,
                target_path=target_path,
                expected_bytes=expected_bytes,
                window=window,
            )
            after_inventory = forensic_byte_view(facts)
            after_facts["authority_after_forensic_inventory"] = facts.model_dump(mode="json")
        else:
            after_inventory = raw_inventory(paths.authority)
        record = canonical_json_bytes(
            {
                "schema_version": "hosted-manager-negative-run/v1",
                "case": case,
                "case_family": family,
                "deployment_profile_hash": deployment.profile.content_hash,
                "campaign_hash": deployment.bundle.campaign.content_hash,
                "prelaunch_hash": prelaunch_hash,
                "argv": argv,
                "program_hash": program_hash,
                "authority_root": str(paths.authority),
                "authority_after_inventory": after_inventory.model_dump(mode="json"),
                **after_facts,
                "channel_inventory": raw_inventory(paths.channel).model_dump(mode="json"),
                "manager_child_observation": child,
                "manager_namespace_identities": {
                    name: os.readlink(f"/proc/self/ns/{name}")
                    for name in ("net", "pid", "mnt", "user")
                },
                "return_code": return_code,
                "observation_hash": observation_hash,
                "observation_failure_type": observation_failure_type,
                "qualification_eligibility": "NOT_QUALIFIED",
            }
        )
        guard(record)
        atomic_write_bytes(
            deployment.root / "evidence" / f"negative-run-{sha256_bytes(record)}.json", record
        )
        completion_written = True
        if return_code or child is None or observation_hash is None:
            raise ArtifactIntegrityError(
                "negative installed worker failed; original roots retained"
            )
        return target
    except Exception as error:
        if prelaunch_hash is not None and not completion_written:
            # A launch error/timeout has no verified completion. Retain that
            # uncertainty without inventing an exit code or refund.
            failure = canonical_json_bytes(
                {
                    "schema_version": "hosted-manager-negative-invocation-failure/v1",
                    "deployment_profile_hash": deployment.profile.content_hash,
                    "case": case,
                    "case_family": family,
                    "prelaunch_hash": prelaunch_hash,
                    "authority_root": str(paths.authority),
                    "wrapper_pid": process.pid if process is not None else None,
                    "error_type": type(error).__name__,
                    "completion_status": "NOT_OBSERVED",
                    "qualification_eligibility": "NOT_QUALIFIED",
                }
            )
            guard(failure)
            atomic_write_bytes(
                deployment.root
                / "evidence"
                / f"negative-invocation-failure-{sha256_bytes(failure)}.json",
                failure,
            )
        raise
    finally:
        os.close(descriptor)
        os.close(info_fd)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def publish_manager_export(
    deployment: HostedManagedDeployment, mappings: tuple[tuple[str, str], ...]
) -> CanonicalContract:
    """Retain an exact source mapping; qualification is computed by a separate verifier."""
    from quantos.contracts.hosted_qualification import HostedManagerExport, HostedManagerExportFile
    from quantos.infrastructure.hosted_verification import digest_relative

    files: list[HostedManagerExportFile] = []
    for bundle_path, source_path in sorted(mappings):
        digest, length = digest_relative(deployment.root, source_path)
        files.append(
            HostedManagerExportFile(
                bundle_path=bundle_path, source_path=source_path, sha256=digest, size_bytes=length
            )
        )
    export = HostedManagerExport(
        deployment_profile_hash=deployment.profile.content_hash,
        exact_commit=deployment.profile.exact_commit,
        files=tuple(files),
    )
    encoded = export.canonical_bytes()
    # The existing export reader accepts at most16MiB. A complete durable matrix
    # can exceed the guard's per-call4MiB cap, so scan typed records separately
    # (including decoded JSON strings) and all raw bytes in overlapping windows.
    # The generic guard and research-channel limits retain their existing caps.
    if len(encoded) > 16_777_216:
        raise ValueError("manager export byte cap exceeded")
    guard = KnownValueGuard((deployment.capability,))
    guard(canonical_json_bytes(export.model_dump(mode="python", exclude={"files"})))
    for file in export.files:
        guard(file.canonical_bytes())
    window_bytes = 1_048_576
    # register_value's longest representation is six bytes per input byte.
    overlap = 6 * len(deployment.capability)
    for offset in range(0, len(encoded), window_bytes - overlap):
        guard(encoded[offset : offset + window_bytes])
    atomic_write_bytes(deployment.root / "evidence" / export.content_hash, encoded)
    return export


def capture_authority_snapshot(
    deployment: HostedManagedDeployment, logical_path: str
) -> CanonicalContract:
    """Preserve before/after disk facts for a manager-driven scenario, without verdicts."""
    from quantos.contracts.refs import validate_logical_path
    from quantos.infrastructure.hosted_verification import (
        MAX_SINGLE_FILE_BYTES,
        raw_inventory,
        read_relative,
        verify_raw_inventory,
    )

    logical = validate_logical_path(logical_path)
    if not logical.startswith("qualification-cases/"):
        raise ValueError("case snapshot must use the fixed management evidence prefix")
    target = deployment.root / logical
    if target.exists() or target.is_symlink():
        raise ArtifactIntegrityError("case snapshot requires a new absent root")
    before = raw_inventory(deployment.paths.authority)
    with opened_directory(target, create=True):
        pass
    for item in before.files:
        data = read_relative(
            deployment.paths.authority, item.logical_path, max_bytes=MAX_SINGLE_FILE_BYTES
        )
        KnownValueGuard((deployment.capability,), byte_cap=item.size_bytes)(data)
        atomic_write_bytes(target / item.logical_path, data, expected_sha256=item.sha256)
    verify_raw_inventory(deployment.paths.authority, before)
    verify_raw_inventory(target, before)
    atomic_write_bytes(deployment.root / (logical + "-inventory.json"), before.canonical_bytes())
    return before
