"""Bounded SDK producer for the existing campaign protocol, with durable recovery.

The runtime is invoked only by ``launch``. Preparation and replay are offline.
A launch intent without a completed response/failure is UNKNOWN and never reissued.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Literal, cast

from quantos.application.agent_harness import (
    HarnessAttemptResult,
    HarnessExecutionResult,
    LocalAgentHarness,
    capture_from_agent_events,
    parse_agent_events,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
)
from quantos.contracts.agent import (
    AgentRole,
    AgentRunManifestV3,
    AgentRunSpecV3,
    AgentUsage,
    HarnessAttemptRecord,
)
from quantos.contracts.autonomous import AutonomousCandidateProposal
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import (
    AgentEventKind,
    HarnessCapabilityObservation,
    HarnessEnvironmentVariable,
    HarnessExecutionRequest,
    HarnessRuntimeIdentityV2,
    HarnessRuntimePolicy,
)
from quantos.contracts.hosted import (
    HostedAgentRequest,
    parse_hosted_contract,
    strict_json_object,
    unique_json_object_pairs,
)
from quantos.contracts.sdk_producer import (
    SdkAgentRequest,
    SdkAgentRequestV3,
    SdkAgentResponse,
    SdkAgentResponseV2,
    SdkAgentResponseV3,
    SdkCampaignSpec,
    SdkLaunchReservation,
    SdkProducerProfile,
    SdkProducerProfileV2,
    SdkProducerProfileV3,
    SdkProducerProfileV4,
    SdkSemanticProposal,
    parse_sdk_response,
)
from quantos.contracts.status import RunStatus
from quantos.integrations.codex.notification_projection import (
    IDENTIFIER as METADATA_PROJECTION_IDENTIFIER,
)
from quantos.integrations.codex.notification_projection import (
    normalize_provider_events,
    observe_usage,
    provider_events,
    source_hash,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter
from quantos.security import validate_secret_free


def semantic_schema() -> bytes:
    schema = SdkSemanticProposal.model_json_schema()
    # The host rejects inserted defaults: the SDK must require the same explicit
    # fields, including the literal schema identity, before a real launch.
    schema["required"] = sorted(schema["properties"])
    return canonical_json_bytes(schema)


def runtime_policy() -> HarnessRuntimePolicy:
    environment = tuple(
        HarnessEnvironmentVariable(name=cast(Literal["LANG", "PATH", "TZ"], name), value=value)
        for name, value in (("LANG", "C.UTF-8"), ("PATH", "/usr/bin:/bin"), ("TZ", "UTC"))
    )
    return HarnessRuntimePolicy(
        host_environment=environment,
        child_environment=environment,
        shell_environment=environment,
        shell_tool_enabled=False,
    )


def model_configuration(profile: SdkProducerProfile) -> bytes:
    """Configuration bytes must also be frozen in the business input inventory."""
    return canonical_json_bytes(
        {
            "adapter": "openai-codex-python-sdk",
            "model": profile.model,
            "reasoning_effort": profile.reasoning_effort,
            **(
                {"reasoning_summary": profile.reasoning_summary}
                if profile.reasoning_summary is not None
                else {}
            ),
            "sdk_version": profile.sdk_version,
            "runtime_package_version": profile.runtime_package_version,
            "runtime_binary_hash": profile.runtime_binary_hash,
            "cwd": profile.cwd,
            "runtime_policy_hash": runtime_policy().content_hash,
            "output_schema_hash": sha256_bytes(semantic_schema()),
            "max_attempts": 1,
            **(
                {
                    "prompt_projection_identifier": profile.prompt_projection_identifier,
                    "prompt_projection_hash": profile.prompt_projection_hash,
                }
                if isinstance(profile, SdkProducerProfileV4)
                else {}
            ),
        }
    )


def _nonfinite(_: str) -> object:
    raise ValueError("nonfinite JSON number")


def map_semantic_response(
    request: HostedAgentRequest, raw: bytes, profile: SdkProducerProfile
) -> AutonomousCandidateProposal:
    """Parse ordinary JSON strictly, then derive fields from one exact frozen ref."""
    if len(raw) > profile.max_raw_response_bytes:
        raise ValueError("SDK raw response exceeds bound")
    value: object = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=unique_json_object_pairs,
        parse_constant=_nonfinite,
    )
    if not isinstance(value, dict):
        raise ValueError("SDK semantic response must be an object")
    value = cast(dict[str, object], value)
    validate_secret_free(value, file_name="sdk-semantic-response.json")
    semantic = SdkSemanticProposal.model_validate(value)
    # Reject coercions/default insertion while allowing whitespace/key ordering.
    if semantic.canonical_bytes() != canonical_json_bytes(value):
        raise ValueError("SDK semantic response scalar/default mismatch")
    matches = [
        x
        for x in request.business_request.candidate_options
        if x.candidate_id == semantic.candidate_ref
    ]
    if len(matches) != 1:
        raise ValueError("SDK candidate reference is unknown or ambiguous")
    candidate = matches[0]
    return AutonomousCandidateProposal(
        campaign_hash=request.campaign_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=candidate.expression,
        exact_expression_hash=candidate.exact_expression_hash,
        structural_expression_hash=candidate.structural_expression_hash,
        rationale=semantic.rationale,
        request_stop=semantic.request_stop,
    )


def build_reservation(request: SdkAgentRequest, spec: SdkCampaignSpec) -> SdkLaunchReservation:
    # Direct Python callers must obey the same explicit discriminator/cap as bytes.
    spec = SdkCampaignSpec.model_validate(spec.model_dump(mode="python"))
    profile = spec.sdk_profile
    request_type = (
        SdkAgentRequestV3 if isinstance(profile, SdkProducerProfileV3) else SdkAgentRequest
    )
    if (
        type(request) is not request_type
        or request.schema_version != request_type.model_fields["schema_version"].default
    ):
        raise ArtifactIntegrityError("SDK request version differs from frozen profile")
    if (
        request.campaign_hash != spec.campaign_hash
        or request.hosted_spec_hash != spec.content_hash
        or request.sdk_profile_hash != profile.content_hash
        or request.transport_ordinal > profile.max_launches
        or request.candidate_manifest_hash != spec.candidate_manifest_hash
        or request.business_request.family_hash != spec.campaign.family_hash
        or request.business_request.budget_hash != spec.campaign.budget_hash
        or request.input_hashes
        != tuple(
            sorted(
                {
                    *spec.frozen_input_hashes,
                    *request.business_request.agent_run_spec.input_artifact_hashes,
                }
            )
        )
        or request.max_request_bytes != spec.hosted_budget.max_request_bytes
        or request.max_response_bytes != spec.hosted_budget.max_response_bytes
        or request.max_proposal_bytes != spec.hosted_budget.max_proposal_bytes
        or request.attempt_identity
        != sha256_bytes(
            canonical_json_bytes((spec.campaign_hash, "ATTEMPT", request.transport_ordinal))
        )
        or request.expires_at
        != request.issued_at + timedelta(seconds=spec.hosted_budget.request_ttl_seconds)
    ):
        raise ArtifactIntegrityError("SDK request escaped its frozen profile")
    if sha256_bytes(model_configuration(profile)) != spec.requested_model_configuration_hash:
        raise ArtifactIntegrityError("SDK model configuration bytes/hash disagree")
    if (
        request.business_request.agent_run_spec.requested_model_configuration_hash
        != spec.requested_model_configuration_hash
    ):
        raise ArtifactIntegrityError("SDK business request configuration differs")
    prompt = (
        "Return one JSON object with schema_version sdk-candidate-reference/v1, "
        "candidate_ref copied exactly from a listed candidate_id, rationale and request_stop. "
        "Use only the frozen options and context below. Do not invoke tools. "
        "Do not compute hashes or copy derived proposal fields. "
        "Agent output is a proposal, never evidence. Frozen request:\n"
        + request.canonical_bytes().decode("utf-8")
    )
    if isinstance(profile, SdkProducerProfileV4):
        from quantos.application.sdk_prompt import bounded_prompt

        prompt = bounded_prompt(request, profile)
    execution = HarnessExecutionRequest(
        run_id=f"sdk-{request.attempt_identity}",
        cwd=profile.cwd,
        prompt=prompt,
        model=profile.model,
        reasoning_effort=profile.reasoning_effort,
        reasoning_summary=profile.reasoning_summary,
        runtime_policy=runtime_policy(),
        mcp_servers=(),
        output_schema_json=semantic_schema().decode("utf-8"),
        timeout_seconds=profile.timeout_seconds,
        total_timeout_seconds=profile.timeout_seconds,
        max_transcript_bytes=profile.max_transcript_bytes,
        max_normalized_transcript_bytes=(
            profile.max_normalized_transcript_bytes
            if isinstance(profile, (SdkProducerProfileV2, SdkProducerProfileV3))
            else None
        ),
        max_input_tokens=profile.max_input_tokens,
        max_output_tokens=profile.max_output_tokens,
        max_attempts=1,
    )
    instructions = tuple(sorted(set(profile.instruction_hashes)))
    run_spec = AgentRunSpecV3(
        run_id=execution.run_id,
        role=AgentRole.RESEARCHER,
        capability_policy_hash=execution.runtime_policy.content_hash,
        campaign_hash=request.campaign_hash,
        requested_model_configuration_hash=spec.requested_model_configuration_hash,
        requested_runtime_policy_hash=execution.runtime_policy.content_hash,
        transcript_policy_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "max_bytes": profile.max_transcript_bytes,
                    **(
                        {"max_normalized_bytes": profile.max_normalized_transcript_bytes}
                        if isinstance(profile, (SdkProducerProfileV2, SdkProducerProfileV3))
                        else {}
                    ),
                }
            )
        ),
        retry_budget_hash=sha256_bytes(canonical_json_bytes({"max_attempts": 1, "reissue": False})),
        tool_schema_hash=sha256_bytes(canonical_json_bytes(())),
        instruction_hashes=instructions,
        skill_hash=profile.skill_hash,
        ledger_snapshot_hash=request.business_request.context_pack.ledger_snapshot_hash,
        input_artifact_hashes=tuple(
            sorted(
                {
                    request.content_hash,
                    spec.content_hash,
                    profile.content_hash,
                    execution.content_hash,
                    request.context_pack_hash,
                    request.candidate_manifest_hash,
                    sha256_bytes(semantic_schema()),
                    *request.input_hashes,
                    *instructions,
                    profile.skill_hash,
                }
            )
        ),
    )
    return SdkLaunchReservation(
        request_hash=request.content_hash,
        attempt_identity=request.attempt_identity,
        campaign_hash=request.campaign_hash,
        sdk_profile_hash=profile.content_hash,
        execution_request=execution,
        run_spec=run_spec,
    )


def _persist_host_transport(directory: Path, execution: HarnessExecutionResult) -> str | None:
    """Publish optional bounded failed-host originals with independent secret checks."""
    from quantos.application.hosted_protocol import scan_protocol_artifact
    from quantos.integrations.codex.sdk_adapter import contains_parent_secret

    observed = execution.attempts[-1].qualification_observations or {}
    diagnostic = observed.get("host_transport")
    if not isinstance(diagnostic, dict):
        return None
    diagnostic = cast(dict[str, object], diagnostic)
    if diagnostic.get("schema_version") != "sdk-host-transport/v1":
        raise ArtifactIntegrityError("SDK host transport schema is invalid")
    raw_streams = diagnostic.get("streams")
    streams = cast(list[object], raw_streams) if isinstance(raw_streams, list) else None
    if streams is None or len(streams) != 2:
        raise ArtifactIntegrityError("SDK host transport capture shape is invalid")
    clean: dict[str, object] = {
        key: diagnostic.get(key) for key in ("schema_version", "phase", "exception_class")
    }
    metadata: list[dict[str, object]] = []
    expected_names = ("host-stdout.txt", "host-stderr.txt")
    for raw_entry, expected in zip(streams, expected_names, strict=True):
        if not isinstance(raw_entry, dict):
            raise ArtifactIntegrityError("SDK host transport capture escaped fixed file names")
        entry = cast(dict[str, object], raw_entry)
        if entry.get("file") != expected:
            raise ArtifactIntegrityError("SDK host transport capture escaped fixed file names")
        item: dict[str, object] = {
            key: entry[key]
            for key in ("file", "complete", "bytes", "sha256", "retention")
            if key in entry
        }
        if entry.get("retention") == "RETAINED":
            encoded = entry.get("base64")
            if not isinstance(encoded, str) or len(encoded) > 87_384:
                raise ArtifactIntegrityError("SDK host transport encoded capture exceeds cap")
            try:
                payload = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise ArtifactIntegrityError("SDK host transport encoding is invalid") from None
            if (
                len(payload) > 65_536
                or entry.get("bytes") != len(payload)
                or entry.get("sha256") != sha256_bytes(payload)
            ):
                raise ArtifactIntegrityError("SDK host transport original bytes disagree")
            try:
                if contains_parent_secret(payload):
                    raise ValueError("forbidden parent value")
                text = payload.decode("utf-8")
                scan_protocol_artifact(text)
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    value = None
                if value is not None:
                    if contains_parent_secret(canonical_json_bytes(value)):
                        raise ValueError("forbidden decoded parent value")
                    scan_protocol_artifact(value)
            except (ValueError, UnicodeError):
                item["retention"] = "CREDENTIAL_OR_ENCODING_GUARD"
            else:
                atomic_write_bytes(directory / expected, payload)
        metadata.append(item)
    clean["streams"] = metadata
    provider_failure = observed.get("provider_failure")
    if provider_failure is not None:
        from quantos.integrations.codex.event_normalizer import (
            PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
        )

        normalizer_hash = _normalizer_hash()
        if not isinstance(provider_failure, dict):
            raise ArtifactIntegrityError("provider failure observation differs from failed attempt")
        provider_failure = cast(dict[str, object], provider_failure)
        if (
            provider_failure.get("schema_version") != "codex-provider-failure-observation/v1"
            or provider_failure.get("normalizer_identifier")
            != PROVIDER_FAILURE_NORMALIZER_IDENTIFIER
            or provider_failure.get("normalizer_hash") != normalizer_hash
            or provider_failure.get("projection") != "FAILURE_ONLY"
            or provider_failure.get("retryable") is not False
            or execution.terminal_error is None
            or execution.terminal_error.retryable
            or execution.capture.agent_messages
        ):
            raise ArtifactIntegrityError("provider failure observation differs from failed attempt")
        errors = provider_failure.get("provider_errors")
        if not isinstance(errors, list) or not errors:
            raise ArtifactIntegrityError("provider failure observations are absent")
        retained_errors: list[dict[str, object]] = []
        for raw_error in cast(list[object], errors):
            if not isinstance(raw_error, dict):
                raise ArtifactIntegrityError("provider failure observation shape is invalid")
            item = cast(dict[str, object], raw_error)
            code, will_retry = item.get("provider_error_code"), item.get("will_retry")
            size = item.get("message_bytes")
            if (
                item.get("normalizer_identifier") != PROVIDER_FAILURE_NORMALIZER_IDENTIFIER
                or item.get("normalizer_hash") != normalizer_hash
                or item.get("retryable") is not False
                or (
                    code is not None
                    and (
                        not isinstance(code, str)
                        or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,63}", code) is None
                    )
                )
                or (will_retry is not None and not isinstance(will_retry, bool))
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or any(
                    not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                    for digest in (item.get("message_hash"), item.get("provider_error_hash"))
                )
            ):
                raise ArtifactIntegrityError("provider failure observation values are invalid")
            retained_errors.append(
                {
                    key: item[key]
                    for key in (
                        "normalizer_identifier",
                        "normalizer_hash",
                        "provider_error_code",
                        "will_retry",
                        "retryable",
                        "message_bytes",
                        "message_hash",
                        "provider_error_hash",
                    )
                }
            )
        # Explicit successor schema only when the failure-only field is present.
        # Existing successful and historical v1 transport bytes stay unchanged.
        clean["schema_version"] = "sdk-host-transport/v2"
        retained_failure: dict[str, object] = {
            "schema_version": "codex-provider-failure-observation/v1",
            "normalizer_identifier": PROVIDER_FAILURE_NORMALIZER_IDENTIFIER,
            "normalizer_hash": normalizer_hash,
            "projection": "FAILURE_ONLY",
            "retryable": False,
            "provider_errors": retained_errors,
        }
        events = parse_agent_events(execution.normalized_transcript, max_bytes=1_000_000)
        tool_starts = sum(event.kind is AgentEventKind.TOOL_STARTED for event in events)
        usage_observed = any(event.kind is AgentEventKind.USAGE for event in events)
        tool_activity = bool(tool_starts or execution.capture.tool_calls)
        retained_failure["safety_observations"] = {
            "observed_tool_calls": len(execution.capture.tool_calls),
            "observed_tool_started_events": tool_starts,
            "observed_tool_terminal_events": len(execution.capture.tool_calls),
            "tool_activity_observed": tool_activity,
            "observed_command_started_events": execution.capture.command_started_count,
            "observed_command_terminal_events": execution.capture.command_terminal_count,
            "observed_approval_requested": execution.capture.approval_requested,
            "observed_usage": (
                AgentUsage(
                    input_tokens=execution.capture.usage["input_tokens"],
                    output_tokens=execution.capture.usage["output_tokens"],
                    cached_input_tokens=execution.capture.usage["cached_input_tokens"],
                    tool_calls=len(execution.capture.tool_calls),
                    retry_count=0,
                ).model_dump(mode="json")
                if usage_observed
                else None
            ),
            "usage_observation_status": "OBSERVED" if usage_observed else "UNAVAILABLE",
            "manifest_tool_usage_semantics": "MAPPED_CAPABILITY_INTERACTIONS_ONLY",
            "limitations": ["MANIFEST_TOOL_USAGE_NOT_OBSERVATION"]
            + (
                ["MANIFEST_TOOL_USAGE_UNAVAILABLE_FOR_UNMAPPED_PROVIDER_TOOL"]
                if tool_activity
                else []
            ),
        }
        clean["provider_failure"] = retained_failure
    scan_protocol_artifact(clean)
    encoded_metadata = canonical_json_bytes(clean)
    if contains_parent_secret(encoded_metadata):
        raise ArtifactIntegrityError("SDK host transport metadata contains forbidden parent value")
    return atomic_write_bytes(directory / "host-transport.json", encoded_metadata)


def _normalizer_hash() -> str:
    return sha256_bytes(
        (Path(__file__).parents[1] / "integrations/codex/event_normalizer.py").read_bytes()
    )


def _persist_sdk_process_exit(directory: Path, execution: HarnessExecutionResult) -> str | None:
    """Persist actual wait observations before capture/semantic processing can fail."""
    from quantos.application.hosted_protocol import scan_protocol_artifact
    from quantos.integrations.codex.sdk_adapter import contains_parent_secret

    observed = execution.attempts[-1].qualification_observations or {}
    value = observed.get("host_process_exit")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ArtifactIntegrityError("SDK process exit observation is invalid")
    value = cast(dict[str, object], value)
    if (
        set(value) != {"schema_version", "spawned", "wait_observed", "return_code"}
        or value.get("schema_version") != "sdk-host-process-exit/v1"
        or type(value.get("spawned")) is not bool
        or type(value.get("wait_observed")) is not bool
        or (value.get("return_code") is not None and type(value["return_code"]) is not int)
        or value["wait_observed"] != (value["return_code"] is not None)
        or (value["wait_observed"] and not value["spawned"])
    ):
        raise ArtifactIntegrityError("SDK process exit observation is invalid")
    payload = canonical_json_bytes(value)
    scan_protocol_artifact(value)
    if contains_parent_secret(payload):
        raise ArtifactIntegrityError("SDK process exit contains forbidden parent value")
    return atomic_write_bytes(directory / "sdk-process-exit.json", payload)


def _persist_sdk_observation(directory: Path, execution: HarnessExecutionResult) -> str:
    """A separate source-bound usage observation, never accepted evidence or billing."""
    from quantos.application.hosted_protocol import scan_protocol_artifact
    from quantos.integrations.codex.sdk_adapter import contains_parent_secret

    events = provider_events(execution.provider_transcript)
    observed = {
        "schema_version": "sdk-provider-observation/v1",
        "provider_transcript_hash": sha256_bytes(execution.provider_transcript or b""),
        "provider_transcript_available": execution.provider_transcript is not None,
        "usage_observation": observe_usage(events),
        "normalization_pipeline_hash": source_hash(events),
        "projection_identifier": METADATA_PROJECTION_IDENTIFIER,
        "harness_terminal_error": execution.terminal_error.kind.value
        if execution.terminal_error is not None
        else None,
        "normalized_usage_semantics": "CAPTURE_COUNTS_NOT_BILLING",
        "billing": "PROVIDER_EVENT_OBSERVATION_NOT_INVOICE",
    }
    payload = canonical_json_bytes(observed)
    scan_protocol_artifact(observed)
    if contains_parent_secret(payload):
        raise ArtifactIntegrityError("SDK observation contains forbidden parent value")
    return atomic_write_bytes(directory / "sdk-observation.json", payload)


def _manifest(
    reservation: SdkLaunchReservation,
    execution: HarnessExecutionResult,
    started: datetime,
    completed: datetime,
    raw_hash: str | None,
    error: str | None,
) -> tuple[AgentRunManifestV3, HarnessCapabilityObservation]:
    if len(execution.attempts) != 1:
        raise ArtifactIntegrityError("SDK producer requires one actual attempt")
    capture, runtime = execution.capture, execution.runtime
    provider_hash = (
        sha256_bytes(execution.provider_transcript)
        if execution.provider_transcript is not None
        else None
    )
    observation = HarnessCapabilityObservation(
        command_count=len(capture.commands),
        shell_command_observed=bool(capture.commands),
        approval_request_observed=capture.approval_requested,
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_hash,
    )
    # This entry permits no tools. Unexpected tools are rejected before projection.
    usage = AgentUsage(
        input_tokens=capture.usage.get("input_tokens", 0),
        output_tokens=capture.usage.get("output_tokens", 0),
        cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
        tool_calls=0,
        retry_count=0,
    )
    terminal = execution.terminal_error
    kind = terminal.kind.value if terminal else error
    attempt = HarnessAttemptRecord(
        attempt_index=1,
        provider_thread_id=capture.thread_ids[-1] if capture.thread_ids else None,
        event_stream_hash=capture.transcript_hash,
        usage=usage,
        terminal_error_kind=kind,
        terminal_error_message_hash=terminal.message_hash
        if terminal
        else sha256_bytes((error or "").encode())
        if error
        else None,
        error_retryable=terminal.retryable if terminal else False,
        produced_proposal_hash=raw_hash if kind is None else None,
        started_at=started,
        completed_at=completed,
    )
    spec = reservation.run_spec
    manifest = AgentRunManifestV3(
        run_spec_hash=spec.content_hash,
        provider_model_identifier=reservation.execution_request.model,
        sdk_version=runtime.sdk_version if runtime else None,
        runtime_package_version=runtime.runtime_package_version
        if isinstance(runtime, HarnessRuntimeIdentityV2)
        else None,
        runtime_version=runtime.runtime_version if runtime else None,
        runtime_binary_hash=runtime.runtime_binary_hash
        if isinstance(runtime, HarnessRuntimeIdentityV2)
        else None,
        normalizer_hash=source_hash(provider_events(execution.provider_transcript)),
        requested_policy_hash=reservation.execution_request.runtime_policy.content_hash,
        capability_observation_hash=observation.content_hash,
        instruction_hashes=spec.instruction_hashes,
        skill_hash=spec.skill_hash,
        tool_schema_hash=spec.tool_schema_hash,
        interactions=(),
        input_hashes=spec.input_artifact_hashes,
        output_proposal_hashes=(raw_hash,) if raw_hash is not None and kind is None else (),
        normalized_transcript_hash=execution.normalized_transcript_hash,
        provider_transcript_hash=provider_hash,
        provider_transcript_retention_reason=None if provider_hash else "SDK_HOST_UNAVAILABLE",
        attempts=(attempt,),
        aggregate_usage=usage,
        run_status=RunStatus.SUCCEEDED if kind is None else RunStatus.FAILED,
        failure_reason_code="HARNESS_OUTPUT_INVALID" if kind else None,
        limitations=("EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED", "MODEL_IDENTIFIER_NOT_IMMUTABLE"),
        started_at=started,
        completed_at=completed,
    )
    return manifest, observation


def _response_type(profile: SdkProducerProfile) -> type[SdkAgentResponse]:
    if isinstance(profile, SdkProducerProfileV3):
        return SdkAgentResponseV3
    if isinstance(profile, SdkProducerProfileV2):
        return SdkAgentResponseV2
    return SdkAgentResponse


def verify_sdk_response(
    request: SdkAgentRequest, spec: SdkCampaignSpec, response: SdkAgentResponse
) -> None:
    """Rebuild mapping and actual capture/usage identities on submit and replay."""
    response_type = _response_type(spec.sdk_profile)
    if (
        type(response) is not response_type
        or response.schema_version != response_type.model_fields["schema_version"].default
    ):
        raise ValueError("SDK capture response version differs from frozen profile")
    expected = build_reservation(request, spec)
    if len(response.canonical_bytes()) > request.max_response_bytes:
        raise ValueError("SDK source response exceeds frozen transport cap")
    if response.reservation != expected or (
        response.request_hash,
        response.campaign_hash,
        response.transport_ordinal,
        response.context_pack_hash,
        response.attempt_identity,
        response.sdk_profile_hash,
    ) != (
        request.content_hash,
        request.campaign_hash,
        request.transport_ordinal,
        request.context_pack_hash,
        request.attempt_identity,
        spec.sdk_profile.content_hash,
    ):
        raise ValueError("SDK source request/profile differs")
    normalized = response.normalized_transcript.encode("utf-8")
    capture = capture_from_agent_events(
        parse_agent_events(
            normalized,
            max_bytes=expected.execution_request.max_normalized_transcript_bytes
            or spec.sdk_profile.max_transcript_bytes,
        ),
        max_bytes=expected.execution_request.max_normalized_transcript_bytes
        or spec.sdk_profile.max_transcript_bytes,
    )
    profile, manifest = spec.sdk_profile, response.manifest
    if (
        capture.agent_messages != (response.raw_response,)
        or not capture.turn_completed
        or not capture.turn_started
        or capture.turn_failed
        or capture.approval_requested
        or capture.commands
        or capture.tool_calls
        or capture.attempt_index != 1
    ):
        raise ValueError("SDK source final message/permissions differ")
    if not capture.thread_ids:
        raise ValueError("SDK source thread unavailable")
    provider = response.provider_transcript.encode("utf-8")
    if len(provider) > profile.max_transcript_bytes:
        raise ValueError("SDK provider transcript exceeds bound")
    provider_events = tuple(
        cast(
            dict[str, object],
            json.loads(line, object_pairs_hook=unique_json_object_pairs, parse_constant=_nonfinite),
        )
        for line in provider.splitlines()
    )
    reconstructed = capture_from_agent_events(
        normalize_provider_events(provider_events, thread_id=capture.thread_ids[-1], attempt=1),
        max_bytes=expected.execution_request.max_normalized_transcript_bytes
        or profile.max_transcript_bytes,
    )
    if reconstructed.transcript != normalized:
        raise ValueError("SDK provider/normalized originals disagree")
    if not (
        0 < capture.usage.get("input_tokens", 0) <= profile.max_input_tokens
        and 0 < capture.usage.get("output_tokens", 0) <= profile.max_output_tokens
    ):
        raise ValueError("SDK observed usage absent/over bound")
    if (
        manifest.sdk_version,
        manifest.runtime_package_version,
        manifest.runtime_binary_hash,
        manifest.provider_model_identifier,
    ) != (
        profile.sdk_version,
        profile.runtime_package_version,
        profile.runtime_binary_hash,
        profile.model,
    ):
        raise ValueError("SDK actual runtime differs from frozen profile")
    if (
        manifest.runtime_version is None
        or manifest.runtime_version.partition(" ")[0] != profile.runtime_package_version
    ):
        raise ValueError("SDK runtime version differs from accepted package")
    runtime = HarnessRuntimeIdentityV2(
        sdk_version=profile.sdk_version,
        runtime_package_version=profile.runtime_package_version,
        runtime_version=manifest.runtime_version,
        runtime_binary_hash=profile.runtime_binary_hash,
    )  # type: ignore[arg-type]
    execution = HarnessExecutionResult(
        attempts=(
            HarnessAttemptResult(
                capture=capture, runtime=runtime, terminal_error=None, provider_transcript=provider
            ),
        )
    )
    rebuilt, _ = _manifest(
        expected,
        execution,
        manifest.started_at,
        manifest.completed_at,
        response.raw_response_hash,
        None,
    )
    if manifest != rebuilt or response.proposal_json != map_semantic_response(
        request, response.raw_response.encode("utf-8"), profile
    ).canonical_bytes().decode("utf-8"):
        raise ValueError("SDK manifest/projection differs from retained originals")


def require_sdk_storage_reservation(roots: tuple[Path, ...], expected_new_bytes: int) -> None:
    """Reuse the existing host-volume supervisor/lease; no parallel reservation pool."""
    from quantos.artifacts.store import opened_directory, read_regular_bytes_at
    from quantos.infrastructure.hosted_storage import LEASE_ENV, StorageRejected, configured_guard

    if type(expected_new_bytes) is not int or expected_new_bytes <= 0:
        raise StorageRejected("STORAGE_ESTIMATE_INVALID")
    try:
        guard = configured_guard()
        for root in roots:
            guard.require_root(root)
        guard.require_lease()
        with opened_directory(Path(os.environ[LEASE_ENV])) as parent:
            data = read_regular_bytes_at(parent, "prelaunch.json", max_bytes=16384)
        decoded: object = json.loads(data)
        if not isinstance(decoded, dict):
            raise StorageRejected("STORAGE_SUPERVISOR_UNBOUND")
        reservation = cast(dict[str, object], decoded).get("expected_new_bytes")
        if type(reservation) is not int or reservation < expected_new_bytes:
            raise StorageRejected("STORAGE_ESTIMATE_EXCEEDS_LEASE")
        guard.check(expected_new_bytes)
    except (OSError, KeyError, TypeError, ValueError):
        raise StorageRejected("STORAGE_OBSERVATION_UNAVAILABLE") from None


def _stable_directory(path: Path) -> Path:
    """Frozen producer directories cannot change authority through path aliases."""
    absolute = path.absolute()
    try:
        aliased = absolute != absolute.resolve() or any(
            part.is_symlink() for part in (absolute, *absolute.parents)
        )
    except (OSError, RuntimeError):
        raise ValueError("SDK directory aliases or symlink components are forbidden") from None
    if aliased:
        raise ValueError("SDK directory aliases or symlink components are forbidden")
    return absolute


class SdkCampaignProducer:
    def __init__(self, root: Path) -> None:
        resolved = _stable_directory(root)
        if (
            resolved == Path("/tmp")
            or Path("/tmp") in resolved.parents
            or resolved == Path("/var/tmp")
            or Path("/var/tmp") in resolved.parents
        ):
            raise ValueError("SDK authoritative evidence requires durable storage")
        self.root = resolved

    def _directory(self, request: SdkAgentRequest) -> Path:
        return _stable_directory(self.root / request.campaign_hash / request.content_hash)

    def _assert_root(self, spec: SdkCampaignSpec) -> None:
        frozen = Path(spec.sdk_profile.evidence_root)
        if not frozen.is_absolute() or _stable_directory(frozen) != _stable_directory(self.root):
            raise ArtifactIntegrityError("SDK durable evidence root differs from frozen profile")

    def prepare(self, request: SdkAgentRequest, spec: SdkCampaignSpec) -> SdkLaunchReservation:
        self._assert_root(spec)
        reservation = build_reservation(request, spec)
        directory = self._directory(request)
        from quantos.application.hosted_protocol import scan_protocol_artifact
        from quantos.integrations.codex.sdk_adapter import contains_parent_secret

        for artifact in (request, spec, reservation):
            if contains_parent_secret(artifact.canonical_bytes()):
                raise ArtifactIntegrityError("SDK frozen input contains forbidden parent value")
            scan_protocol_artifact(artifact.model_dump(mode="json"))
        with exclusive_directory_lock(directory):
            for name, data in (
                ("request.json", request.canonical_bytes()),
                ("campaign-spec.json", spec.canonical_bytes()),
                ("semantic-schema.json", semantic_schema()),
                ("model-configuration.json", model_configuration(spec.sdk_profile)),
                ("reservation.json", reservation.canonical_bytes()),
            ):
                atomic_write_bytes(directory / name, data)
        return reservation

    def status(self, request: SdkAgentRequest, spec: SdkCampaignSpec) -> str:
        self._assert_root(spec)
        directory = self._directory(request)
        if (directory / "response.json").exists():
            self.replay(request, spec)
            return "CAPTURED"
        if (directory / "failure.json").exists():
            failure = strict_json_object(
                confined_regular_file(directory, "failure.json").read_bytes(), max_bytes=16384
            )
            if failure.get("state") != "FAILED":
                raise ArtifactIntegrityError("SDK failure state differs")
            manifest_hash = failure.get("manifest_hash")
            if manifest_hash is not None:
                data = confined_regular_file(directory, "agent-run-manifest.json").read_bytes()
                manifest = parse_hosted_contract(
                    data, AgentRunManifestV3, max_bytes=request.max_response_bytes
                )
                if (
                    sha256_bytes(data) != manifest_hash
                    or manifest.run_status is not RunStatus.FAILED
                ):
                    raise ArtifactIntegrityError("SDK failure manifest differs")
            return "FAILED"
        if (directory / "launch-intent.json").exists():
            intent = strict_json_object(
                confined_regular_file(directory, "launch-intent.json").read_bytes(), max_bytes=16384
            )
            if intent.get("reservation_hash") != build_reservation(request, spec).content_hash:
                raise ArtifactIntegrityError("SDK launch intent differs from frozen reservation")
            return "UNKNOWN"
        if (directory / "reservation.json").exists():
            return "PREPARED"
        return "NOT_PREPARED"

    def read_published(self, request: SdkAgentRequest, spec: SdkCampaignSpec) -> SdkAgentResponse:
        """Read-only source authority check; protocol validation cannot repair outputs."""
        return self.replay(request, spec, recover=False)

    def replay(
        self, request: SdkAgentRequest, spec: SdkCampaignSpec, *, recover: bool = True
    ) -> SdkAgentResponse:
        self._assert_root(spec)
        directory = self._directory(request)
        reservation = build_reservation(request, spec)
        for name, expected in (
            ("request.json", request.canonical_bytes()),
            ("campaign-spec.json", spec.canonical_bytes()),
            ("reservation.json", reservation.canonical_bytes()),
            ("semantic-schema.json", semantic_schema()),
            ("model-configuration.json", model_configuration(spec.sdk_profile)),
        ):
            if confined_regular_file(directory, name).read_bytes() != expected:
                raise ArtifactIntegrityError("SDK prepared source artifact differs")
        if not (directory / "response.json").exists():
            if not recover:
                raise ArtifactIntegrityError("SDK published response is unavailable")
            fact = strict_json_object(
                confined_regular_file(directory, "capture-fact.json").read_bytes(), max_bytes=16384
            )
            if (
                fact.get("reservation_hash") != reservation.content_hash
                or fact.get("terminal_error") is not None
                or fact.get("observed_tool_calls") != 0
            ):
                raise ArtifactIntegrityError("SDK retained capture is not a successful source")
            normalized = confined_regular_file(
                directory, "normalized-transcript.jsonl"
            ).read_bytes()
            provider = confined_regular_file(directory, "provider-transcript.jsonl").read_bytes()
            raw = confined_regular_file(directory, "raw-response.txt").read_bytes()
            capture = capture_from_agent_events(
                parse_agent_events(
                    normalized,
                    max_bytes=reservation.execution_request.max_normalized_transcript_bytes
                    or spec.sdk_profile.max_transcript_bytes,
                ),
                max_bytes=reservation.execution_request.max_normalized_transcript_bytes
                or spec.sdk_profile.max_transcript_bytes,
            )
            execution = HarnessExecutionResult(
                attempts=(
                    HarnessAttemptResult(
                        capture=capture,
                        runtime=HarnessRuntimeIdentityV2.model_validate(fact["runtime"]),
                        terminal_error=None,
                        provider_transcript=provider,
                    ),
                )
            )
            manifest, observation = _manifest(
                reservation,
                execution,
                datetime.fromisoformat(cast(str, fact["started_at"])),
                datetime.fromisoformat(cast(str, fact["completed_at"])),
                sha256_bytes(raw),
                None,
            )
            proposal = map_semantic_response(request, raw, spec.sdk_profile)
            response_type = _response_type(spec.sdk_profile)
            recovered = response_type(
                request_hash=request.content_hash,
                campaign_hash=request.campaign_hash,
                transport_ordinal=request.transport_ordinal,
                context_pack_hash=request.context_pack_hash,
                attempt_identity=request.attempt_identity,
                sdk_profile_hash=spec.sdk_profile.content_hash,
                reservation=reservation,
                manifest=manifest,
                normalized_transcript=normalized.decode("utf-8"),
                provider_transcript=provider.decode("utf-8"),
                raw_response=raw.decode("utf-8"),
                raw_response_hash=sha256_bytes(raw),
                proposal_json=proposal.canonical_bytes().decode("utf-8"),
                proposal_hash=proposal.content_hash,
            )
            verify_sdk_response(request, spec, recovered)
            with exclusive_directory_lock(directory):
                atomic_write_bytes(
                    directory / "agent-run-manifest.json", manifest.canonical_bytes()
                )
                atomic_write_bytes(
                    directory / "capability-observation.json", observation.canonical_bytes()
                )
                atomic_write_bytes(directory / "response.json", recovered.canonical_bytes())
        intent = strict_json_object(
            confined_regular_file(directory, "launch-intent.json").read_bytes(), max_bytes=16384
        )
        if intent.get("reservation_hash") != reservation.content_hash:
            raise ArtifactIntegrityError("SDK published launch origin differs")
        data = confined_regular_file(directory, "response.json").read_bytes()
        response = parse_sdk_response(data, max_bytes=request.max_response_bytes)
        verify_sdk_response(request, spec, response)
        for name, expected in (
            ("normalized-transcript.jsonl", response.normalized_transcript.encode("utf-8")),
            ("provider-transcript.jsonl", response.provider_transcript.encode("utf-8")),
            ("raw-response.txt", response.raw_response.encode("utf-8")),
            ("agent-run-manifest.json", response.manifest.canonical_bytes()),
        ):
            if confined_regular_file(directory, name).read_bytes() != expected:
                raise ArtifactIntegrityError("SDK retained original differs from response")
        return response

    def launch(
        self,
        request: SdkAgentRequest,
        spec: SdkCampaignSpec,
        *,
        harness: LocalAgentHarness | None = None,
    ) -> SdkAgentResponse:
        """One explicit launch; a retained intent is never automatically reissued."""
        reservation = self.prepare(request, spec)
        directory = self._directory(request)
        with exclusive_directory_lock(directory.parent), exclusive_directory_lock(directory):
            if (directory / "response.json").exists():
                return self.replay(request, spec)
            if (directory / "launch-intent.json").exists():
                raise ArtifactIntegrityError(
                    "SDK prior launch requires reconciliation; automatic reissue forbidden"
                )
            if harness is None and not (
                request.issued_at <= datetime.now(UTC) < request.expires_at
            ):
                raise ArtifactIntegrityError("SDK direct launch request is outside frozen TTL")
            launch_intents = tuple(directory.parent.glob("*/launch-intent.json"))
            if len(launch_intents) >= spec.sdk_profile.max_launches:
                raise ArtifactIntegrityError("SDK durable campaign launch allowance exhausted")
            cwd = _stable_directory(Path(spec.sdk_profile.cwd))
            if not cwd.is_absolute() or cwd.is_symlink() or not cwd.is_dir() or any(cwd.iterdir()):
                raise ArtifactIntegrityError("SDK cwd must be a frozen empty directory")
            if harness is None and (version("openai-codex"), version("openai-codex-cli-bin")) != (
                spec.sdk_profile.sdk_version,
                spec.sdk_profile.runtime_package_version,
            ):
                raise ArtifactIntegrityError(
                    "explicit accepted SDK interpreter/runtime installation required"
                )
            if harness is None:
                bundled_codex_path = cast(
                    Callable[[], str], import_module("codex_cli_bin").bundled_codex_path
                )
                from quantos.artifacts.store import sha256_file

                if sha256_file(Path(bundled_codex_path())) != spec.sdk_profile.runtime_binary_hash:
                    raise ArtifactIntegrityError(
                        "SDK bundled runtime binary differs from frozen profile"
                    )
            started = datetime.now(UTC)
            atomic_write_bytes(
                directory / "launch-intent.json",
                canonical_json_bytes(
                    {
                        "reservation_hash": reservation.content_hash,
                        "started_at": started.isoformat(),
                        "state": "UNKNOWN_UNTIL_CAPTURED",
                        "max_attempts": 1,
                    }
                ),
            )
            # Exceptions (including interrupts) leave the durable intent UNKNOWN.
            execution = (
                harness
                or CodexSdkAdapter(
                    runtime_candidate_id=spec.sdk_profile.runtime_candidate_id,
                    metadata_projection=True,
                )
            ).execute(reservation.execution_request)
            completed = datetime.now(UTC)
            process_exit_hash = _persist_sdk_process_exit(directory, execution)
            # Independent completed capture is retained before proposal parsing.
            from quantos.application.hosted_protocol import scan_protocol_artifact
            from quantos.integrations.codex.sdk_adapter import contains_parent_secret

            retained = (
                ("normalized-transcript.jsonl", execution.normalized_transcript),
                ("provider-transcript.jsonl", execution.provider_transcript or b""),
                (
                    "raw-response.txt",
                    (
                        execution.capture.agent_messages[-1]
                        if execution.capture.agent_messages
                        else ""
                    ).encode("utf-8"),
                ),
            )
            try:
                for _, payload in retained:
                    if contains_parent_secret(payload):
                        raise ValueError("SDK source contains forbidden parent value")
                    scan_protocol_artifact(payload.decode("utf-8"))
            except ValueError:
                atomic_write_bytes(
                    directory / "failure.json",
                    canonical_json_bytes(
                        {
                            "state": "FAILED",
                            "reason": "CAPTURE_REJECTED_BY_CREDENTIAL_GUARD",
                            "completed_at": completed.isoformat(),
                        }
                    ),
                )
                raise ArtifactIntegrityError(
                    "SDK unsafe capture rejected; bounded failure retained"
                ) from None
            for name, payload in retained:
                if isinstance(spec.sdk_profile, (SdkProducerProfileV2, SdkProducerProfileV3)):
                    cap = {
                        "normalized-transcript.jsonl": (
                            spec.sdk_profile.max_normalized_transcript_bytes
                        ),
                        "provider-transcript.jsonl": spec.sdk_profile.max_transcript_bytes,
                        "raw-response.txt": spec.sdk_profile.max_raw_response_bytes,
                    }[name]
                    if len(payload) > cap:
                        atomic_write_bytes(
                            directory / "failure.json",
                            canonical_json_bytes(
                                {
                                    "state": "FAILED",
                                    "reason": "SOURCE_CAPTURE_OVER_BOUND",
                                    "completed_at": completed.isoformat(),
                                    "source_file": name,
                                    "observed_bytes": len(payload),
                                    "source_hash": sha256_bytes(payload),
                                    "cap_bytes": cap,
                                }
                            ),
                        )
                        raise ArtifactIntegrityError("SDK capture exceeds frozen source bound")
            for name, payload in retained:
                atomic_write_bytes(directory / name, payload)
            observation_hash = _persist_sdk_observation(directory, execution)
            host_transport_hash = _persist_host_transport(directory, execution)
            capture_fact_bytes = canonical_json_bytes(
                {
                    "reservation_hash": reservation.content_hash,
                    "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(),
                    "runtime": execution.runtime.model_dump(mode="json")
                    if execution.runtime
                    else None,
                    "terminal_error": execution.terminal_error.model_dump(mode="json")
                    if execution.terminal_error
                    else None,
                    "observed_tool_calls": len(execution.capture.tool_calls),
                    "sdk_observation_hash": observation_hash,
                    **({"sdk_process_exit_hash": process_exit_hash} if process_exit_hash else {}),
                    **({"host_transport_hash": host_transport_hash} if host_transport_hash else {}),
                }
            )
            if contains_parent_secret(capture_fact_bytes):
                raise ArtifactIntegrityError("SDK capture metadata contains forbidden parent value")
            scan_protocol_artifact(capture_fact_bytes.decode("utf-8"))
            atomic_write_bytes(directory / "capture-fact.json", capture_fact_bytes)
            error = None
            raw = execution.capture.agent_messages[-1] if execution.capture.agent_messages else ""
            try:
                if (
                    execution.terminal_error is not None
                    or execution.capture.commands
                    or execution.capture.tool_calls
                    or execution.capture.approval_requested
                ):
                    raise ValueError("SDK transport/permission failure")
                proposal = map_semantic_response(request, raw.encode("utf-8"), spec.sdk_profile)
                manifest, observation = _manifest(
                    reservation,
                    execution,
                    started,
                    completed,
                    sha256_bytes(raw.encode("utf-8")),
                    None,
                )
                response_type = _response_type(spec.sdk_profile)
                response = response_type(
                    request_hash=request.content_hash,
                    campaign_hash=request.campaign_hash,
                    transport_ordinal=request.transport_ordinal,
                    context_pack_hash=request.context_pack_hash,
                    attempt_identity=request.attempt_identity,
                    sdk_profile_hash=spec.sdk_profile.content_hash,
                    reservation=reservation,
                    manifest=manifest,
                    normalized_transcript=execution.normalized_transcript.decode("utf-8"),
                    provider_transcript=(execution.provider_transcript or b"").decode("utf-8"),
                    raw_response=raw,
                    raw_response_hash=sha256_bytes(raw.encode("utf-8")),
                    proposal_json=proposal.canonical_bytes().decode("utf-8"),
                    proposal_hash=proposal.content_hash,
                )
                verify_sdk_response(request, spec, response)
                if len(response.canonical_bytes()) > request.max_response_bytes:
                    raise ValueError("SDK source response exceeds frozen transport cap")
            except (ValueError, TypeError, UnicodeError):
                error = "OUTPUT_INVALID"
                manifest, observation = _manifest(
                    reservation, execution, started, completed, None, error
                )
                response = None
            # Scan originals before persistence; never log failed sensitive values.
            scan_protocol_artifact(manifest.model_dump(mode="json"))
            scan_protocol_artifact(observation.model_dump(mode="json"))
            for name, payload in (
                ("agent-run-manifest.json", manifest.canonical_bytes()),
                ("capability-observation.json", observation.canonical_bytes()),
            ):
                atomic_write_bytes(directory / name, payload)
            if response is None:
                atomic_write_bytes(
                    directory / "failure.json",
                    canonical_json_bytes(
                        {
                            "state": "FAILED",
                            "manifest_hash": manifest.content_hash,
                            "reason": error,
                            "completed_at": completed.isoformat(),
                        }
                    ),
                )
                raise ArtifactIntegrityError(
                    "SDK failed; immutable failure retained; no automatic retry"
                )
            atomic_write_bytes(directory / "response.json", response.canonical_bytes())
            return response

    def step(
        self,
        service: object,
        campaign_hash: str,
        *,
        harness: LocalAgentHarness | None = None,
        expected_new_bytes: int | None = None,
    ) -> object:
        """Explicit bounded model step followed by existing submit/resume execution."""
        from quantos.application.hosted_campaign import HostedCampaignApplicationService

        if not isinstance(service, HostedCampaignApplicationService):
            raise TypeError("registered campaign application required")
        if harness is None:
            if expected_new_bytes is None:
                raise ArtifactIntegrityError(
                    "production SDK step requires complete storage growth reservation"
                )
            require_sdk_storage_reservation(
                (self.root, *service.execution_storage_roots(campaign_hash)), expected_new_bytes
            )
        request = service.pending(campaign_hash)
        if request is None:
            return service.resume(campaign_hash)
        spec = service.registered_spec(campaign_hash)
        if not isinstance(request, SdkAgentRequest) or not isinstance(spec, SdkCampaignSpec):
            raise ValueError("explicit SDK campaign profile required")
        # The protocol clock is authoritative; reconcile TTL/cancellation first.
        protocol_status = service.protocol.status(campaign_hash)
        if protocol_status.projected_expiration or protocol_status.state != "WAITING_FOR_AGENT":
            return service.resume(campaign_hash)
        response = self.launch(request, spec, harness=harness)
        receipt = service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")
        atomic_write_bytes(
            self._directory(request) / "submission-receipt.json", receipt.canonical_bytes()
        )
        return service.resume(campaign_hash)
