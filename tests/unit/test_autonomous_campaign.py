from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.application.autonomous import (
    AutonomousAgentExchangeStore,
    AutonomousCampaignOrchestrator,
    AutonomousLoopReportStore,
    AutonomousOrchestrationError,
    CampaignEventStore,
    ReplayAgentDriver,
    ScriptedAgentDriver,
)
from quantos.application.campaign_selection import (
    CampaignSelectionService,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import CampaignChainEvent, ResearchCampaignGovernor
from quantos.application.enumeration import (
    enumerate_research_family,
    exact_expression_hash,
    structural_expression_hash,
)
from quantos.application.ledger import ResearchLedgerService
from quantos.application.specs import resolve_experiment
from quantos.config import load_yaml_contract
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE,
    P14DQ_LIMITATIONS,
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousAgentExchangeArtifact,
    AutonomousAgentRequest,
    AutonomousAgentRunPolicy,
    AutonomousBudgetView,
    AutonomousCampaignPolicy,
    AutonomousCandidateProposal,
    AutonomousExecutionBindings,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    AutonomousLoopState,
    AutonomousSelectionFinalizationProfile,
    AutonomousStoppingReason,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    CampaignStoppingRule,
    MultipleTestingPolicy,
    ParameterDimension,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    TrialOutcome,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionVerdict,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.enumeration import (
    CandidateEnumerationManifest,
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchTemplateParameterSlot,
)
from quantos.contracts.ledger import (
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    ResearchContextBudgetPolicy,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSnapshot,
)
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.qlib_view import (
    ConverterInputDigest,
    QlibSemanticSample,
    QlibViewFile,
    QlibViewManifest,
)
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    StrategyAuthoringSpec,
)
from quantos.contracts.status import ReasonCode
from quantos.research.qlib import ResearchResultArtifactBuilder
from quantos.research.qlib import result as result_module

ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _trading_dates() -> tuple[date, ...]:
    result: list[date] = []
    current = date(2021, 1, 4)
    while len(result) < 40:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="autonomous-delta-template",
        expression_schema_version="safe-qlib-expression/v2",
        nodes=(
            ResearchFactorTemplateNode(
                node_id="price", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
            ),
            ResearchFactorTemplateNode(
                node_id="factor", operator=SafeQlibOperator.DELTA, inputs=("price",)
            ),
        ),
        output_node_id="factor",
        parameter_slots=(
            ResearchTemplateParameterSlot(name="window", node_id="factor", field="window"),
        ),
    )


def _write_view(root: Path, dates: tuple[date, ...]) -> tuple[QlibViewManifest, Path]:
    calendar = "\n".join(item.isoformat() for item in dates).encode() + b"\n"
    view = QlibViewManifest.create(
        source_snapshot_hash="4" * 64,
        view_spec_hash="5" * 64,
        qlib_version="0.9.7",
        qlib_source_commit="6" * 40,
        dump_bin_sha256="7" * 64,
        health_check_sha256="8" * 64,
        converter_inputs=(
            ConverterInputDigest(qlib_id="SH600000", sha256="9" * 64, row_count=len(dates)),
        ),
        files=(
            QlibViewFile(
                logical_path="calendars/day.txt",
                sha256=sha256_bytes(calendar),
                size_bytes=len(calendar),
            ),
        ),
        health_check_passed=True,
        semantic_samples=(
            QlibSemanticSample(
                qlib_id="SH600000",
                trade_date=dates[0],
                field="$close",
                expected=10.0,
                actual=10.0,
                passed=True,
            ),
        ),
        created_at=NOW,
    )
    path = root / f"sha256-{view.view_hash}"
    (path / "calendars").mkdir(parents=True)
    (path / "calendars" / "day.txt").write_bytes(calendar)
    (path / "manifest.json").write_bytes(canonical_json_bytes(view.model_dump(mode="python")))
    return view, path


class _ExecutionPort:
    def __init__(
        self,
        outcomes: tuple[TrialOutcome, ...] = (TrialOutcome.PASS, TrialOutcome.PASS),
    ) -> None:
        self.outcomes = outcomes
        self.requests: list[AutonomousExecutionRequest] = []
        self.cache: dict[str, AutonomousExecutionResult] = {}

    def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
        self.requests.append(request)
        prior = self.cache.get(request.idempotency_key)
        if prior is not None:
            if prior.request_hash != request.content_hash:
                raise AssertionError("execution idempotency key changed inputs")
            return prior
        outcome = self.outcomes[min(len(self.requests) - 1, len(self.outcomes) - 1)]
        result = AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=outcome,
            execution_requested=outcome is not TrialOutcome.PIT_REJECT,
            compute_seconds=1,
            evidence_hashes=("d" * 64,) if outcome is TrialOutcome.PASS else (),
        )
        self.cache[request.idempotency_key] = result
        return result


