"""Native read-only accounting for finite Q06 budget fixtures.

The scenario predicate does not establish installation or original-source identity.
Those gates and the complete lifecycle matrix remain mandatory for formal Q06.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import cast

from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedSubmissionReceipt, strict_json_object
from quantos.contracts.hosted_qualification import (
    HostedQualificationCase,
    HostedRawInventory,
)
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_business_file_closure import verify_native_authority_file_closure
from quantos.infrastructure.hosted_business_verification import (
    build_verified_business_orchestrator,
    verify_hosted_business_root,
    verify_native_business_budgets,
    verify_native_business_steps,
)
from quantos.infrastructure.hosted_fixture_frames import (
    business_rejection_frame,
    deterministic_candidate_frame,
)
from quantos.infrastructure.hosted_negative_origin import require, verify_managed_fixture_source
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedStoreSnapshot
from quantos.infrastructure.hosted_verification import (
    digest_relative,
    directory_inventory,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)

BUDGET_SNAPSHOT_PHASES = ("before", "after-exercise", "after-recovery", "after")
BUDGET_PROCESS_PHASES = ("exercise", "recovery-1", "recovery-2")


def verify_budget_scenario(
    name: str,
    roots: dict[str, Path],
    processes: dict[str, dict[str, object]],
    observation: dict[str, object],
    *,
    parent_pid: int,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    """Recompute native reports, reservations, actions and immutable restarts."""
    require(name in HOSTED_BUDGET_CASES, "unknown finite budget scenario")
    recipe = HOSTED_BUDGET_CASES[name]
    deployment = sources.deployment
    require(
        deployment.bundle.research_budget.budget_id == f"hm-q06-{name}-budget-v1",
        "budget scenario requires its independently frozen variant",
    )
    require(set(roots) == set(BUDGET_SNAPSHOT_PHASES), "budget snapshots incomplete")
    require(set(processes) == set(BUDGET_PROCESS_PHASES), "budget process records incomplete")
    states: dict[str, HostedStoreSnapshot] = {}
    checked: set[str] = set()
    executed: tuple[str, ...] = ()
    for phase, root in roots.items():
        final = phase != "before"
        state, orchestrator, events = build_verified_business_orchestrator(
            root,
            deployment.bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.paths.offline_inputs,
            provenance_workspace=deployment.paths.provenance,
        )
        states[phase] = state
        research = HostedCampaignApplicationService.verify_research_facts(state)
        latest, validations, executions = verify_native_business_steps(
            state, orchestrator, events, research.steps
        )
        require(len(research.reports) == int(final), "budget report phase differs")
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
        trials = int(final and name not in ("request_submissions", "compute_allowance"))
        require(
            budget.used_trials == trials
            and budget.used_validation_rounds == trials
            and budget.used_executions == int(final and recipe.native_execution)
            and (
                budget.used_compute_units > 0
                if final and recipe.native_execution
                else budget.used_compute_units == 0
            ),
            "budget native research charges differ",
        )
        require(
            state.budget.used_requests == (2 if final and name == "campaign_submissions" else 1)
            and state.budget.used_unique_submissions
            == (0 if not final else 2 if recipe.action in ("global_cap", "reject_frames") else 1),
            "budget native transport charges reset or differ",
        )
        require(
            len(executions) == int(final and recipe.native_execution)
            and len(validations) == int(final and recipe.native_execution),
            "budget execution or validation denominator differs",
        )
        business = None
        if final:
            business = verify_hosted_business_root(
                root,
                deployment.bundle,
                deployment_profile_hash=deployment.profile.content_hash,
                input_root=deployment.paths.offline_inputs,
                provenance_workspace=deployment.paths.provenance,
            )
            assert report is not None
            require(
                report.state == "EXHAUSTED"
                and report.reason == recipe.expected_reason
                and report.research_run_status == "FAILED"
                and report.research_verdict == "NOT_EVALUATED"
                and report.selection_report_hash is None
                and len(report.trial_hashes) == trials
                and "HOST_INTERNAL_USAGE_UNAVAILABLE" in report.limitations,
                "budget exhaustion report differs",
            )
            executed = tuple(sorted(executions))
        verified_paths = verify_native_authority_file_closure(
            root,
            deployment.bundle,
            state,
            orchestrator,
            events,
            business=business,
        )
        checked.update(digest_relative(root, path)[0] for path in verified_paths)
        directories = {"business-locks", f"business-locks/{state.spec.campaign_hash}"}
        if executions:
            execution_root = f"business/{state.spec.campaign_hash}/execution"
            directories.add(f"{execution_root}/execution-locks")
            for identity in executions:
                directories.add(f"{execution_root}/execution-locks/{identity}")
                directories.add(
                    f"{execution_root}/executions/{identity}/qlib-workflow/mlflow-runtime/.trash"
                )
        for item in raw_inventory(root).files:
            directories.update(str(p) for p in Path(item.logical_path).parents if str(p) != ".")
        require(
            directory_inventory(root) == tuple(sorted(directories)),
            "budget authority directory closure differs",
        )
        require(
            all(r.issued_at == state.spec.started_at for r in state.requests),
            "budget request clock differs",
        )
        require(
            all(
                e.recorded_at == state.spec.started_at
                for e in state.journal
                if e.phase == "INTENT" and e.operation_kind != "BUSINESS"
            ),
            "budget native protocol clock differs",
        )
        checked.update(state.artifacts)
    for phase in ("after-recovery", "after"):
        require(
            raw_inventory(roots[phase]) == raw_inventory(roots["after-exercise"])
            and directory_inventory(roots[phase]) == directory_inventory(roots["after-exercise"]),
            "budget restart changed authority",
        )
    state = states["after-exercise"]
    request = states["before"].requests[0]
    frames = (
        (b"{}", b"[]")
        if recipe.action == "reject_frames"
        else (
            deterministic_candidate_frame(request)
            if recipe.action == "native_candidate"
            else business_rejection_frame(request, "known_schema_invalid"),
        )
    )
    request_hashes = [request.content_hash] * len(frames)
    if recipe.action == "global_cap":
        frames = (*frames, b"{}")
        request_hashes.append(state.requests[1].content_hash)
    receipts: list[HostedSubmissionReceipt] = []
    for request_hash, frame in zip(request_hashes, frames, strict=True):
        matches = [
            r
            for r in state.receipts
            if r.request_hash == request_hash and r.submission_bytes_hash == sha256_bytes(frame)
        ]
        require(len(matches) == 1, "budget fixed response receipt absent or ambiguous")
        receipt = matches[0]
        require(
            receipt.authenticated_principal == "budget.fixture"
            and receipt.recorded_at == state.spec.started_at,
            "budget receipt principal or clock differs",
        )
        receipts.append(receipt)
    exhausted = [r for r in state.receipts if r.outcome == "EXHAUSTED"]
    cap = recipe.action in ("reject_frames", "global_cap")
    require(
        len(exhausted) == 1 + len(state.requests),
        "budget prepublished bounded exhaustion receipts differ",
    )
    cap_receipt = next(
        r
        for r in exhausted
        if r.request_hash == (None if recipe.action == "global_cap" else request.content_hash)
    )
    expected_status = HostedCampaignApplicationService.project_status(
        state,
        HostedProtocolService.project_status(state, state.spec.started_at),
    ).model_dump(mode="json")
    exits: list[dict[str, object]] = []
    pids: set[int] = set()
    for phase in BUDGET_PROCESS_PHASES:
        record = processes[phase]
        pid = record.get("pid")
        require(
            type(pid) is int and pid > parent_pid and pid not in pids,
            "budget native child PID differs",
        )
        pids.add(cast(int, pid))
        exercise = phase == "exercise"
        expected = {
            "status": expected_status,
            "receipts": [r.model_dump(mode="json") for r in receipts] if exercise else [],
            "over_cap_hashes": [cap_receipt.content_hash] * 32 if exercise and cap else [],
            "repeat_receipt_hash": receipts[0].content_hash if exercise and cap else None,
        }
        require(
            record.get("schema_version") == "hosted-budget-process-observation/v1"
            and record.get("phase") == phase
            and record.get("parent_pid") == parent_pid
            and record.get("fresh_application_bootstrap") is True
            and record.get("clock") == state.spec.started_at.isoformat()
            and record.get("result_json") == expected
            and record.get("result_hash") == sha256_bytes(canonical_json_bytes(expected))
            and record.get("python_flags") == observation.get("python_flags")
            and record.get("python_executable") == observation.get("python_executable")
            and record.get("execute_calls") == (list(executed) if exercise else [])
            and record.get("network_attempts") == [],
            "budget fresh process evidence or result differs",
        )
        workflows = record.get("workflow_calls")
        require(isinstance(workflows, list), "budget Workflow observations absent")
        workflows = cast(list[object], workflows)
        require(
            (
                bool(workflows) and all(w == "QLIB_WORKFLOW" for w in workflows)
                if exercise and recipe.native_execution
                else workflows == []
            ),
            "budget native Workflow observations differ",
        )
        exits.append({"phase": phase, "pid": pid, "exit_code": 0})
    require(observation.get("process_exits") == exits, "budget actual parent exits differ")
    return tuple(sorted(checked))


def verify_q06_budget_subset(
    bundle_root: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Require all seven original nested deployments; this alone never awards Q06."""
    from quantos.infrastructure.hosted_budget_deployment import (
        budget_deployment_declaration,
        read_managed_budget_deployment,
    )

    require(case.case_id == "Q06", "budget qualification case differs")
    indexed = {r.name: r for r in case.roots}
    require(
        set(indexed)
        == {f"{name}-{phase}" for name in HOSTED_BUDGET_CASES for phase in BUDGET_SNAPSHOT_PHASES},
        "complete finite budget matrix absent",
    )
    evidence = [
        (
            p,
            strict_json_object(read_relative(bundle_root, p), max_bytes=16_777_216),
            read_relative(bundle_root, p),
        )
        for p in case.evidence_paths
    ]
    checked: set[str] = set()
    for name in HOSTED_BUDGET_CASES:
        declarations = [
            (p, fact, raw)
            for p, fact, raw in evidence
            if sources.files[p].source_path == f"evidence/budget-deployment-{name}.json"
        ]
        require(len(declarations) == 1, "budget parent declaration absent or ambiguous")
        _, declaration, encoded = declarations[0]
        child_hash = declaration.get("child_profile_hash")
        require(isinstance(child_hash, str), "budget child profile hash absent")
        child = read_managed_budget_deployment(sources.deployment, name, cast(str, child_hash))
        require(
            encoded
            == canonical_json_bytes(budget_deployment_declaration(sources.deployment, child, name)),
            "budget parent declaration bytes differ",
        )
        checked.add(sha256_bytes(encoded))
        child_prefix = f"qualification-deployments/Q06/{name}/"
        records = {
            p: record.model_copy(
                update={
                    "source_path": record.source_path.removeprefix(child_prefix),
                }
            )
            for p, record in sources.files.items()
            if record.source_path.startswith(child_prefix)
        }
        nested = HostedVerifiedSources(child, MappingProxyType(records), sources.export_hash)
        child_evidence = [(p, fact, raw) for p, fact, raw in evidence if p in records]
        prefix = f"qualification-cases/Q06/{name}"
        roots: dict[str, Path] = {}
        inventories: dict[str, HostedRawInventory] = {}
        for phase in BUDGET_SNAPSHOT_PHASES:
            root = indexed[f"{name}-{phase}"]
            inventory = HostedRawInventory.model_validate_json(
                read_relative(bundle_root, root.raw_inventory_path)
            )
            original = child.root / prefix / f"channel/snapshots/{phase}/authority"
            require(
                root.campaign_hash == child.spec.campaign_hash
                and nested.files[root.raw_inventory_path].source_path
                == f"{prefix}/channel/phase-inventories/{phase}.json"
                and nested.root_origin(root, inventory) == original,
                "budget snapshot or sidecar origin differs",
            )
            verify_raw_inventory(original, inventory)
            copied = bundle_root / root.logical_path
            verify_raw_inventory(copied, inventory)
            require(
                directory_inventory(copied) == directory_inventory(original),
                "budget copied directories differ",
            )
            roots[phase], inventories[phase] = copied, inventory
        observations = [
            (p, fact, raw)
            for p, fact, raw in child_evidence
            if fact.get("schema_version") == "hosted-negative-observation/v1"
            and fact.get("case") == name
        ]
        runs = [
            (p, fact, raw)
            for p, fact, raw in child_evidence
            if fact.get("schema_version") == "hosted-manager-negative-run/v1"
            and fact.get("case") == name
        ]
        require(len(observations) == len(runs) == 1, "budget invocation ambiguous")
        opath, observation, obytes = observations[0]
        rpath, run, rbytes = runs[0]
        kernel, hashes = verify_managed_fixture_source(
            child_evidence,
            nested,
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
        original_authority = child.root / prefix / "authority"
        verify_raw_inventory(original_authority, inventories["after"])
        require(
            directory_inventory(original_authority) == directory_inventory(roots["after"]),
            "budget original authority directories differ",
        )
        expected_paths = {
            f"{prefix}/channel/process-records/{phase}{suffix}.json"
            for phase in BUDGET_PROCESS_PHASES
            for suffix in ("", "-exit")
        }
        seen: set[str] = set()
        processes: dict[str, dict[str, object]] = {}
        for path, payload, data in child_evidence:
            source = nested.files[path].source_path
            if not source.startswith(f"{prefix}/channel/process-records/"):
                continue
            require(
                source in expected_paths and source not in seen, "budget extra process evidence"
            )
            seen.add(source)
            phase = payload.get("phase")
            require(
                isinstance(phase, str) and phase in BUDGET_PROCESS_PHASES,
                "budget process phase differs",
            )
            phase = cast(str, phase)
            suffix = "-exit" if source.endswith("-exit.json") else ""
            require(
                source == f"{prefix}/channel/process-records/{phase}{suffix}.json",
                "budget process phase origin differs",
            )
            if suffix:
                exits = cast(list[dict[str, object]], observation.get("process_exits"))
                require(
                    payload == next((e for e in exits if e.get("phase") == phase), None),
                    "budget original waitpid differs",
                )
            else:
                require(phase not in processes, "budget duplicate process evidence")
                processes[phase] = payload
            checked.add(sha256_bytes(data))
        require(seen == expected_paths, "budget process evidence incomplete")
        security = cast(list[str], kernel["service_process_security"])
        nspid = [line.split(":", 1)[1].split() for line in security if line.startswith("NSpid:")]
        require(
            len(nspid) == 1 and bool(nspid[0]) and all(v.isdecimal() for v in nspid[0]),
            "budget kernel parent PID absent",
        )
        checked.update(
            verify_budget_scenario(
                name,
                roots,
                processes,
                observation,
                parent_pid=int(nspid[0][-1]),
                sources=nested,
            )
        )
    return tuple(sorted(checked))
