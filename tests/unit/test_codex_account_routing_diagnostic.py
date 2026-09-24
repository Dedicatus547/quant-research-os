from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from quantos.integrations.codex.account_routing_diagnostic import (
    classify_rpc_error,
    derive_account_routing_classification,
)


def _scenario(
    scenario_id: str,
    *,
    initialize_status: str = "PASS",
    account_read_status: str = "PASS",
    rpc_error_classification: str | None = None,
    rpc_error_code: int | None = None,
    rpc_error_type: str | None = None,
    rpc_error_message_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "scenario_id": scenario_id,
        "initialize_status": initialize_status,
        "account_read_status": account_read_status,
        "rpc_method": "account/read" if account_read_status == "FAILED" else None,
        "rpc_error_classification": rpc_error_classification,
        "rpc_error_code": rpc_error_code,
        "rpc_error_type": rpc_error_type,
        "rpc_error_message_sha256": rpc_error_message_sha256,
        "auth_projection_sha256": "a" * 64,
        "runtime_identity_verified": True,
        "config_projection_complete": True,
    }


@pytest.mark.parametrize(
    ("error_type", "rpc_code", "message", "expected"),
    [
        (
            "InternalRpcError",
            -32603,
            "duplicate workspace in routing discovery",
            "DUPLICATE_WORKSPACE",
        ),
        ("InternalRpcError", -32603, "backend origin mismatch", "ORIGIN_POLICY_MISMATCH"),
        (
            "InternalRpcError",
            -32603,
            "selected workspace missing from routing discovery",
            "WORKSPACE_NOT_FOUND",
        ),
        ("InternalRpcError", -32603, "missing routing field", "ROUTING_RESPONSE_INVALID"),
        (
            "InternalRpcError",
            -32603,
            "workspace routing discovery missing backend origin",
            "ROUTING_RESPONSE_INVALID",
        ),
        ("TimeoutError", None, "routing timed out", "ROUTING_TIMEOUT"),
        ("InternalRpcError", -32603, "accounts/check HTTP 500", "ACCOUNTS_CHECK_HTTP_FAILURE"),
        (
            "InternalRpcError",
            -32603,
            "workspace routing discovery unauthorized (401)",
            "AUTH_STATE_INVALID",
        ),
        (
            "InternalRpcError",
            -32603,
            "failed to reload workspace requirements",
            "REQUIREMENTS_MISMATCH",
        ),
        (
            "InternalRpcError",
            -32603,
            "required ChatGPT backend conflicts with workspace routing",
            "ORIGIN_POLICY_MISMATCH",
        ),
        ("ConnectError", None, "connection refused", "NETWORK_PREREQUISITE_FAILED"),
        ("InternalRpcError", -32603, "Internal server error", "UNKNOWN_INTERNAL"),
        ("InvalidRequestError", -32600, "bad request", "OTHER_RPC_FAILURE"),
    ],
)
def test_classify_rpc_error_uses_bounded_allowlisted_categories(
    error_type: str, rpc_code: int | None, message: str, expected: str
) -> None:
    assert classify_rpc_error(error_type=error_type, rpc_code=rpc_code, message=message) == expected


def test_diagnostic_matrix_recomputes_candidate_compatibility() -> None:
    scenarios = [_scenario("A"), _scenario("B"), _scenario("C")]

    assert derive_account_routing_classification(scenarios) == "ACCOUNT_ROUTING_COMPATIBLE"


def test_diagnostic_matrix_recomputes_isolation_incompatibility() -> None:
    scenarios = [
        _scenario("A"),
        _scenario("B", account_read_status="FAILED", rpc_error_classification="UNKNOWN_INTERNAL"),
        {**_scenario("C"), "config_projection_fields": ["chatgpt_base_url"]},
    ]

    assert derive_account_routing_classification(scenarios) == "ISOLATION_PROFILE_INCOMPATIBLE"


