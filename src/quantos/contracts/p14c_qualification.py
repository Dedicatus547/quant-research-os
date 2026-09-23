"""Immutable evidence contracts for the P14c clean-commit qualification."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign_selection import CampaignSelectionVerdict
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict

P14C_CANONICAL_CASES = ("SELECTED", "NO_SELECTION", "FAILED_NOT_EVALUATED")
P14C_NEGATIVE_CASES = (
    "ARTIFACT_EXACT_FILE_SET_VIOLATION",
    "CAMPAIGN_HASH_MISMATCH",
    "CANDIDATE_EXPRESSION_FINGERPRINT_MISMATCH",
    "FORGED_ADJUSTED_P_VALUE",
    "FORGED_CANDIDATE_SCORE",
    "FORGED_RAW_P_VALUE",
    "FORGED_SELECTED_CANDIDATE",
    "FAMILY_HASH_MISMATCH",
    "INCOMPLETE_CANDIDATE_DENOMINATOR",
    "INSUFFICIENT_VALIDATION_SESSIONS",
    "INVALID_RANK_IC_SERIES",
    "MALFORMED_VALIDATION_CALENDAR",
    "MANIFEST_HASH_MISMATCH",
    "MISSING_CANDIDATE_DISPOSITION",
    "MISSING_RANK_IC_SERIES",
    "MISSING_TRIAL_ACCOUNTING",
    "MODIFIED_CAMPAIGN_SELECTION_PLAN",
    "MODIFIED_CAMPAIGN_SELECTION_REPORT",
    "MISSING_TRIAL_RESULT_BINDING",
    "NONFINITE_RANK_IC",
    "NO_SELECTION_SEALED_CONFIRMATION_DENIED",
    "NOT_EVALUATED_SEALED_CONFIRMATION_DENIED",
    "POST_FREEZE_DEVELOPMENT_TRIAL_DENIED",
    "POST_FREEZE_VALIDATION_TRIAL_DENIED",
    "RANK_IC_OUT_OF_RANGE",
    "REPEATED_CANDIDATE_VALIDATION",
    "RESULT_OUTSIDE_VALIDATION_SEGMENT",
    "RESULT_REUSED_ACROSS_CANDIDATES",
    "SELECTED_CANDIDATE_OOS_MISMATCH",
    "SELF_REPORTED_SELECTION_FREEZE_DENIED",
    "VALIDATION_CALENDAR_MISMATCH",
    "CAMPAIGN_BUDGET_FAMILY_BINDING_MISMATCH",
    "UNVERIFIED_SELECTION_REPORT_FREEZE_DENIED",
)

P14C_LIMITATIONS = (
    "CIRCULAR_BLOCK_BOOTSTRAP_STATIONARITY_NOT_MARKET_VALIDATED",
    "MUTATION_CROSSOVER_NOT_AUTHORIZED",
    "NO_VENDOR_VINTAGE_PIT_QUALIFICATION",
    "P14D_AUTONOMOUS_CAMPAIGN_NOT_AUTHORIZED",
    "REAL_MARKET_RETURN_CLAIM_NOT_ESTABLISHED",
    "STRATEGY_PROFITABILITY_NOT_ESTABLISHED",
    "SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE",
    "UNDECLARED_ADAPTIVE_VALIDATION_REUSE_NOT_PREVENTED",
)


class P14cNamedHash(CanonicalContract):
    schema_version: Literal["p14c-named-hash/v1"] = "p14c-named-hash/v1"
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_/-]*$")
    sha256: str = Field(pattern=SHA256_PATTERN)


class P14cQualificationFile(CanonicalContract):
    schema_version: Literal["p14c-qualification-file/v1"] = "p14c-qualification-file/v1"
    logical_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class P14cCanonicalCaseResult(CanonicalContract):
    schema_version: Literal["p14c-canonical-case-result/v1"] = "p14c-canonical-case-result/v1"
    case_id: Literal["SELECTED", "NO_SELECTION", "FAILED_NOT_EVALUATED"]
    run_status: RunStatus
    verdict: CampaignSelectionVerdict
    reason_code: ReasonCode | None = None
    selected_candidate_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    selection_plan_hash: str = Field(pattern=SHA256_PATTERN)
    selection_report_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def outcome_matches_case(self) -> Self:
        expected = {
            "SELECTED": (RunStatus.SUCCEEDED, CampaignSelectionVerdict.SELECTED, None),
            "NO_SELECTION": (RunStatus.SUCCEEDED, CampaignSelectionVerdict.NO_SELECTION, None),
            "FAILED_NOT_EVALUATED": (
                RunStatus.FAILED,
                CampaignSelectionVerdict.NOT_EVALUATED,
                ReasonCode.ARTIFACT_CORRUPTED,
            ),
        }[self.case_id]
        if (self.run_status, self.verdict, self.reason_code) != expected:
            raise ValueError("P14c canonical outcome does not match its frozen case")
        if (self.case_id == "SELECTED") != (self.selected_candidate_hash is not None):
            raise ValueError("only the SELECTED case may carry a selected candidate")
        return self


class P14cRootCaseEvidence(CanonicalContract):
    schema_version: Literal["p14c-root-case-evidence/v1"] = "p14c-root-case-evidence/v1"
    outcome: P14cCanonicalCaseResult
    candidate_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_accounting_hash: str = Field(pattern=SHA256_PATTERN)
    research_result_hashes: tuple[str, ...]
    event_hashes: tuple[str, ...]
    event_chain_hash: str = Field(pattern=SHA256_PATTERN)
    selection_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    principal_hashes: tuple[P14cNamedHash, ...]

    @field_validator("research_result_hashes")
    @classmethod
    def hashes_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("P14c root evidence hashes must be sorted and unique")
        return value

    @field_validator("event_hashes")
    @classmethod
    def event_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("P14c event hashes must be unique")
        return value

    @field_validator("principal_hashes")
    @classmethod
    def principal_hashes_are_complete(
        cls, value: tuple[P14cNamedHash, ...]
    ) -> tuple[P14cNamedHash, ...]:
        names = tuple(item.name for item in value)
        required = (
            "campaign_selection_plan",
            "candidate_accounting",
            "candidate_manifest",
            "campaign_selection_report",
            "event_chain",
            "research_results_set",
        )
        if names != required:
            raise ValueError("P14c root principal hash summary is incomplete or unordered")
        return value

    @model_validator(mode="after")
    def principal_bindings_match_fields(self) -> Self:
        hashes = {item.name: item.sha256 for item in self.principal_hashes}
        if (
            hashes["campaign_selection_plan"] != self.outcome.selection_plan_hash
            or hashes["campaign_selection_report"] != self.outcome.selection_report_hash
            or hashes["candidate_manifest"] != self.candidate_manifest_hash
            or hashes["candidate_accounting"] != self.candidate_accounting_hash
            or hashes["event_chain"] != self.event_chain_hash
            or hashes["research_results_set"]
            != sha256_bytes(canonical_json_bytes(self.research_result_hashes))
        ):
            raise ValueError("P14c principal hash summary does not match case evidence")
        if (self.outcome.case_id == "SELECTED") != (self.selection_event_hash is not None):
            raise ValueError("only selected root evidence may carry SelectionFrozen")
        if (
            self.selection_event_hash is not None
            and self.selection_event_hash not in self.event_hashes
        ):
            raise ValueError("selection event hash is absent from the event chain")
        return self


class P14cNegativeCaseEvidence(CanonicalContract):
    schema_version: Literal["p14c-negative-case-evidence/v1"] = "p14c-negative-case-evidence/v1"
    case_id: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    input_hash: str = Field(pattern=SHA256_PATTERN)
    outcome_hash: str = Field(pattern=SHA256_PATTERN)
    reason_code: ReasonCode

    @model_validator(mode="after")
    def case_is_frozen(self) -> Self:
        if self.case_id not in P14C_NEGATIVE_CASES:
            raise ValueError("unknown frozen P14c negative case")
        return self


class P14cRootEvidence(CanonicalContract):
    schema_version: Literal["p14c-root-evidence/v1"] = "p14c-root-evidence/v1"
    root_id: Literal["root-A", "root-B"]
    input_fixture_hash: str = Field(pattern=SHA256_PATTERN)
    cases: tuple[P14cRootCaseEvidence, ...]
    negative_case_ids: tuple[str, ...]
    negative_cases: tuple[P14cNegativeCaseEvidence, ...]

    @model_validator(mode="after")
    def root_case_sets_are_complete(self) -> Self:
        case_ids = tuple(item.outcome.case_id for item in self.cases)
        if case_ids != P14C_CANONICAL_CASES:
            raise ValueError("P14c root must contain all canonical cases in frozen order")
        if self.negative_case_ids != P14C_NEGATIVE_CASES:
            raise ValueError("P14c root must execute the complete frozen negative case set")
        if tuple(item.case_id for item in self.negative_cases) != P14C_NEGATIVE_CASES:
            raise ValueError("P14c root negative evidence is incomplete or unordered")
        return self


def p14c_principal_hash_summary(roots: tuple[P14cRootEvidence, ...]) -> str:
    """Hash the ordered per-case principal evidence from both qualification roots."""

    summary = tuple(
        (
            root.root_id,
            tuple(
                (
                    case.outcome.case_id,
                    case.selection_event_hash,
                    tuple((item.name, item.sha256) for item in case.principal_hashes),
                )
                for case in root.cases
            ),
        )
        for root in roots
    )
    return sha256_bytes(canonical_json_bytes(summary))


class P14cQualificationReport(CanonicalContract):
    """Hash-addressed result of the clean-commit independent-root qualification."""

    schema_version: Literal["p14c-qualification-report/v1"] = "p14c-qualification-report/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"qualification_hash"})

    qualification_hash: str = Field(pattern=SHA256_PATTERN)
    status: Literal[RunStatus.SUCCEEDED] = RunStatus.SUCCEEDED
    verdict: Literal[ValidationVerdict.PASS] = ValidationVerdict.PASS
    implementation_commit_hash: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_provenance_hash: str = Field(pattern=SHA256_PATTERN)
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    policy_hashes: tuple[P14cNamedHash, ...]
    fixture_hash: str = Field(pattern=SHA256_PATTERN)
    principal_hash_summary: str = Field(pattern=SHA256_PATTERN)
    roots: tuple[P14cRootEvidence, ...]
    principal_hashes_byte_exact: Literal[True] = True
    negative_case_count: int = Field(ge=len(P14C_NEGATIVE_CASES))
    limitations: tuple[str, ...]
    files: tuple[P14cQualificationFile, ...]

    @field_validator("policy_hashes")
    @classmethod
    def policies_are_ordered(cls, value: tuple[P14cNamedHash, ...]) -> tuple[P14cNamedHash, ...]:
        if tuple(item.name for item in value) != (
            "p14c_contract",
            "multiple_testing_policy",
            "research_policy",
            "selection_policy",
        ):
            raise ValueError("P14c frozen policy bindings are incomplete or unordered")
        return value

    @field_validator("limitations")
    @classmethod
    def limitations_are_complete(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != P14C_LIMITATIONS:
            raise ValueError("P14c qualification limitations must match the frozen boundary")
        return value

    @field_validator("files")
    @classmethod
    def files_are_ordered_unique(
        cls, value: tuple[P14cQualificationFile, ...]
    ) -> tuple[P14cQualificationFile, ...]:
        paths = tuple(item.logical_path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("P14c qualification files must be sorted and unique")
        return value

    @model_validator(mode="after")
    def qualification_is_bound_and_reproducible(self) -> Self:
        if self.qualification_hash != self.content_hash:
            raise ValueError("P14c qualification hash does not match report content")
        if tuple(item.root_id for item in self.roots) != ("root-A", "root-B"):
            raise ValueError("P14c qualification requires root-A and root-B evidence")
        if self.principal_hash_summary != p14c_principal_hash_summary(self.roots):
            raise ValueError("P14c principal hash summary does not match its root evidence")
        if any(item.input_fixture_hash != self.fixture_hash for item in self.roots):
            raise ValueError("P14c roots do not bind the frozen synthetic fixture")
        if self.negative_case_count != len(P14C_NEGATIVE_CASES) * len(self.roots):
            raise ValueError("P14c negative-case count does not match both roots")
        left_cases, right_cases = self.roots[0].cases, self.roots[1].cases
        for left, right in zip(left_cases, right_cases, strict=True):
            if left != right:
                raise ValueError("P14c independent roots produced different principal evidence")
        if self.roots[0].negative_cases != self.roots[1].negative_cases:
            raise ValueError("P14c independent roots produced different negative-case evidence")
        required_files = {
            "code-provenance.json",
            "frozen/uv.lock",
            "runtime-fingerprint.json",
        }
        actual = {item.logical_path for item in self.files}
        if not required_files.issubset(actual):
            raise ValueError("P14c qualification provenance files are missing")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {"schema_version": "p14c-qualification-report/v1", **values}
        digest = sha256_bytes(canonical_json_bytes(payload))
        return cls(qualification_hash=digest, **values)  # type: ignore[arg-type]
