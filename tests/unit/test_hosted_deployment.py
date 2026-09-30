from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import zipfile
from pathlib import Path

import pytest
import pytest_socket
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService, _scan_safe
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedContract
from quantos.contracts.hosted_deployment import HostedChannelPolicy, HostedChannelRequest
from quantos.infrastructure.hosted_client import (
    CHANNEL_MAGIC,
    HostedChannelError,
    HostedUnixClient,
    consume_capability_fd,
)
from quantos.infrastructure.hosted_deployment import (
    HostedNamespacePaths,
    KnownValueGuard,
    export_projection,
    install_inventory,
    namespace_command,
    read_projection,
    source_seccomp_filter,
    verify_install,
)
from quantos.infrastructure.hosted_service import (
    HostedPrincipalGrant,
    HostedUnixService,
    _hashed_wheel,
    _verify_wheel_install,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.security import SecretArtifactRejected


def _policy(**changes: object) -> HostedChannelPolicy:
    return HostedChannelPolicy.model_validate(
        {
            "header_byte_cap": 4096,
            "response_byte_cap": 262144,
            "reply_byte_cap": 1052672,
            "io_timeout_ms": 100,
            "operation_reply_timeout_ms": 2000,
            "max_connections": 2,
            "max_total_connections": 20,
            "listen_backlog": 2,
            **changes,
        }
    )


@pytest.fixture
def unix_only() -> object:
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.enable_socket()
        pytest_socket.disable_socket()


class CountingApplication:
    def __init__(self, protocol: HostedProtocolService, *, status_delay: float = 0) -> None:
        self.protocol = protocol
        self.calls: list[str] = []
        self.status_delay = status_delay

    def start(self, digest: str) -> HostedContract:
        self.calls.append("start")
        return self.protocol.start(digest)

    def pending(self, digest: str):  # type: ignore[no-untyped-def]
        self.calls.append("pending")
        return self.protocol.pending(digest)

    def status(self, digest: str) -> HostedContract:
        self.calls.append("status")
        time.sleep(self.status_delay)
        return self.protocol.status(digest)

    def submit(self, digest: str, data: bytes, principal: str) -> HostedContract:
        self.calls.append("submit")
        return self.protocol.submit(digest, data, principal)

    def resume(self, digest: str) -> HostedContract:
        self.calls.append("resume")
        return self.protocol.resume(digest)

    def cancel(self, digest: str, principal: str) -> HostedContract:
        self.calls.append("cancel")
        return self.protocol.cancel(digest, principal)


def _serve(tmp_path: Path, *, status_delay: float = 0):  # type: ignore[no-untyped-def]
    fixture = _fixture(tmp_path)
    capability = b"C" * 32
    guard = KnownValueGuard((capability,))
    protocol = HostedProtocolService(
        HostedProtocolStore(fixture.root),
        clock=fixture.clock,
        verify_inputs=lambda _: None,
        scan_submission=guard,
    )
    application = CountingApplication(protocol, status_delay=status_delay)
    endpoint = tmp_path / "channel"
    endpoint.mkdir()
    service = HostedUnixService(
        application,
        endpoint / "service.sock",
        _policy(),
        (
            HostedPrincipalGrant(
                "host.one",
                "instance.one",
                os.getuid(),
                os.getgid(),
                frozenset((fixture.spec.campaign_hash,)),
                capability,
            ),
        ),
        specs={fixture.spec.content_hash: fixture.spec.campaign_hash},
        requests={fixture.request.content_hash: fixture.spec.campaign_hash},
        publication_guard=guard,
    )
    thread = threading.Thread(target=service.serve)
    thread.start()
    assert service.ready.wait(2)
    client = HostedUnixClient(service.socket_path, capability, service.policy)
    return fixture, application, service, thread, client


def _stop(service: HostedUnixService, thread: threading.Thread) -> None:
    service.stop()
    thread.join(3)
    assert not thread.is_alive()


def test_unix_channel_routes_shared_receipts_and_idempotence(
    tmp_path: Path, unix_only: object
) -> None:
    fixture, application, service, thread, client = _serve(tmp_path)
    try:
        pending = client.pending(fixture.spec.campaign_hash)
        assert pending == fixture.request.canonical_payload()
        raw = fixture.response.canonical_bytes()
        first = client.submit(fixture.request.content_hash, raw, fixture.spec.campaign_hash)
        second = client.submit(fixture.request.content_hash, raw, fixture.spec.campaign_hash)
        assert first == second and first is not None and first["outcome"] == "ACCEPTED"
        assert first["authenticated_principal"] == "host.one"
        assert application.protocol.status(fixture.spec.campaign_hash).used_unique_submissions == 1
    finally:
        _stop(service, thread)


def test_same_uid_without_capability_or_wrong_campaign_never_queries_application(
    tmp_path: Path, unix_only: object
) -> None:
    fixture, application, service, thread, _ = _serve(tmp_path)
    try:
        bad = HostedUnixClient(service.socket_path, b"X" * 32, service.policy)
        with pytest.raises(HostedChannelError):
            bad.status(fixture.spec.campaign_hash)
        right = HostedUnixClient(service.socket_path, b"C" * 32, service.policy)
        with pytest.raises(HostedChannelError):
            right.status("f" * 64)
        assert application.calls == []
        assert application.protocol.status(fixture.spec.campaign_hash).used_unique_submissions == 0
    finally:
        _stop(service, thread)


def test_header_cap_timeout_and_unknown_operation_are_bounded(
    tmp_path: Path, unix_only: object
) -> None:
    _, application, service, thread, _ = _serve(tmp_path)
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(service.socket_path))
            connection.sendall(CHANNEL_MAGIC + b"C" * 32 + struct.pack("!I", 4097))
            assert connection.recv(1) == b""
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(str(service.socket_path))
            connection.sendall(b"Q")
            assert connection.recv(1) == b""
        assert application.calls == []
    finally:
        _stop(service, thread)


