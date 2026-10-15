from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from openai_codex import (
    InternalRpcError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    ParseError,
    ServerBusyError,
    TransportClosedError,
)
from pydantic import BaseModel, ValidationError

from quantos.contracts import (
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessMcpServer,
    HarnessRuntimePolicy,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.integrations.codex.sdk_host import (
    _error_kind,
    _failure,
    _provider_event,
    _sdk_config,
)
from quantos.integrations.codex.sdk_host import (
    execute as sdk_host_execute,
)


def _request(tmp_path: Path) -> HarnessExecutionRequest:
    environment = (
        HarnessEnvironmentVariable(name="LANG", value="C.UTF-8"),
        HarnessEnvironmentVariable(name="PATH", value="/usr/bin:/bin"),
        HarnessEnvironmentVariable(name="TZ", value="UTC"),
    )
    return HarnessExecutionRequest(
        run_id="sdk-host-helper-test",
        cwd=str(tmp_path),
        prompt="return an object",
        model="gpt-test",
        reasoning_effort="high",
        runtime_policy=HarnessRuntimePolicy(
            host_environment=environment,
            child_environment=environment,
            shell_environment=environment,
            shell_tool_enabled=True,
        ),
        mcp_servers=(
            HarnessMcpServer(
                name="probe",
                command="python",
                args=("mock_server.py",),
                enabled_tools=("read_fixture",),
                implementation_hash="a" * 64,
                tool_schema_hash="b" * 64,
            ),
        ),
        timeout_seconds=10,
        total_timeout_seconds=30,
        max_transcript_bytes=100_000,
        max_input_tokens=1_000,
        max_output_tokens=100,
    )


class _Payload(BaseModel):
    snake_name: str


def test_sdk_host_builds_explicit_runtime_configuration(tmp_path: Path) -> None:
    config = _sdk_config(_request(tmp_path))

    assert config == {
        "allow_login_shell": False,
        "features": {"shell_tool": True},
        "history": {"persistence": "none"},
        "mcp_servers": {
            "probe": {
                "args": ["mock_server.py"],
                "command": "python",
                "enabled_tools": ["read_fixture"],
                "required": True,
            }
        },
        "model_reasoning_effort": "high",
        "shell_environment_policy": {
            "inherit": "none",
            "set": {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"},
        },
    }


def test_sdk_host_rejects_unallowlisted_runtime_candidate_before_starting_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUANTOS_CODEX_RUNTIME_CANDIDATE_ID", "openai-codex-latest")

    response = sdk_host_execute(_request(tmp_path))

    error = cast(dict[str, object], response["error"])
    assert error["kind"] == HarnessErrorKind.RUNTIME_MISMATCH.value
    assert response["provider_events"] == []
    assert "message_hash" in error


def test_sdk_host_normalizes_model_and_params_notifications() -> None:
    assert _provider_event("model", _Payload(snake_name="value")) == {
        "method": "model",
        "payload": {"snake_name": "value"},
    }
    assert _provider_event("params", SimpleNamespace(params={"ok": True})) == {
        "method": "params",
        "payload": {"ok": True},
    }
    with pytest.raises(ValueError, match="unsupported notification"):
        _provider_event("invalid", SimpleNamespace(params="not-an-object"))


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (ServerBusyError(-32000, "busy"), HarnessErrorKind.OVERLOADED, True),
        (TransportClosedError("closed"), HarnessErrorKind.TRANSPORT_CLOSED, False),
        (MethodNotFoundError(-32601, "missing"), HarnessErrorKind.PROTOCOL_UNSUPPORTED, False),
        (ParseError(-32700, "bad json"), HarnessErrorKind.OUTPUT_INVALID, False),
        (InternalRpcError(-32603, "internal"), HarnessErrorKind.TRANSPORT_CLOSED, False),
        (InvalidParamsError(-32602, "params"), HarnessErrorKind.CONFIGURATION_INVALID, False),
        (InvalidRequestError(-32600, "request"), HarnessErrorKind.CONFIGURATION_INVALID, False),
        (
            ValidationError.from_exception_data("test", []),
            HarnessErrorKind.CONFIGURATION_INVALID,
            False,
        ),
        (ValueError("bad value"), HarnessErrorKind.CONFIGURATION_INVALID, False),
        (RuntimeError("unknown"), HarnessErrorKind.UNKNOWN, False),
    ],
)
def test_sdk_host_classifies_runtime_errors(
    error: BaseException, kind: HarnessErrorKind, retryable: bool
) -> None:
    assert _error_kind(error) == (kind, retryable)


