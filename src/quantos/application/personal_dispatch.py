"""Finite local product jobs using the existing host lease and PID supervisor."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from quantos.application.personal_strategy_authority import ScopeReservationMissing
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    regular_tree_files,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalForwardScope, PersonalResearchScope
from quantos.contracts.refs import SHA256_PATTERN
from quantos.infrastructure.hosted_storage import (
    LEASE_ENV,
    StorageGuard,
    StoragePolicy,
    require_bounded_bwrap,
    supervise_storage_job,
)

_CAP = 4 * 1024 * 1024
_TIMEOUT = Path("/usr/bin/timeout")


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _Research(_Payload):
    task_id: str = Field(pattern=SHA256_PATTERN)


class _Observe(_Payload):
    observation_id: str = Field(pattern=SHA256_PATTERN)
    day: date
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    observed_at: datetime
    recompute: bool = False

    @field_validator("observed_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation dispatch time requires a timezone")
        return value.astimezone(UTC)


class _Recover(_Payload):
    observation_id: str = Field(pattern=SHA256_PATTERN)
    attempt_hash: str = Field(pattern=SHA256_PATTERN)


class _Advance(_Payload):
    shadow_id: str = Field(pattern=SHA256_PATTERN)
    execution_date: date
    observation_record_hash: str = Field(pattern=SHA256_PATTERN)
    execution_dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


_OPERATIONS: dict[str, type[_Payload]] = {
    "research_execute": _Research,
    "observation_observe": _Observe,
    "observation_recover": _Recover,
    "shadow_advance": _Advance,
}


def dispatch_payload(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A fixed method allowlist; payloads cannot carry paths, approval or code."""
    contract = _OPERATIONS.get(operation)
    if contract is None:
        raise ValueError("unsupported personal worker operation")
    result = contract.model_validate(payload).model_dump(mode="json")
    if len(canonical_json_bytes(result)) > 16_384:
        raise ValueError("personal dispatch payload is too large")
    return result


def _hash(value: str) -> str:
    if re.fullmatch(SHA256_PATTERN, value) is None:
        raise ValueError("personal dispatch requires exact SHA256 identities")
    return value


def _read(path: Path, expected: str | None = None) -> bytes:
    if not path.is_absolute():
        raise ValueError("trusted dispatch paths must be absolute")
    with opened_directory(path.parent) as descriptor:
        raw = read_regular_bytes_at(descriptor, path.name, max_bytes=_CAP)
    if expected is not None and sha256_bytes(raw) != _hash(expected):
        raise ArtifactIntegrityError("dispatch original hash disagrees")
    return raw


def _object(path: Path) -> dict[str, Any]:
    return _decode(_read(path))


def _decode(raw: bytes) -> dict[str, Any]:
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ArtifactIntegrityError("dispatch artifact must be a canonical object")
    value = cast(dict[str, Any], decoded)
    if canonical_json_bytes(value) != raw:
        raise ArtifactIntegrityError("dispatch artifact is not canonical")
    return value


def _write(directory: Path, name: str, value: object) -> None:
    with opened_directory(directory, create=True) as descriptor:
        atomic_write_bytes_at(descriptor, name, canonical_json_bytes(value))


def _argv(command_path: Path, command_hash: str, request: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(_TIMEOUT),
        "--signal=TERM",
        "--kill-after=10",
        str(request["wall_seconds"]),
        request["python_executable"],
        "-I",
        "-B",
        "-m",
        "quantos.personal_worker",
        "--command",
        str(command_path),
        "--command-sha256",
        command_hash,
    )


