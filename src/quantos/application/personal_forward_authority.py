"""Trusted finite forward scope; observations never approve their own execution."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quantos.application.personal_strategy_authority import ScopeBudgetJournal
from quantos.artifacts.store import exclusive_directory_lock
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import PersonalForwardScope


def forward_operation_identity(operation: str, payload: dict[str, Any]) -> str:
    """Public step identity shared by product, worker and dispatcher settlement."""
    if operation in {"observe", "observation_observe"}:
        normalized = {
            "observation_id": payload["observation_id"],
            "day": str(payload["day"]),
            "dataset_id": payload["dataset_id"],
            "recompute": bool(payload.get("recompute", False)),
        }
        operation = "observe"
    elif operation == "shadow_advance":
        normalized = {
            key: payload[key]
            for key in (
                "shadow_id",
                "execution_date",
                "observation_record_hash",
                "execution_dataset_id",
            )
        }
        normalized["execution_date"] = str(normalized["execution_date"])
    else:
        raise ValueError("unsupported forward operation identity")
    return sha256_bytes(canonical_json_bytes({"operation": operation, "request": normalized}))


class PersonalForwardAuthority:
    def __init__(
        self,
        product_root: Path,
        scope: PersonalForwardScope,
        approval: bytes,
        *,
        resource_check: Any,
    ) -> None:
        if sha256_bytes(approval) != scope.approval_evidence_sha256:
            raise PermissionError("forward approval original differs")
        self.root = product_root.absolute() / "campaigns" / scope.content_hash
        self.scope, self.resource_check = scope, resource_check
        self.journal = ScopeBudgetJournal(self.root, scope, flat=True)

    def _limits(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        limits = self.journal.resources(events)
        attempts = list(self.journal.reservations(events).values())
        limits["remaining_observations"] = max(
            0, self.scope.max_observations - sum(a.get("operation") == "observe" for a in attempts)
        )
        limits["remaining_native_steps"] = max(
            0,
            self.scope.max_native_steps
            - sum(a.get("operation") == "shadow_advance" for a in attempts),
        )
        limits["admissible"] = bool(
            limits["admissible"]
            and (limits["remaining_observations"] or limits["remaining_native_steps"])
        )
        return limits

    def authorize(
        self,
        *,
        strategy_hash: str,
        policy_hash: str,
        runtime_hash: str,
        operation: str,
        dataset_hash: str,
        day: date,
        operation_identity: str,
        kind: str,
    ) -> str:
        with exclusive_directory_lock(self.root):
            scope, events = self.scope, self.journal.events()
            if any(e["kind"] == "STOP" for e in events):
                raise PermissionError("forward authority stopped")
            if scope.expires_at <= datetime.now(UTC):
                self.journal.append("STOP", {"reason": "EXPIRY"})
                raise PermissionError("forward authority expired")
            if (
                strategy_hash != scope.strategy_hash
                or policy_hash != scope.policy_hash
                or runtime_hash != scope.runtime_hash
                or dataset_hash not in scope.allowed_dataset_hashes
                or not scope.start_date <= day <= scope.end_date
                or kind not in {"market", "synthetic"}
                or (kind == "market") != (scope.purpose == "FORWARD_OBSERVATION")
            ):
                raise PermissionError("forward operation outside trusted scope")
            if operation not in {"observe", "shadow_advance"}:
                raise PermissionError("unsupported forward operation")
            self.journal.identity({"identity": operation_identity})
            attempts = self.journal.reservations(events)
            if operation_identity in attempts:
                prior = attempts[operation_identity]
                if (
                    prior.get("operation") != operation
                    or prior.get("dataset_hash") != dataset_hash
                    or str(prior.get("day")) != str(day)
                ):
                    raise ValueError("forward identity belongs to another operation")
                if self.resource_check is None:
                    raise PermissionError("trusted resource dispatcher unavailable")
                self.resource_check(scope)
                return scope.content_hash
            limits = self.journal.resources(events)
            if limits["pending"]:
                raise PermissionError(
                    "unsettled forward reservation requires actual exit reconciliation"
                )
            bound = scope.max_observations if operation == "observe" else scope.max_native_steps
            if (
                sum(a.get("operation") == operation for a in attempts.values()) >= bound
                or not limits["admissible"]
            ):
                self.journal.append("STOP", {"reason": "BUDGET"})
                raise PermissionError("forward operation budget exhausted")
            if self.resource_check is None:
                raise PermissionError("trusted resource dispatcher unavailable")
            self.resource_check(scope)
            self.journal.append(
                "RESERVED",
                {
                    "identity": operation_identity,
                    "operation": operation,
                    "dataset_hash": dataset_hash,
                    "day": day,
                    "wall_limit_seconds": limits["wall_seconds"],
                    "growth_limit_bytes": limits["growth_bytes"],
                    **self.journal.lease_binding(),
                },
            )
            return scope.content_hash

    def remaining_limits(self) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            return self._limits(self.journal.events())

    def reservation(self, operation_identity: str) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            return self.journal.reservation(operation_identity)

    def record(
        self,
        operation: str,
        operation_identity: str,
        state: str,
        detail: dict[str, Any] | None = None,
        *,
        wall_seconds: float | None = None,
        growth_bytes: int | None = None,
        exit_scope: str = "IN_PROCESS_RETURN",
        exit_reference: dict[str, str] | None = None,
    ) -> None:
        with exclusive_directory_lock(self.root):
            if self.journal.reservation(operation_identity).get("operation") != operation:
                raise ValueError("forward result operation differs from reservation")
            self.journal.record(
                operation_identity,
                state,
                {**(detail or {}), "operation": operation},
                wall_seconds=wall_seconds,
                growth_bytes=growth_bytes,
                exit_scope=exit_scope,
                exit_reference=exit_reference,
            )

    def settle(
        self,
        operation: str,
        operation_identity: str,
        state: str,
        *,
        wall_seconds: float | None,
        growth_bytes: int | None,
        exit_reference: dict[str, str],
        exit_scope: str = "SUPERVISOR_PROCESS_WAIT",
        growth_measurement: str = "OWNED_RETAINED_LOGICAL_BYTES",
    ) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            if self.journal.reservation(operation_identity).get("operation") != operation:
                raise ValueError("forward settlement operation differs from reservation")
            self.journal.settle(
                operation_identity,
                state,
                wall_seconds=wall_seconds,
                growth_bytes=growth_bytes,
                exit_reference=exit_reference,
                exit_scope=exit_scope,
                growth_measurement=growth_measurement,
            )
            return self._limits(self.journal.events())

    def status(self) -> dict[str, Any]:
        with exclusive_directory_lock(self.root):
            events = self.journal.events()
            limits = self._limits(events)
        return {
            "scope_hash": self.scope.content_hash,
            "events": events,
            "state": limits["state"],
            "remaining_limits": limits,
            "validation_verdict": "NOT_EVALUATED",
        }

    def stop(self, reason: str) -> dict[str, Any]:
        if not reason.strip() or len(reason) > 4000:
            raise ValueError("explicit bounded STOP reason required")
        with exclusive_directory_lock(self.root):
            if not any(e["kind"] == "STOP" for e in self.journal.events()):
                self.journal.append("STOP", {"reason": "OPERATOR_STOP", "explanation": reason})
        return self.status()
