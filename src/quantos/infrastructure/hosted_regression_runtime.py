"""Frozen management CI prefix and kernel network isolation, separate from research."""

from __future__ import annotations

import base64
import csv
import ctypes
import io
import os
from collections.abc import Callable
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import HostedFileIdentity, HostedInstallInventory
from quantos.infrastructure.hosted_deployment import NAMESPACE_TMPFS_BYTES, install_inventory
from quantos.infrastructure.hosted_storage_copy import copy_tree_verified
from quantos.infrastructure.hosted_verification import read_relative

CI_PREFIX = "qualification-checks/Q12"
CI_PYTEST_TEMP = Path("/tmp/pt/b")
COVERAGE_PTH = (
    b'import sys; exec(\'import os\\n\\nif os.getenv("COVERAGE_PROCESS_START") or '
    b'os.getenv("COVERAGE_PROCESS_CONFIG"):\\n try:\\n  import coverage\\n except:\\n'
    b'  pass\\n else:\\n  coverage.process_startup(slug="pth")\')\n'
)
BRIDGE_PROGRAM = """import hashlib,json,os,socket,sys
exe=os.readlink('/proc/self/exe')
with open(exe,'rb') as stream: executable_hash=hashlib.file_digest(stream,'sha256').hexdigest()
namespace=os.stat('/proc/self/ns/net').st_ino
probe=socket.socket()
try:
 probe.settimeout(1); probe.connect(('192.0.2.1',9))
except OSError as error: denied_errno=error.errno
else: raise SystemExit(91)
finally: probe.close()
print(json.dumps({'namespace_pid':os.getpid(),'namespace_parent_pid':os.getppid(),
 'pid_namespace_inode':os.stat('/proc/self/ns/pid').st_ino,'net_namespace_inode':namespace,
 'executable_hash':executable_hash,'network_probe_errno':denied_errno},sort_keys=True,separators=(',',':')),flush=True)
if sys.stdin.buffer.read(1)!=b'G': raise SystemExit(92)
argv=json.loads(sys.argv[1]); os.execve(argv[0],argv,dict(os.environ))
"""


