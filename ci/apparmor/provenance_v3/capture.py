"""Bounded read-only policy sources; correspondence remains a manual unresolved question."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import resource
import stat
import subprocess
import sys
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

MAX_FILES = 512
MAX_FILE_BYTES = 65536
MAX_TOTAL_BYTES = 4 * 1024 * 1024
CONFIG = (
    "/etc/apparmor/parser.conf",
    "/etc/default/apparmor",
    "/usr/lib/systemd/system/apparmor.service",
    "/usr/lib/apparmor/apparmor.systemd",
    "/usr/lib/apparmor/functions",
    "/usr/lib/os-release",
)
NAMESPACE = (".ns_name", ".ns_level", ".ns_stacked", ".stacked")


@dataclass
class Reader:
    root: Path
    files: int = 0
    total: int = 0
    entries: int = 0

    def open(self, path: str, directory: bool = False) -> int:
        """No symlink in any component, even for a privileged collector."""
        parts = Path(path).parts
        if not path.startswith("/") or any(x in (".", "..") for x in path.split("/")):
            raise ValueError("unsafe source path")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(parts[1:]):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 2 or directory:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def read(self, path: str, binary: bool = False) -> dict[str, object]:
        if self.files >= MAX_FILES or self.total >= MAX_TOTAL_BYTES:
            return {"path": path, "status": "limit", "sha256": None}
        self.files += 1
        try:
            descriptor = self.open(path)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("not a regular policy file")
                limit = min(
                    MAX_TOTAL_BYTES - self.total, MAX_TOTAL_BYTES if binary else MAX_FILE_BYTES
                )
                chunks: list[bytes] = []
                count = 0
                while count <= limit:
                    block = os.read(descriptor, min(65536, limit + 1 - count))
                    if not block:
                        break
                    chunks.append(block)
                    count += len(block)
                raw = b"".join(chunks)
                self.total += len(raw)
                after = os.fstat(descriptor)
                if len(raw) > limit:
                    raise ValueError("byte limit exceeded")
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise ValueError("source changed during read")
            finally:
                os.close(descriptor)
            result: dict[str, object] = {
                "path": path,
                "status": "ok",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
            }
            if not binary:
                result["base64"] = base64.b64encode(raw).decode("ascii")
            return result
        except (OSError, ValueError) as error:
            return {
                "path": path,
                "status": "missing" if isinstance(error, FileNotFoundError) else "error",
                "sha256": None,
                "error": str(error),
            }

    def tree(self, path: str) -> tuple[list[str], list[str]]:
        files: list[str] = []
        errors: list[str] = []
        try:
            descriptor = self.open(path, directory=True)
            try:
                with os.scandir(descriptor) as entries:
                    names = sorted(
                        (entry.name, entry.is_dir(follow_symlinks=False))
                        for entry in islice(entries, MAX_FILES + 1)
                    )
                self.entries += len(names)
                if self.entries > MAX_FILES:
                    raise ValueError("directory entry limit exceeded")
                for name, is_directory in names:
                    child = path + "/" + name
                    if is_directory:
                        nested, failures = self.tree(child)
                        files.extend(nested)
                        errors.extend(failures)
                    else:
                        files.append(child)
            finally:
                os.close(descriptor)
        except (OSError, ValueError) as error:
            errors.append(f"{path}: {error}")
        return files, errors


def command(argv: tuple[str, ...]) -> dict[str, object]:
    """Only fixed dpkg metadata commands; no shell, provider or parser execution."""
    import tempfile

    # Temporary command scratch is not evidence: bounded bytes are returned to the report.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.run(
                argv,
                stdout=stdout,
                stderr=stderr,
                timeout=10,
                check=False,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144)),
            )
            stdout.seek(0)
            stderr.seek(0)
            raw = stdout.read(262145)
            err = stderr.read(8193)
            if len(raw) > 262144 or len(err) > 8192:
                return {
                    "argv": list(argv),
                    "status": "limit",
                    "exit": proc.returncode,
                    "stdout": raw[:262144].decode("utf-8", errors="replace"),
                    "stderr": err[:8192].decode("utf-8", errors="replace"),
                    "stdout_truncated": len(raw) > 262144,
                    "stderr_truncated": len(err) > 8192,
                }
            return {
                "argv": list(argv),
                "status": "ok" if proc.returncode == 0 else "error",
                "exit": proc.returncode,
                "stdout": raw.decode("utf-8"),
                "stderr": err.decode("utf-8"),
            }
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            return {"argv": list(argv), "status": "error", "exit": None, "error": str(error)}


def capture(
    raw_inventory: bytes, plan: dict[str, object], reader: Reader, image_version: str | None = None
) -> dict[str, object]:
    from ci.apparmor.provenance_v3.binding import items, mapping

    if plan.get("schema") != "quantos-apparmor-source-plan-v3":
        raise ValueError("unsupported source plan")
    entries = items(plan.get("files"))
    directories = items(plan.get("directories"))
    paths: set[str] = set()
    for value in entries:
        item = mapping(value)
        if not isinstance(item.get("path"), str):
            raise ValueError("invalid planned source")
        path = str(item["path"])
        if not path.startswith("/etc/apparmor.d/"):
            raise ValueError("source plan outside policy root")
        paths.add(path)
    listings: dict[str, object] = {}
    errors: list[str] = []
    for directory in directories:
        if not isinstance(directory, str) or not directory.startswith("/etc/apparmor.d/tunables/"):
            raise ValueError("unsupported planned include directory")
        files, failures = reader.tree(directory)
        listings[directory] = files
        paths.update(files)
        errors.extend(failures)
    sources = [reader.read(path) for path in sorted(paths)]
    settings = [reader.read(path) for path in CONFIG]
    features_root = "/sys/kernel/security/apparmor/features"
    features, failures = reader.tree(features_root)
    errors.extend(failures)
    feature_records = [reader.read(path) for path in features]
    namespace = [reader.read("/sys/kernel/security/apparmor/" + name) for name in NAMESPACE]
    binaries = [
        reader.read(path, binary=True) for path in ("/usr/sbin/apparmor_parser", "/usr/bin/bwrap")
    ]
    owned_paths = tuple(
        str(record["path"])
        for record in [*sources, *settings, *binaries]
        if record["status"] == "ok"
    )
    package_owners = (
        command(("/usr/bin/dpkg-query", "--search", "--", *owned_paths))
        if owned_paths
        else {"status": "missing", "exit": None, "stdout": "", "stderr": "no readable sources"}
    )
    owners: set[str] = {"apparmor"}
    output = package_owners.get("stdout")
    if isinstance(output, str):
        for line in output.splitlines():
            if ": " not in line:
                continue
            for owner in line.rsplit(": ", 1)[0].split(", "):
                if re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?", owner):
                    owners.add(owner)
    # Query only owners of the selected sources, not the whole installed database.
    package_versions = command(
        (
            "/usr/bin/dpkg-query",
            "--show",
            "--showformat=${Package}\t${Version}\t${Architecture}\n",
            *sorted(owners),
        )
    )
    for record in [*sources, *settings, *feature_records, *namespace, *binaries]:
        if record["status"] != "ok":
            errors.append(f"{record['path']}: {record['status']}")
    if package_owners.get("status") != "ok" or package_versions.get("status") != "ok":
        errors.append("package provenance metadata incomplete")
    return {
        "schema": "quantos-apparmor-provenance-v3",
        "inventory_sha256": hashlib.sha256(raw_inventory).hexdigest(),
        "inventory_raw_base64": base64.b64encode(raw_inventory).decode("ascii"),
        "plan": plan,
        "sources": sources,
        "include_directories": listings,
        "settings": settings,
        "features": feature_records,
        "namespace": namespace,
        "binaries": binaries,
        "packages": {
            "owners": package_owners,
            "versions": package_versions,
            "archive_origin": "UNRESOLVED",
        },
        "runtime": {"image": image_version, "kernel": platform.release()},
        "compilation_history": "UNRESOLVED",
        "source_to_loaded_correspondence": "UNRESOLVED",
        "collection_complete": not errors,
        "errors": errors,
        "budget": {"files": reader.files, "bytes": reader.total},
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ci.apparmor.provenance_v3.binding import items, mapping, project_inventory

    parsed_inventory: object = json.loads(raw)
    inventory = mapping(parsed_inventory)
    project_inventory(inventory)
    path = Path(__file__).with_name("source-plan.json")
    plan_value: object = json.loads(path.read_text())
    plan = mapping(plan_value)
    result = capture(raw, plan, Reader(Path("/")), image_version=args.image_version)
    # Keep policy changes during source acquisition observable, not just v2 collection.
    from ci.apparmor.identity_v2.collect import field

    result["revision_after_sources"] = field(Path("/sys/kernel/security/apparmor/policy/revision"))
    if result["revision_after_sources"] != inventory["revision_after"]:
        result["errors"] = [*items(result["errors"]), "policy changed during source acquisition"]
        result["collection_complete"] = False
    result["tool_sources"] = {
        str(path.relative_to(Path(__file__).resolve().parents[3])): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in (
            Path(__file__),
            Path(__file__).with_name("binding.py"),
            path,
            Path(__file__).parents[1] / "identity_v2/collect.py",
        )
    }
    output = json.dumps(result, sort_keys=True, indent=2)
    if len(output.encode("utf-8")) > 12 * 1024 * 1024:
        print(
            json.dumps(
                {
                    "status": "report_limit",
                    "inventory_sha256": args.inventory_sha256,
                    "load_authorized": False,
                }
            )
        )
        raise SystemExit(1)
    print(output)
    raise SystemExit(0 if result["collection_complete"] else 1)


if __name__ == "__main__":
    main()
