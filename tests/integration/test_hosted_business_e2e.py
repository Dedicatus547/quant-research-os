"""Real offline Qlib business verification on synthetic fixtures; never live qualification."""

from __future__ import annotations

import shutil
from datetime import timedelta
from functools import partial
from pathlib import Path
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
from quantos.contracts.base import sha256_bytes
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
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    compare_principal_roots,
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
        export = tmp_path / f"principal-{index}"
        for item in principal.files:
            atomic_write_bytes(export / item.logical_path, read_relative(target, item.logical_path))
        assert raw_inventory(export) == principal
        exports.append(export)
        assert len(tuple(replay_execution.research_results_root.glob("sha256-*"))) == 2
    compare_principal_roots(
        exports[0], exports[1], raw_inventory(exports[0]), raw_inventory(exports[1])
    )
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
