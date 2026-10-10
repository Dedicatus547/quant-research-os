"""Read-only native atomic checkpoints and original managed source predicates.

Forensic copies never become canonical authority. Only the published windows
enter the existing native protocol/business readers; temporary windows must be
rejected with their original physical facts intact. This subset grants no Q05.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from quantos.application.hosted_campaign import HostedCampaignApplicationService
from quantos.application.hosted_protocol import HostedProtocolService
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import HostedCampaignSpec, parse_hosted_contract, strict_json_object
from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_atomic_forensics import (
    HostedAtomicForensicInventory,
    atomic_forensic_inventory,
    native_registration_publication,
)
from quantos.infrastructure.hosted_atomic_snapshot import forensic_byte_view
from quantos.infrastructure.hosted_business_file_closure import verify_native_authority_file_closure
from quantos.infrastructure.hosted_business_verification import (
    build_verified_business_orchestrator,
    verify_native_business_budgets,
    verify_native_business_steps,
)
from quantos.infrastructure.hosted_fault_cases import ATOMIC_FAULT_WINDOWS, FAULT_SNAPSHOT_PHASES
from quantos.infrastructure.hosted_negative_origin import require, verify_managed_fixture_source
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_verification import (
    directory_inventory,
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)

_TEMPORARY = re.compile(r"\.publish-[0-9a-f]{32}\Z")
_PROCESS_PHASES = ("crash", "recovery-1", "recovery-2")


def verify_atomic_publication_checkpoint(
    authority: Path,
    facts: HostedAtomicForensicInventory,
    bundle: HostedFrozenBusinessInputs,
    spec: HostedCampaignSpec,
    *,
    domain: str,
    window: str,
) -> tuple[str, ...]:
    """Derive every crash byte/directory from the native registration and seed."""
    target, data = native_registration_publication(spec, domain)
    require(
        facts.target_path == target
        and facts.expected_publication_hash == sha256_bytes(data)
        and facts.window == window,
        "Q05 atomic publication parameters differ",
    )
    inventory = raw_inventory(authority)
    require(inventory == forensic_byte_view(facts), "Q05 atomic copied byte view differs")
    paths = tuple(item.logical_path for item in facts.files)
    dirs = tuple(item.logical_path for item in facts.directories)
    require(
        paths == tuple(sorted(set(paths))) and dirs == tuple(sorted(set(dirs))) and "" in dirs,
        "Q05 atomic physical inventory names differ",
    )
    expected = {
        f"business/{spec.campaign_hash}/ledger/{item.logical_path}": (item.sha256, item.size_bytes)
        for item in bundle.initial_ledger_files
    }
    plan = bundle.selection_plan
    expected[
        f"business/{spec.campaign_hash}/selection-plans/sha256-{plan.content_hash}/plan.json"
    ] = (
        plan.content_hash,
        len(plan.canonical_bytes()),
    )
    for prior in (
        () if domain == "spec" else ("spec",) if domain == "journal" else ("spec", "journal")
    ):
        prior_path, prior_bytes = native_registration_publication(spec, prior)
        expected[prior_path] = (sha256_bytes(prior_bytes), len(prior_bytes))
    temporary = tuple(
        path
        for path in paths
        if Path(path).parent == Path(target).parent and _TEMPORARY.fullmatch(Path(path).name)
    )
    require(
        len(temporary) == (1 if window in ("file_fsynced", "file_linked") else 0),
        "Q05 atomic temporary geometry differs",
    )
    publications = (*temporary, *((target,) if window != "file_fsynced" else ()))
    for path in publications:
        expected[path] = (sha256_bytes(data), len(data))
        require(
            read_relative(authority, path) == data, "Q05 atomic native publication bytes differ"
        )
    require(
        {item.logical_path: (item.sha256, item.size_bytes) for item in inventory.files} == expected,
        "Q05 atomic checkpoint contains unrelated or missing bytes",
    )
    expected_dirs = {"", "protocol", "protocol/specs", "protocol/campaigns"}
    for path in expected:
        expected_dirs.update(str(parent) for parent in Path(path).parents if str(parent) != ".")
    if domain != "spec":
        expected_dirs.update(
            (
                "business-locks",
                f"business-locks/{spec.campaign_hash}",
                f"protocol/campaigns/{spec.campaign_hash}/objects",
                f"protocol/campaigns/{spec.campaign_hash}/journal",
            )
        )
    require(
        set(dirs) == expected_dirs
        and directory_inventory(authority) == tuple(sorted(expected_dirs - {""})),
        "Q05 atomic checkpoint contains unrelated or missing directories",
    )
    physical = {item.logical_path: item for item in facts.files}
    for path, item in physical.items():
        require(
            item.link_count == (2 if window == "file_linked" and path in publications else 1),
            "Q05 atomic checkpoint physical link count differs",
        )
    if window == "file_linked":
        left, right = (physical[path] for path in publications)
        require(
            (left.device, left.inode, left.mode, left.uid, left.gid, left.mtime_ns, left.ctime_ns)
            == (
                right.device,
                right.inode,
                right.mode,
                right.uid,
                right.gid,
                right.mtime_ns,
                right.ctime_ns,
            ),
            "Q05 atomic checkpoint aliases differ",
        )
    return tuple(
        sorted({facts.content_hash, inventory.content_hash, *[v[0] for v in expected.values()]})
    )


def verify_atomic_recovery_scenario(
    name: str,
    roots: dict[str, Path],
    facts: dict[str, HostedAtomicForensicInventory],
    records: dict[str, dict[str, object]],
    observation: dict[str, object],
    *,
    parent_pid: int,
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    """Verify exact native outcomes after callers bind original sources/kernel."""
    require(name in ATOMIC_FAULT_WINDOWS, "unknown atomic fixture")
    require(set(roots) == set(FAULT_SNAPSHOT_PHASES), "Q05 atomic phase roots incomplete")
    require(set(facts) == {"crashed", "recovered", "after"}, "Q05 atomic facts incomplete")
    require(set(records) == set(_PROCESS_PHASES), "Q05 atomic process facts incomplete")
    deployment = sources.deployment
    domain, window = ATOMIC_FAULT_WINDOWS[name]
    spec, bundle = deployment.spec, deployment.bundle
    checked = set(
        verify_atomic_publication_checkpoint(
            roots["crashed"], facts["crashed"], bundle, spec, domain=domain, window=window
        )
    )
    require(
        not raw_inventory(roots["before"]).files and not directory_inventory(roots["before"]),
        "Q05 atomic starting authority was not empty",
    )
    for phase, physical in facts.items():
        require(
            raw_inventory(roots[phase]) == forensic_byte_view(physical)
            and directory_inventory(roots[phase])
            == tuple(item.logical_path for item in physical.directories if item.logical_path),
            "Q05 atomic phase copy differs from original physical byte/directory view",
        )
    rejected = window in ("file_fsynced", "file_linked")
    require(facts["recovered"] == facts["after"], "Q05 second atomic recovery changed originals")
    if rejected:
        require(facts["crashed"] == facts["after"], "Q05 unsafe atomic authority was modified")
        expected_result: dict[str, object] = {
            "outcome": "REJECTED_ATOMIC_INTERMEDIATE",
            "error_type": "ArtifactIntegrityError",
        }
    else:
        state, orchestrator, events = build_verified_business_orchestrator(
            roots["after"],
            bundle,
            deployment_profile_hash=deployment.profile.content_hash,
            input_root=deployment.paths.offline_inputs,
            provenance_workspace=deployment.paths.provenance,
        )
        native = HostedCampaignApplicationService.verify_research_facts(state)
        require(
            events == bundle.initial_events
            and not native.steps
            and not native.reports
            and len(native.budgets) == 1
            and len(state.requests) == 1
            and state.budget.used_requests == 1
            and state.budget.used_unique_submissions == 0,
            "Q05 published atomic recovery produced unrelated business effects",
        )
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
        ledger = orchestrator.current_ledger_snapshot(spec.started_at, events)
        orchestrator.require_initial_snapshot_prefix(ledger)
        require(
            ledger.node_object_hashes == bundle.initial_ledger_snapshot.node_object_hashes
            and ledger.source_event_hashes == bundle.initial_ledger_snapshot.source_event_hashes,
            "Q05 atomic recovery changed seed Ledger",
        )
        verify_native_authority_file_closure(roots["after"], bundle, state, orchestrator, events)
        checked.update(verify_protocol_root(roots["after"] / "protocol", spec.campaign_hash))
        status = HostedCampaignApplicationService.project_status(
            state, HostedProtocolService.project_status(state, spec.started_at)
        )
        require(status.state == "WAITING_FOR_AGENT", "Q05 atomic recovered status differs")
        expected_result = status.model_dump(mode="json")
        after_files = {item.logical_path: item for item in facts["after"].files}
        require(
            all(after_files.get(item.logical_path) == item for item in facts["crashed"].files),
            "Q05 atomic recovery replaced retained physical files",
        )
        after_dirs = {item.logical_path: item for item in facts["after"].directories}
        for item in facts["crashed"].directories:
            final = after_dirs.get(item.logical_path)
            require(
                final is not None
                and all(
                    getattr(final, field) == getattr(item, field)
                    for field in ("device", "inode", "mode", "uid", "gid")
                ),
                "Q05 atomic recovery replaced retained physical directories",
            )
    pids: set[int] = set()
    exits: list[dict[str, object]] = []
    for phase in _PROCESS_PHASES:
        record = records[phase]
        pid = record.get("pid")
        require(
            type(pid) is int and pid > parent_pid and pid not in pids,
            "Q05 atomic child PID differs",
        )
        pids.add(cast(int, pid))
        exits.append(
            {
                "phase": phase,
                "pid": pid,
                "exit_code": 73 if phase == "crash" else 74 if rejected else 0,
            }
        )
        require(
            record.get("schema_version") == "hosted-atomic-fault-process-observation/v1"
            and record.get("case") == name
            and record.get("phase") == phase
            and record.get("parent_pid") == parent_pid
            and record.get("fresh_application_bootstrap") is True
            and record.get("clock") == spec.started_at.isoformat()
            and record.get("python_flags") == observation.get("python_flags")
            and record.get("python_executable") == observation.get("python_executable")
            and record.get("execute_calls")
            == record.get("workflow_calls")
            == record.get("network_attempts")
            == [],
            "Q05 atomic child bootstrap/clock/offline facts differ",
        )
        if phase == "crash":
            require(
                record.get("domain") == domain
                and record.get("window") == window
                and record.get("point") == f"{domain}_{window}"
                and record.get("forensic_inventory") == facts["crashed"].model_dump(mode="json"),
                "Q05 atomic physical exit point/facts differ",
            )
        else:
            initial = facts["crashed" if phase == "recovery-1" else "recovered"]
            final = facts["recovered" if phase == "recovery-1" else "after"]
            require(
                record.get("before_forensic_inventory") == initial.model_dump(mode="json")
                and record.get("after_forensic_inventory") == final.model_dump(mode="json")
                and record.get("result_json") == expected_result
                and record.get("result_hash")
                == sha256_bytes(canonical_json_bytes(expected_result)),
                "Q05 atomic native recovery result or physical accounting differs",
            )
    require(
        observation.get("process_exits") == exits
        and observation.get("domain") == domain
        and observation.get("window") == window
        and observation.get("point") == f"{domain}_{window}"
        and observation.get("authority_after_forensic_inventory")
        == facts["after"].model_dump(mode="json"),
        "Q05 atomic parent observation differs",
    )
    checked.update(item.content_hash for item in facts.values())
    return tuple(sorted(checked))


def verify_q05_atomic_subset(
    bundle_root: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Require all twelve original fixed workers; never independently grant Q05."""
    require(case.case_id == "Q05", "Q05 atomic case identity differs")
    indexed = {root.name: root for root in case.roots}
    require(
        set(indexed)
        == {f"{name}-{phase}" for name in ATOMIC_FAULT_WINDOWS for phase in FAULT_SNAPSHOT_PHASES},
        "Q05 complete atomic matrix absent",
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
    for name, (domain, window) in ATOMIC_FAULT_WINDOWS.items():
        prefix = f"qualification-cases/Q05/{name}"
        target = deployment.root / prefix
        roots: dict[str, Path] = {}
        inventories: dict[str, HostedRawInventory] = {}
        facts: dict[str, HostedAtomicForensicInventory] = {}
        for phase in FAULT_SNAPSHOT_PHASES:
            root = indexed[f"{name}-{phase}"]
            require(
                root.campaign_hash == deployment.spec.campaign_hash, "Q05 atomic campaign differs"
            )
            data = read_relative(bundle_root, root.raw_inventory_path)
            require(
                sources.files[root.raw_inventory_path].source_path
                == f"{prefix}/channel/phase-inventories/{phase}.json",
                "Q05 atomic phase sidecar origin differs",
            )
            inventory = parse_hosted_contract(data, HostedRawInventory, max_bytes=16_777_216)
            original = target / f"channel/snapshots/{phase}/authority"
            require(raw_inventory(original) == inventory, "Q05 original atomic copy changed")
            if inventory.files:
                require(
                    sources.root_origin(root, inventory) == original,
                    "Q05 atomic root combines origins",
                )
            roots[phase] = bundle_root / root.logical_path
            inventories[phase] = inventory
            verify_raw_inventory(roots[phase], inventory)
            require(
                directory_inventory(roots[phase]) == directory_inventory(original),
                "Q05 atomic copied directories differ",
            )
            checked.add(sha256_bytes(data))
            if phase != "before":
                matches = [
                    (path, payload, raw)
                    for path, payload, raw in evidence
                    if sources.files[path].source_path
                    == f"{prefix}/channel/phase-forensics/{phase}.json"
                ]
                require(len(matches) == 1, "Q05 original physical sidecar absent or ambiguous")
                _, _, raw = matches[0]
                facts[phase] = parse_hosted_contract(
                    raw, HostedAtomicForensicInventory, max_bytes=16_777_216
                )
                checked.add(sha256_bytes(raw))
        target_path, expected_bytes = native_registration_publication(deployment.spec, domain)
        actual = atomic_forensic_inventory(
            target / "authority",
            target_path=target_path,
            expected_bytes=expected_bytes,
            window=window,
        )
        require(
            actual == facts["after"],
            "Q05 original physical authority differs from retained sidecar",
        )
        observations = [
            (path, payload, data)
            for path, payload, data in evidence
            if payload.get("schema_version") == "hosted-negative-observation/v1"
            and payload.get("case") == name
        ]
        runs = [
            (path, payload, data)
            for path, payload, data in evidence
            if payload.get("schema_version") == "hosted-manager-negative-run/v1"
            and payload.get("case") == name
        ]
        require(len(observations) == len(runs) == 1, "Q05 atomic original invocation ambiguous")
        observation_path, observation, observation_bytes = observations[0]
        run_path, run, run_bytes = runs[0]
        require(
            run.get("authority_after_forensic_inventory") == actual.model_dump(mode="json"),
            "Q05 manager physical authority differs",
        )
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
        processes: dict[str, dict[str, object]] = {}
        expected_paths = {
            f"{prefix}/channel/process-records/{phase}{suffix}.json"
            for phase in _PROCESS_PHASES
            for suffix in ("", "-exit")
        }
        seen: set[str] = set()
        for path, payload, data in evidence:
            source = sources.files[path].source_path
            if not source.startswith(f"{prefix}/channel/process-records/"):
                continue
            require(
                source in expected_paths and source not in seen, "Q05 atomic extra process record"
            )
            seen.add(source)
            phase = payload.get("phase")
            require(
                isinstance(phase, str) and phase in _PROCESS_PHASES,
                "Q05 atomic process phase differs",
            )
            phase = cast(str, phase)
            if source.endswith("-exit.json"):
                expected_exit = next(
                    (
                        item
                        for item in cast(list[dict[str, object]], observation["process_exits"])
                        if item.get("phase") == phase
                    ),
                    None,
                )
                require(
                    source == f"{prefix}/channel/process-records/{phase}-exit.json"
                    and payload == expected_exit,
                    "Q05 atomic parent waitpid record differs",
                )
            else:
                require(
                    source == f"{prefix}/channel/process-records/{phase}.json"
                    and phase not in processes,
                    "Q05 atomic process origin differs",
                )
                processes[phase] = payload
            checked.add(sha256_bytes(data))
        require(seen == expected_paths, "Q05 atomic process records incomplete")
        security = cast(list[str], kernel["service_process_security"])
        nspid = [line.split(":", 1)[1].split() for line in security if line.startswith("NSpid:")]
        require(
            len(nspid) == 1 and bool(nspid[0]) and all(v.isdecimal() for v in nspid[0]),
            "Q05 atomic kernel parent PID absent",
        )
        checked.update(
            verify_atomic_recovery_scenario(
                name,
                roots,
                facts,
                processes,
                observation,
                parent_pid=int(nspid[0][-1]),
                sources=sources,
            )
        )
    return tuple(sorted(checked))
