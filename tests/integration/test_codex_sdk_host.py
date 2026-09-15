from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

import pytest

from quantos.contracts import (
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessRuntimePolicy,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter


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
