"""Trusted finite scope resources in the existing immutable campaign journal."""

from __future__ import annotations

import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalResearchScope, PreparedStrategyStudy
from quantos.contracts.refs import SHA256_PATTERN
from quantos.infrastructure.hosted_storage import HASH_ENV, LEASE_ENV

NORMAL_SCOPE_RESULTS = {"SUCCEEDED", "EMITTED", "ABSTAIN", "MISSING", "STOPPED"}
SCOPE_RESULTS = NORMAL_SCOPE_RESULTS | {"FAILED", "CANCELLED", "UNKNOWN", "REJECTED"}


class ScopeReservationMissing(ValueError):
    """The verified journal has no reservation for this explicit operation."""


def budget_event_detail(event: dict[str, Any]) -> dict[str, Any]:
    """Keep retained flat forward and nested research journal rows readable."""
    if "detail" in event and "identity" not in event:
        return cast(dict[str, Any], event["detail"])
    metadata = {"kind", "scope_hash", "previous_hash", "at", "schema_version", "event_hash"}
    return {key: value for key, value in event.items() if key not in metadata}


def _read(path: Path) -> bytes:
    if not path.is_absolute():
        raise ArtifactIntegrityError("scope originals require absolute paths")
    with opened_directory(path.parent) as descriptor:
        return read_regular_bytes_at(descriptor, path.name, max_bytes=65_536)


def _usage(wall: object, growth: object) -> None:
    if wall is not None and (
        not isinstance(wall, (float, int))
        or isinstance(wall, bool)
        or not math.isfinite(wall)
        or wall < 0
    ):
        raise ValueError("observed wall time must be finite and nonnegative")
    if growth is not None and (
        isinstance(growth, bool) or not isinstance(growth, int) or growth < 0
    ):
        raise ValueError("observed growth must be nonnegative integral bytes")


