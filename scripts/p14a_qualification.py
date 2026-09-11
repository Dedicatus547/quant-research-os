#!/usr/bin/env python3
"""Qualify P14a ledger/context behavior from a clean checkout and two independent roots."""

from __future__ import annotations

import argparse
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quantos.application import (
    ResearchLedgerService,
    build_context_bound_agent_run_spec,
    capture_code_provenance,
    capture_runtime_fingerprint,
)
from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
)
from quantos.config import load_yaml_contract
from quantos.contracts import (
    AgentRole,
    AgentRunSpec,
    CodeProvenance,
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    P14aQualificationReport,
    ResearchContextAgentBinding,
    ResearchContextBudgetPolicy,
    ResearchContextPack,
    ResearchLedgerAccessScope,
    ResearchLedgerIndex,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSearchRequest,
    ResearchLedgerSearchResult,
    ResearchLedgerSnapshot,
    RunStatus,
    RuntimeFingerprint,
    ValidationVerdict,
    canonical_json_bytes,
    sha256_bytes,
)

SEARCH_POLICY = Path("configs/research/ledger_search_v1.yaml")
CONTEXT_BUDGET_POLICY = Path("configs/research/context_budget_v1.yaml")
OCCURRED_AT = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
LEDGER_ID = "p14a-qualification-ledger"
LIMITATIONS = ("SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE",)


def _hash_label(label: str) -> str:
    return sha256_bytes(canonical_json_bytes({"p14a_qualification": label}))


CAMPAIGN_HASH = _hash_label("current-campaign")
HISTORICAL_CAMPAIGN_HASH = _hash_label("historical-campaign")


def _object(
    payload: object, *, access: LedgerObjectAccess, campaign_hash: str | None
) -> tuple[ResearchLedgerObjectRef, bytes]:
    encoded = canonical_json_bytes(payload)
    return (
        ResearchLedgerObjectRef(
            object_hash=sha256_bytes(encoded),
            media_type="application/json",
            source_domain="p14a-qualification",
            access=access,
            campaign_hash=campaign_hash,
        ),
        encoded,
    )


def _fixture_payload() -> dict[str, object]:
    return {
        "campaign_hash": CAMPAIGN_HASH,
        "historical_campaign_hash": HISTORICAL_CAMPAIGN_HASH,
        "ledger_id": LEDGER_ID,
        "objects": (
            {"body": "historical rank ic failure reusable", "title": "prior result"},
            {"body": "rank ic candidate evidence", "title": "current result"},
        ),
        "occurred_at": OCCURRED_AT,
        "query": "rank ic failure",
        "schema_version": "p14a-qualification-fixture/v1",
    }


def _execute_pipeline(
    root: Path,
    *,
    policy: ResearchLedgerSearchPolicy,
    budget: ResearchContextBudgetPolicy,
) -> dict[str, object]:
    service = ResearchLedgerService(root / "ledger")
    fixture = _fixture_payload()
    historical, historical_bytes = _object(
        fixture["objects"][0],  # type: ignore[index]
        access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
        campaign_hash=HISTORICAL_CAMPAIGN_HASH,
    )
    current, current_bytes = _object(
        fixture["objects"][1],  # type: ignore[index]
        access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
        campaign_hash=CAMPAIGN_HASH,
    )
    service.append(
        ledger_id=LEDGER_ID,
        node_id="historical-result",
        node_kind=ResearchLedgerNodeKind.RESEARCH_RESULT,
        object_ref=historical,
        object_bytes=historical_bytes,
        authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
        occurred_at=OCCURRED_AT,
    )
    service.append(
        ledger_id=LEDGER_ID,
        node_id="current-result",
        node_kind=ResearchLedgerNodeKind.RESEARCH_RESULT,
        object_ref=current,
        object_bytes=current_bytes,
        authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
        occurred_at=OCCURRED_AT + timedelta(seconds=1),
        parent_object_hashes=(historical.object_hash,),
    )
    snapshot = service.verify(LEDGER_ID, created_at=OCCURRED_AT + timedelta(seconds=2))
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN_HASH,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN_HASH, HISTORICAL_CAMPAIGN_HASH))),
    )
    request = ResearchLedgerSearchRequest(
        campaign_hash=CAMPAIGN_HASH,
        ledger_snapshot_hash=snapshot.content_hash,
        search_policy_hash=policy.content_hash,
        access_scope_hash=scope.content_hash,
        query=str(fixture["query"]),
    )
    result = service.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
    index, index_ref = service.publish_index(snapshot, policy, root / "derived")
    pack, pack_ref = service.publish_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
        output_root=root / "derived",
    )
    service.verify_index_artifact(root / "derived" / index_ref.logical_path, snapshot, policy)
    service.verify_context_pack_artifact(
        root / "derived" / pack_ref.logical_path,
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
    )
    binding, spec = build_context_bound_agent_run_spec(
        run_id="p14a-context-binding-qualification",
        role=AgentRole.RESEARCHER,
        capability_policy_hash=_hash_label("capability-policy"),
        requested_model_configuration_hash=_hash_label("model-configuration"),
        tool_schema_hash=_hash_label("tool-schema"),
        instruction_hashes=(_hash_label("instructions"),),
        skill_hash=_hash_label("skill"),
        pack=pack,
    )
    return {
        "access_scope": scope,
        "agent_context_binding": binding,
        "agent_run_spec": spec,
        "context_pack": pack,
        "index": index,
        "ledger_snapshot": snapshot,
        "search_request": request,
        "search_result": result,
    }


