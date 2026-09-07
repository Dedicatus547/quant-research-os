from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantos.application.harness_runner import (
    SYNTHETIC_SECRET_MARKER,
    HarnessRunnerError,
    build_agent_manifest,
    build_spike_spec,
    capability_policy,
    codex_argv,
    load_frozen_spike_inputs,
    model_configuration_payload,
    publish_run_artifacts,
    safe_result_summary,
    sanitized_process_environment,
    verify_codex_version,
)
from quantos.application.harness_spike import (
    HarnessTranscriptError,
    build_codex_spike_report,
    evaluate_codex_capture,
    parse_codex_exec_jsonl,
)
from quantos.contracts import HarnessCapability, HarnessDecision, RunStatus

FIXTURE = Path("tests/fixtures/p10_codex_workspace")
NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _baseline() -> dict[str, object]:
    return json.loads((FIXTURE / "manual_baseline.json").read_text(encoding="utf-8"))


def _event(event_type: str, **values: object) -> dict[str, object]:
    return {"type": event_type, **values}


def _item(item: dict[str, object]) -> dict[str, object]:
    return _event("item.completed", item=item)


def _command(command: str, output: str, exit_code: int) -> dict[str, object]:
    return _item(
        {
            "type": "command_execution",
            "command": command,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": "completed",
        }
    )


def _valid_events() -> list[dict[str, object]]:
    baseline = _baseline()
    structured = {
        "dataset_hash": "a" * 64,
        "fields": ["adjusted_close", "membership", "tradable"],
        "fixture_kind": "SYNTHETIC",
        "row_count": 3,
    }
    return [
        _event("thread.started", thread_id="thread-p10-test"),
        _event("turn.started"),
        _item(
            {
                "type": "mcp_tool_call",
                "server": "quantosP10",
                "tool": "dataset_describe",
                "arguments": {
                    "dataset_hash": "a" * 64,
                    "skill_nonce": "P10_SKILL_20260907",
                },
                "result": {"structured_content": structured},
                "error": None,
                "status": "completed",
            }
        ),
        _command('/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"', "", 0),
        _command(
            "/usr/bin/python3 write_probe.py",
            "PermissionError: [Errno 30] Read-only file system: 'should-not-exist'\n",
            1,
        ),
        _command(
            "/usr/bin/curl --max-time 2 -fsS https://example.com",
            "curl: (6) Could not resolve host: example.com\n",
            6,
        ),
        _command("/usr/bin/pwd", "/fixture\n", 0),
        _item(
            {
                "type": "agent_message",
                "text": json.dumps(baseline, separators=(",", ":"), sort_keys=True),
            }
        ),
        _event(
            "turn.completed",
            usage={
                "input_tokens": 2_000,
                "cached_input_tokens": 1_000,
                "output_tokens": 300,
            },
        ),
    ]


