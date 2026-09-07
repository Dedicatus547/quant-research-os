from __future__ import annotations

import json
from datetime import date

import pytest

from quantos.application import (
    ProposalCompilationError,
    ProposalMcpError,
    ProposalMcpService,
    compile_experiment_proposal,
    proposal_mcp_policy,
)
from quantos.contracts import (
    CampaignSegment,
    EvidenceCitation,
    ExpectedDirection,
    ExperimentProposalSpec,
    FactorProposalSpec,
    FalsificationCriterion,
    HypothesisProposal,
    ObservationProposal,
    ParameterDimension,
    ProposalSubmissionRequest,
    ProposedAttribute,
    RegisteredFeatureRef,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    StrategyAuthoringSpec,
    SubmittableProposalKind,
    canonical_json_bytes,
)
from quantos.contracts.campaign import CampaignStoppingRule, MultipleTestingPolicy
from quantos.contracts.status import ReasonCode

AGENT_RUNS = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
SNAPSHOT = "1" * 64
VIEW = "2" * 64
EVIDENCE = "3" * 64


def _chain() -> tuple[
    ObservationProposal,
    HypothesisProposal,
    FactorProposalSpec,
    ExperimentProposalSpec,
    ResearchCampaignSpec,
    ResearchFamilySpec,
]:
    citation = EvidenceCitation(
        evidence_hash=EVIDENCE,
        extracted_text_hash="4" * 64,
        char_start=0,
        char_end=10,
        cited_text_hash="5" * 64,
    )
    observation = ObservationProposal(
        proposal_id="observation-p11",
        agent_run_hash=AGENT_RUNS[0],
        statement="The structured synthetic fixture contains adjusted closes.",
        citations=(citation,),
        limitations=("SYNTHETIC_FIXTURE",),
    )
    hypothesis = HypothesisProposal(
        proposal_id="hypothesis-p11",
        agent_run_hash=AGENT_RUNS[1],
        observation_hashes=(observation.content_hash,),
        claim="A one-session return may rank the synthetic universe.",
        mechanism="The fixture permits a deterministic momentum example.",
        evidence_citations=(citation,),
        expected_direction=ExpectedDirection.POSITIVE,
        confounders=("synthetic_construction",),
        falsification=(
            FalsificationCriterion(
                metric="annualized_return",
                comparison="min",
                threshold=0,
                segment="VALIDATION",
            ),
        ),
    )
    template_hash = "6" * 64
    family = ResearchFamilySpec(
        family_id="family-p11",
        research_question="Can the frozen return template execute end to end?",
        hypothesis_hash=hypothesis.content_hash,
        factor_template_hash=template_hash,
        allowed_operators=("field", "return"),
        parameter_space=(ParameterDimension(name="window", values=(1,)),),
        declared_candidate_count=1,
    )
    expression = SafeQlibExpressionSpec(
        expression_id="momentum_1d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
            SafeExpressionNode(
                node_id="momentum_1d", operator="return", inputs=("price",), window=1
            ),
        ),
        output_node_id="momentum_1d",
        input_lag_trading_days=0,
    )
    factor = FactorProposalSpec(
        proposal_id="factor-p11",
        agent_run_hash=AGENT_RUNS[2],
        hypothesis_hash=hypothesis.content_hash,
        family_hash=family.content_hash,
        factor_template_hash=template_hash,
        parameters=(ProposedAttribute(name="window", value=1),),
        expression=expression,
        registered_features=(
            RegisteredFeatureRef(
                field_name="adjusted_close",
                source_artifact_hash=SNAPSHOT,
                availability_policy_hash="7" * 64,
            ),
        ),
        rationale="Exercise the existing safe return expression.",
        limitations=("SYNTHETIC_FIXTURE",),
    )
    campaign_values = {
        "campaign_id": "campaign-p11",
        "research_question": family.research_question,
        "family_hash": family.content_hash,
        "budget_hash": "8" * 64,
        "evidence_hashes": (EVIDENCE,),
        "ledger_snapshot_hash": "9" * 64,
        "snapshot_hash": SNAPSHOT,
        "qlib_view_hash": VIEW,
        "development": ResearchSegment(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        "validation": ResearchSegment(start=date(2024, 2, 1), end=date(2024, 2, 29)),
        "sealed_confirmation": ResearchSegment(start=date(2024, 3, 1), end=date(2024, 3, 31)),
        "multiple_testing_policy": MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        "stopping_rule": CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    }
    campaign = ResearchCampaignSpec(**campaign_values)
    experiment = ExperimentProposalSpec(
        proposal_id="experiment-p11",
        agent_run_hash=AGENT_RUNS[3],
        campaign_hash=campaign.content_hash,
        factor_proposal_hash=factor.content_hash,
        segment=CampaignSegment.VALIDATION,
        evaluation_start=date(2024, 2, 1),
        evaluation_end=date(2024, 2, 29),
        strategy=StrategyAuthoringSpec(
            universe_index="000300.SH",
            top_k=1,
            max_weight=1,
        ),
        snapshot_hash=SNAPSHOT,
        qlib_view_hash=VIEW,
    )
    return observation, hypothesis, factor, experiment, campaign, family


def test_linked_proposals_compile_to_existing_authoring_contract() -> None:
    compiled = compile_experiment_proposal(*_chain(), agent_run_hashes=AGENT_RUNS)

    assert compiled.authoring_spec.expression.expression_id == "momentum_1d"
    assert compiled.authoring_spec.expression.window == 1
    assert compiled.authoring_spec.strategy.top_k == 1
    assert compiled.experiment_proposal_hash == _chain()[3].content_hash
    assert EVIDENCE in compiled.input_hashes
    assert compiled.source_agent_run_hashes == AGENT_RUNS


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("agent", ReasonCode.CAPABILITY_DENIED),
        ("evidence", ReasonCode.SOURCE_INCOMPLETE),
        ("snapshot", ReasonCode.SNAPSHOT_HASH_MISMATCH),
        ("oos", ReasonCode.OOS_POLICY_VIOLATION),
        ("expression", ReasonCode.SCHEMA_INVALID),
    ],
)
def test_compiler_rejects_unbound_authority_and_unsupported_execution_inputs(
    mutation: str, reason_code: ReasonCode
) -> None:
    observation, hypothesis, factor, experiment, campaign, family = _chain()
    runs = AGENT_RUNS
    if mutation == "agent":
        runs = AGENT_RUNS[:-1]
    elif mutation == "evidence":
        campaign = campaign.model_copy(update={"evidence_hashes": ("0" * 64,)})
        experiment = experiment.model_copy(update={"campaign_hash": campaign.content_hash})
    elif mutation == "snapshot":
        experiment = experiment.model_copy(update={"snapshot_hash": "0" * 64})
    elif mutation == "oos":
        experiment = experiment.model_copy(update={"evaluation_end": date(2024, 3, 1)})
    elif mutation == "expression":
        extra = SafeExpressionNode(node_id="absolute", operator="abs", inputs=("momentum_1d",))
        changed = factor.expression.model_copy(
            update={
                "schema_version": "safe-qlib-expression/v2",
                "nodes": (*factor.expression.nodes, extra),
                "output_node_id": "absolute",
            }
        )
        factor = factor.model_copy(update={"expression": changed})
        experiment = experiment.model_copy(update={"factor_proposal_hash": factor.content_hash})

    with pytest.raises(ProposalCompilationError) as failure:
        compile_experiment_proposal(
            observation,
            hypothesis,
            factor,
            experiment,
            campaign,
            family,
            agent_run_hashes=runs,
        )
    assert failure.value.reason_code is reason_code