def test_reply_wait_has_separate_bound_from_frame_timeout(
    tmp_path: Path, unix_only: object
) -> None:
    fixture, _, service, thread, client = _serve(tmp_path, status_delay=0.25)
    try:
        result = client.status(fixture.spec.campaign_hash)
        assert result is not None and result["state"] == "WAITING_FOR_AGENT"
    finally:
        _stop(service, thread)


def test_cap_plus_one_goes_to_protocol_incomplete_prefix_receipt(
    tmp_path: Path, unix_only: object
) -> None:
    fixture, application, service, thread, client = _serve(tmp_path)
    try:
        result = client.submit(
            fixture.request.content_hash, b"x" * 300000, fixture.spec.campaign_hash
        )
        assert result is not None and result["complete"] is False
        assert result["observed_bytes"] == 262145
        assert result["submission_bytes_hash"] is None
        assert application.protocol.status(fixture.spec.campaign_hash).used_unique_submissions == 1
    finally:
        _stop(service, thread)


@pytest.mark.parametrize("form", ["literal", "hex", "base64", "json_escape"])
def test_known_capability_rejects_with_counted_receipt_and_zero_body_retention(
    tmp_path: Path, form: str
) -> None:
    fixture = _fixture(tmp_path)
    capability = b"R" * 32
    value = {
        "literal": capability.decode(),
        "hex": capability.hex(),
        "base64": base64.b64encode(capability).decode(),
        "json_escape": capability.decode(),
    }[form]
    response = fixture.response.model_copy(
        update={
            "host_observation": fixture.response.host_observation.model_copy(
                update={"reported_model_identifier": value}
            )
        }
    )
    raw = response.canonical_bytes()
    if form == "json_escape":
        raw = raw.replace(capability, b"\\u0052" * 32)
    service = HostedProtocolService(
        HostedProtocolStore(fixture.root),
        clock=fixture.clock,
        verify_inputs=lambda _: None,
        scan_submission=KnownValueGuard((capability,)),
    )
    receipt = service.submit(fixture.request.content_hash, raw, "host.one")
    assert receipt.reason == "CREDENTIAL_LIKE_PAYLOAD" and receipt.outcome == "REJECTED"
    assert receipt.submission_bytes_hash == sha256_bytes(raw)
    assert service.submit(fixture.request.content_hash, raw, "host.one") == receipt
    assert service.status(fixture.spec.campaign_hash).used_unique_submissions == 1
    for path in fixture.root.rglob("*"):
        if path.is_file():
            assert capability not in path.read_bytes()
            assert raw != path.read_bytes()


