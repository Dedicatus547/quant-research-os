"""Hosted CLI boundary tests; fake channel calls confer no live qualification."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_protocol import _fixture
from typer.testing import CliRunner

from quantos import cli
from quantos.contracts.hosted_deployment import HostedChannelPolicy, HostedClientConfiguration
from quantos.infrastructure.hosted_client import HostedUnixClient
from quantos.infrastructure.hosted_host import _read_exported_request

CAMPAIGN = "a" * 64
SPEC = "b" * 64
REQUEST = "c" * 64


class FakeClient:
    def __init__(self, request_value: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.policy = SimpleNamespace(response_byte_cap=4)
        self.request_value = request_value

    def start(self, spec: str, campaign: str) -> dict[str, object]:
        self.calls.append(("start", spec, campaign))
        return {"state": "WAITING_FOR_AGENT"}

    def pending(self, campaign: str) -> dict[str, object] | None:
        self.calls.append(("pending", campaign))
        return self.request_value

    def status(self, campaign: str) -> dict[str, object]:
        self.calls.append(("status", campaign))
        return {"state": "WAITING_FOR_AGENT"}

    def resume(self, campaign: str) -> dict[str, object]:
        self.calls.append(("resume", campaign))
        return {"state": "STEP_COMPLETED"}

    def submit(self, request: str, body: bytes, campaign: str) -> dict[str, object]:
        self.calls.append(("submit", request, body, campaign))
        return {"outcome": "REJECTED"}

    def cancel(self, request: str, campaign: str) -> dict[str, object]:
        self.calls.append(("cancel", request, campaign))
        return {"outcome": "CANCELLED"}


def _invoke(*args: str) -> object:
    return CliRunner().invoke(cli.app, ["hosted", *args, "--capability-fd", "3"])


def test_hosted_commands_use_only_restricted_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(cli, "_hosted_client", lambda *_args: fake)
    runner = CliRunner()
    commands = [
        ("start", ["--spec", SPEC, "--campaign", CAMPAIGN], ("start", SPEC, CAMPAIGN)),
        ("status", ["--campaign", CAMPAIGN], ("status", CAMPAIGN)),
        ("resume", ["--campaign", CAMPAIGN], ("resume", CAMPAIGN)),
        ("cancel", ["--campaign", CAMPAIGN, "--request", REQUEST], ("cancel", REQUEST, CAMPAIGN)),
    ]
    for name, options, expected in commands:
        result = runner.invoke(cli.app, ["hosted", name, *options, "--capability-fd", "3"])
        assert result.exit_code == 0, result.stdout
        assert fake.calls[-1] == expected
        assert isinstance(json.loads(result.stdout), dict)
    pending = runner.invoke(
        cli.app, ["hosted", "pending", "--campaign", CAMPAIGN, "--capability-fd", "3"]
    )
    assert pending.exit_code == 0
    assert json.loads(pending.stdout)["status"] == "NO_PENDING_REQUEST"


@pytest.mark.parametrize("bad", ["latest", "current", "auto", "A" * 64, "0" * 63, "g" * 64])
def test_hosted_rejects_mutable_or_invalid_identity_before_client(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(cli, "_hosted_client", lambda *_args: pytest.fail("client reached"))
    result = CliRunner().invoke(
        cli.app, ["hosted", "status", "--campaign", bad, "--capability-fd", "3"]
    )
    assert result.exit_code == 20
    assert json.loads(result.stdout)["reason_code"] == "HOSTED_HASH_INVALID"


def test_submit_reads_only_bounded_regular_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(cli, "_hosted_client", lambda *_args: fake)
    response = tmp_path / "response.json"
    response.write_bytes(b"1234567890")
    options = [
        "hosted",
        "submit",
        "--campaign",
        CAMPAIGN,
        "--request",
        REQUEST,
        "--response",
        str(response),
        "--capability-fd",
        "3",
    ]
    result = CliRunner().invoke(cli.app, options)
    assert result.exit_code == 0
    assert fake.calls == [("submit", REQUEST, b"12345", CAMPAIGN)]

    symlink = tmp_path / "link"
    symlink.symlink_to(response)
    blocked = CliRunner().invoke(cli.app, [*options[:7], str(symlink), *options[8:]])
    assert blocked.exit_code == 20
    assert len(fake.calls) == 1

    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    blocked_fifo = CliRunner().invoke(cli.app, [*options[:7], str(fifo), *options[8:]])
    assert blocked_fifo.exit_code == 20
    assert len(fake.calls) == 1

    hardlink = tmp_path / "hardlink"
    os.link(response, hardlink)
    blocked_hardlink = CliRunner().invoke(cli.app, [*options[:7], str(hardlink), *options[8:]])
    assert blocked_hardlink.exit_code == 20
    assert len(fake.calls) == 1

    alias = tmp_path / "directory-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    blocked_parent = CliRunner().invoke(
        cli.app, [*options[:7], str(alias / response.name), *options[8:]]
    )
    assert blocked_parent.exit_code == 20
    assert len(fake.calls) == 1


def test_pending_export_exact_request_and_never_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    request = fixture.request
    fake = FakeClient(json.loads(request.canonical_bytes()))
    monkeypatch.setattr(cli, "_hosted_client", lambda *_args: fake)
    campaign = request.campaign_hash
    pending = CliRunner().invoke(
        cli.app, ["hosted", "pending", "--campaign", campaign, "--capability-fd", "3"]
    )
    assert pending.exit_code == 0
    assert json.loads(pending.stdout)["request_hash"] == request.content_hash
    assert request.business_request_hash not in pending.stdout

    output = tmp_path / "request.json"
    args = [
        "hosted",
        "request-export",
        "--campaign",
        campaign,
        "--output",
        str(output),
        "--capability-fd",
        "3",
    ]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0
    assert output.read_bytes() == request.canonical_bytes()
    assert output.stat().st_mode & 0o777 == 0o600
    repeated = CliRunner().invoke(cli.app, args)
    assert repeated.exit_code == 20
    assert output.read_bytes() == request.canonical_bytes()

    alias = tmp_path / "directory-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    redirected = CliRunner().invoke(
        cli.app,
        [
            "hosted",
            "request-export",
            "--campaign",
            campaign,
            "--output",
            str(alias / "redirected.json"),
            "--capability-fd",
            "3",
        ],
    )
    assert redirected.exit_code == 20
    assert not (tmp_path / "redirected.json").exists()


def test_config_consumes_private_capability_fd_without_printing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = HostedChannelPolicy(
        header_byte_cap=4096,
        response_byte_cap=8,
        reply_byte_cap=4096,
        io_timeout_ms=1000,
        operation_reply_timeout_ms=1000,
        max_connections=1,
        max_total_connections=10,
        listen_backlog=1,
    )
    config = HostedClientConfiguration(socket_path="/channel/quantos.sock", policy=policy)
    config_path = tmp_path / "client.json"
    config_path.write_bytes(config.canonical_bytes())
    secret = b"z" * 32
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    captured: dict[str, object] = {}

    def make_client(configuration: HostedClientConfiguration, fd: int) -> FakeClient:
        captured["config"] = configuration
        captured["fd"] = fd
        from quantos.infrastructure.hosted_client import consume_capability_fd

        captured["capability"] = consume_capability_fd(fd)
        return FakeClient()

    monkeypatch.setattr(HostedUnixClient, "from_configuration", make_client)
    result = CliRunner().invoke(
        cli.app,
        [
            "hosted",
            "status",
            "--campaign",
            CAMPAIGN,
            "--client-config",
            str(config_path),
            "--capability-fd",
            str(read_fd),
        ],
    )
    assert result.exit_code == 0
    assert captured["capability"] == secret
    assert secret.decode() not in result.stdout
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_hosted_errors_never_print_client_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object) -> object:
        raise RuntimeError("private capability and response body")

    monkeypatch.setattr(cli, "_hosted_client", fail)
    result = CliRunner().invoke(
        cli.app, ["hosted", "status", "--campaign", CAMPAIGN, "--capability-fd", "3"]
    )
    assert result.exit_code == 20
    assert json.loads(result.stdout) == {
        "reason_code": "HOSTED_OPERATION_FAILED",
        "status": "FAILED",
    }


@pytest.mark.parametrize(
    "mutation", [None, "noncanonical", "corrupted", "symlink", "hardlink", "fifo"]
)
def test_manager_wrapper_returns_only_original_export_bytes(
    tmp_path: Path, mutation: str | None
) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError

    fixture = _fixture(tmp_path / "authority")
    directory = tmp_path / "private-output"
    directory.mkdir()
    path = directory / "hosted-request.json"
    encoded = fixture.request.canonical_bytes()
    if mutation == "fifo":
        os.mkfifo(path)
    elif mutation == "symlink":
        original = tmp_path / "source.json"
        original.write_bytes(encoded)
        path.symlink_to(original)
    else:
        path.write_bytes(
            b" " + encoded
            if mutation == "noncanonical"
            else b"{}"
            if mutation == "corrupted"
            else encoded
        )
        if mutation == "hardlink":
            os.link(path, directory / "alias")
    if mutation is None:
        assert _read_exported_request(directory) == encoded
    else:
        with pytest.raises((ArtifactIntegrityError, ValueError, OSError)):
            _read_exported_request(directory)
