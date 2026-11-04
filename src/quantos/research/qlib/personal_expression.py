"""Bounded successor translation; native Qlib computes every numeric operator."""

from __future__ import annotations

from quantos.contracts.personal_strategy import PersonalExpression, PredicateNode, ScalarNode
from quantos.contracts.pit import SafeExpressionNode, SafeQlibOperator
from quantos.research.qlib.expression import render_safe_operator

FIELD_MAPPING = {
    "adjusted_open": "$open",
    "adjusted_high": "$high",
    "adjusted_low": "$low",
    "adjusted_close": "$close",
    "adjusted_volume": "$volume",
    "amount_cny": "$amount_cny",
}
MAX_TRANSLATION_CHARS = 65_536
_NULL = "(($close-$close)/($close-$close))"


def _finite(expression: str) -> str:
    return f"((({expression})-({expression}))==0)"


def _guard(expression: str, valid: str) -> str:
    return f"If({valid},{expression},{_NULL})"


def translate_personal_expression(spec: PersonalExpression) -> str:
    """Render only admitted nodes, preserving null through native boolean operators.

    Qlib comparisons turn NaN into False and rolling operators permit partial
    windows. Explicit finite/Count guards define v3's stricter missing semantics.
    """
    translated: dict[str, str] = {}
    for node in spec.nodes:
        inputs = [translated[x] for x in node.inputs]
        if isinstance(node, ScalarNode):
            # This native feature keeps an absent/invalid source bar absent.
            out = f"($close*0+({format(node.value, '.17g')}))"
        elif isinstance(node, PredicateNode):
            if node.operator == "not":
                value = f"(({inputs[0]})==0)"
                valid = _finite(inputs[0])
            else:
                if node.operator in {"and", "or"}:
                    operator = "&" if node.operator == "and" else "|"
                    value = f"((({inputs[0]})!=0){operator}(({inputs[1]})!=0))"
                else:
                    operator = {"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": "=="}[
                        node.operator
                    ]
                    value = f"(({inputs[0]}){operator}({inputs[1]}))"
                valid = f"({_finite(inputs[0])}&{_finite(inputs[1])})"
            out = _guard(value, valid)
        elif node.operator is SafeQlibOperator.FIELD:
            assert node.field_name is not None
            out = FIELD_MAPPING[node.field_name]
        else:
            out = render_safe_operator(node, inputs)
            if node.operator is SafeQlibOperator.DIVIDE:
                valid = f"({_finite(inputs[0])}&{_finite(inputs[1])}&(({inputs[1]})!=0))"
                out = _guard(out, valid)
            elif node.operator is SafeQlibOperator.RETURN:
                previous = f"Ref({inputs[0]},{node.window})"
                valid = f"({_finite(inputs[0])}&{_finite(previous)}&(({previous})!=0))"
                out = _guard(out, valid)
            elif node.operator in {
                SafeQlibOperator.ROLLING_MEAN,
                SafeQlibOperator.ROLLING_STD,
                SafeQlibOperator.ROLLING_SUM,
                SafeQlibOperator.ROLLING_MIN,
                SafeQlibOperator.ROLLING_MAX,
                SafeQlibOperator.RANK,
            }:
                present = _guard(inputs[0], _finite(inputs[0]))
                out = _guard(out, f"(Count({present},{node.window})=={node.window})")
        if len(out) > MAX_TRANSLATION_CHARS:
            raise ValueError("expanded Qlib expression exceeds 65536 characters")
        translated[node.node_id] = out
    output = translated[spec.output_node_id]
    if spec.input_lag_trading_days:
        output = f"Ref({output},{spec.input_lag_trading_days})"
    if len(output) > MAX_TRANSLATION_CHARS:
        raise ValueError("expanded Qlib expression exceeds 65536 characters")
    return output


def expression_dependencies(spec: PersonalExpression) -> dict[str, tuple[int, ...]]:
    """Exact bounded field/session offsets for the output's backward dependencies."""
    lineage: dict[str, dict[str, set[int]]] = {}
    for node in spec.nodes:
        if isinstance(node, ScalarNode):
            output = {"adjusted_close": {0}}
        elif isinstance(node, SafeExpressionNode) and node.operator is SafeQlibOperator.FIELD:
            assert node.field_name is not None
            output = {node.field_name: {0}}
        else:
            shifts = {0}
            if isinstance(node, SafeExpressionNode) and node.window is not None:
                if node.operator is SafeQlibOperator.REF:
                    shifts = {node.window}
                elif node.operator in {SafeQlibOperator.RETURN, SafeQlibOperator.DELTA}:
                    shifts = {0, node.window}
                else:
                    shifts = set(range(node.window))
            output: dict[str, set[int]] = {}
            for parent in node.inputs:
                for field, offsets in lineage[parent].items():
                    output.setdefault(field, set()).update(
                        x + shift for x in offsets for shift in shifts
                    )
        lineage[node.node_id] = output
    return {
        field: tuple(sorted(x + spec.input_lag_trading_days for x in offsets))
        for field, offsets in lineage[spec.output_node_id].items()
    }


def required_history(spec: PersonalExpression) -> int:
    """Conservative backward dependency; input lag is applied exactly once."""
    return max((max(offsets) for offsets in expression_dependencies(spec).values()), default=0)
