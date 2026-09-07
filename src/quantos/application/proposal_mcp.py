"""Typed proposal MCP application boundary with immutable idempotent receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from quantos.application.security import AgentRequestBoundary, SecurityBoundaryError
from quantos.artifacts.store import (
    ArtifactConflictError,
    atomic_write_bytes,
    exclusive_directory_lock,
)
from quantos.contracts.agent import AgentCapability, AgentCapabilityPolicy
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.proposals import (
    ProposalSubmissionReceipt,
    ProposalSubmissionRequest,
    SubmittableProposalKind,
)
from quantos.contracts.status import ReasonCode

_CAPABILITY_KINDS = {
    AgentCapability.PROPOSAL_SUBMIT_HYPOTHESIS.value: SubmittableProposalKind.HYPOTHESIS,
    AgentCapability.PROPOSAL_SUBMIT_FACTOR.value: SubmittableProposalKind.FACTOR,
    AgentCapability.PROPOSAL_SUBMIT_EXPERIMENT.value: SubmittableProposalKind.EXPERIMENT,
}


class ProposalMcpError(ValueError):
    """A typed proposal request was denied before reaching deterministic services."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def proposal_mcp_policy(*, max_requests: int = 32) -> AgentCapabilityPolicy:
    return AgentCapabilityPolicy(
        policy_id="p11-proposal-mcp-v1",
        capabilities=tuple(
            sorted(
                (
                    AgentCapability.PROPOSAL_SUBMIT_EXPERIMENT,
                    AgentCapability.PROPOSAL_SUBMIT_FACTOR,
                    AgentCapability.PROPOSAL_SUBMIT_HYPOTHESIS,
                ),
                key=str,
            )
        ),
        max_payload_bytes=262_144,
        max_payload_depth=24,
        max_payload_nodes=10_000,
        max_string_bytes=65_536,
        max_requests=max_requests,
    )


class ProposalMcpService:
    """Store proposals as proposals; never execute, validate, or mutate Registry state."""

    def __init__(self, root: Path, policy: AgentCapabilityPolicy | None = None) -> None:
        self._root = root
        self._boundary = AgentRequestBoundary.from_policy(policy or proposal_mcp_policy())

    @property
    def audit_decisions(self):  # return type is inherited from the P8 boundary
        return self._boundary.audit_decisions

    def submit(self, capability: str, payload: bytes) -> ProposalSubmissionReceipt:
        try:
            accepted = self._boundary.accept(capability, payload)
            request = ProposalSubmissionRequest.model_validate(accepted)
        except SecurityBoundaryError as error:
            raise ProposalMcpError(error.reason_code, str(error)) from error
        except ValidationError as error:
            raise ProposalMcpError(
                ReasonCode.SCHEMA_INVALID, "proposal request is invalid"
            ) from error
        expected_kind = _CAPABILITY_KINDS.get(capability)
        if expected_kind is None or request.proposal_kind is not expected_kind:
            raise ProposalMcpError(
                ReasonCode.CAPABILITY_DENIED,
                "proposal capability and typed proposal kind disagree",
            )
        request_hash = sha256_bytes(canonical_json_bytes(request))
        receipt = ProposalSubmissionReceipt(
            idempotency_key=request.idempotency_key,
            capability=cast(
                Literal[
                    "proposal.submit_hypothesis",
                    "proposal.submit_factor",
                    "proposal.submit_experiment",
                ],
                capability,
            ),
            request_hash=request_hash,
            proposal_kind=request.proposal_kind,
            proposal_hash=request.proposal.content_hash,
            agent_run_hash=request.agent_run_hash,
            campaign_hash=request.campaign_hash,
            budget_hash=request.budget_hash,
            input_hashes=request.input_hashes,
        )
        self._publish(request.proposal, receipt)
        return receipt

    def _publish(self, proposal: CanonicalContract, receipt: ProposalSubmissionReceipt) -> None:
        proposal_path = (
            self._root
            / "proposals"
            / receipt.proposal_kind.value
            / f"sha256-{receipt.proposal_hash}.json"
        )
        receipt_path = self._root / "idempotency" / f"{receipt.idempotency_key}.json"
        with exclusive_directory_lock(self._root):
            if receipt_path.exists():
                try:
                    existing = ProposalSubmissionReceipt.model_validate_json(
                        receipt_path.read_bytes()
                    )
                except (OSError, ValidationError) as error:
                    raise ProposalMcpError(
                        ReasonCode.ARTIFACT_CORRUPTED,
                        "existing proposal receipt is invalid",
                    ) from error
                if existing != receipt:
                    raise ProposalMcpError(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "idempotency key is already bound to another request",
                    )
                return
            try:
                atomic_write_bytes(proposal_path, proposal.canonical_bytes())
                atomic_write_bytes(receipt_path, receipt.canonical_bytes())
            except ArtifactConflictError as error:
                raise ProposalMcpError(
                    ReasonCode.DUPLICATE_ID_CONFLICT,
                    "immutable proposal publication conflicted",
                ) from error

    def read_receipt(self, idempotency_key: str) -> ProposalSubmissionReceipt:
        if len(idempotency_key) != 64 or any(
            character not in "0123456789abcdef" for character in idempotency_key
        ):
            raise ProposalMcpError(ReasonCode.SCHEMA_INVALID, "idempotency key is invalid")
        path = self._root / "idempotency" / f"{idempotency_key}.json"
        try:
            return ProposalSubmissionReceipt.model_validate_json(path.read_bytes())
        except FileNotFoundError as error:
            raise ProposalMcpError(
                ReasonCode.SOURCE_INCOMPLETE, "proposal receipt does not exist"
            ) from error
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            raise ProposalMcpError(
                ReasonCode.ARTIFACT_CORRUPTED, "proposal receipt is invalid"
            ) from error