class ScopeBudgetJournal:
    """Shared resource receipts; this remains the same campaign authority store."""

    def __init__(self, root: Path, scope: Any, *, flat: bool = False) -> None:
        self.root, self.scope, self.flat = root, scope, flat
        atomic_write_bytes(root / "scope.json", scope.canonical_bytes())

    def events(self) -> list[dict[str, Any]]:
        if _read(self.root / "scope.json") != self.scope.canonical_bytes():
            raise ArtifactIntegrityError("campaign scope original changed")
        directory = self.root / "events"
        if not directory.exists() and not directory.is_symlink():
            return []
        with opened_directory(directory):
            names = sorted(p.name for p in directory.iterdir())
        if len(names) > 1024:
            raise ArtifactIntegrityError("campaign journal exceeds finite bound")
        result: list[dict[str, Any]] = []
        previous: str | None = None
        for index, name in enumerate(names, 1):
            raw = _read(directory / name)
            decoded: Any = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ArtifactIntegrityError("campaign journal row is not an object")
            row = cast(dict[str, Any], decoded)
            if (
                name != f"{index:06d}.json"
                or canonical_json_bytes(row) != raw
                or row.get("previous_hash") != previous
                or row.get("scope_hash") != self.scope.content_hash
            ):
                raise ArtifactIntegrityError("campaign journal hash chain differs")
            if row.get("schema_version") == "personal-scope-event/v2":
                payload = {key: value for key, value in row.items() if key != "event_hash"}
                if sha256_bytes(canonical_json_bytes(payload)) != row.get("event_hash"):
                    raise ArtifactIntegrityError("campaign journal event content changed")
            elif row["kind"] not in {"RESERVED", "RESULT", "STOP"} or any(
                key in budget_event_detail(row)
                for key in ("wall_limit_seconds", "growth_limit_bytes", "supervisor_lease")
            ):
                raise ArtifactIntegrityError("resource events require their versioned content hash")
            result.append(row)
            previous = sha256_bytes(raw)
        return result

    def append(self, kind: str, detail: dict[str, Any]) -> None:
        events = self.events()
        if len(events) >= 1024:
            raise ValueError("campaign journal budget exhausted")
        body = detail if self.flat else {"detail": detail}
        row = {
            **body,
            "schema_version": "personal-scope-event/v2",
            "kind": kind,
            "scope_hash": self.scope.content_hash,
            "previous_hash": sha256_bytes(canonical_json_bytes(events[-1])) if events else None,
            "at": datetime.now(UTC),
        }
        row["event_hash"] = sha256_bytes(canonical_json_bytes(row))
        raw = canonical_json_bytes(row)
        if len(raw) > 65_536:
            raise ValueError("campaign journal row exceeds finite size")
        atomic_write_bytes(self.root / "events" / f"{len(events) + 1:06d}.json", raw)

    @staticmethod
    def identity(detail: dict[str, Any]) -> str:
        identity = detail.get("identity", detail.get("task_id"))
        if not isinstance(identity, str) or re.fullmatch(SHA256_PATTERN, identity) is None:
            raise ValueError("scope reservation identity must be an exact SHA256")
        return identity

    def reservations(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        reservations: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["kind"] == "RESERVED":
                detail = budget_event_detail(event)
                identity = self.identity(detail)
                if identity in reservations:
                    raise ArtifactIntegrityError("duplicate campaign reservation")
                reservations[identity] = detail
        return reservations

    @staticmethod
    def lease_binding() -> dict[str, Any]:
        lease, policy = os.environ.get(LEASE_ENV), os.environ.get(HASH_ENV)
        if lease is None or policy is None:
            raise PermissionError("new scope reservations require the actual live supervisor lease")
        raw = _read(Path(lease) / "prelaunch.json")
        prelaunch: dict[str, Any] = json.loads(raw)
        if prelaunch.get("stage") != "matrix" or prelaunch.get("policy_hash") != policy:
            raise PermissionError("reservation requires the actual matrix supervisor")
        return {
            "supervisor_lease": lease,
            "supervisor_policy_hash": policy,
            "supervisor_prelaunch_sha256": sha256_bytes(raw),
        }

    def resources(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        reservations = self.reservations(events)
        settled: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["kind"] == "SETTLED":
                detail = budget_event_detail(event)
                identity = self.identity(detail)
                if identity not in reservations or identity in settled:
                    raise ArtifactIntegrityError("scope settlement denominator differs")
                settled[identity] = detail
        charged_wall = observed_wall = retained_wall = 0.0
        charged_growth = observed_growth = retained_growth = 0
        pending: list[str] = []
        for identity, reservation in reservations.items():
            wall_limit = float(reservation.get("wall_limit_seconds", self.scope.wall_seconds))
            growth_limit = int(reservation.get("growth_limit_bytes", self.scope.growth_bytes))
            _usage(wall_limit, growth_limit)
            completed = settled.get(identity)
            if completed is None:
                pending.append(identity)
                charged_wall += wall_limit
                charged_growth += growth_limit
                retained_wall += wall_limit
                retained_growth += growth_limit
                continue
            wall, growth = float(completed["wall_seconds"]), int(completed["growth_bytes"])
            _usage(wall, growth)
            observed_wall += wall
            observed_growth += growth
            normal = completed["state"] in NORMAL_SCOPE_RESULTS
            wall_charge = wall if normal else max(wall, wall_limit)
            growth_charge = growth if normal else max(growth, growth_limit)
            charged_wall += wall_charge
            charged_growth += growth_charge
            retained_wall += wall_charge - wall
            retained_growth += growth_charge - growth
        wall_left = max(0.0, float(self.scope.wall_seconds) - charged_wall)
        growth_left = max(0, self.scope.growth_bytes - charged_growth)
        stopped = any(e["kind"] == "STOP" for e in events)
        expired = self.scope.expires_at <= datetime.now(UTC)
        return {
            "wall_seconds": wall_left,
            "growth_bytes": growth_left,
            "timeout_seconds": max(0, math.floor(wall_left)),
            "pending": sorted(pending),
            "observed_used_wall_seconds": observed_wall,
            "observed_retained_output_bytes": observed_growth,
            "charged_wall_seconds": charged_wall,
            "charged_growth_bytes": charged_growth,
            "retained_reservation_wall_seconds": retained_wall,
            "retained_reservation_growth_bytes": retained_growth,
            "state": "STOPPED"
            if stopped
            else "EXPIRED"
            if expired
            else "UNSETTLED"
            if pending
            else "OPEN",
            "admissible": not stopped
            and not expired
            and not pending
            and wall_left > 0
            and growth_left > 0,
            "overrun": charged_wall > self.scope.wall_seconds
            or charged_growth > self.scope.growth_bytes,
            "measurement": "COMPLETE_JOB_WALL_AND_OWNED_RETAINED_LOGICAL_OUTPUT; "
            "HELD_UNUSED_LIMITS_ARE_RESERVATIONS_NOT_OBSERVED_USAGE",
        }

    def reservation(self, identity: str) -> dict[str, Any]:
        events = self.events()
        reservations = self.reservations(events)
        if identity not in reservations:
            raise ScopeReservationMissing("identity has no trusted reservation in this scope")
        settled = [
            budget_event_detail(e)
            for e in events
            if e["kind"] == "SETTLED" and self.identity(budget_event_detail(e)) == identity
        ]
        return {
            **reservations[identity],
            "settled": bool(settled),
            "settlement": settled[-1] if settled else None,
        }

    def record(
        self,
        identity: str,
        state: str,
        detail: dict[str, Any],
        *,
        wall_seconds: float | None,
        growth_bytes: int | None,
        exit_scope: str,
        exit_reference: dict[str, str] | None,
    ) -> None:
        if state not in SCOPE_RESULTS or exit_scope not in {
            "IN_PROCESS_RETURN",
            "IN_PROCESS_EXCEPTION",
            "SUPERVISOR_PROCESS_WAIT",
        }:
            raise ValueError("unsupported scope result state/exit scope")
        _usage(wall_seconds, growth_bytes)
        self.reservation(identity)
        value = {
            **detail,
            "identity": identity,
            "state": state,
            "wall_seconds": wall_seconds,
            "growth_bytes": growth_bytes,
            "exit_scope": exit_scope,
            "exit_reference": exit_reference,
            "resource_settlement": "PENDING_REAL_SUPERVISOR_WAIT",
        }
        if value not in [budget_event_detail(e) for e in self.events() if e["kind"] == "RESULT"]:
            self.append("RESULT", value)
        if state in {"UNKNOWN", "CANCELLED", "STOPPED"} and not any(
            e["kind"] == "STOP" for e in self.events()
        ):
            self.append("STOP", {"reason": state, "identity": identity})
        if exit_scope == "SUPERVISOR_PROCESS_WAIT" and exit_reference is not None:
            self.settle(
                identity,
                state,
                wall_seconds=wall_seconds,
                growth_bytes=growth_bytes,
                exit_reference=exit_reference,
                exit_scope=exit_scope,
                growth_measurement="OWNED_RETAINED_LOGICAL_BYTES",
            )

    def settle(
        self,
        identity: str,
        state: str,
        *,
        wall_seconds: float | None,
        growth_bytes: int | None,
        exit_reference: dict[str, str],
        exit_scope: str,
        growth_measurement: str,
    ) -> dict[str, Any]:
        if state not in SCOPE_RESULTS or exit_scope != "SUPERVISOR_PROCESS_WAIT":
            raise ValueError("settlement requires a final state and actual supervisor wait")
        if growth_measurement != "OWNED_RETAINED_LOGICAL_BYTES":
            raise ValueError("whole-volume growth is not exact attributable task output")
        _usage(wall_seconds, growth_bytes)
        reservation = self.reservation(identity)
        lease = reservation.get("supervisor_lease")
        if not isinstance(lease, str) or set(exit_reference) != {"path", "sha256"}:
            raise PermissionError("reservation has no original supervisor binding")
        path = Path(exit_reference["path"])
        if path != Path(lease) / "exit.json" or not path.is_absolute():
            raise PermissionError("exit is not this reservation's actual supervisor")
        raw = _read(path)
        if sha256_bytes(raw) != exit_reference["sha256"] or (
            sha256_bytes(_read(Path(lease) / "prelaunch.json"))
            != reservation.get("supervisor_prelaunch_sha256")
        ):
            raise ArtifactIntegrityError("settlement supervisor original changed")
        actual: dict[str, Any] = json.loads(raw)
        code = actual.get("return_code")
        if (
            actual.get("stage") != "matrix"
            or actual.get("policy_hash") != reservation.get("supervisor_policy_hash")
            or actual.get("waitpid_observed") is not True
            or actual.get("namespace_exit_observed") is not True
            or actual.get("cleanup_verified") is not True
            or actual.get("process_scope") != "PID_NAMESPACE_WRAPPER"
            or not isinstance(code, int)
            or isinstance(code, bool)
        ):
            raise PermissionError("actual process/namespace exit is not fully observed")
        if state in NORMAL_SCOPE_RESULTS and (code != 0 or actual.get("failure") is not None):
            raise PermissionError("normal completion cannot adopt failed supervisor exit")
        value = {
            "identity": identity,
            "state": state,
            "wall_seconds": wall_seconds,
            "growth_bytes": growth_bytes,
            "exit_reference": exit_reference,
            "exit_scope": exit_scope,
            "growth_measurement": growth_measurement,
            "supervisor_return_code": code,
            "unused_failed_limits_refunded": False,
        }
        if reservation["settled"]:
            if reservation["settlement"] != value:
                raise ArtifactIntegrityError("settled scope resources cannot be rewritten")
            return self.resources(self.events())
        if wall_seconds is None or growth_bytes is None:
            if value not in [
                budget_event_detail(e) for e in self.events() if e["kind"] == "SETTLEMENT_PENDING"
            ]:
                self.append("SETTLEMENT_PENDING", value)
            return self.resources(self.events())
        self.append("SETTLED", value)
        resources = self.resources(self.events())
        if (resources["overrun"] or state in {"UNKNOWN", "CANCELLED", "STOPPED"}) and not any(
            e["kind"] == "STOP" for e in self.events()
        ):
            self.append(
                "STOP",
                {
                    "reason": "RESOURCE_OVERRUN" if resources["overrun"] else state,
                    "identity": identity,
                },
            )
        return self.resources(self.events())


class PersonalStrategyAuthority:
    """Operator construction and source checks remain outside proposal parameters."""

    def __init__(
        self,
        product_root: Path,
        scope: PersonalResearchScope,
        approval: bytes,
        *,
        resource_check: Any = None,
    ) -> None:
        if sha256_bytes(approval) != scope.approval_evidence_sha256:
            raise PermissionError("scope approval original differs")
        self.scope, self.resource_check = scope, resource_check
        self.root = product_root.absolute() / "campaigns" / scope.content_hash
        self.journal = ScopeBudgetJournal(self.root, scope)

    def _limits(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        limits = self.journal.resources(events)
        attempts = list(self.journal.reservations(events).values())
        limits["remaining_attempts"] = max(0, self.scope.max_attempts - len(attempts))
        limits["remaining_native_accounts"] = max(
            0, self.scope.max_native_accounts - sum(a["accounts"] for a in attempts)
        )
        limits["admissible"] = bool(
            limits["admissible"]
            and limits["remaining_attempts"]
            and limits["remaining_native_accounts"]
        )
        return limits

    def status(self) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            events = self.journal.events()
            attempts = list(self.journal.reservations(events).values())
            limits = self._limits(events)
        return {
            "scope_hash": self.scope.content_hash,
            "scope": self.scope.model_dump(mode="json"),
            "attempts": attempts,
            "attempted_denominator": len(attempts),
            "reserved_native_accounts": sum(a["accounts"] for a in attempts),
            "state": limits["state"],
            "remaining_limits": limits,
            "events": events,
            "validation_verdict": "NOT_EVALUATED",
        }

    def remaining_limits(self) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            return self._limits(self.journal.events())

    def reservation(self, task_id: str) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            return self.journal.reservation(task_id)

    def reserve(self, prepared: PreparedStrategyStudy, kind: str) -> str:
        with exclusive_directory_lock(self.root):
            events, scope = self.journal.events(), self.scope
            if any(e["kind"] == "STOP" for e in events):
                raise PermissionError("bounded research already stopped")
            if scope.expires_at <= datetime.now(UTC):
                self.journal.append("STOP", {"reason": "EXPIRY"})
                raise PermissionError("bounded research expired")
            if (
                scope.dataset_hash != prepared.dataset_hash
                or scope.policy_hash != prepared.policy_hash
                or scope.runtime_hash != prepared.code_hash
                or scope.start_date != prepared.request.start_date
                or scope.end_date != prepared.request.end_date
                or not set(prepared.strategy_hashes.values()) <= set(scope.allowed_strategy_hashes)
                or kind not in {"market", "synthetic"}
                or (kind == "market") != (scope.purpose == "MARKET_RESEARCH")
            ):
                raise PermissionError("proposal outside trusted scope")
            if self.resource_check is None:
                raise PermissionError("trusted resource dispatcher unavailable")
            attempts = self.journal.reservations(events)
            if prepared.content_hash in attempts:
                self.resource_check(scope)
                return scope.content_hash
            limits = self.journal.resources(events)
            if limits["pending"]:
                raise PermissionError("unsettled reservation requires actual exit reconciliation")
            count = len(prepared.candidates)
            if (
                len(attempts) >= scope.max_attempts
                or sum(a["accounts"] for a in attempts.values()) + count > scope.max_native_accounts
                or not limits["admissible"]
            ):
                self.journal.append("STOP", {"reason": "BUDGET"})
                raise PermissionError("bounded research budget exhausted")
            self.resource_check(scope)
            self.journal.append(
                "RESERVED",
                {
                    "identity": prepared.content_hash,
                    "task_id": prepared.content_hash,
                    "accounts": count,
                    "wall_limit_seconds": limits["wall_seconds"],
                    "growth_limit_bytes": limits["growth_bytes"],
                    **self.journal.lease_binding(),
                },
            )
            return scope.content_hash

    def record(
        self,
        task_id: str,
        state: str,
        detail: dict[str, Any],
        *,
        wall_seconds: float | None = None,
        growth_bytes: int | None = None,
        exit_scope: str = "IN_PROCESS_RETURN",
        exit_reference: dict[str, str] | None = None,
    ) -> None:
        with exclusive_directory_lock(self.root):
            self.journal.record(
                task_id,
                state,
                {**detail, "task_id": task_id},
                wall_seconds=wall_seconds,
                growth_bytes=growth_bytes,
                exit_scope=exit_scope,
                exit_reference=exit_reference,
            )

    def settle(
        self,
        task_id: str,
        state: str,
        *,
        wall_seconds: float | None,
        growth_bytes: int | None,
        exit_reference: dict[str, str],
        exit_scope: str = "SUPERVISOR_PROCESS_WAIT",
        growth_measurement: str = "OWNED_RETAINED_LOGICAL_BYTES",
    ) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            self.journal.settle(
                task_id,
                state,
                wall_seconds=wall_seconds,
                growth_bytes=growth_bytes,
                exit_reference=exit_reference,
                exit_scope=exit_scope,
                growth_measurement=growth_measurement,
            )
            return self._limits(self.journal.events())

    def stop(self, reason: str) -> dict[str, Any]:
        if not reason.strip() or len(reason) > 4000:
            raise ValueError("STOP requires a bounded explicit reason")
        with exclusive_directory_lock(self.root):
            if not any(e["kind"] == "STOP" for e in self.journal.events()):
                self.journal.append("STOP", {"reason": "OPERATOR_STOP", "explanation": reason})
        return self.status()
