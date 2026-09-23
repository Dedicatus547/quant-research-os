from __future__ import annotations

import pytest

from quantos.application import (
    CandidateEnumerationError,
    build_candidate_duplicate_evidence,
    enumerate_research_family,
    exact_expression_hash,
    structural_expression_hash,
    verify_candidate_enumeration_manifest,
)
from quantos.contracts import (
    CandidateDuplicateKind,
    CandidateEnumerationManifest,
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


def test_structural_fingerprint_ignores_topological_listing_but_preserves_input_order() -> None:
    price = SafeExpressionNode(
        node_id="price", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
    )
    volume = SafeExpressionNode(
        node_id="volume", operator=SafeQlibOperator.FIELD, field_name="volume"
    )
    output = SafeExpressionNode(
        node_id="result", operator=SafeQlibOperator.ADD, inputs=("price", "volume")
    )
    first = SafeQlibExpressionSpec(
        expression_id="first", nodes=(price, volume, output), output_node_id="result"
    )
    reordered = first.model_copy(update={"nodes": (volume, price, output)})
    swapped = first.model_copy(
        update={
            "nodes": (
                price,
                volume,
                output.model_copy(update={"inputs": ("volume", "price")}),
            )
        }
    )
    assert structural_expression_hash(first) == structural_expression_hash(reordered)
    assert structural_expression_hash(first) != structural_expression_hash(swapped)

    unused = SafeExpressionNode(
        node_id="unused", operator=SafeQlibOperator.FIELD, field_name="volume"
    )
    with_unused = SafeQlibExpressionSpec(
        expression_id="with-unused",
        nodes=(price, unused, volume, output),
        output_node_id="result",
    )
    reordered_unused = SafeQlibExpressionSpec(
        expression_id="reordered-unused",
        nodes=(unused, volume, price, output),
        output_node_id="result",
    )
    assert structural_expression_hash(with_unused) == structural_expression_hash(reordered_unused)

    shared = SafeExpressionNode(
        node_id="shared", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
    )
    copy = SafeExpressionNode(
        node_id="copy", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
    )
    left = SafeExpressionNode(node_id="left", operator=SafeQlibOperator.ABS, inputs=("shared",))
    right = SafeExpressionNode(node_id="right", operator=SafeQlibOperator.ABS, inputs=("copy",))
    shared_first = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="shared-first",
        nodes=(shared, copy, left, right),
        output_node_id="shared",
    )
    copy_first = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="copy-first",
        nodes=(copy, shared, right, left),
        output_node_id="shared",
    )
    assert structural_expression_hash(shared_first) == structural_expression_hash(copy_first)


def test_multi_dimensional_family_enumerates_entire_cartesian_product() -> None:
    template = ResearchFactorTemplateSpec(
        template_id="two-window-template",
        expression_schema_version="safe-qlib-expression/v2",
        nodes=(
            ResearchFactorTemplateNode(
                node_id="price", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
            ),
            ResearchFactorTemplateNode(
                node_id="delta", operator=SafeQlibOperator.DELTA, inputs=("price",)
            ),
            ResearchFactorTemplateNode(
                node_id="smooth", operator=SafeQlibOperator.ROLLING_MEAN, inputs=("delta",)
            ),
        ),
        output_node_id="smooth",
        parameter_slots=(
            ResearchTemplateParameterSlot(name="lag", node_id="delta", field="window"),
            ResearchTemplateParameterSlot(name="window", node_id="smooth", field="window"),
        ),
    )
    family = ResearchFamilySpec(
        family_id="two-window-family",
        research_question="Does this two-window family generalize?",
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(
            sorted(
                (
                    SafeQlibOperator.DELTA,
                    SafeQlibOperator.FIELD,
                    SafeQlibOperator.ROLLING_MEAN,
                ),
                key=str,
            )
        ),
        parameter_space=(
            ParameterDimension(name="lag", values=(4, 2)),
            ParameterDimension(name="window", values=(5, 3)),
        ),
        declared_candidate_count=4,
    )
    manifest = enumerate_research_family(family, template)
    assert [
        tuple(item.value for item in candidate.parameters) for candidate in manifest.candidates
    ] == [
        (2, 3),
        (2, 5),
        (4, 3),
        (4, 5),
    ]
    assert len({candidate.content_hash for candidate in manifest.candidates}) == 4
    verify_candidate_enumeration_manifest(family, template, manifest)


@pytest.mark.parametrize(
    "change",
    [
        {"candidate_id": "candidate-" + "f" * 64},
        {"exact_expression_hash": "f" * 64},
        {"structural_expression_hash": "f" * 64},
        {"expression": _expression(renamed=True)},
    ],
)
def test_manifest_verifier_rejects_candidate_self_reports(change: dict[str, object]) -> None:
    template = _template()
    family = _family(template)
    manifest = enumerate_research_family(family, template)
    candidates = (manifest.candidates[0].model_copy(update=change), *manifest.candidates[1:])
    tampered = manifest.model_copy(update={"candidates": candidates})
    with pytest.raises(CandidateEnumerationError) as rejected:
        verify_candidate_enumeration_manifest(family, template, tampered)
    assert rejected.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_manifest_verifier_rejects_missing_duplicate_evidence() -> None:
    template = _template()
    family = _family(template)
    candidates = (
        _candidate(2, _expression(renamed=False)),
        _candidate(3, _expression(renamed=True)),
    )
    manifest = CandidateEnumerationManifest(
        family_hash=candidates[0].family_hash,
        factor_template_hash=candidates[0].factor_template_hash,
        declared_candidate_count=2,
        candidates=candidates,
        duplicate_evidence=(),
    )
    with pytest.raises(CandidateEnumerationError, match="duplicate evidence") as rejected:
        verify_candidate_enumeration_manifest(family, template, manifest)
    assert rejected.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


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
            template_id="field-with-window-slot",
            expression_schema_version="safe-qlib-expression/v2",
            nodes=(
                ResearchFactorTemplateNode(
                    node_id="price", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
                ),
            ),
            output_node_id="price",
            parameter_slots=(
                ResearchTemplateParameterSlot(name="window", node_id="price", field="window"),
            ),
        )

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
