"""Managed discovery proposal capture through the existing isolated Codex transport.

This successor binds design/request/reservation originals before launch. Capturing a
source does not adopt the old campaign's business qualification or confer SDK status.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from quantos.application.discovery_hosted import (
    generation_prompt,
    generation_schema_bytes,
    parse_generation_request,
)
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import DiscoveryDesignContract, DiscoveryDesignReader
from quantos.contracts.discovery_hosted import (
    HostedGenerationProjectionFact,
    HostedGenerationRequest,
    HostedSequentialGenerationRequest,
)
from quantos.contracts.hosted import parse_hosted_contract
from quantos.contracts.hosted_deployment import (
    HostedDeploymentProfile,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedLauncherRecord,
)
from quantos.infrastructure.hosted_deployment import (
    HostedNamespacePaths,
    install_inventory,
    namespace_command,
    read_projection,
    source_seccomp_filter,
    system_runtime_inventory,
    verify_install,
)
from quantos.infrastructure.hosted_launcher import (
    EXTRACTION_RULE_BYTES,
    LauncherOutcome,
    TrustedCodexLauncher,
    TrustedLauncherEvidenceStore,
    _capture_process,  # pyright: ignore[reportPrivateUsage]
    extract_proposal,
    probe_projection_mount,
    register_model_auth_memory,
    scan_cli_capture,
)
from quantos.infrastructure.hosted_storage import storage_checkpoint
from quantos.security import SecretArtifactRejected

_OBJECT_CAP = 2_097_152
_PROJECTION_CAP = 16_777_216
_RUNTIME_INVENTORY_CAP = 16_777_216
_ACCEPTED_COMPONENT_HASH = "e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec"
_ACCEPTED_PROFILE_HASH = "1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf"
_ACCEPTED_INSTALL_HASH = "cabd9c952f30dc92e689879087a0d564f5b40d9b210b08ad313aef76567d1624"
_ACCEPTED_COMMIT = "a47e5a95db15f51e748c1343d96e124fc5b04d8c"
_ACCEPTED_BUSINESS_HASH = "4d577d6521d7413202f41c1d8260b2bace2cebb82e0b33438220b6a004deb829"


def _durable_root(root: Path) -> None:
    absolute = root.absolute()
    if (
        absolute.resolve(strict=True) != absolute
        or ".." in absolute.parts
        or any(absolute.is_relative_to(Path(prefix)) for prefix in ("/tmp", "/var/tmp"))
    ):
        raise ArtifactIntegrityError("generation launcher evidence requires a durable root")


def verify_generation_projection_fact(
    fact: HostedGenerationProjectionFact,
    *,
    request: HostedGenerationRequest | HostedSequentialGenerationRequest,
    design: DiscoveryDesignContract,
    profile: HostedDeploymentProfile,
    configuration: HostedLauncherConfiguration,
    initial_inventory: HostedInstallInventory,
    projection_root: Path,
    evidence: TrustedLauncherEvidenceStore,
) -> HostedInstallInventory:
    """Verify every mounted original and the successor's exact prelaunch scope."""
    generation = request.generation_request
    required = {
        design.content_hash,
        generation.content_hash,
        request.reservation.content_hash,
        configuration.content_hash,
        profile.content_hash,
        request.proposal_schema_hash,
        *design.context_hashes,
    }
    if isinstance(request, HostedSequentialGenerationRequest):
        required.update(
            (
                request.policy.content_hash,
                request.attempt.content_hash,
                request.attempt.history.content_hash,
            )
        )
    if (
        fact.design_hash != design.content_hash
        or fact.design_hash != request.design_hash
        or fact.request_hash != request.content_hash
        or fact.reservation_hash != request.reservation.content_hash
        or fact.deployment_profile_hash != profile.content_hash
        or request.deployment_profile_hash != profile.content_hash
        or request.configuration_hash != configuration.content_hash
        or profile.model_configuration_hash != configuration.content_hash
        or profile.extraction_rule_hash != sha256_bytes(EXTRACTION_RULE_BYTES)
        or configuration.extraction_rule != "codex-jsonl-single-final/v2"
        or fact.initial_projection_inventory_hash != initial_inventory.content_hash
        or initial_inventory.content_hash != profile.projection_inventory_hash
        or generation.input_hashes != design.context_hashes
        or generation.max_attempts != design.evaluation_opportunities_per_method
        or generation.model_identifier != configuration.model
        or generation.reasoning_effort != configuration.reasoning_effort
        or configuration.proposal_byte_cap != request.max_response_bytes
        or request.max_response_bytes > design.max_output_bytes_per_attempt
        or set(request.projection_object_hashes) != required
        or set(request.input_hashes) != required
    ):
        raise ArtifactIntegrityError("generation prelaunch scope bindings disagree")
    actual = install_inventory(projection_root)
    if (
        actual.content_hash != fact.projection_inventory_hash
        or {item.relative_path for item in actual.files}
        != {*request.projection_object_hashes, request.content_hash}
        or sum(item.size_bytes for item in actual.files) > _PROJECTION_CAP + _OBJECT_CAP
    ):
        raise ArtifactIntegrityError("generation prelaunch projection inventory changed")
    initial_objects = {
        design.content_hash,
        configuration.content_hash,
        request.proposal_schema_hash,
        *design.context_hashes,
    }
    observed_initial = HostedInstallInventory(
        files=tuple(item for item in actual.files if item.relative_path in initial_objects)
    )
    if observed_initial.canonical_bytes() != initial_inventory.canonical_bytes():
        raise ArtifactIntegrityError("generation initial projection originals differ")
    originals = {
        request.content_hash: request.canonical_bytes(),
        design.content_hash: design.canonical_bytes(),
        generation.content_hash: generation.canonical_bytes(),
        request.reservation.content_hash: request.reservation.canonical_bytes(),
        profile.content_hash: profile.canonical_bytes(),
        configuration.content_hash: configuration.canonical_bytes(),
        request.proposal_schema_hash: generation_schema_bytes(),
    }
    if isinstance(request, HostedSequentialGenerationRequest):
        for contract in (request.policy, request.attempt, request.attempt.history):
            originals[contract.content_hash] = contract.canonical_bytes()
    if sha256_bytes(originals[request.proposal_schema_hash]) != request.proposal_schema_hash:
        raise ArtifactIntegrityError("generation proposal schema differs from current contract")
    for digest in (*request.projection_object_hashes, request.content_hash):
        data = read_projection(projection_root, digest, max_bytes=_OBJECT_CAP)
        evidence.guard(data)
        if digest in originals and data != originals[digest]:
            raise ArtifactIntegrityError("generation mounted contract original differs")
        if digest == request.content_hash:
            parse_generation_request(data)
        elif digest == design.content_hash:
            try:
                decoded_design = DiscoveryDesignReader.model_validate_json(data)
            except ValueError:
                raise ArtifactIntegrityError("generation projected design is invalid") from None
            if decoded_design.canonical_bytes() != data:
                raise ArtifactIntegrityError("generation projected design is not canonical")
    return actual


