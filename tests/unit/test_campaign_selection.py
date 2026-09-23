from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import pytest
from typer.testing import CliRunner

import quantos.application.campaign_selection as selection_module
import quantos.application.campaigns as campaigns_module
from quantos.application import (
    CampaignGovernanceError,
    CampaignSelectionError,
    CampaignSelectionService,
    ResearchCampaignGovernor,
    enumerate_research_family,
)
from quantos.application.campaign_selection import (
    _bootstrap_exceedances,
    _report_from_payload,
    publish_selection_plan,
    verify_selection_plan_artifact,
)
from quantos.application.enumeration import build_candidate_duplicate_evidence
from quantos.application.specs import resolve_experiment
from quantos.cli import app
from quantos.config import load_yaml_contract
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.campaign import (
    CampaignStoppingRule,
    CampaignTrial,
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
    CampaignSelectionEventType,
    CampaignSelectionVerdict,
    CandidateDispositionKind,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.enumeration import (
    CandidateEnumerationManifest,
    ResearchFactorTemplateNode,
    ResearchFactorTemplateSpec,
    ResearchTemplateParameterSlot,
)
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
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.research.qlib import ResearchResultArtifactBuilder
from quantos.research.qlib import result as result_module

ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _trading_dates() -> tuple[date, ...]:
    current = date(2021, 1, 4)
    dates: list[date] = []
    while len(dates) < 40:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return tuple(dates)


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="campaign-delta-template",
        expression_schema_version="safe-qlib-expression/v2",
        nodes=(
            ResearchFactorTemplateNode(
                node_id="price", operator="field", field_name="adjusted_close"
            ),
            ResearchFactorTemplateNode(node_id="factor", operator="delta", inputs=("price",)),
        ),
        output_node_id="factor",
        parameter_slots=(
            ResearchTemplateParameterSlot(name="window", node_id="factor", field="window"),
        ),
    )


def _family(template: ResearchFactorTemplateSpec) -> ResearchFamilySpec:
    return ResearchFamilySpec(
        family_id="selection-family",
        research_question="Does the bounded delta family have positive validation Rank IC?",
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted(("delta", "field"))),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )


def _write_qlib_view(root: Path, dates: tuple[date, ...]) -> QlibViewManifest:
    view_path = root / "view-working"
    (view_path / "calendars").mkdir(parents=True)
    calendar_bytes = "\n".join(item.isoformat() for item in dates).encode("utf-8") + b"\n"
    (view_path / "calendars" / "day.txt").write_bytes(calendar_bytes)
    manifest = QlibViewManifest.create(
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
                sha256=__import__("hashlib").sha256(calendar_bytes).hexdigest(),
                size_bytes=len(calendar_bytes),
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
    destination = root / f"sha256-{manifest.view_hash}"
    view_path.rename(destination)
    (destination / "manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="python"))
    )
    return manifest


def _campaign_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    weak_rank_ic: bool = False,
) -> tuple[
    ResearchCampaignGovernor,
    ResearchCampaignSpec,
    ResearchBudgetSpec,
    ResearchFamilySpec,
    ResearchFactorTemplateSpec,
    object,
    tuple[object, ...],
    tuple[date, ...],
    CampaignSelectionService,
    tuple[object, ...],
    dict[str, object],
]:
    dates = _trading_dates()
    view = _write_qlib_view(tmp_path, dates)
    template = _template()
    family = _family(template)
    manifest = enumerate_research_family(family, template)
    budget = ResearchBudgetSpec(
        budget_id="selection-budget",
        max_trials=4,
        max_distinct_candidates=2,
        max_agent_runs=4,
        max_executions=4,
        max_validation_rounds=4,
        max_compute_seconds=10_000,
    )
    campaign = ResearchCampaignSpec(
        campaign_id="selection-campaign",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=("3" * 64,),
        ledger_snapshot_hash="a" * 64,
        snapshot_hash="4" * 64,
        qlib_view_hash=view.view_hash,
        development=ResearchSegment(start=date(2020, 1, 1), end=date(2020, 12, 31)),
        validation=ResearchSegment(start=dates[0], end=dates[-1]),
        sealed_confirmation=ResearchSegment(start=date(2022, 1, 1), end=date(2022, 12, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    multiple_policy = MultipleTestingPolicySpec(seed="b" * 64)
    selection_policy = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple_policy.content_hash,
        direction="POSITIVE",
    )
    research_policy = load_yaml_contract(ROOT / "configs/research/policy_v1.yaml", ResearchPolicy)
    result_root = tmp_path / "research-results"
    result_root.mkdir()
    resolved_by_signal: dict[str, str] = {}
    monkeypatch.setattr(
        result_module,
        "verify_signal_artifact",
        lambda path: SimpleNamespace(
            resolved_experiment_hash=resolved_by_signal[str(path)], artifact_hash="2" * 64
        ),
    )

    results: dict[str, object] = {}
    for candidate_index, candidate in enumerate(manifest.candidates):
        strategy = StrategyAuthoringSpec(
            universe_index="000300.SH",
            top_k=50,
            input_lag_trading_days=candidate.expression.input_lag_trading_days,
        )
        authoring = ExperimentAuthoringSpec(
            experiment_id=f"selection-candidate-{candidate_index}",
            evaluation_start=dates[0],
            evaluation_end=dates[-1],
            expression=candidate.expression,
            strategy=strategy,
        )
        resolved = resolve_experiment(
            authoring,
            snapshot_hash=campaign.snapshot_hash,
            qlib_view_hash=campaign.qlib_view_hash,
            qlib_version="0.9.7",
            qlib_view_spec_hash=view.view_spec_hash,
            pit_audit_evidence_hash="c" * 64,
            research_policy_hash=research_policy.content_hash,
            validation_policy_hash="d" * 64,
            cost_policy_hash="e" * 64,
            backtest_policy_hash="f" * 64,
            code_commit_hash="0" * 40,
            lockfile_hash="1" * 64,
        )
        native = tmp_path / f"native-{candidate_index}"
        (native / "sig_analysis").mkdir(parents=True)
        index = pd.MultiIndex.from_tuples(
            [("SH600000", pd.Timestamp(dates[0]))], names=("instrument", "datetime")
        )
        pd.DataFrame({"score": [0.2]}, index=index).to_pickle(native / "pred.pkl")
        pd.DataFrame({"LABEL0": [0.1]}, index=index).to_pickle(native / "label.pkl")
        pd.Series([0.1 + candidate_index], index=[pd.Timestamp(dates[0])]).to_pickle(
            native / "sig_analysis" / "ic.pkl"
        )
        if weak_rank_ic:
            rank_ic_values = tuple(0.1 if position % 2 else -0.1 for position in range(40))
        elif candidate_index == 0:
            rank_ic_values = tuple(
                0.45 + ((position * 17) % 41 - 20) / 1000 for position in range(40)
            )
        else:
            rank_ic_values = tuple(
                -0.3 + ((position * 19) % 37 - 18) / 1000 for position in range(40)
            )
        pd.Series(
            rank_ic_values, index=pd.to_datetime([item.isoformat() for item in dates])
        ).to_pickle(native / "sig_analysis" / "ric.pkl")
        (native / "metrics.json").write_bytes(
            canonical_json_bytes({"IC": 0.1, "ICIR": 1.0, "Rank IC": 0.2, "Rank ICIR": 2.0})
        )
        signal_path = tmp_path / f"signal-{candidate_index}"
        resolved_by_signal[str(signal_path)] = resolved.content_hash
        result = ResearchResultArtifactBuilder().build(
            resolved,
            research_policy,
            signal_path,
            native,
            result_root,
            qlib_run_id=f"selection-run-{candidate_index}",
            label_expression="Ref($close,-1)/$close-1",
            created_at=NOW,
        )
        results[candidate.content_hash] = result

    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple_policy,
        selection_policy,
        tmp_path / f"sha256-{view.view_hash}",
        (result_root,),
    )
    governor = ResearchCampaignGovernor(family, template, manifest)
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("90000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    plan_event, _ = service.freeze_plan(
        governor,
        (activation,),
        event_id=UUID("90000000-0000-0000-0000-000000000002"),
        occurred_at=NOW + timedelta(seconds=1),
        artifact_root=tmp_path / "plans",
    )
    events: tuple[object, ...] = (activation, plan_event)
    for candidate_index, candidate in enumerate(manifest.candidates):
        artifact = results[candidate.content_hash]
        trial = CampaignTrial(
            trial_id=f"validation-{candidate_index}",
            idempotency_key=f"{candidate_index + 1:x}".zfill(64),
            proposal_hash=f"{candidate_index + 3:x}".zfill(64),
            candidate_hash=candidate.content_hash,
            segment=CampaignSegment.VALIDATION,
            outcome=TrialOutcome.PASS,
            agent_run_hash="a" * 64,
            execution_requested=True,
            compute_seconds=1,
            evidence_hashes=(artifact.manifest.artifact_hash,),
        )
        event = governor.record_selection_trial(
            campaign,
            budget,
            events,
            trial,
            service.plan,
            event_id=UUID(f"90000000-0000-0000-0000-{candidate_index + 3:012d}"),
            occurred_at=NOW + timedelta(seconds=candidate_index + 2),
        )
        events += (event,)

    return (
        governor,
        campaign,
        budget,
        family,
        template,
        manifest,
        tuple(results.values()),
        dates,
        service,
        events,
        results,
    )


def test_selection_report_is_golden_hash_bound_and_byte_exact_across_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        _governor,
        _campaign,
        _budget,
        _family,
        _template,
        manifest,
        result_artifacts,
        _dates,
        service,
        events,
        _results,
    ) = _campaign_inputs(tmp_path / "inputs", monkeypatch)
    first, first_path = service.publish_report(events, tmp_path / "root-a" / "reports")

    copied_results = tmp_path / "root-b" / "results"
    copied_results.mkdir(parents=True)
    for result in result_artifacts:
        source = result.path
        shutil.copytree(source, copied_results / source.name)
    copied_views = tmp_path / "root-b" / "views"
    copied_views.mkdir()
    shutil.copytree(
        service.qlib_view_path,
        copied_views / service.qlib_view_path.name,
    )
    service_b = CampaignSelectionService(
        service.campaign,
        service.family,
        service.budget,
        service.template,
        service.manifest,
        service.multiple_testing_policy,
        service.selection_policy,
        copied_views / service.qlib_view_path.name,
        (copied_results,),
        plan=service.plan,
    )
    second, second_path = service_b.publish_report(events, tmp_path / "root-b" / "reports")

    assert first == second
    assert (first_path / "report.json").read_bytes() == (second_path / "report.json").read_bytes()
    assert first.report_hash == first.content_hash
    assert first.verdict is CampaignSelectionVerdict.SELECTED
    assert first.run_status is RunStatus.SUCCEEDED
    assert len(first.candidate_dispositions) == manifest.declared_candidate_count
    assert len(first.trial_bindings) == 2
    assert all(item.kind.value == "ELIGIBLE" for item in first.candidate_dispositions)
    assert sorted(item.raw_p_value for item in first.scores) == [0.0001, 1.0]
    assert sorted(item.adjusted_p_value for item in first.scores) == [0.0002, 1.0]
    assert first.selected_candidate_hash == next(
        item.candidate_hash for item in first.scores if item.raw_p_value == 0.0001
    )
    assert service_b.verify_report(second_path, events) == first


