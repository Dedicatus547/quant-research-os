from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_deployment import (
    HostedChannelPolicy,
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedLauncherRecord,
    HostedMountObservation,
    HostedProjectionFact,
)
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    KnownValueGuard,
    export_projection,
    install_inventory,
    private_memory_fd,
)
from quantos.infrastructure.hosted_launcher import (
    EXTRACTION_RULE_BYTES,
    TrustedLauncherEvidenceStore,
    _capture_process,
    extract_proposal,
    hosted_prompt,
    register_model_auth_memory,
    scan_cli_capture,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.security import SecretArtifactRejected


def _configuration(**changes: object) -> HostedLauncherConfiguration:
    return HostedLauncherConfiguration.model_validate(
        {
            "output_byte_cap": 65536,
            "proposal_byte_cap": 65536,
            "runtime_timeout_seconds": 2,
            **changes,
        }
    )


def _events(proposal: str, *, model: str | None = None) -> bytes:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "observed-thread"},
        {"type": "turn.started", **({"model": model} if model else {})},
        {
            "type": "item.completed",
            "item": {"id": "one", "type": "agent_message", "text": proposal},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 123, "output_tokens": 10}},
    ]
    return b"\n".join(canonical_json_bytes(x) for x in events) + b"\n"


def _profile(
    configuration: HostedLauncherConfiguration, *, initial_inventory_hash: str = "a" * 64
) -> HostedDeploymentProfile:
    return HostedDeploymentProfile(
        operating_system="Linux",
        kernel_release="fixture-kernel",
        libc="fixture-libc",
        python_version="3.11.15",
        exact_commit="a" * 40,
        lock_hash="a" * 64,
        wheel_hash="a" * 64,
        install_inventory_hash="a" * 64,
        provenance_inventory_hash="a" * 64,
        configuration_hash="a" * 64,
        projection_inventory_hash=initial_inventory_hash,
        bwrap_binary_hash="a" * 64,
        os_inventory_hash="a" * 64,
        mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
        libseccomp_binary_hash="a" * 64,
        bwrap_version="0.6.1",
        seccomp_bpf_hash="a" * 64,
        cli_binary_hash="b" * 64,
        model_configuration_hash=configuration.content_hash,
        extraction_rule_hash=sha256_bytes(EXTRACTION_RULE_BYTES),
        policy=HostedChannelPolicy(
            header_byte_cap=4096,
            response_byte_cap=262144,
            reply_byte_cap=1052672,
            io_timeout_ms=100,
            operation_reply_timeout_ms=2000,
            max_connections=2,
            max_total_connections=20,
            listen_backlog=2,
        ),
    )


def test_fixed_extraction_retains_exact_proposal_bytes_and_unavailable_actual_model() -> None:
    proposal = '  {"candidate_hash":"' + "a" * 64 + '"}\n '
    output = _events(proposal)
    configuration = _configuration()
    extracted, model = extract_proposal(output, configuration, guard=KnownValueGuard(()))
    assert extracted == proposal.encode() and model is None
    scan_cli_capture(output, guard=KnownValueGuard(()))


@pytest.mark.parametrize(
    "case", ["tools", "duplicate", "failure", "duplicate_keys", "model_conflict", "secret"]
)
def test_invalid_or_self_reported_source_never_extracts_proposal(case: str) -> None:
    output = _events('{"candidate_hash":"' + "a" * 64 + '"}')
    if case == "tools":
        output = output.replace(b"agent_message", b"command_execution")
    elif case == "duplicate":
        output = output.replace(
            b'{"type":"turn.completed"',
            b'{"type":"item.completed","item":{"id":"two","type":"agent_message","text":"fake"}}\n{"type":"turn.completed"',
        )
    elif case == "failure":
        output = output.replace(b"turn.completed", b"turn.failed")
    elif case == "duplicate_keys":
        output = output.replace(
            b'"type":"thread.started"', b'"type":"thread.started","type":"thread.started"'
        )
    elif case == "model_conflict":
        output = _events('{"candidate_hash":"' + "a" * 64 + '"}', model="another-model")
    else:
        output = _events('{"api_key":"NON_SECRET_TEST_CREDENTIAL"}')
    with pytest.raises((ValueError, SecretArtifactRejected)):
        extract_proposal(output, _configuration(), guard=KnownValueGuard(()))