@dataclass
class _Inputs:
    campaign: ResearchCampaignSpec
    family: ResearchFamilySpec
    budget: ResearchBudgetSpec
    template: ResearchFactorTemplateSpec
    manifest: CandidateEnumerationManifest
    initial_snapshot: ResearchLedgerSnapshot
    ledger: ResearchLedgerService
    ledger_id: str
    search_policy: ResearchLedgerSearchPolicy
    context_budget: ResearchContextBudgetPolicy
    campaign_policy: AutonomousCampaignPolicy
    agent_policy: AutonomousAgentRunPolicy
    selection: CampaignSelectionService
    initial_events: tuple[CampaignChainEvent, ...]
    paths: dict[str, Path]
    execution_bindings: AutonomousExecutionBindings

    def orchestrator(
        self,
        tmp_path: Path,
        script: tuple[AutonomousCandidateProposal | bytes, ...],
        execution: _ExecutionPort | None = None,
        selection_finalization_profile: AutonomousSelectionFinalizationProfile = (
            AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE
        ),
    ) -> AutonomousCampaignOrchestrator:
        return AutonomousCampaignOrchestrator(
            campaign=self.campaign,
            family=self.family,
            budget=self.budget,
            template=self.template,
            manifest=self.manifest,
            initial_ledger_snapshot=self.initial_snapshot,
            ledger_service=self.ledger,
            ledger_id=self.ledger_id,
            search_policy=self.search_policy,
            context_budget=self.context_budget,
            campaign_policy=self.campaign_policy,
            agent_run_policy=self.agent_policy,
            agent_driver=ScriptedAgentDriver(script, self.agent_policy),
            execution_port=execution or _ExecutionPort(),
            exchange_root=self.paths["exchanges"],
            event_root=self.paths["events"],
            selection_service=self.selection,
            selection_artifact_root=self.paths["selection-reports"],
            autonomous_report_root=self.paths["loop-reports"],
            execution_bindings=self.execution_bindings,
            selection_finalization_profile=selection_finalization_profile,
        )


def _inputs(
    root: Path,
    *,
    max_trials: int = 3,
    max_agent_runs: int = 3,
    max_distinct_candidates: int = 2,
    max_executions: int | None = None,
    max_validation_rounds: int | None = None,
    max_compute_seconds: int = 30,
    allow_manual_stop: bool = False,
) -> _Inputs:
    ledger_id = "autonomous-ledger"
    ledger = ResearchLedgerService(root / "ledger")
    evidence_bytes = canonical_json_bytes({"title": "campaign source", "body": "frozen alpha"})
    evidence_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(evidence_bytes),
        media_type="application/json",
        source_domain="autonomous-fixture",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    ledger.append(
        ledger_id=ledger_id,
        node_id="fixture-evidence",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=evidence_ref,
        object_bytes=evidence_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW,
    )
    initial_snapshot = ledger.verify(ledger_id, created_at=NOW + timedelta(seconds=1))
    template = _template()
    family = ResearchFamilySpec(
        family_id="autonomous-family",
        research_question="Does a bounded delta candidate generalize?",
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )
    manifest = enumerate_research_family(family, template)
    budget = ResearchBudgetSpec(
        budget_id="autonomous-budget",
        max_trials=max_trials,
        max_distinct_candidates=max_distinct_candidates,
        max_agent_runs=max_agent_runs,
        max_executions=max_executions if max_executions is not None else max_trials,
        max_validation_rounds=(
            max_validation_rounds if max_validation_rounds is not None else max_trials
        ),
        max_compute_seconds=max_compute_seconds,
    )
    dates = _trading_dates()
    view, view_path = _write_view(root / "views", dates)
    campaign = ResearchCampaignSpec(
        campaign_id="autonomous-campaign",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=(evidence_ref.object_hash,),
        ledger_snapshot_hash=initial_snapshot.content_hash,
        snapshot_hash=view.source_snapshot_hash,
        qlib_view_hash=view.view_hash,
        development=ResearchSegment(start=date(2020, 1, 1), end=date(2020, 12, 31)),
        validation=ResearchSegment(start=dates[0], end=dates[-1]),
        sealed_confirmation=ResearchSegment(start=date(2022, 1, 1), end=date(2022, 12, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    policy = ResearchLedgerSearchPolicy(
        policy_id="autonomous-search-policy",
        allowed_node_kinds=tuple(sorted(ResearchLedgerNodeKind, key=str)),
        allowed_authorities=tuple(sorted(LedgerAssertionAuthority, key=str)),
        allow_cross_campaign_history=True,
        max_query_bytes=4096,
        max_query_terms=32,
        max_hit_bytes=65536,
        max_results=50,
        max_serialized_bytes=262144,
        max_index_entries=1000,
        max_terms_per_object=4096,
        max_index_serialized_bytes=16777216,
    )
    context_budget = ResearchContextBudgetPolicy(
        policy_id="autonomous-context-budget",
        max_items=50,
        max_item_bytes=65536,
        max_serialized_bytes=262144,
    )
    campaign_policy = AutonomousCampaignPolicy(
        policy_id="autonomous-campaign-policy",
        context_query="campaign source",
        readable_campaign_hashes=(campaign.content_hash,),
        trial_segment=CampaignSegment.VALIDATION,
        allow_agent_requested_manual_close=allow_manual_stop,
        max_agent_request_bytes=262144,
    )
    agent_policy = AutonomousAgentRunPolicy(
        capability_policy_hash="a" * 64,
        requested_model_configuration_hash="b" * 64,
        tool_schema_hash="c" * 64,
        instruction_hashes=tuple(sorted(("e" * 64, "f" * 64))),
        skill_hash="1" * 64,
        sandbox_policy_hash="2" * 64,
        permission_policy_hash="3" * 64,
        runtime_policy_hash="4" * 64,
        harness_identifier="scripted-agent-driver/v1",
        provider_model_identifier="scripted-fixture/v1",
        model_snapshot_immutable=True,
    )
    multiple_policy = MultipleTestingPolicySpec(seed="9" * 64)
    selection_policy = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple_policy.content_hash,
        direction="POSITIVE",
    )
    selection = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple_policy,
        selection_policy,
        view_path,
    )
    governor = ResearchCampaignGovernor(family, template, manifest)
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("90000000-0000-0000-0000-000000000001"),
        occurred_at=NOW + timedelta(seconds=2),
    )
    plan_event, _ = selection.freeze_plan(
        governor,
        (activation,),
        event_id=UUID("90000000-0000-0000-0000-000000000002"),
        occurred_at=NOW + timedelta(seconds=3),
        artifact_root=root / "selection-plans",
    )
    return _Inputs(
        campaign=campaign,
        family=family,
        budget=budget,
        template=template,
        manifest=manifest,
        initial_snapshot=initial_snapshot,
        ledger=ledger,
        ledger_id=ledger_id,
        search_policy=policy,
        context_budget=context_budget,
        campaign_policy=campaign_policy,
        agent_policy=agent_policy,
        selection=selection,
        initial_events=(activation, plan_event),
        paths={
            "exchanges": root / "agent-exchanges",
            "events": root / "campaign-events",
            "selection-reports": root / "selection-reports",
            "loop-reports": root / "loop-reports",
            "view": view_path,
        },
        execution_bindings=AutonomousExecutionBindings(
            dataset_id="synthetic-p14d-test",
            authoring_hash="8" * 64,
            execution_policy_hash="f" * 64,
            pit_policy_hash="1" * 64,
            research_policy_hash="2" * 64,
            validation_policy_hash="3" * 64,
            cost_policy_hash="4" * 64,
            backtest_policy_hash="5" * 64,
            code_commit_hash="6" * 40,
            lockfile_hash="7" * 64,
            qlib_version="0.9.7",
        ),
    )


