"""Offline G0-G10 validation over verified Qlib-produced artifacts."""

from __future__ import annotations

import importlib
import math
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quantos.application.provenance import (
    ProvenanceError,
    capture_runtime_fingerprint,
    verify_code_provenance,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    ImmutableEventWriter,
    atomic_write_bytes,
    publish_directory,
    sha256_file,
    verify_file,
)
from quantos.backtest import verify_backtest_artifact
from quantos.contracts.backtest import BacktestArtifactManifest, QlibBacktestConfig
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.events import EventType, ImmutableEvent
from quantos.contracts.pit import PITAuditReport, PITEvidenceMode
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    SoftMetric,
    ThresholdComparison,
    ValidationPolicy,
)
from quantos.contracts.research_execution import PITCrossSectionEvidenceCollection
from quantos.contracts.signal import SignalArtifactManifest
from quantos.contracts.snapshot import DataQualityReport, DataSnapshotManifest
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import (
    VALIDATION_GATE_ORDER,
    GateResult,
    GateSeverity,
    ReproducibilityComparison,
    RobustnessCaseResult,
    RobustnessKind,
    ValidationArtifactFile,
    ValidationGateId,
    ValidationMetric,
    ValidationReport,
    validate_runtime_fingerprint_binding,
)
from quantos.data import QlibViewBuildError, SnapshotBuildError, verify_qlib_view, verify_snapshot
from quantos.research.qlib import QlibResearchError, verify_signal_artifact
from quantos.research.qlib.pit_evidence import (
    load_pit_artifact_evidence,
    verify_compact_pit_evidence,
)
from quantos.validation.locators import ValidationRunLocators, VariantArtifactLocator

_GATE_SEVERITY: Mapping[ValidationGateId, GateSeverity] = {
    ValidationGateId.G0_SCHEMA_REFERENCE: GateSeverity.HARD,
    ValidationGateId.G1_SNAPSHOT_DATA_QUALITY: GateSeverity.HARD,
    ValidationGateId.G2_PIT_LINEAGE: GateSeverity.HARD,
    ValidationGateId.G3_FACTOR_RESEARCH: GateSeverity.SOFT,
    ValidationGateId.G4_REFERENCE_BACKTEST: GateSeverity.SOFT,
    ValidationGateId.G5_OUT_OF_SAMPLE: GateSeverity.SOFT,
    ValidationGateId.G6_COST_STRESS: GateSeverity.SOFT,
    ValidationGateId.G7_PARAMETER_STABILITY: GateSeverity.SOFT,
    ValidationGateId.G8_SUBPERIOD_STABILITY: GateSeverity.SOFT,
    ValidationGateId.G9_REPRODUCIBILITY: GateSeverity.HARD,
    ValidationGateId.G10_ARTIFACT_INTEGRITY: GateSeverity.HARD,
}

_METRIC_GATE: Mapping[SoftMetric, ValidationGateId] = {
    SoftMetric.RANK_IC: ValidationGateId.G3_FACTOR_RESEARCH,
    SoftMetric.ICIR: ValidationGateId.G3_FACTOR_RESEARCH,
    SoftMetric.OOS_SHARPE: ValidationGateId.G5_OUT_OF_SAMPLE,
    SoftMetric.MAX_DRAWDOWN: ValidationGateId.G5_OUT_OF_SAMPLE,
    SoftMetric.ANNUALIZED_TURNOVER: ValidationGateId.G5_OUT_OF_SAMPLE,
    SoftMetric.ANNUALIZED_RETURN: ValidationGateId.G5_OUT_OF_SAMPLE,
    SoftMetric.COST_SENSITIVITY: ValidationGateId.G6_COST_STRESS,
    SoftMetric.PARAMETER_STABILITY: ValidationGateId.G7_PARAMETER_STABILITY,
    SoftMetric.SUBPERIOD_STABILITY: ValidationGateId.G8_SUBPERIOD_STABILITY,
}

_PARQUET_TABLES = (
    "order-indicators.parquet",
    "portfolio.parquet",
    "positions.parquet",
    "risk-metrics.parquet",
    "trade-indicators.parquet",
)
_QLIB_RISK_ANALYSIS = cast(Any, importlib.import_module("qlib.contrib.evaluate")).risk_analysis


