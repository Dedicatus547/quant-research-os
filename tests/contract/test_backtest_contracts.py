from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.backtest import BacktestArtifactFile, BacktestArtifactManifest


def _files() -> tuple[BacktestArtifactFile, ...]:
    return tuple(
        BacktestArtifactFile(logical_path=name, sha256=str(index) * 64, size_bytes=index)
        for index, name in enumerate(
            (
                "backtest-config.json",
                "order-indicators.parquet",
                "portfolio.parquet",
                "positions.parquet",
                "reconciliation.json",
                "risk-metrics.parquet",
                "trade-indicators.parquet",
            ),
            start=1,
        )
    )


def test_backtest_manifest_is_content_addressed_and_time_independent() -> None:
    values = dict(
        resolved_experiment_hash="a" * 64,
        signal_artifact_hash="b" * 64,
        snapshot_hash="c" * 64,
        qlib_view_hash="d" * 64,
        qlib_version="0.9.7",
        cost_policy_hash="e" * 64,
        backtest_policy_hash="f" * 64,
        backtest_config_hash="1" * 64,
        reconciliation_hash="2" * 64,
        start_date=date(2024, 1, 8),
        end_date=date(2024, 1, 12),
        portfolio_rows=5,
        position_rows=4,
        trade_indicator_rows=5,
        order_indicator_rows=2,
        risk_metric_rows=10,
        files=_files(),
        known_limitations=(
            "QLIB_TARGET_WEIGHT_PRECHECK_BLOCKS_BOTH_DIRECTIONS_IF_EITHER_LIMIT_SIDE_IS_SET",
            "QLIB_HAS_NO_STABLE_PER_ORDER_REJECTION_REASON_CODE",
        ),
    )
    first = BacktestArtifactManifest.create(
        **values,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
    )
    second = BacktestArtifactManifest.create(
        **values,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
    )

    assert first.result_hash == second.result_hash
    assert first.content_hash == first.result_hash

    with pytest.raises(ValidationError, match="artifact file set"):
        BacktestArtifactManifest.create(
            **{**values, "files": _files()[:-1]},  # type: ignore[arg-type]
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