def test_holm_bootstrap_golden_counter_stream_value() -> None:
    policy = MultipleTestingPolicySpec(seed="b" * 64)
    values = tuple(0.025 + ((position * 17) % 41 - 20) / 100 for position in range(40))
    mean, exceedances = _bootstrap_exceedances(values, policy, "a" * 64)
    assert mean == pytest.approx(0.024)
    assert exceedances == 36


def test_exact_duplicate_remains_in_family_denominator_and_trial_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        _original_governor,
        campaign,
        budget,
        family,
        template,
        manifest,
        _result_artifacts,
        _dates,
        original_service,
        _original_events,
        results,
    ) = _campaign_inputs(tmp_path, monkeypatch)
    first_candidate, duplicate_source = manifest.candidates
    duplicate = duplicate_source.model_copy(
        update={
            "expression": first_candidate.expression,
            "exact_expression_hash": first_candidate.exact_expression_hash,
            "structural_expression_hash": first_candidate.structural_expression_hash,
        }
    )
    candidates = (first_candidate, duplicate)
    duplicate_manifest = CandidateEnumerationManifest.model_validate(
        {
            **manifest.model_dump(mode="python"),
            "candidates": candidates,
            "duplicate_evidence": build_candidate_duplicate_evidence(candidates),
        }
    )
    exact_group = next(
        item for item in duplicate_manifest.duplicate_evidence if item.kind.value == "EXACT"
    )
    representative = next(
        item
        for item in candidates
        if item.content_hash == exact_group.representative_candidate_hash
    )
    duplicate = next(
        item for item in candidates if item.content_hash in exact_group.duplicate_candidate_hashes
    )

    # P14b's present canonical enumerator cannot emit exact duplicates. Isolate the
    # P14c accounting semantics with a schema-valid duplicate-evidence manifest.
    monkeypatch.setattr(
        selection_module, "verify_candidate_enumeration_manifest", lambda *_args: None
    )
    monkeypatch.setattr(
        campaigns_module, "verify_candidate_enumeration_manifest", lambda *_args: None
    )
    governor = ResearchCampaignGovernor(family, template, duplicate_manifest)
    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        duplicate_manifest,
        original_service.multiple_testing_policy,
        original_service.selection_policy,
        original_service.qlib_view_path,
        original_service.research_results_roots,
    )
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("91000000-0000-0000-0000-000000000001"),
        occurred_at=NOW,
    )
    plan_event, _ = service.freeze_plan(
        governor,
        (activation,),
        event_id=UUID("91000000-0000-0000-0000-000000000002"),
        occurred_at=NOW + timedelta(seconds=1),
        artifact_root=tmp_path / "duplicate-plans",
    )
    events = (activation, plan_event)
    representative_result = results[first_candidate.content_hash]
    representative_trial = CampaignTrial(
        trial_id="duplicate-representative-validation",
        idempotency_key="a" * 64,
        proposal_hash="b" * 64,
        candidate_hash=representative.content_hash,
        segment=CampaignSegment.VALIDATION,
        outcome=TrialOutcome.PASS,
        execution_requested=True,
        compute_seconds=1,
        evidence_hashes=(representative_result.manifest.artifact_hash,),
    )
    representative_event = governor.record_selection_trial(
        campaign,
        budget,
        events,
        representative_trial,
        service.plan,
        event_id=UUID("91000000-0000-0000-0000-000000000003"),
        occurred_at=NOW + timedelta(seconds=2),
    )
    events += (representative_event,)
    duplicate_trial = CampaignTrial(
        trial_id="exact-duplicate-validation",
        idempotency_key="c" * 64,
        proposal_hash="d" * 64,
        candidate_hash=duplicate.content_hash,
        segment=CampaignSegment.VALIDATION,
        outcome=TrialOutcome.DUPLICATE_CANDIDATE,
        execution_requested=False,
        compute_seconds=0,
    )
    duplicate_event = governor.record_selection_trial(
        campaign,
        budget,
        events,
        duplicate_trial,
        service.plan,
        event_id=UUID("91000000-0000-0000-0000-000000000004"),
        occurred_at=NOW + timedelta(seconds=3),
    )
    report = service.build_report((*events, duplicate_event))

    duplicate_disposition = next(
        item
        for item in report.candidate_dispositions
        if item.candidate_hash == duplicate.content_hash
    )
    assert duplicate_disposition.kind.value == "EXACT_DUPLICATE"
    assert duplicate_event.content_hash in duplicate_disposition.trial_event_hashes
    assert len(report.trial_bindings) == 2
    assert [item.candidate_hash for item in report.scores] == [representative.content_hash]
    assert report.scores[0].raw_p_value == 0.0001
    assert report.scores[0].adjusted_p_value == 0.0002
    assert report.verdict is CampaignSelectionVerdict.SELECTED


