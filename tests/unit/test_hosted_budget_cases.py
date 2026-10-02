"""Management recipes are finite, typed minima, never mutable installed policy."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def test_derived_budget_campaigns_keep_execution_label_and_distinct_frozen_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_hosted_input_bootstrap import _inputs

    from quantos.contracts.autonomous import P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
    from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs
    from quantos.infrastructure.hosted_budget_cases import derive_hosted_budget_case

    input_root = tmp_path / "inputs"
    baseline, _ = _inputs(input_root, monkeypatch)
    baseline = HostedFrozenBusinessInputs.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "selection_finalization_profile": P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
        }
    )
    original = baseline.canonical_bytes()
    variants = [
        derive_hosted_budget_case(baseline, case, input_root=input_root)
        for case in HOSTED_BUDGET_CASES
    ]
    assert baseline.canonical_bytes() == original
    assert len({variant.campaign.content_hash for variant in variants}) == len(variants)
    for case, variant in zip(HOSTED_BUDGET_CASES, variants, strict=True):
        assert variant.campaign.campaign_id == baseline.campaign.campaign_id
        assert variant.campaign.content_hash != baseline.campaign.content_hash
        assert variant.campaign.budget_hash == variant.research_budget.content_hash
        assert variant.research_budget.budget_id == f"hm-q06-{case}-budget-v1"
        assert variant.selection_plan.campaign_hash == variant.campaign.content_hash
        assert variant.manifest == baseline.manifest
        assert variant.execution_bindings == baseline.execution_bindings
        assert derive_hosted_budget_case(baseline, case, input_root=input_root) == variant


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


@pytest.mark.parametrize("case", tuple(HOSTED_BUDGET_CASES))
def test_baseline_budget_cannot_be_run_as_an_installed_variant(tmp_path: Path, case: str) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError
    from quantos.infrastructure.hosted_manager import run_managed_budget_case

    deployment = SimpleNamespace(
        root=tmp_path,
        bundle=SimpleNamespace(research_budget=_base()[0]),
    )
    with pytest.raises(ArtifactIntegrityError, match="separately frozen"):
        run_managed_budget_case(deployment, case)
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.parametrize("case", ("../trial_allowance", "execution_allowance;exec", "auto", ""))
def test_unregistered_budget_deployments_reject_before_read_or_write(
    tmp_path: Path, case: str
) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError
    from quantos.infrastructure.hosted_budget_deployment import (
        read_managed_budget_deployment,
        stage_managed_budget_deployment,
    )
    from quantos.infrastructure.hosted_budget_probe import run_budget_probe
    from quantos.infrastructure.hosted_manager import run_managed_budget_case

    untrusted = SimpleNamespace(root=tmp_path)
    with pytest.raises(ValueError, match="unknown fixed"):
        stage_managed_budget_deployment(
            untrusted, case, tmp_path, base_python=tmp_path, dependency_site=tmp_path
        )
    with pytest.raises(ArtifactIntegrityError, match="unknown fixed"):
        read_managed_budget_deployment(untrusted, case, "0" * 64)
    with pytest.raises(ValueError, match="unknown fixed"):
        run_managed_budget_case(untrusted, case)
    with pytest.raises(ValueError, match="unknown fixed"):
        run_budget_probe("0" * 64, case, authority_root=tmp_path, channel_root=tmp_path)
    assert tuple(tmp_path.iterdir()) == ()
