"""Process-isolated adapter for the optional official Codex Python SDK."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
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
    HarnessTerminalError,
)
from quantos.integrations.codex.event_normalizer import (
    CodexEventNormalizationError,
    normalize_provider_events,
)

_HOST_MODULE = "quantos.integrations.codex.sdk_host"
_SENSITIVE_PARENT_NAMES = frozenset({"P10_FORBIDDEN_SECRET"})
_SENSITIVE_PARENT_PREFIXES = ("TUSHARE_",)


class CodexSdkAdapter:
    """Execute one bounded request in a fresh process group and isolated config home."""

    def __init__(
        self,
        *,
        authentication_home: Path | None = None,
        host_argv: tuple[str, ...] | None = None,
    ) -> None:
        self._authentication_home = authentication_home
        self._host_argv = host_argv or (sys.executable, "-m", _HOST_MODULE)

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
        with tempfile.TemporaryDirectory(prefix="quantos-codex-sdk-") as temporary:
            isolated_home = Path(temporary)
            self._link_authentication(isolated_home)
            environment = {
                item.name: item.value for item in request.runtime_policy.host_environment
            }
            environment["CODEX_HOME"] = str(isolated_home)
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
            except OSError as error:
                return self._failed_result(
                    HarnessErrorKind.TRANSPORT_START_FAILED, error, attempt=attempt_index
                )
            try:
                stdout, stderr = process.communicate(
                    request.canonical_bytes(), timeout=timeout_seconds
                )
            except subprocess.TimeoutExpired as error:
                self._terminate_process_group(process)
                return self._failed_result(HarnessErrorKind.TIMEOUT, error, attempt=attempt_index)

        if _contains_parent_secret(stdout, stderr):
            return self._failed_result(
                HarnessErrorKind.PERMISSION_DENIED,
                ValueError("forbidden parent environment value observed in SDK host output"),
                attempt=attempt_index,
            )
        if process.returncode != 0:
            return self._failed_result(
                HarnessErrorKind.TRANSPORT_CLOSED,
                RuntimeError(
                    f"SDK host exited {process.returncode}; stderr={sha256_bytes(stderr)}"
                ),
                attempt=attempt_index,
            )
        if len(stdout) > request.max_transcript_bytes + 1_000_000:
            return self._failed_result(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host response exceeds its bound"),
                attempt=attempt_index,
            )
        try:
            response = cast(object, json.loads(stdout))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return self._failed_result(
                HarnessErrorKind.OUTPUT_INVALID, error, attempt=attempt_index
            )
        if not isinstance(response, dict):
            return self._failed_result(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host response is not an object"),
                attempt=attempt_index,
            )
        body = cast(Mapping[str, object], response)
        terminal_error = self._terminal_error(body.get("error"))
        provider_events = self._provider_events(body.get("provider_events"))
        if provider_events is None:
            return self._failed_result(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("SDK host provider events are malformed"),
                attempt=attempt_index,
            )
        provider_transcript = b"".join(
            canonical_json_bytes(event) + b"\n" for event in provider_events
        )
        if len(provider_transcript) > request.max_transcript_bytes:
            return self._failed_result(
                HarnessErrorKind.OUTPUT_INVALID,
                ValueError("provider transcript exceeds its bound"),
                attempt=attempt_index,
            )
        runtime = self._runtime_identity(body)
        if terminal_error is not None:
            return self._failed_result(
                terminal_error.kind,
                None,
                message_hash=terminal_error.message_hash,
                retryable=terminal_error.retryable,
                provider_transcript=provider_transcript,
                runtime=runtime,
                attempt=attempt_index,
            )
        thread_id = body.get("thread_id")
        if runtime is None or not isinstance(thread_id, str):
            return self._failed_result(
                HarnessErrorKind.RUNTIME_MISMATCH,
                ValueError("SDK runtime identity or thread id is unavailable"),
                provider_transcript=provider_transcript,
                attempt=attempt_index,
            )
        try:
            events = normalize_provider_events(
                provider_events, thread_id=thread_id, attempt=attempt_index
            )
            capture = capture_from_agent_events(events, max_bytes=request.max_transcript_bytes)
        except (CodexEventNormalizationError, HarnessCaptureError, ValidationError) as error:
            return self._failed_result(
                HarnessErrorKind.PROTOCOL_UNSUPPORTED,
                error,
                provider_transcript=provider_transcript,
                runtime=runtime,
                attempt=attempt_index,
            )
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
            )
        return HarnessAttemptResult(
            capture=capture,
            runtime=runtime,
            terminal_error=None,
            provider_transcript=provider_transcript,
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
    def _runtime_identity(body: Mapping[str, object]) -> HarnessRuntimeIdentity | None:
        try:
            return HarnessRuntimeIdentity(
                sdk_version=cast(str, body["sdk_version"]),
                runtime_version=cast(str, body["runtime_version"]),
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
        runtime: HarnessRuntimeIdentity | None = None,
        attempt: int = 1,
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
