from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts.pit import (
    LineageSource,
    OperatorDelayPolicy,
    PITAuditReport,
    PITGateId,
    PITGateResult,
    SafeExpressionNode,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
    TransformLineage,
)
from quantos.contracts.status import ReasonCode, ValidationVerdict
from quantos.contracts.temporal import (
    AvailabilityEvidenceLevel,
    DecisionSchedule,
    TemporalMetadata,
)


def _expression(field_name: str = "close") -> SafeQlibExpressionSpec:
    return SafeQlibExpressionSpec(
        expression_id="momentum_2d",
        nodes=(
            SafeExpressionNode(node_id="price", operator="field", field_name=field_name),
            SafeExpressionNode(node_id="momentum", operator="return", inputs=("price",), window=2),
        ),
        output_node_id="momentum",
    )


def test_safe_expression_is_topological_and_rejects_arbitrary_code() -> None:
    expression = _expression()
    assert expression.nodes[-1].operator is SafeQlibOperator.RETURN
    with pytest.raises(ValidationError):
        SafeQlibExpressionSpec.model_validate(
            {
                "expression_id": "unsafe",
                "nodes": [
                    {
                        "node_id": "x",
                        "operator": "field",
                        "field_name": "close",
                        "code": "import os",
                    }
                ],
                "output_node_id": "x",
            }
        )
    with pytest.raises(ValidationError):
        SafeQlibExpressionSpec(
            expression_id="bad_order",
            nodes=(
                SafeExpressionNode(node_id="out", operator="rank", inputs=("later",)),
                SafeExpressionNode(node_id="later", operator="field", field_name="close"),
            ),
            output_node_id="out",
        )


def test_expression_node_shape_is_operator_specific() -> None:
    with pytest.raises(ValidationError):
        SafeExpressionNode(node_id="bad", operator="divide", inputs=("one",))
    with pytest.raises(ValidationError):
        SafeExpressionNode(node_id="bad", operator="field", inputs=("one",), field_name="close")


def test_lineage_rejects_duplicate_operator_policies() -> None:
    with pytest.raises(ValidationError):
        TransformLineage(
            expression=_expression(),
            sources=(),
            operator_delays=(
                OperatorDelayPolicy(policy_id="one/v1", operator="return", delay_seconds=1),
                OperatorDelayPolicy(policy_id="two/v1", operator="return", delay_seconds=2),
            ),
        )


def test_lineage_rejects_missing_operator_policy() -> None:
    temporal = TemporalMetadata(
        event_time=datetime(2024, 1, 2, 15, tzinfo=UTC),
        known_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        available_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        observed_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        evidence_level=AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED,
        policy_id="test/v1",
    )
    with pytest.raises(ValidationError, match="versioned delay policy"):
        TransformLineage(
            expression=_expression(),
            sources=(
                LineageSource(
                    source_id="bar",
                    table_name="bars",
                    field_name="close",
                    row_key="000001.SZ:2024-01-02",
                    temporal=temporal,
                ),
            ),
            operator_delays=(),
        )


def test_pit_gate_and_report_summaries_are_consistent() -> None:
    passing = PITGateResult(
        gate_id=PITGateId.SCHEDULE,
        verdict=ValidationVerdict.PASS,
        detail="valid",
    )
    temporal = TemporalMetadata(
        event_time=datetime(2024, 1, 2, 15, tzinfo=UTC),
        known_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        available_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        observed_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
        evidence_level=AvailabilityEvidenceLevel.CONSERVATIVE_DERIVED,
        policy_id="test/v1",
    )
    report = PITAuditReport(
        audit_spec_hash="a" * 64,
        snapshot_hash="b" * 64,
        expression_spec_hash=_expression().content_hash,
        schedule=DecisionSchedule(
            signal_time=datetime(2024, 1, 2, 15, tzinfo=UTC),
            signal_available_at=datetime(2024, 1, 2, 15, tzinfo=UTC),
            decision_time=datetime(2024, 1, 2, 16, tzinfo=UTC),
            execution_time=datetime(2024, 1, 3, 9, tzinfo=UTC),
        ),
        verdict=ValidationVerdict.PASS,
        gates=(passing,),
        output_temporal=temporal,
    )
    assert report.limitations == ("SINGLE_SOURCE_NON_VINTAGE",)
    with pytest.raises(ValidationError):
        PITGateResult(
            gate_id=PITGateId.SCHEDULE,
            verdict=ValidationVerdict.REJECT,
            detail="invalid",
        )

    canonical = report.model_dump(mode="python")
    canonical["evidence_mode"] = "CANONICAL_SNAPSHOT_BOUND"
    with pytest.raises(ValidationError, match="request and selector bindings"):
        PITAuditReport.model_validate(canonical)
    with pytest.raises(ValidationError):
        PITGateResult(
            gate_id=PITGateId.SCHEDULE,
            verdict=ValidationVerdict.PASS,
            reason_code=ReasonCode.LOOK_AHEAD,
            detail="invalid",
        )