def publish_generation_projection_fact(
    request: HostedGenerationRequest | HostedSequentialGenerationRequest,
    design: DiscoveryDesignContract,
    *,
    profile: HostedDeploymentProfile,
    configuration: HostedLauncherConfiguration,
    initial_inventory: HostedInstallInventory,
    projection_root: Path,
    host_instance: str,
    evidence: TrustedLauncherEvidenceStore,
) -> HostedGenerationProjectionFact:
    """Management verifies and durably publishes Pi before any model invocation."""
    _durable_root(evidence.root)
    _durable_root(projection_root)
    storage_checkpoint(evidence.root, "matrix", 0, profile.mount_policy_hash)
    actual = install_inventory(projection_root)
    fact = HostedGenerationProjectionFact(
        design_hash=design.content_hash,
        request_hash=request.content_hash,
        reservation_hash=request.reservation.content_hash,
        deployment_profile_hash=profile.content_hash,
        host_instance=host_instance,
        initial_projection_inventory_hash=initial_inventory.content_hash,
        projection_inventory_hash=actual.content_hash,
    )
    verify_generation_projection_fact(
        fact,
        request=request,
        design=design,
        profile=profile,
        configuration=configuration,
        initial_inventory=initial_inventory,
        projection_root=projection_root,
        evidence=evidence,
    )
    if evidence.publish_bytes(fact.canonical_bytes()) != fact.content_hash:
        raise ArtifactIntegrityError("generation prelaunch publication hash differs")
    return fact


