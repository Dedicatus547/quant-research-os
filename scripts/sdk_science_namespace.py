#!/usr/bin/env python3
"""Management namespace for a newly frozen two-step SDK campaign; no SDK calls or retries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

FAILED_EXECUTION = "6e75906de5c1e676636ab995eabf7c33bfc16e834c2840bc6dc7376a8691f5d6"
TMPFS_BYTES = 64 << 20


def pinned(path, digest):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("SCI2 management dependency hash differs")
    return data


def write(path, value):
    from quantos.artifacts.store import atomic_write_bytes
    from quantos.contracts.base import canonical_json_bytes

    atomic_write_bytes(Path(path), canonical_json_bytes(value))


def frozen_tuple(args):
    from quantos.contracts.hosted import parse_hosted_contract
    from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration
    from quantos.contracts.sdk_producer import (
        SdkCampaignSpec,
        SdkProducerProfileV2,
        SdkProducerProfileV3,
        SdkProducerProfileV4,
    )

    config = parse_hosted_contract(
        pinned(args.metadata_root / "loader-config.json", args.expected_config_hash),
        HostedBusinessLoaderConfiguration,
        max_bytes=65536,
    )
    spec = parse_hosted_contract(
        pinned(args.metadata_root / "sdk-campaign-spec.json", args.expected_spec_hash),
        SdkCampaignSpec,
        max_bytes=1048576,
    )
    if (
        config.provenance_workspace != str(args.workspace)
        or spec.sdk_profile.max_launches != 2
        or spec.sdk_profile.max_attempts != 1
        or not isinstance(
            spec.sdk_profile, (SdkProducerProfileV2, SdkProducerProfileV3, SdkProducerProfileV4)
        )
        or spec.campaign_hash == "3e2f36eff8302ad83c27cf469ff9e4f63e380ee8b99e1aa89c4bca25232fa51b"
    ):
        raise ValueError("SCI2 frozen loader tuple differs")
    return config, spec


def request_check(request, campaign_hash):
    if (
        request.campaign_hash != campaign_hash
        or request.trial_ordinal not in (1, 2)
        or request.execution_identity == FAILED_EXECUTION
    ):
        raise ValueError(
            "only an original request from the new frozen two-step campaign may execute"
        )


def prepare_layout(request, execution_root, job_root, campaign_hash):
    """Root-owned invocation only; reproduces completed B2 mount layout."""
    from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
    from quantos.infrastructure.hosted_storage import configured_guard

    request_check(request, campaign_hash)
    execution_root, job_root = Path(execution_root), Path(job_root)
    guard = configured_guard()
    for root in (execution_root, job_root):
        guard.require_root(root)
    guard.require_lease()
    identity = request.execution_identity
    layout_root = execution_root / "management-mlflow-layout-sdk-campaign"
    workflow = execution_root / "executions" / identity / "qlib-workflow"
    native = workflow / "native-records"
    overlay = layout_root / "workflow-views" / identity
    runtime_root = layout_root / "runtime"
    for root in (native, overlay / "native-records", runtime_root / identity, job_root):
        with opened_directory(root, create=True):
            pass
    target = f"/tmp/qlib-runtime/{identity}"
    link = overlay / "mlflow-runtime"
    if link.is_symlink():
        if os.readlink(link) != target:
            raise ArtifactIntegrityError("SCI2 runtime alias differs")
    elif link.exists():
        raise ArtifactIntegrityError("SCI2 runtime alias occupied")
    else:
        link.symlink_to(target, target_is_directory=True)
    layout = {
        "schema_version": "sdk-campaign-science-mlflow-mount-layout/v1",
        "execution_identity": identity,
        "execution_request_hash": request.content_hash,
        "runtime_durable_root": str(runtime_root),
        "runtime_namespace_root": "/tmp/qlib-runtime",
        "workflow_path": str(workflow),
        "readonly_overlay": str(overlay),
        "native_export_path": str(native),
        "runtime_durable_path": str(runtime_root / identity),
        "runtime_namespace_path": target,
        "failed_original_runtime_modified": False,
        "frozen_scientific_source_changed": False,
        "native_exports_keep_original_paths": True,
        "mlflow_runtime_is_authority": False,
    }
    write(job_root / "mlflow-layout.json", layout)
    return layout


def namespace_argv(args, execution_root, job_root, layout, command):
    from quantos.infrastructure.hosted_storage import HASH_ENV, LEASE_ENV, POLICY_ENV

    argv = [
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
        str(TMPFS_BYTES),
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tmp/home",
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp/home",
        "TMPDIR": "/tmp",
        "PYTHONPATH": str(args.workspace / "src"),
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
        if not os.environ.get(name):
            raise ValueError("SCI2 storage supervisor binding missing")
        env[name] = os.environ[name]
    for name, value in env.items():
        argv.extend(("--setenv", name, value))
    lease_lock = Path(env[LEASE_ENV]).parent / "lease.lock"
    for root in (Path(execution_root), Path(job_root), lease_lock):
        argv.extend(("--bind", str(root), str(root)))
    argv.extend(
        (
            "--bind",
            layout["runtime_durable_root"],
            "/tmp/qlib-runtime",
            "--ro-bind",
            layout["readonly_overlay"],
            layout["workflow_path"],
            "--bind",
            layout["native_export_path"],
            layout["native_export_path"],
            "--chdir",
            str(args.workspace),
            *command,
        )
    )
    return argv


@contextmanager
def configure_execution_namespace(service, args, run):
    """Dispatch each original trial once to an offline namespace; no failed execution resume."""
    from quantos.artifacts.store import exclusive_directory_lock
    from quantos.infrastructure.hosted_storage import require_bounded_bwrap

    _, spec = frozen_tuple(args)
    adapter = service._registered(spec.campaign_hash).orchestrator.execution_port
    called = set()

    def dispatch(request):
        request_check(request, spec.campaign_hash)
        if request.trial_ordinal in called:
            raise RuntimeError("SCI2 dispatch cannot retry")
        called.add(request.trial_ordinal)
        job = Path(run) / f"science-{request.trial_ordinal}-namespace"
        deadline = datetime.fromisoformat(args.deadline_utc)
        seconds = int((deadline - datetime.now(UTC)).total_seconds()) - 5
        if seconds <= 0:
            raise TimeoutError("authorized deadline elapsed before SCI2")
        require_bounded_bwrap()
        with exclusive_directory_lock(job):
            if (job / "prelaunch.json").exists():
                raise RuntimeError("SCI2 namespace already launched")
            layout = prepare_layout(request, adapter.output_root, job, spec.campaign_hash)
            write(job / "request.json", request.model_dump(mode="json"))
            request_sha = hashlib.sha256((job / "request.json").read_bytes()).hexdigest()
            helper = Path(__file__).absolute()
            helper_sha = args.science_management_helper_hash
            pinned(helper, helper_sha)
            command = [
                str(Path(sys.executable).absolute()),
                "-B",
                str(helper),
                "child",
                "--workspace",
                str(args.workspace),
                "--live-root",
                str(args.live_root),
                "--metadata-root",
                str(args.metadata_root),
                "--expected-config-hash",
                args.expected_config_hash,
                "--expected-spec-hash",
                args.expected_spec_hash,
                "--request",
                str(job / "request.json"),
                "--expected-request-hash",
                request_sha,
                "--expected-helper-hash",
                helper_sha,
                "--job-root",
                str(job),
                "--deadline-utc",
                args.deadline_utc,
            ]
            argv = namespace_argv(args, adapter.output_root, job, layout, command)
            write(
                job / "prelaunch.json",
                {
                    "schema_version": "sdk-campaign-science-namespace-prelaunch/v1",
                    "argv": argv,
                    "execution_identity": request.execution_identity,
                    "execution_request_hash": request.content_hash,
                    "helper_sha256": helper_sha,
                    "timeout_seconds": seconds,
                    "started_utc": datetime.now(UTC),
                    "network": "UNSHARED_OFFLINE",
                    "namespace_tmpfs_bytes": TMPFS_BYTES,
                    "model_calls": 0,
                },
            )
            start = time.monotonic()
            # Child writes bounded structured failures directly to durable job storage.
            # Native/Qlib stdout is deliberately not retained or printed here.
            try:
                process = subprocess.run(
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=seconds,
                    check=False,
                )
                actual_exit, outcome = process.returncode, "EXITED"
            except subprocess.TimeoutExpired:
                actual_exit, outcome = None, "TIMED_OUT"
            except OSError as error:
                write(
                    job / "launch-error.json",
                    {"error_class": type(error).__name__, "utc": datetime.now(UTC)},
                )
                actual_exit, outcome = None, "LAUNCH_FAILED"
            write(
                job / "process-exit.json",
                {
                    "schema_version": "sdk-campaign-science-namespace-process-exit/v1",
                    "actual_exit": actual_exit,
                    "process_outcome": outcome,
                    "elapsed_wall_seconds": time.monotonic() - start,
                    "ended_utc": datetime.now(UTC),
                    "execution_identity": request.execution_identity,
                },
            )
            if actual_exit != 0 or outcome != "EXITED":
                raise RuntimeError("SCI2 namespace failed; immutable exit retained; no retry")
            result = adapter.inspect_completed_execution(request)
            if result is None:
                raise RuntimeError("SCI2 child lacks verified completion receipt")
            child = json.loads((job / "child-exit.json").read_bytes())
            if (
                child.get("actual_exit") != 0
                or child.get("execution_result_hash") != result.content_hash
            ):
                raise RuntimeError("SCI2 child result differs from original verified receipt")
            write(
                job / "completion.json",
                {
                    "schema_version": "sdk-campaign-science-namespace-completion/v1",
                    "actual_exit": 0,
                    "execution_identity": request.execution_identity,
                    "execution_result_hash": result.content_hash,
                    "execution_artifact_hash": result.execution_artifact_hash,
                    "verified_original_receipt": True,
                    "model_calls": 0,
                    "completed_utc": datetime.now(UTC),
                },
            )
            return result

    with patch.object(adapter, "execute", dispatch):
        yield


def child(args):
    sys.path.insert(0, str(args.workspace / "src"))
    from quantos.application import autonomous_execution
    from quantos.application.hosted_inputs import load_hosted_campaign_application
    from quantos.application.hosted_protocol import HostedProtocolService
    from quantos.contracts.autonomous import AutonomousExecutionRequest
    from quantos.infrastructure.hosted_store import HostedProtocolStore

    try:
        pinned(Path(__file__), args.expected_helper_hash)
        if not Path(autonomous_execution.__file__).resolve().is_relative_to(args.workspace / "src"):
            raise ValueError("SCI2 imports different frozen execution source")
        if datetime.now(UTC) >= datetime.fromisoformat(args.deadline_utc):
            raise TimeoutError("authorized deadline elapsed in SCI2 child")
        request = AutonomousExecutionRequest.model_validate_json(
            pinned(args.request, args.expected_request_hash)
        )
        config, spec = frozen_tuple(args)
        request_check(request, spec.campaign_hash)
        holder = []
        protocol = HostedProtocolService(
            HostedProtocolStore(args.live_root / "protocol"),
            verify_inputs=lambda value: holder[0].verify_registered_inputs(value),
        )
        service = load_hosted_campaign_application(
            config,
            protocol,
            args.live_root / "business-locks",
            deployment_profile_hash=spec.deployment_profile_hash,
            sdk_spec=spec,
        )
        holder.append(service)
        execution = service._registered(spec.campaign_hash).orchestrator.execution_port
        result = execution.execute(request)
        verified = execution.inspect_completed_execution(request)
        if verified is None or verified.content_hash != result.content_hash:
            raise RuntimeError("SCI2 returned result lacks matching original receipt")
        write(
            args.job_root / "child-exit.json",
            {
                "actual_exit": 0,
                "execution_identity": request.execution_identity,
                "execution_result_hash": verified.content_hash,
                "execution_artifact_hash": verified.execution_artifact_hash,
                "model_calls": 0,
                "utc": datetime.now(UTC),
            },
        )
        return 0
    except Exception as error:
        write(
            args.job_root / "child-exit.json",
            {
                "actual_exit": 1,
                "error_class": type(error).__name__,
                "failure_frames": [
                    {
                        "filename": Path(frame.filename).name,
                        "function": frame.name,
                        "line": frame.lineno,
                    }
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
                "model_calls": 0,
                "utc": datetime.now(UTC),
            },
        )
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("child",))
    for name in ("workspace", "live-root", "metadata-root", "request", "job-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "expected-config-hash",
        "expected-spec-hash",
        "expected-request-hash",
        "expected-helper-hash",
        "deadline-utc",
    ):
        parser.add_argument("--" + name, required=True)
    return child(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
