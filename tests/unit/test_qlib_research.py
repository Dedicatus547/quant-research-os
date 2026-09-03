from __future__ import annotations

import pytest
from pydantic import ValidationError
from qlib.config import C
from qlib.data.data import LocalExpressionProvider
from qlib.data.ops import register_all_ops

from quantos.contracts.pit import (
    SafeExpressionNode,
    SafeQlibExpressionSpec,
)
from quantos.research.qlib import translate_safe_expression

register_all_ops(C)
QLIB_EXPRESSION_PROVIDER = LocalExpressionProvider()


def test_safe_expression_translates_to_parseable_qlib_syntax_with_input_lag() -> None:
    spec = SafeQlibExpressionSpec(
        expression_id="momentum_20d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="momentum", operator="return", inputs=("price",), window=20),
        ),
        output_node_id="momentum",
        input_lag_trading_days=1,
    )

    translated = translate_safe_expression(spec)

    assert translated.expression_spec_hash == spec.content_hash
    assert translated.output_expression == "Ref((($close)/(Ref($close,20))-1),1)"
    assert str(QLIB_EXPRESSION_PROVIDER.get_expression_instance(translated.output_expression)) == (
        "Ref(Sub(Div($close,Ref($close,20)),1),1)"
    )


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("ref", "Ref($close,5)"),
        ("rolling_mean", "Mean($close,5)"),
        ("rolling_std", "Std($close,5)"),
        ("rank", "Rank($close,5)"),
    ],
)
def test_window_operators_map_to_official_qlib_operators(operator: str, expected: str) -> None:
    spec = SafeQlibExpressionSpec(
        expression_id="window_feature",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="output", operator=operator, inputs=("price",), window=5),
        ),
        output_node_id="output",
    )
    translated = translate_safe_expression(spec)

    assert translated.output_expression == expected
    assert (
        QLIB_EXPRESSION_PROVIDER.get_expression_instance(translated.output_expression) is not None
    )


def test_translation_rejects_field_absent_from_locked_view() -> None:
    spec = SafeQlibExpressionSpec(
        expression_id="raw",
        nodes=(SafeExpressionNode(node_id="raw", operator="field", field_name="raw_close"),),
        output_node_id="raw",
    )
    with pytest.raises(ValueError, match="not present"):
        translate_safe_expression(spec)


def test_rank_requires_an_explicit_window() -> None:
    with pytest.raises(ValidationError, match="window operator"):
        SafeExpressionNode(node_id="rank", operator="rank", inputs=("price",))
