"""Append-only Research Ledger persistence and deterministic lexical retrieval."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Never, TypeVar
from uuid import UUID, uuid5

from quantos.artifacts.store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    atomic_write_bytes,
    exclusive_directory_lock,
    regular_tree_files,
    sha256_file,
)
from quantos.contracts.agent import AgentRole, AgentRunManifest, AgentRunSpec
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.ledger import (
    LedgerAssertionAuthority,
    LedgerObjectAccess,
    ResearchContextAgentBinding,
    ResearchContextBudgetPolicy,
    ResearchContextItem,
    ResearchContextPack,
    ResearchLedgerAccessScope,
    ResearchLedgerEventV2,
    ResearchLedgerIndex,
    ResearchLedgerIndexEntry,
    ResearchLedgerNodeKind,
    ResearchLedgerObjectRef,
    ResearchLedgerSearchHit,
    ResearchLedgerSearchPolicy,
    ResearchLedgerSearchRequest,
    ResearchLedgerSearchResult,
    ResearchLedgerSnapshot,
    ResearchLedgerTermFrequency,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode

_EVENT_NAMESPACE = UUID("90c2ea0f-42ee-5bda-abe5-847833e42720")
_TOKEN = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff]")
C = TypeVar("C", bound=CanonicalContract)


class ResearchLedgerError(RuntimeError):
    """Ledger authority or a bounded retrieval request failed closed."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _raise(reason_code: ReasonCode, message: str) -> Never:
    raise ResearchLedgerError(reason_code, message)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _TOKEN.finditer(value.lower()))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        _raise(ReasonCode.SCHEMA_INVALID, "ledger timestamp must be timezone-aware")
    return value


def _validated(value: C, *, label: str) -> C:
    """Revalidate even model instances so unchecked model_copy updates cannot cross the boundary."""

    try:
        return type(value).model_validate(value.model_dump(mode="python"))
    except ValueError as error:
        raise ResearchLedgerError(ReasonCode.SCHEMA_INVALID, f"{label} is invalid") from error


def bind_context_pack(pack: ResearchContextPack) -> ResearchContextAgentBinding:
    """Create the exact hash bridge that a P14 AgentRun must carry as input."""

    pack = _validated(pack, label="ContextPack")
    return ResearchContextAgentBinding(
        campaign_hash=pack.campaign_hash,
        context_pack_hash=pack.content_hash,
        ledger_snapshot_hash=pack.ledger_snapshot_hash,
        search_policy_hash=pack.search_policy_hash,
        access_scope_hash=pack.access_scope_hash,
        context_budget_policy_hash=pack.context_budget_policy_hash,
        search_request_hash=pack.search_request_hash,
        search_result_hash=pack.search_result_hash,
    )


def _required_context_hashes(
    pack: ResearchContextPack, binding: ResearchContextAgentBinding
) -> frozenset[str]:
    return frozenset(
        {
            binding.content_hash,
            binding.context_pack_hash,
            binding.ledger_snapshot_hash,
            binding.search_policy_hash,
            binding.access_scope_hash,
            binding.context_budget_policy_hash,
            binding.search_request_hash,
            binding.search_result_hash,
            pack.content_hash,
        }
    )


def build_context_bound_agent_run_spec(
    *,
    run_id: str,
    role: AgentRole,
    capability_policy_hash: str,
    requested_model_configuration_hash: str,
    tool_schema_hash: str,
    instruction_hashes: tuple[str, ...],
    skill_hash: str,
    pack: ResearchContextPack,
    evidence_hashes: tuple[str, ...] = (),
    additional_input_hashes: tuple[str, ...] = (),
) -> tuple[ResearchContextAgentBinding, AgentRunSpec]:
    """Construct a P14 AgentRunSpec with the ContextPack and all of its authority bindings."""

    binding = bind_context_pack(pack)
    inputs = tuple(
        sorted(
            {
                *_required_context_hashes(pack, binding),
                *additional_input_hashes,
                *evidence_hashes,
                *instruction_hashes,
                capability_policy_hash,
                requested_model_configuration_hash,
                skill_hash,
                tool_schema_hash,
            }
        )
    )
    spec = AgentRunSpec(
        run_id=run_id,
        role=role,
        capability_policy_hash=capability_policy_hash,
        campaign_hash=pack.campaign_hash,
        requested_model_configuration_hash=requested_model_configuration_hash,
        tool_schema_hash=tool_schema_hash,
        instruction_hashes=instruction_hashes,
        skill_hash=skill_hash,
        ledger_snapshot_hash=pack.ledger_snapshot_hash,
        evidence_hashes=evidence_hashes,
        input_artifact_hashes=inputs,
    )
    verify_context_bound_agent_run_spec(spec=spec, binding=binding, pack=pack)
    return binding, spec


