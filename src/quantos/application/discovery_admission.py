"""Deterministic capability admission and singleton-family batch freezing."""

from __future__ import annotations

import json
from typing import cast

from quantos.application.discovery_baselines import baseline_expression_space
from quantos.application.enumeration import (
    enumerate_research_family,
    structural_expression_hash,
)
from quantos.contracts.campaign import ParameterDimension, ResearchFamilySpec
from quantos.contracts.discovery import (
    DiscoveryBatch,
    DiscoveryCompositionDesign,
    DiscoveryDesignContract,
    DiscoverySubtask,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
    ProposalMapping,
)
from quantos.contracts.enumeration import (
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchTemplateParameterSlot,
)
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator


def capability_rejection(
    design: DiscoveryDesignContract, expression: SafeQlibExpressionSpec
) -> str | None:
    """Static support checks; these never substitute for execution-time PIT."""
    if len(expression.nodes) > design.max_nodes:
        return "NODE_LIMIT"
    if expression.input_lag_trading_days != design.authoring.strategy.input_lag_trading_days:
        return "INPUT_LAG_MISMATCH"
    if any(node.operator not in design.allowed_operators for node in expression.nodes):
        return "OPERATOR_UNSUPPORTED"
    if any(
        node.operator is SafeQlibOperator.FIELD and node.field_name != "adjusted_close"
        for node in expression.nodes
    ):
        return "FIELD_PIT_SOURCE_UNSUPPORTED"
    windows = [node for node in expression.nodes if node.window is not None]
    if isinstance(design, DiscoveryCompositionDesign):
        from quantos.application.discovery_composition import (
            composition_structural_hashes,
            expression_depth,
        )

        if expression_depth(expression) > design.max_depth:
            return "DEPTH_LIMIT"
        if any(node.window not in design.allowed_windows for node in windows):
            return "WINDOW_UNSUPPORTED"
        if structural_expression_hash(expression) not in composition_structural_hashes(design):
            return "OUTSIDE_SHARED_GRAMMAR"
        return None
    if len(windows) != 1:
        return "EXACTLY_ONE_WINDOW_REQUIRED"
    if windows[0].window not in design.allowed_windows:
        return "WINDOW_UNSUPPORTED"
    reachable = {expression.output_node_id}
    for node in reversed(expression.nodes):
        if node.node_id in reachable:
            reachable.update(node.inputs)
    if reachable != {node.node_id for node in expression.nodes}:
        return "UNUSED_NODES"
    if structural_expression_hash(expression) not in {
        structural_expression_hash(item) for item in baseline_expression_space(design)
    }:
        return "OUTSIDE_SHARED_GRAMMAR"
    return None


def _subtask(
    design: DiscoveryDesignContract, expression: SafeQlibExpressionSpec
) -> DiscoverySubtask:
    fingerprint = structural_expression_hash(expression)
    if isinstance(design, DiscoveryCompositionDesign):
        # Inventory order/names make parameter slots invariant to proposal node naming/order.
        expression = next(
            item
            for item in baseline_expression_space(design)
            if structural_expression_hash(item) == fingerprint
        )
        window_nodes = tuple(node for node in expression.nodes if node.window is not None)
        slots = tuple(
            ResearchTemplateParameterSlot(
                name=f"window_{index:03d}", node_id=node.node_id, field="window"
            )
            for index, node in enumerate(window_nodes)
        )
        template = ResearchFactorTemplateSpec(
            template_id=f"discovery-{fingerprint}",
            expression_schema_version=expression.schema_version,
            nodes=tuple(
                ResearchFactorTemplateNode(
                    node_id=n.node_id,
                    operator=n.operator,
                    inputs=n.inputs,
                    field_name=n.field_name,
                    window=None,
                )
                for n in expression.nodes
            ),
            output_node_id=expression.output_node_id,
            input_lag_trading_days=expression.input_lag_trading_days,
            parameter_slots=slots,
        )
        family = ResearchFamilySpec(
            family_id=f"discovery-{fingerprint}",
            research_question=design.research_question,
            hypothesis_hash=design.content_hash,
            factor_template_hash=template.content_hash,
            allowed_operators=design.allowed_operators,
            parameter_space=tuple(
                ParameterDimension(name=slot.name, values=(cast(int, node.window),))
                for slot, node in zip(slots, window_nodes, strict=True)
            ),
            declared_candidate_count=1,
        )
        return DiscoverySubtask(
            design_hash=design.content_hash,
            template=template,
            family=family,
            manifest=enumerate_research_family(family, template),
        )
    window_node = next(node for node in expression.nodes if node.window is not None)
    if window_node.window is None:
        raise ValueError("singleton template requires one bounded window")
    template = ResearchFactorTemplateSpec(
        template_id=f"discovery-{fingerprint}",
        expression_schema_version=expression.schema_version,
        nodes=tuple(
            ResearchFactorTemplateNode(
                node_id=node.node_id,
                operator=node.operator,
                inputs=node.inputs,
                field_name=node.field_name,
                window=None if node.node_id == window_node.node_id else node.window,
            )
            for node in expression.nodes
        ),
        output_node_id=expression.output_node_id,
        input_lag_trading_days=expression.input_lag_trading_days,
        parameter_slots=(
            ResearchTemplateParameterSlot(
                name="window", node_id=window_node.node_id, field="window"
            ),
        ),
    )
    family = ResearchFamilySpec(
        family_id=f"discovery-{fingerprint}",
        research_question=design.research_question,
        hypothesis_hash=design.content_hash,
        factor_template_hash=template.content_hash,
        allowed_operators=design.allowed_operators,
        parameter_space=(ParameterDimension(name="window", values=(window_node.window,)),),
        declared_candidate_count=1,
    )
    return DiscoverySubtask(
        design_hash=design.content_hash,
        template=template,
        family=family,
        manifest=enumerate_research_family(family, template),
    )


