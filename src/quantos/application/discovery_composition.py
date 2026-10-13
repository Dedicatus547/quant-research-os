"""Finite price composition grammar, shared by admission and both baselines.

Productions: C=Return(close,w); N=Mean/Std(Return(close,a),b);
C, N, C/N, C*N. No arbitrary expressions or runtime evaluation.
"""

from functools import lru_cache

from quantos.application.enumeration import structural_expression_hash
from quantos.contracts.discovery import DiscoveryCompositionDesign
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator


def expression_depth(expression: SafeQlibExpressionSpec) -> int:
    depths: dict[str, int] = {}
    for node in expression.nodes:
        depths[node.node_id] = 1 + max((depths[i] for i in node.inputs), default=0)
    return depths[expression.output_node_id]


@lru_cache(maxsize=32)
def _space(
    windows: tuple[int, ...],
    operators: tuple[SafeQlibOperator, ...],
    max_nodes: int,
    max_depth: int,
    lag: int,
) -> tuple[SafeQlibExpressionSpec, ...]:
    field = SafeExpressionNode(
        node_id="close", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
    )
    candidates: dict[str, SafeQlibExpressionSpec] = {}

    def add(nodes: tuple[SafeExpressionNode, ...]) -> None:
        expression = SafeQlibExpressionSpec(
            schema_version="safe-qlib-expression/v2",
            expression_id="composition",
            nodes=nodes,
            output_node_id=nodes[-1].node_id,
            input_lag_trading_days=lag,
        )
        if (
            len(nodes) <= max_nodes
            and expression_depth(expression) <= max_depth
            and all(n.operator in operators for n in nodes)
        ):
            digest = structural_expression_hash(expression)
            candidates[digest] = expression.model_copy(
                update={"expression_id": f"composition_{digest}"}
            )

    # The finite inventory order is also the declared deterministic rule preference.
    components: list[tuple[SafeExpressionNode, ...]] = []
    nested: list[tuple[SafeExpressionNode, ...]] = []
    combinations: list[tuple[SafeExpressionNode, ...]] = []
    short_windows = tuple(
        sorted(
            windows,
            key=lambda w: ((5, 10, 20, 1, 60).index(w) if w in (5, 10, 20, 1, 60) else 5, w),
        )
    )
    long_windows = tuple(
        sorted(
            windows,
            key=lambda w: ((20, 60, 10, 5, 1).index(w) if w in (20, 60, 10, 5, 1) else 5, w),
        )
    )
    for w in short_windows:
        component = SafeExpressionNode(
            node_id="short_return", operator=SafeQlibOperator.RETURN, inputs=("close",), window=w
        )
        components.append((field, component))
    for op in (SafeQlibOperator.ROLLING_STD, SafeQlibOperator.ROLLING_MEAN):
        for a in windows:
            inner = SafeExpressionNode(
                node_id="inner_return",
                operator=SafeQlibOperator.RETURN,
                inputs=("close",),
                window=a,
            )
            for b in long_windows:
                long = SafeExpressionNode(
                    node_id="long_stat", operator=op, inputs=("inner_return",), window=b
                )
                nested.append((field, inner, long))
                for w in short_windows:
                    short = SafeExpressionNode(
                        node_id="short_return",
                        operator=SafeQlibOperator.RETURN,
                        inputs=("close",),
                        window=w,
                    )
                    for binary in (SafeQlibOperator.DIVIDE, SafeQlibOperator.MULTIPLY):
                        out = SafeExpressionNode(
                            node_id="combination",
                            operator=binary,
                            inputs=("short_return", "long_stat"),
                        )
                        combinations.append((field, short, inner, long, out))
    # Rule baseline alternates interaction, its simple constituent, and nested constituent.
    for index in range(max(len(components), len(nested), len(combinations))):
        for layer in (combinations, components, nested):
            if index < len(layer):
                add(layer[index])
    return tuple(candidates.values())


def composition_expression_space(
    design: DiscoveryCompositionDesign,
) -> tuple[SafeQlibExpressionSpec, ...]:
    return _space(
        design.allowed_windows,
        design.allowed_operators,
        design.max_nodes,
        design.max_depth,
        design.authoring.strategy.input_lag_trading_days,
    )


@lru_cache(maxsize=32)
def _hashes(
    windows: tuple[int, ...],
    operators: tuple[SafeQlibOperator, ...],
    max_nodes: int,
    max_depth: int,
    lag: int,
) -> frozenset[str]:
    return frozenset(
        structural_expression_hash(e) for e in _space(windows, operators, max_nodes, max_depth, lag)
    )


def composition_structural_hashes(design: DiscoveryCompositionDesign) -> frozenset[str]:
    return _hashes(
        design.allowed_windows,
        design.allowed_operators,
        design.max_nodes,
        design.max_depth,
        design.authoring.strategy.input_lag_trading_days,
    )
