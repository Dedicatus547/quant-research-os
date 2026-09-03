#!/usr/bin/env python3
"""Run two independent native-Qlib synthetic P7 release pipelines."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from validation_feasibility import _PipelineResult, _run_pipeline

from quantos.config import load_yaml_contract
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.events import EventType
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ValidationPolicy,
)
from quantos.contracts.snapshot import SnapshotSourceKind
from quantos.contracts.status import StrategyStatus
from quantos.registry import RegistryService

_RELEASE_TIME = datetime(2024, 2, 1, tzinfo=UTC)
_OOS_EVENT_ID = UUID("2b94c09f-7f95-5c48-a815-4b395a347e9b")


@dataclass(frozen=True)
class _ReleaseResult:
    pipeline: _PipelineResult
    experiment_manifest_hash: str
    registry_index_hash: str
    strategy_status: StrategyStatus


def _register_release(
    *,
    pipeline: _PipelineResult,
    run_root: Path,
    authoring: ExperimentAuthoringSpec,
) -> _ReleaseResult:
    registry = RegistryService(run_root / "registry")
    registration = registry.register_experiment(
        pipeline.report_path,
        event_root=run_root / "events",
        snapshot_path=run_root / "snapshots" / f"sha256-{pipeline.snapshot_hash}",
        qlib_view_path=run_root / "qlib-views" / f"sha256-{pipeline.qlib_view_hash}",
        signal_path=run_root / "signals" / f"sha256-{pipeline.baseline_signal_hash}",
        registered_at=_RELEASE_TIME,
    )
    registry.register_strategy(
        "synthetic-hs300-momentum",
        authoring.strategy.content_hash,
        version=1,
        occurred_at=_RELEASE_TIME,
    )
    for event_type in (
        EventType.VALIDATION_STARTED,
        EventType.VALIDATION_PASSED,
        EventType.STRATEGY_VERSION_VALIDATED,
    ):
        version = registry.append_strategy_event(
            "synthetic-hs300-momentum",
            1,
            event_type,
            authoring.experiment_id,
            occurred_at=_RELEASE_TIME,
        )
    index = registry.verify()
    if (
        registration.manifest.snapshot_source_kind is not SnapshotSourceKind.SYNTHETIC_FIXTURE
        or version.status is not StrategyStatus.VALIDATED
        or len(index.experiments) != 1
        or len(index.strategies) != 1
    ):
        raise RuntimeError("synthetic P7 registry did not reach its expected validated projection")
    return _ReleaseResult(
        pipeline=pipeline,
        experiment_manifest_hash=registration.manifest.manifest_hash,
        registry_index_hash=index.index_hash,
        strategy_status=version.status,
    )


def run(
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
    authoring_path: Path,
    research_policy_path: Path,
    validation_policy_path: Path,
    cost_policy_path: Path,
    backtest_policy_path: Path,
) -> dict[str, object]:
    """Execute and compare two complete Snapshot-to-Registry release pipelines."""

    authoring = load_yaml_contract(authoring_path, ExperimentAuthoringSpec)
    research_policy = load_yaml_contract(research_policy_path, ResearchPolicy)
    validation_policy = load_yaml_contract(validation_policy_path, ValidationPolicy)
    base_cost = load_yaml_contract(cost_policy_path, CostPolicy)
    backtest_policy = load_yaml_contract(backtest_policy_path, BacktestPolicy)
    results: list[_ReleaseResult] = []
    for name in ("run-a", "run-b"):
        run_root = output_root / name
        pipeline = _run_pipeline(
            fixture_root=fixture_root,
            qlib_source=qlib_source,
            output_root=run_root,
            workspace=workspace,
            authoring=authoring,
            research_policy=research_policy,
            validation_policy=validation_policy,
            base_cost=base_cost,
            backtest_policy=backtest_policy,
            validation_now=_RELEASE_TIME,
            validation_event_id=_OOS_EVENT_ID,
        )
        results.append(_register_release(pipeline=pipeline, run_root=run_root, authoring=authoring))
    first, second = results
    exact_fields = (
        "snapshot_hash",
        "qlib_view_hash",
        "baseline_signal_hash",
        "baseline_backtest_hash",
        "report_hash",
    )
    if any(
        getattr(first.pipeline, field) != getattr(second.pipeline, field) for field in exact_fields
    ) or (
        first.experiment_manifest_hash != second.experiment_manifest_hash
        or first.registry_index_hash != second.registry_index_hash
    ):
        raise RuntimeError("independent native-Qlib P7 release runs did not reproduce exact hashes")
    return {
        "schema_version": "release-feasibility-report/v1",
        "status": "PASS",
        "release_track": "OFFLINE_ENGINEERING",
        "source_kind": SnapshotSourceKind.SYNTHETIC_FIXTURE,
        "code_commit_hash": first.pipeline.code_commit_hash,
        "runtime_fingerprint_hash": first.pipeline.runtime_fingerprint_hash,
        "snapshot_hash": first.pipeline.snapshot_hash,
        "qlib_view_hash": first.pipeline.qlib_view_hash,
        "qlib_version": first.pipeline.qlib_version,
        "qlib_source_commit": first.pipeline.qlib_source_commit,
        "signal_artifact_hash": first.pipeline.baseline_signal_hash,
        "backtest_result_hash": first.pipeline.baseline_backtest_hash,
        "validation_report_hash": first.pipeline.report_hash,
        "experiment_manifest_hash": first.experiment_manifest_hash,
        "registry_index_hash": first.registry_index_hash,
        "strategy_status": first.strategy_status,
        "independent_release_pipelines": 2,
        "principal_hashes_byte_exact": True,
        "data_qualified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("tests/fixtures/synthetic_backtest_snapshot"),
    )
    parser.add_argument("--qlib-source", type=Path, default=Path(".tools/qlib-0.9.7"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/feasibility/release-p7"),
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--authoring",
        type=Path,
        default=Path("configs/research/synthetic_validation_experiment_v1.yaml"),
    )
    parser.add_argument(
        "--research-policy",
        type=Path,
        default=Path("configs/research/synthetic_validation_policy_v1.yaml"),
    )
    parser.add_argument(
        "--validation-policy",
        type=Path,
        default=Path("configs/validation/synthetic_engineering_v1.yaml"),
    )
    parser.add_argument("--cost-policy", type=Path, default=Path("configs/backtest/cost_v1.yaml"))
    parser.add_argument(
        "--backtest-policy", type=Path, default=Path("configs/backtest/policy_v1.yaml")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.fixture_root,
                args.qlib_source,
                args.output_root,
                args.workspace,
                args.authoring,
                args.research_policy,
                args.validation_policy,
                args.cost_policy,
                args.backtest_policy,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
