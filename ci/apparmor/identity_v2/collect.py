"""Read-only, grouped AppArmor identity collection; never approves or loads policy."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path

POLICY = Path("/sys/kernel/security/apparmor/policy")
MAX_PROFILES = 512
MAX_FIELD_BYTES = 8192


def field(path: Path) -> dict[str, object]:
    """Keep unavailable and empty fields distinct from literal <unknown>."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            raw = os.read(descriptor, MAX_FIELD_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_FIELD_BYTES:
            return {"status": "too_large", "value": None}
        return {
            "status": "ok" if raw else "empty",
            "value": raw.decode("utf-8"),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    except OSError as error:
        return {
            "status": "missing" if error.errno == errno.ENOENT else "error",
            "value": None,
            "errno": error.errno,
        }
    except UnicodeError:
        return {"status": "invalid_utf8", "value": None}


def collect(policy: Path = POLICY) -> dict[str, object]:
    """The path parameter is for synthetic fixtures; CLI always uses POLICY."""
    before = field(policy / "revision")
    records: list[dict[str, object]] = []
    errors: list[str] = []
    unknown = 0

    def walk(container: Path) -> None:
        nonlocal unknown
        for directory in sorted(container.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(f"unexpected profile entry: {directory}")
            if len(records) >= MAX_PROFILES:
                raise ValueError("profile count exceeds bounded collection limit")
            required = {name: field(directory / name) for name in ("name", "mode", "attach")}
            optional = {
                name: field(directory / name) for name in ("sha256", "raw_sha256", "raw_abi")
            }
            links: dict[str, object] = {}
            for name in ("raw_data", "raw_sha256", "raw_abi"):
                try:
                    links[name] = {"status": "ok", "target": os.readlink(directory / name)}
                except OSError as error:
                    links[name] = {
                        "status": "missing" if error.errno == errno.ENOENT else "error",
                        "target": None,
                        "errno": error.errno,
                    }
            record: dict[str, object] = {
                "directory": str(directory.relative_to(policy)),
                "fields": required,
                "loaded_metadata": optional,
                "links": links,
            }
            records.append(record)
            if any(value["status"] != "ok" for value in required.values()):
                errors.append(f"incomplete required fields: {directory}")
            if required["attach"].get("value") == "<unknown>\n":
                unknown += 1
            children = directory / "profiles"
            if children.is_symlink():
                raise ValueError(f"unexpected child profile symlink: {children}")
            if children.exists():
                walk(children)

    try:
        walk(policy / "profiles")
        # Other policy namespaces need separate review; never silently omit them.
        namespaces = sorted(path.name for path in (policy / "namespaces").iterdir())
        if namespaces:
            errors.append("additional policy namespaces require separate collection and review")
    except (OSError, ValueError) as error:
        errors.append(str(error))
        namespaces = None
    after = field(policy / "revision")
    stable = before["status"] == after["status"] == "ok" and before == after
    if not stable:
        errors.append("policy revision unavailable or changed during collection")
    if not records:
        errors.append("no profiles collected")
    return {
        "schema": "quantos-apparmor-identity-v2",
        "policy_root": str(policy),
        "revision_before": before,
        "revision_after": after,
        "profiles": records,
        "profile_count": len(records),
        "unknown_attachment_count": unknown,
        "other_namespaces": namespaces,
        "errors": errors,
        "collection_complete": not errors,
        "attachment_review": "UNREVIEWED",
        "load_authorized": False,
    }


if __name__ == "__main__":
    result = collect()
    print(json.dumps(result, sort_keys=True, indent=2))
    raise SystemExit(0 if result["collection_complete"] else 1)