def test_known_capability_capture_does_not_publish_any_raw_output(tmp_path: Path) -> None:
    capability = b"CAPABILITY_CANARY_MEMORY_ONLY_ABCD"
    store = TrustedLauncherEvidenceStore(tmp_path / "evidence", KnownValueGuard((capability,)))
    output = _events(capability.decode())
    with pytest.raises(SecretArtifactRejected):
        scan_cli_capture(output, guard=store.guard)
    with pytest.raises(SecretArtifactRejected):
        store.publish_bytes(output)
    assert list(store.root.iterdir()) == []


def test_model_auth_memory_values_are_registered_before_capture_publication(tmp_path: Path) -> None:
    fd = private_memory_fd("fixture-model-auth")
    token = "NON_SECRET_AUTH_CANARY_ABCDEFGHIJKLMNOP"
    os.write(fd, json.dumps({"tokens": {"access_token": token}}).encode())
    store = TrustedLauncherEvidenceStore(tmp_path / "evidence", KnownValueGuard(()))
    try:
        register_model_auth_memory(fd, store.guard)
    finally:
        os.close(fd)
    with pytest.raises(SecretArtifactRejected):
        store.publish_bytes(_events(token))
    assert list(store.root.iterdir()) == []


def test_direct_process_capture_is_bounded_for_both_pipes_and_timeout() -> None:
    # This is an external process primitive test, not a genuine model-source fixture.
    result = _capture_process(
        (
            sys.executable,
            "-c",
            "import sys; x=sys.stdin.read(); print(x); print('safe-diagnostic',file=sys.stderr)",
        ),
        pass_fds=(),
        configuration=_configuration(),
        input_bytes=b"FROZEN_PROMPT",
    )
    assert result[0] == 0 and result[1] == b"FROZEN_PROMPT\n" and result[3] == "CAPTURED"
    assert result[2] == b"safe-diagnostic\n"
    oversized = _capture_process(
        (sys.executable, "-c", "print('x'*10000)"),
        pass_fds=(),
        configuration=_configuration(output_byte_cap=100),
        input_bytes=b"prompt",
    )
    assert oversized[3] == "OUTPUT_LIMIT" and len(oversized[1]) + len(oversized[2]) == 101
    timeout = _capture_process(
        (sys.executable, "-c", "import time; time.sleep(3)"),
        pass_fds=(),
        configuration=_configuration(runtime_timeout_seconds=1),
        input_bytes=b"prompt",
    )
    assert timeout[3] == "TIMED_OUT"