@pytest.mark.parametrize("failure", ("calendar", "rank_ic"))
def test_invalid_calendar_or_missing_rank_ic_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    (*_, service, events, results) = _campaign_inputs(tmp_path, monkeypatch)
    if failure == "calendar":
        calendar_path = service.qlib_view_path / "calendars" / "day.txt"
        calendar_path.write_bytes(calendar_path.read_bytes() + b"\n")
    else:
        result = results[next(iter(results))]
        (result.path / "rank-ic-series.json").unlink()

    report = service.build_report(events)
    assert report.run_status is RunStatus.FAILED
    assert report.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert report.scores == ()
    assert report.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_complete_valid_run_without_significance_is_no_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch, weak_rank_ic=True)
    report = service.build_report(events)
    assert report.run_status is RunStatus.SUCCEEDED
    assert report.verdict is CampaignSelectionVerdict.NO_SELECTION
    assert report.selected_candidate_hash is None
    assert len(report.scores) == 2
    assert all(item.adjusted_p_value > 0.05 for item in report.scores)


def test_campaign_selection_cli_report_and_verify_recompute_from_explicit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    inputs = tmp_path / "cli-inputs"
    inputs.mkdir()
    contracts = {
        "campaign.json": service.campaign,
        "family.json": service.family,
        "budget.json": service.budget,
        "template.json": service.template,
        "manifest.json": service.manifest,
        "multiple-testing-policy.json": service.multiple_testing_policy,
        "selection-policy.json": service.selection_policy,
    }
    paths: dict[str, Path] = {}
    for name, contract in contracts.items():
        path = inputs / name
        path.write_bytes(contract.canonical_bytes())
        paths[name] = path
    event_chain = inputs / "event-chain.json"
    event_chain.write_bytes(canonical_json_bytes(events))
    results_root = service.research_results_roots[0]
    common = [
        str(paths["campaign.json"]),
        str(paths["family.json"]),
        str(paths["budget.json"]),
        str(paths["template.json"]),
        str(paths["manifest.json"]),
        str(paths["multiple-testing-policy.json"]),
        str(paths["selection-policy.json"]),
        str(event_chain),
        str(service.qlib_view_path),
        str(results_root),
    ]
    report_root = tmp_path / "cli-reports"
    runner = CliRunner()
    built = runner.invoke(
        app,
        ["campaign", "selection-report", *common, "--output-root", str(report_root)],
    )
    assert built.exit_code == 0, built.output
    result_payload = __import__("json").loads(built.stdout)
    report_path = Path(result_payload["artifact_path"])
    assert result_payload["verdict"] == "SELECTED"

    verified = runner.invoke(
        app,
        ["campaign", "selection-verify", str(report_path), *common],
    )
    assert verified.exit_code == 0, verified.output
    assert __import__("json").loads(verified.stdout)["status"] == "PASS"


