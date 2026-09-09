"""Read-only typed Agent boundary over verified immutable Evidence Stores."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from quantos.application.security import AgentRequestBoundary, SecurityBoundaryError
from quantos.contracts.agent import AgentCapability, AgentCapabilityPolicy
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import (
    EvidenceAgentView,
    EvidenceCitation,
    EvidenceCitationRequest,
    EvidenceGetRequest,
    EvidenceRecord,
    EvidenceTextSpan,
    ExtractedTextArtifact,
)
from quantos.contracts.status import ReasonCode


class EvidenceMcpError(ValueError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class EvidenceBinding:
    evidence: EvidenceRecord
    extracted_text: ExtractedTextArtifact
    text: str

    def __post_init__(self) -> None:
        if (
            self.extracted_text.evidence_hash != self.evidence.content_hash
            or sha256_bytes(self.text.encode("utf-8")) != self.extracted_text.text_hash
            or len(self.text) != self.extracted_text.character_count
        ):
            raise ValueError("Evidence MCP binding hashes disagree")


def evidence_mcp_policy(*, max_requests: int = 3) -> AgentCapabilityPolicy:
    return AgentCapabilityPolicy(
        policy_id="p13-evidence-mcp-v1",
        capabilities=(AgentCapability.EVIDENCE_CITE, AgentCapability.EVIDENCE_GET),
        max_payload_bytes=65_536,
        max_payload_depth=16,
        max_payload_nodes=5_000,
        max_string_bytes=32_768,
        max_requests=max_requests,
    )


def evidence_mcp_tools() -> tuple[dict[str, object], ...]:
    """Return the exact MCP tool surface advertised to the extraction Agent."""

    requests = (
        (
            "evidence_cite",
            "Build one exact citation after matching the requested frozen text range.",
            EvidenceCitationRequest,
        ),
        (
            "evidence_get",
            "Read one admitted EvidenceRecord and its path-free extracted-text spans.",
            EvidenceGetRequest,
        ),
    )
    return tuple(
        {
            "name": name,
            "description": description,
            "inputSchema": request_type.model_json_schema(),
        }
        for name, description, request_type in requests
    )


def evidence_mcp_tool_schema_hash() -> str:
    return sha256_bytes(canonical_json_bytes(evidence_mcp_tools()))


def _text_spans(binding: EvidenceBinding) -> tuple[EvidenceTextSpan, ...]:
    spans: list[EvidenceTextSpan] = []
    offset = 0
    page = 1
    for raw_line in binding.text.splitlines(keepends=True):
        text = raw_line.rstrip("\r\n")
        if text:
            spans.append(
                EvidenceTextSpan(
                    page=page,
                    char_start=offset,
                    char_end=offset + len(text),
                    text=text,
                    text_hash=sha256_bytes(text.encode("utf-8")),
                )
            )
        elif raw_line:
            page += 1
        offset += len(raw_line)
    if offset < len(binding.text):
        text = binding.text[offset:]
        spans.append(
            EvidenceTextSpan(
                page=page,
                char_start=offset,
                char_end=len(binding.text),
                text=text,
                text_hash=sha256_bytes(text.encode("utf-8")),
            )
        )
    if binding.extracted_text.page_count is not None and page != binding.extracted_text.page_count:
        raise EvidenceMcpError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "extracted text page separators disagree with its frozen page count",
        )
    return tuple(spans)


class EvidenceMcpService:
    """Expose only verified evidence content and exact citation construction."""

    def __init__(
        self,
        bindings: Mapping[str, EvidenceBinding],
        policy: AgentCapabilityPolicy | None = None,
    ) -> None:
        self._bindings = dict(bindings)
        self._boundary = AgentRequestBoundary.from_policy(policy or evidence_mcp_policy())
        if not self._bindings or any(
            digest != binding.evidence.content_hash for digest, binding in self._bindings.items()
        ):
            raise ValueError("Evidence MCP catalog keys must bind EvidenceRecord hashes")

    @property
    def audit_decisions(self):
        return self._boundary.audit_decisions

    def call(self, capability: str, payload: bytes) -> CanonicalContract:
        handlers: dict[str, Callable[[dict[str, object]], CanonicalContract]] = {
            AgentCapability.EVIDENCE_CITE.value: self._cite,
            AgentCapability.EVIDENCE_GET.value: self._get,
        }
        try:
            accepted = self._boundary.accept(capability, payload)
            handler = handlers.get(capability)
            if handler is None:
                raise EvidenceMcpError(ReasonCode.CAPABILITY_DENIED, "capability is not mapped")
            return handler(accepted)
        except EvidenceMcpError:
            raise
        except SecurityBoundaryError as error:
            raise EvidenceMcpError(error.reason_code, str(error)) from error
        except ValidationError as error:
            raise EvidenceMcpError(
                ReasonCode.SCHEMA_INVALID, "Evidence MCP request is invalid"
            ) from error

    def _binding(self, evidence_hash: str) -> EvidenceBinding:
        binding = self._bindings.get(evidence_hash)
        if binding is None:
            raise EvidenceMcpError(ReasonCode.SOURCE_INCOMPLETE, "evidence is not admitted")
        return binding

    def _get(self, payload: dict[str, object]) -> EvidenceAgentView:
        request = EvidenceGetRequest.model_validate(payload)
        binding = self._binding(request.evidence_hash)
        return EvidenceAgentView(
            evidence=binding.evidence,
            extracted_text=binding.extracted_text,
            spans=_text_spans(binding),
        )

    def _cite(self, payload: dict[str, object]) -> EvidenceCitation:
        request = EvidenceCitationRequest.model_validate(payload)
        binding = self._binding(request.evidence_hash)
        if (
            request.extracted_text_hash != binding.extracted_text.content_hash
            or request.char_end > len(binding.text)
            or binding.text[request.char_start : request.char_end] != request.expected_text
            or (
                binding.extracted_text.page_count is not None
                and request.page > binding.extracted_text.page_count
            )
        ):
            raise EvidenceMcpError(
                ReasonCode.ARTIFACT_CORRUPTED,
                "citation request does not match the frozen extracted text",
            )
        return EvidenceCitation(
            evidence_hash=binding.evidence.content_hash,
            extracted_text_hash=binding.extracted_text.content_hash,
            page=request.page,
            char_start=request.char_start,
            char_end=request.char_end,
            cited_text_hash=sha256_bytes(request.expected_text.encode("utf-8")),
        )
