"""Explicit immutable history references; an index is never a new result authority."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from quantos.artifacts.store import confined_regular_file, sha256_file


class PersonalHistoryService:
    def __init__(self, root: Path, repo_root: Path) -> None:
        self.root = root
        self.repo_root = repo_root

    def _entries(self) -> list[dict[str, Any]]:
        if not (self.root / "history-catalog.json").exists():
            return []
        path = confined_regular_file(self.root, "history-catalog.json")
        if path.stat().st_size > 128_000:
            raise ValueError("history catalog is too large")
        catalog: dict[str, Any] = json.loads(path.read_bytes())
        if (
            set(catalog) != {"schema_version", "records"}
            or catalog["schema_version"] != "personal-history-catalog/v1"
        ):
            raise ValueError("unsupported history catalog")
        raw_records: object = catalog["records"]
        if not isinstance(raw_records, list):
            raise ValueError("history catalog exceeds bounded record count")
        untyped_records = cast(list[object], raw_records)
        if len(untyped_records) > 100:
            raise ValueError("history catalog exceeds bounded record count")
        records: list[dict[str, Any]] = []
        ids: set[str] = set()
        for item in untyped_records:
            if not isinstance(item, dict):
                raise ValueError("invalid history entry")
            entry = cast(dict[str, Any], item)
            if set(entry) != {
                "record_id",
                "label",
                "path",
                "sha256",
                "origin",
            }:
                raise ValueError("invalid history entry")
            if any(not isinstance(value, str) for value in entry.values()):
                raise ValueError("history entry fields must be strings")
            if (
                not re.fullmatch(r"[a-z0-9_-]{1,96}", entry["record_id"])
                or entry["record_id"] in ids
            ):
                raise ValueError("history IDs must be unique logical IDs")
            if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
                raise ValueError("history must bind an explicit hash")
            relative = Path(entry["path"])
            if relative.is_absolute() or any("sealed" in part.lower() for part in relative.parts):
                raise ValueError("history source is outside authorized scope")
            source = confined_regular_file(self.repo_root, relative.as_posix())
            if source.stat().st_size > 512_000 or sha256_file(source) != entry["sha256"]:
                raise ValueError("history source identity or size disagrees")
            ids.add(entry["record_id"])
            records.append(entry)
        return records

    def search(self, query: str = "", limit: int = 20) -> dict[str, Any]:
        if len(query) > 256 or not 1 <= limit <= 100:
            raise ValueError("history search exceeds limits")
        entries = self._entries()
        hits = [
            entry
            for entry in entries
            if query.lower() in (entry["record_id"] + " " + entry["label"]).lower()
        ]
        return {
            "records": hits[:limit],
            "matched": len(hits),
            "total": len(entries),
            "authority": "REFERENCES_ONLY_READ_ORIGINAL_FOR_OUTCOME",
            "rerun_performed": False,
        }

    def read(self, record_id: str) -> dict[str, Any]:
        entry = next((entry for entry in self._entries() if entry["record_id"] == record_id), None)
        if entry is None:
            raise ValueError("history record is not in the explicit catalog")
        source = confined_regular_file(self.repo_root, entry["path"])
        # Recheck bytes actually returned, rather than trusting a preceding file lookup.
        raw = source.read_bytes()
        import hashlib

        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("history changed during read")
        return {
            "reference": entry,
            "original": json.loads(raw),
            "adoption": "READ_ONLY_ORIGINAL_IDENTITY_NO_NEW_VALIDATION_OR_EXECUTION",
        }
