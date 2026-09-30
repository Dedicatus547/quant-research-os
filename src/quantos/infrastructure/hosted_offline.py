"""Fixed offline management entrypoint; never offered by the research channel."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_deployment import HostedDeploymentProfile, HostedServiceConfiguration
from quantos.contracts.hosted_inputs import (
    HostedBusinessLoaderConfiguration,
    HostedFrozenBusinessInputs,
)
from quantos.infrastructure.hosted_business_verification import verify_hosted_business_root
from quantos.infrastructure.hosted_replay import SavedHostedProtocol
from quantos.infrastructure.hosted_service import (
    bootstrap_hosted_service,
    hydrate_service_capabilities,
    read_hashed_configuration,
)
from quantos.infrastructure.hosted_verification import raw_inventory, verify_raw_inventory
from quantos.research.qlib import QlibWorkflowResearchService


def run_offline(profile_hash: str, mode: str) -> None:
    if mode not in {"RECEIPT_REUSE", "REEXECUTE"}:
        raise ValueError("unknown fixed offline mode")
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
    authority = Path("/authority")
    source_root = authority / "saved-protocol" if mode == "REEXECUTE" else authority / "protocol"
    if mode == "REEXECUTE" and any(
        (authority / name).exists() or (authority / name).is_symlink()
        for name in ("protocol", "business", "business-locks", "offline-observation.json")
    ):
        raise ArtifactIntegrityError("offline reexecution target is not a fresh root")
    source_before = raw_inventory(source_root)
    saved = SavedHostedProtocol.load(source_root, bundle.campaign.content_hash)
    execute_calls: list[str] = []
    workflow_calls: list[str] = []
    network_attempts: list[str] = []
    original_execute = QuantosResearchExecutionAdapter.execute
    original_workflow = QlibWorkflowResearchService.run

    def observed_execute(self: QuantosResearchExecutionAdapter, request: Any) -> Any:
        execute_calls.append(request.execution_identity)
        if mode == "RECEIPT_REUSE":
            raise ArtifactIntegrityError("receipt reuse attempted execution")
        return original_execute(self, request)

    def observed_workflow(self: QlibWorkflowResearchService, *args: Any, **kwargs: Any) -> Any:
        workflow_calls.append(str(kwargs["execution_identity"]))
        if mode == "RECEIPT_REUSE":
            raise ArtifactIntegrityError("receipt reuse attempted Qlib Workflow")
        return original_workflow(self, *args, **kwargs)

    def denied_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        network_attempts.append("SOCKET_CONNECT")
        raise ArtifactIntegrityError("offline transport is blocked")

    with (
        patch.object(QuantosResearchExecutionAdapter, "execute", observed_execute),
        patch.object(QlibWorkflowResearchService, "run", observed_workflow),
        patch.object(socket.socket, "connect", denied_network),
        patch.object(socket.socket, "connect_ex", denied_network),
        patch.object(socket, "create_connection", denied_network),
    ):
        hydrate_service_capabilities(profile_hash)
        service = bootstrap_hosted_service(
            profile_hash,
            protocol_clock=saved.clock if mode == "REEXECUTE" else None,
            verify_journal_entry=saved.verify_entry if mode == "REEXECUTE" else None,
        )
        application = service.application
        if not isinstance(application, HostedCampaignApplicationService):
            raise ArtifactIntegrityError("offline application factory differs")
        if mode == "REEXECUTE":
            saved.run(application)
        else:
            application.resume(bundle.campaign.content_hash)
        facts = verify_hosted_business_root(
            authority,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=Path("/inputs"),
            provenance_workspace=Path("/provenance"),
        )
    verify_raw_inventory(source_root, source_before)
    if network_attempts or any(
        name == "tushare" or name.startswith(("openai", "quantos.agents.openai"))
        for name in sys.modules
    ):
        raise ArtifactIntegrityError("offline run imported or attempted forbidden transport")
    if mode == "REEXECUTE" and (
        tuple(sorted(execute_calls)) != facts.execution_identities
        or len(set(execute_calls)) != len(execute_calls)
        or not workflow_calls
    ):
        raise ArtifactIntegrityError(
            "fresh root did not independently execute its full denominator"
        )
    observation = {
        "schema_version": "hosted-offline-observation/v1",
        "mode": mode,
        "deployment_profile_hash": profile_hash,
        "campaign_hash": bundle.campaign.content_hash,
        "source_inventory_hash": source_before.content_hash,
        "execute_calls": execute_calls,
        "workflow_calls": workflow_calls,
        "network_attempts": network_attempts,
        "python_executable": sys.executable,
        "python_hash_seed_environment": os.environ.get("PYTHONHASHSEED"),
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
        "numeric_environment": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "report_hash": facts.report.content_hash,
        "qualification_eligibility": "NOT_QUALIFIED",
    }
    atomic_write_bytes(authority / "offline-observation.json", canonical_json_bytes(observation))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--mode", choices=("RECEIPT_REUSE", "REEXECUTE"), required=True)
    args = parser.parse_args()
    try:
        run_offline(args.profile_hash, args.mode)
    except Exception as error:
        print(
            canonical_json_bytes({"offline": "FAILED", "error_type": type(error).__name__}).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
