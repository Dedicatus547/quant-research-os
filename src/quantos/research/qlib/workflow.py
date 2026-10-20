"""Reusable offline Qlib Workflow execution for immutable ResearchResult export."""

from __future__ import annotations

import hashlib
import math
import os
import pickle
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as day_time
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import qlib  # pyright: ignore[reportMissingTypeStubs]
from qlib.config import REG_CN  # pyright: ignore[reportMissingTypeStubs]
from qlib.contrib.model.gbdt import LGBModel  # pyright: ignore[reportMissingTypeStubs]
from qlib.data.dataset import DatasetH  # pyright: ignore[reportMissingTypeStubs]
from qlib.data.dataset.handler import DataHandlerLP  # pyright: ignore[reportMissingTypeStubs]
from qlib.workflow import R  # pyright: ignore[reportMissingTypeStubs]
from qlib.workflow.record_temp import (  # pyright: ignore[reportMissingTypeStubs]
    SigAnaRecord,
    SignalRecord,
)

from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.model_data_split import QlibModelDataSegment, QlibModelDataSplitAudit
from quantos.contracts.research import ResearchPolicy, ResearchSegment, ResolvedExperimentSpec
from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceCollectionV3,
    PITExecutionProfile,
)
from quantos.contracts.research_result import ResearchResultSourceFile
from quantos.contracts.status import ReasonCode
from quantos.data.qlib_view import verify_qlib_view
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.model_split import effective_model_segments, verify_model_data_split
from quantos.research.qlib.pit_evidence import load_pit_artifact_evidence
from quantos.research.qlib.result import ResearchResultArtifactBuilder, ResearchResultBuildResult
from quantos.research.qlib.universe import (
    QlibResearchError,
    WorkflowRecorderInterfaceError,
    WorkflowRequiredMetricNonFiniteError,
    resolve_historical_universe_spans,
)

_WORKFLOW_LOCK = threading.RLock()
_METRIC_NAMES = ("IC", "ICIR", "Rank IC", "Rank ICIR")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@contextmanager
def _workflow_tracking_runtime(
    runtime_root: Path, execution_profile: PITExecutionProfile
) -> Generator[str, None, None]:
    """Select a Qlib recorder backend under the caller-held Workflow lock."""
    runtime_root = runtime_root.resolve()
    field_study = execution_profile == "frozen-field-study/v1"
    # MLflow's FileStore rejects run ancestors named "artifacts". The fixed study
    # lives under that directory, so use its supported SQLite tracking backend.
    # Keeping cwd here also confines SQLite's default ./mlruns artifact store.
    runtime_uri = (
        f"sqlite:///{runtime_root / 'tracking.sqlite'}" if field_study else runtime_root.as_uri()
    )
    previous_cwd = Path.cwd()
    previous_setting = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    # Legacy Qlib file-URI locking strips the leading slash before joining cwd.
    os.chdir(runtime_root if field_study else Path("/"))
    try:
        yield runtime_uri
    finally:
        os.chdir(previous_cwd)
        if previous_setting is None:
            os.environ.pop("MLFLOW_ALLOW_FILE_STORE", None)
        else:
            os.environ["MLFLOW_ALLOW_FILE_STORE"] = previous_setting


@dataclass(frozen=True)
class QlibWorkflowResearchResult:
    """Native Qlib output exported into the existing immutable ResearchResult artifact."""

    build: ResearchResultBuildResult
    recorder_id: str
    label_expression: str
    model_data_split_hash: str


def _sample_segment(
    frame: Any, declared: ResearchSegment, effective: ResearchSegment
) -> QlibModelDataSegment:
    if len(frame) == 0 or not frame.index.is_unique:
        raise ValueError("DatasetH returned empty or duplicate model samples")
    days: set[date] = set()
    digest = hashlib.sha256()
    names = tuple(frame.index.names)
    if set(names) != {"datetime", "instrument"}:
        raise ValueError("DatasetH model samples lack native datetime/instrument keys")
    date_index, instrument_index = names.index("datetime"), names.index("instrument")
    for key in frame.index:
        day = key[date_index].date()
        days.add(day)
        digest.update(canonical_json_bytes((day, str(key[instrument_index]))))
        digest.update(b"\n")
    return QlibModelDataSegment(
        declared=declared,
        effective=effective,
        observed_sessions=tuple(sorted(days)),
        sample_rows=len(frame),
        sample_index_hash=digest.hexdigest(),
    )


