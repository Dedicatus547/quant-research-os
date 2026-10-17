"""Small durable append-only successor journal, using existing file authority and locks."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from quantos.application.autonomous_execution import require_durable_execution_root
from quantos.application.hosted_protocol import scan_protocol_artifact
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.adaptive import AdaptiveEvent, AdaptiveResearchSpec
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.integrations.codex.sdk_adapter import contains_parent_secret

C = TypeVar("C", bound=CanonicalContract)


def _scan_view(value: Any) -> Any:
    """Explicit successor scan view; never changes the retained original bytes.

    The frozen scanner treats *_hash as SHA256 and token-named fields as secrets.
    Only validated contract fields may project Git SHA1 and numeric usage here.
    """
    if isinstance(value, list):
        return [_scan_view(x) for x in cast(list[Any], value)]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = dict(cast(dict[str, Any], value))
    schema = result.get("schema_version")
    if schema in {"autonomous-execution-bindings/v1", "autonomous-execution-request/v2"}:
        from quantos.contracts.autonomous import (
            AutonomousExecutionBindings,
            AutonomousExecutionRequest,
        )

        cls = (
            AutonomousExecutionRequest
            if schema == "autonomous-execution-request/v2"
            else AutonomousExecutionBindings
        )
        cls.model_validate(result)
        commit = result.pop("code_commit_hash")
        if not isinstance(commit, str) or re.fullmatch("[0-9a-f]{40}", commit) is None:
            raise ArtifactIntegrityError("typed Git identity invalid")
        result["code_commit_identity"] = commit
    if schema == "adaptive-sdk-profile/v1":
        from quantos.contracts.adaptive import AdaptiveSdkProfile

        AdaptiveSdkProfile.model_validate(result)
        for name in ("max_input_tokens", "max_output_tokens"):
            scalar = result.pop(name)
            if type(scalar) is not int or scalar <= 0:
                raise ArtifactIntegrityError("typed token bound invalid")
            result[name.replace("tokens", "count")] = scalar
    if schema == "harness-execution-request/v2":
        from quantos.contracts.harness import HarnessExecutionRequest

        HarnessExecutionRequest.model_validate(result)
        if result.get("output_schema_json"):
            result["output_schema_json"] = "schema-fragment " + result["output_schema_json"]
    if schema == "adaptive-sdk-response/v1":
        from quantos.contracts.agent import AgentUsage

        result["usage"] = AgentUsage.model_validate(result["usage"]).model_dump(mode="json")
    if schema == "adaptive-feedback/v1":
        from quantos.contracts.adaptive_feedback import AdaptiveFeedback

        AdaptiveFeedback.model_validate(result)
        # This contract explicitly preserves unavailable usage as null.
        result["sdk_usage_observation"] = result.pop("token_usage")
    return {key: _scan_view(item) for key, item in result.items()}


def save(path: Path, value: CanonicalContract | dict[str, Any] | bytes) -> str:
    data = (
        value
        if isinstance(value, bytes)
        else value.canonical_bytes()
        if isinstance(value, CanonicalContract)
        else canonical_json_bytes(value)
    )
    if contains_parent_secret(data):
        raise ArtifactIntegrityError("forbidden parent value in adaptive artifact")
    text = data.decode("utf-8")
    if path.name == "schema.json":
        from quantos.application.adaptive_sdk import decision_schema

        if data != decision_schema():
            raise ArtifactIntegrityError("adaptive schema bytes differ")
        scan_protocol_artifact("schema-fragment " + text)
    else:
        try:
            view = json.loads(text)
        except ValueError:
            view = text
        scan_protocol_artifact(_scan_view(view))
    atomic_write_bytes(path, data)
    return sha256_bytes(data)


def read(path: Path, cap: int = 1 << 20) -> bytes:
    with opened_directory(path.parent) as fd:
        return read_regular_bytes_at(fd, path.name, max_bytes=cap)


def contract(path: Path, cls: type[C]) -> C:
    data = read(path)
    value = cls.model_validate_json(data)
    if value.canonical_bytes() != data:
        raise ArtifactIntegrityError("adaptive artifact is not canonical")
    return value


class AdaptiveStore:
    def __init__(self, spec: AdaptiveResearchSpec):
        self.spec = spec
        self.root = Path(spec.output_root)
        require_durable_execution_root(self.root)
        if not self.root.is_absolute() or self.root.is_symlink():
            raise ValueError("absolute durable adaptive root required")

    def initialize(self) -> None:
        save(self.root / "spec.json", self.spec)

    def put(self, value: CanonicalContract | dict[str, Any]) -> str:
        data = (
            value.canonical_bytes()
            if isinstance(value, CanonicalContract)
            else canonical_json_bytes(value)
        )
        digest = sha256_bytes(data)
        save(self.root / "objects" / f"{digest}.json", data)
        return digest

    def get(self, digest: str, cls: type[C]) -> C:
        data = read(self.root / "objects" / f"{digest}.json")
        if sha256_bytes(data) != digest:
            raise ArtifactIntegrityError("adaptive content identity differs")
        result = cls.model_validate_json(data)
        if result.canonical_bytes() != data:
            raise ArtifactIntegrityError("adaptive object is not canonical")
        return result

    def events(self) -> tuple[AdaptiveEvent, ...]:
        events: list[AdaptiveEvent] = []
        previous = None
        for index, path in enumerate(sorted((self.root / "events").glob("*.json")), 1):
            event = contract(path, AdaptiveEvent)
            if (
                path.name != f"{index:06d}.json"
                or event.ordinal != index
                or event.task_hash != self.spec.content_hash
                or event.previous_hash != previous
            ):
                raise ArtifactIntegrityError("adaptive event chain differs")
            previous = event.content_hash
            events.append(event)
        return tuple(events)

    def append(
        self, kind: Any, reference_hash: str, now: datetime, units: int = 0
    ) -> AdaptiveEvent:
        events = self.events()
        event = AdaptiveEvent(
            task_hash=self.spec.content_hash,
            ordinal=len(events) + 1,
            previous_hash=events[-1].content_hash if events else None,
            kind=kind,
            reference_hash=reference_hash,
            units=units,
            occurred_at=now,
        )
        save(self.root / "events" / f"{event.ordinal:06d}.json", event)
        return event
