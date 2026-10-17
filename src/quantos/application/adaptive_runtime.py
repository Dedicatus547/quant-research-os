"""Bounded successor controller. Model output stays a proposal; all effects are ordered."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from quantos.application.adaptive_execution import AdaptiveExecutionPort, freeze_child
from quantos.application.adaptive_feedback import build_feedback, render_adaptive_report
from quantos.application.adaptive_sdk import AdaptiveSdkProducer
from quantos.application.adaptive_store import AdaptiveStore, read, save
from quantos.application.enumeration import structural_expression_hash
from quantos.artifacts.store import ArtifactIntegrityError, exclusive_directory_lock
from quantos.contracts.adaptive import (
    AdaptiveChild,
    AdaptiveDecision,
    AdaptiveDecisionRequest,
    AdaptiveEvent,
    AdaptiveResearchSpec,
)
from quantos.contracts.adaptive_feedback import AdaptiveFeedback
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes

UNPROVEN = [
    "REAL_NEW_AST_SDK_SCIENCE_FEEDBACK_COMBINATION",
    "FEEDBACK_CAUSAL_QUALITY_IMPROVEMENT",
    "LONG_TERM_RELIABILITY",
    "CROSS_HOST_INSTALL",
    "HISTORICAL_VENDOR_VINTAGE_PIT",
    "SEALED_CONFIRMATION",
]


class AdaptiveRuntime:
    def __init__(
        self,
        spec: AdaptiveResearchSpec,
        producer: AdaptiveSdkProducer,
        execution: AdaptiveExecutionPort,
        *,
        clock: Callable[[], datetime] | None = None,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.spec, self.producer, self.execution = spec, producer, execution
        self.store = AdaptiveStore(spec)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.fault: Callable[[str], None] = fault or (lambda _: None)
        self._verified_feedback: set[str] = set()

    def _object(self, digest: str) -> dict[str, Any]:
        data = read(self.store.root / "objects" / f"{digest}.json")
        if sha256_bytes(data) != digest:
            raise ArtifactIntegrityError("adaptive referenced original drift")
        return json.loads(data)

    def _append(
        self, kind: Any, value: CanonicalContract | dict[str, Any], units: int = 0
    ) -> AdaptiveEvent:
        digest = self.store.put(value)
        return self.store.append(kind, digest, self.clock(), units)

    def _stop(self, reason: str | None) -> dict[str, Any]:
        if not any(e.kind == "STOPPED" for e in self.store.events()):
            self._append("STOPPED", {"schema_version": "adaptive-stop/v1", "reason": reason})
        return self.checkpoint()

    def _inactive(self) -> str | None:
        events = self.store.events()
        cancel = self.store.root / "cancel-request.json"
        if cancel.exists():
            if json.loads(read(cancel)).get("task_hash") != self.spec.content_hash:
                raise ArtifactIntegrityError("cancellation belongs to another task")
            return "CANCELLED"
        if any(e.kind == "CANCELLED" for e in events):
            return "CANCELLED"
        if any(e.kind == "STOPPED" for e in events):
            return "STOPPED"
        activation = self._object(events[0].reference_hash)
        if self.clock() >= datetime.fromisoformat(activation["deadline"]):
            return "EXPIRED"
        return None

    def status(self) -> dict[str, Any]:
        events = self.store.events()
        sdk_attempts: list[dict[str, Any]] = []
        for event in events:
            if event.kind != "DECISION_RESERVED":
                continue
            request = self.store.get(event.reference_hash, AdaptiveDecisionRequest)
            directory = self.producer.directory(request)
            response_path = directory / "response.json"
            usage = None
            if response_path.exists():
                response_bytes = read(response_path)
                capture = next(
                    (
                        self._object(e.reference_hash)
                        for e in events
                        if e.kind == "DECISION_CAPTURED"
                        and self._object(e.reference_hash)["request_hash"] == request.content_hash
                    ),
                    None,
                )
                if capture is not None and sha256_bytes(response_bytes) != capture["response_hash"]:
                    raise ArtifactIntegrityError("SDK report response original differs")
                usage = json.loads(response_bytes)["usage"]
            sdk_attempts.append(
                {
                    "request_hash": request.content_hash,
                    "state": self.producer.status(request),
                    "usage": usage,
                    "originals": str(directory),
                }
            )
        children = [
            self.store.get(e.reference_hash, AdaptiveChild)
            for e in events
            if e.kind == "CHILD_RESERVED"
        ]
        settled = [
            self.store.get(e.reference_hash, AdaptiveFeedback)
            for e in events
            if e.kind == "SCIENCE_SETTLED"
        ]
        settled_children = {f.child_hash for f in settled}
        # Every event is checked against its parent, request and immutable child.
        if len(settled_children) != len(settled):
            raise ArtifactIntegrityError("duplicate scientific settlement")
        for f in settled:
            child = next((c for c in children if c.content_hash == f.child_hash), None)
            if (
                child is None
                or f.task_hash != self.spec.content_hash
                or f.request_hash != child.request.content_hash
                or f.campaign_hash != child.campaign.content_hash
            ):
                raise ArtifactIntegrityError("feedback task/child/request differs")
        consumed = sum(c.quote_units for c in children if c.content_hash in settled_children)
        reserved = sum(c.quote_units for c in children if c.content_hash not in settled_children)
        decisions = sum(e.kind == "DECISION_RESERVED" for e in events)
        starts = sum(e.kind == "SCIENCE_STARTED" for e in events)
        if (
            len(children) > self.spec.limits.new_candidates
            or decisions > self.spec.limits.sdk_decisions
            or starts > self.spec.limits.scientific_executions
            or consumed + reserved > self.spec.limits.compute_units
        ):
            raise ArtifactIntegrityError("parent budget exceeded")
        stops = [self._object(e.reference_hash) for e in events if e.kind == "STOPPED"]
        return {
            "schema_version": "adaptive-report/v1",
            "task_hash": self.spec.content_hash,
            "status": "STOPPED" if stops else "RUNNING" if events else "PREPARED",
            "stop_reason": stops[-1]["reason"] if stops else None,
            "qualification": "NOT_QUALIFIED",
            "opportunities": {
                "sdk_decisions": {"used": decisions, "limit": self.spec.limits.sdk_decisions},
                "new_candidates": {"used": len(children), "limit": self.spec.limits.new_candidates},
                "scientific_executions": {
                    "used": starts,
                    "reserved": len(children) - starts,
                    "limit": self.spec.limits.scientific_executions,
                },
            },
            "consumed_units": consumed,
            "reserved_units": reserved,
            "compute_unit_limit": self.spec.limits.compute_units,
            "feedback": [f.model_dump(mode="json") for f in settled],
            "feedback_verification": "VERIFIED_THIS_OPERATION"
            if all(f.content_hash in self._verified_feedback for f in settled)
            else "RETAINED_PROJECTION_REVERIFY_REQUIRED",
            "events": [e.model_dump(mode="json") for e in events],
            "originals": str(self.store.root),
            "sdk_observations": [
                str(p) for p in sorted((self.store.root / "sdk").glob("*/sdk-observation.json"))
            ],
            "sdk_attempts": sdk_attempts,
            "unknown_usage": "UNAVAILABLE_UNLESS_CAPTURE_OBSERVED_NOT_ZERO",
            "billing_semantics": "LOCAL_OBSERVATION_LIMITS_NOT_PROVIDER_BILLING_CAP",
            "interpretation": self.spec.interpretation,
            "unproven_capabilities": UNPROVEN,
            "scientific_summary": "SEE_INDIVIDUAL_VERIFIED_FEEDBACK_NO_SELECTION_OR_PROFIT_CLAIM",
        }

    def checkpoint(self) -> dict[str, Any]:
        result = self.status()
        digest = self.store.put(result)
        save(
            self.store.root / "checkpoints" / f"{len(self.store.events()):06d}-{digest}.json",
            result,
        )
        save(self.store.root / "reports" / f"{digest}.md", render_adaptive_report(result).encode())
        return result

    def cancel(self) -> dict[str, Any]:
        # Independent intent can be published while the controller owns its writer
        # lock. It grants no journal write or refund; in-flight work may finish.
        save(
            self.store.root / "cancel-request.json",
            {"schema_version": "adaptive-cancel/v1", "task_hash": self.spec.content_hash},
        )
        return {
            "task_hash": self.spec.content_hash,
            "status": "CANCEL_REQUESTED",
            "inflight": "NOT_ASSUMED_CANCELLED_OR_REFUNDED",
        }

    def _feedback(self) -> list[AdaptiveFeedback]:
        result: list[AdaptiveFeedback] = []
        children = {
            e.reference_hash: self.store.get(e.reference_hash, AdaptiveChild)
            for e in self.store.events()
            if e.kind == "CHILD_RESERVED"
        }
        for e in self.store.events():
            if e.kind == "SCIENCE_SETTLED":
                retained = self.store.get(e.reference_hash, AdaptiveFeedback)
                child = children[retained.child_hash]
                if retained.content_hash in self._verified_feedback:
                    result.append(retained)
                    continue
                outcome = self.execution.reconcile(child)
                if outcome is None:
                    raise ArtifactIntegrityError("settled science original missing")
                actual = build_feedback(
                    task_hash=self.spec.content_hash,
                    child_hash=child.content_hash,
                    request=child.request,
                    outcome=outcome,
                    adapter=self.execution.adapter(child),
                    process_exit=self.execution.process_exit(child),
                )
                if actual != retained:
                    raise ArtifactIntegrityError("feedback differs from scientific originals")
                result.append(retained)
                self._verified_feedback.add(retained.content_hash)
        return result

    def _request(self, ordinal: int) -> AdaptiveDecisionRequest:
        events = self.store.events()
        feedback = self._feedback()
        captures = [self._object(e.reference_hash) for e in events if e.kind == "DECISION_CAPTURED"]
        previous = captures[-1]["decision_hash"] if captures else None
        seen_hashes = set(self.spec.initial_structural_hashes)
        for capture in captures:
            expression = self.store.get(capture["decision_hash"], AdaptiveDecision).expression
            if expression is not None:
                seen_hashes.add(structural_expression_hash(expression))
        seen = sorted(seen_hashes)
        exposure_hash = self.store.put(
            {
                "schema_version": "adaptive-exposure/v1",
                "structural_hashes": seen,
                "feedback_hashes": [f.content_hash for f in feedback],
                "prior_exposure": self.spec.design.exposure_history,
            }
        )
        payload = {
            "task_hash": self.spec.content_hash,
            "question": self.spec.design.research_question,
            "context": self.spec.context,
            "source_hashes": self.spec.context_source_hashes,
            "parent_proposal_hash": previous,
            "feedback": [
                {"feedback_hash": f.content_hash, "projection": f.model_dump(mode="json")}
                for f in feedback
            ],
            "exposure_history": {
                "structural_hashes": seen,
                "interpretation": self.spec.interpretation,
            },
            "allowed": {
                "grammar": self.spec.design.candidate_grammar,
                "operators": self.spec.design.allowed_operators,
                "windows": self.spec.design.allowed_windows,
                "max_nodes": self.spec.design.max_nodes,
                "max_depth": getattr(self.spec.design, "max_depth", None),
                "field": "adjusted_close",
                "input_lag_trading_days": (
                    self.spec.design.authoring.strategy.input_lag_trading_days
                ),
            },
            "remaining": {
                "sdk_decisions_including_this": self.spec.limits.sdk_decisions - ordinal + 1,
                "new_candidates": self.spec.limits.new_candidates
                - sum(e.kind == "CHILD_RESERVED" for e in events),
                "compute_units": self.spec.limits.compute_units
                - sum(e.units for e in events if e.kind == "CHILD_RESERVED"),
            },
            "validation_thresholds": [
                gate.model_dump(mode="json")
                for gate in self.spec.design.validation_policy.soft_gates
            ],
        }
        prompt = (
            "Return one explicit adaptive-decision/v1 JSON object. Decide STOP or "
            "PROPOSE based on the supplied evidence. Do not invoke tools. A proposal "
            "includes a hypothesis and safe AST within the exact grammar; use no "
            "Python, new field, operator or data. Copy parent_proposal_hash and all "
            "feedback_hashes exactly; cite at least one supplied source_hash. Give the "
            "reason for stopping or for the revision. No requirement to continue or "
            "change candidate. Scientific REJECT is valid evidence; no profitability "
            "target. Model output is a proposal, never evidence. Every response field, "
            "including nullable fields and nested schema versions, must be explicit. "
            "Context:\n"
        ) + canonical_json_bytes(payload).decode()
        return AdaptiveDecisionRequest(
            task_hash=self.spec.content_hash,
            ordinal=ordinal,
            previous_event_hash=events[-1].content_hash,
            parent_proposal_hash=previous,
            feedback_hashes=tuple(sorted(f.content_hash for f in feedback)),
            exposure_hash=exposure_hash,
            prompt=prompt,
        )

    def run(self, *, receipt_only: bool = False) -> dict[str, Any]:
        with exclusive_directory_lock(self.store.root / "writer"):
            self._verified_feedback.clear()
            self.store.initialize()
            if not self.store.events():
                if receipt_only:
                    return self.checkpoint()
                activation_path = self.store.root / "activation.json"
                activation = (
                    json.loads(read(activation_path))
                    if activation_path.exists()
                    else {
                        "schema_version": "adaptive-activation/v1",
                        "task_hash": self.spec.content_hash,
                        "started_at": self.clock(),
                        "deadline": self.clock() + timedelta(seconds=self.spec.limits.wall_seconds),
                    }
                )
                if activation["task_hash"] != self.spec.content_hash:
                    raise ArtifactIntegrityError("activation belongs to another task")
                save(self.store.root / "activation.json", activation)
                self._append("ACTIVATED", activation)
                self.checkpoint()
            # At most the frozen number of decisions. No retry or repair-model calls.
            for ordinal in range(1, self.spec.limits.sdk_decisions + 1):
                events = self.store.events()
                requests = [e for e in events if e.kind == "DECISION_RESERVED"]
                if ordinal > len(requests):
                    inactive = self._inactive()
                    if inactive or receipt_only:
                        return (
                            self.checkpoint()
                            if receipt_only or inactive == "STOPPED"
                            else self._stop(inactive)
                        )
                    request = self._request(ordinal)
                    self._append("DECISION_RESERVED", request)
                    self.checkpoint()
                    self.fault("decision_reserved")
                else:
                    event = requests[ordinal - 1]
                    request = self.store.get(event.reference_hash, AdaptiveDecisionRequest)
                    if (
                        request.task_hash != self.spec.content_hash
                        or request.ordinal != ordinal
                        or request.previous_event_hash != event.previous_hash
                    ):
                        raise ArtifactIntegrityError("decision reserved prefix differs")
                # A retained later request does not exempt its feedback from bottom-up
                # verification after a restart. No new call uses a stale projection.
                feedback = self._feedback()
                provided = set(request.feedback_hashes)
                earlier = {
                    f.content_hash
                    for f in feedback
                    if any(
                        e.kind == "SCIENCE_SETTLED"
                        and e.reference_hash == f.content_hash
                        and e.ordinal
                        < next(
                            x.ordinal
                            for x in self.store.events()
                            if x.kind == "DECISION_RESERVED"
                            and x.reference_hash == request.content_hash
                        )
                        for e in self.store.events()
                    )
                }
                if provided != earlier:
                    raise ArtifactIntegrityError("request feedback differs from reserved history")
                captures = [
                    self._object(e.reference_hash)
                    for e in self.store.events()
                    if e.kind == "DECISION_CAPTURED"
                ]
                capture = next(
                    (c for c in captures if c["request_hash"] == request.content_hash), None
                )
                if capture is None:
                    state = self.producer.status(request)
                    if state == "UNKNOWN":
                        return self._stop("UNKNOWN")
                    if state == "FAILED":
                        return self._stop("SDK_FAILED")
                    if state == "NOT_STARTED" and (receipt_only or self._inactive()):
                        return self.checkpoint() if receipt_only else self._stop(self._inactive())
                    if state == "NOT_STARTED":
                        self.execution.verify_inputs()
                        if self._inactive():
                            return self._stop(self._inactive())
                    try:
                        decision, response_hash = (
                            self.producer.complete(request)
                            if state == "CAPTURED"
                            else self.producer.launch(request)
                        )
                    except (ValueError, ArtifactIntegrityError):
                        return self._stop("SDK_CAPTURE_OR_OUTPUT_INVALID")
                    self.fault("capture_complete")
                    self.store.put(decision)
                    capture = {
                        "schema_version": "adaptive-captured-decision/v1",
                        "request_hash": request.content_hash,
                        "decision_hash": decision.content_hash,
                        "response_hash": response_hash,
                    }
                    self._append("DECISION_CAPTURED", capture)
                    self.checkpoint()
                    self.fault("decision_submitted")
                else:
                    decision, response_hash = self.producer.complete(request)
                    if (
                        decision.content_hash != capture["decision_hash"]
                        or response_hash != capture["response_hash"]
                    ):
                        raise ArtifactIntegrityError("submitted decision differs from SDK original")
                decision = self.store.get(capture["decision_hash"], AdaptiveDecision)
                if (
                    decision.parent_proposal_hash != request.parent_proposal_hash
                    or decision.feedback_hashes != request.feedback_hashes
                    or not decision.source_hashes
                    or not set(decision.source_hashes) <= set(self.spec.context_source_hashes)
                ):
                    return self._stop("DECISION_SOURCE_OR_FEEDBACK_REJECTED")
                if decision.action == "STOP":
                    return self._stop("MODEL_STOP")
                children = [
                    self.store.get(e.reference_hash, AdaptiveChild)
                    for e in self.store.events()
                    if e.kind == "CHILD_RESERVED"
                ]
                child = next(
                    (c for c in children if c.decision_hash == decision.content_hash), None
                )
                if child is None:
                    if receipt_only or self._inactive():
                        return self.checkpoint() if receipt_only else self._stop(self._inactive())
                    seen = {
                        *self.spec.initial_structural_hashes,
                        *[c.request.candidate_structural_expression_hash for c in children],
                    }
                    if (
                        decision.expression is not None
                        and structural_expression_hash(decision.expression) in seen
                    ):
                        return self._stop("DUPLICATE_AST")
                    try:
                        child = freeze_child(
                            self.spec, decision, capture["response_hash"], len(children) + 1
                        )
                    except ValueError:
                        return self._stop("STATIC_ADMISSION_REJECTED")
                    if (
                        len(children) >= self.spec.limits.new_candidates
                        or len(children) >= self.spec.limits.scientific_executions
                        or sum(c.quote_units for c in children) + child.quote_units
                        > self.spec.limits.compute_units
                    ):
                        return self._stop("PARENT_BUDGET_EXHAUSTED")
                    self._append("CHILD_RESERVED", child, child.quote_units)
                    self.checkpoint()
                    self.fault("child_reserved")
                expected = freeze_child(
                    self.spec, decision, capture["response_hash"], child.ordinal
                )
                if child != expected:
                    raise ArtifactIntegrityError("child authority/request or quote drift")
                events = self.store.events()
                settled = [
                    self.store.get(e.reference_hash, AdaptiveFeedback)
                    for e in events
                    if e.kind == "SCIENCE_SETTLED"
                ]
                if any(f.child_hash == child.content_hash for f in settled):
                    continue
                started = any(
                    e.kind == "SCIENCE_STARTED" and e.reference_hash == child.content_hash
                    for e in events
                )
                if started:
                    outcome = self.execution.reconcile(child)
                    if outcome is None:
                        return self._stop("RECOVERY_REQUIRED")
                else:
                    if receipt_only or self._inactive():
                        return self.checkpoint() if receipt_only else self._stop(self._inactive())
                    self.store.append(
                        "SCIENCE_STARTED", child.content_hash, self.clock(), child.quote_units
                    )
                    self.checkpoint()
                    self.fault("science_started")
                    outcome = self.execution.execute(child)
                    self.fault("science_complete")
                feedback = build_feedback(
                    task_hash=self.spec.content_hash,
                    child_hash=child.content_hash,
                    request=child.request,
                    outcome=outcome,
                    adapter=self.execution.adapter(child),
                    process_exit=self.execution.process_exit(child),
                )
                if outcome.compute_seconds != child.quote_units:
                    raise ArtifactIntegrityError(
                        "scientific policy charge differs from reservation"
                    )
                self._append("SCIENCE_SETTLED", feedback)
                self._verified_feedback.add(feedback.content_hash)
                self.checkpoint()
                self.fault("science_settled")
            return self.checkpoint() if receipt_only else self._stop("DECISION_BUDGET_EXHAUSTED")
