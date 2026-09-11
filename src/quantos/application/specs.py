"""Deterministic translation from proposal YAML to canonical resolved specs."""

from __future__ import annotations

from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResolvedExperimentSpec,
    ResolvedStrategySpec,
)


def resolve_experiment(
    authoring: ExperimentAuthoringSpec,
    *,
    snapshot_hash: str,
    qlib_view_hash: str,
    qlib_version: str,
    qlib_view_spec_hash: str,
    pit_audit_evidence_hash: str,
    research_policy_hash: str,
    validation_policy_hash: str,
    cost_policy_hash: str,
    backtest_policy_hash: str,
    code_commit_hash: str,
    lockfile_hash: str,
) -> ResolvedExperimentSpec:
    """Resolve every logical dependency before a canonical process may start."""

    if isinstance(authoring.expression, SafeQlibExpressionSpec):
        expression = authoring.expression
    else:
        field_node = SafeExpressionNode(
            node_id="adjusted_close",
            operator=SafeQlibOperator.FIELD,
            field_name=authoring.expression.field,
        )
        output_node = SafeExpressionNode(
            node_id=authoring.expression.expression_id,
            operator=SafeQlibOperator.RETURN,
            inputs=(field_node.node_id,),
            window=authoring.expression.window,
        )
        expression = SafeQlibExpressionSpec(
            expression_id=authoring.expression.expression_id,
            nodes=(field_node, output_node),
            output_node_id=output_node.node_id,
            input_lag_trading_days=authoring.strategy.input_lag_trading_days,
        )
    strategy = ResolvedStrategySpec(
        universe_index=authoring.strategy.universe_index,
        selection_method=authoring.strategy.selection_method,
        top_k=authoring.strategy.top_k,
        weighting_method=authoring.strategy.weighting_method,
        rebalance_frequency=authoring.strategy.rebalance_frequency,
        execution_mode=authoring.strategy.execution_mode,
        input_lag_trading_days=authoring.strategy.input_lag_trading_days,
        execution_lag_trading_sessions=authoring.strategy.execution_lag_trading_sessions,
        exclude_st=authoring.strategy.exclude_st,
        exclude_suspended=authoring.strategy.exclude_suspended,
        respect_price_limits=authoring.strategy.respect_price_limits,
        trade_unit_shares=authoring.strategy.trade_unit_shares,
        max_weight=authoring.strategy.max_weight,
    )
    return ResolvedExperimentSpec(
        experiment_id=authoring.experiment_id,
        authoring_spec_hash=authoring.content_hash,
        evaluation_start=authoring.evaluation_start,
        evaluation_end=authoring.evaluation_end,
        snapshot_hash=snapshot_hash,
        qlib_view_hash=qlib_view_hash,
        qlib_version=qlib_version,
        qlib_view_spec_hash=qlib_view_spec_hash,
        pit_audit_evidence_hash=pit_audit_evidence_hash,
        expression=expression,
        strategy=strategy,
        research_policy_hash=research_policy_hash,
        validation_policy_hash=validation_policy_hash,
        cost_policy_hash=cost_policy_hash,
        backtest_policy_hash=backtest_policy_hash,
        code_commit_hash=code_commit_hash,
        lockfile_hash=lockfile_hash,
    )
