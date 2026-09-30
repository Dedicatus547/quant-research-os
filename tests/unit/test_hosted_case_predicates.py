"""Scenario semantic negative tests; synthetic sources cannot grant qualification."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_campaign import _fixture

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure.hosted_case_predicates import verify_q01
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "snapshot",
        "pending",
        "queries",
        "status",
        "same_pid",
        "no_process_source",
        "missing_observation",
        "summary",
        "summary_hash",
        "summary_expiry",
        "summary_extra",
    ],
)
def test_q01_reconciles_disk_and_queries_instead_of_claimed_verdict(
    tmp_path: Path, mutation: str | None
) -> None:
    component = _fixture(tmp_path / "component")
    status = component.service.start(component.spec.content_hash)
    request = component.service.pending(component.spec.campaign_hash)
    assert request is not None
    inventory = raw_inventory(component.root)
    bundle = tmp_path / "bundle"
    roots = []
    for name in ("before", "after"):
        path = f"cases/Q01/{name}/authority"
        shutil.copytree(component.root, bundle / path)
        inventory_path = f"cases/Q01/{name}-inventory.json"
        (bundle / inventory_path).write_bytes(inventory.canonical_bytes())
        roots.append(
            HostedQualificationRoot(
                name=name,
                logical_path=path,
                campaign_hash=component.spec.campaign_hash,
                raw_inventory_path=inventory_path,
            )
        )
    queries = [
        request.model_dump(mode="json"),
        status.model_dump(mode="json"),
        status.model_dump(mode="json"),
    ] * 2
    fact = {
        "schema_version": "hosted-manager-suspend-restart/v1",
        "deployment_profile_hash": "d" * 64,
        "before_inventory": inventory.model_dump(mode="json"),
        "after_inventory": inventory.model_dump(mode="json"),
        "pending_before": request.model_dump(mode="json"),
        "queries": queries,
        # These IDs are explicit synthetic semantic fixtures. The real origin
        # verifier requires frozen install/proc bytes before this predicate runs.
        "before_wrapper_pid": 33,
        "after_wrapper_pid": 34,
        "verdict": "PASS",
    }
    if mutation is not None and mutation.startswith("summary"):
        summary = {
            "status": "PENDING",
            "campaign_hash": request.campaign_hash,
            "request_hash": request.content_hash,
            "expires_at": request.expires_at.isoformat(),
        }
        if mutation == "summary_hash":
            summary["request_hash"] = "f" * 64
        elif mutation == "summary_expiry":
            summary["expires_at"] = "2000-01-01T00:00:00+00:00"
        elif mutation == "summary_extra":
            summary["ordinal"] = request.transport_ordinal
        fact["pending_before"] = summary
        queries[0] = queries[3] = summary
    if mutation == "snapshot":
        fact["after_inventory"] = {"files": []}
    elif mutation == "pending":
        fact["pending_before"] = component.spec.model_dump(mode="json")
    elif mutation == "queries":
        fact["queries"] = queries[:3]
    elif mutation == "status":
        queries[1] = status.model_copy(update={"state": "COMPLETED"}).model_dump(mode="json")
    elif mutation == "same_pid":
        fact["after_wrapper_pid"] = 33
    elif mutation == "missing_observation":
        fact["schema_version"] = "untrusted-summary/v1"
    evidence = {
        "cases/Q01/observations.json": ("evidence/restart-observation", canonical_json_bytes(fact)),
        "cases/Q01/start-before.json": (
            "evidence/service-start-before.json",
            canonical_json_bytes({"manager_child_observation": {"wrapper_pid": 33}}),
        ),
        "cases/Q01/start-after.json": (
            "evidence/service-start-after.json",
            canonical_json_bytes({"manager_child_observation": {"wrapper_pid": 34}}),
        ),
    }
    records = {}
    for logical, (source, data) in evidence.items():
        (bundle / logical).write_bytes(data)
        records[logical] = HostedManagerExportFile(
            bundle_path=logical, source_path=source, sha256=sha256_bytes(data), size_bytes=len(data)
        )
    if mutation == "no_process_source":
        item = records["cases/Q01/start-after.json"]
        records[item.bundle_path] = item.model_copy(
            update={"source_path": "evidence/host-self-report.json"}
        )
    case = HostedQualificationCase(
        case_id="Q01", roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    sources = HostedVerifiedSources(
        SimpleNamespace(spec=component.spec, profile=SimpleNamespace(content_hash="d" * 64)),
        records,
        "f" * 64,
    )
    if mutation in (None, "summary"):
        assert request.content_hash in verify_q01(bundle, case, sources)
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            verify_q01(bundle, case, sources)
