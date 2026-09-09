"""Execute safe Qlib expressions and publish immutable SignalArtifact directories."""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import qlib  # pyright: ignore[reportMissingTypeStubs]
from qlib.config import REG_CN  # pyright: ignore[reportMissingTypeStubs]
from qlib.data import D  # pyright: ignore[reportMissingTypeStubs]

from quantos.application.provenance import ProvenanceError, verify_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.qlib_view import QlibViewSpec
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.research import ResolvedExperimentSpec
from quantos.contracts.research_execution import (
    PITArtifactEvidence,
    PITCrossSectionEvidenceCollection,
    QlibExpressionTranslation,
)
from quantos.contracts.signal import SignalArtifactFile, SignalArtifactManifest, SignalRow
from quantos.contracts.status import ReasonCode
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.pit_evidence import (
    load_pit_artifact_evidence,
    pit_bundle_members,
    pit_bundle_output_temporal,
    pit_transform_lineage_hash,
)
from quantos.research.qlib.universe import QlibResearchError

SIGNAL_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("signal_time", pa.timestamp("us", tz="Asia/Shanghai"), nullable=False),
        pa.field("decision_time", pa.timestamp("us", tz="Asia/Shanghai"), nullable=False),
        pa.field("available_at", pa.timestamp("us", tz="Asia/Shanghai"), nullable=False),
        pa.field("score", pa.float64(), nullable=True),
        pa.field("score_valid", pa.bool_(), nullable=False),
        pa.field("tradable", pa.bool_(), nullable=False),
    ]
)


@dataclass(frozen=True)
class SignalArtifactBuildResult:
    reference: ArtifactRef
    manifest: SignalArtifactManifest
    path: Path


def signal_content_hash(rows: tuple[SignalRow, ...]) -> str:
    return sha256_bytes(canonical_json_bytes([row.model_dump(mode="python") for row in rows]))


def write_signal_table(rows: tuple[SignalRow, ...], path: Path) -> None:
    table = pa.Table.from_pylist(
        [
            {
                "instrument_id": row.instrument_id,
                "signal_time": row.signal_time,
                "decision_time": row.decision_time,
                "available_at": row.available_at,
                "score": row.score,
                "score_valid": row.score_valid,
                "tradable": row.tradable,
            }
            for row in rows
        ],
        schema=SIGNAL_SCHEMA,
    )
    pq.write_table(  # pyright: ignore[reportUnknownMemberType]
        table,
        path,
        compression="zstd",
        data_page_version="1.0",
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )


def _artifact_files(root: Path) -> tuple[SignalArtifactFile, ...]:
    return tuple(
        SignalArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "manifest.json"
    )


def _execute_expression(
    view_path: Path,
    qlib_ids: tuple[str, ...],
    expression: str,
    signal_date: date,
) -> dict[str, float]:
    """Delegate all factor value execution to Qlib's expression provider."""

    qlib.init(  # pyright: ignore[reportUnknownMemberType]
        provider_uri=str(view_path), region=REG_CN
    )
    frame = cast(
        pd.DataFrame,
        D.features(  # pyright: ignore[reportUnknownMemberType]
            list(qlib_ids),
            [expression],
            start_time=signal_date,
            end_time=signal_date,
            freq="day",
        ),
    )
    scores: dict[str, float] = {}
    series = cast("pd.Series[float]", frame.iloc[:, 0])
    for index, value in series.items():
        instrument = cast(tuple[str, object], index)[0]
        scores[instrument.upper()] = value
    return scores


def _execute_expression_grid(
    view_path: Path,
    qlib_ids: tuple[str, ...],
    expression: str,
    signal_dates: tuple[date, ...],
) -> dict[date, dict[str, float]]:
    """Execute one Qlib feature query for a complete production schedule grid."""

    qlib.init(  # pyright: ignore[reportUnknownMemberType]
        provider_uri=str(view_path), region=REG_CN
    )
    frame = cast(
        pd.DataFrame,
        D.features(  # pyright: ignore[reportUnknownMemberType]
            list(qlib_ids),
            [expression],
            start_time=min(signal_dates),
            end_time=max(signal_dates),
            freq="day",
        ),
    )
    requested_dates = set(signal_dates)
    scores: dict[date, dict[str, float]] = {item: {} for item in signal_dates}
    series = cast("pd.Series[float]", frame.iloc[:, 0])
    for index, value in series.items():
        instrument, timestamp = cast(tuple[str, object], index)
        trade_date = cast("pd.Timestamp", timestamp).date()
        if trade_date in requested_dates:
            scores[trade_date][instrument.upper()] = value
    return scores


