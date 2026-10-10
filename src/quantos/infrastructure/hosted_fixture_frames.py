"""Explicit synthetic transport recipes shared by management capture and verification.

These bytes never provide live model provenance. Credential-like recipes are only
synthetic scanner inputs and must never be exported as raw or reversible bytes.
"""

from __future__ import annotations

from quantos.contracts.autonomous import AutonomousCandidateProposal
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostObservation,
    HostReportedUsage,
)

BOUNDED_REJECTION_CASES = (
    "frame_byte_cap",
    "invalid_utf8",
    "duplicate_json_keys",
    "unknown_fields",
    "noncanonical",
    "unknown_candidate",
    "credential_like",
)

BUSINESS_REJECTION_CASES = (
    "known_schema_invalid",
    "unsafe_dsl",
    "invalid_ast",
    "outside_parameters",
    "wrong_exact_fingerprint",
    "wrong_structural_fingerprint",
)

DUPLICATE_SUBMISSION_CASES = ("accepted", "rejected")
DUPLICATE_SNAPSHOT_PHASES = (
    "before",
    "after-submit",
    "after-first-resume",
    "after-business",
    "before-cap",
    "after",
)


def duplicate_frame(request: HostedAgentRequest, case: str) -> bytes:
    if case not in DUPLICATE_SUBMISSION_CASES:
        raise ValueError("unknown fixed duplicate case")
    return (
        business_rejection_frame(request, "known_schema_invalid") if case == "accepted" else b"{}"
    )


def transport_fixture_response(request: HostedAgentRequest) -> HostedAgentResponse:
    proposal = canonical_json_bytes(
        {"candidate_hash": request.business_request.candidate_options[0].content_hash}
    ).decode()
    return HostedAgentResponse(
        request_hash=request.content_hash,
        campaign_hash=request.campaign_hash,
        transport_ordinal=request.transport_ordinal,
        context_pack_hash=request.context_pack_hash,
        attempt_identity=request.attempt_identity,
        proposal_json=proposal,
        proposal_hash=sha256_bytes(proposal.encode()),
        host_observation=HostObservation(
            requested_configuration_hash=request.business_request.agent_run_spec.requested_model_configuration_hash,
            reported_usage=HostReportedUsage(unavailable_reason="TRANSPORT_NEGATIVE_FIXTURE"),
            unavailable_reasons=(
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "HOST_TRANSCRIPT_UNAVAILABLE",
            ),
        ),
    )


def deterministic_candidate_frame(
    request: HostedAgentRequest, *, candidate_hash: str | None = None
) -> bytes:
    """A typed offline fault fixture from the frozen candidate; never live evidence."""
    candidate = next(
        (
            option
            for option in request.business_request.candidate_options
            if candidate_hash is None or option.content_hash == candidate_hash
        ),
        None,
    )
    if candidate is None:
        raise ValueError("fault candidate is outside the frozen request options")
    proposal = AutonomousCandidateProposal(
        campaign_hash=request.campaign_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=candidate.expression,
        exact_expression_hash=candidate.exact_expression_hash,
        structural_expression_hash=candidate.structural_expression_hash,
        rationale="SYNTHETIC_PHYSICAL_EXECUTION_FAULT_FIXTURE",
    ).canonical_bytes()
    return (
        transport_fixture_response(request)
        .model_copy(
            update={"proposal_json": proposal.decode(), "proposal_hash": sha256_bytes(proposal)}
        )
        .canonical_bytes()
    )


def bounded_rejection_frame(request: HostedAgentRequest, case: str) -> bytes:
    if case not in BOUNDED_REJECTION_CASES:
        raise ValueError("unknown fixed bounded rejection case")
    response = transport_fixture_response(request)
    if case == "frame_byte_cap":
        return b"x" * (request.max_response_bytes + 1)
    if case == "invalid_utf8":
        return b"\xff"
    if case == "duplicate_json_keys":
        return b'{"duplicate":1,"duplicate":2}'
    if case == "unknown_fields":
        return canonical_json_bytes({**response.model_dump(mode="json"), "unknown": True})
    if case == "noncanonical":
        return b" " + response.canonical_bytes()
    proposal = canonical_json_bytes(
        {"candidate_hash": "0" * 64}
        if case == "unknown_candidate"
        else {
            "candidate_hash": request.business_request.candidate_options[0].content_hash,
            "api_key": "SYNTHETIC_CREDENTIAL_REJECTION_FIXTURE_ONLY",
        }
    ).decode()
    return response.model_copy(
        update={"proposal_json": proposal, "proposal_hash": sha256_bytes(proposal.encode())}
    ).canonical_bytes()


