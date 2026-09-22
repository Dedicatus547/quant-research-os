from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    AgentRunManifestV3,
    AgentUsage,
    HarnessAttemptRecord,
    HarnessCapabilityObservation,
    RunStatus,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)
HASH = "a" * 64


def _manifest() -> AgentRunManifestV3:
    usage = AgentUsage(input_tokens=10, output_tokens=2, tool_calls=0, retry_count=0)
    return AgentRunManifestV3(
        run_spec_hash=HASH,
        provider_model_identifier="gpt-test",
        sdk_version="0.154.0",
        runtime_package_version="0.154.0",
        runtime_version="0.154.0 test",
        runtime_binary_hash=HASH,
        normalizer_hash=HASH,
        requested_policy_hash=HASH,
        capability_observation_hash=HASH,
        instruction_hashes=(HASH,),
        skill_hash=HASH,
        tool_schema_hash=HASH,
        interactions=(),
        input_hashes=(HASH,),
        output_proposal_hashes=(HASH,),
        normalized_transcript_hash=HASH,
        provider_transcript_hash=HASH,
        attempts=(
            HarnessAttemptRecord(
                attempt_index=1,
                provider_thread_id="thread-1",
                event_stream_hash=HASH,
                usage=usage,
                produced_proposal_hash=HASH,
                started_at=NOW,
                completed_at=NOW,
            ),
        ),
        aggregate_usage=usage,
        run_status=RunStatus.SUCCEEDED,
        limitations=(
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
        ),
        started_at=NOW,
        completed_at=NOW,
    )


def test_v3_separates_requested_policy_from_unattested_runtime_policy() -> None:
    manifest = _manifest()

    assert manifest.requested_policy_hash == HASH
    assert manifest.resolved_runtime_config_hash is None
    assert manifest.attested_policy_hash is None
    assert manifest.runtime_package_version == "0.154.0"
    assert manifest.runtime_binary_hash == HASH
    assert manifest.normalizer_identifier == "quantos-codex-normalizer/v2"


def test_v3_requires_attestation_limitation_when_policy_is_unknown() -> None:
    payload = _manifest().model_dump(mode="python")
    payload["limitations"] = ("MODEL_IDENTIFIER_NOT_IMMUTABLE",)

    with pytest.raises(ValidationError, match="policy attestation"):
        AgentRunManifestV3.model_validate(payload)


def test_v3_attestation_requires_resolved_runtime_config() -> None:
    payload = _manifest().model_dump(mode="python")
    payload["attested_policy_hash"] = HASH
    payload["limitations"] = ("MODEL_IDENTIFIER_NOT_IMMUTABLE",)

    with pytest.raises(ValidationError, match="resolved runtime configuration"):
        AgentRunManifestV3.model_validate(payload)


def test_capability_observation_rejects_claims_without_command_events() -> None:
    with pytest.raises(ValidationError, match="without command events"):
        HarnessCapabilityObservation(
            command_count=0,
            shell_command_observed=False,
            filesystem_denial_observed=False,
            approval_request_observed=False,
            normalized_transcript_hash=HASH,
        )
