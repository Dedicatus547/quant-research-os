"""Source-bound Q09/Q10 predicates over actual native offline invocations."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.application.campaigns import CampaignGovernanceError
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import (
    HostedQualificationCase,
    HostedQualificationRoot,
    HostedRawInventory,
)
from quantos.contracts.refs import validate_logical_path
from quantos.infrastructure.hosted_business_verification import (
    HostedVerifiedBusiness,
    c11_business_projection_paths,
    principal_business_inventory,
    verify_hosted_business_root,
)
from quantos.infrastructure.hosted_offline_verification import verify_offline_manager_run
from quantos.infrastructure.hosted_qualification_sources import (
    HostedVerifiedSources,
    verify_original_live_source,
)
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    compare_verified_principal_roots,
    read_relative,
    verify_raw_inventory,
)

TAMPER_SCHEMAS = {
    "REQUEST": "hosted-agent-request/v1",
    "RESPONSE": "hosted-agent-response/v1",
    "RECEIPT": "autonomous-execution-receipt/v1",
    "RESULT": "research-result-manifest/v1",
    "EVENT": "research-campaign-event/v1",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def _business(authority: Path, sources: HostedVerifiedSources) -> HostedVerifiedBusiness:
    deployment = sources.deployment
    return verify_hosted_business_root(
        authority,
        deployment.bundle,
        deployment_profile_hash=deployment.profile.content_hash,
        input_root=deployment.root / "inputs",
        provenance_workspace=deployment.paths.provenance,
    )


def _observation(
    bundle: Path, case: HostedQualificationCase, schema: str
) -> tuple[bytes, dict[str, object]]:
    matches: list[tuple[bytes, dict[str, object]]] = []
    for path in case.evidence_paths:
        data = read_relative(bundle, path)
        try:
            value = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        if value.get("schema_version") == schema:
            _require(canonical_json_bytes(value) == data, "replay observation is not canonical")
            matches.append((data, value))
    _require(len(matches) == 1, "replay manager observation is missing or ambiguous")
    return matches[0]


def verify_q10(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Recompute both complete pipelines and compare only bottom-up verified principal files."""
    _require(len(case.roots) == 2, "Q10 needs two independent native authority roots")
    checked = set(verify_original_live_source(sources))
    _require(
        checked <= {item.sha256 for item in sources.files.values()},
        "Q10 original model sources were not fully exported",
    )
    authorities: list[Path] = []
    originals: list[Path] = []
    raw: list[HostedRawInventory] = []
    principal: list[HostedRawInventory] = []
    approved: list[frozenset[str]] = []
    roots: list[dict[str, object]] = []
    for root in case.roots:
        authority = bundle / root.logical_path
        inventory = HostedRawInventory.model_validate_json(
            read_relative(bundle, root.raw_inventory_path)
        )
        original = sources.root_origin(root, inventory)
        _require(original not in originals, "Q10 reused an original authority root")
        facts = _business(authority, sources)
        checked.update(
            verify_offline_manager_run(
                bundle,
                case,
                sources,
                authority=authority,
                original_authority=original,
                mode="REEXECUTE",
                facts=facts,
            )
        )
        identities, runtime = principal_business_inventory(authority, facts)
        approved.append(c11_business_projection_paths(authority, facts, sources.deployment.bundle))
        authorities.append(authority)
        originals.append(original)
        raw.append(inventory)
        principal.append(identities)
        roots.append(
            {
                "authority_root": str(original),
                "raw_inventory": inventory.model_dump(mode="json"),
                "principal_inventory": identities.model_dump(mode="json"),
                "runtime_inventory": runtime.model_dump(mode="json"),
            }
        )
        checked.update(facts.artifact_hashes)
    _require(approved[0] == approved[1], "Q10 referenced C11 manifests differ")
    projections = compare_verified_principal_roots(
        authorities[0],
        authorities[1],
        raw[0],
        raw[1],
        principal[0],
        principal[1],
        allowed_projection_paths=approved[0],
    )
    encoded, comparison = _observation(bundle, case, "hosted-manager-replay-comparison/v1")
    expected = {
        "schema_version": "hosted-manager-replay-comparison/v1",
        "deployment_profile_hash": sources.deployment.profile.content_hash,
        "campaign_hash": sources.deployment.bundle.campaign.content_hash,
        "roots": roots,
        "projections": [item.model_dump(mode="json") for item in projections],
        "qualification_eligibility": "NOT_QUALIFIED",
    }
    _require(
        comparison == expected, "Q10 comparison did not retain full raw/runtime/projection facts"
    )
    checked.add(sha256_bytes(encoded))
    checked.update(item.projected_hash for item in projections)
    return tuple(sorted(checked))


