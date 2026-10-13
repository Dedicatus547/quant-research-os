#!/usr/bin/env python3
"""Bind fresh B2 scientific authority to frozen composition proposals; no science runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from quantos.application.discovery_execution import quote_discovery_workload
from quantos.application.discovery_generation import GenerationStore
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryCompositionDesign, SequentialDiscoveryBatch
from quantos.contracts.discovery_evaluation import (
    ScientificEvaluationBudget,
    ScientificEvaluationDeclaration,
    ScientificExecutionAuthorization,
    ScientificSchedulingCutoff,
)
from quantos.contracts.hosted import strict_json_object


def read(path: Path, *, require_canonical: bool = True) -> tuple[dict[str, object], bytes]:
    file = confined_regular_file(path.absolute().parent, path.name)
    if file.stat().st_size > 16 << 20:
        raise ValueError("B2 metadata exceeds its byte bound")
    data = file.read_bytes()
    value = strict_json_object(data, max_bytes=16 << 20)
    if require_canonical and canonical_json_bytes(value) != data:
        raise ValueError("B2 originals require canonical JSON")
    return value, data


def prepare(
    *,
    generation_root: Path,
    source_capsule: Path,
    authorization_record: Path,
    output_root: Path,
    execution_root: Path,
) -> dict[str, object]:
    """Write independent originals before launch; mutable/unknown exits grant no retry."""
    for root in (output_root, execution_root):
        if any(root.absolute().is_relative_to(p) for p in (Path("/tmp"), Path("/var/tmp"))):
            raise ValueError("B2 scientific authority must remain durable")
    _, frozen = read(generation_root / "frozen.json")
    wrapper = SequentialDiscoveryBatch.model_validate_json(frozen)
    GenerationStore(generation_root).verify_frozen(wrapper)
    design = wrapper.batch.design
    if not isinstance(design, DiscoveryCompositionDesign):
        raise ValueError("B2 science requires the explicit composition successor")
    if design.evaluation_opportunities_per_method != 3 or design.max_compute_units != 180:
        raise ValueError("B2 design exceeds the accepted three-opportunity/180-unit scope")
    if any(r.max_attempts != 3 for r in wrapper.batch.requests):
        raise ValueError("B2 methods must bind three declared opportunities each")
    if any(
        r.method == "LLM" and (r.model_identifier, r.reasoning_effort) != ("gpt-6.1-sol", "high")
        for r in wrapper.batch.requests
    ):
        raise ValueError("B2 scientific source differs from the authorized Hosted method")
    capsule, capsule_bytes = read(source_capsule)
    authorization, authorization_bytes = read(authorization_record, require_canonical=False)
    # The caller supplies the actual retained root authorization, not a new quota.
    if (
        authorization.get("schema_version") != "a1-b2-run-authorization/v1"
        or authorization.get("user_instruction") != "授权A和B"
        or authorization.get("unknown_reissue") is not False
        or authorization.get("b2_authorized") is not True
    ):
        raise ValueError("B2 requires its explicit retained user authorization")
    for name, cap in (
        ("model_call_caps", 3),
        ("scientific_units_caps", 180),
        ("wall_caps_seconds", 14_400),
        ("growth_caps_bytes", 12 << 30),
        ("scientific_initial_caps", 9),
        ("scientific_global_resume_caps", 1),
        ("opportunities_per_method", 3),
    ):
        values = authorization.get(name)
        if not isinstance(values, dict) or cast(dict[str, object], values).get("B2") != cap:
            raise ValueError("B2 authorization differs from its accepted bounds")
    workspace = Path(cast(str, capsule.get("workspace")))
    commit = cast(str, capsule.get("actual_commit"))
    lock = cast(str, capsule.get("lockfile_hash"))
    if (
        capsule.get("schema_version") != "post-hm-source-capsule/v1"
        or design.bindings.code_commit_hash != commit
        or design.bindings.lockfile_hash != lock
    ):
        raise ValueError("B2 authority source differs from frozen generation")
    verify_code_provenance(workspace, expected_commit_hash=commit, expected_lockfile_hash=lock)
    count = len(wrapper.batch.subtasks)
    quoted = quote_discovery_workload(wrapper.batch)
    if count > 9 or quoted > 162:
        raise ValueError("B2 candidate count or initial workload exceeds accepted limits")
    source_hash = sha256_bytes(capsule_bytes)
    if count == 0:
        result: dict[str, object] = {
            "schema_version": "b2-scientific-preparation/v1",
            "status": "NO_ADMITTED_CANDIDATES",
            "batch_hash": wrapper.content_hash,
            "science_started": False,
            "authorization_record_hash": sha256_bytes(authorization_bytes),
        }
        atomic_write_bytes(output_root / "preparation.json", canonical_json_bytes(result))
        return result
    auth = ScientificExecutionAuthorization(
        user_instruction=(
            "User authorized A and B (授权A和B). B2 Hosted gpt-6.1-sol/high: "
            "3 generation opportunities per method, 9 initial scientific candidates "
            "and 1 global explicit failed resume; 180 units, 4 hours, 12 GiB growth, "
            "32 GiB host floor. No unknown reissue, purchase, push or unique-evidence deletion. "
            f"Retained authorization SHA256 {sha256_bytes(authorization_bytes)}."
        ),
        original_sequential_batch_hash=wrapper.content_hash,
    )
    cutoff = ScientificSchedulingCutoff(
        original_sequential_batch_hash=wrapper.content_hash,
        original_batch_hash=wrapper.batch.content_hash,
        original_design_hash=design.content_hash,
        authorization_hash=auth.content_hash,
    )
    budget = ScientificEvaluationBudget(
        full_batch_compute_units=quoted,
        new_execution_compute_units=quoted,
        max_compute_units=180,
        max_distinct_candidates=count,
        max_new_candidate_executions=count,
        max_failed_task_resumes=1,
    )
    declaration = ScientificEvaluationDeclaration(
        original_sequential_batch_hash=wrapper.content_hash,
        original_generation_policy_hash=wrapper.policy.content_hash,
        original_batch_hash=wrapper.batch.content_hash,
        original_design_hash=design.content_hash,
        original_generation_source_commit=commit,
        original_generation_source_declaration_hash=source_hash,
        evaluation_source_declaration_hash=source_hash,
        snapshot_hash=design.snapshot_hash,
        qlib_view_hash=design.qlib_view_hash,
        authorization_hash=auth.content_hash,
        scientific_scheduling_cutoff_hash=cutoff.content_hash,
        budget=budget,
        bindings=design.bindings,
        exposure_history_append=(
            "Authorized B2 science evaluates only this frozen generation batch; "
            "no feedback is returned to its closed generation phase. "
            "2015-2025 exposures remain retrospective; sealed 2026 is inaccessible.",
        ),
    )
    originals = {
        "scientific-authorization.json": auth.canonical_bytes(),
        "scientific-scheduling-cutoff.json": cutoff.canonical_bytes(),
        "original-generation-source.json": capsule_bytes,
        "evaluation-source.json": capsule_bytes,
    }
    for name, data in originals.items():
        atomic_write_bytes(execution_root / name, data, expected_sha256=sha256_bytes(data))
    atomic_write_bytes(output_root / "scientific-evaluation.json", declaration.canonical_bytes())
    atomic_write_bytes(output_root / "scientific-scheduling-cutoff.json", cutoff.canonical_bytes())
    growth = {
        "schema_version": "b2-independent-scientific-growth/v1",
        "design_hash": design.content_hash,
        "complete_attempt_envelope_count": count + 1,
        "growth_components": {
            "complete_attempt_envelopes_bytes": (count + 1) * (512 << 20),
            "independent_origin_prediction_import_and_comparison_bytes": 2 << 30,
            "shared_metadata_runtime_authority_logs_bytes": 512 << 20,
            "safe_finish_and_unobserved_growth_margin_bytes": 1 << 30,
            # 9 GiB science reservation + 256 MiB preparation/generation <=12 GiB total.
            "expected_new_durable_bytes": 9 << 30,
        },
        "sizing_origin": "Retained 512 MiB complete-attempt envelope; shared inputs read-only.",
        "scientific_execution_granted_by_size_estimate": False,
    }
    atomic_write_bytes(output_root / "growth-estimate.json", canonical_json_bytes(growth))
    result = {
        "schema_version": "b2-scientific-preparation/v1",
        "status": "PREPARED_NOT_EXECUTED",
        "batch_hash": wrapper.content_hash,
        "declaration_hash": declaration.content_hash,
        "distinct_candidates": count,
        "initial_quote_units": quoted,
        "max_compute_units": 180,
        "global_failed_resume_limit": 1,
        "source_capsule_hash": source_hash,
        "authorization_record_hash": sha256_bytes(authorization_bytes),
        "science_started": False,
    }
    atomic_write_bytes(output_root / "preparation.json", canonical_json_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "generation-root",
        "source-capsule",
        "authorization-record",
        "output-root",
        "execution-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(**vars(args))
    except (OSError, ValueError, RuntimeError, TypeError):
        print(json.dumps({"status": "FAILED", "reason": "B2_SCIENTIFIC_PREPARATION_REJECTED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
