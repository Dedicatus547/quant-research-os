"""CLI transport failures expose controlled codes and never imply completion."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quantos import cli


@pytest.mark.parametrize(
    "command", ["start", "pending", "resume", "status", "cancel", "request-export"]
)
@pytest.mark.parametrize("failure", ["hash", "transport", "empty"])
def test_hosted_commands_control_invalid_identity_transport_and_empty_results(
    tmp_path, monkeypatch, command, failure
):
    calls = []

    def operation(*args):
        calls.append(args)
        if failure == "transport":
            raise OSError("synthetic detail must not leak")
        return None

    monkeypatch.setattr(
        cli,
        "_hosted_client",
        lambda *args: SimpleNamespace(
            start=operation, pending=operation, resume=operation, status=operation, cancel=operation
        ),
    )
    args = [
        "hosted",
        command,
        "--campaign",
        "bad" if failure == "hash" else "a" * 64,
        "--capability-fd",
        "5",
    ]
    if command == "start":
        args += ["--spec", "b" * 64]
    elif command == "cancel":
        args += ["--request", "b" * 64]
    elif command == "request-export":
        args += ["--output", str(tmp_path / "export.json")]
    result = CliRunner().invoke(cli.app, args)
    if command == "pending" and failure == "empty":
        assert result.exit_code == 0
        assert json.loads(result.stdout)["status"] == "NO_PENDING_REQUEST"
    else:
        assert result.exit_code != 0
        assert "HOSTED_" in result.output
    assert "synthetic detail" not in result.output
    assert len(calls) == (failure != "hash")
    assert not (tmp_path / "export.json").exists()
