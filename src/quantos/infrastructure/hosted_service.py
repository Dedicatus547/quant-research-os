"""Authenticated bounded Unix channel for the one shared hosted application service."""

from __future__ import annotations

import argparse
import hmac
import io
import os
import platform
import socket
import stat
import struct
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedAgentRequest, parse_hosted_contract
from quantos.contracts.hosted_deployment import (
    HostedChannelPolicy,
    HostedChannelRequest,
    HostedClientConfiguration,
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedServiceConfiguration,
)
from quantos.infrastructure.hosted_client import (
    CHANNEL_MAGIC,
    HostedChannelError,
    consume_capability_fd,
    receive_exact,
)
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    KnownValueGuard,
    install_inventory,
    private_memory_fd,
    source_seccomp_filter,
    system_runtime_inventory,
    verify_install,
)

ConfigT = TypeVar("ConfigT", bound=CanonicalContract)


class HostedApplication(Protocol):
    def start(self, spec_hash: str) -> CanonicalContract: ...
    def pending(self, campaign_hash: str) -> HostedAgentRequest | None: ...
    def status(self, campaign_hash: str) -> CanonicalContract: ...
    def submit(
        self, request_hash: str, response_bytes: bytes, authenticated_principal: str
    ) -> CanonicalContract: ...
    def resume(self, campaign_hash: str) -> CanonicalContract: ...
    def cancel(self, request_hash: str, authenticated_principal: str) -> CanonicalContract: ...


@dataclass(frozen=True)
class HostedPrincipalGrant:
    principal: str
    host_instance: str
    uid: int
    gid: int
    campaign_hashes: frozenset[str]
    capability: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.capability) != 32 or not self.campaign_hashes:
            raise ValueError("principal grant requires capability and campaign allowlist")


