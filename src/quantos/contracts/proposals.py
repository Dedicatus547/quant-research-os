"""Deterministic compilation records for Agent proposal chains."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from quantos.contracts.agent import (
    ExperimentProposalSpec,
    FactorProposalSpec,
    HypothesisProposal,
)
from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research import ExperimentAuthoringSpec


class SubmittableProposalKind(StrEnum):
    HYPOTHESIS = "hypothesis"
    FACTOR = "factor"
    EXPERIMENT = "experiment"


class ProposalSubmissionRequest(CanonicalContract):
    schema_version: Literal["proposal-submission-request/v1"] = "proposal-submission-request/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    proposal_kind: SubmittableProposalKind
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]
    proposal: HypothesisProposal | FactorProposalSpec | ExperimentProposalSpec

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("proposal submission inputs must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("proposal submission input hash is invalid")
        return value

    @model_validator(mode="after")
    def envelope_matches_proposal(self) -> ProposalSubmissionRequest:
        kind_matches = (
            (
                self.proposal_kind is SubmittableProposalKind.HYPOTHESIS
                and isinstance(self.proposal, HypothesisProposal)
            )
            or (
                self.proposal_kind is SubmittableProposalKind.FACTOR
                and isinstance(self.proposal, FactorProposalSpec)
            )
            or (
                self.proposal_kind is SubmittableProposalKind.EXPERIMENT
                and isinstance(self.proposal, ExperimentProposalSpec)
            )
        )
        if not kind_matches:
            raise ValueError("proposal kind and payload schema disagree")
        if self.proposal.agent_run_hash != self.agent_run_hash:
            raise ValueError("proposal submission AgentRun hash disagrees with payload")
        required = {self.agent_run_hash, self.campaign_hash, self.budget_hash}
        if not required.issubset(self.input_hashes):
            raise ValueError("proposal submission must bind AgentRun, campaign, and budget inputs")
        if isinstance(self.proposal, ExperimentProposalSpec) and (
            self.proposal.campaign_hash != self.campaign_hash
        ):
            raise ValueError("experiment proposal campaign hash disagrees with envelope")
        return self


class ProposalSubmissionReceipt(CanonicalContract):
    schema_version: Literal["proposal-submission-receipt/v1"] = "proposal-submission-receipt/v1"
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    capability: Literal[
        "proposal.submit_hypothesis",
        "proposal.submit_factor",
        "proposal.submit_experiment",
    ]
    request_hash: str = Field(pattern=SHA256_PATTERN)
    proposal_kind: SubmittableProposalKind
    proposal_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]

    @field_validator("input_hashes")
    @classmethod
    def inputs_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("receipt input hashes must be sorted and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("receipt input hash is invalid")
        return value


class ProposalSubmissionAuditEvent(CanonicalContract):
    """Append-only accepted-write evidence without proposal text or runtime secrets."""

    schema_version: Literal["proposal-submission-audit-event/v1"] = (
        "proposal-submission-audit-event/v1"
    )
    idempotency_key: str = Field(pattern=SHA256_PATTERN)
    sequence: Literal[1] = 1
    capability: Literal[
        "proposal.submit_hypothesis",
        "proposal.submit_factor",
        "proposal.submit_experiment",
    ]
    request_hash: str = Field(pattern=SHA256_PATTERN)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)
    proposal_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    budget_hash: str = Field(pattern=SHA256_PATTERN)
    input_hashes: tuple[str, ...]

    @field_validator("input_hashes")
    @classmethod
    def audit_inputs_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("proposal audit input hashes must be sorted and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("proposal audit input hash is invalid")
        return value


class CompiledExperimentProposal(CanonicalContract):
    schema_version: Literal["compiled-experiment-proposal/v1"] = "compiled-experiment-proposal/v1"
    observation_hash: str = Field(pattern=SHA256_PATTERN)
    hypothesis_hash: str = Field(pattern=SHA256_PATTERN)
    factor_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    experiment_proposal_hash: str = Field(pattern=SHA256_PATTERN)
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    family_hash: str = Field(pattern=SHA256_PATTERN)
    source_agent_run_hashes: tuple[str, ...]
    input_hashes: tuple[str, ...]
    authoring_spec: ExperimentAuthoringSpec

    @field_validator("source_agent_run_hashes", "input_hashes")
    @classmethod
    def hashes_are_nonempty_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("compiled proposal hashes must be nonempty, sorted, and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("compiled proposal hash is invalid")
        return value
