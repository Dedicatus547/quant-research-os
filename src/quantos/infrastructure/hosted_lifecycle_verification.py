"""Read-only Q06 lifecycle subset; budgets must be separately proven for Q06."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.artifacts.store import opened_directory
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedRequestTerminalReceipt,
    HostedSubmissionReceipt,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_business_file_closure import verify_native_authority_file_closure
from quantos.infrastructure.hosted_business_verification import (
    build_verified_business_orchestrator,
    verify_hosted_business_root,
    verify_native_business_budgets,
    verify_native_business_steps,
)
from quantos.infrastructure.hosted_fixture_frames import business_rejection_frame
from quantos.infrastructure.hosted_lifecycle_cases import (
    HOSTED_LIFECYCLE_CASES,
    LIFECYCLE_SNAPSHOT_PHASES,
)
from quantos.infrastructure.hosted_negative_origin import require, verify_managed_fixture_source
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedStoreSnapshot
from quantos.infrastructure.hosted_verification import (
    directory_inventory,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def lifecycle_process_phases(case: str) -> tuple[str, ...]:
    require(case in HOSTED_LIFECYCLE_CASES, "unknown fixed lifecycle case")
    actions = (
        ("winner", "loser")
        if case in HOSTED_LIFECYCLE_CASES[:2]
        else ("seen", "seen-repeat", "late")
        if case == "ttl_seen_response"
        else ("late",)
    )
    return (*actions, "response-repeat", "recovery-1", "recovery-2")


def _verify_fixture_protocol_times(name: str, state: HostedStoreSnapshot) -> None:
    """Cross-bind the fixed worker clock to native publications, not just metadata."""
    first = state.requests[0]
    require(first.issued_at == state.spec.started_at, "lifecycle initial request clock differs")
    for request in state.requests:
        require(
            request.issued_at
            == (state.spec.started_at if request.transport_ordinal == 1 else first.expires_at),
            "lifecycle request publication clock differs",
        )
    for entry in state.journal:
        if entry.phase != "INTENT" or entry.operation_kind == "BUSINESS":
            continue
        expected_time = state.spec.started_at
        if entry.operation_kind == "ISSUE":
            request = next(
                request
                for request in state.requests
                if any(p.artifact_hash == request.content_hash for p in entry.publications)
            )
            expected_time = request.issued_at
        elif entry.operation_kind == "SUBMIT":
            receipt = state.artifact(entry.publications[-1].artifact_hash, HostedSubmissionReceipt)
            expected_time = (
                first.expires_at
                if name.startswith("ttl_") and receipt.submission_bytes_hash != sha256_bytes(b"{}")
                else state.spec.started_at
            )
            require(
                receipt.recorded_at == expected_time
                and receipt.authenticated_principal == "lifecycle.fixture",
                "lifecycle fixed submission clock or principal differs",
            )
            if len(entry.publications) == 3:
                terminal = state.artifact(
                    entry.publications[1].artifact_hash, HostedRequestTerminalReceipt
                )
                require(
                    terminal.recorded_at == first.expires_at
                    and terminal.authenticated_principal == "service",
                    "lifecycle embedded expiration clock or principal differs",
                )
        elif entry.operation_kind == "TERMINATE":
            terminal = state.artifact(
                entry.publications[0].artifact_hash, HostedRequestTerminalReceipt
            )
            expected_time = (
                state.spec.started_at
                if terminal.request_hash == first.content_hash
                and name in HOSTED_LIFECYCLE_CASES[:2]
                else first.expires_at
            )
            require(
                terminal.recorded_at == expected_time
                and terminal.authenticated_principal == "lifecycle.fixture",
                "lifecycle fixed cancellation clock or principal differs",
            )
        require(
            entry.recorded_at == expected_time, "lifecycle fixed protocol journal clock differs"
        )


def verify_lifecycle_scenario(
    name: str,
    roots: dict[str, Path],
    processes: dict[str, dict[str, object]],
    observation: dict[str, object],
    *,
    parent_pid: int,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    """Native accounting and exact fixed actions; callers separately bind origins."""
    phases = lifecycle_process_phases(name)
    require(set(roots) == set(LIFECYCLE_SNAPSHOT_PHASES), "lifecycle snapshots incomplete")
    require(set(processes) == set(phases), "lifecycle process records incomplete")
    deployment = sources.deployment
    checked: set[str] = set()
    states: dict[str, HostedStoreSnapshot] = {}
    for phase, root in roots.items():
        state, orchestrator, events = build_verified_business_orchestrator(
            root,
            deployment.bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.paths.offline_inputs,
            provenance_workspace=deployment.paths.provenance,
        )
        states[phase] = state
        _verify_fixture_protocol_times(name, state)
        research = HostedCampaignApplicationService.verify_research_facts(state)
        latest, validations, executions = verify_native_business_steps(
            state, orchestrator, events, research.steps
        )
        require(not validations and not executions, "lifecycle fixture executed research")
        final = phase in ("after-recovery", "after")
        require(len(research.reports) == int(final), "lifecycle final report phase differs")
        report = research.reports[0] if final else None
        budget = verify_native_business_budgets(
            state,
            orchestrator,
            events,
            deployment.bundle.initial_events,
            research.budgets,
            research.steps,
            latest,
            report,
        )
        business = (
            verify_hosted_business_root(
                root,
                deployment.bundle,
                deployment_profile_hash=deployment.profile.content_hash,
                input_root=deployment.paths.offline_inputs,
                provenance_workspace=deployment.paths.provenance,
            )
            if final
            else None
        )
        checked.update(
            verify_native_authority_file_closure(
                root, deployment.bundle, state, orchestrator, events, business=business
            )
        )
        expected_directories = {"business-locks", f"business-locks/{state.spec.campaign_hash}"}
        for item in raw_inventory(root).files:
            expected_directories.update(
                str(parent) for parent in Path(item.logical_path).parents if str(parent) != "."
            )
        require(
            directory_inventory(root) == tuple(sorted(expected_directories)),
            "lifecycle authority contains unrelated or missing directories",
        )
        expected_trials = int(final and name == "submit_before_cancel")
        require(
            budget.used_trials == expected_trials
            and budget.used_executions == budget.used_compute_units == 0
            and budget.used_validation_rounds == expected_trials,
            "lifecycle research charges differ",
        )
        require(
            state.budget.used_requests == 1 + expected_trials
            and state.budget.used_unique_submissions
            == (0 if phase == "before" else 2 if name == "ttl_seen_response" else 1),
            "lifecycle transport charges reset or differ",
        )
        if report is not None:
            require(
                report.state == ("EXPIRED" if name.startswith("ttl_") else "CANCELLED")
                and report.research_run_status == "FAILED"
                and report.research_verdict == "NOT_EVALUATED"
                and report.selection_report_hash is None
                and len(report.trial_hashes) == expected_trials
                and bool(report.remaining_candidate_hashes)
                and "HOST_INTERNAL_USAGE_UNAVAILABLE" in report.limitations,
                "lifecycle termination report or hidden cost limit differs",
            )
        checked.update(state.artifacts)
    require(
        raw_inventory(roots["after-recovery"]) == raw_inventory(roots["after"])
        and directory_inventory(roots["after-recovery"]) == directory_inventory(roots["after"]),
        "second lifecycle recovery changed authority",
    )
    before, actions = states["before"], states["after-actions"]
    require(
        len(before.requests) == len(actions.requests) == 1, "lifecycle request identity differs"
    )
    request = before.requests[0]
    response = business_rejection_frame(request, "known_schema_invalid")
    receipt = next(
        (r for r in actions.receipts if r.submission_bytes_hash == sha256_bytes(response)), None
    )
    require(receipt is not None, "lifecycle fixed submission receipt absent")
    assert receipt is not None
    require(
        receipt.outcome == ("ACCEPTED" if name == "submit_before_cancel" else "REJECTED")
        and receipt.reason
        == (
            "TRANSPORT_ACCEPTED"
            if name == "submit_before_cancel"
            else "REQUEST_CANCELLED"
            if name == "cancel_before_submit"
            else "REQUEST_EXPIRED"
        ),
        "lifecycle winner outcome differs",
    )
    terminal = next((t for t in actions.terminals if t.request_hash == request.content_hash), None)
    require(
        terminal is not None
        and terminal.outcome
        == (
            "CANCEL_REJECTED"
            if name == "submit_before_cancel"
            else "CANCELLED"
            if name == "cancel_before_submit"
            else "EXPIRED"
        ),
        "lifecycle cancellation/expiration outcome differs",
    )
    expected: dict[str, object] = {"response-repeat": receipt.model_dump(mode="json")}
    if name in HOSTED_LIFECYCLE_CASES[:2]:
        assert terminal is not None
        expected.update(
            {
                "winner": terminal.model_dump(mode="json")
                if name == "cancel_before_submit"
                else receipt.model_dump(mode="json"),
                "loser": receipt.model_dump(mode="json")
                if name == "cancel_before_submit"
                else terminal.model_dump(mode="json"),
            }
        )
        barrier = observation.get("race_barrier")
        require(isinstance(barrier, dict), "lifecycle race barrier absent")
        barrier = cast(dict[str, object], barrier)
        require(
            barrier
            == {
                "winner_pid": processes["winner"].get("pid"),
                "loser_pid": processes["loser"].get("pid"),
                "lock_identity": processes["winner"].get("lock_identity"),
                "winner_native_intent_published": True,
                "loser_entered_native_flock": True,
                "inspector_nonblocking_flock_rejected": True,
                "loser_waitpid_before_release": [0, 0],
            }
            and processes["winner"].get("lock_identity") == processes["loser"].get("lock_identity"),
            "lifecycle actual lock barrier differs",
        )
        operations = tuple(
            entry.operation_kind
            for entry in actions.journal
            if entry.phase == "INTENT" and entry.operation_kind in ("SUBMIT", "TERMINATE")
        )
        require(
            operations
            == (
                ("TERMINATE", "SUBMIT")
                if name == "cancel_before_submit"
                else ("SUBMIT", "TERMINATE")
            ),
            "lifecycle durable lock order differs",
        )
    else:
        require(observation.get("race_barrier") is None, "TTL fixture claimed race evidence")
        expected["late"] = receipt.model_dump(mode="json")
        if name == "ttl_seen_response":
            seen = next(
                (r for r in actions.receipts if r.submission_bytes_hash == sha256_bytes(b"{}")),
                None,
            )
            require(
                seen is not None and seen.reason == "SCHEMA_INVALID",
                "TTL original seen receipt differs",
            )
            assert seen is not None
            expected.update(
                {"seen": seen.model_dump(mode="json"), "seen-repeat": seen.model_dump(mode="json")}
            )
    require(
        observation.get("request_hash") == request.content_hash
        and observation.get("response_hash") == sha256_bytes(response),
        "lifecycle response/request identity differs",
    )
    flags = observation.get("python_flags")
    pids: set[int] = set()
    exits: list[dict[str, object]] = []
    for phase in phases:
        record = processes[phase]
        pid = record.get("pid")
        require(
            type(pid) is int and pid > parent_pid and pid not in pids,
            "lifecycle child PID differs",
        )
        pids.add(cast(int, pid))
        result = record.get("result_json")
        if phase.startswith("recovery-"):
            result_state = states["after-recovery" if phase == "recovery-1" else "after"]
            from quantos.application.hosted_protocol import HostedProtocolService

            result_expected = HostedCampaignApplicationService.project_status(
                result_state, HostedProtocolService.project_status(result_state, request.expires_at)
            ).model_dump(mode="json")
        else:
            result_expected = expected[phase]
        require(
            record.get("phase") == phase
            and record.get("parent_pid") == parent_pid
            and record.get("fresh_application_bootstrap")
            is (phase not in ("winner", "loser", "seen"))
            and record.get("clock")
            == (
                request.issued_at if phase in ("winner", "loser", "seen") else request.expires_at
            ).isoformat()
            and result == result_expected
            and record.get("result_hash") == sha256_bytes(canonical_json_bytes(result_expected))
            and record.get("python_executable") == observation.get("python_executable")
            and record.get("python_flags") == flags
            and record.get("execute_calls")
            == record.get("workflow_calls")
            == record.get("network_attempts")
            == [],
            "lifecycle process action or native restart result differs",
        )
        exits.append({"phase": phase, "pid": pid, "exit_code": 0})
    require(observation.get("process_exits") == exits, "lifecycle actual parent exits differ")
    return tuple(sorted(checked))


def verify_q06_lifecycle_subset(
    bundle_root: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """All four original installed workers are mandatory; this never grants Q06."""
    require(case.case_id == "Q06", "lifecycle case identity differs")
    indexed = {root.name: root for root in case.roots}
    require(
        set(indexed)
        == {
            f"{name}-{phase}"
            for name in HOSTED_LIFECYCLE_CASES
            for phase in LIFECYCLE_SNAPSHOT_PHASES
        },
        "complete lifecycle matrix absent",
    )
    evidence: list[tuple[str, dict[str, object], bytes]] = []
    for path in case.evidence_paths:
        data = read_relative(bundle_root, path)
        evidence.append((path, strict_json_object(data, max_bytes=16_777_216), data))
    checked: set[str] = set()
    for name in HOSTED_LIFECYCLE_CASES:
        prefix = f"qualification-cases/Q06/{name}"
        roots: dict[str, Path] = {}
        inventories: dict[str, HostedRawInventory] = {}
        for phase in LIFECYCLE_SNAPSHOT_PHASES:
            root = indexed[f"{name}-{phase}"]
            inventory = HostedRawInventory.model_validate_json(
                read_relative(bundle_root, root.raw_inventory_path)
            )
            original = sources.deployment.root / f"{prefix}/channel/snapshots/{phase}/authority"
            require(
                root.campaign_hash == sources.deployment.spec.campaign_hash
                and sources.files[root.raw_inventory_path].source_path
                == f"{prefix}/channel/phase-inventories/{phase}.json"
                and sources.root_origin(root, inventory) == original,
                "lifecycle root/sidecar origin differs",
            )
            verify_raw_inventory(original, inventory)
            roots[phase] = bundle_root / root.logical_path
            verify_raw_inventory(roots[phase], inventory)
            require(
                directory_inventory(roots[phase]) == directory_inventory(original),
                "lifecycle copied directories differ",
            )
            inventories[phase] = inventory
        observations = [
            (path, fact, data)
            for path, fact, data in evidence
            if fact.get("schema_version") == "hosted-negative-observation/v1"
            and fact.get("case") == name
        ]
        runs = [
            (path, fact, data)
            for path, fact, data in evidence
            if fact.get("schema_version") == "hosted-manager-negative-run/v1"
            and fact.get("case") == name
        ]
        require(len(observations) == len(runs) == 1, "lifecycle original invocation ambiguous")
        opath, observation, obytes = observations[0]
        rpath, run, rbytes = runs[0]
        kernel, hashes = verify_managed_fixture_source(
            evidence,
            sources,
            family="Q06",
            name=name,
            observation_path=opath,
            observation=observation,
            observation_bytes=obytes,
            run_path=rpath,
            run=run,
            run_bytes=rbytes,
            before_inventory=inventories["before"],
            after_inventory=inventories["after"],
        )
        checked.update(hashes)
        original_authority = sources.deployment.root / prefix / "authority"
        verify_raw_inventory(original_authority, inventories["after"])
        require(
            directory_inventory(original_authority) == directory_inventory(roots["after"]),
            "lifecycle original authority directories differ",
        )
        phases = lifecycle_process_phases(name)
        expected_paths = {
            f"{prefix}/channel/process-records/{phase}{suffix}.json"
            for phase in phases
            for suffix in ("", "-exit")
        }
        seen: set[str] = set()
        processes: dict[str, dict[str, object]] = {}
        for path, payload, data in evidence:
            source = sources.files[path].source_path
            if not source.startswith(f"{prefix}/channel/process-records/"):
                continue
            require(
                source in expected_paths and source not in seen, "lifecycle extra process evidence"
            )
            seen.add(source)
            phase = payload.get("phase")
            require(isinstance(phase, str) and phase in phases, "lifecycle process phase differs")
            phase = cast(str, phase)
            suffix = "-exit" if source.endswith("-exit.json") else ""
            require(
                source == f"{prefix}/channel/process-records/{phase}{suffix}.json",
                "lifecycle process phase origin differs",
            )
            if source.endswith("-exit.json"):
                exits = cast(list[dict[str, object]], observation.get("process_exits"))
                require(
                    payload == next((exit for exit in exits if exit.get("phase") == phase), None),
                    "lifecycle parent waitpid record differs",
                )
            else:
                require(phase not in processes, "lifecycle duplicate process record")
                processes[phase] = payload
            checked.add(sha256_bytes(data))
        require(seen == expected_paths, "lifecycle process records incomplete")
        with opened_directory(
            original_authority / "protocol/campaigns" / sources.deployment.spec.campaign_hash
        ) as fd:
            import os

            inode = os.fstat(fd)
            require(
                all(
                    record.get("lock_identity") == [inode.st_dev, inode.st_ino]
                    for record in processes.values()
                ),
                "lifecycle recorded lock differs from original retained inode",
            )
        security = cast(list[str], kernel["service_process_security"])
        nspid = [line.split(":", 1)[1].split() for line in security if line.startswith("NSpid:")]
        require(
            len(nspid) == 1 and bool(nspid[0]) and all(v.isdecimal() for v in nspid[0]),
            "lifecycle kernel parent PID absent",
        )
        if name in HOSTED_LIFECYCLE_CASES[:2]:
            barriers = [
                (path, fact, raw)
                for path, fact, raw in evidence
                if sources.files[path].source_path == f"{prefix}/channel/race-barrier.json"
            ]
            require(
                len(barriers) == 1 and barriers[0][1] == observation.get("race_barrier"),
                "lifecycle original race barrier differs",
            )
            checked.add(sha256_bytes(barriers[0][2]))
        checked.update(
            verify_lifecycle_scenario(
                name, roots, processes, observation, parent_pid=int(nspid[0][-1]), sources=sources
            )
        )
    return tuple(sorted(checked))
