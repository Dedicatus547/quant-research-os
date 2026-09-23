"""Deterministic, runtime-independent P14d-A autonomous campaign orchestration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn, Protocol, cast
from uuid import UUID, uuid5

from pydantic import ValidationError

from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.campaign_selection import CampaignSelectionError, CampaignSelectionService
from quantos.application.campaigns import (
    CampaignChainEvent,
    ResearchCampaignGovernor,
)
from quantos.application.enumeration import (
    CandidateEnumerationError,
    verify_candidate_enumeration_manifest,
)
from quantos.application.ledger import (
    ResearchLedgerError,
    ResearchLedgerService,
    bind_context_pack,
    build_context_bound_agent_run_spec,
    verify_context_bound_agent_manifest,
)
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    regular_tree_files,
)
from quantos.contracts.agent import (
    AgentRole,
    AgentRunManifest,
    AgentUsage,
    CampaignSegment,
)
from quantos.contracts.autonomous import (
    AutonomousAgentExchangeArtifact,
    AutonomousAgentRequest,
    AutonomousAgentResponse,
    AutonomousAgentRunPolicy,
    AutonomousBudgetView,
    AutonomousCampaignPolicy,
    AutonomousCandidateProposal,
    AutonomousExecutionBindings,
    AutonomousExecutionFailureEvidence,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    AutonomousLoopReport,
    AutonomousLoopState,
    AutonomousStoppingReason,
    autonomous_execution_identity,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignEventType,
    CampaignLifecycleStatus,
    CampaignTrial,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSnapshot,
    ResearchCampaignSpec,
    ResearchFamilySpec,
    TrialOutcome,
)
from quantos.contracts.campaign_selection import (
    CampaignSelectionEvent,
    CampaignSelectionEventType,
    CampaignSelectionVerdict,
)
from quantos.contracts.enumeration import (
    CandidateEnumerationManifest,
    ResearchCandidateSpec,
    ResearchFactorTemplateSpec,
)
from quantos.contracts.ledger import (
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    ResearchContextBudgetPolicy,
    ResearchContextPack,
    ResearchLedgerAccessScope,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSearchRequest,
    ResearchLedgerSnapshot,
)
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.research_result import ResearchResultManifest
from quantos.contracts.status import ReasonCode, RunStatus
from quantos.contracts.validation import ValidationReport

_AUTONOMOUS_EVENT_NAMESPACE = UUID("c5b20640-d7c8-4c54-a2d0-7d8b28a17867")
_SCRIPTED_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_RESEARCH_OUTCOMES = {
    TrialOutcome.EXECUTION_FAILED,
    TrialOutcome.HARD_REJECT,
    TrialOutcome.PASS,
    TrialOutcome.PIT_REJECT,
    TrialOutcome.SOFT_REJECT,
}


class AutonomousAgentDriver(Protocol):
    """Runtime-neutral Agent port. Implementations return proposal bytes only."""

    def run(self, request: AutonomousAgentRequest) -> AutonomousAgentResponse: ...


class DeterministicResearchExecutionPort(Protocol):
    """Adapter to existing PIT/Qlib/Validation services with request idempotency."""

    def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult: ...

    def verify_research_result(self, result_hash: str) -> ResearchResultManifest | None: ...

    def verify_validation_report(self, report_hash: str) -> ValidationReport | None: ...

    def verify_execution_failure(
        self, failure_hash: str
    ) -> AutonomousExecutionFailureEvidence | None: ...


def _raise(reason_code: ReasonCode, message: str) -> NoReturn:
    raise AutonomousOrchestrationError(reason_code, message)


def _validate_response(
    request: AutonomousAgentRequest,
    response: AutonomousAgentResponse,
    policy: AutonomousAgentRunPolicy,
) -> AutonomousAgentResponse:
    try:
        response = AutonomousAgentResponse.model_validate(response.model_dump(mode="python"))
        verify_context_bound_agent_manifest(
            manifest=response.manifest,
            spec=request.agent_run_spec,
            binding=request.context_binding,
            pack=request.context_pack,
        )
    except (ValueError, ResearchLedgerError) as error:
        raise AutonomousOrchestrationError(
            ReasonCode.ARTIFACT_CORRUPTED, "AgentRun response or ContextPack binding is invalid"
        ) from error
    manifest = response.manifest
    if (
        response.invocation_hash != request.content_hash
        or response.agent_run_spec_hash != request.agent_run_spec.content_hash
        or manifest.harness_identifier != policy.harness_identifier
        or manifest.provider_model_identifier != policy.provider_model_identifier
        or manifest.model_snapshot_immutable != policy.model_snapshot_immutable
        or manifest.model_configuration_hash != policy.requested_model_configuration_hash
        or manifest.instruction_hashes != policy.instruction_hashes
        or manifest.skill_hash != policy.skill_hash
        or manifest.tool_schema_hash != policy.tool_schema_hash
        or manifest.sandbox_policy_hash != policy.sandbox_policy_hash
        or manifest.permission_policy_hash != policy.permission_policy_hash
        or manifest.runtime_policy_hash != policy.runtime_policy_hash
        or manifest.input_hashes != request.agent_run_spec.input_artifact_hashes
    ):
        _raise(ReasonCode.ARTIFACT_CORRUPTED, "AgentRun provenance differs from the frozen request")
    return response


class ScriptedAgentDriver:
    """Deterministic fixture driver. Script bytes are proposals, not research evidence."""

    def __init__(
        self,
        script: tuple[AutonomousCandidateProposal | bytes, ...],
        policy: AutonomousAgentRunPolicy,
    ) -> None:
        if not script:
            raise ValueError("scripted Agent driver requires at least one proposal fixture")
        self._script = tuple(
            item.canonical_bytes() if isinstance(item, AutonomousCandidateProposal) else bytes(item)
            for item in script
        )
        self._policy = policy
        self._cache: dict[str, AutonomousAgentResponse] = {}

    def run(self, request: AutonomousAgentRequest) -> AutonomousAgentResponse:
        cached = self._cache.get(request.content_hash)
        if cached is not None:
            return cached
        index = request.run_ordinal - 1
        if index >= len(self._script):
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "scripted Agent fixture is exhausted")
        proposal_bytes = self._script[index]
        try:
            proposal_text = proposal_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AutonomousOrchestrationError(
                ReasonCode.SCHEMA_INVALID, "scripted proposal fixture is not UTF-8"
            ) from error
        proposal_hash = sha256_bytes(proposal_bytes)
        transcript_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "driver": "scripted-agent-driver/v1",
                    "invocation_hash": request.content_hash,
                    "proposal_hash": proposal_hash,
                }
            )
        )
        timestamp = _SCRIPTED_EPOCH + timedelta(microseconds=request.run_ordinal)
        limitations = ["SCRIPTED_FIXTURE_NOT_RESEARCH_EVIDENCE"]
        if not self._policy.model_snapshot_immutable:
            limitations.append("MODEL_IDENTIFIER_NOT_IMMUTABLE")
        manifest = AgentRunManifest(
            run_spec_hash=request.agent_run_spec.content_hash,
            provider_thread_id=f"scripted-{request.agent_run_spec.run_id}",
            provider_model_identifier=self._policy.provider_model_identifier,
            model_snapshot_immutable=self._policy.model_snapshot_immutable,
            model_configuration_hash=self._policy.requested_model_configuration_hash,
            harness_identifier=self._policy.harness_identifier,
            sandbox_policy_hash=self._policy.sandbox_policy_hash,
            permission_policy_hash=self._policy.permission_policy_hash,
            runtime_policy_hash=self._policy.runtime_policy_hash,
            instruction_hashes=self._policy.instruction_hashes,
            skill_hash=self._policy.skill_hash,
            tool_schema_hash=self._policy.tool_schema_hash,
            interactions=(),
            input_hashes=request.agent_run_spec.input_artifact_hashes,
            output_proposal_hashes=(proposal_hash,),
            transcript_hash=transcript_hash,
            usage=AgentUsage(input_tokens=0, output_tokens=0, tool_calls=0, retry_count=0),
            run_status=RunStatus.SUCCEEDED,
            limitations=tuple(sorted(limitations)),
            started_at=timestamp,
            completed_at=timestamp,
        )
        response = AutonomousAgentResponse(
            invocation_hash=request.content_hash,
            agent_run_spec_hash=request.agent_run_spec.content_hash,
            manifest=manifest,
            proposal_bytes=proposal_text,
            proposal_hash=proposal_hash,
        )
        self._cache[request.content_hash] = response
        return response


class AutonomousAgentExchangeStore:
    """Content-addressed request/response exchange store with create-if-absent semantics."""

    def __init__(self, root: Path, policy: AutonomousAgentRunPolicy) -> None:
        self.root = root
        self.policy = policy

    def _artifacts(self) -> tuple[tuple[Path, AutonomousAgentExchangeArtifact], ...]:
        if not self.root.exists():
            return ()
        try:
            files = regular_tree_files(self.root)
            if any(path.parent != self.root or path.suffix != ".json" for path in files):
                _raise(
                    ReasonCode.ARTIFACT_CORRUPTED, "Agent exchange root contains an invalid path"
                )
            artifacts: list[tuple[Path, AutonomousAgentExchangeArtifact]] = []
            for path in files:
                encoded = path.read_bytes()
                if len(encoded) > 600_000:
                    _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "Agent exchange exceeds byte limit")
                artifact = AutonomousAgentExchangeArtifact.model_validate_json(encoded)
                if (
                    encoded != artifact.canonical_bytes()
                    or path.name != f"sha256-{artifact.content_hash}.json"
                ):
                    _raise(ReasonCode.ARTIFACT_CORRUPTED, "Agent exchange is not content addressed")
                _validate_response(artifact.request, artifact.response, self.policy)
                artifacts.append((path, artifact))
            return tuple(artifacts)
        except (OSError, ValueError, ArtifactIntegrityError) as error:
            if isinstance(error, AutonomousOrchestrationError):
                raise
            raise AutonomousOrchestrationError(
                ReasonCode.ARTIFACT_CORRUPTED, "Agent exchange store failed verification"
            ) from error

    def for_request(self, request: AutonomousAgentRequest) -> AutonomousAgentResponse | None:
        matches = [
            artifact
            for _, artifact in self._artifacts()
            if artifact.request.content_hash == request.content_hash
        ]
        if len(matches) > 1:
            _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "Agent invocation has multiple exchanges")
        if not matches:
            return None
        artifact = matches[0]
        if artifact.request != request:
            _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "Agent invocation key has conflicting input")
        return _validate_response(request, artifact.response, self.policy)

    def for_campaign_ordinal(
        self, campaign_hash: str, run_ordinal: int
    ) -> AutonomousAgentExchangeArtifact | None:
        matches = [
            artifact
            for _, artifact in self._artifacts()
            if artifact.request.campaign_hash == campaign_hash
            and artifact.request.run_ordinal == run_ordinal
        ]
        if len(matches) > 1:
            _raise(
                ReasonCode.DUPLICATE_ID_CONFLICT,
                "campaign AgentRun ordinal has multiple immutable exchanges",
            )
        return matches[0] if matches else None

    def for_run_hash(self, run_hash: str) -> AutonomousAgentExchangeArtifact | None:
        matches = [
            artifact
            for _, artifact in self._artifacts()
            if artifact.response.manifest.transcript_hash == run_hash
        ]
        if len(matches) > 1:
            _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "AgentRun hash has multiple exchanges")
        return matches[0] if matches else None

    def publish(
        self,
        request: AutonomousAgentRequest,
        response: AutonomousAgentResponse,
    ) -> AutonomousAgentExchangeArtifact:
        response = _validate_response(request, response, self.policy)
        artifact = AutonomousAgentExchangeArtifact(request=request, response=response)
        with exclusive_directory_lock(self.root):
            existing = self.for_request(request)
            if existing is not None:
                if existing != response:
                    _raise(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "Agent invocation returned conflicting bytes",
                    )
                return AutonomousAgentExchangeArtifact(request=request, response=existing)
            path = self.root / f"sha256-{artifact.content_hash}.json"
            try:
                atomic_write_bytes(
                    path, artifact.canonical_bytes(), expected_sha256=artifact.content_hash
                )
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                raise AutonomousOrchestrationError(
                    ReasonCode.DUPLICATE_ID_CONFLICT, "Agent exchange publication conflicts"
                ) from error
        return artifact


class ReplayAgentDriver:
    """Return an already retained exchange after revalidating request and AgentRun bindings."""

    def __init__(self, store: AutonomousAgentExchangeStore) -> None:
        self.store = store

    def run(self, request: AutonomousAgentRequest) -> AutonomousAgentResponse:
        response = self.store.for_request(request)
        if response is None:
            _raise(ReasonCode.SOURCE_INCOMPLETE, "immutable AgentRun exchange is missing")
        return response


class CampaignEventStore:
    """Append-only persistence for the existing campaign event chain."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _parse(encoded: bytes) -> CampaignChainEvent:
        try:
            return ResearchCampaignEvent.model_validate_json(encoded)
        except ValidationError:
            return CampaignSelectionEvent.model_validate_json(encoded)

    def load(
        self,
        governor: ResearchCampaignGovernor,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
    ) -> tuple[CampaignChainEvent, ...]:
        if not self.root.exists():
            return ()
        try:
            files = regular_tree_files(self.root)
            if any(path.parent != self.root for path in files):
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign event store has nested files")
            parsed: list[CampaignChainEvent] = []
            for path in files:
                encoded = path.read_bytes()
                event = self._parse(encoded)
                if (
                    encoded != event.canonical_bytes()
                    or path.name != f"{event.sequence:08d}-sha256-{event.content_hash}.json"
                ):
                    _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign event file is not canonical")
                parsed.append(event)
            events = tuple(sorted(parsed, key=lambda item: item.sequence))
            governor.project(campaign, budget, events)
            return events
        except (OSError, ValueError, ArtifactIntegrityError) as error:
            if isinstance(error, AutonomousOrchestrationError):
                raise
            raise AutonomousOrchestrationError(
                ReasonCode.EVENT_CHAIN_INVALID, "campaign event chain failed verification"
            ) from error

    def append(
        self,
        event: CampaignChainEvent,
        governor: ResearchCampaignGovernor,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
    ) -> tuple[CampaignChainEvent, ...]:
        with exclusive_directory_lock(self.root):
            current = self.load(governor, campaign, budget)
            if any(item.content_hash == event.content_hash for item in current):
                return current
            if event.sequence != len(current) + 1 or event.previous_event_hash != (
                current[-1].content_hash if current else None
            ):
                _raise(
                    ReasonCode.EVENT_CHAIN_INVALID, "campaign event append is not at the chain head"
                )
            governor.project(campaign, budget, (*current, event))
            path = self.root / f"{event.sequence:08d}-sha256-{event.content_hash}.json"
            try:
                atomic_write_bytes(
                    path, event.canonical_bytes(), expected_sha256=event.content_hash
                )
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                raise AutonomousOrchestrationError(
                    ReasonCode.DUPLICATE_ID_CONFLICT, "campaign event append conflicts"
                ) from error
            return self.load(governor, campaign, budget)

    def seed(
        self,
        initial: tuple[CampaignChainEvent, ...],
        governor: ResearchCampaignGovernor,
        campaign: ResearchCampaignSpec,
        budget: ResearchBudgetSpec,
    ) -> tuple[CampaignChainEvent, ...]:
        governor.project(campaign, budget, initial)
        current = self.load(governor, campaign, budget)
        if len(initial) > len(current):
            for event in initial[len(current) :]:
                self.append(event, governor, campaign, budget)
            current = self.load(governor, campaign, budget)
        if current[: len(initial)] != initial:
            _raise(
                ReasonCode.DUPLICATE_ID_CONFLICT,
                "provided event prefix conflicts with stored chain",
            )
        return current


