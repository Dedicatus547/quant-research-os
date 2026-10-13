"""Deterministic method-local proposal history; no scientific feedback or runtime calls."""

from __future__ import annotations

import json

from quantos.application.discovery_admission import capability_rejection
from quantos.application.enumeration import structural_expression_hash
from quantos.contracts.discovery import (
    DiscoveryDesignContract,
    GenerationRequest,
    GenerationReservation,
    GenerationResponse,
    SequentialGenerationHistory,
    SequentialHistoryEntry,
    SequentialPolicyContract,
)
from quantos.contracts.pit import SafeQlibExpressionSpec


def build_generation_history(
    design: DiscoveryDesignContract,
    request: GenerationRequest,
    policy: SequentialPolicyContract,
    reservations: tuple[GenerationReservation, ...],
    responses: tuple[GenerationResponse, ...],
) -> SequentialGenerationHistory:
    """Extract only AST/fingerprint/static status, binding the immutable originals."""
    if (
        request.design_hash != policy.design_hash
        or design.content_hash != policy.design_hash
        or request.content_hash not in policy.request_hashes
        or tuple(item.ordinal for item in reservations) != tuple(range(1, len(reservations) + 1))
        or any(item.request_hash != request.content_hash for item in reservations)
    ):
        raise ValueError("history originals escape the fixed policy or method")
    by_reservation = {item.reservation.content_hash: item for item in responses}
    if len(by_reservation) != len(responses) or not set(by_reservation).issubset(
        {item.content_hash for item in reservations}
    ):
        raise ValueError("history responses escape their exact reserved prefix")
    entries: list[SequentialHistoryEntry] = []
    seen: set[str] = set()
    for reservation in reservations:
        response = by_reservation.get(reservation.content_hash)
        expression = None
        structural = None
        if response is None:
            status, reason = "UNFINISHED", "NO_RESPONSE_CAPTURED"
        elif response.reservation != reservation:
            raise ValueError("history response reservation differs")
        elif response.failure_code is not None:
            status, reason = "FAILED", response.failure_code
        elif len(response.text.encode("utf-8")) > design.max_output_bytes_per_attempt:
            status, reason = "REJECTED", "OUTPUT_LIMIT"
        else:
            try:
                expression = SafeQlibExpressionSpec.model_validate(json.loads(response.text))
            except (ValueError, TypeError, RecursionError):
                status, reason = "PARSE_FAILED", "INVALID_EXPRESSION_JSON"
            else:
                structural = structural_expression_hash(expression)
                rejection = capability_rejection(design, expression)
                if rejection is not None:
                    status, reason = "REJECTED", rejection
                elif structural in seen:
                    status, reason = "DUPLICATE", "STRUCTURAL_DUPLICATE"
                else:
                    status, reason = "ADMITTED", "STATIC_CAPABILITY_ADMITTED"
                if rejection is None:
                    seen.add(structural)
        entries.append(
            SequentialHistoryEntry(
                reservation_hash=reservation.content_hash,
                ordinal=reservation.ordinal,
                response_hash=None if response is None else response.content_hash,
                status=status,
                reason=reason,
                expression=expression,
                structural_hash=structural,
            )
        )
    return SequentialGenerationHistory(
        policy_hash=policy.content_hash,
        request_hash=request.content_hash,
        method=request.method,
        entries=tuple(entries),
    )


def sequential_baseline(
    design: DiscoveryDesignContract, request: GenerationRequest, policy: SequentialPolicyContract
) -> tuple[str, ...]:
    """Use the typed successor coverage policy, preserving old baseline behavior."""
    from quantos.application.discovery_baselines import generate_sequential_baseline

    return generate_sequential_baseline(design, request, policy)
