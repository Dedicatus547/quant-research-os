"""Authoring and fully resolved research specification contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from itertools import pairwise
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.refs import SHA256_PATTERN


class SelectionMethod(StrEnum):
    TOP_K = "top_k"


class WeightingMethod(StrEnum):
    EQUAL = "equal"


class RebalanceFrequency(StrEnum):
    WEEKLY = "weekly"


class ExecutionMode(StrEnum):
    NEXT_OPEN = "next_open"


class ExpressionAuthoringSpec(CanonicalContract):
    """Small human-facing shorthand; never accepted by a canonical run."""

    schema_version: Literal["expression-authoring/v1"] = "expression-authoring/v1"
    expression_id: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    operator: Literal["return"]
    field: Literal["adjusted_close"]
    window: PositiveInt


class StrategyAuthoringSpec(CanonicalContract):
    schema_version: Literal["strategy-authoring/v1"] = "strategy-authoring/v1"
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    selection_method: Literal[SelectionMethod.TOP_K] = SelectionMethod.TOP_K
    top_k: PositiveInt
    weighting_method: Literal[WeightingMethod.EQUAL] = WeightingMethod.EQUAL
    rebalance_frequency: Literal[RebalanceFrequency.WEEKLY] = RebalanceFrequency.WEEKLY
    execution_mode: Literal[ExecutionMode.NEXT_OPEN] = ExecutionMode.NEXT_OPEN
    input_lag_trading_days: NonNegativeInt = 0
    execution_lag_trading_sessions: Literal[1] = 1
    exclude_st: Literal[True] = True
    exclude_suspended: Literal[True] = True
    respect_price_limits: Literal[True] = True
    trade_unit_shares: Literal[100] = 100
    max_weight: float = Field(default=0.03, gt=0, le=1)


class ExperimentAuthoringSpec(CanonicalContract):
    schema_version: Literal["experiment-authoring/v1"] = "experiment-authoring/v1"
    experiment_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    evaluation_start: date
    evaluation_end: date
    expression: ExpressionAuthoringSpec
    strategy: StrategyAuthoringSpec

    @model_validator(mode="after")
    def evaluation_range_is_ordered(self) -> Self:
        if self.evaluation_start > self.evaluation_end:
            raise ValueError("evaluation_start cannot be after evaluation_end")
        return self


class ResolvedStrategySpec(CanonicalContract):
    schema_version: Literal["resolved-strategy/v1"] = "resolved-strategy/v1"
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    selection_method: Literal[SelectionMethod.TOP_K] = SelectionMethod.TOP_K
    top_k: PositiveInt
    weighting_method: Literal[WeightingMethod.EQUAL] = WeightingMethod.EQUAL
    rebalance_frequency: Literal[RebalanceFrequency.WEEKLY] = RebalanceFrequency.WEEKLY
    execution_mode: Literal[ExecutionMode.NEXT_OPEN] = ExecutionMode.NEXT_OPEN
    input_lag_trading_days: NonNegativeInt
    execution_lag_trading_sessions: Literal[1]
    exclude_st: Literal[True] = True
    exclude_suspended: Literal[True] = True
    respect_price_limits: Literal[True] = True
    trade_unit_shares: Literal[100] = 100
    max_weight: float = Field(gt=0, le=1)


class ResolvedExperimentSpec(CanonicalContract):
    """Canonical input: every mutable/logical dependency has been replaced by a hash."""

    schema_version: Literal["resolved-experiment/v1"] = "resolved-experiment/v1"
    experiment_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    authoring_spec_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_start: date
    evaluation_end: date
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    qlib_view_spec_hash: str = Field(pattern=SHA256_PATTERN)
    pit_audit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    expression: SafeQlibExpressionSpec
    strategy: ResolvedStrategySpec
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    cost_policy_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def resolved_spec_is_consistent(self) -> Self:
        if self.evaluation_start > self.evaluation_end:
            raise ValueError("evaluation_start cannot be after evaluation_end")
        if self.expression.input_lag_trading_days != self.strategy.input_lag_trading_days:
            raise ValueError("expression and strategy input lag must match")
        return self


class ResearchSegment(CanonicalContract):
    schema_version: Literal["research-segment/v1"] = "research-segment/v1"
    start: date
    end: date

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("research segment start cannot be after end")
        return self


class ResearchPolicy(CanonicalContract):
    schema_version: Literal["research-policy/v1"] = "research-policy/v1"
    policy_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    train: ResearchSegment
    validation: ResearchSegment
    test: ResearchSegment
    purge_trading_days: NonNegativeInt
    label_horizon_trading_sessions: PositiveInt
    model: Literal["LGBModel"] = "LGBModel"
    random_seed: NonNegativeInt
    num_threads: PositiveInt
    num_boost_round: PositiveInt
    early_stopping_rounds: PositiveInt

    @model_validator(mode="after")
    def segments_are_strictly_separated(self) -> Self:
        if not (self.train.end < self.validation.start and self.validation.end < self.test.start):
            raise ValueError("research segments must be ordered and non-overlapping")
        if self.purge_trading_days < self.label_horizon_trading_sessions:
            raise ValueError("purge must cover the complete forward-label horizon")
        return self


class HardGateId(StrEnum):
    SCHEMA = "schema"
    SNAPSHOT_INTEGRITY = "snapshot_integrity"
    DATA_QUALITY = "data_quality"
    PIT = "pit"
    REPRODUCIBILITY = "reproducibility"
    ARTIFACT_INTEGRITY = "artifact_integrity"


class SoftMetric(StrEnum):
    OOS_SHARPE = "oos_sharpe"
    RANK_IC = "rank_ic"
    ICIR = "icir"
    MAX_DRAWDOWN = "max_drawdown"
    ANNUALIZED_TURNOVER = "annualized_turnover"
    ANNUALIZED_RETURN = "annualized_return"
    COST_SENSITIVITY = "cost_sensitivity"
    PARAMETER_STABILITY = "parameter_stability"
    SUBPERIOD_STABILITY = "subperiod_stability"


class ThresholdComparison(StrEnum):
    MIN = "min"
    MAX = "max"


class SoftGateThreshold(CanonicalContract):
    schema_version: Literal["soft-gate-threshold/v1"] = "soft-gate-threshold/v1"
    metric: SoftMetric
    comparison: ThresholdComparison
    threshold: float


class ValidationSubperiod(CanonicalContract):
    schema_version: Literal["validation-subperiod/v1"] = "validation-subperiod/v1"
    period_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    start: date
    end: date

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("validation subperiod start cannot be after end")
        return self


class ValidationPolicy(CanonicalContract):
    schema_version: Literal["validation-policy/v1"] = "validation-policy/v1"
    policy_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    hard_gates: tuple[HardGateId, ...]
    soft_gates: tuple[SoftGateThreshold, ...] = ()
    annualization_factor: PositiveInt = 250
    minimum_oos_observations: PositiveInt = 20
    cost_stress_multipliers: tuple[float, ...] = (1.0, 1.5, 2.0)
    parameter_windows: tuple[PositiveInt, ...] = (15, 20, 25)
    parameter_top_k: tuple[PositiveInt, ...] = (40, 50, 60)
    subperiods: tuple[ValidationSubperiod, ...] = (
        ValidationSubperiod(period_id="2015-2017", start=date(2015, 1, 1), end=date(2017, 12, 31)),
        ValidationSubperiod(period_id="2018-2020", start=date(2018, 1, 1), end=date(2020, 12, 31)),
        ValidationSubperiod(period_id="2021-2023", start=date(2021, 1, 1), end=date(2023, 12, 31)),
        ValidationSubperiod(period_id="2024-2025", start=date(2024, 1, 1), end=date(2025, 12, 31)),
    )
    minimum_subperiod_observations: PositiveInt = 20
    reproducibility_absolute_tolerance: float = Field(default=1e-12, ge=0)
    reproducibility_relative_tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("hard_gates")
    @classmethod
    def hard_gates_are_unique_and_complete(
        cls, value: tuple[HardGateId, ...]
    ) -> tuple[HardGateId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("hard gates must be unique")
        required = set(HardGateId)
        if set(value) != required:
            raise ValueError("validation policy must contain every required hard gate")
        return value

    @field_validator("soft_gates")
    @classmethod
    def soft_metrics_are_unique(
        cls, value: tuple[SoftGateThreshold, ...]
    ) -> tuple[SoftGateThreshold, ...]:
        metrics = [item.metric for item in value]
        if len(metrics) != len(set(metrics)):
            raise ValueError("soft gate metrics must be unique")
        return value

    @field_validator("cost_stress_multipliers")
    @classmethod
    def cost_multipliers_are_locked(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if value != (1.0, 1.5, 2.0):
            raise ValueError("v1 cost stress multipliers must be 1.0, 1.5, and 2.0")
        return value

    @field_validator("parameter_windows", "parameter_top_k")
    @classmethod
    def perturbations_are_sorted_and_unique(
        cls, value: tuple[PositiveInt, ...]
    ) -> tuple[PositiveInt, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("parameter perturbations must be nonempty, sorted, and unique")
        return value

    @field_validator("subperiods")
    @classmethod
    def subperiods_are_ordered_and_disjoint(
        cls, value: tuple[ValidationSubperiod, ...]
    ) -> tuple[ValidationSubperiod, ...]:
        if not value:
            raise ValueError("validation subperiods cannot be empty")
        ids = [item.period_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("validation subperiod IDs must be unique")
        if any(left.end >= right.start for left, right in pairwise(value)):
            raise ValueError("validation subperiods must be ordered and disjoint")
        return value
