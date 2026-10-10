"""Functional state-machine tests; fake receipts do not establish live qualification."""

from __future__ import annotations

import multiprocessing
import os
import pickle
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_autonomous_campaign import NOW, _Inputs, _inputs, _proposal

from quantos.application.autonomous_execution import AutonomousExecutionReceipt
from quantos.application.hosted_campaign import (
    HostedCampaignApplicationService,
    HostedCampaignInputs,
)
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.autonomous import (
    AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE,
    P14DQ_REPORT_ONLY_FINALIZATION_PROFILE,
    AutonomousExecutionRequest,
    AutonomousExecutionResult,
    AutonomousSelectionFinalizationProfile,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.hosted import (
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetPolicy,
    HostedCampaignReport,
    HostedCampaignSpec,
    HostedResearchBudgetFact,
    HostObservation,
    HostReportedUsage,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore


class _DiskExecution:
    """Test-only deterministic receipt producer, never a Qlib qualification substitute."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def execution_compute_charge(self, request: AutonomousExecutionRequest) -> int:
        return 1

    def execute(self, request: AutonomousExecutionRequest) -> AutonomousExecutionResult:
        self.root.mkdir(parents=True, exist_ok=True)
        counter = self.root / "calls"
        count = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(count + 1))
        time.sleep(0.05)
        outcome = AutonomousExecutionResult(
            request_hash=request.content_hash,
            outcome=TrialOutcome.EXECUTION_FAILED,
            execution_requested=True,
            compute_seconds=1,
        )
        receipt = AutonomousExecutionReceipt(request=request, outcome=outcome)
        atomic_write_bytes(
            self.root / f"{request.execution_identity}.json", receipt.canonical_bytes()
        )
        return self.verified_completed_execution(request)  # type: ignore[return-value]

    def verified_completed_execution(
        self, request: AutonomousExecutionRequest
    ) -> AutonomousExecutionResult | None:
        path = self.root / f"{request.execution_identity}.json"
        if not path.exists():
            return None
        receipt = AutonomousExecutionReceipt.model_validate_json(path.read_bytes())
        if receipt.request != request:
            raise ArtifactIntegrityError("test receipt request mismatch")
        return receipt.outcome.model_copy(
            update={
                "execution_artifact_hash": receipt.content_hash,
                "evidence_hashes": (receipt.content_hash,),
            }
        )


@dataclass
class _Fixture:
    root: Path
    inputs: _Inputs
    spec: HostedCampaignSpec
    service: HostedCampaignApplicationService
    clock: list[Any]


def _spec(inputs: _Inputs, *, requests: int = 3, submissions: int = 5) -> HostedCampaignSpec:
    assert inputs.selection.plan is not None
    return HostedCampaignSpec(
        campaign=inputs.campaign,
        research_budget=inputs.budget,
        hosted_budget=HostedBudgetPolicy(
            max_requests=min(requests, inputs.budget.max_agent_runs),
            max_unique_submissions=submissions,
            max_submissions_per_request=submissions,
            max_response_bytes=262144,
            max_proposal_bytes=262144,
            max_request_bytes=1048576,
            request_ttl_seconds=60,
        ),
        candidate_manifest_hash=inputs.manifest.content_hash,
        factor_template_hash=inputs.template.content_hash,
        selection_plan_hash=inputs.selection.plan.content_hash,
        selection_finalization_profile_hash=AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE.content_hash,
        execution_bindings=inputs.execution_bindings,
        search_policy_hash=inputs.search_policy.content_hash,
        context_budget_policy_hash=inputs.context_budget.content_hash,
        campaign_policy_hash=inputs.campaign_policy.content_hash,
        agent_run_policy_hash=inputs.agent_policy.content_hash,
        requested_model_configuration_hash=inputs.agent_policy.requested_model_configuration_hash,
        deployment_profile_hash="d" * 64,
        contract_hash="14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df",
        acceptance_hash="e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e",
        started_at=NOW,
    )


def _service(
    root: Path,
    inputs: _Inputs,
    spec: HostedCampaignSpec,
    *,
    fault: str | None = None,
    clock: list[Any] | None = None,
    selection_profile: AutonomousSelectionFinalizationProfile = (
        AUTONOMOUS_DEFAULT_FINALIZATION_PROFILE
    ),
) -> HostedCampaignApplicationService:
    clock = clock or [NOW]
    holder: list[HostedCampaignApplicationService] = []
    protocol = HostedProtocolService(
        HostedProtocolStore(root / "protocol"),
        clock=lambda: clock[0],
        verify_inputs=lambda value: holder[0].verify_registered_inputs(value),
    )

    def hook(point: str) -> None:
        if point == fault:
            os._exit(73)

    service = HostedCampaignApplicationService(
        protocol, business_lock_root=root / "business-locks", fault_hook=hook
    )
    holder.append(service)
    o = inputs.orchestrator(
        root,
        (_proposal(inputs, 0),),
        execution=_DiskExecution(root / "executions"),
        selection_finalization_profile=selection_profile,
    )  # type: ignore[arg-type]
    service.register_inputs(spec, HostedCampaignInputs(o, inputs.initial_events, lambda _: None))
    return service


def _fixture(root: Path, **budget: int) -> _Fixture:
    if "max_trials" in budget and "max_distinct_candidates" not in budget:
        budget["max_distinct_candidates"] = min(2, budget["max_trials"])
    if "max_executions" in budget and "max_validation_rounds" not in budget:
        budget["max_validation_rounds"] = budget["max_executions"]
    inputs = _inputs(root / "business", **budget)
    spec = _spec(inputs)
    clock = [NOW]
    service = _service(root, inputs, spec, clock=clock)
    # Test-only management fixture for fresh spawned processes; never host input.
    (root / "test-management-inputs.pickle").write_bytes(pickle.dumps((inputs, spec)))
    return _Fixture(root, inputs, spec, service, clock)


def _response(f: _Fixture, request: HostedAgentRequest, index: int = 0) -> bytes:
    proposal = _proposal(f.inputs, index).canonical_bytes().decode()
    return HostedAgentResponse(
        request_hash=request.content_hash,
        campaign_hash=f.spec.campaign_hash,
        transport_ordinal=request.transport_ordinal,
        context_pack_hash=request.context_pack_hash,
        attempt_identity=request.attempt_identity,
        proposal_json=proposal,
        proposal_hash=sha256_bytes(proposal.encode()),
        host_observation=HostObservation(
            requested_configuration_hash=f.spec.requested_model_configuration_hash,
            reported_usage=HostReportedUsage(unavailable_reason="FUNCTIONAL_FAKE"),
            unavailable_reasons=(
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "HOST_TRANSCRIPT_UNAVAILABLE",
            ),
        ),
    ).canonical_bytes()


def _worker(root: str, campaign: str, fault: str | None, queue: Any) -> None:
    path = Path(root)
    inputs, spec = pickle.loads((path / "test-management-inputs.pickle").read_bytes())
    service = _service(path, inputs, spec, fault=fault)
    try:
        status = service.resume(campaign)
        queue.put((status.state, status.reason))
    except Exception as error:
        queue.put((type(error).__name__, str(error)))


def _run(root: Path, campaign: str, fault: str | None = None) -> tuple[int | None, Any]:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_worker, args=(str(root), campaign, fault, queue))
    process.start()
    process.join(30)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("fresh-process recovery timed out")
    result = queue.get(timeout=2) if process.exitcode == 0 else None
    return process.exitcode, result


def test_suspend_queries_and_new_process_keep_original_request(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    status = f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None and status.state == "WAITING_FOR_AGENT"
    inventory = {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    assert _run(tmp_path, f.spec.campaign_hash) == (0, ("WAITING_FOR_AGENT", None))
    for _ in range(2):
        assert (
            f.service.pending(f.spec.campaign_hash).canonical_bytes() == request.canonical_bytes()
        )
        assert f.service.status(f.spec.campaign_hash) == status
    assert inventory == {
        str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    assert status.protocol.used_requests == 1


@pytest.mark.parametrize("window", ["research_initial", "request_checkpoint"])
def test_initial_reservation_and_checkpoint_recover_without_extra_charge(
    tmp_path: Path, window: str
) -> None:
    from quantos.infrastructure.hosted_verification import raw_inventory, verify_protocol_root

    f = _fixture(tmp_path)
    f.service.protocol.start(f.spec.content_hash)
    assert _run(tmp_path, f.spec.campaign_hash, window)[0] == 73
    crashed_state = f.service.protocol.store.snapshot(f.spec.campaign_hash, recover=False)
    crashed_request = crashed_state.active_request
    assert (crashed_request is not None) == (window == "request_checkpoint")
    assert _run(tmp_path, f.spec.campaign_hash) == (0, ("WAITING_FOR_AGENT", None))
    state = f.service.protocol.store.snapshot(f.spec.campaign_hash, recover=False)
    assert len(state.requests) == 1
    if crashed_request is not None:
        assert state.requests == (crashed_request,)
    facts = [
        HostedResearchBudgetFact.model_validate_json(data)
        for data in state.artifacts.values()
        if b'"schema_version":"hosted-research-budget-fact/v1"' in data
    ]
    assert len(facts) == 1 and facts[0].phase == "INITIAL"
    assert facts[0].used_trials == facts[0].used_executions == facts[0].used_compute_units == 0
    assert state.budget.used_requests == 1 and state.budget.used_unique_submissions == 0
    assert not (tmp_path / "executions" / "calls").exists()
    inventory = raw_inventory(tmp_path)
    assert _run(tmp_path, f.spec.campaign_hash) == (0, ("WAITING_FOR_AGENT", None))
    assert raw_inventory(tmp_path) == inventory
    verify_protocol_root(tmp_path / "protocol", f.spec.campaign_hash)


@pytest.mark.parametrize(
    "window",
    [
        "prepared",
        "started",
        "execution_receipt",
        "completed_intent",
        "trial_event",
        "ledger",
        "step_completed",
    ],
)
def test_durable_windows_recover_in_fresh_process(tmp_path: Path, window: str) -> None:
    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    crashed = _run(tmp_path, f.spec.campaign_hash, window)
    assert crashed[0] == 73, crashed
    recovered = _run(tmp_path, f.spec.campaign_hash)
    if window == "started":
        assert recovered == (0, ("RECOVERY_REQUIRED", "EXECUTION_UNCERTAIN"))
        assert not (tmp_path / "executions" / "calls").exists()
        state = f.service.protocol.store.snapshot(f.spec.campaign_hash)
        report = state.artifact(
            f.service.status(f.spec.campaign_hash).report_hash, HostedCampaignReport
        )
        assert report.remaining_candidate_hashes == report.candidate_hashes
        assert f.service.status(f.spec.campaign_hash).research_budget_hash is not None
    else:
        assert recovered == (0, ("WAITING_FOR_AGENT", None))
        assert (tmp_path / "executions" / "calls").read_text() == "1"
        assert f.service.protocol.pending(f.spec.campaign_hash).transport_ordinal == 2
    assert _run(tmp_path, f.spec.campaign_hash) == recovered


def test_finite_family_final_report_and_restart_preserve_denominator(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    for index in range(2):
        request = f.service.pending(f.spec.campaign_hash)
        assert request is not None
        raw = _response(f, request, index)
        receipt = f.service.submit(request.content_hash, raw, "functional.host")
        assert f.service.submit(request.content_hash, raw, "functional.host") == receipt
        result = f.service.resume(f.spec.campaign_hash)
    assert result.state == "COMPLETED"
    state = f.service.protocol.store.snapshot(f.spec.campaign_hash)
    report = state.artifact(result.report_hash, HostedCampaignReport)
    assert len(report.attempted_candidate_hashes) == 2 and not report.remaining_candidate_hashes
    assert len(report.trial_hashes) == 2
    assert report.research_run_status == "FAILED" and report.research_verdict == "NOT_EVALUATED"
    assert report.qualification_eligibility == "NOT_QUALIFIED"
    assert _run(tmp_path, f.spec.campaign_hash) == (0, ("COMPLETED", "ALL_CANDIDATES_TERMINAL"))
    assert (tmp_path / "executions" / "calls").read_text() == "2"


@pytest.mark.parametrize(
    "reason", ["cancel", "expire", "submission", "trial", "execution", "compute"]
)
def test_stops_keep_complete_family_and_no_extra_execution(tmp_path: Path, reason: str) -> None:
    budgets = {
        "trial": {"max_trials": 1},
        "execution": {"max_executions": 1},
        "compute": {"max_compute_seconds": 1},
    }
    f = _fixture(tmp_path, **budgets.get(reason, {}))
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    if reason == "cancel":
        f.service.cancel(request.content_hash, "functional.host")
    elif reason == "expire":
        f.clock[0] += timedelta(seconds=61)
    elif reason == "submission":
        for index in range(5):
            f.service.submit(
                request.content_hash, canonical_json_bytes({"bad": index}), "functional.host"
            )
    else:
        f.service.submit(request.content_hash, _response(f, request), "functional.host")
    status = f.service.resume(f.spec.campaign_hash)
    assert status.state in ("CANCELLED", "EXPIRED", "EXHAUSTED")
    state = f.service.protocol.store.snapshot(f.spec.campaign_hash)
    report = state.artifact(status.report_hash, HostedCampaignReport)
    assert len(report.candidate_hashes) == 2 and report.remaining_candidate_hashes
    assert report.research_run_status == "FAILED"
    assert status.protocol.used_requests == 1


@pytest.mark.parametrize("reason", ("cancel", "expire", "submission"))
def test_incomplete_dq_stop_persists_failed_accounting_without_selection(
    tmp_path: Path, reason: str
) -> None:
    inputs = _inputs(tmp_path / "inputs")
    profile = P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
    spec = _spec(inputs, submissions=2)
    spec = HostedCampaignSpec.model_validate(
        {
            **spec.model_dump(mode="python"),
            "selection_finalization_profile_hash": profile.content_hash,
        }
    )
    authority = tmp_path / "authority"
    clock = [NOW]
    service = _service(authority, inputs, spec, clock=clock, selection_profile=profile)
    service.start(spec.content_hash)
    request = service.pending(spec.campaign_hash)
    assert request is not None
    if reason == "cancel":
        service.cancel(request.content_hash, "functional.host")
    elif reason == "expire":
        clock[0] += timedelta(seconds=61)
    else:
        for index in range(2):
            service.submit(
                request.content_hash, canonical_json_bytes({"bad": index}), "functional.host"
            )
    status = service.resume(spec.campaign_hash)
    state = service.protocol.store.snapshot(spec.campaign_hash, recover=False)
    report = state.artifact(status.report_hash, HostedCampaignReport)
    assert (
        status.state
        == {"cancel": "CANCELLED", "expire": "EXPIRED", "submission": "EXHAUSTED"}[reason]
    )
    assert report.research_run_status == "FAILED" and report.research_verdict == "NOT_EVALUATED"
    assert report.selection_report_hash is None and report.trial_hashes == ()
    assert report.remaining_candidate_hashes == report.candidate_hashes
    assert "P14DQ_INCOMPLETE_DENOMINATOR_SELECTION_NOT_PERFORMED" in report.limitations
    assert not inputs.paths["selection-reports"].exists()
    assert not (authority / "executions").exists()
    bound_inputs = service._registered(spec.campaign_hash)
    for changes in (
        {"limitations": report.limitations[:-1]},
        {"limitations": (*report.limitations, "UNATTESTED_EXTRA_LIMIT")},
        {"selection_report_hash": "a" * 64},
        {"research_run_status": "SUCCEEDED", "research_verdict": "SELECTED"},
        {"research_verdict": "NO_SELECTION"},
    ):
        # Untrusted decoded claims must be rejected even before contract validation.
        with pytest.raises(ArtifactIntegrityError, match="claims selection or different limits"):
            service._verify_report(state, report.model_copy(update=changes), bound_inputs)
    from quantos.infrastructure.hosted_verification import directory_inventory, raw_inventory

    before = raw_inventory(authority), directory_inventory(authority)
    fresh = _service(authority, inputs, spec, clock=clock, selection_profile=profile)
    assert fresh.resume(spec.campaign_hash) == status
    assert (raw_inventory(authority), directory_inventory(authority)) == before


def test_complete_dq_family_still_requires_native_preselection_verifier(tmp_path: Path) -> None:
    from quantos.application.autonomous import AutonomousOrchestrationError

    inputs = _inputs(tmp_path / "inputs")
    profile = P14DQ_REPORT_ONLY_FINALIZATION_PROFILE
    spec = HostedCampaignSpec.model_validate(
        {
            **_spec(inputs).model_dump(mode="python"),
            "selection_finalization_profile_hash": profile.content_hash,
        }
    )
    authority = tmp_path / "authority"
    service = _service(authority, inputs, spec, selection_profile=profile)
    fixture = _Fixture(authority, inputs, spec, service, [NOW])
    service.start(spec.content_hash)
    for index in range(2):
        request = service.pending(spec.campaign_hash)
        assert request is not None
        service.submit(request.content_hash, _response(fixture, request, index), "functional.host")
        if index == 0:
            assert service.resume(spec.campaign_hash).state == "WAITING_FOR_AGENT"
        else:
            # This functional receipt producer has no native DQ verifier. Full
            # denominators must continue to fail the existing gate, not skip it.
            with pytest.raises(AutonomousOrchestrationError, match="DQ preselection verifier"):
                service.resume(spec.campaign_hash)
    state = service.protocol.store.snapshot(spec.campaign_hash, recover=False)
    assert not service.verify_research_facts(state).reports
    facts = service.verify_research_facts(state)
    assert len(tuple(step for step in facts.steps if step.phase == "COMPLETED")) == 2


def test_concurrent_resumes_do_not_mistake_inflight_started_for_uncertainty(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_worker, args=(str(tmp_path), f.spec.campaign_hash, None, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert [queue.get(timeout=2) for _ in processes] == [("WAITING_FOR_AGENT", None)] * 2
    assert (tmp_path / "executions" / "calls").read_text() == "1"


def test_registration_and_pending_ledger_changes_fail_closed(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    altered = f.spec.model_copy(
        update={
            "execution_bindings": f.spec.execution_bindings.model_copy(
                update={"qlib_version": "0.9.8"}
            )
        }
    )
    with pytest.raises(ArtifactIntegrityError, match="frozen hosted spec"):
        f.service.register_inputs(
            altered,
            HostedCampaignInputs(
                f.inputs.orchestrator(tmp_path, (_proposal(f.inputs, 0),)),
                f.inputs.initial_events,
                lambda _: None,
            ),
        )


@pytest.mark.parametrize("window", ["selection_ledger", "final_report"])
def test_terminal_report_windows_recover_in_new_process(tmp_path: Path, window: str) -> None:
    f = _fixture(tmp_path, max_trials=1)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    crashed = _run(tmp_path, f.spec.campaign_hash, window)
    assert crashed[0] == 73, crashed
    assert _run(tmp_path, f.spec.campaign_hash) == (0, ("EXHAUSTED", "BUDGET_EXHAUSTED"))
    assert (tmp_path / "executions" / "calls").read_text() == "1"


def test_known_duplicate_accounts_trial_without_second_execution(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    for _ in range(2):
        request = f.service.pending(f.spec.campaign_hash)
        assert request is not None
        assert len(request.business_request.candidate_options) == 2
        assert (
            f.service.submit(request.content_hash, _response(f, request), "functional.host").outcome
            == "ACCEPTED"
        )
        f.service.resume(f.spec.campaign_hash)
    events = f.inputs.orchestrator(tmp_path, (_proposal(f.inputs, 0),)).event_store.load(
        f.inputs.orchestrator(tmp_path, (_proposal(f.inputs, 0),)).governor,
        f.inputs.campaign,
        f.inputs.budget,
    )
    trials = [event.trial for event in events if getattr(event, "trial", None)]
    assert [trial.outcome for trial in trials] == [
        TrialOutcome.EXECUTION_FAILED,
        TrialOutcome.DUPLICATE_CANDIDATE,
    ]
    assert (tmp_path / "executions" / "calls").read_text() == "1"


def test_known_invalid_proposal_forms_schema_invalid_trial(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    raw = HostedAgentResponse.model_validate_json(_response(f, request))
    proposal = canonical_json_bytes(
        {"candidate_hash": f.inputs.manifest.candidates[0].content_hash, "unexpected": True}
    ).decode()
    response = raw.model_copy(
        update={"proposal_json": proposal, "proposal_hash": sha256_bytes(proposal.encode())}
    )
    assert (
        f.service.submit(
            request.content_hash, response.canonical_bytes(), "functional.host"
        ).outcome
        == "ACCEPTED"
    )
    f.service.resume(f.spec.campaign_hash)
    o = f.inputs.orchestrator(tmp_path, (_proposal(f.inputs, 0),))
    events = o.event_store.load(o.governor, o.campaign, o.budget)
    trials = [event.trial for event in events if getattr(event, "trial", None)]
    assert trials[0].outcome == TrialOutcome.SCHEMA_INVALID
    assert not (tmp_path / "executions" / "calls").exists()


def test_compute_reservation_stops_before_pipeline_when_quote_exceeds_remaining(
    tmp_path: Path,
) -> None:
    f = _fixture(tmp_path, max_compute_seconds=1)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    o = f.inputs.orchestrator(
        tmp_path, (_proposal(f.inputs, 0),), execution=_DiskExecution(tmp_path / "executions")
    )
    o.execution_port.execution_compute_charge = lambda request: 2
    f.service.register_inputs(
        f.spec, HostedCampaignInputs(o, f.inputs.initial_events, lambda _: None)
    )
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    status = f.service.resume(f.spec.campaign_hash)
    assert status.state == "EXHAUSTED" and status.reason == "RESEARCH_RESERVATION_EXHAUSTED"
    assert not (tmp_path / "executions" / "calls").exists()


def test_unaccounted_ledger_change_rejects_pending_request(tmp_path: Path) -> None:
    from quantos.contracts.ledger import (
        LedgerAssertionAuthority,
        LedgerObjectAccess,
        ResearchLedgerNodeKind,
        ResearchLedgerObjectRef,
    )

    f = _fixture(tmp_path)
    f.service.start(f.spec.content_hash)
    request = f.service.pending(f.spec.campaign_hash)
    assert request is not None
    f.service.submit(request.content_hash, _response(f, request), "functional.host")
    extra = canonical_json_bytes({"body": "unaccounted ledger addition"})
    f.inputs.ledger.append(
        ledger_id=f.inputs.ledger_id,
        node_id="external-unaccounted",
        node_kind=ResearchLedgerNodeKind.EVIDENCE,
        object_ref=ResearchLedgerObjectRef(
            object_hash=sha256_bytes(extra),
            media_type="application/json",
            source_domain="functional-negative",
            access=LedgerObjectAccess.PUBLIC_HISTORY,
        ),
        object_bytes=extra,
        authority=LedgerAssertionAuthority.SOURCE_ASSERTION,
        occurred_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ArtifactIntegrityError, match="pending request Ledger was changed"):
        f.service.resume(f.spec.campaign_hash)
    assert not (tmp_path / "executions" / "calls").exists()