def _assert_byte_exact(left: dict[str, object], right: dict[str, object]) -> None:
    if left.keys() != right.keys():
        raise ValueError("P14a independent pipelines emitted different artifact sets")
    for name in left:
        left_contract = left[name]
        right_contract = right[name]
        if not hasattr(left_contract, "canonical_bytes") or not hasattr(
            right_contract, "canonical_bytes"
        ):
            raise TypeError(f"P14a pipeline artifact is not canonical: {name}")
        if left_contract.canonical_bytes() != right_contract.canonical_bytes():  # type: ignore[attr-defined]
            raise ValueError(f"P14a independent pipeline mismatch: {name}")


def _qualification_payloads(
    report: P14aQualificationReport,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
    artifacts: dict[str, object],
) -> dict[str, bytes]:
    payloads = {
        "code-provenance.json": code.canonical_bytes(),
        "qualification-report.json": report.canonical_bytes(),
        "runtime-fingerprint.json": runtime.canonical_bytes(),
    }
    for name, contract in artifacts.items():
        payloads[f"{name.replace('_', '-')}.json"] = contract.canonical_bytes()  # type: ignore[attr-defined]
    return payloads


def _publish_report(
    output_root: Path,
    report: P14aQualificationReport,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
    artifacts: dict[str, object],
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / f"sha256-{report.content_hash}"
    expected = _qualification_payloads(report, code, runtime, artifacts)
    if destination.exists() or destination.is_symlink():
        try:
            actual = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in regular_tree_files(destination)
            }
        except (ArtifactIntegrityError, OSError, ValueError):
            raise ArtifactConflictError("P14a qualification output is invalid") from None
        if actual != expected:
            raise ArtifactConflictError("P14a qualification output conflicts")
        return destination
    with tempfile.TemporaryDirectory(prefix=".p14a-report-", dir=output_root) as staging:
        staging_root = Path(staging)
        for relative, encoded in expected.items():
            atomic_write_bytes(staging_root / relative, encoded)
        publish_directory(staging_root, destination)
    return destination


def qualify(
    *,
    workspace: Path,
    output_root: Path,
    code: CodeProvenance,
    runtime: RuntimeFingerprint,
) -> dict[str, object]:
    policy = load_yaml_contract(workspace / SEARCH_POLICY, ResearchLedgerSearchPolicy)
    budget = load_yaml_contract(workspace / CONTEXT_BUDGET_POLICY, ResearchContextBudgetPolicy)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p14a-pipelines-", dir=output_root) as temporary:
        root = Path(temporary)
        left = _execute_pipeline(root / "left", policy=policy, budget=budget)
        right = _execute_pipeline(root / "right", policy=policy, budget=budget)
        _assert_byte_exact(left, right)

    snapshot = left["ledger_snapshot"]
    index = left["index"]
    scope = left["access_scope"]
    request = left["search_request"]
    result = left["search_result"]
    pack = left["context_pack"]
    binding = left["agent_context_binding"]
    spec = left["agent_run_spec"]
    assert isinstance(snapshot, ResearchLedgerSnapshot)
    assert isinstance(index, ResearchLedgerIndex)
    assert isinstance(scope, ResearchLedgerAccessScope)
    assert isinstance(request, ResearchLedgerSearchRequest)
    assert isinstance(result, ResearchLedgerSearchResult)
    assert isinstance(pack, ResearchContextPack)
    assert isinstance(binding, ResearchContextAgentBinding)
    assert isinstance(spec, AgentRunSpec)
    report = P14aQualificationReport(
        code_provenance_hash=code.content_hash,
        runtime_fingerprint_hash=runtime.content_hash,
        search_policy_hash=policy.content_hash,
        context_budget_policy_hash=budget.content_hash,
        fixture_hash=sha256_bytes(canonical_json_bytes(_fixture_payload())),
        ledger_snapshot_hash=snapshot.content_hash,
        index_hash=index.content_hash,
        access_scope_hash=scope.content_hash,
        search_request_hash=request.content_hash,
        search_result_hash=result.content_hash,
        context_pack_hash=pack.content_hash,
        agent_context_binding_hash=binding.content_hash,
        agent_run_spec_hash=spec.content_hash,
        independent_root_count=2,
        principal_hashes_byte_exact=True,
        context_bound_to_agent_spec=True,
        status=RunStatus.SUCCEEDED,
        verdict=ValidationVerdict.PASS,
        limitations=LIMITATIONS,
    )
    destination = _publish_report(output_root, report, code, runtime, left)
    return {
        "schema_version": "p14a-qualification-runner-result/v1",
        "qualification_report_hash": report.content_hash,
        "qualification_path": str(destination),
        "ledger_snapshot_hash": report.ledger_snapshot_hash,
        "index_hash": report.index_hash,
        "context_pack_hash": report.context_pack_hash,
        "agent_run_spec_hash": report.agent_run_spec_hash,
        "status": report.status,
        "verdict": report.verdict,
    }


def run(*, workspace: Path, output_root: Path) -> dict[str, object]:
    """Require clean Git provenance before producing qualification evidence."""

    code = capture_code_provenance(workspace)
    runtime = capture_runtime_fingerprint()
    return qualify(
        workspace=workspace,
        output_root=output_root,
        code=code,
        runtime=runtime,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/qualification/p14a"))
    args = parser.parse_args()
    result = run(workspace=args.workspace.resolve(), output_root=args.output_root.resolve())
    print(canonical_json_bytes(result).decode("utf-8"))


if __name__ == "__main__":
    main()
