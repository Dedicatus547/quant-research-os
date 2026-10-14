"""Controlled successor import and read-only comparison of untouched Qlib predictions.

The original execution may have failed at export. No model, factor, portfolio,
Validation, Registry or LLM call is made here. Existing data/PIT verifiers retain
hard rejection; native statistics are reproduced with Qlib's own evaluator.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import platform
import re
import tempfile
import warnings
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time
from importlib.metadata import version
from pathlib import Path
from typing import TypeVar, cast
from zoneinfo import ZoneInfo

import pandas as pd

from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
    build_autonomous_execution_bindings,
    field_study_pit_policy_hash,
    require_durable_execution_root,
)
from quantos.application.provenance import capture_runtime_fingerprint, verify_code_provenance
from quantos.artifacts.store import (
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
    sha256_file,
)
from quantos.contracts.autonomous import AutonomousExecutionRequest, AutonomousExecutionResult
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryDesignReader
from quantos.contracts.discovery_prediction import (
    PREDICTION_RULE_HASH,
    PREDICTION_RULE_SPEC,
    PredictionDay,
    PredictionEvaluationProfile,
    PredictionEvidence,
    PredictionEvidenceManifest,
    PredictionFileSource,
    PredictionImportSource,
    PredictionStatistic,
)
from quantos.contracts.field_study import FrozenFieldStudyConfiguration, expression_identity
from quantos.contracts.pit import PITGateId, SafeQlibExpressionSpec
from quantos.contracts.refs import validate_logical_path
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
)
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceCollection,
    PITCrossSectionEvidenceCollectionV3,
)
from quantos.contracts.snapshot import DataQualityReport
from quantos.contracts.status import ValidationVerdict
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.research.qlib.model_split import verify_model_data_split
from quantos.research.qlib.pit_evidence import (
    build_pit_evidence_collection,
    load_pit_artifact_evidence,
    verify_compact_pit_evidence,
)
from quantos.research.qlib.signal import verify_signal_artifact
from quantos.research.qlib.universe import resolve_historical_universe_spans

_RULE = "finite-pair-constant-null-common-rank-ic/v1"
_META_CAP = 16 << 20
_NATIVE_CAP = 256 << 20
_Model = TypeVar("_Model", bound=CanonicalContract)
_QlibIC = Callable[[pd.Series, pd.Series], tuple[pd.Series, pd.Series]]

_PIT_VERIFICATION_FACTS: ContextVar[set[str] | None] = ContextVar(
    "prediction_pit_verification_facts", default=None
)


@contextmanager
def prediction_pit_verification_scope() -> Generator[None, None, None]:
    """Reuse successful PIT reproduction only within one controlled operation.

    Original file hashes and bindings still verify on every import/comparison.
    No parsed market data, failures, or facts survive the outermost scope.
    """
    if _PIT_VERIFICATION_FACTS.get() is not None:
        yield
        return
    token = _PIT_VERIFICATION_FACTS.set(set())
    try:
        yield
    finally:
        _PIT_VERIFICATION_FACTS.reset(token)


@dataclass(frozen=True)
class _AuthoringContext:
    """The original pure authoring method reads this single frozen attribute."""

    base_authoring: ExperimentAuthoringSpec


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _safe_path(value: str | Path, *, directory: bool = False) -> Path:
    path = Path(value).absolute()
    _require(not any(item.is_symlink() for item in (path, *path.parents)), "UNSAFE_SOURCE_PATH")
    _require(path.is_dir() if directory else path.is_file(), "SOURCE_MISSING")
    _require(path.resolve() == path, "SOURCE_PATH_NOT_CANONICAL")
    return path


def _raw_json(reference: PredictionFileSource) -> dict[str, object]:
    path = _safe_path(reference.path)
    _require(path.stat().st_size <= _META_CAP, "SOURCE_METADATA_LIMIT")
    raw = path.read_bytes()
    _require(sha256_bytes(raw) == reference.sha256, "SOURCE_HASH_MISMATCH")
    payload: object = json.loads(raw)
    _require(isinstance(payload, dict), "SOURCE_METADATA_OBJECT_REQUIRED")
    value = cast(dict[str, object], payload)
    _require(canonical_json_bytes(value) == raw, "SOURCE_METADATA_NOT_CANONICAL")
    return value


def _contract(reference: PredictionFileSource, model: type[_Model]) -> _Model:
    value = model.model_validate(_raw_json(reference))
    _require(value.content_hash == reference.sha256, "SOURCE_CONTRACT_HASH_MISMATCH")
    return value


def _research_policy(reference: PredictionFileSource) -> ResearchPolicy:
    """Adopt the original frozen design's policy without inventing a historical file."""
    payload = _raw_json(reference)
    schema = payload.get("schema_version")
    if schema == "frozen-field-study-config/v1":
        return FrozenFieldStudyConfiguration.model_validate(payload).research_policy
    if schema == "research-policy/v1":
        return ResearchPolicy.model_validate(payload)
    if schema in ("discovery-design/v1", "discovery-design/v3"):
        return DiscoveryDesignReader.model_validate(payload).research_policy
    if schema == "discovery-sequential-batch/v2":
        batch = payload.get("batch")
        _require(isinstance(batch, dict), "FROZEN_RESEARCH_POLICY_MISSING")
        payload = cast(dict[str, object], batch)
        schema = payload.get("schema_version")
    if schema == "discovery-batch/v1":
        value = payload.get("design")
        _require(isinstance(value, dict), "FROZEN_RESEARCH_POLICY_MISSING")
        return DiscoveryDesignReader.model_validate(value).research_policy
    raise ValueError("FROZEN_RESEARCH_POLICY_CONTAINER_UNSUPPORTED")


