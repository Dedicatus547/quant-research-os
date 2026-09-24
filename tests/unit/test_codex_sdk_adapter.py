from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

import pytest

from quantos.application.agent_harness import HarnessAttemptResult
from quantos.contracts import (
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessRuntimePolicy,
    canonical_json_bytes,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.integrations.codex.versioning import expected_codex_versions


def _request(tmp_path: Path) -> HarnessExecutionRequest:
    environment = (
        HarnessEnvironmentVariable(name="LANG", value="C.UTF-8"),
        HarnessEnvironmentVariable(name="PATH", value="/usr/bin:/bin"),
        HarnessEnvironmentVariable(name="TZ", value="UTC"),
    )
    return HarnessExecutionRequest(
        run_id="sdk-adapter-test",
        cwd=str(tmp_path),
        prompt="return an object",
        model="gpt-test",
        reasoning_effort="medium",
        runtime_policy=HarnessRuntimePolicy(
            host_environment=environment,
            child_environment=environment,
            shell_environment=environment,
            shell_tool_enabled=False,
        ),
        mcp_servers=(),
        timeout_seconds=10,
        total_timeout_seconds=30,
        max_transcript_bytes=100_000,
        max_input_tokens=1_000,
        max_output_tokens=100,
    )


def _response() -> bytes:
    events = [
        {
            "method": "turn/started",
            "payload": {
                "thread_id": "thread-test",
                "turn": {"id": "turn-test", "status": "inProgress", "error": None},
            },
        },
        {
            "method": "item/completed",
            "payload": {"item": {"type": "agentMessage", "text": "{}", "phase": "final_answer"}},
        },
        {
            "method": "thread/tokenUsage/updated",
            "payload": {
                "token_usage": {
                    "last": {
                        "input_tokens": 10,
                        "cached_input_tokens": 0,
                        "output_tokens": 2,
                    }
                }
            },
        },
        {
            "method": "turn/completed",
            "payload": {
                "thread_id": "thread-test",
                "turn": {"id": "turn-test", "status": "completed", "error": None},
            },
        },
    ]
    return canonical_json_bytes(
        {
            "provider_events": events,
            "runtime_package_version": "0.154.0",
            "runtime_version": "0.154.0 test",
            "runtime_binary_hash": "a" * 64,
            "sdk_version": "0.154.0",
            "thread_id": "thread-test",
        }
    )


def test_adapter_starts_host_with_exact_environment_and_isolated_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_home = tmp_path / "auth-home"
    auth_home.mkdir()
    (auth_home / "auth.json").write_text("synthetic", encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeProcess:
        returncode = 0
        pid = 123

        def __init__(self, *_args: object, **kwargs: object) -> None:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            typed_environment = cast(dict[str, str], environment)
            codex_home = Path(typed_environment["CODEX_HOME"])
            observed["environment"] = dict(typed_environment)
            observed["auth_is_symlink"] = (codex_home / "auth.json").is_symlink()

        def communicate(self, payload: bytes, timeout: int) -> tuple[bytes, bytes]:
            observed["request"] = json.loads(payload)
            observed["timeout"] = timeout
            return _response(), b"unpersisted diagnostic"

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    result = CodexSdkAdapter(authentication_home=auth_home).execute(_request(tmp_path))

    assert observed["auth_is_symlink"] is True
    observed_environment = cast(dict[str, str], observed["environment"])
    assert observed_environment == {
        "CODEX_HOME": observed_environment["CODEX_HOME"],
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
    }
    assert "TUSHARE_TOKEN" not in observed_environment
    assert result.terminal_error is None
    assert result.runtime is not None and result.runtime.sdk_version == "0.154.0"
    assert result.runtime.runtime_package_version == "0.154.0"
    assert result.capture.agent_messages == ("{}",)


def test_adapter_candidate_profile_is_explicit_and_allowlisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    class CandidateProcess:
        returncode = 0
        pid = 124

        def __init__(self, *_args: object, **kwargs: object) -> None:
            environment = cast(dict[str, str], kwargs["env"])
            observed["environment"] = dict(environment)

        def communicate(self, _payload: bytes, timeout: float) -> tuple[bytes, bytes]:
            assert timeout > 0
            response = cast(dict[str, object], json.loads(_response()))
            response["sdk_version"] = "0.156.1"
            response["runtime_package_version"] = "0.156.1"
            response["runtime_version"] = "0.156.1 test"
            return canonical_json_bytes(response), b""

    monkeypatch.setattr(subprocess, "Popen", CandidateProcess)
    adapter = CodexSdkAdapter(
        authentication_home=tmp_path,
        runtime_candidate_id="openai-codex-0.156.1-p10-v3",
    )

    result = adapter.execute(_request(tmp_path))

    environment = cast(dict[str, str], observed["environment"])
    assert environment["QUANTOS_CODEX_RUNTIME_CANDIDATE_ID"] == "openai-codex-0.156.1-p10-v3"
    assert result.terminal_error is None
    assert result.runtime is not None and result.runtime.sdk_version == "0.156.1"
    assert result.runtime.runtime_package_version == "0.156.1"
    with pytest.raises(ValueError, match="unsupported Codex runtime candidate"):
        CodexSdkAdapter(runtime_candidate_id="openai-codex-latest")
    assert expected_codex_versions(None) == ("0.154.0", "0.154.0")
    assert expected_codex_versions("openai-codex-0.156.1-p10-v3") == ("0.156.1", "0.156.1")
    assert expected_codex_versions("openai-codex-latest") is None


def test_adapter_timeout_becomes_hashed_failure_without_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TimeoutProcess:
        returncode = None
        pid = 123

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, _payload: bytes, timeout: int) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired("sdk-host", timeout)

    terminated: list[int] = []

    def terminate(process: subprocess.Popen[bytes]) -> None:
        terminated.append(process.pid)

    monkeypatch.setattr(subprocess, "Popen", TimeoutProcess)
    monkeypatch.setattr(
        CodexSdkAdapter,
        "_terminate_process_group",
        staticmethod(terminate),
    )

    result = CodexSdkAdapter(authentication_home=tmp_path).execute(_request(tmp_path))

    assert terminated == [123]
    assert result.terminal_error is not None
    assert result.terminal_error.kind is HarnessErrorKind.TIMEOUT
    assert result.capture.agent_messages == ()
    assert result.provider_transcript is None


def test_adapter_rejects_missing_runtime_package_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MissingIdentityProcess:
        returncode = 0
        pid = 123

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, _payload: bytes, timeout: float) -> tuple[bytes, bytes]:
            assert timeout > 0
            response = cast(dict[str, object], json.loads(_response()))
            response.pop("runtime_package_version")
            return canonical_json_bytes(response), b""

    monkeypatch.setattr(subprocess, "Popen", MissingIdentityProcess)

    result = CodexSdkAdapter(authentication_home=tmp_path).execute(_request(tmp_path))

    assert result.terminal_error is not None
    assert result.terminal_error.kind is HarnessErrorKind.RUNTIME_MISMATCH
    assert result.runtime is None