class HostedUnixService:
    """One request per connection, bounded workers and lifetime accepts, fixed errors only.

    The manager registers trusted spec/request identities before exposing the socket.
    Accepted response/source/admission semantics remain in the shared application.
    """

    def __init__(
        self,
        application: HostedApplication,
        socket_path: Path,
        policy: HostedChannelPolicy,
        grants: tuple[HostedPrincipalGrant, ...],
        *,
        specs: dict[str, str],
        requests: dict[str, str],
        publication_guard: KnownValueGuard,
    ) -> None:
        if not grants or len(grants) > 32:
            raise ValueError("bounded principal registration required")
        if len({x.capability for x in grants}) != len(grants):
            raise ValueError("each host instance requires an independent capability")
        self.application = application
        self.socket_path = socket_path
        self.policy = policy
        self._grants = grants
        self._specs = dict(specs)
        self._requests = dict(requests)
        self._guard = publication_guard
        self._stop = threading.Event()
        self._workers: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._capacity = threading.BoundedSemaphore(policy.max_connections)
        self._listener: socket.socket | None = None
        self.ready = threading.Event()
        self.accepted_connections = 0
        self.denied_connections = 0

    def register_request(self, request: HostedAgentRequest) -> None:
        """Trusted management recovery registration; never a channel operation."""
        with self._lock:
            self._requests[request.content_hash] = request.campaign_hash

    def stop(self) -> None:
        self._stop.set()

    def serve(self) -> None:
        parent = self.socket_path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError("service channel directory must be real and service-owned")
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise ValueError("channel socket already exists; manager must reconcile deployment")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener = listener
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            listener.listen(self.policy.listen_backlog)
            listener.settimeout(0.1)
            self.ready.set()
            while (
                not self._stop.is_set()
                and self.accepted_connections < self.policy.max_total_connections
            ):
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                self.accepted_connections += 1
                if not self._capacity.acquire(blocking=False):
                    connection.close()
                    self.denied_connections += 1
                    continue
                thread = threading.Thread(target=self._worker, args=(connection,), daemon=True)
                with self._lock:
                    self._workers.add(thread)
                thread.start()
        finally:
            listener.close()
            with self._lock:
                workers = tuple(self._workers)
            for thread in workers:
                thread.join(self.policy.io_timeout_ms / 1000 + 1)
            if self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                self.socket_path.unlink()

    def _worker(self, connection: socket.socket) -> None:
        try:
            with connection:
                connection.settimeout(self.policy.io_timeout_ms / 1000)
                value = self._dispatch(connection)
                self._reply(connection, value=value)
        except (OSError, ValueError, RuntimeError):
            # Never log exceptions, client bytes, auth material or unbounded errors.
            with self._lock:
                self.denied_connections += 1
        finally:
            self._capacity.release()
            with self._lock:
                self._workers.discard(threading.current_thread())

    def _dispatch(self, connection: socket.socket) -> CanonicalContract | None:
        pid, uid, gid = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        del pid  # Same UID is insufficient; possession of the per-instance grant is mandatory.
        hello = receive_exact(connection, 36)
        if hello[:4] != CHANNEL_MAGIC:
            raise HostedChannelError("CHANNEL_DENIED")
        grant = next(
            (
                item
                for item in self._grants
                if item.uid == uid
                and item.gid == gid
                and hmac.compare_digest(item.capability, hello[4:])
            ),
            None,
        )
        if grant is None:
            raise HostedChannelError("CHANNEL_DENIED")
        size = struct.unpack("!I", receive_exact(connection, 4))[0]
        if size > self.policy.header_byte_cap:
            raise HostedChannelError("CHANNEL_HEADER_LIMIT")
        header = parse_hosted_contract(
            receive_exact(connection, size),
            HostedChannelRequest,
            max_bytes=self.policy.header_byte_cap,
        )
        if header.campaign_hash not in grant.campaign_hashes:
            raise HostedChannelError("CHANNEL_DENIED")
        target = header.target_hash
        if header.operation == "start":
            if self._specs.get(target) != header.campaign_hash:
                raise HostedChannelError("CHANNEL_DENIED")
        elif header.operation in ("submit", "cancel"):
            with self._lock:
                campaign = self._requests.get(target)
            if campaign != header.campaign_hash:
                raise HostedChannelError("CHANNEL_DENIED")
        elif target != header.campaign_hash:
            raise HostedChannelError("CHANNEL_DENIED")
        declared = struct.unpack("!I", receive_exact(connection, 4))[0]
        if header.operation != "submit" and declared:
            raise HostedChannelError("CHANNEL_BODY_FORBIDDEN")
        body = receive_exact(connection, min(declared, self.policy.response_byte_cap + 1))
        connection.settimeout(self.policy.operation_reply_timeout_ms / 1000)
        if header.operation == "submit":
            return self.application.submit(target, body, grant.principal)
        if header.operation == "cancel":
            return self.application.cancel(target, grant.principal)
        if header.operation == "start":
            result = self.application.start(target)
        elif header.operation == "pending":
            result = self.application.pending(target)
        elif header.operation == "resume":
            result = self.application.resume(target)
        else:
            result = self.application.status(target)
        if isinstance(result, HostedAgentRequest):
            self.register_request(result)
        elif header.operation in ("start", "resume"):
            request = self.application.pending(header.campaign_hash)
            if request is not None:
                self.register_request(request)
        return result

    def _reply(self, connection: socket.socket, *, value: CanonicalContract | None) -> None:
        data = canonical_json_bytes(
            {
                "schema_version": "hosted-channel-result/v1",
                "ok": True,
                "error": None,
                "value": value.canonical_payload() if value else None,
            }
        )
        if len(data) > self.policy.reply_byte_cap:
            raise HostedChannelError("CHANNEL_REPLY_LIMIT")
        self._guard(data)
        connection.sendall(struct.pack("!I", len(data)) + data)


def _hashed_configuration(
    root: Path, digest: str, contract_type: type[ConfigT], *, max_bytes: int = 16_777_216
) -> ConfigT:
    """Read one manager-selected canonical object without following path aliases."""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ArtifactIntegrityError("configuration requires an explicit SHA-256 identity")
    with opened_directory(root) as descriptor:
        data = read_regular_bytes_at(descriptor, f"sha256-{digest}.json", max_bytes=max_bytes)
    if sha256_bytes(data) != digest:
        raise ArtifactIntegrityError("configuration bytes differ from requested identity")
    value = parse_hosted_contract(data, contract_type, max_bytes=max_bytes)
    if value.canonical_bytes() != data:
        raise ArtifactIntegrityError("configuration bytes are not canonical")
    return value


