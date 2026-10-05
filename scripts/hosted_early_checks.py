#!/usr/bin/env python3
# ruff: noqa: E402
"""Read-only development checks; never publish hosted qualification authority.

Run with the repository Python environment and explicit C/B/D pins. ``deployment``
checks the installed input trees and projections before a campaign; ``capacity``
measures a retained source index and optionally estimates additional authority
copies; ``gate`` diagnoses one captured case without rechecking unrelated files.
The full frozen verifier and independent review remain required for qualification.
No command starts a service, acquires inputs, authenticates or calls a model.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

# Set this before loading any project module, including when the caller omits -B.
sys.dont_write_bytecode = True

from quantos.application.hosted_inputs import _verify_bundle
from quantos.artifacts.store import atomic_write_bytes_at, opened_directory
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import parse_hosted_contract, strict_json_object
from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration
from quantos.contracts.hosted_qualification import (
    HOSTED_QUALIFICATION_CASES,
    HostedManagerExport,
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationManifest,
    HostedRawInventory,
)
from quantos.infrastructure.hosted_budget_cases import HOSTED_BUDGET_CASES
from quantos.infrastructure.hosted_deployment import install_inventory, read_projection
from quantos.infrastructure.hosted_fault_cases import ATOMIC_FAULT_WINDOWS, MANAGEMENT_FAULT_WINDOWS
from quantos.infrastructure.hosted_fixture_frames import (
    BOUNDED_REJECTION_CASES,
    BUSINESS_REJECTION_CASES,
    DUPLICATE_SUBMISSION_CASES,
    HOST_OBSERVATION_CASES,
)
from quantos.infrastructure.hosted_lifecycle_cases import HOSTED_LIFECYCLE_CASES
from quantos.infrastructure.hosted_manager import HostedManagedDeployment, read_managed_deployment
from quantos.infrastructure.hosted_negative_probe import NEGATIVE_CASES
from quantos.infrastructure.hosted_qualification_sources import (
    HostedVerifiedSources,
    read_manager_export,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    MAX_MANAGER_EXPORT_BYTES,
    MAX_TYPED_BYTES,
    HostedQualificationError,
    digest_relative,
    directory_inventory,
    read_relative,
    verify_case,
)

T = TypeVar("T")


class DiagnosticCheckError(HostedQualificationError):
    """Tool-owned codes are safe to export; upstream exception text is not."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def timed(timings: dict[str, float], name: str, action: Callable[[], T]) -> T:
    started = time.monotonic()
    try:
        return action()
    finally:
        timings[name] = time.monotonic() - started


def readonly_git_action(action: Callable[[], T]) -> T:
    """Native provenance uses git status; disable its optional index refresh write."""
    previous = os.environ.get("GIT_OPTIONAL_LOCKS")
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return action()
    finally:
        if previous is None:
            os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        else:
            os.environ["GIT_OPTIONAL_LOCKS"] = previous


