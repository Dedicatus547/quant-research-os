from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from quantos.application import (
    DatasetBinding,
    ProposalChainBinding,
    ResearchMcpError,
    ResearchMcpService,
    compile_experiment_proposal,
    research_mcp_policy,
)
from quantos.contracts import (
    CampaignSegment,
    ColumnManifest,
    ConverterInputDigest,
    DatasetDescription,
    DatasetFieldCatalog,
    DataSnapshotManifest,
    EvidenceCitation,
    ExecutionJob,
    ExecutionJobState,
    ExecutionOutcome,
    ExpectedDirection,
    ExperimentExecutionRequest,
    ExperimentProposalSpec,
    ExperimentResolutionReceipt,
    ExperimentResolutionRequest,
    FactorProposalSpec,
    FalsificationCriterion,
    HypothesisProposal,
    InstrumentCodeMapping,
    JobLookupRequest,
    ObservationProposal,
    ParameterDimension,
    ProposedAttribute,
    QlibSemanticSample,
    QlibViewFile,
    QlibViewManifest,
    QlibViewSpec,
    RegisteredFeatureRef,
    RegistrySearchRequest,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SnapshotFileManifest,
    SnapshotSourceKind,
    StrategyAuthoringSpec,
    ValidationLookupRequest,
    canonical_json_bytes,
)
from quantos.contracts.campaign import CampaignStoppingRule, MultipleTestingPolicy
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.registry import RegistryService

RUNS = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
EVIDENCE = "3" * 64
BUDGET = "8" * 64