def verify_context_bound_agent_run_spec(
    *,
    spec: AgentRunSpec,
    binding: ResearchContextAgentBinding,
    pack: ResearchContextPack,
) -> None:
    """Fail closed if an AgentRunSpec can execute without its selected ContextPack authority."""

    spec = _validated(spec, label="AgentRunSpec")
    binding = _validated(binding, label="Agent context binding")
    pack = _validated(pack, label="ContextPack")
    if binding != bind_context_pack(pack):
        _raise(ReasonCode.ARTIFACT_CORRUPTED, "Agent context binding does not match ContextPack")
    if (
        spec.campaign_hash != binding.campaign_hash
        or spec.ledger_snapshot_hash != binding.ledger_snapshot_hash
        or not _required_context_hashes(pack, binding).issubset(spec.input_artifact_hashes)
    ):
        _raise(ReasonCode.ARTIFACT_CORRUPTED, "AgentRunSpec does not bind its ContextPack inputs")


def verify_context_bound_agent_manifest(
    *,
    manifest: AgentRunManifest,
    spec: AgentRunSpec,
    binding: ResearchContextAgentBinding,
    pack: ResearchContextPack,
) -> None:
    """Verify the retained AgentRun evidence still carries the exact ContextPack binding."""

    manifest = _validated(manifest, label="AgentRunManifest")
    spec = _validated(spec, label="AgentRunSpec")
    binding = _validated(binding, label="Agent context binding")
    pack = _validated(pack, label="ContextPack")
    verify_context_bound_agent_run_spec(spec=spec, binding=binding, pack=pack)
    if (
        manifest.run_spec_hash != spec.content_hash
        or manifest.model_configuration_hash != spec.requested_model_configuration_hash
        or manifest.tool_schema_hash != spec.tool_schema_hash
        or manifest.instruction_hashes != spec.instruction_hashes
        or manifest.skill_hash != spec.skill_hash
        or manifest.input_hashes != spec.input_artifact_hashes
    ):
        _raise(ReasonCode.ARTIFACT_CORRUPTED, "AgentRunManifest lost its ContextPack binding")


