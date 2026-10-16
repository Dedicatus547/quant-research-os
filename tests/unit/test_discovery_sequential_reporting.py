"""Offline prefix and reporting regressions; no model entry or scientific execution."""

import json
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_offline_regression import requests

from quantos.application import discovery_generation_report as reporting
from quantos.application.discovery_baselines import baseline_expression_space
from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_sequential import build_generation_history
from quantos.contracts.discovery import (
    GenerationReservation,
    GenerationResponse,
    SequentialGenerationPolicy,
)


def sequential_inputs(design):
    reqs = tuple(
        r.model_copy(update={"seed": None if r.method == "LLM" else 1729}) for r in requests(design)
    )
    policy = SequentialGenerationPolicy(
        design_hash=design.content_hash,
        request_hashes=tuple(r.content_hash for r in reqs),
        max_attempts_per_method=2,
    )
    return reqs, policy


@pytest.mark.parametrize(
    "second,status",
    [
        ("duplicate", "DUPLICATE"),
        ("parse", "PARSE_FAILED"),
        ("failure", "FAILED"),
        ("limit", "REJECTED"),
        ("capability", "REJECTED"),
        ("missing", "UNFINISHED"),
    ],
)
def test_exact_method_prefix_retains_unfinished_failure_and_duplicates(design, second, status):
    reqs, policy = sequential_inputs(design)
    request = reqs[0]
    reservations = tuple(
        GenerationReservation(request_hash=request.content_hash, ordinal=i) for i in (1, 2)
    )
    text = baseline_expression_space(design)[0].canonical_bytes().decode()
    responses = [
        GenerationResponse(reservation=reservations[0], text=text, producer="OFFLINE_IMPORT")
    ]
    if second != "missing":
        captured = text
        if second == "parse":
            captured = "{"
        elif second == "limit":
            captured = "é" * (design.max_output_bytes_per_attempt // 2 + 1)
        elif second == "capability":
            altered = json.loads(text)
            altered["input_lag_trading_days"] += 1
            captured = json.dumps(altered)
        responses.append(
            GenerationResponse(
                reservation=reservations[1],
                text=captured,
                producer="OFFLINE_IMPORT",
                failure_code="CAPTURE_FAILED" if second == "failure" else None,
            )
        )
    history = build_generation_history(design, request, policy, reservations, tuple(responses))
    assert [e.status for e in history.entries] == ["ADMITTED", status]
    if second == "duplicate":
        assert history.entries[0].structural_hash == history.entries[1].structural_hash
    if second == "missing":
        assert history.entries[-1].response_hash is None
    for bad_reservations, bad_responses in (
        (reservations[1:], tuple(responses)),
        (reservations, tuple(responses + responses[:1])),
        (reservations[:1], tuple(responses[1:2])),
    ):
        if not bad_responses and bad_reservations == reservations[:1]:
            continue
        with pytest.raises(ValueError, match="history"):
            build_generation_history(design, request, policy, bad_reservations, bad_responses)
    with pytest.raises(ValueError, match="policy or method"):
        build_generation_history(design, reqs[1], policy, reservations, tuple(responses))


@pytest.fixture
def frozen_sequential(design, durable):
    reqs, policy = sequential_inputs(design)
    store = GenerationStore(durable / "sequential")
    store.save_sequential_policy(policy)
    for request in reqs:
        store.save_request(design, request)
        reservation = store.reserve(request)
        if request.method == "LLM":
            store.complete(
                request, reservation, "invalid json", producer="OFFLINE_IMPORT", wall_seconds=0.25
            )
        else:
            # A missing response is frozen as unknown rather than a fabricated call.
            store.reserve(request)
    return store, store.freeze(design)


def test_verified_generation_counts_keep_null_costs_and_original_opportunities(frozen_sequential):
    store, wrapper = frozen_sequential
    report = reporting.build_generation_analysis(wrapper, store)
    counts = report["counts"]
    assert counts["candidate_opportunities"] == {"granted": 6, "occupied": 5}
    assert counts["scientific_execution"]["status"] == "NOT_OBSERVED"
    entries = counts["management_model_entries"]
    assert entries["confirmed"] == 0 and entries["confirmed_zero_slots"] == 1
    assert entries["unknown_slots"] == 4 and entries["observable_retries"] is None
    llm = next(row for row in counts["methods"] if row["method"] == "LLM")
    assert llm["unoccupied_opportunities"] == 1
    assert llm["costs"]["wall_seconds"]["total"] == 0.25
    assert llm["costs"]["monetary_cost"]["total"] is None
    assert reporting._observed_total([])["total"] is None
    assert reporting._observed_total([0, None]) == {
        "total": None,
        "observed_total": 0,
        "observed_items": 1,
        "items": 2,
    }


@pytest.mark.parametrize(
    "attempts,expected_status,total,resumes",
    [
        ([1, 2], "OBSERVED_COMPARISON", 3, 1),
        ([None, 1], "PARTIALLY_OBSERVED_COMPARISON", None, None),
        ([True, 1], "PARTIALLY_OBSERVED_COMPARISON", None, None),
    ],
)
def test_comparison_counts_distinguish_unobserved_and_zero(
    attempts, expected_status, total, resumes
):
    wrapper = SimpleNamespace(
        batch=SimpleNamespace(
            content_hash="batch", subtasks=[SimpleNamespace(content_hash=k) for k in ("a", "b")]
        )
    )
    tasks = [
        {"subtask_hash": key, "execution_attempt_count": value}
        for key, value in zip(("a", "b"), attempts, strict=True)
    ]
    comparison = {
        "batch_hash": "batch",
        "costs": {"task_measurements": tasks, "batch_attempt_count": 1},
    }
    result = reporting.attach_verified_comparison_counts(
        {"original": "preserved"}, wrapper, comparison
    )
    science = result["scientific_execution"]
    assert science["status"] == expected_status
    assert science["attempt_count"] == total and science["resume_count"] == resumes
    assert result["original"] == "preserved"
    assert comparison["costs"]["task_measurements"] == tasks


@pytest.mark.parametrize(
    "damage", ["batch", "costs", "tasks", "kind", "identity", "duplicate", "set"]
)
def test_comparison_counts_reject_unbound_or_duplicate_measurements(damage):
    wrapper = SimpleNamespace(
        batch=SimpleNamespace(content_hash="batch", subtasks=[SimpleNamespace(content_hash="a")])
    )
    report = {"batch_hash": "batch", "costs": {"task_measurements": [{"subtask_hash": "a"}]}}
    if damage == "batch":
        report["batch_hash"] = "other"
    elif damage == "costs":
        report["costs"] = None
    elif damage == "tasks":
        report["costs"]["task_measurements"] = {}
    elif damage == "kind":
        report["costs"]["task_measurements"] = [None]
    elif damage == "identity":
        report["costs"]["task_measurements"] = [{}]
    elif damage == "duplicate":
        report["costs"]["task_measurements"] *= 2
    else:
        report["costs"]["task_measurements"] = []
    with pytest.raises(ValueError, match="comparison"):
        reporting.attach_verified_comparison_counts({}, wrapper, report)
