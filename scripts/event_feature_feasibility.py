#!/usr/bin/env python3
"""Run the frozen synthetic P13 EventFeature and EventStudy engineering slice."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantos.application import (
    EventFeatureBuildResult,
    FrozenEventFeatureAdmissionPolicy,
    build_json_rpc_tool_schema,
    capture_code_provenance,
    capture_runtime_fingerprint,
    publish_event_feature_artifact,
)
from quantos.artifacts.store import atomic_write_bytes
from quantos.config import load_yaml_contract
from quantos.contracts import (
    EventFeatureAdmissionPolicySpec,
    EventStudyMetric,
    EventStudySpec,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    ExtractedTextArtifact,
    P13QualificationReport,
    ReasonCode,
    RunStatus,
    TradingSessionResolverPolicy,
    ValidationVerdict,
    canonical_json_bytes,
    sha256_bytes,
)
from quantos.data import SyntheticSnapshotBuilder
from quantos.data.snapshot import SnapshotBuildResult
from quantos.research import EventStudyBuildResult, build_event_study

_TEXT = "浦发银行公告: 公司决定实施股份回购。\n"


def run(workspace: Path, output_root: Path) -> dict[str, object]:
    """Produce two independent hash-identical synthetic P13 pipelines."""

    provenance = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    evidence = load_yaml_contract(
        workspace / "configs/research/p13_synthetic_evidence_v1.yaml", EvidenceRecord
    )
    if evidence.raw_bytes_hash != sha256_bytes(_TEXT.encode()) or evidence.raw_size_bytes != len(
        _TEXT.encode()
    ):
        raise RuntimeError("P13 synthetic Evidence does not bind the frozen text bytes")
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash=evidence.raw_bytes_hash,
        character_count=len(_TEXT),
        page_count=1,
        parser_name="fixture",
        parser_version="1",
        parser_config_hash="5" * 64,
        code_commit_hash="6" * 40,
        runtime_fingerprint_hash="7" * 64,
    )
    start = _TEXT.index("股份回购")
    end = start + len("股份回购")
    citation = EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        page=1,
        char_start=start,
        char_end=end,
        cited_text_hash=sha256_bytes(_TEXT[start:end].encode()),
    )
    proposal = EvidenceExtractionProposal(
        proposal_id="share-repurchase-001",
        agent_run_hash="8" * 64,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        event_label="share_repurchase",
        entity_refs=evidence.entity_refs,
        proposed_event_time=evidence.published_at,
        citations=(citation,),
        limitations=("AGENT_PROPOSAL",),
    )
    policy = FrozenEventFeatureAdmissionPolicy(
        load_yaml_contract(
            workspace / "configs/research/p13_share_repurchase_benchmark_v1.yaml",
            EventFeatureAdmissionPolicySpec,
        )
    )
    resolver = load_yaml_contract(
        workspace / "configs/research/p13_trading_session_resolver_v1.yaml",
        TradingSessionResolverPolicy,
    )
    pipelines: list[tuple[SnapshotBuildResult, EventFeatureBuildResult, EventStudyBuildResult]] = []
    for name in ("pipeline-a", "pipeline-b"):
        root = output_root / name
        snapshot = SyntheticSnapshotBuilder().build(
            workspace / "tests/fixtures/synthetic_snapshot", root / "snapshots"
        )
        feature = publish_event_feature_artifact(
            evidence=evidence,
            extracted_text=extracted,
            extracted_text_content=_TEXT,
            proposal=proposal,
            admission_policy=policy,
            resolver_policy=resolver,
            snapshot_path=snapshot.path,
            output_root=root / "event-features",
            code_commit_hash=provenance.commit_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            limitations=("SINGLE_SOURCE_NON_VINTAGE", "SYNTHETIC_FIXTURE"),
        )
        study_spec = EventStudySpec(
            study_id="share-repurchase-post-event-v1",
            event_feature_artifact_hash=feature.manifest.artifact_hash,
            snapshot_hash=snapshot.manifest.snapshot_hash,
            benchmark_id="000300.SH",
            code_commit_hash=provenance.commit_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            window_start=0,
            window_end=1,
            metrics=tuple(sorted(EventStudyMetric, key=str)),
        )
        study = build_event_study(
            feature_artifact_path=feature.path,
            snapshot_path=snapshot.path,
            spec=study_spec,
            output_root=root / "event-studies",
        )
        pipelines.append((snapshot, feature, study))
    first, second = pipelines
    if (
        first[0].manifest.snapshot_hash != second[0].manifest.snapshot_hash
        or first[1].manifest.artifact_hash != second[1].manifest.artifact_hash
        or first[2].manifest.artifact_hash != second[2].manifest.artifact_hash
    ):
        raise RuntimeError("independent P13 output roots did not reproduce principal hashes")
    qualification = P13QualificationReport(
        benchmark_policy_hash=policy.policy_hash,
        benchmark_case_count=len(policy.spec.cases),
        proposal_count=1,
        schema_valid_count=1,
        citation_accurate_count=1,
        admitted_count=1,
        pit_valid_count=1,
        duplicate_count=0,
        schema_valid_rate=1.0,
        citation_accuracy=1.0,
        admission_rate=1.0,
        pit_valid_rate=1.0,
        duplicate_rate=0.0,
        total_agent_tokens=0,
        offline_engineering_status=RunStatus.SUCCEEDED,
        offline_engineering_verdict=ValidationVerdict.PASS,
        data_qualified_status=RunStatus.FAILED,
        data_qualified_verdict=ValidationVerdict.NOT_EVALUATED,
        data_qualified_reason=ReasonCode.ADMISSION_REJECTED,
        feature_artifact_hash=first[1].manifest.artifact_hash,
        event_study_hash=first[2].manifest.artifact_hash,
        limitations=(
            "NO_AGENT_GENERATED_PROPOSAL",
            "NO_DATA_QUALIFIED_EVENT_RESULT",
            "SINGLE_SOURCE_NON_VINTAGE",
            "SYNTHETIC_FIXTURE",
        ),
    )
    tool_schema = build_json_rpc_tool_schema()
    report: dict[str, object] = {
        "schema_version": "event-feature-feasibility-report/v1",
        "status": "PASS",
        "implementation_commit": provenance.commit_hash,
        "lockfile_hash": provenance.lockfile_hash,
        "runtime_fingerprint_hash": runtime.content_hash,
        "tool_schema_hash": tool_schema.content_hash,
        "qualification_report_hash": qualification.content_hash,
        "qualification": qualification.canonical_payload(),
        "snapshot_hash": first[0].manifest.snapshot_hash,
        "event_feature_artifact_hash": first[1].manifest.artifact_hash,
        "event_study_artifact_hash": first[2].manifest.artifact_hash,
        "independent_roots_equal": True,
    }
    atomic_write_bytes(output_root / "report.json", canonical_json_bytes(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.workspace, args.output_root), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
