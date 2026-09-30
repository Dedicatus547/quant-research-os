from __future__ import annotations

import io
import json
import multiprocessing
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_autonomous_campaign import NOW, _inputs, _proposal

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.autonomous import AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetPolicy,
    HostedCampaignSpec,
    HostObservation,
    HostReportedUsage,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Fixture:
    root: Path
    clock: Clock
    service: HostedProtocolService
    spec: HostedCampaignSpec
    request: HostedAgentRequest
    response: HostedAgentResponse


def _fixture(tmp_path: Path, *, total: int = 5, per_request: int = 5) -> Fixture:
    inputs = _inputs(tmp_path / "business")
    orchestration = inputs.orchestrator(tmp_path, (_proposal(inputs, 0),))
    business_request, _ = orchestration._build_agent_request(
        inputs.initial_snapshot,
        orchestration._access_scope(inputs.initial_snapshot),
        orchestration.governor.project(inputs.campaign, inputs.budget, inputs.initial_events),
        inputs.initial_events,
    )
    assert inputs.selection.plan is not None
    spec = HostedCampaignSpec(
        campaign=inputs.campaign,
        research_budget=inputs.budget,
        hosted_budget=HostedBudgetPolicy(
            max_requests=3,
            max_unique_submissions=total,
            max_submissions_per_request=per_request,
            max_response_bytes=262_144,
            max_proposal_bytes=262_144,
            max_request_bytes=1_048_576,
            request_ttl_seconds=60,
        ),
        candidate_manifest_hash=inputs.manifest.content_hash,
        factor_template_hash=inputs.template.content_hash,
        selection_plan_hash=inputs.selection.plan.content_hash,
        selection_finalization_profile_hash=AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE.content_hash,
        execution_bindings=inputs.execution_bindings,
        search_policy_hash=inputs.search_policy.content_hash,
        context_budget_policy_hash=inputs.context_budget.content_hash,
        campaign_policy_hash=inputs.campaign_policy.content_hash,
        agent_run_policy_hash=inputs.agent_policy.content_hash,
        requested_model_configuration_hash=inputs.agent_policy.requested_model_configuration_hash,
        deployment_profile_hash="d" * 64,
        contract_hash="14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df",
        acceptance_hash="e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e",
        started_at=NOW,
    )
    clock = Clock()
    root = tmp_path / "protocol"
    service = HostedProtocolService(
        HostedProtocolStore(root), clock=clock, verify_inputs=lambda _: None
    )
    service.register(spec)
    request = service.issue(
        spec.content_hash,
        business_request,
        projection_object_hashes=(business_request.context_pack.content_hash,),
    )
    proposal = _proposal(inputs, 0).canonical_bytes().decode("utf-8")
    response = HostedAgentResponse(
        request_hash=request.content_hash,
        campaign_hash=spec.campaign_hash,
        transport_ordinal=1,
        context_pack_hash=request.context_pack_hash,
        attempt_identity=request.attempt_identity,
        proposal_json=proposal,
        proposal_hash=sha256_bytes(proposal.encode("utf-8")),
        host_observation=HostObservation(
            requested_configuration_hash=spec.requested_model_configuration_hash,
            reported_usage=HostReportedUsage(unavailable_reason="NOT_OBSERVED"),
            unavailable_reasons=(
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "HOST_TRANSCRIPT_UNAVAILABLE",
            ),
        ),
    )
    return Fixture(root, clock, service, spec, request, response)


def _mutate(response: HostedAgentResponse, **changes: object) -> bytes:
    return canonical_json_bytes({**response.model_dump(mode="json"), **changes})