def test_legacy_unplanned_prefix_and_repeated_validation_fail_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        governor,
        campaign,
        budget,
        _family,
        _template,
        manifest,
        _result_artifacts,
        _dates,
        service,
        events,
        results,
    ) = _campaign_inputs(tmp_path, monkeypatch)
    trial_event = events[-1]
    assert isinstance(trial_event, ResearchCampaignEvent)
    first_trial = trial_event.trial
    assert first_trial is not None

    legacy_events = (events[0],)
    legacy_trial = first_trial.model_copy(
        update={"trial_id": "legacy-validation", "idempotency_key": "f" * 64}
    )
    legacy_event = governor.record_trial(
        campaign,
        budget,
        legacy_events,
        legacy_trial,
        event_id=UUID("90000000-0000-0000-0000-000000000099"),
        occurred_at=NOW + timedelta(seconds=1),
    )
    legacy_report = service.build_report((events[0], legacy_event))
    assert legacy_report.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert legacy_report.reason_code is ReasonCode.EVENT_CHAIN_INVALID

    candidate_hash = first_trial.candidate_hash
    candidate_result = results[candidate_hash]
    repeated_trial = first_trial.model_copy(
        update={"trial_id": "validation-repeat", "idempotency_key": "e" * 64}
    )
    repeated_event = governor.record_selection_trial(
        campaign,
        budget,
        events,
        repeated_trial,
        service.plan,
        event_id=UUID("90000000-0000-0000-0000-000000000100"),
        occurred_at=NOW + timedelta(seconds=10),
    )
    repeated_report = service.build_report((*events, repeated_event))
    assert repeated_report.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert repeated_report.run_status is RunStatus.FAILED
    assert repeated_report.reason_code is ReasonCode.ARTIFACT_CORRUPTED
    assert len(repeated_report.candidate_dispositions) == manifest.declared_candidate_count
    assert candidate_result.manifest.artifact_hash == first_trial.evidence_hashes[0]


