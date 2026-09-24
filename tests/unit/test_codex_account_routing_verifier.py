from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.security import validate_secret_free

ROOT = Path(__file__).parents[2]
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "codex_account_routing_diagnostic_test_module",
    ROOT / "scripts/codex_account_routing_diagnostic.py",
)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = runner
RUNNER_SPEC.loader.exec_module(runner)
SPEC = importlib.util.spec_from_file_location(
    "verify_codex_account_routing_diagnostic_test_module",
    ROOT / "scripts/verify_codex_account_routing_diagnostic.py",
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)
AccountRoutingArtifactError = verifier.AccountRoutingArtifactError
verify_account_routing_artifact = verifier.verify_account_routing_artifact

CANDIDATE_BINARY_SHA256 = "0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
AUTH_SHA256 = "a" * 64
SELECTED_ID_SHA256 = "b" * 64


def _scenario(scenario_id: str) -> dict[str, object]:
    baseline = scenario_id == "A"
    runtime_version = "0.154.0" if baseline else "0.156.1"
    return {
        "scenario_id": scenario_id,
        "requested_runtime_version": runtime_version,
        "expected_runtime_candidate_id": None if baseline else "openai-codex-0.156.1-p10-v3",
        "sdk_version": runtime_version,
        "runtime_package_version": runtime_version,
        "app_server_version": f"{runtime_version} test-build",
        "runtime_binary_sha256": "c" * 64 if baseline else CANDIDATE_BINARY_SHA256,
        "runtime_identity_verified": True,
        "initialize_status": "PASS",
        "account_read_status": "PASS",
        "rpc_method": None,
        "rpc_error_code": None,
        "rpc_error_type": None,
        "rpc_error_classification": None,
        "rpc_error_message_sha256": None,
        "auth_projection_sha256": AUTH_SHA256,
        "selected_account_workspace_id_presence": "PRESENT",
        "selected_account_workspace_id_sha256": SELECTED_ID_SHA256,
        "config_sha256": None if scenario_id in {"A", "B"} else sha256_bytes(b""),
        "config_projection_complete": True,
        "config_projection_fields": [],
        "codex_home_mode": {
            "A": "ISOLATED_AUTH_ONLY_0_154",
            "B": "ISOLATED_AUTH_ONLY_0_156_1",
            "C": "NORMAL_USER_SAFE_PROJECTION_0_156_1",
        }[scenario_id],
        "thread_start_count": 0,
        "turn_start_count": 0,
        "provider_request_count": 0,
        "request_count_basis": "DIAGNOSTIC_CALL_TRACE; no thread or turn API is invoked",
        "explicit_account_read_call_count": 1,
        "accounts_check_attempted": "false" if baseline else "true",
    }


