#!/usr/bin/env python3
"""Run the complete P13 attempt with strict frozen-input and failure semantics."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import cast

from quantos.application import (
    EventFeatureBuildResult,
    EventFeatureError,
    FrozenEventFeatureAdmissionPolicy,
    capture_code_provenance,
    capture_runtime_fingerprint,
    publish_event_feature_artifact,
)
from quantos.application.p13_agent_runner import (
    P13AgentRunnerError,
    P13AgentRunResult,
    execute_p13_agent,
    load_p13_agent_run,
)
from quantos.application.provenance import ProvenanceError
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    publish_directory,
    regular_tree_files,
    sha256_file,
)
from quantos.backtest import QlibBacktestService, verify_backtest_artifact
from quantos.config import load_yaml_contract
from quantos.contracts import (
    AgentRunManifest,
    BacktestPolicy,
    CostPolicy,
    EventFeatureAdmissionPolicySpec,
    EventFeatureAdmissionRecord,
    EventSignalAlignmentPolicy,
    EventStudyMetric,
    EventStudySpec,
    P13BenchmarkBinding,
    P13QualificationBundle,
    P13QualificationReport,
    PublishedEvidenceItem,
    ReasonCode,
    ResolvedEventExperimentSpec,
    ResolvedStrategySpec,
    RunStatus,
    TradingSessionResolverPolicy,
    ValidationVerdict,
    canonical_json_bytes,
)
from quantos.contracts.evidence import EvidenceExtractionProposal, ExtractedTextArtifact
from quantos.contracts.evidence_acquisition import ExtractionStatus
from quantos.contracts.research import ResearchPolicy, ValidationPolicy
from quantos.data import QlibViewBuilder
from quantos.data.snapshot import verify_snapshot
from quantos.evidence.publisher import EvidencePublicationError, verify_evidence_store
from quantos.research import build_event_study, verify_event_study
from quantos.research.qlib import (
    EventSignalArtifactBuilder,
    build_event_signal_evidence,
    verify_event_signal_artifact,
    verify_event_signal_pit,
)

FROZEN_BINDING = Path("configs/research/p13_real_sse_benchmark_binding_v2.yaml")
REAL_POLICY = Path("configs/research/p13_real_sse_share_repurchase_benchmark_v2.yaml")
RESOLVER_POLICY = Path("configs/research/p13_trading_session_resolver_v1.yaml")
ALIGNMENT_POLICY = Path("configs/research/p13_event_signal_alignment_v1.yaml")
RESEARCH_POLICY = Path("configs/research/policy_v1.yaml")
VALIDATION_POLICY = Path("configs/validation/research_candidate_v1.yaml")
COST_POLICY = Path("configs/backtest/cost_v1.yaml")
BACKTEST_POLICY = Path("configs/backtest/policy_v1.yaml")
DEFAULT_OFFLINE_REPORT = Path("artifacts/feasibility/p13-event-signal/report.json")
FROZEN_OFFLINE_REPORT_HASH = "dbcb2866d3bc65c745172a1ca77f0cd88ced2f9d2ff22cf73381671612c04d60"
EVENT_EVALUATION_START = date(2025, 8, 5)
EVENT_EVALUATION_END = date(2025, 8, 15)
DEFAULT_SNAPSHOT = Path(
    "artifacts/data/snapshots/"
    "sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
)

_CANDIDATE_AGENTS = """# P13 candidate Agent workspace rules

1. Use only the quant-event-extractor skill and the quantosP13 MCP tools.
2. Read exactly the Evidence hash supplied by the task through `evidence_get`.
3. Do not use shell, network, local files, arbitrary paths, secrets, or direct CLI calls.
4. Return only an AGENT_PROPOSAL. Never claim source truth, PIT safety, execution success,
   a validation verdict, or a market conclusion.
5. The Evidence hash for this attempt is `{evidence_hash}`.
"""

_CANDIDATE_SKILL = """---
name: quant-event-extractor
description: Extract one cited event proposal from frozen QuantOS Evidence through typed MCP tools.
---

