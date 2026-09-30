"""Management-only frozen deployment construction and restricted client execution."""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, sha256_file
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedCampaignSpec, strict_json_object
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
) -> HostedManagedDeployment:
    """Construct the reviewed B→L→C→I0→D graph before exposing any service/model."""
    provenance = capture_code_provenance(workspace)
    if provenance != bundle.code_provenance:
        raise ArtifactIntegrityError("business authoring differs from clean deployment provenance")
    if root.exists() or root.is_symlink():
        raise ArtifactIntegrityError("deployment staging root already exists")
    if (
        launcher_configuration.content_hash
        != bundle.hosted_recipe.requested_model_configuration_hash
    ):
        raise ArtifactIntegrityError("model configuration differs from frozen business recipe")
    if set(frozen_objects) != {item.logical_path for item in bundle.frozen_byte_objects}:
        raise ArtifactIntegrityError("business input file set differs")
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
            "-Wl,-rpath,$ORIGIN/python/lib",
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
                "compiler_hash": sha256_file(Path("/usr/bin/gcc")),
                "compiler_flags": (
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-lpython3.11",
                    "-Wl,-rpath,$ORIGIN/python/lib",
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
        libseccomp_binary_hash=sha256_file(Path("/lib/x86_64-linux-gnu/libseccomp.so.2")),
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
    os.write(descriptor, data)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def start_managed_service(deployment: HostedManagedDeployment) -> subprocess.Popen[bytes]:
    descriptor = _memory(deployment.capability, "service-capability")
    command = (
        "/install/python-seeded",
        "-m",
        "quantos.infrastructure.hosted_service",
        "--profile-hash",
        deployment.profile.content_hash,
    )
    try:
        process = subprocess.Popen(
            namespace_command(
                "service", deployment.paths, command, service_capability_fds=(descriptor,)
            ),
            pass_fds=(descriptor,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
    finally:
        os.close(descriptor)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ArtifactIntegrityError("frozen service failed before socket readiness")
        if (deployment.paths.channel / "quantos.sock").exists():
            return process
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
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
    if operation not in {"start", "pending", "status", "submit", "resume", "cancel"}:
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
        argv = namespace_command("host", paths, command, seccomp_fd=seccomp_fd)
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
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("restricted host CLI reply is not an object")
        return strict_json_object(
            canonical_json_bytes(cast(dict[str, object], value)), max_bytes=1_052_672
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