def _load_tradability(
    view_path: Path, signal_dates: tuple[date, ...]
) -> dict[tuple[date, str], dict[str, object]]:
    rows = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        view_path / "sidecars" / "tradability.parquet",
        columns=[
            "instrument_id",
            "trade_date",
            "is_suspended",
            "is_st",
            "available_at",
        ],
        filters=[("trade_date", "in", list(signal_dates))],
    ).to_pylist()
    return {(cast(date, row["trade_date"]), cast(str, row["instrument_id"])): row for row in rows}


def _validate_execution_bindings(
    resolved: ResolvedExperimentSpec,
    evidence: PITArtifactEvidence,
    view_path: Path,
) -> tuple[QlibExpressionTranslation, dict[str, str]]:
    try:
        view = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if (
        view.view_hash != resolved.qlib_view_hash
        or view.source_snapshot_hash != resolved.snapshot_hash
        or view.view_spec_hash != resolved.qlib_view_spec_hash
        or view.qlib_version != resolved.qlib_version
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "resolved experiment does not match the verified Qlib view",
        )
    if (
        evidence.content_hash != resolved.pit_audit_evidence_hash
        or evidence.snapshot_hash != resolved.snapshot_hash
        or evidence.expression_spec_hash != resolved.expression.content_hash
        or evidence.universe_index != resolved.strategy.universe_index
        or (
            isinstance(evidence, PITCrossSectionEvidenceCollection)
            and evidence.qlib_view_hash != resolved.qlib_view_hash
        )
    ):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "PIT evidence does not match the resolved experiment",
        )
    for bundle in evidence.bundles:
        if not (
            resolved.evaluation_start
            <= bundle.schedule.decision_time.date()
            <= resolved.evaluation_end
        ):
            raise QlibResearchError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "signal decision falls outside the resolved evaluation range",
            )
    translation = translate_safe_expression(resolved.expression)
    try:
        view_spec = QlibViewSpec.model_validate_json((view_path / "view-spec.json").read_bytes())
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view spec is invalid"
        ) from error
    mappings = {mapping.instrument_id: mapping.qlib_id for mapping in view_spec.mappings}
    return translation, mappings


