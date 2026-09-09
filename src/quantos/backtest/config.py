"""Translate hash-bound policies to an explicit Qlib backtest configuration."""

from __future__ import annotations

from quantos.contracts.backtest import QlibBacktestConfig
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.event_research import ResolvedEventExperimentSpec
from quantos.contracts.research import ResolvedExperimentSpec
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.research.qlib.universe import QlibResearchError


def translate_backtest_config(
    resolved: ResolvedExperimentSpec | ResolvedEventExperimentSpec,
    *,
    signal_artifact_hash: str,
    cost_policy: CostPolicy,
    backtest_policy: BacktestPolicy,
    schedules: tuple[DecisionSchedule, ...],
    exchange_codes: tuple[str, ...],
) -> QlibBacktestConfig:
    if not schedules:
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "decision schedules must be nonempty",
        )
    signal_dates = tuple(schedule.signal_time.date() for schedule in schedules)
    execution_dates = tuple(schedule.execution_time.date() for schedule in schedules)
    if signal_dates != tuple(sorted(set(signal_dates))) or execution_dates != tuple(
        sorted(set(execution_dates))
    ):
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "signal and execution dates must be sorted and unique",
        )
    if not exchange_codes or exchange_codes != tuple(sorted(set(exchange_codes))):
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "exchange codes must be nonempty, sorted, and unique",
        )
    if (
        cost_policy.content_hash != resolved.cost_policy_hash
        or backtest_policy.content_hash != resolved.backtest_policy_hash
    ):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "backtest or cost policy does not match the resolved experiment",
        )
    if cost_policy.trade_unit_shares != resolved.strategy.trade_unit_shares:
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "strategy and cost policy trade units do not match",
        )
    expected_benchmark = (
        f"{resolved.strategy.universe_index[-2:]}{resolved.strategy.universe_index[:6]}"
    )
    if backtest_policy.benchmark != expected_benchmark:
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID,
            "backtest benchmark does not match the resolved historical universe",
        )
    volume_expression = f"$volume*{format(cost_policy.volume_limit_fraction, '.17g')}"
    return QlibBacktestConfig(
        resolved_experiment_hash=resolved.content_hash,
        signal_artifact_hash=signal_artifact_hash,
        snapshot_hash=resolved.snapshot_hash,
        qlib_view_hash=resolved.qlib_view_hash,
        qlib_version=resolved.qlib_version,
        cost_policy_hash=cost_policy.content_hash,
        backtest_policy_hash=backtest_policy.content_hash,
        start_date=execution_dates[0],
        end_date=execution_dates[-1],
        exchange_start_date=signal_dates[0],
        exchange_codes=exchange_codes,
        signal_dates=signal_dates,
        execution_dates=execution_dates,
        decision_schedule_hash=sha256_bytes(
            canonical_json_bytes([schedule.model_dump(mode="python") for schedule in schedules])
        ),
        benchmark=backtest_policy.benchmark,
        initial_cash_cny=backtest_policy.initial_cash_cny,
        top_k=resolved.strategy.top_k,
        max_weight=resolved.strategy.max_weight,
        open_cost_rate=cost_policy.open_cost_rate,
        close_cost_rate=cost_policy.close_cost_rate,
        minimum_cost_cny=cost_policy.minimum_cost_cny,
        trade_unit_shares=resolved.strategy.trade_unit_shares,
        volume_threshold=("current", volume_expression),
    )
