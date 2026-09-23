"""Immutable evidence contracts for the P14d clean-commit double-root qualification."""

from __future__ import annotations

from typing import ClassVar, Literal, Self, cast

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from quantos.contracts.autonomous import AutonomousLoopState
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict

P14D_CANONICAL_CASES = ("SELECTED", "NO_SELECTION", "FAILED_NOT_EVALUATED")
P14D_NEGATIVE_CASES = (
    "BUDGET_EXHAUSTION",
    "CANDIDATE_AST_MISMATCH",
    "CANDIDATE_FINGERPRINT_MISMATCH",
    "CANDIDATE_HASH_MISMATCH",
    "CONFLICTING_EXECUTION_RETRY",
    "CONFLICTING_TRIAL_IDENTITY",
    "DUPLICATE_PROPOSAL",
    "EXECUTION_FAILURE",
    "INVALID_PROPOSAL_SCHEMA",
    "LEDGER_CHAIN_CORRUPTION",
    "MANIFEST_DRIFT",
    "MAX_AGENT_RUNS",
    "MAX_TRIALS",
    "P14C_REPORT_TAMPER",
    "PIT_LOOK_AHEAD_REJECTION",
    "POLICY_MISMATCH",
    "QLIB_VIEW_MISMATCH",
    "SELECTION_MISMATCH",
    "SNAPSHOT_MISMATCH",
    "STALE_CONTEXTPACK",
    "STALE_LEDGER_SNAPSHOT",
    "TAMPERED_AGENT_EXCHANGE",
    "TAMPERED_EXECUTION_RECEIPT",
    "TAMPERED_REPLAY_ARTIFACT",
    "TAMPERED_RESEARCH_RESULT",
    "TAMPERED_VALIDATION_REPORT",
    "UNKNOWN_CANDIDATE",
)
P14D_RESTART_CASES = (
    "AGENT_EXCHANGE_AND_EXECUTION_RECEIPT_BEFORE_TRIAL",
    "CAMPAIGN_TRIAL_COMMITTED_LEDGER_RECONCILIATION_INCOMPLETE",
    "P14C_REPORT_PUBLISHED_SELECTION_EVENT_NOT_COMMITTED",
)
P14D_LIMITATIONS = (
    "FR03_REMAINS_NO_GO",
    "LIVE_AGENT_RUNTIME_NOT_QUALIFIED",
    "NO_HISTORICAL_VENDOR_VINTAGE_PIT_CLAIM",
    "NO_MARKET_ALPHA_OR_PROFITABILITY_CLAIM",
    "NO_SEALED_CONFIRMATION_QUALIFICATION",
    "SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE",
)


class P14dNamedHash(CanonicalContract):
    schema_version: Literal["p14d-named-hash/v1"] = "p14d-named-hash/v1"
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_/-]*$")
    sha256: str = Field(pattern=SHA256_PATTERN)


