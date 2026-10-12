"""Cross-origin cohort binding without weakening single-origin prediction profiles."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from quantos.contracts.autonomous import AutonomousExecutionRequest
from quantos.contracts.base import CanonicalContract
from quantos.contracts.discovery_prediction import PredictionEvaluationProfile, PredictionFileSource
from quantos.contracts.refs import SHA256_PATTERN


class ScientificPredictionPolicy(CanonicalContract):
    schema_version: Literal["scientific-prediction-policy/v1"] = "scientific-prediction-policy/v1"
    source_design: PredictionFileSource
    original_sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    min_defined_fraction: float = Field(ge=0, le=1)
    min_common_days: PositiveInt
    meaningful_llm_increment: float = Field(ge=0)
    max_llm_entry_wall_seconds: float = Field(gt=0)
    max_new_science_wall_seconds: float = Field(gt=0)
    adopted_origin_count: NonNegativeInt
    new_execution_count: NonNegativeInt
    max_compute_units: PositiveInt
    expected_growth_bytes: PositiveInt
    interpretation: Literal["SUCCESSOR_RETROSPECTIVE_EXPLORATORY"] = (
        "SUCCESSOR_RETROSPECTIVE_EXPLORATORY"
    )
    selected_by: Literal["PRIMARY_AGENT_WITHIN_USER_AUTHORIZED_SCIENCE_SCOPE"] = (
        "PRIMARY_AGENT_WITHIN_USER_AUTHORIZED_SCIENCE_SCOPE"
    )
    user_specified_individual_values: Literal[False] = False
    monetary_cost_criterion: Literal["UNAVAILABLE_NO_MONETARY_SUPERIORITY_VERDICT"] = (
        "UNAVAILABLE_NO_MONETARY_SUPERIORITY_VERDICT"
    )


class ScientificPredictionOrigin(CanonicalContract):
    schema_version: Literal["scientific-prediction-origin/v1"] = "scientific-prediction-origin/v1"
    target_subtask_hash: str = Field(pattern=SHA256_PATTERN)
    source_subtask_hash: str = Field(pattern=SHA256_PATTERN)
    mode: Literal["NEW_SCIENTIFIC_EXECUTION", "REUSED_HISTORICAL_ORIGIN"]
    actual_request: AutonomousExecutionRequest
    prediction_profile_hash: str = Field(pattern=SHA256_PATTERN)


class ScientificPredictionCohortRepair(CanonicalContract):
    """Separate repair record; original v1 cohort bytes remain unchanged."""

    schema_version: Literal["scientific-prediction-cohort-repair/v1"] = (
        "scientific-prediction-cohort-repair/v1"
    )
    predecessor_cohort: PredictionFileSource
    successor_cohort_hash: str = Field(pattern=SHA256_PATTERN)
    reason: Literal["BASE_VERSUS_DERIVED_AUTHORING_BINDING_FIX"] = (
        "BASE_VERSUS_DERIVED_AUTHORING_BINDING_FIX"
    )
    allowed_change: Literal["VERIFIER_IDENTITIES_AND_DERIVED_PROFILE_HASHES_ONLY"] = (
        "VERIFIER_IDENTITIES_AND_DERIVED_PROFILE_HASHES_ONLY"
    )
    scientific_reexecution_required: Literal[False] = False


class ScientificPredictionCohort(CanonicalContract):
    schema_version: Literal["scientific-prediction-cohort/v1"] = "scientific-prediction-cohort/v1"
    sequential_batch_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_declaration_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_adoption_plan_hash: str = Field(pattern=SHA256_PATTERN)
    scientific_dependency_adoption_hash: str = Field(pattern=SHA256_PATTERN)
    cohort_verifier_identity_hash: str = Field(pattern=SHA256_PATTERN)
    policy: ScientificPredictionPolicy
    expected_dates: tuple[date, ...]
    profiles: tuple[PredictionEvaluationProfile, ...]
    origins: tuple[ScientificPredictionOrigin, ...]
    generation_scope: Literal["FROZEN_WRAPPER_FIFTEEN_OPPORTUNITIES_NO_NEW_CALLS"] = (
        "FROZEN_WRAPPER_FIFTEEN_OPPORTUNITIES_NO_NEW_CALLS"
    )

    @model_validator(mode="after")
    def origins_and_profiles_bind_exactly(self) -> Self:
        targets = tuple(item.target_subtask_hash for item in self.origins)
        if targets != tuple(sorted(set(targets))) or not targets:
            raise ValueError("cohort target tasks must be ordered, unique and complete")
        profile_by_hash = {item.content_hash: item for item in self.profiles}
        if len(profile_by_hash) != len(self.profiles) or tuple(profile_by_hash) != tuple(
            sorted(profile_by_hash)
        ):
            raise ValueError("origin profiles must be ordered and unique")
        assigned: dict[str, set[str]] = {key: set() for key in profile_by_hash}
        for origin in self.origins:
            profile = profile_by_hash.get(origin.prediction_profile_hash)
            if profile is None:
                raise ValueError("origin references an undeclared profile")
            request = origin.actual_request
            if (
                request.content_hash not in profile.execution_request_hashes
                or profile.expected_dates != self.expected_dates
                or profile.min_defined_fraction != self.policy.min_defined_fraction
                or profile.min_common_days != self.policy.min_common_days
                or any(
                    getattr(request, name) != getattr(profile, name)
                    for name in (
                        "code_commit_hash",
                        "lockfile_hash",
                        "qlib_version",
                        "snapshot_hash",
                        "qlib_view_hash",
                        "research_policy_hash",
                    )
                )
            ):
                raise ValueError("origin request differs from its actual single-origin profile")
            assigned[profile.content_hash].add(request.content_hash)
        if any(
            assigned[key] != set(profile.execution_request_hashes)
            for key, profile in profile_by_hash.items()
        ):
            raise ValueError("profile request denominator differs from assigned actual origins")
        if (
            sum(item.mode == "NEW_SCIENTIFIC_EXECUTION" for item in self.origins)
            != self.policy.new_execution_count
            or sum(item.mode == "REUSED_HISTORICAL_ORIGIN" for item in self.origins)
            != self.policy.adopted_origin_count
        ):
            raise ValueError("new executions and historical origins disagree with frozen policy")
        return self