def tree_change_fingerprint(root: Path) -> tuple[str, int]:
    """Cheap no-follow mutation guard; metadata is never qualification authority."""
    records = []

    def walk(descriptor: int, prefix: str) -> None:
        with os.scandir(descriptor) as entries:
            names = sorted(entry.name for entry in entries)
        for name in names:
            require(len(records) < 1_000_000, "DIAGNOSTIC_CHANGE_GUARD_ENTRY_CAP")
            logical = f"{prefix}/{name}" if prefix else name
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            require(
                stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                "DIAGNOSTIC_CHANGE_GUARD_UNSAFE_OBJECT",
            )
            records.append(
                (
                    logical,
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    info.st_nlink,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
            )
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                try:
                    require(
                        (os.fstat(child).st_dev, os.fstat(child).st_ino)
                        == (info.st_dev, info.st_ino),
                        "DIAGNOSTIC_DIRECTORY_REPLACED",
                    )
                    walk(child, logical)
                finally:
                    os.close(child)

    with opened_directory(root) as descriptor:
        info = os.fstat(descriptor)
        records.append(
            (
                ".",
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )
        )
        walk(descriptor, "")
    return sha256_bytes(canonical_json_bytes(records)), len(records)


def check_guarded_action(
    roots: tuple[Path, ...],
    action: Callable[[], T],
    facts: dict[str, object],
    timings: dict[str, float],
) -> T:
    def capture() -> dict[str, tuple[str, int]]:
        return {str(root): tree_change_fingerprint(root) for root in roots}

    before = timed(timings, "original_tree_change_guard_before", capture)
    facts["scope"] = "NO_FOLLOW_METADATA_CHANGE_GUARD_NOT_QUALIFICATION_AUTHORITY"
    facts["before"] = before
    try:
        return readonly_git_action(action)
    finally:
        after = timed(timings, "original_tree_change_guard_after", capture)
        facts["after"] = after
        facts["changed_roots"] = [root for root in before if before[root] != after[root]]
        require(before == after, "ORIGINAL_TREE_CHANGED_DURING_DIAGNOSTIC")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DiagnosticCheckError(code)


def case_denominators() -> dict[str, object]:
    """Retain the frozen complete matrix even when only one family is evaluated."""
    families = {
        "Q02": tuple(DUPLICATE_SUBMISSION_CASES),
        "Q03": tuple(NEGATIVE_CASES),
        "Q04": (*BOUNDED_REJECTION_CASES, *BUSINESS_REJECTION_CASES),
        "Q05": (*MANAGEMENT_FAULT_WINDOWS, *ATOMIC_FAULT_WINDOWS),
        "Q06": (*HOSTED_LIFECYCLE_CASES, *HOSTED_BUDGET_CASES),
        "Q08": tuple(HOST_OBSERVATION_CASES),
    }
    return {
        "case_ids": HOSTED_QUALIFICATION_CASES,
        "case_count": len(HOSTED_QUALIFICATION_CASES),
        "captured_scenario_count": sum(len(names) for names in families.values()),
        "captured_scenarios": families,
    }


def pin_deployment(args: argparse.Namespace) -> HostedManagedDeployment:
    require(args.manager_root.is_absolute(), "ABSOLUTE_MANAGER_ROOT_REQUIRED")
    require(re.fullmatch(r"[0-9a-f]{40}", args.commit) is not None, "EXPLICIT_COMMIT_REQUIRED")
    for digest in (args.profile_hash, args.business_inputs_hash):
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "EXPLICIT_HASH_REQUIRED")
    deployment = read_managed_deployment(args.manager_root, args.profile_hash)
    require(
        deployment.profile.exact_commit == args.commit
        and deployment.bundle.content_hash == args.business_inputs_hash,
        "C_B_D_PIN_MISMATCH",
    )
    return deployment