def prediction_verifier_identity() -> dict[str, object]:
    """Bind actual adapter, contract and reused verifier bytes, plus numeric runtime.

    Schema-bearing contracts and the packages used by reused data/PIT verifiers
    are conservative dependency sets. This identity is separate from source04.
    """
    package = Path(__file__).resolve().parents[1]
    roots = ("contracts", "artifacts", "data", "research/qlib", "integrations/qlib")
    paths = {path for name in roots for path in (package / name).rglob("*.py")}
    paths.update(
        package / name
        for name in (
            "__init__.py",
            "application/__init__.py",
            "application/autonomous_execution.py",
            "application/field_study.py",
            "application/provenance.py",
            "application/pit.py",
            "application/discovery_prediction.py",
            "application/discovery_prediction_adoption.py",
            "integrations/__init__.py",
        )
        if (package / name).is_file()
    )
    external: list[dict[str, str]] = []
    for name in (
        "qlib.contrib.eva.alpha",
        "pandas.core.nanops",
        "pandas.core.series",
        "scipy.stats._stats_py",
    ):
        module = importlib.import_module(name)
        _require(module.__file__ is not None, "VERIFIER_DEPENDENCY_SOURCE_UNAVAILABLE")
        external.append({"module": name, "sha256": sha256_file(Path(cast(str, module.__file__)))})
    return {
        "schema_version": "prediction-verifier-identity/v1",
        "rule_id": _RULE,
        "rule_hash": PREDICTION_RULE_HASH,
        "rule_spec": PREDICTION_RULE_SPEC,
        "dependencies": [
            {"logical_path": str(path.relative_to(package)), "sha256": sha256_file(path)}
            for path in sorted(paths)
        ],
        "external_dependencies": external,
        "python_version": platform.python_version(),
        "packages": {
            name: version(name)
            for name in ("pyqlib", "numpy", "pandas", "scipy", "pyarrow", "pydantic")
        },
    }


def _verify_source_code(
    source: PredictionImportSource, request: AutonomousExecutionRequest
) -> None:
    capsule = _raw_json(source.source_capsule)
    inventory = _raw_json(source.source_inventory)
    workspace = _safe_path(source.source_workspace, directory=True)
    _require(
        capsule.get("actual_commit") == request.code_commit_hash
        and capsule.get("lockfile_hash") == request.lockfile_hash
        and capsule.get("source_inventory_hash") == source.source_inventory.sha256
        and capsule.get("workspace") == str(workspace),
        "ORIGINAL_SOURCE_CAPSULE_BINDING_MISMATCH",
    )
    verify_code_provenance(
        workspace,
        expected_commit_hash=request.code_commit_hash,
        expected_lockfile_hash=request.lockfile_hash,
    )
    files_value = inventory.get("files")
    _require(isinstance(files_value, list), "ORIGINAL_SOURCE_INVENTORY_MISSING")
    files = cast(list[dict[str, object]], files_value)
    _require(bool(files), "ORIGINAL_SOURCE_INVENTORY_MISSING")
    seen: set[str] = set()
    for item in files:
        logical = validate_logical_path(str(item["path"]))
        _require(logical not in seen, "ORIGINAL_SOURCE_INVENTORY_DUPLICATE")
        seen.add(logical)
        path = _safe_path(workspace / logical)
        _require(
            path.stat().st_size == item["size_bytes"] and sha256_file(path) == item["bytes_hash"],
            "ORIGINAL_SOURCE_INVENTORY_HASH_MISMATCH",
        )


