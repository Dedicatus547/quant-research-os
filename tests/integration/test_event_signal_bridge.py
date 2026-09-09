from __future__ import annotations

import importlib
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantos.application import (
    FrozenEventFeatureAdmissionPolicy,
    publish_event_feature_artifact,
)
from quantos.backtest import (
    NormalizedBacktestOutput,
    QlibBacktestService,
    verify_backtest_artifact,
)
from quantos.config import load_yaml_contract
from quantos.contracts import (
    BacktestPolicy,
    BacktestReconciliation,
    BacktestReconciliationCheck,
    CostPolicy,
    EventFeatureAdmissionPolicySpec,
    EventFeatureBenchmarkCase,
    EventSignalAlignmentPolicy,
    EvidenceCitation,
    EvidenceExtractionProposal,
    EvidenceRecord,
    ExtractedTextArtifact,
    InstrumentCodeMapping,
    QlibViewSpec,
    ReasonCode,
    ResolvedEventExperimentSpec,
    ResolvedStrategySpec,
    TradingSessionResolverPolicy,
    sha256_bytes,
)
from quantos.data.snapshot import SyntheticSnapshotBuilder
from quantos.research.qlib import (
    EventSignalArtifactBuilder,
    QlibResearchError,
    build_event_signal_evidence,
    verify_event_signal_artifact,
)

backtest_service = importlib.import_module("quantos.backtest.service")
event_signal_service = importlib.import_module("quantos.research.qlib.event_signal")

REPOSITORY = Path(__file__).parents[2]
FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_backtest_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")
TEXT = "平安银行公告: 公司决定实施股份回购。\n"


def _feature_inputs():
    base = load_yaml_contract(
        REPOSITORY / "configs/research/p13_synthetic_evidence_v1.yaml", EvidenceRecord
    )
    evidence = base.model_copy(
        update={
            "evidence_id": "synthetic-share-repurchase-000001",
            "entity_refs": ("000001.SZ",),
            "raw_bytes_hash": sha256_bytes(TEXT.encode()),
            "raw_size_bytes": len(TEXT.encode()),
        }
    )
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=sha256_bytes(TEXT.encode()),
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
    benchmark = EventFeatureBenchmarkCase(
        case_id="share-repurchase-000001",
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        entity_refs=evidence.entity_refs,
        event_time=evidence.published_at,
        citations=(citation,),
    )
    policy = FrozenEventFeatureAdmissionPolicy(
        EventFeatureAdmissionPolicySpec(policy_id="p13-event-signal-test/v1", cases=(benchmark,))
    )
    return evidence, extracted, proposal, policy


def _fake_view(tmp_path: Path, snapshot_hash: str):
    view_path = tmp_path / "view"
    (view_path / "calendars").mkdir(parents=True)
    (view_path / "sidecars").mkdir()
    (view_path / "calendars" / "day.txt").write_text(
        "2024-01-02\n2024-01-03\n2024-01-04\n2024-01-05\n2024-01-08\n2024-01-09\n",
        encoding="utf-8",
    )
    view_spec = QlibViewSpec(
        source_snapshot_hash=snapshot_hash,
        qlib_version="0.9.7",
        qlib_source_commit="1" * 40,
        dump_bin_sha256="2" * 64,
        health_check_sha256="3" * 64,
        mappings=(InstrumentCodeMapping(instrument_id="000001.SZ", qlib_id="SZ000001"),),
    )
    (view_path / "view-spec.json").write_bytes(view_spec.canonical_bytes())
    tradability_schema = pa.schema(
        [
            pa.field("instrument_id", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("is_suspended", pa.bool_(), nullable=False),
            pa.field("is_st", pa.bool_(), nullable=False),
            pa.field("available_at", pa.timestamp("us", tz="Asia/Shanghai"), nullable=False),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "instrument_id": "000001.SZ",
                    "trade_date": date(2024, 1, 5),
                    "is_suspended": False,
                    "is_st": False,
                    "available_at": datetime(2024, 1, 5, 15, 31, tzinfo=SHANGHAI),
                }
            ],
            schema=tradability_schema,
        ),
        view_path / "sidecars" / "tradability.parquet",
    )
    manifest = SimpleNamespace(
        view_hash="4" * 64,
        source_snapshot_hash=snapshot_hash,
        view_spec_hash=view_spec.content_hash,
        qlib_version="0.9.7",
    )
    return view_path, view_spec, manifest


def _reconciliation(config):
    names = (
        "asset_identity",
        "cash_nonnegative",
        "position_value_and_weight",
        "return_cost_turnover_deltas",
        "temporal_schedule",
        "trade_unit_and_no_short",
    )
    return BacktestReconciliation(
        backtest_config_hash=config.content_hash,
        decision_schedule_hash=config.decision_schedule_hash,
        absolute_tolerance=1e-6,
        relative_tolerance=1e-7,
        checks=tuple(
            BacktestReconciliationCheck(
                name=name,  # type: ignore[arg-type]
                checked_rows=1,
                max_abs_error=0.0,
                detail="frozen bridge fixture",
            )
            for name in names
        ),
    )