def inspect_deployment(
    deployment: HostedManagedDeployment, timings: dict[str, float]
) -> dict[str, object]:
    """Reuse native immutable input checks without initializing any business runtime."""
    bundle, paths = deployment.bundle, deployment.paths
    require(
        timed(
            timings, "provenance_hashes", lambda: install_inventory(paths.provenance)
        ).content_hash
        == deployment.profile.provenance_inventory_hash,
        "PROVENANCE_CHANGED",
    )
    actual_install = timed(timings, "installation_hashes", lambda: install_inventory(paths.install))
    require(actual_install == deployment.install, "INSTALLATION_CHANGED")
    trees = (bundle.snapshot_directory, bundle.qlib_view_directory, bundle.initial_ledger_directory)
    require(
        len(set(trees)) == 3
        and all(
            not Path(left).is_relative_to(right)
            for left in trees
            for right in trees
            if left != right
        ),
        "THREE_DISJOINT_INPUT_TREES_REQUIRED",
    )
    # The no-follow inventory detects unsafe directory objects before native readers run.
    directories = directory_inventory(paths.offline_inputs)
    require(all(tree in directories for tree in trees), "INPUT_TREE_LAYOUT_INCOMPLETE")
    configuration = HostedBusinessLoaderConfiguration(
        business_inputs_hash=bundle.content_hash,
        input_root=str(paths.offline_inputs),
        business_root=str(paths.authority),
        provenance_workspace=str(paths.provenance),
    )
    timed(
        timings,
        "native_input_verification",
        lambda: readonly_git_action(lambda: _verify_bundle(configuration, bundle)),
    )
    require(
        timed(
            timings, "provenance_after_native_inputs", lambda: install_inventory(paths.provenance)
        ).content_hash
        == deployment.profile.provenance_inventory_hash,
        "PROVENANCE_CHANGED_DURING_NATIVE_INPUT_CHECK",
    )
    require(
        install_inventory(paths.projection) == deployment.initial_projection,
        "INITIAL_PROJECTION_CHANGED",
    )
    initial_paths = {item.relative_path for item in deployment.initial_projection.files}
    require(initial_paths == {bundle.manifest.content_hash}, "INITIAL_PROJECTION_ALLOWLIST_DIFFERS")
    require(
        read_projection(paths.projection, bundle.manifest.content_hash, max_bytes=MAX_TYPED_BYTES)
        == bundle.manifest.canonical_bytes(),
        "INITIAL_PROJECTION_BYTES_CHANGED",
    )
    state = HostedProtocolStore(paths.authority / "protocol").snapshot(
        bundle.campaign.content_hash, recover=False
    )
    projection_hashes = []
    for request in state.requests:
        projection = deployment.root / "request-projections" / request.content_hash
        inventory = install_inventory(projection)
        require(
            {item.relative_path for item in inventory.files}
            == {request.content_hash, request.context_pack_hash, request.proposal_schema_hash}
            and set(request.projection_object_hashes)
            == {request.context_pack_hash, request.proposal_schema_hash},
            "REQUEST_PROJECTION_ALLOWLIST_DIFFERS",
        )
        require(
            read_projection(projection, request.content_hash, max_bytes=request.max_request_bytes)
            == request.canonical_bytes(),
            "REQUEST_PROJECTION_BYTES_CHANGED",
        )
        for digest in request.projection_object_hashes:
            read_projection(projection, digest, max_bytes=request.max_request_bytes)
        projection_hashes.append(inventory.content_hash)
    return {
        "input_trees": trees,
        "input_directory_count": len(directories),
        "installation_hash": deployment.install.content_hash,
        "installation_file_count": len(deployment.install.files),
        "installation_hashed_bytes": sum(item.size_bytes for item in deployment.install.files),
        "initial_projection_hash": deployment.initial_projection.content_hash,
        "request_projection_count": len(projection_hashes),
        "request_projection_hashes": projection_hashes,
        "permission_scope": "LAYOUT_AND_RETAINED_BYTES_ONLY_NO_NEW_OS_PROBE",
    }


def read_captured_manifest(bundle: Path) -> HostedQualificationManifest:
    return parse_hosted_contract(
        read_relative(bundle, "qualification-manifest.json"),
        HostedQualificationManifest,
        max_bytes=MAX_TYPED_BYTES,
    )


def selected_closure(bundle: Path, case: HostedQualificationCase) -> set[str]:
    paths = set(case.evidence_paths)
    for root in case.roots:
        paths.add(root.raw_inventory_path)
        inventory = parse_hosted_contract(
            read_relative(bundle, root.raw_inventory_path),
            HostedRawInventory,
            max_bytes=MAX_TYPED_BYTES,
        )
        paths.update(f"{root.logical_path}/{item.logical_path}" for item in inventory.files)
    return paths


def bind_selected_sources(
    bundle: Path,
    manifest: HostedQualificationManifest,
    exported: HostedManagerExport,
    deployment: HostedManagedDeployment,
    selected: set[str],
) -> HostedVerifiedSources:
    """Only the declared case closure; this is not full verify_manager_export.

    Unselected records remain unavailable to a scenario predicate. A predicate
    needing extra source records fails closed rather than gaining an unverified map.
    """
    encoded = exported.canonical_bytes()
    require(
        exported.content_hash == manifest.manager_export_hash
        and exported.deployment_profile_hash == deployment.profile.content_hash
        and exported.exact_commit == deployment.profile.exact_commit
        and manifest.exact_commit == deployment.profile.exact_commit
        and manifest.lockfile_hash == deployment.profile.lock_hash,
        "CAPTURED_INDEX_PINS_DIFFER",
    )
    require(
        read_relative(
            deployment.root, f"evidence/{exported.content_hash}", max_bytes=MAX_MANAGER_EXPORT_BYTES
        )
        == encoded,
        "INDEX_NOT_RETAINED_BY_ORIGINAL_MANAGER",
    )
    expected = {
        item.logical_path: item
        for item in manifest.files
        if item.logical_path not in {"manager-export.json", "verifier-result.json"}
    }
    records = {item.bundle_path: item for item in exported.files}
    require(set(records) == set(expected), "FULL_INDEX_DENOMINATOR_DIFFERS")
    require(selected <= set(records), "SELECTED_SOURCE_CLOSURE_INCOMPLETE")
    for logical in sorted(selected):
        item, record = expected[logical], records[logical]
        require(
            (record.sha256, record.size_bytes) == (item.sha256, item.size_bytes)
            and digest_relative(deployment.root, record.source_path)
            == (item.sha256, item.size_bytes)
            and digest_relative(bundle, logical) == (item.sha256, item.size_bytes),
            "SELECTED_ORIGINAL_BYTES_DIFFER",
        )
    return HostedVerifiedSources(
        deployment,
        MappingProxyType({path: records[path] for path in selected}),
        exported.content_hash,
    )


