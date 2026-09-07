"""Run Qlib's reference backtest and publish normalized immutable evidence."""

from __future__ import annotations

import importlib
import math
import tempfile
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import qlib  # pyright: ignore[reportMissingTypeStubs]
from qlib.config import REG_CN  # pyright: ignore[reportMissingTypeStubs]
from qlib.data import D  # pyright: ignore[reportMissingTypeStubs]

from quantos.application.provenance import ProvenanceError, verify_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.backtest.config import translate_backtest_config
from quantos.contracts.backtest import (
    BacktestArtifactFile,
    BacktestArtifactManifest,
    BacktestReconciliation,
    BacktestReconciliationCheck,
    QlibBacktestConfig,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.qlib_view import QlibViewSpec
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import ResolvedExperimentSpec
from quantos.contracts.research_execution import PITArtifactEvidence
from quantos.contracts.signal import SignalRow
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.research.qlib.pit_evidence import load_pit_artifact_evidence
from quantos.research.qlib.signal import verify_signal_artifact
from quantos.research.qlib.universe import QlibResearchError

PORTFOLIO_SCHEMA = pa.schema(
    [
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("account", pa.float64(), nullable=False),
        pa.field("return", pa.float64(), nullable=False),
        pa.field("total_turnover", pa.float64(), nullable=False),
        pa.field("turnover", pa.float64(), nullable=False),
        pa.field("total_cost", pa.float64(), nullable=False),
        pa.field("cost", pa.float64(), nullable=False),
        pa.field("value", pa.float64(), nullable=False),
        pa.field("cash", pa.float64(), nullable=False),
        pa.field("bench", pa.float64(), nullable=False),
    ]
)

POSITION_SCHEMA = pa.schema(
    [
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("qlib_id", pa.string(), nullable=False),
        pa.field("adjusted_amount", pa.float64(), nullable=False),
        pa.field("adjustment_factor", pa.float64(), nullable=False),
        pa.field("raw_shares", pa.float64(), nullable=False),
        pa.field("adjusted_close", pa.float64(), nullable=False),
        pa.field("market_value", pa.float64(), nullable=False),
        pa.field("portfolio_weight", pa.float64(), nullable=False),
    ]
)

TRADE_INDICATOR_SCHEMA = pa.schema(
    [
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("fulfillment_rate", pa.float64(), nullable=True),
        pa.field("price_advantage", pa.float64(), nullable=True),
        pa.field("positive_rate", pa.float64(), nullable=True),
        pa.field("dealt_amount", pa.float64(), nullable=True),
        pa.field("trade_value", pa.float64(), nullable=True),
        pa.field("order_count", pa.float64(), nullable=True),
    ]
)

ORDER_INDICATOR_SCHEMA = pa.schema(
    [
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("qlib_id", pa.string(), nullable=False),
        pa.field("trade_direction", pa.string(), nullable=False),
        pa.field("requested_amount_adjusted", pa.float64(), nullable=False),
        pa.field("dealt_amount_adjusted", pa.float64(), nullable=False),
        pa.field("adjustment_factor", pa.float64(), nullable=False),
        pa.field("requested_raw_shares", pa.float64(), nullable=False),
        pa.field("dealt_raw_shares", pa.float64(), nullable=False),
        pa.field("trade_price", pa.float64(), nullable=True),
        pa.field("trade_value", pa.float64(), nullable=True),
        pa.field("trade_cost", pa.float64(), nullable=True),
        pa.field("fulfillment_rate", pa.float64(), nullable=True),
    ]
)

# Locked Qlib 0.9.7 adds 0.1 raw share before flooring an adjusted BUY to
# the configured trade unit.  A cash-limited fill can therefore consume at
# most this fraction of one raw share beyond the pre-rounding cash bound.
_QLIB_RAW_SHARE_ROUNDING_EPSILON = 0.1

RISK_METRIC_SCHEMA = pa.schema(
    [
        pa.field("scope", pa.string(), nullable=False),
        pa.field("metric", pa.string(), nullable=False),
        pa.field("value", pa.float64(), nullable=True),
    ]
)

_PORTFOLIO_COLUMNS = (
    "account",
    "return",
    "total_turnover",
    "turnover",
    "total_cost",
    "cost",
    "value",
    "cash",
    "bench",
)
_TRADE_INDICATOR_COLUMNS = {
    "ffr": "fulfillment_rate",
    "pa": "price_advantage",
    "pos": "positive_rate",
    "deal_amount": "dealt_amount",
    "value": "trade_value",
    "count": "order_count",
}
_QLIB_BACKTEST = cast(Any, importlib.import_module("qlib.backtest")).backtest
_QLIB_RISK_ANALYSIS = cast(Any, importlib.import_module("qlib.contrib.evaluate")).risk_analysis
_QLIB_ORDER_GENERATOR = cast(
    Any, importlib.import_module("qlib.contrib.strategy.order_generator")
).OrderGenWOInteract


@dataclass(frozen=True)
class NormalizedBacktestOutput:
    portfolio: tuple[dict[str, object], ...]
    positions: tuple[dict[str, object], ...]
    trade_indicators: tuple[dict[str, object], ...]
    order_indicators: tuple[dict[str, object], ...]
    risk_metrics: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class BacktestArtifactBuildResult:
    reference: ArtifactRef
    manifest: BacktestArtifactManifest
    path: Path


def _finite_float(value: object, *, nullable: bool = False) -> float | None:
    if hasattr(value, "metric"):
        value = cast(Any, value).metric
    if value is None:
        if nullable:
            return None
        raise QlibResearchError(ReasonCode.QLIB_EXECUTION_FAILED, "Qlib emitted a null value")
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError) as error:
        if nullable:
            return None
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib emitted a non-numeric value"
        ) from error
    if not math.isfinite(result):
        if nullable:
            return None
        raise QlibResearchError(ReasonCode.QLIB_EXECUTION_FAILED, "Qlib emitted a non-finite value")
    return result


