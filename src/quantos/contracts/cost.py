"""Cost configuration consumed by Qlib's Exchange adapter."""

from typing import Literal

from pydantic import Field, PositiveInt

from quantos.contracts.base import CanonicalContract


class CostPolicy(CanonicalContract):
    schema_version: Literal["cost-policy/v1"] = "cost-policy/v1"
    policy_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    deal_price: Literal["open"] = "open"
    open_cost_rate: float = Field(ge=0, lt=1)
    close_cost_rate: float = Field(ge=0, lt=1)
    minimum_cost_cny: float = Field(ge=0)
    trade_unit_shares: PositiveInt
    price_limit_fields: Literal["$limit_buy,$limit_sell"] = "$limit_buy,$limit_sell"
    volume_limit_fraction: float = Field(gt=0, le=1)


class BacktestPolicy(CanonicalContract):
    schema_version: Literal["backtest-policy/v1"] = "backtest-policy/v1"
    policy_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    engine: Literal["Qlib SimulatorExecutor"] = "Qlib SimulatorExecutor"
    strategy_adapter: Literal["FullReplacementTopKStrategy"] = "FullReplacementTopKStrategy"
    order_generator: Literal["Qlib OrderGenWOInteract"] = "Qlib OrderGenWOInteract"
    benchmark: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    initial_cash_cny: float = Field(gt=0)
    frequency: Literal["day"] = "day"
    risk_degree: Literal[1] = 1
    trade_type: Literal["serial"] = "serial"
    settlement: Literal["None"] = "None"
    generate_portfolio_metrics: Literal[True] = True
    limit_precheck_semantics: Literal["conservative_block_if_either_side_limited/v1"] = (
        "conservative_block_if_either_side_limited/v1"
    )
    blocked_trade_evidence: Literal["aggregate_fulfillment_without_reason_codes/v1"] = (
        "aggregate_fulfillment_without_reason_codes/v1"
    )
