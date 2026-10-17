#!/usr/bin/env python3
"""Prepare/run/status/cancel/reconcile an explicitly frozen adaptive research task."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quantos.application.adaptive_execution import AdaptiveExecutionPort  # noqa: E402
from quantos.application.adaptive_namespace import AdaptiveNamespaceDispatcher  # noqa: E402
from quantos.application.adaptive_runtime import AdaptiveRuntime  # noqa: E402
from quantos.application.adaptive_sdk import AdaptiveSdkProducer  # noqa: E402
from quantos.application.adaptive_store import AdaptiveStore, contract, read, save  # noqa: E402
from quantos.application.provenance import verify_code_provenance  # noqa: E402
from quantos.artifacts.store import ArtifactIntegrityError, exclusive_directory_lock  # noqa: E402
from quantos.contracts.adaptive import AdaptiveChild, AdaptiveResearchSpec  # noqa: E402
from quantos.contracts.base import sha256_bytes  # noqa: E402
from quantos.infrastructure.hosted_storage import configured_guard  # noqa: E402


def pinned_spec(path, digest, *, read_only=False):
    data = read(path)
    if sha256_bytes(data) != digest:
        raise ArtifactIntegrityError("adaptive spec pin differs")
    spec = AdaptiveResearchSpec.model_validate_json(data)
    if data != spec.canonical_bytes() or (not read_only and Path(spec.workspace) != ROOT):
        raise ArtifactIntegrityError("canonical spec/workspace differs")
    return spec


def preflight(spec):
    verify_code_provenance(
        ROOT,
        expected_commit_hash=spec.design.bindings.code_commit_hash,
        expected_lockfile_hash=spec.design.bindings.lockfile_hash,
    )
    guard = configured_guard()
    guard.require_root(Path(spec.output_root))
    guard.require_lease()
    from quantos.application.sdk_producer import require_sdk_storage_reservation

    require_sdk_storage_reservation((Path(spec.output_root),), spec.limits.storage_growth_bytes)


def science_child(args, spec):
    preflight(spec)
    child = contract(args.child, AdaptiveChild)
    if child.content_hash != args.child_sha256 or child.task_hash != spec.content_hash:
        raise ArtifactIntegrityError("science child pin differs")
    store = AdaptiveStore(spec)
    events = store.events()
    if not any(
        e.kind == "CHILD_RESERVED" and e.reference_hash == child.content_hash for e in events
    ):
        raise ArtifactIntegrityError("science child lacks its exact frozen reservation")
    if store.get(child.content_hash, AdaptiveChild) != child:
        raise ArtifactIntegrityError("science child differs from parent authority")
    if not any(
        e.kind == "SCIENCE_STARTED" and e.reference_hash == child.content_hash for e in events
    ):
        raise ArtifactIntegrityError("science child lacks parent launch reservation")
    if (
        sum(e.kind == "SCIENCE_STARTED" for e in events) > spec.limits.scientific_executions
        or sum(e.units for e in events if e.kind == "CHILD_RESERVED") > spec.limits.compute_units
    ):
        raise ArtifactIntegrityError("science parent allowance exceeded")
    activation_bytes = read(Path(spec.output_root) / "activation.json")
    if sha256_bytes(activation_bytes) != events[0].reference_hash:
        raise ArtifactIntegrityError("science activation original differs")
    activation = json.loads(activation_bytes)
    if (
        datetime.now(UTC) >= datetime.fromisoformat(activation["deadline"])
        or (Path(spec.output_root) / "cancel-request.json").exists()
    ):
        raise TimeoutError("science launch expired or cancelled")
    job = Path(spec.output_root) / "children" / child.content_hash / "job"
    prelaunch = json.loads(read(job / "prelaunch.json"))
    if (
        prelaunch.get("request_hash") != child.request.content_hash
        or prelaunch.get("child_hash") != child.content_hash
        or prelaunch.get("task_hash") != spec.content_hash
        or prelaunch.get("parent_network_namespace") == os.readlink("/proc/self/ns/net")
        or not prelaunch.get("parent_network_namespace")
    ):
        raise ArtifactIntegrityError("science requires the bound offline namespace")
    with exclusive_directory_lock(job / "science-writer"):
        _execute_science_once(spec, child, job)


def _execute_science_once(spec, child, job):
    # This command is only invoked once by the namespace dispatcher. Parent STARTED
    # and job prelaunch remain immutable even if the child process disappears.
    claim = job / "science-claim.json"
    if claim.exists():
        raise ArtifactIntegrityError("science child was already claimed; no restart")
    port = AdaptiveExecutionPort(spec)
    adapter = port.adapter(child)
    # Adapter preparation verifies complete immutable inputs and may be slow.
    # Recheck immediately before claiming the external scientific side effect.
    events = AdaptiveStore(spec).events()
    activation_bytes = read(Path(spec.output_root) / "activation.json")
    if sha256_bytes(activation_bytes) != events[0].reference_hash:
        raise ArtifactIntegrityError("science activation original differs")
    activation = json.loads(activation_bytes)
    if (
        datetime.now(UTC) >= datetime.fromisoformat(activation["deadline"])
        or (Path(spec.output_root) / "cancel-request.json").exists()
        or any(e.kind in {"STOPPED", "CANCELLED"} for e in events)
    ):
        raise TimeoutError("science expired or cancelled during input preparation")
    save(
        claim,
        {
            "schema_version": "adaptive-science-claim/v1",
            "child_hash": child.content_hash,
            "request_hash": child.request.content_hash,
            "started_at": datetime.now(UTC),
        },
    )
    result = adapter.execute(child.request)
    verified = adapter.verified_completed_execution(child.request)
    if result != verified:
        raise ArtifactIntegrityError("science child result lacks original receipt")
    save(
        claim.parent / "child-exit.json",
        {
            "schema_version": "adaptive-science-child-exit/v1",
            "request_hash": child.request.content_hash,
            "outcome_hash": result.content_hash,
            "exit_code": 0,
            "completed_at": datetime.now(UTC),
            "model_calls": 0,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["prepare", "run", "status", "cancel", "reconcile", "science-child", "closeout"],
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Operator asserts explicit approval of this exact run package",
    )
    parser.add_argument("--child", type=Path)
    parser.add_argument("--child-sha256")
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--operator-exit", type=Path)
    parser.add_argument("--observer-exit", type=Path)
    parser.add_argument("--guard-exit", type=Path)
    parser.add_argument("--operator-operation", type=Path)
    args = parser.parse_args()
    spec = pinned_spec(args.spec, args.spec_sha256, read_only=args.command == "closeout")
    if args.command == "closeout":
        from quantos.application.adaptive_closeout import closeout_adaptive

        if args.audit_output is None:
            raise ValueError("closeout requires --audit-output outside the input tree")
        exits = {
            name: path
            for name, path in (
                ("operator", args.operator_exit),
                ("observer", args.observer_exit),
                ("guard", args.guard_exit),
            )
            if path is not None
        }
        result = closeout_adaptive(
            spec, args.audit_output, inventory=args.inventory, exit_paths=exits
        )
        print(
            json.dumps(
                {
                    "task_hash": spec.content_hash,
                    "output": str(args.audit_output),
                    "input_stable": result["input_stable"],
                    "issues": result["issues"],
                }
            )
        )
        if result["issues"] or not result["input_stable"]:
            raise SystemExit(1)
        return
    store = AdaptiveStore(spec)
    port = AdaptiveExecutionPort(spec, AdaptiveNamespaceDispatcher(spec))
    runtime = AdaptiveRuntime(spec, AdaptiveSdkProducer(spec), port)
    if args.command == "prepare":
        store.initialize()
        cwd = Path(spec.sdk_cwd)
        cwd.mkdir(parents=True, exist_ok=True)
        if any(cwd.iterdir()):
            raise ValueError("SDK cwd must be empty")
        print(
            json.dumps(
                {
                    "task_hash": spec.content_hash,
                    "status": "PREPARED_NOT_AUTHORIZED",
                    "output_root": spec.output_root,
                }
            )
        )
        return
    if args.command == "status":
        print(json.dumps(runtime.status(), ensure_ascii=False))
        return
    if args.command == "cancel":
        print(json.dumps(runtime.cancel(), ensure_ascii=False))
        return
    if args.command == "run" and not args.approved:
        raise ValueError("run requires explicit operator approval of the concrete package")
    preflight(spec)
    if args.command == "science-child":
        science_child(args, spec)
        return
    operation = (
        Path(spec.output_root) / "operations" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    save(
        operation / "prelaunch.json",
        {
            "command": args.command,
            "task_hash": spec.content_hash,
            "started_at": datetime.now(UTC),
            "actual_exit": "NOT_OBSERVED",
        },
    )
    actual_exit = 1
    try:
        result = runtime.run(receipt_only=args.command == "reconcile")
        actual_exit = 0
        print(
            json.dumps(
                {
                    "task_hash": spec.content_hash,
                    "status": result["status"],
                    "stop_reason": result["stop_reason"],
                    "output_root": spec.output_root,
                }
            )
        )
        return
    except BaseException as error:
        save(
            operation / "failure.json",
            {
                "schema_version": "adaptive-operation-failure/v1",
                "exception_class": type(error).__name__,
                "ended_at": datetime.now(UTC),
            },
        )
        runtime.checkpoint()
        raise
    finally:
        save(
            operation / "process-exit.json",
            {
                "actual_exit": actual_exit,
                "observed_by": "CONTROLLER_FINALLY_NOT_PARENT_WAITPID",
                "ended_at": datetime.now(UTC),
            },
        )


if __name__ == "__main__":
    main()