def _dataset() -> DatasetBinding:
    snapshot = DataSnapshotManifest.create(
        dataset_id="p11-synthetic",
        source_kind=SnapshotSourceKind.SYNTHETIC_FIXTURE,
        provider="structured-fixture",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        build_spec_hash="1" * 64,
        quality_policy_hash="2" * 64,
        quality_report_hash="4" * 64,
        normalizer_version="synthetic/v1",
        files=(
            SnapshotFileManifest(
                logical_path="canonical/bars.parquet",
                sha256="5" * 64,
                size_bytes=1,
                media_type="application/vnd.apache.parquet",
                table_name="bars",
                row_count=1,
                columns=(ColumnManifest(name="close", arrow_type="double", nullable=False),),
            ),
        ),
        limitations=("SYNTHETIC_DATA_NOT_LIVE_EVIDENCE",),
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    mapping = InstrumentCodeMapping(instrument_id="600000.SH", qlib_id="SH600000")
    spec = QlibViewSpec(
        source_snapshot_hash=snapshot.snapshot_hash,
        qlib_version="0.9.7",
        qlib_source_commit="6" * 40,
        dump_bin_sha256="7" * 64,
        health_check_sha256="9" * 64,
        mappings=(mapping,),
    )
    view = QlibViewManifest.create(
        source_snapshot_hash=snapshot.snapshot_hash,
        view_spec_hash=spec.content_hash,
        qlib_version=spec.qlib_version,
        qlib_source_commit=spec.qlib_source_commit,
        dump_bin_sha256=spec.dump_bin_sha256,
        health_check_sha256=spec.health_check_sha256,
        converter_inputs=(ConverterInputDigest(qlib_id="SH600000", sha256="0" * 64, row_count=1),),
        files=(QlibViewFile(logical_path="calendars/day.txt", sha256="1" * 64, size_bytes=1),),
        health_check_passed=True,
        semantic_samples=(
            QlibSemanticSample(
                qlib_id="SH600000",
                trade_date=date(2024, 1, 2),
                field="$close",
                expected=10,
                actual=10,
                passed=True,
            ),
        ),
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    return DatasetBinding(snapshot, view, spec)


def _chain(dataset: DatasetBinding) -> ProposalChainBinding:
    citation = EvidenceCitation(
        evidence_hash=EVIDENCE,
        extracted_text_hash="e" * 64,
        char_start=0,
        char_end=10,
        cited_text_hash="f" * 64,
    )
    observation = ObservationProposal(
        proposal_id="observation-p11-mcp",
        agent_run_hash=RUNS[0],
        statement="The frozen structured fixture includes adjusted closes.",
        citations=(citation,),
        limitations=("SYNTHETIC_FIXTURE",),
    )
    hypothesis = HypothesisProposal(
        proposal_id="hypothesis-p11-mcp",
        agent_run_hash=RUNS[1],
        observation_hashes=(observation.content_hash,),
        claim="A one-session return can exercise the deterministic pipeline.",
        mechanism="The structured fixture supports a bounded momentum example.",
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
    template = "6" * 64
    family = ResearchFamilySpec(
        family_id="family-p11-mcp",
        research_question="Can the frozen proposal enter the existing Qlib path?",
        hypothesis_hash=hypothesis.content_hash,
        factor_template_hash=template,
        allowed_operators=("field", "return"),
        parameter_space=(ParameterDimension(name="window", values=(1,)),),
        declared_candidate_count=1,
    )
    factor = FactorProposalSpec(
        proposal_id="factor-p11-mcp",
        agent_run_hash=RUNS[2],
        hypothesis_hash=hypothesis.content_hash,
        family_hash=family.content_hash,
        factor_template_hash=template,
        parameters=(ProposedAttribute(name="window", value=1),),
        expression=SafeQlibExpressionSpec(
            expression_id="momentum_1d",
            nodes=(
                SafeExpressionNode(node_id="price", operator="field", field_name="adjusted_close"),
                SafeExpressionNode(
                    node_id="momentum_1d", operator="return", inputs=("price",), window=1
                ),
            ),
            output_node_id="momentum_1d",
            input_lag_trading_days=0,
        ),
        registered_features=(
            RegisteredFeatureRef(
                field_name="adjusted_close",
                source_artifact_hash=dataset.snapshot.snapshot_hash,
                availability_policy_hash="7" * 64,
            ),
        ),
        rationale="Use the already admitted return template.",
        limitations=("SYNTHETIC_FIXTURE",),
    )
    campaign = ResearchCampaignSpec(
        campaign_id="campaign-p11-mcp",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=BUDGET,
        evidence_hashes=(EVIDENCE,),
        ledger_snapshot_hash="9" * 64,
        snapshot_hash=dataset.snapshot.snapshot_hash,
        qlib_view_hash=dataset.qlib_view.view_hash,
        development=ResearchSegment(start=date(2023, 1, 1), end=date(2023, 3, 31)),
        validation=ResearchSegment(start=date(2023, 4, 1), end=date(2023, 6, 30)),
        sealed_confirmation=ResearchSegment(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    experiment = ExperimentProposalSpec(
        proposal_id="synthetic-validation-feasibility-v1",
        agent_run_hash=RUNS[3],
        campaign_hash=campaign.content_hash,
        factor_proposal_hash=factor.content_hash,
        segment=CampaignSegment.SEALED_CONFIRMATION,
        evaluation_start=date(2024, 1, 1),
        evaluation_end=date(2024, 1, 31),
        strategy=StrategyAuthoringSpec(universe_index="000300.SH", top_k=1, max_weight=1),
        snapshot_hash=dataset.snapshot.snapshot_hash,
        qlib_view_hash=dataset.qlib_view.view_hash,
    )
    return ProposalChainBinding(observation, hypothesis, factor, experiment, campaign, family)


def _service(tmp_path, *, executor=None, max_queued_jobs: int = 8):
    dataset = _dataset()
    chain = _chain(dataset)
    service = ResearchMcpService(
        tmp_path / "mcp",
        datasets={dataset.snapshot.snapshot_hash: dataset},
        proposal_chains={chain.experiment.content_hash: chain},
        registry=RegistryService(tmp_path / "registry"),
        executor=executor,
        max_queued_jobs=max_queued_jobs,
    )
    return service, dataset, chain


def _resolve_request(chain: ProposalChainBinding) -> ExperimentResolutionRequest:
    compiled = compile_experiment_proposal(
        chain.observation,
        chain.hypothesis,
        chain.factor,
        chain.experiment,
        chain.campaign,
        chain.family,
        agent_run_hashes=RUNS,
    )
    return ExperimentResolutionRequest(
        idempotency_key="0" * 64,
        observation_hash=chain.observation.content_hash,
        hypothesis_hash=chain.hypothesis.content_hash,
        factor_proposal_hash=chain.factor.content_hash,
        experiment_proposal_hash=chain.experiment.content_hash,
        campaign_hash=chain.campaign.content_hash,
        family_hash=chain.family.content_hash,
        budget_hash=BUDGET,
        agent_run_hashes=RUNS,
        input_hashes=tuple(sorted({*compiled.input_hashes, *RUNS, BUDGET})),
    )


def _enqueue(service: ResearchMcpService, chain: ProposalChainBinding, *, key: str = "1" * 64):
    resolved = service.call("experiment.resolve", canonical_json_bytes(_resolve_request(chain)))
    assert isinstance(resolved, ExperimentResolutionReceipt)
    compiled_hash = resolved.compiled_proposal_hash
    compiled = compile_experiment_proposal(
        chain.observation,
        chain.hypothesis,
        chain.factor,
        chain.experiment,
        chain.campaign,
        chain.family,
        agent_run_hashes=RUNS,
    )
    request = ExperimentExecutionRequest(
        idempotency_key=key,
        compiled_proposal_hash=compiled_hash,
        agent_run_hash=RUNS[-1],
        campaign_hash=chain.campaign.content_hash,
        budget_hash=BUDGET,
        input_hashes=tuple(
            sorted(
                {
                    *compiled.input_hashes,
                    compiled_hash,
                    RUNS[-1],
                    chain.campaign.content_hash,
                    BUDGET,
                }
            )
        ),
        timeout_seconds=10,
    )
    return service.call("experiment.request_execution", canonical_json_bytes(request)), request


def test_policy_is_only_the_p11_typed_application_surface() -> None:
    values = tuple(item.value for item in research_mcp_policy().capabilities)
    assert values == tuple(sorted(values))
    assert set(values) == {
        "dataset.describe",
        "dataset.fields",
        "experiment.request_execution",
        "experiment.resolve",
        "job.get",
        "registry.get",
        "registry.search",
        "validation.get",
    }


def test_dataset_capabilities_return_verified_hash_bound_metadata(tmp_path) -> None:
    service, dataset, _ = _service(tmp_path)
    payload = canonical_json_bytes(
        {
            "schema_version": "dataset-lookup-request/v1",
            "snapshot_hash": dataset.snapshot.snapshot_hash,
            "qlib_view_hash": dataset.qlib_view.view_hash,
        }
    )
    description = service.call("dataset.describe", payload)
    fields = service.call("dataset.fields", payload)

    assert isinstance(description, DatasetDescription)
    assert description.source_kind is SnapshotSourceKind.SYNTHETIC_FIXTURE
    assert isinstance(fields, DatasetFieldCatalog)
    assert "adjusted_close" in {item.field_name for item in fields.fields}
    assert "path" not in json.dumps(fields.model_dump(mode="json"))


def test_resolution_is_deterministic_immutable_and_idempotent(tmp_path) -> None:
    service, _, chain = _service(tmp_path)
    request = _resolve_request(chain)

    first = service.call("experiment.resolve", canonical_json_bytes(request))
    second = service.call("experiment.resolve", canonical_json_bytes(request))

    assert first == second
    assert isinstance(first, ExperimentResolutionReceipt)
    assert (tmp_path / "mcp" / "compiled" / f"sha256-{first.compiled_proposal_hash}.json").is_file()
    changed = request.model_copy(update={"agent_run_hashes": (*RUNS, "f" * 64)})
    changed = changed.model_copy(
        update={"input_hashes": tuple(sorted({*changed.input_hashes, "f" * 64}))}
    )
    with pytest.raises(ResearchMcpError) as conflict:
        service.call("experiment.resolve", canonical_json_bytes(changed))
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT


def test_execution_queue_projects_success_from_trusted_executor(tmp_path) -> None:
    outcome = ExecutionOutcome(
        run_status=RunStatus.SUCCEEDED,
        validation_verdict=ValidationVerdict.REJECT,
        validation_report_hash="1" * 64,
        registry_manifest_hash="2" * 64,
        registry_index_hash="3" * 64,
        compute_seconds=2,
    )
    service, _, chain = _service(tmp_path, executor=lambda _compiled: outcome)
    receipt, request = _enqueue(service, chain)
    repeated = service.call("experiment.request_execution", canonical_json_bytes(request))

    assert receipt == repeated
    queued = service.call(
        "job.get",
        canonical_json_bytes(JobLookupRequest(job_id=receipt.job_id)),  # type: ignore[attr-defined]
    )
    assert isinstance(queued, ExecutionJob)
    assert queued.state is ExecutionJobState.QUEUED
    completed = service.run_next()
    assert completed is not None
    assert completed.state is ExecutionJobState.SUCCEEDED
    assert completed.outcome == outcome
    assert len(completed.event_hashes) == 3


def test_queued_execution_survives_service_restart(tmp_path) -> None:
    outcome = ExecutionOutcome(
        run_status=RunStatus.SUCCEEDED,
        validation_verdict=ValidationVerdict.REJECT,
        validation_report_hash="1" * 64,
        registry_manifest_hash="2" * 64,
        registry_index_hash="3" * 64,
        compute_seconds=1,
    )
    first, dataset, chain = _service(tmp_path)
    receipt, _ = _enqueue(first, chain)
    restarted = ResearchMcpService(
        tmp_path / "mcp",
        datasets={dataset.snapshot.snapshot_hash: dataset},
        proposal_chains={chain.experiment.content_hash: chain},
        executor=lambda _compiled: outcome,
    )

    completed = restarted.run_next()

    assert completed is not None
    assert completed.job_id == receipt.job_id  # type: ignore[attr-defined]
    assert completed.state is ExecutionJobState.SUCCEEDED


@pytest.mark.parametrize(
    ("executor", "expected"),
    [
        (lambda _compiled: (_ for _ in ()).throw(RuntimeError("boom")), ExecutionJobState.FAILED),
        (lambda _compiled: (_ for _ in ()).throw(TimeoutError()), ExecutionJobState.TIMED_OUT),
    ],
)
def test_execution_failures_never_become_a_verdict(tmp_path, executor, expected) -> None:
    service, _, chain = _service(tmp_path, executor=executor)
    _enqueue(service, chain)
    job = service.run_next()

    assert job is not None
    assert job.state is expected
    if expected is ExecutionJobState.FAILED:
        assert job.outcome is not None
        assert job.outcome.run_status is RunStatus.FAILED
        assert job.outcome.validation_verdict is ValidationVerdict.NOT_EVALUATED
    else:
        assert job.outcome is None


def test_queue_is_bounded_and_queued_job_can_be_cancelled(tmp_path) -> None:
    service, _, chain = _service(tmp_path, max_queued_jobs=1)
    first, _ = _enqueue(service, chain)
    with pytest.raises(ResearchMcpError) as full:
        _enqueue(service, chain, key="2" * 64)
    assert full.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED

    cancelled = service.cancel(first.job_id)  # type: ignore[attr-defined]
    assert cancelled.state is ExecutionJobState.CANCELLED
    assert service.run_next() is None


def test_read_surfaces_fail_closed_and_registry_search_is_bounded(tmp_path) -> None:
    service, _, _ = _service(tmp_path)
    result = service.call("registry.search", canonical_json_bytes(RegistrySearchRequest(limit=1)))
    assert result.hits == ()  # type: ignore[attr-defined]

    with pytest.raises(ResearchMcpError) as missing:
        service.call(
            "validation.get",
            canonical_json_bytes(ValidationLookupRequest(validation_report_hash="f" * 64)),
        )
    assert missing.value.reason_code is ReasonCode.SOURCE_INCOMPLETE


def test_security_boundary_denies_paths_authority_and_unmapped_capabilities(tmp_path) -> None:
    service, dataset, _ = _service(tmp_path)
    base = {
        "schema_version": "dataset-lookup-request/v1",
        "snapshot_hash": dataset.snapshot.snapshot_hash,
        "qlib_view_hash": dataset.qlib_view.view_hash,
    }
    for field, expected in (
        ("path", ReasonCode.SCHEMA_INVALID),
        ("force_pass", ReasonCode.AUTHORITY_FIELD_DENIED),
        ("token", ReasonCode.SECRET_ACCESS_DENIED),
    ):
        payload = {**base, field: "/tmp/escape"}
        with pytest.raises(ResearchMcpError) as denied:
            service.call("dataset.describe", canonical_json_bytes(payload))
        assert denied.value.reason_code is expected
    with pytest.raises(ResearchMcpError) as shell:
        service.call("shell.execute", b"{}")
    assert shell.value.reason_code is ReasonCode.CAPABILITY_DENIED
