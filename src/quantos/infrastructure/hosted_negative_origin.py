"""Read-only Q03 predicates over original fixed management negative invocations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import (
    HostedResearchBudgetFact,
    HostedSubmissionReceipt,
    strict_json_object,
)
from quantos.contracts.hosted_qualification import HostedQualificationCase, HostedRawInventory
from quantos.infrastructure.hosted_deployment import namespace_command
from quantos.infrastructure.hosted_fixture_frames import (
    BOUNDED_REJECTION_CASES,
    BUSINESS_REJECTION_CASES,
    HOST_OBSERVATION_CASES,
    HOST_OBSERVATION_SCHEMA_REJECTIONS,
    bounded_rejection_frame,
    business_rejection_frame,
    host_observation_frame,
)
from quantos.infrastructure.hosted_negative_verification import (
    NegativeSubmissionKind,
    verify_negative_submission_transition,
)
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
    verify_protocol_root,
    verify_raw_inventory,
)

CASES = (
    "campaign_hash",
    "transport_ordinal",
    "context_pack_hash",
    "request_hash",
    "attempt_identity",
    "expired",
    "cancelled",
    "conflict",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def verify_q03(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    return _verify_transport_matrix(bundle, case, sources, family="Q03", names=CASES)


def verify_q08(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Unattested fields and fake sources never establish qualification authority."""
    return _verify_transport_matrix(
        bundle, case, sources, family="Q08", names=HOST_OBSERVATION_CASES
    )


