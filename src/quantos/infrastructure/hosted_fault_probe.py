"""Physical exits and fresh disk bootstraps in the fixed management namespace.

This finite offline fixture is not a live model source or a complete Q05 verdict.
Each child constructs a new production application from frozen disk inputs. Only
the one-use authorization bytes survive in private parent RAM, as in Q02.
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
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted import HostedJournalEntry, strict_json_object
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_fault_cases import HOSTED_FAULT_WINDOWS
from quantos.infrastructure.hosted_fixture_frames import (
    deterministic_candidate_frame,
    duplicate_frame,
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
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)
from quantos.research.qlib import QlibWorkflowResearchService


def run_fault_probe(
    profile_hash: str,
    case: str,
    *,
    authority_root: Path = Path("/authority"),
    channel_root: Path = Path("/channel"),
) -> None:
    """Root overrides are management test arguments, never CLI or RPC inputs."""
    if case not in HOSTED_FAULT_WINDOWS:
        raise ValueError("unknown fixed fault window")
    window = HOSTED_FAULT_WINDOWS[case]
    authority, channel = authority_root, channel_root
    if raw_inventory(authority).files or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("fault case requires fresh retained roots")
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
    spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash)
    campaign = bundle.campaign.content_hash
    clock = [bundle.hosted_recipe.started_at]
    capabilities: tuple[tuple[int, bytes], ...] = ()
    execute_calls: list[str] = []
    workflow_calls: list[str] = []
    network_attempts: list[str] = []
    original_execute = QuantosResearchExecutionAdapter.execute
    original_workflow = QlibWorkflowResearchService.run

    def assert_offline_imports() -> None:
        if any(
            name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
            for name in sys.modules
        ):
            raise ArtifactIntegrityError("fault fixture imported forbidden transport")

    def denied_execute(self: QuantosResearchExecutionAdapter, request: Any) -> Any:
        execute_calls.append(request.execution_identity)
        if window.native_execution:
            return original_execute(self, request)
        raise ArtifactIntegrityError("admission fault fixture attempted execution")

    def denied_workflow(self: QlibWorkflowResearchService, *args: Any, **kwargs: Any) -> Any:
        workflow_calls.append("QLIB_WORKFLOW")
        if window.native_execution:
            return original_workflow(self, *args, **kwargs)
        raise ArtifactIntegrityError("admission fault fixture attempted Workflow")

    def denied_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        network_attempts.append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("offline fault fixture attempted network")

    def boot(*, crash: bool = False) -> HostedCampaignApplicationService:
        active: HostedJournalEntry | None = None
        hits = 0

        def observe(entry: object) -> None:
            nonlocal active
            if not isinstance(entry, HostedJournalEntry):
                raise ArtifactIntegrityError("fault journal observation is not typed")
            active = entry

        def hook(point: str) -> None:
            nonlocal hits
            if not crash or point != window.point:
                return
            if window.operation_kind is not None and (
                active is None or active.operation_kind != window.operation_kind
            ):
                return
            hits += 1
            if hits != window.occurrence:
                return
            assert_offline_imports()
            atomic_write_bytes(
                channel / "process-records/crash.json",
                canonical_json_bytes(
                    {
                        "schema_version": "hosted-fault-process-observation/v1",
                        "phase": "crash",
                        "case": case,
                        "pid": os.getpid(),
                        "parent_pid": os.getppid(),
                        "fresh_application_bootstrap": True,
                        "clock": clock[0].isoformat(),
                        "point": point,
                        "occurrence": hits,
                        "journal_entry": active.model_dump(mode="json") if active else None,
                        "inventory": raw_inventory(authority).model_dump(mode="json"),
                        "execute_calls": execute_calls,
                        "workflow_calls": workflow_calls,
                        "network_attempts": network_attempts,
                        "python_flags": management_python_flags(),
                        "python_executable": sys.executable,
                    }
                ),
            )
            os._exit(73)

        restore_restart_capabilities(capabilities)
        application = bootstrap_hosted_service(
            profile_hash,
            protocol_clock=lambda: clock[0],
            authority_root=authority,
            channel_root=channel,
            verify_journal_entry=observe,
            protocol_fault_hook=hook if window.operation_kind else None,
            business_fault_hook=hook if window.operation_kind is None else None,
        ).application
        if not isinstance(application, HostedCampaignApplicationService):
            raise ArtifactIntegrityError("fault application factory differs")
        return application

    def snapshot(phase: str) -> None:
        snapshot_management_authority(phase, authority, channel)
        atomic_write_bytes(
            channel / "phase-inventories" / f"{phase}.json",
            raw_inventory(authority).canonical_bytes(),
        )

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", denied_execute),
        patch.object(QlibWorkflowResearchService, "run", denied_workflow),
        patch.object(socket.socket, "connect", denied_network),
        patch.object(socket.socket, "connect_ex", denied_network),
        patch.object(socket, "create_connection", denied_network),
    ):
        hydrate_service_capabilities(profile_hash)
        capabilities = capture_restart_capabilities(configuration)
        request = None
        response = None
        if window.action not in ("register", "issue", "start"):
            application = boot()
            application.start(spec.content_hash)
            request = application.pending(campaign)
            if request is None:
                raise ArtifactIntegrityError("fault fixture has no pending request")
            response = (
                deterministic_candidate_frame(request)
                if window.native_execution
                else duplicate_frame(request, "accepted")
            )
            if window.action in ("resume", "execute_campaign"):
                application.submit(request.content_hash, response, "fault.fixture")
            elif window.action == "expire":
                clock[0] = request.expires_at
        snapshot("before")
        exits: list[dict[str, object]] = []

        def child(phase: str, *, crash: bool = False) -> dict[str, object] | None:
            pid = os.fork()
            if pid == 0:
                try:
                    before = raw_inventory(authority)
                    application = boot(crash=crash)
                    if window.action in ("register", "issue", "start"):
                        result = application.start(spec.content_hash)
                    elif window.action in ("submit", "reject") and request is not None:
                        result = application.submit(
                            request.content_hash,
                            response if window.action == "submit" and response else b"{}",
                            "fault.fixture",
                        )
                    elif window.action == "cancel" and request is not None:
                        result = application.cancel(request.content_hash, "fault.fixture")
                    elif window.action == "expire":
                        # Transport termination must not finalize an incomplete DQ campaign.
                        result = application.protocol.resume(campaign)
                    elif window.action in ("resume", "execute_campaign"):
                        result = application.resume(campaign)
                        if window.native_execution:
                            # Finish the frozen family through the native application,
                            # so the read-only verifier can use the real final report.
                            for _ in range(spec.hosted_budget.max_requests):
                                if result.report_hash is not None:
                                    break
                                pending = application.pending(campaign)
                                if pending is None:
                                    raise ArtifactIntegrityError(
                                        "execution fault lost pending step"
                                    )
                                state = application.protocol.store.snapshot(campaign, recover=False)
                                charged = (
                                    application.verify_research_facts(state)
                                    .budgets[-1]
                                    .candidate_hashes
                                )
                                candidate_hash = next(
                                    (
                                        option.content_hash
                                        for option in pending.business_request.candidate_options
                                        if option.content_hash not in charged
                                    ),
                                    None,
                                )
                                if candidate_hash is None:
                                    raise ArtifactIntegrityError(
                                        "execution fault has no unattempted frozen candidate"
                                    )
                                application.submit(
                                    pending.content_hash,
                                    deterministic_candidate_frame(
                                        pending, candidate_hash=candidate_hash
                                    ),
                                    "fault.fixture",
                                )
                                result = application.resume(campaign)
                            if result.report_hash is None:
                                raise ArtifactIntegrityError("execution fault lacks native report")
                    else:
                        raise ArtifactIntegrityError("fault action differs from finite registry")
                    if crash:
                        raise ArtifactIntegrityError("fixed physical exit hook was not reached")
                    assert_offline_imports()
                    atomic_write_bytes(
                        channel / "process-records" / f"{phase}.json",
                        canonical_json_bytes(
                            {
                                "schema_version": "hosted-fault-process-observation/v1",
                                "phase": phase,
                                "case": case,
                                "pid": os.getpid(),
                                "parent_pid": os.getppid(),
                                "fresh_application_bootstrap": True,
                                "clock": clock[0].isoformat(),
                                "before_inventory": before.model_dump(mode="json"),
                                "after_inventory": raw_inventory(authority).model_dump(mode="json"),
                                "result_hash": result.content_hash,
                                "result_json": result.model_dump(mode="json"),
                                "execute_calls": execute_calls,
                                "workflow_calls": workflow_calls,
                                "network_attempts": network_attempts,
                                "python_flags": management_python_flags(),
                                "python_executable": sys.executable,
                            }
                        ),
                    )
                except Exception as error:
                    atomic_write_bytes(
                        channel / "process-records" / f"{phase}-failure.json",
                        canonical_json_bytes(
                            {"pid": os.getpid(), "error_type": type(error).__name__}
                        ),
                    )
                    os._exit(1)
                os._exit(0)
            deadline = time.monotonic() + (3600 if window.native_execution else 120)
            while True:
                observed, status = os.waitpid(pid, os.WNOHANG)
                if observed:
                    break
                if time.monotonic() >= deadline:
                    os.kill(pid, signal.SIGKILL)
                    observed, status = os.waitpid(pid, 0)
                    exits.append({"phase": phase, "pid": observed, "exit_code": -signal.SIGKILL})
                    raise ArtifactIntegrityError("fault child timeout; original root retained")
                time.sleep(0.05)
            code = os.waitstatus_to_exitcode(status)
            exits.append({"phase": phase, "pid": observed, "exit_code": code})
            atomic_write_bytes(
                channel / "process-records" / f"{phase}-exit.json",
                canonical_json_bytes(exits[-1]),
            )
            if observed != pid or code != (73 if crash else 0):
                raise ArtifactIntegrityError("fault child exit differs; original root retained")
            if crash:
                return None
            return strict_json_object(
                read_relative(channel, f"process-records/{phase}.json"), max_bytes=16_777_216
            )

        child("crash", crash=True)
        snapshot("crashed")
        first = child("recovery-1")
        snapshot("recovered")
        recovered = raw_inventory(authority)
        second = child("recovery-2")
        verify_raw_inventory(authority, recovered)
        if first is None or second is None or first["result_hash"] != second["result_hash"]:
            raise ArtifactIntegrityError("second fresh recovery changed its result")
        snapshot("after")
        assert_offline_imports()
        atomic_write_bytes(
            channel / "negative-observation.json",
            canonical_json_bytes(
                {
                    "schema_version": "hosted-fault-observation/v1",
                    "case_family": "Q05",
                    "case": case,
                    "fixture_kind": (
                        "PHYSICAL_EXIT_EXECUTION_FIXTURE"
                        if window.native_execution
                        else "PHYSICAL_EXIT_ADMISSION_FIXTURE"
                    ),
                    "deployment_profile_hash": profile_hash,
                    "campaign_hash": campaign,
                    "request_hash": request.content_hash if request else None,
                    "process_exits": exits,
                    "before_inventory": raw_inventory(
                        channel / "snapshots/before/authority"
                    ).model_dump(mode="json"),
                    "after_inventory": recovered.model_dump(mode="json"),
                    "python_flags": management_python_flags(),
                    "python_executable": sys.executable,
                    "execute_calls": execute_calls,
                    "workflow_calls": workflow_calls,
                    "network_attempts": network_attempts,
                    "qualification_eligibility": "NOT_QUALIFIED",
                    "limitation": "SYNTHETIC_OFFLINE_FAULT_FIXTURE_NOT_LIVE_SOURCE",
                }
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", required=True, choices=tuple(HOSTED_FAULT_WINDOWS))
    args = parser.parse_args()
    run_fault_probe(args.profile_hash, args.case)


if __name__ == "__main__":
    main()
