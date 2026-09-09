"""Bridge admitted event features into the existing Qlib signal/backtest boundary."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from pydantic import ValidationError

from quantos.application.event_features import (
    EventFeatureError,
    verify_event_feature_artifact,
)
from quantos.application.provenance import ProvenanceError, verify_code_provenance
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
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.event_research import (
    EventFeatureArtifactManifest,
    EventSignalAlignmentPolicy,
    EventSignalArtifactFile,
    EventSignalArtifactManifest,
    EventSignalEvidence,
    EventSignalEvidenceItem,
    ResolvedEventExperimentSpec,
)
from quantos.contracts.evidence import EventFeatureArtifact, EventFeatureRow
from quantos.contracts.qlib_view import QlibViewSpec
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.signal import SignalRow
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.research.qlib.signal import SIGNAL_SCHEMA, signal_content_hash, write_signal_table
from quantos.research.qlib.universe import QlibResearchError

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class EventSignalArtifactBuildResult:
    reference: ArtifactRef
    manifest: EventSignalArtifactManifest
    path: Path


def _calendar_dates(view_path: Path) -> tuple[date, ...]:
    try:
        values = tuple(
            date.fromisoformat(line.strip())
            for line in (view_path / "calendars" / "day.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib event-signal calendar cannot be read"
        ) from error
    if not values or values != tuple(sorted(set(values))):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "Qlib event-signal calendar must be nonempty, sorted, and unique",
        )
    return values


def _weekly_schedule(
    effective_date: date,
    calendar: tuple[date, ...],
    policy: EventSignalAlignmentPolicy,
) -> DecisionSchedule:
    index_by_date = {value: index for index, value in enumerate(calendar)}
    effective_index = index_by_date.get(effective_date)
    if effective_index is None:
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "event effective session is absent from the verified Qlib calendar",
        )
    signal_index = effective_index
    effective_week = effective_date.isocalendar()[:2]
    while (
        signal_index + 1 < len(calendar)
        and calendar[signal_index + 1].isocalendar()[:2] == effective_week
    ):
        signal_index += 1
    if signal_index - effective_index > policy.max_alignment_lag_sessions:
        raise QlibResearchError(
            ReasonCode.OOS_POLICY_VIOLATION,
            "event-to-week-end alignment exceeds the frozen lag budget",
        )
    if signal_index + policy.execution_lag_trading_sessions >= len(calendar):
        raise QlibResearchError(
            ReasonCode.OOS_POLICY_VIOLATION,
            "event signal has no following Qlib execution session",
        )
    signal_date = calendar[signal_index]
    execution_date = calendar[signal_index + policy.execution_lag_trading_sessions]
    return DecisionSchedule(
        signal_time=datetime.combine(signal_date, time.fromisoformat(policy.signal_time), SHANGHAI),
        signal_available_at=datetime.combine(
            signal_date, time.fromisoformat(policy.signal_available_time), SHANGHAI
        ),
        decision_time=datetime.combine(
            signal_date, time.fromisoformat(policy.decision_time), SHANGHAI
        ),
        execution_time=datetime.combine(
            execution_date, time.fromisoformat(policy.execution_time), SHANGHAI
        ),
    )


def _derive_evidence_items(
    feature: EventFeatureArtifact,
    view_spec: QlibViewSpec,
    calendar: tuple[date, ...],
    alignment_policy: EventSignalAlignmentPolicy,
    evaluation_start: date,
    evaluation_end: date,
) -> tuple[EventSignalEvidenceItem, ...]:
    mapped_entities = {item.instrument_id for item in view_spec.mappings}
    grouped: dict[tuple[datetime, str, str], list[EventFeatureRow]] = defaultdict(list)
    schedules: dict[tuple[datetime, str, str], DecisionSchedule] = {}
    for row in feature.rows:
        if row.entity_ref not in mapped_entities:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE,
                "event entity is absent from the verified Qlib mapping",
            )
        schedule = _weekly_schedule(row.effective_trade_date, calendar, alignment_policy)
        if not evaluation_start <= schedule.signal_time.date() <= evaluation_end:
            raise QlibResearchError(
                ReasonCode.OOS_POLICY_VIOLATION,
                "aligned event signal falls outside the resolved evaluation range",
            )
        available_at = row.available_at.astimezone(SHANGHAI)
        if available_at > schedule.signal_time:
            raise QlibResearchError(
                ReasonCode.LOOK_AHEAD, "event feature is unavailable at aligned signal time"
            )
        key = (schedule.signal_time, row.entity_ref, row.event_label)
        grouped[key].append(row)
        schedules[key] = schedule
    return tuple(
        EventSignalEvidenceItem(
            event_feature_row_hashes=tuple(sorted(row.content_hash for row in rows)),
            entity_ref=key[1],
            event_label=key[2],
            first_effective_trade_date=min(row.effective_trade_date for row in rows),
            last_effective_trade_date=max(row.effective_trade_date for row in rows),
            source_available_at=max(row.available_at for row in rows).astimezone(SHANGHAI),
            schedule=schedules[key],
            score=len(rows),
        )
        for key, rows in sorted(grouped.items())
    )


def build_event_signal_evidence(
    *,
    event_feature_path: Path,
    view_path: Path,
    alignment_policy: EventSignalAlignmentPolicy,
    expected_event_feature_artifact_hash: str,
    expected_snapshot_hash: str,
    expected_qlib_view_hash: str,
    evaluation_start: date,
    evaluation_end: date,
) -> EventSignalEvidence:
    """Derive a complete, immutable event-to-weekly-decision PIT witness."""

    try:
        feature_manifest = verify_event_feature_artifact(event_feature_path)
        view = verify_qlib_view(view_path)
        feature = EventFeatureArtifact.model_validate_json(
            confined_regular_file(event_feature_path, "feature.json").read_bytes()
        )
        view_spec = QlibViewSpec.model_validate_json(
            confined_regular_file(view_path, "view-spec.json").read_bytes()
        )
    except EventFeatureError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    except (OSError, ValueError, ArtifactIntegrityError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "event signal input artifact is invalid"
        ) from error
    if (
        feature_manifest.artifact_hash != expected_event_feature_artifact_hash
        or feature_manifest.snapshot_hash != expected_snapshot_hash
        or feature.source_snapshot_hash != expected_snapshot_hash
        or view.view_hash != expected_qlib_view_hash
        or view.source_snapshot_hash != expected_snapshot_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "event feature, snapshot, and Qlib view bindings disagree",
        )
    calendar = _calendar_dates(view_path)
    items = _derive_evidence_items(
        feature,
        view_spec,
        calendar,
        alignment_policy,
        evaluation_start,
        evaluation_end,
    )
    return EventSignalEvidence(
        event_feature_artifact_hash=feature_manifest.artifact_hash,
        event_feature_hash=feature.content_hash,
        snapshot_hash=expected_snapshot_hash,
        qlib_view_hash=view.view_hash,
        alignment_policy_hash=alignment_policy.content_hash,
        items=items,
    )


def _artifact_files(root: Path) -> tuple[EventSignalArtifactFile, ...]:
    return tuple(
        EventSignalArtifactFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in regular_tree_files(root)
        if path.name != "manifest.json"
    )


def _tradability(
    view_path: Path, dates: tuple[date, ...]
) -> dict[tuple[date, str], dict[str, object]]:
    rows = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        view_path / "sidecars" / "tradability.parquet",
        columns=["instrument_id", "trade_date", "is_suspended", "is_st", "available_at"],
        filters=[("trade_date", "in", list(dates))],
    ).to_pylist()
    return {(cast(date, row["trade_date"]), cast(str, row["instrument_id"])): row for row in rows}


class EventSignalArtifactBuilder:
    """Publish standard signal rows; Qlib remains the only downstream backtest engine."""

    def build(
        self,
        resolved: ResolvedEventExperimentSpec,
        evidence: EventSignalEvidence,
        event_feature_path: Path,
        view_path: Path,
        alignment_policy: EventSignalAlignmentPolicy,
        output_root: Path,
        *,
        workspace: Path | None = None,
    ) -> EventSignalArtifactBuildResult:
        try:
            verify_code_provenance(
                workspace or Path.cwd(),
                expected_commit_hash=resolved.code_commit_hash,
                expected_lockfile_hash=resolved.lockfile_hash,
            )
            feature_manifest = verify_event_feature_artifact(event_feature_path)
            view = verify_qlib_view(view_path)
            feature = EventFeatureArtifact.model_validate_json(
                confined_regular_file(event_feature_path, "feature.json").read_bytes()
            )
        except ProvenanceError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        except EventFeatureError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        except QlibViewBuildError as error:
            raise QlibResearchError(error.reason_code, str(error)) from None
        except (OSError, ValueError, ArtifactIntegrityError) as error:
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED, "event signal build input is invalid"
            ) from error
        if (
            resolved.event_feature_artifact_hash != feature_manifest.artifact_hash
            or resolved.event_signal_alignment_policy_hash != alignment_policy.content_hash
            or resolved.event_signal_evidence_hash != evidence.content_hash
            or resolved.snapshot_hash != feature_manifest.snapshot_hash
            or resolved.snapshot_hash != evidence.snapshot_hash
            or resolved.qlib_view_hash != evidence.qlib_view_hash
            or resolved.qlib_view_hash != view.view_hash
            or resolved.qlib_view_spec_hash != view.view_spec_hash
            or resolved.qlib_version != view.qlib_version
            or evidence.event_feature_hash != feature.content_hash
        ):
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "resolved event experiment does not bind every verified input",
            )
        status_by_key = _tradability(
            view_path, tuple(sorted({item.schedule.signal_time.date() for item in evidence.items}))
        )
        rows: list[SignalRow] = []
        for item in evidence.items:
            status = status_by_key.get((item.schedule.signal_time.date(), item.entity_ref))
            if status is None:
                raise QlibResearchError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "event signal lacks same-session tradability evidence",
                )
            if cast(datetime, status["available_at"]) > item.schedule.signal_time:
                raise QlibResearchError(
                    ReasonCode.LOOK_AHEAD,
                    "event-signal tradability is unavailable at signal time",
                )
            rows.append(
                SignalRow(
                    instrument_id=item.entity_ref,
                    signal_time=item.schedule.signal_time,
                    decision_time=item.schedule.decision_time,
                    available_at=item.source_available_at,
                    score=float(item.score),
                    tradable=not cast(bool, status["is_st"])
                    and not cast(bool, status["is_suspended"]),
                )
            )
        canonical_rows = tuple(sorted(rows, key=lambda row: (row.signal_time, row.instrument_id)))
        if len(canonical_rows) != len(
            {(row.signal_time, row.instrument_id) for row in canonical_rows}
        ):
            raise QlibResearchError(
                ReasonCode.DUPLICATE_ID_CONFLICT,
                "event labels collide on one signal cross section and instrument",
            )
        output_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".event-signal-", dir=output_root))
        try:
            payloads = {
                "event-feature-manifest.json": canonical_json_bytes(
                    feature_manifest.model_dump(mode="python")
                ),
                "event-feature.json": feature.canonical_bytes(),
                "event-signal-evidence.json": evidence.canonical_bytes(),
                "event-signal-policy.json": alignment_policy.canonical_bytes(),
                "resolved-event-experiment.json": resolved.canonical_bytes(),
            }
            for name, payload in payloads.items():
                atomic_write_bytes(temporary / name, payload)
            write_signal_table(canonical_rows, temporary / "signals.parquet")
            manifest = EventSignalArtifactManifest.create(
                resolved_experiment_hash=resolved.content_hash,
                event_feature_artifact_hash=feature_manifest.artifact_hash,
                event_feature_hash=feature.content_hash,
                event_signal_evidence_hash=evidence.content_hash,
                event_signal_alignment_policy_hash=alignment_policy.content_hash,
                snapshot_hash=resolved.snapshot_hash,
                qlib_version=resolved.qlib_version,
                qlib_view_spec_hash=resolved.qlib_view_spec_hash,
                qlib_view_hash=resolved.qlib_view_hash,
                row_count=len(canonical_rows),
                signal_start=canonical_rows[0].signal_time,
                signal_end=canonical_rows[-1].signal_time,
                signal_content_hash=signal_content_hash(canonical_rows),
                files=_artifact_files(temporary),
                created_at=datetime.now(SHANGHAI),
            )
            atomic_write_bytes(
                temporary / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = output_root / f"sha256-{manifest.artifact_hash}"
            if destination.exists():
                existing = verify_event_signal_artifact(destination)
                if existing.artifact_hash != manifest.artifact_hash:
                    raise QlibResearchError(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "existing event signal differs from deterministic rebuild",
                    )
                shutil.rmtree(temporary)
            else:
                publish_directory(temporary, destination)
            verified = verify_event_signal_artifact(destination)
            return EventSignalArtifactBuildResult(
                reference=ArtifactRef(
                    kind="event-signal",
                    sha256=verified.artifact_hash,
                    size_bytes=(destination / "manifest.json").stat().st_size,
                    media_type="application/json",
                    logical_path=destination.name,
                ),
                manifest=verified,
                path=destination,
            )
        except QlibResearchError:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        except (OSError, ValueError, ArtifactConflictError, ArtifactIntegrityError) as error:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "event signal publication failed deterministic verification",
            ) from error


def verify_event_signal_artifact(path: Path) -> EventSignalArtifactManifest:
    try:
        manifest = EventSignalArtifactManifest.model_validate_json(
            confined_regular_file(path, "manifest.json").read_bytes()
        )
        if path.name != f"sha256-{manifest.artifact_hash}":
            raise ValueError("event signal directory does not bind its manifest hash")
        actual = {
            item.relative_to(path).as_posix()
            for item in regular_tree_files(path)
            if item.name != "manifest.json"
        }
        if actual != {item.logical_path for item in manifest.files}:
            raise ValueError("event signal exact-file set disagrees")
        for item in manifest.files:
            target = confined_regular_file(path, item.logical_path)
            verify_file(target, item.sha256)
            if target.stat().st_size != item.size_bytes:
                raise ValueError("event signal file size disagrees")
        feature_manifest = EventFeatureArtifactManifest.model_validate_json(
            (path / "event-feature-manifest.json").read_bytes()
        )
        feature = EventFeatureArtifact.model_validate_json(
            (path / "event-feature.json").read_bytes()
        )
        evidence = EventSignalEvidence.model_validate_json(
            (path / "event-signal-evidence.json").read_bytes()
        )
        policy = EventSignalAlignmentPolicy.model_validate_json(
            (path / "event-signal-policy.json").read_bytes()
        )
        resolved = ResolvedEventExperimentSpec.model_validate_json(
            (path / "resolved-event-experiment.json").read_bytes()
        )
        table = pq.read_table(path / "signals.parquet")  # pyright: ignore[reportUnknownMemberType]
        if table.schema != SIGNAL_SCHEMA:
            raise ValueError("event signal Arrow schema does not match SignalRow/v2")
        rows = tuple(SignalRow.model_validate(item) for item in table.to_pylist())
        keys = [(row.signal_time, row.instrument_id) for row in rows]
        if not rows or keys != sorted(set(keys)):
            raise ValueError("event signal rows must be nonempty, sorted, and unique")
        source_rows = {row.content_hash: row for row in feature.rows}
        for item in evidence.items:
            if not set(item.event_feature_row_hashes) <= set(source_rows):
                raise ValueError("event signal evidence references an unknown feature row")
            selected = tuple(source_rows[digest] for digest in item.event_feature_row_hashes)
            if (
                any(
                    row.entity_ref != item.entity_ref or row.event_label != item.event_label
                    for row in selected
                )
                or min(row.effective_trade_date for row in selected)
                != item.first_effective_trade_date
                or max(row.effective_trade_date for row in selected)
                != item.last_effective_trade_date
                or max(row.available_at for row in selected).astimezone(SHANGHAI)
                != item.source_available_at
            ):
                raise ValueError("event signal evidence misstates its source feature rows")
            schedule = item.schedule
            if (
                schedule.signal_time.astimezone(SHANGHAI).time().isoformat() != policy.signal_time
                or schedule.signal_available_at.astimezone(SHANGHAI).time().isoformat()
                != policy.signal_available_time
                or schedule.decision_time.astimezone(SHANGHAI).time().isoformat()
                != policy.decision_time
                or schedule.execution_time.astimezone(SHANGHAI).time().isoformat()
                != policy.execution_time
            ):
                raise ValueError("event signal schedule disagrees with the alignment policy")
        items_by_key = {
            (item.schedule.signal_time, item.entity_ref): item for item in evidence.items
        }
        if set(items_by_key) != set(keys):
            raise ValueError("event signal rows do not exactly match event PIT evidence")
        for row in rows:
            item = items_by_key[(row.signal_time, row.instrument_id)]
            if (
                row.decision_time != item.schedule.decision_time
                or row.available_at != item.source_available_at
                or row.score != float(item.score)
            ):
                raise ValueError("event signal row disagrees with event PIT evidence")
        if not (
            feature_manifest.artifact_hash == manifest.event_feature_artifact_hash
            and feature_manifest.feature_hash == manifest.event_feature_hash
            and feature.content_hash == manifest.event_feature_hash
            and evidence.content_hash == manifest.event_signal_evidence_hash
            and evidence.event_feature_artifact_hash == manifest.event_feature_artifact_hash
            and evidence.event_feature_hash == manifest.event_feature_hash
            and evidence.snapshot_hash == manifest.snapshot_hash
            and evidence.qlib_view_hash == manifest.qlib_view_hash
            and evidence.alignment_policy_hash == manifest.event_signal_alignment_policy_hash
            and policy.content_hash == manifest.event_signal_alignment_policy_hash
            and resolved.content_hash == manifest.resolved_experiment_hash
            and resolved.event_feature_artifact_hash == manifest.event_feature_artifact_hash
            and resolved.event_signal_evidence_hash == manifest.event_signal_evidence_hash
            and resolved.event_signal_alignment_policy_hash
            == manifest.event_signal_alignment_policy_hash
            and resolved.snapshot_hash == manifest.snapshot_hash
            and resolved.qlib_view_hash == manifest.qlib_view_hash
            and resolved.qlib_view_spec_hash == manifest.qlib_view_spec_hash
            and resolved.qlib_version == manifest.qlib_version
            and len(rows) == manifest.row_count
            and rows[0].signal_time == manifest.signal_start
            and rows[-1].signal_time == manifest.signal_end
            and signal_content_hash(rows) == manifest.signal_content_hash
        ):
            raise ValueError("event signal authority bindings disagree")
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError, json.JSONDecodeError):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event signal artifact failed exact-file or hash verification",
        ) from None
    return manifest


def verify_event_signal_pit(signal_path: Path, view_path: Path) -> EventSignalEvidence:
    """Recompute event alignment and tradability against the exact bound Qlib view."""

    manifest = verify_event_signal_artifact(signal_path)
    try:
        feature = EventFeatureArtifact.model_validate_json(
            confined_regular_file(signal_path, "event-feature.json").read_bytes()
        )
        evidence = EventSignalEvidence.model_validate_json(
            confined_regular_file(signal_path, "event-signal-evidence.json").read_bytes()
        )
        policy = EventSignalAlignmentPolicy.model_validate_json(
            confined_regular_file(signal_path, "event-signal-policy.json").read_bytes()
        )
        resolved = ResolvedEventExperimentSpec.model_validate_json(
            confined_regular_file(signal_path, "resolved-event-experiment.json").read_bytes()
        )
        view = verify_qlib_view(view_path)
        view_spec = QlibViewSpec.model_validate_json(
            confined_regular_file(view_path, "view-spec.json").read_bytes()
        )
        rows = tuple(
            SignalRow.model_validate(item)
            for item in pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                signal_path / "signals.parquet"
            ).to_pylist()
        )
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    except (OSError, ValueError, ValidationError, ArtifactIntegrityError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event signal PIT inputs cannot be recomputed",
        ) from error
    if (
        view.view_hash != manifest.qlib_view_hash
        or view.source_snapshot_hash != manifest.snapshot_hash
        or view.view_spec_hash != manifest.qlib_view_spec_hash
        or view.qlib_version != manifest.qlib_version
        or view_spec.content_hash != manifest.qlib_view_spec_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "event signal PIT verification received a different Qlib view",
        )
    recomputed_items = _derive_evidence_items(
        feature,
        view_spec,
        _calendar_dates(view_path),
        policy,
        resolved.evaluation_start,
        resolved.evaluation_end,
    )
    recomputed = EventSignalEvidence(
        event_feature_artifact_hash=manifest.event_feature_artifact_hash,
        event_feature_hash=feature.content_hash,
        snapshot_hash=manifest.snapshot_hash,
        qlib_view_hash=view.view_hash,
        alignment_policy_hash=policy.content_hash,
        items=recomputed_items,
    )
    if recomputed != evidence:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "event signal PIT evidence differs from snapshot-backed recomputation",
        )
    statuses = _tradability(
        view_path, tuple(sorted({item.schedule.signal_time.date() for item in evidence.items}))
    )
    items_by_key = {(item.schedule.signal_time, item.entity_ref): item for item in evidence.items}
    for row in rows:
        item = items_by_key[(row.signal_time, row.instrument_id)]
        status = statuses.get((item.schedule.signal_time.date(), item.entity_ref))
        if status is None:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE,
                "event signal PIT recomputation lacks tradability evidence",
            )
        if cast(datetime, status["available_at"]) > item.schedule.signal_time:
            raise QlibResearchError(
                ReasonCode.LOOK_AHEAD,
                "event signal PIT recomputation found late tradability evidence",
            )
        expected_tradable = not cast(bool, status["is_st"]) and not cast(
            bool, status["is_suspended"]
        )
        if row.tradable != expected_tradable:
            raise QlibResearchError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "event signal tradability differs from the bound Qlib sidecar",
            )
    return evidence
