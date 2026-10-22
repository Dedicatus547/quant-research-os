"""Bounded local announcement reading; proposals never grant research admission."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from quantos.artifacts.store import (
    atomic_write_bytes,
    atomic_write_bytes_at,
    confined_regular_file,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence import EvidenceUsePermission
from quantos.contracts.local_evidence import (
    LocalEvidenceStoreManifest,
    LocalImportPolicy,
    LocalPublishedEvidence,
)
from quantos.evidence.local_store import (
    LocalImportSource,
    local_binding,
    local_citation,
    publish_local_evidence_store,
    verify_local_evidence_store,
)
from quantos.security.artifact_secrets import validate_secret_free


def explicit_root(value: Path) -> Path:
    """Reject cwd-dependent configuration and symbolic path components."""
    value = Path(value)
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("root must be an explicit absolute path")
    if any(part.is_symlink() for part in (value, *value.parents)):
        raise ValueError("symbolic root paths are not allowed")
    return value.resolve()


def _hash(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected an explicit SHA256 identity")
    return value


class PersonalEvidenceService:
    """Read explicit catalog entries, reuse frozen stores and exact citation code.

    UNKNOWN source rights permit only local document understanding, never an
    assertion of research permission or historical availability. RESTRICTED
    content is denied. No acquisition, admission or external model is invoked.
    """

    def __init__(self, root: Path, repo_root: Path) -> None:
        self.root = explicit_root(root)
        self.repo_root = explicit_root(repo_root)

    def _stores(self) -> list[tuple[Path, LocalEvidenceStoreManifest]]:
        catalog = self.root / "evidence-catalog.json"
        if not catalog.exists():
            if catalog.is_symlink():
                raise ValueError("symbolic evidence catalog is not allowed")
            return []
        path = confined_regular_file(self.root, "evidence-catalog.json")
        if path.stat().st_size > 65_536:
            raise ValueError("evidence catalog exceeds size limit")
        data = json.loads(path.read_bytes())
        if (
            set(data) != {"schema_version", "stores"}
            or data["schema_version"] != "personal-evidence-catalog/v1"
        ):
            raise ValueError("unsupported evidence catalog")
        entries: object = data["stores"]
        if not isinstance(entries, list) or len(cast(list[object], entries)) > 16:
            raise ValueError("evidence catalog must contain at most 16 stores")
        stores: list[tuple[Path, LocalEvidenceStoreManifest]] = []
        seen: set[str] = set()
        for raw_entry in cast(list[object], entries):
            if not isinstance(raw_entry, dict):
                raise ValueError("invalid catalog entry")
            entry = cast(dict[str, Any], raw_entry)
            if set(entry) != {"store_hash", "path"}:
                raise ValueError("invalid catalog entry")
            digest = _hash(entry["store_hash"])
            relative = Path(entry["path"])
            if relative.is_absolute() or any(
                p == ".." or "sealed" in p.lower() for p in relative.parts
            ):
                raise ValueError("evidence catalog path is outside permitted local scope")
            manifest_path = confined_regular_file(
                self.repo_root, (relative / "manifest.json").as_posix()
            )
            if manifest_path.stat().st_size > 2_000_000:
                raise ValueError("evidence manifest exceeds size limit")
            envelope = json.loads(manifest_path.read_bytes())
            files = envelope.get("files", [])
            if len(files) > 2048:
                raise ValueError("evidence store exceeds file count limit")
            total = 0
            for item in files:
                total += (
                    confined_regular_file(manifest_path.parent, item["logical_path"]).stat().st_size
                )
                if total > 64 * 1024 * 1024:
                    raise ValueError("evidence store exceeds 64 MiB read budget")
            manifest = verify_local_evidence_store(manifest_path.parent)
            if digest != manifest.store_hash or digest in seen:
                raise ValueError("catalog identity mismatch or duplicate store")
            seen.add(digest)
            stores.append((manifest_path.parent, manifest))
        return stores

    def list_evidence(self, limit: int = 20) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        items: list[dict[str, Any]] = []
        for _, manifest in self._stores():
            for item in manifest.items:
                items.append(
                    {
                        "store_hash": manifest.store_hash,
                        "evidence_hash": item.evidence.content_hash,
                        "sample_id": item.sample_id,
                        "entities": list(item.evidence.entity_refs),
                        "permission": item.evidence.use_permission.value,
                        "available_at": item.evidence.model_dump(mode="json")["available_at"],
                        "research_admission": "NOT_GRANTED",
                    }
                )
        return {
            "items": items[:limit],
            "total": len(items),
            "truncated": len(items) > limit,
            "mode": "LOCAL_AUXILIARY_DOCUMENT_UNDERSTANDING",
        }

    def _item(
        self, evidence_hash: str, as_of: str | None = None
    ) -> tuple[Path, LocalPublishedEvidence]:
        _hash(evidence_hash)
        for path, manifest in self._stores():
            for item in manifest.items:
                if item.evidence.content_hash != evidence_hash:
                    continue
                if item.evidence.use_permission == EvidenceUsePermission.RESTRICTED:
                    raise PermissionError("source permission is RESTRICTED")
                if as_of is not None:
                    stamp = datetime.fromisoformat(as_of)
                    if stamp.tzinfo is None or stamp.utcoffset() is None:
                        raise ValueError("as_of must contain a timezone")
                    if item.evidence.available_at is None or item.evidence.available_at > stamp:
                        raise ValueError("historical availability is unknown or after as_of")
                return path, item
        raise ValueError("evidence identity is not in the explicit local catalog")

    def read(
        self, evidence_hash: str, start: int = 0, max_chars: int = 8000, as_of: str | None = None
    ) -> dict[str, Any]:
        if (
            type(start) is not int
            or start < 0
            or type(max_chars) is not int
            or not 1 <= max_chars <= 16000
        ):
            raise ValueError("invalid bounded text range")
        path, item = self._item(evidence_hash, as_of)
        binding = local_binding(path, item)
        if start > len(binding.text):
            raise ValueError("start escapes frozen text")
        end = min(start + max_chars, len(binding.text))
        return {
            "evidence_hash": evidence_hash,
            "extracted_text_hash": item.extracted_text.content_hash,
            "text": binding.text[start:end],
            "char_start": start,
            "char_end": end,
            "total_chars": len(binding.text),
            "permission": item.evidence.use_permission.value,
            "research_admission": "NOT_GRANTED",
            "available_at": item.evidence.model_dump(mode="json")["available_at"],
            "limitations": list(item.evidence.limitations),
            "interpretation": (
                "Auxiliary analysis only; absence of detected risk does not establish "
                "absence of adverse information."
            ),
        }

    def cite(self, evidence_hash: str, start: int, end: int, expected_text: str) -> dict[str, Any]:
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end
            or end - start > 10000
        ):
            raise ValueError("invalid bounded citation range")
        path, item = self._item(evidence_hash)
        binding = local_binding(path, item)
        if binding.text[start:end] != expected_text or len(expected_text) != end - start:
            raise ValueError("citation does not match frozen text")
        page_bytes = confined_regular_file(path, item.page_map_ref.logical_path).read_bytes()
        if sha256_bytes(page_bytes) != item.page_map_ref.sha256:
            raise ValueError("physical page map identity mismatch")
        pages = json.loads(page_bytes)
        return local_citation(binding, pages, start, end).model_dump(mode="json")

    def propose(
        self, evidence_hash: str, claim: str, citations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if type(claim) is not str or not 1 <= len(claim) <= 8000 or not 1 <= len(citations) <= 16:
            raise ValueError("proposal requires bounded claim and 1-16 exact citations")
        verified: list[dict[str, Any]] = []
        for citation in citations:
            if set(citation) != {"start", "end", "expected_text"}:
                raise ValueError("citation accepts only start, end and expected_text")
            verified.append(self.cite(evidence_hash, **citation))
        record = {
            "schema_version": "personal-evidence-proposal/v1",
            "evidence_hash": evidence_hash,
            "claim": claim,
            "citations": verified,
            "origin": "HOST_SESSION_PROPOSAL",
            "model_identity": "UNKNOWN",
            "research_admission": "NOT_GRANTED",
            "semantic_validation": "NOT_EVALUATED",
        }
        validate_secret_free(record, file_name="personal-evidence-proposal.json")
        digest = sha256_bytes(canonical_json_bytes(record))
        self.root.mkdir(parents=True, exist_ok=True)
        # Cross-process ordering reuses the repository's directory flock pattern.
        with exclusive_directory_lock(self.root):
            destination = self.root / "evidence-proposals"
            if destination.is_symlink():
                raise ValueError("symbolic proposal directory is not allowed")
            destination.mkdir(exist_ok=True)
            target = destination / (digest + ".json")
            content = canonical_json_bytes(record)
            if target.exists():
                if confined_regular_file(destination, target.name).read_bytes() != content:
                    raise ValueError("immutable proposal identity mismatch")
            else:
                atomic_write_bytes(target, content)
        return {"proposal_id": digest, **record}

    def review(self, proposal_id: str) -> dict[str, Any]:
        digest = _hash(proposal_id)
        path = confined_regular_file(self.root, "evidence-proposals/" + digest + ".json")
        if path.stat().st_size > 256_000:
            raise ValueError("proposal exceeds size limit")
        raw = path.read_bytes()
        if sha256_bytes(raw) != digest:
            raise ValueError("proposal identity mismatch")
        record = json.loads(raw)
        # Recheck exact source identity and each citation, not merely saved labels.
        source, item = self._item(record["evidence_hash"])
        binding = local_binding(source, item)
        for citation in record["citations"]:
            actual = self.cite(
                record["evidence_hash"],
                citation["char_start"],
                citation["char_end"],
                binding.text[citation["char_start"] : citation["char_end"]],
            )
            if actual != citation:
                raise ValueError("proposal citation identity mismatch")
        return {
            "proposal_id": digest,
            "proposal": record,
            "citation_integrity": "VERIFIED",
            "semantic_validation": "NOT_EVALUATED",
            "research_admission": "NOT_GRANTED",
            "reviewed_at": datetime.now(UTC).isoformat(),
        }

    def import_local(self, intake_manifest: str) -> dict[str, Any]:
        """Reuse retained raw/text/page maps; no extraction, acquisition or admission.

        Intake JSON: {schema_version: personal-evidence-intake/v1, sources: [...]},
        with LocalImportSource fields and repository-relative retained file paths.
        The server supplies the import policy's actual code/source identities.
        """
        if not self.root.is_relative_to(self.repo_root):
            raise ValueError("local import requires product root inside repo_root")
        relative = Path(intake_manifest)
        if relative.is_absolute() or any(
            p == ".." or "sealed" in p.lower() for p in relative.parts
        ):
            raise ValueError("intake manifest is outside permitted local scope")
        path = confined_regular_file(self.repo_root, intake_manifest)
        if path.stat().st_size > 128_000:
            raise ValueError("intake manifest exceeds size limit")
        raw = path.read_bytes()
        data = json.loads(raw)
        validate_secret_free(data, file_name="personal-evidence-intake.json")
        if (
            set(data) != {"schema_version", "sources"}
            or data["schema_version"] != "personal-evidence-intake/v1"
        ):
            raise ValueError("unsupported local intake manifest")
        if not isinstance(data["sources"], list) or not 1 <= len(data["sources"]) <= 16:
            raise ValueError("local intake requires 1-16 retained materials")
        sources: list[LocalImportSource] = []
        total = 0
        allowed = {f.name for f in fields(LocalImportSource)}
        for raw_item in cast(list[object], data["sources"]):
            if not isinstance(raw_item, dict):
                raise ValueError("unsupported retained source field")
            item = cast(dict[str, Any], raw_item)
            if set(item) - allowed:
                raise ValueError("unsupported retained source field")
            values: dict[str, Any] = {
                **item,
                "use_permission": EvidenceUsePermission(item.get("use_permission", "UNKNOWN")),
            }
            source = LocalImportSource(**values)
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", source.sample_id):
                raise ValueError("invalid retained source sample_id")
            if source.use_permission == EvidenceUsePermission.RESTRICTED:
                raise PermissionError("cannot import RESTRICTED material")
            if source.use_permission != EvidenceUsePermission.UNKNOWN:
                raise PermissionError("source rights require independent server-bound evidence")
            for name in (source.raw_path, source.text_path, source.page_map_path):
                if any("sealed" in p.lower() for p in Path(name).parts):
                    raise ValueError("sealed material is outside local intake scope")
                total += confined_regular_file(self.repo_root, name).stat().st_size
            if total > 16 * 1024 * 1024:
                raise ValueError("local intake exceeds 16 MiB budget")
            sources.append(source)
        head = subprocess.run(
            ["git", "-C", str(self.repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        policy = LocalImportPolicy(
            policy_id="personal-document-understanding-v1",
            code_commit_hash=head,
            importer_source_hash=sha256_bytes(
                (self.repo_root / "src/quantos/evidence/local_store.py").read_bytes()
            ),
            adoption_record_hashes=(),
        )
        request_id = sha256_bytes(
            canonical_json_bytes({"intake_hash": sha256_bytes(raw), "policy": policy})
        )
        with exclusive_directory_lock(self.root):
            stores = self._stores()
            # Explicit per-request output makes a completed import discoverable
            # after interruption before catalog publication, without reimporting.
            destination = self.root / "evidence-imports" / request_id
            explicit_root(destination)
            destination.mkdir(parents=True, exist_ok=True)
            completed = list(destination.glob("sha256-*"))
            if len(completed) > 1:
                raise ValueError("ambiguous interrupted import output")
            if completed:
                store = completed[0]
                manifest = verify_local_evidence_store(store)
                if manifest.import_policy_hash != policy.content_hash:
                    raise ValueError("completed import policy mismatch")
            else:
                if len(stores) >= 16:
                    raise ValueError("evidence catalog capacity is exhausted")
                store = publish_local_evidence_store(self.repo_root, destination, sources, policy)
                manifest = verify_local_evidence_store(store)
            entries = [
                {"store_hash": m.store_hash, "path": p.relative_to(self.repo_root).as_posix()}
                for p, m in stores
            ]
            if manifest.store_hash not in {e["store_hash"] for e in entries}:
                if len(entries) >= 16:
                    raise ValueError("evidence catalog capacity is exhausted")
                entries.append(
                    {
                        "store_hash": manifest.store_hash,
                        "path": store.relative_to(self.repo_root).as_posix(),
                    }
                )
                self._replace_catalog(entries)
        return {
            "request_id": request_id,
            "store_hash": manifest.store_hash,
            "items": len(manifest.items),
            "research_admission": "NOT_GRANTED",
            "historical_availability": "UNKNOWN",
            "operation": "REUSED_LOCAL_EXTRACTION_NO_ACQUISITION",
        }

    def _replace_catalog(self, entries: list[dict[str, str]]) -> None:
        """Update the lookup index under the caller's lock, retaining immutable revisions."""
        content = canonical_json_bytes(
            {"schema_version": "personal-evidence-catalog/v1", "stores": entries}
        )
        with opened_directory(self.root) as root_fd:
            with opened_directory(
                self.root / "evidence-catalog-revisions", create=True
            ) as archive_fd:
                try:
                    os.stat("evidence-catalog.json", dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    previous = None
                else:
                    previous = read_regular_bytes_at(
                        root_fd, "evidence-catalog.json", max_bytes=65536
                    )
                if previous is not None:
                    atomic_write_bytes_at(archive_fd, sha256_bytes(previous) + ".json", previous)
                digest = atomic_write_bytes_at(archive_fd, sha256_bytes(content) + ".json", content)
            temporary = ".catalog-" + digest + ".json"
            atomic_write_bytes_at(root_fd, temporary, content)
            os.replace(temporary, "evidence-catalog.json", src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
