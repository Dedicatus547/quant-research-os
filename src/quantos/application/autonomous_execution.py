"""Production execution adapter for P14d's existing deterministic research services."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as day_time
from pathlib import Path
from time import perf_counter, process_time
from typing import Any, Literal, NoReturn
from uuid import UUID, uuid5

from pydantic import Field, PositiveInt, ValidationError, field_validator

from quantos.application import data_qualified_release as release
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.data_qualified_release import (
    _operator_delays as research_operator_delays,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.data_qualified_release import (
    _schedule_hash as research_schedule_hash,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.data_qualified_release import (
    _Variant as ResearchExecutionVariant,  # pyright: ignore[reportPrivateUsage]
)
from quantos.application.enumeration import (
    CandidateEnumerationError,
    verify_candidate_enumeration_manifest,
)
from quantos.application.provenance import capture_runtime_fingerprint, verify_code_provenance
from quantos.application.schedules import resolve_weekly_decision_schedules
from quantos.application.specs import resolve_experiment
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    regular_tree_files,
    sha256_file,
)
from quantos.backtest import QlibBacktestService, verify_backtest_artifact
from quantos.contracts.autonomous import (
    AutonomousExecutionBindings,
    AutonomousExecutionFailureEvidence,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    autonomous_execution_identity,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    TrialOutcome,
)
from quantos.contracts.discovery_adoption import (
    DiscoveryAdoptedVariant,
    DiscoveryEvaluationSourceAdoption,
)
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.model_data_split import QlibModelDataSplitAudit
from quantos.contracts.native_adoption import (
    NativeArtifactAdoptionReceipt,
    verify_adoption_bindings,
)
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import (
    ExperimentAuthoringSpec,
    ResearchPolicy,
    ResolvedExperimentSpec,
    ValidationPolicy,
)
from quantos.contracts.research_execution import PITCrossSectionEvidenceCollection
from quantos.contracts.research_result import P14dqNativeLabelExportAudit, ResearchResultManifest
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.temporal import DecisionSchedule
from quantos.contracts.validation import GateSeverity, ValidationReport
from quantos.data import QlibViewBuildError, SnapshotBuildError, verify_qlib_view, verify_snapshot
from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    QlibResearchError,
    QlibWorkflowResearchService,
    verify_compact_pit_evidence,
    verify_p14dq_native_label_audit,
    verify_research_result,
    verify_signal_artifact,
)
from quantos.research.qlib.model_split import verify_model_data_split
from quantos.research.qlib.result import research_result_verification_scope
from quantos.validation import (
    CostStressLocator,
    ParameterStabilityLocator,
    SubperiodLocator,
    ValidationRunLocators,
    ValidationService,
    verify_validation_report,
)

_EXECUTION_NAMESPACE = UUID("1bf3c8b5-a113-4ea9-bc65-1f2d8f8a51ac")
_PIT_POLICY_HASH = sha256_bytes(
    canonical_json_bytes(
        {
            "policy_id": "snapshot-bound-compact-cross-section-pit/v1",
            "source_vintage_claim": False,
            "temporal_source": "canonical-snapshot/v1",
        }
    )
)
_QLIB_WORKFLOW_POLICY = {
    "policy_id": "quantos-native-qlib-workflow/v1",
    "model": "LGBModel",
    "dataset": "DatasetH/DataHandlerLP/QlibDataLoader",
    "records": ("SignalRecord", "SigAnaRecord"),
    "universe": "verified-historical-index-membership/v1",
    "universe_membership_decision_time": "16:10:00+08:00",
    "feature_name": "candidate-expression",
    "label_name": "LABEL0",
    "learning_rate": 0.05,
    "max_depth": 3,
    "num_leaves": 7,
    "deterministic": True,
    "force_col_wise": True,
    "model_data_split": "calendar-session-purge/v1",
}

# Frozen workload units for deterministic compute authority. These are policy units, not
# observed wall-clock seconds: the same request and frozen policy always produce the same charge.
_COMPUTE_BASELINE_EXECUTION = 1
_COMPUTE_COST_STRESS_VARIANT = 1
_COMPUTE_PARAMETER_VARIANT = 1
_COMPUTE_SUBPERIOD_VARIANT = 1
_COMPUTE_REPRODUCTION_BACKTEST = 1
_COMPUTE_VALIDATION_REPORT = 1
_COMPUTE_ACCOUNTING_POLICY = {
    "policy_id": "autonomous-deterministic-compute-accounting/v1",
    "baseline_execution": _COMPUTE_BASELINE_EXECUTION,
    "cost_stress_variant": _COMPUTE_COST_STRESS_VARIANT,
    "parameter_variant": _COMPUTE_PARAMETER_VARIANT,
    "subperiod_variant": _COMPUTE_SUBPERIOD_VARIANT,
    "reproduction_backtest": _COMPUTE_REPRODUCTION_BACKTEST,
    "validation_report": _COMPUTE_VALIDATION_REPORT,
}


def _discovery_failure_diagnostic(stage: str, error: BaseException) -> dict[str, str | None]:
    """Classify known failures without persisting exception text or untrusted attributes.

    These labels explain an exception that is still raised; they neither evaluate a
    candidate nor change checkpoint reuse. Unknown errors remain unclassified.
    """
    reason: str | None = None
    detail = "UNCLASSIFIED"
    if isinstance(error, QlibResearchError):
        reason = next((item.value for item in ReasonCode if error.reason_code is item), None)
        if stage.endswith("-signal") and error.reason_code is ReasonCode.SOURCE_INCOMPLETE:
            # Only these source-owned message shapes select fixed labels. Never copy
            # their instrument suffix, arbitrary exception text, or chained errors.
            message = error.args[0] if len(error.args) == 1 else None
            if isinstance(message, str):
                if message == "PIT member is absent from the Qlib view mapping":
                    detail = "SIGNAL_PIT_MEMBER_UNMAPPED"
                elif message.startswith("finite signal lacks tradability evidence for "):
                    detail = "SIGNAL_FINITE_WITHOUT_TRADABILITY"
    return {"failure_reason_code": reason, "failure_detail_code": detail}


def autonomous_compute_accounting_policy_hash() -> str:
    """Return the frozen deterministic compute-accounting policy hash."""

    return sha256_bytes(canonical_json_bytes(_COMPUTE_ACCOUNTING_POLICY))


def quote_autonomous_workload(
    authoring: ExperimentAuthoringSpec, validation_policy: ValidationPolicy
) -> int:
    """Quote frozen policy units from the workload shape; no scientific input is read."""
    baseline_window = release.parameter_window(authoring)
    parameters = sum(
        1
        for window in validation_policy.parameter_windows
        for top_k in validation_policy.parameter_top_k
        if (window, top_k) != (baseline_window, authoring.strategy.top_k)
    )
    costs = sum(1 for value in validation_policy.cost_stress_multipliers if value != 1.0)
    return (
        _COMPUTE_BASELINE_EXECUTION
        + _COMPUTE_COST_STRESS_VARIANT * costs
        + _COMPUTE_PARAMETER_VARIANT * parameters
        + _COMPUTE_SUBPERIOD_VARIANT * len(validation_policy.subperiods)
        + _COMPUTE_REPRODUCTION_BACKTEST
        + _COMPUTE_VALIDATION_REPORT
    )


@dataclass(frozen=True, init=False)
class VerifiedExecutionInputs:
    """Internal same-operation proof produced solely by the existing full verifiers."""

    snapshot_path: Path
    view_path: Path
    snapshot: DataSnapshotManifest
    view: QlibViewManifest

    def __init__(self, snapshot_path: Path, view_path: Path) -> None:
        object.__setattr__(self, "snapshot_path", snapshot_path.resolve())
        object.__setattr__(self, "view_path", view_path.resolve())
        object.__setattr__(self, "snapshot", verify_snapshot(snapshot_path))
        object.__setattr__(self, "view", verify_qlib_view(view_path))


def build_autonomous_execution_bindings(
    *,
    snapshot: DataSnapshotManifest,
    qlib_view: QlibViewManifest,
    research_policy: ResearchPolicy,
    validation_policy: ValidationPolicy,
    authoring: ExperimentAuthoringSpec,
    cost_policy: release.CostPolicy,
    backtest_policy: release.BacktestPolicy,
    code_commit_hash: str,
    lockfile_hash: str,
) -> AutonomousExecutionBindings:
    """Bind one exact dataset and all policy/provenance inputs used by the adapter."""

    execution_policy_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "qlib_workflow": _QLIB_WORKFLOW_POLICY,
                "authoring_hash": authoring.content_hash,
                "research_policy_hash": research_policy.content_hash,
                "validation_policy_hash": validation_policy.content_hash,
                "cost_policy_hash": cost_policy.content_hash,
                "backtest_policy_hash": backtest_policy.content_hash,
                "compute_accounting": _COMPUTE_ACCOUNTING_POLICY,
            }
        )
    )
    return AutonomousExecutionBindings(
        dataset_id=snapshot.dataset_id,
        authoring_hash=authoring.content_hash,
        execution_policy_hash=execution_policy_hash,
        pit_policy_hash=_PIT_POLICY_HASH,
        research_policy_hash=research_policy.content_hash,
        validation_policy_hash=validation_policy.content_hash,
        cost_policy_hash=cost_policy.content_hash,
        backtest_policy_hash=backtest_policy.content_hash,
        code_commit_hash=code_commit_hash,
        lockfile_hash=lockfile_hash,
        qlib_version=qlib_view.qlib_version,
    )


class AutonomousExecutionReceipt(CanonicalContract):
    """Immutable execution-to-authority link published before campaign accounting."""

    schema_version: Literal["autonomous-execution-receipt/v1"] = "autonomous-execution-receipt/v1"
    request: AutonomousExecutionRequest
    outcome: AutonomousExecutionResult


class AutonomousExecutionTrialIndex(CanonicalContract):
    """Immutable reservation that prevents a trial identity from being rebound."""

    schema_version: Literal["autonomous-execution-trial-index/v1"] = (
        "autonomous-execution-trial-index/v1"
    )
    campaign_hash: str
    trial_ordinal: int
    execution_identity: str
    request_hash: str


class DiscoveryExecutionStageCheckpoint(CanonicalContract):
    """Completed deterministic stage, with exact inputs and immutable output identities."""

    schema_version: Literal["discovery-execution-stage-checkpoint/v1"] = (
        "discovery-execution-stage-checkpoint/v1"
    )
    request_hash: str = Field(pattern=SHA256_PATTERN)
    stage: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    inputs_hash: str = Field(pattern=SHA256_PATTERN)
    reservation_hash: str = Field(pattern=SHA256_PATTERN)
    attempt_ordinal: PositiveInt
    outputs: dict[str, str]

    @field_validator("outputs")
    @classmethod
    def output_identities_are_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        if not values or any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in values.values()
        ):
            raise ValueError("checkpoint output identities must be SHA256 hashes")
        return values


def require_durable_execution_root(path: Path) -> None:
    """Discovery authority must not reside in temporary or automatically cleaned storage."""
    resolved = path.resolve()
    if any(
        root == resolved or root in resolved.parents for root in (Path("/tmp"), Path("/var/tmp"))
    ):
        raise ValueError("discovery execution authority requires durable storage")
    if any(part in {".cache", "__pycache__"} for part in resolved.parts):
        raise ValueError("discovery execution authority cannot use a cache directory")


class QuantosResearchExecutionAdapter:
    """Carry frozen P14b candidates through PIT, Qlib, Validation and verified artifacts.

    It composes existing application and Qlib services. It does not implement expression values,
    IC, backtest accounting, or Validation verdicts.
    """

    def __init__(
        self,
        *,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        template: ResearchFactorTemplateSpec,
        manifest: CandidateEnumerationManifest,
        snapshot_path: Path,
        qlib_view_path: Path,
        base_authoring: ExperimentAuthoringSpec,
        research_policy: ResearchPolicy,
        validation_policy: ValidationPolicy,
        cost_policy: release.CostPolicy,
        backtest_policy: release.BacktestPolicy,
        bindings: AutonomousExecutionBindings,
        output_root: Path,
        workspace: Path,
        canonical_validation: bool = True,
        p14dq_v2_profile: bool = False,
        discovery_stage_recovery: bool = False,
        discovery_profile: Literal["singleton-full-chain/v1"] | None = None,
        _verified_inputs: VerifiedExecutionInputs | None = None,
        discovery_source_adoption: DiscoveryEvaluationSourceAdoption | None = None,
    ) -> None:
        try:
            verify_candidate_enumeration_manifest(family, template, manifest)
            if _verified_inputs is None:
                snapshot = verify_snapshot(snapshot_path)
                view = verify_qlib_view(qlib_view_path)
            else:
                if type(_verified_inputs) is not VerifiedExecutionInputs:
                    raise ValueError(
                        "internal verified inputs must originate in the full verifiers"
                    )
                if not discovery_stage_recovery or (
                    _verified_inputs.snapshot_path != snapshot_path.resolve()
                    or _verified_inputs.view_path != qlib_view_path.resolve()
                ):
                    raise ValueError("internal verified inputs escaped their operation paths")
                snapshot, view = _verified_inputs.snapshot, _verified_inputs.view
        except (CandidateEnumerationError, SnapshotBuildError, QlibViewBuildError) as error:
            raise ValueError("autonomous execution input artifact failed verification") from error
        if (
            campaign.family_hash != family.content_hash
            or campaign.budget_hash != budget.content_hash
            or manifest.family_hash != family.content_hash
            or manifest.factor_template_hash != template.content_hash
            or snapshot.snapshot_hash != campaign.snapshot_hash
            or view.view_hash != campaign.qlib_view_hash
            or view.source_snapshot_hash != snapshot.snapshot_hash
            or snapshot.dataset_id != bindings.dataset_id
            or view.qlib_version != bindings.qlib_version
            or bindings.pit_policy_hash != _PIT_POLICY_HASH
            or bindings.authoring_hash != base_authoring.content_hash
            or bindings.research_policy_hash != research_policy.content_hash
            or bindings.validation_policy_hash != validation_policy.content_hash
            or bindings.cost_policy_hash != cost_policy.content_hash
            or bindings.backtest_policy_hash != backtest_policy.content_hash
            or bindings.execution_policy_hash
            != build_autonomous_execution_bindings(
                snapshot=snapshot,
                qlib_view=view,
                research_policy=research_policy,
                validation_policy=validation_policy,
                authoring=base_authoring,
                cost_policy=cost_policy,
                backtest_policy=backtest_policy,
                code_commit_hash=bindings.code_commit_hash,
                lockfile_hash=bindings.lockfile_hash,
            ).execution_policy_hash
        ):
            raise ValueError("autonomous execution bindings disagree with frozen inputs")
        if p14dq_v2_profile and (
            campaign.campaign_id != "p14-dq-live-data-campaign-v1"
            or snapshot.snapshot_hash
            != "6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
            or view.view_hash != "fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
            or research_policy.policy_id != "p14dq_daily_research_v2"
            or validation_policy.policy_id != "p14dq_research_candidate_v2"
        ):
            raise ValueError("P14-DQ v2 execution profile escaped its frozen campaign")
        self.campaign = campaign
        self.family = family
        self.budget = budget
        self.template = template
        self.manifest = manifest
        self.snapshot = snapshot
        self.view = view
        self.snapshot_path = snapshot_path
        self.qlib_view_path = qlib_view_path
        self.base_authoring = base_authoring
        self.research_policy = research_policy
        self.validation_policy = validation_policy
        self.cost_policy = cost_policy
        self.backtest_policy = backtest_policy
        self.bindings = bindings
        self.output_root = output_root
        self.workspace = workspace
        self.canonical_validation = canonical_validation
        self.p14dq_v2_profile = p14dq_v2_profile
        self.discovery_stage_recovery = discovery_stage_recovery
        self.discovery_profile = discovery_profile
        self.discovery_source_adoption = discovery_source_adoption
        if discovery_source_adoption is not None and (
            not discovery_stage_recovery
            or discovery_source_adoption.evaluation_source_commit != bindings.code_commit_hash
            or discovery_source_adoption.lockfile_hash != bindings.lockfile_hash
            or discovery_source_adoption.evaluation_execution_policy_hash
            != bindings.execution_policy_hash
        ):
            raise ValueError("origin adoption is outside its explicit successor execution")
        if discovery_profile is not None and not discovery_stage_recovery:
            raise ValueError("discovery full-chain profile requires explicit stage recovery")
        self._discovery_runtime_hash: str | None = None
        self._discovery_verified_pit_hashes: set[str] = set()
        if discovery_stage_recovery:
            require_durable_execution_root(output_root)
        self._candidate_by_hash = {item.content_hash: item for item in manifest.candidates}

    @property
    def research_results_root(self) -> Path:
        return self.output_root / "research-results"

    def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
        with research_result_verification_scope():
            return self._execute(request)

    def _execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
        if self.discovery_stage_recovery:
            self._discovery_runtime_hash = None
            self._discovery_verified_pit_hashes.clear()
        self._verify_request(request)
        self._reserve_trial_identity(request)
        with exclusive_directory_lock(
            self.output_root / "execution-locks" / request.execution_identity
        ):
            prior = self._read_receipt(request.execution_identity)
            if prior is not None:
                if prior.request != request:
                    self._integrity("execution identity is already bound to different inputs")
                self._verify_receipt(prior)
                return self._outcome_with_receipt(prior)

            compute_charge = self._deterministic_compute_charge(request)
            if self.discovery_stage_recovery:
                atomic_write_bytes(
                    self.output_root / "execution-requests" / f"{request.execution_identity}.json",
                    request.canonical_bytes(),
                )
            try:
                result, report, pit_hash, signal_hash, backtest_hash, audit_hash = (
                    self._execute_pipeline(request)
                )
                outcome = self._outcome_from_validation(
                    request,
                    result,
                    report,
                    pit_hash=pit_hash,
                    signal_hash=signal_hash,
                    backtest_hash=backtest_hash,
                    audit_hash=audit_hash,
                    compute_seconds=compute_charge,
                )
            except AutonomousOrchestrationError:
                raise
            except QlibResearchError as error:
                if error.reason_code in {
                    ReasonCode.ARTIFACT_CORRUPTED,
                    ReasonCode.SNAPSHOT_HASH_MISMATCH,
                    ReasonCode.REPRODUCIBILITY_MISMATCH,
                    ReasonCode.OOS_POLICY_VIOLATION,
                    ReasonCode.MODEL_CONFIGURATION_MISMATCH,
                }:
                    self._integrity(
                        "existing research service reported an authority mismatch", error
                    )
                if error.reason_code in {
                    ReasonCode.LOOK_AHEAD,
                    ReasonCode.UNKNOWN_AVAILABILITY,
                }:
                    failure_kind: Literal["PIT_REJECTED", "EXECUTION_FAILED"] = "PIT_REJECTED"
                elif error.reason_code in {
                    ReasonCode.QLIB_EXECUTION_FAILED,
                    ReasonCode.SOURCE_INCOMPLETE,
                }:
                    failure_kind = "EXECUTION_FAILED"
                else:
                    self._integrity(
                        "existing research service reported an unclassified failure", error
                    )
                outcome = self._failure_outcome(
                    request,
                    error.reason_code,
                    failure_kind=failure_kind,
                    compute_seconds=compute_charge,
                )
            except (SnapshotBuildError, QlibViewBuildError, ValidationError) as error:
                self._integrity("existing research artifact failed authority verification", error)
            if self._native_label_audit_enabled and outcome.research_result_hash is not None:
                audit = self._verify_dq_audit_for_request(request, outcome.research_result_hash)
                if audit.audit_hash not in outcome.evidence_hashes:
                    self._integrity("DQ export audit is absent before receipt publication")
            return self._publish_receipt(request, outcome)

    def execution_compute_charge(self, request: AutonomousExecutionRequest) -> int:
        """Quote the existing frozen workload units without running the pipeline."""
        self._verify_request(request)
        return self._deterministic_compute_charge(request)

    @property
    def _native_label_audit_enabled(self) -> bool:
        return self.p14dq_v2_profile or self.discovery_profile == "singleton-full-chain/v1"

    def verified_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None:
        """Verify an existing receipt; never reserve a trial or run the pipeline.

        An existing receipt may repair its content-addressed receipt index through
        ``_read_receipt``. This is a recoverable publication, not a pure read. Missing
        receipts produce no receipt, trial reservation, or execution.
        """
        with research_result_verification_scope():
            return self._verified_completed_execution(request)

    def _verified_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None:
        self._verify_request(request)
        with exclusive_directory_lock(
            self.output_root / "execution-locks" / request.execution_identity
        ):
            receipt = self._read_receipt(request.execution_identity)
            if receipt is None:
                return None
            if receipt.request != request:
                self._integrity("completed execution is bound to different inputs")
            self._verify_receipt(receipt)
            return self._outcome_with_receipt(receipt)

    def inspect_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None:
        """Bottom-up verify saved execution authority without repairing or publishing files.

        Offline qualification uses this read-only boundary. Online crash recovery keeps
        using ``verified_completed_execution`` and its existing receipt-index repair.
        """
        with research_result_verification_scope():
            return self._inspect_completed_execution(request)

    def _inspect_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None:
        self._verify_request(request)
        path = self._receipt_path(request.execution_identity)
        if not path.exists():
            return None
        with opened_directory(path.parent) as parent:
            encoded = read_regular_bytes_at(parent, path.name, max_bytes=16_777_216)
        receipt = AutonomousExecutionReceipt.model_validate_json(encoded)
        if receipt.canonical_bytes() != encoded or receipt.request != request:
            self._integrity("saved execution receipt differs from exact request")
        with opened_directory(self.output_root / "execution-record-artifacts") as parent:
            indexed = read_regular_bytes_at(
                parent, f"sha256-{receipt.content_hash}.json", max_bytes=16_777_216
            )
        if indexed != encoded:
            self._integrity("saved execution receipt index differs from original bytes")
        self._verify_receipt(receipt)
        return self._outcome_with_receipt(receipt)

    def verify_preselection_dq_trials(self, events: tuple[ResearchCampaignEvent, ...]) -> None:
        """Reverify every DQ trial and its native-label audit before P14c reads it."""

        if not self.p14dq_v2_profile:
            self._integrity("DQ preselection verification requires the frozen DQ profile")
        trials = tuple(
            event.trial
            for event in events
            if event.event_type is CampaignEventType.TRIAL_RECORDED and event.trial is not None
        )
        if len(trials) != len(self.manifest.candidates) or {
            trial.candidate_hash for trial in trials
        } != set(self._candidate_by_hash):
            self._integrity("DQ preselection does not cover the full candidate denominator")
        receipts = tuple(
            receipt
            for path in self._receipt_paths()
            if (receipt := self._read_receipt(path.stem)) is not None
        )
        if len(receipts) != len(trials):
            self._integrity("DQ preselection receipt count differs from campaign trials")
        for trial in trials:
            matches = tuple(
                receipt
                for receipt in receipts
                if receipt.request.candidate.content_hash == trial.candidate_hash
                and receipt.content_hash in trial.evidence_hashes
            )
            if len(matches) != 1:
                self._integrity("DQ trial is not bound to exactly one execution receipt")
            receipt = matches[0]
            if receipt.outcome.outcome is not trial.outcome or not set(
                receipt.outcome.evidence_hashes
            ).issubset(trial.evidence_hashes):
                self._integrity("DQ trial evidence differs from its receipt")
            self._verify_receipt(receipt)

    def _deterministic_compute_charge(self, request: AutonomousExecutionRequest) -> int:
        """Derive the frozen workload charge for one execution-class request.

        The charge is a policy unit derived from the exact candidate authoring, the frozen
        validation workload shape, and the frozen compute-accounting policy. It is never an
        observation of elapsed time.
        """

        return quote_autonomous_workload(self._authoring(request), self.validation_policy)

    def _failure_outcome(
        self,
        request: AutonomousExecutionRequest,
        reason_code: ReasonCode,
        *,
        failure_kind: Literal["PIT_REJECTED", "EXECUTION_FAILED"],
        compute_seconds: int,
    ) -> AutonomousExecutionResult:
        failure = AutonomousExecutionFailureEvidence(
            execution_identity=request.execution_identity,
            request_hash=request.content_hash,
            campaign_hash=request.campaign_hash,
            candidate_hash=request.candidate.content_hash,
            snapshot_hash=request.snapshot_hash,
            reason_code=reason_code,
            failure_kind=failure_kind,
        )
        failure_hash = failure.content_hash
        self._publish_content_addressed(
            self.output_root / "execution-failures", failure_hash, failure.canonical_bytes()
        )
        return AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=(
                TrialOutcome.PIT_REJECT
                if failure_kind == "PIT_REJECTED"
                else TrialOutcome.EXECUTION_FAILED
            ),
            execution_requested=failure_kind != "PIT_REJECTED",
            compute_seconds=compute_seconds,
            evidence_hashes=(failure_hash,),
            failure_reason_code=reason_code,
        )

    def verify_research_result(self, result_hash: str) -> ResearchResultManifest | None:
        path = self.research_results_root / f"sha256-{result_hash}"
        if not path.exists():
            return None
        try:
            manifest = verify_research_result(path)
            receipt = self._receipt_for_result(result_hash)
        except (QlibResearchError, ValueError, OSError) as error:
            self._integrity("ResearchResult failed bottom-up adapter verification", error)
        if (
            receipt is None
            or receipt.outcome.research_result_hash != result_hash
            or manifest.snapshot_hash != self.campaign.snapshot_hash
            or manifest.qlib_view_hash != self.campaign.qlib_view_hash
        ):
            self._integrity("ResearchResult is not linked to a verified campaign execution")
        self._verify_receipt(receipt)
        if manifest.expression_spec_hash != receipt.request.candidate.expression.content_hash:
            self._integrity("ResearchResult candidate expression differs from its receipt")
        return manifest

    def verify_validation_report(self, report_hash: str) -> ValidationReport | None:
        path = self.output_root / "validation" / f"sha256-{report_hash}"
        if not path.exists():
            return None
        try:
            report = verify_validation_report(path)
            receipt = self._receipt_for_validation(report_hash)
        except (ValueError, OSError) as error:
            self._integrity("ValidationReport failed bottom-up adapter verification", error)
        if receipt is None or receipt.outcome.validation_report_hash != report_hash:
            self._integrity("ValidationReport is not linked to a verified campaign execution")
        self._verify_receipt(receipt)
        return report

    def verify_execution_failure(
        self, failure_hash: str
    ) -> AutonomousExecutionFailureEvidence | None:
        path = self.output_root / "execution-failures" / f"sha256-{failure_hash}.json"
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            evidence = AutonomousExecutionFailureEvidence.model_validate_json(encoded)
        except (OSError, ValidationError, ValueError) as error:
            self._integrity("execution failure evidence is invalid", error)
        if encoded != evidence.canonical_bytes() or evidence.content_hash != failure_hash:
            self._integrity("execution failure evidence failed canonical hash verification")
        receipt = self._receipt_for_failure(failure_hash)
        if (
            receipt is None
            or receipt.request.content_hash != evidence.request_hash
            or receipt.request.execution_identity != evidence.execution_identity
            or receipt.request.campaign_hash != evidence.campaign_hash
            or receipt.request.candidate.content_hash != evidence.candidate_hash
            or receipt.request.snapshot_hash != evidence.snapshot_hash
        ):
            self._integrity("execution failure evidence is not linked to its exact request")
        self._verify_receipt(receipt)
        return evidence

    def _verify_request(self, request: AutonomousExecutionRequest) -> None:
        candidate = self._candidate_by_hash.get(request.candidate.content_hash)
        expected_execution_identity = autonomous_execution_identity(
            campaign_hash=request.campaign_hash,
            family_hash=request.family_hash,
            budget_hash=request.budget_hash,
            candidate_manifest_hash=request.candidate_manifest_hash,
            candidate=request.candidate,
            snapshot_hash=request.snapshot_hash,
            qlib_view_hash=request.qlib_view_hash,
            segment=request.segment,
            segment_start=request.segment_start,
            segment_end=request.segment_end,
            trial_ordinal=request.trial_ordinal,
            bindings=self.bindings,
        )
        segment = {
            "DEVELOPMENT": self.campaign.development,
            "VALIDATION": self.campaign.validation,
        }.get(request.segment.value)
        if (
            request.campaign_hash != self.campaign.content_hash
            or request.family_hash != self.family.content_hash
            or request.budget_hash != self.budget.content_hash
            or request.candidate_manifest_hash != self.manifest.content_hash
            or candidate != request.candidate
            or request.candidate_exact_expression_hash != request.candidate.exact_expression_hash
            or request.candidate_structural_expression_hash
            != request.candidate.structural_expression_hash
            or request.execution_identity != expected_execution_identity
            or request.snapshot_hash != self.snapshot.snapshot_hash
            or request.dataset_id != self.snapshot.dataset_id
            or request.qlib_view_hash != self.view.view_hash
            or segment is None
            or request.segment_start != segment.start
            or request.segment_end != segment.end
            or request.execution_policy_hash != self.bindings.execution_policy_hash
            or request.pit_policy_hash != self.bindings.pit_policy_hash
            or request.authoring_hash != self.bindings.authoring_hash
            or request.research_policy_hash != self.research_policy.content_hash
            or request.validation_policy_hash != self.validation_policy.content_hash
            or request.cost_policy_hash != self.cost_policy.content_hash
            or request.backtest_policy_hash != self.backtest_policy.content_hash
            or request.code_commit_hash != self.bindings.code_commit_hash
            or request.lockfile_hash != self.bindings.lockfile_hash
            or request.qlib_version != self.view.qlib_version
        ):
            self._integrity("AutonomousExecutionRequest escaped frozen P14b or dataset bindings")
        if (
            request.segment_start != self.research_policy.test.start
            or request.segment_end != self.research_policy.test.end
        ):
            self._integrity("frozen research test segment differs from campaign validation segment")

    def _authoring(self, request: AutonomousExecutionRequest) -> ExperimentAuthoringSpec:
        payload = self.base_authoring.model_dump(mode="python")
        payload["experiment_id"] = f"p14d-{request.execution_identity[:32]}"
        payload["evaluation_start"] = request.segment_start
        payload["evaluation_end"] = request.segment_end
        payload["expression"] = request.candidate.expression.model_dump(mode="python")
        return ExperimentAuthoringSpec.model_validate(payload)

    def _discovery_stage(
        self,
        request: AutonomousExecutionRequest,
        stage: str,
        inputs: dict[str, object],
        build: Callable[[], dict[str, str]],
        verify: Callable[[dict[str, str]], Any],
        recover: Callable[[], dict[str, str] | None] | None = None,
    ) -> Any:
        """Persist each completed stage before proceeding, and verify originals on reuse.

        An orphan output can be adopted only after a matching durable reservation. The
        adoption record reports unavailable timing and never invents a historical exit.
        All failed and interrupted attempt records remain immutable.
        """
        if self._discovery_runtime_hash is None:
            verify_code_provenance(
                self.workspace,
                expected_commit_hash=request.code_commit_hash,
                expected_lockfile_hash=request.lockfile_hash,
            )
            self._discovery_runtime_hash = capture_runtime_fingerprint().content_hash
        inputs_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "request_hash": request.content_hash,
                    "runtime_fingerprint_hash": self._discovery_runtime_hash,
                    "stage": stage,
                    "inputs": inputs,
                    "recovery_policy": "discovery-stage-original-verification/v1",
                }
            )
        )
        root = self.output_root / "execution-checkpoints" / request.execution_identity / stage
        reservation = {
            "schema_version": "discovery-stage-reservation/v1",
            "request_hash": request.content_hash,
            "stage": stage,
            "inputs_hash": inputs_hash,
            "inputs": inputs,
            "runtime_fingerprint_hash": self._discovery_runtime_hash,
        }
        reservation_bytes = canonical_json_bytes(reservation)
        checkpoint_path = root / f"sha256-{inputs_hash}.json"
        if checkpoint_path.exists():
            with opened_directory(root) as parent:
                encoded = read_regular_bytes_at(parent, checkpoint_path.name, max_bytes=65536)
            checkpoint = DiscoveryExecutionStageCheckpoint.model_validate_json(encoded)
            if encoded != checkpoint.canonical_bytes() or (
                checkpoint.request_hash != request.content_hash
                or checkpoint.stage != stage
                or checkpoint.inputs_hash != inputs_hash
                or checkpoint.reservation_hash != sha256_bytes(reservation_bytes)
            ):
                self._integrity("discovery stage checkpoint differs from its exact inputs")
            origin = root / inputs_hash / "attempts" / f"{checkpoint.attempt_ordinal:08d}"
            with opened_directory(origin) as parent:
                original = read_regular_bytes_at(parent, "reservation.json", max_bytes=16_777_216)
            if original != reservation_bytes:
                self._integrity("discovery stage checkpoint lacks its original reservation")
            return verify(checkpoint.outputs)

        attempts = root / inputs_hash / "attempts"
        reservations = sorted(attempts.glob("*/reservation.json"))
        for path in reservations:
            with opened_directory(path.parent) as parent:
                prior = read_regular_bytes_at(parent, path.name, max_bytes=16_777_216)
            if prior != reservation_bytes:
                self._integrity("discovery stage reservation differs from its exact inputs")
        attempt = attempts / f"{len(reservations) + 1:08d}"
        atomic_write_bytes(attempt / "reservation.json", reservation_bytes)
        wall_start, cpu_start = perf_counter(), process_time()
        adopted = False
        try:
            outputs = recover() if reservations and recover is not None else None
            adopted = outputs is not None
            if outputs is None:
                outputs = build()
            result = verify(outputs)
            checkpoint = DiscoveryExecutionStageCheckpoint(
                request_hash=request.content_hash,
                stage=stage,
                inputs_hash=inputs_hash,
                reservation_hash=sha256_bytes(reservation_bytes),
                attempt_ordinal=len(reservations) + 1,
                outputs=outputs,
            )
            atomic_write_bytes(checkpoint_path, checkpoint.canonical_bytes())
        except BaseException as error:
            atomic_write_bytes(
                attempt / "completion.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-stage-attempt-completion/v2",
                        "inputs_hash": inputs_hash,
                        "status": "FAILED",
                        "failure_code": "STAGE_EXCEPTION",
                        **_discovery_failure_diagnostic(stage, error),
                        "wall_seconds": max(0.0, perf_counter() - wall_start),
                        "cpu_seconds": max(0.0, process_time() - cpu_start),
                    }
                ),
            )
            raise
        atomic_write_bytes(
            attempt / "completion.json",
            canonical_json_bytes(
                {
                    "schema_version": "discovery-stage-attempt-completion/v1",
                    "inputs_hash": inputs_hash,
                    "status": "ADOPTED" if adopted else "SUCCEEDED",
                    "checkpoint_hash": checkpoint.content_hash,
                    "wall_seconds": None if adopted else max(0.0, perf_counter() - wall_start),
                    "cpu_seconds": None if adopted else max(0.0, process_time() - cpu_start),
                    "process_exit": None,
                }
            ),
        )
        return result

    def _verify_adoption_origin(
        self, request: AutonomousExecutionRequest, origin: DiscoveryAdoptedVariant
    ) -> None:
        adoption = self.discovery_source_adoption
        if adoption is None:
            self._integrity("origin adoption lacks its bound declaration")

        def read(path: str, digest: str | None = None) -> bytes:
            target = Path(path)
            if not target.is_absolute():
                self._integrity("origin adoption path must be absolute")
            with opened_directory(target.parent) as parent:
                encoded = read_regular_bytes_at(parent, target.name, max_bytes=16_777_216)
            if digest is not None and sha256_bytes(encoded) != digest:
                self._integrity("origin adoption original bytes differ")
            return encoded

        old = AutonomousExecutionRequest.model_validate_json(
            read(origin.request_path, origin.request_hash)
        )
        scientific = (
            "candidate",
            "snapshot_hash",
            "qlib_view_hash",
            "segment_start",
            "segment_end",
            "pit_policy_hash",
            "authoring_hash",
            "research_policy_hash",
            "validation_policy_hash",
            "cost_policy_hash",
            "backtest_policy_hash",
            "lockfile_hash",
            "qlib_version",
        )
        if old.code_commit_hash != adoption.original_source_commit or any(
            getattr(old, field) != getattr(request, field) for field in scientific
        ):
            self._integrity("origin adoption changed an actual scientific dependency")

        def checkpoint(path: str, digest: str, stage: str, output: str, output_hash: str) -> None:
            encoded = read(path, digest)
            record = json.loads(encoded)
            if canonical_json_bytes(record) != encoded or (
                record.get("request_hash") != old.content_hash
                or record.get("stage") != stage
                or record.get("outputs", {}).get(output) != output_hash
            ):
                self._integrity("origin stage checkpoint differs from its original request")
            root = (
                Path(path).parent
                / record["inputs_hash"]
                / "attempts"
                / f"{record['attempt_ordinal']:08d}"
            )
            reservation_bytes = read(str(root / "reservation.json"), record["reservation_hash"])
            reservation = json.loads(reservation_bytes)
            completion = json.loads(read(str(root / "completion.json")))
            if (
                reservation.get("request_hash") != old.content_hash
                or reservation.get("inputs_hash") != record["inputs_hash"]
                or reservation.get("stage") != stage
                or completion.get("checkpoint_hash") != digest
                or completion.get("status") != "SUCCEEDED"
                or completion.get("inputs_hash") != record["inputs_hash"]
            ):
                self._integrity("origin stage lacks its actual completed reservation")

        checkpoint(
            origin.signal_checkpoint_path,
            origin.signal_checkpoint_hash,
            f"{origin.stage}-signal",
            "signal_hash",
            origin.signal_hash,
        )
        signal = verify_signal_artifact(Path(origin.signal_path))
        if signal.artifact_hash != origin.signal_hash or (
            sha256_bytes(read(origin.pit_path, origin.pit_hash)) != signal.pit_evidence_hash
        ):
            self._integrity("origin PIT/signal source inventory differs")
        if origin.backtest_path is not None:
            if (
                origin.backtest_checkpoint_path is None
                or origin.backtest_checkpoint_hash is None
                or origin.backtest_hash is None
            ):
                self._integrity("origin backtest requires its completed checkpoint")
            checkpoint(
                origin.backtest_checkpoint_path,
                origin.backtest_checkpoint_hash,
                origin.stage,
                "backtest_hash",
                origin.backtest_hash,
            )
            if (
                verify_backtest_artifact(Path(origin.backtest_path)).result_hash
                != origin.backtest_hash
            ):
                self._integrity("origin backtest differs from its original checkpoint")

    def _discovery_variant(
        self,
        request: AutonomousExecutionRequest,
        authoring: ExperimentAuthoringSpec,
        cost_policy: release.CostPolicy,
        schedules: tuple[DecisionSchedule, ...],
        destination: Path,
        evidence_cache: dict[tuple[str, str], PITCrossSectionEvidenceCollection],
        evidence_override: PITCrossSectionEvidenceCollection | None,
    ) -> Any:
        """Resume full existing signal and backtest services without a new execution engine."""
        provisional = resolve_experiment(
            authoring,
            snapshot_hash=request.snapshot_hash,
            qlib_view_hash=request.qlib_view_hash,
            qlib_version=self.view.qlib_version,
            qlib_view_spec_hash=self.view.view_spec_hash,
            pit_audit_evidence_hash="0" * 64,
            research_policy_hash=self.research_policy.content_hash,
            validation_policy_hash=self.validation_policy.content_hash,
            cost_policy_hash=cost_policy.content_hash,
            backtest_policy_hash=self.backtest_policy.content_hash,
            code_commit_hash=request.code_commit_hash,
            lockfile_hash=request.lockfile_hash,
        )
        stage = destination.name
        adoption = self.discovery_source_adoption
        origins = (
            ()
            if adoption is None
            else tuple(
                item
                for item in adoption.variants
                if item.stage == stage and item.subtask_hash == self.output_root.name
            )
        )
        if len(origins) > 1:
            self._integrity("origin adoption has ambiguous stage originals")
        origin = origins[0] if origins else None
        if origin is not None:
            self._verify_adoption_origin(request, origin)
        inputs: dict[str, object] = {
            "provisional_resolved_hash": provisional.content_hash,
            "schedule_hash": research_schedule_hash(schedules),
            "evidence_override_hash": evidence_override.content_hash if evidence_override else None,
        }

        def verify_signal(outputs: dict[str, str]):
            signal_path = destination / "signals" / f"sha256-{outputs['signal_hash']}"
            manifest = verify_signal_artifact(signal_path)
            resolved = ResolvedExperimentSpec.model_validate_json(
                (signal_path / "resolved-experiment.json").read_bytes()
            )
            evidence = PITCrossSectionEvidenceCollection.model_validate_json(
                (signal_path / "pit-evidence.json").read_bytes()
            )
            expected = ResolvedExperimentSpec.model_validate(
                provisional.model_copy(
                    update={"pit_audit_evidence_hash": evidence.content_hash}
                ).model_dump(mode="python")
            )
            if resolved != expected or (
                manifest.artifact_hash != outputs["signal_hash"]
                or tuple(bundle.schedule for bundle in evidence.bundles) != schedules
                or evidence.expression_spec_hash != provisional.expression.content_hash
                or evidence.operator_delays != research_operator_delays(authoring)
                or (evidence_override is not None and evidence != evidence_override)
            ):
                self._integrity("recovered variant signal escaped its exact inputs")
            if evidence.content_hash not in self._discovery_verified_pit_hashes:
                verify_compact_pit_evidence(evidence, self.snapshot_path, self.qlib_view_path)
                self._discovery_verified_pit_hashes.add(evidence.content_hash)
            return resolved, evidence, signal_path, manifest.artifact_hash

        def recover_signal() -> dict[str, str] | None:
            paths = sorted((destination / "signals").glob("sha256-*"))
            if len(paths) > 1:
                self._integrity("variant signal recovery has ambiguous originals")
            return {"signal_hash": paths[0].name.removeprefix("sha256-")} if paths else None

        def build_signal() -> dict[str, str]:
            if origin is not None and adoption is not None:
                evidence = PITCrossSectionEvidenceCollection.model_validate_json(
                    Path(origin.pit_path).read_bytes()
                )
                resolved = ResolvedExperimentSpec.model_validate(
                    provisional.model_copy(
                        update={"pit_audit_evidence_hash": evidence.content_hash}
                    ).model_dump(mode="python")
                )
                built = FactorSignalArtifactBuilder().adopt_verified(
                    resolved,
                    Path(origin.signal_path),
                    destination / "signals",
                    source_adoption_record_hash=adoption.content_hash,
                    source_workspace=Path(adoption.original_workspace),
                    workspace=self.workspace,
                    adoption_root=self.output_root / "native-adoptions",
                    original_execution_status="SUCCEEDED",
                )
                return {
                    "signal_hash": built.manifest.artifact_hash,
                    "source_adoption_record_hash": adoption.content_hash,
                    "original_signal_hash": origin.signal_hash,
                }
            cache_key = (provisional.expression.content_hash, research_schedule_hash(schedules))
            pit_root = self.output_root / "execution-pit-evidence"
            produced_pit: PITCrossSectionEvidenceCollection | None = None

            def build_pit() -> dict[str, str]:
                nonlocal produced_pit
                evidence = evidence_override or evidence_cache.get(cache_key)
                if evidence is None:
                    evidence = release.build_compact_pit_evidence_collection(
                        self.snapshot_path,
                        self.qlib_view_path,
                        expected_snapshot_hash=request.snapshot_hash,
                        expected_view_hash=request.qlib_view_hash,
                        universe_index=provisional.strategy.universe_index,
                        expression=provisional.expression,
                        operator_delays=research_operator_delays(authoring),
                        schedules=schedules,
                    )
                encoded = evidence.canonical_bytes()
                digest = sha256_bytes(encoded)
                atomic_write_bytes(pit_root / f"sha256-{digest}.json", encoded)
                self._discovery_verified_pit_hashes.add(digest)
                produced_pit = evidence
                return {"pit_evidence_hash": digest}

            def verify_pit(outputs: dict[str, str]) -> PITCrossSectionEvidenceCollection:
                digest = outputs["pit_evidence_hash"]
                with opened_directory(pit_root) as parent:
                    encoded = read_regular_bytes_at(
                        parent, f"sha256-{digest}.json", max_bytes=536_870_912
                    )
                evidence = produced_pit or PITCrossSectionEvidenceCollection.model_validate_json(
                    encoded
                )
                if (
                    sha256_bytes(encoded) != digest
                    or (produced_pit is None and evidence.canonical_bytes() != encoded)
                    or (
                        evidence.snapshot_hash != request.snapshot_hash
                        or evidence.qlib_view_hash != request.qlib_view_hash
                        or evidence.expression != provisional.expression
                        or evidence.universe_index != provisional.strategy.universe_index
                        or evidence.operator_delays != research_operator_delays(authoring)
                        or tuple(bundle.schedule for bundle in evidence.bundles) != schedules
                        or (evidence_override is not None and evidence != evidence_override)
                    )
                ):
                    self._integrity("PIT evidence differs from the variant inputs")
                if digest not in self._discovery_verified_pit_hashes:
                    verify_compact_pit_evidence(evidence, self.snapshot_path, self.qlib_view_path)
                    self._discovery_verified_pit_hashes.add(digest)
                return evidence

            evidence = self._discovery_stage(
                request,
                f"{stage}-pit",
                inputs,
                build_pit,
                verify_pit,
            )
            evidence_cache[cache_key] = evidence
            resolved = ResolvedExperimentSpec.model_validate(
                provisional.model_copy(
                    update={"pit_audit_evidence_hash": evidence.content_hash}
                ).model_dump(mode="python")
            )
            built = FactorSignalArtifactBuilder().build(
                resolved,
                evidence,
                self.qlib_view_path,
                destination / "signals",
                workspace=self.workspace,
            )
            return {"signal_hash": built.manifest.artifact_hash}

        resolved, evidence, signal_path, signal_hash = self._discovery_stage(
            request, f"{stage}-signal", inputs, build_signal, verify_signal, recover_signal
        )
        evidence_cache[(resolved.expression.content_hash, research_schedule_hash(schedules))] = (
            evidence
        )

        def verify_backtest(outputs: dict[str, str]):
            path = destination / "backtests" / f"sha256-{outputs['backtest_hash']}"
            manifest = verify_backtest_artifact(path)
            if (
                manifest.result_hash != outputs["backtest_hash"]
                or manifest.resolved_experiment_hash != resolved.content_hash
                or manifest.signal_artifact_hash != signal_hash
                or manifest.cost_policy_hash != cost_policy.content_hash
                or manifest.backtest_policy_hash != self.backtest_policy.content_hash
            ):
                self._integrity("recovered variant backtest escaped its exact inputs")
            return ResearchExecutionVariant(
                resolved, evidence, signal_path, signal_hash, path, manifest.result_hash
            )

        def build_backtest() -> dict[str, str]:
            if origin is not None and adoption is not None and origin.backtest_path is not None:
                built = QlibBacktestService().adopt_verified(
                    resolved,
                    Path(origin.backtest_path),
                    Path(origin.signal_path),
                    signal_path,
                    cost_policy,
                    self.backtest_policy,
                    destination / "backtests",
                    source_adoption_record_hash=adoption.content_hash,
                    source_workspace=Path(adoption.original_workspace),
                    workspace=self.workspace,
                    adoption_root=self.output_root / "native-adoptions",
                    original_execution_status="SUCCEEDED",
                )
                return {
                    "backtest_hash": built.manifest.result_hash,
                    "source_adoption_record_hash": adoption.content_hash,
                    "original_backtest_hash": origin.backtest_hash or "",
                }
            built = QlibBacktestService().run(
                resolved,
                signal_path,
                self.qlib_view_path,
                cost_policy,
                self.backtest_policy,
                destination / "backtests",
                workspace=self.workspace,
            )
            return {"backtest_hash": built.manifest.result_hash}

        def recover_backtest() -> dict[str, str] | None:
            paths = sorted((destination / "backtests").glob("sha256-*"))
            if len(paths) > 1:
                self._integrity("variant backtest recovery has ambiguous originals")
            return {"backtest_hash": paths[0].name.removeprefix("sha256-")} if paths else None

        return self._discovery_stage(
            request,
            stage,
            {**inputs, "resolved_hash": resolved.content_hash, "signal_hash": signal_hash},
            build_backtest,
            verify_backtest,
            recover_backtest,
        )

    def _execute_pipeline(
        self, request: AutonomousExecutionRequest
    ) -> tuple[ResearchResultManifest, ValidationReport, str, str, str, str | None]:
        authoring = self._authoring(request)
        execution_root = self.output_root / "executions" / request.execution_identity
        schedules = resolve_weekly_decision_schedules(
            self.qlib_view_path,
            expected_view_hash=request.qlib_view_hash,
            evaluation_start=request.segment_start,
            evaluation_end=request.segment_end,
        )
        evidence_cache: dict[tuple[str, str], PITCrossSectionEvidenceCollection] = {}

        def build_variant(
            variant_authoring: ExperimentAuthoringSpec,
            cost_policy: release.CostPolicy,
            variant_schedules: tuple[DecisionSchedule, ...],
            *,
            evidence_override: PITCrossSectionEvidenceCollection | None = None,
            destination: Path,
        ):
            if self.discovery_stage_recovery:
                return self._discovery_variant(
                    request,
                    variant_authoring,
                    cost_policy,
                    variant_schedules,
                    destination,
                    evidence_cache,
                    evidence_override,
                )
            return release.build_research_variant(
                authoring=variant_authoring,
                research_policy=self.research_policy,
                validation_policy=self.validation_policy,
                cost_policy=cost_policy,
                backtest_policy=self.backtest_policy,
                snapshot_path=self.snapshot_path,
                snapshot_hash=request.snapshot_hash,
                view_path=self.qlib_view_path,
                view_hash=request.qlib_view_hash,
                view_version=self.view.qlib_version,
                view_spec_hash=self.view.view_spec_hash,
                schedules=variant_schedules,
                output_root=destination,
                workspace=self.workspace,
                commit_hash=request.code_commit_hash,
                lockfile_hash=request.lockfile_hash,
                evidence_cache=evidence_cache,
                evidence_override=evidence_override,
            )

        baseline = build_variant(
            authoring,
            self.cost_policy,
            schedules,
            destination=execution_root / "baseline",
        )
        if baseline.resolved.snapshot_hash != request.snapshot_hash:
            self._integrity("resolved candidate changed the frozen snapshot")

        workflow_build: Any = None

        def build_workflow() -> dict[str, str]:
            nonlocal workflow_build
            workflow = QlibWorkflowResearchService().run(
                baseline.resolved,
                self.research_policy,
                baseline.signal_path,
                self.qlib_view_path,
                execution_root / "qlib-workflow",
                execution_identity=request.execution_identity,
                research_result_root=self.research_results_root,
                workspace=self.workspace,
                dq_audit_root=(
                    self.output_root / "research-result-audits"
                    if self._native_label_audit_enabled
                    else None
                ),
            )
            workflow_build = workflow
            return {
                "research_result_hash": workflow.build.manifest.artifact_hash,
                "model_data_split_hash": workflow.model_data_split_hash,
                **(
                    {"audit_hash": workflow.build.export_audit_hash}
                    if workflow.build.export_audit_hash is not None
                    else {}
                ),
            }

        def verify_workflow(outputs: dict[str, str]):
            result = self._verify_result_for_request(request, outputs["research_result_hash"])
            if result.resolved_experiment_hash != baseline.resolved.content_hash or (
                result.signal_artifact_hash != baseline.signal_hash
            ):
                self._integrity("recovered Workflow differs from the verified baseline")
            native = (
                execution_root
                / "qlib-workflow"
                / "native-records"
                / f"sha256-{request.execution_identity}"
            )
            regular_tree_files(native)
            for source in result.source_files:
                path = native / source.logical_path
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or (
                        path.stat().st_size != source.size_bytes
                        or sha256_file(path) != source.sha256
                    )
                ):
                    self._integrity("recovered Workflow lacks its original native record bytes")
            split_audit = verify_model_data_split(
                native / "model-data-splits.json",
                resolved=baseline.resolved,
                research_policy=self.research_policy,
                calendar=tuple(
                    date.fromisoformat(line.strip())
                    for line in (self.qlib_view_path / "calendars" / "day.txt")
                    .read_text()
                    .splitlines()
                    if line.strip()
                ),
                source_files=result.source_files,
            )
            if outputs.get("model_data_split_hash") != split_audit.content_hash:
                self._integrity("recovered Workflow effective model split differs")
            if self._native_label_audit_enabled:
                audit = self._verify_dq_audit_for_request(request, result.artifact_hash)
                if outputs.get("audit_hash") != audit.audit_hash:
                    self._integrity("recovered Workflow audit differs")
            return result, outputs.get("audit_hash")

        def recover_workflow() -> dict[str, str] | None:
            matches: list[ResearchResultManifest] = []
            for path in sorted(self.research_results_root.glob("sha256-*/manifest.json")):
                candidate = ResearchResultManifest.model_validate_json(path.read_bytes())
                if candidate.qlib_run_id == request.execution_identity[:32]:
                    matches.append(candidate)
            if len(matches) > 1:
                self._integrity("Workflow recovery has ambiguous originals")
            if not matches:
                return None
            outputs = {"research_result_hash": matches[0].artifact_hash}
            native = (
                execution_root
                / "qlib-workflow"
                / "native-records"
                / f"sha256-{request.execution_identity}"
            )
            split_audit = verify_model_data_split(
                native / "model-data-splits.json",
                resolved=baseline.resolved,
                research_policy=self.research_policy,
                calendar=tuple(
                    date.fromisoformat(line.strip())
                    for line in (self.qlib_view_path / "calendars" / "day.txt")
                    .read_text()
                    .splitlines()
                    if line.strip()
                ),
                source_files=matches[0].source_files,
            )
            outputs["model_data_split_hash"] = split_audit.content_hash
            if self._native_label_audit_enabled:
                outputs["audit_hash"] = self._verify_dq_audit_for_request(
                    request, matches[0].artifact_hash
                ).audit_hash
            return outputs

        if self.discovery_stage_recovery:
            result_manifest, audit_hash = self._discovery_stage(
                request,
                "workflow",
                {
                    "resolved_hash": baseline.resolved.content_hash,
                    "signal_hash": baseline.signal_hash,
                    "research_policy_hash": self.research_policy.content_hash,
                },
                build_workflow,
                verify_workflow,
                recover_workflow,
            )
        else:
            workflow_outputs = build_workflow()
            result_manifest = verify_research_result(workflow_build.build.path)
            audit_hash = workflow_outputs.get("audit_hash")
        research_result_path = (
            self.research_results_root / f"sha256-{result_manifest.artifact_hash}"
            if self.discovery_stage_recovery
            else workflow_build.build.path
        )
        if (
            (
                workflow_build is not None
                and result_manifest.artifact_hash != workflow_build.build.manifest.artifact_hash
            )
            or result_manifest.expression_spec_hash != request.candidate.expression.content_hash
            or result_manifest.snapshot_hash != request.snapshot_hash
            or result_manifest.qlib_view_hash != request.qlib_view_hash
        ):
            self._integrity("Qlib ResearchResult lost a frozen candidate or dataset binding")

        cost_variants: dict[float, Any] = {1.0: baseline}
        for multiplier in self.validation_policy.cost_stress_multipliers:
            if multiplier != 1.0:
                cost_variants[multiplier] = build_variant(
                    authoring,
                    release.scale_cost_policy(self.cost_policy, multiplier),
                    schedules,
                    destination=execution_root / f"cost-{multiplier:.1f}x",
                )

        parameter_variants: dict[tuple[int, int], Any] = {}
        baseline_window = release.parameter_window(authoring)
        for window in self.validation_policy.parameter_windows:
            for top_k in self.validation_policy.parameter_top_k:
                key = (window, top_k)
                variant_authoring = (
                    authoring
                    if key == (baseline_window, authoring.strategy.top_k)
                    else release.variant_authoring(authoring, window=window, top_k=top_k)
                )
                parameter_variants[key] = (
                    baseline
                    if variant_authoring == authoring
                    else build_variant(
                        variant_authoring,
                        self.cost_policy,
                        schedules,
                        destination=execution_root / f"parameter-{window}-{top_k}",
                    )
                )

        subperiod_variants: dict[str, Any] = {}
        for period in self.validation_policy.subperiods:
            if self.p14dq_v2_profile or self.discovery_profile == "singleton-full-chain/v1":
                period_schedules = release.schedules_within_subperiod(
                    resolve_weekly_decision_schedules(
                        self.qlib_view_path,
                        expected_view_hash=request.qlib_view_hash,
                        evaluation_start=period.start,
                        evaluation_end=period.end,
                    ),
                    start=period.start,
                    end=period.end,
                )
                required = {
                    "2015-2017": 152,
                    "2018-2020": 153,
                    "2021-2023": 151,
                    "2024-2025": 103,
                }
                if self.p14dq_v2_profile and len(period_schedules) != required.get(
                    period.period_id
                ):
                    self._integrity("P14-DQ subperiod schedule differs from the verified view")
                period_evidence = None
            else:
                period_schedules = release.schedules_within_subperiod(
                    schedules, start=period.start, end=period.end
                )
                period_evidence = release.subset_compact_pit_evidence(
                    baseline.evidence, period_schedules
                )
            subperiod_authoring = release.variant_authoring(
                authoring, evaluation_start=period.start, evaluation_end=period.end
            )
            subperiod_variants[period.period_id] = build_variant(
                subperiod_authoring,
                self.cost_policy,
                period_schedules,
                evidence_override=period_evidence,
                destination=execution_root / f"subperiod-{period.period_id}",
            )

        reproduction_build: Any = None

        def build_reproduction() -> dict[str, str]:
            nonlocal reproduction_build
            reproduction = QlibBacktestService().run(
                baseline.resolved,
                baseline.signal_path,
                self.qlib_view_path,
                self.cost_policy,
                self.backtest_policy,
                execution_root / "reproduction",
                workspace=self.workspace,
            )
            reproduction_build = reproduction
            return {"backtest_hash": reproduction.manifest.result_hash}

        def verify_reproduction(outputs: dict[str, str]) -> Path:
            path = execution_root / "reproduction" / f"sha256-{outputs['backtest_hash']}"
            manifest = verify_backtest_artifact(path)
            if manifest.resolved_experiment_hash != baseline.resolved.content_hash or (
                manifest.signal_artifact_hash != baseline.signal_hash
                or manifest.cost_policy_hash != self.cost_policy.content_hash
                or manifest.backtest_policy_hash != self.backtest_policy.content_hash
            ):
                self._integrity("reproduction backtest differs from its exact inputs")
            return path

        def recover_reproduction() -> dict[str, str] | None:
            paths = sorted((execution_root / "reproduction").glob("sha256-*"))
            if len(paths) > 1:
                self._integrity("reproduction recovery has ambiguous originals")
            return {"backtest_hash": paths[0].name.removeprefix("sha256-")} if paths else None

        if self.discovery_stage_recovery:
            reproduction_path = self._discovery_stage(
                request,
                "reproduction",
                {
                    "resolved_hash": baseline.resolved.content_hash,
                    "signal_hash": baseline.signal_hash,
                    "cost_policy_hash": self.cost_policy.content_hash,
                    "backtest_policy_hash": self.backtest_policy.content_hash,
                },
                build_reproduction,
                verify_reproduction,
                recover_reproduction,
            )
        else:
            build_reproduction()
            reproduction_path = reproduction_build.path
        locators = ValidationRunLocators(
            snapshot_path=self.snapshot_path,
            qlib_view_path=self.qlib_view_path,
            signal_path=baseline.signal_path,
            research_result_path=research_result_path,
            baseline_backtest_path=baseline.backtest_path,
            reproduction_backtest_path=reproduction_path,
            cost_stress=tuple(
                CostStressLocator(
                    multiplier=multiplier,
                    signal_path=cost_variants[multiplier].signal_path,
                    backtest_path=cost_variants[multiplier].backtest_path,
                )
                for multiplier in self.validation_policy.cost_stress_multipliers
            ),
            parameter_stability=tuple(
                ParameterStabilityLocator(
                    window=window,
                    top_k=top_k,
                    signal_path=parameter_variants[(window, top_k)].signal_path,
                    backtest_path=parameter_variants[(window, top_k)].backtest_path,
                )
                for window in self.validation_policy.parameter_windows
                for top_k in self.validation_policy.parameter_top_k
            ),
            subperiods=tuple(
                SubperiodLocator(
                    period_id=period.period_id,
                    start=period.start,
                    end=period.end,
                    signal_path=subperiod_variants[period.period_id].signal_path,
                    backtest_path=subperiod_variants[period.period_id].backtest_path,
                )
                for period in self.validation_policy.subperiods
            ),
        )
        event_time = datetime.combine(request.segment_end, day_time.min, tzinfo=UTC)
        validation_build: Any = None

        def build_validation() -> dict[str, str]:
            nonlocal validation_build
            built = ValidationService().run(
                authoring,
                self.validation_policy,
                self.research_policy,
                locators,
                self.output_root / "validation",
                self.output_root / "validation-events" / request.execution_identity,
                workspace=self.workspace,
                canonical=self.canonical_validation,
                now=event_time,
                event_id=uuid5(_EXECUTION_NAMESPACE, request.execution_identity),
            )
            validation_build = built
            return {"validation_report_hash": built.report.report_hash}

        def verify_validation(outputs: dict[str, str]):
            report = self._load_validation_report(outputs["validation_report_hash"])
            if (
                report.resolved_experiment_hash != baseline.resolved.content_hash
                or report.authoring_spec_hash != authoring.content_hash
                or report.signal_artifact_hash != baseline.signal_hash
                or report.backtest_result_hash != baseline.backtest_hash
                or report.research_policy_hash != self.research_policy.content_hash
                or report.validation_policy_hash != self.validation_policy.content_hash
                or report.canonical != self.canonical_validation
                or report.runtime_fingerprint_hash != self._discovery_runtime_hash
            ):
                self._integrity("recovered ValidationReport escaped its exact inputs")
            return report

        def recover_validation() -> dict[str, str] | None:
            matches: list[ValidationReport] = []
            for path in sorted((self.output_root / "validation").glob("sha256-*/report.json")):
                candidate = ValidationReport.model_validate_json(path.read_bytes())
                if candidate.authoring_spec_hash == authoring.content_hash:
                    matches.append(candidate)
            if len(matches) > 1:
                self._integrity("validation recovery has ambiguous originals")
            return {"validation_report_hash": matches[0].report_hash} if matches else None

        if self.discovery_stage_recovery:
            report = self._discovery_stage(
                request,
                "validation",
                {
                    "authoring_hash": authoring.content_hash,
                    "resolved_hash": baseline.resolved.content_hash,
                    "research_result_hash": result_manifest.artifact_hash,
                    "baseline_backtest_hash": baseline.backtest_hash,
                    "reproduction_backtest_hash": reproduction_path.name.removeprefix("sha256-"),
                    "cost_variant_hashes": {
                        str(k): v.backtest_hash for k, v in cost_variants.items()
                    },
                    "parameter_variant_hashes": {
                        f"{k[0]}-{k[1]}": v.backtest_hash for k, v in parameter_variants.items()
                    },
                    "subperiod_variant_hashes": {
                        k: v.backtest_hash for k, v in subperiod_variants.items()
                    },
                    "canonical": self.canonical_validation,
                },
                build_validation,
                verify_validation,
                recover_validation,
            )
        else:
            build_validation()
            report = verify_validation_report(validation_build.path)
        if (
            (
                validation_build is not None
                and report.report_hash != validation_build.report.report_hash
            )
            or report.resolved_experiment_hash != baseline.resolved.content_hash
            or report.snapshot_hash != request.snapshot_hash
            or report.qlib_view_hash != request.qlib_view_hash
        ):
            self._integrity("ValidationReport does not bind the executed candidate")
        return (
            result_manifest,
            report,
            baseline.evidence.content_hash,
            baseline.signal_hash,
            baseline.backtest_hash,
            audit_hash,
        )

    def _outcome_from_validation(
        self,
        request: AutonomousExecutionRequest,
        result: ResearchResultManifest,
        report: ValidationReport,
        *,
        pit_hash: str,
        signal_hash: str,
        backtest_hash: str,
        audit_hash: str | None,
        compute_seconds: int,
    ) -> AutonomousExecutionResult:
        if report.run_status is RunStatus.FAILED:
            outcome = TrialOutcome.EXECUTION_FAILED
        elif report.verdict is ValidationVerdict.PASS:
            outcome = TrialOutcome.PASS
        elif any(
            gate.severity is GateSeverity.HARD and gate.verdict is ValidationVerdict.REJECT
            for gate in report.gates
        ):
            outcome = TrialOutcome.HARD_REJECT
        else:
            outcome = TrialOutcome.SOFT_REJECT
        failure_reason = next(
            (gate.reason_code for gate in report.gates if gate.reason_code is not None), None
        )
        hashes = tuple(
            sorted(
                {
                    result.artifact_hash,
                    report.report_hash,
                    pit_hash,
                    signal_hash,
                    backtest_hash,
                    self._verify_model_split_for_request(request, result).content_hash,
                    *self._native_adoption_hashes(request),
                    *((audit_hash,) if audit_hash is not None else ()),
                }
            )
        )
        return AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=outcome,
            execution_requested=True,
            compute_seconds=compute_seconds,
            evidence_hashes=hashes,
            research_result_hash=result.artifact_hash,
            validation_report_hash=report.report_hash,
            failure_reason_code=failure_reason,
        )

    def _publish_receipt(
        self, request: AutonomousExecutionRequest, outcome: AutonomousExecutionResult
    ) -> AutonomousExecutionResult:
        receipt = AutonomousExecutionReceipt(request=request, outcome=outcome)
        receipt_path = self._receipt_path(request.execution_identity)
        with exclusive_directory_lock(receipt_path.parent):
            existing = self._read_receipt(request.execution_identity)
            if existing is not None:
                if existing.request != request:
                    self._integrity("execution identity conflicts with a published receipt")
                self._verify_receipt(existing)
                return self._outcome_with_receipt(existing)
            try:
                atomic_write_bytes(receipt_path, receipt.canonical_bytes())
                self._publish_content_addressed(
                    self.output_root / "execution-record-artifacts",
                    receipt.content_hash,
                    receipt.canonical_bytes(),
                )
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                self._integrity("execution receipt publication conflicts", error)
        return self._outcome_with_receipt(receipt)

    @staticmethod
    def _outcome_with_receipt(
        receipt: AutonomousExecutionReceipt,
    ) -> AutonomousExecutionResult:
        receipt_hash = receipt.content_hash
        return AutonomousExecutionResult.model_validate(
            receipt.outcome.model_copy(
                update={
                    "execution_artifact_hash": receipt_hash,
                    "evidence_hashes": tuple(
                        sorted({*receipt.outcome.evidence_hashes, receipt_hash})
                    ),
                }
            ).model_dump(mode="python")
        )

    def _native_adoption_hashes(self, request: AutonomousExecutionRequest) -> tuple[str, ...]:
        adoption = self.discovery_source_adoption
        if adoption is None:
            return ()
        hashes: list[str] = []
        receipts: list[NativeArtifactAdoptionReceipt] = []
        for path in sorted((self.output_root / "native-adoptions").glob("sha256-*.json")):
            with opened_directory(path.parent) as parent:
                encoded = read_regular_bytes_at(parent, path.name, max_bytes=1 << 20)
            receipt = NativeArtifactAdoptionReceipt.model_validate_json(encoded)
            if (
                encoded != receipt.canonical_bytes()
                or path.name != f"sha256-{receipt.content_hash}.json"
                or (
                    receipt.source_adoption_record_hash != adoption.content_hash
                    or receipt.scientific_origin_commit != adoption.original_source_commit
                    or receipt.adoption_commit != request.code_commit_hash
                    or receipt.lockfile_hash != request.lockfile_hash
                )
            ):
                self._integrity("native origin receipt differs from its successor authority")
            kind = receipt.artifact_kind
            origins = tuple(
                item
                for item in adoption.variants
                if item.subtask_hash == self.output_root.name
                and (item.signal_hash if kind == "FACTOR_SIGNAL" else item.backtest_hash)
                == receipt.original_artifact_hash
            )
            if len(origins) != 1:
                self._integrity("native origin receipt has no unique retained stage")
            origin = origins[0]
            self._verify_adoption_origin(request, origin)
            old_path = Path(
                origin.signal_path if kind == "FACTOR_SIGNAL" else origin.backtest_path or ""
            )
            new_path = (
                self.output_root
                / "executions"
                / request.execution_identity
                / origin.stage
                / ("signals" if kind == "FACTOR_SIGNAL" else "backtests")
                / f"sha256-{receipt.adopted_artifact_hash}"
            )
            verified = (
                verify_signal_artifact(new_path)
                if kind == "FACTOR_SIGNAL"
                else verify_backtest_artifact(new_path)
            )
            if verified.resolved_experiment_hash != receipt.adopted_resolved_hash:
                self._integrity("native origin receipt differs from adopted experiment")
            old_resolved = ResolvedExperimentSpec.model_validate_json(
                (Path(origin.signal_path) / "resolved-experiment.json").read_bytes()
            )
            new_signal_path = (
                self.output_root
                / "executions"
                / request.execution_identity
                / origin.stage
                / "signals"
            )
            new_signals = tuple(new_signal_path.glob("sha256-*/resolved-experiment.json"))
            if len(new_signals) != 1:
                self._integrity("native origin receipt has ambiguous adopted signal bindings")
            new_resolved = ResolvedExperimentSpec.model_validate_json(new_signals[0].read_bytes())
            verify_adoption_bindings(old_resolved, new_resolved)
            if (
                old_resolved.content_hash != receipt.original_resolved_hash
                or new_resolved.content_hash != receipt.adopted_resolved_hash
            ):
                self._integrity("native origin receipt differs from original resolution")
            for native in receipt.native_files:
                for original_path in (
                    old_path / native.logical_path,
                    new_path / native.logical_path,
                ):
                    if (
                        original_path.is_symlink()
                        or not original_path.is_file()
                        or (
                            original_path.stat().st_size != native.size_bytes
                            or sha256_file(original_path) != native.bytes_hash
                        )
                    ):
                        self._integrity("native origin receipt lost its unchanged scientific bytes")
            hashes.append(receipt.content_hash)
            receipts.append(receipt)
        for origin in adoption.variants:
            if origin.subtask_hash != self.output_root.name:
                continue
            for kind, original_hash, subdirectory in (
                ("FACTOR_SIGNAL", origin.signal_hash, "signals"),
                ("QLIB_BACKTEST", origin.backtest_hash, "backtests"),
            ):
                artifacts = tuple(
                    (
                        self.output_root
                        / "executions"
                        / request.execution_identity
                        / origin.stage
                        / subdirectory
                    ).glob("sha256-*/manifest.json")
                )
                if original_hash is None or not artifacts:
                    continue
                matching = tuple(
                    item for item in receipts if item.original_artifact_hash == original_hash
                )
                if len(matching) != 1 or matching[0].artifact_kind != kind:
                    self._integrity("completed adopted stage lost its unique native origin receipt")
        return tuple(sorted(hashes))

    def _verify_model_split_for_request(
        self, request: AutonomousExecutionRequest, result: ResearchResultManifest
    ) -> QlibModelDataSplitAudit:
        resolved = ResolvedExperimentSpec.model_validate_json(
            (
                self.research_results_root
                / f"sha256-{result.artifact_hash}"
                / "resolved-experiment.json"
            ).read_bytes()
        )
        native = (
            self.output_root
            / "executions"
            / request.execution_identity
            / "qlib-workflow"
            / "native-records"
            / f"sha256-{request.execution_identity}"
        )
        return verify_model_data_split(
            native / "model-data-splits.json",
            resolved=resolved,
            research_policy=self.research_policy,
            calendar=tuple(
                date.fromisoformat(line.strip())
                for line in (self.qlib_view_path / "calendars" / "day.txt").read_text().splitlines()
                if line.strip()
            ),
            source_files=result.source_files,
        )

    def _verify_receipt(self, receipt: AutonomousExecutionReceipt) -> None:
        request = receipt.request
        self._verify_request(request)
        if receipt.outcome.request_hash != request.content_hash:
            self._integrity("execution receipt outcome binds a different request")
        if receipt.outcome.research_result_hash is not None and not set(
            self._native_adoption_hashes(request)
        ) <= set(receipt.outcome.evidence_hashes):
            self._integrity("native origin receipt hash is absent from execution evidence")
        result: ResearchResultManifest | None = None
        if receipt.outcome.research_result_hash is not None:
            result = self._verify_result_for_request(request, receipt.outcome.research_result_hash)
            split = self._verify_model_split_for_request(request, result)
            if split.content_hash not in receipt.outcome.evidence_hashes:
                self._integrity("effective model split hash is absent from the execution receipt")
            if self._native_label_audit_enabled:
                audit = self._verify_dq_audit_for_request(
                    request, receipt.outcome.research_result_hash
                )
                if audit.audit_hash not in receipt.outcome.evidence_hashes:
                    self._integrity("DQ export audit hash is absent from the execution receipt")
        if receipt.outcome.validation_report_hash is not None:
            report = self._load_validation_report(receipt.outcome.validation_report_hash)
            if (
                report.snapshot_hash != request.snapshot_hash
                or report.qlib_view_hash != request.qlib_view_hash
                or report.research_policy_hash != request.research_policy_hash
                or report.validation_policy_hash != request.validation_policy_hash
                or report.authoring_spec_hash != self._authoring(request).content_hash
                or result is None
                or report.resolved_experiment_hash != result.resolved_experiment_hash
                or report.signal_artifact_hash != result.signal_artifact_hash
                or report.backtest_result_hash is None
                or report.backtest_result_hash not in receipt.outcome.evidence_hashes
            ):
                self._integrity("published ValidationReport is bound to different inputs")
            try:
                backtest = verify_backtest_artifact(
                    self.output_root
                    / "executions"
                    / request.execution_identity
                    / "baseline"
                    / "backtests"
                    / f"sha256-{report.backtest_result_hash}"
                )
            except (QlibResearchError, OSError, ValueError) as error:
                self._integrity("execution backtest failed bottom-up verification", error)
            if (
                backtest.resolved_experiment_hash != result.resolved_experiment_hash
                or backtest.signal_artifact_hash != result.signal_artifact_hash
                or backtest.snapshot_hash != request.snapshot_hash
                or backtest.qlib_view_hash != request.qlib_view_hash
                or backtest.cost_policy_hash != request.cost_policy_hash
                or backtest.backtest_policy_hash != request.backtest_policy_hash
            ):
                self._integrity("execution backtest differs from the exact execution request")
            expected_outcome = (
                TrialOutcome.EXECUTION_FAILED
                if report.run_status is RunStatus.FAILED
                else TrialOutcome.PASS
                if report.verdict is ValidationVerdict.PASS
                else TrialOutcome.HARD_REJECT
                if any(
                    gate.severity is GateSeverity.HARD and gate.verdict is ValidationVerdict.REJECT
                    for gate in report.gates
                )
                else TrialOutcome.SOFT_REJECT
            )
            expected_reason = next(
                (gate.reason_code for gate in report.gates if gate.reason_code is not None), None
            )
            if (
                receipt.outcome.outcome is not expected_outcome
                or receipt.outcome.failure_reason_code is not expected_reason
                or receipt.outcome.research_result_hash is None
                or not receipt.outcome.execution_requested
                or report.report_hash not in receipt.outcome.evidence_hashes
                or result.artifact_hash not in receipt.outcome.evidence_hashes
            ):
                self._integrity("execution outcome differs from saved ValidationReport")
        elif (
            receipt.outcome.outcome not in (TrialOutcome.PIT_REJECT, TrialOutcome.EXECUTION_FAILED)
            or receipt.outcome.failure_reason_code is None
            or receipt.outcome.research_result_hash is not None
        ):
            self._integrity("execution without validation lacks classified native failure")
        else:
            self._verify_failure_for_receipt(receipt)

    def _verify_failure_for_receipt(self, receipt: AutonomousExecutionReceipt) -> None:
        """Pure, nonrecursive failure verification shared by every receipt reuse path."""
        request = receipt.request
        pit = receipt.outcome.outcome is TrialOutcome.PIT_REJECT
        allowed = (
            {ReasonCode.LOOK_AHEAD, ReasonCode.UNKNOWN_AVAILABILITY}
            if pit
            else {ReasonCode.QLIB_EXECUTION_FAILED, ReasonCode.SOURCE_INCOMPLETE}
        )
        if (
            receipt.outcome.failure_reason_code not in allowed
            or receipt.outcome.execution_requested == pit
        ):
            self._integrity("saved execution failure is outside native classification")
        failures: list[AutonomousExecutionFailureEvidence] = []
        for digest in receipt.outcome.evidence_hashes:
            path = self.output_root / "execution-failures" / f"sha256-{digest}.json"
            if not path.exists():
                continue
            try:
                with opened_directory(path.parent) as parent:
                    encoded = read_regular_bytes_at(parent, path.name, max_bytes=65536)
                failure = AutonomousExecutionFailureEvidence.model_validate_json(encoded)
            except (OSError, ValueError, ArtifactIntegrityError) as error:
                self._integrity("saved execution failure evidence is invalid", error)
            if failure.canonical_bytes() != encoded or failure.content_hash != digest:
                self._integrity("saved execution failure canonical bytes differ")
            failures.append(failure)
        if len(failures) != 1 or (
            failures[0].request_hash != request.content_hash
            or failures[0].execution_identity != request.execution_identity
            or failures[0].campaign_hash != request.campaign_hash
            or failures[0].candidate_hash != request.candidate.content_hash
            or failures[0].snapshot_hash != request.snapshot_hash
            or failures[0].reason_code != receipt.outcome.failure_reason_code
            or (failures[0].failure_kind == "PIT_REJECTED") != pit
        ):
            self._integrity("saved execution failure evidence is missing or mismatched")

    def _verify_result_for_request(
        self, request: AutonomousExecutionRequest, result_hash: str
    ) -> ResearchResultManifest:
        path = self.research_results_root / f"sha256-{result_hash}"
        try:
            result = verify_research_result(path)
            resolved = ResolvedExperimentSpec.model_validate_json(
                (path / "resolved-experiment.json").read_bytes()
            )
        except (QlibResearchError, OSError, ValidationError, ValueError) as error:
            self._integrity("execution ResearchResult failed bottom-up verification", error)
        if (
            result.artifact_hash != result_hash
            or result.qlib_run_id != request.execution_identity[:32]
            or result.snapshot_hash != request.snapshot_hash
            or result.qlib_view_hash != request.qlib_view_hash
            or result.expression_spec_hash != request.candidate.expression.content_hash
            or result.research_policy_hash != request.research_policy_hash
            or resolved.authoring_spec_hash != self._authoring(request).content_hash
            or resolved.evaluation_start != request.segment_start
            or resolved.evaluation_end != request.segment_end
        ):
            self._integrity("ResearchResult differs from the exact execution request")
        return result

    def _verify_dq_audit_for_request(
        self, request: AutonomousExecutionRequest, result_hash: str
    ) -> P14dqNativeLabelExportAudit:
        audit_root = self.output_root / "research-result-audits"
        matches: list[tuple[Path, P14dqNativeLabelExportAudit]] = []
        try:
            for path in sorted(audit_root.glob("sha256-*.json")):
                audit = P14dqNativeLabelExportAudit.model_validate_json(path.read_bytes())
                if audit.research_result_hash == result_hash:
                    matches.append((path, audit))
            if len(matches) != 1:
                self._integrity("DQ ResearchResult must have exactly one native-label audit")
            path, expected = matches[0]
            native_root = (
                self.output_root
                / "executions"
                / request.execution_identity
                / "qlib-workflow"
                / "native-records"
                / f"sha256-{request.execution_identity}"
            )
            calendar = tuple(
                day
                for day in (
                    date.fromisoformat(line)
                    for line in (self.qlib_view_path / "calendars" / "day.txt")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line
                )
                if request.segment_start <= day <= request.segment_end
            )
            verified = verify_p14dq_native_label_audit(
                self.research_results_root / f"sha256-{result_hash}",
                native_root,
                path,
                calendar,
            )
            if verified != expected:
                self._integrity("DQ export audit changed during bottom-up verification")
        except AutonomousOrchestrationError:
            raise
        except (QlibResearchError, OSError, ValueError, ValidationError) as error:
            self._integrity("DQ native-label export audit failed verification", error)
        return verified

    def _load_validation_report(self, report_hash: str) -> ValidationReport:
        try:
            return verify_validation_report(
                self.output_root / "validation" / f"sha256-{report_hash}"
            )
        except (ValueError, OSError) as error:
            self._integrity("execution ValidationReport failed bottom-up verification", error)

    def _receipt_path(self, execution_identity: str) -> Path:
        return self.output_root / "execution-records" / "identities" / f"{execution_identity}.json"

    def _reserve_trial_identity(self, request: AutonomousExecutionRequest) -> None:
        index = AutonomousExecutionTrialIndex(
            campaign_hash=request.campaign_hash,
            trial_ordinal=request.trial_ordinal,
            execution_identity=request.execution_identity,
            request_hash=request.content_hash,
        )
        key = f"{request.campaign_hash}-{request.trial_ordinal:08d}"
        identity_path = self.output_root / "trial-identities" / f"{key}.json"
        with exclusive_directory_lock(identity_path.parent):
            if identity_path.exists():
                try:
                    encoded = identity_path.read_bytes()
                    existing = AutonomousExecutionTrialIndex.model_validate_json(encoded)
                except (OSError, ValidationError, ValueError) as error:
                    self._integrity("trial identity index is invalid", error)
                if encoded != existing.canonical_bytes():
                    self._integrity("trial identity index is not canonical")
                if existing != index:
                    self._integrity("trial identity is already bound to different inputs")
                self._publish_content_addressed(
                    self.output_root / "trial-identity-artifacts",
                    existing.content_hash,
                    existing.canonical_bytes(),
                )
                return
            try:
                atomic_write_bytes(identity_path, index.canonical_bytes())
                self._publish_content_addressed(
                    self.output_root / "trial-identity-artifacts",
                    index.content_hash,
                    index.canonical_bytes(),
                )
            except (ArtifactConflictError, ArtifactIntegrityError, ValueError) as error:
                self._integrity("trial identity reservation conflicts", error)

    def _read_receipt(self, execution_identity: str) -> AutonomousExecutionReceipt | None:
        path = self._receipt_path(execution_identity)
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            receipt = AutonomousExecutionReceipt.model_validate_json(encoded)
        except (OSError, ValidationError, ValueError) as error:
            self._integrity("execution receipt is missing or invalid", error)
        if (
            encoded != receipt.canonical_bytes()
            or receipt.request.execution_identity != execution_identity
        ):
            self._integrity("execution receipt failed canonical or identity verification")
        self._publish_content_addressed(
            self.output_root / "execution-record-artifacts",
            receipt.content_hash,
            encoded,
        )
        return receipt

    def _receipt_for_result(self, result_hash: str) -> AutonomousExecutionReceipt | None:
        matches = [
            receipt
            for path in self._receipt_paths()
            if (receipt := self._read_receipt(path.stem)) is not None
            and receipt.outcome.research_result_hash == result_hash
        ]
        if len(matches) > 1:
            self._integrity("ResearchResult is bound by multiple execution receipts")
        return matches[0] if matches else None

    def _receipt_for_validation(self, report_hash: str) -> AutonomousExecutionReceipt | None:
        matches = [
            receipt
            for path in self._receipt_paths()
            if (receipt := self._read_receipt(path.stem)) is not None
            and receipt.outcome.validation_report_hash == report_hash
        ]
        if len(matches) > 1:
            self._integrity("ValidationReport is bound by multiple execution receipts")
        return matches[0] if matches else None

    def _receipt_for_failure(self, failure_hash: str) -> AutonomousExecutionReceipt | None:
        matches = [
            receipt
            for path in self._receipt_paths()
            if (receipt := self._read_receipt(path.stem)) is not None
            and failure_hash in receipt.outcome.evidence_hashes
        ]
        if len(matches) > 1:
            self._integrity("execution failure is bound by multiple execution receipts")
        return matches[0] if matches else None

    def _receipt_paths(self) -> tuple[Path, ...]:
        root = self.output_root / "execution-records" / "identities"
        if not root.exists():
            return ()
        try:
            files = regular_tree_files(root)
        except (OSError, ArtifactIntegrityError) as error:
            self._integrity("execution receipt store is invalid", error)
        if any(path.parent != root or path.suffix != ".json" for path in files):
            self._integrity("execution receipt store contains unexpected files")
        return tuple(sorted(files))

    @staticmethod
    def _publish_content_addressed(root: Path, digest: str, encoded: bytes) -> None:
        if sha256_bytes(encoded) != digest:
            raise ValueError("content-addressed evidence hash mismatch")
        path = root / f"sha256-{digest}.json"
        with exclusive_directory_lock(root):
            if path.exists():
                if path.read_bytes() != encoded:
                    raise ValueError("content-addressed failure evidence conflicts")
                return
            atomic_write_bytes(path, encoded, expected_sha256=digest)

    @staticmethod
    def _integrity(message: str, cause: BaseException | None = None) -> NoReturn:
        error = AutonomousOrchestrationError(ReasonCode.ARTIFACT_CORRUPTED, message)
        if cause is None:
            raise error
        raise error from cause
