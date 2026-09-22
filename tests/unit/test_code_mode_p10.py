from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.application.agent_harness import (
    HarnessAttemptResult,
    HarnessExecutionResult,
    capture_from_agent_events,
)
from quantos.application.harness_runner import (
    P10ArtifactVerificationError,
    _failure_reason,
    _normalizer_hash,
    _parse_provider_event_jsonl,
    _publish_sdk_run_artifacts,
    _sdk_request,
    _sdk_run_spec,
    _sdk_spike_spec,
    _verify_p10_secret_absence,
    execute_codex_spike,
    load_frozen_spike_inputs,
    safe_result_summary,
    verify_codex_spike_artifact,
)
from quantos.application.harness_spike import (
    build_harness_spike_report_v3,
    build_p10_capability_observation,
    build_p10_capability_observation_v2,
    evaluate_harness_capture_v3,
)
from quantos.contracts import (
    AgentCapability,
    AgentRunManifestV3,
    AgentUsage,
    HarnessAttemptRecord,
    HarnessCapability,
    HarnessCapabilityObservationV2,
    HarnessCapabilitySpikeReportV3,
    HarnessCapabilitySpikeSpecV3,
    HarnessDecision,
    HarnessErrorKind,
    HarnessObservationState,
    HarnessRuntimeIdentityV2,
    RunStatus,
    ToolInteractionDigest,
    canonical_json_bytes,
    sha256_bytes,
)
from quantos.integrations.codex.event_normalizer import normalize_provider_events
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.integrations.codex.versioning import (
    CODEX_PROTOCOL_IDENTIFIER,
    CODEX_RUNTIME_PACKAGE_VERSION,
    CODEX_SDK_VERSION,
)

FIXTURE = Path("tests/fixtures/p10_codex_workspace_v3")
LEGACY_FIXTURE = Path("tests/fixtures/p10_codex_workspace")
NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)


def _command_events(
    item_id: str,
    command: str,
    output: str,
    exit_code: int,
) -> list[dict[str, object]]:
    envelope = {"thread_id": "thread-p10-v3", "turn_id": "turn-p10-v3"}
    return [
        {
            "method": "item/started",
            "payload": {
                **envelope,
                "item": {
                    "id": item_id,
                    "type": "commandExecution",
                    "command": command,
                    "aggregated_output": None,
                    "exit_code": None,
                    "status": "inProgress",
                },
            },
        },
        {
            "method": "item/completed",
            "payload": {
                **envelope,
                "item": {
                    "id": item_id,
                    "type": "commandExecution",
                    "command": command,
                    "aggregated_output": output,
                    "exit_code": exit_code,
                    "status": "completed",
                },
            },
        },
    ]


def _provider_events(
    *, network_output: str = "curl: (7) Operation not permitted\n"
) -> list[dict[str, object]]:
    baseline = json.loads((FIXTURE / "manual_baseline.json").read_text(encoding="utf-8"))
    events: list[dict[str, object]] = [
        {
            "method": "turn/started",
            "payload": {
                "thread_id": "thread-p10-v3",
                "turn": {"id": "turn-p10-v3", "status": "inProgress", "error": None},
            },
        },
        {
            "method": "item/completed",
            "payload": {
                "item": {
                    "type": "mcpToolCall",
                    "server": "quantosP10",
                    "tool": "dataset_describe",
                    "arguments": {
                        "dataset_hash": "a" * 64,
                        "skill_nonce": "P10_SKILL_20260907",
                    },
                    "result": {
                        "structured_content": {
                            "dataset_hash": "a" * 64,
                            "fields": ["adjusted_close", "membership", "tradable"],
                            "fixture_kind": "SYNTHETIC",
                            "row_count": 3,
                        }
                    },
                    "error": None,
                    "status": "completed",
                }
            },
        },
    ]
    events.extend(
        _command_events(
            "secret",
            '/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"',
            "",
            0,
        )
    )
    events.extend(
        _command_events(
            "write",
            "/usr/bin/python3 write_probe.py",
            "PermissionError: [Errno 30] Read-only file system: 'should-not-exist'\n",
            1,
        )
    )
    events.extend(
        _command_events(
            "network",
            "/usr/bin/curl --max-time 2 -fsS https://example.com",
            network_output,
            6,
        )
    )
    events.extend(_command_events("recovery", "/usr/bin/pwd", "/fixture\n", 0))
    events.extend(
        [
            {
                "method": "item/completed",
                "payload": {
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": json.dumps(baseline, separators=(",", ":"), sort_keys=True),
                    }
                },
            },
            {
                "method": "thread/tokenUsage/updated",
                "payload": {
                    "token_usage": {
                        "last": {
                            "input_tokens": 2_000,
                            "cached_input_tokens": 1_000,
                            "output_tokens": 300,
                        }
                    }
                },
            },
            {
                "method": "turn/completed",
                "payload": {
                    "thread_id": "thread-p10-v3",
                    "turn": {"id": "turn-p10-v3", "status": "completed", "error": None},
                },
            },
        ]
    )
    return events


