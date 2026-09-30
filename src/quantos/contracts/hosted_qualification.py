"""Pure, immutable evidence indexes for host-mediated qualification."""

from __future__ import annotations

from typing import Literal, Self, cast

from pydantic import Field, NonNegativeInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path

HOSTED_QUALIFICATION_CASES: tuple[str, ...] = tuple(f"Q{index:02d}" for index in range(1, 13))
HOSTED_CONTRACT_SHA256 = "14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df"
HOSTED_ACCEPTANCE_SHA256 = "e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e"
HOSTED_FREEZE_SHA256 = "ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e"


class HostedQualificationFile(CanonicalContract):
    schema_version: Literal["hosted-qualification-file/v1"] = "hosted-qualification-file/v1"
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class HostedQualificationRoot(CanonicalContract):
    """One independently inventoried authority root, never an asserted verdict."""

    schema_version: Literal["hosted-qualification-root/v1"] = "hosted-qualification-root/v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    logical_path: str
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    raw_inventory_path: str

    @field_validator("logical_path", "raw_inventory_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class HostedQualificationCase(CanonicalContract):
    """Evidence index only. A producer cannot set a case verdict."""

    schema_version: Literal["hosted-qualification-case/v1"] = "hosted-qualification-case/v1"
    case_id: str
    roots: tuple[HostedQualificationRoot, ...] = ()
    evidence_paths: tuple[str, ...] = ()

    @field_validator("evidence_paths")
    @classmethod
    def evidence_paths_are_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("case evidence paths must be sorted unique")
        for path in value:
            validate_logical_path(path)
        return value

    @model_validator(mode="after")
    def case_bindings(self) -> Self:
        if self.case_id not in HOSTED_QUALIFICATION_CASES:
            raise ValueError("unknown hosted qualification case")
        if len({root.name for root in self.roots}) != len(self.roots):
            raise ValueError("case roots must have unique names")
        return self


class HostedRawInventory(CanonicalContract):
    schema_version: Literal["hosted-raw-inventory/v1"] = "hosted-raw-inventory/v1"
    files: tuple[HostedQualificationFile, ...]

    @field_validator("files")
    @classmethod
    def files_are_sorted(
        cls, value: tuple[HostedQualificationFile, ...]
    ) -> tuple[HostedQualificationFile, ...]:
        paths = tuple(item.logical_path for item in value)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("raw inventory files must be sorted unique")
        return value


class HostedManagerExportFile(CanonicalContract):
    """Exact bundle bytes mapped to a file in the independently supplied manager root."""

    schema_version: Literal["hosted-manager-export-file/v1"] = "hosted-manager-export-file/v1"
    bundle_path: str
    source_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: NonNegativeInt

    @field_validator("bundle_path", "source_path")
    @classmethod
    def paths_are_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class HostedManagerExport(CanonicalContract):
    """Source mapping, never a producer verdict or a substitute for original bytes."""

    schema_version: Literal["hosted-manager-export/v1"] = "hosted-manager-export/v1"
    deployment_profile_hash: str = Field(pattern=SHA256_PATTERN)
    exact_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: tuple[HostedManagerExportFile, ...]

    @field_validator("files")
    @classmethod
    def files_are_exact(
        cls, value: tuple[HostedManagerExportFile, ...]
    ) -> tuple[HostedManagerExportFile, ...]:
        paths = tuple(item.bundle_path for item in value)
        if not paths or paths != tuple(sorted(set(paths))):
            raise ValueError("manager export files must be nonempty, sorted and unique")
        if {"manager-export.json", "qualification-manifest.json", "verifier-result.json"} & set(
            paths
        ):
            raise ValueError("manager export cannot bind its own or derived verifier authority")
        return value


class HostedPrincipalProjection(CanonicalContract):
    schema_version: Literal["hosted-principal-projection/v1"] = "hosted-principal-projection/v1"
    logical_path: str
    authority_schema: str
    root_a_raw_hash: str = Field(pattern=SHA256_PATTERN)
    root_b_raw_hash: str = Field(pattern=SHA256_PATTERN)
    projected_hash: str = Field(pattern=SHA256_PATTERN)

    @field_validator("logical_path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)


class HostedQualificationGate(CanonicalContract):
    schema_version: Literal["hosted-qualification-gate/v1"] = "hosted-qualification-gate/v1"
    case_id: str
    verdict: Literal["PASS", "FAIL", "NOT_EVALUATED"]
    reason: str = Field(min_length=1, max_length=300)
    checked_artifact_hashes: tuple[str, ...] = ()

    @field_validator("checked_artifact_hashes")
    @classmethod
    def hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("checked hashes must be sorted unique")
        for digest in value:
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("checked artifact identity is invalid")
        return value


class HostedQualificationVerification(CanonicalContract):
    schema_version: Literal["hosted-qualification-verification/v1"] = (
        "hosted-qualification-verification/v1"
    )
    gates: tuple[HostedQualificationGate, ...]
    eligibility: Literal["NOT_QUALIFIED", "ELIGIBLE_FOR_HM09_REVIEW"] = "NOT_QUALIFIED"

    @model_validator(mode="after")
    def exact_registry(self) -> Self:
        if tuple(gate.case_id for gate in self.gates) != HOSTED_QUALIFICATION_CASES:
            raise ValueError("hosted gate registry must be complete and ordered")
        eligible = all(gate.verdict == "PASS" for gate in self.gates)
        if (self.eligibility == "ELIGIBLE_FOR_HM09_REVIEW") != eligible:
            raise ValueError("hosted review eligibility differs from independently derived gates")
        return self


class HostedQualificationManifest(CanonicalContract):
    schema_version: Literal["hosted-qualification-manifest/v1"] = "hosted-qualification-manifest/v1"
    exact_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    lockfile_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    deployment_profile_hash: str = Field(pattern=SHA256_PATTERN)
    hosted_contract_hash: Literal[
        "14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df"
    ] = HOSTED_CONTRACT_SHA256
    hosted_acceptance_hash: Literal[
        "e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e"
    ] = HOSTED_ACCEPTANCE_SHA256
    hm02_freeze_hash: Literal[
        "ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e"
    ] = HOSTED_FREEZE_SHA256
    case_records: tuple[HostedQualificationCase, ...]
    verifier_result_hash: str = Field(pattern=SHA256_PATTERN)
    manager_export_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    failed_attempt_hashes: tuple[str, ...] = ()
    limitations: tuple[str, ...]
    files: tuple[HostedQualificationFile, ...]

    @field_validator("failed_attempt_hashes", mode="before")
    @classmethod
    def failed_attempt_hashes_are_valid(cls, value: object) -> object:
        import re

        if not isinstance(value, (list, tuple)):
            raise ValueError("failed attempts must use explicit SHA-256 hashes")
        if any(
            not isinstance(digest, str) or re.fullmatch(SHA256_PATTERN, digest) is None
            for digest in cast(list[object] | tuple[object, ...], value)
        ):
            raise ValueError("failed attempts must use explicit SHA-256 hashes")
        return cast(object, value)

    @model_validator(mode="after")
    def exact_registry_and_files(self) -> Self:
        if tuple(case.case_id for case in self.case_records) != HOSTED_QUALIFICATION_CASES:
            raise ValueError("hosted case registry must be complete and ordered")
        paths = tuple(item.logical_path for item in self.files)
        if paths != tuple(sorted(set(paths))) or "verifier-result.json" not in paths:
            raise ValueError("hosted qualification files must be exact and ordered")
        if "qualification-manifest.json" in paths:
            raise ValueError("manifest cannot inventory itself")
        if self.failed_attempt_hashes != tuple(sorted(set(self.failed_attempt_hashes))):
            raise ValueError("failed attempts must be sorted unique")
        return self

    @property
    def qualification_hash(self) -> str:
        return sha256_bytes(self.canonical_bytes())
