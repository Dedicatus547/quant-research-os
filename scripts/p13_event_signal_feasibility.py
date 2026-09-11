#!/usr/bin/env python3
"""Run the native-Qlib synthetic EventFeature-to-backtest P13 bridge twice."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from quantos.application import (
    FrozenEventFeatureAdmissionPolicy,
    capture_code_provenance,
    capture_runtime_fingerprint,
    publish_event_feature_artifact,
)
from quantos.artifacts.store import atomic_write_bytes
from quantos.backtest import QlibBacktestService, verify_backtest_artifact
from quantos.config import load_yaml_contract
from quantos.contracts import (
    BacktestPolicy,
    CostPolicy,
    EventFeatureAdmissionPolicySpec,
    EventFeatureBenchmarkCase,
    EventSignalAlignmentPolicy,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    ExtractedTextArtifact,
    ResolvedEventExperimentSpec,
    ResolvedStrategySpec,
    TradingSessionResolverPolicy,
    canonical_json_bytes,
    sha256_bytes,
)
from quantos.data import QlibViewBuilder, SyntheticSnapshotBuilder
from quantos.research.qlib import (
    EventSignalArtifactBuilder,
    build_event_signal_evidence,
    verify_event_signal_artifact,
)

_TEXT = "平安银行公告: 公司决定实施股份回购。\n"


def _synthetic_inputs(
    workspace: Path,
) -> tuple[
    EvidenceRecord,
    ExtractedTextArtifact,
    EvidenceExtractionProposal,
    FrozenEventFeatureAdmissionPolicy,
]:
    """Construct only the explicit synthetic input; no real Evidence is implied."""

    base = load_yaml_contract(
        workspace / "configs/research/p13_synthetic_evidence_v1.yaml", EvidenceRecord
    )
    evidence = base.model_copy(
        update={
            "evidence_id": "synthetic-share-repurchase-000001",
            "entity_refs": ("000001.SZ",),
            "raw_bytes_hash": sha256_bytes(_TEXT.encode("utf-8")),
            "raw_size_bytes": len(_TEXT.encode("utf-8")),
        }
    )
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=sha256_bytes(_TEXT.encode("utf-8")),
        text_hash=sha256_bytes(_TEXT.encode("utf-8")),
        character_count=len(_TEXT),
        page_count=1,
        parser_name="fixture",
        parser_version="1",
        parser_config_hash="5" * 64,
        code_commit_hash="6" * 40,
        runtime_fingerprint_hash="7" * 64,
    )
    start = _TEXT.index("股份回购")
    citation = EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        page=1,
        char_start=start,
        char_end=start + len("股份回购"),
        cited_text_hash=sha256_bytes("股份回购".encode()),
    )
    proposal = EvidenceExtractionProposal(
        proposal_id="share-repurchase-000001",
        agent_run_hash="8" * 64,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        event_label="share_repurchase",
        entity_refs=evidence.entity_refs,
        proposed_event_time=evidence.published_at,
        citations=(citation,),
        limitations=("AGENT_PROPOSAL",),
    )
    case = EventFeatureBenchmarkCase(
        case_id="share-repurchase-000001",
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        entity_refs=evidence.entity_refs,
        event_time=evidence.published_at,
        citations=(citation,),
    )
    policy = EventFeatureAdmissionPolicySpec(policy_id="p13-event-native-qlib/v1", cases=(case,))
    return evidence, extracted, proposal, FrozenEventFeatureAdmissionPolicy(policy)


def run(
    workspace: Path,
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
) -> dict[str, object]:
    """Build, verify, and compare two independent native-Qlib bridge pipelines."""

    provenance = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    resolver = load_yaml_contract(
        workspace / "configs/research/p13_trading_session_resolver_v1.yaml",
        TradingSessionResolverPolicy,
    )
    alignment = load_yaml_contract(
        workspace / "configs/research/p13_event_signal_alignment_v1.yaml",
        EventSignalAlignmentPolicy,
    )
    cost = load_yaml_contract(workspace / "configs/backtest/cost_v1.yaml", CostPolicy)
    backtest_policy = load_yaml_contract(
        workspace / "configs/backtest/policy_v1.yaml", BacktestPolicy
    )
    evidence, extracted, proposal, admission = _synthetic_inputs(workspace)
    principal: list[dict[str, object]] = []
    for name in ("run-a", "run-b"):
        root = output_root / name
        snapshot = SyntheticSnapshotBuilder().build(fixture_root, root / "snapshots")
        view = QlibViewBuilder().build(snapshot.path, root / "qlib-views", qlib_source)
        feature = publish_event_feature_artifact(
            evidence=evidence,
            extracted_text=extracted,
            extracted_text_content=_TEXT,
            proposal=proposal,
            admission_policy=admission,
            resolver_policy=resolver,
            snapshot_path=snapshot.path,
            output_root=root / "event-features",
            code_commit_hash=provenance.commit_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            limitations=("SINGLE_SOURCE_NON_VINTAGE", "SYNTHETIC_FIXTURE"),
        )
        event_evidence = build_event_signal_evidence(
            event_feature_path=feature.path,
            view_path=view.path,
            alignment_policy=alignment,
            expected_event_feature_artifact_hash=feature.manifest.artifact_hash,
            expected_snapshot_hash=snapshot.manifest.snapshot_hash,
            expected_qlib_view_hash=view.manifest.view_hash,
            evaluation_start=date(2024, 1, 2),
            evaluation_end=date(2024, 1, 5),
        )
        resolved = ResolvedEventExperimentSpec(
            experiment_id="p13-event-native-qlib-v1",
            event_feature_artifact_hash=feature.manifest.artifact_hash,
            event_signal_alignment_policy_hash=alignment.content_hash,
            event_signal_evidence_hash=event_evidence.content_hash,
            evaluation_start=date(2024, 1, 2),
            evaluation_end=date(2024, 1, 5),
            snapshot_hash=snapshot.manifest.snapshot_hash,
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
            research_policy_hash="b" * 64,
            validation_policy_hash="c" * 64,
            cost_policy_hash=cost.content_hash,
            backtest_policy_hash=backtest_policy.content_hash,
            code_commit_hash=provenance.commit_hash,
            lockfile_hash=provenance.lockfile_hash,
        )
        signal = EventSignalArtifactBuilder().build(
            resolved,
            event_evidence,
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
        verify_event_signal_artifact(signal.path)
        verify_backtest_artifact(backtest.path)
        principal.append(
            {
                "snapshot_hash": snapshot.manifest.snapshot_hash,
                "qlib_view_hash": view.manifest.view_hash,
                "event_feature_artifact_hash": feature.manifest.artifact_hash,
                "event_signal_evidence_hash": event_evidence.content_hash,
                "event_signal_artifact_hash": signal.manifest.artifact_hash,
                "backtest_result_hash": backtest.manifest.result_hash,
                "reconciliation_hash": backtest.manifest.reconciliation_hash,
                "signal_rows": signal.manifest.row_count,
            }
        )
    if principal[0] != principal[1]:
        raise RuntimeError("independent native-Qlib P13 bridge runs did not reproduce exact hashes")
    report = {
        "schema_version": "event-signal-feasibility-report/v1",
        "status": "PASS",
        "release_track": "OFFLINE_ENGINEERING",
        "source_kind": "SYNTHETIC_FIXTURE",
        "implementation_commit": provenance.commit_hash,
        "lockfile_hash": provenance.lockfile_hash,
        "runtime_fingerprint_hash": runtime.content_hash,
        "independent_pipelines": 2,
        "principal_hashes_byte_exact": True,
        "principal": principal[0],
        "native_qlib_components": [
            "Qlib dump_bin",
            "Qlib data-health checks",
            "Qlib SimulatorExecutor",
            "Qlib Exchange",
            "Qlib Position",
        ],
        "limitations": [
            "NO_DATA_QUALIFIED_EVENT_RESULT",
            "SINGLE_SOURCE_NON_VINTAGE",
            "SYNTHETIC_FIXTURE",
        ],
    }
    atomic_write_bytes(output_root / "report.json", canonical_json_bytes(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--qlib-source", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    fixture_root = (
        args.fixture_root or workspace / "tests/fixtures/synthetic_backtest_snapshot"
    ).resolve()
    qlib_source = (args.qlib_source or workspace / ".tools/qlib-0.9.7").resolve()
    output_root = (
        args.output_root or workspace / "artifacts/feasibility/p13-event-signal"
    ).resolve()
    print(
        json.dumps(run(workspace, fixture_root, qlib_source, output_root), indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
