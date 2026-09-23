#!/usr/bin/env python3
"""Qualify frozen P14c campaign selection from a clean commit and two fresh roots."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import tempfile
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError
from qlib.workflow.record_temp import SigAnaRecord  # pyright: ignore[reportMissingTypeStubs]

from quantos.application import (
    CampaignGovernanceError,
    CampaignSelectionError,
    CampaignSelectionService,
    ResearchCampaignGovernor,
    capture_code_provenance,
    capture_runtime_fingerprint,
    enumerate_research_family,
    resolve_experiment,
)
from quantos.application.campaign_selection import (
    verify_selection_plan_artifact,
    verify_selection_report_artifact,
)
from quantos.application.campaigns import CampaignChainEvent
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
    sha256_file,
)
from quantos.config import load_yaml_contract
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
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
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionPlan,
    CampaignSelectionReport,
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
from quantos.contracts.p14c_qualification import (
    P14C_CANONICAL_CASES,
    P14C_LIMITATIONS,
    P14C_NEGATIVE_CASES,
    P14cCanonicalCaseResult,
    P14cNamedHash,
    P14cNegativeCaseEvidence,
    P14cQualificationFile,
    P14cQualificationReport,
    P14cRootCaseEvidence,
    P14cRootEvidence,
    p14c_principal_hash_summary,
)
from quantos.contracts.pit import (
    OperatorDelayPolicy,
    PITGateId,
    PITGateResult,
    SafeQlibOperator,
)
from quantos.contracts.provenance import CodeProvenance, RuntimeFingerprint
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
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceBundle,
    PITCrossSectionEvidenceCollection,
    PITMembershipSetEvidence,
    PITSourceSetEvidence,
    required_expression_observations,
)
from quantos.contracts.research_result import (
    ResearchResultArtifactFile,
    ResearchResultManifest,
)
from quantos.contracts.signal import (
    SignalArtifactFile,
    SignalArtifactManifest,
    SignalRow,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.temporal import (
    AvailabilityEvidenceLevel,
    DecisionSchedule,
    TemporalMetadata,
)
from quantos.data.qlib_view import verify_qlib_view
from quantos.research.qlib import (
    QlibResearchError,
    ResearchResultArtifactBuilder,
    verify_research_result,
)
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.pit_evidence import pit_transform_lineage_hash
from quantos.research.qlib.signal import (
    signal_content_hash,
    verify_signal_artifact,
    write_signal_table,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("docs/p14c-selection-contract.md")
RESEARCH_POLICY_PATH = Path("configs/research/policy_v1.yaml")
OCCURRED_AT = datetime(2026, 9, 11, tzinfo=UTC)
SHANGHAI = ZoneInfo("Asia/Shanghai")
LIMITATION_CODES = P14C_LIMITATIONS


class QualificationError(RuntimeError):
    """P14c qualification did not satisfy a frozen engineering gate."""


@dataclass(frozen=True)
class _CaseInputs:
    case_id: str
    campaign: ResearchCampaignSpec
    family: ResearchFamilySpec
    budget: ResearchBudgetSpec
    template: ResearchFactorTemplateSpec
    manifest: CandidateEnumerationManifest
    multiple_testing_policy: MultipleTestingPolicySpec
    selection_policy: SelectionPolicySpec
    research_policy: ResearchPolicy
    view_path: Path
    results_root: Path
    plan_path: Path
    report_path: Path
    events_path: Path
    report_events_path: Path
    events: tuple[CampaignChainEvent, ...]
    report_events: tuple[CampaignChainEvent, ...]
    report: CampaignSelectionReport
    plan: CampaignSelectionPlan
    governor: ResearchCampaignGovernor
    service: CampaignSelectionService


class _NativeRecorder:
    def __init__(self, prediction: pd.DataFrame, label: pd.DataFrame) -> None:
        self.objects: dict[str, object] = {"pred.pkl": prediction, "label.pkl": label}
        self.metrics: dict[str, float] = {}

    def load_object(self, path: str) -> object:
        return self.objects[path.rsplit("/", 1)[-1]]

    def log_metrics(self, **metrics: float) -> None:
        self.metrics.update(metrics)


def _trading_dates(count: int = 40) -> tuple[date, ...]:
    current = date(2021, 1, 4)
    result: list[date] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _template() -> ResearchFactorTemplateSpec:
    return ResearchFactorTemplateSpec(
        template_id="p14c-qualification-delta-template",
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
        family_id="p14c-qualification-family",
        research_question=(
            "Does a bounded synthetic factor family have positive validation Rank IC?"
        ),
        hypothesis_hash="1" * 64,
        factor_template_hash=template.content_hash,
        allowed_operators=tuple(sorted((SafeQlibOperator.DELTA, SafeQlibOperator.FIELD), key=str)),
        parameter_space=(ParameterDimension(name="window", values=(2, 3)),),
        declared_candidate_count=2,
    )


def _fixture_payload() -> dict[str, object]:
    return {
        "schema_version": "p14c-qualification-fixture/v1",
        "calendar": tuple(item.isoformat() for item in _trading_dates()),
        "candidate_rank_ic": {
            "SELECTED": (
                "Qlib SigAnaRecord Spearman correlation from cyclic rank shifts 9-11",
                "Qlib SigAnaRecord inverse cyclic rank shifts 9-11",
            ),
            "NO_SELECTION": "paired positive/negative Qlib Rank IC over 40 sessions",
            "FAILED_NOT_EVALUATED": "PASS validation trial has no ResearchResult binding",
        },
        "candidate_windows": (2, 3),
        "cross_section": {
            "instrument_count": 100,
            "instrument_ids": "SH600000 through SH600099",
            "score_rank": "instrument ordinal ascending",
            "label_rank": "rotate by 9 + ((session_index // 2) % 3), then optionally reverse",
            "selected_direction": "candidate 0 positive, candidate 1 reversed",
            "no_selection_direction": "even sessions positive, odd sessions reversed",
        },
        "method": {
            "alpha": 0.05,
            "bootstrap_replicates": 9999,
            "block_length": 5,
            "direction": "POSITIVE",
            "seed": "b" * 64,
        },
        "synthetic_only": True,
    }


def _synthetic_label_rank(
    case_id: str, candidate_index: int, session_index: int, instrument_rank: int, count: int
) -> int:
    """Build deterministic cross-sections whose Rank IC Qlib computes from source rows."""

    shift = 9 + ((session_index // 2) % 3)
    positive = session_index % 2 == 0 if case_id == "NO_SELECTION" else candidate_index == 0
    rotated_rank = (instrument_rank + shift) % count
    return rotated_rank if positive else count - 1 - rotated_rank


def _write_view(root: Path, dates: tuple[date, ...]) -> QlibViewManifest:
    work = root / "view-work"
    (work / "calendars").mkdir(parents=True)
    calendar_bytes = "\n".join(item.isoformat() for item in dates).encode("utf-8") + b"\n"
    (work / "calendars" / "day.txt").write_bytes(calendar_bytes)
    files = (
        QlibViewFile(
            logical_path="calendars/day.txt",
            sha256=sha256_bytes(calendar_bytes),
            size_bytes=len(calendar_bytes),
        ),
    )
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
        files=files,
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
        created_at=OCCURRED_AT,
    )
    destination = root / "views" / f"sha256-{manifest.view_hash}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    work.rename(destination)
    atomic_write_bytes(
        destination / "manifest.json", canonical_json_bytes(manifest.model_dump(mode="python"))
    )
    verify_qlib_view(destination)
    return manifest


def _temporal(event_time: datetime, available_at: datetime) -> TemporalMetadata:
    return TemporalMetadata(
        event_time=event_time,
        known_at=available_at,
        available_at=available_at,
        observed_at=available_at + timedelta(minutes=1),
        evidence_level=AvailabilityEvidenceLevel.DOCUMENTED_UPDATE_SCHEDULE,
        policy_id="p14c-qualification-synthetic-temporal/v1",
    )


def _publish_signal(
    resolved: object,
    root: Path,
    *,
    view_hash: str,
    session_date: date,
    code: CodeProvenance,
) -> Path:
    from quantos.contracts.research import ResolvedExperimentSpec

    assert isinstance(resolved, ResolvedExperimentSpec)
    signal_time = datetime.combine(session_date, datetime.min.time(), SHANGHAI).replace(
        hour=16, minute=0
    )
    available_at = signal_time - timedelta(minutes=30)
    decision_time = signal_time + timedelta(minutes=10)
    execution_time = decision_time + timedelta(days=1)
    schedule = DecisionSchedule(
        signal_time=signal_time,
        signal_available_at=signal_time + timedelta(minutes=1),
        decision_time=decision_time,
        execution_time=execution_time,
    )
    expression = resolved.expression
    prior_dates = tuple(item for item in _trading_dates() if item < session_date)
    required_observations = required_expression_observations(expression)
    source_window = prior_dates[-required_observations:]
    if len(source_window) != required_observations:
        raise QualificationError("synthetic PIT source window must precede signal time")
    source_available_at = datetime.combine(
        source_window[-1], datetime.min.time(), SHANGHAI
    ).replace(hour=15, minute=30)
    source_max = _temporal(
        datetime.combine(source_window[-1], datetime.min.time(), SHANGHAI).replace(hour=15),
        source_available_at,
    )
    membership_time = _temporal(
        datetime.combine(session_date, datetime.min.time(), SHANGHAI),
        decision_time - timedelta(minutes=5),
    )
    sources = (
        PITSourceSetEvidence(
            table_name="adjustment_factors",
            logical_field_name="adjusted_close",
            source_field_name="adjustment_factor",
            expected_row_count=required_observations,
            present_row_count=required_observations,
            missing_row_count=0,
            row_set_hash="a" * 64,
            maximum_temporal=source_max,
        ),
        PITSourceSetEvidence(
            table_name="bars",
            logical_field_name="adjusted_close",
            source_field_name="close",
            expected_row_count=required_observations,
            present_row_count=required_observations,
            missing_row_count=0,
            row_set_hash="b" * 64,
            maximum_temporal=source_max,
        ),
    )
    evidence = PITCrossSectionEvidenceCollection(
        snapshot_hash=resolved.snapshot_hash,
        qlib_view_hash=view_hash,
        expression_spec_hash=expression.content_hash,
        expression=expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="synthetic-delta-delay/v1", operator=SafeQlibOperator.DELTA
            ),
        ),
        universe_index=resolved.strategy.universe_index,
        bundles=(
            PITCrossSectionEvidenceBundle(
                snapshot_hash=resolved.snapshot_hash,
                expression_spec_hash=expression.content_hash,
                universe_index=resolved.strategy.universe_index,
                schedule=schedule,
                required_observations=required_observations,
                source_window=source_window,
                members=("600000.SH",),
                source_sets=sources,
                membership_set=PITMembershipSetEvidence(
                    row_count=1, row_set_hash="c" * 64, maximum_temporal=membership_time
                ),
                output_temporal=_temporal(
                    datetime.combine(session_date, datetime.min.time(), SHANGHAI), available_at
                ),
                gates=tuple(
                    PITGateResult(
                        gate_id=gate,
                        verdict=ValidationVerdict.PASS,
                        detail="synthetic frozen input",
                    )
                    for gate in PITGateId
                ),
            ),
        ),
    )
    if evidence.content_hash != resolved.pit_audit_evidence_hash:
        resolved = resolved.model_copy(update={"pit_audit_evidence_hash": evidence.content_hash})
    translation = translate_safe_expression(expression)
    row = SignalRow(
        instrument_id="600000.SH",
        signal_time=signal_time,
        decision_time=decision_time,
        available_at=available_at,
        score=0.25,
        score_valid=True,
        tradable=True,
    )
    destination_root = root / "signals"
    destination_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14c-signal-", dir=destination_root) as temporary:
        staging = Path(temporary) / "signal"
        staging.mkdir()
        atomic_write_bytes(staging / "resolved-experiment.json", resolved.canonical_bytes())
        atomic_write_bytes(staging / "expression-translation.json", translation.canonical_bytes())
        atomic_write_bytes(staging / "pit-evidence.json", evidence.canonical_bytes())
        write_signal_table((row,), staging / "signals.parquet")
        files = tuple(
            SignalArtifactFile(
                logical_path=path.relative_to(staging).as_posix(),
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        )
        manifest = SignalArtifactManifest.create(
            resolved_experiment_hash=resolved.content_hash,
            source_expression_or_model_hash=expression.content_hash,
            snapshot_hash=resolved.snapshot_hash,
            qlib_version=resolved.qlib_version,
            qlib_view_spec_hash=resolved.qlib_view_spec_hash,
            qlib_view_hash=resolved.qlib_view_hash,
            qlib_run_id=None,
            pit_evidence_hash=evidence.content_hash,
            transform_lineage_hash=pit_transform_lineage_hash(evidence),
            expression_translation_hash=translation.content_hash,
            row_count=1,
            signal_start=signal_time,
            signal_end=signal_time,
            signal_content_hash=signal_content_hash((row,)),
            files=files,
            created_at=OCCURRED_AT,
        )
        atomic_write_bytes(
            staging / "manifest.json", canonical_json_bytes(manifest.model_dump(mode="python"))
        )
        destination = destination_root / f"sha256-{manifest.artifact_hash}"
        if not destination.exists():
            publish_directory(staging, destination)
    verified = verify_signal_artifact(destination)
    if verified.resolved_experiment_hash != resolved.content_hash or code.commit_hash == "0" * 40:
        raise QualificationError("synthetic Signal artifact is not bound to qualification inputs")
    return destination


def _write_result(
    root: Path,
    *,
    candidate: object,
    candidate_index: int,
    campaign: ResearchCampaignSpec,
    view_manifest: QlibViewManifest,
    research_policy: ResearchPolicy,
    code: CodeProvenance,
    dates: tuple[date, ...],
    case_id: str,
    missing_signal: bool = False,
) -> ResearchResultManifest:
    from quantos.contracts.enumeration import ResearchCandidateSpec
    from quantos.contracts.research import ResolvedExperimentSpec

    assert isinstance(candidate, ResearchCandidateSpec)
    strategy = StrategyAuthoringSpec(
        universe_index="000300.SH",
        top_k=50,
        input_lag_trading_days=candidate.expression.input_lag_trading_days,
    )
    authoring = ExperimentAuthoringSpec(
        experiment_id=f"p14c-{case_id.lower()}-candidate-{candidate_index}",
        evaluation_start=dates[0],
        evaluation_end=dates[-1],
        expression=candidate.expression,
        strategy=strategy,
    )
    resolved: ResolvedExperimentSpec = resolve_experiment(
        authoring,
        snapshot_hash=campaign.snapshot_hash,
        qlib_view_hash=campaign.qlib_view_hash,
        qlib_version=view_manifest.qlib_version,
        qlib_view_spec_hash=view_manifest.view_spec_hash,
        pit_audit_evidence_hash="c" * 64,
        research_policy_hash=research_policy.content_hash,
        validation_policy_hash="d" * 64,
        cost_policy_hash="e" * 64,
        backtest_policy_hash="f" * 64,
        code_commit_hash=code.commit_hash,
        lockfile_hash=code.lockfile_hash,
    )
    signal_path = _publish_signal(
        resolved,
        root,
        view_hash=view_manifest.view_hash,
        session_date=dates[5],
        code=code,
    )
    resolved_path = signal_path / "resolved-experiment.json"
    resolved = ResolvedExperimentSpec.model_validate_json(resolved_path.read_bytes())
    native = root / f"native-{candidate_index}"
    (native / "sig_analysis").mkdir(parents=True)
    instrument_count = 100
    instruments = tuple(f"SH{600000 + index:06d}" for index in range(instrument_count))
    index = pd.MultiIndex.from_tuples(
        [
            (instrument, pd.Timestamp(trade_date))
            for trade_date in dates
            for instrument in instruments
        ],
        names=("instrument", "datetime"),
    )
    prediction = pd.DataFrame(
        {"score": [float(rank) for _ in dates for rank in range(instrument_count)]},
        index=index,
    )
    label = pd.DataFrame(
        {
            "LABEL0": [
                float(_synthetic_label_rank(case_id, candidate_index, day, rank, instrument_count))
                for day, _trade_date in enumerate(dates)
                for rank in range(instrument_count)
            ]
        },
        index=index,
    )
    recorder = _NativeRecorder(prediction, label)
    with redirect_stdout(io.StringIO()):
        generated = cast(
            dict[str, object] | None,
            SigAnaRecord(recorder)._generate(),  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        )
    if generated is None:
        raise QualificationError("Qlib SigAnaRecord did not return its native output mapping")
    prediction.to_pickle(native / "pred.pkl")
    label.to_pickle(native / "label.pkl")
    cast(pd.Series, generated["ic.pkl"]).to_pickle(native / "sig_analysis" / "ic.pkl")
    cast(pd.Series, generated["ric.pkl"]).to_pickle(native / "sig_analysis" / "ric.pkl")
    (native / "metrics.json").write_bytes(canonical_json_bytes(recorder.metrics))
    # The synthetic PIT object is rebuilt after the resolved experiment has been frozen.
    result = ResearchResultArtifactBuilder().build(
        resolved,
        research_policy,
        signal_path,
        native,
        root / "results",
        qlib_run_id=f"p14c-{case_id.lower()}-run-{candidate_index}",
        label_expression="Ref($close,-1)/$close-1",
        created_at=OCCURRED_AT,
    )
    if missing_signal:
        raise AssertionError("missing_signal fixture is not used for canonical generation")
    return verify_research_result(result.path)


def _write_model(path: Path, model: object) -> None:
    if not hasattr(model, "canonical_bytes"):
        raise TypeError(f"qualification input is not a canonical contract: {path.name}")
    atomic_write_bytes(path, model.canonical_bytes())  # type: ignore[attr-defined]


def _write_events(path: Path, events: tuple[CampaignChainEvent, ...]) -> None:
    atomic_write_bytes(
        path,
        canonical_json_bytes([item.model_dump(mode="python") for item in events]),
    )


def _read_events(path: Path) -> tuple[CampaignChainEvent, ...]:
    from quantos.contracts.campaign_selection import CampaignSelectionEvent

    payload_value = json.loads(path.read_bytes())
    if not isinstance(payload_value, list):
        raise ValueError("campaign event chain must be a JSON list")
    payload = cast(list[object], payload_value)
    events: list[CampaignChainEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("campaign event chain item must be an object")
        record = cast(dict[str, object], item)
        if record.get("schema_version") == "campaign-selection-event/v1":
            events.append(CampaignSelectionEvent.model_validate(record))
        else:
            events.append(ResearchCampaignEvent.model_validate(record))
    return tuple(events)


def _build_case(
    root: Path,
    *,
    case_id: str,
    code: CodeProvenance,
    dates: tuple[date, ...],
    research_policy: ResearchPolicy,
    enforce_outcome: bool = True,
) -> _CaseInputs:
    if case_id not in P14C_CANONICAL_CASES:
        raise ValueError("unknown canonical P14c qualification case")
    case_root = root / "cases" / case_id.lower()
    case_root.mkdir(parents=True)
    template = _template()
    family = _family(template)
    manifest = enumerate_research_family(family, template)
    budget = ResearchBudgetSpec(
        budget_id="p14c-qualification-budget",
        max_trials=4,
        max_distinct_candidates=2,
        max_agent_runs=4,
        max_executions=4,
        max_validation_rounds=4,
        max_compute_seconds=10_000,
    )
    multiple = MultipleTestingPolicySpec(seed="b" * 64)
    selection = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple.content_hash,
        direction="POSITIVE",
    )
    view_manifest = _write_view(case_root, dates)
    campaign = ResearchCampaignSpec(
        campaign_id=f"p14c-qualification-{case_id.lower()}",
        research_question=family.research_question,
        family_hash=family.content_hash,
        budget_hash=budget.content_hash,
        evidence_hashes=("3" * 64,),
        ledger_snapshot_hash="a" * 64,
        snapshot_hash=view_manifest.source_snapshot_hash,
        qlib_view_hash=view_manifest.view_hash,
        development=ResearchSegment(start=date(2020, 1, 1), end=date(2020, 12, 31)),
        validation=ResearchSegment(start=dates[0], end=dates[-1]),
        sealed_confirmation=ResearchSegment(start=date(2022, 1, 1), end=date(2022, 12, 31)),
        multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
        stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
    )
    result_manifests: list[ResearchResultManifest] = []
    for candidate_index, candidate in enumerate(manifest.candidates):
        result_manifests.append(
            _write_result(
                case_root,
                candidate=candidate,
                candidate_index=candidate_index,
                campaign=campaign,
                view_manifest=view_manifest,
                research_policy=research_policy,
                code=code,
                dates=dates,
                case_id=case_id,
            )
        )
    results_root = case_root / "results"
    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple,
        selection,
        case_root / "views" / f"sha256-{view_manifest.view_hash}",
        (results_root,),
    )
    plan = service.build_plan()
    governor = ResearchCampaignGovernor(family, template, manifest)
    activation = governor.activate(
        campaign,
        family,
        budget,
        (),
        event_id=UUID("90000000-0000-0000-0000-000000000001"),
        occurred_at=OCCURRED_AT,
    )
    plan_event, plan_path = service.freeze_plan(
        governor,
        (activation,),
        event_id=UUID("90000000-0000-0000-0000-000000000002"),
        occurred_at=OCCURRED_AT + timedelta(seconds=1),
        artifact_root=case_root / "selection-plan",
    )
    events: tuple[CampaignChainEvent, ...] = (activation, plan_event)
    sorted_candidates = tuple(sorted(manifest.candidates, key=lambda item: item.content_hash))
    manifest_order = {item.content_hash: index for index, item in enumerate(manifest.candidates)}
    for event_index, candidate in enumerate(sorted_candidates):
        candidate_index = manifest_order[candidate.content_hash]
        result_hash = result_manifests[candidate_index].artifact_hash
        evidence_hashes = (
            () if case_id == "FAILED_NOT_EVALUATED" and event_index == 0 else (result_hash,)
        )
        trial = CampaignTrial(
            trial_id=f"validation-{event_index}",
            idempotency_key=f"{event_index + 1:x}".zfill(64),
            proposal_hash=f"{event_index + 3:x}".zfill(64),
            candidate_hash=candidate.content_hash,
            segment=CampaignSegment.VALIDATION,
            outcome=TrialOutcome.PASS,
            agent_run_hash="a" * 64,
            execution_requested=True,
            compute_seconds=1,
            evidence_hashes=evidence_hashes,
        )
        event = governor.record_selection_trial(
            campaign,
            budget,
            events,
            trial,
            plan,
            event_id=UUID(f"90000000-0000-0000-0000-{event_index + 3:012d}"),
            occurred_at=OCCURRED_AT + timedelta(seconds=event_index + 2),
        )
        events += (event,)
    report, report_path = service.publish_report(events, case_root / "selection-report")
    if case_id == "SELECTED" and enforce_outcome:
        if (
            report.run_status is not RunStatus.SUCCEEDED
            or report.verdict is not CampaignSelectionVerdict.SELECTED
        ):
            raise QualificationError("frozen SELECTED case did not select a candidate")
        selection_event = service.freeze_selection(
            governor,
            events,
            report_path,
            event_id=UUID("90000000-0000-0000-0000-000000000020"),
            occurred_at=OCCURRED_AT + timedelta(seconds=20),
        )
        all_events = (*events, selection_event)
    elif case_id == "NO_SELECTION" and enforce_outcome:
        if (
            report.run_status is not RunStatus.SUCCEEDED
            or report.verdict is not CampaignSelectionVerdict.NO_SELECTION
        ):
            raise QualificationError("frozen NO_SELECTION case did not complete without selection")
        all_events = events
    elif case_id == "FAILED_NOT_EVALUATED" and enforce_outcome:
        if (
            report.run_status is not RunStatus.FAILED
            or report.verdict is not CampaignSelectionVerdict.NOT_EVALUATED
            or report.reason_code is not ReasonCode.ARTIFACT_CORRUPTED
        ):
            raise QualificationError(
                "frozen failure case did not fail closed with ARTIFACT_CORRUPTED"
            )
        all_events = events
    else:
        all_events = events
    inputs = case_root / "inputs"
    inputs.mkdir()
    for filename, model in (
        ("campaign.json", campaign),
        ("family.json", family),
        ("budget.json", budget),
        ("template.json", template),
        ("candidate-manifest.json", manifest),
        ("multiple-testing-policy.json", multiple),
        ("selection-policy.json", selection),
        ("research-policy.json", research_policy),
        ("selection-plan.json", plan),
    ):
        _write_model(inputs / filename, model)
    events_path = case_root / "events.json"
    report_events_path = case_root / "report-events.json"
    _write_events(events_path, all_events)
    _write_events(report_events_path, events)
    return _CaseInputs(
        case_id=case_id,
        campaign=campaign,
        family=family,
        budget=budget,
        template=template,
        manifest=manifest,
        multiple_testing_policy=multiple,
        selection_policy=selection,
        research_policy=research_policy,
        view_path=case_root / "views" / f"sha256-{view_manifest.view_hash}",
        results_root=results_root,
        plan_path=plan_path,
        report_path=report_path,
        events_path=events_path,
        report_events_path=report_events_path,
        events=all_events,
        report_events=events,
        report=report,
        plan=plan,
        governor=governor,
        service=service,
    )


def _principal_hashes(case: _CaseInputs) -> tuple[P14cNamedHash, ...]:
    report = case.report
    accounting = sha256_bytes(
        canonical_json_bytes(
            {
                "candidate_dispositions": report.candidate_dispositions,
                "trial_bindings": report.trial_bindings,
            }
        )
    )
    result_hashes = tuple(
        sorted(
            verify_research_result(item).artifact_hash
            for item in case.results_root.glob("sha256-*")
        )
    )
    result_set = sha256_bytes(canonical_json_bytes(result_hashes))
    chain_hash = sha256_bytes(
        canonical_json_bytes(tuple(event.content_hash for event in case.events))
    )
    return (
        P14cNamedHash(name="campaign_selection_plan", sha256=case.plan.content_hash),
        P14cNamedHash(name="candidate_accounting", sha256=accounting),
        P14cNamedHash(name="candidate_manifest", sha256=case.manifest.content_hash),
        P14cNamedHash(name="campaign_selection_report", sha256=report.report_hash),
        P14cNamedHash(name="event_chain", sha256=chain_hash),
        P14cNamedHash(name="research_results_set", sha256=result_set),
    )


def _case_evidence(case: _CaseInputs) -> P14cRootCaseEvidence:
    result_hashes = tuple(
        sorted(
            verify_research_result(item).artifact_hash
            for item in case.results_root.glob("sha256-*")
        )
    )
    event_hashes = tuple(event.content_hash for event in case.events)
    accounting_hash = next(
        item.sha256 for item in _principal_hashes(case) if item.name == "candidate_accounting"
    )
    selection_events = tuple(
        event
        for event in case.events
        if isinstance(event, CampaignSelectionEvent)
        and event.event_type is CampaignSelectionEventType.SELECTION_FROZEN
    )
    outcome = P14cCanonicalCaseResult(
        case_id=case.case_id,  # type: ignore[arg-type]
        run_status=case.report.run_status,
        verdict=case.report.verdict,
        reason_code=case.report.reason_code,
        selected_candidate_hash=case.report.selected_candidate_hash,
        selection_plan_hash=case.plan.content_hash,
        selection_report_hash=case.report.report_hash,
    )
    return P14cRootCaseEvidence(
        outcome=outcome,
        candidate_manifest_hash=case.manifest.content_hash,
        candidate_accounting_hash=accounting_hash,
        research_result_hashes=result_hashes,
        event_hashes=event_hashes,
        event_chain_hash=sha256_bytes(canonical_json_bytes(event_hashes)),
        selection_event_hash=selection_events[0].content_hash if selection_events else None,
        principal_hashes=_principal_hashes(case),
    )


def _load_case_inputs(case_root: Path) -> _CaseInputs:
    from quantos.contracts.enumeration import CandidateEnumerationManifest
    from quantos.contracts.research import ResearchPolicy

    inputs = case_root / "inputs"
    campaign = ResearchCampaignSpec.model_validate_json((inputs / "campaign.json").read_bytes())
    family = ResearchFamilySpec.model_validate_json((inputs / "family.json").read_bytes())
    budget = ResearchBudgetSpec.model_validate_json((inputs / "budget.json").read_bytes())
    template = ResearchFactorTemplateSpec.model_validate_json(
        (inputs / "template.json").read_bytes()
    )
    manifest = CandidateEnumerationManifest.model_validate_json(
        (inputs / "candidate-manifest.json").read_bytes()
    )
    multiple = MultipleTestingPolicySpec.model_validate_json(
        (inputs / "multiple-testing-policy.json").read_bytes()
    )
    selection = SelectionPolicySpec.model_validate_json(
        (inputs / "selection-policy.json").read_bytes()
    )
    research_policy = ResearchPolicy.model_validate_json(
        (inputs / "research-policy.json").read_bytes()
    )
    plan = CampaignSelectionPlan.model_validate_json((inputs / "selection-plan.json").read_bytes())
    verified_plan = verify_selection_plan_artifact(
        case_root / "selection-plan" / f"sha256-{plan.content_hash}"
    )
    if verified_plan != plan:
        raise ValueError("P14c qualification root plan artifact differs from its frozen input")
    view_path = case_root / "views" / f"sha256-{campaign.qlib_view_hash}"
    results_root = case_root / "results"
    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple,
        selection,
        view_path,
        (results_root,),
        plan=plan,
    )
    report_path = case_root / "selection-report" / f"sha256-{plan.content_hash}"
    report_artifacts = tuple((case_root / "selection-report").glob("sha256-*"))
    if len(report_artifacts) != 1:
        raise ValueError("P14c canonical case must contain one selection report artifact")
    report_path = report_artifacts[0]
    report = verify_selection_report_artifact(report_path)
    report_events = _read_events(case_root / "report-events.json")
    events = _read_events(case_root / "events.json")
    governor = ResearchCampaignGovernor(family, template, manifest)
    return _CaseInputs(
        case_id=case_root.name.upper(),
        campaign=campaign,
        family=family,
        budget=budget,
        template=template,
        manifest=manifest,
        multiple_testing_policy=multiple,
        selection_policy=selection,
        research_policy=research_policy,
        view_path=view_path,
        results_root=results_root,
        plan_path=case_root / "selection-plan" / f"sha256-{plan.content_hash}",
        report_path=report_path,
        events_path=case_root / "events.json",
        report_events_path=case_root / "report-events.json",
        events=events,
        report_events=report_events,
        report=report,
        plan=plan,
        governor=governor,
        service=service,
    )


def _copy_results(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    for artifact in sorted(source.glob("sha256-*")):
        shutil.copytree(artifact, destination / artifact.name)
    return destination


def _rehash_result(
    source: Path,
    destination_root: Path,
    *,
    rank_value: float | None = None,
    nonfinite_rank_ic: bool = False,
    evaluation_start: date | None = None,
) -> Path:
    from quantos.contracts.research import ResolvedExperimentSpec

    manifest = verify_research_result(source)
    destination_root.mkdir(parents=True, exist_ok=True)
    work = destination_root / "result-work"
    shutil.copytree(source, work)
    payload = manifest.model_dump(mode="python", exclude={"artifact_hash"})
    files = list(payload["files"])
    rank_path = work / "rank-ic-series.json"
    if rank_value is not None or nonfinite_rank_ic:
        rows = json.loads(rank_path.read_bytes())
        rows[0]["value"] = float("nan") if nonfinite_rank_ic else rank_value
        rank_bytes = json.dumps(
            rows,
            allow_nan=nonfinite_rank_ic,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        rank_path.write_bytes(rank_bytes)
        payload["rank_ic_content_hash"] = sha256_bytes(rank_bytes)
        for index, item in enumerate(files):
            if item["logical_path"] == "rank-ic-series.json":
                files[index] = ResearchResultArtifactFile(
                    logical_path="rank-ic-series.json",
                    sha256=sha256_bytes(rank_bytes),
                    size_bytes=len(rank_bytes),
                )
                break
    if evaluation_start is not None:
        resolved_path = work / "resolved-experiment.json"
        resolved = ResolvedExperimentSpec.model_validate_json(resolved_path.read_bytes())
        resolved = resolved.model_copy(update={"evaluation_start": evaluation_start})
        resolved_bytes = resolved.canonical_bytes()
        resolved_path.write_bytes(resolved_bytes)
        payload["resolved_experiment_hash"] = resolved.content_hash
        for index, item in enumerate(files):
            if item["logical_path"] == "resolved-experiment.json":
                files[index] = ResearchResultArtifactFile(
                    logical_path="resolved-experiment.json",
                    sha256=sha256_bytes(resolved_bytes),
                    size_bytes=len(resolved_bytes),
                )
                break
    payload["files"] = tuple(files)
    new_manifest = ResearchResultManifest.create(**payload)
    (work / "manifest.json").write_bytes(
        canonical_json_bytes(new_manifest.model_dump(mode="python"))
    )
    destination = destination_root / f"sha256-{new_manifest.artifact_hash}"
    work.rename(destination)
    return destination


def _service_for(
    case: _CaseInputs,
    *,
    view_path: Path | None = None,
    results_root: Path | None = None,
    campaign: ResearchCampaignSpec | None = None,
    family: ResearchFamilySpec | None = None,
    budget: ResearchBudgetSpec | None = None,
    manifest: CandidateEnumerationManifest | None = None,
) -> CampaignSelectionService:
    return CampaignSelectionService(
        campaign or case.campaign,
        family or case.family,
        budget or case.budget,
        case.template,
        manifest or case.manifest,
        case.multiple_testing_policy,
        case.selection_policy,
        view_path or case.view_path,
        (results_root or case.results_root,),
        plan=case.plan,
    )


def _replace_event_and_relink(
    events: tuple[CampaignChainEvent, ...], index: int, replacement: ResearchCampaignEvent
) -> tuple[CampaignChainEvent, ...]:
    changed = list(events)
    changed[index] = replacement
    for position in range(index + 1, len(changed)):
        previous = changed[position - 1]
        event = changed[position]
        changed[position] = event.model_copy(update={"previous_event_hash": previous.content_hash})
    return tuple(changed)


def _failed_report(
    service: CampaignSelectionService, events: tuple[CampaignChainEvent, ...]
) -> tuple[ReasonCode, str]:
    report = service.build_report(events)
    if (
        report.run_status is not RunStatus.FAILED
        or report.verdict is not CampaignSelectionVerdict.NOT_EVALUATED
        or report.reason_code is None
    ):
        raise QualificationError("P14c negative input did not fail closed")
    return report.reason_code, report.content_hash


def _caught_reason(action: Callable[[], object]) -> tuple[ReasonCode, str]:
    try:
        result = action()
    except (CampaignSelectionError, CampaignGovernanceError, QlibResearchError) as error:
        return error.reason_code, type(error).__name__
    except (ValidationError, ValueError, OSError, ArtifactIntegrityError) as error:
        return ReasonCode.ARTIFACT_CORRUPTED, type(error).__name__
    if isinstance(result, tuple):
        values = cast(tuple[object, ...], result)
        if len(values) == 2 and isinstance(values[0], ReasonCode):
            return cast(tuple[ReasonCode, str], values)
    raise QualificationError("P14c negative action unexpectedly succeeded")


def _negative_input_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        normalized: object = {
            "bytes_sha256": sha256_bytes(value),
            "size_bytes": len(value),
        }
    elif isinstance(value, tuple):
        values = cast(tuple[object, ...], value)
        normalized = tuple(json.loads(_negative_input_bytes(item)) for item in values)
    elif isinstance(value, list):
        values = cast(list[object], value)
        normalized = [json.loads(_negative_input_bytes(item)) for item in values]
    elif isinstance(value, dict):
        values = cast(dict[object, object], value)
        normalized = {
            str(key): json.loads(_negative_input_bytes(item)) for key, item in values.items()
        }
    else:
        return canonical_json_bytes(value)
    return canonical_json_bytes(normalized)


def _forged_report_path(
    root: Path,
    case: _CaseInputs,
    case_id: str,
    mutate: Callable[[dict[str, object]], dict[str, object]],
) -> Path:
    payload = case.report.model_dump(mode="python", exclude={"report_hash", "schema_version"})
    changed = mutate(payload)
    full_payload = {"schema_version": "campaign-selection-report/v1", **changed}
    report_hash = sha256_bytes(canonical_json_bytes(full_payload))
    forged = CampaignSelectionReport.model_validate({"report_hash": report_hash, **changed})
    destination = root / case_id / f"sha256-{forged.report_hash}"
    destination.mkdir(parents=True)
    atomic_write_bytes(destination / "report.json", forged.canonical_bytes())
    return destination


def _run_negative_cases(
    root: Path,
    cases: dict[str, _CaseInputs],
    *,
    publish_proofs: bool = True,
) -> tuple[P14cNegativeCaseEvidence, ...]:
    """Execute each frozen negative case against the real P14c verifiers and governor."""

    selected = cases["SELECTED"]
    no_selection = cases["NO_SELECTION"]
    failed = cases["FAILED_NOT_EVALUATED"]
    temporary = Path(tempfile.mkdtemp(prefix="p14c-negative-"))
    first_event = cast(ResearchCampaignEvent, selected.report_events[-2])
    last_event = cast(ResearchCampaignEvent, selected.report_events[-1])
    assert first_event.trial is not None and last_event.trial is not None
    first_trial = first_event.trial
    last_trial = last_event.trial
    first_result_hash = first_trial.evidence_hashes[0]
    losing_hash = next(
        item.content_hash
        for item in selected.manifest.candidates
        if item.content_hash != selected.report.selected_candidate_hash
    )
    negative_inputs: dict[str, object] = {}
    actions: dict[str, Callable[[], object]] = {}

    def set_report_failure(
        case_id: str,
        service: CampaignSelectionService,
        events: tuple[CampaignChainEvent, ...],
        input_value: object,
    ) -> None:
        negative_inputs[case_id] = input_value
        actions[case_id] = lambda: _failed_report(service, events)

    bad_manifest = selected.manifest.model_copy(update={"declared_candidate_count": 3})
    set_report_failure(
        "INCOMPLETE_CANDIDATE_DENOMINATOR",
        _service_for(selected, manifest=bad_manifest),
        selected.report_events,
        bad_manifest,
    )
    missing_trial = last_event.model_copy(
        update={"trial": last_trial.model_copy(update={"evidence_hashes": ()})}
    )
    set_report_failure(
        "MISSING_TRIAL_RESULT_BINDING",
        selected.service,
        (*selected.report_events[:-1], missing_trial),
        missing_trial,
    )
    repeated_trial = first_trial.model_copy(
        update={
            "trial_id": "repeat-validation",
            "idempotency_key": "f" * 64,
            "proposal_hash": "e" * 64,
        }
    )
    repeated_event = selected.governor.record_selection_trial(
        selected.campaign,
        selected.budget,
        selected.report_events,
        repeated_trial,
        selected.plan,
        event_id=UUID("90000000-0000-0000-0000-000000000090"),
        occurred_at=OCCURRED_AT + timedelta(seconds=30),
    )
    set_report_failure(
        "REPEATED_CANDIDATE_VALIDATION",
        selected.service,
        (*selected.report_events, repeated_event),
        repeated_event,
    )
    reused_trial = last_trial.model_copy(update={"evidence_hashes": (first_result_hash,)})
    reused_event = last_event.model_copy(update={"trial": reused_trial})
    set_report_failure(
        "RESULT_REUSED_ACROSS_CANDIDATES",
        selected.service,
        (*selected.report_events[:-1], reused_event),
        reused_event,
    )

    malformed_view_root = temporary / "malformed-view"
    shutil.copytree(selected.view_path, malformed_view_root)
    (malformed_view_root / "calendars/day.txt").write_text("not-a-date\n", encoding="utf-8")
    set_report_failure(
        "MALFORMED_VALIDATION_CALENDAR",
        _service_for(selected, view_path=malformed_view_root),
        selected.report_events,
        (malformed_view_root / "calendars/day.txt").read_bytes(),
    )
    alternate_view_root = temporary / "mismatched-view"
    _write_view(alternate_view_root, tuple(item + timedelta(days=1) for item in _trading_dates()))
    alternate_view = next((alternate_view_root / "views").glob("sha256-*"))
    set_report_failure(
        "VALIDATION_CALENDAR_MISMATCH",
        _service_for(selected, view_path=alternate_view),
        selected.report_events,
        verify_qlib_view(alternate_view),
    )

    corrupt_root = _copy_results(selected.results_root, temporary / "invalid-rank-ic")
    (corrupt_root / f"sha256-{first_result_hash}" / "rank-ic-series.json").write_bytes(b"{}")
    set_report_failure(
        "INVALID_RANK_IC_SERIES",
        _service_for(selected, results_root=corrupt_root),
        selected.report_events,
        (first_result_hash, b"{}"),
    )
    missing_root = _copy_results(selected.results_root, temporary / "missing-rank-ic")
    (missing_root / f"sha256-{first_result_hash}" / "rank-ic-series.json").unlink()
    set_report_failure(
        "MISSING_RANK_IC_SERIES",
        _service_for(selected, results_root=missing_root),
        selected.report_events,
        (first_result_hash, "rank-ic-series.json absent"),
    )
    nonfinite_root = temporary / "nonfinite-result"
    nonfinite_path = _rehash_result(
        selected.results_root / f"sha256-{first_result_hash}",
        nonfinite_root,
        nonfinite_rank_ic=True,
    )
    nonfinite_service_root = _copy_results(selected.results_root, temporary / "nonfinite-results")
    shutil.copytree(nonfinite_path, nonfinite_service_root / nonfinite_path.name)
    nonfinite_trial = first_trial.model_copy(
        update={"evidence_hashes": (nonfinite_path.name.removeprefix("sha256-"),)}
    )
    nonfinite_event = first_event.model_copy(update={"trial": nonfinite_trial})
    nonfinite_events = _replace_event_and_relink(selected.report_events, 2, nonfinite_event)
    set_report_failure(
        "NONFINITE_RANK_IC",
        _service_for(selected, results_root=nonfinite_service_root),
        nonfinite_events,
        (first_result_hash, b"non-finite Rank IC"),
    )
    range_root = temporary / "out-of-range-result"
    range_path = _rehash_result(
        selected.results_root / f"sha256-{first_result_hash}",
        range_root,
        rank_value=1.01,
    )
    range_results = _copy_results(selected.results_root, temporary / "out-of-range-results")
    shutil.copytree(range_path, range_results / range_path.name)
    range_trial = first_trial.model_copy(
        update={"evidence_hashes": (range_path.name.removeprefix("sha256-"),)}
    )
    range_event = first_event.model_copy(update={"trial": range_trial})
    range_events = _replace_event_and_relink(selected.report_events, 2, range_event)
    set_report_failure(
        "RANK_IC_OUT_OF_RANGE",
        _service_for(selected, results_root=range_results),
        range_events,
        (first_result_hash, 1.01),
    )

    # Rehashed summary forgeries must fail the real frozen-input recomputation.
    def verify_forgery(
        case_id: str, mutator: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        report_path = _forged_report_path(temporary / "forged", selected, case_id, mutator)
        negative_inputs[case_id] = (case_id, (report_path / "report.json").read_bytes())
        actions[case_id] = lambda: _caught_reason(
            lambda: selected.service.verify_report(report_path, selected.report_events)
        )

    verify_forgery("FORGED_CANDIDATE_SCORE", lambda p: _change_score(p, "oriented_mean_rank_ic"))
    verify_forgery("FORGED_RAW_P_VALUE", lambda p: _change_score(p, "raw_p_value"))
    verify_forgery("FORGED_ADJUSTED_P_VALUE", lambda p: _change_score(p, "adjusted_p_value"))
    verify_forgery("FORGED_SELECTED_CANDIDATE", _change_selected_candidate)
    verify_forgery(
        "MISSING_CANDIDATE_DISPOSITION", lambda p: _drop_losing_candidate(p, losing_hash)
    )

    modified_report_root = temporary / "modified-report"
    modified_report = modified_report_root / selected.report_path.name
    shutil.copytree(selected.report_path, modified_report)
    with (modified_report / "report.json").open("ab") as handle:
        handle.write(b" ")
    negative_inputs["MODIFIED_CAMPAIGN_SELECTION_REPORT"] = (selected.report.report_hash, b" ")
    actions["MODIFIED_CAMPAIGN_SELECTION_REPORT"] = lambda: _caught_reason(
        lambda: selected.service.verify_report(modified_report, selected.report_events)
    )

    modified_plan_root = temporary / "modified-plan"
    modified_plan = modified_plan_root / selected.plan_path.name
    shutil.copytree(selected.plan_path, modified_plan)
    (modified_plan / "plan.json").write_bytes(b"{}")
    negative_inputs["MODIFIED_CAMPAIGN_SELECTION_PLAN"] = (selected.plan.content_hash, b"{}")
    actions["MODIFIED_CAMPAIGN_SELECTION_PLAN"] = lambda: _caught_reason(
        lambda: verify_selection_plan_artifact(modified_plan)
    )
    extra_plan_root = temporary / "extra-plan"
    extra_plan = extra_plan_root / selected.plan_path.name
    shutil.copytree(selected.plan_path, extra_plan)
    (extra_plan / "unexpected.json").write_bytes(b"{}")
    negative_inputs["ARTIFACT_EXACT_FILE_SET_VIOLATION"] = (
        selected.plan.content_hash,
        "unexpected.json",
    )
    actions["ARTIFACT_EXACT_FILE_SET_VIOLATION"] = lambda: _caught_reason(
        lambda: verify_selection_plan_artifact(extra_plan)
    )

    campaign_event = selected.report_events[0].model_copy(update={"campaign_hash": "f" * 64})
    set_report_failure(
        "CAMPAIGN_HASH_MISMATCH",
        selected.service,
        (campaign_event, *selected.report_events[1:]),
        campaign_event,
    )
    set_report_failure(
        "MANIFEST_HASH_MISMATCH",
        _service_for(
            selected, manifest=selected.manifest.model_copy(update={"declared_candidate_count": 4})
        ),
        selected.report_events,
        (selected.manifest.content_hash, "declared_candidate_count=4"),
    )
    set_report_failure(
        "FAMILY_HASH_MISMATCH",
        _service_for(
            selected, campaign=selected.campaign.model_copy(update={"family_hash": "f" * 64})
        ),
        selected.report_events,
        (selected.campaign.content_hash, "family_hash=" + "f" * 64),
    )
    set_report_failure(
        "CAMPAIGN_BUDGET_FAMILY_BINDING_MISMATCH",
        _service_for(
            selected, campaign=selected.campaign.model_copy(update={"budget_hash": "f" * 64})
        ),
        selected.report_events,
        (selected.campaign.content_hash, selected.budget.content_hash),
    )
    expression_mismatch_event = last_event.model_copy(
        update={"trial": last_trial.model_copy(update={"evidence_hashes": (first_result_hash,)})}
    )
    set_report_failure(
        "CANDIDATE_EXPRESSION_FINGERPRINT_MISMATCH",
        selected.service,
        (*selected.report_events[:-1], expression_mismatch_event),
        expression_mismatch_event,
    )

    out_segment_root = _copy_results(selected.results_root, temporary / "out-segment-results")
    out_segment_path = _rehash_result(
        selected.results_root / f"sha256-{first_result_hash}",
        temporary / "out-segment-result",
        evaluation_start=selected.campaign.validation.start - timedelta(days=1),
    )
    shutil.copytree(out_segment_path, out_segment_root / out_segment_path.name)
    out_segment_trial = first_trial.model_copy(
        update={"evidence_hashes": (out_segment_path.name.removeprefix("sha256-"),)}
    )
    out_segment_event = first_event.model_copy(update={"trial": out_segment_trial})
    set_report_failure(
        "RESULT_OUTSIDE_VALIDATION_SEGMENT",
        _service_for(selected, results_root=out_segment_root),
        _replace_event_and_relink(selected.report_events, 2, out_segment_event),
        (first_result_hash, selected.campaign.validation.start - timedelta(days=1)),
    )

    session_case = _build_case(
        temporary / "insufficient-sessions",
        case_id="SELECTED",
        code=CodeProvenance(
            commit_hash="a" * 40,
            lockfile_hash="b" * 64,
            worktree_clean=True,
        ),
        dates=_trading_dates(39),
        research_policy=selected.research_policy,
        enforce_outcome=False,
    )
    if session_case.report.reason_code is not ReasonCode.SOFT_THRESHOLD_NOT_MET:
        raise QualificationError("39-session Rank IC input did not fail on the frozen minimum")
    negative_inputs["INSUFFICIENT_VALIDATION_SESSIONS"] = (39, session_case.report.content_hash)
    actions["INSUFFICIENT_VALIDATION_SESSIONS"] = lambda: (
        session_case.report.reason_code,
        session_case.report.content_hash,
    )

    wrong_selected = next(
        item.content_hash
        for item in selected.manifest.candidates
        if item.content_hash != selected.report.selected_candidate_hash
    )
    sealed_trial = CampaignTrial(
        trial_id="sealed-wrong-candidate",
        idempotency_key="c" * 64,
        proposal_hash="d" * 64,
        candidate_hash=wrong_selected,
        segment=CampaignSegment.SEALED_CONFIRMATION,
        outcome=TrialOutcome.PASS,
        execution_requested=True,
        compute_seconds=1,
    )
    negative_inputs["SELECTED_CANDIDATE_OOS_MISMATCH"] = (
        selected.report.report_hash,
        wrong_selected,
    )
    actions["SELECTED_CANDIDATE_OOS_MISMATCH"] = lambda: _caught_reason(
        lambda: selected.service.access_sealed_confirmation(
            selected.governor,
            selected.events,
            sealed_trial,
            selected.report_path,
            event_id=UUID("90000000-0000-0000-0000-000000000091"),
            occurred_at=OCCURRED_AT + timedelta(seconds=40),
        )
    )

    negative_inputs["SELF_REPORTED_SELECTION_FREEZE_DENIED"] = selected.report
    actions["SELF_REPORTED_SELECTION_FREEZE_DENIED"] = lambda: _caught_reason(
        lambda: selected.governor.freeze_selection(
            selected.campaign,
            selected.budget,
            selected.report_events,
            selected.report,
            event_id=UUID("90000000-0000-0000-0000-000000000092"),
            occurred_at=OCCURRED_AT + timedelta(seconds=41),
        )
    )

    unverified_report = _forged_report_path(
        temporary / "unverified-selection-report",
        selected,
        "unverified-selection-report",
        lambda payload: _change_score(payload, "raw_p_value"),
    )
    negative_inputs["UNVERIFIED_SELECTION_REPORT_FREEZE_DENIED"] = (
        selected.report.report_hash,
        (unverified_report / "report.json").read_bytes(),
    )
    actions["UNVERIFIED_SELECTION_REPORT_FREEZE_DENIED"] = lambda: _caught_reason(
        lambda: selected.service.freeze_selection(
            selected.governor,
            selected.report_events,
            unverified_report,
            event_id=UUID("90000000-0000-0000-0000-000000000096"),
            occurred_at=OCCURRED_AT + timedelta(seconds=44),
        )
    )

    for case_id, segment in (
        ("POST_FREEZE_VALIDATION_TRIAL_DENIED", CampaignSegment.VALIDATION),
        ("POST_FREEZE_DEVELOPMENT_TRIAL_DENIED", CampaignSegment.DEVELOPMENT),
    ):
        appended_trial = first_trial.model_copy(
            update={
                "trial_id": case_id.lower(),
                "idempotency_key": hashlib.sha256(case_id.encode()).hexdigest(),
                "proposal_hash": hashlib.sha256((case_id + "proposal").encode()).hexdigest(),
                "segment": segment,
            }
        )
        negative_inputs[case_id] = (selected.events[-1].content_hash, appended_trial)
        actions[case_id] = lambda trial=appended_trial, event_name=case_id: _caught_reason(
            lambda: selected.governor.record_trial(
                selected.campaign,
                selected.budget,
                selected.events,
                trial,
                event_id=UUID(
                    "90000000-0000-0000-0000-000000000093"
                    if event_name.endswith("VALIDATION_TRIAL_DENIED")
                    else "90000000-0000-0000-0000-000000000094"
                ),
                occurred_at=OCCURRED_AT + timedelta(seconds=42),
            )
        )

    for case_id, source in (
        ("NO_SELECTION_SEALED_CONFIRMATION_DENIED", no_selection),
        ("NOT_EVALUATED_SEALED_CONFIRMATION_DENIED", failed),
    ):
        sealed = sealed_trial.model_copy(
            update={
                "trial_id": case_id.lower(),
                "candidate_hash": source.manifest.candidates[0].content_hash,
            }
        )
        negative_inputs[case_id] = (source.report.report_hash, sealed)
        actions[case_id] = lambda case=source, trial=sealed: _caught_reason(
            lambda: case.service.access_sealed_confirmation(
                case.governor,
                case.events,
                trial,
                case.report_path,
                event_id=UUID("90000000-0000-0000-0000-000000000095"),
                occurred_at=OCCURRED_AT + timedelta(seconds=43),
            )
        )

    missing_trial_events = (*selected.report_events[:2], *selected.report_events[3:])
    set_report_failure(
        "MISSING_TRIAL_ACCOUNTING",
        selected.service,
        missing_trial_events,
        missing_trial_events,
    )

    absent = set(P14C_NEGATIVE_CASES) - set(actions)
    extra = set(actions) - set(P14C_NEGATIVE_CASES)
    if absent or extra:
        raise QualificationError(
            f"P14c negative case registry mismatch: absent={sorted(absent)} extra={sorted(extra)}"
        )

    proofs: list[P14cNegativeCaseEvidence] = []
    proof_root = root / "negative-cases"
    if publish_proofs:
        proof_root.mkdir(parents=True, exist_ok=True)
    for case_id in P14C_NEGATIVE_CASES:
        input_value = negative_inputs[case_id]
        input_bytes = _negative_input_bytes(input_value)
        reason, evidence = _caught_reason(actions[case_id])
        outcome_hash = sha256_bytes(
            canonical_json_bytes({"case_id": case_id, "evidence": evidence, "reason_code": reason})
        )
        proof = P14cNegativeCaseEvidence(
            case_id=case_id,
            input_hash=sha256_bytes(input_bytes),
            outcome_hash=outcome_hash,
            reason_code=reason,
        )
        proofs.append(proof)
        if publish_proofs:
            atomic_write_bytes(proof_root / f"{case_id}.json", proof.canonical_bytes())
    shutil.rmtree(temporary)
    return tuple(proofs)


def _change_score(payload: dict[str, object], field: str) -> dict[str, object]:
    scores = [dict(item) for item in cast(list[dict[str, object]], payload["scores"])]
    target = next(
        item for item in scores if item["candidate_hash"] == payload["selected_candidate_hash"]
    )
    target[field] = float(cast(float, target[field])) + 0.001
    payload["scores"] = tuple(scores)
    return payload


def _change_selected_candidate(payload: dict[str, object]) -> dict[str, object]:
    selected = cast(str, payload["selected_candidate_hash"])
    payload["selected_candidate_hash"] = next(
        item["candidate_hash"]
        for item in cast(list[dict[str, object]], payload["scores"])
        if item["candidate_hash"] != selected
    )
    return payload


def _drop_losing_candidate(payload: dict[str, object], candidate_hash: str) -> dict[str, object]:
    dispositions = cast(list[dict[str, object]], payload["candidate_dispositions"])
    scores = cast(list[dict[str, object]], payload["scores"])
    payload["candidate_dispositions"] = tuple(
        item for item in dispositions if item["candidate_hash"] != candidate_hash
    )
    payload["scores"] = tuple(item for item in scores if item["candidate_hash"] != candidate_hash)
    return payload


def _root_pipeline(
    root: Path,
    *,
    root_id: str,
    code: CodeProvenance,
    research_policy: ResearchPolicy,
) -> tuple[P14cRootEvidence, dict[str, _CaseInputs]]:
    dates = _trading_dates()
    cases: dict[str, _CaseInputs] = {}
    for case_id in P14C_CANONICAL_CASES:
        cases[case_id] = _build_case(
            root,
            case_id=case_id,
            code=code,
            dates=dates,
            research_policy=research_policy,
        )
    negative_cases = _run_negative_cases(root, cases)
    evidence = P14cRootEvidence(
        root_id=root_id,  # type: ignore[arg-type]
        input_fixture_hash=sha256_bytes(canonical_json_bytes(_fixture_payload())),
        cases=tuple(_case_evidence(cases[item]) for item in P14C_CANONICAL_CASES),
        negative_case_ids=P14C_NEGATIVE_CASES,
        negative_cases=negative_cases,
    )
    return evidence, cases


def _all_file_digests(root: Path) -> tuple[P14cQualificationFile, ...]:
    return tuple(
        P14cQualificationFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


def _publish_qualification(
    output_root: Path,
    *,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
    fixture_hash: str,
    roots: tuple[P14cRootEvidence, ...],
    pipeline_roots: tuple[Path, Path],
    policy_hashes: tuple[P14cNamedHash, ...],
) -> P14cQualificationReport:
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14c-qualification-", dir=output_root) as temporary:
        staging = Path(temporary)
        frozen = staging / "frozen"
        frozen.mkdir()
        atomic_write_bytes(
            frozen / "p14c-selection-contract.md", (ROOT / CONTRACT_PATH).read_bytes()
        )
        atomic_write_bytes(
            frozen / "research-policy.yaml", (ROOT / RESEARCH_POLICY_PATH).read_bytes()
        )
        atomic_write_bytes(frozen / "uv.lock", (ROOT / "uv.lock").read_bytes())
        atomic_write_bytes(
            frozen / "qualification-fixture.json", canonical_json_bytes(_fixture_payload())
        )
        atomic_write_bytes(staging / "code-provenance.json", code.canonical_bytes())
        atomic_write_bytes(staging / "runtime-fingerprint.json", runtime.canonical_bytes())
        for root_id, pipeline_root in zip(("root-A", "root-B"), pipeline_roots, strict=True):
            shutil.copytree(pipeline_root, staging / root_id)
        file_hashes = _all_file_digests(staging)
        report = P14cQualificationReport.create(
            status=RunStatus.SUCCEEDED,
            verdict="PASS",
            implementation_commit_hash=code.commit_hash,
            code_provenance_hash=code.content_hash,
            lockfile_hash=code.lockfile_hash,
            runtime_fingerprint_hash=runtime.content_hash,
            policy_hashes=policy_hashes,
            fixture_hash=fixture_hash,
            principal_hash_summary=p14c_principal_hash_summary(roots),
            roots=roots,
            principal_hashes_byte_exact=True,
            negative_case_count=len(P14C_NEGATIVE_CASES) * 2,
            limitations=LIMITATION_CODES,
            files=file_hashes,
        )
        atomic_write_bytes(
            staging / "qualification-report.json",
            canonical_json_bytes(report.model_dump(mode="python")),
        )
        destination = output_root / f"sha256-{report.qualification_hash}"
        if destination.exists() or destination.is_symlink():
            verified = verify_p14c_qualification_artifact(destination)
            if verified != report:
                raise ArtifactConflictError("existing P14c qualification report conflicts")
            return verified
        publish_directory(staging, destination)
    return report


def _qualify_from_provenance(
    *,
    workspace: Path,
    output_root: Path,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> dict[str, object]:
    """Run two complete synthetic pipelines and publish one immutable qualification report."""

    del workspace  # The exact Git workspace is checked by run() before this deterministic core.
    policy = load_yaml_contract(ROOT / RESEARCH_POLICY_PATH, ResearchPolicy)
    multiple = MultipleTestingPolicySpec(seed="b" * 64)
    selection = SelectionPolicySpec(
        multiple_testing_policy_hash=multiple.content_hash, direction="POSITIVE"
    )
    policy_hashes = (
        P14cNamedHash(name="p14c_contract", sha256=sha256_file(ROOT / CONTRACT_PATH)),
        P14cNamedHash(name="multiple_testing_policy", sha256=multiple.content_hash),
        P14cNamedHash(name="research_policy", sha256=policy.content_hash),
        P14cNamedHash(name="selection_policy", sha256=selection.content_hash),
    )
    fixture_hash = sha256_bytes(canonical_json_bytes(_fixture_payload()))
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14c-roots-", dir=output_root) as temporary:
        staging = Path(temporary)
        root_a_evidence, _ = _root_pipeline(
            staging / "root-A", root_id="root-A", code=code, research_policy=policy
        )
        root_b_evidence, _ = _root_pipeline(
            staging / "root-B", root_id="root-B", code=code, research_policy=policy
        )
        if root_a_evidence.cases != root_b_evidence.cases:
            raise QualificationError(
                "independent P14c roots produced non-identical principal hashes"
            )
        report = _publish_qualification(
            output_root,
            code=code,
            runtime=runtime,
            fixture_hash=fixture_hash,
            roots=(root_a_evidence, root_b_evidence),
            pipeline_roots=(staging / "root-A", staging / "root-B"),
            policy_hashes=policy_hashes,
        )
    artifact_path = output_root / f"sha256-{report.qualification_hash}"
    verified = verify_p14c_qualification_artifact(artifact_path)
    return {
        "schema_version": "p14c-qualification-runner-result/v1",
        "qualification_hash": verified.qualification_hash,
        "qualification_path": str(artifact_path),
        "implementation_commit_hash": verified.implementation_commit_hash,
        "lockfile_hash": verified.lockfile_hash,
        "runtime_fingerprint_hash": verified.runtime_fingerprint_hash,
        "principal_hashes_byte_exact": verified.principal_hashes_byte_exact,
        "canonical_cases": P14C_CANONICAL_CASES,
        "negative_case_count": verified.negative_case_count,
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


def verify_p14c_qualification_artifact(path: Path) -> P14cQualificationReport:
    """Verify the immutable report's exact files, provenance, principal artifacts, and replay."""

    try:
        tree = regular_tree_files(path)
        report_bytes = (path / "qualification-report.json").read_bytes()
        report = P14cQualificationReport.model_validate_json(report_bytes)
        expected_paths = {item.logical_path for item in report.files} | {
            "qualification-report.json"
        }
        actual_paths = {item.relative_to(path).as_posix() for item in tree}
        if actual_paths != expected_paths:
            raise ValueError("P14c qualification exact-file set does not match the report")
        if (
            path.name != f"sha256-{report.qualification_hash}"
            or canonical_json_bytes(report.model_dump(mode="python")) != report_bytes
        ):
            raise ValueError("P14c qualification report path or bytes do not match its hash")
        for item in report.files:
            target = path / item.logical_path
            if target.is_symlink() or target.stat().st_size != item.size_bytes:
                raise ValueError("P14c qualification file metadata does not match")
            if sha256_file(target) != item.sha256:
                raise ValueError("P14c qualification file hash does not match")
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
        ):
            raise ValueError("P14c qualification provenance does not match the report")
        fixture = (path / "frozen" / "qualification-fixture.json").read_bytes()
        if sha256_bytes(fixture) != report.fixture_hash:
            raise ValueError("P14c qualification synthetic fixture hash does not match")
        fixture_value = json.loads(fixture)
        if canonical_json_bytes(fixture_value) != fixture:
            raise ValueError("P14c qualification fixture is not canonical JSON")
        if sha256_file(path / "frozen" / "p14c-selection-contract.md") != next(
            item.sha256 for item in report.policy_hashes if item.name == "p14c_contract"
        ):
            raise ValueError("P14c selection contract changed after qualification")
        policy = load_yaml_contract(path / "frozen" / "research-policy.yaml", ResearchPolicy)
        if policy.content_hash != next(
            item.sha256 for item in report.policy_hashes if item.name == "research_policy"
        ):
            raise ValueError("P14c research policy changed after qualification")
        multiple = MultipleTestingPolicySpec(seed="b" * 64)
        selection = SelectionPolicySpec(
            multiple_testing_policy_hash=multiple.content_hash, direction="POSITIVE"
        )
        if multiple.content_hash != next(
            item.sha256 for item in report.policy_hashes if item.name == "multiple_testing_policy"
        ) or selection.content_hash != next(
            item.sha256 for item in report.policy_hashes if item.name == "selection_policy"
        ):
            raise ValueError("P14c frozen statistical or selection policy changed")
        # Root pipelines are replayed from their own frozen inputs. They never read the other root.
        for root_id, evidence in zip(("root-A", "root-B"), report.roots, strict=True):
            if evidence.root_id != root_id:
                raise ValueError("P14c qualification root identity is invalid")
            contexts: dict[str, _CaseInputs] = {}
            for case in evidence.cases:
                case_root = path / root_id / "cases" / case.outcome.case_id.lower()
                _verify_root_case(case_root, case, research_policy_hash=policy.content_hash)
                contexts[case.outcome.case_id] = _load_case_inputs(case_root)
            proof_root = path / root_id / "negative-cases"
            proof_paths = {item.name for item in proof_root.glob("*.json")}
            expected_proof_paths = {f"{item}.json" for item in P14C_NEGATIVE_CASES}
            if proof_paths != expected_proof_paths:
                raise ValueError("P14c negative-case proof set is incomplete")
            stored_proofs = tuple(
                P14cNegativeCaseEvidence.model_validate_json(
                    (proof_root / f"{case_id}.json").read_bytes()
                )
                for case_id in P14C_NEGATIVE_CASES
            )
            if stored_proofs != evidence.negative_cases:
                raise ValueError("P14c negative-case files disagree with the qualification report")
            with tempfile.TemporaryDirectory(prefix="p14c-qualification-verifier-") as work:
                replayed_proofs = _run_negative_cases(Path(work), contexts, publish_proofs=False)
            if replayed_proofs != evidence.negative_cases:
                raise ValueError("P14c negative cases did not reproduce independently")
        if report.roots[0].cases != report.roots[1].cases:
            raise ValueError("P14c qualification root comparison failed")
        if report.roots[0].negative_cases != report.roots[1].negative_cases:
            raise ValueError("P14c qualification negative-case comparison failed")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ValidationError,
        ArtifactIntegrityError,
        CampaignSelectionError,
        CampaignGovernanceError,
    ) as error:
        raise QualificationError("P14c qualification artifact verification failed") from error
    return report


