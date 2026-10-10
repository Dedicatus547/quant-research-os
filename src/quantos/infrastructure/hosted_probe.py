"""Actual restricted-host security probes; output records observed syscalls, never PASS."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import socket
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path

from quantos.artifacts.store import opened_directory, read_regular_bytes_at, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import HostedClientConfiguration
from quantos.infrastructure.hosted_client import CHANNEL_MAGIC, HostedChannelError, HostedUnixClient
from quantos.infrastructure.hosted_deployment import private_memory_fd


def main() -> None:
    with opened_directory(Path("/tmp")) as parent:
        context = strict_json_object(
            read_regular_bytes_at(parent, "hosted-probe.json", max_bytes=4096), max_bytes=4096
        )
        capability = read_regular_bytes_at(parent, "hosted-client-capability", max_bytes=32)
        os.unlink("hosted-client-capability", dir_fd=parent)
    with opened_directory(Path("/install")) as parent:
        config = HostedClientConfiguration.model_validate_json(
            read_regular_bytes_at(parent, "hosted-client.json", max_bytes=4096)
        )
    results: list[dict[str, object]] = []

    def file_attempt(name: str, path: str, flags: int) -> None:
        try:
            descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except OSError as error:
            results.append({"name": name, "errno": error.errno, "opened": False})
        else:
            os.close(descriptor)
            results.append({"name": name, "errno": None, "opened": True})

    for name, path in (
        ("WRITE_AUTHORITY", "/authority/probe"),
        ("WRITE_EVENT", str(context["event_path"])),
        ("WRITE_LEDGER", str(context["ledger_path"])),
        ("WRITE_INSTALL", "/install/python/lib/python3.11/site-packages/quantos/__init__.py"),
        ("WRITE_LAUNCHER", "/install/python-seeded"),
        ("WRITE_CLI", "/install/codex"),
        ("WRITE_PYTHON", "/install/python/bin/python3"),
        ("WRITE_CONFIG", "/config/probe"),
        ("WRITE_PROVENANCE", "/provenance/src/quantos/cli.py"),
        ("WRITE_PROJECTION", "/projection/probe"),
        ("WRITE_CHANNEL", "/channel/probe"),
        ("WRITE_TRUSTED_SOURCE", str(context["source_root"]) + "/evidence/probe"),
    ):
        # Never truncate a file even if an isolation regression grants write access.
        file_attempt(name, path, os.O_WRONLY | os.O_CREAT)
    for name, path in (
        ("READ_SEALED", "/authority/sealed-canary"),
        ("READ_VENDOR_CREDENTIAL", "/config/vendor-credential-canary"),
        ("READ_MANAGER_HOME", "/home/zjw/.codex/auth.json"),
        ("READ_SERVICE_CAPABILITY", "/tmp/hosted-service-capability-0"),
        ("READ_PARENT_FD", f"/proc/{context['manager_pid']}/fd/0"),
        ("READ_PARENT_ROOT", f"/proc/{context['manager_pid']}/root/authority/sealed-canary"),
        ("READ_TRUSTED_SOURCE", str(context["source_root"]) + "/evidence/source-canary"),
        ("READ_PROJECTION_PARENT_SEALED", "/projection/../authority/sealed-canary"),
        ("READ_ABSOLUTE_INPUTS", "/inputs"),
    ):
        file_attempt(name, path, os.O_RDONLY)
    library = ctypes.CDLL(None, use_errno=True)
    buffer = ctypes.create_string_buffer(1)

    class Iovec(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("length", ctypes.c_size_t)]

    local = Iovec(ctypes.addressof(buffer), 1)
    remote = Iovec(int(str(context["memory_canary_address"])), 1)
    canary_fd = private_memory_fd("hosted-pidfd-canary")
    os.write(canary_fd, b"nonsecret-pidfd-canary")
    pidfd = library.syscall(434, os.getpid(), 0)
    if pidfd < 0:
        os.close(canary_fd)
        raise OSError(ctypes.get_errno(), "actual pidfd canary unavailable")
    for name, syscall, arguments in (
        ("PTRACE_PARENT", 101, (16, int(str(context["manager_pid"])), 0, 0)),
        (
            "PROCESS_VM_PARENT",
            310,
            (int(str(context["manager_pid"])), ctypes.byref(local), 1, ctypes.byref(remote), 1, 0),
        ),
        ("UNSHARE_ESCAPE", 272, (0x10000000,)),
        ("PIDFD_GETFD_ESCAPE", 438, (pidfd, canary_fd, 0)),
        ("SETNS_ESCAPE", 308, (-1, 0)),
    ):
        ctypes.set_errno(0)
        value = library.syscall(syscall, *arguments)
        results.append({"name": name, "return": value, "errno": ctypes.get_errno()})
    os.close(pidfd)
    os.close(canary_fd)
    client = HostedUnixClient(Path(config.socket_path), capability, config.policy)
    for name, selected, campaign in (
        (
            "WRONG_CAPABILITY",
            HostedUnixClient(Path(config.socket_path), b"X" * 32, config.policy),
            str(context["campaign_hash"]),
        ),
        ("WRONG_CAMPAIGN", client, "f" * 64),
    ):
        try:
            selected.status(campaign)
        except HostedChannelError:
            results.append({"name": name, "channel_returned": False})
        else:
            results.append({"name": name, "channel_returned": True})
    reply = client.status(str(context["campaign_hash"]))
    results.append({"name": "AUTHORIZED_QUERY", "channel_returned": reply is not None})
    for name, mutation in (
        ("CHANNEL_SYMLINK", lambda: os.symlink("/tmp/fake.sock", "/channel/probe.sock")),
        (
            "CHANNEL_HARDLINK",
            lambda: os.link(
                "/install/python/lib/python3.11/site-packages/quantos/__init__.py",
                "/channel/probe-hardlink",
            ),
        ),
        ("CHANNEL_FIFO", lambda: os.mkfifo("/channel/probe-fifo", 0o600)),
        ("CHANNEL_UNLINK", lambda: os.unlink(config.socket_path)),
        ("CHANNEL_REPLACE", lambda: os.replace("/tmp/channel-replacement", config.socket_path)),
    ):
        Path("/tmp/channel-replacement").write_bytes(b"nonsecret channel race canary")
        try:
            mutation()
        except OSError as error:
            results.append({"name": name, "changed": False, "errno": error.errno})
        else:
            results.append({"name": name, "changed": True, "errno": None})
    start_read, start_write = os.pipe()
    result_read, result_write = os.pipe()
    racer = os.fork()
    if racer == 0:
        os.close(start_write)
        os.close(result_read)
        os.read(start_read, 1)
        attempts: list[int | None] = []
        for _ in range(128):
            try:
                os.replace("/tmp/channel-replacement", config.socket_path)
            except OSError as error:
                attempts.append(error.errno)
            else:
                attempts.append(None)
            time.sleep(0.002)
        os.write(result_write, canonical_json_bytes({"attempts": attempts}))
        os._exit(0)
    os.close(start_read)
    os.close(result_write)
    try:
        os.write(start_write, b"x")
        for index in range(8):
            results.append(
                {
                    "name": f"CHANNEL_RACE_QUERY_{index}",
                    "channel_returned": client.status(str(context["campaign_hash"])) is not None,
                }
            )
        concurrent = strict_json_object(os.read(result_read, 4096), max_bytes=4096)
        results.append({"name": "CHANNEL_CONCURRENT_RACE", **concurrent})
    finally:
        os.close(start_write)
        os.close(result_read)
        os.waitpid(racer, 0)
    header = canonical_json_bytes(
        {
            "schema_version": "hosted-channel-request/v1",
            "operation": "execute",
            "campaign_hash": context["campaign_hash"],
            "target_hash": context["campaign_hash"],
            "command": "/bin/sh",
        }
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(config.socket_path)
        try:
            connection.sendall(
                CHANNEL_MAGIC
                + capability
                + struct.pack("!I", len(header))
                + header
                + struct.pack("!I", 0)
            )
            value = connection.recv(4096)
        except (ConnectionResetError, BrokenPipeError):
            value = b""
        results.append({"name": "MANAGEMENT_API_ESCAPE", "closed_without_reply": not value})
    # Positive control uses real files at all three untrusted import locations.
    locations = (
        Path("/tmp"),
        Path("/tmp/import-canary"),
        Path("/tmp/home/.local/lib/python3.11/site-packages"),
    )
    for location in locations:
        location.mkdir(parents=True, exist_ok=True)
        (location / "hosted_import_canary.py").write_bytes(b"CANARY = True\n")
    code = (
        "import importlib.util,json;print(json.dumps({'found':"
        "importlib.util.find_spec('hosted_import_canary') is not None},"
        "sort_keys=True,separators=(',',':')))"
    )
    environment = dict(
        os.environ, PYTHONPATH="/tmp/import-canary", PYTHONUSERBASE="/tmp/home/.local"
    )
    found: list[bool] = []
    for binary in ("/install/python/bin/python3", "/install/python-seeded"):
        child = subprocess.run(
            (binary, "-c", code),
            cwd="/tmp",
            env=environment,
            capture_output=True,
            timeout=10,
            check=True,
        )
        if not child.stdout.endswith(b"\n"):
            raise ValueError("import probe framing differs")
        found.append(strict_json_object(child.stdout[:-1], max_bytes=4096)["found"] is True)
    results.append(
        {
            "name": "IMPORT_CANARY",
            "found": importlib.util.find_spec("hosted_import_canary") is not None,
            "files_present": all(
                (location / "hosted_import_canary.py").is_file() for location in locations
            ),
            "unisolated_control_found": found[0],
            "isolated_child_found": found[1],
        }
    )
    results.append({"name": "PROC_CONTENT", "entries": sorted(os.listdir("/proc"))})
    if os.path.lexists("/proc/self"):
        results.append(
            {
                "name": "PROC_EXECUTABLE_HINT",
                "self_is_directory": stat.S_ISDIR(os.lstat("/proc/self").st_mode),
                "self_entries": sorted(os.listdir("/proc/self")),
                "exe_is_symlink": stat.S_ISLNK(os.lstat("/proc/self/exe").st_mode),
                "exe_target": os.readlink("/proc/self/exe"),
                "exe_bytes_hash": sha256_file(Path("/proc/self/exe").resolve(strict=True)),
            }
        )
    results.append({"name": "SECCOMP_MODE", "mode": library.prctl(21, 0, 0, 0, 0)})
    for name in ("/install", "/projection", "/channel", "/proc"):
        results.append(
            {
                "name": "READ_ONLY_MOUNT:" + name,
                "read_only": bool(os.statvfs(name).f_flag & os.ST_RDONLY),
            }
        )
    descriptor = private_memory_fd("hosted-probe-private-fd")
    try:
        file_attempt("READ_OWN_PROC_FD", f"/proc/self/fd/{descriptor}", os.O_RDONLY)
    finally:
        os.close(descriptor)
    print(
        canonical_json_bytes(
            {
                "schema_version": "hosted-deployment-probe-observation/v1",
                "uid": os.getuid(),
                "gid": os.getgid(),
                "python_flags": {
                    name: getattr(sys.flags, name)
                    for name in (
                        "isolated",
                        "ignore_environment",
                        "no_user_site",
                        "safe_path",
                        "hash_randomization",
                    )
                },
                "python_path": sys.path,
                "module_path": __file__,
                "python_executable": sys.executable,
                "results": results,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