def diagnose_gate(
    bundle: Path,
    case_id: str,
    deployment: HostedManagedDeployment,
    timings: dict[str, float],
    *,
    max_source_files: int,
    max_source_bytes: int,
) -> dict[str, object]:
    require(bundle.is_absolute(), "ABSOLUTE_CAPTURED_BUNDLE_REQUIRED")
    a, b = bundle.resolve(), deployment.root.resolve()
    require(not a.is_relative_to(b) and not b.is_relative_to(a), "INDEPENDENT_BUNDLE_REQUIRED")
    manifest = timed(timings, "captured_manifest", lambda: read_captured_manifest(bundle))
    exported = timed(
        timings, "typed_source_index", lambda: read_manager_export(bundle, "manager-export.json")
    )
    case = next(case for case in manifest.case_records if case.case_id == case_id)
    selected = timed(
        timings, "selected_closure_inventories", lambda: selected_closure(bundle, case)
    )
    expected = {item.logical_path: item for item in manifest.files}
    selected_bytes = sum(expected[path].size_bytes for path in selected)
    require(
        0 < max_source_files <= 100_000 and 0 < max_source_bytes <= 128 * 1024**3,
        "BOUNDED_SOURCE_LIMITS_REQUIRED",
    )
    require(
        len(selected) <= max_source_files and selected_bytes <= max_source_bytes,
        "SELECTED_CLOSURE_EXCEEDS_REQUESTED_DIAGNOSTIC_LIMIT",
    )
    sources = timed(
        timings,
        "selected_original_and_bundle_hashes",
        lambda: bind_selected_sources(bundle, manifest, exported, deployment, selected),
    )
    # Reuse the existing complete family predicate; never supply or edit its verdict.
    gate = timed(
        timings, "native_case_predicate", lambda: verify_case(bundle, case, sources=sources)
    )
    return {
        "captured_manifest_hash": manifest.qualification_hash,
        "retained_manager_export_hash": exported.content_hash,
        "source_binding_scope": "SELECTED_CASE_FILE_CLOSURE_ONLY",
        "formal_source_verification": "NOT_PERFORMED",
        "full_index_file_count": len(exported.files),
        "checked_source_file_count": len(selected),
        "checked_source_bytes": selected_bytes,
        "source_and_bundle_hashed_bytes": selected_bytes * 2,
        "predicate_additional_io_bytes": "UNAVAILABLE",
        "source_file_limit": max_source_files,
        "source_byte_limit": max_source_bytes,
        "unchecked_source_file_count": len(exported.files) - len(selected),
        "captured_root_counts": {item.case_id: len(item.roots) for item in manifest.case_records},
        "selected_case": case_id,
        "predicate_observation": gate.model_dump(mode="json"),
        "unevaluated_case_ids": tuple(x for x in HOSTED_QUALIFICATION_CASES if x != case_id),
        "formal_frozen_verification": "NOT_PERFORMED",
    }


