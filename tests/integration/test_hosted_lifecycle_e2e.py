"""Native synthetic lifecycle accounting; no installed or live qualification."""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
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

from quantos.application.autonomous import AutonomousCampaignOrchestrator
from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
from quantos.application.campaign_selection import publish_selection_plan
from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    HostedCampaignInputs,
)
from quantos.application.hosted_inputs import HostedProposalOnlyDriver
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.application.ledger import ResearchLedgerService
from quantos.application.provenance import capture_code_provenance
from quantos.artifacts.store import regular_tree_files
from quantos.contracts.autonomous import P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import HostedBudgetPolicy, HostedSubmissionReceipt
from quantos.contracts.hosted_inputs import (
    HostedCampaignRecipe,
    HostedFrozenBusinessInputs,
    HostedFrozenInputFile,
    derive_hosted_campaign_spec,
)
from quantos.contracts.hosted_qualification import HOSTED_ACCEPTANCE_SHA256, HOSTED_CONTRACT_SHA256
from quantos.data import verify_qlib_view, verify_snapshot
from quantos.infrastructure import (
    hosted_business_verification as business_verification,
)
from quantos.infrastructure import (
    hosted_lifecycle_probe as probe,
)
from quantos.infrastructure.hosted_client import consume_capability_fd
from quantos.infrastructure.hosted_deployment import private_memory_fd
from quantos.infrastructure.hosted_lifecycle_verification import (
    lifecycle_process_phases,
    verify_lifecycle_scenario,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    directory_inventory,
    raw_inventory,
)


