"""Management-only frozen installs, projections and Linux namespace construction."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import shutil
import stat
import sys
import zipfile
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import quote

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    atomic_write_bytes_at,
    opened_directory,
    read_regular_bytes_at,
    regular_tree_files,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedAgentRequest, HostedCampaignSpec
from quantos.contracts.hosted_deployment import (
    HostedClientConfiguration,
    HostedDeploymentProfile,
    HostedFileIdentity,
    HostedInstallInventory,
    HostedProjectionFact,
)
from quantos.security import SecretArtifactRejected


class KnownValueGuard:
    """Reject known sensitive memory values before immutable publication; never logs values."""

    def __init__(self, values: Iterable[bytes], *, byte_cap: int = 4_194_304) -> None:
        self._variants: tuple[bytes, ...] = ()
        self._byte_cap = byte_cap
        for value in values:
            self.register_value(value)

    def register_value(self, value: bytes) -> None:
        """Manager-only in-memory registration before any capture may be persisted."""
        if not 16 <= len(value) <= 4096:
            raise ValueError("known sensitive values must have bounded entropy material")
        variants: set[bytes] = {value, value.hex().encode(), value.hex().upper().encode()}
        variants.update((base64.b64encode(value), base64.urlsafe_b64encode(value)))
        variants.update(x.rstrip(b"=") for x in tuple(variants))
        variants.update(
            (
                b"".join(f"%{x:02X}".encode() for x in value),
                b"".join(f"%{x:02x}".encode() for x in value),
                b"".join(f"\\u{x:04x}".encode() for x in value),
                b"".join(f"\\u{x:04X}".encode() for x in value),
            )
        )
        with suppress(UnicodeError):
            variants.add(quote(value.decode("utf-8"), safe="").encode())
        self._variants = tuple(set(self._variants).union(variants))

    def __repr__(self) -> str:
        return "KnownValueGuard(REDACTED)"

    def __call__(self, data: bytes) -> None:
        if len(data) > self._byte_cap:
            raise ValueError("known-value scan byte cap exceeded")
        if any(value in data for value in self._variants):
            self._reject()
        try:
            value: object = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            return
        self._visit(value, 0)

    def _visit(self, value: object, depth: int) -> None:
        if depth > 64:
            raise ValueError("known-value scan nesting cap exceeded")
        if isinstance(value, str):
            if any(item in value.encode("utf-8") for item in self._variants):
                self._reject()
        elif isinstance(value, dict):
            mapping = cast(dict[str, object], value)
            for key, item in mapping.items():
                self._visit(key, depth + 1)
                self._visit(item, depth + 1)
        elif isinstance(value, list):
            for item in cast(list[object], value):
                self._visit(item, depth + 1)

    @staticmethod
    def _reject() -> None:
        raise SecretArtifactRejected(
            file_name="hosted-memory-value.json",
            json_path="$",
            rule="KNOWN_SENSITIVE_MEMORY_VALUE",
            value_classification="SENSITIVE_VALUE",
        )


def install_inventory(root: Path) -> HostedInstallInventory:
    files = regular_tree_files(root)
    entries: list[HostedFileIdentity] = []
    for path in files:
        info = path.lstat()
        if info.st_nlink != 1:
            raise ArtifactIntegrityError("installation contains a hard-link alias")
        entries.append(
            HostedFileIdentity(
                relative_path=path.relative_to(root).as_posix(),
                bytes_hash=sha256_file(path),
                size_bytes=info.st_size,
                mode=stat.S_IMODE(info.st_mode),
            )
        )
    return HostedInstallInventory(files=tuple(sorted(entries, key=lambda x: x.relative_path)))


def verify_install(root: Path, expected: HostedInstallInventory) -> None:
    if install_inventory(root).canonical_bytes() != expected.canonical_bytes():
        raise ArtifactIntegrityError("frozen installation inventory changed")


def freeze_python_install(
    destination: Path,
    *,
    wheel: Path,
    base_python: Path,
    dependency_site: Path,
    codex_binary: Path,
    client_configuration: HostedClientConfiguration,
) -> HostedInstallInventory:
    """Freeze a Python prefix and installed dependencies; never imports editable source.

    The manager supplies an already lock-verified dependency installation. No download,
    dependency resolution or acquisition occurs here. Actual inventory is authoritative.
    """
    if destination.exists():
        raise ArtifactIntegrityError("frozen installation destination already exists")
    if sys.version_info[:2] != (3, 11):
        raise ValueError("QuantOS frozen installation requires Python 3.11 manager")
    python_root = destination / "python"
    shutil.copytree(base_python, python_root, symlinks=False)
    site = python_root / "lib/python3.11/site-packages"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for source in sorted(dependency_site.iterdir()):
        # No pth/import hooks or editable QuantOS distribution may enter execution.
        name = source.name
        if name.endswith(".pth") or name.startswith(
            ("quantos", "_quant_research_os", "quant_research_os")
        ):
            continue
        target = site / name
        if source.is_dir():
            shutil.copytree(source, target, symlinks=False)
        else:
            shutil.copy2(source, target, follow_symlinks=True)
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            name = Path(entry.filename)
            if name.is_absolute() or ".." in name.parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise ArtifactIntegrityError("wheel contains unsafe member")
            archive.extract(entry, site)
    if not (site / "quantos/__init__.py").is_file():
        raise ArtifactIntegrityError("wheel does not contain QuantOS installation")
    if client_configuration.socket_path != "/channel/quantos.sock":
        raise ArtifactIntegrityError("public hosted client configuration escaped fixed channel")
    shutil.copy2(codex_binary, destination / "codex")
    atomic_write_bytes(destination / "hosted-client.json", client_configuration.canonical_bytes())
    return install_inventory(destination)


def export_projection(
    root: Path,
    request: HostedAgentRequest,
    objects: dict[str, bytes],
    *,
    guard: KnownValueGuard,
) -> HostedInstallInventory:
    """Publish exactly the request's allowed hash objects, never arbitrary paths or sealed data."""
    if tuple(sorted(objects)) != request.projection_object_hashes:
        raise ArtifactIntegrityError("projection objects disagree with frozen allowlist")
    with opened_directory(root, create=True) as directory_fd:
        for digest, data in objects.items():
            if sha256_bytes(data) != digest:
                raise ArtifactIntegrityError("projection object hash mismatch")
            guard(data)
            atomic_write_bytes_at(directory_fd, digest, data)
        guard(request.canonical_bytes())
        atomic_write_bytes_at(directory_fd, request.content_hash, request.canonical_bytes())
    inventory = install_inventory(root)
    if {x.relative_path for x in inventory.files} != {*objects, request.content_hash}:
        raise ArtifactIntegrityError("projection root contains unapproved objects")
    return inventory