def test_compiler_is_offline_and_does_not_promote_validation_authority() -> None:
    compiled = compile_experiment_proposal(*_chain(), agent_run_hashes=AGENT_RUNS)
    serialized = compiled.model_dump(mode="json")

    assert "verdict" not in serialized
    assert "status" not in serialized


def _submission_payload(*, statement: str | None = None) -> bytes:
    observation, hypothesis, *_ = _chain()
    del observation
    if statement is not None:
        hypothesis = hypothesis.model_copy(update={"claim": statement})
    campaign_hash = "e" * 64
    budget_hash = "f" * 64
    request = ProposalSubmissionRequest(
        idempotency_key="0" * 64,
        proposal_kind=SubmittableProposalKind.HYPOTHESIS,
        agent_run_hash=hypothesis.agent_run_hash,
        campaign_hash=campaign_hash,
        budget_hash=budget_hash,
        input_hashes=tuple(sorted((hypothesis.agent_run_hash, campaign_hash, budget_hash))),
        proposal=hypothesis,
    )
    return canonical_json_bytes(request)


def test_proposal_mcp_submission_is_immutable_and_idempotent(tmp_path) -> None:
    service = ProposalMcpService(tmp_path / "proposal-store")
    capability = "proposal.submit_hypothesis"

    first = service.submit(capability, _submission_payload())
    second = service.submit(capability, _submission_payload())

    assert first == second
    assert service.read_receipt("0" * 64) == first
    proposal_path = (
        tmp_path / "proposal-store/proposals/hypothesis" / f"sha256-{first.proposal_hash}.json"
    )
    assert proposal_path.is_file()
    assert len(service.audit_decisions) == 2

    with pytest.raises(ProposalMcpError) as conflict:
        service.submit(capability, _submission_payload(statement="A conflicting claim."))
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT


def test_proposal_mcp_denies_authority_fields_wrong_capability_and_budget(tmp_path) -> None:
    authority = json.loads(_submission_payload())
    authority["force_pass"] = True
    service = ProposalMcpService(tmp_path / "authority")
    with pytest.raises(ProposalMcpError) as denied:
        service.submit("proposal.submit_hypothesis", canonical_json_bytes(authority))
    assert denied.value.reason_code is ReasonCode.AUTHORITY_FIELD_DENIED

    service = ProposalMcpService(tmp_path / "kind")
    with pytest.raises(ProposalMcpError) as wrong_kind:
        service.submit("proposal.submit_factor", _submission_payload())
    assert wrong_kind.value.reason_code is ReasonCode.CAPABILITY_DENIED

    service = ProposalMcpService(tmp_path / "budget", proposal_mcp_policy(max_requests=1))
    service.submit("proposal.submit_hypothesis", _submission_payload())
    with pytest.raises(ProposalMcpError) as exhausted:
        service.submit("proposal.submit_hypothesis", _submission_payload())
    assert exhausted.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED


def test_proposal_mcp_missing_receipt_fails_closed(tmp_path) -> None:
    service = ProposalMcpService(tmp_path / "missing")
    with pytest.raises(ProposalMcpError) as missing:
        service.read_receipt("1" * 64)
    assert missing.value.reason_code is ReasonCode.SOURCE_INCOMPLETE
