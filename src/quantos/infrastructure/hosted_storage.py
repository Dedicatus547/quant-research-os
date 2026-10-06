"""Management resource safety; these observations never confer research qualification."""

from __future__ import annotations

import fcntl
import json
import os
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes

GIB = 1 << 30
POLICY_ENV = "QUANTOS_STORAGE_POLICY"
HASH_ENV = "QUANTOS_STORAGE_POLICY_SHA256"
LEASE_ENV = "QUANTOS_STORAGE_LEASE"
STARTUP_BRIDGE = """import json,os,sys
if os.read(0,1)!=b'G': raise SystemExit(125)
os.close(0)
descriptor=os.open('/dev/null',os.O_RDONLY)
if descriptor!=0:
 os.dup2(descriptor,0); os.close(descriptor)
os.set_inheritable(0,True)
argv=json.loads(sys.argv[1])
os.execvpe(argv[0],argv,dict(os.environ))
"""


class StorageRejected(ArtifactIntegrityError):
    """Fixed safe code only: never interpolate paths, argv, environment or exceptions."""


@dataclass(frozen=True)
class StoragePolicy:
    evidence_root: Path
    scratch_root: Path
    host_volume: Path
    vhd_file: Path
    linux_reserve_bytes: int
    host_reserve_bytes: int
    scratch_quota_bytes: int
    poll_seconds: float = 1.0
    terminate_grace_seconds: float = 10.0

    def __post_init__(self) -> None:
        if any(not path.is_absolute() for path in self.paths):
            raise StorageRejected("STORAGE_PATH_NOT_ABSOLUTE")
        if (
            self.linux_reserve_bytes < GIB
            or self.host_reserve_bytes < GIB
            or self.scratch_quota_bytes <= 0
            or not 0 < self.poll_seconds <= 5
            or not 0 < self.terminate_grace_seconds <= 30
        ):
            raise StorageRejected("STORAGE_POLICY_INVALID")

    @property
    def paths(self) -> tuple[Path, ...]:
        return self.evidence_root, self.scratch_root, self.host_volume, self.vhd_file

    def canonical_bytes(self) -> bytes:
        value = asdict(self)
        for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
            value[key] = str(value[key])
        return canonical_json_bytes(value)


def _plain_path(path: Path) -> Path:
    # resolve() alone silently accepts symlink aliases, including parent aliases.
    if ".." in path.parts:
        raise StorageRejected("STORAGE_PATH_ALIAS")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise StorageRejected("STORAGE_PATH_ALIAS")
    return path.resolve(strict=True)


def _mount(path: Path) -> tuple[str, Path]:
    """Find the longest mount prefix; no credentials or process command lines."""
    best: tuple[str, Path] | None = None
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        encoded = before.split()[4]
        for code, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
            encoded = encoded.replace(code, char)
        mount = Path(encoded)
        if path.is_relative_to(mount) and (best is None or len(mount.parts) > len(best[1].parts)):
            best = after.split()[0], mount
    if best is None:
        raise StorageRejected("STORAGE_MOUNT_UNAVAILABLE")
    return best


def _capacity(path: Path) -> tuple[int, int, int]:
    value = os.statvfs(path)
    return value.f_bavail * value.f_frsize, value.f_blocks * value.f_frsize, value.f_favail


def storage_mount_identity(path: Path) -> tuple[str, Path]:
    """Expose the same actual mount observation used by the resource guard."""
    return _mount(path)


@lru_cache(maxsize=4)
def _bwrap_size_support(identity: tuple[int, ...]) -> bool:
    result = subprocess.run(
        ("/usr/bin/bwrap", "--help"),
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
    )
    observed = Path("/usr/bin/bwrap").stat()
    after = (
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )
    return result.returncode == 0 and b"--size " in result.stdout and identity == after


def require_bounded_bwrap() -> None:
    value = Path("/usr/bin/bwrap").stat()
    identity = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if not _bwrap_size_support(identity):
        raise StorageRejected("STORAGE_BWRAP_HARD_QUOTA_UNAVAILABLE")


