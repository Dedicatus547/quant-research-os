"""Explicit capture v3 successor; offline mocks grant no runtime qualification."""

import json
from dataclasses import replace

import pytest
from test_sdk_campaign_producer import _Harness
from test_sdk_campaign_producer import setup as sdk_setup  # noqa: F401
from test_sdk_capture_v2 import _FullStreamHarness

from quantos.application.hosted_protocol import HostedProtocolService, scan_protocol_artifact
from quantos.application.sdk_producer import (
    build_reservation,
    model_configuration,
    verify_sdk_response,
)
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedAgentRequest, HostedBudgetPolicy
from quantos.contracts.sdk_producer import (
    SdkAgentRequest,
    SdkAgentRequestV3,
    SdkAgentResponse,
    SdkAgentResponseV2,
    SdkAgentResponseV3,
    SdkCampaignSpec,
    SdkHostedBudgetPolicyV3,
    SdkProducerProfile,
    SdkProducerProfileV2,
    SdkProducerProfileV3,
    parse_agent_request,
    parse_campaign_spec,
    parse_sdk_response,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore


def _successor(setup_values, tmp_path):
    _service, old_spec, old_request, producer, _harness = setup_values
    profile = SdkProducerProfileV3.model_validate(
        {
            **old_spec.sdk_profile.model_dump(mode="json"),
            "schema_version": "sdk-producer-profile/v3",
            "max_transcript_bytes": 262144,
            "reasoning_summary": "none",
        }
    )
    profile = profile.model_copy(
        update={"requested_model_configuration_hash": sha256_bytes(model_configuration(profile))}
    )
    budget = SdkHostedBudgetPolicyV3.model_validate(
        {
            **old_spec.hosted_budget.model_dump(mode="json"),
            "schema_version": "sdk-hosted-budget-policy/v3",
            "max_response_bytes": 524288,
        }
    )
    spec = SdkCampaignSpec.model_validate(
        {
            **old_spec.model_dump(mode="json"),
            "requested_model_configuration_hash": profile.requested_model_configuration_hash,
            "sdk_profile": profile.model_dump(mode="json"),
            "hosted_budget": budget.model_dump(mode="json"),
        }
    )
    run_spec = old_request.business_request.agent_run_spec.model_copy(
        update={"requested_model_configuration_hash": profile.requested_model_configuration_hash}
    )
    business = old_request.business_request.model_copy(update={"agent_run_spec": run_spec})
    protocol = HostedProtocolService(
        HostedProtocolStore(tmp_path / "v3-protocol"),
        clock=lambda: old_request.issued_at,
        verify_inputs=lambda _spec: None,
    )
    protocol.register(spec)
    request = protocol.issue(
        spec.content_hash, business, projection_object_hashes=old_request.projection_object_hashes
    )
    return spec, request, producer, protocol


def _changed_original(response, field, value):
    digest = sha256_bytes(value.encode("utf-8"))
    key = {
        "provider_transcript": "provider_transcript_hash",
        "normalized_transcript": "normalized_transcript_hash",
        "raw_response": "output_proposal_hashes",
    }[field]
    updates = {key: (digest,) if field == "raw_response" else digest}
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
    return changed


def test_v3_publication_submit_replay_recovery_and_full_original(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    harness.size = 180000
    response = producer.launch(request, spec, harness=harness)
    assert type(request) is SdkAgentRequestV3
    assert type(response) is SdkAgentResponseV3
    assert 131072 < len(response.provider_transcript.encode()) <= 262144
    assert len(response.canonical_bytes()) <= request.max_response_bytes == 524288
    assert (
        json.loads(response.provider_transcript.splitlines()[1])["payload"]["delta"] == "x" * 180000
    )
    reservation = build_reservation(request, spec)
    assert reservation.execution_request.max_transcript_bytes == 262144
    assert reservation.execution_request.max_normalized_transcript_bytes == 65536
    assert reservation.run_spec.transcript_policy_hash == sha256_bytes(
        canonical_json_bytes({"max_bytes": 262144, "max_normalized_bytes": 65536})
    )
    assert parse_agent_request(request.canonical_bytes(), max_bytes=1048576) == request
    assert parse_campaign_spec(spec.canonical_bytes(), max_bytes=1048576) == spec
    assert parse_sdk_response(response.canonical_bytes(), max_bytes=524288) == response
    scan_protocol_artifact(spec.model_dump(mode="json"))
    scan_protocol_artifact(response.model_dump(mode="json"))
    assert (
        protocol.submit(request.content_hash, response.canonical_bytes(), "synthetic-sdk").outcome
        == "ACCEPTED"
    )
    assert protocol.accepted_exchange(request.content_hash)[1] == response
    assert producer.read_published(request, spec) == response
    assert producer.replay(request, spec) == response
    # Simulate an interrupted publication in this synthetic development fixture.
    directory = producer.root / request.campaign_hash / request.content_hash
    (directory / "response.json").unlink()
    assert producer.replay(request, spec) == response
    assert producer.launch(request, spec, harness=harness) == response
    assert harness.calls == 1


@pytest.mark.parametrize(
    "field,cap",
    [("provider_transcript", 262144), ("normalized_transcript", 65536), ("raw_response", 16384)],
)
def test_v3_utf8_byte_bounds_with_correct_hashes(sdk_setup, tmp_path, field, cap):  # noqa: F811
    spec, request, producer, _protocol = _successor(sdk_setup, tmp_path)
    response = producer.launch(request, spec, harness=_Harness(request, spec.sdk_profile))
    exact = "界" * (cap // 3) + "x" * (cap % 3)
    assert len(exact.encode()) == cap
    assert (
        getattr(SdkAgentResponseV3.model_validate(_changed_original(response, field, exact)), field)
        == exact
    )
    with pytest.raises(ValueError, match="explicit capture version bound"):
        SdkAgentResponseV3.model_validate(_changed_original(response, field, exact + "x"))
    with pytest.raises(ValueError):
        SdkAgentResponseV3.model_validate(_changed_original(response, field, "x" * (cap + 1)))


@pytest.mark.parametrize("over_field", ["provider", "normalized", "raw"])
def test_v3_retained_failure_and_no_reissue(sdk_setup, tmp_path, over_field):  # noqa: F811
    spec, request, producer, _protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    harness.size = 262145 if over_field == "provider" else 180000
    harness.over_field = over_field
    with pytest.raises(ArtifactIntegrityError):
        producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    assert (
        json.loads((directory / "failure.json").read_bytes())["reason"]
        == "SOURCE_CAPTURE_OVER_BOUND"
    )
    assert producer.status(request, spec) == "FAILED"
    assert all(
        not (directory / name).exists()
        for name in (
            "normalized-transcript.jsonl",
            "provider-transcript.jsonl",
            "raw-response.txt",
            "response.json",
        )
    )
    with pytest.raises(ArtifactIntegrityError):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1


def test_v3_secret_guard_before_publication(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, _protocol = _successor(sdk_setup, tmp_path)
    harness = _FullStreamHarness(request, spec.sdk_profile)
    harness.size, harness.secret = 180000, True
    with pytest.raises((ArtifactIntegrityError, ValueError)):
        producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    assert (
        json.loads((directory / "failure.json").read_bytes())["reason"]
        == "CAPTURE_REJECTED_BY_CREDENTIAL_GUARD"
    )
    assert not (directory / "response.json").exists()
    assert not (directory / "provider-transcript.jsonl").exists()
    assert harness.calls == 1


class _EscapedHarness(_Harness):
    def execute(self, request):
        result = super().execute(request)
        attempt = result.attempts[0]
        events = [json.loads(line) for line in attempt.provider_transcript.splitlines()]
        events.insert(1, {"method": "item/reasoning/textDelta", "payload": {"delta": ""}})
        base = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        events[1]["payload"]["delta"] = '"' * ((262144 - len(base)) // 2)
        provider = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        assert 262140 <= len(provider) <= 262144
        return replace(result, attempts=(replace(attempt, provider_transcript=provider),))


def test_v3_escaping_can_exceed_frame_bound_and_recovery_cannot_publish(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, protocol = _successor(sdk_setup, tmp_path)
    harness = _EscapedHarness(request, spec.sdk_profile)
    with pytest.raises(ArtifactIntegrityError, match="immutable failure"):
        producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    assert json.loads((directory / "failure.json").read_bytes())["reason"] == "OUTPUT_INVALID"
    assert len((directory / "provider-transcript.jsonl").read_bytes()) <= 262144
    assert not (directory / "response.json").exists()
    with pytest.raises(ValueError, match="transport cap"):
        producer.replay(request, spec)
    assert not (directory / "response.json").exists()
    receipt = protocol.submit(request.content_hash, b"x" * 524289, "synthetic-sdk")
    assert receipt.outcome == "REJECTED"
    assert receipt.reason == "FRAME_BYTE_CAP_EXCEEDED"
    assert harness.calls == 1


def test_v3_version_pairing_and_legacy_bounds(sdk_setup, tmp_path):  # noqa: F811
    spec, request, producer, protocol = _successor(sdk_setup, tmp_path)
    response = producer.launch(request, spec, harness=_Harness(request, spec.sdk_profile))
    for cls in (SdkAgentResponse, SdkAgentResponseV2):
        value = {
            **response.model_dump(mode="python"),
            "schema_version": cls.model_fields["schema_version"].default,
        }
        old = cls.model_validate(value)
        with pytest.raises(ValueError, match="version differs"):
            verify_sdk_response(request, spec, old)
        receipt = protocol.submit(request.content_hash, old.canonical_bytes(), "synthetic-sdk")
        assert receipt.outcome == "REJECTED"
    for schema in ("sdk-agent-response/v1", "sdk-agent-response/v2", "sdk-agent-response/v9"):
        changed = response.canonical_bytes().replace(b"sdk-agent-response/v3", schema.encode())
        if schema.endswith("v9"):
            with pytest.raises(ValueError):
                parse_sdk_response(changed, max_bytes=524288)
    legacy_spec = sdk_setup[1]
    for budget in (legacy_spec.hosted_budget, spec.hosted_budget):
        profile = (
            spec.sdk_profile if budget is legacy_spec.hosted_budget else legacy_spec.sdk_profile
        )
        with pytest.raises(ValueError, match="versions disagree"):
            SdkCampaignSpec.model_validate(
                {**spec.model_dump(mode="python"), "hosted_budget": budget, "sdk_profile": profile}
            )
    for cls, schema in (
        (HostedAgentRequest, "hosted-agent-request/v1"),
        (SdkAgentRequest, "sdk-agent-request/v1"),
    ):
        value = {**request.model_dump(mode="json"), "schema_version": schema}
        if cls is HostedAgentRequest:
            value.pop("sdk_profile_hash")
            value["profile"] = "hm-mvp/v1"
        with pytest.raises(ValueError):
            cls.model_validate(value)
    with pytest.raises(ValueError):
        HostedBudgetPolicy.model_validate(
            {**legacy_spec.hosted_budget.model_dump(mode="json"), "max_response_bytes": 524288}
        )
    for field, values in (
        ("max_transcript_bytes", (131072, 262143, 262145)),
        ("max_normalized_transcript_bytes", (65535, 65537)),
        ("reasoning_summary", (None, "brief")),
        ("max_raw_response_bytes", (16385,)),
    ):
        for value in values:
            with pytest.raises(ValueError):
                SdkProducerProfileV3.model_validate(
                    {**spec.sdk_profile.model_dump(mode="python"), field: value}
                )
    for cls in (SdkProducerProfile, SdkProducerProfileV2):
        with pytest.raises(ValueError):
            cls.model_validate(
                {
                    **spec.sdk_profile.model_dump(mode="json"),
                    "schema_version": cls.model_fields["schema_version"].default,
                }
            )


@pytest.mark.parametrize(
    "cls,expected",
    [
        (SdkAgentRequest, "bc90a52ebf6eccac9c8cc6f81c71df8d41757219d6a7f1b3f62def825ef41e4d"),
        (SdkAgentResponse, "3e53a977ae805281a6c5694b4afac3333417da1caf3fa37152d11f9e0b94256e"),
        (SdkAgentResponseV2, "cef686025effd7ae792c5b147d39afc0d876b4769f55d58791c0c579da680932"),
        (SdkProducerProfile, "ce5351fa8f63884fb6d8d4d1710c72f4c73f6ec307a90ef58aca5abc212af80c"),
        (SdkProducerProfileV2, "92b56286e2b1eb1a7195175cf20c8be866771ff1570c55bf89d39a3f3a4657ec"),
    ],
)
def test_legacy_schemas_remain_byte_identical(cls, expected):
    schema = json.dumps(cls.model_json_schema(), sort_keys=True, separators=(",", ":")).encode()
    assert sha256_bytes(schema) == expected


def test_v3_namespace_frozen_tuple_and_cli_parse_are_offline(sdk_setup, tmp_path):  # noqa: F811
    import argparse

    from scripts.sdk_campaign import _inputs
    from scripts.sdk_science_namespace import frozen_tuple

    from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration

    spec, request, _producer, _protocol = _successor(sdk_setup, tmp_path)
    config = HostedBusinessLoaderConfiguration(
        business_inputs_hash="a" * 64,
        input_root=str(tmp_path / "inputs"),
        business_root=str(tmp_path / "business"),
        provenance_workspace=str(tmp_path),
    )
    tuple_spec = SdkCampaignSpec.model_validate(
        {
            **spec.model_dump(mode="python"),
            "sdk_profile": spec.sdk_profile.model_copy(update={"max_launches": 2}),
            "hosted_budget": spec.hosted_budget.model_copy(update={"max_requests": 2}),
        }
    )
    (tmp_path / "loader-config.json").write_bytes(config.canonical_bytes())
    (tmp_path / "sdk-campaign-spec.json").write_bytes(tuple_spec.canonical_bytes())
    args = argparse.Namespace(
        metadata_root=tmp_path,
        workspace=tmp_path,
        expected_config_hash=config.content_hash,
        expected_spec_hash=tuple_spec.content_hash,
    )
    assert frozen_tuple(args) == (config, tuple_spec)
    args.expected_spec_hash = "0" * 64
    with pytest.raises(ValueError, match="dependency hash differs"):
        frozen_tuple(args)
    (tmp_path / "request.json").write_bytes(request.canonical_bytes())
    (tmp_path / "spec.json").write_bytes(spec.canonical_bytes())
    assert _inputs(
        argparse.Namespace(
            request=str(tmp_path / "request.json"),
            request_sha256=request.content_hash,
            spec=str(tmp_path / "spec.json"),
            spec_sha256=spec.content_hash,
        )
    ) == (request, spec)


def test_v3_adapter_full_provider_over_128k_is_not_truncated(tmp_path, monkeypatch):
    import subprocess

    from test_codex_sdk_adapter import _request, _response

    from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter

    body = json.loads(_response())
    body["provider_events"].insert(
        1, {"method": "item/reasoning/textDelta", "payload": {"delta": "x" * 180000}}
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
        update={"max_transcript_bytes": 262144, "max_normalized_transcript_bytes": 65536}
    )
    result = CodexSdkAdapter(authentication_home=tmp_path).execute(request)
    assert result.terminal_error is None
    assert len(result.normalized_transcript) <= 65536
    assert 131072 < len(result.provider_transcript) <= 262144
    assert result.provider_transcript.count(b"x") >= 180000


@pytest.mark.parametrize("changed_allowance", [False, True])
def test_v3_loader_projects_only_explicit_frame_delta_from_verified_bundle(
    sdk_setup,  # noqa: F811
    tmp_path,
    monkeypatch,
    changed_allowance,
):
    from types import SimpleNamespace

    from quantos.application import hosted_inputs as loader
    from quantos.contracts.hosted import HostedCampaignSpec
    from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration

    spec, _request, _producer, protocol = _successor(sdk_setup, tmp_path)
    old_budget = sdk_setup[1].hosted_budget
    expected_values = spec.model_dump(mode="python")
    expected_values.pop("sdk_profile")
    expected_values.update(
        schema_version="hosted-campaign-spec/v1", profile="hm-mvp/v1", hosted_budget=old_budget
    )
    expected = HostedCampaignSpec.model_validate(expected_values)
    if changed_allowance:
        spec = SdkCampaignSpec.model_validate(
            {
                **spec.model_dump(mode="python"),
                "hosted_budget": spec.hosted_budget.model_copy(
                    update={"max_unique_submissions": spec.hosted_budget.max_unique_submissions + 1}
                ),
            }
        )
    fixture_bytes = b'{"offline_mock_bundle":true}'
    config = HostedBusinessLoaderConfiguration(
        business_inputs_hash=sha256_bytes(fixture_bytes),
        input_root=str(tmp_path / "inputs"),
        business_root=str(tmp_path / "business"),
        provenance_workspace=str(tmp_path),
    )
    item = SimpleNamespace(logical_path="synthetic-seed")
    bundle = SimpleNamespace(
        campaign=spec.campaign,
        initial_ledger_directory="seed",
        initial_ledger_files=(item,),
    )
    checked = []
    monkeypatch.setattr(loader, "_read_file", lambda *_args, **_kwargs: fixture_bytes)
    monkeypatch.setattr(loader, "parse_hosted_contract", lambda *_args, **_kwargs: bundle)
    monkeypatch.setattr(loader, "_verify_bundle", lambda *args, **kwargs: checked.append(kwargs))
    monkeypatch.setattr(loader, "derive_hosted_campaign_spec", lambda *_args, **_kwargs: expected)
    monkeypatch.setattr(loader, "_verify_file", lambda *_args: b"synthetic-seed")

    class ReachedSeedPublication(Exception):
        pass

    def stop_before_seed(*_args):
        raise ReachedSeedPublication

    monkeypatch.setattr(loader, "_publish_seed_file", stop_before_seed)
    error = ArtifactIntegrityError if changed_allowance else ReachedSeedPublication
    with pytest.raises(error):
        loader.load_hosted_campaign_application(
            config, protocol, tmp_path / "locks", deployment_profile_hash="a" * 64, sdk_spec=spec
        )
    assert checked == [{"sdk": True}]