def _verify_pit(
    source: PredictionImportSource,
    request: AutonomousExecutionRequest,
    resolved: ResolvedExperimentSpec,
    *,
    _verified_data_identity: tuple[str, str, str] | None = None,
) -> str:
    signal_path = _safe_path(source.signal_path, directory=True)
    signal = verify_signal_artifact(signal_path)
    evidence = load_pit_artifact_evidence(signal_path / "pit-evidence.json")
    _require(
        signal.artifact_hash == source.signal_hash
        and signal.resolved_experiment_hash == resolved.content_hash
        and signal.snapshot_hash == request.snapshot_hash
        and signal.qlib_view_hash == request.qlib_view_hash
        and signal.source_expression_or_model_hash == request.candidate.expression.content_hash
        and evidence.content_hash == resolved.pit_audit_evidence_hash
        and evidence.snapshot_hash == request.snapshot_hash
        and evidence.expression_spec_hash == request.candidate.expression.content_hash
        and evidence.universe_index == resolved.strategy.universe_index,
        "PIT_BINDING_MISMATCH",
    )
    snapshot_path, view_path = Path(source.snapshot_path), Path(source.qlib_view_path)
    # The sole production caller supplies identities only after its unconditional
    # full snapshot/view file verification. Direct private calls remain strict too.
    if _verified_data_identity is None:
        snapshot, view = verify_snapshot(snapshot_path), verify_qlib_view(view_path)
        _verified_data_identity = (snapshot.snapshot_hash, view.view_hash, view.view_spec_hash)
    _require(
        _verified_data_identity
        == (request.snapshot_hash, request.qlib_view_hash, resolved.qlib_view_spec_hash),
        "PIT_DATA_BINDING_MISMATCH",
    )
    fact_key = sha256_bytes(
        canonical_json_bytes(
            {
                "source": source.content_hash,
                "request": request.content_hash,
                "resolved": resolved.content_hash,
                "signal": signal.artifact_hash,
                "evidence": evidence.content_hash,
                "expression": request.candidate.expression.content_hash,
                "snapshot_path": str(snapshot_path.absolute()),
                "view_path": str(view_path.absolute()),
                "verified_data": _verified_data_identity,
            }
        )
    )
    facts = _PIT_VERIFICATION_FACTS.get()
    already_reproduced = facts is not None and fact_key in facts
    if isinstance(
        evidence, (PITCrossSectionEvidenceCollection, PITCrossSectionEvidenceCollectionV3)
    ):
        _require(
            isinstance(evidence, PITCrossSectionEvidenceCollectionV3)
            == (getattr(request, "pit_policy_hash", None) == field_study_pit_policy_hash()),
            "PIT_EXECUTION_PROFILE_MISMATCH",
        )
        if not already_reproduced:
            verify_compact_pit_evidence(evidence, snapshot_path, view_path)
        gate_sets = [bundle.gates for bundle in evidence.bundles]
    else:
        first = evidence.bundles[0].items[0].request
        rebuilt = (
            evidence
            if already_reproduced
            else build_pit_evidence_collection(
                snapshot_path,
                view_path,
                expected_snapshot_hash=request.snapshot_hash,
                expected_view_hash=request.qlib_view_hash,
                universe_index=evidence.universe_index,
                expression=request.candidate.expression,
                operator_delays=first.operator_delays,
                schedules=tuple(bundle.schedule for bundle in evidence.bundles),
            )
        )
        _require(rebuilt == evidence, "PIT_SOURCE_REPRODUCTION_MISMATCH")
        gate_sets = [item.report.gates for bundle in evidence.bundles for item in bundle.items]
    _require(
        all(
            tuple(gate.gate_id for gate in gates) == tuple(PITGateId)
            and all(gate.verdict is ValidationVerdict.PASS for gate in gates)
            for gates in gate_sets
        ),
        "PIT_HARD_REJECTION",
    )
    if facts is not None:
        facts.add(fact_key)
    return evidence.content_hash


def _statistic(native: float, reason: str) -> PredictionStatistic:
    state = (
        "FINITE"
        if math.isfinite(native)
        else "NAN"
        if math.isnan(native)
        else "POSITIVE_INFINITY"
        if native > 0
        else "NEGATIVE_INFINITY"
    )
    _require(state in ("FINITE", "NAN"), "NATIVE_STATISTIC_INFINITE")
    if reason == "DEFINED_FINITE_PAIRS":
        _require(state == "FINITE", "UNEXPLAINED_NONFINITE_STATISTIC")
    return PredictionStatistic.model_validate(
        {
            "native_value": native if state == "FINITE" else None,
            "native_state": state,
            "value": native if reason == "DEFINED_FINITE_PAIRS" else None,
            "status": "DEFINED" if reason == "DEFINED_FINITE_PAIRS" else "UNDEFINED",
            "reason": reason,
        }
    )


def _native_frame(path: Path) -> pd.DataFrame:
    value: object = pd.read_pickle(path)
    _require(isinstance(value, pd.DataFrame), "NATIVE_FRAME_REQUIRED")
    frame = cast(pd.DataFrame, value)
    _require(
        len(frame) > 0
        and frame.shape[1] == 1
        and isinstance(frame.index, pd.MultiIndex)
        and tuple(frame.index.names) == ("datetime", "instrument")
        and frame.index.is_unique,
        "NATIVE_KEYS_OR_COLUMNS_INVALID",
    )
    return frame


def _series(path: Path, dates: tuple[date, ...]) -> pd.Series:
    value: object = pd.read_pickle(path)
    _require(isinstance(value, pd.Series), "NATIVE_STATISTIC_SERIES_REQUIRED")
    series = cast(pd.Series, value)
    _require(
        isinstance(series.index, pd.DatetimeIndex)
        and series.index.is_unique
        and tuple(day.date() for day in series.index) == dates,
        "NATIVE_STATISTIC_CALENDAR_MISMATCH",
    )
    return series


