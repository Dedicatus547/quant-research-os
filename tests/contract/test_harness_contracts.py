from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    CodexHarnessSpikeReport,
    CodexHarnessSpikeSpec,
    HarnessCapability,
    HarnessCapabilityCheck,
    HarnessDecision,
    ReasonCode,
)

H = "a" * 64
NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _spec() -> CodexHarnessSpikeSpec:
    return CodexHarnessSpikeSpec(
        spike_id="p10-contract-test",
        provider_model_identifier="gpt-5.6-sol",
        model_reasoning_effort="medium",
        codex_cli_version="codex-cli 0.153.4",
        shell_environment=("LANG", "PATH", "TZ"),
        capability_policy_hash=H,
        instruction_hashes=("1" * 64,),
        task_hash="2" * 64,
        dataset_hash="3" * 64,
        mcp_server_hash="4" * 64,
        mcp_tool_schema_hash="5" * 64,
        output_schema_hash="6" * 64,
        manual_baseline_hash="7" * 64,
        write_probe_hash="8" * 64,
        required_capabilities=tuple(sorted(HarnessCapability, key=str)),
        max_transcript_bytes=1_000,
        max_input_tokens=2_000,
        max_output_tokens=500,
    )


def _checks(*, failed: HarnessCapability | None = None) -> tuple[HarnessCapabilityCheck, ...]:
    return tuple(
        HarnessCapabilityCheck(
            capability=capability,
            passed=capability is not failed,
            evidence_hashes=(H,),
            detail="frozen evidence",
            reason_code=(ReasonCode.HARNESS_CAPABILITY_MISSING if capability is failed else None),
        )
        for capability in sorted(HarnessCapability, key=str)
    )


def test_harness_spec_freezes_every_hard_capability_and_minimal_environment() -> None:
    spec = _spec()

    assert spec.model_snapshot_immutable is False
    assert set(spec.required_capabilities) == set(HarnessCapability)

    with pytest.raises(ValidationError, match="every frozen hard capability"):
        CodexHarnessSpikeSpec.model_validate(
            {
                **spec.model_dump(mode="python"),
                "required_capabilities": tuple(HarnessCapability)[:-1],
            }
        )
    with pytest.raises(ValidationError, match="frozen minimal key set"):
        CodexHarnessSpikeSpec.model_validate(
            {**spec.model_dump(mode="python"), "shell_environment": ("LANG", "TZ")}
        )


def test_harness_check_requires_evidence_and_failed_reason() -> None:
    with pytest.raises(ValidationError, match="failed capability requires a reason"):
        HarnessCapabilityCheck(
            capability=HarnessCapability.MCP,
            passed=False,
            evidence_hashes=(H,),
            detail="failed",
        )
    with pytest.raises(ValidationError, match="forbids one"):
        HarnessCapabilityCheck(
            capability=HarnessCapability.MCP,
            passed=True,
            evidence_hashes=(H,),
            detail="passed",
            reason_code=ReasonCode.HARNESS_CAPABILITY_MISSING,
        )


def test_report_decision_is_derived_from_complete_capability_matrix() -> None:
    report = CodexHarnessSpikeReport(
        spike_spec_hash=_spec().content_hash,
        agent_run_manifest_hash="7" * 64,
        transcript_hash="8" * 64,
        raw_transcript_retained=True,
        checks=_checks(),
        decision=HarnessDecision.GO,
        limitations=("SYNTHETIC_CAPABILITY_SPIKE",),
        created_at=NOW,
    )
    assert report.decision is HarnessDecision.GO

    with pytest.raises(ValidationError, match="does not match"):
        CodexHarnessSpikeReport.model_validate(
            {
                **report.model_dump(mode="python"),
                "checks": _checks(failed=HarnessCapability.SANDBOX),
            }
        )
    with pytest.raises(ValidationError, match="one sorted check"):
        CodexHarnessSpikeReport.model_validate(
            {**report.model_dump(mode="python"), "checks": report.checks[:-1]}
        )