def _trade_date(value: object) -> date:
    return pd.Timestamp(cast(Any, value)).date()


def _normalize_portfolio(report: pd.DataFrame) -> tuple[dict[str, object], ...]:
    if tuple(report.columns) != _PORTFOLIO_COLUMNS:
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib portfolio report columns do not match the locked 0.9.7 interface",
        )
    rows: list[dict[str, object]] = []
    for index, source in report.sort_index().iterrows():
        row: dict[str, object] = {"trade_date": _trade_date(index)}
        for column in _PORTFOLIO_COLUMNS:
            row[column] = _finite_float(source[column])
        rows.append(row)
    dates = [cast(date, row["trade_date"]) for row in rows]
    if not rows or dates != sorted(set(dates)):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib portfolio rows must be nonempty and unique"
        )
    return tuple(rows)


def _factor_lookup(
    qlib_ids: tuple[str, ...], start_date: date, end_date: date
) -> dict[tuple[date, str], float]:
    frame = cast(
        pd.DataFrame,
        D.features(  # pyright: ignore[reportUnknownMemberType]
            list(qlib_ids), ["$factor"], start_date, end_date, freq="day"
        ),
    )
    factors: dict[tuple[date, str], float] = {}
    series = cast("pd.Series[float]", frame.iloc[:, 0]).sort_index()
    for index, value in series.items():
        qlib_id, timestamp = cast(tuple[str, object], index)
        normalized_qlib_id = qlib_id.upper()
        # D.features materializes the requested instrument/calendar grid.  A
        # cell may therefore be empty when an instrument has no observation
        # on that session.  Preserve only actual observations here.  Position
        # normalization resolves its factor as-of the position date, while an
        # order still requires an exact same-day observation.
        if bool(pd.isna(value)):
            continue
        factor = _finite_float(value)
        assert factor is not None
        if factor <= 0:
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED,
                "Qlib adjustment factor must be positive",
            )
        factors[(_trade_date(timestamp), normalized_qlib_id)] = factor
    return factors


FactorTimelines = Mapping[str, tuple[tuple[date, ...], tuple[float, ...]]]


def _factor_timelines(
    factors: Mapping[tuple[date, str], float],
) -> FactorTimelines:
    grouped: dict[str, list[tuple[date, float]]] = {}
    for (observed_date, qlib_id), factor in factors.items():
        grouped.setdefault(qlib_id, []).append((observed_date, factor))
    timelines: dict[str, tuple[tuple[date, ...], tuple[float, ...]]] = {}
    for qlib_id, observations in grouped.items():
        ordered = sorted(observations)
        timelines[qlib_id] = (
            tuple(item[0] for item in ordered),
            tuple(item[1] for item in ordered),
        )
    return timelines


def _factor_at_or_before(
    timelines: FactorTimelines,
    trade_date: date,
    qlib_id: str,
) -> float | None:
    timeline = timelines.get(qlib_id)
    if timeline is None:
        return None
    dates, values = timeline
    position = bisect_right(dates, trade_date) - 1
    return values[position] if position >= 0 else None


