"""Manager-owned P10 v4 controls, immutable export and offline replay. No CLI fallback."""

from __future__ import annotations

import base64
import os
import selectors
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quantos.application import harness_runner as legacy
from quantos.application import p10_v4 as rubric
from quantos.application.agent_harness import (
    HarnessCapture,
    LocalAgentHarness,
    capture_from_agent_events,
    parse_agent_events,
)
from quantos.application.harness_runner import (
    _failure_reason as failure_reason,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_runner import (
    _normalizer_hash as normalizer_hash,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_runner import (
    _parse_provider_event_jsonl as parse_provider_jsonl,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_runner import (
    _verify_p10_secret_absence as verify_secret_absence,  # pyright: ignore[reportPrivateUsage]
)
from quantos.artifacts.store import atomic_write_bytes, publish_directory, regular_tree_files
from quantos.contracts.agent import (
    AgentCapability,
    AgentRunManifestV3,
    AgentUsage,
    HarnessAttemptRecord,
    ToolInteractionDigest,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    HarnessCapabilitySpikeReportV4,
    HarnessCapabilitySpikeSpecV4,
    HarnessErrorKind,
    HarnessRuntimeIdentityV2,
    HarnessTerminalError,
)
from quantos.contracts.p10_v4 import (
    PROBE_ARGV,
    PROBE_BYTE_CAP,
    PROBE_ENVIRONMENT,
    P10ExecutionRecord,
    P10ManagementReceipt,
    P10ObservationV4,
    ProbeProcessRecord,
)
from quantos.contracts.status import RunStatus
from quantos.integrations.codex.event_normalizer import normalize_provider_events


@dataclass(frozen=True)
class ResultV4:
    report: HarnessCapabilitySpikeReportV4
    manifest: AgentRunManifestV3
    report_path: Path

    @property
    def process_return_code(self) -> int:
        return 0 if self.report.decision == "GO" else 1


def collect_control(
    inputs: rubric.InputsV4,
    spec: HarnessCapabilitySpikeSpecV4,
    *,
    phase: str,
) -> ProbeProcessRecord:
    """Only invoked by the manager inside the outer wrapper, never by the model."""
    context = rubric.probe_context(inputs, spec)
    started_at, started_ns = datetime.now(UTC), time.monotonic_ns()
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    failure: str | None = None
    exit_code: int | None = None
    try:
        process = subprocess.Popen(
            PROBE_ARGV,
            cwd=inputs.fixture_root,
            env=PROBE_ENVIRONMENT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        failure = "START_FAILED"
    else:
        assert process.stdout is not None and process.stderr is not None
        deadline = time.monotonic() + 5
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure = "TIMEOUT"
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        data = os.read(key.fd, PROBE_BYTE_CAP + 1)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        target = streams[str(key.data)]
                        left = PROBE_BYTE_CAP - sum(len(value) for value in streams.values())
                        target.extend(data[:left])
                        if len(data) > left:
                            failure = "OUTPUT_LIMIT"
                            break
                    if failure:
                        break
            if failure is None:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    failure = "TIMEOUT"
        finally:
            # Kill the whole helper group on timeout/output overflow; always reap actual exit.
            if failure is not None or process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            exit_code = process.wait()
            process.stdout.close()
            process.stderr.close()
    return ProbeProcessRecord.model_validate(
        {
            "phase": phase,
            "context": context,
            "probe_hash": inputs.network_probe_hash,
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "started_ns": started_ns,
            "completed_ns": time.monotonic_ns(),
            "stdout_base64": base64.b64encode(streams["stdout"]).decode(),
            "stderr_base64": base64.b64encode(streams["stderr"]).decode(),
            "exit_code": exit_code,
            "failure": failure,
        }
    )


def _manifest(
    inputs: rubric.InputsV4,
    spec: HarnessCapabilitySpikeSpecV4,
    capture: HarnessCapture,
    receipt: P10ManagementReceipt,
    observation: P10ObservationV4,
) -> AgentRunManifestV3:
    request = rubric.build_request(inputs)
    run_spec = rubric.build_run_spec(inputs, request, spec)
    record, runtime = receipt.execution, receipt.execution.runtime
    terminal = record.terminal_error
    proposal = (
        sha256_bytes(capture.agent_messages[-1].encode())
        if terminal is None
        and capture.turn_completed
        and not capture.turn_failed
        and capture.agent_messages
        else None
    )
    if terminal is None and proposal is None:
        terminal = HarnessTerminalError(
            kind=HarnessErrorKind.OUTPUT_INVALID,
            message_hash=sha256_bytes(b"P10 v4 has no proposal"),
        )
    interactions = tuple(
        ToolInteractionDigest(
            sequence=index,
            capability=AgentCapability.DATASET_DESCRIBE,
            request_hash=sha256_bytes(canonical_json_bytes(call.arguments)),
            response_hash=(
                sha256_bytes(canonical_json_bytes(call.result))
                if call.status == "completed" and call.error is None and call.result is not None
                else None
            ),
            succeeded=call.status == "completed" and call.error is None and call.result is not None,
        )
        for index, call in enumerate(capture.tool_calls, start=1)
    )
    usage = AgentUsage(
        input_tokens=capture.usage.get("input_tokens", 0),
        output_tokens=capture.usage.get("output_tokens", 0),
        cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
        tool_calls=len(interactions),
        retry_count=0,
    )
    return AgentRunManifestV3(
        run_spec_hash=run_spec.content_hash,
        provider_model_identifier=request.model,
        sdk_version=runtime.sdk_version if runtime else None,
        runtime_package_version=runtime.runtime_package_version if runtime else None,
        runtime_version=runtime.runtime_version if runtime else None,
        runtime_binary_hash=runtime.runtime_binary_hash if runtime else None,
        normalizer_hash=normalizer_hash(),
        requested_policy_hash=request.runtime_policy.content_hash,
        capability_observation_hash=observation.content_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.mcp_tool_schema_hash,
        interactions=interactions,
        input_hashes=inputs.all_input_hashes,
        output_proposal_hashes=(proposal,) if proposal else (),
        normalized_transcript_hash=record.normalized_transcript_hash,
        provider_transcript_hash=record.provider_transcript_hash,
        provider_transcript_retention_reason=(
            None if record.provider_transcript_hash is not None else "SDK_HOST_UNAVAILABLE"
        ),
        attempts=(
            HarnessAttemptRecord(
                attempt_index=1,
                provider_thread_id=capture.thread_ids[-1] if capture.thread_ids else None,
                event_stream_hash=capture.transcript_hash,
                usage=usage,
                terminal_error_kind=terminal.kind.value if terminal else None,
                terminal_error_message_hash=terminal.message_hash if terminal else None,
                error_retryable=terminal.retryable if terminal else False,
                produced_proposal_hash=proposal,
                started_at=record.started_at,
                completed_at=record.completed_at,
            ),
        ),
        aggregate_usage=usage,
        run_status=RunStatus.FAILED if terminal else RunStatus.SUCCEEDED,
        failure_reason_code=failure_reason(terminal) if terminal else None,
        limitations=rubric.LIMITATIONS,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _payloads(
    inputs: rubric.InputsV4,
    spec: HarnessCapabilitySpikeSpecV4,
    capture: HarnessCapture,
    receipt: P10ManagementReceipt,
    provider: bytes | None,
) -> tuple[dict[str, bytes], HarnessCapabilitySpikeReportV4, AgentRunManifestV3]:
    request = rubric.build_request(inputs)
    observation = rubric.build_observation(inputs, spec, capture, receipt)
    manifest = _manifest(inputs, spec, capture, receipt, observation)
    report = rubric.build_report(inputs, spec, manifest, capture, receipt, observation)
    payloads = {
        "agent-events.jsonl": capture.transcript,
        "agent-run-manifest.json": manifest.canonical_bytes(),
        "agent-run-spec.json": rubric.build_run_spec(inputs, request, spec).canonical_bytes(),
        "harness-request.json": request.canonical_bytes(),
        "harness-spike-spec.json": spec.canonical_bytes(),
        "harness-capability-observation.json": observation.canonical_bytes(),
        "harness-spike-report.json": canonical_json_bytes(report),
        "management-receipt.json": receipt.canonical_bytes(),
    }
    if provider is not None:
        payloads["provider-events.jsonl"] = provider
    verify_secret_absence(payloads)
    return payloads, report, manifest


def execute(
    fixture: Path,
    output: Path,
    *,
    adapter: LocalAgentHarness,
    preparation_hash: str,
    model: str = "gpt-5.6-sol",
) -> ResultV4:
    """Authorized manager entry. Caller must hold the existing storage lease and allowance."""
    inputs = rubric.load_inputs(fixture, model=model)
    request = rubric.build_request(inputs)
    spec = rubric.build_spec(inputs, request)
    checkpoint = output / "manager-checkpoint"
    checkpoint.mkdir(parents=True, exist_ok=False)  # No retry/rewrite of a used attempt.
    atomic_write_bytes(checkpoint / "harness-request.json", request.canonical_bytes())
    atomic_write_bytes(checkpoint / "harness-spike-spec.json", spec.canonical_bytes())
    before = collect_control(inputs, spec, phase="before")
    atomic_write_bytes(checkpoint / "before.json", before.canonical_bytes())
    if not rubric.control_passes(
        before, rubric.probe_context(inputs, spec), inputs.network_probe_hash
    ):
        raise legacy.HarnessRunnerError("outer before control failed; no runtime/model started")
    previous = os.environ.get("P10_FORBIDDEN_SECRET")
    os.environ["P10_FORBIDDEN_SECRET"] = legacy.SYNTHETIC_SECRET_MARKER
    started_at, started_ns = datetime.now(UTC), time.monotonic_ns()
    try:
        execution = adapter.execute(request)
    finally:
        if previous is None:
            os.environ.pop("P10_FORBIDDEN_SECRET", None)
        else:
            os.environ["P10_FORBIDDEN_SECRET"] = previous
    completed_at, completed_ns = datetime.now(UTC), time.monotonic_ns()
    if len(execution.attempts) != 1:
        raise legacy.HarnessRunnerError("finite P10 v4 permits exactly one attempt")
    provider = execution.provider_transcript
    runtime = execution.runtime
    record = P10ExecutionRecord(
        request_hash=request.content_hash,
        started_at=started_at,
        completed_at=completed_at,
        started_ns=started_ns,
        completed_ns=completed_ns,
        runtime=runtime if isinstance(runtime, HarnessRuntimeIdentityV2) else None,
        terminal_error=execution.terminal_error,
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=sha256_bytes(provider) if provider is not None else None,
    )
    completed = {
        "execution.json": record.canonical_bytes(),
        "agent-events.jsonl": execution.normalized_transcript,
    }
    if execution.attempts[0].qualification_observations is not None:
        completed["host-observations.json"] = canonical_json_bytes(
            execution.attempts[0].qualification_observations
        )
    if provider is not None:
        completed["provider-events.jsonl"] = provider
    verify_secret_absence(completed)
    for name, data in completed.items():
        atomic_write_bytes(checkpoint / name, data)
    # Persist the completed model attempt before the independent after control.
    after = collect_control(inputs, spec, phase="after")
    atomic_write_bytes(checkpoint / "after.json", after.canonical_bytes())
    receipt = P10ManagementReceipt(
        preparation_hash=preparation_hash,
        spike_spec_hash=spec.content_hash,
        before=before,
        execution=record,
        after=after,
    )
    atomic_write_bytes(checkpoint / "management-receipt.json", receipt.canonical_bytes())
    if rubric.load_inputs(fixture, model=model) != inputs:
        raise legacy.HarnessRunnerError("fixture changed during execution; retain checkpoint")
    payloads, report, _ = _payloads(inputs, spec, execution.capture, receipt, provider)
    bundles = output / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".p10-v4-", dir=bundles))
    for name, data in payloads.items():
        atomic_write_bytes(staging / name, data)
    destination = bundles / f"sha256-{report.content_hash}"
    publish_directory(staging, destination)  # On failure retain staging for inspection.
    return verify(destination, fixture, expected_receipt_hash=receipt.content_hash, model=model)


def verify(
    run: Path, fixture: Path, *, expected_receipt_hash: str, model: str = "gpt-5.6-sol"
) -> ResultV4:
    """Replay offline using a manager receipt hash obtained outside the Agent bundle."""
    try:
        paths = regular_tree_files(run)
        if any(p.parent != run or p.stat().st_size > legacy.MAX_TRANSCRIPT_BYTES for p in paths):
            raise ValueError("v4 artifact file is not flat/bounded")
        retained = {p.name: p.read_bytes() for p in paths}
        receipt = P10ManagementReceipt.model_validate_json(retained["management-receipt.json"])
        if sha256_bytes(retained["management-receipt.json"]) != expected_receipt_hash:
            raise ValueError("management receipt does not match externally supplied trusted hash")
        spec = HarnessCapabilitySpikeSpecV4.model_validate_json(retained["harness-spike-spec.json"])
        inputs = rubric.load_inputs(fixture, model=model)
        request = rubric.build_request(inputs)
        expected_spec = rubric.build_spec(inputs, request, interpreter_hash=spec.interpreter_hash)
        if spec != expected_spec or spec.content_hash != receipt.spike_spec_hash:
            raise ValueError("v4 spec does not bind current inputs/implementation")
        if receipt.execution.request_hash != request.content_hash:
            raise ValueError("v4 execution request binding mismatch")
        events = parse_agent_events(
            retained["agent-events.jsonl"], max_bytes=request.max_transcript_bytes
        )
        capture = capture_from_agent_events(events, max_bytes=request.max_transcript_bytes)
        if (
            capture.attempt_index != 1
            or receipt.execution.normalized_transcript_hash != capture.transcript_hash
        ):
            raise ValueError("v4 normalized transcript binding mismatch")
        provider = retained.get("provider-events.jsonl")
        if (
            sha256_bytes(provider) if provider is not None else None
        ) != receipt.execution.provider_transcript_hash:
            raise ValueError("v4 provider transcript binding mismatch")
        if provider is not None and capture.thread_ids:
            replay = capture_from_agent_events(
                normalize_provider_events(
                    parse_provider_jsonl(provider), thread_id=capture.thread_ids[-1]
                ),
                max_bytes=request.max_transcript_bytes,
            )
            if replay.transcript != capture.transcript:
                raise ValueError("v4 provider and normalized events disagree")
        expected, report, manifest = _payloads(inputs, spec, capture, receipt, provider)
        if retained != expected or run.name != f"sha256-{report.content_hash}":
            raise ValueError("v4 artifacts do not replay exactly")
    except (KeyError, ValueError, OSError) as error:
        raise legacy.P10ArtifactVerificationError("P10 v4 retained evidence is invalid") from error
    return ResultV4(report=report, manifest=manifest, report_path=run / "harness-spike-report.json")


def summary(result: ResultV4) -> dict[str, object]:
    return {
        "schema_version": "p10-v4-summary/v1",
        "report_hash": result.report.content_hash,
        "report_path": str(result.report_path),
        "decision": result.report.decision,
        "failed_capabilities": [c.capability for c in result.report.checks if not c.passed],
        "process_return_code": result.process_return_code,
        "management_receipt_hash": result.report.management_receipt_hash,
        "classification": (
            "QUALIFICATION_NOT_EVALUATED"
            if result.manifest.run_status == RunStatus.FAILED
            else "P10_V4_MATRIX_OBSERVED"
        ),
        "fr03_authority_change": False,
    }
