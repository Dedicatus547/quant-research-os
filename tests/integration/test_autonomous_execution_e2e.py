from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from quantos.application import data_qualified_release as release
from quantos.application.autonomous import (
    AutonomousAgentExchangeStore,
    AutonomousCampaignOrchestrator,
    AutonomousOrchestrationError,
    CampaignEventStore,
    ReplayAgentDriver,
    ScriptedAgentDriver,
)
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
    build_autonomous_execution_bindings,
)
from quantos.application.campaign_selection import (
    CampaignSelectionService,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import CampaignChainEvent, ResearchCampaignGovernor
from quantos.application.enumeration import enumerate_research_family
from quantos.application.ledger import ResearchLedgerService
from quantos.artifacts.store import sha256_file
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    AutonomousAgentRunPolicy,
    AutonomousCampaignPolicy,
    AutonomousCandidateProposal,
    AutonomousExecutionRequest,
    AutonomousLoopState,
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
    CandidateDispositionKind,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.enumeration import (
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
)
from quantos.contracts.p14dq_qualification import (
    P14DQ_CANDIDATE_HASHES,
    P14DQ_CANDIDATE_MANIFEST_HASH,
    P14DQ_FAMILY_HASH,
    P14dqCampaignEvidence,
    P14dqCandidateEvaluation,
    P14dqValidationGateEvidence,
)
from quantos.contracts.pit import SafeQlibOperator
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    HardGateId,
    ResearchPolicy,
    ResolvedExperimentSpec,
    SoftGateThreshold,
    SoftMetric,
    StrategyAuthoringSpec,
    ThresholdComparison,
    ValidationPolicy,
    ValidationSubperiod,
)
from quantos.contracts.research import (
    ResearchSegment as PolicySegment,
)
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import GateSeverity, ValidationGateId
from quantos.data import SyntheticSnapshotBuilder, verify_qlib_view, verify_snapshot
from quantos.research.qlib import (
    QlibResearchError,
    QlibWorkflowResearchService,
    ResearchResultArtifactBuilder,
    verify_p14dq_native_label_audit,
    verify_research_result,
)
from quantos.validation import verify_validation_report

ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "p14d_e2e"
E2E_SNAPSHOT_FIXTURE_ROOT = FIXTURE_ROOT / "snapshot"
E2E_VIEW_FIXTURE_ROOT = FIXTURE_ROOT / "view"
NOW = datetime(2024, 6, 1, tzinfo=UTC)


def _fixture_hash_directory(root: Path) -> tuple[Path, ...]:
    directories = tuple(
        sorted(
            item
            for item in root.iterdir()
            if item.is_dir() and item.name.startswith("sha256-") and len(item.name) == 71
        )
    )
    if len(directories) != 1:
        raise AssertionError(f"expected exactly one frozen fixture directory under {root}")
    return directories


def _sessions(count: int) -> tuple[date, ...]:
    current = date(2023, 9, 4)
    result: list[date] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _write_rows(
    root: Path, filename: str, fields: tuple[str, ...], rows: list[dict[str, str]]
) -> None:
    with (root / filename).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _synthetic_fixture(root: Path) -> tuple[date, ...]:
    root.mkdir(parents=True)
    dates = _sessions(77)
    symbols = ("600000.SH", "000001.SZ")
    stock_rows = [
        {
            "ts_code": code,
            "symbol": code[:6],
            "name": f"SYNTHETIC_{code[:6]}",
            "exchange": "SSE" if code.endswith("SH") else "SZSE",
            "list_status": "L",
            "list_date": "19900101",
            "delist_date": "",
        }
        for code in symbols
    ]
    _write_rows(
        root,
        "stock_basic.csv",
        ("ts_code", "symbol", "name", "exchange", "list_status", "list_date", "delist_date"),
        stock_rows,
    )

    calendar_rows: list[dict[str, str]] = []
    for exchange in ("SSE", "SZSE"):
        for index, session in enumerate(dates):
            previous = dates[index - 1] if index else session - timedelta(days=3)
            calendar_rows.append(
                {
                    "exchange": exchange,
                    "cal_date": session.strftime("%Y%m%d"),
                    "is_open": "1",
                    "pretrade_date": previous.strftime("%Y%m%d"),
                }
            )
    _write_rows(
        root,
        "trade_cal.csv",
        ("exchange", "cal_date", "is_open", "pretrade_date"),
        calendar_rows,
    )

    bars: list[dict[str, str]] = []
    factors: list[dict[str, str]] = []
    limits: list[dict[str, str]] = []
    for code_index, code in enumerate(symbols):
        prior_close = 10.0 if code_index == 0 else 20.0
        daily_step = 0.10 if code_index == 0 else 0.01
        for _index, session in enumerate(dates):
            close = prior_close + daily_step
            opening = prior_close
            bar = {
                "ts_code": code,
                "trade_date": session.strftime("%Y%m%d"),
                "open": f"{opening:.6f}",
                "high": f"{close + 0.05:.6f}",
                "low": f"{opening - 0.05:.6f}",
                "close": f"{close:.6f}",
                "pre_close": f"{prior_close:.6f}",
                "vol": "10000",
                "amount": f"{close * 10000:.3f}",
            }
            bars.append(bar)
            factors.append(
                {
                    "ts_code": code,
                    "trade_date": session.strftime("%Y%m%d"),
                    "adj_factor": "1.0",
                }
            )
            limits.append(
                {
                    "ts_code": code,
                    "trade_date": session.strftime("%Y%m%d"),
                    "pre_close": f"{prior_close:.6f}",
                    "up_limit": f"{prior_close * 1.1:.6f}",
                    "down_limit": f"{prior_close * 0.9:.6f}",
                }
            )
            prior_close = close
    _write_rows(
        root,
        "bars.csv",
        ("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"),
        bars,
    )
    _write_rows(root, "adj_factor.csv", ("ts_code", "trade_date", "adj_factor"), factors)
    _write_rows(
        root,
        "stk_limit.csv",
        ("ts_code", "trade_date", "pre_close", "up_limit", "down_limit"),
        limits,
    )

    index_rows: list[dict[str, str]] = []
    prior_index = 3000.0
    for session in dates:
        close = prior_index + 0.001
        index_rows.append(
            {
                "ts_code": "000300.SH",
                "trade_date": session.strftime("%Y%m%d"),
                "open": f"{prior_index:.6f}",
                "high": f"{close + 0.1:.6f}",
                "low": f"{prior_index - 0.1:.6f}",
                "close": f"{close:.6f}",
                "pre_close": f"{prior_index:.6f}",
                "vol": "1000000",
                "amount": "30000000",
            }
        )
        prior_index = close
    _write_rows(
        root,
        "index_daily.csv",
        ("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"),
        index_rows,
    )
    _write_rows(
        root,
        "index_weight.csv",
        ("index_code", "con_code", "trade_date", "weight"),
        [
            {
                "index_code": "000300.SH",
                "con_code": code,
                "trade_date": dates[0].strftime("%Y%m%d"),
                "weight": "50.0",
            }
            for code in symbols
        ],
    )
    _write_rows(root, "stock_st.csv", ("ts_code", "trade_date", "type"), [])
    _write_rows(
        root,
        "suspend_d.csv",
        ("ts_code", "trade_date", "suspend_type", "suspend_timing"),
        [],
    )
    (root / "manifest.json").write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "synthetic-snapshot/v1",
                "dataset_id": "p14d-offline-execution-e2e",
                "synthetic": True,
                "redistributable": True,
                "instruments": list(symbols),
                "date_range": {"start": dates[0], "end": dates[-1]},
            }
        )
    )
    return dates