def _capture_generation_projection(
    paths: HostedNamespacePaths,
    *,
    profile: HostedDeploymentProfile,
    configuration: HostedLauncherConfiguration,
    evidence: TrustedLauncherEvidenceStore,
    request: HostedGenerationRequest | HostedSequentialGenerationRequest,
    projection: HostedInstallInventory,
    projection_fact_hash: str,
    host_instance: str,
    prompt: bytes,
    model_auth_memory_fd: int | None,
) -> tuple[HostedLauncherRecord, bytes | None]:
    """Shared frozen transport; caller must mechanically verify the actual projection first."""
    seccomp_fd, bpf = source_seccomp_filter()
    try:
        if sha256_bytes(bpf) != profile.seccomp_bpf_hash:
            raise ArtifactIntegrityError("launcher source filter changed")
        mount = probe_projection_mount(
            paths,
            request=request,
            profile=profile,
            projection=projection,
            seccomp_fd=seccomp_fd,
        )
        isolation_observation_hash = evidence.publish_bytes(mount.canonical_bytes())
        os.lseek(seccomp_fd, 0, os.SEEK_SET)
        command = (
            "/install/codex",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--model",
            configuration.model,
            "-c",
            f'model_reasoning_effort="{configuration.reasoning_effort}"',
            "--sandbox",
            "read-only",
            "--output-schema",
            "/projection/" + request.proposal_schema_hash,
            "-",
        )
        argv = namespace_command(
            "host",
            paths,
            command,
            seccomp_fd=seccomp_fd,
            mount_policy_hash=profile.mount_policy_hash,
        )
        descriptors = (seccomp_fd,)
        if model_auth_memory_fd is not None:
            # bwrap copies the caller's private memory fd into tmpfs; no disk auth copy.
            # The outer controller must include auth's known values in its guard.
            index = len(argv) - len(command)
            argv = (
                *argv[:index],
                "--ro-bind-data",
                str(model_auth_memory_fd),
                "/tmp/codex/auth.json",
                *argv[index:],
            )
            descriptors = (*descriptors, model_auth_memory_fd)
        started = datetime.now(UTC)
        if not request.issued_at <= started < request.expires_at:
            raise ArtifactIntegrityError("generation request expired before process launch")
        if (request.expires_at - started).total_seconds() < configuration.runtime_timeout_seconds:
            raise ArtifactIntegrityError("generation capture deadline exceeds request interval")
        try:
            exit_code, output, diagnostic, outcome = _capture_process(
                argv, pass_fds=descriptors, configuration=configuration, input_bytes=prompt
            )
        except (OSError, subprocess.TimeoutExpired):
            exit_code, output, diagnostic, outcome = None, b"", b"", "REJECTED"
    finally:
        os.close(seccomp_fd)
    terminated = datetime.now(UTC)
    proposal: bytes | None = None
    model: str | None = None
    output_hash = diagnostic_hash = None
    reason = "CLI_EVENT_CAPTURED"
    raw_complete = outcome not in ("OUTPUT_LIMIT", "TIMED_OUT")
    try:
        scan_cli_capture(output, guard=evidence.guard)
        scan_cli_capture(diagnostic, guard=evidence.guard)
        output_hash = evidence.publish_bytes(output)
        diagnostic_hash = evidence.publish_bytes(diagnostic)
        if outcome == "CAPTURED" and exit_code == 0:
            proposal, model = extract_proposal(output, configuration, guard=evidence.guard)
        else:
            reason = "CLI_PROCESS_NOT_COMPLETED"
            if outcome == "CAPTURED":
                outcome = "REJECTED"
    except (ValueError, UnicodeError, RecursionError, SecretArtifactRejected):
        outcome, reason = "REJECTED", "CLI_OUTPUT_UNSAFE_OR_SOURCE_INVALID"
        proposal = None
    record = HostedLauncherRecord(
        deployment_profile_hash=profile.content_hash,
        host_instance=host_instance,
        request_hash=request.content_hash,
        projection_inventory_hash=projection.content_hash,
        projection_fact_hash=projection_fact_hash,
        executable_hash=profile.cli_binary_hash,
        executable_version=profile.cli_version,
        configuration_hash=configuration.content_hash,
        argv_hash=sha256_bytes(canonical_json_bytes(command)),
        prompt_hash=sha256_bytes(prompt),
        isolation_observation_hash=isolation_observation_hash,
        raw_output_hash=output_hash,
        raw_output_complete=raw_complete,
        diagnostic_output_hash=diagnostic_hash,
        proposal_hash=sha256_bytes(proposal) if proposal else None,
        proposal_bytes=len(proposal) if proposal else 0,
        actual_model_identifier=model,
        started_at=started,
        terminated_at=terminated,
        exit_code=exit_code,
        outcome=cast("LauncherOutcome", outcome),
        reason=reason,
        unavailable_reasons=(
            "HOST_INTERNAL_USAGE_UNAVAILABLE",
            "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
            "MODEL_IDENTIFIER_NOT_IMMUTABLE",
            "PROVIDER_INTERNAL_TRANSCRIPT_UNAVAILABLE",
            *(("MODEL_IDENTITY_NOT_EXPOSED_BY_CLI",) if model is None else ()),
        ),
    )
    evidence.publish_record(record)
    return record, proposal