def _hashed_wheel(root: Path, digest: str) -> bytes:
    with opened_directory(root) as descriptor:
        data = read_regular_bytes_at(descriptor, f"sha256-{digest}.whl", max_bytes=16_777_216)
    if sha256_bytes(data) != digest:
        raise ArtifactIntegrityError("frozen wheel bytes differ from identity")
    return data


def _verify_wheel_install(install_root: Path, wheel_bytes: bytes) -> None:
    """The frozen QuantOS files must be the exact bound wheel members."""
    site = install_root / "python/lib/python3.11/site-packages"
    quantos_files = 0
    total_bytes = 0
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
            for member in archive.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts or not path.parts or member.is_dir():
                    if member.is_dir() and path.parts and ".." not in path.parts:
                        continue
                    raise ArtifactIntegrityError("frozen wheel has unsafe member")
                total_bytes += member.file_size
                if member.file_size > 16_777_216 or total_bytes > 67_108_864:
                    raise ArtifactIntegrityError("frozen wheel expansion exceeds byte cap")
                actual = site.joinpath(*path.parts)
                if (
                    not actual.is_file()
                    or actual.is_symlink()
                    or actual.read_bytes() != archive.read(member)
                ):
                    raise ArtifactIntegrityError("installed package differs from frozen wheel")
                if path.parts[0] == "quantos":
                    quantos_files += 1
    except (OSError, zipfile.BadZipFile) as error:
        raise ArtifactIntegrityError("frozen wheel is unreadable") from error
    if quantos_files == 0:
        raise ArtifactIntegrityError("frozen wheel has no QuantOS package")