class HostedProjectionObjectSource(Protocol):
    def projection_object_bytes(self, campaign_hash: str, object_hash: str) -> bytes: ...


def export_registered_request_projection(
    root: Path,
    request: HostedAgentRequest,
    source: HostedProjectionObjectSource,
    *,
    guard: KnownValueGuard,
) -> HostedInstallInventory:
    """Manager exports only HM04's pending R context and proposal schema bytes."""
    if set(request.projection_object_hashes) != {
        request.context_pack_hash,
        request.proposal_schema_hash,
    }:
        raise ArtifactIntegrityError("request projection is not the fixed context/schema pair")
    objects = {
        digest: source.projection_object_bytes(request.campaign_hash, digest)
        for digest in request.projection_object_hashes
    }
    return export_projection(root, request, objects, guard=guard)


def read_projection(root: Path, digest: str, *, max_bytes: int) -> bytes:
    if len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
        raise ArtifactIntegrityError("projection requires an explicit SHA-256 identity")
    with opened_directory(root) as directory_fd:
        data = read_regular_bytes_at(directory_fd, digest, max_bytes=max_bytes)
    if sha256_bytes(data) != digest:
        raise ArtifactIntegrityError("projection object changed")
    return data


def verify_projection_fact(
    fact: HostedProjectionFact,
    *,
    request: HostedAgentRequest,
    spec: HostedCampaignSpec,
    profile: HostedDeploymentProfile,
    initial_inventory: HostedInstallInventory,
    projection_root: Path,
) -> HostedInstallInventory:
    """Re-read every actual mounted byte and the exact request/object allowlist."""
    if (
        fact.source != "TRUSTED_PROJECTION_MANAGER"
        or fact.phase != "PRE_LAUNCH"
        or fact.campaign_hash != request.campaign_hash
        or fact.hosted_spec_hash != request.hosted_spec_hash
        or fact.hosted_spec_hash != spec.content_hash
        or spec.deployment_profile_hash != profile.content_hash
        or fact.deployment_profile_hash != profile.content_hash
        or fact.request_hash != request.content_hash
        or fact.initial_projection_inventory_hash != initial_inventory.content_hash
        or fact.initial_projection_inventory_hash != profile.projection_inventory_hash
        or profile.content_hash not in request.input_hashes
    ):
        raise ArtifactIntegrityError("pre-launch projection fact binding invalid")
    actual = install_inventory(projection_root)
    if actual.content_hash != fact.projection_inventory_hash:
        raise ArtifactIntegrityError("pre-launch projection inventory changed")
    if {x.relative_path for x in actual.files} != {
        *request.projection_object_hashes,
        request.content_hash,
    }:
        raise ArtifactIntegrityError("pre-launch projection object set disagrees")
    if (
        read_projection(projection_root, request.content_hash, max_bytes=request.max_request_bytes)
        != request.canonical_bytes()
    ):
        raise ArtifactIntegrityError("pre-launch projection request bytes changed")
    for digest in request.projection_object_hashes:
        read_projection(projection_root, digest, max_bytes=request.max_request_bytes)
    return actual


