from __future__ import annotations

import pytest

from quantos.security import SecretArtifactRejected, validate_secret_free


@pytest.mark.parametrize(
    "payload",
    [
        {"OPENAI_API_KEY": "ABSENT"},
        {"OPENAI_API_KEY": "PRESENT"},
        {"access_token_presence": "PRESENT"},
        {"refresh_token_presence": "ABSENT"},
        {"auth_file_sha256": "a" * 64},
        {"selected_account_workspace_id_sha256": "b" * 64},
        {"rpc_error_message_sha256": "c" * 64},
        {"Authorization_header_present": True},
        {"diagnostic": 'config field "OPENAI_API_KEY": "PRESENT" is metadata'},
        {"parent_managed_environment_presence": {"CODEX_API_KEY": "PRESENT"}},
        {
            "credential_store_mode": "DEFAULT_OR_UNSET",
            "normal_config_bootstrap_fields": {"cli_auth_credentials_store": "PRESENT"},
        },
        {"config_key_names": ["model_provider", "cli_auth_credentials_store"]},
        {"rpc_error_classification": "UNKNOWN_INTERNAL"},
        {"access_token_classification": "SAFE_METADATA"},
    ],
)
def test_safe_secret_metadata_is_allowed(payload: object) -> None:
    validate_secret_free(payload, file_name="synthetic.json")


@pytest.mark.parametrize(
    ("payload", "expected_path", "expected_rule"),
    [
        (
            {"OPENAI_API_KEY": "synthetic-openai-secret-value"},
            "$.OPENAI_API_KEY",
            "RAW_CREDENTIAL_VALUE",
        ),
        (
            {"CODEX_API_KEY": "synthetic-codex-secret-value"},
            "$.CODEX_API_KEY",
            "RAW_CREDENTIAL_VALUE",
        ),
        (
            {"TUSHARE_TOKEN": "synthetic-tushare-secret-value"},
            "$.TUSHARE_TOKEN",
            "RAW_CREDENTIAL_VALUE",
        ),
        ({"api_key": "synthetic-provider-key-value"}, "$.api_key", "RAW_CREDENTIAL_VALUE"),
        (
            {"client_secret": "synthetic-client-secret-value"},
            "$.client_secret",
            "RAW_CREDENTIAL_VALUE",
        ),
        (
            {"Authorization": "Bearer synthetic-actual-token"},
            "$.Authorization",
            "RAW_CREDENTIAL_VALUE",
        ),
        ({"Cookie": "session=synthetic-cookie-value"}, "$.Cookie", "RAW_CREDENTIAL_VALUE"),
        ({"access_token": "synthetic-access-token"}, "$.access_token", "RAW_CREDENTIAL_VALUE"),
        (
            {"refresh_token": "synthetic-refresh-token"},
            "$.refresh_token",
            "RAW_CREDENTIAL_VALUE",
        ),
        (
            {"auth_json": '{"tokens":{"access_token":"synthetic-auth-token"}}'},
            "$.auth_json.tokens",
            "RAW_CREDENTIAL_VALUE",
        ),
        ({"diagnostic": "sk-proj-syntheticcredentialvalue"}, "$.diagnostic", "RAW_OPENAI_KEY"),
        ({"diagnostic": "ghp_syntheticgithubcredential"}, "$.diagnostic", "RAW_GITHUB_TOKEN"),
        ({"diagnostic": "gho_syntheticgithubcredential"}, "$.diagnostic", "RAW_GITHUB_TOKEN"),
        (
            {"diagnostic": "TUSHARE_TOKEN=synthetic-tushare-secret"},
            "$.diagnostic",
            "RAW_CREDENTIAL_ASSIGNMENT",
        ),
        (
            {"diagnostic": "Authorization: Bearer synthetic-header-token"},
            "$.diagnostic",
            "RAW_AUTHORIZATION_HEADER",
        ),
        (
            {"diagnostic": "Cookie: session=synthetic-cookie-value"},
            "$.diagnostic",
            "RAW_COOKIE_HEADER",
        ),
        (
            {"diagnostic": "access_token=synthetic-access-token"},
            "$.diagnostic",
            "RAW_TOKEN_ASSIGNMENT",
        ),
        (
            {"diagnostic": 'embedded config: {"Cookie":"session=synthetic-cookie"}'},
            "$.diagnostic",
            "RAW_EMBEDDED_CREDENTIAL_FIELD",
        ),
        (
            {"request_body": {"payload": "synthetic-body-value"}},
            "$.request_body",
            "RAW_EXCEPTION_OR_BODY_TEXT",
        ),
    ],
)
def test_credential_values_are_rejected_without_echoing_them(
    payload: object, expected_path: str, expected_rule: str
) -> None:
    with pytest.raises(SecretArtifactRejected) as captured:
        validate_secret_free(payload, file_name="account-routing-matrix.json")

    message = str(captured.value)
    assert "SECRET_VALUE_DETECTED" in message
    assert "file=account-routing-matrix.json" in message
    assert f"json_path={expected_path}" in message
    assert f"rule={expected_rule}" in message
    assert "synthetic" not in message


