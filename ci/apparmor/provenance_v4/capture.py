"""Successor bounded source observation; never executes a loader or grants loading."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import stat
import sys
from itertools import islice
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ci.apparmor.provenance_v3.binding import items, mapping, project_inventory
from ci.apparmor.provenance_v3.capture import MAX_FILES, NAMESPACE, Reader, command
from ci.apparmor.provenance_v4.dependencies import ROOT, dependencies, policy_path

CONFIG = (
    "/etc/apparmor/parser.conf",
    "/etc/default/apparmor",
    "/usr/lib/systemd/system/apparmor.service",
    "/usr/lib/apparmor/apparmor.systemd",
    "/usr/lib/apparmor/rc.apparmor.functions",
    "/usr/lib/os-release",
)
ALIASES = {"/lib": "usr/lib", "/sbin": "usr/sbin"}
MAX_LISTING_BYTES = 128 * 1024


def aliases(reader: Reader) -> list[dict[str, object]]:
    """Observe only the two known usrmerge directory aliases, without following them."""
    records: list[dict[str, object]] = []
    descriptor = reader.open("/", directory=True)
    try:
        for path, expected in ALIASES.items():
            try:
                info = os.stat(path[1:], dir_fd=descriptor, follow_symlinks=False)
                target = (
                    os.readlink(path[1:], dir_fd=descriptor) if stat.S_ISLNK(info.st_mode) else None
                )
                if target is not None and target not in (expected, "/" + expected):
                    raise ValueError("unexpected usrmerge alias")
                if target is None and not stat.S_ISDIR(info.st_mode):
                    raise ValueError("not a directory or known usrmerge alias")
                records.append(
                    {"path": path, "status": "ok", "target": target, "mode": info.st_mode}
                )
            except (OSError, ValueError) as error:
                records.append({"path": path, "status": "error", "error": str(error)})
    finally:
        os.close(descriptor)
    return records


def root_listing(reader: Reader) -> dict[str, object]:
    """One level of names/types only; no automatic source selection or symlink read."""
    path = ROOT.rstrip("/")
    try:
        descriptor = reader.open(path, directory=True)
        try:
            with os.scandir(descriptor) as entries:
                names = sorted(
                    (entry.name, entry.is_dir(follow_symlinks=False), entry.is_symlink())
                    for entry in islice(entries, 257)
                )
            reader.entries += len(names)
            if len(names) > 256 or reader.entries > MAX_FILES:
                raise ValueError("policy root listing entry limit")
            encoded_bytes = len(json.dumps(names, ensure_ascii=True).encode("ascii"))
            if encoded_bytes > MAX_LISTING_BYTES:
                raise ValueError("policy root listing byte limit")
            return {
                "path": path,
                "status": "ok",
                "names": names,
                "encoded_bytes": encoded_bytes,
                "recursive": False,
            }
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:
        return {"path": path, "status": "error", "error": str(error)}


def ownership(
    paths: list[str],
    alias_records: list[dict[str, object]],
    observations: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
    queries = {path: [path] for path in paths}
    for record in alias_records:
        if record.get("status") == "ok" and record.get("target") is not None:
            logical = str(record["path"])
            canonical = "/" + ALIASES[logical]
            for path in paths:
                if path.startswith(canonical + "/"):
                    queries[path].append(logical + path[len(canonical) :])
    requested = {path for alternatives in queries.values() for path in alternatives}
    argv = ("/usr/bin/dpkg-query", "--search", "--", *sorted(requested))
    result = command(argv) if observations is None else mapping(observations["owners"])
    owners: dict[str, set[str]] = {path: set() for path in requested}
    unowned: set[str] = set()
    errors: list[str] = []
    if result.get("argv") != list(argv):
        errors.append("ownership query arguments do not match selected paths")
    for line in str(result.get("stdout", "")).splitlines():
        packages, separator, path = line.rpartition(": ")
        names = packages.split(", ")
        if (
            not separator
            or path not in requested
            or any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?", x) for x in names)
        ):
            errors.append("unresolved dpkg stdout record: " + line)
        else:
            owners[path].update(names)
    for line in str(result.get("stderr", "")).splitlines():
        prefix = "dpkg-query: no path found matching pattern "
        path = line.removeprefix(prefix)
        if not line.startswith(prefix) or path not in requested:
            errors.append("unresolved dpkg stderr record: " + line)
        else:
            unowned.add(path)
    records: list[dict[str, object]] = []
    for path, alternatives in sorted(queries.items()):
        evidence: list[dict[str, object]] = []
        for query in alternatives:
            state = "OWNED" if owners[query] else "UNOWNED" if query in unowned else "UNRESOLVED"
            if (owners[query] and query in unowned) or state == "UNRESOLVED":
                errors.append("unresolved/conflicting package ownership: " + query)
            evidence.append({"query_path": query, "state": state, "owners": sorted(owners[query])})
        records.append({"path": path, "queries": evidence})
    accounted_exit = 1 if unowned else 0
    if result.get("exit") != accounted_exit or result.get("status") not in ("ok", "error"):
        errors.append("dpkg ownership command failed beyond accounted unowned paths")
    packages = sorted({owner for names in owners.values() for owner in names})
    version_argv = (
        "/usr/bin/dpkg-query",
        "--show",
        "--showformat=${Package}\t${Version}\t${Architecture}\n",
        *packages,
    )
    versions = (
        (command(version_argv) if packages else {"status": "missing", "exit": None})
        if observations is None
        else mapping(observations["versions"])
    )
    if packages and versions.get("argv") != list(version_argv):
        errors.append("version query arguments do not match observed owners")
    if versions.get("status") != "ok":
        errors.append("package versions unavailable")
    return {
        "owners": result,
        "per_path": records,
        "versions": versions,
        "archive_origin": "UNRESOLVED",
    }, errors


def closure(
    sources: list[dict[str, object]], directories: list[dict[str, object]], plan: dict[str, object]
) -> dict[str, object]:
    """Classify observed literal dependencies, never the loaded-policy correspondence."""
    observed = {str(record["path"]): record for record in [*sources, *directories]}
    if len(observed) != len(sources) + len(directories):
        raise ValueError("duplicate source/directory observation")
    edges: list[dict[str, object]] = []
    errors: list[str] = []
    for record in sources:
        if record["status"] == "ok":
            try:
                found, failures = dependencies(
                    base64.b64decode(str(record["base64"]), validate=True)
                )
            except UnicodeError as error:
                errors.append(f"{record['path']}: unreadable dependency text: {error}")
                continue
            edges.extend({"source": record["path"], **edge} for edge in found)
            errors.extend(f"{record['path']}: {error}" for error in failures)
    required = {str(edge["path"]) for edge in edges if edge["if_exists"] is False}
    optional = {str(edge["path"]) for edge in edges if edge["if_exists"] is True}
    # Template-derived dependencies remain explicit investigation candidates until their
    # parent is actually observed. A plan boolean cannot waive a required dependency.
    roots = {
        str(path)
        for profile in items(plan["profiles"])
        for path in items(mapping(profile)["source_candidates"])
    }
    for profile_value in items(plan["profiles"]):
        profile = mapping(profile_value)
        candidates = items(profile["source_candidates"])
        if not candidates or not any(
            observed.get(str(path), {}).get("status") == "ok" for path in candidates
        ):
            errors.append("no readable root candidate for lineage: " + str(profile["lineage"]))
    absent: list[dict[str, object]] = []
    for path in sorted(required | optional | set(observed)):
        record = observed.get(path, {"status": "unplanned"})
        status = record["status"]
        if status == "ok":
            continue
        explicit_absence = status == "missing" and path in optional - required - roots
        classification = (
            "EXPLICIT_IF_EXISTS_ABSENT"
            if explicit_absence
            else "REQUIRED_DEPENDENCY_MISSING"
            if path in required
            else "INVESTIGATION_GAP"
        )
        absent.append({"path": path, "status": status, "classification": classification})
        if not explicit_absence:
            errors.append(f"{path}: {classification} ({status})")
    return {"literal_dependencies": edges, "missing": absent, "errors": errors}


def capture(
    raw_inventory: bytes, plan: dict[str, object], reader: Reader, image_version: str
) -> dict[str, object]:
    if plan.get("schema") != "quantos-apparmor-source-plan-v4":
        raise ValueError("unsupported source plan")
    entries = [mapping(item) for item in items(plan["files"])]
    paths = [policy_path(str(entry["path"])) for entry in entries]
    if len(paths) != len(set(paths)) or len(paths) > MAX_FILES:
        raise ValueError("duplicate/oversized source plan")
    sources: dict[str, dict[str, object]] = {}
    directories: list[dict[str, object]] = []
    errors: list[str] = []
    for path in sorted(paths):
        if path in sources:
            continue
        try:
            descriptor = reader.open(path)
            try:
                is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
            finally:
                os.close(descriptor)
        except (OSError, ValueError):
            is_directory = False
        if not is_directory:
            sources[path] = reader.read(path)
            continue
        children, failures = reader.tree(path)
        directories.append(
            {"path": path, "status": "error" if failures else "ok", "files": children}
        )
        errors.extend(failures)
        for child in children:
            try:
                policy_path(child)
            except ValueError as error:
                errors.append(f"{child}: {error}")
                continue
            if child not in sources:
                sources[child] = reader.read(child)
    alias_records = aliases(reader)
    listing = root_listing(reader)
    settings = [reader.read(path) for path in CONFIG]
    # On a non-usrmerged host read the loader's actual /lib paths separately.
    lib_record = next(record for record in alias_records if record["path"] == "/lib")
    if lib_record.get("status") == "ok" and lib_record.get("target") is None:
        settings.extend(
            reader.read("/lib/apparmor/" + name)
            for name in ("apparmor.systemd", "rc.apparmor.functions")
        )
    feature_paths, failures = reader.tree("/sys/kernel/security/apparmor/features")
    errors.extend(failures)
    features = [reader.read(path) for path in feature_paths]
    namespace = [reader.read("/sys/kernel/security/apparmor/" + name) for name in NAMESPACE]
    binaries = [
        reader.read(path, binary=True) for path in ("/usr/sbin/apparmor_parser", "/usr/bin/bwrap")
    ]
    source_records = list(sources.values())
    dependency_status = closure(source_records, directories, plan)
    errors.extend(str(error) for error in items(dependency_status["errors"]))
    for record in [*settings, *features, *namespace, *binaries, *alias_records, listing]:
        if record["status"] != "ok":
            errors.append(f"{record['path']}: {record['status']}")
    packages, failures = ownership(
        [
            str(record["path"])
            for record in [*source_records, *settings, *binaries]
            if record["status"] == "ok"
        ],
        alias_records,
    )
    errors.extend(failures)
    return {
        "schema": "quantos-apparmor-provenance-v4",
        "inventory_sha256": hashlib.sha256(raw_inventory).hexdigest(),
        "inventory_raw_base64": base64.b64encode(raw_inventory).decode("ascii"),
        "plan": plan,
        "sources": source_records,
        "include_directories": directories,
        "dependency_status": dependency_status,
        "settings": settings,
        "usrmerge_aliases": alias_records,
        "policy_root_listing": listing,
        "features": features,
        "namespace": namespace,
        "binaries": binaries,
        "packages": packages,
        "runtime": {"image": image_version, "kernel": platform.release()},
        "compilation_history": "UNRESOLVED",
        "source_to_loaded_correspondence": "UNRESOLVED",
        "collection_complete": not errors,
        "errors": errors,
        "budget": {"files": reader.files, "bytes": reader.total, "entries": reader.entries},
        "load_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--image-version", required=True)
    args = parser.parse_args()
    with args.inventory.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != args.inventory_sha256:
        raise SystemExit("inventory size/hash mismatch")
    inventory_value: object = json.loads(raw)
    inventory = mapping(inventory_value)
    project_inventory(inventory)
    plan_value: object = json.loads(Path(__file__).with_name("source-plan.json").read_bytes())
    os.environ["LC_ALL"] = "C"  # Exact dpkg diagnostics are classified, never discarded.
    result = capture(raw, mapping(plan_value), Reader(Path("/")), args.image_version)
    from ci.apparmor.identity_v2.collect import field

    result["revision_after_sources"] = field(Path("/sys/kernel/security/apparmor/policy/revision"))
    if result["revision_after_sources"] != inventory["revision_after"]:
        result["errors"] = [*items(result["errors"]), "policy changed during source acquisition"]
        result["collection_complete"] = False
    root = Path(__file__).resolve().parents[3]
    result["tool_sources"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(
            [
                *Path(__file__).parent.glob("*.py"),
                Path(__file__).with_name("source-plan.json"),
                root / "ci/apparmor/provenance_v3/binding.py",
                root / "ci/apparmor/provenance_v3/capture.py",
                root / "ci/apparmor/identity_v2/collect.py",
            ]
        )
    }
    output = json.dumps(result, sort_keys=True, indent=2)
    if len(output.encode()) > 12 * 1024 * 1024:
        print(json.dumps({"status": "report_limit", "load_authorized": False}))
        raise SystemExit(1)
    print(output)
    raise SystemExit(0 if result["collection_complete"] else 1)


if __name__ == "__main__":
    main()