def publish_projection_fact(
    request: HostedAgentRequest,
    spec: HostedCampaignSpec,
    *,
    profile: HostedDeploymentProfile,
    initial_inventory: HostedInstallInventory,
    projection_root: Path,
    host_instance: str,
    publish_bytes: Callable[[bytes], str],
) -> HostedProjectionFact:
    """Manager only: validate the complete Ii and fsync Pi before any model launch."""
    actual = install_inventory(projection_root)
    fact = HostedProjectionFact(
        campaign_hash=request.campaign_hash,
        hosted_spec_hash=request.hosted_spec_hash,
        deployment_profile_hash=profile.content_hash,
        request_hash=request.content_hash,
        host_instance=host_instance,
        initial_projection_inventory_hash=initial_inventory.content_hash,
        projection_inventory_hash=actual.content_hash,
    )
    verify_projection_fact(
        fact,
        request=request,
        spec=spec,
        profile=profile,
        initial_inventory=initial_inventory,
        projection_root=projection_root,
    )
    if publish_bytes(fact.canonical_bytes()) != fact.content_hash:
        raise ArtifactIntegrityError("pre-launch fact publication mismatch")
    return fact


DENIED_SOURCE_SYSCALLS = (
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "pidfd_getfd",
    "kcmp",
    "unshare",
    "setns",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "open_by_handle_at",
    "name_to_handle_at",
    "fsopen",
    "fsconfig",
    "fsmount",
    "open_tree",
    "move_mount",
    "mount_setattr",
    "bpf",
    "perf_event_open",
    "userfaultfd",
)

