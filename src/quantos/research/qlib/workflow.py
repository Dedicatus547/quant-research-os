"""Reusable offline Qlib Workflow execution for immutable ResearchResult export."""

from __future__ import annotations

import math
import os
import pickle
import threading
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

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.research import ResearchPolicy, ResolvedExperimentSpec
from quantos.contracts.status import ReasonCode
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.result import ResearchResultArtifactBuilder, ResearchResultBuildResult
from quantos.research.qlib.universe import (
    QlibResearchError,
    resolve_historical_universe_spans,
)

_WORKFLOW_LOCK = threading.RLock()
_METRIC_NAMES = ("IC", "ICIR", "Rank IC", "Rank ICIR")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class QlibWorkflowResearchResult:
    """Native Qlib output exported into the existing immutable ResearchResult artifact."""

    build: ResearchResultBuildResult
    recorder_id: str
    label_expression: str


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
        raise ValueError("Qlib recorder does not expose native SignalRecord outputs")
    prediction = load_object("pred.pkl")
    label = load_object("label.pkl")
    ic = load_object("sig_analysis/ic.pkl")
    rank_ic = load_object("sig_analysis/ric.pkl")
    raw_metrics = cast(dict[str, object], list_metrics())
    metrics = {name: float(cast(float, raw_metrics[name])) for name in _METRIC_NAMES}
    if any(not math.isfinite(value) for value in metrics.values()):
        raise ValueError("Qlib SigAnaRecord produced a non-finite required metric")
    return prediction, label, ic, rank_ic, metrics


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
    ) -> QlibWorkflowResearchResult:
        recorder_id = qlib_recorder_id(execution_identity)
        feature = translate_safe_expression(resolved.expression).output_expression
        label = _label_expression(research_policy)
        runtime_root = output_root / "mlflow-runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_uri = runtime_root.resolve().as_uri()
        native_root = output_root / "native-records" / f"sha256-{execution_identity}"

        try:
            qlib_runtime = cast(Any, qlib)
            workflow = cast(Any, R)
            data_handler_type = cast(Any, DataHandlerLP)
            dataset_type = cast(Any, DatasetH)
            model_type = cast(Any, LGBModel)
            signal_record_type = cast(Any, SignalRecord)
            sigana_record_type = cast(Any, SigAnaRecord)
            with _WORKFLOW_LOCK:
                previous_cwd = Path.cwd()
                previous_setting = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
                os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
                os.chdir(workspace)
                try:
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
                            raise ValueError(
                                "resumed Qlib recorder has a partial native record set"
                            )
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
                                    "train": (
                                        research_policy.train.start,
                                        research_policy.train.end,
                                    ),
                                    "valid": (
                                        research_policy.validation.start,
                                        research_policy.validation.end,
                                    ),
                                    "test": (resolved.evaluation_start, resolved.evaluation_end),
                                },
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
                            model.fit(dataset, verbose_eval=0)
                            signal_record_type(model, dataset, recorder).generate()
                            sigana_record_type(recorder, ana_long_short=True).generate()
                        prediction, target, ic, rank_ic, metrics = _native_objects(recorder)
                finally:
                    os.chdir(previous_cwd)
                    if previous_setting is None:
                        os.environ.pop("MLFLOW_ALLOW_FILE_STORE", None)
                    else:
                        os.environ["MLFLOW_ALLOW_FILE_STORE"] = previous_setting
            _write_native_records(
                native_root,
                prediction=prediction,
                label=target,
                ic=ic,
                rank_ic=rank_ic,
                metrics=metrics,
            )
            built = ResearchResultArtifactBuilder().build(
                resolved,
                research_policy,
                signal_path,
                native_root,
                research_result_root,
                qlib_run_id=recorder_id,
                label_expression=label,
            )
            return QlibWorkflowResearchResult(built, recorder_id, label)
        except QlibResearchError:
            raise
        except Exception as error:
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED,
                "native Qlib Workflow execution or ResearchResult export failed",
            ) from error
