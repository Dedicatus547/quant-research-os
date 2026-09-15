"""Isolated process entry point for the optional official Codex Python SDK."""

from __future__ import annotations

import json
import sys
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import HarnessErrorKind, HarnessExecutionRequest

MAX_HOST_REQUEST_BYTES = 1_000_000


def _sdk_config(request: HarnessExecutionRequest) -> dict[str, object]:
    policy = request.runtime_policy
    servers: dict[str, object] = {}
    for server in request.mcp_servers:
        servers[server.name] = {
            "args": list(server.args),
            "command": server.command,
            "enabled_tools": list(server.enabled_tools),
            "required": server.required,
        }
    return {
        "allow_login_shell": policy.login_shell_allowed,
        "features": {"shell_tool": policy.shell_tool_enabled},
        "history": {"persistence": policy.history_persistence},
        "mcp_servers": servers,
        "model_reasoning_effort": request.reasoning_effort,
        "shell_environment_policy": {
            "inherit": "none",
            "set": {item.name: item.value for item in policy.shell_environment},
        },
    }


def _provider_event(method: str, payload: object) -> dict[str, object]:
    if isinstance(payload, BaseModel):
        body = cast(dict[str, object], payload.model_dump(mode="json", by_alias=False))
    else:
        params = getattr(payload, "params", None)
        if not isinstance(params, dict):
            raise ValueError("SDK returned an unsupported notification payload")
        body = cast(dict[str, object], params)
    return {"method": method, "payload": body}


def _error_kind(error: BaseException) -> tuple[HarnessErrorKind, bool]:
    try:
        from openai_codex import (
            InternalRpcError,
            InvalidParamsError,
            InvalidRequestError,
            MethodNotFoundError,
            ParseError,
            ServerBusyError,
            TransportClosedError,
        )
    except ImportError:
        return HarnessErrorKind.RUNTIME_MISMATCH, False
    if isinstance(error, ServerBusyError):
        return HarnessErrorKind.OVERLOADED, True
    if isinstance(error, TransportClosedError):
        return HarnessErrorKind.TRANSPORT_CLOSED, False
    if isinstance(error, MethodNotFoundError):
        return HarnessErrorKind.PROTOCOL_UNSUPPORTED, False
    if isinstance(error, ParseError):
        return HarnessErrorKind.OUTPUT_INVALID, False
    if isinstance(error, InternalRpcError):
        return HarnessErrorKind.TRANSPORT_CLOSED, False
    if isinstance(error, (InvalidParamsError, InvalidRequestError, ValidationError, ValueError)):
        return HarnessErrorKind.CONFIGURATION_INVALID, False
    return HarnessErrorKind.UNKNOWN, False


def execute(request: HarnessExecutionRequest) -> dict[str, object]:
    try:
        import openai_codex
        from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox
        from openai_codex.generated.v2_all import ReasoningEffort
        from openai_codex.models import JsonObject
    except ImportError as error:
        return _failure(HarnessErrorKind.RUNTIME_MISMATCH, error, retryable=False)

    provider_events: list[dict[str, object]] = []
    try:
        child_environment = {
            item.name: item.value for item in request.runtime_policy.child_environment
        }
        with Codex(CodexConfig(cwd=request.cwd, env=child_environment)) as codex:
            account = codex.account(refresh_token=False)
            if account.account is None:
                return _failure(
                    HarnessErrorKind.AUTH_UNAVAILABLE,
                    RuntimeError("pre-existing Codex authentication is unavailable"),
                    retryable=False,
                )
            server_info = codex.metadata.serverInfo
            runtime_version = server_info.version if server_info is not None else None
            if not runtime_version:
                return _failure(
                    HarnessErrorKind.RUNTIME_MISMATCH,
                    RuntimeError("Codex runtime version is unavailable"),
                    retryable=False,
                )
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                config=cast(Any, _sdk_config(request)),
                cwd=request.cwd,
                ephemeral=True,
                model=request.model,
                sandbox=Sandbox.read_only,
            )
            output_schema = (
                cast(JsonObject, json.loads(request.output_schema_json))
                if request.output_schema_json is not None
                else None
            )
            handle = thread.turn(
                request.prompt,
                approval_mode=ApprovalMode.deny_all,
                cwd=request.cwd,
                effort=ReasoningEffort(request.reasoning_effort),
                output_schema=output_schema,
                sandbox=Sandbox.read_only,
            )
            for notification in handle.stream():
                provider_events.append(_provider_event(notification.method, notification.payload))
                if len(canonical_json_bytes(provider_events)) > request.max_transcript_bytes:
                    handle.interrupt()
                    raise ValueError("provider transcript exceeds its bound")
        return {
            "provider_events": provider_events,
            "runtime_version": runtime_version,
            "sdk_version": openai_codex.__version__,
            "thread_id": thread.id,
        }
    except BaseException as error:
        kind, retryable = _error_kind(error)
        return _failure(kind, error, retryable=retryable, provider_events=provider_events)


def _failure(
    kind: HarnessErrorKind,
    error: BaseException,
    *,
    retryable: bool,
    provider_events: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    message = f"{type(error).__name__}: {error}"
    return {
        "error": {
            "kind": kind.value,
            "message_hash": sha256_bytes(message.encode("utf-8", errors="replace")),
            "retryable": retryable,
        },
        "provider_events": provider_events or [],
    }


def main() -> None:
    payload = sys.stdin.buffer.read(MAX_HOST_REQUEST_BYTES + 1)
    if not payload or len(payload) > MAX_HOST_REQUEST_BYTES:
        response = _failure(
            HarnessErrorKind.CONFIGURATION_INVALID,
            ValueError("host request is empty or oversized"),
            retryable=False,
        )
    else:
        try:
            request = HarnessExecutionRequest.model_validate_json(payload)
        except ValidationError as error:
            response = _failure(
                HarnessErrorKind.CONFIGURATION_INVALID,
                error,
                retryable=False,
            )
        else:
            response = execute(request)
    sys.stdout.buffer.write(canonical_json_bytes(response))


if __name__ == "__main__":
    main()