class P14dQualificationFile(CanonicalContract):
    schema_version: Literal["p14d-qualification-file/v1"] = "p14d-qualification-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class P14dCaseEvidence(CanonicalContract):
    """Deterministic principal evidence for one canonical autonomous campaign case."""

    schema_version: Literal["p14d-case-evidence/v1"] = "p14d-case-evidence/v1"
    case_id: Literal["SELECTED", "NO_SELECTION", "FAILED_NOT_EVALUATED"]
    fixture_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    initial_context_pack_hash: str = Field(pattern=SHA256_PATTERN)
    agent_request_hashes: tuple[str, ...]
    agent_proposal_hashes: tuple[str, ...]
    execution_request_hashes: tuple[str, ...]
    execution_identities: tuple[str, ...]
    research_result_hashes: tuple[str, ...]
    validation_report_hashes: tuple[str, ...]
    campaign_trial_hashes: tuple[str, ...]
    campaign_event_hashes: tuple[str, ...]
    final_campaign_event_hash: str = Field(pattern=SHA256_PATTERN)
    final_ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_principal_hash: str = Field(pattern=SHA256_PATTERN)
    selection_report_hash: str = Field(pattern=SHA256_PATTERN)
    selection_frozen_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    autonomous_loop_report_hash: str = Field(pattern=SHA256_PATTERN)
    loop_state: AutonomousLoopState
    trial_outcomes: tuple[TrialOutcome, ...]
    case_summary_hash: str = Field(pattern=SHA256_PATTERN)

    @field_validator(
        "agent_request_hashes",
        "agent_proposal_hashes",
        "execution_request_hashes",
        "execution_identities",
        "campaign_trial_hashes",
        "campaign_event_hashes",
    )
    @classmethod
    def history_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("P14d case history hashes must be unique")
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("P14d case authority hash is invalid")
        return value

    @field_validator("research_result_hashes", "validation_report_hashes")
    @classmethod
    def result_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("P14d ResearchResult and ValidationReport hashes must be sorted")
        if any(
            len(item) != 64 or any(character not in "0123456789abcdef" for character in item)
            for item in value
        ):
            raise ValueError("P14d case authority hash is invalid")
        return value

    @model_validator(mode="after")
    def case_evidence_is_complete(self) -> Self:
        if len(self.agent_request_hashes) != len(self.agent_proposal_hashes):
            raise ValueError("P14d Agent request and proposal histories disagree")
        if self.final_campaign_event_hash != self.campaign_event_hashes[-1]:
            raise ValueError("P14d final campaign event hash is not the chain head")
        if len(self.execution_request_hashes) != len(self.execution_identities):
            raise ValueError("P14d execution request and identity histories disagree")
        if len(self.research_result_hashes) != len(self.validation_report_hashes):
            raise ValueError("P14d ResearchResult and ValidationReport histories disagree")
        if (self.case_id == "SELECTED") != (self.selection_frozen_event_hash is not None):
            raise ValueError("only the SELECTED case may carry SelectionFrozen")
        expected_state = {
            "SELECTED": AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION,
            "NO_SELECTION": AutonomousLoopState.SELECTION_COMPLETE,
            "FAILED_NOT_EVALUATED": AutonomousLoopState.SELECTION_COMPLETE,
        }[self.case_id]
        if self.loop_state is not expected_state:
            raise ValueError("P14d canonical case loop state does not match its frozen outcome")
        if self.case_id == "NO_SELECTION" and TrialOutcome.PASS not in self.trial_outcomes:
            raise ValueError("NO_SELECTION case requires a successful real execution")
        if self.case_id == "FAILED_NOT_EVALUATED" and TrialOutcome.PASS in self.trial_outcomes:
            raise ValueError("FAILED_NOT_EVALUATED case cannot contain fabricated success")
        if self.case_summary_hash != p14d_case_summary_hash(self):
            raise ValueError("P14d case summary hash does not match case evidence")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {"schema_version": "p14d-case-evidence/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(case_summary_hash=digest, **values)  # type: ignore[arg-type]


def p14d_case_summary_hash(case: P14dCaseEvidence) -> str:
    payload = case.model_dump(
        mode="python",
        exclude={"case_summary_hash"},
    )
    return sha256_bytes(canonical_json_bytes(payload))


class P14dNegativeCaseEvidence(CanonicalContract):
    schema_version: Literal["p14d-negative-case-evidence/v1"] = "p14d-negative-case-evidence/v1"
    case_id: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    input_hash: str = Field(pattern=SHA256_PATTERN)
    outcome_hash: str = Field(pattern=SHA256_PATTERN)
    reason_code: ReasonCode

    @model_validator(mode="after")
    def case_is_frozen(self) -> Self:
        if self.case_id not in P14D_NEGATIVE_CASES:
            raise ValueError("unknown frozen P14d negative case")
        return self


class P14dRestartCaseEvidence(CanonicalContract):
    schema_version: Literal["p14d-restart-case-evidence/v1"] = "p14d-restart-case-evidence/v1"
    case_id: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    input_hash: str = Field(pattern=SHA256_PATTERN)
    pre_restart_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    post_restart_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    duplicate_authority_absent: Literal[True] = True

    @model_validator(mode="after")
    def case_is_frozen(self) -> Self:
        if self.case_id not in P14D_RESTART_CASES:
            raise ValueError("unknown frozen P14d restart case")
        return self


class P14dReplayCaseEvidence(CanonicalContract):
    schema_version: Literal["p14d-replay-case-evidence/v1"] = "p14d-replay-case-evidence/v1"
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
            raise ValueError("P14d replay performed another Qlib execution")
        if self.prior_exchange_hash != p14d_replay_binding_hash(
            request_hash=self.request_hash,
            response_hash=self.response_hash,
            proposal_hash=self.proposal_hash,
            candidate_hash=self.candidate_hash,
            execution_identity=self.execution_identity,
        ):
            raise ValueError("P14d replay evidence is not canonically bound")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        prior_hash = p14d_replay_binding_hash(
            request_hash=cast(str, values["request_hash"]),
            response_hash=cast(str, values["response_hash"]),
            proposal_hash=cast(str, values["proposal_hash"]),
            candidate_hash=cast(str, values["candidate_hash"]),
            execution_identity=cast(str, values["execution_identity"]),
        )
        return cls(prior_exchange_hash=prior_hash, **values)  # type: ignore[arg-type]


def p14d_replay_binding_hash(
    *,
    request_hash: str,
    response_hash: str,
    proposal_hash: str,
    candidate_hash: str,
    execution_identity: str,
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "candidate_hash": candidate_hash,
                "execution_identity": execution_identity,
                "proposal_hash": proposal_hash,
                "request_hash": request_hash,
                "response_hash": response_hash,
            }
        )
    )


