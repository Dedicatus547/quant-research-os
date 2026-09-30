"""Management recipes are finite, typed minima, never mutable installed policy."""

from __future__ import annotations

import pytest

from quantos.contracts.campaign import ResearchBudgetSpec
from quantos.contracts.hosted import HostedBudgetPolicy
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES, budget_case_specs


def _base() -> tuple[ResearchBudgetSpec, HostedBudgetPolicy]:
    return (
        ResearchBudgetSpec(
            budget_id="p14-dq-two-candidate-budget-v1",
            max_trials=2,
            max_distinct_candidates=2,
            max_agent_runs=2,
            max_executions=2,
            max_validation_rounds=2,
            max_compute_seconds=100_000,
        ),
        HostedBudgetPolicy(
            max_requests=2,
            max_unique_submissions=4,
            max_submissions_per_request=2,
            max_response_bytes=262144,
            max_proposal_bytes=262144,
            max_request_bytes=1048576,
            request_ttl_seconds=3600,
        ),
    )


@pytest.mark.parametrize("case", tuple(HOSTED_BUDGET_CASES))
def test_budget_minima_remain_consistent_and_do_not_mutate_baseline(case: str) -> None:
    research, transport = _base()
    before = research.canonical_bytes(), transport.canonical_bytes()
    bounded, channel = budget_case_specs(case, research, transport)
    assert bounded.content_hash != research.content_hash
    assert channel.max_requests <= bounded.max_agent_runs
    assert bounded.max_validation_rounds <= bounded.max_executions <= bounded.max_trials
    assert bounded.max_distinct_candidates <= bounded.max_trials
    for field in (
        "max_trials",
        "max_distinct_candidates",
        "max_agent_runs",
        "max_executions",
        "max_validation_rounds",
        "max_compute_seconds",
    ):
        assert 1 <= getattr(bounded, field) <= getattr(research, field)
    assert (research.canonical_bytes(), transport.canonical_bytes()) == before
    # Repeated management authoring is deterministic, never an installed reset.
    assert budget_case_specs(case, research, transport) == (bounded, channel)


@pytest.mark.parametrize("case", ("../trial_allowance", "compute_allowance;exec", "auto", ""))
def test_unknown_recipes_cannot_become_management_policy_editors(case: str) -> None:
    with pytest.raises(ValueError, match="unknown fixed"):
        budget_case_specs(case, *_base())


@pytest.mark.parametrize(
    "field,value",
    (
        ("max_trials", 3),
        ("max_distinct_candidates", 1),
        ("max_agent_runs", 1),
        ("max_executions", 1),
        ("max_compute_seconds", 50),
        ("max_requests", 1),
        ("max_unique_submissions", 2),
        ("max_submissions_per_request", 1),
    ),
)
def test_other_base_policies_cannot_silently_use_reviewed_minimum_recipes(
    field: str, value: int
) -> None:
    research, transport = _base()
    if field in ResearchBudgetSpec.model_fields:
        change = {field: value}
        if field == "max_executions":
            change["max_validation_rounds"] = value
        research = ResearchBudgetSpec.model_validate(
            {**research.model_dump(mode="python"), **change}
        )
    else:
        transport = HostedBudgetPolicy.model_validate(
            {**transport.model_dump(mode="python"), field: value}
        )
    with pytest.raises(ValueError, match="frozen two-candidate baseline"):
        budget_case_specs("trial_allowance", research, transport)
