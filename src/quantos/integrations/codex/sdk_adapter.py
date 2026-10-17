"""Process-isolated adapter for the optional official Codex Python SDK."""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from quantos.application.agent_harness import (
    HarnessAttemptResult,
    HarnessCaptureError,
    HarnessExecutionResult,
    capture_from_agent_events,
    make_agent_event,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    AgentEventKind,
    HarnessErrorKind,
    HarnessExecutionRequest,
    HarnessRuntimeIdentity,
    HarnessRuntimeIdentityV2,
    HarnessTerminalError,
)
from quantos.integrations.codex.event_normalizer import (
    CodexEventNormalizationError,
    normalize_provider_events,
    normalize_provider_failure_events,
)
from quantos.integrations.codex.notification_projection import (
    normalize_provider_events as normalize_projected_provider_events,
)
from quantos.integrations.codex.versioning import (
    CODEX_CANDIDATE_RUNTIME_PROFILES,
)
from quantos.security import validate_secret_free

_HOST_MODULE = "quantos.integrations.codex.sdk_host"
_SENSITIVE_PARENT_NAMES = frozenset({"P10_FORBIDDEN_SECRET"})
_SENSITIVE_PARENT_PREFIXES = ("TUSHARE_",)
_RUNTIME_CANDIDATE_ENV = "QUANTOS_CODEX_RUNTIME_CANDIDATE_ID"


_HOST_TRANSPORT_CAPTURE_MAX_BYTES = 65_536
_HOST_FAILURE_PHASES = frozenset(
    {
        "REQUEST_PARSE",
        "SDK_IMPORT",
        "VERSION_CHECK",
        "BINARY_HASH",
        "SDK_STARTUP",
        "ACCOUNT_READ",
        "RUNTIME_METADATA",
        "THREAD_START",
        "MCP_INVENTORY",
        "OUTPUT_SCHEMA_PARSE",
        "TURN_START",
        "TURN_STREAM",
    }
)


def _host_transport_capture(
    stdout: bytes | None,
    stderr: bytes | None,
    *,
    phase: str,
    exception_class: str | None,
    complete: bool,
) -> dict[str, object]:
    """Bound and scan originals before attaching local failure observations."""
    streams: list[dict[str, object]] = []
    for name, payload in (("host-stdout.txt", stdout), ("host-stderr.txt", stderr)):
        item: dict[str, object] = {"file": name, "complete": complete}
        if payload is None:
            item["retention"] = "UNOBSERVED"
        else:
            item.update(bytes=len(payload), sha256=sha256_bytes(payload))
            if len(payload) > _HOST_TRANSPORT_CAPTURE_MAX_BYTES:
                item["retention"] = "OVER_BYTE_CAP"
            else:
                try:
                    if _contains_parent_secret(payload):
                        raise ValueError("forbidden parent value")
                    decoded = payload.decode("utf-8")
                    validate_secret_free(decoded, file_name=name)
                    # Structured failure output is scanned with the existing typed
                    # protocol view so credential fields cannot hide inside JSON.
                    try:
                        value = json.loads(decoded)
                    except json.JSONDecodeError:
                        value = None
                    if value is not None:
                        if _contains_parent_secret(canonical_json_bytes(value)):
                            raise ValueError("forbidden decoded parent value")
                        from quantos.application.hosted_protocol import scan_protocol_artifact

                        scan_protocol_artifact(value)
                except (ValueError, UnicodeError):
                    item["retention"] = "CREDENTIAL_OR_ENCODING_GUARD"
                else:
                    item["retention"] = "RETAINED"
                    item["base64"] = base64.b64encode(payload).decode("ascii")
        streams.append(item)
    return {
        "schema_version": "sdk-host-transport/v1",
        "phase": phase,
        "exception_class": exception_class,
        "streams": streams,
    }


