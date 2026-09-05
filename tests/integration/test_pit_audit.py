from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from quantos.application.pit import PITAuditService, temporal_from_canonical_row
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    LineageSource,
    MembershipUse,
    OperatorDelayPolicy,
    PITAuditSpec,
    PITEvidenceMode,
    PITGateId,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    TransformLineage,
)
from quantos.contracts.status import ReasonCode, ValidationVerdict
from quantos.contracts.temporal import (
    AvailabilityEvidenceLevel,
    DecisionSchedule,
    TemporalMetadata,
)
from quantos.data.snapshot import SyntheticSnapshotBuilder

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _schedule(*, signal_hour: int = 16) -> DecisionSchedule:
    return DecisionSchedule(
        signal_time=datetime(2024, 1, 5, signal_hour, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, signal_hour, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, signal_hour, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )


def _expression(
    field_name: str = "adjusted_close", *, window: int = 2, input_lag: int = 0
) -> SafeQlibExpressionSpec:
    return SafeQlibExpressionSpec(
        expression_id=f"momentum_{window}d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name=field_name),
            SafeExpressionNode(
                node_id="momentum", operator="return", inputs=("price",), window=window
            ),
        ),
        output_node_id="momentum",
        input_lag_trading_days=input_lag,
    )


def _delay(seconds: int = 60) -> OperatorDelayPolicy:
    return OperatorDelayPolicy(
        policy_id=f"qlib-return-delay-{seconds}s/v1",
        operator="return",
        delay_seconds=seconds,
    )


def _canonical_request(snapshot_hash: str, **changes: object) -> CanonicalPITAuditRequest:
    values: dict[str, object] = {
        "snapshot_hash": snapshot_hash,
        "instrument_id": "000001.SZ",
        "universe_index": "000300.SH",
        "expression": _expression(),
        "operator_delays": (_delay(),),
        "schedule": _schedule(),
    }
    values.update(changes)
    return CanonicalPITAuditRequest.model_validate(values)


def _proposal_spec(tmp_path: Path) -> PITAuditSpec:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    bars = pq.read_table(snapshot.path / "canonical" / "bars.parquet").to_pylist()
    selected = [row for row in bars if row["instrument_id"] == "000001.SZ"]
    sources = tuple(
        LineageSource(
            source_id=f"bar-{row['trade_date']}",
            table_name="bars",
            field_name="adjusted_close",
            row_key=f"000001.SZ:{row['trade_date']}",
            temporal=temporal_from_canonical_row(row),
        )
        for row in selected
    )
    membership_rows = pq.read_table(
        snapshot.path / "canonical" / "index_membership.parquet"
    ).to_pylist()
    membership_row = next(
        row
        for row in membership_rows
        if row["instrument_id"] == "000001.SZ" and row["effective_from"] == date(2024, 1, 5)
    )
    membership = MembershipUse(
        index_id=membership_row["index_id"],
        instrument_id=membership_row["instrument_id"],
        effective_from=membership_row["effective_from"],
        effective_to=membership_row["effective_to"],
        temporal=temporal_from_canonical_row(membership_row),
    )
    return PITAuditSpec(
        snapshot_hash=snapshot.manifest.snapshot_hash,
        lineage=TransformLineage(
            expression=_expression(),
            sources=sources,
            operator_delays=(_delay(),),
        ),
        schedule=_schedule(),
        memberships=(membership,),
    )


def test_verified_snapshot_builds_lineage_and_publishes_canonical_evidence(tmp_path: Path) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    request = _canonical_request(snapshot.manifest.snapshot_hash)
    service = PITAuditService()
    report = service.audit_snapshot(request, snapshot.path)
    first = service.publish(report, tmp_path / "evidence")
    repeated = service.publish(report, tmp_path / "evidence")

    assert report.verdict is ValidationVerdict.PASS
    assert report.evidence_mode is PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND
    assert report.output_temporal is not None
    assert report.output_temporal.available_at == datetime(2024, 1, 5, 15, 31, tzinfo=SHANGHAI)
    assert report.limitations == ("SINGLE_SOURCE_NON_VINTAGE",)
    assert {gate.gate_id for gate in report.gates} >= {
        PITGateId.SNAPSHOT_BINDING,
        PITGateId.SOURCE_WINDOW,
    }
    assert first == repeated


def test_fake_snapshot_hash_and_incomplete_window_are_canonical_rejections(tmp_path: Path) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    service = PITAuditService()

    wrong_hash = service.audit_snapshot(_canonical_request("a" * 64), snapshot.path)
    assert wrong_hash.verdict is ValidationVerdict.REJECT
    assert any(gate.reason_code is ReasonCode.SNAPSHOT_HASH_MISMATCH for gate in wrong_hash.gates)

    too_wide = service.audit_snapshot(
        _canonical_request(
            snapshot.manifest.snapshot_hash,
            expression=_expression(window=20),
        ),
        snapshot.path,
    )
    assert too_wide.verdict is ValidationVerdict.REJECT
    assert any(
        gate.gate_id is PITGateId.SOURCE_WINDOW and gate.reason_code is ReasonCode.SOURCE_INCOMPLETE
        for gate in too_wide.gates
    )


def test_input_lag_is_applied_to_snapshot_source_window(tmp_path: Path) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    request = _canonical_request(
        snapshot.manifest.snapshot_hash,
        expression=_expression(input_lag=1),
    )
    report = PITAuditService().audit_snapshot(request, snapshot.path)

    assert report.verdict is ValidationVerdict.PASS
    assert report.output_temporal is not None
    assert report.output_temporal.event_time.date() == date(2024, 1, 4)


def test_proposal_pass_cannot_be_published_as_validated_evidence(tmp_path: Path) -> None:
    report = PITAuditService().audit(_proposal_spec(tmp_path))
    assert report.verdict is ValidationVerdict.PASS
    assert report.evidence_mode is PITEvidenceMode.PROPOSAL_UNBOUND
    with pytest.raises(ValueError, match="cannot be published"):
        PITAuditService().publish(report, tmp_path / "evidence")


@pytest.mark.parametrize(
    "table_name",
    ["bars", "adjustment_factors", "st_status", "suspensions", "price_limits"],
)
def test_future_temporal_inputs_are_hard_rejected(tmp_path: Path, table_name: str) -> None:
    spec = _proposal_spec(tmp_path)
    source = spec.lineage.sources[0]
    future = datetime(2024, 1, 5, 16, 5, tzinfo=SHANGHAI)
    temporal = TemporalMetadata(
        event_time=source.temporal.event_time,
        known_at=future,
        available_at=future,
        observed_at=future,
        evidence_level=AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED,
        policy_id="future-test/v1",
    )
    changed_source = source.model_copy(update={"table_name": table_name, "temporal": temporal})
    changed_lineage = spec.lineage.model_copy(
        update={"sources": (changed_source, *spec.lineage.sources[1:])}
    )
    report = PITAuditService().audit(spec.model_copy(update={"lineage": changed_lineage}))

    assert report.verdict is ValidationVerdict.REJECT
    assert any(gate.reason_code is ReasonCode.LOOK_AHEAD for gate in report.gates)


def test_unknown_availability_and_missing_lineage_are_stable_rejections(tmp_path: Path) -> None:
    spec = _proposal_spec(tmp_path)
    source = spec.lineage.sources[0]
    unknown = source.temporal.model_copy(
        update={"evidence_level": AvailabilityEvidenceLevel.UNKNOWN}
    )
    changed_lineage = spec.lineage.model_copy(
        update={"sources": (source.model_copy(update={"temporal": unknown}),)}
    )
    unknown_report = PITAuditService().audit(spec.model_copy(update={"lineage": changed_lineage}))
    assert any(gate.reason_code is ReasonCode.UNKNOWN_AVAILABILITY for gate in unknown_report.gates)

    missing_lineage = TransformLineage(
        expression=_expression("close"),
        sources=spec.lineage.sources,
        operator_delays=spec.lineage.operator_delays,
    )
    missing_report = PITAuditService().audit(spec.model_copy(update={"lineage": missing_lineage}))
    assert missing_report.verdict is ValidationVerdict.REJECT
    assert any(gate.reason_code is ReasonCode.SOURCE_INCOMPLETE for gate in missing_report.gates)


def test_future_or_out_of_interval_membership_is_rejected(tmp_path: Path) -> None:
    spec = _proposal_spec(tmp_path)
    membership = spec.memberships[0].model_copy(
        update={
            "effective_from": date(2024, 1, 8),
            "effective_to": date(2024, 1, 31),
        }
    )
    report = PITAuditService().audit(spec.model_copy(update={"memberships": (membership,)}))
    assert report.verdict is ValidationVerdict.REJECT
    assert any(
        gate.gate_id == "MEMBERSHIP_AS_OF" and gate.reason_code is not None for gate in report.gates
    )


def test_operator_delay_can_push_derived_feature_past_signal_time(tmp_path: Path) -> None:
    spec = _proposal_spec(tmp_path)
    delayed = spec.lineage.model_copy(
        update={
            "operator_delays": (
                OperatorDelayPolicy(
                    policy_id="delayed-return/v1",
                    operator="return",
                    delay_seconds=int(timedelta(hours=1).total_seconds()),
                ),
            )
        }
    )
    report = PITAuditService().audit(spec.model_copy(update={"lineage": delayed}))
    assert report.verdict is ValidationVerdict.REJECT
    assert any(gate.reason_code is ReasonCode.LOOK_AHEAD for gate in report.gates)
