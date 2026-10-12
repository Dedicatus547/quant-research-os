"""Real offline Qlib business verification on synthetic fixtures; never live qualification."""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
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
from quantos.application.campaign_selection import publish_selection_plan
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
from quantos.contracts.campaign import CampaignTrial
from quantos.contracts.hosted import (
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedBudgetPolicy,
    HostedCampaignStatus,
    HostedResearchBudgetFact,
    HostedResearchStepIntent,
    HostedSubmissionReceipt,
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
from quantos.contracts.ledger import ResearchLedgerEventV2
from quantos.contracts.status import ReasonCode
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.infrastructure import hosted_business_verification as verification
from quantos.infrastructure.hosted_business_file_closure import verify_native_authority_file_closure
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
    verify_protocol_root,
    verify_raw_inventory,
)
from quantos.research.qlib import QlibResearchError


@pytest.mark.fresh_offline_process
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
    # Preserve the exact synthetic input contracts beside retained component roots
    # so failed checks can be re-inspected without rerunning Qlib or rebuilding input.
    atomic_write_bytes(tmp_path / "synthetic-frozen-business-inputs.json", bundle.canonical_bytes())

    def build_component(
        authority: Path,
        saved: Any = None,
        *,
        protocol_clock: Any = None,
        protocol_fault_hook: Any = None,
        business_fault_hook: Any = None,
        journal_observer: Any = None,
    ):
        runtime = authority / "business" / campaign.content_hash
        runtime.mkdir(parents=True, exist_ok=True)
        if not (runtime / "ledger").exists():
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
        publish_selection_plan(bundle.selection_plan, runtime / "selection-plans")
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
                    verify_journal_entry=saved.verify_entry if saved else journal_observer,
                    fault_hook=protocol_fault_hook,
                ),
                clock=saved.clock
                if saved
                else protocol_clock or (lambda: NOW + timedelta(seconds=30)),
                verify_inputs=lambda value: service.verify_registered_inputs(value),
            ),
            business_lock_root=authority / "business-locks",
            fault_hook=business_fault_hook,
        )
        # Synthetic data deliberately cannot pass the production p14dq loader. Here only
        # the real native adapter constructor is supplied, with its canonical gates intact.
        service.register_inputs(
            spec, HostedCampaignInputs(orchestrator, initial_events, lambda _: None)
        )
        return service, execution

    monkeypatch.setattr(
        verification,
        "build_hosted_execution_adapter",
        lambda *args, **kwargs: QuantosResearchExecutionAdapter(
            **{**adapter_args, "output_root": kwargs["runtime_root"] / "execution"}
        ),
    )
    # Literal physical exits use fresh service/adapter objects in each child.
    # Only the component factory replaces the production p14dq input loader;
    # execution, native receipts/gates/Ledger and full read-only verification are real.
    from quantos.infrastructure import hosted_fault_probe as fault_probe
    from quantos.infrastructure.hosted_client import consume_capability_fd
    from quantos.infrastructure.hosted_deployment import private_memory_fd
    from quantos.infrastructure.hosted_fault_cases import (
        FAULT_SNAPSHOT_PHASES,
        HOSTED_FAULT_WINDOWS,
        MANAGEMENT_FAULT_WINDOWS,
    )
    from quantos.infrastructure.hosted_fault_verification import verify_fault_recovery_scenario

    def fault_boot(
        _profile: str,
        *,
        protocol_clock,
        authority_root,
        channel_root,
        verify_journal_entry,
        protocol_fault_hook,
        business_fault_hook,
    ):
        assert channel_root.is_dir()
        assert consume_capability_fd(100) == b"S" * 32
        application, _ = build_component(
            authority_root,
            protocol_clock=protocol_clock,
            journal_observer=verify_journal_entry,
            protocol_fault_hook=protocol_fault_hook,
            business_fault_hook=business_fault_hook,
        )
        if (authority_root / "protocol/campaigns" / campaign.content_hash).exists():
            application.protocol.store.snapshot(campaign.content_hash, recover=True)
        return SimpleNamespace(application=application)

    def fault_hydrate(_profile: str) -> None:
        descriptor = private_memory_fd("synthetic-native-fault-capability")
        try:
            os.write(descriptor, b"S" * 32)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if descriptor != 100:
                os.dup2(descriptor, 100, inheritable=False)
        finally:
            if descriptor != 100:
                os.close(descriptor)

    fault_inputs = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": SimpleNamespace(
            business_configuration_hash="b" * 64,
            principals=(SimpleNamespace(capability_fd=100),),
        ),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
    }
    with monkeypatch.context() as fault_factory:
        fault_factory.setattr(fault_probe, "bootstrap_hosted_service", fault_boot)
        fault_factory.setattr(fault_probe, "hydrate_service_capabilities", fault_hydrate)
        fault_factory.setattr(
            fault_probe,
            "read_hashed_configuration",
            lambda _root, _hash, cls: fault_inputs[cls.__name__],
        )
        for window in MANAGEMENT_FAULT_WINDOWS:
            target = tmp_path / "physical-native-faults" / window
            local_authority, local_channel = target / "authority", target / "channel"
            local_authority.mkdir(parents=True)
            local_channel.mkdir()
            fault_probe.run_fault_probe(
                profile_hash, window, authority_root=local_authority, channel_root=local_channel
            )
            original_inventory = raw_inventory(local_authority)
            records = {
                phase: json.loads(
                    (local_channel / "process-records" / f"{phase}.json").read_bytes()
                )
                for phase in ("crash", "recovery-1", "recovery-2")
            }
            assert len({record["pid"] for record in records.values()}) == 3
            assert records["recovery-2"]["execute_calls"] == []
            assert records["recovery-2"]["workflow_calls"] == []
            assert (
                records["recovery-2"]["before_inventory"]
                == records["recovery-2"]["after_inventory"]
            )
            assert all(record["network_attempts"] == [] for record in records.values())
            observation = json.loads((local_channel / "negative-observation.json").read_bytes())
            roots = {
                phase: local_authority
                if phase == "after"
                else local_channel / "snapshots" / phase / "authority"
                for phase in FAULT_SNAPSHOT_PHASES
            }
            component_sources = SimpleNamespace(
                deployment=SimpleNamespace(
                    bundle=bundle,
                    profile=SimpleNamespace(content_hash=profile_hash),
                    paths=SimpleNamespace(
                        offline_inputs=tmp_path, provenance=tmp_path / "provenance"
                    ),
                )
            )
            phase_inventories = {phase: raw_inventory(root) for phase, root in roots.items()}
            checked = verify_fault_recovery_scenario(
                window,
                roots,
                records,
                observation,
                parent_pid=os.getpid(),
                sources=component_sources,
            )
            assert checked
            assert phase_inventories == {
                phase: raw_inventory(root) for phase, root in roots.items()
            }
            atomic_write_bytes(
                local_channel / "predicate-checkpoint.json",
                canonical_json_bytes(
                    {"case": window, "checked_hashes": checked, "scope": "PREDICATE_COMPLETED"}
                ),
            )
            if window == "corruption-journal_fragment":
                checkpoint, native_o, native_events = (
                    verification.build_verified_business_orchestrator(
                        roots["before"],
                        bundle,
                        deployment_profile_hash=profile_hash,
                        input_root=tmp_path,
                        provenance_workspace=tmp_path / "provenance",
                    )
                )
                plan_path = (
                    f"business/{campaign.content_hash}/selection-plans/"
                    f"sha256-{bundle.selection_plan.content_hash}/plan.json"
                )
                checked_paths = verify_native_authority_file_closure(
                    roots["before"], bundle, checkpoint, native_o, native_events
                )
                assert plan_path in checked_paths
                for damage in ("noncanonical", "extra_plan"):
                    altered = tmp_path / "frozen-plan-negatives" / damage
                    shutil.copytree(roots["before"], altered)
                    if damage == "noncanonical":
                        (altered / plan_path).write_bytes(
                            bundle.selection_plan.canonical_bytes() + b"\n"
                        )
                    else:
                        extra = altered / Path(plan_path).parent.parent / ("sha256-" + "a" * 64)
                        extra.mkdir()
                        (extra / "plan.json").write_bytes(bundle.selection_plan.canonical_bytes())
                    with pytest.raises(
                        HostedQualificationError, match=r"bytes differ|raw file delta"
                    ):
                        verify_native_authority_file_closure(
                            altered, bundle, checkpoint, native_o, native_events
                        )
            if MANAGEMENT_FAULT_WINDOWS[window].corruption:
                assert [item["exit_code"] for item in observation["process_exits"]] == [73, 74, 74]
                bad_records = deepcopy(records)
                wrong_result = {"outcome": "REJECTED_CORRUPT_AUTHORITY", "error_type": "OSError"}
                for phase in ("recovery-1", "recovery-2"):
                    bad_records[phase]["result_json"] = wrong_result
                    bad_records[phase]["result_hash"] = sha256_bytes(
                        canonical_json_bytes(wrong_result)
                    )
                with pytest.raises(HostedQualificationError, match="did not reject"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        bad_records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                bad_directories = deepcopy(records)
                for phase in ("recovery-1", "recovery-2"):
                    bad_directories[phase]["before_directories"] = []
                    bad_directories[phase]["after_directories"] = []
                with pytest.raises(HostedQualificationError, match="did not reject"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        bad_directories,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                bad_observation = deepcopy(observation)
                bad_observation["process_exits"][1]["exit_code"] = 0
                with pytest.raises(HostedQualificationError, match="waitpid"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        records,
                        bad_observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                # Self-consistent inventory rewrites still cannot hide extra disk
                # damage outside the exact fixed plan. Mutate copies only.
                copied_roots = {}
                for phase, root in roots.items():
                    copied = tmp_path / "corruption-extra-negative" / window / phase
                    shutil.copytree(root, copied)
                    copied_roots[phase] = copied
                    if phase != "before":
                        (copied / "unrelated-corruption.json").write_bytes(b"{}")
                with pytest.raises(HostedQualificationError, match="unrelated bytes"):
                    verify_fault_recovery_scenario(
                        window,
                        copied_roots,
                        records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                for phase in ("crashed", "recovered", "after"):
                    (copied_roots[phase] / "unrelated-corruption.json").unlink()
                for phase in ("recovered", "after"):
                    (copied_roots[phase] / "unobserved-empty-directory").mkdir()
                with pytest.raises(HostedQualificationError, match="actual directories"):
                    verify_fault_recovery_scenario(
                        window,
                        copied_roots,
                        records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
            # Actual original disk bytes stay unchanged; these are mutated uploaded
            # observation arguments to the core, not new trusted manager evidence.
            if window == next(iter(HOSTED_FAULT_WINDOWS)):
                # Recomputed observation hashes cannot authorize unknown files or
                # replace native status with another schema-valid state.
                altered_records = deepcopy(records)
                additions = []
                for phase in ("recovered", "after"):
                    path = roots[phase] / "unpublished-q05-review.json"
                    path.write_bytes(b'{"unrelated":true}')
                    additions.append(path)
                altered_records["recovery-1"]["after_inventory"] = raw_inventory(
                    roots["recovered"]
                ).model_dump(mode="json")
                for key in ("before_inventory", "after_inventory"):
                    altered_records["recovery-2"][key] = raw_inventory(roots["after"]).model_dump(
                        mode="json"
                    )
                changed_inventories = {phase: raw_inventory(root) for phase, root in roots.items()}
                with pytest.raises(HostedQualificationError, match="unattributed raw file"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        altered_records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                assert changed_inventories == {
                    phase: raw_inventory(root) for phase, root in roots.items()
                }
                for path in additions:
                    path.unlink()
                altered_records = deepcopy(records)
                original_status = HostedCampaignStatus.model_validate(
                    records["recovery-1"]["result_json"]
                )
                altered_status = HostedCampaignStatus.model_validate(
                    {**original_status.model_dump(mode="json"), "state": "RECOVERY_REQUIRED"}
                )
                assert altered_status != original_status
                for phase in ("recovery-1", "recovery-2"):
                    altered_records[phase]["result_json"] = altered_status.model_dump(mode="json")
                    altered_records[phase]["result_hash"] = altered_status.content_hash
                with pytest.raises(HostedQualificationError, match="status differs from native"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        altered_records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                orphan_roots = {}
                for phase, root in roots.items():
                    copied = tmp_path / "orphan-register-negative" / phase
                    shutil.copytree(root, copied)
                    orphan_roots[phase] = copied
                for phase in ("recovered", "after"):
                    store = HostedProtocolStore(orphan_roots[phase] / "protocol")
                    native_state = store.snapshot(campaign.content_hash, recover=False)
                    registration = native_state.journal[0]
                    publications = (
                        native_state.spec,
                        native_state.artifact(
                            registration.publications[1].artifact_hash, HostedBudgetJournalFact
                        ),
                        native_state.artifact(
                            registration.publications[2].artifact_hash, HostedSubmissionReceipt
                        ),
                    )
                    with store.campaign_lock(campaign.content_hash) as descriptor:
                        store.commit_locked(
                            descriptor,
                            campaign_hash=campaign.content_hash,
                            operation_id="0" * 64,
                            operation_kind="REGISTER",
                            recorded_at=native_state.spec.started_at,
                            artifacts=publications,
                        )
                    verify_protocol_root(orphan_roots[phase] / "protocol", campaign.content_hash)
                changed = deepcopy(records)
                state = HostedProtocolStore(orphan_roots["recovered"] / "protocol").snapshot(
                    campaign.content_hash, recover=False
                )
                updated_status = HostedCampaignApplicationService.project_status(
                    state, HostedProtocolService.project_status(state, NOW)
                )
                changed["recovery-1"]["after_inventory"] = raw_inventory(
                    orphan_roots["recovered"]
                ).model_dump(mode="json")
                for key in ("before_inventory", "after_inventory"):
                    changed["recovery-2"][key] = raw_inventory(orphan_roots["after"]).model_dump(
                        mode="json"
                    )
                for phase in ("recovery-1", "recovery-2"):
                    changed[phase]["result_json"] = updated_status.model_dump(mode="json")
                    changed[phase]["result_hash"] = updated_status.content_hash
                with pytest.raises(HostedQualificationError, match="operation chronology"):
                    verify_fault_recovery_scenario(
                        window,
                        orphan_roots,
                        changed,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                bad_observation = json.loads(json.dumps(observation))
                bad_observation["process_exits"][0]["exit_code"] = 0
                with pytest.raises(HostedQualificationError, match="waitpid"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        records,
                        bad_observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
            if window == "expire-intent_published-1":
                malformed = tmp_path / "missing-before-specs"
                shutil.copytree(roots["before"], malformed)
                specs = malformed / "protocol/specs"
                shutil.rmtree(specs)
                before_paths = tuple(
                    sorted(path.relative_to(malformed) for path in malformed.rglob("*"))
                )
                with pytest.raises(HostedQualificationError, match="authority is incomplete"):
                    verify_fault_recovery_scenario(
                        window,
                        {**roots, "before": malformed},
                        records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
                assert not specs.exists()
                assert before_paths == tuple(
                    sorted(path.relative_to(malformed) for path in malformed.rglob("*"))
                )
                bad_records = json.loads(json.dumps(records))
                bad_records["recovery-2"]["pid"] = bad_records["recovery-1"]["pid"]
                with pytest.raises(HostedQualificationError, match="not distinct"):
                    verify_fault_recovery_scenario(
                        window,
                        roots,
                        bad_records,
                        observation,
                        parent_pid=os.getpid(),
                        sources=component_sources,
                    )
            assert raw_inventory(local_authority) == original_inventory
            if window == "business-prepared":
                altered = tmp_path / "typed-ledger-negative"
                shutil.copytree(local_authority, altered)
                ledger_root = altered / "business" / campaign.content_hash / "ledger"
                event_path = sorted((ledger_root / "events" / bundle.ledger_id).iterdir())[-1]
                event = ResearchLedgerEventV2.model_validate_json(event_path.read_bytes())
                assert event.node_kind.value == "CAMPAIGN_TRIAL"
                data = {**event.model_dump(mode="python"), "node_kind": "EXPERIMENT"}
                data["event_id"] = ResearchLedgerService._event_identity(
                    **{
                        key: data[key]
                        for key in (
                            "ledger_id",
                            "node_id",
                            "node_kind",
                            "object_ref",
                            "authority",
                            "parent_object_hashes",
                            "agent_run_hash",
                            "human_review_evidence_hash",
                            "verdict_report_hash",
                            "occurred_at",
                        )
                    }
                )
                changed_event = ResearchLedgerEventV2.model_validate(data)
                event_path.unlink()
                (
                    event_path.parent
                    / f"{changed_event.sequence:020d}-{changed_event.event_id}.json"
                ).write_bytes(changed_event.canonical_bytes())
                ResearchLedgerService(ledger_root).verify(
                    bundle.ledger_id, created_at=event.occurred_at
                )
                checkpoint, native_o, native_events = (
                    verification.build_verified_business_orchestrator(
                        altered,
                        bundle,
                        deployment_profile_hash=profile_hash,
                        input_root=tmp_path,
                        provenance_workspace=tmp_path / "provenance",
                    )
                )
                with pytest.raises(HostedQualificationError, match="Ledger event is unrelated"):
                    verify_native_authority_file_closure(
                        altered, bundle, checkpoint, native_o, native_events
                    )
            if not MANAGEMENT_FAULT_WINDOWS[window].native_execution:
                continue
            facts = verification.verify_hosted_business_root(
                local_authority,
                bundle,
                deployment_profile_hash=profile_hash,
                input_root=tmp_path,
                provenance_workspace=tmp_path / "provenance",
            )
            crash_calls = records["crash"]["execute_calls"]
            recovery_calls = records["recovery-1"]["execute_calls"]
            assert not set(crash_calls).intersection(recovery_calls)
            if window == "execution-started":
                assert crash_calls == recovery_calls == []
                assert facts.report.state == "RECOVERY_REQUIRED"
                assert facts.report.reason == "EXECUTION_UNCERTAIN"
                assert facts.report.trial_hashes == ()
                assert facts.execution_identities == ()
                checkpoint, native_o, native_events = (
                    verification.build_verified_business_orchestrator(
                        local_authority,
                        bundle,
                        deployment_profile_hash=profile_hash,
                        input_root=tmp_path,
                        provenance_workspace=tmp_path / "provenance",
                    )
                )
                native_facts = HostedCampaignApplicationService.verify_research_facts(checkpoint)
                bad_prepared = HostedResearchStepIntent.model_validate(
                    {
                        **native_facts.steps[0].model_dump(mode="json"),
                        "event_time": (
                            native_facts.steps[0].event_time + timedelta(seconds=1)
                        ).isoformat(),
                    }
                )
                with pytest.raises(HostedQualificationError, match="proposal/trial/execution"):
                    verification.verify_native_business_steps(
                        checkpoint,
                        native_o,
                        native_events,
                        (bad_prepared,),
                    )
                bad_initial = HostedResearchBudgetFact.model_validate(
                    {
                        **native_facts.budgets[0].model_dump(mode="json"),
                        "operation_id": "0" * 64,
                    }
                )
                with pytest.raises(HostedQualificationError, match="native budget operation"):
                    verification.verify_native_business_budgets(
                        checkpoint,
                        native_o,
                        bundle.initial_events,
                        bundle.initial_events,
                        (bad_initial,),
                        (),
                        {},
                        None,
                    )
                assert raw_inventory(local_authority) == original_inventory
            else:
                assert len(crash_calls) + len(recovery_calls) == 2
                assert tuple(sorted(crash_calls + recovery_calls)) == facts.execution_identities
                assert len(facts.report.trial_hashes) == 2
                assert len(facts.validation_reports) == 2
                assert facts.selection is not None
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
    from quantos.infrastructure.hosted_admission_verification import (
        verify_business_admission_fixture,
    )
    from quantos.infrastructure.hosted_fixture_frames import (
        BUSINESS_REJECTION_CASES,
        business_rejection_frame,
    )

    # Actual native adapter and full business verification, with explicit synthetic
    # inputs. A malformed known candidate must create its trial without reaching
    # Qlib or borrowing a previously executed strategy's receipt.
    for invalid_case in BUSINESS_REJECTION_CASES:
        rejected_root = tmp_path / f"native-admission-{invalid_case}"
        rejected_service, _ = build_component(rejected_root)
        rejected_service.start(spec.content_hash)
        rejected_request = rejected_service.pending(campaign.content_hash)
        assert rejected_request is not None
        before_root = tmp_path / f"native-admission-before-{invalid_case}"
        shutil.copytree(rejected_root, before_root)
        bad_frame = business_rejection_frame(rejected_request, invalid_case)
        observed_calls: list[str] = []

        def reject_unexpected_execution(
            self: Any, request: Any, captured_calls: list[str] = observed_calls
        ) -> Any:
            captured_calls.append(request.execution_identity)
            raise AssertionError("schema-invalid proposal reached native execution")

        with monkeypatch.context() as guard:
            guard.setattr(QuantosResearchExecutionAdapter, "execute", reject_unexpected_execution)
            accepted = rejected_service.submit(
                rejected_request.content_hash, bad_frame, "component-test"
            )
            assert accepted.outcome == "ACCEPTED"
            terminal_status = rejected_service.resume(campaign.content_hash)
            pending_after = rejected_service.pending(campaign.content_hash)
            cancelled = None
            if pending_after is not None:
                cancelled = rejected_service.cancel(pending_after.content_hash, "component-test")
                # Keep the cancelled next request at its original checkpoint.
        assert observed_calls == []
        assert terminal_status.report_hash is None
        original_sources = SimpleNamespace(
            deployment=SimpleNamespace(
                bundle=bundle,
                profile=SimpleNamespace(content_hash=profile_hash),
                paths=SimpleNamespace(offline_inputs=tmp_path, provenance=tmp_path / "provenance"),
            )
        )
        inventories = raw_inventory(before_root), raw_inventory(rejected_root)
        checked = verify_business_admission_fixture(
            before_root,
            rejected_root,
            rejected_request,
            bad_frame,
            accepted.content_hash,
            terminal_status.report_hash,
            cancelled.content_hash if cancelled else None,
            original_sources,
        )
        assert accepted.content_hash in checked
        assert inventories == (raw_inventory(before_root), raw_inventory(rejected_root))
        if invalid_case == BUSINESS_REJECTION_CASES[0]:
            for extra_path in (
                "unpublished.json",
                f"business/{campaign.content_hash}/execution/receipts/unpublished.json",
                f"business/{campaign.content_hash}/execution/validation/unpublished-manifest.json",
                f"business/{campaign.content_hash}/execution/signals/unpublished-sidecar.json",
            ):
                extra = rejected_root / extra_path
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b'{"unpublished":true}')
                changed = raw_inventory(before_root), raw_inventory(rejected_root)
                with pytest.raises((HostedQualificationError, ValueError)):
                    verify_business_admission_fixture(
                        before_root,
                        rejected_root,
                        rejected_request,
                        bad_frame,
                        accepted.content_hash,
                        terminal_status.report_hash,
                        cancelled.content_hash if cancelled else None,
                        original_sources,
                    )
                assert changed == (raw_inventory(before_root), raw_inventory(rejected_root))
                extra.unlink()
            checkpoint = HostedProtocolStore(rejected_root / "protocol").snapshot(
                campaign.content_hash, recover=False
            )
            original_trial = next(
                checkpoint.artifact(digest, CampaignTrial)
                for digest, data in checkpoint.artifacts.items()
                if json.loads(data).get("schema_version") == "campaign-trial/v1"
            )
            unrelated_trial = CampaignTrial.model_validate(
                {
                    **original_trial.model_dump(mode="json"),
                    "trial_id": "unreferenced-journal-trial",
                    "idempotency_key": "0" * 64,
                }
            )
            settled = next(
                checkpoint.artifact(digest, HostedResearchBudgetFact)
                for digest, data in checkpoint.artifacts.items()
                if json.loads(data).get("schema_version") == "hosted-research-budget-fact/v1"
                and json.loads(data).get("phase") == "SETTLED"
            )
            for case_index, (kind, publications) in enumerate(
                (
                    ("BUSINESS", (unrelated_trial,)),
                    ("BUSINESS", (original_trial,)),
                    ("BUSINESS", (settled,)),
                    ("TERMINATE", (unrelated_trial,)),
                )
            ):
                altered_root = tmp_path / f"extra-journal-publication-{case_index}"
                shutil.copytree(rejected_root, altered_root)
                altered_store = HostedProtocolStore(altered_root / "protocol")
                with altered_store.campaign_lock(campaign.content_hash) as descriptor:
                    altered_store.commit_locked(
                        descriptor,
                        campaign_hash=campaign.content_hash,
                        operation_id=sha256_bytes(f"extra-publication-{case_index}".encode()),
                        operation_kind=kind,
                        recorded_at=rejected_request.issued_at,
                        artifacts=publications,
                    )
                changed = raw_inventory(before_root), raw_inventory(altered_root)
                with pytest.raises(HostedQualificationError, match="publication chronology"):
                    verify_business_admission_fixture(
                        before_root,
                        altered_root,
                        rejected_request,
                        bad_frame,
                        accepted.content_hash,
                        None,
                        cancelled.content_hash if cancelled else None,
                        original_sources,
                    )
                assert changed == (raw_inventory(before_root), raw_inventory(altered_root))
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
    extra_trial_root = tmp_path / "extra-native-trial-publication"
    shutil.copytree(authority, extra_trial_root)
    extra_store = HostedProtocolStore(extra_trial_root / "protocol")
    extra_state = extra_store.snapshot(campaign.content_hash, recover=False)
    original_trial = extra_state.artifact(facts.report.trial_hashes[0], CampaignTrial)
    unreferenced_trial = CampaignTrial.model_validate(
        {
            **original_trial.model_dump(mode="json"),
            "trial_id": "unreferenced-native-trial",
            "idempotency_key": "0" * 64,
        }
    )
    HostedProtocolService(extra_store).publish_business(
        campaign.content_hash,
        operation_id=sha256_bytes(b"unreferenced-native-trial-publication"),
        recorded_at=facts.report.recorded_at,
        artifacts=(unreferenced_trial,),
        expected_journal_head_hash=extra_state.journal_head_hash,
    )
    altered_inventory = raw_inventory(extra_trial_root)
    with pytest.raises(HostedQualificationError, match="unreferenced or unpublished trial"):
        verification.verify_hosted_business_root(
            extra_trial_root,
            bundle,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
    verify_raw_inventory(extra_trial_root, altered_inventory)
    verify_raw_inventory(authority, before)
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