def test_diagnostic_matrix_does_not_infer_isolation_change_without_prerequisite_delta() -> None:
    scenarios = [
        _scenario("A"),
        _scenario("B", account_read_status="FAILED", rpc_error_classification="UNKNOWN_INTERNAL"),
        _scenario("C"),
    ]

    assert derive_account_routing_classification(scenarios) == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "fields",
    [["model_provider"], ["cli_auth_credentials_store"], ["chatgpt_base_url", "model_provider"]],
)
def test_diagnostic_matrix_requires_one_known_bootstrap_prerequisite(
    fields: list[str],
) -> None:
    scenarios = [
        _scenario("A"),
        _scenario("B", account_read_status="FAILED", rpc_error_classification="UNKNOWN_INTERNAL"),
        {**_scenario("C"), "config_projection_fields": fields},
    ]

    assert derive_account_routing_classification(scenarios) == "INCONCLUSIVE"


def test_diagnostic_matrix_recomputes_upstream_routing_failure() -> None:
    error = {
        "account_read_status": "FAILED",
        "rpc_error_classification": "DUPLICATE_WORKSPACE",
        "rpc_error_code": -32603,
        "rpc_error_type": "InternalRpcError",
        "rpc_error_message_sha256": "b" * 64,
        "auth_projection_sha256": "a" * 64,
    }
    scenarios = [
        _scenario("A"),
        {**_scenario("B", account_read_status="FAILED"), **error},
        {**_scenario("C", account_read_status="FAILED"), **error},
    ]

    assert derive_account_routing_classification(scenarios) == "UPSTREAM_ACCOUNT_ROUTING_FAILURE"


def test_diagnostic_matrix_accepts_isolated_routing_prerequisite_as_profile_cause() -> None:
    failed = {
        "account_read_status": "FAILED",
        "rpc_error_classification": "DUPLICATE_WORKSPACE",
        "rpc_error_code": -32603,
        "rpc_error_type": "InternalRpcError",
        "rpc_error_message_sha256": "b" * 64,
        "auth_projection_sha256": "a" * 64,
    }
    normal = {
        **_scenario("C", account_read_status="FAILED"),
        **failed,
        "config_projection_fields": ["chatgpt_base_url"],
    }
    isolated_minimum = {
        **_scenario("D"),
        "config_projection_fields": ["chatgpt_base_url"],
    }
    scenarios = [
        _scenario("A"),
        {**_scenario("B", account_read_status="FAILED"), **failed},
        normal,
        isolated_minimum,
    ]

    assert derive_account_routing_classification(scenarios) == "ISOLATION_PROFILE_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("error_classification", "expected"),
    [
        ("AUTH_STATE_INVALID", "AUTH_STATE_INVALID"),
        ("ORIGIN_POLICY_MISMATCH", "ORIGIN_POLICY_MISMATCH"),
        ("ROUTING_RESPONSE_INVALID", "ROUTING_RESPONSE_INVALID"),
        ("NETWORK_PREREQUISITE_FAILED", "NETWORK_PREREQUISITE_FAILED"),
    ],
)
def test_diagnostic_matrix_preserves_specific_candidate_failure(
    error_classification: str, expected: str
) -> None:
    error = {
        "account_read_status": "FAILED",
        "rpc_error_classification": error_classification,
        "rpc_error_code": -32603,
        "rpc_error_type": "InternalRpcError",
        "rpc_error_message_sha256": "b" * 64,
        "auth_projection_sha256": "a" * 64,
    }
    scenarios = [_scenario("A"), {"scenario_id": "B", **error}, {"scenario_id": "C", **error}]

    assert derive_account_routing_classification(scenarios) == expected


def test_diagnostic_matrix_requires_unique_known_scenarios() -> None:
    with pytest.raises(ValueError, match="unique strings"):
        derive_account_routing_classification([_scenario("A"), _scenario("A"), _scenario("C")])
    with pytest.raises(ValueError, match="contain A, B, C"):
        derive_account_routing_classification([_scenario("A"), _scenario("B")])
    with pytest.raises(ValueError, match="string-keyed mapping"):
        derive_account_routing_classification([cast(Mapping[str, object], {1: "not a string key"})])
