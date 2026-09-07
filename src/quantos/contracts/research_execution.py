"""Deterministic Qlib research translation and universe-resolution evidence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.pit import (
    CanonicalPITAuditRequest,
    OperatorDelayPolicy,
    PITAuditReport,
    PITEvidenceMode,
    PITGateId,
    PITGateResult,
    SafeQlibExpressionSpec,
    SafeQlibOperator,
)
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule, TemporalMetadata


class QlibExpressionTranslation(CanonicalContract):
    schema_version: Literal["qlib-expression-translation/v1"] = "qlib-expression-translation/v1"
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    output_name: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    output_expression: str = Field(min_length=1)


class HistoricalUniverseMember(CanonicalContract):
    schema_version: Literal["historical-universe-member/v1"] = "historical-universe-member/v1"
    instrument_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    qlib_id: str = Field(pattern=r"^(SH|SZ)[0-9]{6}$")
    weight_percent: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def identifiers_are_reversible(self) -> Self:
        if self.qlib_id != f"{self.instrument_id[-2:]}{self.instrument_id[:6]}":
            raise ValueError("historical universe mapping is not reversible")
        return self


class HistoricalUniverseResolution(CanonicalContract):
    schema_version: Literal["historical-universe-resolution/v1"] = (
        "historical-universe-resolution/v1"
    )
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    source_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    index_id: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    as_of_date: date
    decision_time: datetime
    members: tuple[HistoricalUniverseMember, ...]

    @field_validator("decision_time")
    @classmethod
    def decision_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        return value

    @field_validator("members")
    @classmethod
    def members_are_sorted_and_unique(
        cls, value: tuple[HistoricalUniverseMember, ...]
    ) -> tuple[HistoricalUniverseMember, ...]:
        ids = [item.instrument_id for item in value]
        if not value or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("historical universe members must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def decision_matches_as_of_date(self) -> Self:
        if self.decision_time.date() != self.as_of_date:
            raise ValueError("decision_time date must equal as_of_date")
        return self


class PITAuditEvidenceItem(CanonicalContract):
    """A canonical PIT request paired with the exact report that evaluated it."""

    schema_version: Literal["pit-audit-evidence-item/v1"] = "pit-audit-evidence-item/v1"
    request: CanonicalPITAuditRequest
    report: PITAuditReport

    @model_validator(mode="after")
    def request_and_report_are_bound(self) -> Self:
        if self.report.evidence_mode is not PITEvidenceMode.CANONICAL_SNAPSHOT_BOUND:
            raise ValueError("PIT evidence item requires canonical snapshot-bound evidence")
        if self.report.verdict is not ValidationVerdict.PASS:
            raise ValueError("PIT evidence item requires a passing report")
        if self.report.canonical_request_hash != self.request.content_hash:
            raise ValueError("PIT report does not bind the canonical request")
        if self.report.snapshot_hash != self.request.snapshot_hash:
            raise ValueError("PIT report snapshot does not match its request")
        if self.report.expression_spec_hash != self.request.expression.content_hash:
            raise ValueError("PIT report expression does not match its request")
        if self.report.schedule != self.request.schedule:
            raise ValueError("PIT report schedule does not match its request")
        if self.report.instrument_id != self.request.instrument_id:
            raise ValueError("PIT report instrument does not match its request")
        if self.report.universe_index != self.request.universe_index:
            raise ValueError("PIT report universe does not match its request")
        return self


class PITAuditEvidenceBundle(CanonicalContract):
    """Complete PIT evidence for one decision-time signal cross section."""

    schema_version: Literal["pit-audit-evidence-bundle/v1"] = "pit-audit-evidence-bundle/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    schedule: DecisionSchedule
    items: tuple[PITAuditEvidenceItem, ...]

    @model_validator(mode="after")
    def items_are_complete_and_consistent(self) -> Self:
        ids = [item.request.instrument_id for item in self.items]
        if not ids or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("PIT evidence items must be nonempty, sorted, and unique")
        for item in self.items:
            request = item.request
            if request.snapshot_hash != self.snapshot_hash:
                raise ValueError("PIT evidence bundle contains a different snapshot")
            if request.expression.content_hash != self.expression_spec_hash:
                raise ValueError("PIT evidence bundle contains a different expression")
            if request.universe_index != self.universe_index:
                raise ValueError("PIT evidence bundle contains a different universe")
            if request.schedule != self.schedule:
                raise ValueError("PIT evidence bundle contains a different decision schedule")
        return self


class PITAuditEvidenceCollection(CanonicalContract):
    """Ordered PIT evidence for every decision cross section in a signal artifact."""

    schema_version: Literal["pit-audit-evidence-collection/v1"] = "pit-audit-evidence-collection/v1"
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    bundles: tuple[PITAuditEvidenceBundle, ...]

    @model_validator(mode="after")
    def bundles_are_ordered_and_consistent(self) -> Self:
        schedules = [bundle.schedule for bundle in self.bundles]
        keys = [
            (schedule.signal_time, schedule.decision_time, schedule.execution_time)
            for schedule in schedules
        ]
        if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("PIT evidence bundles must be nonempty, ordered, and unique")
        for bundle in self.bundles:
            if bundle.snapshot_hash != self.snapshot_hash:
                raise ValueError("PIT evidence collection contains a different snapshot")
            if bundle.expression_spec_hash != self.expression_spec_hash:
                raise ValueError("PIT evidence collection contains a different expression")
            if bundle.universe_index != self.universe_index:
                raise ValueError("PIT evidence collection contains a different universe")
        return self


class PITSourceSetEvidence(CanonicalContract):
    """Digest and availability summary for one canonical source-table projection."""

    schema_version: Literal["pit-source-set-evidence/v2"] = "pit-source-set-evidence/v2"
    table_name: Literal["bars", "adjustment_factors"]
    logical_field_name: Literal["close", "adjusted_close"]
    source_field_name: Literal["close", "adjustment_factor"]
    expected_row_count: PositiveInt
    present_row_count: NonNegativeInt
    missing_row_count: NonNegativeInt
    row_set_hash: str = Field(pattern=SHA256_PATTERN)
    maximum_temporal: TemporalMetadata | None

    @model_validator(mode="after")
    def counts_and_temporal_are_consistent(self) -> Self:
        if self.present_row_count + self.missing_row_count != self.expected_row_count:
            raise ValueError("PIT source-set counts do not reconcile")
        if (self.present_row_count == 0) != (self.maximum_temporal is None):
            raise ValueError("PIT source-set temporal summary does not match row presence")
        return self


class PITMembershipSetEvidence(CanonicalContract):
    """Digest of the exact effective and available membership rows used."""

    schema_version: Literal["pit-membership-set-evidence/v2"] = "pit-membership-set-evidence/v2"
    row_count: PositiveInt
    row_set_hash: str = Field(pattern=SHA256_PATTERN)
    maximum_temporal: TemporalMetadata


class PITCrossSectionEvidenceBundle(CanonicalContract):
    """Compact PIT proof for one complete decision-time cross section."""

    schema_version: Literal["pit-cross-section-evidence-bundle/v2"] = (
        "pit-cross-section-evidence-bundle/v2"
    )
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    schedule: DecisionSchedule
    required_observations: PositiveInt
    source_window: tuple[date, ...]
    members: tuple[str, ...]
    source_sets: tuple[PITSourceSetEvidence, ...]
    membership_set: PITMembershipSetEvidence
    output_temporal: TemporalMetadata
    gates: tuple[PITGateResult, ...]

    @field_validator("source_window")
    @classmethod
    def source_window_is_complete_and_ordered(cls, value: tuple[date, ...]) -> tuple[date, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("PIT source window must be nonempty, sorted, and unique")
        return value

    @field_validator("members")
    @classmethod
    def members_are_supported_sorted_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if (
            not value
            or value != tuple(sorted(set(value)))
            or any(re.fullmatch(r"[0-9]{6}\.(SH|SZ)", item) is None for item in value)
        ):
            raise ValueError("PIT members must be nonempty supported sorted unique identifiers")
        return value

    @model_validator(mode="after")
    def compact_proof_is_consistent(self) -> Self:
        if len(self.source_window) != self.required_observations:
            raise ValueError("PIT source window does not match required observations")
        if self.membership_set.row_count != len(self.members):
            raise ValueError("PIT membership evidence must cover every member exactly once")
        keys = [(item.table_name, item.source_field_name) for item in self.source_sets]
        if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("PIT source sets must be nonempty, sorted, and unique")
        expected_rows = len(self.members) * len(self.source_window)
        if any(item.expected_row_count != expected_rows for item in self.source_sets):
            raise ValueError("PIT source sets must cover the complete cross-section window")
        gate_ids = [item.gate_id for item in self.gates]
        if gate_ids != list(PITGateId) or any(
            item.verdict is not ValidationVerdict.PASS for item in self.gates
        ):
            raise ValueError("compact PIT evidence requires every ordered PIT gate to pass")
        if self.output_temporal.available_at > self.schedule.signal_time:
            raise ValueError("compact PIT output is unavailable at signal time")
        if self.membership_set.maximum_temporal.available_at > self.schedule.decision_time:
            raise ValueError("compact PIT membership is unavailable at decision time")
        return self


def required_expression_observations(expression: SafeQlibExpressionSpec) -> int:
    observations: dict[str, int] = {}
    for node in expression.nodes:
        if node.operator is SafeQlibOperator.FIELD:
            observations[node.node_id] = 1
            continue
        base = max(observations[item] for item in node.inputs)
        if node.operator in {
            SafeQlibOperator.DELTA,
            SafeQlibOperator.REF,
            SafeQlibOperator.RETURN,
        }:
            observations[node.node_id] = base + int(node.window or 0)
        elif node.operator in {
            SafeQlibOperator.ROLLING_MEAN,
            SafeQlibOperator.ROLLING_STD,
            SafeQlibOperator.ROLLING_SUM,
            SafeQlibOperator.ROLLING_MIN,
            SafeQlibOperator.ROLLING_MAX,
            SafeQlibOperator.RANK,
        }:
            observations[node.node_id] = base + int(node.window or 0) - 1
        else:
            observations[node.node_id] = base
    return observations[expression.output_node_id]


class PITCrossSectionEvidenceCollection(CanonicalContract):
    """Scalable snapshot-recomputable PIT evidence for production signal grids."""

    schema_version: Literal["pit-cross-section-evidence-collection/v2"] = (
        "pit-cross-section-evidence-collection/v2"
    )
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    expression_spec_hash: str = Field(pattern=SHA256_PATTERN)
    expression: SafeQlibExpressionSpec
    operator_delays: tuple[OperatorDelayPolicy, ...]
    universe_index: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ)$")
    bundles: tuple[PITCrossSectionEvidenceBundle, ...]

    @model_validator(mode="after")
    def bundles_and_expression_are_consistent(self) -> Self:
        if self.expression.content_hash != self.expression_spec_hash:
            raise ValueError("compact PIT expression hash is inconsistent")
        required_operators = {
            node.operator
            for node in self.expression.nodes
            if node.operator is not SafeQlibOperator.FIELD
        }
        provided_operators = [item.operator for item in self.operator_delays]
        if (
            len(provided_operators) != len(set(provided_operators))
            or set(provided_operators) != required_operators
        ):
            raise ValueError("compact PIT operator-delay policies are incomplete")
        keys = [
            (
                bundle.schedule.signal_time,
                bundle.schedule.decision_time,
                bundle.schedule.execution_time,
            )
            for bundle in self.bundles
        ]
        if not keys or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("compact PIT bundles must be nonempty, ordered, and unique")
        required_observations = required_expression_observations(self.expression)
        logical_fields = {
            node.field_name
            for node in self.expression.nodes
            if node.operator is SafeQlibOperator.FIELD
        }
        expected_sources: set[tuple[str, str, str]] = set()
        if "close" in logical_fields:
            expected_sources.add(("bars", "close", "close"))
        if "adjusted_close" in logical_fields:
            expected_sources.update(
                {
                    ("adjustment_factors", "adjusted_close", "adjustment_factor"),
                    ("bars", "adjusted_close", "close"),
                }
            )
        for bundle in self.bundles:
            if (
                bundle.snapshot_hash != self.snapshot_hash
                or bundle.expression_spec_hash != self.expression_spec_hash
                or bundle.universe_index != self.universe_index
                or bundle.required_observations != required_observations
            ):
                raise ValueError("compact PIT bundle bindings are inconsistent")
            actual_sources = {
                (item.table_name, item.logical_field_name, item.source_field_name)
                for item in bundle.source_sets
            }
            if actual_sources != expected_sources:
                raise ValueError("compact PIT bundle source mapping is incomplete")
        return self


PITArtifactEvidence = PITAuditEvidenceCollection | PITCrossSectionEvidenceCollection