def index_capacity(
    exported: HostedManagerExport,
    reference: HostedRawInventory | None = None,
    additional_authorities: int = 0,
) -> dict[str, object]:
    encoded = exported.canonical_bytes()
    result: dict[str, object] = {
        "measurement_scope": "RETAINED_TYPED_INDEX_ONLY_NO_SOURCE_BYTE_VERIFICATION",
        "manager_export_hash": exported.content_hash,
        "actual_record_count": len(exported.files),
        "actual_encoded_bytes": len(encoded),
        "manager_export_cap_bytes": MAX_MANAGER_EXPORT_BYTES,
        "manager_export_headroom_bytes": MAX_MANAGER_EXPORT_BYTES - len(encoded),
        "ordinary_typed_cap_bytes": MAX_TYPED_BYTES,
        "ordinary_typed_headroom_bytes": MAX_TYPED_BYTES - len(encoded),
    }
    require(0 <= additional_authorities <= 1000, "BOUNDED_AUTHORITY_ESTIMATE_REQUIRED")
    if reference is not None:
        # Count the exact canonical per-record encoding. Prefixes are assumptions,
        # not file mappings or a synthetic qualification export.
        extra_bytes = 0
        for ordinal in range(additional_authorities):
            for item in reference.files:
                record = HostedManagerExportFile(
                    bundle_path=f"projected-authorities/{ordinal:04d}/authority/{item.logical_path}",
                    source_path=f"projected-originals/{ordinal:04d}/authority/{item.logical_path}",
                    sha256=item.sha256,
                    size_bytes=item.size_bytes,
                )
                extra_bytes += len(record.canonical_bytes()) + 1
        result["layout_estimate"] = {
            "scope": "SYNTHETIC_SIZE_ESTIMATE_ONLY_NOT_EVIDENCE",
            "reference_inventory_hash": reference.content_hash,
            "reference_file_count": len(reference.files),
            "additional_authority_count": additional_authorities,
            "additional_record_count": len(reference.files) * additional_authorities,
            "projected_total_record_count": len(exported.files)
            + len(reference.files) * additional_authorities,
            "projected_encoded_bytes": len(encoded) + extra_bytes,
            "projected_headroom_bytes": MAX_MANAGER_EXPORT_BYTES - len(encoded) - extra_bytes,
            "ordinary_typed_projected_headroom_bytes": MAX_TYPED_BYTES - len(encoded) - extra_bytes,
            "prefix_assumption": "projected-authorities/0000/authority AND "
            "projected-originals/0000/authority",
            "final_export_upper_bound": False,
            "layout_count_requirement": "COMPLETE_PLANNED_LOGICAL_AUTHORITY_COPIES_INCLUDING_REUSE_"
            "REPLAY_AND_TAMPER_LOCATIONS",
            "original_source_validation": "NOT_PERFORMED",
        }
    else:
        require(additional_authorities == 0, "REFERENCE_INVENTORY_REQUIRED_FOR_ESTIMATE")
    return result


