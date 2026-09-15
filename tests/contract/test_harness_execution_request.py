from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    HarnessEnvironmentVariable,
    HarnessExecutionRequest,
    HarnessRuntimePolicy,
)


def _request(tmp_path: Path) -> HarnessExecutionRequest:
    environment = (
        HarnessEnvironmentVariable(name="LANG", value="C.UTF-8"),
        HarnessEnvironmentVariable(name="PATH", value="/usr/bin:/bin"),
        HarnessEnvironmentVariable(name="TZ", value="UTC"),
    )
    return HarnessExecutionRequest(
        run_id="contract-test",
        cwd=str(tmp_path),
        prompt="return a proposal",
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
        retry_backoff_milliseconds=100,
        max_transcript_bytes=100_000,
        max_input_tokens=1_000,
        max_output_tokens=100,
        max_attempts=3,
    )


def test_execution_request_v2_binds_retry_and_total_timeout_policy(tmp_path: Path) -> None:
    request = _request(tmp_path)

    assert request.schema_version == "harness-execution-request/v2"
    assert (
        request.content_hash
        != request.model_copy(update={"retry_backoff_milliseconds": 101}).content_hash
    )
    assert (
        request.content_hash
        != request.model_copy(update={"total_timeout_seconds": 31}).content_hash
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("total_timeout_seconds", 9, "total harness timeout"),
        ("retry_backoff_milliseconds", 5_001, "less than or equal to 5000"),
        ("max_attempts", 4, "less than or equal to 3"),
    ],
)
def test_execution_request_v2_rejects_unbounded_retry_policy(
    tmp_path: Path, field: str, value: int, message: str
) -> None:
    payload = _request(tmp_path).model_dump(mode="python")

    with pytest.raises(ValidationError, match=message):
        HarnessExecutionRequest.model_validate({**payload, field: value})
