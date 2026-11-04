"""Fixed local personal-product child; invoked only through a bound matrix lease."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantos.application.personal_dispatch import validate_worker_command
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure.hosted_storage import configured_guard


def execute_worker_operation(core: Any, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Fixed routes, never arbitrary method names or runtime plugins."""
    if operation == "research_execute":
        return core.execute(payload["task_id"])
    if operation == "observation_observe":
        result = core.product_services.observations.observe(**payload)
        core.product_services.record_forward_result(operation, payload, result)
        return result
    if operation == "observation_recover":
        return core.product_services.observations.recover(**payload)
    if operation == "shadow_advance":
        result = core.product_services.shadow.advance(**payload)
        core.product_services.record_forward_result(operation, payload, result)
        return result
    raise ValueError("unsupported personal worker operation")


def run_worker(command_path: Path, command_hash: str) -> int:
    guard = configured_guard()
    guard.require_lease()
    command = validate_worker_command(command_path, command_hash, guard)
    request = command["request"]
    output = Path(command["output_root"])
    try:
        from quantos.application.personal_server_config import make_trusted_service

        core = make_trusted_service(
            Path(request["product_root"]),
            Path(request["repo_root"]),
            Path(request["server_config_path"]),
            worker_mode=True,
        )
        result = execute_worker_operation(core, request["operation"], request["payload"])
        atomic_write_bytes(
            output / "worker-result.json",
            canonical_json_bytes(
                {
                    "schema_version": "personal-worker-result/v1",
                    "job_id": command["request_hash"],
                    "command_hash": command_hash,
                    "operation": request["operation"],
                    "result": result,
                    "actual_exit": "IN_PROCESS_RETURN",
                    "completed_at": datetime.now(UTC),
                }
            ),
        )
        return 0
    except Exception as error:
        reason = (
            "PIT_HARD_REJECTION"
            if getattr(error, "reason_code", None) == "PIT_HARD_REJECTION"
            else "AUTHORIZATION_REJECTED"
            if isinstance(error, PermissionError)
            else "INTEGRITY_REJECTED"
            if isinstance(error, ArtifactIntegrityError)
            else "EXECUTION_ERROR"
        )
        # No exception message, raw child output, process environment or secrets.
        atomic_write_bytes(
            output / "worker-failure.json",
            canonical_json_bytes(
                {
                    "schema_version": "personal-worker-failure/v1",
                    "job_id": command["request_hash"],
                    "command_hash": command_hash,
                    "reason_code": reason,
                    "error_type": type(error).__name__,
                    "actual_exit": "IN_PROCESS_EXCEPTION",
                    "run_status": "FAILED",
                    "validation_verdict": "NOT_EVALUATED",
                    "recorded_at": datetime.now(UTC),
                }
            ),
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--command-sha256", required=True)
    args = parser.parse_args()
    try:
        return run_worker(args.command, args.command_sha256)
    except Exception:
        # An invalid/unbound command has no trusted output root. Its real process
        # exit is retained by the parent supervisor; do not invent a child receipt.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