# Quant event extractor

1. Issue exactly three MCP calls, in this order: one `evidence_get`, then two `evidence_cite`
   calls. Do not emit the final JSON until both citation calls have returned successfully.
2. Use only its hash-bound line spans. Never read paths, files, shell output, or network content.
   For citations, use the view's explicit `extracted_text_hash` field; it is the
   `ExtractedTextArtifact` content hash required by the citation contract, not the nested
   `extracted_text.text_hash` content-bytes hash.
3. If the document supports a share-repurchase progress event, use `share_repurchase`; otherwise
   use `other` and do not imitate the requested benchmark.
4. Build exactly two citations with the two `evidence_cite` calls, in source order: the complete
   event-title line and the complete cumulative-progress paragraph. For this frozen benchmark
   layout, the title span is [99,112) and the cumulative paragraph is the complete consecutive
   span [1066,1193), including every intervening line through the excluded-fees statement.
   Copy each returned citation object verbatim; never calculate `cited_text_hash` yourself.
5. Use the EvidenceRecord `published_at` value as `proposed_event_time`.
6. Copy `entity_refs` exactly, leave `attributes` empty, and set `limitations` to exactly the
   sorted union of `AGENT_PROPOSAL` and every EvidenceRecord limitation. Add no other limitation.
7. Emit only the JSON object required by the output schema. It is a proposal, never a verdict.
"""

_CANDIDATE_TASK = """Use the quant-event-extractor skill to inspect exactly this Evidence object:

`{evidence_hash}`