def test_selection_freeze_verifies_artifact_and_oos_is_bound_to_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        governor,
        campaign,
        budget,
        _family,
        _template,
        manifest,
        _result_artifacts,
        _dates,
        service,
        events,
        _results,
    ) = _campaign_inputs(tmp_path, monkeypatch)
    report, report_path = service.publish_report(events, tmp_path / "reports")
    assert report.selected_candidate_hash is not None
    with pytest.raises(CampaignGovernanceError) as direct_freeze:
        governor.freeze_selection(
            campaign,
            budget,
            events,
            report,
            event_id=UUID("90000000-0000-0000-0000-000000000020"),
            occurred_at=NOW + timedelta(seconds=20),
        )
    assert direct_freeze.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION

    selection_event = service.freeze_selection(
        governor,
        events,
        report_path,
        event_id=UUID("90000000-0000-0000-0000-000000000021"),
        occurred_at=NOW + timedelta(seconds=20),
    )
    assert selection_event.event_type is CampaignSelectionEventType.SELECTION_FROZEN

    selected_trial = CampaignTrial(
        trial_id="sealed-selected",
        idempotency_key="2" * 64,
        proposal_hash="3" * 64,
        candidate_hash=report.selected_candidate_hash,
        segment=CampaignSegment.SEALED_CONFIRMATION,
        outcome=TrialOutcome.PASS,
        execution_requested=True,
        compute_seconds=1,
    )
    frozen_events = (*events, selection_event)
    with pytest.raises(CampaignGovernanceError) as direct_oos:
        governor.access_sealed_confirmation(
            campaign,
            budget,
            frozen_events,
            selected_trial,
            event_id=UUID("90000000-0000-0000-0000-000000000022"),
            occurred_at=NOW + timedelta(seconds=21),
        )
    assert direct_oos.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION

    oos_event = service.access_sealed_confirmation(
        governor,
        frozen_events,
        selected_trial,
        report_path,
        event_id=UUID("90000000-0000-0000-0000-000000000023"),
        occurred_at=NOW + timedelta(seconds=21),
    )
    snapshot = governor.project(campaign, budget, (*frozen_events, oos_event))
    assert snapshot.sealed_confirmation_accessed

    wrong_candidate = next(
        item.content_hash
        for item in manifest.candidates
        if item.content_hash != report.selected_candidate_hash
    )
    wrong_trial = selected_trial.model_copy(
        update={
            "trial_id": "sealed-wrong",
            "idempotency_key": "4" * 64,
            "candidate_hash": wrong_candidate,
        }
    )
    with pytest.raises(CampaignSelectionError) as wrong_oos:
        service.access_sealed_confirmation(
            governor,
            frozen_events,
            wrong_trial,
            report_path,
            event_id=UUID("90000000-0000-0000-0000-000000000024"),
            occurred_at=NOW + timedelta(seconds=22),
        )
    assert wrong_oos.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION


def test_plan_freeze_requires_verifying_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        governor,
        campaign,
        budget,
        family,
        _template,
        manifest,
        _result_artifacts,
        _dates,
        service,
        events,
        _results,
    ) = _campaign_inputs(tmp_path, monkeypatch)
    assert service.plan is not None
    with pytest.raises(CampaignGovernanceError) as direct_plan:
        governor.freeze_selection_plan(
            campaign,
            family,
            budget,
            manifest,
            events[:1],
            service.plan,
            event_id=UUID("90000000-0000-0000-0000-000000000025"),
            occurred_at=NOW + timedelta(seconds=1),
        )
    assert direct_plan.value.reason_code is ReasonCode.OOS_POLICY_VIOLATION


