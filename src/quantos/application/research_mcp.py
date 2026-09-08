"""Restricted typed facade over existing deterministic research services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, cast

from pydantic import ValidationError

from quantos.application.proposals import ProposalCompilationError, compile_experiment_proposal
from quantos.application.security import AgentRequestBoundary, SecurityBoundaryError
from quantos.artifacts.store import (
    ArtifactConflictError,
    atomic_write_bytes,
    exclusive_directory_lock,
)
from quantos.contracts.agent import (
    AgentCapability,
    AgentCapabilityPolicy,
    ExperimentProposalSpec,
    FactorProposalSpec,
    HypothesisProposal,
    ObservationProposal,
)
from quantos.contracts.base import CanonicalContract
from quantos.contracts.campaign import ResearchCampaignSpec, ResearchFamilySpec
from quantos.contracts.proposals import CompiledExperimentProposal
from quantos.contracts.qlib_view import QlibViewManifest, QlibViewSpec
from quantos.contracts.registry import (
    RegistryExperimentManifest,
    StrategyVersionRecord,
)
from quantos.contracts.research_mcp import (
    DatasetDescription,
    DatasetFieldCatalog,
    DatasetFieldDescriptor,
    DatasetFieldKind,
    DatasetLookupRequest,
    ExecutionJob,
    ExecutionJobEvent,
    ExecutionJobReceipt,
    ExecutionJobState,
    ExecutionOutcome,
    ExperimentExecutionRequest,
    ExperimentResolutionReceipt,
    ExperimentResolutionRequest,
    JobLookupRequest,
    McpWriteAuditEvent,
    RegistryGetRequest,
    RegistryResourceKind,
    RegistrySearchHit,
    RegistrySearchRequest,
    RegistrySearchResult,
    ValidationLookupRequest,
)
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict
from quantos.contracts.validation import ValidationReport
from quantos.registry import RegistryError, RegistryService


class ResearchMcpError(ValueError):
    """A typed MCP request failed closed with a stable reason code."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class DatasetBinding:
    snapshot: DataSnapshotManifest
    qlib_view: QlibViewManifest
    qlib_view_spec: QlibViewSpec

    def __post_init__(self) -> None:
        if (
            self.qlib_view.source_snapshot_hash != self.snapshot.snapshot_hash
            or self.qlib_view.view_spec_hash != self.qlib_view_spec.content_hash
            or self.qlib_view_spec.source_snapshot_hash != self.snapshot.snapshot_hash
        ):
            raise ValueError("dataset binding hashes disagree")


@dataclass(frozen=True)
class ProposalChainBinding:
    observation: ObservationProposal
    hypothesis: HypothesisProposal
    factor: FactorProposalSpec
    experiment: ExperimentProposalSpec
    campaign: ResearchCampaignSpec
    family: ResearchFamilySpec


Executor = Callable[[CompiledExperimentProposal], ExecutionOutcome]
C = TypeVar("C", bound=CanonicalContract)


def research_mcp_policy(*, max_requests: int = 256) -> AgentCapabilityPolicy:
    capabilities = (
        AgentCapability.DATASET_DESCRIBE,
        AgentCapability.DATASET_FIELDS,
        AgentCapability.EXPERIMENT_REQUEST_EXECUTION,
        AgentCapability.EXPERIMENT_RESOLVE,
        AgentCapability.JOB_GET,
        AgentCapability.REGISTRY_GET,
        AgentCapability.REGISTRY_SEARCH,
        AgentCapability.VALIDATION_GET,
    )
    return AgentCapabilityPolicy(
        policy_id="p11-research-mcp-v1",
        capabilities=tuple(sorted(capabilities, key=str)),
        max_payload_bytes=262_144,
        max_payload_depth=24,
        max_payload_nodes=10_000,
        max_string_bytes=65_536,
        max_requests=max_requests,
    )