def _native_analysis(
    root: Path,
    dates: tuple[date, ...],
    membership: dict[str, tuple[tuple[date, date], ...]],
    sample_rows: int,
    sample_index_hash: str,
) -> tuple[tuple[PredictionDay, ...], str, str]:
    prediction, label = _native_frame(root / "pred.pkl"), _native_frame(root / "label.pkl")
    _require(prediction.index.equals(label.index), "PREDICTION_LABEL_KEY_MISMATCH")
    pred = prediction.iloc[:, 0]
    target = label.iloc[:, 0]
    raw_digest, omitted_digest = hashlib.sha256(), hashlib.sha256()
    observed: set[date] = set()
    seen_keys: set[tuple[date, str]] = set()
    date_set = set(dates)
    for raw_key, score, value in zip(prediction.index, pred, target, strict=True):
        key = cast(tuple[object, object], raw_key)
        timestamp, instrument = key
        _require(
            isinstance(timestamp, pd.Timestamp)
            and isinstance(instrument, str)
            and re.fullmatch(r"(?:SH|SZ)[0-9]{6}", instrument) is not None,
            "NATIVE_KEY_TYPE_INVALID",
        )
        stamp = cast(pd.Timestamp, timestamp)
        _require(
            stamp.tzinfo is None and stamp == stamp.normalize(), "NATIVE_DAILY_TIMESTAMP_INVALID"
        )
        day = stamp.date()
        qlib_id = cast(str, instrument)
        _require((day, qlib_id) not in seen_keys, "NATIVE_NORMALIZED_KEY_DUPLICATE")
        seen_keys.add((day, qlib_id))
        _require(
            day in date_set
            and any(start <= day <= end for start, end in membership.get(qlib_id, ())),
            "NATIVE_KEY_OUTSIDE_PIT_UNIVERSE_OR_CALENDAR",
        )
        _require(math.isfinite(float(score)), "NATIVE_PREDICTION_NONFINITE")
        _require(not math.isinf(float(value)), "NATIVE_LABEL_INFINITE")
        observed.add(day)
        encoded = canonical_json_bytes((day, qlib_id)) + b"\n"
        raw_digest.update(encoded)
        if math.isnan(float(value)):
            omitted_digest.update(encoded)
    _require(tuple(sorted(observed)) == dates, "NATIVE_PREDICTION_CALENDAR_INCOMPLETE")
    _require(
        len(prediction) == sample_rows and raw_digest.hexdigest() == sample_index_hash,
        "ACTUAL_DATASETH_TEST_INDEX_MISMATCH",
    )
    ic, rank_ic = (
        _series(root / "sig_analysis/ic.pkl", dates),
        _series(root / "sig_analysis/ric.pkl", dates),
    )
    calc_ic = cast(_QlibIC, importlib.import_module("qlib.contrib.eva.alpha").calc_ic)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        computed_ic, computed_rank_ic = calc_ic(pred, target)
    # Exact reproduction: a tolerance supplied after observing values cannot
    # turn source corruption into statistical undefinedness.
    for native, rebuilt in ((ic, computed_ic), (rank_ic, computed_rank_ic)):
        _require(native.index.equals(rebuilt.index), "NATIVE_STATISTIC_KEYS_NOT_REPRODUCED")
        _require(
            all(
                float(left) == float(right)
                or (math.isnan(float(left)) and math.isnan(float(right)))
                for left, right in zip(native, rebuilt, strict=True)
            ),
            "NATIVE_STATISTICS_NOT_REPRODUCED",
        )
    frame = pd.DataFrame({"prediction": pred, "label": target})
    daily: list[PredictionDay] = []
    for raw_timestamp, group in frame.groupby(level="datetime", sort=True):
        timestamp = cast(pd.Timestamp, raw_timestamp)
        day = timestamp.date()
        pairs = group.dropna()
        predictions = cast(list[float], pairs["prediction"].tolist())
        labels = cast(list[float], pairs["label"].tolist())
        pred_unique, label_unique = len(set(predictions)), len(set(labels))
        reason = (
            "INSUFFICIENT_FINITE_PAIRS"
            if len(pairs) < 2
            else "CONSTANT_PREDICTION"
            if pred_unique <= 1
            else "CONSTANT_LABEL"
            if label_unique <= 1
            else "DEFINED_FINITE_PAIRS"
        )
        daily.append(
            PredictionDay(
                trade_date=day,
                prediction_rows=len(group),
                label_rows=len(group),
                paired_rows=len(group),
                finite_pairs=len(pairs),
                prediction_nonfinite=0,
                label_nan=len(group) - len(pairs),
                label_infinite=0,
                prediction_unique_finite=pred_unique,
                label_unique_finite=label_unique,
                ic=_statistic(float(ic.loc[timestamp]), reason),
                rank_ic=_statistic(float(rank_ic.loc[timestamp]), reason),
            )
        )
    return tuple(daily), raw_digest.hexdigest(), omitted_digest.hexdigest()