class DiscoveryCodexLauncher:
    """Management-only launcher with no host access to authority or source storage.

    Each persisted generation reservation can launch at most once. A crash leaves
    its immutable prelaunch evidence unresolved; retry requires a new reservation.
    """

    def __init__(
        self,
        paths: HostedNamespacePaths,
        profile: HostedDeploymentProfile,
        install: HostedInstallInventory,
        configuration: HostedLauncherConfiguration,
        evidence: TrustedLauncherEvidenceStore,
        *,
        adopted_profile: HostedDeploymentProfile,
        accepted_component_record_path: Path,
    ) -> None:
        # Adopt the exact old executable/configuration checks, without claiming its
        # old campaign business outcome applies to the discovery generation scope.
        TrustedCodexLauncher(paths, profile, install, configuration, evidence)
        self.paths, self.profile, self.install = paths, profile, install
        self.configuration, self.evidence = configuration, evidence
        self.adopted_profile = adopted_profile
        _durable_root(evidence.root)
        _durable_root(paths.projection)
        with opened_directory(accepted_component_record_path.parent) as directory_fd:
            accepted_bytes = read_regular_bytes_at(
                directory_fd, accepted_component_record_path.name, max_bytes=131_072
            )
        if sha256_bytes(accepted_bytes) != _ACCEPTED_COMPONENT_HASH:
            raise ArtifactIntegrityError("generation requires the adopted component original")
        self.evidence.guard(accepted_bytes)
        accepted = cast(dict[str, object], json.loads(accepted_bytes))
        if (
            accepted.get("decision") != "ACCEPT_COMPONENT_V2"
            or accepted.get("engineering_status") != "ACCEPTED_COMPONENT_V2"
            or accepted.get("candidate_tuple")
            != {
                "business_inputs_hash": _ACCEPTED_BUSINESS_HASH,
                "deployment_profile_hash": _ACCEPTED_PROFILE_HASH,
                "exact_commit": _ACCEPTED_COMMIT,
                "install_inventory_hash": _ACCEPTED_INSTALL_HASH,
            }
            or adopted_profile.content_hash != _ACCEPTED_PROFILE_HASH
            or install.content_hash != _ACCEPTED_INSTALL_HASH
            or adopted_profile.exact_commit != _ACCEPTED_COMMIT
            or profile.model_dump(exclude={"model_configuration_hash", "projection_inventory_hash"})
            != adopted_profile.model_dump(
                exclude={"model_configuration_hash", "projection_inventory_hash"}
            )
        ):
            raise ArtifactIntegrityError("generation adopted component scope differs")
        self._accepted_component_bytes = accepted_bytes

    def _verify_runtime_originals(self, initial_inventory: HostedInstallInventory) -> None:
        for contract in (
            self.adopted_profile,
            self.profile,
            self.install,
            self.configuration,
            initial_inventory,
        ):
            if (
                read_projection(
                    self.paths.configuration,
                    contract.content_hash,
                    max_bytes=_RUNTIME_INVENTORY_CAP,
                )
                != contract.canonical_bytes()
            ):
                raise ArtifactIntegrityError("generation frozen runtime original differs")
        verify_install(self.paths.install, self.install)
        if (
            install_inventory(self.paths.provenance).content_hash
            != self.profile.provenance_inventory_hash
            or sha256_file(self.paths.provenance / "uv.lock") != self.profile.lock_hash
            or sha256_file(Path("/usr/bin/bwrap")) != self.profile.bwrap_binary_hash
            or sha256_file(Path("/lib/x86_64-linux-gnu/libseccomp.so.2").resolve(strict=True))
            != self.profile.libseccomp_binary_hash
            or system_runtime_inventory().content_hash != self.profile.os_inventory_hash
        ):
            raise ArtifactIntegrityError("generation frozen runtime or provenance changed")

    def capture(
        self,
        request: HostedGenerationRequest | HostedSequentialGenerationRequest,
        design: DiscoveryDesignContract,
        projection: HostedInstallInventory,
        initial_inventory: HostedInstallInventory,
        *,
        projection_fact_hash: str,
        host_instance: str,
        model_auth_memory_fd: int | None = None,
    ) -> tuple[HostedLauncherRecord, bytes | None]:
        """Capture one original final message; caller owns response/source verification."""
        storage_checkpoint(
            self.evidence.root,
            "matrix",
            2 * self.configuration.output_byte_cap + 2 * request.max_response_bytes + _OBJECT_CAP,
            self.profile.mount_policy_hash,
        )
        storage_checkpoint(
            self.paths.configuration.parent, "matrix", 0, self.profile.mount_policy_hash
        )
        if model_auth_memory_fd is not None:
            register_model_auth_memory(model_auth_memory_fd, self.evidence.guard)
        if self.evidence.publish_bytes(self._accepted_component_bytes) != _ACCEPTED_COMPONENT_HASH:
            raise ArtifactIntegrityError("generation component original publication differs")
        self._verify_runtime_originals(initial_inventory)
        fact = parse_hosted_contract(
            self.evidence.read_bytes(projection_fact_hash, max_bytes=65_536),
            HostedGenerationProjectionFact,
            max_bytes=65_536,
        )
        if fact.content_hash != projection_fact_hash or fact.host_instance != host_instance:
            raise ArtifactIntegrityError("generation launch requires its trusted prelaunch fact")
        actual = verify_generation_projection_fact(
            fact,
            request=request,
            design=design,
            profile=self.profile,
            configuration=self.configuration,
            initial_inventory=initial_inventory,
            projection_root=self.paths.projection,
            evidence=self.evidence,
        )
        if actual.canonical_bytes() != projection.canonical_bytes():
            raise ArtifactIntegrityError("generation requested mount inventory differs")
        prompt = generation_prompt(request)
        self.evidence.guard(prompt)
        if len(prompt) > _OBJECT_CAP:
            raise ArtifactIntegrityError("generation prompt exceeds its bound")
        launches = self.evidence.root / "generation-launches"
        with exclusive_directory_lock(launches):
            attempt = launches / request.reservation.content_hash
            marker = attempt / "prelaunch.json"
            if marker.exists():
                raise ArtifactIntegrityError("generation reservation already has a launch attempt")
            now = datetime.now(UTC)
            if not request.issued_at <= now < request.expires_at:
                raise ArtifactIntegrityError("generation request is outside its launch interval")
            prelaunch = canonical_json_bytes(
                {
                    "schema_version": "discovery-hosted-launch-attempt/v1",
                    "qualification": "NOT_EVALUATED",
                    "request_hash": request.content_hash,
                    "reservation_hash": request.reservation.content_hash,
                    "design_hash": design.content_hash,
                    "projection_fact_hash": fact.content_hash,
                    "projection_inventory_hash": actual.content_hash,
                    "deployment_profile_hash": self.profile.content_hash,
                    "configuration_hash": self.configuration.content_hash,
                    "accepted_component_record_hash": _ACCEPTED_COMPONENT_HASH,
                    "adopted_deployment_profile_hash": self.adopted_profile.content_hash,
                    "adopted_scope": "RUNTIME_AND_ISOLATION_FACILITIES_ONLY",
                    "successor_profile_differences": (
                        "model_configuration_hash",
                        "projection_inventory_hash",
                    ),
                    "old_business_qualification_adopted": False,
                    "prompt_hash": sha256_bytes(prompt),
                    "started_at": now,
                }
            )
            self.evidence.guard(prelaunch)
            atomic_write_bytes(marker, prelaunch)
            try:
                record, proposal = _capture_generation_projection(
                    self.paths,
                    profile=self.profile,
                    configuration=self.configuration,
                    evidence=self.evidence,
                    request=request,
                    projection=actual,
                    projection_fact_hash=fact.content_hash,
                    host_instance=host_instance,
                    prompt=prompt,
                    model_auth_memory_fd=model_auth_memory_fd,
                )
            except Exception:
                # No invented process exit or raw exception/provider/auth text.
                atomic_write_bytes(
                    attempt / "completion.json",
                    canonical_json_bytes(
                        {
                            "schema_version": "discovery-hosted-launch-completion/v1",
                            "prelaunch_hash": sha256_bytes(prelaunch),
                            "outcome": "FAILED",
                            "reason": "LAUNCH_OR_CAPTURE_FAILED",
                            "process_exit": None,
                            "terminated_at": datetime.now(UTC),
                        }
                    ),
                )
                raise ArtifactIntegrityError("generation launch or capture failed") from None
            atomic_write_bytes(
                attempt / "completion.json",
                canonical_json_bytes(
                    {
                        "schema_version": "discovery-hosted-launch-completion/v1",
                        "prelaunch_hash": sha256_bytes(prelaunch),
                        "launcher_record_hash": record.content_hash,
                        "outcome": record.outcome,
                        "reason": record.reason,
                        "process_exit": record.exit_code,
                        "terminated_at": record.terminated_at,
                        "qualification": "NOT_EVALUATED",
                    }
                ),
            )
            return record, proposal