def inspect_original_case(
    deployment: HostedManagedDeployment,
    case_id: str,
    scenario: str,
    timings: dict[str, float],
) -> dict[str, object]:
    """Bounded retained worker diagnostics, including incomplete failed captures.

    This command never reads a crash authority through a canonical reader and
    never manufactures missing observation, phase or original-source records.
    Budget children require their independent pins and are deliberately excluded.
    """
    families = case_denominators()["captured_scenarios"]
    require(case_id in families and scenario in families[case_id], "UNKNOWN_FROZEN_SCENARIO")
    require(
        case_id != "Q06" or scenario in HOSTED_LIFECYCLE_CASES,
        "BUDGET_CHILD_REQUIRES_INDEPENDENT_DEPLOYMENT_PINS",
    )
    prefix = f"qualification-cases/{case_id}/{scenario}/channel"
    channel = deployment.root / prefix
    candidates = []
    with opened_directory(channel) as descriptor:
        names = os.listdir(descriptor)
        require(len(names) <= 1000, "ORIGINAL_CASE_DIRECTORY_LIMIT")
        for name in ("negative-observation.json", "phase-inventories", "process-records"):
            if name not in names:
                continue
            if name == "negative-observation.json":
                candidates.append(prefix + "/" + name)
                continue
            with opened_directory(channel / name) as child:
                records = os.listdir(child)
                require(len(records) <= 1000, "ORIGINAL_CASE_RECORD_LIMIT")
                for record in sorted(records):
                    require(record.endswith(".json"), "ORIGINAL_CASE_NON_JSON_RECORD")
                    candidates.append(f"{prefix}/{name}/{record}")
    with opened_directory(deployment.root) as descriptor:
        if "negative-staging-failure.json" in os.listdir(descriptor):
            candidates.append("negative-staging-failure.json")
    facts = []
    total = 0
    failed = False
    expected_exits: dict[str, int] = {}
    expected_paths: set[str] = set()
    checked_exit_phases: set[str] = set()
    observation_binding_matches = False
    if case_id == "Q05":
        expected_recovery = (
            (74 if MANAGEMENT_FAULT_WINDOWS[scenario].corruption else 0)
            if scenario in MANAGEMENT_FAULT_WINDOWS
            else (74 if ATOMIC_FAULT_WINDOWS[scenario][1] in ("file_fsynced", "file_linked") else 0)
        )
        expected_exits = {
            "crash": 73,
            "recovery-1": expected_recovery,
            "recovery-2": expected_recovery,
        }
        expected_paths = (
            {prefix + "/negative-observation.json"}
            | {
                f"{prefix}/phase-inventories/{phase}.json"
                for phase in ("before", "crashed", "recovered", "after")
            }
            | {
                f"{prefix}/process-records/{phase}{suffix}.json"
                for phase in expected_exits
                for suffix in ("", "-exit")
            }
        )
    for path in sorted(candidates):
        data = timed(
            timings,
            "original_record_" + path,
            lambda path=path: read_relative(deployment.root, path, max_bytes=4_194_304),
        )
        total += len(data)
        require(total <= 16_777_216, "ORIGINAL_CASE_AGGREGATE_BYTE_LIMIT")
        record = strict_json_object(data, max_bytes=4_194_304)
        if path == prefix + "/negative-observation.json":
            observation_binding_matches = (
                record.get("case") == scenario
                and record.get("case_family") == case_id
                and record.get("deployment_profile_hash") == deployment.profile.content_hash
                and record.get("campaign_hash") == deployment.bundle.campaign.content_hash
            )
        fact: dict[str, object] = {
            "original_source_path": path,
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }
        scoped_worker_record = path.startswith(prefix + "/process-records/")
        fact["record_scope"] = (
            "SELECTED_CASE" if path.startswith(prefix + "/") else ("DEPLOYMENT_WIDE_UNATTRIBUTED")
        )
        # Export only bounded structural diagnostics, never arbitrary log/messages.
        for field in ("schema_version", "phase", "error_type", "completion_status"):
            value = record.get(field)
            if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_./-]{1,100}", value):
                fact[field] = value
        exit_code = record.get("exit_code")
        if type(exit_code) is int and -255 <= exit_code <= 255:
            fact["exit_code"] = exit_code
            # Frozen corruption/atomic rejection codes are expected observations.
            phase = Path(path).name.removesuffix("-exit.json")
            expected_exit = expected_exits.get(phase)
            if scoped_worker_record and expected_exit is not None:
                fact["expected_exit_code"] = expected_exit
                checked_exit_phases.add(phase)
                failed |= exit_code != expected_exit
        locations = record.get("failure_locations")
        if isinstance(locations, list):
            safe_locations = []
            for location in locations[:100]:
                if not isinstance(location, dict):
                    continue
                module, function, line = (
                    location.get(key) for key in ("module", "function", "line")
                )
                if (
                    isinstance(module, str)
                    and re.fullmatch(r"[a-zA-Z0-9_.]{1,100}", module)
                    and isinstance(function, str)
                    and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", function)
                    and type(line) is int
                    and 0 < line < 1_000_000
                ):
                    safe_locations.append({"module": module, "function": function, "line": line})
            fact["failure_locations"] = safe_locations
        failed |= scoped_worker_record and path.endswith("-failure.json")
        facts.append(fact)
    return {
        "selected_case": case_id,
        "selected_scenario": scenario,
        "scope": "RETAINED_ORIGINAL_WORKER_RECORDS_ONLY_NO_AUTHORITY_OR_GATE_VERIFICATION",
        "original_record_count": len(facts),
        "original_hashed_bytes": total,
        "original_records": facts,
        "worker_failure_observed": failed,
        "capture_records_complete": bool(expected_paths)
        and expected_paths <= set(candidates)
        and checked_exit_phases == set(expected_exits)
        and observation_binding_matches,
        "missing_expected_record_paths": sorted(expected_paths - set(candidates)),
        "observation_binding_matches": observation_binding_matches,
        "negative_observation_available": "negative-observation.json" in names,
        "gate_evaluation": "NOT_EVALUATED",
        "formal_frozen_verification": "NOT_PERFORMED",
    }