def test_trusted_source_root_and_output_binding_are_required(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    configuration = _configuration()
    initial_projection = tmp_path / "initial-projection"
    initial_projection.mkdir()
    (initial_projection / "initial-schema").write_bytes(b"static initial input")
    initial_inventory = install_inventory(initial_projection)
    profile = _profile(configuration, initial_inventory_hash=initial_inventory.content_hash)
    spec = fixture.spec.model_copy(update={"deployment_profile_hash": profile.content_hash})
    protocol = HostedProtocolService(
        HostedProtocolStore(tmp_path / "bound-protocol"),
        clock=fixture.clock,
        verify_inputs=lambda _: None,
    )
    protocol.register(spec)
    request = protocol.issue(
        spec.content_hash,
        fixture.request.business_request,
        projection_object_hashes=(fixture.request.context_pack_hash,),
    )
    projection_root = tmp_path / "request-projection"
    projection = export_projection(
        projection_root,
        request,
        {request.context_pack_hash: request.business_request.context_pack.canonical_bytes()},
        guard=KnownValueGuard(()),
    )
    assert isinstance(projection, HostedInstallInventory)
    store = TrustedLauncherEvidenceStore(tmp_path / "management-evidence", KnownValueGuard(()))
    output = _events(fixture.response.proposal_json)
    output_hash = store.publish_bytes(output)
    fact = HostedProjectionFact(
        campaign_hash=request.campaign_hash,
        hosted_spec_hash=spec.content_hash,
        deployment_profile_hash=profile.content_hash,
        request_hash=request.content_hash,
        host_instance="fixture.instance",
        initial_projection_inventory_hash=initial_inventory.content_hash,
        projection_inventory_hash=projection.content_hash,
    )
    fact_hash = store.publish_bytes(fact.canonical_bytes())
    mount = HostedMountObservation(
        request_hash=request.content_hash,
        deployment_profile_hash=profile.content_hash,
        projection_inventory_hash=projection.content_hash,
        observed_uid=1000,
        observed_gid=1000,
    )
    mount_hash = store.publish_bytes(mount.canonical_bytes())
    record = HostedLauncherRecord(
        deployment_profile_hash=profile.content_hash,
        host_instance="fixture.instance",
        request_hash=request.content_hash,
        projection_inventory_hash=projection.content_hash,
        projection_fact_hash=fact_hash,
        executable_hash=profile.cli_binary_hash,
        executable_version="0.158.0",
        configuration_hash=configuration.content_hash,
        argv_hash="a" * 64,
        prompt_hash=sha256_bytes(hosted_prompt(request)),
        isolation_observation_hash=mount_hash,
        raw_output_hash=output_hash,
        raw_output_complete=True,
        diagnostic_output_hash=None,
        proposal_hash=fixture.response.proposal_hash,
        proposal_bytes=len(fixture.response.proposal_json.encode()),
        started_at=fixture.clock.now,
        terminated_at=fixture.clock.now + timedelta(seconds=1),
        exit_code=0,
        outcome="CAPTURED",
        reason="FIXTURE_NOT_LIVE_SOURCE",
        unavailable_reasons=("FIXTURE_NOT_QUALIFIED",),
    )
    record_hash = store.publish_record(record)
    response = fixture.response.model_copy(
        update={
            "request_hash": request.content_hash,
            "campaign_hash": request.campaign_hash,
            "context_pack_hash": request.context_pack_hash,
            "attempt_identity": request.attempt_identity,
            "host_observation": fixture.response.host_observation.model_copy(
                update={"external_evidence_hashes": (record_hash,)}
            ),
        }
    )
    assert (
        store.verify_response_source(
            response,
            request=request,
            spec=spec,
            profile=profile,
            initial_inventory=initial_inventory,
            projection_root=projection_root,
            configuration=configuration,
        )
        == record
    )
    fake = TrustedLauncherEvidenceStore(tmp_path / "different-root", KnownValueGuard(()))
    with pytest.raises((ArtifactIntegrityError, FileNotFoundError)):
        fake.verify_response_source(
            response,
            request=request,
            spec=spec,
            profile=profile,
            initial_inventory=initial_inventory,
            projection_root=projection_root,
            configuration=configuration,
        )
    conflicting = response.model_copy(
        update={
            "host_observation": response.host_observation.model_copy(
                update={"reported_model_identifier": "another-model"}
            )
        }
    )
    with pytest.raises(ArtifactIntegrityError):
        store.verify_response_source(
            conflicting,
            request=request,
            spec=spec,
            profile=profile,
            initial_inventory=initial_inventory,
            projection_root=projection_root,
            configuration=configuration,
        )
    altered = response.model_copy(update={"proposal_json": json.dumps({"different": "bytes"})})
    with pytest.raises(ArtifactIntegrityError):
        store.verify_response_source(
            altered,
            request=request,
            spec=spec,
            profile=profile,
            initial_inventory=initial_inventory,
            projection_root=projection_root,
            configuration=configuration,
        )
