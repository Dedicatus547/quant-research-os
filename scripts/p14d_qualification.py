#!/usr/bin/env python3
"""Qualify bounded deterministic autonomous campaigns from a clean commit and two roots."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import patch
from uuid import UUID

from pydantic import ValidationError

from quantos.application.autonomous import (
    AutonomousAgentExchangeStore,
    AutonomousCampaignOrchestrator,
    AutonomousOrchestrationError,
    ReplayAgentDriver,
    ScriptedAgentDriver,
)
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
    autonomous_compute_accounting_policy_hash,
    build_autonomous_execution_bindings,
)
from quantos.application.campaign_selection import (
    CampaignSelectionService,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import CampaignChainEvent, ResearchCampaignGovernor
from quantos.application.enumeration import (
    enumerate_research_family,
    verify_candidate_enumeration_manifest,
)
from quantos.application.ledger import ResearchLedgerService
from quantos.application.provenance import (
    capture_code_provenance,
    capture_runtime_fingerprint,
    verify_code_provenance,
)
from quantos.artifacts.store import (
    publish_directory,
    regular_tree_files,
    sha256_file,
)
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    AutonomousAgentExchangeArtifact,
    AutonomousAgentRunPolicy,
    AutonomousCampaignPolicy,
    AutonomousCandidateProposal,
    AutonomousExecutionBindings,
    AutonomousExecutionRequest,
    AutonomousLoopState,
    AutonomousStoppingReason,
    autonomous_execution_identity,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignStoppingRule,
    MultipleTestingPolicy,
    ParameterDimension,
    ResearchBudgetSpec,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    ResearchSegment,
    TrialOutcome,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionVerdict,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.cost import BacktestPolicy, CostPolicy
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
from quantos.contracts.p14d_qualification import (
    P14D_CANONICAL_CASES,
    P14D_LIMITATIONS,
    P14D_NEGATIVE_CASES,
    P14D_RESTART_CASES,
    P14dCaseEvidence,
    P14dNamedHash,
    P14dNegativeCaseEvidence,
    P14dQualificationFile,
    P14dQualificationReport,
    P14dReplayCaseEvidence,
    P14dRestartCaseEvidence,
    P14dRootEvidence,
    p14d_principal_hash_summary,
)
from quantos.contracts.pit import SafeQlibOperator
from quantos.contracts.provenance import CodeProvenance, RuntimeFingerprint
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    HardGateId,
    ResearchPolicy,
    StrategyAuthoringSpec,
    ValidationPolicy,
    ValidationSubperiod,
)
from quantos.contracts.research import ResearchSegment as PolicySegment
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.status import ReasonCode
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.research.qlib import (
    QlibResearchError,
    QlibWorkflowResearchService,
    verify_research_result,
)
from quantos.validation import verify_validation_report

ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_CONTRACT_PATH = Path("docs/p14d-qualification-contract.md")
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "p14d_qualification"
CASE_STARTED_AT = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
RESTART_STARTED_AT = CASE_STARTED_AT + timedelta(minutes=5)
LEDGER_SEEDED_AT = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


class QualificationError(RuntimeError):
    """P14d qualification failed a frozen engineering gate."""


@dataclass(frozen=True)
class _Fixture:
    fixture_id: str
    snapshot_path: Path
    view_path: Path
    snapshot_manifest: DataSnapshotManifest
    view_manifest: QlibViewManifest
    fixture_hash: str

    @property
    def qlib_binding_hash(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "dump_bin_sha256": self.view_manifest.dump_bin_sha256,
                    "health_check_sha256": self.view_manifest.health_check_sha256,
                    "qlib_source_commit": self.view_manifest.qlib_source_commit,
                    "qlib_version": self.view_manifest.qlib_version,
                }
            )
        )


@dataclass(frozen=True)
class _CaseContext:
    case_id: str
    case_root: Path
    fixture: _Fixture
    ledger: ResearchLedgerService
    ledger_id: str
    initial_ledger: ResearchLedgerSnapshot
    initial_events: tuple[CampaignChainEvent, ...]
    campaign: ResearchCampaignSpec
    family: ResearchFamilySpec
    budget: ResearchBudgetSpec
    template: ResearchFactorTemplateSpec
    manifest: CandidateEnumerationManifest
    search_policy: ResearchLedgerSearchPolicy
    context_budget: ResearchContextBudgetPolicy
    campaign_policy: AutonomousCampaignPolicy
    agent_policy: AutonomousAgentRunPolicy
    selection: CampaignSelectionService
    adapter_args: dict[str, object]
    execution_bindings: AutonomousExecutionBindings
    proposal: AutonomousCandidateProposal
    malformed_proposal: bytes


@dataclass(frozen=True)
class _CaseRun:
    context: _CaseContext
    orchestrator: AutonomousCampaignOrchestrator
    adapter: QuantosResearchExecutionAdapter
    report: object
    events: tuple[CampaignChainEvent, ...]


def _single_sha_directory(root: Path) -> Path:
    directories = tuple(
        sorted(
            item
            for item in root.iterdir()
            if item.is_dir() and item.name.startswith("sha256-") and len(item.name) == 71
        )
    )
    if len(directories) != 1:
        raise QualificationError(f"expected exactly one frozen fixture directory under {root}")
    return directories[0]


def _directory_file_hash(root: Path) -> str:
    entries = tuple(
        {
            "logical_path": item.relative_to(root).as_posix(),
            "sha256": sha256_file(item),
            "size_bytes": item.stat().st_size,
        }
        for item in sorted(entry for entry in root.rglob("*") if entry.is_file())
    )
    return sha256_bytes(canonical_json_bytes(entries))


def _load_fixture(fixture_id: str, destination: Path) -> _Fixture:
    source = FIXTURE_ROOT / fixture_id
    snapshot = _single_sha_directory(source / "snapshot")
    view = _single_sha_directory(source / "view")
    snapshot_destination = destination / "snapshot" / snapshot.name
    view_destination = destination / "view" / view.name
    shutil.copytree(snapshot, snapshot_destination)
    shutil.copytree(view, view_destination)
    snapshot_manifest = verify_snapshot(snapshot_destination)
    view_manifest = verify_qlib_view(view_destination)
    if view_manifest.source_snapshot_hash != snapshot_manifest.snapshot_hash:
        raise QualificationError("frozen fixture view does not bind its snapshot")
    fixture_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "fixture_id": fixture_id,
                "snapshot_content_hash": _directory_file_hash(snapshot_destination),
                "snapshot_hash": snapshot_manifest.snapshot_hash,
                "view_content_hash": _directory_file_hash(view_destination),
                "view_hash": view_manifest.view_hash,
            }
        )
    )
    return _Fixture(
        fixture_id=fixture_id,
        snapshot_path=snapshot_destination,
        view_path=view_destination,
        snapshot_manifest=snapshot_manifest,
        view_manifest=view_manifest,
        fixture_hash=fixture_hash,
    )


def _fixture_dates(view_path: Path) -> tuple[date, ...]:
    values = tuple(
        date.fromisoformat(line.strip())
        for line in (view_path / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(values) < 77 or values != tuple(sorted(set(values))):
        raise QualificationError("qualification fixture calendar is too short or not canonical")
    return values


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="p14d-qualification-delta-template",
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


def _family(template: ResearchFactorTemplateSpec) -> ResearchFamilySpec:
    return ResearchFamilySpec(
        family_id="p14d-qualification-family",
        research_question=(
            "Does a bounded synthetic factor family reproduce the same autonomous authority?"
        ),
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )


def _cost_policy() -> CostPolicy:
    return CostPolicy(
        policy_id="p14d-qualification-cost-policy",
        open_cost_rate=0.0005,
        close_cost_rate=0.0015,
        minimum_cost_cny=5.0,
        trade_unit_shares=100,
        volume_limit_fraction=0.1,
    )


def _backtest_policy() -> BacktestPolicy:
    return BacktestPolicy(
        policy_id="p14d-qualification-backtest-policy",
        benchmark="SH000300",
        initial_cash_cny=1_000_000.0,
    )


def _build_case_context(
    case_id: str,
    case_root: Path,
    fixture: _Fixture,
    code: CodeProvenance,
    workspace: Path | None = None,
) -> _CaseContext:
    case_root.mkdir(parents=True, exist_ok=True)
    dates = _fixture_dates(fixture.view_path)
    ledger_id = f"p14d-qualification-{case_id.lower()}-ledger"
    ledger = ResearchLedgerService(case_root / "ledger")
    evidence_bytes = canonical_json_bytes(
        {"body": f"p14d {case_id} frozen synthetic campaign input", "fixture": fixture.fixture_hash}
    )
    evidence_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(evidence_bytes),
        media_type="application/json",
        source_domain="p14d-qualification-fixture",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    ledger.append(
        ledger_id=ledger_id,
        node_id="frozen-campaign-evidence",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=evidence_ref,
        object_bytes=evidence_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=LEDGER_SEEDED_AT,
    )
    initial_ledger = ledger.verify(ledger_id, created_at=LEDGER_SEEDED_AT + timedelta(seconds=1))

    template = _template()
    family = _family(template)
    manifest = enumerate_research_family(family, template)
    first_candidate = manifest.candidates[0]
    trial_window = cast(int, first_candidate.parameters[0].value)
    budget = ResearchBudgetSpec(
        budget_id=f"p14d-qualification-{case_id.lower()}-budget",
        max_trials=2,
        max_distinct_candidates=2,
        max_agent_runs=2,
        max_executions=2,
        max_validation_rounds=2,
        max_compute_seconds=100_000,
    )
    test_start, test_end = dates[36], dates[75]
    campaign = ResearchCampaignSpec(
        campaign_id=f"p14d-qualification-{case_id.lower()}-campaign",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=(evidence_ref.object_hash,),
        ledger_snapshot_hash=initial_ledger.content_hash,
        snapshot_hash=fixture.snapshot_manifest.snapshot_hash,
        qlib_view_hash=fixture.view_manifest.view_hash,
        development=ResearchSegment(start=dates[0], end=dates[35]),
        validation=ResearchSegment(start=test_start, end=test_end),
        sealed_confirmation=ResearchSegment(
            start=dates[76] + timedelta(days=1), end=dates[76] + timedelta(days=30)
        ),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    research_policy = ResearchPolicy(
        policy_id=f"p14d-qualification-{case_id.lower()}-research-policy",
        train=PolicySegment(start=dates[0], end=dates[24]),
        validation=PolicySegment(start=dates[26], end=dates[35]),
        test=PolicySegment(start=test_start, end=test_end),
        purge_trading_days=1,
        label_horizon_trading_sessions=1,
        random_seed=23,
        num_threads=1,
        num_boost_round=2,
        early_stopping_rounds=1,
    )
    validation_policy = ValidationPolicy(
        policy_id=f"p14d-qualification-{case_id.lower()}-validation-policy",
        hard_gates=tuple(HardGateId),
        minimum_oos_observations=1,
        parameter_windows=(trial_window,),
        parameter_top_k=(1,),
        subperiods=(
            ValidationSubperiod(period_id="full-validation", start=test_start, end=test_end),
        ),
        minimum_subperiod_observations=1,
    )
    cost_policy = _cost_policy()
    backtest_policy = _backtest_policy()
    authoring = ExperimentAuthoringSpec(
        experiment_id=f"p14d-qualification-{case_id.lower()}-candidate-0",
        evaluation_start=test_start,
        evaluation_end=test_end,
        expression=first_candidate.expression,
        strategy=StrategyAuthoringSpec(
            universe_index="000300.SH",
            top_k=1,
            input_lag_trading_days=first_candidate.expression.input_lag_trading_days,
            max_weight=0.5,
        ),
    )
    execution_root = case_root / "execution"
    bindings = build_autonomous_execution_bindings(
        snapshot=fixture.snapshot_manifest,
        qlib_view=fixture.view_manifest,
        research_policy=research_policy,
        validation_policy=validation_policy,
        authoring=authoring,
        cost_policy=cost_policy,
        backtest_policy=backtest_policy,
        code_commit_hash=code.commit_hash,
        lockfile_hash=code.lockfile_hash,
    )
    adapter_args: dict[str, object] = {
        "campaign": campaign,
        "family": family,
        "budget": budget,
        "template": template,
        "manifest": manifest,
        "snapshot_path": fixture.snapshot_path,
        "qlib_view_path": fixture.view_path,
        "base_authoring": authoring,
        "research_policy": research_policy,
        "validation_policy": validation_policy,
        "cost_policy": cost_policy,
        "backtest_policy": backtest_policy,
        "bindings": bindings,
        "output_root": execution_root,
        "workspace": workspace or ROOT,
        "canonical_validation": True,
    }
    multiple_testing = MultipleTestingPolicySpec(seed="9" * 64)
    selection_policy = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple_testing.content_hash,
        direction="POSITIVE",
    )
    selection = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple_testing,
        selection_policy,
        fixture.view_path,
        (execution_root / "research-results",),
    )
    governor = ResearchCampaignGovernor(family, template, manifest)
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID(int=int(sha256_bytes(f"{case_id}-activation".encode())[:32], 16)),
        occurred_at=CASE_STARTED_AT - timedelta(seconds=3),
    )
    plan_event, _plan = selection.freeze_plan(
        governor,
        (activation,),
        event_id=UUID(int=int(sha256_bytes(f"{case_id}-plan".encode())[:32], 16)),
        occurred_at=CASE_STARTED_AT - timedelta(seconds=2),
        artifact_root=case_root / "selection-plans",
    )
    search_policy = ResearchLedgerSearchPolicy(
        policy_id=f"p14d-qualification-{case_id.lower()}-search-policy",
        allowed_node_kinds=tuple(sorted(ResearchLedgerNodeKind, key=str)),
        allowed_authorities=tuple(sorted(LedgerAssertionAuthority, key=str)),
        allow_cross_campaign_history=True,
        max_query_bytes=4096,
        max_query_terms=32,
        max_hit_bytes=262144,
        max_results=50,
        max_serialized_bytes=1_000_000,
        max_index_entries=1000,
        max_terms_per_object=4096,
        max_index_serialized_bytes=16_777_216,
    )
    context_budget = ResearchContextBudgetPolicy(
        policy_id=f"p14d-qualification-{case_id.lower()}-context-budget",
        max_items=50,
        max_item_bytes=262144,
        max_serialized_bytes=1_000_000,
    )
    campaign_policy = AutonomousCampaignPolicy(
        policy_id=f"p14d-qualification-{case_id.lower()}-campaign-policy",
        context_query="outcome research_policy_hash",
        readable_campaign_hashes=(campaign.content_hash,),
        trial_segment=CampaignSegment.VALIDATION,
    )
    agent_policy = AutonomousAgentRunPolicy(
        capability_policy_hash="a" * 64,
        requested_model_configuration_hash="b" * 64,
        tool_schema_hash="c" * 64,
        instruction_hashes=("d" * 64,),
        skill_hash="e" * 64,
        sandbox_policy_hash="f" * 64,
        permission_policy_hash="1" * 64,
        runtime_policy_hash="2" * 64,
        harness_identifier="scripted-agent-driver/v1",
        provider_model_identifier="scripted-fixture/v1",
        model_snapshot_immutable=True,
    )
    proposal = AutonomousCandidateProposal(
        campaign_hash=campaign.content_hash,
        candidate_hash=first_candidate.content_hash,
        parameters=first_candidate.parameters,
        expression=first_candidate.expression,
        exact_expression_hash=first_candidate.exact_expression_hash,
        structural_expression_hash=first_candidate.structural_expression_hash,
        rationale=f"deterministic {case_id} fixture proposal",
    )
    malformed_proposal = canonical_json_bytes(
        {"candidate_hash": manifest.candidates[1].content_hash}
    )
    return _CaseContext(
        case_id=case_id,
        case_root=case_root,
        fixture=fixture,
        ledger=ledger,
        ledger_id=ledger_id,
        initial_ledger=initial_ledger,
        initial_events=(activation, plan_event),
        campaign=campaign,
        family=family,
        budget=budget,
        template=template,
        manifest=manifest,
        search_policy=search_policy,
        context_budget=context_budget,
        campaign_policy=campaign_policy,
        agent_policy=agent_policy,
        selection=selection,
        adapter_args=adapter_args,
        execution_bindings=bindings,
        proposal=proposal,
        malformed_proposal=malformed_proposal,
    )


class _InjectedPitRejectAdapter(QuantosResearchExecutionAdapter):
    """Known PIT rejection fixture at the deterministic service boundary."""

    def _execute_pipeline(self, request: AutonomousExecutionRequest):
        del request
        raise QlibResearchError(ReasonCode.LOOK_AHEAD, "synthetic frozen PIT rejection fixture")


class _InjectedExecutionFailureAdapter(QuantosResearchExecutionAdapter):
    """Known Qlib operational failure fixture at the deterministic service boundary."""

    def _execute_pipeline(self, request: AutonomousExecutionRequest):
        del request
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "synthetic frozen execution failure fixture"
        )


def _adapter_for_case(
    context: _CaseContext, fault: str | None = None
) -> QuantosResearchExecutionAdapter:
    if fault == "pit_reject":
        return _InjectedPitRejectAdapter(**context.adapter_args)  # type: ignore[arg-type]
    if fault == "execution_failure":
        return _InjectedExecutionFailureAdapter(**context.adapter_args)  # type: ignore[arg-type]
    return QuantosResearchExecutionAdapter(**context.adapter_args)  # type: ignore[arg-type]


def _build_orchestrator(
    context: _CaseContext,
    adapter: QuantosResearchExecutionAdapter,
    script: Sequence[AutonomousCandidateProposal | bytes],
) -> AutonomousCampaignOrchestrator:
    return AutonomousCampaignOrchestrator(
        campaign=context.campaign,
        family=context.family,
        budget=context.budget,
        template=context.template,
        manifest=context.manifest,
        initial_ledger_snapshot=context.initial_ledger,
        ledger_service=context.ledger,
        ledger_id=context.ledger_id,
        search_policy=context.search_policy,
        context_budget=context.context_budget,
        campaign_policy=context.campaign_policy,
        agent_run_policy=context.agent_policy,
        agent_driver=ScriptedAgentDriver(tuple(script), context.agent_policy),
        execution_port=adapter,
        exchange_root=context.case_root / "agent-exchanges",
        event_root=context.case_root / "campaign-events",
        selection_service=context.selection,
        selection_artifact_root=context.case_root / "selection-reports",
        autonomous_report_root=context.case_root / "loop-reports",
        execution_bindings=context.execution_bindings,
    )


def _run_case(
    context: _CaseContext,
    *,
    script: Sequence[AutonomousCandidateProposal | bytes],
    fault: str | None = None,
) -> _CaseRun:
    adapter = _adapter_for_case(context, fault)
    orchestrator = _build_orchestrator(context, adapter, script)
    report, events = orchestrator.run(context.initial_events, started_at=CASE_STARTED_AT)
    return _CaseRun(
        context=context, orchestrator=orchestrator, adapter=adapter, report=report, events=events
    )


def _load_exchanges(
    root: Path, policy: AutonomousAgentRunPolicy
) -> tuple[AutonomousAgentExchangeArtifact, ...]:
    artifacts: list[AutonomousAgentExchangeArtifact] = []
    for path in sorted(root.glob("sha256-*.json")):
        encoded = path.read_bytes()
        artifact = AutonomousAgentExchangeArtifact.model_validate_json(encoded)
        if (
            encoded != artifact.canonical_bytes()
            or path.name != f"sha256-{artifact.content_hash}.json"
        ):
            raise QualificationError("Agent exchange artifact is not canonical")
        if artifact.response.manifest.provider_model_identifier != policy.provider_model_identifier:
            raise QualificationError("Agent exchange artifact does not bind the frozen policy")
        artifacts.append(artifact)
    return tuple(artifacts)


def _load_receipts(
    context: _CaseContext,
) -> tuple[AutonomousExecutionReceipt, ...]:
    root = context.case_root / "execution" / "execution-records" / "identities"
    receipts: list[AutonomousExecutionReceipt] = []
    for path in sorted(root.glob("*.json")):
        encoded = path.read_bytes()
        receipt = AutonomousExecutionReceipt.model_validate_json(encoded)
        if encoded != receipt.canonical_bytes():
            raise QualificationError("execution receipt artifact is not canonical")
        receipts.append(receipt)
    return tuple(receipts)


def _ledger_principal_hash(snapshot: ResearchLedgerSnapshot) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "head_event_hash": snapshot.head_event_hash,
                "ledger_id": snapshot.ledger_id,
                "node_object_hashes": snapshot.node_object_hashes,
                "source_event_hashes": snapshot.source_event_hashes,
            }
        )
    )


def _case_evidence(case_id: str, run: _CaseRun) -> P14dCaseEvidence:
    context = run.context
    report = cast(object, run.report)
    events = run.events
    exchanges = _load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    receipts = _load_receipts(context)
    selection_report_hash = getattr(report, "selection_report_hash", None)
    if not isinstance(selection_report_hash, str):
        raise QualificationError(f"{case_id} loop report has no P14c selection report")
    selection_path = context.case_root / "selection-reports" / f"sha256-{selection_report_hash}"
    selection_report = verify_selection_report_artifact(selection_path)
    loop_report_hash = cast(str, report.content_hash)  # type: ignore[attr-defined]
    loop_report_path = context.case_root / "loop-reports" / f"sha256-{loop_report_hash}.json"
    loop_report = AutonomousCampaignOrchestrator.__module__  # keep import surface explicit
    del loop_report
    if not loop_report_path.is_file():
        raise QualificationError("autonomous loop report artifact is missing")
    final_ledger = context.ledger.verify(
        context.ledger_id, created_at=CASE_STARTED_AT + timedelta(days=1)
    )
    if final_ledger.content_hash != report.final_ledger_snapshot_hash:
        raise QualificationError("final Ledger snapshot differs from the loop report binding")
    trial_events = tuple(
        event
        for event in events
        if getattr(event, "trial", None) is not None
        and getattr(event.trial, "proposal_hash", None) is not None
    )
    failure_receipts = tuple(
        receipt for receipt in receipts if receipt.outcome.research_result_hash is None
    )
    successful_receipts = tuple(
        receipt for receipt in receipts if receipt.outcome.research_result_hash is not None
    )
    if len(failure_receipts) + len(successful_receipts) != len(receipts):
        raise QualificationError("execution receipts cannot be classified")
    if any(receipt.outcome.validation_report_hash is None for receipt in successful_receipts):
        raise QualificationError("successful execution receipt lacks a ValidationReport")
    trial_hashes = tuple(
        sorted(
            sha256_bytes(cast(object, event.trial).canonical_bytes())  # type: ignore[attr-defined]
            for event in trial_events
        )
    )
    return P14dCaseEvidence.create(
        case_id=case_id,
        fixture_hash=context.fixture.fixture_hash,
        campaign_hash=context.campaign.content_hash,
        family_hash=context.family.content_hash,
        budget_hash=context.budget.content_hash,
        candidate_manifest_hash=context.manifest.content_hash,
        initial_context_pack_hash=min(
            exchanges, key=lambda item: item.request.run_ordinal
        ).request.context_pack.content_hash,
        agent_request_hashes=tuple(item.request.content_hash for item in exchanges),
        agent_proposal_hashes=tuple(item.response.proposal_hash for item in exchanges),
        execution_request_hashes=tuple(
            sorted(receipt.request.content_hash for receipt in receipts)
        ),
        execution_identities=tuple(
            sorted(receipt.request.execution_identity for receipt in receipts)
        ),
        research_result_hashes=tuple(
            sorted(
                cast(str, receipt.outcome.research_result_hash) for receipt in successful_receipts
            )
        ),
        validation_report_hashes=tuple(
            sorted(
                cast(str, receipt.outcome.validation_report_hash) for receipt in successful_receipts
            )
        ),
        campaign_trial_hashes=trial_hashes,
        campaign_event_hashes=tuple(event.content_hash for event in events),
        final_campaign_event_hash=events[-1].content_hash,
        final_ledger_snapshot_hash=final_ledger.content_hash,
        ledger_principal_hash=_ledger_principal_hash(final_ledger),
        selection_report_hash=selection_report.report_hash,
        selection_frozen_event_hash=report.selection_event_hash,
        autonomous_loop_report_hash=loop_report_hash,
        loop_state=report.state,
        trial_outcomes=tuple(cast(object, event.trial).outcome for event in trial_events),  # type: ignore[attr-defined]
    )


def _fixture_set_hash(fixtures: Sequence[_Fixture]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            tuple(
                {
                    "fixture_hash": fixture.fixture_hash,
                    "fixture_id": fixture.fixture_id,
                    "qlib_binding_hash": fixture.qlib_binding_hash,
                }
                for fixture in fixtures
            )
        )
    )


def _run_canonical_case(
    case_id: str,
    root: Path,
    fixture: _Fixture,
    code: CodeProvenance,
    *,
    fault: str | None,
    workspace: Path | None = None,
) -> tuple[_CaseRun, P14dCaseEvidence]:
    context = _build_case_context(case_id, root, fixture, code, workspace=workspace)
    run = _run_case(
        context,
        script=(context.proposal, context.malformed_proposal),
        fault=fault,
    )
    evidence = _case_evidence(case_id, run)
    return run, evidence


def _selection_verdict(run: _CaseRun) -> CampaignSelectionVerdict:
    case_root = run.context.case_root
    loop_report_hash = run.report.selection_report_hash
    if not isinstance(loop_report_hash, str):
        raise QualificationError("case has no selection report")
    return verify_selection_report_artifact(
        case_root / "selection-reports" / f"sha256-{loop_report_hash}"
    ).verdict


@dataclass(frozen=True)
class _CanonicalBundle:
    case_id: str
    run: _CaseRun
    evidence: P14dCaseEvidence


def _run_root_canonical_bundles(
    root: Path,
    fixture_set: Path,
    code: CodeProvenance,
    *,
    workspace: Path | None = None,
) -> tuple[_CanonicalBundle, ...]:
    selected = _load_fixture("selected", root / "fixtures" / "selected")
    no_selection = _load_fixture("no_selection", root / "fixtures" / "no_selection")
    del fixture_set
    bundles: list[_CanonicalBundle] = []
    selected_run, selected_evidence = _run_canonical_case(
        "SELECTED",
        root / "cases" / "selected",
        selected,
        code,
        fault=None,
        workspace=workspace,
    )
    if (
        selected_run.report.state is not AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION
        or _selection_verdict(selected_run) is not CampaignSelectionVerdict.SELECTED
    ):
        raise QualificationError("SELECTED case did not freeze a verified selection")
    bundles.append(_CanonicalBundle("SELECTED", selected_run, selected_evidence))
    no_selection_run, no_selection_evidence = _run_canonical_case(
        "NO_SELECTION",
        root / "cases" / "no_selection",
        no_selection,
        code,
        fault=None,
        workspace=workspace,
    )
    if (
        no_selection_run.report.state is not AutonomousLoopState.SELECTION_COMPLETE
        or _selection_verdict(no_selection_run) is not CampaignSelectionVerdict.NO_SELECTION
    ):
        raise QualificationError("NO_SELECTION case did not close without selection")
    bundles.append(_CanonicalBundle("NO_SELECTION", no_selection_run, no_selection_evidence))
    failed_run, failed_evidence = _run_canonical_case(
        "FAILED_NOT_EVALUATED",
        root / "cases" / "failed_not_evaluated",
        selected,
        code,
        fault="pit_reject",
        workspace=workspace,
    )
    if (
        failed_run.report.state is not AutonomousLoopState.SELECTION_COMPLETE
        or _selection_verdict(failed_run) is not CampaignSelectionVerdict.NOT_EVALUATED
    ):
        raise QualificationError("FAILED_NOT_EVALUATED case did not close without authority")
    bundles.append(_CanonicalBundle("FAILED_NOT_EVALUATED", failed_run, failed_evidence))
    if tuple(item.case_id for item in bundles) != P14D_CANONICAL_CASES:
        raise QualificationError("canonical case registry is incomplete or unordered")
    return tuple(bundles)


def _run_root_canonical_cases(
    root: Path,
    fixture_set: Path,
    code: CodeProvenance,
    *,
    workspace: Path | None = None,
) -> tuple[P14dCaseEvidence, ...]:
    return tuple(
        item.evidence
        for item in _run_root_canonical_bundles(root, fixture_set, code, workspace=workspace)
    )


def _reason_code(error: BaseException) -> ReasonCode:
    reason = getattr(error, "reason_code", None)
    if isinstance(reason, ReasonCode):
        return reason
    if isinstance(error, (ValidationError, ValueError, OSError, TypeError, KeyError)):
        return ReasonCode.ARTIFACT_CORRUPTED
    raise QualificationError(f"unclassified negative-case exception: {type(error).__name__}")


def _negative_evidence(
    case_id: str,
    action: Callable[[], object],
    *,
    expected_reason: ReasonCode | None = None,
    expected_value_hash: str | None = None,
) -> P14dNegativeCaseEvidence:
    input_hash = sha256_bytes(
        canonical_json_bytes({"case_id": case_id, "runner": "p14d-negative/v1"})
    )
    try:
        value = action()
    except Exception as error:
        if expected_reason is None:
            raise QualificationError(f"negative case {case_id} raised unexpectedly") from error
        reason = _reason_code(error)
        if reason is not expected_reason:
            raise QualificationError(
                f"negative case {case_id} failed with {reason}, expected {expected_reason}"
            ) from error
        outcome_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "case_id": case_id,
                    "error_type": type(error).__name__,
                    "reason_code": reason.value,
                }
            )
        )
        return P14dNegativeCaseEvidence(
            case_id=case_id,
            input_hash=input_hash,
            outcome_hash=outcome_hash,
            reason_code=reason,
        )
    if expected_reason is None or expected_value_hash is None:
        raise QualificationError(f"negative case {case_id} action unexpectedly returned")
    value_hash = _hash_outcome(value)
    if value_hash != expected_value_hash:
        raise QualificationError(f"negative case {case_id} returned an unexpected outcome")
    return P14dNegativeCaseEvidence(
        case_id=case_id,
        input_hash=input_hash,
        outcome_hash=value_hash,
        reason_code=expected_reason,
    )


def _hash_outcome(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _build_pack_for_snapshot(context: _CaseContext, snapshot: ResearchLedgerSnapshot) -> object:
    from quantos.contracts.ledger import (
        ResearchLedgerAccessScope,
        ResearchLedgerSearchRequest,
    )

    scope = ResearchLedgerAccessScope(
        campaign_hash=context.campaign.content_hash,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=(context.campaign.content_hash,),
        inherited_contamination_hashes=(),
        authorized_sealed_object_hashes=(),
    )
    request = ResearchLedgerSearchRequest(
        campaign_hash=context.campaign.content_hash,
        ledger_snapshot_hash=snapshot.content_hash,
        search_policy_hash=context.search_policy.content_hash,
        access_scope_hash=scope.content_hash,
        query=context.campaign_policy.context_query,
    )
    result = context.ledger.search(
        snapshot=snapshot, policy=context.search_policy, scope=scope, request=request
    )
    return context.ledger.build_context_pack(
        snapshot=snapshot,
        policy=context.search_policy,
        scope=scope,
        request=request,
        result=result,
        budget=context.context_budget,
    )


def _run_negative_cases(run: _CaseRun) -> tuple[P14dNegativeCaseEvidence, ...]:
    context = run.context
    orchestrator = run.orchestrator
    receipt = _load_receipts(context)[0]
    request = receipt.request
    exchanges = _load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    first_exchange = min(exchanges, key=lambda item: item.request.run_ordinal)
    evidence: dict[str, P14dNegativeCaseEvidence] = {}

    def record(
        case_id: str,
        action: Callable[[], object],
        *,
        expected_reason: ReasonCode | None = None,
        expected_value: object | None = None,
        expected_value_hash: str | None = None,
    ) -> None:
        if expected_value_hash is None and expected_value is not None:
            expected_value_hash = _hash_outcome(expected_value)
        evidence[case_id] = _negative_evidence(
            case_id,
            action,
            expected_reason=expected_reason,
            expected_value_hash=expected_value_hash,
        )

    record(
        "MANIFEST_DRIFT",
        lambda: verify_candidate_enumeration_manifest(
            context.family,
            context.template,
            context.manifest.model_copy(update={"family_hash": "0" * 64}),
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    record(
        "CANDIDATE_HASH_MISMATCH",
        lambda: run.adapter._verify_request(  # pyright: ignore[reportPrivateUsage]
            request.model_copy(
                update={
                    "candidate": context.manifest.candidates[1],
                    "candidate_exact_expression_hash": context.manifest.candidates[
                        1
                    ].exact_expression_hash,
                    "candidate_structural_expression_hash": context.manifest.candidates[
                        1
                    ].structural_expression_hash,
                }
            )
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    swapped_expression = context.manifest.candidates[1].expression
    record(
        "CANDIDATE_AST_MISMATCH",
        lambda: verify_candidate_enumeration_manifest(
            context.family,
            context.template,
            CandidateEnumerationManifest.model_validate(
                {
                    **context.manifest.model_dump(),
                    "candidates": (
                        context.manifest.candidates[0].model_copy(
                            update={"expression": swapped_expression}
                        ),
                        *context.manifest.candidates[1:],
                    ),
                }
            ),
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    record(
        "CANDIDATE_FINGERPRINT_MISMATCH",
        lambda: verify_candidate_enumeration_manifest(
            context.family,
            context.template,
            CandidateEnumerationManifest.model_validate(
                {
                    **context.manifest.model_dump(),
                    "candidates": (
                        context.manifest.candidates[0].model_copy(
                            update={"exact_expression_hash": "0" * 64}
                        ),
                        *context.manifest.candidates[1:],
                    ),
                }
            ),
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )

    no_selection_fixture = _load_fixture(
        "no_selection",
        context.case_root.parent / "negative-mismatch-fixture",
    )
    mismatch_args = dict(context.adapter_args)
    mismatch_args["snapshot_path"] = no_selection_fixture.snapshot_path
    mismatch_args["output_root"] = context.case_root / "negative-snapshot-mismatch"
    record(
        "SNAPSHOT_MISMATCH",
        lambda: QuantosResearchExecutionAdapter(**mismatch_args),  # type: ignore[arg-type]
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    view_mismatch_args = dict(context.adapter_args)
    view_mismatch_args["qlib_view_path"] = no_selection_fixture.view_path
    view_mismatch_args["output_root"] = context.case_root / "negative-view-mismatch"
    record(
        "QLIB_VIEW_MISMATCH",
        lambda: QuantosResearchExecutionAdapter(**view_mismatch_args),  # type: ignore[arg-type]
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    record(
        "POLICY_MISMATCH",
        lambda: run.adapter._verify_request(  # pyright: ignore[reportPrivateUsage]
            request.model_copy(update={"research_policy_hash": "0" * 64})
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )

    current_ledger = context.ledger.verify(
        context.ledger_id, created_at=CASE_STARTED_AT + timedelta(days=1)
    )
    current_pack = _build_pack_for_snapshot(context, current_ledger)
    from quantos.application.ledger import verify_context_bound_agent_manifest

    record(
        "STALE_CONTEXTPACK",
        lambda: verify_context_bound_agent_manifest(
            manifest=first_exchange.response.manifest,
            spec=first_exchange.request.agent_run_spec,
            binding=first_exchange.request.context_binding,
            pack=current_pack,  # type: ignore[arg-type]
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    record(
        "STALE_LEDGER_SNAPSHOT",
        lambda: orchestrator._require_initial_snapshot_prefix(  # pyright: ignore[reportPrivateUsage]
            ResearchLedgerSnapshot(
                ledger_id=context.initial_ledger.ledger_id,
                source_event_hashes=(),
                head_event_hash=None,
                node_object_hashes=(),
                created_at=CASE_STARTED_AT,
            )
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )

    with tempfile.TemporaryDirectory(prefix="p14d-negative-") as temporary_name:
        temporary = Path(temporary_name)
        exchange_root = context.case_root / "agent-exchanges"
        tampered_exchange_root = temporary / "exchanges"
        shutil.copytree(exchange_root, tampered_exchange_root)
        tampered_exchange_file = sorted(tampered_exchange_root.glob("sha256-*.json"))[0]
        tampered_exchange_file.write_bytes(tampered_exchange_file.read_bytes() + b" ")
        tampered_store = AutonomousAgentExchangeStore(tampered_exchange_root, context.agent_policy)
        record(
            "TAMPERED_AGENT_EXCHANGE",
            lambda: tampered_store._artifacts(),  # pyright: ignore[reportPrivateUsage]
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )
        record(
            "TAMPERED_REPLAY_ARTIFACT",
            lambda: ReplayAgentDriver(tampered_store).run(first_exchange.request),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

        tampered_receipt_root = temporary / "receipt-root"
        receipt_relative = (
            context.case_root
            / "execution"
            / "execution-records"
            / "identities"
            / f"{request.execution_identity}.json"
        )
        receipt_destination = (
            tampered_receipt_root / "execution-records" / "identities" / receipt_relative.name
        )
        receipt_destination.parent.mkdir(parents=True)
        shutil.copyfile(receipt_relative, receipt_destination)
        receipt_destination.write_bytes(receipt_destination.read_bytes() + b" ")
        receipt_args = dict(context.adapter_args)
        receipt_args["output_root"] = tampered_receipt_root
        corrupted_adapter = QuantosResearchExecutionAdapter(
            **receipt_args  # type: ignore[arg-type]
        )
        record(
            "TAMPERED_EXECUTION_RECEIPT",
            lambda: corrupted_adapter._read_receipt(  # pyright: ignore[reportPrivateUsage]
                request.execution_identity
            ),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

    assert receipt.outcome.research_result_hash is not None
    research_result_path = (
        context.case_root
        / "execution"
        / "research-results"
        / f"sha256-{receipt.outcome.research_result_hash}"
    )
    with tempfile.TemporaryDirectory(prefix="p14d-result-tamper-") as temporary_name:
        tampered_result = Path(temporary_name) / "result"
        shutil.copytree(research_result_path, tampered_result)
        predictions = tampered_result / "predictions.json"
        predictions.write_bytes(predictions.read_bytes() + b" ")
        record(
            "TAMPERED_RESEARCH_RESULT",
            lambda: verify_research_result(tampered_result),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

    assert receipt.outcome.validation_report_hash is not None
    validation_path = (
        context.case_root
        / "execution"
        / "validation"
        / f"sha256-{receipt.outcome.validation_report_hash}"
    )
    with tempfile.TemporaryDirectory(prefix="p14d-validation-tamper-") as temporary_name:
        tampered_validation = Path(temporary_name) / "validation"
        shutil.copytree(validation_path, tampered_validation)
        report_file = tampered_validation / "report.json"
        report_file.write_bytes(report_file.read_bytes() + b" ")
        record(
            "TAMPERED_VALIDATION_REPORT",
            lambda: verify_validation_report(tampered_validation),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

    record(
        "CONFLICTING_EXECUTION_RETRY",
        lambda: run.adapter.execute(request.model_copy(update={"agent_run_hash": "a" * 64})),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )
    record(
        "CONFLICTING_TRIAL_IDENTITY",
        lambda: run.adapter._reserve_trial_identity(  # pyright: ignore[reportPrivateUsage]
            request.model_copy(update={"execution_identity": "0" * 64, "idempotency_key": "0" * 64})
        ),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )

    duplicate_trial = orchestrator._make_trial(  # pyright: ignore[reportPrivateUsage]
        request=request,
        response=first_exchange.response,
        proposal=context.proposal,
        candidate=context.manifest.candidates[0],
        events=run.events,
        event_time=CASE_STARTED_AT + timedelta(seconds=30),
    )
    record(
        "DUPLICATE_PROPOSAL",
        lambda: {"kind": duplicate_trial.outcome.value},
        expected_reason=ReasonCode.DUPLICATE_ID_CONFLICT,
        expected_value={"kind": TrialOutcome.DUPLICATE_CANDIDATE.value},
    )

    base_snapshot = orchestrator.governor.project(
        context.campaign, context.budget, context.initial_events
    )
    record(
        "BUDGET_EXHAUSTION",
        lambda: {
            "reason": orchestrator._stopping_reason(  # pyright: ignore[reportPrivateUsage]
                base_snapshot.model_copy(
                    update={"compute_seconds": context.budget.max_compute_seconds}
                ),
                context.initial_events,
            )
        },
        expected_reason=ReasonCode.RESEARCH_BUDGET_EXCEEDED,
        expected_value={"reason": AutonomousStoppingReason.BUDGET_EXHAUSTED},
    )
    record(
        "MAX_AGENT_RUNS",
        lambda: {
            "reason": orchestrator._stopping_reason(  # pyright: ignore[reportPrivateUsage]
                base_snapshot.model_copy(update={"agent_run_count": context.budget.max_agent_runs}),
                context.initial_events,
            )
        },
        expected_reason=ReasonCode.RESEARCH_BUDGET_EXCEEDED,
        expected_value={"reason": AutonomousStoppingReason.BUDGET_EXHAUSTED},
    )
    record(
        "MAX_TRIALS",
        lambda: {
            "reason": orchestrator._stopping_reason(  # pyright: ignore[reportPrivateUsage]
                base_snapshot.model_copy(update={"trial_count": context.budget.max_trials}),
                context.initial_events,
            )
        },
        expected_reason=ReasonCode.RESEARCH_BUDGET_EXCEEDED,
        expected_value={"reason": AutonomousStoppingReason.BUDGET_EXHAUSTED},
    )

    unknown_bytes = canonical_json_bytes({"candidate_hash": "f" * 64}).decode("utf-8")

    def unknown_candidate_action() -> object:
        candidate_hash = orchestrator._extract_candidate_hash(  # pyright: ignore[reportPrivateUsage]
            unknown_bytes
        )
        if candidate_hash in orchestrator._candidate_by_hash:  # pyright: ignore[reportPrivateUsage]
            raise QualificationError("unknown-candidate fixture unexpectedly resolved")
        raise AutonomousOrchestrationError(
            ReasonCode.SCHEMA_INVALID, "proposal candidate is outside frozen manifest"
        )

    record(
        "UNKNOWN_CANDIDATE",
        unknown_candidate_action,
        expected_reason=ReasonCode.SCHEMA_INVALID,
    )

    record(
        "INVALID_PROPOSAL_SCHEMA",
        lambda: {
            "outcome": orchestrator._make_trial(  # pyright: ignore[reportPrivateUsage]
                request=request,
                response=first_exchange.response,
                proposal=None,
                candidate=context.manifest.candidates[0],
                events=context.initial_events,
                event_time=CASE_STARTED_AT + timedelta(seconds=40),
            ).outcome.value
        },
        expected_reason=ReasonCode.SCHEMA_INVALID,
        expected_value={"outcome": TrialOutcome.SCHEMA_INVALID.value},
    )

    fault_candidate = context.manifest.candidates[1]
    fault_identity = autonomous_execution_identity(
        campaign_hash=context.campaign.content_hash,
        family_hash=context.family.content_hash,
        budget_hash=context.budget.content_hash,
        candidate_manifest_hash=context.manifest.content_hash,
        candidate=fault_candidate,
        snapshot_hash=context.campaign.snapshot_hash,
        qlib_view_hash=context.campaign.qlib_view_hash,
        segment=context.campaign_policy.trial_segment,
        segment_start=context.campaign.validation.start,
        segment_end=context.campaign.validation.end,
        trial_ordinal=2,
        bindings=context.execution_bindings,
    )
    fault_request = request.model_copy(
        update={
            "candidate": fault_candidate,
            "candidate_exact_expression_hash": fault_candidate.exact_expression_hash,
            "candidate_structural_expression_hash": fault_candidate.structural_expression_hash,
            "execution_identity": fault_identity,
            "idempotency_key": fault_identity,
            "trial_ordinal": 2,
        }
    )

    def run_fault(fault: str) -> dict[str, object]:
        fault_root = context.case_root / f"negative-fault-{fault}"
        fault_args = dict(context.adapter_args)
        fault_args["output_root"] = fault_root
        adapter = _adapter_for_case(
            _CaseContext(
                **{**context.__dict__, "case_root": fault_root, "adapter_args": fault_args}
            ),
            fault=fault,
        )
        outcome = adapter.execute(fault_request)
        return {"outcome": outcome.outcome.value, "reason": outcome.failure_reason_code}

    record(
        "PIT_LOOK_AHEAD_REJECTION",
        lambda: run_fault("pit_reject"),
        expected_reason=ReasonCode.LOOK_AHEAD,
        expected_value={"outcome": TrialOutcome.PIT_REJECT.value, "reason": ReasonCode.LOOK_AHEAD},
    )
    record(
        "EXECUTION_FAILURE",
        lambda: run_fault("execution_failure"),
        expected_reason=ReasonCode.QLIB_EXECUTION_FAILED,
        expected_value={
            "outcome": TrialOutcome.EXECUTION_FAILED.value,
            "reason": ReasonCode.QLIB_EXECUTION_FAILED,
        },
    )

    with tempfile.TemporaryDirectory(prefix="p14d-ledger-tamper-") as temporary_name:
        tampered_ledger = Path(temporary_name) / "ledger"
        shutil.copytree(context.case_root / "ledger", tampered_ledger)
        event_files = sorted((tampered_ledger / "events" / context.ledger_id).glob("*.json"))
        event_files[0].write_bytes(event_files[0].read_bytes() + b" ")
        record(
            "LEDGER_CHAIN_CORRUPTION",
            lambda: ResearchLedgerService(tampered_ledger).verify(
                context.ledger_id, created_at=CASE_STARTED_AT + timedelta(days=1)
            ),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

    selection_report_hash = run.report.selection_report_hash
    assert isinstance(selection_report_hash, str)
    selection_path = context.case_root / "selection-reports" / f"sha256-{selection_report_hash}"
    with tempfile.TemporaryDirectory(prefix="p14d-selection-tamper-") as temporary_name:
        tampered_selection_root = Path(temporary_name) / "selection"
        shutil.copytree(selection_path, tampered_selection_root / selection_path.name)
        tampered_report = tampered_selection_root / selection_path.name / "report.json"
        tampered_report.write_bytes(tampered_report.read_bytes() + b" ")
        record(
            "P14C_REPORT_TAMPER",
            lambda: verify_selection_report_artifact(tampered_selection_root / selection_path.name),
            expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
        )

    selection_report = verify_selection_report_artifact(selection_path)
    report_events = tuple(
        event
        for event in run.events
        if event.content_hash in set(selection_report.source_event_hashes)
    )
    record(
        "SELECTION_MISMATCH",
        lambda: context.selection.verify_report(selection_path, report_events[:-1]),
        expected_reason=ReasonCode.ARTIFACT_CORRUPTED,
    )

    missing = set(P14D_NEGATIVE_CASES) - set(evidence)
    extra = set(evidence) - set(P14D_NEGATIVE_CASES)
    if missing or extra:
        raise QualificationError(
            f"negative-case registry mismatch: missing={sorted(missing)} extra={sorted(extra)}"
        )
    return tuple(evidence[case_id] for case_id in P14D_NEGATIVE_CASES)


class _InjectedRestartCrash(RuntimeError):
    """Deterministic process-boundary crash used by restart qualification."""


def _restart_state(context: _CaseContext, workflow_runs: int) -> dict[str, object]:
    from quantos.application.autonomous import CampaignEventStore

    governor = ResearchCampaignGovernor(context.family, context.template, context.manifest)
    events = CampaignEventStore(context.case_root / "campaign-events").load(
        governor, context.campaign, context.budget
    )
    receipts = _load_receipts(context)
    trial_events = tuple(event for event in events if getattr(event, "trial", None) is not None)
    selection_events = tuple(
        event
        for event in events
        if getattr(getattr(event, "event_type", None), "value", None) == "SelectionFrozen"
    )
    result_paths = tuple(
        sorted(
            item for item in (context.case_root / "execution" / "research-results").glob("sha256-*")
        )
    )
    report_paths = tuple(
        sorted(item for item in (context.case_root / "selection-reports").glob("sha256-*"))
    )
    return {
        "event_hashes": tuple(event.content_hash for event in events),
        "execution_receipt_hashes": tuple(sorted(item.content_hash for item in receipts)),
        "exchange_hashes": tuple(
            sorted(
                item.content_hash
                for item in _load_exchanges(
                    context.case_root / "agent-exchanges", context.agent_policy
                )
            )
        ),
        "report_directory_names": tuple(item.name for item in report_paths),
        "research_result_directory_names": tuple(item.name for item in result_paths),
        "selection_event_hashes": tuple(item.content_hash for item in selection_events),
        "trial_event_hashes": tuple(item.content_hash for item in trial_events),
        "workflow_runs": workflow_runs,
    }


def _assert_restart_authority(
    state: dict[str, object],
    *,
    trial_events: int,
    selection_events: int,
    workflow_runs: int,
) -> None:
    if (
        state["workflow_runs"] != workflow_runs
        or len(cast(tuple[str, ...], state["execution_receipt_hashes"])) != 1
        or len(cast(tuple[str, ...], state["exchange_hashes"])) != 2
        or len(cast(tuple[str, ...], state["report_directory_names"])) != 1
        or len(cast(tuple[str, ...], state["research_result_directory_names"])) != 1
        or len(cast(tuple[str, ...], state["trial_event_hashes"])) != trial_events
        or len(cast(tuple[str, ...], state["selection_event_hashes"])) != selection_events
    ):
        raise QualificationError("restart authority counts do not reconcile")


def _restart_evidence(
    case_id: str,
    *,
    context: _CaseContext,
    pre_state: dict[str, object],
    post_state: dict[str, object],
) -> P14dRestartCaseEvidence:
    return P14dRestartCaseEvidence(
        case_id=case_id,
        input_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "campaign_hash": context.campaign.content_hash,
                    "case_id": case_id,
                    "fixture_hash": context.fixture.fixture_hash,
                }
            )
        ),
        pre_restart_evidence_hash=sha256_bytes(canonical_json_bytes(pre_state)),
        post_restart_evidence_hash=sha256_bytes(canonical_json_bytes(post_state)),
    )


def _run_restart_cases(
    root: Path,
    fixture: _Fixture,
    code: CodeProvenance,
    *,
    workspace: Path | None,
) -> tuple[P14dRestartCaseEvidence, ...]:
    original_workflow_run = QlibWorkflowResearchService.run
    results: list[P14dRestartCaseEvidence] = []

    def counting_workflow(counter: dict[str, int]):
        def run_workflow(self: object, *args: object, **kwargs: object):
            counter["count"] += 1
            return original_workflow_run(cast(QlibWorkflowResearchService, self), *args, **kwargs)

        return run_workflow

    # 1. Agent exchange published, but CampaignTrialRecorded not committed.
    context = _build_case_context(
        "RESTART_AGENT_EXCHANGE_BEFORE_TRIAL",
        root / "agent-exchange-before-trial",
        fixture,
        code,
        workspace=workspace,
    )
    workflow_calls = {"count": 0}
    crash_calls = {"count": 0}
    adapter = _adapter_for_case(context)
    orchestrator = _build_orchestrator(
        context, adapter, (context.proposal, context.malformed_proposal)
    )
    orchestrator.event_store.seed(
        context.initial_events, orchestrator.governor, context.campaign, context.budget
    )
    real_append = orchestrator.event_store.append

    def crash_before_trial(*args: object, **kwargs: object):
        crash_calls["count"] += 1
        if crash_calls["count"] == 1:
            raise _InjectedRestartCrash("crash before CampaignTrialRecorded")
        return real_append(*args, **kwargs)

    with patch.object(QlibWorkflowResearchService, "run", counting_workflow(workflow_calls)):
        with patch.object(orchestrator.event_store, "append", crash_before_trial):
            try:
                orchestrator.run(context.initial_events, started_at=CASE_STARTED_AT)
            except _InjectedRestartCrash:
                pass
            else:
                raise QualificationError("agent-exchange restart crash did not trigger")
        pre_state = _restart_state(context, workflow_calls["count"])
        if (
            len(cast(tuple[str, ...], pre_state["exchange_hashes"])) != 1
            or len(cast(tuple[str, ...], pre_state["execution_receipt_hashes"])) != 1
            or pre_state["trial_event_hashes"] != ()
        ):
            raise QualificationError("pre-restart exchange/receipt/trial state is invalid")
        restart_orchestrator = _build_orchestrator(
            context,
            _adapter_for_case(context),
            (context.proposal, context.malformed_proposal),
        )
        restart_orchestrator.run(context.initial_events, started_at=RESTART_STARTED_AT)
        post_state = _restart_state(context, workflow_calls["count"])
    _assert_restart_authority(post_state, trial_events=2, selection_events=1, workflow_runs=1)
    results.append(
        _restart_evidence(
            "AGENT_EXCHANGE_AND_EXECUTION_RECEIPT_BEFORE_TRIAL",
            context=context,
            pre_state=pre_state,
            post_state=post_state,
        )
    )

    # 2. CampaignTrialRecorded committed, but Ledger reconciliation incomplete.
    context = _build_case_context(
        "RESTART_TRIAL_BEFORE_LEDGER",
        root / "trial-before-ledger",
        fixture,
        code,
        workspace=workspace,
    )
    workflow_calls = {"count": 0}
    reconcile_calls = {"count": 0}

    with patch.object(QlibWorkflowResearchService, "run", counting_workflow(workflow_calls)):
        orchestrator = _build_orchestrator(
            context,
            _adapter_for_case(context),
            (context.proposal, context.malformed_proposal),
        )
        real_reconcile = orchestrator._reconcile_ledger  # pyright: ignore[reportPrivateUsage]

        def crash_reconcile(*args: object, **kwargs: object):
            reconcile_calls["count"] += 1
            if reconcile_calls["count"] == 2:
                raise _InjectedRestartCrash("crash during Ledger reconciliation")
            return real_reconcile(*args, **kwargs)

        orchestrator._reconcile_ledger = crash_reconcile  # type: ignore[method-assign]
        try:
            orchestrator.run(context.initial_events, started_at=CASE_STARTED_AT)
        except _InjectedRestartCrash:
            pass
        else:
            raise QualificationError("ledger restart crash did not trigger")
        pre_state = _restart_state(context, workflow_calls["count"])
        if (
            len(cast(tuple[str, ...], pre_state["execution_receipt_hashes"])) != 1
            or len(cast(tuple[str, ...], pre_state["trial_event_hashes"])) != 1
        ):
            raise QualificationError("pre-restart trial/ledger state is invalid")
        restart_orchestrator = _build_orchestrator(
            context,
            _adapter_for_case(context),
            (context.proposal, context.malformed_proposal),
        )
        restart_orchestrator.run(context.initial_events, started_at=RESTART_STARTED_AT)
        post_state = _restart_state(context, workflow_calls["count"])
    _assert_restart_authority(post_state, trial_events=2, selection_events=1, workflow_runs=1)
    results.append(
        _restart_evidence(
            "CAMPAIGN_TRIAL_COMMITTED_LEDGER_RECONCILIATION_INCOMPLETE",
            context=context,
            pre_state=pre_state,
            post_state=post_state,
        )
    )

    # 3. P14c report published, but SelectionFrozen not committed.
    context = _build_case_context(
        "RESTART_SELECTION_REPORT_BEFORE_EVENT",
        root / "selection-report-before-event",
        fixture,
        code,
        workspace=workspace,
    )
    workflow_calls = {"count": 0}
    freeze_calls = {"count": 0}

    with patch.object(QlibWorkflowResearchService, "run", counting_workflow(workflow_calls)):
        orchestrator = _build_orchestrator(
            context,
            _adapter_for_case(context),
            (context.proposal, context.malformed_proposal),
        )
        real_freeze = context.selection.freeze_selection

        def crash_freeze(*args: object, **kwargs: object):
            freeze_calls["count"] += 1
            if freeze_calls["count"] == 1:
                raise _InjectedRestartCrash("crash before SelectionFrozen")
            return real_freeze(*args, **kwargs)

        context.selection.freeze_selection = crash_freeze  # type: ignore[method-assign]
        try:
            orchestrator.run(context.initial_events, started_at=CASE_STARTED_AT)
        except _InjectedRestartCrash:
            context.selection.freeze_selection = real_freeze  # type: ignore[method-assign]
        else:
            raise QualificationError("selection-event restart crash did not trigger")
        pre_state = _restart_state(context, workflow_calls["count"])
        if (
            len(cast(tuple[str, ...], pre_state["report_directory_names"])) != 1
            or pre_state["selection_event_hashes"] != ()
        ):
            raise QualificationError("pre-restart P14c report/selection state is invalid")
        restart_orchestrator = _build_orchestrator(
            context,
            _adapter_for_case(context),
            (context.proposal, context.malformed_proposal),
        )
        restart_orchestrator.run(context.initial_events, started_at=RESTART_STARTED_AT)
        post_state = _restart_state(context, workflow_calls["count"])
    _assert_restart_authority(post_state, trial_events=2, selection_events=1, workflow_runs=1)
    results.append(
        _restart_evidence(
            "P14C_REPORT_PUBLISHED_SELECTION_EVENT_NOT_COMMITTED",
            context=context,
            pre_state=pre_state,
            post_state=post_state,
        )
    )

    if tuple(item.case_id for item in results) != P14D_RESTART_CASES:
        raise QualificationError("restart case registry is incomplete or unordered")
    return tuple(results)


def _replay_evidence(selected_bundle: _CanonicalBundle) -> P14dReplayCaseEvidence:
    run = selected_bundle.run
    context = run.context
    exchanges = _load_exchanges(context.case_root / "agent-exchanges", context.agent_policy)
    first_exchange = min(exchanges, key=lambda item: item.request.run_ordinal)
    agent_request = first_exchange.request
    execution_request = _load_receipts(context)[0].request
    store = AutonomousAgentExchangeStore(
        context.case_root / "agent-exchanges", context.agent_policy
    )
    calls = {"count": 0}
    original_run = QlibWorkflowResearchService.run

    def counting_workflow(self: object, *args: object, **kwargs: object):
        calls["count"] += 1
        return original_run(cast(QlibWorkflowResearchService, self), *args, **kwargs)

    with patch.object(QlibWorkflowResearchService, "run", counting_workflow):
        replayed = ReplayAgentDriver(store).run(agent_request)
        if replayed != first_exchange.response:
            raise QualificationError("replay returned different proposal bytes or manifest")
        replayed_outcome = run.adapter.execute(execution_request)
    if calls["count"] != 0:
        raise QualificationError("replay performed a second Qlib execution")
    if replayed.proposal_hash != first_exchange.response.proposal_hash:
        raise QualificationError("replay proposal hash changed")
    candidate_hash = run.orchestrator._extract_candidate_hash(  # pyright: ignore[reportPrivateUsage]
        replayed.proposal_bytes
    )
    if candidate_hash not in run.orchestrator._candidate_by_hash:  # pyright: ignore[reportPrivateUsage]
        raise QualificationError("replay candidate escaped the frozen manifest")
    receipt = run.adapter._read_receipt(  # pyright: ignore[reportPrivateUsage]
        execution_request.execution_identity
    )
    if receipt is None or receipt.content_hash != replayed_outcome.execution_artifact_hash:
        raise QualificationError("replay did not reuse the verified execution receipt")
    return P14dReplayCaseEvidence.create(
        request_hash=agent_request.content_hash,
        response_hash=replayed.content_hash,
        proposal_hash=replayed.proposal_hash,
        candidate_hash=candidate_hash,
        execution_identity=execution_request.execution_identity,
        execution_receipt_hash=receipt.content_hash,
        qlib_runs_before_replay=0,
        qlib_runs_after_replay=0,
    )


def _run_root_pipeline(
    root: Path,
    root_id: str,
    code: CodeProvenance,
    *,
    workspace: Path | None = None,
) -> P14dRootEvidence:
    if root_id not in {"root-A", "root-B"}:
        raise QualificationError("qualification root id is invalid")
    canonical = _run_root_canonical_bundles(root, root / "fixtures", code, workspace=workspace)
    selected = canonical[0]
    no_selection = canonical[1]
    fixture_set_hash = _fixture_set_hash(
        (selected.run.context.fixture, no_selection.run.context.fixture)
    )
    negative_cases = _run_negative_cases(selected.run)
    restart_cases = _run_restart_cases(
        root / "restart",
        selected.run.context.fixture,
        code,
        workspace=workspace,
    )
    replay_case = _replay_evidence(selected)
    selected_context = selected.run.context
    selection_plan = selected_context.selection.plan
    if selection_plan is None:
        raise QualificationError("selected case lost its P14c selection plan")
    return P14dRootEvidence.create(
        root_id=cast(str, root_id),
        fixture_set_hash=fixture_set_hash,
        qlib_binding_hash=selected_context.fixture.qlib_binding_hash,
        autonomous_campaign_policy_hash=selected_context.campaign_policy.content_hash,
        autonomous_agent_run_policy_hash=selected_context.agent_policy.content_hash,
        autonomous_compute_accounting_hash=autonomous_compute_accounting_policy_hash(),
        autonomous_execution_bindings_hash=selected_context.execution_bindings.content_hash,
        p14c_selection_plan_hash=selection_plan.content_hash,
        cases=tuple(item.evidence for item in canonical),
        negative_case_ids=P14D_NEGATIVE_CASES,
        negative_cases=negative_cases,
        restart_case_ids=P14D_RESTART_CASES,
        restart_cases=restart_cases,
        replay_case=replay_case,
    )


def _strip_runtime_telemetry(root: Path) -> None:
    """Remove non-authority Qlib/MLflow runtime state before qualification publication."""

    for path in sorted(root.rglob("mlflow-runtime"), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
    for path in sorted(root.rglob("mlruns"), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)


def _all_file_digests(root: Path) -> tuple[P14dQualificationFile, ...]:
    entries = sorted(
        (entry for entry in root.rglob("*") if entry.is_file()),
        key=lambda entry: entry.relative_to(root).as_posix(),
    )
    files = tuple(
        P14dQualificationFile(
            logical_path=entry.relative_to(root).as_posix(),
            sha256=sha256_file(entry),
            size_bytes=entry.stat().st_size,
        )
        for entry in entries
    )
    paths = tuple(item.logical_path for item in files)
    if not files or paths != tuple(sorted(set(paths))):
        raise QualificationError("qualification bundle file set is empty, duplicated, or unsorted")
    return files


def _verify_report_file_set(path: Path, report: P14dQualificationReport) -> None:
    tree = regular_tree_files(path)
    expected = {item.logical_path for item in report.files} | {"qualification-report.json"}
    actual = {item.relative_to(path).as_posix() for item in tree}
    if actual != expected:
        raise QualificationError("qualification exact-file set does not match the report")
    for item in report.files:
        target = path / item.logical_path
        if target.is_symlink() or target.stat().st_size != item.size_bytes:
            raise QualificationError("qualification file metadata does not match")
        if sha256_file(target) != item.sha256:
            raise QualificationError("qualification file hash does not match")


def _publish_qualification(
    output_root: Path,
    staging: Path,
    *,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> P14dQualificationReport:
    report_file = staging / "code-provenance.json"
    report_file.write_bytes(code.canonical_bytes())
    runtime_file = staging / "runtime-fingerprint.json"
    runtime_file.write_bytes(runtime.canonical_bytes())
    frozen = staging / "frozen"
    frozen.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "uv.lock", frozen / "uv.lock")
    shutil.copyfile(ROOT / QUALIFICATION_CONTRACT_PATH, frozen / QUALIFICATION_CONTRACT_PATH.name)
    _strip_runtime_telemetry(staging)
    files = _all_file_digests(staging)
    roots = (
        P14dRootEvidence.model_validate_json(
            (staging / "root-A" / "root-evidence.json").read_bytes()
        ),
        P14dRootEvidence.model_validate_json(
            (staging / "root-B" / "root-evidence.json").read_bytes()
        ),
    )
    contract_hash = sha256_file(ROOT / QUALIFICATION_CONTRACT_PATH)
    policy_hashes = tuple(
        sorted(
            (
                P14dNamedHash(
                    name="autonomous_agent_run_policy",
                    sha256=roots[0].autonomous_agent_run_policy_hash,
                ),
                P14dNamedHash(
                    name="autonomous_campaign_policy",
                    sha256=roots[0].autonomous_campaign_policy_hash,
                ),
                P14dNamedHash(
                    name="autonomous_compute_accounting",
                    sha256=roots[0].autonomous_compute_accounting_hash,
                ),
                P14dNamedHash(
                    name="autonomous_execution_bindings",
                    sha256=roots[0].autonomous_execution_bindings_hash,
                ),
                P14dNamedHash(name="p14c_selection_plan", sha256=roots[0].p14c_selection_plan_hash),
                P14dNamedHash(name="p14d_qualification_contract", sha256=contract_hash),
            ),
            key=lambda item: item.name,
        )
    )
    report = P14dQualificationReport.create(
        implementation_commit_hash=code.commit_hash,
        code_provenance_hash=code.content_hash,
        lockfile_hash=code.lockfile_hash,
        runtime_fingerprint_hash=runtime.content_hash,
        qualification_contract_hash=contract_hash,
        qlib_binding_hash=roots[0].qlib_binding_hash,
        fixture_set_hash=roots[0].fixture_set_hash,
        policy_hashes=policy_hashes,
        roots=roots,
        principal_hash_summary=p14d_principal_hash_summary(roots),
        negative_case_count=len(P14D_NEGATIVE_CASES) * len(roots),
        restart_case_count=len(P14D_RESTART_CASES) * len(roots),
        limitations=P14D_LIMITATIONS,
        files=files,
    )
    (staging / "qualification-report.json").write_bytes(
        canonical_json_bytes(report.model_dump(mode="python"))
    )
    destination = output_root / f"sha256-{report.qualification_hash}"
    if destination.exists():
        stored = verify_p14d_qualification_artifact(destination)
        if stored.content_hash != report.content_hash:
            raise QualificationError("existing P14d qualification bundle conflicts")
        return stored
    publish_directory(staging, destination)
    return report


def _qualify_from_provenance(
    *,
    workspace: Path,
    output_root: Path,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14d-roots-", dir=output_root) as temporary_name:
        staging = Path(temporary_name) / "bundle"
        staging.mkdir()
        root_a = staging / "root-A"
        root_b = staging / "root-B"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        evidence_a = _run_root_pipeline(root_a, "root-A", code, workspace=workspace)
        evidence_b = _run_root_pipeline(root_b, "root-B", code, workspace=workspace)
        if evidence_a != evidence_b.model_copy(update={"root_id": evidence_a.root_id}):
            raise QualificationError("independent P14d roots produced different principal evidence")
        (root_a / "root-evidence.json").write_bytes(evidence_a.canonical_bytes())
        (root_b / "root-evidence.json").write_bytes(evidence_b.canonical_bytes())
        report = _publish_qualification(
            output_root,
            staging,
            code=code,
            runtime=runtime,
        )
    artifact_path = output_root / f"sha256-{report.qualification_hash}"
    verified = verify_p14d_qualification_artifact(artifact_path)
    return {
        "schema_version": "p14d-qualification-runner-result/v1",
        "qualification_hash": verified.qualification_hash,
        "qualification_path": str(artifact_path),
        "implementation_commit_hash": verified.implementation_commit_hash,
        "lockfile_hash": verified.lockfile_hash,
        "runtime_fingerprint_hash": verified.runtime_fingerprint_hash,
        "principal_hash_summary": verified.principal_hash_summary,
        "principal_hashes_byte_exact": verified.principal_hashes_byte_exact,
        "canonical_cases": P14D_CANONICAL_CASES,
        "negative_case_count": verified.negative_case_count,
        "restart_case_count": verified.restart_case_count,
        "status": verified.status,
        "verdict": verified.verdict,
    }


def run(*, workspace: Path, output_root: Path) -> dict[str, object]:
    """Require the exact clean Git root and bind its lockfile and runtime before running."""

    if workspace.resolve() != ROOT.resolve():
        raise QualificationError("qualification workspace must be the runner's source repository")
    code = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    return _qualify_from_provenance(
        workspace=workspace, output_root=output_root, code=code, runtime=runtime
    )


def verify_p14d_qualification_artifact(path: Path) -> P14dQualificationReport:
    """Verify a P14d bundle top-down and recreate both root evidence sets bottom-up."""

    try:
        report_bytes = (path / "qualification-report.json").read_bytes()
        report = P14dQualificationReport.model_validate_json(report_bytes)
        if (
            path.name != f"sha256-{report.qualification_hash}"
            or canonical_json_bytes(report.model_dump(mode="python")) != report_bytes
        ):
            raise QualificationError("qualification report path or bytes do not match its hash")
        _verify_report_file_set(path, report)
        code = CodeProvenance.model_validate_json((path / "code-provenance.json").read_bytes())
        runtime = RuntimeFingerprint.model_validate_json(
            (path / "runtime-fingerprint.json").read_bytes()
        )
        if (
            code.content_hash != report.code_provenance_hash
            or code.commit_hash != report.implementation_commit_hash
            or code.lockfile_hash != report.lockfile_hash
            or sha256_file(path / "frozen" / "uv.lock") != report.lockfile_hash
            or runtime.content_hash != report.runtime_fingerprint_hash
            or sha256_file(path / "frozen" / QUALIFICATION_CONTRACT_PATH.name)
            != report.qualification_contract_hash
        ):
            raise QualificationError("qualification provenance does not match the report")
        verify_code_provenance(
            ROOT,
            expected_commit_hash=code.commit_hash,
            expected_lockfile_hash=code.lockfile_hash,
        )
        with tempfile.TemporaryDirectory(prefix="p14d-qualification-verify-") as temporary_name:
            temporary = Path(temporary_name)
            root_a = temporary / "root-A"
            root_b = temporary / "root-B"
            root_a.mkdir(parents=True)
            root_b.mkdir(parents=True)
            rebuilt_a = _run_root_pipeline(root_a, "root-A", code)
            rebuilt_b = _run_root_pipeline(root_b, "root-B", code)
        if rebuilt_a != report.roots[0] or rebuilt_b != report.roots[1]:
            raise QualificationError("qualification roots did not reproduce independently")
        if report.policy_hashes != tuple(
            sorted(
                (
                    P14dNamedHash(
                        name="autonomous_agent_run_policy",
                        sha256=rebuilt_a.autonomous_agent_run_policy_hash,
                    ),
                    P14dNamedHash(
                        name="autonomous_campaign_policy",
                        sha256=rebuilt_a.autonomous_campaign_policy_hash,
                    ),
                    P14dNamedHash(
                        name="autonomous_compute_accounting",
                        sha256=rebuilt_a.autonomous_compute_accounting_hash,
                    ),
                    P14dNamedHash(
                        name="autonomous_execution_bindings",
                        sha256=rebuilt_a.autonomous_execution_bindings_hash,
                    ),
                    P14dNamedHash(
                        name="p14c_selection_plan",
                        sha256=rebuilt_a.p14c_selection_plan_hash,
                    ),
                    P14dNamedHash(
                        name="p14d_qualification_contract",
                        sha256=report.qualification_contract_hash,
                    ),
                ),
                key=lambda item: item.name,
            )
        ):
            raise QualificationError("qualification policy bindings did not reproduce")
    except QualificationError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ValidationError,
    ) as error:
        raise QualificationError("P14d qualification artifact verification failed") from error
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/qualification/p14d"))
    parser.add_argument("--verify", type=Path, default=None)
    args = parser.parse_args()
    if args.verify is not None:
        report = verify_p14d_qualification_artifact(args.verify.resolve())
        result: dict[str, object] = {
            "schema_version": "p14d-qualification-verification/v1",
            "qualification_hash": report.qualification_hash,
            "status": report.status,
            "verdict": report.verdict,
        }
    else:
        result = run(workspace=args.workspace.resolve(), output_root=args.output_root.resolve())
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
