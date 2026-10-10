"""Finite offline minimum-budget exercise on an independently frozen variant B.

Management must stage a new deployment for each recipe. This worker never edits
an installed budget or accepts a policy from the research host. Synthetic frames
and these observations do not establish live provenance or grant Q06.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedSubmissionReceipt
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_fault_probe import failure_locations
from quantos.infrastructure.hosted_fixture_frames import (
    business_rejection_frame,
    deterministic_candidate_frame,
)
from quantos.infrastructure.hosted_management_runtime import (
    capture_restart_capabilities,
    management_python_flags,
    restore_restart_capabilities,
    snapshot_management_authority,
)
from quantos.infrastructure.hosted_service import (
    bootstrap_hosted_service,
    hydrate_service_capabilities,
    read_hashed_configuration,
)
from quantos.infrastructure.hosted_verification import (
    directory_inventory,
    raw_inventory,
    verify_raw_inventory,
)
from quantos.research.qlib import QlibWorkflowResearchService


def run_budget_probe(
    profile_hash: str,
    case: str,
    *,
    authority_root: Path = Path("/authority"),
    channel_root: Path = Path("/channel"),
) -> None:
    """Only fixed recipes; component root overrides are absent from the executable."""
    if case not in HOSTED_BUDGET_CASES:
        raise ValueError("unknown fixed budget case")
    recipe = HOSTED_BUDGET_CASES[case]
    authority, channel = authority_root, channel_root
    if raw_inventory(authority).files or directory_inventory(authority) or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("budget case requires fresh retained roots")
    profile = read_hashed_configuration(Path("/config"), profile_hash, HostedDeploymentProfile)
    configuration = read_hashed_configuration(
        Path("/config"), profile.configuration_hash, HostedServiceConfiguration
    )
    loader = read_hashed_configuration(
        Path("/config"),
        configuration.business_configuration_hash,
        HostedBusinessLoaderConfiguration,
    )
    bundle = read_hashed_configuration(
        Path("/inputs"), loader.business_inputs_hash, HostedFrozenBusinessInputs
    )
    if bundle.research_budget.budget_id != f"hm-q06-{case}-budget-v1":
        raise ArtifactIntegrityError("budget case requires a separately frozen variant deployment")
    spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash)
    counters: dict[str, list[str]] = {
        key: [] for key in ("execute_calls", "workflow_calls", "network_attempts")
    }
    original_execute = QuantosResearchExecutionAdapter.execute
    original_workflow = QlibWorkflowResearchService.run

    def execute(self: QuantosResearchExecutionAdapter, request: Any) -> Any:
        counters["execute_calls"].append(request.execution_identity)
        if not recipe.native_execution:
            raise ArtifactIntegrityError("nonexecution budget fixture attempted execution")
        return original_execute(self, request)

    def workflow(self: QlibWorkflowResearchService, *args: Any, **kwargs: Any) -> Any:
        counters["workflow_calls"].append("QLIB_WORKFLOW")
        if not recipe.native_execution:
            raise ArtifactIntegrityError("nonexecution budget fixture attempted Workflow")
        return original_workflow(self, *args, **kwargs)

    def network(*_args: object, **_kwargs: object) -> None:
        counters["network_attempts"].append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("budget fixture attempted network")

    def snapshot(phase: str) -> None:
        snapshot_management_authority(phase, authority, channel)
        atomic_write_bytes(
            channel / f"phase-inventories/{phase}.json", raw_inventory(authority).canonical_bytes()
        )

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", execute),
        patch.object(QlibWorkflowResearchService, "run", workflow),
        patch.object(socket.socket, "connect", network),
        patch.object(socket.socket, "connect_ex", network),
        patch.object(socket, "create_connection", network),
    ):
        hydrate_service_capabilities(profile_hash)
        capabilities = capture_restart_capabilities(configuration)

        def boot() -> HostedCampaignApplicationService:
            restore_restart_capabilities(capabilities)
            application = bootstrap_hosted_service(
                profile_hash,
                protocol_clock=lambda: spec.started_at,
                authority_root=authority,
                channel_root=channel,
            ).application
            if not isinstance(application, HostedCampaignApplicationService):
                raise ArtifactIntegrityError("budget native application differs")
            return application

        application = boot()
        application.start(spec.content_hash)
        snapshot("before")
        exits: list[dict[str, object]] = []
        for phase in ("exercise", "recovery-1", "recovery-2"):
            pid = os.fork()
            if pid == 0:
                try:
                    fresh = boot()
                    receipts: list[HostedSubmissionReceipt] = []
                    over_cap_hashes: list[str] = []
                    repeated_hash: str | None = None
                    if phase == "exercise":
                        request = fresh.pending(spec.campaign_hash)
                        if request is None:
                            raise ArtifactIntegrityError("budget request absent")
                        first_request = request
                        first_bytes = b"{}"
                        if recipe.action == "reject_frames":
                            for data in (b"{}", b"[]"):
                                receipts.append(
                                    fresh.submit(request.content_hash, data, "budget.fixture")
                                )
                        else:
                            frame = (
                                deterministic_candidate_frame(request)
                                if recipe.action == "native_candidate"
                                else business_rejection_frame(request, "known_schema_invalid")
                            )
                            first_bytes = frame
                            receipts.append(
                                fresh.submit(request.content_hash, frame, "budget.fixture")
                            )
                            fresh.resume(spec.campaign_hash)
                            if recipe.action == "global_cap":
                                request = fresh.pending(spec.campaign_hash)
                                if request is None:
                                    raise ArtifactIntegrityError("global budget case lacks R2")
                                receipts.append(
                                    fresh.submit(request.content_hash, b"{}", "budget.fixture")
                                )
                        status = fresh.resume(spec.campaign_hash)
                        if status.state != "EXHAUSTED" or status.reason != recipe.expected_reason:
                            raise ArtifactIntegrityError(
                                "budget fixture did not stop at its fixed boundary"
                            )
                        if recipe.action in ("reject_frames", "global_cap"):
                            unchanged = raw_inventory(authority)
                            unchanged_directories = directory_inventory(authority)
                            for index in range(32):
                                exhausted = fresh.submit(
                                    request.content_hash,
                                    b"FIXED_OVER_CAP_FIXTURE_" + str(index).encode(),
                                    "budget.fixture",
                                )
                                if exhausted.outcome != "EXHAUSTED":
                                    raise ArtifactIntegrityError(
                                        "over-cap fixture did not reuse exhaustion"
                                    )
                                over_cap_hashes.append(exhausted.content_hash)
                            if len(set(over_cap_hashes)) != 1:
                                raise ArtifactIntegrityError(
                                    "over-cap fixture created distinct receipts"
                                )
                            repeated = fresh.submit(
                                first_request.content_hash, first_bytes, "budget.fixture"
                            )
                            if repeated != receipts[0]:
                                raise ArtifactIntegrityError(
                                    "seen budget response was charged twice"
                                )
                            repeated_hash = repeated.content_hash
                            verify_raw_inventory(authority, unchanged)
                            if directory_inventory(authority) != unchanged_directories:
                                raise ArtifactIntegrityError("over-cap fixture changed directories")
                    else:
                        status = fresh.resume(spec.campaign_hash)
                    if counters["network_attempts"] or any(
                        name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
                        for name in sys.modules
                    ):
                        raise ArtifactIntegrityError("budget fixture crossed offline boundary")
                    result = {
                        "status": status.model_dump(mode="json"),
                        "receipts": [r.model_dump(mode="json") for r in receipts],
                        "over_cap_hashes": over_cap_hashes,
                        "repeat_receipt_hash": repeated_hash,
                    }
                    atomic_write_bytes(
                        channel / f"process-records/{phase}.json",
                        canonical_json_bytes(
                            {
                                "schema_version": "hosted-budget-process-observation/v1",
                                "phase": phase,
                                "pid": os.getpid(),
                                "parent_pid": os.getppid(),
                                "fresh_application_bootstrap": True,
                                "clock": spec.started_at.isoformat(),
                                "result_json": result,
                                "result_hash": sha256_bytes(canonical_json_bytes(result)),
                                "python_flags": management_python_flags(),
                                "python_executable": sys.executable,
                                **counters,
                            }
                        ),
                    )
                    os._exit(0)
                except Exception as error:
                    atomic_write_bytes(
                        channel / f"process-records/{phase}-failure.json",
                        canonical_json_bytes(
                            {
                                "pid": os.getpid(),
                                "error_type": type(error).__name__,
                                "failure_locations": failure_locations(error),
                                **counters,
                            }
                        ),
                    )
                    os._exit(1)
            deadline = time.monotonic() + (3600 if recipe.native_execution else 300)
            try:
                while True:
                    observed, status_code = os.waitpid(pid, os.WNOHANG)
                    if observed:
                        break
                    if time.monotonic() >= deadline:
                        raise ArtifactIntegrityError("budget child deadline exceeded")
                    time.sleep(0.02)
            except BaseException:
                try:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass
                raise
            exit_fact: dict[str, object] = {
                "phase": phase,
                "pid": observed,
                "exit_code": os.waitstatus_to_exitcode(status_code),
            }
            exits.append(exit_fact)
            atomic_write_bytes(
                channel / f"process-records/{phase}-exit.json", canonical_json_bytes(exit_fact)
            )
            if exit_fact["exit_code"] != 0:
                raise ArtifactIntegrityError("budget child failed; originals retained")
            if phase == "exercise":
                snapshot("after-exercise")
            elif phase == "recovery-1":
                verify_raw_inventory(
                    authority, raw_inventory(channel / "snapshots/after-exercise/authority")
                )
                if directory_inventory(authority) != directory_inventory(
                    channel / "snapshots/after-exercise/authority"
                ):
                    raise ArtifactIntegrityError("budget recovery changed directories")
                snapshot("after-recovery")
            else:
                verify_raw_inventory(
                    authority, raw_inventory(channel / "snapshots/after-recovery/authority")
                )
                if directory_inventory(authority) != directory_inventory(
                    channel / "snapshots/after-recovery/authority"
                ):
                    raise ArtifactIntegrityError("second budget recovery changed directories")
                snapshot("after")
        atomic_write_bytes(
            channel / "negative-observation.json",
            canonical_json_bytes(
                {
                    "schema_version": "hosted-negative-observation/v1",
                    "case_family": "Q06",
                    "case": case,
                    "fixture_kind": "BUDGET_FIXTURE",
                    "deployment_profile_hash": profile_hash,
                    "campaign_hash": spec.campaign_hash,
                    "before_inventory": raw_inventory(
                        channel / "snapshots/before/authority"
                    ).model_dump(mode="json"),
                    "after_inventory": raw_inventory(authority).model_dump(mode="json"),
                    "process_exits": exits,
                    "python_flags": management_python_flags(),
                    "python_executable": sys.executable,
                    **counters,
                    "qualification_eligibility": "NOT_QUALIFIED",
                }
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=tuple(HOSTED_BUDGET_CASES), required=True)
    args = parser.parse_args()
    run_budget_probe(args.profile_hash, args.case)


if __name__ == "__main__":
    main()