def _verify_root_case(
    path: Path, expected: P14cRootCaseEvidence, *, research_policy_hash: str
) -> None:
    from quantos.contracts.campaign import ResearchFamilySpec
    from quantos.contracts.campaign_selection import (
        CampaignSelectionPlan,
        MultipleTestingPolicySpec,
        SelectionPolicySpec,
    )
    from quantos.contracts.enumeration import (
        CandidateEnumerationManifest,
        ResearchFactorTemplateSpec,
    )
    from quantos.contracts.research import ResearchPolicy

    inputs = path / "inputs"
    campaign = ResearchCampaignSpec.model_validate_json((inputs / "campaign.json").read_bytes())
    family = ResearchFamilySpec.model_validate_json((inputs / "family.json").read_bytes())
    budget = ResearchBudgetSpec.model_validate_json((inputs / "budget.json").read_bytes())
    template = ResearchFactorTemplateSpec.model_validate_json(
        (inputs / "template.json").read_bytes()
    )
    manifest = CandidateEnumerationManifest.model_validate_json(
        (inputs / "candidate-manifest.json").read_bytes()
    )
    multiple = MultipleTestingPolicySpec.model_validate_json(
        (inputs / "multiple-testing-policy.json").read_bytes()
    )
    selection = SelectionPolicySpec.model_validate_json(
        (inputs / "selection-policy.json").read_bytes()
    )
    research_policy = ResearchPolicy.model_validate_json(
        (inputs / "research-policy.json").read_bytes()
    )
    if research_policy.content_hash != research_policy_hash:
        raise ValueError("P14c root research policy differs from the frozen qualification policy")
    plan = CampaignSelectionPlan.model_validate_json((inputs / "selection-plan.json").read_bytes())
    verified_plan = verify_selection_plan_artifact(
        path / "selection-plan" / f"sha256-{plan.content_hash}"
    )
    if verified_plan != plan:
        raise ValueError("P14c qualification root plan artifact differs from its frozen input")
    if (
        verify_qlib_view(path / "views" / f"sha256-{campaign.qlib_view_hash}").view_hash
        != campaign.qlib_view_hash
    ):
        raise ValueError("P14c qualification root Qlib view is not verified")
    result_hashes = tuple(
        sorted(
            verify_research_result(item).artifact_hash
            for item in (path / "results").glob("sha256-*")
        )
    )
    if not result_hashes:
        raise ValueError("P14c qualification root has no immutable ResearchResult artifacts")
    service = CampaignSelectionService(
        campaign,
        family,
        budget,
        template,
        manifest,
        multiple,
        selection,
        path / "views" / f"sha256-{campaign.qlib_view_hash}",
        (path / "results",),
        plan=plan,
    )
    events = _read_events(path / "events.json")
    report_events = _read_events(path / "report-events.json")
    report_path = path / "selection-report" / f"sha256-{expected.outcome.selection_report_hash}"
    verified = service.verify_report(report_path, report_events)
    if (
        verified.report_hash != expected.outcome.selection_report_hash
        or verified.run_status != expected.outcome.run_status
        or verified.verdict != expected.outcome.verdict
        or verified.reason_code != expected.outcome.reason_code
        or verified.selected_candidate_hash != expected.outcome.selected_candidate_hash
    ):
        raise ValueError("P14c root selection report differs from the frozen outcome")
    governor = ResearchCampaignGovernor(family, template, manifest)
    if expected.outcome.case_id == "SELECTED":
        if len(events) != len(report_events) + 1:
            raise ValueError("selected root must append exactly one SelectionFrozen event")
        last = events[-1]
        if not isinstance(last, CampaignSelectionEvent):
            raise ValueError("selected root event chain does not end with SelectionFrozen")
        rebuilt = service.freeze_selection(
            governor,
            report_events,
            report_path,
            event_id=last.event_id,
            occurred_at=last.occurred_at,
        )
        if rebuilt != last:
            raise ValueError("SelectionFrozen event is not reproducible from verified report")
    elif events != report_events:
        raise ValueError("unselected qualification case cannot append SelectionFrozen")
    governor.project(campaign, budget, events)
    accounting_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "candidate_dispositions": verified.candidate_dispositions,
                "trial_bindings": verified.trial_bindings,
            }
        )
    )
    event_hashes = tuple(item.content_hash for item in events)
    chain_hash = sha256_bytes(canonical_json_bytes(event_hashes))
    principal = (
        P14cNamedHash(name="campaign_selection_plan", sha256=plan.content_hash),
        P14cNamedHash(name="candidate_accounting", sha256=accounting_hash),
        P14cNamedHash(name="candidate_manifest", sha256=manifest.content_hash),
        P14cNamedHash(name="campaign_selection_report", sha256=verified.report_hash),
        P14cNamedHash(name="event_chain", sha256=chain_hash),
        P14cNamedHash(
            name="research_results_set",
            sha256=sha256_bytes(canonical_json_bytes(result_hashes)),
        ),
    )
    rebuilt_evidence = P14cRootCaseEvidence(
        outcome=expected.outcome,
        candidate_manifest_hash=manifest.content_hash,
        candidate_accounting_hash=accounting_hash,
        research_result_hashes=result_hashes,
        event_hashes=event_hashes,
        event_chain_hash=chain_hash,
        selection_event_hash=(
            events[-1].content_hash if expected.outcome.case_id == "SELECTED" else None
        ),
        principal_hashes=principal,
    )
    if rebuilt_evidence != expected:
        raise ValueError("P14c root principal hash summary does not match replay")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/qualification/p14c"))
    parser.add_argument("--verify", type=Path, default=None)
    args = parser.parse_args()
    if args.verify is not None:
        report = verify_p14c_qualification_artifact(args.verify.resolve())
        result: dict[str, object] = {
            "schema_version": "p14c-qualification-verification/v1",
            "qualification_hash": report.qualification_hash,
            "status": report.status,
            "verdict": report.verdict,
        }
    else:
        result = run(workspace=args.workspace.resolve(), output_root=args.output_root.resolve())
    print(canonical_json_bytes(result).decode("utf-8"))


if __name__ == "__main__":
    main()