class AutonomousLoopReportStore:
    """Publish canonical loop reports as immutable content-addressed JSON artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def publish(self, report: AutonomousLoopReport) -> Path:
        try:
            report = AutonomousLoopReport.model_validate(report.model_dump(mode="python"))
        except ValueError as error:
            raise AutonomousOrchestrationError(
                ReasonCode.SCHEMA_INVALID, "autonomous loop report is invalid"
            ) from error
        path = self.root / f"sha256-{report.content_hash}.json"
        with exclusive_directory_lock(self.root):
            existing = self.verify(report.content_hash) if path.exists() else None
            if existing is not None:
                if existing != report:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "loop report hash conflicts")
                return path
            try:
                atomic_write_bytes(
                    path, report.canonical_bytes(), expected_sha256=report.content_hash
                )
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                raise AutonomousOrchestrationError(
                    ReasonCode.DUPLICATE_ID_CONFLICT, "loop report publication conflicts"
                ) from error
        return path

    def verify(self, report_hash: str) -> AutonomousLoopReport:
        if re.fullmatch(SHA256_PATTERN, report_hash) is None:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "loop report hash is invalid")
        path = self.root / f"sha256-{report_hash}.json"
        try:
            encoded = path.read_bytes()
            report = AutonomousLoopReport.model_validate_json(encoded)
        except (OSError, ValidationError, ValueError) as error:
            raise AutonomousOrchestrationError(
                ReasonCode.ARTIFACT_CORRUPTED, "loop report artifact is missing or invalid"
            ) from error
        if (
            encoded != report.canonical_bytes()
            or report.content_hash != report_hash
            or path.name != f"sha256-{report.content_hash}.json"
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "loop report artifact failed hash verification")
        return report


class AutonomousCampaignOrchestrator:
    """Run bounded candidate proposals through existing campaign, ledger, and selection services."""

    def __init__(
        self,
        *,
        campaign: ResearchCampaignSpec,
        family: ResearchFamilySpec,
        budget: ResearchBudgetSpec,
        template: ResearchFactorTemplateSpec,
        manifest: CandidateEnumerationManifest,
        initial_ledger_snapshot: ResearchLedgerSnapshot,
        ledger_service: ResearchLedgerService,
        ledger_id: str,
        search_policy: ResearchLedgerSearchPolicy,
        context_budget: ResearchContextBudgetPolicy,
        campaign_policy: AutonomousCampaignPolicy,
        agent_run_policy: AutonomousAgentRunPolicy,
        agent_driver: AutonomousAgentDriver,
        execution_port: DeterministicResearchExecutionPort,
        exchange_root: Path,
        event_root: Path,
        selection_service: CampaignSelectionService,
        selection_artifact_root: Path,
        autonomous_report_root: Path,
        execution_bindings: AutonomousExecutionBindings,
    ) -> None:
        try:
            self.campaign = ResearchCampaignSpec.model_validate(campaign.model_dump(mode="python"))
            self.family = ResearchFamilySpec.model_validate(family.model_dump(mode="python"))
            self.budget = ResearchBudgetSpec.model_validate(budget.model_dump(mode="python"))
            self.template = ResearchFactorTemplateSpec.model_validate(
                template.model_dump(mode="python")
            )
            self.manifest = CandidateEnumerationManifest.model_validate(
                manifest.model_dump(mode="python")
            )
            self.campaign_policy = AutonomousCampaignPolicy.model_validate(
                campaign_policy.model_dump(mode="python")
            )
            self.agent_run_policy = AutonomousAgentRunPolicy.model_validate(
                agent_run_policy.model_dump(mode="python")
            )
            self.execution_bindings = AutonomousExecutionBindings.model_validate(
                execution_bindings.model_dump(mode="python")
            )
        except ValueError as error:
            raise AutonomousOrchestrationError(
                ReasonCode.SCHEMA_INVALID, "autonomous campaign input contract is invalid"
            ) from error
        try:
            verify_candidate_enumeration_manifest(self.family, self.template, self.manifest)
        except CandidateEnumerationError as error:
            raise AutonomousOrchestrationError(error.reason_code, str(error)) from error
        if (
            self.campaign.family_hash != self.family.content_hash
            or self.campaign.budget_hash != self.budget.content_hash
            or self.manifest.family_hash != self.family.content_hash
            or self.manifest.factor_template_hash != self.template.content_hash
            or self.campaign_policy.readable_campaign_hashes.count(self.campaign.content_hash) != 1
            or initial_ledger_snapshot.content_hash != self.campaign.ledger_snapshot_hash
            or initial_ledger_snapshot.ledger_id != ledger_id
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign/family/budget/ledger bindings disagree")
        selection = selection_service
        if (
            selection.campaign != self.campaign
            or selection.family != self.family
            or selection.budget != self.budget
            or selection.template != self.template
            or selection.manifest != self.manifest
            or selection.plan is None
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "P14c selection service is not bound to campaign")
        self.initial_ledger_snapshot = initial_ledger_snapshot
        self.ledger_service = ledger_service
        self.ledger_id = ledger_id
        self.search_policy = search_policy
        self.context_budget = context_budget
        self.agent_driver = agent_driver
        self.execution_port = execution_port
        self.exchange_store = AutonomousAgentExchangeStore(exchange_root, self.agent_run_policy)
        self.event_store = CampaignEventStore(event_root)
        self.selection_service = selection
        self.selection_plan_hash = selection.plan.content_hash
        self.selection_artifact_root = selection_artifact_root
        self.report_store = AutonomousLoopReportStore(autonomous_report_root)
        self.execution_policy_hash = self.execution_bindings.execution_policy_hash
        self.governor = ResearchCampaignGovernor(self.family, self.template, self.manifest)
        self._candidate_by_hash = {item.content_hash: item for item in self.manifest.candidates}

    def run(
        self,
        initial_events: tuple[CampaignChainEvent, ...],
        *,
        started_at: datetime,
    ) -> tuple[AutonomousLoopReport, tuple[CampaignChainEvent, ...]]:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            _raise(ReasonCode.SCHEMA_INVALID, "autonomous loop start time must be timezone-aware")
        events = self.event_store.seed(initial_events, self.governor, self.campaign, self.budget)
        snapshot = self.governor.project(self.campaign, self.budget, events)
        if (
            snapshot.status is not CampaignLifecycleStatus.ACTIVE
            or snapshot.sealed_confirmation_accessed
        ):
            _raise(ReasonCode.CAMPAIGN_CLOSED, "campaign is not eligible for autonomous iterations")
        self._require_frozen_plan(events)
        ledger_snapshot = self._current_snapshot(started_at, events)
        self._require_initial_snapshot_prefix(ledger_snapshot)
        events, ledger_snapshot = self._reconcile_ledger(events, ledger_snapshot, started_at)

        stopping_reason: AutonomousStoppingReason | None = None
        while stopping_reason is None:
            campaign_snapshot = self.governor.project(self.campaign, self.budget, events)
            stopping_reason = self._stopping_reason(campaign_snapshot, events)
            if stopping_reason is not None:
                break
            event_time = self._next_event_time(started_at, events, ledger_snapshot)
            ledger_snapshot = self._current_snapshot(event_time, events)
            self._require_initial_snapshot_prefix(ledger_snapshot)
            scope = self._access_scope(ledger_snapshot)
            request, _pack = self._build_agent_request(
                ledger_snapshot, scope, campaign_snapshot, events
            )
            prior_exchange = self.exchange_store.for_campaign_ordinal(
                self.campaign.content_hash, request.run_ordinal
            )
            if prior_exchange is not None and prior_exchange.request != request:
                _raise(
                    ReasonCode.DUPLICATE_ID_CONFLICT,
                    "campaign AgentRun ordinal is already bound to different inputs",
                )
            response = self.exchange_store.for_request(request)
            if response is None:
                response = self.agent_driver.run(request)
                response = _validate_response(request, response, self.agent_run_policy)
                self.exchange_store.publish(request, response)
            self._validate_proposal_binding(request, response)
            proposal = self._parse_candidate_proposal(response)
            candidate_hash = self._extract_candidate_hash(response.proposal_bytes)
            candidate = self._candidate_by_hash.get(candidate_hash)
            if candidate is None:
                _raise(ReasonCode.SCHEMA_INVALID, "proposal candidate is outside frozen manifest")
            proposal_is_valid = self._proposal_matches_candidate(proposal, candidate)
            if proposal is not None and proposal.campaign_hash != self.campaign.content_hash:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "proposal campaign binding is invalid")
            trial = self._make_trial(
                request=request,
                response=response,
                proposal=proposal if proposal_is_valid else None,
                candidate=candidate,
                events=events,
                event_time=event_time,
            )
            event = self.governor.record_trial(
                self.campaign,
                self.budget,
                events,
                trial,
                event_id=uuid5(_AUTONOMOUS_EVENT_NAMESPACE, trial.idempotency_key),
                occurred_at=event_time,
            )
            events = self.event_store.append(event, self.governor, self.campaign, self.budget)
            events, ledger_snapshot = self._reconcile_ledger(events, ledger_snapshot, event_time)
            if (
                proposal_is_valid
                and proposal is not None
                and proposal.request_stop
                and self.campaign.stopping_rule.value == "BUDGET_EXHAUSTED_OR_MANUAL_CLOSE"
                and self.campaign_policy.allow_agent_requested_manual_close
            ):
                post = self.governor.project(self.campaign, self.budget, events)
                if self._stopping_reason(post, events) is None:
                    stopping_reason = (
                        AutonomousStoppingReason.MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY
                    )

        return self._selection_handoff(
            events,
            started_at=started_at,
            stopping_reason=stopping_reason,
        )

    def _require_frozen_plan(self, events: tuple[CampaignChainEvent, ...]) -> None:
        plan_events = [
            event
            for event in events
            if isinstance(event, CampaignSelectionEvent)
            and event.event_type is CampaignSelectionEventType.PLAN_FROZEN
        ]
        if (
            len(plan_events) != 1
            or len(events) < 2
            or events[1] != plan_events[0]
            or plan_events[0].selection_plan_hash != self.selection_plan_hash
        ):
            _raise(
                ReasonCode.OOS_POLICY_VIOLATION,
                "autonomous loop requires the matching P14c plan after activation",
            )

    def _current_snapshot(
        self, at: datetime, events: tuple[CampaignChainEvent, ...]
    ) -> ResearchLedgerSnapshot:
        last_time = max((event.occurred_at for event in events), default=at)
        as_of = max(at, last_time)
        try:
            return self.ledger_service.verify(self.ledger_id, created_at=as_of)
        except ResearchLedgerError as error:
            raise AutonomousOrchestrationError(error.reason_code, str(error)) from error

    def _require_initial_snapshot_prefix(self, current: ResearchLedgerSnapshot) -> None:
        initial = self.initial_ledger_snapshot
        if (
            current.ledger_id != initial.ledger_id
            or current.source_event_hashes[: len(initial.source_event_hashes)]
            != initial.source_event_hashes
            or not set(initial.node_object_hashes).issubset(current.node_object_hashes)
        ):
            _raise(
                ReasonCode.ARTIFACT_CORRUPTED, "current Ledger is not a descendant of frozen input"
            )

    def _access_scope(self, snapshot: ResearchLedgerSnapshot) -> ResearchLedgerAccessScope:
        readable = tuple(sorted(set(self.campaign_policy.readable_campaign_hashes)))
        if self.campaign.content_hash not in readable:
            _raise(ReasonCode.CAPABILITY_DENIED, "Ledger scope omits the autonomous campaign")
        return ResearchLedgerAccessScope(
            campaign_hash=self.campaign.content_hash,
            ledger_snapshot_hash=snapshot.content_hash,
            readable_campaign_hashes=readable,
            inherited_contamination_hashes=self.campaign.inherited_contamination,
            authorized_sealed_object_hashes=(),
        )

    def _build_agent_request(
        self,
        snapshot: ResearchLedgerSnapshot,
        scope: ResearchLedgerAccessScope,
        campaign_snapshot: ResearchCampaignSnapshot,
        events: tuple[CampaignChainEvent, ...],
    ) -> tuple[AutonomousAgentRequest, ResearchContextPack]:
        search_request = ResearchLedgerSearchRequest(
            campaign_hash=self.campaign.content_hash,
            ledger_snapshot_hash=snapshot.content_hash,
            search_policy_hash=self.search_policy.content_hash,
            access_scope_hash=scope.content_hash,
            query=self.campaign_policy.context_query,
        )
        try:
            result = self.ledger_service.search(
                snapshot=snapshot,
                policy=self.search_policy,
                scope=scope,
                request=search_request,
            )
            pack = self.ledger_service.build_context_pack(
                snapshot=snapshot,
                policy=self.search_policy,
                scope=scope,
                request=search_request,
                result=result,
                budget=self.context_budget,
            )
        except ResearchLedgerError as error:
            raise AutonomousOrchestrationError(error.reason_code, str(error)) from error
        binding = bind_context_pack(pack)
        exact_duplicates = self._attempted_exact_expression_hashes(events)
        attempted = {
            event.trial.candidate_hash
            for event in events
            if isinstance(event, ResearchCampaignEvent) and event.trial is not None
        }
        options = tuple(
            sorted(
                (
                    candidate
                    for candidate in self.manifest.candidates
                    if candidate.content_hash not in attempted
                    and candidate.exact_expression_hash not in exact_duplicates
                ),
                key=lambda item: item.content_hash,
            )
        )
        if not options:
            _raise(ReasonCode.RESEARCH_BUDGET_EXCEEDED, "no candidate remains for an Agent request")
        proposal_schema_bytes = canonical_json_bytes(
            AutonomousCandidateProposal.model_json_schema()
        )
        proposal_schema_hash = sha256_bytes(proposal_schema_bytes)
        policy_hashes = tuple(
            sorted(
                {
                    self.campaign_policy.content_hash,
                    self.agent_run_policy.content_hash,
                    self.search_policy.content_hash,
                    self.context_budget.content_hash,
                    self.selection_plan_hash,
                    self.execution_policy_hash,
                    proposal_schema_hash,
                }
            )
        )
        ordinal = campaign_snapshot.agent_run_count + 1
        run_identity_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "campaign_hash": self.campaign.content_hash,
                    "candidate_manifest_hash": self.manifest.content_hash,
                    "context_pack_hash": pack.content_hash,
                    "ledger_snapshot_hash": snapshot.content_hash,
                    "ordinal": ordinal,
                    "policy_hashes": policy_hashes,
                }
            )
        )
        run_id = f"autonomous-{run_identity_hash}"
        _, spec = build_context_bound_agent_run_spec(
            run_id=run_id,
            role=AgentRole.RESEARCHER,
            capability_policy_hash=self.agent_run_policy.capability_policy_hash,
            requested_model_configuration_hash=(
                self.agent_run_policy.requested_model_configuration_hash
            ),
            tool_schema_hash=self.agent_run_policy.tool_schema_hash,
            instruction_hashes=self.agent_run_policy.instruction_hashes,
            skill_hash=self.agent_run_policy.skill_hash,
            pack=pack,
            evidence_hashes=self.campaign.evidence_hashes,
            additional_input_hashes=(
                self.campaign.content_hash,
                self.family.content_hash,
                self.budget.content_hash,
                self.manifest.content_hash,
                *policy_hashes,
            ),
        )
        request = AutonomousAgentRequest(
            campaign_id=self.campaign.campaign_id,
            campaign_hash=self.campaign.content_hash,
            family_hash=self.family.content_hash,
            budget_hash=self.budget.content_hash,
            candidate_manifest_hash=self.manifest.content_hash,
            relevant_policy_hashes=policy_hashes,
            run_ordinal=ordinal,
            allowed_proposal_schema_json=proposal_schema_bytes.decode("utf-8"),
            proposal_schema_hash=proposal_schema_hash,
            budget=AutonomousBudgetView.from_usage(
                self.budget,
                trials=campaign_snapshot.trial_count,
                agent_runs=campaign_snapshot.agent_run_count,
                distinct_candidates=campaign_snapshot.distinct_candidate_count,
                executions=campaign_snapshot.execution_count,
                validation_rounds=campaign_snapshot.validation_round_count,
                compute_seconds=campaign_snapshot.compute_seconds,
            ),
            context_pack=pack,
            context_binding=binding,
            candidate_options=options,
            agent_run_spec=spec,
        )
        if len(request.canonical_bytes()) > self.campaign_policy.max_agent_request_bytes:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "Agent request exceeds frozen byte budget")
        return request, pack

    def _attempted_exact_expression_hashes(
        self, events: tuple[CampaignChainEvent, ...]
    ) -> frozenset[str]:
        attempted_hashes = {
            event.trial.candidate_hash
            for event in events
            if isinstance(event, ResearchCampaignEvent) and event.trial is not None
        }
        return frozenset(
            item.exact_expression_hash
            for item in self.manifest.candidates
            if item.content_hash in attempted_hashes
        )

    @staticmethod
    def _has_attempted_exact_expression(
        candidate: ResearchCandidateSpec,
        attempted_exact_expression_hashes: frozenset[str],
    ) -> bool:
        """Suppress exact repeats while leaving structurally similar candidates eligible."""

        return candidate.exact_expression_hash in attempted_exact_expression_hashes

    @staticmethod
    def _extract_candidate_hash(proposal_bytes: str) -> str:
        try:
            raw: object = json.loads(proposal_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise AutonomousOrchestrationError(
                ReasonCode.SCHEMA_INVALID,
                "invalid proposal has no independently parseable candidate reference",
            ) from error
        candidate_hash: object = None
        if isinstance(raw, dict):
            raw_object = cast(dict[str, object], raw)
            candidate_hash = raw_object.get("candidate_hash")
        if (
            not isinstance(candidate_hash, str)
            or re.fullmatch(SHA256_PATTERN, candidate_hash) is None
        ):
            _raise(ReasonCode.SCHEMA_INVALID, "proposal does not identify a frozen candidate")
        return candidate_hash

    def _parse_candidate_proposal(
        self, response: AutonomousAgentResponse
    ) -> AutonomousCandidateProposal | None:
        try:
            proposal = AutonomousCandidateProposal.model_validate_json(
                response.proposal_bytes.encode("utf-8")
            )
        except (ValidationError, ValueError):
            return None
        if proposal.canonical_bytes() != response.proposal_bytes.encode("utf-8"):
            return None
        return proposal

    def _proposal_matches_candidate(
        self,
        proposal: AutonomousCandidateProposal | None,
        candidate: ResearchCandidateSpec,
    ) -> bool:
        return proposal is not None and (
            proposal.candidate_hash == candidate.content_hash
            and proposal.parameters == candidate.parameters
            and proposal.expression == candidate.expression
            and proposal.exact_expression_hash == candidate.exact_expression_hash
            and proposal.structural_expression_hash == candidate.structural_expression_hash
        )

    def _validate_proposal_binding(
        self, request: AutonomousAgentRequest, response: AutonomousAgentResponse
    ) -> None:
        if (
            len(response.proposal_bytes.encode("utf-8"))
            > self.campaign_policy.max_agent_request_bytes
        ):
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "Agent proposal exceeds frozen byte budget")
        if response.invocation_hash != request.content_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "Agent response is bound to a different request")

    def _make_trial(
        self,
        *,
        request: AutonomousAgentRequest,
        response: AutonomousAgentResponse,
        proposal: AutonomousCandidateProposal | None,
        candidate: ResearchCandidateSpec,
        events: tuple[CampaignChainEvent, ...],
        event_time: datetime,
    ) -> CampaignTrial:
        proposal_valid = self._proposal_matches_candidate(proposal, candidate)
        candidate_attempted = any(
            isinstance(event, ResearchCampaignEvent)
            and event.trial is not None
            and event.trial.candidate_hash == candidate.content_hash
            for event in events
        )
        same_expression_attempted = self._has_attempted_exact_expression(
            candidate, self._attempted_exact_expression_hashes(events)
        )
        if not proposal_valid:
            outcome = TrialOutcome.SCHEMA_INVALID
            execution_requested = False
            compute_seconds = 0
            evidence_hashes: tuple[str, ...] = ()
        elif candidate_attempted or same_expression_attempted:
            outcome = TrialOutcome.DUPLICATE_CANDIDATE
            execution_requested = False
            compute_seconds = 0
            evidence_hashes = ()
        else:
            run_hash = response.manifest.transcript_hash
            projection = self.governor.project(self.campaign, self.budget, events)
            trial_ordinal = projection.trial_count + 1
            segment = {
                CampaignSegment.DEVELOPMENT: self.campaign.development,
                CampaignSegment.VALIDATION: self.campaign.validation,
            }[self.campaign_policy.trial_segment]
            execution_identity = autonomous_execution_identity(
                campaign_hash=self.campaign.content_hash,
                family_hash=self.family.content_hash,
                budget_hash=self.budget.content_hash,
                candidate_manifest_hash=self.manifest.content_hash,
                candidate=candidate,
                snapshot_hash=self.campaign.snapshot_hash,
                qlib_view_hash=self.campaign.qlib_view_hash,
                segment=self.campaign_policy.trial_segment,
                segment_start=segment.start,
                segment_end=segment.end,
                trial_ordinal=trial_ordinal,
                bindings=self.execution_bindings,
            )
            execution_request = AutonomousExecutionRequest(
                idempotency_key=execution_identity,
                execution_identity=execution_identity,
                trial_ordinal=trial_ordinal,
                campaign_hash=self.campaign.content_hash,
                family_hash=self.family.content_hash,
                budget_hash=self.budget.content_hash,
                candidate_manifest_hash=self.manifest.content_hash,
                candidate=candidate,
                candidate_exact_expression_hash=candidate.exact_expression_hash,
                candidate_structural_expression_hash=candidate.structural_expression_hash,
                snapshot_hash=self.campaign.snapshot_hash,
                dataset_id=self.execution_bindings.dataset_id,
                qlib_view_hash=self.campaign.qlib_view_hash,
                segment=self.campaign_policy.trial_segment,
                segment_start=segment.start,
                segment_end=segment.end,
                agent_run_hash=run_hash,
                execution_policy_hash=self.execution_bindings.execution_policy_hash,
                pit_policy_hash=self.execution_bindings.pit_policy_hash,
                authoring_hash=self.execution_bindings.authoring_hash,
                research_policy_hash=self.execution_bindings.research_policy_hash,
                validation_policy_hash=self.execution_bindings.validation_policy_hash,
                cost_policy_hash=self.execution_bindings.cost_policy_hash,
                backtest_policy_hash=self.execution_bindings.backtest_policy_hash,
                code_commit_hash=self.execution_bindings.code_commit_hash,
                lockfile_hash=self.execution_bindings.lockfile_hash,
                qlib_version=self.execution_bindings.qlib_version,
                remaining_executions=max(
                    0, self.budget.max_executions - projection.execution_count
                ),
                remaining_validation_rounds=max(
                    0, self.budget.max_validation_rounds - projection.validation_round_count
                ),
                remaining_compute_seconds=max(
                    0, self.budget.max_compute_seconds - projection.compute_seconds
                ),
            )
            try:
                execution_result = self.execution_port.execute(execution_request)
                execution_result = AutonomousExecutionResult.model_validate(
                    execution_result.model_dump(mode="python")
                )
            except (ValueError, AttributeError) as error:
                raise AutonomousOrchestrationError(
                    ReasonCode.QLIB_EXECUTION_FAILED,
                    "deterministic execution adapter returned an invalid result",
                ) from error
            if execution_result.request_hash != execution_request.content_hash:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "execution result binds a different request")
            if execution_result.research_result_hash is not None:
                try:
                    result_manifest = self.execution_port.verify_research_result(
                        execution_result.research_result_hash
                    )
                except (ValueError, AttributeError) as error:
                    raise AutonomousOrchestrationError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "execution adapter could not bottom-up verify its ResearchResult",
                    ) from error
                if (
                    result_manifest is None
                    or result_manifest.artifact_hash != execution_result.research_result_hash
                    or result_manifest.snapshot_hash != execution_request.snapshot_hash
                    or result_manifest.qlib_view_hash != execution_request.qlib_view_hash
                    or result_manifest.expression_spec_hash != candidate.expression.content_hash
                    or result_manifest.research_policy_hash
                    != execution_request.research_policy_hash
                ):
                    _raise(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "ResearchResult differs from the frozen candidate execution request",
                    )
            if execution_result.validation_report_hash is not None:
                try:
                    validation_report = self.execution_port.verify_validation_report(
                        execution_result.validation_report_hash
                    )
                except (ValueError, AttributeError) as error:
                    raise AutonomousOrchestrationError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "execution adapter could not bottom-up verify its ValidationReport",
                    ) from error
                if (
                    validation_report is None
                    or validation_report.report_hash != execution_result.validation_report_hash
                    or validation_report.snapshot_hash != execution_request.snapshot_hash
                    or validation_report.qlib_view_hash != execution_request.qlib_view_hash
                    or validation_report.research_policy_hash
                    != execution_request.research_policy_hash
                    or validation_report.validation_policy_hash
                    != execution_request.validation_policy_hash
                ):
                    _raise(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "ValidationReport differs from the frozen execution request",
                    )
                if (
                    execution_result.research_result_hash is not None
                    and validation_report.resolved_experiment_hash is None
                ):
                    _raise(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "ValidationReport lacks its resolved experiment binding",
                    )
            if (
                execution_result.compute_seconds + projection.compute_seconds
                > self.budget.max_compute_seconds
            ):
                _raise(
                    ReasonCode.RESEARCH_BUDGET_EXCEEDED,
                    "execution exceeded remaining compute budget",
                )
            outcome = execution_result.outcome
            execution_requested = execution_result.execution_requested
            compute_seconds = execution_result.compute_seconds
            evidence_hashes = execution_result.evidence_hashes
        idempotency_key = sha256_bytes(
            canonical_json_bytes(
                {
                    "agent_run_hash": response.manifest.transcript_hash,
                    "candidate_hash": candidate.content_hash,
                    "proposal_hash": response.proposal_hash,
                    "campaign_hash": self.campaign.content_hash,
                    "segment": self.campaign_policy.trial_segment,
                }
            )
        )
        trial_id = f"trial-{idempotency_key[:48]}"
        return CampaignTrial(
            trial_id=trial_id,
            idempotency_key=idempotency_key,
            proposal_hash=response.proposal_hash,
            candidate_hash=candidate.content_hash,
            segment=self.campaign_policy.trial_segment,
            outcome=outcome,
            agent_run_hash=response.manifest.transcript_hash,
            execution_requested=execution_requested,
            compute_seconds=compute_seconds,
            evidence_hashes=evidence_hashes,
        )

    def _stopping_reason(
        self,
        snapshot: ResearchCampaignSnapshot,
        events: tuple[CampaignChainEvent, ...],
    ) -> AutonomousStoppingReason | None:
        attempted = {
            event.trial.candidate_hash
            for event in events
            if isinstance(event, ResearchCampaignEvent) and event.trial is not None
        }
        if len(attempted) == len(self.manifest.candidates):
            return AutonomousStoppingReason.ALL_CANDIDATES_TERMINAL
        usage = (
            (snapshot.trial_count, self.budget.max_trials),
            (snapshot.agent_run_count, self.budget.max_agent_runs),
            (snapshot.distinct_candidate_count, self.budget.max_distinct_candidates),
            (snapshot.execution_count, self.budget.max_executions),
            (snapshot.validation_round_count, self.budget.max_validation_rounds),
            (snapshot.compute_seconds, self.budget.max_compute_seconds),
        )
        if any(used >= limit for used, limit in usage):
            return AutonomousStoppingReason.BUDGET_EXHAUSTED
        exact_attempted = self._attempted_exact_expression_hashes(events)
        remaining = tuple(
            item
            for item in self.manifest.candidates
            if item.content_hash not in attempted
            and item.exact_expression_hash not in exact_attempted
        )
        if not remaining:
            return AutonomousStoppingReason.NO_REMAINING_ELIGIBLE_CANDIDATES
        return None

    def _next_event_time(
        self,
        started_at: datetime,
        events: tuple[CampaignChainEvent, ...],
        ledger_snapshot: ResearchLedgerSnapshot,
    ) -> datetime:
        count = sum(
            isinstance(event, ResearchCampaignEvent)
            and event.event_type is CampaignEventType.TRIAL_RECORDED
            for event in events
        )
        candidate = started_at + timedelta(seconds=count + 1)
        previous = max((event.occurred_at for event in events), default=candidate)
        if previous >= candidate:
            candidate = previous + timedelta(seconds=1)
        return candidate

    def _reconcile_ledger(
        self,
        events: tuple[CampaignChainEvent, ...],
        snapshot: ResearchLedgerSnapshot,
        at: datetime,
    ) -> tuple[tuple[CampaignChainEvent, ...], ResearchLedgerSnapshot]:
        event_trials = tuple(
            event
            for event in events
            if isinstance(event, ResearchCampaignEvent)
            and event.event_type is CampaignEventType.TRIAL_RECORDED
            and event.trial is not None
        )
        for event in event_trials:
            trial = cast(CampaignTrial, event.trial)
            if trial.agent_run_hash is not None:
                exchange = self.exchange_store.for_run_hash(trial.agent_run_hash)
                if exchange is not None:
                    response = exchange.response
                    if (
                        response.proposal_hash != trial.proposal_hash
                        or response.manifest.transcript_hash != trial.agent_run_hash
                        or self._extract_candidate_hash(response.proposal_bytes)
                        != trial.candidate_hash
                    ):
                        _raise(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "trial and retained Agent exchange disagree",
                        )
                    parsed = self._parse_candidate_proposal(response)
                    candidate = self._candidate_by_hash.get(trial.candidate_hash)
                    if (
                        parsed is not None
                        and candidate is not None
                        and parsed.campaign_hash == self.campaign.content_hash
                        and self._proposal_matches_candidate(parsed, candidate)
                    ):
                        snapshot = self._append_proposal_if_missing(
                            parsed,
                            response,
                            exchange.request.context_pack,
                            snapshot,
                            event.occurred_at,
                        )
            trial_hash = sha256_bytes(trial.canonical_bytes())
            if trial_hash not in snapshot.node_object_hashes:
                self._append_ledger_object(
                    contract=trial,
                    object_hash=trial_hash,
                    node_kind=ResearchLedgerNodeKind.CAMPAIGN_TRIAL,
                    authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
                    node_id=f"campaign-trial-{event.content_hash}",
                    occurred_at=event.occurred_at,
                    campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
                    agent_run_hash=None,
                    parent_object_hashes=(),
                )
                snapshot = self._current_snapshot(max(at, event.occurred_at), events)
            snapshot = self._reconcile_execution_evidence(
                trial=trial,
                candidate=self._candidate_by_hash.get(trial.candidate_hash),
                trial_hash=trial_hash,
                snapshot=snapshot,
                occurred_at=event.occurred_at,
            )
        return events, snapshot

    def _reconcile_execution_evidence(
        self,
        *,
        trial: CampaignTrial,
        candidate: ResearchCandidateSpec | None,
        trial_hash: str,
        snapshot: ResearchLedgerSnapshot,
        occurred_at: datetime,
    ) -> ResearchLedgerSnapshot:
        result_hashes: list[str] = []
        validation_hashes: list[str] = []
        verify_result = cast(
            Callable[[str], ResearchResultManifest | None] | None,
            getattr(self.execution_port, "verify_research_result", None),
        )
        verify_validation = cast(
            Callable[[str], ValidationReport | None] | None,
            getattr(self.execution_port, "verify_validation_report", None),
        )
        verify_failure = cast(
            Callable[[str], AutonomousExecutionFailureEvidence | None] | None,
            getattr(self.execution_port, "verify_execution_failure", None),
        )
        failure_hashes: list[str] = []
        for evidence_hash in trial.evidence_hashes:
            if verify_result is not None:
                try:
                    result = verify_result(evidence_hash)
                except (ValueError, AttributeError) as error:
                    raise AutonomousOrchestrationError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "trial ResearchResult evidence failed bottom-up verification",
                    ) from error
                if result is not None:
                    if (
                        candidate is None
                        or result.artifact_hash != evidence_hash
                        or result.snapshot_hash != self.campaign.snapshot_hash
                        or result.qlib_view_hash != self.campaign.qlib_view_hash
                        or result.expression_spec_hash != candidate.expression.content_hash
                    ):
                        _raise(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "trial ResearchResult identity differs from its frozen candidate",
                        )
                    result_hashes.append(evidence_hash)
            if verify_validation is not None:
                try:
                    report = verify_validation(evidence_hash)
                except (ValueError, AttributeError) as error:
                    raise AutonomousOrchestrationError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "trial ValidationReport evidence failed bottom-up verification",
                    ) from error
                if report is not None:
                    if (
                        report.report_hash != evidence_hash
                        or report.snapshot_hash != self.campaign.snapshot_hash
                        or report.qlib_view_hash != self.campaign.qlib_view_hash
                    ):
                        _raise(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "trial ValidationReport differs from campaign snapshot bindings",
                        )
                    validation_hashes.append(evidence_hash)
            if verify_failure is not None:
                try:
                    failure = verify_failure(evidence_hash)
                except (ValueError, AttributeError) as error:
                    raise AutonomousOrchestrationError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "trial execution failure evidence failed bottom-up verification",
                    ) from error
                if failure is not None:
                    if (
                        failure.content_hash != evidence_hash
                        or failure.campaign_hash != self.campaign.content_hash
                        or failure.snapshot_hash != self.campaign.snapshot_hash
                        or failure.candidate_hash != trial.candidate_hash
                    ):
                        _raise(
                            ReasonCode.ARTIFACT_CORRUPTED,
                            "trial execution failure evidence binding differs",
                        )
                    failure_hashes.append(evidence_hash)

        if len(result_hashes) > 1 or len(validation_hashes) > 1 or len(failure_hashes) > 1:
            _raise(
                ReasonCode.ARTIFACT_CORRUPTED,
                "trial binds multiple execution result, validation, or failure authorities",
            )
        result_hash = result_hashes[0] if result_hashes else None
        validation_hash = validation_hashes[0] if validation_hashes else None
        if result_hash is not None and result_hash not in snapshot.node_object_hashes:
            if verify_result is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ResearchResult verifier is unavailable")
            manifest = verify_result(result_hash)
            if manifest is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ResearchResult evidence disappeared")
            self._append_ledger_object(
                contract=manifest,
                object_hash=result_hash,
                node_kind=ResearchLedgerNodeKind.RESEARCH_RESULT,
                authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
                node_id=f"research-result-{result_hash}",
                occurred_at=occurred_at,
                campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
                agent_run_hash=None,
                parent_object_hashes=(trial_hash,),
            )
            snapshot = self._current_snapshot(occurred_at, ())
        if validation_hash is not None and validation_hash not in snapshot.node_object_hashes:
            if verify_validation is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ValidationReport verifier is unavailable")
            report = verify_validation(validation_hash)
            if report is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ValidationReport evidence disappeared")
            parents = tuple(sorted({trial_hash, *result_hashes}))
            self._append_ledger_object(
                contract=report,
                object_hash=validation_hash,
                node_kind=ResearchLedgerNodeKind.VALIDATION_REPORT,
                authority=LedgerAssertionAuthority.DETERMINISTIC_VERDICT,
                node_id=f"validation-report-{validation_hash}",
                occurred_at=occurred_at,
                campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
                agent_run_hash=None,
                parent_object_hashes=parents,
                verdict_report_hash=validation_hash,
            )
            snapshot = self._current_snapshot(occurred_at, ())
        failure_hash = failure_hashes[0] if failure_hashes else None
        if failure_hash is not None and failure_hash not in snapshot.node_object_hashes:
            if verify_failure is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "execution failure verifier is unavailable")
            failure = verify_failure(failure_hash)
            if failure is None:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "execution failure evidence disappeared")
            self._append_ledger_object(
                contract=failure,
                object_hash=failure_hash,
                node_kind=ResearchLedgerNodeKind.EXPERIMENT,
                authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
                node_id=f"execution-failure-{failure_hash}",
                occurred_at=occurred_at,
                campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
                agent_run_hash=None,
                parent_object_hashes=(trial_hash,),
            )
            snapshot = self._current_snapshot(occurred_at, ())
        return snapshot

    def _append_proposal_if_missing(
        self,
        proposal: AutonomousCandidateProposal,
        response: AutonomousAgentResponse,
        context_pack: ResearchContextPack,
        snapshot: ResearchLedgerSnapshot,
        occurred_at: datetime,
    ) -> ResearchLedgerSnapshot:
        if proposal.content_hash in snapshot.node_object_hashes:
            return snapshot
        self._append_ledger_object(
            contract=proposal,
            object_hash=proposal.content_hash,
            node_kind=ResearchLedgerNodeKind.FACTOR_PROPOSAL,
            authority=LedgerAssertionAuthority.AGENT_PROPOSAL,
            node_id=f"candidate-proposal-{response.manifest.transcript_hash}-{proposal.content_hash}",
            occurred_at=occurred_at,
            campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
            agent_run_hash=response.manifest.transcript_hash,
            parent_object_hashes=tuple(
                sorted({item.object_ref.object_hash for item in context_pack.items})
            ),
        )
        return self._current_snapshot(occurred_at, ())

    def _append_ledger_object(
        self,
        *,
        contract: CanonicalContract,
        object_hash: str,
        node_kind: ResearchLedgerNodeKind,
        authority: LedgerAssertionAuthority,
        node_id: str,
        occurred_at: datetime,
        campaign_access: LedgerObjectAccess,
        agent_run_hash: str | None,
        parent_object_hashes: tuple[str, ...],
        verdict_report_hash: str | None = None,
    ) -> None:
        encoded = contract.canonical_bytes()
        if sha256_bytes(encoded) != object_hash:
            _raise(
                ReasonCode.ARTIFACT_CORRUPTED, "Ledger object hash differs from canonical content"
            )
        reference = ResearchLedgerObjectRef(
            object_hash=object_hash,
            media_type="application/json",
            source_domain="quantos-autonomous",
            access=campaign_access,
            campaign_hash=self.campaign.content_hash,
        )
        try:
            self.ledger_service.append(
                ledger_id=self.ledger_id,
                node_id=node_id,
                node_kind=node_kind,
                object_ref=reference,
                object_bytes=encoded,
                authority=authority,
                occurred_at=occurred_at,
                parent_object_hashes=parent_object_hashes,
                agent_run_hash=agent_run_hash,
                verdict_report_hash=verdict_report_hash,
            )
        except ResearchLedgerError as error:
            raise AutonomousOrchestrationError(error.reason_code, str(error)) from error

    def _selection_handoff(
        self,
        events: tuple[CampaignChainEvent, ...],
        *,
        started_at: datetime,
        stopping_reason: AutonomousStoppingReason,
    ) -> tuple[AutonomousLoopReport, tuple[CampaignChainEvent, ...]]:
        try:
            report, report_path = self.selection_service.publish_report(
                events, self.selection_artifact_root
            )
            report = self.selection_service.verify_report(report_path, events)
        except CampaignSelectionError as error:
            raise AutonomousOrchestrationError(error.reason_code, str(error)) from error
        event_time = self._next_event_time(started_at, events, self.initial_ledger_snapshot)
        parent_hashes = tuple(
            sorted(
                sha256_bytes(event.trial.canonical_bytes())
                for event in events
                if isinstance(event, ResearchCampaignEvent)
                and event.event_type is CampaignEventType.TRIAL_RECORDED
                and event.trial is not None
            )
        )
        self._append_ledger_object(
            contract=report,
            object_hash=report.report_hash,
            node_kind=ResearchLedgerNodeKind.CAMPAIGN_SELECTION_REPORT,
            authority=LedgerAssertionAuthority.DETERMINISTIC_VERDICT,
            node_id=f"campaign-selection-{report.report_hash}",
            occurred_at=event_time,
            campaign_access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
            agent_run_hash=None,
            parent_object_hashes=parent_hashes,
            verdict_report_hash=report.report_hash,
        )
        ledger_snapshot = self._current_snapshot(event_time, events)
        selection_event_hash: str | None = None
        if report.verdict is CampaignSelectionVerdict.SELECTED:
            try:
                selection_event = self.selection_service.freeze_selection(
                    self.governor,
                    events,
                    report_path,
                    event_id=uuid5(_AUTONOMOUS_EVENT_NAMESPACE, report.report_hash),
                    occurred_at=event_time + timedelta(seconds=1),
                )
            except CampaignSelectionError as error:
                raise AutonomousOrchestrationError(error.reason_code, str(error)) from error
            events = self.event_store.append(
                selection_event, self.governor, self.campaign, self.budget
            )
            selection_event_hash = selection_event.content_hash
            state = AutonomousLoopState.READY_FOR_SEALED_CONFIRMATION
        else:
            close = self.governor.close(
                self.campaign,
                self.budget,
                events,
                event_id=uuid5(
                    _AUTONOMOUS_EVENT_NAMESPACE,
                    f"closed:{self.campaign.content_hash}:{report.report_hash}",
                ),
                occurred_at=event_time + timedelta(seconds=1),
                reason=f"P14c {report.verdict.value}: no sealed confirmation authority",
            )
            events = self.event_store.append(close, self.governor, self.campaign, self.budget)
            state = AutonomousLoopState.SELECTION_COMPLETE
        events, ledger_snapshot = self._reconcile_ledger(events, ledger_snapshot, event_time)
        projection = self.governor.project(self.campaign, self.budget, events)
        exchanges = self._exchanges_for_events(events)
        trial_events = tuple(
            event
            for event in events
            if isinstance(event, ResearchCampaignEvent)
            and event.event_type is CampaignEventType.TRIAL_RECORDED
            and event.trial is not None
        )
        report_contract = AutonomousLoopReport(
            campaign_hash=self.campaign.content_hash,
            family_hash=self.family.content_hash,
            budget_hash=self.budget.content_hash,
            candidate_manifest_hash=self.manifest.content_hash,
            campaign_policy_hash=self.campaign_policy.content_hash,
            agent_run_policy_hash=self.agent_run_policy.content_hash,
            initial_ledger_snapshot_hash=self.initial_ledger_snapshot.content_hash,
            final_ledger_snapshot_hash=ledger_snapshot.content_hash,
            agent_request_hashes=tuple(item.request.content_hash for item in exchanges),
            agent_run_hashes=tuple(item.response.manifest.transcript_hash for item in exchanges),
            agent_manifest_hashes=tuple(item.response.manifest.content_hash for item in exchanges),
            context_pack_hashes=tuple(item.request.context_pack.content_hash for item in exchanges),
            proposal_hashes=tuple(item.response.proposal_hash for item in exchanges),
            trial_event_hashes=tuple(event.content_hash for event in trial_events),
            campaign_event_hashes=tuple(event.content_hash for event in events),
            final_campaign_event_hash=events[-1].content_hash,
            trial_count=len(trial_events),
            agent_run_count=len(exchanges),
            stopping_reason=stopping_reason,
            budget=AutonomousBudgetView.from_usage(
                self.budget,
                trials=projection.trial_count,
                agent_runs=projection.agent_run_count,
                distinct_candidates=projection.distinct_candidate_count,
                executions=projection.execution_count,
                validation_rounds=projection.validation_round_count,
                compute_seconds=projection.compute_seconds,
            ),
            selection_report_hash=report.report_hash,
            selection_event_hash=selection_event_hash,
            state=state,
            limitations=(
                "FR03_NO_GO_LIVE_AGENT_RUNTIME_NOT_USED",
                "P14D_A_OFFLINE_ORCHESTRATION_EVIDENCE_ONLY",
                "P14D_B_DOUBLE_ROOT_QUALIFICATION_PENDING",
                "REAL_MARKET_CONCLUSION_NOT_ESTABLISHED",
            ),
        )
        report_path = self.report_store.publish(report_contract)
        verified_report = self.report_store.verify(report_contract.content_hash)
        if report_path.name != f"sha256-{verified_report.content_hash}.json":
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "published loop report path is inconsistent")
        return verified_report, events

    def _exchanges_for_events(
        self, events: tuple[CampaignChainEvent, ...]
    ) -> tuple[AutonomousAgentExchangeArtifact, ...]:
        exchanges: list[AutonomousAgentExchangeArtifact] = []
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, ResearchCampaignEvent) or event.trial is None:
                continue
            run_hash = event.trial.agent_run_hash
            if run_hash is None or run_hash in seen:
                continue
            exchange = self.exchange_store.for_run_hash(run_hash)
            if exchange is None:
                # Historical campaign trials may predate P14d and are not AgentDriver outputs.
                continue
            if (
                exchange.response.proposal_hash != event.trial.proposal_hash
                or self._extract_candidate_hash(exchange.response.proposal_bytes)
                != event.trial.candidate_hash
            ):
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "campaign trial does not match its AgentRun")
            seen.add(run_hash)
            exchanges.append(exchange)
        return tuple(exchanges)


__all__ = [
    "AutonomousAgentDriver",
    "AutonomousAgentExchangeStore",
    "AutonomousCampaignOrchestrator",
    "AutonomousLoopReportStore",
    "AutonomousOrchestrationError",
    "CampaignEventStore",
    "DeterministicResearchExecutionPort",
    "ReplayAgentDriver",
    "ScriptedAgentDriver",
]