class P14dRootEvidence(CanonicalContract):
    schema_version: Literal["p14d-root-evidence/v1"] = "p14d-root-evidence/v1"
    root_id: Literal["root-A", "root-B"]
    fixture_set_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_binding_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_campaign_policy_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_agent_run_policy_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_compute_accounting_hash: str = Field(pattern=SHA256_PATTERN)
    autonomous_execution_bindings_hash: str = Field(pattern=SHA256_PATTERN)
    p14c_selection_plan_hash: str = Field(pattern=SHA256_PATTERN)
    cases: tuple[P14dCaseEvidence, ...]
    negative_case_ids: tuple[str, ...]
    negative_cases: tuple[P14dNegativeCaseEvidence, ...]
    restart_case_ids: tuple[str, ...]
    restart_cases: tuple[P14dRestartCaseEvidence, ...]
    replay_case: P14dReplayCaseEvidence
    principal_hash_summary: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def root_evidence_is_complete(self) -> Self:
        if tuple(item.case_id for item in self.cases) != P14D_CANONICAL_CASES:
            raise ValueError("P14d root must contain all canonical cases in frozen order")
        if self.negative_case_ids != P14D_NEGATIVE_CASES:
            raise ValueError("P14d root must execute the complete frozen negative case set")
        if tuple(item.case_id for item in self.negative_cases) != P14D_NEGATIVE_CASES:
            raise ValueError("P14d root negative evidence is incomplete or unordered")
        if self.restart_case_ids != P14D_RESTART_CASES:
            raise ValueError("P14d root must execute the complete frozen restart case set")
        if tuple(item.case_id for item in self.restart_cases) != P14D_RESTART_CASES:
            raise ValueError("P14d root restart evidence is incomplete or unordered")
        if self.principal_hash_summary != p14d_root_principal_hash(self):
            raise ValueError("P14d root principal hash summary does not match its evidence")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_construct(
            _fields_set=None, principal_hash_summary="0" * 64, **values
        )
        digest = p14d_root_principal_hash(provisional)
        return cls(principal_hash_summary=digest, **values)  # type: ignore[arg-type]


def p14d_root_principal_payload(root: P14dRootEvidence) -> object:
    return {
        "autonomous_agent_run_policy_hash": root.autonomous_agent_run_policy_hash,
        "autonomous_campaign_policy_hash": root.autonomous_campaign_policy_hash,
        "autonomous_compute_accounting_hash": root.autonomous_compute_accounting_hash,
        "autonomous_execution_bindings_hash": root.autonomous_execution_bindings_hash,
        "cases": tuple(item.model_dump(mode="python") for item in root.cases),
        "fixture_set_hash": root.fixture_set_hash,
        "negative_cases": tuple(item.model_dump(mode="python") for item in root.negative_cases),
        "p14c_selection_plan_hash": root.p14c_selection_plan_hash,
        "qlib_binding_hash": root.qlib_binding_hash,
        "replay_case": root.replay_case.model_dump(mode="python"),
        "restart_cases": tuple(item.model_dump(mode="python") for item in root.restart_cases),
    }


def p14d_root_principal_hash(root: P14dRootEvidence) -> str:
    return sha256_bytes(canonical_json_bytes(p14d_root_principal_payload(root)))


def p14d_principal_hash_summary(roots: tuple[P14dRootEvidence, ...]) -> str:
    if tuple(root.root_id for root in roots) != ("root-A", "root-B"):
        raise ValueError("P14d principal summary requires root-A and root-B in order")
    return sha256_bytes(
        canonical_json_bytes(tuple(p14d_root_principal_payload(root) for root in roots))
    )