SYSTEM_RUNTIME_PATHS = (
    "/usr/bin/bwrap",
    "/usr/bin/git",
    "/usr/bin/env",
    "/usr/bin/sh",
    "/lib/x86_64-linux-gnu/libc.so.6",
    "/lib/x86_64-linux-gnu/libseccomp.so.2",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/ssl/certs/ca-certificates.crt",
)
LEGACY_MOUNT_POLICY_BYTES = canonical_json_bytes(
    {
        "schema_version": "hosted-mount-policy/v1",
        "service": (
            "ro-install",
            "ro-config",
            "ro-provenance",
            "ro-inputs",
            "rw-authority",
            "rw-channel",
            "private-proc",
            "private-tmp",
            "offline-management-source-ro-/saved-evidence",
            "unshared-network",
        ),
        "host": (
            "ro-install",
            "ro-projection",
            "ro-channel",
            "empty-ro-proc",
            "private-tmp",
            "shared-proposal-network",
            "fixed-source-seccomp",
            "ro-dns-and-ca-bundle",
        ),
        "system_ro": ("/usr", "/lib", "/lib64"),
    }
)
MOUNT_POLICY_BYTES = canonical_json_bytes(
    {
        **json.loads(LEGACY_MOUNT_POLICY_BYTES),
        "schema_version": "hosted-mount-policy/v2",
        "service_bin_alias": {"/bin": "/usr/bin"},
        "service_environment": {"MLFLOW_DISABLE_TELEMETRY": "true"},
    }
)


def system_runtime_inventory() -> HostedInstallInventory:
    entries: list[HostedFileIdentity] = []
    for logical in SYSTEM_RUNTIME_PATHS:
        path = Path(logical).resolve(strict=True)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactIntegrityError("fixed system runtime path is not regular")
        entries.append(
            HostedFileIdentity(
                relative_path=logical.lstrip("/"),
                bytes_hash=sha256_file(path),
                size_bytes=info.st_size,
                mode=stat.S_IMODE(info.st_mode),
            )
        )
    return HostedInstallInventory(files=tuple(sorted(entries, key=lambda x: x.relative_path)))


NAMESPACE_CLONE_FLAGS = (
    0x00020000,
    0x02000000,
    0x04000000,
    0x08000000,
    0x10000000,
    0x20000000,
    0x40000000,
)


class _ArgumentComparison(ctypes.Structure):
    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def private_memory_fd(name: str) -> int:
    """libc memfd works with standalone Python builds lacking os.memfd_create."""
    library = ctypes.CDLL(None, use_errno=True)
    library.memfd_create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    library.memfd_create.restype = ctypes.c_int
    descriptor = library.memfd_create(name.encode("ascii"), 1)  # MFD_CLOEXEC
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "private memory descriptor unavailable")
    return descriptor


def source_seccomp_filter() -> tuple[int, bytes]:
    """Return a private memory fd/BPF for the frozen Linux x86_64 host boundary."""
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("isolated service supports Linux x86_64 only")
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("source seccomp initialization failed")
    fd = private_memory_fd("hosted-source-filter")
    try:
        for name in DENIED_SOURCE_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or library.seccomp_rule_add(context, 0x00050001, number, 0) != 0:
                raise RuntimeError("required source syscall rule unavailable")
        number = library.seccomp_syscall_resolve_name(b"clone3")
        if number < 0 or library.seccomp_rule_add(context, 0x00050026, number, 0) != 0:
            raise RuntimeError("source clone3 fallback unavailable")
        clone = library.seccomp_syscall_resolve_name(b"clone")
        for flag in NAMESPACE_CLONE_FLAGS:
            if (
                library.seccomp_rule_add(
                    context, 0x00050001, clone, 1, _ArgumentComparison(0, 7, flag, flag)
                )
                != 0
            ):
                raise RuntimeError("source namespace rule unavailable")
        if library.seccomp_export_bpf(context, fd) != 0:
            raise RuntimeError("source seccomp export failed")
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, 1_048_576)
        os.lseek(fd, 0, os.SEEK_SET)
        return fd, data
    except BaseException:
        os.close(fd)
        raise
    finally:
        library.seccomp_release(context)


