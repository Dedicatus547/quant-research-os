from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantos.contracts import (
    AgentRunManifestV2,
    AgentUsage,
    HarnessAttemptRecord,
    RunStatus,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
HASH = "a" * 64


def _usage() -> AgentUsage:
    return AgentUsage(
        input_tokens=10,
        output_tokens=2,
        cached_input_tokens=4,
        tool_calls=0,
        retry_count=0,
    )


def _manifest() -> AgentRunManifestV2:
    usage = _usage()
    return AgentRunManifestV2(
        run_spec_hash=HASH,
        provider_model_identifier="gpt-test",
        sdk_version="0.154.0",
        runtime_version="0.154.0 test",
        normalizer_hash=HASH,
        requested_policy_hash=HASH,
        effective_policy_hash=HASH,
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
        limitations=("MODEL_IDENTIFIER_NOT_IMMUTABLE",),
        started_at=NOW,
        completed_at=NOW,
    )


def test_v2_manifest_binds_runtime_attempt_and_transcript_identity() -> None:
    manifest = _manifest()

    assert manifest.attempts[0].produced_proposal_hash == HASH
    assert manifest.usage == manifest.aggregate_usage
    assert manifest.provider_transcript_retention_reason is None


def test_v2_manifest_rejects_fabricated_success_and_usage() -> None:
    payload = _manifest().model_dump(mode="python")
    with pytest.raises(ValidationError, match="runtime identity"):
        AgentRunManifestV2.model_validate({**payload, "runtime_version": None})
    with pytest.raises(ValidationError, match="aggregate usage"):
        AgentRunManifestV2.model_validate(
            {**payload, "aggregate_usage": _usage().model_copy(update={"input_tokens": 11})}
        )


def test_failed_v2_manifest_may_lack_runtime_but_never_proposal_authority() -> None:
    payload = _manifest().model_dump(mode="python")
    usage = _usage()
    failed_attempt = HarnessAttemptRecord(
        attempt_index=1,
        event_stream_hash=HASH,
        usage=usage,
        terminal_error_kind="TIMEOUT",
        terminal_error_message_hash=HASH,
        started_at=NOW,
        completed_at=NOW,
    )
    failed = AgentRunManifestV2.model_validate(
        {
            **payload,
            "sdk_version": None,
            "runtime_version": None,
            "output_proposal_hashes": (),
            "provider_transcript_hash": None,
            "provider_transcript_retention_reason": "SDK_HOST_UNAVAILABLE",
            "attempts": (failed_attempt,),
            "aggregate_usage": usage,
            "run_status": RunStatus.FAILED,
            "failure_reason_code": "HARNESS_TIMEOUT",
        }
    )

    assert failed.output_proposal_hashes == ()


def test_v2_manifest_rejects_non_retryable_intermediate_attempt() -> None:
    manifest = _manifest()
    payload = manifest.model_dump(mode="python")
    failed_attempt = HarnessAttemptRecord(
        attempt_index=1,
        event_stream_hash="b" * 64,
        usage=_usage(),
        terminal_error_kind="OUTPUT_INVALID",
        terminal_error_message_hash="b" * 64,
        error_retryable=False,
        started_at=NOW,
        completed_at=NOW,
    )
    successful_attempt = manifest.attempts[0].model_copy(update={"attempt_index": 2})
    doubled_usage = _usage().model_copy(
        update={
            "input_tokens": 20,
            "output_tokens": 4,
            "cached_input_tokens": 8,
            "retry_count": 1,
        }
    )

    with pytest.raises(ValidationError, match="retryable failed attempts"):
        AgentRunManifestV2.model_validate(
            {
                **payload,
                "attempts": (failed_attempt, successful_attempt),
                "aggregate_usage": doubled_usage,
            }
        )