def test_plan_rejects_invalid_frozen_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, _events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    assert service.plan is not None
    cases = (
        {"campaign": service.campaign.model_copy(update={"family_hash": "f" * 64})},
        {"campaign": service.campaign.model_copy(update={"budget_hash": "f" * 64})},
        {"campaign": service.campaign.model_copy(update={"qlib_view_hash": "f" * 64})},
        {
            "campaign": service.campaign.model_copy(
                update={
                    "validation": ResearchSegment(start=date(2021, 7, 1), end=date(2021, 7, 30))
                }
            )
        },
        {"manifest": service.manifest.model_copy(update={"declared_candidate_count": 3})},
        {
            "selection_policy": SelectionPolicySpec(
                multiple_testing_policy_hash="f" * 64, direction="POSITIVE"
            )
        },
        {"plan": service.plan.model_copy(update={"selection_policy_hash": "f" * 64})},
        {"qlib_view_path": tmp_path / "missing-view"},
    )
    base = {
        "campaign": service.campaign,
        "family": service.family,
        "budget": service.budget,
        "template": service.template,
        "manifest": service.manifest,
        "multiple_testing_policy": service.multiple_testing_policy,
        "selection_policy": service.selection_policy,
        "qlib_view_path": service.qlib_view_path,
        "research_results_roots": service.research_results_roots,
        "plan": service.plan,
    }
    for changes in cases:
        invalid = CampaignSelectionService(**{**base, **changes})
        with pytest.raises(CampaignSelectionError):
            invalid.build_plan()