def verify_signal_artifact(path: Path) -> SignalArtifactManifest:
    try:
        tree_files = regular_tree_files(path)
        manifest = SignalArtifactManifest.model_validate_json((path / "manifest.json").read_bytes())
    except (OSError, ValueError, ArtifactIntegrityError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal manifest is invalid"
        ) from error
    if path.name != f"sha256-{manifest.artifact_hash}":
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal directory does not match artifact hash"
        )
    expected_paths = {item.logical_path for item in manifest.files}
    actual_paths = {
        item.relative_to(path).as_posix() for item in tree_files if item.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal artifact file set does not match manifest"
        )
    for item in manifest.files:
        try:
            verify_file(path / item.logical_path, item.sha256)
        except (OSError, ArtifactIntegrityError) as error:
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                f"signal artifact file failed verification: {item.logical_path}",
            ) from error

    try:
        resolved = ResolvedExperimentSpec.model_validate_json(
            (path / "resolved-experiment.json").read_bytes()
        )
        translation = QlibExpressionTranslation.model_validate_json(
            (path / "expression-translation.json").read_bytes()
        )
        evidence = load_pit_artifact_evidence(path / "pit-evidence.json")
        table = pq.read_table(path / "signals.parquet")  # pyright: ignore[reportUnknownMemberType]
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal artifact payload is invalid"
        ) from error
    if table.schema != SIGNAL_SCHEMA:
        raise QlibResearchError(ReasonCode.ARTIFACT_CORRUPTED, "signal schema does not match v2")
    try:
        rows = tuple(SignalRow.model_validate(row) for row in table.to_pylist())
    except ValueError as error:
        raise QlibResearchError(ReasonCode.ARTIFACT_CORRUPTED, "signal rows are invalid") from error
    keys = [(row.signal_time, row.instrument_id) for row in rows]
    if not rows or keys != sorted(keys) or len(keys) != len(set(keys)):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal rows must be nonempty, sorted, and unique"
        )
    pit_rows = {
        (bundle.schedule.signal_time, instrument_id): (
            bundle.schedule,
            pit_bundle_output_temporal(bundle, instrument_id),
        )
        for bundle in evidence.bundles
        for instrument_id in pit_bundle_members(bundle)
    }
    if set(pit_rows) != {(row.signal_time, row.instrument_id) for row in rows}:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal rows do not exactly match PIT evidence members"
        )
    for row in rows:
        schedule, output_temporal = pit_rows[(row.signal_time, row.instrument_id)]
        if (
            row.signal_time != schedule.signal_time
            or row.decision_time != schedule.decision_time
            or row.available_at != output_temporal.available_at
        ):
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED, "signal row does not match PIT temporal evidence"
            )
    bindings_match = (
        resolved.content_hash == manifest.resolved_experiment_hash
        and resolved.expression.content_hash == manifest.source_expression_or_model_hash
        and resolved.snapshot_hash == manifest.snapshot_hash
        and resolved.qlib_version == manifest.qlib_version
        and resolved.qlib_view_spec_hash == manifest.qlib_view_spec_hash
        and resolved.qlib_view_hash == manifest.qlib_view_hash
        and resolved.pit_audit_evidence_hash == manifest.pit_evidence_hash
        and evidence.content_hash == manifest.pit_evidence_hash
        and translation.content_hash == manifest.expression_translation_hash
        and translation.expression_spec_hash == resolved.expression.content_hash
        and pit_transform_lineage_hash(evidence) == manifest.transform_lineage_hash
        and len(rows) == manifest.row_count
        and rows[0].signal_time == manifest.signal_start
        and rows[-1].signal_time == manifest.signal_end
        and signal_content_hash(rows) == manifest.signal_content_hash
    )
    if not bindings_match:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "signal manifest bindings are inconsistent"
        )
    return manifest


