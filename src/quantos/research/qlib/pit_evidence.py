"""Build complete snapshot-bound PIT evidence for a signal cross section."""

from __future__ import annotations

from pathlib import Path

from quantos.application.pit import PITAuditService
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    OperatorDelayPolicy,
    SafeQlibExpressionSpec,
)
from quantos.contracts.research_execution import (
    PITAuditEvidenceBundle,
    PITAuditEvidenceCollection,
    PITAuditEvidenceItem,
)
from quantos.contracts.status import ReasonCode, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
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
