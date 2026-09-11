from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantos.application import (
    ResearchLedgerError,
    ResearchLedgerService,
    build_context_bound_agent_run_spec,
    verify_context_bound_agent_manifest,
    verify_context_bound_agent_run_spec,
)
from quantos.config import load_yaml_contract
from quantos.contracts import (
    AgentRole,
    AgentRunManifest,
    AgentUsage,
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    ReasonCode,
    ResearchContextBudgetPolicy,
    ResearchLedgerAccessScope,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSearchRequest,
    RunStatus,
    canonical_json_bytes,
    sha256_bytes,
)

CAMPAIGN = "1" * 64
HISTORICAL_CAMPAIGN = "2" * 64
AGENT_RUN = "3" * 64
CONTAMINATION = "4" * 64
NOW = datetime(2026, 9, 11, 10, tzinfo=UTC)
ROOT = Path(__file__).parents[2]


def _object(
    payload: object,
    *,
    access: LedgerObjectAccess = LedgerObjectAccess.PUBLIC_HISTORY,
    campaign_hash: str | None = None,
    contamination_hashes: tuple[str, ...] = (),
) -> tuple[ResearchLedgerObjectRef, bytes]:
    encoded = canonical_json_bytes(payload)
    return (
        ResearchLedgerObjectRef(
            object_hash=sha256_bytes(encoded),
            media_type="application/json",
            source_domain="quantos-contracts",
            access=access,
            campaign_hash=campaign_hash,
            contamination_hashes=contamination_hashes,
        ),
        encoded,
    )


def _policy(*, cross_campaign: bool = True, max_bytes: int = 20_000):
    return ResearchLedgerSearchPolicy(
        policy_id="p14-ledger-search-v1",
        allowed_node_kinds=tuple(sorted(ResearchLedgerNodeKind, key=str)),
        allowed_authorities=tuple(sorted(LedgerAssertionAuthority, key=str)),
        allow_cross_campaign_history=cross_campaign,
        max_query_terms=8,
        max_results=10,
        max_serialized_bytes=max_bytes,
    )


def _append_fixture(service: ResearchLedgerService):
    evidence, evidence_bytes = _object({"title": "alpha evidence", "body": "alpha public"})
    first = service.append(
        ledger_id="research-ledger",
        node_id="evidence-1",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=evidence,
        object_bytes=evidence_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW,
    )
    historical, historical_bytes = _object(
        {"title": "historical failure", "body": "alpha"},
        access=LedgerObjectAccess.CAMPAIGN_INTERNAL,
        campaign_hash=HISTORICAL_CAMPAIGN,
    )
    second = service.append(
        ledger_id="research-ledger",
        node_id="hypothesis-1",
        node_kind=ResearchLedgerNodeKind.HYPOTHESIS_PROPOSAL,
        object_ref=historical,
        object_bytes=historical_bytes,
        authority=LedgerAssertionAuthority.AGENT_PROPOSAL,
        occurred_at=NOW + timedelta(seconds=1),
        parent_object_hashes=(evidence.object_hash,),
        agent_run_hash=AGENT_RUN,
    )
    sealed, sealed_bytes = _object(
        {"title": "sealed alpha", "body": "alpha alpha alpha"},
        access=LedgerObjectAccess.SEALED_CONFIRMATION,
        campaign_hash=HISTORICAL_CAMPAIGN,
        contamination_hashes=(CONTAMINATION,),
    )
    third = service.append(
        ledger_id="research-ledger",
        node_id="result-1",
        node_kind=ResearchLedgerNodeKind.RESEARCH_RESULT,
        object_ref=sealed,
        object_bytes=sealed_bytes,
        authority=LedgerAssertionAuthority.DETERMINISTIC_EVIDENCE,
        occurred_at=NOW + timedelta(seconds=2),
        parent_object_hashes=(historical.object_hash,),
    )
    return (first, second, third), (evidence, historical, sealed)


def _request(snapshot_hash: str, policy_hash: str, scope_hash: str):
    return ResearchLedgerSearchRequest(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot_hash,
        search_policy_hash=policy_hash,
        access_scope_hash=scope_hash,
        query="alpha",
    )


