"""Deterministic P14b frozen-family enumeration and expression fingerprinting."""

from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Never

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ResearchFamilySpec
from quantos.contracts.enumeration import (
    CandidateDuplicateEvidence,
    CandidateDuplicateKind,
    CandidateEnumerationManifest,
    ResearchCandidateParameter,
    ResearchCandidateSpec,
    ResearchFactorTemplateSpec,
)
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec
from quantos.contracts.status import ReasonCode


class CandidateEnumerationError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _raise(reason_code: ReasonCode, message: str) -> Never:
    raise CandidateEnumerationError(reason_code, message)


def exact_expression_hash(expression: SafeQlibExpressionSpec) -> str:
    """Hash an expression while ignoring only its presentation-level expression_id."""

    return sha256_bytes(
        canonical_json_bytes(
            {
                "input_lag_trading_days": expression.input_lag_trading_days,
                "nodes": expression.nodes,
                "output_node_id": expression.output_node_id,
                "schema_version": "exact-expression-fingerprint/v1",
                "source_schema_version": expression.schema_version,
            }
        )
    )


def structural_expression_hash(expression: SafeQlibExpressionSpec) -> str:
    """Hash topology and operator parameters after deterministic node-ID normalization."""

    normalized_ids = {node.node_id: f"n{index:04d}" for index, node in enumerate(expression.nodes)}
    nodes = tuple(
        {
            "field_name": node.field_name,
            "inputs": tuple(normalized_ids[item] for item in node.inputs),
            "node_id": normalized_ids[node.node_id],
            "operator": node.operator,
            "window": node.window,
        }
        for node in expression.nodes
    )
    return sha256_bytes(
        canonical_json_bytes(
            {
                "input_lag_trading_days": expression.input_lag_trading_days,
                "nodes": nodes,
                "output_node_id": normalized_ids[expression.output_node_id],
                "schema_version": "structural-expression-fingerprint/v1",
                "source_schema_version": expression.schema_version,
            }
        )
    )


def _instantiate(
    template: ResearchFactorTemplateSpec,
    parameters: tuple[ResearchCandidateParameter, ...],
) -> SafeQlibExpressionSpec:
    values = {item.name: item.value for item in parameters}
    slots = {item.node_id: item.name for item in template.parameter_slots}
    nodes: list[SafeExpressionNode] = []
    for node in template.nodes:
        window = node.window
        parameter_name = slots.get(node.node_id)
        if parameter_name is not None:
            candidate = values[parameter_name]
            if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate <= 0:
                _raise(
                    ReasonCode.SCHEMA_INVALID,
                    "window template parameters must be positive integers",
                )
            window = candidate
        try:
            nodes.append(
                SafeExpressionNode(
                    node_id=node.node_id,
                    operator=node.operator,
                    inputs=node.inputs,
                    field_name=node.field_name,
                    window=window,
                )
            )
        except ValueError as error:
            raise CandidateEnumerationError(
                ReasonCode.SCHEMA_INVALID,
                "factor template instantiation is invalid",
            ) from error

    parameter_hash = sha256_bytes(canonical_json_bytes(parameters))
    try:
        return SafeQlibExpressionSpec(
            schema_version=template.expression_schema_version,
            expression_id=f"candidate_{parameter_hash}",
            nodes=tuple(nodes),
            output_node_id=template.output_node_id,
            input_lag_trading_days=template.input_lag_trading_days,
        )
    except ValueError as error:
        raise CandidateEnumerationError(
            ReasonCode.SCHEMA_INVALID,
            "instantiated candidate expression is invalid",
        ) from error


def build_candidate_duplicate_evidence(
    candidates: tuple[ResearchCandidateSpec, ...],
) -> tuple[CandidateDuplicateEvidence, ...]:
    evidence: list[CandidateDuplicateEvidence] = []
    for kind, attribute in (
        (CandidateDuplicateKind.EXACT, "exact_expression_hash"),
        (CandidateDuplicateKind.STRUCTURAL, "structural_expression_hash"),
    ):
        groups: dict[str, list[ResearchCandidateSpec]] = defaultdict(list)
        for candidate in candidates:
            groups[getattr(candidate, attribute)].append(candidate)
        for fingerprint, group in sorted(groups.items()):
            if len(group) < 2:
                continue
            if (
                kind is CandidateDuplicateKind.STRUCTURAL
                and len({item.exact_expression_hash for item in group}) == 1
            ):
                continue
            hashes = sorted(item.content_hash for item in group)
            evidence.append(
                CandidateDuplicateEvidence(
                    kind=kind,
                    fingerprint_hash=fingerprint,
                    representative_candidate_hash=hashes[0],
                    duplicate_candidate_hashes=tuple(hashes[1:]),
                )
            )
    return tuple(sorted(evidence, key=lambda item: (str(item.kind), item.fingerprint_hash)))


def enumerate_research_family(
    family: ResearchFamilySpec,
    template: ResearchFactorTemplateSpec,
) -> CandidateEnumerationManifest:
    """Enumerate the complete frozen Cartesian family with no mutation or inferred slots."""

    if family.factor_template_hash != template.content_hash:
        _raise(
            ReasonCode.ARTIFACT_CORRUPTED,
            "research family does not bind this factor template",
        )
    dimension_names = tuple(item.name for item in family.parameter_space)
    slot_names = tuple(item.name for item in template.parameter_slots)
    if dimension_names != slot_names:
        _raise(
            ReasonCode.SCHEMA_INVALID,
            "research family dimensions do not exactly match explicit template slots",
        )
    template_operators = {item.operator for item in template.nodes}
    if not template_operators.issubset(family.allowed_operators):
        _raise(
            ReasonCode.SCHEMA_INVALID,
            "factor template escapes the family operator allowlist",
        )

    ordered_values = tuple(
        tuple(sorted(item.values, key=canonical_json_bytes)) for item in family.parameter_space
    )
    candidates: list[ResearchCandidateSpec] = []
    for values in product(*ordered_values):
        parameters = tuple(
            ResearchCandidateParameter(name=dimension.name, value=value)
            for dimension, value in zip(family.parameter_space, values, strict=True)
        )
        expression = _instantiate(template, parameters)
        exact = exact_expression_hash(expression)
        structural = structural_expression_hash(expression)
        identity = sha256_bytes(
            canonical_json_bytes(
                {
                    "exact_expression_hash": exact,
                    "family_hash": family.content_hash,
                    "factor_template_hash": template.content_hash,
                    "parameters": parameters,
                    "schema_version": "research-candidate-identity/v1",
                    "structural_expression_hash": structural,
                }
            )
        )
        candidates.append(
            ResearchCandidateSpec(
                candidate_id=f"candidate-{identity}",
                family_hash=family.content_hash,
                factor_template_hash=template.content_hash,
                parameters=parameters,
                expression=expression,
                exact_expression_hash=exact,
                structural_expression_hash=structural,
            )
        )
    ordered_candidates = tuple(
        sorted(candidates, key=lambda item: canonical_json_bytes(item.parameters))
    )
    if len(ordered_candidates) != family.declared_candidate_count:
        _raise(
            ReasonCode.SCHEMA_INVALID,
            "enumeration did not cover the frozen denominator",
        )
    return CandidateEnumerationManifest(
        family_hash=family.content_hash,
        factor_template_hash=template.content_hash,
        declared_candidate_count=family.declared_candidate_count,
        candidates=ordered_candidates,
        duplicate_evidence=build_candidate_duplicate_evidence(ordered_candidates),
    )
