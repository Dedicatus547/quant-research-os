#!/usr/bin/env python3
"""Run the complete synthetic SignalArtifact-to-Qlib-BacktestArtifact P5 slice."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantos.application import capture_code_provenance, resolve_experiment
from quantos.backtest import QlibBacktestService, verify_backtest_artifact
from quantos.config import load_yaml_contract
from quantos.contracts.backtest import BacktestReconciliation
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.pit import OperatorDelayPolicy
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.temporal import DecisionSchedule
from quantos.data import QlibViewBuilder, SyntheticSnapshotBuilder
from quantos.research.qlib import FactorSignalArtifactBuilder, build_pit_evidence_collection

SHANGHAI = ZoneInfo("Asia/Shanghai")


def run(
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
) -> dict[str, object]:
    """Build and verify the complete offline P5 artifact chain twice."""

    provenance = capture_code_provenance(workspace)
    snapshot = SyntheticSnapshotBuilder().build(fixture_root, output_root / "snapshots")
    if snapshot.manifest.source_kind is not SnapshotSourceKind.SYNTHETIC_FIXTURE:
        raise ValueError("backtest feasibility accepts only an explicit synthetic fixture")
    view = QlibViewBuilder().build(snapshot.path, output_root / "qlib-views", qlib_source)

    research_policy = load_yaml_contract(
        workspace / "configs" / "research" / "policy_v1.yaml", ResearchPolicy
    )
    validation_policy = load_yaml_contract(
        workspace / "configs" / "validation" / "research_candidate_v1.yaml",
        ValidationPolicy,
    )
    cost_policy = load_yaml_contract(
        workspace / "configs" / "backtest" / "cost_v1.yaml", CostPolicy
    )
    backtest_policy = load_yaml_contract(
        workspace / "configs" / "backtest" / "policy_v1.yaml", BacktestPolicy
    )
    authoring = ExperimentAuthoringSpec.model_validate(
        {
            "experiment_id": "synthetic-backtest-feasibility-v1",
            "evaluation_start": "2024-01-02",
            "evaluation_end": "2024-01-05",
            "expression": {
                "expression_id": "momentum_1d",
                "operator": "return",
                "field": "adjusted_close",
                "window": 1,
            },
            "strategy": {"universe_index": "000300.SH", "top_k": 1},
        }
    )
    provisional = resolve_experiment(
        authoring,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_view_spec_hash=view.manifest.view_spec_hash,
        pit_audit_evidence_hash="0" * 64,
        research_policy_hash=research_policy.content_hash,
        validation_policy_hash=validation_policy.content_hash,
        cost_policy_hash=cost_policy.content_hash,
        backtest_policy_hash=backtest_policy.content_hash,
        code_commit_hash=provenance.commit_hash,
        lockfile_hash=provenance.lockfile_hash,
    )
    schedule = DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 16, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 16, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )
    evidence = build_pit_evidence_collection(
        snapshot.path,
        view.path,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=provisional.expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="qlib-return-delay-60s/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=(schedule,),
    )
    resolved = ResolvedExperimentSpec.model_validate(
        provisional.model_copy(
            update={"pit_audit_evidence_hash": evidence.content_hash}
        ).model_dump(mode="python")
    )
    signal = FactorSignalArtifactBuilder().build(
        resolved,
        evidence,
        view.path,
        output_root / "signals",
        workspace=workspace,
    )
    service = QlibBacktestService()
    first = service.run(
        resolved,
        signal.path,
        view.path,
        cost_policy,
        backtest_policy,
        output_root / "backtests",
        workspace=workspace,
    )
    repeated = service.run(
        resolved,
        signal.path,
        view.path,
        cost_policy,
        backtest_policy,
        output_root / "backtests",
        workspace=workspace,
    )
    if first.path != repeated.path or first.manifest != repeated.manifest:
        raise RuntimeError("P5 double-run did not reproduce the BacktestArtifact")
    verified = verify_backtest_artifact(first.path)
    reconciliation = BacktestReconciliation.model_validate_json(
        (first.path / "reconciliation.json").read_bytes()
    )
    return {
        "schema_version": "backtest-feasibility-report/v1",
        "status": "PASS",
        "snapshot_hash": snapshot.manifest.snapshot_hash,
        "qlib_view_hash": view.manifest.view_hash,
        "signal_artifact_hash": signal.manifest.artifact_hash,
        "signal_content_hash": signal.manifest.signal_content_hash,
        "pit_evidence_hash": evidence.content_hash,
        "backtest_result_hash": verified.result_hash,
        "backtest_config_hash": verified.backtest_config_hash,
        "reconciliation_hash": verified.reconciliation_hash,
        "portfolio_rows": verified.portfolio_rows,
        "position_rows": verified.position_rows,
        "trade_indicator_rows": verified.trade_indicator_rows,
        "order_indicator_rows": verified.order_indicator_rows,
        "risk_metric_rows": verified.risk_metric_rows,
        "reconciliation_checks": [item.name for item in reconciliation.checks],
        "known_limitations": list(verified.known_limitations),
        "double_run_hash_equal": True,
        "native_qlib_components": [
            "WeightStrategyBase",
            "OrderGenWOInteract",
            "Exchange",
            "SimulatorExecutor",
            "Position",
        ],
        "source_kind": snapshot.manifest.source_kind,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("tests/fixtures/synthetic_backtest_snapshot"),
    )
    parser.add_argument(
        "--qlib-source",
        type=Path,
        default=Path(".tools/qlib-0.9.7"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/feasibility/backtest-p5"),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.fixture_root, args.qlib_source, args.output_root, args.workspace),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