def _normalize_positions(
    history: Mapping[object, object],
    inverse_mappings: Mapping[str, str],
    factor_timelines: FactorTimelines,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    ordered_history = sorted(history.items(), key=lambda item: pd.Timestamp(cast(Any, item[0])))
    for timestamp, position_object in ordered_history:
        trade_date = _trade_date(timestamp)
        raw_position = getattr(position_object, "position", None)
        if not isinstance(raw_position, Mapping):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib position history has an unknown shape"
            )
        position = cast(Mapping[object, object], raw_position)
        qlib_ids = sorted(
            str(item)
            for item in position
            if str(item) not in {"cash", "cash_delay", "now_account_value"}
        )
        for qlib_id in qlib_ids:
            values = position[qlib_id]
            if qlib_id not in inverse_mappings or not isinstance(values, Mapping):
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED, "Qlib position cannot be mapped canonically"
                )
            position_values = cast(Mapping[object, object], values)
            amount = _finite_float(position_values.get("amount"))
            close = _finite_float(position_values.get("price"))
            weight = _finite_float(position_values.get("weight"))
            factor = _factor_at_or_before(factor_timelines, trade_date, qlib_id)
            if amount is None or close is None or weight is None or factor is None:
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED, "Qlib position fields are incomplete"
                )
            rows.append(
                {
                    "trade_date": trade_date,
                    "instrument_id": inverse_mappings[qlib_id],
                    "qlib_id": qlib_id,
                    "adjusted_amount": amount,
                    "adjustment_factor": factor,
                    "raw_shares": amount * factor,
                    "adjusted_close": close,
                    "market_value": amount * close,
                    "portfolio_weight": weight,
                }
            )
    return tuple(sorted(rows, key=lambda row: (row["trade_date"], row["instrument_id"])))


def _normalize_trade_indicators(frame: pd.DataFrame) -> tuple[dict[str, object], ...]:
    if set(frame.columns) != set(_TRADE_INDICATOR_COLUMNS):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib trade indicator columns do not match the locked 0.9.7 interface",
        )
    rows: list[dict[str, object]] = []
    for index, source in frame.sort_index().iterrows():
        row: dict[str, object] = {"trade_date": _trade_date(index)}
        for source_name, output_name in _TRADE_INDICATOR_COLUMNS.items():
            row[output_name] = _finite_float(source[source_name], nullable=True)
        rows.append(row)
    return tuple(rows)


def _metric_value(metric: object, qlib_id: str, *, nullable: bool = False) -> float | None:
    if not isinstance(metric, Mapping):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib order metric is not a mapping"
        )
    values = cast(Mapping[object, object], metric)
    return _finite_float(values.get(qlib_id), nullable=nullable)


def _order_metric_maps(order_indicator: object) -> dict[str, dict[str, object]]:
    """Adapt Qlib SingleData without its pandas-2.3-incompatible to_series method."""

    raw_metrics = getattr(order_indicator, "data", None)
    if not isinstance(raw_metrics, Mapping):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib order indicator data is unavailable"
        )
    result: dict[str, dict[str, object]] = {}
    for raw_name, metric in cast(Mapping[object, object], raw_metrics).items():
        to_dict = getattr(metric, "to_dict", None)
        if not callable(to_dict):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib SingleData cannot be normalized"
            )
        raw_values = to_dict()
        if not isinstance(raw_values, Mapping):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib SingleData did not produce a mapping"
            )
        result[str(raw_name)] = {
            str(key).upper(): value
            for key, value in cast(Mapping[object, object], raw_values).items()
        }
    return result


def _normalize_order_indicators(
    indicator_object: object,
    inverse_mappings: Mapping[str, str],
    factors: Mapping[tuple[date, str], float],
) -> tuple[dict[str, object], ...]:
    history = getattr(indicator_object, "order_indicator_his", None)
    if not isinstance(history, Mapping):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib order indicator history is unavailable",
        )
    typed_history = cast(Mapping[object, object], history)
    rows: list[dict[str, object]] = []
    ordered_history = sorted(
        typed_history.items(), key=lambda item: pd.Timestamp(cast(Any, item[0]))
    )
    for timestamp, order_indicator in ordered_history:
        trade_date = _trade_date(timestamp)
        metrics = _order_metric_maps(order_indicator)
        required = {"amount", "deal_amount", "trade_dir"}
        if not required.issubset(metrics):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib order indicator fields are incomplete"
            )
        amount_metric = metrics["amount"]
        for raw_qlib_id in sorted(amount_metric):
            if raw_qlib_id not in inverse_mappings:
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED, "Qlib order cannot be mapped canonically"
                )
            requested = _metric_value(amount_metric, raw_qlib_id)
            dealt = _metric_value(metrics["deal_amount"], raw_qlib_id)
            direction_value = _metric_value(metrics["trade_dir"], raw_qlib_id)
            factor = factors.get((trade_date, raw_qlib_id))
            if requested is None or dealt is None or direction_value is None or factor is None:
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED, "Qlib order fields are incomplete"
                )
            direction = "BUY" if direction_value > 0 else "SELL"
            rows.append(
                {
                    "trade_date": trade_date,
                    "instrument_id": inverse_mappings[raw_qlib_id],
                    "qlib_id": raw_qlib_id,
                    "trade_direction": direction,
                    "requested_amount_adjusted": requested,
                    "dealt_amount_adjusted": dealt,
                    "adjustment_factor": factor,
                    "requested_raw_shares": requested * factor,
                    "dealt_raw_shares": dealt * factor,
                    "trade_price": _metric_value(
                        metrics.get("trade_price", {}),
                        raw_qlib_id,
                        nullable=True,
                    ),
                    "trade_value": _metric_value(
                        metrics.get("trade_value", {}),
                        raw_qlib_id,
                        nullable=True,
                    ),
                    "trade_cost": _metric_value(
                        metrics.get("trade_cost", {}),
                        raw_qlib_id,
                        nullable=True,
                    ),
                    "fulfillment_rate": _metric_value(
                        metrics.get("ffr", {}),
                        raw_qlib_id,
                        nullable=True,
                    ),
                }
            )
    return tuple(sorted(rows, key=lambda row: (row["trade_date"], row["instrument_id"])))