def original_case_outcome(result: dict[str, object]) -> str:
    if result["worker_failure_observed"]:
        return "PROBLEM_FOUND"
    return "NO_PROBLEM_OBSERVED" if result["capture_records_complete"] else "NOT_EVALUATED"


def write_diagnostic(output: Path, payload: dict[str, object], protected: tuple[Path, ...]) -> None:
    require(output.is_absolute(), "ABSOLUTE_NEW_OUTPUT_REQUIRED")
    resolved = output.resolve(strict=False)
    for root in protected:
        frozen = root.resolve(strict=True)
        require(not resolved.is_relative_to(frozen), "OUTPUT_MUST_NOT_CHANGE_ORIGINALS")
    with opened_directory(output.parent) as descriptor:
        # The descriptor-anchored artifact writer refuses different existing bytes.
        require(not output.exists() and not output.is_symlink(), "NEW_DIAGNOSTIC_OUTPUT_REQUIRED")
        atomic_write_bytes_at(descriptor, output.name, canonical_json_bytes(payload))


def run_requested_check(
    args: argparse.Namespace, deployment: HostedManagedDeployment, timings: dict[str, float]
) -> dict[str, object]:
    if args.command == "deployment":
        result = inspect_deployment(deployment, timings)
        if args.permission_proof:
            from quantos.infrastructure.hosted_security_verification import (
                verify_deployment_security,
            )

            hashes = timed(
                timings,
                "retained_original_permission_proof",
                lambda: verify_deployment_security(deployment),
            )
            result["permission_scope"] = "RETAINED_ORIGINAL_OS_PROBE_REVERIFIED_NO_NEW_PROBE"
            result["permission_checked_artifact_hashes"] = hashes
    elif args.command == "capacity":
        exported = timed(
            timings,
            "typed_source_index",
            lambda: read_manager_export(args.index.parent, args.index.name),
        )
        require(
            exported.exact_commit == args.commit
            and exported.deployment_profile_hash == args.profile_hash,
            "CAPACITY_INDEX_PINS_DIFFER",
        )
        require(
            read_relative(
                deployment.root,
                f"evidence/{exported.content_hash}",
                max_bytes=MAX_MANAGER_EXPORT_BYTES,
            )
            == exported.canonical_bytes(),
            "CAPACITY_INDEX_NOT_ORIGINAL",
        )
        reference = None
        if args.reference_inventory:
            reference = parse_hosted_contract(
                read_relative(args.reference_inventory.parent, args.reference_inventory.name),
                HostedRawInventory,
                max_bytes=MAX_TYPED_BYTES,
            )
        result = timed(
            timings,
            "capacity_and_layout_estimate",
            lambda: index_capacity(exported, reference, args.additional_authorities),
        )
    elif args.command == "gate":
        result = diagnose_gate(
            args.bundle,
            args.case,
            deployment,
            timings,
            max_source_files=args.max_source_files,
            max_source_bytes=args.max_source_bytes,
        )
    else:
        result = inspect_original_case(deployment, args.case_id, args.scenario, timings)
    return result


