"""Build complete snapshot-bound PIT evidence for a signal cross section."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq

from quantos.application.pit import PITAuditService, temporal_from_canonical_row
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    OperatorDelayPolicy,
    PITGateId,
    PITGateResult,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
)
from quantos.contracts.research_execution import (
    PITArtifactEvidence,
    PITAuditEvidenceBundle,
    PITAuditEvidenceCollection,
    PITAuditEvidenceItem,
    PITCrossSectionEvidenceBundle,
    PITCrossSectionEvidenceCollection,
    PITMembershipSetEvidence,
    PITSourceSetEvidence,
    required_expression_observations,
)
from quantos.contracts.status import ReasonCode, ValidationVerdict
from quantos.contracts.temporal import (
    AvailabilityEvidenceLevel,
    DecisionSchedule,
    TemporalMetadata,
)
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view
from quantos.data.snapshot import verify_snapshot
from quantos.research.qlib.universe import QlibResearchError, resolve_historical_universe


def build_pit_evidence_bundle(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
    universe_index: str,
    expression: SafeQlibExpressionSpec,
    operator_delays: tuple[OperatorDelayPolicy, ...],
    schedule: DecisionSchedule,
) -> PITAuditEvidenceBundle:
    """Audit every member selected by the historical-universe sidecar."""

    universe = resolve_historical_universe(
        view_path,
        expected_view_hash=expected_view_hash,
        expected_snapshot_hash=expected_snapshot_hash,
        index_id=universe_index,
        as_of_date=schedule.decision_time.date(),
        decision_time=schedule.decision_time,
    )
    service = PITAuditService()
    items: list[PITAuditEvidenceItem] = []
    for member in universe.members:
        request = CanonicalPITAuditRequest(
            snapshot_hash=expected_snapshot_hash,
            instrument_id=member.instrument_id,
            universe_index=universe_index,
            expression=expression,
            operator_delays=operator_delays,
            schedule=schedule,
        )
        report = service.audit_snapshot(request, snapshot_path)
        if report.verdict is not ValidationVerdict.PASS:
            reason = next(
                (
                    gate.reason_code
                    for gate in report.gates
                    if gate.verdict is ValidationVerdict.REJECT and gate.reason_code is not None
                ),
                ReasonCode.LOOK_AHEAD,
            )
            raise QlibResearchError(
                reason,
                f"PIT audit rejected signal member {member.instrument_id}",
            )
        items.append(PITAuditEvidenceItem(request=request, report=report))
    return PITAuditEvidenceBundle(
        snapshot_hash=expected_snapshot_hash,
        expression_spec_hash=expression.content_hash,
        universe_index=universe_index,
        schedule=schedule,
        items=tuple(items),
    )


def build_pit_evidence_collection(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
    universe_index: str,
    expression: SafeQlibExpressionSpec,
    operator_delays: tuple[OperatorDelayPolicy, ...],
    schedules: tuple[DecisionSchedule, ...],
) -> PITAuditEvidenceCollection:
    bundles = tuple(
        build_pit_evidence_bundle(
            snapshot_path,
            view_path,
            expected_snapshot_hash=expected_snapshot_hash,
            expected_view_hash=expected_view_hash,
            universe_index=universe_index,
            expression=expression,
            operator_delays=operator_delays,
            schedule=schedule,
        )
        for schedule in schedules
    )
    return PITAuditEvidenceCollection(
        snapshot_hash=expected_snapshot_hash,
        expression_spec_hash=expression.content_hash,
        universe_index=universe_index,
        bundles=bundles,
    )


SourceTable = Literal["bars", "adjustment_factors"]
LogicalField = Literal["close", "adjusted_close"]
SourceField = Literal["close", "adjustment_factor"]

_FIELD_SOURCES: Mapping[LogicalField, tuple[tuple[SourceTable, SourceField], ...]] = {
    "close": (("bars", "close"),),
    "adjusted_close": (
        ("adjustment_factors", "adjustment_factor"),
        ("bars", "close"),
    ),
}


def _row_set_hash(rows: Sequence[Mapping[str, object]]) -> str:
    return sha256_bytes(canonical_json_bytes([dict(row) for row in rows]))


def _arrow_row_set_hash(table: pa.Table) -> str:
    """Hash a deterministic Arrow projection without expanding every row to Python."""

    sink = pa.BufferOutputStream()
    normalized = table.combine_chunks()
    with pa.ipc.new_stream(sink, normalized.schema) as writer:
        writer.write_table(normalized)
    return sha256_bytes(sink.getvalue().to_pybytes())


def _market_row_index(table: pa.Table) -> dict[date, dict[str, int]]:
    """Build a bounded lookup over Arrow row positions, reusing instrument strings."""

    positions: dict[date, dict[str, int]] = {}
    offset = 0
    for batch in table.select(["instrument_id", "trade_date"]).to_batches(max_chunksize=65_536):
        identifiers = cast(list[str], batch.column("instrument_id").to_pylist())
        dates = cast(list[date], batch.column("trade_date").to_pylist())
        for relative, (instrument_id, trade_date) in enumerate(
            zip(identifiers, dates, strict=True)
        ):
            by_instrument = positions.setdefault(trade_date, {})
            key = sys.intern(instrument_id)
            if key in by_instrument:
                raise QlibResearchError(
                    ReasonCode.SCHEMA_INVALID,
                    "canonical market table contains duplicate primary keys",
                )
            by_instrument[key] = offset + relative
        offset += batch.num_rows
    return positions


def _weakest_evidence(values: Sequence[AvailabilityEvidenceLevel]) -> AvailabilityEvidenceLevel:
    priority = {
        AvailabilityEvidenceLevel.EXPLICIT_SOURCE_TIMESTAMP: 0,
        AvailabilityEvidenceLevel.DOCUMENTED_UPDATE_SCHEDULE: 1,
        AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED: 2,
        AvailabilityEvidenceLevel.OBSERVED_ONLY: 3,
        AvailabilityEvidenceLevel.UNKNOWN: 4,
    }
    return max(values, key=priority.__getitem__)


def _maximum_temporal(
    rows: Sequence[Mapping[str, object]], *, policy_id: str
) -> TemporalMetadata | None:
    if not rows:
        return None
    values = [temporal_from_canonical_row(row) for row in rows]
    return TemporalMetadata(
        event_time=max(item.event_time for item in values),
        known_at=max(item.known_at for item in values),
        available_at=max(item.available_at for item in values),
        observed_at=max(item.observed_at for item in values),
        evidence_level=_weakest_evidence([item.evidence_level for item in values]),
        policy_id=policy_id,
    )


def _propagate_compact_availability(
    expression: SafeQlibExpressionSpec,
    operator_delays: tuple[OperatorDelayPolicy, ...],
    source_sets: tuple[PITSourceSetEvidence, ...],
) -> TemporalMetadata:
    by_field: dict[str, list[TemporalMetadata]] = {}
    for item in source_sets:
        if item.maximum_temporal is not None:
            by_field.setdefault(item.logical_field_name, []).append(item.maximum_temporal)
    delays = {item.operator: item for item in operator_delays}
    propagated: dict[str, TemporalMetadata] = {}
    for node in expression.nodes:
        if node.operator is SafeQlibOperator.FIELD:
            values = by_field.get(cast(str, node.field_name), [])
            if not values:
                raise QlibResearchError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "compact PIT source projection contains no usable rows",
                )
            propagated[node.node_id] = TemporalMetadata(
                event_time=max(item.event_time for item in values),
                known_at=max(item.known_at for item in values),
                available_at=max(item.available_at for item in values),
                observed_at=max(item.observed_at for item in values),
                evidence_level=_weakest_evidence([item.evidence_level for item in values]),
                policy_id=f"compact-lineage-field:{node.field_name}/v2",
            )
            continue
        inputs = [propagated[item] for item in node.inputs]
        delay = delays[node.operator]
        weakest = _weakest_evidence([item.evidence_level for item in inputs])
        if weakest not in {
            AvailabilityEvidenceLevel.UNKNOWN,
            AvailabilityEvidenceLevel.OBSERVED_ONLY,
        }:
            weakest = AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED
        propagated[node.node_id] = TemporalMetadata(
            event_time=max(item.event_time for item in inputs),
            known_at=max(item.known_at for item in inputs),
            available_at=max(item.available_at for item in inputs)
            + timedelta(seconds=delay.delay_seconds),
            observed_at=max(item.observed_at for item in inputs),
            evidence_level=weakest,
            policy_id=delay.policy_id,
        )
    return propagated[expression.output_node_id]


def _pass_gate(gate_id: PITGateId, detail: str) -> PITGateResult:
    return PITGateResult(gate_id=gate_id, verdict=ValidationVerdict.PASS, detail=detail)


def build_compact_pit_evidence_collection(
    snapshot_path: Path,
    view_path: Path,
    *,
    expected_snapshot_hash: str,
    expected_view_hash: str,
    universe_index: str,
    expression: SafeQlibExpressionSpec,
    operator_delays: tuple[OperatorDelayPolicy, ...],
    schedules: tuple[DecisionSchedule, ...],
) -> PITCrossSectionEvidenceCollection:
    """Audit production cross sections with snapshot-recomputable row-set digests.

    Missing market rows remain explicit in each source-set count.  They are not a
    look-ahead failure and are never imputed here; Qlib execution records the
    corresponding signal as invalid when its expression result is non-finite.
    """

    snapshot = verify_snapshot(snapshot_path)
    try:
        view = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if (
        snapshot.snapshot_hash != expected_snapshot_hash
        or view.view_hash != expected_view_hash
        or view.source_snapshot_hash != expected_snapshot_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "compact PIT inputs do not match the verified snapshot and Qlib view",
        )
    try:
        calendar = tuple(
            date.fromisoformat(line.strip())
            for line in (view_path / "calendars" / "day.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    except (OSError, ValueError) as error:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib calendar cannot be read for PIT audit"
        ) from error
    if not calendar or calendar != tuple(sorted(set(calendar))):
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "Qlib calendar must be nonempty, sorted, and unique",
        )
    market_tables = {
        name: pq.read_table(  # pyright: ignore[reportUnknownMemberType]
            snapshot_path / "canonical" / f"{name}.parquet"
        )
        for name in ("bars", "adjustment_factors")
    }
    market_keys = market_tables["bars"].select(["instrument_id", "trade_date"])
    if not market_keys.equals(
        market_tables["adjustment_factors"].select(["instrument_id", "trade_date"])
    ):
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "bar and adjustment-factor keys do not align",
        )
    market_positions = _market_row_index(market_tables["bars"])
    membership_rows = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "index_membership.parquet"
    ).to_pylist()
    required_observations = required_expression_observations(expression)
    field_names: set[LogicalField] = {
        cast(LogicalField, node.field_name)
        for node in expression.nodes
        if node.operator is SafeQlibOperator.FIELD
    }
    try:
        source_mapping: tuple[tuple[SourceTable, LogicalField, SourceField], ...] = tuple(
            sorted(
                (table_name, field_name, source_field)
                for field_name in field_names
                for table_name, source_field in _FIELD_SOURCES[field_name]
            )
        )
    except KeyError as error:
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "safe expression field has no canonical PIT source mapping",
        ) from error

    calendar_position = {session: position for position, session in enumerate(calendar)}
    bundles: list[PITCrossSectionEvidenceBundle] = []
    for schedule in schedules:
        signal_date = schedule.signal_time.date()
        cutoff = calendar_position.get(signal_date)
        if cutoff is None:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE, "signal date is absent from the Qlib calendar"
            )
        cutoff -= expression.input_lag_trading_days
        start = cutoff - required_observations + 1
        if start < 0:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE, "signal lacks the complete calendar source window"
            )
        source_window = calendar[start : cutoff + 1]
        decision_date = schedule.decision_time.date()
        active_memberships = sorted(
            (
                row
                for row in membership_rows
                if row["index_id"] == universe_index
                and cast(date, row["effective_from"])
                <= decision_date
                <= cast(date, row["effective_to"])
                and cast(datetime, row["available_at"]) <= schedule.decision_time
            ),
            key=lambda row: cast(str, row["instrument_id"]),
        )
        members = tuple(cast(str, row["instrument_id"]) for row in active_memberships)
        if not members or len(members) != len(set(members)):
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE,
                "historical universe is empty or has duplicate effective memberships",
            )
        expected_row_count = len(members) * len(source_window)
        selected_positions = [
            position
            for instrument_id in members
            for session in source_window
            if (position := market_positions.get(session, {}).get(instrument_id)) is not None
        ]
        position_array = pa.array(selected_positions, type=pa.int64())
        source_sets: list[PITSourceSetEvidence] = []
        for table_name, logical_field, source_field in source_mapping:
            selected_table = market_tables[table_name].take(position_array)
            selected = selected_table.to_pylist()
            maximum = _maximum_temporal(
                selected,
                policy_id=f"compact-source-maximum:{table_name}:{source_field}/v2",
            )
            source_sets.append(
                PITSourceSetEvidence(
                    table_name=table_name,
                    logical_field_name=logical_field,
                    source_field_name=source_field,
                    expected_row_count=expected_row_count,
                    present_row_count=len(selected),
                    missing_row_count=expected_row_count - len(selected),
                    row_set_hash=_arrow_row_set_hash(selected_table),
                    maximum_temporal=maximum,
                )
            )
        canonical_source_sets = tuple(source_sets)
        output_temporal = _propagate_compact_availability(
            expression, operator_delays, canonical_source_sets
        )
        membership_temporal = _maximum_temporal(
            active_memberships, policy_id="compact-membership-maximum/v2"
        )
        if membership_temporal is None:
            raise QlibResearchError(
                ReasonCode.SOURCE_INCOMPLETE, "membership temporal evidence is absent"
            )
        maximum_sources = [
            item.maximum_temporal
            for item in canonical_source_sets
            if item.maximum_temporal is not None
        ]
        if any(
            item.evidence_level is AvailabilityEvidenceLevel.UNKNOWN
            or item.available_at > schedule.signal_time
            for item in maximum_sources
        ):
            raise QlibResearchError(
                ReasonCode.LOOK_AHEAD,
                "compact PIT source availability exceeds the signal boundary",
            )
        if output_temporal.available_at > schedule.signal_time:
            raise QlibResearchError(
                ReasonCode.LOOK_AHEAD,
                "compact PIT derived availability exceeds the signal boundary",
            )
        missing_rows = sum(item.missing_row_count for item in canonical_source_sets)
        gates = (
            _pass_gate(PITGateId.SNAPSHOT_BINDING, "snapshot and Qlib view hashes verified"),
            _pass_gate(
                PITGateId.SOURCE_WINDOW,
                "calendar window is complete; "
                f"{missing_rows} missing market values remain explicit",
            ),
            _pass_gate(PITGateId.LINEAGE_COMPLETE, "all expression fields map to source digests"),
            _pass_gate(
                PITGateId.SOURCE_AVAILABILITY,
                "all present source rows are available by signal_time",
            ),
            _pass_gate(
                PITGateId.DERIVED_AVAILABILITY,
                "derived feature availability is no later than signal_time",
            ),
            _pass_gate(
                PITGateId.MEMBERSHIP_AS_OF,
                "every member is effective and available at decision_time",
            ),
            _pass_gate(
                PITGateId.SCHEDULE,
                "signal_time <= signal_available_at <= decision_time < execution_time",
            ),
        )
        bundles.append(
            PITCrossSectionEvidenceBundle(
                snapshot_hash=expected_snapshot_hash,
                expression_spec_hash=expression.content_hash,
                universe_index=universe_index,
                schedule=schedule,
                required_observations=required_observations,
                source_window=source_window,
                members=members,
                source_sets=canonical_source_sets,
                membership_set=PITMembershipSetEvidence(
                    row_count=len(active_memberships),
                    row_set_hash=_row_set_hash(active_memberships),
                    maximum_temporal=membership_temporal,
                ),
                output_temporal=output_temporal,
                gates=gates,
            )
        )
    return PITCrossSectionEvidenceCollection(
        snapshot_hash=expected_snapshot_hash,
        qlib_view_hash=expected_view_hash,
        expression_spec_hash=expression.content_hash,
        expression=expression,
        operator_delays=operator_delays,
        universe_index=universe_index,
        bundles=tuple(bundles),
    )


def verify_compact_pit_evidence(
    evidence: PITCrossSectionEvidenceCollection,
    snapshot_path: Path,
    view_path: Path,
) -> None:
    rebuilt = build_compact_pit_evidence_collection(
        snapshot_path,
        view_path,
        expected_snapshot_hash=evidence.snapshot_hash,
        expected_view_hash=evidence.qlib_view_hash,
        universe_index=evidence.universe_index,
        expression=evidence.expression,
        operator_delays=evidence.operator_delays,
        schedules=tuple(bundle.schedule for bundle in evidence.bundles),
    )
    if rebuilt.content_hash != evidence.content_hash:
        raise QlibResearchError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "compact PIT evidence cannot be reproduced from the bound snapshot",
        )


def subset_compact_pit_evidence(
    evidence: PITCrossSectionEvidenceCollection,
    schedules: tuple[DecisionSchedule, ...],
) -> PITCrossSectionEvidenceCollection:
    """Create an exact immutable subperiod projection without rescanning source data."""

    wanted = {(item.signal_time, item.decision_time, item.execution_time) for item in schedules}
    bundles = tuple(
        bundle
        for bundle in evidence.bundles
        if (
            bundle.schedule.signal_time,
            bundle.schedule.decision_time,
            bundle.schedule.execution_time,
        )
        in wanted
    )
    if len(bundles) != len(wanted):
        raise ValueError("compact PIT subperiod schedules are not covered by the parent evidence")
    return PITCrossSectionEvidenceCollection(
        snapshot_hash=evidence.snapshot_hash,
        qlib_view_hash=evidence.qlib_view_hash,
        expression_spec_hash=evidence.expression_spec_hash,
        expression=evidence.expression,
        operator_delays=evidence.operator_delays,
        universe_index=evidence.universe_index,
        bundles=bundles,
    )


def load_pit_artifact_evidence(path: Path) -> PITArtifactEvidence:
    try:
        payload = json.loads(path.read_bytes())
        schema_version = payload.get("schema_version")
        if schema_version == "pit-audit-evidence-collection/v1":
            return PITAuditEvidenceCollection.model_validate(payload)
        if schema_version == "pit-cross-section-evidence-collection/v2":
            return PITCrossSectionEvidenceCollection.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("PIT evidence payload is invalid") from error
    raise ValueError("PIT evidence schema version is unsupported")


def pit_bundle_members(
    bundle: PITAuditEvidenceBundle | PITCrossSectionEvidenceBundle,
) -> tuple[str, ...]:
    if isinstance(bundle, PITAuditEvidenceBundle):
        return tuple(item.request.instrument_id for item in bundle.items)
    return bundle.members


def pit_bundle_output_temporal(
    bundle: PITAuditEvidenceBundle | PITCrossSectionEvidenceBundle,
    instrument_id: str,
) -> TemporalMetadata:
    if isinstance(bundle, PITAuditEvidenceBundle):
        report = next(
            item.report for item in bundle.items if item.request.instrument_id == instrument_id
        )
        if report.output_temporal is None:
            raise ValueError("passing PIT evidence lacks output temporal metadata")
        return report.output_temporal
    if instrument_id not in bundle.members:
        raise ValueError("instrument is absent from compact PIT bundle")
    return bundle.output_temporal


def pit_transform_lineage_hash(evidence: PITArtifactEvidence) -> str:
    if isinstance(evidence, PITAuditEvidenceCollection):
        values: object = [
            item.report.audit_spec_hash for bundle in evidence.bundles for item in bundle.items
        ]
    else:
        values = [
            {
                "membership": bundle.membership_set.row_set_hash,
                "sources": [item.row_set_hash for item in bundle.source_sets],
            }
            for bundle in evidence.bundles
        ]
    return sha256_bytes(canonical_json_bytes(values))
