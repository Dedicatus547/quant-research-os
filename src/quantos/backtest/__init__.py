"""Thin adapters around Qlib's reference backtest engine."""

from quantos.backtest.config import translate_backtest_config
from quantos.backtest.service import (
    BacktestArtifactBuildResult,
    NormalizedBacktestOutput,
    QlibBacktestService,
    normalize_qlib_outputs,
    reconcile_backtest_output,
    verify_backtest_artifact,
)
from quantos.backtest.strategy import FullReplacementTopKStrategy

__all__ = [
    "BacktestArtifactBuildResult",
    "FullReplacementTopKStrategy",
    "NormalizedBacktestOutput",
    "QlibBacktestService",
    "normalize_qlib_outputs",
    "reconcile_backtest_output",
    "translate_backtest_config",
    "verify_backtest_artifact",
]
