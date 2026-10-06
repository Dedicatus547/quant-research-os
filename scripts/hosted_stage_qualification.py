#!/usr/bin/env python3
"""Capture a new offline hosted attempt; no provider authentication or qualification."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.hosted_live_qualification import author_p14dq_business_inputs

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_deployment import HostedLauncherConfiguration
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_budget_deployment import stage_managed_budget_deployment
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_fault_cases import ATOMIC_FAULT_WINDOWS, MANAGEMENT_FAULT_WINDOWS
from quantos.infrastructure.hosted_fixture_frames import (
    BOUNDED_REJECTION_CASES,
    BUSINESS_REJECTION_CASES,
    DUPLICATE_SUBMISSION_CASES,
    HOST_OBSERVATION_CASES,
)
from quantos.infrastructure.hosted_lifecycle_cases import HOSTED_LIFECYCLE_CASES
from quantos.infrastructure.hosted_manager import (
    HostedManagedDeployment,
    capture_authority_snapshot,
    probe_managed_deployment,
    restricted_client_call,
    run_managed_admission_case,
    run_managed_budget_case,
    run_managed_duplicate_case,
    run_managed_fault_case,
    run_managed_lifecycle_case,
    run_managed_negative_case,
    run_managed_observation_case,
    stage_hosted_deployment,
    start_managed_service,
    stop_managed_service,
)
from quantos.infrastructure.hosted_negative_probe import NEGATIVE_CASES
from quantos.infrastructure.hosted_regression_capture import prepare_managed_regression
from quantos.infrastructure.hosted_security_verification import verify_deployment_security
from quantos.infrastructure.hosted_storage import storage_checkpoint
from quantos.infrastructure.hosted_verification import raw_inventory, verify_raw_inventory

MATRIX = (
    *(("Q02", case) for case in DUPLICATE_SUBMISSION_CASES),
    *(("Q03", case) for case in NEGATIVE_CASES),
    *(("Q04", case) for case in (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES)),
    *(("Q05", case) for case in (*MANAGEMENT_FAULT_WINDOWS, *ATOMIC_FAULT_WINDOWS)),
    *(("Q06", case) for case in (*HOSTED_LIFECYCLE_CASES, *HOSTED_BUDGET_CASES)),
    *(("Q08", case) for case in HOST_OBSERVATION_CASES),
)
RUNNERS = {
    "Q02": run_managed_duplicate_case,
    "Q03": run_managed_negative_case,
    "Q04": run_managed_admission_case,
    "Q05": run_managed_fault_case,
    "Q06": run_managed_lifecycle_case,
    "Q08": run_managed_observation_case,
}


def publish(directory: Path, name: str, value: dict[str, object]) -> None:
    path = directory / name
    if path.exists() or path.is_symlink():
        raise ArtifactIntegrityError("offline capture record already exists")
    atomic_write_bytes(path, canonical_json_bytes(value))


def capture_restart_and_security(deployment: HostedManagedDeployment) -> None:
    process = start_managed_service(deployment)
    record: dict[str, object] = {"deployment_profile_hash": deployment.profile.content_hash}
    try:
        record["start"] = restricted_client_call(deployment, "start")
        before = raw_inventory(deployment.paths.authority)
        capture_authority_snapshot(deployment, "qualification-cases/Q01/before/authority")
        pending = restricted_client_call(deployment, "pending")
        record["pending_before"] = pending
        record["before_wrapper_pid"] = process.pid
        stop_managed_service(deployment, process)
        record["before_wrapper_return_code"] = process.returncode
        process = start_managed_service(deployment)
        record["after_wrapper_pid"] = process.pid
        queries: list[dict[str, object]] = []
        for _ in range(2):
            observed = restricted_client_call(deployment, "pending")
            if observed != pending:
                raise ArtifactIntegrityError("service restart changed pending request bytes")
            queries.extend((observed, restricted_client_call(deployment, "status")))
            queries.append(restricted_client_call(deployment, "resume"))
        verify_raw_inventory(deployment.paths.authority, before)
        capture_authority_snapshot(deployment, "qualification-cases/Q01/after/authority")
        record.update(
            schema_version="hosted-manager-suspend-restart/v1",
            before_inventory=before.model_dump(mode="json"),
            after_inventory=raw_inventory(deployment.paths.authority).model_dump(mode="json"),
            queries=queries,
            qualification_eligibility="NOT_QUALIFIED",
        )
        KnownValueGuard((deployment.capability,))(canonical_json_bytes(record))
        publish(deployment.root / "evidence", "offline-suspend-restart.json", record)
        probe_managed_deployment(deployment)
        verify_deployment_security(deployment)
    finally:
        stop_managed_service(deployment, process)
        publish(
            deployment.root / "evidence",
            "offline-service-stop.json",
            {
                "pid": process.pid,
                "return_code": process.returncode,
                "wait_observed": True,
                "qualification_eligibility": "NOT_QUALIFIED",
            },
        )


def capture_ci(command: tuple[str, ...], records: Path) -> None:
    publish(records, "ci-prelaunch.json", {"argv": command})
    interrupted = False
    with (records / "ci-output.log").open("xb") as output:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            publish(records, "ci-start.json", {"pid": process.pid})
            process.wait()
        except BaseException:
            interrupted = True
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            result: dict[str, object] = {
                "pid": process.pid,
                "return_code": process.returncode,
                "wait_observed": True,
                "interrupted": interrupted,
            }
            publish(records, "ci-exit.json", result)
    if process.returncode != 0:
        raise ArtifactIntegrityError("offline CI failed; matrix scheduling stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    names = (
        "workspace",
        "root",
        "wheel",
        "base-python",
        "dependency-site",
        "codex-binary",
        "node-binary",
    )
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.absolute()
    workspace = arguments.workspace.absolute()
    if root.exists() or root.is_symlink():
        raise ArtifactIntegrityError("offline attempt requires a new retained root")
    storage_checkpoint(root, "deployment")
    records = root.parent / (root.name + "-orchestration")
    records.mkdir(mode=0o700)
    completed: list[tuple[str, str]] = []
    step_number = 0
    active_step = "author-and-stage"

    def step(name: str, action: Callable[[], object]) -> None:
        nonlocal step_number, active_step
        step_number += 1
        active_step = name
        prefix = f"{step_number:03d}-{name}"
        started: dict[str, object] = {"step": name, "started_at": datetime.now(UTC).isoformat()}
        publish(records, prefix + "-start.json", started)
        action()
        finished: dict[str, object] = {"step": name, "finished_at": datetime.now(UTC).isoformat()}
        publish(records, prefix + "-complete.json", finished)

    publish(
        records,
        "plan.json",
        {
            "schema_version": "hosted-offline-stage-plan/v1",
            "root": str(root),
            "workspace": str(workspace),
            "source_hash": sha256_file(Path(__file__)),
            "matrix": MATRIX,
            "matrix_cases": len(MATRIX),
            "matrix_workers": 1,
            "ci_before_matrix": True,
            "qualification": "NOT_QUALIFIED",
        },
    )
    try:
        configuration = HostedLauncherConfiguration(
            model="gpt-6.1-sol",
            reasoning_effort="high",
            output_byte_cap=1_048_576,
            proposal_byte_cap=262144,
            runtime_timeout_seconds=900,
        )
        bundle, objects = author_p14dq_business_inputs(
            workspace,
            records / "seed",
            started_at=datetime.now(UTC),
            configuration=configuration,
        )
        deployment = stage_hosted_deployment(
            root,
            workspace,
            bundle,
            objects,
            records / "seed/ledger",
            wheel=arguments.wheel.absolute(),
            base_python=arguments.base_python.absolute(),
            dependency_site=arguments.dependency_site.absolute(),
            codex_binary=arguments.codex_binary.absolute(),
            launcher_configuration=configuration,
        )
        publish(
            records,
            "identity.json",
            {
                "business_inputs_hash": bundle.content_hash,
                "deployment_profile_hash": deployment.profile.content_hash,
                "exact_commit": deployment.profile.exact_commit,
                "lock_hash": deployment.profile.lock_hash,
                "wheel_hash": deployment.profile.wheel_hash,
                "configuration_hash": deployment.configuration.content_hash,
                "install_inventory_hash": deployment.install.content_hash,
                "model_configuration_hash": configuration.content_hash,
                "qualification": "NOT_QUALIFIED",
            },
        )
        step("Q01-Q07", lambda: capture_restart_and_security(deployment))
        command = prepare_managed_regression(
            deployment, workspace, node_source=arguments.node_binary
        )
        step("Q12", lambda: capture_ci(command, records))
        for family, case in MATRIX:

            def run_case(family: str = family, case: str = case) -> Path:
                subject = deployment
                if family == "Q06" and case in HOSTED_BUDGET_CASES:
                    subject = stage_managed_budget_deployment(
                        deployment,
                        case,
                        workspace,
                        base_python=arguments.base_python,
                        dependency_site=arguments.dependency_site,
                    )
                    return run_managed_budget_case(subject, case)
                return RUNNERS[family](subject, case)

            step(f"{family}-{case}", run_case)
            completed.append((family, case))
        result: dict[str, object] = {
            "state": "OFFLINE_CAPTURE_COMPLETE",
            "completed_cases": completed,
            "qualification": "NOT_QUALIFIED",
        }
        publish(records, "result.json", result)
    except BaseException as error:
        publish(
            records,
            "failure.json",
            {
                "state": "FAILED",
                "validation": "NOT_EVALUATED",
                "error_type": type(error).__name__,
                "active_step": active_step,
                "completed_cases": completed,
                "qualification": "NOT_QUALIFIED",
            },
        )
        raise


if __name__ == "__main__":
    main()
