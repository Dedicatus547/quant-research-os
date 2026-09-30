"""Fixed management-only transport negative cases in the frozen service namespace.

Handwritten transport fixtures here never constitute live model source. The research
channel cannot select this program, its clock, or its case identifier.
"""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
    derive_hosted_campaign_spec,
)
from quantos.infrastructure.hosted_fixture_frames import (
    BOUNDED_REJECTION_CASES,
    BUSINESS_REJECTION_CASES,
    bounded_rejection_frame,
    business_rejection_frame,
    transport_fixture_response,
)
from quantos.infrastructure.hosted_service import (
    bootstrap_hosted_service,
    hydrate_service_capabilities,
    read_hashed_configuration,
)
from quantos.infrastructure.hosted_verification import (
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)
from quantos.research.qlib import QlibWorkflowResearchService

NEGATIVE_CASES = (
    "campaign_hash",
    "transport_ordinal",
    "context_pack_hash",
    "request_hash",
    "attempt_identity",
    "expired",
    "cancelled",
    "conflict",
)


def run_negative_probe(profile_hash: str, case: str) -> None:
    run_transport_fixture(profile_hash, case, "Q03")


def run_transport_fixture(profile_hash: str, case: str, family: str) -> None:
    allowed = {"Q03": NEGATIVE_CASES, "Q04": (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES)}
    if family not in allowed or case not in allowed[family]:
        raise ValueError("unknown fixed negative case")
    authority, channel = Path("/authority"), Path("/channel")
    initial = raw_inventory(authority)
    if initial.files or tuple(channel.iterdir()):
        raise ArtifactIntegrityError("negative case requires empty authority and channel")
    profile = read_hashed_configuration(Path("/config"), profile_hash, HostedDeploymentProfile)
    config = read_hashed_configuration(
        Path("/config"), profile.configuration_hash, HostedServiceConfiguration
    )
    loader = read_hashed_configuration(
        Path("/config"), config.business_configuration_hash, HostedBusinessLoaderConfiguration
    )
    bundle = read_hashed_configuration(
        Path("/inputs"), loader.business_inputs_hash, HostedFrozenBusinessInputs
    )
    clock = [bundle.hosted_recipe.started_at]
    execute_calls: list[str] = []
    workflow_calls: list[str] = []
    network_attempts: list[str] = []

    def denied_execute(self: QuantosResearchExecutionAdapter, request: Any) -> Any:
        execute_calls.append(request.execution_identity)
        raise ArtifactIntegrityError("negative transport attempted deterministic execution")

    def denied_workflow(self: QlibWorkflowResearchService, *args: Any, **kwargs: Any) -> Any:
        del self, args, kwargs
        workflow_calls.append("QLIB_WORKFLOW")
        raise ArtifactIntegrityError("negative transport attempted Qlib Workflow")

    def denied_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        network_attempts.append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("negative transport attempted network")

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", denied_execute),
        patch.object(QlibWorkflowResearchService, "run", denied_workflow),
        patch.object(socket.socket, "connect", denied_network),
        patch.object(socket.socket, "connect_ex", denied_network),
        patch.object(socket, "create_connection", denied_network),
    ):
        hydrate_service_capabilities(profile_hash)
        service = bootstrap_hosted_service(profile_hash, protocol_clock=lambda: clock[0])
        application = service.application
        if not isinstance(application, HostedCampaignApplicationService):
            raise ArtifactIntegrityError("negative application factory differs")
        application.start(
            derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash).content_hash
        )
        campaign = bundle.campaign.content_hash
        request = application.pending(campaign)
        if request is None:
            raise ArtifactIntegrityError("negative case has no frozen pending request")
        response = transport_fixture_response(request)
        raw = response.canonical_bytes()
        seen = None
        cancellation = None
        business_cancellation = None
        business_report_hash = None
        if family == "Q04":
            if case in BUSINESS_REJECTION_CASES:
                raw = business_rejection_frame(request, case)
            elif case == "frame_byte_cap":
                import io

                frame = io.BytesIO(b"x" * (request.max_response_bytes + 8192))
                raw = application.protocol.read_response_frame(request.content_hash, frame)
                if frame.tell() != request.max_response_bytes + 1:
                    raise ArtifactIntegrityError("oversized frame was not bounded")
            else:
                raw = bounded_rejection_frame(request, case)
        elif case in ("expired", "cancelled"):
            seen = application.submit(request.content_hash, b"{}", "negative.fixture")
            if case == "cancelled":
                cancellation = application.cancel(request.content_hash, "negative.fixture")
            else:
                clock[0] = request.expires_at
        elif case == "conflict":
            seen = application.submit(request.content_hash, raw, "negative.fixture")
            cancellation = application.cancel(request.content_hash, "negative.fixture")
            raw = canonical_json_bytes(
                {
                    **response.model_dump(mode="json"),
                    "transport_ordinal": response.transport_ordinal + 1,
                }
            )
        else:
            raw = canonical_json_bytes(
                {
                    **response.model_dump(mode="json"),
                    case: response.transport_ordinal + 1
                    if case == "transport_ordinal"
                    else "0" * 64,
                }
            )
        before = raw_inventory(authority)
        for item in before.files:
            atomic_write_bytes(
                channel / "before/authority" / item.logical_path,
                read_relative(authority, item.logical_path, max_bytes=16_777_216),
            )
        verify_raw_inventory(channel / "before/authority", before)
        verify_raw_inventory(authority, before)
        receipt = application.submit(request.content_hash, raw, "negative.fixture")
        if family == "Q04":
            expected = "ACCEPTED" if case in BUSINESS_REJECTION_CASES else "REJECTED"
            if receipt.outcome != expected:
                raise ArtifactIntegrityError("admission fixture transport outcome differs")
            if case in BUSINESS_REJECTION_CASES:
                status = application.resume(campaign)
                next_request = application.pending(campaign)
                if next_request is not None:
                    business_cancellation = application.cancel(
                        next_request.content_hash, "negative.fixture"
                    )
                    status = application.resume(campaign)
                business_report_hash = status.report_hash
                if business_report_hash is None:
                    raise ArtifactIntegrityError("business fixture has no immutable final report")
        after = raw_inventory(authority)
        clock[0] = request.expires_at + timedelta(seconds=1)
        repeat = application.submit(request.content_hash, raw, "negative.fixture")
        if repeat != receipt:
            raise ArtifactIntegrityError("negative repeat did not reuse receipt")
        if seen is not None:
            seen_raw = response.canonical_bytes() if case == "conflict" else b"{}"
            if application.submit(request.content_hash, seen_raw, "negative.fixture") != seen:
                raise ArtifactIntegrityError("seen bytes lost original receipt")
        if (
            cancellation is not None
            and application.cancel(request.content_hash, "negative.fixture") != cancellation
        ):
            raise ArtifactIntegrityError("repeated cancellation changed receipt")
        if (
            business_cancellation is not None
            and application.cancel(business_cancellation.request_hash, "negative.fixture")
            != business_cancellation
        ):
            raise ArtifactIntegrityError("business cancellation changed receipt")
        verify_raw_inventory(authority, after)
    if execute_calls or workflow_calls or network_attempts:
        raise ArtifactIntegrityError("negative fixture had a deterministic or network side effect")
    if any(
        name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
        for name in sys.modules
    ):
        raise ArtifactIntegrityError("negative fixture imported forbidden transport")
    observation = {
        "schema_version": "hosted-negative-observation/v1",
        "case": case,
        "case_family": family,
        "deployment_profile_hash": profile_hash,
        "campaign_hash": campaign,
        "request_hash": request.content_hash,
        "receipt_hash": receipt.content_hash,
        # Reversible rejected credential-like/invalid UTF-8/oversized bytes are
        # deliberately absent. The verifier reconstructs the fixed test recipe.
        "response_json": raw.decode() if family == "Q03" else None,
        "response_observed_hash": sha256_bytes(raw),
        "response_observed_bytes": len(raw),
        "before_inventory": before.model_dump(mode="json"),
        "after_inventory": after.model_dump(mode="json"),
        "primary_clock": receipt.recorded_at.isoformat(),
        "repeat_clock": clock[0].isoformat(),
        "repeat_receipt_hash": repeat.content_hash,
        "seen_receipt_hash": seen.content_hash if seen is not None else None,
        "cancellation_receipt_hash": cancellation.content_hash
        if cancellation is not None
        else None,
        "business_report_hash": business_report_hash,
        "business_cancellation_hash": business_cancellation.content_hash
        if business_cancellation is not None
        else None,
        "execute_calls": execute_calls,
        "workflow_calls": workflow_calls,
        "network_attempts": network_attempts,
        "fixture_kind": "TRANSPORT_NEGATIVE_FIXTURE",
        "python_executable": sys.executable,
        "python_flags": {
            name: getattr(sys.flags, name)
            for name in (
                "isolated",
                "ignore_environment",
                "no_user_site",
                "safe_path",
                "hash_randomization",
            )
        },
        "qualification_eligibility": "NOT_QUALIFIED",
    }
    atomic_write_bytes(channel / "negative-observation.json", canonical_json_bytes(observation))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=NEGATIVE_CASES, required=True)
    args = parser.parse_args()
    try:
        run_negative_probe(args.profile_hash, args.case)
    except Exception as error:
        print(
            canonical_json_bytes(
                {"negative": "FAILED", "error_type": type(error).__name__}
            ).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
