"""Frozen Codex SDK and bundled runtime package identity."""

from collections.abc import Mapping
from types import MappingProxyType

CODEX_SDK_DISTRIBUTION = "openai-codex"
CODEX_SDK_VERSION = "0.154.0"
CODEX_RUNTIME_DISTRIBUTION = "openai-codex-cli-bin"
CODEX_RUNTIME_PACKAGE_VERSION = "0.154.0"
CODEX_PROTOCOL_IDENTIFIER = "codex-app-server-jsonrpc-v2"

CODEX_CANDIDATE_RUNTIME_PROFILES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {"openai-codex-0.156.1-p10-v3": ("0.156.1", "0.156.1")}
)


def expected_codex_versions(profile_id: str | None) -> tuple[str, str] | None:
    """Return the finite SDK/runtime identity for canonical or candidate execution."""

    if profile_id is None:
        return CODEX_SDK_VERSION, CODEX_RUNTIME_PACKAGE_VERSION
    return CODEX_CANDIDATE_RUNTIME_PROFILES.get(profile_id)
