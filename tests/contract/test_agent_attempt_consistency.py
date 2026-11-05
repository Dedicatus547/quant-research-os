"""Serialized agent receipts cannot manufacture success, retries or usage."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_agent_run_manifest_v2 import _manifest as manifest_v2
from test_agent_run_manifest_v3 import _manifest as manifest_v3


@pytest.mark.parametrize("factory", [manifest_v2, manifest_v3])
@pytest.mark.parametrize(
    "attack",
    [
        "time",
        "naive",
        "empty",
        "ordinal",
        "extra_proposal",
        "runtime",
        "failure_with_proposal",
        "empty_success",
        "usage",
        "tool_count",
        "instructions",
        "inputs",
        "mutable_model",
        "provider_original",
        "two_originals",
        "attempt_time",
        "attempt_naive",
        "attempt_error",
        "retryable_success",
    ],
)
def test_manifest_rejects_inconsistent_original_attempts(factory, attack):
    manifest = factory()
    value = manifest.model_dump()
    attempt = value["attempts"][0]
    if attack == "time":
        value["completed_at"] = value["started_at"] - timedelta(seconds=1)
    elif attack == "naive":
        value["started_at"] = value["started_at"].replace(tzinfo=None)
    elif attack == "empty":
        value["attempts"] = ()
    elif attack == "ordinal":
        attempt["attempt_index"] = 2
    elif attack == "extra_proposal":
        value["output_proposal_hashes"] = ("b" * 64,)
    elif attack == "runtime":
        value["sdk_version"] = None
    elif attack == "failure_with_proposal":
        value.update(run_status="FAILED", failure_reason_code="HARNESS_TIMEOUT")
    elif attack == "empty_success":
        attempt["produced_proposal_hash"] = None
        value["output_proposal_hashes"] = ()
    elif attack == "usage":
        value["aggregate_usage"]["input_tokens"] += 1
    elif attack == "tool_count":
        attempt["usage"]["tool_calls"] = 1
        value["aggregate_usage"]["tool_calls"] = 1
    elif attack == "instructions":
        value["instruction_hashes"] = ()
    elif attack == "inputs":
        value["input_hashes"] = ()
    elif attack == "mutable_model":
        value["limitations"] = tuple(
            x for x in value["limitations"] if x != "MODEL_IDENTIFIER_NOT_IMMUTABLE"
        )
    elif attack == "provider_original":
        value["provider_transcript_hash"] = None
    elif attack == "two_originals":
        value["provider_transcript_retention_reason"] = "SDK_HOST_UNAVAILABLE"
    elif attack == "attempt_time":
        attempt["completed_at"] = attempt["started_at"] - timedelta(seconds=1)
    elif attack == "attempt_naive":
        attempt["completed_at"] = attempt["completed_at"].replace(tzinfo=None)
    elif attack == "attempt_error":
        attempt["terminal_error_kind"] = "TIMEOUT"
    else:
        attempt["error_retryable"] = True
    with pytest.raises(ValidationError):
        type(manifest).model_validate(value)