def _namespace_pidfd(wrapper: int, info_fd: int) -> int | None:
    raw = os.pread(info_fd, 4097, 0)
    if not raw:
        return None
    if len(raw) > 4096:
        raise StorageRejected("STORAGE_NAMESPACE_INFORMATION_INVALID")
    # bubblewrap writes its JSON in several writes. The strict worker bridge
    # keeps init alive while the complete record becomes available.
    if not raw.rstrip().endswith(b"}"):
        return None
    try:
        info = json.loads(raw)
        pid = info["child-pid"]
        if type(pid) is not int or pid <= 1:
            raise ValueError
        from quantos.infrastructure.hosted_regression_runtime import native_pidfd_open

        descriptor = native_pidfd_open(pid)
        try:
            lines = Path(f"/proc/{pid}/status").read_text().splitlines()
            fields = dict(line.split(":", 1) for line in lines if ":" in line)
            namespace = os.readlink(f"/proc/{pid}/ns/pid")
            if (
                int(fields["PPid"].strip()) != wrapper
                or namespace != f"pid:[{info['pid-namespace']}]"
                or namespace == os.readlink("/proc/self/ns/pid")
            ):
                raise ValueError
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor
    except (OSError, ValueError, KeyError, TypeError):
        raise StorageRejected("STORAGE_NAMESPACE_INFORMATION_UNAVAILABLE") from None