def _normalize_risk_metrics(report: pd.DataFrame) -> tuple[dict[str, object], ...]:
    scopes = {
        "excess_before_cost": cast("pd.Series[float]", report["return"] - report["bench"]),
        "excess_after_cost": cast(
            "pd.Series[float]", report["return"] - report["cost"] - report["bench"]
        ),
    }
    rows: list[dict[str, object]] = []
    for scope, series in scopes.items():
        analysis = _QLIB_RISK_ANALYSIS(series, freq="day")
        if not isinstance(analysis, pd.DataFrame):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib risk analysis is not a DataFrame"
            )
        if tuple(analysis.columns) != ("risk",):
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib risk analysis shape changed"
            )
        for metric, value in analysis["risk"].sort_index().items():
            rows.append(
                {
                    "scope": scope,
                    "metric": str(metric),
                    "value": _finite_float(value, nullable=True),
                }
            )
    if not rows:
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib risk analysis produced no metrics"
        )
    return tuple(sorted(rows, key=lambda row: (row["scope"], row["metric"])))


def normalize_qlib_outputs(
    portfolio_by_frequency: Mapping[str, tuple[pd.DataFrame, Mapping[object, object]]],
    indicators_by_frequency: Mapping[str, tuple[pd.DataFrame, object]],
    *,
    inverse_mappings: Mapping[str, str],
    factors: Mapping[tuple[date, str], float],
) -> NormalizedBacktestOutput:
    if set(portfolio_by_frequency) != {"1day"} or set(indicators_by_frequency) != {"1day"}:
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib must emit exactly one daily result level"
        )
    report, positions = portfolio_by_frequency["1day"]
    trade_frame, indicator_object = indicators_by_frequency["1day"]
    factor_timelines = _factor_timelines(factors)
    return NormalizedBacktestOutput(
        portfolio=_normalize_portfolio(report),
        positions=_normalize_positions(positions, inverse_mappings, factor_timelines),
        trade_indicators=_normalize_trade_indicators(trade_frame),
        order_indicators=_normalize_order_indicators(indicator_object, inverse_mappings, factors),
        risk_metrics=_normalize_risk_metrics(report),
    )


