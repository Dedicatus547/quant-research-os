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
