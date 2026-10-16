"""Synthetic retained capture recovery; never launch a process, SDK or model."""

import json
from types import SimpleNamespace

import pytest
from test_discovery_hosted_offline import captured_fixture
from test_discovery_hosted_offline import prepared as prepared
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_offline_regression import requests

from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_generation_report import build_generation_analysis
from quantos.application.discovery_hosted import (
    recover_generation_capture,
    verify_generation_origin,
)
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.discovery import SequentialGenerationPolicy, SequentialLaunchSource
from quantos.contracts.discovery_hosted import (
    HostedGenerationProjectionFact,
    HostedSequentialGenerationOrigin,
)
from quantos.infrastructure.hosted_deployment import install_inventory


@pytest.fixture
def captured_sequential(prepared, durable):
    f = prepared
    request = f.request.generation_request
    reqs = (request, *(r.model_copy(update={"seed": 1729}) for r in requests(f.design)[1:]))
    policy = SequentialGenerationPolicy(
        design_hash=f.design.content_hash,
        request_hashes=tuple(r.content_hash for r in reqs),
        max_attempts_per_method=2,
    )
    store = GenerationStore(durable / "sequential-generation")
    store.save_sequential_policy(policy)
    for req in reqs:
        store.save_request(f.design, req)
    reservation = store.reserve(request)
    attempt = store.read_attempt(request, reservation)
    f.request = f.manager.prepare(
        f.design,
        request,
        reservation,
        f.config,
        f.profile,
        context_objects={request.input_hashes[0]: b'{"fixture":true}'},
        issued_at=f.request.issued_at,
        expires_at=f.request.expires_at,
        policy=policy,
        attempt=attempt,
    )
    f.projection = f.manager.root / f.request.content_hash / "projection"
    f.fact = HostedGenerationProjectionFact(
        design_hash=f.design.content_hash,
        request_hash=f.request.content_hash,
        reservation_hash=reservation.content_hash,
        deployment_profile_hash=f.profile.content_hash,
        host_instance="fixture.instance",
        initial_projection_inventory_hash=f.initial.content_hash,
        projection_inventory_hash=install_inventory(f.projection).content_hash,
    )
    record, _ = captured_fixture(f)
    for value in (f.request, f.config, f.profile):
        f.evidence.publish_bytes(value.canonical_bytes())
    job = durable / "generation-job"
    job.mkdir()
    atomic_write_bytes(job / "generation-reservation.json", reservation.canonical_bytes())
    source = SequentialLaunchSource(
        request_hash=request.content_hash,
        reservation_hash=reservation.content_hash,
        manager_root=str(f.manager.root),
        evidence_root=str(f.evidence.root),
        job_root=str(job),
        authenticated_principal="fixture",
    )
    store.save_launch_source(request, reservation, source)
    return SimpleNamespace(
        f=f, store=store, request=request, reservation=reservation, record=record
    )


def test_captured_original_recovery_and_freeze_never_issue_another_call(captured_sequential):
    p = captured_sequential
    before = (
        p.f.evidence.root / "generation-launches" / p.reservation.content_hash / "completion.json"
    ).read_bytes()
    response = recover_generation_capture(p.store.root, p.request, p.reservation)
    assert response.producer == "HOSTED_HANDOFF" and response.failure_code is None
    assert recover_generation_capture(p.store.root, p.request, p.reservation) == response
    envelope = json.loads(
        (
            p.store.root / "requests" / p.request.content_hash / "responses" / "000001.json"
        ).read_bytes()
    )
    origin = HostedSequentialGenerationOrigin.model_validate(envelope["hosted_origin"])
    request, _, record = verify_generation_origin(origin)
    assert request == p.f.request and record == p.record
    assert (
        before
        == (
            p.f.evidence.root
            / "generation-launches"
            / p.reservation.content_hash
            / "completion.json"
        ).read_bytes()
    )
    wrapper = p.store.freeze(p.f.design)
    counts = build_generation_analysis(wrapper, p.store)["counts"]
    assert counts["candidate_opportunities"] == {"granted": 6, "occupied": 1}
    assert counts["management_model_entries"]["confirmed"] == 1
    assert counts["management_model_entries"]["provider_internal_calls"] is None
    assert counts["scientific_execution"]["status"] == "NOT_OBSERVED"
    assert all(row["costs"]["monetary_cost"]["total"] is None for row in counts["methods"])


def test_completed_failure_cannot_be_rewritten_as_capture(design, durable):
    request = requests(design)[0]
    store = GenerationStore(durable / "failure")
    store.save_request(design, request)
    reservation = store.reserve(request)
    failure = store.complete(
        request, reservation, "", producer="OFFLINE_IMPORT", failure_code="CAPTURE_FAILED"
    )
    assert failure.failure_code == "CAPTURE_FAILED"
    with pytest.raises(ArtifactIntegrityError, match="cannot be rewritten"):
        recover_generation_capture(store.root, request, reservation)
