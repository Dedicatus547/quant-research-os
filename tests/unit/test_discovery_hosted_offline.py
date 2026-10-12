"""Synthetic source binding and projection tests; no launcher, auth or model invocation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_offline_regression import requests
from test_hosted_launcher import _configuration, _events, _profile

from quantos.application.discovery_hosted import (
    HostedGenerationManager,
    generation_prompt,
    generation_schema_bytes,
    verify_generation_origin,
)
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import GenerationReservation
from quantos.contracts.discovery_hosted import (
    HostedGenerationOrigin,
    HostedGenerationProjectionFact,
    HostedGenerationResponse,
)
from quantos.contracts.hosted import HostObservation, HostReportedUsage
from quantos.contracts.hosted_deployment import HostedLauncherRecord, HostedMountObservation
from quantos.infrastructure import discovery_launcher as launcher
from quantos.infrastructure.discovery_launcher import verify_generation_projection_fact
from quantos.infrastructure.hosted_deployment import KnownValueGuard, install_inventory
from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore


@pytest.fixture
def prepared(design, durable):
    config = _configuration(model="gpt-6.1-sol", reasoning_effort="high")
    context = b'{"fixture":true}'
    schema = generation_schema_bytes()
    initial = durable / "initial"
    for digest, data in {
        design.content_hash: design.canonical_bytes(),
        config.content_hash: config.canonical_bytes(),
        sha256_bytes(context): context,
        sha256_bytes(schema): schema,
    }.items():
        atomic_write_bytes(initial / digest, data)
    inventory = install_inventory(initial)
    profile = _profile(config, initial_inventory_hash=inventory.content_hash).model_copy(
        update={"host_proc": "EMPTY_READ_ONLY_TMPFS"}
    )
    request = requests(design)[0].model_copy(
        update={"configuration_hash": config.content_hash, "reasoning_effort": "high"}
    )
    reservation = GenerationReservation(request_hash=request.content_hash, ordinal=1)
    evidence = TrustedLauncherEvidenceStore(durable / "evidence", KnownValueGuard(()))
    manager = HostedGenerationManager(
        durable / "manager",
        evidence=evidence,
        authenticated_principal="fixture",
        guard=evidence.guard,
    )
    now = datetime.now(UTC)
    hosted = manager.prepare(
        design,
        request,
        reservation,
        config,
        profile,
        context_objects={sha256_bytes(context): context},
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(hours=1),
    )
    projection = manager.root / hosted.content_hash / "projection"
    fact = HostedGenerationProjectionFact(
        design_hash=design.content_hash,
        request_hash=hosted.content_hash,
        reservation_hash=reservation.content_hash,
        deployment_profile_hash=profile.content_hash,
        host_instance="fixture.instance",
        initial_projection_inventory_hash=inventory.content_hash,
        projection_inventory_hash=install_inventory(projection).content_hash,
    )
    return SimpleNamespace(
        design=design,
        config=config,
        profile=profile,
        request=hosted,
        evidence=evidence,
        manager=manager,
        initial=inventory,
        projection=projection,
        fact=fact,
        now=now,
    )


def verify_projection(f):
    return verify_generation_projection_fact(
        f.fact,
        request=f.request,
        design=f.design,
        profile=f.profile,
        configuration=f.config,
        initial_inventory=f.initial,
        projection_root=f.projection,
        evidence=f.evidence,
    )


def test_preparation_is_offline_and_exact_projection_rejects_additions(prepared):
    f = prepared
    assert verify_projection(f).content_hash == f.fact.projection_inventory_hash
    assert b"Do not use tools" in generation_prompt(f.request)
    status = (f.manager.root / f.request.content_hash / "status.json").read_bytes()
    assert b'"real_model_calls":0' in status
    atomic_write_bytes(f.projection / ("f" * 64), b"unrelated")
    with pytest.raises(ArtifactIntegrityError, match="inventory"):
        verify_projection(f)


@pytest.mark.parametrize(
    "field",
    [
        "design_hash",
        "request_hash",
        "reservation_hash",
        "deployment_profile_hash",
        "initial_projection_inventory_hash",
    ],
)
def test_projection_fact_cannot_substitute_a_different_source(prepared, field):
    prepared.fact = prepared.fact.model_copy(update={field: "f" * 64})
    with pytest.raises(ArtifactIntegrityError, match="bindings"):
        verify_projection(prepared)


def captured_fixture(f):
    """Create declared synthetic transport records without calling transport code."""
    proposal = f.design.authoring.expression.canonical_bytes().decode()
    output_hash = f.evidence.publish_bytes(_events(proposal))
    fact_hash = f.evidence.publish_bytes(f.fact.canonical_bytes())
    mount = HostedMountObservation(
        request_hash=f.request.content_hash,
        deployment_profile_hash=f.profile.content_hash,
        projection_inventory_hash=f.fact.projection_inventory_hash,
        observed_uid=1000,
        observed_gid=1000,
    )
    mount_hash = f.evidence.publish_bytes(mount.canonical_bytes())
    record = HostedLauncherRecord(
        deployment_profile_hash=f.profile.content_hash,
        host_instance=f.fact.host_instance,
        request_hash=f.request.content_hash,
        projection_inventory_hash=f.fact.projection_inventory_hash,
        projection_fact_hash=fact_hash,
        executable_hash=f.profile.cli_binary_hash,
        executable_version=f.profile.cli_version,
        configuration_hash=f.config.content_hash,
        argv_hash="a" * 64,
        prompt_hash=sha256_bytes(generation_prompt(f.request)),
        isolation_observation_hash=mount_hash,
        raw_output_hash=output_hash,
        raw_output_complete=True,
        diagnostic_output_hash=None,
        proposal_hash=sha256_bytes(proposal.encode()),
        proposal_bytes=len(proposal.encode()),
        actual_model_identifier=None,
        started_at=f.now,
        terminated_at=f.now + timedelta(seconds=1),
        exit_code=0,
        outcome="CAPTURED",
        reason="CLI_EVENT_CAPTURED",
        unavailable_reasons=("SYNTHETIC_TRANSPORT_FIXTURE_NO_MODEL_CALL",),
    )
    f.evidence.publish_record(record)
    response = HostedGenerationResponse(
        request_hash=f.request.content_hash,
        design_hash=f.design.content_hash,
        reservation_hash=f.request.reservation.content_hash,
        proposal_json=proposal,
        proposal_hash=record.proposal_hash,
        host_observation=HostObservation(
            requested_configuration_hash=f.config.content_hash,
            reported_usage=HostReportedUsage(unavailable_reason="HOST_INTERNAL_USAGE_UNAVAILABLE"),
            external_evidence_hashes=(record.content_hash,),
            unavailable_reasons=(
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_TRANSCRIPT_UNAVAILABLE",
            ),
        ),
    )
    accepted = Path(__file__).parents[1] / "fixtures/discovery_regression/accepted-component.json"
    accepted_hash = f.evidence.publish_bytes(accepted.read_bytes())
    launch = {
        "schema_version": "discovery-hosted-launch-attempt/v1",
        "qualification": "NOT_EVALUATED",
        "request_hash": f.request.content_hash,
        "reservation_hash": f.request.reservation.content_hash,
        "design_hash": f.design.content_hash,
        "projection_fact_hash": fact_hash,
        "projection_inventory_hash": f.fact.projection_inventory_hash,
        "deployment_profile_hash": f.profile.content_hash,
        "configuration_hash": f.config.content_hash,
        "accepted_component_record_hash": accepted_hash,
        "adopted_deployment_profile_hash": (
            "1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf"
        ),
        "adopted_scope": "RUNTIME_AND_ISOLATION_FACILITIES_ONLY",
        "successor_profile_differences": ["model_configuration_hash", "projection_inventory_hash"],
        "old_business_qualification_adopted": False,
        "prompt_hash": record.prompt_hash,
        "started_at": f.now.isoformat(),
    }
    raw = canonical_json_bytes(launch)
    complete = {
        "schema_version": "discovery-hosted-launch-completion/v1",
        "prelaunch_hash": sha256_bytes(raw),
        "launcher_record_hash": record.content_hash,
        "outcome": "CAPTURED",
        "reason": record.reason,
        "process_exit": 0,
        "terminated_at": record.terminated_at,
        "qualification": "NOT_EVALUATED",
    }
    directory = f.evidence.root / "generation-launches" / f.request.reservation.content_hash
    atomic_write_bytes(directory / "prelaunch.json", raw)
    atomic_write_bytes(directory / "completion.json", canonical_json_bytes(complete))
    return record, response


def test_source_receipt_keeps_unknown_usage_and_replays_original_bytes(prepared):
    f = prepared
    record, response = captured_fixture(f)
    receipt = f.manager.verify_existing_capture(
        response,
        request=f.request,
        configuration=f.config,
        profile=f.profile,
        launcher_record_hash=record.content_hash,
    )
    assert receipt.qualification == "NOT_EVALUATED"
    for contract in (f.request, f.config, f.profile):
        f.evidence.publish_bytes(contract.canonical_bytes())
    origin = HostedGenerationOrigin(
        manager_root=str(f.manager.root),
        evidence_root=str(f.evidence.root),
        authenticated_principal="fixture",
        request_hash=f.request.content_hash,
        response_hash=response.content_hash,
        source_receipt_hash=receipt.content_hash,
        configuration_hash=f.config.content_hash,
        deployment_profile_hash=f.profile.content_hash,
    )
    assert verify_generation_origin(origin) == (f.request, response, record)
    claimed = response.model_copy(
        update={
            "host_observation": response.host_observation.model_copy(
                update={
                    "reported_usage": HostReportedUsage(
                        input_tokens=0, unavailable_reason="HOST_INTERNAL_USAGE_UNAVAILABLE"
                    )
                }
            )
        }
    )
    with pytest.raises(ArtifactIntegrityError, match="unknown"):
        f.manager.verify_existing_capture(
            claimed,
            request=f.request,
            configuration=f.config,
            profile=f.profile,
            launcher_record_hash=record.content_hash,
        )
    with pytest.raises(ArtifactIntegrityError, match="source bindings"):
        f.manager.verify_existing_capture(
            response.model_copy(update={"reservation_hash": "f" * 64}),
            request=f.request,
            configuration=f.config,
            profile=f.profile,
            launcher_record_hash=record.content_hash,
        )


@pytest.mark.parametrize(
    "outcome,exit_code,expected",
    [
        ("CAPTURED", 0, "CAPTURED"),
        ("CAPTURED", 1, "REJECTED"),
        ("TIMED_OUT", None, "TIMED_OUT"),
        ("OUTPUT_LIMIT", None, "OUTPUT_LIMIT"),
        ("exception", None, "REJECTED"),
        ("unsafe", 0, "REJECTED"),
    ],
)
def test_transport_result_classification_without_starting_transport(
    prepared,
    monkeypatch,
    outcome,
    exit_code,
    expected,
):
    import os

    f = prepared
    descriptor, bpf = launcher.source_seccomp_filter()
    try:
        profile = f.profile.model_copy(update={"seccomp_bpf_hash": sha256_bytes(bpf)})
        monkeypatch.setattr(launcher, "source_seccomp_filter", lambda: (os.dup(descriptor), bpf))
        projection = install_inventory(f.projection)
        mount = HostedMountObservation(
            request_hash=f.request.content_hash,
            deployment_profile_hash=profile.content_hash,
            projection_inventory_hash=projection.content_hash,
            observed_uid=1000,
            observed_gid=1000,
        )
        monkeypatch.setattr(launcher, "probe_projection_mount", lambda *args, **kwargs: mount)
        monkeypatch.setattr(
            launcher, "namespace_command", lambda *args, **kwargs: ("synthetic-never-executed",)
        )

        def fixture_capture(*args, **kwargs):
            if outcome == "exception":
                raise OSError("synthetic transport error")
            raw = b'{"api_key":"fixture-secret"}' if outcome == "unsafe" else _events("{}")
            return exit_code, raw, b"", "CAPTURED" if outcome == "unsafe" else outcome

        monkeypatch.setattr(launcher, "_capture_process", fixture_capture)
        record, proposal = launcher._capture_generation_projection(
            SimpleNamespace(),
            profile=profile,
            configuration=f.config,
            evidence=f.evidence,
            request=f.request,
            projection=projection,
            projection_fact_hash=f.fact.content_hash,
            host_instance="synthetic",
            prompt=generation_prompt(f.request),
            model_auth_memory_fd=None,
        )
        assert record.outcome == expected
        assert (proposal is not None) == (expected == "CAPTURED")
        if outcome in {"TIMED_OUT", "OUTPUT_LIMIT"}:
            assert not record.raw_output_complete
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("capture_failed", [False, True])
def test_managed_capture_keeps_one_launch_and_records_unknown_failure_exit(
    prepared, monkeypatch, capture_failed
):
    f = prepared
    obj = object.__new__(launcher.DiscoveryCodexLauncher)
    obj.paths = SimpleNamespace(projection=f.projection, configuration=f.manager.root / "config")
    obj.profile, obj.configuration, obj.evidence = f.profile, f.config, f.evidence
    obj.adopted_profile = f.profile
    obj._accepted_component_bytes = (
        Path(__file__).parents[1] / "fixtures/discovery_regression/accepted-component.json"
    ).read_bytes()
    monkeypatch.setattr(launcher, "storage_checkpoint", lambda *a: None)
    monkeypatch.setattr(obj, "_verify_runtime_originals", lambda _: None)
    fact_hash = f.evidence.publish_bytes(f.fact.canonical_bytes())
    calls = []
    record = SimpleNamespace(
        content_hash="c" * 64,
        outcome="CAPTURED",
        reason="SYNTHETIC_CAPTURE",
        exit_code=0,
        terminated_at=f.now,
    )

    def capture(*args, **kwargs):
        calls.append(kwargs["request"].content_hash)
        if capture_failed:
            raise RuntimeError("synthetic transport exception: confidential detail")
        return record, b"{}"

    monkeypatch.setattr(launcher, "_capture_generation_projection", capture)
    kwargs = dict(projection_fact_hash=fact_hash, host_instance=f.fact.host_instance)

    def launch():
        return obj.capture(
            f.request, f.design, install_inventory(f.projection), f.initial, **kwargs
        )

    if capture_failed:
        with pytest.raises(ArtifactIntegrityError, match="capture failed"):
            launch()
    else:
        assert launch() == (record, b"{}")
    import json

    completion = next(f.evidence.root.glob("generation-launches/*/completion.json"))
    saved = completion.read_bytes()
    value = json.loads(saved)
    assert value["process_exit"] == (None if capture_failed else 0)
    assert b"confidential" not in saved
    with pytest.raises(ArtifactIntegrityError, match="already has a launch"):
        launch()
    assert len(calls) == 1 and completion.read_bytes() == saved


@pytest.mark.parametrize("damage", ["fact", "inventory", "expired", "runtime"])
def test_capture_rejects_prelaunch_changes_before_transport(prepared, monkeypatch, damage):
    f = prepared
    obj = object.__new__(launcher.DiscoveryCodexLauncher)
    obj.paths = SimpleNamespace(projection=f.projection, configuration=f.manager.root / "config")
    obj.profile, obj.configuration, obj.evidence = f.profile, f.config, f.evidence
    obj.adopted_profile = f.profile
    obj._accepted_component_bytes = (
        Path(__file__).parents[1] / "fixtures/discovery_regression/accepted-component.json"
    ).read_bytes()
    monkeypatch.setattr(launcher, "storage_checkpoint", lambda *a: None)

    def runtime(_):
        if damage == "runtime":
            raise ArtifactIntegrityError("runtime original differs")

    monkeypatch.setattr(obj, "_verify_runtime_originals", runtime)
    monkeypatch.setattr(
        launcher,
        "_capture_generation_projection",
        lambda *a, **kw: pytest.fail("transport must not run"),
    )
    fact_hash = f.evidence.publish_bytes(f.fact.canonical_bytes())
    inventory = install_inventory(f.projection)
    if damage == "inventory":
        inventory = inventory.model_copy(update={"files": inventory.files[:-1]})
    if damage == "expired":
        monkeypatch.setattr(
            launcher, "datetime", SimpleNamespace(now=lambda _: f.request.expires_at)
        )
    with pytest.raises(ArtifactIntegrityError):
        obj.capture(
            f.request,
            f.design,
            inventory,
            f.initial,
            projection_fact_hash=fact_hash,
            host_instance="wrong-instance" if damage == "fact" else f.fact.host_instance,
        )
    assert not tuple(f.evidence.root.glob("generation-launches/*/prelaunch.json"))


@pytest.mark.parametrize("claimed_usage", [None, 0])
def test_hosted_generation_store_binds_independent_originals_and_keeps_unknown_usage(
    prepared, claimed_usage
):
    from quantos.application.discovery_generation import GenerationStore

    f = prepared
    record, response = captured_fixture(f)
    receipt = f.manager.verify_existing_capture(
        response,
        request=f.request,
        configuration=f.config,
        profile=f.profile,
        launcher_record_hash=record.content_hash,
    )
    for contract in (f.request, f.config, f.profile):
        f.evidence.publish_bytes(contract.canonical_bytes())
    origin = HostedGenerationOrigin(
        manager_root=str(f.manager.root),
        evidence_root=str(f.evidence.root),
        authenticated_principal="fixture",
        request_hash=f.request.content_hash,
        response_hash=response.content_hash,
        source_receipt_hash=receipt.content_hash,
        configuration_hash=f.config.content_hash,
        deployment_profile_hash=f.profile.content_hash,
    )
    request = f.request.generation_request
    store = GenerationStore(f.manager.root.parent / "generation-store")
    store.save_request(f.design, request)
    reserved = store.reserve(request)
    captured = store.complete(
        request,
        reserved,
        response.proposal_json,
        producer="HOSTED_HANDOFF",
        hosted_origin=origin,
        usage_input_units=claimed_usage,
        wall_seconds=1,
    )
    if claimed_usage is None:
        assert captured.failure_code is None and captured.usage_input_units is None
        assert store.inventory(request)[1] == (captured,)
    else:
        assert captured.failure_code == "CAPTURE_PROVENANCE_REJECTED" and captured.text == ""
