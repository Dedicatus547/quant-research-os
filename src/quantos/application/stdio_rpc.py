"""Narrow newline-delimited JSON-RPC adapter over the typed MCP facades."""

from __future__ import annotations

from collections.abc import Mapping
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quantos.application.proposal_mcp import ProposalMcpError, ProposalMcpService
from quantos.application.research_mcp import ResearchMcpError, ResearchMcpService
from quantos.application.security import (
    ResourceBudget,
    SecurityBoundaryError,
    load_bounded_json_object,
)
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.proposals import ProposalSubmissionRequest
from quantos.contracts.research_mcp import (
    DatasetLookupRequest,
    ExperimentExecutionRequest,
    ExperimentResolutionRequest,
    JobLookupRequest,
    RegistryGetRequest,
    RegistrySearchRequest,
    ValidationLookupRequest,
)
from quantos.contracts.status import ReasonCode
from quantos.contracts.transport import (
    JsonRpcToolDescriptor,
    JsonRpcToolSchemaManifest,
    JsonRpcTranscript,
    JsonRpcTranscriptEntry,
)


class _JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    jsonrpc: Literal["2.0"]
    id: int | str = Field(union_mode="left_to_right")
    method: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", max_length=100)
    params: dict[str, object]


_REQUEST_TYPES: Mapping[str, type[BaseModel]] = {
    "dataset.describe": DatasetLookupRequest,
    "dataset.fields": DatasetLookupRequest,
    "experiment.request_execution": ExperimentExecutionRequest,
    "experiment.resolve": ExperimentResolutionRequest,
    "job.get": JobLookupRequest,
    "proposal.submit_experiment": ProposalSubmissionRequest,
    "proposal.submit_factor": ProposalSubmissionRequest,
    "proposal.submit_hypothesis": ProposalSubmissionRequest,
    "registry.get": RegistryGetRequest,
    "registry.search": RegistrySearchRequest,
    "validation.get": ValidationLookupRequest,
}


def build_json_rpc_tool_schema() -> JsonRpcToolSchemaManifest:
    descriptors: list[JsonRpcToolDescriptor] = []
    for method, model in sorted(_REQUEST_TYPES.items()):
        schema = model.model_json_schema()
        descriptors.append(
            JsonRpcToolDescriptor(
                method=method,
                input_schema=schema,
                input_schema_hash=sha256_bytes(canonical_json_bytes(schema)),
            )
        )
    return JsonRpcToolSchemaManifest(tools=tuple(descriptors))


class StdioJsonRpcAdapter:
    """Validate one request envelope and dispatch only an existing typed capability."""

    def __init__(
        self,
        *,
        proposals: ProposalMcpService,
        research: ResearchMcpService,
        max_request_bytes: int = 262_144,
    ) -> None:
        if max_request_bytes < 1:
            raise ValueError("max_request_bytes must be positive")
        self._proposals = proposals
        self._research = research
        self._max_request_bytes = max_request_bytes
        self._budget = ResourceBudget(max_payload_bytes=max_request_bytes)
        self.tool_schema = build_json_rpc_tool_schema()
        self._entries: list[JsonRpcTranscriptEntry] = []

    @property
    def transcript(self) -> JsonRpcTranscript:
        return JsonRpcTranscript.create(
            tool_schema_hash=self.tool_schema.content_hash,
            entries=tuple(self._entries),
        )

    def handle_line(self, line: bytes) -> bytes:
        request_hash = sha256_bytes(line)
        request_id: int | str | None = None
        method = "invalid.request"
        reason: ReasonCode | None = None
        try:
            if not line or len(line) > self._max_request_bytes:
                raise _TransportError(
                    ReasonCode.RESOURCE_BUDGET_EXCEEDED,
                    "JSON-RPC request exceeds the transport byte budget",
                    -32600,
                )
            try:
                raw = load_bounded_json_object(line, budget=self._budget)
                request = _JsonRpcRequest.model_validate(raw)
            except SecurityBoundaryError as error:
                raise _TransportError(error.reason_code, str(error), -32600) from error
            except ValidationError as error:
                raise _TransportError(
                    ReasonCode.SCHEMA_INVALID, "invalid JSON-RPC request", -32600
                ) from error
            request_id = request.id
            method = request.method
            if method not in _REQUEST_TYPES:
                raise _TransportError(
                    ReasonCode.CAPABILITY_DENIED, "method is not allowlisted", -32601
                )
            params = canonical_json_bytes(request.params)
            result: CanonicalContract
            if method.startswith("proposal.submit_"):
                result = self._proposals.submit(method, params)
            else:
                result = self._research.call(method, params)
            response: dict[str, object] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result.canonical_payload(),
            }
        except (ProposalMcpError, ResearchMcpError) as error:
            reason = error.reason_code
            response = self._error_response(request_id, -32602, reason, str(error))
        except _TransportError as error:
            reason = error.reason_code
            response = self._error_response(request_id, error.code, reason, str(error))
        encoded = canonical_json_bytes(response)
        self._entries.append(
            JsonRpcTranscriptEntry(
                sequence=len(self._entries) + 1,
                method=method,
                request_hash=request_hash,
                response_hash=sha256_bytes(encoded),
                succeeded=reason is None,
                reason_code=reason,
            )
        )
        return encoded

    @staticmethod
    def _error_response(
        request_id: int | str | None,
        code: int,
        reason: ReasonCode,
        message: str,
    ) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
                "data": {"reason_code": reason.value},
            },
        }


class _TransportError(ValueError):
    def __init__(self, reason_code: ReasonCode, message: str, code: int) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.code = code


def serve_stdio(
    adapter: StdioJsonRpcAdapter,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
) -> None:
    """Serve newline-delimited JSON-RPC until an explicit input EOF."""

    for line in input_stream:
        output_stream.write(adapter.handle_line(line.rstrip(b"\r\n")) + b"\n")
        output_stream.flush()