def test_sdk_host_failure_is_safe_and_retains_provider_events() -> None:
    result = _failure(
        HarnessErrorKind.UNKNOWN,
        RuntimeError("sensitive detail"),
        retryable=True,
        provider_events=[{"method": "turn/started", "payload": {}}],
    )

    assert result["provider_events"] == [{"method": "turn/started", "payload": {}}]
    error = cast(dict[str, object], result["error"])
    assert error["kind"] == "UNKNOWN"
    assert error["retryable"] is True
    assert len(cast(str, error["message_hash"])) == 64
    assert "sensitive detail" not in json.dumps(result)
    assert result["failure_diagnostic"] == {
        "phase": "REQUEST_PARSE",
        "exception_class": "RuntimeError",
        "details_retention": "HASH_ONLY",
    }


@pytest.mark.parametrize(
    ("message", "retention"),
    [
        ("benign fixture detail", "RETAINED"),
        ("Authorization: Bearer synthetic-invalid-credential", "CREDENTIAL_GUARD"),
        ("x" * 4097, "OVER_BYTE_CAP"),
    ],
)
def test_sdk_host_later_diagnostics_remain_bounded_and_credential_guarded(
    message: str, retention: str
) -> None:
    result = _failure(
        HarnessErrorKind.UNKNOWN, RuntimeError(message), retryable=False, phase="ACCOUNT_READ"
    )
    diagnostic = cast(dict[str, object], result["failure_diagnostic"])
    assert diagnostic["details_retention"] == retention
    assert message not in json.dumps(result["error"])
    if retention == "RETAINED":
        assert diagnostic["details"] == f"RuntimeError: {message}"
    else:
        assert "details" not in diagnostic