def reconcile_backtest_output(
    output: NormalizedBacktestOutput,
    config: QlibBacktestConfig,
    schedules: Sequence[DecisionSchedule],
    *,
    absolute_tolerance: float = 1e-6,
    relative_tolerance: float = 1e-7,
) -> BacktestReconciliation:
    portfolio_by_date = {cast(date, row["trade_date"]): row for row in output.portfolio}
    positions_by_date: dict[date, list[dict[str, object]]] = {}
    for row in output.positions:
        positions_by_date.setdefault(cast(date, row["trade_date"]), []).append(row)

    asset_errors = [
        abs(cast(float, row["account"]) - cast(float, row["cash"]) - cast(float, row["value"]))
        for row in output.portfolio
    ]
    cash_values = [cast(float, row["cash"]) for row in output.portfolio]
    executed_order_dates: set[date] = set()
    cash_rounding_allowance_by_date: dict[date, float] = {}
    for row in output.order_indicators:
        trade_value = cast(float | None, row["trade_value"])
        if trade_value is not None and abs(trade_value) > absolute_tolerance:
            trade_date = cast(date, row["trade_date"])
            executed_order_dates.add(trade_date)
            dealt_raw_shares = abs(cast(float, row["dealt_raw_shares"]))
            requested_raw_shares = abs(cast(float, row["requested_raw_shares"]))
            if (
                row["trade_direction"] == "BUY"
                and dealt_raw_shares > absolute_tolerance
                and requested_raw_shares - dealt_raw_shares > absolute_tolerance
            ):
                raw_share_price = abs(trade_value) / dealt_raw_shares
                cash_rounding_allowance_by_date[trade_date] = max(
                    cash_rounding_allowance_by_date.get(trade_date, 0.0),
                    _QLIB_RAW_SHARE_ROUNDING_EPSILON * raw_share_price,
                )

    cash_checks: list[bool] = []
    carried_rounding_allowance = 0.0
    previous_cash: float | None = None
    for row in output.portfolio:
        trade_date = cast(date, row["trade_date"])
        cash = cast(float, row["cash"])
        account = cast(float, row["account"])
        numerical_tolerance = absolute_tolerance + relative_tolerance * max(abs(account), 1.0)
        if trade_date in executed_order_dates:
            carried_rounding_allowance = cash_rounding_allowance_by_date.get(trade_date, 0.0)
        elif previous_cash is None or cash < previous_cash - numerical_tolerance:
            carried_rounding_allowance = 0.0
        if cash >= 0.0:
            carried_rounding_allowance = 0.0
        cash_checks.append(cash >= -(numerical_tolerance + carried_rounding_allowance))
        previous_cash = cash

    position_errors: list[float] = []
    for trade_date, portfolio in portfolio_by_date.items():
        position_rows = positions_by_date.get(trade_date, [])
        position_value = sum(cast(float, row["market_value"]) for row in position_rows)
        position_errors.append(abs(position_value - cast(float, portfolio["value"])))
        account = cast(float, portfolio["account"])
        position_errors.extend(
            abs(cast(float, row["portfolio_weight"]) - cast(float, row["market_value"]) / account)
            for row in position_rows
        )

    unit_errors: list[float] = []
    position_share_values = [cast(float, row["raw_shares"]) for row in output.positions]
    buy_share_values = [
        abs(cast(float, row["dealt_raw_shares"]))
        for row in output.order_indicators
        if row["trade_direction"] == "BUY"
    ]
    for shares in buy_share_values:
        nearest_lot = round(shares / config.trade_unit_shares) * config.trade_unit_shares
        unit_errors.append(abs(shares - nearest_lot))

    delta_errors: list[float] = []
    previous_account = float(config.initial_cash_cny)
    previous_cost = 0.0
    previous_turnover = 0.0
    for row in output.portfolio:
        account = cast(float, row["account"])
        total_cost = cast(float, row["total_cost"])
        total_turnover = cast(float, row["total_turnover"])
        daily_cost = total_cost - previous_cost
        daily_turnover = total_turnover - previous_turnover
        delta_errors.extend(
            (
                abs(cast(float, row["cost"]) - daily_cost / previous_account),
                abs(cast(float, row["turnover"]) - daily_turnover / previous_account),
                abs(
                    cast(float, row["return"])
                    - (account - previous_account + daily_cost) / previous_account
                ),
            )
        )
        previous_account = account
        previous_cost = total_cost
        previous_turnover = total_turnover

    expected_schedule_hash = config.decision_schedule_hash
    schedule_hash = translate_backtest_config_schedule_hash(schedules)
    schedule_passed = (
        schedule_hash == expected_schedule_hash
        and tuple(schedule.signal_time.date() for schedule in schedules) == config.signal_dates
        and tuple(schedule.execution_time.date() for schedule in schedules)
        == config.execution_dates
    )
    checks_pass = (
        all(error <= absolute_tolerance + relative_tolerance for error in asset_errors),
        all(cash_checks),
        all(error <= absolute_tolerance + relative_tolerance for error in position_errors),
        all(error <= absolute_tolerance + relative_tolerance for error in delta_errors),
        schedule_passed,
        all(value >= -absolute_tolerance for value in position_share_values)
        and all(error <= absolute_tolerance + relative_tolerance for error in unit_errors)
        and {
            cast(str, row["qlib_id"]) for row in (*output.positions, *output.order_indicators)
        }.issubset(config.exchange_codes),
    )
    if not all(checks_pass):
        failed = [
            name
            for name, passed in zip(
                (
                    "asset_identity",
                    "cash_nonnegative",
                    "position_value_and_weight",
                    "return_cost_turnover_deltas",
                    "temporal_schedule",
                    "trade_unit_and_no_short",
                ),
                checks_pass,
                strict=True,
            )
            if not passed
        ]
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            f"Qlib result failed arithmetic reconciliation: {', '.join(failed)}",
        )
    checks = (
        BacktestReconciliationCheck(
            name="asset_identity",
            checked_rows=len(asset_errors),
            max_abs_error=max(asset_errors, default=0.0),
            detail="Qlib account equals cash plus reported security value",
        ),
        BacktestReconciliationCheck(
            name="cash_nonnegative",
            checked_rows=len(cash_values),
            max_abs_error=max(0.0, -min(cash_values)),
            detail=(
                "Qlib available cash never crosses the per-row absolute plus account-scaled "
                "relative numerical tolerance, with Qlib's 0.1-raw-share rounding epsilon "
                "allowed only after a partially filled BUY and across no-trade carry days"
            ),
        ),
        BacktestReconciliationCheck(
            name="position_value_and_weight",
            checked_rows=len(position_errors),
            max_abs_error=max(position_errors, default=0.0),
            detail="normalized Qlib positions sum to report value and weights",
        ),
        BacktestReconciliationCheck(
            name="return_cost_turnover_deltas",
            checked_rows=len(delta_errors),
            max_abs_error=max(delta_errors, default=0.0),
            detail="Qlib return, cost, and turnover rates reconcile to cumulative values",
        ),
        BacktestReconciliationCheck(
            name="temporal_schedule",
            checked_rows=len(schedules),
            max_abs_error=None,
            detail="signal and execution dates match the hash-bound PIT schedules",
        ),
        BacktestReconciliationCheck(
            name="trade_unit_and_no_short",
            checked_rows=len(output.positions) + len(output.order_indicators),
            max_abs_error=max(unit_errors, default=0.0),
            detail=(
                "factor-adjusted BUY executions are 100-share lots, holdings are nonnegative, "
                "and all holdings/orders belong to the hash-bound exchange code set; Qlib "
                "sell-all execution may liquidate corporate-action odd lots"
            ),
        ),
    )
    return BacktestReconciliation(
        backtest_config_hash=config.content_hash,
        decision_schedule_hash=config.decision_schedule_hash,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        checks=checks,
    )


