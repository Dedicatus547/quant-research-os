#!/usr/bin/env python3
"""Independent successor prediction identity/import/verify/compare management entry.

This entry never trains a model or changes historical outcome/Validation/P14c.
Full source verifications reuse the existing hosted storage guard and lease.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, process_time
from typing import TypeVar, cast

from quantos.application.autonomous_execution import require_durable_execution_root
from quantos.application.discovery_prediction import (
    compare_prediction_evidence,
    prediction_verifier_identity,
    publish_prediction_evidence,
    validate_prediction_output_root,
    verify_prediction_evidence,
)
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_prediction import (
    PredictionEvaluationProfile,
    PredictionImportSource,
)
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.infrastructure.hosted_storage import configured_guard

_C = TypeVar("_C", bound=CanonicalContract)


def _read(path: Path, expected_hash: str) -> bytes:
    path = confined_regular_file(path.absolute().parent, path.name)
    if path.stat().st_size > 16_777_216:
        raise ValueError("INPUT_METADATA_LIMIT")
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_hash:
        raise ValueError("INPUT_METADATA_HASH_MISMATCH")
    return raw


def _contract(path: Path, expected_hash: str, model: type[_C]) -> _C:
    raw = _read(path, expected_hash)
    result = model.model_validate_json(raw)
    if result.canonical_bytes() != raw:
        raise ValueError("INPUT_METADATA_NOT_CANONICAL")
    return result


def _operation(args: argparse.Namespace) -> dict[str, object]:
    profile = _contract(args.profile, args.profile_hash, PredictionEvaluationProfile)
    base_authoring = _contract(
        args.base_authoring, args.base_authoring_hash, ExperimentAuthoringSpec
    )
    if args.command == "compare":
        raw = _read(args.inputs, args.inputs_hash)
        decoded: object = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("COMPARISON_INPUTS_INVALID")
        payload = cast(dict[str, object], decoded)
        if canonical_json_bytes(payload) != raw:
            raise ValueError("COMPARISON_INPUTS_INVALID")
        if payload.get("schema_version") != "prediction-comparison-inputs/v1":
            raise ValueError("COMPARISON_INPUTS_SCHEMA_INVALID")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("COMPARISON_INPUTS_ENTRIES_INVALID")
        sources: dict[str, PredictionImportSource] = {}
        references: dict[str, tuple[Path, str]] = {}
        seen: set[str] = set()
        for entry in cast(list[dict[str, object]], entries):
            key = str(entry["execution_request_hash"])
            if key in seen or key not in profile.execution_request_hashes:
                raise ValueError("COMPARISON_INPUTS_COHORT_MISMATCH")
            seen.add(key)
            if entry.get("source_path") is not None:
                sources[key] = _contract(
                    Path(str(entry["source_path"])),
                    str(entry["source_hash"]),
                    PredictionImportSource,
                )
            if entry.get("artifact_path") is not None:
                references[key] = (Path(str(entry["artifact_path"])), str(entry["artifact_hash"]))
        if seen != set(profile.execution_request_hashes):
            raise ValueError("COMPARISON_INPUTS_DENOMINATOR_INCOMPLETE")
        return compare_prediction_evidence(
            profile, sources, references, base_authoring=base_authoring
        )
    source = _contract(args.source, args.source_hash, PredictionImportSource)
    if args.command == "import":
        path = publish_prediction_evidence(
            source, profile, args.output_root, base_authoring=base_authoring
        )
        return {"artifact_path": str(path), "artifact_hash": path.name.removeprefix("sha256-")}
    evidence = verify_prediction_evidence(
        args.artifact,
        expected_hash=args.artifact_hash,
        source=source,
        profile=profile,
        base_authoring=base_authoring,
    )
    return {
        "verification": "REBUILT_FROM_ORIGINALS",
        "evidence_hash": evidence.content_hash,
        "artifact_hash": args.artifact_hash,
        "profile_hash": profile.content_hash,
        "scope": "SUCCESSOR_RETROSPECTIVE_PREDICTION_ONLY",
    }


def _layout_sources(args: argparse.Namespace) -> tuple[PredictionImportSource, ...]:
    """Read only small pinned descriptors before permitting an authority write."""
    if args.command != "compare":
        return (_contract(args.source, args.source_hash, PredictionImportSource),)
    raw = _read(args.inputs, args.inputs_hash)
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("COMPARISON_INPUTS_INVALID")
    payload = cast(dict[str, object], decoded)
    entries_value = payload.get("entries")
    if not isinstance(entries_value, list):
        raise ValueError("COMPARISON_INPUTS_ENTRIES_INVALID")
    entries = cast(list[dict[str, object]], entries_value)
    return tuple(
        _contract(
            Path(str(entry["source_path"])), str(entry["source_hash"]), PredictionImportSource
        )
        for entry in entries
        if entry.get("source_path") is not None
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    identity = subparsers.add_parser(
        "identity", help="Write actual rule/verifier dependency identity"
    )
    identity.add_argument("--output", type=Path, required=True)
    for name in ("import", "verify", "compare"):
        command = subparsers.add_parser(name)
        command.add_argument("--profile", type=Path, required=True)
        command.add_argument("--profile-hash", required=True)
        command.add_argument("--base-authoring", type=Path, required=True)
        command.add_argument("--base-authoring-hash", required=True)
        command.add_argument("--operation-root", type=Path, required=True)
        command.add_argument("--expected-new-bytes", type=int, required=True)
        if name != "compare":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--source-hash", required=True)
        if name == "import":
            command.add_argument("--output-root", type=Path, required=True)
        elif name == "verify":
            command.add_argument("--artifact", type=Path, required=True)
            command.add_argument("--artifact-hash", required=True)
        else:
            command.add_argument("--inputs", type=Path, required=True)
            command.add_argument("--inputs-hash", required=True)
    args = parser.parse_args()
    if args.command == "identity":
        validate_prediction_output_root(args.output.parent, ())
        identity_payload = canonical_json_bytes(prediction_verifier_identity())
        digest = atomic_write_bytes(args.output, identity_payload)
        print(json.dumps({"path": str(args.output), "sha256": digest}))
        return 0
    operation = cast(Path, args.operation_root).absolute()
    require_durable_execution_root(operation)
    layout_sources = _layout_sources(args)
    validate_prediction_output_root(operation, layout_sources)
    if args.command == "import":
        validate_prediction_output_root(args.output_root, layout_sources)
    if (operation / "prelaunch.json").exists():
        raise ValueError("OPERATION_ALREADY_RESERVED")
    start = datetime.now(UTC)
    wall, cpu = perf_counter(), process_time()
    # Persist attempted action before potentially costly data/PIT verification.
    prelaunch = {
        "schema_version": "prediction-evidence-operation/v1",
        "command": args.command,
        "profile_hash": args.profile_hash,
        "base_authoring": {
            "path": str(args.base_authoring.absolute()),
            "sha256": args.base_authoring_hash,
        },
        "expected_new_bytes": args.expected_new_bytes,
        "started_at": start,
    }
    atomic_write_bytes(operation / "prelaunch.json", canonical_json_bytes(prelaunch))
    exit_code = 1
    handled = False
    result: dict[str, object]
    try:
        guard = configured_guard()
        guard.require_root(operation)
        if args.command == "import":
            guard.require_root(args.output_root)
        guard.require_lease()
        capacity = guard.check(args.expected_new_bytes)
        atomic_write_bytes(operation / "capacity.json", canonical_json_bytes(capacity))
        result = _operation(args)
        atomic_write_bytes(operation / "result.json", canonical_json_bytes(result))
        exit_code = 0
        handled = True
    except Exception as error:
        exit_code = 1
        text = str(error)
        reason = text if re.fullmatch(r"[A-Z_]{1,100}", text) else type(error).__name__
        result = {"status": "FAILED", "reason": reason}
        atomic_write_bytes(operation / "failure.json", canonical_json_bytes(result))
        handled = True
    finally:
        atomic_write_bytes(
            operation / "completion.json",
            canonical_json_bytes(
                {
                    "schema_version": "prediction-evidence-operation-completion/v1",
                    "status": ("COMPLETED" if exit_code == 0 else "FAILED")
                    if handled
                    else "INTERRUPTED_OR_UNCAUGHT",
                    "entrypoint_return_code": exit_code if handled else None,
                    "process_exit_observation": "REQUIRES_OUTER_PROCESS_OBSERVER",
                    "wall_seconds": perf_counter() - wall,
                    "cpu_seconds": process_time() - cpu,
                    "ended_at": datetime.now(UTC),
                }
            ),
        )
    print(json.dumps(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