class P14dQualificationReport(CanonicalContract):
    """Hash-addressed result of the clean-commit independent double-root P14d qualification."""

    schema_version: Literal["p14d-qualification-report/v1"] = "p14d-qualification-report/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"qualification_hash"})

    qualification_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal[RunStatus.SUCCEEDED] = RunStatus.SUCCEEDED
    verdict: Literal[ValidationVerdict.PASS] = ValidationVerdict.PASS
    implementation_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_provenance_hash: str = Field(pattern=SHA256_PATTERN)
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    qualification_contract_hash: str = Field(pattern=SHA256_PATTERN)
    qlib_binding_hash: str = Field(pattern=SHA256_PATTERN)
    fixture_set_hash: str = Field(pattern=SHA256_PATTERN)
    policy_hashes: tuple[P14dNamedHash, ...]
    roots: tuple[P14dRootEvidence, ...]
    principal_hash_summary: str = Field(pattern=SHA256_PATTERN)
    principal_hashes_byte_exact: Literal[True] = True
    negative_case_count: int = Field(ge=len(P14D_NEGATIVE_CASES))
    restart_case_count: int = Field(ge=len(P14D_RESTART_CASES))
    limitations: tuple[str, ...]
    files: tuple[P14dQualificationFile, ...]

    @field_validator("policy_hashes")
    @classmethod
    def policies_are_ordered(cls, value: tuple[P14dNamedHash, ...]) -> tuple[P14dNamedHash, ...]:
        names = tuple(item.name for item in value)
        if len(names) != len(set(names)) or names != tuple(sorted(set(names))):
            raise ValueError("P14d policy hashes must be sorted and unique")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_complete(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != P14D_LIMITATIONS:
            raise ValueError("P14d qualification limitations must match the frozen boundary")
        return value

    @field_validator("files")
    @classmethod
    def files_are_ordered_unique(
        cls, value: tuple[P14dQualificationFile, ...]
    ) -> tuple[P14dQualificationFile, ...]:
        paths = tuple(item.logical_path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("P14d qualification files must be sorted and unique")
        return value

    @model_validator(mode="after")
    def qualification_is_bound_and_reproducible(self) -> Self:
        if self.qualification_hash != self.content_hash:
            raise ValueError("P14d qualification hash does not match report content")
        if tuple(item.root_id for item in self.roots) != ("root-A", "root-B"):
            raise ValueError("P14d qualification requires root-A and root-B evidence")
        if self.principal_hash_summary != p14d_principal_hash_summary(self.roots):
            raise ValueError("P14d principal hash summary does not match root evidence")
        if any(item.fixture_set_hash != self.fixture_set_hash for item in self.roots):
            raise ValueError("P14d roots do not bind the same frozen fixture set")
        if any(item.qlib_binding_hash != self.qlib_binding_hash for item in self.roots):
            raise ValueError("P14d roots do not bind the same Qlib source release")
        left, right = self.roots
        if (
            p14d_root_principal_payload(left) != p14d_root_principal_payload(right)
            or left.principal_hash_summary != right.principal_hash_summary
        ):
            raise ValueError("P14d independent roots produced different principal evidence")
        if self.negative_case_count != len(P14D_NEGATIVE_CASES) * len(self.roots):
            raise ValueError("P14d negative-case count does not match both roots")
        if self.restart_case_count != len(P14D_RESTART_CASES) * len(self.roots):
            raise ValueError("P14d restart-case count does not match both roots")
        required_policy_names = {
            "autonomous_agent_run_policy",
            "autonomous_campaign_policy",
            "autonomous_compute_accounting",
            "autonomous_execution_bindings",
            "p14d_qualification_contract",
        }
        if not required_policy_names.issubset({item.name for item in self.policy_hashes}):
            raise ValueError("P14d frozen policy bindings are incomplete")
        required_files = {
            "code-provenance.json",
            "frozen/uv.lock",
            "runtime-fingerprint.json",
            "frozen/p14d-qualification-contract.md",
        }
        actual = {item.logical_path for item in self.files}
        if not required_files.issubset(actual):
            raise ValueError("P14d qualification provenance files are missing")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_construct(_fields_set=None, qualification_hash="0" * 64, **values)
        digest = provisional.content_hash
        return cls(qualification_hash=digest, **values)  # type: ignore[arg-type]


__all__ = [
    "P14D_CANONICAL_CASES",
    "P14D_LIMITATIONS",
    "P14D_NEGATIVE_CASES",
    "P14D_RESTART_CASES",
    "P14dCaseEvidence",
    "P14dNamedHash",
    "P14dNegativeCaseEvidence",
    "P14dQualificationFile",
    "P14dQualificationReport",
    "P14dReplayCaseEvidence",
    "P14dRestartCaseEvidence",
    "P14dRootEvidence",
    "p14d_case_summary_hash",
    "p14d_principal_hash_summary",
    "p14d_replay_binding_hash",
    "p14d_root_principal_hash",
]