def _proposal(inputs: _Inputs, index: int, *, stop: bool = False) -> AutonomousCandidateProposal:
    candidate = inputs.manifest.candidates[index]
    return AutonomousCandidateProposal(
        campaign_hash=inputs.campaign.content_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=candidate.expression,
        exact_expression_hash=candidate.exact_expression_hash,
        structural_expression_hash=candidate.structural_expression_hash,
        rationale=f"scripted candidate {index}",
        request_stop=stop,
    )


def test_agent_contract_is_proposal_only_and_extra_authority_fields_are_rejected(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    proposal = _proposal(inputs, 0)
    base = proposal.model_dump(mode="python")
    for field, value in (
        ("verdict", "PASS"),
        ("campaign_state", "CLOSED"),
        ("budget", {"max_trials": 999}),
        ("sealed_access", True),
        ("artifact_root", "/tmp/authority"),
        ("secret", "not-allowed"),
    ):
        with pytest.raises(ValidationError):
            AutonomousCandidateProposal.model_validate({**base, field: value})
    assert "verdict" not in AutonomousCandidateProposal.model_fields
    assert "campaign_state" not in AutonomousAgentRequest.model_fields
    assert "sealed_access" not in AutonomousAgentRequest.model_fields
    with pytest.raises(ValidationError):
        AutonomousBudgetView(
            max_trials=2,
            used_trials=1,
            remaining_trials=0,
            max_agent_runs=2,
            used_agent_runs=0,
            remaining_agent_runs=2,
            max_distinct_candidates=2,
            used_distinct_candidates=0,
            remaining_distinct_candidates=2,
            max_executions=2,
            used_executions=0,
            remaining_executions=2,
            max_validation_rounds=2,
            used_validation_rounds=0,
            remaining_validation_rounds=2,
            max_compute_seconds=2,
            used_compute_seconds=0,
            remaining_compute_seconds=2,
        )
    with pytest.raises(ValidationError):
        AutonomousExecutionResult(
            request_hash="a" * 64,
            outcome=TrialOutcome.PASS,
            execution_requested=True,
            compute_seconds=0,
        )


def test_scripted_loop_updates_ledger_and_next_context_uses_new_snapshot(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    execution = _ExecutionPort((TrialOutcome.PASS, TrialOutcome.PASS))
    orchestrator = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
        execution,
    )
    report, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))

    assert report.stopping_reason is AutonomousStoppingReason.ALL_CANDIDATES_TERMINAL
    assert report.state is AutonomousLoopState.SELECTION_COMPLETE
    assert report.agent_run_count == report.trial_count == 2
    assert report.initial_ledger_snapshot_hash == inputs.initial_snapshot.content_hash
    assert report.final_ledger_snapshot_hash != report.initial_ledger_snapshot_hash
    assert report.selection_report_hash is not None
    assert report.selection_event_hash is None
    assert report.sealed_confirmation_authority is False
    trials = [
        event.trial for event in events if isinstance(event, ResearchCampaignEvent) and event.trial
    ]
    assert [trial.outcome for trial in trials] == [TrialOutcome.PASS, TrialOutcome.PASS]
    assert not any(
        isinstance(event, ResearchCampaignEvent) and event.event_type.value == "OOSAccessed"
        for event in events
    )
    store = AutonomousAgentExchangeStore(inputs.paths["exchanges"], inputs.agent_policy)
    exchanges = [store.for_run_hash(trial.agent_run_hash) for trial in trials]
    assert all(item is not None for item in exchanges)
    assert '"request_stop"' in exchanges[0].request.allowed_proposal_schema_json
    assert '"verdict"' not in exchanges[0].request.allowed_proposal_schema_json
    snapshots = [item.request.context_pack.ledger_snapshot_hash for item in exchanges if item]
    assert snapshots[0] == inputs.initial_snapshot.content_hash
    assert snapshots[1] != snapshots[0]
    final = inputs.ledger.verify(inputs.ledger_id, created_at=NOW + timedelta(minutes=1))
    assert report.final_ledger_snapshot_hash == final.content_hash
    report_store = AutonomousLoopReportStore(inputs.paths["loop-reports"])
    assert report_store.verify(report.content_hash) == report
    assert report_store.publish(report).name == f"sha256-{report.content_hash}.json"
    assert (inputs.paths["loop-reports"] / f"sha256-{report.content_hash}.json").is_file()


