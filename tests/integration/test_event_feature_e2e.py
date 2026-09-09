from pathlib import Path

import pytest

from quantos.application import (
    EventFeatureError,
    FrozenEventFeatureAdmissionPolicy,
    publish_event_feature_artifact,
    verify_event_feature_artifact,
)
from quantos.config import load_yaml_contract
from quantos.contracts import (
    EventFeatureAdmissionPolicySpec,
    EventStudyMetric,
    EventStudySpec,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    EvidenceUsePermission,
    ExtractedTextArtifact,
    P13QualificationReport,
    ReasonCode,
    RunStatus,
    TradingSessionResolverPolicy,
    ValidationVerdict,
    sha256_bytes,
)
from quantos.data.snapshot import SyntheticSnapshotBuilder
from quantos.research import EventStudyError, build_event_study, verify_event_study

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
REPOSITORY = Path(__file__).parents[2]
TEXT = "浦发银行公告: 公司决定实施股份回购。\n"


def _inputs():  # type annotation would obscure this fixture's authority chain
    evidence = load_yaml_contract(
        REPOSITORY / "configs/research/p13_synthetic_evidence_v1.yaml",
        EvidenceRecord,
    )
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash=sha256_bytes(TEXT.encode()),
        character_count=len(TEXT),
        page_count=1,
        parser_name="fixture",
        parser_version="1",
        parser_config_hash="5" * 64,
        code_commit_hash="6" * 40,
        runtime_fingerprint_hash="7" * 64,
    )
    start = TEXT.index("股份回购")
    end = start + len("股份回购")
    citation = EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        page=1,
        char_start=start,
        char_end=end,
        cited_text_hash=sha256_bytes(TEXT[start:end].encode()),
    )
    proposal = EvidenceExtractionProposal(
        proposal_id="share-repurchase-001",
        agent_run_hash="8" * 64,
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        event_label="share_repurchase",
        entity_refs=("600000.SH",),
        proposed_event_time=evidence.published_at,
        citations=(citation,),
        limitations=("AGENT_PROPOSAL",),
    )
    policy = FrozenEventFeatureAdmissionPolicy(
        load_yaml_contract(
            REPOSITORY / "configs/research/p13_share_repurchase_benchmark_v1.yaml",
            EventFeatureAdmissionPolicySpec,
        )
    )
    resolver = load_yaml_contract(
        REPOSITORY / "configs/research/p13_trading_session_resolver_v1.yaml",
        TradingSessionResolverPolicy,
    )
    return evidence, extracted, proposal, policy, resolver