def translate_backtest_config_schedule_hash(schedules: Sequence[DecisionSchedule]) -> str:
    from quantos.contracts.base import sha256_bytes

    return sha256_bytes(
        canonical_json_bytes([schedule.model_dump(mode="python") for schedule in schedules])
    )


def _read_signal_inputs(
    signal_path: Path,
) -> tuple[ResolvedExperimentSpec, PITArtifactEvidence, tuple[SignalRow, ...]]:
    try:
        resolved = ResolvedExperimentSpec.model_validate_json(
            (signal_path / "resolved-experiment.json").read_bytes()
        )
        evidence = load_pit_artifact_evidence(signal_path / "pit-evidence.json")
        rows = tuple(
            SignalRow.model_validate(row)
            for row in pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                signal_path / "signals.parquet"
            ).to_pylist()
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal inputs cannot be loaded for backtest"
        ) from error
    return resolved, evidence, rows


def _calendar_dates(view_path: Path) -> tuple[date, ...]:
    try:
        calendar_path = view_path / "calendars" / "day.txt"
        values = tuple(
            date.fromisoformat(line.strip())
            for line in calendar_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib daily calendar cannot be read"
        ) from error
    if not values or values != tuple(sorted(set(values))):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib daily calendar is not sorted and unique"
        )
    return values


def _validate_schedules(schedules: tuple[DecisionSchedule, ...], view_path: Path) -> None:
    calendar = _calendar_dates(view_path)
    index_by_date = {value: index for index, value in enumerate(calendar)}
    for schedule in schedules:
        signal_date = schedule.signal_time.date()
        execution_date = schedule.execution_time.date()
        signal_index = index_by_date.get(signal_date)
        if signal_index is None or signal_index + 1 >= len(calendar):
            raise QlibResearchError(
                ReasonCode.OOS_POLICY_VIOLATION, "signal has no following Qlib trading session"
            )
        if calendar[signal_index + 1] != execution_date:
            raise QlibResearchError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "execution date must be the next Qlib trading session",
            )
        signal_week = signal_date.isocalendar()[:2]
        if calendar[signal_index + 1].isocalendar()[:2] == signal_week:
            raise QlibResearchError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "weekly signal must use the final trading session of its ISO week",
            )


def _load_view_mappings(view_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    try:
        spec = QlibViewSpec.model_validate_json((view_path / "view-spec.json").read_bytes())
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view mappings cannot be read"
        ) from error
    forward = {item.instrument_id: item.qlib_id for item in spec.mappings}
    inverse = {item.qlib_id: item.instrument_id for item in spec.mappings}
    return forward, inverse


def _signal_series(rows: tuple[SignalRow, ...], mappings: Mapping[str, str]) -> pd.Series:
    values: list[float] = []
    index: list[tuple[pd.Timestamp, str]] = []
    for row in rows:
        qlib_id = mappings.get(row.instrument_id)
        if qlib_id is None:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE, "signal instrument is absent from Qlib mappings"
            )
        index.append((pd.Timestamp(row.signal_time.date()), qlib_id))
        values.append(cast(float, row.score) if row.tradable and row.score_valid else math.nan)
    result = pd.Series(
        values,
        index=pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"]),
        name="score",
        dtype=float,
    )
    return result.sort_index()


def _artifact_files(root: Path) -> tuple[BacktestArtifactFile, ...]:
    return tuple(
        BacktestArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "manifest.json"
    )


def _write_table(rows: Sequence[dict[str, object]], schema: pa.Schema, path: Path) -> None:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    pq.write_table(  # pyright: ignore[reportUnknownMemberType]
        table,
        path,
        compression="zstd",
        data_page_version="1.0",
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )


