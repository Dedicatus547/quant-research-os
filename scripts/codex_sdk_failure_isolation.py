#!/usr/bin/env python3
"""Run non-canonical Codex SDK D0, app-server D0.5, and raw-thread D0.6 diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from quantos.application.agent_harness import serialize_agent_events
from quantos.artifacts.store import (
    atomic_write_bytes,
    confined_regular_file,
    publish_directory,
    regular_tree_files,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.event_normalizer import normalize_provider_events
from quantos.integrations.codex.sdk_host import _provider_event, _sha256_file
from quantos.integrations.codex.versioning import (
    CODEX_PROTOCOL_IDENTIFIER,
    CODEX_RUNTIME_DISTRIBUTION,
    CODEX_RUNTIME_PACKAGE_VERSION,
    CODEX_SDK_DISTRIBUTION,
    CODEX_SDK_VERSION,
)

MODEL_IDENTIFIER = "gpt-5.6-sol"
MODEL_REASONING_EFFORT = "medium"
PINNED_SDK_VERSION = CODEX_SDK_VERSION
PINNED_RUNTIME_PACKAGE_VERSION = CODEX_RUNTIME_PACKAGE_VERSION
PROMPT = (
    "Run /usr/bin/pwd as a shell command.\n"
    "After the command completes, report the exact working directory.\n"
    "Do not answer without executing the command."
)
MAX_PROVIDER_TRANSCRIPT_BYTES = 1_000_000
MAX_JSON_RPC_LINE_BYTES = 256_000
MAX_STDERR_BYTES = 64_000
DEFAULT_TIMEOUT_SECONDS = 90
COMMAND_EXEC_TIMEOUT_MS = 10_000
RAW_LIMITATIONS = (
    "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
    "INDEPENDENT_MODEL_CALLS_NOT_CAUSAL_PROOF",
    "MODEL_IDENTIFIER_NOT_IMMUTABLE",
)
RAW_SENTINELS = {
    "binary": "<BUNDLED_BINARY>",
    "codex_home": "<TEMP_CODEX_HOME>",
    "path_dir": "<BUNDLED_PATH_DIR>",
    "request_id": "<REQUEST_ID>",
    "thread_id": "<THREAD_ID>",
    "workspace": "<TEMP_WORKSPACE>",
}
PROHIBITED_OUTPUT_PATTERN = re.compile(
    rb'TUSHARE_|P10_FORBIDDEN_SECRET|"(?:access[_-]?token|refresh[_-]?token)"\s*:\s*"[^\"]+"',
    re.IGNORECASE,
)
VARIANTS = (
    "default",
    "shell-on-unified-default",
    "shell-on-unified-off",
    "shell-off",
)
POSITIVE_VARIANTS = VARIANTS[:-1]
NEGATIVE_VARIANT = "shell-off"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@contextmanager
def _deadline(seconds: int) -> Iterator[None]:
    def timeout_handler(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"Codex diagnostic exceeded {seconds} seconds")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def _config(variant: str) -> dict[str, object]:
    config: dict[str, object] = {
        "allow_login_shell": False,
        "history": {"persistence": "none"},
        "shell_environment_policy": {
            "inherit": "none",
            "set": {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"},
        },
    }
    if variant == "shell-on-unified-default":
        config["features"] = {"shell_tool": True}
    elif variant == "shell-on-unified-off":
        config["features"] = {"shell_tool": True, "unified_exec": False}
    elif variant == "shell-off":
        config["features"] = {"shell_tool": False}
    elif variant != "default":
        raise ValueError(f"unsupported diagnostic variant: {variant}")
    return config


def _summarize(
    events: list[dict[str, object]],
    *,
    sdk_version: str,
    runtime_package_version: str,
    runtime_version: str | None,
    runtime_binary_hash: str,
    variant: str,
    config_hash: str,
) -> dict[str, object]:
    methods: list[str] = []
    item_types: list[str] = []
    command_count = 0
    turn_status: str | None = None
    usage: dict[str, int] = {}
    thread_id: str | None = None
    for event in events:
        method = event.get("method")
        payload = event.get("payload")
        if isinstance(method, str):
            methods.append(method)
        if not isinstance(payload, dict):
            continue
        candidate_thread = payload.get("thread_id")
        if isinstance(candidate_thread, str):
            thread_id = candidate_thread
        item = payload.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if isinstance(item_type, str):
                item_types.append(item_type)
                if method == "item/started" and item_type == "commandExecution":
                    command_count += 1
        turn = payload.get("turn")
        if isinstance(turn, dict) and isinstance(turn.get("status"), str):
            turn_status = cast(str, turn["status"])
        token_usage = payload.get("token_usage")
        if isinstance(token_usage, dict) and isinstance(token_usage.get("last"), dict):
            last = cast(dict[str, object], token_usage["last"])
            usage = {
                key: value
                for key in ("cached_input_tokens", "input_tokens", "output_tokens")
                if isinstance((value := last.get(key)), int)
            }
    return {
        "schema_version": "codex-sdk-failure-isolation-result/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "variant": variant,
        "sdk_version": sdk_version,
        "runtime_package_version": runtime_package_version,
        "runtime_version": runtime_version,
        "runtime_binary_hash": runtime_binary_hash,
        "requested_config_hash": config_hash,
        "prompt_hash": sha256_bytes(PROMPT.encode("utf-8")),
        "thread_id": thread_id,
        "instruction_sources": None,
        "provider_event_methods": sorted(set(methods)),
        "observed_item_types": sorted(set(item_types)),
        "command_count": command_count,
        "turn_status": turn_status,
        "usage": usage,
        "decision": "SHELL_OBSERVED" if command_count else "SHELL_NOT_OBSERVED",
        "limitations": [
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "HIGH_LEVEL_SDK_THREAD_START_METADATA_UNAVAILABLE",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
        ],
    }


def _classify_matrix(results: Sequence[dict[str, object]]) -> str:
    by_variant = {str(result.get("variant")): result for result in results}
    if set(by_variant) != set(VARIANTS) or len(results) != len(VARIANTS):
        raise ValueError("diagnostic matrix must contain every variant exactly once")
    if any(
        result.get("decision") == "DIAGNOSTIC_FAILED" or result.get("turn_status") != "completed"
        for result in results
    ):
        return "DIAGNOSTIC_FAILED"
    for result in results:
        command_count = result.get("command_count")
        if (
            not isinstance(command_count, int)
            or isinstance(command_count, bool)
            or command_count < 0
            or result.get("decision")
            != ("SHELL_OBSERVED" if command_count > 0 else "SHELL_NOT_OBSERVED")
        ):
            return "DIAGNOSTIC_FAILED"
    identities = {
        (
            result.get("sdk_version"),
            result.get("runtime_package_version"),
            result.get("runtime_version"),
            result.get("runtime_binary_hash"),
        )
        for result in results
    }
    if len(identities) != 1:
        return "RUNTIME_MISMATCH"
    negative_count = by_variant[NEGATIVE_VARIANT].get("command_count")
    if not isinstance(negative_count, int):
        return "DIAGNOSTIC_FAILED"
    if negative_count > 0:
        return "NEGATIVE_CONTROL_FAILED"
    positive_counts = [by_variant[variant].get("command_count") for variant in POSITIVE_VARIANTS]
    if not all(isinstance(value, int) for value in positive_counts):
        return "DIAGNOSTIC_FAILED"
    if all(value > 0 for value in positive_counts if isinstance(value, int)):
        return "SHELL_SURFACE_AVAILABLE"
    if all(value == 0 for value in positive_counts):
        return "OBSERVABILITY_GAP"
    return "VARIANT_DEPENDENT"


def _canonical_object(payload: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise RuntimeError(f"{label} is not a canonical JSON object")
    return cast(dict[str, object], value)


def _canonical_jsonl_objects(payload: bytes, *, label: str) -> list[dict[str, object]]:
    if not payload:
        return []
    if not payload.endswith(b"\n"):
        raise RuntimeError(f"{label} does not end with a newline")
    values: list[dict[str, object]] = []
    for line in payload.splitlines(keepends=True):
        body = line[:-1]
        value = _canonical_object(body, label=label)
        if canonical_json_bytes(value) + b"\n" != line:
            raise RuntimeError(f"{label} contains a non-canonical line")
        values.append(value)
    return values


def verify_matrix(
    matrix_path: Path, *, expected_sdk_version: str = PINNED_SDK_VERSION
) -> dict[str, object]:
    if {str(path.relative_to(matrix_path)) for path in regular_tree_files(matrix_path)} != {
        "matrix.json"
    }:
        raise RuntimeError("diagnostic matrix file set is invalid")
    matrix_bytes = confined_regular_file(matrix_path, "matrix.json").read_bytes()
    matrix_hash = sha256_bytes(matrix_bytes)
    if matrix_path.name != f"matrix-sha256-{matrix_hash}":
        raise RuntimeError("diagnostic matrix path does not match its content hash")
    matrix = _canonical_object(matrix_bytes, label="diagnostic matrix")
    if (
        matrix.get("schema_version") != "codex-sdk-failure-isolation-matrix/v1"
        or matrix.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
        or set(matrix)
        != {
            "authority",
            "classification",
            "eligible_for_p10",
            "runtime_binary_hash",
            "runtime_package_version",
            "runtime_version",
            "schema_version",
            "sdk_version",
            "variants",
        }
    ):
        raise RuntimeError("diagnostic matrix identity is invalid")
    variants = matrix.get("variants")
    if not isinstance(variants, list) or len(variants) != len(VARIANTS):
        raise RuntimeError("diagnostic matrix variant set is invalid")
    results: list[dict[str, object]] = []
    for expected_variant, entry_value in zip(VARIANTS, variants, strict=True):
        if not isinstance(entry_value, dict):
            raise RuntimeError("diagnostic matrix entry is invalid")
        entry = cast(dict[str, object], entry_value)
        bundle_hash = entry.get("bundle_hash")
        result_hash = entry.get("result_hash")
        if (
            entry.get("variant") != expected_variant
            or set(entry)
            != {
                "bundle_hash",
                "command_count",
                "decision",
                "result_hash",
                "turn_status",
                "variant",
            }
            or not isinstance(bundle_hash, str)
            or SHA256_PATTERN.fullmatch(bundle_hash) is None
            or not isinstance(result_hash, str)
            or SHA256_PATTERN.fullmatch(result_hash) is None
        ):
            raise RuntimeError("diagnostic matrix entry binding is invalid")
        bundle_path = matrix_path.parent / f"sha256-{bundle_hash}"
        manifest_bytes = confined_regular_file(bundle_path, "diagnostic-manifest.json").read_bytes()
        if sha256_bytes(manifest_bytes) != bundle_hash:
            raise RuntimeError("diagnostic bundle path does not match its manifest hash")
        manifest = _canonical_object(manifest_bytes, label="diagnostic bundle manifest")
        files_value = manifest.get("files")
        if (
            manifest.get("schema_version") != "codex-sdk-diagnostic-manifest/v1"
            or manifest.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
            or set(manifest) != {"authority", "files", "schema_version"}
            or not isinstance(files_value, dict)
        ):
            raise RuntimeError("diagnostic bundle manifest is invalid")
        files = cast(dict[str, object], files_value)
        required_files = {
            "provider-events.jsonl",
            "requested-config.json",
            "result.json",
            "runtime-identity.json",
        }
        allowed_file_sets = (
            required_files,
            required_files | {"normalized-events.jsonl"},
        )
        if set(files) not in allowed_file_sets:
            raise RuntimeError("diagnostic bundle manifest file set is invalid")
        actual_names = {
            str(path.relative_to(bundle_path)) for path in regular_tree_files(bundle_path)
        }
        if actual_names != {*files, "diagnostic-manifest.json"}:
            raise RuntimeError("diagnostic bundle file set is invalid")
        for name, expected_hash in files.items():
            if (
                not isinstance(expected_hash, str)
                or SHA256_PATTERN.fullmatch(expected_hash) is None
                or _sha256_file(confined_regular_file(bundle_path, name)) != expected_hash
            ):
                raise RuntimeError("diagnostic bundle file hash is invalid")
        result_bytes = confined_regular_file(bundle_path, "result.json").read_bytes()
        if sha256_bytes(result_bytes) != result_hash:
            raise RuntimeError("diagnostic matrix result hash is invalid")
        result = _canonical_object(result_bytes, label="diagnostic result")
        if (
            result.get("schema_version") != "codex-sdk-failure-isolation-result/v1"
            or result.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
            or any(
                entry.get(field) != result.get(field)
                for field in ("command_count", "decision", "turn_status", "variant")
            )
        ):
            raise RuntimeError("diagnostic matrix result summary is invalid")

        config_bytes = confined_regular_file(bundle_path, "requested-config.json").read_bytes()
        config = _canonical_object(config_bytes, label="diagnostic requested config")
        config_hash = sha256_bytes(config_bytes)
        if (
            config != _config(expected_variant)
            or result.get("requested_config_hash") != config_hash
        ):
            raise RuntimeError("diagnostic requested config binding is invalid")

        runtime_identity = _canonical_object(
            confined_regular_file(bundle_path, "runtime-identity.json").read_bytes(),
            label="diagnostic runtime identity",
        )
        runtime_binary_hash = result.get("runtime_binary_hash")
        if (
            set(runtime_identity)
            != {
                "protocol_identifier",
                "runtime_binary_hash",
                "runtime_distribution",
                "runtime_package_version",
                "runtime_version",
                "schema_version",
                "sdk_distribution",
                "sdk_version",
            }
            or runtime_identity.get("schema_version") != "codex-sdk-diagnostic-runtime-identity/v1"
            or runtime_identity.get("sdk_distribution") != CODEX_SDK_DISTRIBUTION
            or runtime_identity.get("sdk_version") != result.get("sdk_version")
            or runtime_identity.get("runtime_distribution") != CODEX_RUNTIME_DISTRIBUTION
            or runtime_identity.get("runtime_package_version")
            != result.get("runtime_package_version")
            or runtime_identity.get("runtime_version") != result.get("runtime_version")
            or runtime_identity.get("runtime_binary_hash") != runtime_binary_hash
            or runtime_identity.get("protocol_identifier") != CODEX_PROTOCOL_IDENTIFIER
            or result.get("sdk_version") != expected_sdk_version
            or result.get("runtime_package_version") != expected_sdk_version
            or not isinstance(runtime_binary_hash, str)
            or SHA256_PATTERN.fullmatch(runtime_binary_hash) is None
        ):
            raise RuntimeError("diagnostic runtime identity binding is invalid")

        provider_bytes = confined_regular_file(bundle_path, "provider-events.jsonl").read_bytes()
        provider_events = _canonical_jsonl_objects(
            provider_bytes, label="diagnostic provider transcript"
        )
        recomputed = _summarize(
            provider_events,
            sdk_version=cast(str, result["sdk_version"]),
            runtime_package_version=cast(str, result["runtime_package_version"]),
            runtime_version=cast(str | None, result.get("runtime_version")),
            runtime_binary_hash=runtime_binary_hash,
            variant=expected_variant,
            config_hash=config_hash,
        )
        summary_fields = set(recomputed) - {"decision"}
        if any(result.get(field) != recomputed[field] for field in summary_fields):
            raise RuntimeError("diagnostic raw provider summary binding is invalid")
        if result.get("decision") != "DIAGNOSTIC_FAILED" and (
            result.get("decision") != recomputed["decision"]
            or "terminal_error_kind" in result
            or "terminal_error_message_hash" in result
        ):
            raise RuntimeError("diagnostic result decision is invalid")
        if result.get("decision") == "DIAGNOSTIC_FAILED" and (
            not isinstance(result.get("terminal_error_kind"), str)
            or not isinstance(result.get("terminal_error_message_hash"), str)
            or SHA256_PATTERN.fullmatch(cast(str, result["terminal_error_message_hash"])) is None
        ):
            raise RuntimeError("diagnostic failure evidence is invalid")

        normalized_name = "normalized-events.jsonl"
        thread_id = result.get("thread_id")
        if normalized_name in files:
            if not isinstance(thread_id, str):
                raise RuntimeError("normalized transcript has no provider thread binding")
            expected_normalized = serialize_agent_events(
                normalize_provider_events(provider_events, thread_id=thread_id)
            )
            if (
                confined_regular_file(bundle_path, normalized_name).read_bytes()
                != expected_normalized
            ):
                raise RuntimeError("diagnostic normalized transcript binding is invalid")
        elif isinstance(thread_id, str):
            try:
                normalize_provider_events(provider_events, thread_id=thread_id)
            except ValueError as error:
                expected_error_hash = sha256_bytes(
                    f"{type(error).__name__}: {error}".encode("utf-8", errors="replace")
                )
                if result.get("normalizer_error_hash") != expected_error_hash:
                    raise RuntimeError(
                        "diagnostic normalizer failure binding is invalid"
                    ) from error
            else:
                raise RuntimeError("diagnostic normalized transcript is missing")
        results.append(result)
    classification = _classify_matrix(results)
    first = results[0]
    if (
        matrix.get("classification") != classification
        or matrix.get("eligible_for_p10") != (classification == "SHELL_SURFACE_AVAILABLE")
        or matrix.get("sdk_version") != first.get("sdk_version")
        or matrix.get("runtime_package_version") != first.get("runtime_package_version")
        or matrix.get("runtime_version") != first.get("runtime_version")
        or matrix.get("runtime_binary_hash") != first.get("runtime_binary_hash")
    ):
        raise RuntimeError("diagnostic matrix conclusion is invalid")
    return matrix


def _publish(
    output_root: Path,
    *,
    events: list[dict[str, object]],
    config: dict[str, object],
    result: dict[str, object],
    normalized_transcript: bytes | None,
) -> Path:
    provider_transcript = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    runtime_identity = {
        "schema_version": "codex-sdk-diagnostic-runtime-identity/v1",
        "sdk_distribution": CODEX_SDK_DISTRIBUTION,
        "sdk_version": result["sdk_version"],
        "runtime_distribution": CODEX_RUNTIME_DISTRIBUTION,
        "runtime_package_version": result["runtime_package_version"],
        "runtime_version": result["runtime_version"],
        "runtime_binary_hash": result["runtime_binary_hash"],
        "protocol_identifier": CODEX_PROTOCOL_IDENTIFIER,
    }
    files = {
        "provider-events.jsonl": provider_transcript,
        "requested-config.json": canonical_json_bytes(config),
        "result.json": canonical_json_bytes(result),
        "runtime-identity.json": canonical_json_bytes(runtime_identity),
    }
    if normalized_transcript is not None:
        files["normalized-events.jsonl"] = normalized_transcript
    manifest = {
        "schema_version": "codex-sdk-diagnostic-manifest/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "files": {name: sha256_bytes(payload) for name, payload in sorted(files.items())},
    }
    manifest_bytes = canonical_json_bytes(manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codex-d0-", dir=output_root) as temporary:
        staging = Path(temporary) / "published"
        staging.mkdir()
        for name, payload in files.items():
            atomic_write_bytes(staging / name, payload)
        atomic_write_bytes(staging / "diagnostic-manifest.json", manifest_bytes)
        destination = output_root / f"sha256-{sha256_bytes(manifest_bytes)}"
        publish_directory(staging, destination)
    return destination


def run_diagnostic(
    *,
    variant: str,
    output_root: Path,
    authentication_home: Path,
    expected_sdk_version: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, object]]:
    source_auth = authentication_home / "auth.json"
    if source_auth.is_symlink() or not source_auth.is_file():
        raise RuntimeError("a regular pre-existing Codex auth.json is required")
    with (
        tempfile.TemporaryDirectory(prefix="quantos-codex-d0-workspace-", dir="/tmp") as cwd,
        tempfile.TemporaryDirectory(prefix="quantos-codex-d0-home-", dir="/tmp") as codex_home,
    ):
        isolated_home = Path(codex_home)
        (isolated_home / "auth.json").symlink_to(source_auth)
        os.environ.clear()
        os.environ.update(
            {
                "CODEX_HOME": codex_home,
                "LANG": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "TZ": "UTC",
            }
        )
        import openai_codex
        from codex_cli_bin import bundled_codex_path
        from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox
        from openai_codex.generated.v2_all import ReasoningEffort

        if openai_codex.__version__ != expected_sdk_version:
            raise RuntimeError(
                f"expected openai-codex {expected_sdk_version}, got {openai_codex.__version__}"
            )
        runtime_package_version = version(CODEX_RUNTIME_DISTRIBUTION)
        if runtime_package_version != expected_sdk_version:
            raise RuntimeError(
                "installed bundled Codex runtime package does not match the expected version"
            )
        config = _config(variant)
        events: list[dict[str, object]] = []
        runtime_binary_hash = _sha256_file(Path(bundled_codex_path()))
        runtime_version: str | None = None
        terminal_error: BaseException | None = None
        try:
            with (
                _deadline(timeout_seconds),
                Codex(
                    CodexConfig(
                        cwd=cwd,
                        env={
                            "CODEX_HOME": codex_home,
                            "LANG": "C.UTF-8",
                            "PATH": "/usr/bin:/bin",
                            "TZ": "UTC",
                        },
                    )
                ) as codex,
            ):
                account = codex.account(refresh_token=False)
                if account.account is None:
                    raise RuntimeError("pre-existing Codex authentication is unavailable")
                server_info = codex.metadata.serverInfo
                runtime_version = server_info.version if server_info is not None else None
                if not runtime_version:
                    raise RuntimeError("Codex runtime version is unavailable")
                if runtime_version.partition(" ")[0] != expected_sdk_version:
                    raise RuntimeError("reported Codex runtime version does not match expectation")
                thread = codex.thread_start(
                    approval_mode=ApprovalMode.deny_all,
                    config=cast(Any, config),
                    cwd=cwd,
                    ephemeral=True,
                    model=MODEL_IDENTIFIER,
                    sandbox=Sandbox.read_only,
                )
                handle = thread.turn(
                    PROMPT,
                    approval_mode=ApprovalMode.deny_all,
                    cwd=cwd,
                    effort=ReasoningEffort(MODEL_REASONING_EFFORT),
                    sandbox=Sandbox.read_only,
                )
                for notification in handle.stream():
                    events.append(_provider_event(notification.method, notification.payload))
                    if len(canonical_json_bytes(events)) > MAX_PROVIDER_TRANSCRIPT_BYTES:
                        handle.interrupt()
                        raise RuntimeError("diagnostic provider transcript exceeded its bound")
        except Exception as error:
            terminal_error = error
        config_hash = sha256_bytes(canonical_json_bytes(config))
        result = _summarize(
            events,
            sdk_version=openai_codex.__version__,
            runtime_package_version=runtime_package_version,
            runtime_version=runtime_version,
            runtime_binary_hash=runtime_binary_hash,
            variant=variant,
            config_hash=config_hash,
        )
        if terminal_error is not None:
            result["decision"] = "DIAGNOSTIC_FAILED"
            result["terminal_error_kind"] = type(terminal_error).__name__
            result["terminal_error_message_hash"] = sha256_bytes(
                str(terminal_error).encode("utf-8", errors="replace")
            )
        normalized_transcript: bytes | None = None
        thread_id = result["thread_id"]
        if isinstance(thread_id, str):
            try:
                normalized_transcript = serialize_agent_events(
                    normalize_provider_events(events, thread_id=thread_id)
                )
            except ValueError as error:
                result["normalizer_error_hash"] = sha256_bytes(
                    f"{type(error).__name__}: {error}".encode("utf-8", errors="replace")
                )
        destination = _publish(
            output_root,
            events=events,
            config=config,
            result=result,
            normalized_transcript=normalized_transcript,
        )
        return destination, result


def run_command_exec_probe(
    *,
    output_root: Path,
    expected_sdk_version: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, object]]:
    """Run D0.5 directly against app-server without a model thread or SDK adapter."""
    import openai_codex
    from codex_cli_bin import bundled_codex_path
    from openai_codex.client import CodexClient, CodexConfig
    from openai_codex.generated.v2_all import CommandExecResponse

    if openai_codex.__version__ != expected_sdk_version:
        raise RuntimeError(
            f"expected openai-codex {expected_sdk_version}, got {openai_codex.__version__}"
        )
    runtime_package_version = version(CODEX_RUNTIME_DISTRIBUTION)
    if runtime_package_version != expected_sdk_version:
        raise RuntimeError(
            "installed bundled Codex runtime package does not match the expected version"
        )
    runtime_path = Path(bundled_codex_path())
    runtime_binary_hash = _sha256_file(runtime_path)
    with (
        tempfile.TemporaryDirectory(prefix="quantos-codex-d05-workspace-", dir="/tmp") as cwd,
        tempfile.TemporaryDirectory(prefix="quantos-codex-d05-home-", dir="/tmp") as codex_home,
    ):
        requests = [
            {
                "id": 0,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "quantos_d0_5",
                        "title": "QuantOS D0.5",
                        "version": "1.0.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"method": "initialized", "params": {}},
            {
                "id": 1,
                "method": "command/exec",
                "params": {
                    "command": ["/usr/bin/pwd"],
                    "cwd": cwd,
                    "sandboxPolicy": {
                        "type": "externalSandbox",
                        "networkAccess": "restricted",
                    },
                    "timeoutMs": COMMAND_EXEC_TIMEOUT_MS,
                },
            },
        ]
        request_bytes = b"".join(canonical_json_bytes(item) + b"\n" for item in requests)
        client = CodexClient(
            CodexConfig(
                client_name="quantos_d0_5",
                client_title="QuantOS D0.5",
                client_version="1.0.0",
                cwd=cwd,
                env={
                    "CODEX_HOME": codex_home,
                    "LANG": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "TZ": "UTC",
                },
            )
        )
        try:
            with _deadline(timeout_seconds):
                client.start()
                initialization = client.initialize()
                command = client.request(
                    "command/exec",
                    cast(Any, requests[2]["params"]),
                    response_model=CommandExecResponse,
                )
        finally:
            client.close()
        initialize_result = cast(
            dict[str, object], initialization.model_dump(mode="json", by_alias=True)
        )
        command_result = cast(dict[str, object], command.model_dump(mode="json", by_alias=True))
        responses = [{"id": 0, "result": initialize_result}, {"id": 1, "result": command_result}]
        user_agent = initialization.userAgent
        runtime_version = None
        if isinstance(user_agent, str):
            reported_version = user_agent.partition("/")[2].partition(" ")[0]
            runtime_version = reported_version or None
        command_stdout = command_result.get("stdout")
        command_stderr = command_result.get("stderr")
        command_exit_code = command_result.get("exitCode")
        succeeded = command_exit_code == 0 and command_stdout == f"{cwd}\n" and command_stderr == ""
        result = {
            "schema_version": "codex-app-server-command-exec-result/v1",
            "authority": "NON_CANONICAL_DIAGNOSTIC",
            "probe": "D0.5_COMMAND_EXEC",
            "sdk_version": openai_codex.__version__,
            "runtime_package_version": runtime_package_version,
            "runtime_version": runtime_version,
            "runtime_binary_hash": runtime_binary_hash,
            "app_server_user_agent": user_agent,
            "initialize_succeeded": True,
            "command_exit_code": command_exit_code,
            "command_stdout_matches_cwd": command_stdout == f"{cwd}\n",
            "command_stderr_empty": command_stderr == "",
            "decision": "COMMAND_EXEC_AVAILABLE" if succeeded else "COMMAND_EXEC_FAILED",
        }
        files = {
            "requests.jsonl": request_bytes,
            "responses.jsonl": b"".join(canonical_json_bytes(item) + b"\n" for item in responses),
            "result.json": canonical_json_bytes(result),
        }
        manifest = {
            "schema_version": "codex-app-server-command-exec-manifest/v1",
            "authority": "NON_CANONICAL_DIAGNOSTIC",
            "files": {name: sha256_bytes(payload) for name, payload in sorted(files.items())},
        }
        manifest_bytes = canonical_json_bytes(manifest)
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".codex-d05-", dir=output_root) as temporary:
            staging = Path(temporary) / "published"
            staging.mkdir()
            for name, payload in files.items():
                atomic_write_bytes(staging / name, payload)
            atomic_write_bytes(staging / "diagnostic-manifest.json", manifest_bytes)
            destination = output_root / f"sha256-{sha256_bytes(manifest_bytes)}"
            publish_directory(staging, destination)
        return destination, result


def _wire_dict(value: object) -> dict[str, object]:
    if not hasattr(value, "model_dump"):
        raise TypeError("captured SDK params are not serializable")
    payload = value.model_dump(by_alias=True, exclude_none=True, mode="json")
    if not isinstance(payload, dict):
        raise TypeError("captured SDK params must serialize to an object")
    return cast(dict[str, object], payload)


def _build_raw_wire_fixture(variant: str, *, expected_sdk_version: str) -> dict[str, object]:
    """Capture final high-level SDK params without launching app-server or reading auth."""
    import openai_codex
    from codex_cli_bin import bundled_path_dir
    from openai_codex import ApprovalMode, Sandbox
    from openai_codex.api import Codex, Thread
    from openai_codex.client import CodexConfig
    from openai_codex.generated.v2_all import ReasoningEffort

    if openai_codex.__version__ != expected_sdk_version:
        raise RuntimeError(
            f"expected openai-codex {expected_sdk_version}, got {openai_codex.__version__}"
        )

    captured: dict[str, dict[str, object]] = {}

    class CaptureOnlyClient:
        def account_read(self, params: object) -> object:
            captured["account_read"] = _wire_dict(params)
            return SimpleNamespace(account=object())

        def thread_start(self, params: object) -> object:
            captured["thread_start"] = _wire_dict(params)
            return SimpleNamespace(thread=SimpleNamespace(id=RAW_SENTINELS["thread_id"]))

        def _start_turn(
            self,
            thread_id: str,
            input_items: list[dict[str, object]],
            params: object,
            *,
            for_handle: bool,
        ) -> tuple[object, object]:
            if not for_handle:
                raise RuntimeError("capture-only turn must create a handle")
            payload = {
                **_wire_dict(params),
                "threadId": thread_id,
                "input": input_items,
            }
            captured["turn_start"] = payload
            return SimpleNamespace(turn=SimpleNamespace(id="capture-turn")), object()

    capture_client = CaptureOnlyClient()
    codex = object.__new__(Codex)
    codex._client = cast(Any, capture_client)
    codex.account(refresh_token=False)
    thread = codex.thread_start(
        approval_mode=ApprovalMode.deny_all,
        config=cast(Any, _config(variant)),
        cwd=RAW_SENTINELS["workspace"],
        ephemeral=True,
        model=MODEL_IDENTIFIER,
        sandbox=Sandbox.read_only,
    )
    if not isinstance(thread, Thread):
        raise RuntimeError("capture-only SDK did not return a thread")
    thread.turn(
        PROMPT,
        approval_mode=ApprovalMode.deny_all,
        cwd=RAW_SENTINELS["workspace"],
        effort=ReasoningEffort(MODEL_REASONING_EFFORT),
        sandbox=Sandbox.read_only,
    )

    sdk_config = CodexConfig()
    initialize_params = {
        "clientInfo": {
            "name": sdk_config.client_name,
            "title": sdk_config.client_title,
            "version": sdk_config.client_version,
        },
        "capabilities": {"experimentalApi": sdk_config.experimental_api},
    }
    path_dir = bundled_path_dir()
    if path_dir is None:
        raise RuntimeError("bundled Codex PATH directory is unavailable")
    return {
        "schema_version": "codex-raw-thread-wire-fixture/v1",
        "sdk_version": expected_sdk_version,
        "variant": variant,
        "app_server_argv": [
            RAW_SENTINELS["binary"],
            "app-server",
            "--listen",
            "stdio://",
        ],
        "environment": {
            "CODEX_HOME": RAW_SENTINELS["codex_home"],
            "LANG": "C.UTF-8",
            "PATH": f"{RAW_SENTINELS['path_dir']}:/usr/bin:/bin",
            "TZ": "UTC",
        },
        "requests": {
            "initialize": {
                "id": RAW_SENTINELS["request_id"],
                "method": "initialize",
                "params": initialize_params,
            },
            "initialized": {"method": "initialized", "params": {}},
            "account_read": {
                "id": RAW_SENTINELS["request_id"],
                "method": "account/read",
                "params": captured["account_read"],
            },
            "thread_start": {
                "id": RAW_SENTINELS["request_id"],
                "method": "thread/start",
                "params": captured["thread_start"],
            },
            "turn_start": {
                "id": RAW_SENTINELS["request_id"],
                "method": "turn/start",
                "params": captured["turn_start"],
            },
        },
    }


def _substitute_sentinels(value: object, replacements: dict[str, object]) -> object:
    if isinstance(value, dict):
        return {key: _substitute_sentinels(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_sentinels(item, replacements) for item in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        result = value
        for sentinel, replacement in replacements.items():
            if sentinel in result:
                if not isinstance(replacement, str):
                    raise TypeError("embedded sentinel replacement must be text")
                result = result.replace(sentinel, replacement)
        return result
    return value


class _RawAppServer:
    def __init__(
        self,
        *,
        argv: list[str],
        cwd: str,
        environment: dict[str, str],
    ) -> None:
        self.argv = argv
        self._stdout: queue.Queue[bytes | BaseException | None] = queue.Queue()
        self._stdout_bytes = 0
        self._stderr_hash = hashlib.sha256()
        self._stderr_bytes = 0
        self._stderr_lines = 0
        self._stderr_error: BaseException | None = None
        self._stderr_lock = threading.Lock()
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=environment,
            start_new_session=True,
        )
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._stdout.put(RuntimeError("app-server stdout is unavailable"))
            return
        pending = bytearray()
        try:
            while True:
                chunk = stream.read1(8192)
                if not chunk:
                    break
                self._stdout_bytes += len(chunk)
                if self._stdout_bytes > MAX_PROVIDER_TRANSCRIPT_BYTES:
                    raise RuntimeError("app-server stdout exceeded its bound")
                pending.extend(chunk)
                if len(pending) > MAX_JSON_RPC_LINE_BYTES and b"\n" not in pending:
                    raise RuntimeError("app-server JSON-RPC line exceeded its bound")
                while True:
                    newline = pending.find(b"\n")
                    if newline < 0:
                        break
                    line = bytes(pending[:newline])
                    del pending[: newline + 1]
                    if len(line) > MAX_JSON_RPC_LINE_BYTES:
                        raise RuntimeError("app-server JSON-RPC line exceeded its bound")
                    self._stdout.put(line)
            if pending:
                raise RuntimeError("app-server stdout ended without a newline")
        except BaseException as error:
            self._stdout.put(error)
        finally:
            self._stdout.put(None)

    def _read_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read1(8192)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_hash.update(chunk)
                    self._stderr_bytes += len(chunk)
                    self._stderr_lines += chunk.count(b"\n")
                    if self._stderr_bytes > MAX_STDERR_BYTES and self._stderr_error is None:
                        self._stderr_error = RuntimeError("app-server stderr exceeded its bound")
        except BaseException as error:
            with self._stderr_lock:
                if self._stderr_error is None:
                    self._stderr_error = error

    def _check_stderr(self) -> None:
        with self._stderr_lock:
            error = self._stderr_error
        if error is not None:
            raise error

    def send(self, message: dict[str, object]) -> None:
        self._check_stderr()
        stream = self._process.stdin
        if stream is None:
            raise RuntimeError("app-server stdin is unavailable")
        stream.write(canonical_json_bytes(message) + b"\n")
        stream.flush()

    def next_message(self, *, deadline: float) -> dict[str, object]:
        while True:
            self._check_stderr()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("raw app-server diagnostic exceeded its deadline")
            try:
                line = self._stdout.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError("app-server stdout closed before diagnostic completion")
            if isinstance(line, BaseException):
                raise line
            try:
                _safe_artifact_payload("app-server JSON-RPC message", line)
                text = line.decode("utf-8", errors="strict")
                value = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("app-server emitted invalid JSON-RPC") from error
            if not isinstance(value, dict):
                raise RuntimeError("app-server JSON-RPC message is not an object")
            return cast(dict[str, object], value)

    def request(
        self, message: dict[str, object], *, deadline: float
    ) -> tuple[dict[str, object], dict[str, object]]:
        request_id = message.get("id")
        self.send(message)
        while True:
            incoming = self.next_message(deadline=deadline)
            if "method" in incoming:
                if "id" in incoming:
                    raise RuntimeError("unexpected app-server request")
                continue
            if incoming.get("id") != request_id:
                raise RuntimeError("unexpected app-server response id")
            if "error" in incoming:
                raise RuntimeError("app-server request returned an error")
            result = incoming.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("app-server response result is not an object")
            return incoming, cast(dict[str, object], result)

    def turn(
        self,
        message: dict[str, object],
        *,
        expected_thread_id: str,
        deadline: float,
    ) -> tuple[dict[str, object], list[dict[str, object]], str]:
        request_id = message.get("id")
        response: dict[str, object] | None = None
        turn_id: str | None = None
        terminal_seen = False
        events: list[dict[str, object]] = []
        transcript_bytes = 0
        self.send(message)
        while response is None or not terminal_seen:
            incoming = self.next_message(deadline=deadline)
            method = incoming.get("method")
            if isinstance(method, str):
                if "id" in incoming:
                    raise RuntimeError("unexpected app-server request")
                encoded = canonical_json_bytes(incoming) + b"\n"
                transcript_bytes += len(encoded)
                if transcript_bytes > MAX_PROVIDER_TRANSCRIPT_BYTES:
                    raise RuntimeError("raw provider transcript exceeded its bound")
                events.append(incoming)
                if method == "turn/completed":
                    params = incoming.get("params")
                    if not isinstance(params, dict):
                        raise RuntimeError("turn/completed params are invalid")
                    event_thread = params.get("threadId")
                    turn = params.get("turn")
                    if event_thread != expected_thread_id or not isinstance(turn, dict):
                        raise RuntimeError("turn/completed reference mismatch")
                    event_turn = turn.get("id")
                    if not isinstance(event_turn, str):
                        raise RuntimeError("turn/completed turn id is missing")
                    if turn_id is not None and event_turn != turn_id:
                        raise RuntimeError("turn/completed turn id mismatch")
                    turn_id = event_turn
                    terminal_seen = True
                continue
            if incoming.get("id") != request_id or response is not None:
                raise RuntimeError("unexpected app-server response id")
            if "error" in incoming:
                raise RuntimeError("turn/start returned an error")
            result = incoming.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("turn"), dict):
                raise RuntimeError("turn/start response is invalid")
            candidate_turn = cast(dict[str, object], result["turn"]).get("id")
            if not isinstance(candidate_turn, str):
                raise RuntimeError("turn/start response has no turn id")
            if turn_id is not None and candidate_turn != turn_id:
                raise RuntimeError("turn response and notification ids differ")
            turn_id = candidate_turn
            response = incoming
        if response is None or turn_id is None:
            raise RuntimeError("turn did not produce a complete response")
        return response, events, turn_id

    def stderr_summary(self) -> dict[str, object]:
        with self._stderr_lock:
            return {
                "byte_count": self._stderr_bytes,
                "line_count": self._stderr_lines,
                "sha256": self._stderr_hash.hexdigest(),
            }

    def close(self) -> None:
        stream = self._process.stdin
        if stream is not None and not stream.closed:
            stream.close()
        if self._process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(self._process.pid, signal.SIGTERM)
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(self._process.pid, signal.SIGKILL)
                self._process.wait(timeout=2)
        self._stdout_thread.join(timeout=0.5)
        self._stderr_thread.join(timeout=0.5)


def _raw_event_summary(
    events: list[dict[str, object]], *, thread_id: str | None, turn_id: str | None
) -> dict[str, object]:
    methods: list[str] = []
    item_types: list[str] = []
    started: dict[str, str] = {}
    completed: set[str] = set()
    command_started = 0
    command_completed = 0
    command_failed = 0
    command_declined = 0
    command_succeeded = 0
    turn_status: str | None = None
    terminal_seen = False
    integrity_error: str | None = None
    for event in events:
        method = event.get("method")
        params = event.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            integrity_error = "INVALID_NOTIFICATION"
            break
        methods.append(method)
        scoped_thread = params.get("threadId")
        scoped_turn = params.get("turnId")
        if method.startswith("item/") or method.startswith("turn/"):
            if scoped_thread is not None and scoped_thread != thread_id:
                integrity_error = "CROSS_THREAD_EVENT"
                break
            if scoped_turn is not None and scoped_turn != turn_id:
                integrity_error = "CROSS_TURN_EVENT"
                break
        if terminal_seen and method.startswith(("item/", "turn/")):
            integrity_error = "EVENT_AFTER_TERMINAL"
            break
        if method in {"item/started", "item/completed"}:
            item = params.get("item")
            if not isinstance(item, dict):
                integrity_error = "INVALID_ITEM"
                break
            item_id = item.get("id")
            item_type = item.get("type")
            if not isinstance(item_id, str) or not isinstance(item_type, str):
                integrity_error = "INVALID_ITEM_IDENTITY"
                break
            item_types.append(item_type)
            if method == "item/started":
                if item_id in started:
                    integrity_error = "DUPLICATE_ITEM_START"
                    break
                started[item_id] = item_type
                if item_type == "commandExecution":
                    command_started += 1
            else:
                if item_id not in started:
                    integrity_error = "ITEM_COMPLETED_WITHOUT_START"
                    break
                if started[item_id] != item_type or item_id in completed:
                    integrity_error = "ITEM_LIFECYCLE_MISMATCH"
                    break
                completed.add(item_id)
                if item_type == "commandExecution":
                    status = item.get("status")
                    if status == "completed":
                        command_completed += 1
                        if item.get("exitCode") == 0:
                            command_succeeded += 1
                    elif status == "failed":
                        command_failed += 1
                    elif status == "declined":
                        command_declined += 1
                    else:
                        integrity_error = "INVALID_COMMAND_TERMINAL_STATUS"
                        break
        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict) or turn.get("id") != turn_id:
                integrity_error = "TURN_COMPLETED_REFERENCE_MISMATCH"
                break
            status = turn.get("status")
            if not isinstance(status, str):
                integrity_error = "INVALID_TURN_STATUS"
                break
            turn_status = status
            terminal_seen = True
    if integrity_error is None and set(started) != completed:
        integrity_error = "INCOMPLETE_ITEM_LIFECYCLE"
    if integrity_error is None and not terminal_seen:
        integrity_error = "TURN_TERMINAL_MISSING"
    return {
        "provider_event_methods": sorted(set(methods)),
        "observed_item_types": sorted(set(item_types)),
        "command_count": command_started,
        "command_started_count": command_started,
        "command_completed_count": command_completed,
        "command_failed_count": command_failed,
        "command_declined_count": command_declined,
        "command_succeeded_count": command_succeeded,
        "turn_status": turn_status,
        "reference_integrity": integrity_error is None,
        "lifecycle_integrity": integrity_error is None,
        "integrity_error": integrity_error,
    }


def _raw_classify_matrix(results: Sequence[dict[str, object]]) -> str:
    by_variant = {str(result.get("variant")): result for result in results}
    if set(by_variant) != set(VARIANTS) or len(results) != len(VARIANTS):
        raise ValueError("raw diagnostic matrix must contain every variant exactly once")
    if any(
        result.get("decision") == "DIAGNOSTIC_FAILED"
        or result.get("turn_status") != "completed"
        or result.get("reference_integrity") is not True
        or result.get("lifecycle_integrity") is not True
        for result in results
    ):
        return "DIAGNOSTIC_FAILED"
    identities = {
        (
            result.get("sdk_version"),
            result.get("runtime_package_version"),
            result.get("runtime_version"),
            result.get("runtime_binary_hash"),
        )
        for result in results
    }
    if len(identities) != 1:
        return "DIAGNOSTIC_FAILED"
    counts = {variant: by_variant[variant].get("command_started_count") for variant in VARIANTS}
    if any(not isinstance(value, int) or isinstance(value, bool) for value in counts.values()):
        return "DIAGNOSTIC_FAILED"
    if cast(int, counts[NEGATIVE_VARIANT]) > 0:
        return "NEGATIVE_CONTROL_FAILED"
    positives = [cast(int, counts[variant]) for variant in POSITIVE_VARIANTS]
    if all(value > 0 for value in positives):
        return "RAW_THREAD_COMMAND_AVAILABLE"
    if all(value == 0 for value in positives):
        return "RAW_THREAD_OBSERVABILITY_GAP"
    return "VARIANT_DEPENDENT"


def _safe_artifact_payload(name: str, payload: bytes) -> bytes:
    if PROHIBITED_OUTPUT_PATTERN.search(payload):
        raise RuntimeError(f"prohibited secret marker observed before persisting {name}")
    return payload


def _publish_raw_bundle(output_root: Path, files: dict[str, bytes]) -> Path:
    safe_files = {name: _safe_artifact_payload(name, payload) for name, payload in files.items()}
    manifest = {
        "schema_version": "codex-raw-thread-manifest/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "files": {name: sha256_bytes(payload) for name, payload in sorted(safe_files.items())},
    }
    manifest_bytes = canonical_json_bytes(manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codex-d06-", dir=output_root) as temporary:
        staging = Path(temporary) / "published"
        staging.mkdir()
        for name, payload in safe_files.items():
            atomic_write_bytes(staging / name, payload)
        atomic_write_bytes(staging / "manifest.json", manifest_bytes)
        destination = output_root / f"raw-sha256-{sha256_bytes(manifest_bytes)}"
        publish_directory(staging, destination)
    return destination


def _runtime_version_from_initialize(result: dict[str, object]) -> str | None:
    server_info = result.get("serverInfo")
    if isinstance(server_info, dict) and isinstance(server_info.get("version"), str):
        return cast(str, server_info["version"])
    user_agent = result.get("userAgent")
    if isinstance(user_agent, str):
        candidate = user_agent.partition("/")[2].partition(" ")[0]
        return candidate or None
    return None


def _unavailable_response(request_id: object) -> dict[str, object]:
    return {"available": False, "id": request_id}


def run_raw_thread_diagnostic(
    *,
    variant: str,
    output_root: Path,
    authentication_home: Path,
    expected_sdk_version: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, object]]:
    """Run D0.6 through raw app-server JSON-RPC without the SDK transport."""
    import openai_codex
    from codex_cli_bin import bundled_codex_path, bundled_path_dir

    source_auth = authentication_home / "auth.json"
    if source_auth.is_symlink() or not source_auth.is_file():
        raise RuntimeError("a regular pre-existing Codex auth.json is required")
    if openai_codex.__version__ != expected_sdk_version:
        raise RuntimeError(
            f"expected openai-codex {expected_sdk_version}, got {openai_codex.__version__}"
        )
    runtime_package_version = version(CODEX_RUNTIME_DISTRIBUTION)
    if runtime_package_version != expected_sdk_version:
        raise RuntimeError(
            "installed bundled Codex runtime package does not match the expected version"
        )
    runtime_path = Path(bundled_codex_path())
    path_dir_value = bundled_path_dir()
    if path_dir_value is None:
        raise RuntimeError("bundled Codex PATH directory is unavailable")
    path_dir = Path(path_dir_value)
    fixture = _build_raw_wire_fixture(variant, expected_sdk_version=expected_sdk_version)
    fixture_hash = sha256_bytes(canonical_json_bytes(fixture))
    fixture_requests = fixture.get("requests")
    if not isinstance(fixture_requests, dict):
        raise RuntimeError("raw wire fixture has no requests")

    with (
        tempfile.TemporaryDirectory(prefix="quantos-codex-d06-workspace-", dir="/tmp") as cwd,
        tempfile.TemporaryDirectory(prefix="quantos-codex-d06-home-", dir="/tmp") as codex_home,
    ):
        (Path(codex_home) / "auth.json").symlink_to(source_auth)
        environment = {
            "CODEX_HOME": codex_home,
            "LANG": "C.UTF-8",
            "PATH": f"{path_dir}:/usr/bin:/bin",
            "TZ": "UTC",
        }
        argv = [str(runtime_path), "app-server", "--listen", "stdio://"]
        base_replacements: dict[str, object] = {
            RAW_SENTINELS["binary"]: str(runtime_path),
            RAW_SENTINELS["codex_home"]: codex_home,
            RAW_SENTINELS["path_dir"]: str(path_dir),
            RAW_SENTINELS["workspace"]: cwd,
        }

        def request(name: str, request_id: int, **extra: object) -> dict[str, object]:
            template = fixture_requests.get(name)
            if not isinstance(template, dict):
                raise RuntimeError(f"raw wire fixture is missing {name}")
            replacements = {
                **base_replacements,
                RAW_SENTINELS["request_id"]: request_id,
                **extra,
            }
            resolved = _substitute_sentinels(template, replacements)
            if not isinstance(resolved, dict):
                raise RuntimeError(f"resolved {name} request is invalid")
            return cast(dict[str, object], resolved)

        initialize_request = request("initialize", 0)
        account_request = request("account_read", 1)
        thread_request = request("thread_start", 2)
        turn_request: dict[str, object] = {
            "available": False,
            "id": 3,
        }
        initialize_response = _unavailable_response(0)
        thread_response = _unavailable_response(2)
        turn_response = _unavailable_response(3)
        account_summary: dict[str, object] = {"authenticated": False}
        events: list[dict[str, object]] = []
        runtime_version: str | None = None
        thread_id: str | None = None
        turn_id: str | None = None
        terminal_error: BaseException | None = None
        client: _RawAppServer | None = None
        stderr_summary = {"byte_count": 0, "line_count": 0, "sha256": hashlib.sha256().hexdigest()}
        try:
            deadline = time.monotonic() + timeout_seconds
            client = _RawAppServer(argv=argv, cwd=cwd, environment=environment)
            initialize_response, initialize_result = client.request(
                initialize_request, deadline=deadline
            )
            runtime_version = _runtime_version_from_initialize(initialize_result)
            if not runtime_version or runtime_version.partition(" ")[0] != expected_sdk_version:
                raise RuntimeError("reported Codex runtime version does not match expectation")
            initialized_template = fixture_requests.get("initialized")
            if not isinstance(initialized_template, dict):
                raise RuntimeError("raw wire fixture is missing initialized")
            initialized = _substitute_sentinels(initialized_template, base_replacements)
            if not isinstance(initialized, dict):
                raise RuntimeError("resolved initialized notification is invalid")
            client.send(cast(dict[str, object], initialized))
            _account_response, account_result = client.request(account_request, deadline=deadline)
            account_summary = {"authenticated": account_result.get("account") is not None}
            if account_summary["authenticated"] is not True:
                raise RuntimeError("pre-existing Codex authentication is unavailable")
            thread_response, thread_result = client.request(thread_request, deadline=deadline)
            thread_value = thread_result.get("thread")
            if not isinstance(thread_value, dict) or not isinstance(thread_value.get("id"), str):
                raise RuntimeError("thread/start response has no thread id")
            thread_id = cast(str, thread_value["id"])
            turn_request = request(
                "turn_start",
                3,
                **{RAW_SENTINELS["thread_id"]: thread_id},
            )
            turn_response, events, turn_id = client.turn(
                turn_request,
                expected_thread_id=thread_id,
                deadline=deadline,
            )
        except Exception as error:
            terminal_error = error
        finally:
            if client is not None:
                client.close()
                stderr_summary = client.stderr_summary()
                if stderr_summary["byte_count"] > MAX_STDERR_BYTES and terminal_error is None:
                    terminal_error = RuntimeError("app-server stderr exceeded its bound")

        event_summary = _raw_event_summary(events, thread_id=thread_id, turn_id=turn_id)
        decision = (
            "SHELL_OBSERVED" if event_summary["command_started_count"] > 0 else "SHELL_NOT_OBSERVED"
        )
        if (
            terminal_error is not None
            or event_summary["reference_integrity"] is not True
            or event_summary["lifecycle_integrity"] is not True
            or event_summary["turn_status"] != "completed"
        ):
            decision = "DIAGNOSTIC_FAILED"
        result: dict[str, object] = {
            "schema_version": "codex-raw-thread-result/v1",
            "authority": "NON_CANONICAL_DIAGNOSTIC",
            "probe": "D0.6_RAW_THREAD",
            "variant": variant,
            "sdk_version": openai_codex.__version__,
            "runtime_package_version": runtime_package_version,
            "runtime_version": runtime_version,
            "runtime_binary_hash": _sha256_file(runtime_path),
            "wire_fixture_hash": fixture_hash,
            "model": MODEL_IDENTIFIER,
            "reasoning_effort": MODEL_REASONING_EFFORT,
            "prompt_hash": sha256_bytes(PROMPT.encode("utf-8")),
            "thread_id": thread_id,
            "turn_id": turn_id,
            **event_summary,
            "decision": decision,
            "limitations": list(RAW_LIMITATIONS),
        }
        if terminal_error is not None:
            result["terminal_error_kind"] = type(terminal_error).__name__
            result["terminal_error_message_hash"] = sha256_bytes(
                str(terminal_error).encode("utf-8", errors="replace")
            )
        runtime_identity = {
            "schema_version": "codex-raw-thread-runtime-identity/v1",
            "sdk_distribution": CODEX_SDK_DISTRIBUTION,
            "sdk_version": openai_codex.__version__,
            "runtime_distribution": CODEX_RUNTIME_DISTRIBUTION,
            "runtime_package_version": runtime_package_version,
            "runtime_version": runtime_version,
            "runtime_binary_hash": result["runtime_binary_hash"],
            "protocol_identifier": CODEX_PROTOCOL_IDENTIFIER,
        }
        effective_environment = {
            "schema_version": "codex-raw-thread-environment/v1",
            "app_server_argv": argv,
            "app_server_environment": environment,
            "shell_environment_policy": _config(variant)["shell_environment_policy"],
            "workspace": cwd,
        }
        provider_bytes = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        files = {
            "runtime-identity.json": canonical_json_bytes(runtime_identity),
            "wire-fixture.json": canonical_json_bytes(fixture),
            "effective-environment.json": canonical_json_bytes(effective_environment),
            "initialize-request.json": canonical_json_bytes(initialize_request),
            "initialize-response.json": canonical_json_bytes(initialize_response),
            "account-read-request.json": canonical_json_bytes(account_request),
            "account-read-summary.json": canonical_json_bytes(account_summary),
            "thread-start-request.json": canonical_json_bytes(thread_request),
            "thread-start-response.json": canonical_json_bytes(thread_response),
            "turn-start-request.json": canonical_json_bytes(turn_request),
            "turn-start-response.json": canonical_json_bytes(turn_response),
            "provider-events.jsonl": provider_bytes,
            "stderr-summary.json": canonical_json_bytes(stderr_summary),
            "result.json": canonical_json_bytes(result),
        }
        destination = _publish_raw_bundle(output_root, files)
        return destination, result


def run_raw_thread_matrix(
    *,
    output_root: Path,
    authentication_home: Path,
    expected_sdk_version: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, object]]:
    entries: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for variant in VARIANTS:
        destination, result = run_raw_thread_diagnostic(
            variant=variant,
            output_root=output_root,
            authentication_home=authentication_home,
            expected_sdk_version=expected_sdk_version,
            timeout_seconds=timeout_seconds,
        )
        results.append(result)
        entries.append(
            {
                "bundle_hash": destination.name.removeprefix("raw-sha256-"),
                "command_started_count": result["command_started_count"],
                "decision": result["decision"],
                "result_hash": sha256_bytes(canonical_json_bytes(result)),
                "turn_status": result["turn_status"],
                "variant": variant,
            }
        )
    classification = _raw_classify_matrix(results)
    first = results[0]
    matrix = {
        "schema_version": "codex-raw-thread-matrix/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "classification": classification,
        "eligible_for_p10": classification == "RAW_THREAD_COMMAND_AVAILABLE",
        "runtime_binary_hash": first["runtime_binary_hash"],
        "runtime_package_version": first["runtime_package_version"],
        "runtime_version": first["runtime_version"],
        "sdk_version": first["sdk_version"],
        "variants": entries,
    }
    matrix_bytes = canonical_json_bytes(matrix)
    matrix_hash = sha256_bytes(matrix_bytes)
    with tempfile.TemporaryDirectory(prefix=".codex-d06-matrix-", dir=output_root) as temporary:
        staging = Path(temporary) / "published"
        staging.mkdir()
        atomic_write_bytes(staging / "matrix.json", matrix_bytes, expected_sha256=matrix_hash)
        destination = output_root / f"raw-matrix-sha256-{matrix_hash}"
        publish_directory(staging, destination)
    return destination, matrix


RAW_BUNDLE_FILE_NAMES = {
    "account-read-request.json",
    "account-read-summary.json",
    "effective-environment.json",
    "initialize-request.json",
    "initialize-response.json",
    "provider-events.jsonl",
    "result.json",
    "runtime-identity.json",
    "stderr-summary.json",
    "thread-start-request.json",
    "thread-start-response.json",
    "turn-start-request.json",
    "turn-start-response.json",
    "wire-fixture.json",
}
RAW_RESULT_BASE_KEYS = {
    "authority",
    "command_completed_count",
    "command_count",
    "command_declined_count",
    "command_failed_count",
    "command_started_count",
    "command_succeeded_count",
    "decision",
    "integrity_error",
    "lifecycle_integrity",
    "limitations",
    "model",
    "observed_item_types",
    "probe",
    "prompt_hash",
    "provider_event_methods",
    "reasoning_effort",
    "reference_integrity",
    "runtime_binary_hash",
    "runtime_package_version",
    "runtime_version",
    "schema_version",
    "sdk_version",
    "thread_id",
    "turn_id",
    "turn_status",
    "variant",
    "wire_fixture_hash",
}
RAW_RESULT_ERROR_KEYS = {
    "terminal_error_kind",
    "terminal_error_message_hash",
}


def _verify_raw_bundle(
    bundle_path: Path,
    *,
    expected_variant: str,
    expected_sdk_version: str,
    expected_bundle_hash: str,
    expected_result_hash: str,
) -> dict[str, object]:
    manifest_bytes = confined_regular_file(bundle_path, "manifest.json").read_bytes()
    if sha256_bytes(manifest_bytes) != expected_bundle_hash:
        raise RuntimeError("raw diagnostic bundle path does not match its manifest hash")
    manifest = _canonical_object(manifest_bytes, label="raw diagnostic manifest")
    files_value = manifest.get("files")
    if (
        manifest.get("schema_version") != "codex-raw-thread-manifest/v1"
        or manifest.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
        or set(manifest) != {"authority", "files", "schema_version"}
        or not isinstance(files_value, dict)
        or set(files_value) != RAW_BUNDLE_FILE_NAMES
    ):
        raise RuntimeError("raw diagnostic manifest is invalid")
    files = cast(dict[str, object], files_value)
    actual_names = {str(path.relative_to(bundle_path)) for path in regular_tree_files(bundle_path)}
    if actual_names != {*RAW_BUNDLE_FILE_NAMES, "manifest.json"}:
        raise RuntimeError("raw diagnostic bundle file set is invalid")
    payloads: dict[str, bytes] = {}
    for name, expected_hash in files.items():
        if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
            raise RuntimeError("raw diagnostic file hash is invalid")
        payload = confined_regular_file(bundle_path, name).read_bytes()
        if sha256_bytes(payload) != expected_hash:
            raise RuntimeError("raw diagnostic file hash is invalid")
        _safe_artifact_payload(name, payload)
        payloads[name] = payload

    result_bytes = payloads["result.json"]
    if sha256_bytes(result_bytes) != expected_result_hash:
        raise RuntimeError("raw diagnostic matrix result hash is invalid")
    result = _canonical_object(result_bytes, label="raw diagnostic result")
    result_keys = set(result)
    if (
        result.get("schema_version") != "codex-raw-thread-result/v1"
        or result.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
        or result.get("probe") != "D0.6_RAW_THREAD"
        or result.get("variant") != expected_variant
        or result.get("sdk_version") != expected_sdk_version
        or result.get("runtime_package_version") != expected_sdk_version
        or result.get("limitations") != list(RAW_LIMITATIONS)
        or result.get("model") != MODEL_IDENTIFIER
        or result.get("reasoning_effort") != MODEL_REASONING_EFFORT
        or result.get("prompt_hash") != sha256_bytes(PROMPT.encode("utf-8"))
        or (
            result_keys != RAW_RESULT_BASE_KEYS
            and result_keys != RAW_RESULT_BASE_KEYS | RAW_RESULT_ERROR_KEYS
        )
    ):
        raise RuntimeError("raw diagnostic result identity is invalid")

    fixture = _canonical_object(payloads["wire-fixture.json"], label="raw wire fixture")
    expected_fixture = _build_raw_wire_fixture(
        expected_variant, expected_sdk_version=expected_sdk_version
    )
    if fixture != expected_fixture:
        raise RuntimeError("raw wire fixture does not match the SDK capture")
    fixture_hash = sha256_bytes(payloads["wire-fixture.json"])
    if result.get("wire_fixture_hash") != fixture_hash:
        raise RuntimeError("raw wire fixture hash binding is invalid")

    environment = _canonical_object(
        payloads["effective-environment.json"], label="raw effective environment"
    )
    app_environment = environment.get("app_server_environment")
    argv = environment.get("app_server_argv")
    workspace = environment.get("workspace")
    if (
        environment.get("schema_version") != "codex-raw-thread-environment/v1"
        or not isinstance(app_environment, dict)
        or set(app_environment) != {"CODEX_HOME", "LANG", "PATH", "TZ"}
        or not isinstance(argv, list)
        or len(argv) != 4
        or not isinstance(workspace, str)
        or environment.get("shell_environment_policy")
        != _config(expected_variant)["shell_environment_policy"]
    ):
        raise RuntimeError("raw effective environment is invalid")
    codex_home = app_environment.get("CODEX_HOME")
    app_path = app_environment.get("PATH")
    if not isinstance(codex_home, str) or not isinstance(app_path, str):
        raise RuntimeError("raw effective environment paths are invalid")
    path_suffix = ":/usr/bin:/bin"
    if not app_path.endswith(path_suffix):
        raise RuntimeError("raw app-server PATH is invalid")
    path_dir = app_path[: -len(path_suffix)]
    binary = argv[0]
    if not isinstance(binary, str):
        raise RuntimeError("raw app-server binary is invalid")
    environment_replacements: dict[str, object] = {
        RAW_SENTINELS["binary"]: binary,
        RAW_SENTINELS["codex_home"]: codex_home,
        RAW_SENTINELS["path_dir"]: path_dir,
        RAW_SENTINELS["workspace"]: workspace,
    }
    if argv != _substitute_sentinels(fixture.get("app_server_argv"), environment_replacements):
        raise RuntimeError("raw app-server argv does not match its fixture")
    if app_environment != _substitute_sentinels(
        fixture.get("environment"), environment_replacements
    ):
        raise RuntimeError("raw app-server environment does not match its fixture")

    request_files = {
        "initialize": "initialize-request.json",
        "account_read": "account-read-request.json",
        "thread_start": "thread-start-request.json",
        "turn_start": "turn-start-request.json",
    }
    requests = fixture.get("requests")
    if not isinstance(requests, dict):
        raise RuntimeError("raw fixture requests are invalid")
    actual_requests = {
        key: _canonical_object(payloads[name], label=name) for key, name in request_files.items()
    }
    request_ids = [request.get("id") for request in actual_requests.values()]
    if any(
        isinstance(request_id, bool) or not isinstance(request_id, (int, str))
        for request_id in request_ids
    ) or len({(type(request_id), request_id) for request_id in request_ids}) != len(request_ids):
        raise RuntimeError("raw request ids are invalid")
    thread_id = result.get("thread_id")
    for key, actual in actual_requests.items():
        template = requests.get(key)
        if not isinstance(template, dict):
            raise RuntimeError("raw fixture request is missing")
        replacements: dict[str, object] = {
            RAW_SENTINELS["binary"]: binary,
            RAW_SENTINELS["codex_home"]: codex_home,
            RAW_SENTINELS["path_dir"]: path_dir,
            RAW_SENTINELS["workspace"]: workspace,
            RAW_SENTINELS["request_id"]: actual.get("id"),
        }
        if key == "turn_start":
            if isinstance(thread_id, str):
                replacements[RAW_SENTINELS["thread_id"]] = thread_id
            elif actual.get("available") is False:
                continue
            else:
                raise RuntimeError("raw turn request has no thread binding")
        expected = _substitute_sentinels(template, replacements)
        if actual != expected:
            raise RuntimeError(f"raw {key} request does not match its fixture")

    runtime_identity = _canonical_object(
        payloads["runtime-identity.json"], label="raw runtime identity"
    )
    runtime_hash = result.get("runtime_binary_hash")
    if (
        runtime_identity.get("schema_version") != "codex-raw-thread-runtime-identity/v1"
        or runtime_identity.get("sdk_distribution") != CODEX_SDK_DISTRIBUTION
        or runtime_identity.get("sdk_version") != expected_sdk_version
        or runtime_identity.get("runtime_distribution") != CODEX_RUNTIME_DISTRIBUTION
        or runtime_identity.get("runtime_package_version") != expected_sdk_version
        or runtime_identity.get("runtime_version") != result.get("runtime_version")
        or runtime_identity.get("runtime_binary_hash") != runtime_hash
        or runtime_identity.get("protocol_identifier") != CODEX_PROTOCOL_IDENTIFIER
        or not isinstance(runtime_hash, str)
        or SHA256_PATTERN.fullmatch(runtime_hash) is None
    ):
        raise RuntimeError("raw runtime identity binding is invalid")

    initialize_response = _canonical_object(
        payloads["initialize-response.json"], label="raw initialize response"
    )
    initialize_request_id = actual_requests["initialize"].get("id")
    if (
        type(initialize_response.get("id")) is not type(initialize_request_id)
        or initialize_response.get("id") != initialize_request_id
    ):
        raise RuntimeError("raw initialize response id binding is invalid")
    if initialize_response.get("available") is not False:
        initialize_result = initialize_response.get("result")
        if not isinstance(initialize_result, dict) or _runtime_version_from_initialize(
            cast(dict[str, object], initialize_result)
        ) != result.get("runtime_version"):
            raise RuntimeError("raw initialize response binding is invalid")
    thread_response = _canonical_object(
        payloads["thread-start-response.json"], label="raw thread response"
    )
    thread_request_id = actual_requests["thread_start"].get("id")
    if (
        type(thread_response.get("id")) is not type(thread_request_id)
        or thread_response.get("id") != thread_request_id
    ):
        raise RuntimeError("raw thread response id binding is invalid")
    if thread_response.get("available") is not False:
        thread_result = thread_response.get("result")
        thread_value = thread_result.get("thread") if isinstance(thread_result, dict) else None
        if not isinstance(thread_value, dict) or thread_value.get("id") != result.get("thread_id"):
            raise RuntimeError("raw thread response binding is invalid")
    turn_response = _canonical_object(
        payloads["turn-start-response.json"], label="raw turn response"
    )
    turn_request_id = actual_requests["turn_start"].get("id")
    if (
        type(turn_response.get("id")) is not type(turn_request_id)
        or turn_response.get("id") != turn_request_id
    ):
        raise RuntimeError("raw turn response id binding is invalid")
    if turn_response.get("available") is not False:
        turn_result = turn_response.get("result")
        turn_value = turn_result.get("turn") if isinstance(turn_result, dict) else None
        if not isinstance(turn_value, dict) or turn_value.get("id") != result.get("turn_id"):
            raise RuntimeError("raw turn response binding is invalid")

    account_summary = _canonical_object(
        payloads["account-read-summary.json"], label="raw account summary"
    )
    if set(account_summary) != {"authenticated"} or not isinstance(
        account_summary.get("authenticated"), bool
    ):
        raise RuntimeError("raw account summary is not allowlisted")
    stderr_summary = _canonical_object(payloads["stderr-summary.json"], label="raw stderr summary")
    if (
        set(stderr_summary) != {"byte_count", "line_count", "sha256"}
        or type(stderr_summary.get("byte_count")) is not int
        or cast(int, stderr_summary["byte_count"]) < 0
        or type(stderr_summary.get("line_count")) is not int
        or cast(int, stderr_summary["line_count"]) < 0
        or cast(int, stderr_summary["line_count"]) > cast(int, stderr_summary["byte_count"])
        or not isinstance(stderr_summary.get("sha256"), str)
        or SHA256_PATTERN.fullmatch(cast(str, stderr_summary["sha256"])) is None
    ):
        raise RuntimeError("raw stderr summary is invalid")

    provider_bytes = payloads["provider-events.jsonl"]
    if len(provider_bytes) > MAX_PROVIDER_TRANSCRIPT_BYTES:
        raise RuntimeError("raw provider transcript exceeds its bound")
    if any(len(line) > MAX_JSON_RPC_LINE_BYTES + 1 for line in provider_bytes.splitlines(True)):
        raise RuntimeError("raw provider transcript line exceeds its bound")
    events = _canonical_jsonl_objects(provider_bytes, label="raw provider transcript")
    recomputed = _raw_event_summary(
        events,
        thread_id=cast(str | None, result.get("thread_id")),
        turn_id=cast(str | None, result.get("turn_id")),
    )
    for field, value in recomputed.items():
        actual = result.get(field)
        if type(actual) is not type(value) or actual != value:
            raise RuntimeError("raw provider summary binding is invalid")
    expected_decision = (
        "SHELL_OBSERVED" if recomputed["command_started_count"] > 0 else "SHELL_NOT_OBSERVED"
    )
    diagnostic_failed = (
        recomputed["reference_integrity"] is not True
        or recomputed["lifecycle_integrity"] is not True
        or recomputed["turn_status"] != "completed"
        or cast(int, stderr_summary["byte_count"]) > MAX_STDERR_BYTES
    )
    if result.get("decision") == "DIAGNOSTIC_FAILED":
        if not diagnostic_failed and not (
            isinstance(result.get("terminal_error_kind"), str)
            and isinstance(result.get("terminal_error_message_hash"), str)
            and SHA256_PATTERN.fullmatch(cast(str, result["terminal_error_message_hash"]))
            is not None
        ):
            raise RuntimeError("raw diagnostic failure evidence is invalid")
    elif diagnostic_failed or result.get("decision") != expected_decision:
        raise RuntimeError("raw diagnostic result decision is invalid")
    return result


def verify_raw_matrix(
    matrix_path: Path, *, expected_sdk_version: str = PINNED_SDK_VERSION
) -> dict[str, object]:
    if {str(path.relative_to(matrix_path)) for path in regular_tree_files(matrix_path)} != {
        "matrix.json"
    }:
        raise RuntimeError("raw matrix file set is invalid")
    matrix_bytes = confined_regular_file(matrix_path, "matrix.json").read_bytes()
    matrix_hash = sha256_bytes(matrix_bytes)
    if matrix_path.name != f"raw-matrix-sha256-{matrix_hash}":
        raise RuntimeError("raw matrix path does not match its content hash")
    matrix = _canonical_object(matrix_bytes, label="raw diagnostic matrix")
    variants = matrix.get("variants")
    if (
        matrix.get("schema_version") != "codex-raw-thread-matrix/v1"
        or matrix.get("authority") != "NON_CANONICAL_DIAGNOSTIC"
        or set(matrix)
        != {
            "authority",
            "classification",
            "eligible_for_p10",
            "runtime_binary_hash",
            "runtime_package_version",
            "runtime_version",
            "schema_version",
            "sdk_version",
            "variants",
        }
        or not isinstance(variants, list)
        or len(variants) != len(VARIANTS)
    ):
        raise RuntimeError("raw diagnostic matrix identity is invalid")
    results: list[dict[str, object]] = []
    for expected_variant, entry_value in zip(VARIANTS, variants, strict=True):
        if not isinstance(entry_value, dict):
            raise RuntimeError("raw matrix entry is invalid")
        entry = cast(dict[str, object], entry_value)
        bundle_hash = entry.get("bundle_hash")
        result_hash = entry.get("result_hash")
        if (
            set(entry)
            != {
                "bundle_hash",
                "command_started_count",
                "decision",
                "result_hash",
                "turn_status",
                "variant",
            }
            or entry.get("variant") != expected_variant
            or not isinstance(bundle_hash, str)
            or SHA256_PATTERN.fullmatch(bundle_hash) is None
            or not isinstance(result_hash, str)
            or SHA256_PATTERN.fullmatch(result_hash) is None
        ):
            raise RuntimeError("raw matrix entry binding is invalid")
        bundle_path = matrix_path.parent / f"raw-sha256-{bundle_hash}"
        result = _verify_raw_bundle(
            bundle_path,
            expected_variant=expected_variant,
            expected_sdk_version=expected_sdk_version,
            expected_bundle_hash=bundle_hash,
            expected_result_hash=result_hash,
        )
        if any(
            entry.get(field) != result.get(field)
            for field in ("command_started_count", "decision", "turn_status", "variant")
        ):
            raise RuntimeError("raw matrix entry result binding is invalid")
        results.append(result)
    classification = _raw_classify_matrix(results)
    first = results[0]
    if (
        matrix.get("classification") != classification
        or matrix.get("eligible_for_p10") != (classification == "RAW_THREAD_COMMAND_AVAILABLE")
        or matrix.get("sdk_version") != first.get("sdk_version")
        or matrix.get("runtime_package_version") != first.get("runtime_package_version")
        or matrix.get("runtime_version") != first.get("runtime_version")
        or matrix.get("runtime_binary_hash") != first.get("runtime_binary_hash")
    ):
        raise RuntimeError("raw matrix conclusion is invalid")
    return matrix


def run_matrix(
    *,
    output_root: Path,
    authentication_home: Path,
    expected_sdk_version: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, object]]:
    entries: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    for variant in VARIANTS:
        destination, result = run_diagnostic(
            variant=variant,
            output_root=output_root,
            authentication_home=authentication_home,
            expected_sdk_version=expected_sdk_version,
            timeout_seconds=timeout_seconds,
        )
        results.append(result)
        entries.append(
            {
                "bundle_hash": destination.name.removeprefix("sha256-"),
                "command_count": result["command_count"],
                "decision": result["decision"],
                "result_hash": sha256_bytes(canonical_json_bytes(result)),
                "turn_status": result["turn_status"],
                "variant": variant,
            }
        )
    classification = _classify_matrix(results)
    first = results[0]
    matrix = {
        "schema_version": "codex-sdk-failure-isolation-matrix/v1",
        "authority": "NON_CANONICAL_DIAGNOSTIC",
        "classification": classification,
        "eligible_for_p10": classification == "SHELL_SURFACE_AVAILABLE",
        "runtime_binary_hash": first["runtime_binary_hash"],
        "runtime_package_version": first["runtime_package_version"],
        "runtime_version": first["runtime_version"],
        "sdk_version": first["sdk_version"],
        "variants": entries,
    }
    matrix_bytes = canonical_json_bytes(matrix)
    matrix_hash = sha256_bytes(matrix_bytes)
    with tempfile.TemporaryDirectory(prefix=".codex-d0-matrix-", dir=output_root) as temporary:
        staging = Path(temporary) / "published"
        staging.mkdir()
        atomic_write_bytes(staging / "matrix.json", matrix_bytes, expected_sha256=matrix_hash)
        destination = output_root / f"matrix-sha256-{matrix_hash}"
        publish_directory(staging, destination)
    return destination, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--variant", choices=VARIANTS)
    mode.add_argument("--all-variants", action="store_true")
    mode.add_argument("--command-exec", action="store_true")
    mode.add_argument("--verify-matrix", type=Path)
    mode.add_argument("--verify-raw-matrix", type=Path)
    parser.add_argument("--raw-thread", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/quantos-codex-sdk-d0"))
    parser.add_argument("--authentication-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--expected-sdk-version", default=PINNED_SDK_VERSION)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.verify_raw_matrix is not None:
        matrix = verify_raw_matrix(
            args.verify_raw_matrix, expected_sdk_version=args.expected_sdk_version
        )
        print(
            json.dumps(
                {
                    "classification": matrix["classification"],
                    "eligible_for_p10": matrix["eligible_for_p10"],
                    "matrix_path": str(args.verify_raw_matrix),
                    "verified": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.verify_matrix is not None:
        if args.raw_thread:
            raise RuntimeError("--raw-thread cannot be combined with --verify-matrix")
        matrix = verify_matrix(args.verify_matrix, expected_sdk_version=args.expected_sdk_version)
        print(
            json.dumps(
                {
                    "classification": matrix["classification"],
                    "eligible_for_p10": matrix["eligible_for_p10"],
                    "matrix_path": str(args.verify_matrix),
                    "verified": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command_exec:
        if args.raw_thread:
            raise RuntimeError("--raw-thread cannot be combined with --command-exec")
        destination, result = run_command_exec_probe(
            output_root=args.output_root,
            expected_sdk_version=args.expected_sdk_version,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(
                {
                    "decision": result["decision"],
                    "diagnostic_path": str(destination),
                    "runtime_binary_hash": result["runtime_binary_hash"],
                    "runtime_package_version": result["runtime_package_version"],
                    "runtime_version": result["runtime_version"],
                    "sdk_version": result["sdk_version"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.all_variants:
        runner = run_raw_thread_matrix if args.raw_thread else run_matrix
        destination, matrix = runner(
            output_root=args.output_root,
            authentication_home=args.authentication_home,
            expected_sdk_version=args.expected_sdk_version,
            timeout_seconds=args.timeout_seconds,
        )
        print(
            json.dumps(
                {
                    "classification": matrix["classification"],
                    "diagnostic_path": str(destination),
                    "eligible_for_p10": matrix["eligible_for_p10"],
                    "runtime_binary_hash": matrix["runtime_binary_hash"],
                    "runtime_package_version": matrix["runtime_package_version"],
                    "runtime_version": matrix["runtime_version"],
                    "sdk_version": matrix["sdk_version"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.variant is None:
        raise RuntimeError("one diagnostic mode is required")
    runner_variant = run_raw_thread_diagnostic if args.raw_thread else run_diagnostic
    destination, result = runner_variant(
        variant=args.variant,
        output_root=args.output_root,
        authentication_home=args.authentication_home,
        expected_sdk_version=args.expected_sdk_version,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "diagnostic_path": str(destination),
                "runtime_binary_hash": result["runtime_binary_hash"],
                "runtime_package_version": result["runtime_package_version"],
                "runtime_version": result["runtime_version"],
                "sdk_version": result["sdk_version"],
                "variant": result["variant"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
