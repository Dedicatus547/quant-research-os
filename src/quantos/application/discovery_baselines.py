"""Deterministic bounded baseline expression generation for discovery."""

from __future__ import annotations

import random

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryCompositionDesign,
    DiscoveryDesignContract,
    GenerationRequest,
    SequentialPolicyContract,
)
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


def baseline_expression_space(
    design: DiscoveryDesignContract,
) -> tuple[SafeQlibExpressionSpec, ...]:
    """Common finite grammar for LLM admission and both cheap baselines."""
    if isinstance(design, DiscoveryCompositionDesign):
        from quantos.application.discovery_composition import composition_expression_space

        return composition_expression_space(design)
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


def generate_baseline(
    design: DiscoveryDesignContract, request: GenerationRequest
) -> tuple[str, ...]:
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
    if isinstance(design, DiscoveryCompositionDesign):
        if request.max_attempts > len(candidates):
            raise ValueError("baseline exhausts composition space")
        selected = (
            candidates[: request.max_attempts]
            if request.method == "TEMPLATE"
            else tuple(random.Random(request.seed).sample(candidates, request.max_attempts))
        )
    elif request.method == "TEMPLATE":
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


def generate_sequential_baseline(
    design: DiscoveryDesignContract, request: GenerationRequest, policy: SequentialPolicyContract
) -> tuple[str, ...]:
    """Successor coverage policy; each output is tied to its original opportunity."""
    if request.method not in ("TEMPLATE", "RANDOM"):
        raise ValueError("sequential baseline requires TEMPLATE or RANDOM")
    if (
        request.design_hash != design.content_hash
        or policy.design_hash != design.content_hash
        or request.content_hash not in policy.request_hashes
        or request.max_attempts > policy.max_attempts_per_method
        or request.max_attempts > design.evaluation_opportunities_per_method
        or request.seed is None
    ):
        raise ValueError("sequential baseline identities or opportunity limits differ")
    if isinstance(design, DiscoveryCompositionDesign) != isinstance(
        policy, CompositionGenerationPolicy
    ):
        raise ValueError("generation policy and design profile differ")
    space = baseline_expression_space(design)
    if request.max_attempts > len(space):
        raise ValueError("sequential baseline exhausts the common expression space")
    if request.method == "RANDOM":
        if request.seed != policy.random_seed:
            raise ValueError("sequential random request must bind policy seed 1729")
        selected = random.Random(policy.random_seed).sample(space, request.max_attempts)
    elif isinstance(design, DiscoveryCompositionDesign):
        selected = space[: request.max_attempts]
    else:
        layers = [
            [expression for expression in space if expression.nodes[1].operator is operator]
            for operator in _TEMPLATE_ORDER
        ]
        ordered: list[SafeQlibExpressionSpec] = []
        while any(layers):
            for layer in layers:
                if layer:
                    ordered.append(layer.pop(0))
        selected = ordered[: request.max_attempts]
    encoded = tuple(canonical_json_bytes(expression) for expression in selected)
    if any(len(value) > design.max_output_bytes_per_attempt for value in encoded):
        raise ValueError("baseline expression exceeds per-attempt output byte limit")
    return tuple(value.decode("utf-8") for value in encoded)
