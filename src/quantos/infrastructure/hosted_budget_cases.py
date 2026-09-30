"""Finite management-only Q06 recipes, frozen before installation or requests.

Budget variants create new campaign, plan and bundle identities. They cannot
alter an existing service policy, provide model provenance or award Q06.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from quantos.application.campaign_selection import CampaignSelectionService, publish_selection_plan
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.contracts.autonomous import (
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousCampaignPolicy,
)
from quantos.contracts.campaign import ResearchBudgetSpec, ResearchCampaignSpec
from quantos.contracts.hosted import HostedBudgetPolicy
from quantos.contracts.hosted_inputs import HostedCampaignRecipe, HostedFrozenBusinessInputs


@dataclass(frozen=True)
class HostedBudgetCase:
    research_limits: tuple[tuple[str, int], ...] = ()
    transport_limits: tuple[tuple[str, int], ...] = ()
    action: Literal["schema_invalid", "reject_frames", "global_cap", "native_candidate"] = (
        "schema_invalid"
    )
    expected_reason: str = "BUDGET_EXHAUSTED"
    native_execution: bool = False


HOSTED_BUDGET_CASES = MappingProxyType(
    {
        "request_allowance": HostedBudgetCase(
            transport_limits=(("max_requests", 1),), expected_reason="PROTOCOL_EXHAUSTED"
        ),
        "research_attempts": HostedBudgetCase(
            research_limits=(("max_agent_runs", 1),),
            transport_limits=(("max_requests", 1),),
        ),
        "campaign_submissions": HostedBudgetCase(
            transport_limits=(("max_unique_submissions", 2),),
            action="global_cap",
            expected_reason="PROTOCOL_EXHAUSTED",
        ),
        "request_submissions": HostedBudgetCase(
            action="reject_frames", expected_reason="PROTOCOL_EXHAUSTED"
        ),
        "trial_allowance": HostedBudgetCase(
            research_limits=(
                ("max_trials", 1),
                ("max_distinct_candidates", 1),
                ("max_executions", 1),
                ("max_validation_rounds", 1),
            ),
        ),
        "execution_allowance": HostedBudgetCase(
            research_limits=(("max_executions", 1), ("max_validation_rounds", 1)),
            action="native_candidate",
            native_execution=True,
        ),
        "compute_allowance": HostedBudgetCase(
            research_limits=(("max_compute_seconds", 1),),
            action="native_candidate",
            expected_reason="RESEARCH_RESERVATION_EXHAUSTED",
        ),
    }
)


def budget_case_specs(
    case: str, research: ResearchBudgetSpec, transport: HostedBudgetPolicy
) -> tuple[ResearchBudgetSpec, HostedBudgetPolicy]:
    """Apply one fixed recipe through the existing typed budget validators."""
    try:
        recipe = HOSTED_BUDGET_CASES[case]
    except KeyError as error:
        raise ValueError("unknown fixed hosted budget case") from error
    # These are minima for the frozen two-candidate fixture, not a general policy
    # editor. A different base must have its own reviewed finite recipes.
    if (
        (research.max_trials, research.max_distinct_candidates, research.max_agent_runs)
        != (2, 2, 2)
        or (research.max_executions, research.max_validation_rounds) != (2, 2)
        or research.max_compute_seconds != 100_000
        or (transport.max_requests, transport.max_unique_submissions) != (2, 4)
        or transport.max_submissions_per_request != 2
    ):
        raise ValueError("Q06 budget recipes require the frozen two-candidate baseline")
    bounded_research = ResearchBudgetSpec.model_validate(
        {
            **research.model_dump(mode="python"),
            **dict(recipe.research_limits),
            "budget_id": f"hm-q06-{case}-budget-v1",
        }
    )
    bounded_transport = HostedBudgetPolicy.model_validate(
        {**transport.model_dump(mode="python"), **dict(recipe.transport_limits)}
    )
    return bounded_research, bounded_transport


def derive_hosted_budget_case(
    bundle: HostedFrozenBusinessInputs,
    case: str,
    *,
    input_root: Path,
) -> HostedFrozenBusinessInputs:
    """Read-only derivation of a finite B variant and native activation/plan events.

    The caller authors the clean baseline B and verifies its input bytes first.
    This function never mutates it, its seed Ledger or an installed deployment.
    """
    research, transport = budget_case_specs(
        case, bundle.research_budget, bundle.hosted_recipe.hosted_budget
    )
    if (
        bundle.selection_finalization_profile != P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
        or len(bundle.manifest.candidates) != 2
        or not bundle.code_provenance.worktree_clean
    ):
        raise ValueError("Q06 recipes require clean frozen DQ business inputs")
    campaign = ResearchCampaignSpec.model_validate(
        {
            **bundle.campaign.model_dump(mode="python"),
            "campaign_id": f"hm-q06-{case}-campaign-v1",
            "budget_hash": research.content_hash,
        }
    )
    selection = CampaignSelectionService(
        campaign,
        bundle.family,
        research,
        bundle.template,
        bundle.manifest,
        bundle.multiple_testing_policy,
        bundle.selection_policy,
        input_root / bundle.qlib_view_directory,
        (),
    )
    plan = selection.build_plan()
    governor = ResearchCampaignGovernor(bundle.family, bundle.template, bundle.manifest)
    activation = governor.activate(
        campaign,
        bundle.family,
        research,
        (),
        event_id=uuid5(NAMESPACE_URL, f"quantos/hosted/q06/activate/{campaign.content_hash}"),
        occurred_at=bundle.initial_events[0].occurred_at,
    )
    frozen_plan = governor._freeze_verified_plan(  # pyright: ignore[reportPrivateUsage]
        campaign,
        bundle.family,
        research,
        bundle.manifest,
        (activation,),
        plan,
        event_id=uuid5(NAMESPACE_URL, f"quantos/hosted/q06/plan/{plan.content_hash}"),
        occurred_at=bundle.initial_events[1].occurred_at,
    )
    policy = AutonomousCampaignPolicy.model_validate(
        {
            **bundle.campaign_policy.model_dump(mode="python"),
            "readable_campaign_hashes": tuple(
                sorted(
                    campaign.content_hash if digest == bundle.campaign.content_hash else digest
                    for digest in bundle.campaign_policy.readable_campaign_hashes
                )
            ),
        }
    )
    recipe = HostedCampaignRecipe.model_validate(
        {**bundle.hosted_recipe.model_dump(mode="python"), "hosted_budget": transport}
    )
    return HostedFrozenBusinessInputs.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "campaign": campaign,
            "research_budget": research,
            "hosted_recipe": recipe,
            "initial_events": (activation, frozen_plan),
            "campaign_policy": policy,
            "selection_plan": plan,
        }
    )


def freeze_hosted_budget_case(
    bundle: HostedFrozenBusinessInputs,
    case: str,
    *,
    input_root: Path,
    artifact_root: Path,
) -> HostedFrozenBusinessInputs:
    """Publish a newly derived plan; never overwrite an existing variant root."""
    if artifact_root.exists() or artifact_root.is_symlink():
        raise ValueError("Q06 plan publication requires a fresh artifact root")
    bounded = derive_hosted_budget_case(bundle, case, input_root=input_root)
    # Same native publication used by CampaignSelectionService.freeze_plan;
    # read-only source verifiers use the derivation above without publication.
    publish_selection_plan(bounded.selection_plan, artifact_root)
    return bounded