def test_known_guard_does_not_erase_normal_protocol_usage_fields(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    service = HostedProtocolService(
        HostedProtocolStore(fixture.root),
        clock=fixture.clock,
        verify_inputs=lambda _: None,
        scan_submission=KnownValueGuard((b"S" * 32,)),
    )
    assert (
        service.submit(
            fixture.request.content_hash, fixture.response.canonical_bytes(), "host.one"
        ).outcome
        == "ACCEPTED"
    )


def test_step_intent_commit_exception_does_not_grant_nested_proposal_exceptions(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    # The exact typed root position is the only scanner metadata adaptation.
    _scan_safe(
        {
            "schema_version": "hosted-research-step-intent/v1",
            "execution_request": {
                "schema_version": "autonomous-execution-request/v2",
                "code_commit_hash": "a" * 40,
            },
        }
    )
    poisoned = fixture.response.model_copy(
        update={
            "proposal_json": json.dumps(
                {
                    "schema_version": "hosted-research-step-intent/v1",
                    "execution_request": {
                        "schema_version": "autonomous-execution-request/v2",
                        "code_commit_hash": "a" * 40,
                        "api_key": "NON_SECRET_TEST_CREDENTIAL",
                    },
                }
            )
        }
    )
    with pytest.raises(SecretArtifactRejected):
        _scan_safe(poisoned.model_dump(mode="json"))


def test_capability_descriptor_is_consumed_and_closed() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"V" * 32)
    os.close(write_fd)
    assert consume_capability_fd(read_fd) == b"V" * 32
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_projection_exact_hash_allowlist_and_unsafe_aliases(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    context = fixture.request.business_request.context_pack.canonical_bytes()
    root = tmp_path / "projection"
    inventory = export_projection(
        root, fixture.request, {sha256_bytes(context): context}, guard=KnownValueGuard(())
    )
    assert read_projection(root, fixture.request.context_pack_hash, max_bytes=1048576) == context
    verify_install(root, inventory)
    with pytest.raises(ArtifactIntegrityError):
        read_projection(root, "../authority", max_bytes=10)
    (root / "escape").symlink_to(fixture.root)
    with pytest.raises(ArtifactIntegrityError):
        install_inventory(root)


def test_bootstrap_wheel_is_anchored_regular_file_without_aliases(tmp_path: Path) -> None:
    content = b"frozen-wheel-canary"
    digest = sha256_bytes(content)
    target = tmp_path / f"sha256-{digest}.whl"
    target.write_bytes(content)
    _hashed_wheel(tmp_path, digest)
    target.unlink()
    target.symlink_to(tmp_path / "external-wheel")
    (tmp_path / "external-wheel").write_bytes(content)
    with pytest.raises(ArtifactIntegrityError):
        _hashed_wheel(tmp_path, digest)
    target.unlink()
    os.link(tmp_path / "external-wheel", target)
    with pytest.raises(ArtifactIntegrityError):
        _hashed_wheel(tmp_path, digest)


def test_installed_quantos_bytes_must_match_bound_wheel(tmp_path: Path) -> None:
    from io import BytesIO

    site = tmp_path / "python/lib/python3.11/site-packages/quantos"
    site.mkdir(parents=True)
    package = site / "__init__.py"
    package.write_bytes(b"frozen package")
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("quantos/__init__.py", b"frozen package")
    _verify_wheel_install(tmp_path, stream.getvalue())
    package.write_bytes(b"mutable checkout")
    with pytest.raises(ArtifactIntegrityError):
        _verify_wheel_install(tmp_path, stream.getvalue())


def test_namespace_role_excludes_authority_credentials_and_checkout_from_host(
    tmp_path: Path,
) -> None:
    paths = HostedNamespacePaths(
        *(
            tmp_path / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "config",
                "provenance",
                "inputs",
            )
        )
    )
    host = namespace_command("host", paths, ("/install/codex", "--version"), seccomp_fd=7)
    service = namespace_command(
        "service", paths, ("/install/python/bin/python3", "-I", "-m", "quantos")
    )
    assert str(paths.authority) not in host and str(paths.provenance) not in host
    assert str(paths.offline_inputs) not in host and "--share-net" in host
    assert "--share-net" not in service and "--proc" in service
    assert "--tmpfs" in host and "--seccomp" in host and "/home/zjw" not in host
    with pytest.raises(ValueError):
        namespace_command("host", paths, ("/install/codex", "--version"))


def test_source_seccomp_export_matches_observed_frozen_filter() -> None:
    fd, data = source_seccomp_filter()
    try:
        assert (
            sha256_bytes(data) == "a66ee36d025856553d5516ac52783c18c530b057d18bfadf637e7e3c5605defb"
        )
    finally:
        os.close(fd)


def test_channel_request_forbids_arbitrary_paths_and_management_operations() -> None:
    with pytest.raises(ValueError):
        HostedChannelRequest.model_validate(
            {
                "operation": "register",
                "campaign_hash": "a" * 64,
                "target_hash": "b" * 64,
                "path": "/authority",
            }
        )
