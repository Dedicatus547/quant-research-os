"""Deterministic bounded baseline expression generation for discovery."""

from __future__ import annotations

import random

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.discovery import DiscoveryDesign, GenerationRequest
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator

_TEMPLATE_ORDER = (
    SafeQlibOperator.RETURN,
    SafeQlibOperator.ROLLING_MEAN,
    SafeQlibOperator.ROLLING_STD,
    SafeQlibOperator.RANK,
)


def _expression(
    operator: SafeQlibOperator,
    window: int,
    *,
    absolute: bool = False,
    ratio: bool = False,
) -> SafeQlibExpressionSpec:
    nodes = [
        SafeExpressionNode(
            node_id="close", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
        ),
        SafeExpressionNode(
            node_id="window",
            operator=operator,
            inputs=("close",),
            window=window,
        ),
    ]
    output_node_id = "window"
    if ratio:
        nodes.append(
            SafeExpressionNode(
                node_id="ratio",
                operator=SafeQlibOperator.DIVIDE,
                inputs=("close", "window"),
            )
        )
        output_node_id = "ratio"
    if absolute:
        nodes.append(
            SafeExpressionNode(
                node_id="absolute",
                operator=SafeQlibOperator.ABS,
                inputs=(output_node_id,),
            )
        )
        output_node_id = "absolute"
    return SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id=f"baseline_{operator.value}_{window}"
        + ("_ratio" if ratio else "")
        + ("_abs" if absolute else ""),
        nodes=tuple(nodes),
        output_node_id=output_node_id,
    )


def baseline_expression_space(design: DiscoveryDesign) -> tuple[SafeQlibExpressionSpec, ...]:
    """Common finite grammar for LLM admission and both cheap baselines."""
    allowed = set(design.allowed_operators)
    if SafeQlibOperator.FIELD not in allowed or design.max_nodes < 2:
        raise ValueError("design does not permit the minimum field/window baseline expression")
    window_operators = tuple(operator for operator in _TEMPLATE_ORDER if operator in allowed)
    if not window_operators:
        raise ValueError("design allows no baseline window operator")

    candidates: list[SafeQlibExpressionSpec] = []
    for operator in window_operators:
        for window in design.allowed_windows:
            candidates.append(_expression(operator, window))
            if SafeQlibOperator.ABS in allowed:
                candidates.append(_expression(operator, window, absolute=True))
            if operator is SafeQlibOperator.ROLLING_MEAN and SafeQlibOperator.DIVIDE in allowed:
                candidates.append(_expression(operator, window, ratio=True))
                if SafeQlibOperator.ABS in allowed:
                    candidates.append(_expression(operator, window, ratio=True, absolute=True))
    return tuple(
        SafeQlibExpressionSpec.model_validate(
            {
                **expression.model_dump(mode="python"),
                "input_lag_trading_days": design.authoring.strategy.input_lag_trading_days,
            }
        )
        for expression in candidates
        if len(expression.nodes) <= design.max_nodes
        and all(node.operator in allowed for node in expression.nodes)
    )


def generate_baseline(design: DiscoveryDesign, request: GenerationRequest) -> tuple[str, ...]:
    """Return bounded canonical SafeQlibExpressionSpec JSON strings.

    Duplicate expressions are retained as separate attempts. This function only
    creates proposals; it does not evaluate expressions or calculate science values.
    """

    if request.method not in ("TEMPLATE", "RANDOM"):
        raise ValueError("baseline generation supports TEMPLATE or RANDOM requests only")
    if request.design_hash != design.content_hash:
        raise ValueError("generation request design_hash does not match design")
    if request.seed is None:  # The contract requires an explicit seed for baselines.
        raise ValueError("baseline generation requires an explicit seed")
    if request.max_attempts > design.evaluation_opportunities_per_method:
        raise ValueError("max_attempts exceeds design opportunities for this method")

    candidates = baseline_expression_space(design)
    if not candidates:
        raise ValueError("design allows no baseline expression within its node and operator limits")
    if request.method == "TEMPLATE":
        selected = tuple(
            candidates[index % len(candidates)] for index in range(request.max_attempts)
        )
    else:
        generator = random.Random(request.seed)
        selected = tuple(generator.choice(candidates) for _ in range(request.max_attempts))

    output: list[str] = []
    for expression in selected:
        encoded = canonical_json_bytes(expression)
        if len(encoded) > design.max_output_bytes_per_attempt:
            raise ValueError("baseline expression exceeds per-attempt output byte limit")
        output.append(encoded.decode("utf-8"))
    return tuple(output)
