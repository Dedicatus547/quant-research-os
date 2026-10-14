"""Translate the safe expression DAG into Qlib's official expression syntax."""

from __future__ import annotations

from importlib.metadata import version
from typing import cast

from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.research_execution import PITExecutionProfile, QlibExpressionTranslation

_FIELD_MAPPING = {"adjusted_close": "$close"}


def translate_safe_expression(
    spec: SafeQlibExpressionSpec, *, execution_profile: PITExecutionProfile = "legacy-price/v2"
) -> QlibExpressionTranslation:
    """Construct Qlib syntax solely from validated nodes; no caller code is evaluated."""

    if execution_profile not in {"legacy-price/v2", "frozen-field-study/v1"}:
        raise ValueError("unsupported expression execution profile")
    field_mapping = dict(_FIELD_MAPPING)
    if execution_profile == "frozen-field-study/v1":
        field_mapping["adjusted_volume"] = "$volume"
    translated: dict[str, str] = {}
    for node in spec.nodes:
        if node.operator is SafeQlibOperator.FIELD:
            field_name = cast(str, node.field_name)
            try:
                translated[node.node_id] = field_mapping[field_name]
            except KeyError:
                raise ValueError(
                    f"field is not present in the locked Qlib view: {field_name}"
                ) from None
            continue
        inputs = [translated[item] for item in node.inputs]
        window = cast(int, node.window)
        if node.operator is SafeQlibOperator.REF:
            expression = f"Ref({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.DELTA:
            expression = f"Delta({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.RETURN:
            expression = f"(({inputs[0]})/(Ref({inputs[0]},{window}))-1)"
        elif node.operator is SafeQlibOperator.ROLLING_MEAN:
            expression = f"Mean({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ROLLING_STD:
            expression = f"Std({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ROLLING_SUM:
            expression = f"Sum({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ROLLING_MIN:
            expression = f"Min({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ROLLING_MAX:
            expression = f"Max({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.RANK:
            expression = f"Rank({inputs[0]},{window})"
        elif node.operator is SafeQlibOperator.ABS:
            expression = f"Abs({inputs[0]})"
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