Classify and cite the announcement according to the skill. Use proposal ID
`share-repurchase-600010-20250805-agent`. Return only the structured Agent proposal draft.
"""


def _write_candidate_fixture(root: Path, evidence_hash: str) -> None:
    atomic_write_bytes(
        root / "AGENTS.md",
        _CANDIDATE_AGENTS.format(evidence_hash=evidence_hash).encode("utf-8"),
    )
    atomic_write_bytes(
        root / ".agents/skills/quant-event-extractor/SKILL.md",
        _CANDIDATE_SKILL.encode("utf-8"),
    )
    atomic_write_bytes(
        root / "task.md",
        _CANDIDATE_TASK.format(evidence_hash=evidence_hash).encode("utf-8"),
    )


def _load_text(store_path: Path, item: PublishedEvidenceItem) -> str:
    if item.extraction_status is not ExtractionStatus.SUCCEEDED:
        raise ValueError("P13 Evidence extraction did not succeed")
    if item.extracted_text is None or item.text_ref is None:
        raise ValueError("P13 Evidence has no extracted text reference")
    text_path = confined_regular_file(store_path, item.text_ref.logical_path)
    text = text_path.read_text(encoding="utf-8")
    if item.extracted_text.text_hash != sha256_file(text_path):
        raise ValueError("P13 extracted text hash does not match its store file")
    if len(text) != item.extracted_text.character_count:
        raise ValueError("P13 extracted text character count disagrees")
    return text


def _offline_report(path: Path | None) -> tuple[str | None, int, bool, bool]:
    if path is None:
        return None, 1, False, False
    try:
        payload = json.loads(path.read_bytes())
        if not isinstance(payload, dict):
            return sha256_file(path), 1, False, False
        report_payload = cast(dict[str, object], payload)
        report_hash = sha256_file(path)
        hash_matches = report_hash == FROZEN_OFFLINE_REPORT_HASH
        passed = hash_matches and (
            report_payload.get("status") == "PASS"
            and report_payload.get("principal_hashes_byte_exact") is True
        )
        roots = report_payload.get("independent_pipelines", 2)
        return (
            report_hash,
            int(roots) if isinstance(roots, int) and roots > 0 else 1,
            passed,
            hash_matches,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, 1, False, False


def _run_agent(
    *,
    workspace: Path,
    store_path: Path,
    store_hash: str,
    evidence_hash: str,
    benchmark_policy_hash: str,
    agent_root: Path,
    candidate: bool,
) -> P13AgentRunResult:
    agent_root.mkdir(parents=True, exist_ok=True)
    if not candidate:
        return execute_p13_agent(
            workspace,
            store_path,
            agent_root,
            expected_store_hash=store_hash,
            expected_evidence_hash=evidence_hash,
            benchmark_policy_hash=benchmark_policy_hash,
        )
    with tempfile.TemporaryDirectory(prefix=".p13-candidate-fixture-", dir=workspace) as fixture:
        fixture_root = Path(fixture)
        _write_candidate_fixture(fixture_root, evidence_hash)
        return execute_p13_agent(
            workspace,
            store_path,
            agent_root,
            expected_store_hash=store_hash,
            expected_evidence_hash=evidence_hash,
            benchmark_policy_hash=benchmark_policy_hash,
            fixture_root=fixture_root,
        )


def _real_pipeline(
    *,
    workspace: Path,
    evidence_item: PublishedEvidenceItem,
    extracted_text_content: str,
    proposal: EvidenceExtractionProposal,
    policy: FrozenEventFeatureAdmissionPolicy,
    resolver: TradingSessionResolverPolicy,
    alignment: EventSignalAlignmentPolicy,
    cost: CostPolicy,
    backtest_policy: BacktestPolicy,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    snapshot_path: Path,
    qlib_source: Path,
    output_root: Path,
) -> dict[str, str | int | bool]:
    provenance = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    evidence = evidence_item.evidence
    extracted = evidence_item.extracted_text
    if extracted is None:
        raise ValueError("qualified P13 Evidence has no extracted text")
    extracted_artifact: ExtractedTextArtifact = extracted
    results: list[dict[str, str | int]] = []
    for name in ("run-a", "run-b"):
        root = output_root / name
        snapshot = snapshot_path.resolve(strict=True)
        snapshot_manifest = verify_snapshot(snapshot)
        view = QlibViewBuilder().build(snapshot, root / "qlib-views", qlib_source)
        feature: EventFeatureBuildResult = publish_event_feature_artifact(
            evidence=evidence,
            extracted_text=extracted_artifact,
            extracted_text_content=extracted_text_content,
            proposal=proposal,
            admission_policy=policy,
            resolver_policy=resolver,
            snapshot_path=snapshot,
            output_root=root / "event-features",
            code_commit_hash=provenance.commit_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            limitations=("SINGLE_SOURCE_NON_VINTAGE",),
        )
        study_spec = EventStudySpec(
            study_id="share-repurchase-600010-post-event-v1",
            event_feature_artifact_hash=feature.manifest.artifact_hash,
            snapshot_hash=feature.manifest.snapshot_hash,
            benchmark_id="000300.SH",
            code_commit_hash=provenance.commit_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            window_start=0,
            window_end=1,
            metrics=tuple(sorted(EventStudyMetric, key=str)),
        )
        study = build_event_study(
            feature_artifact_path=feature.path,
            snapshot_path=snapshot,
            spec=study_spec,
            output_root=root / "event-studies",
        )
        event_signal_evidence = build_event_signal_evidence(
            event_feature_path=feature.path,
            view_path=view.path,
            alignment_policy=alignment,
            expected_event_feature_artifact_hash=feature.manifest.artifact_hash,
            expected_snapshot_hash=snapshot_manifest.snapshot_hash,
            expected_qlib_view_hash=view.manifest.view_hash,
            evaluation_start=EVENT_EVALUATION_START,
            evaluation_end=EVENT_EVALUATION_END,
        )
        resolved = ResolvedEventExperimentSpec(
            experiment_id="p13-real-sse-share-repurchase-v1",
            event_feature_artifact_hash=feature.manifest.artifact_hash,
            event_signal_alignment_policy_hash=alignment.content_hash,
            event_signal_evidence_hash=event_signal_evidence.content_hash,
            evaluation_start=EVENT_EVALUATION_START,
            evaluation_end=EVENT_EVALUATION_END,
            snapshot_hash=snapshot_manifest.snapshot_hash,
            qlib_view_hash=view.manifest.view_hash,
            qlib_version=view.manifest.qlib_version,
            qlib_view_spec_hash=view.manifest.view_spec_hash,
            strategy=ResolvedStrategySpec(
                universe_index="000300.SH",
                top_k=1,
                input_lag_trading_days=0,
                execution_lag_trading_sessions=1,
                max_weight=0.03,
            ),
            research_policy_hash=research_policy.content_hash,
            validation_policy_hash=validation_policy.content_hash,
            cost_policy_hash=cost.content_hash,
            backtest_policy_hash=backtest_policy.content_hash,
            code_commit_hash=provenance.commit_hash,
            lockfile_hash=provenance.lockfile_hash,
        )
        signal = EventSignalArtifactBuilder().build(
            resolved,
            event_signal_evidence,
            feature.path,
            view.path,
            alignment,
            root / "signals",
            workspace=workspace,
        )
        backtest = QlibBacktestService().run(
            resolved,
            signal.path,
            view.path,
            cost,
            backtest_policy,
            root / "backtests",
            workspace=workspace,
        )
        verified_feature = feature.manifest.artifact_hash
        verified_study = verify_event_study(study.path).artifact_hash
        verify_event_signal_artifact(signal.path)
        verify_event_signal_pit(signal.path, view.path)
        verify_backtest_artifact(backtest.path)
        results.append(
            {
                "snapshot_hash": snapshot_manifest.snapshot_hash,
                "qlib_view_hash": view.manifest.view_hash,
                "feature_artifact_hash": verified_feature,
                "event_study_hash": verified_study,
                "event_signal_artifact_hash": signal.manifest.artifact_hash,
                "backtest_result_hash": backtest.manifest.result_hash,
                "reconciliation_hash": backtest.manifest.reconciliation_hash,
            }
        )
    if results[0] != results[1]:
        raise RuntimeError("real P13 independent Qlib roots are not byte-exact")
    return {**results[0], "independent_roots_equal": True, "independent_root_count": 2}


def _make_report(
    *,
    binding: P13BenchmarkBinding,
    benchmark_case_count: int,
    offline_passed: bool,
    offline_status_hash: str | None,
    independent_root_count: int,
    proposal_count: int,
    schema_valid_count: int,
    citation_accurate_count: int,
    admitted_count: int,
    pit_valid_count: int,
    total_agent_tokens: int,
    data_reason: ReasonCode | None,
    feature_artifact_hash: str | None,
    event_study_hash: str | None,
    limitations: set[str],
) -> tuple[P13QualificationReport, P13QualificationBundle]:
    report = P13QualificationReport(
        benchmark_policy_hash=binding.benchmark_policy_hash,
        benchmark_case_count=benchmark_case_count,
        proposal_count=proposal_count,
        schema_valid_count=schema_valid_count,
        citation_accurate_count=citation_accurate_count,
        admitted_count=admitted_count,
        pit_valid_count=pit_valid_count,
        duplicate_count=0,
        schema_valid_rate=schema_valid_count / proposal_count,
        citation_accuracy=citation_accurate_count / proposal_count,
        admission_rate=admitted_count / proposal_count,
        pit_valid_rate=pit_valid_count / proposal_count,
        duplicate_rate=0.0,
        total_agent_tokens=total_agent_tokens,
        offline_engineering_status=(RunStatus.SUCCEEDED if offline_passed else RunStatus.FAILED),
        offline_engineering_verdict=(
            ValidationVerdict.PASS if offline_passed else ValidationVerdict.NOT_EVALUATED
        ),
        data_qualified_status=(RunStatus.SUCCEEDED if data_reason is None else RunStatus.FAILED),
        data_qualified_verdict=(
            ValidationVerdict.PASS if data_reason is None else ValidationVerdict.NOT_EVALUATED
        ),
        data_qualified_reason=data_reason,
        feature_artifact_hash=feature_artifact_hash,
        event_study_hash=event_study_hash,
        limitations=tuple(sorted(limitations)),
    )
    bundle = P13QualificationBundle(
        benchmark_binding_hash=binding.content_hash,
        qualification_report_hash=report.content_hash,
        native_bridge_report_hash=offline_status_hash,
        agent_run_manifest_hash=None,
        admission_record_hash=None,
        feature_artifact_hash=feature_artifact_hash,
        event_study_hash=event_study_hash,
        event_signal_artifact_hash=None,
        backtest_result_hash=None,
        reconciliation_hash=None,
        snapshot_hash=None,
        qlib_view_hash=None,
        independent_root_count=independent_root_count,
        limitations=tuple(sorted(limitations)),
    )
    return report, bundle


def _publish_bundle(
    output_root: Path,
    binding: P13BenchmarkBinding,
    report: P13QualificationReport,
    bundle: P13QualificationBundle,
    references: Mapping[str, object],
    *,
    admission_record: EventFeatureAdmissionRecord | None = None,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"sha256-{bundle.content_hash}"
    if destination.exists() or destination.is_symlink():
        expected_payloads: dict[str, bytes] = {
            "benchmark-binding.json": binding.canonical_bytes(),
            "qualification-report.json": report.canonical_bytes(),
            "bundle.json": bundle.canonical_bytes(),
            "references.json": canonical_json_bytes(references),
        }
        if admission_record is not None:
            expected_payloads["admission-record.json"] = admission_record.canonical_bytes()
        try:
            existing_files = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in regular_tree_files(destination)
            }
        except (ArtifactIntegrityError, OSError, ValueError):
            raise ArtifactConflictError(
                "P13 qualification bundle conflicts with an invalid immutable output"
            ) from None
        if existing_files != expected_payloads:
            raise ArtifactConflictError("P13 qualification bundle conflicts with immutable output")
        return destination
    with tempfile.TemporaryDirectory(prefix=".p13-qualification-", dir=output_root) as staging:
        root = Path(staging)
        atomic_write_bytes(root / "benchmark-binding.json", binding.canonical_bytes())
        atomic_write_bytes(root / "qualification-report.json", report.canonical_bytes())
        atomic_write_bytes(root / "bundle.json", bundle.canonical_bytes())
        atomic_write_bytes(root / "references.json", canonical_json_bytes(references))
        if admission_record is not None:
            atomic_write_bytes(root / "admission-record.json", admission_record.canonical_bytes())
        publish_directory(root, destination)
    return destination


def run(
    *,
    workspace: Path,
    store_path: Path,
    output_root: Path,
    agent_output_root: Path,
    snapshot_path: Path,
    qlib_source: Path,
    offline_report_path: Path | None,
    candidate: bool,
    retained_agent_path: Path | None = None,
) -> dict[str, object]:
    binding = load_yaml_contract(workspace / FROZEN_BINDING, P13BenchmarkBinding)
    policy_spec = load_yaml_contract(workspace / REAL_POLICY, EventFeatureAdmissionPolicySpec)
    if policy_spec.content_hash != binding.benchmark_policy_hash:
        raise ValueError("P13 benchmark binding does not match the frozen policy")
    policy = FrozenEventFeatureAdmissionPolicy(policy_spec)
    offline_hash, root_count, offline_passed, offline_hash_matches = _offline_report(
        offline_report_path
    )
    limitations: set[str] = {"SINGLE_SOURCE_NON_VINTAGE"}
    if offline_passed:
        limitations.add("SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE")
    else:
        limitations.add("NO_NATIVE_Q_LIB_OFFLINE_REPORT")
    if offline_report_path is not None and not offline_hash_matches:
        limitations.add("OFFLINE_REPORT_HASH_MISMATCH")
    if candidate:
        limitations.add("NON_FROZEN_EVIDENCE_ATTEMPT")

    observed_store_hash: str | None = None
    observed_evidence_hash: str | None = None
    observed_text_hash: str | None = None
    agent_result: P13AgentRunResult | None = None
    retained_manifest: AgentRunManifest | None = None
    agent_attempted = False
    admission: EventFeatureAdmissionRecord | None = None
    real: dict[str, str | int | bool] | None = None
    failure_reason: ReasonCode | None = None
    failure_detail: str | None = None
    proposal_count = 1
    schema_valid_count = 0
    citation_accurate_count = 0
    admitted_count = 0
    pit_valid_count = 0
    total_agent_tokens = 0

    try:
        store = verify_evidence_store(store_path.resolve(strict=True))
        observed_store_hash = store.store_hash
    except (EvidencePublicationError, OSError, ValueError):
        store = None
        failure_reason = ReasonCode.SOURCE_INCOMPLETE
        failure_detail = "Evidence Store is unavailable or failed exact-file verification"

    item = None
    extracted_content = None
    if store is not None:
        if not candidate and store.store_hash != binding.evidence_store_hash:
            failure_reason = ReasonCode.SOURCE_INCOMPLETE
            failure_detail = "Evidence Store hash does not match the human-frozen P13 binding"
            limitations.add("HUMAN_FROZEN_STORE_UNAVAILABLE")
        else:
            expected_evidence_hash = binding.evidence_hash
            if candidate:
                if len(store.items) != 1:
                    failure_reason = ReasonCode.SOURCE_INCOMPLETE
                    failure_detail = "candidate Evidence Store is not a single-item attempt"
                else:
                    expected_evidence_hash = store.items[0].evidence.content_hash
            matches = [
                entry
                for entry in store.items
                if entry.evidence.content_hash == expected_evidence_hash
            ]
            if len(matches) != 1:
                failure_reason = ReasonCode.SOURCE_INCOMPLETE
                failure_detail = "expected P13 Evidence is absent or ambiguous"
            else:
                item = matches[0]
                observed_evidence_hash = item.evidence.content_hash
                observed_text_hash = (
                    item.extracted_text.content_hash if item.extracted_text else None
                )
                if not candidate and observed_text_hash != binding.extracted_text_hash:
                    failure_reason = ReasonCode.SOURCE_INCOMPLETE
                    failure_detail = (
                        "ExtractedText artifact hash does not match the human-frozen P13 binding"
                    )
                    limitations.add("HUMAN_FROZEN_BINDING_MISMATCH")
                try:
                    extracted_content = _load_text(store_path, item)
                except (OSError, ValueError):
                    failure_reason = ReasonCode.SOURCE_INCOMPLETE
                    failure_detail = "P13 extracted text failed deterministic store binding"

    if item is not None and extracted_content is not None and failure_reason is None:
        assert store is not None
        assert item.extracted_text is not None
        agent_root = agent_output_root.resolve()
        agent_attempted = True
        try:
            if retained_agent_path is not None:
                if candidate:
                    raise P13AgentRunnerError("retained Agent replay requires frozen mode")
                agent_result = load_p13_agent_run(
                    workspace,
                    store_path,
                    retained_agent_path,
                    expected_store_hash=store.store_hash,
                    expected_evidence_hash=item.evidence.content_hash,
                    benchmark_policy_hash=binding.benchmark_policy_hash,
                )
            else:
                agent_result = _run_agent(
                    workspace=workspace,
                    store_path=store_path,
                    store_hash=store.store_hash,
                    evidence_hash=item.evidence.content_hash,
                    benchmark_policy_hash=binding.benchmark_policy_hash,
                    agent_root=agent_root,
                    candidate=candidate,
                )
        except P13AgentRunnerError as error:
            retained_manifest = error.manifest
            failure_reason = ReasonCode.HARNESS_EXECUTION_FAILED
            if retained_manifest is not None and retained_manifest.failure_reason_code in {
                item.value for item in ReasonCode
            }:
                failure_reason = ReasonCode(retained_manifest.failure_reason_code)
            failure_detail = (
                "P13 Agent attempt failed; immutable AgentRun evidence was retained when available"
            )
            if retained_manifest is not None:
                limitations.add("FAILED_AGENT_RUN_RETAINED")
                total_agent_tokens = (
                    retained_manifest.usage.input_tokens + retained_manifest.usage.output_tokens
                )
        else:
            schema_valid_count = 1
            total_agent_tokens = (
                agent_result.manifest.usage.input_tokens + agent_result.manifest.usage.output_tokens
            )
            admission = policy.evaluate(
                item.evidence,
                item.extracted_text,
                extracted_content,
                agent_result.proposal,
            )
            citation_accurate_count = int(
                any(
                    check.check_id == "citation-text-exact" and check.passed
                    for check in admission.checks
                )
            )
            admitted_count = int(admission.admitted)
            if not admission.admitted:
                failure_reason = ReasonCode.ADMISSION_REJECTED
                failure_detail = "Agent proposal failed the human-frozen P13 admission benchmark"
                limitations.add("NO_DATA_QUALIFIED_EVENT_RESULT")

    if (
        admission is not None
        and admission.admitted
        and not candidate
        and item is not None
        and extracted_content is not None
        and agent_result is not None
    ):
        try:
            resolver = load_yaml_contract(workspace / RESOLVER_POLICY, TradingSessionResolverPolicy)
            alignment = load_yaml_contract(workspace / ALIGNMENT_POLICY, EventSignalAlignmentPolicy)
            cost = load_yaml_contract(workspace / COST_POLICY, CostPolicy)
            backtest_policy = load_yaml_contract(workspace / BACKTEST_POLICY, BacktestPolicy)
            research_policy = load_yaml_contract(workspace / RESEARCH_POLICY, ResearchPolicy)
            validation_policy = load_yaml_contract(workspace / VALIDATION_POLICY, ValidationPolicy)
            real = _real_pipeline(
                workspace=workspace,
                evidence_item=item,
                extracted_text_content=extracted_content,
                proposal=agent_result.proposal,
                policy=policy,
                resolver=resolver,
                alignment=alignment,
                cost=cost,
                backtest_policy=backtest_policy,
                research_policy=research_policy,
                validation_policy=validation_policy,
                snapshot_path=snapshot_path,
                qlib_source=qlib_source,
                output_root=output_root / "real-pipeline",
            )
            pit_valid_count = 1
            failure_reason = None
        except ProvenanceError:
            failure_reason = ReasonCode.REPRODUCIBILITY_MISMATCH
            failure_detail = (
                "real P13 deterministic evaluation requires a clean bound implementation checkout"
            )
        except (EventFeatureError, RuntimeError, OSError, ValueError):
            failure_reason = ReasonCode.QLIB_EXECUTION_FAILED
            failure_detail = "real P13 deterministic downstream execution failed"
    elif admission is not None and admission.admitted and candidate:
        failure_reason = ReasonCode.ADMISSION_REJECTED
        failure_detail = "non-frozen candidate mode cannot promote an admission to qualification"
        limitations.add("NON_FROZEN_EVIDENCE_ATTEMPT")
    elif admission is not None and admission.admitted:
        failure_reason = ReasonCode.SOURCE_INCOMPLETE
        failure_detail = "qualified P13 Evidence content was unavailable to evaluation"

    if failure_reason is not None:
        limitations.add("NO_DATA_QUALIFIED_EVENT_RESULT")
    if agent_result is not None:
        limitations.update(agent_result.manifest.limitations)

    feature_hash = str(real["feature_artifact_hash"]) if real else None
    study_hash = str(real["event_study_hash"]) if real else None
    report, base_bundle = _make_report(
        binding=binding,
        benchmark_case_count=len(policy_spec.cases),
        offline_passed=offline_passed,
        offline_status_hash=offline_hash,
        independent_root_count=root_count,
        proposal_count=proposal_count,
        schema_valid_count=schema_valid_count,
        citation_accurate_count=citation_accurate_count,
        admitted_count=admitted_count,
        pit_valid_count=pit_valid_count,
        total_agent_tokens=total_agent_tokens,
        data_reason=failure_reason,
        feature_artifact_hash=feature_hash,
        event_study_hash=study_hash,
        limitations=limitations,
    )
    agent_manifest_hash = (
        agent_result.manifest.content_hash
        if agent_result
        else (retained_manifest.content_hash if retained_manifest is not None else None)
    )
    bundle = base_bundle.model_copy(
        update={
            "agent_run_manifest_hash": agent_manifest_hash,
            "admission_record_hash": admission.content_hash if admission is not None else None,
            "event_signal_artifact_hash": real.get("event_signal_artifact_hash") if real else None,
            "backtest_result_hash": real.get("backtest_result_hash") if real else None,
            "reconciliation_hash": real.get("reconciliation_hash") if real else None,
            "snapshot_hash": real.get("snapshot_hash") if real else None,
            "qlib_view_hash": real.get("qlib_view_hash") if real else None,
        }
    )
    references = {
        "schema_version": "p13-qualification-references/v1",
        "mode": "NON_FROZEN_CANDIDATE" if candidate else "FROZEN_BENCHMARK",
        "observed_store_hash": observed_store_hash,
        "observed_evidence_hash": observed_evidence_hash,
        "observed_extracted_text_hash": observed_text_hash,
        "failure_reason_code": failure_reason.value if failure_reason else None,
        "failure_detail": failure_detail,
        "agent_attempted": agent_attempted,
        "native_bridge_report_hash": offline_hash,
        "independent_root_count": root_count,
    }
    destination = _publish_bundle(
        output_root,
        binding,
        report,
        bundle,
        references,
        admission_record=admission,
    )
    return {
        "schema_version": "p13-qualification-runner-result/v1",
        "bundle_hash": bundle.content_hash,
        "bundle_path": destination.as_posix(),
        "qualification_report_hash": report.content_hash,
        "offline_engineering_status": report.offline_engineering_status,
        "offline_engineering_verdict": report.offline_engineering_verdict,
        "data_qualified_status": report.data_qualified_status,
        "data_qualified_verdict": report.data_qualified_verdict,
        "data_qualified_reason": report.data_qualified_reason,
        "agent_run_manifest_hash": agent_manifest_hash,
        "feature_artifact_hash": feature_hash,
        "event_study_hash": study_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/qualification/p13"))
    parser.add_argument("--agent-output-root", type=Path)
    parser.add_argument(
        "--agent-run", type=Path, help="verify and reuse one explicit successful run"
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--qlib-source", type=Path, default=Path(".tools/qlib-0.9.7"))
    parser.add_argument("--offline-report", type=Path, default=DEFAULT_OFFLINE_REPORT)
    parser.add_argument(
        "--candidate-store",
        action="store_true",
        help="run a non-frozen extraction attempt without allowing downstream qualification",
    )
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output_root = args.output_root.resolve()
    agent_output_root = (args.agent_output_root or output_root / "agent-runs").resolve()
    offline_report = args.offline_report.resolve() if args.offline_report else None
    print(
        json.dumps(
            run(
                workspace=workspace,
                store_path=args.store.resolve(),
                output_root=output_root,
                agent_output_root=agent_output_root,
                snapshot_path=args.snapshot.resolve(),
                qlib_source=args.qlib_source.resolve(),
                offline_report_path=offline_report,
                candidate=args.candidate_store,
                retained_agent_path=args.agent_run.resolve() if args.agent_run else None,
            ),
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
