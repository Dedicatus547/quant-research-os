"""Deterministic experiment-time point-in-time availability audit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    LineageSource,
    MembershipUse,
    PITAuditReport,
    PITAuditSpec,
    PITEvidenceMode,
    PITGateId,
    PITGateResult,
    SafeExpressionNode,
    SafeQlibOperator,
    TransformLineage,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode, ValidationVerdict
from quantos.contracts.temporal import AvailabilityEvidenceLevel, TemporalMetadata
from quantos.data.snapshot import verify_snapshot


def temporal_from_canonical_row(row: Mapping[str, object]) -> TemporalMetadata:
    """Resolve P2 canonical temporal columns into the shared P1 contract."""

    try:
        return TemporalMetadata(
            event_time=cast(datetime, row["event_time"]),
            known_at=cast(datetime, row["known_at"]),
            available_at=cast(datetime, row["available_at"]),
            observed_at=cast(datetime, row["observed_at"]),
            evidence_level=AvailabilityEvidenceLevel(cast(str, row["availability_basis"])),
            policy_id=cast(str, row["availability_policy_id"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("canonical row lacks valid temporal metadata") from error


def expression_field_names(nodes: tuple[SafeExpressionNode, ...]) -> frozenset[str]:
    return frozenset(
        node.field_name
        for node in nodes
        if node.operator is SafeQlibOperator.FIELD and node.field_name is not None
    )


def _weakest_evidence(values: list[AvailabilityEvidenceLevel]) -> AvailabilityEvidenceLevel:
    priority = {
        AvailabilityEvidenceLevel.EXPLICIT_SOURCE_TIMESTAMP: 0,
        AvailabilityEvidenceLevel.DOCUMENTED_UPDATE_SCHEDULE: 1,
        AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED: 2,
        AvailabilityEvidenceLevel.OBSERVED_ONLY: 3,
        AvailabilityEvidenceLevel.UNKNOWN: 4,
    }
    return max(values, key=priority.__getitem__)


def _combine_sources(sources: list[LineageSource], policy_id: str) -> TemporalMetadata:
    temporals = [source.temporal for source in sources]
    return TemporalMetadata(
        event_time=max(item.event_time for item in temporals),
        known_at=max(item.known_at for item in temporals),
        available_at=max(item.available_at for item in temporals),
        observed_at=max(item.observed_at for item in temporals),
        evidence_level=_weakest_evidence([item.evidence_level for item in temporals]),
        policy_id=policy_id,
    )


def propagate_availability(
    spec: PITAuditSpec,
) -> tuple[dict[str, TemporalMetadata], tuple[str, ...]]:
    """Propagate availability over the validated safe-expression DAG without executing values."""

    by_field: dict[str, list[LineageSource]] = {}
    for source in spec.lineage.sources:
        by_field.setdefault(source.field_name, []).append(source)
    delay_by_operator = {policy.operator: policy for policy in spec.lineage.operator_delays}
    propagated: dict[str, TemporalMetadata] = {}
    missing: list[str] = []
    for node in spec.lineage.expression.nodes:
        if node.operator is SafeQlibOperator.FIELD:
            field_name = cast(str, node.field_name)
            sources = by_field.get(field_name, [])
            if not sources:
                missing.append(field_name)
                continue
            propagated[node.node_id] = _combine_sources(sources, f"lineage-field:{field_name}/v1")
            continue
        inputs = [propagated.get(input_id) for input_id in node.inputs]
        if any(item is None for item in inputs):
            missing.append(node.node_id)
            continue
        resolved = cast(list[TemporalMetadata], inputs)
        delay_policy = delay_by_operator[node.operator]
        delay = delay_policy.delay_seconds
        weakest = _weakest_evidence([item.evidence_level for item in resolved])
        if weakest not in {
            AvailabilityEvidenceLevel.UNKNOWN,
            AvailabilityEvidenceLevel.OBSERVED_ONLY,
        }:
            weakest = AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED
        propagated[node.node_id] = TemporalMetadata(
            event_time=max(item.event_time for item in resolved),
            known_at=max(item.known_at for item in resolved),
            available_at=max(item.available_at for item in resolved) + timedelta(seconds=delay),
            observed_at=max(item.observed_at for item in resolved),
            evidence_level=weakest,
            policy_id=delay_policy.policy_id,
        )
    return propagated, tuple(sorted(set(missing)))


def _gate(
    gate_id: PITGateId,
    passed: bool,
    detail: str,
    reason_code: ReasonCode = ReasonCode.LOOK_AHEAD,
) -> PITGateResult:
    return PITGateResult(
        gate_id=gate_id,
        verdict=ValidationVerdict.PASS if passed else ValidationVerdict.REJECT,
        reason_code=None if passed else reason_code,
        detail=detail,
    )


class PITAuditService:
    """Audit feature inputs, derived availability, membership as-of use, and schedule."""

    def audit(
        self,
        spec: PITAuditSpec,
        *,
        evidence_mode: PITEvidenceMode = PITEvidenceMode.PROPOSAL_UNBOUND,
        binding_gates: tuple[PITGateResult, ...] = (),
        canonical_request: CanonicalPITAuditRequest | None = None,
    ) -> PITAuditReport:
        propagated, missing = propagate_availability(spec)
        gates: list[PITGateResult] = [
            *binding_gates,
            _gate(
                PITGateId.LINEAGE_COMPLETE,
                not missing,
                "lineage resolves all expression fields"
                if not missing
                else f"lineage is missing: {','.join(missing)}",
                ReasonCode.SOURCE_INCOMPLETE,
            ),
        ]

        unknown_sources = [
            source.source_id
            for source in spec.lineage.sources
            if source.temporal.evidence_level is AvailabilityEvidenceLevel.UNKNOWN
        ]
        future_sources = [
            source.source_id
            for source in spec.lineage.sources
            if source.temporal.available_at > spec.schedule.signal_time
        ]
        if unknown_sources:
            gates.append(
                _gate(
                    PITGateId.SOURCE_AVAILABILITY,
                    False,
                    f"UNKNOWN source availability: {','.join(sorted(unknown_sources))}",
                    ReasonCode.UNKNOWN_AVAILABILITY,
                )
            )
        else:
            gates.append(
                _gate(
                    PITGateId.SOURCE_AVAILABILITY,
                    not future_sources,
                    "all sources are available by signal_time"
                    if not future_sources
                    else f"sources available after signal_time: {','.join(sorted(future_sources))}",
                )
            )

        output = propagated.get(spec.lineage.expression.output_node_id)
        output_usable = output is not None and output.available_at <= spec.schedule.signal_time
        gates.append(
            _gate(
                PITGateId.DERIVED_AVAILABILITY,
                output_usable,
                "derived feature is available by signal_time"
                if output_usable
                else "derived feature availability exceeds signal_time or is unresolved",
                ReasonCode.SOURCE_INCOMPLETE if output is None else ReasonCode.LOOK_AHEAD,
            )
        )

        decision_date = spec.schedule.decision_time.date()
        invalid_memberships = [
            f"{item.index_id}:{item.instrument_id}"
            for item in spec.memberships
            if not (item.effective_from <= decision_date <= item.effective_to)
            or item.temporal.evidence_level is AvailabilityEvidenceLevel.UNKNOWN
            or item.temporal.available_at > spec.schedule.decision_time
        ]
        gates.append(
            _gate(
                PITGateId.MEMBERSHIP_AS_OF,
                not invalid_memberships,
                "all memberships are effective and known at decision_time"
                if not invalid_memberships
                else f"invalid membership as-of use: {','.join(sorted(invalid_memberships))}",
            )
        )
        gates.append(
            _gate(
                PITGateId.SCHEDULE,
                True,
                "signal_time <= signal_available_at <= decision_time < execution_time",
            )
        )
        results = tuple(gates)
        verdict = (
            ValidationVerdict.PASS
            if all(item.verdict is ValidationVerdict.PASS for item in results)
            else ValidationVerdict.REJECT
        )
        return PITAuditReport(
            audit_spec_hash=spec.content_hash,
            canonical_request_hash=(
                canonical_request.content_hash if canonical_request is not None else None
            ),
            snapshot_hash=spec.snapshot_hash,
            expression_spec_hash=spec.lineage.expression.content_hash,
            schedule=spec.schedule,
            instrument_id=(
                canonical_request.instrument_id if canonical_request is not None else None
            ),
            universe_index=(
                canonical_request.universe_index if canonical_request is not None else None
            ),
            evidence_mode=evidence_mode,
            verdict=verdict,
            gates=results,
            output_temporal=output,
        )

    def audit_snapshot(
        self, request: CanonicalPITAuditRequest, snapshot_path: Path
    ) -> PITAuditReport:
        manifest = verify_snapshot(snapshot_path)
        binding_gate = _gate(
            PITGateId.SNAPSHOT_BINDING,
            manifest.snapshot_hash == request.snapshot_hash,
            "request hash resolves to the verified snapshot"
            if manifest.snapshot_hash == request.snapshot_hash
            else "request hash does not match the verified snapshot",
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
        )
        required_observations = _required_observations(
            request.expression.nodes, request.expression.output_node_id
        )
        exchange = "SSE" if request.instrument_id.endswith(".SH") else "SZSE"
        calendar = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
            snapshot_path / "canonical" / "calendar.parquet"
        ).to_pylist()
        sessions = sorted(
            cast(date, row["trade_date"])
            for row in calendar
            if row["exchange"] == exchange
            and row["is_open"] is True
            and cast(date, row["trade_date"]) <= request.schedule.signal_time.date()
        )
        cutoff_position = len(sessions) - 1 - request.expression.input_lag_trading_days
        window_dates = (
            sessions[cutoff_position - required_observations + 1 : cutoff_position + 1]
            if cutoff_position >= 0
            else []
        )
        window_complete = len(window_dates) == required_observations

        field_names = expression_field_names(request.expression.nodes)
        field_tables = {
            "close": (("bars", "close"),),
            "adjusted_close": (
                ("bars", "close"),
                ("adjustment_factors", "adjustment_factor"),
            ),
        }
        unsupported_fields = sorted(field_names - field_tables.keys())
        sources: list[LineageSource] = []
        missing_rows: list[str] = []
        if window_complete and not unsupported_fields:
            for field_name in sorted(field_names):
                for table_name, source_field in field_tables[field_name]:
                    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
                        snapshot_path / "canonical" / f"{table_name}.parquet"
                    ).to_pylist()
                    rows_by_date = {
                        cast(date, row["trade_date"]): row
                        for row in table
                        if row["instrument_id"] == request.instrument_id
                    }
                    for session in window_dates:
                        row = rows_by_date.get(session)
                        if row is None:
                            missing_rows.append(f"{table_name}:{request.instrument_id}:{session}")
                            continue
                        sources.append(
                            LineageSource(
                                source_id=(
                                    f"{table_name}:{request.instrument_id}:{session}:{source_field}"
                                ),
                                table_name=table_name,
                                field_name=field_name,
                                row_key=f"{request.instrument_id}:{session}",
                                temporal=temporal_from_canonical_row(row),
                            )
                        )

        memberships_table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
            snapshot_path / "canonical" / "index_membership.parquet"
        ).to_pylist()
        decision_date = request.schedule.decision_time.date()
        membership_rows = [
            row
            for row in memberships_table
            if row["index_id"] == request.universe_index
            and row["instrument_id"] == request.instrument_id
            and cast(date, row["effective_from"])
            <= decision_date
            <= cast(date, row["effective_to"])
        ]
        memberships = tuple(
            MembershipUse(
                index_id=cast(str, row["index_id"]),
                instrument_id=cast(str, row["instrument_id"]),
                effective_from=cast(date, row["effective_from"]),
                effective_to=cast(date, row["effective_to"]),
                temporal=temporal_from_canonical_row(row),
            )
            for row in membership_rows
        )
        source_window_gate = _gate(
            PITGateId.SOURCE_WINDOW,
            window_complete
            and not unsupported_fields
            and not missing_rows
            and len(memberships) == 1,
            (
                f"snapshot supplies {required_observations} complete source sessions and one "
                "membership interval"
                if window_complete
                and not unsupported_fields
                and not missing_rows
                and len(memberships) == 1
                else "snapshot source window, field mapping, or membership interval is incomplete"
            ),
            ReasonCode.SOURCE_INCOMPLETE,
        )
        binding_gates = (binding_gate, source_window_gate)
        if source_window_gate.verdict is ValidationVerdict.REJECT or not sources:
            return _binding_rejection_report(request, manifest.snapshot_hash, binding_gates)

        spec = PITAuditSpec(
            snapshot_hash=manifest.snapshot_hash,
            lineage=TransformLineage(
                expression=request.expression,
                sources=tuple(sources),
                operator_delays=request.operator_delays,
            ),
            schedule=request.schedule,
            memberships=memberships,
        )
        return self.audit(
            spec,
            evidence_mode=PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND,
            binding_gates=binding_gates,
            canonical_request=request,
        )

    def publish(self, report: PITAuditReport, root: Path) -> ArtifactRef:
        if report.evidence_mode is not PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND:
            raise ValueError("proposal/unbound PIT reports cannot be published as evidence")
        encoded = report.canonical_bytes()
        relative = Path("pit") / f"sha256-{report.content_hash}.json"
        digest = atomic_write_bytes(root / relative, encoded)
        return ArtifactRef(
            kind="pit_audit_report",
            sha256=digest,
            size_bytes=len(encoded),
            media_type="application/json",
            logical_path=relative.as_posix(),
        )


def load_pit_spec_json(payload: Mapping[str, Any]) -> PITAuditSpec:
    """Typed boundary used by the CLI without introducing a configuration framework."""

    return PITAuditSpec.model_validate(payload)


def load_canonical_pit_request_json(payload: Mapping[str, Any]) -> CanonicalPITAuditRequest:
    return CanonicalPITAuditRequest.model_validate(payload)


def _required_observations(nodes: tuple[SafeExpressionNode, ...], output_node_id: str) -> int:
    observations: dict[str, int] = {}
    for node in nodes:
        if node.operator is SafeQlibOperator.FIELD:
            observations[node.node_id] = 1
            continue
        inputs = [observations[item] for item in node.inputs]
        base = max(inputs)
        if node.operator in {SafeQlibOperator.REF, SafeQlibOperator.RETURN}:
            observations[node.node_id] = base + cast(int, node.window)
        elif node.operator in {
            SafeQlibOperator.ROLLING_MEAN,
            SafeQlibOperator.ROLLING_STD,
            SafeQlibOperator.RANK,
        }:
            observations[node.node_id] = base + cast(int, node.window) - 1
        else:
            observations[node.node_id] = base
    return observations[output_node_id]


def _binding_rejection_report(
    request: CanonicalPITAuditRequest,
    snapshot_hash: str,
    gates: tuple[PITGateResult, ...],
) -> PITAuditReport:
    return PITAuditReport(
        audit_spec_hash=request.content_hash,
        canonical_request_hash=request.content_hash,
        snapshot_hash=snapshot_hash,
        expression_spec_hash=request.expression.content_hash,
        schedule=request.schedule,
        instrument_id=request.instrument_id,
        universe_index=request.universe_index,
        evidence_mode=PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND,
        verdict=ValidationVerdict.REJECT,
        gates=gates,
        output_temporal=None,
    )
