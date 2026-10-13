"""Explicit 128 KiB capture successor; synthetic SDK/producer only."""

import json
import subprocess
from dataclasses import replace

import pytest
from test_codex_sdk_adapter import _request, _response
from test_sdk_campaign_producer import _Harness
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401

from quantos.application.hosted_protocol import HostedProtocolService, scan_protocol_artifact
from quantos.application.sdk_producer import (
    build_reservation,
    model_configuration,
    verify_sdk_response,
)
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.sdk_producer import (
    SdkAgentRequest,
    SdkAgentResponse,
    SdkAgentResponseV2,
    SdkCampaignSpec,
    SdkProducerProfile,
    SdkProducerProfileV2,
    parse_sdk_response,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter


def _successor(setup_values, tmp_path):
    _old_service, old_spec, old_request, producer, _old_harness = setup_values
    profile = SdkProducerProfileV2.model_validate(
        {
            **old_spec.sdk_profile.model_dump(mode="json"),
            "schema_version": "sdk-producer-profile/v2",
            "max_transcript_bytes": 131072,
            "reasoning_summary": "none",
        }
    )
    profile = profile.model_copy(
        update={"requested_model_configuration_hash": sha256_bytes(model_configuration(profile))}
    )
    spec = SdkCampaignSpec.model_validate(
        {
            **old_spec.model_dump(mode="json"),
            "requested_model_configuration_hash": profile.requested_model_configuration_hash,
            "sdk_profile": profile.model_dump(mode="json"),
        }
    )
    run_spec = old_request.business_request.agent_run_spec.model_copy(
        update={"requested_model_configuration_hash": profile.requested_model_configuration_hash}
    )
    business = old_request.business_request.model_copy(update={"agent_run_spec": run_spec})
    protocol = HostedProtocolService(
        HostedProtocolStore(tmp_path / "v2-protocol"),
        clock=lambda: old_request.issued_at,
        verify_inputs=lambda _spec: None,
    )
    protocol.register(spec)
    request = protocol.issue(
        spec.content_hash, business, projection_object_hashes=old_request.projection_object_hashes
    )
    assert isinstance(request, SdkAgentRequest)
    return spec, request, producer, protocol


class _FullStreamHarness(_Harness):
    size = 90000
    secret = False
    over_field = None

    def execute(self, request):
        result = super().execute(request)
        attempt = result.attempts[0]
        events = [json.loads(line) for line in attempt.provider_transcript.splitlines()]
        payload = {"delta": "x" * self.size}
        if self.secret:
            payload["api_key"] = "synthetic-key-never-a-real-credential"
        events.insert(1, {"method": "item/reasoning/textDelta", "payload": payload})
        provider = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        if self.over_field == "normalized":
            attempt = replace(attempt, capture=replace(attempt.capture, transcript=b"x" * 65537))
        elif self.over_field == "raw":
            attempt = replace(
                attempt, capture=replace(attempt.capture, agent_messages=("x" * 16385,))
            )
        return replace(result, attempts=(replace(attempt, provider_transcript=provider),))


def test_v2_full_stream_source_publication_submit_replay_and_version(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    response = producer.launch(request, spec, harness=harness)
    assert type(response) is SdkAgentResponseV2
    assert 65536 < len(response.provider_transcript.encode()) <= 131072
    assert len(response.canonical_bytes()) <= request.max_response_bytes == 262144
    assert (
        json.loads(response.provider_transcript.splitlines()[1])["payload"]["delta"]
        == "x" * harness.size
    )
    reservation = build_reservation(request, spec)
    assert reservation.execution_request.max_transcript_bytes == 131072
    assert reservation.execution_request.max_normalized_transcript_bytes == 65536
    assert reservation.run_spec.transcript_policy_hash == sha256_bytes(
        canonical_json_bytes({"max_bytes": 131072, "max_normalized_bytes": 65536})
    )
    assert len(response.normalized_transcript.encode()) <= 65536
    scan_protocol_artifact(spec.model_dump(mode="json"))
    scan_protocol_artifact(response.model_dump(mode="json"))
    assert (
        protocol.submit(request.content_hash, response.canonical_bytes(), "synthetic-sdk").outcome
        == "ACCEPTED"
    )
    assert protocol.accepted_exchange(request.content_hash)[1] == response
    assert producer.read_published(request, spec) == response
    assert producer.replay(request, spec) == response
    assert producer.launch(request, spec, harness=harness) == response
    assert harness.calls == 1
    with pytest.raises(ValueError, match="version differs"):
        verify_sdk_response(
            request,
            spec,
            SdkAgentResponse.model_construct(
                **{**response.model_dump(mode="python"), "schema_version": "sdk-agent-response/v1"}
            ),
        )
    with pytest.raises(ValueError):
        parse_sdk_response(
            response.canonical_bytes().replace(b"sdk-agent-response/v2", b"sdk-agent-response/v9"),
            max_bytes=262144,
        )
    for field, value in [
        ("provider_transcript", "x" * 131073),
        ("normalized_transcript", "x" * 65537),
        ("raw_response", "x" * 16385),
    ]:
        with pytest.raises(ValueError):
            SdkAgentResponseV2.model_validate({**response.model_dump(mode="python"), field: value})
    # Correct every original hash, so these UTF-8 boundaries cannot pass merely
    # because a changed payload disagrees with an old manifest hash.
    for field, value, manifest_key in (
        ("provider_transcript", "界" * 44000, "provider_transcript_hash"),
        ("normalized_transcript", "界" * 22000, "normalized_transcript_hash"),
        ("raw_response", "界" * 5500, "output_proposal_hashes"),
    ):
        digest = sha256_bytes(value.encode())
        updates = {manifest_key: (digest,) if field == "raw_response" else digest}
        if field == "raw_response":
            updates["attempts"] = tuple(
                attempt.model_copy(update={"produced_proposal_hash": digest})
                for attempt in response.manifest.attempts
            )
        changed = {
            **response.model_dump(mode="python"),
            field: value,
            "manifest": response.manifest.model_copy(update=updates),
        }
        if field == "raw_response":
            changed["raw_response_hash"] = digest
        with pytest.raises(ValueError, match="explicit capture version bound"):
            SdkAgentResponseV2.model_validate(changed)
    with pytest.raises(ValueError):
        SdkAgentResponse.model_validate(
            {**response.model_dump(mode="python"), "schema_version": "sdk-agent-response/v1"}
        )


def test_v1_exact_bytes_caps_and_explicit_discriminator(sdk_setup, tmp_path):  # noqa: F811
    _service, spec, request, _producer, _harness = sdk_setup
    legacy = spec.sdk_profile
    assert legacy.schema_version == "sdk-producer-profile/v1"
    assert legacy.canonical_bytes() == canonical_json_bytes(legacy.model_dump(mode="json"))
    for schema in ["sdk-producer-profile/v1", "sdk-producer-profile/v9"]:
        with pytest.raises(ValueError):
            SdkCampaignSpec.model_validate(
                {
                    **spec.model_dump(mode="json"),
                    "sdk_profile": {
                        **legacy.model_dump(mode="json"),
                        "schema_version": schema,
                        "max_transcript_bytes": 131072,
                    },
                }
            )
    for cap in [65536, 131071, 131073, 262144]:
        with pytest.raises(ValueError):
            SdkProducerProfileV2.model_validate(
                {
                    **legacy.model_dump(mode="json"),
                    "schema_version": "sdk-producer-profile/v2",
                    "max_transcript_bytes": cap,
                }
            )
    with pytest.raises(ValueError):
        SdkProducerProfile.model_validate(
            {**legacy.model_dump(mode="json"), "max_transcript_bytes": 131072}
        )
    forged = spec.model_copy(
        update={"sdk_profile": legacy.model_copy(update={"max_transcript_bytes": 131072})}
    )
    with pytest.raises(ValueError):
        build_reservation(request, forged)
    assert request.sdk_profile_hash == legacy.content_hash
    assert "max_normalized_transcript_bytes" not in build_reservation(
        request, spec
    ).execution_request.model_dump(mode="json")


@pytest.mark.parametrize("over_field", ["provider", "normalized", "raw"])
def test_v2_over_bound_are_retained_failures(sdk_setup, tmp_path, over_field):  # noqa: F811
    spec, request, producer, _protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    harness.size = 131073 if over_field == "provider" else 90000
    harness.over_field = over_field
    with pytest.raises(ArtifactIntegrityError):
        producer.launch(request, spec, harness=harness)
    assert producer.status(request, spec) == "FAILED"
    directory = producer.root / request.campaign_hash / request.content_hash
    assert (
        json.loads((directory / "failure.json").read_bytes())["reason"]
        == "SOURCE_CAPTURE_OVER_BOUND"
    )
    for name in ("normalized-transcript.jsonl", "provider-transcript.jsonl", "raw-response.txt"):
        assert not (directory / name).exists()
    with pytest.raises(ArtifactIntegrityError):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1


def test_v2_secret_guard_before_publication(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, _protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    harness.secret = True
    with pytest.raises((ArtifactIntegrityError, ValueError)):
        producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    assert not (directory / "response.json").exists()
    assert not (directory / "provider-transcript.jsonl").exists()
    assert harness.calls == 1


@pytest.mark.parametrize("normalized_over", [False, True])
def test_adapter_separate_provider_and_normalized_bounds(tmp_path, monkeypatch, normalized_over):
    body = json.loads(_response())
    if normalized_over:
        body["provider_events"][1]["payload"]["item"]["text"] = "z" * 70000
    else:
        body["provider_events"].insert(
            1, {"method": "item/reasoning/textDelta", "payload": {"delta": "x" * 90000}}
        )
    stdout = canonical_json_bytes(body)

    class FakeProcess:
        returncode = 0
        pid = 123

        def __init__(self, *_args, **_kwargs):
            pass

        def communicate(self, _payload, timeout):
            return stdout, b""

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    request = _request(tmp_path).model_copy(
        update={"max_transcript_bytes": 131072, "max_normalized_transcript_bytes": 65536}
    )
    result = CodexSdkAdapter(authentication_home=tmp_path).execute(request)
    assert len(result.normalized_transcript) <= 65536
    assert 65536 < len(result.provider_transcript) <= 131072
    assert (result.terminal_error is not None) is normalized_over
    if not normalized_over:
        assert result.provider_transcript.count(b"x") >= 90000