def test_calendar_parser_rejects_malformed_verified_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolate parser failures after the normal view verifier has accepted the fixture."""

    (*_, service, _events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    manifest = selection_module.verify_qlib_view(service.qlib_view_path)
    calendar_path = service.qlib_view_path / "calendars" / "day.txt"
    original_bytes = calendar_path.read_bytes()
    base = (
        service.campaign,
        service.family,
        service.budget,
        service.template,
        service.manifest,
        service.multiple_testing_policy,
        service.selection_policy,
        service.qlib_view_path,
        service.research_results_roots,
    )

    monkeypatch.setattr(selection_module, "verify_qlib_view", lambda _path: manifest)
    calendar_path.write_text("not-a-date\n", encoding="utf-8")
    with pytest.raises(CampaignSelectionError) as malformed:
        CampaignSelectionService(*base).build_plan()
    assert malformed.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    calendar_path.write_bytes(original_bytes + original_bytes.splitlines()[0] + b"\n")
    with pytest.raises(CampaignSelectionError) as duplicate:
        CampaignSelectionService(*base).build_plan()
    assert duplicate.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    calendar_path.write_bytes(original_bytes)
    missing_file_manifest = manifest.model_copy(update={"files": ()})
    monkeypatch.setattr(selection_module, "verify_qlib_view", lambda _path: missing_file_manifest)
    with pytest.raises(CampaignSelectionError) as absent:
        CampaignSelectionService(*base).build_plan()
    assert absent.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_nonpass_and_missing_result_are_accounted_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    last_event = events[-1]
    assert isinstance(last_event, ResearchCampaignEvent)
    assert last_event.trial is not None
    rejected_trial = last_event.trial.model_copy(
        update={
            "outcome": TrialOutcome.PIT_REJECT,
            "execution_requested": False,
            "evidence_hashes": (),
        }
    )
    rejected_event = last_event.model_copy(update={"trial": rejected_trial})
    rejection_report = service.build_report((*events[:-1], rejected_event))
    assert rejection_report.run_status is RunStatus.SUCCEEDED
    assert rejection_report.verdict is CampaignSelectionVerdict.SELECTED
    rejected_disposition = next(
        item
        for item in rejection_report.candidate_dispositions
        if item.candidate_hash == rejected_trial.candidate_hash
    )
    assert rejected_disposition.kind is CandidateDispositionKind.NONPASS_VALIDATION
    assert len(rejection_report.trial_bindings) == 2

    missing_trial = last_event.trial.model_copy(update={"evidence_hashes": ()})
    missing_event = last_event.model_copy(update={"trial": missing_trial})
    missing_report = service.build_report((*events[:-1], missing_event))
    assert missing_report.run_status is RunStatus.FAILED
    assert missing_report.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert missing_report.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    first_event = events[-2]
    assert isinstance(first_event, ResearchCampaignEvent)
    assert first_event.trial is not None
    reused_trial = last_event.trial.model_copy(
        update={"evidence_hashes": first_event.trial.evidence_hashes}
    )
    reused_event = last_event.model_copy(update={"trial": reused_trial})
    reused_report = service.build_report((*events[:-1], reused_event))
    assert reused_report.verdict is CampaignSelectionVerdict.NOT_EVALUATED


def test_empty_prefix_and_zero_eligible_candidates_do_not_select(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    with pytest.raises(CampaignSelectionError) as absent:
        service.build_report(())
    assert absent.value.reason_code is ReasonCode.EVENT_CHAIN_INVALID
    zero_eligible = service.build_report(events[:2])
    assert zero_eligible.run_status is RunStatus.FAILED
    assert zero_eligible.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert all(
        item.kind is CandidateDispositionKind.NOT_RUN_MANUAL_CLOSE
        for item in zero_eligible.candidate_dispositions
    )


def test_rank_ic_value_failures_reject_entire_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    first_event = events[-2]
    assert isinstance(first_event, ResearchCampaignEvent)
    assert first_event.trial is not None
    target_hash = first_event.trial.evidence_hashes[0]
    original_loader = service._load_verified_result
    original_rows = original_loader(target_hash).rank_ic
    invalid_rows = (
        original_rows[:-1],
        (original_rows[0].model_copy(update={"value": 2.0}), *original_rows[1:]),
        (original_rows[0].model_copy(update={"value": float("nan")}), *original_rows[1:]),
        tuple(item.model_copy(update={"value": 0.25}) for item in original_rows),
    )
    for rows in invalid_rows:

        def load_with_bad_series(
            result_hash: str, *, replacement: tuple[object, ...] = rows
        ) -> object:
            verified = original_loader(result_hash)
            return (
                replace(verified, rank_ic=replacement) if result_hash == target_hash else verified
            )

        monkeypatch.setattr(service, "_load_verified_result", load_with_bad_series)
        report = service.build_report(events)
        assert report.run_status is RunStatus.FAILED
        assert report.verdict is CampaignSelectionVerdict.NOT_EVALUATED


def test_published_plan_and_report_reject_recomputed_score_forgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    assert service.plan is not None
    plan_root = tmp_path / "published-plans"
    plan_path = publish_selection_plan(service.plan, plan_root)
    assert publish_selection_plan(service.plan, plan_root) == plan_path
    assert verify_selection_plan_artifact(plan_path) == service.plan
    (plan_path / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(CampaignSelectionError):
        verify_selection_plan_artifact(plan_path)

    report_root = tmp_path / "published-reports"
    report, _report_path = service.publish_report(events, report_root)
    assert service.publish_report(events, report_root)[0] == report
    payload = report.model_dump(mode="python", exclude={"report_hash", "schema_version"})
    scores = list(payload["scores"])
    scores[0] = {**scores[0], "raw_p_value": 0.0002}
    payload["scores"] = tuple(scores)
    forged = _report_from_payload(**payload)
    forged_path = report_root / f"sha256-{forged.report_hash}"
    forged_path.mkdir()
    (forged_path / "report.json").write_bytes(
        canonical_json_bytes(forged.model_dump(mode="python"))
    )
    with pytest.raises(CampaignSelectionError):
        service.verify_report(forged_path, events)


def test_selection_artifact_rejects_modified_report_and_extra_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (*_, service, events, _results) = _campaign_inputs(tmp_path, monkeypatch)
    _report, path = service.publish_report(events, tmp_path / "reports")
    (path / "extra.json").write_bytes(b"{}")
    with pytest.raises(CampaignSelectionError):
        service.verify_report(path, events)

    (path / "extra.json").unlink()
    report_file = path / "report.json"
    report_file.write_bytes(report_file.read_bytes() + b" ")
    with pytest.raises(CampaignSelectionError):
        service.verify_report(path, events)
