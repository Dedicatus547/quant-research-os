"""Bounded subprocess adapter around the existing Qlib executor and storage supervisor."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from quantos.artifacts.store import (
    atomic_write_bytes,
    confined_regular_file,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_cash import PreparedHS300CashStudy
from quantos.contracts.hs300_lifecycle import PreparedHS300LifecycleStudy
from quantos.contracts.personal_research import PreparedHS300Study
from quantos.infrastructure.hosted_storage import (
    StorageGuard,
    StoragePolicy,
    StorageRejected,
    require_bounded_bwrap,
    supervise_storage_job,
)

HS300Prepared = PreparedHS300Study | PreparedHS300LifecycleStudy | PreparedHS300CashStudy


def _read_prepared(raw: bytes) -> HS300Prepared:
    contract = (
        PreparedHS300CashStudy
        if json.loads(raw).get("schema_version") == "personal-study-prepared/v4"
        else PreparedHS300LifecycleStudy
        if json.loads(raw).get("schema_version") == "personal-study-prepared/v3"
        else PreparedHS300Study
    )
    return contract.model_validate_json(raw)


class HS300WorkerFailure(RuntimeError):
    """Safe child failure classification; actual supervisor exit remains immutable."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class GuardedHS300Executor:
    """A single namespace job; Qlib exclusively owns orders, fills and accounts.

    The existing supervisor reserves full growth and observes host/Linux space.
    GNU timeout bounds the entire child including all seven candidates. No retry
    is issued after a timeout or an unobserved parent exit.
    """

    def __init__(
        self,
        catalog: Mapping[str, Any],
        *,
        server_config_path: Path,
        storage_policy_path: Path,
        storage_policy_hash: str,
        wall_seconds: int,
        growth_bytes: int,
    ) -> None:
        self.catalog = dict(catalog)
        self.server_config_path = server_config_path.absolute()
        self.storage_policy_path = storage_policy_path.absolute()
        self.storage_policy_hash = storage_policy_hash
        self.wall_seconds = wall_seconds
        self.growth_bytes = growth_bytes

    def _guard(self) -> StorageGuard:
        verify_file(self.storage_policy_path, self.storage_policy_hash)
        data = json.loads(self.storage_policy_path.read_bytes())
        for name in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
            data[name] = Path(data[name])
        return StorageGuard(StoragePolicy(**data))

    def preflight(self, prepared: HS300Prepared) -> None:
        if self.wall_seconds <= 0 or self.growth_bytes <= 0:
            raise PermissionError("bounded wall and complete growth limits are required")
        if len(prepared.candidates) != 7:
            raise PermissionError("HS300 run must preserve the fixed seven-candidate denominator")
        if not Path("/usr/bin/timeout").is_file():
            raise PermissionError("wall supervisor is unavailable")
        self._guard().check(self.growth_bytes)
        require_bounded_bwrap()

    def __call__(
        self, prepared: HS300Prepared, root: Path, cancelled: Callable[[], bool]
    ) -> dict[str, Any]:
        self.preflight(prepared)
        if cancelled():
            return {
                "prepared_hash": prepared.content_hash,
                "run_status": "FAILED",
                "validation_verdict": "NOT_EVALUATED",
                "planned_denominator": 7,
                "receipts": [],
            }
        # This root is owned by the parent task service; the worker only publishes
        # candidate artifacts and its own outcome. The parent owns ledger transitions.
        prepared_path = root / "worker-prepared.json"
        atomic_write_bytes(prepared_path, prepared.canonical_bytes())
        command = (
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=10",
            str(self.wall_seconds),
            sys.executable,
            "-B",
            "-m",
            "quantos.application.hs300_worker",
            "--config",
            str(self.server_config_path),
            "--prepared",
            str(prepared_path.absolute()),
            "--output",
            str(root.absolute()),
        )
        atomic_write_bytes(
            root / "bounded-launch.json",
            canonical_json_bytes(
                {
                    "prepared_hash": prepared.content_hash,
                    "server_config_sha256": sha256_file(self.server_config_path),
                    "storage_policy_sha256": self.storage_policy_hash,
                    "timeout_sha256": sha256_file(Path("/usr/bin/timeout")),
                    "wall_seconds": self.wall_seconds,
                    "complete_growth_bytes": self.growth_bytes,
                    "argv": command,
                }
            ),
        )
        try:
            supervision = supervise_storage_job(
                self._guard(), command, stage="matrix", expected_new_bytes=self.growth_bytes
            )
        except StorageRejected:
            # stdout/stderr are intentionally suppressed by the existing supervisor.
            # Keep a child's safe PIT classification without rewriting its real exit.
            failure_path = root / "worker-failure.json"
            if failure_path.exists():
                failure = json.loads(
                    confined_regular_file(root, "worker-failure.json").read_bytes()
                )
                if failure.get("prepared_hash") != prepared.content_hash:
                    raise ValueError("worker failure does not bind prepared study") from None
                if failure.get("reason_code") == "PIT_HARD_REJECTION":
                    raise HS300WorkerFailure("PIT_HARD_REJECTION") from None
            raise
        atomic_write_bytes(
            root / "storage-supervision.json",
            canonical_json_bytes(
                {"path": str(supervision), "exit_sha256": sha256_file(supervision / "exit.json")}
            ),
        )
        outcome = json.loads((root / "worker-outcome.json").read_bytes())
        if outcome.get("prepared_hash") != prepared.content_hash:
            raise ValueError("worker outcome does not bind prepared study")
        return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepared = _read_prepared(args.prepared.read_bytes())
    try:
        return _run_worker(args, prepared)
    except Exception as error:
        # No arbitrary exception message, input row, environment or secret is exported.
        reason = (
            "PIT_HARD_REJECTION"
            if getattr(error, "reason_code", None) == "PIT_HARD_REJECTION"
            else "execution_error"
        )
        atomic_write_bytes(
            args.output / "worker-failure.json",
            canonical_json_bytes(
                {
                    "schema_version": "personal-hs300-worker-failure/v1",
                    "prepared_hash": prepared.content_hash,
                    "run_status": "FAILED",
                    "validation_verdict": "NOT_EVALUATED",
                    "reason_code": reason,
                    "error_type": type(error).__name__,
                }
            ),
        )
        return 1


def _run_worker(args: argparse.Namespace, prepared: HS300Prepared) -> int:
    from quantos.application.personal_server_config import make_trusted_service
    from quantos.infrastructure.hosted_storage import configured_guard
    from quantos.research.personal_qlib import PersonalQlibExecutor

    configured_guard().require_lease()
    config = json.loads(args.config.read_bytes())
    service = make_trusted_service(
        Path(config["product_root"]), Path(config["repo_root"]), config_path=args.config
    )
    task_id = prepared.content_hash
    # Fail closed if an entry point tries to run an unowned or mismatched task.
    state = service.worker_state(task_id)
    if state not in {"RUNNING", "CANCEL_REQUESTED"}:
        raise PermissionError("worker requires an existing live parent task")
    parent_prepared = _read_prepared(
        confined_regular_file(service.root, f"tasks/{task_id}/prepared.json").read_bytes()
    )
    if parent_prepared.content_hash != prepared.content_hash:
        raise PermissionError("worker prepared identity differs from parent")
    if args.output != service.root / "tasks" / task_id / "execution":
        raise PermissionError("worker output must belong to the exact parent task")
    outcome = PersonalQlibExecutor(service.catalog)(
        prepared, args.output, lambda: service.worker_state(task_id) == "CANCEL_REQUESTED"
    )
    atomic_write_bytes(args.output / "worker-outcome.json", canonical_json_bytes(outcome))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
