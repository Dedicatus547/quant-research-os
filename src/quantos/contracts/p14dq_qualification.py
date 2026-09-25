"""Immutable evidence contracts for the P14-DQ qualification path."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import ClassVar, Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.autonomous import (
    P14DQ_LIMITATIONS,
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousLoopState,
    AutonomousSelectionFinalizationProfile,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.p14d_qualification import (
    P14D_NEGATIVE_CASES,
    P14dNegativeCaseEvidence,
    p14d_replay_binding_hash,
)
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import GateSeverity, ValidationGateId

P14DQ_SNAPSHOT_HASH = "6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
P14DQ_VIEW_HASH = "fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
P14DQ_VIEW_SPEC_HASH = "b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375"
P14DQ_UPSTREAM_RELEASE_REPORT_HASH = (
    "6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca"
)
P14DQ_TEMPLATE_HASH = "a9df666299ac2feac2a50608d76b568bf6bc31bbfaaa1d98c0c60a4a6a69158a"
P14DQ_FAMILY_HASH = "fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb"
P14DQ_CANDIDATE_MANIFEST_HASH = "b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae"
P14DQ_CANDIDATE_HASHES = (
    "b7ca426ad868e15827365aa2bfcceb20870893a91add47713ff88dc2a43d444f",
    "f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96",
)
P14DQ_NEGATIVE_CASES = (
    "DQ_SNAPSHOT_HASH_OR_PATH_MISMATCH",
    "DQ_SYNTHETIC_OR_ALTERNATE_SNAPSHOT",
    "DQ_SNAPSHOT_FILE_TAMPER_OR_EXTRA_FILE",
    "DQ_QUALITY_REPORT_OR_LIMITATION_MISMATCH",
    "DQ_VIEW_HASH_OR_FILE_SET_MISMATCH",
    "DQ_VIEW_SOURCE_SNAPSHOT_MISMATCH",
    "DQ_QILIB_SPEC_OR_HEALTH_MISMATCH",
    "DQ_UPSTREAM_RELEASE_REPORT_TAMPER",
    "DQ_UNQUALIFIED_UPSTREAM_RELEASE",
    "DQ_ROOT_INPUT_SUBSTITUTION",
    "DQ_FORBIDDEN_SEALED_HANDOFF",
    "DQ_QUALIFICATION_BUNDLE_FILE_SET_TAMPER",
)
P14DQ_RESTART_CASES = (
    "AGENT_EXCHANGE_AND_EXECUTION_RECEIPT_BEFORE_TRIAL",
    "CAMPAIGN_TRIAL_COMMITTED_LEDGER_RECONCILIATION_INCOMPLETE",
    "P14C_REPORT_PUBLISHED_BEFORE_CAMPAIGN_CLOSE",
)

# Frozen Validation gate contract for the zero-eligible engineering exception. The gate
# order, severity map and admissible-rejection allowlist are copied into the P14-DQ
# contract on purpose: if the live Validation contract ever adds, removes or reseverities
# a gate, the recorded gate set stops matching this frozen tuple and the evidence fails
# closed instead of silently widening the exception.
P14DQ_FROZEN_VALIDATION_GATE_ORDER: tuple[ValidationGateId, ...] = (
    ValidationGateId.G0_SCHEMA_REFERENCE,
    ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
    ValidationGateId.G2_PIT_LINEAGE,
    ValidationGateId.G3_FACTOR_RESEARCH,
    ValidationGateId.G4_REFERENCE_BACKTEST,
    ValidationGateId.G5_OUT_OF_SAMPLE,
    ValidationGateId.G6_COST_STRESS,
    ValidationGateId.G7_PARAMETER_STABILITY,
    ValidationGateId.G8_SUBPERIOD_STABILITY,
    ValidationGateId.G9_REPRODUCIBILITY,
    ValidationGateId.G10_ARTIFACT_INTEGRITY,
)
P14DQ_FROZEN_VALIDATION_GATE_SEVERITY: Mapping[ValidationGateId, GateSeverity] = MappingProxyType(
    {
        ValidationGateId.G0_SCHEMA_REFERENCE: GateSeverity.HARD,
        ValidationGateId.G1_SNAPSHOT_DATA_QUALITY: GateSeverity.HARD,
        ValidationGateId.G2_PIT_LINEAGE: GateSeverity.HARD,
        ValidationGateId.G3_FACTOR_RESEARCH: GateSeverity.SOFT,
        ValidationGateId.G4_REFERENCE_BACKTEST: GateSeverity.SOFT,
        ValidationGateId.G5_OUT_OF_SAMPLE: GateSeverity.SOFT,
        ValidationGateId.G6_COST_STRESS: GateSeverity.SOFT,
        ValidationGateId.G7_PARAMETER_STABILITY: GateSeverity.SOFT,
        ValidationGateId.G8_SUBPERIOD_STABILITY: GateSeverity.SOFT,
        ValidationGateId.G9_REPRODUCIBILITY: GateSeverity.HARD,
        ValidationGateId.G10_ARTIFACT_INTEGRITY: GateSeverity.HARD,
    }
)
P14DQ_REQUIRED_PASSING_GATES: tuple[ValidationGateId, ...] = (
    ValidationGateId.G0_SCHEMA_REFERENCE,
    ValidationGateId.G1_SNAPSHOT_DATA_QUALITY,
    ValidationGateId.G2_PIT_LINEAGE,
    ValidationGateId.G4_REFERENCE_BACKTEST,
    ValidationGateId.G9_REPRODUCIBILITY,
    ValidationGateId.G10_ARTIFACT_INTEGRITY,
)
P14DQ_ADMISSIBLE_SOFT_REJECTION_GATES: tuple[ValidationGateId, ...] = (
    ValidationGateId.G3_FACTOR_RESEARCH,
    ValidationGateId.G5_OUT_OF_SAMPLE,
    ValidationGateId.G6_COST_STRESS,
    ValidationGateId.G7_PARAMETER_STABILITY,
    ValidationGateId.G8_SUBPERIOD_STABILITY,
)
P14DQ_ADMISSIBLE_SOFT_REJECTION_REASON = ReasonCode.SOFT_THRESHOLD_NOT_MET


class P14dqNamedHash(CanonicalContract):
    schema_version: Literal["p14dq-named-hash/v1"] = "p14dq-named-hash/v1"
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_/-]*$")
    sha256: str = Field(pattern=SHA256_PATTERN)


class P14dqQualificationFile(CanonicalContract):
    schema_version: Literal["p14dq-qualification-file/v1"] = "p14dq-qualification-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class P14dqQualificationAttempt(CanonicalContract):
    """Content-addressed evidence for an incomplete, non-qualifying runner attempt."""

    schema_version: Literal["p14dq-qualification-attempt/v1"] = "p14dq-qualification-attempt/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"attempt_hash"})

    attempt_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal[RunStatus.FAILED] = RunStatus.FAILED
    verdict: Literal[ValidationVerdict.NOT_EVALUATED] = ValidationVerdict.NOT_EVALUATED
    reason_code: ReasonCode
    files: tuple[P14dqQualificationFile, ...]

    @field_validator("files")
    @classmethod
    def files_are_sorted_and_unique(
        cls, value: tuple[P14dqQualificationFile, ...]
    ) -> tuple[P14dqQualificationFile, ...]:
        paths = tuple(item.logical_path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("P14-DQ attempt files must be sorted and unique")
        return value

    @model_validator(mode="after")
    def attempt_hash_matches(self) -> Self:
        if self.attempt_hash != self.content_hash:
            raise ValueError("P14-DQ attempt hash does not match its content")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_construct(_fields_set=None, attempt_hash="0" * 64, **values)
        return cls(attempt_hash=provisional.content_hash, **values)  # type: ignore[arg-type]


class P14dqExternalBindings(CanonicalContract):
    schema_version: Literal["p14dq-external-bindings/v1"] = "p14dq-external-bindings/v1"
    snapshot_path: Literal[
        "artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
    ]
    snapshot_hash: Literal["6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"]
    snapshot_manifest_file_hash: str = Field(pattern=SHA256_PATTERN)
    snapshot_files_inventory_hash: str = Field(pattern=SHA256_PATTERN)
    source_kind: Literal["TUSHARE"] = "TUSHARE"
    provider: Literal["tushare-pro"] = "tushare-pro"
    dataset_id: Literal["cn-a-share-hs300-eval-2015-2025-v1"] = "cn-a-share-hs300-eval-2015-2025-v1"
    snapshot_start_date: date
    snapshot_end_date: date
    quality_report_hash: Literal["e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8"]
    quality_report_file_hash: str = Field(pattern=SHA256_PATTERN)
    non_vintage_limitation: Literal["SINGLE_SOURCE_NON_VINTAGE"] = "SINGLE_SOURCE_NON_VINTAGE"
    qlib_view_path: Literal[
        "artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
    ]
    qlib_view_hash: Literal["fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"]
    qlib_view_manifest_file_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_view_files_inventory_hash: str = Field(pattern=SHA256_PATTERN)
    view_spec_hash: Literal["b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375"]
    view_spec_file_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_version: Literal["0.9.7"] = "0.9.7"
    qlib_source_commit: Literal["da920b7f954f48ab1bb64117c976710de198373e"] = (
        "da920b7f954f48ab1bb64117c976710de198373e"
    )
    dump_bin_sha256: str = Field(pattern=SHA256_PATTERN)
    health_check_sha256: str = Field(pattern=SHA256_PATTERN)
    qlib_view_manifest_bindings_hash: str = Field(pattern=SHA256_PATTERN)
    upstream_release_report_path: Literal[
        "artifacts/releases/data-qualified-v0.1-f3fc768/report.json"
    ] = "artifacts/releases/data-qualified-v0.1-f3fc768/report.json"
    upstream_release_report_hash: Literal[
        "6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca"
    ] = "6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca"
    upstream_release_input_hash: str = Field(pattern=SHA256_PATTERN)
    upstream_release_status: Literal["PASS"] = "PASS"
    upstream_release_track: Literal["DATA_QUALIFIED"] = "DATA_QUALIFIED"
    upstream_data_qualified: Literal[True] = True
    historical_validation_verdict: Literal["REJECT"] = "REJECT"
    historical_strategy_status: Literal["REJECTED"] = "REJECTED"

    @model_validator(mode="after")
    def date_range_is_frozen(self) -> Self:
        if (self.snapshot_start_date, self.snapshot_end_date) != (
            date(2014, 11, 1),
            date(2025, 12, 31),
        ):
            raise ValueError("P14-DQ snapshot date range differs from the frozen binding")
        return self


class P14dqValidationGateEvidence(CanonicalContract):
    """One frozen Validation gate outcome, recorded only as a verified fact."""

    schema_version: Literal["p14dq-validation-gate-evidence/v1"] = (
        "p14dq-validation-gate-evidence/v1"
    )
    gate_id: ValidationGateId
    severity: GateSeverity
    verdict: ValidationVerdict
    reason_code: ReasonCode | None = None

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> Self:
        if self.severity is not P14DQ_FROZEN_VALIDATION_GATE_SEVERITY[self.gate_id]:
            raise ValueError("P14-DQ validation gate severity differs from the frozen contract")
        if self.verdict is ValidationVerdict.PASS and self.reason_code is not None:
            raise ValueError("passing P14-DQ validation gate cannot carry a reason code")
        if self.verdict is ValidationVerdict.REJECT and self.reason_code is None:
            raise ValueError("rejected P14-DQ validation gate requires a reason code")
        return self


class P14dqCandidateEvaluation(CanonicalContract):
    schema_version: Literal["p14dq-candidate-evaluation/v2"] = "p14dq-candidate-evaluation/v2"
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    trial_event_hash: str = Field(pattern=SHA256_PATTERN)
    trial_outcome: TrialOutcome
    research_result_hash: str = Field(pattern=SHA256_PATTERN)
    export_audit_hash: str = Field(pattern=SHA256_PATTERN)
    validation_report_hash: str = Field(pattern=SHA256_PATTERN)
    validation_status: Literal[RunStatus.SUCCEEDED] = RunStatus.SUCCEEDED
    validation_verdict: Literal[ValidationVerdict.PASS, ValidationVerdict.REJECT]
    validation_gates: tuple[P14dqValidationGateEvidence, ...]

    @model_validator(mode="after")
    def result_matches_verdict(self) -> Self:
        if tuple(item.gate_id for item in self.validation_gates) != (
            P14DQ_FROZEN_VALIDATION_GATE_ORDER
        ):
            raise ValueError(
                "P14-DQ natural candidate must record the complete frozen Validation gate set"
            )
        rejected = tuple(
            item for item in self.validation_gates if item.verdict is ValidationVerdict.REJECT
        )
        not_evaluated = tuple(
            item
            for item in self.validation_gates
            if item.verdict is ValidationVerdict.NOT_EVALUATED
        )
        verdict = (
            ValidationVerdict.REJECT
            if rejected
            else ValidationVerdict.PASS
            if not not_evaluated
            else ValidationVerdict.NOT_EVALUATED
        )
        if verdict is not self.validation_verdict:
            raise ValueError("P14-DQ Validation verdict differs from its recorded gates")
        hard_rejected = any(item.severity is GateSeverity.HARD for item in rejected)
        if self.trial_outcome is TrialOutcome.PASS:
            valid = self.validation_verdict is ValidationVerdict.PASS
        elif self.trial_outcome is TrialOutcome.SOFT_REJECT:
            valid = self.validation_verdict is ValidationVerdict.REJECT and not hard_rejected
        elif self.trial_outcome is TrialOutcome.HARD_REJECT:
            valid = self.validation_verdict is ValidationVerdict.REJECT and hard_rejected
        else:
            valid = False
        if not valid:
            raise ValueError("P14-DQ natural candidate outcome is not a Validation disposition")
        return self

    def admissible_research_rejection(self) -> bool:
        """Rebuild the only zero-eligible rejection the v3 exception may accept.

        Positive allowlist: a genuine executed research-threshold rejection must leave
        every HARD gate and the reference-backtest gate PASS, must not contain any
        NOT_EVALUATED gate, and every REJECT gate must be one of the frozen soft
        research gates rejected solely for `SOFT_THRESHOLD_NOT_MET`. Any other
        rejection cause, gate, severity or reason code fails closed. This is derived
        from recorded gate facts and is never supplied as a caller assertion.
        """

        if self.validation_status is not RunStatus.SUCCEEDED:
            return False
        if self.validation_verdict is not ValidationVerdict.REJECT:
            return False
        if any(item.verdict is ValidationVerdict.NOT_EVALUATED for item in self.validation_gates):
            return False
        if any(
            item.verdict is not ValidationVerdict.PASS
            for item in self.validation_gates
            if item.gate_id in P14DQ_REQUIRED_PASSING_GATES
        ):
            return False
        rejected = tuple(
            item for item in self.validation_gates if item.verdict is ValidationVerdict.REJECT
        )
        if not rejected:
            return False
        return all(
            item.gate_id in P14DQ_ADMISSIBLE_SOFT_REJECTION_GATES
            and item.severity is GateSeverity.SOFT
            and item.reason_code is P14DQ_ADMISSIBLE_SOFT_REJECTION_REASON
            for item in rejected
        )


class P14dqCampaignEvidence(CanonicalContract):
    schema_version: Literal["p14dq-campaign-evidence/v3"] = "p14dq-campaign-evidence/v3"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: Literal["fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb"]
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: Literal[
        "b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae"
    ]
    candidate_hashes: tuple[str, ...]
    context_pack_hashes: tuple[str, ...]
    agent_request_hashes: tuple[str, ...]
    agent_proposal_hashes: tuple[str, ...]
    execution_request_hashes: tuple[str, ...]
    execution_identities: tuple[str, ...]
    evaluations: tuple[P14dqCandidateEvaluation, ...]
    selection_plan_hash: str = Field(pattern=SHA256_PATTERN)
    selection_calendar_hash: str = Field(pattern=SHA256_PATTERN)
    selection_calendar_session_count: PositiveInt
    selection_calendar_first_date: date
    selection_calendar_last_date: date
    selection_report_hash: str = Field(pattern=SHA256_PATTERN)
    selection_status: RunStatus
    selection_verdict: Literal[
        "SELECTED",
        "NO_SELECTION",
        "NOT_EVALUATED",
    ]
    selection_reason_code: ReasonCode | None
    eligible_candidate_count: NonNegativeInt
    selection_performed: bool
    selected_candidate_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    campaign_trial_hashes: tuple[str, ...]
    campaign_event_hashes: tuple[str, ...]
    final_campaign_event_hash: str = Field(pattern=SHA256_PATTERN)
    final_ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_principal_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_loop_report_hash: str = Field(pattern=SHA256_PATTERN)
    loop_state: Literal[AutonomousLoopState.SELECTION_COMPLETE] = (
        AutonomousLoopState.SELECTION_COMPLETE
    )
    selection_event_hash: None = None
    sealed_confirmation_authority: Literal[False] = False

    @model_validator(mode="after")
    def natural_campaign_is_evaluated_and_report_only(self) -> Self:
        if self.candidate_hashes != P14DQ_CANDIDATE_HASHES:
            raise ValueError("P14-DQ denominator must be the frozen two-candidate manifest")
        if tuple(item.candidate_hash for item in self.evaluations) != self.candidate_hashes:
            raise ValueError("P14-DQ natural run must evaluate every frozen candidate in order")
        for hashes in (
            tuple(item.research_result_hash for item in self.evaluations),
            tuple(item.export_audit_hash for item in self.evaluations),
            tuple(item.validation_report_hash for item in self.evaluations),
        ):
            if len(set(hashes)) != len(self.candidate_hashes):
                raise ValueError("P14-DQ candidates must have distinct verified evidence")
        if len(self.campaign_trial_hashes) != 2 or len(set(self.campaign_trial_hashes)) != 2:
            raise ValueError("P14-DQ natural run must record exactly two candidate trials")
        if (
            not self.campaign_event_hashes
            or self.final_campaign_event_hash != self.campaign_event_hashes[-1]
        ):
            raise ValueError("P14-DQ campaign event hash is not the chain head")
        eligible_count = sum(item.trial_outcome is TrialOutcome.PASS for item in self.evaluations)
        if eligible_count != self.eligible_candidate_count:
            raise ValueError("P14-DQ eligible count differs from verified candidate outcomes")
        if eligible_count == 0:
            if (
                self.selection_status is not RunStatus.FAILED
                or self.selection_verdict != "NOT_EVALUATED"
                or self.selection_reason_code is not ReasonCode.SOURCE_INCOMPLETE
                or self.selection_performed
                or self.selected_candidate_hash is not None
                or any(
                    item.trial_outcome not in {TrialOutcome.SOFT_REJECT, TrialOutcome.HARD_REJECT}
                    for item in self.evaluations
                )
                or not all(item.admissible_research_rejection() for item in self.evaluations)
            ):
                raise ValueError("P14-DQ zero-eligible natural outcome is not exact")
        elif (
            self.selection_status is not RunStatus.SUCCEEDED
            or self.selection_verdict not in {"SELECTED", "NO_SELECTION"}
            or self.selection_reason_code is not None
            or not self.selection_performed
        ):
            raise ValueError("P14-DQ eligible natural selection did not complete")
        if (self.selection_verdict == "SELECTED") != (self.selected_candidate_hash is not None):
            raise ValueError("P14-DQ selected candidate does not match the natural verdict")
        if self.selected_candidate_hash is not None and self.selected_candidate_hash not in (
            self.candidate_hashes
        ):
            raise ValueError("P14-DQ selected candidate escapes the frozen denominator")
        for values in (
            self.context_pack_hashes,
            self.agent_request_hashes,
            self.agent_proposal_hashes,
            self.execution_request_hashes,
            self.execution_identities,
            self.campaign_trial_hashes,
            self.campaign_event_hashes,
        ):
            if not values or len(values) != len(set(values)):
                raise ValueError("P14-DQ campaign histories must be nonempty and unique")
            if any(
                len(item) != 64 or any(c not in "0123456789abcdef" for c in item) for item in values
            ):
                raise ValueError("P14-DQ campaign history contains an invalid hash")
        if self.selection_calendar_first_date > self.selection_calendar_last_date:
            raise ValueError("P14-DQ selection calendar date range is invalid")
        return self


class P14dqNegativeCaseEvidence(CanonicalContract):
    schema_version: Literal["p14dq-negative-case-evidence/v1"] = "p14dq-negative-case-evidence/v1"
    case_id: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    input_hash: str = Field(pattern=SHA256_PATTERN)
    outcome_hash: str = Field(pattern=SHA256_PATTERN)
    reason_code: ReasonCode

    @model_validator(mode="after")
    def case_is_frozen(self) -> Self:
        if self.case_id not in P14DQ_NEGATIVE_CASES:
            raise ValueError("unknown P14-DQ external negative case")
        return self


class P14dqRestartCaseEvidence(CanonicalContract):
    schema_version: Literal["p14dq-restart-case-evidence/v1"] = "p14dq-restart-case-evidence/v1"
    case_id: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    input_hash: str = Field(pattern=SHA256_PATTERN)
    pre_restart_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    post_restart_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_runs_before_restart: NonNegativeInt
    qlib_runs_after_restart: NonNegativeInt
    pre_campaign_close_count: NonNegativeInt
    post_campaign_close_count: NonNegativeInt
    pre_selection_frozen_event_count: Literal[0] = 0
    post_selection_frozen_event_count: Literal[0] = 0
    final_campaign_close_count: Literal[1] = 1
    duplicate_authority_absent: Literal[True] = True

    @model_validator(mode="after")
    def case_is_frozen(self) -> Self:
        if self.case_id not in P14DQ_RESTART_CASES:
            raise ValueError("unknown P14-DQ restart case")
        if self.qlib_runs_after_restart < self.qlib_runs_before_restart:
            raise ValueError("P14-DQ restart Qlib run count cannot decrease")
        if self.pre_campaign_close_count > 1 or self.post_campaign_close_count > 1:
            raise ValueError("P14-DQ restart duplicated campaign closure")
        return self


class P14dqReplayCaseEvidence(CanonicalContract):
    schema_version: Literal["p14dq-replay-case-evidence/v1"] = "p14dq-replay-case-evidence/v1"
    prior_exchange_hash: str = Field(pattern=SHA256_PATTERN)
    request_hash: str = Field(pattern=SHA256_PATTERN)
    response_hash: str = Field(pattern=SHA256_PATTERN)
    proposal_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)
    execution_identity: str = Field(pattern=SHA256_PATTERN)
    execution_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_runs_before_replay: NonNegativeInt
    qlib_runs_after_replay: NonNegativeInt
    authority_promoted: Literal[False] = False

    @model_validator(mode="after")
    def replay_reuses_verified_execution(self) -> Self:
        if self.qlib_runs_before_replay != self.qlib_runs_after_replay:
            raise ValueError("P14-DQ replay performed another Qlib execution")
        if self.prior_exchange_hash != p14d_replay_binding_hash(
            request_hash=self.request_hash,
            response_hash=self.response_hash,
            proposal_hash=self.proposal_hash,
            candidate_hash=self.candidate_hash,
            execution_identity=self.execution_identity,
        ):
            raise ValueError("P14-DQ replay evidence is not canonically bound")
        return self


class P14dqRootEvidence(CanonicalContract):
    schema_version: Literal["p14dq-root-evidence/v3"] = "p14dq-root-evidence/v3"
    root_id: Literal["root-A", "root-B"]
    external_bindings_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: Literal["fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb"]
    candidate_manifest_hash: Literal[
        "b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae"
    ]
    finalization_profile_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_campaign_policy_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_agent_run_policy_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_compute_accounting_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_execution_bindings_hash: str = Field(pattern=SHA256_PATTERN)
    multiple_testing_policy_hash: str = Field(pattern=SHA256_PATTERN)
    selection_policy_hash: str = Field(pattern=SHA256_PATTERN)
    campaign: P14dqCampaignEvidence
    p14d_negative_cases: tuple[P14dNegativeCaseEvidence, ...]
    p14dq_negative_cases: tuple[P14dqNegativeCaseEvidence, ...]
    restart_cases: tuple[P14dqRestartCaseEvidence, ...]
    replay_case: P14dqReplayCaseEvidence
    artifact_tree_hash: str = Field(pattern=SHA256_PATTERN)
    principal_hash_summary: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def root_evidence_is_complete(self) -> Self:
        if tuple(item.case_id for item in self.p14d_negative_cases) != P14D_NEGATIVE_CASES:
            raise ValueError("P14-DQ must retain the applicable P14d negative-case coverage")
        if tuple(item.case_id for item in self.p14dq_negative_cases) != P14DQ_NEGATIVE_CASES:
            raise ValueError("P14-DQ external negative-case evidence is incomplete or unordered")
        if tuple(item.case_id for item in self.restart_cases) != P14DQ_RESTART_CASES:
            raise ValueError("P14-DQ restart evidence is incomplete or unordered")
        if self.finalization_profile_hash != P14DQ_REPORT_ONLY_FINALIZATION_PROFILE.content_hash:
            raise ValueError("P14-DQ root does not bind report-only finalization")
        if (
            self.campaign.selection_event_hash is not None
            or self.campaign.sealed_confirmation_authority
        ):
            raise ValueError("P14-DQ root contains sealed-selection authority")
        if self.principal_hash_summary != p14dq_root_principal_hash(self):
            raise ValueError("P14-DQ root principal hash summary does not match evidence")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_construct(
            _fields_set=None, principal_hash_summary="0" * 64, **values
        )
        return cls(principal_hash_summary=p14dq_root_principal_hash(provisional), **values)  # type: ignore[arg-type]


def p14dq_root_principal_payload(root: P14dqRootEvidence) -> object:
    return {
        "artifact_tree_hash": root.artifact_tree_hash,
        "autonomous_agent_run_policy_hash": root.autonomous_agent_run_policy_hash,
        "autonomous_campaign_policy_hash": root.autonomous_campaign_policy_hash,
        "autonomous_compute_accounting_hash": root.autonomous_compute_accounting_hash,
        "autonomous_execution_bindings_hash": root.autonomous_execution_bindings_hash,
        "campaign": root.campaign.model_dump(mode="python"),
        "candidate_manifest_hash": root.candidate_manifest_hash,
        "external_bindings_hash": root.external_bindings_hash,
        "family_hash": root.family_hash,
        "finalization_profile_hash": root.finalization_profile_hash,
        "multiple_testing_policy_hash": root.multiple_testing_policy_hash,
        "p14d_negative_cases": tuple(
            item.model_dump(mode="python") for item in root.p14d_negative_cases
        ),
        "p14dq_negative_cases": tuple(
            item.model_dump(mode="python") for item in root.p14dq_negative_cases
        ),
        "replay_case": root.replay_case.model_dump(mode="python"),
        "restart_cases": tuple(item.model_dump(mode="python") for item in root.restart_cases),
        "selection_policy_hash": root.selection_policy_hash,
    }


def p14dq_root_principal_hash(root: P14dqRootEvidence) -> str:
    return sha256_bytes(canonical_json_bytes(p14dq_root_principal_payload(root)))


def p14dq_principal_hash_summary(roots: tuple[P14dqRootEvidence, ...]) -> str:
    if tuple(item.root_id for item in roots) != ("root-A", "root-B"):
        raise ValueError("P14-DQ principal summary requires root-A and root-B in order")
    return sha256_bytes(canonical_json_bytes(tuple(p14dq_root_principal_payload(r) for r in roots)))


class P14dqQualificationReport(CanonicalContract):
    """Content-addressed, successful P14-DQ engineering qualification report."""

    schema_version: Literal["p14dq-qualification-report/v3"] = "p14dq-qualification-report/v3"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"qualification_hash"})

    qualification_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal[RunStatus.SUCCEEDED] = RunStatus.SUCCEEDED
    verdict: Literal[ValidationVerdict.PASS] = ValidationVerdict.PASS
    implementation_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_provenance_hash: str = Field(pattern=SHA256_PATTERN)
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    qualification_contract_hash: str = Field(pattern=SHA256_PATTERN)
    external_bindings: P14dqExternalBindings
    family_hash: Literal["fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb"]
    candidate_manifest_hash: Literal[
        "b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae"
    ]
    finalization_profile: AutonomousSelectionFinalizationProfile
    policy_hashes: tuple[P14dqNamedHash, ...]
    roots: tuple[P14dqRootEvidence, ...]
    principal_hash_summary: str = Field(pattern=SHA256_PATTERN)
    principal_hashes_byte_exact: Literal[True] = True
    p14d_negative_case_count: PositiveInt
    p14dq_negative_case_count: PositiveInt
    restart_case_count: PositiveInt
    limitations: tuple[str, ...]
    files: tuple[P14dqQualificationFile, ...]

    @field_validator("policy_hashes")
    @classmethod
    def policy_hashes_are_sorted(
        cls, value: tuple[P14dqNamedHash, ...]
    ) -> tuple[P14dqNamedHash, ...]:
        names = tuple(item.name for item in value)
        if names != tuple(sorted(set(names))):
            raise ValueError("P14-DQ policy hashes must be sorted and unique")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_frozen(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != P14DQ_LIMITATIONS:
            raise ValueError("P14-DQ limitation set differs from its frozen live-data boundary")
        return value

    @field_validator("files")
    @classmethod
    def files_are_sorted_and_unique(
        cls, value: tuple[P14dqQualificationFile, ...]
    ) -> tuple[P14dqQualificationFile, ...]:
        paths = tuple(item.logical_path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("P14-DQ qualification files must be sorted and unique")
        return value

    @model_validator(mode="after")
    def report_is_complete_and_reproducible(self) -> Self:
        if self.qualification_hash != self.content_hash:
            raise ValueError("P14-DQ qualification hash does not match report content")
        if self.finalization_profile != P14DQ_REPORT_ONLY_FINALIZATION_PROFILE:
            raise ValueError("P14-DQ report does not bind the frozen report-only profile")
        required_policy_names = {
            "autonomous_agent_run_policy",
            "autonomous_campaign_policy",
            "autonomous_compute_accounting",
            "autonomous_execution_bindings",
            "backtest_policy",
            "backtest_policy_file",
            "candidate_manifest",
            "cost_policy",
            "cost_policy_file",
            "execution_authoring",
            "execution_authoring_file",
            "finalization_profile",
            "multiple_testing_policy",
            "p14c_selection_plan",
            "p14dq_family",
            "p14dq_qualification_contract",
            "p14dq_template",
            "research_policy",
            "research_policy_file",
            "selection_policy",
            "validation_policy",
            "validation_policy_file",
        }
        if not required_policy_names.issubset({item.name for item in self.policy_hashes}):
            raise ValueError("P14-DQ frozen policy bindings are incomplete")
        if tuple(item.root_id for item in self.roots) != ("root-A", "root-B"):
            raise ValueError("P14-DQ requires independent root-A and root-B evidence")
        if self.principal_hash_summary != p14dq_principal_hash_summary(self.roots):
            raise ValueError("P14-DQ principal hash summary does not match its roots")
        if p14dq_root_principal_payload(self.roots[0]) != p14dq_root_principal_payload(
            self.roots[1]
        ):
            raise ValueError("P14-DQ independent roots produced different principal evidence")
        if self.p14d_negative_case_count != len(P14D_NEGATIVE_CASES) * len(self.roots):
            raise ValueError("P14-DQ P14d negative-case count does not cover both roots")
        if self.p14dq_negative_case_count != len(P14DQ_NEGATIVE_CASES) * len(self.roots):
            raise ValueError("P14-DQ data-qualified negative-case count does not cover both roots")
        if self.restart_case_count != len(P14DQ_RESTART_CASES) * len(self.roots):
            raise ValueError("P14-DQ restart-case count does not cover both roots")
        required_files = {
            "code-provenance.json",
            "runtime-fingerprint.json",
            "frozen/uv.lock",
            "frozen/p14-dq-qualification-contract.md",
            "external/snapshot-manifest.json",
            "external/snapshot-quality-report.json",
            "external/qlib-view-manifest.json",
            "external/qlib-view-spec.json",
            "external/upstream-release-report.json",
            "root-A/root-evidence.json",
            "root-B/root-evidence.json",
        }
        if not required_files.issubset({item.logical_path for item in self.files}):
            raise ValueError("P14-DQ qualification bundle omits a frozen evidence file")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_construct(_fields_set=None, qualification_hash="0" * 64, **values)
        return cls(qualification_hash=provisional.content_hash, **values)  # type: ignore[arg-type]


__all__ = [
    "P14DQ_ADMISSIBLE_SOFT_REJECTION_GATES",
    "P14DQ_ADMISSIBLE_SOFT_REJECTION_REASON",
    "P14DQ_CANDIDATE_HASHES",
    "P14DQ_CANDIDATE_MANIFEST_HASH",
    "P14DQ_FAMILY_HASH",
    "P14DQ_FROZEN_VALIDATION_GATE_ORDER",
    "P14DQ_FROZEN_VALIDATION_GATE_SEVERITY",
    "P14DQ_LIMITATIONS",
    "P14DQ_NEGATIVE_CASES",
    "P14DQ_REQUIRED_PASSING_GATES",
    "P14DQ_RESTART_CASES",
    "P14DQ_SNAPSHOT_HASH",
    "P14DQ_TEMPLATE_HASH",
    "P14DQ_UPSTREAM_RELEASE_REPORT_HASH",
    "P14DQ_VIEW_HASH",
    "P14DQ_VIEW_SPEC_HASH",
    "P14dqCampaignEvidence",
    "P14dqCandidateEvaluation",
    "P14dqExternalBindings",
    "P14dqNamedHash",
    "P14dqNegativeCaseEvidence",
    "P14dqQualificationAttempt",
    "P14dqQualificationFile",
    "P14dqQualificationReport",
    "P14dqReplayCaseEvidence",
    "P14dqRestartCaseEvidence",
    "P14dqRootEvidence",
    "P14dqValidationGateEvidence",
    "p14dq_principal_hash_summary",
    "p14dq_root_principal_hash",
    "p14dq_root_principal_payload",
]
