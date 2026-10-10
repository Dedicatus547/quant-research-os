"""Reject fixed synthetic source claims against the independently supplied original root."""

from __future__ import annotations

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedAgentRequest, HostedAgentResponse, parse_hosted_contract
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_fixture_frames import (
    FAKE_ATTESTATION_BYTES,
    HOST_OBSERVATION_SCHEMA_REJECTIONS,
    conflicting_model_capture,
)
from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore, extract_proposal
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def verify_untrusted_observation_source(
    request: HostedAgentRequest,
    submitted: bytes,
    case: str,
    source_conflict_rejected: object,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    if case in HOST_OBSERVATION_SCHEMA_REJECTIONS:
        if source_conflict_rejected is not None:
            raise HostedQualificationError("invalid self-report has an unrelated observation")
        return ()
    response = parse_hosted_contract(
        submitted, HostedAgentResponse, max_bytes=request.max_response_bytes
    )
    deployment = sources.deployment
    evidence = deployment.root / "evidence"
    # The existing evidence directory is mandatory: verifier construction must
    # not create a missing original source directory.
    with opened_directory(evidence):
        pass
    if case == "fake_attestation":
        untrusted = (
            deployment.root / "qualification-cases/Q08/fake_attestation/channel/untrusted-source"
        )
        if read_relative(untrusted, sha256_bytes(FAKE_ATTESTATION_BYTES)) != FAKE_ATTESTATION_BYTES:
            raise HostedQualificationError(
                "synthetic attestation was not retained outside the trusted source root"
            )
    original = raw_inventory(evidence)
    store = TrustedLauncherEvidenceStore(evidence, KnownValueGuard(()))
    rejected = False
    try:
        store.verify_response_source(
            response,
            request=request,
            spec=deployment.spec,
            profile=deployment.profile,
            initial_inventory=deployment.initial_projection,
            projection_root=deployment.paths.projection,
            configuration=deployment.launcher_configuration,
        )
    except (ArtifactIntegrityError, FileNotFoundError, ValueError):
        rejected = True
    if not rejected:
        raise HostedQualificationError("synthetic self-report acquired trusted source authority")
    if case == "source_model_conflict":
        if source_conflict_rejected is not True:
            raise HostedQualificationError("requested/observed model conflict was not observed")
        try:
            extract_proposal(
                conflicting_model_capture(response.proposal_json),
                deployment.launcher_configuration,
                guard=KnownValueGuard(()),
            )
        except ValueError:
            pass
        else:
            raise HostedQualificationError("requested/observed model conflict was accepted")
    elif source_conflict_rejected is not None:
        raise HostedQualificationError("self-report contains an unrelated conflict observation")
    verify_raw_inventory(evidence, original)
    return (original.content_hash, response.content_hash)
