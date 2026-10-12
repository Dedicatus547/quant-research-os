"""Synthetic rubric/manager tests. All socket and SDK execution boundaries are mocked."""

from __future__ import annotations

import base64
import json
import runpy
import socket
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_code_mode_p10 import _capture, _provider_events

from quantos.application import p10_v4 as rubric
from quantos.application import p10_v4_runner as runner
from quantos.application.agent_harness import HarnessAttemptResult, HarnessExecutionResult
from quantos.application.harness_runner import P10ArtifactVerificationError
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.harness import HarnessCapabilitySpikeSpecV4, HarnessRuntimeIdentityV2
from quantos.contracts.p10_v4 import (
    PROBE_COMMAND,
    PROBE_ENVIRONMENT,
    SOCKET_CASES,
    P10ManagementReceipt,
    ProbeProcessRecord,
)

FIXTURE = Path("tests/fixtures/p10_codex_workspace_v4").resolve()


def test_successor_model_is_bound_without_changing_benchmark() -> None:
    old = rubric.load_inputs(FIXTURE)
    new = rubric.load_inputs(FIXTURE, model="gpt-6.1-sol")
    old_request, new_request = rubric.build_request(old), rubric.build_request(new)
    assert old.all_input_hashes == new.all_input_hashes
    assert old_request.runtime_policy == new_request.runtime_policy
    assert old_request.max_attempts == new_request.max_attempts == 1
    assert new_request.model == "gpt-6.1-sol" and new_request.reasoning_effort == "medium"
    old_spec, new_spec = rubric.build_spec(old, old_request), rubric.build_spec(new, new_request)
    assert old_spec.required_capabilities == new_spec.required_capabilities
    assert old_spec.content_hash != new_spec.content_hash
    assert rubric.build_run_spec(old, old_request, old_spec).requested_model_configuration_hash != (
        rubric.build_run_spec(new, new_request, new_spec).requested_model_configuration_hash
    )
    with pytest.raises(
        rubric.legacy.HarnessRunnerError, match="unsupported P10 qualification model"
    ):
        rubric.load_inputs(FIXTURE, model="auto")


def probe_payload(*, errno: int | None = 1) -> dict[str, Any]:
    inputs = rubric.load_inputs(FIXTURE)
    spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    return {
        "schema_version": "p10-socket-observation/v1",
        "context": rubric.probe_context(inputs, spec).model_dump(),
        "samples": [
            dict(
                schema_version="p10-socket-sample/v1",
                family=family,
                type=kind,
                operation="socket",
                result="CREATED" if errno is None else "ERROR",
                errno=errno,
            )
            for family, kind in SOCKET_CASES
        ],
    }


def probe_output(*, errno: int | None = 1) -> str:
    return (canonical_json_bytes(probe_payload(errno=errno)) + b"\n").decode()


def events() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _provider_events()  # Reuse unchanged MCP/proposal/usage fixture.
    for event in result:
        item = event["payload"].get("item", {})
        if item.get("id") == "network":
            item["command"] = PROBE_COMMAND
            if event["method"] == "item/completed":
                item.update(aggregated_output=probe_output(), exit_code=1, status="failed")
        if item.get("id") == "recovery" and event["method"] == "item/completed":
            item["aggregated_output"] = str(FIXTURE) + "\n"
    return result


class SyntheticAdapter:
    calls = 0

    def __init__(self, provider: list[dict[str, Any]]) -> None:
        self.provider = provider

    def execute(self, request: object) -> HarnessExecutionResult:
        self.calls += 1
        raw = b"".join(canonical_json_bytes(e) + b"\n" for e in self.provider)
        return HarnessExecutionResult(
            attempts=(
                HarnessAttemptResult(
                    capture=_capture(self.provider),
                    runtime=HarnessRuntimeIdentityV2(
                        sdk_version=rubric.VERSION,
                        runtime_package_version=rubric.VERSION,
                        runtime_version=rubric.VERSION + " synthetic",
                        runtime_binary_hash=rubric.RUNTIME_HASH,
                    ),
                    terminal_error=None,
                    provider_transcript=raw,
                ),
            )
        )


