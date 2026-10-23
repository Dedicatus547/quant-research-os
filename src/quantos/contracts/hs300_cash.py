"""Explicit cash-only successor; previous lifecycle contracts remain frozen."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.cash_option_proof import ContinuousCashOptionRule
from quantos.contracts.hs300_lifecycle import (
    HS300LifecycleDatasetManifest,
    HS300LifecycleProfile,
    HS300LifecycleStudyRequest,
    PreparedHS300LifecycleStudy,
)
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path


class CashRuntimePolicy(CanonicalContract):
    schema_version: Literal["hs300-cash-runtime-policy/v1"] = "hs300-cash-runtime-policy/v1"
    scope: Literal["CASH_ONLY_CONTINUOUS_HOLDING_NECESSARY_CONDITION"] = (
        "CASH_ONLY_CONTINUOUS_HOLDING_NECESSARY_CONDITION"
    )
    proof_phase: Literal["ACTUAL_TARGET_AND_NATIVE_GENERATED_ORDERS_BEFORE_FILL"] = (
        "ACTUAL_TARGET_AND_NATIVE_GENERATED_ORDERS_BEFORE_FILL"
    )
    known_rights_or_unknown: Literal["HARD_STOP"] = "HARD_STOP"
    later_ordinary_purchase: Literal["DOES_NOT_RESTORE_THIS_CASH_RIGHT"] = (
        "DOES_NOT_RESTORE_THIS_CASH_RIGHT"
    )
    merger_and_delisting: Literal["UNCHANGED_V1_HARD_BOUNDARIES"] = "UNCHANGED_V1_HARD_BOUNDARIES"
    accounting: Literal["NO_ACCOUNT_OR_RIGHTS_LEDGER_MUTATION"] = (
        "NO_ACCOUNT_OR_RIGHTS_LEDGER_MUTATION"
    )


class BoundArtifact(CanonicalContract):
    schema_version: Literal["hs300-bound-artifact/v1"] = "hs300-bound-artifact/v1"
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def logical_path(cls, value: str) -> str:
        return validate_logical_path(value)


class ClassicOriginReuse(CanonicalContract):
    schema_version: Literal["hs300-classic-origin-reuse/v1"] = "hs300-classic-origin-reuse/v1"
    candidate_id: Literal["classic"] = "classic"
    origin_root: str = Field(min_length=1)
    prepared: BoundArtifact
    receipt: BoundArtifact
    outcome: BoundArtifact
    dependencies: tuple[BoundArtifact, ...] = Field(min_length=1)
    source_refs: tuple[BoundArtifact, ...] = Field(min_length=1)
    adoption_scope: Literal["COMPLETED_ORIGIN_CLASSIC_SAME_SCIENTIFIC_INPUTS"] = (
        "COMPLETED_ORIGIN_CLASSIC_SAME_SCIENTIFIC_INPUTS"
    )


class SignalReuseSpec(CanonicalContract):
    schema_version: Literal["hs300-signal-origin-reuse/v1"] = "hs300-signal-origin-reuse/v1"
    origin_root: str = Field(min_length=1)
    prepared: BoundArtifact
    checkpoint: BoundArtifact
    dependency_manifest: BoundArtifact
    compiler_originals: dict[str, BoundArtifact]
    signal_files: dict[str, BoundArtifact]
    compiler_dependency_hashes: dict[str, str]
    panel_sha256: str = Field(pattern=SHA256_PATTERN)


class HS300CashProfile(HS300LifecycleProfile):
    schema_version: Literal["hs300-daily-trend-tushare-lifecycle/v2"] = (  # pyright: ignore[reportIncompatibleVariableOverride]
        "hs300-daily-trend-tushare-lifecycle/v2"
    )
    cash_runtime_policy_hash: str = CashRuntimePolicy().content_hash


class HS300CashStudyRequest(HS300LifecycleStudyRequest):
    schema_version: Literal["personal-study-request/v5"] = "personal-study-request/v5"  # pyright: ignore[reportIncompatibleVariableOverride]
    profile: HS300CashProfile = Field(default_factory=HS300CashProfile)  # pyright: ignore[reportIncompatibleVariableOverride]


class HS300CashDatasetManifest(HS300LifecycleDatasetManifest):
    schema_version: Literal["personal-dataset/v4"] = "personal-dataset/v4"  # pyright: ignore[reportIncompatibleVariableOverride]
    cash_rules: tuple[ContinuousCashOptionRule, ...] = Field(min_length=1)
    cash_runtime_policy_hash: str = Field(pattern=SHA256_PATTERN)
    native_source_hashes: dict[str, str] = Field(min_length=1)


class PreparedHS300CashStudy(PreparedHS300LifecycleStudy):
    schema_version: Literal["personal-study-prepared/v4"] = "personal-study-prepared/v4"  # pyright: ignore[reportIncompatibleVariableOverride]
    request: HS300CashStudyRequest  # pyright: ignore[reportIncompatibleVariableOverride]
    dataset_manifest: HS300CashDatasetManifest | None  # pyright: ignore[reportIncompatibleVariableOverride]
    origin_reuse: tuple[ClassicOriginReuse, ...] = ()
    signal_reuse: SignalReuseSpec | None = None

    @model_validator(mode="after")
    def cash_bindings(self) -> Self:
        if len(self.origin_reuse) > 1:
            raise ValueError("only one completed classic origin may be adopted")
        if self.request.profile.cash_runtime_policy_hash != CashRuntimePolicy().content_hash:
            raise ValueError("cash runtime profile policy differs")
        if self.dataset_manifest is not None and (
            self.dataset_manifest.cash_runtime_policy_hash != CashRuntimePolicy().content_hash
        ):
            raise ValueError("cash runtime dataset policy differs")
        return self