def test_suspend_restart_queries_preserve_request_and_budget(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    before = f.service.status(f.spec.campaign_hash)
    inventory = sorted(str(x.relative_to(f.root)) for x in f.root.rglob("*"))
    service = HostedProtocolService(
        HostedProtocolStore(f.root), clock=f.clock, verify_inputs=lambda _: None
    )
    for _ in range(3):
        assert service.pending(f.spec.campaign_hash) == f.request
        assert service.status(f.spec.campaign_hash) == before
        assert service.resume(f.spec.campaign_hash) == before
    assert inventory == sorted(str(x.relative_to(f.root)) for x in f.root.rglob("*"))
    assert before.used_requests == 1 and before.used_unique_submissions == 0


def test_acceptance_same_bytes_precedes_expiry_cap_and_cancel(tmp_path: Path) -> None:
    f = _fixture(tmp_path, total=1, per_request=1)
    raw = f.response.canonical_bytes()
    receipt = f.service.submit(f.request.content_hash, raw, "host.one")
    assert receipt.outcome == "ACCEPTED"
    assert f.service.cancel(f.request.content_hash, "host.one").outcome == "CANCEL_REJECTED"
    f.clock.now += timedelta(hours=1)
    assert f.service.submit(f.request.content_hash, raw, "host.one") == receipt
    assert (
        f.service.accepted_exchange(f.request.content_hash)[2].provenance_kind == "HOSTED_EXCHANGE"
    )
    assert f.service.status(f.spec.campaign_hash).used_unique_submissions == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaign_hash", "a" * 64),
        ("transport_ordinal", 2),
        ("context_pack_hash", "b" * 64),
        ("attempt_identity", "c" * 64),
        ("request_hash", "e" * 64),
    ],
)
def test_wrong_bindings_have_bounded_immutable_receipt(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    f = _fixture(tmp_path)
    raw = _mutate(f.response, **{field: value})
    receipt = f.service.submit(f.request.content_hash, raw, "host.one")
    assert receipt.outcome == "REJECTED"
    assert receipt.reason == "RESPONSE_BINDING_MISMATCH"
    assert f.service.submit(f.request.content_hash, raw, "host.one") == receipt
    assert f.service.status(f.spec.campaign_hash).used_unique_submissions == 1
    assert f.service.accepted_exchange(f.request.content_hash) is None


@pytest.mark.parametrize("bad", [b"{} ", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"[]"])
def test_strict_json_rejects_noncanonical_duplicate_nonfinite_and_utf8(bad: bytes) -> None:
    with pytest.raises(ValueError):
        strict_json_object(bad, max_bytes=100)


@pytest.mark.parametrize("bad", [b"{}", b"\xff", b'{"x":1,"x":2}'])
def test_schema_rejection_is_idempotent_after_cancel(tmp_path: Path, bad: bytes) -> None:
    f = _fixture(tmp_path)
    receipt = f.service.submit(f.request.content_hash, bad, "host.one")
    f.service.cancel(f.request.content_hash, "host.one")
    f.clock.now += timedelta(hours=1)
    assert f.service.submit(f.request.content_hash, bad, "host.one") == receipt
    assert receipt.outcome == "REJECTED"


def test_conflict_preserves_first_acceptance_and_fixed_exhaustion(tmp_path: Path) -> None:
    f = _fixture(tmp_path, total=3, per_request=2)
    accepted = f.service.submit(f.request.content_hash, f.response.canonical_bytes(), "host.one")
    other = _mutate(f.response, transport_ordinal=2)
    conflict = f.service.submit(f.request.content_hash, other, "host.one")
    assert conflict.outcome == "CONFLICT"
    exhausted = f.service.submit(f.request.content_hash, b"{}", "host.one")
    assert exhausted.outcome == "EXHAUSTED"
    count = len(tuple(f.root.rglob("*")))
    for number in range(20):
        assert (
            f.service.submit(f.request.content_hash, str(number).encode(), "host.one") == exhausted
        )
    assert len(tuple(f.root.rglob("*"))) == count
    assert f.service.submit(f.request.content_hash, other, "host.one") == conflict
    assert (
        f.service.submit(f.request.content_hash, f.response.canonical_bytes(), "host.one")
        == accepted
    )


def test_campaign_submission_cap_is_fixed_and_does_not_refund(tmp_path: Path) -> None:
    f = _fixture(tmp_path, total=1, per_request=5)
    f.service.submit(f.request.content_hash, b"{}", "host.one")
    assert f.service.status(f.spec.campaign_hash).state == "EXHAUSTED"
    exhausted = f.service.submit(f.request.content_hash, b"[]", "host.one")
    assert exhausted.request_hash is None
    f.service.cancel(f.request.content_hash, "host.one")
    assert f.service.submit(f.request.content_hash, b"null", "host.one") == exhausted
    assert f.service.status(f.spec.campaign_hash).used_requests == 1
    assert f.service.status(f.spec.campaign_hash).used_unique_submissions == 1


def test_oversized_frame_prefix_is_not_full_response_hash(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    payload = b"x" * (f.request.max_response_bytes + 5000)
    stream = io.BytesIO(payload)
    bounded = f.service.read_response_frame(f.request.content_hash, stream)
    assert stream.tell() == f.request.max_response_bytes + 1
    receipt = f.service.submit(f.request.content_hash, bounded, "host.one")
    assert receipt.outcome == "REJECTED" and not receipt.complete
    assert receipt.submission_bytes_hash is None
    assert receipt.observed_bytes == f.request.max_response_bytes + 1
    assert receipt.observed_prefix_hash == sha256_bytes(bounded)
    assert f.service.submit(f.request.content_hash, payload, "host.one") == receipt
    assert not any(payload[:100] in path.read_bytes() for path in f.root.rglob("*.json"))


def test_expiry_status_is_readonly_resume_terminal_and_no_reissue(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    count = len(tuple(f.root.rglob("*")))
    f.clock.now += timedelta(seconds=60)
    status = f.service.status(f.spec.campaign_hash)
    assert status.state == "WAITING_FOR_AGENT" and status.projected_expiration
    assert len(tuple(f.root.rglob("*"))) == count
    assert f.service.resume(f.spec.campaign_hash).state == "EXPIRED"
    late = f.service.submit(f.request.content_hash, f.response.canonical_bytes(), "host.one")
    assert late.reason == "REQUEST_EXPIRED"
    with pytest.raises(ArtifactIntegrityError, match="reissue=false"):
        f.service.issue(
            f.spec.content_hash,
            f.request.business_request,
            projection_object_hashes=f.request.projection_object_hashes,
        )


def test_known_candidate_invalid_proposal_is_accepted_for_business_admission(
    tmp_path: Path,
) -> None:
    f = _fixture(tmp_path)
    proposal = json.loads(f.response.proposal_json)
    candidate = proposal["candidate_hash"]
    for text, expected in [
        (
            canonical_json_bytes({"candidate_hash": candidate, "arbitrary": "invalid"}).decode(),
            "ACCEPTED",
        ),
    ]:
        raw = _mutate(f.response, proposal_json=text, proposal_hash=sha256_bytes(text.encode()))
        assert f.service.submit(f.request.content_hash, raw, "host.one").outcome == expected


def test_unknown_candidate_rejected_without_trial(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    proposal = canonical_json_bytes({"candidate_hash": "0" * 64}).decode()
    receipt = f.service.submit(
        f.request.content_hash,
        _mutate(f.response, proposal_json=proposal, proposal_hash=sha256_bytes(proposal.encode())),
        "host.one",
    )
    assert receipt.reason == "UNKNOWN_CANDIDATE"
    assert not any("campaign-trial" in path.read_text() for path in f.root.rglob("*.json"))


def test_proposal_whitespace_preserved_and_scalar_schema_strict(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    proposal = "  " + f.response.proposal_json + "\n"
    raw = _mutate(f.response, proposal_json=proposal, proposal_hash=sha256_bytes(proposal.encode()))
    parsed = parse_hosted_contract(raw, HostedAgentResponse, max_bytes=262_144)
    assert parsed.proposal_json == proposal
    assert f.service.submit(f.request.content_hash, raw, "host.one").outcome == "ACCEPTED"
    with pytest.raises(ValueError):
        parse_hosted_contract(
            _mutate(f.response, transport_ordinal="1"), HostedAgentResponse, max_bytes=262_144
        )


def test_credential_like_proposal_never_persisted_or_echoed(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    proposal = json.loads(f.response.proposal_json)
    marker = "synthetic-sensitive-token-value"
    proposal["rationale"] = "TUSHARE_TOKEN=" + marker
    text = canonical_json_bytes(proposal).decode()
    receipt = f.service.submit(
        f.request.content_hash,
        _mutate(f.response, proposal_json=text, proposal_hash=sha256_bytes(text.encode())),
        "host.one",
    )
    assert receipt.reason == "CREDENTIAL_LIKE_PAYLOAD"
    assert marker not in receipt.canonical_bytes().decode()
    assert not any(marker.encode() in path.read_bytes() for path in f.root.rglob("*.json"))


def test_host_reported_numbers_do_not_attest_usage_snapshot_or_permissions(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    observation = f.response.host_observation.model_dump(mode="json")
    observation["reported_usage"] = HostReportedUsage(
        input_tokens=100, output_tokens=10, cost_microunits=1
    ).model_dump(mode="json")
    observation["immutable_model_snapshot"] = "claimed-snapshot"
    observation["reported_permission_pass"] = True
    raw = _mutate(f.response, host_observation=observation)
    receipt = f.service.submit(f.request.content_hash, raw, "host.one")
    assert receipt.outcome == "ACCEPTED"
    observation["unavailable_reasons"] = ["HOST_EFFECTIVE_POLICY_NOT_ATTESTED"]
    with pytest.raises(ValidationError):
        HostObservation.model_validate(observation)


@pytest.mark.parametrize("change", ["type", "strip", "default", "schema", "path"])
def test_canonical_contract_rejects_coercion_strip_defaults_and_extra_fields(
    tmp_path: Path,
    change: str,
) -> None:
    f = _fixture(tmp_path)
    payload = f.response.model_dump(mode="json")
    if change == "type":
        payload["transport_ordinal"] = "1"
    elif change == "strip":
        payload["request_hash"] = " " + f.request.content_hash
    elif change == "default":
        del payload["host_observation"]["source"]
    elif change == "schema":
        payload["schema_version"] = "hosted-agent-response/v99"
    else:
        payload["path"] = "../sealed"
    raw = canonical_json_bytes(payload)
    with pytest.raises(ValueError):
        parse_hosted_contract(raw, HostedAgentResponse, max_bytes=262_144)
    assert f.service.submit(f.request.content_hash, raw, "host.one").outcome == "REJECTED"


@pytest.mark.parametrize("key", ["api_key", "access_token", "input_tokens"])
def test_nested_proposal_cannot_use_usage_schema_to_hide_credentials(
    tmp_path: Path,
    key: str,
) -> None:
    f = _fixture(tmp_path)
    proposal = json.loads(f.response.proposal_json)
    marker = "synthetic-sensitive-marker"
    proposal["extra"] = {"schema_version": "hosted-reported-usage/v1", key: marker}
    text = canonical_json_bytes(proposal).decode()
    receipt = f.service.submit(
        f.request.content_hash,
        _mutate(f.response, proposal_json=text, proposal_hash=sha256_bytes(text.encode())),
        "host.one",
    )
    assert receipt.reason == "CREDENTIAL_LIKE_PAYLOAD"
    assert not any(marker.encode() in path.read_bytes() for path in f.root.rglob("*.json"))


@pytest.mark.parametrize(
    "point", ["intent_published", "artifact_published", "completion_published"]
)
def test_faulted_submit_recovers_original_bytes_timestamp_and_budget(
    tmp_path: Path, point: str
) -> None:
    f = _fixture(tmp_path)

    def fault(observed: str) -> None:
        if observed == point:
            raise RuntimeError("injected process exit")

    broken = HostedProtocolService(
        HostedProtocolStore(f.root, fault_hook=fault), clock=f.clock, verify_inputs=lambda _: None
    )
    raw = f.response.canonical_bytes()
    with pytest.raises(RuntimeError, match="injected"):
        broken.submit(f.request.content_hash, raw, "host.one")
    f.clock.now += timedelta(hours=1)
    receipt = f.service.submit(f.request.content_hash, raw, "host.one")
    assert receipt.outcome == "ACCEPTED" and receipt.recorded_at == NOW
    assert f.service.status(f.spec.campaign_hash).used_unique_submissions == 1


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "publish_temp", "fifo", "corrupt", "missing", "orphan"]
)
def test_authority_integrity_errors_fail_closed(tmp_path: Path, kind: str) -> None:
    f = _fixture(tmp_path)
    directory = f.root / "campaigns" / f.spec.campaign_hash / "objects"
    target = directory / (f.request.content_hash + ".json")
    if kind == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "escape")
    elif kind == "hardlink":
        os.link(target, tmp_path / "alias")
    elif kind == "publish_temp":
        # Simulates process death after link(temp,target), before unlink(temp).
        # Recovery preserves both names and fails closed; it never guesses that
        # an unexplained authority hard link is safe to remove.
        os.link(target, directory / ".publish-interrupted")
    elif kind == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif kind == "corrupt":
        target.write_bytes(b"{}")
    elif kind == "missing":
        target.unlink()
    elif kind == "orphan":
        (directory / ("f" * 64 + ".json")).write_bytes(b"{}")
    with pytest.raises((ArtifactIntegrityError, ValueError)):
        f.service.resume(f.spec.campaign_hash)


def _submit_process(root: str, request: str, raw: bytes, queue: object) -> None:
    service = HostedProtocolService(
        HostedProtocolStore(Path(root)), clock=lambda: NOW, verify_inputs=lambda _: None
    )
    receipt = service.submit(request, raw, "host.one")
    queue.put(receipt.content_hash)


def test_concurrent_processes_publish_one_submission(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    processes = [
        ctx.Process(
            target=_submit_process,
            args=(str(f.root), f.request.content_hash, f.response.canonical_bytes(), queue),
        )
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert len({queue.get(timeout=2) for _ in processes}) == 1
    assert f.service.status(f.spec.campaign_hash).used_unique_submissions == 1
