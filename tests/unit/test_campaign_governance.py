from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from quantos.application import CampaignGovernanceError, ResearchCampaignGovernor
from quantos.contracts import (
    CampaignLifecycleStatus,
    CampaignSegment,
    CampaignStoppingRule,
    CampaignTrial,
    ExperimentProposalSpec,
    FactorProposalSpec,
    InterpretationProposal,
    MultipleTestingPolicy,
    ParameterDimension,
    ProposedAttribute,
    ReasonCode,
    RegisteredFeatureRef,
    ResearchBudgetSpec,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
    StrategyAuthoringSpec,
    TrialOutcome,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _expression() -> SafeQlibExpressionSpec:
    return SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="delta_2d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(node_id="factor", operator="delta", inputs=("price",), window=2),
        ),
        output_node_id="factor",
    )


def _family() -> ResearchFamilySpec:
    return ResearchFamilySpec(
        family_id="family-001",
        research_question="Does a bounded delta family generalize?",
        hypothesis_hash="1" * 64,
        factor_template_hash="2" * 64,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )


def _budget(*, max_trials: int = 3) -> ResearchBudgetSpec:
    return ResearchBudgetSpec(
        budget_id="budget-001",
        max_trials=max_trials,
        max_distinct_candidates=min(2, max_trials),
        max_agent_runs=max_trials,
        max_executions=min(2, max_trials),
        max_validation_rounds=1,
        max_compute_seconds=100,
    )