def build_prediction_evidence(
    source: PredictionImportSource,
    profile: PredictionEvaluationProfile,
    *,
    base_authoring: ExperimentAuthoringSpec | None = None,
) -> PredictionEvidence:
    """Reconstruct admissible evidence from independently verified originals."""
    identity_hash = sha256_bytes(canonical_json_bytes(prediction_verifier_identity()))
    _require(identity_hash == profile.verifier_identity_hash, "VERIFIER_IDENTITY_MISMATCH")
    _require(version("pyqlib") == profile.qlib_version, "VERIFIER_QLIB_VERSION_MISMATCH")
    request = _contract(source.request, AutonomousExecutionRequest)
    outcome = _contract(source.outcome, AutonomousExecutionResult)
    receipt = _contract(source.receipt, AutonomousExecutionReceipt)
    resolved = _contract(source.resolved, ResolvedExperimentSpec)
    policy = _research_policy(source.research_policy)
    _require(base_authoring is not None, "BASE_AUTHORING_REQUIRED")
    assert base_authoring is not None
    _require(base_authoring.content_hash == request.authoring_hash, "BASE_AUTHORING_HASH_MISMATCH")
    # Reuse the actual execution method without constructing an engine or loading
    # data. Its source is bound in prediction_verifier_identity(). The complete
    # derived hash also binds the unchanged base strategy.
    authoring = QuantosResearchExecutionAdapter._authoring(  # pyright: ignore[reportPrivateUsage]
        cast(QuantosResearchExecutionAdapter, _AuthoringContext(base_authoring)), request
    )
    _require(request.content_hash in profile.execution_request_hashes, "REQUEST_NOT_IN_COHORT")
    _require(
        outcome.request_hash == request.content_hash == receipt.outcome.request_hash,
        "OUTCOME_REQUEST_MISMATCH",
    )
    _require(receipt.request == request, "RECEIPT_REQUEST_MISMATCH")
    expected_outcome = receipt.outcome.model_copy(
        update={
            "execution_artifact_hash": receipt.content_hash,
            "evidence_hashes": tuple(
                sorted(set((*receipt.outcome.evidence_hashes, receipt.content_hash)))
            ),
        }
    )
    _require(outcome == expected_outcome, "RECEIPT_OUTCOME_MISMATCH")
    _require(
        outcome.execution_requested and str(outcome.outcome) != "PIT_REJECT",
        "ORIGINAL_PIT_REJECTED",
    )
    for name in (
        "snapshot_hash",
        "qlib_view_hash",
        "research_policy_hash",
        "code_commit_hash",
        "lockfile_hash",
        "qlib_version",
    ):
        _require(
            getattr(request, name) == getattr(profile, name) == getattr(resolved, name),
            "SOURCE_PROFILE_BINDING_MISMATCH",
        )
    _require(
        policy.content_hash == profile.research_policy_hash
        and resolved.expression == request.candidate.expression
        and resolved.authoring_spec_hash == authoring.content_hash
        and resolved.experiment_id == authoring.experiment_id
        and resolved.validation_policy_hash == request.validation_policy_hash
        and resolved.cost_policy_hash == request.cost_policy_hash
        and resolved.backtest_policy_hash == request.backtest_policy_hash
        and request.segment_start == resolved.evaluation_start == policy.test.start
        and request.segment_end == resolved.evaluation_end == policy.test.end,
        "RESOLVED_SOURCE_BINDING_MISMATCH",
    )
    _verify_source_code(source, request)
    reservation = _raw_json(source.workflow_reservation)
    completion = _raw_json(source.workflow_completion)
    _raw_json(source.management_exit)  # Preserve the actual original management observation.
    inputs = {
        "resolved_hash": resolved.content_hash,
        "research_policy_hash": policy.content_hash,
        "signal_hash": source.signal_hash,
    }
    runtime_hash = capture_runtime_fingerprint().content_hash
    _require(
        reservation.get("runtime_fingerprint_hash") == runtime_hash,
        "ORIGINAL_WORKFLOW_RUNTIME_MISMATCH",
    )
    stage_inputs_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "request_hash": request.content_hash,
                "runtime_fingerprint_hash": runtime_hash,
                "stage": "workflow",
                "inputs": inputs,
                "recovery_policy": "discovery-stage-original-verification/v1",
            }
        )
    )
    _require(
        reservation.get("schema_version") == "discovery-stage-reservation/v1"
        and reservation.get("request_hash") == request.content_hash
        and reservation.get("stage") == "workflow"
        and reservation.get("inputs") == inputs
        and reservation.get("inputs_hash") == stage_inputs_hash
        and completion.get("inputs_hash") == reservation.get("inputs_hash")
        and completion.get("schema_version")
        in ("discovery-stage-attempt-completion/v1", "discovery-stage-attempt-completion/v2")
        and completion.get("status") in ("SUCCEEDED", "ADOPTED", "FAILED"),
        "ACTUAL_WORKFLOW_STAGE_BINDING_MISMATCH",
    )
    snapshot_path = _safe_path(source.snapshot_path, directory=True)
    view_path = _safe_path(source.qlib_view_path, directory=True)
    snapshot, view = verify_snapshot(snapshot_path), verify_qlib_view(view_path)
    quality = DataQualityReport.model_validate_json(
        (snapshot_path / "quality-report.json").read_bytes()
    )
    _require(
        snapshot.snapshot_hash == request.snapshot_hash
        and view.view_hash == request.qlib_view_hash
        and view.source_snapshot_hash == snapshot.snapshot_hash
        and view.view_spec_hash == resolved.qlib_view_spec_hash
        and quality.content_hash == snapshot.quality_report_hash
        and quality.passed
        and view.health_check_passed,
        "DATA_IDENTITY_OR_QUALITY_REJECTED",
    )
    if request.pit_policy_hash == field_study_pit_policy_hash():
        config = _contract(source.research_policy, FrozenFieldStudyConfiguration)
        label = "V" if base_authoring == config.volume else "P"
        _require(base_authoring in (config.volume, config.price), "FIELD_STUDY_AUTHORING_MISMATCH")
        _require(
            isinstance(base_authoring.expression, SafeQlibExpressionSpec),
            "FIELD_STUDY_DSL_REQUIRED",
        )
        _require(
            expression_identity(request.candidate.expression)
            == expression_identity(base_authoring.expression)
            and request.agent_run_hash == config.input_reference(label),
            "FIELD_STUDY_CANDIDATE_MISMATCH",
        )
        from quantos.application.field_study import build_task

        _require(
            request == build_task(config, label, snapshot, view).request,
            "FIELD_STUDY_REQUEST_IDENTITY_MISMATCH",
        )
        bindings = build_autonomous_execution_bindings(
            snapshot=snapshot,
            qlib_view=view,
            research_policy=config.research_policy,
            validation_policy=config.validation_policy,
            authoring=base_authoring,
            cost_policy=config.cost_policy,
            backtest_policy=config.backtest_policy,
            code_commit_hash=config.code_commit_hash,
            lockfile_hash=config.lockfile_hash,
            field_study=config,
        )
        _require(
            all(
                getattr(request, name) == getattr(bindings, name)
                for name in type(bindings).model_fields
                if name != "schema_version"
            ),
            "FIELD_STUDY_EXECUTION_BINDING_MISMATCH",
        )
    calendar = tuple(
        date.fromisoformat(line)
        for line in (view_path / "calendars/day.txt").read_text().splitlines()
        if line
    )
    _require(calendar == tuple(sorted(set(calendar))) and bool(calendar), "DATA_CALENDAR_INVALID")
    dates = tuple(day for day in calendar if policy.test.start <= day <= policy.test.end)
    _require(dates == profile.expected_dates, "PROFILE_CALENDAR_INCOMPLETE")
    pit_hash = _verify_pit(
        source,
        request,
        resolved,
        _verified_data_identity=(snapshot.snapshot_hash, view.view_hash, view.view_spec_hash),
    )
    native_root = _safe_path(source.native_root, directory=True)
    _require(
        native_root.name == f"sha256-{request.execution_identity}",
        "NATIVE_EXECUTION_DIRECTORY_MISMATCH",
    )
    split_path = _safe_path(native_root / "model-data-splits.json")
    _require(sha256_file(split_path) == source.model_split_sha256, "MODEL_SPLIT_HASH_MISMATCH")
    split = verify_model_data_split(
        split_path, resolved=resolved, research_policy=policy, calendar=calendar
    )
    native_sources: list[PredictionFileSource] = []
    for item in split.source_files:
        native_path = _safe_path(native_root / item.logical_path)
        _require(item.size_bytes <= _NATIVE_CAP, "NATIVE_FILE_LIMIT")
        native_sources.append(PredictionFileSource(path=str(native_path), sha256=item.sha256))
    membership = resolve_historical_universe_spans(
        view_path,
        expected_view_hash=request.qlib_view_hash,
        expected_snapshot_hash=request.snapshot_hash,
        index_id=resolved.strategy.universe_index,
        sessions=dates,
        decision_times=tuple(
            datetime.combine(day, time(16, 10), tzinfo=ZoneInfo("Asia/Shanghai")) for day in dates
        ),
    )
    daily, raw_keys, omitted_keys = _native_analysis(
        native_root, dates, membership, split.test.sample_rows, split.test.sample_index_hash
    )
    return PredictionEvidence(
        profile_hash=profile.content_hash,
        source_hash=source.content_hash,
        verifier_identity_hash=identity_hash,
        execution_request_hash=request.content_hash,
        execution_identity=request.execution_identity,
        candidate_hash=request.candidate.content_hash,
        structural_expression_hash=request.candidate_structural_expression_hash,
        raw_key_hash=raw_keys,
        omitted_nan_label_key_hash=omitted_keys,
        raw_pair_count=sum(item.paired_rows for item in daily),
        finite_pair_count=sum(item.finite_pairs for item in daily),
        omitted_nan_label_count=sum(item.label_nan for item in daily),
        model_split_hash=split.content_hash,
        signal_hash=source.signal_hash,
        pit_evidence_hash=pit_hash,
        native_sources=tuple(native_sources),
        daily=daily,
        original_outcome_hash=outcome.content_hash,
        original_receipt_hash=receipt.content_hash,
        original_validation_report_hash=outcome.validation_report_hash,
        original_research_result_hash=outcome.research_result_hash,
        original_failure_reason=str(outcome.failure_reason_code)
        if outcome.failure_reason_code
        else None,
        original_execution_outcome=str(outcome.outcome),
        original_stage_status=str(completion["status"]),
    )