def business_rejection_frame(request: HostedAgentRequest, case: str) -> bytes:
    if case not in BUSINESS_REJECTION_CASES:
        raise ValueError("unknown fixed business rejection case")
    candidate = request.business_request.candidate_options[0]
    proposal = AutonomousCandidateProposal(
        campaign_hash=request.campaign_hash,
        candidate_hash=candidate.content_hash,
        parameters=candidate.parameters,
        expression=candidate.expression,
        exact_expression_hash=candidate.exact_expression_hash,
        structural_expression_hash=candidate.structural_expression_hash,
        rationale="SYNTHETIC_ADMISSION_REJECTION_FIXTURE",
    ).model_dump(mode="json")
    if case == "known_schema_invalid":
        proposal["unknown_authority"] = True
    elif case == "unsafe_dsl":
        proposal["expression"]["nodes"][0]["operator"] = "EXEC_PYTHON"
    elif case == "invalid_ast":
        proposal["expression"]["output_node_id"] = "nonexistent.output"
    elif case == "outside_parameters":
        proposal["parameters"][0]["value"] = "OUTSIDE_FROZEN_DOMAIN"
    else:
        field = (
            "exact_expression_hash"
            if case == "wrong_exact_fingerprint"
            else "structural_expression_hash"
        )
        proposal[field] = "0" * 64
    text = canonical_json_bytes(proposal).decode()
    return (
        transport_fixture_response(request)
        .model_copy(update={"proposal_json": text, "proposal_hash": sha256_bytes(text.encode())})
        .canonical_bytes()
    )


HOST_OBSERVATION_CASES = (
    "reported_permission_pass",
    "reported_usage",
    "reported_model",
    "claimed_snapshot",
    "missing_transcript",
    "fake_attestation",
    "source_model_conflict",
    "reported_verdict",
    "fake_sdk_manifest",
    "removed_limitations",
    "claimed_trusted_source",
)
HOST_OBSERVATION_SCHEMA_REJECTIONS = (
    "reported_verdict",
    "fake_sdk_manifest",
    "removed_limitations",
    "claimed_trusted_source",
)
FAKE_ATTESTATION_BYTES = canonical_json_bytes(
    {"source": "HOST_REPORTED", "policy_pass": True, "fixture": "SYNTHETIC_UNTRUSTED_SOURCE"}
)


def host_observation_frame(request: HostedAgentRequest, case: str) -> bytes:
    """Self reports remain typed self reports; extra authority fields are invalid."""
    if case not in HOST_OBSERVATION_CASES:
        raise ValueError("unknown fixed host observation case")
    data = transport_fixture_response(request).model_dump(mode="json")
    observation = data["host_observation"]
    if case == "reported_permission_pass":
        observation["reported_permission_pass"] = True
    elif case == "reported_usage":
        observation["reported_usage"] = HostReportedUsage(
            input_tokens=0, output_tokens=0, cost_microunits=0
        ).model_dump(mode="json")
    elif case in ("reported_model", "source_model_conflict"):
        observation["reported_model_identifier"] = "SYNTHETIC_SELF_REPORTED_MODEL"
        observation["reported_reasoning_effort"] = "SYNTHETIC_SELF_REPORTED_EFFORT"
    elif case == "claimed_snapshot":
        observation["immutable_model_snapshot"] = "SYNTHETIC_SELF_REPORTED_SNAPSHOT"
    elif case == "fake_attestation":
        digest = sha256_bytes(FAKE_ATTESTATION_BYTES)
        observation["transcript_hash"] = digest
        observation["external_evidence_hashes"] = [digest]
    elif case == "reported_verdict":
        data["verdict"] = "PASS"
    elif case == "fake_sdk_manifest":
        data["sdk_manifest"] = {"permission_pass": True}
    elif case == "removed_limitations":
        observation["unavailable_reasons"] = ["SYNTHETIC_NO_LIMITATIONS_CLAIM"]
    elif case == "claimed_trusted_source":
        observation["source"] = "TRUSTED"
    return canonical_json_bytes(data)


def conflicting_model_capture(proposal: str) -> bytes:
    """Explicitly synthetic CLI metadata for requested/observed identity rejection."""
    events = (
        {"type": "thread.started", "thread_id": "synthetic-not-live"},
        {"type": "turn.started", "model": "SYNTHETIC_CONFLICTING_MODEL"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": proposal}},
        {"type": "turn.completed"},
    )
    return b"\n".join(canonical_json_bytes(event) for event in events) + b"\n"
