"""Pre-agent trust-boundary primitives.

This module deliberately contains no Agent harness or LLM integration.  It is the
small, deterministic boundary that a later MCP adapter must call before it may
dispatch to an application service.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.status import ReasonCode


class SecurityBoundaryError(ValueError):
    """An untrusted request crossed a fixed security boundary."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ResourceBudget:
    """Hard limits applied before a proposal reaches a public contract."""

    max_payload_bytes: int = 262_144
    max_depth: int = 24
    max_nodes: int = 10_000
    max_string_bytes: int = 65_536
    max_requests: int = 1_000

    def __post_init__(self) -> None:
        if (
            min(
                self.max_payload_bytes,
                self.max_depth,
                self.max_nodes,
                self.max_string_bytes,
                self.max_requests,
            )
            < 1
        ):
            raise ValueError("resource budget limits must be positive")


@dataclass(frozen=True)
class BoundaryAuditDecision:
    """Non-sensitive decision metadata suitable for an AgentRun audit record."""

    sequence: int
    capability: str
    payload_sha256: str
    payload_size_bytes: int
    allowed: bool
    reason_code: ReasonCode | None


_FORBIDDEN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "environment.get",
        "filesystem.read",
        "filesystem.write",
        "registry.transition",
        "registry.write",
        "secret.read",
        "shell.execute",
        "snapshot.write",
        "validation.override",
    }
)
_FORBIDDEN_CAPABILITY_PREFIXES: Final[tuple[str, ...]] = (
    "authority.",
    "environment.",
    "filesystem.",
    "secret.",
    "shell.",
)
_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
        "tushare_token",
    }
)
_AUTHORITY_CONTROL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "canonical",
        "direct_validated",
        "force_pass",
        "gate_override",
        "oos_access",
        "run_status",
        "strategy_status",
        "unseal_oos",
        "validation_verdict",
        "verdict",
    }
)
_SAFE_ENVIRONMENT_KEYS: Final[frozenset[str]] = frozenset({"LANG", "LC_ALL", "LC_CTYPE", "TZ"})
_CAPABILITY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _reject_json_constant(value: str) -> object:
    raise SecurityBoundaryError(
        ReasonCode.SCHEMA_INVALID, f"non-finite JSON constant is forbidden: {value}"
    )


def _capability_is_forbidden(value: str) -> bool:
    return value in _FORBIDDEN_CAPABILITIES or value.startswith(_FORBIDDEN_CAPABILITY_PREFIXES)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SecurityBoundaryError(ReasonCode.SCHEMA_INVALID, "duplicate JSON object key")
        result[key] = value
    return result


def _validate_payload_graph(value: object, budget: ResourceBudget) -> None:
    nodes = 0
    string_bytes = 0
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > budget.max_nodes:
            raise SecurityBoundaryError(
                ReasonCode.RESOURCE_BUDGET_EXCEEDED, "payload node budget exceeded"
            )
        if depth > budget.max_depth:
            raise SecurityBoundaryError(
                ReasonCode.RESOURCE_BUDGET_EXCEEDED, "payload depth budget exceeded"
            )
        if isinstance(item, str):
            string_bytes += len(item.encode("utf-8"))
        elif isinstance(item, dict):
            mapping = cast(dict[object, object], item)
            for key, child in mapping.items():
                if not isinstance(key, str):
                    raise SecurityBoundaryError(
                        ReasonCode.SCHEMA_INVALID, "payload keys must be strings"
                    )
                string_bytes += len(key.encode("utf-8"))
                normalized_key = key.casefold().replace("-", "_")
                if normalized_key in _SENSITIVE_KEYS:
                    raise SecurityBoundaryError(
                        ReasonCode.SECRET_ACCESS_DENIED, "secret-bearing fields are forbidden"
                    )
                if normalized_key in _AUTHORITY_CONTROL_KEYS:
                    raise SecurityBoundaryError(
                        ReasonCode.AUTHORITY_FIELD_DENIED,
                        "authority-owned fields are forbidden",
                    )
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            sequence = cast(list[object], item)
            stack.extend((child, depth + 1) for child in sequence)
        elif isinstance(item, float) and not math.isfinite(item):
            raise SecurityBoundaryError(ReasonCode.SCHEMA_INVALID, "payload numbers must be finite")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise SecurityBoundaryError(
                ReasonCode.SCHEMA_INVALID, "payload contains an invalid value"
            )
        if string_bytes > budget.max_string_bytes:
            raise SecurityBoundaryError(
                ReasonCode.RESOURCE_BUDGET_EXCEEDED, "payload string budget exceeded"
            )