def fake_control(
    inputs: rubric.InputsV4, spec: HarnessCapabilitySpikeSpecV4, *, phase: str
) -> ProbeProcessRecord:
    now, ns = datetime.now(UTC), time.monotonic_ns()
    return ProbeProcessRecord.model_validate(
        {
            "phase": phase,
            "context": rubric.probe_context(inputs, spec),
            "probe_hash": inputs.network_probe_hash,
            "started_at": now,
            "completed_at": now,
            "started_ns": ns,
            "completed_ns": ns,
            "stdout_base64": base64.b64encode(probe_output(errno=None).encode()).decode(),
            "stderr_base64": "",
            "exit_code": 0,
        }
    )


def run_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: list[dict[str, Any]] | None = None
) -> runner.ResultV4:
    monkeypatch.setattr(runner, "collect_control", fake_control)
    return runner.execute(
        FIXTURE, tmp_path, adapter=SyntheticAdapter(provider or events()), preparation_hash="a" * 64
    )


@pytest.mark.parametrize("errno,exit_code", [(None, 0), (1, 1), (97, 2), (24, 2), (13, 2)])
def test_structured_operations_have_exact_exit_semantics(errno: int | None, exit_code: int) -> None:
    assert rubric.parse_probe(probe_output(errno=errno), exit_code) is not None
    assert rubric.parse_probe(probe_output(errno=errno), (exit_code + 1) % 3) is None


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "extra",
        "boolean",
        "string_errno",
        "fake_success",
        "wrong_operation",
        "duplicate_key",
        "prose",
        "oversized",
        "bool_exit",
        "exit127",
    ],
)
def test_malformed_or_faked_probe_output_fails_closed(case: str) -> None:
    payload = probe_payload()
    code: Any = 1
    if case == "duplicate":
        payload["samples"][-1] = payload["samples"][0]
    elif case == "missing":
        payload["samples"].pop()
    elif case == "extra":
        payload["passed"] = True
    elif case == "boolean":
        payload["samples"][0]["errno"] = True
    elif case == "string_errno":
        payload["samples"][0]["errno"] = "1"
    elif case == "fake_success":
        payload["samples"][0]["result"] = "CREATED"
    elif case == "wrong_operation":
        payload["samples"][0]["operation"] = "connect"
    raw = canonical_json_bytes(payload).decode() + "\n"
    if case == "duplicate_key":
        raw = raw.replace('"errno":1', '"errno":1,"errno":1', 1)
    elif case == "prose":
        raw = "Operation not permitted\n" + raw
    elif case == "oversized":
        raw += " " * 4096
    elif case == "bool_exit":
        code = True
    elif case == "exit127":
        code = 127
    assert rubric.parse_probe(raw, code) is None


@pytest.mark.parametrize(
    "mode,expected_exit", [("created", 0), ("eperm", 1), ("unsupported", 2), ("mixed", 2)]
)
def test_helper_observes_socket_calls_with_no_real_sockets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    expected_exit: int,
) -> None:
    module = runpy.run_path(str(FIXTURE / "network_probe.py"))
    calls: list[tuple[int, int]] = []
    closed: list[bool] = []

    class Descriptor:
        def close(self) -> None:
            closed.append(True)

    def synthetic_socket(family: int, kind: int) -> Descriptor:
        calls.append((family, kind))
        if mode == "eperm" or (mode == "mixed" and len(calls) == 1):
            raise OSError(1, "synthetic")
        if mode == "unsupported":
            raise OSError(97, "synthetic")
        return Descriptor()

    monkeypatch.setattr(socket, "socket", synthetic_socket)
    assert module["main"]() == expected_exit
    assert calls == [
        (getattr(socket, family), getattr(socket, kind)) for family, kind in SOCKET_CASES
    ]
    assert len(closed) == (4 if mode == "created" else 3 if mode == "mixed" else 0)
    parsed = rubric.parse_probe(capsys.readouterr().out, expected_exit)
    assert parsed is not None


def test_helper_does_not_disguise_close_error_as_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    module = runpy.run_path(str(FIXTURE / "network_probe.py"))

    class Descriptor:
        def close(self) -> None:
            raise OSError(1, "synthetic close error")

    monkeypatch.setattr(socket, "socket", lambda *_: Descriptor())
    with pytest.raises(OSError, match="close error"):
        module["main"]()


