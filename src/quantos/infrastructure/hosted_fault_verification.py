"""Read-only physical-exit scenario facts, below the original-source gate.

The durable subset deliberately cannot grant the full Q05 gate: atomic fsync and
corruption cases must also have original management evidence before that wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import (
    HostedCampaignStatus,
    HostedJournalEntry,
    HostedProtocolStatus,
    HostedRequestTerminalReceipt,
    HostedResearchBudgetFact,
    HostedSubmissionReceipt,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_admission_checkpoint import verify_native_admission_checkpoint
from quantos.infrastructure.hosted_business_file_closure import verify_native_authority_file_closure
from quantos.infrastructure.hosted_business_verification import (
    build_verified_business_orchestrator,
    principal_business_inventory,
    verify_hosted_business_root,
    verify_native_business_budgets,
    verify_native_business_steps,
)
from quantos.infrastructure.hosted_fault_cases import FAULT_SNAPSHOT_PHASES, HOSTED_FAULT_WINDOWS
from quantos.infrastructure.hosted_negative_origin import require, verify_managed_fixture_source
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)

FAULT_PROCESS_PHASES = ("crash", "recovery-1", "recovery-2")


def verify_q05_durable_subset(
    bundle_root: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Require all fixed durable windows and original kernel/source facts.

    This is a diagnostic subset, never wired as a full Q05 PASS: file/directory
    fsync and corruption cases still require their own original-source predicates.
    """
    require(case.case_id == "Q05", "Q05 case identity differs")
    indexed = {root.name: root for root in case.roots}
    require(
        set(indexed)
        == {f"{name}-{phase}" for name in HOSTED_FAULT_WINDOWS for phase in FAULT_SNAPSHOT_PHASES},
        "Q05 complete durable matrix is absent",
    )
    evidence: list[tuple[str, dict[str, object], bytes]] = []
    for path in case.evidence_paths:
        data = read_relative(bundle_root, path)
        try:
            payload = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        evidence.append((path, payload, data))
    deployment = sources.deployment
    checked: set[str] = set()
    for name in HOSTED_FAULT_WINDOWS:
        prefix = f"qualification-cases/Q05/{name}"
        target = deployment.root / prefix
        roots: dict[str, Path] = {}
        inventories: dict[str, HostedRawInventory] = {}
        for phase in FAULT_SNAPSHOT_PHASES:
            root = indexed[f"{name}-{phase}"]
            require(
                root.campaign_hash == deployment.bundle.campaign.content_hash,
                "Q05 phase campaign differs",
            )
            sidecar = read_relative(bundle_root, root.raw_inventory_path)
            source = sources.files[root.raw_inventory_path]
            require(
                source.source_path == f"{prefix}/channel/phase-inventories/{phase}.json",
                "Q05 inventory has no original fixed phase source",
            )
            inventory = parse_hosted_contract(sidecar, HostedRawInventory, max_bytes=16_777_216)
            original = target / (
                "authority" if phase == "after" else f"channel/snapshots/{phase}/authority"
            )
            require(raw_inventory(original) == inventory, "Q05 original phase bytes changed")
            # Empty REGISTER/start before roots bind the original sidecar and fresh
            # prelaunch; their file set has no member from which to infer a prefix.
            if inventory.files:
                require(
                    sources.root_origin(root, inventory) == original,
                    "Q05 phase combines unrelated original roots",
                )
            exported = bundle_root / root.logical_path
            verify_raw_inventory(exported, inventory)
            roots[phase], inventories[phase] = exported, inventory
            checked.add(sha256_bytes(sidecar))
        observations = [
            (path, payload, data)
            for path, payload, data in evidence
            if payload.get("schema_version") == "hosted-fault-observation/v1"
            and payload.get("case") == name
        ]
        runs = [
            (path, payload, data)
            for path, payload, data in evidence
            if payload.get("schema_version") == "hosted-manager-negative-run/v1"
            and payload.get("case") == name
        ]
        require(
            len(observations) == len(runs) == 1,
            "Q05 original invocation or observation is ambiguous",
        )
        observation_path, observation, observation_bytes = observations[0]
        run_path, run, run_bytes = runs[0]
        kernel, hashes = verify_managed_fixture_source(
            evidence,
            sources,
            family="Q05",
            name=name,
            observation_path=observation_path,
            observation=observation,
            observation_bytes=observation_bytes,
            run_path=run_path,
            run=run,
            run_bytes=run_bytes,
            before_inventory=inventories["before"],
            after_inventory=inventories["after"],
        )
        checked.update(hashes)
        process_records: dict[str, dict[str, object]] = {}
        expected_paths = {
            f"{prefix}/channel/process-records/{phase}{suffix}.json"
            for phase in FAULT_PROCESS_PHASES
            for suffix in ("", "-exit")
        }
        paths: set[str] = set()
        for path, payload, data in evidence:
            original_path = sources.files[path].source_path
            if not original_path.startswith(f"{prefix}/channel/process-records/"):
                continue
            require(
                original_path in expected_paths and original_path not in paths,
                "Q05 extra or duplicate process evidence",
            )
            paths.add(original_path)
            phase = payload.get("phase")
            require(
                isinstance(phase, str) and phase in FAULT_PROCESS_PHASES,
                "Q05 process phase differs",
            )
            phase = cast(str, phase)
            if original_path.endswith("-exit.json"):
                expected_exit = next(
                    (
                        item
                        for item in cast(list[dict[str, object]], observation["process_exits"])
                        if item.get("phase") == phase
                    ),
                    None,
                )
                require(payload == expected_exit, "Q05 original parent waitpid record differs")
            else:
                require(
                    payload.get("schema_version") == "hosted-fault-process-observation/v1"
                    and original_path == f"{prefix}/channel/process-records/{phase}.json"
                    and phase not in process_records,
                    "Q05 process observation origin differs",
                )
                process_records[phase] = payload
            checked.add(sha256_bytes(data))
        require(paths == expected_paths, "Q05 physical process evidence is incomplete")
        security = cast(list[str], kernel["service_process_security"])
        nspid = [line.split(":", 1)[1].split() for line in security if line.startswith("NSpid:")]
        require(
            len(nspid) == 1 and bool(nspid[0]) and all(value.isdecimal() for value in nspid[0]),
            "Q05 kernel parent PID is absent",
        )
        checked.update(
            verify_fault_recovery_scenario(
                name,
                roots,
                process_records,
                observation,
                parent_pid=int(nspid[0][-1]),
                sources=sources,
            )
        )
    return tuple(sorted(checked))


