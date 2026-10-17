"""Bounded deterministic feedback; original verified artifacts remain authority."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import SoftMetric
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import ValidationGateId

MAX_FEEDBACK_BYTES = 24 * 1024


class AdaptiveGateFeedback(CanonicalContract):
    schema_version: Literal["adaptive-gate-feedback/v1"] = "adaptive-gate-feedback/v1"
    gate_id: ValidationGateId
    verdict: ValidationVerdict
    reason_code: ReasonCode | None = None


class AdaptiveMetricFeedback(CanonicalContract):
    schema_version: Literal["adaptive-metric-feedback/v1"] = "adaptive-metric-feedback/v1"
    metric: SoftMetric
    value: float | None
    source_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def source_matches_presence(self) -> Self:
        if (self.value is None) != (self.source_hash is None):
            raise ValueError("metric value and original source must both be present or null")
        return self


class AdaptiveProcessExit(CanonicalContract):
    """Caller observation only; never a substitute for the verified receipt."""

    schema_version: Literal["adaptive-process-exit/v1"] = "adaptive-process-exit/v1"
    exit_code: StrictInt | None = None
    evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    authority: Literal["UNVERIFIED_OBSERVATION"] = "UNVERIFIED_OBSERVATION"


class AdaptiveFeedback(CanonicalContract):
    schema_version: Literal["adaptive-feedback/v1"] = "adaptive-feedback/v1"
    authority: Literal["VERIFIED_ORIGINALS_REMAIN_AUTHORITY"] = (
        "VERIFIED_ORIGINALS_REMAIN_AUTHORITY"
    )
    task_hash: str = Field(pattern=SHA256_PATTERN)
    child_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_exact_expression_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_structural_expression_hash: str = Field(pattern=SHA256_PATTERN)
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    outcome_hash: str = Field(pattern=SHA256_PATTERN)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)
    outcome: TrialOutcome
    run_status: RunStatus
    verdict: ValidationVerdict
    failure_reason_code: ReasonCode | None = None
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    failure_evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    original_hashes: tuple[str, ...]
    gates: tuple[AdaptiveGateFeedback, ...] = Field(max_length=11)
    metrics: tuple[AdaptiveMetricFeedback, ...] = Field(max_length=len(SoftMetric))
    missing_evidence: tuple[Literal["VALIDATION_REPORT", "PROCESS_EXIT"], ...] = ()
    process_exit: AdaptiveProcessExit | None = None
    compute_units: int = Field(ge=0)
    token_usage: None = None
    limitations: tuple[Literal["SINGLE_SOURCE_NON_VINTAGE", "PROJECTION_IS_NOT_AUTHORITY"], ...] = (
        "SINGLE_SOURCE_NON_VINTAGE",
        "PROJECTION_IS_NOT_AUTHORITY",
    )

    @model_validator(mode="after")
    def bounded_and_consistent(self) -> Self:
        import re

        if self.original_hashes != tuple(sorted(set(self.original_hashes))) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in self.original_hashes
        ):
            raise ValueError("original hashes must be sorted unique SHA256 identities")
        for digest in (self.receipt_hash, self.validation_report_hash, self.failure_evidence_hash):
            if digest is not None and digest not in self.original_hashes:
                raise ValueError("feedback source is absent from verified originals")
        if tuple(item.metric for item in self.metrics) != tuple(SoftMetric):
            raise ValueError("feedback requires every ordered scalar metric, missing values null")
        if self.gates and tuple(item.gate_id for item in self.gates) != tuple(ValidationGateId):
            raise ValueError("feedback gates must be complete and ordered")
        if self.run_status is RunStatus.FAILED:
            if self.verdict is not ValidationVerdict.NOT_EVALUATED:
                raise ValueError("execution failure cannot have a scientific verdict")
            if any(item.value is not None for item in self.metrics):
                raise ValueError("execution failure cannot supply scientific metrics")
        if len(self.canonical_bytes()) > MAX_FEEDBACK_BYTES:
            raise ValueError("adaptive feedback exceeds 24 KiB")
        return self
