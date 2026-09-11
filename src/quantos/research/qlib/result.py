"""Deterministic immutable adapter for Qlib SignalRecord/SigAnaRecord outputs."""

from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import ResearchPolicy, ResolvedExperimentSpec
from quantos.contracts.research_result import (
    ResearchResultArtifactFile,
    ResearchResultManifest,
    ResearchResultMetric,
    ResearchResultSeriesRow,
    ResearchResultSourceFile,
    ResearchResultValueRow,
)
from quantos.contracts.status import ReasonCode
from quantos.research.qlib.signal import verify_signal_artifact
from quantos.research.qlib.universe import QlibResearchError

SourcePath = Literal[
    "label.pkl", "metrics.json", "pred.pkl", "sig_analysis/ic.pkl", "sig_analysis/ric.pkl"
]
MetricName = Literal["IC", "ICIR", "Rank IC", "Rank ICIR"]

_SOURCE_PATHS: tuple[SourcePath, ...] = (
    "label.pkl",
    "metrics.json",
    "pred.pkl",
    "sig_analysis/ic.pkl",
    "sig_analysis/ric.pkl",
)
_METRIC_NAMES: tuple[MetricName, ...] = ("IC", "ICIR", "Rank IC", "Rank ICIR")


@dataclass(frozen=True)
class ResearchResultBuildResult:
    reference: ArtifactRef
    manifest: ResearchResultManifest
    path: Path


def _value_rows(value: object, *, name: str) -> tuple[ResearchResultValueRow, ...]:
    series: pd.Series[Any]
    if isinstance(value, pd.Series):
        series = cast("pd.Series[Any]", value)
    elif isinstance(value, pd.DataFrame) and value.shape[1] == 1:
        series = value.iloc[:, 0]
    else:
        raise ValueError(f"{name} must be a one-column pandas object")
    rows: list[ResearchResultValueRow] = []
    for raw_key, raw_value in series.items():
        if not isinstance(raw_key, tuple):
            raise ValueError(f"{name} requires a two-level Qlib index")
        key = cast(tuple[object, ...], raw_key)
        if len(key) != 2:
            raise ValueError(f"{name} requires a two-level Qlib index")
        instrument = next((item for item in key if isinstance(item, str)), None)
        timestamp = next(
            (item for item in key if not isinstance(item, str)),
            None,
        )
        if instrument is None or timestamp is None:
            raise ValueError(f"{name} index must bind instrument and datetime")
        numeric = float(raw_value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name} contains a non-finite value")
        rows.append(
            ResearchResultValueRow(
                trade_date=_trade_date(timestamp),
                qlib_instrument_id=instrument.upper(),
                value=numeric,
            )
        )
    ordered = tuple(sorted(rows, key=lambda item: (item.trade_date, item.qlib_instrument_id)))
    keys = [(item.trade_date, item.qlib_instrument_id) for item in ordered]
    if not ordered or len(keys) != len(set(keys)):
        raise ValueError(f"{name} rows must be nonempty and unique")
    return ordered


def _series_rows(value: object, *, name: str) -> tuple[ResearchResultSeriesRow, ...]:
    if not isinstance(value, pd.Series):
        raise ValueError(f"{name} must be a pandas Series produced by SigAnaRecord")
    series = cast("pd.Series[Any]", value)
    rows = tuple(
        sorted(
            (
                ResearchResultSeriesRow(
                    trade_date=_trade_date(index), value=float(raw_value)
                )
                for index, raw_value in series.items()
            ),
            key=lambda item: item.trade_date,
        )
    )
    if not rows or len({item.trade_date for item in rows}) != len(rows):
        raise ValueError(f"{name} rows must be nonempty and unique")
    return rows


def _trade_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("Qlib result index must contain daily timestamps")


def _row_bytes(rows: tuple[CanonicalContract, ...]) -> bytes:
    return canonical_json_bytes([row.model_dump(mode="python") for row in rows])


def _artifact_files(root: Path) -> tuple[ResearchResultArtifactFile, ...]:
    return tuple(
        ResearchResultArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "manifest.json"
    )


def _load_rows(
    path: Path,
    model: type[ResearchResultValueRow] | type[ResearchResultSeriesRow],
) -> tuple[CanonicalContract, ...]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, list):
        raise ValueError("ResearchResult row payload must be a list")
    return tuple(model.model_validate(item) for item in cast(list[object], payload))


def verify_research_result(path: Path) -> ResearchResultManifest:
    try:
        tree = regular_tree_files(path)
        manifest = ResearchResultManifest.model_validate_json((path / "manifest.json").read_bytes())
        if path.name != f"sha256-{manifest.artifact_hash}":
            raise ValueError("ResearchResult directory name disagrees with its hash")
        actual = {
            item.relative_to(path).as_posix() for item in tree if item.name != "manifest.json"
        }
        expected = {item.logical_path for item in manifest.files}
        if actual != expected:
            raise ValueError("ResearchResult exact file set disagrees")
        for item in manifest.files:
            verify_file(path / item.logical_path, item.sha256)
        resolved = ResolvedExperimentSpec.model_validate_json(
            (path / "resolved-experiment.json").read_bytes()
        )
        policy = ResearchPolicy.model_validate_json((path / "research-policy.json").read_bytes())
        predictions = _load_rows(path / "predictions.json", ResearchResultValueRow)
        labels = _load_rows(path / "labels.json", ResearchResultValueRow)
        ic = _load_rows(path / "ic-series.json", ResearchResultSeriesRow)
        rank_ic = _load_rows(path / "rank-ic-series.json", ResearchResultSeriesRow)
        if (
            resolved.content_hash != manifest.resolved_experiment_hash
            or resolved.expression.content_hash != manifest.expression_spec_hash
            or resolved.snapshot_hash != manifest.snapshot_hash
            or resolved.qlib_view_hash != manifest.qlib_view_hash
            or resolved.qlib_version != manifest.qlib_version
            or policy.content_hash != manifest.research_policy_hash
            or policy.label_horizon_trading_sessions
            != manifest.label_horizon_trading_sessions
            or len(predictions) != manifest.prediction_row_count
            or len(labels) != manifest.label_row_count
            or len(ic) != manifest.ic_row_count
            or len(rank_ic) != manifest.rank_ic_row_count
            or sha256_bytes(_row_bytes(predictions)) != manifest.prediction_content_hash
            or sha256_bytes(_row_bytes(labels)) != manifest.label_content_hash
            or sha256_bytes(_row_bytes(ic)) != manifest.ic_content_hash
            or sha256_bytes(_row_bytes(rank_ic)) != manifest.rank_ic_content_hash
        ):
            raise ValueError("ResearchResult bindings are inconsistent")
    except (OSError, ValueError, TypeError, ArtifactIntegrityError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "ResearchResult artifact verification failed"
        ) from error
    return manifest


