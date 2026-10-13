"""Explicit consumption of retained, successfully verified prediction evidence."""

from typing import Literal, Self

from pydantic import Field, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.refs import SHA256_PATTERN


class RetainedPredictionEvidence(CanonicalContract):
    schema_version: Literal["retained-prediction-evidence/v1"] = "retained-prediction-evidence/v1"
    execution_request_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_root: str = Field(min_length=1)
    manifest_hash: str = Field(pattern=SHA256_PATTERN)


class PredictionEvidenceAdoption(CanonicalContract):
    schema_version: Literal["prediction-evidence-adoption/v1"] = "prediction-evidence-adoption/v1"
    prior_report: PredictionFileSource
    prior_report_exit: PredictionFileSource
    prior_report_prelaunch: PredictionFileSource
    prior_operator: PredictionFileSource
    prior_configuration: PredictionFileSource
    prior_profile: PredictionFileSource
    prior_cohort: PredictionFileSource
    comparison_policy: PredictionFileSource
    prior_verifier_capsule: PredictionFileSource
    prior_verifier_inventory: PredictionFileSource
    retained: tuple[RetainedPredictionEvidence, ...]
    interpretation: Literal["RETAINED_VERIFIED_EVIDENCE_ORIGINS_UNCHANGED"] = (
        "RETAINED_VERIFIED_EVIDENCE_ORIGINS_UNCHANGED"
    )
    pit_reconstruction_repeated: Literal[False] = False
    original_scientific_outcomes_changed: Literal[False] = False

    @model_validator(mode="after")
    def unique_retained_requests(self) -> Self:
        keys = tuple(item.execution_request_hash for item in self.retained)
        if not keys or keys != tuple(sorted(set(keys))):
            raise ValueError("retained evidence requires ordered unique request hashes")
        return self
