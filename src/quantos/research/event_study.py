"""Deterministic event-study primitives over an immutable canonical snapshot."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from statistics import fmean
from typing import cast

import pyarrow.parquet as pq
from pydantic import ValidationError

from quantos.application.event_features import (
    EventFeatureError,
    verify_event_feature_artifact,
)
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    publish_directory,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.event_research import (
    EventFeatureArtifactManifest,
    EventStudyArtifactFile,
    EventStudyArtifactManifest,
    EventStudyMetric,
    EventStudyRow,
    EventStudySpec,
    EventStudySummary,
)
from quantos.contracts.evidence import EventFeatureArtifact
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode
from quantos.data.snapshot import SnapshotBuildError, verify_snapshot


class EventStudyError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class EventStudyBuildResult:
    reference: ArtifactRef
    manifest: EventStudyArtifactManifest
    summary: EventStudySummary
    rows: tuple[EventStudyRow, ...]
    path: Path


def _read_rows(path: Path, columns: list[str]) -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        pq.read_table(  # pyright: ignore[reportUnknownMemberType]
            path, columns=columns
        ).to_pylist(),
    )


def _adjusted_closes(snapshot_path: Path) -> dict[tuple[str, date], float]:
    bars = _read_rows(
        snapshot_path / "canonical" / "bars.parquet",
        ["instrument_id", "trade_date", "close"],
    )
    factors = _read_rows(
        snapshot_path / "canonical" / "adjustment_factors.parquet",
        ["instrument_id", "trade_date", "adjustment_factor"],
    )
    factor_map = {
        (cast(str, item["instrument_id"]), cast(date, item["trade_date"])): cast(
            float, item["adjustment_factor"]
        )
        for item in factors
    }
    values: dict[tuple[str, date], float] = {}
    for item in bars:
        key = (cast(str, item["instrument_id"]), cast(date, item["trade_date"]))
        factor = factor_map.get(key)
        if factor is None:
            raise EventStudyError(
                ReasonCode.SOURCE_INCOMPLETE,
                "event-study bar has no same-session adjustment factor",
            )
        value = cast(float, item["close"]) * factor
        if not math.isfinite(value) or value <= 0:
            raise EventStudyError(
                ReasonCode.SCHEMA_INVALID,
                "event-study adjusted close is not finite and positive",
            )
        values[key] = value
    return values


def _benchmark_closes(snapshot_path: Path) -> dict[tuple[str, date], float]:
    rows = _read_rows(
        snapshot_path / "canonical" / "benchmark_bars.parquet",
        ["benchmark_id", "trade_date", "close"],
    )
    values = {
        (cast(str, item["benchmark_id"]), cast(date, item["trade_date"])): cast(
            float, item["close"]
        )
        for item in rows
    }
    if any(not math.isfinite(value) or value <= 0 for value in values.values()):
        raise EventStudyError(
            ReasonCode.SCHEMA_INVALID,
            "event-study benchmark close is not finite and positive",
        )
    return values


def _open_sessions(snapshot_path: Path) -> dict[str, tuple[date, ...]]:
    rows = _read_rows(
        snapshot_path / "canonical" / "calendar.parquet",
        ["exchange", "trade_date", "is_open"],
    )
    grouped: dict[str, set[date]] = {}
    for item in rows:
        if item["is_open"] is True:
            grouped.setdefault(cast(str, item["exchange"]), set()).add(
                cast(date, item["trade_date"])
            )
    return {key: tuple(sorted(values)) for key, values in grouped.items()}


def _total_return(values: dict[tuple[str, date], float], key: str, start: date, end: date) -> float:
    try:
        first = values[(key, start)]
        last = values[(key, end)]
    except KeyError as error:
        raise EventStudyError(
            ReasonCode.SOURCE_INCOMPLETE,
            "event-study window is missing a required close",
        ) from error
    return last / first - 1.0


def _car(
    stock: dict[tuple[str, date], float],
    benchmark: dict[tuple[str, date], float],
    entity: str,
    benchmark_id: str,
    dates: tuple[date, ...],
) -> float:
    total = 0.0
    for left, right in pairwise(dates):
        total += _total_return(stock, entity, left, right) - _total_return(
            benchmark, benchmark_id, left, right
        )
    return total


def _artifact_files(root: Path) -> tuple[EventStudyArtifactFile, ...]:
    return tuple(
        EventStudyArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in regular_tree_files(root)
        if path.name != "manifest.json"
    )


def build_event_study(
    *,
    feature_artifact_path: Path,
    snapshot_path: Path,
    spec: EventStudySpec,
    output_root: Path,
) -> EventStudyBuildResult:
    """Compute only the metrics admitted by EventStudyMetric; this is not a backtest."""

    try:
        feature_manifest = verify_event_feature_artifact(feature_artifact_path)
        snapshot = verify_snapshot(snapshot_path)
    except (EventFeatureError, SnapshotBuildError) as error:
        raise EventStudyError(error.reason_code, str(error)) from None
    if (
        spec.event_feature_artifact_hash != feature_manifest.artifact_hash
        or spec.snapshot_hash != snapshot.snapshot_hash
        or feature_manifest.snapshot_hash != snapshot.snapshot_hash
    ):
        raise EventStudyError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "event-study inputs do not bind the same frozen market snapshot",
        )
    try:
        feature = EventFeatureArtifact.model_validate_json(
            (feature_artifact_path / "feature.json").read_bytes()
        )
    except (OSError, ValidationError) as error:
        raise EventStudyError(
            ReasonCode.ARTIFACT_CORRUPTED, "event feature payload is invalid"
        ) from error
    stock = _adjusted_closes(snapshot_path)
    benchmark = _benchmark_closes(snapshot_path)
    sessions = _open_sessions(snapshot_path)
    study_rows: list[EventStudyRow] = []
    for event in feature.rows:
        exchange = "SSE" if event.entity_ref.endswith(".SH") else "SZSE"
        market_sessions = sessions.get(exchange, ())
        try:
            event_index = market_sessions.index(event.effective_trade_date)
            window_dates = market_sessions[
                event_index + spec.window_start : event_index + spec.window_end + 1
            ]
        except ValueError as error:
            raise EventStudyError(
                ReasonCode.SOURCE_INCOMPLETE,
                "event effective date is not an open session",
            ) from error
        expected_length = spec.window_end - spec.window_start + 1
        if len(window_dates) != expected_length:
            raise EventStudyError(
                ReasonCode.SOURCE_INCOMPLETE,
                "snapshot does not cover the complete event-study window",
            )
        start_date, end_date = window_dates[0], window_dates[-1]
        stock_return = _total_return(stock, event.entity_ref, start_date, end_date)
        benchmark_return = _total_return(benchmark, spec.benchmark_id, start_date, end_date)
        cumulative_abnormal_return = _car(
            stock,
            benchmark,
            event.entity_ref,
            spec.benchmark_id,
            window_dates,
        )
        study_rows.append(
            EventStudyRow(
                entity_ref=event.entity_ref,
                event_trade_date=event.effective_trade_date,
                window_start_date=start_date,
                window_end_date=end_date,
                stock_return=stock_return,
                benchmark_return=benchmark_return,
                abnormal_return=stock_return - benchmark_return,
                cumulative_abnormal_return=cumulative_abnormal_return,
            )
        )
    rows = tuple(sorted(study_rows, key=lambda item: (item.event_trade_date, item.entity_ref)))
    if not rows:
        raise EventStudyError(ReasonCode.SOURCE_INCOMPLETE, "event study has no qualified rows")
    metric_set = set(spec.metrics)
    summary = EventStudySummary(
        event_count=len(rows),
        mean_abnormal_return=(
            fmean(item.abnormal_return for item in rows)
            if EventStudyMetric.MEAN_ABNORMAL_RETURN in metric_set
            else None
        ),
        mean_car=(
            fmean(item.cumulative_abnormal_return for item in rows)
            if EventStudyMetric.MEAN_CAR in metric_set
            else None
        ),
    )
    encoded_rows = canonical_json_bytes([item.model_dump(mode="python") for item in rows])
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".event-study-", dir=output_root))
    try:
        atomic_write_bytes(
            temporary / "event-feature-manifest.json",
            canonical_json_bytes(feature_manifest.model_dump(mode="python")),
        )
        atomic_write_bytes(temporary / "event-study-rows.json", encoded_rows)
        atomic_write_bytes(temporary / "event-study-spec.json", spec.canonical_bytes())
        atomic_write_bytes(temporary / "event-study-summary.json", summary.canonical_bytes())
        manifest = EventStudyArtifactManifest.create(
            spec_hash=spec.content_hash,
            event_feature_artifact_hash=feature_manifest.artifact_hash,
            event_feature_hash=feature.content_hash,
            snapshot_hash=snapshot.snapshot_hash,
            row_count=len(rows),
            rows_hash=sha256_bytes(encoded_rows),
            summary_hash=summary.content_hash,
            files=_artifact_files(temporary),
        )
        atomic_write_bytes(
            temporary / "manifest.json",
            canonical_json_bytes(manifest.model_dump(mode="python")),
        )
        destination = output_root / f"sha256-{manifest.artifact_hash}"
        if destination.exists():
            existing = verify_event_study(destination)
            if existing != manifest:
                raise EventStudyError(
                    ReasonCode.DUPLICATE_ID_CONFLICT,
                    "existing event-study artifact differs from rebuild",
                )
            shutil.rmtree(temporary)
        else:
            publish_directory(temporary, destination)
        verified = verify_event_study(destination)
        encoded_manifest = (destination / "manifest.json").read_bytes()
        return EventStudyBuildResult(
            reference=ArtifactRef(
                kind="event-study",
                sha256=verified.artifact_hash,
                size_bytes=len(encoded_manifest),
                media_type="application/json",
                logical_path=destination.name,
            ),
            manifest=verified,
            summary=summary,
            rows=rows,
            path=destination,
        )
    except EventStudyError:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    except (OSError, ValueError, ArtifactConflictError, ArtifactIntegrityError) as error:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise EventStudyError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event-study publication failed deterministic verification",
        ) from error


def verify_event_study(path: Path) -> EventStudyArtifactManifest:
    try:
        manifest = EventStudyArtifactManifest.model_validate_json(
            confined_regular_file(path, "manifest.json").read_bytes()
        )
        if path.name != f"sha256-{manifest.artifact_hash}":
            raise ValueError("event-study directory does not bind manifest hash")
        actual = {
            item.relative_to(path).as_posix()
            for item in regular_tree_files(path)
            if item.name != "manifest.json"
        }
        if actual != {item.logical_path for item in manifest.files}:
            raise ValueError("event-study exact-file set disagrees")
        for item in manifest.files:
            target = confined_regular_file(path, item.logical_path)
            verify_file(target, item.sha256)
            if target.stat().st_size != item.size_bytes:
                raise ValueError("event-study file size disagrees")
        spec = EventStudySpec.model_validate_json((path / "event-study-spec.json").read_bytes())
        summary = EventStudySummary.model_validate_json(
            (path / "event-study-summary.json").read_bytes()
        )
        feature_manifest = EventFeatureArtifactManifest.model_validate_json(
            (path / "event-feature-manifest.json").read_bytes()
        )
        raw_rows = json.loads((path / "event-study-rows.json").read_bytes())
        rows = tuple(EventStudyRow.model_validate(item) for item in raw_rows)
        rows_bytes = canonical_json_bytes([item.model_dump(mode="python") for item in rows])
        expected_abnormal = (
            fmean(item.abnormal_return for item in rows)
            if EventStudyMetric.MEAN_ABNORMAL_RETURN in spec.metrics
            else None
        )
        expected_car = (
            fmean(item.cumulative_abnormal_return for item in rows)
            if EventStudyMetric.MEAN_CAR in spec.metrics
            else None
        )
        if (
            spec.content_hash != manifest.spec_hash
            or spec.event_feature_artifact_hash != feature_manifest.artifact_hash
            or feature_manifest.artifact_hash != manifest.event_feature_artifact_hash
            or feature_manifest.feature_hash != manifest.event_feature_hash
            or spec.snapshot_hash != manifest.snapshot_hash
            or len(rows) != manifest.row_count
            or sha256_bytes(rows_bytes) != manifest.rows_hash
            or summary.content_hash != manifest.summary_hash
            or summary.event_count != len(rows)
            or summary.mean_abnormal_return != expected_abnormal
            or summary.mean_car != expected_car
        ):
            raise ValueError("event-study authority bindings disagree")
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError):
        raise EventStudyError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event-study artifact failed exact-file or hash verification",
        ) from None
    return manifest
