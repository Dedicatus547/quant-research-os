from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import quantos.application.p13_agent_runner as runner
from quantos.application.evidence_mcp import evidence_mcp_tools
from quantos.contracts import (
    EvidenceCitation,
    EvidenceExtractionDraft,
    EvidenceRecord,
    EvidenceStoreManifest,
    ExtractedTextArtifact,
    ExtractionStatus,
    RunStatus,
    canonical_json_bytes,
    sha256_bytes,
)


def _inputs(tmp_path: Path) -> tuple[runner.P13AgentInputs, EvidenceExtractionDraft]:
    evidence = EvidenceRecord(
        evidence_id="p13-test",
        source_kind="EXCHANGE_ANNOUNCEMENT",
        source_locator="https://example.invalid/p13.pdf",
        publisher="SSE",
        retrieval_request_hash="1" * 64,
        retrieval_response_metadata_hash="2" * 64,
        raw_bytes_hash="3" * 64,
        raw_size_bytes=1,
        media_type="application/pdf",
        published_at=datetime(2025, 8, 5, tzinfo=UTC),
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        available_at=datetime(2025, 8, 5, tzinfo=UTC),
        availability_kind="CONSERVATIVE",
        availability_policy_hash="4" * 64,
        collector_version="test",
        license_id="test",
        use_permission="RESEARCH_ALLOWED",
        entity_refs=("600010.SH",),
        limitations=(
            "DATE_ONLY_PUBLICATION_TIME",
            "NEXT_TRADING_SESSION_REQUIRED",
            "SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED",
            "SOURCE_REVISION_HISTORY_NOT_GUARANTEED",
        ),
    )
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash="5" * 64,
        character_count=100,
        page_count=2,
        parser_name="test",
        parser_version="1",
        parser_config_hash="6" * 64,
        code_commit_hash="7" * 40,
        runtime_fingerprint_hash="8" * 64,
    )
    citations = (
        EvidenceCitation(
            evidence_hash=evidence.content_hash,
            extracted_text_hash=extracted.content_hash,
            page=1,
            char_start=1,
            char_end=2,
            cited_text_hash="9" * 64,
        ),
        EvidenceCitation(
            evidence_hash=evidence.content_hash,
            extracted_text_hash=extracted.content_hash,
            page=2,
            char_start=3,
            char_end=4,
            cited_text_hash="a" * 64,
        ),
    )
    draft = EvidenceExtractionDraft(
        proposal_id="share-repurchase-600010-20250805-agent",
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        event_label="share_repurchase",
        entity_refs=evidence.entity_refs,
        proposed_event_time=evidence.published_at,
        citations=citations,
        limitations=tuple(sorted(("AGENT_PROPOSAL", *evidence.limitations))),
    )
    item = SimpleNamespace(evidence=evidence, extracted_text=extracted)
    store = cast(
        EvidenceStoreManifest,
        SimpleNamespace(store_hash="b" * 64, items=(item,)),
    )
    schema = runner.extraction_output_schema(evidence.content_hash, extracted.content_hash)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    inputs = runner.P13AgentInputs(
        store_path=tmp_path,
        store=store,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        fixture_root=fixture,
        agents_hash="c" * 64,
        skill_hash="d" * 64,
        task_hash="e" * 64,
        server_hash="f" * 64,
        output_schema=schema,
        output_schema_hash=sha256_bytes(canonical_json_bytes(schema)),
        tool_schema_hash="0" * 64,
        task_text="extract",
    )
    return inputs, draft


def _jsonl(draft: EvidenceExtractionDraft, *, valid: bool = True) -> bytes:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "thread-p13"},
        {"type": "turn.started"},
    ]
    if valid:
        calls = [
            ("evidence_get", {"view": True}),
            ("evidence_cite", draft.citations[0].canonical_payload()),
            ("evidence_cite", draft.citations[1].canonical_payload()),
        ]
        for index, (tool, structured) in enumerate(calls, start=1):
            events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "id": f"item-{index}",
                        "type": "mcp_tool_call",
                        "server": "quantosP13",
                        "tool": tool,
                        "arguments": {"request": index},
                        "result": {"structured_content": structured},
                        "error": None,
                        "status": "completed",
                    },
                }
            )
        message = draft.canonical_bytes().decode()
    else:
        message = "{}"
    events.extend(
        [
            {
                "type": "item.completed",
                "item": {"id": "final", "type": "agent_message", "text": message},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 50,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 10,
                },
            },
        ]
    )
    return b"".join(canonical_json_bytes(item) + b"\n" for item in events)