def test_unauthorized_sealed_ledger_object_never_enters_context_pack(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    sealed_bytes = canonical_json_bytes({"body": "campaign source sealed confirmation"})
    sealed_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(sealed_bytes),
        media_type="application/json",
        source_domain="autonomous-fixture",
        access=LedgerObjectAccess.SEALED_CONFIRMATION,
        campaign_hash=inputs.campaign.content_hash,
        contamination_hashes=("c" * 64,),
    )
    inputs.ledger.append(
        ledger_id=inputs.ledger_id,
        node_id="sealed-fixture",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=sealed_ref,
        object_bytes=sealed_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW + timedelta(seconds=4),
    )
    inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),)).run(
        inputs.initial_events, started_at=NOW + timedelta(seconds=30)
    )
    exchange_path = next(inputs.paths["exchanges"].glob("sha256-*.json"))
    exchange = AutonomousAgentExchangeArtifact.model_validate_json(exchange_path.read_bytes())
    assert all(
        item.object_ref.object_hash != sealed_ref.object_hash
        for item in exchange.request.context_pack.items
    )


@pytest.mark.parametrize("force_no_selection", (False, True))
@pytest.mark.parametrize("report_only", (False, True))
def test_p14c_handoff_freezes_or_closes_without_sealed_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force_no_selection: bool,
    report_only: bool,
) -> None:
    inputs = _inputs(tmp_path)
    dates = _trading_dates()
    view = QlibViewManifest.model_validate_json(
        (inputs.paths["view"] / "manifest.json").read_bytes()
    )
    result_root = tmp_path / "research-results"
    result_root.mkdir()
    research_policy = load_yaml_contract(ROOT / "configs/research/policy_v1.yaml", ResearchPolicy)
    resolved_by_signal: dict[str, str] = {}
    monkeypatch.setattr(
        result_module,
        "verify_signal_artifact",
        lambda path: SimpleNamespace(
            resolved_experiment_hash=resolved_by_signal[str(path)],
            artifact_hash="2" * 64,
        ),
    )
    result_hashes: dict[str, str] = {}
    builder = ResearchResultArtifactBuilder()
    for index, candidate in enumerate(inputs.manifest.candidates):
        authoring = ExperimentAuthoringSpec(
            experiment_id=f"autonomous-selected-{index}",
            evaluation_start=dates[0],
            evaluation_end=dates[-1],
            expression=candidate.expression,
            strategy=StrategyAuthoringSpec(
                universe_index="000300.SH",
                top_k=50,
                input_lag_trading_days=candidate.expression.input_lag_trading_days,
            ),
        )
        resolved = resolve_experiment(
            authoring,
            snapshot_hash=inputs.campaign.snapshot_hash,
            qlib_view_hash=inputs.campaign.qlib_view_hash,
            qlib_version=view.qlib_version,
            qlib_view_spec_hash=view.view_spec_hash,
            pit_audit_evidence_hash="c" * 64,
            research_policy_hash=research_policy.content_hash,
            validation_policy_hash="d" * 64,
            cost_policy_hash="e" * 64,
            backtest_policy_hash="f" * 64,
            code_commit_hash="0" * 40,
            lockfile_hash="1" * 64,
        )
        native = tmp_path / f"native-{index}"
        (native / "sig_analysis").mkdir(parents=True)
        row_index = pd.MultiIndex.from_tuples(
            [("SH600000", pd.Timestamp(dates[0]))], names=("instrument", "datetime")
        )
        pd.DataFrame({"score": [0.2]}, index=row_index).to_pickle(native / "pred.pkl")
        pd.DataFrame({"LABEL0": [0.1]}, index=row_index).to_pickle(native / "label.pkl")
        pd.Series([0.1 + index], index=[pd.Timestamp(dates[0])]).to_pickle(
            native / "sig_analysis" / "ic.pkl"
        )
        if force_no_selection:
            rank_ic = tuple(0.1 if position % 2 else -0.1 for position in range(40))
        elif index == 0:
            rank_ic = tuple(0.45 + ((position * 17) % 41 - 20) / 1000 for position in range(40))
        else:
            rank_ic = tuple(-0.3 + ((position * 19) % 37 - 18) / 1000 for position in range(40))
        pd.Series(
            rank_ic,
            index=pd.to_datetime([item.isoformat() for item in dates]),
        ).to_pickle(native / "sig_analysis" / "ric.pkl")
        (native / "metrics.json").write_bytes(
            canonical_json_bytes({"IC": 0.1, "ICIR": 1.0, "Rank IC": 0.2, "Rank ICIR": 2.0})
        )
        signal_path = tmp_path / f"signal-{index}"
        resolved_by_signal[str(signal_path)] = resolved.content_hash
        research_result = builder.build(
            resolved,
            research_policy,
            signal_path,
            native,
            result_root,
            qlib_run_id=f"autonomous-selected-run-{index}",
            label_expression="Ref($close,-1)/$close-1",
            created_at=NOW,
        )
        result_hashes[candidate.content_hash] = research_result.manifest.artifact_hash
    inputs.selection.research_results_roots = (result_root,)

    class _ResearchResultExecutionPort:
        def verify_preselection_dq_trials(self, events: object) -> None:
            assert events

        def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
            return AutonomousExecutionResult(
                request_hash=request.content_hash,
                outcome=TrialOutcome.PASS,
                execution_requested=True,
                compute_seconds=1,
                evidence_hashes=(result_hashes[request.candidate.content_hash],),
            )

    report, events = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
        _ResearchResultExecutionPort(),  # type: ignore[arg-type]
        selection_finalization_profile=(
            P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
            if report_only
            else AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE
        ),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))

    closes_campaign = force_no_selection or report_only
    expected_state = (
        AutonomousLoopState.SELECTION_COMPLETE
        if closes_campaign
        else AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION
    )
    assert report.state is expected_state
    assert report.selection_report_hash is not None
    assert (report.selection_event_hash is None) is closes_campaign
    assert report.sealed_confirmation_authority is False
    assert (report.limitations == P14DQ_LIMITATIONS) is report_only
    report_path = next(
        path for path in inputs.paths["selection-reports"].iterdir() if path.is_dir()
    )
    selection_report = verify_selection_report_artifact(report_path)
    assert selection_report.verdict is (
        CampaignSelectionVerdict.NO_SELECTION
        if force_no_selection
        else CampaignSelectionVerdict.SELECTED
    )
    selection_events = [
        event
        for event in events
        if isinstance(event, CampaignSelectionEvent) and event.event_type.value == "SelectionFrozen"
    ]
    assert len(selection_events) == (0 if closes_campaign else 1)
    close_events = [
        event
        for event in events
        if isinstance(event, ResearchCampaignEvent)
        and event.event_type is CampaignEventType.CLOSED
    ]
    assert len(close_events) == int(closes_campaign)
    verdict_nodes = [
        node
        for node in inputs.ledger._load_and_verify()[inputs.ledger_id]
        if node.node_kind is ResearchLedgerNodeKind.CAMPAIGN_SELECTION_REPORT
        and node.authority is LedgerAssertionAuthority.DETERMINISTIC_VERDICT
        and node.verdict_report_hash == report.selection_report_hash
    ]
    assert len(verdict_nodes) == 1
    trial_events = [
        event
        for event in events
        if isinstance(event, ResearchCampaignEvent)
        and event.event_type is CampaignEventType.TRIAL_RECORDED
        and event.trial is not None
    ]
    exchange_store = AutonomousAgentExchangeStore(inputs.paths["exchanges"], inputs.agent_policy)
    exchanges = [exchange_store.for_run_hash(event.trial.agent_run_hash) for event in trial_events]
    assert all(exchange is not None for exchange in exchanges)
    assert all(
        (
            P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash
            in exchange.request.relevant_policy_hashes
        )
        is report_only
        for exchange in exchanges
        if exchange is not None
    )
    assert not any(
        isinstance(event, ResearchCampaignEvent) and event.event_type.value == "OOSAccessed"
        for event in events
    )
    assert not any(
        isinstance(event, ResearchCampaignEvent) and event.event_type.value == "OOSAccessed"
        for event in events
    )