def main() -> None:
    sys.dont_write_bytecode = True
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--business-inputs-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    deployment_parser = commands.add_parser("deployment")
    deployment_parser.add_argument(
        "--permission-proof",
        action="store_true",
        help="Reverify the retained original OS probe; never launch a new probe.",
    )
    capacity = commands.add_parser("capacity")
    capacity.add_argument("--index", type=Path, required=True)
    capacity.add_argument("--reference-inventory", type=Path)
    capacity.add_argument(
        "--additional-authorities",
        type=int,
        default=0,
        help="Count the complete planned logical authority layout, including reuse, replay and "
        "tamper copies. Synthetic prefixes are assumptions; this is not a final-export "
        "upper bound.",
    )
    gate = commands.add_parser("gate")
    gate.add_argument("--bundle", type=Path, required=True)
    gate.add_argument(
        "--case-id", "--case", dest="case", choices=HOSTED_QUALIFICATION_CASES, required=True
    )
    gate.add_argument("--max-source-files", type=int, default=100_000)
    gate.add_argument("--max-source-bytes", type=int, default=128 * 1024**3)
    original = commands.add_parser("original-case")
    original.add_argument("--case-id", choices=HOSTED_QUALIFICATION_CASES, required=True)
    original.add_argument("--scenario", required=True)
    args = parser.parse_args()
    protected = [args.manager_root, Path(__file__).resolve().parents[1]]
    if args.command == "gate":
        protected.append(args.bundle)
    elif (
        args.command == "capacity" and (args.index.parent / "qualification-manifest.json").exists()
    ):
        protected.append(args.index.parent)
    workspace = Path(__file__).resolve().parents[1]
    executing_commit = subprocess.check_output(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
    ).strip()
    timings: dict[str, float] = {}
    payload: dict[str, object] = {
        "schema_version": "hosted-development-diagnostic/v1",
        "eligibility": "NOT_QUALIFIED",
        "purpose": "DEVELOPMENT_EARLY_CHECK_ONLY",
        "command": args.command,
        "original_manager_root": str(args.manager_root),
        "exact_commit": args.commit,
        "deployment_profile_hash": args.profile_hash,
        "business_inputs_hash": args.business_inputs_hash,
        "tool_sha256": sha256_bytes(Path(__file__).read_bytes()),
        "executing_worktree_commit": executing_commit,
        "execution_scope": "DEVELOPMENT_WORKTREE_NOT_FROZEN_INSTALLED_VERIFIER",
        "executing_manager_export_cap_bytes": MAX_MANAGER_EXPORT_BYTES,
        "source_historical_cap": "NOT_INFERRED_FROM_DIAGNOSTIC_EXECUTION",
        "denominators": case_denominators(),
        "stage_elapsed_seconds": timings,
    }
    stage = "PIN_C_B_D"
    try:
        deployment = timed(timings, "pin_c_b_d", lambda: pin_deployment(args))
        roots = [
            deployment.paths.install,
            deployment.paths.provenance,
            deployment.paths.configuration,
            deployment.paths.projection,
            deployment.paths.offline_inputs,
            deployment.paths.authority,
        ]
        if args.command == "gate":
            roots.append(args.bundle)
            original_family = deployment.root / "qualification-cases" / args.case
            if original_family.exists():
                roots.append(original_family)
        elif args.command == "original-case":
            roots.append(deployment.root / "qualification-cases" / args.case_id / args.scenario)
        change_guard: dict[str, object] = {}
        payload["original_tree_change_guard"] = change_guard
        stage = args.command.upper()
        result = check_guarded_action(
            tuple(roots),
            lambda: run_requested_check(args, deployment, timings),
            change_guard,
            timings,
        )
        outcome = "NO_PROBLEM_OBSERVED"
        if args.command == "gate":
            verdict = result["predicate_observation"]["verdict"]
            outcome = {
                "PASS": "NO_PROBLEM_OBSERVED",
                "FAIL": "PROBLEM_FOUND",
                "NOT_EVALUATED": "NOT_EVALUATED",
            }[verdict]
        elif args.command == "capacity" and "layout_estimate" in result:
            if result["layout_estimate"]["projected_headroom_bytes"] < 0:
                outcome = "PROBLEM_FOUND"
        elif args.command == "original-case":
            outcome = original_case_outcome(result)
        payload.update(
            {"execution": "COMPLETED", "diagnostic_outcome": outcome, "observations": result}
        )
    except (
        HostedQualificationError,
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
    ) as error:
        # Never serialize exception messages: original input may contain sensitive values.
        payload.update(
            {"execution": "FAILED", "failure_stage": stage, "error_class": type(error).__name__}
        )
        if isinstance(error, DiagnosticCheckError):
            payload["failure_code"] = error.code
    write_diagnostic(args.output, payload, tuple(protected))
    print(f"development diagnostic: {args.output}; eligibility: NOT_QUALIFIED")
    if (
        payload["execution"] != "COMPLETED"
        or payload["diagnostic_outcome"] != "NO_PROBLEM_OBSERVED"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
