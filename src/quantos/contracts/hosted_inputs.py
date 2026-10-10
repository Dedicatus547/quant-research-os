"""Pure typed management configuration for a frozen hosted business registration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.autonomous import (
    AutonomousAgentRunPolicy,
    AutonomousCampaignPolicy,
    AutonomousExecutionBindings,
    AutonomousSelectionFinalizationProfile,
)
from quantos.contracts.campaign import (
    CampaignEventType,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
    ResearchFamilySpec,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionPlan,
    MultipleTestingPolicySpec,
    SelectionPolicySpec,
)
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.hosted import (
    Hash,
    HostedBudgetPolicy,
    HostedCampaignSpec,
    HostedContract,
    Identity,
)
from quantos.contracts.ledger import (
    ResearchContextBudgetPolicy,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSnapshot,
)
from quantos.contracts.provenance import CodeProvenance
from quantos.contracts.research import ExperimentAuthoringSpec, ResearchPolicy, ValidationPolicy


class HostedFrozenInputFile(HostedContract):
    schema_version: Literal["hosted-frozen-input-file/v1"] = "hosted-frozen-input-file/v1"
    logical_path: str = Field(min_length=1, max_length=500, pattern=r"^[a-zA-Z0-9._/-]+$")
    sha256: Hash
    size_bytes: int = Field(ge=0, le=16_777_216)

    @field_validator("logical_path")
    @classmethod
    def relative_components(cls, value: str) -> str:
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("frozen input path must have ordinary relative components")
        return value


class HostedCampaignRecipe(HostedContract):
    """Deployment-independent request policy, frozen before the service profile."""

    schema_version: Literal["hosted-campaign-recipe/v1"] = "hosted-campaign-recipe/v1"
    hosted_budget: HostedBudgetPolicy
    requested_model_configuration_hash: Hash
    contract_hash: Hash
    acceptance_hash: Hash
    started_at: datetime


class HostedFrozenBusinessInputs(HostedContract):
    """Immutable configuration, emitted by management before model requests."""

    schema_version: Literal["hosted-frozen-business-inputs/v1"] = "hosted-frozen-business-inputs/v1"
    execution_profile: Literal["p14dq-frozen/v1"] = "p14dq-frozen/v1"
    campaign: ResearchCampaignSpec
    research_budget: ResearchBudgetSpec
    execution_bindings: AutonomousExecutionBindings
    hosted_recipe: HostedCampaignRecipe
    family: ResearchFamilySpec
    template: ResearchFactorTemplateSpec
    manifest: CandidateEnumerationManifest
    initial_ledger_snapshot: ResearchLedgerSnapshot
    initial_events: tuple[ResearchCampaignEvent | CampaignSelectionEvent, ...]
    ledger_id: Identity
    search_policy: ResearchLedgerSearchPolicy
    context_budget: ResearchContextBudgetPolicy
    campaign_policy: AutonomousCampaignPolicy
    agent_run_policy: AutonomousAgentRunPolicy
    selection_finalization_profile: AutonomousSelectionFinalizationProfile
    multiple_testing_policy: MultipleTestingPolicySpec
    selection_policy: SelectionPolicySpec
    selection_plan: CampaignSelectionPlan
    authoring: ExperimentAuthoringSpec
    research_policy: ResearchPolicy
    validation_policy: ValidationPolicy
    cost_policy: CostPolicy
    backtest_policy: BacktestPolicy
    code_provenance: CodeProvenance
    snapshot_directory: str
    qlib_view_directory: str
    initial_ledger_directory: str
    initial_ledger_files: tuple[HostedFrozenInputFile, ...] = Field(min_length=1, max_length=10000)
    frozen_byte_objects: tuple[HostedFrozenInputFile, ...] = Field(min_length=4, max_length=10000)

    @field_validator("snapshot_directory", "qlib_view_directory", "initial_ledger_directory")
    @classmethod
    def relative_directory(cls, value: str) -> str:
        if len(value) > 500 or any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("input directory must be an ordinary relative path")
        return value

    @model_validator(mode="after")
    def inventories_are_frozen(self) -> Self:
        for inventory in (self.initial_ledger_files, self.frozen_byte_objects):
            paths = tuple(item.logical_path for item in inventory)
            if (
                paths != tuple(sorted(set(paths)))
                or sum(item.size_bytes for item in inventory) > 67_108_864
            ):
                raise ValueError("frozen input inventory must be sorted, unique and bounded")
        if (
            self.code_provenance.commit_hash != self.execution_bindings.code_commit_hash
            or self.code_provenance.lockfile_hash != self.execution_bindings.lockfile_hash
            or self.initial_ledger_snapshot.content_hash != self.campaign.ledger_snapshot_hash
            or self.initial_ledger_snapshot.ledger_id != self.ledger_id
            or self.research_budget.content_hash != self.campaign.budget_hash
            or self.hosted_recipe.requested_model_configuration_hash
            != self.agent_run_policy.requested_model_configuration_hash
            or len(self.initial_events) != 2
            or not isinstance(self.initial_events[0], ResearchCampaignEvent)
            or self.initial_events[0].event_type is not CampaignEventType.ACTIVATED
            or not isinstance(self.initial_events[1], CampaignSelectionEvent)
            or self.initial_events[1].event_type is not CampaignSelectionEventType.PLAN_FROZEN
            or self.initial_events[1].selection_plan_hash != self.selection_plan.content_hash
            or any(
                event.campaign_hash != self.campaign.content_hash for event in self.initial_events
            )
        ):
            raise ValueError("business bundle frozen campaign/code/plan identity differs")
        return self


class HostedBusinessLoaderConfiguration(HostedContract):
    """Manager-only paths bound by the read-only service configuration hash."""

    schema_version: Literal["hosted-business-loader-configuration/v1"] = (
        "hosted-business-loader-configuration/v1"
    )
    factory: Literal["p14dq-frozen/v1"] = "p14dq-frozen/v1"
    business_inputs_hash: Hash
    input_root: str = Field(min_length=1, max_length=500)
    provenance_workspace: str = Field(min_length=1, max_length=500)
    business_root: str = Field(min_length=1, max_length=500)

    @field_validator("input_root", "provenance_workspace", "business_root")
    @classmethod
    def absolute_service_path(cls, value: str) -> str:
        if not value.startswith("/") or any(part in (".", "..") for part in value.split("/")):
            raise ValueError("service path must be an explicit absolute path")
        return value


def derive_hosted_campaign_spec(
    bundle: HostedFrozenBusinessInputs, *, deployment_profile_hash: str
) -> HostedCampaignSpec:
    """Derive the unique hosted spec after the management domain verifies D."""
    recipe = bundle.hosted_recipe
    return HostedCampaignSpec(
        campaign=bundle.campaign,
        research_budget=bundle.research_budget,
        hosted_budget=recipe.hosted_budget,
        candidate_manifest_hash=bundle.manifest.content_hash,
        factor_template_hash=bundle.template.content_hash,
        selection_plan_hash=bundle.selection_plan.content_hash,
        selection_finalization_profile_hash=bundle.selection_finalization_profile.content_hash,
        execution_bindings=bundle.execution_bindings,
        search_policy_hash=bundle.search_policy.content_hash,
        context_budget_policy_hash=bundle.context_budget.content_hash,
        campaign_policy_hash=bundle.campaign_policy.content_hash,
        agent_run_policy_hash=bundle.agent_run_policy.content_hash,
        requested_model_configuration_hash=recipe.requested_model_configuration_hash,
        deployment_profile_hash=deployment_profile_hash,
        contract_hash=recipe.contract_hash,
        acceptance_hash=recipe.acceptance_hash,
        started_at=recipe.started_at,
    )