class ResearchLedgerService:
    """Persist canonical objects/events and rebuild every derived ledger view."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def _event_root(self) -> Path:
        return self.root / "events"

    @property
    def _object_root(self) -> Path:
        return self.root / "objects"

    @staticmethod
    def _object_suffix(media_type: str) -> str:
        return ".json" if media_type == "application/json" else ".txt"

    def _object_path(self, reference: ResearchLedgerObjectRef) -> Path:
        return (
            self._object_root
            / reference.source_domain
            / f"sha256-{reference.object_hash}{self._object_suffix(reference.media_type)}"
        )

    @staticmethod
    def _validate_object_bytes(reference: ResearchLedgerObjectRef, encoded: bytes) -> None:
        if sha256_bytes(encoded) != reference.object_hash:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger object bytes do not match object_hash")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ResearchLedgerError(
                ReasonCode.ARTIFACT_CORRUPTED, "ledger object must be UTF-8"
            ) from error
        if reference.media_type == "application/json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as error:
                raise ResearchLedgerError(
                    ReasonCode.ARTIFACT_CORRUPTED, "ledger JSON object is invalid"
                ) from error
            if canonical_json_bytes(payload) != encoded:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger JSON object is not canonical")

    @staticmethod
    def _event_identity(
        *,
        ledger_id: str,
        node_id: str,
        node_kind: ResearchLedgerNodeKind,
        object_ref: ResearchLedgerObjectRef,
        authority: LedgerAssertionAuthority,
        parent_object_hashes: tuple[str, ...],
        agent_run_hash: str | None,
        human_review_evidence_hash: str | None,
        verdict_report_hash: str | None,
        occurred_at: datetime,
    ) -> UUID:
        payload = {
            "ledger_id": ledger_id,
            "node_id": node_id,
            "node_kind": node_kind,
            "object_ref": object_ref,
            "authority": authority,
            "parent_object_hashes": parent_object_hashes,
            "agent_run_hash": agent_run_hash,
            "human_review_evidence_hash": human_review_evidence_hash,
            "verdict_report_hash": verdict_report_hash,
            "occurred_at": occurred_at,
        }
        return uuid5(_EVENT_NAMESPACE, canonical_json_bytes(payload).decode("utf-8"))

    def append(
        self,
        *,
        ledger_id: str,
        node_id: str,
        node_kind: ResearchLedgerNodeKind,
        object_ref: ResearchLedgerObjectRef,
        object_bytes: bytes,
        authority: LedgerAssertionAuthority,
        occurred_at: datetime,
        parent_object_hashes: tuple[str, ...] = (),
        agent_run_hash: str | None = None,
        human_review_evidence_hash: str | None = None,
        verdict_report_hash: str | None = None,
    ) -> ResearchLedgerEventV2:
        """Append one deterministic event; an exact retry returns the existing event."""

        _aware(occurred_at)
        object_ref = _validated(object_ref, label="ledger object reference")
        self._validate_object_bytes(object_ref, object_bytes)
        event_id = self._event_identity(
            ledger_id=ledger_id,
            node_id=node_id,
            node_kind=node_kind,
            object_ref=object_ref,
            authority=authority,
            parent_object_hashes=parent_object_hashes,
            agent_run_hash=agent_run_hash,
            human_review_evidence_hash=human_review_evidence_hash,
            verdict_report_hash=verdict_report_hash,
            occurred_at=occurred_at,
        )
        with exclusive_directory_lock(self.root.parent):
            groups = self._load_and_verify()
            chain = groups.get(ledger_id, ())
            existing = next((item for item in chain if item.event_id == event_id), None)
            if existing is not None:
                return existing

            if chain and occurred_at < chain[-1].occurred_at:
                _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger event time moved backwards")
            known_objects = {item.object_ref.object_hash for item in chain}
            known_object_refs = {
                item.object_ref.object_hash: item.object_ref
                for existing_chain in groups.values()
                for item in existing_chain
            }
            if not set(parent_object_hashes).issubset(known_objects):
                _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger event parent is not in the chain")
            prior_object_ref = known_object_refs.get(object_ref.object_hash)
            if prior_object_ref is not None and prior_object_ref != object_ref:
                _raise(
                    ReasonCode.DUPLICATE_ID_CONFLICT,
                    "ledger object hash cannot change its access binding",
                )
            same_node = [item for item in chain if item.node_id == node_id]
            if same_node:
                _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "ledger node_id is already bound")

            sequence = len(chain) + 1
            previous = chain[-1].content_hash if chain else None
            try:
                event = ResearchLedgerEventV2(
                    event_id=event_id,
                    ledger_id=ledger_id,
                    sequence=sequence,
                    node_id=node_id,
                    node_kind=node_kind,
                    object_ref=object_ref,
                    authority=authority,
                    parent_object_hashes=parent_object_hashes,
                    agent_run_hash=agent_run_hash,
                    human_review_evidence_hash=human_review_evidence_hash,
                    verdict_report_hash=verdict_report_hash,
                    occurred_at=occurred_at,
                    previous_event_hash=previous,
                )
            except ValueError as error:
                raise ResearchLedgerError(
                    ReasonCode.SCHEMA_INVALID, "ledger event is invalid"
                ) from error

            object_path = self._object_path(object_ref)
            event_path = self._event_root / ledger_id / f"{sequence:020d}-{event_id}.json"
            try:
                atomic_write_bytes(
                    object_path, object_bytes, expected_sha256=object_ref.object_hash
                )
                atomic_write_bytes(event_path, event.canonical_bytes())
            except (ArtifactConflictError, ArtifactIntegrityError) as error:
                raise ResearchLedgerError(
                    ReasonCode.DUPLICATE_ID_CONFLICT, "immutable ledger publication conflicts"
                ) from error
            return event

    def _load_and_verify(self) -> dict[str, tuple[ResearchLedgerEventV2, ...]]:
        if not self.root.exists():
            return {}
        if self.root.is_symlink() or not self.root.is_dir():
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger root is unsafe")
        try:
            files = regular_tree_files(self.root)
        except ArtifactIntegrityError as error:
            raise ResearchLedgerError(
                ReasonCode.ARTIFACT_CORRUPTED, "ledger tree is unsafe"
            ) from error

        groups: dict[str, list[ResearchLedgerEventV2]] = {}
        for path in files:
            relative = path.relative_to(self.root)
            if relative.parts[0] == "objects":
                self._verify_stored_object_path(path, relative)
                continue
            if len(relative.parts) != 3 or relative.parts[0] != "events":
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger tree contains an unexpected file")
            try:
                encoded = path.read_bytes()
                event = ResearchLedgerEventV2.model_validate_json(encoded)
            except (OSError, ValueError) as error:
                raise ResearchLedgerError(
                    ReasonCode.ARTIFACT_CORRUPTED, "ledger event is invalid"
                ) from error
            if encoded != event.canonical_bytes():
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger event bytes are not canonical")
            expected_name = f"{event.sequence:020d}-{event.event_id}.json"
            if relative.parts[1] != event.ledger_id or relative.name != expected_name:
                _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger event path does not match content")
            groups.setdefault(event.ledger_id, []).append(event)

        verified: dict[str, tuple[ResearchLedgerEventV2, ...]] = {}
        root_object_refs: dict[str, ResearchLedgerObjectRef] = {}
        for ledger_id, events in groups.items():
            chain = tuple(sorted(events, key=lambda item: item.sequence))
            known_objects: set[str] = set()
            known_object_refs: dict[str, ResearchLedgerObjectRef] = {}
            known_nodes: dict[str, ResearchLedgerObjectRef] = {}
            previous: ResearchLedgerEventV2 | None = None
            for expected_sequence, event in enumerate(chain, 1):
                if event.sequence != expected_sequence:
                    _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger sequence is not contiguous")
                expected_previous = previous.content_hash if previous is not None else None
                if event.previous_event_hash != expected_previous:
                    _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger predecessor hash is invalid")
                expected_event_id = self._event_identity(
                    ledger_id=event.ledger_id,
                    node_id=event.node_id,
                    node_kind=event.node_kind,
                    object_ref=event.object_ref,
                    authority=event.authority,
                    parent_object_hashes=event.parent_object_hashes,
                    agent_run_hash=event.agent_run_hash,
                    human_review_evidence_hash=event.human_review_evidence_hash,
                    verdict_report_hash=event.verdict_report_hash,
                    occurred_at=event.occurred_at,
                )
                if event.event_id != expected_event_id:
                    _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger event UUID is not deterministic")
                if previous is not None and event.occurred_at < previous.occurred_at:
                    _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger event time moved backwards")
                if not set(event.parent_object_hashes).issubset(known_objects):
                    _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger parent is missing or forward")
                if event.node_id in known_nodes:
                    _raise(ReasonCode.DUPLICATE_ID_CONFLICT, "ledger node_id is duplicated")
                prior_object_ref = known_object_refs.get(event.object_ref.object_hash)
                if prior_object_ref is not None and prior_object_ref != event.object_ref:
                    _raise(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "ledger object hash has conflicting access bindings",
                    )
                root_object_ref = root_object_refs.get(event.object_ref.object_hash)
                if root_object_ref is not None and root_object_ref != event.object_ref:
                    _raise(
                        ReasonCode.DUPLICATE_ID_CONFLICT,
                        "ledger root object hash has conflicting access bindings",
                    )
                self._read_object(event.object_ref)
                known_objects.add(event.object_ref.object_hash)
                known_object_refs[event.object_ref.object_hash] = event.object_ref
                known_nodes[event.node_id] = event.object_ref
                root_object_refs[event.object_ref.object_hash] = event.object_ref
                previous = event
            verified[ledger_id] = chain
        return verified

    def _verify_stored_object_path(self, path: Path, relative: Path) -> None:
        if len(relative.parts) != 3:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger object path is invalid")
        domain = relative.parts[1]
        if re.fullmatch(r"^[a-z0-9][a-z0-9._-]*$", domain) is None:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger object domain is invalid")
        match = re.fullmatch(r"sha256-([0-9a-f]{64})\.(json|txt)", relative.name)
        if match is None or sha256_file(path) != match.group(1):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger object path/hash is invalid")
        encoded = path.read_bytes()
        media_type = "application/json" if match.group(2) == "json" else "text/plain"
        reference = ResearchLedgerObjectRef(
            object_hash=match.group(1),
            media_type=media_type,
            source_domain=domain,
            access=LedgerObjectAccess.PUBLIC_HISTORY,
        )
        self._validate_object_bytes(reference, encoded)

    def _read_object(self, reference: ResearchLedgerObjectRef) -> bytes:
        path = self._object_path(reference)
        try:
            encoded = path.read_bytes()
        except OSError as error:
            raise ResearchLedgerError(
                ReasonCode.SOURCE_INCOMPLETE, "ledger object is unavailable"
            ) from error
        self._validate_object_bytes(reference, encoded)
        return encoded

    def verify(self, ledger_id: str, *, created_at: datetime) -> ResearchLedgerSnapshot:
        """Rebuild one snapshot after verifying the complete authority tree."""

        _aware(created_at)
        chain = self._load_and_verify().get(ledger_id, ())
        if not chain:
            _raise(ReasonCode.SOURCE_INCOMPLETE, "ledger does not contain the requested chain")
        if created_at < chain[-1].occurred_at:
            _raise(ReasonCode.EVENT_CHAIN_INVALID, "ledger snapshot predates its chain head")
        return ResearchLedgerSnapshot(
            ledger_id=ledger_id,
            source_event_hashes=tuple(item.content_hash for item in chain),
            head_event_hash=chain[-1].content_hash if chain else None,
            node_object_hashes=tuple(sorted({item.object_ref.object_hash for item in chain})),
            created_at=created_at,
        )

    def build_index(
        self,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
    ) -> ResearchLedgerIndex:
        snapshot = _validated(snapshot, label="ledger snapshot")
        policy = _validated(policy, label="ledger search policy")
        rebuilt = self.verify(snapshot.ledger_id, created_at=snapshot.created_at)
        if rebuilt.content_hash != snapshot.content_hash or (
            rebuilt.source_event_hashes != snapshot.source_event_hashes
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger snapshot does not match authority")
        chain = self._load_and_verify().get(snapshot.ledger_id, ())
        eligible = tuple(
            event
            for event in chain
            if event.node_kind in policy.allowed_node_kinds
            and event.authority in policy.allowed_authorities
        )
        if len(eligible) > policy.max_index_entries:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger index entry budget exceeded")
        entries: list[ResearchLedgerIndexEntry] = []
        for event in eligible:
            encoded = self._read_object(event.object_ref)
            if len(encoded) > policy.max_hit_bytes:
                _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger object byte budget exceeded")
            frequencies = Counter(_tokens(encoded.decode("utf-8")))
            if len(frequencies) > policy.max_terms_per_object:
                _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger object term budget exceeded")
            entries.append(
                ResearchLedgerIndexEntry(
                    event_hash=event.content_hash,
                    sequence=event.sequence,
                    node_id=event.node_id,
                    node_kind=event.node_kind,
                    object_ref=event.object_ref,
                    authority=event.authority,
                    term_frequencies=tuple(
                        ResearchLedgerTermFrequency(term=term, count=count)
                        for term, count in sorted(frequencies.items())
                    ),
                )
            )
        index = ResearchLedgerIndex(
            ledger_snapshot_hash=snapshot.content_hash,
            search_policy_hash=policy.content_hash,
            source_event_hashes=snapshot.source_event_hashes,
            entries=tuple(entries),
        )
        if len(index.canonical_bytes()) > policy.max_index_serialized_bytes:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger index byte budget exceeded")
        return index

    @staticmethod
    def _publish_derived(
        contract: ResearchLedgerIndex | ResearchContextPack,
        output_root: Path,
        *,
        directory: str,
        kind: str,
    ) -> ArtifactRef:
        encoded = contract.canonical_bytes()
        relative = Path(directory) / f"sha256-{contract.content_hash}.json"
        try:
            digest = atomic_write_bytes(output_root / relative, encoded)
        except (ArtifactConflictError, ArtifactIntegrityError) as error:
            raise ResearchLedgerError(
                ReasonCode.DUPLICATE_ID_CONFLICT, "derived ledger artifact publication conflicts"
            ) from error
        return ArtifactRef(
            kind=kind,
            sha256=digest,
            size_bytes=len(encoded),
            media_type="application/json",
            logical_path=relative.as_posix(),
        )

    def publish_index(
        self,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
        output_root: Path,
    ) -> tuple[ResearchLedgerIndex, ArtifactRef]:
        index = self.build_index(snapshot, policy)
        reference = self._publish_derived(
            index,
            output_root,
            directory="indexes",
            kind="research_ledger_index",
        )
        return index, reference

    def verify_index_artifact(
        self,
        path: Path,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
    ) -> ResearchLedgerIndex:
        try:
            digest = sha256_file(path)
            encoded = path.read_bytes()
            index = ResearchLedgerIndex.model_validate_json(encoded)
        except (ArtifactIntegrityError, OSError, ValueError) as error:
            raise ResearchLedgerError(
                ReasonCode.ARTIFACT_CORRUPTED, "ledger index artifact is invalid"
            ) from error
        if (
            encoded != index.canonical_bytes()
            or digest != index.content_hash
            or path.name != f"sha256-{index.content_hash}.json"
            or index != self.build_index(snapshot, policy)
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger index artifact is not reproducible")
        return index

    @staticmethod
    def _is_authorized(
        reference: ResearchLedgerObjectRef,
        scope: ResearchLedgerAccessScope,
        policy: ResearchLedgerSearchPolicy,
    ) -> bool:
        if reference.access is LedgerObjectAccess.PUBLIC_HISTORY:
            return True
        if reference.access is LedgerObjectAccess.SEALED_CONFIRMATION:
            return bool(
                reference.object_hash in scope.authorized_sealed_object_hashes
                and reference.campaign_hash in scope.readable_campaign_hashes
                and (
                    reference.campaign_hash == scope.campaign_hash
                    or policy.allow_cross_campaign_history
                )
                and set(reference.contamination_hashes).issubset(
                    scope.inherited_contamination_hashes
                )
            )
        if reference.campaign_hash == scope.campaign_hash:
            return True
        return bool(
            policy.allow_cross_campaign_history
            and reference.campaign_hash in scope.readable_campaign_hashes
        )

    def search(
        self,
        *,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
        scope: ResearchLedgerAccessScope,
        request: ResearchLedgerSearchRequest,
    ) -> ResearchLedgerSearchResult:
        snapshot = _validated(snapshot, label="ledger snapshot")
        policy = _validated(policy, label="ledger search policy")
        scope = _validated(scope, label="ledger access scope")
        request = _validated(request, label="ledger search request")
        if (
            request.campaign_hash != scope.campaign_hash
            or request.ledger_snapshot_hash != snapshot.content_hash
            or request.ledger_snapshot_hash != scope.ledger_snapshot_hash
            or request.search_policy_hash != policy.content_hash
            or request.access_scope_hash != scope.content_hash
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger search bindings disagree")
        if len(request.query.encode("utf-8")) > policy.max_query_bytes:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger query byte budget exceeded")
        query_terms = tuple(sorted(set(_tokens(request.query))))
        if not query_terms:
            _raise(ReasonCode.SCHEMA_INVALID, "ledger query has no searchable terms")
        if len(query_terms) > policy.max_query_terms:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger query term budget exceeded")
        index = self.build_index(snapshot, policy)
        hits: list[ResearchLedgerSearchHit] = []
        for entry in index.entries:
            if not self._is_authorized(entry.object_ref, scope, policy):
                continue
            frequencies = {item.term: item.count for item in entry.term_frequencies}
            score = sum(frequencies.get(term, 0) for term in query_terms)
            if score:
                content = self._read_object(entry.object_ref).decode("utf-8")
                if len(content.encode("utf-8")) > policy.max_hit_bytes:
                    _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger hit byte budget exceeded")
                hits.append(
                    ResearchLedgerSearchHit(
                        event_hash=entry.event_hash,
                        node_id=entry.node_id,
                        node_kind=entry.node_kind,
                        object_ref=entry.object_ref,
                        authority=entry.authority,
                        score=score,
                        content=content,
                        content_bytes=len(content.encode("utf-8")),
                    )
                )
        ranked = sorted(
            hits,
            key=lambda item: (-item.score, item.object_ref.object_hash, item.event_hash),
        )
        unique_hits: list[ResearchLedgerSearchHit] = []
        seen_objects: set[str] = set()
        for hit in ranked:
            if hit.object_ref.object_hash in seen_objects:
                continue
            unique_hits.append(hit)
            seen_objects.add(hit.object_ref.object_hash)
        result = ResearchLedgerSearchResult(
            request_hash=request.content_hash,
            index_hash=index.content_hash,
            query_terms=query_terms,
            hits=tuple(unique_hits[: policy.max_results]),
        )
        if len(result.canonical_bytes()) > policy.max_serialized_bytes:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "ledger search response budget exceeded")
        return result

    def build_context_pack(
        self,
        *,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
        scope: ResearchLedgerAccessScope,
        request: ResearchLedgerSearchRequest,
        result: ResearchLedgerSearchResult,
        budget: ResearchContextBudgetPolicy,
    ) -> ResearchContextPack:
        result = _validated(result, label="ledger search result")
        budget = _validated(budget, label="context budget policy")
        expected = self.search(snapshot=snapshot, policy=policy, scope=scope, request=request)
        if result != expected:
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "ledger search result is not reproducible")
        items: list[ResearchContextItem] = []
        total = 0
        for hit in result.hits[: budget.max_items]:
            content = hit.content
            content_bytes = hit.content_bytes
            if (
                content_bytes > budget.max_item_bytes
                or total + content_bytes > budget.max_serialized_bytes
            ):
                _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "context pack byte budget exceeded")
            items.append(
                ResearchContextItem(
                    event_hash=hit.event_hash,
                    node_id=hit.node_id,
                    node_kind=hit.node_kind,
                    object_ref=hit.object_ref,
                    authority=hit.authority,
                    score=hit.score,
                    content=content,
                    content_bytes=content_bytes,
                )
            )
            total += content_bytes
        pack = ResearchContextPack(
            campaign_hash=request.campaign_hash,
            ledger_snapshot_hash=request.ledger_snapshot_hash,
            search_policy_hash=request.search_policy_hash,
            access_scope_hash=request.access_scope_hash,
            context_budget_policy_hash=budget.content_hash,
            search_request_hash=request.content_hash,
            search_result_hash=result.content_hash,
            items=tuple(items),
            included_content_bytes=total,
        )
        if len(pack.canonical_bytes()) > budget.max_serialized_bytes:
            _raise(ReasonCode.RESOURCE_BUDGET_EXCEEDED, "context pack byte budget exceeded")
        return pack

    def publish_context_pack(
        self,
        *,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
        scope: ResearchLedgerAccessScope,
        request: ResearchLedgerSearchRequest,
        result: ResearchLedgerSearchResult,
        budget: ResearchContextBudgetPolicy,
        output_root: Path,
    ) -> tuple[ResearchContextPack, ArtifactRef]:
        pack = self.build_context_pack(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=result,
            budget=budget,
        )
        reference = self._publish_derived(
            pack,
            output_root,
            directory="context-packs",
            kind="research_context_pack",
        )
        return pack, reference

    def verify_context_pack_artifact(
        self,
        path: Path,
        *,
        snapshot: ResearchLedgerSnapshot,
        policy: ResearchLedgerSearchPolicy,
        scope: ResearchLedgerAccessScope,
        request: ResearchLedgerSearchRequest,
        result: ResearchLedgerSearchResult,
        budget: ResearchContextBudgetPolicy,
    ) -> ResearchContextPack:
        try:
            digest = sha256_file(path)
            encoded = path.read_bytes()
            pack = ResearchContextPack.model_validate_json(encoded)
        except (ArtifactIntegrityError, OSError, ValueError) as error:
            raise ResearchLedgerError(
                ReasonCode.ARTIFACT_CORRUPTED, "context pack artifact is invalid"
            ) from error
        expected = self.build_context_pack(
            snapshot=snapshot,
            policy=policy,
            scope=scope,
            request=request,
            result=result,
            budget=budget,
        )
        if (
            encoded != pack.canonical_bytes()
            or digest != pack.content_hash
            or path.name != f"sha256-{pack.content_hash}.json"
            or pack != expected
        ):
            _raise(ReasonCode.ARTIFACT_CORRUPTED, "context pack artifact is not reproducible")
        return pack
