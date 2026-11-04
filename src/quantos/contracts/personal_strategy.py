"""Versioned personal strategy proposals; no runtime or model dependencies.

Legacy personal requests and Safe DSL v1/v2 retain their canonical bytes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.personal_research import HostSessionProposalV2
from quantos.contracts.pit import SafeExpressionNode
from quantos.contracts.refs import SHA256_PATTERN


class ScalarNode(CanonicalContract):
    schema_version: Literal["safe-scalar-node/v1"] = "safe-scalar-node/v1"
    node_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    operator: Literal["constant"] = "constant"
    value: float = Field(ge=-1e9, le=1e9)
    inputs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def no_inputs(self) -> Self:
        if self.inputs:
            raise ValueError("constants have no inputs")
        return self


class PredicateNode(CanonicalContract):
    schema_version: Literal["safe-predicate-node/v1"] = "safe-predicate-node/v1"
    node_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    operator: Literal["gt", "ge", "lt", "le", "eq", "and", "or", "not"]
    inputs: tuple[str, ...]

    @model_validator(mode="after")
    def arity(self) -> Self:
        if len(self.inputs) != (1 if self.operator == "not" else 2):
            raise ValueError("predicate arity disagrees")
        return self


class PersonalExpression(CanonicalContract):
    schema_version: Literal["safe-qlib-expression/v3"] = "safe-qlib-expression/v3"
    expression_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
    nodes: tuple[SafeExpressionNode | ScalarNode | PredicateNode, ...] = Field(
        min_length=1, max_length=64
    )
    output_node_id: str
    input_lag_trading_days: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def bounded_dag(self) -> Self:
        known: set[str] = set()
        for node in self.nodes:
            if node.node_id in known or any(x not in known for x in node.inputs):
                raise ValueError("nodes must be a unique topological DAG")
            if isinstance(node, SafeExpressionNode):
                if node.window is not None and node.window > 120:
                    raise ValueError("window exceeds 120 sessions")
                if node.field_name is not None and node.field_name not in {
                    "adjusted_open",
                    "adjusted_high",
                    "adjusted_low",
                    "adjusted_close",
                    "adjusted_volume",
                    "amount_cny",
                }:
                    raise ValueError("field not supported by the personal daily mapping")
            known.add(node.node_id)
        if self.output_node_id not in known:
            raise ValueError("unknown output")
        return self


class PersonalStrategy(CanonicalContract):
    schema_version: Literal["personal-strategy/v1"] = "personal-strategy/v1"
    score: PersonalExpression
    eligibility: PersonalExpression | None = None
    market_condition: PersonalExpression | None = None
    rank_direction: Literal["descending", "ascending"] = "descending"
    tie_break: Literal["instrument_ascending"] = "instrument_ascending"
    cross_section: Literal["eligible_finite_scores"] = "eligible_finite_scores"
    top_k: int = Field(default=10, ge=1, le=20)
    max_weight: float = Field(default=0.1, gt=0, le=1)
    risk_degree: float = Field(default=0.9, gt=0, le=1)
    target_weights: dict[str, float] | None = None
    rebalance: Literal["daily", "weekly_first_session"] = "daily"
    rank_buffer: int = Field(default=0, ge=0, le=20)
    max_holding_sessions: int | None = Field(default=None, ge=1, le=120)
    rule_priority: Literal["eligibility_max_age_then_schedule_buffer"] = (
        "eligibility_max_age_then_schedule_buffer"
    )
    signal_time: Literal["after_close_2359_Asia_Shanghai"] = "after_close_2359_Asia_Shanghai"
    execution_time: Literal["next_actual_session_open"] = "next_actual_session_open"

    @model_validator(mode="after")
    def finite_weights(self) -> Self:
        if self.target_weights is not None:
            import re

            if (
                not self.target_weights
                or len(self.target_weights) > 20
                or any(
                    re.fullmatch(r"(SH|SZ)[0-9]{6}", k) is None or not 0 < v <= self.max_weight
                    for k, v in self.target_weights.items()
                )
                or sum(self.target_weights.values()) > self.risk_degree + 1e-12
            ):
                raise ValueError("explicit weights exceed instrument or portfolio bounds")
        return self


class PersonalExecutionPolicy(CanonicalContract):
    schema_version: Literal["personal-execution-policy/v1"] = "personal-execution-policy/v1"
    engine: Literal["Qlib-0.9.7"] = "Qlib-0.9.7"
    units: Literal["supplier_adjusted_price_and_quantity"] = "supplier_adjusted_price_and_quantity"
    initial_cash_cny: float = Field(default=1_000_000, gt=0, le=1e9)
    buy_cost: float = Field(default=0.0005, ge=0, le=0.01)
    sell_cost: float = Field(default=0.0015, ge=0, le=0.02)
    minimum_cost_cny: float = Field(default=5, ge=0, le=100)
    trade_unit_shares: int = Field(default=200, ge=1, le=1000)
    volume_participation: float = Field(default=0.1, gt=0, le=0.1)
    settlement: Literal["native_cash_daily_no_full_exchange_qualification"] = (
        "native_cash_daily_no_full_exchange_qualification"
    )
    unsupported_actions: Literal["HARD_STOP"] = "HARD_STOP"


class StrategyCandidate(CanonicalContract):
    schema_version: Literal["personal-strategy-candidate/v1"] = "personal-strategy-candidate/v1"
    candidate_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,48}$")
    role: Literal["main", "control", "successor"]
    hypothesis: str = Field(min_length=1, max_length=4000)
    strategy: PersonalStrategy


class StrategyStudyRequest(CanonicalContract):
    schema_version: Literal["personal-study-request/v7"] = "personal-study-request/v7"
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    brief: str = Field(min_length=1, max_length=12000)
    proposal: HostSessionProposalV2
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    start_date: date
    end_date: date
    warmup_start: date
    benchmark: str = Field(default="SH000300", pattern=r"^(SH|SZ)[0-9]{6}$")
    candidates: tuple[StrategyCandidate, ...] = Field(min_length=1, max_length=4)
    policy: PersonalExecutionPolicy = Field(default_factory=PersonalExecutionPolicy)
    parent_task_id: str | None = Field(default=None, pattern=SHA256_PATTERN)
    feedback_hashes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        if not self.warmup_start <= self.start_date <= self.end_date:
            raise ValueError("warmup and execution dates are reversed")
        ids = [c.candidate_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate ids")
        if len({c.strategy.content_hash for c in self.candidates}) != len(self.candidates):
            raise ValueError(
                "duplicate executable strategies; change roles without executing twice"
            )
        import re

        if len(self.feedback_hashes) > 20 or any(
            re.fullmatch(SHA256_PATTERN, h) is None for h in self.feedback_hashes
        ):
            raise ValueError("feedback must be bounded immutable references")
        return self


class PreparedStrategyStudy(CanonicalContract):
    schema_version: Literal["personal-study-prepared/v6"] = "personal-study-prepared/v6"
    request: StrategyStudyRequest
    code_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    strategy_hashes: dict[str, str]
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    readiness: Literal["READY_FOR_AUTHORIZATION", "BLOCKED"]
    gaps: tuple[str, ...]
    resolved: dict[str, object]
    validation_verdict: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"

    @property
    def candidates(self) -> tuple[StrategyCandidate, ...]:
        return self.request.candidates


class PersonalSignalArtifact(CanonicalContract):
    """Successor SignalArtifact, using the existing SignalRow/Arrow representation."""

    schema_version: Literal["personal-signal-artifact/v1"] = "personal-signal-artifact/v1"
    strategy_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    panel_sha256: str = Field(pattern=SHA256_PATTERN)
    pit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_hash: str = Field(pattern=SHA256_PATTERN)
    expression_translation_hash: str = Field(pattern=SHA256_PATTERN)
    transform_lineage_hash: str = Field(pattern=SHA256_PATTERN)
    signal_content_hash: str = Field(pattern=SHA256_PATTERN)
    signals_parquet_sha256: str = Field(pattern=SHA256_PATTERN)
    start_date: date
    end_date: date
    row_count: int = Field(gt=0)
    input_lag: Literal["expression_once"] = "expression_once"
    execution_lag: Literal["native_previous_actual_session_once"] = (
        "native_previous_actual_session_once"
    )
    source_vintage: str


class PersonalSignalArtifactV2(PersonalSignalArtifact):
    schema_version: Literal["personal-signal-artifact/v2"] = "personal-signal-artifact/v2"  # pyright: ignore[reportIncompatibleVariableOverride]
    field_mapping_profile: Literal["canonical-personal-fields/v1"] = "canonical-personal-fields/v1"


class PersonalResearchScope(CanonicalContract):
    schema_version: Literal["personal-research-scope/v1"] = "personal-research-scope/v1"
    purpose: Literal["SYNTHETIC_ENGINEERING", "MARKET_RESEARCH"]
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_hash: str = Field(pattern=SHA256_PATTERN)
    allowed_strategy_hashes: tuple[str, ...] = Field(min_length=1, max_length=16)
    start_date: date
    end_date: date
    max_attempts: int = Field(ge=1, le=8)
    max_native_accounts: int = Field(ge=1, le=16)
    wall_seconds: int = Field(gt=0, le=3600)
    growth_bytes: int = Field(gt=0, le=512 * 1024**2)
    expires_at: datetime
    approval_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    acquisition_calls: Literal[0] = 0
    sdk_calls: Literal[0] = 0
    validation_calls: Literal[0] = 0
    stop_on: tuple[Literal["BUDGET", "EXPIRY", "CANCEL", "UNKNOWN", "OPERATOR_STOP"], ...] = (
        "BUDGET",
        "EXPIRY",
        "CANCEL",
        "UNKNOWN",
        "OPERATOR_STOP",
    )

    @model_validator(mode="after")
    def bounded_authority(self) -> Self:
        import re

        if self.start_date > self.end_date or self.expires_at.tzinfo is None:
            raise ValueError("scope dates/timezone invalid")
        if len(set(self.allowed_strategy_hashes)) != len(self.allowed_strategy_hashes) or any(
            re.fullmatch(SHA256_PATTERN, x) is None for x in self.allowed_strategy_hashes
        ):
            raise ValueError("scope requires unique explicit strategy hashes")
        if set(self.stop_on) != {"BUDGET", "EXPIRY", "CANCEL", "UNKNOWN", "OPERATOR_STOP"}:
            raise ValueError("all frozen stop conditions are required")
        return self


class PersonalForwardScope(CanonicalContract):
    schema_version: Literal["personal-forward-scope/v1"] = "personal-forward-scope/v1"
    purpose: Literal["SYNTHETIC_ENGINEERING", "FORWARD_OBSERVATION"]
    strategy_hash: str = Field(pattern=SHA256_PATTERN)
    policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_hash: str = Field(pattern=SHA256_PATTERN)
    allowed_dataset_hashes: tuple[str, ...] = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date
    max_observations: int = Field(gt=0, le=120)
    max_native_steps: int = Field(gt=0, le=120)
    wall_seconds: int = Field(gt=0, le=3600)
    growth_bytes: int = Field(gt=0, le=512 * 1024**2)
    expires_at: datetime
    approval_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    acquisition_calls: Literal[0] = 0
    sdk_calls: Literal[0] = 0

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        import re

        if (
            self.start_date > self.end_date
            or self.expires_at.tzinfo is None
            or any(re.fullmatch(SHA256_PATTERN, h) is None for h in self.allowed_dataset_hashes)
        ):
            raise ValueError("forward scope requires explicit valid dates and dataset hashes")
        if len(set(self.allowed_dataset_hashes)) != len(self.allowed_dataset_hashes):
            raise ValueError("duplicate forward dataset identities")
        return self
