#!/usr/bin/env python3
"""Read-only successor prediction comparison with frozen Discovery method attribution."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, process_time
from typing import TypeVar, cast

from quantos.application.autonomous_execution import require_durable_execution_root
from quantos.application.discovery_execution import DiscoveryExecutionService
from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_prediction import validate_prediction_output_root
from quantos.application.discovery_prediction_batch import (
    build_discovery_prediction_comparison,
    render_discovery_prediction_comparison,
)
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, sha256_file
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryBatch, SequentialDiscoveryBatch
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration
from quantos.contracts.discovery_prediction import (
    PredictionEvaluationProfile,
    PredictionImportSource,
)
from quantos.infrastructure.hosted_storage import configured_guard

_C = TypeVar("_C", bound=CanonicalContract)


def _bytes(path: Path) -> bytes:
    source = confined_regular_file(path.absolute().parent, path.name)
    if source.stat().st_size > 16_777_216:
        raise ValueError("INPUT_BYTE_LIMIT")
    return source.read_bytes()


def _contract(path: Path, kind: type[_C], expected_hash: str | None = None) -> _C:
    raw = _bytes(path)
    value = kind.model_validate_json(raw)
    if value.canonical_bytes() != raw:
        raise ValueError("INPUT_NOT_CANONICAL")
    if expected_hash is not None and value.content_hash != expected_hash:
        raise ValueError("INPUT_HASH_MISMATCH")
    return value


def _inputs(
    path: Path, expected_hash: str, profile: PredictionEvaluationProfile
) -> tuple[dict[str, PredictionImportSource], dict[str, tuple[Path, str]]]:
    raw = _bytes(path)
    if sha256_bytes(raw) != expected_hash:
        raise ValueError("COMPARISON_INPUTS_HASH_MISMATCH")
    payload: object = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("COMPARISON_INPUTS_NOT_CANONICAL")
    fields = cast(dict[str, object], payload)
    if canonical_json_bytes(fields) != raw:
        raise ValueError("COMPARISON_INPUTS_NOT_CANONICAL")
    if fields.get("schema_version") != "prediction-comparison-inputs/v1" or not isinstance(
        fields.get("entries"), list
    ):
        raise ValueError("COMPARISON_INPUTS_INVALID")
    sources: dict[str, PredictionImportSource] = {}
    references: dict[str, tuple[Path, str]] = {}
    seen: set[str] = set()
    for item in cast(list[object], fields["entries"]):
        if not isinstance(item, dict):
            raise ValueError("COMPARISON_ENTRY_INVALID")
        entry = cast(dict[str, object], item)
        request_hash = str(entry["execution_request_hash"])
        if request_hash in seen or request_hash not in profile.execution_request_hashes:
            raise ValueError("COMPARISON_COHORT_MISMATCH")
        seen.add(request_hash)
        if entry.get("source_path") is not None:
            sources[request_hash] = _contract(
                Path(str(entry["source_path"])),
                PredictionImportSource,
                str(entry["source_hash"]),
            )
        if entry.get("artifact_path") is not None:
            references[request_hash] = (
                Path(str(entry["artifact_path"])),
                str(entry["artifact_hash"]),
            )
    if seen != set(profile.execution_request_hashes):
        raise ValueError("COMPARISON_DENOMINATOR_INCOMPLETE")
    return sources, references


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "generation-root",
        "snapshot",
        "view",
        "execution-root",
        "workspace",
        "profile",
        "report-root",
        "operation-root",
        "inputs",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--evaluation-declaration", type=Path)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--inputs-hash", required=True)
    parser.add_argument("--batch-hash", required=True)
    parser.add_argument("--expected-new-bytes", type=int, required=True)
    args = parser.parse_args()
    operation = args.operation_root.absolute()
    wall, cpu = perf_counter(), process_time()
    recorded = False
    handled = False
    exit_code = 1
    try:
        require_durable_execution_root(operation)
        profile = _contract(args.profile, PredictionEvaluationProfile, args.profile_hash)
        sources, references = _inputs(args.inputs, args.inputs_hash, profile)
        validate_prediction_output_root(operation, tuple(sources.values()))
        validate_prediction_output_root(args.report_root, tuple(sources.values()))
        originals = (args.generation_root, args.snapshot, args.view, args.execution_root)
        if any(
            output.absolute().is_relative_to(original.absolute())
            for output in (operation, args.report_root)
            for original in originals
        ):
            raise ValueError("OUTPUT_OVERLAPS_BATCH_ORIGINALS")
        if (operation / "prelaunch.json").exists():
            raise ValueError("OPERATION_ALREADY_RESERVED")
        atomic_write_bytes(
            operation / "prelaunch.json",
            canonical_json_bytes(
                {
                    "schema_version": "discovery-prediction-comparison-operation/v1",
                    "profile_hash": args.profile_hash,
                    "inputs_hash": args.inputs_hash,
                    "batch_hash": args.batch_hash,
                    "entrypoint_hash": sha256_file(Path(__file__)),
                    "expected_new_bytes": args.expected_new_bytes,
                    "started_at": datetime.now(UTC),
                }
            ),
        )
        recorded = True
        guard = configured_guard()
        guard.require_root(operation)
        guard.require_root(args.report_root)
        guard.require_lease()
        atomic_write_bytes(
            operation / "capacity.json", canonical_json_bytes(guard.check(args.expected_new_bytes))
        )
        store = GenerationStore(args.generation_root)
        wrapper = None
        if store.sequential_policy() is None:
            batch = _contract(store.root / "frozen.json", DiscoveryBatch)
        else:
            wrapper = _contract(store.root / "frozen.json", SequentialDiscoveryBatch)
            batch = wrapper.batch
        if (batch if wrapper is None else wrapper).content_hash != args.batch_hash:
            raise ValueError("FROZEN_BATCH_HASH_MISMATCH")
        service = DiscoveryExecutionService(
            batch=batch,
            sequential_batch=wrapper,
            snapshot_path=args.snapshot,
            qlib_view_path=args.view,
            output_root=args.execution_root,
            workspace=args.workspace,
            generation_root=store.root,
            evaluation_declaration=None
            if args.evaluation_declaration is None
            else _contract(args.evaluation_declaration, DiscoveryEvaluationDeclaration),
        )
        report = build_discovery_prediction_comparison(service, profile, sources, references)
        root = args.report_root.absolute()
        if root.resolve() != root or any(
            root.is_relative_to(Path(prefix)) for prefix in ("/tmp", "/var/tmp")
        ):
            raise ValueError("REPORT_REQUIRES_DURABLE_CANONICAL_ROOT")
        encoded = canonical_json_bytes(report)
        markdown = render_discovery_prediction_comparison(report).encode("utf-8")
        if len(encoded) + len(markdown) + 65_536 > args.expected_new_bytes:
            raise ValueError("REPORT_EXCEEDS_RESERVED_GROWTH")
        guard.check(args.expected_new_bytes)
        digest = sha256_bytes(encoded)
        directory = root / f"sha256-{digest}"
        atomic_write_bytes(directory / "report.json", encoded)
        atomic_write_bytes(directory / "report.md", markdown)
        atomic_write_bytes(
            operation / "result.json",
            canonical_json_bytes({"report_hash": digest, "path": str(directory)}),
        )
        print(json.dumps({"report_hash": digest, "path": str(directory)}, sort_keys=True))
        exit_code = 0
        handled = True
        return 0
    except Exception as error:
        if recorded:
            atomic_write_bytes(
                operation / "failure.json",
                canonical_json_bytes({"status": "FAILED", "error_type": type(error).__name__}),
            )
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__}))
        handled = True
        return 1
    finally:
        if recorded:
            atomic_write_bytes(
                operation / "completion.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-prediction-comparison-completion/v1",
                        "entrypoint_return_code": exit_code if handled else None,
                        "process_exit_observation": "REQUIRES_OUTER_PROCESS_OBSERVER",
                        "wall_seconds": perf_counter() - wall,
                        "cpu_seconds": process_time() - cpu,
                        "ended_at": datetime.now(UTC),
                    }
                ),
            )


if __name__ == "__main__":
    raise SystemExit(main())
