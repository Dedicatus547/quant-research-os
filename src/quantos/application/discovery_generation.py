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
    DiscoveryBatch,
    DiscoveryDesign,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
)
from quantos.contracts.discovery_hosted import HostedGenerationOrigin
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

    def _writable(self) -> None:
        if (self.root / "frozen.json").exists() or (self.root / "frozen.json").is_symlink():
            raise ArtifactIntegrityError("generation store is frozen")

    def _directory(self, request: GenerationRequest) -> Path:
        return self.root / "requests" / request.content_hash

    @staticmethod
    def _bind(design: DiscoveryDesign, request: GenerationRequest) -> None:
        if (
            request.design_hash != design.content_hash
            or request.max_attempts != design.evaluation_opportunities_per_method
            or request.input_hashes != design.context_hashes
        ):
            raise ArtifactIntegrityError("generation request disagrees with the frozen design")

    def save_request(self, design: DiscoveryDesign, request: GenerationRequest) -> None:
        self._bind(design, request)
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

    def _load(self, request: GenerationRequest) -> DiscoveryDesign:
        directory = self._directory(request)
        retained = _contract(
            self.root, f"requests/{request.content_hash}/request.json", GenerationRequest
        )
        if retained != request:
            raise ArtifactIntegrityError("generation request identity mismatch")
        design = _contract(directory, "design.json", DiscoveryDesign)
        self._bind(design, request)
        _safe(design.model_dump(mode="json"))
        _safe(request.model_dump(mode="json"))
        return design

    @staticmethod
    def _agent_binding(
        design: DiscoveryDesign,
        request: GenerationRequest,
        response: GenerationResponse,
        manifest: AgentRunManifestV3 | None,
        spec: AgentRunSpecV3 | None,
        normalized_transcript: bytes | None,
        execution_request: HarnessExecutionRequest | None,
        model_configuration: bytes | None,
        hosted_origin: HostedGenerationOrigin | None = None,
    ) -> None:
        """Bind captured SDK originals; this does not grant Hosted qualification."""
        if response.producer != "HOSTED_HANDOFF" and hosted_origin is not None:
            raise ArtifactIntegrityError("non-Hosted capture cannot claim Hosted originals")
        if response.producer == "SDK_CAPTURE":
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
                expected = generate_baseline(design, request)[response.reservation.ordinal - 1]
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
            and path.relative_to(directory).as_posix() not in {"reservations", "responses"}
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
            reservation = _contract(directory, name, GenerationReservation)
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
                    HostedGenerationOrigin.model_validate(envelope["hosted_origin"])
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
                reservation.canonical_bytes(),
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
        hosted_origin: HostedGenerationOrigin | None = None,
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

    def verify_frozen(self, batch: DiscoveryBatch) -> None:
        """Read original producer materials and check the entire frozen denominator."""
        if not self.root.is_dir():
            raise ArtifactIntegrityError("frozen generation originals are unavailable")
        with exclusive_directory_lock(self.root):
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

    def freeze(self, design: DiscoveryDesign) -> DiscoveryBatch:
        from quantos.application.discovery_admission import build_discovery_batch

        with exclusive_directory_lock(self.root):
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
