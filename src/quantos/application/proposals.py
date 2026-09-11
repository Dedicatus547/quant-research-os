"""Fail-closed compiler from linked Agent proposals to existing authoring contracts."""

from __future__ import annotations

from collections.abc import Mapping

from quantos.contracts.agent import (
    ExperimentProposalSpec,
    FactorProposalSpec,
    HypothesisProposal,
    ObservationProposal,
)
from quantos.contracts.campaign import ResearchCampaignSpec, ResearchFamilySpec
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.proposals import CompiledExperimentProposal
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ExpressionAuthoringSpec,
    ResearchSegment,
    StrategyAuthoringSpec,
)
from quantos.contracts.status import ReasonCode


class ProposalCompilationError(ValueError):
    """A proposal chain cannot enter deterministic execution."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def compile_experiment_proposal(
    observation: ObservationProposal,
    hypothesis: HypothesisProposal,
    factor: FactorProposalSpec,
    experiment: ExperimentProposalSpec,
    campaign: ResearchCampaignSpec,
    family: ResearchFamilySpec,
    *,
    agent_run_hashes: tuple[str, ...],
) -> CompiledExperimentProposal:
    """Compile a fully linked minimal proposal chain without executing or validating it."""

    allowed_runs = set(agent_run_hashes)
    proposal_runs = {
        observation.agent_run_hash,
        hypothesis.agent_run_hash,
        factor.agent_run_hash,
        experiment.agent_run_hash,
    }
    if not agent_run_hashes or proposal_runs - allowed_runs:
        raise ProposalCompilationError(
            ReasonCode.CAPABILITY_DENIED,
            "every proposal must bind an explicitly admitted Agent run",
        )
    if hypothesis.observation_hashes != (observation.content_hash,):
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "hypothesis does not bind the observation"
        )
    if factor.hypothesis_hash != hypothesis.content_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "factor does not bind the hypothesis"
        )
    if experiment.factor_proposal_hash != factor.content_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "experiment does not bind the factor proposal"
        )
    if experiment.campaign_hash != campaign.content_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "experiment does not bind the campaign"
        )
    if factor.family_hash != family.content_hash or campaign.family_hash != family.content_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "factor and campaign must bind the same family"
        )
    if family.hypothesis_hash != hypothesis.content_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED, "research family does not bind the hypothesis"
        )
    cited_evidence = {citation.evidence_hash for citation in observation.citations}
    if not cited_evidence.issubset(campaign.evidence_hashes):
        raise ProposalCompilationError(
            ReasonCode.SOURCE_INCOMPLETE, "observation evidence is outside the frozen campaign"
        )
    citation_hashes = {
        digest
        for citation in (*observation.citations, *hypothesis.evidence_citations)
        for digest in (
            citation.evidence_hash,
            citation.extracted_text_hash,
            citation.cited_text_hash,
        )
    }
    if experiment.snapshot_hash != campaign.snapshot_hash or (
        experiment.qlib_view_hash != campaign.qlib_view_hash
    ):
        raise ProposalCompilationError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "experiment data hashes do not match the campaign",
        )
    if experiment.feature_artifact_hashes != campaign.feature_artifact_hashes:
        raise ProposalCompilationError(
            ReasonCode.SOURCE_INCOMPLETE,
            "experiment feature inputs do not match the frozen campaign",
        )
    registered_sources = {item.source_artifact_hash for item in factor.registered_features}
    allowed_sources = {campaign.snapshot_hash, *campaign.feature_artifact_hashes}
    if not registered_sources.issubset(allowed_sources):
        raise ProposalCompilationError(
            ReasonCode.SOURCE_INCOMPLETE,
            "factor references a field outside frozen dataset and feature artifacts",
        )
    period = _campaign_period(experiment, campaign)
    if experiment.evaluation_start < period.start or experiment.evaluation_end > period.end:
        raise ProposalCompilationError(
            ReasonCode.OOS_POLICY_VIOLATION,
            "experiment dates escape the selected frozen campaign segment",
        )
    expression = _authoring_expression(factor, family)
    if factor.expression.input_lag_trading_days != experiment.strategy.input_lag_trading_days:
        raise ProposalCompilationError(
            ReasonCode.SCHEMA_INVALID,
            "factor expression and strategy input lags disagree",
        )
    authoring = ExperimentAuthoringSpec(
        experiment_id=experiment.proposal_id,
        evaluation_start=experiment.evaluation_start,
        evaluation_end=experiment.evaluation_end,
        expression=expression,
        strategy=StrategyAuthoringSpec.model_validate(
            experiment.strategy.model_dump(mode="python", exclude={"schema_version"})
        ),
    )
    input_hashes = tuple(
        sorted(
            {
                campaign.content_hash,
                family.content_hash,
                observation.content_hash,
                hypothesis.content_hash,
                factor.content_hash,
                experiment.content_hash,
                *campaign.evidence_hashes,
                *citation_hashes,
                *campaign.feature_artifact_hashes,
                campaign.snapshot_hash,
                campaign.qlib_view_hash,
            }
        )
    )
    return CompiledExperimentProposal(
        observation_hash=observation.content_hash,
        hypothesis_hash=hypothesis.content_hash,
        factor_proposal_hash=factor.content_hash,
        experiment_proposal_hash=experiment.content_hash,
        campaign_hash=campaign.content_hash,
        family_hash=family.content_hash,
        source_agent_run_hashes=tuple(sorted(allowed_runs)),
        input_hashes=input_hashes,
        authoring_spec=authoring,
    )


def _campaign_period(
    experiment: ExperimentProposalSpec, campaign: ResearchCampaignSpec
) -> ResearchSegment:
    periods: Mapping[str, ResearchSegment] = {
        "DEVELOPMENT": campaign.development,
        "VALIDATION": campaign.validation,
        "SEALED_CONFIRMATION": campaign.sealed_confirmation,
    }
    return periods[experiment.segment.value]


def _authoring_expression(
    factor: FactorProposalSpec, family: ResearchFamilySpec
) -> ExpressionAuthoringSpec | SafeQlibExpressionSpec:
    nodes = factor.expression.nodes
    used_operators = {node.operator for node in nodes}
    if not used_operators.issubset(family.allowed_operators):
        raise ProposalCompilationError(
            ReasonCode.SCHEMA_INVALID,
            "factor expression uses an operator outside the frozen research family",
        )
    if factor.factor_template_hash != family.factor_template_hash:
        raise ProposalCompilationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "factor proposal does not bind the frozen family template",
        )
    fields = {node.field_name for node in nodes if node.operator is SafeQlibOperator.FIELD}
    if fields != {"adjusted_close"}:
        raise ProposalCompilationError(
            ReasonCode.SCHEMA_INVALID,
            "factor expression references a field absent from the qualified Qlib view",
        )

    # Preserve the legacy shorthand (and its hashes) for the original P11 template.
    if len(nodes) != 2:
        return factor.expression
    field, output = nodes
    if (
        field.operator is not SafeQlibOperator.FIELD
        or field.field_name != "adjusted_close"
        or output.operator is not SafeQlibOperator.RETURN
        or output.inputs != (field.node_id,)
        or output.window is None
        or factor.expression.output_node_id != output.node_id
    ):
        return factor.expression
    return ExpressionAuthoringSpec(
        expression_id=output.node_id,
        operator="return",
        field="adjusted_close",
        window=output.window,
    )
