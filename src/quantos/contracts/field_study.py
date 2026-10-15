"""Fixed two-feature retrospective study inputs; no Agent or runtime dependency."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

# These existing contracts are only containers for deterministic execution inputs.
from quantos.contracts.autonomous import AutonomousExecutionBindings, AutonomousExecutionRequest
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ResearchFamilySpec
from quantos.contracts.cost import BacktestPolicy, CostPolicy
from quantos.contracts.discovery_prediction import PredictionEvaluationProfile, PredictionFileSource
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ExpressionAuthoringSpec,
    ResearchPolicy,
    ResearchSegment,
    ValidationPolicy,
)
from quantos.contracts.snapshot import DataSnapshotManifest

FIELD_STUDY_PROFILE = "frozen-field-study/v1"
FIELD_STUDY_QUESTION = (
    "Compare five-day relative adjusted volume with five-day adjusted price return "
    "in fixed single-feature LGBModel predictions, date coverage and execution cost."
)


def expression_identity(expression: SafeQlibExpressionSpec | ExpressionAuthoringSpec) -> str:
    if not isinstance(expression, SafeQlibExpressionSpec):
        raise ValueError("field-study requires explicit Safe DSL")
    return sha256_bytes(canonical_json_bytes(expression.model_dump(exclude={"expression_id"})))


class FrozenFieldStudyConfiguration(CanonicalContract):
    schema_version: Literal["frozen-field-study-config/v1"] = "frozen-field-study-config/v1"
    execution_profile: Literal["frozen-field-study/v1"] = FIELD_STUDY_PROFILE
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    volume: ExperimentAuthoringSpec
    price: ExperimentAuthoringSpec
    research_policy: ResearchPolicy
    validation_policy: ValidationPolicy
    cost_policy: CostPolicy
    backtest_policy: BacktestPolicy
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    workspace: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    qlib_view_path: str = Field(min_length=1)
    min_defined_fraction: float = Field(default=0.9, ge=0.9, le=0.9)

    @model_validator(mode="after")
    def fixed_design(self) -> Self:
        if self.study_id in {"latest", "current", "auto"}:
            raise ValueError("study identity must be explicit")
        if (
            self.snapshot_hash != "6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
            or self.qlib_view_hash
            != "fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
            or self.validation_policy.content_hash
            != "d5ad58f3b6986c39dbc0dcba370a142812d3760b01ba1752a7933a495caac514"
            or self.cost_policy.content_hash
            != "5b96c6726d7890e0526e2808e0a9771437f796a29cf1e359ff1a5bfd0c6701df"
            or self.backtest_policy.content_hash
            != "3839f857fa791fd58c5d19bcfdd2a050588259258f6bad3ce531f31caf68157b"
        ):
            raise ValueError("fixed study data or shared policies differ")
        for name, authoring in (("V", self.volume), ("P", self.price)):
            expression = authoring.expression
            if not isinstance(expression, SafeQlibExpressionSpec):
                raise ValueError("fixed study requires explicit Safe DSL")
            field = "adjusted_volume" if name == "V" else "adjusted_close"
            window_id = "adjusted_volume_mean_5" if name == "V" else "adjusted_close_return5"
            output = "adjusted_volume_relative5" if name == "V" else window_id
            expected: list[tuple[str, str, tuple[str, ...], str | None, int | None]] = [
                (field, "field", (), field, None),
                (window_id, "rolling_mean" if name == "V" else "return", (field,), None, 5),
            ]
            if name == "V":
                expected.append((output, "divide", (field, window_id), None, None))
            actual = [
                (n.node_id, str(n.operator), n.inputs, n.field_name, n.window)
                for n in expression.nodes
            ]
            if (
                actual != expected
                or expression.schema_version != "safe-qlib-expression/v1"
                or expression.output_node_id != output
                or expression.input_lag_trading_days != 0
                or authoring.evaluation_start != date(2015, 1, 1)
                or authoring.evaluation_end != date(2025, 12, 31)
                or authoring.strategy.universe_index != "000300.SH"
                or authoring.strategy.top_k != 50
                or authoring.strategy.max_weight != 0.03
                or authoring.strategy.input_lag_trading_days != 0
            ):
                raise ValueError("candidate escaped fixed V/P design")
        if self.volume.strategy != self.price.strategy:
            raise ValueError("V/P strategy inputs must match")
        policy = self.research_policy
        if [(s.start, s.end) for s in (policy.train, policy.validation, policy.test)] != [
            (date(2015, 1, 1), date(2019, 12, 31)),
            (date(2020, 1, 1), date(2022, 12, 31)),
            (date(2023, 1, 1), date(2025, 12, 31)),
        ] or (
            policy.purge_trading_days,
            policy.label_horizon_trading_sessions,
            policy.random_seed,
            policy.num_threads,
            policy.num_boost_round,
            policy.early_stopping_rounds,
        ) != (5, 1, 1729, 1, 100, 20):
            raise ValueError("research policy escaped fixed study design")
        return self

    def input_reference(self, candidate: Literal["V", "P"]) -> str:
        """Compatibility binding for the execution port, never an AgentRun assertion."""
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "frozen-field-study-input-reference/v1",
                    "authority": "FIXED_DESIGN_NOT_AGENT_RUN",
                    "configuration_hash": self.content_hash,
                    "candidate": candidate,
                }
            )
        )


class FieldStudyExecutionScope(CanonicalContract):
    """Execution identity container; no Ledger, Agent or sealed campaign authority."""

    schema_version: Literal["frozen-field-study-execution-scope/v1"] = (
        "frozen-field-study-execution-scope/v1"
    )
    campaign_id: str
    configuration_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_hash: str = Field(pattern=SHA256_PATTERN)
    development: ResearchSegment
    validation: ResearchSegment


class FieldStudyBudget(CanonicalContract):
    schema_version: Literal["frozen-field-study-budget/v1"] = "frozen-field-study-budget/v1"
    max_executions: Literal[1] = 1
    max_validation_rounds: Literal[1] = 1
    max_compute_units: int = Field(gt=0)


class FieldStudyTask(CanonicalContract):
    schema_version: Literal["frozen-field-study-task/v1"] = "frozen-field-study-task/v1"
    label: Literal["V", "P"]
    family: ResearchFamilySpec
    template: ResearchFactorTemplateSpec
    manifest: CandidateEnumerationManifest
    budget: FieldStudyBudget
    campaign: FieldStudyExecutionScope
    bindings: AutonomousExecutionBindings
    request: AutonomousExecutionRequest
    compute_units: int = Field(gt=0)


class FieldStudySourceChange(CanonicalContract):
    schema_version: Literal["field-study-source-change/v1"] = "field-study-source-change/v1"
    path: str
    original_hash: str | None = Field(pattern=SHA256_PATTERN)
    successor_hash: str | None = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def changed_file(self) -> Self:
        validate_logical_path(self.path)
        if self.original_hash == self.successor_hash:
            raise ValueError("source change must describe different bytes")
        return self


class FieldStudyBaselineOrigin(CanonicalContract):
    """Only successful baseline stages; never a Workflow or parent qualification."""

    schema_version: Literal["field-study-baseline-origin/v1"] = "field-study-baseline-origin/v1"
    label: Literal["V", "P"]
    stage: Literal["baseline"] = "baseline"
    request: PredictionFileSource
    pit: PredictionFileSource
    pit_checkpoint: PredictionFileSource
    signal_path: str
    signal_hash: str = Field(pattern=SHA256_PATTERN)
    signal_checkpoint: PredictionFileSource
    backtest_path: str
    backtest_hash: str = Field(pattern=SHA256_PATTERN)
    backtest_checkpoint: PredictionFileSource
    workflow_failure: PredictionFileSource
    guard_exit: PredictionFileSource


class FieldStudyRecoveryOrigin(CanonicalContract):
    schema_version: Literal["field-study-recovery-origin/v1"] = "field-study-recovery-origin/v1"
    predecessor_preparation: PredictionFileSource
    reconstructed_workspace: str
    successor_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    source_changes: tuple[FieldStudySourceChange, ...]
    baselines: tuple[FieldStudyBaselineOrigin, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_ordered_origins(self) -> Self:
        paths = tuple(item.path for item in self.source_changes)
        labels = tuple(item.label for item in self.baselines)
        if paths != tuple(sorted(set(paths))) or labels != tuple(sorted(set(labels))):
            raise ValueError("recovery sources must be unique and ordered")
        return self


class FieldStudyOpportunityTransfer(CanonicalContract):
    schema_version: Literal["field-study-opportunity-transfer/v1"] = (
        "field-study-opportunity-transfer/v1"
    )
    label: Literal["V", "P"]
    opportunity_identity: str = Field(pattern=SHA256_PATTERN)
    original_request_hash: str = Field(pattern=SHA256_PATTERN)
    successor_request_hash: str = Field(pattern=SHA256_PATTERN)
    complete_compute_units: Literal[18] = 18
    logical_executions: Literal[1] = 1
    original_consumed_units: None = None


class FieldStudySourceAdoption(CanonicalContract):
    schema_version: Literal["field-study-source-adoption/v1"] = "field-study-source-adoption/v1"
    origin: FieldStudyRecoveryOrigin
    original_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluation_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_capsule_hash: str = Field(pattern=SHA256_PATTERN)
    evaluation_inventory_hash: str = Field(pattern=SHA256_PATTERN)
    successor_preparation_root: str
    successor_execution_root: str
    transfers: tuple[FieldStudyOpportunityTransfer, FieldStudyOpportunityTransfer]
    complete_study_compute_units: Literal[36] = 36
    whole_job_growth_estimate_bytes: Literal[8589934592] = 8589934592
    model_predictions_recomputed: Literal[True] = True
    original_qualification_transferred: Literal[False] = False

    @model_validator(mode="after")
    def same_two_opportunities(self) -> Self:
        if (
            tuple(t.label for t in self.transfers) != ("V", "P")
            or len({t.opportunity_identity for t in self.transfers}) != 2
        ):
            raise ValueError("recovery must retain the two original opportunities")
        return self


class FieldStudyOpportunityState(CanonicalContract):
    schema_version: Literal["field-study-opportunity-state/v1"] = "field-study-opportunity-state/v1"
    opportunity_identity: str = Field(pattern=SHA256_PATTERN)
    original_request_hash: str = Field(pattern=SHA256_PATTERN)
    active_request_hash: str = Field(pattern=SHA256_PATTERN)
    active_configuration_hash: str = Field(pattern=SHA256_PATTERN)
    active_execution_root: str
    source_adoption_record_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    complete_compute_units: Literal[18] = 18
    logical_executions: Literal[1] = 1


class _FieldStudyPreparation(CanonicalContract):
    configuration: FrozenFieldStudyConfiguration
    snapshot: DataSnapshotManifest
    view: QlibViewManifest
    tasks: tuple[FieldStudyTask, FieldStudyTask]
    prediction_profile: PredictionEvaluationProfile
    execution_root: str
    preparation_root: str
    full_calendar: tuple[date, ...]
    effective_segments: dict[str, ResearchSegment]
    last_computable_label_date: date
    source_inventory_hash: str = Field(pattern=SHA256_PATTERN)
    source_capsule_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_pair(self) -> Self:
        if tuple(t.label for t in self.tasks) != ("V", "P"):
            raise ValueError("preparation must contain ordered V/P tasks")
        if (
            self.snapshot.snapshot_hash != self.configuration.snapshot_hash
            or self.view.view_hash != self.configuration.qlib_view_hash
            or self.view.source_snapshot_hash != self.snapshot.snapshot_hash
        ):
            raise ValueError("preparation dataset identity differs")
        return self


class FieldStudyPreparation(_FieldStudyPreparation):
    schema_version: Literal["frozen-field-study-preparation/v1"] = (
        "frozen-field-study-preparation/v1"
    )


class FieldStudyRecoveryPreparation(_FieldStudyPreparation):
    schema_version: Literal["frozen-field-study-preparation/v2"] = (
        "frozen-field-study-preparation/v2"
    )
    source_adoption: FieldStudySourceAdoption


PreparedFieldStudy = FieldStudyPreparation | FieldStudyRecoveryPreparation
