"""Bounded classification rules for Codex account-routing preflight evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

AccountRoutingClassification = Literal[
    "ACCOUNT_ROUTING_COMPATIBLE",
    "ISOLATION_PROFILE_INCOMPATIBLE",
    "UPSTREAM_ACCOUNT_ROUTING_FAILURE",
    "AUTH_STATE_INVALID",
    "ORIGIN_POLICY_MISMATCH",
    "ROUTING_RESPONSE_INVALID",
    "NETWORK_PREREQUISITE_FAILED",
    "INCONCLUSIVE",
]

RpcErrorClassification = Literal[
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
]

_ROUTING_RPC_ERRORS = frozenset(
    {
        "DUPLICATE_WORKSPACE",
        "WORKSPACE_NOT_FOUND",
        "ORIGIN_POLICY_MISMATCH",
        "ROUTING_RESPONSE_INVALID",
        "ROUTING_TIMEOUT",
        "ACCOUNTS_CHECK_HTTP_FAILURE",
        "REQUIREMENTS_MISMATCH",
    }
)


def classify_rpc_error(
    *,
    error_type: str,
    rpc_code: int | None,
    message: str,
) -> RpcErrorClassification:
    """Reduce an in-memory SDK error message to a bounded, allowlisted category."""

    text = message.casefold()[:16_384]
    error_name = error_type.casefold()
    if "duplicate workspace" in text:
        return "DUPLICATE_WORKSPACE"
    if any(
        marker in text
        for marker in (
            "origin mismatch",
            "backend origin mismatch",
            "conflicts with workspace routing",
        )
    ):
        return "ORIGIN_POLICY_MISMATCH"
    if any(
        marker in text
        for marker in (
            "workspace not found",
            "workspace does not exist",
            "selected workspace missing from routing discovery",
        )
    ):
        return "WORKSPACE_NOT_FOUND"
    if any(
        marker in text
        for marker in (
            "requirements mismatch",
            "required backend",
            "failed to reload workspace requirements",
        )
    ):
        return "REQUIREMENTS_MISMATCH"
    if any(
        marker in text
        for marker in (
            "malformed",
            "missing routing",
            "invalid routing response",
            "routing discovery missing backend origin",
            "invalid account routing override",
            "must return an origin",
            "invalid workspace backend url",
            "invalid backend origin",
        )
    ):
        return "ROUTING_RESPONSE_INVALID"
    if "timeout" in text or "timed out" in text:
        return "ROUTING_TIMEOUT"
    if any(
        marker in text
        for marker in (
            "unauthorized",
            "invalid_grant",
            "refresh token",
            "authentication expired",
            "http 401",
            "http 403",
            "unauthorized (401)",
            "status 401",
            "status 403",
        )
    ):
        return "AUTH_STATE_INVALID"
    if any(
        marker in text
        for marker in (
            "accounts/check",
            "http 4",
            "http 5",
            "status 4",
            "status 5",
        )
    ):
        return "ACCOUNTS_CHECK_HTTP_FAILURE"
    if any(
        marker in text
        for marker in (
            "connection refused",
            "connection reset",
            "name resolution",
            "dns",
            "network is unreachable",
            "failed to connect",
            "connecterror",
            "sslerror",
            "proxyerror",
        )
    ) or any(marker in error_name for marker in ("connect", "timeout", "network")):
        return "NETWORK_PREREQUISITE_FAILED"
    if error_type == "InternalRpcError" and rpc_code == -32603:
        return "UNKNOWN_INTERNAL"
    if rpc_code is not None:
        return "OTHER_RPC_FAILURE"
    return (
        "NETWORK_PREREQUISITE_FAILED"
        if error_name == "transportclosederror"
        else "OTHER_RPC_FAILURE"
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a string-keyed mapping")
    unknown_mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in unknown_mapping):
        raise ValueError(f"{label} must be a string-keyed mapping")
    return cast(Mapping[str, object], unknown_mapping)


def derive_account_routing_classification(
    scenarios: Sequence[Mapping[str, object]],
) -> AccountRoutingClassification:
    """Recompute the diagnostic result from A/B/C and optional D scenario evidence."""

    by_id: dict[str, Mapping[str, object]] = {}
    for scenario_value in scenarios:
        scenario = _mapping(scenario_value, "scenario")
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or scenario_id in by_id:
            raise ValueError("scenario ids must be unique strings")
        by_id[scenario_id] = scenario
    if not {"A", "B", "C"}.issubset(by_id) or set(by_id) - {"A", "B", "C", "D"}:
        raise ValueError("diagnostic matrix must contain A, B, C and optional D")

    baseline = by_id["A"]
    isolated = by_id["B"]
    normal_projection = by_id["C"]
    if baseline.get("initialize_status") != "PASS":
        return _classification_from_error(baseline)
    if baseline.get("account_read_status") != "PASS":
        return _classification_from_error(baseline)
    if isolated.get("initialize_status") != "PASS":
        return _classification_from_error(isolated)
    if isolated.get("runtime_identity_verified") is not True:
        return "INCONCLUSIVE"
    if isolated.get("account_read_status") == "PASS":
        return "ACCOUNT_ROUTING_COMPATIBLE"
    if isolated.get("account_read_status") != "FAILED":
        return "INCONCLUSIVE"

    if normal_projection.get("initialize_status") != "PASS":
        return _classification_from_error(normal_projection)
    if normal_projection.get("runtime_identity_verified") is not True:
        return "INCONCLUSIVE"
    if normal_projection.get("config_projection_complete") is not True:
        return "INCONCLUSIVE"
    if normal_projection.get("account_read_status") == "PASS":
        fields = normal_projection.get("config_projection_fields")
        if (
            isinstance(fields, list)
            and fields == ["chatgpt_base_url"]
            and normal_projection.get("config_projection_complete") is True
        ):
            return "ISOLATION_PROFILE_INCOMPATIBLE"
        return "INCONCLUSIVE"
    if normal_projection.get("account_read_status") != "FAILED":
        return "INCONCLUSIVE"

    if isolated.get("auth_projection_sha256") != normal_projection.get("auth_projection_sha256"):
        return "INCONCLUSIVE"
    if not _same_account_read_error(isolated, normal_projection):
        return _classification_from_error(normal_projection)

    if "D" in by_id:
        prerequisite = by_id["D"]
        fields = prerequisite.get("config_projection_fields")
        if (
            prerequisite.get("initialize_status") == "PASS"
            and prerequisite.get("runtime_identity_verified") is True
            and prerequisite.get("account_read_status") == "PASS"
            and isinstance(fields, list)
            and bool(cast(list[object], fields))
        ):
            return "ISOLATION_PROFILE_INCOMPATIBLE"

    error_classification = isolated.get("rpc_error_classification")
    if error_classification == "AUTH_STATE_INVALID":
        return "AUTH_STATE_INVALID"
    if error_classification == "ORIGIN_POLICY_MISMATCH":
        return "ORIGIN_POLICY_MISMATCH"
    if error_classification == "ROUTING_RESPONSE_INVALID":
        return "ROUTING_RESPONSE_INVALID"
    if error_classification == "NETWORK_PREREQUISITE_FAILED":
        return "NETWORK_PREREQUISITE_FAILED"
    if error_classification in _ROUTING_RPC_ERRORS or (
        isolated.get("rpc_error_code") == -32603
        and isolated.get("rpc_error_classification") == "UNKNOWN_INTERNAL"
    ):
        return "UPSTREAM_ACCOUNT_ROUTING_FAILURE"
    return "INCONCLUSIVE"


def _same_account_read_error(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return (
        left.get("rpc_method") == right.get("rpc_method") == "account/read"
        and left.get("rpc_error_code") == right.get("rpc_error_code")
        and left.get("rpc_error_type") == right.get("rpc_error_type")
        and left.get("rpc_error_classification") == right.get("rpc_error_classification")
        and left.get("rpc_error_message_sha256") == right.get("rpc_error_message_sha256")
    )


def _classification_from_error(scenario: Mapping[str, object]) -> AccountRoutingClassification:
    error = scenario.get("rpc_error_classification")
    if error == "AUTH_STATE_INVALID":
        return "AUTH_STATE_INVALID"
    if error == "ORIGIN_POLICY_MISMATCH":
        return "ORIGIN_POLICY_MISMATCH"
    if error == "ROUTING_RESPONSE_INVALID":
        return "ROUTING_RESPONSE_INVALID"
    if error == "NETWORK_PREREQUISITE_FAILED":
        return "NETWORK_PREREQUISITE_FAILED"
    account_read_error = (
        scenario.get("scenario_id") in {"B", "C", "D"}
        and scenario.get("rpc_method") == "account/read"
    )
    if account_read_error and (
        error in _ROUTING_RPC_ERRORS
        or (scenario.get("rpc_error_code") == -32603 and error == "UNKNOWN_INTERNAL")
    ):
        return "UPSTREAM_ACCOUNT_ROUTING_FAILURE"
    return "INCONCLUSIVE"
