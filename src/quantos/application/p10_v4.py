"""Finite P10 successor: deterministic probe parsing and shared evaluation/replay."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from quantos.application import harness_runner as legacy
from quantos.application.agent_harness import HarnessCapture
from quantos.application.harness_runner import (
    _sdk_request as sdk_request_v3,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_runner import (
    _sdk_run_spec as sdk_run_spec_v3,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_runner import (
    _sdk_spike_spec as sdk_spike_spec_v3,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.harness_spike import (
    _evaluate_p10_capture,  # pyright: ignore[reportPrivateUsage]
    _find_lifecycle,  # pyright: ignore[reportPrivateUsage]
    _is_policy_denial,  # pyright: ignore[reportPrivateUsage]
)
from quantos.artifacts.store import regular_tree_files
from quantos.contracts.agent import AgentRunManifestV3, AgentRunSpecV3
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    HarnessCapability,
    HarnessCapabilityCheck,
    HarnessCapabilityObservationV2,
    HarnessCapabilitySpikeReportV4,
    HarnessCapabilitySpikeSpecV4,
    HarnessDecision,
    HarnessExecutionRequest,
    HarnessObservationState,
)
from quantos.contracts.p10_v4 import (
    PROBE_BYTE_CAP,
    PROBE_COMMAND,
    PROBE_ENVIRONMENT,
    P10ManagementReceipt,
    P10ObservationV4,
    ProbeContext,
    ProbeProcessRecord,
    SocketObservation,
)
from quantos.contracts.status import ReasonCode, RunStatus

VERSION = "0.162.1"
PROFILE = "openai-codex-0.162.1-p10-v4"
RUNTIME_HASH = "628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1"
RUN_ID = "p10-codex-sdk-socket-v4-20261011"
ROOT = Path(__file__).resolve().parents[3]
LIMITATIONS = (
    "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
    "FOUR_IP_SOCKET_CREATIONS_ONLY",
    "MANAGEMENT_RECEIPT_REQUIRES_TRUSTED_ORIGIN",
    "MODEL_IDENTIFIER_NOT_IMMUTABLE",
    "SYNTHETIC_CAPABILITY_SPIKE",
    "WRITE_DENIAL_ATTRIBUTED_TO_COMBINED_BOUNDARY",
)


@dataclass(frozen=True)
class InputsV4(legacy.FrozenSpikeInputs):
    network_probe_hash: str
    model: str = "gpt-5.6-sol"

    @property
    def all_input_hashes(self) -> tuple[str, ...]:
        return tuple(sorted({*super().all_input_hashes, self.network_probe_hash}))


def load_inputs(fixture: Path, *, model: str = "gpt-5.6-sol") -> InputsV4:
    if model not in {"gpt-5.6-sol", "gpt-6.1-sol"}:
        raise legacy.HarnessRunnerError("unsupported P10 qualification model")
    if fixture.is_symlink():
        raise legacy.HarnessRunnerError("v4 fixture root cannot be a symlink")
    root = fixture.resolve(strict=True)
    names = {
        "agents": "AGENTS.md",
        "skill": ".agents/skills/quantos-p10-probe/SKILL.md",
        "task": "task.md",
        "dataset": "dataset.json",
        "mcp_server": "mock_mcp_server.py",
        "mcp_tool_schema": "mcp_tool.schema.json",
        "output_schema": "output.schema.json",
        "manual_baseline": "manual_baseline.json",
        "write_probe": "write_probe.py",
        "network_probe": "network_probe.py",
    }
    if {p.relative_to(root).as_posix() for p in regular_tree_files(root)} != set(names.values()):
        raise legacy.HarnessRunnerError("v4 fixture file set is not exact")
    payloads = {name: (root / relative).read_bytes() for name, relative in names.items()}
    baseline = json.loads(payloads["manual_baseline"])
    if not isinstance(baseline, dict):
        raise legacy.HarnessRunnerError("v4 baseline must be an object")
    return InputsV4(
        fixture_root=root,
        agents_hash=sha256_bytes(payloads["agents"]),
        skill_hash=sha256_bytes(payloads["skill"]),
        task_hash=sha256_bytes(payloads["task"]),
        dataset_hash=sha256_bytes(payloads["dataset"]),
        mcp_server_hash=sha256_bytes(payloads["mcp_server"]),
        mcp_tool_schema_hash=sha256_bytes(payloads["mcp_tool_schema"]),
        output_schema_hash=sha256_bytes(payloads["output_schema"]),
        manual_baseline_hash=sha256_bytes(payloads["manual_baseline"]),
        write_probe_hash=sha256_bytes(payloads["write_probe"]),
        network_probe_hash=sha256_bytes(payloads["network_probe"]),
        model=model,
        manual_baseline=cast(dict[str, object], baseline),
        task_text=payloads["task"].decode(),
    )


def implementation_hash() -> str:
    # Bind actual evaluator/export/adapter/contract dependencies, not the overall Git commit.
    paths = {
        *ROOT.glob("src/quantos/contracts/*.py"),
        *ROOT.glob("src/quantos/integrations/codex/*.py"),
        *(
            ROOT / f"src/quantos/application/{name}.py"
            for name in (
                "p10_v4",
                "p10_v4_runner",
                "agent_harness",
                "harness_runner",
                "harness_spike",
            )
        ),
        ROOT / "src/quantos/artifacts/store.py",
        ROOT / "src/quantos/infrastructure/hosted_storage.py",
        ROOT / "scripts/fr03_p10_v4.py",
        ROOT / "scripts/fr03_candidate_01621.py",
    }
    return sha256_bytes(
        canonical_json_bytes(
            {p.relative_to(ROOT).as_posix(): sha256_bytes(p.read_bytes()) for p in sorted(paths)}
        )
    )


def build_request(inputs: InputsV4) -> HarnessExecutionRequest:
    # Same SDK policy/budgets/MCP port as v3; no alternate transport.
    return HarnessExecutionRequest.model_validate(
        {
            **sdk_request_v3(inputs).model_dump(),
            "run_id": RUN_ID
            if inputs.model == "gpt-5.6-sol"
            else "p10-gpt61-01621-v4-env1-apps-isolated1",
            "model": inputs.model,
        }
    )


def build_spec(
    inputs: InputsV4,
    request: HarnessExecutionRequest,
    *,
    interpreter_hash: str | None = None,
) -> HarnessCapabilitySpikeSpecV4:
    return HarnessCapabilitySpikeSpecV4.model_validate(
        {
            **sdk_spike_spec_v3(inputs, request).model_dump(),
            "schema_version": "agent-harness-spike-spec/v4",
            "spike_id": request.run_id,
            "network_probe_hash": inputs.network_probe_hash,
            "interpreter_hash": (
                interpreter_hash
                if interpreter_hash is not None
                else sha256_bytes(Path("/usr/bin/python3").read_bytes())
            ),
            "implementation_hash": implementation_hash(),
            "runtime_binary_hash": RUNTIME_HASH,
        }
    )


def build_run_spec(
    inputs: InputsV4,
    request: HarnessExecutionRequest,
    spec: HarnessCapabilitySpikeSpecV4,
) -> AgentRunSpecV3:
    common = sdk_run_spec_v3(inputs, request, sdk_spike_spec_v3(inputs, request))
    configuration = legacy.sdk_model_configuration_payload(inputs)
    configuration.update(
        {
            "sdk_version": VERSION,
            "runtime_package_version": VERSION,
            "model_identifier": inputs.model,
        }
    )
    if inputs.model == "gpt-6.1-sol":
        configuration["apps_enabled"] = False
    return AgentRunSpecV3.model_validate(
        {
            **common.model_dump(),
            "run_id": request.run_id,
            "campaign_hash": sha256_bytes(canonical_json_bytes({"spike_spec": spec.content_hash})),
            "requested_model_configuration_hash": sha256_bytes(canonical_json_bytes(configuration)),
        }
    )


def probe_context(inputs: InputsV4, spec: HarnessCapabilitySpikeSpecV4) -> ProbeContext:
    return ProbeContext(
        cwd=str(inputs.fixture_root),
        uid=os.getuid(),
        interpreter_hash=spec.interpreter_hash,
        environment=dict(PROBE_ENVIRONMENT),
    )


def parse_probe(output: str, exit_code: int | None) -> SocketObservation | None:
    """Accept exact helper JSON, never denial-looking prose or coerced numeric values."""
    try:
        raw = output.encode("utf-8")
        if len(raw) > PROBE_BYTE_CAP or type(exit_code) is not int:
            return None
        observation = SocketObservation.model_validate_json(raw)
        # Canonical equality also rejects duplicate keys, extras and coercions.
        if raw != observation.canonical_bytes() + b"\n" or exit_code != observation.expected_exit:
            return None
        return observation
    except (ValueError, UnicodeError):
        return None


def control_passes(
    record: ProbeProcessRecord,
    context: ProbeContext,
    probe_hash: str,
) -> bool:
    if record.failure is not None or record.stderr_base64 or record.exit_code != 0:
        return False
    try:
        result = parse_probe(base64.b64decode(record.stdout_base64).decode(), record.exit_code)
    except UnicodeError:
        return False
    return bool(
        result is not None
        and result.context == context
        and record.context == context
        and record.probe_hash == probe_hash
    )


def build_observation(
    inputs: InputsV4,
    spec: HarnessCapabilitySpikeSpecV4,
    capture: HarnessCapture,
    receipt: P10ManagementReceipt,
) -> P10ObservationV4:
    before, after, execution = receipt.before, receipt.after, receipt.execution
    context = before.context
    controls = bool(
        context.cwd == str(inputs.fixture_root)
        and context.environment == PROBE_ENVIRONMENT
        and context.interpreter_hash == spec.interpreter_hash
        and before.phase == "before"
        and after.phase == "after"
        and control_passes(before, context, inputs.network_probe_hash)
        and control_passes(after, context, inputs.network_probe_hash)
        and before.completed_ns
        <= execution.started_ns
        <= execution.completed_ns
        <= after.started_ns
        and before.completed_at
        <= execution.started_at
        <= execution.completed_at
        <= after.started_at
        and receipt.spike_spec_hash == spec.content_hash
        and execution.request_hash == spec.execution_request_hash
    )
    secret, write, network, recovery = (
        _find_lifecycle(capture, command)
        for command in (
            '/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"',
            "/usr/bin/python3 write_probe.py",
            PROBE_COMMAND,
            "/usr/bin/pwd",
        )
    )
    ordered = bool(
        capture.command_lifecycle_integrity
        and secret is not None
        and write is not None
        and network is not None
        and recovery is not None
        and len({(p.thread_id, p.turn_id) for p in (secret, write, network, recovery)}) == 1
        and secret.started_sequence
        < secret.terminal_sequence
        < write.started_sequence
        < write.terminal_sequence
        < network.started_sequence
        < network.terminal_sequence
        < recovery.started_sequence
        < recovery.terminal_sequence
    )
    network_result = parse_probe(network.output, network.exit_code) if network else None
    network_denied = bool(
        ordered
        and controls
        and network_result is not None
        and network_result.context == context
        and network_result.expected_exit == 1
    )
    write_denied = bool(ordered and _is_policy_denial(write))
    observed = capture.command_lifecycle_integrity and bool(capture.command_lifecycles)
    commands = HarnessCapabilityObservationV2(
        code_mode_exec_initiated=HarnessObservationState.UNKNOWN,
        nested_exec_command_dispatched=HarnessObservationState.UNKNOWN,
        command_started_count=capture.command_started_count,
        command_terminal_count=capture.command_terminal_count,
        matched_command_count=len(capture.command_lifecycles),
        command_lifecycle_integrity=capture.command_lifecycle_integrity,
        filesystem_denial_observed=write_denied if observed else None,
        network_denial_observed=network_denied if observed else None,
        parent_secret_absence_observed=(
            bool(ordered and secret is not None and secret.exit_code == 0) if observed else None
        ),
        recovery_observed=(
            bool(
                write_denied
                and network_denied
                and recovery is not None
                and recovery.exit_code == 0
                and recovery.output.strip() == str(inputs.fixture_root)
            )
            if observed
            else None
        ),
        approval_request_observed=capture.approval_requested,
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=execution.provider_transcript_hash,
    )
    return P10ObservationV4(
        commands=commands,
        management_receipt_hash=receipt.content_hash,
        controls_valid=controls,
        strict_completion_order=ordered,
        socket_creation_denial_observed=network_denied,
    )


def build_report(
    inputs: InputsV4,
    spec: HarnessCapabilitySpikeSpecV4,
    manifest: AgentRunManifestV3,
    capture: HarnessCapture,
    receipt: P10ManagementReceipt,
    observation: P10ObservationV4,
) -> HarnessCapabilitySpikeReportV4:
    # Reuse the unchanged MCP/skill/proposal/usage rubric; replace all command predicates.
    old = _evaluate_p10_capture(spec, capture, inputs.manual_baseline)
    commands = observation.commands
    runtime = receipt.execution.runtime
    identity_valid = bool(
        runtime is not None
        and runtime.sdk_version == VERSION
        and runtime.runtime_package_version == VERSION
        and runtime.runtime_version.partition(" ")[0] == VERSION
        and runtime.runtime_binary_hash == spec.runtime_binary_hash
    )
    changed = {
        HarnessCapability.SANDBOX: (
            commands.filesystem_denial_observed is True
            and observation.socket_creation_denial_observed,
            "combined boundary denied write; four IP socket creations returned EPERM with controls",
        ),
        HarnessCapability.FAILURE_RECOVERY: (
            commands.recovery_observed is True,
            "both denied command lifecycles completed before successful recovery started",
        ),
        HarnessCapability.PERMISSION_DENIAL: (
            commands.parent_secret_absence_observed is True and not capture.approval_requested,
            "ordered parent-marker probe succeeded and no approval request was observed",
        ),
        HarnessCapability.TRANSCRIPT: (
            capture.event_count > 0
            and capture.transcript_size_bytes <= spec.max_transcript_bytes
            and capture.command_lifecycle_integrity
            and capture.transcript_hash == manifest.normalized_transcript_hash
            and manifest.provider_transcript_hash is not None,
            "bounded provider projection and normalized events have complete command lifecycles",
        ),
        HarnessCapability.THREAD: (
            manifest.run_status is RunStatus.SUCCEEDED
            and identity_valid
            and len(capture.thread_ids) == 1
            and capture.turn_started
            and capture.turn_completed
            and not capture.turn_failed,
            "one attempt completed under the fixed SDK/runtime binary identity",
        ),
    }
    evidence = tuple(sorted({capture.transcript_hash, receipt.content_hash}))
    checks: list[HarnessCapabilityCheck] = []
    for check in old:
        passed, detail = changed.get(check.capability, (check.passed, check.detail))
        checks.append(
            HarnessCapabilityCheck(
                capability=check.capability,
                passed=passed,
                detail=detail,
                evidence_hashes=evidence,
                reason_code=None if passed else ReasonCode.HARNESS_CAPABILITY_MISSING,
            )
        )
    return HarnessCapabilitySpikeReportV4(
        spike_spec_hash=spec.content_hash,
        agent_run_manifest_hash=manifest.content_hash,
        transcript_hash=manifest.normalized_transcript_hash,
        management_receipt_hash=receipt.content_hash,
        checks=tuple(checks),
        decision=HarnessDecision.GO if all(c.passed for c in checks) else HarnessDecision.NO_GO,
        limitations=LIMITATIONS,
        created_at=receipt.after.completed_at,
    )
