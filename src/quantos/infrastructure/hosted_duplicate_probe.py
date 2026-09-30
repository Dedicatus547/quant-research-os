"""Fixed management-only two-process submission and native resume fixtures.

The accepted fixture intentionally has native schema-invalid business admission.
It proves one recorded trial, not successful execution or live model provenance.
"""

from __future__ import annotations

import argparse
import os
import select
import socket
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedSubmissionReceipt, strict_json_object
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_fixture_frames import DUPLICATE_SUBMISSION_CASES, duplicate_frame
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


def _snapshot(phase: str, authority: Path, channel: Path) -> None:
    inventory = raw_inventory(authority)
    target = channel / "snapshots" / phase / "authority"
    for item in inventory.files:
        atomic_write_bytes(target / item.logical_path, read_relative(authority, item.logical_path))
    verify_raw_inventory(target, inventory)


def _flags() -> dict[str, object]:
    return {
        name: getattr(sys.flags, name)
        for name in (
            "isolated",
            "ignore_environment",
            "no_user_site",
            "safe_path",
            "hash_randomization",
        )
    }


def _capture_restart_capabilities(
    configuration: HostedServiceConfiguration,
) -> tuple[tuple[int, bytes], ...]:
    """Capture one-use service descriptors into RAM, never into evidence or logs."""
    values: list[tuple[int, bytes]] = []
    for index, principal in enumerate(configuration.principals):
        if principal.capability_fd != 100 + index:
            raise ArtifactIntegrityError("fixed private service descriptor differs")
        value = os.pread(principal.capability_fd, 33, 0)
        if len(value) != 32:
            raise ArtifactIntegrityError("fixed private service capability length differs")
        values.append((principal.capability_fd, value))
    return tuple(values)


def _restore_restart_capabilities(values: tuple[tuple[int, bytes], ...]) -> None:
    """Recreate only the configured private slots before a fresh fixed bootstrap."""
    for target, value in values:
        descriptor = private_memory_fd("duplicate-service-capability")
        try:
            os.write(descriptor, value)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if descriptor != target:
                os.dup2(descriptor, target, inheritable=False)
        finally:
            if descriptor != target:
                os.close(descriptor)


