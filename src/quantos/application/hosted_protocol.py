"""One bounded protocol service shared by hosted orchestration and authenticated channels."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, cast

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.autonomous import AutonomousAgentRequest
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentExchange,
    HostedAgentRequest,
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedCampaignSpec,
    HostedCheckpoint,
    HostedProtocolStatus,
    HostedRequestSubmissionCount,
    HostedRequestTerminalReceipt,
    HostedSubmissionReceipt,
    parse_hosted_contract,
)
from quantos.contracts.sdk_producer import (
    SdkAgentExchange,
    SdkAgentRequest,
    SdkAgentRequestV3,
    SdkAgentResponse,
    SdkCampaignSpec,
    SdkProducerProfileV3,
    parse_agent_exchange,
    parse_sdk_response,
)
from quantos.contracts.validation import ReproducibilityComparison
from quantos.infrastructure.hosted_store import HostedProtocolStore, HostedStoreSnapshot
from quantos.security import SecretArtifactRejected, validate_secret_free


def _clock() -> datetime:
    return datetime.now(UTC)


def _identity(value: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}", value) is None:
        raise ValueError("authenticated principal must be a bounded opaque identity")
    validate_secret_free(value, file_name="hosted-principal.json")
    return value


def hosted_protocol_operation_id(campaign: str, kind: str, identity: object) -> str:
    return sha256_bytes(canonical_json_bytes((campaign, kind, identity)))


def _scan_safe(value: object) -> None:
    """Reuse the credential scanner, preserving its per-string bound.

    Only the typed usage scalars bypass sensitive-key heuristics. Proposal text is
    parsed when possible, so credential fields remain checked even in large text.
    Large free text is scanned in overlapping bounded pieces; rejected bytes are
    never written. The scanner has no logging and its exceptions omit values.
    """

    if isinstance(value, dict):
        root = cast(dict[str, object], value)
        if root.get("schema_version") == "hosted-agent-response/v1":
            root = dict(root)
            observation = dict(cast(dict[str, object], root["host_observation"]))
            usage = dict(cast(dict[str, object], observation["reported_usage"]))
            for name in ("input_tokens", "output_tokens", "cost_microunits"):
                scalar = usage.pop(name)
                if scalar is not None and (type(scalar) is not int or scalar < 0):
                    raise ValueError("hosted reported usage scalar is invalid")
                usage[f"reported_{name.replace('tokens', 'count')}"] = scalar
            observation["reported_usage"] = usage
            root["host_observation"] = observation
            value = root

    if isinstance(value, dict):
        root = dict(cast(dict[str, object], value))
        schema = root.get("schema_version")
        if schema in ("hosted-campaign-spec/v1", "sdk-campaign-spec/v1"):
            binding = dict(cast(dict[str, object], root["execution_bindings"]))
            commit = binding.pop("code_commit_hash")
            if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ValueError("typed commit identity is invalid")
            binding["code_commit_identity"] = commit
            root["execution_bindings"] = binding
        elif schema == "autonomous-execution-request/v2":
            commit = root.pop("code_commit_hash")
            if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ValueError("typed commit identity is invalid")
            root["code_commit_identity"] = commit
        elif (
            schema == "hosted-research-step-intent/v1" and root.get("execution_request") is not None
        ):
            execution = dict(cast(dict[str, object], root["execution_request"]))
            if execution.get("schema_version") != "autonomous-execution-request/v2":
                raise ValueError("typed step execution schema is invalid")
            commit = execution.pop("code_commit_hash")
            if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ValueError("typed step execution commit identity is invalid")
            execution["code_commit_identity"] = commit
            root["execution_request"] = execution
        elif schema in ("hosted-agent-request/v1", "sdk-agent-request/v1", "sdk-agent-request/v3"):
            business = dict(cast(dict[str, object], root["business_request"]))
            declaration = business["allowed_proposal_schema_json"]
            if not isinstance(declaration, str):
                raise ValueError("typed proposal schema declaration is invalid")
            business["allowed_proposal_schema_json"] = "schema-fragment " + declaration
            root["business_request"] = business
        value = root

    if isinstance(value, dict):
        sdk_scan_value = dict(cast(dict[str, object], value))
        if sdk_scan_value.get("schema_version") in (
            "sdk-agent-response/v1",
            "sdk-agent-response/v2",
            "sdk-agent-response/v3",
        ):
            sdk_scan_value["semantic_response_text"] = sdk_scan_value.pop("raw_response")
        value = sdk_scan_value

    def prepare(item: object) -> object:
        if isinstance(item, dict):
            mapping = cast(dict[str, object], item)
            schema_kind = mapping.get("schema_version")
            scalar_fields = {
                "sdk-producer-profile/v1": ("max_input_tokens", "max_output_tokens"),
                "sdk-producer-profile/v2": ("max_input_tokens", "max_output_tokens"),
                "sdk-producer-profile/v3": ("max_input_tokens", "max_output_tokens"),
                "sdk-producer-profile/v4": ("max_input_tokens", "max_output_tokens"),
                "harness-execution-request/v2": ("max_input_tokens", "max_output_tokens"),
                "agent-usage/v1": ("input_tokens", "output_tokens", "cached_input_tokens"),
            }.get(schema_kind if isinstance(schema_kind, str) else "", ())
            if mapping.get("schema_version") == "harness-capability-observation/v1":
                mapping = dict(mapping)
                absence = mapping.pop("parent_secret_absence_observed")
                if absence is not None and type(absence) is not bool:
                    raise ValueError("SDK typed credential-absence observation is invalid")
                mapping["parent_sensitive_value_absence_observed"] = absence
            if scalar_fields:
                mapping = dict(mapping)
                for field in scalar_fields:
                    scalar = mapping.pop(field)
                    if type(scalar) is not int or scalar < 0:
                        raise ValueError("SDK typed usage/budget scalar is invalid")
                    mapping[field.replace("tokens", "count")] = scalar
            if mapping.get("schema_version") == "reproducibility-comparison/v1":
                comparison = ReproducibilityComparison.model_validate(mapping)
                if type(
                    mapping.get("exact_content_hash")
                ) is not bool or comparison.canonical_bytes() != canonical_json_bytes(mapping):
                    raise ValueError(
                        "typed reproducibility comparison differs from canonical bytes"
                    )
                # This existing contract field is a boolean comparison result, not
                # a digest. Rename only this validated field in the scan view.
                mapping = dict(mapping)
                mapping["exact_content_hash_matches"] = mapping.pop("exact_content_hash")
            return {key: prepare(val) for key, val in mapping.items()}
        if isinstance(item, (list, tuple)):
            return [prepare(val) for val in cast(list[object] | tuple[object, ...], item)]
        if isinstance(item, str):
            try:
                embedded: object = json.loads(item)
            except (ValueError, RecursionError):
                embedded = None
            if isinstance(embedded, (dict, list)):
                return prepare(cast(object, embedded))
            if len(item) > 65_536:
                return [
                    item[max(0, offset - 4096) : offset + 60_000]
                    for offset in range(0, len(item), 60_000)
                ]
        return item

    validate_secret_free(prepare(cast(object, value)), file_name="hosted-protocol.json")


class HostedProtocolService:
    """Transport authority only. Business admission/execution belongs to HM-04.

    Authentication and campaign authorization happen in the service-owned channel
    before calling this object. ``register`` and ``publish_business`` are internal
    management operations and must never be exposed on that host channel.
    """

    def __init__(
        self,
        store: HostedProtocolStore,
        *,
        clock: Callable[[], datetime] = _clock,
        verify_inputs: Callable[[HostedCampaignSpec], None] | None = None,
        scan_submission: Callable[[bytes], None] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock
        self._verify_inputs = verify_inputs
        self._scan_submission = scan_submission

    def register(self, spec: HostedCampaignSpec) -> str:
        _scan_safe(spec.model_dump(mode="json"))
        return self.store.register_spec(spec)

    def start(self, spec_hash: str) -> HostedProtocolStatus:
        spec = self.store.spec(spec_hash)
        if self._verify_inputs is None:
            raise ArtifactIntegrityError("frozen input reverifier is required before start")
        self._verify_inputs(spec)
        with self.store.campaign_lock(spec.campaign_hash, create=True) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            try:
                state = self.store.snapshot_locked(campaign_fd)
            except ArtifactIntegrityError:
                # Only a genuinely empty journal may initialize a campaign.
                if self.store.has_journal_locked(campaign_fd):
                    raise
                now = spec.started_at
                op = hosted_protocol_operation_id(spec.campaign_hash, "REGISTER", spec_hash)
                budget = HostedBudgetJournalFact(
                    campaign_hash=spec.campaign_hash,
                    hosted_spec_hash=spec_hash,
                    operation_id=op,
                    previous_hash=None,
                    used_requests=0,
                    used_unique_submissions=0,
                    request_submissions=(),
                    recorded_at=now,
                )
                exhausted = self.project_exhaustion_receipt(spec, budget, None, now)
                self.store.commit_locked(
                    campaign_fd,
                    campaign_hash=spec.campaign_hash,
                    operation_id=op,
                    operation_kind="REGISTER",
                    recorded_at=now,
                    artifacts=(spec, budget, exhausted),
                )
                state = self.store.snapshot_locked(campaign_fd)
            if state.spec.content_hash != spec_hash:
                raise ArtifactIntegrityError("campaign is already bound to another hosted spec")
            return self.project_status(state, self._clock())

    @staticmethod
    def project_exhaustion_receipt(
        spec: HostedCampaignSpec,
        budget: HostedBudgetJournalFact,
        request: HostedAgentRequest | None,
        now: datetime,
    ) -> HostedSubmissionReceipt:
        return HostedSubmissionReceipt(
            campaign_hash=spec.campaign_hash,
            request_hash=request.content_hash if request else None,
            submission_bytes_hash=None,
            observed_bytes=0,
            complete=True,
            attempt_identity=request.attempt_identity if request else None,
            outcome="EXHAUSTED",
            reason="SUBMISSION_ALLOWANCE_EXHAUSTED",
            budget_before_hash=budget.content_hash,
            budget_after_hash=budget.content_hash,
            recorded_at=now,
            authenticated_principal="service",
        )

    def issue(
        self,
        spec_hash: str,
        business_request: AutonomousAgentRequest,
        *,
        projection_object_hashes: tuple[str, ...],
    ) -> HostedAgentRequest:
        self.start(spec_hash)
        spec = self.store.spec(spec_hash)
        with self.store.campaign_lock(spec.campaign_hash) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            state = self.store.snapshot_locked(campaign_fd)
            existing = state.active_request
            if existing is not None:
                return existing
            if any(x.outcome in ("CANCELLED", "EXPIRED") for x in state.terminals):
                raise ArtifactIntegrityError("reissue=false: hosted campaign terminated")
            before = state.budget
            if before.used_requests >= spec.hosted_budget.max_requests:
                raise ArtifactIntegrityError("hosted request allowance exhausted")
            if before.used_unique_submissions >= spec.hosted_budget.max_unique_submissions:
                raise ArtifactIntegrityError("hosted submission allowance exhausted")
            if (
                business_request.campaign_hash != spec.campaign_hash
                or business_request.family_hash != spec.campaign.family_hash
                or business_request.budget_hash != spec.campaign.budget_hash
                or business_request.candidate_manifest_hash != spec.candidate_manifest_hash
                or business_request.agent_run_spec.requested_model_configuration_hash
                != spec.requested_model_configuration_hash
                or business_request.context_pack.search_policy_hash != spec.search_policy_hash
                or business_request.context_pack.context_budget_policy_hash
                != spec.context_budget_policy_hash
            ):
                raise ArtifactIntegrityError("hosted business request frozen bindings disagree")
            now = self._clock()
            ordinal = before.used_requests + 1
            op = hosted_protocol_operation_id(spec.campaign_hash, "ISSUE", ordinal)
            after = HostedBudgetJournalFact(
                campaign_hash=spec.campaign_hash,
                hosted_spec_hash=spec_hash,
                operation_id=op,
                previous_hash=before.content_hash,
                used_requests=ordinal,
                used_unique_submissions=before.used_unique_submissions,
                request_submissions=(
                    *before.request_submissions,
                    HostedRequestSubmissionCount(transport_ordinal=ordinal, used_submissions=0),
                ),
                recorded_at=now,
            )
            request_type: type[HostedAgentRequest] = HostedAgentRequest
            sdk_fields: dict[str, object] = {}
            if isinstance(spec, SdkCampaignSpec):
                request_type = (
                    SdkAgentRequestV3
                    if isinstance(spec.sdk_profile, SdkProducerProfileV3)
                    else SdkAgentRequest
                )
                sdk_fields["sdk_profile_hash"] = spec.sdk_profile.content_hash
            request = request_type.model_validate(
                dict(
                    **sdk_fields,
                    campaign_hash=spec.campaign_hash,
                    hosted_spec_hash=spec_hash,
                    transport_ordinal=ordinal,
                    business_request=business_request,
                    business_request_hash=business_request.content_hash,
                    context_pack_hash=business_request.context_pack.content_hash,
                    candidate_manifest_hash=spec.candidate_manifest_hash,
                    input_hashes=tuple(
                        sorted(
                            set(
                                (
                                    *spec.frozen_input_hashes,
                                    *business_request.agent_run_spec.input_artifact_hashes,
                                )
                            )
                        )
                    ),
                    policy_hashes=business_request.relevant_policy_hashes,
                    budget_reservation_hash=after.content_hash,
                    proposal_schema_hash=business_request.proposal_schema_hash,
                    max_request_bytes=spec.hosted_budget.max_request_bytes,
                    max_response_bytes=spec.hosted_budget.max_response_bytes,
                    max_proposal_bytes=spec.hosted_budget.max_proposal_bytes,
                    attempt_identity=hosted_protocol_operation_id(
                        spec.campaign_hash, "ATTEMPT", ordinal
                    ),
                    projection_object_hashes=projection_object_hashes,
                    issued_at=now,
                    expires_at=now + timedelta(seconds=spec.hosted_budget.request_ttl_seconds),
                )
            )
            if len(request.canonical_bytes()) > request.max_request_bytes:
                raise ValueError("hosted request exceeds frozen byte cap")
            _scan_safe(request.model_dump(mode="json"))
            checkpoint = HostedCheckpoint(
                request_hash=request.content_hash,
                campaign_hash=spec.campaign_hash,
                transport_ordinal=ordinal,
                recorded_at=now,
            )
            exhausted = self.project_exhaustion_receipt(spec, after, request, now)
            self.store.commit_locked(
                campaign_fd,
                campaign_hash=spec.campaign_hash,
                operation_id=op,
                operation_kind="ISSUE",
                recorded_at=now,
                artifacts=(after, request, checkpoint, exhausted),
            )
            return request

    def pending(self, campaign_hash: str) -> HostedAgentRequest | None:
        return self.store.snapshot(campaign_hash).active_request

    def status(self, campaign_hash: str) -> HostedProtocolStatus:
        return self.project_status(self.store.snapshot(campaign_hash), self._clock())

    @staticmethod
    def project_status(state: HostedStoreSnapshot, now: datetime) -> HostedProtocolStatus:
        request = state.active_request
        projected = bool(
            request
            and request.expires_at <= now
            and state.accepted_receipt(request.content_hash) is None
        )
        status = "READY"
        last = state.requests[-1] if state.requests else None
        if request is not None:
            status = (
                "RESPONSE_ACCEPTED"
                if state.accepted_receipt(request.content_hash)
                else "WAITING_FOR_AGENT"
            )
            if status == "WAITING_FOR_AGENT" and (
                state.budget.used_unique_submissions
                >= state.spec.hosted_budget.max_unique_submissions
                or state.budget.request_submissions[request.transport_ordinal - 1].used_submissions
                >= state.spec.hosted_budget.max_submissions_per_request
            ):
                status = "EXHAUSTED"
        elif last is not None:
            terminal = state.terminal(last.content_hash)
            if terminal is not None:
                status = terminal.outcome
        if status in ("READY", "STEP_COMPLETED") and (
            state.budget.used_requests >= state.spec.hosted_budget.max_requests
            or state.budget.used_unique_submissions
            >= state.spec.hosted_budget.max_unique_submissions
        ):
            status = "EXHAUSTED"
        return HostedProtocolStatus(
            campaign_hash=state.spec.campaign_hash,
            hosted_spec_hash=state.spec.content_hash,
            request_hash=request.content_hash if request else last.content_hash if last else None,
            state=cast("LiteralStatus", status),
            projected_expiration=projected,
            budget_hash=state.budget.content_hash,
            used_requests=state.budget.used_requests,
            used_unique_submissions=state.budget.used_unique_submissions,
            journal_head_hash=state.journal_head_hash,
        )

    def read_response_frame(self, request_hash: str, stream: BinaryIO) -> bytes:
        """Read at most cap+1 bytes. Channel closes an oversized frame without draining."""
        campaign = self.store.locate_request(request_hash)
        request = self.store.snapshot(campaign).request(request_hash)
        return stream.read(request.max_response_bytes + 1)

    def submit(
        self,
        request_hash: str,
        response_bytes: bytes,
        authenticated_principal: str,
    ) -> HostedSubmissionReceipt:
        principal = _identity(authenticated_principal)
        campaign = self.store.locate_request(request_hash)
        with self.store.campaign_lock(campaign) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            state = self.store.snapshot_locked(campaign_fd)
            request = state.request(request_hash)
            complete = len(response_bytes) <= request.max_response_bytes
            observed = response_bytes[: request.max_response_bytes + 1]
            digest = sha256_bytes(observed)
            # This check intentionally precedes current cap, cancellation and clock checks.
            for original in state.receipts:
                if (
                    original.request_hash == request_hash
                    and original.complete == complete
                    and (
                        original.submission_bytes_hash
                        if complete
                        else original.observed_prefix_hash
                    )
                    == digest
                ):
                    return original
            before = state.budget
            request_count = before.request_submissions[request.transport_ordinal - 1]
            if before.used_unique_submissions >= state.spec.hosted_budget.max_unique_submissions:
                return next(
                    x for x in state.receipts if x.request_hash is None and x.outcome == "EXHAUSTED"
                )
            if (
                request_count.used_submissions
                >= state.spec.hosted_budget.max_submissions_per_request
            ):
                return next(
                    x
                    for x in state.receipts
                    if x.request_hash == request_hash and x.outcome == "EXHAUSTED"
                )
            now = self._clock()
            op = hosted_protocol_operation_id(campaign, "SUBMIT", (request_hash, complete, digest))
            after = HostedBudgetJournalFact(
                campaign_hash=campaign,
                hosted_spec_hash=state.spec.content_hash,
                operation_id=op,
                previous_hash=before.content_hash,
                used_requests=before.used_requests,
                used_unique_submissions=before.used_unique_submissions + 1,
                request_submissions=tuple(
                    HostedRequestSubmissionCount(
                        transport_ordinal=x.transport_ordinal,
                        used_submissions=x.used_submissions
                        + (x.transport_ordinal == request.transport_ordinal),
                    )
                    for x in before.request_submissions
                ),
                recorded_at=now,
            )
            terminal = state.terminal(request_hash)
            accepted = state.accepted_receipt(request_hash)
            response: HostedAgentResponse | SdkAgentResponse | None = None
            outcome = "REJECTED"
            reason = "FRAME_BYTE_CAP_EXCEEDED"
            extra: tuple[CanonicalContract, ...] = ()
            if accepted is not None:
                outcome, reason = "CONFLICT", "REQUEST_ALREADY_ACCEPTED"
            elif terminal is not None:
                reason = "REQUEST_" + terminal.outcome
            elif now >= request.expires_at:
                reason = "REQUEST_EXPIRED"
                extra = (
                    HostedRequestTerminalReceipt(
                        request_hash=request_hash,
                        campaign_hash=campaign,
                        outcome="EXPIRED",
                        reason="REQUEST_TTL_ELAPSED",
                        authenticated_principal="service",
                        recorded_at=now,
                    ),
                )
            elif complete:
                try:
                    if self._scan_submission is not None:
                        self._scan_submission(observed)
                    response = (
                        parse_sdk_response(observed, max_bytes=request.max_response_bytes)
                        if isinstance(state.spec, SdkCampaignSpec)
                        else parse_hosted_contract(
                            observed, HostedAgentResponse, max_bytes=request.max_response_bytes
                        )
                    )
                    _scan_safe(response.model_dump(mode="json"))
                    reason = self._response_reason(state.spec, request, response)
                    if reason == "TRANSPORT_ACCEPTED":
                        outcome = "ACCEPTED"
                except SecretArtifactRejected:
                    reason = "CREDENTIAL_LIKE_PAYLOAD"
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    reason = "SCHEMA_INVALID"
            exchange: HostedAgentExchange | None = None
            if outcome == "ACCEPTED" and response is not None:
                if isinstance(response, SdkAgentResponse):
                    exchange = SdkAgentExchange(
                        request_hash=request_hash,
                        response_hash=response.content_hash,
                        proposal_hash=response.proposal_hash,
                        authenticated_principal=principal,
                        host_observation_hash=response.manifest.content_hash,
                        manifest_hash=response.manifest.content_hash,
                        sdk_profile_hash=response.sdk_profile_hash,
                        raw_response_hash=response.raw_response_hash,
                    )
                    extra = (
                        *extra,
                        response.reservation,
                        response.reservation.run_spec,
                        response.manifest,
                        response,
                        exchange,
                    )
                else:
                    exchange = HostedAgentExchange(
                        request_hash=request_hash,
                        response_hash=response.content_hash,
                        proposal_hash=response.proposal_hash,
                        authenticated_principal=principal,
                        host_observation_hash=response.host_observation.content_hash,
                    )
                    extra = (*extra, response.host_observation, response, exchange)
            receipt = HostedSubmissionReceipt(
                campaign_hash=campaign,
                request_hash=request_hash,
                submission_bytes_hash=digest if complete else None,
                observed_prefix_hash=None if complete else digest,
                observed_bytes=len(observed),
                complete=complete,
                attempt_identity=request.attempt_identity,
                outcome=cast("LiteralOutcome", outcome),
                reason=reason,
                accepted_exchange_hash=exchange.content_hash if exchange else None,
                budget_before_hash=before.content_hash,
                budget_after_hash=after.content_hash,
                recorded_at=now,
                authenticated_principal=principal,
            )
            self.store.commit_locked(
                campaign_fd,
                campaign_hash=campaign,
                operation_id=op,
                operation_kind="SUBMIT",
                recorded_at=now,
                artifacts=(after, *extra, receipt),
            )
            return receipt

    @staticmethod
    def _response_reason(
        spec: HostedCampaignSpec,
        request: HostedAgentRequest,
        response: HostedAgentResponse | SdkAgentResponse,
    ) -> str:
        if isinstance(response, SdkAgentResponse):
            if not isinstance(spec, SdkCampaignSpec) or not isinstance(request, SdkAgentRequest):
                return "RESPONSE_BINDING_MISMATCH"
            from quantos.application.sdk_producer import SdkCampaignProducer

            try:
                published = SdkCampaignProducer(
                    Path(spec.sdk_profile.evidence_root)
                ).read_published(request, spec)
            except (ArtifactIntegrityError, OSError, ValueError):
                return "SDK_SOURCE_UNAVAILABLE"
            if published != response:
                return "SDK_SOURCE_PUBLICATION_MISMATCH"
        elif isinstance(spec, SdkCampaignSpec):
            return "RESPONSE_BINDING_MISMATCH"
        if (
            response.request_hash != request.content_hash
            or response.campaign_hash != request.campaign_hash
            or response.transport_ordinal != request.transport_ordinal
            or response.context_pack_hash != request.context_pack_hash
            or response.attempt_identity != request.attempt_identity
            or (
                isinstance(response, HostedAgentResponse)
                and response.host_observation.requested_configuration_hash
                != spec.requested_model_configuration_hash
            )
        ):
            return "RESPONSE_BINDING_MISMATCH"
        if len(response.proposal_json.encode("utf-8")) > request.max_proposal_bytes:
            return "PROPOSAL_BYTE_CAP_EXCEEDED"
        try:
            proposal: object = json.loads(response.proposal_json)
        except (ValueError, RecursionError):
            return "CANDIDATE_IDENTITY_UNAVAILABLE"
        if not isinstance(proposal, dict):
            return "CANDIDATE_IDENTITY_UNAVAILABLE"
        candidate_hash = cast(dict[str, object], proposal).get("candidate_hash")
        if candidate_hash not in {
            x.content_hash for x in request.business_request.candidate_options
        }:
            return "UNKNOWN_CANDIDATE"
        # Proposal schema/DSL/fingerprint are business admission, including SCHEMA_INVALID trials.
        return "TRANSPORT_ACCEPTED"

    def cancel(
        self,
        request_hash: str,
        authenticated_principal: str,
    ) -> HostedRequestTerminalReceipt:
        principal = _identity(authenticated_principal)
        campaign = self.store.locate_request(request_hash)
        with self.store.campaign_lock(campaign) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            state = self.store.snapshot_locked(campaign_fd)
            existing = state.terminal(request_hash)
            if existing is not None:
                return existing
            accepted = state.accepted_receipt(request_hash)
            outcome = "CANCEL_REJECTED" if accepted else "CANCELLED"
            previous = next(
                (
                    x
                    for x in state.terminals
                    if x.request_hash == request_hash and x.outcome == outcome
                ),
                None,
            )
            if previous is not None:
                return previous
            now = self._clock()
            receipt = HostedRequestTerminalReceipt(
                request_hash=request_hash,
                campaign_hash=campaign,
                outcome=cast("LiteralTerminal", outcome),
                reason="REQUEST_ALREADY_ACCEPTED" if accepted else "AUTHORIZED_CANCELLATION",
                authenticated_principal=principal,
                recorded_at=now,
            )
            self.store.commit_locked(
                campaign_fd,
                campaign_hash=campaign,
                operation_id=hosted_protocol_operation_id(campaign, "CANCEL", request_hash),
                operation_kind="TERMINATE",
                recorded_at=now,
                artifacts=(receipt,),
            )
            return receipt

    def resume(self, campaign_hash: str) -> HostedProtocolStatus:
        with self.store.campaign_lock(campaign_hash) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            state = self.store.snapshot_locked(campaign_fd)
            if self._verify_inputs is None:
                raise ArtifactIntegrityError("frozen input reverifier is required before resume")
            self._verify_inputs(state.spec)
            request = state.active_request
            now = self._clock()
            if (
                request
                and now >= request.expires_at
                and not state.accepted_receipt(request.content_hash)
            ):
                receipt = HostedRequestTerminalReceipt(
                    request_hash=request.content_hash,
                    campaign_hash=campaign_hash,
                    outcome="EXPIRED",
                    reason="REQUEST_TTL_ELAPSED",
                    authenticated_principal="service",
                    recorded_at=now,
                )
                self.store.commit_locked(
                    campaign_fd,
                    campaign_hash=campaign_hash,
                    operation_id=hosted_protocol_operation_id(
                        campaign_hash, "EXPIRE", request.content_hash
                    ),
                    operation_kind="TERMINATE",
                    recorded_at=now,
                    artifacts=(receipt,),
                )
                state = self.store.snapshot_locked(campaign_fd)
            return self.project_status(state, now)

    def accepted_exchange(
        self,
        request_hash: str,
    ) -> (
        tuple[HostedAgentRequest, HostedAgentResponse | SdkAgentResponse, HostedAgentExchange]
        | None
    ):
        state = self.store.snapshot(self.store.locate_request(request_hash))
        receipt = state.accepted_receipt(request_hash)
        if receipt is None or receipt.accepted_exchange_hash is None:
            return None
        exchange = parse_agent_exchange(
            state.artifacts[receipt.accepted_exchange_hash], max_bytes=16 * 1_048_576
        )
        request = state.request(request_hash)
        response = (
            parse_sdk_response(
                state.artifacts[exchange.response_hash], max_bytes=request.max_response_bytes
            )
            if isinstance(exchange, SdkAgentExchange)
            else state.artifact(exchange.response_hash, HostedAgentResponse)
        )
        if isinstance(response, SdkAgentResponse):
            if not isinstance(request, SdkAgentRequest) or not isinstance(
                state.spec, SdkCampaignSpec
            ):
                raise ArtifactIntegrityError("SDK exchange escaped successor profile")
            from quantos.application.sdk_producer import SdkCampaignProducer

            try:
                published = SdkCampaignProducer(
                    Path(state.spec.sdk_profile.evidence_root)
                ).read_published(request, state.spec)
            except (ArtifactIntegrityError, OSError, ValueError):
                raise ArtifactIntegrityError(
                    "SDK accepted exchange source publication unavailable"
                ) from None
            if published != response:
                raise ArtifactIntegrityError(
                    "SDK accepted exchange differs from source publication"
                )
            if (
                exchange.proposal_hash != response.proposal_hash
                or not isinstance(exchange, SdkAgentExchange)
                or exchange.manifest_hash != response.manifest.content_hash
                or exchange.raw_response_hash != response.raw_response_hash
                or exchange.sdk_profile_hash != response.sdk_profile_hash
            ):
                raise ArtifactIntegrityError("SDK exchange source binding differs")
        return request, response, exchange

    def publish_business(
        self,
        campaign_hash: str,
        *,
        operation_id: str,
        recorded_at: datetime,
        artifacts: tuple[CanonicalContract, ...],
        expected_journal_head_hash: str,
    ) -> HostedStoreSnapshot:
        """Internal CAS publication for frozen HM-04 intents/step receipts; no host exposure."""
        for artifact in artifacts:
            _scan_safe(artifact.model_dump(mode="json"))
        with self.store.campaign_lock(campaign_hash) as campaign_fd:
            self.store.recover_locked(campaign_fd)
            state = self.store.snapshot_locked(campaign_fd)
            existing = next(
                (
                    x
                    for x in state.journal
                    if x.operation_id == operation_id and x.phase == "INTENT"
                ),
                None,
            )
            if existing:
                if tuple(x.artifact_hash for x in existing.publications) != tuple(
                    x.content_hash for x in artifacts
                ):
                    raise ArtifactIntegrityError("business operation immutable payload conflict")
                return state
            if state.journal_head_hash != expected_journal_head_hash:
                raise ArtifactIntegrityError("hosted business publication compare-and-set conflict")
            self.store.commit_locked(
                campaign_fd,
                campaign_hash=campaign_hash,
                operation_id=operation_id,
                operation_kind="BUSINESS",
                recorded_at=recorded_at,
                artifacts=artifacts,
            )
            return self.store.snapshot_locked(campaign_fd)


from typing import Literal  # noqa: E402

LiteralStatus = Literal[
    "READY",
    "WAITING_FOR_AGENT",
    "RESPONSE_ACCEPTED",
    "STEP_COMPLETED",
    "CANCELLED",
    "EXPIRED",
    "EXHAUSTED",
]
LiteralOutcome = Literal["ACCEPTED", "REJECTED", "CONFLICT", "EXHAUSTED"]
LiteralTerminal = Literal["CANCELLED", "EXPIRED", "CANCEL_REJECTED", "STEP_COMPLETED"]


# Shared bounded credential scan used by the SDK producer before persistence.
scan_protocol_artifact = _scan_safe
