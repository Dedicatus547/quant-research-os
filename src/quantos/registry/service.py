"""Single-writer append-only registry over immutable manifests and events."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    ImmutableEventWriter,
    StoredEvent,
    atomic_write_bytes,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.events import EventType, ImmutableEvent
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef
from quantos.contracts.registry import (
    LOGICAL_ID_PATTERN,
    RegistryExperimentIndexEntry,
    RegistryExperimentManifest,
    RegistryIndex,
    RegistryStrategyRecord,
    StrategyVersionRecord,
)
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResolvedExperimentSpec,
)
from quantos.contracts.status import ReasonCode, RunStatus, StrategyStatus, ValidationVerdict
from quantos.data import QlibViewBuildError, SnapshotBuildError, verify_qlib_view, verify_snapshot
from quantos.research.qlib import QlibResearchError, verify_signal_artifact
from quantos.validation import ValidationError, verify_validation_report

_EVENT_NAMESPACE = UUID("f52d4cbe-06f4-5d21-a00d-d76c86fc99e7")
_PARTIAL_FILE = re.compile(r"^\..+\.json\..+$")


class RegistryError(RuntimeError):
    """Registry input or authority is invalid."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class RegistryConflictError(RegistryError):
    """A logical identifier is already bound to different immutable content."""

    def __init__(self, message: str) -> None:
        super().__init__(ReasonCode.DUPLICATE_ID_CONFLICT, message)


@dataclass(frozen=True)
class RegistryRegistrationResult:
    manifest: RegistryExperimentManifest
    event: ArtifactRef
    index: RegistryIndex


@dataclass
class _MutableStrategyVersion:
    strategy_id: str
    version: int
    strategy_spec_hash: str
    status: StrategyStatus
    validation_experiment_id: str | None
    validation_report_hash: str | None
    event_hashes: list[str]


def _safe_logical_id(value: str, *, label: str) -> str:
    if re.fullmatch(LOGICAL_ID_PATTERN, value) is None:
        raise RegistryError(ReasonCode.SCHEMA_INVALID, f"{label} is not a safe logical identifier")
    return value


def _event_uuid(scope: str, payload: object) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{scope}:{canonical_json_bytes(payload).decode('utf-8')}")


def _event_reference(root: Path, event: ImmutableEvent) -> ArtifactRef:
    relative = Path(event.aggregate_id) / f"{event.event_id}.json"
    path = root / relative
    return ArtifactRef(
        kind="event",
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        media_type="application/json",
        logical_path=relative.as_posix(),
    )


def _read_stored_event(path: Path) -> StoredEvent:
    try:
        encoded = path.read_bytes()
        stored = StoredEvent.model_validate_json(encoded)
    except (OSError, ValueError) as error:
        raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "registry event is invalid") from error
    if encoded != canonical_json_bytes(stored.model_dump(mode="python")):
        raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "registry event bytes are not canonical")
    if (
        path.name != f"{stored.event.event_id}.json"
        or path.parent.name != stored.event.aggregate_id
    ):
        raise RegistryError(
            ReasonCode.ARTIFACT_CORRUPTED, "registry event path does not match its envelope"
        )
    return stored


def _ordered_chain(events: list[StoredEvent], *, aggregate_id: str) -> list[StoredEvent]:
    if not events:
        return []
    by_hash = {item.event_hash: item for item in events}
    if len(by_hash) != len(events):
        raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "duplicate event hash in aggregate")
    heads = [item for item in events if item.event.previous_event_hash is None]
    if len(heads) != 1:
        raise RegistryError(
            ReasonCode.ARTIFACT_CORRUPTED, "event aggregate must contain exactly one chain head"
        )
    children: dict[str, list[StoredEvent]] = {}
    for item in events:
        previous = item.event.previous_event_hash
        if previous is None:
            continue
        if previous not in by_hash:
            raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "event chain predecessor is missing")
        children.setdefault(previous, []).append(item)
    ordered = [heads[0]]
    while ordered[-1].event_hash in children:
        successors = children[ordered[-1].event_hash]
        if len(successors) != 1:
            raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "event chain contains a fork")
        successor = successors[0]
        if successor.event.occurred_at < ordered[-1].event.occurred_at:
            raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "event chain time moved backwards")
        ordered.append(successor)
    if len(ordered) != len(events):
        raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "event chain is disconnected")
    if any(item.event.aggregate_id != aggregate_id for item in ordered):
        raise RegistryError(ReasonCode.ARTIFACT_CORRUPTED, "event aggregate identifier mismatch")
    return ordered