def _pidfd_syscall(name: bytes, *arguments: int | ctypes.c_void_p) -> int:
    resolver = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    resolver.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    resolver.seccomp_syscall_resolve_name.restype = ctypes.c_int
    number = resolver.seccomp_syscall_resolve_name(name)
    if number < 0:
        raise OSError("native pidfd syscall is unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    result = library.syscall(ctypes.c_long(number), *arguments)
    if result < 0:
        raise OSError(ctypes.get_errno(), "native CI pidfd operation failed")
    return int(result)


def native_pidfd_open(pid: int) -> int:
    """Use the Linux syscall even when the frozen Python/glibc lacks its wrapper."""
    return _pidfd_syscall(b"pidfd_open", pid, 0)


def native_pidfd_kill(descriptor: int) -> None:
    _pidfd_syscall(b"pidfd_send_signal", descriptor, 9, ctypes.c_void_p(None), 0)


def ci_python(root: Path) -> Path:
    return root / CI_PREFIX / ".venv/bin/python3.11"


def expected_ci_runtime(installation: HostedInstallInventory) -> HostedInstallInventory:
    files = [
        file.model_copy(update={"relative_path": file.relative_path.removeprefix("python/")})
        for file in installation.files
        if file.relative_path.startswith("python/")
    ]
    files.append(
        HostedFileIdentity(
            relative_path="lib/python3.11/site-packages/a1_coverage.pth",
            bytes_hash=sha256_bytes(COVERAGE_PTH),
            size_bytes=len(COVERAGE_PTH),
            mode=0o600,
        )
    )
    return HostedInstallInventory(files=tuple(sorted(files, key=lambda item: item.relative_path)))


def verify_ci_runtime(deployment_root: Path, installation: HostedInstallInventory) -> None:
    target = deployment_root / CI_PREFIX
    expected = expected_ci_runtime(installation)
    if (
        read_relative(target, "runtime-install.json") != expected.canonical_bytes()
        or install_inventory(target / ".venv") != expected
    ):
        raise ArtifactIntegrityError("management CI prefix bytes differ from frozen derivation")


def verify_ci_declaration(
    deployment_root: Path, installation: HostedInstallInventory
) -> dict[str, object]:
    target = deployment_root / CI_PREFIX
    data = read_relative(target, "runtime-declaration.json")
    declaration = strict_json_object(data, max_bytes=65536)
    node = read_relative(target, "node-bin/node", max_bytes=268435456)
    expected = expected_ci_runtime(installation)
    if (
        declaration
        != {
            "schema_version": "hosted-management-ci-runtime/v1",
            "runtime_inventory_hash": expected.content_hash,
            "node_hash": sha256_bytes(node),
            "node_size_bytes": len(node),
            "coverage_hook_hash": sha256_bytes(COVERAGE_PTH),
        }
        or data != canonical_json_bytes(declaration)
        or not node.startswith(b"\x7fELF")
        or install_inventory(target / "node-bin")
        != HostedInstallInventory(
            files=(
                HostedFileIdentity(
                    relative_path="node",
                    bytes_hash=sha256_bytes(node),
                    size_bytes=len(node),
                    mode=0o500,
                ),
            )
        )
    ):
        raise ArtifactIntegrityError("management CI Node or runtime declaration differs")
    return declaration


def prepare_ci_runtime_contents(
    install: Path,
    expected: HostedInstallInventory,
    node_source: Path,
    *,
    before_physical_copy: Callable[[int], None] | None = None,
) -> dict[str, object]:
    """Called only inside a private management child's already-pinned new cwd."""
    records = tuple(
        csv.reader(
            io.StringIO(
                read_relative(
                    install, "python/lib/python3.11/site-packages/coverage-7.16.0.dist-info/RECORD"
                ).decode()
            )
        )
    )
    digest = (
        base64.urlsafe_b64encode(bytes.fromhex(sha256_bytes(COVERAGE_PTH))).rstrip(b"=").decode()
    )
    if ("a1_coverage.pth", "sha256=" + digest, str(len(COVERAGE_PTH))) not in tuple(
        map(tuple, records)
    ):
        raise ArtifactIntegrityError("CI coverage hook differs from locked installed wheel")
    copy_tree_verified(
        install / "python", Path(".venv"), reserve_physical_copy=before_physical_copy
    )
    atomic_write_bytes(Path(".venv/lib/python3.11/site-packages/a1_coverage.pth"), COVERAGE_PTH)
    if install_inventory(Path(".venv")) != expected:
        raise ArtifactIntegrityError("CI prefix differs from frozen installation derivation")
    node = read_relative(node_source.parent, node_source.name, max_bytes=268435456)
    if not node.startswith(b"\x7fELF"):
        raise ArtifactIntegrityError("CI Node requires the explicit native ELF executable")
    atomic_write_bytes(Path("node-bin/node"), node)
    os.chmod("node-bin/node", 0o500)
    atomic_write_bytes(Path("runtime-install.json"), expected.canonical_bytes())
    declaration: dict[str, object] = {
        "schema_version": "hosted-management-ci-runtime/v1",
        "runtime_inventory_hash": expected.content_hash,
        "node_hash": sha256_bytes(node),
        "node_size_bytes": len(node),
        "coverage_hook_hash": sha256_bytes(COVERAGE_PTH),
    }
    atomic_write_bytes(Path("runtime-declaration.json"), canonical_json_bytes(declaration))
    return declaration


def ci_namespace_command(
    python: Path,
    workspace: Path,
    target: Path,
    environment: dict[str, str],
    command: tuple[str, ...],
) -> tuple[str, ...]:
    """Management-only fixed wrapper; research callers cannot select these mounts."""
    argv = [
        "/usr/bin/bwrap",
        "--unshare-user",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--clearenv",
        "--size",
        str(NAMESPACE_TMPFS_BYTES),
        "--tmpfs",
        "/tmp",
        "--dir",
        str(CI_PYTEST_TEMP.parent),
        "--ro-bind",
        str(python.parent.parent),
        str(python.parent.parent),
        "--bind",
        str(workspace),
        str(workspace),
        "--bind",
        str(target),
        str(target),
        "--ro-bind",
        str(target / ".venv"),
        str(target / ".venv"),
        "--ro-bind",
        str(target / "node-bin"),
        str(target / "node-bin"),
        "--chdir",
        str(workspace),
    ]
    for name, value in sorted(environment.items()):
        argv.extend(("--setenv", name, value))
    argv.extend(
        (
            str(python),
            "-I",
            "-B",
            "-X",
            f"pycache_prefix={target / 'bridge-cache'}",
            "-c",
            BRIDGE_PROGRAM,
            canonical_json_bytes(command).decode(),
        )
    )
    return tuple(argv)


def ci_environment(python: Path, workspace: Path, target: Path) -> dict[str, str]:
    return {
        "PATH": str(target / "node-bin") + ":" + str(python.parent) + ":/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONPATH": str(workspace / "src"),
        "COVERAGE_FILE": str(target / "coverage-data"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(target / "check-cache"),
        "PYRIGHT_PYTHON_IGNORE_WARNINGS": "1",
        "PYRIGHT_PYTHON_NODEJS_WHEEL": "0",
        "PYRIGHT_PYTHON_GLOBAL_NODE": "1",
        "PYRIGHT_PYTHON_USE_BUNDLED_PYRIGHT": "1",
    }