def test_agent_stop_request_is_policy_gated_and_never_stops_by_itself(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=False)
    orchestrator = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0, stop=True), _proposal(inputs, 1)),
    )
    report, _ = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.ALL_CANDIDATES_TERMINAL
    assert report.agent_run_count == 2


def test_manual_close_requires_policy_acceptance_after_trial_accounting(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),))
    report, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert (
        report.stopping_reason is AutonomousStoppingReason.MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY
    )
    assert report.trial_count == 1
    assert report.state is AutonomousLoopState.SELECTION_COMPLETE
    assert not any(
        isinstance(event, CampaignSelectionEvent) and event.event_type.value == "SelectionFrozen"
        for event in events
    )


def test_schema_invalid_proposal_is_accounted_and_loop_continues(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    candidate = inputs.manifest.candidates[0]
    invalid = canonical_json_bytes(
        {
            "schema_version": "autonomous-candidate-proposal/v1",
            "campaign_hash": inputs.campaign.content_hash,
            "candidate_hash": candidate.content_hash,
            "verdict": "PASS",
        }
    )
    execution = _ExecutionPort((TrialOutcome.PASS,))
    orchestrator = inputs.orchestrator(
        tmp_path,
        (invalid, _proposal(inputs, 1, stop=True)),
        execution,
    )
    report, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trials = [
        event.trial for event in events if isinstance(event, ResearchCampaignEvent) and event.trial
    ]
    assert [trial.outcome for trial in trials] == [TrialOutcome.SCHEMA_INVALID, TrialOutcome.PASS]
    assert not trials[0].execution_requested
    assert len(execution.requests) == 1
    assert report.agent_run_count == 2


def test_candidate_outside_frozen_manifest_fails_closed(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    candidate = inputs.manifest.candidates[0]
    proposal = _proposal(inputs, 0).model_dump(mode="python")
    proposal["candidate_hash"] = "f" * 64
    raw = canonical_json_bytes(proposal)
    orchestrator = inputs.orchestrator(tmp_path, (raw,))
    with pytest.raises(AutonomousOrchestrationError) as rejected:
        orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert rejected.value.reason_code is ReasonCode.SCHEMA_INVALID
    assert inputs.manifest.candidates[0] == candidate  # frozen manifest was not mutated


@pytest.mark.parametrize(
    ("outcome", "expected_execution"),
    (
        (TrialOutcome.PIT_REJECT, False),
        (TrialOutcome.EXECUTION_FAILED, True),
        (TrialOutcome.SOFT_REJECT, True),
    ),
)
def test_deterministic_research_outcomes_remain_campaign_trials(
    tmp_path: Path, outcome: TrialOutcome, expected_execution: bool
) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    executor = _ExecutionPort((outcome,))
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),), executor)
    report, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trial = next(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    assert trial.outcome is outcome
    assert trial.execution_requested is expected_execution
    assert report.trial_count == 1


def test_duplicate_candidate_attempt_consumes_trial_without_reexecution(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    execution = _ExecutionPort((TrialOutcome.PASS, TrialOutcome.PASS))
    repeated = _proposal(inputs, 0)
    orchestrator = inputs.orchestrator(
        tmp_path,
        (repeated, repeated, _proposal(inputs, 1)),
        execution,
    )
    report, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trials = [
        event.trial for event in events if isinstance(event, ResearchCampaignEvent) and event.trial
    ]
    assert [item.outcome for item in trials] == [
        TrialOutcome.PASS,
        TrialOutcome.DUPLICATE_CANDIDATE,
        TrialOutcome.PASS,
    ]
    assert not trials[1].execution_requested
    assert len(execution.requests) == 2
    assert report.trial_count == 3
    assert report.state is AutonomousLoopState.SELECTION_COMPLETE


def test_budget_limit_stops_before_an_extra_agent_run(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        max_trials=1,
        max_agent_runs=1,
        max_distinct_candidates=1,
    )
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0),))
    report, _ = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.BUDGET_EXHAUSTED
    assert report.agent_run_count == report.trial_count == 1
    assert report.budget.remaining_agent_runs == 0


