"""Compose existing task/history services with executable research and forward tools."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quantos.application.personal_forward_authority import (
    PersonalForwardAuthority,
    forward_operation_identity,
)
from quantos.application.personal_memory import PersonalMemoryService
from quantos.application.personal_observation import PersonalObservationService, SnapshotArrival
from quantos.application.personal_shadow import PersonalShadowService
from quantos.application.personal_strategy import PersonalStrategyResearch
from quantos.application.personal_strategy_authority import (
    PersonalStrategyAuthority,
    ScopeReservationMissing,
)
from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalForwardScope, PersonalResearchScope


class PersonalProductServices:
    def __init__(
        self,
        core: Any,
        *,
        metadata: dict[str, SnapshotArrival] | None = None,
        forward_authority: PersonalForwardAuthority | None = None,
        dispatcher: Any = None,
    ) -> None:
        self.core = core
        self.research = PersonalStrategyResearch(core)
        self.memory = PersonalMemoryService(core.root, core.repo_root)
        self.runtime_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "research_runtime": self.research.runtime_hash(),
                    "forward_sources": {
                        name: sha256_file(core.repo_root / name)
                        for name in (
                            "src/quantos/application/personal_product.py",
                            "src/quantos/application/personal_observation.py",
                            "src/quantos/application/personal_shadow.py",
                            "src/quantos/application/personal_forward_authority.py",
                        )
                    },
                }
            )
        )
        self.forward_authority = forward_authority
        self.dispatcher = dispatcher

        def compiler(
            binding: Any, strategy: Any, day: date, publication_time: datetime
        ) -> dict[str, Any]:
            from quantos.research.personal_signal import (
                compile_strategy_signal,
                dataset_binding_hash,
            )

            identity = sha256_bytes(
                canonical_json_bytes(
                    {
                        "strategy_hash": strategy.content_hash,
                        "dataset_hash": dataset_binding_hash(binding),
                        "day": day,
                        "runtime_hash": self.runtime_hash,
                    }
                )
            )
            directory = core.root / "strategy-signals" / identity
            artifact, _ = compile_strategy_signal(
                binding, strategy, day, day, directory, self.runtime_hash
            )
            # publication_time is recorded by the observation journal, separately
            # from the historical signal cutoff inside SignalArtifact.
            return {"directory": str(directory), "artifact_hash": artifact.content_hash}

        def authorize_observation(context: dict[str, Any]) -> str | None:
            if forward_authority is None:
                return None
            plan, data = context["plan"], context["input"]
            return forward_authority.authorize(
                strategy_hash=plan["strategy_hash"],
                policy_hash=plan["policy_hash"],
                runtime_hash=self.runtime_hash,
                operation="observe",
                dataset_hash=data.get("dataset_binding_hash", data["dataset_manifest_hash"]),
                day=date.fromisoformat(context["day"]),
                kind=data["kind"],
                operation_identity=forward_operation_identity("observe", context),
            )

        self.observations = PersonalObservationService(
            core.root,
            core.catalog,
            compiler,
            metadata=metadata,
            authorizer=authorize_observation,
            compiler_runtime_hash=self.runtime_hash,
        )

        def authorize_shadow(
            plan: dict[str, Any], operation: str, payload: dict[str, Any]
        ) -> str | None:
            if forward_authority is None:
                return None
            from quantos.research.personal_signal import dataset_binding_hash

            binding = next(
                b
                for b in core.catalog.values()
                if dataset_binding_hash(b) == payload["dataset_hash"]
            )
            return forward_authority.authorize(
                strategy_hash=plan["strategy_hash"],
                policy_hash=plan["policy_hash"],
                runtime_hash=self.runtime_hash,
                operation=operation,
                dataset_hash=payload["dataset_hash"],
                day=date.fromisoformat(payload["execution_date"]),
                kind=binding.manifest.kind,
                operation_identity=forward_operation_identity(
                    "shadow_advance",
                    {
                        "shadow_id": sha256_bytes(canonical_json_bytes(plan)),
                        "execution_date": payload["execution_date"],
                        "observation_record_hash": payload["observation_record_hash"],
                        "execution_dataset_id": binding.manifest.dataset_id,
                    },
                ),
            )

        self.shadow = PersonalShadowService(
            core.root,
            self.observations,
            runtime_hash=self.runtime_hash,
            authorizer=authorize_shadow,
        )

    def observe(self, **payload: Any) -> dict[str, Any]:
        self.core.require_unchanged_runtime()
        if self.dispatcher is not None:
            return self.dispatcher("observation_observe", payload)
        return self.observations.observe(**payload)

    def advance_shadow(self, **payload: Any) -> dict[str, Any]:
        self.core.require_unchanged_runtime()
        if self.dispatcher is not None:
            return self.dispatcher("shadow_advance", payload)
        return self.shadow.advance(**payload)

    def record_forward_result(
        self, operation: str, payload: dict[str, Any], result: dict[str, Any]
    ) -> None:
        if self.forward_authority is None or operation == "observation_recover":
            return
        kind = "observe" if operation == "observation_observe" else operation
        identity = forward_operation_identity(kind, payload)
        try:
            reservation = self.forward_authority.reservation(identity)
        except ScopeReservationMissing:
            return
        if not reservation or reservation.get("settled"):
            return
        observed = (
            result.get("status")
            if kind == "observe"
            else result.get("native_receipt", {}).get("run_status")
        )
        state = (
            "SUCCEEDED"
            if observed in {"EMITTED", "ABSTAIN", "MISSING", "SUCCEEDED"}
            else observed or "UNKNOWN"
        )
        self.forward_authority.record(
            kind,
            identity,
            state,
            {
                "result_hash": sha256_bytes(canonical_json_bytes(result)),
                "measurement": "IN_PROCESS_COMPLETION_ONLY; supervisor exit settled by dispatcher",
            },
        )

    def scope_status(self) -> dict[str, Any]:
        return {
            "research": self.core.strategy_authority.status()
            if self.core.strategy_authority
            else None,
            "forward": self.forward_authority.status() if self.forward_authority else None,
            "execution_permission_from_tool_arguments": False,
        }

    def stop(self, kind: str, reason: str) -> dict[str, Any]:
        authority = (
            self.core.strategy_authority
            if kind == "research"
            else self.forward_authority
            if kind == "forward"
            else None
        )
        if authority is None:
            raise ValueError("no configured bounded scope of that kind")
        return authority.stop(reason)

    def reconcile(self, task_id: str) -> dict[str, Any]:
        status = self.core.status(task_id)
        results = self.core.results(task_id)
        return {
            "task_id": task_id,
            "state": status["state"],
            "verified_results": results,
            "reissued": False,
            "real_exit_invented": False,
            "next_action": "read retained artifacts; UNKNOWN needs operator reconciliation"
            if status["state"] == "UNKNOWN"
            else "prepare a bounded successor for unfinished work",
        }

    def feedback(
        self, task_id: str, interpretation: str, recommendation: str, reason: str
    ) -> dict[str, Any]:
        """Facts come from verified native receipts; free prose stays an annotation."""
        from quantos.contracts.personal_strategy import PreparedStrategyStudy

        prepared = self.core._prepared(task_id)
        if not isinstance(prepared, PreparedStrategyStudy):
            raise ValueError("retained v6 results use their existing cited history records")
        results = self.core.results(task_id)
        if results["state"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("feedback requires a settled terminal task")
        sources: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for index, row in enumerate(results["rows"]):
            if "receipt_sha256" not in row:
                continue
            path = (
                self.core.root
                / "tasks"
                / task_id
                / "execution"
                / row["candidate_id"]
                / "receipt.json"
            )
            relative = path.relative_to(self.core.repo_root).as_posix()
            source_id = f"candidate-{index}"
            sources.append(
                {
                    "source_id": source_id,
                    "path": relative,
                    "sha256": row["receipt_sha256"],
                    "available_at": results["event"]["at"],
                    "scope": "ORIGINAL_RESULT",
                }
            )
            for name, pointer, definition in (
                (
                    "execution_status",
                    "/run_status",
                    "Actual candidate terminal status; failures are not zero returns",
                ),
                (
                    "native_metrics",
                    "/metrics",
                    (
                        "Qlib net wealth, cash/exposure, fees, turnover and annual descriptions; "
                        "null means missing"
                    ),
                ),
            ):
                observations.append(
                    {
                        "name": row["candidate_id"] + ":" + name,
                        "source_id": source_id,
                        "pointer": pointer,
                        "definition": definition,
                    }
                )
        if not sources:
            raise ValueError("no completed candidate original available for feedback")
        annotation_hash = sha256_bytes(
            canonical_json_bytes(
                {"text": interpretation, "recommendation": recommendation, "reason": reason}
            )
        )[:16]
        draft = {
            "record_id": f"study-{task_id[:32]}-{annotation_hash}",
            "label": "Cited personal strategy study " + task_id[:16],
            "hypothesis": prepared.request.brief[:4000],
            "expectation": "; ".join(c.hypothesis for c in prepared.candidates)[:4000],
            "universe": "HS300 historical PIT membership; synthetic fixtures explicitly labelled",
            "period": f"{prepared.request.start_date}/{prepared.request.end_date}",
            "data_scenario": prepared.dataset_hash,
            "cost_scenario": canonical_json_bytes(prepared.request.policy).decode(),
            "tags": [
                "personal-study",
                "strategy",
                "engineering"
                if self.core.catalog[prepared.request.dataset_id].manifest.kind == "synthetic"
                else "exploratory",
            ],
            "sources": sources,
            "observations": observations,
            "annotations": [
                {
                    "kind": "MODEL_INTERPRETATION",
                    "text": interpretation,
                    "source_ids": [s["source_id"] for s in sources],
                }
            ],
            "uncertainties": results["limits"],
            "invalidation_conditions": [
                "Strategy, snapshot, units, cost, time policy or source identity changes"
            ],
            "recommendation": recommendation,
            "recommendation_reason": reason,
        }
        return self.memory.append(draft)


def configure_personal_product(
    core: Any, config: Any, config_path: Path, *, worker_mode: bool
) -> None:
    """Only validated operator configuration supplies scopes, arrivals and dispatch."""
    from quantos.application.personal_server_config import (
        _read,  # pyright: ignore[reportPrivateUsage]
        load_server_config,
    )
    from quantos.infrastructure.hosted_storage import StorageGuard, StoragePolicy

    metadata: dict[str, SnapshotArrival] = {}
    for registration in config.snapshot_arrivals:
        if registration.dataset_id not in core.catalog or registration.dataset_id in metadata:
            raise ValueError("arrival registration has no unique dataset binding")
        arrival = SnapshotArrival.model_validate_json(
            _read(registration.metadata_path, registration.metadata_sha256)
        )
        _read(registration.evidence_path, arrival.evidence_sha256)
        metadata[registration.dataset_id] = arrival

    def resource_check(registration: Any, scope: Any) -> None:
        core.require_unchanged_runtime()
        if load_server_config(config_path) != config:
            raise PermissionError("trusted config changed; restart product service")
        _read(registration.scope_path, registration.scope_sha256)
        _read(registration.approval_evidence_path, scope.approval_evidence_sha256)
        raw = _read(registration.storage_policy_path, registration.storage_policy_sha256)
        policy = json.loads(raw)
        for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
            policy[key] = Path(policy[key])
        guard = StorageGuard(StoragePolicy(**policy))
        guard.check(scope.growth_bytes)
        guard.require_lease()

    dispatcher: Any = None
    forward_authority: PersonalForwardAuthority | None = None
    for registration, contract, attribute in (
        (config.research_scope, PersonalResearchScope, "research"),
        (config.forward_scope, PersonalForwardScope, "forward"),
    ):
        if registration is None:
            continue
        scope: Any = contract.model_validate_json(
            _read(registration.scope_path, registration.scope_sha256)
        )
        approval = _read(registration.approval_evidence_path, scope.approval_evidence_sha256)

        def check_scope(s: Any, r: Any = registration) -> None:
            resource_check(r, s)

        if attribute == "research":
            core.strategy_authority = PersonalStrategyAuthority(
                core.root,
                scope,
                approval,
                resource_check=check_scope,
            )
        else:
            forward_authority = PersonalForwardAuthority(
                core.root,
                scope,
                approval,
                resource_check=check_scope,
            )
        if not worker_mode:
            from quantos.application.personal_dispatch import PersonalResourceDispatcher

            # A dispatcher re-reads the matching research/forward registration
            # per operation rather than inheriting another scope's resource budget.
            dispatcher = PersonalResourceDispatcher(core.root, core.repo_root, config_path)
    core.strategy_dispatcher = dispatcher
    core.product_services = PersonalProductServices(
        core,
        metadata=metadata,
        forward_authority=forward_authority,
        dispatcher=dispatcher,
    )


def personal_product(core: Any) -> PersonalProductServices:
    if core.product_services is None:
        core.product_services = PersonalProductServices(core)
    return core.product_services
