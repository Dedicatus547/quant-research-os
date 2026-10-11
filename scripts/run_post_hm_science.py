#!/usr/bin/env python3
"""Manage one offline run/resume of the pinned discovery science workspace.

Scientific authority and checkpoint recovery remain in the existing frozen CLI.
This wrapper records resources, source identities, bounded logs and actual exits.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration
from quantos.contracts.hosted import strict_json_object, unique_json_object_pairs
from quantos.contracts.provenance import CodeProvenance
from quantos.infrastructure.hosted_deployment import NAMESPACE_TMPFS_BYTES, KnownValueGuard
from quantos.infrastructure.hosted_launcher import scan_cli_capture
from quantos.infrastructure.hosted_storage import (
    HASH_ENV,
    LEASE_ENV,
    POLICY_ENV,
    configured_guard,
    require_bounded_bwrap,
)
from quantos.security import SecretArtifactRejected

_SCIENCE_COMMIT = "dc8d5b67babf86332fb3802fb4fe783c6aec56a8"
_SCIENCE_LOCK = "0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca"
_SOURCE_INVENTORY_HASH = "6241ce9821708b76e8c622d54e7f34db7531017becfd0f80fb86ac7975dd5b4b"
_LOG_CAP = 16 << 20
_MEMORY_RESERVE = 2 << 30
_META_CAP = 16 << 20


def _read(path: Path, cap: int = _META_CAP) -> bytes:
    with opened_directory(path.parent) as fd:
        return read_regular_bytes_at(fd, path.name, max_bytes=cap)


def _memory() -> dict[str, object]:
    available: int | None = None
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                available = int(fields[1]) * 1024
    required = _MEMORY_RESERVE + NAMESPACE_TMPFS_BYTES
    if available is None or available < required:
        raise ArtifactIntegrityError("science memory reserve is unavailable")
    facts: dict[str, object] = {
        "mem_available_bytes": available,
        "science_memory_reserve_bytes": _MEMORY_RESERVE,
        "private_tmpfs_max_bytes": NAMESPACE_TMPFS_BYTES,
        "required_memory_headroom_bytes": required,
        "memory_reserve_added_to_disk_growth": False,
        "cgroup_limit_status": "UNAVAILABLE",
    }
    # WSL may expose no memory controller files. Preserve that observation;
    # absence does not attest an unlimited cgroup or a cgroup PASS.
    try:
        lines = Path("/proc/self/cgroup").read_text().splitlines()
        unified = next((line[3:] for line in lines if line.startswith("0::")), None)
        if unified is not None and ".." not in Path(unified).parts:
            root = Path("/sys/fs/cgroup") / unified.lstrip("/")
            current = int((root / "memory.current").read_text().strip())
            raw_limit = (root / "memory.max").read_text().strip()
            facts["cgroup_current_bytes"] = current
            if raw_limit == "max":
                facts["cgroup_limit_status"] = "OBSERVED_UNLIMITED"
                facts["cgroup_limit_bytes"] = None
            else:
                limit = int(raw_limit)
                facts["cgroup_limit_status"] = "OBSERVED_FINITE"
                facts["cgroup_limit_bytes"] = limit
                if current < 0 or limit - current < required:
                    raise ArtifactIntegrityError("science cgroup memory headroom is unavailable")
    except (OSError, ValueError):
        facts["cgroup_limit_status"] = "UNAVAILABLE"
    return facts


def _capture(argv: tuple[str, ...], timeout: int) -> tuple[int | None, bytes, bytes, str]:
    """Bound both pipes together; terminate the process group on a real limit."""
    output, diagnostic = bytearray(), bytearray()
    outcome = "EXITED"
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return None, b"", b"", "PROCESS_START_FAILED"
    with process:
        assert process.stdout is not None and process.stderr is not None
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, output)
            selector.register(process.stderr, selectors.EVENT_READ, diagnostic)
            while selector.get_map():
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    outcome = "TIMED_OUT"
                    break
                for key, _ in selector.select(min(0.2, remaining_time)):
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining_bytes = _LOG_CAP - len(output) - len(diagnostic)
                    cast(bytearray, key.data).extend(chunk[:remaining_bytes])
                    if len(chunk) > remaining_bytes:
                        outcome = "OUTPUT_LIMIT"
                        break
                if outcome != "EXITED":
                    break
        if outcome != "EXITED":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        try:
            exit_code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            outcome = "TIMED_OUT"
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            exit_code = process.wait()
    return exit_code, bytes(output), bytes(diagnostic), outcome


def _summary(output: bytes) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        if not line.strip() or len(line) > 65_536:
            continue
        try:
            value: object = json.loads(line, object_pairs_hook=unique_json_object_pairs)
        except (ValueError, UnicodeError, RecursionError):
            continue
        if isinstance(value, dict):
            result = cast(dict[str, object], value)
            if "report_hash" in result or result.get("status") == "FAILED":
                try:
                    canonical_json_bytes(result)
                except (ValueError, TypeError, RecursionError):
                    continue
                return result
    return None


def _evaluation(args: argparse.Namespace) -> DiscoveryEvaluationDeclaration | None:
    if args.evaluation_declaration is None:
        return None
    data = _read(args.evaluation_declaration)
    declaration = DiscoveryEvaluationDeclaration.model_validate_json(data)
    if declaration.canonical_bytes() != data:
        raise ArtifactIntegrityError("evaluation declaration must use canonical bytes")
    return declaration


def _science_source(
    args: argparse.Namespace, evaluation: DiscoveryEvaluationDeclaration | None
) -> tuple[CodeProvenance, str, dict[str, object] | None]:
    workspace = cast(Path, args.workspace)
    inventory_bytes = _read(workspace.parent / "source-inventory.json")
    inventory_hash = sha256_bytes(inventory_bytes)
    if args.source_declaration is None:
        if evaluation is not None or inventory_hash != _SOURCE_INVENTORY_HASH:
            raise ArtifactIntegrityError(
                "successor evaluation requires its explicit source capsule"
            )
        provenance = verify_code_provenance(
            workspace, expected_commit_hash=_SCIENCE_COMMIT, expected_lockfile_hash=_SCIENCE_LOCK
        )
        return provenance, inventory_hash, None
    if evaluation is None:
        raise ArtifactIntegrityError("successor science source requires an evaluation declaration")
    declaration_bytes = _read(args.source_declaration)
    declaration = strict_json_object(declaration_bytes, max_bytes=_META_CAP)
    if (
        canonical_json_bytes(declaration) != declaration_bytes
        or declaration.get("schema_version") != "post-hm-source-capsule/v1"
        or declaration.get("workspace") != str(workspace)
        or declaration.get("actual_commit") != evaluation.bindings.code_commit_hash
        or declaration.get("lockfile_hash") != evaluation.bindings.lockfile_hash
        or declaration.get("source_inventory_hash") != inventory_hash
    ):
        raise ArtifactIntegrityError("successor source declaration differs from its actual inputs")
    provenance = verify_code_provenance(
        workspace,
        expected_commit_hash=evaluation.bindings.code_commit_hash,
        expected_lockfile_hash=evaluation.bindings.lockfile_hash,
    )
    if declaration.get("code_provenance") != provenance.model_dump(mode="json"):
        raise ArtifactIntegrityError("successor source provenance is inconsistent")
    inventory = strict_json_object(inventory_bytes, max_bytes=_META_CAP)
    entries = inventory.get("files")
    if inventory.get("schema_version") != "post-hm-source-inventory/v1" or not isinstance(
        entries, list
    ):
        raise ArtifactIntegrityError("successor source inventory is incomplete")
    seen: set[str] = set()
    for value in cast(list[object], entries):
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("source inventory entry is invalid")
        entry = cast(dict[str, object], value)
        relative = entry.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or relative in seen
        ):
            raise ArtifactIntegrityError("source inventory path is invalid")
        seen.add(relative)
        path = workspace / relative
        data = _read(path)
        if (
            entry.get("bytes_hash") != sha256_bytes(data)
            or entry.get("size_bytes") != len(data)
            or entry.get("executable") is not bool(path.stat().st_mode & 0o111)
        ):
            raise ArtifactIntegrityError("successor source bytes differ from their inventory")
    if not seen or "scripts/post_hm_discovery.py" not in seen or "uv.lock" not in seen:
        raise ArtifactIntegrityError("source inventory omits the scientific entry")
    return (
        provenance,
        inventory_hash,
        {
            "path": str(args.source_declaration),
            "bytes_hash": sha256_bytes(declaration_bytes),
        },
    )


def _supersession_cutoff(
    args: argparse.Namespace,
    frozen_bytes: bytes,
    provenance: CodeProvenance,
    evaluation: DiscoveryEvaluationDeclaration | None,
) -> dict[str, object] | None:
    path = cast(Path | None, args.supersession_cutoff)
    if evaluation is not None and path is None:
        raise ArtifactIntegrityError("successor evaluation requires its explicit scheduling cutoff")
    if path is None:
        retained = args.generation_root.parent / "batch/unpurged-evaluation-cutoff.json"
        if not retained.exists():
            return None
        path = retained
    cutoff_bytes = _read(path)
    cutoff = strict_json_object(cutoff_bytes, max_bytes=_META_CAP)
    frozen = strict_json_object(frozen_bytes, max_bytes=_META_CAP)
    design = cast(dict[str, object], frozen["design"])
    original_bindings = cast(dict[str, object], design["bindings"])
    if (
        canonical_json_bytes(cutoff) != cutoff_bytes
        or cutoff.get("schema_version") != "post-hm-unpurged-evaluation-cutoff/v1"
        or cutoff.get("batch_hash") != sha256_bytes(frozen_bytes)
        or cutoff.get("blocked_source_commit") != original_bindings["code_commit_hash"]
        or cutoff.get("old_scheduling_permitted") is not False
        or cutoff.get("new_generation_permitted") is not False
        or cutoff.get("actual_supervisor_exit_code") != 1
        or cutoff.get("supervisor_cleanup_verified") is not True
        or cutoff.get("refund_claimed") is not False
    ):
        raise ArtifactIntegrityError("scheduling cutoff differs from its frozen authority")

    def original(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("cutoff original reference is absent")
        reference = cast(dict[str, object], value)
        original_path = reference.get("path")
        if not isinstance(original_path, str) or not Path(original_path).is_absolute():
            raise ArtifactIntegrityError("cutoff original requires an explicit durable path")
        data = _read(Path(original_path))
        if sha256_bytes(data) != reference.get("sha256"):
            raise ArtifactIntegrityError("cutoff original hash differs")
        record = strict_json_object(data, max_bytes=_META_CAP)
        if canonical_json_bytes(record) != data:
            raise ArtifactIntegrityError("cutoff original bytes are not canonical")
        return record

    manager = original(cutoff.get("manager_completion"))
    process_exit = original(cutoff.get("scientific_process_exit"))
    supervisor = original(cutoff.get("supervisor_exit"))
    stop = original(cutoff.get("stop_intent"))
    compute = original(cutoff.get("original_compute_reservation"))
    manager_reference = cast(dict[str, object], cutoff["manager_completion"])
    supervisor_reference = cast(dict[str, object], cutoff["supervisor_exit"])
    manager_root = Path(cast(str, manager_reference["path"])).parent
    prior_prelaunch_bytes = _read(manager_root / "prelaunch.json")
    prior_prelaunch = strict_json_object(prior_prelaunch_bytes, max_bytes=_META_CAP)
    prior_provenance = cast(dict[str, object], prior_prelaunch["science_provenance"])
    if (
        manager.get("status") != "FAILED"
        or manager.get("process_exit") != -15
        or process_exit.get("process_exit") != -15
        or manager.get("prelaunch_hash") != process_exit.get("prelaunch_hash")
        or manager.get("prelaunch_hash") != sha256_bytes(prior_prelaunch_bytes)
        or prior_prelaunch.get("batch_hash") != cutoff["batch_hash"]
        or prior_provenance.get("commit_hash") != cutoff["blocked_source_commit"]
        or supervisor.get("return_code") != 1
        or supervisor.get("cleanup_verified") is not True
        or supervisor.get("namespace_exit_observed") is not True
        or supervisor.get("waitpid_observed") is not True
        or stop.get("source_commit") != cutoff["blocked_source_commit"]
        or stop.get("reason") != cutoff.get("cause")
        or stop.get("preserve_original_attempts") is not True
        or stop.get("job_root") != str(manager_root)
        or stop.get("guard_run") != str(Path(cast(str, supervisor_reference["path"])).parent)
        or compute.get("batch_hash") != cutoff["batch_hash"]
        or compute.get("maximum_compute_units") != design["max_compute_units"]
        or compute.get("reserved_compute_units") != cutoff.get("original_initial_reservation_units")
    ):
        raise ArtifactIntegrityError("cutoff actual exits or original reservation are inconsistent")
    task_quotes = {
        cast(str, item["subtask_hash"]): cast(int, item["quoted_compute_units"])
        for item in cast(list[dict[str, object]], compute["tasks"])
    }
    references = cutoff.get("task_attempt_reservations")
    if not isinstance(references, list) or not references:
        raise ArtifactIntegrityError("cutoff started reservations are absent")
    commitments = 0
    seen: set[tuple[str, int]] = set()
    for value in cast(list[object], references):
        record = original(value)
        reference = cast(dict[str, object], value)
        reservation_path = Path(cast(str, reference["path"]))
        request_bytes = _read(reservation_path.parents[2] / "request.json")
        key, ordinal = record.get("subtask_hash"), record.get("ordinal")
        if (
            not isinstance(key, str)
            or type(ordinal) is not int
            or ordinal not in (1, 2)
            or key not in task_quotes
            or (key, ordinal) in seen
            or record.get("batch_hash") != cutoff["batch_hash"]
            or reservation_path.parents[2].name != key
            or reservation_path.parent.name != f"{ordinal:08d}"
            or record.get("request_hash") != sha256_bytes(request_bytes)
        ):
            raise ArtifactIntegrityError("cutoff started task reservation is inconsistent")
        seen.add((key, ordinal))
        commitments += task_quotes[key]
    global_max = design["max_compute_units"]
    successor_max = cutoff.get("successor_max_compute_units")
    if (
        type(global_max) is not int
        or type(successor_max) is not int
        or cutoff.get("original_global_max_compute_units") != global_max
        or cutoff.get("conservative_started_commitment_units") != commitments
        or successor_max != global_max - commitments
        or (evaluation is not None and evaluation.max_compute_units > successor_max)
    ):
        raise ArtifactIntegrityError("successor evaluation exceeds the remaining commitment cap")
    if provenance.commit_hash == cutoff["blocked_source_commit"]:
        raise ArtifactIntegrityError(
            "the retained science source is stopped by its scheduling cutoff"
        )
    return {"path": str(path), "bytes_hash": sha256_bytes(cutoff_bytes)}


def _runtime_layout(
    args: argparse.Namespace,
    frozen_bytes: bytes,
    evaluation: DiscoveryEvaluationDeclaration | None,
) -> dict[str, object]:
    """Redirect only non-authoritative MLflow paths inside the mount namespace.

    MLflow rejects run paths with any ancestor named ``artifacts``. Preserve the
    failed runtime in place; a readonly workflow overlay exposes a runtime link
    and a bind of the original native-export directory. Export paths and frozen
    scientific code therefore keep their original identities.
    """
    from quantos.application.discovery_execution import DiscoveryExecutionService
    from quantos.contracts.discovery import DiscoveryBatch

    batch = DiscoveryBatch.model_validate_json(frozen_bytes)
    service = DiscoveryExecutionService(
        batch=batch,
        snapshot_path=args.snapshot,
        qlib_view_path=args.view,
        output_root=args.output_root,
        workspace=args.workspace,
        generation_root=args.generation_root,
        evaluation_declaration=evaluation,
    )
    layout_root = args.output_root / "management-mlflow-layout"
    runtime_root = layout_root / "runtime"
    guard = configured_guard()
    guard.require_root(layout_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    mappings: list[dict[str, str]] = []
    for task in batch.subtasks:
        identity = service.task_request(task.content_hash).execution_identity
        original = args.output_root / "tasks" / task.content_hash / "executions" / identity
        workflow_root = original / "qlib-workflow"
        native_root = workflow_root / "native-records"
        overlay = layout_root / "workflow-views" / identity
        for root in (native_root, overlay / "native-records", runtime_root / identity):
            with opened_directory(root, create=True):
                pass
        link = overlay / "mlflow-runtime"
        target = f"/tmp/qlib-runtime/{identity}"
        if link.is_symlink():
            if os.readlink(link) != target:
                raise ArtifactIntegrityError("MLflow namespace layout differs from its binding")
        elif link.exists():
            raise ArtifactIntegrityError("MLflow namespace runtime link is occupied")
        else:
            link.symlink_to(target, target_is_directory=True)
        mappings.append(
            {
                "subtask_hash": task.content_hash,
                "execution_identity": identity,
                "workflow_path": str(workflow_root),
                "readonly_overlay": str(overlay),
                "native_export_path": str(native_root),
                "runtime_namespace_path": target,
                "runtime_durable_path": str(runtime_root / identity),
                "preserved_original_runtime": str(workflow_root / "mlflow-runtime"),
            }
        )
    receipt: dict[str, object] = {
        "schema_version": "discovery-science-mlflow-mount-layout/v1",
        "batch_hash": batch.content_hash,
        "evaluation_identity": service.evaluation_identity,
        "runtime_durable_root": str(runtime_root),
        "runtime_namespace_root": "/tmp/qlib-runtime",
        "mappings": mappings,
        "frozen_scientific_source_changed": False,
        "failed_original_runtime_modified": False,
        "native_exports_keep_original_paths": True,
        "mlflow_runtime_is_authority": False,
    }
    atomic_write_bytes(args.job_root / "mlflow-layout.json", canonical_json_bytes(receipt))
    return receipt


def run(args: argparse.Namespace) -> dict[str, object]:
    guard = configured_guard()
    guard.require_root(args.output_root)
    guard.require_root(args.job_root)
    guard.require_lease()
    require_bounded_bwrap()
    lease_name = os.environ.get(LEASE_ENV)
    if lease_name is None:
        raise ArtifactIntegrityError("science requires the formal supervisor lease")
    lease_root = Path(lease_name)
    lease_bytes = _read(lease_root / "prelaunch.json", 16_384)
    lease = strict_json_object(lease_bytes, max_bytes=16_384)
    growth_bytes = _read(args.growth_estimate)
    growth = strict_json_object(growth_bytes, max_bytes=_META_CAP)
    components = growth.get("growth_components")
    if not isinstance(components, dict):
        raise ArtifactIntegrityError("science growth estimate is incomplete")
    estimate = cast(dict[str, object], components).get("expected_new_durable_bytes")
    reserved = lease.get("expected_new_bytes")
    expected = cast(int, args.expected_new_bytes)
    if (
        type(estimate) is not int
        or estimate < 18 << 30
        or expected < estimate
        or type(reserved) is not int
        or reserved < expected
    ):
        raise ArtifactIntegrityError("science complete growth exceeds its lease reservation")
    capacity = guard.check(expected)
    memory = _memory()
    workspace = cast(Path, args.workspace)
    for root in (workspace, args.snapshot, args.view, args.generation_root):
        if root.resolve(strict=True) != root or not root.is_dir():
            raise ArtifactIntegrityError("science inputs require canonical readonly directories")
    for writable in (args.output_root, args.job_root):
        if any(
            writable.is_relative_to(root) or root.is_relative_to(writable)
            for root in (workspace, args.snapshot, args.view, args.generation_root)
        ):
            raise ArtifactIntegrityError("science writable and immutable roots overlap")
    for declaration_path in (
        args.source_declaration,
        args.evaluation_declaration,
        args.supersession_cutoff,
    ):
        if declaration_path is not None and (
            declaration_path.resolve(strict=True) != declaration_path
            or any(
                declaration_path.is_relative_to(writable)
                for writable in (args.output_root, args.job_root)
            )
        ):
            raise ArtifactIntegrityError(
                "science declarations must remain canonical readonly inputs"
            )
    evaluation = _evaluation(args)
    provenance, inventory_hash, source_declaration = _science_source(args, evaluation)
    frozen_bytes = _read(args.generation_root / "frozen.json")
    frozen = strict_json_object(frozen_bytes, max_bytes=_META_CAP)
    design_value = frozen.get("design")
    if not isinstance(design_value, dict):
        raise ArtifactIntegrityError("science requires the completed frozen discovery batch")
    design = cast(dict[str, object], design_value)
    if growth.get("design_hash") != sha256_bytes(canonical_json_bytes(design)):
        raise ArtifactIntegrityError("science growth estimate belongs to another frozen design")
    cutoff = _supersession_cutoff(args, frozen_bytes, provenance, evaluation)
    cli = workspace / "scripts/post_hm_discovery.py"
    command = (
        str(Path(sys.executable).absolute()),
        str(cli),
        "--generation-root",
        str(args.generation_root),
        args.command,
        "--snapshot",
        str(args.snapshot),
        "--view",
        str(args.view),
        "--output-root",
        str(args.output_root),
        "--workspace",
        str(workspace),
        "--expected-new-bytes",
        str(expected),
    )
    if evaluation is not None:
        command += ("--evaluation-declaration", str(args.evaluation_declaration))
    with exclusive_directory_lock(args.job_root):
        if (args.job_root / "prelaunch.json").exists():
            raise ArtifactIntegrityError("science job already has an immutable prelaunch")
        with opened_directory(args.output_root, create=True):
            pass
        argv: list[str] = [
            "/usr/bin/bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev-bind",
            "/dev",
            "/dev",
            "--size",
            str(NAMESPACE_TMPFS_BYTES),
            "--tmpfs",
            "/tmp",
            "--dir",
            "/tmp/home",
        ]
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp/home",
            "TMPDIR": "/tmp",
            "PYTHONPATH": str(workspace / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "GIT_OPTIONAL_LOCKS": "0",
            "MLFLOW_DISABLE_TELEMETRY": "true",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
        }
        for name in (POLICY_ENV, HASH_ENV, LEASE_ENV):
            value = os.environ.get(name)
            if value is None:
                raise ArtifactIntegrityError("science supervisor configuration is incomplete")
            environment[name] = value
        for name, value in environment.items():
            argv.extend(("--setenv", name, value))
        # require_lease opens this actual inode O_RDWR and observes the existing
        # exclusive supervisor lock; the remainder of lease control stays RO.
        lease_lock = lease_root.parent / "lease.lock"
        for root in (args.output_root, args.job_root, lease_lock):
            argv.extend(("--bind", str(root), str(root)))
        layout = _runtime_layout(args, frozen_bytes, evaluation)
        argv.extend(("--bind", str(layout["runtime_durable_root"]), "/tmp/qlib-runtime"))
        for mapping in cast(list[dict[str, str]], layout["mappings"]):
            argv.extend(
                (
                    "--ro-bind",
                    mapping["readonly_overlay"],
                    mapping["workflow_path"],
                    "--bind",
                    mapping["native_export_path"],
                    mapping["native_export_path"],
                )
            )
        argv.extend(("--chdir", str(workspace), *command))
        prelaunch = canonical_json_bytes(
            {
                "schema_version": "discovery-science-management-prelaunch/v1",
                "command": args.command,
                "batch_hash": sha256_bytes(frozen_bytes),
                "design_hash": growth["design_hash"],
                "runner_hash": sha256_file(Path(__file__).absolute()),
                "science_cli_hash": sha256_file(cli),
                "science_workspace": str(workspace),
                "science_provenance": provenance.model_dump(mode="json"),
                "source_inventory_hash": inventory_hash,
                "source_declaration": source_declaration,
                "evaluation_declaration_hash": None
                if evaluation is None
                else evaluation.content_hash,
                "supersession_cutoff": cutoff,
                "interpreter_path": command[0],
                "interpreter_binary_path": str(Path(command[0]).resolve(strict=True)),
                "interpreter_hash": sha256_file(Path(command[0]).resolve(strict=True)),
                "command_hash": sha256_bytes(canonical_json_bytes(command)),
                "namespace_argv_hash": sha256_bytes(canonical_json_bytes(argv)),
                "mlflow_layout_hash": sha256_bytes(canonical_json_bytes(layout)),
                "network": "UNSHARED_OFFLINE",
                "storage_policy_hash": guard.policy_hash,
                "lease_prelaunch_hash": sha256_bytes(lease_bytes),
                "expected_new_bytes": expected,
                "growth_estimate_hash": sha256_bytes(growth_bytes),
                "capacity": capacity,
                "memory": memory,
                "log_byte_cap": _LOG_CAP,
                "timeout_seconds": args.timeout_seconds,
                "started_at": datetime.now(UTC),
            }
        )
        atomic_write_bytes(args.job_root / "prelaunch.json", prelaunch)
        started = time.monotonic()
        exit_code, output, diagnostic, outcome = _capture(tuple(argv), args.timeout_seconds)
        # Preserve this independent completed step before parsing or publishing logs.
        # A later publication failure must not erase the observed child exit.
        atomic_write_bytes(
            args.job_root / "process-exit.json",
            canonical_json_bytes(
                {
                    "schema_version": "discovery-science-management-process-exit/v1",
                    "prelaunch_hash": sha256_bytes(prelaunch),
                    "process_outcome": outcome,
                    "process_exit": exit_code,
                    "terminated_at": datetime.now(UTC),
                }
            ),
        )
        logs_safe = True
        try:
            log_guard = KnownValueGuard((), byte_cap=_LOG_CAP)
            scan_cli_capture(output, guard=log_guard)
            scan_cli_capture(diagnostic, guard=log_guard)
            atomic_write_bytes(args.job_root / "stdout.txt", output)
            atomic_write_bytes(args.job_root / "stderr.txt", diagnostic)
        except (ValueError, UnicodeError, RecursionError, SecretArtifactRejected):
            logs_safe = False
        try:
            summary = _summary(output) if logs_safe else None
        except (ValueError, TypeError, RecursionError):
            summary = None
        if summary is not None:
            atomic_write_bytes(args.job_root / "result.json", canonical_json_bytes(summary))
        status = (
            "COMPLETED"
            if exit_code == 0 and outcome == "EXITED" and summary is not None and logs_safe
            else "FAILED"
        )
        completion = {
            "schema_version": "discovery-science-management-completion/v1",
            "prelaunch_hash": sha256_bytes(prelaunch),
            "status": status,
            "process_outcome": outcome,
            "process_exit": exit_code,
            "logs_safe": logs_safe,
            "logs_complete": outcome == "EXITED",
            "stdout_bytes": len(output),
            "stderr_bytes": len(diagnostic),
            "stdout_hash": sha256_bytes(output) if logs_safe else None,
            "stderr_hash": sha256_bytes(diagnostic) if logs_safe else None,
            "result_hash": sha256_bytes(canonical_json_bytes(summary))
            if summary is not None
            else None,
            "wall_seconds": time.monotonic() - started,
            "terminated_at": datetime.now(UTC),
            "scientific_verdict": "READ_THE_EXISTING_COMPARISON_AND_VALIDATION_ORIGINALS",
        }
        atomic_write_bytes(args.job_root / "completion.json", canonical_json_bytes(completion))
        return {
            "status": status,
            "process_exit": exit_code,
            "process_outcome": outcome,
            "job_root": str(args.job_root),
            "result": summary,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume"))
    for name in (
        "snapshot",
        "view",
        "output-root",
        "workspace",
        "generation-root",
        "job-root",
        "growth-estimate",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source-declaration", type=Path)
    parser.add_argument("--evaluation-declaration", type=Path)
    parser.add_argument("--supersession-cutoff", type=Path)
    parser.add_argument("--expected-new-bytes", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=86_400)
    args = parser.parse_args()
    try:
        if args.timeout_seconds <= 0:
            raise ArtifactIntegrityError("science timeout must be positive")
        for name in (
            "snapshot",
            "view",
            "output_root",
            "workspace",
            "generation_root",
            "job_root",
            "growth_estimate",
        ):
            setattr(args, name, cast(Path, getattr(args, name)).absolute())
        for name in ("source_declaration", "evaluation_declaration", "supersession_cutoff"):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, cast(Path, value).absolute())
        result = run(args)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "COMPLETED" else 1
    except Exception as error:
        # Never print arbitrary paths, scientific payloads, environment or secrets.
        with suppress(Exception):
            failure_guard = configured_guard()
            failure_guard.require_root(args.job_root)
            atomic_write_bytes(
                args.job_root / "management-failure.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-science-management-failure/v1",
                        "status": "FAILED",
                        "reason": "SCIENCE_MANAGEMENT_FAILED",
                        "error_type": type(error).__name__,
                        "recorded_at": datetime.now(UTC),
                    }
                ),
            )
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": "SCIENCE_MANAGEMENT_FAILED",
                    "error_type": type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