def test_max_agent_runs_is_enforced_independently_of_trial_budget(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        max_trials=3,
        max_agent_runs=1,
        max_distinct_candidates=2,
    )
    report, _ = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.BUDGET_EXHAUSTED
    assert report.agent_run_count == report.trial_count == 1
    assert report.budget.remaining_trials == 2
    assert report.budget.remaining_agent_runs == 0


def test_max_trials_is_enforced_independently_of_agent_run_budget(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        max_trials=1,
        max_agent_runs=3,
        max_distinct_candidates=1,
    )
    report, _ = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.BUDGET_EXHAUSTED
    assert report.agent_run_count == report.trial_count == 1
    assert report.budget.remaining_trials == 0
    assert report.budget.remaining_agent_runs == 2


def test_max_distinct_candidates_is_enforced_by_campaign_governor(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        max_trials=3,
        max_agent_runs=3,
        max_distinct_candidates=1,
    )
    report, _ = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.BUDGET_EXHAUSTED
    assert report.agent_run_count == report.trial_count == 1
    assert report.budget.remaining_distinct_candidates == 0


def test_execution_and_compute_budget_stops_before_an_extra_run(tmp_path: Path) -> None:
    inputs = _inputs(
        tmp_path,
        max_trials=3,
        max_agent_runs=3,
        max_distinct_candidates=2,
        max_executions=1,
        max_validation_rounds=1,
        max_compute_seconds=1,
    )
    report, _ = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.stopping_reason is AutonomousStoppingReason.BUDGET_EXHAUSTED
    assert report.agent_run_count == report.trial_count == 1
    assert report.budget.remaining_executions == 0
    assert report.budget.remaining_validation_rounds == 0
    assert report.budget.remaining_compute_seconds == 0


