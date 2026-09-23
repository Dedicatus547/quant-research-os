from __future__ import annotations

import pytest

from quantos.application import (
    CandidateEnumerationError,
    build_candidate_duplicate_evidence,
    enumerate_research_family,
    exact_expression_hash,
    structural_expression_hash,
)
from quantos.contracts import (
    CandidateDuplicateKind,
    ParameterDimension,
    ReasonCode,
    ResearchCandidateParameter,
    ResearchCandidateSpec,
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchFamilySpec,
    ResearchTemplateParameterSlot,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
)


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="delta-window-template-v1",
        expression_schema_version="safe-qlib-expression/v2",
        nodes=(
            ResearchFactorTemplateNode(
                node_id="price",
                operator=SafeQlibOperator.FIELD,
                field_name="adjusted_close",
            ),
            ResearchFactorTemplateNode(
                node_id="factor",
                operator=SafeQlibOperator.DELTA,
                inputs=("price",),
            ),
        ),
        output_node_id="factor",
        parameter_slots=(
            ResearchTemplateParameterSlot(name="window", node_id="factor", field="window"),
        ),
    )


def _family(
    template: ResearchFactorTemplateSpec,
    *,
    dimension_name: str = "window",
    values: tuple[object, ...] = (5, 2),
) -> ResearchFamilySpec:
    return ResearchFamilySpec(
        family_id="delta-window-family-v1",
        research_question="Does a frozen delta window generalize?",
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name=dimension_name, values=values),),
        declared_candidate_count=len(values),
    )


def _expression(*, renamed: bool) -> SafeQlibExpressionSpec:
    source = "source" if renamed else "price"
    output = "output" if renamed else "factor"
    return SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="renamed" if renamed else "original",
        nodes=(
            SafeExpressionNode(
                node_id=source,
                operator=SafeQlibOperator.FIELD,
                field_name="adjusted_close",
            ),
            SafeExpressionNode(
                node_id=output,
                operator=SafeQlibOperator.DELTA,
                inputs=(source,),
                window=2,
            ),
        ),
        output_node_id=output,
    )


def _candidate(value: int, expression: SafeQlibExpressionSpec) -> ResearchCandidateSpec:
    return ResearchCandidateSpec(
        candidate_id=f"candidate-{value:064x}",
        family_hash="2" * 64,
        factor_template_hash="3" * 64,
        parameters=(ResearchCandidateParameter(name="window", value=value),),
        expression=expression,
        exact_expression_hash=exact_expression_hash(expression),
        structural_expression_hash=structural_expression_hash(expression),
    )


def test_frozen_family_enumeration_is_complete_and_deterministic() -> None:
    template = _template()
    family = _family(template)

    first = enumerate_research_family(family, template)
    second = enumerate_research_family(family, template)

    assert first == second
    assert first.content_hash == second.content_hash
    assert tuple(item.parameters[0].value for item in first.candidates) == (2, 5)
    assert len(first.candidates) == family.declared_candidate_count
    assert not first.duplicate_evidence
    assert all(item.candidate_id.startswith("candidate-") for item in first.candidates)


def test_expression_fingerprints_distinguish_exact_names_but_normalize_structure() -> None:
    original = _expression(renamed=False)
    renamed = _expression(renamed=True)

    assert exact_expression_hash(original) != exact_expression_hash(renamed)
    assert structural_expression_hash(original) == structural_expression_hash(renamed)

    candidates = (_candidate(2, original), _candidate(3, renamed))
    evidence = build_candidate_duplicate_evidence(candidates)
    assert len(evidence) == 1
    assert evidence[0].kind is CandidateDuplicateKind.STRUCTURAL
    assert evidence[0].representative_candidate_hash == min(
        item.content_hash for item in candidates
    )
    assert set(evidence[0].duplicate_candidate_hashes) == {
        max(item.content_hash for item in candidates)
    }


def test_enumeration_rejects_unbound_template_slots_and_invalid_window_values() -> None:
    template = _template()
    family = _family(template)

    mismatched_template = template.model_copy(update={"template_id": "different-template"})
    with pytest.raises(CandidateEnumerationError) as corrupted:
        enumerate_research_family(family, mismatched_template)
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    wrong_dimension = _family(template, dimension_name="lookback")
    with pytest.raises(CandidateEnumerationError) as mismatched:
        enumerate_research_family(wrong_dimension, template)
    assert mismatched.value.reason_code is ReasonCode.SCHEMA_INVALID

    invalid_window = _family(template, values=(True, 5))
    with pytest.raises(CandidateEnumerationError) as invalid:
        enumerate_research_family(invalid_window, template)
    assert invalid.value.reason_code is ReasonCode.SCHEMA_INVALID


def test_template_contract_rejects_implicit_or_dangling_parameter_targets() -> None:
    with pytest.raises(ValueError, match="shape or parameter target"):
        ResearchFactorTemplateSpec(
            template_id="fixed-and-slotted-window",
            expression_schema_version="safe-qlib-expression/v2",
            nodes=(
                ResearchFactorTemplateNode(
                    node_id="price",
                    operator=SafeQlibOperator.FIELD,
                    field_name="adjusted_close",
                ),
                ResearchFactorTemplateNode(
                    node_id="factor",
                    operator=SafeQlibOperator.DELTA,
                    inputs=("price",),
                    window=2,
                ),
            ),
            output_node_id="factor",
            parameter_slots=(
                ResearchTemplateParameterSlot(name="window", node_id="factor", field="window"),
            ),
        )

    with pytest.raises(ValueError, match="unknown node"):
        ResearchFactorTemplateSpec(
            template_id="dangling-window",
            expression_schema_version="safe-qlib-expression/v2",
            nodes=(
                ResearchFactorTemplateNode(
                    node_id="price",
                    operator=SafeQlibOperator.FIELD,
                    field_name="adjusted_close",
                ),
            ),
            output_node_id="price",
            parameter_slots=(
                ResearchTemplateParameterSlot(
                    name="window",
                    node_id="ghost",
                    field="window",
                ),
            ),
        )

    with pytest.raises(ValueError, match="DSL v2 operators require a v2 factor template"):
        ResearchFactorTemplateSpec(
            template_id="v1-with-v2-operator",
            expression_schema_version="safe-qlib-expression/v1",
            nodes=(
                ResearchFactorTemplateNode(
                    node_id="price",
                    operator=SafeQlibOperator.FIELD,
                    field_name="adjusted_close",
                ),
                ResearchFactorTemplateNode(
                    node_id="factor",
                    operator=SafeQlibOperator.DELTA,
                    inputs=("price",),
                ),
            ),
            output_node_id="factor",
            parameter_slots=(
                ResearchTemplateParameterSlot(
                    name="window",
                    node_id="factor",
                    field="window",
                ),
            ),
        )