class ResearchResultArtifactBuilder:
    """Export Qlib-owned metrics; this adapter never calculates IC or Rank IC."""

    def build(
        self,
        resolved: ResolvedExperimentSpec,
        research_policy: ResearchPolicy,
        signal_path: Path,
        native_record_root: Path,
        output_root: Path,
        *,
        qlib_run_id: str,
        label_expression: str,
        created_at: datetime | None = None,
    ) -> ResearchResultBuildResult:
        try:
            signal = verify_signal_artifact(signal_path)
            if signal.resolved_experiment_hash != resolved.content_hash:
                raise ValueError("signal does not bind the resolved experiment")
            source_files = tuple(
                ResearchResultSourceFile(
                    logical_path=relative,
                    sha256=sha256_file(native_record_root / relative),
                    size_bytes=(native_record_root / relative).stat().st_size,
                )
                for relative in _SOURCE_PATHS
            )
            predictions = _value_rows(
                pd.read_pickle(native_record_root / "pred.pkl"), name="prediction"
            )
            labels = _value_rows(pd.read_pickle(native_record_root / "label.pkl"), name="label")
            if {(row.trade_date, row.qlib_instrument_id) for row in predictions} != {
                (row.trade_date, row.qlib_instrument_id) for row in labels
            }:
                raise ValueError("Qlib prediction and label keys disagree")
            ic = _series_rows(pd.read_pickle(native_record_root / "sig_analysis/ic.pkl"), name="IC")
            rank_ic = _series_rows(
                pd.read_pickle(native_record_root / "sig_analysis/ric.pkl"), name="Rank IC"
            )
            native_metrics = json.loads((native_record_root / "metrics.json").read_bytes())
            metrics = tuple(
                ResearchResultMetric(name=name, value=float(native_metrics[name]))
                for name in _METRIC_NAMES
            )
        except QlibResearchError:
            raise
        except (OSError, ValueError, TypeError, KeyError, ArtifactIntegrityError) as error:
            raise QlibResearchError(
                ReasonCode.QLIB_EXECUTION_FAILED,
                "Qlib native SignalRecord/SigAnaRecord output is incomplete or invalid",
            ) from error

        payloads = {
            "ic-series.json": _row_bytes(ic),
            "labels.json": _row_bytes(labels),
            "predictions.json": _row_bytes(predictions),
            "rank-ic-series.json": _row_bytes(rank_ic),
            "research-policy.json": research_policy.canonical_bytes(),
            "resolved-experiment.json": resolved.canonical_bytes(),
        }
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".research-result-work-", dir=output_root
        ) as temporary:
            staging = Path(temporary) / "research-result"
            staging.mkdir()
            for name, data in payloads.items():
                atomic_write_bytes(staging / name, data)
            files = _artifact_files(staging)
            manifest = ResearchResultManifest.create(
                resolved_experiment_hash=resolved.content_hash,
                signal_artifact_hash=signal.artifact_hash,
                expression_spec_hash=resolved.expression.content_hash,
                research_policy_hash=research_policy.content_hash,
                snapshot_hash=resolved.snapshot_hash,
                qlib_view_hash=resolved.qlib_view_hash,
                qlib_version=resolved.qlib_version,
                qlib_run_id=qlib_run_id,
                segment="test",
                label_expression=label_expression,
                label_horizon_trading_sessions=research_policy.label_horizon_trading_sessions,
                prediction_row_count=len(predictions),
                label_row_count=len(labels),
                ic_row_count=len(ic),
                rank_ic_row_count=len(rank_ic),
                prediction_content_hash=sha256_bytes(payloads["predictions.json"]),
                label_content_hash=sha256_bytes(payloads["labels.json"]),
                ic_content_hash=sha256_bytes(payloads["ic-series.json"]),
                rank_ic_content_hash=sha256_bytes(payloads["rank-ic-series.json"]),
                metrics=metrics,
                source_files=source_files,
                files=files,
                created_at=created_at or datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = output_root / f"sha256-{manifest.artifact_hash}"
            if destination.exists():
                published = verify_research_result(destination)
            else:
                publish_directory(staging, destination)
                published = verify_research_result(destination)
        size_bytes = sum(item.stat().st_size for item in destination.rglob("*") if item.is_file())
        return ResearchResultBuildResult(
            reference=ArtifactRef(
                kind="research_result",
                sha256=published.artifact_hash,
                size_bytes=size_bytes,
                media_type="application/vnd.quantos.research-result+directory",
                logical_path=f"research/results/{destination.name}",
            ),
            manifest=published,
            path=destination,
        )
