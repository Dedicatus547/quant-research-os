"""Deterministic Qlib research translation and universe-resolution evidence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.pit import CanonicalPITAuditRequest, PITAuditReport, PITEvidenceMode
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule


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