def verify_backtest_artifact(path: Path) -> BacktestArtifactManifest:
    try:
        tree_files = regular_tree_files(path)
        manifest = BacktestArtifactManifest.model_validate_json(
            (path / "manifest.json").read_bytes()
        )
    except (OSError, ValueError, ArtifactIntegrityError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest manifest is invalid"
        ) from error
    if path.name != f"sha256-{manifest.result_hash}":
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest directory does not match result hash"
        )
    expected_paths = {item.logical_path for item in manifest.files}
    actual_paths = {
        item.relative_to(path).as_posix() for item in tree_files if item.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest file set does not match manifest"
        )
    for item in manifest.files:
        try:
            verify_file(path / item.logical_path, item.sha256)
        except (OSError, ArtifactIntegrityError) as error:
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                f"backtest file failed verification: {item.logical_path}",
            ) from error
    try:
        config = QlibBacktestConfig.model_validate_json(
            (path / "backtest-config.json").read_bytes()
        )
        reconciliation = BacktestReconciliation.model_validate_json(
            (path / "reconciliation.json").read_bytes()
        )
        tables = {
            "portfolio": pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                path / "portfolio.parquet"
            ),
            "positions": pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                path / "positions.parquet"
            ),
            "trade_indicators": pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                path / "trade-indicators.parquet"
            ),
            "order_indicators": pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                path / "order-indicators.parquet"
            ),
            "risk_metrics": pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                path / "risk-metrics.parquet"
            ),
        }
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest payload is invalid"
        ) from error
    expected_schemas = {
        "portfolio": PORTFOLIO_SCHEMA,
        "positions": POSITION_SCHEMA,
        "trade_indicators": TRADE_INDICATOR_SCHEMA,
        "order_indicators": ORDER_INDICATOR_SCHEMA,
        "risk_metrics": RISK_METRIC_SCHEMA,
    }
    if any(tables[name].schema != schema for name, schema in expected_schemas.items()):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest table schema does not match v1"
        )
    counts = {
        "portfolio": manifest.portfolio_rows,
        "positions": manifest.position_rows,
        "trade_indicators": manifest.trade_indicator_rows,
        "order_indicators": manifest.order_indicator_rows,
        "risk_metrics": manifest.risk_metric_rows,
    }
    portfolio_dates = cast(list[date], tables["portfolio"].column("trade_date").to_pylist())
    bindings_match = (
        all(tables[name].num_rows == count for name, count in counts.items())
        and bool(portfolio_dates)
        and portfolio_dates == sorted(set(portfolio_dates))
        and portfolio_dates[0] == manifest.start_date == config.start_date
        and portfolio_dates[-1] == manifest.end_date == config.end_date
        and config.content_hash == manifest.backtest_config_hash
        and reconciliation.content_hash == manifest.reconciliation_hash
        and reconciliation.backtest_config_hash == config.content_hash
        and reconciliation.decision_schedule_hash == config.decision_schedule_hash
        and manifest.signal_artifact_hash == config.signal_artifact_hash
        and manifest.resolved_experiment_hash == config.resolved_experiment_hash
        and manifest.snapshot_hash == config.snapshot_hash
        and manifest.qlib_view_hash == config.qlib_view_hash
        and manifest.qlib_version == config.qlib_version
        and manifest.cost_policy_hash == config.cost_policy_hash
        and manifest.backtest_policy_hash == config.backtest_policy_hash
        and manifest.known_limitations == config.known_limitations
    )
    if not bindings_match:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "backtest manifest bindings are inconsistent"
        )
    return manifest


