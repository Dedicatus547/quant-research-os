"""Read-only negative submission accounting, without awarding scenario qualification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted import (
    HostedAgentResponse,
    HostedBudgetJournalFact,
    HostedSubmissionReceipt,
    parse_hosted_contract,
)
from quantos.contracts.hosted_qualification import HostedQualificationFile
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    verify_protocol_root,
)
from quantos.security import SecretArtifactRejected, validate_secret_free

NegativeSubmissionKind = Literal[
    "campaign_hash",
    "transport_ordinal",
    "context_pack_hash",
    "request_hash",
    "attempt_identity",
    "expired",
    "cancelled",
    "conflict",
    "seen_bytes",
    "schema_invalid",
    "unknown_candidate",
    "oversized",
    "credential_like",
]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HostedQualificationError(message)


def verify_negative_submission_transition(
    before_root: Path,
    after_root: Path,
    *,
    campaign_hash: str,
    request_hash: str,
    response_bytes: bytes,
    receipt_hash: str,
    kind: NegativeSubmissionKind,
) -> tuple[str, ...]:
    """Reconcile original snapshots and bytes; process/source proof is a separate gate.

    This routine never executes or repairs authority. A producer's response reason,
    budget counters, success field or claimed unchanged business root is insufficient.
    Credential-like fixtures must be explicitly synthetic scanner inputs. Callers
    must never retain them as raw or reversible artifacts or pass real credentials.
    """
    checked = set(verify_protocol_root(before_root / "protocol", campaign_hash))
    checked.update(verify_protocol_root(after_root / "protocol", campaign_hash))
    before = HostedProtocolStore(before_root / "protocol").snapshot(campaign_hash, recover=False)
    after = HostedProtocolStore(after_root / "protocol").snapshot(campaign_hash, recover=False)
    _require(before.spec == after.spec, "negative submission changed frozen spec")
    _require(before.requests == after.requests, "negative submission changed requests")
    request = before.request(request_hash)
    receipt = after.artifact(receipt_hash, HostedSubmissionReceipt)
    observed = response_bytes[: request.max_response_bytes + 1]
    digest = sha256_bytes(observed)
    complete_frame = len(response_bytes) <= request.max_response_bytes
    _require(
        receipt.request_hash == request_hash
        and receipt.campaign_hash == campaign_hash
        and receipt.attempt_identity == request.attempt_identity
        and receipt.complete == complete_frame
        and receipt.observed_bytes == len(observed)
        and receipt.submission_bytes_hash == (digest if complete_frame else None)
        and receipt.observed_prefix_hash == (None if complete_frame else digest),
        "negative submission bytes and receipt differ",
    )
    before_raw, after_raw = raw_inventory(before_root), raw_inventory(after_root)
    business_before = tuple(
        item for item in before_raw.files if not item.logical_path.startswith("protocol/")
    )
    business_after = tuple(
        item for item in after_raw.files if not item.logical_path.startswith("protocol/")
    )
    _require(
        business_before == business_after, "negative submission mutated deterministic authority"
    )
    checked.update((digest, receipt.content_hash, before_raw.content_hash, after_raw.content_hash))
    if kind == "seen_bytes":
        _require(receipt_hash in before.artifacts, "seen submission has no original receipt")
        _require(before_raw == after_raw, "seen bytes were charged or published again")
        _require(
            before.artifact(receipt_hash, HostedSubmissionReceipt) == receipt,
            "original receipt changed",
        )
        return tuple(sorted(checked))
    _require(
        receipt_hash not in before.artifacts
        and after.journal[: len(before.journal)] == before.journal
        and len(after.journal) == len(before.journal) + 2,
        "negative submission lacks exactly one new journal operation",
    )
    intent, complete = after.journal[-2:]
    _require(
        intent.operation_kind == complete.operation_kind == "SUBMIT"
        and intent.recorded_at == complete.recorded_at == receipt.recorded_at,
        "negative submission operation and receipt differ",
    )
    expected_files = {item.logical_path: item for item in before_raw.files}
    for logical_path, data in (
        *(
            (
                f"protocol/campaigns/{campaign_hash}/objects/{publication.artifact_hash}.json",
                publication.canonical_json.encode("utf-8"),
            )
            for publication in intent.publications
        ),
        *(
            (
                f"protocol/campaigns/{campaign_hash}/journal/{entry.sequence:08d}-{entry.content_hash}.json",
                entry.canonical_bytes(),
            )
            for entry in (intent, complete)
        ),
    ):
        file = HostedQualificationFile(
            logical_path=logical_path, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        _require(
            expected_files.get(logical_path, file) == file,
            "negative submission overwrote original raw evidence",
        )
        expected_files[logical_path] = file
    _require(
        expected_files == {item.logical_path: item for item in after_raw.files},
        "negative submission raw file delta differs from exact journal publications",
    )
    _require(
        all(after.artifacts.get(digest) == raw for digest, raw in before.artifacts.items())
        and set(after.artifacts) - set(before.artifacts)
        == {publication.artifact_hash for publication in intent.publications},
        "negative submission changed an original artifact or added unrelated authority",
    )
    _require(
        after.receipts == (*before.receipts, receipt)
        and after.budget.content_hash == receipt.budget_after_hash
        and before.budget.content_hash == receipt.budget_before_hash,
        "negative submission receipt/accounting chronology differs",
    )
    budget = after.artifact(receipt.budget_after_hash, HostedBudgetJournalFact)
    _require(
        budget.previous_hash == before.budget.content_hash
        and budget.operation_id == intent.operation_id
        and budget.recorded_at == receipt.recorded_at
        and budget.used_requests == before.budget.used_requests
        and budget.used_unique_submissions == before.budget.used_unique_submissions + 1
        and len(budget.request_submissions) == len(before.budget.request_submissions)
        and all(
            current.transport_ordinal == previous.transport_ordinal
            and current.used_submissions
            == previous.used_submissions
            + int(previous.transport_ordinal == request.transport_ordinal)
            for previous, current in zip(
                before.budget.request_submissions, budget.request_submissions, strict=True
            )
        ),
        "negative submission did not charge exactly one bounded reservation",
    )
    accepted = before.accepted_receipt(request_hash)
    _require(
        after.accepted_receipt(request_hash) == accepted, "negative submission replaced acceptance"
    )
    if kind == "conflict":
        _require(accepted is not None, "conflict has no original acceptance")
        assert accepted is not None
        _require(
            accepted.submission_bytes_hash != digest
            and receipt.outcome == "CONFLICT"
            and receipt.reason == "REQUEST_ALREADY_ACCEPTED",
            "conflict did not preserve distinct original response bytes",
        )
    else:
        _require(
            accepted is None and receipt.outcome == "REJECTED", "negative response was accepted"
        )
        if kind == "expired":
            _require(
                receipt.recorded_at >= request.expires_at,
                "expiry rejection occurred before frozen TTL",
            )
            terminal = after.terminal(request_hash)
            _require(
                terminal is not None and terminal.outcome == "EXPIRED", "expiry terminal is absent"
            )
            _require(receipt.reason == "REQUEST_EXPIRED", "expiry rejection reason differs")
        elif kind == "cancelled":
            terminal = before.terminal(request_hash)
            _require(
                terminal is not None and terminal.outcome == "CANCELLED",
                "cancelled request was not terminated",
            )
            _require(receipt.reason == "REQUEST_CANCELLED", "cancellation rejection reason differs")
        elif kind in ("schema_invalid", "unknown_candidate", "oversized", "credential_like"):
            _require(
                receipt.recorded_at < request.expires_at and before.terminal(request_hash) is None,
                "bounded rejection borrowed an expired or cancelled request",
            )
            if kind == "oversized":
                _require(
                    not complete_frame and receipt.reason == "FRAME_BYTE_CAP_EXCEEDED",
                    "oversized rejection lacks a bounded incomplete prefix",
                )
            else:
                _require(complete_frame, "complete rejection has an oversized frame")
                if kind == "schema_invalid":
                    invalid = False
                    try:
                        parse_hosted_contract(
                            response_bytes,
                            HostedAgentResponse,
                            max_bytes=request.max_response_bytes,
                        )
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        invalid = True
                    _require(
                        invalid and receipt.reason == "SCHEMA_INVALID",
                        "schema rejection contains a valid canonical response",
                    )
                else:
                    response = parse_hosted_contract(
                        response_bytes, HostedAgentResponse, max_bytes=request.max_response_bytes
                    )
                    _require(
                        response.campaign_hash == request.campaign_hash
                        and response.transport_ordinal == request.transport_ordinal
                        and response.context_pack_hash == request.context_pack_hash
                        and response.request_hash == request_hash
                        and response.attempt_identity == request.attempt_identity
                        and response.host_observation.requested_configuration_hash
                        == before.spec.requested_model_configuration_hash,
                        "admission rejection borrowed a wrong binding",
                    )
                    proposal: object = json.loads(response.proposal_json)
                    if kind == "unknown_candidate":
                        _require(
                            isinstance(proposal, dict)
                            and cast(dict[str, object], proposal).get("candidate_hash")
                            not in {
                                candidate.content_hash
                                for candidate in request.business_request.candidate_options
                            }
                            and receipt.reason == "UNKNOWN_CANDIDATE",
                            "unknown-candidate rejection contains an allowed candidate",
                        )
                    else:
                        unsafe = False
                        try:
                            validate_secret_free(proposal, file_name="negative-proposal.json")
                        except SecretArtifactRejected:
                            unsafe = True
                        _require(
                            unsafe and receipt.reason == "CREDENTIAL_LIKE_PAYLOAD",
                            "credential rejection contains no credential-like proposal",
                        )
        else:
            _require(
                kind
                in (
                    "campaign_hash",
                    "transport_ordinal",
                    "context_pack_hash",
                    "request_hash",
                    "attempt_identity",
                )
                and receipt.recorded_at < request.expires_at
                and before.terminal(request_hash) is None
                and receipt.reason == "RESPONSE_BINDING_MISMATCH",
                "binding rejection context or reason differs",
            )
            response = parse_hosted_contract(
                response_bytes, HostedAgentResponse, max_bytes=request.max_response_bytes
            )
            bindings = {
                "campaign_hash": request.campaign_hash,
                "transport_ordinal": request.transport_ordinal,
                "context_pack_hash": request.context_pack_hash,
                "request_hash": request.content_hash,
                "attempt_identity": request.attempt_identity,
            }
            _require(
                {
                    field
                    for field, expected in bindings.items()
                    if getattr(response, field) != expected
                }
                == {kind}
                and response.host_observation.requested_configuration_hash
                == before.spec.requested_model_configuration_hash,
                "response did not isolate the designated binding error",
            )
    _require(
        receipt.accepted_exchange_hash is None, "negative submission published an accepted exchange"
    )
    before_terminal = before.terminal(request_hash)
    _require(
        after.terminals == before.terminals
        or (
            kind == "expired"
            and before_terminal is None
            and len(after.terminals) == len(before.terminals) + 1
            and after.terminals[:-1] == before.terminals
            and after.terminals[-1].recorded_at == receipt.recorded_at
            and after.terminals[-1].authenticated_principal == "service"
        ),
        "negative submission altered unrelated terminals",
    )
    _require(
        {publication.artifact_hash for publication in intent.publications}
        == {budget.content_hash, receipt_hash}
        | ({after.terminals[-1].content_hash} if after.terminals != before.terminals else set()),
        "negative submission contains unrelated publications",
    )
    return tuple(sorted(checked))
