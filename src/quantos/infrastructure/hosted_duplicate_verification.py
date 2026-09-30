"""Read-only Q02 accounting over original cross-process management fixtures."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedCampaignStatus,
    HostedResearchBudgetFact,
    HostedSubmissionReceipt,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import (
    HostedQualificationCase,
    HostedQualificationFile,
    HostedRawInventory,
)
from quantos.infrastructure.hosted_admission_verification import verify_business_admission_fixture
from quantos.infrastructure.hosted_fixture_frames import DUPLICATE_SNAPSHOT_PHASES, duplicate_frame
from quantos.infrastructure.hosted_negative_origin import require
from quantos.infrastructure.hosted_negative_verification import (
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)

PROCESS_PHASES = ("submit-1", "submit-2", "repeat", "resume-1", "resume-2", "late-repeat")


def verify_duplicate_fixture(
    bundle: Path,
    case: HostedQualificationCase,
    name: str,
    observation: dict[str, object],
    kernel_child: dict[str, object],
    sources: HostedVerifiedSources,
) -> tuple[str, ...]:
    deployment = sources.deployment
    campaign = deployment.bundle.campaign.content_hash
    target = deployment.root / "qualification-cases/Q02" / name
    roots = {root.name: root for root in case.roots}
    snapshots: dict[str, tuple[Path, HostedRawInventory]] = {}
    checked: set[str] = set()
    for phase in DUPLICATE_SNAPSHOT_PHASES:
        root = roots[f"{name}-{phase}"]
        inventory = HostedRawInventory.model_validate_json(
            read_relative(bundle, root.raw_inventory_path)
        )
        original = target / (
            "authority" if phase == "after" else f"channel/snapshots/{phase}/authority"
        )
        require(
            sources.root_origin(root, inventory) == original,
            "Q02 phase combines unrelated original roots",
        )
        require(raw_inventory(original) == inventory, "Q02 original phase snapshot changed")
        exported = bundle / root.logical_path
        verify_raw_inventory(exported, inventory)
        checked.update(verify_protocol_root(exported / "protocol", campaign))
        checked.add(inventory.content_hash)
        snapshots[phase] = exported, inventory
    before, after_submit = snapshots["before"][0], snapshots["after-submit"][0]
    initial = HostedProtocolStore(before / "protocol").snapshot(campaign, recover=False)
    request = initial.requests[0]
    require(
        initial.spec.hosted_budget.max_submissions_per_request == 2,
        "Q02 frozen fixture cap differs",
    )
    frame = duplicate_frame(request, name)
    receipt_hash = observation.get("receipt_hash")
    require(isinstance(receipt_hash, str), "Q02 primary receipt is absent")
    receipt_hash = cast(str, receipt_hash)
    checked.update(
        verify_negative_submission_transition(
            before,
            after_submit,
            campaign_hash=campaign,
            request_hash=request.content_hash,
            response_bytes=frame,
            receipt_hash=receipt_hash,
            kind="source_unattested" if name == "accepted" else "schema_invalid",
        )
    )
    submitted_state = HostedProtocolStore(after_submit / "protocol").snapshot(
        campaign, recover=False
    )
    receipt = submitted_state.artifact(receipt_hash, HostedSubmissionReceipt)
    processes: dict[str, dict[str, object]] = {}
    for path in case.evidence_paths:
        data = read_relative(bundle, path)
        try:
            payload = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        if payload.get("schema_version") != "hosted-duplicate-process-observation/v1":
            continue
        # Each case has its own original source prefix, independent of producer labels.
        origin = sources.files[path].source_path
        if not origin.startswith(f"qualification-cases/Q02/{name}/channel/process-records/"):
            continue
        phase = payload.get("phase")
        require(
            isinstance(phase, str) and phase in PROCESS_PHASES and phase not in processes,
            "Q02 process phase is unknown or duplicated",
        )
        phase = cast(str, phase)
        require(
            origin == f"qualification-cases/Q02/{name}/channel/process-records/{phase}.json",
            "Q02 process observation source differs",
        )
        processes[phase] = payload
        checked.add(sha256_bytes(data))
    require(
        set(processes) == set(PROCESS_PHASES), "Q02 original process observations are incomplete"
    )
    security = kernel_child.get("service_process_security")
    require(isinstance(security, list), "Q02 actual parent kernel identity is absent")
    nspid = [
        line.split(":", 1)[1].split()
        for line in cast(list[str], security)
        if line.startswith("NSpid:")
    ]
    require(
        len(nspid) == 1 and bool(nspid[0]) and all(value.isdecimal() for value in nspid[0]),
        "Q02 kernel namespace PID is absent",
    )
    parent_pid = int(nspid[0][-1])
    flags = observation.get("python_flags")
    lock_id: object = None
    pids: set[int] = set()
    expected_exits: list[dict[str, object]] = []
    for phase in PROCESS_PHASES:
        process = processes[phase]
        pid = process.get("pid")
        require(
            type(pid) is int and pid > parent_pid and pid not in pids,
            "Q02 child processes are not distinct",
        )
        pid = cast(int, pid)
        pids.add(pid)
        expected_exits.append({"pid": pid, "phase": phase, "exit_code": 0})
        if lock_id is None:
            lock_id = process.get("lock_before")
            require(
                isinstance(lock_id, list)
                and len(cast(list[object], lock_id)) == 2
                and all(type(value) is int and value > 0 for value in cast(list[object], lock_id)),
                "Q02 stable lock inode is absent",
            )
        resume = phase.startswith("resume-")
        require(
            process.get("parent_pid") == parent_pid
            and process.get("lock_before") == process.get("lock_after") == lock_id
            and process.get("action") == ("resume" if resume else "submit")
            and process.get("barrier") is phase.startswith("submit-")
            and process.get("fresh_application_bootstrap") is resume
            and process.get("request_hash") == request.content_hash
            and process.get("response_hash") == sha256_bytes(frame)
            and process.get("python_executable") == "/install/python-seeded"
            and process.get("python_flags") == flags
            and process.get("execute_calls")
            == process.get("workflow_calls")
            == process.get("network_attempts")
            == [],
            "Q02 child source, lock, barrier or side-effect facts differ",
        )
        expected_clock = request.expires_at if phase == "late-repeat" else receipt.recorded_at
        require(isinstance(process.get("clock"), str), "Q02 child clock is absent")
        clock = datetime.fromisoformat(cast(str, process["clock"]))
        require(
            clock > expected_clock if phase == "late-repeat" else clock == expected_clock,
            "Q02 original child clock differs",
        )
        if not resume:
            repeated = HostedSubmissionReceipt.model_validate(process.get("result_json"))
            require(
                repeated == receipt and process.get("result_hash") == repeated.content_hash,
                "Q02 concurrent/repeated receipt differs",
            )
        before_inventory = HostedRawInventory.model_validate(process.get("before_inventory"))
        after_inventory = HostedRawInventory.model_validate(process.get("after_inventory"))
        expected_before = (
            snapshots["before"][1]
            if phase.startswith("submit-")
            else snapshots["after"][1]
            if phase == "late-repeat"
            else snapshots["after-first-resume"][1]
            if phase == "resume-2"
            else snapshots["after-submit"][1]
        )
        expected_after = (
            snapshots["after-first-resume"][1]
            if resume
            else snapshots["after"][1]
            if phase == "late-repeat"
            else snapshots["after-submit"][1]
        )
        require(
            before_inventory == expected_before and after_inventory == expected_after,
            "Q02 child operation raw snapshots differ",
        )
    require(
        observation.get("process_exits") == expected_exits,
        "Q02 actual waitpid/exit accounting differs",
    )
    first_status = HostedCampaignStatus.model_validate(processes["resume-1"].get("result_json"))
    second_status = HostedCampaignStatus.model_validate(processes["resume-2"].get("result_json"))
    first_state = HostedProtocolStore(snapshots["after-first-resume"][0] / "protocol").snapshot(
        campaign, recover=False
    )
    budgets = [
        first_state.artifact(digest, HostedResearchBudgetFact)
        for digest, data in first_state.artifacts.items()
        if strict_json_object(data, max_bytes=16_777_216).get("schema_version")
        == "hosted-research-budget-fact/v1"
    ]
    require(
        first_status == second_status
        and all(
            processes[phase].get("result_hash") == first_status.content_hash
            for phase in ("resume-1", "resume-2")
        )
        and first_status.campaign_hash == campaign
        and first_status.hosted_spec_hash == initial.spec.content_hash
        and first_status.state == "WAITING_FOR_AGENT"
        and first_status.report_hash is None
        and first_status.protocol.budget_hash == first_state.budget.content_hash
        and first_status.protocol.journal_head_hash == first_state.journal_head_hash
        and first_status.protocol.used_unique_submissions == 1
        and first_status.protocol.used_requests == len(first_state.requests)
        and first_status.research_budget_hash in {budget.content_hash for budget in budgets},
        "Q02 repeated resume status/native accounting differs",
    )
    business_root = snapshots["after-business"][0]
    business_state = HostedProtocolStore(business_root / "protocol").snapshot(
        campaign, recover=False
    )
    if name == "accepted":
        checked.update(
            verify_business_admission_fixture(
                before,
                business_root,
                request,
                frame,
                receipt_hash,
                None,
                observation.get("business_cancellation_hash"),
                sources,
            )
        )
        require(
            len(first_state.requests) == 2
            and first_state.terminal(first_state.requests[1].content_hash) is None,
            "Q02 resume issued no unique pending next request",
        )
        cancellation = business_state.terminal(first_state.requests[1].content_hash)
        require(
            cancellation is not None
            and cancellation.outcome == "CANCELLED"
            and cancellation.reason == "AUTHORIZED_CANCELLATION"
            and cancellation.recorded_at == receipt.recorded_at
            and cancellation.authenticated_principal == "duplicate.fixture",
            "Q02 checkpoint cancellation differs",
        )
        assert cancellation is not None
        require(
            business_state.journal[:-2] == first_state.journal
            and business_state.budget == first_state.budget,
            "Q02 cancellation changed native prefix/accounting",
        )
        intent, complete = business_state.journal[-2:]
        require(
            intent.operation_kind == "TERMINATE"
            and tuple(publication.artifact_hash for publication in intent.publications)
            == (cancellation.content_hash,),
            "Q02 checkpoint cancellation publications differ",
        )
        expected_files = {
            item.logical_path: item for item in snapshots["after-first-resume"][1].files
        }
        for logical, data in (
            (
                f"protocol/campaigns/{campaign}/objects/{cancellation.content_hash}.json",
                cancellation.canonical_bytes(),
            ),
            *(
                (
                    f"protocol/campaigns/{campaign}/journal/{entry.sequence:08d}-{entry.content_hash}.json",
                    entry.canonical_bytes(),
                )
                for entry in (intent, complete)
            ),
        ):
            expected_files[logical] = HostedQualificationFile(
                logical_path=logical, sha256=sha256_bytes(data), size_bytes=len(data)
            )
        require(
            expected_files
            == {item.logical_path: item for item in snapshots["after-business"][1].files},
            "Q02 cancellation has an unrelated raw delta",
        )
    else:
        require(
            snapshots["after-submit"][1]
            == snapshots["after-first-resume"][1]
            == snapshots["after-business"][1]
            and observation.get("business_cancellation_hash") is None,
            "Q02 rejected duplicates created deterministic effects",
        )
    require(
        snapshots["before-cap"][1] == snapshots["after-business"][1],
        "Q02 cap starting checkpoint differs",
    )
    cap_hashes = observation.get("cap_receipt_hashes")
    require(
        isinstance(cap_hashes, list)
        and len(cast(list[object], cap_hashes)) == 1
        and isinstance(cap_hashes[0], str),
        "Q02 cap reservation is absent",
    )
    cap_hash = cast(list[str], cap_hashes)[0]
    checked.update(
        verify_negative_submission_transition(
            snapshots["before-cap"][0],
            snapshots["after"][0],
            campaign_hash=campaign,
            request_hash=request.content_hash,
            response_bytes=canonical_json_bytes({"duplicate_cap_fixture": 1}),
            receipt_hash=cap_hash,
            kind="conflict" if name == "accepted" else "schema_invalid",
        )
    )
    final = HostedProtocolStore(snapshots["after"][0] / "protocol").snapshot(
        campaign, recover=False
    )
    exhausted_hash = observation.get("exhaustion_receipt_hash")
    require(isinstance(exhausted_hash, str), "Q02 fixed exhaustion receipt is absent")
    exhaustion = final.artifact(cast(str, exhausted_hash), HostedSubmissionReceipt)
    require(
        exhaustion.outcome == "EXHAUSTED"
        and exhaustion.request_hash == request.content_hash
        and exhaustion.content_hash in submitted_state.artifacts
        and final.budget.request_submissions[0].used_submissions == 2
        and final.budget.used_unique_submissions == 2
        and final.artifact(receipt_hash, HostedSubmissionReceipt) == receipt,
        "Q02 cap/late receipt reuse or accounting differs",
    )
    return tuple(sorted(checked))
