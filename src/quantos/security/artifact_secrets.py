"""Deterministic secret-value validation for structured artifact payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import NoReturn, cast

_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_FILE_LABEL_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_SAFE_CLASSIFICATIONS = frozenset({"ABSENT", "PRESENT", "UNKNOWN"})
_SECRET_KEY_NAMES = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "tokens",
        "api_key",
        "openai_api_key",
        "codex_api_key",
        "tushare_token",
        "github_token",
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "secret",
        "password",
        "credential",
        "credentials",
    }
)
_RAW_TEXT_KEY_NAMES = frozenset(
    {
        "error_message",
        "rpc_error_message",
        "worker_error_message",
        "exception_message",
        "stderr",
        "stdout",
        "worker_stderr",
        "worker_stdout",
        "raw_response",
        "response_body",
        "request_body",
        "http_headers",
        "headers",
    }
)
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RAW_AUTHORIZATION_HEADER", re.compile(r"(?i)\b(?:proxy-)?authorization\s*:\s*\S+")),
    ("RAW_BEARER_TOKEN", re.compile(r"(?i)\bbearer\s+\S+")),
    ("RAW_COOKIE_HEADER", re.compile(r"(?i)\b(?:set-cookie|cookie)\s*:\s*[^\r\n]+")),
    (
        "RAW_CREDENTIAL_ASSIGNMENT",
        re.compile(
            r"(?i)\b(?:OPENAI_API_KEY|CODEX_API_KEY|TUSHARE_TOKEN|(?:X[-_])?API[-_]?KEY)"
            r"\s*[:=]\s*(?!ABSENT\b|PRESENT\b|UNKNOWN\b)[^\s,;]+"
        ),
    ),
    (
        "RAW_TOKEN_ASSIGNMENT",
        re.compile(
            r"(?i)\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token)"
            r"\s*[:=]\s*(?!ABSENT\b|PRESENT\b|UNKNOWN\b)[^\s,;]+"
        ),
    ),
    (
        "RAW_EMBEDDED_CREDENTIAL_FIELD",
        re.compile(
            r"(?is)[\"'](?:authorization|proxy-authorization|cookie|set-cookie|access_token|"
            r"refresh_token|id_token|api_key|openai_api_key|codex_api_key|tushare_token)"
            r"[\"']\s*:\s*[\"'](?!(?:ABSENT|PRESENT|UNKNOWN)[\"'])[^\"']+[\"']"
        ),
    ),
    (
        "RAW_AUTH_JSON_TOKEN_CONTAINER",
        re.compile(r"(?is)[\"']tokens[\"']\s*:\s*[\{\[]"),
    ),
    ("RAW_OPENAI_KEY", re.compile(r"(?i)\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}")),
    ("RAW_GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b")),
    (
        "RAW_JWT_CREDENTIAL",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)
_MAX_VALUE_LENGTH = 65_536


class SecretArtifactRejected(ValueError):
    """Safe, path-specific rejection that never includes the offending value."""

    def __init__(
        self,
        *,
        file_name: str,
        json_path: str,
        rule: str,
        value_classification: str,
    ) -> None:
        self.file_name = file_name
        self.json_path = json_path
        self.rule = rule
        self.value_classification = value_classification
        super().__init__(
            "SECRET_VALUE_DETECTED "
            f"file={file_name} json_path={json_path} rule={rule} "
            f"value_classification={value_classification}"
        )


def validate_secret_free(value: object, *, file_name: str) -> None:
    """Validate a canonical JSON-like value tree without exposing rejected values."""

    if _FILE_LABEL_PATTERN.fullmatch(file_name) is None or _contains_value_pattern(file_name):
        raise ValueError("artifact file name must be a safe, non-empty label")

    def reject(path: str, rule: str, classification: str) -> NoReturn:
        raise SecretArtifactRejected(
            file_name=file_name,
            json_path=path,
            rule=rule,
            value_classification=classification,
        )

    def visit(item: object, path: str, key_name: str | None = None) -> None:
        if key_name is not None:
            normalized = key_name.casefold().replace("-", "_")
            if normalized in _RAW_TEXT_KEY_NAMES:
                reject(path, "RAW_EXCEPTION_OR_BODY_TEXT", "UNREDACTED_TEXT_FIELD")

            if _is_secret_key(normalized):
                if _safe_metadata_value(normalized, item):
                    return
                reject(path, "RAW_CREDENTIAL_VALUE", _classify_value(item))
            if normalized.endswith(("_sha256", "_hash")):
                if item is None or (
                    isinstance(item, str) and _SHA256_PATTERN.fullmatch(item) is not None
                ):
                    return
                reject(path, "INVALID_HASH_VALUE", _classify_value(item))

        if item is None or isinstance(item, (bool, int, float)):
            return
        if isinstance(item, str):
            if len(item) > _MAX_VALUE_LENGTH:
                reject(path, "VALUE_EXCEEDS_SCAN_BOUND", "OVERSIZED_STRING")
            embedded = _parse_embedded_json(item)
            if embedded is not None:
                visit(embedded, path)
                return
            rule = _matched_value_rule(item)
            if rule is not None:
                reject(path, rule, "CREDENTIAL_PATTERN")
            return
        if isinstance(item, Mapping):
            mapping = cast(Mapping[object, object], item)
            for child_key, child_value in mapping.items():
                if not isinstance(child_key, str):
                    reject(path, "NON_STRING_JSON_KEY", "INVALID_JSON_STRUCTURE")
                key_rule = _matched_value_rule(child_key)
                if key_rule is not None:
                    reject(_child_path(path, child_key), key_rule, "CREDENTIAL_PATTERN")
                visit(child_value, _child_path(path, child_key), child_key)
            return
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray, str)):
            sequence = cast(Sequence[object], item)
            for index, child_value in enumerate(sequence):
                visit(child_value, f"{path}[{index}]")
            return
        reject(path, "UNSUPPORTED_JSON_VALUE", "INVALID_JSON_STRUCTURE")

    visit(value, "$")


def _is_secret_key(normalized: str) -> bool:
    if normalized in _SECRET_KEY_NAMES:
        return True
    compact = normalized.replace("_", "")
    return any(
        marker in compact
        for marker in (
            "token",
            "apikey",
            "authorization",
            "cookie",
            "secret",
            "password",
            "credential",
        )
    )


def _safe_metadata_value(key: str, value: object) -> bool:
    normalized = key.replace("-", "_")
    if normalized.endswith(("_sha256", "_hash")):
        return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None
    if normalized.endswith(("_presence", "_present")):
        return (isinstance(value, str) and value in _SAFE_CLASSIFICATIONS) or isinstance(
            value, bool
        )
    if normalized.endswith("_classification"):
        return isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is not None
    if normalized.endswith("_mode"):
        return isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is not None
    return isinstance(value, str) and value in _SAFE_CLASSIFICATIONS


def _classify_value(value: object) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        return "STRUCTURED_CREDENTIAL_OBJECT"
    if isinstance(value, str):
        return "STRING_VALUE"
    if value is None:
        return "NULL_VALUE"
    return "NON_STRING_VALUE"


def _parse_embedded_json(value: str) -> object | None:
    try:
        parsed: object = json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        return None
    if isinstance(parsed, dict):
        return cast(dict[str, object], parsed)
    if isinstance(parsed, list):
        return cast(list[object], parsed)
    return None


def _child_path(parent: str, key: str) -> str:
    if len(key) >= 40 or _contains_value_pattern(key):
        digest = sha256(key.encode("utf-8", errors="replace")).hexdigest()
        return f'{parent}["<key-sha256:{digest}>"]'
    if _KEY_PATTERN.fullmatch(key) is not None:
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key, ensure_ascii=True)}]"


def _matched_value_rule(value: str) -> str | None:
    return next((rule for rule, pattern in _VALUE_PATTERNS if pattern.search(value)), None)


def _contains_value_pattern(value: str) -> bool:
    return _matched_value_rule(value) is not None