def test_helper_runs_on_bound_system_python_without_real_sockets() -> None:
    # The manager/model use /usr/bin/python3, not the pytest virtualenv interpreter.
    bootstrap = """
import runpy, socket, sys
from types import SimpleNamespace
calls = []
def synthetic_socket(family, kind):
    calls.append((family, kind))
    return SimpleNamespace(close=lambda: None)
socket.socket = synthetic_socket
module = runpy.run_path(sys.argv[1])
code = module['main']()
assert len(calls) == 4
raise SystemExit(code)
"""
    completed = subprocess.run(
        ["/usr/bin/python3", "-I", "-S", "-B", "-c", bootstrap, "network_probe.py"],
        cwd=FIXTURE,
        env=dict(PROBE_ENVIRONMENT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    observed = rubric.parse_probe(completed.stdout, completed.returncode)
    assert observed is not None
    inputs = rubric.load_inputs(FIXTURE)
    spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    assert observed.context == rubric.probe_context(inputs, spec)


def test_synthetic_export_replays_from_independent_manager_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_synthetic(tmp_path, monkeypatch)
    assert result.report.decision == "GO"  # Synthetic matrix only; not FR03 qualification.
    assert len(result.report.checks) == 9
    receipt = P10ManagementReceipt.model_validate_json(
        (tmp_path / "manager-checkpoint/management-receipt.json").read_bytes()
    )
    assert (
        runner.verify(
            result.report_path.parent, FIXTURE, expected_receipt_hash=receipt.content_hash
        )
        == result
    )
    assert runner.summary(result)["fr03_authority_change"] is False
    with pytest.raises(P10ArtifactVerificationError):
        runner.verify(result.report_path.parent, FIXTURE, expected_receipt_hash="f" * 64)


@pytest.mark.parametrize(
    "case",
    [
        "dns",
        "created",
        "non_eperm",
        "wrong_context",
        "overlap",
        "duplicate_command",
        "missing_start",
        "wrong_turn",
        "spoof_command",
    ],
)
def test_network_or_order_evidence_cannot_pass_by_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    provider = events()
    if case == "dns":
        provider[7]["payload"]["item"].update(
            aggregated_output="Could not resolve host", exit_code=6
        )
    elif case in {"created", "non_eperm"}:
        provider[7]["payload"]["item"].update(
            aggregated_output=probe_output(errno=None if case == "created" else 97),
            exit_code=0 if case == "created" else 2,
        )
    elif case == "wrong_context":
        payload = probe_payload()
        payload["context"]["cwd"] = "/wrong"
        provider[7]["payload"]["item"]["aggregated_output"] = (
            canonical_json_bytes(payload).decode() + "\n"
        )
    elif case == "overlap":
        # Same start order, each lifecycle individually valid; recovery finishes before denials.
        provider[4:10] = [provider[i] for i in (4, 6, 8, 9, 5, 7)]
    elif case == "duplicate_command":
        import copy

        duplicate = copy.deepcopy(provider[6:8])
        for event in duplicate:
            event["payload"]["item"]["id"] = "duplicate-network"
        provider[8:8] = duplicate
    elif case == "missing_start":
        del provider[6]
    elif case == "wrong_turn":
        for event in provider[6:8]:
            event["payload"]["turn_id"] = "different-turn"
    else:
        for event in provider[6:8]:
            event["payload"]["item"]["command"] = "/usr/bin/true # " + PROBE_COMMAND
    result = run_synthetic(tmp_path, monkeypatch, provider)
    failed = {c.capability.value for c in result.report.checks if not c.passed}
    assert {"SANDBOX", "FAILURE_RECOVERY"} <= failed
    observation = json.loads(
        (result.report_path.parent / "harness-capability-observation.json").read_bytes()
    )
    assert observation["commands"]["recovery_observed"] is not True


@pytest.mark.parametrize("phase", ["before", "after"])
def test_failed_control_stops_or_rejects_and_retains_completed_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    def control(
        inputs: rubric.InputsV4, spec: HarnessCapabilitySpikeSpecV4, *, phase: str
    ) -> ProbeProcessRecord:
        result = fake_control(inputs, spec, phase=phase)
        return (
            result.model_copy(update={"stderr_base64": "eA=="}) if phase == failed_phase else result
        )

    failed_phase = phase
    monkeypatch.setattr(runner, "collect_control", control)
    adapter = SyntheticAdapter(events())
    if phase == "before":
        with pytest.raises(RuntimeError, match="before control failed"):
            runner.execute(FIXTURE, tmp_path, adapter=adapter, preparation_hash="a" * 64)
        assert adapter.calls == 0
        assert (tmp_path / "manager-checkpoint/before.json").exists()
    else:
        result = runner.execute(FIXTURE, tmp_path, adapter=adapter, preparation_hash="a" * 64)
        assert result.report.decision == "NO_GO"
        assert adapter.calls == 1
        assert (tmp_path / "manager-checkpoint/execution.json").exists()


@pytest.mark.parametrize(
    "name",
    [
        "management-receipt.json",
        "agent-events.jsonl",
        "provider-events.jsonl",
        "harness-capability-observation.json",
        "harness-spike-spec.json",
        "agent-run-manifest.json",
        "harness-spike-report.json",
        "unexpected.json",
    ],
)
def test_offline_replay_rejects_tampered_or_extra_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    result = run_synthetic(tmp_path, monkeypatch)
    target = result.report_path.parent / name
    target.write_bytes(target.read_bytes() + b" " if target.exists() else b"{}")
    with pytest.raises(P10ArtifactVerificationError):
        runner.verify(
            result.report_path.parent,
            FIXTURE,
            expected_receipt_hash=result.report.management_receipt_hash,
        )


def test_runtime_identity_mismatch_and_missing_proposal_do_not_qualify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "collect_control", fake_control)

    class WrongRuntime(SyntheticAdapter):
        def execute(self, request: object) -> HarnessExecutionResult:
            execution = super().execute(request)
            runtime = execution.runtime
            assert isinstance(runtime, HarnessRuntimeIdentityV2)
            return HarnessExecutionResult(
                attempts=(
                    replace(
                        execution.attempts[0],
                        runtime=runtime.model_copy(update={"runtime_binary_hash": "f" * 64}),
                    ),
                )
            )

    wrong = runner.execute(
        FIXTURE, tmp_path / "runtime", adapter=WrongRuntime(events()), preparation_hash="a" * 64
    )
    assert wrong.report.decision == "NO_GO"
    incomplete = events()
    del incomplete[-3]
    failed = runner.execute(
        FIXTURE,
        tmp_path / "incomplete",
        adapter=SyntheticAdapter(incomplete),
        preparation_hash="a" * 64,
    )
    assert failed.report.decision == "NO_GO"
    assert runner.summary(failed)["classification"] == "QUALIFICATION_NOT_EVALUATED"


def test_control_start_failure_keeps_no_invented_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic process start failure")

    monkeypatch.setattr(runner.subprocess, "Popen", unavailable)
    inputs = rubric.load_inputs(FIXTURE)
    spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    record = runner.collect_control(inputs, spec, phase="before")
    assert record.failure == "START_FAILED"
    assert record.exit_code is None
    assert record.stdout_base64 == record.stderr_base64 == ""


def test_controls_must_bracket_the_actual_attempt_and_no_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_synthetic(tmp_path, monkeypatch)
    receipt = P10ManagementReceipt.model_validate_json(
        (tmp_path / "manager-checkpoint/management-receipt.json").read_bytes()
    )
    inputs = rubric.load_inputs(FIXTURE)
    spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    invalid = receipt.model_copy(
        update={"before": receipt.after.model_copy(update={"phase": "before"})}
    )
    observation = rubric.build_observation(inputs, spec, _capture(events()), invalid)
    assert observation.controls_valid is False
    assert observation.socket_creation_denial_observed is False
    adapter = SyntheticAdapter(events())
    with pytest.raises(FileExistsError):
        runner.execute(FIXTURE, tmp_path, adapter=adapter, preparation_hash="a" * 64)
    assert adapter.calls == 0
    assert result.report.management_receipt_hash == receipt.content_hash