def test_restart_reuses_persisted_exchange_and_partial_campaign_chain(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    execution = _ExecutionPort((TrialOutcome.PASS, TrialOutcome.PASS))
    first = inputs.orchestrator(tmp_path, (_proposal(inputs, 0),), execution)
    with pytest.raises(AutonomousOrchestrationError):
        first.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    persisted = first.event_store.load(first.governor, inputs.campaign, inputs.budget)
    assert (
        sum(
            isinstance(event, ResearchCampaignEvent) and event.trial is not None
            for event in persisted
        )
        == 1
    )

    resumed = inputs.orchestrator(
        tmp_path,
        (_proposal(inputs, 0), _proposal(inputs, 1)),
        execution,
    )
    report, events = resumed.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert report.trial_count == 2
    assert report.agent_run_count == 2
    assert len(execution.requests) == 2
    assert (
        sum(
            isinstance(event, ResearchCampaignEvent) and event.trial is not None for event in events
        )
        == 2
    )


def test_unaccounted_exchange_ordinal_rejects_changed_ledger_on_restart(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)

    class _CrashBeforeTrial:
        def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
            raise RuntimeError("simulated process failure after Agent exchange publication")

    first = inputs.orchestrator(tmp_path, (_proposal(inputs, 0),), _CrashBeforeTrial())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        first.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    exchange_files = tuple(inputs.paths["exchanges"].glob("sha256-*.json"))
    assert len(exchange_files) == 1

    changed_bytes = canonical_json_bytes({"body": "campaign source changed after exchange"})
    changed_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(changed_bytes),
        media_type="application/json",
        source_domain="autonomous-fixture",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    inputs.ledger.append(
        ledger_id=inputs.ledger_id,
        node_id="post-exchange-evidence",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=changed_ref,
        object_bytes=changed_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW + timedelta(seconds=25),
    )
    resumed = inputs.orchestrator(
        tmp_path, (_proposal(inputs, 0),), _ExecutionPort((TrialOutcome.PASS,))
    )
    with pytest.raises(AutonomousOrchestrationError) as conflict:
        resumed.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT
    assert len(tuple(inputs.paths["exchanges"].glob("sha256-*.json"))) == 1
    events = resumed.event_store.load(resumed.governor, inputs.campaign, inputs.budget)
    assert not any(
        isinstance(event, ResearchCampaignEvent) and event.trial is not None for event in events
    )


def test_campaign_event_store_exact_append_retry_is_idempotent(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    governor = ResearchCampaignGovernor(inputs.family, inputs.template, inputs.manifest)
    store = CampaignEventStore(inputs.paths["events"])
    current = store.seed(inputs.initial_events, governor, inputs.campaign, inputs.budget)
    assert store.append(current[-1], governor, inputs.campaign, inputs.budget) == current


def test_replay_driver_is_byte_exact_and_tampering_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),))
    _, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trial = next(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    store = AutonomousAgentExchangeStore(inputs.paths["exchanges"], inputs.agent_policy)
    exchange = store.for_run_hash(trial.agent_run_hash)
    assert exchange is not None
    replay = ReplayAgentDriver(store).run(exchange.request)
    assert replay.proposal_bytes == exchange.response.proposal_bytes
    assert replay.proposal_hash == exchange.response.proposal_hash
    response_payload = exchange.response.model_dump(mode="python")
    for field, value in (
        ("verdict", "PASS"),
        ("campaign_state", "CLOSED"),
        ("budget", {"max_trials": 999}),
        ("sealed_access", True),
    ):
        with pytest.raises(ValidationError):
            type(exchange.response).model_validate({**response_payload, field: value})
    with pytest.raises(ValueError):
        ScriptedAgentDriver((), inputs.agent_policy)
    with pytest.raises(AutonomousOrchestrationError) as non_utf8:
        ScriptedAgentDriver((b"\xff",), inputs.agent_policy).run(exchange.request)
    assert non_utf8.value.reason_code is ReasonCode.SCHEMA_INVALID
    scripted_retry = ScriptedAgentDriver(
        (_proposal(inputs, 0, stop=True),), inputs.agent_policy
    ).run(exchange.request)
    assert scripted_retry == exchange.response
    mutable_model_policy = inputs.agent_policy.model_copy(
        update={"model_snapshot_immutable": False}
    )
    mutable_model_response = ScriptedAgentDriver(
        (exchange.response.proposal_bytes.encode("utf-8"),), mutable_model_policy
    ).run(exchange.request)
    assert "MODEL_IDENTIFIER_NOT_IMMUTABLE" in mutable_model_response.manifest.limitations
    assert store.publish(exchange.request, exchange.response).response == exchange.response
    conflicting = ScriptedAgentDriver((_proposal(inputs, 1, stop=True),), inputs.agent_policy).run(
        exchange.request
    )
    with pytest.raises(AutonomousOrchestrationError) as conflict:
        store.publish(exchange.request, conflicting)
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT
    wrong_invocation = exchange.response.model_copy(update={"invocation_hash": "f" * 64})
    with pytest.raises(AutonomousOrchestrationError):
        store.publish(exchange.request, wrong_invocation)
    wrong_provenance = exchange.response.model_copy(
        update={
            "manifest": exchange.response.manifest.model_copy(
                update={"permission_policy_hash": "f" * 64}
            )
        }
    )
    with pytest.raises(AutonomousOrchestrationError):
        store.publish(exchange.request, wrong_provenance)
    artifact_path = next(inputs.paths["exchanges"].glob("sha256-*.json"))
    artifact_path.write_bytes(b"{}")
    with pytest.raises(AutonomousOrchestrationError):
        ReplayAgentDriver(store).run(exchange.request)


def test_stale_replay_request_and_conflicting_retry_fail_closed(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),))
    _, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trial = next(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    store = AutonomousAgentExchangeStore(inputs.paths["exchanges"], inputs.agent_policy)
    exchange = store.for_run_hash(trial.agent_run_hash)
    assert exchange is not None
    with pytest.raises(AutonomousOrchestrationError) as missing:
        ReplayAgentDriver(store).run(exchange.request.model_copy(update={"run_ordinal": 2}))
    assert missing.value.reason_code is ReasonCode.SOURCE_INCOMPLETE
    stale_schema = exchange.request.model_dump(mode="python")
    stale_schema["allowed_proposal_schema_json"] = "{}"
    with pytest.raises(ValidationError):
        AutonomousAgentRequest.model_validate(stale_schema)
    stale_context = exchange.request.model_dump(mode="python")
    stale_context["context_pack"]["ledger_snapshot_hash"] = "e" * 64
    with pytest.raises(ValidationError):
        AutonomousAgentRequest.model_validate(stale_context)


def test_changed_ast_for_known_candidate_is_recorded_as_schema_invalid(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    candidate = inputs.manifest.candidates[0]  # type: ignore[attr-defined]
    changed_nodes = list(candidate.expression.nodes)
    changed_nodes[-1] = changed_nodes[-1].model_copy(update={"window": 17})
    changed_expression = SafeQlibExpressionSpec(
        schema_version=candidate.expression.schema_version,
        expression_id=candidate.expression.expression_id,
        nodes=tuple(changed_nodes),
        output_node_id=candidate.expression.output_node_id,
    )
    changed = AutonomousCandidateProposal(
        campaign_hash=inputs.campaign.content_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=changed_expression,
        exact_expression_hash=exact_expression_hash(changed_expression),
        structural_expression_hash=structural_expression_hash(changed_expression),
        rationale="altered AST test",
    )
    orchestrator = inputs.orchestrator(tmp_path, (changed, _proposal(inputs, 1, stop=True)))
    _, events = orchestrator.run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trials = [
        event.trial for event in events if isinstance(event, ResearchCampaignEvent) and event.trial
    ]
    assert trials[0].outcome is TrialOutcome.SCHEMA_INVALID
    assert not trials[0].execution_requested


def test_exact_duplicates_are_suppressed_but_structural_duplicates_are_not(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    original = inputs.manifest.candidates[0]
    renamed_nodes = []
    for node in original.expression.nodes:
        renamed_nodes.append(
            node.model_copy(
                update={
                    "node_id": f"renamed-{node.node_id}",
                    "inputs": tuple(f"renamed-{item}" for item in node.inputs),
                }
            )
        )
    renamed_expression = SafeQlibExpressionSpec(
        schema_version=original.expression.schema_version,
        expression_id="renamed-expression",
        nodes=tuple(renamed_nodes),
        output_node_id=f"renamed-{original.expression.output_node_id}",
        input_lag_trading_days=original.expression.input_lag_trading_days,
    )
    structural_duplicate = original.model_copy(
        update={
            "expression": renamed_expression,
            "exact_expression_hash": exact_expression_hash(renamed_expression),
            "structural_expression_hash": structural_expression_hash(renamed_expression),
        }
    )
    assert structural_duplicate.structural_expression_hash == original.structural_expression_hash
    assert structural_duplicate.exact_expression_hash != original.exact_expression_hash
    assert not AutonomousCampaignOrchestrator._has_attempted_exact_expression(
        structural_duplicate, frozenset({original.exact_expression_hash})
    )
    assert AutonomousCampaignOrchestrator._has_attempted_exact_expression(
        original, frozenset({original.exact_expression_hash})
    )


@pytest.mark.parametrize(
    "failed_outcome", (TrialOutcome.HARD_REJECT, TrialOutcome.EXECUTION_FAILED)
)
def test_terminal_failure_candidate_repeat_is_accounted_without_retry(
    tmp_path: Path, failed_outcome: TrialOutcome
) -> None:
    inputs = _inputs(tmp_path)
    executor = _ExecutionPort((failed_outcome, TrialOutcome.PASS))
    repeated = _proposal(inputs, 0)
    report, events = inputs.orchestrator(
        tmp_path,
        (repeated, repeated, _proposal(inputs, 1)),
        executor,
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trials = [
        event.trial for event in events if isinstance(event, ResearchCampaignEvent) and event.trial
    ]
    assert [item.outcome for item in trials] == [
        failed_outcome,
        TrialOutcome.DUPLICATE_CANDIDATE,
        TrialOutcome.PASS,
    ]
    assert len(executor.requests) == 2
    assert report.trial_count == 3


@pytest.mark.parametrize(
    "alteration", ("parameters", "exact_fingerprint", "structural_fingerprint")
)
def test_changed_parameters_or_fingerprints_are_rejected_as_trial_evidence(
    tmp_path: Path, alteration: str
) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    candidate = inputs.manifest.candidates[0]
    proposal = _proposal(inputs, 0, stop=True)
    if alteration == "parameters":
        changed_parameters = tuple(
            item.model_copy(update={"value": 17}) for item in proposal.parameters
        )
        proposal = proposal.model_copy(update={"parameters": changed_parameters})
    elif alteration == "exact_fingerprint":
        proposal = proposal.model_copy(update={"exact_expression_hash": "e" * 64})
    else:
        proposal = proposal.model_copy(update={"structural_expression_hash": "e" * 64})
    assert proposal.candidate_hash == candidate.content_hash
    report, events = inputs.orchestrator(
        tmp_path,
        (proposal, _proposal(inputs, 1, stop=True)),
    ).run(
        inputs.initial_events,
        started_at=NOW + timedelta(seconds=30),
    )
    trial = next(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    assert trial.outcome is TrialOutcome.SCHEMA_INVALID
    assert not trial.execution_requested
    assert report.trial_count == 2


def test_new_grammar_operator_is_rejected_by_frozen_candidate_resolution(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    candidate = inputs.manifest.candidates[0]
    nodes = list(candidate.expression.nodes)
    nodes[-1] = nodes[-1].model_copy(update={"operator": SafeQlibOperator.ROLLING_MEAN})
    changed_expression = SafeQlibExpressionSpec(
        schema_version=candidate.expression.schema_version,
        expression_id=candidate.expression.expression_id,
        nodes=tuple(nodes),
        output_node_id=candidate.expression.output_node_id,
        input_lag_trading_days=candidate.expression.input_lag_trading_days,
    )
    proposal = AutonomousCandidateProposal(
        campaign_hash=inputs.campaign.content_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=changed_expression,
        exact_expression_hash=exact_expression_hash(changed_expression),
        structural_expression_hash=structural_expression_hash(changed_expression),
        rationale="unfrozen operator test",
    )
    _, events = inputs.orchestrator(
        tmp_path,
        (proposal, _proposal(inputs, 1, stop=True)),
    ).run(inputs.initial_events, started_at=NOW + timedelta(seconds=30))
    trial = next(
        event.trial
        for event in events
        if isinstance(event, ResearchCampaignEvent) and event.trial is not None
    )
    assert trial.outcome is TrialOutcome.SCHEMA_INVALID
    assert not trial.execution_requested


def test_loop_report_artifact_tampering_is_rejected(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, allow_manual_stop=True)
    report, _ = inputs.orchestrator(tmp_path, (_proposal(inputs, 0, stop=True),)).run(
        inputs.initial_events, started_at=NOW + timedelta(seconds=30)
    )
    store = AutonomousLoopReportStore(inputs.paths["loop-reports"])
    path = inputs.paths["loop-reports"] / f"sha256-{report.content_hash}.json"
    path.write_bytes(b"{}")
    with pytest.raises(AutonomousOrchestrationError):
        store.verify(report.content_hash)
    with pytest.raises(AutonomousOrchestrationError):
        store.verify("not-a-hash")


def test_orchestrator_rejects_naive_time_and_missing_frozen_plan(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    orchestrator = inputs.orchestrator(tmp_path, (_proposal(inputs, 0),))
    with pytest.raises(AutonomousOrchestrationError) as naive_time:
        orchestrator.run(inputs.initial_events, started_at=datetime(2026, 1, 1))
    assert naive_time.value.reason_code is ReasonCode.SCHEMA_INVALID
    with pytest.raises(AutonomousOrchestrationError) as missing_plan:
        orchestrator.run(inputs.initial_events[:1], started_at=NOW + timedelta(seconds=30))
    assert missing_plan.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION
