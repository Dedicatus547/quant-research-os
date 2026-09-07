"""Safe expression lineage and experiment-time point-in-time audit contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule, TemporalMetadata


class SafeQlibOperator(StrEnum):
    ABS = "abs"
    FIELD = "field"
    REF = "ref"
    RETURN = "return"
    ROLLING_MEAN = "rolling_mean"
    ROLLING_STD = "rolling_std"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    RANK = "rank"
    DELTA = "delta"
    ROLLING_SUM = "rolling_sum"
    ROLLING_MIN = "rolling_min"
    ROLLING_MAX = "rolling_max"


class SafeExpressionNode(CanonicalContract):
    schema_version: Literal["safe-expression-node/v1"] = "safe-expression-node/v1"
    node_id: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    operator: SafeQlibOperator
    inputs: tuple[str, ...] = ()
    field_name: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    window: PositiveInt | None = None

    @model_validator(mode="after")
    def operator_shape_is_valid(self) -> Self:
        unary_window = {
            SafeQlibOperator.DELTA,
            SafeQlibOperator.REF,
            SafeQlibOperator.RETURN,
            SafeQlibOperator.ROLLING_MEAN,
            SafeQlibOperator.ROLLING_STD,
            SafeQlibOperator.ROLLING_SUM,
            SafeQlibOperator.ROLLING_MIN,
            SafeQlibOperator.ROLLING_MAX,
            SafeQlibOperator.RANK,
        }
        binary = {
            SafeQlibOperator.ADD,
            SafeQlibOperator.SUBTRACT,
            SafeQlibOperator.MULTIPLY,
            SafeQlibOperator.DIVIDE,
        }
        if self.operator is SafeQlibOperator.FIELD:
            if self.field_name is None or self.inputs or self.window is not None:
                raise ValueError("field node requires only field_name")
        elif self.operator is SafeQlibOperator.ABS:
            if len(self.inputs) != 1 or self.window is not None or self.field_name is not None:
                raise ValueError("unary element operator requires one input and no window")
        elif self.operator in unary_window:
            if len(self.inputs) != 1 or self.window is None or self.field_name is not None:
                raise ValueError("window operator requires one input and window")
        elif self.operator in binary and (
            len(self.inputs) != 2 or self.window is not None or self.field_name is not None
        ):
            raise ValueError("binary operator requires exactly two inputs")
        return self


class SafeQlibExpressionSpec(CanonicalContract):
    schema_version: Literal["safe-qlib-expression/v1", "safe-qlib-expression/v2"] = (
        "safe-qlib-expression/v1"
    )
    expression_id: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    nodes: tuple[SafeExpressionNode, ...]
    output_node_id: str
    input_lag_trading_days: NonNegativeInt = 0

    @model_validator(mode="after")
    def expression_is_a_topological_dag(self) -> Self:
        known: set[str] = set()
        for node in self.nodes:
            if node.node_id in known:
                raise ValueError("expression node_id must be unique")
            if any(input_id not in known for input_id in node.inputs):
                raise ValueError("expression nodes must be in topological order")
            known.add(node.node_id)
        if not known or self.output_node_id not in known:
            raise ValueError("output_node_id must resolve to an expression node")
        v2_operators = {
            SafeQlibOperator.ABS,
            SafeQlibOperator.DELTA,
            SafeQlibOperator.ROLLING_MAX,
            SafeQlibOperator.ROLLING_MIN,
            SafeQlibOperator.ROLLING_SUM,
        }
        if self.schema_version == "safe-qlib-expression/v1" and any(
            node.operator in v2_operators for node in self.nodes
        ):
            raise ValueError("DSL v2 operators require safe-qlib-expression/v2")
        return self


class LineageSource(CanonicalContract):
    schema_version: Literal["lineage-source/v1"] = "lineage-source/v1"
    source_id: str = Field(min_length=1)
    table_name: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    row_key: str = Field(min_length=1)
    temporal: TemporalMetadata


class OperatorDelayPolicy(CanonicalContract):
    schema_version: Literal["operator-delay-policy/v1"] = "operator-delay-policy/v1"
    policy_id: str = Field(min_length=1)
    operator: SafeQlibOperator
    delay_seconds: NonNegativeInt = 0


class TransformLineage(CanonicalContract):
    schema_version: Literal["transform-lineage/v1"] = "transform-lineage/v1"
    expression: SafeQlibExpressionSpec
    sources: tuple[LineageSource, ...]
    operator_delays: tuple[OperatorDelayPolicy, ...]

    @field_validator("sources")
    @classmethod
    def sources_are_unique(cls, value: tuple[LineageSource, ...]) -> tuple[LineageSource, ...]:
        ids = [source.source_id for source in value]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("lineage sources must be nonempty and unique")
        return value

    @model_validator(mode="after")
    def operator_delay_policy_is_complete(self) -> Self:
        operators = [item.operator for item in self.operator_delays]
        if len(operators) != len(set(operators)):
            raise ValueError("operator delay policies must be unique")
        required = {
            node.operator
            for node in self.expression.nodes
            if node.operator is not SafeQlibOperator.FIELD
        }
        if set(operators) != required:
            raise ValueError("every used non-field operator requires one versioned delay policy")
        return self


class MembershipUse(CanonicalContract):
    schema_version: Literal["membership-use/v1"] = "membership-use/v1"
    index_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    effective_from: date
    effective_to: date
    temporal: TemporalMetadata

    @model_validator(mode="after")
    def effective_interval_is_ordered(self) -> Self:
        if self.effective_from > self.effective_to:
            raise ValueError("membership effective interval is invalid")
        return self


class PITAuditSpec(CanonicalContract):
    schema_version: Literal["pit-audit-spec/v1"] = "pit-audit-spec/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    lineage: TransformLineage
    schedule: DecisionSchedule
    memberships: tuple[MembershipUse, ...] = ()


class CanonicalPITAuditRequest(CanonicalContract):
    """Selectors only; temporal evidence is always loaded from a verified snapshot."""

    schema_version: Literal["canonical-pit-audit-request/v1"] = "canonical-pit-audit-request/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    expression: SafeQlibExpressionSpec
    operator_delays: tuple[OperatorDelayPolicy, ...]
    schedule: DecisionSchedule

    @model_validator(mode="after")
    def operator_policies_match_expression(self) -> Self:
        provided = [item.operator for item in self.operator_delays]
        required = {
            node.operator
            for node in self.expression.nodes
            if node.operator is not SafeQlibOperator.FIELD
        }
        if len(provided) != len(set(provided)) or set(provided) != required:
            raise ValueError("operator policies must exactly cover expression operators")
        return self


class PITEvidenceMode(StrEnum):
    PROPOSAL_UNBOUND = "PROPOSAL_UNBOUND"
    CANONICAL_SNAPSHOT_BOUND = "CANONICAL_SNAPSHOT_BOUND"


class PITGateId(StrEnum):
    SNAPSHOT_BINDING = "SNAPSHOT_BINDING"
    SOURCE_WINDOW = "SOURCE_WINDOW"
    LINEAGE_COMPLETE = "LINEAGE_COMPLETE"
    SOURCE_AVAILABILITY = "SOURCE_AVAILABILITY"
    DERIVED_AVAILABILITY = "DERIVED_AVAILABILITY"
    MEMBERSHIP_AS_OF = "MEMBERSHIP_AS_OF"
    SCHEDULE = "SCHEDULE"


class PITGateResult(CanonicalContract):
    schema_version: Literal["pit-gate-result/v1"] = "pit-gate-result/v1"
    gate_id: PITGateId
    verdict: ValidationVerdict
    reason_code: ReasonCode | None = None
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def verdict_and_reason_match(self) -> Self:
        if self.verdict is ValidationVerdict.PASS and self.reason_code is not None:
            raise ValueError("passing PIT gate cannot have a reason code")
        if self.verdict is ValidationVerdict.REJECT and self.reason_code is None:
            raise ValueError("rejected PIT gate requires a reason code")
        if self.verdict is ValidationVerdict.NOT_EVALUATED:
            raise ValueError("completed PIT audit gates cannot be NOT_EVALUATED")
        return self


class PITAuditReport(CanonicalContract):
    schema_version: Literal["pit-audit-report/v1"] = "pit-audit-report/v1"
    audit_spec_hash: str = Field(pattern=SHA256_PATTERN)
    canonical_request_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    schedule: DecisionSchedule
    instrument_id: str | None = Field(default=None, pattern=r"^[0-9]{6}\.(SH|SZ)$")
    universe_index: str | None = Field(default=None, pattern=r"^[0-9]{6}\.(SH|SZ)$")
    evidence_mode: PITEvidenceMode = PITEvidenceMode.PROPOSAL_UNBOUND
    run_status: Literal[RunStatus.SUCCEEDED] = RunStatus.SUCCEEDED
    verdict: ValidationVerdict
    gates: tuple[PITGateResult, ...]
    output_temporal: TemporalMetadata | None
    limitations: tuple[Literal["SINGLE_SOURCE_NON_VINTAGE"], ...] = ("SINGLE_SOURCE_NON_VINTAGE",)

    @model_validator(mode="after")
    def report_summary_matches_gates(self) -> Self:
        if not self.gates:
            raise ValueError("PIT audit report must contain gates")
        expected = (
            ValidationVerdict.PASS
            if all(gate.verdict is ValidationVerdict.PASS for gate in self.gates)
            else ValidationVerdict.REJECT
        )
        if self.verdict is not expected:
            raise ValueError("PIT audit verdict does not match gates")
        if self.verdict is ValidationVerdict.PASS and self.output_temporal is None:
            raise ValueError("passing PIT audit requires output temporal evidence")
        canonical_bindings = (
            self.canonical_request_hash,
            self.instrument_id,
            self.universe_index,
        )
        if self.evidence_mode is PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND:
            if any(item is None for item in canonical_bindings):
                raise ValueError("canonical PIT evidence requires request and selector bindings")
        elif any(item is not None for item in canonical_bindings):
            raise ValueError("proposal PIT evidence cannot claim canonical request bindings")
        return self
