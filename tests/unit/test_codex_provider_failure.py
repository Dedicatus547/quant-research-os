"""Synthetic provider errors only; no SDK transport or scientific execution."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest
from test_codex_sdk_adapter import _request, _response
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401

from quantos.application.agent_harness import HarnessExecutionResult
from quantos.application.sdk_producer import _persist_host_transport
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import AgentEventKind, HarnessErrorKind
from quantos.integrations.codex.event_normalizer import (
    NORMALIZER_IDENTIFIER,
    PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
    CodexEventNormalizationError,
    normalize_provider_events,
    normalize_provider_failure_events,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter, _host_transport_capture


def _failure_response(*, will_retry=False, code="serverOverloaded", final_message=False):
    response = json.loads(_response())
    error = {"codex_error_info": code, "message": "synthetic provider unavailable"}
    events = response["provider_events"]
    if not final_message:
        events[:] = [events[0], events[-1]]
    events.insert(
        1,
        {
            "method": "error",
            "payload": {
                "thread_id": "thread-test",
                "turn_id": "turn-test",
                "will_retry": will_retry,
                "error": error,
            },
        },
    )
    events[-1]["payload"]["turn"].update(status="failed", error=error)
    return canonical_json_bytes(response)


def _fake_provider(monkeypatch, response):
    calls = []

    class FakeProvider:
        returncode = 0
        pid = 123

        def __init__(self, *_args, **_kwargs):
            calls.append(1)

        def communicate(self, _payload, timeout):
            assert timeout > 0
            return response, b""

    monkeypatch.setattr(subprocess, "Popen", FakeProvider)
    return calls


def _safety_failure_response():
    response = json.loads(_failure_response(final_message=True))
    tool = {
        "type": "mcpToolCall",
        "server": "fixture",
        "tool": "read",
        "arguments": {"hash": "a" * 64},
        "result": None,
        "error": None,
    }
    command = {
        "id": "command-test",
        "type": "commandExecution",
        "command": "/usr/bin/pwd",
        "aggregated_output": "",
    }
    safety = [
        {"method": "item/started", "payload": {"item": {**tool, "status": "inProgress"}}},
        {"method": "item/completed", "payload": {"item": {**tool, "status": "failed"}}},
        {
            "method": "item/started",
            "payload": {
                "thread_id": "thread-test",
                "turn_id": "turn-test",
                "item": {**command, "status": "inProgress", "exit_code": None},
            },
        },
        {
            "method": "item/completed",
            "payload": {
                "thread_id": "thread-test",
                "turn_id": "turn-test",
                "item": {**command, "status": "failed", "exit_code": 1},
            },
        },
        {"method": "item/commandExecution/requestApproval", "payload": {}},
    ]
    response["provider_events"][1:1] = safety
    return canonical_json_bytes(response)


def test_failure_projection_retains_tools_commands_approval_and_usage(tmp_path, monkeypatch):
    calls = _fake_provider(monkeypatch, _safety_failure_response())
    result = CodexSdkAdapter(authentication_home=tmp_path).execute(_request(tmp_path))
    assert result.terminal_error.kind is HarnessErrorKind.OVERLOADED
    assert not result.terminal_error.retryable and len(calls) == 1
    assert len(result.capture.tool_calls) == 1
    assert result.capture.tool_calls[0].status == "failed"
    assert len(result.capture.commands) == 1 and result.capture.commands[0].exit_code == 1
    assert result.capture.command_lifecycle_integrity is True
    assert result.capture.approval_requested is True
    assert result.capture.usage["input_tokens"] == 10
    assert result.capture.usage["output_tokens"] == 2
    assert result.capture.agent_messages == ()


@pytest.mark.parametrize("will_retry", [False, True])
def test_overload_is_classified_without_proposal_or_retry(tmp_path, monkeypatch, will_retry):
    response = _failure_response(will_retry=will_retry, final_message=True)
    calls = _fake_provider(monkeypatch, response)
    result = CodexSdkAdapter(authentication_home=tmp_path).execute(
        _request(tmp_path).model_copy(update={"max_attempts": 3})
    )
    assert result.terminal_error.kind is HarnessErrorKind.OVERLOADED
    assert result.terminal_error.retryable is False
    assert result.capture.agent_messages == ()
    assert result.capture.turn_failed
    assert len(result.attempts) == len(calls) == 1
    observed = result.attempts[-1].qualification_observations["provider_failure"]
    assert observed["normalizer_identifier"] == PROVIDER_FAILURE_NORMALIZER_IDENTIFIER
    assert observed["provider_errors"][0]["will_retry"] is will_retry
    events = [json.loads(line) for line in result.normalized_transcript.splitlines()]
    error = next(item for item in events if item["kind"] == AgentEventKind.HARNESS_ERROR.value)
    assert error["payload"]["provider_error_code"] == "serverOverloaded"
    assert error["payload"]["normalizer_identifier"] == PROVIDER_FAILURE_NORMALIZER_IDENTIFIER
    assert b"synthetic provider unavailable" not in result.normalized_transcript


def test_unknown_provider_code_is_observed_without_protocol_reclassification():
    response = json.loads(_failure_response(code="futureProviderFailure"))
    normalized = normalize_provider_failure_events(
        response["provider_events"], thread_id="thread-test"
    )
    assert normalized.terminal_error.kind is HarnessErrorKind.UNKNOWN
    assert (
        normalized.observation["provider_errors"][0]["provider_error_code"]
        == "futureProviderFailure"
    )
    assert normalized.terminal_error.retryable is False


def test_terminal_turn_error_without_error_notification_keeps_failure_code():
    response = json.loads(_failure_response())
    response["provider_events"].pop(1)
    normalized = normalize_provider_failure_events(
        response["provider_events"], thread_id="thread-test"
    )
    assert normalized.terminal_error.kind is HarnessErrorKind.OVERLOADED
    assert normalized.observation["provider_errors"][0]["will_retry"] is None


def test_success_and_historical_v2_entry_remain_unchanged():
    success = json.loads(_response())["provider_events"]
    before = normalize_provider_events(success, thread_id="thread-test")
    assert normalize_provider_failure_events(success, thread_id="thread-test") is None
    assert normalize_provider_events(success, thread_id="thread-test") == before
    assert NORMALIZER_IDENTIFIER == "quantos-codex-normalizer/v2"
    with pytest.raises(CodexEventNormalizationError):
        normalize_provider_events(
            json.loads(_failure_response())["provider_events"], thread_id="thread-test"
        )


@pytest.mark.parametrize("defect", ["thread", "turn", "retry"])
def test_provider_failure_identity_and_observation_fail_closed(defect):
    events = json.loads(_failure_response())["provider_events"]
    payload = events[1]["payload"]
    payload[{"thread": "thread_id", "turn": "turn_id", "retry": "will_retry"}[defect]] = "invalid"
    with pytest.raises(CodexEventNormalizationError):
        normalize_provider_failure_events(events, thread_id="thread-test")


@pytest.mark.parametrize("safety_observations", [False, True])
def test_producer_persists_failure_observation(
    sdk_setup,  # noqa: F811
    tmp_path,
    monkeypatch,
    safety_observations,
):
    _, spec, request, producer, _ = sdk_setup
    calls = _fake_provider(
        monkeypatch, _safety_failure_response() if safety_observations else _failure_response()
    )
    adapter = CodexSdkAdapter(authentication_home=tmp_path)
    with pytest.raises(ArtifactIntegrityError, match="immutable failure"):
        producer.launch(request, spec, harness=adapter)
    directory = producer.root / request.campaign_hash / request.content_hash
    encoded = (directory / "host-transport.json").read_bytes()
    metadata = json.loads(encoded)
    observed = metadata["provider_failure"]
    assert metadata["schema_version"] == "sdk-host-transport/v2"
    assert observed["normalizer_identifier"] == PROVIDER_FAILURE_NORMALIZER_IDENTIFIER
    assert observed["projection"] == "FAILURE_ONLY"
    assert observed["provider_errors"][0]["provider_error_code"] == "serverOverloaded"
    assert observed["provider_errors"][0]["will_retry"] is False
    assert observed["provider_errors"][0]["message_bytes"] == len(b"synthetic provider unavailable")
    assert b"synthetic provider unavailable" not in encoded
    fact = json.loads((directory / "capture-fact.json").read_bytes())
    assert fact["host_transport_hash"] == sha256_bytes(encoded)
    assert fact["terminal_error"]["kind"] == "OVERLOADED"
    assert fact["observed_tool_calls"] == int(safety_observations)
    manifest = json.loads((directory / "agent-run-manifest.json").read_bytes())
    observation = json.loads((directory / "capability-observation.json").read_bytes())
    assert manifest["aggregate_usage"]["tool_calls"] == 0
    assert manifest["attempts"][0]["usage"]["tool_calls"] == 0
    assert observation["approval_request_observed"] is safety_observations
    assert observation["command_count"] == int(safety_observations)
    safety = observed["safety_observations"]
    assert safety["observed_tool_calls"] == int(safety_observations)
    assert safety["observed_tool_started_events"] == int(safety_observations)
    assert safety["observed_approval_requested"] is safety_observations
    assert "MANIFEST_TOOL_USAGE_NOT_OBSERVATION" in safety["limitations"]
    if safety_observations:
        assert safety["observed_usage"]["input_tokens"] == 10
        assert safety["observed_usage"]["output_tokens"] == 2
        assert safety["usage_observation_status"] == "OBSERVED"
        assert "MANIFEST_TOOL_USAGE_UNAVAILABLE_FOR_UNMAPPED_PROVIDER_TOOL" in safety["limitations"]
    else:
        assert safety["observed_usage"] is None
        assert safety["usage_observation_status"] == "UNAVAILABLE"
    assert producer.status(request, spec) == "FAILED"
    assert not (directory / "response.json").exists()
    with pytest.raises(ArtifactIntegrityError, match="automatic reissue forbidden"):
        producer.launch(request, spec, harness=adapter)
    assert len(calls) == 1


def test_success_transport_metadata_keeps_existing_v1_bytes(tmp_path, monkeypatch):
    _fake_provider(monkeypatch, _response())
    result = CodexSdkAdapter(authentication_home=tmp_path).execute(_request(tmp_path))
    diagnostic = _host_transport_capture(
        None, None, phase="TEST", exception_class=None, complete=True
    )
    result = HarnessExecutionResult(
        attempts=(
            replace(result.attempts[0], qualification_observations={"host_transport": diagnostic}),
        )
    )
    output = tmp_path / "persist"
    _persist_host_transport(output, result)
    expected = {key: diagnostic[key] for key in ("schema_version", "phase", "exception_class")}
    expected["streams"] = diagnostic["streams"]
    assert (output / "host-transport.json").read_bytes() == canonical_json_bytes(expected)