def test_native_lifecycle_accounting_and_tampered_process_records(
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
        selection_finalization_profile=P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
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
    from quantos.infrastructure.hosted_budget_cases import (
        HOSTED_BUDGET_CASES,
        derive_hosted_budget_case,
        freeze_hosted_budget_case,
    )

    view_before = raw_inventory(view_path), directory_inventory(view_path)
    for case in HOSTED_BUDGET_CASES:
        derived = derive_hosted_budget_case(bundle, case, input_root=tmp_path)
        assert (raw_inventory(view_path), directory_inventory(view_path)) == view_before
        published = freeze_hosted_budget_case(
            bundle,
            case,
            input_root=tmp_path,
            artifact_root=tmp_path / "budget-plans" / case,
        )
        assert (
            published == derived and derived.campaign.content_hash != bundle.campaign.content_hash
        )
        assert derived.initial_ledger_files == bundle.initial_ledger_files
        assert derived.execution_bindings == bundle.execution_bindings
        assert derived.selection_plan.campaign_hash == derived.campaign.content_hash
        assert derived.selection_plan.budget_hash == derived.research_budget.content_hash
        plan_file = (
            tmp_path
            / "budget-plans"
            / case
            / f"sha256-{derived.selection_plan.content_hash}"
            / "plan.json"
        )
        assert plan_file.read_bytes() == derived.selection_plan.canonical_bytes()
        original_plan = raw_inventory(plan_file.parent), directory_inventory(plan_file.parent)
        with pytest.raises(ValueError, match="fresh"):
            freeze_hosted_budget_case(
                bundle, case, input_root=tmp_path, artifact_root=tmp_path / "budget-plans" / case
            )
        assert (
            raw_inventory(plan_file.parent),
            directory_inventory(plan_file.parent),
        ) == original_plan
    profile_hash = "d" * 64
    spec = derive_hosted_campaign_spec(bundle, deployment_profile_hash=profile_hash)

    active_bundle = [bundle]

    def boot(_profile, *, protocol_clock, authority_root, channel_root):
        selected = active_bundle[0]
        native_spec = derive_hosted_campaign_spec(selected, deployment_profile_hash=profile_hash)
        assert consume_capability_fd(100) == b"S" * 32
        store = HostedProtocolStore(authority_root / "protocol")
        store.verify_spec_registration(native_spec)
        if (authority_root / "protocol/campaigns" / selected.campaign.content_hash).exists():
            store.snapshot(selected.campaign.content_hash, recover=True)
        runtime = authority_root / "business" / selected.campaign.content_hash
        runtime.mkdir(parents=True, exist_ok=True)
        if not (runtime / "ledger").exists():
            shutil.copytree(tmp_path / "ledger", runtime / "ledger")
        execution = QuantosResearchExecutionAdapter(
            **{
                **adapter_args,
                "campaign": selected.campaign,
                "budget": selected.research_budget,
                "output_root": runtime / "execution",
            }
        )
        selection = type(original_selection)(
            selected.campaign,
            selected.family,
            selected.research_budget,
            selected.template,
            selected.manifest,
            selected.multiple_testing_policy,
            selected.selection_policy,
            view_path,
            (execution.research_results_root,),
            plan=selected.selection_plan,
        )
        publish_selection_plan(selected.selection_plan, runtime / "selection-plans")
        orchestrator = AutonomousCampaignOrchestrator(
            campaign=selected.campaign,
            family=selected.family,
            budget=selected.research_budget,
            template=selected.template,
            manifest=selected.manifest,
            initial_ledger_snapshot=selected.initial_ledger_snapshot,
            ledger_service=ResearchLedgerService(runtime / "ledger"),
            ledger_id=selected.ledger_id,
            search_policy=selected.search_policy,
            context_budget=selected.context_budget,
            campaign_policy=selected.campaign_policy,
            agent_run_policy=selected.agent_run_policy,
            agent_driver=HostedProposalOnlyDriver(),
            execution_port=execution,
            exchange_root=runtime / "legacy-exchanges-unused",
            event_root=runtime / "campaign-events",
            selection_service=selection,
            selection_artifact_root=runtime / "selection-reports",
            autonomous_report_root=runtime / "legacy-loop-reports-unused",
            execution_bindings=selected.execution_bindings,
            selection_finalization_profile=selected.selection_finalization_profile,
        )
        service = HostedCampaignApplicationService(
            HostedProtocolService(
                store,
                clock=protocol_clock,
                verify_inputs=lambda value: service.verify_registered_inputs(value),
            ),
            business_lock_root=authority_root / "business-locks",
        )
        service.register_inputs(
            native_spec, HostedCampaignInputs(orchestrator, selected.initial_events, lambda _: None)
        )
        return SimpleNamespace(application=service)

    def hydrate(_):
        fd = private_memory_fd("native-synthetic-lifecycle-capability")
        try:
            os.write(fd, b"S" * 32)
            os.lseek(fd, 0, os.SEEK_SET)
            if fd != 100:
                os.dup2(fd, 100, inheritable=False)
        finally:
            if fd != 100:
                os.close(fd)

    values = {
        "HostedDeploymentProfile": SimpleNamespace(configuration_hash="a" * 64),
        "HostedServiceConfiguration": SimpleNamespace(
            business_configuration_hash="b" * 64, principals=(SimpleNamespace(capability_fd=100),)
        ),
        "HostedBusinessLoaderConfiguration": SimpleNamespace(business_inputs_hash="c" * 64),
        "HostedFrozenBusinessInputs": bundle,
    }
    monkeypatch.setattr(probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(probe, "hydrate_service_capabilities", hydrate)
    monkeypatch.setattr(
        probe, "read_hashed_configuration", lambda root, hash, cls: values[cls.__name__]
    )
    monkeypatch.setattr(
        business_verification,
        "build_hosted_execution_adapter",
        lambda selected, **kwargs: QuantosResearchExecutionAdapter(
            **{
                **adapter_args,
                "campaign": selected.campaign,
                "budget": selected.research_budget,
                "output_root": kwargs["runtime_root"] / "execution",
            }
        ),
    )
    sources = SimpleNamespace(
        deployment=SimpleNamespace(
            spec=spec,
            bundle=bundle,
            profile=SimpleNamespace(content_hash=profile_hash),
            paths=SimpleNamespace(offline_inputs=tmp_path, provenance=tmp_path / "provenance"),
        )
    )
    for case in probe.HOSTED_LIFECYCLE_CASES:
        root = tmp_path / "cases" / case
        authority, channel = root / "authority", root / "channel"
        authority.mkdir(parents=True)
        channel.mkdir()
        probe.run_lifecycle_probe(
            profile_hash, case, authority_root=authority, channel_root=channel
        )
        observation = json.loads((channel / "negative-observation.json").read_bytes())
        phases = lifecycle_process_phases(case)
        records = {
            phase: json.loads((channel / "process-records" / f"{phase}.json").read_bytes())
            for phase in phases
        }
        roots = {
            phase: channel / "snapshots" / phase / "authority"
            for phase in ("before", "after-actions", "after-recovery", "after")
        }
        original = (raw_inventory(authority), directory_inventory(authority))
        checked = verify_lifecycle_scenario(
            case, roots, records, observation, parent_pid=os.getpid(), sources=sources
        )
        assert checked and (raw_inventory(authority), directory_inventory(authority)) == original
        for mutation in (
            "charge-reset",
            "exit-phase",
            "response-receipt",
            "fresh-bootstrap",
            "clock",
        ):
            altered = deepcopy(records)
            obs = deepcopy(observation)
            if mutation == "exit-phase":
                obs["process_exits"][-1] = obs["process_exits"][0]
            elif mutation == "response-receipt":
                altered["response-repeat"]["result_json"]["outcome"] = (
                    "ACCEPTED" if case != "submit_before_cancel" else "REJECTED"
                )
            elif mutation == "fresh-bootstrap":
                altered["recovery-2"]["fresh_application_bootstrap"] = False
            elif mutation == "clock":
                altered["response-repeat"]["clock"] = spec.started_at.isoformat()
            else:
                altered["recovery-2"]["result_json"]["protocol"]["used_unique_submissions"] = 0
            with pytest.raises(HostedQualificationError):
                verify_lifecycle_scenario(
                    case, roots, altered, obs, parent_pid=os.getpid(), sources=sources
                )
        assert (raw_inventory(authority), directory_inventory(authority)) == original

    from quantos.infrastructure import hosted_budget_probe as budget_probe
    from quantos.infrastructure.hosted_business_file_closure import (
        verify_native_authority_file_closure,
    )
    from quantos.infrastructure.hosted_business_verification import (
        build_verified_business_orchestrator,
        verify_hosted_business_root,
    )

    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "true")
    monkeypatch.setattr(budget_probe, "bootstrap_hosted_service", boot)
    monkeypatch.setattr(budget_probe, "hydrate_service_capabilities", hydrate)
    monkeypatch.setattr(
        budget_probe, "read_hashed_configuration", lambda root, hash, cls: values[cls.__name__]
    )
    for case, recipe in HOSTED_BUDGET_CASES.items():
        selected = derive_hosted_budget_case(bundle, case, input_root=tmp_path)
        active_bundle[0] = selected
        values["HostedFrozenBusinessInputs"] = selected
        root = tmp_path / "budget-cases" / case
        authority, channel = root / "authority", root / "channel"
        authority.mkdir(parents=True)
        channel.mkdir()
        budget_probe.run_budget_probe(
            profile_hash, case, authority_root=authority, channel_root=channel
        )
        from quantos.infrastructure.hosted_budget_verification import (
            BUDGET_PROCESS_PHASES,
            BUDGET_SNAPSHOT_PHASES,
            verify_budget_scenario,
        )

        budget_sources = SimpleNamespace(
            deployment=SimpleNamespace(
                bundle=selected,
                profile=SimpleNamespace(content_hash=profile_hash),
                paths=sources.deployment.paths,
            )
        )
        budget_roots = {
            phase: channel / "snapshots" / phase / "authority" for phase in BUDGET_SNAPSHOT_PHASES
        }
        budget_processes = {
            phase: json.loads((channel / "process-records" / f"{phase}.json").read_bytes())
            for phase in BUDGET_PROCESS_PHASES
        }
        budget_observation = json.loads((channel / "negative-observation.json").read_bytes())
        budget_args = dict(parent_pid=os.getpid(), sources=budget_sources)
        checked = verify_budget_scenario(
            case, budget_roots, budget_processes, budget_observation, **budget_args
        )
        assert checked
        for field, replacement in (
            ("fresh_application_bootstrap", False),
            ("clock", "2000-01-01T00:00:00+00:00"),
            ("result_hash", "0" * 64),
            ("network_attempts", ["SOCKET_CONNECT"]),
            ("parent_pid", 0),
        ):
            altered = deepcopy(budget_processes)
            altered["exercise"][field] = replacement
            with pytest.raises(HostedQualificationError):
                verify_budget_scenario(
                    case, budget_roots, altered, budget_observation, **budget_args
                )
        before = raw_inventory(authority), directory_inventory(authority)
        facts = verify_hosted_business_root(
            authority,
            selected,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
        state, native, events = build_verified_business_orchestrator(
            authority,
            selected,
            deployment_profile_hash=profile_hash,
            input_root=tmp_path,
            provenance_workspace=tmp_path / "provenance",
        )
        verify_native_authority_file_closure(
            authority, selected, state, native, events, business=facts
        )
        assert facts.report.state == "EXHAUSTED" and facts.report.reason == recipe.expected_reason
        assert (
            facts.report.research_run_status == "FAILED"
            and facts.report.research_verdict == "NOT_EVALUATED"
        )
        assert facts.report.selection_report_hash is None
        exercise = json.loads((channel / "process-records/exercise.json").read_bytes())
        if recipe.native_execution:
            assert len(exercise["execute_calls"]) == 1 and exercise["workflow_calls"]
        else:
            assert exercise["execute_calls"] == exercise["workflow_calls"] == []
        assert exercise["network_attempts"] == []
        if recipe.action in ("reject_frames", "global_cap"):
            assert len(exercise["result_json"]["over_cap_hashes"]) == 32
            assert len(set(exercise["result_json"]["over_cap_hashes"])) == 1
            assert (
                exercise["result_json"]["repeat_receipt_hash"]
                == HostedSubmissionReceipt.model_validate(
                    exercise["result_json"]["receipts"][0]
                ).content_hash
            )
        for phase in ("recovery-1", "recovery-2"):
            record = json.loads((channel / "process-records" / f"{phase}.json").read_bytes())
            assert (
                record["execute_calls"]
                == record["workflow_calls"]
                == record["network_attempts"]
                == []
            )
            assert record["result_json"]["status"] == exercise["result_json"]["status"]
        assert (raw_inventory(authority), directory_inventory(authority)) == before