def _required_payload(event: ImmutableEvent, keys: set[str]) -> dict[str, object]:
    payload = cast(dict[str, object], event.payload)
    if set(payload) != keys:
        raise RegistryError(
            ReasonCode.ARTIFACT_CORRUPTED,
            f"{event.event_type} payload does not match the locked registry schema",
        )
    return payload


class RegistryService:
    """Registry API for a trusted single-user, single-writer filesystem root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._manifest_root = root / "manifests" / "experiments"
        self._experiment_event_root = root / "events" / "experiments"
        self._strategy_event_root = root / "events" / "strategies"

    def register_experiment(
        self,
        validation_path: Path,
        *,
        event_root: Path | None = None,
        snapshot_path: Path | None = None,
        qlib_view_path: Path | None = None,
        signal_path: Path | None = None,
        registered_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> RegistryRegistrationResult:
        """Verify and retain PASS, REJECT, or FAILED validation evidence immutably."""

        try:
            report = verify_validation_report(validation_path)
            authoring = ExperimentAuthoringSpec.model_validate_json(
                (validation_path / "authoring-spec.json").read_bytes()
            )
            runtime = RuntimeFingerprint.model_validate_json(
                (validation_path / "runtime-fingerprint.json").read_bytes()
            )
        except (OSError, ValueError, ValidationError) as error:
            reason = getattr(error, "reason_code", ReasonCode.ARTIFACT_CORRUPTED)
            raise RegistryError(reason, "validation artifact cannot be registered") from error
        if authoring.experiment_id != report.experiment_id:
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "validation report and authoring experiment identifiers disagree",
            )
        if registered_at is not None and (
            registered_at.tzinfo is None or registered_at.utcoffset() is None
        ):
            raise RegistryError(ReasonCode.SCHEMA_INVALID, "registered_at must be timezone-aware")
        existing_manifest_paths = tuple((self._manifest_root / report.experiment_id).glob("*.json"))
        if existing_manifest_paths:
            if len(existing_manifest_paths) != 1:
                raise RegistryConflictError("duplicate logical experiment identifier")
            existing_manifest = self._read_manifest(existing_manifest_paths[0])
            if existing_manifest.validation_report_hash != report.report_hash:
                raise RegistryConflictError(
                    "experiment_id is already bound to a different validation report"
                )

        snapshot = None
        if report.snapshot_hash is not None:
            if snapshot_path is None:
                raise RegistryError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "registered validation report requires its explicit snapshot path",
                )
            try:
                snapshot = verify_snapshot(snapshot_path)
            except SnapshotBuildError as error:
                raise RegistryError(
                    error.reason_code, "registered snapshot failed verification"
                ) from error
            if snapshot.snapshot_hash != report.snapshot_hash:
                raise RegistryError(
                    ReasonCode.SNAPSHOT_HASH_MISMATCH,
                    "registered snapshot does not match the validation report",
                )
        elif snapshot_path is not None:
            raise RegistryError(
                ReasonCode.SCHEMA_INVALID, "snapshot path supplied for a report without a snapshot"
            )

        view = None
        if report.qlib_view_hash is not None:
            if qlib_view_path is None:
                raise RegistryError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "registered validation report requires its explicit Qlib view path",
                )
            try:
                view = verify_qlib_view(qlib_view_path)
            except QlibViewBuildError as error:
                raise RegistryError(
                    error.reason_code, "registered Qlib view failed verification"
                ) from error
            if (
                view.view_hash != report.qlib_view_hash
                or view.source_snapshot_hash != report.snapshot_hash
            ):
                raise RegistryError(
                    ReasonCode.SNAPSHOT_HASH_MISMATCH,
                    "registered Qlib view does not match the validation report and snapshot",
                )
        elif qlib_view_path is not None:
            raise RegistryError(
                ReasonCode.SCHEMA_INVALID, "Qlib view path supplied for a report without a view"
            )

        resolved: ResolvedExperimentSpec | None = None
        signal = None
        if report.signal_artifact_hash is not None:
            if signal_path is None:
                raise RegistryError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "registered validation report requires its explicit SignalArtifact path",
                )
            try:
                signal = verify_signal_artifact(signal_path)
                resolved = ResolvedExperimentSpec.model_validate_json(
                    (signal_path / "resolved-experiment.json").read_bytes()
                )
            except (OSError, ValueError, QlibResearchError) as error:
                reason = getattr(error, "reason_code", ReasonCode.ARTIFACT_CORRUPTED)
                raise RegistryError(
                    reason, "registered SignalArtifact failed verification"
                ) from error
            if (
                signal.artifact_hash != report.signal_artifact_hash
                or signal.resolved_experiment_hash != resolved.content_hash
                or report.resolved_experiment_hash != resolved.content_hash
                or resolved.authoring_spec_hash != report.authoring_spec_hash
                or resolved.snapshot_hash != report.snapshot_hash
                or signal.snapshot_hash != report.snapshot_hash
                or resolved.qlib_view_hash != report.qlib_view_hash
                or signal.qlib_view_hash != report.qlib_view_hash
                or view is None
                or signal.qlib_view_spec_hash != view.view_spec_hash
                or signal.qlib_version != view.qlib_version
            ):
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "registered signal, resolved experiment, and report bindings disagree",
                )
        elif signal_path is not None:
            raise RegistryError(
                ReasonCode.SCHEMA_INVALID, "signal path supplied for a report without a signal"
            )

        oos_event: ImmutableEvent | None = None
        imported_oos_ref: ArtifactRef | None = None
        if report.oos_access_event is not None:
            if event_root is None:
                raise RegistryError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "registered validation report requires its explicit OOS event root",
                )
            try:
                if (
                    report.oos_access_event.kind != "event"
                    or report.oos_access_event.media_type != "application/json"
                ):
                    raise ArtifactIntegrityError("OOS event reference type is invalid")
                source_writer = ImmutableEventWriter(event_root)
                oos_event = source_writer.read(report.oos_access_event)
                source_path = event_root / report.oos_access_event.logical_path
                if source_path.stat().st_size != report.oos_access_event.size_bytes:
                    raise ArtifactIntegrityError("OOS event size does not match its reference")
            except (OSError, ValueError, ArtifactIntegrityError) as error:
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED, "OOS access event failed verification"
                ) from error
            self._validate_oos_event(oos_event, report, authoring)
            try:
                imported_oos_ref = ImmutableEventWriter(self._experiment_event_root).append(
                    oos_event
                )
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                raise RegistryConflictError(
                    "OOS event identifier conflicts in the registry"
                ) from error
            if imported_oos_ref.sha256 != report.oos_access_event.sha256:
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "imported OOS event does not preserve its immutable file hash",
                )

        timestamp = (registered_at or report.created_at).astimezone(UTC)
        if oos_event is not None and timestamp < oos_event.occurred_at.astimezone(UTC):
            raise RegistryError(
                ReasonCode.SCHEMA_INVALID, "registration cannot precede the imported OOS event"
            )
        artifact_hashes = self._validation_artifact_hashes(report)
        manifest = RegistryExperimentManifest.create(
            experiment_id=report.experiment_id,
            authoring_spec_hash=report.authoring_spec_hash,
            strategy_spec_hash=authoring.strategy.content_hash,
            resolved_experiment_hash=report.resolved_experiment_hash,
            validation_policy_hash=report.validation_policy_hash,
            research_policy_hash=report.research_policy_hash,
            runtime_fingerprint_hash=report.runtime_fingerprint_hash,
            runtime_fingerprint=runtime,
            code_commit_hash=resolved.code_commit_hash if resolved is not None else None,
            lockfile_hash=resolved.lockfile_hash if resolved is not None else None,
            code_worktree_clean=True if resolved is not None else None,
            snapshot_hash=report.snapshot_hash,
            snapshot_source_kind=snapshot.source_kind if snapshot is not None else None,
            snapshot_build_spec_hash=snapshot.build_spec_hash if snapshot is not None else None,
            data_quality_policy_hash=(
                snapshot.quality_policy_hash if snapshot is not None else None
            ),
            data_quality_report_hash=(
                snapshot.quality_report_hash if snapshot is not None else None
            ),
            qlib_view_hash=report.qlib_view_hash,
            qlib_view_spec_hash=view.view_spec_hash if view is not None else None,
            qlib_version=view.qlib_version if view is not None else None,
            qlib_source_commit=view.qlib_source_commit if view is not None else None,
            dump_bin_sha256=view.dump_bin_sha256 if view is not None else None,
            health_check_sha256=view.health_check_sha256 if view is not None else None,
            qlib_run_id=signal.qlib_run_id if signal is not None else None,
            pit_audit_evidence_hash=(
                resolved.pit_audit_evidence_hash if resolved is not None else None
            ),
            cost_policy_hash=resolved.cost_policy_hash if resolved is not None else None,
            backtest_policy_hash=resolved.backtest_policy_hash if resolved is not None else None,
            source_expression_or_model_hash=(
                signal.source_expression_or_model_hash if signal is not None else None
            ),
            signal_artifact_hash=report.signal_artifact_hash,
            backtest_result_hash=report.backtest_result_hash,
            validation_report_hash=report.report_hash,
            artifact_hashes=artifact_hashes,
            run_status=report.run_status,
            verdict=report.verdict,
            canonical=report.canonical,
            oos_access_event=imported_oos_ref,
            oos_access_event_hash=oos_event.content_hash if oos_event is not None else None,
            limitations=report.limitations,
            registered_at=timestamp,
        )
        manifest_path = (
            self._manifest_root / manifest.experiment_id / f"sha256-{manifest.manifest_hash}.json"
        )
        existing = tuple((self._manifest_root / manifest.experiment_id).glob("*.json"))
        if any(path != manifest_path for path in existing):
            raise RegistryConflictError(
                "experiment_id is already bound to a different immutable manifest"
            )
        if manifest_path.exists():
            registered_manifest = self._read_manifest(manifest_path)
            if registered_manifest.manifest_hash != manifest.manifest_hash:
                raise RegistryConflictError(
                    "experiment manifest content conflicts with its identifier"
                )
            manifest = registered_manifest
        else:
            try:
                atomic_write_bytes(
                    manifest_path,
                    canonical_json_bytes(manifest.model_dump(mode="python")),
                )
            except ArtifactConflictError as error:
                raise RegistryConflictError("experiment manifest publication conflicted") from error

        event_payload: dict[str, object] = {
            "experiment_id": manifest.experiment_id,
            "manifest_hash": manifest.manifest_hash,
            "run_status": manifest.run_status.value,
            "validation_report_hash": manifest.validation_report_hash,
            "verdict": manifest.verdict.value,
        }
        existing_event = self._find_matching_event(
            self._experiment_event_root,
            manifest.experiment_id,
            EventType.EXPERIMENT_REGISTERED,
            event_payload,
        )
        if existing_event is None:
            previous = oos_event.content_hash if oos_event is not None else None
            registration = ImmutableEvent(
                event_id=event_id
                or _event_uuid(f"experiment:{manifest.experiment_id}", event_payload),
                aggregate_id=manifest.experiment_id,
                event_type=EventType.EXPERIMENT_REGISTERED,
                occurred_at=timestamp,
                payload=cast(dict[str, object], event_payload),  # type: ignore[arg-type]
                previous_event_hash=previous,
            )
            try:
                event_ref = ImmutableEventWriter(self._experiment_event_root).append(registration)
            except ArtifactConflictError as error:
                raise RegistryConflictError(
                    "experiment registration event identifier conflicts"
                ) from error
        else:
            event_ref = _event_reference(self._experiment_event_root, existing_event.event)
        return RegistryRegistrationResult(manifest, event_ref, self.rebuild_index(now=timestamp))

    @staticmethod
    def _validation_artifact_hashes(report: object) -> tuple[str, ...]:
        from quantos.contracts.validation import ValidationReport

        validated = cast(ValidationReport, report)
        hashes = {
            item
            for item in (
                validated.snapshot_hash,
                validated.qlib_view_hash,
                validated.signal_artifact_hash,
                validated.backtest_result_hash,
                validated.report_hash,
            )
            if item is not None
        }
        hashes.update(reference.sha256 for gate in validated.gates for reference in gate.evidence)
        hashes.update(metric.source.sha256 for metric in validated.metrics)
        for case in validated.robustness_cases:
            hashes.update(reference.sha256 for reference in case.evidence)
            hashes.update(metric.source.sha256 for metric in case.metrics)
        if validated.reproducibility is not None:
            hashes.update(
                (validated.reproducibility.left.sha256, validated.reproducibility.right.sha256)
            )
        if validated.oos_access_event is not None:
            hashes.add(validated.oos_access_event.sha256)
        return tuple(sorted(hashes))

    def register_strategy(
        self,
        strategy_id: str,
        strategy_spec_hash: str,
        *,
        version: int,
        occurred_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> StrategyVersionRecord:
        """Create exactly the next strategy version; identical retries are idempotent."""

        _safe_logical_id(strategy_id, label="strategy_id")
        if re.fullmatch(SHA256_PATTERN, strategy_spec_hash) is None or version < 1:
            raise RegistryError(ReasonCode.SCHEMA_INVALID, "strategy version input is invalid")
        index = self.rebuild_index()
        record = next((item for item in index.strategies if item.strategy_id == strategy_id), None)
        versions = record.versions if record is not None else ()
        if version <= len(versions):
            existing = versions[version - 1]
            if existing.strategy_spec_hash == strategy_spec_hash:
                return existing
            raise RegistryConflictError("strategy_id and version already bind different content")
        if version != len(versions) + 1:
            raise RegistryError(
                ReasonCode.STATE_TRANSITION_INVALID,
                "strategy versions must be created monotonically without gaps",
            )
        timestamp = self._aware_now(occurred_at)
        previous = self._last_event_hash(self._strategy_event_root, strategy_id)
        payload: dict[str, object] = {
            "strategy_spec_hash": strategy_spec_hash,
            "version": version,
        }
        event = ImmutableEvent(
            event_id=event_id or _event_uuid(f"strategy:{strategy_id}:created", payload),
            aggregate_id=strategy_id,
            event_type=EventType.STRATEGY_CREATED,
            occurred_at=timestamp,
            payload=cast(dict[str, object], payload),  # type: ignore[arg-type]
            previous_event_hash=previous,
        )
        try:
            ImmutableEventWriter(self._strategy_event_root).append(event)
        except ArtifactConflictError as error:
            raise RegistryConflictError("strategy creation event identifier conflicts") from error
        return self.get_strategy(strategy_id, version=version)

    def append_strategy_event(
        self,
        strategy_id: str,
        version: int,
        event_type: EventType,
        experiment_id: str,
        *,
        occurred_at: datetime | None = None,
        event_id: UUID | None = None,
    ) -> StrategyVersionRecord:
        """Append one validated lifecycle transition bound to a registered experiment."""

        allowed = {
            EventType.VALIDATION_STARTED,
            EventType.VALIDATION_REJECTED,
            EventType.VALIDATION_PASSED,
            EventType.STRATEGY_VERSION_VALIDATED,
        }
        if event_type not in allowed:
            raise RegistryError(
                ReasonCode.STATE_TRANSITION_INVALID,
                "event type is not a strategy lifecycle transition",
            )
        current = self.get_strategy(strategy_id, version=version)
        experiment = self.get_experiment(experiment_id)
        if current.strategy_spec_hash != experiment.strategy_spec_hash:
            raise RegistryError(
                ReasonCode.STATE_TRANSITION_INVALID,
                "strategy version and validation experiment bind different strategy specs",
            )
        payload: dict[str, object] = {
            "experiment_id": experiment.experiment_id,
            "validation_report_hash": experiment.validation_report_hash,
            "version": version,
        }
        existing = self._find_matching_event(
            self._strategy_event_root, strategy_id, event_type, payload
        )
        if existing is not None:
            return self.get_strategy(strategy_id, version=version)
        self._validate_transition(current, experiment, event_type)
        timestamp = self._aware_now(occurred_at)
        previous = self._last_event_hash(self._strategy_event_root, strategy_id)
        event = ImmutableEvent(
            event_id=event_id
            or _event_uuid(
                f"strategy:{strategy_id}:{event_type.value}", {**payload, "previous": previous}
            ),
            aggregate_id=strategy_id,
            event_type=event_type,
            occurred_at=timestamp,
            payload=cast(dict[str, object], payload),  # type: ignore[arg-type]
            previous_event_hash=previous,
        )
        try:
            ImmutableEventWriter(self._strategy_event_root).append(event)
        except ArtifactConflictError as error:
            raise RegistryConflictError("strategy lifecycle event identifier conflicts") from error
        return self.get_strategy(strategy_id, version=version)

    def rebuild_index(self, *, now: datetime | None = None) -> RegistryIndex:
        """Verify every authoritative file and rebuild the complete in-memory projection."""

        self._reject_unexpected_files()
        manifests = self._load_manifests()
        experiment_events = self._load_event_scope(self._experiment_event_root)
        strategy_events = self._load_event_scope(self._strategy_event_root)
        experiment_entries = self._project_experiments(manifests, experiment_events)
        strategies = self._project_strategies(manifests, strategy_events)
        all_event_hashes = tuple(
            sorted(
                {
                    item.event_hash
                    for aggregate in (*experiment_events.values(), *strategy_events.values())
                    for item in aggregate
                }
            )
        )
        return RegistryIndex.create(
            experiments=tuple(experiment_entries),
            strategies=tuple(strategies),
            source_manifest_hashes=tuple(sorted(item.manifest_hash for item in manifests.values())),
            source_event_hashes=all_event_hashes,
            generated_at=self._aware_now(now),
        )

    def verify(self) -> RegistryIndex:
        return self.rebuild_index()

    def list_experiments(self) -> tuple[RegistryExperimentManifest, ...]:
        index = self.rebuild_index()
        return tuple(self._manifest_by_hash(item.manifest_hash) for item in index.experiments)

    def get_experiment(self, experiment_id: str) -> RegistryExperimentManifest:
        _safe_logical_id(experiment_id, label="experiment_id")
        index = self.rebuild_index()
        entry = next(
            (item for item in index.experiments if item.experiment_id == experiment_id), None
        )
        if entry is None:
            raise RegistryError(ReasonCode.SOURCE_INCOMPLETE, "experiment is not registered")
        return self._manifest_by_hash(entry.manifest_hash)

    def get_strategy(
        self, strategy_id: str, *, version: int | None = None
    ) -> StrategyVersionRecord:
        _safe_logical_id(strategy_id, label="strategy_id")
        index = self.rebuild_index()
        record = next((item for item in index.strategies if item.strategy_id == strategy_id), None)
        if record is None:
            raise RegistryError(ReasonCode.SOURCE_INCOMPLETE, "strategy is not registered")
        if version is None:
            return record.versions[-1]
        if version < 1 or version > len(record.versions):
            raise RegistryError(ReasonCode.SOURCE_INCOMPLETE, "strategy version is not registered")
        return record.versions[version - 1]

    def get_strategy_versions(self, strategy_id: str) -> tuple[StrategyVersionRecord, ...]:
        latest = self.get_strategy(strategy_id)
        index = self.rebuild_index()
        return next(
            item.versions for item in index.strategies if item.strategy_id == latest.strategy_id
        )

    def recover_partial_writes(self) -> tuple[str, ...]:
        """Remove only atomic-writer temporary files; authoritative JSON is never modified."""

        if not self.root.exists():
            return ()
        recovered: list[str] = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if _PARTIAL_FILE.fullmatch(path.name):
                recovered.append(path.relative_to(self.root).as_posix())
                path.unlink()
        return tuple(recovered)

    def _load_manifests(self) -> dict[str, RegistryExperimentManifest]:
        manifests: dict[str, RegistryExperimentManifest] = {}
        if not self._manifest_root.exists():
            return manifests
        for path in sorted(self._manifest_root.glob("*/*.json")):
            manifest = self._read_manifest(path)
            expected = (
                self._manifest_root
                / manifest.experiment_id
                / f"sha256-{manifest.manifest_hash}.json"
            )
            if path != expected:
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "registry experiment manifest path does not match its content",
                )
            if manifest.experiment_id in manifests:
                raise RegistryConflictError("duplicate logical experiment identifier")
            manifests[manifest.experiment_id] = manifest
        return manifests

    def _read_manifest(self, path: Path) -> RegistryExperimentManifest:
        try:
            encoded = path.read_bytes()
            manifest = RegistryExperimentManifest.model_validate_json(encoded)
        except (OSError, ValueError) as error:
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED, "registry experiment manifest is invalid"
            ) from error
        if encoded != canonical_json_bytes(manifest.model_dump(mode="python")):
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "registry experiment manifest bytes are not canonical",
            )
        return manifest

    def _manifest_by_hash(self, digest: str) -> RegistryExperimentManifest:
        matches = tuple(self._manifest_root.glob(f"*/sha256-{digest}.json"))
        if len(matches) != 1:
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED, "registry manifest hash is not uniquely resolvable"
            )
        return self._read_manifest(matches[0])

    def _load_event_scope(self, root: Path) -> dict[str, list[StoredEvent]]:
        aggregates: dict[str, list[StoredEvent]] = {}
        if not root.exists():
            return aggregates
        for path in sorted(root.glob("*/*.json")):
            stored = _read_stored_event(path)
            aggregates.setdefault(stored.event.aggregate_id, []).append(stored)
        return {
            aggregate_id: _ordered_chain(events, aggregate_id=aggregate_id)
            for aggregate_id, events in aggregates.items()
        }

    def _project_experiments(
        self,
        manifests: dict[str, RegistryExperimentManifest],
        event_groups: dict[str, list[StoredEvent]],
    ) -> list[RegistryExperimentIndexEntry]:
        if set(manifests) != set(event_groups):
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "experiment manifests and registration event aggregates disagree",
            )
        entries: list[RegistryExperimentIndexEntry] = []
        for experiment_id in sorted(manifests):
            manifest = manifests[experiment_id]
            events = event_groups[experiment_id]
            registrations = [
                item for item in events if item.event.event_type is EventType.EXPERIMENT_REGISTERED
            ]
            oos_events = [
                item for item in events if item.event.event_type is EventType.OOS_ACCESSED
            ]
            if len(registrations) != 1 or len(events) != len(registrations) + len(oos_events):
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "experiment aggregate contains an invalid event set",
                )
            registration = registrations[0]
            expected_payload: dict[str, object] = {
                "experiment_id": manifest.experiment_id,
                "manifest_hash": manifest.manifest_hash,
                "run_status": manifest.run_status.value,
                "validation_report_hash": manifest.validation_report_hash,
                "verdict": manifest.verdict.value,
            }
            if cast(dict[str, object], registration.event.payload) != expected_payload:
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "experiment registration event does not bind its manifest",
                )
            if manifest.oos_access_event_hash is None:
                if oos_events:
                    raise RegistryError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "unexpected OOS event in experiment aggregate",
                    )
            else:
                if (
                    len(oos_events) != 1
                    or oos_events[0].event_hash != manifest.oos_access_event_hash
                ):
                    raise RegistryError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "registered OOS event binding is inconsistent",
                    )
                reference = cast(ArtifactRef, manifest.oos_access_event)
                event_path = self._experiment_event_root / reference.logical_path
                try:
                    if (
                        sha256_file(event_path) != reference.sha256
                        or event_path.stat().st_size != reference.size_bytes
                    ):
                        raise OSError
                except OSError as error:
                    raise RegistryError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "registered OOS event file reference is inconsistent",
                    ) from error
            entries.append(
                RegistryExperimentIndexEntry(
                    experiment_id=manifest.experiment_id,
                    manifest_hash=manifest.manifest_hash,
                    validation_report_hash=manifest.validation_report_hash,
                    run_status=manifest.run_status,
                    verdict=manifest.verdict,
                    canonical=manifest.canonical,
                    snapshot_source_kind=manifest.snapshot_source_kind,
                    event_hashes=tuple(item.event_hash for item in events),
                )
            )
        return entries

    def _project_strategies(
        self,
        manifests: dict[str, RegistryExperimentManifest],
        event_groups: dict[str, list[StoredEvent]],
    ) -> list[RegistryStrategyRecord]:
        records: list[RegistryStrategyRecord] = []
        for strategy_id in sorted(event_groups):
            versions: dict[int, _MutableStrategyVersion] = {}
            for stored in event_groups[strategy_id]:
                event = stored.event
                if event.event_type is EventType.STRATEGY_CREATED:
                    payload = _required_payload(event, {"strategy_spec_hash", "version"})
                    version = payload["version"]
                    digest = payload["strategy_spec_hash"]
                    if (
                        not isinstance(version, int)
                        or isinstance(version, bool)
                        or version != len(versions) + 1
                        or not isinstance(digest, str)
                        or re.fullmatch(SHA256_PATTERN, digest) is None
                    ):
                        raise RegistryError(
                            ReasonCode.STATE_TRANSITION_INVALID,
                            "StrategyCreated does not create the next valid version",
                        )
                    versions[version] = _MutableStrategyVersion(
                        strategy_id,
                        version,
                        digest,
                        StrategyStatus.DRAFT,
                        None,
                        None,
                        [stored.event_hash],
                    )
                    continue
                if event.event_type not in {
                    EventType.VALIDATION_STARTED,
                    EventType.VALIDATION_REJECTED,
                    EventType.VALIDATION_PASSED,
                    EventType.STRATEGY_VERSION_VALIDATED,
                }:
                    raise RegistryError(
                        ReasonCode.STATE_TRANSITION_INVALID,
                        "strategy aggregate contains an unsupported event",
                    )
                payload = _required_payload(
                    event, {"experiment_id", "validation_report_hash", "version"}
                )
                version = payload["version"]
                experiment_id = payload["experiment_id"]
                report_hash = payload["validation_report_hash"]
                if (
                    not isinstance(version, int)
                    or isinstance(version, bool)
                    or version not in versions
                    or not isinstance(experiment_id, str)
                    or not isinstance(report_hash, str)
                    or experiment_id not in manifests
                ):
                    raise RegistryError(
                        ReasonCode.STATE_TRANSITION_INVALID,
                        "strategy event references an invalid version or experiment",
                    )
                current = versions[version]
                experiment = manifests[experiment_id]
                if (
                    report_hash != experiment.validation_report_hash
                    or current.strategy_spec_hash != experiment.strategy_spec_hash
                ):
                    raise RegistryError(
                        ReasonCode.STATE_TRANSITION_INVALID,
                        "strategy event evidence binding is inconsistent",
                    )
                frozen = self._freeze_strategy_version(current)
                self._validate_transition(frozen, experiment, event.event_type)
                current.status = {
                    EventType.VALIDATION_STARTED: StrategyStatus.VALIDATING,
                    EventType.VALIDATION_REJECTED: StrategyStatus.REJECTED,
                    EventType.VALIDATION_PASSED: StrategyStatus.CANDIDATE,
                    EventType.STRATEGY_VERSION_VALIDATED: StrategyStatus.VALIDATED,
                }[event.event_type]
                current.validation_experiment_id = experiment_id
                current.validation_report_hash = report_hash
                current.event_hashes.append(stored.event_hash)
            if not versions:
                raise RegistryError(
                    ReasonCode.STATE_TRANSITION_INVALID,
                    "strategy aggregate does not contain StrategyCreated",
                )
            records.append(
                RegistryStrategyRecord(
                    strategy_id=strategy_id,
                    versions=tuple(
                        self._freeze_strategy_version(versions[key]) for key in sorted(versions)
                    ),
                )
            )
        return records

    @staticmethod
    def _freeze_strategy_version(value: _MutableStrategyVersion) -> StrategyVersionRecord:
        return StrategyVersionRecord(
            strategy_id=value.strategy_id,
            version=value.version,
            strategy_spec_hash=value.strategy_spec_hash,
            status=value.status,
            validation_experiment_id=value.validation_experiment_id,
            validation_report_hash=value.validation_report_hash,
            event_hashes=tuple(value.event_hashes),
        )

    @staticmethod
    def _validate_transition(
        current: StrategyVersionRecord,
        experiment: RegistryExperimentManifest,
        event_type: EventType,
    ) -> None:
        if event_type is EventType.VALIDATION_STARTED:
            valid = current.status in {StrategyStatus.DRAFT, StrategyStatus.REJECTED}
        elif event_type is EventType.VALIDATION_REJECTED:
            valid = (
                current.status is StrategyStatus.VALIDATING
                and experiment.run_status is RunStatus.SUCCEEDED
                and experiment.verdict is ValidationVerdict.REJECT
            )
        elif event_type is EventType.VALIDATION_PASSED:
            valid = (
                current.status is StrategyStatus.VALIDATING
                and experiment.run_status is RunStatus.SUCCEEDED
                and experiment.verdict is ValidationVerdict.PASS
            )
        else:
            valid = (
                current.status is StrategyStatus.CANDIDATE
                and current.validation_experiment_id == experiment.experiment_id
                and experiment.run_status is RunStatus.SUCCEEDED
                and experiment.verdict is ValidationVerdict.PASS
                and experiment.canonical
            )
        if not valid:
            raise RegistryError(
                ReasonCode.STATE_TRANSITION_INVALID,
                f"{event_type.value} is not legal from {current.status.value}",
            )

    @staticmethod
    def _validate_oos_event(
        event: ImmutableEvent, report: object, authoring: ExperimentAuthoringSpec
    ) -> None:
        from quantos.contracts.validation import ValidationReport

        validated = cast(ValidationReport, report)
        if (
            event.event_type is not EventType.OOS_ACCESSED
            or event.aggregate_id != authoring.experiment_id
        ):
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED, "OOS event type or aggregate is inconsistent"
            )
        payload = cast(dict[str, object], event.payload)
        expected = {
            "authoring_spec_hash": validated.authoring_spec_hash,
            "backtest_result_hash": validated.backtest_result_hash,
            "research_policy_hash": validated.research_policy_hash,
            "resolved_experiment_hash": validated.resolved_experiment_hash,
            "validation_policy_hash": validated.validation_policy_hash,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED, "OOS event does not bind the validation report"
            )

    def _find_matching_event(
        self,
        root: Path,
        aggregate_id: str,
        event_type: EventType,
        payload: dict[str, object],
    ) -> StoredEvent | None:
        directory = root / aggregate_id
        if not directory.exists():
            return None
        matches: list[StoredEvent] = []
        for path in directory.glob("*.json"):
            stored = _read_stored_event(path)
            if (
                stored.event.event_type is event_type
                and cast(dict[str, object], stored.event.payload) == payload
            ):
                matches.append(stored)
        if len(matches) > 1:
            raise RegistryError(
                ReasonCode.ARTIFACT_CORRUPTED, "duplicate semantic event in aggregate"
            )
        return matches[0] if matches else None

    def _last_event_hash(self, root: Path, aggregate_id: str) -> str | None:
        directory = root / aggregate_id
        if not directory.exists():
            return None
        events = [_read_stored_event(path) for path in directory.glob("*.json")]
        chain = _ordered_chain(events, aggregate_id=aggregate_id)
        return chain[-1].event_hash if chain else None

    def _reject_unexpected_files(self) -> None:
        if not self.root.exists():
            return
        for path in (item for item in self.root.rglob("*") if item.is_file()):
            if _PARTIAL_FILE.fullmatch(path.name):
                continue
            relative = path.relative_to(self.root)
            parts = relative.parts
            valid = (
                len(parts) == 4
                and parts[0:2] == ("manifests", "experiments")
                and parts[3].startswith("sha256-")
                and parts[3].endswith(".json")
            ) or (
                len(parts) == 4
                and parts[0] == "events"
                and parts[1] in {"experiments", "strategies"}
                and parts[3].endswith(".json")
            )
            if not valid:
                raise RegistryError(
                    ReasonCode.ARTIFACT_CORRUPTED, "registry contains an unexpected authority file"
                )

    @staticmethod
    def _aware_now(value: datetime | None) -> datetime:
        timestamp = value or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RegistryError(
                ReasonCode.SCHEMA_INVALID, "registry timestamp must be timezone-aware"
            )
        return timestamp.astimezone(UTC)