class ResearchMcpService:
    """Map typed requests to verified services without exposing paths or authority controls."""

    def __init__(
        self,
        root: Path,
        *,
        datasets: Mapping[str, DatasetBinding],
        proposal_chains: Mapping[str, ProposalChainBinding],
        validations: Mapping[str, ValidationReport] | None = None,
        validation_loader: Callable[[str], ValidationReport] | None = None,
        registry: RegistryService | None = None,
        executor: Executor | None = None,
        max_queued_jobs: int = 8,
        max_timeout_seconds: int = 3_600,
        policy: AgentCapabilityPolicy | None = None,
    ) -> None:
        if max_queued_jobs < 1 or max_timeout_seconds < 1:
            raise ValueError("execution queue and timeout limits must be positive")
        self._root = root
        self._datasets = dict(datasets)
        self._proposal_chains = dict(proposal_chains)
        self._validations = dict(validations or {})
        self._validation_loader = validation_loader
        self._registry = registry
        self._executor = executor
        self._max_queued_jobs = max_queued_jobs
        self._max_timeout_seconds = max_timeout_seconds
        self._boundary = AgentRequestBoundary.from_policy(policy or research_mcp_policy())
        self._compiled: dict[str, CompiledExperimentProposal] = {}
        for digest, binding in self._datasets.items():
            if digest != binding.snapshot.snapshot_hash:
                raise ValueError("dataset catalog key is not its snapshot hash")
        for digest, binding in self._proposal_chains.items():
            if digest != binding.experiment.content_hash:
                raise ValueError("proposal catalog key is not its experiment proposal hash")
        for digest, report in self._validations.items():
            if digest != report.report_hash:
                raise ValueError("validation catalog key is not its report hash")

    @property
    def audit_decisions(self):  # inherited immutable decision records
        return self._boundary.audit_decisions

    def call(self, capability: str, payload: bytes) -> CanonicalContract:
        handlers: dict[str, Callable[[dict[str, object]], CanonicalContract]] = {
            AgentCapability.DATASET_DESCRIBE.value: self._dataset_describe,
            AgentCapability.DATASET_FIELDS.value: self._dataset_fields,
            AgentCapability.EXPERIMENT_RESOLVE.value: self._resolve,
            AgentCapability.EXPERIMENT_REQUEST_EXECUTION.value: self._request_execution,
            AgentCapability.JOB_GET.value: self._job_get,
            AgentCapability.VALIDATION_GET.value: self._validation_get,
            AgentCapability.REGISTRY_GET.value: self._registry_get,
            AgentCapability.REGISTRY_SEARCH.value: self._registry_search,
        }
        try:
            accepted = self._boundary.accept(capability, payload)
            handler = handlers.get(capability)
            if handler is None:  # policy and dispatch table must agree
                raise ResearchMcpError(ReasonCode.CAPABILITY_DENIED, "capability is not mapped")
            return handler(accepted)
        except ResearchMcpError:
            raise
        except SecurityBoundaryError as error:
            raise ResearchMcpError(error.reason_code, str(error)) from error
        except ValidationError as error:
            raise ResearchMcpError(ReasonCode.SCHEMA_INVALID, "MCP request is invalid") from error
        except ProposalCompilationError as error:
            raise ResearchMcpError(error.reason_code, str(error)) from error
        except RegistryError as error:
            raise ResearchMcpError(error.reason_code, str(error)) from error

    def _dataset(self, request: DatasetLookupRequest) -> DatasetBinding:
        binding = self._datasets.get(request.snapshot_hash)
        if binding is None:
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "dataset is not admitted")
        if binding.qlib_view.view_hash != request.qlib_view_hash:
            raise ResearchMcpError(
                ReasonCode.SNAPSHOT_HASH_MISMATCH, "Qlib view does not bind the snapshot"
            )
        return binding

    def _dataset_describe(self, payload: dict[str, object]) -> DatasetDescription:
        request = DatasetLookupRequest.model_validate(payload)
        binding = self._dataset(request)
        return DatasetDescription(
            dataset_id=binding.snapshot.dataset_id,
            snapshot_hash=binding.snapshot.snapshot_hash,
            qlib_view_hash=binding.qlib_view.view_hash,
            source_kind=binding.snapshot.source_kind,
            start_date=binding.snapshot.start_date.isoformat(),
            end_date=binding.snapshot.end_date.isoformat(),
            quality_report_hash=binding.snapshot.quality_report_hash,
            qlib_view_spec_hash=binding.qlib_view.view_spec_hash,
            qlib_version=binding.qlib_view.qlib_version,
            limitations=binding.snapshot.limitations,
        )

    def _dataset_fields(self, payload: dict[str, object]) -> DatasetFieldCatalog:
        request = DatasetLookupRequest.model_validate(payload)
        binding = self._dataset(request)
        fields = {
            item: DatasetFieldDescriptor(
                field_name=item,
                field_kind=DatasetFieldKind.QLIB_DERIVED_VIEW,
                source_artifact_hash=binding.qlib_view.view_hash,
            )
            for item in binding.qlib_view_spec.include_fields
        }
        fields["adjusted_close"] = DatasetFieldDescriptor(
            field_name="adjusted_close",
            field_kind=DatasetFieldKind.ADJUSTED_PRICE,
            source_artifact_hash=binding.snapshot.snapshot_hash,
        )
        return DatasetFieldCatalog(
            snapshot_hash=binding.snapshot.snapshot_hash,
            qlib_view_hash=binding.qlib_view.view_hash,
            fields=tuple(fields[name] for name in sorted(fields)),
        )

    def _resolve(self, payload: dict[str, object]) -> ExperimentResolutionReceipt:
        request = ExperimentResolutionRequest.model_validate(payload)
        chain = self._proposal_chains.get(request.experiment_proposal_hash)
        if chain is None:
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "proposal chain is not admitted")
        actual = (
            chain.observation.content_hash,
            chain.hypothesis.content_hash,
            chain.factor.content_hash,
            chain.experiment.content_hash,
            chain.campaign.content_hash,
            chain.family.content_hash,
            chain.campaign.budget_hash,
        )
        expected = (
            request.observation_hash,
            request.hypothesis_hash,
            request.factor_proposal_hash,
            request.experiment_proposal_hash,
            request.campaign_hash,
            request.family_hash,
            request.budget_hash,
        )
        if actual != expected:
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, "proposal binding disagrees")
        compiled = compile_experiment_proposal(
            chain.observation,
            chain.hypothesis,
            chain.factor,
            chain.experiment,
            chain.campaign,
            chain.family,
            agent_run_hashes=request.agent_run_hashes,
        )
        if not set(compiled.input_hashes).issubset(request.input_hashes):
            raise ResearchMcpError(
                ReasonCode.SOURCE_INCOMPLETE, "resolution input set is incomplete"
            )
        receipt = ExperimentResolutionReceipt(
            idempotency_key=request.idempotency_key,
            request_hash=request.content_hash,
            compiled_proposal_hash=compiled.content_hash,
            authoring_spec_hash=compiled.authoring_spec.content_hash,
            input_hashes=request.input_hashes,
        )
        self._publish_resolution(request, compiled, receipt)
        self._compiled[compiled.content_hash] = compiled
        return receipt

    def _publish_resolution(
        self,
        request: ExperimentResolutionRequest,
        compiled: CompiledExperimentProposal,
        receipt: ExperimentResolutionReceipt,
    ) -> None:
        compiled_path = self._root / "compiled" / f"sha256-{compiled.content_hash}.json"
        receipt_path = self._root / "resolution-idempotency" / f"{request.idempotency_key}.json"
        audit = McpWriteAuditEvent(
            idempotency_key=request.idempotency_key,
            capability="experiment.resolve",
            request_hash=request.content_hash,
            response_hash=receipt.content_hash,
            agent_run_hashes=request.agent_run_hashes,
            campaign_hash=request.campaign_hash,
            budget_hash=request.budget_hash,
            input_hashes=request.input_hashes,
        )
        audit_path = self._root / "audit" / "experiment.resolve" / f"{request.idempotency_key}.json"
        with exclusive_directory_lock(self._root):
            existing = self._read_optional(receipt_path, ExperimentResolutionReceipt)
            if existing is not None:
                if existing != receipt:
                    raise ResearchMcpError(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "resolution idempotency key is bound to another request",
                    )
                self._verify_audit(audit_path, audit)
                return
            self._atomic(compiled_path, compiled)
            self._atomic(audit_path, audit)
            self._atomic(receipt_path, receipt)

    def _request_execution(self, payload: dict[str, object]) -> ExecutionJobReceipt:
        request = ExperimentExecutionRequest.model_validate(payload)
        compiled = self._load_compiled(request.compiled_proposal_hash)
        if compiled is None:
            raise ResearchMcpError(
                ReasonCode.SOURCE_INCOMPLETE, "compiled proposal is not admitted in this service"
            )
        required = {
            *compiled.input_hashes,
            request.compiled_proposal_hash,
            request.agent_run_hash,
            request.campaign_hash,
            request.budget_hash,
        }
        if not required.issubset(request.input_hashes):
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "execution inputs are incomplete")
        if request.campaign_hash != compiled.campaign_hash:
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, "execution campaign disagrees")
        if request.timeout_seconds > self._max_timeout_seconds:
            raise ResearchMcpError(
                ReasonCode.RESOURCE_BUDGET_EXCEEDED, "execution timeout exceeds service limit"
            )
        receipt = ExecutionJobReceipt(
            idempotency_key=request.idempotency_key,
            request_hash=request.content_hash,
            job_id=request.content_hash,
            compiled_proposal_hash=request.compiled_proposal_hash,
        )
        receipt_path = self._root / "execution-idempotency" / f"{request.idempotency_key}.json"
        audit = McpWriteAuditEvent(
            idempotency_key=request.idempotency_key,
            capability="experiment.request_execution",
            request_hash=request.content_hash,
            response_hash=receipt.content_hash,
            agent_run_hashes=(request.agent_run_hash,),
            campaign_hash=request.campaign_hash,
            budget_hash=request.budget_hash,
            input_hashes=request.input_hashes,
        )
        audit_path = (
            self._root
            / "audit"
            / "experiment.request_execution"
            / f"{request.idempotency_key}.json"
        )
        with exclusive_directory_lock(self._root):
            existing = self._read_optional(receipt_path, ExecutionJobReceipt)
            if existing is not None:
                if existing != receipt:
                    raise ResearchMcpError(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "execution idempotency key is bound to another request",
                    )
                self._verify_audit(audit_path, audit)
                return existing
            if len(self._queued_jobs()) >= self._max_queued_jobs:
                raise ResearchMcpError(
                    ReasonCode.RESOURCE_BUDGET_EXCEEDED, "execution queue is full"
                )
            self._atomic(self._job_request_path(receipt.job_id), request)
            self._append_job_event(
                ExecutionJobEvent(
                    job_id=receipt.job_id,
                    request_hash=request.content_hash,
                    sequence=1,
                    state=ExecutionJobState.QUEUED,
                )
            )
            self._atomic(audit_path, audit)
            self._atomic(receipt_path, receipt)
        return receipt

    def _job_get(self, payload: dict[str, object]) -> ExecutionJob:
        return self.get_job(JobLookupRequest.model_validate(payload).job_id)

    def get_job(self, job_id: str) -> ExecutionJob:
        request = self._read_required(
            self._job_request_path(job_id), ExperimentExecutionRequest, "execution job"
        )
        if request.content_hash != job_id:
            raise ResearchMcpError(
                ReasonCode.ARTIFACT_CORRUPTED, "execution job identifier is invalid"
            )
        events = self._job_events(job_id)
        current = events[-1]
        return ExecutionJob(
            job_id=job_id,
            request_hash=request.content_hash,
            compiled_proposal_hash=request.compiled_proposal_hash,
            state=current.state,
            event_hashes=tuple(item.content_hash for item in events),
            outcome=current.outcome,
        )

    def run_next(self) -> ExecutionJob | None:
        """Trusted worker entry point; dispatches one job to the configured existing pipeline."""

        queued = self._queued_jobs()
        if not queued:
            return None
        job_id = queued[0]
        request = self._read_required(
            self._job_request_path(job_id), ExperimentExecutionRequest, "execution job"
        )
        compiled = self._load_compiled(request.compiled_proposal_hash)
        if compiled is None or self._executor is None:
            outcome = ExecutionOutcome(
                run_status=RunStatus.FAILED,
                validation_verdict=ValidationVerdict.NOT_EVALUATED,
                compute_seconds=0,
                reason_code=ReasonCode.SOURCE_INCOMPLETE,
            )
            self._append_terminal(job_id, request.content_hash, ExecutionJobState.FAILED, outcome)
            return self.get_job(job_id)
        self._transition_job(
            ExecutionJobState.QUEUED,
            ExecutionJobEvent(
                job_id=job_id,
                request_hash=request.content_hash,
                sequence=2,
                state=ExecutionJobState.RUNNING,
            ),
        )
        try:
            outcome = self._executor(compiled)
        except TimeoutError:
            self._transition_job(
                ExecutionJobState.RUNNING,
                ExecutionJobEvent(
                    job_id=job_id,
                    request_hash=request.content_hash,
                    sequence=3,
                    state=ExecutionJobState.TIMED_OUT,
                    reason_code=ReasonCode.RESOURCE_BUDGET_EXCEEDED,
                ),
            )
            return self.get_job(job_id)
        except Exception:  # deterministic failure semantics; no exception text enters artifacts
            outcome = ExecutionOutcome(
                run_status=RunStatus.FAILED,
                validation_verdict=ValidationVerdict.NOT_EVALUATED,
                compute_seconds=0,
                reason_code=ReasonCode.QLIB_EXECUTION_FAILED,
            )
        if outcome.compute_seconds > request.timeout_seconds:
            self._transition_job(
                ExecutionJobState.RUNNING,
                ExecutionJobEvent(
                    job_id=job_id,
                    request_hash=request.content_hash,
                    sequence=3,
                    state=ExecutionJobState.TIMED_OUT,
                    reason_code=ReasonCode.RESOURCE_BUDGET_EXCEEDED,
                ),
            )
        else:
            state = (
                ExecutionJobState.SUCCEEDED
                if outcome.run_status is RunStatus.SUCCEEDED
                else ExecutionJobState.FAILED
            )
            self._append_terminal(job_id, request.content_hash, state, outcome)
        return self.get_job(job_id)

    def cancel(self, job_id: str) -> ExecutionJob:
        """Trusted cancellation control; Agent capability surface remains read/request only."""

        current = self.get_job(job_id)
        if current.state is not ExecutionJobState.QUEUED:
            raise ResearchMcpError(
                ReasonCode.STATE_TRANSITION_INVALID, "only a queued job can be cancelled"
            )
        self._transition_job(
            ExecutionJobState.QUEUED,
            ExecutionJobEvent(
                job_id=job_id,
                request_hash=current.request_hash,
                sequence=2,
                state=ExecutionJobState.CANCELLED,
                reason_code=ReasonCode.STATE_TRANSITION_INVALID,
            ),
        )
        return self.get_job(job_id)

    def _validation_get(self, payload: dict[str, object]) -> ValidationReport:
        request = ValidationLookupRequest.model_validate(payload)
        report = self._validations.get(request.validation_report_hash)
        if report is None and self._validation_loader is not None:
            report = self._validation_loader(request.validation_report_hash)
        if report is None:
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "ValidationReport is not admitted")
        if report.report_hash != request.validation_report_hash:
            raise ResearchMcpError(
                ReasonCode.ARTIFACT_CORRUPTED, "ValidationReport loader returned another hash"
            )
        return report

    def _registry_get(
        self, payload: dict[str, object]
    ) -> RegistryExperimentManifest | StrategyVersionRecord:
        request = RegistryGetRequest.model_validate(payload)
        registry = self._require_registry()
        if request.resource_kind is RegistryResourceKind.EXPERIMENT:
            return registry.get_experiment(request.logical_id)
        return registry.get_strategy(request.logical_id, version=cast(int, request.version))

    def _registry_search(self, payload: dict[str, object]) -> RegistrySearchResult:
        request = RegistrySearchRequest.model_validate(payload)
        index = self._require_registry().verify()
        hits: list[RegistrySearchHit] = []
        include_experiments = (
            request.experiment_id_prefix is not None or request.strategy_id_prefix is None
        )
        include_strategies = (
            request.strategy_id_prefix is not None or request.experiment_id_prefix is None
        )
        for item in index.experiments if include_experiments else ():
            if request.experiment_id_prefix is None or item.experiment_id.startswith(
                request.experiment_id_prefix
            ):
                hits.append(
                    RegistrySearchHit(
                        resource_kind=RegistryResourceKind.EXPERIMENT,
                        logical_id=item.experiment_id,
                        artifact_hash=item.manifest_hash,
                    )
                )
        for strategy in index.strategies if include_strategies else ():
            if request.strategy_id_prefix is None or strategy.strategy_id.startswith(
                request.strategy_id_prefix
            ):
                hits.extend(
                    RegistrySearchHit(
                        resource_kind=RegistryResourceKind.STRATEGY,
                        logical_id=strategy.strategy_id,
                        version=version.version,
                        artifact_hash=version.content_hash,
                    )
                    for version in strategy.versions
                )
        hits.sort(key=lambda item: (item.resource_kind.value, item.logical_id, item.version or 0))
        return RegistrySearchResult(
            registry_index_hash=index.index_hash,
            hits=tuple(hits[: request.limit]),
            truncated=len(hits) > request.limit,
        )

    def _require_registry(self) -> RegistryService:
        if self._registry is None:
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "Registry is not configured")
        return self._registry

    def _queued_jobs(self) -> tuple[str, ...]:
        root = self._root / "jobs"
        if not root.exists():
            return ()
        queued: list[str] = []
        for path in sorted(root.iterdir()):
            if path.is_dir() and self.get_job(path.name).state is ExecutionJobState.QUEUED:
                queued.append(path.name)
        return tuple(queued)

    def _job_request_path(self, job_id: str) -> Path:
        return self._root / "jobs" / job_id / "request.json"

    def _job_events(self, job_id: str) -> tuple[ExecutionJobEvent, ...]:
        event_root = self._root / "jobs" / job_id / "events"
        if not event_root.is_dir():
            raise ResearchMcpError(ReasonCode.SOURCE_INCOMPLETE, "execution job does not exist")
        event_paths = tuple(sorted(event_root.glob("*.json")))
        events = tuple(
            self._read_required(path, ExecutionJobEvent, "execution event") for path in event_paths
        )
        if not events or tuple(item.sequence for item in events) != tuple(
            range(1, len(events) + 1)
        ):
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, "job event chain is invalid")
        if any(item.job_id != job_id for item in events):
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, "job event binding is invalid")
        if any(
            path.name != f"{event.sequence:06d}-sha256-{event.content_hash}.json"
            for path, event in zip(event_paths, events, strict=True)
        ):
            raise ResearchMcpError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "job event filename is not content addressed",
            )
        states = tuple(item.state for item in events)
        allowed = {
            (ExecutionJobState.QUEUED,),
            (ExecutionJobState.QUEUED, ExecutionJobState.CANCELLED),
            (ExecutionJobState.QUEUED, ExecutionJobState.FAILED),
            (ExecutionJobState.QUEUED, ExecutionJobState.RUNNING),
            (
                ExecutionJobState.QUEUED,
                ExecutionJobState.RUNNING,
                ExecutionJobState.FAILED,
            ),
            (
                ExecutionJobState.QUEUED,
                ExecutionJobState.RUNNING,
                ExecutionJobState.SUCCEEDED,
            ),
            (
                ExecutionJobState.QUEUED,
                ExecutionJobState.RUNNING,
                ExecutionJobState.TIMED_OUT,
            ),
        }
        if states not in allowed:
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, "job state chain is invalid")
        return events

    def _append_terminal(
        self,
        job_id: str,
        request_hash: str,
        state: ExecutionJobState,
        outcome: ExecutionOutcome,
    ) -> None:
        current = self.get_job(job_id)
        self._transition_job(
            current.state,
            ExecutionJobEvent(
                job_id=job_id,
                request_hash=request_hash,
                sequence=3 if current.state is ExecutionJobState.RUNNING else 2,
                state=state,
                outcome=outcome,
            ),
        )

    def _transition_job(self, expected: ExecutionJobState, event: ExecutionJobEvent) -> None:
        with exclusive_directory_lock(self._root):
            current = self.get_job(event.job_id)
            if current.state is not expected or len(current.event_hashes) + 1 != event.sequence:
                raise ResearchMcpError(
                    ReasonCode.STATE_TRANSITION_INVALID, "execution job changed concurrently"
                )
            self._append_job_event(event)

    def _append_job_event(self, event: ExecutionJobEvent) -> None:
        path = (
            self._root
            / "jobs"
            / event.job_id
            / "events"
            / f"{event.sequence:06d}-sha256-{event.content_hash}.json"
        )
        self._atomic(path, event)

    def _load_compiled(self, digest: str) -> CompiledExperimentProposal | None:
        compiled = self._compiled.get(digest)
        path = self._root / "compiled" / f"sha256-{digest}.json"
        if compiled is None and path.exists():
            compiled = self._read_required(
                path, CompiledExperimentProposal, "compiled experiment proposal"
            )
            if compiled.content_hash != digest:
                raise ResearchMcpError(
                    ReasonCode.ARTIFACT_CORRUPTED,
                    "compiled proposal filename does not match its content",
                )
            self._compiled[digest] = compiled
        return compiled

    @staticmethod
    def _atomic(path: Path, contract: CanonicalContract) -> None:
        try:
            atomic_write_bytes(path, contract.canonical_bytes())
        except ArtifactConflictError as error:
            raise ResearchMcpError(
                ReasonCode.DUPLICATE_ID_CONFLICT, "immutable MCP artifact conflicted"
            ) from error

    @staticmethod
    def _verify_audit(path: Path, expected: McpWriteAuditEvent) -> None:
        actual = ResearchMcpService._read_required(path, McpWriteAuditEvent, "MCP audit event")
        if actual != expected:
            raise ResearchMcpError(
                ReasonCode.ARTIFACT_CORRUPTED, "MCP audit event disagrees with its receipt"
            )

    @staticmethod
    def _read_optional(path: Path, contract_type: type[C]) -> C | None:
        if not path.exists():
            return None
        return ResearchMcpService._read_required(path, contract_type, "MCP receipt")

    @staticmethod
    def _read_required(path: Path, contract_type: type[C], label: str) -> C:
        try:
            encoded = path.read_bytes()
            contract = contract_type.model_validate_json(encoded)
        except FileNotFoundError as error:
            raise ResearchMcpError(
                ReasonCode.SOURCE_INCOMPLETE, f"{label} does not exist"
            ) from error
        except (OSError, ValidationError, ValueError) as error:
            raise ResearchMcpError(ReasonCode.ARTIFACT_CORRUPTED, f"{label} is invalid") from error
        if encoded != contract.canonical_bytes():
            raise ResearchMcpError(
                ReasonCode.ARTIFACT_CORRUPTED, f"{label} bytes are not canonical"
            )
        return contract