def validate_prediction_output_root(
    output_root: Path, sources: tuple[PredictionImportSource, ...]
) -> None:
    """Keep successor operations and artifacts outside every original source store."""
    root = output_root.absolute()
    require_durable_execution_root(root)
    _require(
        root.resolve() == root and not any(item.is_symlink() for item in (root, *root.parents)),
        "UNSAFE_OUTPUT_ROOT",
    )
    for source in sources:
        original_roots = (
            source.source_workspace,
            source.native_root,
            source.snapshot_path,
            source.qlib_view_path,
            source.signal_path,
            *(
                str(Path(getattr(source, name).path).parent)
                for name in (
                    "request",
                    "outcome",
                    "receipt",
                    "resolved",
                    "research_policy",
                    "workflow_reservation",
                    "workflow_completion",
                    "management_exit",
                    "source_capsule",
                    "source_inventory",
                )
            ),
        )
        _require(
            not any(root.is_relative_to(Path(path).absolute()) for path in original_roots),
            "OUTPUT_OVERLAPS_ORIGINALS",
        )


def publish_prediction_evidence(
    source: PredictionImportSource,
    profile: PredictionEvaluationProfile,
    output_root: Path,
    *,
    base_authoring: ExperimentAuthoringSpec | None = None,
) -> Path:
    """Publish a small immutable derivative; controlled native originals stay intact."""
    validate_prediction_output_root(output_root, (source,))
    evidence = build_prediction_evidence(source, profile, base_authoring=base_authoring)
    return _publish_built_prediction_evidence(source, profile, output_root, evidence)