def _clean_provenance_copy(destination: Path) -> tuple[str, str]:
    destination.mkdir()
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    for entry in listed.split(b"\0"):
        if not entry:
            continue
        relative = Path(entry.decode("utf-8"))
        source = ROOT / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    subprocess.run(["git", "-C", str(destination), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(destination), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(destination),
            "-c",
            "user.name=QuantOS offline integration fixture",
            "-c",
            "user.email=quantos-fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "temporary provenance fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, sha256_file(destination / "uv.lock")


def _contracts(
    root: Path,
    dates: tuple[date, ...],
    snapshot: DataSnapshotManifest,
    snapshot_path: Path,
    snapshot_hash: str,
    view: QlibViewManifest,
    view_hash: str,
    qlib_view_path: Path,
    *,
    family_bundle: tuple[object, object, object] | None = None,
    soft_reject: bool = False,
) -> tuple[object, ...]:
    ledger_id = "p14d-e2e-ledger"
    ledger = ResearchLedgerService(root / "ledger")
    evidence_bytes = canonical_json_bytes({"body": "offline frozen synthetic campaign input"})
    evidence_ref = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(evidence_bytes),
        media_type="application/json",
        source_domain="p14d-e2e-fixture",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    ledger.append(
        ledger_id=ledger_id,
        node_id="frozen-campaign-evidence",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=evidence_ref,
        object_bytes=evidence_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW,
    )
    initial_ledger = ledger.verify(ledger_id, created_at=NOW + timedelta(seconds=1))

    template = ResearchFactorTemplateSpec(
        template_id="p14d-e2e-delta-template",
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
    family = ResearchFamilySpec(
        family_id="p14d-e2e-family",
        research_question="Does the frozen price delta rank future synthetic returns?",
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )
    manifest = enumerate_research_family(family, template)
    if family_bundle is not None:
        template, family, manifest = family_bundle
    first_candidate = manifest.candidates[0]
    trial_window = cast(int, first_candidate.parameters[0].value)
    budget = ResearchBudgetSpec(
        budget_id="p14d-e2e-budget",
        max_trials=2,
        max_distinct_candidates=2,
        max_agent_runs=2,
        max_executions=2,
        max_validation_rounds=2,
        max_compute_seconds=100_000,
    )
    test_start, test_end = dates[36], dates[75]
    campaign = ResearchCampaignSpec(
        campaign_id="p14d-e2e-campaign",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=(evidence_ref.object_hash,),
        ledger_snapshot_hash=initial_ledger.content_hash,
        snapshot_hash=snapshot_hash,
        qlib_view_hash=view_hash,
        development=ResearchSegment(start=dates[0], end=dates[35]),
        validation=ResearchSegment(start=test_start, end=test_end),
        sealed_confirmation=ResearchSegment(
            start=dates[76] + timedelta(days=1), end=dates[76] + timedelta(days=30)
        ),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    research_policy = ResearchPolicy(
        policy_id="p14d-e2e-research-policy",
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
        policy_id="p14d-e2e-validation-policy",
        hard_gates=tuple(HardGateId),
        soft_gates=(
            (
                SoftGateThreshold(
                    metric=SoftMetric.OOS_SHARPE,
                    comparison=ThresholdComparison.MIN,
                    threshold=1.0e9,
                ),
            )
            if soft_reject
            else ()
        ),
        minimum_oos_observations=1,
        parameter_windows=(trial_window,),
        parameter_top_k=(1,),
        subperiods=(
            ValidationSubperiod(period_id="full-validation", start=test_start, end=test_end),
        ),
        minimum_subperiod_observations=1,
    )
    cost_policy = release_cost_policy()
    backtest_policy = release_backtest_policy()
    authoring = ExperimentAuthoringSpec(
        experiment_id="p14d-e2e-frozen-candidate",
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
    execution_root = root / "execution"
    provenance_root = root / "provenance"
    commit_hash, lock_hash = _clean_provenance_copy(provenance_root)
    assert snapshot.snapshot_hash == snapshot_hash
    assert view.view_hash == view_hash
    bindings = build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        research_policy=research_policy,
        validation_policy=validation_policy,
        authoring=authoring,
        cost_policy=cost_policy,
        backtest_policy=backtest_policy,
        code_commit_hash=commit_hash,
        lockfile_hash=lock_hash,
    )
    adapter_args = {
        "campaign": campaign,
        "family": family,
        "budget": budget,
        "template": template,
        "manifest": manifest,
        "snapshot_path": snapshot_path,
        "qlib_view_path": qlib_view_path,
        "base_authoring": authoring,
        "research_policy": research_policy,
        "validation_policy": validation_policy,
        "cost_policy": cost_policy,
        "backtest_policy": backtest_policy,
        "bindings": bindings,
        "output_root": execution_root,
        "workspace": provenance_root,
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
        qlib_view_path,
        (execution_root / "research-results",),
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
    search_policy = ResearchLedgerSearchPolicy(
        policy_id="p14d-e2e-search-policy",
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
        policy_id="p14d-e2e-context-budget",
        max_items=50,
        max_item_bytes=262144,
        max_serialized_bytes=1_000_000,
    )
    campaign_policy = AutonomousCampaignPolicy(
        policy_id="p14d-e2e-campaign-policy",
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
        rationale="deterministic synthetic integration proposal",
    )
    malformed_proposal = canonical_json_bytes(
        {"candidate_hash": manifest.candidates[1].content_hash}
    )
    return (
        ledger_id,
        initial_ledger,
        ledger,
        campaign,
        family,
        budget,
        template,
        manifest,
        search_policy,
        context_budget,
        campaign_policy,
        agent_policy,
        selection,
        (activation, plan_event),
        adapter_args,
        proposal,
        malformed_proposal,
        execution_root,
    )


def release_cost_policy():
    from quantos.contracts.cost import CostPolicy

    return CostPolicy(
        policy_id="p14d-e2e-cost-policy",
        open_cost_rate=0.0005,
        close_cost_rate=0.0015,
        minimum_cost_cny=5.0,
        trade_unit_shares=100,
        volume_limit_fraction=0.1,
    )


def release_backtest_policy():
    from quantos.contracts.cost import BacktestPolicy

    return BacktestPolicy(
        policy_id="p14d-e2e-backtest-policy",
        benchmark="SH000300",
        initial_cash_cny=1_000_000.0,
    )


def test_scripted_autonomous_real_execution_restart_ledger_and_p14c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "fixture"
    dates = _synthetic_fixture(fixture_root)
    snapshot_fixture = _fixture_hash_directory(E2E_SNAPSHOT_FIXTURE_ROOT)[0]
    snapshot_path = tmp_path / "prebuilt-snapshot" / snapshot_fixture.name
    shutil.copytree(snapshot_fixture, snapshot_path)
    snapshot_manifest = verify_snapshot(snapshot_path)
    stale_fixture_root = tmp_path / "stale-fixture"
    shutil.copytree(fixture_root, stale_fixture_root)
    instrument_master = stale_fixture_root / "stock_basic.csv"
    instrument_master.write_text(
        instrument_master.read_text(encoding="utf-8").replace(
            "SYNTHETIC_600000", "SYNTHETIC_REVISION_600000", 1
        ),
        encoding="utf-8",
    )
    stale_snapshot = SyntheticSnapshotBuilder().build(
        stale_fixture_root, tmp_path / "stale-snapshot"
    )
    assert stale_snapshot.manifest.snapshot_hash != snapshot_manifest.snapshot_hash
    view_fixture = _fixture_hash_directory(E2E_VIEW_FIXTURE_ROOT)[0]
    view_path = tmp_path / "prebuilt-views" / view_fixture.name
    shutil.copytree(view_fixture, view_path)
    view_manifest = verify_qlib_view(view_path)
    contracts = _contracts(
        tmp_path,
        dates,
        snapshot_manifest,
        snapshot_path,
        snapshot_manifest.snapshot_hash,
        view_manifest,
        view_manifest.view_hash,
        view_path,
    )
    (
        ledger_id,
        initial_ledger,
        ledger,
        campaign,
        family,
        budget,
        template,
        manifest,
        search_policy,
        context_budget,
        campaign_policy,
        agent_policy,
        selection,
        initial_events,
        adapter_args,
        proposal,
        malformed_proposal,
        execution_root,
    ) = contracts
    stale_adapter_args = cast(dict[str, object], adapter_args).copy()
    stale_adapter_args["snapshot_path"] = stale_snapshot.path
    with pytest.raises(ValueError, match="bindings disagree"):
        QuantosResearchExecutionAdapter(**stale_adapter_args)
    workflow_runs: list[str] = []
    original_workflow_run = QlibWorkflowResearchService.run

    def count_workflow_run(self: QlibWorkflowResearchService, *args: object, **kwargs: object):
        execution_identity = cast(str, kwargs["execution_identity"])
        workflow_runs.append(execution_identity)
        return original_workflow_run(self, *args, **kwargs)

    monkeypatch.setattr(QlibWorkflowResearchService, "run", count_workflow_run)
    execution_requests: list[AutonomousExecutionRequest] = []

    class CountingAdapter(QuantosResearchExecutionAdapter):
        def execute(self, request: AutonomousExecutionRequest):
            execution_requests.append(request)
            return super().execute(request)

    def adapter() -> CountingAdapter:
        return CountingAdapter(**cast(dict[str, object], adapter_args))

    def orchestrator(port: CountingAdapter) -> AutonomousCampaignOrchestrator:
        return AutonomousCampaignOrchestrator(
            campaign=cast(ResearchCampaignSpec, campaign),
            family=cast(ResearchFamilySpec, family),
            budget=cast(ResearchBudgetSpec, budget),
            template=cast(ResearchFactorTemplateSpec, template),
            manifest=cast(object, manifest),
            initial_ledger_snapshot=cast(object, initial_ledger),
            ledger_service=cast(ResearchLedgerService, ledger),
            ledger_id=cast(str, ledger_id),
            search_policy=cast(ResearchLedgerSearchPolicy, search_policy),
            context_budget=cast(ResearchContextBudgetPolicy, context_budget),
            campaign_policy=cast(AutonomousCampaignPolicy, campaign_policy),
            agent_run_policy=cast(AutonomousAgentRunPolicy, agent_policy),
            agent_driver=ScriptedAgentDriver(
                (
                    cast(AutonomousCandidateProposal, proposal),
                    cast(bytes, malformed_proposal),
                ),
                cast(AutonomousAgentRunPolicy, agent_policy),
            ),
            execution_port=port,
            exchange_root=tmp_path / "agent-exchanges",
            event_root=tmp_path / "campaign-events",
            selection_service=cast(CampaignSelectionService, selection),
            selection_artifact_root=tmp_path / "selection-reports",
            autonomous_report_root=tmp_path / "loop-reports",
            execution_bindings=cast(object, cast(dict[str, object], adapter_args)["bindings"]),
        )

    started_at = NOW + timedelta(seconds=30)
    first_orchestrator = orchestrator(adapter())
    cast(CampaignEventStore, first_orchestrator.event_store).seed(
        cast(tuple[CampaignChainEvent, ...], initial_events),
        cast(ResearchCampaignGovernor, first_orchestrator.governor),
        cast(ResearchCampaignSpec, campaign),
        cast(ResearchBudgetSpec, budget),
    )

    def crash_before_trial_commit(
        *_args: object, **_kwargs: object
    ) -> tuple[CampaignChainEvent, ...]:
        raise RuntimeError("simulated crash before CampaignTrialRecorded commit")

    monkeypatch.setattr(first_orchestrator.event_store, "append", crash_before_trial_commit)
    with pytest.raises(RuntimeError, match="before CampaignTrialRecorded"):
        first_orchestrator.run(
            cast(tuple[CampaignChainEvent, ...], initial_events), started_at=started_at
        )

    assert len(execution_requests) == 1
    request = execution_requests[0]
    receipt_root = cast(Path, execution_root) / "execution-records" / "identities"
    receipt_files = tuple(receipt_root.glob("*.json"))
    assert len(receipt_files) == 1
    receipt = json.loads(receipt_files[0].read_bytes())
    result_hash = cast(str, receipt["outcome"]["research_result_hash"])
    result_path = cast(Path, execution_root) / "research-results" / f"sha256-{result_hash}"
    real_result = verify_research_result(result_path)
    assert real_result.expression_spec_hash == request.candidate.expression.content_hash
    assert real_result.snapshot_hash == request.snapshot_hash
    assert real_result.qlib_view_hash == request.qlib_view_hash
    prediction_rows = json.loads((result_path / "predictions.json").read_bytes())
    assert real_result.prediction_row_count == len(prediction_rows)
    assert {row["qlib_instrument_id"] for row in prediction_rows} == {
        "SH600000",
        "SZ000001",
    }

    exchange_store = AutonomousAgentExchangeStore(
        tmp_path / "agent-exchanges", cast(AutonomousAgentRunPolicy, agent_policy)
    )
    first_exchange = exchange_store.for_campaign_ordinal(
        cast(ResearchCampaignSpec, campaign).content_hash, 1
    )
    assert first_exchange is not None
    replayed_response = ReplayAgentDriver(exchange_store).run(first_exchange.request)
    assert replayed_response == first_exchange.response
    replayed_proposal = AutonomousCandidateProposal.model_validate_json(
        replayed_response.proposal_bytes
    )
    assert replayed_proposal.candidate_hash == request.candidate.content_hash
    replayed_outcome = adapter().execute(request)
    assert replayed_outcome.research_result_hash == result_hash
    assert request.execution_identity == execution_requests[0].execution_identity
    assert len(workflow_runs) == 1

    second_orchestrator = orchestrator(adapter())
    real_append = second_orchestrator.event_store.append

    def commit_trial_then_crash(*args: object, **kwargs: object) -> tuple[CampaignChainEvent, ...]:
        real_append(*args, **kwargs)
        raise RuntimeError("simulated crash after CampaignTrialRecorded commit")

    monkeypatch.setattr(second_orchestrator.event_store, "append", commit_trial_then_crash)
    with pytest.raises(RuntimeError, match="after CampaignTrialRecorded"):
        second_orchestrator.run(
            cast(tuple[CampaignChainEvent, ...], initial_events), started_at=started_at
        )
    assert len(tuple((tmp_path / "campaign-events").glob("*-sha256-*.json"))) == 3
    assert len(workflow_runs) == 1

    third_orchestrator = orchestrator(adapter())
    report, events = third_orchestrator.run(
        cast(tuple[CampaignChainEvent, ...], initial_events), started_at=started_at
    )
    assert len(workflow_runs) == 1
    assert len(tuple((cast(Path, execution_root) / "research-results").glob("sha256-*"))) == 1
    assert report.final_ledger_snapshot_hash != cast(object, initial_ledger).content_hash
    assert report.selection_report_hash is not None
    assert report.sealed_confirmation_authority is False
    assert report.state in {
        AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
        AutonomousLoopState.SELECTION_COMPLETE,
    }
    trials = [event.trial for event in events if getattr(event, "trial", None) is not None]
    assert [item.outcome for item in trials] == [TrialOutcome.PASS, TrialOutcome.SCHEMA_INVALID]

    exchange_files = sorted((tmp_path / "agent-exchanges").glob("sha256-*.json"))
    assert len(exchange_files) == 2
    exchange_requests = [json.loads(path.read_bytes())["request"] for path in exchange_files]
    second_context = next(request for request in exchange_requests if request["run_ordinal"] == 2)
    context_pack = second_context["context_pack"]
    assert context_pack["ledger_snapshot_hash"] != cast(object, initial_ledger).content_hash
    assert second_context["budget"]["used_trials"] == 1
    context_hashes = {item["object_ref"]["object_hash"] for item in context_pack["items"]}
    trial_hash = cast(str, trials[0].content_hash)
    assert result_hash in context_hashes
    assert trial_hash in context_hashes
    final_ledger = cast(ResearchLedgerService, ledger).verify(
        cast(str, ledger_id), created_at=started_at + timedelta(minutes=1)
    )
    assert result_hash in final_ledger.node_object_hashes
    assert trial_hash in final_ledger.node_object_hashes

    report_dirs = tuple((tmp_path / "selection-reports").glob("sha256-*"))
    assert len(report_dirs) == 1
    selection_report = verify_selection_report_artifact(report_dirs[0])
    assert selection_report.verdict in {
        CampaignSelectionVerdict.SELECTED,
        CampaignSelectionVerdict.NO_SELECTION,
    }
    assert selection_report.run_status.value == "SUCCEEDED"
    assert report.state is (
        AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION
        if selection_report.verdict is CampaignSelectionVerdict.SELECTED
        else AutonomousLoopState.SELECTION_COMPLETE
    )
    assert not any(
        getattr(event, "event_type", None) is not None
        and getattr(event.event_type, "value", None) == "OOSAccessed"
        for event in events
    )

    restarted_adapter = adapter()
    exact_retry = restarted_adapter.execute(request)
    assert exact_retry.research_result_hash == result_hash
    assert len(workflow_runs) == 1
    conflicting_request = request.model_copy(update={"agent_run_hash": "a" * 64})
    with pytest.raises(AutonomousOrchestrationError) as rejected:
        restarted_adapter.execute(conflicting_request)
    assert rejected.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    invalid_requests = (
        request.model_copy(update={"candidate_manifest_hash": "e" * 64}),
        request.model_copy(update={"snapshot_hash": "f" * 64}),
        request.model_copy(update={"dataset_id": "different-dataset"}),
        request.model_copy(update={"qlib_view_hash": "9" * 64}),
        request.model_copy(update={"authoring_hash": "6" * 64}),
        request.model_copy(update={"segment_end": request.segment_end - timedelta(days=1)}),
        request.model_copy(update={"candidate_exact_expression_hash": "8" * 64}),
        request.model_copy(update={"execution_identity": "7" * 64, "idempotency_key": "7" * 64}),
    )
    for invalid_request in invalid_requests:
        with pytest.raises(AutonomousOrchestrationError) as mismatch:
            restarted_adapter.execute(invalid_request)
        assert mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    with pytest.raises(ValidationError):
        AutonomousExecutionRequest.model_validate(
            {**request.model_dump(mode="python"), "research_result": real_result.model_dump()}
        )

    prediction_file = result_path / "predictions.json"
    prediction_file.write_bytes(prediction_file.read_bytes() + b" ")
    with pytest.raises(QlibResearchError):
        verify_research_result(result_path)
    with pytest.raises(AutonomousOrchestrationError) as tampered:
        restarted_adapter.verify_research_result(result_hash)
    assert tampered.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    second_candidate = cast(object, manifest).candidates[1]
    bindings = cast(object, cast(dict[str, object], adapter_args)["bindings"])
    failure_identity = autonomous_execution_identity(
        campaign_hash=request.campaign_hash,
        family_hash=request.family_hash,
        budget_hash=request.budget_hash,
        candidate_manifest_hash=request.candidate_manifest_hash,
        candidate=second_candidate,
        snapshot_hash=request.snapshot_hash,
        qlib_view_hash=request.qlib_view_hash,
        segment=request.segment,
        segment_start=request.segment_start,
        segment_end=request.segment_end,
        trial_ordinal=2,
        bindings=bindings,
    )
    failure_request = AutonomousExecutionRequest.model_validate(
        {
            **request.model_dump(mode="python"),
            "idempotency_key": failure_identity,
            "execution_identity": failure_identity,
            "trial_ordinal": 2,
            "candidate": second_candidate,
            "candidate_exact_expression_hash": second_candidate.exact_expression_hash,
            "candidate_structural_expression_hash": second_candidate.structural_expression_hash,
        }
    )
    for reason_code, expected_outcome in (
        (ReasonCode.LOOK_AHEAD, TrialOutcome.PIT_REJECT),
        (ReasonCode.QLIB_EXECUTION_FAILED, TrialOutcome.EXECUTION_FAILED),
    ):
        failure_args = cast(dict[str, object], adapter_args).copy()
        failure_args["output_root"] = tmp_path / f"failure-{reason_code.value.lower()}"
        failure_adapter = QuantosResearchExecutionAdapter(**failure_args)

        def fail_existing_service(
            *, _reason_code: ReasonCode = reason_code, **_kwargs: object
        ) -> object:
            raise QlibResearchError(_reason_code, "typed offline service failure fixture")

        monkeypatch.setattr(release, "build_research_variant", fail_existing_service)
        failure_outcome = failure_adapter.execute(failure_request)
        assert failure_outcome.outcome is expected_outcome
        assert failure_outcome.failure_reason_code is reason_code
        assert failure_outcome.execution_requested is (
            expected_outcome is not TrialOutcome.PIT_REJECT
        )
        failure_evidence = tuple(
            evidence
            for evidence_hash in failure_outcome.evidence_hashes
            if (evidence := failure_adapter.verify_execution_failure(evidence_hash)) is not None
        )
        assert len(failure_evidence) == 1
        assert failure_evidence[0].reason_code is reason_code

    unexpected_args = cast(dict[str, object], adapter_args).copy()
    unexpected_args["output_root"] = tmp_path / "unexpected-internal-failure"
    unexpected_adapter = QuantosResearchExecutionAdapter(**unexpected_args)

    def raise_unexpected_bug(**_kwargs: object) -> object:
        raise TypeError("unexpected internal implementation failure")

    monkeypatch.setattr(release, "build_research_variant", raise_unexpected_bug)
    with pytest.raises(TypeError, match="unexpected internal implementation failure"):
        unexpected_adapter.execute(failure_request)


def _load_p14dq_runner() -> object:
    """Load the frozen P14-DQ qualification runner exactly as its unit test does."""

    spec = importlib.util.spec_from_file_location(
        "p14dq_zero_eligible_path_runner", ROOT / "scripts/p14dq_qualification.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return module


def _revalidated(
    evaluation: P14dqCandidateEvaluation,
    gates: tuple[P14dqValidationGateEvidence, ...],
    trial_outcome: TrialOutcome,
) -> P14dqCandidateEvaluation:
    return P14dqCandidateEvaluation.model_validate(
        {
            **evaluation.model_dump(mode="python"),
            "validation_gates": gates,
            "trial_outcome": trial_outcome,
        }
    )


def test_p14dq_zero_eligible_natural_path_reaches_engineering_acceptance(
    tmp_path: Path,
) -> None:
    """Full zero-eligible P14-DQ path over real artifacts.

    Real candidate execution -> real ResearchResult -> real DQ native-label export-audit
    sidecar -> real Validation `SUCCEEDED`/`REJECT` produced by a genuine soft research
    threshold -> the exact P14-DQ admissible-rejection predicate -> a real P14c
    `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` report with zero eligible candidates ->
    the P14-DQ engineering acceptance layer.

    Boundary: the frozen P14-DQ campaign/snapshot/view artifacts are ~198 MB and
    gitignored, and the adapter refuses `p14dq_v2_profile` on any other inputs, so this
    test runs the frozen P14-DQ template/family/manifest on the synthetic fixture
    snapshot/view and creates each DQ sidecar through the same frozen builder API. No
    frozen threshold, gate, policy, family, manifest or P14c rule is modified.
    """

    runner = _load_p14dq_runner()
    family_bundle = runner._p14dq_family_manifest()
    manifest = family_bundle[2]
    assert tuple(item.content_hash for item in manifest.candidates) == P14DQ_CANDIDATE_HASHES

    fixture_root = tmp_path / "fixture"
    dates = _synthetic_fixture(fixture_root)
    snapshot_fixture = _fixture_hash_directory(E2E_SNAPSHOT_FIXTURE_ROOT)[0]
    snapshot_path = tmp_path / "prebuilt-snapshot" / snapshot_fixture.name
    shutil.copytree(snapshot_fixture, snapshot_path)
    snapshot_manifest = verify_snapshot(snapshot_path)
    view_fixture = _fixture_hash_directory(E2E_VIEW_FIXTURE_ROOT)[0]
    view_path = tmp_path / "prebuilt-views" / view_fixture.name
    shutil.copytree(view_fixture, view_path)
    view_manifest = verify_qlib_view(view_path)

    contracts = _contracts(
        tmp_path,
        dates,
        snapshot_manifest,
        snapshot_path,
        snapshot_manifest.snapshot_hash,
        view_manifest,
        view_manifest.view_hash,
        view_path,
        family_bundle=family_bundle,
        soft_reject=True,
    )
    (
        ledger_id,
        initial_ledger,
        ledger,
        campaign,
        campaign_family,
        budget,
        campaign_template,
        campaign_manifest,
        search_policy,
        context_budget,
        campaign_policy,
        agent_policy,
        selection,
        initial_events,
        adapter_args,
        _proposal,
        _malformed,
        execution_root,
    ) = contracts
    assert campaign_family.content_hash == P14DQ_FAMILY_HASH
    assert campaign_manifest.content_hash == P14DQ_CANDIDATE_MANIFEST_HASH
    research_policy = cast(ResearchPolicy, cast(dict[str, object], adapter_args)["research_policy"])

    proposals = tuple(
        AutonomousCandidateProposal(
            campaign_hash=cast(ResearchCampaignSpec, campaign).content_hash,
            candidate_hash=candidate.content_hash,
            parameters=candidate.parameters,
            expression=candidate.expression,
            exact_expression_hash=candidate.exact_expression_hash,
            structural_expression_hash=candidate.structural_expression_hash,
            rationale=f"zero-eligible deterministic proposal {index}",
        )
        for index, candidate in enumerate(cast(object, campaign_manifest).candidates)
    )
    execution_port = QuantosResearchExecutionAdapter(**cast(dict[str, object], adapter_args))
    orchestrator = AutonomousCampaignOrchestrator(
        campaign=cast(ResearchCampaignSpec, campaign),
        family=cast(ResearchFamilySpec, campaign_family),
        budget=cast(ResearchBudgetSpec, budget),
        template=cast(ResearchFactorTemplateSpec, campaign_template),
        manifest=cast(object, campaign_manifest),
        initial_ledger_snapshot=cast(object, initial_ledger),
        ledger_service=cast(ResearchLedgerService, ledger),
        ledger_id=cast(str, ledger_id),
        search_policy=cast(ResearchLedgerSearchPolicy, search_policy),
        context_budget=cast(ResearchContextBudgetPolicy, context_budget),
        campaign_policy=cast(AutonomousCampaignPolicy, campaign_policy),
        agent_run_policy=cast(AutonomousAgentRunPolicy, agent_policy),
        agent_driver=ScriptedAgentDriver(
            cast(tuple[AutonomousCandidateProposal, ...], proposals),
            cast(AutonomousAgentRunPolicy, agent_policy),
        ),
        execution_port=execution_port,
        exchange_root=tmp_path / "agent-exchanges",
        event_root=tmp_path / "campaign-events",
        selection_service=cast(CampaignSelectionService, selection),
        selection_artifact_root=tmp_path / "selection-reports",
        autonomous_report_root=tmp_path / "loop-reports",
        execution_bindings=cast(object, cast(dict[str, object], adapter_args)["bindings"]),
    )
    cast(CampaignEventStore, orchestrator.event_store).seed(
        cast(tuple[CampaignChainEvent, ...], initial_events),
        cast(ResearchCampaignGovernor, orchestrator.governor),
        cast(ResearchCampaignSpec, campaign),
        cast(ResearchBudgetSpec, budget),
    )
    started_at = NOW + timedelta(seconds=30)
    report, events = orchestrator.run(
        cast(tuple[CampaignChainEvent, ...], initial_events), started_at=started_at
    )

    trial_events = [event for event in events if getattr(event, "trial", None) is not None]
    trials = [event.trial for event in trial_events]
    trial_by_candidate = {cast(object, event.trial).candidate_hash: event for event in trial_events}
    assert len(trials) == 2
    assert [item.outcome for item in trials] == [
        TrialOutcome.SOFT_REJECT,
        TrialOutcome.SOFT_REJECT,
    ]
    assert report.state is AutonomousLoopState.SELECTION_COMPLETE
    assert report.selection_event_hash is None
    assert report.sealed_confirmation_authority is False

    receipt_root = cast(Path, execution_root) / "execution-records" / "identities"
    receipts = tuple(
        AutonomousExecutionReceipt.model_validate_json(path.read_bytes())
        for path in sorted(receipt_root.glob("*.json"))
    )
    assert len(receipts) == 2
    exchange_store = AutonomousAgentExchangeStore(
        tmp_path / "agent-exchanges", cast(AutonomousAgentRunPolicy, agent_policy)
    )
    exchanges = tuple(
        exchange_store.for_campaign_ordinal(
            cast(ResearchCampaignSpec, campaign).content_hash, ordinal
        )
        for ordinal in (1, 2)
    )
    assert all(item is not None for item in exchanges)

    calendar = tuple(
        date.fromisoformat(line)
        for line in (view_path / "calendars" / "day.txt").read_text(encoding="utf-8").splitlines()
        if line
    )
    validation_segment = cast(ResearchCampaignSpec, campaign).validation
    dq_calendar = tuple(
        day for day in calendar if validation_segment.start <= day <= validation_segment.end
    )
    assert dq_calendar

    evaluations: list[P14dqCandidateEvaluation] = []
    for candidate_hash in P14DQ_CANDIDATE_HASHES:
        receipt = next(
            item for item in receipts if item.request.candidate.content_hash == candidate_hash
        )
        result_hash = receipt.outcome.research_result_hash
        validation_hash = receipt.outcome.validation_report_hash
        assert result_hash is not None and validation_hash is not None
        result_path = cast(Path, execution_root) / "research-results" / f"sha256-{result_hash}"
        result_manifest = verify_research_result(result_path)
        validation_report = verify_validation_report(
            cast(Path, execution_root) / "validation" / f"sha256-{validation_hash}"
        )
        assert validation_report.content_hash == validation_hash
        assert validation_report.run_status is RunStatus.SUCCEEDED
        assert validation_report.verdict is ValidationVerdict.REJECT
        assert validation_report.canonical is True
        submitted = {gate.gate_id: gate for gate in validation_report.gates}
        assert tuple(submitted) == tuple(ValidationGateId)
        for gate in validation_report.gates:
            assert gate.verdict is not ValidationVerdict.NOT_EVALUATED
            if gate.severity is GateSeverity.HARD:
                assert gate.verdict is ValidationVerdict.PASS
        assert submitted[ValidationGateId.G4_REFERENCE_BACKTEST].verdict is ValidationVerdict.PASS
        assert [
            (gate_id, gate.reason_code)
            for gate_id, gate in submitted.items()
            if gate.verdict is ValidationVerdict.REJECT
        ] == [(ValidationGateId.G5_OUT_OF_SAMPLE, ReasonCode.SOFT_THRESHOLD_NOT_MET)]

        identity = receipt.request.execution_identity
        native_root = (
            cast(Path, execution_root)
            / "executions"
            / identity
            / "qlib-workflow"
            / "native-records"
            / f"sha256-{identity}"
        )
        signal_path = (
            cast(Path, execution_root)
            / "executions"
            / identity
            / "baseline"
            / "signals"
            / f"sha256-{result_manifest.signal_artifact_hash}"
        )
        resolved = ResolvedExperimentSpec.model_validate_json(
            (signal_path / "resolved-experiment.json").read_bytes()
        )
        built = ResearchResultArtifactBuilder().build(
            resolved,
            research_policy,
            signal_path,
            native_root,
            cast(Path, execution_root) / "research-results",
            qlib_run_id=result_manifest.qlib_run_id,
            label_expression=result_manifest.label_expression,
            dq_calendar=dq_calendar,
            dq_audit_root=cast(Path, execution_root) / "research-result-audits",
        )
        assert built.manifest.artifact_hash == result_hash
        assert built.export_audit_path is not None
        audit = verify_p14dq_native_label_audit(
            built.path, native_root, built.export_audit_path, dq_calendar
        )
        assert audit.audit_hash == built.export_audit_hash

        trial_event = trial_by_candidate[candidate_hash]
        trial = trial_event.trial
        evaluations.append(
            P14dqCandidateEvaluation(
                candidate_hash=candidate_hash,
                trial_event_hash=trial_event.content_hash,
                trial_outcome=trial.outcome,
                research_result_hash=result_hash,
                export_audit_hash=cast(str, built.export_audit_hash),
                validation_report_hash=validation_hash,
                validation_status=validation_report.run_status,
                validation_verdict=validation_report.verdict,
                validation_gates=tuple(
                    P14dqValidationGateEvidence(
                        gate_id=gate.gate_id,
                        severity=gate.severity,
                        verdict=gate.verdict,
                        reason_code=gate.reason_code,
                    )
                    for gate in validation_report.gates
                ),
            )
        )

    report_dirs = tuple((tmp_path / "selection-reports").glob("sha256-*"))
    assert len(report_dirs) == 1
    selection_report = verify_selection_report_artifact(report_dirs[0])
    assert selection_report.run_status is RunStatus.FAILED
    assert selection_report.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert selection_report.reason_code is ReasonCode.SOURCE_INCOMPLETE
    assert selection_report.selected_candidate_hash is None
    assert selection_report.scores == ()
    assert tuple(item.kind for item in selection_report.candidate_dispositions) == (
        CandidateDispositionKind.NONPASS_VALIDATION,
        CandidateDispositionKind.NONPASS_VALIDATION,
    )

    frozen = tuple(evaluations)
    assert all(item.admissible_research_rejection() for item in frozen)
    assert runner._verify_natural_selection_outcome(selection_report, frozen) == (0, False)

    final_ledger = cast(ResearchLedgerService, ledger).verify(
        cast(str, ledger_id), created_at=started_at + timedelta(days=1)
    )
    assert cast(CampaignSelectionService, selection).plan is not None
    assert cast(CampaignSelectionService, selection).calendar is not None
    evidence = P14dqCampaignEvidence.model_validate(
        {
            "campaign_hash": cast(ResearchCampaignSpec, campaign).content_hash,
            "family_hash": P14DQ_FAMILY_HASH,
            "budget_hash": cast(ResearchBudgetSpec, budget).content_hash,
            "candidate_manifest_hash": P14DQ_CANDIDATE_MANIFEST_HASH,
            "candidate_hashes": P14DQ_CANDIDATE_HASHES,
            "context_pack_hashes": tuple(
                cast(object, item).request.context_pack.content_hash for item in exchanges
            ),
            "agent_request_hashes": tuple(
                cast(object, item).request.content_hash for item in exchanges
            ),
            "agent_proposal_hashes": tuple(
                cast(object, item).response.proposal_hash for item in exchanges
            ),
            "execution_request_hashes": tuple(item.request.content_hash for item in receipts),
            "execution_identities": tuple(item.request.execution_identity for item in receipts),
            "evaluations": frozen,
            "selection_plan_hash": cast(CampaignSelectionService, selection).plan.content_hash,
            "selection_calendar_hash": cast(
                CampaignSelectionService, selection
            ).calendar.content_hash,
            "selection_calendar_session_count": len(dq_calendar),
            "selection_calendar_first_date": dq_calendar[0],
            "selection_calendar_last_date": dq_calendar[-1],
            "selection_report_hash": selection_report.report_hash,
            "selection_status": selection_report.run_status,
            "selection_verdict": selection_report.verdict.value,
            "selection_reason_code": selection_report.reason_code,
            "eligible_candidate_count": 0,
            "selection_performed": False,
            "selected_candidate_hash": None,
            "campaign_trial_hashes": tuple(item.content_hash for item in trial_events),
            "campaign_event_hashes": tuple(item.content_hash for item in events),
            "final_campaign_event_hash": events[-1].content_hash,
            "final_ledger_snapshot_hash": report.final_ledger_snapshot_hash,
            "ledger_principal_hash": runner.p14d._ledger_principal_hash(final_ledger),
            "autonomous_loop_report_hash": report.content_hash,
        }
    )
    assert evidence.eligible_candidate_count == 0
    assert evidence.selection_performed is False
    assert evidence.selection_verdict == "NOT_EVALUATED"
    assert evidence.selection_status is RunStatus.FAILED
    assert evidence.selection_reason_code is ReasonCode.SOURCE_INCOMPLETE

    # The very same real evidence fails closed for every non-admissible rejection.
    genuine_gates = frozen[0].validation_gates
    hard_gates = tuple(
        P14dqValidationGateEvidence(
            gate_id=gate.gate_id,
            severity=gate.severity,
            verdict=(
                ValidationVerdict.REJECT
                if gate.gate_id is ValidationGateId.G2_PIT_LINEAGE
                else ValidationVerdict.PASS
            ),
            reason_code=(
                ReasonCode.LOOK_AHEAD if gate.gate_id is ValidationGateId.G2_PIT_LINEAGE else None
            ),
        )
        for gate in genuine_gates
    )
    hard_evaluations = tuple(
        _revalidated(item, hard_gates, TrialOutcome.HARD_REJECT) for item in frozen
    )
    assert not all(item.admissible_research_rejection() for item in hard_evaluations)
    with pytest.raises(runner.QualificationError, match="zero-eligible"):
        runner._verify_natural_selection_outcome(selection_report, hard_evaluations)

    integrity_gates = tuple(
        P14dqValidationGateEvidence(
            gate_id=gate.gate_id,
            severity=gate.severity,
            verdict=gate.verdict,
            reason_code=(
                ReasonCode.ARTIFACT_CORRUPTED
                if gate.gate_id is ValidationGateId.G5_OUT_OF_SAMPLE
                else gate.reason_code
            ),
        )
        for gate in genuine_gates
    )
    integrity_evaluations = tuple(
        _revalidated(item, integrity_gates, TrialOutcome.SOFT_REJECT) for item in frozen
    )
    assert not all(item.admissible_research_rejection() for item in integrity_evaluations)
    with pytest.raises(runner.QualificationError, match="zero-eligible"):
        runner._verify_natural_selection_outcome(selection_report, integrity_evaluations)

    with pytest.raises(ValidationError, match="complete frozen Validation gate set"):
        _revalidated(frozen[0], genuine_gates[:-1], TrialOutcome.SOFT_REJECT)
