#!/usr/bin/env python3
"""Publish one canonical synthetic SignalArtifact using the real Qlib expression engine."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quantos.application import capture_code_provenance, resolve_experiment
from quantos.config import load_yaml_contract
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
from quantos.data.qlib_view import verify_qlib_view
from quantos.data.snapshot import verify_snapshot
from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    build_pit_evidence_collection,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def run(
    snapshot_path: Path, view_path: Path, output_root: Path, workspace: Path
) -> dict[str, object]:
    snapshot = verify_snapshot(snapshot_path)
    view = verify_qlib_view(view_path)
    if snapshot.source_kind is not SnapshotSourceKind.SYNTHETIC_FIXTURE:
        raise ValueError("signal feasibility script accepts only an explicit synthetic fixture")
    if view.source_snapshot_hash != snapshot.snapshot_hash:
        raise ValueError("Qlib view does not derive from the supplied synthetic snapshot")

    provenance = capture_code_provenance(workspace)
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
            "experiment_id": "synthetic-signal-feasibility-v1",
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
        snapshot_hash=snapshot.snapshot_hash,
        qlib_view_hash=view.view_hash,
        qlib_version=view.qlib_version,
        qlib_view_spec_hash=view.view_spec_hash,
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
        snapshot_path,
        view_path,
        expected_snapshot_hash=snapshot.snapshot_hash,
        expected_view_hash=view.view_hash,
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
    resolved_payload = provisional.model_dump(mode="python")
    resolved_payload["pit_audit_evidence_hash"] = evidence.content_hash
    resolved = ResolvedExperimentSpec.model_validate(resolved_payload)
    result = FactorSignalArtifactBuilder().build(
        resolved,
        evidence,
        view_path,
        output_root,
        workspace=workspace,
    )
    return {
        "schema_version": "signal-feasibility-report/v1",
        "status": "PASS",
        "artifact_hash": result.manifest.artifact_hash,
        "signal_content_hash": result.manifest.signal_content_hash,
        "pit_evidence_hash": evidence.content_hash,
        "row_count": result.manifest.row_count,
        "source_kind": snapshot.source_kind,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_path", type=Path)
    parser.add_argument("view_path", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.snapshot_path, args.view_path, args.output_root, args.workspace),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
