"""New-AST SDK successor using the retained one-attempt transport and normalizer.

No candidate-ref mapping and no authority in model output. Capture completion precedes
business submission; an incomplete intent is never reissued.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

from quantos.application.adaptive_store import AdaptiveStore, read, save
from quantos.application.agent_harness import (
    LocalAgentHarness,
    capture_from_agent_events,
    parse_agent_events,
)
from quantos.application.sdk_producer import (
    persist_sdk_host_transport,
    persist_sdk_observation,
    persist_sdk_process_exit,
    runtime_policy,
)
from quantos.artifacts.store import ArtifactIntegrityError, exclusive_directory_lock, sha256_file
from quantos.contracts.adaptive import (
    AdaptiveDecision,
    AdaptiveDecisionRequest,
    AdaptiveResearchSpec,
    AdaptiveSdkReservation,
)
from quantos.contracts.agent import AgentRole, AgentRunSpecV3, AgentUsage
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.harness import HarnessExecutionRequest, HarnessRuntimeIdentityV2
from quantos.contracts.hosted import strict_json_object
from quantos.integrations.codex.notification_projection import (
    normalize_provider_events,
    provider_events,
)
from quantos.integrations.codex.sdk_adapter import CodexSdkAdapter


def decision_schema() -> bytes:
    schema = AdaptiveDecision.model_json_schema()

    def explicit(item: Any) -> None:
        if isinstance(item, dict):
            mapping = cast(dict[str, Any], item)
            mapping.pop("default", None)
            if "properties" in mapping:
                mapping["required"] = sorted(mapping["properties"])
            for value in mapping.values():
                explicit(value)
        elif isinstance(item, list):
            for value in cast(list[Any], item):
                explicit(value)

    explicit(schema)
    return canonical_json_bytes(schema)


def reservation(
    spec: AdaptiveResearchSpec, request: AdaptiveDecisionRequest
) -> AdaptiveSdkReservation:
    if request.task_hash != spec.content_hash or request.ordinal > spec.limits.sdk_decisions:
        raise ArtifactIntegrityError("SDK request outside adaptive task")
    execution = HarnessExecutionRequest(
        run_id=f"adaptive-{request.content_hash}",
        cwd=spec.sdk_cwd,
        prompt=request.prompt,
        model=spec.sdk.model,
        reasoning_effort=spec.sdk.reasoning_effort,
        reasoning_summary="none",
        runtime_policy=runtime_policy(),
        mcp_servers=(),
        output_schema_json=decision_schema().decode(),
        timeout_seconds=spec.sdk.timeout_seconds,
        total_timeout_seconds=spec.sdk.timeout_seconds,
        max_transcript_bytes=spec.sdk.max_transcript_bytes,
        max_normalized_transcript_bytes=spec.sdk.max_normalized_transcript_bytes,
        max_input_tokens=spec.sdk.max_input_tokens,
        max_output_tokens=spec.sdk.max_output_tokens,
        max_attempts=1,
    )
    run = AgentRunSpecV3(
        run_id=execution.run_id,
        role=AgentRole.RESEARCHER,
        capability_policy_hash=runtime_policy().content_hash,
        campaign_hash=spec.content_hash,
        requested_model_configuration_hash=spec.sdk.content_hash,
        requested_runtime_policy_hash=runtime_policy().content_hash,
        transcript_policy_hash=sha256_bytes(
            canonical_json_bytes(
                {
                    "provider": spec.sdk.max_transcript_bytes,
                    "normalized": spec.sdk.max_normalized_transcript_bytes,
                }
            )
        ),
        retry_budget_hash=sha256_bytes(b'{"max_attempts":1,"reissue":false}'),
        tool_schema_hash=sha256_bytes(b"[]"),
        instruction_hashes=(sha256_bytes(decision_schema()),),
        skill_hash=sha256_bytes(b"bounded-adaptive-research/v1"),
        ledger_snapshot_hash=spec.design.ledger_snapshot_hash,
        input_artifact_hashes=tuple(
            sorted(
                {
                    spec.content_hash,
                    request.content_hash,
                    execution.content_hash,
                    *request.feedback_hashes,
                    *spec.context_source_hashes,
                }
            )
        ),
    )
    return AdaptiveSdkReservation(
        request_hash=request.content_hash,
        task_hash=spec.content_hash,
        execution_request=execution,
        run_spec=run,
    )


def parse_decision(raw: bytes, spec: AdaptiveResearchSpec) -> AdaptiveDecision:
    value = strict_json_object(raw, max_bytes=spec.sdk.max_raw_response_bytes)
    decision = AdaptiveDecision.model_validate(value)
    if decision.canonical_bytes() != canonical_json_bytes(value):
        raise ArtifactIntegrityError("decision defaults or scalar coercion forbidden")
    return decision


class AdaptiveSdkProducer:
    def __init__(
        self, spec: AdaptiveResearchSpec, harness: LocalAgentHarness | None = None
    ) -> None:
        self.spec, self.harness = spec, harness
        self.root = Path(spec.output_root) / "sdk"

    def directory(self, request: AdaptiveDecisionRequest) -> Path:
        return self.root / request.content_hash

    def status(self, request: AdaptiveDecisionRequest) -> str:
        d = self.directory(request)
        if (d / "failure.json").exists():
            return "FAILED"
        if (d / "capture-fact.json").exists():
            return "CAPTURED"
        if (d / "launch-intent.json").exists():
            return "UNKNOWN"
        return "NOT_STARTED"

    def _verified_capture(
        self, request: AdaptiveDecisionRequest
    ) -> tuple[AdaptiveDecision, dict[str, Any]]:
        spec, d = self.spec, self.directory(request)
        expected = reservation(spec, request)
        if (
            read(d / "request.json") != request.canonical_bytes()
            or read(d / "reservation.json") != expected.canonical_bytes()
        ):
            raise ArtifactIntegrityError("SDK prepared source drift")
        fact: dict[str, Any] = cast(
            dict[str, Any], strict_json_object(read(d / "capture-fact.json"), max_bytes=16384)
        )
        intent = strict_json_object(read(d / "launch-intent.json"), max_bytes=16384)
        if (
            fact["reservation_hash"] != expected.content_hash
            or intent["reservation_hash"] != expected.content_hash
        ):
            raise ArtifactIntegrityError("capture reservation differs")
        for name, digest in fact["sources"].items():
            if sha256_bytes(read(d / name, spec.sdk.max_transcript_bytes)) != digest:
                raise ArtifactIntegrityError("SDK captured original drift")
        if fact["terminal_error"] is not None or fact["attempts"] != 1:
            raise ArtifactIntegrityError("SDK unsuccessful capture")
        runtime = HarnessRuntimeIdentityV2.model_validate(fact["runtime"])
        if (
            runtime.sdk_version,
            runtime.runtime_package_version,
            runtime.runtime_binary_hash,
            runtime.runtime_version.partition(" ")[0],
        ) != (
            spec.sdk.sdk_version,
            spec.sdk.runtime_package_version,
            spec.sdk.runtime_binary_hash,
            spec.sdk.runtime_package_version,
        ):
            raise ArtifactIntegrityError("SDK runtime source differs")
        normalized = read(
            d / "normalized-transcript.jsonl", spec.sdk.max_normalized_transcript_bytes
        )
        capture = capture_from_agent_events(
            parse_agent_events(normalized, max_bytes=spec.sdk.max_normalized_transcript_bytes),
            max_bytes=spec.sdk.max_normalized_transcript_bytes,
        )
        provider = read(d / "provider-transcript.jsonl", spec.sdk.max_transcript_bytes)
        if not capture.thread_ids:
            raise ArtifactIntegrityError("SDK source thread missing")
        rebuilt = capture_from_agent_events(
            normalize_provider_events(
                provider_events(provider), thread_id=capture.thread_ids[-1], attempt=1
            ),
            max_bytes=spec.sdk.max_normalized_transcript_bytes,
        )
        raw = read(d / "raw-response.txt", spec.sdk.max_raw_response_bytes)
        if (
            rebuilt.transcript != normalized
            or capture.agent_messages != (raw.decode(),)
            or not capture.turn_started
            or not capture.turn_completed
            or capture.turn_failed
            or capture.commands
            or capture.tool_calls
            or capture.approval_requested
        ):
            raise ArtifactIntegrityError("SDK source/permission mismatch")
        if not (
            0 < capture.usage.get("input_tokens", 0) <= spec.sdk.max_input_tokens
            and 0 < capture.usage.get("output_tokens", 0) <= spec.sdk.max_output_tokens
        ):
            raise ArtifactIntegrityError("SDK usage missing or over bound")
        decision = parse_decision(raw, spec)
        response = {
            "schema_version": "adaptive-sdk-response/v1",
            "task_hash": spec.content_hash,
            "request_hash": request.content_hash,
            "reservation_hash": expected.content_hash,
            "capture_fact_hash": sha256_bytes(read(d / "capture-fact.json")),
            "decision_hash": decision.content_hash,
            "usage": AgentUsage(
                input_tokens=capture.usage.get("input_tokens", 0),
                output_tokens=capture.usage.get("output_tokens", 0),
                cached_input_tokens=capture.usage.get("cached_input_tokens", 0),
                tool_calls=0,
                retry_count=0,
            ).model_dump(mode="json"),
            "raw_response_hash": sha256_bytes(raw),
        }
        return decision, response

    def verify_capture(self, request: AdaptiveDecisionRequest) -> tuple[AdaptiveDecision, str]:
        """Verify completed originals without repairing or publishing any file."""
        decision, response = self._verified_capture(request)
        d = self.directory(request)
        if read(d / "decision.json") != decision.canonical_bytes() or read(
            d / "response.json"
        ) != canonical_json_bytes(response):
            raise ArtifactIntegrityError("SDK published response differs or is incomplete")
        return decision, sha256_bytes(canonical_json_bytes(response))

    def complete(self, request: AdaptiveDecisionRequest) -> tuple[AdaptiveDecision, str]:
        decision, response = self._verified_capture(request)
        d = self.directory(request)
        save(d / "decision.json", decision)
        save(d / "response.json", response)
        return decision, sha256_bytes(canonical_json_bytes(response))

    def launch(self, request: AdaptiveDecisionRequest) -> tuple[AdaptiveDecision, str]:
        spec, d = self.spec, self.directory(request)
        # The producer is independently bounded even if called outside the controller.
        # Its own launch lock serializes alternate request hashes; the parent writer
        # remains owned by the controller and is never recursively acquired here.
        with exclusive_directory_lock(self.root), exclusive_directory_lock(d):
            state = self.status(request)
            if state == "CAPTURED":
                return self.complete(request)
            if state != "NOT_STARTED":
                raise ArtifactIntegrityError("SDK UNKNOWN/FAILED is never reissued")
            events = AdaptiveStore(spec).events()
            requests = [e for e in events if e.kind == "DECISION_RESERVED"]
            if (
                not events
                or not requests
                or requests[-1].reference_hash != request.content_hash
                or len(requests) != request.ordinal
                or any(e.kind in {"STOPPED", "CANCELLED"} for e in events)
                or (Path(spec.output_root) / "cancel-request.json").exists()
                or len(tuple(self.root.glob("*/launch-intent.json"))) >= spec.limits.sdk_decisions
            ):
                raise ArtifactIntegrityError("SDK launch lacks live parent reservation")
            activation_path = Path(spec.output_root) / "activation.json"
            activation = cast(
                dict[str, Any], strict_json_object(read(activation_path), max_bytes=16384)
            )
            if (
                activation.get("task_hash") != spec.content_hash
                or sha256_bytes(read(activation_path)) != events[0].reference_hash
                or datetime.now(UTC) >= datetime.fromisoformat(activation["deadline"])
            ):
                raise ArtifactIntegrityError("SDK activation differs or expired")
            res = reservation(spec, request)
            cwd = Path(spec.sdk_cwd)
            if not cwd.is_absolute() or cwd.is_symlink() or not cwd.is_dir() or any(cwd.iterdir()):
                raise ArtifactIntegrityError("SDK requires frozen empty cwd")
            if self.harness is None and (
                (version("openai-codex"), version("openai-codex-cli-bin"))
                != (spec.sdk.sdk_version, spec.sdk.runtime_package_version)
                or sha256_file(Path(import_module("codex_cli_bin").bundled_codex_path()))
                != spec.sdk.runtime_binary_hash
            ):
                raise ArtifactIntegrityError("SDK install differs")
            save(d / "request.json", request)
            save(d / "reservation.json", res)
            save(d / "schema.json", decision_schema())
            save(
                d / "launch-intent.json",
                {
                    "reservation_hash": res.content_hash,
                    "started_at": datetime.now(UTC),
                    "state": "UNKNOWN_UNTIL_CAPTURED",
                    "max_attempts": 1,
                },
            )
            result = (
                self.harness
                or CodexSdkAdapter(
                    runtime_candidate_id=spec.sdk.runtime_candidate_id, metadata_projection=True
                )
            ).execute(res.execution_request)
            # Existing helpers retain independent real exit/usage/failed-host observations.
            persist_sdk_process_exit(d, result)
            raw = (
                result.capture.agent_messages[-1] if result.capture.agent_messages else ""
            ).encode()
            sources: dict[str, str] = {}
            for name, data, cap in [
                (
                    "normalized-transcript.jsonl",
                    result.normalized_transcript,
                    spec.sdk.max_normalized_transcript_bytes,
                ),
                (
                    "provider-transcript.jsonl",
                    result.provider_transcript or b"",
                    spec.sdk.max_transcript_bytes,
                ),
                ("raw-response.txt", raw, spec.sdk.max_raw_response_bytes),
            ]:
                if len(data) > cap:
                    save(
                        d / "failure.json",
                        {
                            "state": "FAILED",
                            "reason": "SOURCE_OVER_BOUND",
                            "file": name,
                            "source_hash": sha256_bytes(data),
                            "bytes": len(data),
                        },
                    )
                    raise ArtifactIntegrityError("SDK source over bound")
                sources[name] = save(d / name, data)
            try:
                persist_sdk_observation(d, result)
                persist_sdk_host_transport(d, result)
                sources.update(
                    {
                        p.name: sha256_bytes(read(p))
                        for p in (
                            d / "sdk-observation.json",
                            d / "sdk-process-exit.json",
                            d / "host-transport.json",
                        )
                        if p.exists()
                    }
                )
                save(
                    d / "capture-fact.json",
                    {
                        "schema_version": "adaptive-sdk-capture/v1",
                        "reservation_hash": res.content_hash,
                        "runtime": result.runtime.model_dump(mode="json")
                        if result.runtime
                        else None,
                        "terminal_error": result.terminal_error.model_dump(mode="json")
                        if result.terminal_error
                        else None,
                        "attempts": len(result.attempts),
                        "sources": sources,
                        "completed_at": datetime.now(UTC),
                    },
                )
                return self.complete(request)
            except (ValueError, TypeError, UnicodeError):
                save(
                    d / "failure.json",
                    {
                        "state": "FAILED",
                        "reason": "CAPTURE_OR_OUTPUT_INVALID",
                        "usage_semantics": "SEE_RETAINED_PROVIDER_OBSERVATION",
                    },
                )
                raise ArtifactIntegrityError("SDK failed; no automatic retry") from None