def bootstrap_hosted_service(
    profile_hash: str,
    *,
    configuration_root: Path = Path("/config"),
    install_root: Path = Path("/install"),
    initial_projection_root: Path = Path("/projection"),
    authority_root: Path = Path("/authority"),
    provenance_root: Path = Path("/provenance"),
    input_root: Path = Path("/inputs"),
    channel_root: Path = Path("/channel"),
    protocol_clock: Callable[[], datetime] | None = None,
    verify_journal_entry: Callable[[object], None] | None = None,
) -> HostedUnixService:
    """Rebuild the single fixed production registration before exposing a socket.

    Root overrides exist only for manager tests. The executable entrypoint below
    supplies literal isolated namespace paths and exposes no root/path option.
    """
    from quantos.application.hosted_inputs import load_hosted_campaign_application
    from quantos.application.hosted_protocol import HostedProtocolService
    from quantos.contracts.hosted_inputs import (
        HostedBusinessLoaderConfiguration,
        HostedFrozenBusinessInputs,
        derive_hosted_campaign_spec,
    )
    from quantos.infrastructure.hosted_launcher import EXTRACTION_RULE_BYTES
    from quantos.infrastructure.hosted_store import HostedProtocolStore

    profile = _hashed_configuration(configuration_root, profile_hash, HostedDeploymentProfile)
    configuration = _hashed_configuration(
        configuration_root, profile.configuration_hash, HostedServiceConfiguration
    )
    business = _hashed_configuration(
        configuration_root,
        configuration.business_configuration_hash,
        HostedBusinessLoaderConfiguration,
    )
    if (
        business.factory != configuration.application_factory
        or business.input_root != "/inputs"
        or business.provenance_workspace != "/provenance"
        or business.business_root != "/authority/business"
        or configuration.policy != profile.policy
        or configuration.configuration_root != "/config"
        or configuration.protocol_root != "/authority/protocol"
        or configuration.business_lock_root != "/authority/business-locks"
        or configuration.socket_path != "/channel/quantos.sock"
    ):
        raise ArtifactIntegrityError("service configuration escaped the fixed deployment")
    bundle = _hashed_configuration(
        input_root, business.business_inputs_hash, HostedFrozenBusinessInputs
    )
    campaign_hash = bundle.campaign.content_hash
    if (
        tuple(item.campaign_hash for item in configuration.campaigns) != (campaign_hash,)
        or bundle.hosted_recipe.requested_model_configuration_hash
        != profile.model_configuration_hash
        or bundle.code_provenance.commit_hash != profile.exact_commit
        or bundle.code_provenance.lockfile_hash != profile.lock_hash
    ):
        raise ArtifactIntegrityError("frozen business campaign is not the exact service grant")

    initial_inventory = _hashed_configuration(
        configuration_root, profile.projection_inventory_hash, HostedInstallInventory
    )
    launcher_configuration = _hashed_configuration(
        configuration_root, profile.model_configuration_hash, HostedLauncherConfiguration
    )
    install_expected = _hashed_configuration(
        configuration_root, profile.install_inventory_hash, HostedInstallInventory
    )
    if (
        launcher_configuration.content_hash != profile.model_configuration_hash
        or sha256_bytes(EXTRACTION_RULE_BYTES) != profile.extraction_rule_hash
    ):
        raise ArtifactIntegrityError("external model configuration or extraction rule changed")
    wheel_bytes = _hashed_wheel(configuration_root, profile.wheel_hash)
    if (
        install_inventory(initial_projection_root).canonical_bytes()
        != initial_inventory.canonical_bytes()
    ):
        raise ArtifactIntegrityError("initial projection inventory changed")
    verify_install(install_root, install_expected)
    _verify_wheel_install(install_root, wheel_bytes)
    with opened_directory(install_root) as descriptor:
        public_client_bytes = read_regular_bytes_at(
            descriptor, "hosted-client.json", max_bytes=4096
        )
    expected_public_client = HostedClientConfiguration(
        socket_path=configuration.socket_path, policy=configuration.policy
    )
    if public_client_bytes != expected_public_client.canonical_bytes():
        raise ArtifactIntegrityError("frozen public client configuration differs from service")
    if (
        install_inventory(provenance_root).content_hash != profile.provenance_inventory_hash
        or sha256_file(provenance_root / "uv.lock") != profile.lock_hash
        or sha256_file(install_root / "codex") != profile.cli_binary_hash
        or sha256_file(Path("/usr/bin/bwrap")) != profile.bwrap_binary_hash
        or sha256_file(Path("/lib/x86_64-linux-gnu/libseccomp.so.2"))
        != profile.libseccomp_binary_hash
        or system_runtime_inventory().content_hash != profile.os_inventory_hash
        or sha256_bytes(MOUNT_POLICY_BYTES) != profile.mount_policy_hash
    ):
        raise ArtifactIntegrityError("frozen runtime or provenance inventory changed")
    seccomp_fd, seccomp_bytes = source_seccomp_filter()
    os.close(seccomp_fd)
    if sha256_bytes(seccomp_bytes) != profile.seccomp_bpf_hash:
        raise ArtifactIntegrityError("source seccomp policy changed")
    if (
        platform.system() != profile.operating_system
        or platform.release() != profile.kernel_release
        or " ".join(platform.libc_ver()) != profile.libc
        or platform.python_version() != profile.python_version
        or subprocess.run(
            ("/usr/bin/bwrap", "--version"),
            check=True,
            capture_output=True,
            timeout=5,
        )
        .stdout.decode("utf-8")
        .strip()
        != profile.bwrap_version
        or subprocess.run(
            ("/install/codex", "--version"),
            check=True,
            capture_output=True,
            timeout=5,
        )
        .stdout.decode("utf-8")
        .strip()
        != f"codex-cli {profile.cli_version}"
    ):
        raise ArtifactIntegrityError("running OS or external CLI identity changed")
    if (
        not sys.flags.isolated
        or not sys.flags.ignore_environment
        or not sys.flags.no_user_site
        or not sys.flags.safe_path
        or sys.flags.hash_randomization != 0
        or os.environ.get("PYTHONHASHSEED") != "0"
        or not Path(sys.executable).resolve().is_relative_to(install_root.resolve())
        or not Path(__file__)
        .resolve()
        .is_relative_to((install_root / "python/lib/python3.11/site-packages").resolve())
    ):
        raise ArtifactIntegrityError("service is not importing from frozen isolated Python")

    derived_spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile.content_hash)
    store = HostedProtocolStore(
        authority_root / "protocol", verify_journal_entry=verify_journal_entry
    )
    campaign_directory = authority_root / "protocol/campaigns" / campaign_hash
    existing_requests: dict[str, str] = {}
    if campaign_directory.exists() or campaign_directory.is_symlink():
        snapshot = store.snapshot(campaign_hash, recover=True)
        if snapshot.spec.canonical_bytes() != derived_spec.canonical_bytes():
            raise ArtifactIntegrityError("restarted service spec differs from stored bytes")
        existing_requests = {request.content_hash: campaign_hash for request in snapshot.requests}
    campaign_names = tuple(
        sorted(path.name for path in (authority_root / "protocol/campaigns").iterdir())
    )
    if any(name != campaign_hash for name in campaign_names):
        raise ArtifactIntegrityError("authority contains an unregistered hosted campaign")

    capabilities = tuple(
        consume_capability_fd(principal.capability_fd) for principal in configuration.principals
    )
    guard = KnownValueGuard(capabilities)
    holder: dict[str, HostedApplication] = {}

    def verify_inputs(spec: object) -> None:
        application = holder.get("application")
        if application is None:
            raise ArtifactIntegrityError("hosted business loader has not completed")
        application.verify_registered_inputs(spec)  # type: ignore[attr-defined,arg-type]

    options = {} if protocol_clock is None else {"clock": protocol_clock}
    protocol = HostedProtocolService(
        store, verify_inputs=verify_inputs, scan_submission=guard, **options
    )
    application = load_hosted_campaign_application(
        business,
        protocol,
        authority_root / "business-locks",
        deployment_profile_hash=profile.content_hash,
    )
    holder["application"] = application
    registered_spec = application.registered_spec(campaign_hash)
    if (
        registered_spec.canonical_bytes() != derived_spec.canonical_bytes()
        or store.spec(derived_spec.content_hash).canonical_bytes() != derived_spec.canonical_bytes()
    ):
        raise ArtifactIntegrityError("loader did not reconstruct the unique frozen spec")
    grants = tuple(
        HostedPrincipalGrant(
            principal=item.principal,
            host_instance=item.host_instance,
            uid=item.uid,
            gid=item.gid,
            campaign_hashes=frozenset(item.campaign_hashes),
            capability=capability,
        )
        for item, capability in zip(configuration.principals, capabilities, strict=True)
    )
    return HostedUnixService(
        application,
        channel_root / "quantos.sock",
        configuration.policy,
        grants,
        specs={derived_spec.content_hash: campaign_hash},
        requests=existing_requests,
        publication_guard=guard,
    )