def test_qualified_share_repurchase_event_and_study_are_reproducible(tmp_path: Path) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    evidence, extracted, proposal, policy, resolver = _inputs()

    first = publish_event_feature_artifact(
        evidence=evidence,
        extracted_text=extracted,
        extracted_text_content=TEXT,
        proposal=proposal,
        admission_policy=policy,
        resolver_policy=resolver,
        snapshot_path=snapshot.path,
        output_root=tmp_path / "features-a",
        code_commit_hash="9" * 40,
        runtime_fingerprint_hash="a" * 64,
        limitations=("SINGLE_SOURCE_NON_VINTAGE", "SYNTHETIC_FIXTURE"),
    )
    second = publish_event_feature_artifact(
        evidence=evidence,
        extracted_text=extracted,
        extracted_text_content=TEXT,
        proposal=proposal,
        admission_policy=policy,
        resolver_policy=resolver,
        snapshot_path=snapshot.path,
        output_root=tmp_path / "features-b",
        code_commit_hash="9" * 40,
        runtime_fingerprint_hash="a" * 64,
        limitations=("SINGLE_SOURCE_NON_VINTAGE", "SYNTHETIC_FIXTURE"),
    )

    assert first.manifest.artifact_hash == second.manifest.artifact_hash
    assert first.feature.rows[0].effective_trade_date.isoformat() == "2024-01-03"
    assert first.feature.source_snapshot_hash == snapshot.manifest.snapshot_hash
    assert verify_event_feature_artifact(first.path) == first.manifest
    repeated = publish_event_feature_artifact(
        evidence=evidence,
        extracted_text=extracted,
        extracted_text_content=TEXT,
        proposal=proposal,
        admission_policy=policy,
        resolver_policy=resolver,
        snapshot_path=snapshot.path,
        output_root=tmp_path / "features-a",
        code_commit_hash="9" * 40,
        runtime_fingerprint_hash="a" * 64,
        limitations=("SINGLE_SOURCE_NON_VINTAGE", "SYNTHETIC_FIXTURE"),
    )
    assert repeated.path == first.path

    spec = EventStudySpec(
        study_id="share-repurchase-post-event-v1",
        event_feature_artifact_hash=first.manifest.artifact_hash,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        benchmark_id="000300.SH",
        code_commit_hash="9" * 40,
        runtime_fingerprint_hash="a" * 64,
        window_start=0,
        window_end=1,
        metrics=tuple(sorted(EventStudyMetric, key=str)),
    )
    study_a = build_event_study(
        feature_artifact_path=first.path,
        snapshot_path=snapshot.path,
        spec=spec,
        output_root=tmp_path / "studies-a",
    )
    study_b = build_event_study(
        feature_artifact_path=second.path,
        snapshot_path=snapshot.path,
        spec=spec,
        output_root=tmp_path / "studies-b",
    )

    assert study_a.manifest.artifact_hash == study_b.manifest.artifact_hash
    assert study_a.summary.event_count == 1
    assert study_a.summary.mean_abnormal_return == pytest.approx(10.5 / 10.4 - 3350.0 / 3310.0)
    assert study_a.summary.mean_car == study_a.summary.mean_abnormal_return
    assert verify_event_study(study_a.path) == study_a.manifest
    repeated_study = build_event_study(
        feature_artifact_path=first.path,
        snapshot_path=snapshot.path,
        spec=spec,
        output_root=tmp_path / "studies-a",
    )
    assert repeated_study.path == study_a.path

    (study_a.path / "event-study-summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EventStudyError) as tampered_study:
        verify_event_study(study_a.path)
    assert tampered_study.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    (first.path / "feature.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EventFeatureError) as tampered_feature:
        verify_event_feature_artifact(first.path)
    assert tampered_feature.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_unlicensed_or_inexact_extraction_cannot_publish(tmp_path: Path) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    evidence, extracted, proposal, policy, resolver = _inputs()
    restricted = evidence.model_copy(update={"use_permission": EvidenceUsePermission.UNKNOWN})

    with pytest.raises(EventFeatureError) as denied:
        publish_event_feature_artifact(
            evidence=restricted,
            extracted_text=extracted,
            extracted_text_content=TEXT,
            proposal=proposal,
            admission_policy=policy,
            resolver_policy=resolver,
            snapshot_path=snapshot.path,
            output_root=tmp_path / "denied",
            code_commit_hash="9" * 40,
            runtime_fingerprint_hash="a" * 64,
        )
    assert denied.value.reason_code is ReasonCode.ADMISSION_REJECTED

    wrong_text = TEXT.replace("股份回购", "分红派息")
    with pytest.raises(EventFeatureError) as citation_error:
        publish_event_feature_artifact(
            evidence=evidence,
            extracted_text=extracted,
            extracted_text_content=wrong_text,
            proposal=proposal,
            admission_policy=policy,
            resolver_policy=resolver,
            snapshot_path=snapshot.path,
            output_root=tmp_path / "wrong-text",
            code_commit_hash="9" * 40,
            runtime_fingerprint_hash="a" * 64,
        )
    assert citation_error.value.reason_code is ReasonCode.ADMISSION_REJECTED


def test_event_study_rejects_unbound_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        EventStudySpec(
            study_id="unsupported",
            event_feature_artifact_hash="1" * 64,
            snapshot_hash="2" * 64,
            benchmark_id="000300.SH",
            code_commit_hash="9" * 40,
            runtime_fingerprint_hash="a" * 64,
            window_start=0,
            window_end=1,
            metrics=(EventStudyMetric.MEAN_CAR,),
        )

    with pytest.raises(EventStudyError) as missing:
        verify_event_study(tmp_path / "missing")
    assert missing.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_p13_report_separates_offline_pass_from_unqualified_real_evidence() -> None:
    report = P13QualificationReport(
        benchmark_policy_hash="1" * 64,
        benchmark_case_count=1,
        proposal_count=2,
        schema_valid_count=2,
        citation_accurate_count=1,
        admitted_count=1,
        pit_valid_count=1,
        duplicate_count=0,
        schema_valid_rate=1.0,
        citation_accuracy=0.5,
        admission_rate=0.5,
        pit_valid_rate=0.5,
        duplicate_rate=0.0,
        total_agent_tokens=0,
        offline_engineering_status=RunStatus.SUCCEEDED,
        offline_engineering_verdict=ValidationVerdict.PASS,
        data_qualified_status=RunStatus.FAILED,
        data_qualified_verdict=ValidationVerdict.NOT_EVALUATED,
        data_qualified_reason=ReasonCode.ADMISSION_REJECTED,
        feature_artifact_hash="2" * 64,
        event_study_hash="3" * 64,
        limitations=("REAL_EVIDENCE_PERMISSION_UNKNOWN", "SYNTHETIC_FIXTURE"),
    )

    assert report.offline_engineering_verdict is ValidationVerdict.PASS
    assert report.data_qualified_verdict is ValidationVerdict.NOT_EVALUATED