def _write_artifact(
    path: Path,
    *,
    claimed_classification: str,
    candidate_failed: bool = False,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    scenarios = [_scenario(scenario_id) for scenario_id in ("A", "B", "C")]
    if candidate_failed:
        scenarios[1].update(
            {
                "account_read_status": "FAILED",
                "rpc_method": "account/read",
                "rpc_error_code": -32603,
                "rpc_error_type": "InternalRpcError",
                "rpc_error_classification": "UNKNOWN_INTERNAL",
                "rpc_error_message_sha256": "e" * 64,
            }
        )
    matrix = {
        "schema_version": "fr03-codex-account-routing-matrix/v2",
        "run_id": "fr03-codex-0.156.1-account-routing-v2-20260924-120000",
        "scenarios": scenarios,
    }
    source = {
        "schema_version": "fr03-codex-account-routing-source-audit/v2",
        "upstream_source_commits": {
            "rust-v0.154.0": "6b9826e3aa83b1a5947db50f4332cb9c65f1b340",
            "rust-v0.156.1": "b412ff32c417f855c2b2d1581b77058eed87c84b",
        },
        "p10_contract_change": False,
        "normalizer_or_evaluator_change": False,
    }
    matrix_bytes = canonical_json_bytes(matrix)
    source_bytes = canonical_json_bytes(source)
    report: dict[str, object] = {
        "schema_version": "fr03-codex-account-routing-diagnostic/v2",
        "run_id": matrix["run_id"],
        "implementation_commit": "d" * 40,
        "candidate_runtime_candidate_id": "openai-codex-0.156.1-p10-v3",
        "candidate_sdk_version": "0.156.1",
        "candidate_runtime_package_version": "0.156.1",
        "model_scope": "gpt-5.6-sol; not invoked",
        "normal_profile_audit": {
            "normal_codex_home_used_directly": False,
            "normal_auth_file_sha256": AUTH_SHA256,
            "config_projection_complete": True,
            "config_projection_fields": [],
            "selected_account_workspace_id_presence": "PRESENT",
            "selected_account_workspace_id_sha256": SELECTED_ID_SHA256,
        },
        "diagnostic_classification": claimed_classification,
        "p10_eligible": not candidate_failed,
        "p10_started": False,
        "p10_score": None,
        "matched_command_lifecycle_count": None,
        "canonical_pin_changed": False,
        "p10_contract_changed": False,
        "fr03_status": "NO_GO",
        "p14d_c_status": "BLOCKED_UNIMPLEMENTED",
        "matrix_sha256": sha256_bytes(matrix_bytes),
        "source_audit_sha256": sha256_bytes(source_bytes),
        "artifact_file_hashes": {
            "account-routing-matrix.json": sha256_bytes(matrix_bytes),
            "upstream-source-audit.json": sha256_bytes(source_bytes),
        },
    }
    validate_secret_free(matrix, file_name="account-routing-matrix.json")
    validate_secret_free(source, file_name="upstream-source-audit.json")
    validate_secret_free(report, file_name="account-routing-report.json")
    report_bytes = canonical_json_bytes(report)
    destination = path / f"sha256-{sha256_bytes(report_bytes)}"
    destination.mkdir()
    (destination / "account-routing-matrix.json").write_bytes(matrix_bytes)
    (destination / "upstream-source-audit.json").write_bytes(source_bytes)
    (destination / "account-routing-report.json").write_bytes(report_bytes)
    return destination


def test_offline_verifier_recomputes_classification_and_runtime_bindings(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path, claimed_classification="ACCOUNT_ROUTING_COMPATIBLE")

    result = verify_account_routing_artifact(artifact)

    assert result["offline_verification"] == "PASS"
    assert result["diagnostic_classification"] == "ACCOUNT_ROUTING_COMPATIBLE"
    assert result["p10_eligible"] is True


def test_offline_verifier_rejects_caller_supplied_classification(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path, claimed_classification="UPSTREAM_ACCOUNT_ROUTING_FAILURE")

    with pytest.raises(AccountRoutingArtifactError, match="classification"):
        verify_account_routing_artifact(artifact)


def test_synthetic_failed_candidate_round_trips_and_recomputes_classification(
    tmp_path: Path,
) -> None:
    artifact = _write_artifact(
        tmp_path,
        claimed_classification="INCONCLUSIVE",
        candidate_failed=True,
    )

    result = verify_account_routing_artifact(artifact)

    assert result["offline_verification"] == "PASS"
    assert result["diagnostic_classification"] == "INCONCLUSIVE"
    assert result["p10_eligible"] is False
    assert result["scenario_count"] == 3


def test_runner_publisher_round_trips_through_offline_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _write_artifact(
        tmp_path / "seed",
        claimed_classification="INCONCLUSIVE",
        candidate_failed=True,
    )
    matrix = verifier._load_json((seed / "account-routing-matrix.json").read_bytes(), "matrix")
    source = verifier._load_json((seed / "upstream-source-audit.json").read_bytes(), "source")
    report = verifier._load_json((seed / "account-routing-report.json").read_bytes(), "report")
    monkeypatch.setattr(runner, "ARTIFACT_ROOT", tmp_path / "published")

    report_hash, published = runner._publish_artifact(report, matrix, source)
    result = verify_account_routing_artifact(published)

    assert published.name == f"sha256-{report_hash}"
    assert result["artifact_hash"] == report_hash
    assert result["offline_verification"] == "PASS"
    assert result["diagnostic_classification"] == "INCONCLUSIVE"


def test_real_source_audit_accepts_safe_refresh_token_boolean() -> None:
    audit = runner._source_audit()

    validate_secret_free(audit, file_name="upstream-source-audit.json")


def _rewrite_artifact(
    path: Path,
    artifact: Path,
    *,
    matrix_change: dict[str, object] | None = None,
    source_change: dict[str, object] | None = None,
    report_change: dict[str, object] | None = None,
    refresh_bindings: bool = True,
) -> Path:
    matrix = verifier._load_json((artifact / "account-routing-matrix.json").read_bytes(), "matrix")
    source = verifier._load_json((artifact / "upstream-source-audit.json").read_bytes(), "source")
    report = verifier._load_json((artifact / "account-routing-report.json").read_bytes(), "report")
    if matrix_change:
        matrix.update(matrix_change)
    if source_change:
        source.update(source_change)
    if report_change:
        report.update(report_change)
    matrix_bytes = canonical_json_bytes(matrix)
    source_bytes = canonical_json_bytes(source)
    if refresh_bindings:
        report["matrix_sha256"] = sha256_bytes(matrix_bytes)
        report["source_audit_sha256"] = sha256_bytes(source_bytes)
        report["artifact_file_hashes"] = {
            "account-routing-matrix.json": sha256_bytes(matrix_bytes),
            "upstream-source-audit.json": sha256_bytes(source_bytes),
        }
    report_bytes = canonical_json_bytes(report)
    destination = path / f"sha256-{sha256_bytes(report_bytes)}"
    destination.mkdir()
    (destination / "account-routing-matrix.json").write_bytes(matrix_bytes)
    (destination / "upstream-source-audit.json").write_bytes(source_bytes)
    (destination / "account-routing-report.json").write_bytes(report_bytes)
    return destination


@pytest.mark.parametrize(
    "tampering",
    ["matrix", "report", "source audit", "secret field", "hash"],
)
def test_offline_verifier_rejects_tampering(tmp_path: Path, tampering: str) -> None:
    original = _write_artifact(
        tmp_path / "original", claimed_classification="ACCOUNT_ROUTING_COMPATIBLE"
    )
    target = tmp_path / "tampered"
    target.mkdir()
    if tampering == "matrix":
        changed = _rewrite_artifact(
            target,
            original,
            matrix_change={"run_id": "fr03-codex-0.156.1-account-routing-v2-20260924-120001"},
        )
    elif tampering == "report":
        changed = _rewrite_artifact(
            target,
            original,
            report_change={"diagnostic_classification": "INCONCLUSIVE"},
        )
    elif tampering == "source audit":
        changed = _rewrite_artifact(
            target,
            original,
            source_change={"p10_contract_change": True},
        )
    elif tampering == "secret field":
        changed = _rewrite_artifact(
            target,
            original,
            matrix_change={"OPENAI_API_KEY": "synthetic-secret-that-must-not-persist"},
        )
    else:
        changed = _rewrite_artifact(
            target,
            original,
            report_change={"matrix_sha256": "f" * 64},
            refresh_bindings=False,
        )

    with pytest.raises(AccountRoutingArtifactError):
        verify_account_routing_artifact(changed)
