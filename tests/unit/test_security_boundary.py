import json
from pathlib import Path

import pytest

from quantos.application import (
    AgentRequestBoundary,
    AuthorityRootResolver,
    ResourceBudget,
    SecurityBoundaryError,
    restricted_agent_environment,
)
from quantos.artifacts import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes


def test_agent_boundary_allows_only_budgeted_secret_free_payloads() -> None:
    boundary = AgentRequestBoundary(frozenset({"proposal.submit"}))
    payload = b'{"hypothesis":"bounded"}'

    assert boundary.accept("proposal.submit", payload) == {"hypothesis": "bounded"}
    decision = boundary.audit_decisions[0]
    assert decision.allowed
    assert decision.payload_sha256 == sha256_bytes(payload)
    assert decision.payload_size_bytes == len(payload)

    with pytest.raises(SecurityBoundaryError) as denied:
        boundary.accept("shell.execute", b"{}")
    assert denied.value.reason_code == "CAPABILITY_DENIED"
    assert boundary.audit_decisions[-1].reason_code == "CAPABILITY_DENIED"


def test_agent_policy_can_never_grant_authority_capabilities() -> None:
    with pytest.raises(ValueError, match="cannot grant"):
        AgentRequestBoundary(frozenset({"validation.override"}))
    with pytest.raises(ValueError, match="cannot grant"):
        AgentRequestBoundary(frozenset({"shell.execute-v2"}))
    with pytest.raises(ValueError, match="bounded logical"):
        AgentRequestBoundary(frozenset({"proposal.submit\nsecret"}))


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    [
        (b'{"x":1,"x":2}', "SCHEMA_INVALID"),
        (b'{"score":NaN}', "SCHEMA_INVALID"),
        (b'{"score":1e10000}', "SCHEMA_INVALID"),
        (b'{"nested":{"token":"do-not-record"}}', "SECRET_ACCESS_DENIED"),
        (b'{"nested":{"tushare-token":"do-not-record"}}', "SECRET_ACCESS_DENIED"),
        (b'{"validation_verdict":"PASS"}', "AUTHORITY_FIELD_DENIED"),
        (b'{"unseal_oos":true}', "AUTHORITY_FIELD_DENIED"),
    ],
)
def test_agent_boundary_rejects_malicious_control_payloads(
    payload: bytes, reason_code: str
) -> None:
    boundary = AgentRequestBoundary(frozenset({"proposal.submit"}))

    with pytest.raises(SecurityBoundaryError) as rejected:
        boundary.accept("proposal.submit", payload)

    assert rejected.value.reason_code == reason_code
    assert boundary.audit_decisions[-1].reason_code == reason_code
    assert repr(boundary.audit_decisions[-1]).find("do-not-record") == -1


def test_agent_boundary_enforces_byte_depth_node_and_string_budgets() -> None:
    budget = ResourceBudget(
        max_payload_bytes=64,
        max_depth=3,
        max_nodes=5,
        max_string_bytes=8,
    )
    boundary = AgentRequestBoundary(frozenset({"proposal.submit"}), budget=budget)

    for payload in (
        b'{"value":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}',
        b'{"a":{"b":{"c":1}}}',
        b'{"a":[1,2,3,4,5]}',
        b'{"value":"123456789"}',
    ):
        with pytest.raises(SecurityBoundaryError) as rejected:
            boundary.accept("proposal.submit", payload)
        assert rejected.value.reason_code == "RESOURCE_BUDGET_EXCEEDED"


def test_agent_boundary_bounds_requests_and_invalid_audit_labels() -> None:
    boundary = AgentRequestBoundary(
        frozenset({"proposal.submit"}),
        budget=ResourceBudget(max_requests=1),
    )
    with pytest.raises(SecurityBoundaryError) as invalid:
        boundary.accept("invalid\nsecret-value", b"{}")
    assert invalid.value.reason_code == "SCHEMA_INVALID"
    assert boundary.audit_decisions[0].capability == "<invalid>"

    with pytest.raises(SecurityBoundaryError) as exhausted:
        boundary.accept("proposal.submit", b"{}")
    assert exhausted.value.reason_code == "RESOURCE_BUDGET_EXCEEDED"


def test_agent_boundary_translates_decoder_recursion_failure() -> None:
    boundary = AgentRequestBoundary(frozenset({"proposal.submit"}))
    payload = b'{"x":' + (b"[" * 2_000) + b"0" + (b"]" * 2_000) + b"}"

    with pytest.raises(SecurityBoundaryError) as rejected:
        boundary.accept("proposal.submit", payload)

    assert rejected.value.reason_code == "RESOURCE_BUDGET_EXCEEDED"


def test_restricted_agent_environment_is_an_allowlist() -> None:
    secret = "not-visible-to-agent"
    result = restricted_agent_environment(
        {
            "LANG": "C.UTF-8",
            "PATH": "/authority/bin",
            "TUSHARE_TOKEN": secret,
            "OTHER_API_KEY": secret,
        }
    )

    assert result == {"LANG": "C.UTF-8"}
    assert secret not in json.dumps(result)


def test_authority_resolver_accepts_hashes_not_caller_paths(tmp_path: Path) -> None:
    digest = "a" * 64
    root = tmp_path / "validation"
    artifact = root / f"sha256-{digest}"
    artifact.mkdir(parents=True)
    payload = b'{"report":"immutable"}'
    (artifact / "report.json").write_bytes(payload)
    resolver = AuthorityRootResolver({"validation": root})

    resolved = resolver.verify_artifact_file(
        "validation",
        digest,
        "report.json",
        expected_sha256=sha256_bytes(payload),
        expected_size_bytes=len(payload),
    )

    assert resolved == (artifact / "report.json").resolve()
    with pytest.raises(SecurityBoundaryError):
        resolver.artifact_file("validation", digest, "../outside")
    with pytest.raises(SecurityBoundaryError):
        resolver.content_addressed_directory("validation", "../outside")
    with pytest.raises(SecurityBoundaryError):
        resolver.content_addressed_directory("registry", digest)


def test_authority_resolver_rejects_symlink_escape_and_spoofing(tmp_path: Path) -> None:
    digest = "b" * 64
    root = tmp_path / "signals"
    artifact = root / f"sha256-{digest}"
    artifact.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    (artifact / "manifest.json").symlink_to(outside)
    resolver = AuthorityRootResolver({"signals": root})

    with pytest.raises(SecurityBoundaryError) as escaped:
        resolver.artifact_file("signals", digest, "manifest.json")
    assert escaped.value.reason_code == "PATH_BOUNDARY_VIOLATION"

    (artifact / "manifest.json").unlink()
    (artifact / "manifest.json").write_bytes(b"spoofed")
    with pytest.raises(ArtifactIntegrityError):
        resolver.verify_artifact_file(
            "signals",
            digest,
            "manifest.json",
            expected_sha256="c" * 64,
            expected_size_bytes=7,
        )


def test_authority_resolver_rejects_symlink_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(SecurityBoundaryError) as rejected:
        AuthorityRootResolver({"validation": linked})
    assert rejected.value.reason_code == "AUTHORITY_ROOT_INVALID"
