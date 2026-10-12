"""Versioned retrospective prediction evidence; existing result domains are unchanged."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN

PREDICTION_RULE_SPEC = (
    "finite-pair-constant-null-common-rank-ic/v1",
    "all prediction and label raw keys must match and be unique",
    "prediction must be finite; only native NaN labels excluded; label infinity rejected",
    "complete frozen date calendar; fewer than two finite pairs or constant input is undefined",
    "preserve native value/state independently; exact native IC and Rank IC reproduction with Qlib",
    "primary Rank IC mean on common defined dates of source-verified coverage-admitted candidates",
    "own-date mean is sensitivity only; full frozen request denominator includes missing sources",
    "source, data, PIT and actual model split failures are hard evidence rejections",
)
PREDICTION_RULE_HASH = sha256_bytes(canonical_json_bytes(PREDICTION_RULE_SPEC))


class PredictionFileSource(CanonicalContract):
    schema_version: Literal["prediction-file-source/v1"] = "prediction-file-source/v1"
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class PredictionEvaluationProfile(CanonicalContract):
    """Caller-frozen cohort and coverage requirements, supplied before analysis."""

    schema_version: Literal["prediction-evaluation-profile/v1"] = "prediction-evaluation-profile/v1"
    rule_id: Literal["finite-pair-constant-null-common-rank-ic/v1"] = (
        "finite-pair-constant-null-common-rank-ic/v1"
    )
    interpretation: Literal["SUCCESSOR_RETROSPECTIVE_EXPLORATORY"] = (
        "SUCCESSOR_RETROSPECTIVE_EXPLORATORY"
    )
    rule_hash: str = Field(default=PREDICTION_RULE_HASH, pattern=SHA256_PATTERN)
    verifier_identity_hash: str = Field(pattern=SHA256_PATTERN)
    execution_request_hashes: tuple[str, ...]
    expected_dates: tuple[date, ...]
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    research_policy_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: str = Field(min_length=1)
    min_defined_fraction: float = Field(ge=0, le=1)
    min_common_days: PositiveInt

    @model_validator(mode="after")
    def cohort_and_dates_are_explicit(self) -> Self:
        if self.rule_hash != PREDICTION_RULE_HASH:
            raise ValueError("prediction rule hash differs from the declared version")
        if not self.expected_dates or self.expected_dates != tuple(
            sorted(set(self.expected_dates))
        ):
            raise ValueError("expected dates must be complete, ordered and unique")
        if (
            not self.execution_request_hashes
            or self.execution_request_hashes != tuple(sorted(set(self.execution_request_hashes)))
            or any(
                len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
                for value in self.execution_request_hashes
            )
            or self.min_common_days > len(self.expected_dates)
        ):
            raise ValueError("cohort and common-day requirement are inconsistent")
        return self


class PredictionImportSource(CanonicalContract):
    """Explicit controlled originals; hashes pin metadata, paths select immutable stores."""

    schema_version: Literal["prediction-import-source/v1"] = "prediction-import-source/v1"
    request: PredictionFileSource
    outcome: PredictionFileSource
    receipt: PredictionFileSource
    resolved: PredictionFileSource
    research_policy: PredictionFileSource
    workflow_reservation: PredictionFileSource
    workflow_completion: PredictionFileSource
    management_exit: PredictionFileSource
    source_capsule: PredictionFileSource
    source_inventory: PredictionFileSource
    source_workspace: str = Field(min_length=1)
    native_root: str = Field(min_length=1)
    model_split_sha256: str = Field(pattern=SHA256_PATTERN)
    snapshot_path: str = Field(min_length=1)
    qlib_view_path: str = Field(min_length=1)
    signal_path: str = Field(min_length=1)
    signal_hash: str = Field(pattern=SHA256_PATTERN)


class PredictionStatistic(CanonicalContract):
    schema_version: Literal["prediction-statistic/v1"] = "prediction-statistic/v1"
    native_value: float | None
    native_state: Literal["FINITE", "NAN", "POSITIVE_INFINITY", "NEGATIVE_INFINITY"]
    value: float | None
    status: Literal["DEFINED", "UNDEFINED"]
    reason: Literal[
        "DEFINED_FINITE_PAIRS",
        "INSUFFICIENT_FINITE_PAIRS",
        "CONSTANT_PREDICTION",
        "CONSTANT_LABEL",
    ]

    @model_validator(mode="after")
    def values_keep_definedness_separate(self) -> Self:
        if (self.native_state == "FINITE") != (self.native_value is not None):
            raise ValueError("native finite state and value disagree")
        if (self.status == "DEFINED") != (self.value is not None):
            raise ValueError("mathematical definedness and value disagree")
        if (self.status == "DEFINED") != (self.reason == "DEFINED_FINITE_PAIRS"):
            raise ValueError("definedness and reason disagree")
        if self.status == "DEFINED" and (
            self.native_state != "FINITE" or self.value != self.native_value
        ):
            raise ValueError("defined statistic must preserve its native value")
        return self


class PredictionDay(CanonicalContract):
    schema_version: Literal["prediction-day/v1"] = "prediction-day/v1"
    trade_date: date
    prediction_rows: PositiveInt
    label_rows: PositiveInt
    paired_rows: PositiveInt
    finite_pairs: NonNegativeInt
    prediction_nonfinite: NonNegativeInt
    label_nan: NonNegativeInt
    label_infinite: NonNegativeInt
    prediction_unique_finite: NonNegativeInt
    label_unique_finite: NonNegativeInt
    ic: PredictionStatistic
    rank_ic: PredictionStatistic

    @model_validator(mode="after")
    def counts_retain_raw_denominator(self) -> Self:
        if (
            self.prediction_rows != self.label_rows
            or self.paired_rows != self.prediction_rows
            or self.finite_pairs + self.label_nan != self.paired_rows
            or self.prediction_nonfinite != 0
            or self.label_infinite != 0
        ):
            raise ValueError("raw/finite pair counts disagree with finite-pair profile")
        return self


class PredictionEvidence(CanonicalContract):
    schema_version: Literal["prediction-evidence/v1"] = "prediction-evidence/v1"
    profile_hash: str = Field(pattern=SHA256_PATTERN)
    source_hash: str = Field(pattern=SHA256_PATTERN)
    verifier_identity_hash: str = Field(pattern=SHA256_PATTERN)
    execution_request_hash: str = Field(pattern=SHA256_PATTERN)
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    structural_expression_hash: str = Field(pattern=SHA256_PATTERN)
    raw_key_hash: str = Field(pattern=SHA256_PATTERN)
    omitted_nan_label_key_hash: str = Field(pattern=SHA256_PATTERN)
    raw_pair_count: PositiveInt
    finite_pair_count: NonNegativeInt
    omitted_nan_label_count: NonNegativeInt
    model_split_hash: str = Field(pattern=SHA256_PATTERN)
    signal_hash: str = Field(pattern=SHA256_PATTERN)
    pit_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    native_sources: tuple[PredictionFileSource, ...]
    daily: tuple[PredictionDay, ...]
    original_outcome_hash: str = Field(pattern=SHA256_PATTERN)
    original_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    original_validation_report_hash: str | None = Field(pattern=SHA256_PATTERN)
    original_research_result_hash: str | None = Field(pattern=SHA256_PATTERN)
    original_failure_reason: str | None
    original_execution_outcome: str
    original_stage_status: str
    limitations: tuple[str, ...] = (
        "RETROSPECTIVE_EXPLORATORY_ONLY",
        "ORIGINAL_VALIDATION_AND_P14C_UNCHANGED",
        "PIT_COVERAGE_IS_RETAINED_ORIGINAL_SCHEDULES",
        "NO_HISTORICAL_VENDOR_VINTAGE_CLAIM",
        "MODEL_TRAIN_VALID_SAMPLE_AUDITS_ADOPTED_NOT_REEXECUTED",
    )


class PredictionEvidenceManifest(CanonicalContract):
    schema_version: Literal["prediction-evidence-manifest/v1"] = "prediction-evidence-manifest/v1"
    profile_hash: str = Field(pattern=SHA256_PATTERN)
    source_hash: str = Field(pattern=SHA256_PATTERN)
    verifier_identity_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_hash: str = Field(pattern=SHA256_PATTERN)
    execution_request_hash: str = Field(pattern=SHA256_PATTERN)