def _campaign(
    family: ResearchFamilySpec,
    budget: ResearchBudgetSpec,
    *,
    parent_hash: str | None = None,
    contamination: tuple[str, ...] = (),
) -> ResearchCampaignSpec:
    return ResearchCampaignSpec(
        campaign_id="campaign-child" if parent_hash else "campaign-001",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=("3" * 64,),
        ledger_snapshot_hash="6" * 64,
        snapshot_hash="4" * 64,
        qlib_view_hash="5" * 64,
        development=ResearchSegment(start=date(2020, 1, 1), end=date(2020, 12, 31)),
        validation=ResearchSegment(start=date(2021, 1, 1), end=date(2021, 12, 31)),
        sealed_confirmation=ResearchSegment(start=date(2022, 1, 1), end=date(2022, 12, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
        parent_campaign_hash=parent_hash,
        inherited_contamination=contamination,
    )


def _trial(
    trial_id: str,
    *,
    segment: CampaignSegment,
    outcome: TrialOutcome,
    candidate: str,
    executed: bool,
) -> CampaignTrial:
    return CampaignTrial(
        trial_id=trial_id,
        idempotency_key=(trial_id[-1] * 64),
        proposal_hash=(trial_id[-1] * 64),
        candidate_hash=(candidate * 64),
        segment=segment,
        outcome=outcome,
        agent_run_hash="a" * 64,
        execution_requested=executed,
        compute_seconds=10 if executed else 0,
    )


def test_campaign_accounts_every_trial_and_seals_confirmation_once() -> None:
    governor = ResearchCampaignGovernor()
    family = _family()
    budget = _budget()
    campaign = _campaign(family, budget)
    activated = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("10000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    events = (activated,)
    invalid = _trial(
        "trial-1",
        segment=CampaignSegment.DEVELOPMENT,
        outcome=TrialOutcome.SCHEMA_INVALID,
        candidate="1",
        executed=False,
    )
    first = governor.record_trial(
        campaign,
        budget,
        events,
        invalid,
        event_id=UUID("10000000-0000-0000-0000-000000000002"),
        occurred_at=NOW + timedelta(seconds=1),
    )
    events += (first,)
    assert (
        governor.record_trial(
            campaign,
            budget,
            events,
            invalid,
            event_id=UUID("10000000-0000-0000-0000-000000000099"),
            occurred_at=NOW + timedelta(seconds=2),
        )
        == first
    )
    validation = _trial(
        "trial-2",
        segment=CampaignSegment.VALIDATION,
        outcome=TrialOutcome.EXECUTION_FAILED,
        candidate="2",
        executed=True,
    )
    second = governor.record_trial(
        campaign,
        budget,
        events,
        validation,
        event_id=UUID("10000000-0000-0000-0000-000000000003"),
        occurred_at=NOW + timedelta(seconds=2),
    )
    events += (second,)
    sealed = _trial(
        "trial-3",
        segment=CampaignSegment.SEALED_CONFIRMATION,
        outcome=TrialOutcome.PASS,
        candidate="2",
        executed=True,
    )
    oos = governor.access_sealed_confirmation(
        campaign,
        budget,
        events,
        sealed,
        event_id=UUID("10000000-0000-0000-0000-000000000004"),
        occurred_at=NOW + timedelta(seconds=3),
    )
    events += (oos,)

    snapshot = governor.project(campaign, budget, events)
    assert snapshot.status is CampaignLifecycleStatus.CLOSED
    assert snapshot.trial_count == 3
    assert snapshot.distinct_candidate_count == 2
    assert snapshot.execution_count == 2
    assert snapshot.validation_round_count == 1
    assert snapshot.sealed_confirmation_accessed
    assert campaign.content_hash in snapshot.contamination_hashes
    with pytest.raises(CampaignGovernanceError) as repeated:
        governor.access_sealed_confirmation(
            campaign,
            budget,
            events,
            sealed,
            event_id=UUID("10000000-0000-0000-0000-000000000005"),
            occurred_at=NOW + timedelta(seconds=4),
        )
    assert repeated.value.reason_code is ReasonCode.OOS_ALREADY_ACCESSED


def test_budget_and_event_chain_fail_closed() -> None:
    governor = ResearchCampaignGovernor()
    family = _family()
    budget = _budget(max_trials=1)
    campaign = _campaign(family, budget)
    active = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("20000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    first_trial = _trial(
        "trial-1",
        segment=CampaignSegment.DEVELOPMENT,
        outcome=TrialOutcome.SCHEMA_INVALID,
        candidate="1",
        executed=False,
    )
    first = governor.record_trial(
        campaign,
        budget,
        (active,),
        first_trial,
        event_id=UUID("20000000-0000-0000-0000-000000000002"),
        occurred_at=NOW,
    )
    second_trial = _trial(
        "trial-2",
        segment=CampaignSegment.DEVELOPMENT,
        outcome=TrialOutcome.DUPLICATE_CANDIDATE,
        candidate="1",
        executed=False,
    )
    with pytest.raises(CampaignGovernanceError) as exceeded:
        governor.record_trial(
            campaign,
            budget,
            (active, first),
            second_trial,
            event_id=UUID("20000000-0000-0000-0000-000000000003"),
            occurred_at=NOW,
        )
    assert exceeded.value.reason_code is ReasonCode.RESEARCH_BUDGET_EXCEEDED

    tampered = first.model_copy(update={"previous_event_hash": "f" * 64})
    with pytest.raises(CampaignGovernanceError) as invalid_chain:
        governor.project(campaign, budget, (active, tampered))
    assert invalid_chain.value.reason_code is ReasonCode.EVENT_CHAIN_INVALID


def test_campaign_authorizes_only_frozen_inputs_and_nonsealed_segments() -> None:
    governor = ResearchCampaignGovernor()
    family = _family()
    budget = _budget()
    campaign = _campaign(family, budget)
    active = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("30000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    snapshot = governor.project(campaign, budget, (active,))
    proposal = ExperimentProposalSpec(
        proposal_id="experiment-001",
        agent_run_hash="a" * 64,
        campaign_hash=campaign.content_hash,
        factor_proposal_hash="b" * 64,
        segment=CampaignSegment.DEVELOPMENT,
        evaluation_start=campaign.development.start,
        evaluation_end=campaign.development.end,
        strategy=StrategyAuthoringSpec(universe_index="000300.SH", top_k=10),
        snapshot_hash=campaign.snapshot_hash,
        qlib_view_hash=campaign.qlib_view_hash,
    )

    governor.authorize_proposal(campaign, snapshot, proposal)
    with pytest.raises(CampaignGovernanceError) as escaped:
        governor.authorize_proposal(
            campaign,
            snapshot,
            proposal.model_copy(
                update={
                    "segment": CampaignSegment.VALIDATION,
                    "evaluation_start": campaign.development.start,
                }
            ),
        )
    assert escaped.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION
    with pytest.raises(CampaignGovernanceError) as sealed:
        governor.authorize_proposal(
            campaign,
            snapshot,
            proposal.model_copy(
                update={
                    "segment": CampaignSegment.SEALED_CONFIRMATION,
                    "evaluation_start": campaign.sealed_confirmation.start,
                    "evaluation_end": campaign.sealed_confirmation.end,
                }
            ),
        )
    assert sealed.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION


def test_factor_family_and_contamination_propagation_are_mandatory() -> None:
    governor = ResearchCampaignGovernor()
    family = _family()
    budget = _budget()
    campaign = _campaign(family, budget)
    factor = FactorProposalSpec(
        proposal_id="factor-001",
        agent_run_hash="a" * 64,
        hypothesis_hash=family.hypothesis_hash,
        family_hash=family.content_hash,
        factor_template_hash=family.factor_template_hash,
        parameters=(ProposedAttribute(name="window", value=2),),
        expression=_expression(),
        registered_features=(
            RegisteredFeatureRef(
                field_name="adjusted_close",
                source_artifact_hash="b" * 64,
                availability_policy_hash="c" * 64,
            ),
        ),
        rationale="Bounded family proposal.",
    )
    governor.authorize_factor(family, factor)
    with pytest.raises(CampaignGovernanceError) as escaped_family:
        governor.authorize_factor(
            family,
            factor.model_copy(update={"parameters": (ProposedAttribute(name="window", value=99),)}),
        )
    assert escaped_family.value.reason_code is ReasonCode.SCHEMA_INVALID

    active = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("40000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    sealed_trial = _trial(
        "trial-1",
        segment=CampaignSegment.SEALED_CONFIRMATION,
        outcome=TrialOutcome.PASS,
        candidate="1",
        executed=True,
    )
    sealed = governor.access_sealed_confirmation(
        campaign,
        budget,
        (active,),
        sealed_trial,
        event_id=UUID("40000000-0000-0000-0000-000000000002"),
        occurred_at=NOW,
    )
    snapshot = governor.project(campaign, budget, (active, sealed))
    interpretation = InterpretationProposal(
        proposal_id="interpretation-001",
        agent_run_hash="d" * 64,
        campaign_hash=campaign.content_hash,
        validation_report_hash="e" * 64,
        summary="Proposal only.",
        findings=("Finding",),
    )
    with pytest.raises(CampaignGovernanceError) as contaminated:
        governor.require_interpretation_contamination(snapshot, interpretation)
    assert contaminated.value.reason_code is ReasonCode.CONTAMINATION_REQUIRED

    child_base = _campaign(
        family,
        budget,
        parent_hash=campaign.content_hash,
        contamination=snapshot.contamination_hashes,
    )
    child = ResearchCampaignSpec.model_validate(
        {
            **child_base.model_dump(mode="python"),
            "snapshot_hash": "f" * 64,
            "development": {"start": "2023-01-01", "end": "2023-12-31"},
            "validation": {"start": "2024-01-01", "end": "2024-12-31"},
            "sealed_confirmation": {"start": "2025-01-01", "end": "2025-12-31"},
        }
    )
    governor.authorize_child_campaign(campaign, snapshot, child)
    governor.require_interpretation_contamination(
        snapshot,
        interpretation.model_copy(
            update={"inherited_contamination": snapshot.contamination_hashes}
        ),
    )
