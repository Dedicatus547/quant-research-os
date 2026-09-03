"""Public contracts for the deterministic G0-G10 validation pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.provenance import RuntimeFingerprint
from quantos.contracts.refs import SHA256_PATTERN, ArtifactRef
from quantos.contracts.research import SoftMetric
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict


class ValidationGateId(StrEnum):
    G0_SCHEMA_REFERENCE = "G0_SCHEMA_REFERENCE"
    G1_SNAPSHOT_DATA_QUALITY = "G1_SNAPSHOT_DATA_QUALITY"
    G2_PIT_LINEAGE = "G2_PIT_LINEAGE"
    G3_FACTOR_RESEARCH = "G3_FACTOR_RESEARCH"
    G4_REFERENCE_BACKTEST = "G4_REFERENCE_BACKTEST"
    G5_OUT_OF_SAMPLE = "G5_OUT_OF_SAMPLE"
    G6_COST_STRESS = "G6_COST_STRESS"
    G7_PARAMETER_STABILITY = "G7_PARAMETER_STABILITY"
    G8_SUBPERIOD_STABILITY = "G8_SUBPERIOD_STABILITY"
    G9_REPRODUCIBILITY = "G9_REPRODUCIBILITY"
    G10_ARTIFACT_INTEGRITY = "G10_ARTIFACT_INTEGRITY"


VALIDATION_GATE_ORDER: tuple[ValidationGateId, ...] = tuple(ValidationGateId)


class GateSeverity(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class ValidationMetric(CanonicalContract):
    schema_version: Literal["validation-metric/v1"] = "validation-metric/v1"
    metric: SoftMetric
    value: float
    source: ArtifactRef
    detail: str = Field(min_length=1)


class RobustnessKind(StrEnum):
    COST_STRESS = "COST_STRESS"
    PARAMETER_STABILITY = "PARAMETER_STABILITY"
    SUBPERIOD = "SUBPERIOD"


class RobustnessCaseResult(CanonicalContract):
    schema_version: Literal["robustness-case-result/v1"] = "robustness-case-result/v1"
    kind: RobustnessKind
    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    dimensions: tuple[str, ...]
    observation_count: NonNegativeInt
    metrics: tuple[ValidationMetric, ...]
    evidence: tuple[ArtifactRef, ...]

    @field_validator("dimensions")
    @classmethod
    def dimensions_are_sorted_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("robustness dimensions must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def evidence_and_metrics_are_present(self) -> Self:
        if not self.evidence:
            raise ValueError("robustness case requires verified evidence")
        metrics = [item.metric for item in self.metrics]
        if len(metrics) != len(set(metrics)):
            raise ValueError("robustness case metrics must be unique")
        return self


class ReproducibilityComparison(CanonicalContract):
    schema_version: Literal["reproducibility-comparison/v1"] = "reproducibility-comparison/v1"
    left: ArtifactRef
    right: ArtifactRef
    exact_content_hash: bool
    exact_fields_checked: NonNegativeInt
    float_fields_checked: NonNegativeInt
    max_absolute_error: float = Field(ge=0)
    absolute_tolerance: float = Field(ge=0)
    relative_tolerance: float = Field(ge=0)
    passed: bool
    detail: str = Field(min_length=1)


class GateResult(CanonicalContract):
    schema_version: Literal["gate-result/v1"] = "gate-result/v1"
    gate_id: ValidationGateId
    severity: GateSeverity
    verdict: ValidationVerdict
    reason_code: ReasonCode | None = None
    reason: str = Field(min_length=1)
    evidence: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> Self:
        if self.verdict is ValidationVerdict.PASS and self.reason_code is not None:
            raise ValueError("passing gate cannot have a reason code")
        if self.verdict is ValidationVerdict.REJECT and self.reason_code is None:
            raise ValueError("rejected gate requires a reason code")
        if self.verdict is not ValidationVerdict.NOT_EVALUATED and not self.evidence:
            raise ValueError("evaluated gate requires immutable evidence")
        return self


class ValidationArtifactFile(CanonicalContract):
    schema_version: Literal["validation-artifact-file/v1"] = "validation-artifact-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("validation file path must be a safe relative POSIX path")
        return path.as_posix()


class ValidationReport(CanonicalContract):
    """Immutable strategy verdict; runtime access timestamps are outer metadata."""

    schema_version: Literal["validation-report/v2"] = "validation-report/v2"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset(
        {"report_hash", "created_at", "oos_access_event"}
    )

    report_hash: str = Field(pattern=SHA256_PATTERN)
    experiment_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    authoring_spec_hash: str = Field(pattern=SHA256_PATTERN)
    resolved_experiment_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_policy_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    qlib_view_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    signal_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    backtest_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    run_status: RunStatus
    verdict: ValidationVerdict
    canonical: bool
    gates: tuple[GateResult, ...]
    metrics: tuple[ValidationMetric, ...] = ()
    robustness_cases: tuple[RobustnessCaseResult, ...] = ()
    reproducibility: ReproducibilityComparison | None = None
    oos_access_event: ArtifactRef | None = None
    limitations: tuple[str, ...] = ("SINGLE_SOURCE_NON_VINTAGE",)
    files: tuple[ValidationArtifactFile, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("validation report created_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("gates")
    @classmethod
    def gates_are_complete_and_ordered(
        cls, value: tuple[GateResult, ...]
    ) -> tuple[GateResult, ...]:
        if tuple(item.gate_id for item in value) != VALIDATION_GATE_ORDER:
            raise ValueError("validation report must contain G0-G10 in order")
        return value

    @field_validator("metrics")
    @classmethod
    def metrics_are_unique(
        cls, value: tuple[ValidationMetric, ...]
    ) -> tuple[ValidationMetric, ...]:
        metrics = [item.metric for item in value]
        if len(metrics) != len(set(metrics)):
            raise ValueError("validation summary metrics must be unique")
        return value

    @field_validator("files")
    @classmethod
    def files_are_exact(
        cls, value: tuple[ValidationArtifactFile, ...]
    ) -> tuple[ValidationArtifactFile, ...]:
        expected = [
            "authoring-spec.json",
            "research-policy.json",
            "runtime-fingerprint.json",
            "validation-policy.json",
        ]
        if [item.logical_path for item in value] != expected:
            raise ValueError("validation artifact file set does not match v2")
        return value

    @model_validator(mode="after")
    def summary_is_consistent(self) -> Self:
        rejected = any(item.verdict is ValidationVerdict.REJECT for item in self.gates)
        if self.run_status is RunStatus.FAILED:
            if self.verdict is not ValidationVerdict.NOT_EVALUATED:
                raise ValueError("failed runs must have a NOT_EVALUATED summary verdict")
        else:
            expected = ValidationVerdict.REJECT if rejected else ValidationVerdict.PASS
            if self.verdict is not expected:
                raise ValueError("successful run verdict does not match gate results")
        if self.verdict is ValidationVerdict.PASS and any(
            item.verdict is not ValidationVerdict.PASS for item in self.gates
        ):
            raise ValueError("passing report requires every gate to pass")
        if "SINGLE_SOURCE_NON_VINTAGE" not in self.limitations:
            raise ValueError("validation report must disclose the source-vintage limitation")
        if self.report_hash != self.content_hash:
            raise ValueError("report_hash does not match validation report content")
        return self

    @classmethod
    def create(cls, **values: Any) -> Self:
        provisional = cls.model_construct(report_hash="0" * 64, **values)
        digest = sha256_bytes(canonical_json_bytes(provisional.canonical_payload()))
        payload = provisional.model_dump(mode="python")
        payload["report_hash"] = digest
        return cls.model_validate(payload)


def validate_runtime_fingerprint_binding(
    report: ValidationReport, fingerprint: RuntimeFingerprint
) -> None:
    if report.runtime_fingerprint_hash != fingerprint.content_hash:
        raise ValueError("runtime fingerprint does not match validation report binding")
