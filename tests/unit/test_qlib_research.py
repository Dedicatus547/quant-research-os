from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from qlib.config import C
from qlib.data.data import LocalExpressionProvider
from qlib.data.ops import Abs, Delta, Max, Min, Sum, register_all_ops

from quantos.contracts.pit import (
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
)
from quantos.contracts.research_execution import required_expression_observations
from quantos.research.qlib import translate_safe_expression

register_all_ops(C)
QLIB_EXPRESSION_PROVIDER = LocalExpressionProvider()


class _FrozenSeries:
    def __init__(self, values: list[float]) -> None:
        self._values = pd.Series(values, dtype=float)

    def load(self, *_args: object, **_kwargs: object) -> pd.Series:
        return self._values.copy()


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
    ("operator", "expected", "schema_version"),
    [
        ("ref", "Ref($close,5)", "safe-qlib-expression/v1"),
        ("rolling_mean", "Mean($close,5)", "safe-qlib-expression/v1"),
        ("rolling_std", "Std($close,5)", "safe-qlib-expression/v1"),
        ("rank", "Rank($close,5)", "safe-qlib-expression/v1"),
        ("delta", "Delta($close,5)", "safe-qlib-expression/v2"),
        ("rolling_sum", "Sum($close,5)", "safe-qlib-expression/v2"),
        ("rolling_min", "Min($close,5)", "safe-qlib-expression/v2"),
        ("rolling_max", "Max($close,5)", "safe-qlib-expression/v2"),
    ],
)
def test_window_operators_map_to_official_qlib_operators(
    operator: str, expected: str, schema_version: str
) -> None:
    spec = SafeQlibExpressionSpec(
        schema_version=schema_version,
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


def test_v2_abs_maps_to_official_qlib_and_preserves_complete_pit_window() -> None:
    spec = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="absolute_delta",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="delta", operator="delta", inputs=("price",), window=5),
            SafeExpressionNode(node_id="output", operator="abs", inputs=("delta",)),
        ),
        output_node_id="output",
    )

    translated = translate_safe_expression(spec)

    assert translated.output_expression == "Abs(Delta($close,5))"
    assert QLIB_EXPRESSION_PROVIDER.get_expression_instance(translated.output_expression)
    assert required_expression_observations(spec) == 6


def test_v2_numeric_semantics_are_locked_to_official_qlib_operators() -> None:
    source = _FrozenSeries([1.0, float("nan"), -3.0, 4.0, float("inf")])
    actual = {
        "abs": Abs(source)._load_internal("fixture", 0, 4).to_numpy(),
        "delta": Delta(source, 2)._load_internal("fixture", 0, 4).to_numpy(),
        "rolling_sum": Sum(source, 3)._load_internal("fixture", 0, 4).to_numpy(),
        "rolling_min": Min(source, 3)._load_internal("fixture", 0, 4).to_numpy(),
        "rolling_max": Max(source, 3)._load_internal("fixture", 0, 4).to_numpy(),
    }
    expected = {
        "abs": [1.0, float("nan"), 3.0, 4.0, float("inf")],
        "delta": [float("nan"), float("nan"), -4.0, float("nan"), float("inf")],
        "rolling_sum": [1.0, 1.0, -2.0, 1.0, 1.0],
        "rolling_min": [1.0, 1.0, -3.0, -3.0, -3.0],
        "rolling_max": [1.0, 1.0, 1.0, 4.0, 4.0],
    }
    for operator, values in actual.items():
        np.testing.assert_allclose(values, expected[operator], equal_nan=True)


def test_unadmitted_dsl_candidates_are_not_public_operators() -> None:
    for candidate in (
        "clip",
        "correlation",
        "cross_section_rank",
        "industry_neutralize",
        "log",
        "size_neutralize",
        "zscore",
    ):
        with pytest.raises(ValueError):
            SafeQlibOperator(candidate)


def test_dsl_v1_cannot_silently_use_v2_operator() -> None:
    with pytest.raises(ValidationError, match="DSL v2 operators"):
        SafeQlibExpressionSpec(
            expression_id="v1_delta",
            nodes=(
                SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
                SafeExpressionNode(node_id="output", operator="delta", inputs=("price",), window=2),
            ),
            output_node_id="output",
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
