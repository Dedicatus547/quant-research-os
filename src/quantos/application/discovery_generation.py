"""Durable, bounded proposal capture without a provider or runtime invocation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, TypeVar, cast

from quantos.application.agent_harness import capture_from_agent_events, parse_agent_events
from quantos.application.discovery_baselines import generate_baseline
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
    regular_tree_files,
)
from quantos.contracts.agent import AgentRunManifestV3, AgentRunSpecV3, AgentUsage
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryBatch,
    DiscoveryCompositionDesign,
    DiscoveryDesignContract,
    DiscoveryDesignReader,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
    SequentialDiscoveryBatch,
    SequentialGenerationAttempt,
    SequentialLaunchObservation,
    SequentialLaunchSource,
    SequentialPolicyContract,
    SequentialPolicyReader,
)
from quantos.contracts.discovery_hosted import (
    HostedGenerationOrigin,
    HostedSequentialGenerationOrigin,
)
from quantos.contracts.harness import AgentEvent, AgentEventKind, HarnessExecutionRequest
from quantos.contracts.pit import SafeQlibExpressionSpec
from quantos.contracts.status import RunStatus
from quantos.security import SecretArtifactRejected, validate_secret_free

_Contract = TypeVar("_Contract", bound=CanonicalContract)
_FILE_CAP = 2_097_152
_CAPTURE_FAILURES = frozenset(
    {
        "CAPTURE_OUTPUT_LIMIT",
        "CAPTURE_SECRET_REJECTED",
        "CAPTURE_PROVENANCE_REJECTED",
    }
)


class _CaptureRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _CredentialRejected(ArtifactIntegrityError):
    pass


def _read(root: Path, name: str) -> bytes:
    path = confined_regular_file(root, name)
    with path.open("rb") as stream:
        data = stream.read(_FILE_CAP + 1)
    if len(data) > _FILE_CAP:
        raise ArtifactIntegrityError("generation record exceeds its bound")
    return data


def _contract(root: Path, name: str, kind: type[_Contract]) -> _Contract:
    data = _read(root, name)
    try:
        result = kind.model_validate_json(data)
        if result.canonical_bytes() != data:
            raise ValueError
    except ValueError:
        raise ArtifactIntegrityError("generation record is not a canonical contract") from None
    return result


def _design_contract(root: Path, name: str) -> DiscoveryDesignContract:
    data = _read(root, name)
    try:
        result = DiscoveryDesignReader.model_validate_json(data)
        if result.canonical_bytes() != data:
            raise ValueError
        return result
    except ValueError:
        raise ArtifactIntegrityError("invalid canonical discovery design") from None


def _policy_contract(root: Path, name: str) -> SequentialPolicyContract:
    data = _read(root, name)
    try:
        result = SequentialPolicyReader.model_validate_json(data)
        if result.canonical_bytes() != data:
            raise ValueError
        return result
    except ValueError:
        raise ArtifactIntegrityError("invalid canonical discovery policy") from None


def _safe(value: object) -> None:
    # Scanner exceptions expose classifications, never the rejected text.
    def prepare(item: object) -> object:
        if isinstance(item, dict):
            mapping = cast(dict[str, object], item)
            if mapping.get("schema_version") == "autonomous-execution-bindings/v1":
                from quantos.contracts.autonomous import AutonomousExecutionBindings

                binding = AutonomousExecutionBindings.model_validate(mapping)
                mapping = dict(mapping)
                del mapping["code_commit_hash"]
                mapping["code_commit_identity"] = binding.code_commit_hash
            if mapping.get("schema_version") == "agent-usage/v1":
                try:
                    usage = AgentUsage.model_validate(item)
                except ValueError:
                    raise ArtifactIntegrityError("generation usage metadata is invalid") from None
                return tuple(usage.model_dump(exclude={"schema_version"}).values())
            if mapping.get("schema_version") == "quantos-agent-event/v1":
                event = AgentEvent.model_validate(mapping)
                if event.kind is AgentEventKind.USAGE:
                    raw = event.payload.get("usage")
                    if not isinstance(raw, dict):
                        raise ArtifactIntegrityError("generation event usage metadata is invalid")
                    counters = cast(dict[str, object], raw)
                    if set(counters) != {
                        "input_tokens",
                        "output_tokens",
                        "cached_input_tokens",
                    } or any(
                        isinstance(value, bool) or not isinstance(value, int) or value < 0
                        for value in counters.values()
                    ):
                        raise ArtifactIntegrityError("generation event usage metadata is invalid")
                    mapping = dict(mapping)
                    payload = dict(event.payload)
                    payload["usage"] = tuple(counters[key] for key in sorted(counters))
                    mapping["payload"] = payload
            return {key: prepare(child) for key, child in mapping.items()}
        if isinstance(item, list):
            return [prepare(child) for child in cast(list[object], item)]
        return item

    validate_secret_free(prepare(value), file_name="discovery-generation.json")
    encoded = canonical_json_bytes(value)
    if any(
        secret and secret.encode("utf-8") in encoded
        for name, secret in os.environ.items()
        if name.startswith("TUSHARE_")
    ):
        raise _CredentialRejected("generation record contains a prohibited credential")


def _safe_envelope(envelope: dict[str, object]) -> None:
    # Scan canonical events individually rather than treating a long JSONL stream
    # as one opaque string. The stored original is never rewritten by this view.
    view = dict(envelope)
    raw = view.pop("normalized_transcript")
    if raw is not None:
        if not isinstance(raw, str):
            raise ArtifactIntegrityError("generation transcript metadata is invalid")
        events = parse_agent_events(raw.encode("utf-8"), max_bytes=_FILE_CAP)
        for event in events:
            _safe(event.model_dump(mode="json"))
    _safe(view)


class GenerationStore:
    """One global writer lock serializes attempts, completion, and freezing."""

    def __init__(self, root: Path):
        absolute = root.absolute()
        if any(part.is_symlink() for part in (absolute, *absolute.parents)):
            raise ArtifactIntegrityError("generation root must not contain a symbolic link")
        resolved = absolute.resolve()
        if any(
            resolved == base or base in resolved.parents
            for base in (Path("/tmp"), Path("/var/tmp"))
        ):
            raise ArtifactIntegrityError("generation authority requires durable storage")
        self.root = resolved

    def sequential_policy(self) -> SequentialPolicyContract | None:
        marker = self.root / "policy.json"
        if not marker.exists() and not marker.is_symlink():
            return None
        return _policy_contract(self.root, "policy.json")

    def save_sequential_policy(self, policy: SequentialPolicyContract) -> None:
        """Opt in before saving any requests; policy cannot be attached to old attempts."""
        _safe(policy.model_dump(mode="json"))
        with exclusive_directory_lock(self.root):
            self._writable()
            retained = self.sequential_policy()
            if retained is not None:
                if retained != policy:
                    raise ArtifactIntegrityError("sequential policy is immutable")
                return
            if regular_tree_files(self.root):
                raise ArtifactIntegrityError("sequential policy must precede all requests")
            atomic_write_bytes(self.root / "policy.json", policy.canonical_bytes())

    def _make_attempt(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
        reservations: tuple[GenerationReservation, ...],
        responses: tuple[GenerationResponse, ...],
    ) -> SequentialGenerationAttempt:
        from quantos.application.discovery_sequential import build_generation_history

        policy = self.sequential_policy()
        if policy is None:
            raise ArtifactIntegrityError("sequential policy original is missing")
        return SequentialGenerationAttempt(
            reservation=reservation,
            history=build_generation_history(
                self._load(request), request, policy, reservations, responses
            ),
        )

    def _verify_attempt(
        self,
        request: GenerationRequest,
        attempt: SequentialGenerationAttempt,
        reservations: tuple[GenerationReservation, ...],
        responses: tuple[GenerationResponse, ...],
    ) -> None:
        if self._make_attempt(request, attempt.reservation, reservations, responses) != attempt:
            raise ArtifactIntegrityError(
                "sequential history differs from its exact original prefix"
            )

    def read_attempt(
        self, request: GenerationRequest, reservation: GenerationReservation
    ) -> SequentialGenerationAttempt:
        """Rebuild only earlier raw originals, avoiding recursive runtime-source verification."""
        directory = self._directory(request)
        reservations: list[GenerationReservation] = []
        responses: list[GenerationResponse] = []
        for ordinal in range(1, reservation.ordinal + 1):
            attempt = _contract(
                directory, f"reservations/{ordinal:06d}.json", SequentialGenerationAttempt
            )
            self._verify_attempt(request, attempt, tuple(reservations), tuple(responses))
            if ordinal == reservation.ordinal:
                if attempt.reservation != reservation:
                    raise ArtifactIntegrityError("sequential reservation original differs")
                return attempt
            reservations.append(attempt.reservation)
            name = f"responses/{ordinal:06d}.json"
            if (directory / name).exists() or (directory / name).is_symlink():
                raw = _read(directory, name)
                envelope: object = json.loads(raw)
                if not isinstance(envelope, dict):
                    raise ArtifactIntegrityError("sequential response original is not canonical")
                fields = cast(dict[str, object], envelope)
                if canonical_json_bytes(fields) != raw:
                    raise ArtifactIntegrityError("sequential response original is not canonical")
                response = GenerationResponse.model_validate(fields.get("response"))
                if response.reservation != attempt.reservation:
                    raise ArtifactIntegrityError(
                        "sequential response binds a different reservation"
                    )
                responses.append(response)
        raise ArtifactIntegrityError("sequential reservation is unavailable")

    def save_launch_source(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
        source: SequentialLaunchSource,
    ) -> None:
        """Bind management originals before launch; absence of completion remains unknown."""
        with exclusive_directory_lock(self.root):
            self._writable()
            if self.sequential_policy() is None or request.method != "LLM":
                raise ArtifactIntegrityError("launch-source pointers require sequential LLM scope")
            reservations, responses = self._inventory(request)
            if (
                reservation not in reservations
                or reservation != reservations[-1]
                or any(item.reservation == reservation for item in responses)
            ):
                raise ArtifactIntegrityError(
                    "launch-source pointer requires the final unfinished slot"
                )
            self._verify_launch_source(source, request, reservation)
            _safe(source.model_dump(mode="json"))
            atomic_write_bytes(
                self._directory(request) / "sources" / f"{reservation.ordinal:06d}.json",
                source.canonical_bytes(),
            )

    def launch_source(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
    ) -> SequentialLaunchSource | None:
        self._load(request)
        name = f"sources/{reservation.ordinal:06d}.json"
        path = self._directory(request) / name
        if not path.exists() and not path.is_symlink():
            return None
        source = _contract(self._directory(request), name, SequentialLaunchSource)
        self._verify_launch_source(source, request, reservation)
        return source

    @staticmethod
    def _verify_launch_source(
        source: SequentialLaunchSource,
        request: GenerationRequest,
        reservation: GenerationReservation,
    ) -> None:
        if (
            source.request_hash != request.content_hash
            or source.reservation_hash != reservation.content_hash
        ):
            raise ArtifactIntegrityError("launch source reservation binding differs")
        for value in (source.manager_root, source.evidence_root, source.job_root):
            root = Path(value)
            if (
                not root.is_absolute()
                or root.resolve(strict=True) != root
                or any(root.is_relative_to(base) for base in (Path("/tmp"), Path("/var/tmp")))
            ):
                raise ArtifactIntegrityError(
                    "launch source original root is not durable and canonical"
                )
        retained = _contract(
            Path(source.job_root), "generation-reservation.json", GenerationReservation
        )
        if retained != reservation:
            raise ArtifactIntegrityError("launch source job reservation original differs")

    def _check_sealed(
        self,
        reservation: GenerationReservation,
        reservations: tuple[GenerationReservation, ...],
        responses: tuple[GenerationResponse, ...],
    ) -> None:
        if self.sequential_policy() is not None and (
            reservation.ordinal < len(reservations)
            and not any(item.reservation == reservation for item in responses)
        ):
            raise ArtifactIntegrityError(
                "successor history permanently sealed this unfinished slot"
            )

    @staticmethod
    def _observe_launch_source(
        source: SequentialLaunchSource,
        frozen: SequentialLaunchObservation | None = None,
    ) -> SequentialLaunchObservation:
        """Read bounded management metadata; later completions never rewrite frozen unknowns."""
        fields = (
            ("job_prelaunch_hash", Path(source.job_root), "prelaunch.json"),
            ("job_completion_hash", Path(source.job_root), "completion.json"),
            (
                "launch_prelaunch_hash",
                Path(source.evidence_root) / "generation-launches" / source.reservation_hash,
                "prelaunch.json",
            ),
            (
                "launch_completion_hash",
                Path(source.evidence_root) / "generation-launches" / source.reservation_hash,
                "completion.json",
            ),
        )
        observed: dict[str, object] = {}
        completion: dict[str, object] | None = None
        job_completion: dict[str, object] | None = None
        launch: dict[str, object] | None = None
        for key, root, name in fields:
            expected = None if frozen is None else getattr(frozen, key)
            path = root / name
            if frozen is not None and expected is None:
                observed[key] = None
                continue
            if not path.exists() and not path.is_symlink():
                if expected is not None:
                    raise ArtifactIntegrityError("frozen launch original is unavailable")
                observed[key] = None
                continue
            data = _read(root, name)
            value: object = json.loads(data)
            if not isinstance(value, dict):
                raise ArtifactIntegrityError("launch original must be canonical metadata")
            record = cast(dict[str, object], value)
            if canonical_json_bytes(record) != data:
                raise ArtifactIntegrityError("launch original is not canonical")
            digest = sha256_bytes(data)
            if expected is not None and expected != digest:
                raise ArtifactIntegrityError("frozen launch original identity changed")
            if key == "job_prelaunch_hash" and record.get("request_hash") != source.request_hash:
                raise ArtifactIntegrityError("job launch source base request differs")
            if key == "launch_prelaunch_hash":
                if record.get("reservation_hash") != source.reservation_hash:
                    raise ArtifactIntegrityError("launcher prelaunch reservation differs")
                launch = record
            if key == "launch_completion_hash":
                completion = record
            if key == "job_completion_hash":
                job_completion = record
            observed[key] = digest
        if job_completion is not None and job_completion.get("prelaunch_hash") != observed.get(
            "job_prelaunch_hash"
        ):
            raise ArtifactIntegrityError("job completion does not bind observed prelaunch")
        if completion is not None and completion.get("prelaunch_hash") != observed.get(
            "launch_prelaunch_hash"
        ):
            raise ArtifactIntegrityError("launcher completion does not bind observed prelaunch")
        if frozen is None:
            digest = None if completion is None else completion.get("launcher_record_hash")
        else:
            digest = frozen.launcher_record_hash
        if digest is not None:
            from quantos.contracts.hosted import parse_hosted_contract
            from quantos.contracts.hosted_deployment import HostedLauncherRecord
            from quantos.infrastructure.hosted_deployment import KnownValueGuard
            from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore

            if not isinstance(digest, str):
                raise ArtifactIntegrityError("launcher completion record identity is invalid")
            evidence = TrustedLauncherEvidenceStore(Path(source.evidence_root), KnownValueGuard(()))
            launcher_record = parse_hosted_contract(
                evidence.read_bytes(digest, max_bytes=65_536),
                HostedLauncherRecord,
                max_bytes=65_536,
            )
            if (
                launcher_record.content_hash != digest
                or launch is None
                or launcher_record.request_hash != launch.get("request_hash")
                or completion is None
                or completion.get("launcher_record_hash") != digest
            ):
                raise ArtifactIntegrityError(
                    "frozen launcher record differs from observed prelaunch"
                )
        if launch is not None:
            from quantos.application.discovery_hosted import parse_generation_request
            from quantos.contracts.discovery_hosted import HostedSequentialGenerationRequest
            from quantos.infrastructure.hosted_deployment import KnownValueGuard
            from quantos.infrastructure.hosted_launcher import TrustedLauncherEvidenceStore

            request_hash = launch.get("request_hash")
            if not isinstance(request_hash, str):
                raise ArtifactIntegrityError("launcher request original identity is invalid")
            evidence = TrustedLauncherEvidenceStore(Path(source.evidence_root), KnownValueGuard(()))
            request = parse_generation_request(
                evidence.read_bytes(request_hash, max_bytes=_FILE_CAP)
            )
            if (
                not isinstance(request, HostedSequentialGenerationRequest)
                or request.generation_request.content_hash != source.request_hash
                or request.reservation.content_hash != source.reservation_hash
            ):
                raise ArtifactIntegrityError("launcher source request originals differ")
        observed.update(
            source_hash=source.content_hash,
            reservation_hash=source.reservation_hash,
            launcher_record_hash=digest,
        )
        return SequentialLaunchObservation.model_validate(observed)

    def _sequential_batch(
        self,
        design: DiscoveryDesignContract,
        frozen: SequentialDiscoveryBatch | None = None,
    ) -> SequentialDiscoveryBatch:
        from quantos.application.discovery_admission import build_discovery_batch

        policy = self.sequential_policy()
        if policy is None or policy.design_hash != design.content_hash:
            raise ArtifactIntegrityError("sequential batch design/policy differs")
        requests = tuple(
            _contract(self.root, f"requests/{digest}/request.json", GenerationRequest)
            for digest in policy.request_hashes
        )
        if tuple(item.method for item in requests) != ("LLM", "RANDOM", "TEMPLATE"):
            raise ArtifactIntegrityError("policy base request order must be LLM/RANDOM/TEMPLATE")
        reservations: list[GenerationReservation] = []
        responses: list[GenerationResponse] = []
        attempts: list[SequentialGenerationAttempt] = []
        sources: list[SequentialLaunchSource] = []
        expected = {self.root / "policy.json"}
        expected_directories = {self.root / "requests"}
        for request in requests:
            self._bind(design, request)
            saved_reservations, saved_responses = self._inventory(request)
            reservations.extend(saved_reservations)
            responses.extend(saved_responses)
            attempts.extend(self.read_attempt(request, item) for item in saved_reservations)
            directory = self._directory(request)
            for item in saved_reservations:
                name = f"sources/{item.ordinal:06d}.json"
                if (directory / name).exists():
                    sources.append(_contract(directory, name, SequentialLaunchSource))
            expected.update(regular_tree_files(directory))
            expected_directories.add(directory)
            expected_directories.update(
                directory / name
                for name in ("reservations", "responses", "sources")
                if (directory / name).is_dir()
            )
        marker = self.root / "frozen.json"
        if marker.exists() or marker.is_symlink():
            expected.add(marker)
        if (
            set(regular_tree_files(self.root)) != expected
            or {path for path in self.root.rglob("*") if path.is_dir()} != expected_directories
        ):
            raise ArtifactIntegrityError("sequential authority inventory differs")
        batch = build_discovery_batch(design, requests, tuple(reservations), tuple(responses))
        by_hash = {item.reservation.content_hash: item for item in attempts}
        sorted_sources = tuple(sorted(sources, key=lambda item: item.reservation_hash))
        frozen_observations = (
            {}
            if frozen is None
            else {item.source_hash: item for item in frozen.launch_observations}
        )
        if frozen is not None and set(frozen_observations) != {
            item.content_hash for item in sorted_sources
        }:
            raise ArtifactIntegrityError("frozen launch source set differs")
        return SequentialDiscoveryBatch(
            policy=policy,
            batch=batch,
            attempts=tuple(by_hash[item.content_hash] for item in batch.reservations),
            launch_sources=sorted_sources,
            launch_observations=tuple(
                self._observe_launch_source(item, frozen_observations.get(item.content_hash))
                for item in sorted_sources
            ),
        )

    def _verify_sequential_frozen(self, batch: SequentialDiscoveryBatch) -> None:
        retained = _contract(self.root, "frozen.json", SequentialDiscoveryBatch)
        if retained != batch or self._sequential_batch(batch.batch.design, retained) != retained:
            raise ArtifactIntegrityError("frozen sequential histories differ from their originals")

    def _freeze_sequential(self, design: DiscoveryDesignContract) -> SequentialDiscoveryBatch:
        marker = self.root / "frozen.json"
        if marker.exists() or marker.is_symlink():
            retained = _contract(self.root, "frozen.json", SequentialDiscoveryBatch)
            if retained.batch.design != design:
                raise ArtifactIntegrityError("frozen sequential batch belongs to another design")
            self._verify_sequential_frozen(retained)
            return retained
        batch = self._sequential_batch(design)
        atomic_write_bytes(marker, batch.canonical_bytes())
        return batch

    def _writable(self) -> None:
        if (self.root / "frozen.json").exists() or (self.root / "frozen.json").is_symlink():
            raise ArtifactIntegrityError("generation store is frozen")

    def _directory(self, request: GenerationRequest) -> Path:
        return self.root / "requests" / request.content_hash

    @staticmethod
    def _bind(design: DiscoveryDesignContract, request: GenerationRequest) -> None:
        if (
            request.design_hash != design.content_hash
            or request.max_attempts != design.evaluation_opportunities_per_method
            or request.input_hashes != design.context_hashes
        ):
            raise ArtifactIntegrityError("generation request disagrees with the frozen design")

    def save_request(self, design: DiscoveryDesignContract, request: GenerationRequest) -> None:
        self._bind(design, request)
        policy = self.sequential_policy()
        if policy is not None and isinstance(design, DiscoveryCompositionDesign) != isinstance(
            policy, CompositionGenerationPolicy
        ):
            raise ArtifactIntegrityError("generation policy and design profile disagree")
        if policy is not None and (
            policy.design_hash != design.content_hash
            or request.content_hash not in policy.request_hashes
            or request.max_attempts != policy.max_attempts_per_method
            or (request.method != "LLM" and request.seed != policy.random_seed)
        ):
            raise ArtifactIntegrityError("request differs from the sequential base policy")
        _safe(design.model_dump(mode="json"))
        _safe(request.model_dump(mode="json"))
        with exclusive_directory_lock(self.root):
            self._writable()
            directory = self._directory(request)
            if directory.exists():
                regular_tree_files(directory)
            elif (self.root / "requests").is_symlink():
                raise ArtifactIntegrityError("generation requests root is unsafe")
            atomic_write_bytes(directory / "design.json", design.canonical_bytes())
            atomic_write_bytes(directory / "request.json", request.canonical_bytes())

    def _load(self, request: GenerationRequest) -> DiscoveryDesignContract:
        directory = self._directory(request)
        retained = _contract(
            self.root, f"requests/{request.content_hash}/request.json", GenerationRequest
        )
        if retained != request:
            raise ArtifactIntegrityError("generation request identity mismatch")
        design = _design_contract(directory, "design.json")
        self._bind(design, request)
        policy = self.sequential_policy()
        if policy is not None and isinstance(design, DiscoveryCompositionDesign) != isinstance(
            policy, CompositionGenerationPolicy
        ):
            raise ArtifactIntegrityError("generation policy and design profile disagree")
        if policy is not None and (
            policy.design_hash != design.content_hash
            or request.content_hash not in policy.request_hashes
            or request.max_attempts != policy.max_attempts_per_method
            or (request.method != "LLM" and request.seed != policy.random_seed)
        ):
            raise ArtifactIntegrityError("request differs from the sequential base policy")
        _safe(design.model_dump(mode="json"))
        _safe(request.model_dump(mode="json"))
        return design

    def _agent_binding(
        self,
        design: DiscoveryDesignContract,
        request: GenerationRequest,
        response: GenerationResponse,
        manifest: AgentRunManifestV3 | None,
        spec: AgentRunSpecV3 | None,
        normalized_transcript: bytes | None,
        execution_request: HarnessExecutionRequest | None,
        model_configuration: bytes | None,
        hosted_origin: HostedGenerationOrigin | HostedSequentialGenerationOrigin | None = None,
    ) -> None:
        """Bind captured SDK originals; this does not grant Hosted qualification."""
        if response.producer != "HOSTED_HANDOFF" and hosted_origin is not None:
            raise ArtifactIntegrityError("non-Hosted capture cannot claim Hosted originals")
        if response.producer == "SDK_CAPTURE":
            if self.sequential_policy() is not None:
                raise ArtifactIntegrityError("sequential SDK captures do not bind Hosted history")
            sources = {request.content_hash, request.design_hash, response.reservation.content_hash}
            if (
                request.method != "LLM"
                or manifest is None
                or spec is None
                or normalized_transcript is None
                or execution_request is None
                or model_configuration is None
                or manifest.content_hash != response.agent_run_hash
                or manifest.run_spec_hash != spec.content_hash
                or spec.requested_model_configuration_hash != request.configuration_hash
                or not sources.issubset(manifest.input_hashes)
                or not sources.issubset(spec.input_artifact_hashes)
            ):
                raise ArtifactIntegrityError("generation AgentRun provenance does not match")
            if (
                execution_request.max_attempts != 1
                or len(manifest.attempts) != 1
                or execution_request.run_id != spec.run_id
                or execution_request.model != request.model_identifier
                or execution_request.reasoning_effort != request.reasoning_effort
                or execution_request.prompt != request.prompt
                or manifest.requested_policy_hash != execution_request.runtime_policy.content_hash
                or spec.requested_runtime_policy_hash
                != execution_request.runtime_policy.content_hash
                or spec.retry_budget_hash
                != sha256_bytes(
                    canonical_json_bytes(
                        {
                            "max_attempts": execution_request.max_attempts,
                            "retry_backoff_milliseconds": (
                                execution_request.retry_backoff_milliseconds
                            ),
                            "total_timeout_seconds": execution_request.total_timeout_seconds,
                        }
                    )
                )
                or spec.transcript_policy_hash
                != sha256_bytes(
                    canonical_json_bytes(
                        {
                            "max_bytes": execution_request.max_transcript_bytes,
                            "retain": True,
                        }
                    )
                )
                or sha256_bytes(model_configuration) != request.configuration_hash
            ):
                raise ArtifactIntegrityError("generation SDK request differs from frozen inputs")
            configuration: object = json.loads(model_configuration)
            if not isinstance(configuration, dict):
                raise ArtifactIntegrityError("generation model configuration is invalid")
            fields = cast(dict[str, object], configuration)
            if (
                canonical_json_bytes(fields) != model_configuration
                or fields.get("model_identifier") != request.model_identifier
                or fields.get("model_reasoning_effort") != request.reasoning_effort
            ):
                raise ArtifactIntegrityError("generation model configuration differs")
            events = parse_agent_events(
                normalized_transcript,
                max_bytes=min(_FILE_CAP, execution_request.max_transcript_bytes),
            )
            capture = capture_from_agent_events(
                events, max_bytes=min(_FILE_CAP, execution_request.max_transcript_bytes)
            )
            attempt = manifest.attempts[0]
            usage = AgentUsage(
                input_tokens=capture.usage.get("input_tokens", 0),
                output_tokens=capture.usage.get("output_tokens", 0),
                cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
                tool_calls=len(capture.tool_calls),
                retry_count=0,
            )
            if (
                capture.attempt_index != 1
                or capture.transcript != normalized_transcript
                or capture.transcript_hash != manifest.normalized_transcript_hash
                or capture.transcript_hash != attempt.event_stream_hash
                or usage != attempt.usage
                or usage != manifest.aggregate_usage
                or (
                    response.usage_input_units is not None
                    and (
                        "input_tokens" not in capture.usage
                        or response.usage_input_units != usage.input_tokens
                    )
                )
                or (
                    response.usage_output_units is not None
                    and (
                        "output_tokens" not in capture.usage
                        or response.usage_output_units != usage.output_tokens
                    )
                )
            ):
                raise ArtifactIntegrityError("generation transcript or usage differs from AgentRun")
            message = capture.agent_messages[-1] if capture.agent_messages else ""
            if response.text != message:
                raise ArtifactIntegrityError("generation text differs from captured final message")
            if manifest.run_status is RunStatus.SUCCEEDED:
                expression = SafeQlibExpressionSpec.model_validate(json.loads(response.text))
                if (
                    not capture.turn_started
                    or not capture.turn_completed
                    or capture.turn_failed
                    or response.failure_code is not None
                    or manifest.output_proposal_hashes != (expression.content_hash,)
                ):
                    raise ArtifactIntegrityError(
                        "generation output is not the captured Safe DSL proposal"
                    )
            elif (
                response.failure_code != manifest.failure_reason_code
                or manifest.output_proposal_hashes
            ):
                raise ArtifactIntegrityError("generation failure differs from captured AgentRun")
        elif response.producer == "HOSTED_HANDOFF":
            from quantos.application.discovery_hosted import verify_generation_origin

            if hosted_origin is None or any(
                value is not None
                for value in (
                    manifest,
                    spec,
                    normalized_transcript,
                    execution_request,
                    model_configuration,
                    response.agent_run_hash,
                )
            ):
                raise ArtifactIntegrityError(
                    "Hosted capture requires independent launcher originals"
                )
            hosted_request, hosted_response, record = verify_generation_origin(hosted_origin)
            policy = self.sequential_policy()
            if policy is not None:
                from quantos.contracts.discovery_hosted import HostedSequentialGenerationRequest

                source = _contract(
                    self._directory(request),
                    f"sources/{response.reservation.ordinal:06d}.json",
                    SequentialLaunchSource,
                )
                if (
                    source.manager_root != hosted_origin.manager_root
                    or source.evidence_root != hosted_origin.evidence_root
                    or source.authenticated_principal != hosted_origin.authenticated_principal
                    or not isinstance(hosted_request, HostedSequentialGenerationRequest)
                    or not isinstance(hosted_origin, HostedSequentialGenerationOrigin)
                    or hosted_origin.generation_root != str(self.root)
                    or hosted_request.policy != policy
                    or hosted_request.attempt != self.read_attempt(request, response.reservation)
                ):
                    raise ArtifactIntegrityError(
                        "Hosted source does not bind retained sequential history"
                    )
            elif isinstance(hosted_origin, HostedSequentialGenerationOrigin):
                raise ArtifactIntegrityError("legacy store cannot claim sequential provenance")
            if (
                hosted_request.generation_request != request
                or hosted_request.design_hash != design.content_hash
                or hosted_request.reservation != response.reservation
                or response.text != hosted_response.proposal_json
                or response.failure_code is not None
                or response.usage_input_units is not None
                or response.usage_output_units is not None
                or response.monetary_cost is not None
                or (
                    response.wall_seconds is not None
                    and response.wall_seconds
                    != (record.terminated_at - record.started_at).total_seconds()
                )
            ):
                raise ArtifactIntegrityError(
                    "Hosted capture differs from its actual reserved source"
                )
        else:
            if any(
                value is not None
                for value in (
                    manifest,
                    spec,
                    normalized_transcript,
                    execution_request,
                    model_configuration,
                    response.agent_run_hash,
                )
            ):
                raise ArtifactIntegrityError(
                    "non-runtime generation cannot claim AgentRun provenance"
                )
            if response.producer == "BASELINE":
                policy = self.sequential_policy()
                if policy is None:
                    proposals = generate_baseline(design, request)
                else:
                    from quantos.application.discovery_sequential import sequential_baseline

                    proposals = sequential_baseline(design, request, policy)
                expected = proposals[response.reservation.ordinal - 1]
                if response.failure_code is not None or response.text != expected:
                    raise ArtifactIntegrityError(
                        "baseline output differs from the frozen seed and ordinal"
                    )
            elif response.producer == "CAPTURE_REJECTED" and (
                response.text
                or response.failure_code not in _CAPTURE_FAILURES
                or any(
                    value is not None
                    for value in (
                        response.wall_seconds,
                        response.usage_input_units,
                        response.usage_output_units,
                        response.monetary_cost,
                    )
                )
            ):
                raise ArtifactIntegrityError(
                    "rejected capture must retain only a safe classification"
                )

    def _inventory(
        self, request: GenerationRequest
    ) -> tuple[tuple[GenerationReservation, ...], tuple[GenerationResponse, ...]]:
        design = self._load(request)
        directory = self._directory(request)
        files = {path.relative_to(directory).as_posix() for path in regular_tree_files(directory)}
        if any(
            path.is_dir()
            and path.relative_to(directory).as_posix()
            not in (
                {"reservations", "responses"}
                if self.sequential_policy() is None
                else {"reservations", "responses", "sources"}
            )
            for path in directory.rglob("*")
        ):
            raise ArtifactIntegrityError("generation directory set is invalid")
        expected = {"request.json", "design.json"}
        reservations: list[GenerationReservation] = []
        responses: list[GenerationResponse] = []
        response_hashes: set[str] = set()
        for ordinal in range(1, request.max_attempts + 1):
            name = f"reservations/{ordinal:06d}.json"
            if name not in files:
                break
            expected.add(name)
            policy = self.sequential_policy()
            if policy is None:
                reservation = _contract(directory, name, GenerationReservation)
            else:
                attempt = _contract(directory, name, SequentialGenerationAttempt)
                reservation = attempt.reservation
                self._verify_attempt(request, attempt, tuple(reservations), tuple(responses))
            if (
                reservation.request_hash != request.content_hash
                or reservation.ordinal != ordinal
                or (
                    reservation.revision_of is not None
                    and reservation.revision_of not in response_hashes
                )
            ):
                raise ArtifactIntegrityError("generation reservation identity mismatch")
            reservations.append(reservation)
            source_name = f"sources/{ordinal:06d}.json"
            if source_name in files:
                if policy is None or request.method != "LLM":
                    raise ArtifactIntegrityError("launch source is outside sequential LLM scope")
                expected.add(source_name)
                self._verify_launch_source(
                    _contract(directory, source_name, SequentialLaunchSource), request, reservation
                )
            completion = f"responses/{ordinal:06d}.json"
            if completion not in files:
                continue
            expected.add(completion)
            data = _read(directory, completion)
            try:
                value: object = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError
                envelope = cast(dict[str, object], value)
                expected_keys = {
                    "response",
                    "agent_run",
                    "agent_run_spec",
                    "normalized_transcript",
                    "execution_request",
                    "requested_model_configuration",
                }
                if "hosted_origin" in envelope:
                    expected_keys.add("hosted_origin")
                if set(envelope) != expected_keys:
                    raise ValueError
                if canonical_json_bytes(envelope) != data:
                    raise ValueError
                response = GenerationResponse.model_validate(envelope["response"])
                if response.canonical_bytes() != canonical_json_bytes(envelope["response"]):
                    raise ValueError
                manifest = (
                    AgentRunManifestV3.model_validate(envelope["agent_run"])
                    if envelope["agent_run"] is not None
                    else None
                )
                spec = (
                    AgentRunSpecV3.model_validate(envelope["agent_run_spec"])
                    if envelope["agent_run_spec"] is not None
                    else None
                )
                raw_transcript = envelope["normalized_transcript"]
                if raw_transcript is not None and not isinstance(raw_transcript, str):
                    raise ValueError
                transcript = None if raw_transcript is None else raw_transcript.encode("utf-8")
                execution_request = (
                    HarnessExecutionRequest.model_validate(envelope["execution_request"])
                    if envelope["execution_request"] is not None
                    else None
                )
                configuration = (
                    canonical_json_bytes(envelope["requested_model_configuration"])
                    if envelope["requested_model_configuration"] is not None
                    else None
                )
                hosted_origin = (
                    (
                        HostedSequentialGenerationOrigin
                        if isinstance(envelope["hosted_origin"], dict)
                        and cast(dict[str, object], envelope["hosted_origin"]).get("schema_version")
                        == "hosted-sequential-generation-origin/v2"
                        else HostedGenerationOrigin
                    ).model_validate(envelope["hosted_origin"])
                    if envelope.get("hosted_origin") is not None
                    else None
                )
                if (
                    (
                        manifest is not None
                        and manifest.canonical_bytes()
                        != canonical_json_bytes(envelope["agent_run"])
                    )
                    or (
                        spec is not None
                        and spec.canonical_bytes()
                        != canonical_json_bytes(envelope["agent_run_spec"])
                    )
                    or (
                        execution_request is not None
                        and execution_request.canonical_bytes()
                        != canonical_json_bytes(envelope["execution_request"])
                    )
                ):
                    raise ValueError
            except (ValueError, TypeError):
                raise ArtifactIntegrityError("generation completion is invalid") from None
            if (
                response.reservation != reservation
                or len(response.text.encode("utf-8")) > design.max_output_bytes_per_attempt
            ):
                raise ArtifactIntegrityError("generation completion binding or size mismatch")
            self._agent_binding(
                design,
                request,
                response,
                manifest,
                spec,
                transcript,
                execution_request,
                configuration,
                hosted_origin,
            )
            _safe_envelope(envelope)
            responses.append(response)
            response_hashes.add(response.content_hash)
        if expected != files:
            raise ArtifactIntegrityError("generation file set or attempt ordering is invalid")
        return tuple(reservations), tuple(responses)

    def inventory(
        self, request: GenerationRequest
    ) -> tuple[tuple[GenerationReservation, ...], tuple[GenerationResponse, ...]]:
        with exclusive_directory_lock(self.root):
            return self._inventory(request)

    def reserve(
        self, request: GenerationRequest, revision_of: str | None = None
    ) -> GenerationReservation:
        with exclusive_directory_lock(self.root):
            self._writable()
            reservations, responses = self._inventory(request)
            if len(reservations) >= request.max_attempts:
                raise ArtifactIntegrityError("generation attempt budget exhausted")
            if revision_of is not None and revision_of not in {
                item.content_hash for item in responses
            }:
                raise ArtifactIntegrityError(
                    "revision must reference an existing response of this request"
                )
            reservation = GenerationReservation(
                request_hash=request.content_hash,
                ordinal=len(reservations) + 1,
                revision_of=revision_of,
            )
            atomic_write_bytes(
                self._directory(request) / "reservations" / f"{reservation.ordinal:06d}.json",
                (
                    reservation.canonical_bytes()
                    if self.sequential_policy() is None
                    else self._make_attempt(
                        request, reservation, reservations, responses
                    ).canonical_bytes()
                ),
            )
            return reservation

    def complete(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
        text: str,
        *,
        producer: Literal["BASELINE", "HOSTED_HANDOFF", "OFFLINE_IMPORT", "SDK_CAPTURE"],
        agent_run_hash: str | None = None,
        agent_run: AgentRunManifestV3 | None = None,
        agent_run_spec: AgentRunSpecV3 | None = None,
        normalized_transcript: bytes | None = None,
        execution_request: HarnessExecutionRequest | None = None,
        model_configuration: bytes | None = None,
        hosted_origin: HostedGenerationOrigin | HostedSequentialGenerationOrigin | None = None,
        wall_seconds: float | None = None,
        usage_input_units: int | None = None,
        usage_output_units: int | None = None,
        monetary_cost: float | None = None,
        failure_code: str | None = None,
    ) -> GenerationResponse:
        with exclusive_directory_lock(self.root):
            self._writable()
            design = self._load(request)
            reservations, completions = self._inventory(request)
            if reservation not in reservations:
                raise ArtifactIntegrityError(
                    "generation completion requires a retained reservation"
                )
            self._check_sealed(reservation, reservations, completions)
            if self.sequential_policy() is not None and producer == "SDK_CAPTURE":
                raise ArtifactIntegrityError(
                    "sequential runtime capture requires the Hosted history path"
                )
            try:
                if len(text.encode("utf-8")) > design.max_output_bytes_per_attempt or (
                    normalized_transcript is not None and len(normalized_transcript) > _FILE_CAP
                ):
                    raise _CaptureRejected("CAPTURE_OUTPUT_LIMIT")
                _safe(text)
                response = GenerationResponse(
                    reservation=reservation,
                    text=text,
                    producer=producer,
                    agent_run_hash=agent_run_hash,
                    wall_seconds=wall_seconds,
                    usage_input_units=usage_input_units,
                    usage_output_units=usage_output_units,
                    monetary_cost=monetary_cost,
                    failure_code=failure_code,
                )
                if response.text != text:
                    raise ArtifactIntegrityError("generation capture must preserve response bytes")
                envelope: dict[str, object] = {
                    "response": response.model_dump(mode="json"),
                    "agent_run": agent_run.model_dump(mode="json")
                    if agent_run is not None
                    else None,
                    "agent_run_spec": agent_run_spec.model_dump(mode="json")
                    if agent_run_spec is not None
                    else None,
                    "normalized_transcript": normalized_transcript.decode("utf-8")
                    if normalized_transcript is not None
                    else None,
                    "execution_request": execution_request.model_dump(mode="json")
                    if execution_request is not None
                    else None,
                    "requested_model_configuration": json.loads(model_configuration)
                    if model_configuration is not None
                    else None,
                }
                if hosted_origin is not None:
                    envelope["hosted_origin"] = hosted_origin.model_dump(mode="json")
                _safe_envelope(envelope)
                self._agent_binding(
                    design,
                    request,
                    response,
                    agent_run,
                    agent_run_spec,
                    normalized_transcript,
                    execution_request,
                    model_configuration,
                    hosted_origin,
                )
                encoded = canonical_json_bytes(envelope)
                if len(encoded) > _FILE_CAP:
                    raise _CaptureRejected("CAPTURE_OUTPUT_LIMIT")
            except (SecretArtifactRejected, _CredentialRejected):
                return self._reject_capture(
                    request, reservation, completions, "CAPTURE_SECRET_REJECTED"
                )
            except _CaptureRejected as error:
                return self._reject_capture(request, reservation, completions, error.code)
            except (ValueError, TypeError, RecursionError, ArtifactIntegrityError, OSError):
                return self._reject_capture(
                    request, reservation, completions, "CAPTURE_PROVENANCE_REJECTED"
                )
            atomic_write_bytes(
                self._directory(request) / "responses" / f"{reservation.ordinal:06d}.json",
                encoded,
            )
            return response

    def reject_capture(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
        code: Literal[
            "CAPTURE_OUTPUT_LIMIT", "CAPTURE_SECRET_REJECTED", "CAPTURE_PROVENANCE_REJECTED"
        ],
    ) -> GenerationResponse:
        """Retain a bounded input-read rejection without retaining rejected bytes."""
        with exclusive_directory_lock(self.root):
            self._writable()
            reservations, completions = self._inventory(request)
            if reservation not in reservations:
                raise ArtifactIntegrityError("capture rejection requires a retained reservation")
            self._check_sealed(reservation, reservations, completions)
            return self._reject_capture(request, reservation, completions, code)

    def _reject_capture(
        self,
        request: GenerationRequest,
        reservation: GenerationReservation,
        completions: tuple[GenerationResponse, ...],
        code: str,
    ) -> GenerationResponse:
        # The parent already holds the global writer lock. Never persist the
        # rejected input, its digest, or an exception; costs remain unavailable.
        response = GenerationResponse(
            reservation=reservation,
            text="",
            producer="CAPTURE_REJECTED",
            failure_code=code,
        )
        existing = next((item for item in completions if item.reservation == reservation), None)
        if existing is not None and existing != response:
            raise ArtifactIntegrityError("generation reservation is already completed")
        envelope: dict[str, object] = {
            "response": response.model_dump(mode="json"),
            "agent_run": None,
            "agent_run_spec": None,
            "normalized_transcript": None,
            "execution_request": None,
            "requested_model_configuration": None,
        }
        _safe_envelope(envelope)
        atomic_write_bytes(
            self._directory(request) / "responses" / f"{reservation.ordinal:06d}.json",
            canonical_json_bytes(envelope),
        )
        return response

    def verify_frozen(self, batch: DiscoveryBatch | SequentialDiscoveryBatch) -> None:
        """Read original producer materials and check the entire frozen denominator."""
        if not self.root.is_dir():
            raise ArtifactIntegrityError("frozen generation originals are unavailable")
        with exclusive_directory_lock(self.root):
            if self.sequential_policy() is not None:
                if not isinstance(batch, SequentialDiscoveryBatch):
                    raise ArtifactIntegrityError("sequential freeze requires the successor wrapper")
                self._verify_sequential_frozen(batch)
            else:
                if isinstance(batch, SequentialDiscoveryBatch):
                    raise ArtifactIntegrityError("legacy freeze cannot accept a sequential wrapper")
                self._verify_frozen_unlocked(batch)

    def _verify_frozen_unlocked(self, batch: DiscoveryBatch) -> None:
        from quantos.application.discovery_admission import build_discovery_batch

        retained = _contract(self.root, "frozen.json", DiscoveryBatch)
        if retained != batch:
            raise ArtifactIntegrityError("frozen generation bytes differ from supplied batch")
        reservations: list[GenerationReservation] = []
        responses: list[GenerationResponse] = []
        expected = {self.root / "frozen.json"}
        for request in batch.requests:
            saved_reservations, saved_responses = self._inventory(request)
            reservations.extend(saved_reservations)
            responses.extend(saved_responses)
            expected.update(regular_tree_files(self._directory(request)))
        if (
            set(regular_tree_files(self.root)) != expected
            or build_discovery_batch(
                batch.design, batch.requests, tuple(reservations), tuple(responses)
            )
            != batch
        ):
            raise ArtifactIntegrityError("frozen generation inventory or producer binding differs")

    def freeze(self, design: DiscoveryDesignContract) -> DiscoveryBatch | SequentialDiscoveryBatch:
        from quantos.application.discovery_admission import build_discovery_batch

        with exclusive_directory_lock(self.root):
            if self.sequential_policy() is not None:
                return self._freeze_sequential(design)
            marker = self.root / "frozen.json"
            if marker.exists() or marker.is_symlink():
                batch = _contract(self.root, "frozen.json", DiscoveryBatch)
                if batch.design != design:
                    raise ArtifactIntegrityError("frozen batch belongs to another design")
                self._verify_frozen_unlocked(batch)
                return batch
            request_root = self.root / "requests"
            request_files = [
                path for path in regular_tree_files(request_root) if path.name == "request.json"
            ]
            requests = tuple(
                sorted(
                    (
                        _contract(
                            request_root,
                            path.relative_to(request_root).as_posix(),
                            GenerationRequest,
                        )
                        for path in request_files
                    ),
                    key=lambda item: item.method,
                )
            )
            if tuple(item.method for item in requests) != ("LLM", "RANDOM", "TEMPLATE"):
                raise ArtifactIntegrityError("freeze requires exactly three comparison methods")
            expected: set[Path] = set()
            reservations: list[GenerationReservation] = []
            responses: list[GenerationResponse] = []
            for request in requests:
                self._bind(design, request)
                retained_reservations, retained_responses = self._inventory(request)
                expected.update(regular_tree_files(self._directory(request)))
                reservations.extend(retained_reservations)
                responses.extend(retained_responses)
            if set(regular_tree_files(self.root)) != expected:
                raise ArtifactIntegrityError("generation root contains unexpected records")
            expected_directories = {request_root}
            for request in requests:
                directory = self._directory(request)
                expected_directories.add(directory)
                expected_directories.update(
                    directory / name
                    for name in ("reservations", "responses")
                    if (directory / name).is_dir()
                )
            if {path for path in self.root.rglob("*") if path.is_dir()} != expected_directories:
                raise ArtifactIntegrityError("generation root contains unexpected directories")
            batch = build_discovery_batch(design, requests, tuple(reservations), tuple(responses))
            atomic_write_bytes(marker, batch.canonical_bytes())
            return batch
