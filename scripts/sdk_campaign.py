#!/usr/bin/env python3
"""Offline controls and explicitly invoked steps for the bounded Codex SDK campaign."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantos.application.hosted_campaign import HostedCampaignApplicationService  # noqa: E402
from quantos.application.hosted_inputs import load_hosted_campaign_application  # noqa: E402
from quantos.application.hosted_protocol import (  # noqa: E402
    HostedProtocolService,
    scan_protocol_artifact,
)
from quantos.application.sdk_producer import (  # noqa: E402
    SdkCampaignProducer,
    require_sdk_storage_reservation,
)
from quantos.artifacts.store import (  # noqa: E402
    ArtifactIntegrityError,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import sha256_bytes  # noqa: E402
from quantos.contracts.hosted import parse_hosted_contract, strict_json_object  # noqa: E402
from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration  # noqa: E402
from quantos.contracts.sdk_producer import (  # noqa: E402
    SdkAgentRequest,
    SdkCampaignSpec,
    parse_agent_request,
    parse_campaign_spec,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore  # noqa: E402

_HASH = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_MAX = 1_048_576
_SPEC_MAX = 1_048_576
_CONFIG_MAX = 65_536


def _read_pinned(path_text: str, digest: str, cap: int, label: str) -> bytes:
    if _HASH.fullmatch(digest) is None:
        raise ValueError(f"invalid {label} SHA256")
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    with opened_directory(path.parent) as parent_fd:
        data = read_regular_bytes_at(parent_fd, path.name, max_bytes=cap)
    if sha256_bytes(data) != digest:
        raise ValueError(f"{label} byte hash or size mismatch")
    parsed = strict_json_object(data, max_bytes=cap)
    scan_protocol_artifact(parsed)
    return data


def _inputs(args: argparse.Namespace) -> tuple[SdkAgentRequest, SdkCampaignSpec]:
    req_bytes = _read_pinned(args.request, args.request_sha256, _REQUEST_MAX, "request")
    spec_bytes = _read_pinned(args.spec, args.spec_sha256, _SPEC_MAX, "spec")
    request = parse_agent_request(req_bytes, max_bytes=_REQUEST_MAX)
    spec = parse_campaign_spec(spec_bytes, max_bytes=_SPEC_MAX)
    if not isinstance(request, SdkAgentRequest) or not isinstance(spec, SdkCampaignSpec):
        raise ValueError("SDK successor request/spec required")
    if request.canonical_bytes() != req_bytes or spec.canonical_bytes() != spec_bytes:
        raise ValueError("request/spec must use canonical contract bytes")
    return request, spec


def _identity(request: SdkAgentRequest, spec: SdkCampaignSpec) -> dict[str, str]:
    return {
        "campaign_hash": request.campaign_hash,
        "request_hash": request.content_hash,
        "spec_hash": spec.content_hash,
    }


def _producer(args: argparse.Namespace) -> SdkCampaignProducer:
    root = Path(args.evidence_root)
    if not root.is_absolute():
        raise ValueError("evidence root must be absolute")
    return SdkCampaignProducer(root)


def _runtime_preflight(spec: SdkCampaignSpec) -> None:
    expected = (spec.sdk_profile.sdk_version, spec.sdk_profile.runtime_package_version)
    try:
        actual = (
            importlib.metadata.version("openai-codex"),
            importlib.metadata.version("openai-codex-cli-bin"),
        )
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("accepted SDK/runtime distributions are not installed") from exc
    if actual != expected:
        raise ValueError("accepted SDK/runtime installation required before live operation")


def _service(args: argparse.Namespace, spec: SdkCampaignSpec) -> HostedCampaignApplicationService:
    config_bytes = _read_pinned(
        args.loader_config,
        args.loader_config_sha256,
        _CONFIG_MAX,
        "loader configuration",
    )
    config = parse_hosted_contract(
        config_bytes, HostedBusinessLoaderConfiguration, max_bytes=_CONFIG_MAX
    )
    if config.canonical_bytes() != config_bytes:
        raise ValueError("loader configuration must use canonical contract bytes")
    holder: list[HostedCampaignApplicationService] = []

    def verify_inputs(candidate: Any) -> None:
        if not holder:
            raise ArtifactIntegrityError("campaign application is not initialized")
        holder[0].verify_registered_inputs(candidate)

    protocol = HostedProtocolService(
        HostedProtocolStore(Path(args.protocol_root)), verify_inputs=verify_inputs
    )
    service = load_hosted_campaign_application(
        config,
        protocol,
        Path(args.business_lock_root),
        deployment_profile_hash=spec.deployment_profile_hash,
        sdk_spec=spec,
    )
    holder.append(service)
    return service


def _add_pinned_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--evidence-root", required=True)


def _add_service_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", required=True)
    parser.add_argument("--spec-sha256", required=True)
    parser.add_argument("--loader-config", required=True)
    parser.add_argument("--loader-config-sha256", required=True)
    parser.add_argument("--protocol-root", required=True)
    parser.add_argument("--business-lock-root", required=True)
    parser.add_argument("--evidence-root", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "status", "replay", "launch"):
        command = sub.add_parser(name)
        _add_pinned_inputs(command)
    for name in ("start", "business-status", "resume", "step"):
        command = sub.add_parser(name)
        _add_service_inputs(command)
        if name in {"resume", "step"}:
            command.add_argument("--expected-new-bytes", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command in {"prepare", "status", "replay", "launch"}:
            request, spec = _inputs(args)
            producer = _producer(args)
            identity = _identity(request, spec)
            if args.command == "prepare":
                reservation = producer.prepare(request, spec)
                result: object = {**identity, "reservation_hash": reservation.content_hash}
            elif args.command == "status":
                result = {**identity, "state": producer.status(request, spec)}
            elif args.command == "replay":
                response = producer.replay(request, spec)
                result = {
                    **identity,
                    "response_hash": response.content_hash,
                    "proposal_hash": response.proposal_hash,
                }
            else:
                request_state = producer.status(request, spec)
                if request_state in {"NOT_PREPARED", "PREPARED"}:
                    _runtime_preflight(spec)
                response = producer.launch(request, spec)
                result = {
                    **identity,
                    "response_hash": response.content_hash,
                    "proposal_hash": response.proposal_hash,
                }
        else:
            spec_bytes = _read_pinned(args.spec, args.spec_sha256, _SPEC_MAX, "spec")
            spec = parse_campaign_spec(spec_bytes, max_bytes=_SPEC_MAX)
            if not isinstance(spec, SdkCampaignSpec) or spec.canonical_bytes() != spec_bytes:
                raise ValueError("canonical SDK successor spec required")
            producer = _producer(args)
            config_bytes = _read_pinned(
                args.loader_config,
                args.loader_config_sha256,
                _CONFIG_MAX,
                "loader configuration",
            )
            config = parse_hosted_contract(
                config_bytes, HostedBusinessLoaderConfiguration, max_bytes=_CONFIG_MAX
            )
            if config.canonical_bytes() != config_bytes:
                raise ValueError("loader configuration must use canonical contract bytes")
            if args.command in {"resume", "step"}:
                require_sdk_storage_reservation(
                    (
                        Path(args.evidence_root),
                        Path(args.protocol_root),
                        Path(args.business_lock_root),
                        Path(config.input_root),
                        Path(config.business_root),
                    ),
                    args.expected_new_bytes,
                )
            service = _service(args, spec)
            if args.command == "start":
                state = service.start(spec.content_hash)
            elif args.command == "business-status":
                state = service.status(spec.campaign_hash)
            elif args.command == "resume":
                state = service.resume(spec.campaign_hash)
            else:
                pending = service.pending(spec.campaign_hash)
                if pending is not None:
                    request_state = producer.status(pending, spec)
                    if request_state in {"NOT_PREPARED", "PREPARED"}:
                        _runtime_preflight(spec)
                state = producer.step(
                    service,
                    spec.campaign_hash,
                    expected_new_bytes=args.expected_new_bytes,
                )
            result = {
                "campaign_hash": spec.campaign_hash,
                "spec_hash": spec.content_hash,
                "state": getattr(state, "state", "UNKNOWN"),
            }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        # Deliberately omit exception text: input paths and contract values stay private.
        print(json.dumps({"error": "operation_rejected"}, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
