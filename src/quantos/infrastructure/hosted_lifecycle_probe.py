"""Actual directory-flock cancellation races and TTL/restart management fixtures.

The barrier observes a winner inside its native durable commit and a loser
entering the actual flock syscall on that same inode. No thread lock substitutes
for the protocol lock. Synthetic proposals never establish live provenance.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import socket
import sys
import time
from collections.abc import Callable
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, opened_directory
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_fault_probe import failure_locations
from quantos.infrastructure.hosted_fixture_frames import business_rejection_frame
from quantos.infrastructure.hosted_lifecycle_cases import HOSTED_LIFECYCLE_CASES
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
    verify_raw_inventory,
)
from quantos.research.qlib import QlibWorkflowResearchService


def _receive(descriptor: int) -> None:
    if not select.select([descriptor], [], [], 30)[0] or os.read(descriptor, 1) != b"r":
        raise ArtifactIntegrityError("lifecycle barrier deadline or byte differs")


def run_lifecycle_probe(
    profile_hash: str,
    case: str,
    *,
    authority_root: Path = Path("/authority"),
    channel_root: Path = Path("/channel"),
) -> None:
    """Root overrides are component-management arguments, never RPC arguments."""
    if case not in HOSTED_LIFECYCLE_CASES:
        raise ValueError("unknown fixed lifecycle case")
    authority, channel = authority_root, channel_root
    if raw_inventory(authority).files or directory_inventory(authority) or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("lifecycle case requires fresh retained roots")
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
    clock = [spec.started_at]
    counters: dict[str, list[str]] = {
        key: [] for key in ("execute_calls", "workflow_calls", "network_attempts")
    }

    def deny(key: str) -> Callable[..., None]:
        def denied(*_args: object, **_kwargs: object) -> None:
            counters[key].append(key)
            raise ArtifactIntegrityError("lifecycle fixture crossed offline execution boundary")

        return denied

    def offline() -> None:
        if any(counters.values()) or any(
            name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
            for name in sys.modules
        ):
            raise ArtifactIntegrityError("lifecycle fixture crossed offline execution boundary")

    def snapshot(phase: str) -> None:
        snapshot_management_authority(phase, authority, channel)
        atomic_write_bytes(
            channel / f"phase-inventories/{phase}.json", raw_inventory(authority).canonical_bytes()
        )

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", deny("execute_calls")),
        patch.object(QlibWorkflowResearchService, "run", deny("workflow_calls")),
        patch.object(socket.socket, "connect", deny("network_attempts")),
        patch.object(socket.socket, "connect_ex", deny("network_attempts")),
        patch.object(socket, "create_connection", deny("network_attempts")),
    ):
        hydrate_service_capabilities(profile_hash)
        capabilities = capture_restart_capabilities(configuration)

        def boot() -> HostedCampaignApplicationService:
            restore_restart_capabilities(capabilities)
            application = bootstrap_hosted_service(
                profile_hash,
                protocol_clock=lambda: clock[0],
                authority_root=authority,
                channel_root=channel,
            ).application
            if not isinstance(application, HostedCampaignApplicationService):
                raise ArtifactIntegrityError("lifecycle native application differs")
            return application

        application = boot()
        application.start(spec.content_hash)
        request = application.pending(spec.campaign_hash)
        if request is None:
            raise ArtifactIntegrityError("lifecycle request absent")
        response = business_rejection_frame(request, "known_schema_invalid")
        lock_path = authority / "protocol/campaigns" / spec.campaign_hash
        identity = lock_path.stat()
        lock_identity = (identity.st_dev, identity.st_ino)
        snapshot("before")
        exits: list[dict[str, object]] = []
        children: set[int] = set()

        def spawn(phase: str, action: Callable[[], Any], *, fresh: bool = False) -> int:
            pid = os.fork()
            if pid:
                children.add(pid)
                return pid
            try:
                result = action()
                offline()
                data = result.model_dump(mode="json")
                atomic_write_bytes(
                    channel / f"process-records/{phase}.json",
                    canonical_json_bytes(
                        {
                            "schema_version": "hosted-lifecycle-process-observation/v1",
                            "phase": phase,
                            "pid": os.getpid(),
                            "parent_pid": os.getppid(),
                            "clock": clock[0].isoformat(),
                            "fresh_application_bootstrap": fresh,
                            "lock_identity": lock_identity,
                            "result_json": data,
                            "result_hash": sha256_bytes(canonical_json_bytes(data)),
                            "python_flags": management_python_flags(),
                            "python_executable": sys.executable,
                            **counters,
                        }
                    ),
                )
            except Exception as error:
                atomic_write_bytes(
                    channel / f"process-records/{phase}-failure.json",
                    canonical_json_bytes(
                        {
                            "pid": os.getpid(),
                            "error_type": type(error).__name__,
                            "failure_locations": failure_locations(error),
                        }
                    ),
                )
                os._exit(1)
            os._exit(0)

        def join(pid: int, phase: str) -> dict[str, object]:
            deadline = time.monotonic() + 300
            while True:
                observed, status = os.waitpid(pid, os.WNOHANG)
                if observed:
                    children.discard(pid)
                    break
                if time.monotonic() >= deadline:
                    raise ArtifactIntegrityError("lifecycle child deadline exceeded")
                time.sleep(0.02)
            fact: dict[str, object] = {
                "phase": phase,
                "pid": observed,
                "exit_code": os.waitstatus_to_exitcode(status),
            }
            exits.append(fact)
            atomic_write_bytes(
                channel / f"process-records/{phase}-exit.json", canonical_json_bytes(fact)
            )
            if observed != pid or fact["exit_code"] != 0:
                raise ArtifactIntegrityError("lifecycle child failed; originals retained")
            return strict_json_object(
                read_relative(channel, f"process-records/{phase}.json"), max_bytes=16_777_216
            )

        def submit() -> Any:
            return application.submit(request.content_hash, response, "lifecycle.fixture")

        def cancel() -> Any:
            return application.cancel(request.content_hash, "lifecycle.fixture")

        barrier_fact: dict[str, object] | None = None
        try:
            if case in ("cancel_before_submit", "submit_before_cancel"):
                entered_read, entered_write = os.pipe()
                release_read, release_write = os.pipe()
                blocked_read, blocked_write = os.pipe()
                try:
                    winner_action, loser_action = (
                        (cancel, submit) if case == "cancel_before_submit" else (submit, cancel)
                    )

                    def winner() -> Any:
                        def hold(point: str) -> None:
                            if point == "intent_published":
                                os.write(entered_write, b"r")
                                _receive(release_read)

                        with patch.object(application.protocol.store, "_fault_hook", hold):
                            return winner_action()

                    winner_pid = spawn("winner", winner)
                    _receive(entered_read)

                    def loser() -> Any:
                        notified = False

                        def observed_flock(fd: int, operation: int) -> None:
                            nonlocal notified
                            info = os.fstat(fd)
                            if (
                                not notified
                                and operation == LOCK_EX
                                and (info.st_dev, info.st_ino) == lock_identity
                            ):
                                notified = True
                                os.write(blocked_write, b"r")
                            flock(fd, operation)

                        with patch("quantos.infrastructure.hosted_store.flock", observed_flock):
                            return loser_action()

                    loser_pid = spawn("loser", loser)
                    _receive(blocked_read)
                    with opened_directory(lock_path) as fd:
                        try:
                            flock(fd, LOCK_EX | LOCK_NB)
                        except BlockingIOError:
                            pass
                        else:
                            flock(fd, LOCK_UN)
                            raise ArtifactIntegrityError("winner did not hold native campaign lock")
                        info = os.fstat(fd)
                        if (info.st_dev, info.st_ino) != lock_identity:
                            raise ArtifactIntegrityError("lifecycle inspector lock inode changed")
                    if os.waitpid(loser_pid, os.WNOHANG) != (0, 0):
                        children.discard(loser_pid)
                        raise ArtifactIntegrityError("loser exited before winner release")
                    barrier_fact = {
                        "winner_pid": winner_pid,
                        "loser_pid": loser_pid,
                        "lock_identity": lock_identity,
                        "winner_native_intent_published": True,
                        "loser_entered_native_flock": True,
                        "inspector_nonblocking_flock_rejected": True,
                        "loser_waitpid_before_release": [0, 0],
                    }
                    atomic_write_bytes(
                        channel / "race-barrier.json", canonical_json_bytes(barrier_fact)
                    )
                    os.write(release_write, b"r")
                    join(winner_pid, "winner")
                    join(loser_pid, "loser")
                finally:
                    for fd in (
                        entered_read,
                        entered_write,
                        release_read,
                        release_write,
                        blocked_read,
                        blocked_write,
                    ):
                        os.close(fd)
            else:
                if case == "ttl_seen_response":
                    original = join(
                        spawn(
                            "seen",
                            lambda: application.submit(
                                request.content_hash, b"{}", "lifecycle.fixture"
                            ),
                        ),
                        "seen",
                    )
                    clock[0] = request.expires_at
                    unchanged = raw_inventory(authority)
                    repeat = join(
                        spawn(
                            "seen-repeat",
                            lambda: boot().submit(request.content_hash, b"{}", "lifecycle.fixture"),
                            fresh=True,
                        ),
                        "seen-repeat",
                    )
                    if original["result_hash"] != repeat["result_hash"]:
                        raise ArtifactIntegrityError("seen response changed at TTL boundary")
                    verify_raw_inventory(authority, unchanged)
                clock[0] = request.expires_at
                join(
                    spawn(
                        "late",
                        lambda: boot().submit(request.content_hash, response, "lifecycle.fixture"),
                        fresh=True,
                    ),
                    "late",
                )
            # Previously seen bytes retain their exact original receipt even at
            # the TTL boundary or after cancellation. A fresh bootstrap cannot
            # charge again or change the acceptance/rejection.
            clock[0] = request.expires_at
            repeat_before = raw_inventory(authority)
            join(
                spawn(
                    "response-repeat",
                    lambda: boot().submit(request.content_hash, response, "lifecycle.fixture"),
                    fresh=True,
                ),
                "response-repeat",
            )
            verify_raw_inventory(authority, repeat_before)
            snapshot("after-actions")

            def finish() -> Any:
                fresh = boot()
                status = fresh.resume(spec.campaign_hash)
                pending = fresh.pending(spec.campaign_hash)
                if pending is not None:
                    fresh.cancel(pending.content_hash, "lifecycle.fixture")
                    status = fresh.resume(spec.campaign_hash)
                return status

            join(spawn("recovery-1", finish, fresh=True), "recovery-1")
            snapshot("after-recovery")
            before_repeat = raw_inventory(authority)
            join(
                spawn("recovery-2", lambda: boot().resume(spec.campaign_hash), fresh=True),
                "recovery-2",
            )
            verify_raw_inventory(authority, before_repeat)
            snapshot("after")
            offline()
            atomic_write_bytes(
                channel / "negative-observation.json",
                canonical_json_bytes(
                    {
                        "schema_version": "hosted-negative-observation/v1",
                        "case_family": "Q06",
                        "case": case,
                        "fixture_kind": "LIFECYCLE_FIXTURE",
                        "deployment_profile_hash": profile_hash,
                        "campaign_hash": spec.campaign_hash,
                        "request_hash": request.content_hash,
                        "response_hash": sha256_bytes(response),
                        "process_exits": exits,
                        "race_barrier": barrier_fact,
                        "before_inventory": raw_inventory(
                            channel / "snapshots/before/authority"
                        ).model_dump(mode="json"),
                        "after_inventory": raw_inventory(authority).model_dump(mode="json"),
                        "python_flags": management_python_flags(),
                        "python_executable": sys.executable,
                        "qualification_eligibility": "NOT_QUALIFIED",
                        **counters,
                    }
                ),
            )
        finally:
            for pid in children:
                try:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=HOSTED_LIFECYCLE_CASES, required=True)
    args = parser.parse_args()
    run_lifecycle_probe(args.profile_hash, args.case)


if __name__ == "__main__":
    main()