def qlib_recorder_id(execution_identity: str) -> str:
    """Map the logical execution identity to a stable, Qlib-safe recorder identifier."""

    if len(execution_identity) != 64 or any(
        character not in "0123456789abcdef" for character in execution_identity
    ):
        raise ValueError("execution identity must be a lowercase SHA-256 digest")
    return execution_identity[:32]


def _label_expression(policy: ResearchPolicy) -> str:
    horizon = policy.label_horizon_trading_sessions
    return f"Ref($close,-{horizon})/$close-1"


def _native_objects(recorder: object) -> tuple[object, object, object, object, dict[str, float]]:
    load_object = getattr(recorder, "load_object", None)
    list_metrics = getattr(recorder, "list_metrics", None)
    if not callable(load_object) or not callable(list_metrics):
        raise WorkflowRecorderInterfaceError()
    prediction = load_object("pred.pkl")
    label = load_object("label.pkl")
    ic = load_object("sig_analysis/ic.pkl")
    rank_ic = load_object("sig_analysis/ric.pkl")
    raw_metrics = cast(dict[str, object], list_metrics())
    metrics = {name: float(cast(float, raw_metrics[name])) for name in _METRIC_NAMES}
    if any(not math.isfinite(value) for value in metrics.values()):
        raise WorkflowRequiredMetricNonFiniteError()
    return prediction, label, ic, rank_ic, metrics


def _flush_recorder_logs(recorder: object) -> None:
    """Drain and close Qlib's asynchronous recorder queue.

    Qlib logs metrics through a background queue. MLflow's file store reads run metrics whenever
    it handles an artifact operation, so artifact writes must not overlap a queued metric write.
    The queue cannot be reused after ``wait`` closes it; clear it so later metric calls run
    synchronously instead of being added to a stopped worker.
    """

    async_log = getattr(recorder, "async_log", None)
    wait = getattr(async_log, "wait", None)
    if callable(wait):
        wait()
        if getattr(recorder, "async_log", None) is async_log:
            cast(Any, recorder).async_log = None


def _fit_and_generate_signal_record(
    model: Any, dataset: Any, recorder: Any, signal_record_type: Any
) -> None:
    """Drain Qlib fit metrics before SignalRecord writes artifacts through MLflow."""

    model.fit(dataset, verbose_eval=0)
    _flush_recorder_logs(recorder)
    signal_record_type(model, dataset, recorder).generate()


def _write_native_records(
    native_root: Path,
    *,
    prediction: object,
    label: object,
    ic: object,
    rank_ic: object,
    metrics: dict[str, float],
) -> None:
    native_root.mkdir(parents=True, exist_ok=True)
    sig_analysis = native_root / "sig_analysis"
    sig_analysis.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("pred.pkl", prediction),
        ("label.pkl", label),
        ("sig_analysis/ic.pkl", ic),
        ("sig_analysis/ric.pkl", rank_ic),
    ):
        atomic_write_bytes(
            native_root / name, pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        )
    atomic_write_bytes(native_root / "metrics.json", canonical_json_bytes(metrics))