def _jsonl(events: list[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(event, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        for event in events
    )


def _valid_capture():  # type annotation would repeat the public parser return type
    payload = _jsonl(_valid_events())
    return parse_codex_exec_jsonl(
        payload,
        max_bytes=len(payload),
        forbidden_marker=SYNTHETIC_SECRET_MARKER.encode(),
    )


def test_valid_capture_passes_all_hard_capabilities_and_builds_go_report() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    spec = build_spike_spec(inputs)
    capture = _valid_capture()
    manifest = build_agent_manifest(
        inputs=inputs,
        spec=spec,
        capture=capture,
        process_return_code=0,
        started_at=NOW,
        completed_at=NOW,
    )
    report = build_codex_spike_report(
        spec,
        manifest,
        capture,
        inputs.manual_baseline,
        raw_transcript_retained=True,
        created_at=NOW,
    )

    assert all(check.passed for check in report.checks)
    assert report.decision is HarnessDecision.GO
    assert manifest.run_status is RunStatus.SUCCEEDED
    assert manifest.provider_thread_id == "thread-p10-test"
    assert manifest.usage.tool_calls == 1


@pytest.mark.parametrize(
    ("event_index", "replacement", "failed_capability"),
    [
        (
            4,
            _command("/usr/bin/python3 write_probe.py", "/usr/bin/python3: not found\n", 127),
            HarnessCapability.SANDBOX,
        ),
        (
            6,
            _command("/usr/bin/pwd", "permission denied\n", 1),
            HarnessCapability.FAILURE_RECOVERY,
        ),
        (
            8,
            _event(
                "turn.completed",
                usage={"input_tokens": 999_999, "output_tokens": 300},
            ),
            HarnessCapability.USAGE,
        ),
    ],
)
def test_hard_capability_failures_force_no_go(
    event_index: int,
    replacement: dict[str, object],
    failed_capability: HarnessCapability,
) -> None:
    events = _valid_events()
    events[event_index] = replacement
    capture = parse_codex_exec_jsonl(_jsonl(events), max_bytes=100_000)
    spec = build_spike_spec(load_frozen_spike_inputs(FIXTURE))
    checks = evaluate_codex_capture(spec, capture, _baseline())

    failed = {check.capability for check in checks if not check.passed}
    assert failed_capability in failed


def test_marker_approval_bad_mcp_and_bad_proposal_are_rejected() -> None:
    events = _valid_events()
    mcp_item = events[2]["item"]
    assert isinstance(mcp_item, dict)
    mcp_item["arguments"] = {"dataset_hash": "a" * 64, "skill_nonce": "wrong"}
    mcp_item["result"] = {"structured_content": {"row_count": 4}}
    agent_item = events[7]["item"]
    assert isinstance(agent_item, dict)
    agent_item["text"] = json.dumps({**_baseline(), "verdict": "PASS"})
    events.insert(3, _event("approval.requested", detail=SYNTHETIC_SECRET_MARKER))
    payload = _jsonl(events)
    capture = parse_codex_exec_jsonl(
        payload,
        max_bytes=100_000,
        forbidden_marker=SYNTHETIC_SECRET_MARKER.encode(),
    )
    spec = build_spike_spec(load_frozen_spike_inputs(FIXTURE))
    checks = evaluate_codex_capture(spec, capture, _baseline())
    failed = {check.capability for check in checks if not check.passed}

    assert {
        HarnessCapability.MCP,
        HarnessCapability.PERMISSION_DENIAL,
        HarnessCapability.PROPOSAL_BOUNDARY,
        HarnessCapability.SKILLS,
    } <= failed


def test_command_name_in_comment_cannot_spoof_a_required_probe() -> None:
    events = _valid_events()
    events[3] = _command(
        '/usr/bin/true # /usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"',
        "",
        0,
    )
    capture = parse_codex_exec_jsonl(_jsonl(events), max_bytes=100_000)
    spec = build_spike_spec(load_frozen_spike_inputs(FIXTURE))
    checks = evaluate_codex_capture(spec, capture, _baseline())
    permission = next(
        check for check in checks if check.capability is HarnessCapability.PERMISSION_DENIAL
    )

    assert permission.passed is False


def test_parser_rejects_unbounded_malformed_or_invalid_event_shapes() -> None:
    with pytest.raises(HarnessTranscriptError, match="empty or exceeds"):
        parse_codex_exec_jsonl(b"", max_bytes=10)
    with pytest.raises(HarnessTranscriptError, match="empty or exceeds"):
        parse_codex_exec_jsonl(b"{}\n", max_bytes=1)
    with pytest.raises(HarnessTranscriptError, match="invalid JSONL"):
        parse_codex_exec_jsonl(b"not-json\n", max_bytes=100)
    with pytest.raises(HarnessTranscriptError, match="event type"):
        parse_codex_exec_jsonl(b"{}\n", max_bytes=100)
    with pytest.raises(HarnessTranscriptError, match="command capture"):
        parse_codex_exec_jsonl(
            _jsonl([_item({"type": "command_execution", "command": 1})]),
            max_bytes=1_000,
        )
    with pytest.raises(HarnessTranscriptError, match="usage"):
        parse_codex_exec_jsonl(
            _jsonl([_event("turn.completed", usage={"input_tokens": -1})]),
            max_bytes=1_000,
        )


def test_failed_execution_manifest_cannot_publish_agent_output_authority() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    manifest = build_agent_manifest(
        inputs=inputs,
        spec=build_spike_spec(inputs),
        capture=_valid_capture(),
        process_return_code=1,
        started_at=NOW,
        completed_at=NOW,
    )

    assert manifest.run_status is RunStatus.FAILED
    assert manifest.output_proposal_hashes == ()
    assert manifest.failure_reason_code == "HARNESS_EXECUTION_FAILED"


def test_runner_configuration_is_frozen_and_strips_tushare_environment() -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    environment = sanitized_process_environment(
        {"PATH": "/bin", "TUSHARE_TOKEN": "never-visible", "tushare_other": "also-hidden"}
    )
    argv = codex_argv(inputs)
    configuration = model_configuration_payload(inputs)

    assert "TUSHARE_TOKEN" not in environment
    assert "tushare_other" not in environment
    assert environment["P10_FORBIDDEN_SECRET"] == SYNTHETIC_SECRET_MARKER
    assert "--ignore-user-config" in argv
    assert "allow_login_shell=false" in argv
    assert configuration["command_network_allowed"] is False
    assert capability_policy().max_requests == 1


def test_frozen_fixture_rejects_extra_files_and_symlink_root(tmp_path: Path) -> None:
    copied = tmp_path / "fixture"
    shutil.copytree(FIXTURE, copied)
    (copied / "unexpected.txt").write_text("not frozen", encoding="utf-8")
    with pytest.raises(HarnessRunnerError, match="file set"):
        load_frozen_spike_inputs(copied)

    linked = tmp_path / "linked"
    linked.symlink_to(FIXTURE.resolve(), target_is_directory=True)
    with pytest.raises(HarnessRunnerError, match="root cannot be"):
        load_frozen_spike_inputs(linked)


def test_version_check_fails_closed_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["codex", "--version"], 0, b"codex-cli 0.0.0\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(HarnessRunnerError, match="does not match"):
        verify_codex_version({})


def test_report_manifest_and_transcript_publish_as_one_immutable_tree(tmp_path: Path) -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    capture = _valid_capture()
    spec = build_spike_spec(inputs)
    manifest = build_agent_manifest(
        inputs=inputs,
        spec=spec,
        capture=capture,
        process_return_code=0,
        started_at=NOW,
        completed_at=NOW,
    )
    report = build_codex_spike_report(
        spec,
        manifest,
        capture,
        inputs.manual_baseline,
        raw_transcript_retained=True,
        created_at=NOW,
    )
    transcript = _jsonl(_valid_events())

    report_path, manifest_path, spec_path, transcript_path = publish_run_artifacts(
        tmp_path,
        transcript=transcript,
        spec=spec,
        manifest=manifest,
        report=report,
    )

    assert json.loads(report_path.read_bytes())["created_at"] == "2026-09-07T12:00:00.000000Z"
    assert manifest_path.read_bytes() == manifest.canonical_bytes()
    assert spec_path.read_bytes() == spec.canonical_bytes()
    assert transcript_path.read_bytes() == transcript


def test_safe_summary_contains_hashes_but_not_raw_transcript(tmp_path: Path) -> None:
    inputs = load_frozen_spike_inputs(FIXTURE)
    capture = _valid_capture()
    spec = build_spike_spec(inputs)
    manifest = build_agent_manifest(
        inputs=inputs,
        spec=spec,
        capture=capture,
        process_return_code=0,
        started_at=NOW,
        completed_at=NOW,
    )
    report = build_codex_spike_report(
        spec,
        manifest,
        capture,
        inputs.manual_baseline,
        raw_transcript_retained=True,
        created_at=NOW,
    )
    from quantos.application.harness_runner import HarnessRunResult

    result = HarnessRunResult(
        report=report,
        manifest=manifest,
        report_path=tmp_path / "report.json",
        manifest_path=tmp_path / "manifest.json",
        spec_path=tmp_path / "spec.json",
        transcript_path=tmp_path / "events.jsonl",
        process_return_code=0,
    )
    summary = safe_result_summary(result)

    assert summary["decision"] == "GO"
    assert "transcript_hash" in summary
    assert "transcript" not in summary


def test_mock_mcp_server_returns_only_frozen_read_only_tool() -> None:
    requests = "\n".join(
        json.dumps(item)
        for item in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "dataset_describe",
                    "arguments": {
                        "dataset_hash": "a" * 64,
                        "skill_nonce": "P10_SKILL_20260907",
                    },
                },
            },
        )
    )
    result = subprocess.run(
        ["/usr/bin/python3", str(FIXTURE / "mock_mcp_server.py")],
        input=requests + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]

    assert responses[1]["result"]["tools"][0]["name"] == "dataset_describe"
    assert responses[1]["result"]["tools"][0]["annotations"]["readOnlyHint"] is True
    assert responses[2]["result"]["structuredContent"]["row_count"] == 3
    assert result.stderr == ""