def test_p13_output_schema_is_accepted_by_json_schema_providers() -> None:
    schema = runner.extraction_output_schema("a" * 64, "b" * 64)
    properties = schema["properties"]
    required = schema["required"]
    assert isinstance(properties, dict)
    assert isinstance(required, list)
    assert "attributes" not in properties
    assert "attributes" not in required


def test_p13_mcp_tools_are_declared_read_only_and_closed_world() -> None:
    tools = evidence_mcp_tools()

    assert {item["name"] for item in tools} == {"evidence_get", "evidence_cite"}
    assert all(
        item["annotations"]
        == {
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "readOnlyHint": True,
        }
        for item in tools
    )


def test_p13_agent_runner_publishes_successful_transcript_bound_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, draft = _inputs(tmp_path)
    transcript = _jsonl(draft)
    monkeypatch.setattr(runner, "load_p13_agent_inputs", lambda *_args, **_kwargs: inputs)
    monkeypatch.setattr(runner, "verify_codex_version", lambda _environment: None)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=transcript, stderr=b"", returncode=0),
    )
    result = runner.execute_p13_agent(
        tmp_path,
        tmp_path,
        tmp_path / "runs",
        expected_store_hash="b" * 64,
        expected_evidence_hash=inputs.evidence_hash,
        benchmark_policy_hash="1" * 64,
    )

    assert result.manifest.run_status is RunStatus.SUCCEEDED
    assert result.manifest.usage.tool_calls == 3
    assert result.proposal.agent_run_hash == sha256_bytes(transcript)
    assert result.manifest.output_proposal_hashes == (result.proposal.content_hash,)
    assert sorted(item.name for item in result.path.iterdir()) == [
        "agent-run-manifest.json",
        "agent-run-spec.json",
        "codex-events.jsonl",
        "extraction-draft.json",
        "extraction-proposal.json",
        "output-schema.json",
        "task.md",
        "tool-schema.json",
    ]
    assert "TUSHARE_TOKEN" not in runner._environment()
    replay = runner.load_p13_agent_run(
        tmp_path,
        tmp_path,
        result.path,
        expected_store_hash="b" * 64,
        expected_evidence_hash=inputs.evidence_hash,
        benchmark_policy_hash="1" * 64,
    )
    assert replay.proposal == result.proposal
    (result.path / "extraction-proposal.json").write_text("{}")
    with pytest.raises(runner.P13AgentRunnerError, match="does not bind"):
        runner.load_p13_agent_run(
            tmp_path,
            tmp_path,
            result.path,
            expected_store_hash="b" * 64,
            expected_evidence_hash=inputs.evidence_hash,
            benchmark_policy_hash="1" * 64,
        )


def test_load_p13_agent_inputs_binds_fixture_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _draft = _inputs(tmp_path)
    item = inputs.store.items[0]
    item.extraction_status = ExtractionStatus.SUCCEEDED
    item.text_ref = SimpleNamespace(logical_path="text.txt")
    workspace = tmp_path / "workspace"
    fixture = workspace / "tests/fixtures/p13_codex_workspace"
    skill = fixture / ".agents/skills/quant-event-extractor"
    skill.mkdir(parents=True)
    (fixture / "AGENTS.md").write_text("rules", encoding="utf-8")
    (fixture / "task.md").write_text("task", encoding="utf-8")
    (skill / "SKILL.md").write_text("skill", encoding="utf-8")
    server = workspace / "scripts/p13_evidence_mcp_server.py"
    server.parent.mkdir()
    server.write_text("server", encoding="utf-8")
    store_path = tmp_path / "store"
    store_path.mkdir()
    monkeypatch.setattr(runner, "verify_evidence_store", lambda _path: inputs.store)

    loaded = runner.load_p13_agent_inputs(
        workspace,
        store_path,
        expected_store_hash=inputs.store.store_hash,
        expected_evidence_hash=inputs.evidence_hash,
    )

    assert loaded.store_path == store_path.resolve()
    assert loaded.evidence_hash == inputs.evidence_hash
    assert loaded.output_schema_hash == sha256_bytes(canonical_json_bytes(loaded.output_schema))