def _historical_universe_instruments(
    qlib_view_path: Path,
    *,
    expected_view_hash: str,
    expected_snapshot_hash: str,
    universe_index: str,
) -> dict[str, tuple[tuple[datetime, datetime], ...]]:
    """Resolve membership at each verified session for Qlib's native date-span filter."""

    try:
        calendar = tuple(
            date.fromisoformat(line.strip())
            for line in (qlib_view_path / "calendars" / "day.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "verified Qlib calendar could not be read"
        ) from error
    if not calendar or calendar != tuple(sorted(set(calendar))):
        raise QlibResearchError(ReasonCode.ARTIFACT_CORRUPTED, "Qlib calendar is not canonical")

    resolved_spans = resolve_historical_universe_spans(
        qlib_view_path,
        expected_view_hash=expected_view_hash,
        expected_snapshot_hash=expected_snapshot_hash,
        index_id=universe_index,
        sessions=calendar,
        decision_times=tuple(
            datetime.combine(session, day_time(16, 10), tzinfo=_SHANGHAI) for session in calendar
        ),
    )
    return {
        instrument: tuple(
            (
                datetime.combine(start, day_time.min),
                datetime.combine(end, day_time.max),
            )
            for start, end in spans
        )
        for instrument, spans in resolved_spans.items()
    }


class QlibWorkflowResearchService:
    """Run Qlib's native DatasetH/LGBModel/Record Template chain, then export its outputs.

    This is the application-facing form of the already-qualified Qlib Workflow used by the P0
    feasibility runner. Qlib owns fitting and SigAnaRecord owns IC/Rank IC calculation; this
    service only binds the frozen feature expression and research segments and exports objects.
    """

    def run(
        self,
        resolved: ResolvedExperimentSpec,
        research_policy: ResearchPolicy,
        signal_path: Path,
        qlib_view_path: Path,
        output_root: Path,
        *,
        execution_identity: str,
        research_result_root: Path,
        workspace: Path,
        dq_audit_root: Path | None = None,
        execution_profile: PITExecutionProfile = "legacy-price/v2",
    ) -> QlibWorkflowResearchResult:
        if execution_profile == "frozen-field-study/v1":
            evidence = load_pit_artifact_evidence(signal_path / "pit-evidence.json")
            if (
                not isinstance(evidence, PITCrossSectionEvidenceCollectionV3)
                or evidence.content_hash != resolved.pit_audit_evidence_hash
                or evidence.expression != resolved.expression
                or evidence.snapshot_hash != resolved.snapshot_hash
                or evidence.qlib_view_hash != resolved.qlib_view_hash
            ):
                raise ValueError("Workflow field-study PIT binding differs")
        recorder_id = qlib_recorder_id(execution_identity)
        feature = (
            translate_safe_expression(resolved.expression)
            if execution_profile == "legacy-price/v2"
            else translate_safe_expression(resolved.expression, execution_profile=execution_profile)
        ).output_expression
        label = _label_expression(research_policy)
        runtime_root = output_root / "mlflow-runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        native_root = output_root / "native-records" / f"sha256-{execution_identity}"
        calendar = tuple(
            date.fromisoformat(line.strip())
            for line in (qlib_view_path / "calendars" / "day.txt").read_text().splitlines()
            if line.strip()
        )
        segments = effective_model_segments(research_policy, resolved, calendar)
        samples: dict[str, QlibModelDataSegment] = {}

        try:
            qlib_runtime = cast(Any, qlib)
            workflow = cast(Any, R)
            data_handler_type = cast(Any, DataHandlerLP)
            dataset_type = cast(Any, DatasetH)
            model_type = cast(Any, LGBModel)
            signal_record_type = cast(Any, SignalRecord)
            sigana_record_type = cast(Any, SigAnaRecord)
            with (
                _WORKFLOW_LOCK,
                _workflow_tracking_runtime(runtime_root, execution_profile) as runtime_uri,
            ):
                qlib_runtime.init(provider_uri=str(qlib_view_path), region=REG_CN)
                with workflow.start(
                    experiment_name="quantos-research",
                    recorder_id=recorder_id,
                    uri=runtime_uri,
                    resume=True,
                ):
                    recorder = workflow.get_recorder()
                    artifacts = set(cast(list[str], recorder.list_artifacts()))
                    if "sig_analysis" in artifacts:
                        nested = cast(list[str], recorder.list_artifacts("sig_analysis"))
                        artifacts.update(
                            item if item.startswith("sig_analysis/") else f"sig_analysis/{item}"
                            for item in nested
                        )
                    expected_artifacts = {
                        "pred.pkl",
                        "label.pkl",
                        "sig_analysis/ic.pkl",
                        "sig_analysis/ric.pkl",
                    }
                    present = expected_artifacts.intersection(artifacts)
                    if present and present != expected_artifacts:
                        raise ValueError("resumed Qlib recorder has a partial native record set")
                    if not present:
                        instruments = _historical_universe_instruments(
                            qlib_view_path,
                            expected_view_hash=resolved.qlib_view_hash,
                            expected_snapshot_hash=resolved.snapshot_hash,
                            universe_index=resolved.strategy.universe_index,
                        )
                        handler = data_handler_type(
                            start_time=research_policy.train.start,
                            end_time=resolved.evaluation_end,
                            instruments=instruments,
                            data_loader={
                                "class": "QlibDataLoader",
                                "module_path": "qlib.data.dataset.loader",
                                "kwargs": {
                                    "config": {
                                        "feature": [
                                            [feature],
                                            [resolved.expression.expression_id],
                                        ],
                                        "label": [[label], ["LABEL0"]],
                                    },
                                    "freq": "day",
                                },
                            },
                            learn_processors=[{"class": "DropnaLabel"}],
                        )
                        dataset = dataset_type(
                            handler=handler,
                            segments={
                                name: (part.start, part.end) for name, part in segments.items()
                            },
                        )
                        declared = {
                            "train": research_policy.train,
                            "valid": research_policy.validation,
                            "test": ResearchSegment(
                                start=resolved.evaluation_start, end=resolved.evaluation_end
                            ),
                        }
                        for name in ("train", "valid", "test"):
                            frame = dataset.prepare(
                                name,
                                col_set=["feature", "label"] if name != "test" else "feature",
                                data_key=data_handler_type.DK_L
                                if name != "test"
                                else data_handler_type.DK_I,
                            )
                            samples[name] = _sample_segment(frame, declared[name], segments[name])
                            del frame
                        recorder.save_objects(
                            **{
                                "model-data-split-samples.pkl": {
                                    name: part.model_dump(mode="json")
                                    for name, part in samples.items()
                                }
                            }
                        )
                        model = model_type(
                            loss="mse",
                            learning_rate=0.05,
                            max_depth=3,
                            num_leaves=7,
                            num_threads=research_policy.num_threads,
                            seed=research_policy.random_seed,
                            feature_fraction_seed=research_policy.random_seed,
                            bagging_seed=research_policy.random_seed,
                            data_random_seed=research_policy.random_seed,
                            deterministic=True,
                            force_col_wise=True,
                            num_boost_round=research_policy.num_boost_round,
                            early_stopping_rounds=research_policy.early_stopping_rounds,
                        )
                        _fit_and_generate_signal_record(
                            model, dataset, recorder, signal_record_type
                        )
                        sigana_record_type(recorder, ana_long_short=True).generate()
                    else:
                        if "model-data-split-samples.pkl" not in artifacts:
                            raise ValueError(
                                "resumed Qlib recorder lacks actual DatasetH split samples"
                            )
                        raw_samples = recorder.load_object("model-data-split-samples.pkl")
                        samples = {
                            name: QlibModelDataSegment.model_validate(raw_samples[name])
                            for name in ("train", "valid", "test")
                        }
                    _flush_recorder_logs(recorder)
                    prediction, target, ic, rank_ic, metrics = _native_objects(recorder)
            _write_native_records(
                native_root,
                prediction=prediction,
                label=target,
                ic=ic,
                rank_ic=rank_ic,
                metrics=metrics,
            )
            split_audit = QlibModelDataSplitAudit(
                resolved_spec_hash=resolved.content_hash,
                code_commit_hash=resolved.code_commit_hash,
                lockfile_hash=resolved.lockfile_hash,
                snapshot_hash=resolved.snapshot_hash,
                qlib_view_hash=resolved.qlib_view_hash,
                research_policy_hash=research_policy.content_hash,
                calendar_hash=sha256_bytes(canonical_json_bytes(calendar)),
                purge_trading_days=research_policy.purge_trading_days,
                label_horizon_trading_sessions=research_policy.label_horizon_trading_sessions,
                train=samples["train"],
                valid=samples["valid"],
                test=samples["test"],
                source_files=tuple(
                    ResearchResultSourceFile(
                        logical_path=name,
                        sha256=sha256_file(native_root / name),
                        size_bytes=(native_root / name).stat().st_size,
                    )
                    for name in (
                        "label.pkl",
                        "metrics.json",
                        "pred.pkl",
                        "sig_analysis/ic.pkl",
                        "sig_analysis/ric.pkl",
                    )
                ),
            )
            split_path = native_root / "model-data-splits.json"
            atomic_write_bytes(split_path, split_audit.canonical_bytes())
            verify_model_data_split(
                split_path, resolved=resolved, research_policy=research_policy, calendar=calendar
            )
            dq_calendar: tuple[date, ...] | None = None
            if dq_audit_root is not None:
                verified_view = verify_qlib_view(qlib_view_path)
                if verified_view.view_hash != resolved.qlib_view_hash:
                    raise QlibResearchError(
                        ReasonCode.SNAPSHOT_HASH_MISMATCH,
                        "DQ export view differs from the frozen ResearchResult input",
                    )
                dq_calendar = tuple(
                    day
                    for day in (
                        date.fromisoformat(line)
                        for line in (qlib_view_path / "calendars" / "day.txt")
                        .read_text(encoding="utf-8")
                        .splitlines()
                        if line
                    )
                    if resolved.evaluation_start <= day <= resolved.evaluation_end
                )
            built = ResearchResultArtifactBuilder().build(
                resolved,
                research_policy,
                signal_path,
                native_root,
                research_result_root,
                qlib_run_id=recorder_id,
                label_expression=label,
                dq_calendar=dq_calendar,
                dq_audit_root=dq_audit_root,
            )
            return QlibWorkflowResearchResult(built, recorder_id, label, split_audit.content_hash)
        except QlibResearchError:
            raise
        except (OSError, ValueError, KeyError) as error:
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED,
                "native Qlib Workflow execution or ResearchResult export failed",
            ) from error
