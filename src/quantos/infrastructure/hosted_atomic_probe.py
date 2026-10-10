"""Fixed offline native registration fsync workers; no qualification grant.

Unsafe physical intermediates remain original. Their copies and inode/link facts
are explicit forensic evidence, never ordinary canonical-authority snapshots.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_atomic_forensics import (
    atomic_forensic_inventory,
    native_registration_publication,
)
from quantos.infrastructure.hosted_atomic_snapshot import (
    forensic_byte_view,
    snapshot_atomic_authority,
)
from quantos.infrastructure.hosted_fault_cases import ATOMIC_FAULT_WINDOWS
from quantos.infrastructure.hosted_fault_probe import failure_locations
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
    read_relative,
)
from quantos.research.qlib import QlibWorkflowResearchService


def run_atomic_probe(
    profile_hash: str,
    case: str,
    *,
    authority_root: Path = Path("/authority"),
    channel_root: Path = Path("/channel"),
) -> None:
    """Overrides are component-management arguments, never host CLI/RPC inputs."""
    if case not in ATOMIC_FAULT_WINDOWS:
        raise ValueError("unknown fixed atomic window")
    domain, window = ATOMIC_FAULT_WINDOWS[case]
    authority, channel = authority_root, channel_root
    if raw_inventory(authority).files or directory_inventory(authority) or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("atomic window requires fresh retained roots")
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
    target_path, expected_bytes = native_registration_publication(spec, domain)
    before = raw_inventory(authority)
    snapshot_management_authority("before", authority, channel)
    atomic_write_bytes(channel / "phase-inventories/before.json", before.canonical_bytes())
    counters: dict[str, list[str]] = {
        name: [] for name in ("execute_calls", "workflow_calls", "network_attempts")
    }

    def denied_execute(*_args: object, **_kwargs: object) -> None:
        counters["execute_calls"].append("EXECUTION")
        raise ArtifactIntegrityError("atomic fixture attempted execution")

    def denied_workflow(*_args: object, **_kwargs: object) -> None:
        counters["workflow_calls"].append("QLIB_WORKFLOW")
        raise ArtifactIntegrityError("atomic fixture attempted Workflow")

    def denied_network(*_args: object, **_kwargs: object) -> None:
        counters["network_attempts"].append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("atomic fixture attempted network")

    def require_offline() -> None:
        if any(counters.values()) or any(
            name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
            for name in sys.modules
        ):
            raise ArtifactIntegrityError("atomic fixture crossed its offline boundary")

    def inventory():
        return atomic_forensic_inventory(
            authority, target_path=target_path, expected_bytes=expected_bytes, window=window
        )

    def snapshot(phase: str):
        return snapshot_atomic_authority(
            phase,
            authority,
            channel,
            target_path=target_path,
            expected_bytes=expected_bytes,
            window=window,
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
        exits: list[dict[str, object]] = []
        for phase in ("crash", "recovery-1", "recovery-2"):
            pid = os.fork()
            if pid == 0:
                try:
                    restore_restart_capabilities(capabilities)
                    if phase == "crash":

                        def stop(point: str) -> None:
                            if point != f"{domain}_{window}":
                                return
                            require_offline()
                            facts = snapshot("crashed")
                            record = {
                                "schema_version": "hosted-atomic-fault-process-observation/v1",
                                "case": case,
                                "phase": "crash",
                                "pid": os.getpid(),
                                "parent_pid": os.getppid(),
                                "fresh_application_bootstrap": True,
                                "point": point,
                                "domain": domain,
                                "window": window,
                                "clock": spec.started_at.isoformat(),
                                "forensic_inventory": facts.model_dump(mode="json"),
                                "python_flags": management_python_flags(),
                                "python_executable": sys.executable,
                                **counters,
                            }
                            atomic_write_bytes(
                                channel / "process-records/crash.json", canonical_json_bytes(record)
                            )
                            os._exit(73)

                        application = bootstrap_hosted_service(
                            profile_hash,
                            protocol_clock=lambda: spec.started_at,
                            authority_root=authority,
                            channel_root=channel,
                            protocol_fault_hook=stop,
                        ).application
                        if not isinstance(application, HostedCampaignApplicationService):
                            raise ArtifactIntegrityError("atomic application factory differs")
                        application.start(spec.content_hash)
                        raise ArtifactIntegrityError("atomic physical hook was not reached")
                    initial = inventory()
                    rejected = window in ("file_fsynced", "file_linked")
                    try:
                        application = bootstrap_hosted_service(
                            profile_hash,
                            protocol_clock=lambda: spec.started_at,
                            authority_root=authority,
                            channel_root=channel,
                        ).application
                        if not isinstance(application, HostedCampaignApplicationService):
                            raise ArtifactIntegrityError("atomic application factory differs")
                        result = application.start(spec.content_hash)
                    except ArtifactIntegrityError as error:
                        if not rejected:
                            raise
                        result_json = {
                            "outcome": "REJECTED_ATOMIC_INTERMEDIATE",
                            "error_type": type(error).__name__,
                        }
                    else:
                        if rejected:
                            raise ArtifactIntegrityError("unsafe atomic authority was repaired")
                        result_json = result.model_dump(mode="json")
                    final = inventory()
                    if (rejected or phase == "recovery-2") and final != initial:
                        raise ArtifactIntegrityError(
                            "atomic recovery changed retained physical facts"
                        )
                    require_offline()
                    record = {
                        "schema_version": "hosted-atomic-fault-process-observation/v1",
                        "case": case,
                        "phase": phase,
                        "pid": os.getpid(),
                        "parent_pid": os.getppid(),
                        "fresh_application_bootstrap": True,
                        "clock": spec.started_at.isoformat(),
                        "before_forensic_inventory": initial.model_dump(mode="json"),
                        "after_forensic_inventory": final.model_dump(mode="json"),
                        "result_json": result_json,
                        "result_hash": sha256_bytes(canonical_json_bytes(result_json)),
                        "python_flags": management_python_flags(),
                        "python_executable": sys.executable,
                        **counters,
                    }
                    atomic_write_bytes(
                        channel / "process-records" / f"{phase}.json", canonical_json_bytes(record)
                    )
                    os._exit(74 if rejected else 0)
                except Exception as error:
                    atomic_write_bytes(
                        channel / "process-records" / f"{phase}-failure.json",
                        canonical_json_bytes(
                            {
                                "pid": os.getpid(),
                                "error_type": type(error).__name__,
                                "failure_locations": failure_locations(error),
                            }
                        ),
                    )
                    os._exit(1)
            deadline = time.monotonic() + 300
            while True:
                observed, status = os.waitpid(pid, os.WNOHANG)
                if observed:
                    break
                if time.monotonic() >= deadline:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                    raise ArtifactIntegrityError(
                        "atomic child deadline exceeded; originals retained"
                    )
                time.sleep(0.02)
            exit_code = os.waitstatus_to_exitcode(status)
            fact: dict[str, object] = {"phase": phase, "pid": pid, "exit_code": exit_code}
            exits.append(fact)
            atomic_write_bytes(
                channel / "process-records" / f"{phase}-exit.json", canonical_json_bytes(fact)
            )
            expected_exit = (
                73 if phase == "crash" else 74 if window in ("file_fsynced", "file_linked") else 0
            )
            if exit_code != expected_exit:
                raise ArtifactIntegrityError("atomic child failed; originals retained")
            if phase == "crash":
                recorded = strict_json_object(
                    read_relative(channel, "process-records/crash.json"), max_bytes=16_777_216
                )
                if recorded["forensic_inventory"] != inventory().model_dump(mode="json"):
                    raise ArtifactIntegrityError("atomic physical exit inventory changed")
            else:
                snapshot("recovered" if phase == "recovery-1" else "after")
        final = inventory()
        require_offline()
        observation = {
            "schema_version": "hosted-negative-observation/v1",
            "case_family": "Q05",
            "case": case,
            "fixture_kind": "PHYSICAL_EXIT_ATOMIC_FIXTURE",
            "deployment_profile_hash": profile_hash,
            "campaign_hash": spec.campaign_hash,
            "point": f"{domain}_{window}",
            "domain": domain,
            "window": window,
            "before_inventory": before.model_dump(mode="json"),
            "after_inventory": forensic_byte_view(final).model_dump(mode="json"),
            "authority_after_forensic_inventory": final.model_dump(mode="json"),
            "process_exits": exits,
            "python_flags": management_python_flags(),
            "python_executable": sys.executable,
            "qualification_eligibility": "NOT_QUALIFIED",
            **counters,
        }
        atomic_write_bytes(channel / "negative-observation.json", canonical_json_bytes(observation))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=tuple(ATOMIC_FAULT_WINDOWS), required=True)
    args = parser.parse_args()
    run_atomic_probe(args.profile_hash, args.case)


if __name__ == "__main__":
    main()
