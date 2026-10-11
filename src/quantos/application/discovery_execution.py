"""Bounded retrospective discovery through the existing full deterministic execution chain."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from time import perf_counter, process_time
from typing import cast
from uuid import UUID, uuid5

from quantos.application.autonomous_execution import (
    QuantosResearchExecutionAdapter,
    VerifiedExecutionInputs,
    quote_autonomous_workload,
    require_durable_execution_root,
)
from quantos.application.campaigns import ResearchCampaignGovernor
from quantos.application.discovery_admission import verify_discovery_batch
from quantos.application.discovery_generation import GenerationStore
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.agent import CampaignSegment
from quantos.contracts.autonomous import (
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    autonomous_execution_identity,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import (
    CampaignStoppingRule,
    CampaignTrial,
    MultipleTestingPolicy,
    ResearchBudgetSpec,
    ResearchCampaignEvent,
    ResearchCampaignSpec,
)
from quantos.contracts.discovery import (
    DiscoveryBatch,
    DiscoverySubtask,
    GenerationResponse,
    ProposalMapping,
)
from quantos.contracts.discovery_adoption import DiscoveryEvaluationSourceAdoption
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.infrastructure.hosted_storage import (
    LEASE_ENV,
    StorageGuard,
    StorageRejected,
    configured_guard,
)
from quantos.research.qlib.result import research_result_verification_scope

_NAMESPACE = UUID("be71054c-78f5-45a1-a931-01573a8e009d")
_UNSET = object()
_RECOVERY_SCHEMA = "discovery-execution-recovery-reservation/v1"
_RECOVERY_ACCOUNTING = "CONSERVATIVE_FULL_WORKLOAD_PER_SUCCESSOR_ATTEMPT"


def _read_json(path: Path) -> dict[str, object]:
    with opened_directory(path.parent) as parent:
        encoded = read_regular_bytes_at(parent, path.name, max_bytes=16_777_216)
    decoded: object = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ArtifactIntegrityError("discovery execution record is not a JSON object")
    value = cast(dict[str, object], decoded)
    if canonical_json_bytes(value) != encoded:
        raise ArtifactIntegrityError("discovery execution record is not canonical")
    return value


@dataclass(frozen=True)
class DiscoveryExecutionInspection:
    request: AutonomousExecutionRequest
    outcome: AutonomousExecutionResult
    adapter: QuantosResearchExecutionAdapter


class DiscoveryExecutionService:
    """Run frozen singleton subtasks with a batch budget and durable, ordered authority.

    No candidate generation, selection or sealed access is performed here. The
    ``agent_run_hash`` field of the legacy execution request is a compatibility carrier
    for a GenerationResponse hash when generation did not produce an AgentRun. The exact
    successor meaning is retained in each task's generation-authority.json; campaign
    accounting records only an actual declared AgentRun identity, never a fabricated run.
    """

    def __init__(
        self,
        *,
        batch: DiscoveryBatch,
        snapshot_path: Path,
        qlib_view_path: Path,
        output_root: Path,
        workspace: Path,
        generation_root: Path | None = None,
        evaluation_declaration: DiscoveryEvaluationDeclaration | None = None,
    ) -> None:
        verify_discovery_batch(batch)
        if generation_root is None:
            raise ArtifactIntegrityError(
                "discovery execution requires the retained generation originals"
            )
        GenerationStore(generation_root).verify_frozen(batch)
        absolute = output_root.absolute()
        if any(part.is_symlink() for part in (absolute, *absolute.parents)):
            raise ArtifactIntegrityError("discovery execution root must not contain symbolic links")
        require_durable_execution_root(absolute)
        self.batch = batch
        self.snapshot_path = snapshot_path
        self.qlib_view_path = qlib_view_path
        self.output_root = absolute.resolve()
        self.workspace = workspace
        self.generation_root = generation_root
        self.evaluation_declaration = evaluation_declaration
        self.evaluation_bindings = (
            batch.design.bindings
            if evaluation_declaration is None
            else evaluation_declaration.bindings
        )
        self.max_compute_units = (
            batch.design.max_compute_units
            if evaluation_declaration is None
            else evaluation_declaration.max_compute_units
        )
        self.evaluation_identity = (
            batch.content_hash
            if evaluation_declaration is None
            else evaluation_declaration.content_hash
        )
        self._verify_evaluation_declaration()
        self.source_adoption: DiscoveryEvaluationSourceAdoption | None = None
        if evaluation_declaration is not None:
            adopted = DiscoveryEvaluationSourceAdoption.model_validate(
                _read_json(self.output_root / "source-adoption.json")
            )
            if (
                adopted.content_hash != evaluation_declaration.source_adoption_record_hash
                or adopted.original_batch_hash != batch.content_hash
                or adopted.original_design_hash != batch.design.content_hash
                or adopted.original_source_commit != batch.design.bindings.code_commit_hash
                or adopted.evaluation_source_commit != self.evaluation_bindings.code_commit_hash
                or adopted.lockfile_hash != self.evaluation_bindings.lockfile_hash
                or adopted.evaluation_execution_policy_hash
                != self.evaluation_bindings.execution_policy_hash
            ):
                raise ArtifactIntegrityError(
                    "successor source adoption differs from evaluation declaration"
                )
            self.source_adoption = adopted
        self._verify_evaluation_authority()
        self._subtasks = {task.content_hash: task for task in batch.subtasks}
        self._mappings = {
            mapping.subtask_hash: mapping
            for mapping in batch.mappings
            if mapping.status == "ADMITTED"
        }
        self._responses = {item.content_hash: item for item in batch.responses}
        self._adapters: dict[str, QuantosResearchExecutionAdapter] = {}
        self._verified_inputs: VerifiedExecutionInputs | None = None
        self._requests: dict[str, AutonomousExecutionRequest] = {}
        self._campaigns: dict[str, ResearchCampaignSpec] = {}
        self._budgets: dict[str, ResearchBudgetSpec] = {}
        self._governors: dict[str, ResearchCampaignGovernor] = {}
        for task in batch.subtasks:
            self._prepare_task(task, self._mappings[task.content_hash])

    def _verify_evaluation_declaration(self) -> None:
        declaration = self.evaluation_declaration
        if declaration is None:
            return
        original = self.batch.design.bindings
        if (
            declaration.original_batch_hash != self.batch.content_hash
            or declaration.original_design_hash != self.batch.design.content_hash
            or declaration.original_generation_source_commit != original.code_commit_hash
            or declaration.max_compute_units > self.batch.design.max_compute_units
            or declaration.bindings.code_commit_hash == original.code_commit_hash
            or declaration.bindings.model_dump(
                exclude={"code_commit_hash", "execution_policy_hash"}
            )
            != original.model_dump(exclude={"code_commit_hash", "execution_policy_hash"})
        ):
            raise ArtifactIntegrityError("successor evaluation changed its frozen proposal inputs")

    def evaluation_metadata(self) -> dict[str, object]:
        declaration = self.evaluation_declaration
        return {
            "schema_version": "discovery-evaluation-authority/v1",
            "evaluation_identity": self.evaluation_identity,
            "evaluation_declaration_hash": None
            if declaration is None
            else declaration.content_hash,
            "original_batch_hash": self.batch.content_hash,
            "original_design_hash": self.batch.design.content_hash,
            "original_generation_source_commit": self.batch.design.bindings.code_commit_hash,
            "evaluation_bindings": self.evaluation_bindings.model_dump(mode="json"),
            "maximum_compute_units": self.max_compute_units,
            "source_adoption_record_hash": None
            if declaration is None
            else declaration.source_adoption_record_hash,
            "reason": None if declaration is None else declaration.reason,
            "exposure_history_append": []
            if declaration is None
            else list(declaration.exposure_history_append),
            "no_new_generation": True,
            "sealed_confirmation_accessed": False,
        }

    def _verify_evaluation_authority(self) -> None:
        declaration_path = self.output_root / "evaluation-declaration.json"
        authority_path = self.output_root / "evaluation-authority.json"
        declaration = self.evaluation_declaration
        if declaration is None:
            if declaration_path.exists() or authority_path.exists():
                raise ArtifactIntegrityError("successor output requires its evaluation declaration")
            return
        if declaration_path.exists():
            if _read_json(declaration_path) != declaration.model_dump(mode="json") or (
                authority_path.exists() and _read_json(authority_path) != self.evaluation_metadata()
            ):
                raise ArtifactIntegrityError("successor output belongs to a different declaration")
            if not authority_path.exists() and (self.output_root / "batch.json").exists():
                raise ArtifactIntegrityError("published successor batch lacks evaluation authority")
        elif (
            authority_path.exists()
            or (self.output_root / "batch.json").exists()
            or any((self.output_root / "tasks").glob("*/request.json"))
        ):
            raise ArtifactIntegrityError("existing batch authority cannot adopt a new declaration")

    def _save_evaluation_authority(self) -> None:
        self._verify_evaluation_authority()
        if self.evaluation_declaration is not None:
            atomic_write_bytes(
                self.output_root / "evaluation-declaration.json",
                self.evaluation_declaration.canonical_bytes(),
            )
            atomic_write_bytes(
                self.output_root / "evaluation-authority.json",
                canonical_json_bytes(self.evaluation_metadata()),
            )

    def _task_root(self, subtask_hash: str) -> Path:
        if subtask_hash not in self._subtasks:
            raise ValueError("subtask does not belong to the frozen batch")
        return self.output_root / "tasks" / subtask_hash

    def _mapping_response(self, mapping: ProposalMapping) -> GenerationResponse:
        digest = mapping.response_hash
        if digest is None:
            raise ArtifactIntegrityError("admitted task requires its generation response")
        return self._responses[digest]

    def _storage_authority(self, expected_new_bytes: int) -> tuple[StorageGuard, dict[str, object]]:
        """Use the existing exclusive host lease and its complete growth reservation."""
        if type(expected_new_bytes) is not int or expected_new_bytes <= 0:
            raise StorageRejected("STORAGE_ESTIMATE_INVALID")
        try:
            guard = configured_guard()
            guard.require_root(self.output_root)
            guard.require_lease()
            lease = Path(os.environ[LEASE_ENV])
            with opened_directory(lease) as parent:
                encoded = read_regular_bytes_at(parent, "prelaunch.json", max_bytes=16384)
            decoded: object = json.loads(encoded)
            if not isinstance(decoded, dict):
                raise StorageRejected("STORAGE_SUPERVISOR_UNBOUND")
            prelaunch = cast(dict[str, object], decoded)
            leased_bytes = prelaunch.get("expected_new_bytes")
            if type(leased_bytes) is not int or leased_bytes < expected_new_bytes:
                raise StorageRejected("STORAGE_ESTIMATE_EXCEEDS_LEASE")
            facts = guard.check(expected_new_bytes)
            return guard, {
                "expected_new_bytes": expected_new_bytes,
                "storage_policy_hash": guard.policy_hash,
                "lease_prelaunch_hash": sha256_bytes(encoded),
                "lease_reserved_new_bytes": leased_bytes,
                "growth_scope": "ENTIRE_BATCH_AND_ALL_CONCURRENT_LEASE_CHILDREN",
                "initial_capacity": facts,
            }
        except (OSError, ValueError, KeyError, TypeError):
            raise StorageRejected("STORAGE_OBSERVATION_UNAVAILABLE") from None

    def _prepare_task(self, task: DiscoverySubtask, mapping: ProposalMapping) -> None:
        design = self.batch.design
        if mapping.response_hash is None:
            raise ArtifactIntegrityError("admitted task requires its generation response")
        response = self._mapping_response(mapping)
        budget = ResearchBudgetSpec(
            budget_id=f"discovery-{task.content_hash[:32]}",
            max_trials=1,
            max_distinct_candidates=1,
            max_agent_runs=1,
            max_executions=1,
            max_validation_rounds=1,
            max_compute_seconds=self.max_compute_units,
        )
        sources = tuple(
            sorted(
                {
                    *design.evidence_hashes,
                    self.batch.content_hash,
                    mapping.content_hash,
                    response.content_hash,
                    mapping.request_hash,
                    mapping.reservation_hash,
                    *(
                        ()
                        if self.evaluation_declaration is None
                        else (
                            self.evaluation_identity,
                            self.evaluation_declaration.source_adoption_record_hash,
                        )
                    ),
                }
            )
        )
        campaign = ResearchCampaignSpec(
            campaign_id=f"discovery-{task.content_hash[:32]}",
            research_question=design.research_question,
            family_hash=task.family.content_hash,
            budget_hash=budget.content_hash,
            evidence_hashes=sources,
            ledger_snapshot_hash=design.ledger_snapshot_hash,
            snapshot_hash=design.snapshot_hash,
            qlib_view_hash=design.qlib_view_hash,
            development=design.research_policy.validation,
            validation=design.research_policy.test,
            sealed_confirmation=design.sealed_confirmation,
            multiple_testing_policy=MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY,
            stopping_rule=CampaignStoppingRule.BUDGET_EXHAUSTED_OR_MANUAL_CLOSE,
        )
        candidate = task.manifest.candidates[0]
        identity = autonomous_execution_identity(
            campaign_hash=campaign.content_hash,
            family_hash=task.family.content_hash,
            budget_hash=budget.content_hash,
            candidate_manifest_hash=task.manifest.content_hash,
            candidate=candidate,
            snapshot_hash=design.snapshot_hash,
            qlib_view_hash=design.qlib_view_hash,
            segment=CampaignSegment.VALIDATION,
            segment_start=design.research_policy.test.start,
            segment_end=design.research_policy.test.end,
            trial_ordinal=1,
            bindings=self.evaluation_bindings,
        )
        bindings = self.evaluation_bindings.model_dump(mode="python", exclude={"schema_version"})
        request = AutonomousExecutionRequest(
            **bindings,
            idempotency_key=identity,
            execution_identity=identity,
            trial_ordinal=1,
            campaign_hash=campaign.content_hash,
            family_hash=task.family.content_hash,
            budget_hash=budget.content_hash,
            candidate_manifest_hash=task.manifest.content_hash,
            candidate=candidate,
            candidate_exact_expression_hash=candidate.exact_expression_hash,
            candidate_structural_expression_hash=candidate.structural_expression_hash,
            snapshot_hash=design.snapshot_hash,
            qlib_view_hash=design.qlib_view_hash,
            segment=CampaignSegment.VALIDATION,
            segment_start=design.research_policy.test.start,
            segment_end=design.research_policy.test.end,
            agent_run_hash=response.agent_run_hash or response.content_hash,
            remaining_executions=1,
            remaining_validation_rounds=1,
            remaining_compute_seconds=self.max_compute_units,
        )
        self._requests[task.content_hash] = request
        self._campaigns[task.content_hash] = campaign
        self._budgets[task.content_hash] = budget
        self._governors[task.content_hash] = ResearchCampaignGovernor(
            task.family,
            task.template,
            task.manifest,
        )

    def task_request(self, subtask_hash: str) -> AutonomousExecutionRequest:
        self._task_root(subtask_hash)
        return self._requests[subtask_hash]

    def task_adapter(self, subtask_hash: str) -> QuantosResearchExecutionAdapter:
        self._task_root(subtask_hash)
        if subtask_hash not in self._adapters:
            task, design = self._subtasks[subtask_hash], self.batch.design
            self._adapters[subtask_hash] = QuantosResearchExecutionAdapter(
                campaign=self._campaigns[subtask_hash],
                family=task.family,
                budget=self._budgets[subtask_hash],
                template=task.template,
                manifest=task.manifest,
                snapshot_path=self.snapshot_path,
                qlib_view_path=self.qlib_view_path,
                base_authoring=design.authoring,
                research_policy=design.research_policy,
                validation_policy=design.validation_policy,
                cost_policy=design.cost_policy,
                backtest_policy=design.backtest_policy,
                bindings=self.evaluation_bindings,
                output_root=self._task_root(subtask_hash),
                workspace=self.workspace,
                discovery_stage_recovery=True,
                discovery_profile="singleton-full-chain/v1",
                _verified_inputs=self._verified_inputs,
                discovery_source_adoption=self.source_adoption,
            )
        return self._adapters[subtask_hash]

    def inspect_completed_execution(self, subtask_hash: str) -> DiscoveryExecutionInspection | None:
        """Read-only bottom-up verification; inspection never creates task authority."""
        with research_result_verification_scope():
            request, adapter = self.task_request(subtask_hash), self.task_adapter(subtask_hash)
            outcome = adapter.inspect_completed_execution(request)
            if outcome is None:
                return None
            return DiscoveryExecutionInspection(request, outcome, adapter)

    def _save_task_inputs(self, subtask_hash: str, charge: int) -> None:
        root, mapping = self._task_root(subtask_hash), self._mappings[subtask_hash]
        response = self._mapping_response(mapping)
        for name, contract in (
            ("subtask.json", self._subtasks[subtask_hash]),
            ("campaign.json", self._campaigns[subtask_hash]),
            ("budget.json", self._budgets[subtask_hash]),
            ("request.json", self._requests[subtask_hash]),
        ):
            atomic_write_bytes(root / name, contract.canonical_bytes())
        atomic_write_bytes(
            root / "generation-authority.json",
            canonical_json_bytes(
                {
                    "schema_version": "discovery-execution-generation-authority/v1",
                    "batch_hash": self.batch.content_hash,
                    "subtask_hash": subtask_hash,
                    "mapping_hash": mapping.content_hash,
                    "generation_request_hash": mapping.request_hash,
                    "generation_response_hash": response.content_hash,
                    "declared_agent_run_hash": response.agent_run_hash,
                    "legacy_request_agent_run_hash_meaning": (
                        "DECLARED_AGENT_RUN"
                        if response.agent_run_hash
                        else "GENERATION_RESPONSE_COMPATIBILITY_CARRIER"
                    ),
                    "agent_run_original_verification": (
                        "GENERATION_STORE_FREEZE_BOUNDARY"
                        if response.agent_run_hash
                        else "NOT_APPLICABLE"
                    ),
                    "llm_runtime_generation_used": response.producer == "SDK_CAPTURE",
                    "sealed_confirmation_accessed": False,
                    "deterministic_compute_units_quoted": charge,
                }
            ),
        )

    def _events(self, subtask_hash: str) -> tuple[ResearchCampaignEvent, ...]:
        root = self._task_root(subtask_hash) / "campaign-events"
        events: list[ResearchCampaignEvent] = []
        for path in sorted(root.glob("*.json")):
            with opened_directory(root) as parent:
                encoded = read_regular_bytes_at(parent, path.name, max_bytes=65536)
            event = ResearchCampaignEvent.model_validate_json(encoded)
            if event.canonical_bytes() != encoded:
                raise ArtifactIntegrityError("discovery campaign event is not canonical")
            events.append(event)
        self._governors[subtask_hash].project(
            self._campaigns[subtask_hash],
            self._budgets[subtask_hash],
            tuple(events),
        )
        return tuple(events)

    def _save_event(self, subtask_hash: str, event: ResearchCampaignEvent) -> None:
        atomic_write_bytes(
            self._task_root(subtask_hash) / "campaign-events" / f"{event.sequence:08d}.json",
            event.canonical_bytes(),
        )

    def _record_outcome(self, subtask_hash: str, outcome: AutonomousExecutionResult) -> None:
        root, mapping = self._task_root(subtask_hash), self._mappings[subtask_hash]
        response, request = self._mapping_response(mapping), self._requests[subtask_hash]
        if outcome.request_hash != request.content_hash:
            raise ArtifactIntegrityError("discovery outcome does not bind its exact request")
        atomic_write_bytes(root / "outcome.json", outcome.canonical_bytes())
        events = self._events(subtask_hash)
        trial = CampaignTrial(
            trial_id=f"discovery-{request.execution_identity[:32]}",
            idempotency_key=request.execution_identity,
            proposal_hash=mapping.content_hash,
            candidate_hash=request.candidate.content_hash,
            segment=CampaignSegment.VALIDATION,
            outcome=outcome.outcome,
            agent_run_hash=response.agent_run_hash,
            execution_requested=outcome.execution_requested,
            compute_seconds=outcome.compute_seconds,
            evidence_hashes=tuple(
                sorted({*outcome.evidence_hashes, *self._campaigns[subtask_hash].evidence_hashes})
            ),
        )
        event = self._governors[subtask_hash].record_trial(
            self._campaigns[subtask_hash],
            self._budgets[subtask_hash],
            events,
            trial,
            event_id=uuid5(_NAMESPACE, f"{request.execution_identity}:trial"),
            occurred_at=datetime.combine(request.segment_end, datetime.min.time(), tzinfo=UTC),
        )
        self._save_event(subtask_hash, event)

    def _attempt_records(self, subtask_hash: str) -> tuple[dict[str, object], ...]:
        request = self.task_request(subtask_hash)
        root = self._task_root(subtask_hash) / "attempts"
        records: list[dict[str, object]] = []
        recovery_reservations = self._recovery_reservations()
        for path in sorted(root.glob("*/reservation.json")):
            reservation = _read_json(path)
            ordinal = len(records) + 1
            if (
                reservation
                != {
                    "schema_version": "discovery-execution-attempt-reservation/v1",
                    "batch_hash": self.batch.content_hash,
                    "subtask_hash": subtask_hash,
                    "request_hash": request.content_hash,
                    "execution_identity": request.execution_identity,
                    "ordinal": ordinal,
                }
                or path.parent.name != f"{ordinal:08d}"
            ):
                raise ArtifactIntegrityError(
                    "discovery execution attempt reservation is inconsistent"
                )
            if ordinal > 1 and (subtask_hash, ordinal) not in recovery_reservations:
                raise ArtifactIntegrityError(
                    "successor attempt lacks its original compute reservation"
                )
            completion = path.parent / "completion.json"
            record: dict[str, object] = (
                _read_json(completion)
                if completion.exists()
                else {
                    "status": "UNFINISHED",
                    "wall_seconds": None,
                    "cpu_seconds": None,
                }
            )
            if completion.exists() and (
                record.get("reservation_hash") != sha256_bytes(canonical_json_bytes(reservation))
                or record.get("request_hash") != request.content_hash
                or record.get("status") not in {"SUCCEEDED", "FAILED"}
            ):
                raise ArtifactIntegrityError("discovery execution completion is inconsistent")
            for name in ("wall_seconds", "cpu_seconds"):
                value = record.get(name)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isfinite(value)
                    or value < 0
                ):
                    raise ArtifactIntegrityError("discovery execution measurement is invalid")
            records.append(record)
        return tuple(records)

    def _recovery_reservations(self) -> dict[tuple[str, int], int]:
        """Reconcile immutable, conservatively charged successor attempts."""
        records: dict[tuple[str, int], int] = {}
        for path in sorted((self.output_root / "recovery-reservations").glob("*/*.json")):
            key = path.parent.name
            request = self.task_request(key)
            value = _read_json(path)
            ordinal = value.get("ordinal")
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 2:
                raise ArtifactIntegrityError("recovery reservation ordinal is invalid")
            expected = {
                "schema_version": _RECOVERY_SCHEMA,
                "batch_hash": self.batch.content_hash,
                "subtask_hash": key,
                "request_hash": request.content_hash,
                "ordinal": ordinal,
                "reserved_compute_units": self._task_charge(key),
                "accounting": _RECOVERY_ACCOUNTING,
            }
            if (
                value != expected
                or path.name != f"{ordinal:08d}.json"
                or (ordinal > 1 + self.batch.design.max_execution_resumes_per_subtask)
            ):
                raise ArtifactIntegrityError(
                    "recovery reservation escaped the frozen attempt budget"
                )
            records[(key, ordinal)] = self._task_charge(key)
        return records

    def task_state(
        self,
        subtask_hash: str,
        *,
        inspection: DiscoveryExecutionInspection | object | None = _UNSET,
    ) -> dict[str, object]:
        """Read retained status and observed costs; incomplete attempts remain unavailable."""
        root = self._task_root(subtask_hash)
        attempts = self._attempt_records(subtask_hash)
        complete = bool(attempts) and all(
            item["status"] != "UNFINISHED"
            and item.get("wall_seconds") is not None
            and item.get("cpu_seconds") is not None
            for item in attempts
        )
        wall_values = [
            float(cast(int | float, item["wall_seconds"]))
            for item in attempts
            if item.get("wall_seconds") is not None
        ]
        cpu_values = [
            float(cast(int | float, item["cpu_seconds"]))
            for item in attempts
            if item.get("cpu_seconds") is not None
        ]
        wall, cpu = sum(wall_values), sum(cpu_values)
        if inspection is _UNSET:
            inspection = self.inspect_completed_execution(subtask_hash)
        if inspection is not None and not isinstance(inspection, DiscoveryExecutionInspection):
            raise ValueError("invalid discovery execution inspection")
        if isinstance(inspection, DiscoveryExecutionInspection) and (
            inspection.request != self.task_request(subtask_hash)
        ):
            raise ArtifactIntegrityError("task state inspection binds a different task")
        reason = None
        if inspection is not None:
            status = "COMPLETED"
        elif attempts and attempts[-1]["status"] == "FAILED":
            status, reason = "FAILED", "EXECUTION_EXCEPTION"
        elif (root / "not-executed.json").exists():
            record = _read_json(root / "not-executed.json")
            if record.get("request_hash") != self.task_request(subtask_hash).content_hash or (
                record.get("batch_hash") != self.batch.content_hash
            ):
                raise ArtifactIntegrityError("not-executed record escaped its task")
            status, reason = "NOT_EXECUTED", record.get("reason")
        elif attempts:
            status = "UNFINISHED"
        else:
            status = "NOT_STARTED"
        return {
            "status": status,
            "reason": reason,
            "attempt_count": len(attempts),
            "wall_seconds": wall if complete else None,
            "cpu_seconds": cpu if complete else None,
            "observed_wall_seconds": wall if wall_values else None,
            "observed_cpu_seconds": cpu if cpu_values else None,
            "measurements_complete": complete,
            "deterministic_compute_units": inspection.outcome.compute_seconds
            if inspection
            else None,
            "execution_receipt_hash": inspection.outcome.execution_artifact_hash
            if inspection
            else None,
            "outcome": inspection.outcome.outcome.value if inspection else None,
            "recovery_reserved_compute_units": sum(
                value
                for (key, _), value in self._recovery_reservations().items()
                if key == subtask_hash
            ),
            "sealed_confirmation_accessed": False,
        }

    def _task_charge(self, subtask_hash: str) -> int:
        payload = self.batch.design.authoring.model_dump(mode="python")
        payload["expression"] = self.task_request(subtask_hash).candidate.expression.model_dump(
            mode="python"
        )
        return quote_autonomous_workload(
            ExperimentAuthoringSpec.model_validate(payload),
            self.batch.design.validation_policy,
        )

    def quote(self) -> int:
        """Return the entire frozen batch workload quote without writes or dataset scans."""
        return sum(self._task_charge(task.content_hash) for task in self.batch.subtasks)

    def batch_state(self) -> dict[str, object]:
        """Read total measured execution cost, including shared input verification.

        Batch totals overlap task/stage timings and must never be added to them. CPU
        measurements cover the calling process; child-process CPU is unavailable.
        """
        attempts: list[dict[str, object]] = []
        for ordinal, path in enumerate(
            sorted((self.output_root / "batch-attempts").glob("*/reservation.json")), start=1
        ):
            reservation = _read_json(path)
            if (
                path.parent.name != f"{ordinal:08d}"
                or reservation.get("batch_hash") != self.batch.content_hash
                or (
                    reservation.get("ordinal") != ordinal
                    or reservation.get("schema_version")
                    != "discovery-batch-execution-reservation/v1"
                    or not isinstance(reservation.get("resume_failed_attempts"), bool)
                )
            ):
                raise ArtifactIntegrityError("batch cost reservation is inconsistent")
            completion = path.parent / "completion.json"
            record: dict[str, object] = (
                _read_json(completion) if completion.exists() else {"status": "UNFINISHED"}
            )
            if completion.exists() and (
                record.get("batch_hash") != self.batch.content_hash
                or record.get("reservation_hash") != sha256_bytes(canonical_json_bytes(reservation))
                or record.get("status") not in {"SUCCEEDED", "FAILED"}
            ):
                raise ArtifactIntegrityError("batch cost completion is inconsistent")
            for name in ("wall_seconds", "cpu_seconds"):
                value = record.get(name)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isfinite(value)
                    or value < 0
                ):
                    raise ArtifactIntegrityError("batch execution measurement is invalid")
            attempts.append(record)
        wall = [
            float(cast(int | float, record["wall_seconds"]))
            for record in attempts
            if record.get("wall_seconds") is not None
        ]
        cpu = [
            float(cast(int | float, record["cpu_seconds"]))
            for record in attempts
            if record.get("cpu_seconds") is not None
        ]
        complete = bool(attempts) and len(wall) == len(cpu) == len(attempts)
        recoveries = self._recovery_reservations()
        return {
            "attempt_count": len(attempts),
            "wall_seconds": sum(wall) if complete else None,
            "cpu_seconds": sum(cpu) if complete else None,
            "observed_wall_seconds": sum(wall) if wall else None,
            "observed_cpu_seconds": sum(cpu) if cpu else None,
            "measurements_complete": complete,
            "cpu_measurement_scope": "CALLING_PROCESS",
            "child_cpu_seconds": None,
            "recovery_reserved_compute_units": sum(recoveries.values()),
            "quoted_full_batch_compute_units": self.quote(),
            "maximum_compute_units": self.max_compute_units,
        }

    def run(
        self,
        *,
        expected_new_bytes: int,
        resume_failed_attempts: bool = False,
    ) -> tuple[AutonomousExecutionResult, ...]:
        """Run only under a guarded lease covering complete batch/concurrent growth."""
        if type(resume_failed_attempts) is not bool:
            raise ValueError("failed-attempt resume must be an explicit Boolean")
        guard, storage_authority = self._storage_authority(expected_new_bytes)
        with exclusive_directory_lock(self.output_root):
            self._save_evaluation_authority()
            atomic_write_bytes(self.output_root / "batch.json", self.batch.canonical_bytes())
            attempts = self.output_root / "batch-attempts"
            prior = sorted(attempts.glob("*/reservation.json"))
            for ordinal, path in enumerate(prior, start=1):
                previous = _read_json(path)
                if (
                    path.parent.name != f"{ordinal:08d}"
                    or previous
                    != {
                        "schema_version": "discovery-batch-execution-reservation/v1",
                        "batch_hash": self.batch.content_hash,
                        "ordinal": ordinal,
                        "resume_failed_attempts": previous.get("resume_failed_attempts"),
                        "expected_new_bytes": previous.get("expected_new_bytes"),
                        "storage_policy_hash": previous.get("storage_policy_hash"),
                        "lease_prelaunch_hash": previous.get("lease_prelaunch_hash"),
                    }
                    or not isinstance(previous.get("resume_failed_attempts"), bool)
                ):
                    raise ArtifactIntegrityError(
                        "batch execution reservation history is inconsistent"
                    )
            reservation = {
                "schema_version": "discovery-batch-execution-reservation/v1",
                "batch_hash": self.batch.content_hash,
                "ordinal": len(prior) + 1,
                "resume_failed_attempts": resume_failed_attempts,
                "expected_new_bytes": expected_new_bytes,
                "storage_policy_hash": guard.policy_hash,
                "lease_prelaunch_hash": storage_authority["lease_prelaunch_hash"],
            }
            attempt = attempts / f"{len(prior) + 1:08d}"
            atomic_write_bytes(attempt / "reservation.json", canonical_json_bytes(reservation))
            atomic_write_bytes(
                attempt / "storage-reservation.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-execution-storage-reservation/v1",
                        "batch_hash": self.batch.content_hash,
                        "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                        **storage_authority,
                    }
                ),
            )
            wall_start, cpu_start = perf_counter(), process_time()
            try:
                if any(response.producer == "SDK_CAPTURE" for response in self.batch.responses):
                    atomic_write_bytes(
                        attempt / "execution-blocked.json",
                        canonical_json_bytes(
                            {
                                "schema_version": "discovery-execution-entry-blocker/v1",
                                "batch_hash": self.batch.content_hash,
                                "reason": "SDK_GENERATION_ENTRY_NOT_QUALIFIED",
                                "scientific_execution_requested": False,
                            }
                        ),
                    )
                    raise ArtifactIntegrityError("SDK_GENERATION_ENTRY_NOT_QUALIFIED")
                outcomes = self._run(resume_failed_attempts=resume_failed_attempts, guard=guard)
            except BaseException:
                atomic_write_bytes(
                    attempt / "completion.json",
                    canonical_json_bytes(
                        {
                            "schema_version": "discovery-batch-execution-completion/v1",
                            "batch_hash": self.batch.content_hash,
                            "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                            "status": "FAILED",
                            "failure_code": "BATCH_EXECUTION_EXCEPTION",
                            "wall_seconds": max(0.0, perf_counter() - wall_start),
                            "cpu_seconds": max(0.0, process_time() - cpu_start),
                            "process_exit": None,
                        }
                    ),
                )
                raise
            finally:
                self._verified_inputs = None
            atomic_write_bytes(
                attempt / "completion.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-batch-execution-completion/v1",
                        "batch_hash": self.batch.content_hash,
                        "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                        "status": "SUCCEEDED",
                        "outcome_hashes": [outcome.content_hash for outcome in outcomes],
                        "wall_seconds": max(0.0, perf_counter() - wall_start),
                        "cpu_seconds": max(0.0, process_time() - cpu_start),
                        "process_exit": None,
                    }
                ),
            )
            return outcomes

    def _run(
        self,
        *,
        resume_failed_attempts: bool,
        guard: StorageGuard,
    ) -> tuple[AutonomousExecutionResult, ...]:
        """Reserve the full batch plan before any execution, then resume ordered subtasks."""
        with research_result_verification_scope():
            atomic_write_bytes(self.output_root / "batch.json", self.batch.canonical_bytes())
            self._adapters.clear()
            if self.batch.subtasks:
                self._verified_inputs = VerifiedExecutionInputs(
                    self.snapshot_path, self.qlib_view_path
                )
            charges = {
                task.content_hash: self._task_charge(task.content_hash)
                for task in self.batch.subtasks
            }
            allocated: dict[str, bool] = {}
            reserved = 0
            for task in self.batch.subtasks:
                charge = charges[task.content_hash]
                fits = reserved + charge <= self.max_compute_units
                allocated[task.content_hash] = fits
                if fits:
                    reserved += charge
            recovery_reservations = self._recovery_reservations()
            recovery_reserved = sum(recovery_reservations.values())
            if reserved + recovery_reserved > self.max_compute_units:
                raise ArtifactIntegrityError(
                    "discovery recovery reservations exceed the batch budget"
                )
            atomic_write_bytes(
                self.output_root / "compute-reservation.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-batch-compute-reservation/v1",
                        "batch_hash": self.batch.content_hash,
                        "maximum_compute_units": self.max_compute_units,
                        "reserved_compute_units": reserved,
                        "tasks": [
                            {
                                "subtask_hash": task.content_hash,
                                "quoted_compute_units": charges[task.content_hash],
                                "allocated": allocated[task.content_hash],
                            }
                            for task in self.batch.subtasks
                        ],
                        "policy": "autonomous-deterministic-compute-accounting/v1",
                    }
                ),
            )
            outcomes: list[AutonomousExecutionResult] = []
            for task in self.batch.subtasks:
                guard.require_lease()
                guard.check()
                key = task.content_hash
                request, adapter, root = (
                    self.task_request(key),
                    self.task_adapter(key),
                    self._task_root(key),
                )
                self._save_task_inputs(key, charges[key])
                events = self._events(key)
                if not events:
                    activated = self._governors[key].activate(
                        self._campaigns[key],
                        task.family,
                        self._budgets[key],
                        (),
                        event_id=uuid5(_NAMESPACE, f"{request.execution_identity}:activate"),
                        occurred_at=datetime.combine(
                            request.segment_end, datetime.min.time(), tzinfo=UTC
                        ),
                    )
                    self._save_event(key, activated)
                prior = adapter.verified_completed_execution(request)
                if prior is not None:
                    self._record_outcome(key, prior)
                    outcomes.append(prior)
                    continue
                if not allocated[key]:
                    atomic_write_bytes(
                        root / "not-executed.json",
                        canonical_json_bytes(
                            {
                                "schema_version": "discovery-task-not-executed/v1",
                                "batch_hash": self.batch.content_hash,
                                "request_hash": request.content_hash,
                                "reason": "BUDGET_EXHAUSTED",
                                "quoted_compute_units": charges[key],
                            }
                        ),
                    )
                    continue
                records = self._attempt_records(key)
                if records and records[-1]["status"] == "FAILED" and not resume_failed_attempts:
                    # An actual failed parent is retained. No automatic retry is authorized.
                    continue
                ordinal = len(records) + 1
                if ordinal > 1:
                    blocked = None
                    if ordinal > 1 + self.batch.design.max_execution_resumes_per_subtask:
                        blocked = "RECOVERY_LIMIT_EXHAUSTED"
                    elif (key, ordinal) not in recovery_reservations:
                        if reserved + recovery_reserved + charges[key] > self.max_compute_units:
                            blocked = "RECOVERY_BUDGET_EXHAUSTED"
                        else:
                            atomic_write_bytes(
                                self.output_root
                                / "recovery-reservations"
                                / key
                                / f"{ordinal:08d}.json",
                                canonical_json_bytes(
                                    {
                                        "schema_version": (
                                            "discovery-execution-recovery-reservation/v1"
                                        ),
                                        "batch_hash": self.batch.content_hash,
                                        "subtask_hash": key,
                                        "request_hash": request.content_hash,
                                        "ordinal": ordinal,
                                        "reserved_compute_units": charges[key],
                                        "accounting": (
                                            "CONSERVATIVE_FULL_WORKLOAD_PER_SUCCESSOR_ATTEMPT"
                                        ),
                                    }
                                ),
                            )
                            recovery_reservations[(key, ordinal)] = charges[key]
                            recovery_reserved += charges[key]
                    if blocked is not None:
                        atomic_write_bytes(
                            root / "recovery-not-executed" / f"{ordinal:08d}.json",
                            canonical_json_bytes(
                                {
                                    "schema_version": "discovery-task-recovery-not-executed/v1",
                                    "batch_hash": self.batch.content_hash,
                                    "request_hash": request.content_hash,
                                    "ordinal": ordinal,
                                    "reason": blocked,
                                    "quoted_compute_units": charges[key],
                                }
                            ),
                        )
                        continue
                attempt = root / "attempts" / f"{ordinal:08d}"
                reservation = {
                    "schema_version": "discovery-execution-attempt-reservation/v1",
                    "batch_hash": self.batch.content_hash,
                    "subtask_hash": key,
                    "request_hash": request.content_hash,
                    "execution_identity": request.execution_identity,
                    "ordinal": ordinal,
                }
                atomic_write_bytes(attempt / "reservation.json", canonical_json_bytes(reservation))
                wall_start, cpu_start = perf_counter(), process_time()
                try:
                    outcome = adapter.execute(request)
                except BaseException:
                    atomic_write_bytes(
                        attempt / "completion.json",
                        canonical_json_bytes(
                            {
                                "schema_version": "discovery-execution-attempt-completion/v1",
                                "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                                "request_hash": request.content_hash,
                                "status": "FAILED",
                                "failure_code": "EXECUTION_EXCEPTION",
                                "wall_seconds": max(0.0, perf_counter() - wall_start),
                                "cpu_seconds": max(0.0, process_time() - cpu_start),
                                "process_exit": None,
                            }
                        ),
                    )
                    raise
                atomic_write_bytes(
                    attempt / "completion.json",
                    canonical_json_bytes(
                        {
                            "schema_version": "discovery-execution-attempt-completion/v1",
                            "reservation_hash": sha256_bytes(canonical_json_bytes(reservation)),
                            "request_hash": request.content_hash,
                            "status": "SUCCEEDED",
                            "execution_outcome": outcome.outcome.value,
                            "outcome_hash": outcome.content_hash,
                            "execution_receipt_hash": outcome.execution_artifact_hash,
                            "wall_seconds": max(0.0, perf_counter() - wall_start),
                            "cpu_seconds": max(0.0, process_time() - cpu_start),
                            "process_exit": None,
                        }
                    ),
                )
                self._record_outcome(key, outcome)
                outcomes.append(outcome)
            return tuple(outcomes)
