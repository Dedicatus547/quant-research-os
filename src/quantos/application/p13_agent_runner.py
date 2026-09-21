"""Bounded real Codex extraction runner for the P13 announcement benchmark."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from quantos.application.agent_harness import (
    HarnessCapture,
    captures_from_agent_events,
    parse_agent_events,
)
from quantos.application.evidence_mcp import (
    evidence_mcp_policy,
    evidence_mcp_tool_schema_hash,
    evidence_mcp_tools,
)
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, publish_directory
from quantos.contracts.agent import (
    AgentCapability,
    AgentRole,
    AgentRunManifestV2,
    AgentRunManifestV3,
    AgentRunSpecV2,
    AgentRunSpecV3,
    AgentUsage,
    HarnessAttemptRecord,
    ToolInteractionDigest,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceCitation,
    EvidenceExtractionDraft,
    EvidenceExtractionProposal,
)
from quantos.contracts.evidence_acquisition import EvidenceStoreManifest, ExtractionStatus
from quantos.contracts.harness import (
    HarnessCapabilityObservation,
    HarnessEnvironmentVariable,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessMcpServer,
    HarnessRuntimeIdentityV2,
    HarnessRuntimePolicy,
)
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.evidence.publisher import verify_evidence_store
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.integrations.codex.versioning import (
    CODEX_PROTOCOL_IDENTIFIER,
    CODEX_RUNTIME_DISTRIBUTION,
    CODEX_RUNTIME_PACKAGE_VERSION,
    CODEX_SDK_DISTRIBUTION,
    CODEX_SDK_VERSION,
)

MODEL_IDENTIFIER = "gpt-5.6-sol"
MODEL_REASONING_EFFORT = "medium"
SHELL_ENVIRONMENT = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}
MAX_TRANSCRIPT_BYTES = 2_000_000
MAX_INPUT_TOKENS = 250_000
MAX_OUTPUT_TOKENS = 4_096
TIMEOUT_SECONDS = 900
SERVER_NAME = "quantosP13"


class P13AgentRunnerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        manifest: AgentRunManifestV2 | AgentRunManifestV3 | None = None,
    ) -> None:
        super().__init__(message)
        self.manifest = manifest


@dataclass(frozen=True)
class P13AgentInputs:
    store_path: Path
    store: EvidenceStoreManifest
    evidence_hash: str
    extracted_text_hash: str
    raw_bytes_hash: str
    fixture_root: Path
    agents_hash: str
    skill_hash: str
    task_hash: str
    server_hash: str
    output_schema: dict[str, object]
    output_schema_hash: str
    tool_schema_hash: str
    task_text: str

    @property
    def instruction_hashes(self) -> tuple[str, ...]:
        return tuple(sorted((self.agents_hash, self.skill_hash, self.task_hash)))

    @property
    def input_hashes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.store.store_hash,
                    self.evidence_hash,
                    self.extracted_text_hash,
                    self.raw_bytes_hash,
                    self.server_hash,
                    self.output_schema_hash,
                    self.tool_schema_hash,
                    *self.instruction_hashes,
                }
            )
        )


@dataclass(frozen=True)
class P13AgentRunResult:
    manifest: AgentRunManifestV2 | AgentRunManifestV3
    draft: EvidenceExtractionDraft
    proposal: EvidenceExtractionProposal
    path: Path


def extraction_output_schema(
    evidence_hash: str,
    extracted_text_hash: str,
    expected_limitations: tuple[str, ...] | None = None,
) -> dict[str, object]:
    citation = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": "evidence-citation/v1"},
            "evidence_hash": {"type": "string", "const": evidence_hash},
            "extracted_text_hash": {"type": "string", "const": extracted_text_hash},
            "page": {"type": "integer", "minimum": 1},
            "char_start": {"type": "integer", "minimum": 0},
            "char_end": {"type": "integer", "minimum": 1},
            "cited_text_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "required": [
            "schema_version",
            "evidence_hash",
            "extracted_text_hash",
            "page",
            "char_start",
            "char_end",
            "cited_text_hash",
        ],
    }
    limitation_count = len(expected_limitations) if expected_limitations is not None else 5
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "const": "evidence-extraction-draft/v1",
            },
            "authority": {"type": "string", "const": "AGENT_PROPOSAL"},
            "proposal_id": {
                "type": "string",
                "const": "share-repurchase-600010-20250805-agent",
            },
            "evidence_hash": {"type": "string", "const": evidence_hash},
            "extracted_text_hash": {"type": "string", "const": extracted_text_hash},
            "event_label": {"type": "string", "enum": ["other", "share_repurchase"]},
            "entity_refs": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[0-9]{6}\\.(SH|SZ)$"},
                "minItems": 1,
                "maxItems": 4,
            },
            "proposed_event_time": {
                "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
            },
            "citations": {
                "type": "array",
                "items": citation,
                "minItems": 2,
                "maxItems": 2,
            },
            "limitations": {
                "type": "array",
                "items": (
                    {"type": "string", "enum": list(expected_limitations)}
                    if expected_limitations is not None
                    else {"type": "string"}
                ),
                "minItems": limitation_count,
                "maxItems": limitation_count,
            },
        },
        "required": [
            "schema_version",
            "authority",
            "proposal_id",
            "evidence_hash",
            "extracted_text_hash",
            "event_label",
            "entity_refs",
            "proposed_event_time",
            "citations",
            "limitations",
        ],
    }


def load_p13_agent_inputs(
    workspace: Path,
    store_path: Path,
    *,
    expected_store_hash: str,
    expected_evidence_hash: str,
    fixture_root: Path | None = None,
) -> P13AgentInputs:
    store_path = store_path.resolve(strict=True)
    store = verify_evidence_store(store_path)
    if store.store_hash != expected_store_hash:
        raise P13AgentRunnerError("P13 Evidence Store hash does not match")
    matches = [item for item in store.items if item.evidence.content_hash == expected_evidence_hash]
    if len(matches) != 1:
        raise P13AgentRunnerError("P13 evidence is absent or ambiguous")
    item = matches[0]
    if (
        item.extraction_status is not ExtractionStatus.SUCCEEDED
        or item.extracted_text is None
        or item.text_ref is None
    ):
        raise P13AgentRunnerError("P13 evidence has no qualified extracted text")
    fixture_root = (fixture_root or workspace / "tests/fixtures/p13_codex_workspace").resolve(
        strict=True
    )
    paths = {
        "agents": fixture_root / "AGENTS.md",
        "skill": fixture_root / ".agents/skills/quant-event-extractor/SKILL.md",
        "task": fixture_root / "task.md",
        "server": workspace / "scripts/p13_evidence_mcp_server.py",
    }
    payloads = {name: path.read_bytes() for name, path in paths.items()}
    expected_limitations = tuple(sorted(("AGENT_PROPOSAL", *item.evidence.limitations)))
    schema = extraction_output_schema(
        item.evidence.content_hash,
        item.extracted_text.content_hash,
        expected_limitations,
    )
    schema_hash = sha256_bytes(canonical_json_bytes(schema))
    return P13AgentInputs(
        store_path=store_path,
        store=store,
        evidence_hash=item.evidence.content_hash,
        extracted_text_hash=item.extracted_text.content_hash,
        raw_bytes_hash=item.evidence.raw_bytes_hash,
        fixture_root=fixture_root,
        agents_hash=sha256_bytes(payloads["agents"]),
        skill_hash=sha256_bytes(payloads["skill"]),
        task_hash=sha256_bytes(payloads["task"]),
        server_hash=sha256_bytes(payloads["server"]),
        output_schema=schema,
        output_schema_hash=schema_hash,
        tool_schema_hash=evidence_mcp_tool_schema_hash(),
        task_text=payloads["task"].decode("utf-8"),
    )


def _model_configuration(inputs: P13AgentInputs) -> dict[str, object]:
    return {
        "approval_policy": "never",
        "adapter": "openai-codex-python-sdk",
        "ephemeral": True,
        "model_identifier": MODEL_IDENTIFIER,
        "model_reasoning_effort": MODEL_REASONING_EFFORT,
        "network_allowed": False,
        "output_schema_hash": inputs.output_schema_hash,
        "protocol_identifier": CODEX_PROTOCOL_IDENTIFIER,
        "runtime_distribution": CODEX_RUNTIME_DISTRIBUTION,
        "runtime_package_version": CODEX_RUNTIME_PACKAGE_VERSION,
        "sandbox_mode": "read-only",
        "sdk_distribution": CODEX_SDK_DISTRIBUTION,
        "sdk_version": CODEX_SDK_VERSION,
        "shell_environment_inherit": "none",
        "shell_tool_enabled": False,
        "allow_login_shell": False,
        "shell_environment": SHELL_ENVIRONMENT,
        "tool_schema_hash": inputs.tool_schema_hash,
    }


def _execution_request(workspace: Path, inputs: P13AgentInputs) -> HarnessExecutionRequest:
    environment = (
        HarnessEnvironmentVariable(name="LANG", value=SHELL_ENVIRONMENT["LANG"]),
        HarnessEnvironmentVariable(name="PATH", value=SHELL_ENVIRONMENT["PATH"]),
        HarnessEnvironmentVariable(name="TZ", value=SHELL_ENVIRONMENT["TZ"]),
    )
    server = workspace / "scripts/p13_evidence_mcp_server.py"
    python = workspace / ".venv/bin/python"
    return HarnessExecutionRequest(
        run_id="p13-codex-sdk-sse-600010-20250805",
        cwd=str(inputs.fixture_root),
        prompt=inputs.task_text,
        model=MODEL_IDENTIFIER,
        reasoning_effort=MODEL_REASONING_EFFORT,
        runtime_policy=HarnessRuntimePolicy(
            host_environment=environment,
            child_environment=environment,
            shell_environment=environment,
            shell_tool_enabled=False,
        ),
        mcp_servers=(
            HarnessMcpServer(
                name=SERVER_NAME,
                command=str(python),
                args=(
                    str(server),
                    str(inputs.store_path),
                    inputs.store.store_hash,
                    inputs.evidence_hash,
                ),
                enabled_tools=("evidence_cite", "evidence_get"),
                implementation_hash=inputs.server_hash,
                tool_schema_hash=inputs.tool_schema_hash,
            ),
        ),
        output_schema_json=canonical_json_bytes(inputs.output_schema).decode("utf-8"),
        timeout_seconds=TIMEOUT_SECONDS,
        total_timeout_seconds=TIMEOUT_SECONDS,
        max_transcript_bytes=MAX_TRANSCRIPT_BYTES,
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )


def _run_spec(
    inputs: P13AgentInputs,
    benchmark_policy_hash: str,
    request: HarnessExecutionRequest,
) -> AgentRunSpecV3:
    policy = evidence_mcp_policy()
    return AgentRunSpecV3(
        run_id="p13-codex-sdk-sse-600010-20250805",
        role=AgentRole.RESEARCHER,
        capability_policy_hash=policy.content_hash,
        campaign_hash=sha256_bytes(canonical_json_bytes({"benchmark": benchmark_policy_hash})),
        requested_model_configuration_hash=sha256_bytes(
            canonical_json_bytes(_model_configuration(inputs))
        ),
        requested_runtime_policy_hash=request.runtime_policy.content_hash,
        transcript_policy_hash=sha256_bytes(
            canonical_json_bytes({"max_bytes": MAX_TRANSCRIPT_BYTES, "retain": True})
        ),
        retry_budget_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "max_attempts": request.max_attempts,
                    "retry_backoff_milliseconds": request.retry_backoff_milliseconds,
                    "total_timeout_seconds": request.total_timeout_seconds,
                }
            )
        ),
        tool_schema_hash=inputs.tool_schema_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        evidence_hashes=(inputs.evidence_hash,),
        input_artifact_hashes=inputs.input_hashes,
    )


def _run_spec_v2(
    inputs: P13AgentInputs,
    benchmark_policy_hash: str,
    request: HarnessExecutionRequest,
) -> AgentRunSpecV2:
    current = _run_spec(inputs, benchmark_policy_hash, request)
    payload = current.model_dump(mode="python")
    payload["schema_version"] = "agent-run-spec/v2"
    return AgentRunSpecV2.model_validate(payload)


def _tool_interactions(capture: HarnessCapture) -> tuple[ToolInteractionDigest, ...]:
    capabilities = {
        "evidence_cite": AgentCapability.EVIDENCE_CITE,
        "evidence_get": AgentCapability.EVIDENCE_GET,
    }
    return tuple(
        ToolInteractionDigest(
            sequence=index,
            capability=capabilities.get(call.tool, AgentCapability.EVIDENCE_GET),
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


def _parse_success(
    inputs: P13AgentInputs,
    capture: HarnessCapture,
    execution_succeeded: bool,
    *,
    agent_run_hash: str | None = None,
) -> tuple[EvidenceExtractionDraft | None, EvidenceExtractionProposal | None]:
    successful_calls = tuple(
        call
        for call in capture.tool_calls
        if call.status == "completed" and call.error is None and call.result is not None
    )
    if (
        not execution_succeeded
        or not capture.turn_started
        or not capture.turn_completed
        or capture.turn_failed
        or capture.commands
        or capture.approval_requested
        or not capture.agent_messages
        or [(call.server, call.tool) for call in successful_calls]
        != [
            (SERVER_NAME, "evidence_get"),
            (SERVER_NAME, "evidence_cite"),
            (SERVER_NAME, "evidence_cite"),
        ]
    ):
        return None, None
    try:
        draft = EvidenceExtractionDraft.model_validate_json(capture.agent_messages[-1])
    except ValidationError:
        return None, None
    item = next(
        item for item in inputs.store.items if item.evidence.content_hash == inputs.evidence_hash
    )
    expected_limitations = tuple(sorted(("AGENT_PROPOSAL", *item.evidence.limitations)))
    cited: list[EvidenceCitation] = []
    for call in successful_calls[1:]:
        assert call.result is not None
        structured = call.result.get("structured_content")
        if not isinstance(structured, dict):
            return None, None
        try:
            cited.append(EvidenceCitation.model_validate(structured))
        except ValidationError:
            return None, None
    if (
        draft.evidence_hash != inputs.evidence_hash
        or draft.extracted_text_hash != inputs.extracted_text_hash
        or draft.limitations != expected_limitations
        or draft.attributes
        or draft.citations != tuple(cited)
    ):
        return None, None
    proposal = EvidenceExtractionProposal(
        proposal_id=draft.proposal_id,
        agent_run_hash=agent_run_hash or capture.transcript_hash,
        evidence_hash=draft.evidence_hash,
        extracted_text_hash=draft.extracted_text_hash,
        event_label=draft.event_label,
        entity_refs=draft.entity_refs,
        proposed_event_time=draft.proposed_event_time,
        citations=draft.citations,
        attributes=draft.attributes,
        limitations=draft.limitations,
    )
    return draft, proposal


def load_p13_agent_run(
    workspace: Path,
    store_path: Path,
    run_path: Path,
    *,
    expected_store_hash: str,
    expected_evidence_hash: str,
    benchmark_policy_hash: str,
) -> P13AgentRunResult:
    """Replay a specifically addressed successful extraction without calling the model."""
    inputs = load_p13_agent_inputs(
        workspace,
        store_path,
        expected_store_hash=expected_store_hash,
        expected_evidence_hash=expected_evidence_hash,
    )

    def read(name: str) -> bytes:
        return confined_regular_file(run_path, name).read_bytes()

    request = _execution_request(workspace, inputs)
    manifest_bytes = read("agent-run-manifest.json")
    try:
        manifest_payload = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise P13AgentRunnerError("retained P13 manifest is invalid JSON") from error
    if not isinstance(manifest_payload, dict):
        raise P13AgentRunnerError("retained P13 manifest is not an object")
    typed_manifest_payload = cast(dict[str, object], manifest_payload)
    schema_version = typed_manifest_payload.get("schema_version")
    if schema_version == "agent-run-manifest/v3":
        manifest: AgentRunManifestV2 | AgentRunManifestV3 = AgentRunManifestV3.model_validate(
            typed_manifest_payload
        )
        spec: AgentRunSpecV2 | AgentRunSpecV3 = _run_spec(inputs, benchmark_policy_hash, request)
    elif schema_version == "agent-run-manifest/v2":
        manifest = AgentRunManifestV2.model_validate(typed_manifest_payload)
        spec = _run_spec_v2(inputs, benchmark_policy_hash, request)
    else:
        raise P13AgentRunnerError("retained P13 manifest schema is unsupported")
    events = parse_agent_events(read("agent-events.jsonl"), max_bytes=MAX_TRANSCRIPT_BYTES)
    captures = captures_from_agent_events(events, max_bytes=MAX_TRANSCRIPT_BYTES)
    capture = captures[-1]
    replay_interactions = tuple(
        interaction.model_copy(update={"sequence": sequence})
        for sequence, interaction in enumerate(
            (
                interaction
                for attempt_capture in captures
                for interaction in _tool_interactions(attempt_capture)
            ),
            start=1,
        )
    )
    replay_usage = AgentUsage(
        input_tokens=sum(item.usage.get("input_tokens", 0) for item in captures),
        output_tokens=sum(item.usage.get("output_tokens", 0) for item in captures),
        cached_input_tokens=sum(item.usage.get("cached_input_tokens", 0) for item in captures),
        tool_calls=len(replay_interactions),
        retry_count=len(captures) - 1,
    )
    provider_path = run_path / "provider-events.jsonl"
    provider_binding_valid = False
    if manifest.provider_transcript_hash is not None:
        try:
            provider_binding_valid = (
                sha256_bytes(read("provider-events.jsonl")) == manifest.provider_transcript_hash
            )
        except (OSError, ValueError):
            provider_binding_valid = False
    elif manifest.provider_transcript_retention_reason is not None:
        provider_binding_valid = not provider_path.exists() and not provider_path.is_symlink()
    observation_binding_valid = True
    if isinstance(manifest, AgentRunManifestV3):
        try:
            observation_bytes = read("harness-capability-observation.json")
            observation = HarnessCapabilityObservation.model_validate_json(observation_bytes)
            expected_observation = HarnessCapabilityObservation(
                command_count=len(capture.commands),
                shell_command_observed=bool(capture.commands),
                approval_request_observed=capture.approval_requested,
                normalized_transcript_hash=manifest.normalized_transcript_hash,
                provider_transcript_hash=manifest.provider_transcript_hash,
            )
            observation_binding_valid = all(
                (
                    sha256_bytes(observation_bytes) == manifest.capability_observation_hash,
                    observation.content_hash == manifest.capability_observation_hash,
                    observation == expected_observation,
                )
            )
        except (OSError, ValidationError, ValueError):
            observation_binding_valid = False
    draft, proposal = _parse_success(
        inputs,
        capture,
        manifest.run_status is RunStatus.SUCCEEDED,
        agent_run_hash=manifest.normalized_transcript_hash,
    )
    if (
        run_path.name != f"sha256-{manifest.content_hash}"
        or manifest.run_status is not RunStatus.SUCCEEDED
        or manifest.run_spec_hash != spec.content_hash
        or read("agent-run-spec.json") != spec.canonical_bytes()
        or manifest.normalized_transcript_hash != sha256_bytes(read("agent-events.jsonl"))
        or manifest.input_hashes != inputs.input_hashes
        or manifest.interactions != replay_interactions
        or manifest.aggregate_usage != replay_usage
        or tuple(item.event_stream_hash for item in manifest.attempts)
        != tuple(item.transcript_hash for item in captures)
        or not provider_binding_valid
        or not observation_binding_valid
        or draft is None
        or proposal is None
        or manifest.output_proposal_hashes != (proposal.content_hash,)
        or read("extraction-draft.json") != draft.canonical_bytes()
        or read("extraction-proposal.json") != proposal.canonical_bytes()
        or read("output-schema.json") != canonical_json_bytes(inputs.output_schema)
        or read("tool-schema.json") != canonical_json_bytes(evidence_mcp_tools())
        or read("task.md") != inputs.task_text.encode("utf-8")
        or read("harness-request.json") != request.canonical_bytes()
    ):
        raise P13AgentRunnerError("retained P13 run does not bind the requested frozen inputs")
    return P13AgentRunResult(manifest=manifest, draft=draft, proposal=proposal, path=run_path)


def execute_p13_agent(
    workspace: Path,
    store_path: Path,
    output_root: Path,
    *,
    expected_store_hash: str,
    expected_evidence_hash: str,
    benchmark_policy_hash: str,
    fixture_root: Path | None = None,
) -> P13AgentRunResult:
    inputs = load_p13_agent_inputs(
        workspace,
        store_path,
        expected_store_hash=expected_store_hash,
        expected_evidence_hash=expected_evidence_hash,
        fixture_root=fixture_root,
    )
    request = _execution_request(workspace, inputs)
    spec = _run_spec(inputs, benchmark_policy_hash, request)
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    execution = CodexSdkAdapter().execute(request)
    completed_at = datetime.now(UTC)
    capture = execution.capture
    draft, proposal = _parse_success(
        inputs,
        capture,
        execution.terminal_error is None,
        agent_run_hash=execution.normalized_transcript_hash,
    )
    interactions = tuple(
        interaction.model_copy(update={"sequence": sequence})
        for sequence, interaction in enumerate(
            (
                interaction
                for attempt in execution.attempts
                for interaction in _tool_interactions(attempt.capture)
            ),
            start=1,
        )
    )
    aggregate_usage = AgentUsage(
        input_tokens=sum(item.capture.usage.get("input_tokens", 0) for item in execution.attempts),
        output_tokens=sum(
            item.capture.usage.get("output_tokens", 0) for item in execution.attempts
        ),
        cached_input_tokens=sum(
            item.capture.usage.get("cached_input_tokens", 0) for item in execution.attempts
        ),
        tool_calls=len(interactions),
        retry_count=len(execution.attempts) - 1,
    )
    terminal = execution.terminal_error
    if terminal is None and proposal is None:
        terminal_kind = HarnessErrorKind.OUTPUT_INVALID
        terminal_message_hash = sha256_bytes(b"P13 normalized output failed admission")
    else:
        terminal_kind = terminal.kind if terminal else None
        terminal_message_hash = terminal.message_hash if terminal else None
    succeeded = proposal is not None and terminal_kind is None
    proposal_hash = proposal.content_hash if proposal is not None else None
    runtime = execution.runtime
    provider_transcript_hash = (
        sha256_bytes(execution.provider_transcript)
        if execution.provider_transcript is not None
        else None
    )
    observation = HarnessCapabilityObservation(
        command_count=len(capture.commands),
        shell_command_observed=bool(capture.commands),
        approval_request_observed=capture.approval_requested,
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_transcript_hash,
    )
    manifest = AgentRunManifestV3(
        run_spec_hash=spec.content_hash,
        provider_model_identifier=MODEL_IDENTIFIER,
        sdk_version=runtime.sdk_version if runtime else None,
        runtime_package_version=(
            runtime.runtime_package_version
            if isinstance(runtime, HarnessRuntimeIdentityV2)
            else None
        ),
        runtime_version=runtime.runtime_version if runtime else None,
        runtime_binary_hash=(
            runtime.runtime_binary_hash if isinstance(runtime, HarnessRuntimeIdentityV2) else None
        ),
        protocol_identifier=CODEX_PROTOCOL_IDENTIFIER,
        normalizer_hash=_normalizer_hash(),
        requested_policy_hash=request.runtime_policy.content_hash,
        resolved_runtime_config_hash=None,
        capability_observation_hash=observation.content_hash,
        attested_policy_hash=None,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        tool_schema_hash=inputs.tool_schema_hash,
        interactions=interactions,
        input_hashes=inputs.input_hashes,
        output_proposal_hashes=((proposal_hash,) if proposal_hash is not None else ()),
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_transcript_hash,
        provider_transcript_retention_reason=(
            None if execution.provider_transcript is not None else "SDK_HOST_UNAVAILABLE"
        ),
        attempts=tuple(
            HarnessAttemptRecord(
                attempt_index=item.capture.attempt_index,
                provider_thread_id=(
                    item.capture.thread_ids[-1] if item.capture.thread_ids else None
                ),
                event_stream_hash=item.capture.transcript_hash,
                usage=AgentUsage(
                    input_tokens=item.capture.usage.get("input_tokens", 0),
                    output_tokens=item.capture.usage.get("output_tokens", 0),
                    cached_input_tokens=item.capture.usage.get("cached_input_tokens", 0),
                    tool_calls=len(item.capture.tool_calls),
                    retry_count=0,
                ),
                terminal_error_kind=(
                    (
                        terminal_kind.value
                        if item is execution.attempts[-1] and terminal_kind is not None
                        else None
                    )
                    if item.terminal_error is None
                    else item.terminal_error.kind.value
                ),
                terminal_error_message_hash=(
                    terminal_message_hash
                    if item is execution.attempts[-1] and item.terminal_error is None
                    else (
                        item.terminal_error.message_hash
                        if item.terminal_error is not None
                        else None
                    )
                ),
                error_retryable=(item.terminal_error.retryable if item.terminal_error else False),
                produced_proposal_hash=(
                    proposal_hash if succeeded and item is execution.attempts[-1] else None
                ),
                started_at=started_at,
                completed_at=completed_at,
            )
            for item in execution.attempts
        ),
        aggregate_usage=aggregate_usage,
        run_status=RunStatus.SUCCEEDED if succeeded else RunStatus.FAILED,
        failure_reason_code=(None if succeeded else _failure_reason(terminal_kind)),
        limitations=(
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "SINGLE_SOURCE_NON_VINTAGE",
        ),
        started_at=started_at,
        completed_at=completed_at,
    )
    with tempfile.TemporaryDirectory(prefix=".p13-agent-", dir=output_root) as temporary:
        temporary_path = Path(temporary)
        staging = temporary_path / "published"
        staging.mkdir()
        atomic_write_bytes(staging / "agent-run-manifest.json", manifest.canonical_bytes())
        atomic_write_bytes(staging / "agent-run-spec.json", spec.canonical_bytes())
        atomic_write_bytes(staging / "agent-events.jsonl", execution.normalized_transcript)
        atomic_write_bytes(
            staging / "harness-capability-observation.json", observation.canonical_bytes()
        )
        atomic_write_bytes(staging / "harness-request.json", request.canonical_bytes())
        if execution.provider_transcript is not None:
            atomic_write_bytes(staging / "provider-events.jsonl", execution.provider_transcript)
        atomic_write_bytes(
            staging / "output-schema.json", canonical_json_bytes(inputs.output_schema)
        )
        atomic_write_bytes(staging / "task.md", inputs.task_text.encode("utf-8"))
        atomic_write_bytes(staging / "tool-schema.json", canonical_json_bytes(evidence_mcp_tools()))
        if draft is not None and proposal is not None:
            atomic_write_bytes(staging / "extraction-draft.json", draft.canonical_bytes())
            atomic_write_bytes(staging / "extraction-proposal.json", proposal.canonical_bytes())
        destination = output_root / f"sha256-{manifest.content_hash}"
        publish_directory(staging, destination)
    if draft is None or proposal is None:
        raise P13AgentRunnerError(
            f"P13 Codex extraction failed; immutable run: {destination.as_posix()}",
            manifest=manifest,
        )
    return P13AgentRunResult(manifest=manifest, draft=draft, proposal=proposal, path=destination)


def _normalizer_hash() -> str:
    module_path = Path(__file__).parents[1] / "integrations/codex/event_normalizer.py"
    return sha256_bytes(module_path.read_bytes())


def _failure_reason(kind: HarnessErrorKind | None) -> str:
    mapping = {
        HarnessErrorKind.AUTH_UNAVAILABLE: ReasonCode.HARNESS_AUTH_UNAVAILABLE,
        HarnessErrorKind.CONFIGURATION_INVALID: ReasonCode.HARNESS_CONFIGURATION_INVALID,
        HarnessErrorKind.INTERRUPTED: ReasonCode.HARNESS_INTERRUPTED,
        HarnessErrorKind.MCP_FAILED: ReasonCode.HARNESS_MCP_FAILED,
        HarnessErrorKind.OUTPUT_INVALID: ReasonCode.HARNESS_OUTPUT_INVALID,
        HarnessErrorKind.OVERLOADED: ReasonCode.HARNESS_OVERLOADED,
        HarnessErrorKind.PERMISSION_DENIED: ReasonCode.HARNESS_PERMISSION_DENIED,
        HarnessErrorKind.PROTOCOL_UNSUPPORTED: ReasonCode.HARNESS_PROTOCOL_UNSUPPORTED,
        HarnessErrorKind.QUOTA_EXHAUSTED: ReasonCode.HARNESS_QUOTA_EXHAUSTED,
        HarnessErrorKind.RUNTIME_MISMATCH: ReasonCode.HARNESS_RUNTIME_MISMATCH,
        HarnessErrorKind.TIMEOUT: ReasonCode.HARNESS_TIMEOUT,
        HarnessErrorKind.TRANSPORT_CLOSED: ReasonCode.HARNESS_TRANSPORT_FAILED,
        HarnessErrorKind.TRANSPORT_START_FAILED: ReasonCode.HARNESS_TRANSPORT_FAILED,
    }
    if kind is None:
        return ReasonCode.HARNESS_EXECUTION_FAILED.value
    return mapping.get(kind, ReasonCode.HARNESS_EXECUTION_FAILED).value
