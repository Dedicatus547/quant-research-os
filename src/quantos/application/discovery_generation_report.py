"""Offline generation analysis over frozen originals; no scientific execution."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import cast

from quantos.application.discovery_generation import GenerationStore
from quantos.application.enumeration import structural_expression_hash
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import SequentialDiscoveryBatch
from quantos.contracts.hosted import parse_hosted_contract
from quantos.contracts.hosted_deployment import HostedLauncherRecord
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore


def _observed_total(values: list[int | float | None]) -> dict[str, object]:
    known = [value for value in values if value is not None]
    return {
        "total": sum(known) if len(known) == len(values) and values else None,
        "observed_total": sum(known) if known else None,
        "observed_items": len(known),
        "items": len(values),
    }


def generation_counts_from_verified_batch(wrapper: SequentialDiscoveryBatch) -> dict[str, object]:
    """Consume a wrapper just verified by GenerationStore; verify counted record bytes again.

    This adapter is for the same management verification scope, not an independent
    claim that a caller supplied wrapper has valid producer provenance.
    """
    batch = wrapper.batch
    observations = {item.reservation_hash: item for item in wrapper.launch_observations}
    sources = {item.reservation_hash: item for item in wrapper.launch_sources}
    responses = {item.reservation.content_hash: item for item in batch.responses}
    call_rows: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    for mapping in batch.mappings:
        response = responses.get(mapping.reservation_hash)
        source = sources.get(mapping.reservation_hash)
        observation = observations.get(mapping.reservation_hash)
        call_status = "UNKNOWN_AT_FREEZE"
        entry_count: int | None = None
        record_wall: float | None = None
        if source is not None and observation is not None:
            if observation.launcher_record_hash is not None:
                evidence = TrustedLauncherEvidenceStore(
                    Path(source.evidence_root), KnownValueGuard(())
                )
                data = evidence.read_bytes(observation.launcher_record_hash, max_bytes=65_536)
                record = parse_hosted_contract(data, HostedLauncherRecord, max_bytes=65_536)
                if record.content_hash != observation.launcher_record_hash:
                    raise ValueError("counted launcher record identity differs")
                # The launcher persists even empty output after startup OSError. A
                # raw-output reference alone therefore cannot confirm process entry.
                observed_event = False
                if record.exit_code is None and record.raw_output_hash is not None:
                    output = evidence.read_bytes(record.raw_output_hash, max_bytes=2_097_152)
                    for line in output.splitlines():
                        try:
                            event: object = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if isinstance(event, dict) and cast(dict[str, object], event).get(
                            "type"
                        ) in (
                            "thread.started",
                            "turn.started",
                            "turn.completed",
                            "item.started",
                            "item.updated",
                            "item.completed",
                        ):
                            observed_event = True
                            break
                if record.exit_code is not None or observed_event:
                    entry_count, call_status = 1, "CONFIRMED_MANAGEMENT_ENTRY"
                    record_wall = (record.terminated_at - record.started_at).total_seconds()
        elif response is not None and response.producer in ("BASELINE", "OFFLINE_IMPORT"):
            entry_count, call_status = 0, "NO_MODEL_ENTRY_BY_PRODUCER"
        call_rows.append(
            {
                "reservation_hash": mapping.reservation_hash,
                "request_hash": mapping.request_hash,
                "source_hash": None if source is None else source.content_hash,
                "observation_hash": None if observation is None else observation.content_hash,
                "status": call_status,
                "confirmed_entry_count": entry_count,
                "observed_entry_wall_seconds": record_wall,
            }
        )
        rows.append(
            {
                "request_hash": mapping.request_hash,
                "reservation_hash": mapping.reservation_hash,
                "response_hash": mapping.response_hash,
                "status": mapping.status,
                "reason": mapping.reason,
                "structural_hash": None
                if mapping.expression is None
                else structural_expression_hash(mapping.expression),
                "subtask_hash": mapping.subtask_hash,
                "producer": None if response is None else response.producer,
                "model_entry": call_rows[-1],
                "wall_seconds": None if response is None else response.wall_seconds,
                "usage_input_units": None if response is None else response.usage_input_units,
                "usage_output_units": None if response is None else response.usage_output_units,
                "monetary_cost": None if response is None else response.monetary_cost,
            }
        )
    methods: list[dict[str, object]] = []
    for request in batch.requests:
        selected = [row for row in rows if row["request_hash"] == request.content_hash]
        statuses = Counter(str(row["status"]) for row in selected)
        admitted = statuses["ADMITTED"] + statuses["DUPLICATE"]
        structures = sorted(
            {str(row["subtask_hash"]) for row in selected if row["subtask_hash"] is not None}
        )
        call_selected = [row for row in call_rows if row["request_hash"] == request.content_hash]
        local_duplicate_count = admitted - len(structures)
        methods.append(
            {
                "method": request.method,
                "request_hash": request.content_hash,
                "granted_opportunities": request.max_attempts,
                "occupied_opportunities": len(selected),
                "unoccupied_opportunities": request.max_attempts - len(selected),
                "status_counts": dict(sorted(statuses.items())),
                "static_admitted_including_duplicates": admitted,
                "static_admission_rate_original_opportunities": admitted / request.max_attempts,
                "duplicate_count": local_duplicate_count,
                "shared_global_duplicate_count": statuses["DUPLICATE"],
                "duplicate_rate_original_opportunities": local_duplicate_count
                / request.max_attempts,
                "different_admitted_structures": len(structures),
                "subtask_hashes": structures,
                "confirmed_management_entries": sum(
                    row["confirmed_entry_count"] == 1 for row in call_selected
                ),
                "unknown_management_entry_slots": sum(
                    row["confirmed_entry_count"] is None for row in call_selected
                ),
                "management_entry_wall_seconds": _observed_total(
                    [
                        cast(float | None, row["observed_entry_wall_seconds"])
                        for row in call_selected
                    ]
                ),
                "costs": {
                    name: _observed_total([cast(int | float | None, row[name]) for row in selected])
                    for name in (
                        "wall_seconds",
                        "usage_input_units",
                        "usage_output_units",
                        "monetary_cost",
                    )
                },
            }
        )
    return {
        "schema_version": "discovery-generation-counts/v2",
        "management_model_entries": {
            "confirmed": sum(row["confirmed_entry_count"] == 1 for row in call_rows),
            "unknown_slots": sum(row["confirmed_entry_count"] is None for row in call_rows),
            "confirmed_zero_slots": sum(row["confirmed_entry_count"] == 0 for row in call_rows),
            "observable_retries": None
            if any(row["confirmed_entry_count"] is None for row in call_rows)
            else 0,
            "observed_additional_launcher_entries_same_slot": 0,
            "retry_scope": "one frozen launcher source per opportunity; revisions occupy new slots",
            "provider_internal_calls": None,
            "rows": call_rows,
        },
        "candidate_opportunities": {
            "granted": sum(request.max_attempts for request in batch.requests),
            "occupied": len(batch.reservations),
        },
        "scientific_execution": {
            "status": "NOT_OBSERVED",
            "different_candidates_executed": None,
            "attempt_count": None,
            "resume_count": None,
            "different_admitted_structures": len(batch.subtasks),
        },
        "methods": methods,
        "rows": rows,
    }


def attach_verified_comparison_counts(
    counts: dict[str, object], wrapper: SequentialDiscoveryBatch, report: dict[str, object]
) -> dict[str, object]:
    """Reuse the same-scope already verified comparison; never reparse prediction data."""
    if report.get("batch_hash") != wrapper.batch.content_hash:
        raise ValueError("comparison does not bind the inner batch")
    costs = report.get("costs")
    if not isinstance(costs, dict):
        raise ValueError("comparison cost observations are missing")
    cost_values = cast(dict[str, object], costs)
    raw = cost_values.get("task_measurements")
    if not isinstance(raw, list):
        raise ValueError("comparison task observations are missing")
    tasks: dict[str, dict[str, object]] = {}
    for value in cast(list[object], raw):
        if not isinstance(value, dict):
            raise ValueError("comparison task observation is invalid")
        task = cast(dict[str, object], value)
        identity = task.get("subtask_hash")
        if not isinstance(identity, str) or identity in tasks:
            raise ValueError("comparison task identities are missing or duplicated")
        tasks[identity] = task
    if set(tasks) != {task.content_hash for task in wrapper.batch.subtasks}:
        raise ValueError("comparison task set differs")
    attempts = [task.get("execution_attempt_count") for task in tasks.values()]
    known = [value for value in attempts if isinstance(value, int) and not isinstance(value, bool)]
    complete = len(known) == len(attempts)
    return {
        **counts,
        "scientific_execution": {
            "status": "OBSERVED_COMPARISON" if complete else "PARTIALLY_OBSERVED_COMPARISON",
            "comparison_report_hash": sha256_bytes(canonical_json_bytes(report)),
            "different_candidates_executed": sum(value > 0 for value in known)
            if complete
            else None,
            "observed_different_candidates_executed": sum(value > 0 for value in known),
            "attempt_count": sum(known) if complete else None,
            "resume_count": sum(max(0, value - 1) for value in known) if complete else None,
            "resume_semantics": "additional retained task attempts, not complete reruns",
            "unknown_candidate_attempt_counts": len(attempts) - len(known),
            "batch_attempt_count": cost_values.get("batch_attempt_count"),
            "shared_structure_allocation": "global once; method subtask hashes preserve membership",
            "task_measurements": list(tasks.values()),
        },
    }


def build_generation_analysis(
    wrapper: SequentialDiscoveryBatch, store: GenerationStore
) -> dict[str, object]:
    """Reconstruct the freeze from originals before reporting static counts."""
    store.verify_frozen(wrapper)
    return {
        "schema_version": "discovery-generation-analysis/v2",
        "sequential_batch_hash": wrapper.content_hash,
        "batch_hash": wrapper.batch.content_hash,
        "policy_hash": wrapper.policy.content_hash,
        "scope": "FROZEN_STATIC_GENERATION_ONLY",
        "counts": generation_counts_from_verified_batch(wrapper),
        "limitations": [
            "Static admission is not prediction analyzability or a scientific verdict.",
            "Null frozen launch observations remain UNKNOWN_AT_FREEZE.",
            "Management entry is the observed external launcher process; "
            "provider-internal requests remain unknown.",
            "Scientific execution is NOT_OBSERVED without same-scope verified comparison evidence.",
            "No general economic equivalence simplifier; "
            "admitted structure uses frozen grammar identity.",
        ],
    }
