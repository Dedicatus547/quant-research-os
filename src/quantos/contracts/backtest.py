"""Explicit configuration for Qlib's reference backtest engine."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import ClassVar, Literal, Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN


class QlibBacktestConfig(CanonicalContract):
    schema_version: Literal["qlib-backtest-config/v1"] = "qlib-backtest-config/v1"
    resolved_experiment_hash: str = Field(pattern=SHA256_PATTERN)
    signal_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    start_date: date
    end_date: date
    exchange_start_date: date
    exchange_codes: tuple[str, ...]
    signal_dates: tuple[date, ...]
    execution_dates: tuple[date, ...]
    decision_schedule_hash: str = Field(pattern=SHA256_PATTERN)
    benchmark: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    initial_cash_cny: PositiveFloat
    frequency: Literal["day"] = "day"
    executor: Literal["Qlib SimulatorExecutor"] = "Qlib SimulatorExecutor"
    strategy_adapter: Literal["FullReplacementTopKStrategy"] = "FullReplacementTopKStrategy"
    order_generator: Literal["Qlib OrderGenWOInteract"] = "Qlib OrderGenWOInteract"
    position_type: Literal["Position"] = "Position"
    top_k: PositiveInt
    max_weight: float = Field(gt=0, le=1)
    risk_degree: Literal[1] = 1
    trade_type: Literal["serial"] = "serial"
    settlement: Literal["None"] = "None"
    generate_portfolio_metrics: Literal[True] = True
    deal_price: Literal["$open"] = "$open"
    open_cost_rate: float = Field(ge=0, lt=1)
    close_cost_rate: float = Field(ge=0, lt=1)
    minimum_cost_cny: float = Field(ge=0)
    trade_unit_shares: Literal[100] = 100
    limit_threshold_fields: tuple[Literal["$limit_buy+$is_st"], Literal["$limit_sell+$is_st"]] = (
        "$limit_buy+$is_st",
        "$limit_sell+$is_st",
    )
    volume_threshold: tuple[Literal["current"], str]
    no_short: Literal[True] = True
    leverage_allowed: Literal[False] = False
    known_limitations: tuple[
        Literal["QLIB_TARGET_WEIGHT_PRECHECK_BLOCKS_BOTH_DIRECTIONS_IF_EITHER_LIMIT_SIDE_IS_SET"],
        Literal["QLIB_HAS_NO_STABLE_PER_ORDER_REJECTION_REASON_CODE"],
    ] = (
        "QLIB_TARGET_WEIGHT_PRECHECK_BLOCKS_BOTH_DIRECTIONS_IF_EITHER_LIMIT_SIDE_IS_SET",
        "QLIB_HAS_NO_STABLE_PER_ORDER_REJECTION_REASON_CODE",
    )

    @model_validator(mode="after")
    def dates_and_volume_expression_are_valid(self) -> QlibBacktestConfig:
        if self.start_date > self.end_date:
            raise ValueError("backtest start_date cannot be after end_date")
        if (
            not self.signal_dates
            or len(self.signal_dates) != len(self.execution_dates)
            or self.signal_dates != tuple(sorted(set(self.signal_dates)))
            or self.execution_dates != tuple(sorted(set(self.execution_dates)))
        ):
            raise ValueError("signal and execution dates must be nonempty, paired, sorted, unique")
        if any(
            signal >= execution
            for signal, execution in zip(self.signal_dates, self.execution_dates, strict=True)
        ):
            raise ValueError("every signal date must precede its execution date")
        if self.start_date != self.execution_dates[0] or self.end_date != self.execution_dates[-1]:
            raise ValueError("backtest range must be derived from the exact execution schedule")
        if self.exchange_start_date != self.signal_dates[0]:
            raise ValueError("exchange history must start on the first signal date")
        if (
            not self.exchange_codes
            or self.exchange_codes != tuple(sorted(set(self.exchange_codes)))
            or any(re.fullmatch(r"(SH|SZ)[0-9]{6}", code) is None for code in self.exchange_codes)
        ):
            raise ValueError("exchange codes must be nonempty, sorted, unique Qlib identifiers")
        if not self.volume_threshold[1].startswith("$volume*"):
            raise ValueError("volume threshold must be a locked Qlib volume expression")
        return self


ReconciliationName = Literal[
    "asset_identity",
    "cash_nonnegative",
    "position_value_and_weight",
    "return_cost_turnover_deltas",
    "temporal_schedule",
    "trade_unit_and_no_short",
]


class BacktestReconciliationCheck(CanonicalContract):
    schema_version: Literal["backtest-reconciliation-check/v1"] = "backtest-reconciliation-check/v1"
    name: ReconciliationName
    passed: Literal[True] = True
    checked_rows: NonNegativeInt
    max_abs_error: float | None = Field(default=None, ge=0)
    detail: str = Field(min_length=1)


class BacktestReconciliation(CanonicalContract):
    schema_version: Literal["backtest-reconciliation/v1"] = "backtest-reconciliation/v1"
    backtest_config_hash: str = Field(pattern=SHA256_PATTERN)
    decision_schedule_hash: str = Field(pattern=SHA256_PATTERN)
    absolute_tolerance: float = Field(gt=0)
    relative_tolerance: float = Field(gt=0)
    checks: tuple[BacktestReconciliationCheck, ...]

    @field_validator("checks")
    @classmethod
    def checks_are_complete_and_sorted(
        cls, value: tuple[BacktestReconciliationCheck, ...]
    ) -> tuple[BacktestReconciliationCheck, ...]:
        expected = [
            "asset_identity",
            "cash_nonnegative",
            "position_value_and_weight",
            "return_cost_turnover_deltas",
            "temporal_schedule",
            "trade_unit_and_no_short",
        ]
        if [item.name for item in value] != expected:
            raise ValueError("backtest reconciliation checks must match the locked v1 set")
        return value


class BacktestArtifactFile(CanonicalContract):
    schema_version: Literal["backtest-artifact-file/v1"] = "backtest-artifact-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def logical_path_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("logical_path must be a safe relative POSIX path")
        return path.as_posix()


class BacktestInputHash(CanonicalContract):
    schema_version: Literal["backtest-input-hash/v1"] = "backtest-input-hash/v1"
    kind: Literal[
        "backtest_config",
        "backtest_policy",
        "cost_policy",
        "qlib_view_cache",
        "reconciliation",
        "resolved_experiment",
        "signal_artifact",
        "snapshot",
    ]
    sha256: str = Field(pattern=SHA256_PATTERN)


class BacktestArtifactManifest(CanonicalContract):
    """Immutable normalized evidence from Qlib's reference backtest."""

    schema_version: Literal["backtest-artifact-manifest/v1"] = "backtest-artifact-manifest/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"result_hash", "created_at"})

    result_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str = Field(pattern=SHA256_PATTERN)
    signal_artifact_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_config_hash: str = Field(pattern=SHA256_PATTERN)
    reconciliation_hash: str = Field(pattern=SHA256_PATTERN)
    start_date: date
    end_date: date
    portfolio_rows: PositiveInt
    position_rows: NonNegativeInt
    trade_indicator_rows: PositiveInt
    order_indicator_rows: NonNegativeInt
    risk_metric_rows: PositiveInt
    input_hashes: tuple[BacktestInputHash, ...]
    files: tuple[BacktestArtifactFile, ...]
    known_limitations: tuple[
        Literal["QLIB_TARGET_WEIGHT_PRECHECK_BLOCKS_BOTH_DIRECTIONS_IF_EITHER_LIMIT_SIDE_IS_SET"],
        Literal["QLIB_HAS_NO_STABLE_PER_ORDER_REJECTION_REASON_CODE"],
    ]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_complete_and_sorted(
        cls, value: tuple[BacktestInputHash, ...]
    ) -> tuple[BacktestInputHash, ...]:
        expected = [
            "backtest_config",
            "backtest_policy",
            "cost_policy",
            "qlib_view_cache",
            "reconciliation",
            "resolved_experiment",
            "signal_artifact",
            "snapshot",
        ]
        if [item.kind for item in value] != expected:
            raise ValueError("backtest input hashes must match the locked v1 set")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact_and_sorted(
        cls, value: tuple[BacktestArtifactFile, ...]
    ) -> tuple[BacktestArtifactFile, ...]:
        expected = [
            "backtest-config.json",
            "order-indicators.parquet",
            "portfolio.parquet",
            "positions.parquet",
            "reconciliation.json",
            "risk-metrics.parquet",
            "trade-indicators.parquet",
        ]
        if [item.logical_path for item in value] != expected:
            raise ValueError("backtest artifact file set must match the locked v1 layout")
        return value

    @model_validator(mode="after")
    def manifest_is_consistent(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("backtest result start_date cannot be after end_date")
        expected_inputs = {
            "backtest_config": self.backtest_config_hash,
            "backtest_policy": self.backtest_policy_hash,
            "cost_policy": self.cost_policy_hash,
            "qlib_view_cache": self.qlib_view_hash,
            "reconciliation": self.reconciliation_hash,
            "resolved_experiment": self.resolved_experiment_hash,
            "signal_artifact": self.signal_artifact_hash,
            "snapshot": self.snapshot_hash,
        }
        if {item.kind: item.sha256 for item in self.input_hashes} != expected_inputs:
            raise ValueError("backtest input hashes do not match manifest bindings")
        if self.result_hash != self.content_hash:
            raise ValueError("result_hash does not match backtest manifest content")
        return self

    @classmethod
    def create(
        cls,
        *,
        resolved_experiment_hash: str,
        signal_artifact_hash: str,
        snapshot_hash: str,
        qlib_view_hash: str,
        qlib_version: str,
        cost_policy_hash: str,
        backtest_policy_hash: str,
        backtest_config_hash: str,
        reconciliation_hash: str,
        start_date: date,
        end_date: date,
        portfolio_rows: int,
        position_rows: int,
        trade_indicator_rows: int,
        order_indicator_rows: int,
        risk_metric_rows: int,
        files: tuple[BacktestArtifactFile, ...],
        known_limitations: tuple[
            Literal[
                "QLIB_TARGET_WEIGHT_PRECHECK_BLOCKS_BOTH_DIRECTIONS_IF_EITHER_LIMIT_SIDE_IS_SET"
            ],
            Literal["QLIB_HAS_NO_STABLE_PER_ORDER_REJECTION_REASON_CODE"],
        ],
        created_at: datetime,
    ) -> Self:
        input_hashes = tuple(
            BacktestInputHash(kind=kind, sha256=digest)  # type: ignore[arg-type]
            for kind, digest in (
                ("backtest_config", backtest_config_hash),
                ("backtest_policy", backtest_policy_hash),
                ("cost_policy", cost_policy_hash),
                ("qlib_view_cache", qlib_view_hash),
                ("reconciliation", reconciliation_hash),
                ("resolved_experiment", resolved_experiment_hash),
                ("signal_artifact", signal_artifact_hash),
                ("snapshot", snapshot_hash),
            )
        )
        payload = {
            "schema_version": "backtest-artifact-manifest/v1",
            "resolved_experiment_hash": resolved_experiment_hash,
            "signal_artifact_hash": signal_artifact_hash,
            "snapshot_hash": snapshot_hash,
            "qlib_view_hash": qlib_view_hash,
            "qlib_version": qlib_version,
            "cost_policy_hash": cost_policy_hash,
            "backtest_policy_hash": backtest_policy_hash,
            "backtest_config_hash": backtest_config_hash,
            "reconciliation_hash": reconciliation_hash,
            "start_date": start_date,
            "end_date": end_date,
            "portfolio_rows": portfolio_rows,
            "position_rows": position_rows,
            "trade_indicator_rows": trade_indicator_rows,
            "order_indicator_rows": order_indicator_rows,
            "risk_metric_rows": risk_metric_rows,
            "input_hashes": input_hashes,
            "files": files,
            "known_limitations": known_limitations,
        }
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(
            result_hash=digest,
            resolved_experiment_hash=resolved_experiment_hash,
            signal_artifact_hash=signal_artifact_hash,
            snapshot_hash=snapshot_hash,
            qlib_view_hash=qlib_view_hash,
            qlib_version=qlib_version,
            cost_policy_hash=cost_policy_hash,
            backtest_policy_hash=backtest_policy_hash,
            backtest_config_hash=backtest_config_hash,
            reconciliation_hash=reconciliation_hash,
            start_date=start_date,
            end_date=end_date,
            portfolio_rows=portfolio_rows,
            position_rows=position_rows,
            trade_indicator_rows=trade_indicator_rows,
            order_indicator_rows=order_indicator_rows,
            risk_metric_rows=risk_metric_rows,
            input_hashes=input_hashes,
            files=files,
            known_limitations=known_limitations,
            created_at=created_at.astimezone(UTC),
        )