class ValidationError(RuntimeError):
    """Published validation evidence is invalid or incomplete."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class _GateRejected(ValidationError):
    def __init__(
        self,
        reason_code: ReasonCode,
        message: str,
        evidence: tuple[ArtifactRef, ...],
    ) -> None:
        super().__init__(reason_code, message)
        self.evidence = evidence


class _ExecutionFailed(ValidationError):
    pass


@dataclass(frozen=True)
class ValidationBuildResult:
    reference: ArtifactRef
    report: ValidationReport
    path: Path


@dataclass(frozen=True)
class _Variant:
    locator: VariantArtifactLocator
    resolved: ResolvedExperimentSpec
    signal: SignalArtifactManifest
    backtest: BacktestArtifactManifest
    config: QlibBacktestConfig
    signal_ref: ArtifactRef
    backtest_ref: ArtifactRef


@dataclass(frozen=True)
class _MetricExtraction:
    observation_count: int
    metrics: tuple[ValidationMetric, ...]


@dataclass(frozen=True)
class _StageOutput:
    reason: str
    evidence: tuple[ArtifactRef, ...]
    metrics: tuple[ValidationMetric, ...] = ()
    robustness_cases: tuple[RobustnessCaseResult, ...] = ()
    reproducibility: ReproducibilityComparison | None = None


@dataclass
class _RunState:
    authoring: ExperimentAuthoringSpec
    validation_policy: ValidationPolicy
    research_policy: ResearchPolicy
    locators: ValidationRunLocators
    workspace: Path
    canonical: bool
    event_root: Path
    now: datetime
    event_id: UUID
    runtime_fingerprint: RuntimeFingerprint
    resolved: ResolvedExperimentSpec | None = None
    snapshot: DataSnapshotManifest | None = None
    view: QlibViewManifest | None = None
    signal: SignalArtifactManifest | None = None
    baseline: BacktestArtifactManifest | None = None
    baseline_config: QlibBacktestConfig | None = None
    snapshot_ref: ArtifactRef | None = None
    view_ref: ArtifactRef | None = None
    signal_ref: ArtifactRef | None = None
    baseline_ref: ArtifactRef | None = None
    all_evidence: dict[tuple[str, str], ArtifactRef] = field(
        default_factory=lambda: cast(dict[tuple[str, str], ArtifactRef], {})
    )
    summary_metrics: dict[SoftMetric, ValidationMetric] = field(
        default_factory=lambda: cast(dict[SoftMetric, ValidationMetric], {})
    )
    robustness_cases: list[RobustnessCaseResult] = field(
        default_factory=lambda: cast(list[RobustnessCaseResult], [])
    )
    reproducibility: ReproducibilityComparison | None = None
    oos_event: ArtifactRef | None = None

    def retain(self, references: Sequence[ArtifactRef]) -> None:
        for reference in references:
            self.all_evidence[(reference.kind, reference.sha256)] = reference


def _contract_ref(kind: str, contract: Any, logical_name: str) -> ArtifactRef:
    encoded = cast(bytes, contract.canonical_bytes())
    return ArtifactRef(
        kind=kind,
        sha256=cast(str, contract.content_hash),
        size_bytes=len(encoded),
        media_type="application/json",
        logical_path=f"contracts/sha256-{contract.content_hash}-{logical_name}.json",
    )


def _directory_ref(kind: str, digest: str, path: Path) -> ArtifactRef:
    try:
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError as error:
        raise _ExecutionFailed(
            ReasonCode.SOURCE_INCOMPLETE, "artifact directory is unreadable"
        ) from error
    return ArtifactRef(
        kind=kind,
        sha256=digest,
        size_bytes=size,
        media_type=f"application/vnd.quantos.{kind}+directory",
        logical_path=f"{kind}/sha256-{digest}",
    )


def _file_ref(kind: str, path: Path) -> ArtifactRef:
    try:
        digest = sha256_file(path)
        size = path.stat().st_size
    except OSError as error:
        raise _ExecutionFailed(
            ReasonCode.SOURCE_INCOMPLETE, "evidence file is unreadable"
        ) from error
    return ArtifactRef(
        kind=kind,
        sha256=digest,
        size_bytes=size,
        media_type="application/json",
        logical_path=f"{kind}/sha256-{digest}.json",
    )


def _safe_read_resolved(signal_path: Path) -> ResolvedExperimentSpec:
    try:
        return ResolvedExperimentSpec.model_validate_json(
            (signal_path / "resolved-experiment.json").read_bytes()
        )
    except (OSError, ValueError) as error:
        raise _GateRejected(
            ReasonCode.SCHEMA_INVALID,
            "resolved experiment cannot be loaded from the signal artifact",
            (),
        ) from error


def _safe_read_config(backtest_path: Path) -> QlibBacktestConfig:
    try:
        return QlibBacktestConfig.model_validate_json(
            (backtest_path / "backtest-config.json").read_bytes()
        )
    except (OSError, ValueError) as error:
        raise _GateRejected(
            ReasonCode.ARTIFACT_CORRUPTED,
            "backtest configuration cannot be loaded",
            (),
        ) from error


def _metric(
    metric: SoftMetric,
    value: float,
    source: ArtifactRef,
    detail: str,
) -> ValidationMetric | None:
    if not math.isfinite(value):
        return None
    return ValidationMetric(metric=metric, value=value, source=source, detail=detail)


def _risk_values(net_returns: pd.Series[float]) -> dict[str, float]:
    analysis = cast(pd.DataFrame, _QLIB_RISK_ANALYSIS(net_returns, freq="day"))
    if tuple(analysis.columns) != ("risk",):
        raise _ExecutionFailed(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib risk analysis interface does not match the locked contract",
        )
    values: dict[str, float] = {}
    for key in ("annualized_return", "information_ratio", "max_drawdown"):
        if key not in analysis.index:
            continue
        value = float(cast(Any, analysis.loc[key, "risk"]))
        if math.isfinite(value):
            values[key] = value
    return values


def _extract_metrics(
    backtest_path: Path,
    source: ArtifactRef,
    *,
    start: date,
    end: date,
    annualization_factor: int,
) -> _MetricExtraction:
    try:
        table = pq.read_table(backtest_path / "portfolio.parquet")  # pyright: ignore[reportUnknownMemberType]
        frame = table.to_pandas()  # pyright: ignore[reportUnknownMemberType]
    except (OSError, pa.ArrowException) as error:
        raise _GateRejected(
            ReasonCode.ARTIFACT_CORRUPTED,
            "portfolio evidence cannot be read for validation",
            (source,),
        ) from error
    required = {"trade_date", "return", "cost", "turnover"}
    if not required.issubset(frame.columns):
        raise _GateRejected(
            ReasonCode.ARTIFACT_CORRUPTED,
            "portfolio evidence lacks required Qlib result columns",
            (source,),
        )
    selected = frame.loc[
        frame["trade_date"].map(lambda value: start <= cast(date, value) <= end)
    ].copy()
    if selected.empty:
        return _MetricExtraction(0, ())
    selected = selected.sort_values("trade_date")
    net_returns = cast("pd.Series[float]", selected["return"] - selected["cost"])
    net_returns.index = pd.DatetimeIndex(selected["trade_date"])
    try:
        risk = _risk_values(net_returns)
    except _ExecutionFailed:
        raise
    except Exception as error:
        raise _ExecutionFailed(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib risk analysis failed during offline validation",
        ) from error
    metrics: list[ValidationMetric] = []
    candidates = (
        _metric(
            SoftMetric.OOS_SHARPE,
            risk.get("information_ratio", math.nan),
            source,
            "Qlib daily information_ratio for net strategy returns over the selected OOS rows",
        ),
        _metric(
            SoftMetric.MAX_DRAWDOWN,
            abs(risk.get("max_drawdown", math.nan)),
            source,
            "absolute Qlib max_drawdown for net strategy returns over the selected OOS rows",
        ),
        _metric(
            SoftMetric.ANNUALIZED_RETURN,
            risk.get("annualized_return", math.nan),
            source,
            "Qlib annualized_return for net strategy returns over the selected OOS rows",
        ),
        _metric(
            SoftMetric.ANNUALIZED_TURNOVER,
            float(cast("pd.Series[float]", selected["turnover"]).mean()) * annualization_factor,
            source,
            "mean Qlib daily turnover multiplied by the policy annualization factor",
        ),
    )
    metrics.extend(item for item in candidates if item is not None)
    return _MetricExtraction(len(selected), tuple(metrics))


def _threshold_failures(
    policy: ValidationPolicy,
    gate_id: ValidationGateId,
    metrics: Sequence[ValidationMetric],
) -> tuple[str, ...]:
    values = {item.metric: item.value for item in metrics}
    failures: list[str] = []
    for threshold in policy.soft_gates:
        if _METRIC_GATE[threshold.metric] is not gate_id:
            continue
        value = values.get(threshold.metric)
        if value is None:
            failures.append(f"{threshold.metric}:missing")
            continue
        passed = (
            value >= threshold.threshold
            if threshold.comparison is ThresholdComparison.MIN
            else value <= threshold.threshold
        )
        if not passed:
            failures.append(
                f"{threshold.metric}:{value:.17g}:{threshold.comparison}:{threshold.threshold:.17g}"
            )
    return tuple(failures)


def _same_baseline_bindings(base: ResolvedExperimentSpec, variant: ResolvedExperimentSpec) -> bool:
    return (
        variant.snapshot_hash == base.snapshot_hash
        and variant.qlib_view_hash == base.qlib_view_hash
        and variant.qlib_view_spec_hash == base.qlib_view_spec_hash
        and variant.qlib_version == base.qlib_version
        and variant.research_policy_hash == base.research_policy_hash
        and variant.validation_policy_hash == base.validation_policy_hash
        and variant.backtest_policy_hash == base.backtest_policy_hash
        and variant.code_commit_hash == base.code_commit_hash
        and variant.lockfile_hash == base.lockfile_hash
    )


def _compare_scalars(
    left: object,
    right: object,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[bool, bool, float]:
    if isinstance(left, float) or isinstance(right, float):
        try:
            left_number = float(cast(Any, left))
            right_number = float(cast(Any, right))
        except (TypeError, ValueError):
            return False, True, 0.0
        if math.isnan(left_number) and math.isnan(right_number):
            return True, True, 0.0
        error = abs(left_number - right_number)
        return (
            math.isclose(
                left_number,
                right_number,
                abs_tol=absolute_tolerance,
                rel_tol=relative_tolerance,
            ),
            True,
            error,
        )
    return left == right, False, 0.0


def compare_backtest_artifacts(
    left_path: Path,
    right_path: Path,
    left: BacktestArtifactManifest,
    right: BacktestArtifactManifest,
    left_ref: ArtifactRef,
    right_ref: ArtifactRef,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> ReproducibilityComparison:
    exact_hash = left.result_hash == right.result_hash
    manifest_bindings_match = left.model_dump(
        exclude={"result_hash", "files", "created_at"}
    ) == right.model_dump(exclude={"result_hash", "files", "created_at"})
    exact_checked = 0
    float_checked = 0
    max_error = 0.0
    passed = manifest_bindings_match
    for filename in _PARQUET_TABLES:
        try:
            left_rows = pq.read_table(left_path / filename).to_pylist()  # pyright: ignore[reportUnknownMemberType]
            right_rows = pq.read_table(right_path / filename).to_pylist()  # pyright: ignore[reportUnknownMemberType]
        except (OSError, pa.ArrowException) as error:
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "reproducibility tables cannot be read",
                (left_ref, right_ref),
            ) from error
        if len(left_rows) != len(right_rows):
            passed = False
            continue
        for left_row, right_row in zip(left_rows, right_rows, strict=True):
            if left_row.keys() != right_row.keys():
                passed = False
                continue
            for key in left_row:
                equal, is_float, error = _compare_scalars(
                    left_row[key],
                    right_row[key],
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                )
                if is_float:
                    float_checked += 1
                    max_error = max(max_error, error)
                else:
                    exact_checked += 1
                passed = passed and equal
    return ReproducibilityComparison(
        left=left_ref,
        right=right_ref,
        exact_content_hash=exact_hash,
        exact_fields_checked=exact_checked,
        float_fields_checked=float_checked,
        max_absolute_error=max_error,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        passed=passed,
        detail=(
            "backtest content hashes are byte-exact"
            if exact_hash
            else "manifest bindings and canonicalized result fields were compared"
        ),
    )


class ValidationService:
    """Consume immutable Qlib evidence and publish one deterministic ValidationReport."""

    def run(
        self,
        authoring: ExperimentAuthoringSpec,
        validation_policy: ValidationPolicy,
        research_policy: ResearchPolicy,
        locators: ValidationRunLocators,
        output_root: Path,
        event_root: Path,
        *,
        workspace: Path | None = None,
        canonical: bool = True,
        now: datetime | None = None,
        event_id: UUID | None = None,
    ) -> ValidationBuildResult:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        state = _RunState(
            authoring=authoring,
            validation_policy=validation_policy,
            research_policy=research_policy,
            locators=locators,
            workspace=workspace or Path.cwd(),
            canonical=canonical,
            event_root=event_root,
            now=timestamp,
            event_id=event_id or uuid4(),
            runtime_fingerprint=capture_runtime_fingerprint(),
        )
        stages = {
            ValidationGateId.G0_SCHEMA_REFERENCE: self._g0,
            ValidationGateId.G1_SNAPSHOT_DATA_QUALITY: self._g1,
            ValidationGateId.G2_PIT_LINEAGE: self._g2,
            ValidationGateId.G3_FACTOR_RESEARCH: self._g3,
            ValidationGateId.G4_REFERENCE_BACKTEST: self._g4,
            ValidationGateId.G5_OUT_OF_SAMPLE: self._g5,
            ValidationGateId.G6_COST_STRESS: self._g6,
            ValidationGateId.G7_PARAMETER_STABILITY: self._g7,
            ValidationGateId.G8_SUBPERIOD_STABILITY: self._g8,
            ValidationGateId.G9_REPRODUCIBILITY: self._g9,
            ValidationGateId.G10_ARTIFACT_INTEGRITY: self._g10,
        }
        results: list[GateResult] = []
        stopped = False
        run_status = RunStatus.SUCCEEDED
        for gate_id in VALIDATION_GATE_ORDER:
            if stopped:
                results.append(
                    GateResult(
                        gate_id=gate_id,
                        severity=_GATE_SEVERITY[gate_id],
                        verdict=ValidationVerdict.NOT_EVALUATED,
                        reason="not evaluated because a prior hard gate or execution failed",
                    )
                )
                continue
            try:
                output = stages[gate_id](state)
                state.retain(output.evidence)
                for metric in output.metrics:
                    state.summary_metrics[metric.metric] = metric
                state.robustness_cases.extend(output.robustness_cases)
                if output.reproducibility is not None:
                    state.reproducibility = output.reproducibility
                failures = _threshold_failures(validation_policy, gate_id, output.metrics)
                if failures:
                    raise _GateRejected(
                        ReasonCode.SOFT_THRESHOLD_NOT_MET,
                        "soft thresholds not met: " + ",".join(failures),
                        output.evidence,
                    )
                result = GateResult(
                    gate_id=gate_id,
                    severity=_GATE_SEVERITY[gate_id],
                    verdict=ValidationVerdict.PASS,
                    reason=output.reason,
                    evidence=output.evidence,
                )
            except _GateRejected as error:
                evidence = error.evidence or tuple(state.all_evidence.values())[:1]
                result = GateResult(
                    gate_id=gate_id,
                    severity=_GATE_SEVERITY[gate_id],
                    verdict=ValidationVerdict.REJECT,
                    reason_code=error.reason_code,
                    reason=str(error),
                    evidence=evidence,
                )
                state.retain(evidence)
                if _GATE_SEVERITY[gate_id] is GateSeverity.HARD:
                    stopped = True
            except _ExecutionFailed as error:
                result = GateResult(
                    gate_id=gate_id,
                    severity=_GATE_SEVERITY[gate_id],
                    verdict=ValidationVerdict.NOT_EVALUATED,
                    reason_code=error.reason_code,
                    reason=str(error),
                )
                run_status = RunStatus.FAILED
                stopped = True
            except Exception:
                result = GateResult(
                    gate_id=gate_id,
                    severity=_GATE_SEVERITY[gate_id],
                    verdict=ValidationVerdict.NOT_EVALUATED,
                    reason_code=ReasonCode.QLIB_EXECUTION_FAILED,
                    reason="unexpected deterministic validation execution failure",
                )
                run_status = RunStatus.FAILED
                stopped = True
            results.append(result)

        verdict = (
            ValidationVerdict.NOT_EVALUATED
            if run_status is RunStatus.FAILED
            else (
                ValidationVerdict.REJECT
                if any(item.verdict is ValidationVerdict.REJECT for item in results)
                else ValidationVerdict.PASS
            )
        )
        return self._publish(state, tuple(results), run_status, verdict, output_root)

    def _g0(self, state: _RunState) -> _StageOutput:
        evidence = (
            _contract_ref("authoring_spec", state.authoring, "authoring"),
            _contract_ref("validation_policy", state.validation_policy, "validation-policy"),
            _contract_ref("research_policy", state.research_policy, "research-policy"),
            _contract_ref("runtime_fingerprint", state.runtime_fingerprint, "runtime-fingerprint"),
        )
        if state.locators.signal_path is not None:
            try:
                state.resolved = _safe_read_resolved(state.locators.signal_path)
            except _GateRejected as error:
                raise _GateRejected(error.reason_code, str(error), evidence) from error
            resolved = state.resolved
            if (
                resolved.authoring_spec_hash != state.authoring.content_hash
                or resolved.validation_policy_hash != state.validation_policy.content_hash
                or resolved.research_policy_hash != state.research_policy.content_hash
            ):
                raise _GateRejected(
                    ReasonCode.SCHEMA_INVALID,
                    "resolved experiment does not bind the supplied authoring and policies",
                    evidence,
                )
            evidence = (*evidence, _contract_ref("resolved_experiment", resolved, "resolved"))
        return _StageOutput("strict schemas and immutable hash bindings resolved", evidence)

    def _g1(self, state: _RunState) -> _StageOutput:
        try:
            state.snapshot = verify_snapshot(state.locators.snapshot_path)
            state.view = verify_qlib_view(state.locators.qlib_view_path)
            quality = DataQualityReport.model_validate_json(
                (state.locators.snapshot_path / "quality-report.json").read_bytes()
            )
        except (SnapshotBuildError, QlibViewBuildError) as error:
            reason = error.reason_code
            raise _GateRejected(
                reason, str(error), tuple(state.all_evidence.values())[:1]
            ) from error
        except (OSError, ValueError) as error:
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "snapshot quality report cannot be loaded",
                tuple(state.all_evidence.values())[:1],
            ) from error
        if not quality.passed or quality.content_hash != state.snapshot.quality_report_hash:
            raise _GateRejected(
                ReasonCode.SOURCE_INCOMPLETE,
                "snapshot data-quality evidence did not pass or lost its manifest binding",
                tuple(state.all_evidence.values())[:1],
            )
        if (
            state.view.source_snapshot_hash != state.snapshot.snapshot_hash
            or (
                state.resolved is not None
                and state.resolved.snapshot_hash != state.snapshot.snapshot_hash
            )
            or (
                state.resolved is not None and state.resolved.qlib_view_hash != state.view.view_hash
            )
        ):
            raise _GateRejected(
                ReasonCode.SNAPSHOT_HASH_MISMATCH,
                "snapshot, Qlib view, and resolved experiment bindings disagree",
                tuple(state.all_evidence.values())[:1],
            )
        state.snapshot_ref = _directory_ref(
            "data_snapshot", state.snapshot.snapshot_hash, state.locators.snapshot_path
        )
        state.view_ref = _directory_ref(
            "qlib_view", state.view.view_hash, state.locators.qlib_view_path
        )
        return _StageOutput(
            "snapshot integrity, data quality, and derived Qlib view passed",
            (state.snapshot_ref, state.view_ref),
        )

    def _g2(self, state: _RunState) -> _StageOutput:
        if state.locators.pit_report_path is not None:
            reference = _file_ref("pit_audit_report", state.locators.pit_report_path)
            try:
                report = PITAuditReport.model_validate_json(
                    state.locators.pit_report_path.read_bytes()
                )
            except (OSError, ValueError) as error:
                raise _GateRejected(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "standalone PIT report is invalid",
                    (reference,),
                ) from error
            if reference.sha256 != report.content_hash:
                raise _GateRejected(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "standalone PIT report bytes do not match its canonical hash",
                    (reference,),
                )
            if (
                report.evidence_mode is not PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND
                or state.snapshot is None
                or report.snapshot_hash != state.snapshot.snapshot_hash
            ):
                raise _GateRejected(
                    ReasonCode.SNAPSHOT_HASH_MISMATCH,
                    "PIT report is not bound to the verified snapshot",
                    (reference,),
                )
            if report.verdict is ValidationVerdict.REJECT:
                failed = next(
                    item for item in report.gates if item.verdict is ValidationVerdict.REJECT
                )
                raise _GateRejected(
                    cast(ReasonCode, failed.reason_code),
                    f"PIT hard rejection: {failed.detail}",
                    (reference,),
                )
            return _StageOutput("standalone canonical PIT audit passed", (reference,))
        if state.locators.signal_path is None:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE,
                "neither standalone PIT evidence nor a signal artifact was supplied",
            )
        path = state.locators.signal_path / "pit-evidence.json"
        reference = _file_ref("pit_evidence_collection", path)
        try:
            evidence = load_pit_artifact_evidence(path)
        except (OSError, ValueError) as error:
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "PIT evidence collection is invalid",
                (reference,),
            ) from error
        if (
            state.resolved is None
            or evidence.content_hash != state.resolved.pit_audit_evidence_hash
            or (
                state.snapshot is not None
                and evidence.snapshot_hash != state.snapshot.snapshot_hash
            )
        ):
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "PIT evidence does not match the resolved experiment",
                (reference,),
            )
        if isinstance(evidence, PITCrossSectionEvidenceCollection):
            try:
                verify_compact_pit_evidence(
                    evidence,
                    state.locators.snapshot_path,
                    state.locators.qlib_view_path,
                )
            except QlibResearchError as error:
                raise _GateRejected(error.reason_code, str(error), (reference,)) from error
        return _StageOutput(
            "complete PIT and lineage evidence passed and compact proofs reproduced",
            (reference,),
        )

    def _g3(self, state: _RunState) -> _StageOutput:
        if state.locators.signal_path is None:
            raise _ExecutionFailed(ReasonCode.SOURCE_INCOMPLETE, "factor signal artifact is absent")
        try:
            state.signal = verify_signal_artifact(state.locators.signal_path)
        except QlibResearchError as error:
            if error.reason_code is ReasonCode.QLIB_EXECUTION_FAILED:
                raise _ExecutionFailed(error.reason_code, str(error)) from error
            raise _GateRejected(
                error.reason_code, str(error), tuple(state.all_evidence.values())[:1]
            ) from error
        if (
            state.resolved is None
            or state.signal.resolved_experiment_hash != state.resolved.content_hash
        ):
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "signal artifact does not bind the resolved experiment",
                tuple(state.all_evidence.values())[:1],
            )
        state.signal_ref = _directory_ref(
            "signal_artifact", state.signal.artifact_hash, state.locators.signal_path
        )
        requested = {
            item.metric
            for item in state.validation_policy.soft_gates
            if _METRIC_GATE[item.metric] is ValidationGateId.G3_FACTOR_RESEARCH
        }
        if requested:
            raise _GateRejected(
                ReasonCode.SOURCE_INCOMPLETE,
                "rank IC metrics require a verified Qlib ResearchResult artifact",
                (state.signal_ref,),
            )
        return _StageOutput(
            "Qlib factor SignalArtifact passed complete verification", (state.signal_ref,)
        )

    def _g4(self, state: _RunState) -> _StageOutput:
        if state.locators.baseline_backtest_path is None:
            raise _ExecutionFailed(ReasonCode.SOURCE_INCOMPLETE, "baseline Qlib backtest is absent")
        try:
            state.baseline = verify_backtest_artifact(state.locators.baseline_backtest_path)
        except QlibResearchError as error:
            if error.reason_code is ReasonCode.QLIB_EXECUTION_FAILED:
                raise _ExecutionFailed(error.reason_code, str(error)) from error
            raise _GateRejected(
                error.reason_code, str(error), tuple(state.all_evidence.values())[:1]
            ) from error
        state.baseline_config = _safe_read_config(state.locators.baseline_backtest_path)
        if (
            state.resolved is None
            or state.signal is None
            or state.baseline.resolved_experiment_hash != state.resolved.content_hash
            or state.baseline.signal_artifact_hash != state.signal.artifact_hash
        ):
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "baseline backtest does not bind the verified signal and experiment",
                tuple(state.all_evidence.values())[:1],
            )
        state.baseline_ref = _directory_ref(
            "backtest_result", state.baseline.result_hash, state.locators.baseline_backtest_path
        )
        return _StageOutput(
            "Qlib reference backtest and six reconciliations passed",
            (state.baseline_ref,),
        )

    def _g5(self, state: _RunState) -> _StageOutput:
        baseline_path = state.locators.baseline_backtest_path
        if baseline_path is None or state.baseline_ref is None or state.resolved is None:
            raise _ExecutionFailed(ReasonCode.SOURCE_INCOMPLETE, "OOS prerequisites are absent")
        extracted = _extract_metrics(
            baseline_path,
            state.baseline_ref,
            start=state.research_policy.test.start,
            end=state.research_policy.test.end,
            annualization_factor=state.validation_policy.annualization_factor,
        )
        event = ImmutableEvent(
            event_id=state.event_id,
            aggregate_id=state.authoring.experiment_id,
            event_type=EventType.OOS_ACCESSED,
            occurred_at=state.now,
            payload={
                "authoring_spec_hash": state.authoring.content_hash,
                "resolved_experiment_hash": state.resolved.content_hash,
                "research_policy_hash": state.research_policy.content_hash,
                "validation_policy_hash": state.validation_policy.content_hash,
                "backtest_result_hash": state.baseline_ref.sha256,
                "oos_start": state.research_policy.test.start.isoformat(),
                "oos_end": state.research_policy.test.end.isoformat(),
            },
        )
        state.oos_event = ImmutableEventWriter(state.event_root).append(event)
        if extracted.observation_count < state.validation_policy.minimum_oos_observations:
            raise _GateRejected(
                ReasonCode.OOS_POLICY_VIOLATION,
                "OOS result has fewer observations than the validation policy requires",
                (state.baseline_ref,),
            )
        return _StageOutput(
            f"evaluated {extracted.observation_count} frozen OOS observations",
            (state.baseline_ref,),
            metrics=extracted.metrics,
        )

    def _load_variant(self, locator: VariantArtifactLocator) -> _Variant:
        try:
            signal = verify_signal_artifact(locator.signal_path)
            backtest = verify_backtest_artifact(locator.backtest_path)
        except QlibResearchError as error:
            if error.reason_code is ReasonCode.QLIB_EXECUTION_FAILED:
                raise _ExecutionFailed(error.reason_code, str(error)) from error
            raise _GateRejected(error.reason_code, str(error), ()) from error
        resolved = _safe_read_resolved(locator.signal_path)
        config = _safe_read_config(locator.backtest_path)
        signal_ref = _directory_ref("signal_artifact", signal.artifact_hash, locator.signal_path)
        backtest_ref = _directory_ref(
            "backtest_result", backtest.result_hash, locator.backtest_path
        )
        if (
            signal.resolved_experiment_hash != resolved.content_hash
            or backtest.resolved_experiment_hash != resolved.content_hash
            or backtest.signal_artifact_hash != signal.artifact_hash
            or config.content_hash != backtest.backtest_config_hash
        ):
            raise _GateRejected(
                ReasonCode.ARTIFACT_CORRUPTED,
                "robustness variant artifacts are not hash-bound to each other",
                (signal_ref, backtest_ref),
            )
        return _Variant(
            locator,
            resolved,
            signal,
            backtest,
            config,
            signal_ref,
            backtest_ref,
        )

    def _g6(self, state: _RunState) -> _StageOutput:
        expected = state.validation_policy.cost_stress_multipliers
        supplied = tuple(sorted(item.multiplier for item in state.locators.cost_stress))
        if supplied != expected:
            raise _GateRejected(
                ReasonCode.SOURCE_INCOMPLETE,
                "cost stress evidence must contain the complete 1.0x/1.5x/2.0x grid",
                (cast(ArtifactRef, state.baseline_ref),),
            )
        if state.resolved is None or state.baseline_config is None:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE, "cost stress prerequisites are absent"
            )
        cases: list[RobustnessCaseResult] = []
        returns: dict[float, float] = {}
        evidence: list[ArtifactRef] = []
        for locator in sorted(state.locators.cost_stress, key=lambda item: item.multiplier):
            variant = self._load_variant(locator)
            evidence.extend((variant.signal_ref, variant.backtest_ref))
            if (
                not _same_baseline_bindings(state.resolved, variant.resolved)
                or variant.resolved.authoring_spec_hash != state.resolved.authoring_spec_hash
                or variant.resolved.expression != state.resolved.expression
                or variant.resolved.strategy != state.resolved.strategy
                or state.signal is None
                or variant.signal.signal_content_hash != state.signal.signal_content_hash
            ):
                raise _GateRejected(
                    ReasonCode.SCHEMA_INVALID,
                    "cost stress changed a non-cost experiment binding",
                    (variant.signal_ref, variant.backtest_ref),
                )
            multiplier = locator.multiplier
            baseline = state.baseline_config
            if not all(
                math.isclose(actual, original * multiplier, abs_tol=1e-12, rel_tol=1e-9)
                for actual, original in (
                    (variant.config.open_cost_rate, baseline.open_cost_rate),
                    (variant.config.close_cost_rate, baseline.close_cost_rate),
                    (variant.config.minimum_cost_cny, baseline.minimum_cost_cny),
                )
            ):
                raise _GateRejected(
                    ReasonCode.SCHEMA_INVALID,
                    "cost stress Qlib configuration does not match its multiplier",
                    (variant.backtest_ref,),
                )
            extracted = _extract_metrics(
                locator.backtest_path,
                variant.backtest_ref,
                start=state.research_policy.test.start,
                end=state.research_policy.test.end,
                annualization_factor=state.validation_policy.annualization_factor,
            )
            if extracted.observation_count < state.validation_policy.minimum_oos_observations:
                raise _GateRejected(
                    ReasonCode.SOURCE_INCOMPLETE,
                    f"cost stress {multiplier:.1f}x has too few OOS observations",
                    (variant.backtest_ref,),
                )
            annual_return = next(
                (
                    item.value
                    for item in extracted.metrics
                    if item.metric is SoftMetric.ANNUALIZED_RETURN
                ),
                math.nan,
            )
            if math.isfinite(annual_return):
                returns[multiplier] = annual_return
            cases.append(
                RobustnessCaseResult(
                    kind=RobustnessKind.COST_STRESS,
                    case_id=f"cost-{multiplier:.1f}x",
                    dimensions=(f"cost_multiplier={multiplier:.1f}",),
                    observation_count=extracted.observation_count,
                    metrics=extracted.metrics,
                    evidence=(variant.signal_ref, variant.backtest_ref),
                )
            )
        if set(returns) != set(expected):
            aggregate_metrics: tuple[ValidationMetric, ...] = ()
        else:
            sensitivity = returns[1.0] - min(returns[1.5], returns[2.0])
            aggregate = _metric(
                SoftMetric.COST_SENSITIVITY,
                sensitivity,
                cast(ArtifactRef, state.baseline_ref),
                "baseline annualized return minus the worst stressed-cost annualized return",
            )
            aggregate_metrics = () if aggregate is None else (aggregate,)
        return _StageOutput(
            "complete cost stress grid was executed by Qlib",
            tuple(evidence),
            metrics=aggregate_metrics,
            robustness_cases=tuple(cases),
        )

    def _g7(self, state: _RunState) -> _StageOutput:
        expected = {
            (window, top_k)
            for window in state.validation_policy.parameter_windows
            for top_k in state.validation_policy.parameter_top_k
        }
        supplied = {(item.window, item.top_k) for item in state.locators.parameter_stability}
        if supplied != expected:
            raise _GateRejected(
                ReasonCode.SOURCE_INCOMPLETE,
                "parameter stability evidence does not contain the complete perturbation grid",
                (cast(ArtifactRef, state.baseline_ref),),
            )
        if state.resolved is None:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE, "parameter stability prerequisites are absent"
            )
        cases: list[RobustnessCaseResult] = []
        returns: list[float] = []
        evidence: list[ArtifactRef] = []
        for locator in sorted(
            state.locators.parameter_stability, key=lambda item: (item.window, item.top_k)
        ):
            variant = self._load_variant(locator)
            evidence.extend((variant.signal_ref, variant.backtest_ref))
            output_node = next(
                node
                for node in variant.resolved.expression.nodes
                if node.node_id == variant.resolved.expression.output_node_id
            )
            if (
                not _same_baseline_bindings(state.resolved, variant.resolved)
                or variant.resolved.cost_policy_hash != state.resolved.cost_policy_hash
                or output_node.window != locator.window
                or variant.resolved.strategy.top_k != locator.top_k
                or variant.resolved.evaluation_start != state.resolved.evaluation_start
                or variant.resolved.evaluation_end != state.resolved.evaluation_end
                or state.baseline_config is None
                or variant.config.open_cost_rate != state.baseline_config.open_cost_rate
                or variant.config.close_cost_rate != state.baseline_config.close_cost_rate
                or variant.config.minimum_cost_cny != state.baseline_config.minimum_cost_cny
            ):
                raise _GateRejected(
                    ReasonCode.SCHEMA_INVALID,
                    "parameter variant does not match its declared perturbation",
                    (variant.signal_ref, variant.backtest_ref),
                )
            extracted = _extract_metrics(
                locator.backtest_path,
                variant.backtest_ref,
                start=state.research_policy.test.start,
                end=state.research_policy.test.end,
                annualization_factor=state.validation_policy.annualization_factor,
            )
            if extracted.observation_count < state.validation_policy.minimum_oos_observations:
                raise _GateRejected(
                    ReasonCode.SOURCE_INCOMPLETE,
                    f"parameter case {locator.window}/{locator.top_k} has too few OOS observations",
                    (variant.backtest_ref,),
                )
            returns.extend(
                item.value
                for item in extracted.metrics
                if item.metric is SoftMetric.ANNUALIZED_RETURN
            )
            cases.append(
                RobustnessCaseResult(
                    kind=RobustnessKind.PARAMETER_STABILITY,
                    case_id=f"window-{locator.window}-topk-{locator.top_k}",
                    dimensions=(f"top_k={locator.top_k}", f"window={locator.window}"),
                    observation_count=extracted.observation_count,
                    metrics=extracted.metrics,
                    evidence=(variant.signal_ref, variant.backtest_ref),
                )
            )
        stability = (
            len([value for value in returns if value >= 0]) / len(returns) if returns else math.nan
        )
        aggregate = _metric(
            SoftMetric.PARAMETER_STABILITY,
            stability,
            cast(ArtifactRef, state.baseline_ref),
            "fraction of complete perturbation cases with nonnegative Qlib annualized return",
        )
        return _StageOutput(
            "complete momentum-window and top-k perturbation grid was evaluated",
            tuple(evidence),
            metrics=() if aggregate is None else (aggregate,),
            robustness_cases=tuple(cases),
        )

    def _g8(self, state: _RunState) -> _StageOutput:
        expected = {
            item.period_id: (item.start, item.end) for item in state.validation_policy.subperiods
        }
        supplied = {item.period_id: (item.start, item.end) for item in state.locators.subperiods}
        if supplied != expected:
            raise _GateRejected(
                ReasonCode.SOURCE_INCOMPLETE,
                "subperiod evidence does not match the complete policy periods",
                (cast(ArtifactRef, state.baseline_ref),),
            )
        if state.resolved is None:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE, "subperiod prerequisites are absent"
            )
        cases: list[RobustnessCaseResult] = []
        returns: list[float] = []
        evidence: list[ArtifactRef] = []
        for locator in sorted(state.locators.subperiods, key=lambda item: item.period_id):
            variant = self._load_variant(locator)
            evidence.extend((variant.signal_ref, variant.backtest_ref))
            if (
                not _same_baseline_bindings(state.resolved, variant.resolved)
                or variant.resolved.cost_policy_hash != state.resolved.cost_policy_hash
                or variant.resolved.expression != state.resolved.expression
                or variant.resolved.strategy != state.resolved.strategy
                or variant.resolved.evaluation_start != locator.start
                or variant.resolved.evaluation_end != locator.end
                or variant.backtest.start_date < locator.start
                or variant.backtest.end_date > locator.end
                or state.baseline_config is None
                or variant.config.open_cost_rate != state.baseline_config.open_cost_rate
                or variant.config.close_cost_rate != state.baseline_config.close_cost_rate
                or variant.config.minimum_cost_cny != state.baseline_config.minimum_cost_cny
            ):
                raise _GateRejected(
                    ReasonCode.SCHEMA_INVALID,
                    "subperiod artifacts do not match their frozen period",
                    (variant.signal_ref, variant.backtest_ref),
                )
            extracted = _extract_metrics(
                locator.backtest_path,
                variant.backtest_ref,
                start=locator.start,
                end=locator.end,
                annualization_factor=state.validation_policy.annualization_factor,
            )
            if extracted.observation_count < state.validation_policy.minimum_subperiod_observations:
                raise _GateRejected(
                    ReasonCode.SOURCE_INCOMPLETE,
                    f"subperiod {locator.period_id} has too few observations",
                    (variant.backtest_ref,),
                )
            returns.extend(
                item.value
                for item in extracted.metrics
                if item.metric is SoftMetric.ANNUALIZED_RETURN
            )
            cases.append(
                RobustnessCaseResult(
                    kind=RobustnessKind.SUBPERIOD,
                    case_id=locator.period_id,
                    dimensions=(f"end={locator.end}", f"start={locator.start}"),
                    observation_count=extracted.observation_count,
                    metrics=extracted.metrics,
                    evidence=(variant.signal_ref, variant.backtest_ref),
                )
            )
        stability = (
            len([value for value in returns if value >= 0]) / len(returns) if returns else math.nan
        )
        aggregate = _metric(
            SoftMetric.SUBPERIOD_STABILITY,
            stability,
            cast(ArtifactRef, state.baseline_ref),
            "fraction of frozen subperiods with nonnegative Qlib annualized return",
        )
        return _StageOutput(
            "all frozen subperiods met their minimum observation counts",
            tuple(evidence),
            metrics=() if aggregate is None else (aggregate,),
            robustness_cases=tuple(cases),
        )

    def _g9(self, state: _RunState) -> _StageOutput:
        reproduction_path = state.locators.reproduction_backtest_path
        baseline_path = state.locators.baseline_backtest_path
        if reproduction_path is None or baseline_path is None or state.baseline is None:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE, "independent reproduction artifact is absent"
            )
        if state.canonical:
            if state.resolved is None:
                raise _ExecutionFailed(
                    ReasonCode.SOURCE_INCOMPLETE, "resolved provenance binding is absent"
                )
            try:
                verify_code_provenance(
                    state.workspace,
                    expected_commit_hash=state.resolved.code_commit_hash,
                    expected_lockfile_hash=state.resolved.lockfile_hash,
                )
            except ProvenanceError as error:
                raise _GateRejected(
                    error.reason_code, str(error), (cast(ArtifactRef, state.baseline_ref),)
                ) from error
        try:
            reproduced = verify_backtest_artifact(reproduction_path)
        except QlibResearchError as error:
            raise _GateRejected(
                error.reason_code, str(error), (cast(ArtifactRef, state.baseline_ref),)
            ) from error
        reproduced_ref = _directory_ref(
            "backtest_result", reproduced.result_hash, reproduction_path
        )
        comparison = compare_backtest_artifacts(
            baseline_path,
            reproduction_path,
            state.baseline,
            reproduced,
            cast(ArtifactRef, state.baseline_ref),
            reproduced_ref,
            absolute_tolerance=state.validation_policy.reproducibility_absolute_tolerance,
            relative_tolerance=state.validation_policy.reproducibility_relative_tolerance,
        )
        if not comparison.passed:
            raise _GateRejected(
                ReasonCode.REPRODUCIBILITY_MISMATCH,
                "independent backtest reproduction exceeds the frozen comparison tolerances",
                (cast(ArtifactRef, state.baseline_ref), reproduced_ref),
            )
        return _StageOutput(
            "independent backtest reproduction matched within policy tolerances",
            (cast(ArtifactRef, state.baseline_ref), reproduced_ref),
            reproducibility=comparison,
        )

    def _g10(self, state: _RunState) -> _StageOutput:
        references = tuple(
            sorted(state.all_evidence.values(), key=lambda item: (item.kind, item.sha256))
        )
        if not references:
            raise _ExecutionFailed(
                ReasonCode.SOURCE_INCOMPLETE, "no immutable evidence was retained"
            )
        try:
            if state.snapshot is not None:
                verify_snapshot(state.locators.snapshot_path)
            if state.view is not None:
                verify_qlib_view(state.locators.qlib_view_path)
            if state.signal is not None and state.locators.signal_path is not None:
                verify_signal_artifact(state.locators.signal_path)
            if state.baseline is not None and state.locators.baseline_backtest_path is not None:
                verify_backtest_artifact(state.locators.baseline_backtest_path)
            if state.locators.reproduction_backtest_path is not None:
                verify_backtest_artifact(state.locators.reproduction_backtest_path)
            for locator in (
                *state.locators.cost_stress,
                *state.locators.parameter_stability,
                *state.locators.subperiods,
            ):
                self._load_variant(locator)
            if state.oos_event is not None:
                ImmutableEventWriter(state.event_root).read(state.oos_event)
            if state.locators.pit_report_path is not None:
                reference = _file_ref("pit_audit_report", state.locators.pit_report_path)
                verify_file(state.locators.pit_report_path, reference.sha256)
        except (SnapshotBuildError, QlibViewBuildError, QlibResearchError) as error:
            reason = error.reason_code
            raise _GateRejected(reason, str(error), references) from error
        return _StageOutput("all retained immutable input artifacts re-verified", references)

    def _publish(
        self,
        state: _RunState,
        gates: tuple[GateResult, ...],
        run_status: RunStatus,
        verdict: ValidationVerdict,
        output_root: Path,
    ) -> ValidationBuildResult:
        authoring_bytes = state.authoring.canonical_bytes()
        research_bytes = state.research_policy.canonical_bytes()
        validation_bytes = state.validation_policy.canonical_bytes()
        runtime_bytes = state.runtime_fingerprint.canonical_bytes()
        files = (
            ValidationArtifactFile(
                logical_path="authoring-spec.json",
                sha256=state.authoring.content_hash,
                size_bytes=len(authoring_bytes),
            ),
            ValidationArtifactFile(
                logical_path="research-policy.json",
                sha256=state.research_policy.content_hash,
                size_bytes=len(research_bytes),
            ),
            ValidationArtifactFile(
                logical_path="runtime-fingerprint.json",
                sha256=state.runtime_fingerprint.content_hash,
                size_bytes=len(runtime_bytes),
            ),
            ValidationArtifactFile(
                logical_path="validation-policy.json",
                sha256=state.validation_policy.content_hash,
                size_bytes=len(validation_bytes),
            ),
        )
        report = ValidationReport.create(
            experiment_id=state.authoring.experiment_id,
            authoring_spec_hash=state.authoring.content_hash,
            resolved_experiment_hash=(
                state.resolved.content_hash if state.resolved is not None else None
            ),
            validation_policy_hash=state.validation_policy.content_hash,
            research_policy_hash=state.research_policy.content_hash,
            runtime_fingerprint_hash=state.runtime_fingerprint.content_hash,
            snapshot_hash=state.snapshot.snapshot_hash if state.snapshot is not None else None,
            qlib_view_hash=state.view.view_hash if state.view is not None else None,
            signal_artifact_hash=(state.signal.artifact_hash if state.signal is not None else None),
            backtest_result_hash=(
                state.baseline.result_hash if state.baseline is not None else None
            ),
            run_status=run_status,
            verdict=verdict,
            canonical=state.canonical,
            gates=gates,
            metrics=tuple(
                state.summary_metrics[key] for key in sorted(state.summary_metrics, key=str)
            ),
            robustness_cases=tuple(state.robustness_cases),
            reproducibility=state.reproducibility,
            oos_access_event=state.oos_event,
            files=files,
            created_at=state.now,
        )
        output_root.mkdir(parents=True, exist_ok=True)
        destination = output_root / f"sha256-{report.report_hash}"
        if not destination.exists():
            with tempfile.TemporaryDirectory(
                prefix=".validation-work-", dir=output_root
            ) as temporary:
                staging = Path(temporary) / "validation"
                staging.mkdir()
                atomic_write_bytes(staging / "authoring-spec.json", authoring_bytes)
                atomic_write_bytes(staging / "research-policy.json", research_bytes)
                atomic_write_bytes(staging / "runtime-fingerprint.json", runtime_bytes)
                atomic_write_bytes(staging / "validation-policy.json", validation_bytes)
                atomic_write_bytes(
                    staging / "report.json",
                    canonical_json_bytes(report.model_dump(mode="python")),
                )
                publish_directory(staging, destination)
        published = verify_validation_report(destination)
        size = sum(item.stat().st_size for item in destination.rglob("*") if item.is_file())
        return ValidationBuildResult(
            reference=ArtifactRef(
                kind="validation_report",
                sha256=published.report_hash,
                size_bytes=size,
                media_type="application/vnd.quantos.validation+directory",
                logical_path=f"validation/sha256-{published.report_hash}",
            ),
            report=published,
            path=destination,
        )


def verify_validation_report(path: Path) -> ValidationReport:
    try:
        report_bytes = (path / "report.json").read_bytes()
        report = ValidationReport.model_validate_json(report_bytes)
    except (OSError, ValueError) as error:
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED, "validation report is invalid"
        ) from error
    if report_bytes != canonical_json_bytes(report.model_dump(mode="python")):
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "validation report bytes are not canonical",
        )
    if path.name != f"sha256-{report.report_hash}":
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "validation directory does not match the report hash",
        )
    expected = {item.logical_path for item in report.files} | {"report.json"}
    actual = {item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()}
    if actual != expected:
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "validation artifact file set does not match the report",
        )
    for item in report.files:
        try:
            verify_file(path / item.logical_path, item.sha256)
        except (OSError, ArtifactIntegrityError) as error:
            raise ValidationError(
                ReasonCode.ARTIFACT_CORRUPTED,
                f"validation input failed verification: {item.logical_path}",
            ) from error
    try:
        authoring = ExperimentAuthoringSpec.model_validate_json(
            (path / "authoring-spec.json").read_bytes()
        )
        research = ResearchPolicy.model_validate_json((path / "research-policy.json").read_bytes())
        runtime = RuntimeFingerprint.model_validate_json(
            (path / "runtime-fingerprint.json").read_bytes()
        )
        policy = ValidationPolicy.model_validate_json(
            (path / "validation-policy.json").read_bytes()
        )
    except (OSError, ValueError) as error:
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "validation artifact contracts cannot be loaded",
        ) from error
    if (
        authoring.content_hash != report.authoring_spec_hash
        or research.content_hash != report.research_policy_hash
        or runtime.content_hash != report.runtime_fingerprint_hash
        or policy.content_hash != report.validation_policy_hash
    ):
        raise ValidationError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "validation report contract bindings are inconsistent",
        )
    try:
        validate_runtime_fingerprint_binding(report, runtime)
    except ValueError as error:
        raise ValidationError(ReasonCode.ARTIFACT_CORRUPTED, str(error)) from error
    return report