class CodexSdkAdapter:
    """Execute one bounded request in a fresh process group and isolated config home."""

    def __init__(
        self,
        *,
        authentication_home: Path | None = None,
        host_argv: tuple[str, ...] | None = None,
        runtime_candidate_id: str | None = None,
        metadata_projection: bool = False,
    ) -> None:
        if (
            runtime_candidate_id is not None
            and runtime_candidate_id not in CODEX_CANDIDATE_RUNTIME_PROFILES
        ):
            raise ValueError("unsupported Codex runtime candidate profile")
        self._authentication_home = authentication_home
        self._host_argv = host_argv or (sys.executable, "-m", _HOST_MODULE)
        self._runtime_candidate_id = runtime_candidate_id
        self._metadata_projection = metadata_projection

    def execute(self, request: HarnessExecutionRequest) -> HarnessExecutionResult:
        attempts: list[HarnessAttemptResult] = []
        deadline = time.monotonic() + request.total_timeout_seconds
        for attempt_index in range(1, request.max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                attempts.append(
                    self._failed_result(
                        HarnessErrorKind.TIMEOUT,
                        TimeoutError("total harness wall-clock budget exhausted"),
                        attempt=attempt_index,
                    )
                )
                break
            attempt = self._execute_once(
                request,
                attempt_index=attempt_index,
                timeout_seconds=min(float(request.timeout_seconds), remaining),
            )
            attempts.append(attempt)
            if attempt.terminal_error is None or not attempt.terminal_error.retryable:
                break
            backoff = min(
                request.retry_backoff_milliseconds / 1_000,
                max(0.0, deadline - time.monotonic()),
            )
            if backoff > 0:
                time.sleep(backoff)
        return HarnessExecutionResult(attempts=tuple(attempts))

    def _execute_once(
        self,
        request: HarnessExecutionRequest,
        *,
        attempt_index: int,
        timeout_seconds: float,
    ) -> HarnessAttemptResult:
        stdout: bytes | None = None
        stderr: bytes | None = None
        phase = "HOST_SPAWN"
        complete = False
        host_failure: Mapping[str, object] | None = None
        process_exit: dict[str, object] = {
            "schema_version": "sdk-host-process-exit/v1",
            "spawned": False,
            "wait_observed": False,
            "return_code": None,
        }

        def failed(
            kind: HarnessErrorKind,
            error: BaseException | None,
            *,
            message_hash: str | None = None,
            retryable: bool = False,
            provider_transcript: bytes | None = None,
            runtime: HarnessRuntimeIdentity | HarnessRuntimeIdentityV2 | None = None,
            attempt: int = 1,
            qualification_observations: Mapping[str, object] | None = None,
        ) -> HarnessAttemptResult:
            failure_phase = phase
            error_class = type(error).__name__ if error is not None else None
            if host_failure is not None:
                reported_phase = host_failure.get("phase")
                if isinstance(reported_phase, str) and reported_phase in _HOST_FAILURE_PHASES:
                    failure_phase = reported_phase
                value = host_failure.get("exception_class")
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
                    error_class = value
            result = self._failed_result(
                kind,
                error,
                message_hash=message_hash,
                retryable=retryable,
                provider_transcript=provider_transcript,
                runtime=runtime,
                attempt=attempt,
                qualification_observations=qualification_observations,
            )
            return replace(
                result,
                qualification_observations={
                    **(qualification_observations or {}),
                    "host_process_exit": dict(process_exit),
                    "host_transport": _host_transport_capture(
                        stdout,
                        stderr,
                        phase=failure_phase,
                        exception_class=error_class,
                        complete=complete,
                    ),
                },
            )

        with tempfile.TemporaryDirectory(prefix="quantos-codex-sdk-") as temporary:
            isolated_home = Path(temporary)
            self._link_authentication(isolated_home)
            environment = {
                item.name: item.value for item in request.runtime_policy.host_environment
            }
            environment["CODEX_HOME"] = str(isolated_home)
            if self._runtime_candidate_id is not None:
                environment[_RUNTIME_CANDIDATE_ENV] = self._runtime_candidate_id
            try:
                process = subprocess.Popen(
                    self._host_argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=request.cwd,
                    env=environment,
                    start_new_session=True,
                )
                process_exit["spawned"] = True
            except OSError as error:
                return failed(HarnessErrorKind.TRANSPORT_START_FAILED, error, attempt=attempt_index)
            try:
                phase = "HOST_COMMUNICATE"
                stdout, stderr = process.communicate(
                    request.canonical_bytes(), timeout=timeout_seconds
                )
                complete = True
                process_exit.update(
                    wait_observed=type(process.returncode) is int, return_code=process.returncode
                )
            except subprocess.TimeoutExpired as error:
                stdout = error.output if isinstance(error.output, bytes) else None
                stderr = error.stderr if isinstance(error.stderr, bytes) else None
                self._terminate_process_group(process)
                process_exit.update(
                    wait_observed=type(process.returncode) is int, return_code=process.returncode
                )
                return failed(HarnessErrorKind.TIMEOUT, error, attempt=attempt_index)

        assert stdout is not None and stderr is not None
        phase = "HOST_OUTPUT_GUARD"
        if _contains_parent_secret(stdout, stderr):
            return failed(
                HarnessErrorKind.PERMISSION_DENIED,
                ValueError("forbidden parent environment value observed in SDK host output"),
                attempt=attempt_index,
            )
        phase = "HOST_EXIT"
        if process.returncode != 0:
            return failed(
                HarnessErrorKind.TRANSPORT_CLOSED,
                RuntimeError(
                    f"SDK host exited {process.returncode}; stderr={sha256_bytes(stderr)}"
                ),
                attempt=attempt_index,
            )
        if len(stdout) > request.max_transcript_bytes + 1_000_000:
            return failed(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host response exceeds its bound"),
                attempt=attempt_index,
            )
        phase = "HOST_JSON_PARSE"
        try:
            response = cast(object, json.loads(stdout))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return failed(HarnessErrorKind.OUTPUT_INVALID, error, attempt=attempt_index)
        try:
            if _contains_parent_secret(canonical_json_bytes(response)):
                return failed(
                    HarnessErrorKind.PERMISSION_DENIED,
                    ValueError("forbidden decoded parent value observed in SDK host output"),
                    attempt=attempt_index,
                )
        except ValueError as error:
            return failed(HarnessErrorKind.OUTPUT_INVALID, error, attempt=attempt_index)
        if not isinstance(response, dict):
            return failed(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host response is not an object"),
                attempt=attempt_index,
            )
        body = cast(Mapping[str, object], response)
        diagnostic = body.get("failure_diagnostic")
        host_failure = (
            cast(Mapping[str, object], diagnostic) if isinstance(diagnostic, dict) else None
        )
        phase = "HOST_PROVIDER_PARSE"
        terminal_error = self._terminal_error(body.get("error"))
        provider_events = self._provider_events(body.get("provider_events"))
        if provider_events is None:
            return failed(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host provider events are malformed"),
                attempt=attempt_index,
            )
        provider_transcript = b"".join(
            canonical_json_bytes(event) + b"\n" for event in provider_events
        )
        if len(provider_transcript) > request.max_transcript_bytes:
            return failed(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("provider transcript exceeds its bound"),
                attempt=attempt_index,
            )
        runtime = self._runtime_identity(body)
        if terminal_error is not None:
            return failed(
                terminal_error.kind,
                None,
                message_hash=terminal_error.message_hash,
                retryable=terminal_error.retryable,
                provider_transcript=provider_transcript,
                runtime=runtime,
                attempt=attempt_index,
                qualification_observations=(
                    cast(Mapping[str, object], body["qualification_observations"])
                    if isinstance(body.get("qualification_observations"), dict)
                    else None
                ),
            )
        phase = "HOST_RUNTIME_IDENTITY"
        thread_id = body.get("thread_id")
        if runtime is None or not isinstance(thread_id, str):
            return failed(
                HarnessErrorKind.RUNTIME_MISMATCH,
                ValueError("SDK runtime identity or thread id is unavailable"),
                provider_transcript=provider_transcript,
                attempt=attempt_index,
            )
        phase = "HOST_EVENT_NORMALIZATION"
        try:
            provider_failure = normalize_provider_failure_events(
                provider_events, thread_id=thread_id, attempt=attempt_index
            )
            if provider_failure is not None:
                capture = capture_from_agent_events(
                    provider_failure.events,
                    max_bytes=request.max_normalized_transcript_bytes
                    or request.max_transcript_bytes,
                )
                return HarnessAttemptResult(
                    capture=capture,
                    runtime=runtime,
                    terminal_error=provider_failure.terminal_error,
                    provider_transcript=provider_transcript,
                    qualification_observations={
                        "host_process_exit": dict(process_exit),
                        "provider_failure": provider_failure.observation,
                        "host_transport": _host_transport_capture(
                            stdout,
                            stderr,
                            phase="HOST_PROVIDER_FAILURE_NORMALIZATION",
                            exception_class=None,
                            complete=complete,
                        ),
                    },
                )
            normalizer = (
                normalize_projected_provider_events
                if self._metadata_projection
                else normalize_provider_events
            )
            events = normalizer(provider_events, thread_id=thread_id, attempt=attempt_index)
            capture = capture_from_agent_events(
                events,
                max_bytes=request.max_normalized_transcript_bytes or request.max_transcript_bytes,
            )
        except (CodexEventNormalizationError, HarnessCaptureError, ValidationError) as error:
            return failed(
                HarnessErrorKind.PROTOCOL_UNSUPPORTED,
                error,
                provider_transcript=provider_transcript,
                runtime=runtime,
                attempt=attempt_index,
            )
        phase = "HOST_CAPTURE_VALIDATION"
        validation_error: tuple[HarnessErrorKind, str] | None = None
        if (
            not capture.turn_started
            or not capture.turn_completed
            or capture.turn_failed
            or not capture.agent_messages
        ):
            validation_error = (
                HarnessErrorKind.OUTPUT_INVALID,
                "normalized turn is incomplete or has no final Agent message",
            )
        elif capture.approval_requested:
            validation_error = (
                HarnessErrorKind.PERMISSION_DENIED,
                "provider requested approval under deny-all policy",
            )
        elif (
            capture.usage.get("input_tokens", 0) <= 0
            or capture.usage.get("input_tokens", 0) > request.max_input_tokens
            or capture.usage.get("output_tokens", 0) <= 0
            or capture.usage.get("output_tokens", 0) > request.max_output_tokens
        ):
            validation_error = (HarnessErrorKind.OUTPUT_INVALID, "usage is absent or over budget")
        if validation_error is not None:
            kind, message = validation_error
            return HarnessAttemptResult(
                capture=capture,
                runtime=runtime,
                terminal_error=HarnessTerminalError(
                    kind=kind, message_hash=sha256_bytes(message.encode("utf-8"))
                ),
                provider_transcript=provider_transcript,
                qualification_observations={
                    "host_process_exit": dict(process_exit),
                    "host_transport": _host_transport_capture(
                        stdout, stderr, phase=phase, exception_class=None, complete=complete
                    ),
                },
            )
        return HarnessAttemptResult(
            capture=capture,
            runtime=runtime,
            terminal_error=None,
            provider_transcript=provider_transcript,
            qualification_observations={
                **(
                    cast(Mapping[str, object], body["qualification_observations"])
                    if isinstance(body.get("qualification_observations"), dict)
                    else {}
                ),
                "host_process_exit": dict(process_exit),
            },
        )

    def _link_authentication(self, isolated_home: Path) -> None:
        source_home = self._authentication_home
        if source_home is None:
            configured = os.environ.get("CODEX_HOME")
            source_home = Path(configured) if configured else Path.home() / ".codex"
        source = source_home / "auth.json"
        if source.is_file() and not source.is_symlink():
            (isolated_home / "auth.json").symlink_to(source)

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.wait()

    @staticmethod
    def _provider_events(value: object) -> tuple[Mapping[str, object], ...] | None:
        if not isinstance(value, list):
            return None
        events: list[Mapping[str, object]] = []
        for event in cast(list[object], value):
            if not isinstance(event, dict):
                return None
            mapping = cast(Mapping[object, object], event)
            if not all(isinstance(key, str) for key in mapping):
                return None
            events.append(cast(Mapping[str, object], mapping))
        return tuple(events)

    @staticmethod
    def _terminal_error(value: object) -> HarnessTerminalError | None:
        if value is None:
            return None
        try:
            return HarnessTerminalError.model_validate(value)
        except ValidationError:
            return HarnessTerminalError(
                kind=HarnessErrorKind.OUTPUT_INVALID,
                message_hash=sha256_bytes(b"malformed SDK host error"),
            )

    @staticmethod
    def _runtime_identity(
        body: Mapping[str, object],
    ) -> HarnessRuntimeIdentity | HarnessRuntimeIdentityV2 | None:
        try:
            return HarnessRuntimeIdentityV2(
                sdk_version=cast(str, body["sdk_version"]),
                runtime_package_version=cast(str, body["runtime_package_version"]),
                runtime_version=cast(str, body["runtime_version"]),
                runtime_binary_hash=cast(str, body["runtime_binary_hash"]),
            )
        except (KeyError, ValidationError):
            return None

    @staticmethod
    def _failed_result(
        kind: HarnessErrorKind,
        error: BaseException | None,
        *,
        message_hash: str | None = None,
        retryable: bool = False,
        provider_transcript: bytes | None = None,
        runtime: HarnessRuntimeIdentity | HarnessRuntimeIdentityV2 | None = None,
        attempt: int = 1,
        qualification_observations: Mapping[str, object] | None = None,
    ) -> HarnessAttemptResult:
        digest = message_hash or sha256_bytes(
            f"{type(error).__name__}: {error}".encode("utf-8", errors="replace")
        )
        terminal = HarnessTerminalError(kind=kind, message_hash=digest, retryable=retryable)
        events = (
            make_agent_event(
                sequence=1,
                kind=AgentEventKind.ATTEMPT_STARTED,
                provider_event_type="quantos.attempt.started",
                payload={"attempt": attempt},
                attempt=attempt,
            ),
            make_agent_event(
                sequence=2,
                kind=AgentEventKind.HARNESS_ERROR,
                provider_event_type="quantos.harness.error",
                payload=terminal.canonical_payload(),
                attempt=attempt,
            ),
            make_agent_event(
                sequence=3,
                kind=AgentEventKind.ATTEMPT_FAILED,
                provider_event_type="quantos.attempt.failed",
                payload={"attempt": attempt, "error_kind": kind.value},
                attempt=attempt,
            ),
        )
        capture = capture_from_agent_events(events, max_bytes=1_000_000)
        return HarnessAttemptResult(
            capture=capture,
            runtime=runtime,
            terminal_error=terminal,
            provider_transcript=provider_transcript,
            qualification_observations=qualification_observations,
        )


def _contains_parent_secret(*payloads: bytes) -> bool:
    """Scan in memory without returning, logging, or persisting sensitive values."""

    markers = tuple(
        value.encode("utf-8")
        for name, value in os.environ.items()
        if value
        and (
            name in _SENSITIVE_PARENT_NAMES
            or any(name.startswith(prefix) for prefix in _SENSITIVE_PARENT_PREFIXES)
        )
    )
    return any(marker in payload for marker in markers for payload in payloads)


# Public in-memory check for producer capture persistence; never exposes values.
contains_parent_secret = _contains_parent_secret
