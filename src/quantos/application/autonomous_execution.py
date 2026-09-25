"""Production execution adapter for P14d's existing deterministic research services."""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as day_time
from pathlib import Path
from typing import Any, Literal, NoReturn
from uuid import UUID, uuid5

from pydantic import ValidationError

from quantos.application import data_qualified_release as release
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.enumeration import (
    CandidateEnumerationError,
    verify_candidate_enumeration_manifest,
)
from quantos.application.schedules import resolve_weekly_decision_schedules
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    regular_tree_files,
)
from quantos.backtest import QlibBacktestService
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
from quantos.contracts.enumeration import CandidateEnumerationManifest, ResearchFactorTemplateSpec
from quantos.contracts.qlib_view import QlibViewManifest
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
    QlibResearchError,
    QlibWorkflowResearchService,
    verify_p14dq_native_label_audit,
    verify_research_result,
)
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


def autonomous_compute_accounting_policy_hash() -> str:
    """Return the frozen deterministic compute-accounting policy hash."""

    return sha256_bytes(canonical_json_bytes(_COMPUTE_ACCOUNTING_POLICY))


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
    ) -> None:
        try:
            verify_candidate_enumeration_manifest(family, template, manifest)
            snapshot = verify_snapshot(snapshot_path)
            view = verify_qlib_view(qlib_view_path)
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
            or view.view_hash
            != "fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
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
        self._candidate_by_hash = {item.content_hash: item for item in manifest.candidates}

    @property
    def research_results_root(self) -> Path:
        return self.output_root / "research-results"

    def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
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
            if self.p14dq_v2_profile and outcome.research_result_hash is not None:
                audit = self._verify_dq_audit_for_request(request, outcome.research_result_hash)
                if audit.audit_hash not in outcome.evidence_hashes:
                    self._integrity("DQ export audit is absent before receipt publication")
            return self._publish_receipt(request, outcome)

    def verify_preselection_dq_trials(
        self, events: tuple[ResearchCampaignEvent, ...]
    ) -> None:
        """Reverify every DQ trial and its native-label audit before P14c reads it."""

        if not self.p14dq_v2_profile:
            self._integrity("DQ preselection verification requires the frozen DQ profile")
        trials = tuple(
            event.trial
            for event in events
            if event.event_type is CampaignEventType.TRIAL_RECORDED and event.trial is not None
        )
        if (
            len(trials) != len(self.manifest.candidates)
            or {trial.candidate_hash for trial in trials} != set(self._candidate_by_hash)
        ):
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
            if (
                receipt.outcome.outcome is not trial.outcome
                or not set(receipt.outcome.evidence_hashes).issubset(trial.evidence_hashes)
            ):
                self._integrity("DQ trial evidence differs from its receipt")
            self._verify_receipt(receipt)

    def _deterministic_compute_charge(self, request: AutonomousExecutionRequest) -> int:
        """Derive the frozen workload charge for one execution-class request.

        The charge is a policy unit derived from the exact candidate authoring, the frozen
        validation workload shape, and the frozen compute-accounting policy. It is never an
        observation of elapsed time.
        """

        authoring = self._authoring(request)
        baseline_window = release.parameter_window(authoring)
        parameter_variants = sum(
            1
            for window in self.validation_policy.parameter_windows
            for top_k in self.validation_policy.parameter_top_k
            if (window, top_k) != (baseline_window, authoring.strategy.top_k)
        )
        cost_variants = sum(
            1 for multiplier in self.validation_policy.cost_stress_multipliers if multiplier != 1.0
        )
        return (
            _COMPUTE_BASELINE_EXECUTION
            + _COMPUTE_COST_STRESS_VARIANT * cost_variants
            + _COMPUTE_PARAMETER_VARIANT * parameter_variants
            + _COMPUTE_SUBPERIOD_VARIANT * len(self.validation_policy.subperiods)
            + _COMPUTE_REPRODUCTION_BACKTEST
            + _COMPUTE_VALIDATION_REPORT
        )

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
                self.output_root / "research-result-audits" if self.p14dq_v2_profile else None
            ),
        )
        result_manifest = verify_research_result(workflow.build.path)
        if (
            result_manifest.artifact_hash != workflow.build.manifest.artifact_hash
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
            if self.p14dq_v2_profile:
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
                if len(period_schedules) != required.get(period.period_id):
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

        reproduction = QlibBacktestService().run(
            baseline.resolved,
            baseline.signal_path,
            self.qlib_view_path,
            self.cost_policy,
            self.backtest_policy,
            execution_root / "reproduction",
            workspace=self.workspace,
        )
        locators = ValidationRunLocators(
            snapshot_path=self.snapshot_path,
            qlib_view_path=self.qlib_view_path,
            signal_path=baseline.signal_path,
            research_result_path=workflow.build.path,
            baseline_backtest_path=baseline.backtest_path,
            reproduction_backtest_path=reproduction.path,
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
        validation_build = ValidationService().run(
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
        report = verify_validation_report(validation_build.path)
        if (
            report.report_hash != validation_build.report.report_hash
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
            workflow.build.export_audit_hash,
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

    def _verify_receipt(self, receipt: AutonomousExecutionReceipt) -> None:
        request = receipt.request
        self._verify_request(request)
        if receipt.outcome.request_hash != request.content_hash:
            self._integrity("execution receipt outcome binds a different request")
        if receipt.outcome.research_result_hash is not None:
            self._verify_result_for_request(request, receipt.outcome.research_result_hash)
            if self.p14dq_v2_profile:
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
            ):
                self._integrity("published ValidationReport is bound to different inputs")

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
