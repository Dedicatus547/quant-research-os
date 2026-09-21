#!/usr/bin/env python3
"""Run one non-canonical Codex SDK shell-isolation diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
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
PROMPT = (
    "Run /usr/bin/pwd as a shell command.\n"
    "After the command completes, report the exact working directory.\n"
    "Do not answer without executing the command."
)
MAX_PROVIDER_TRANSCRIPT_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 90
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


def verify_matrix(matrix_path: Path) -> dict[str, object]:
    if {
        str(path.relative_to(matrix_path)) for path in regular_tree_files(matrix_path)
    } != {"matrix.json"}:
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
            or runtime_identity.get("schema_version")
            != "codex-sdk-diagnostic-runtime-identity/v1"
            or runtime_identity.get("sdk_distribution") != CODEX_SDK_DISTRIBUTION
            or runtime_identity.get("sdk_version") != result.get("sdk_version")
            or runtime_identity.get("runtime_distribution") != CODEX_RUNTIME_DISTRIBUTION
            or runtime_identity.get("runtime_package_version")
            != result.get("runtime_package_version")
            or runtime_identity.get("runtime_version") != result.get("runtime_version")
            or runtime_identity.get("runtime_binary_hash") != runtime_binary_hash
            or runtime_identity.get("protocol_identifier") != CODEX_PROTOCOL_IDENTIFIER
            or result.get("sdk_version") != CODEX_SDK_VERSION
            or result.get("runtime_package_version") != CODEX_RUNTIME_PACKAGE_VERSION
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
        if runtime_package_version != CODEX_RUNTIME_PACKAGE_VERSION:
            raise RuntimeError(
                "installed bundled Codex runtime package does not match the frozen version"
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
                if runtime_version.partition(" ")[0] != CODEX_RUNTIME_PACKAGE_VERSION:
                    raise RuntimeError("reported Codex runtime version does not match the pin")
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
    mode.add_argument("--verify-matrix", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/quantos-codex-sdk-d0"))
    parser.add_argument("--authentication-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--expected-sdk-version", default=PINNED_SDK_VERSION)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.verify_matrix is not None:
        matrix = verify_matrix(args.verify_matrix)
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
    if args.all_variants:
        destination, matrix = run_matrix(
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
    destination, result = run_diagnostic(
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
