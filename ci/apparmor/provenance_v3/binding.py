"""Explicit v3 cross-job content proposal; never grants policy-loading authority."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import TypeGuard


def dictionary(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def sequence(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def mapping(value: object) -> dict[str, object]:
    if not dictionary(value) or any(not isinstance(key, str) for key in value):
        raise ValueError("expected string-keyed object")
    return {str(key): item for key, item in value.items()}


def items(value: object) -> list[object]:
    if not sequence(value):
        raise ValueError("expected list")
    return value


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def field(value: object) -> str:
    record = mapping(value)
    if set(record) != {"status", "value", "bytes", "sha256"}:
        raise ValueError("unsupported inventory field metadata")
    text = record.get("value")
    if record.get("status") != "ok" or not isinstance(text, str):
        raise ValueError("missing/unreadable inventory field")
    raw = text.encode("utf-8")
    if record.get("bytes") != len(raw) or record.get("sha256") != digest(raw):
        raise ValueError("inventory field bytes/hash mismatch")
    return text


def inventory_binding(raw: bytes) -> dict[str, object]:
    value: object = json.loads(raw)
    return project_inventory(mapping(value))


def project_inventory(obj: dict[str, object]) -> dict[str, object]:
    expected = {
        "schema",
        "policy_root",
        "revision_before",
        "revision_after",
        "profiles",
        "profile_count",
        "unknown_attachment_count",
        "other_namespaces",
        "errors",
        "collection_complete",
        "attachment_review",
        "load_authorized",
    }
    if set(obj) != expected or obj["schema"] != "quantos-apparmor-identity-v2":
        raise ValueError("unsupported inventory schema/fields")
    if (
        obj["collection_complete"] is not True
        or obj["errors"] != []
        or obj["other_namespaces"] != []
    ):
        raise ValueError("incomplete or additional-namespace inventory")
    if obj["policy_root"] != "/sys/kernel/security/apparmor/policy":
        raise ValueError("unexpected policy namespace root")
    if obj["attachment_review"] != "UNREVIEWED" or obj["load_authorized"] is not False:
        raise ValueError("inventory cannot supply approval")
    if field(obj["revision_before"]) != field(obj["revision_after"]):
        raise ValueError("policy revision changed")
    records = [mapping(item) for item in items(obj["profiles"])]
    if not 0 < len(records) <= 512 or obj["profile_count"] != len(records):
        raise ValueError("profile count mismatch/limit")
    by_directory: dict[str, dict[str, object]] = {}
    for record in records:
        if set(record) != {"directory", "fields", "loaded_metadata", "links"}:
            raise ValueError("unsupported profile fields")
        directory = record["directory"]
        if not isinstance(directory, str) or directory in by_directory:
            raise ValueError("invalid/duplicate directory")
        parts = directory.split("/")
        if (
            len(parts) > 64
            or len(parts) % 2
            or any(
                parts[i] != "profiles" or not re.fullmatch(r"[^/\x00]+\.[0-9]+", parts[i + 1])
                for i in range(0, len(parts), 2)
            )
        ):
            raise ValueError("invalid directory lineage")
        by_directory[directory] = record

    def lineage(directory: str) -> list[str]:
        parent = directory.rsplit("/profiles/", 1)[0] if "/profiles/" in directory else None
        if parent is not None and parent not in by_directory:
            raise ValueError("missing parent profile")
        name = field(mapping(by_directory[directory]["fields"])["name"]).removesuffix("\n")
        if not name or "\n" in name or "\x00" in name:
            raise ValueError("invalid profile name")
        return ([] if parent is None else lineage(parent)) + [name]

    portable: list[dict[str, object]] = []
    identities: set[tuple[str, ...]] = set()
    groups: dict[str, list[list[str]]] = {}
    group_hashes: dict[str, tuple[str, str]] = {}
    unknown = 0
    for directory, record in by_directory.items():
        identity = lineage(directory)
        if tuple(identity) in identities:
            raise ValueError("duplicate full parent/child identity")
        identities.add(tuple(identity))
        required = mapping(record["fields"])
        metadata = mapping(record["loaded_metadata"])
        links = mapping(record["links"])
        if (
            set(required) != {"name", "mode", "attach"}
            or set(metadata) != {"sha256", "raw_sha256", "raw_abi"}
            or set(links) != {"raw_data", "raw_sha256", "raw_abi"}
        ):
            raise ValueError("incomplete/unknown profile metadata")
        values = {key: field(item) for key, item in required.items()}
        loaded = {key: field(item) for key, item in metadata.items()}
        if any(
            not re.fullmatch(r"[0-9a-f]{64}\n", loaded[key]) for key in ("sha256", "raw_sha256")
        ) or not re.fullmatch(r"v[0-9]+\n", loaded["raw_abi"]):
            raise ValueError("invalid loaded hash/ABI")
        if values["mode"] not in ("enforce\n", "complain\n", "unconfined\n", "kill\n"):
            raise ValueError("unrecognized policy mode")
        group: str | None = None
        for key, filename in (
            ("raw_data", "raw_data"),
            ("raw_sha256", "sha256"),
            ("raw_abi", "abi"),
        ):
            link = mapping(links[key])
            target = link.get("target")
            if (
                set(link) != {"status", "target"}
                or link["status"] != "ok"
                or not isinstance(target, str)
                or target.startswith("/")
            ):
                raise ValueError("unavailable/unsupported raw link")
            resolved = posixpath.normpath(posixpath.join(directory, target))
            if not re.fullmatch(r"raw_data/[0-9]+/" + filename, resolved):
                raise ValueError("raw link escape or wrong target field")
            current = resolved.rsplit("/", 1)[0]
            if target != "../" * len(directory.split("/")) + current + "/" + filename:
                raise ValueError("noncanonical raw link traversal")
            if group is not None and current != group:
                raise ValueError("raw links disagree on policy group")
            group = current
        hashes = (loaded["raw_sha256"], loaded["raw_abi"])
        if group in group_hashes and group_hashes[group] != hashes:
            raise ValueError("inconsistent shared raw group hash/ABI")
        group_hashes[group] = hashes
        groups.setdefault(group, []).append(identity)
        unknown += values["attach"] == "<unknown>\n"
        portable.append(
            {
                "lineage": identity,
                "directory_prefixes": [
                    part.rsplit(".", 1)[0] for part in directory.split("/")[1::2]
                ],
                "fields": values,
                "loaded_metadata": loaded,
            }
        )
    if obj["unknown_attachment_count"] != unknown:
        raise ValueError("unknown attachment count mismatch")
    return {
        "schema": "quantos-apparmor-cross-job-v3",
        "namespace": "root-policy-view",
        "profiles": sorted(portable, key=lambda item: canonical(item["lineage"])),
        "raw_group_members": sorted([sorted(members) for members in groups.values()]),
        "unknown_attachment_count": unknown,
        "stable_revision_within_capture": True,
    }


def candidate(raw: bytes) -> dict[str, object]:
    value: object = json.loads(raw)
    capture = mapping(value)
    if capture.get("schema") != "quantos-apparmor-provenance-v3":
        raise ValueError("unsupported provenance schema")
    inventory_raw = base64.b64decode(str(capture["inventory_raw_base64"]), validate=True)
    if digest(inventory_raw) != capture["inventory_sha256"]:
        raise ValueError("raw inventory hash mismatch")
    inventory_value: object = json.loads(inventory_raw)
    inventory = mapping(inventory_value)
    portable = project_inventory(inventory)
    # Only explicitly documented execution-local observations are omitted. All other
    # fields, including unknown future fields, participate in rejection via the digest.
    content = {
        key: item
        for key, item in capture.items()
        if key
        not in {"inventory_raw_base64", "inventory_sha256", "revision_after_sources", "budget"}
    }
    content["inventory"] = portable
    if field(capture.get("revision_after_sources")) != field(inventory["revision_after"]):
        raise ValueError("policy changed during provenance capture")
    if (
        capture.get("source_to_loaded_correspondence") != "UNRESOLVED"
        or capture.get("load_authorized") is not False
    ):
        raise ValueError("this proposal cannot assert verified source or loading authority")
    for group in ("sources", "settings", "features", "namespace", "binaries"):
        seen: set[str] = set()
        records = items(capture[group])
        if not records:
            raise ValueError("missing provenance group")
        for entry in records:
            record = mapping(entry)
            path = record.get("path")
            if not isinstance(path, str) or path in seen:
                raise ValueError("duplicate/invalid provenance path")
            seen.add(path)
            if record.get("status") == "ok" and group != "binaries":
                if "base64" not in record:
                    raise ValueError("missing source bytes")
                data = base64.b64decode(str(record["base64"]), validate=True)
                if digest(data) != record.get("sha256") or len(data) != record.get("bytes"):
                    raise ValueError("source bytes/hash mismatch")
    namespace = {
        str(mapping(entry)["path"]): mapping(entry) for entry in items(capture["namespace"])
    }
    prefix = "/sys/kernel/security/apparmor/"
    if set(namespace) != {
        prefix + name for name in (".ns_name", ".ns_level", ".ns_stacked", ".stacked")
    }:
        raise ValueError("incomplete namespace identity")
    if any(record.get("status") != "ok" for record in namespace.values()):
        raise ValueError("unreadable namespace identity")
    for name, expected_value in (
        (".ns_level", b"0\n"),
        (".ns_stacked", b"no\n"),
        (".stacked", b"no\n"),
    ):
        record = namespace[prefix + name]
        if (
            record.get("status") != "ok"
            or base64.b64decode(str(record.get("base64")), validate=True) != expected_value
        ):
            raise ValueError("unsupported namespace/stacking")
    if not mapping(capture["runtime"]).get("image") or not mapping(capture["runtime"]).get(
        "kernel"
    ):
        raise ValueError("missing image/kernel identity")
    return {
        "schema": "quantos-apparmor-binding-proposal-v3",
        "raw_capture_sha256": digest(raw),
        "raw_inventory_sha256": digest(inventory_raw),
        "candidate_content_sha256": digest(canonical(content)),
        "source_correspondence_unresolved": True,
        "unknown_attachment_count": portable["unknown_attachment_count"],
        "collection_complete": capture.get("collection_complete") is True
        and capture.get("errors") == [],
        "load_authorized": False,
    }


def compare(left: bytes, right: bytes, expected_sha256: str | None = None) -> dict[str, object]:
    first, second = candidate(left), candidate(right)
    equal = first["candidate_content_sha256"] == second["candidate_content_sha256"]
    complete = first["collection_complete"] is True and second["collection_complete"] is True
    return {
        "left": first,
        "right": second,
        "content_equal": equal,
        "matches_explicit_digest": complete
        and expected_sha256 is not None
        and expected_sha256
        == first["candidate_content_sha256"]
        == second["candidate_content_sha256"],
        "load_authorized": False,
        "decision": "UNRESOLVED_SOURCE_REVIEW_REQUIRED"
        if complete
        else "REJECTED_INCOMPLETE_CAPTURE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()

    def read(path: Path) -> bytes:
        with path.open("rb") as stream:
            raw = stream.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError("capture size limit")
        return raw

    try:
        result = compare(read(args.left), read(args.right), args.expected_sha256)
    except (ValueError, KeyError, TypeError) as error:
        result = {"decision": "REJECTED", "error": str(error), "load_authorized": False}
    print(json.dumps(result, sort_keys=True, indent=2))
    # This candidate never substitutes for explicit provenance/attachment acceptance.
    raise SystemExit(1)


if __name__ == "__main__":
    main()
