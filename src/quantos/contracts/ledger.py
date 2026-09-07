"""Append-only research-ledger schemas; persistence and search arrive in P14."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.evidence import LOGICAL_ID_PATTERN
from quantos.contracts.refs import SHA256_PATTERN


class LedgerAssertionAuthority(StrEnum):
    AGENT_PROPOSAL = "AGENT_PROPOSAL"
    DETERMINISTIC_EVIDENCE = "DETERMINISTIC_EVIDENCE"
    DETERMINISTIC_VERDICT = "DETERMINISTIC_VERDICT"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    SOURCE_ASSERTION = "SOURCE_ASSERTION"


class ResearchLedgerNodeKind(StrEnum):
    EVIDENCE = "EVIDENCE"
    EXPERIMENT = "EXPERIMENT"
    EXTRACTED_TEXT = "EXTRACTED_TEXT"
    FACTOR_PROPOSAL = "FACTOR_PROPOSAL"
    HUMAN_REVIEW_STATEMENT = "HUMAN_REVIEW_STATEMENT"
    HYPOTHESIS_PROPOSAL = "HYPOTHESIS_PROPOSAL"
    INTERPRETATION_PROPOSAL = "INTERPRETATION_PROPOSAL"
    OBSERVATION_PROPOSAL = "OBSERVATION_PROPOSAL"
    VALIDATION_REPORT = "VALIDATION_REPORT"


class ResearchLedgerEvent(CanonicalContract):
    schema_version: Literal["research-ledger-event/v1"] = "research-ledger-event/v1"
    event_id: UUID
    ledger_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    sequence: PositiveInt
    node_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    node_kind: ResearchLedgerNodeKind
    object_hash: str = Field(pattern=SHA256_PATTERN)
    authority: LedgerAssertionAuthority
    parent_object_hashes: tuple[str, ...] = ()
    agent_run_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    human_review_evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    validation_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    occurred_at: datetime
    previous_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("parent_object_hashes")
    @classmethod
    def parents_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("ledger parents must be sorted and unique")
        if any(re.fullmatch(SHA256_PATTERN, item) is None for item in value):
            raise ValueError("ledger parent hash is invalid")
        return value

    @field_validator("occurred_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ledger event timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def provenance_matches_authority(self) -> Self:
        expected = {
            LedgerAssertionAuthority.AGENT_PROPOSAL: (
                self.agent_run_hash is not None
                and self.human_review_evidence_hash is None
                and self.validation_report_hash is None
            ),
            LedgerAssertionAuthority.HUMAN_REVIEWED: (
                self.agent_run_hash is None
                and self.human_review_evidence_hash is not None
                and self.validation_report_hash is None
            ),
            LedgerAssertionAuthority.DETERMINISTIC_VERDICT: (
                self.agent_run_hash is None
                and self.human_review_evidence_hash is None
                and self.validation_report_hash is not None
            ),
            LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE: (
                self.agent_run_hash is None
                and self.human_review_evidence_hash is None
                and self.validation_report_hash is None
            ),
            LedgerAssertionAuthority.SOURCE_ASSERTION: (
                self.agent_run_hash is None
                and self.human_review_evidence_hash is None
                and self.validation_report_hash is None
            ),
        }
        if not expected[self.authority]:
            raise ValueError("ledger provenance does not match assertion authority")
        if (
            self.authority is LedgerAssertionAuthority.DETERMINISTIC_VERDICT
            and self.node_kind is not ResearchLedgerNodeKind.VALIDATION_REPORT
        ):
            raise ValueError("deterministic verdict must reference a ValidationReport node")
        if (
            self.authority is LedgerAssertionAuthority.DETERMINISTIC_VERDICT
            and self.object_hash != self.validation_report_hash
        ):
            raise ValueError("deterministic verdict object must be its ValidationReport")
        if (
            self.authority is LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE
            and self.node_kind is not ResearchLedgerNodeKind.EXPERIMENT
        ):
            raise ValueError("deterministic evidence must reference an Experiment node")
        proposal_nodes = {
            ResearchLedgerNodeKind.FACTOR_PROPOSAL,
            ResearchLedgerNodeKind.HYPOTHESIS_PROPOSAL,
            ResearchLedgerNodeKind.INTERPRETATION_PROPOSAL,
            ResearchLedgerNodeKind.OBSERVATION_PROPOSAL,
        }
        if (
            self.authority is LedgerAssertionAuthority.AGENT_PROPOSAL
            and self.node_kind not in proposal_nodes
        ):
            raise ValueError("Agent authority can only record proposal nodes")
        if self.authority is LedgerAssertionAuthority.SOURCE_ASSERTION and self.node_kind not in {
            ResearchLedgerNodeKind.EVIDENCE,
            ResearchLedgerNodeKind.EXTRACTED_TEXT,
        }:
            raise ValueError("source authority can only record evidence nodes")
        if (
            self.authority is LedgerAssertionAuthority.HUMAN_REVIEWED
            and self.node_kind is not ResearchLedgerNodeKind.HUMAN_REVIEW_STATEMENT
        ):
            raise ValueError("human authority can only record human-review statements")
        return self


class ResearchLedgerSnapshot(CanonicalContract):
    schema_version: Literal["research-ledger-snapshot/v1"] = "research-ledger-snapshot/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})
    ledger_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    source_event_hashes: tuple[str, ...]
    head_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    node_object_hashes: tuple[str, ...]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ledger snapshot timestamp must be timezone-aware")
        return value

    @field_validator("source_event_hashes")
    @classmethod
    def event_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger event hashes must be unique")
        return value

    @field_validator("node_object_hashes")
    @classmethod
    def node_hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger node hashes must be sorted and unique")
        return value

    @model_validator(mode="after")
    def head_matches_event_chain(self) -> Self:
        if bool(self.source_event_hashes) != (self.head_event_hash is not None):
            raise ValueError("ledger head presence does not match source events")
        if self.source_event_hashes and self.head_event_hash != self.source_event_hashes[-1]:
            raise ValueError("ledger head must be the final source event hash")
        return self
