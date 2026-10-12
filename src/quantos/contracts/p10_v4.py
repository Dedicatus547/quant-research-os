"""SDK-independent, bounded observations for the finite P10 v4 successor."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from quantos.contracts.base import CanonicalContract
from quantos.contracts.harness import (
    HarnessCapabilityObservationV2,
    HarnessRuntimeIdentityV2,
    HarnessTerminalError,
)
from quantos.contracts.refs import SHA256_PATTERN

SOCKET_CASES = tuple(
    (family, kind) for family in ("AF_INET", "AF_INET6") for kind in ("SOCK_STREAM", "SOCK_DGRAM")
)
PROBE_ARGV = ("/usr/bin/python3", "-I", "-S", "network_probe.py")
PROBE_COMMAND = " ".join(PROBE_ARGV)
PROBE_ENVIRONMENT = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}
PROBE_BYTE_CAP = 4096


class SocketSample(CanonicalContract):
    schema_version: Literal["p10-socket-sample/v1"] = "p10-socket-sample/v1"
    family: Literal["AF_INET", "AF_INET6"]
    type: Literal["SOCK_STREAM", "SOCK_DGRAM"]
    operation: Literal["socket"]
    result: Literal["CREATED", "ERROR"]
    errno: StrictInt | None

    @model_validator(mode="after")
    def result_matches_errno(self) -> Self:
        if self.result == "CREATED" and self.errno is not None:
            raise ValueError("created socket cannot have an errno")
        if self.result == "ERROR" and (self.errno is None or self.errno <= 0):
            raise ValueError("socket error requires a positive numeric errno")
        return self


class ProbeContext(CanonicalContract):
    schema_version: Literal["p10-probe-context/v1"] = "p10-probe-context/v1"
    cwd: str = Field(min_length=1)
    uid: StrictInt = Field(ge=0)
    interpreter_hash: str = Field(pattern=SHA256_PATTERN)
    environment: dict[str, str | None]

    @model_validator(mode="after")
    def environment_is_bounded(self) -> Self:
        if set(self.environment) != set(PROBE_ENVIRONMENT):
            raise ValueError("probe records only the three controlled environment keys")
        return self


class SocketObservation(CanonicalContract):
    schema_version: Literal["p10-socket-observation/v1"] = "p10-socket-observation/v1"
    context: ProbeContext
    samples: tuple[SocketSample, ...]

    @model_validator(mode="after")
    def cases_are_exact(self) -> Self:
        if tuple((item.family, item.type) for item in self.samples) != SOCKET_CASES:
            raise ValueError("probe requires exactly the four ordered socket operations")
        return self

    @property
    def expected_exit(self) -> int:
        if all(item.result == "CREATED" for item in self.samples):
            return 0
        if all(item.result == "ERROR" and item.errno == 1 for item in self.samples):
            return 1  # Fixed Linux EPERM; not a universal sandbox guarantee.
        return 2


class ProbeProcessRecord(CanonicalContract):
    schema_version: Literal["p10-manager-probe/v1"] = "p10-manager-probe/v1"
    phase: Literal["before", "after"]
    argv: tuple[str, ...] = PROBE_ARGV
    context: ProbeContext
    probe_hash: str = Field(pattern=SHA256_PATTERN)
    started_at: datetime
    completed_at: datetime
    started_ns: StrictInt = Field(ge=0)
    completed_ns: StrictInt = Field(ge=0)
    stdout_base64: str
    stderr_base64: str
    exit_code: StrictInt | None
    failure: Literal["START_FAILED", "TIMEOUT", "OUTPUT_LIMIT"] | None = None

    @model_validator(mode="after")
    def record_is_bounded(self) -> Self:
        if self.argv != PROBE_ARGV:
            raise ValueError("manager probe command is not exact")
        _check_times(self.started_at, self.completed_at, self.started_ns, self.completed_ns)
        total = 0
        for value in (self.stdout_base64, self.stderr_base64):
            raw = base64.b64decode(value, validate=True)
            total += len(raw)
            if len(raw) > PROBE_BYTE_CAP or base64.b64encode(raw).decode("ascii") != value:
                raise ValueError("probe stream is not bounded canonical base64")
        if total > PROBE_BYTE_CAP:
            raise ValueError("combined probe streams exceed byte cap")
        if (self.exit_code is None) != (self.failure == "START_FAILED"):
            raise ValueError("only a failed start has no real process exit")
        return self


class P10ExecutionRecord(CanonicalContract):
    schema_version: Literal["p10-manager-execution/v1"] = "p10-manager-execution/v1"
    request_hash: str = Field(pattern=SHA256_PATTERN)
    started_at: datetime
    completed_at: datetime
    started_ns: StrictInt = Field(ge=0)
    completed_ns: StrictInt = Field(ge=0)
    runtime: HarnessRuntimeIdentityV2 | None
    terminal_error: HarnessTerminalError | None
    normalized_transcript_hash: str = Field(pattern=SHA256_PATTERN)
    provider_transcript_hash: str | None = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def times_are_valid(self) -> Self:
        _check_times(self.started_at, self.completed_at, self.started_ns, self.completed_ns)
        return self


class P10ManagementReceipt(CanonicalContract):
    """Manager-origin record; its trusted hash is supplied separately to replay."""

    schema_version: Literal["p10-management-receipt/v1"] = "p10-management-receipt/v1"
    preparation_hash: str = Field(pattern=SHA256_PATTERN)
    spike_spec_hash: str = Field(pattern=SHA256_PATTERN)
    before: ProbeProcessRecord
    execution: P10ExecutionRecord
    after: ProbeProcessRecord


class P10ObservationV4(CanonicalContract):
    schema_version: Literal["harness-capability-observation/v4"] = (
        "harness-capability-observation/v4"
    )
    commands: HarnessCapabilityObservationV2
    management_receipt_hash: str = Field(pattern=SHA256_PATTERN)
    controls_valid: bool
    strict_completion_order: bool
    socket_creation_denial_observed: bool
    scope: Literal["FOUR_IP_SOCKET_CREATIONS_IN_FIXED_LINUX_COMBINATION"] = (
        "FOUR_IP_SOCKET_CREATIONS_IN_FIXED_LINUX_COMBINATION"
    )


def _check_times(start: datetime, end: datetime, start_ns: int, end_ns: int) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (start, end)):
        raise ValueError("manager timestamps must be timezone-aware")
    if end < start or end_ns < start_ns:
        raise ValueError("manager operation ends before it starts")
