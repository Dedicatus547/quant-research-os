"""Frozen factor-template and deterministic finite-family enumeration contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes
from quantos.contracts.campaign import ParameterValue
from quantos.contracts.evidence import LOGICAL_ID_PATTERN
from quantos.contracts.pit import SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.refs import SHA256_PATTERN


class ResearchFactorTemplateNode(CanonicalContract):
    schema_version: Literal["research-factor-template-node/v1"] = "research-factor-template-node/v1"
    node_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    operator: SafeQlibOperator
    inputs: tuple[str, ...] = ()
    field_name: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    window: PositiveInt | None = None


class ResearchTemplateParameterSlot(CanonicalContract):
    schema_version: Literal["research-template-parameter-slot/v1"] = (
        "research-template-parameter-slot/v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    node_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    field: Literal["window"]


class ResearchFactorTemplateSpec(CanonicalContract):
    schema_version: Literal["research-factor-template/v1"] = "research-factor-template/v1"
    template_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    expression_schema_version: Literal["safe-qlib-expression/v1", "safe-qlib-expression/v2"]
    nodes: tuple[ResearchFactorTemplateNode, ...]
    output_node_id: str
    input_lag_trading_days: NonNegativeInt = 0
    parameter_slots: tuple[ResearchTemplateParameterSlot, ...]

    @model_validator(mode="after")
    def template_is_an_explicit_topological_dag(self) -> Self:
        slot_names = [item.name for item in self.parameter_slots]
        targets = [(item.node_id, item.field) for item in self.parameter_slots]
        if not slot_names or slot_names != sorted(set(slot_names)):
            raise ValueError("template parameter slots must be nonempty, sorted, and unique")
        if len(targets) != len(set(targets)):
            raise ValueError("each template field can bind at most one parameter slot")

        slot_by_node = {item.node_id: item for item in self.parameter_slots}
        known: set[str] = set()

        window_operators = {
            SafeQlibOperator.DELTA,
            SafeQlibOperator.REF,
            SafeQlibOperator.RETURN,
            SafeQlibOperator.ROLLING_MAX,
            SafeQlibOperator.ROLLING_MEAN,
            SafeQlibOperator.ROLLING_MIN,
            SafeQlibOperator.ROLLING_STD,
            SafeQlibOperator.ROLLING_SUM,
            SafeQlibOperator.RANK,
        }
        binary_operators = {
            SafeQlibOperator.ADD,
            SafeQlibOperator.DIVIDE,
            SafeQlibOperator.MULTIPLY,
            SafeQlibOperator.SUBTRACT,
        }
        v2_operators = {
            SafeQlibOperator.ABS,
            SafeQlibOperator.DELTA,
            SafeQlibOperator.ROLLING_MAX,
            SafeQlibOperator.ROLLING_MIN,
            SafeQlibOperator.ROLLING_SUM,
        }

        for node in self.nodes:
            if node.node_id in known or any(item not in known for item in node.inputs):
                raise ValueError("template nodes must be a topological DAG with unique IDs")
            known.add(node.node_id)
            slot = slot_by_node.get(node.node_id)
            if node.operator is SafeQlibOperator.FIELD:
                valid = node.field_name is not None and not node.inputs and node.window is None
            elif node.operator is SafeQlibOperator.ABS:
                valid = (
                    len(node.inputs) == 1
                    and node.field_name is None
                    and node.window is None
                    and slot is None
                )
            elif node.operator in window_operators:
                valid = (
                    len(node.inputs) == 1
                    and node.field_name is None
                    and (node.window is None) != (slot is None)
                )
            elif node.operator in binary_operators:
                valid = (
                    len(node.inputs) == 2
                    and node.field_name is None
                    and node.window is None
                    and slot is None
                )
            else:  # pragma: no cover - the enum is exhaustive today
                valid = False
            if not valid:
                raise ValueError("template node shape or parameter target is invalid")
        if not known or self.output_node_id not in known:
            raise ValueError("template output node must resolve")
        if set(slot_by_node) - known:
            raise ValueError("template parameter slot targets an unknown node")
        if self.expression_schema_version == "safe-qlib-expression/v1" and any(
            node.operator in v2_operators for node in self.nodes
        ):
            raise ValueError("DSL v2 operators require a v2 factor template")
        return self


class ResearchCandidateParameter(CanonicalContract):
    schema_version: Literal["research-candidate-parameter/v1"] = "research-candidate-parameter/v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: ParameterValue


class ResearchCandidateSpec(CanonicalContract):
    schema_version: Literal["research-candidate/v1"] = "research-candidate/v1"
    candidate_id: str = Field(pattern=r"^candidate-[0-9a-f]{64}$")
    family_hash: str = Field(pattern=SHA256_PATTERN)
    factor_template_hash: str = Field(pattern=SHA256_PATTERN)
    parameters: tuple[ResearchCandidateParameter, ...]
    expression: SafeQlibExpressionSpec
    exact_expression_hash: str = Field(pattern=SHA256_PATTERN)
    structural_expression_hash: str = Field(pattern=SHA256_PATTERN)

    @field_validator("parameters")
    @classmethod
    def parameters_are_sorted(
        cls, value: tuple[ResearchCandidateParameter, ...]
    ) -> tuple[ResearchCandidateParameter, ...]:
        names = [item.name for item in value]
        if not names or names != sorted(set(names)):
            raise ValueError("candidate parameters must be nonempty, sorted, and unique")
        return value


class CandidateDuplicateKind(StrEnum):
    EXACT = "EXACT"
    STRUCTURAL = "STRUCTURAL"


class CandidateDuplicateEvidence(CanonicalContract):
    schema_version: Literal["candidate-duplicate-evidence/v1"] = "candidate-duplicate-evidence/v1"
    kind: CandidateDuplicateKind
    fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    representative_candidate_hash: str = Field(pattern=SHA256_PATTERN)
    duplicate_candidate_hashes: tuple[str, ...]

    @field_validator("duplicate_candidate_hashes")
    @classmethod
    def duplicates_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not value
            or value != tuple(sorted(set(value)))
            or any(re.fullmatch(SHA256_PATTERN, item) is None for item in value)
        ):
            raise ValueError("duplicate candidate hashes must be nonempty, sorted, and unique")
        return value

    @model_validator(mode="after")
    def representative_is_not_a_duplicate(self) -> Self:
        if self.representative_candidate_hash in self.duplicate_candidate_hashes:
            raise ValueError("duplicate evidence representative cannot duplicate itself")
        return self


class CandidateEnumerationManifest(CanonicalContract):
    schema_version: Literal["candidate-enumeration-manifest/v1"] = (
        "candidate-enumeration-manifest/v1"
    )
    enumeration_policy_id: Literal["canonical-cartesian-v1"] = "canonical-cartesian-v1"
    family_hash: str = Field(pattern=SHA256_PATTERN)
    factor_template_hash: str = Field(pattern=SHA256_PATTERN)
    declared_candidate_count: PositiveInt
    candidates: tuple[ResearchCandidateSpec, ...]
    duplicate_evidence: tuple[CandidateDuplicateEvidence, ...]

    @field_validator("candidates")
    @classmethod
    def candidates_are_unique_and_ordered(
        cls, value: tuple[ResearchCandidateSpec, ...]
    ) -> tuple[ResearchCandidateSpec, ...]:
        keys = [canonical_json_bytes(item.parameters) for item in value]
        if keys != sorted(set(keys)):
            raise ValueError("enumerated candidates must use canonical parameter order")
        return value

    @field_validator("duplicate_evidence")
    @classmethod
    def duplicate_evidence_is_ordered(
        cls, value: tuple[CandidateDuplicateEvidence, ...]
    ) -> tuple[CandidateDuplicateEvidence, ...]:
        keys = [(str(item.kind), item.fingerprint_hash) for item in value]
        if keys != sorted(set(keys)):
            raise ValueError("duplicate evidence must be sorted and unique")
        return value

    @model_validator(mode="after")
    def manifest_matches_frozen_family(self) -> Self:
        if len(self.candidates) != self.declared_candidate_count:
            raise ValueError("candidate manifest does not cover its declared denominator")
        if any(
            item.family_hash != self.family_hash
            or item.factor_template_hash != self.factor_template_hash
            for item in self.candidates
        ):
            raise ValueError("candidate manifest contains an unbound candidate")
        candidate_hashes = {item.content_hash for item in self.candidates}
        for evidence in self.duplicate_evidence:
            if evidence.representative_candidate_hash not in candidate_hashes or not set(
                evidence.duplicate_candidate_hashes
            ).issubset(candidate_hashes):
                raise ValueError("duplicate evidence references a candidate outside the manifest")
        return self