def verify_tamper_case(
    baseline: Path,
    altered: Path,
    *,
    logical_path: str,
    kind: str,
    baseline_inventory: HostedRawInventory,
    altered_inventory: HostedRawInventory,
    sources: HostedVerifiedSources,
) -> str:
    """Prove one changed authoritative file, then independently reproduce semantic rejection."""
    _require(kind in TAMPER_SCHEMAS, "Q09 tamper kind is not frozen")
    validate_logical_path(logical_path)
    verify_raw_inventory(baseline, baseline_inventory)
    verify_raw_inventory(altered, altered_inventory)
    before = {item.logical_path: item for item in baseline_inventory.files}
    after = {item.logical_path: item for item in altered_inventory.files}
    _require(
        set(before) == set(after)
        and [path for path in sorted(before) if before[path] != after[path]] == [logical_path],
        "Q09 tamper was not exactly one original file",
    )
    original = strict_json_object(read_relative(baseline, logical_path), max_bytes=16_777_216)
    _require(
        original.get("schema_version") == TAMPER_SCHEMAS[kind],
        "Q09 changed the wrong authority type",
    )
    # An invalid schema is an explicit typed corruption, not a new valid proposal
    # or accepted source. This also exercises manifest readers that accept JSON
    # whitespace while verifying their logical content hash.
    _require(
        read_relative(altered, logical_path)
        == canonical_json_bytes({**original, "schema_version": "tampered/" + TAMPER_SCHEMAS[kind]}),
        "Q09 mutation differs from the fixed typed corruption",
    )
    try:
        _business(altered, sources)
    except (
        ArtifactIntegrityError,
        HostedQualificationError,
        AutonomousOrchestrationError,
        CampaignGovernanceError,
        OSError,
        ValueError,
    ) as error:
        verify_raw_inventory(altered, altered_inventory)
        return type(error).__name__
    raise HostedQualificationError("Q09 corrupted authority was accepted")


def verify_q09(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    _require(len(case.roots) == 1, "Q09 requires original native receipt-reuse authority")
    checked = set(verify_original_live_source(sources))
    _require(
        checked <= {item.sha256 for item in sources.files.values()},
        "Q09 original model sources were not fully exported",
    )
    root = case.roots[0]
    authority = bundle / root.logical_path
    inventory = HostedRawInventory.model_validate_json(
        read_relative(bundle, root.raw_inventory_path)
    )
    original = sources.root_origin(root, inventory)
    facts = _business(authority, sources)
    checked.update(
        verify_offline_manager_run(
            bundle,
            case,
            sources,
            authority=authority,
            original_authority=original,
            mode="RECEIPT_REUSE",
            facts=facts,
        )
    )
    encoded, observation = _observation(bundle, case, "hosted-manager-replay-tamper/v1")
    _require(
        observation.get("deployment_profile_hash") == sources.deployment.profile.content_hash
        and observation.get("baseline_inventory_hash") == inventory.content_hash,
        "Q09 tamper baseline differs from receipt reuse",
    )
    cases = observation.get("cases")
    _require(
        isinstance(cases, list) and len(cast(list[object], cases)) == 5,
        "Q09 tamper matrix is incomplete",
    )
    kinds: list[str] = []
    for value in cast(list[object], cases):
        _require(isinstance(value, dict), "Q09 tamper observation is malformed")
        item = cast(dict[str, object], value)
        kind = cast(str, item["kind"])
        altered_root = HostedQualificationRoot.model_validate(item["root"])
        _require(
            altered_root.logical_path.startswith("cases/Q09/tamper/")
            and altered_root.campaign_hash == root.campaign_hash,
            "Q09 tamper root escaped its scenario",
        )
        altered_inventory = HostedRawInventory.model_validate_json(
            read_relative(bundle, altered_root.raw_inventory_path)
        )
        sources.root_origin(altered_root, altered_inventory)
        error = verify_tamper_case(
            authority,
            bundle / altered_root.logical_path,
            kind=kind,
            logical_path=cast(str, item["logical_path"]),
            baseline_inventory=inventory,
            altered_inventory=altered_inventory,
            sources=sources,
        )
        _require(item.get("error_type") == error, "Q09 observed corruption rejection differs")
        checked.add(altered_inventory.content_hash)
        kinds.append(kind)
    _require(
        tuple(kinds) == tuple(TAMPER_SCHEMAS), "Q09 tamper kinds are missing/repeated/reordered"
    )
    checked.update(facts.artifact_hashes)
    checked.add(sha256_bytes(encoded))
    return tuple(sorted(checked))
