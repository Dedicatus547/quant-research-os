"""Append-only research-ledger, retrieval, and P14a qualification schemas."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.evidence import LOGICAL_ID_PATTERN
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import RunStatus, ValidationVerdict


class LedgerAssertionAuthority(StrEnum):
    AGENT_PROPOSAL = "AGENT_PROPOSAL"
    DETERMINISTIC_EVIDENCE = "DETERMINISTIC_EVIDENCE"
    DETERMINISTIC_VERDICT = "DETERMINISTIC_VERDICT"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    SOURCE_ASSERTION = "SOURCE_ASSERTION"


class ResearchLedgerNodeKind(StrEnum):
    CAMPAIGN_SELECTION_REPORT = "CAMPAIGN_SELECTION_REPORT"
    CAMPAIGN_TRIAL = "CAMPAIGN_TRIAL"
    EVIDENCE = "EVIDENCE"
    EXPERIMENT = "EXPERIMENT"
    EXTRACTED_TEXT = "EXTRACTED_TEXT"
    FACTOR_PROPOSAL = "FACTOR_PROPOSAL"
    HUMAN_REVIEW_STATEMENT = "HUMAN_REVIEW_STATEMENT"
    HYPOTHESIS_PROPOSAL = "HYPOTHESIS_PROPOSAL"
    INTERPRETATION_PROPOSAL = "INTERPRETATION_PROPOSAL"
    OBSERVATION_PROPOSAL = "OBSERVATION_PROPOSAL"
    RESEARCH_RESULT = "RESEARCH_RESULT"
    VALIDATION_REPORT = "VALIDATION_REPORT"


class LedgerObjectAccess(StrEnum):
    CAMPAIGN_INTERNAL = "CAMPAIGN_INTERNAL"
    PUBLIC_HISTORY = "PUBLIC_HISTORY"
    SEALED_CONFIRMATION = "SEALED_CONFIRMATION"


class ResearchLedgerObjectRef(CanonicalContract):
    schema_version: Literal["research-ledger-object-ref/v1"] = "research-ledger-object-ref/v1"
    object_hash: str = Field(pattern=SHA256_PATTERN)
    media_type: Literal["application/json", "text/plain"]
    source_domain: str = Field(pattern=LOGICAL_ID_PATTERN)
    access: LedgerObjectAccess
    campaign_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    contamination_hashes: tuple[str, ...] = ()

    @field_validator("contamination_hashes")
    @classmethod
    def contamination_is_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger object contamination hashes must be sorted and unique")
        return value

    @model_validator(mode="after")
    def access_matches_campaign(self) -> Self:
        if self.access is not LedgerObjectAccess.PUBLIC_HISTORY and self.campaign_hash is None:
            raise ValueError("campaign and sealed ledger objects must bind a campaign")
        if self.access is LedgerObjectAccess.PUBLIC_HISTORY and self.contamination_hashes:
            raise ValueError("public ledger objects cannot carry sealed contamination")
        if self.access is LedgerObjectAccess.SEALED_CONFIRMATION and not self.contamination_hashes:
            raise ValueError("sealed ledger objects must carry contamination")
        return self


class ResearchLedgerEventV2(CanonicalContract):
    schema_version: Literal["research-ledger-event/v2"] = "research-ledger-event/v2"
    event_id: UUID
    ledger_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    sequence: PositiveInt
    node_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    node_kind: ResearchLedgerNodeKind
    object_ref: ResearchLedgerObjectRef
    authority: LedgerAssertionAuthority
    parent_object_hashes: tuple[str, ...] = ()
    agent_run_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    human_review_evidence_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    verdict_report_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    occurred_at: datetime
    previous_event_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("parent_object_hashes")
    @classmethod
    def parents_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger parents must be sorted and unique")
        return value

    @field_validator("occurred_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ledger event timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def provenance_matches_authority(self) -> Self:
        bindings = (
            self.agent_run_hash,
            self.human_review_evidence_hash,
            self.verdict_report_hash,
        )
        expected_binding = {
            LedgerAssertionAuthority.AGENT_PROPOSAL: 0,
            LedgerAssertionAuthority.HUMAN_REVIEWED: 1,
            LedgerAssertionAuthority.DETERMINISTIC_VERDICT: 2,
        }.get(self.authority)
        if expected_binding is None:
            if any(item is not None for item in bindings):
                raise ValueError(
                    "evidence/source ledger authority cannot carry a provenance binding"
                )
        elif any(
            (item is not None) != (index == expected_binding) for index, item in enumerate(bindings)
        ):
            raise ValueError("ledger provenance does not match assertion authority")

        verdict_nodes = {
            ResearchLedgerNodeKind.CAMPAIGN_SELECTION_REPORT,
            ResearchLedgerNodeKind.VALIDATION_REPORT,
        }
        evidence_nodes = {
            ResearchLedgerNodeKind.CAMPAIGN_TRIAL,
            ResearchLedgerNodeKind.EXPERIMENT,
            ResearchLedgerNodeKind.RESEARCH_RESULT,
        }
        proposal_nodes = {
            ResearchLedgerNodeKind.FACTOR_PROPOSAL,
            ResearchLedgerNodeKind.HYPOTHESIS_PROPOSAL,
            ResearchLedgerNodeKind.INTERPRETATION_PROPOSAL,
            ResearchLedgerNodeKind.OBSERVATION_PROPOSAL,
        }
        if self.authority is LedgerAssertionAuthority.DETERMINISTIC_VERDICT and (
            self.node_kind not in verdict_nodes
            or self.object_ref.object_hash != self.verdict_report_hash
        ):
            raise ValueError("deterministic verdict must bind its verdict report object")
        if (
            self.authority is LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE
            and self.node_kind not in evidence_nodes
        ):
            raise ValueError("deterministic evidence must use a deterministic-evidence node")
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


class ResearchLedgerAccessScope(CanonicalContract):
    schema_version: Literal["research-ledger-access-scope/v1"] = "research-ledger-access-scope/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    readable_campaign_hashes: tuple[str, ...]
    inherited_contamination_hashes: tuple[str, ...] = ()
    authorized_sealed_object_hashes: tuple[str, ...] = ()

    @field_validator(
        "readable_campaign_hashes",
        "inherited_contamination_hashes",
        "authorized_sealed_object_hashes",
    )
    @classmethod
    def hashes_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger access hashes must be sorted and unique")
        return value

    @model_validator(mode="after")
    def current_campaign_is_readable(self) -> Self:
        if self.campaign_hash not in self.readable_campaign_hashes:
            raise ValueError("ledger access scope must include its current campaign")
        return self


class ResearchLedgerSearchPolicy(CanonicalContract):
    schema_version: Literal["research-ledger-search-policy/v1"] = "research-ledger-search-policy/v1"
    policy_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    tokenizer_id: Literal["unicode-word-v1"] = "unicode-word-v1"
    ranking_id: Literal["term-frequency-object-hash-v1"] = "term-frequency-object-hash-v1"
    allowed_node_kinds: tuple[ResearchLedgerNodeKind, ...]
    allowed_authorities: tuple[LedgerAssertionAuthority, ...]
    allow_cross_campaign_history: bool
    max_query_terms: PositiveInt
    max_results: PositiveInt
    max_serialized_bytes: PositiveInt

    @field_validator("allowed_node_kinds", "allowed_authorities")
    @classmethod
    def enums_are_sorted(cls, value: tuple[StrEnum, ...]) -> tuple[StrEnum, ...]:
        if not value or value != tuple(sorted(set(value), key=str)):
            raise ValueError("ledger search allowlists must be nonempty, sorted, and unique")
        return value


class ResearchLedgerTermFrequency(CanonicalContract):
    schema_version: Literal["research-ledger-term-frequency/v1"] = (
        "research-ledger-term-frequency/v1"
    )
    term: str = Field(min_length=1, max_length=256)
    count: PositiveInt


class ResearchLedgerIndexEntry(CanonicalContract):
    schema_version: Literal["research-ledger-index-entry/v1"] = "research-ledger-index-entry/v1"
    event_hash: str = Field(pattern=SHA256_PATTERN)
    sequence: PositiveInt
    node_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    node_kind: ResearchLedgerNodeKind
    object_ref: ResearchLedgerObjectRef
    authority: LedgerAssertionAuthority
    term_frequencies: tuple[ResearchLedgerTermFrequency, ...]

    @field_validator("term_frequencies")
    @classmethod
    def terms_are_sorted(cls, value: tuple[ResearchLedgerTermFrequency, ...]):
        terms = [item.term for item in value]
        if terms != sorted(set(terms)):
            raise ValueError("ledger index terms must be sorted and unique")
        return value


class ResearchLedgerIndex(CanonicalContract):
    schema_version: Literal["research-ledger-index/v1"] = "research-ledger-index/v1"
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    search_policy_hash: str = Field(pattern=SHA256_PATTERN)
    tokenizer_id: Literal["unicode-word-v1"] = "unicode-word-v1"
    source_event_hashes: tuple[str, ...]
    entries: tuple[ResearchLedgerIndexEntry, ...]

    @field_validator("source_event_hashes")
    @classmethod
    def source_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            re.fullmatch(SHA256_PATTERN, item) is None for item in value
        ):
            raise ValueError("ledger index source hashes must be unique")
        return value

    @field_validator("entries")
    @classmethod
    def entries_follow_event_order(
        cls, value: tuple[ResearchLedgerIndexEntry, ...]
    ) -> tuple[ResearchLedgerIndexEntry, ...]:
        if [item.sequence for item in value] != sorted(item.sequence for item in value):
            raise ValueError("ledger index entries must follow event order")
        if len({item.event_hash for item in value}) != len(value):
            raise ValueError("ledger index event hashes must be unique")
        return value


class ResearchLedgerSearchRequest(CanonicalContract):
    schema_version: Literal["research-ledger-search-request/v1"] = (
        "research-ledger-search-request/v1"
    )
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    search_policy_hash: str = Field(pattern=SHA256_PATTERN)
    access_scope_hash: str = Field(pattern=SHA256_PATTERN)
    query: str = Field(min_length=1, max_length=4_096)


class ResearchLedgerSearchHit(CanonicalContract):
    schema_version: Literal["research-ledger-search-hit/v1"] = "research-ledger-search-hit/v1"
    event_hash: str = Field(pattern=SHA256_PATTERN)
    node_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    node_kind: ResearchLedgerNodeKind
    object_ref: ResearchLedgerObjectRef
    authority: LedgerAssertionAuthority
    score: PositiveInt
    content: str
    content_bytes: NonNegativeInt

    @model_validator(mode="after")
    def byte_count_matches(self) -> Self:
        if self.content_bytes != len(self.content.encode("utf-8")):
            raise ValueError("ledger search hit byte count does not match its content")
        return self


class ResearchLedgerSearchResult(CanonicalContract):
    schema_version: Literal["research-ledger-search-result/v1"] = "research-ledger-search-result/v1"
    request_hash: str = Field(pattern=SHA256_PATTERN)
    index_hash: str = Field(pattern=SHA256_PATTERN)
    query_terms: tuple[str, ...]
    hits: tuple[ResearchLedgerSearchHit, ...]

    @field_validator("query_terms")
    @classmethod
    def query_terms_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("ledger query terms must be nonempty, sorted, and unique")
        return value

    @field_validator("hits")
    @classmethod
    def hits_are_ranked(
        cls, value: tuple[ResearchLedgerSearchHit, ...]
    ) -> tuple[ResearchLedgerSearchHit, ...]:
        ranked = tuple(
            sorted(
                value,
                key=lambda item: (-item.score, item.object_ref.object_hash, item.event_hash),
            )
        )
        if (
            value != ranked
            or len({item.event_hash for item in value}) != len(value)
            or len({item.object_ref.object_hash for item in value}) != len(value)
        ):
            raise ValueError("ledger search hits must be ranked and unique")
        return value


class ResearchContextBudgetPolicy(CanonicalContract):
    schema_version: Literal["research-context-budget-policy/v1"] = (
        "research-context-budget-policy/v1"
    )
    policy_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    max_items: PositiveInt
    max_item_bytes: PositiveInt
    max_serialized_bytes: PositiveInt

    @model_validator(mode="after")
    def item_fits_total(self) -> Self:
        if self.max_item_bytes > self.max_serialized_bytes:
            raise ValueError("context item byte limit cannot exceed the total byte limit")
        return self


class ResearchContextItem(CanonicalContract):
    schema_version: Literal["research-context-item/v1"] = "research-context-item/v1"
    event_hash: str = Field(pattern=SHA256_PATTERN)
    node_id: str = Field(pattern=LOGICAL_ID_PATTERN)
    node_kind: ResearchLedgerNodeKind
    object_ref: ResearchLedgerObjectRef
    authority: LedgerAssertionAuthority
    score: PositiveInt
    content: str
    content_bytes: NonNegativeInt

    @model_validator(mode="after")
    def byte_count_matches(self) -> Self:
        if self.content_bytes != len(self.content.encode("utf-8")):
            raise ValueError("context item byte count does not match its content")
        return self


class ResearchContextPack(CanonicalContract):
    schema_version: Literal["research-context-pack/v1"] = "research-context-pack/v1"
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    search_policy_hash: str = Field(pattern=SHA256_PATTERN)
    access_scope_hash: str = Field(pattern=SHA256_PATTERN)
    context_budget_policy_hash: str = Field(pattern=SHA256_PATTERN)
    search_request_hash: str = Field(pattern=SHA256_PATTERN)
    search_result_hash: str = Field(pattern=SHA256_PATTERN)
    items: tuple[ResearchContextItem, ...]
    included_content_bytes: NonNegativeInt

    @model_validator(mode="after")
    def total_byte_count_matches(self) -> Self:
        if self.included_content_bytes != sum(item.content_bytes for item in self.items):
            raise ValueError("context pack byte count does not match its items")
        return self


class ResearchContextAgentBinding(CanonicalContract):
    """Hash-only bridge from a deterministic ContextPack into an Agent run specification."""

    schema_version: Literal["research-context-agent-binding/v1"] = (
        "research-context-agent-binding/v1"
    )
    campaign_hash: str = Field(pattern=SHA256_PATTERN)
    context_pack_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    search_policy_hash: str = Field(pattern=SHA256_PATTERN)
    access_scope_hash: str = Field(pattern=SHA256_PATTERN)
    context_budget_policy_hash: str = Field(pattern=SHA256_PATTERN)
    search_request_hash: str = Field(pattern=SHA256_PATTERN)
    search_result_hash: str = Field(pattern=SHA256_PATTERN)


class P14aQualificationReport(CanonicalContract):
    """Immutable evidence that the P14a deterministic boundary passed its frozen gates."""

    schema_version: Literal["p14a-qualification-report/v1"] = "p14a-qualification-report/v1"
    code_provenance_hash: str = Field(pattern=SHA256_PATTERN)
    runtime_fingerprint_hash: str = Field(pattern=SHA256_PATTERN)
    search_policy_hash: str = Field(pattern=SHA256_PATTERN)
    context_budget_policy_hash: str = Field(pattern=SHA256_PATTERN)
    fixture_hash: str = Field(pattern=SHA256_PATTERN)
    ledger_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    index_hash: str = Field(pattern=SHA256_PATTERN)
    access_scope_hash: str = Field(pattern=SHA256_PATTERN)
    search_request_hash: str = Field(pattern=SHA256_PATTERN)
    search_result_hash: str = Field(pattern=SHA256_PATTERN)
    context_pack_hash: str = Field(pattern=SHA256_PATTERN)
    agent_context_binding_hash: str = Field(pattern=SHA256_PATTERN)
    agent_run_spec_hash: str = Field(pattern=SHA256_PATTERN)
    independent_root_count: Literal[2]
    principal_hashes_byte_exact: Literal[True]
    context_bound_to_agent_spec: Literal[True]
    status: Literal[RunStatus.SUCCEEDED]
    verdict: Literal[ValidationVerdict.PASS]
    limitations: tuple[str, ...]

    @field_validator("limitations")
    @classmethod
    def limitations_are_sorted(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("P14a qualification limitations must be nonempty, sorted, and unique")
        return value
