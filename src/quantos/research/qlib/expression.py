"""Translate the safe expression DAG into Qlib's official expression syntax."""

from __future__ import annotations

from importlib.metadata import version
from typing import cast

from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.research_execution import QlibExpressionTranslation

_FIELD_MAPPING = {"adjusted_close": "$close"}


def translate_safe_expression(spec: SafeQlibExpressionSpec) -> QlibExpressionTranslation:
    """Construct Qlib syntax solely from validated nodes; no caller code is evaluated."""

    translated: dict[str, str] = {}
    for node in spec.nodes:
        if node.operator is SafeQlibOperator.FIELD:
            field_name = cast(str, node.field_name)
            try:
                translated[node.node_id] = _FIELD_MAPPING[field_name]
            except KeyError:
                raise ValueError(
                    f"field is not present in the locked Qlib view: {field_name}"
                ) from None
            continue
        inputs = [translated[item] for item in node.inputs]
        window = cast(int, node.window)
        if node.operator is SafeQlibOperator.REF:
            expression = f"Ref({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.RETURN:
            expression = f"(({inputs[0]})/(Ref({inputs[0]},{window}))-1)"
        elif node.operator is SafeQlibOperator.ROLLING_MEAN:
            expression = f"Mean({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ROLLING_STD:
            expression = f"Std({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.RANK:
            expression = f"Rank({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ADD:
            expression = f"({inputs[0]}+{inputs[1]})"
        elif node.operator is SafeQlibOperator.SUBTRACT:
            expression = f"({inputs[0]}-{inputs[1]})"
        elif node.operator is SafeQlibOperator.MULTIPLY:
            expression = f"({inputs[0]}*{inputs[1]})"
        elif node.operator is SafeQlibOperator.DIVIDE:
            expression = f"({inputs[0]}/{inputs[1]})"
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"unsupported safe Qlib operator: {node.operator}")
        translated[node.node_id] = expression

    output = translated[spec.output_node_id]
    if spec.input_lag_trading_days:
        output = f"Ref({output},{spec.input_lag_trading_days})"
    return QlibExpressionTranslation(
        expression_spec_hash=spec.content_hash,
        qlib_version=version("pyqlib"),
        output_name=spec.expression_id,
        output_expression=output,
    )
