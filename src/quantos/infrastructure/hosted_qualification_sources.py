"""Original manager-source bindings for a read-only qualification verifier.

The caller supplies the trusted deployment root independently of the uploaded bundle.
No producer's source label, verdict, or copied transcript establishes that origin.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from quantos.artifacts.store import opened_directory
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedAgentExchange, HostedAgentResponse, parse_hosted_contract
from quantos.contracts.hosted_qualification import (
    HostedManagerExport,
    HostedManagerExportFile,
    HostedQualificationManifest,
    HostedQualificationRoot,
    HostedRawInventory,
)
from quantos.infrastructure.hosted_deployment import KnownValueGuard, install_inventory
from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore
from quantos.infrastructure.hosted_manager import HostedManagedDeployment, read_managed_deployment
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    MAX_MANAGER_EXPORT_BYTES,
    HostedQualificationError,
    digest_relative,
    read_relative,
    verify_protocol_root,
)


@dataclass(frozen=True)
class HostedVerifiedSources:
    deployment: HostedManagedDeployment
    files: Mapping[str, HostedManagerExportFile]
    export_hash: str

    def root_origin(self, root: HostedQualificationRoot, inventory: HostedRawInventory) -> Path:
        """Every exported root file must retain its path under one original source root."""
        prefixes: set[str] = set()
        for item in inventory.files:
            exported = self.files.get(f"{root.logical_path}/{item.logical_path}")
            suffix = "/" + item.logical_path
            if (
                exported is None
                or exported.sha256 != item.sha256
                or exported.size_bytes != item.size_bytes
                or not exported.source_path.endswith(suffix)
            ):
                raise HostedQualificationError("case root is not bound to original manager files")
            prefixes.add(exported.source_path[: -len(suffix)])
        if len(prefixes) != 1:
            raise HostedQualificationError("case root combines unrelated original sources")
        return self.deployment.root / prefixes.pop()


def read_manager_export(root: Path, logical_path: str) -> HostedManagerExport:
    """Read only a canonical typed source index under its dedicated finite bound.

    The caller must independently bind the index to the original deployment
    and every referenced file.
    """
    return parse_hosted_contract(
        read_relative(root, logical_path, max_bytes=MAX_MANAGER_EXPORT_BYTES),
        HostedManagerExport,
        max_bytes=MAX_MANAGER_EXPORT_BYTES,
    )


def verify_manager_export(
    bundle: Path, manifest: HostedQualificationManifest, manager_root: Path
) -> HostedVerifiedSources:
    """Bind all case bytes to an external original deployment and its retained export."""
    if manifest.manager_export_hash is None:
        raise HostedQualificationError("original manager export is unavailable")
    if not manager_root.is_absolute():
        raise HostedQualificationError("original manager root must be supplied as an absolute path")
    bundle_absolute, manager_absolute = bundle.resolve(), manager_root.resolve()
    if (
        bundle_absolute == manager_absolute
        or bundle_absolute in manager_absolute.parents
        or manager_absolute in bundle_absolute.parents
    ):
        raise HostedQualificationError("bundle and original manager roots must be independent")
    exported = read_manager_export(bundle, "manager-export.json")
    encoded = exported.canonical_bytes()
    digest = sha256_bytes(encoded)
    if (
        digest != manifest.manager_export_hash
        or read_relative(manager_root, f"evidence/{digest}", max_bytes=MAX_MANAGER_EXPORT_BYTES)
        != encoded
    ):
        raise HostedQualificationError("manager export is not the retained original record")
    deployment = read_managed_deployment(manager_root, manifest.deployment_profile_hash)
    if (
        exported.deployment_profile_hash != deployment.profile.content_hash
        or exported.exact_commit != deployment.profile.exact_commit
        or manifest.exact_commit != deployment.profile.exact_commit
        or manifest.lockfile_hash != deployment.profile.lock_hash
        or install_inventory(deployment.paths.install) != deployment.install
        or install_inventory(deployment.paths.provenance).content_hash
        != deployment.profile.provenance_inventory_hash
    ):
        raise HostedQualificationError("original manager installation/provenance differs")
    expected = {
        item.logical_path: item
        for item in manifest.files
        if item.logical_path not in {"manager-export.json", "verifier-result.json"}
    }
    records = {item.bundle_path: item for item in exported.files}
    if set(records) != set(expected):
        raise HostedQualificationError("manager export does not bind the exact case file set")
    for path, file in expected.items():
        record = records[path]
        if (
            (record.sha256, record.size_bytes) != (file.sha256, file.size_bytes)
            or digest_relative(manager_root, record.source_path) != (file.sha256, file.size_bytes)
            or digest_relative(bundle, path) != (file.sha256, file.size_bytes)
        ):
            raise HostedQualificationError("exported file differs from original manager bytes")
    return HostedVerifiedSources(deployment, MappingProxyType(records), digest)


def verify_original_live_source(sources: HostedVerifiedSources) -> tuple[str, ...]:
    """Verify actual saved proposals from the original manager's direct CLI captures."""
    deployment = sources.deployment
    protocol = deployment.paths.authority / "protocol"
    hashes = set(verify_protocol_root(protocol, deployment.bundle.campaign.content_hash))
    state = HostedProtocolStore(protocol).snapshot(
        deployment.bundle.campaign.content_hash, recover=False
    )
    evidence = deployment.root / "evidence"
    # Check existence first: the verifier must not create a missing evidence root.
    with opened_directory(evidence):
        pass
    store = TrustedLauncherEvidenceStore(evidence, guard=KnownValueGuard(()))
    if not state.requests:
        raise HostedQualificationError("original live model requests are absent")
    for request in state.requests:
        receipt = state.accepted_receipt(request.content_hash)
        if receipt is None or receipt.accepted_exchange_hash is None:
            raise HostedQualificationError("original live handoff is incomplete")
        exchange = state.artifact(receipt.accepted_exchange_hash, HostedAgentExchange)
        response = state.artifact(exchange.response_hash, HostedAgentResponse)
        record = store.verify_response_source(
            response,
            request=request,
            spec=state.spec,
            profile=deployment.profile,
            initial_inventory=deployment.initial_projection,
            projection_root=deployment.root / "request-projections" / request.content_hash,
            configuration=deployment.launcher_configuration,
        )
        hashes.update(
            (record.content_hash, record.projection_fact_hash, record.isolation_observation_hash)
        )
        if record.raw_output_hash is not None:
            hashes.add(record.raw_output_hash)
    return tuple(sorted(hashes))