def run_duplicate_probe(
    profile_hash: str,
    case: str,
    *,
    authority_root: Path = Path("/authority"),
    channel_root: Path = Path("/channel"),
) -> None:
    """Root overrides support management tests; the executable exposes none."""
    if case not in DUPLICATE_SUBMISSION_CASES:
        raise ValueError("unknown fixed duplicate case")
    authority, channel = authority_root, channel_root
    if raw_inventory(authority).files or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("duplicate case requires fresh roots")
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
    campaign = bundle.campaign.content_hash
    if bundle.hosted_recipe.hosted_budget.max_submissions_per_request != 2:
        raise ArtifactIntegrityError(
            "duplicate qualification fixture requires frozen per-request cap 2"
        )
    clock = [bundle.hosted_recipe.started_at]
    execute_calls: list[str] = []
    workflow_calls: list[str] = []
    network_attempts: list[str] = []
    restart_capabilities: tuple[tuple[int, bytes], ...] = ()

    def denied_execute(self: QuantosResearchExecutionAdapter, request: Any) -> Any:
        execute_calls.append(request.execution_identity)
        raise ArtifactIntegrityError("schema-invalid fixture attempted execution")

    def denied_workflow(self: QlibWorkflowResearchService, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        workflow_calls.append("QLIB_WORKFLOW")
        raise ArtifactIntegrityError("schema-invalid fixture attempted Workflow")

    def denied_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        network_attempts.append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("duplicate fixture attempted network")

    def boot() -> HostedCampaignApplicationService:
        _restore_restart_capabilities(restart_capabilities)
        application = bootstrap_hosted_service(
            profile_hash,
            protocol_clock=lambda: clock[0],
            authority_root=authority,
            channel_root=channel,
        ).application
        if not isinstance(application, HostedCampaignApplicationService):
            raise ArtifactIntegrityError("duplicate application differs")
        return application

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", denied_execute),
        patch.object(QlibWorkflowResearchService, "run", denied_workflow),
        patch.object(socket.socket, "connect", denied_network),
        patch.object(socket.socket, "connect_ex", denied_network),
        patch.object(socket, "create_connection", denied_network),
    ):
        hydrate_service_capabilities(profile_hash)
        restart_capabilities = _capture_restart_capabilities(configuration)
        application = boot()
        application.start(
            derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash).content_hash
        )
        request = application.pending(campaign)
        if request is None:
            raise ArtifactIntegrityError("duplicate case has no request")
        submitted = duplicate_frame(request, case)
        _snapshot("before", authority, channel)
        lock_path = authority / "protocol/campaigns" / campaign

        def spawn(
            phase: str,
            action: Literal["submit", "resume"],
            *,
            barrier: tuple[int, int] | None = None,
        ) -> int:
            pid = os.fork()
            if pid:
                return pid
            try:
                before = raw_inventory(authority)
                inode = lock_path.stat()
                if barrier is not None:
                    ready, release = barrier
                    os.write(ready, b"r")
                    if not select.select([release], [], [], 30)[0] or os.read(release, 1) != b"g":
                        raise ArtifactIntegrityError("duplicate barrier release differs")
                child_application = boot() if action == "resume" else application
                result = (
                    child_application.resume(campaign)
                    if action == "resume"
                    else child_application.submit(
                        request.content_hash, submitted, "duplicate.fixture"
                    )
                )
                after_inode = lock_path.stat()
                fact = {
                    "schema_version": "hosted-duplicate-process-observation/v1",
                    "phase": phase,
                    "action": action,
                    "pid": os.getpid(),
                    "parent_pid": os.getppid(),
                    "barrier": barrier is not None,
                    "fresh_application_bootstrap": action == "resume",
                    "lock_before": [inode.st_dev, inode.st_ino],
                    "lock_after": [after_inode.st_dev, after_inode.st_ino],
                    "clock": clock[0].isoformat(),
                    "request_hash": request.content_hash,
                    "response_hash": sha256_bytes(submitted),
                    "result_hash": result.content_hash,
                    "result_json": result.model_dump(mode="json"),
                    "before_inventory": before.model_dump(mode="json"),
                    "after_inventory": raw_inventory(authority).model_dump(mode="json"),
                    "execute_calls": execute_calls,
                    "workflow_calls": workflow_calls,
                    "network_attempts": network_attempts,
                    "python_executable": sys.executable,
                    "python_flags": _flags(),
                    "qualification_eligibility": "NOT_QUALIFIED",
                }
                atomic_write_bytes(
                    channel / "process-records" / f"{phase}.json", canonical_json_bytes(fact)
                )
            except Exception as error:
                atomic_write_bytes(
                    channel / "process-records" / f"{phase}-failure.json",
                    canonical_json_bytes({"error_type": type(error).__name__, "pid": os.getpid()}),
                )
                os._exit(1)
            os._exit(0)

        exits: list[dict[str, object]] = []

        def join(pid: int, phase: str) -> dict[str, object]:
            observed_pid, status = os.waitpid(pid, 0)
            code = os.waitstatus_to_exitcode(status)
            exits.append({"pid": observed_pid, "phase": phase, "exit_code": code})
            if observed_pid != pid or code != 0:
                raise ArtifactIntegrityError("duplicate child failed; original evidence retained")
            return strict_json_object(
                read_relative(channel, f"process-records/{phase}.json"), max_bytes=16_777_216
            )

        ready_read, ready_write = os.pipe()
        release_read, release_write = os.pipe()
        try:
            first = spawn("submit-1", "submit", barrier=(ready_write, release_read))
            second = spawn("submit-2", "submit", barrier=(ready_write, release_read))
            # Read each byte independently: pipe reads may return a short buffer.
            for _ in range(2):
                if not select.select([ready_read], [], [], 30)[0] or os.read(ready_read, 1) != b"r":
                    raise ArtifactIntegrityError("duplicate barrier readiness differs")
            os.write(release_write, b"gg")
            submitted_records = (join(first, "submit-1"), join(second, "submit-2"))
        finally:
            for descriptor in (ready_read, ready_write, release_read, release_write):
                os.close(descriptor)
        receipt = HostedSubmissionReceipt.model_validate(submitted_records[0]["result_json"])
        if receipt != HostedSubmissionReceipt.model_validate(submitted_records[1]["result_json"]):
            raise ArtifactIntegrityError("concurrent submissions did not reuse receipt")
        if receipt.outcome != ("ACCEPTED" if case == "accepted" else "REJECTED"):
            raise ArtifactIntegrityError("duplicate primary outcome differs")
        repeat_before = raw_inventory(authority)
        repeated = join(spawn("repeat", "submit"), "repeat")
        if repeated["result_hash"] != receipt.content_hash:
            raise ArtifactIntegrityError("duplicate receipt differs")
        verify_raw_inventory(authority, repeat_before)
        _snapshot("after-submit", authority, channel)
        join(spawn("resume-1", "resume"), "resume-1")
        first_business = raw_inventory(authority)
        _snapshot("after-first-resume", authority, channel)
        join(spawn("resume-2", "resume"), "resume-2")
        verify_raw_inventory(authority, first_business)
        cancellation = None
        pending = application.pending(campaign)
        if case == "accepted" and pending is not None and pending != request:
            cancellation = application.cancel(pending.content_hash, "duplicate.fixture")
        _snapshot("after-business", authority, channel)
        _snapshot("before-cap", authority, channel)
        # Reach the frozen per-request submission cap with unique conflict/reject
        # bytes. No resume occurs after this transport-only budget exercise.
        cap_receipts: list[str] = []
        for index in range(1, bundle.hosted_recipe.hosted_budget.max_submissions_per_request):
            raw = canonical_json_bytes({"duplicate_cap_fixture": index})
            cap_receipts.append(
                application.submit(request.content_hash, raw, "duplicate.fixture").content_hash
            )
        cap_inventory = raw_inventory(authority)
        exhausted = application.submit(
            request.content_hash, b'{"duplicate_cap_unseen":true}', "duplicate.fixture"
        )
        if exhausted.outcome != "EXHAUSTED":
            raise ArtifactIntegrityError("duplicate fixture did not reach frozen cap")
        verify_raw_inventory(authority, cap_inventory)
        clock[0] = request.expires_at + timedelta(seconds=1)
        late = join(spawn("late-repeat", "submit"), "late-repeat")
        if late["result_hash"] != receipt.content_hash:
            raise ArtifactIntegrityError("seen bytes lost receipt after cap/TTL")
        verify_raw_inventory(authority, cap_inventory)
        if any(
            name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
            for name in sys.modules
        ):
            raise ArtifactIntegrityError("duplicate fixture imported forbidden transport")
        observation = {
            "schema_version": "hosted-negative-observation/v1",
            "case_family": "Q02",
            "case": case,
            "deployment_profile_hash": profile_hash,
            "campaign_hash": campaign,
            "request_hash": request.content_hash,
            "receipt_hash": receipt.content_hash,
            "repeat_receipt_hash": late["result_hash"],
            "response_json": None,
            "response_observed_hash": sha256_bytes(submitted),
            "response_observed_bytes": len(submitted),
            "primary_clock": receipt.recorded_at.isoformat(),
            "repeat_clock": clock[0].isoformat(),
            "seen_receipt_hash": None,
            "cancellation_receipt_hash": None,
            "business_report_hash": None,
            "business_cancellation_hash": cancellation.content_hash if cancellation else None,
            "cap_receipt_hashes": cap_receipts,
            "exhaustion_receipt_hash": exhausted.content_hash,
            "before_inventory": raw_inventory(channel / "snapshots/before/authority").model_dump(
                mode="json"
            ),
            "after_inventory": cap_inventory.model_dump(mode="json"),
            "process_exits": exits,
            "execute_calls": execute_calls,
            "workflow_calls": workflow_calls,
            "network_attempts": network_attempts,
            "fixture_kind": "DUPLICATE_SUBMISSION_FIXTURE",
            "python_executable": sys.executable,
            "python_flags": _flags(),
            "qualification_eligibility": "NOT_QUALIFIED",
        }
        atomic_write_bytes(channel / "negative-observation.json", canonical_json_bytes(observation))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=DUPLICATE_SUBMISSION_CASES, required=True)
    args = parser.parse_args()
    try:
        run_duplicate_probe(args.profile_hash, args.case)
    except Exception as error:
        print(
            canonical_json_bytes(
                {"duplicate": "FAILED", "error_type": type(error).__name__}
            ).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
