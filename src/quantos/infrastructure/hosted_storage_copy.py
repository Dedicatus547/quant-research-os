"""Verified independent Linux reflink copies; physical fallback needs a budget guard."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory
from quantos.contracts.base import canonical_json_bytes, sha256_bytes

FICLONE = 0x40049409
_UNSUPPORTED_REFLINK = frozenset(
    (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL, errno.ENOSYS)
)
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class ReflinkUnavailable(ArtifactIntegrityError):
    """The filesystem cannot clone extents and no physical fallback was authorized."""


@dataclass(frozen=True)
class VerifiedCopyReport:
    """Successful ioctl clones are counted separately from budgeted physical writes."""

    inventory_hash: str
    logical_bytes: int
    reflink_files: int
    physical_files: int
    physical_bytes: int


@dataclass(frozen=True)
class _Entry:
    path: str
    mode: int
    size: int
    digest: str | None
    identity: tuple[int, ...]

    def content(self) -> tuple[str, int, int, str | None]:
        return self.path, self.mode, self.size, self.digest


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    # Access times may change when the manager reads. All mutation identities remain bound.
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _file_entry(descriptor: int, path: str) -> _Entry:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ArtifactIntegrityError("copy source must be regular and have one link")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    length = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
        length += len(chunk)
    if _identity(os.fstat(descriptor)) != _identity(before) or length != before.st_size:
        raise ArtifactIntegrityError("file changed during verified copy inventory")
    return _Entry(path, stat.S_IMODE(before.st_mode), length, digest.hexdigest(), _identity(before))


def _snapshot(descriptor: int) -> tuple[_Entry, ...]:
    entries: list[_Entry] = []

    def walk(directory: int, prefix: str) -> None:
        before = os.fstat(directory)
        entries.append(_Entry(prefix, stat.S_IMODE(before.st_mode), 0, None, _identity(before)))
        with os.scandir(directory) as iterator:
            names = sorted(item.name for item in iterator)
        for name in names:
            logical = f"{prefix}/{name}" if prefix else name
            metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                child = os.open(name, _READ_FLAGS, dir_fd=directory)
            else:
                raise ArtifactIntegrityError("copy tree contains a symlink, alias or special file")
            try:
                if _identity(os.fstat(child)) != _identity(metadata):
                    raise ArtifactIntegrityError("copy tree entry changed during inventory")
                if stat.S_ISDIR(metadata.st_mode):
                    walk(child, logical)
                else:
                    entries.append(_file_entry(child, logical))
            finally:
                os.close(child)
        if _identity(os.fstat(directory)) != _identity(before):
            raise ArtifactIntegrityError("copy directory changed during inventory")

    walk(descriptor, "")
    return tuple(sorted(entries, key=lambda item: item.path))


def _content(entries: tuple[_Entry, ...]) -> tuple[tuple[str, int, int, str | None], ...]:
    return tuple(entry.content() for entry in entries)


def _report(entries: tuple[_Entry, ...], methods: list[tuple[bool, int]]) -> VerifiedCopyReport:
    return VerifiedCopyReport(
        inventory_hash=sha256_bytes(canonical_json_bytes(_content(entries))),
        logical_bytes=sum(size for _, size in methods),
        reflink_files=sum(cloned for cloned, _ in methods),
        physical_files=sum(not cloned for cloned, _ in methods),
        physical_bytes=sum(size for cloned, size in methods if not cloned),
    )


def _copy_file_at(
    source: int,
    destination: int,
    name: str,
    expected: _Entry,
    before_physical_copy: Callable[[int], None] | None,
    *,
    destination_name: str | None = None,
) -> tuple[bool, int]:
    original = os.open(name, _READ_FLAGS, dir_fd=source)
    copied: int | None = None
    try:
        if _file_entry(original, expected.path) != expected:
            raise ArtifactIntegrityError("source changed before verified copy")
        metadata = os.fstat(original)
        copied = os.open(
            destination_name or name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination,
        )
        try:
            fcntl.ioctl(copied, FICLONE, original)
        except OSError as error:
            if error.errno not in _UNSUPPORTED_REFLINK:
                raise
            if before_physical_copy is None:
                raise ReflinkUnavailable(
                    "reflink is unsupported; physical copy requires an explicit disk budget guard"
                ) from error
            before_physical_copy(expected.size)
            # A failed ioctl is never credited as saved space. Reset before budgeted copying.
            os.ftruncate(copied, 0)
            os.lseek(original, 0, os.SEEK_SET)
            os.lseek(copied, 0, os.SEEK_SET)
            remaining = expected.size
            while remaining:
                chunk = os.read(original, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ArtifactIntegrityError("source shrank during physical copy") from None
                pending = memoryview(chunk)
                while pending:
                    written = os.write(copied, pending)
                    if written == 0:
                        raise ArtifactIntegrityError("physical copy made no progress") from None
                    pending = pending[written:]
                remaining -= len(chunk)
            if os.read(original, 1):
                raise ArtifactIntegrityError("source grew during physical copy") from None
            cloned = False
        else:
            cloned = True
        os.fchmod(copied, expected.mode)
        os.utime(copied, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        os.fsync(copied)
        if _file_entry(copied, expected.path).content() != expected.content():
            raise ArtifactIntegrityError("copied bytes or mode differ from original")
        if _file_entry(original, expected.path) != expected:
            raise ArtifactIntegrityError("source changed during verified copy")
        if _identity(os.stat(name, dir_fd=source, follow_symlinks=False)) != expected.identity:
            raise ArtifactIntegrityError("source pathname changed during verified copy")
        if _identity(
            os.stat(destination_name or name, dir_fd=destination, follow_symlinks=False)
        ) != _identity(os.fstat(copied)):
            raise ArtifactIntegrityError("destination pathname changed during verified copy")
        return cloned, expected.size
    finally:
        if copied is not None:
            os.close(copied)
        os.close(original)


def physical_copy_budget(total_bytes: int, reserve: Callable[[int], None]) -> Callable[[int], None]:
    """Reserve a known complete copy once and account for each physical file.

    The existing storage supervisor continues monitoring both filesystems. This
    avoids repeating the complete layout/lease check for thousands of tiny files.
    """
    if total_bytes < 0:
        raise ArtifactIntegrityError("physical copy budget must be nonnegative")
    consumed = 0
    reserved = False

    def before_copy(size: int) -> None:
        nonlocal consumed, reserved
        if size < 0 or consumed + size > total_bytes:
            raise ArtifactIntegrityError("physical copy exceeds reserved tree size")
        if not reserved:
            reserve(total_bytes)
            reserved = True
        consumed += size

    return before_copy


def copy_tree_verified(
    source: Path,
    destination: Path,
    *,
    before_physical_copy: Callable[[int], None] | None = None,
    reserve_physical_copy: Callable[[int], None] | None = None,
) -> VerifiedCopyReport:
    """Clone a new tree, verifying all files, empty directories and permission modes.

    Sources must already be normalized: symlinks (including Python aliases), hardlinks
    and special files are rejected. Source hashes and mutation identities are checked
    before and after copying. Each destination file has its own inode. Unsupported
    reflinks fail closed unless a caller-supplied disk budget guard authorizes each
    physical file's full logical size before its first write. Alternatively,
    reserve_physical_copy reserves the complete inventoried tree before its first
    physical write and accounts for each file against that bound. Failed copies retain
    their incomplete destination for the caller's staging cleanup policy.
    """
    if before_physical_copy is not None and reserve_physical_copy is not None:
        raise ArtifactIntegrityError("choose one physical copy reservation method")
    source_absolute, destination_absolute = source.absolute(), destination.absolute()
    if (
        source_absolute == destination_absolute
        or source_absolute in destination_absolute.parents
        or destination_absolute in source_absolute.parents
    ):
        raise ArtifactIntegrityError("verified copy source and destination overlap")
    methods: list[tuple[bool, int]] = []
    with opened_directory(source) as source_fd:
        before = _snapshot(source_fd)
        if reserve_physical_copy is not None:
            before_physical_copy = physical_copy_budget(
                sum(entry.size for entry in before), reserve_physical_copy
            )
        expected = {entry.path: entry for entry in before}
        with opened_directory(destination.parent, create=True) as parent_fd:
            os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
            destination_fd = os.open(
                destination.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:

                def walk(original: int, copied: int, prefix: str) -> None:
                    with os.scandir(original) as iterator:
                        names = sorted(item.name for item in iterator)
                    for name in names:
                        logical = f"{prefix}/{name}" if prefix else name
                        entry = expected.get(logical)
                        if entry is None:
                            raise ArtifactIntegrityError("source file set changed during copy")
                        if entry.digest is not None:
                            methods.append(
                                _copy_file_at(original, copied, name, entry, before_physical_copy)
                            )
                            continue
                        os.mkdir(name, mode=0o700, dir_fd=copied)
                        original_child = os.open(
                            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=original
                        )
                        try:
                            copied_child = os.open(
                                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=copied
                            )
                            try:
                                if _identity(os.fstat(original_child)) != entry.identity:
                                    raise ArtifactIntegrityError(
                                        "source directory changed before copy"
                                    )
                                walk(original_child, copied_child, logical)
                            finally:
                                os.close(copied_child)
                        finally:
                            os.close(original_child)
                    metadata = os.fstat(original)
                    os.fchmod(copied, expected[prefix].mode)
                    os.utime(copied, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                    os.fsync(copied)

                walk(source_fd, destination_fd, "")
                if _snapshot(source_fd) != before:
                    raise ArtifactIntegrityError("source tree changed during verified copy")
                with opened_directory(source) as reopened:
                    if _identity(os.fstat(reopened)) != before[0].identity:
                        raise ArtifactIntegrityError("source root pathname changed during copy")
                if _content(_snapshot(destination_fd)) != _content(before):
                    raise ArtifactIntegrityError("destination tree inventory differs from source")
                os.fsync(parent_fd)
            finally:
                os.close(destination_fd)
    return _report(before, methods)


def copy_file_verified(
    source: Path,
    destination: Path,
    *,
    before_physical_copy: Callable[[int], None] | None = None,
) -> VerifiedCopyReport:
    """Apply the same verified independent-copy policy to a single regular file."""
    with opened_directory(source.parent) as source_fd:
        descriptor = os.open(source.name, _READ_FLAGS, dir_fd=source_fd)
        try:
            expected = _file_entry(descriptor, source.name)
        finally:
            os.close(descriptor)
        with opened_directory(destination.parent, create=True) as destination_fd:
            method = _copy_file_at(
                source_fd,
                destination_fd,
                source.name,
                expected,
                before_physical_copy,
                destination_name=destination.name,
            )
            with opened_directory(source.parent) as reopened:
                if (os.fstat(reopened).st_dev, os.fstat(reopened).st_ino) != (
                    os.fstat(source_fd).st_dev,
                    os.fstat(source_fd).st_ino,
                ):
                    raise ArtifactIntegrityError("source parent pathname changed during copy")
            with opened_directory(destination.parent) as reopened:
                if (os.fstat(reopened).st_dev, os.fstat(reopened).st_ino) != (
                    os.fstat(destination_fd).st_dev,
                    os.fstat(destination_fd).st_ino,
                ):
                    raise ArtifactIntegrityError("destination parent pathname changed during copy")
            os.fsync(destination_fd)
    return _report((replace(expected, path=destination.name),), [method])