def _publish_built_prediction_evidence(
    source: PredictionImportSource,
    profile: PredictionEvaluationProfile,
    output_root: Path,
    evidence: PredictionEvidence,
) -> Path:
    """Same-operation fully verified facts; never a caller-supplied cached assertion."""
    manifest = PredictionEvidenceManifest(
        profile_hash=profile.content_hash,
        source_hash=source.content_hash,
        verifier_identity_hash=evidence.verifier_identity_hash,
        evidence_hash=evidence.content_hash,
        execution_request_hash=evidence.execution_request_hash,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"sha256-{manifest.content_hash}"
    if destination.exists():
        _verify_saved(destination, manifest.content_hash, source, profile, evidence)
        return destination
    # Failure logs/checkpoints belong to the caller's durable operation record.
    with tempfile.TemporaryDirectory(prefix=".prediction-stage-", dir=output_root) as staging:
        stage = Path(staging)
        for name, item in (
            ("manifest.json", manifest),
            ("evidence.json", evidence),
            ("source.json", source),
            ("profile.json", profile),
        ):
            atomic_write_bytes(stage / name, item.canonical_bytes())
        atomic_write_bytes(
            stage / "verifier-identity.json", canonical_json_bytes(prediction_verifier_identity())
        )
        publish_directory(stage, destination)
    return destination


def _verify_saved(
    path: Path,
    expected_hash: str,
    source: PredictionImportSource,
    profile: PredictionEvaluationProfile,
    rebuilt: PredictionEvidence,
) -> PredictionEvidence:
    path = _safe_path(path, directory=True)
    _require(path.name == f"sha256-{expected_hash}", "EVIDENCE_DIRECTORY_HASH_MISMATCH")
    _require(
        {item.relative_to(path).as_posix() for item in regular_tree_files(path)}
        == {
            "manifest.json",
            "evidence.json",
            "source.json",
            "profile.json",
            "verifier-identity.json",
        },
        "EVIDENCE_FILE_SET_MISMATCH",
    )
    manifest_raw = (path / "manifest.json").read_bytes()
    manifest = PredictionEvidenceManifest.model_validate_json(manifest_raw)
    expected_manifest = PredictionEvidenceManifest(
        profile_hash=profile.content_hash,
        source_hash=source.content_hash,
        verifier_identity_hash=rebuilt.verifier_identity_hash,
        evidence_hash=rebuilt.content_hash,
        execution_request_hash=rebuilt.execution_request_hash,
    )
    _require(
        manifest.content_hash == expected_hash
        and manifest == expected_manifest
        and manifest.canonical_bytes() == manifest_raw,
        "EVIDENCE_MANIFEST_BINDING_MISMATCH",
    )
    for name, encoded in (
        ("source.json", source.canonical_bytes()),
        ("profile.json", profile.canonical_bytes()),
        ("evidence.json", rebuilt.canonical_bytes()),
        ("verifier-identity.json", canonical_json_bytes(prediction_verifier_identity())),
    ):
        _require((path / name).read_bytes() == encoded, "SUCCESSOR_EVIDENCE_NOT_REPRODUCED")
    return rebuilt


def verify_prediction_evidence(
    path: Path,
    *,
    expected_hash: str,
    source: PredictionImportSource,
    profile: PredictionEvaluationProfile,
    base_authoring: ExperimentAuthoringSpec | None = None,
) -> PredictionEvidence:
    """Independent verification always rebuilds from data, PIT and native originals."""
    return _verify_saved(
        path,
        expected_hash,
        source,
        profile,
        build_prediction_evidence(source, profile, base_authoring=base_authoring),
    )


def compare_prediction_evidence(
    profile: PredictionEvaluationProfile,
    sources: Mapping[str, PredictionImportSource],
    references: Mapping[str, tuple[Path, str]],
    *,
    base_authoring: ExperimentAuthoringSpec | None = None,
    base_authorings: Mapping[str, ExperimentAuthoringSpec] | None = None,
) -> dict[str, object]:
    """All frozen requests stay in the denominator, including unavailable sources.

    Primary means use only the common defined dates of coverage-admitted different
    structures. Own-date means are sensitivity values and never cross-candidate ranks.
    This function does not map generation opportunities or compare method maxima.
    """
    cohort = set(profile.execution_request_hashes)
    _require(set(sources) <= cohort and set(references) <= cohort, "UNDECLARED_COMPARISON_REQUEST")
    _require(
        profile.verifier_identity_hash
        == sha256_bytes(canonical_json_bytes(prediction_verifier_identity())),
        "VERIFIER_IDENTITY_MISMATCH",
    )
    rows: list[dict[str, object]] = []
    verified: dict[str, tuple[PredictionEvidence, str]] = {}
    for request_hash in profile.execution_request_hashes:
        row: dict[str, object] = {
            "execution_request_hash": request_hash,
            "status": "SOURCE_MISSING",
            "reason": "SOURCE_MISSING",
            "primary_common_rank_ic_mean": None,
            "own_dates_rank_ic_mean_sensitivity": None,
        }
        rows.append(row)
        if request_hash not in sources:
            continue
        source = sources[request_hash]
        if source.request.sha256 != request_hash:
            row.update(
                {
                    "status": "SOURCE_VERIFICATION_REJECTED",
                    "reason": "COMPARISON_SOURCE_REQUEST_MISMATCH",
                }
            )
            continue
        if request_hash not in references:
            row["status"] = "EVIDENCE_MISSING"
            row["reason"] = "EVIDENCE_MISSING"
            continue
        path, expected_hash = references[request_hash]
        try:
            evidence = verify_prediction_evidence(
                path,
                expected_hash=expected_hash,
                source=source,
                profile=profile,
                base_authoring=(
                    base_authorings.get(request_hash)
                    if base_authorings is not None
                    else base_authoring
                ),
            )
        except (OSError, ValueError, RuntimeError) as error:
            # Use bounded error classes/codes, never unrestricted exceptions.
            row.update(
                {
                    "status": "SOURCE_VERIFICATION_REJECTED",
                    "reason": str(error)
                    if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]{1,100}", str(error))
                    else type(error).__name__,
                }
            )
            continue
        verified[request_hash] = (evidence, expected_hash)
    return _comparison_from_verified(profile, rows, verified)


