"""Offline management preparation and original-source inspection for hm-discovery/v1.

No provider, launcher, account probe, or namespace is invoked here. Source inspection
is development evidence; it cannot confer the legacy Hosted qualification.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    DiscoveryDesign,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
    SequentialGenerationAttempt,
    SequentialGenerationPolicy,
)
from quantos.contracts.discovery_hosted import (
    HostedGenerationOrigin,
    HostedGenerationProjectionFact,
    HostedGenerationRequest,
    HostedGenerationResponse,
    HostedGenerationSourceReceipt,
    HostedSequentialGenerationOrigin,
    HostedSequentialGenerationRequest,
)
from quantos.contracts.hosted import HostObservation, HostReportedUsage, parse_hosted_contract
from quantos.contracts.hosted_deployment import (
    HostedDeploymentProfile,
    HostedExecutableHintMountObservation,
    HostedInstallInventory,
    HostedLauncherConfiguration,
    HostedLauncherRecord,
    HostedMountObservation,
)
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.infrastructure.hosted_deployment import (
    MOUNT_POLICY_BYTES,
    KnownValueGuard,
    install_inventory,
    read_projection,
)
from quantos.infrastructure.hosted_launcher import (
    EXTRACTION_RULE_BYTES,
    TrustedLauncherEvidenceStore,
    extract_proposal,
)
from quantos.security import validate_secret_free

_OBJECT_CAP = 2_097_152
_PROJECTION_CAP = 16_777_216


def generation_schema_bytes() -> bytes:
    """Provider form of the same safe AST: explicit fields, including nullable ones.

    Structured output requires every declared property to be present. This narrows
    serialization only; admission still applies the original safe DSL predicates.
    """

    def explicit(value: object) -> object:
        if isinstance(value, dict):
            item = {
                key: explicit(child)
                for key, child in cast(dict[str, object], value).items()
                if key != "default"
            }
            properties = item.get("properties")
            if isinstance(properties, dict):
                item["required"] = sorted(cast(dict[str, object], properties))
            return item
        if isinstance(value, list):
            return [explicit(child) for child in cast(list[object], value)]
        return value

    return canonical_json_bytes(explicit(SafeQlibExpressionSpec.model_json_schema()))


def _scan_safe(value: object) -> None:
    def scan_view(item: object) -> object:
        if isinstance(item, dict):
            return {key: scan_view(child) for key, child in cast(dict[str, object], item).items()}
        if isinstance(item, (tuple, list)):
            return [scan_view(child) for child in cast(tuple[object, ...] | list[object], item)]
        if isinstance(item, str):
            try:
                embedded: object = json.loads(item)
            except (ValueError, RecursionError):
                embedded = None
            if isinstance(embedded, (dict, list)):
                return scan_view(cast(object, embedded))
            if len(item) > 65_536:
                return [
                    item[max(0, offset - 4096) : offset + 60_000]
                    for offset in range(0, len(item), 60_000)
                ]
        return item

    validate_secret_free(scan_view(value), file_name="hosted-generation.json")


def generation_prompt(
    request: HostedGenerationRequest | HostedSequentialGenerationRequest,
) -> bytes:
    """A single AST proposal, without a preselected candidate list or a future campaign."""
    base = (
        "Use the shared context originals included below; the same originals are mounted "
        "read-only in /projection for source verification. Produce exactly one JSON "
        "object conforming to the projected SafeQlibExpressionSpec schema. Propose one "
        "new expression AST within the design's operators, windows, grammar and node "
        "limit. Do not select from a candidate manifest. Do not use tools, execute code, "
        "retrieve new data, or claim validated evidence. Preserve this one response as "
        "your final message. No markdown fences or accompanying prose.\n"
        f"Hosted request: {request.content_hash}\n"
        f"Design: {request.design_hash}\n"
        f"Schema: {request.proposal_schema_hash}\n"
        f"Generation instruction: {request.generation_request.prompt}\n"
    ).encode()
    if isinstance(request, HostedSequentialGenerationRequest):
        base += (
            (
                "Sequential policy: " + request.policy.content_hash + "\n"
                "Attempt: " + request.attempt.content_hash + "\n"
                "Same-method static history: " + request.attempt.history.content_hash + "\n"
                "Prior proposals are unvalidated. Avoid structural duplicates in this method's "
                "history; do not use scientific feedback or infer quality from static admission.\n"
            ).encode()
            + request.attempt.history.canonical_bytes()
            + b"\n"
        )
    return base


class HostedGenerationManager:
    """Trusted management owner; callers provide an already persisted reservation.

    The evidence store and authenticated principal must come from management, never
    from response fields. No source hashes grant host access to management storage.
    """

    def __init__(
        self,
        root: Path,
        *,
        evidence: TrustedLauncherEvidenceStore,
        authenticated_principal: str,
        guard: KnownValueGuard,
    ) -> None:
        root = root.absolute()
        if any(root.is_relative_to(Path(prefix)) for prefix in ("/tmp", "/var/tmp")):
            raise ArtifactIntegrityError("hosted generation requires durable management storage")
        with opened_directory(root, create=True):
            pass
        if root.resolve() != root:
            raise ArtifactIntegrityError("hosted generation management root is not canonical")
        evidence_root = evidence.root.absolute()
        if (
            any(evidence_root.is_relative_to(Path(prefix)) for prefix in ("/tmp", "/var/tmp"))
            or evidence_root.resolve() != evidence_root
        ):
            raise ArtifactIntegrityError("hosted generation source storage must be durable")
        self.root, self.evidence = root, evidence
        self.principal, self.guard = authenticated_principal, guard

    def prepare(
        self,
        design: DiscoveryDesign,
        request: GenerationRequest,
        reservation: GenerationReservation,
        configuration: HostedLauncherConfiguration,
        profile: HostedDeploymentProfile,
        *,
        context_objects: Mapping[str, bytes],
        issued_at: datetime,
        expires_at: datetime,
        policy: SequentialGenerationPolicy | None = None,
        attempt: SequentialGenerationAttempt | None = None,
    ) -> HostedGenerationRequest | HostedSequentialGenerationRequest:
        if (
            request.method != "LLM"
            or request.design_hash != design.content_hash
            or request.input_hashes != design.context_hashes
            or request.max_attempts != design.evaluation_opportunities_per_method
            or reservation.request_hash != request.content_hash
            or request.configuration_hash != configuration.content_hash
            or configuration.content_hash != profile.model_configuration_hash
            or request.model_identifier != configuration.model
            or request.reasoning_effort != configuration.reasoning_effort
            or configuration.proposal_byte_cap > design.max_output_bytes_per_attempt
            or profile.extraction_rule_hash != sha256_bytes(EXTRACTION_RULE_BYTES)
            or configuration.extraction_rule != "codex-jsonl-single-final/v2"
            or set(context_objects) != set(design.context_hashes)
        ):
            raise ArtifactIntegrityError("hosted generation preparation bindings disagree")
        view = design.model_dump(mode="json")
        binding = dict(view["bindings"])
        binding["code_commit_identity"] = binding.pop("code_commit_hash")
        view["bindings"] = binding
        _scan_safe(view)
        _scan_safe(request.model_dump(mode="json"))
        if (policy is None) != (attempt is None):
            raise ArtifactIntegrityError("sequential preparation requires both policy and attempt")
        schema = generation_schema_bytes()
        objects = dict(context_objects)
        if policy is not None and attempt is not None:
            for contract in (policy, attempt, attempt.history):
                _scan_safe(contract.model_dump(mode="json"))
                objects[contract.content_hash] = contract.canonical_bytes()
        for contract in (design, request, reservation, configuration, profile):
            objects[contract.content_hash] = contract.canonical_bytes()
        objects[sha256_bytes(schema)] = schema
        if sum(map(len, objects.values())) > _PROJECTION_CAP:
            raise ArtifactIntegrityError("hosted generation projection exceeds its bound")
        for digest, data in objects.items():
            if len(data) > _OBJECT_CAP or sha256_bytes(data) != digest:
                raise ArtifactIntegrityError("hosted generation projection object differs")
            self.guard(data)
            if digest in context_objects:
                _scan_safe(data.decode("utf-8"))
        payload: dict[str, object] = dict(
            generation_request=request,
            reservation=reservation,
            design_hash=design.content_hash,
            configuration_hash=configuration.content_hash,
            deployment_profile_hash=profile.content_hash,
            proposal_schema_hash=sha256_bytes(schema),
            input_hashes=tuple(sorted(objects)),
            projection_object_hashes=tuple(sorted(objects)),
            max_response_bytes=configuration.proposal_byte_cap,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        if policy is not None and attempt is not None:
            payload.update(policy=policy, attempt=attempt)
            hosted = HostedSequentialGenerationRequest.model_validate(payload)
        else:
            hosted = HostedGenerationRequest.model_validate(payload)
        self.guard(hosted.canonical_bytes())
        prompt = generation_prompt(hosted)
        self.guard(prompt)
        with exclusive_directory_lock(self.root):
            directory = self.root / hosted.content_hash
            with opened_directory(directory, create=True):
                pass
            projection = directory / "projection"
            with opened_directory(projection, create=True):
                pass
            for digest, data in {**objects, hosted.content_hash: hosted.canonical_bytes()}.items():
                atomic_write_bytes(projection / digest, data)
            atomic_write_bytes(directory / "request.json", hosted.canonical_bytes())
            atomic_write_bytes(directory / "prompt.txt", prompt)
            atomic_write_bytes(
                directory / "status.json",
                canonical_json_bytes(
                    {
                        "profile": hosted.profile,
                        "qualification": "NOT_EVALUATED",
                        "status": "PREPARED_OFFLINE",
                        "request_hash": hosted.content_hash,
                        "reservation_hash": reservation.content_hash,
                        "real_model_calls": 0,
                    }
                ),
            )
        return hosted

    def verify_existing_capture(
        self,
        response: HostedGenerationResponse,
        *,
        request: HostedGenerationRequest | HostedSequentialGenerationRequest,
        configuration: HostedLauncherConfiguration,
        profile: HostedDeploymentProfile,
        launcher_record_hash: str,
        source_receipt: HostedGenerationSourceReceipt | None = None,
        persist: bool = True,
    ) -> HostedGenerationSourceReceipt:
        """Re-extract original captured bytes; emit no qualification or generation event."""
        record = parse_hosted_contract(
            self.evidence.read_bytes(launcher_record_hash, max_bytes=65_536),
            HostedLauncherRecord,
            max_bytes=65_536,
        )
        fact = parse_hosted_contract(
            self.evidence.read_bytes(record.projection_fact_hash, max_bytes=65_536),
            HostedGenerationProjectionFact,
            max_bytes=65_536,
        )
        projection = self.root / request.content_hash / "projection"
        inventory = install_inventory(projection)
        initial_objects = {
            request.design_hash,
            request.configuration_hash,
            request.proposal_schema_hash,
            *request.generation_request.input_hashes,
        }
        initial_inventory = HostedInstallInventory(
            files=tuple(item for item in inventory.files if item.relative_path in initial_objects)
        )
        if initial_inventory.content_hash != profile.projection_inventory_hash:
            raise ArtifactIntegrityError("hosted generation initial projection originals differ")
        from quantos.infrastructure.discovery_launcher import verify_generation_projection_fact

        design = DiscoveryDesign.model_validate_json(
            read_projection(projection, request.design_hash, max_bytes=_OBJECT_CAP)
        )
        verify_generation_projection_fact(
            fact,
            request=request,
            design=design,
            profile=profile,
            configuration=configuration,
            initial_inventory=initial_inventory,
            projection_root=projection,
            evidence=self.evidence,
        )
        expected = set(request.projection_object_hashes) | {request.content_hash}
        if {entry.relative_path for entry in inventory.files} != expected:
            raise ArtifactIntegrityError("hosted generation projection set differs")
        for digest in expected:
            read_projection(projection, digest, max_bytes=_OBJECT_CAP)
        hint = profile.mount_policy_hash == sha256_bytes(MOUNT_POLICY_BYTES)
        mount_data = self.evidence.read_bytes(record.isolation_observation_hash, max_bytes=65_536)
        mount = parse_hosted_contract(
            mount_data,
            HostedExecutableHintMountObservation if hint else HostedMountObservation,
            max_bytes=65_536,
        )
        if (
            response.request_hash != request.content_hash
            or response.design_hash != request.design_hash
            or response.reservation_hash != request.reservation.content_hash
            or response.host_observation.requested_configuration_hash != configuration.content_hash
            or len(response.proposal_json.encode("utf-8")) > request.max_response_bytes
            or configuration.content_hash != request.configuration_hash
            or request.generation_request.model_identifier != configuration.model
            or request.generation_request.reasoning_effort != configuration.reasoning_effort
            or not {
                request.configuration_hash,
                request.deployment_profile_hash,
                request.proposal_schema_hash,
            }.issubset(request.projection_object_hashes)
            or configuration.content_hash != profile.model_configuration_hash
            or profile.content_hash != request.deployment_profile_hash
            or profile.extraction_rule_hash != sha256_bytes(EXTRACTION_RULE_BYTES)
            or configuration.extraction_rule != "codex-jsonl-single-final/v2"
            or record.content_hash != launcher_record_hash
            or response.host_observation.external_evidence_hashes != (launcher_record_hash,)
            or record.request_hash != request.content_hash
            or record.outcome != "CAPTURED"
            or record.configuration_hash != configuration.content_hash
            or record.deployment_profile_hash != profile.content_hash
            or record.executable_hash != profile.cli_binary_hash
            or record.executable_version != profile.cli_version
            or record.prompt_hash != sha256_bytes(generation_prompt(request))
            or record.proposal_hash != response.proposal_hash
            or record.proposal_bytes != len(response.proposal_json.encode("utf-8"))
            or record.raw_output_hash is None
            or not record.raw_output_complete
            or record.started_at < request.issued_at
            or record.terminated_at > request.expires_at
            or fact.request_hash != request.content_hash
            or fact.reservation_hash != request.reservation.content_hash
            or fact.design_hash != request.design_hash
            or fact.host_instance != record.host_instance
            or fact.deployment_profile_hash != profile.content_hash
            or fact.initial_projection_inventory_hash != profile.projection_inventory_hash
            or fact.projection_inventory_hash != inventory.content_hash
            or record.projection_inventory_hash != inventory.content_hash
            or mount.request_hash != request.content_hash
            or mount.deployment_profile_hash != profile.content_hash
            or mount.projection_inventory_hash != inventory.content_hash
            or (
                isinstance(mount, HostedExecutableHintMountObservation)
                and mount.exe_hash != profile.cli_binary_hash
            )
            or profile.host_proc
            != ("FIXED_EXECUTABLE_HINT_READ_ONLY_TMPFS" if hint else "EMPTY_READ_ONLY_TMPFS")
        ):
            raise ArtifactIntegrityError("hosted generation original source bindings disagree")
        attempt = self.evidence.root / "generation-launches" / request.reservation.content_hash
        with opened_directory(attempt) as directory:
            prelaunch_bytes = read_regular_bytes_at(directory, "prelaunch.json", max_bytes=65_536)
            completion_bytes = read_regular_bytes_at(directory, "completion.json", max_bytes=65_536)
        prelaunch: object = json.loads(prelaunch_bytes)
        completion: object = json.loads(completion_bytes)
        if not isinstance(prelaunch, dict) or not isinstance(completion, dict):
            raise ArtifactIntegrityError("hosted generation launch originals are invalid")
        launch = cast(dict[str, object], prelaunch)
        ended = cast(dict[str, object], completion)
        accepted_hash = "e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec"
        self.evidence.read_bytes(accepted_hash, max_bytes=131_072)
        expected_launch = {
            "schema_version": "discovery-hosted-launch-attempt/v1",
            "qualification": "NOT_EVALUATED",
            "request_hash": request.content_hash,
            "reservation_hash": request.reservation.content_hash,
            "design_hash": design.content_hash,
            "projection_fact_hash": fact.content_hash,
            "projection_inventory_hash": inventory.content_hash,
            "deployment_profile_hash": profile.content_hash,
            "configuration_hash": configuration.content_hash,
            "accepted_component_record_hash": accepted_hash,
            "adopted_deployment_profile_hash": (
                "1677613786da6ac50b98f6520b8affb38548523f7fa4d66e1734975a1cfb8fbf"
            ),
            "adopted_scope": "RUNTIME_AND_ISOLATION_FACILITIES_ONLY",
            "successor_profile_differences": [
                "model_configuration_hash",
                "projection_inventory_hash",
            ],
            "old_business_qualification_adopted": False,
            "prompt_hash": sha256_bytes(generation_prompt(request)),
            "started_at": launch.get("started_at"),
        }
        expected_completion = {
            "schema_version": "discovery-hosted-launch-completion/v1",
            "prelaunch_hash": sha256_bytes(prelaunch_bytes),
            "launcher_record_hash": record.content_hash,
            "outcome": "CAPTURED",
            "reason": record.reason,
            "process_exit": record.exit_code,
            "terminated_at": record.terminated_at,
            "qualification": "NOT_EVALUATED",
        }
        start_value = launch.get("started_at")
        if not isinstance(start_value, str):
            raise ArtifactIntegrityError("hosted generation launch timestamp is invalid")
        start = datetime.fromisoformat(start_value)
        if (
            canonical_json_bytes(launch) != prelaunch_bytes
            or canonical_json_bytes(ended) != completion_bytes
            or launch != expected_launch
            or completion_bytes != canonical_json_bytes(expected_completion)
            or start.tzinfo is None
            or not request.issued_at <= start <= record.started_at
            or record.exit_code != 0
        ):
            raise ArtifactIntegrityError("hosted generation actual launch completion differs")
        output = self.evidence.read_bytes(
            record.raw_output_hash, max_bytes=configuration.output_byte_cap
        )
        proposal, model = extract_proposal(output, configuration, guard=self.guard)
        if (
            proposal != response.proposal_json.encode("utf-8")
            or model != record.actual_model_identifier
        ):
            raise ArtifactIntegrityError("hosted generation original proposal differs")
        observation = response.host_observation
        if any(
            value is not None
            for value in (
                observation.reported_permission_pass,
                observation.transcript_hash,
                observation.immutable_model_snapshot,
                observation.reported_usage.input_tokens,
                observation.reported_usage.output_tokens,
                observation.reported_usage.cost_microunits,
            )
        ):
            raise ArtifactIntegrityError(
                "hosted generation unavailable observations must stay unknown"
            )
        if (
            observation.reported_model_identifier is not None
            and observation.reported_model_identifier != model
        ) or (
            observation.reported_reasoning_effort is not None
            and observation.reported_reasoning_effort != configuration.reasoning_effort
        ):
            raise ArtifactIntegrityError("hosted generation reported identity differs")
        _scan_safe(response.proposal_json)
        # Only typed, validated usage counters bypass sensitive-key heuristics.
        # Original observation bytes and explicit unavailable reasons remain intact.
        observation_view = observation.model_dump(mode="json")
        usage = observation.reported_usage
        observation_view["reported_usage"] = {
            "counts": (usage.input_tokens, usage.output_tokens, usage.cost_microunits),
            "unavailable_reason": usage.unavailable_reason,
        }
        _scan_safe(observation_view)
        self.guard(response.canonical_bytes())
        receipt = HostedGenerationSourceReceipt(
            authenticated_principal=self.principal,
            request_hash=request.content_hash,
            response_hash=response.content_hash,
            reservation_hash=request.reservation.content_hash,
            launcher_record_hash=record.content_hash,
            projection_fact_hash=fact.content_hash,
            isolation_hash=mount.content_hash,
            launch_prelaunch_hash=sha256_bytes(prelaunch_bytes),
            launch_completion_hash=sha256_bytes(completion_bytes),
            design_hash=request.design_hash,
            proposal_hash=response.proposal_hash,
            configuration_hash=configuration.content_hash,
            deployment_profile_hash=profile.content_hash,
            recorded_at=source_receipt.recorded_at if source_receipt else datetime.now(UTC),
        )
        if source_receipt is not None and receipt != source_receipt:
            raise ArtifactIntegrityError("hosted generation retained source receipt differs")
        if persist:
            self.evidence.publish_bytes(response.canonical_bytes())
            self.evidence.publish_bytes(receipt.canonical_bytes())
        return receipt


def verify_generation_origin(
    origin: HostedGenerationOrigin | HostedSequentialGenerationOrigin,
) -> tuple[
    HostedGenerationRequest | HostedSequentialGenerationRequest,
    HostedGenerationResponse,
    HostedLauncherRecord,
]:
    """Re-read the trusted launcher originals; a captured proposal is still a proposal."""
    guard = KnownValueGuard(())
    manager_root, evidence_root = Path(origin.manager_root), Path(origin.evidence_root)
    for root in (manager_root, evidence_root):
        if (
            not root.is_absolute()
            or root.resolve(strict=True) != root
            or any(root.is_relative_to(Path(prefix)) for prefix in ("/tmp", "/var/tmp"))
        ):
            raise ArtifactIntegrityError("hosted generation origin is not durable and canonical")
        with opened_directory(root):
            pass
    evidence = TrustedLauncherEvidenceStore(evidence_root, guard)
    request = parse_generation_request(
        evidence.read_bytes(origin.request_hash, max_bytes=_OBJECT_CAP)
    )
    if isinstance(origin, HostedSequentialGenerationOrigin):
        from quantos.application.discovery_generation import GenerationStore

        store = GenerationStore(Path(origin.generation_root))
        if str(store.root) != origin.generation_root or not isinstance(
            request, HostedSequentialGenerationRequest
        ):
            raise ArtifactIntegrityError("sequential source authority/profile differs")
        attempt = store.read_attempt(request.generation_request, request.reservation)
        source = store.launch_source(request.generation_request, request.reservation)
        if (
            source is None
            or source.manager_root != origin.manager_root
            or source.evidence_root != origin.evidence_root
            or source.authenticated_principal != origin.authenticated_principal
            or store.sequential_policy() != request.policy
            or attempt != request.attempt
            or attempt.content_hash != origin.attempt_hash
        ):
            raise ArtifactIntegrityError("sequential Hosted source history originals differ")
    elif isinstance(request, HostedSequentialGenerationRequest):
        raise ArtifactIntegrityError("sequential Hosted source requires a sequential origin")
    response = parse_hosted_contract(
        evidence.read_bytes(origin.response_hash, max_bytes=_OBJECT_CAP),
        HostedGenerationResponse,
        max_bytes=_OBJECT_CAP,
    )
    receipt = parse_hosted_contract(
        evidence.read_bytes(origin.source_receipt_hash, max_bytes=65_536),
        HostedGenerationSourceReceipt,
        max_bytes=65_536,
    )
    configuration = parse_hosted_contract(
        evidence.read_bytes(origin.configuration_hash, max_bytes=65_536),
        HostedLauncherConfiguration,
        max_bytes=65_536,
    )
    profile = parse_hosted_contract(
        evidence.read_bytes(origin.deployment_profile_hash, max_bytes=65_536),
        HostedDeploymentProfile,
        max_bytes=65_536,
    )
    manager = HostedGenerationManager(
        manager_root,
        evidence=evidence,
        authenticated_principal=origin.authenticated_principal,
        guard=guard,
    )
    manager.verify_existing_capture(
        response,
        request=request,
        configuration=configuration,
        profile=profile,
        launcher_record_hash=receipt.launcher_record_hash,
        source_receipt=receipt,
        persist=False,
    )
    record = parse_hosted_contract(
        evidence.read_bytes(receipt.launcher_record_hash, max_bytes=65_536),
        HostedLauncherRecord,
        max_bytes=65_536,
    )
    return request, response, record


def parse_generation_request(
    data: bytes,
) -> HostedGenerationRequest | HostedSequentialGenerationRequest:
    """Only explicit supported versions are accepted; no fallback reinterpretation."""
    from quantos.contracts.hosted import strict_json_object

    value = strict_json_object(data, max_bytes=_OBJECT_CAP)
    version = value.get("schema_version")
    if version == "hosted-generation-request/v1":
        return parse_hosted_contract(data, HostedGenerationRequest, max_bytes=_OBJECT_CAP)
    if version == "hosted-sequential-generation-request/v2":
        return parse_hosted_contract(data, HostedSequentialGenerationRequest, max_bytes=_OBJECT_CAP)
    raise ArtifactIntegrityError("unsupported Hosted generation request schema")


def recover_generation_capture(
    generation_root: Path,
    request: GenerationRequest,
    reservation: GenerationReservation,
) -> GenerationResponse:
    """Complete a captured unfinished slot from actual originals without invoking a model."""
    from quantos.application.discovery_generation import GenerationStore
    from quantos.contracts.hosted import strict_json_object

    store = GenerationStore(generation_root)
    reservations, responses = store.inventory(request)
    existing = next((item for item in responses if item.reservation == reservation), None)
    if existing is not None:
        if existing.producer != "HOSTED_HANDOFF":
            raise ArtifactIntegrityError("a completed failure or import cannot be rewritten")
        return existing
    if not reservations or reservation != reservations[-1]:
        raise ArtifactIntegrityError("Hosted recovery requires the final unfinished slot")
    source = store.launch_source(request, reservation)
    if source is None or store.sequential_policy() is None:
        raise ArtifactIntegrityError("Hosted recovery needs retained sequential management sources")
    guard = KnownValueGuard(())
    evidence = TrustedLauncherEvidenceStore(Path(source.evidence_root), guard)
    attempt_root = evidence.root / "generation-launches" / reservation.content_hash
    with opened_directory(attempt_root) as directory:
        prelaunch = strict_json_object(
            read_regular_bytes_at(directory, "prelaunch.json", max_bytes=65_536), max_bytes=65_536
        )
        completion = strict_json_object(
            read_regular_bytes_at(directory, "completion.json", max_bytes=65_536), max_bytes=65_536
        )
    request_hash, record_hash = (
        prelaunch.get("request_hash"),
        completion.get("launcher_record_hash"),
    )
    if not isinstance(request_hash, str) or not isinstance(record_hash, str):
        raise ArtifactIntegrityError("captured launcher originals are unavailable")
    hosted = parse_generation_request(evidence.read_bytes(request_hash, max_bytes=_OBJECT_CAP))
    if (
        not isinstance(hosted, HostedSequentialGenerationRequest)
        or hosted.generation_request != request
        or hosted.reservation != reservation
        or hosted.policy != store.sequential_policy()
        or hosted.attempt != store.read_attempt(request, reservation)
    ):
        raise ArtifactIntegrityError("recovered request history differs from retained authority")
    record = parse_hosted_contract(
        evidence.read_bytes(record_hash, max_bytes=65_536), HostedLauncherRecord, max_bytes=65_536
    )
    configuration = parse_hosted_contract(
        evidence.read_bytes(hosted.configuration_hash, max_bytes=65_536),
        HostedLauncherConfiguration,
        max_bytes=65_536,
    )
    profile = parse_hosted_contract(
        evidence.read_bytes(hosted.deployment_profile_hash, max_bytes=65_536),
        HostedDeploymentProfile,
        max_bytes=65_536,
    )
    if (
        record.outcome != "CAPTURED"
        or record.raw_output_hash is None
        or not record.raw_output_complete
    ):
        raise ArtifactIntegrityError("no complete original model capture is available for recovery")
    proposal, _ = extract_proposal(
        evidence.read_bytes(record.raw_output_hash, max_bytes=configuration.output_byte_cap),
        configuration,
        guard=guard,
    )
    response = HostedGenerationResponse(
        request_hash=hosted.content_hash,
        design_hash=hosted.design_hash,
        reservation_hash=reservation.content_hash,
        proposal_json=proposal.decode("utf-8"),
        proposal_hash=sha256_bytes(proposal),
        host_observation=HostObservation(
            requested_configuration_hash=configuration.content_hash,
            reported_model_identifier=record.actual_model_identifier,
            reported_reasoning_effort=configuration.reasoning_effort,
            reported_usage=HostReportedUsage(unavailable_reason="HOST_INTERNAL_USAGE_UNAVAILABLE"),
            external_evidence_hashes=(record.content_hash,),
            unavailable_reasons=(
                "HOST_EFFECTIVE_POLICY_NOT_ATTESTED",
                "MODEL_IDENTIFIER_NOT_IMMUTABLE",
                "HOST_INTERNAL_USAGE_UNAVAILABLE",
                "HOST_TRANSCRIPT_UNAVAILABLE",
            ),
        ),
    )
    manager = HostedGenerationManager(
        Path(source.manager_root),
        evidence=evidence,
        authenticated_principal=source.authenticated_principal,
        guard=guard,
    )
    # Principal is management authority, never a host observation or provider field.
    receipt = manager.verify_existing_capture(
        response,
        request=hosted,
        configuration=configuration,
        profile=profile,
        launcher_record_hash=record.content_hash,
    )
    origin = HostedSequentialGenerationOrigin(
        manager_root=source.manager_root,
        evidence_root=source.evidence_root,
        authenticated_principal=manager.principal,
        request_hash=hosted.content_hash,
        response_hash=response.content_hash,
        source_receipt_hash=receipt.content_hash,
        configuration_hash=configuration.content_hash,
        deployment_profile_hash=profile.content_hash,
        generation_root=str(store.root),
        attempt_hash=hosted.attempt.content_hash,
    )
    return store.complete(
        request,
        reservation,
        proposal.decode("utf-8"),
        producer="HOSTED_HANDOFF",
        hosted_origin=origin,
        wall_seconds=(record.terminated_at - record.started_at).total_seconds(),
    )
