#!/usr/bin/env python3
"""Run the frozen P11 proposal through typed MCP into the existing Qlib release path."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from release_feasibility import run_with_authoring

from quantos.application import (
    DatasetBinding,
    ProposalChainBinding,
    ProposalMcpService,
    ResearchMcpService,
    capture_code_provenance,
    capture_runtime_fingerprint,
    compile_experiment_proposal,
)
from quantos.artifacts.store import atomic_write_bytes
from quantos.config import load_yaml_contract
from quantos.contracts import (
    CampaignSegment,
    CompiledExperimentProposal,
    DatasetDescription,
    DatasetFieldCatalog,
    EvidenceCitation,
    EvidenceRecord,
    ExecutionJob,
    ExecutionJobReceipt,
    ExecutionJobState,
    ExecutionOutcome,
    ExpectedDirection,
    ExperimentAuthoringSpec,
    ExperimentExecutionRequest,
    ExperimentProposalSpec,
    ExperimentResolutionReceipt,
    ExperimentResolutionRequest,
    ExtractedTextArtifact,
    FactorProposalSpec,
    FalsificationCriterion,
    HypothesisProposal,
    InterpretationProposal,
    JobLookupRequest,
    ObservationProposal,
    ParameterDimension,
    ProposalSubmissionRequest,
    ProposedAttribute,
    QlibViewSpec,
    RegisteredFeatureRef,
    RegistryExperimentManifest,
    RegistryGetRequest,
    RegistryResourceKind,
    RegistrySearchRequest,
    RegistrySearchResult,
    ResearchBudgetSpec,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
    StrategyAuthoringSpec,
    SubmittableProposalKind,
    ThresholdComparison,
    ValidationLookupRequest,
    ValidationReport,
    canonical_json_bytes,
    sha256_bytes,
)
from quantos.contracts.campaign import CampaignStoppingRule, MultipleTestingPolicy
from quantos.data import QlibViewBuilder, SyntheticSnapshotBuilder
from quantos.registry import RegistryService
from quantos.validation import verify_validation_report

_RAW_TEXT = (
    "The frozen structured fixture contains adjusted closing prices for a deterministic momentum "
    "example."
)
_RESEARCHER_RUN_HASH = sha256_bytes(b"p11-researcher-agent-run-v1")
_FORMALIZER_RUN_HASH = sha256_bytes(b"p11-formalizer-agent-run-v1")
_REVIEWER_RUN_HASH = sha256_bytes(b"p11-reviewer-agent-run-v1")
_AGENT_RUN_HASHES = tuple(sorted((_FORMALIZER_RUN_HASH, _RESEARCHER_RUN_HASH)))


def _proposal_chain(
    *,
    evidence: EvidenceRecord,
    extracted: ExtractedTextArtifact,
    snapshot_hash: str,
    qlib_view_hash: str,
    budget: ResearchBudgetSpec,
) -> ProposalChainBinding:
    citation = EvidenceCitation(
        evidence_hash=evidence.content_hash,
        extracted_text_hash=extracted.content_hash,
        char_start=0,
        char_end=len(_RAW_TEXT),
        cited_text_hash=sha256_bytes(_RAW_TEXT.encode()),
    )
    observation = ObservationProposal(
        proposal_id="p11-synthetic-observation-v1",
        agent_run_hash=_RESEARCHER_RUN_HASH,
        statement="The frozen structured fixture provides adjusted closing prices.",
        citations=(citation,),
        limitations=("SYNTHETIC_FIXTURE",),
    )
    hypothesis = HypothesisProposal(
        proposal_id="p11-synthetic-hypothesis-v1",
        agent_run_hash=_RESEARCHER_RUN_HASH,
        observation_hashes=(observation.content_hash,),
        claim="One-session return can exercise the deterministic momentum research path.",
        mechanism="The synthetic price sequence provides a bounded ranking example.",
        evidence_citations=(citation,),
        expected_direction=ExpectedDirection.POSITIVE,
        confounders=("synthetic_construction",),
        falsification=(
            FalsificationCriterion(
                metric="annualized_return",
                comparison=ThresholdComparison.MIN,
                threshold=0,
                segment="VALIDATION",
            ),
        ),
    )
    template_hash = sha256_bytes(b"p11-field-return-template-v1")
    family = ResearchFamilySpec(
        family_id="p11-synthetic-family-v1",
        research_question="Can a frozen proposal reproduce the existing native-Qlib evidence?",
        hypothesis_hash=hypothesis.content_hash,
        factor_template_hash=template_hash,
        allowed_operators=(SafeQlibOperator.FIELD, SafeQlibOperator.RETURN),
        parameter_space=(ParameterDimension(name="window", values=(1,)),),
        declared_candidate_count=1,
    )
    factor = FactorProposalSpec(
        proposal_id="p11-synthetic-factor-v1",
        agent_run_hash=_FORMALIZER_RUN_HASH,
        hypothesis_hash=hypothesis.content_hash,
        family_hash=family.content_hash,
        factor_template_hash=template_hash,
        parameters=(ProposedAttribute(name="window", value=1),),
        expression=SafeQlibExpressionSpec(
            expression_id="momentum_1d",
            nodes=(
                SafeExpressionNode(
                    node_id="price",
                    operator=SafeQlibOperator.FIELD,
                    field_name="adjusted_close",
                ),
                SafeExpressionNode(
                    node_id="momentum_1d",
                    operator=SafeQlibOperator.RETURN,
                    inputs=("price",),
                    window=1,
                ),
            ),
            output_node_id="momentum_1d",
            input_lag_trading_days=0,
        ),
        registered_features=(
            RegisteredFeatureRef(
                field_name="adjusted_close",
                source_artifact_hash=snapshot_hash,
                availability_policy_hash=evidence.availability_policy_hash,
            ),
        ),
        rationale="Compile the frozen registered field through the admitted return template.",
        limitations=("SYNTHETIC_FIXTURE",),
    )
    campaign = ResearchCampaignSpec(
        campaign_id="p11-synthetic-campaign-v1",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=(evidence.content_hash,),
        ledger_snapshot_hash=sha256_bytes(b"p11-empty-ledger-snapshot-v1"),
        snapshot_hash=snapshot_hash,
        qlib_view_hash=qlib_view_hash,
        development=ResearchSegment(start=date(2023, 1, 1), end=date(2023, 3, 31)),
        validation=ResearchSegment(start=date(2023, 4, 1), end=date(2023, 6, 30)),
        sealed_confirmation=ResearchSegment(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    experiment = ExperimentProposalSpec(
        proposal_id="synthetic-validation-feasibility-v1",
        agent_run_hash=_FORMALIZER_RUN_HASH,
        campaign_hash=campaign.content_hash,
        factor_proposal_hash=factor.content_hash,
        segment=CampaignSegment.SEALED_CONFIRMATION,
        evaluation_start=date(2024, 1, 1),
        evaluation_end=date(2024, 1, 31),
        strategy=StrategyAuthoringSpec(universe_index="000300.SH", top_k=1, max_weight=0.03),
        snapshot_hash=snapshot_hash,
        qlib_view_hash=qlib_view_hash,
    )
    return ProposalChainBinding(observation, hypothesis, factor, experiment, campaign, family)


def _submit_proposals(
    service: ProposalMcpService,
    chain: ProposalChainBinding,
    budget_hash: str,
    extracted_hash: str,
) -> tuple[str, ...]:
    items = (
        (
            "proposal.submit_hypothesis",
            SubmittableProposalKind.HYPOTHESIS,
            chain.hypothesis,
            sha256_bytes(b"p11-submit-hypothesis-v1"),
        ),
        (
            "proposal.submit_factor",
            SubmittableProposalKind.FACTOR,
            chain.factor,
            sha256_bytes(b"p11-submit-factor-v1"),
        ),
        (
            "proposal.submit_experiment",
            SubmittableProposalKind.EXPERIMENT,
            chain.experiment,
            sha256_bytes(b"p11-submit-experiment-v1"),
        ),
    )
    receipts: list[str] = []
    for capability, kind, proposal, key in items:
        inputs = tuple(
            sorted(
                {
                    proposal.agent_run_hash,
                    chain.campaign.content_hash,
                    budget_hash,
                    extracted_hash,
                    chain.observation.content_hash,
                    chain.hypothesis.content_hash,
                    chain.factor.content_hash,
                }
            )
        )
        request = ProposalSubmissionRequest(
            idempotency_key=key,
            proposal_kind=kind,
            agent_run_hash=proposal.agent_run_hash,
            campaign_hash=chain.campaign.content_hash,
            budget_hash=budget_hash,
            input_hashes=inputs,
            proposal=proposal,
        )
        receipt = service.submit(capability, canonical_json_bytes(request))
        receipts.append(receipt.content_hash)
    return tuple(receipts)


def run(
    fixture_root: Path,
    qlib_source: Path,
    output_root: Path,
    workspace: Path,
    evidence_path: Path,
    expected_authoring_path: Path,
    research_policy_path: Path,
    validation_policy_path: Path,
    cost_policy_path: Path,
    backtest_policy_path: Path,
) -> dict[str, object]:
    """Exercise typed proposal ingress, compilation, Qlib, validation, registry, and review."""

    provenance = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    evidence = load_yaml_contract(evidence_path, EvidenceRecord)
    if evidence.raw_bytes_hash != sha256_bytes(
        _RAW_TEXT.encode()
    ) or evidence.raw_size_bytes != len(_RAW_TEXT.encode()):
        raise RuntimeError("frozen structured Evidence does not match its source bytes")
    extracted = ExtractedTextArtifact(
        evidence_hash=evidence.content_hash,
        raw_bytes_hash=evidence.raw_bytes_hash,
        text_hash=sha256_bytes(_RAW_TEXT.encode()),
        character_count=len(_RAW_TEXT),
        parser_name="identity-structured-fixture",
        parser_version="1",
        parser_config_hash=sha256_bytes(b"p11-parser-config-v1"),
        code_commit_hash=provenance.commit_hash,
        runtime_fingerprint_hash=runtime.content_hash,
        limitations=("SYNTHETIC_DATA_NOT_LIVE_EVIDENCE",),
    )
    catalog_root = output_root / "catalog"
    snapshot = SyntheticSnapshotBuilder().build(fixture_root, catalog_root / "snapshots")
    view = QlibViewBuilder().build(snapshot.path, catalog_root / "qlib-views", qlib_source)
    view_spec = QlibViewSpec.model_validate_json((view.path / "view-spec.json").read_bytes())
    budget = ResearchBudgetSpec(
        budget_id="p11-synthetic-budget-v1",
        max_trials=1,
        max_distinct_candidates=1,
        max_agent_runs=3,
        max_executions=1,
        max_validation_rounds=1,
        max_compute_seconds=3600,
    )
    chain = _proposal_chain(
        evidence=evidence,
        extracted=extracted,
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        budget=budget,
    )
    compiled = compile_experiment_proposal(
        chain.observation,
        chain.hypothesis,
        chain.factor,
        chain.experiment,
        chain.campaign,
        chain.family,
        agent_run_hashes=_AGENT_RUN_HASHES,
    )
    expected_authoring = load_yaml_contract(expected_authoring_path, ExperimentAuthoringSpec)
    if compiled.authoring_spec != expected_authoring:
        raise RuntimeError("proposal compiler did not reproduce the frozen authoring contract")

    frozen_root = output_root / "frozen-inputs"
    for name, contract in (
        ("evidence", evidence),
        ("extracted-text", extracted),
        ("budget", budget),
        ("observation", chain.observation),
        ("campaign", chain.campaign),
        ("family", chain.family),
    ):
        atomic_write_bytes(
            frozen_root / name / f"sha256-{contract.content_hash}.json",
            contract.canonical_bytes(),
        )
    proposal_receipts = _submit_proposals(
        ProposalMcpService(output_root / "proposal-mcp"),
        chain,
        budget.content_hash,
        extracted.content_hash,
    )

    release_result: dict[str, object] = {}

    def execute(authoring_proposal: CompiledExperimentProposal) -> ExecutionOutcome:
        nonlocal release_result
        release_result = run_with_authoring(
            fixture_root,
            qlib_source,
            output_root / "release",
            workspace,
            authoring_proposal.authoring_spec,
            research_policy_path,
            validation_policy_path,
            cost_policy_path,
            backtest_policy_path,
        )
        run_a_registry = RegistryService(output_root / "release" / "run-a" / "registry")
        manifest = run_a_registry.get_experiment(authoring_proposal.authoring_spec.experiment_id)
        return ExecutionOutcome(
            run_status=manifest.run_status,
            validation_verdict=manifest.verdict,
            validation_report_hash=manifest.validation_report_hash,
            registry_manifest_hash=manifest.manifest_hash,
            registry_index_hash=run_a_registry.verify().index_hash,
            compute_seconds=0,
        )

    def load_validation(digest: str) -> ValidationReport:
        return verify_validation_report(
            output_root / "release" / "run-a" / "validation" / f"sha256-{digest}"
        )

    mcp = ResearchMcpService(
        output_root / "research-mcp",
        datasets={
            snapshot.manifest.snapshot_hash: DatasetBinding(
                snapshot.manifest, view.manifest, view_spec
            )
        },
        proposal_chains={chain.experiment.content_hash: chain},
        validation_loader=load_validation,
        registry=RegistryService(output_root / "release" / "run-a" / "registry"),
        executor=execute,
        max_queued_jobs=1,
        max_timeout_seconds=budget.max_compute_seconds,
    )
    dataset_request = canonical_json_bytes(
        {
            "schema_version": "dataset-lookup-request/v1",
            "snapshot_hash": snapshot.manifest.snapshot_hash,
            "qlib_view_hash": view.manifest.view_hash,
        }
    )
    dataset_description = mcp.call("dataset.describe", dataset_request)
    dataset_fields = mcp.call("dataset.fields", dataset_request)
    if not isinstance(dataset_description, DatasetDescription) or not isinstance(
        dataset_fields, DatasetFieldCatalog
    ):
        raise RuntimeError("dataset tools returned the wrong typed contracts")
    resolution_request = ExperimentResolutionRequest(
        idempotency_key=sha256_bytes(b"p11-resolution-v1"),
        observation_hash=chain.observation.content_hash,
        hypothesis_hash=chain.hypothesis.content_hash,
        factor_proposal_hash=chain.factor.content_hash,
        experiment_proposal_hash=chain.experiment.content_hash,
        campaign_hash=chain.campaign.content_hash,
        family_hash=chain.family.content_hash,
        budget_hash=budget.content_hash,
        agent_run_hashes=_AGENT_RUN_HASHES,
        input_hashes=tuple(
            sorted({*compiled.input_hashes, *_AGENT_RUN_HASHES, budget.content_hash})
        ),
    )
    resolution = mcp.call("experiment.resolve", canonical_json_bytes(resolution_request))
    if not isinstance(resolution, ExperimentResolutionReceipt):
        raise RuntimeError("experiment.resolve returned the wrong typed contract")
    execution_request = ExperimentExecutionRequest(
        idempotency_key=sha256_bytes(b"p11-execution-v1"),
        compiled_proposal_hash=resolution.compiled_proposal_hash,
        agent_run_hash=_FORMALIZER_RUN_HASH,
        campaign_hash=chain.campaign.content_hash,
        budget_hash=budget.content_hash,
        input_hashes=tuple(
            sorted(
                {
                    *compiled.input_hashes,
                    resolution.compiled_proposal_hash,
                    _FORMALIZER_RUN_HASH,
                    budget.content_hash,
                }
            )
        ),
        timeout_seconds=budget.max_compute_seconds,
    )
    execution = mcp.call("experiment.request_execution", canonical_json_bytes(execution_request))
    if not isinstance(execution, ExecutionJobReceipt):
        raise RuntimeError("execution request returned the wrong typed receipt")
    queued = mcp.call("job.get", canonical_json_bytes(JobLookupRequest(job_id=execution.job_id)))
    completed = mcp.run_next()
    if (
        not isinstance(queued, ExecutionJob)
        or queued.state is not ExecutionJobState.QUEUED
        or completed is None
        or completed.state is not ExecutionJobState.SUCCEEDED
        or completed.outcome is None
    ):
        raise RuntimeError("typed execution job did not complete successfully")
    outcome = completed.outcome
    if outcome.validation_report_hash is None:
        raise RuntimeError("successful execution omitted its ValidationReport hash")
    validation = mcp.call(
        "validation.get",
        canonical_json_bytes(
            ValidationLookupRequest(validation_report_hash=outcome.validation_report_hash)
        ),
    )
    if not isinstance(validation, ValidationReport):
        raise RuntimeError("validation.get returned the wrong typed contract")
    registered = mcp.call(
        "registry.get",
        canonical_json_bytes(
            RegistryGetRequest(
                resource_kind=RegistryResourceKind.EXPERIMENT,
                logical_id=compiled.authoring_spec.experiment_id,
            )
        ),
    )
    if not isinstance(registered, RegistryExperimentManifest):
        raise RuntimeError("registry.get returned the wrong typed contract")
    search = mcp.call(
        "registry.search",
        canonical_json_bytes(
            RegistrySearchRequest(experiment_id_prefix="synthetic-validation", limit=10)
        ),
    )
    if not isinstance(search, RegistrySearchResult):
        raise RuntimeError("registry.search returned the wrong typed contract")
    run_b_registry = RegistryService(output_root / "release" / "run-b" / "registry")
    run_b = run_b_registry.get_experiment(compiled.authoring_spec.experiment_id)
    exact_authority_fields = (
        "resolved_experiment_hash",
        "pit_audit_evidence_hash",
        "signal_artifact_hash",
        "backtest_result_hash",
        "validation_report_hash",
        "manifest_hash",
    )
    if any(getattr(registered, field) != getattr(run_b, field) for field in exact_authority_fields):
        raise RuntimeError(
            "proposal-driven independent release runs did not reproduce authority hashes"
        )
    interpretation = InterpretationProposal(
        proposal_id="p11-synthetic-interpretation-v1",
        agent_run_hash=_REVIEWER_RUN_HASH,
        campaign_hash=chain.campaign.content_hash,
        validation_report_hash=validation.report_hash,
        summary="The immutable ValidationReport is explained without changing its verdict.",
        findings=(
            f"run_status={validation.run_status.value}",
            f"validation_verdict={validation.verdict.value}",
        ),
        next_question="Should a distinct pre-frozen family be evaluated in a new campaign?",
        inherited_contamination=(validation.report_hash,),
    )
    atomic_write_bytes(
        output_root / "interpretations" / f"sha256-{interpretation.content_hash}.json",
        interpretation.canonical_bytes(),
    )
    payload: dict[str, object] = {
        "schema_version": "p11-proposal-feasibility-report/v1",
        "status": "PASS",
        "source_kind": "STRUCTURED_FIXTURE",
        "code_commit_hash": provenance.commit_hash,
        "evidence_hash": evidence.content_hash,
        "extracted_text_hash": extracted.content_hash,
        "proposal_hashes": tuple(
            item.content_hash for item in (chain.hypothesis, chain.factor, chain.experiment)
        ),
        "proposal_receipt_hashes": proposal_receipts,
        "compiled_proposal_hash": compiled.content_hash,
        "authoring_spec_hash": compiled.authoring_spec.content_hash,
        "snapshot_hash": dataset_description.snapshot_hash,
        "qlib_view_hash": dataset_fields.qlib_view_hash,
        "resolved_experiment_hash": registered.resolved_experiment_hash,
        "pit_audit_evidence_hash": registered.pit_audit_evidence_hash,
        "signal_artifact_hash": registered.signal_artifact_hash,
        "backtest_result_hash": registered.backtest_result_hash,
        "validation_report_hash": validation.report_hash,
        "registry_manifest_hash": registered.manifest_hash,
        "registry_index_hash": outcome.registry_index_hash,
        "interpretation_proposal_hash": interpretation.content_hash,
        "job_id": completed.job_id,
        "job_event_hashes": completed.event_hashes,
        "registry_search_hit_count": len(search.hits),
        "release_pipeline_count": release_result["independent_release_pipelines"],
        "resolved_and_authority_hashes_byte_exact": True,
        "agent_outputs_remain_proposals": True,
        "data_qualified": False,
    }
    report_hash = sha256_bytes(canonical_json_bytes(payload))
    report = {**payload, "report_hash": report_hash}
    atomic_write_bytes(
        output_root / "reports" / f"sha256-{report_hash}.json",
        canonical_json_bytes(report),
    )
    atomic_write_bytes(output_root / "report.json", canonical_json_bytes(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("tests/fixtures/synthetic_backtest_snapshot"),
    )
    parser.add_argument("--qlib-source", type=Path, default=Path(".tools/qlib-0.9.7"))
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/feasibility/proposal-p11")
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("configs/research/p11_synthetic_evidence_v1.yaml"),
    )
    parser.add_argument(
        "--authoring",
        type=Path,
        default=Path("configs/research/synthetic_validation_experiment_v1.yaml"),
    )
    parser.add_argument(
        "--research-policy",
        type=Path,
        default=Path("configs/research/synthetic_validation_policy_v1.yaml"),
    )
    parser.add_argument(
        "--validation-policy",
        type=Path,
        default=Path("configs/validation/synthetic_engineering_v1.yaml"),
    )
    parser.add_argument("--cost-policy", type=Path, default=Path("configs/backtest/cost_v1.yaml"))
    parser.add_argument(
        "--backtest-policy", type=Path, default=Path("configs/backtest/policy_v1.yaml")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.fixture_root,
                args.qlib_source,
                args.output_root,
                args.workspace,
                args.evidence,
                args.authoring,
                args.research_policy,
                args.validation_policy,
                args.cost_policy,
                args.backtest_policy,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