def test_secret_field_name_alone_does_not_trigger() -> None:
    validate_secret_free(
        {"OPENAI_API_KEY": "PRESENT", "access_token_presence": "PRESENT"},
        file_name="account-routing-report.json",
    )


def test_classification_only_and_hash_only_do_not_trigger() -> None:
    validate_secret_free(
        {
            "rpc_error_classification": "UNKNOWN_INTERNAL",
            "auth_file_sha256": "d" * 64,
        },
        file_name="account-routing-report.json",
    )


def test_hash_shaped_value_under_sensitive_hash_field_must_be_valid_sha256() -> None:
    with pytest.raises(SecretArtifactRejected) as captured:
        validate_secret_free(
            {"access_token_sha256": "not-a-digest"}, file_name="account-routing-matrix.json"
        )

    assert captured.value.rule == "RAW_CREDENTIAL_VALUE"


def test_safe_embedded_json_and_plain_scalar_strings_pass() -> None:
    validate_secret_free(
        {
            "metadata": '{"OPENAI_API_KEY":"PRESENT"}',
            "plain": "true",
            "array": '["safe", 1]',
        },
        file_name="account-routing-matrix.json",
    )


@pytest.mark.parametrize(
    ("payload", "expected_rule"),
    [
        ({"auth_file_sha256": "invalid-hash"}, "INVALID_HASH_VALUE"),
        ({"large_note": "x" * 65_537}, "VALUE_EXCEEDS_SCAN_BOUND"),
        ({1: "synthetic-value"}, "NON_STRING_JSON_KEY"),
        ({"opaque": object()}, "UNSUPPORTED_JSON_VALUE"),
        ({"access_token": None}, "RAW_CREDENTIAL_VALUE"),
        ({"access_token": 7}, "RAW_CREDENTIAL_VALUE"),
    ],
)
def test_invalid_json_artifact_values_are_rejected_safely(
    payload: object, expected_rule: str
) -> None:
    with pytest.raises(SecretArtifactRejected) as captured:
        validate_secret_free(payload, file_name="account-routing-matrix.json")

    assert captured.value.rule == expected_rule
    assert "synthetic-value" not in str(captured.value)


def test_secret_pattern_in_property_name_is_rejected_without_echoing_the_name() -> None:
    with pytest.raises(SecretArtifactRejected) as captured:
        validate_secret_free(
            {"ghp_syntheticgithubcredential": "PRESENT"},
            file_name="account-routing-matrix.json",
        )

    assert captured.value.rule == "RAW_GITHUB_TOKEN"
    assert "ghp_syntheticgithubcredential" not in str(captured.value)
    assert "key-sha256" in captured.value.json_path


def test_unsafe_artifact_filename_is_not_echoed() -> None:
    with pytest.raises(ValueError, match="safe, non-empty label") as captured:
        validate_secret_free({}, file_name="sk-proj-synthetic-secret-value")

    assert "synthetic" not in str(captured.value)
