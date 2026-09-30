"""Actual restricted-host security probes; output records observed syscalls, never PASS."""

from __future__ import annotations

import ctypes
import importlib.util
import os
from pathlib import Path

from quantos.artifacts.store import opened_directory, read_regular_bytes_at
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import HostedClientConfiguration
from quantos.infrastructure.hosted_client import HostedChannelError, HostedUnixClient
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
        ("WRITE_EVENT", "/authority/business/probe/campaign-events/probe"),
        ("WRITE_LEDGER", "/authority/business/probe/ledger/probe"),
        ("WRITE_INSTALL", "/install/python/lib/python3.11/site-packages/quantos/__init__.py"),
        ("WRITE_LAUNCHER", "/install/python-seeded"),
        ("WRITE_CONFIG", "/config/probe"),
        ("WRITE_PROVENANCE", "/provenance/src/quantos/cli.py"),
        ("WRITE_PROJECTION", "/projection/probe"),
        ("WRITE_CHANNEL", "/channel/probe"),
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
    ):
        file_attempt(name, path, os.O_RDONLY)
    library = ctypes.CDLL(None, use_errno=True)
    for name, syscall, arguments in (
        ("PTRACE_PARENT", 101, (16, int(str(context["manager_pid"])), 0, 0)),
        ("PROCESS_VM_PARENT", 310, (int(str(context["manager_pid"])), 0, 0, 0, 0, 0)),
        ("UNSHARE_ESCAPE", 272, (0x10000000,)),
        ("PIDFD_GETFD_ESCAPE", 438, (-1, 0, 0)),
        ("SETNS_ESCAPE", 308, (-1, 0)),
    ):
        ctypes.set_errno(0)
        value = library.syscall(syscall, *arguments)
        results.append({"name": name, "return": value, "errno": ctypes.get_errno()})
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
    # The inherited manager PYTHONPATH and current directory must never be import sources.
    results.append(
        {
            "name": "IMPORT_CANARY",
            "found": importlib.util.find_spec("hosted_import_canary") is not None,
        }
    )
    results.append({"name": "PROC_CONTENT", "entries": sorted(os.listdir("/proc"))})
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
                "results": results,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