def _hydrate_service_capabilities(profile_hash: str) -> None:
    """Move bwrap's one-use tmpfs files into fixed private FDs, then unlink them."""
    profile = _hashed_configuration(Path("/config"), profile_hash, HostedDeploymentProfile)
    configuration = _hashed_configuration(
        Path("/config"), profile.configuration_hash, HostedServiceConfiguration
    )
    expected_names = {
        f"hosted-service-capability-{index}" for index in range(len(configuration.principals))
    }
    with opened_directory(Path("/tmp")) as tmp_fd:
        with os.scandir(tmp_fd) as entries:
            actual_names = {
                x.name for x in entries if x.name.startswith("hosted-service-capability-")
            }
        if actual_names != expected_names:
            raise ArtifactIntegrityError("service capability staging files differ")
        for index, principal in enumerate(configuration.principals):
            target_fd = 100 + index
            if principal.capability_fd != target_fd:
                raise ArtifactIntegrityError("service capability descriptor slot changed")
            name = f"hosted-service-capability-{index}"
            value = read_regular_bytes_at(tmp_fd, name, max_bytes=32)
            if len(value) != 32:
                raise ArtifactIntegrityError("service capability has invalid byte length")
            os.unlink(name, dir_fd=tmp_fd)
            descriptor = private_memory_fd("hosted-service-capability")
            try:
                os.write(descriptor, value)
                os.lseek(descriptor, 0, os.SEEK_SET)
                if descriptor != target_fd:
                    os.dup2(descriptor, target_fd, inheritable=False)
            finally:
                if descriptor != target_fd:
                    os.close(descriptor)


# Management entrypoints share exactly the online configuration and FD hydration.
# Neither function is an operation in HostedChannelRequest or the hosted CLI.
read_hashed_configuration = _hashed_configuration
hydrate_service_capabilities = _hydrate_service_capabilities


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen hosted QuantOS service")
    parser.add_argument("--profile-hash", required=True)
    args = parser.parse_args()
    _hydrate_service_capabilities(args.profile_hash)
    bootstrap_hosted_service(args.profile_hash).serve()


if __name__ == "__main__":
    main()