def _capture(events: list[dict[str, object]] | None = None):
    normalized = normalize_provider_events(events or _provider_events(), thread_id="thread-p10-v3")
    return capture_from_agent_events(normalized, max_bytes=2_000_000)


def _spec():
    inputs = load_frozen_spike_inputs(FIXTURE)
    return _sdk_spike_spec(inputs, _sdk_request(inputs))


def test_code_mode_fixture_is_versioned_without_mutating_legacy_inputs() -> None:
    assert sha256_bytes((LEGACY_FIXTURE / "task.md").read_bytes()) == (
        "976a1c27fb74b7e805c2fe5278042acb97539dc9401acc54daadaa031ac0f471"
    )
    inputs = load_frozen_spike_inputs(FIXTURE)
    assert "Code Mode `exec`" in inputs.task_text
    assert inputs.task_hash != sha256_bytes((LEGACY_FIXTURE / "task.md").read_bytes())


def test_code_mode_capture_passes_unchanged_nine_of_nine_gate() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    capture = _capture()

    checks = evaluate_harness_capture_v3(
        _spec(),
        capture,
        inputs.manual_baseline,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    observation = build_p10_capability_observation_v2(
        capture,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )

    assert all(check.passed for check in checks)
    assert len(checks) == 9
    assert observation.code_mode_exec_initiated is HarnessObservationState.UNKNOWN
    assert observation.nested_exec_command_dispatched is HarnessObservationState.UNKNOWN
    assert observation.matched_command_count == 4
    assert observation.command_lifecycle_integrity is True
    assert observation.filesystem_denial_observed is True
    assert observation.network_denial_observed is True
    assert observation.recovery_observed is True

    unretained_checks = evaluate_harness_capture_v3(
        _spec(),
        capture,
        inputs.manual_baseline,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash=None,
    )
    assert (
        next(
            check for check in unretained_checks if check.capability is HarnessCapability.TRANSCRIPT
        ).passed
        is False
    )

    legacy_observation = build_p10_capability_observation(
        capture,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    assert legacy_observation.command_count == 4
    assert legacy_observation.recovery_observed is True


def test_ambiguous_network_failure_cannot_pass_sandbox_or_recovery() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    capture = _capture(
        _provider_events(network_output="curl: (6) Could not resolve host: example.com\n")
    )

    checks = evaluate_harness_capture_v3(
        _spec(),
        capture,
        inputs.manual_baseline,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    failed = {check.capability for check in checks if not check.passed}

    assert HarnessCapability.SANDBOX in failed
    assert HarnessCapability.FAILURE_RECOVERY in failed


def test_duplicate_probe_and_missing_start_fail_closed() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    duplicate = _provider_events()
    duplicate[-3:-3] = _command_events(
        "write-duplicate",
        "/usr/bin/python3 write_probe.py",
        "Operation not permitted\n",
        1,
    )
    duplicate_capture = _capture(duplicate)
    duplicate_checks = evaluate_harness_capture_v3(
        _spec(),
        duplicate_capture,
        inputs.manual_baseline,
        normalized_transcript_hash=duplicate_capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    duplicate_failed = {check.capability for check in duplicate_checks if not check.passed}
    assert HarnessCapability.SANDBOX in duplicate_failed
    assert HarnessCapability.FAILURE_RECOVERY in duplicate_failed

    missing_start = _provider_events()
    del missing_start[2]
    incomplete = _capture(missing_start)
    incomplete_checks = evaluate_harness_capture_v3(
        _spec(),
        incomplete,
        inputs.manual_baseline,
        normalized_transcript_hash=incomplete.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    incomplete_failed = {check.capability for check in incomplete_checks if not check.passed}
    assert incomplete.command_lifecycle_integrity is False
    assert {
        HarnessCapability.SANDBOX,
        HarnessCapability.PERMISSION_DENIAL,
        HarnessCapability.FAILURE_RECOVERY,
        HarnessCapability.TRANSCRIPT,
    } <= incomplete_failed


def test_observation_rejects_behavior_claim_without_matched_lifecycle() -> None:
    with pytest.raises(ValidationError, match="without matched lifecycles"):
        HarnessCapabilityObservationV2(
            code_mode_exec_initiated=HarnessObservationState.UNKNOWN,
            nested_exec_command_dispatched=HarnessObservationState.UNKNOWN,
            command_started_count=0,
            command_terminal_count=0,
            matched_command_count=0,
            command_lifecycle_integrity=True,
            filesystem_denial_observed=False,
            approval_request_observed=False,
            normalized_transcript_hash="a" * 64,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"command_started_count": 0, "command_terminal_count": 1, "matched_command_count": 1},
        {
            "command_started_count": 1,
            "command_terminal_count": 1,
            "matched_command_count": 1,
            "command_lifecycle_integrity": False,
        },
        {
            "command_started_count": 2,
            "command_terminal_count": 1,
            "matched_command_count": 1,
            "command_lifecycle_integrity": False,
            "filesystem_denial_observed": True,
        },
    ],
)
def test_observation_rejects_inconsistent_lifecycle_claims(
    updates: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "code_mode_exec_initiated": "UNKNOWN",
        "nested_exec_command_dispatched": "UNKNOWN",
        "command_started_count": 0,
        "command_terminal_count": 0,
        "matched_command_count": 0,
        "command_lifecycle_integrity": True,
        "approval_request_observed": False,
        "normalized_transcript_hash": "a" * 64,
    }

    with pytest.raises(ValidationError):
        HarnessCapabilityObservationV2.model_validate({**payload, **updates})


@pytest.mark.parametrize(
    "field,value",
    [
        ("required_capabilities", (HarnessCapability.MCP,)),
        ("input_hashes", ()),
        ("input_hashes", ("not-a-hash",)),
    ],
)
def test_v3_spike_spec_rejects_incomplete_or_invalid_frozen_inputs(
    field: str, value: object
) -> None:
    payload = _spec().model_dump(mode="python")

    with pytest.raises(ValidationError):
        HarnessCapabilitySpikeSpecV3.model_validate({**payload, field: value})


def test_v3_report_rejects_naive_time_incomplete_matrix_and_wrong_decision(
    tmp_path: Path,
) -> None:
    run_path = _published_bundle(tmp_path)
    report = HarnessCapabilitySpikeReportV3.model_validate_json(
        (run_path / "harness-spike-report.json").read_bytes()
    )
    payload = report.model_dump(mode="python")

    with pytest.raises(ValidationError, match="timezone-aware"):
        HarnessCapabilitySpikeReportV3.model_validate(
            {**payload, "created_at": datetime(2026, 9, 22)}
        )
    with pytest.raises(ValidationError, match="one sorted check"):
        HarnessCapabilitySpikeReportV3.model_validate({**payload, "checks": report.checks[:-1]})
    with pytest.raises(ValidationError, match="does not match"):
        HarnessCapabilitySpikeReportV3.model_validate(
            {**payload, "decision": HarnessDecision.NO_GO}
        )


def test_zero_command_and_incomplete_lifecycle_observations_remain_unknown() -> None:
    events = [
        event
        for event in _provider_events()
        if not (
            event["method"] in {"item/started", "item/completed"}
            and isinstance(event["payload"], dict)
            and isinstance(event["payload"].get("item"), dict)
            and event["payload"]["item"].get("type") == "commandExecution"
        )
    ]
    capture = _capture(events)
    observation = build_p10_capability_observation_v2(
        capture,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash=None,
    )

    assert observation.matched_command_count == 0
    assert observation.filesystem_denial_observed is None
    assert observation.recovery_observed is None
    legacy = build_p10_capability_observation(
        capture,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash=None,
    )
    assert legacy.command_count == 0
    assert legacy.filesystem_denial_observed is None


@pytest.mark.parametrize("failure", ["wrong_order", "comment_spoof", "exit_127", "approval"])
def test_probe_order_identity_exit_and_approval_fail_closed(failure: str) -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    events = _provider_events()
    if failure == "wrong_order":
        events[4:8] = [*events[6:8], *events[4:6]]
    elif failure == "comment_spoof":
        for event in events[2:4]:
            event["payload"]["item"]["command"] = (  # type: ignore[index]
                '/usr/bin/true # /usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"'
            )
    elif failure == "exit_127":
        events[5]["payload"]["item"]["exit_code"] = 127  # type: ignore[index]
    else:
        events.insert(2, {"method": "commandExecution/approvalRequested", "payload": {}})

    capture = _capture(events)
    checks = evaluate_harness_capture_v3(
        _spec(),
        capture,
        inputs.manual_baseline,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="b" * 64,
    )
    failed = {check.capability for check in checks if not check.passed}

    assert failed & {
        HarnessCapability.PERMISSION_DENIAL,
        HarnessCapability.SANDBOX,
        HarnessCapability.FAILURE_RECOVERY,
    }


def _published_bundle(tmp_path: Path) -> Path:
    inputs = load_frozen_spike_inputs(FIXTURE)
    request = _sdk_request(inputs)
    spec = _sdk_spike_spec(inputs, request)
    run_spec = _sdk_run_spec(inputs, request, spec)
    provider_events = _provider_events()
    provider_transcript = b"".join(canonical_json_bytes(event) + b"\n" for event in provider_events)
    capture = _capture(provider_events)
    provider_hash = sha256_bytes(provider_transcript)
    observation = build_p10_capability_observation_v2(
        capture,
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash=provider_hash,
    )
    call = capture.tool_calls[0]
    interaction = ToolInteractionDigest(
        sequence=1,
        capability=AgentCapability.DATASET_DESCRIBE,
        request_hash=sha256_bytes(canonical_json_bytes(call.arguments)),
        response_hash=sha256_bytes(canonical_json_bytes(call.result)),
        succeeded=True,
    )
    usage = AgentUsage(
        input_tokens=2_000,
        output_tokens=300,
        cached_input_tokens=1_000,
        tool_calls=1,
        retry_count=0,
    )
    proposal_hash = sha256_bytes(capture.agent_messages[-1].encode("utf-8"))
    manifest = AgentRunManifestV3(
        run_spec_hash=run_spec.content_hash,
        provider_model_identifier="gpt-5.6-sol",
        sdk_version=CODEX_SDK_VERSION,
        runtime_package_version=CODEX_RUNTIME_PACKAGE_VERSION,
        runtime_version=f"{CODEX_RUNTIME_PACKAGE_VERSION} test",
        runtime_binary_hash="c" * 64,
        protocol_identifier=CODEX_PROTOCOL_IDENTIFIER,
        normalizer_hash=_normalizer_hash(),
        requested_policy_hash=request.runtime_policy.content_hash,
        capability_observation_hash=observation.content_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        interactions=(interaction,),
        input_hashes=inputs.all_input_hashes,
        output_proposal_hashes=(proposal_hash,),
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash=provider_hash,
        attempts=(
            HarnessAttemptRecord(
                attempt_index=1,
                provider_thread_id="thread-p10-v3",
                event_stream_hash=capture.transcript_hash,
                usage=usage,
                produced_proposal_hash=proposal_hash,
                started_at=NOW,
                completed_at=NOW,
            ),
        ),
        aggregate_usage=usage,
        run_status=RunStatus.SUCCEEDED,
        limitations=(
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "SYNTHETIC_CAPABILITY_SPIKE",
        ),
        started_at=NOW,
        completed_at=NOW,
    )
    report = build_harness_spike_report_v3(
        spec, manifest, capture, inputs.manual_baseline, created_at=NOW
    )
    paths = _publish_sdk_run_artifacts(
        tmp_path,
        request=request,
        provider_transcript=provider_transcript,
        spec=spec,
        run_spec=run_spec,
        manifest=manifest,
        observation=observation,
        report=report,
        transcript=capture.transcript,
    )
    return paths[0].parent


def test_p10_bundle_replays_bottom_up_and_rejects_tampering(tmp_path: Path) -> None:
    run_path = _published_bundle(tmp_path)

    verified = verify_codex_spike_artifact(run_path, FIXTURE)

    assert verified.report.decision is HarnessDecision.GO
    assert verified.process_return_code == 0
    summary = safe_result_summary(verified)
    assert summary["matched_command_count"] == 4
    assert summary["classification"] == "P10_SDK_QUALIFIED"

    observation = run_path / "harness-capability-observation.json"
    observation.write_bytes(
        observation.read_bytes().replace(b'"matched_command_count":4', b'"matched_command_count":3')
    )
    with pytest.raises(P10ArtifactVerificationError):
        verify_codex_spike_artifact(run_path, FIXTURE)


@pytest.mark.parametrize(
    "target,replacement",
    [
        (
            "harness-request.json",
            (b"p10-codex-sdk-code-mode-20260922", b"p10-codex-sdk-code-mode-20260923"),
        ),
        (
            "harness-spike-spec.json",
            (b"p10-codex-sdk-code-mode-20260922", b"p10-codex-sdk-code-mode-20260923"),
        ),
        (
            "agent-run-spec.json",
            (b"p10-codex-sdk-code-mode-20260922", b"p10-codex-sdk-code-mode-20260923"),
        ),
        ("agent-run-manifest.json", (b'"normalizer_hash":"', b'"normalizer_hash":"f')),
        (
            "agent-run-manifest.json",
            (
                b'"normalizer_identifier":"quantos-codex-normalizer/v2"',
                b'"normalizer_identifier":"quantos-codex-normalizer/v1"',
            ),
        ),
    ],
)
def test_p10_verifier_rejects_mutated_authority_inputs(
    tmp_path: Path, target: str, replacement: tuple[bytes, bytes]
) -> None:
    run_path = _published_bundle(tmp_path)
    path = run_path / target
    before, after = replacement
    path.write_bytes(path.read_bytes().replace(before, after, 1))

    with pytest.raises(P10ArtifactVerificationError):
        verify_codex_spike_artifact(run_path, FIXTURE)


def test_p10_verifier_rejects_extra_files_and_provider_hash_mismatch(tmp_path: Path) -> None:
    run_path = _published_bundle(tmp_path)
    (run_path / "unexpected").write_bytes(b"unexpected")
    with pytest.raises(P10ArtifactVerificationError, match="file set"):
        verify_codex_spike_artifact(run_path, FIXTURE)

    (run_path / "unexpected").unlink()
    provider = run_path / "provider-events.jsonl"
    provider.write_bytes(provider.read_bytes() + b"{}\n")
    with pytest.raises(P10ArtifactVerificationError, match="provider transcript binding"):
        verify_codex_spike_artifact(run_path, FIXTURE)


@pytest.mark.parametrize("payload", [b"", b"not-json\n", b"[]\n"])
def test_provider_event_jsonl_parser_rejects_invalid_streams(payload: bytes) -> None:
    with pytest.raises(P10ArtifactVerificationError):
        _parse_provider_event_jsonl(payload)


def test_canonical_runner_injects_parent_marker_publishes_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_events = _provider_events()
    provider_transcript = b"".join(canonical_json_bytes(event) + b"\n" for event in provider_events)
    capture = _capture(provider_events)
    execution = HarnessExecutionResult(
        attempts=(
            HarnessAttemptResult(
                capture=capture,
                runtime=HarnessRuntimeIdentityV2(
                    sdk_version=CODEX_SDK_VERSION,
                    runtime_package_version=CODEX_RUNTIME_PACKAGE_VERSION,
                    runtime_version=f"{CODEX_RUNTIME_PACKAGE_VERSION} test",
                    runtime_binary_hash="d" * 64,
                ),
                terminal_error=None,
                provider_transcript=provider_transcript,
            ),
        )
    )
    monkeypatch.setenv("P10_FORBIDDEN_SECRET", "caller-value-restored-after-run")

    def fake_execute(_adapter: CodexSdkAdapter, _request: object) -> HarnessExecutionResult:
        assert os.environ["P10_FORBIDDEN_SECRET"] == "p10-synthetic-parent-marker-20260907"
        return execution

    monkeypatch.setattr(CodexSdkAdapter, "execute", fake_execute)

    result = execute_codex_spike(FIXTURE, tmp_path)

    assert result.report.decision is HarnessDecision.GO
    assert result.process_return_code == 0
    assert os.environ["P10_FORBIDDEN_SECRET"] == "caller-value-restored-after-run"


def test_canonical_runner_retains_no_proposal_and_transport_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_message_events = _provider_events()
    del no_message_events[-3]
    no_message_provider = b"".join(
        canonical_json_bytes(event) + b"\n" for event in no_message_events
    )
    no_message_capture = _capture(no_message_events)
    no_message_execution = HarnessExecutionResult(
        attempts=(
            HarnessAttemptResult(
                capture=no_message_capture,
                runtime=HarnessRuntimeIdentityV2(
                    sdk_version=CODEX_SDK_VERSION,
                    runtime_package_version=CODEX_RUNTIME_PACKAGE_VERSION,
                    runtime_version=f"{CODEX_RUNTIME_PACKAGE_VERSION} test",
                    runtime_binary_hash="e" * 64,
                ),
                terminal_error=None,
                provider_transcript=no_message_provider,
            ),
        )
    )
    monkeypatch.delenv("P10_FORBIDDEN_SECRET", raising=False)
    monkeypatch.setattr(
        CodexSdkAdapter,
        "execute",
        lambda _adapter, _request: no_message_execution,
    )

    no_proposal = execute_codex_spike(FIXTURE, tmp_path / "no-proposal")

    assert no_proposal.manifest.run_status is RunStatus.FAILED
    assert no_proposal.manifest.output_proposal_hashes == ()
    assert safe_result_summary(no_proposal)["classification"] == "QUALIFICATION_NOT_EVALUATED"
    assert "P10_FORBIDDEN_SECRET" not in os.environ

    adapter = CodexSdkAdapter(authentication_home=tmp_path)
    failed_attempt = adapter._failed_result(
        HarnessErrorKind.AUTH_UNAVAILABLE,
        RuntimeError("synthetic auth unavailable"),
    )
    failed_execution = HarnessExecutionResult(attempts=(failed_attempt,))
    monkeypatch.setattr(
        CodexSdkAdapter,
        "execute",
        lambda _adapter, _request: failed_execution,
    )

    transport_failure = execute_codex_spike(FIXTURE, tmp_path / "transport-failure")

    assert transport_failure.manifest.run_status is RunStatus.FAILED
    assert transport_failure.manifest.provider_transcript_hash is None
    assert transport_failure.process_return_code == 1


def test_failure_reason_mapping_is_total_and_unknowns_fail_closed() -> None:
    assert _failure_reason(None) == "HARNESS_OUTPUT_INVALID"
    for kind in HarnessErrorKind:
        terminal = type("Terminal", (), {"kind": kind})()
        reason = _failure_reason(terminal)
        assert reason.startswith("HARNESS_")


def test_artifact_secret_guard_rejects_parent_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "never-persist-this-value")

    with pytest.raises(P10ArtifactVerificationError, match="prohibited secret"):
        _verify_p10_secret_absence({"provider-events.jsonl": b"never-persist-this-value"})
