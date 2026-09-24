#!/usr/bin/env python3
"""Offline verification for the Codex 0.156.1 FR-03 preflight artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from quantos.application.agent_harness import capture_from_agent_events
from quantos.application.harness_runner import (
    _sdk_request,
    load_frozen_spike_inputs,
    verify_codex_spike_artifact,
)
from quantos.artifacts.store import regular_tree_files
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.event_normalizer import (
    NORMALIZER_IDENTIFIER,
    normalize_provider_events,
)
from quantos.integrations.codex.sdk_host import _sdk_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_ROOT = ROOT / "tests/fixtures/p10_codex_workspace_v3"
HISTORICAL_P10_PATH = (
    ROOT / "artifacts/feasibility/codex-p10-code-mode-20260922/"
    "sha256-c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc"
)
REPORT_NAME = "candidate-preflight-report.json"
AUDIT_NAME = "compatibility-audit.json"
NOTIFICATIONS_NAME = "candidate-public-notifications.json"
REQUIRED_FILES = {REPORT_NAME, AUDIT_NAME, NOTIFICATIONS_NAME}
SECRET_MARKERS = (
    b"Authorization:",
    b"Bearer ",
    b"sk-proj-",
    b"TUSHARE_TOKEN=",
    b"ghp_",
    b"gho_",
)


class CandidateArtifactError(ValueError):
    """Raised when an immutable candidate preflight artifact does not replay."""


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateArtifactError("candidate preflight artifact JSON is invalid") from error


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandidateArtifactError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def verify_candidate_preflight_artifact(
    artifact_path: Path,
    *,
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
) -> dict[str, object]:
    """Verify the candidate report, synthetic public events and historical P10 replay offline."""

    try:
        files = regular_tree_files(artifact_path)
    except (OSError, RuntimeError, ValueError) as error:
        raise CandidateArtifactError("candidate preflight artifact path is unavailable") from error
    if {path.name for path in files} != REQUIRED_FILES:
        raise CandidateArtifactError("candidate preflight artifact file set is not exact")

    payloads = {path.name: path.read_bytes() for path in files}
    for content in payloads.values():
        if any(marker in content for marker in SECRET_MARKERS):
            raise CandidateArtifactError("candidate artifact contains a credential-like marker")

    report = _mapping(_load_json(artifact_path / REPORT_NAME), "report")
    audit = _mapping(_load_json(artifact_path / AUDIT_NAME), "compatibility audit")
    notifications_value = _load_json(artifact_path / NOTIFICATIONS_NAME)
    if not isinstance(notifications_value, list):
        raise CandidateArtifactError("synthetic public notification fixture must be an array")
    notifications = cast(list[object], notifications_value)

    report_bytes = payloads[REPORT_NAME]
    report_hash = sha256_bytes(report_bytes)
    if (
        artifact_path.name != f"sha256-{report_hash}"
        or canonical_json_bytes(report) != report_bytes
        or report.get("schema_version") != "fr03-codex-runtime-preflight/v1"
        or report.get("artifact_file_hashes")
        != {
            AUDIT_NAME: sha256_bytes(payloads[AUDIT_NAME]),
            NOTIFICATIONS_NAME: sha256_bytes(payloads[NOTIFICATIONS_NAME]),
        }
    ):
        raise CandidateArtifactError("candidate report address or file bindings are invalid")

    if (
        report.get("runtime_candidate_id") != "openai-codex-0.156.1-p10-v3"
        or report.get("run_id")
        not in {
            "fr03-codex-0.156.1-gpt-5.6-sol-preflight-20260924-001",
            "fr03-codex-0.156.1-gpt-5.6-sol-preflight-20260924-002",
        }
        or report.get("qualification_result") != "NOT_EVALUATED"
        or report.get("fr03_status") != "NO_GO"
        or report.get("canonical_pin_changed") is not False
    ):
        raise CandidateArtifactError(
            "candidate report does not record the bounded preflight result"
        )

    run_id = cast(str, report.get("run_id"))
    candidate = _mapping(report.get("candidate_runtime"), "candidate runtime")
    preflight = _mapping(report.get("preflight"), "candidate preflight")
    experiment = _mapping(report.get("experiment"), "candidate experiment")
    p10 = _mapping(report.get("p10_live_result"), "candidate live P10 result")
    if (
        candidate.get("sdk_version") != "0.156.1"
        or candidate.get("runtime_package_version") != "0.156.1"
        or candidate.get("sdk_runtime_versions_equal") is not True
        or candidate.get("runtime_binary_sha256")
        != "0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
        or not str(candidate.get("bundled_app_server_version", "")).startswith("0.156.1 ")
        or preflight.get("host_account_precheck") != "FAILED"
        or preflight.get("host_account_precheck_error_class") != "InternalRpcError"
        or preflight.get("existing_host_thread_start_after_account_failure") != "NOT_REACHED"
        or preflight.get("model_turn_started") is not False
        or preflight.get("provider_request_started") is not False
        or preflight.get("quantos_adapter_host_preflight_invocation_count") not in {None, 2}
        or preflight.get("quantos_adapter_host_each_request_max_attempts") not in {None, 1}
        or preflight.get("quantos_adapter_host_terminal_error_kind") not in {None, "UNKNOWN"}
        or preflight.get("quantos_adapter_host_result")
        not in {None, "FAILED_BEFORE_THREAD_OR_TURN"}
        or preflight.get("quantos_adapter_host_runtime_identity_returned") not in {None, False}
        or preflight.get("quantos_adapter_host_thread_id_count") not in {None, 0}
        or preflight.get("quantos_adapter_host_provider_event_count") not in {None, 0}
        or (
            run_id.endswith("-002")
            and (
                report.get("stopping_point") != "SDK_HOST_FAILURE_BEFORE_THREAD_TURN"
                or preflight.get("quantos_adapter_host_preflight_invocation_count") != 2
                or preflight.get("quantos_adapter_host_each_request_max_attempts") != 1
                or preflight.get("quantos_adapter_host_terminal_error_kind") != "UNKNOWN"
            )
        )
        or experiment.get("model") != "gpt-5.6-sol"
        or experiment.get("provider") != "NOT_STARTED"
        or experiment.get("codex_home_isolated") is not True
        or experiment.get("authentication_bytes_retained") is not False
        or p10.get("status") != "NOT_EVALUATED"
        or p10.get("score") is not None
        or p10.get("command_started_count") is not None
        or p10.get("command_terminal_count") is not None
        or p10.get("matched_probe_count") is not None
    ):
        raise CandidateArtifactError("candidate preflight identity or stop boundary is invalid")

    if (
        audit.get("classification") != "ADDITIVE_COMPATIBLE"
        or audit.get("normalizer_change_required") is not False
        or audit.get("p10_observation_contract_change_required") is not False
        or audit.get("command_lifecycle_wire_contract") != "UNCHANGED"
    ):
        raise CandidateArtifactError("compatibility audit classification is inconsistent")

    event_envelopes: list[dict[str, object]] = []
    for event in notifications:
        envelope = _mapping(event, "notification envelope")
        if not isinstance(envelope.get("method"), str) or not isinstance(
            envelope.get("payload"), dict
        ):
            raise CandidateArtifactError("synthetic notification envelope is malformed")
        event_envelopes.append(envelope)

    try:
        normalized = normalize_provider_events(event_envelopes, thread_id="preflight-thread")
        capture = capture_from_agent_events(normalized, max_bytes=100_000)
    except (ValueError, TypeError) as error:
        raise CandidateArtifactError(
            "synthetic notifications do not replay through the v2 normalizer"
        ) from error

    if (
        NORMALIZER_IDENTIFIER != "quantos-codex-normalizer/v2"
        or capture.command_started_count != 1
        or capture.command_terminal_count != 1
        or capture.command_lifecycle_integrity is not True
        or len(capture.command_lifecycles) != 1
        or capture.command_lifecycles[0].command != "/usr/bin/pwd"
        or capture.command_lifecycles[0].thread_id != "preflight-thread"
        or capture.command_lifecycles[0].turn_id != "preflight-turn"
        or capture.command_lifecycles[0].exit_code != 0
    ):
        raise CandidateArtifactError("synthetic public command lifecycle did not replay exactly")

    historical = verify_codex_spike_artifact(HISTORICAL_P10_PATH, fixture_root)
    historical_report = _mapping(report.get("historical_p10"), "historical P10 reference")
    historical_manifest_hash = historical.manifest.normalized_transcript_hash
    inputs = load_frozen_spike_inputs(fixture_root)
    frozen_request = _sdk_request(inputs)
    fixture_hashes = sorted(inputs.all_input_hashes)
    normalizer_hash = sha256_bytes(
        (ROOT / "src/quantos/integrations/codex/event_normalizer.py").read_bytes()
    )
    if (
        experiment.get("frozen_p10_v3_request_hash") != frozen_request.content_hash
        or experiment.get("requested_sdk_config_hash")
        != sha256_bytes(canonical_json_bytes(_sdk_config(frozen_request)))
        or experiment.get("requested_runtime_policy_hash")
        != frozen_request.runtime_policy.content_hash
        or experiment.get("p10_v3_fixture_input_hashes") != fixture_hashes
        or experiment.get("p10_v3_fixture_hash")
        != sha256_bytes(canonical_json_bytes(fixture_hashes))
        or experiment.get("normalizer_identifier") != NORMALIZER_IDENTIFIER
        or experiment.get("normalizer_sha256") != normalizer_hash
        or historical.report.content_hash != historical_report.get("report_hash")
        or historical.manifest.content_hash != historical_report.get("manifest_hash")
        or historical_manifest_hash != historical_report.get("normalized_transcript_hash")
        or historical.report.decision.value != "NO_GO"
        or sum(check.passed for check in historical.report.checks) != 6
    ):
        raise CandidateArtifactError(
            "historical canonical P10 replay differs from its bound report"
        )

    return {
        "schema_version": "fr03-codex-preflight-verification/v1",
        "artifact_hash": report_hash,
        "classification": audit["classification"],
        "historical_p10_replay": "PASS",
        "synthetic_lifecycle_replay": "PASS",
        "qualification_result": report["qualification_result"],
        "fr03_status": report["fr03_status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-run",
        type=Path,
        required=True,
        help="Offline-verify one retained Codex candidate preflight artifact.",
    )
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    args = parser.parse_args()
    result = verify_candidate_preflight_artifact(
        args.verify_run.resolve(), fixture_root=args.fixture_root.resolve()
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