class FactorSignalArtifactBuilder:
    """Thin artifact adapter; Qlib remains the factor execution engine."""

    def build(
        self,
        resolved: ResolvedExperimentSpec,
        evidence: PITArtifactEvidence,
        view_path: Path,
        output_root: Path,
        *,
        workspace: Path | None = None,
    ) -> SignalArtifactBuildResult:
        try:
            verify_code_provenance(
                workspace or Path.cwd(),
                expected_commit_hash=resolved.code_commit_hash,
                expected_lockfile_hash=resolved.lockfile_hash,
            )
        except ProvenanceError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        translation, mappings = _validate_execution_bindings(resolved, evidence, view_path)
        bundles = evidence.bundles
        tradability = _load_tradability(
            view_path,
            tuple(bundle.schedule.signal_time.date() for bundle in bundles),
        )
        grid_scores: dict[date, dict[str, float]] | None = None
        if len(bundles) > 1:
            all_members = sorted(
                {member for bundle in bundles for member in pit_bundle_members(bundle)}
            )
            try:
                grid_scores = _execute_expression_grid(
                    view_path,
                    tuple(mappings[item] for item in all_members),
                    translation.output_expression,
                    tuple(bundle.schedule.signal_time.date() for bundle in bundles),
                )
            except Exception:
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED,
                    "Qlib expression grid execution failed",
                ) from None
        rows: list[SignalRow] = []
        for bundle in bundles:
            members = pit_bundle_members(bundle)
            try:
                qlib_ids = tuple(mappings[item] for item in members)
            except KeyError as error:
                raise QlibResearchError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "PIT member is absent from the Qlib view mapping",
                ) from error
            signal_date = bundle.schedule.signal_time.date()
            if grid_scores is None:
                try:
                    scores = _execute_expression(
                        view_path, qlib_ids, translation.output_expression, signal_date
                    )
                except Exception:
                    raise QlibResearchError(
                        ReasonCode.QLIB_EXECUTION_FAILED,
                        "Qlib expression execution failed",
                    ) from None
            else:
                scores = {
                    qlib_id: value
                    for qlib_id, value in grid_scores[signal_date].items()
                    if qlib_id in set(qlib_ids)
                }
            if not set(scores) <= set(qlib_ids):
                raise QlibResearchError(
                    ReasonCode.QLIB_EXECUTION_FAILED,
                    "Qlib expression returned an instrument outside the requested PIT universe",
                )
            for instrument_id in members:
                status = tradability.get((signal_date, instrument_id))
                output_temporal = pit_bundle_output_temporal(bundle, instrument_id)
                qlib_score = scores.get(mappings[instrument_id])
                score_valid = qlib_score is not None and math.isfinite(qlib_score)
                if status is None and score_valid:
                    raise QlibResearchError(
                        ReasonCode.SOURCE_INCOMPLETE,
                        f"finite signal lacks tradability evidence for {instrument_id}",
                    )
                if (
                    status is not None
                    and cast(datetime, status["available_at"]) > bundle.schedule.signal_time
                ):
                    raise QlibResearchError(
                        ReasonCode.LOOK_AHEAD,
                        f"tradability is unavailable at signal time for {instrument_id}",
                    )
                rows.append(
                    SignalRow(
                        instrument_id=instrument_id,
                        signal_time=bundle.schedule.signal_time,
                        decision_time=bundle.schedule.decision_time,
                        available_at=output_temporal.available_at,
                        score=qlib_score if score_valid else None,
                        score_valid=score_valid,
                        tradable=status is not None
                        and not cast(bool, status["is_st"])
                        and not cast(bool, status["is_suspended"]),
                    )
                )
        canonical_rows = tuple(
            sorted(rows, key=lambda item: (item.signal_time, item.instrument_id))
        )

        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".signal-work-", dir=output_root) as temporary:
            staging = Path(temporary) / "signal"
            staging.mkdir()
            atomic_write_bytes(staging / "resolved-experiment.json", resolved.canonical_bytes())
            atomic_write_bytes(
                staging / "expression-translation.json", translation.canonical_bytes()
            )
            atomic_write_bytes(staging / "pit-evidence.json", evidence.canonical_bytes())
            write_signal_table(canonical_rows, staging / "signals.parquet")
            files = _artifact_files(staging)
            manifest = SignalArtifactManifest.create(
                resolved_experiment_hash=resolved.content_hash,
                source_expression_or_model_hash=resolved.expression.content_hash,
                snapshot_hash=resolved.snapshot_hash,
                qlib_version=resolved.qlib_version,
                qlib_view_spec_hash=resolved.qlib_view_spec_hash,
                qlib_view_hash=resolved.qlib_view_hash,
                qlib_run_id=None,
                pit_evidence_hash=evidence.content_hash,
                transform_lineage_hash=pit_transform_lineage_hash(evidence),
                expression_translation_hash=translation.content_hash,
                row_count=len(canonical_rows),
                signal_start=canonical_rows[0].signal_time,
                signal_end=canonical_rows[-1].signal_time,
                signal_content_hash=signal_content_hash(canonical_rows),
                files=files,
                created_at=datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = output_root / f"sha256-{manifest.artifact_hash}"
            if destination.exists():
                published = verify_signal_artifact(destination)
            else:
                publish_directory(staging, destination)
                published = verify_signal_artifact(destination)

        size_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
        return SignalArtifactBuildResult(
            reference=ArtifactRef(
                kind="signal_artifact",
                sha256=published.artifact_hash,
                size_bytes=size_bytes,
                media_type="application/vnd.quantos.signal-directory",
                logical_path=f"research/signals/{destination.name}",
            ),
            manifest=published,
            path=destination,
        )
