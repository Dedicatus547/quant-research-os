#!/usr/bin/env python3
"""Capture exactly one managed discovery proposal through the accepted Hosted facilities.

Invocation requires the existing formal storage supervisor lease. No retries,
batch loop, SDK fallback, or scientific execution is performed by this command.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar, cast

from quantos.application.discovery_generation import GenerationStore
from quantos.application.discovery_hosted import HostedGenerationManager, generation_schema_bytes
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    DiscoveryDesign,
    GenerationRequest,
    GenerationReservation,
    SequentialGenerationPolicy,
    SequentialLaunchSource,
)
from quantos.contracts.discovery_hosted import (
    HostedGenerationOrigin,
    HostedGenerationResponse,
    HostedSequentialGenerationOrigin,
)
from quantos.contracts.hosted import (
    HostObservation,
    HostReportedUsage,
    parse_hosted_contract,
    strict_json_object,
)
from quantos.contracts.hosted_deployment import (
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
)
from quantos.infrastructure.discovery_launcher import (
    DiscoveryCodexLauncher,
    publish_generation_projection_fact,
)
from quantos.infrastructure.hosted_deployment import (
    NAMESPACE_TMPFS_BYTES,
    HostedNamespacePaths,
    KnownValueGuard,
    install_inventory,
    private_memory_fd,
)
from quantos.infrastructure.hosted_launcher import (
    TrustedLauncherEvidenceStore,
    _capture_process,  # pyright: ignore[reportPrivateUsage]
    register_model_auth_memory,
    scan_cli_capture,
)
from quantos.infrastructure.hosted_storage import (
    HASH_ENV,
    LEASE_ENV,
    POLICY_ENV,
    configured_guard,
    require_bounded_bwrap,
)

_C = TypeVar("_C", bound=CanonicalContract)
_CAP = 16_777_216
_INSTALL_VIEW_HASH = "42139146fad31485b1dff03f6df472c103dfb2bab84d3fde4c96f482330a8d02"
_BUSINESS_VIEW_HASH = "a2dfdfaac8748a626c972ac11ec9536f45021b5ec73cea55a5bd7229d551b6b4"
_PROFILE_HASH = "1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf"
_INSTALL_HASH = "cabd9c952f30dc92e689879087a0d564f5b40d9b210b08ad313aef76567d1624"


def _bytes(path: Path, cap: int = _CAP) -> bytes:
    path = path.absolute()
    with opened_directory(path.parent) as directory_fd:
        return read_regular_bytes_at(directory_fd, path.name, max_bytes=cap)


def _contract(path: Path, kind: type[_C], cap: int = _CAP) -> _C:
    return parse_hosted_contract(_bytes(path, cap), kind, max_bytes=cap)


def _object_path(value: object) -> Path:
    if not isinstance(value, str):
        raise ArtifactIntegrityError("runtime source path is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ArtifactIntegrityError("runtime source path is not explicit")
    return path


@dataclass(frozen=True)
class Inputs:
    design: DiscoveryDesign
    request: GenerationRequest
    configuration: HostedLauncherConfiguration
    contexts: dict[str, bytes]
    preparation_hash: str
    policy: SequentialGenerationPolicy | None = None


def _inputs(root: Path, store: GenerationStore) -> Inputs:
    data = _bytes(root / "preparation.json")
    preparation = strict_json_object(data, max_bytes=_CAP)
    preparation_hash = sha256_bytes(data)
    if root.name != f"sha256-{preparation_hash}":
        raise ArtifactIntegrityError("preparation requires its content-addressed directory")
    files = preparation.get("files")
    if not isinstance(files, dict):
        raise ArtifactIntegrityError("preparation original inventory is missing")
    inventory = cast(dict[str, object], files)
    originals: dict[str, bytes] = {}
    for name in ("design.json", "llm-request.json", "llm-configuration.json"):
        value = inventory.get(name)
        if not isinstance(value, dict):
            raise ArtifactIntegrityError("preparation required original is missing")
        identity = cast(dict[str, object], value)
        original = _bytes(root / name)
        if sha256_bytes(original) != identity.get("bytes_hash") or len(original) != identity.get(
            "size_bytes"
        ):
            raise ArtifactIntegrityError("preparation original differs")
        originals[name] = original
    design = parse_hosted_contract(originals["design.json"], DiscoveryDesign, max_bytes=_CAP)
    request = parse_hosted_contract(
        originals["llm-request.json"], GenerationRequest, max_bytes=_CAP
    )
    configuration = parse_hosted_contract(
        originals["llm-configuration.json"], HostedLauncherConfiguration, max_bytes=_CAP
    )
    if (
        request.method != "LLM"
        or request.max_attempts != 5
        or design.evaluation_opportunities_per_method != 5
        or request.design_hash != design.content_hash
        or preparation.get("design_hash") != design.content_hash
        or request.configuration_hash != configuration.content_hash
        or configuration.proposal_byte_cap != design.max_output_bytes_per_attempt
        or configuration.proposal_byte_cap != 65_536
    ):
        raise ArtifactIntegrityError("managed generation design/configuration scope differs")
    directory = store.root / "requests" / request.content_hash
    if (
        _contract(directory / "design.json", DiscoveryDesign) != design
        or _contract(directory / "request.json", GenerationRequest) != request
    ):
        raise ArtifactIntegrityError("generation authority differs from preparation")
    contexts: dict[str, bytes] = {}
    for digest in design.context_hashes:
        name = f"contexts/sha256-{digest}.json"
        original = _bytes(root / name)
        identity_value = inventory.get(name)
        if not isinstance(identity_value, dict):
            raise ArtifactIntegrityError("preparation context inventory is missing")
        identity = cast(dict[str, object], identity_value)
        if (
            sha256_bytes(original) != digest
            or identity.get("bytes_hash") != digest
            or identity.get("size_bytes") != len(original)
        ):
            raise ArtifactIntegrityError("preparation context original differs")
        contexts[digest] = original
    if sum(map(len, contexts.values())) > 65_536:
        raise ArtifactIntegrityError("managed generation context exceeds its frozen bound")
    version = preparation.get("schema_version")
    policy = None
    if version == "discovery-input-preparation/v2":
        data = _bytes(root / "sequential-policy.json")
        policy = parse_hosted_contract(data, SequentialGenerationPolicy, max_bytes=_CAP)
        identity_value = inventory.get("sequential-policy.json")
        if not isinstance(identity_value, dict):
            raise ArtifactIntegrityError("sequential preparation policy inventory is missing")
        identity = cast(dict[str, object], identity_value)
        if (
            identity.get("bytes_hash") != policy.content_hash
            or identity.get("size_bytes") != len(data)
            or policy.design_hash != design.content_hash
            or policy.request_hashes[0] != request.content_hash
        ):
            raise ArtifactIntegrityError("sequential preparation policy differs")
    elif version != "discovery-input-preparation/v1":
        raise ArtifactIntegrityError("unsupported generation preparation version")
    if store.sequential_policy() != policy:
        raise ArtifactIntegrityError("generation authority policy differs from preparation")
    return Inputs(design, request, configuration, contexts, preparation_hash, policy)


@dataclass(frozen=True)
class RuntimeView:
    install_root: Path
    provenance_root: Path
    mounts: tuple[tuple[Path, Path], ...]
    adopted_profile: HostedDeploymentProfile
    adopted_configuration: HostedLauncherConfiguration
    install: HostedInstallInventory
    inventory_bytes: int


def _runtime_view(install_path: Path, business_path: Path) -> RuntimeView:
    install_data, business_data = _bytes(install_path), _bytes(business_path)
    if (
        sha256_bytes(install_data) != _INSTALL_VIEW_HASH
        or sha256_bytes(business_data) != _BUSINESS_VIEW_HASH
    ):
        raise ArtifactIntegrityError(
            "managed generation requires the adopted readonly view originals"
        )
    install_view = strict_json_object(install_data, max_bytes=_CAP)
    business_view = strict_json_object(business_data, max_bytes=_CAP)
    install_root = _object_path(install_view["install_root"])
    old_manager = _object_path(business_view["manager_root"])
    provenance_root = old_manager / "provenance"
    profile = _contract(
        old_manager / "config" / f"sha256-{_PROFILE_HASH}.json", HostedDeploymentProfile
    )
    inventory_value = install_view.get("expected_install_inventory")
    if not isinstance(inventory_value, dict):
        raise ArtifactIntegrityError("adopted installation inventory source is missing")
    inventory_record = cast(dict[str, object], inventory_value)
    inventory_path = _object_path(inventory_record.get("path"))
    installation = _contract(inventory_path, HostedInstallInventory)
    if (
        profile.content_hash != _PROFILE_HASH
        or installation.content_hash != _INSTALL_HASH
        or profile.install_inventory_hash != installation.content_hash
        or inventory_record.get("sha256") != installation.content_hash
    ):
        raise ArtifactIntegrityError("adopted deployment/install originals differ")
    mounts: list[tuple[Path, Path]] = []
    raw_install_mounts = install_view.get("mounts")
    raw_business_mounts = business_view.get("mounts")
    if not isinstance(raw_install_mounts, list) or not isinstance(raw_business_mounts, list):
        raise ArtifactIntegrityError("adopted readonly source mappings are missing")
    old_configuration_target = (
        old_manager / "config" / f"sha256-{profile.model_configuration_hash}.json"
    )
    old_configuration_source: Path | None = None
    for raw in cast(list[object], raw_business_mounts):
        if isinstance(raw, dict):
            item = cast(dict[str, object], raw)
            if item.get("target_path") == str(old_configuration_target):
                old_configuration_source = _object_path(item.get("source_path"))
    if old_configuration_source is None:
        raise ArtifactIntegrityError("adopted model configuration readonly source is missing")
    adopted_configuration = _contract(old_configuration_source, HostedLauncherConfiguration)
    if adopted_configuration.content_hash != profile.model_configuration_hash:
        raise ArtifactIntegrityError("adopted model configuration original differs")
    for raw in (*cast(list[object], raw_install_mounts), *cast(list[object], raw_business_mounts)):
        if not isinstance(raw, dict):
            raise ArtifactIntegrityError("adopted readonly source mapping is invalid")
        item = cast(dict[str, object], raw)
        source, target = (
            _object_path(item.get("source_path")),
            _object_path(item.get("target_path")),
        )
        # The host needs only the accepted installation and its provenance, not
        # old business inputs, authority, data, channel state, or model context.
        if not (target.is_relative_to(install_root) or target == provenance_root):
            continue
        if item.get("read_only") is not True or source.resolve(strict=True) != source:
            raise ArtifactIntegrityError(
                "adopted runtime mapping is not a canonical readonly source"
            )
        info = source.stat()
        if item.get("kind") == "file":
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or sha256_file(source) != item.get("sha256")
            ):
                raise ArtifactIntegrityError("adopted runtime source file changed")
        elif item.get("kind") != "directory" or not stat.S_ISDIR(info.st_mode):
            raise ArtifactIntegrityError("adopted runtime source directory changed")
        mounts.append((source, target))
    if not any(target == install_root for _, target in mounts) or not any(
        target == provenance_root for _, target in mounts
    ):
        raise ArtifactIntegrityError("adopted runtime readonly roots are incomplete")
    return RuntimeView(
        install_root,
        provenance_root,
        tuple(mounts),
        profile,
        adopted_configuration,
        installation,
        len(_bytes(inventory_path)),
    )


def _memory_available() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1]) * 1024
    raise ArtifactIntegrityError("host available memory observation is unavailable")


def _authorize(args: argparse.Namespace, minimum_growth: int) -> dict[str, object]:
    growth = cast(int, args.expected_new_bytes)
    if growth <= 0 or growth < minimum_growth:
        raise ArtifactIntegrityError("managed capture growth estimate is incomplete")
    guard = configured_guard()
    for root in (args.generation_root, args.job_root, args.manager_root, args.evidence_root):
        guard.require_root(cast(Path, root))
    guard.require_lease()
    lease_name = os.environ.get(LEASE_ENV)
    if lease_name is None:
        raise ArtifactIntegrityError("managed capture requires the formal supervisor lease")
    lease_bytes = _bytes(Path(lease_name) / "prelaunch.json", 16_384)
    lease = strict_json_object(lease_bytes, max_bytes=16_384)
    declared = lease.get("expected_new_bytes")
    if type(declared) is not int or declared < growth:
        raise ArtifactIntegrityError(
            "managed capture estimate exceeds the formal lease reservation"
        )
    capacity = guard.check(growth)
    require_bounded_bwrap()
    available = _memory_available()
    # The retained guard protects physical disk. Host private tmpfs is separately
    # bounded by the frozen mount policy and also needs real memory headroom.
    memory_reserve = 2 * NAMESPACE_TMPFS_BYTES
    if available < memory_reserve:
        raise ArtifactIntegrityError("managed capture host memory headroom is unavailable")
    return {
        "storage_policy_hash": guard.policy_hash,
        "lease_prelaunch_hash": sha256_bytes(lease_bytes),
        "expected_new_bytes": growth,
        "minimum_growth_bytes": minimum_growth,
        "reservation_scope": "ENTIRE_CAPTURE_JOB_AND_ALL_CONCURRENT_LEASE_CHILDREN",
        "capacity": capacity,
        "memory_available_bytes": available,
        "memory_reservation_bytes": memory_reserve,
        "host_private_tmpfs_max_bytes": NAMESPACE_TMPFS_BYTES,
        "management_private_tmpfs_max_bytes": NAMESPACE_TMPFS_BYTES,
    }


def _growth(inputs: Inputs, runtime: RuntimeView) -> int:
    input_size = (
        len(inputs.design.canonical_bytes())
        + len(inputs.request.canonical_bytes())
        + len(inputs.configuration.canonical_bytes())
        + sum(map(len, inputs.contexts.values()))
        + (
            0
            if inputs.policy is None
            else len(inputs.policy.canonical_bytes()) + 2 * inputs.request.max_attempts * 65_536
        )
    )
    return (
        runtime.inventory_bytes
        + 6 * input_size
        + 2 * inputs.configuration.output_byte_cap
        + (2 << 20)
    )


def _auth_memory(path: Path, guard: KnownValueGuard) -> int:
    data = _bytes(path, 65_536)
    descriptor = private_memory_fd("discovery-hosted-model-auth")
    try:
        if os.write(descriptor, data) != len(data):
            raise ArtifactIntegrityError("managed capture private auth staging is incomplete")
        os.lseek(descriptor, 0, os.SEEK_SET)
        register_model_auth_memory(descriptor, guard)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _worker(args: argparse.Namespace, inputs: Inputs, runtime: RuntimeView) -> dict[str, object]:
    _authorize(args, _growth(inputs, runtime))
    prelaunch = strict_json_object(_bytes(args.job_root / "prelaunch.json"), max_bytes=_CAP)
    if (
        prelaunch.get("request_hash") != inputs.request.content_hash
        or prelaunch.get("preparation_hash") != inputs.preparation_hash
        or prelaunch.get("install_inventory_hash") != runtime.install.content_hash
        or prelaunch.get("script_hash") != sha256_file(Path(__file__).absolute())
    ):
        raise ArtifactIntegrityError("managed capture worker has no matching durable prelaunch")
    store = GenerationStore(args.generation_root)
    guard = KnownValueGuard((), byte_cap=_CAP)
    evidence = TrustedLauncherEvidenceStore(args.evidence_root, guard)
    manager = HostedGenerationManager(
        args.manager_root,
        evidence=evidence,
        authenticated_principal=args.authenticated_principal,
        guard=guard,
    )
    auth_fd = _auth_memory(args.model_auth_file, guard)
    reservation: GenerationReservation | None = None
    completion_retained = False
    try:
        configuration_root = args.manager_root / "runtime" / "config"
        initial_root = args.manager_root / "runtime" / "initial-projection"
        base_objects = dict(inputs.contexts)
        base_objects[inputs.design.content_hash] = inputs.design.canonical_bytes()
        base_objects[inputs.configuration.content_hash] = inputs.configuration.canonical_bytes()
        schema = generation_schema_bytes()
        base_objects[sha256_bytes(schema)] = schema
        for digest, data in base_objects.items():
            guard(data)
            atomic_write_bytes(initial_root / digest, data)
        initial = install_inventory(initial_root)
        successor_payload = runtime.adopted_profile.model_dump(mode="python")
        successor_payload["model_configuration_hash"] = inputs.configuration.content_hash
        successor_payload["projection_inventory_hash"] = initial.content_hash
        successor = HostedDeploymentProfile.model_validate(successor_payload)
        for contract in (
            runtime.adopted_profile,
            successor,
            runtime.install,
            inputs.configuration,
            initial,
        ):
            atomic_write_bytes(
                configuration_root / contract.content_hash, contract.canonical_bytes()
            )
        for name in ("channel", "authority", "offline-inputs"):
            with opened_directory(args.manager_root / "runtime" / name, create=True):
                pass
        paths = HostedNamespacePaths(
            install=runtime.install_root,
            projection=initial_root,
            channel=args.manager_root / "runtime" / "channel",
            authority=args.manager_root / "runtime" / "authority",
            configuration=configuration_root,
            provenance=runtime.provenance_root,
            offline_inputs=args.manager_root / "runtime" / "offline-inputs",
        )
        # Dependency/auth availability and the exact adopted tuple are checked
        # before consuming an opportunity; a provider launch always follows reserve.
        DiscoveryCodexLauncher(
            paths,
            successor,
            runtime.install,
            inputs.configuration,
            evidence,
            adopted_profile=runtime.adopted_profile,
            accepted_component_record_path=args.accepted_component_record,
        )
        if args.reserved_ordinal is None:
            reservation = store.reserve(inputs.request)
        else:
            reservations, responses = store.inventory(inputs.request)
            reservation = next(
                item for item in reservations if item.ordinal == args.reserved_ordinal
            )
            if (
                any(item.reservation == reservation for item in responses)
                or reservation != reservations[-1]
            ):
                raise ArtifactIntegrityError(
                    "reserved-slot recovery requires the final unfinished slot"
                )
        atomic_write_bytes(
            args.job_root / "generation-reservation.json", reservation.canonical_bytes()
        )
        if inputs.policy is not None:
            original_source = store.launch_source(inputs.request, reservation)
            if original_source is None:
                original_source = SequentialLaunchSource(
                    request_hash=inputs.request.content_hash,
                    reservation_hash=reservation.content_hash,
                    manager_root=str(manager.root),
                    evidence_root=str(evidence.root.absolute()),
                    job_root=str(args.job_root),
                    authenticated_principal=args.authenticated_principal,
                )
            elif (
                original_source.manager_root != str(manager.root)
                or original_source.evidence_root != str(evidence.root.absolute())
                or original_source.authenticated_principal != args.authenticated_principal
            ):
                raise ArtifactIntegrityError("reserved-slot recovery management origins differ")
            store.save_launch_source(inputs.request, reservation, original_source)
        now = datetime.now(UTC)
        request = manager.prepare(
            inputs.design,
            inputs.request,
            reservation,
            inputs.configuration,
            successor,
            context_objects=inputs.contexts,
            issued_at=now,
            expires_at=now + timedelta(seconds=inputs.configuration.runtime_timeout_seconds + 600),
            policy=inputs.policy,
            attempt=None
            if inputs.policy is None
            else store.read_attempt(inputs.request, reservation),
        )
        # Origin re-verification reads these trusted originals, never a caller's
        # response claim or files named by provider output.
        for contract in (request, inputs.configuration, successor):
            evidence.publish_bytes(contract.canonical_bytes())
        projection_root = manager.root / request.content_hash / "projection"
        projection = install_inventory(projection_root)
        fact = publish_generation_projection_fact(
            request,
            inputs.design,
            profile=successor,
            configuration=inputs.configuration,
            initial_inventory=initial,
            projection_root=projection_root,
            host_instance=args.host_instance,
            evidence=evidence,
        )
        paths = HostedNamespacePaths(
            install=paths.install,
            projection=projection_root,
            channel=paths.channel,
            authority=paths.authority,
            configuration=paths.configuration,
            provenance=paths.provenance,
            offline_inputs=paths.offline_inputs,
        )
        launcher = DiscoveryCodexLauncher(
            paths,
            successor,
            runtime.install,
            inputs.configuration,
            evidence,
            adopted_profile=runtime.adopted_profile,
            accepted_component_record_path=args.accepted_component_record,
        )
        record, proposal = launcher.capture(
            request,
            inputs.design,
            projection,
            initial,
            projection_fact_hash=fact.content_hash,
            host_instance=args.host_instance,
            model_auth_memory_fd=auth_fd,
        )
        atomic_write_bytes(args.job_root / "launcher-record.json", record.canonical_bytes())
        if proposal is None or record.outcome != "CAPTURED":
            code = (
                "CAPTURE_OUTPUT_LIMIT"
                if record.outcome == "OUTPUT_LIMIT"
                else "CAPTURE_PROVENANCE_REJECTED"
            )
            rejected = store.reject_capture(inputs.request, reservation, code)
            completion_retained = True
            return {
                "status": "FAILED",
                "reason": record.reason,
                "reservation_hash": reservation.content_hash,
                "launcher_record_hash": record.content_hash,
                "generation_response_hash": rejected.content_hash,
                "producer": rejected.producer,
            }
        response = HostedGenerationResponse(
            request_hash=request.content_hash,
            design_hash=inputs.design.content_hash,
            reservation_hash=reservation.content_hash,
            proposal_json=proposal.decode("utf-8"),
            proposal_hash=sha256_bytes(proposal),
            host_observation=HostObservation(
                requested_configuration_hash=inputs.configuration.content_hash,
                reported_model_identifier=record.actual_model_identifier,
                reported_reasoning_effort=inputs.configuration.reasoning_effort,
                reported_usage=HostReportedUsage(
                    unavailable_reason="HOST_INTERNAL_USAGE_UNAVAILABLE"
                ),
                external_evidence_hashes=(record.content_hash,),
                unavailable_reasons=(
                    "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                    "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                    "HOST_INTERNAL_USAGE_UNAVAILABLE",
                    "HOST_TRANSCRIPT_UNAVAILABLE",
                ),
            ),
        )
        receipt = manager.verify_existing_capture(
            response,
            request=request,
            configuration=inputs.configuration,
            profile=successor,
            launcher_record_hash=record.content_hash,
        )
        origin_payload: dict[str, object] = dict(
            manager_root=str(manager.root),
            evidence_root=str(evidence.root.absolute()),
            authenticated_principal=args.authenticated_principal,
            request_hash=request.content_hash,
            response_hash=response.content_hash,
            source_receipt_hash=receipt.content_hash,
            configuration_hash=inputs.configuration.content_hash,
            deployment_profile_hash=successor.content_hash,
        )
        if inputs.policy is None:
            origin = HostedGenerationOrigin.model_validate(origin_payload)
        else:
            origin_payload.update(
                generation_root=str(store.root),
                attempt_hash=store.read_attempt(inputs.request, reservation).content_hash,
            )
            origin = HostedSequentialGenerationOrigin.model_validate(origin_payload)
        retained = store.complete(
            inputs.request,
            reservation,
            proposal.decode("utf-8"),
            producer="HOSTED_HANDOFF",
            hosted_origin=origin,
            wall_seconds=(record.terminated_at - record.started_at).total_seconds(),
        )
        completion_retained = True
        return {
            "status": "COMPLETED" if retained.producer == "HOSTED_HANDOFF" else "FAILED",
            "reservation_hash": reservation.content_hash,
            "launcher_record_hash": record.content_hash,
            "generation_response_hash": retained.content_hash,
            "producer": retained.producer,
            "qualification": "NOT_EVALUATED",
        }
    except Exception:
        if reservation is not None and not completion_retained:
            # Preserve the actual launcher originals when available; never repair
            # a failed response or supply invented timing/usage/exit information.
            with suppress(Exception):
                store.reject_capture(inputs.request, reservation, "CAPTURE_PROVENANCE_REJECTED")
        raise ArtifactIntegrityError("managed generation capture failed") from None
    finally:
        os.close(auth_fd)


def _outer(args: argparse.Namespace, inputs: Inputs, runtime: RuntimeView) -> dict[str, object]:
    facts = _authorize(args, _growth(inputs, runtime))
    _bytes(args.model_auth_file, 65_536)  # Availability only; never persist or hash auth.
    with exclusive_directory_lock(args.job_root):
        if (args.job_root / "prelaunch.json").exists():
            raise ArtifactIntegrityError("capture job already has a retained prelaunch")
        for root in (args.generation_root, args.manager_root, args.evidence_root):
            with opened_directory(root, create=True):
                pass
        prelaunch = canonical_json_bytes(
            {
                "schema_version": "discovery-generation-job-prelaunch/v1",
                "qualification": "NOT_EVALUATED",
                "request_hash": inputs.request.content_hash,
                "design_hash": inputs.design.content_hash,
                "preparation_hash": inputs.preparation_hash,
                "install_view_hash": _INSTALL_VIEW_HASH,
                "business_view_hash": _BUSINESS_VIEW_HASH,
                "adopted_deployment_profile_hash": runtime.adopted_profile.content_hash,
                "install_inventory_hash": runtime.install.content_hash,
                "script_hash": sha256_file(Path(__file__).absolute()),
                "resource_reservation": facts,
                "started_at": datetime.now(UTC),
                "max_model_invocations": 1,
            }
        )
        atomic_write_bytes(args.job_root / "prelaunch.json", prelaunch)
        argv: list[str] = [
            "/usr/bin/bwrap",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev-bind",
            "/dev",
            "/dev",
            "--size",
            str(NAMESPACE_TMPFS_BYTES),
            "--tmpfs",
            "/tmp",
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "PYTHONPATH",
            str(Path(__file__).absolute().parents[1] / "src"),
        ]
        for variable in (POLICY_ENV, HASH_ENV, LEASE_ENV):
            value = os.environ.get(variable)
            if value is None:
                raise ArtifactIntegrityError("capture supervisor configuration is incomplete")
            argv.extend(("--setenv", variable, value))
        for source, target in runtime.mounts:
            argv.extend(("--ro-bind", str(source), str(target)))
        # The formal lease-control descriptor is opened by the guard in both
        # namespaces. It retains its exact inode/lock, without giving the model a
        # channel capability or any authority descriptor.
        lease_name = os.environ.get(LEASE_ENV)
        if lease_name is None:
            raise ArtifactIntegrityError("capture supervisor lease is missing")
        control = Path(lease_name).parent
        argv.extend(("--bind", str(control), str(control)))
        for root in (args.generation_root, args.job_root, args.manager_root, args.evidence_root):
            argv.extend(("--bind", str(root), str(root)))
        argv.extend(
            (
                str(Path(sys.executable).absolute()),
                str(Path(__file__).absolute()),
                *sys.argv[1:],
                "--inside-runtime",
            )
        )
        outer_config = inputs.configuration.model_copy(
            update={
                "output_byte_cap": 65_536,
                "runtime_timeout_seconds": min(
                    3600, inputs.configuration.runtime_timeout_seconds + 600
                ),
            }
        )
        try:
            exit_code, output, diagnostic, outcome = _capture_process(
                tuple(argv), pass_fds=(), configuration=outer_config, input_bytes=b""
            )
        except OSError:
            exit_code, output, diagnostic, outcome = None, b"", b"", "REJECTED"
        # The worker emits only bounded summaries. Raw model/auth data remain in
        # the existing private capture pipes and memory-only auth descriptor.
        safe_guard = KnownValueGuard(())
        try:
            scan_cli_capture(output, guard=safe_guard)
            scan_cli_capture(diagnostic, guard=safe_guard)
            atomic_write_bytes(args.job_root / "manager-output.json", output)
            atomic_write_bytes(args.job_root / "manager-diagnostic.txt", diagnostic)
        except ValueError:
            outcome = "REJECTED"
        completion = {
            "schema_version": "discovery-generation-job-completion/v1",
            "prelaunch_hash": sha256_bytes(prelaunch),
            "process_exit": exit_code,
            "outcome": outcome,
            "terminated_at": datetime.now(UTC),
            "qualification": "NOT_EVALUATED",
        }
        atomic_write_bytes(args.job_root / "completion.json", canonical_json_bytes(completion))
        if exit_code != 0 or outcome != "CAPTURED":
            return {
                "status": "FAILED",
                "reason": "MANAGEMENT_PROCESS_NOT_COMPLETED",
                "process_exit": exit_code,
            }
        return strict_json_object(
            _bytes(args.job_root / "worker-result.json", 65_536), max_bytes=65_536
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "preparation-root",
        "generation-root",
        "job-root",
        "manager-root",
        "evidence-root",
        "accepted-component-record",
        "install-view-manifest",
        "business-view-manifest",
        "model-auth-file",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected-new-bytes", type=int, required=True)
    parser.add_argument("--authenticated-principal", required=True)
    parser.add_argument("--host-instance", required=True)
    parser.add_argument(
        "--reserved-ordinal",
        type=int,
        help=(
            "resume a final unfinished slot before its single launcher prelaunch; "
            "never repeat an existing launch"
        ),
    )
    parser.add_argument("--inside-runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        for name in (
            "preparation_root",
            "generation_root",
            "job_root",
            "manager_root",
            "evidence_root",
            "accepted_component_record",
            "install_view_manifest",
            "business_view_manifest",
            "model_auth_file",
        ):
            setattr(args, name, cast(Path, getattr(args, name)).absolute())
        store = GenerationStore(args.generation_root)
        # Check the real volume, active exclusive reservation and memory before
        # opening the 10 MiB metadata inventory or hashing the fixed CLI binary.
        _authorize(args, 0)
        inputs = _inputs(args.preparation_root, store)
        runtime = _runtime_view(args.install_view_manifest, args.business_view_manifest)
        if inputs.configuration.model_dump(exclude={"proposal_byte_cap"}) != (
            runtime.adopted_configuration.model_dump(exclude={"proposal_byte_cap"})
        ):
            raise ArtifactIntegrityError("successor model configuration exceeds the adopted delta")
        result = (
            _worker(args, inputs, runtime) if args.inside_runtime else _outer(args, inputs, runtime)
        )
        if args.inside_runtime:
            encoded_result = canonical_json_bytes(result)
            strict_json_object(encoded_result, max_bytes=65_536)
            atomic_write_bytes(args.job_root / "worker-result.json", encoded_result)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "COMPLETED" else 1
    except Exception as error:
        # Fixed classification/type only; exceptions may embed response/auth text.
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": "MANAGED_CAPTURE_FAILED",
                    "error_type": type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