class QlibBacktestService:
    """Thin Qlib adapter; it does not match orders or account for a portfolio."""

    def run(
        self,
        resolved: ResolvedExperimentSpec,
        signal_path: Path,
        view_path: Path,
        cost_policy: CostPolicy,
        backtest_policy: BacktestPolicy,
        output_root: Path,
        *,
        workspace: Path | None = None,
    ) -> BacktestArtifactBuildResult:
        try:
            verify_code_provenance(
                workspace or Path.cwd(),
                expected_commit_hash=resolved.code_commit_hash,
                expected_lockfile_hash=resolved.lockfile_hash,
            )
        except ProvenanceError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        signal_manifest = verify_signal_artifact(signal_path)
        embedded_resolved, evidence, signal_rows = _read_signal_inputs(signal_path)
        if (
            embedded_resolved != resolved
            or signal_manifest.resolved_experiment_hash != resolved.content_hash
        ):
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "signal artifact does not contain the requested resolved experiment",
            )
        try:
            view = verify_qlib_view(view_path)
        except QlibViewBuildError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        if (
            view.view_hash != resolved.qlib_view_hash
            or view.source_snapshot_hash != resolved.snapshot_hash
            or view.qlib_version != resolved.qlib_version
        ):
            raise QlibResearchError(
                ReasonCode.SNAPSHOT_HASH_MISMATCH,
                "resolved experiment does not match the verified Qlib view",
            )
        schedules = tuple(bundle.schedule for bundle in evidence.bundles)
        _validate_schedules(schedules, view_path)
        mappings, inverse_mappings = _load_view_mappings(view_path)
        try:
            qlib_ids = tuple(sorted({mappings[row.instrument_id] for row in signal_rows}))
        except KeyError:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE,
                "signal instrument is absent from Qlib mappings",
            ) from None
        config = translate_backtest_config(
            resolved,
            signal_artifact_hash=signal_manifest.artifact_hash,
            cost_policy=cost_policy,
            backtest_policy=backtest_policy,
            schedules=schedules,
            exchange_codes=qlib_ids,
        )
        signal = _signal_series(signal_rows, mappings)
        qlib.init(  # pyright: ignore[reportUnknownMemberType]
            provider_uri=str(view_path), region=REG_CN
        )
        strategy = {
            "class": "FullReplacementTopKStrategy",
            "module_path": "quantos.backtest.strategy",
            "kwargs": {
                "signal": signal,
                "topk": config.top_k,
                "max_weight": config.max_weight,
                "risk_degree": config.risk_degree,
                "order_generator_cls_or_obj": _QLIB_ORDER_GENERATOR,
            },
        }
        executor = {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {
                "time_per_step": config.frequency,
                "generate_portfolio_metrics": config.generate_portfolio_metrics,
                "trade_type": config.trade_type,
                "settle_type": config.settlement,
            },
        }
        exchange_kwargs = {
            "freq": config.frequency,
            "codes": list(config.exchange_codes),
            "start_time": config.exchange_start_date.isoformat(),
            "end_time": config.end_date.isoformat(),
            "deal_price": config.deal_price,
            "limit_threshold": config.limit_threshold_fields,
            "volume_threshold": {"all": config.volume_threshold},
            "open_cost": config.open_cost_rate,
            "close_cost": config.close_cost_rate,
            "min_cost": config.minimum_cost_cny,
            "trade_unit": config.trade_unit_shares,
        }
        try:
            raw_result = _QLIB_BACKTEST(
                start_time=config.start_date.isoformat(),
                end_time=config.end_date.isoformat(),
                strategy=strategy,
                executor=executor,
                benchmark=config.benchmark,
                account=config.initial_cash_cny,
                exchange_kwargs=exchange_kwargs,
                pos_type=config.position_type,
            )
            raw_portfolio, raw_indicators = cast(tuple[object, object], raw_result)
            factors = _factor_lookup(qlib_ids, config.start_date, config.end_date)
            normalized = normalize_qlib_outputs(
                cast(Any, raw_portfolio),
                cast(Any, raw_indicators),
                inverse_mappings=inverse_mappings,
                factors=factors,
            )
        except QlibResearchError:
            raise
        except Exception:
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED, "Qlib reference backtest execution failed"
            ) from None
        reconciliation = reconcile_backtest_output(normalized, config, schedules)

        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".backtest-work-", dir=output_root) as temporary:
            staging = Path(temporary) / "backtest"
            staging.mkdir()
            atomic_write_bytes(staging / "backtest-config.json", config.canonical_bytes())
            _write_table(
                normalized.order_indicators,
                ORDER_INDICATOR_SCHEMA,
                staging / "order-indicators.parquet",
            )
            _write_table(normalized.portfolio, PORTFOLIO_SCHEMA, staging / "portfolio.parquet")
            _write_table(normalized.positions, POSITION_SCHEMA, staging / "positions.parquet")
            atomic_write_bytes(staging / "reconciliation.json", reconciliation.canonical_bytes())
            _write_table(
                normalized.risk_metrics,
                RISK_METRIC_SCHEMA,
                staging / "risk-metrics.parquet",
            )
            _write_table(
                normalized.trade_indicators,
                TRADE_INDICATOR_SCHEMA,
                staging / "trade-indicators.parquet",
            )
            files = _artifact_files(staging)
            manifest = BacktestArtifactManifest.create(
                resolved_experiment_hash=resolved.content_hash,
                signal_artifact_hash=signal_manifest.artifact_hash,
                snapshot_hash=resolved.snapshot_hash,
                qlib_view_hash=resolved.qlib_view_hash,
                qlib_version=resolved.qlib_version,
                cost_policy_hash=cost_policy.content_hash,
                backtest_policy_hash=backtest_policy.content_hash,
                backtest_config_hash=config.content_hash,
                reconciliation_hash=reconciliation.content_hash,
                start_date=cast(date, normalized.portfolio[0]["trade_date"]),
                end_date=cast(date, normalized.portfolio[-1]["trade_date"]),
                portfolio_rows=len(normalized.portfolio),
                position_rows=len(normalized.positions),
                trade_indicator_rows=len(normalized.trade_indicators),
                order_indicator_rows=len(normalized.order_indicators),
                risk_metric_rows=len(normalized.risk_metrics),
                files=files,
                known_limitations=config.known_limitations,
                created_at=datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = output_root / f"sha256-{manifest.result_hash}"
            if destination.exists():
                published = verify_backtest_artifact(destination)
            else:
                publish_directory(staging, destination)
                published = verify_backtest_artifact(destination)

        size_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
        return BacktestArtifactBuildResult(
            reference=ArtifactRef(
                kind="backtest_result",
                sha256=published.result_hash,
                size_bytes=size_bytes,
                media_type="application/vnd.quantos.backtest-directory",
                logical_path=f"research/backtests/{destination.name}",
            ),
            manifest=published,
            path=destination,
        )