@pytest.mark.parametrize("payload", [b"", b"{}", b"not-json"])
def test_sdk_host_rejects_invalid_request_without_starting_runtime(
    tmp_path: Path, payload: bytes
) -> None:
    environment = {
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
        "CODEX_HOME": str(tmp_path / "isolated-codex-home"),
    }
    result = subprocess.run(
        (sys.executable, "-m", "quantos.integrations.codex.sdk_host"),
        input=payload,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0
    response = cast(dict[str, object], json.loads(result.stdout))
    error = cast(dict[str, object], response["error"])
    assert error["kind"] == "CONFIGURATION_INVALID"
    assert len(cast(str, error["message_hash"])) == 64
    assert response["provider_events"] == []
    assert result.stderr == b""
    assert "TUSHARE_TOKEN" not in environment


def test_adapter_timeout_terminates_the_complete_host_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    host_code = (
        "import subprocess,sys,time;"
        "child=subprocess.Popen(['/bin/sleep','60']);"
        "open(sys.argv[1],'w').write(str(child.pid));"
        "time.sleep(60)"
    )
    environment = (
        HarnessEnvironmentVariable(name="LANG", value="C.UTF-8"),
        HarnessEnvironmentVariable(name="PATH", value="/usr/bin:/bin"),
        HarnessEnvironmentVariable(name="TZ", value="UTC"),
    )
    request = HarnessExecutionRequest(
        run_id="sdk-timeout-process-tree-test",
        cwd=str(tmp_path),
        prompt="unused",
        model="unused",
        reasoning_effort="medium",
        runtime_policy=HarnessRuntimePolicy(
            host_environment=environment,
            child_environment=environment,
            shell_environment=environment,
            shell_tool_enabled=False,
        ),
        mcp_servers=(),
        timeout_seconds=1,
        total_timeout_seconds=1,
        max_transcript_bytes=10_000,
        max_input_tokens=10,
        max_output_tokens=10,
    )
    adapter = CodexSdkAdapter(
        authentication_home=tmp_path,
        host_argv=(sys.executable, "-c", host_code, str(child_pid_path)),
    )

    result = adapter.execute(request)

    assert result.terminal_error is not None
    assert result.terminal_error.kind is HarnessErrorKind.TIMEOUT
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not Path(f"/proc/{child_pid}").exists()


@pytest.mark.parametrize("actual_model", ["gpt-6.1-sol", "different-model"])
@pytest.mark.parametrize("expanded_inventory", [False, True])
def test_gpt61_host_retains_provider_identity_and_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    actual_model: str,
    expanded_inventory: bool,
) -> None:
    import codex_cli_bin
    import openai_codex

    import quantos.integrations.codex.sdk_host as host

    marker = SimpleNamespace(model_dump=lambda **_: {"type": "readOnly", "networkAccess": False})
    response = SimpleNamespace(
        model=actual_model,
        model_provider="openai",
        reasoning_effort=SimpleNamespace(value="medium"),
        sandbox=marker,
        approval_policy=marker,
        cwd=str(tmp_path),
    )
    called: list[str] = []
    client = SimpleNamespace(
        thread_start=lambda _: response,
        request=lambda *_, **__: SimpleNamespace(
            data=[
                SimpleNamespace(
                    name="probe",
                    tools={"read_fixture": {}},
                    tools_error=None,
                )
            ]
            + (
                [SimpleNamespace(name="extra", tools={"write": {}}, tools_error=None)]
                if expanded_inventory
                else []
            ),
            next_cursor=None,
        ),
    )

    class FakeCodex:
        def __init__(self, _: object) -> None:
            assert _.config_overrides == ("features.apps=false",)
            self._client = client
            self.metadata = SimpleNamespace(serverInfo=SimpleNamespace(version="0.162.1"))

        def __enter__(self) -> FakeCodex:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def account(self, **kwargs: object) -> object:
            return SimpleNamespace(account=object())

        def thread_start(self, **kwargs: object) -> object:
            self._client.thread_start(kwargs)
            return SimpleNamespace(id="thread", turn=self.turn)

        def turn(self, *args: object, **kwargs: object) -> object:
            called.append("turn")
            return SimpleNamespace(stream=lambda: iter(()))

    monkeypatch.setenv("QUANTOS_CODEX_RUNTIME_CANDIDATE_ID", "openai-codex-0.162.1-gpt61-fr03")
    monkeypatch.setattr(openai_codex, "__version__", "0.162.1")
    monkeypatch.setattr(openai_codex, "Codex", FakeCodex)
    monkeypatch.setattr(codex_cli_bin, "bundled_codex_path", lambda: tmp_path)
    monkeypatch.setattr(host, "version", lambda _: "0.162.1")
    monkeypatch.setattr(host, "_sha256_file", lambda _: "a" * 64)
    request = _request(tmp_path).model_copy(
        update={"model": "gpt-6.1-sol", "reasoning_effort": "medium"}
    )
    request = request.model_copy(
        update={
            "runtime_policy": request.runtime_policy.model_copy(
                update={"shell_tool_enabled": False}
            )
        }
    )
    result = sdk_host_execute(request)
    assert _sdk_config(request)["features"] == {"shell_tool": False, "apps": False}
    if actual_model == "gpt-6.1-sol" and expanded_inventory:
        assert called == []
        assert cast(dict[str, object], result["error"])["kind"] == "PERMISSION_DENIED"
        observation = cast(dict[str, object], result["qualification_observations"])
        assert observation["exact_mcp_inventory_matches"] is False
        assert observation["model_turn_started"] is False
        assert result["sdk_version"] == result["runtime_package_version"] == "0.162.1"
    elif actual_model == "gpt-6.1-sol":
        assert called == ["turn"]
        observation = cast(dict[str, object], result["qualification_observations"])
        assert observation["provider_model_identifier"] == actual_model
        assert observation["provider_reasoning_effort"] == "medium"
        assert observation["mcp_inventory"] == {
            "servers": [{"name": "probe", "tools": ["read_fixture"], "tools_error": None}],
            "next_cursor": None,
        }
    else:
        assert called == []
        assert cast(dict[str, object], result["error"])["kind"] == "CONFIGURATION_INVALID"
