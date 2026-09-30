"""Real offline Qlib business verification on synthetic fixtures; never live qualification."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_autonomous_execution_e2e import (
    E2E_SNAPSHOT_FIXTURE_ROOT,
    E2E_VIEW_FIXTURE_ROOT,
    NOW,
    _contracts,
    _fixture_hash_directory,
    _synthetic_fixture,
)

from quantos.application.autonomous import (
    AutonomousCampaignOrchestrator,
    AutonomousOrchestrationError,
)
from quantos.application.autonomous_execution import (
    AutonomousExecutionReceipt,
    QuantosResearchExecutionAdapter,
)
from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    HostedCampaignInputs,
)
from quantos.application.hosted_inputs import HostedProposalOnlyDriver
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.application.ledger import ResearchLedgerService
from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import atomic_write_bytes, regular_tree_files
from quantos.contracts.autonomous import (
    AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE,
    AutonomousCandidateProposal,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentResponse,
    HostedBudgetPolicy,
    HostObservation,
    HostReportedUsage,
)
from quantos.contracts.hosted_inputs import (
    HostedCampaignRecipe,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
    derive_hosted_campaign_spec,
)
from quantos.contracts.hosted_qualification import HOSTED_ACCEPTANCE_SHA256, HOSTED_CONTRACT_SHA256
from quantos.contracts.status import ReasonCode
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.infrastructure import hosted_business_verification as verification
from quantos.infrastructure.hosted_replay import SavedHostedProtocol
from quantos.infrastructure.hosted_replay_evidence import (
    capture_replay_comparison,
    capture_replay_tampers,
)
from quantos.infrastructure.hosted_replay_verification import TAMPER_SCHEMAS, verify_tamper_case
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    compare_principal_roots,
    compare_verified_principal_roots,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)
from quantos.research.qlib import QlibResearchError


def test_actual_qlib_receipts_events_and_ledger_are_read_only_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _synthetic_fixture(tmp_path / "fixture")
    snapshot_source = _fixture_hash_directory(E2E_SNAPSHOT_FIXTURE_ROOT)[0]
    view_source = _fixture_hash_directory(E2E_VIEW_FIXTURE_ROOT)[0]
    snapshot_path = tmp_path / "snapshot" / snapshot_source.name
    view_path = tmp_path / "view" / view_source.name
    shutil.copytree(snapshot_source, snapshot_path)
    shutil.copytree(view_source, view_path)
    snapshot, view = verify_snapshot(snapshot_path), verify_qlib_view(view_path)
    values: tuple[Any, ...] = _contracts(
        tmp_path,
        dates,
        snapshot,
        snapshot_path,
        snapshot.snapshot_hash,
        view,
        view.view_hash,
        view_path,
        soft_reject=True,
    )
    (
        ledger_id,
        initial_ledger,
        _ledger,
        campaign,
        family,
        budget,
        template,
        manifest,
        search_policy,
        context_budget,
        campaign_policy,
        agent_policy,
        original_selection,
        initial_events,
        adapter_args,
        _proposal,
        _malformed,
        _execution_root,
    ) = values
    seed_files = tuple(
        HostedFrozenInputFile(
            logical_path=path.relative_to(tmp_path / "ledger").as_posix(),
            sha256=sha256_bytes(path.read_bytes()),
            size_bytes=path.stat().st_size,
        )
        for path in regular_tree_files(tmp_path / "ledger")
    )
    objects = {
        f"policies/{name}.json": adapter_args[name].canonical_bytes()
        for name in ("research_policy", "validation_policy", "cost_policy", "backtest_policy")
    }
    bundle = HostedFrozenBusinessInputs(
        campaign=campaign,
        research_budget=budget,
        execution_bindings=adapter_args["bindings"],
        hosted_recipe=HostedCampaignRecipe(
            hosted_budget=HostedBudgetPolicy(
                max_requests=2,
                max_unique_submissions=4,
                max_submissions_per_request=2,
                max_response_bytes=262144,
                max_proposal_bytes=262144,
                max_request_bytes=1048576,
                request_ttl_seconds=3600,
            ),
            requested_model_configuration_hash=agent_policy.requested_model_configuration_hash,
            contract_hash=HOSTED_CONTRACT_SHA256,
            acceptance_hash=HOSTED_ACCEPTANCE_SHA256,
            started_at=NOW,
        ),
        family=family,
        template=template,
        manifest=manifest,
        initial_ledger_snapshot=initial_ledger,
        initial_events=initial_events,
        ledger_id=ledger_id,
        search_policy=search_policy,
        context_budget=context_budget,
        campaign_policy=campaign_policy,
        agent_run_policy=agent_policy,
        selection_finalization_profile=AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE,
        multiple_testing_policy=original_selection.multiple_testing_policy,
        selection_policy=original_selection.selection_policy,
        selection_plan=original_selection.plan,
        authoring=adapter_args["base_authoring"],
        research_policy=adapter_args["research_policy"],
        validation_policy=adapter_args["validation_policy"],
        cost_policy=adapter_args["cost_policy"],
        backtest_policy=adapter_args["backtest_policy"],
        code_provenance=capture_code_provenance(tmp_path / "provenance"),
        snapshot_directory=snapshot_path.relative_to(tmp_path).as_posix(),
        qlib_view_directory=view_path.relative_to(tmp_path).as_posix(),
        initial_ledger_directory="ledger",
        initial_ledger_files=seed_files,
        frozen_byte_objects=tuple(
            HostedFrozenInputFile(
                logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
            )
            for path, data in sorted(objects.items())
        ),
    )
    profile_hash = "d" * 64
    spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash)

    def build_component(authority: Path, saved: Any = None):
        runtime = authority / "business" / campaign.content_hash
        runtime.mkdir(parents=True)
        shutil.copytree(tmp_path / "ledger", runtime / "ledger")
        local_args = {**adapter_args, "output_root": runtime / "execution"}
        execution = QuantosResearchExecutionAdapter(**local_args)
        selection = type(original_selection)(
            campaign,
            family,
            budget,
            template,
            manifest,
            bundle.multiple_testing_policy,
            bundle.selection_policy,
            view_path,
            (execution.research_results_root,),
            plan=bundle.selection_plan,
        )
        orchestrator = AutonomousCampaignOrchestrator(
            campaign=campaign,
            family=family,
            budget=budget,
            template=template,
            manifest=manifest,
            initial_ledger_snapshot=initial_ledger,
            ledger_service=ResearchLedgerService(runtime / "ledger"),
            ledger_id=ledger_id,
            search_policy=search_policy,
            context_budget=context_budget,
            campaign_policy=campaign_policy,
            agent_run_policy=agent_policy,
            agent_driver=HostedProposalOnlyDriver(),
            execution_port=execution,
            exchange_root=runtime / "unused-exchanges",
            event_root=runtime / "campaign-events",
            selection_service=selection,
            selection_artifact_root=runtime / "selection-reports",
            autonomous_report_root=runtime / "unused-reports",
            execution_bindings=bundle.execution_bindings,
        )
        service = HostedCampaignApplicationService(
            HostedProtocolService(
                HostedProtocolStore(
                    authority / "protocol",
                    verify_journal_entry=saved.verify_entry if saved else None,
                ),
                clock=saved.clock if saved else lambda: NOW + timedelta(seconds=30),
                verify_inputs=lambda value: service.verify_registered_inputs(value),
            ),
            business_lock_root=authority / "business-locks",
        )
        # Synthetic data deliberately cannot pass the production p14dq loader. Here only
        # the real native adapter constructor is supplied, with its canonical gates intact.
        service.register_inputs(
            spec, HostedCampaignInputs(orchestrator, initial_events, lambda _: None)
        )
        return service, execution

    authority = tmp_path / "authority"
    service, execution = build_component(authority)
    status = service.start(spec.content_hash)
    receipts = []
    for candidate in manifest.candidates:
        assert status.state == "WAITING_FOR_AGENT"
        request = service.pending(campaign.content_hash)
        assert request is not None
        proposal = AutonomousCandidateProposal(
            campaign_hash=campaign.content_hash,
            candidate_hash=candidate.content_hash,
            parameters=candidate.parameters,
            expression=candidate.expression,
            exact_expression_hash=candidate.exact_expression_hash,
            structural_expression_hash=candidate.structural_expression_hash,
            rationale="offline synthetic integration proposal; not a live model output",
        ).canonical_bytes()
        response = HostedAgentResponse(
            request_hash=request.content_hash,
            campaign_hash=campaign.content_hash,
            transport_ordinal=request.transport_ordinal,
            context_pack_hash=request.context_pack_hash,
            attempt_identity=request.attempt_identity,
            proposal_json=proposal.decode(),
            proposal_hash=sha256_bytes(proposal),
            host_observation=HostObservation(
                requested_configuration_hash=agent_policy.requested_model_configuration_hash,
                reported_usage=HostReportedUsage(unavailable_reason="SYNTHETIC_COMPONENT_TEST"),
                unavailable_reasons=(
                    "HOST_INTERNAL_USAGE_UNAVAILABLE",
                    "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                    "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                    "HOST_TRANSCRIPT_UNAVAILABLE",
                ),
            ),
        )
        receipt = service.submit(request.content_hash, response.canonical_bytes(), "component-test")
        assert receipt.outcome == "ACCEPTED"
        receipts.append(receipt)
        status = service.resume(campaign.content_hash)
    assert status.state != "WAITING_FOR_AGENT"
    monkeypatch.setattr(
        verification,
        "build_hosted_execution_adapter",
        lambda *args, **kwargs: QuantosResearchExecutionAdapter(
            **{**adapter_args, "output_root": kwargs["runtime_root"] / "execution"}
        ),
    )
    original_execute = QuantosResearchExecutionAdapter.execute
    exports: list[Path] = []
    native_roots: list[Path] = []
    native_inventories: list[Any] = []
    native_principals: list[Any] = []
    approved_paths: list[frozenset[str]] = []
    source_before = raw_inventory(authority / "protocol")
    for index in range(2):
        target = tmp_path / f"fresh-authority-{index}"
        saved = SavedHostedProtocol.load(authority / "protocol", campaign.content_hash)
        replay_service, replay_execution = build_component(target, saved)
        calls: list[str] = []

        def observe_execute(self: Any, request: Any, recorded_calls: list[str] = calls):
            recorded_calls.append(request.execution_identity)
            return original_execute(self, request)

        with monkeypatch.context() as observer:
            observer.setattr(QuantosResearchExecutionAdapter, "execute", observe_execute)
            saved.run(replay_service)
        replay_facts = verification.verify_hosted_business_root(
            target,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
        assert tuple(sorted(calls)) == replay_facts.execution_identities
        assert len(calls) == 2
        principal, _observations = verification.principal_business_inventory(target, replay_facts)
        native_roots.append(target)
        native_inventories.append(raw_inventory(target))
        native_principals.append(principal)
        approved_paths.append(
            verification.c11_business_projection_paths(target, replay_facts, bundle)
        )
        export = tmp_path / f"principal-{index}"
        for item in principal.files:
            atomic_write_bytes(export / item.logical_path, read_relative(target, item.logical_path))
        assert raw_inventory(export) == principal
        exports.append(export)
        assert len(tuple(replay_execution.research_results_root.glob("sha256-*"))) == 2
    compare_principal_roots(
        exports[0], exports[1], raw_inventory(exports[0]), raw_inventory(exports[1])
    )
    assert approved_paths[0] == approved_paths[1]
    projections = compare_verified_principal_roots(
        native_roots[0],
        native_roots[1],
        native_inventories[0],
        native_inventories[1],
        native_principals[0],
        native_principals[1],
        allowed_projection_paths=approved_paths[0],
    )
    assert projections
    source_manifest = next(
        native_roots[0].glob(
            "business/*/execution/executions/*/baseline/signals/sha256-*/manifest.json"
        )
    )
    source_relative = source_manifest.relative_to(native_roots[0]).as_posix()
    source_parts = source_relative.split("/")
    identities = sorted(
        {path.split("/")[4] for path in approved_paths[0] if "/executions/" in path}
    )
    other_identity = next(identity for identity in identities if identity != source_parts[4])
    unreferenced = (
        source_relative.replace(source_parts[-2], source_parts[-2].removeprefix("sha256-")),
        source_relative.replace(source_parts[4], other_identity),
        source_relative.replace("/baseline/", "/cost-1.5x/"),
    )
    for logical in unreferenced:
        assert logical not in approved_paths[0]
        for index, root in enumerate(native_roots):
            value = json.loads(source_manifest.read_bytes())
            from datetime import datetime

            value["created_at"] = (
                datetime.fromisoformat(value["created_at"]) + timedelta(days=index)
            ).isoformat()
            atomic_write_bytes(root / logical, canonical_json_bytes(value))
        changed_raw = [raw_inventory(root) for root in native_roots]
        changed_principal = [
            verification.principal_business_inventory(root, replay_facts)[0]
            for root in native_roots
        ]
        approved = verification.c11_business_projection_paths(native_roots[0], replay_facts, bundle)
        assert logical not in approved
        with pytest.raises(HostedQualificationError, match="not a verified C11"):
            compare_verified_principal_roots(
                *native_roots,
                *changed_raw,
                *changed_principal,
                allowed_projection_paths=approved,
            )
        for root in native_roots:
            (root / logical).unlink()
        for root, inventory in zip(native_roots, native_inventories, strict=True):
            verify_raw_inventory(root, inventory)
    verify_raw_inventory(authority / "protocol", source_before)
    monkeypatch.setattr(
        QuantosResearchExecutionAdapter,
        "execute",
        lambda *args: pytest.fail("read-only verification executed"),
    )
    before = raw_inventory(authority)
    facts = verification.verify_hosted_business_root(
        authority,
        bundle,
        deployment_profile_hash=profile_hash,
        input_root=tmp_path,
        provenance_workspace=tmp_path / "provenance",
    )
    assert len(facts.execution_identities) == len(facts.validation_reports) == 2
    assert all(receipt.content_hash in facts.artifact_hashes for receipt in receipts)
    principal, observations = verification.principal_business_inventory(authority, facts)
    assert set(principal.files).isdisjoint(observations.files)
    assert len(principal.files) + len(observations.files) == len(before.files)
    verify_raw_inventory(authority, before)
    tamper_sources = SimpleNamespace(
        deployment=SimpleNamespace(
            bundle=bundle,
            profile=SimpleNamespace(content_hash=profile_hash),
            root=tmp_path,
            paths=SimpleNamespace(provenance=tmp_path / "provenance"),
        )
    )
    targets: dict[str, str] = {}
    for file in before.files:
        if not file.logical_path.endswith(".json"):
            continue
        value = json.loads(read_relative(authority, file.logical_path))
        if not isinstance(value, dict):
            continue
        for kind, schema in TAMPER_SCHEMAS.items():
            if value.get("schema_version") == schema and kind not in targets:
                # Use the exact native receipt identity consumed by recovery,
                # rather than its content-addressed secondary copy.
                if kind == "RECEIPT" and "/execution-records/identities/" not in file.logical_path:
                    continue
                targets[kind] = file.logical_path
    assert set(targets) == set(TAMPER_SCHEMAS)
    for kind, logical in targets.items():
        target = tmp_path / f"tamper-{kind.lower()}"
        shutil.copytree(authority, target)
        original_value = json.loads(read_relative(authority, logical))
        (target / logical).write_bytes(
            canonical_json_bytes(
                {
                    **original_value,
                    "schema_version": "tampered/" + TAMPER_SCHEMAS[kind],
                }
            )
        )
        assert verify_tamper_case(
            authority,
            target,
            logical_path=logical,
            kind=kind,
            baseline_inventory=before,
            altered_inventory=raw_inventory(target),
            sources=tamper_sources,
        )
        verify_raw_inventory(authority, before)
    # Capture actual management facts against these native synthetic roots. Their
    # provenance remains SYNTHETIC_COMPONENT_TEST and cannot supply model sources.
    for original_input in (snapshot_path, view_path):
        target_input = tmp_path / "inputs" / original_input.relative_to(tmp_path)
        target_input.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(original_input, target_input)
    managed = SimpleNamespace(
        bundle=bundle,
        profile=SimpleNamespace(content_hash=profile_hash),
        root=tmp_path,
        paths=SimpleNamespace(authority=authority, provenance=tmp_path / "provenance"),
        capability=b"component-only-capability-material",
    )
    comparison_path = capture_replay_comparison(managed, *native_roots)
    comparison = json.loads(comparison_path.read_bytes())
    assert len(comparison["roots"]) == 2
    assert len(comparison["projections"]) == len(projections)
    tamper_path = capture_replay_tampers(managed)
    assert len(json.loads(tamper_path.read_bytes())["cases"]) == 5
    verify_raw_inventory(authority, before)
    variant_manifest = next(
        authority.glob("business/*/execution/executions/*/cost-1.5x/signals/sha256-*/manifest.json")
    )
    wrong_manifest = next(
        path
        for path in authority.glob(
            "business/*/execution/executions/*/baseline/signals/sha256-*/manifest.json"
        )
        if path.parent.name != variant_manifest.parent.name
    )
    saved_variant_manifest = variant_manifest.read_bytes()
    variant_manifest.write_bytes(wrong_manifest.read_bytes())
    with pytest.raises(HostedQualificationError, match="directory/content"):
        verification.verify_hosted_business_root(
            authority,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
    variant_manifest.write_bytes(saved_variant_manifest)
    variant_table = next(
        authority.glob(
            "business/*/execution/executions/*/cost-1.5x/backtests/sha256-*/portfolio.parquet"
        )
    )
    saved_variant_table = variant_table.read_bytes()
    variant_table.write_bytes(b"corrupted robustness portfolio")
    with pytest.raises(HostedQualificationError, match="robustness artifact is invalid"):
        verification.verify_hosted_business_root(
            authority,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
    variant_table.write_bytes(saved_variant_table)
    verify_raw_inventory(authority, before)
    native_receipts = tuple(
        AutonomousExecutionReceipt.model_validate_json(path.read_bytes())
        for path in sorted((execution.output_root / "execution-records/identities").glob("*.json"))
    )
    first, second = native_receipts
    assert first.outcome.validation_report_hash != second.outcome.validation_report_hash
    # Both reports are valid and share data/policies. Swapping only the report and
    # its evidence hash must still fail against the candidate's native result.
    swapped_outcome = first.outcome.model_copy(
        update={
            "validation_report_hash": second.outcome.validation_report_hash,
            "evidence_hashes": tuple(
                sorted(
                    {
                        *(
                            value
                            for value in first.outcome.evidence_hashes
                            if value != first.outcome.validation_report_hash
                        ),
                        second.outcome.validation_report_hash,
                    }
                )
            ),
        }
    )
    swapped = AutonomousExecutionReceipt(request=first.request, outcome=swapped_outcome)
    with pytest.raises(AutonomousOrchestrationError, match="bound to different inputs"):
        execution._verify_receipt(swapped)
    baseline = next(
        (
            execution.output_root
            / "executions"
            / first.request.execution_identity
            / "baseline/backtests"
        ).glob("sha256-*/portfolio.parquet")
    )
    original_backtest = baseline.read_bytes()
    baseline.write_bytes(b"corrupted backtest table")
    with pytest.raises(AutonomousOrchestrationError, match="backtest failed bottom-up"):
        execution.inspect_completed_execution(first.request)
    baseline.write_bytes(original_backtest)
    verify_raw_inventory(authority, before)
    for reason in (
        ReasonCode.LOOK_AHEAD,
        ReasonCode.UNKNOWN_AVAILABILITY,
        ReasonCode.QLIB_EXECUTION_FAILED,
        ReasonCode.SOURCE_INCOMPLETE,
    ):
        failed_adapter = QuantosResearchExecutionAdapter(
            **{**adapter_args, "output_root": tmp_path / f"native-failure-{reason.value}"}
        )

        def native_failure(request: Any, code: ReasonCode = reason):
            raise QlibResearchError(code, "injected native component failure")

        with monkeypatch.context() as failure_hook:
            failure_hook.setattr(failed_adapter, "_execute_pipeline", native_failure)
            outcome = original_execute(failed_adapter, first.request)
            assert outcome.failure_reason_code is reason
            assert failed_adapter.inspect_completed_execution(first.request) == outcome
            failure = next((failed_adapter.output_root / "execution-failures").glob("*.json"))
            saved_failure = failure.read_bytes()
            failure.unlink()
            for reuse in (
                partial(original_execute, failed_adapter),
                failed_adapter.verified_completed_execution,
                failed_adapter.inspect_completed_execution,
            ):
                with pytest.raises(AutonomousOrchestrationError, match="failure evidence"):
                    reuse(first.request)
            failure.write_bytes(saved_failure)
            saved_receipt = AutonomousExecutionReceipt.model_validate_json(
                failed_adapter._receipt_path(first.request.execution_identity).read_bytes()
            )
            invalid = saved_receipt.outcome.model_copy(
                update={"failure_reason_code": ReasonCode.SOFT_THRESHOLD_NOT_MET}
            )
            with pytest.raises(AutonomousOrchestrationError, match="native classification"):
                failed_adapter._verify_receipt(
                    AutonomousExecutionReceipt(request=first.request, outcome=invalid)
                )
    saved = next(execution.research_results_root.glob("sha256-*/labels.json"))
    original = saved.read_bytes()
    saved.write_bytes(b"[]")
    with pytest.raises(AutonomousOrchestrationError, match="bottom-up verification"):
        verification.verify_hosted_business_root(
            authority,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
    saved.write_bytes(original)
    verify_raw_inventory(authority, before)