class StorageGuard:
    def __init__(self, policy: StoragePolicy) -> None:
        self.policy = policy
        self.policy_hash = sha256_bytes(policy.canonical_bytes())

    def validate_layout(self) -> None:
        p = self.policy
        evidence, scratch, volume, vhd = tuple(_plain_path(path) for path in p.paths)
        if not all(path.is_dir() for path in (evidence, scratch, volume)):
            raise StorageRejected("STORAGE_DIRECTORY_REQUIRED")
        if evidence.is_relative_to(Path("/tmp")) or evidence.is_relative_to(Path("/var/tmp")):
            raise StorageRejected("STORAGE_EVIDENCE_TEMPORARY")
        if evidence.is_relative_to(scratch) or scratch.is_relative_to(evidence):
            raise StorageRejected("STORAGE_ROOTS_OVERLAP")
        evidence_type, _ = _mount(evidence)
        scratch_type, scratch_mount = _mount(scratch)
        host_type, host_mount = _mount(volume)
        if evidence_type in {"tmpfs", "ramfs", "9p", "drvfs"}:
            raise StorageRejected("STORAGE_EVIDENCE_NOT_PERSISTENT_LINUX")
        if (
            host_type not in {"9p", "drvfs"}
            or volume != host_mount
            or not vhd.is_relative_to(volume)
            or not stat.S_ISREG(vhd.stat().st_mode)
            or vhd.stat().st_dev != volume.stat().st_dev
        ):
            raise StorageRejected("STORAGE_VHD_VOLUME_UNBOUND")
        # A polling directory-size limit is not a hard quota. Initially support an
        # independently mounted finite tmpfs only; project quotas need a verifier.
        if scratch_type != "tmpfs" or scratch_mount != scratch:
            raise StorageRejected("STORAGE_SCRATCH_HARD_QUOTA_UNAVAILABLE")
        if _capacity(scratch)[1] > p.scratch_quota_bytes:
            raise StorageRejected("STORAGE_SCRATCH_QUOTA_EXCEEDS_POLICY")

    def check(self, expected_new_bytes: int = 0) -> dict[str, int]:
        if expected_new_bytes < 0:
            raise StorageRejected("STORAGE_ESTIMATE_INVALID")
        self.validate_layout()
        p = self.policy
        linux, _, inodes = _capacity(p.evidence_root)
        host, _, _ = _capacity(p.host_volume)
        scratch, _, scratch_inodes = _capacity(p.scratch_root)
        facts = {
            "linux_available_bytes": linux,
            "host_available_bytes": host,
            "scratch_available_bytes": scratch,
            "linux_available_inodes": inodes,
        }
        if linux < p.linux_reserve_bytes + expected_new_bytes:
            raise StorageRejected("STORAGE_LINUX_HEADROOM")
        # Reserve the entire logical growth on the host even when Linux can reuse
        # free extents; a sparse VHD is not guaranteed to avoid host allocation.
        if host < p.host_reserve_bytes + expected_new_bytes:
            raise StorageRejected("STORAGE_HOST_HEADROOM")
        if inodes < 1024 or scratch_inodes == 0 or scratch < 1 << 20:
            raise StorageRejected("STORAGE_METADATA_OR_SCRATCH_HEADROOM")
        return facts

    def require_root(self, root: Path) -> None:
        # New output roots need not exist yet, but all existing parents must be plain.
        root = root.absolute()
        parent = root
        while not parent.exists() and not parent.is_symlink():
            parent = parent.parent
        _plain_path(parent)
        if ".." in root.parts or not root.is_relative_to(self.policy.evidence_root):
            raise StorageRejected("STORAGE_OUTPUT_OUTSIDE_EVIDENCE")

    def require_lease(self) -> None:
        name = os.environ.get(LEASE_ENV)
        if name is None:
            raise StorageRejected("STORAGE_SUPERVISOR_UNAVAILABLE")
        run = _plain_path(Path(name))
        control = self.policy.evidence_root / "storage-control"
        if run.parent != control:
            raise StorageRejected("STORAGE_SUPERVISOR_UNBOUND")
        with (run / "prelaunch.json").open("rb") as stream:
            data = json.loads(stream.read(16385))
        if data.get("policy_hash") != self.policy_hash:
            raise StorageRejected("STORAGE_SUPERVISOR_UNBOUND")
        if data.get("stage") == "local-validation":
            raise StorageRejected("STORAGE_LOCAL_LEASE_NOT_FORMAL")
        descriptor = os.open(control / "lease.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                owner = json.loads(os.pread(descriptor, 16385, 0))
                if owner != {"run": str(run), "policy_hash": self.policy_hash}:
                    raise StorageRejected("STORAGE_SUPERVISOR_UNBOUND") from None
                return
            raise StorageRejected("STORAGE_SUPERVISOR_NOT_RUNNING")
        finally:
            os.close(descriptor)


def configured_guard() -> StorageGuard:
    """Read only two non-secret management settings; never inspect other env keys."""
    name, digest = os.environ.get(POLICY_ENV), os.environ.get(HASH_ENV)
    if name is None or digest is None:
        raise StorageRejected("STORAGE_POLICY_UNAVAILABLE")
    path = _plain_path(Path(name))
    with opened_directory(path.parent) as parent:
        encoded = read_regular_bytes_at(parent, path.name, max_bytes=16384)
    if sha256_bytes(encoded) != digest:
        raise StorageRejected("STORAGE_POLICY_HASH_MISMATCH")
    try:
        data = json.loads(encoded)
        for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"):
            data[key] = Path(data[key])
        policy = StoragePolicy(**data)
    except (TypeError, ValueError, KeyError):
        raise StorageRejected("STORAGE_POLICY_INVALID") from None
    if policy.canonical_bytes() != encoded:
        raise StorageRejected("STORAGE_POLICY_NONCANONICAL")
    return StorageGuard(policy)


def storage_checkpoint(
    root: Path, stage: str, expected_new_bytes: int = 0, mount_policy_hash: str | None = None
) -> None:
    if stage not in {"deployment", "ci", "matrix", "export", "replay"}:
        raise StorageRejected("STORAGE_STAGE_INVALID")
    try:
        if mount_policy_hash is not None:
            from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES

            if mount_policy_hash != sha256_bytes(MOUNT_POLICY_BYTES):
                raise StorageRejected("STORAGE_LEGACY_MOUNT_EXECUTION_FORBIDDEN")
        guard = configured_guard()
        guard.require_root(root)
        guard.require_lease()
        guard.check(expected_new_bytes)
        require_bounded_bwrap()
    except (OSError, ValueError, KeyError, TypeError):
        raise StorageRejected("STORAGE_OBSERVATION_UNAVAILABLE") from None


def supervise_storage_job(
    guard: StorageGuard, argv: tuple[str, ...], *, stage: str, expected_new_bytes: int
) -> Path:
    """Single host job lease, bounded monitoring, actual wait, immutable safe records.

    The complete job estimate includes parallel children, all retained evidence,
    caches and exports. An exclusive lease avoids cross-job overbooking. The job
    remains responsible for child namespace cleanup using its existing manager.
    """
    if stage not in {"deployment", "ci", "matrix", "export", "local-validation", "replay"}:
        raise StorageRejected("STORAGE_STAGE_INVALID")
    guard.validate_layout()
    control = guard.policy.evidence_root / "storage-control"
    control.mkdir(mode=0o700, exist_ok=True)
    _plain_path(control)
    lock = os.open(control / "lease.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    process: subprocess.Popen[bytes] | None = None
    launch_attempted = False
    namespace_fd: int | None = None
    info_fd: int | None = None
    block_read: int | None = None
    block_write: int | None = None
    old_handlers: dict[int, object] = {}
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StorageRejected("STORAGE_JOB_ALREADY_RUNNING") from None
        previous = os.pread(lock, 16385, 0)
        if previous:
            try:
                prior_run = _plain_path(Path(json.loads(previous)["run"]))
                if prior_run.parent != control:
                    raise ValueError
                prior = json.loads((prior_run / "exit.json").read_bytes())
                if prior.get("cleanup_verified") is not True:
                    raise StorageRejected("STORAGE_PREVIOUS_JOB_UNREAPED")
            except (OSError, ValueError, TypeError, KeyError):
                raise StorageRejected("STORAGE_PREVIOUS_JOB_UNRECONCILED") from None
        run = control / f"run-{time.time_ns()}-{os.getpid()}"
        run.mkdir(mode=0o700)
        owner = canonical_json_bytes({"run": str(run), "policy_hash": guard.policy_hash})
        os.ftruncate(lock, 0)
        os.write(lock, owner)
        os.fsync(lock)
        initial: dict[str, int] = {}
        try:
            initial = guard.check(expected_new_bytes)
            if stage != "local-validation":
                require_bounded_bwrap()
        except StorageRejected as error:
            atomic_write_bytes(
                run / "exit.json",
                canonical_json_bytes(
                    {
                        "schema_version": "hosted-storage-exit/v1",
                        "stage": stage,
                        "policy_hash": guard.policy_hash,
                        "failure": str(error),
                        "pid": None,
                        "return_code": None,
                        "waitpid_observed": False,
                        "launch_attempted": False,
                        "cleanup_verified": True,
                        "execution": "FAILED",
                        "validation": "NOT_EVALUATED",
                        "qualification_eligibility": "NOT_QUALIFIED",
                    }
                ),
            )
            raise
        # Preallocate an emergency recording extent before the job can fill disk.
        reserve = os.open(run / "record-reserve", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        try:
            os.posix_fallocate(reserve, 0, 1 << 20)
        finally:
            os.close(reserve)
        prelaunch = {
            "schema_version": "hosted-storage-prelaunch/v1",
            "stage": stage,
            "policy_hash": guard.policy_hash,
            "expected_new_bytes": expected_new_bytes,
            "initial_capacity": initial,
            "argv_hash": sha256_bytes(canonical_json_bytes(argv)),
            "startup_bridge_hash": sha256_bytes(STARTUP_BRIDGE.encode())
            if stage != "local-validation"
            else None,
            "startup_python_hash": sha256_file(Path(sys.executable).resolve(strict=True))
            if stage != "local-validation"
            else None,
            "qualification_eligibility": "NOT_QUALIFIED",
        }
        atomic_write_bytes(run / "prelaunch.json", canonical_json_bytes(prelaunch))
        atomic_write_bytes(run / "policy.json", guard.policy.canonical_bytes())
        failure: str | None = None
        code: int | None = None
        waited = False

        def interrupted(signum: int, frame: object) -> None:
            raise StorageRejected("STORAGE_SUPERVISOR_INTERRUPTED")

        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                old_handlers[signum] = signal.signal(signum, interrupted)
        try:
            # Do not export arbitrary child stdout/stderr, credentials or argv.
            environment = {
                "PATH": "/usr/bin:/bin",
                "GIT_OPTIONAL_LOCKS": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                POLICY_ENV: str(run / "policy.json"),
                HASH_ENV: guard.policy_hash,
                LEASE_ENV: str(run),
                "TMPDIR": str(guard.policy.scratch_root),
            }
            launch = argv
            descriptors: tuple[int, ...] = ()
            if stage != "local-validation":
                from quantos.infrastructure.hosted_deployment import private_memory_fd

                info_fd = private_memory_fd("hosted-storage-namespace")
                block_read, block_write = os.pipe2(os.O_CLOEXEC)
                descriptors = (info_fd,)
                # The PID namespace remains responsible for all descendants,
                # including managers creating new sessions/process groups.
                launch = (
                    "/usr/bin/bwrap",
                    "--unshare-pid",
                    "--die-with-parent",
                    "--new-session",
                    "--bind",
                    "/",
                    "/",
                    "--dev-bind",
                    "/dev",
                    "/dev",
                    "--ro-bind",
                    str(guard.policy.host_volume),
                    str(guard.policy.host_volume),
                    "--bind",
                    str(guard.policy.scratch_root),
                    str(guard.policy.scratch_root),
                    "--proc",
                    "/proc",
                    "--info-fd",
                    str(info_fd),
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    STARTUP_BRIDGE,
                    json.dumps(argv),
                )
            launch_attempted = True
            process = subprocess.Popen(
                launch,
                stdin=block_read if block_read is not None else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=environment,
                pass_fds=descriptors,
            )
            if block_read is not None:
                os.close(block_read)
                block_read = None
            if info_fd is not None:
                deadline = time.monotonic() + 5
                while namespace_fd is None:
                    namespace_fd = _namespace_pidfd(process.pid, info_fd)
                    if namespace_fd is not None:
                        break
                    guard.check()
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise StorageRejected("STORAGE_NAMESPACE_EXIT_UNOBSERVED")
                    time.sleep(0.01)
                atomic_write_bytes(run / "namespace.json", os.pread(info_fd, 4096, 0))
                if block_write is None:
                    raise StorageRejected("STORAGE_NAMESPACE_GATE_UNAVAILABLE")
                os.write(block_write, b"G")
                os.close(block_write)
                block_write = None
            while True:
                if info_fd is not None and namespace_fd is None:
                    namespace_fd = _namespace_pidfd(process.pid, info_fd)
                facts = guard.check()
                growth = max(
                    initial["linux_available_bytes"] - facts["linux_available_bytes"],
                    initial["host_available_bytes"] - facts["host_available_bytes"],
                    0,
                )
                if growth > expected_new_bytes:
                    raise StorageRejected("STORAGE_ESTIMATE_EXCEEDED")
                code = process.poll()
                if code is not None:
                    if info_fd is not None and namespace_fd is None:
                        raise StorageRejected("STORAGE_NAMESPACE_EXIT_UNOBSERVED")
                    break
                time.sleep(guard.policy.poll_seconds)
        except BaseException as error:
            failure = (
                str(error) if isinstance(error, StorageRejected) else "STORAGE_SUPERVISOR_ERROR"
            )
        finally:
            if old_handlers:
                # Repeated interrupts cannot abort cleanup or discard the original wait.
                for signum in old_handlers:
                    signal.signal(signum, signal.SIG_IGN)
            namespace_exited: bool | None = None
            if process is not None:
                try:
                    if failure is not None:
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=guard.policy.terminate_grace_seconds)
                        except subprocess.TimeoutExpired:
                            with suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait(timeout=10)
                    waited = True
                except (OSError, subprocess.TimeoutExpired):
                    failure = failure or "STORAGE_WAIT_UNOBSERVED"
                    code = None
            if namespace_fd is not None:
                if not select.select([namespace_fd], [], [], 0)[0]:
                    with suppress(ProcessLookupError):
                        from quantos.infrastructure.hosted_regression_runtime import (
                            native_pidfd_kill,
                        )

                        native_pidfd_kill(namespace_fd)
                namespace_exited = bool(select.select([namespace_fd], [], [], 10)[0])
                if not namespace_exited:
                    failure = failure or "STORAGE_NAMESPACE_EXIT_UNOBSERVED"
            # Recheck after the actual wrapper wait and namespace exit, including
            # the final writes between the last sampling call and process exit.
            try:
                final = guard.check()
                growth = max(
                    initial["linux_available_bytes"] - final["linux_available_bytes"],
                    initial["host_available_bytes"] - final["host_available_bytes"],
                    0,
                )
                if growth > expected_new_bytes:
                    failure = failure or "STORAGE_ESTIMATE_EXCEEDED"
            except (StorageRejected, OSError) as error:
                failure = failure or (
                    str(error) if isinstance(error, StorageRejected) else "STORAGE_IO_FAILURE"
                )
            (run / "record-reserve").unlink()
            record = {
                "schema_version": "hosted-storage-exit/v1",
                "policy_hash": guard.policy_hash,
                "stage": stage,
                "pid": process.pid if process is not None else None,
                "return_code": code,
                "waitpid_observed": waited,
                "process_scope": "PID_NAMESPACE_WRAPPER"
                if info_fd is not None
                else "LOCAL_DIRECT_CHILD",
                "namespace_exit_observed": namespace_exited,
                "launch_attempted": launch_attempted,
                "cleanup_verified": (process is None and not launch_attempted)
                or (waited and (info_fd is None or namespace_exited is True)),
                "failure": failure,
                "execution": "SUCCEEDED" if code == 0 and failure is None else "FAILED",
                "validation": "NOT_EVALUATED",
                "qualification_eligibility": "NOT_QUALIFIED",
            }
            atomic_write_bytes(run / "exit.json", canonical_json_bytes(record))
        if code != 0 or failure is not None:
            raise StorageRejected("STORAGE_JOB_FAILED")
        return run
    finally:
        for descriptor in (namespace_fd, info_fd, block_read, block_write):
            if descriptor is not None:
                os.close(descriptor)
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)  # type: ignore[arg-type]
        os.close(lock)