def build_discovery_batch(
    design: DiscoveryDesignContract,
    requests: tuple[GenerationRequest, ...],
    reservations: tuple[GenerationReservation, ...],
    responses: tuple[GenerationResponse, ...],
) -> DiscoveryBatch:
    """Freeze the entire attempt denominator, including interruptions and duplicates."""
    requests = tuple(sorted(requests, key=lambda item: item.method))
    if tuple(item.method for item in requests) != ("LLM", "RANDOM", "TEMPLATE"):
        raise ValueError("comparison requires exactly the three declared methods")
    request_by_hash = {item.content_hash: item for item in requests}
    for request in requests:
        if (
            request.design_hash != design.content_hash
            or request.input_hashes != design.context_hashes
            or request.max_attempts != design.evaluation_opportunities_per_method
        ):
            raise ValueError("generation escaped the shared design or evaluation opportunities")
    reservations = tuple(sorted(reservations, key=lambda item: (item.request_hash, item.ordinal)))
    if len({item.content_hash for item in reservations}) != len(reservations):
        raise ValueError("duplicate generation reservations")
    for request in requests:
        ordinals = [
            item.ordinal for item in reservations if item.request_hash == request.content_hash
        ]
        if ordinals != list(range(1, len(ordinals) + 1)) or len(ordinals) > request.max_attempts:
            raise ValueError("attempts must be continuous and bounded")
    if any(item.request_hash not in request_by_hash for item in reservations):
        raise ValueError("reservation is outside this comparison")
    responses = tuple(
        sorted(
            responses, key=lambda item: (item.reservation.request_hash, item.reservation.ordinal)
        )
    )
    response_by_reservation = {item.reservation.content_hash: item for item in responses}
    reservation_hashes = {item.content_hash for item in reservations}
    if len(response_by_reservation) != len(responses) or not set(response_by_reservation).issubset(
        reservation_hashes
    ):
        raise ValueError("response must bind exactly one reserved attempt")
    response_by_hash = {item.content_hash: item for item in responses}
    for reservation in reservations:
        if reservation.revision_of is not None:
            parent = response_by_hash.get(reservation.revision_of)
            if (
                parent is None
                or parent.reservation.request_hash != reservation.request_hash
                or (parent.reservation.ordinal >= reservation.ordinal)
            ):
                raise ValueError("revision must reference an earlier response in the same request")

    mappings: list[ProposalMapping] = []
    subtasks: list[DiscoverySubtask] = []
    representatives: dict[str, DiscoverySubtask] = {}
    for reservation in reservations:
        response = response_by_reservation.get(reservation.content_hash)
        expression = None
        subtask_hash = None
        if response is None:
            status, reason = "UNFINISHED", "NO_RESPONSE_CAPTURED"
        elif response.failure_code is not None:
            status, reason = "FAILED", response.failure_code
        elif len(response.text.encode("utf-8")) > design.max_output_bytes_per_attempt:
            status, reason = "REJECTED", "OUTPUT_LIMIT"
        else:
            try:
                expression = SafeQlibExpressionSpec.model_validate(json.loads(response.text))
            except (ValueError, TypeError, RecursionError):
                status, reason = "PARSE_FAILED", "INVALID_EXPRESSION_JSON"
            else:
                rejection = capability_rejection(design, expression)
                if rejection is not None:
                    status, reason = "REJECTED", rejection
                else:
                    structural = structural_expression_hash(expression)
                    representative = representatives.get(structural)
                    if representative is None:
                        representative = _subtask(design, expression)
                        representatives[structural] = representative
                        subtasks.append(representative)
                        status, reason = "ADMITTED", "STATIC_CAPABILITY_ADMITTED"
                    else:
                        status, reason = "DUPLICATE", "STRUCTURAL_DUPLICATE"
                    subtask_hash = representative.content_hash
        mappings.append(
            ProposalMapping(
                request_hash=reservation.request_hash,
                reservation_hash=reservation.content_hash,
                response_hash=None if response is None else response.content_hash,
                status=status,
                reason=reason,
                expression=expression,
                subtask_hash=subtask_hash,
            )
        )
    return DiscoveryBatch(
        design=design,
        requests=requests,
        reservations=reservations,
        responses=responses,
        mappings=tuple(mappings),
        subtasks=tuple(subtasks),
    )


def verify_discovery_batch(batch: DiscoveryBatch) -> None:
    rebuilt = build_discovery_batch(
        batch.design, batch.requests, batch.reservations, batch.responses
    )
    if rebuilt.canonical_bytes() != batch.canonical_bytes():
        raise ValueError(
            "frozen comparison mappings or singleton families differ from their origins"
        )
