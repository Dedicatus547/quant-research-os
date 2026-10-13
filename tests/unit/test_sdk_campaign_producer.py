"""Targeted offline SDK producer integration; fake captures grant no qualification."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_campaign import _service, _spec

from quantos.application.agent_harness import (
    HarnessAttemptResult,
    HarnessExecutionResult,
    capture_from_agent_events,
)
from quantos.application.sdk_producer import (
    SdkCampaignProducer,
    map_semantic_response,
    model_configuration,
    semantic_schema,
    verify_sdk_response,
)
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.autonomous import SDK_BOUNDED_FINALIZATION_PROFILE
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import HarnessRuntimeIdentityV2
from quantos.contracts.hosted import HostedCampaignReport
from quantos.contracts.sdk_producer import (
    SdkAgentExchange,
    SdkAgentRequest,
    SdkCampaignSpec,
    SdkProducerProfile,
)
from quantos.integrations.codex.event_normalizer import normalize_provider_events


class _Harness:
    calls = 0
    crash = False
    invalid = False
    stop = True
    candidate_index = 0

    def __init__(self, request: SdkAgentRequest, profile: SdkProducerProfile) -> None:
        self.request, self.profile = request, profile

    def execute(self, request):
        self.calls += 1
        assert request.max_attempts == 1
        if self.crash:
            raise RuntimeError("offline simulated interrupted launch")
        raw = json.dumps(
            {
                "schema_version": "sdk-candidate-reference/v1",
                "candidate_ref": self.request.business_request.candidate_options[
                    self.candidate_index
                ].candidate_id
                if not self.invalid
                else "candidate-" + "0" * 64,
                "rationale": "Frozen evidence suggests testing this candidate.",
                "request_stop": self.stop,
            },
            indent=2,
        )
        provider = (
            {
                "method": "turn/started",
                "payload": {
                    "thread_id": "thread-sdk",
                    "turn": {"id": "turn-sdk", "status": "inProgress", "error": None},
                },
            },
            {
                "method": "item/completed",
                "payload": {"item": {"type": "agentMessage", "phase": "final_answer", "text": raw}},
            },
            {
                "method": "thread/tokenUsage/updated",
                "payload": {
                    "token_usage": {
                        "last": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2}
                    }
                },
            },
            {
                "method": "turn/completed",
                "payload": {
                    "thread_id": "thread-sdk",
                    "turn": {"id": "turn-sdk", "status": "completed", "error": None},
                },
            },
        )
        capture = capture_from_agent_events(
            normalize_provider_events(provider, thread_id="thread-sdk"),
            max_bytes=self.profile.max_transcript_bytes,
        )
        return HarnessExecutionResult(
            attempts=(
                HarnessAttemptResult(
                    capture=capture,
                    runtime=HarnessRuntimeIdentityV2(
                        sdk_version="0.162.1",
                        runtime_package_version="0.162.1",
                        runtime_version="0.162.1",
                        runtime_binary_hash=self.profile.runtime_binary_hash,
                    ),
                    terminal_error=None,
                    provider_transcript=b"".join(canonical_json_bytes(x) + b"\n" for x in provider),
                ),
            )
        )


@pytest.fixture
def setup(tmp_path):
    inputs = _inputs(tmp_path / "inputs", allow_manual_stop=True)
    cwd = tmp_path / "empty-cwd"
    cwd.mkdir()
    root = (
        Path(__file__).resolve().parents[2]
        / "artifacts/next-stage-offline-20261012/a/scenarios"
        / uuid4().hex
    )
    profile = SdkProducerProfile(
        runtime_binary_hash="a" * 64,
        cwd=str(cwd),
        evidence_root=str(root),
        max_launches=3,
        timeout_seconds=30,
        max_input_tokens=1000,
        max_output_tokens=1000,
        max_transcript_bytes=65536,
        max_raw_response_bytes=16384,
        requested_model_configuration_hash="b" * 64,
        skill_hash=inputs.agent_policy.skill_hash,
        instruction_hashes=inputs.agent_policy.instruction_hashes,
    )
    configuration_hash = sha256_bytes(model_configuration(profile))
    profile = profile.model_copy(update={"requested_model_configuration_hash": configuration_hash})
    inputs.agent_policy = inputs.agent_policy.model_copy(
        update={
            "requested_model_configuration_hash": configuration_hash,
            "harness_identifier": "openai-codex-python-sdk",
            "provider_model_identifier": profile.model,
            "model_snapshot_immutable": False,
        }
    )
    inputs.campaign_policy = inputs.campaign_policy.model_copy(
        update={"context_query": "alpha execution_failed"}
    )
    base = _spec(inputs).model_dump(mode="json")
    base.update(
        schema_version="sdk-campaign-spec/v1",
        profile="sdk-bounded/v1",
        sdk_profile=profile.model_dump(mode="json"),
        selection_finalization_profile_hash=SDK_BOUNDED_FINALIZATION_PROFILE.content_hash,
    )
    spec = SdkCampaignSpec.model_validate(base)
    service = _service(
        tmp_path / "business", inputs, spec, selection_profile=SDK_BOUNDED_FINALIZATION_PROFILE
    )
    service.start(spec.content_hash)
    request = service.pending(spec.campaign_hash)
    assert isinstance(request, SdkAgentRequest)

    producer = SdkCampaignProducer(root)
    return service, spec, request, producer, _Harness(request, profile)


def test_raw_mapping_submit_replay_and_terminal_feedback(setup):
    service, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    assert response.raw_response_hash != response.proposal_hash
    assert response.manifest.schema_version == "agent-run-manifest/v3"
    assert response.manifest.aggregate_usage.input_tokens == 10
    verify_sdk_response(request, spec, response)
    assert producer.replay(request, spec) == response
    assert producer.launch(request, spec, harness=harness) == response
    assert harness.calls == 1
    receipt = service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")
    assert receipt.outcome == "ACCEPTED"
    assert (
        service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer") == receipt
    )
    exchange = service.protocol.accepted_exchange(request.content_hash)
    assert exchange is not None and isinstance(exchange[2], SdkAgentExchange)
    service.resume(spec.campaign_hash)
    assert producer.status(request, spec) == "CAPTURED"
    assert service.status(spec.campaign_hash).state == "EXHAUSTED"


def test_unknown_launch_never_reissues(setup):
    _, spec, request, producer, harness = setup
    harness.crash = True
    with pytest.raises(RuntimeError, match="interrupted"):
        producer.launch(request, spec, harness=harness)
    assert producer.status(request, spec) == "UNKNOWN"
    with pytest.raises(ArtifactIntegrityError, match="reissue forbidden"):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1


def test_invalid_semantic_candidate_failure_retains_usage_and_no_reissue(setup):
    _, spec, request, producer, harness = setup
    harness.invalid = True
    with pytest.raises(ArtifactIntegrityError, match="immutable failure"):
        producer.launch(request, spec, harness=harness)
    assert producer.status(request, spec) == "FAILED"
    directory = producer.root / request.campaign_hash / request.content_hash
    manifest = json.loads((directory / "agent-run-manifest.json").read_bytes())
    assert manifest["run_status"] == "FAILED"
    assert manifest["aggregate_usage"]["input_tokens"] == 10
    with pytest.raises(ArtifactIntegrityError, match="reissue forbidden"):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1


@pytest.mark.parametrize("defect", ["proposal", "runtime", "usage", "raw", "reservation"])
def test_tampered_source_rejected_without_new_call(setup, defect):
    service, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    if defect == "proposal":
        response = response.model_copy(
            update={
                "proposal_json": response.proposal_json.replace("Frozen", "Altered"),
                "proposal_hash": sha256_bytes(
                    response.proposal_json.replace("Frozen", "Altered").encode()
                ),
            }
        )
    elif defect == "runtime":
        response = response.model_copy(
            update={
                "manifest": response.manifest.model_copy(update={"runtime_binary_hash": "0" * 64})
            }
        )
    elif defect == "usage":
        response = response.model_copy(
            update={
                "manifest": response.manifest.model_copy(
                    update={
                        "aggregate_usage": response.manifest.aggregate_usage.model_copy(
                            update={"input_tokens": 99}
                        )
                    }
                )
            }
        )
    elif defect == "raw":
        response = response.model_copy(
            update={
                "raw_response": response.raw_response + " ",
                "raw_response_hash": sha256_bytes((response.raw_response + " ").encode()),
            }
        )
    else:
        response = response.model_copy(
            update={
                "reservation": response.reservation.model_copy(
                    update={
                        "execution_request": response.reservation.execution_request.model_copy(
                            update={"max_attempts": 2}
                        )
                    }
                )
            }
        )
    assert (
        service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer").outcome
        == "REJECTED"
    )
    assert harness.calls == 1


def test_duplicate_key_and_unknown_ref_rejected(setup):
    _, spec, request, _, _ = setup
    with pytest.raises(ValueError):
        map_semantic_response(
            request, b'{"candidate_ref":"a","candidate_ref":"b"}', spec.sdk_profile
        )
    raw = canonical_json_bytes(
        {
            "schema_version": "sdk-candidate-reference/v1",
            "candidate_ref": "candidate-" + "0" * 64,
            "rationale": "test",
            "request_stop": False,
        }
    )
    with pytest.raises(ValueError, match="unknown"):
        map_semantic_response(request, raw, spec.sdk_profile)


def test_completed_capture_before_response_recovered_without_new_call(setup):
    _, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    (directory / "response.json").rename(directory / "original-response-retained.json")
    assert producer.status(request, spec) == "UNKNOWN"
    assert producer.replay(request, spec) == response
    assert harness.calls == 1


def test_frozen_evidence_root_prevents_relaunch_through_new_root(setup):
    _, spec, request, producer, harness = setup
    with pytest.raises(ArtifactIntegrityError, match="root differs"):
        SdkCampaignProducer(producer.root.parent / uuid4().hex).prepare(request, spec)
    assert harness.calls == 0


def test_full_step_reuses_existing_receipt_and_reports_sdk_limits(setup):
    service, spec, _request, producer, harness = setup
    status = producer.step(service, spec.campaign_hash, harness=harness)
    assert status.state == "EXHAUSTED"
    assert harness.calls == 1
    assert producer.step(service, spec.campaign_hash, harness=harness) == status
    assert harness.calls == 1
    report = service.protocol.store.snapshot(spec.campaign_hash).artifact(
        status.report_hash,
        HostedCampaignReport,
    )
    assert "SDK_CAMPAIGN_LIVE_QUALIFICATION_NOT_GRANTED" in report.limitations
    assert "HOST_INTERNAL_USAGE_UNAVAILABLE" not in report.limitations


def test_two_sdk_steps_consume_new_context_and_persist_synthetic_example(setup):
    import shutil

    from quantos.artifacts.store import atomic_write_bytes

    service, spec, request, producer, harness = setup
    harness.stop = False
    first = producer.step(service, spec.campaign_hash, harness=harness)
    assert first.state == "WAITING_FOR_AGENT"
    second_request = service.pending(spec.campaign_hash)
    assert isinstance(second_request, SdkAgentRequest)
    assert second_request.context_pack_hash != request.context_pack_hash
    assert (
        second_request.business_request.context_pack.ledger_snapshot_hash
        != request.business_request.context_pack.ledger_snapshot_hash
    )
    assert (
        second_request.business_request.candidate_options
        == request.business_request.candidate_options
    )
    first_candidate_hash = request.business_request.candidate_options[0].content_hash
    prior_trials = [
        item
        for item in second_request.business_request.context_pack.items
        if item.node_kind.value == "CAMPAIGN_TRIAL"
    ]
    assert prior_trials and any(
        "EXECUTION_FAILED" in item.content and first_candidate_hash in item.content
        for item in prior_trials
    )
    assert all(
        item.event_hash
        not in {old.event_hash for old in request.business_request.context_pack.items}
        for item in prior_trials
    )
    harness.request = second_request
    harness.candidate_index = 1
    harness.stop = True
    terminal = producer.step(service, spec.campaign_hash, harness=harness)
    assert terminal.state in ("COMPLETED", "EXHAUSTED")
    assert harness.calls == 2
    first_source = producer.replay(request, spec)
    second_source = producer.replay(second_request, spec)
    assert (
        json.loads(first_source.proposal_json)["candidate_hash"]
        != json.loads(second_source.proposal_json)["candidate_hash"]
    )
    assert first_source.raw_response_hash != second_source.raw_response_hash
    assert service.resume(spec.campaign_hash) == terminal
    assert harness.calls == 2
    example = producer.root.parents[1] / "example" / producer.root.name
    shutil.copytree(producer.root, example / "producer-originals")
    snapshot = service.protocol.store.snapshot(spec.campaign_hash)
    for digest, encoded in snapshot.artifacts.items():
        atomic_write_bytes(example / "protocol-artifacts" / f"{digest}.json", encoded)
    atomic_write_bytes(example / "status.json", terminal.canonical_bytes())
    atomic_write_bytes(
        example / "example.json",
        canonical_json_bytes(
            {
                "authority": "SYNTHETIC_OFFLINE_EXAMPLE_NOT_QUALIFICATION",
                "actual_model_calls": 0,
                "fake_harness_calls": harness.calls,
                "campaign_hash": spec.campaign_hash,
                "sdk_profile_hash": spec.sdk_profile.content_hash,
                "originating_producer_root": str(producer.root),
                "request_hashes": [request.content_hash, second_request.content_hash],
                "report_hash": terminal.report_hash,
                "artifact_hashes": sorted(snapshot.artifacts),
            }
        ),
    )


@pytest.mark.parametrize(
    "field",
    [
        "campaign_hash",
        "candidate_manifest_hash",
        "input_hashes",
        "max_response_bytes",
        "attempt_identity",
        "expires_at",
    ],
)
def test_forged_request_cannot_fork_launch_reservation(setup, field):
    from datetime import timedelta

    service, spec, request, producer, harness = setup
    values = {
        "campaign_hash": "0" * 64,
        "candidate_manifest_hash": "0" * 64,
        "input_hashes": (),
        "max_response_bytes": 1024,
        "attempt_identity": "0" * 64,
        "expires_at": request.expires_at + timedelta(seconds=1),
    }
    forged = request.model_copy(update={field: values[field]})
    with pytest.raises(ArtifactIntegrityError, match="frozen profile"):
        producer.prepare(forged, spec)
    assert harness.calls == 0
    assert not producer.root.exists()
    assert service.pending(spec.campaign_hash) == request


def test_expired_production_launch_rejects_before_runtime_or_launch_intent(setup):
    _, spec, request, producer, harness = setup
    with pytest.raises(ArtifactIntegrityError, match="outside frozen TTL"):
        producer.launch(request, spec)
    assert harness.calls == 0
    assert producer.status(request, spec) == "PREPARED"
    assert not (
        producer.root / request.campaign_hash / request.content_hash / "launch-intent.json"
    ).exists()


def test_self_consistent_sdk_envelope_without_source_publication_is_rejected(setup):
    service, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    verify_sdk_response(request, spec, response)
    directory = producer.root / request.campaign_hash / request.content_hash
    directory.rename(directory.parent / "source-retained-but-unpublished")
    receipt = service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")
    assert receipt.outcome == "REJECTED"
    assert receipt.reason == "SDK_SOURCE_UNAVAILABLE"
    assert service.status(spec.campaign_hash).protocol.used_unique_submissions == 1
    assert service.pending(spec.campaign_hash) == request
    assert harness.calls == 1
    assert not directory.exists()


def test_accepted_sdk_replay_requires_retained_producer_originals(setup):
    service, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    receipt = service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")
    assert receipt.outcome == "ACCEPTED"
    directory = producer.root / request.campaign_hash / request.content_hash
    (directory / "raw-response.txt").rename(directory / "original-raw-response-retained.txt")
    with pytest.raises(ArtifactIntegrityError, match="source publication unavailable"):
        service.protocol.accepted_exchange(request.content_hash)
    assert harness.calls == 1
    assert receipt.outcome == "ACCEPTED"


def test_protocol_source_check_cannot_repair_missing_response(setup):
    service, spec, request, producer, harness = setup
    response = producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    (directory / "response.json").rename(directory / "original-response-retained.json")
    receipt = service.submit(request.content_hash, response.canonical_bytes(), "sdk-producer")
    assert receipt.outcome == "REJECTED"
    assert receipt.reason == "SDK_SOURCE_UNAVAILABLE"
    assert not (directory / "response.json").exists()
    assert harness.calls == 1


def test_symlink_evidence_root_is_rejected_before_writes_or_calls(setup):
    _, spec, request, producer, harness = setup
    target = producer.root.parent / ("empty-target-" + uuid4().hex)
    target.mkdir()
    alias = producer.root.parent / ("alias-" + uuid4().hex)
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="aliases"):
        SdkCampaignProducer(alias)
    assert not tuple(target.iterdir())
    aliased_profile = spec.sdk_profile.model_copy(update={"evidence_root": str(alias)})
    aliased_spec = spec.model_copy(update={"sdk_profile": aliased_profile})
    with pytest.raises(ValueError, match="aliases"):
        SdkCampaignProducer(target).prepare(request, aliased_spec)
    assert not tuple(target.iterdir())
    assert harness.calls == 0


def test_semantic_sdk_schema_requires_every_host_required_property():
    schema = json.loads(semantic_schema())
    assert set(schema["required"]) == set(schema["properties"])
    assert "schema_version" in schema["required"]
    assert schema["properties"]["schema_version"]["const"] == "sdk-candidate-reference/v1"


def test_sdk_execution_successor_requires_exact_scope_and_preserves_dq_guards(setup):
    from quantos.application.autonomous_execution import _verify_sdk_execution_scope

    service, spec, _, _, harness = setup
    o = service._registered(spec.campaign_hash).orchestrator
    frozen = dict(
        campaign=o.campaign,
        family=o.family,
        budget=o.budget,
        template=o.template,
        manifest=o.manifest,
        bindings=o.execution_bindings,
        canonical_validation=True,
        p14dq_v2_profile=True,
        discovery_stage_recovery=False,
        discovery_profile=None,
        discovery_source_adoption=None,
    )
    _verify_sdk_execution_scope(spec, **frozen)
    for changed in (
        {"canonical_validation": False},
        {"canonical_validation": 1},
        {"p14dq_v2_profile": False},
        {"p14dq_v2_profile": 1},
        {"discovery_stage_recovery": True},
        {"discovery_stage_recovery": 0},
        {"discovery_profile": "singleton-full-chain/v1"},
        {"campaign": o.campaign.model_copy(update={"campaign_id": "scope-fork"})},
        {"bindings": o.execution_bindings.model_copy(update={"code_commit_hash": "0" * 40})},
    ):
        with pytest.raises(ValueError, match="frozen DQ authority"):
            _verify_sdk_execution_scope(spec, **(frozen | changed))
    with pytest.raises(ValueError, match="frozen DQ authority"):
        _verify_sdk_execution_scope(spec.model_dump(mode="python"), **frozen)
    assert harness.calls == 0


@pytest.mark.parametrize("counterfeit_secret", [False, True, "unicode-escaped"])
def test_failed_capture_publishes_host_diagnostics_with_independent_secret_guard(
    setup, monkeypatch, counterfeit_secret
):
    import base64
    from dataclasses import replace

    from quantos.contracts.harness import HarnessErrorKind, HarnessTerminalError
    from quantos.integrations.codex.sdk_adapter import _host_transport_capture

    _, spec, request, producer, harness = setup
    original_execute = harness.execute
    stdout, stderr = b"synthetic malformed SDK-host stdout\n", b"synthetic SDK-host stderr\n"
    diagnostic = _host_transport_capture(
        stdout, stderr, phase="HOST_JSON_PARSE", exception_class="JSONDecodeError", complete=True
    )
    if counterfeit_secret:
        # Producer must scan decoded originals independently of adapter assertions.
        unsafe = b"Authorization: Bearer synthetic-invalid-credential"
        if counterfeit_secret == "unicode-escaped":
            monkeypatch.setenv("P10_FORBIDDEN_SECRET", "escaped-known-marker")
            unsafe = b'{"note":"\\u0065scaped-known-marker"}'
            assert b"escaped-known-marker" not in unsafe
        diagnostic["streams"][0].update(
            base64=base64.b64encode(unsafe).decode(), bytes=len(unsafe), sha256=sha256_bytes(unsafe)
        )

    def failed_execute(execution_request):
        result = original_execute(execution_request)
        attempt = replace(
            result.attempts[0],
            terminal_error=HarnessTerminalError(
                kind=HarnessErrorKind.OUTPUT_INVALID, message_hash="1" * 64, retryable=False
            ),
            qualification_observations={"host_transport": diagnostic},
        )
        return HarnessExecutionResult(attempts=(attempt,))

    monkeypatch.setattr(harness, "execute", failed_execute)
    with pytest.raises(ArtifactIntegrityError, match="immutable failure"):
        producer.launch(request, spec, harness=harness)
    directory = producer.root / request.campaign_hash / request.content_hash
    metadata_bytes = (directory / "host-transport.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    assert metadata["phase"] == "HOST_JSON_PARSE"
    assert metadata["exception_class"] == "JSONDecodeError"
    assert (directory / "host-stderr.txt").read_bytes() == stderr
    if counterfeit_secret:
        assert not (directory / "host-stdout.txt").exists()
        assert metadata["streams"][0]["retention"] == "CREDENTIAL_OR_ENCODING_GUARD"
    else:
        assert (directory / "host-stdout.txt").read_bytes() == stdout
        assert metadata["streams"][0]["sha256"] == sha256_bytes(stdout)
    fact = json.loads((directory / "capture-fact.json").read_bytes())
    assert fact["host_transport_hash"] == sha256_bytes(metadata_bytes)
    assert producer.status(request, spec) == "FAILED"
    with pytest.raises(ArtifactIntegrityError, match="automatic reissue forbidden"):
        producer.launch(request, spec, harness=harness)
    assert harness.calls == 1


def test_producer_transport_metadata_rejects_known_parent_value(setup, monkeypatch):
    from dataclasses import replace

    from quantos.application.sdk_producer import _persist_host_transport, build_reservation
    from quantos.integrations.codex.sdk_adapter import _host_transport_capture

    _, spec, request, producer, harness = setup
    monkeypatch.setenv("P10_FORBIDDEN_SECRET", "KnownMetadataMarker")
    execution = harness.execute(build_reservation(request, spec).execution_request)
    diagnostic = _host_transport_capture(
        b"safe original stdout",
        b"safe original stderr",
        phase="HOST_JSON_PARSE",
        exception_class="KnownMetadataMarker",
        complete=True,
    )
    execution = HarnessExecutionResult(
        attempts=(
            replace(
                execution.attempts[0], qualification_observations={"host_transport": diagnostic}
            ),
        )
    )
    directory = producer.root / "synthetic-metadata-guard"
    with pytest.raises(ArtifactIntegrityError, match="metadata contains forbidden parent value"):
        _persist_host_transport(directory, execution)
    assert not (directory / "host-transport.json").exists()