def load_bounded_json_object(
    payload: bytes, *, budget: ResourceBudget | None = None
) -> dict[str, object]:
    """Decode one untrusted JSON object under deterministic resource limits."""

    limits = budget or ResourceBudget()
    if len(payload) > limits.max_payload_bytes:
        raise SecurityBoundaryError(
            ReasonCode.RESOURCE_BUDGET_EXCEEDED, "payload byte budget exceeded"
        )
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except RecursionError as error:
        raise SecurityBoundaryError(
            ReasonCode.RESOURCE_BUDGET_EXCEEDED, "payload nesting cannot be decoded safely"
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SecurityBoundaryError(
            ReasonCode.SCHEMA_INVALID, "payload is not valid JSON"
        ) from error
    if not isinstance(value, dict):
        raise SecurityBoundaryError(ReasonCode.SCHEMA_INVALID, "payload root must be an object")
    result = cast(dict[str, object], value)
    _validate_payload_graph(result, limits)
    return result


def restricted_agent_environment(
    source: Mapping[str, str] | None = None,
    *,
    allowlist: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Return the complete environment permitted for an isolated Agent process."""

    environment = os.environ if source is None else source
    allowed = _SAFE_ENVIRONMENT_KEYS if allowlist is None else frozenset(allowlist)
    if not allowed.issubset(_SAFE_ENVIRONMENT_KEYS):
        raise SecurityBoundaryError(
            ReasonCode.SECRET_ACCESS_DENIED, "Agent environment key is not permitted"
        )
    return {key: environment[key] for key in sorted(allowed) if key in environment}


class AgentRequestBoundary:
    """Capability allowlist and budget gate with payload-free audit decisions."""

    def __init__(
        self,
        allowed_capabilities: frozenset[str],
        *,
        budget: ResourceBudget | None = None,
    ) -> None:
        if any(_CAPABILITY_PATTERN.fullmatch(item) is None for item in allowed_capabilities):
            raise ValueError("allowed capability names must be bounded logical identifiers")
        if any(_capability_is_forbidden(item) for item in allowed_capabilities):
            raise ValueError(
                "an Agent policy cannot grant authority, secret, shell, or path access"
            )
        self._allowed = allowed_capabilities
        self._budget = budget or ResourceBudget()
        self._decisions: list[BoundaryAuditDecision] = []

    @classmethod
    def from_policy(cls, policy: object) -> AgentRequestBoundary:
        from quantos.contracts.agent import AgentCapabilityPolicy

        if not isinstance(policy, AgentCapabilityPolicy):
            raise ValueError("capability policy contract is invalid")
        return cls(
            frozenset(item.value for item in policy.capabilities),
            budget=ResourceBudget(
                max_payload_bytes=policy.max_payload_bytes,
                max_depth=policy.max_payload_depth,
                max_nodes=policy.max_payload_nodes,
                max_string_bytes=policy.max_string_bytes,
                max_requests=policy.max_requests,
            ),
        )

    @property
    def audit_decisions(self) -> tuple[BoundaryAuditDecision, ...]:
        return tuple(self._decisions)

    def accept(self, capability: str, payload: bytes) -> dict[str, object]:
        digest = sha256_bytes(payload)
        if len(self._decisions) >= self._budget.max_requests:
            raise SecurityBoundaryError(
                ReasonCode.RESOURCE_BUDGET_EXCEEDED, "request budget exceeded"
            )
        if _CAPABILITY_PATTERN.fullmatch(capability) is None:
            self._record("<invalid>", digest, len(payload), False, ReasonCode.SCHEMA_INVALID)
            raise SecurityBoundaryError(ReasonCode.SCHEMA_INVALID, "capability name is invalid")
        if _capability_is_forbidden(capability) or capability not in self._allowed:
            self._record(capability, digest, len(payload), False, ReasonCode.CAPABILITY_DENIED)
            raise SecurityBoundaryError(ReasonCode.CAPABILITY_DENIED, "capability is not granted")
        try:
            accepted = load_bounded_json_object(payload, budget=self._budget)
        except SecurityBoundaryError as error:
            self._record(capability, digest, len(payload), False, error.reason_code)
            raise
        self._record(capability, digest, len(payload), True, None)
        return accepted

    def _record(
        self,
        capability: str,
        digest: str,
        size: int,
        allowed: bool,
        reason_code: ReasonCode | None,
    ) -> None:
        self._decisions.append(
            BoundaryAuditDecision(
                sequence=len(self._decisions) + 1,
                capability=capability,
                payload_sha256=digest,
                payload_size_bytes=size,
                allowed=allowed,
                reason_code=reason_code,
            )
        )


class AuthorityRootResolver:
    """Resolve hash-addressed authority inputs without accepting caller paths."""

    def __init__(self, roots: Mapping[str, Path]) -> None:
        resolved: dict[str, Path] = {}
        for domain, root in roots.items():
            if not domain or domain in resolved:
                raise ValueError("authority domains must be unique and nonempty")
            if (
                root.is_symlink()
                or not root.is_dir()
                or root.absolute() != root.resolve(strict=True)
            ):
                raise SecurityBoundaryError(
                    ReasonCode.AUTHORITY_ROOT_INVALID, "authority root is invalid"
                )
            resolved[domain] = root.resolve(strict=True)
        self._roots = MappingProxyType(resolved)

    def content_addressed_directory(self, domain: str, digest: str) -> Path:
        if re.fullmatch(SHA256_PATTERN, digest) is None:
            raise SecurityBoundaryError(ReasonCode.SCHEMA_INVALID, "content hash is invalid")
        root = self._root(domain)
        return self._confined_existing(root, f"sha256-{digest}", expect_directory=True)

    def artifact_file(self, domain: str, digest: str, logical_path: str) -> Path:
        directory = self.content_addressed_directory(domain, digest)
        try:
            safe_path = validate_logical_path(logical_path)
        except ValueError as error:
            raise SecurityBoundaryError(
                ReasonCode.PATH_BOUNDARY_VIOLATION, "logical path is not safe"
            ) from error
        return self._confined_existing(directory, safe_path, expect_directory=False)

    def verify_artifact_file(
        self,
        domain: str,
        digest: str,
        logical_path: str,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Path:
        path = self.artifact_file(domain, digest, logical_path)
        if path.stat().st_size != expected_size_bytes or sha256_file(path) != expected_sha256:
            raise ArtifactIntegrityError("authority file does not match its immutable reference")
        return path

    def _root(self, domain: str) -> Path:
        try:
            return self._roots[domain]
        except KeyError as error:
            raise SecurityBoundaryError(
                ReasonCode.CAPABILITY_DENIED, "authority domain is not granted"
            ) from error

    @staticmethod
    def _confined_existing(root: Path, relative: str, *, expect_directory: bool) -> Path:
        candidate = root / relative
        current = root
        for part in Path(relative).parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise SecurityBoundaryError(
                        ReasonCode.PATH_BOUNDARY_VIOLATION, "symbolic links are forbidden"
                    )
                current.lstat()
            except FileNotFoundError as error:
                raise SecurityBoundaryError(
                    ReasonCode.SOURCE_INCOMPLETE, "authority object does not exist"
                ) from error
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise SecurityBoundaryError(
                ReasonCode.PATH_BOUNDARY_VIOLATION, "authority path escaped its root"
            ) from error
        valid_kind = resolved.is_dir() if expect_directory else resolved.is_file()
        if not valid_kind:
            raise SecurityBoundaryError(
                ReasonCode.SOURCE_INCOMPLETE, "authority object has wrong type"
            )
        return resolved