def test_frozen_ledger_policies_are_bounded_and_complete() -> None:
    search = load_yaml_contract(
        ROOT / "configs/research/ledger_search_v1.yaml", ResearchLedgerSearchPolicy
    )
    context = load_yaml_contract(
        ROOT / "configs/research/context_budget_v1.yaml", ResearchContextBudgetPolicy
    )

    assert set(search.allowed_node_kinds) == set(ResearchLedgerNodeKind)
    assert set(search.allowed_authorities) == set(LedgerAssertionAuthority)
    assert search.max_serialized_bytes == context.max_serialized_bytes == 262_144


def test_append_is_idempotent_and_rebuilds_identically_across_roots(tmp_path: Path) -> None:
    left = ResearchLedgerService(tmp_path / "left")
    right = ResearchLedgerService(tmp_path / "right")
    left_events, _ = _append_fixture(left)
    right_events, _ = _append_fixture(right)

    duplicate_events, duplicate_refs = _append_fixture(left)
    assert duplicate_events == left_events
    assert right_events == left_events
    assert duplicate_refs[0].object_hash == left_events[0].object_ref.object_hash

    left_snapshot = left.verify("research-ledger", created_at=NOW)
    right_snapshot = right.verify("research-ledger", created_at=NOW + timedelta(days=1))
    assert left_snapshot.content_hash == right_snapshot.content_hash
    assert left_snapshot.source_event_hashes == tuple(item.content_hash for item in left_events)
    assert left_snapshot.head_event_hash == left_events[-1].content_hash


def test_search_is_snapshot_bound_cross_campaign_and_sealed_safe(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _, (_, historical, sealed) = _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    request = _request(snapshot.content_hash, policy.content_hash, scope.content_hash)

    result = service.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
    assert [hit.object_ref.object_hash for hit in result.hits] == [
        next(
            hit.object_ref.object_hash
            for hit in result.hits
            if hit.object_ref.access is LedgerObjectAccess.PUBLIC_HISTORY
        ),
        historical.object_hash,
    ]
    assert sealed.object_hash not in {hit.object_ref.object_hash for hit in result.hits}

    allowlist_only = scope.model_copy(
        update={"authorized_sealed_object_hashes": (sealed.object_hash,)}
    )
    allowlist_request = _request(
        snapshot.content_hash, policy.content_hash, allowlist_only.content_hash
    )
    allowlist_result = service.search(
        snapshot=snapshot,
        policy=policy,
        scope=allowlist_only,
        request=allowlist_request,
    )
    assert sealed.object_hash not in {hit.object_ref.object_hash for hit in allowlist_result.hits}

    sealed_scope = scope.model_copy(
        update={
            "inherited_contamination_hashes": (CONTAMINATION,),
            "authorized_sealed_object_hashes": (sealed.object_hash,),
        }
    )
    sealed_request = _request(snapshot.content_hash, policy.content_hash, sealed_scope.content_hash)
    sealed_result = service.search(
        snapshot=snapshot,
        policy=policy,
        scope=sealed_scope,
        request=sealed_request,
    )
    assert sealed_result.hits[0].object_ref.object_hash == sealed.object_hash

    local_policy = _policy(cross_campaign=False)
    local_request = _request(snapshot.content_hash, local_policy.content_hash, scope.content_hash)
    local_result = service.search(
        snapshot=snapshot,
        policy=local_policy,
        scope=scope,
        request=local_request,
    )
    assert historical.object_hash not in {hit.object_ref.object_hash for hit in local_result.hits}


def test_context_pack_is_reproducible_and_fails_closed_on_budget(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    request = _request(snapshot.content_hash, policy.content_hash, scope.content_hash)
    result = service.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
    budget = ResearchContextBudgetPolicy(
        policy_id="p14-context-budget-v1",
        max_items=2,
        max_item_bytes=1_000,
        max_serialized_bytes=10_000,
    )

    first = service.build_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
    )
    second = service.build_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
    )
    assert first.content_hash == second.content_hash
    assert first.included_content_bytes == sum(item.content_bytes for item in first.items)

    left_pack, left_ref = service.publish_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
        output_root=tmp_path / "derived-left",
    )
    right_pack, right_ref = service.publish_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
        output_root=tmp_path / "derived-right",
    )
    assert left_pack == right_pack == first
    assert left_ref.sha256 == right_ref.sha256 == first.content_hash
    assert (
        service.verify_context_pack_artifact(
            tmp_path / "derived-left" / left_ref.logical_path,
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=result,
            budget=budget,
        )
        == first
    )

    tiny = ResearchContextBudgetPolicy(
        policy_id="p14-context-tiny-v1",
        max_items=1,
        max_item_bytes=1,
        max_serialized_bytes=1,
    )
    with pytest.raises(ResearchLedgerError) as raised:
        service.build_context_pack(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=result,
            budget=tiny,
        )
    assert raised.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED


def test_index_artifact_is_content_addressed_and_rebuildable(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()

    index, reference = service.publish_index(snapshot, policy, tmp_path / "derived")
    path = tmp_path / "derived" / reference.logical_path
    assert reference.sha256 == index.content_hash
    assert service.verify_index_artifact(path, snapshot, policy) == index

    wrong_name = tmp_path / "wrong-name.json"
    wrong_name.write_bytes(path.read_bytes())
    with pytest.raises(ResearchLedgerError) as invalid:
        service.verify_index_artifact(wrong_name, snapshot, policy)
    assert invalid.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_ledger_rejects_forward_parents_conflicts_and_tampering(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    reference, encoded = _object({"title": "alpha"})
    with pytest.raises(ResearchLedgerError) as forward:
        service.append(
            ledger_id="research-ledger",
            node_id="evidence-1",
            node_kind=ResearchLedgerNodeKind.EVIDENCE,
            object_ref=reference,
            object_bytes=encoded,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=NOW,
            parent_object_hashes=("f" * 64,),
        )
    assert forward.value.reason_code is ReasonCode.EVENT_CHAIN_INVALID

    _append_fixture(service)
    replacement, replacement_bytes = _object({"title": "different"})
    with pytest.raises(ResearchLedgerError) as conflict:
        service.append(
            ledger_id="research-ledger",
            node_id="evidence-1",
            node_kind=ResearchLedgerNodeKind.EVIDENCE,
            object_ref=replacement,
            object_bytes=replacement_bytes,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=NOW + timedelta(seconds=3),
        )
    assert conflict.value.reason_code is ReasonCode.DUPLICATE_ID_CONFLICT

    event_path = next((tmp_path / "ledger/events/research-ledger").glob("*.json"))
    event_path.write_bytes(event_path.read_bytes() + b" ")
    with pytest.raises(ResearchLedgerError) as tampered:
        service.verify("research-ledger", created_at=NOW)
    assert tampered.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_ledger_rejects_noncanonical_objects_and_mismatched_bindings(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    noncanonical = b'{"title": "alpha"}'
    reference = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(noncanonical),
        media_type="application/json",
        source_domain="quantos-contracts",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    with pytest.raises(ResearchLedgerError) as invalid:
        service.append(
            ledger_id="research-ledger",
            node_id="evidence-1",
            node_kind=ResearchLedgerNodeKind.EVIDENCE,
            object_ref=reference,
            object_bytes=noncanonical,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=NOW,
        )
    assert invalid.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    with pytest.raises(ValueError, match="public ledger objects cannot"):
        ResearchLedgerObjectRef(
            object_hash="a" * 64,
            media_type="application/json",
            source_domain="quantos-contracts",
            access=LedgerObjectAccess.PUBLIC_HISTORY,
            contamination_hashes=(CONTAMINATION,),
        )

    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    request = _request("f" * 64, policy.content_hash, scope.content_hash)
    with pytest.raises(ResearchLedgerError) as mismatch:
        service.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
    assert mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


@pytest.mark.parametrize(
    "encoded",
    [b"\xff", b"{not-json}"],
)
def test_ledger_rejects_non_utf8_or_invalid_json(tmp_path: Path, encoded: bytes) -> None:
    media_type = "text/plain" if encoded == b"\xff" else "application/json"
    reference = ResearchLedgerObjectRef(
        object_hash=sha256_bytes(encoded),
        media_type=media_type,
        source_domain="quantos-contracts",
        access=LedgerObjectAccess.PUBLIC_HISTORY,
    )
    with pytest.raises(ResearchLedgerError) as raised:
        ResearchLedgerService(tmp_path / "ledger").append(
            ledger_id="research-ledger",
            node_id="evidence-1",
            node_kind=ResearchLedgerNodeKind.EVIDENCE,
            object_ref=reference,
            object_bytes=encoded,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=NOW,
        )
    assert raised.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_ledger_rejects_invalid_time_authority_and_unsafe_tree(tmp_path: Path) -> None:
    reference, encoded = _object({"title": "alpha"})
    service = ResearchLedgerService(tmp_path / "ledger")
    with pytest.raises(ResearchLedgerError) as naive:
        service.append(
            ledger_id="research-ledger",
            node_id="evidence-1",
            node_kind=ResearchLedgerNodeKind.EVIDENCE,
            object_ref=reference,
            object_bytes=encoded,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=datetime(2026, 9, 11),
        )
    assert naive.value.reason_code is ReasonCode.SCHEMA_INVALID

    with pytest.raises(ResearchLedgerError) as authority:
        service.append(
            ledger_id="research-ledger",
            node_id="hypothesis-1",
            node_kind=ResearchLedgerNodeKind.HYPOTHESIS_PROPOSAL,
            object_ref=reference,
            object_bytes=encoded,
            authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
            occurred_at=NOW,
        )
    assert authority.value.reason_code is ReasonCode.SCHEMA_INVALID

    unsafe = tmp_path / "unsafe"
    unsafe.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ResearchLedgerError) as root:
        ResearchLedgerService(unsafe).verify("research-ledger", created_at=NOW)
    assert root.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    unexpected = tmp_path / "unexpected"
    unexpected.mkdir()
    (unexpected / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ResearchLedgerError) as tree:
        ResearchLedgerService(unexpected).verify("research-ledger", created_at=NOW)
    assert tree.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_ledger_rejects_missing_objects_and_stale_snapshots(tmp_path: Path) -> None:
    missing_service = ResearchLedgerService(tmp_path / "missing")
    _append_fixture(missing_service)
    object_path = next((tmp_path / "missing/objects").glob("*/*.json"))
    object_path.unlink()
    with pytest.raises(ResearchLedgerError) as missing:
        missing_service.verify("research-ledger", created_at=NOW)
    assert missing.value.reason_code is ReasonCode.SOURCE_INCOMPLETE

    stale_service = ResearchLedgerService(tmp_path / "stale")
    _append_fixture(stale_service)
    snapshot = stale_service.verify("research-ledger", created_at=NOW)
    extra, extra_bytes = _object({"title": "later beta"})
    stale_service.append(
        ledger_id="research-ledger",
        node_id="evidence-2",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=extra,
        object_bytes=extra_bytes,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ResearchLedgerError) as stale:
        stale_service.build_index(snapshot, _policy())
    assert stale.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_search_filters_and_budgets_fail_closed(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    filtered = ResearchLedgerSearchPolicy(
        policy_id="filtered-v1",
        allowed_node_kinds=(ResearchLedgerNodeKind.VALIDATION_REPORT,),
        allowed_authorities=(LedgerAssertionAuthority.DETERMINISTIC_VERDICT,),
        allow_cross_campaign_history=False,
        max_query_terms=1,
        max_results=1,
        max_serialized_bytes=10_000,
    )
    filtered_request = _request(snapshot.content_hash, filtered.content_hash, scope.content_hash)
    assert (
        service.search(
            snapshot=snapshot, policy=filtered, scope=scope, request=filtered_request
        ).hits
        == ()
    )

    empty_query = filtered_request.model_copy(update={"query": "!!!"})
    with pytest.raises(ResearchLedgerError) as empty:
        service.search(snapshot=snapshot, policy=filtered, scope=scope, request=empty_query)
    assert empty.value.reason_code is ReasonCode.SCHEMA_INVALID

    too_many = filtered_request.model_copy(update={"query": "alpha beta"})
    with pytest.raises(ResearchLedgerError) as terms:
        service.search(snapshot=snapshot, policy=filtered, scope=scope, request=too_many)
    assert terms.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED

    tiny = filtered.model_copy(update={"max_serialized_bytes": 1})
    tiny_request = _request(snapshot.content_hash, tiny.content_hash, scope.content_hash)
    with pytest.raises(ResearchLedgerError) as response:
        service.search(snapshot=snapshot, policy=tiny, scope=scope, request=tiny_request)
    assert response.value.reason_code is ReasonCode.RESOURCE_BUDGET_EXCEEDED


def test_context_pack_rejects_a_result_from_another_query(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    request = _request(snapshot.content_hash, policy.content_hash, scope.content_hash)
    other_request = request.model_copy(update={"query": "historical"})
    other_result = service.search(
        snapshot=snapshot, policy=policy, scope=scope, request=other_request
    )
    budget = ResearchContextBudgetPolicy(
        policy_id="p14-context-budget-v1",
        max_items=2,
        max_item_bytes=1_000,
        max_serialized_bytes=10_000,
    )
    with pytest.raises(ResearchLedgerError) as mismatch:
        service.build_context_pack(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=other_result,
            budget=budget,
        )
    assert mismatch.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_context_pack_is_a_required_agent_run_input(tmp_path: Path) -> None:
    service = ResearchLedgerService(tmp_path / "ledger")
    _append_fixture(service)
    snapshot = service.verify("research-ledger", created_at=NOW)
    policy = _policy()
    scope = ResearchLedgerAccessScope(
        campaign_hash=CAMPAIGN,
        ledger_snapshot_hash=snapshot.content_hash,
        readable_campaign_hashes=tuple(sorted((CAMPAIGN, HISTORICAL_CAMPAIGN))),
    )
    request = _request(snapshot.content_hash, policy.content_hash, scope.content_hash)
    result = service.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
    budget = ResearchContextBudgetPolicy(
        policy_id="p14-context-budget-v1",
        max_items=2,
        max_item_bytes=1_000,
        max_serialized_bytes=10_000,
    )
    pack = service.build_context_pack(
        snapshot=snapshot,
        policy=policy,
        scope=scope,
        request=request,
        result=result,
        budget=budget,
    )
    binding, spec = build_context_bound_agent_run_spec(
        run_id="p14-context-bound-probe",
        role=AgentRole.RESEARCHER,
        capability_policy_hash="5" * 64,
        requested_model_configuration_hash="6" * 64,
        tool_schema_hash="7" * 64,
        instruction_hashes=("8" * 64,),
        skill_hash="9" * 64,
        pack=pack,
    )
    assert pack.content_hash in spec.input_artifact_hashes
    assert binding.content_hash in spec.input_artifact_hashes
    assert spec.ledger_snapshot_hash == pack.ledger_snapshot_hash

    manifest = AgentRunManifest(
        run_spec_hash=spec.content_hash,
        provider_thread_id="qualification-probe",
        provider_model_identifier="synthetic-no-model-call",
        model_snapshot_immutable=True,
        model_configuration_hash="6" * 64,
        harness_identifier="p14a-context-binding-probe-v1",
        sandbox_policy_hash="a" * 64,
        permission_policy_hash="b" * 64,
        runtime_policy_hash="c" * 64,
        instruction_hashes=("8" * 64,),
        skill_hash="9" * 64,
        tool_schema_hash="7" * 64,
        interactions=(),
        input_hashes=spec.input_artifact_hashes,
        output_proposal_hashes=("d" * 64,),
        transcript_hash="e" * 64,
        usage=AgentUsage(input_tokens=0, output_tokens=0, tool_calls=0, retry_count=0),
        run_status=RunStatus.SUCCEEDED,
        limitations=("SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE",),
        started_at=NOW,
        completed_at=NOW,
        process_return_code=0,
    )
    verify_context_bound_agent_manifest(manifest=manifest, spec=spec, binding=binding, pack=pack)

    missing = spec.model_copy(
        update={
            "input_artifact_hashes": tuple(
                item for item in spec.input_artifact_hashes if item != pack.content_hash
            )
        }
    )
    with pytest.raises(ResearchLedgerError) as unbound:
        verify_context_bound_agent_run_spec(spec=missing, binding=binding, pack=pack)
    assert unbound.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    wrong_manifest = manifest.model_copy(update={"run_spec_hash": "f" * 64})
    with pytest.raises(ResearchLedgerError) as wrong_spec:
        verify_context_bound_agent_manifest(
            manifest=wrong_manifest, spec=spec, binding=binding, pack=pack
        )
    assert wrong_spec.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