def test_p13_agent_runner_retains_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, draft = _inputs(tmp_path)
    transcript = _jsonl(draft, valid=False)
    monkeypatch.setattr(runner, "load_p13_agent_inputs", lambda *_args, **_kwargs: inputs)
    monkeypatch.setattr(runner, "verify_codex_version", lambda _environment: None)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=transcript, stderr=b"", returncode=0),
    )
    with pytest.raises(runner.P13AgentRunnerError, match="immutable run"):
        runner.execute_p13_agent(
            tmp_path,
            tmp_path,
            tmp_path / "failed-runs",
            expected_store_hash="b" * 64,
            expected_evidence_hash=inputs.evidence_hash,
            benchmark_policy_hash="1" * 64,
        )
    run_path = next((tmp_path / "failed-runs").iterdir())
    manifest = json.loads((run_path / "agent-run-manifest.json").read_text())
    assert manifest["run_status"] == "FAILED"
    assert "extraction-proposal.json" not in {item.name for item in run_path.iterdir()}


def test_p13_agent_runner_retains_empty_transcript_and_stderr_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _draft = _inputs(tmp_path)
    stderr = b"bounded synthetic stderr"
    monkeypatch.setattr(runner, "load_p13_agent_inputs", lambda *_args, **_kwargs: inputs)
    monkeypatch.setattr(runner, "verify_codex_version", lambda _environment: None)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=b"", stderr=stderr, returncode=1),
    )
    with pytest.raises(runner.P13AgentRunnerError, match="immutable run"):
        runner.execute_p13_agent(
            tmp_path,
            tmp_path,
            tmp_path / "empty-runs",
            expected_store_hash="b" * 64,
            expected_evidence_hash=inputs.evidence_hash,
            benchmark_policy_hash="1" * 64,
        )
    run_path = next((tmp_path / "empty-runs").iterdir())
    manifest = json.loads((run_path / "agent-run-manifest.json").read_text())
    assert manifest["failure_reason_code"] == "HARNESS_TRANSCRIPT_INVALID"
    assert manifest["process_return_code"] == 1
    assert manifest["process_stderr_hash"] == sha256_bytes(stderr)
    assert (run_path / "codex-events.jsonl").read_bytes() == b""


def test_p13_agent_runner_classifies_process_start_failure_as_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, _draft = _inputs(tmp_path)
    monkeypatch.setattr(runner, "load_p13_agent_inputs", lambda *_args, **_kwargs: inputs)
    monkeypatch.setattr(runner, "verify_codex_version", lambda _environment: None)

    def fail_to_start(*_args: object, **_kwargs: object) -> object:
        raise OSError("codex unavailable")

    monkeypatch.setattr(runner.subprocess, "run", fail_to_start)
    with pytest.raises(runner.P13AgentRunnerError, match="immutable run"):
        runner.execute_p13_agent(
            tmp_path,
            tmp_path,
            tmp_path / "start-failure-runs",
            expected_store_hash="b" * 64,
            expected_evidence_hash=inputs.evidence_hash,
            benchmark_policy_hash="1" * 64,
        )
    run_path = next((tmp_path / "start-failure-runs").iterdir())
    manifest = json.loads((run_path / "agent-run-manifest.json").read_text())
    assert manifest["failure_reason_code"] == "HARNESS_EXECUTION_FAILED"
    assert manifest["process_return_code"] is None
    assert manifest["process_stderr_hash"] is None
