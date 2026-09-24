#!/usr/bin/env python3
"""Run or replay a bounded Codex account-routing diagnostic without model turns."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.account_routing_diagnostic import (
    classify_rpc_error,
    derive_account_routing_classification,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
ARTIFACT_ROOT = ROOT / "artifacts/diagnostics/codex-account-routing-0.156.1"
SCHEMA_VERSION = "fr03-codex-account-routing-diagnostic/v1"
RUN_ID_PREFIX = "fr03-codex-0.156.1-account-routing"
CANDIDATE_ID = "openai-codex-0.156.1-p10-v3"
CANDIDATE_VERSION = "0.156.1"
CANONICAL_VERSION = "0.154.0"
CANDIDATE_BINARY_SHA256 = "0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
UPSTREAM_COMMITS = {
    "rust-v0.154.0": "6b9826e3aa83b1a5947db50f4332cb9c65f1b340",
    "rust-v0.156.1": "b412ff32c417f855c2b2d1581b77058eed87c84b",
}
MINIMUM_CONFIG_KEYS = ("chatgpt_base_url", "model_provider", "cli_auth_credentials_store")
MANAGED_ENVIRONMENT_NAMES = (
    "CODEX_MANAGED_CONFIG_PATH",
    "CODEX_MANAGED_REQUIREMENTS_PATH",
    "CODEX_REQUIREMENTS_PATH",
)
AUTH_AND_ROUTING_ENVIRONMENT_NAMES = (
    "CODEX_API_KEY",
    "CODEX_HOME",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    *MANAGED_ENVIRONMENT_NAMES,
)
SECRET_MARKERS = (
    b"Authorization:",
    b"Bearer ",
    b"Cookie:",
    b"access_token",
    b"refresh_token",
    b'"tokens"',
    b'"OPENAI_API_KEY"',
    b'"accessToken"',
    b'"refreshToken"',
    b'"Authorization"',
    b'"Cookie"',
    b"TUSHARE_TOKEN=",
    b"sk-proj-",
    b"ghp_",
    b"gho_",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a string-keyed JSON object")
    return cast(dict[str, object], value)


def _safe_config_projection(config: dict[str, object]) -> tuple[bytes, bool, list[str]]:
    """Serialize only supported auth/routing selectors, omitting model and tool settings."""

    present = [key for key in MINIMUM_CONFIG_KEYS if key in config]
    unsupported = any(key in config for key in ("model_providers", "requirements"))
    lines: list[str] = []
    for key in MINIMUM_CONFIG_KEYS:
        value = config.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return b"", False, present
        if key == "chatgpt_base_url" and not _safe_origin_value(value):
            return b"", False, present
        if key == "model_provider" and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value) is None:
            return b"", False, present
        if key == "cli_auth_credentials_store" and value not in {"file", "keyring", "auto"}:
            return b"", False, present
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    return ("\n".join(lines) + ("\n" if lines else "")).encode(), not unsupported, present


def _safe_origin_value(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _selected_workspace_projection(auth: dict[str, object]) -> tuple[str, str | None]:
    tokens_value = auth.get("tokens")
    tokens = tokens_value if isinstance(tokens_value, dict) else {}
    candidates = (
        tokens.get("chatgpt_account_id"),
        tokens.get("account_id"),
        auth.get("chatgpt_account_id"),
        auth.get("account_id"),
    )
    for value in candidates:
        if isinstance(value, str) and value:
            return "PRESENT", _sha256(value.encode("utf-8"))
    return "ABSENT", None


def _auth_classification(auth: dict[str, object]) -> str:
    tokens_value = auth.get("tokens")
    tokens = tokens_value if isinstance(tokens_value, dict) else {}
    if any(
        isinstance(tokens.get(name), str) and tokens.get(name)
        for name in ("access_token", "refresh_token")
    ):
        return "CHATGPT_AUTH_PRESENT"
    api_key = auth.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key:
        return "API_KEY_AUTH_PRESENT"
    return "AUTH_STATE_UNAVAILABLE"


def _credential_store_classification(config: dict[str, object]) -> str:
    mode = config.get("cli_auth_credentials_store")
    if mode == "file":
        return "FILE"
    if mode == "keyring":
        return "KEYRING"
    return "DEFAULT_OR_UNSET"


def _normal_profile_audit(
    normal_home: Path,
) -> tuple[dict[str, object], Path, bytes, str, str | None]:
    if normal_home.is_symlink() or not normal_home.is_dir():
        raise ValueError("normal user CODEX_HOME must be a real directory")
    auth_path = normal_home / "auth.json"
    config_path = normal_home / "config.toml"
    if auth_path.is_symlink() or not auth_path.is_file():
        raise ValueError("normal user auth.json must be a regular file")
    auth_bytes = auth_path.read_bytes()
    auth_data = _json_object(json.loads(auth_bytes), "auth.json")
    selected_status, selected_hash = _selected_workspace_projection(auth_data)
    config_bytes = (
        config_path.read_bytes() if config_path.is_file() and not config_path.is_symlink() else b""
    )
    config_data = tomllib.loads(config_bytes.decode("utf-8")) if config_bytes else {}
    projection_bytes, projection_complete, projected_fields = _safe_config_projection(config_data)
    names = {path.name for path in normal_home.iterdir()}
    parent_env = {
        name: ("PRESENT" if name in os.environ else "ABSENT")
        for name in AUTH_AND_ROUTING_ENVIRONMENT_NAMES
    }
    configured_provider = config_data.get("model_provider")
    audit: dict[str, object] = {
        "normal_codex_home_used_directly": False,
        "normal_auth_file_sha256": _sha256(auth_bytes),
        "normal_config_file_present": config_path.is_file(),
        "normal_config_sha256": _sha256(config_bytes) if config_bytes else None,
        "config_projection_sha256": _sha256(projection_bytes),
        "config_projection_complete": projection_complete,
        "config_projection_fields": projected_fields,
        "normal_config_bootstrap_fields": {
            key: ("PRESENT" if key in config_data else "ABSENT")
            for key in (
                "chatgpt_base_url",
                "model_provider",
                "model_providers",
                "requirements",
                "cli_auth_credentials_store",
            )
        },
        "credential_store_mode": _credential_store_classification(config_data),
        "provider_selection_classification": (
            "MODEL_PROVIDER_CONFIGURED"
            if isinstance(configured_provider, str) and configured_provider
            else "DEFAULT_OR_UNSET"
        ),
        "auth_projection_classification": _auth_classification(auth_data),
        "auth_mode_classification": (
            "CHATGPT"
            if auth_data.get("auth_mode") == "chatgpt"
            else "API_KEY"
            if auth_data.get("auth_mode") == "api_key"
            else "OTHER_OR_UNSET"
        ),
        "api_key_credential_present": bool(auth_data.get("OPENAI_API_KEY")),
        "selected_account_workspace_id_presence": selected_status,
        "selected_account_workspace_id_sha256": selected_hash,
        "workspace_metadata_entry_count": sum("workspace" in name.casefold() for name in names),
        "normal_user_mcp_config": "PRESENT_NOT_PROJECTED"
        if "mcp_servers" in config_data
        else "ABSENT",
        "normal_user_project_config": "PRESENT_NOT_PROJECTED"
        if "projects" in config_data
        else "ABSENT",
        "normal_user_model_config": "PRESENT_NOT_PROJECTED" if "model" in config_data else "ABSENT",
        "parent_managed_environment_presence": parent_env,
        "sdk_host_environment_allowlist": ["CODEX_HOME", "LANG", "PATH", "TZ"],
    }
    return audit, auth_path, projection_bytes, selected_status, selected_hash


def _error_details(error: BaseException) -> tuple[str, int | None, str, str, int]:
    error_type = type(error).__name__
    code_value = getattr(error, "code", None)
    code = code_value if type(code_value) is int else None
    message_value = getattr(error, "message", None)
    message = message_value if isinstance(message_value, str) else str(error)
    encoded = message.encode("utf-8", errors="replace")
    bounded = encoded[:65_536]
    classification = classify_rpc_error(error_type=error_type, rpc_code=code, message=message)
    return error_type, code, classification, _sha256(bounded), len(encoded)


def _run_single_scenario(args: argparse.Namespace) -> int:
    initial_path = os.environ.get("PATH", os.defpath)
    os.environ.clear()
    os.environ.update(
        {
            "CODEX_HOME": args.codex_home,
            "HOME": args.codex_home,
            "LANG": "C.UTF-8",
            "PATH": initial_path,
            "TZ": "UTC",
        }
    )
    started = time.monotonic()
    result: dict[str, object] = {
        "scenario_id": args.single_scenario,
        "initialize_status": "NOT_REACHED",
        "initialize_elapsed_ms": None,
        "account_read_status": "NOT_REACHED",
        "account_read_elapsed_ms": None,
        "rpc_method": None,
        "rpc_error_code": None,
        "rpc_error_type": None,
        "rpc_error_classification": None,
        "rpc_error_message_sha256": None,
        "rpc_error_message_length": None,
        "account_presence": "UNKNOWN",
        "accounts_check_attempted": "false" if args.single_scenario == "A" else "UNKNOWN",
        "accounts_check_observability": (
            "RUNTIME_0_154_HAS_NO_ROUTING_DISCOVERY"
            if args.single_scenario == "A"
            else "PUBLIC_SURFACE_UNAVAILABLE"
        ),
        "selected_account_workspace_id_presence": args.selected_workspace_id_presence,
        "selected_account_workspace_id_sha256": (
            None
            if args.selected_workspace_id_sha256 == "NONE"
            else args.selected_workspace_id_sha256
        ),
        "workspace_routing_schema": "UNKNOWN",
        "workspace_routing_result": "UNKNOWN",
        "thread_start_count": 0,
        "turn_start_count": 0,
        "provider_request_count": 0,
        "elapsed_ms": 0,
        "host_environment_names": ["CODEX_HOME", "HOME", "LANG", "PATH", "TZ"],
        "request_count_basis": "DIAGNOSTIC_CALL_TRACE; no thread or turn API is invoked",
    }
    client = None
    try:
        from importlib.metadata import version

        import openai_codex
        from openai_codex import Codex, CodexConfig
        from openai_codex.client import _installed_codex_path

        executable = _installed_codex_path()
        result["sdk_version"] = openai_codex.__version__
        result["runtime_package_version"] = version("openai-codex-cli-bin")
        result["runtime_binary_sha256"] = _sha256(executable.read_bytes())
        result["platform"] = f"{platform.system().lower()}-{platform.machine().lower()}"
        initialize_started = time.monotonic()
        try:
            client = Codex(config=CodexConfig(cwd="/tmp"))
        except BaseException as error:
            error_type, code, category, message_hash, message_length = _error_details(error)
            result.update(
                {
                    "initialize_status": "FAILED",
                    "initialize_elapsed_ms": round((time.monotonic() - initialize_started) * 1000),
                    "rpc_method": "initialize",
                    "rpc_error_code": code,
                    "rpc_error_type": error_type,
                    "rpc_error_classification": category,
                    "rpc_error_message_sha256": message_hash,
                    "rpc_error_message_length": message_length,
                }
            )
        else:
            result["initialize_status"] = "PASS"
            result["initialize_elapsed_ms"] = round((time.monotonic() - initialize_started) * 1000)
            metadata = client.metadata
            server_info = getattr(metadata, "serverInfo", None) or getattr(
                metadata, "server_info", None
            )
            version_text = getattr(server_info, "version", None)
            result["app_server_version"] = version_text if isinstance(version_text, str) else None
            result["reported_app_server_version_sha256"] = (
                _sha256(version_text.encode()) if isinstance(version_text, str) else None
            )
            if result["rpc_error_classification"] is None:
                account_started = time.monotonic()
                try:
                    account_response = client.account(refresh_token=False)
                except BaseException as error:
                    error_type, code, category, message_hash, message_length = _error_details(error)
                    result.update(
                        {
                            "account_read_status": "FAILED",
                            "account_read_elapsed_ms": round(
                                (time.monotonic() - account_started) * 1000
                            ),
                            "rpc_method": "account/read",
                            "rpc_error_code": code,
                            "rpc_error_type": error_type,
                            "rpc_error_classification": category,
                            "rpc_error_message_sha256": message_hash,
                            "rpc_error_message_length": message_length,
                        }
                    )
                else:
                    result["account_read_status"] = "PASS"
                    result["account_read_elapsed_ms"] = round(
                        (time.monotonic() - account_started) * 1000
                    )
                    account = getattr(account_response, "account", None)
                    result["account_presence"] = "PRESENT" if account is not None else "ABSENT"
                    fields = getattr(type(account_response), "model_fields", {})
                    aliases = (
                        {getattr(field, "alias", None) for field in fields.values()}
                        if isinstance(fields, dict)
                        else set()
                    )
                    schema_present = "workspaceRouting" in aliases or any(
                        key in fields for key in ("workspaceRouting", "workspace_routing")
                    )
                    routing = getattr(account_response, "workspaceRouting", None)
                    if routing is None:
                        routing = getattr(account_response, "workspace_routing", None)
                    result["workspace_routing_schema"] = (
                        "SUPPORTED" if schema_present else "UNSUPPORTED_BY_RUNTIME"
                    )
                    result["workspace_routing_result"] = (
                        "PRESENT" if routing is not None else "NULL_OR_ABSENT"
                    )
                    if routing is not None:
                        result["accounts_check_attempted"] = "true"
                        result["accounts_check_observability"] = "PUBLIC_ROUTING_RESPONSE"
                    elif args.selected_workspace_id_presence == "ABSENT":
                        result["accounts_check_attempted"] = "false"
                        result["accounts_check_observability"] = "NO_SELECTED_WORKSPACE_ID"
    except BaseException as error:
        error_type, code, category, message_hash, message_length = _error_details(error)
        result.update(
            {
                "worker_error_type": error_type,
                "rpc_error_code": code,
                "rpc_error_classification": category,
                "rpc_error_message_sha256": message_hash,
                "rpc_error_message_length": message_length,
            }
        )
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0


def _source_audit() -> dict[str, object]:
    return {
        "schema_version": "fr03-codex-account-routing-source-audit/v1",
        "upstream_source_commits": UPSTREAM_COMMITS,
        "reviewed_source_paths": {
            "rust-v0.154.0": [
                "codex-rs/app-server/src/request_processors/account_processor.rs",
                "codex-rs/app-server-protocol/src/protocol/v2/account.rs",
                "sdk/python/src/openai_codex/client.py",
            ],
            "rust-v0.156.1": [
                "codex-rs/app-server/src/request_processors/account_processor.rs",
                "codex-rs/app-server/src/request_processors/account_processor/workspace_routing.rs",
                "codex-rs/backend-client/src/client.rs",
                "codex-rs/backend-client/src/types.rs",
                "codex-rs/app-server-protocol/src/protocol/v2/account.rs",
                "sdk/python/src/openai_codex/client.py",
            ],
        },
        "upstream_pr": "https://github.com/openai/codex/pull/45529",
        "findings": [
            "0.154.0 response has account/requiresOpenaiAuth; it has no workspaceRouting field.",
            "0.156.1 starts discovery at startup; account/read awaits its result.",
            "Saved ChatGPT auth with a selected workspace calls accounts/check.",
            "Signed-out, API-key, and no-selected-workspace cases need no accounts/check.",
            "Discovery or origin failures return account/read errors; the runtime fails closed.",
            "The account processor maps workspace-routing failures to JSON-RPC internal_error.",
            "The returned code is -32603.",
            "DuplicateWorkspace means multiple accounts/check records match the selected account.",
            "Zero matching records maps to selected-workspace-missing.",
            "The backend client issues GET /api/codex/accounts/check or GET /wham/accounts/check.",
            "Malformed response decoding is a routing-discovery failure.",
            "Routing validates the discovered HTTPS origin against required chatgpt_base_url.",
            "Discovery has a 15-second timeout and may do normal auth recovery after unauthorized.",
            "Codex construction initializes the app-server; account() sends account/read.",
            "That SDK call sets refreshToken=false.",
        ],
        "error_mapping": {
            "duplicate_workspace": (
                "DUPLICATE_WORKSPACE; multiple accounts/check matches for selected account id"
            ),
            "workspace_not_found": "WORKSPACE_NOT_FOUND",
            "origin_mismatch": "ORIGIN_POLICY_MISMATCH",
            "malformed_or_missing_routing_fields": "ROUTING_RESPONSE_INVALID",
            "timeout": "ROUTING_TIMEOUT",
            "accounts_check_http_failure": "ACCOUNTS_CHECK_HTTP_FAILURE",
            "requirements_reload_failure": "REQUIREMENTS_MISMATCH",
            "unauthorized_or_auth_refresh_failure": "AUTH_STATE_INVALID",
            "unclassified_json_rpc_-32603": "UNKNOWN_INTERNAL",
        },
        "p10_contract_change": False,
        "normalizer_or_evaluator_change": False,
    }


def _git_commit_and_clean() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    if status:
        raise ValueError("diagnostic requires a clean worktree")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("implementation commit identity is invalid")
    return commit


def _worker_command(
    scenario_id: str,
    codex_home: Path,
    selected_workspace_id_presence: str,
    selected_workspace_id_sha256: str | None,
    *,
    candidate: bool,
) -> list[str]:
    worker_args = [
        str(ROOT / "scripts/codex_account_routing_diagnostic.py"),
        "--single-scenario",
        scenario_id,
        "--codex-home",
        str(codex_home),
        "--selected-workspace-id-presence",
        selected_workspace_id_presence,
        "--selected-workspace-id-sha256",
        selected_workspace_id_sha256 or "NONE",
    ]
    if candidate:
        return [
            "uv",
            "run",
            "--offline",
            "--no-project",
            "--python",
            "3.11",
            "--with",
            "openai-codex==0.156.1",
            "--with",
            "openai-codex-cli-bin==0.156.1",
            "python",
            *worker_args,
        ]
    return [sys.executable, *worker_args]


def _invoke_worker(
    scenario_id: str,
    codex_home: Path,
    auth_sha256: str,
    selected_workspace_id_presence: str,
    selected_workspace_id_sha256: str | None,
    config_projection_fields: list[str],
    config_projection_complete: bool,
    *,
    candidate: bool,
) -> dict[str, object]:
    environment = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(codex_home),
        "LANG": "C.UTF-8",
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONPATH": str(SOURCE_ROOT),
        "TZ": "UTC",
        "UV_CACHE_DIR": "/tmp/quantos-uv-cache",
    }
    command = _worker_command(
        scenario_id,
        codex_home,
        selected_workspace_id_presence,
        selected_workspace_id_sha256,
        candidate=candidate,
    )
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd="/tmp",
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return {
            "scenario_id": scenario_id,
            "initialize_status": "NOT_REACHED",
            "account_read_status": "NOT_REACHED",
            "rpc_method": None,
            "rpc_error_code": None,
            "rpc_error_type": "DiagnosticTimeout",
            "rpc_error_classification": "NETWORK_PREREQUISITE_FAILED",
            "rpc_error_message_sha256": _sha256(b"bounded account-routing diagnostic timeout"),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "thread_start_count": 0,
            "turn_start_count": 0,
            "provider_request_count": 0,
            "explicit_account_read_call_count": 0,
            "worker_stderr_sha256": _sha256(stderr[:65_536]),
            "auth_projection_sha256": auth_sha256,
            "config_sha256": sha256_bytes((codex_home / "config.toml").read_bytes())
            if (codex_home / "config.toml").is_file()
            else None,
            "config_projection_complete": config_projection_complete,
            "config_projection_fields": config_projection_fields,
            "selected_account_workspace_id_presence": selected_workspace_id_presence,
            "selected_account_workspace_id_sha256": selected_workspace_id_sha256,
            "codex_home_mode": {
                "A": "ISOLATED_AUTH_ONLY_0_154",
                "B": "ISOLATED_AUTH_ONLY_0_156_1",
                "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
                "D": "ISOLATED_MINIMUM_ROUTING_PREREQUISITE_0_156_1",
            }[scenario_id],
        }
    if process.returncode != 0:
        return {
            "scenario_id": scenario_id,
            "initialize_status": "NOT_REACHED",
            "account_read_status": "NOT_REACHED",
            "rpc_method": None,
            "rpc_error_code": None,
            "rpc_error_type": "DiagnosticWorkerFailure",
            "rpc_error_classification": "INCONCLUSIVE",
            "rpc_error_message_sha256": _sha256(b"diagnostic worker failed"),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "thread_start_count": 0,
            "turn_start_count": 0,
            "provider_request_count": 0,
            "explicit_account_read_call_count": 0,
            "worker_stderr_sha256": _sha256(stderr[:65_536]),
            "worker_stdout_sha256": _sha256(stdout[:65_536]),
            "auth_projection_sha256": auth_sha256,
            "config_sha256": sha256_bytes((codex_home / "config.toml").read_bytes())
            if (codex_home / "config.toml").is_file()
            else None,
            "config_projection_complete": config_projection_complete,
            "config_projection_fields": config_projection_fields,
            "selected_account_workspace_id_presence": selected_workspace_id_presence,
            "selected_account_workspace_id_sha256": selected_workspace_id_sha256,
            "codex_home_mode": {
                "A": "ISOLATED_AUTH_ONLY_0_154",
                "B": "ISOLATED_AUTH_ONLY_0_156_1",
                "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
                "D": "ISOLATED_MINIMUM_ROUTING_PREREQUISITE_0_156_1",
            }[scenario_id],
        }
    try:
        result = _json_object(json.loads(stdout), "diagnostic worker result")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        result = {
            "scenario_id": scenario_id,
            "initialize_status": "NOT_REACHED",
            "account_read_status": "NOT_REACHED",
            "rpc_method": None,
            "rpc_error_code": None,
            "rpc_error_type": "DiagnosticOutputInvalid",
            "rpc_error_classification": "INCONCLUSIVE",
            "rpc_error_message_sha256": _sha256(b"diagnostic worker output invalid"),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "thread_start_count": 0,
            "turn_start_count": 0,
            "provider_request_count": 0,
            "explicit_account_read_call_count": 0,
            "auth_projection_sha256": auth_sha256,
            "config_sha256": sha256_bytes((codex_home / "config.toml").read_bytes())
            if (codex_home / "config.toml").is_file()
            else None,
            "config_projection_complete": config_projection_complete,
            "config_projection_fields": config_projection_fields,
            "selected_account_workspace_id_presence": selected_workspace_id_presence,
            "selected_account_workspace_id_sha256": selected_workspace_id_sha256,
            "codex_home_mode": {
                "A": "ISOLATED_AUTH_ONLY_0_154",
                "B": "ISOLATED_AUTH_ONLY_0_156_1",
                "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
                "D": "ISOLATED_MINIMUM_ROUTING_PREREQUISITE_0_156_1",
            }[scenario_id],
        }
    result["auth_projection_sha256"] = auth_sha256
    result["config_sha256"] = (
        sha256_bytes((codex_home / "config.toml").read_bytes())
        if (codex_home / "config.toml").is_file()
        else None
    )
    result["config_projection_complete"] = config_projection_complete
    result["config_projection_fields"] = config_projection_fields
    result["codex_home_mode"] = {
        "A": "ISOLATED_AUTH_ONLY_0_154",
        "B": "ISOLATED_AUTH_ONLY_0_156_1",
        "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
        "D": "ISOLATED_MINIMUM_ROUTING_PREREQUISITE_0_156_1",
    }[scenario_id]
    result["explicit_account_read_call_count"] = (
        1 if result.get("account_read_status") in {"PASS", "FAILED"} else 0
    )
    return result


def _run_scenario(
    scenario_id: str,
    auth_path: Path,
    auth_sha256: str,
    selected_workspace_id_presence: str,
    selected_workspace_id_sha256: str | None,
    config_projection: bytes,
    config_projection_fields: list[str],
    config_projection_complete: bool,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix=f"quantos-codex-route-{scenario_id.lower()}-"
    ) as raw_home:
        codex_home = Path(raw_home)
        auth_projection = codex_home / "auth.json"
        auth_projection.write_bytes(auth_path.read_bytes())
        auth_projection.chmod(0o600)
        if scenario_id in {"C", "D"}:
            (codex_home / "config.toml").write_bytes(config_projection)
        result = _invoke_worker(
            scenario_id,
            codex_home,
            auth_sha256,
            selected_workspace_id_presence,
            selected_workspace_id_sha256,
            config_projection_fields,
            config_projection_complete,
            candidate=scenario_id != "A",
        )
        result["codex_home_entry_classification"] = sorted(
            path.name for path in codex_home.iterdir()
        )
        result["requested_runtime_version"] = (
            CANONICAL_VERSION if scenario_id == "A" else CANDIDATE_VERSION
        )
        result["expected_runtime_candidate_id"] = None if scenario_id == "A" else CANDIDATE_ID
        return result


def _runtime_identity_verified(scenario: dict[str, object]) -> bool:
    requested = scenario.get("requested_runtime_version")
    sdk_version = scenario.get("sdk_version")
    runtime_package_version = scenario.get("runtime_package_version")
    app_server_version = scenario.get("app_server_version")
    binary_hash = scenario.get("runtime_binary_sha256")
    if requested not in {CANONICAL_VERSION, CANDIDATE_VERSION}:
        return False
    if sdk_version != requested or runtime_package_version != requested:
        return False
    if not isinstance(app_server_version, str) or not app_server_version.startswith(
        f"{requested} "
    ):
        return False
    if not isinstance(binary_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", binary_hash):
        return False
    return requested != CANDIDATE_VERSION or binary_hash == CANDIDATE_BINARY_SHA256


def _secret_scan(contents: list[bytes]) -> None:
    if any(marker in payload for payload in contents for marker in SECRET_MARKERS):
        raise ValueError("diagnostic artifact secret scan failed")


def _publish_artifact(
    report: dict[str, object], matrix: dict[str, object], source_audit: dict[str, object]
) -> tuple[str, Path]:
    matrix_bytes = canonical_json_bytes(matrix)
    source_bytes = canonical_json_bytes(source_audit)
    report["artifact_file_hashes"] = {
        "account-routing-matrix.json": sha256_bytes(matrix_bytes),
        "upstream-source-audit.json": sha256_bytes(source_bytes),
    }
    report_bytes = canonical_json_bytes(report)
    _secret_scan([matrix_bytes, source_bytes, report_bytes])
    report_hash = sha256_bytes(report_bytes)
    destination = ARTIFACT_ROOT / f"sha256-{report_hash}"
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("content-addressed diagnostic destination already exists")
    destination.mkdir()
    (destination / "account-routing-matrix.json").write_bytes(matrix_bytes)
    (destination / "upstream-source-audit.json").write_bytes(source_bytes)
    (destination / "account-routing-report.json").write_bytes(report_bytes)
    return report_hash, destination


def _run_matrix(run_id: str) -> dict[str, object]:
    implementation_commit = _git_commit_and_clean()
    normal_home = Path.home() / ".codex"
    profile_audit, auth_path, config_projection, selected_status, selected_hash = (
        _normal_profile_audit(normal_home)
    )
    auth_hash = cast(str, profile_audit["normal_auth_file_sha256"])
    auth_stat = auth_path.stat()
    scenarios = [
        _run_scenario(
            "A",
            auth_path,
            auth_hash,
            selected_status,
            selected_hash,
            config_projection,
            [],
            True,
        ),
        _run_scenario(
            "B",
            auth_path,
            auth_hash,
            selected_status,
            selected_hash,
            config_projection,
            [],
            profile_audit["config_projection_complete"] is True,
        ),
        _run_scenario(
            "C",
            auth_path,
            auth_hash,
            selected_status,
            selected_hash,
            config_projection,
            profile_audit["config_projection_fields"],
            profile_audit["config_projection_complete"] is True,
        ),
    ]
    if (
        scenarios[1].get("account_read_status") == "FAILED"
        and scenarios[2].get("account_read_status") == "PASS"
        and profile_audit["config_projection_complete"] is True
        and bool(profile_audit["config_projection_fields"])
    ):
        scenarios.append(
            _run_scenario(
                "D",
                auth_path,
                auth_hash,
                selected_status,
                selected_hash,
                config_projection,
                profile_audit["config_projection_fields"],
                profile_audit["config_projection_complete"] is True,
            )
        )
    final_auth_stat = auth_path.stat()
    if (
        _sha256(auth_path.read_bytes()) != auth_hash
        or final_auth_stat.st_mtime_ns != auth_stat.st_mtime_ns
        or final_auth_stat.st_size != auth_stat.st_size
    ):
        raise ValueError("normal user auth.json changed during the read-only diagnostic")

    for scenario in scenarios:
        scenario["runtime_identity_verified"] = _runtime_identity_verified(scenario)
        if (
            scenario.get("scenario_id") in {"B", "C", "D"}
            and scenario.get("accounts_check_attempted") == "UNKNOWN"
        ):
            error = scenario.get("rpc_error_classification")
            if error in {
                "DUPLICATE_WORKSPACE",
                "WORKSPACE_NOT_FOUND",
                "ORIGIN_POLICY_MISMATCH",
                "ROUTING_RESPONSE_INVALID",
                "ROUTING_TIMEOUT",
                "ACCOUNTS_CHECK_HTTP_FAILURE",
                "REQUIREMENTS_MISMATCH",
            }:
                scenario["accounts_check_attempted"] = "true"
                scenario["accounts_check_observability"] = "INFERRED_FROM_BOUNDED_ROUTING_ERROR"
    classification = derive_account_routing_classification(scenarios)
    matrix: dict[str, object] = {
        "schema_version": "fr03-codex-account-routing-matrix/v1",
        "run_id": run_id,
        "scenarios": scenarios,
    }
    source_audit = _source_audit()
    candidate_isolated = scenarios[1]
    p10_eligible = (
        candidate_isolated.get("initialize_status") == "PASS"
        and candidate_isolated.get("account_read_status") == "PASS"
        and candidate_isolated.get("runtime_identity_verified") is True
    )
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "implementation_commit": implementation_commit,
        "candidate_runtime_candidate_id": CANDIDATE_ID,
        "candidate_sdk_version": CANDIDATE_VERSION,
        "candidate_runtime_package_version": CANDIDATE_VERSION,
        "model_scope": "gpt-5.6-sol; not invoked",
        "source_audit_sha256": sha256_bytes(canonical_json_bytes(source_audit)),
        "matrix_sha256": sha256_bytes(canonical_json_bytes(matrix)),
        "normal_profile_audit": profile_audit,
        "diagnostic_classification": classification,
        "p10_eligible": p10_eligible,
        "p10_started": False,
        "p10_score": None,
        "matched_command_lifecycle_count": None,
        "canonical_pin_changed": False,
        "p10_contract_changed": False,
        "fr03_status": "NO_GO",
        "p14d_c_status": "BLOCKED_UNIMPLEMENTED",
    }
    report_hash, destination = _publish_artifact(report, matrix, source_audit)
    return {
        "artifact_hash": report_hash,
        "artifact_path": str(destination.relative_to(ROOT)),
        "diagnostic_classification": classification,
        "p10_eligible": p10_eligible,
        "implementation_commit": implementation_commit,
        "scenario_summaries": [
            {
                "scenario_id": scenario.get("scenario_id"),
                "initialize_status": scenario.get("initialize_status"),
                "account_read_status": scenario.get("account_read_status"),
                "rpc_error_code": scenario.get("rpc_error_code"),
                "rpc_error_type": scenario.get("rpc_error_type"),
                "rpc_error_classification": scenario.get("rpc_error_classification"),
                "accounts_check_attempted": scenario.get("accounts_check_attempted"),
                "elapsed_ms": scenario.get("elapsed_ms"),
                "runtime_identity_verified": scenario.get("runtime_identity_verified"),
                "thread_start_count": scenario.get("thread_start_count"),
                "turn_start_count": scenario.get("turn_start_count"),
                "provider_request_count": scenario.get("provider_request_count"),
            }
            for scenario in scenarios
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single-scenario", choices=("A", "B", "C", "D"))
    parser.add_argument("--codex-home")
    parser.add_argument(
        "--selected-workspace-id-presence", choices=("PRESENT", "ABSENT", "UNKNOWN")
    )
    parser.add_argument("--selected-workspace-id-sha256")
    parser.add_argument("--run-matrix", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.single_scenario is not None:
        if (
            args.codex_home is None
            or args.selected_workspace_id_presence is None
            or args.selected_workspace_id_sha256 is None
        ):
            parser.error(
                "single scenario requires CODEX_HOME and selected workspace classification"
            )
        return _run_single_scenario(args)
    if not args.run_matrix:
        parser.error("choose --run-matrix or --single-scenario")
    run_id = args.run_id or f"{RUN_ID_PREFIX}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    if not re.fullmatch(r"fr03-codex-0\.156\.1-account-routing-[0-9]{8}-[0-9]{6}", run_id):
        parser.error("run id does not match the immutable diagnostic format")
    print(json.dumps(_run_matrix(run_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
