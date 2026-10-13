"""Targeted offline successor grammar and binding tests; no market/model execution."""

import json
from pathlib import Path

import pytest

from quantos.application.data_qualified_release import parameter_window, variant_authoring
from quantos.application.discovery_admission import (
    _subtask,
    build_discovery_batch,
    capability_rejection,
    verify_discovery_batch,
)
from quantos.application.discovery_baselines import (
    baseline_expression_space,
    generate_sequential_baseline,
)
from quantos.application.discovery_execution import quote_discovery_workload
from quantos.application.enumeration import structural_expression_hash
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryBatch,
    DiscoveryCompositionDesign,
    DiscoveryDesign,
    DiscoveryDesignReader,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
)
from quantos.contracts.research import ExperimentAuthoringSpec

FIXTURE = Path(__file__).parents[1] / "fixtures/discovery_composition/design.json"


def composition_design():
    return DiscoveryCompositionDesign.model_validate_json(FIXTURE.read_bytes())


def requests(design):
    return tuple(
        GenerationRequest(
            design_hash=design.content_hash,
            method=method,
            max_attempts=design.evaluation_opportunities_per_method,
            seed=None if method == "LLM" else 1729,
            model_identifier="gpt-6.1-sol" if method == "LLM" else None,
            reasoning_effort="medium" if method == "LLM" else None,
            configuration_hash="a" * 64,
            prompt="Offline successor fixture, no actual call",
            input_hashes=design.context_hashes,
        )
        for method in ("LLM", "RANDOM", "TEMPLATE")
    )


def test_legacy_exact_bytes_and_successor_dispatch():
    value = composition_design().model_dump(mode="python")
    value["allowed_windows"] = (1, 5, 10, 20, 60, 10000)
    with pytest.raises(ValueError, match="finite profile set"):
        DiscoveryCompositionDesign.model_validate(value)
    original = (FIXTURE.parent.parent / "discovery_regression/design.json").read_bytes()
    assert DiscoveryDesignReader.model_validate_json(original).canonical_bytes() == original
    assert isinstance(
        DiscoveryDesignReader.model_validate_json(FIXTURE.read_bytes()), DiscoveryCompositionDesign
    )
    with pytest.raises(ValueError):
        DiscoveryDesign.model_validate_json(FIXTURE.read_bytes())


def test_common_finite_grammar_and_new_composition():
    design = composition_design()
    space = baseline_expression_space(design)
    assert len(space) == 555
    assert len({structural_expression_hash(e) for e in space}) == 555
    assert all(capability_rejection(design, e) is None for e in space)
    example = space[0]
    assert [n.window for n in example.nodes if n.window is not None] == [5, 1, 20]
    legacy = DiscoveryDesign.model_validate_json(
        (FIXTURE.parent.parent / "discovery_regression/design.json").read_bytes()
    )
    assert capability_rejection(legacy, example) == "NODE_LIMIT"
    assert (
        capability_rejection(design.model_copy(update={"max_depth": 3}), example) == "DEPTH_LIMIT"
    )


def test_singleton_maps_every_window_in_topological_order():
    design = composition_design()
    expression = baseline_expression_space(design)[0]
    task = _subtask(design, expression)
    assert tuple(p.name for p in task.family.parameter_space) == (
        "window_000",
        "window_001",
        "window_002",
    )
    assert tuple(p.values for p in task.family.parameter_space) == ((5,), (1,), (20,))
    candidate = task.manifest.candidates[0]
    assert structural_expression_hash(candidate.expression) == structural_expression_hash(
        expression
    )


def test_baselines_share_space_are_deterministic_and_no_replacement():
    design = composition_design()
    reqs = requests(design)
    policy = CompositionGenerationPolicy(
        design_hash=design.content_hash, request_hashes=tuple(r.content_hash for r in reqs)
    )
    for request in reqs[1:]:
        texts = generate_sequential_baseline(design, request, policy)
        assert texts == generate_sequential_baseline(design, request, policy)
        assert len(set(texts)) == 3
        if request.method == "TEMPLATE":
            assert json.loads(texts[0])["nodes"][-1]["operator"] == "divide"
    with pytest.raises(ValueError):
        generate_sequential_baseline(design, reqs[1], policy.model_copy(update={"random_seed": 2}))


def test_quote_and_frozen_batch_roundtrip_accept_multi_window():
    design = composition_design()
    reqs = requests(design)
    expr = baseline_expression_space(design)[0]
    reservations = tuple(
        GenerationReservation(request_hash=r.content_hash, ordinal=1) for r in reqs
    )
    responses = tuple(
        GenerationResponse(
            reservation=r,
            text=expr.canonical_bytes().decode(),
            producer="OFFLINE_IMPORT" if i == 0 else "BASELINE",
        )
        for i, r in enumerate(reservations)
    )
    batch = build_discovery_batch(design, reqs, reservations, responses)
    verify_discovery_batch(batch)
    loaded = DiscoveryBatch.model_validate_json(batch.canonical_bytes())
    assert isinstance(loaded.design, DiscoveryCompositionDesign)
    assert quote_discovery_workload(loaded) > 0
    assert len(loaded.subtasks) == 1


def test_explicit_variant_anchor_preserves_other_windows_and_old_rejection():
    design = composition_design()
    expression = baseline_expression_space(design)[0]
    payload = design.authoring.model_dump(mode="python")
    payload["expression"] = expression
    authoring = ExperimentAuthoringSpec.model_validate(payload)
    with pytest.raises(ValueError):
        parameter_window(authoring)
    with pytest.raises(ValueError):
        variant_authoring(authoring, window=10)
    assert parameter_window(authoring, window_node_id="short_return") == 5
    variant = variant_authoring(authoring, window=10, window_node_id="short_return")
    assert [n.window for n in variant.expression.nodes if n.window is not None] == [10, 1, 20]


def test_node_order_and_names_do_not_change_singleton_slots_or_sensitivity():
    design = composition_design()
    expression = baseline_expression_space(design)[0]
    # Independently computable inner-return can precede short-return in a proposal.
    reordered = expression.model_copy(
        update={
            "nodes": (
                expression.nodes[0],
                expression.nodes[2],
                expression.nodes[1],
                expression.nodes[3],
                expression.nodes[4],
            )
        }
    )
    assert structural_expression_hash(reordered) == structural_expression_hash(expression)
    assert _subtask(design, reordered) == _subtask(design, expression)


def test_successor_rejects_legacy_policy_even_with_matching_hashes():
    from quantos.contracts.discovery import SequentialDiscoveryBatch, SequentialGenerationPolicy

    design = composition_design()
    reqs = requests(design)
    batch = build_discovery_batch(design, reqs, (), ())
    policy = SequentialGenerationPolicy(
        design_hash=design.content_hash,
        request_hashes=tuple(r.content_hash for r in reqs),
        max_attempts_per_method=3,
    )
    with pytest.raises(ValueError, match="profiles differ"):
        SequentialDiscoveryBatch(policy=policy, batch=batch, attempts=())