def verify_q04_transport_matrix(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Only the bounded transport subset; it never grants the full Q04 gate."""
    return _verify_transport_matrix(
        bundle,
        _subset_case(case, BOUNDED_REJECTION_CASES),
        sources,
        family="Q04",
        names=BOUNDED_REJECTION_CASES,
    )


def verify_q04_business_matrix(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """The known-invalid trial subset still does not independently grant full Q04."""
    return _verify_transport_matrix(
        bundle,
        _subset_case(case, BUSINESS_REJECTION_CASES),
        sources,
        family="Q04",
        names=BUSINESS_REJECTION_CASES,
    )


def verify_q04(
    bundle: Path, case: HostedQualificationCase, sources: HostedVerifiedSources
) -> tuple[str, ...]:
    """Require transport/known-invalid accounting and actual restricted-host path probes."""
    names = (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES)
    require(
        case.case_id == "Q04"
        and {root.name for root in case.roots}
        == {f"{name}-{phase}" for name in names for phase in ("before", "after")},
        "Q04 complete admission matrix is absent",
    )
    from quantos.infrastructure.hosted_security_verification import verify_deployment_security

    checked = set(verify_deployment_security(sources.deployment))
    evidence_hashes = {sha256_bytes(read_relative(bundle, path)) for path in case.evidence_paths}
    require(checked <= evidence_hashes, "Q04 actual path/isolation source export is incomplete")
    checked.update(verify_q04_transport_matrix(bundle, case, sources))
    checked.update(verify_q04_business_matrix(bundle, case, sources))
    return tuple(sorted(checked))


def _subset_case(case: HostedQualificationCase, names: tuple[str, ...]) -> HostedQualificationCase:
    expected = {f"{name}-{phase}" for name in names for phase in ("before", "after")}
    return case.model_copy(
        update={"roots": tuple(root for root in case.roots if root.name in expected)}
    )


def _verify_transport_matrix(
    bundle: Path,
    case: HostedQualificationCase,
    sources: HostedVerifiedSources,
    *,
    family: str,
    names: tuple[str, ...],
) -> tuple[str, ...]:
    require(case.case_id == family, "Q03 case identity differs")
    roots = {root.name: root for root in case.roots}
    require(
        set(roots) == {f"{name}-{phase}" for name in names for phase in ("before", "after")},
        "Q03 complete independent matrix is absent",
    )
    records: list[tuple[str, dict[str, object], bytes]] = []
    for path in case.evidence_paths:
        data = read_relative(bundle, path)
        try:
            payload = strict_json_object(data, max_bytes=16_777_216)
        except ValueError:
            continue
        records.append((path, payload, data))
    checked: set[str] = set()
    deployment = sources.deployment
    for name in names:
        target = deployment.root / "qualification-cases" / family / name
        snapshots: list[tuple[Path, HostedRawInventory]] = []
        for phase in ("before", "after"):
            root = roots[f"{name}-{phase}"]
            require(
                root.campaign_hash == deployment.bundle.campaign.content_hash,
                "Q03 root campaign differs",
            )
            inventory = HostedRawInventory.model_validate_json(
                read_relative(bundle, root.raw_inventory_path)
            )
            original = target / ("channel/before/authority" if phase == "before" else "authority")
            require(
                sources.root_origin(root, inventory) == original,
                "Q03 snapshots combine unrelated original roots",
            )
            require(raw_inventory(original) == inventory, "Q03 original snapshot changed")
            exported_root = bundle / root.logical_path
            verify_raw_inventory(exported_root, inventory)
            checked.update(verify_protocol_root(exported_root / "protocol", root.campaign_hash))
            snapshots.append((bundle / root.logical_path, inventory))
        observations = [
            (path, fact, data)
            for path, fact, data in records
            if fact.get("schema_version") == "hosted-negative-observation/v1"
            and fact.get("case") == name
        ]
        runs = [
            (path, fact, data)
            for path, fact, data in records
            if fact.get("schema_version") == "hosted-manager-negative-run/v1"
            and fact.get("case") == name
        ]
        require(
            len(observations) == len(runs) == 1,
            "Q03 original invocation or observation is missing or ambiguous",
        )
        observation_path, observation, observation_bytes = observations[0]
        run_path, run, run_bytes = runs[0]
        require(
            sources.files[observation_path].source_path
            == f"qualification-cases/{family}/{name}/channel/negative-observation.json",
            "Q03 observation origin differs",
        )
        require(
            sources.files[run_path].source_path
            == f"evidence/negative-run-{sha256_bytes(run_bytes)}.json",
            "Q03 completion is not original management evidence",
        )
        require(
            type(run.get("return_code")) is int
            and run["return_code"] == 0
            and run.get("observation_failure_type") is None
            and run.get("observation_hash") == sha256_bytes(observation_bytes),
            "Q03 invocation did not complete with safe original observation",
        )
        for fact in (run, observation):
            require(
                fact.get("deployment_profile_hash") == deployment.profile.content_hash
                and fact.get("campaign_hash") == deployment.bundle.campaign.content_hash,
                "Q03 deployment/campaign bindings differ",
            )
        require(
            run.get("authority_root") == str(target / "authority"),
            "Q03 worker did not use its fresh authority",
        )
        require(
            HostedRawInventory.model_validate(run["authority_after_inventory"]) == snapshots[1][1],
            "Q03 completion raw authority differs",
        )
        require(
            HostedRawInventory.model_validate(run["channel_inventory"])
            == raw_inventory(target / "channel"),
            "Q03 original channel inventory differs",
        )
        require(
            HostedRawInventory.model_validate(observation["before_inventory"]) == snapshots[0][1]
            and HostedRawInventory.model_validate(observation["after_inventory"])
            == snapshots[1][1],
            "Q03 observation snapshots differ",
        )
        prelaunch_hash = run.get("prelaunch_hash")
        prelaunches = [
            (path, fact, data)
            for path, fact, data in records
            if fact.get("schema_version") == "hosted-manager-negative-prelaunch/v1"
            and sha256_bytes(data) == prelaunch_hash
        ]
        require(len(prelaunches) == 1, "Q03 durable prelaunch is missing or ambiguous")
        prelaunch_path, prelaunch, prelaunch_bytes = prelaunches[0]
        require(
            sources.files[prelaunch_path].source_path
            == f"evidence/negative-prelaunch-{sha256_bytes(prelaunch_bytes)}.json",
            "Q03 prelaunch origin differs",
        )
        require(
            not HostedRawInventory.model_validate(prelaunch["authority_before_inventory"]).files,
            "Q03 worker authority was not fresh",
        )
        for field in ("case", "deployment_profile_hash", "authority_root", "argv", "program_hash"):
            require(
                prelaunch.get(field) == run.get(field), "Q03 prelaunch/completion binding differs"
            )
        program = next(
            item.bytes_hash
            for item in deployment.install.files
            if item.relative_path
            == "python/lib/python3.11/site-packages/quantos/infrastructure/"
            + {
                "Q03": "hosted_negative_probe.py",
                "Q04": "hosted_admission_probe.py",
                "Q08": "hosted_observation_probe.py",
            }[family]
        )
        native = next(
            item.bytes_hash
            for item in deployment.install.files
            if item.relative_path == "python-seeded"
        )
        require(run.get("program_hash") == program, "Q03 worker differs from frozen installation")
        argv = run.get("argv")
        require(
            isinstance(argv, list)
            and all(isinstance(arg, str) for arg in cast(list[object], argv)),
            "Q03 actual namespace argv is absent",
        )
        arguments = cast(list[str], argv)
        require(
            arguments.count("--file") == arguments.count("--info-fd") == 1,
            "Q03 private descriptors differ",
        )
        capability_fd = int(arguments[arguments.index("--file") + 1])
        info_fd = int(arguments[arguments.index("--info-fd") + 1])
        require(
            capability_fd >= 3 and info_fd >= 3 and capability_fd != info_fd,
            "Q03 private descriptors are invalid",
        )
        command = (
            "/install/python-seeded",
            "-m",
            "quantos.infrastructure."
            + {
                "Q03": "hosted_negative_probe",
                "Q04": "hosted_admission_probe",
                "Q08": "hosted_observation_probe",
            }[family],
            "--profile-hash",
            deployment.profile.content_hash,
            "--case",
            name,
        )
        paths = replace(
            deployment.paths, authority=target / "authority", channel=target / "channel"
        )
        require(
            tuple(arguments)
            == namespace_command(
                "service", paths, command, service_capability_fds=(capability_fd,), info_fd=info_fd
            ),
            "Q03 fixed namespace argv differs",
        )
        child = run.get("manager_child_observation")
        require(isinstance(child, dict), "Q03 actual kernel child binding is absent")
        child_fact = cast(dict[str, object], child)
        require(
            child_fact.get("service_command") == list(command)
            and child_fact.get("service_executable_hash") == native,
            "Q03 running executable/command differs",
        )
        require(
            all(
                type(child_fact.get(field)) is int and cast(int, child_fact[field]) > 1
                for field in ("wrapper_pid", "init_pid", "service_pid")
            )
            and len({child_fact.get(field) for field in ("wrapper_pid", "init_pid", "service_pid")})
            == 3,
            "Q03 actual process chain is absent",
        )
        namespaces, manager_namespaces = (
            child_fact.get("service_namespace_identities"),
            run.get("manager_namespace_identities"),
        )
        require(
            isinstance(namespaces, dict) and isinstance(manager_namespaces, dict),
            "Q03 actual namespace identities are absent",
        )
        child_namespaces = cast(dict[str, object], namespaces)
        parent_namespaces = cast(dict[str, object], manager_namespaces)
        information = child_fact.get("container_information")
        require(isinstance(information, dict), "Q03 container information is absent")
        container = cast(dict[str, object], information)
        require(
            type(container.get("child-pid")) is int
            and container.get("child-pid") == child_fact["init_pid"]
            and all(
                type(container.get(field + "-namespace")) is int
                and child_namespaces.get(field) == f"{field}:[{container[field + '-namespace']}]"
                for field in ("net", "pid", "mnt")
            ),
            "Q03 container information differs from actual kernel namespaces",
        )
        require(
            all(
                isinstance(child_namespaces.get(field), str)
                and isinstance(parent_namespaces.get(field), str)
                and child_namespaces.get(field) != parent_namespaces.get(field)
                for field in ("net", "pid", "mnt", "user")
            ),
            "Q03 worker inherited a management namespace",
        )
        security = child_fact.get("service_process_security")
        require(
            isinstance(security, list)
            and all(isinstance(line, str) for line in cast(list[object], security)),
            "Q03 kernel credentials are absent",
        )
        credentials = {
            line.split(":", 1)[0]: line.split(":", 1)[1].strip()
            for line in cast(list[str], security)
            if ":" in line
        }
        principal = deployment.configuration.principals[0]
        require(
            credentials.get("CapEff") == "0000000000000000"
            and credentials.get("Uid", "").split() == [str(principal.uid)] * 4
            and credentials.get("Gid", "").split() == [str(principal.gid)] * 4,
            "Q03 actual worker principal differs",
        )
        require(
            observation.get("fixture_kind") == "TRANSPORT_NEGATIVE_FIXTURE"
            and observation.get("execute_calls")
            == observation.get("workflow_calls")
            == observation.get("network_attempts")
            == [],
            "Q03 fixture executed a deterministic or network call",
        )
        flags = observation.get("python_flags")
        require(isinstance(flags, dict), "Q03 native interpreter flags are absent")
        flag_values = cast(dict[str, object], flags)
        expected_flags = {
            "isolated": 1,
            "ignore_environment": 1,
            "no_user_site": 1,
            "safe_path": True,
            "hash_randomization": 0,
        }
        require(
            observation.get("python_executable") == "/install/python-seeded"
            and set(flag_values) == set(expected_flags)
            and all(
                type(flag_values.get(name)) is type(value) and flag_values.get(name) == value
                for name, value in expected_flags.items()
            ),
            "Q03 native interpreter flags differ",
        )
        state = HostedProtocolStore(snapshots[0][0] / "protocol").snapshot(
            deployment.bundle.campaign.content_hash, recover=False
        )
        require(
            state.spec == deployment.spec and len(state.requests) == 1,
            "Q03 frozen request/spec differ",
        )
        request = state.requests[0]
        require(request.issued_at == state.spec.started_at, "Q03 fixed test clock differs")
        research = [
            HostedResearchBudgetFact.model_validate_json(data)
            for data in state.artifacts.values()
            if strict_json_object(data, max_bytes=16_777_216).get("schema_version")
            == "hosted-research-budget-fact/v1"
        ]
        require(
            len(research) == 1
            and research[0].phase == "INITIAL"
            and research[0].used_trials
            == research[0].used_executions
            == research[0].used_compute_units
            == 0,
            "Q03 fixture has deterministic business charges",
        )
        require(
            observation.get("request_hash") == state.requests[0].content_hash
            and observation.get("repeat_receipt_hash") == observation.get("receipt_hash"),
            "Q03 original repeat identity differs",
        )
        if family == "Q03":
            require(isinstance(observation.get("response_json"), str), "Q03 original bytes absent")
            submitted = cast(str, observation["response_json"]).encode()
            kind = cast(NegativeSubmissionKind, name)
        else:
            require(
                observation.get("response_json") is None
                and observation.get("case_family") == family
                and run.get("case_family") == prelaunch.get("case_family") == family,
                "Q04 raw negative bytes were exported or fixture family differs",
            )
            submitted = (
                host_observation_frame(request, name)
                if family == "Q08"
                else (
                    business_rejection_frame(request, name)
                    if name in BUSINESS_REJECTION_CASES
                    else bounded_rejection_frame(request, name)
                )
            )
            require(
                observation.get("response_observed_hash") == sha256_bytes(submitted)
                and type(observation.get("response_observed_bytes")) is int
                and observation.get("response_observed_bytes") == len(submitted),
                "Q04 original bounded frame differs from its fixed recipe",
            )
            kind = cast(
                NegativeSubmissionKind,
                {
                    "frame_byte_cap": "oversized",
                    "unknown_candidate": "unknown_candidate",
                    "credential_like": "credential_like",
                }.get(name, "schema_invalid"),
            )
        require(isinstance(observation.get("receipt_hash"), str), "fixture receipt is absent")
        after_state = HostedProtocolStore(snapshots[1][0] / "protocol").snapshot(
            request.campaign_hash, recover=False
        )
        receipt = after_state.artifact(
            cast(str, observation["receipt_hash"]), HostedSubmissionReceipt
        )
        require(
            isinstance(observation.get("primary_clock"), str)
            and datetime.fromisoformat(cast(str, observation["primary_clock"]))
            == receipt.recorded_at
            and isinstance(observation.get("repeat_clock"), str)
            and datetime.fromisoformat(cast(str, observation["repeat_clock"])) > request.expires_at,
            "Q03 late repeat clock or original timestamp differs",
        )
        if name in ("expired", "cancelled", "conflict"):
            seen_hash = observation.get("seen_receipt_hash")
            require(isinstance(seen_hash, str), "Q03 seen response identity is absent")
            seen = state.artifact(cast(str, seen_hash), HostedSubmissionReceipt)
            require(
                seen.outcome == ("ACCEPTED" if name == "conflict" else "REJECTED")
                and (
                    seen == state.accepted_receipt(request.content_hash)
                    if name == "conflict"
                    else seen.submission_bytes_hash == sha256_bytes(b"{}")
                ),
                "Q03 original seen bytes differ",
            )
        else:
            require(
                observation.get("seen_receipt_hash") is None
                and observation.get("cancellation_receipt_hash") is None,
                "Q03 wrong-binding fixture contains unrelated seen/cancel facts",
            )
        if name in ("cancelled", "conflict"):
            cancellation = next(
                (
                    terminal
                    for terminal in state.terminals
                    if terminal.content_hash == observation.get("cancellation_receipt_hash")
                ),
                None,
            )
            require(
                cancellation is not None
                and cancellation.outcome
                == ("CANCEL_REJECTED" if name == "conflict" else "CANCELLED"),
                "Q03 original cancellation differs",
            )
        if family == "Q08":
            kind = (
                "schema_invalid"
                if name in HOST_OBSERVATION_SCHEMA_REJECTIONS
                else "source_unattested"
            )
        if name in BUSINESS_REJECTION_CASES:
            from quantos.infrastructure.hosted_admission_verification import (
                verify_business_admission_fixture,
            )

            checked.update(
                verify_business_admission_fixture(
                    snapshots[0][0],
                    snapshots[1][0],
                    request,
                    submitted,
                    cast(str, observation["receipt_hash"]),
                    observation.get("business_report_hash"),
                    observation.get("business_cancellation_hash"),
                    sources,
                )
            )
        else:
            checked.update(
                verify_negative_submission_transition(
                    snapshots[0][0],
                    snapshots[1][0],
                    campaign_hash=deployment.bundle.campaign.content_hash,
                    request_hash=state.requests[0].content_hash,
                    response_bytes=submitted,
                    receipt_hash=cast(str, observation["receipt_hash"]),
                    kind=kind,
                )
            )
        if family == "Q08":
            from quantos.infrastructure.hosted_observation_verification import (
                verify_untrusted_observation_source,
            )

            checked.update(
                verify_untrusted_observation_source(
                    request, submitted, name, observation.get("source_conflict_rejected"), sources
                )
            )
        checked.update(
            (
                sha256_bytes(observation_bytes),
                sha256_bytes(run_bytes),
                sha256_bytes(prelaunch_bytes),
                program,
                native,
            )
        )
    return tuple(sorted(checked))
