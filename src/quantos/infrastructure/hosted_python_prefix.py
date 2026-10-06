"""Normalize an explicit Python prefix without weakening general copy isolation."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure.hosted_storage_copy import copy_file_verified, physical_copy_budget

_MAX_ENTRIES = 20_000
_MAX_DEPTH = 64
_MAX_BYTES = 512 * 1024 * 1024
_MAX_ALIAS_HOPS = 40
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@dataclass(frozen=True)
class _Entry:
    path: str
    kind: str
    mode: int
    size: int
    digest: str | None
    link: str | None
    identity: tuple[int, ...]

    def content(self) -> tuple[str, str, int, int, str | None, str | None]:
        return self.path, self.kind, self.mode, self.size, self.digest, self.link


@dataclass(frozen=True)
class PythonPrefixNormalizationReport:
    schema_version: str
    source_hash: str
    source_inventory_hash: str
    inventory_hash: str
    source_before_after_equal: bool
    aliases: dict[str, str]
    logical_bytes: int
    reflink_files: int
    reflink_bytes: int
    physical_files: int
    physical_bytes: int


def _snapshot(descriptor: int) -> tuple[_Entry, ...]:
    entries: list[_Entry] = []
    total_bytes = 0

    def add(entry: _Entry) -> None:
        if len(entries) >= _MAX_ENTRIES:
            raise ArtifactIntegrityError("Python prefix exceeds entry bound")
        entries.append(entry)

    def walk(directory: int, prefix: str, depth: int) -> None:
        nonlocal total_bytes
        if depth > _MAX_DEPTH:
            raise ArtifactIntegrityError("Python prefix exceeds directory depth bound")
        before = os.fstat(directory)
        add(
            _Entry(
                prefix, "directory", stat.S_IMODE(before.st_mode), 0, None, None, _identity(before)
            )
        )
        with os.scandir(directory) as iterator:
            names: list[str] = []
            for item in iterator:
                names.append(item.name)
                if len(names) > _MAX_ENTRIES:
                    raise ArtifactIntegrityError("Python prefix exceeds entry bound")
        for name in sorted(names):
            logical = f"{prefix}/{name}" if prefix else name
            metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                link = os.readlink(name, dir_fd=directory)
                if _identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) != (
                    _identity(metadata)
                ):
                    raise ArtifactIntegrityError("Python prefix alias changed during inventory")
                add(
                    _Entry(
                        logical,
                        "alias",
                        mode,
                        metadata.st_size,
                        sha256_bytes(os.fsencode(link)),
                        link,
                        _identity(metadata),
                    )
                )
                continue
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                try:
                    if _identity(os.fstat(child)) != _identity(metadata):
                        raise ArtifactIntegrityError("Python prefix directory changed")
                    walk(child, logical, depth + 1)
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ArtifactIntegrityError("Python prefix contains an alias or special file")
            total_bytes += metadata.st_size
            if total_bytes > _MAX_BYTES:
                raise ArtifactIntegrityError("Python prefix exceeds byte bound")
            child = os.open(name, _READ_FLAGS, dir_fd=directory)
            try:
                if _identity(os.fstat(child)) != _identity(metadata):
                    raise ArtifactIntegrityError("Python prefix file changed before inventory")
                digest = hashlib.sha256()
                length = 0
                while chunk := os.read(child, 1024 * 1024):
                    length += len(chunk)
                    if length > metadata.st_size:
                        raise ArtifactIntegrityError("Python prefix file grew during inventory")
                    digest.update(chunk)
                if length != metadata.st_size or _identity(os.fstat(child)) != _identity(metadata):
                    raise ArtifactIntegrityError("Python prefix file changed during inventory")
                add(
                    _Entry(
                        logical, "file", mode, length, digest.hexdigest(), None, _identity(metadata)
                    )
                )
            finally:
                os.close(child)
        if _identity(os.fstat(directory)) != _identity(before):
            raise ArtifactIntegrityError("Python prefix directory changed during inventory")

    walk(descriptor, "", 0)
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _alias_targets(source: Path, entries: tuple[_Entry, ...]) -> dict[str, str]:
    indexed = {entry.path: entry for entry in entries}
    resolved: dict[str, str] = {}

    def resolve(name: str, visiting: tuple[str, ...]) -> str:
        if name in visiting or len(visiting) >= _MAX_ALIAS_HOPS:
            raise ArtifactIntegrityError("Python prefix alias is cyclic or exceeds hop bound")
        entry = indexed.get(name)
        if entry is None:
            raise ArtifactIntegrityError("Python prefix alias target is unavailable")
        if entry.kind == "file":
            return name
        if entry.kind != "alias" or entry.link is None:
            raise ArtifactIntegrityError("Python prefix alias must target a regular file")
        link = Path(entry.link)
        if link.is_absolute():
            if link.parts[: len(source.parts)] != source.parts:
                raise ArtifactIntegrityError("Python prefix alias escapes its explicit source")
            parts = link.parts[len(source.parts) :]
            components: list[str] = []
        else:
            parts = link.parts
            components = list(Path(name).parent.parts)
        for position, part in enumerate(parts):
            if part == "..":
                if not components:
                    raise ArtifactIntegrityError("Python prefix alias escapes its explicit source")
                components.pop()
                continue
            components.append(part)
            if position != len(parts) - 1:
                parent_entry = indexed.get("/".join(components))
                if parent_entry is None or parent_entry.kind != "directory":
                    raise ArtifactIntegrityError("Python prefix alias traverses a directory alias")
        return resolve("/".join(components), (*visiting, name))

    for entry in entries:
        if entry.kind == "alias":
            resolved[entry.path] = resolve(entry.path, ())
    return resolved


def normalize_python_prefix(
    source: Path,
    destination: Path,
    *,
    before_physical_copy: Callable[[int], None],
) -> PythonPrefixNormalizationReport:
    """Copy a bounded Python prefix, materializing only internal file aliases.

    The caller supplies the active disk budget guard. Existing destinations, directory
    aliases, hard links and special files are rejected; failed staging is retained.
    Every copied file gets its own inode, through the existing verified COW helper.
    """
    source, destination = source.absolute(), destination.absolute()
    if ".." in source.parts or ".." in destination.parts:
        raise ArtifactIntegrityError("Python prefix paths must not contain traversal")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ArtifactIntegrityError("Python prefix source and destination overlap")
    with opened_directory(source) as source_fd:
        before = _snapshot(source_fd)
        indexed = {entry.path: entry for entry in before}
        if (
            indexed.get("bin/python3.11") is None
            or indexed["bin/python3.11"].kind != "file"
            or indexed.get("lib/python3.11") is None
            or indexed["lib/python3.11"].kind != "directory"
        ):
            raise ArtifactIntegrityError("Python prefix lacks the explicit Python 3.11 layout")
        aliases = _alias_targets(source, before)
        expected: list[tuple[str, str, int, int, str | None, None]] = []
        for entry in before:
            original = indexed[aliases[entry.path]] if entry.kind == "alias" else entry
            expected.append(
                (entry.path, original.kind, original.mode, original.size, original.digest, None)
            )
        logical_bytes = sum(entry[3] for entry in expected if entry[1] == "file")
        if logical_bytes > _MAX_BYTES:
            raise ArtifactIntegrityError("Normalized Python prefix exceeds byte bound")
        copy_budget = physical_copy_budget(logical_bytes, before_physical_copy)
        reflink_files = physical_files = physical_bytes = reflink_bytes = 0
        with opened_directory(destination.parent, create=True) as parent_fd:
            os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
            with opened_directory(destination) as destination_fd:
                root_identity = _identity(os.fstat(destination_fd))[:2]
                for entry in before:
                    if entry.kind == "directory":
                        if entry.path:
                            with opened_directory(destination / entry.path, create=True):
                                pass
                        continue
                    target = aliases.get(entry.path, entry.path)
                    if _identity((source / target).lstat()) != indexed[target].identity:
                        raise ArtifactIntegrityError("Python prefix target changed before copy")
                    report = copy_file_verified(
                        source / target,
                        destination / entry.path,
                        before_physical_copy=copy_budget,
                    )
                    reflink_files += report.reflink_files
                    physical_files += report.physical_files
                    physical_bytes += report.physical_bytes
                    reflink_bytes += report.logical_bytes - report.physical_bytes
                for entry in reversed(before):
                    if entry.kind == "directory":
                        with opened_directory(destination / entry.path) as directory_fd:
                            os.fchmod(directory_fd, entry.mode)
                            os.fsync(directory_fd)
                after = _snapshot(source_fd)
                if after != before:
                    raise ArtifactIntegrityError(
                        "Python prefix source changed during normalization"
                    )
                with opened_directory(source) as reopened:
                    if _identity(os.fstat(reopened)) != before[0].identity:
                        raise ArtifactIntegrityError("Python prefix source pathname changed")
                observed = _snapshot(destination_fd)
                if tuple(entry.content() for entry in observed) != tuple(expected):
                    raise ArtifactIntegrityError("Normalized Python prefix differs from derivation")
                with opened_directory(destination) as reopened:
                    if _identity(os.fstat(reopened))[:2] != root_identity:
                        raise ArtifactIntegrityError("Normalized Python prefix pathname changed")
                os.fsync(parent_fd)
    return PythonPrefixNormalizationReport(
        schema_version="hosted-python-prefix-normalization/v1",
        source_hash=sha256_bytes(canonical_json_bytes([asdict(entry) for entry in before])),
        source_inventory_hash=sha256_bytes(
            canonical_json_bytes([entry.content() for entry in before])
        ),
        inventory_hash=sha256_bytes(canonical_json_bytes(expected)),
        source_before_after_equal=True,
        aliases=aliases,
        logical_bytes=logical_bytes,
        reflink_files=reflink_files,
        reflink_bytes=reflink_bytes,
        physical_files=physical_files,
        physical_bytes=physical_bytes,
    )
