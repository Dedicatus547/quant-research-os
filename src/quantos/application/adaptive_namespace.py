"""One science child in the retained offline namespace/mount layout, no retries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from quantos.application.adaptive_store import AdaptiveStore, read, save
from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.artifacts.store import ArtifactIntegrityError, exclusive_directory_lock
from quantos.contracts.adaptive import AdaptiveChild, AdaptiveResearchSpec
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_storage import configured_guard, require_bounded_bwrap


class AdaptiveNamespaceDispatcher:
    def __init__(self, spec: AdaptiveResearchSpec) -> None:
        self.spec = spec

    def __call__(
        self, child: AdaptiveChild, adapter: QuantosResearchExecutionAdapter
    ) -> AutonomousExecutionResult:
        # These two existing helpers only prepare mount layout and bwrap argv;
        # the old fixed-candidate service, tuple and dispatch are not invoked.
        legacy = import_module("scripts.sdk_science_namespace")
        namespace_argv = cast(Callable[..., list[str]], legacy.namespace_argv)
        prepare_layout = cast(Callable[..., dict[str, Any]], legacy.prepare_layout)

        spec = self.spec
        job = Path(spec.output_root) / "children" / child.content_hash / "job"
        guard = configured_guard()
        guard.require_root(job)
        guard.require_root(adapter.output_root)
        guard.require_lease()
        guard.check(spec.limits.storage_growth_bytes)
        activation_bytes = read(Path(spec.output_root) / "activation.json")
        if sha256_bytes(activation_bytes) != AdaptiveStore(spec).events()[0].reference_hash:
            raise ArtifactIntegrityError("science activation original differs")
        activation = json.loads(activation_bytes)
        seconds = (
            int(
                (datetime.fromisoformat(activation["deadline"]) - datetime.now(UTC)).total_seconds()
            )
            - 5
        )
        if seconds <= 0:
            raise TimeoutError("adaptive science deadline exhausted")
        require_bounded_bwrap()
        with exclusive_directory_lock(job):
            if (job / "prelaunch.json").exists():
                raise ArtifactIntegrityError("science was already dispatched; no restart")
            layout: dict[str, Any] = prepare_layout(
                child.request, adapter.output_root, job, child.request.campaign_hash
            )
            save(job / "child.json", child)
            script = Path(spec.workspace) / "scripts/adaptive_research.py"
            command = [
                sys.executable,
                "-B",
                str(script),
                "science-child",
                "--spec",
                str(Path(spec.output_root) / "spec.json"),
                "--spec-sha256",
                spec.content_hash,
                "--child",
                str(job / "child.json"),
                "--child-sha256",
                child.content_hash,
            ]
            argv: list[str] = namespace_argv(
                SimpleNamespace(workspace=Path(spec.workspace)),
                adapter.output_root,
                job,
                layout,
                command,
            )
            save(
                job / "prelaunch.json",
                {
                    "schema_version": "adaptive-science-prelaunch/v1",
                    "task_hash": spec.content_hash,
                    "child_hash": child.content_hash,
                    "request_hash": child.request.content_hash,
                    "argv": argv,
                    "timeout_seconds": seconds,
                    "network": "UNSHARED_OFFLINE",
                    "parent_network_namespace": os.readlink("/proc/self/ns/net"),
                    "model_calls": 0,
                    "started_at": datetime.now(UTC),
                },
            )
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=seconds,
                    check=False,
                )
                exit_code, outcome = completed.returncode, "EXITED"
            except subprocess.TimeoutExpired:
                exit_code, outcome = None, "TIMED_OUT"
            except OSError:
                exit_code, outcome = None, "PROCESS_START_FAILED"
            save(
                job / "process-exit.json",
                {
                    "schema_version": "adaptive-science-process-exit/v1",
                    "task_hash": spec.content_hash,
                    "child_hash": child.content_hash,
                    "request_hash": child.request.content_hash,
                    "exit_code": exit_code,
                    "outcome": outcome,
                    "wall_seconds": time.monotonic() - started,
                    "ended_at": datetime.now(UTC),
                },
            )
            if exit_code != 0:
                raise ArtifactIntegrityError(
                    "science process failed; retain originals and reconcile only"
                )
            result = adapter.verified_completed_execution(child.request)
            record = json.loads(read(job / "child-exit.json"))
            if (
                result is None
                or record.get("outcome_hash") != result.content_hash
                or record.get("exit_code") != 0
            ):
                raise ArtifactIntegrityError("science child/receipt completion differs")
            return result
