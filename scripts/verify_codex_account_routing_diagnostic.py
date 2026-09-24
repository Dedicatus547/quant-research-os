#!/usr/bin/env python3
"""Offline verifier for content-addressed Codex account-routing diagnostics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import cast

from quantos.artifacts.store import regular_tree_files
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.account_routing_diagnostic import (
    derive_account_routing_classification,
)

REPORT_NAME = "account-routing-report.json"
MATRIX_NAME = "account-routing-matrix.json"
SOURCE_NAME = "upstream-source-audit.json"
REQUIRED_FILES = {REPORT_NAME, MATRIX_NAME, SOURCE_NAME}
CANDIDATE_ID = "openai-codex-0.156.1-p10-v3"
CANDIDATE_VERSION = "0.156.1"
CANONICAL_VERSION = "0.154.0"
CANDIDATE_BINARY_SHA256 = "0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
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


class AccountRoutingArtifactError(ValueError):
    """Raised when the immutable diagnostic artifact cannot be replayed offline."""


def _load_json(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AccountRoutingArtifactError(f"{label} JSON is invalid") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AccountRoutingArtifactError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AccountRoutingArtifactError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _verify_runtime_binding(scenario: dict[str, object], scenario_id: str) -> bool:
    expected_version = CANONICAL_VERSION if scenario_id == "A" else CANDIDATE_VERSION
    expected_profile = None if scenario_id == "A" else CANDIDATE_ID
    app_server_version = scenario.get("app_server_version")
    binary_hash = scenario.get("runtime_binary_sha256")
    runtime_verified = (
        scenario.get("requested_runtime_version") == expected_version
        and scenario.get("sdk_version") == expected_version
        and scenario.get("runtime_package_version") == expected_version
        and isinstance(app_server_version, str)
        and app_server_version.startswith(f"{expected_version} ")
        and isinstance(binary_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", binary_hash) is not None
        and (expected_version != CANDIDATE_VERSION or binary_hash == CANDIDATE_BINARY_SHA256)
        and scenario.get("expected_runtime_candidate_id") == expected_profile
    )
    return runtime_verified


def verify_account_routing_artifact(artifact_path: Path) -> dict[str, object]:
    """Recompute bindings and classification without auth, provider access, or network."""

    try:
        files = regular_tree_files(artifact_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise AccountRoutingArtifactError("diagnostic artifact path is unavailable") from error
    if {path.name for path in files} != REQUIRED_FILES:
        raise AccountRoutingArtifactError("diagnostic artifact file set is not exact")
    payloads = {path.name: path.read_bytes() for path in files}
    if any(marker in payload for payload in payloads.values() for marker in SECRET_MARKERS):
        raise AccountRoutingArtifactError("diagnostic artifact contains a prohibited secret marker")

    report_payload = payloads[REPORT_NAME]
    matrix_payload = payloads[MATRIX_NAME]
    source_payload = payloads[SOURCE_NAME]
    report = _load_json(report_payload, "report")
    matrix = _load_json(matrix_payload, "matrix")
    source = _load_json(source_payload, "source audit")
    report_hash = sha256_bytes(report_payload)
    matrix_hash = sha256_bytes(matrix_payload)
    source_hash = sha256_bytes(source_payload)
    if (
        artifact_path.name != f"sha256-{report_hash}"
        or canonical_json_bytes(report) != report_payload
        or canonical_json_bytes(matrix) != matrix_payload
        or canonical_json_bytes(source) != source_payload
    ):
        raise AccountRoutingArtifactError(
            "artifact canonical encoding or content address is invalid"
        )
    if (
        report.get("schema_version") != "fr03-codex-account-routing-diagnostic/v1"
        or report.get("candidate_runtime_candidate_id") != CANDIDATE_ID
        or report.get("candidate_sdk_version") != CANDIDATE_VERSION
        or report.get("candidate_runtime_package_version") != CANDIDATE_VERSION
        or report.get("model_scope") != "gpt-5.6-sol; not invoked"
        or report.get("p10_started") is not False
        or report.get("p10_score") is not None
        or report.get("matched_command_lifecycle_count") is not None
        or report.get("canonical_pin_changed") is not False
        or report.get("p10_contract_changed") is not False
        or report.get("fr03_status") != "NO_GO"
        or report.get("p14d_c_status") != "BLOCKED_UNIMPLEMENTED"
        or report.get("matrix_sha256") != matrix_hash
        or report.get("source_audit_sha256") != source_hash
        or report.get("artifact_file_hashes")
        != {MATRIX_NAME: matrix_hash, SOURCE_NAME: source_hash}
    ):
        raise AccountRoutingArtifactError("report bindings or stop boundary are invalid")

    run_id = report.get("run_id")
    if (
        not isinstance(run_id, str)
        or not re.fullmatch(r"fr03-codex-0\.156\.1-account-routing-[0-9]{8}-[0-9]{6}", run_id)
        or matrix.get("run_id") != run_id
        or matrix.get("schema_version") != "fr03-codex-account-routing-matrix/v1"
    ):
        raise AccountRoutingArtifactError("diagnostic run identity is invalid")
    implementation_commit = report.get("implementation_commit")
    if not isinstance(implementation_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", implementation_commit
    ):
        raise AccountRoutingArtifactError("implementation commit binding is invalid")

    profile = _object(report.get("normal_profile_audit"), "normal profile audit")
    if (
        profile.get("normal_codex_home_used_directly") is not False
        or not isinstance(profile.get("normal_auth_file_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(profile.get("normal_auth_file_sha256"))) is None
        or not isinstance(profile.get("config_projection_complete"), bool)
        or not isinstance(profile.get("config_projection_fields"), list)
        or not isinstance(profile.get("selected_account_workspace_id_presence"), str)
    ):
        raise AccountRoutingArtifactError("safe normal-home projection binding is invalid")
    scenarios_value = matrix.get("scenarios")
    if not isinstance(scenarios_value, list):
        raise AccountRoutingArtifactError("scenario matrix must be an array")
    scenarios = cast(list[object], scenarios_value)
    scenario_objects = [_object(value, "scenario") for value in scenarios]
    ids = [scenario.get("scenario_id") for scenario in scenario_objects]
    if ids not in (["A", "B", "C"], ["A", "B", "C", "D"]):
        raise AccountRoutingArtifactError("scenario order or matrix cardinality is invalid")
    auth_hash = profile["normal_auth_file_sha256"]
    for scenario in scenario_objects:
        scenario_id = cast(str, scenario["scenario_id"])
        expected_mode = {
            "A": "ISOLATED_AUTH_ONLY_0_154",
            "B": "ISOLATED_AUTH_ONLY_0_156_1",
            "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
            "D": "ISOLATED_MINIMUM_ROUTING_PREREQUISITE_0_156_1",
        }[scenario_id]
        if (
            scenario.get("auth_projection_sha256") != auth_hash
            or scenario.get("codex_home_mode") != expected_mode
            or scenario.get("thread_start_count") != 0
            or scenario.get("turn_start_count") != 0
            or scenario.get("provider_request_count") != 0
            or scenario.get("request_count_basis")
            != "DIAGNOSTIC_CALL_TRACE; no thread or turn API is invoked"
            or scenario.get("explicit_account_read_call_count") not in {0, 1}
            or scenario.get("runtime_identity_verified")
            is not _verify_runtime_binding(scenario, scenario_id)
        ):
            raise AccountRoutingArtifactError(
                "scenario runtime, isolation, or count binding is invalid"
            )
        if scenario.get("rpc_method") not in {None, "initialize", "account/read"}:
            raise AccountRoutingArtifactError("scenario contains an unexpected RPC method")
        if scenario.get("accounts_check_attempted") not in {"true", "false", "UNKNOWN"}:
            raise AccountRoutingArtifactError("accounts/check observation is invalid")
        if scenario.get("rpc_error_classification") not in {
            None,
            "DUPLICATE_WORKSPACE",
            "WORKSPACE_NOT_FOUND",
            "ORIGIN_POLICY_MISMATCH",
            "ROUTING_RESPONSE_INVALID",
            "ROUTING_TIMEOUT",
            "ACCOUNTS_CHECK_HTTP_FAILURE",
            "AUTH_STATE_INVALID",
            "REQUIREMENTS_MISMATCH",
            "NETWORK_PREREQUISITE_FAILED",
            "UNKNOWN_INTERNAL",
            "OTHER_RPC_FAILURE",
            "INCONCLUSIVE",
        }:
            raise AccountRoutingArtifactError("scenario error classification is invalid")
        if scenario.get("selected_account_workspace_id_presence") != profile.get(
            "selected_account_workspace_id_presence"
        ) or scenario.get("selected_account_workspace_id_sha256") != profile.get(
            "selected_account_workspace_id_sha256"
        ):
            raise AccountRoutingArtifactError("selected account identity projection disagrees")
        if scenario.get("rpc_error_message_sha256") is not None and not re.fullmatch(
            r"[0-9a-f]{64}", str(scenario.get("rpc_error_message_sha256"))
        ):
            raise AccountRoutingArtifactError("scenario error hash is invalid")
        if "rpc_error_message" in scenario or "raw_response" in scenario:
            raise AccountRoutingArtifactError(
                "scenario contains an unredacted RPC message or response"
            )
        if scenario_id == "A":
            if scenario.get("requested_runtime_version") != CANONICAL_VERSION:
                raise AccountRoutingArtifactError("scenario A is not the canonical baseline")
        elif scenario.get("requested_runtime_version") != CANDIDATE_VERSION:
            raise AccountRoutingArtifactError("candidate scenario is not bound to 0.156.1")

    if len(scenario_objects) == 4:
        b, c, d = scenario_objects[1], scenario_objects[2], scenario_objects[3]
        if (
            b.get("account_read_status") != "FAILED"
            or c.get("account_read_status") != "PASS"
            or d.get("config_sha256") != c.get("config_sha256")
            or not isinstance(c.get("config_projection_fields"), list)
            or not c.get("config_projection_fields")
            or d.get("config_projection_fields") != c.get("config_projection_fields")
            or d.get("config_projection_complete") is not True
            or d.get("account_read_status") not in {"PASS", "FAILED"}
        ):
            raise AccountRoutingArtifactError(
                "scenario D lacks an A/B/C-triggered prerequisite change"
            )
    elif (
        scenario_objects[1].get("account_read_status") == "FAILED"
        and scenario_objects[2].get("account_read_status") == "PASS"
        and scenario_objects[2].get("config_projection_complete") is True
        and bool(scenario_objects[2].get("config_projection_fields"))
    ):
        raise AccountRoutingArtifactError(
            "scenario D was required by the observed matrix difference"
        )

    try:
        classification = derive_account_routing_classification(scenario_objects)
    except (TypeError, ValueError) as error:
        raise AccountRoutingArtifactError("scenario evidence cannot be classified") from error
    candidate_isolated = scenario_objects[1]
    p10_eligible = (
        candidate_isolated.get("initialize_status") == "PASS"
        and candidate_isolated.get("account_read_status") == "PASS"
        and candidate_isolated.get("runtime_identity_verified") is True
    )
    if (
        report.get("diagnostic_classification") != classification
        or report.get("p10_eligible") is not p10_eligible
        or source.get("upstream_source_commits")
        != {
            "rust-v0.154.0": "6b9826e3aa83b1a5947db50f4332cb9c65f1b340",
            "rust-v0.156.1": "b412ff32c417f855c2b2d1581b77058eed87c84b",
        }
        or source.get("p10_contract_change") is not False
        or source.get("normalizer_or_evaluator_change") is not False
    ):
        raise AccountRoutingArtifactError("recomputed classification or source bindings disagree")

    return {
        "schema_version": "fr03-codex-account-routing-verification/v1",
        "artifact_hash": report_hash,
        "diagnostic_classification": classification,
        "scenario_count": len(scenario_objects),
        "p10_eligible": p10_eligible,
        "offline_verification": "PASS",
        "provider_request_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-run", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_account_routing_artifact(args.verify_run), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