def test_adapter_retries_only_retryable_errors_and_preserves_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = CodexSdkAdapter(authentication_home=tmp_path)
    attempts = iter(
        (
            adapter._failed_result(
                HarnessErrorKind.OVERLOADED,
                RuntimeError("synthetic overload"),
                retryable=True,
                attempt=1,
            ),
            adapter._failed_result(
                HarnessErrorKind.OUTPUT_INVALID,
                RuntimeError("synthetic terminal failure"),
                attempt=2,
            ),
        )
    )

    def execute_once(
        _request: HarnessExecutionRequest, *, attempt_index: int, timeout_seconds: float
    ) -> HarnessAttemptResult:
        assert timeout_seconds > 0
        result = next(attempts)
        assert result.capture.attempt_index == attempt_index
        return result

    monkeypatch.setattr(adapter, "_execute_once", execute_once)
    request = _request(tmp_path).model_copy(update={"max_attempts": 3})

    result = adapter.execute(request)

    assert [item.capture.attempt_index for item in result.attempts] == [1, 2]
    assert result.attempts[0].terminal_error is not None
    assert result.attempts[0].terminal_error.retryable is True
    assert result.terminal_error is not None
    assert result.terminal_error.kind is HarnessErrorKind.OUTPUT_INVALID


@pytest.mark.parametrize("environment_name", ["P10_FORBIDDEN_SECRET", "TUSHARE_TOKEN"])
def test_adapter_rejects_parent_secret_echo_without_retaining_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment_name: str
) -> None:
    secret = "synthetic-parent-secret-that-must-not-persist"
    monkeypatch.setenv(environment_name, secret)

    class LeakingProcess:
        returncode = 0
        pid = 123

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def communicate(self, _payload: bytes, timeout: float) -> tuple[bytes, bytes]:
            assert timeout > 0
            return _response().replace(b'"{}"', json.dumps(secret).encode()), b""

    monkeypatch.setattr(subprocess, "Popen", LeakingProcess)

    result = CodexSdkAdapter(authentication_home=tmp_path).execute(_request(tmp_path))

    assert result.terminal_error is not None
    assert result.terminal_error.kind is HarnessErrorKind.PERMISSION_DENIED
    assert result.provider_transcript is None
    assert secret.encode() not in result.normalized_transcript
