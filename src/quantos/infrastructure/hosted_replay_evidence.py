"""Management-only observation capture after actual offline native runs."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import HostedQualificationRoot, HostedRawInventory
from quantos.infrastructure.hosted_business_verification import (
    c11_business_projection_paths,
    principal_business_inventory,
    verify_hosted_business_root,
)
from quantos.infrastructure.hosted_deployment import KnownValueGuard
from quantos.infrastructure.hosted_manager import HostedManagedDeployment
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_replay_verification import TAMPER_SCHEMAS, verify_tamper_case
from quantos.infrastructure.hosted_verification import (
    MAX_SINGLE_FILE_BYTES,
    compare_verified_principal_roots,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def capture_replay_comparison(
    deployment: HostedManagedDeployment, authority_a: Path, authority_b: Path
) -> Path:
    """Retain raw inventories/runtime observations and each permitted timestamp projection."""
    if authority_a == authority_b or deployment.paths.authority in (authority_a, authority_b):
        raise ArtifactIntegrityError("comparison needs two new original native roots")
    raw = [raw_inventory(root) for root in (authority_a, authority_b)]
    principal: list[HostedRawInventory] = []
    approved: list[frozenset[str]] = []
    roots: list[dict[str, object]] = []
    for authority, inventory in zip((authority_a, authority_b), raw, strict=True):
        facts = verify_hosted_business_root(
            authority,
            deployment.bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.root / "inputs",
            provenance_workspace=deployment.paths.provenance,
        )
        identities, runtime = principal_business_inventory(authority, facts)
        principal.append(identities)
        approved.append(c11_business_projection_paths(authority, facts, deployment.bundle))
        roots.append(
            {
                "authority_root": str(authority),
                "raw_inventory": inventory.model_dump(mode="json"),
                "principal_inventory": identities.model_dump(mode="json"),
                "runtime_inventory": runtime.model_dump(mode="json"),
            }
        )
    if approved[0] != approved[1]:
        raise ArtifactIntegrityError("referenced C11 authority paths differ")
    projections = compare_verified_principal_roots(
        authority_a,
        authority_b,
        raw[0],
        raw[1],
        principal[0],
        principal[1],
        allowed_projection_paths=approved[0],
    )
    encoded = canonical_json_bytes(
        {
            "schema_version": "hosted-manager-replay-comparison/v1",
            "deployment_profile_hash": deployment.profile.content_hash,
            "campaign_hash": deployment.bundle.campaign.content_hash,
            "roots": roots,
            "projections": [item.model_dump(mode="json") for item in projections],
            "qualification_eligibility": "NOT_QUALIFIED",
        }
    )
    KnownValueGuard((deployment.capability,))(encoded)
    path = deployment.root / "evidence" / f"replay-comparison-{sha256_bytes(encoded)}.json"
    atomic_write_bytes(path, encoded)
    return path


def capture_replay_tampers(deployment: HostedManagedDeployment) -> Path:
    """Preserve five separate corrupted copies; keep original native authority unchanged."""
    authority = deployment.paths.authority
    baseline = raw_inventory(authority)
    destinations = deployment.root / "qualification-cases/Q09/tamper"
    if destinations.exists() or destinations.is_symlink():
        raise ArtifactIntegrityError("tamper attempt already exists; retain original failure")
    guard = KnownValueGuard((deployment.capability,))
    targets: dict[str, str] = {}
    for file in baseline.files:
        if not file.logical_path.endswith(".json") or file.size_bytes > 16_777_216:
            continue
        data = read_relative(authority, file.logical_path)
        try:
            value = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        for kind, schema in TAMPER_SCHEMAS.items():
            if value.get("schema_version") != schema or kind in targets:
                continue
            if kind == "RECEIPT" and "/execution-records/identities/" not in file.logical_path:
                continue
            targets[kind] = file.logical_path
    if set(targets) != set(TAMPER_SCHEMAS):
        raise ArtifactIntegrityError("native tamper authority denominator is incomplete")
    sources = HostedVerifiedSources(deployment, MappingProxyType({}), "0" * 64)
    cases: list[dict[str, object]] = []
    for kind in TAMPER_SCHEMAS:
        name = kind.lower()
        target = destinations / name / "authority"
        target.mkdir(parents=True, mode=0o700)
        for item in baseline.files:
            data = read_relative(authority, item.logical_path, max_bytes=MAX_SINGLE_FILE_BYTES)
            guard(data)
            atomic_write_bytes(target / item.logical_path, data)
        logical = targets[kind]
        value = strict_json_object(read_relative(authority, logical), max_bytes=16_777_216)
        corrupted = canonical_json_bytes(
            {**value, "schema_version": "tampered/" + TAMPER_SCHEMAS[kind]}
        )
        guard(corrupted)
        # The copied canonical object is never published back to live authority.
        # Replacing it is the explicit mutation of this newly allocated test root.
        (target / logical).unlink()
        atomic_write_bytes(target / logical, corrupted)
        inventory = raw_inventory(target)
        atomic_write_bytes(target.parent / "inventory.json", inventory.canonical_bytes())
        error = verify_tamper_case(
            authority,
            target,
            logical_path=logical,
            kind=kind,
            baseline_inventory=baseline,
            altered_inventory=inventory,
            sources=sources,
        )
        root = HostedQualificationRoot(
            name=name,
            logical_path=f"cases/Q09/tamper/{name}/authority",
            campaign_hash=deployment.bundle.campaign.content_hash,
            raw_inventory_path=f"cases/Q09/tamper/{name}/inventory.json",
        )
        cases.append(
            {
                "kind": kind,
                "logical_path": logical,
                "root": root.model_dump(mode="json"),
                "error_type": error,
            }
        )
        verify_raw_inventory(authority, baseline)
    encoded = canonical_json_bytes(
        {
            "schema_version": "hosted-manager-replay-tamper/v1",
            "deployment_profile_hash": deployment.profile.content_hash,
            "baseline_inventory_hash": baseline.content_hash,
            "cases": cases,
            "qualification_eligibility": "NOT_QUALIFIED",
        }
    )
    guard(encoded)
    path = deployment.root / "evidence" / f"replay-tamper-{sha256_bytes(encoded)}.json"
    atomic_write_bytes(path, encoded)
    return path
