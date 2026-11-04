"""Executable v7 studies on the existing personal task/event authority.

Adaptive SDK packages require autonomous model/execution grants; this local path
instead reuses personal tasks and trusted bounded scope reservations. The outer
session proposes successors; deterministic code alone reserves and dispatches.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PreparedStrategyStudy, StrategyStudyRequest

SOURCES = (
    "src/quantos/contracts/personal_strategy.py",
    "src/quantos/research/qlib/expression.py",
    "src/quantos/research/qlib/personal_expression.py",
    "src/quantos/research/personal_signal.py",
    "src/quantos/research/personal_fields.py",
    "src/quantos/research/hs300_exchange.py",
    "src/quantos/research/hs300_lifecycle_data.py",
    "src/quantos/research/hs300_data.py",
    "src/quantos/data/lifecycle_sources.py",
    "src/quantos/contracts/hs300_lifecycle.py",
    "src/quantos/backtest/personal_strategy.py",
    "src/quantos/research/personal_native.py",
    "src/quantos/research/personal_session.py",
    "src/quantos/research/native_state.py",
    "src/quantos/application/personal_strategy.py",
    "src/quantos/application/personal_strategy_authority.py",
)


class PersonalStrategyResearch:
    def __init__(self, core: Any) -> None:
        self.core = core

    def dependencies(self) -> dict[str, Any]:
        from importlib.metadata import distribution

        manifest = self.core.dependency_manifest()
        for name in SOURCES:
            manifest["sources"][name] = sha256_file(self.core.repo_root / name)
        native = distribution("pyqlib")
        for name in (
            "qlib/backtest/report.py",
            "qlib/backtest/high_performance_ds.py",
            "qlib/backtest/utils.py",
            "qlib/utils/index_data.py",
            "qlib/strategy/base.py",
        ):
            manifest["sources"][name] = sha256_file(Path(str(native.locate_file(name))))
        return manifest

    def runtime_hash(self) -> str:
        self.core.require_unchanged_runtime()
        return sha256_bytes(canonical_json_bytes(self.dependencies()))

    def capabilities(self, include_schema: bool = False) -> dict[str, Any]:
        from quantos.research.personal_signal import dataset_binding_hash

        capabilities: dict[str, Any] = {
            "request_schema": "personal-study-request/v7",
            "strategy_schema": "personal-strategy/v1",
            "expression_schema": "safe-qlib-expression/v3",
            "max_nodes": 64,
            "max_window_sessions": 120,
            "max_input_lag_sessions": 20,
            "max_candidates": 4,
            "max_translated_expression_chars": 65536,
            "max_scope_attempts": 8,
            "fields": [
                "adjusted_open",
                "adjusted_high",
                "adjusted_low",
                "adjusted_close",
                "adjusted_volume",
                "amount_cny",
            ],
            "rank": (
                "eligible finite cross-section, direction then instrument ascending; "
                "Rank operator is time-series"
            ),
            "portfolio": "fixed Top-K slots or explicit weights, caps and cash remainder",
            "holdings": "daily/weekly, eligibility exit then max native age then schedule/buffer",
            "market_default": "CN_HS300_HISTORICAL_PIT/TUSHARE_PRO/daily/supplier_adjusted_units",
            "authority_configured": self.core.strategy_authority is not None,
            "scientific_status": "NOT_EVALUATED",
            "research_runtime_hash": self.runtime_hash(),
            "runtime_snapshot": "STARTUP_VERIFIED_UNCHANGED; restart after source edits",
            "dataset_bindings": [
                {
                    "dataset_id": name,
                    "manifest_hash": binding.manifest.content_hash,
                    "dataset_binding_hash": dataset_binding_hash(binding),
                    "field_mapping_profile": binding.field_mapping_profile,
                }
                for name, binding in sorted(self.core.catalog.items())
            ],
            "operators": {
                "field": {"field_name": "one of the supported fields", "inputs": []},
                "constant": {"value": "finite float in [-1e9,1e9]", "inputs": []},
                "windowed_unary": [
                    "ref",
                    "return",
                    "delta",
                    "rolling_mean",
                    "rolling_std",
                    "rolling_sum",
                    "rolling_min",
                    "rolling_max",
                    "rank",
                ],
                "window_shape": {"inputs": ["earlier_node_id"], "window": "integer 1..120"},
                "unary": ["abs", "not"],
                "binary": [
                    "add",
                    "subtract",
                    "multiply",
                    "divide",
                    "gt",
                    "ge",
                    "lt",
                    "le",
                    "eq",
                    "and",
                    "or",
                ],
                "binary_shape": {"inputs": ["earlier_left_node_id", "earlier_right_node_id"]},
                "null_policy": (
                    "invalid/nonfinite/divide-by-zero/incomplete-window is null; "
                    "predicates preserve unknown"
                ),
            },
        }
        if include_schema:
            capabilities["request_json_schema"] = StrategyStudyRequest.model_json_schema()
        return capabilities

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        from quantos.research.personal_signal import (
            dataset_binding_hash,
            strategy_gaps,
            verified_panel,
        )

        self.core.require_unchanged_runtime()
        proposed = StrategyStudyRequest.model_validate(request)
        gaps: list[str] = []
        resolved: dict[str, Any] = {
            "candidates": {},
            "policy": proposed.policy.model_dump(mode="json"),
            "native_accounts": len(proposed.candidates),
            "llm_execution_calls": 0,
            "acquisition_calls": 0,
        }
        binding = self.core.catalog.get(proposed.dataset_id)
        if binding is None:
            gaps.append("DATASET_NOT_REGISTERED")
        else:
            panel = verified_panel(binding)
            for candidate in proposed.candidates:
                candidate_gaps, detail = strategy_gaps(
                    binding,
                    candidate.strategy,
                    proposed.start_date,
                    proposed.end_date,
                    proposed.warmup_start,
                    proposed.benchmark,
                    panel=panel,
                )
                gaps.extend(f"{candidate.candidate_id}:{x}" for x in candidate_gaps)
                resolved["candidates"][candidate.candidate_id] = detail
            resolved.update(
                {
                    "dataset": binding.manifest.model_dump(mode="json"),
                    "field_mapping_profile": binding.field_mapping_profile,
                    "dataset_binding_hash": dataset_binding_hash(binding),
                    "estimated_growth_bytes": 128 * 1024**2,
                    "estimated_wall_seconds": 120,
                    "estimate_scope": (
                        "engineering fixture <=20 securities/120 sessions; "
                        "market estimate unqualified"
                    ),
                }
            )
        if proposed.parent_task_id is not None:
            parent = self.core._prepared(proposed.parent_task_id)
            if not isinstance(parent, PreparedStrategyStudy):
                gaps.append("SUCCESSOR_REQUIRES_V7_PARENT")
            elif self.core.status(proposed.parent_task_id)["state"] in {
                "RUNNING",
                "CANCEL_REQUESTED",
                "UNKNOWN",
            }:
                gaps.append("PARENT_UNSETTLED_RECONCILE_BEFORE_SUCCESSOR")
            resolved["parent_task_id"] = proposed.parent_task_id
            resolved["feedback_hashes"] = proposed.feedback_hashes
        prepared = PreparedStrategyStudy(
            request=proposed,
            code_hash=self.runtime_hash(),
            dataset_hash=dataset_binding_hash(binding) if binding else None,
            strategy_hashes={c.candidate_id: c.strategy.content_hash for c in proposed.candidates},
            policy_hash=proposed.policy.content_hash,
            readiness="BLOCKED" if gaps else "READY_FOR_AUTHORIZATION",
            gaps=tuple(gaps),
            resolved=resolved,
        )
        return self.core._persist_prepared(prepared)

    def execute(self, prepared: PreparedStrategyStudy) -> dict[str, Any]:
        from quantos.application.personal_research import (
            _process_identity,  # pyright: ignore[reportPrivateUsage]
        )
        from quantos.infrastructure.hosted_storage import HASH_ENV, LEASE_ENV
        from quantos.research.personal_native import execute_candidate
        from quantos.research.personal_signal import compile_strategy_signal

        core = self.core
        core.require_unchanged_runtime()
        task_id = prepared.content_hash
        if core.strategy_dispatcher is not None:
            state = core.status(task_id)
            if state["state"] != "PREPARED":
                return {**state, "idempotent_reuse": True}
            return core.strategy_dispatcher("research_execute", {"task_id": task_id})
        root = core.root / "tasks" / task_id / "execution"
        lease_detail = (
            {
                "supervisor_lease": os.environ[LEASE_ENV],
                "supervisor_policy_hash": os.environ[HASH_ENV],
            }
            if LEASE_ENV in os.environ and HASH_ENV in os.environ
            else {}
        )
        with exclusive_directory_lock(core.root / "worker"):
            with exclusive_directory_lock(core.root):
                last = core._events(task_id)[-1]
                if last.state != "PREPARED":
                    return {
                        "task_id": task_id,
                        "state": last.state,
                        "idempotent_reuse": True,
                        "validation_verdict": "NOT_EVALUATED",
                    }
                if (
                    prepared.readiness != "READY_FOR_AUTHORIZATION"
                    or prepared.code_hash != self.runtime_hash()
                ):
                    raise PermissionError(
                        "blocked or changed execution dependencies; prepare a successor"
                    )
                authority = core.strategy_authority
                if authority is None:
                    raise PermissionError("no trusted server-side v7 research scope")
                binding = core.catalog[prepared.request.dataset_id]
                scope_hash = authority.reserve(prepared, binding.manifest.kind)
                identity = _process_identity(os.getpid())
                if identity is None:
                    raise RuntimeError("cannot establish process identity")
                core._append(
                    task_id,
                    "RUNNING",
                    {
                        "pid": os.getpid(),
                        "process_identity": identity,
                        "scope_hash": scope_hash,
                        **lease_detail,
                    },
                )
            started = time.monotonic()
            receipts: list[dict[str, Any]] = []
            try:
                atomic_write_bytes(
                    root / "dependency-manifest.json", canonical_json_bytes(self.dependencies())
                )
                for candidate in prepared.candidates:
                    if core.worker_state(task_id) != "RUNNING":
                        break
                    if time.monotonic() - started > authority.scope.wall_seconds:
                        raise TimeoutError("bounded research wall limit")
                    destination = root / candidate.candidate_id
                    if destination.exists():
                        raise UnknownNativeStep(
                            "unexpected existing candidate without a settled task"
                        )
                    destination.mkdir(parents=True)
                    account_identity: str | None = None
                    origin_index: Path | None = None
                    try:
                        outcome: dict[str, Any]
                        signal_artifact, signal = compile_strategy_signal(
                            binding,
                            candidate.strategy,
                            prepared.request.warmup_start,
                            prepared.request.end_date,
                            destination / "signal",
                            prepared.code_hash,
                            benchmark=prepared.request.benchmark,
                        )
                        account_identity = sha256_bytes(
                            canonical_json_bytes(
                                {
                                    "strategy": candidate.strategy.content_hash,
                                    "dataset": prepared.dataset_hash,
                                    "policy": prepared.policy_hash,
                                    "runtime": prepared.code_hash,
                                    "signal": signal_artifact.content_hash,
                                    "start": prepared.request.start_date,
                                    "end": prepared.request.end_date,
                                    "benchmark": prepared.request.benchmark,
                                }
                            )
                        )
                        origin_index = (
                            Path(core.root) / "account-origins" / f"{account_identity}.json"
                        )
                        if origin_index.exists():
                            origin = json.loads(
                                confined_regular_file(
                                    origin_index.parent, origin_index.name
                                ).read_bytes()
                            )
                            verified = core.results(origin["task_id"])
                            origin_row = next(
                                r
                                for r in verified["rows"]
                                if r["candidate_id"] == origin["candidate_id"]
                            )
                            if (
                                origin_row["receipt_sha256"] != origin["receipt_sha256"]
                                or origin_row["run_status"] != "SUCCEEDED"
                                or origin_row["account_identity"] != account_identity
                            ):
                                raise ArtifactIntegrityError("native account origin changed")
                            outcome = {
                                "run_status": "REUSED_ORIGIN",
                                "origin": origin,
                                "metrics": origin_row["metrics"],
                                "files": {},
                                "validation_verdict": "NOT_EVALUATED",
                            }
                        else:
                            outcome = execute_candidate(
                                binding,
                                candidate.strategy,
                                prepared.request.policy,
                                signal,
                                str(prepared.request.start_date),
                                str(prepared.request.end_date),
                                prepared.request.benchmark,
                                destination / "native",
                            )
                            outcome["files"] = {
                                "native/" + k: v for k, v in outcome["files"].items()
                            }
                        outcome["account_identity"] = account_identity
                        outcome["signal_artifact_hash"] = signal_artifact.content_hash
                        outcome["files"].update(
                            {
                                "signal/" + n: sha256_file(destination / "signal" / n)
                                for n in (
                                    "manifest.json",
                                    "strategy.json",
                                    "lineage.json",
                                    "signals.parquet",
                                )
                            }
                        )
                    except Exception as error:
                        outcome = {
                            "run_status": "FAILED",
                            "metrics": None,
                            "files": {},
                            "error_type": type(error).__name__,
                            "validation_verdict": "NOT_EVALUATED",
                        }
                    receipt = {
                        **outcome,
                        "prepared_hash": task_id,
                        "candidate_id": candidate.candidate_id,
                        "strategy_hash": candidate.strategy.content_hash,
                        "policy_hash": prepared.policy_hash,
                        "dataset_hash": prepared.dataset_hash,
                        "wall_seconds": time.monotonic() - started,
                    }
                    atomic_write_bytes(destination / "receipt.json", canonical_json_bytes(receipt))
                    receipts.append(
                        {
                            "candidate_id": candidate.candidate_id,
                            "receipt_sha256": sha256_file(destination / "receipt.json"),
                        }
                    )
                    if outcome["run_status"] == "SUCCEEDED":
                        assert origin_index is not None and account_identity is not None
                        atomic_write_bytes(
                            origin_index,
                            canonical_json_bytes(
                                {
                                    "task_id": task_id,
                                    "candidate_id": candidate.candidate_id,
                                    "receipt_sha256": receipts[-1]["receipt_sha256"],
                                    "account_identity": account_identity,
                                }
                            ),
                        )
                    with exclusive_directory_lock(core.root):
                        current = core._events(task_id)[-1].state
                        core._append(
                            task_id,
                            current,
                            {
                                "pid": os.getpid(),
                                "process_identity": identity,
                                "completed_candidate": receipts[-1],
                                **lease_detail,
                            },
                        )
                cancelled = core._cancel_requested(task_id)
                unresolved = core.worker_state(task_id) == "UNKNOWN"
                state = (
                    "UNKNOWN"
                    if unresolved
                    else "CANCELLED"
                    if cancelled
                    else "SUCCEEDED"
                    if len(receipts) == len(prepared.candidates)
                    and all(
                        json.loads((root / x["candidate_id"] / "receipt.json").read_bytes())[
                            "run_status"
                        ]
                        in {"SUCCEEDED", "REUSED_ORIGIN"}
                        for x in receipts
                    )
                    else "FAILED"
                )
                outcome = {
                    "prepared_hash": task_id,
                    "run_status": state,
                    "receipts": receipts,
                    "wall_seconds": time.monotonic() - started,
                    "validation_verdict": "NOT_EVALUATED",
                }
                core.require_unchanged_runtime()
                atomic_write_bytes(root / "outcome.json", canonical_json_bytes(outcome))
                authority.record(
                    task_id,
                    state,
                    {"outcome_hash": sha256_file(root / "outcome.json")},
                    wall_seconds=time.monotonic() - started,
                    growth_bytes=sum(p.stat().st_size for p in regular_tree_files(root)),
                )
                with exclusive_directory_lock(core.root):
                    core._append(
                        task_id,
                        state,
                        {
                            "outcome_hash": sha256_file(root / "outcome.json"),
                            "validation_verdict": "NOT_EVALUATED",
                        },
                    )
            except Exception as error:
                atomic_write_bytes(
                    root / "coordination-failure.json",
                    canonical_json_bytes(
                        {"error_type": type(error).__name__, "validation_verdict": "NOT_EVALUATED"}
                    ),
                )
                with exclusive_directory_lock(core.root):
                    if core._events(task_id)[-1].state not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                        core._append(
                            task_id,
                            "FAILED",
                            {
                                "error_type": type(error).__name__,
                                "validation_verdict": "NOT_EVALUATED",
                            },
                        )
                authority.record(
                    task_id,
                    "FAILED",
                    {"error_type": type(error).__name__},
                    wall_seconds=time.monotonic() - started,
                    growth_bytes=sum(p.stat().st_size for p in regular_tree_files(root)),
                )
        return core.status(task_id)

    def results(self, prepared: PreparedStrategyStudy) -> dict[str, Any]:
        task_id = prepared.content_hash
        status = self.core.status(task_id)
        root = self.core.root / "tasks" / task_id / "execution"
        outcome: dict[str, Any] = {}
        if (root / "outcome.json").exists():
            raw = confined_regular_file(root, "outcome.json").read_bytes()
            terminal = self.core._events(task_id)[-1]
            published = terminal.detail.get("outcome_hash")
            if published is not None and published != sha256_bytes(raw):
                raise ArtifactIntegrityError("v7 outcome binding differs")
            if published is not None:
                outcome = json.loads(raw)
            elif status["state"] == "SUCCEEDED":
                raise ArtifactIntegrityError("successful v7 task has no published outcome binding")
        refs = {x["candidate_id"]: x for x in outcome.get("receipts", [])}
        for event in self.core._events(task_id):
            ref = event.detail.get("completed_candidate")
            if ref is not None:
                refs[ref["candidate_id"]] = ref
        rows: list[dict[str, Any]] = []
        for c in prepared.candidates:
            row: dict[str, Any] = {
                "candidate_id": c.candidate_id,
                "role": c.role,
                "strategy_hash": c.strategy.content_hash,
                "hypothesis": c.hypothesis,
                "run_status": "NOT_RUN",
                "metrics": None,
            }
            if c.candidate_id in refs:
                directory = root / c.candidate_id
                raw = confined_regular_file(directory, "receipt.json").read_bytes()
                if sha256_bytes(raw) != refs[c.candidate_id]["receipt_sha256"]:
                    raise ArtifactIntegrityError("candidate receipt identity differs")
                receipt = json.loads(raw)
                if (
                    receipt["prepared_hash"] != task_id
                    or receipt["strategy_hash"] != c.strategy.content_hash
                ):
                    raise ArtifactIntegrityError("candidate strategy/input binding differs")
                for logical, digest in receipt["files"].items():
                    verify_file(confined_regular_file(directory, logical), digest)
                if receipt["run_status"] == "REUSED_ORIGIN":
                    origin = receipt["origin"]
                    if origin["task_id"] == task_id:
                        raise ArtifactIntegrityError("self-referencing native origin")
                    original = self.core.results(origin["task_id"])
                    source = next(
                        r for r in original["rows"] if r["candidate_id"] == origin["candidate_id"]
                    )
                    if (
                        source["run_status"] != "SUCCEEDED"
                        or source["receipt_sha256"] != origin["receipt_sha256"]
                        or source["account_identity"] != receipt["account_identity"]
                        or source["metrics"] != receipt["metrics"]
                    ):
                        raise ArtifactIntegrityError("native origin tuple differs")
                row.update(receipt)
                row["receipt_sha256"] = sha256_bytes(raw)
            rows.append(row)
        return {
            **status,
            "schema_version": "personal-strategy-results/v1",
            "rows": rows,
            "planned_denominator": len(prepared.candidates),
            "attempted_denominator": len(refs),
            "brief_hash": prepared.request.content_hash,
            "policy_hash": prepared.policy_hash,
            "dataset_hash": prepared.dataset_hash,
            "parent_task_id": prepared.request.parent_task_id,
            "limits": [
                "Engineering scenarios are not scientific validation or future performance",
                (
                    "Native fees/exposure are reported alongside wealth; "
                    "no exposure normalization replaces returns"
                ),
                "Daily coarse lot/volume/settlement scenario; unsupported company actions stop",
            ],
            "scope": self.core.strategy_authority.status()
            if self.core.strategy_authority
            else None,
        }


class UnknownNativeStep(RuntimeError):
    pass