def test_event_feature_signal_and_existing_qlib_backtest_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    evidence, extracted, proposal, admission = _feature_inputs()
    resolver = load_yaml_contract(
        REPOSITORY / "configs/research/p13_trading_session_resolver_v1.yaml",
        TradingSessionResolverPolicy,
    )
    feature = publish_event_feature_artifact(
        evidence=evidence,
        extracted_text=extracted,
        extracted_text_content=TEXT,
        proposal=proposal,
        admission_policy=admission,
        resolver_policy=resolver,
        snapshot_path=snapshot.path,
        output_root=tmp_path / "features",
        code_commit_hash="9" * 40,
        runtime_fingerprint_hash="a" * 64,
        limitations=("SYNTHETIC_FIXTURE",),
    )
    view_path, view_spec, view_manifest = _fake_view(tmp_path, snapshot.manifest.snapshot_hash)
    monkeypatch.setattr(event_signal_service, "verify_qlib_view", lambda _path: view_manifest)
    alignment = load_yaml_contract(
        REPOSITORY / "configs/research/p13_event_signal_alignment_v1.yaml",
        EventSignalAlignmentPolicy,
    )
    event_pit = build_event_signal_evidence(
        event_feature_path=feature.path,
        view_path=view_path,
        alignment_policy=alignment,
        expected_event_feature_artifact_hash=feature.manifest.artifact_hash,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_qlib_view_hash=view_manifest.view_hash,
        evaluation_start=date(2024, 1, 2),
        evaluation_end=date(2024, 1, 5),
    )
    with pytest.raises(QlibResearchError) as unbound_view:
        build_event_signal_evidence(
            event_feature_path=feature.path,
            view_path=view_path,
            alignment_policy=alignment,
            expected_event_feature_artifact_hash=feature.manifest.artifact_hash,
            expected_snapshot_hash=snapshot.manifest.snapshot_hash,
            expected_qlib_view_hash="f" * 64,
            evaluation_start=date(2024, 1, 2),
            evaluation_end=date(2024, 1, 5),
        )
    assert unbound_view.value.reason_code is ReasonCode.SNAPSHOT_HASH_MISMATCH
    cost = load_yaml_contract(REPOSITORY / "configs/backtest/cost_v1.yaml", CostPolicy)
    backtest_policy = load_yaml_contract(
        REPOSITORY / "configs/backtest/policy_v1.yaml", BacktestPolicy
    )
    resolved = ResolvedEventExperimentSpec(
        experiment_id="p13-event-signal-bridge-v1",
        event_feature_artifact_hash=feature.manifest.artifact_hash,
        event_signal_alignment_policy_hash=alignment.content_hash,
        event_signal_evidence_hash=event_pit.content_hash,
        evaluation_start=date(2024, 1, 2),
        evaluation_end=date(2024, 1, 5),
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view_manifest.view_hash,
        qlib_version=view_manifest.qlib_version,
        qlib_view_spec_hash=view_spec.content_hash,
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
        code_commit_hash="d" * 40,
        lockfile_hash="e" * 64,
    )
    monkeypatch.setattr(event_signal_service, "verify_code_provenance", lambda *_args, **_kw: None)
    builder = EventSignalArtifactBuilder()
    first = builder.build(
        resolved,
        event_pit,
        feature.path,
        view_path,
        alignment,
        tmp_path / "signals-a",
    )
    second = builder.build(
        resolved,
        event_pit,
        feature.path,
        view_path,
        alignment,
        tmp_path / "signals-b",
    )
    repeated = builder.build(
        resolved,
        event_pit,
        feature.path,
        view_path,
        alignment,
        tmp_path / "signals-a",
    )
    assert first.manifest.artifact_hash == second.manifest.artifact_hash
    assert repeated.path == first.path
    assert event_pit.items[0].schedule.signal_time.date() == date(2024, 1, 5)
    assert event_pit.items[0].schedule.execution_time.date() == date(2024, 1, 8)
    assert verify_event_signal_artifact(first.path) == first.manifest

    normalized = NormalizedBacktestOutput(
        portfolio=(
            {
                "trade_date": date(2024, 1, 8),
                "account": 1_000_000.0,
                "return": 0.0,
                "total_turnover": 0.0,
                "turnover": 0.0,
                "total_cost": 0.0,
                "cost": 0.0,
                "value": 0.0,
                "cash": 1_000_000.0,
                "bench": 0.0,
            },
        ),
        positions=(),
        trade_indicators=(
            {
                "trade_date": date(2024, 1, 8),
                "fulfillment_rate": None,
                "price_advantage": None,
                "positive_rate": None,
                "dealt_amount": None,
                "trade_value": None,
                "order_count": None,
            },
        ),
        order_indicators=(),
        risk_metrics=({"scope": "excess_after_cost", "metric": "annualized_return", "value": 0.0},),
    )
    monkeypatch.setattr(backtest_service, "verify_code_provenance", lambda *_args, **_kw: None)
    monkeypatch.setattr(backtest_service, "verify_qlib_view", lambda _path: view_manifest)
    monkeypatch.setattr(
        backtest_service,
        "_load_view_mappings",
        lambda _path: ({"000001.SZ": "SZ000001"}, {"SZ000001": "000001.SZ"}),
    )
    monkeypatch.setattr(backtest_service.qlib, "init", lambda **_kwargs: None)
    monkeypatch.setattr(backtest_service, "_QLIB_BACKTEST", lambda **_kwargs: ({}, {}))
    monkeypatch.setattr(backtest_service, "_factor_lookup", lambda *_args: {})
    monkeypatch.setattr(
        backtest_service, "normalize_qlib_outputs", lambda *_args, **_kw: normalized
    )
    monkeypatch.setattr(
        backtest_service, "reconcile_backtest_output", lambda _o, c, _s: _reconciliation(c)
    )
    result = QlibBacktestService().run(
        resolved,
        first.path,
        view_path,
        cost,
        backtest_policy,
        tmp_path / "backtests",
    )

    assert verify_backtest_artifact(result.path) == result.manifest
    assert result.manifest.signal_artifact_hash == first.manifest.artifact_hash
    assert result.manifest.resolved_experiment_hash == resolved.content_hash

    (first.path / "event-signal-evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(QlibResearchError) as tampered:
        verify_event_signal_artifact(first.path)
    assert tampered.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