def verify_fault_recovery_scenario(
    name: str,
    roots: dict[str, Path],
    records: dict[str, dict[str, object]],
    observation: dict[str, object],
    *,
    parent_pid: int,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    """Inspect exact phase bytes and native receipts; never bootstrap or repair.

    Callers must first bind these paths and all observations to the independent
    original manager export and actual fixed installed/kernel invocation.
    """
    require(name in HOSTED_FAULT_WINDOWS, "unknown fixed durable fault window")
    require(set(roots) == set(FAULT_SNAPSHOT_PHASES), "Q05 phase roots are incomplete")
    require(set(records) == set(FAULT_PROCESS_PHASES), "Q05 child records are incomplete")
    window = HOSTED_FAULT_WINDOWS[name]
    deployment = sources.deployment
    bundle = deployment.bundle
    campaign = bundle.campaign.content_hash
    inventories = {phase: raw_inventory(path) for phase, path in roots.items()}
    require(inventories["recovered"] == inventories["after"], "Q05 second recovery changed bytes")
    checked: set[str] = {inventory.content_hash for inventory in inventories.values()}
    if inventories["before"].files:
        checked.update(verify_protocol_root(roots["before"] / "protocol", campaign))
    pids: set[int] = set()
    exits: list[dict[str, object]] = []
    clock = bundle.hosted_recipe.started_at
    if window.action == "expire":
        before = HostedProtocolStore(roots["before"] / "protocol").snapshot(campaign, recover=False)
        require(len(before.requests) == 1, "Q05 expiry initial request differs")
        clock = before.requests[0].expires_at
    for phase in FAULT_PROCESS_PHASES:
        record = records[phase]
        pid = record.get("pid")
        require(
            type(pid) is int and pid > parent_pid and pid not in pids,
            "Q05 recovery processes are not distinct",
        )
        pid = cast(int, pid)
        pids.add(pid)
        exits.append({"phase": phase, "pid": pid, "exit_code": 73 if phase == "crash" else 0})
        require(
            record.get("case") == name
            and record.get("phase") == phase
            and record.get("parent_pid") == parent_pid
            and record.get("fresh_application_bootstrap") is True
            and record.get("clock") == clock.isoformat()
            and record.get("python_executable") == observation.get("python_executable")
            and record.get("python_flags") == observation.get("python_flags")
            and record.get("network_attempts") == [],
            "Q05 child source/bootstrap/clock/network facts differ",
        )
        for field in ("execute_calls", "workflow_calls"):
            values = record.get(field)
            require(
                isinstance(values, list)
                and all(
                    isinstance(value, str) and bool(value) for value in cast(list[object], values)
                ),
                "Q05 native call observations are absent",
            )
            if not window.native_execution or phase == "recovery-2":
                require(values == [], "Q05 repeated recovery performed execution")
    require(observation.get("process_exits") == exits, "Q05 physical waitpid accounting differs")
    crash, first, second = (records[phase] for phase in FAULT_PROCESS_PHASES)
    require(
        crash.get("point") == window.point and crash.get("occurrence") == window.occurrence,
        "Q05 fixed physical exit point differs",
    )
    require(
        crash.get("inventory") == inventories["crashed"].model_dump(mode="json")
        and first.get("before_inventory") == crash.get("inventory")
        and first.get("after_inventory") == inventories["recovered"].model_dump(mode="json")
        and second.get("before_inventory")
        == second.get("after_inventory")
        == inventories["after"].model_dump(mode="json"),
        "Q05 child inventories differ from physical phase bytes",
    )
    require(
        first.get("result_hash") == second.get("result_hash")
        and first.get("result_json") == second.get("result_json"),
        "Q05 repeated recovery changed its canonical result",
    )
    result_type = (
        HostedSubmissionReceipt
        if window.action in ("submit", "reject")
        else HostedRequestTerminalReceipt
        if window.action == "cancel"
        else HostedProtocolStatus
        if window.action == "expire"
        else HostedCampaignStatus
    )
    result = result_type.model_validate(first["result_json"])
    require(result.content_hash == first["result_hash"], "Q05 recovered result hash differs")
    # Bind the crash callback to the physical final journal record. No recovering
    # store is constructed on the crashed root, which can have a pending INTENT.
    journals = tuple(
        item
        for item in inventories["crashed"].files
        if item.logical_path.startswith(f"protocol/campaigns/{campaign}/journal/")
    )
    require(bool(journals), "Q05 crash has no durable native journal")
    entry_bytes = read_relative(roots["crashed"], journals[-1].logical_path)
    entry = parse_hosted_contract(entry_bytes, HostedJournalEntry, max_bytes=16_777_216)
    require(
        crash.get("journal_entry") == entry.model_dump(mode="json"), "Q05 crash journal differs"
    )
    if window.operation_kind is not None:
        require(entry.operation_kind == window.operation_kind, "Q05 crash operation differs")
        require(
            entry.phase == ("COMPLETE" if window.point == "completion_published" else "INTENT"),
            "Q05 crash publication phase differs",
        )
        if window.point == "artifact_published":
            object_paths = {
                item.logical_path
                for item in inventories["crashed"].files
                if item.logical_path.startswith(f"protocol/campaigns/{campaign}/objects/")
            }
            for index, publication in enumerate(entry.publications, start=1):
                require(
                    (
                        f"protocol/campaigns/{campaign}/objects/{publication.artifact_hash}.json"
                        in object_paths
                    )
                    is (index <= window.occurrence),
                    "Q05 durable object publication boundary differs",
                )
    checked.add(sha256_bytes(entry_bytes))
    checked.update(verify_protocol_root(roots["recovered"] / "protocol", campaign))
    recovered_state = HostedProtocolStore(roots["recovered"] / "protocol").snapshot(
        campaign, recover=False
    )
    protocol_status = HostedProtocolService.project_status(recovered_state, clock)
    expected_requests = (
        len(bundle.manifest.candidates)
        if window.native_execution and window.point != "started"
        else 2
        if window.action == "resume"
        else 1
    )
    expected_submissions = (
        expected_requests
        if window.native_execution
        else 1
        if window.action in ("submit", "reject", "resume")
        else 0
    )
    expected_operations = {
        "REGISTER": 1,
        "ISSUE": expected_requests,
        "SUBMIT": expected_submissions,
        "TERMINATE": int(window.action in ("cancel", "expire")),
    }
    intents = tuple(entry for entry in recovered_state.journal if entry.phase == "INTENT")
    require(
        all(
            sum(entry.operation_kind == kind for entry in intents) == count
            for kind, count in expected_operations.items()
        )
        and all(
            request.issued_at == bundle.hosted_recipe.started_at
            for request in recovered_state.requests
        )
        and all(
            receipt.recorded_at == bundle.hosted_recipe.started_at
            and receipt.authenticated_principal == "fault.fixture"
            for receipt in recovered_state.receipts
            if receipt.outcome != "EXHAUSTED"
        ),
        "Q05 fixed protocol operation chronology differs",
    )
    if window.action in ("submit", "reject"):
        from quantos.infrastructure.hosted_fixture_frames import duplicate_frame

        frame = duplicate_frame(
            recovered_state.requests[0], "accepted" if window.action == "submit" else "rejected"
        )
        native_results = tuple(
            receipt
            for receipt in recovered_state.receipts
            if receipt.request_hash == recovered_state.requests[0].content_hash
            and receipt.submission_bytes_hash == sha256_bytes(frame)
            and receipt.authenticated_principal == "fault.fixture"
        )
        require(
            len(native_results) == 1 and result == native_results[0],
            "Q05 recovered receipt differs from native authority",
        )
    elif window.action == "cancel":
        expected_terminal = HostedRequestTerminalReceipt(
            request_hash=recovered_state.requests[0].content_hash,
            campaign_hash=campaign,
            outcome="CANCELLED",
            reason="AUTHORIZED_CANCELLATION",
            authenticated_principal="fault.fixture",
            recorded_at=clock,
        )
        require(
            result == expected_terminal
            and expected_terminal
            == recovered_state.terminal(recovered_state.requests[0].content_hash),
            "Q05 recovered cancellation differs from native authority",
        )
    elif window.action == "expire":
        expected_terminal = HostedRequestTerminalReceipt(
            request_hash=recovered_state.requests[0].content_hash,
            campaign_hash=campaign,
            outcome="EXPIRED",
            reason="REQUEST_TTL_ELAPSED",
            authenticated_principal="service",
            recorded_at=clock,
        )
        require(
            result == protocol_status
            and clock == recovered_state.requests[0].expires_at
            and recovered_state.accepted_receipt(recovered_state.requests[0].content_hash) is None
            and expected_terminal
            == recovered_state.terminal(recovered_state.requests[0].content_hash),
            "Q05 recovered expiry differs from native authority",
        )
    else:
        native_status = HostedCampaignApplicationService.project_status(
            recovered_state, protocol_status
        )
        require(
            result == native_status, "Q05 recovered business status differs from native authority"
        )
    runtime_observations: set[str] = set()
    business = None
    if window.native_execution:
        facts = verify_hosted_business_root(
            roots["recovered"],
            bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.paths.offline_inputs,
            provenance_workspace=deployment.paths.provenance,
        )
        business = facts
        _, runtime = principal_business_inventory(roots["recovered"], facts)
        runtime_observations = {item.logical_path for item in runtime.files}
        # Runtime recorder files can appear/disappear; only the verified native
        # execution prefixes receive this exclusion, as in the existing C11 rule.
        prefixes = tuple(
            f"business/{campaign}/execution/executions/{identity}/qlib-workflow/mlflow-runtime/"
            for identity in facts.execution_identities
        )
        runtime_observations.update(
            item.logical_path
            for item in inventories["crashed"].files
            if item.logical_path.startswith(prefixes)
        )
        crash_calls = cast(list[str], crash["execute_calls"])
        recovery_calls = cast(list[str], first["execute_calls"])
        expected_crash = (
            0
            if window.point in ("prepared", "started")
            else len(bundle.manifest.candidates)
            if window.point in ("selection_ledger", "final_report")
            else 1
        )
        require(len(crash_calls) == expected_crash, "Q05 pre-crash execution count differs")
        if window.point == "started":
            state = HostedProtocolStore(roots["recovered"] / "protocol").snapshot(
                campaign, recover=False
            )
            budget = state.artifact(facts.report.research_budget_hash, HostedResearchBudgetFact)
            require(
                recovery_calls == []
                and first.get("workflow_calls") == []
                and facts.report.state == "RECOVERY_REQUIRED"
                and facts.report.reason == "EXECUTION_UNCERTAIN"
                and facts.report.trial_hashes == ()
                and facts.execution_identities == ()
                and budget.phase == "UNCERTAIN"
                and budget.used_trials == budget.used_executions == 1,
                "Q05 durable STARTED was refunded or retried",
            )
        else:
            require(
                len(crash_calls + recovery_calls) == len(bundle.manifest.candidates)
                and len(set(crash_calls + recovery_calls)) == len(crash_calls + recovery_calls)
                and tuple(sorted(crash_calls + recovery_calls)) == facts.execution_identities
                and len(facts.report.trial_hashes) == len(bundle.manifest.candidates)
                and not facts.report.remaining_candidate_hashes,
                "Q05 native receipt reuse/complete family denominator differs",
            )
        checked.update(facts.artifact_hashes)
    elif window.action == "resume":
        before = HostedProtocolStore(roots["before"] / "protocol").snapshot(campaign, recover=False)
        require(len(before.requests) == 1, "Q05 admission input request differs")
        _, _, hashes = verify_native_admission_checkpoint(
            roots["recovered"], before.requests[0], sources, allow_pending_successor=True
        )
        checked.update(hashes)
    else:
        state, orchestrator, events = build_verified_business_orchestrator(
            roots["recovered"],
            bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.paths.offline_inputs,
            provenance_workspace=deployment.paths.provenance,
        )
        native = HostedCampaignApplicationService.verify_research_facts(state)
        require(
            events == bundle.initial_events and not native.steps and not native.reports,
            "Q05 transport recovery produced business trials",
        )
        require(len(native.budgets) == 1, "Q05 initial research budget was duplicated")
        latest, _, _ = verify_native_business_steps(state, orchestrator, events, native.steps)
        verify_native_business_budgets(
            state,
            orchestrator,
            events,
            bundle.initial_events,
            native.budgets,
            native.steps,
            latest,
            None,
        )
        ledger = orchestrator.current_ledger_snapshot(state.spec.started_at, events)
        orchestrator.require_initial_snapshot_prefix(ledger)
        require(
            ledger.node_object_hashes == bundle.initial_ledger_snapshot.node_object_hashes
            and ledger.source_event_hashes == bundle.initial_ledger_snapshot.source_event_hashes,
            "Q05 transport recovery changed Ledger",
        )
    state, orchestrator, events = build_verified_business_orchestrator(
        roots["recovered"],
        bundle,
        deployment_profile_hash=deployment.profile.content_hash,
        input_root=deployment.paths.offline_inputs,
        provenance_workspace=deployment.paths.provenance,
    )
    verify_native_authority_file_closure(
        roots["recovered"], bundle, state, orchestrator, events, business=business
    )
    # Principal artifacts present before exit must remain exact after recovery.
    recovered_files = {item.logical_path: item for item in inventories["recovered"].files}
    crashed_files = {item.logical_path: item for item in inventories["crashed"].files}
    for phase, files in (("before", crashed_files), ("crashed", recovered_files)):
        for item in inventories[phase].files:
            if item.logical_path in runtime_observations:
                continue
            require(
                files.get(item.logical_path) == item, "Q05 recovery overwrote retained evidence"
            )
    for phase, root in roots.items():
        verify_raw_inventory(root, inventories[phase])
    return tuple(sorted(checked))
