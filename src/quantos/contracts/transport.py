"""Hash-bound contracts for the narrow stdio JSON-RPC transport."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from pydantic import Field, PositiveInt, field_validator, model_validator

from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.refs import SHA256_PATTERN
from quantos.contracts.status import ReasonCode


class JsonRpcToolDescriptor(CanonicalContract):
    schema_version: Literal["json-rpc-tool-descriptor/v1"] = "json-rpc-tool-descriptor/v1"
    method: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    input_schema: dict[str, object]
    input_schema_hash: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def schema_hash_matches(self) -> Self:
        if self.input_schema_hash != sha256_bytes(canonical_json_bytes(self.input_schema)):
            raise ValueError("JSON-RPC input schema hash does not match schema")
        return self


class JsonRpcToolSchemaManifest(CanonicalContract):
    schema_version: Literal["json-rpc-tool-schema-manifest/v1"] = "json-rpc-tool-schema-manifest/v1"
    tools: tuple[JsonRpcToolDescriptor, ...]

    @field_validator("tools")
    @classmethod
    def tools_are_nonempty_sorted(
        cls, value: tuple[JsonRpcToolDescriptor, ...]
    ) -> tuple[JsonRpcToolDescriptor, ...]:
        methods = [item.method for item in value]
        if not methods or methods != sorted(set(methods)):
            raise ValueError("JSON-RPC tools must be nonempty, sorted, and unique")
        return value


class JsonRpcTranscriptEntry(CanonicalContract):
    schema_version: Literal["json-rpc-transcript-entry/v1"] = "json-rpc-transcript-entry/v1"
    sequence: PositiveInt
    method: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    request_hash: str = Field(pattern=SHA256_PATTERN)
    response_hash: str = Field(pattern=SHA256_PATTERN)
    succeeded: bool
    reason_code: ReasonCode | None = None

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> Self:
        if self.succeeded == (self.reason_code is not None):
            raise ValueError("JSON-RPC transcript outcome and reason code disagree")
        return self


class JsonRpcTranscript(CanonicalContract):
    schema_version: Literal["json-rpc-transcript/v1"] = "json-rpc-transcript/v1"
    hash_exclude_fields: ClassVar[frozenset[str]] = frozenset({"transcript_hash"})

    transcript_hash: str = Field(pattern=SHA256_PATTERN)
    tool_schema_hash: str = Field(pattern=SHA256_PATTERN)
    entries: tuple[JsonRpcTranscriptEntry, ...]

    @model_validator(mode="after")
    def sequence_and_hash_are_valid(self) -> Self:
        if [item.sequence for item in self.entries] != list(range(1, len(self.entries) + 1)):
            raise ValueError("JSON-RPC transcript sequence is not contiguous")
        if self.transcript_hash != self.content_hash:
            raise ValueError("JSON-RPC transcript hash does not match content")
        return self

    @classmethod
    def create(
        cls,
        *,
        tool_schema_hash: str,
        entries: tuple[JsonRpcTranscriptEntry, ...],
    ) -> Self:
        payload = {
            "schema_version": "json-rpc-transcript/v1",
            "tool_schema_hash": tool_schema_hash,
            "entries": entries,
        }
        return cls(
            transcript_hash=sha256_bytes(canonical_json_bytes(payload)),
            tool_schema_hash=tool_schema_hash,
            entries=entries,
        )