def _comparison_from_verified(
    profile: PredictionEvaluationProfile,
    rows: list[dict[str, object]],
    verified: Mapping[str, tuple[PredictionEvidence, str]],
) -> dict[str, object]:
    """Unchanged coverage/common-day rules for independently verified or adopted facts."""
    admitted: dict[str, PredictionEvidence] = {}
    for row in rows:
        request_hash = cast(str, row["execution_request_hash"])
        if request_hash not in verified:
            continue
        evidence, expected_hash = verified[request_hash]
        values = [item.rank_ic.value for item in evidence.daily if item.rank_ic.value is not None]
        fraction = len(values) / len(profile.expected_dates)
        row.update(
            {
                "status": "COVERAGE_REJECTED",
                "reason": "DEFINED_FRACTION_BELOW_FROZEN_MINIMUM",
                "evidence_hash": expected_hash,
                "structural_expression_hash": evidence.structural_expression_hash,
                "defined_days": len(values),
                "expected_days": len(profile.expected_dates),
                "defined_fraction": fraction,
                "own_dates_rank_ic_mean_sensitivity": math.fsum(values) / len(values)
                if values
                else None,
                "original_execution_outcome": evidence.original_execution_outcome,
                "original_failure_reason": evidence.original_failure_reason,
                "original_validation_report_hash": evidence.original_validation_report_hash,
                "p14c": "NOT_EVALUATED_BY_THIS_INTERFACE",
            }
        )
        if fraction >= profile.min_defined_fraction:
            row["status"] = "COVERAGE_ADMITTED"
            row["reason"] = "VERIFIED_SOURCE_AND_DEFINED_DATE_COVERAGE"
            admitted[request_hash] = evidence
    # Labels must denote the same original target/key domain across the cohort.
    labels = {
        next(item.sha256 for item in evidence.native_sources if Path(item.path).name == "label.pkl")
        for evidence in admitted.values()
    }
    _require(len(labels) <= 1, "COMPARISON_LABEL_SOURCE_MISMATCH")
    common = set(profile.expected_dates)
    for evidence in admitted.values():
        common &= {item.trade_date for item in evidence.daily if item.rank_ic.value is not None}
    common_dates = tuple(sorted(common)) if admitted else ()
    available = bool(admitted) and len(common_dates) >= profile.min_common_days
    for row in rows:
        request_hash = cast(str, row["execution_request_hash"])
        if request_hash in admitted:
            evidence = admitted[request_hash]
            if available:
                values = [
                    cast(float, item.rank_ic.value)
                    for item in evidence.daily
                    if item.trade_date in common
                ]
                row["primary_common_rank_ic_mean"] = math.fsum(values) / len(values)
            else:
                row["status"] = "COMMON_DATES_INSUFFICIENT"
                row["reason"] = "COMMON_DAYS_BELOW_FROZEN_MINIMUM"
    return {
        "schema_version": "prediction-evidence-comparison/v1",
        "profile_hash": profile.content_hash,
        "interpretation": profile.interpretation,
        "scope": "FROZEN_EXECUTION_REQUEST_COHORT_NOT_METHOD_OPPORTUNITIES",
        "request_denominator": len(profile.execution_request_hashes),
        "rows": rows,
        "common_dates": [day.isoformat() for day in common_dates],
        "common_days": len(common_dates),
        "primary_comparison_status": "AVAILABLE" if available else "UNAVAILABLE",
        "missing_or_rejected_requests": sum(
            hash_ not in admitted for hash_ in profile.execution_request_hashes
        ),
        "method_comparison": "NOT_EVALUATED_REQUIRES_FROZEN_GENERATION_MAPPING",
        "original_validation_and_p14c": "UNCHANGED",
    }


def publish_prediction_cohort(
    profile: PredictionEvaluationProfile,
    sources: Mapping[str, PredictionImportSource],
    *,
    base_authorings: Mapping[str, ExperimentAuthoringSpec],
    output_root: Path,
) -> dict[str, object]:
    """Build each original once, publish immutably, and reuse its local verified facts."""
    _require(set(sources) <= set(profile.execution_request_hashes), "UNDECLARED_COMPARISON_REQUEST")
    _require(
        profile.verifier_identity_hash
        == sha256_bytes(canonical_json_bytes(prediction_verifier_identity())),
        "VERIFIER_IDENTITY_MISMATCH",
    )
    validate_prediction_output_root(output_root, tuple(sources.values()))
    rows: list[dict[str, object]] = []
    verified: dict[str, tuple[PredictionEvidence, str]] = {}
    with prediction_pit_verification_scope():
        for digest in profile.execution_request_hashes:
            row: dict[str, object] = {
                "execution_request_hash": digest,
                "status": "SOURCE_MISSING",
                "reason": "SOURCE_MISSING",
                "primary_common_rank_ic_mean": None,
                "own_dates_rank_ic_mean_sensitivity": None,
            }
            rows.append(row)
            if digest not in sources:
                continue
            source = sources[digest]
            if source.request.sha256 != digest:
                row.update(
                    status="SOURCE_VERIFICATION_REJECTED",
                    reason="COMPARISON_SOURCE_REQUEST_MISMATCH",
                )
                continue
            try:
                evidence = build_prediction_evidence(
                    source, profile, base_authoring=base_authorings.get(digest)
                )
                path = _publish_built_prediction_evidence(source, profile, output_root, evidence)
                verified[digest] = (evidence, path.name.removeprefix("sha256-"))
            except (OSError, ValueError, RuntimeError) as error:
                row.update(
                    status="SOURCE_VERIFICATION_REJECTED",
                    reason=(
                        str(error)
                        if isinstance(error, ValueError)
                        and re.fullmatch(r"[A-Z_]{1,100}", str(error))
                        else type(error).__name__
                    ),
                )
    return _comparison_from_verified(profile, rows, verified)