class PersonalDispatchFailure(RuntimeError):
    """Controlled failure; actual supervisor/worker originals remain separately bound."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self.reason_code = record["reason_code"]
        super().__init__(self.reason_code)


class PersonalResourceDispatcher:
    """One immutable attempt per exact operation; no automatic retry or new authority."""

    def __init__(
        self,
        root: Path,
        repo_root: Path,
        config_path: Path,
        *,
        python_executable: Path | None = None,
    ) -> None:
        self.root, self.repo_root = root.absolute(), repo_root.absolute()
        self.config_path = config_path.absolute()
        self.python_executable = (
            Path(sys.executable) if python_executable is None else python_executable
        ).absolute()
        self.config_sha256 = sha256_bytes(_read(self.config_path))
        self._config()

    def _config(self) -> Any:
        from quantos.application.personal_server_config import PersonalServerConfigV5

        config = PersonalServerConfigV5.model_validate_json(
            _read(self.config_path, self.config_sha256)
        )
        if config.product_root != self.root or config.repo_root != self.repo_root:
            raise PermissionError("dispatch configuration roots disagree")
        return config

    def _selection(
        self, operation: str, *, require_live: bool = True
    ) -> tuple[Any, Any, StorageGuard]:
        config = self._config()
        registration = (
            config.research_scope if operation == "research_execute" else config.forward_scope
        )
        if registration is None:
            raise PermissionError("no trusted bounded scope for this dispatch operation")
        contract = (
            PersonalResearchScope if operation == "research_execute" else PersonalForwardScope
        )
        scope = contract.model_validate_json(
            _read(registration.scope_path, registration.scope_sha256)
        )
        _read(registration.approval_evidence_path, scope.approval_evidence_sha256)
        if require_live and scope.expires_at <= datetime.now(UTC):
            raise PermissionError("personal dispatch scope expired")
        policy_raw = _read(registration.storage_policy_path, registration.storage_policy_sha256)
        policy_data: dict[str, Any] = json.loads(policy_raw)
        for name in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
            policy_data[name] = Path(policy_data[name])
        policy = StoragePolicy(**policy_data)
        if policy.canonical_bytes() != policy_raw:
            raise ArtifactIntegrityError("storage policy must retain its exact canonical identity")
        return registration, scope, StorageGuard(policy)

    def _layout(self, guard: StorageGuard) -> None:
        if (
            not self.root.is_relative_to(self.repo_root / "artifacts")
            or self.root == self.repo_root / "artifacts"
        ):
            raise PermissionError(
                "dispatch product root must be this repository's artifact product"
            )
        if any("sealed" in part.lower() for part in self.root.parts):
            raise PermissionError("sealed storage is outside dispatch scope")
        with opened_directory(self.repo_root), opened_directory(self.root, create=True):
            pass
        # Existing HS300 jobs also write the separately configured product root.
        # Bind this specific product to the monitored evidence volume; do not
        # relax StorageGuard.require_root or infer per-task exact write counts.
        if self.root.stat().st_dev != guard.policy.evidence_root.stat().st_dev:
            raise PermissionError("dispatch product root is outside the monitored evidence volume")

    def _request(
        self, operation: str, payload: dict[str, Any], *, require_live: bool = True
    ) -> tuple[dict[str, Any], StorageGuard]:
        normalized = dispatch_payload(operation, payload)
        registration, scope, guard = self._selection(operation, require_live=require_live)
        self._layout(guard)
        if not self.python_executable.is_file() or not _TIMEOUT.is_file():
            raise PermissionError("fixed interpreter and GNU timeout are required")
        worker = Path(__file__).parents[1] / "personal_worker.py"
        from quantos.infrastructure import hosted_storage

        sources = {
            "dispatcher": sha256_file(Path(__file__)),
            "worker": sha256_file(worker),
            "storage_supervisor": sha256_file(Path(hosted_storage.__file__)),
        }
        request = {
            "schema_version": "personal-dispatch-request/v1",
            "operation": operation,
            "payload": normalized,
            "product_root": str(self.root),
            "repo_root": str(self.repo_root),
            "server_config_path": str(self.config_path),
            "server_config_sha256": self.config_sha256,
            "scope_path": str(registration.scope_path),
            "scope_sha256": registration.scope_sha256,
            "scope_hash": scope.content_hash,
            "storage_policy_path": str(registration.storage_policy_path),
            "storage_policy_sha256": registration.storage_policy_sha256,
            "wall_seconds": scope.wall_seconds,
            "complete_growth_bytes": scope.growth_bytes,
            "python_executable": str(self.python_executable),
            "python_resolved_path": str(self.python_executable.resolve(strict=True)),
            "python_sha256": sha256_file(self.python_executable.resolve(strict=True)),
            "timeout_sha256": sha256_file(_TIMEOUT),
            "source_hashes": sources,
        }
        return request, guard

    def execution_request(
        self, operation: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], StorageGuard]:
        """Rebuild the original scope-budget base, never a later remaining budget.

        This read path grants no launch and works after expiry for reconciliation.
        Worker operation authorization still checks its original finite scope.
        """
        return self._request(operation, payload, require_live=False)

    def __call__(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch(operation, payload)

    @staticmethod
    def base_identity(request: dict[str, Any]) -> str:
        """Stable launch key; a repeated observation freezes its first receipt clock."""
        value = dict(request)
        if request["operation"] == "observation_observe":
            from quantos.application.personal_forward_authority import forward_operation_identity

            value["payload"] = {
                "operation_identity": forward_operation_identity(
                    request["operation"], request["payload"]
                )
            }
        return sha256_bytes(canonical_json_bytes(value))

    def _trusted_core(self) -> Any:
        from quantos.application.personal_server_config import make_trusted_service

        self._config()
        return make_trusted_service(self.root, self.repo_root, self.config_path, worker_mode=True)

    @staticmethod
    def _core_authority(core: Any, operation: str) -> Any:
        authority = (
            core.strategy_authority
            if operation == "research_execute"
            else core.product_services.forward_authority
        )
        if authority is None:
            raise PermissionError("trusted dispatcher scope authority is unavailable")
        return authority

    def _admit(self, base: dict[str, Any]) -> dict[str, Any]:
        core = self._trusted_core()
        authority = self._core_authority(core, base["operation"])
        if authority.scope.content_hash != base["scope_hash"]:
            raise ArtifactIntegrityError("dispatcher authority belongs to another frozen scope")
        limits = authority.remaining_limits()
        if not limits["admissible"] or limits["pending"]:
            raise PermissionError("scope has no available settled resource budget")
        if base["operation"] == "research_execute":
            count = len(core._prepared(base["payload"]["task_id"]).candidates)
            if limits["remaining_attempts"] < 1 or limits["remaining_native_accounts"] < count:
                raise PermissionError("research attempt/native account budget exhausted")
        elif base["operation"] in {"observation_observe", "shadow_advance"}:
            counter = (
                "remaining_observations"
                if base["operation"] == "observation_observe"
                else "remaining_native_steps"
            )
            if limits[counter] < 1:
                raise PermissionError("forward operation count budget exhausted")
        request = {
            **base,
            "wall_seconds": min(base["wall_seconds"], limits["timeout_seconds"]),
            "complete_growth_bytes": min(base["complete_growth_bytes"], limits["growth_bytes"]),
        }
        self.validate_admitted(base, request)
        return request

    @staticmethod
    def validate_admitted(base: dict[str, Any], request: dict[str, Any]) -> None:
        fixed = {
            key: value
            for key, value in base.items()
            if key not in {"wall_seconds", "complete_growth_bytes"}
        }
        actual = {
            key: value
            for key, value in request.items()
            if key not in {"wall_seconds", "complete_growth_bytes"}
        }
        if fixed != actual or any(
            type(request.get(key)) is not int or not 0 < request[key] <= base[key]
            for key in ("wall_seconds", "complete_growth_bytes")
        ):
            raise PermissionError(
                "admitted request differs from trusted base or exceeds its budgets"
            )

    def indexed_request(self, base: dict[str, Any], base_id: str) -> dict[str, Any]:
        binding = _object(self.root / "dispatch-identities" / (base_id + ".json"))
        if (
            set(binding) != {"schema_version", "base_request_hash", "request_hash"}
            or binding["schema_version"] != "personal-dispatch-identity/v1"
            or binding["base_request_hash"] != base_id
        ):
            raise ArtifactIntegrityError("dispatch stable identity binding disagrees")
        identity = _hash(binding["request_hash"])
        request = _object(self.root / "jobs" / identity / "request.json")
        if sha256_bytes(canonical_json_bytes(request)) != identity:
            raise ArtifactIntegrityError("admitted dispatch request original changed")
        # The first admitted observation timestamp is immutable. Later receipt
        # times for the same day/data/recompute operation cannot create a job.
        expected = dict(base)
        if base["operation"] == "observation_observe":
            expected["payload"] = dict(base["payload"])
            expected["payload"]["observed_at"] = request["payload"]["observed_at"]
        self.validate_admitted(expected, request)
        return request

    def _owned_roots(self, request: dict[str, Any]) -> list[Path]:
        """Explicit product-output namespaces; never whole-volume available-space deltas."""
        root = self.root
        identity = sha256_bytes(canonical_json_bytes(request))
        paths = [
            root / "jobs" / identity,
            root / "campaigns" / request["scope_hash"],
            root / "dispatch-identities",
        ]
        payload, operation = request["payload"], request["operation"]
        if operation == "research_execute":
            paths.extend((root / "tasks" / payload["task_id"], root / "account-origins"))
        elif operation in {"observation_observe", "observation_recover"}:
            paths.extend(
                (
                    root / "observations" / payload["observation_id"],
                    root / "strategy-signals",
                    root / "inputs",
                )
            )
        else:
            paths.append(root / "shadow-accounts" / payload["shadow_id"])
        return paths

    @staticmethod
    def _sizes(paths: list[Path]) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for root in paths:
            if root.is_symlink():
                raise ArtifactIntegrityError("symbolic product output cannot be measured")
            if not root.exists():
                continue
            for path in regular_tree_files(root):
                sizes[str(path)] = path.stat().st_size
                if len(sizes) > 200_000:
                    raise ValueError("owned product output inventory exceeds bounded file count")
        return sizes

    def dispatch(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Expired scopes may read an already admitted job; this call cannot launch
        # anything new until the separate live-scope and remaining-limit checks.
        base, guard = self.execution_request(operation, payload)
        base_id = self.base_identity(base)
        bindings = self.root / "dispatch-identities"
        with exclusive_directory_lock(bindings):
            indexed = bindings / (base_id + ".json")
            if indexed.exists() or indexed.is_symlink():
                request = self.indexed_request(base, base_id)
                identity = sha256_bytes(canonical_json_bytes(request))
                job = self.root / "jobs" / identity
                with exclusive_directory_lock(job):
                    return self._settle(identity, request, job / "attempt-0001", guard)
            self._selection(operation, require_live=True)
            request = self._admit(base)
            identity = sha256_bytes(canonical_json_bytes(request))
            job = self.root / "jobs" / identity
            with exclusive_directory_lock(job):
                attempt = job / "attempt-0001"
                if (job / "request.json").exists() or (job / "request.json").is_symlink():
                    if _read(job / "request.json", identity) != canonical_json_bytes(request):
                        raise ArtifactIntegrityError("personal job identity disagrees")
                    _write(
                        bindings,
                        indexed.name,
                        {
                            "schema_version": "personal-dispatch-identity/v1",
                            "base_request_hash": base_id,
                            "request_hash": identity,
                        },
                    )
                    return self._settle(identity, request, attempt, guard)
                started = time.monotonic()
                baseline = self._sizes(self._owned_roots(request))
                guard.check(request["complete_growth_bytes"])
                require_bounded_bwrap()
                _write(job, "request.json", request)
                command = {
                    "schema_version": "personal-dispatch-command/v1",
                    "request_hash": identity,
                    "request": request,
                    "output_root": str(attempt),
                }
                command_hash = sha256_bytes(canonical_json_bytes(command))
                command_path = attempt / "command.json"
                _write(attempt, command_path.name, command)
                argv = _argv(command_path, command_hash, request)
                _write(
                    attempt,
                    "measurement-start.json",
                    {
                        "schema_version": "personal-dispatch-measurement-start/v1",
                        "command_hash": command_hash,
                        "owned_roots": [str(path) for path in self._owned_roots(request)],
                        "baseline": baseline,
                        "measurement": (
                            "OWNED_RETAINED_LOGICAL_BYTES; positive per-path deltas; "
                            "no deletion credits"
                        ),
                    },
                )
                _write(
                    attempt,
                    "launch.json",
                    {
                        "command_hash": command_hash,
                        "argv": argv,
                        "argv_hash": sha256_bytes(canonical_json_bytes(argv)),
                        "created_at": datetime.now(UTC),
                        "measurement": "WHOLE_VOLUME_HEADROOM_AND_GROWTH_NOT_EXACT_TASK_WRITES",
                    },
                )
                _write(
                    bindings,
                    indexed.name,
                    {
                        "schema_version": "personal-dispatch-identity/v1",
                        "base_request_hash": base_id,
                        "request_hash": identity,
                    },
                )

                def retain_run(run: Path) -> None:
                    _write(
                        attempt,
                        "supervisor-run.json",
                        {
                            "path": str(run),
                            "policy_hash": guard.policy_hash,
                            "command_hash": command_hash,
                        },
                    )

                try:
                    run = supervise_storage_job(
                        guard,
                        argv,
                        stage="matrix",
                        expected_new_bytes=request["complete_growth_bytes"],
                        run_observer=retain_run,
                    )
                    retained = _object(attempt / "supervisor-run.json")
                    if retained["path"] != str(run):
                        raise ArtifactIntegrityError("supervisor returned another job identity")
                except Exception as error:
                    _write(
                        attempt,
                        "dispatch-exception.json",
                        {
                            "command_hash": command_hash,
                            "error_type": type(error).__name__,
                            "actual_exit": "SEE_SUPERVISOR_ORIGINAL_IF_PRESENT",
                            "recorded_at": datetime.now(UTC),
                        },
                    )
                finally:
                    _write(
                        attempt,
                        "supervisor-returned.json",
                        {
                            "schema_version": "personal-dispatch-supervisor-return/v1",
                            "command_hash": command_hash,
                            "wall_seconds": time.monotonic() - started,
                            "measurement": (
                                "WHOLE_DISPATCH_PREPARATION_SUPERVISOR_WAIT_AND_CLEANUP; "
                                "not body self-report"
                            ),
                        },
                    )
                return self._settle(identity, request, attempt, guard)

    def _usage(
        self, request: dict[str, Any], attempt: Path, run: Path, command_hash: str, exit_hash: str
    ) -> dict[str, Any]:
        path = attempt / "resource-usage.json"
        if path.exists() or path.is_symlink():
            usage = _object(path)
            if (
                usage.get("command_hash") != command_hash
                or usage.get("supervisor_run") != str(run)
                or usage.get("exit_sha256") != exit_hash
            ):
                raise ArtifactIntegrityError("frozen resource usage belongs to another execution")
            for key, filename in (
                ("baseline_sha256", "measurement-start.json"),
                ("supervisor_return_sha256", "supervisor-returned.json"),
            ):
                if (
                    usage.get(key) is not None
                    and sha256_bytes(_read(attempt / filename)) != usage[key]
                ):
                    raise ArtifactIntegrityError("frozen resource measurement original changed")
            return usage
        roots = self._owned_roots(request)
        baseline_path = attempt / "measurement-start.json"
        start = _object(baseline_path) if baseline_path.exists() else None
        growth = None
        if start is not None:
            if (
                start.get("command_hash") != command_hash
                or start.get("owned_roots") != [str(p) for p in roots]
                or not isinstance(start.get("baseline"), dict)
            ):
                raise ArtifactIntegrityError("resource measurement baseline binding differs")
            baseline = cast(dict[str, int], start["baseline"])
            if any(type(v) is not int or v < 0 for v in baseline.values()):
                raise ArtifactIntegrityError("resource baseline sizes are invalid")
            after = self._sizes([*roots, run])
            growth = sum(max(0, size - baseline.get(name, 0)) for name, size in after.items())
        wall = None
        returned_path = attempt / "supervisor-returned.json"
        if returned_path.exists() or returned_path.is_symlink():
            returned = _object(returned_path)
            if returned.get("command_hash") != command_hash:
                raise ArtifactIntegrityError("supervisor return timing belongs to another command")
            wall = returned.get("wall_seconds")
            if (
                isinstance(wall, bool)
                or not isinstance(wall, (int, float))
                or not math.isfinite(wall)
                or wall < 0
            ):
                raise ArtifactIntegrityError("supervisor return timing is unavailable or invalid")
        usage = {
            "schema_version": "personal-dispatch-resource-usage/v1",
            "command_hash": command_hash,
            "supervisor_run": str(run),
            "exit_sha256": exit_hash,
            "wall_seconds": wall,
            "growth_bytes": growth,
            "growth_measurement": "OWNED_RETAINED_LOGICAL_BYTES",
            "baseline_sha256": sha256_bytes(_read(baseline_path)) if start is not None else None,
            "supervisor_return_sha256": sha256_bytes(_read(returned_path))
            if returned_path.exists()
            else None,
            "owned_roots": [str(p) for p in roots],
            "boundary": (
                "observed supervisor return; final dispatcher settlement/return "
                "receipts are subsequent control records"
            ),
            "attribution": (
                "positive logical byte deltas in explicit product output namespaces "
                "and this run; no volume-growth attribution or deletion credits"
            ),
        }
        _write(attempt, path.name, usage)
        return usage

    def _settle_budget(
        self,
        request: dict[str, Any],
        attempt: Path,
        run: Path,
        command_hash: str,
        exit_raw: bytes,
        state: str,
    ) -> dict[str, Any]:
        operation = request["operation"]
        actual: dict[str, Any] = json.loads(exit_raw)
        fully_waited = (
            actual.get("waitpid_observed") is True
            and actual.get("namespace_exit_observed") is True
            and actual.get("cleanup_verified") is True
            and actual.get("process_scope") == "PID_NAMESPACE_WRAPPER"
            and type(actual.get("return_code")) is int
        )
        usage = (
            self._usage(request, attempt, run, command_hash, sha256_bytes(exit_raw))
            if fully_waited
            else None
        )
        if operation == "observation_recover":
            record = {
                "state": "NOT_RESERVED",
                "reason": "RECOVERY_DOES_NOT_CREATE_AN_EXECUTION_RESERVATION",
                "command_hash": command_hash,
            }
        else:
            authority = self._core_authority(self._trusted_core(), operation)
            if authority.scope.content_hash != request["scope_hash"]:
                raise ArtifactIntegrityError("budget settlement scope identity differs")
            if operation == "research_execute":
                operation_identity = request["payload"]["task_id"]
                authority_operation = None
            else:
                from quantos.application.personal_forward_authority import (
                    forward_operation_identity,
                )

                operation_identity = forward_operation_identity(operation, request["payload"])
                authority_operation = (
                    "observe" if operation == "observation_observe" else "shadow_advance"
                )
            try:
                reservation = authority.reservation(operation_identity)
            except ScopeReservationMissing:
                record = {
                    "state": "NOT_RESERVED",
                    "operation_identity": operation_identity,
                    "command_hash": command_hash,
                    "reason": "WORKER_DID_NOT_ADMIT_THIS_OPERATION",
                }
            else:
                if not fully_waited:
                    record = {
                        "state": "PENDING_REAL_SUPERVISOR_WAIT",
                        "operation_identity": operation_identity,
                        "command_hash": command_hash,
                        "unused_limits_refunded": False,
                    }
                else:
                    if reservation.get("supervisor_lease") != str(run):
                        raise ArtifactIntegrityError(
                            "scope reservation is bound to another actual supervisor"
                        )
                    if usage is None:
                        raise ArtifactIntegrityError("fully waited execution has no usage record")
                    arguments = {
                        "wall_seconds": usage["wall_seconds"],
                        "growth_bytes": usage["growth_bytes"],
                        "exit_reference": {
                            "path": str(run / "exit.json"),
                            "sha256": sha256_bytes(exit_raw),
                        },
                        "exit_scope": "SUPERVISOR_PROCESS_WAIT",
                        "growth_measurement": "OWNED_RETAINED_LOGICAL_BYTES",
                    }
                    if authority_operation is None:
                        authority.settle(operation_identity, state, **arguments)
                    else:
                        authority.settle(
                            authority_operation, operation_identity, state, **arguments
                        )
                    settled = authority.reservation(operation_identity).get("settled", False)
                    record = {
                        "state": "SETTLED" if settled else "PENDING_MEASUREMENT",
                        "operation_identity": operation_identity,
                        "result_state": state,
                        "command_hash": command_hash,
                        "usage_sha256": sha256_bytes(canonical_json_bytes(usage)),
                        "exit_reference": arguments["exit_reference"],
                        "unused_failed_limits_refunded": False,
                    }
        if usage is not None:
            record["usage_sha256"] = sha256_bytes(canonical_json_bytes(usage))
        digest = sha256_bytes(canonical_json_bytes(record))
        _write(attempt / "budget", digest + ".json", record)
        return {"path": "budget/" + digest + ".json", "sha256": digest, "state": record["state"]}

    @staticmethod
    def _result_state(operation: str, result: dict[str, Any]) -> str:
        if operation == "observation_observe":
            state = result.get("status", "UNKNOWN")
            return "SUCCEEDED" if state in {"EMITTED", "ABSTAIN", "MISSING"} else state
        if operation == "shadow_advance":
            return result.get("native_receipt", {}).get("run_status", "UNKNOWN")
        return result.get("state", "UNKNOWN")

    def _settle(
        self, identity: str, request: dict[str, Any], attempt: Path, guard: StorageGuard
    ) -> dict[str, Any]:
        if not (attempt / "command.json").exists() or not (attempt / "launch.json").exists():
            return self._unknown(identity, "LAUNCH_MATERIAL_INCOMPLETE_NO_REISSUE", attempt)
        command = _object(attempt / "command.json")
        if command["request_hash"] != identity or command["request"] != request:
            raise ArtifactIntegrityError("dispatch command differs from frozen request")
        command_hash = sha256_bytes(canonical_json_bytes(command))
        argv = _argv(attempt / "command.json", command_hash, request)
        launch = _object(attempt / "launch.json")
        if (
            launch.get("command_hash") != command_hash
            or launch.get("argv") != list(argv)
            or launch.get("argv_hash") != sha256_bytes(canonical_json_bytes(argv))
        ):
            raise ArtifactIntegrityError("dispatch launch differs from exact command")
        result_path = attempt / "worker-result.json"
        run_ref = attempt / "supervisor-run.json"
        if not run_ref.exists() and not run_ref.is_symlink():
            return self._unknown(identity, "SUPERVISOR_RUN_NOT_OBSERVED", attempt)
        reference = _object(run_ref)
        run = Path(reference["path"])
        if (
            run.parent != guard.policy.evidence_root / "storage-control"
            or re.fullmatch(r"run-[0-9]+-[0-9]+", run.name) is None
            or reference["policy_hash"] != guard.policy_hash
            or reference["command_hash"] != command_hash
        ):
            raise ArtifactIntegrityError("dispatch supervisor binding disagrees")
        exit_path = run / "exit.json"
        if not exit_path.exists() and not exit_path.is_symlink():
            return self._unknown(identity, "SUPERVISOR_EXIT_UNOBSERVED", attempt)
        exit_raw = _read(exit_path)
        exit_record: dict[str, Any] = json.loads(exit_raw)
        if (
            exit_record.get("policy_hash") != guard.policy_hash
            or exit_record.get("stage") != "matrix"
        ):
            raise ArtifactIntegrityError("supervisor exit belongs to another policy/stage")
        for name in ("return.json", "failure.json"):
            retained_path = attempt / name
            if retained_path.exists() or retained_path.is_symlink():
                retained = _object(retained_path)
                prior = retained.get("supervisor", {})
                if (
                    retained.get("command_hash") != command_hash
                    or retained.get("job_id") != identity
                    or prior.get("path") != str(run)
                    or prior.get("exit_sha256") != sha256_bytes(exit_raw)
                ):
                    raise ArtifactIntegrityError("committed dispatch supervisor original changed")
                for field, filename in (
                    ("namespace_sha256", "namespace.json"),
                    ("prelaunch_sha256", "prelaunch.json"),
                ):
                    if field in prior and sha256_bytes(_read(run / filename)) != prior[field]:
                        raise ArtifactIntegrityError(
                            "committed supervisor boundary original changed"
                        )
                budget = retained.get("budget_settlement")
                if budget is not None:
                    if re.fullmatch(
                        r"budget/[a-f0-9]{64}\.json", budget.get("path", "")
                    ) is None or sha256_bytes(_read(attempt / budget["path"])) != budget.get(
                        "sha256"
                    ):
                        raise ArtifactIntegrityError("committed budget settlement original changed")
                    budget_original = _object(attempt / budget["path"])
                    if (
                        budget_original.get("usage_sha256") is not None
                        and sha256_bytes(_read(attempt / "resource-usage.json"))
                        != budget_original["usage_sha256"]
                    ):
                        raise ArtifactIntegrityError(
                            "committed resource measurement original changed"
                        )
                if name == "return.json" and (
                    sha256_bytes(_read(result_path)) != retained.get("worker_result_sha256")
                ):
                    raise ArtifactIntegrityError("committed worker result original changed")
        prelaunch = run / "prelaunch.json"
        if prelaunch.exists() or prelaunch.is_symlink():
            actual: dict[str, Any] = json.loads(_read(prelaunch))
            if actual.get("argv_hash") != launch["argv_hash"] or (
                actual.get("expected_new_bytes") != request["complete_growth_bytes"]
                or actual.get("policy_hash") != guard.policy_hash
                or actual.get("stage") != "matrix"
            ):
                raise ArtifactIntegrityError("supervisor prelaunch command/budget disagrees")
        supervisor = {"path": str(run), "exit_sha256": sha256_bytes(exit_raw)}
        success = (
            type(exit_record.get("return_code")) is int
            and exit_record.get("return_code") == 0
            and exit_record.get("waitpid_observed") is True
            and exit_record.get("namespace_exit_observed") is True
            and exit_record.get("cleanup_verified") is True
            and exit_record.get("failure") is None
            and exit_record.get("process_scope") == "PID_NAMESPACE_WRAPPER"
        )
        if not success:
            reason = "RESOURCE_SUPERVISOR_FAILED"
            failure_path = attempt / "worker-failure.json"
            if failure_path.exists() or failure_path.is_symlink():
                failure = _object(failure_path)
                if failure.get("command_hash") != command_hash or failure.get("job_id") != identity:
                    raise ArtifactIntegrityError("child failure identity disagrees")
                allowed = {
                    "PIT_HARD_REJECTION",
                    "AUTHORIZATION_REJECTED",
                    "INTEGRITY_REJECTED",
                    "EXECUTION_ERROR",
                }
                if failure.get("reason_code") not in allowed:
                    raise ArtifactIntegrityError("unrecognized child failure classification")
                reason = failure["reason_code"]
            budget = self._settle_budget(request, attempt, run, command_hash, exit_raw, "FAILED")
            record = {
                "schema_version": "personal-dispatch-failure/v1",
                "budget_settlement": budget,
                "job_id": identity,
                "command_hash": command_hash,
                "reason_code": reason,
                "supervisor": supervisor,
                "return_code": exit_record.get("return_code"),
                "waitpid_observed": exit_record.get("waitpid_observed", False),
                "cleanup_verified": exit_record.get("cleanup_verified", False),
                "run_status": "FAILED",
                "validation_verdict": "NOT_EVALUATED",
            }
            _write(attempt, "failure.json", record)
            raise PersonalDispatchFailure(record)
        if not result_path.exists() and not result_path.is_symlink():
            self._settle_budget(request, attempt, run, command_hash, exit_raw, "UNKNOWN")
            return self._unknown(
                identity, "WORKER_RESULT_UNOBSERVED_AFTER_SUPERVISOR_EXIT", attempt
            )
        if not prelaunch.exists():
            raise ArtifactIntegrityError("successful supervisor prelaunch original is missing")
        namespace = run / "namespace.json"
        supervisor["namespace_sha256"] = sha256_bytes(_read(namespace))
        supervisor["prelaunch_sha256"] = sha256_bytes(_read(prelaunch))
        result = _object(result_path)
        if (
            result.get("command_hash") != command_hash
            or result.get("job_id") != identity
            or (
                result.get("operation") != request["operation"]
                or not isinstance(result.get("result"), dict)
            )
        ):
            raise ArtifactIntegrityError("worker result does not bind exact command")
        budget = self._settle_budget(
            request,
            attempt,
            run,
            command_hash,
            exit_raw,
            self._result_state(request["operation"], result["result"]),
        )
        receipt = {
            "schema_version": "personal-dispatch-return/v1",
            "budget_settlement": budget,
            "job_id": identity,
            "command_hash": command_hash,
            "supervisor": supervisor,
            "worker_result_sha256": sha256_bytes(canonical_json_bytes(result)),
            "qualification_eligibility": "NOT_QUALIFIED",
        }
        _write(attempt, "return.json", receipt)
        return cast(dict[str, Any], result["result"])

    @staticmethod
    def _unknown(identity: str, reason: str, attempt: Path) -> dict[str, Any]:
        record = {
            "job_id": identity,
            "state": "UNKNOWN",
            "run_status": "UNKNOWN",
            "reason_code": reason,
            "validation_verdict": "NOT_EVALUATED",
            "reissued": False,
            "real_exit_invented": False,
        }
        _write(
            attempt / "diagnostics", sha256_bytes(canonical_json_bytes(record)) + ".json", record
        )
        return record

    def reconcile(self, job_id: str) -> dict[str, Any]:
        job = self.root / "jobs" / _hash(job_id)
        with exclusive_directory_lock(job):
            request = _object(job / "request.json")
            if sha256_bytes(canonical_json_bytes(request)) != job_id:
                raise ArtifactIntegrityError("dispatch recovery request identity disagrees")
            # Reconciliation reads the originally bound policy, even after a
            # scope expires. It grants no new launch or inherited budget.
            policy = json.loads(
                _read(Path(request["storage_policy_path"]), request["storage_policy_sha256"])
            )
            for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
                policy[key] = Path(policy[key])
            return self._settle(
                job_id, request, job / "attempt-0001", StorageGuard(StoragePolicy(**policy))
            )


def validate_worker_command(
    command_path: Path, expected_hash: str, guard: StorageGuard
) -> dict[str, Any]:
    """Bind the exact operator config, command, sources, actual lease and budget."""
    raw = _read(command_path, expected_hash)
    command = _decode(raw)
    if (
        sha256_bytes(raw) != expected_hash
        or set(command) != {"schema_version", "request_hash", "request", "output_root"}
        or command["schema_version"] != "personal-dispatch-command/v1"
    ):
        raise ArtifactIntegrityError("worker command schema differs")
    request: dict[str, Any] = command["request"]
    identity = _hash(command["request_hash"])
    if sha256_bytes(canonical_json_bytes(request)) != identity:
        raise ArtifactIntegrityError("worker request identity differs")
    root, repo_root = Path(request["product_root"]), Path(request["repo_root"])
    output = root / "jobs" / identity / "attempt-0001"
    if command_path != output / "command.json" or command["output_root"] != str(output):
        raise PermissionError("worker command/output must belong to the exact product job")
    dispatcher = PersonalResourceDispatcher(
        root,
        repo_root,
        Path(request["server_config_path"]),
        python_executable=Path(request["python_executable"]),
    )
    actual, actual_guard = dispatcher.execution_request(request["operation"], request["payload"])
    dispatcher.validate_admitted(actual, request)
    base_id = dispatcher.base_identity(actual)
    indexed = dispatcher.indexed_request(actual, base_id)
    if indexed != request or actual_guard.policy_hash != guard.policy_hash:
        raise PermissionError("worker dependencies/configuration/policy differ from launch")
    if str(Path(sys.executable).absolute()) != request["python_executable"]:
        raise PermissionError("worker interpreter path differs from fixed launch")
    guard.require_lease()
    lease_name = os.environ.get(LEASE_ENV)
    if lease_name is None:
        raise PermissionError("worker actual supervisor lease is absent")
    lease = Path(lease_name)
    prelaunch: dict[str, Any] = json.loads(_read(lease / "prelaunch.json"))
    argv = _argv(command_path, expected_hash, request)
    if (
        prelaunch.get("stage") != "matrix"
        or prelaunch.get("policy_hash") != guard.policy_hash
        or prelaunch.get("argv_hash") != sha256_bytes(canonical_json_bytes(argv))
        or prelaunch.get("expected_new_bytes") != request["complete_growth_bytes"]
    ):
        raise PermissionError("worker command is not the actual resource-supervised job")
    return command
