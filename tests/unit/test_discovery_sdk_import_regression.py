"""Synthetic normalized SDK imports: frozen provenance checked without importing SDK."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_offline_regression import requests

from quantos.application.agent_harness import (
    HarnessCaptureError,
    capture_from_agent_events,
    make_agent_event,
)
from quantos.application.discovery_generation import GenerationStore
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.agent import (
    AgentRunManifestV3,
    AgentRunSpecV3,
    AgentUsage,
    HarnessAttemptRecord,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import GenerationResponse
from quantos.contracts.harness import AgentEventKind, HarnessExecutionRequest, HarnessRuntimePolicy


@pytest.fixture
def sdk_import(design, durable):
    config = canonical_json_bytes(
        {"model_identifier": "gpt-6.1-sol", "model_reasoning_effort": "medium"}
    )
    request = requests(design)[0].model_copy(update={"configuration_hash": sha256_bytes(config)})
    store = GenerationStore(durable / "sdk-import")
    store.save_request(design, request)
    reservation = store.reserve(request)
    execution = HarnessExecutionRequest(
        run_id="synthetic-import",
        cwd=str(durable),
        prompt=request.prompt,
        model=request.model_identifier,
        reasoning_effort=request.reasoning_effort,
        runtime_policy=HarnessRuntimePolicy(
            host_environment=(),
            child_environment=(),
            shell_environment=(),
            shell_tool_enabled=False,
        ),
        mcp_servers=(),
        timeout_seconds=900,
        total_timeout_seconds=900,
        max_transcript_bytes=200000,
        max_input_tokens=250000,
        max_output_tokens=4096,
    )
    inputs = tuple(sorted((request.content_hash, design.content_hash, reservation.content_hash)))
    spec = AgentRunSpecV3(
        run_id=execution.run_id,
        role="FORMALIZER",
        capability_policy_hash="a" * 64,
        campaign_hash="b" * 64,
        requested_model_configuration_hash=request.configuration_hash,
        requested_runtime_policy_hash=execution.runtime_policy.content_hash,
        transcript_policy_hash=sha256_bytes(
            canonical_json_bytes({"max_bytes": execution.max_transcript_bytes, "retain": True})
        ),
        retry_budget_hash=sha256_bytes(
            canonical_json_bytes(
                {"max_attempts": 1, "retry_backoff_milliseconds": 0, "total_timeout_seconds": 900}
            )
        ),
        tool_schema_hash="c" * 64,
        instruction_hashes=("d" * 64,),
        skill_hash="e" * 64,
        input_artifact_hashes=inputs,
    )
    text = design.authoring.expression.canonical_bytes().decode()
    events = tuple(
        make_agent_event(sequence=i, kind=kind, provider_event_type="synthetic", payload=payload)
        for i, (kind, payload) in enumerate(
            [
                (AgentEventKind.TURN_STARTED, {}),
                (AgentEventKind.AGENT_MESSAGE, {"text": text}),
                (
                    AgentEventKind.USAGE,
                    {"usage": {"input_tokens": 12, "output_tokens": 3, "cached_input_tokens": 0}},
                ),
                (AgentEventKind.TURN_COMPLETED, {}),
            ],
            start=1,
        )
    )
    capture = capture_from_agent_events(events, max_bytes=execution.max_transcript_bytes)
    usage = AgentUsage(
        input_tokens=12, output_tokens=3, cached_input_tokens=0, tool_calls=0, retry_count=0
    )
    now = datetime.now(UTC)
    manifest = AgentRunManifestV3(
        run_spec_hash=spec.content_hash,
        provider_model_identifier="gpt-6.1-sol",
        sdk_version="0.162.1",
        runtime_package_version="0.162.1",
        runtime_version="synthetic-no-runtime",
        runtime_binary_hash="a" * 64,
        normalizer_hash="b" * 64,
        requested_policy_hash=execution.runtime_policy.content_hash,
        capability_observation_hash="c" * 64,
        instruction_hashes=spec.instruction_hashes,
        skill_hash=spec.skill_hash,
        tool_schema_hash=spec.tool_schema_hash,
        interactions=(),
        input_hashes=inputs,
        output_proposal_hashes=(design.authoring.expression.content_hash,),
        normalized_transcript_hash=capture.transcript_hash,
        provider_transcript_hash="d" * 64,
        attempts=(
            HarnessAttemptRecord(
                attempt_index=1,
                event_stream_hash=capture.transcript_hash,
                usage=usage,
                produced_proposal_hash=design.authoring.expression.content_hash,
                started_at=now,
                completed_at=now,
            ),
        ),
        aggregate_usage=usage,
        run_status="SUCCEEDED",
        limitations=(
            "EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "SYNTHETIC_IMPORT_NO_MODEL_CALL",
        ),
        started_at=now,
        completed_at=now,
    )
    return SimpleNamespace(
        store=store,
        request=request,
        reservation=reservation,
        execution=execution,
        spec=spec,
        config=config,
        text=text,
        capture=capture,
        manifest=manifest,
    )


def validate_import(f, **updates):
    kwargs = dict(
        manifest=f.manifest,
        spec=f.spec,
        normalized_transcript=f.capture.transcript,
        execution_request=f.execution,
        model_configuration=f.config,
    )
    input_units = updates.pop("usage_input_units", 12)
    failure_code = updates.pop("failure_code", None)
    for key, value in updates.items():
        kwargs[{"agent_run": "manifest", "agent_run_spec": "spec"}.get(key, key)] = value
    response = GenerationResponse(
        reservation=f.reservation,
        text=f.text,
        producer="SDK_CAPTURE",
        agent_run_hash=f.manifest.content_hash,
        usage_input_units=input_units,
        usage_output_units=3,
        failure_code=failure_code,
    )
    f.store._agent_binding(f.store._load(f.request), f.request, response, **kwargs)
    return response


def test_captured_sdk_bindings_are_checked_without_conferring_entry_qualification(sdk_import):
    f = sdk_import
    response = validate_import(f)
    assert response.text == f.text and response.agent_run_hash == f.manifest.content_hash
    assert "SYNTHETIC_IMPORT_NO_MODEL_CALL" in f.manifest.limitations
    # The independent discovery SDK entry is not qualified. The store's current
    # secret metadata policy rejects this executor envelope before publication.
    blocked = f.store.complete(
        f.request,
        f.reservation,
        f.text,
        producer="SDK_CAPTURE",
        agent_run_hash=f.manifest.content_hash,
        agent_run=f.manifest,
        agent_run_spec=f.spec,
        normalized_transcript=f.capture.transcript,
        execution_request=f.execution,
        model_configuration=f.config,
    )
    assert blocked.failure_code == "CAPTURE_SECRET_REJECTED" and blocked.agent_run_hash is None
    assert f.store.inventory(f.request)[1] == (blocked,)


@pytest.mark.parametrize(
    "damage",
    [
        "prompt",
        "effort",
        "retry",
        "configuration",
        "spec",
        "usage",
        "text",
        "transcript",
        "proposal",
    ],
)
def test_sdk_import_rejects_provenance_drift_without_retaining_a_proposal(sdk_import, damage):
    f = sdk_import
    updates = {}
    if damage in ("prompt", "effort", "retry"):
        field, value = {
            "prompt": ("prompt", "different"),
            "effort": ("reasoning_effort", "high"),
            "retry": ("max_attempts", 2),
        }[damage]
        updates["execution_request"] = f.execution.model_copy(update={field: value})
    elif damage == "configuration":
        updates["model_configuration"] = canonical_json_bytes(
            {"model_identifier": "other-model", "model_reasoning_effort": "medium"}
        )
    elif damage == "spec":
        updates["agent_run_spec"] = f.spec.model_copy(update={"input_artifact_hashes": ()})
    elif damage == "usage":
        updates["usage_input_units"] = 0
    elif damage == "text":
        f.text = "{}"
    elif damage == "transcript":
        updates["normalized_transcript"] = f.capture.transcript + f.capture.transcript
    else:
        updates["agent_run"] = f.manifest.model_copy(update={"output_proposal_hashes": ("f" * 64,)})
    with pytest.raises((ArtifactIntegrityError, HarnessCaptureError)):
        validate_import(f, **updates)
    assert f.store.inventory(f.request)[1] == ()


@pytest.mark.parametrize("claimed_failure", ["OVERLOADED", "OUTPUT_INVALID"])
def test_failed_sdk_import_retains_failure_without_a_proposal_or_retry(sdk_import, claimed_failure):
    from quantos.contracts.status import RunStatus

    f = sdk_import
    f.text = ""
    old_events = [
        (AgentEventKind.TURN_STARTED, {}),
        (
            AgentEventKind.USAGE,
            {"usage": {"input_tokens": 12, "output_tokens": 3, "cached_input_tokens": 0}},
        ),
        (AgentEventKind.TURN_FAILED, {}),
    ]
    events = tuple(
        make_agent_event(sequence=i, kind=k, provider_event_type="synthetic", payload=p)
        for i, (k, p) in enumerate(old_events, 1)
    )
    f.capture = capture_from_agent_events(events, max_bytes=f.execution.max_transcript_bytes)
    attempt = f.manifest.attempts[0].model_copy(
        update={
            "event_stream_hash": f.capture.transcript_hash,
            "produced_proposal_hash": None,
            "terminal_error_kind": "OVERLOADED",
            "terminal_error_message_hash": "e" * 64,
        }
    )
    f.manifest = AgentRunManifestV3.model_validate(
        f.manifest.model_copy(
            update={
                "run_status": RunStatus.FAILED,
                "failure_reason_code": "OVERLOADED",
                "output_proposal_hashes": (),
                "normalized_transcript_hash": f.capture.transcript_hash,
                "attempts": (attempt,),
            }
        ).model_dump(mode="python")
    )
    if claimed_failure == "OVERLOADED":
        result = validate_import(f, failure_code=claimed_failure)
        assert result.text == "" and f.manifest.aggregate_usage.retry_count == 0
        assert f.manifest.output_proposal_hashes == ()
    else:
        with pytest.raises(ArtifactIntegrityError, match="failure differs"):
            validate_import(f, failure_code=claimed_failure)
