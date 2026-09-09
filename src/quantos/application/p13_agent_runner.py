"""Bounded real Codex extraction runner for the P13 announcement benchmark."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from quantos.application.evidence_mcp import (
    evidence_mcp_policy,
    evidence_mcp_tool_schema_hash,
    evidence_mcp_tools,
)
from quantos.application.harness_runner import verify_codex_version
from quantos.application.harness_spike import CodexExecCapture, parse_codex_exec_jsonl
from quantos.artifacts.store import atomic_write_bytes, publish_directory
from quantos.contracts.agent import (
    AgentCapability,
    AgentRole,
    AgentRunManifest,
    AgentRunSpec,
    AgentUsage,
    ToolInteractionDigest,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceCitation,
    EvidenceExtractionDraft,
    EvidenceExtractionProposal,
)
from quantos.contracts.evidence_acquisition import EvidenceStoreManifest, ExtractionStatus
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.evidence.publisher import verify_evidence_store

CODEX_CLI_VERSION = "codex-cli 0.153.4"
MODEL_IDENTIFIER = "gpt-5.6-sol"
MODEL_REASONING_EFFORT = "medium"
MAX_TRANSCRIPT_BYTES = 2_000_000
MAX_INPUT_TOKENS = 250_000
MAX_OUTPUT_TOKENS = 4_096
TIMEOUT_SECONDS = 900
SERVER_NAME = "quantosP13"


class P13AgentRunnerError(RuntimeError):
    pass


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
    manifest: AgentRunManifest
    draft: EvidenceExtractionDraft
    proposal: EvidenceExtractionProposal
    path: Path


def extraction_output_schema(
    evidence_hash: str, extracted_text_hash: str
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
                "uniqueItems": True,
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
            "attributes": {"type": "array", "maxItems": 0},
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 5,
                "maxItems": 5,
                "uniqueItems": True,
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
            "attributes",
            "limitations",
        ],
    }


def load_p13_agent_inputs(
    workspace: Path,
    store_path: Path,
    *,
    expected_store_hash: str,
    expected_evidence_hash: str,
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
    fixture_root = workspace / "tests/fixtures/p13_codex_workspace"
    paths = {
        "agents": fixture_root / "AGENTS.md",
        "skill": fixture_root / ".agents/skills/quant-event-extractor/SKILL.md",
        "task": fixture_root / "task.md",
        "server": workspace / "scripts/p13_evidence_mcp_server.py",
    }
    payloads = {name: path.read_bytes() for name, path in paths.items()}
    schema = extraction_output_schema(item.evidence.content_hash, item.extracted_text.content_hash)
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
        "codex_cli_version": CODEX_CLI_VERSION,
        "ephemeral": True,
        "model_identifier": MODEL_IDENTIFIER,
        "model_reasoning_effort": MODEL_REASONING_EFFORT,
        "network_allowed": False,
        "output_schema_hash": inputs.output_schema_hash,
        "sandbox_mode": "read-only",
        "shell_tool_enabled": False,
        "tool_schema_hash": inputs.tool_schema_hash,
    }


def _run_spec(inputs: P13AgentInputs, benchmark_policy_hash: str) -> AgentRunSpec:
    policy = evidence_mcp_policy()
    return AgentRunSpec(
        run_id="p13-codex-real-sse-600010-20250805",
        role=AgentRole.RESEARCHER,
        capability_policy_hash=policy.content_hash,
        campaign_hash=sha256_bytes(canonical_json_bytes({"benchmark": benchmark_policy_hash})),
        requested_model_configuration_hash=sha256_bytes(
            canonical_json_bytes(_model_configuration(inputs))
        ),
        tool_schema_hash=inputs.tool_schema_hash,
        instruction_hashes=inputs.instruction_hashes,
        skill_hash=inputs.skill_hash,
        evidence_hashes=(inputs.evidence_hash,),
        input_artifact_hashes=inputs.input_hashes,
    )


def _codex_argv(
    workspace: Path, inputs: P13AgentInputs, output_schema_path: Path
) -> tuple[str, ...]:
    server = workspace / "scripts/p13_evidence_mcp_server.py"
    python = workspace / ".venv/bin/python"
    server_args = [
        str(server),
        str(inputs.store_path),
        inputs.store.store_hash,
        inputs.evidence_hash,
    ]
    return (
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--strict-config",
        "--model",
        MODEL_IDENTIFIER,
        "--sandbox",
        "read-only",
        "--cd",
        str(inputs.fixture_root),
        "--output-schema",
        str(output_schema_path),
        "-c",
        'approval_policy="never"',
        "-c",
        f'model_reasoning_effort="{MODEL_REASONING_EFFORT}"',
        "-c",
        'history.persistence="none"',
        "-c",
        "features.shell_tool=false",
        "-c",
        f'mcp_servers.{SERVER_NAME}.command={json.dumps(str(python))}',
        "-c",
        f"mcp_servers.{SERVER_NAME}.args={json.dumps(server_args)}",
        "-c",
        f'mcp_servers.{SERVER_NAME}.enabled_tools=["evidence_cite","evidence_get"]',
        "-c",
        f"mcp_servers.{SERVER_NAME}.required=true",
        "-",
    )


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in tuple(environment):
        if key.upper().startswith("TUSHARE_"):
            del environment[key]
    return environment


def _tool_interactions(capture: CodexExecCapture) -> tuple[ToolInteractionDigest, ...]:
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
        for index, call in enumerate(capture.mcp_calls, start=1)
    )


def _parse_success(
    inputs: P13AgentInputs, capture: CodexExecCapture, return_code: int
) -> tuple[EvidenceExtractionDraft | None, EvidenceExtractionProposal | None]:
    if (
        return_code != 0
        or not capture.turn_started
        or not capture.turn_completed
        or capture.turn_failed
        or capture.commands
        or capture.approval_requested
        or len(capture.agent_messages) != 1
        or [(call.server, call.tool) for call in capture.mcp_calls]
        != [
            (SERVER_NAME, "evidence_get"),
            (SERVER_NAME, "evidence_cite"),
            (SERVER_NAME, "evidence_cite"),
        ]
        or any(
            call.status != "completed" or call.error is not None or call.result is None
            for call in capture.mcp_calls
        )
    ):
        return None, None
    try:
        draft = EvidenceExtractionDraft.model_validate_json(capture.agent_messages[0])
    except ValidationError:
        return None, None
    item = next(
        item for item in inputs.store.items if item.evidence.content_hash == inputs.evidence_hash
    )
    expected_limitations = tuple(sorted(("AGENT_PROPOSAL", *item.evidence.limitations)))
    cited: list[EvidenceCitation] = []
    for call in capture.mcp_calls[1:]:
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
        agent_run_hash=capture.transcript_hash,
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


def execute_p13_agent(
    workspace: Path,
    store_path: Path,
    output_root: Path,
    *,
    expected_store_hash: str,
    expected_evidence_hash: str,
    benchmark_policy_hash: str,
) -> P13AgentRunResult:
    inputs = load_p13_agent_inputs(
        workspace,
        store_path,
        expected_store_hash=expected_store_hash,
        expected_evidence_hash=expected_evidence_hash,
    )
    spec = _run_spec(inputs, benchmark_policy_hash)
    environment = _environment()
    verify_codex_version(environment)
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix=".p13-agent-", dir=output_root) as temporary:
        temporary_path = Path(temporary)
        schema_path = temporary_path / "output-schema.json"
        atomic_write_bytes(
            schema_path,
            canonical_json_bytes(inputs.output_schema),
            expected_sha256=inputs.output_schema_hash,
        )
        try:
            process = subprocess.run(
                _codex_argv(workspace, inputs, schema_path),
                input=inputs.task_text.encode("utf-8"),
                check=False,
                capture_output=True,
                cwd=inputs.fixture_root,
                env=environment,
                timeout=TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise P13AgentRunnerError(
                "P13 Codex process failed before transcript capture"
            ) from error
        completed_at = datetime.now(UTC)
        capture = parse_codex_exec_jsonl(process.stdout, max_bytes=MAX_TRANSCRIPT_BYTES)
        draft, proposal = _parse_success(inputs, capture, process.returncode)
        interactions = _tool_interactions(capture)
        usage = AgentUsage(
            input_tokens=capture.usage.get("input_tokens", 0),
            output_tokens=capture.usage.get("output_tokens", 0),
            cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
            tool_calls=len(interactions),
            retry_count=0,
        )
        succeeded = draft is not None and proposal is not None
        manifest = AgentRunManifest(
            run_spec_hash=spec.content_hash,
            provider_thread_id=(capture.thread_ids[-1] if capture.thread_ids else "UNAVAILABLE"),
            provider_model_identifier=MODEL_IDENTIFIER,
            model_snapshot_immutable=False,
            model_configuration_hash=spec.requested_model_configuration_hash,
            harness_identifier=CODEX_CLI_VERSION,
            sandbox_policy_hash=sha256_bytes(
                canonical_json_bytes(
                    {"mode": "read-only", "network_allowed": False, "shell_tool": False}
                )
            ),
            permission_policy_hash=sha256_bytes(
                canonical_json_bytes({"approval_policy": "never"})
            ),
            runtime_policy_hash=sha256_bytes(
                canonical_json_bytes({"timeout_seconds": TIMEOUT_SECONDS})
            ),
            instruction_hashes=inputs.instruction_hashes,
            skill_hash=inputs.skill_hash,
            tool_schema_hash=inputs.tool_schema_hash,
            interactions=interactions,
            input_hashes=inputs.input_hashes,
            output_proposal_hashes=((proposal.content_hash,) if proposal is not None else ()),
            transcript_hash=capture.transcript_hash,
            usage=usage,
            run_status=RunStatus.SUCCEEDED if succeeded else RunStatus.FAILED,
            failure_reason_code=None if succeeded else ReasonCode.HARNESS_EXECUTION_FAILED.value,
            limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE", "SINGLE_SOURCE_NON_VINTAGE"),
            started_at=started_at,
            completed_at=completed_at,
        )
        staging = temporary_path / "published"
        staging.mkdir()
        atomic_write_bytes(staging / "agent-run-manifest.json", manifest.canonical_bytes())
        atomic_write_bytes(staging / "agent-run-spec.json", spec.canonical_bytes())
        atomic_write_bytes(staging / "codex-events.jsonl", process.stdout)
        atomic_write_bytes(
            staging / "output-schema.json", canonical_json_bytes(inputs.output_schema)
        )
        atomic_write_bytes(staging / "task.md", inputs.task_text.encode("utf-8"))
        atomic_write_bytes(
            staging / "tool-schema.json", canonical_json_bytes(evidence_mcp_tools())
        )
        if draft is not None and proposal is not None:
            atomic_write_bytes(staging / "extraction-draft.json", draft.canonical_bytes())
            atomic_write_bytes(staging / "extraction-proposal.json", proposal.canonical_bytes())
        destination = output_root / f"sha256-{manifest.content_hash}"
        publish_directory(staging, destination)
    if draft is None or proposal is None:
        raise P13AgentRunnerError(
            f"P13 Codex extraction failed; immutable run: {destination.as_posix()}"
        )
    return P13AgentRunResult(manifest=manifest, draft=draft, proposal=proposal, path=destination)