@dataclass(frozen=True)
class HostedNamespacePaths:
    install: Path
    projection: Path
    channel: Path
    authority: Path
    configuration: Path
    provenance: Path
    offline_inputs: Path


def namespace_command(
    role: Literal["service", "host"],
    paths: HostedNamespacePaths,
    command: tuple[str, ...],
    *,
    seccomp_fd: int | None = None,
    service_capability_fds: tuple[int, ...] = (),
    offline_source_root: Path | None = None,
    info_fd: int | None = None,
    mount_policy_hash: str = sha256_bytes(MOUNT_POLICY_BYTES),
) -> tuple[str, ...]:
    """Management-only argv; this function is never exposed through the research channel."""
    if not command:
        raise ValueError("namespace requires fixed command")
    if mount_policy_hash not in (
        sha256_bytes(LEGACY_MOUNT_POLICY_BYTES),
        sha256_bytes(MOUNT_POLICY_BYTES),
    ):
        raise ValueError("unknown frozen namespace mount policy")
    result = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
    ]
    if info_fd is not None:
        if info_fd < 3:
            raise ValueError("container information requires a private descriptor")
        result += ["--info-fd", str(info_fd)]
    if role == "host":
        if seccomp_fd is None:
            raise ValueError("research host requires source seccomp")
        result += ["--share-net", "--tmpfs", "/proc", "--remount-ro", "/proc"]
    else:
        result += ["--proc", "/proc"]
    for logical in SYSTEM_RUNTIME_PATHS:
        if logical.startswith("/etc/"):
            result += ["--ro-bind", logical, logical]
    for source, target in (
        (Path("/usr"), "/usr"),
        (Path("/lib"), "/lib"),
        (Path("/lib64"), "/lib64"),
        (paths.install, "/install"),
        (paths.projection, "/projection"),
    ):
        result += ["--ro-bind", str(source), target]
    if role == "service" and mount_policy_hash == sha256_bytes(MOUNT_POLICY_BYTES):
        # Qlib's native recorder uses subprocess(..., shell=True), which resolves
        # /bin/sh. Both names reach the same already-read-only /usr tree.
        result += [
            "--symlink",
            "/usr/bin",
            "/bin",
            "--setenv",
            "MLFLOW_DISABLE_TELEMETRY",
            "true",
        ]
    result += [
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tmp/home",
        "--setenv",
        "HOME",
        "/tmp/home",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONHASHSEED",
        "0",
    ]
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        result += ["--setenv", variable, "1"]
    result += ["--setenv", "TZ", "UTC"]
    if role == "service":
        if offline_source_root is not None:
            result += ["--ro-bind", str(offline_source_root), "/saved-evidence"]
        if len(service_capability_fds) > 32 or len(set(service_capability_fds)) != len(
            service_capability_fds
        ):
            raise ValueError("service capability descriptor list is invalid")
        for source, target in ((paths.authority, "/authority"), (paths.channel, "/channel")):
            result += ["--bind", str(source), target]
        for source, target in (
            (paths.configuration, "/config"),
            (paths.provenance, "/provenance"),
            (paths.offline_inputs, "/inputs"),
        ):
            result += ["--ro-bind", str(source), target]
        for index, descriptor in enumerate(service_capability_fds):
            if descriptor < 3:
                raise ValueError("service capability descriptor is invalid")
            result += [
                "--perms",
                "0600",
                "--file",
                str(descriptor),
                f"/tmp/hosted-service-capability-{index}",
            ]
        result += ["--chdir", "/tmp"]
    else:
        if offline_source_root is not None:
            raise ValueError("research host cannot mount offline management sources")
        if service_capability_fds:
            raise ValueError("research host cannot receive service capabilities")
        result += [
            "--ro-bind",
            str(paths.channel),
            "/channel",
            "--dir",
            "/tmp/codex",
            "--setenv",
            "CODEX_HOME",
            "/tmp/codex",
            "--chdir",
            "/projection",
            "--seccomp",
            str(seccomp_fd),
        ]
    return (*result, *command)
