"""Probe collection with real Unix IPC, files, memfds, fork/race and child imports.

Permissions, namespace views and dangerous syscalls are explicit doubles. These
observations cannot establish kernel isolation or grant any qualification.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_socket
from test_hosted_deployment import _serve, _stop

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_deployment import HostedClientConfiguration
from quantos.infrastructure import hosted_probe as probe
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.mark.parametrize("allow_event_write", (False, True))
def test_probe_reports_denials_and_positive_controls_without_inventing_pass(
    tmp_path, monkeypatch, capsys, allow_event_write
):
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    fixture, application, service, thread, _client = _serve(tmp_path / "service")
    private = tmp_path / "probe-tmp"
    private.mkdir()
    installation = tmp_path / "probe-install"
    installation.mkdir()
    event = tmp_path / "event.json"
    ledger = tmp_path / "ledger.json"
    event.write_bytes(b"original immutable event canary")
    ledger.write_bytes(b"original immutable ledger canary")
    (private / "hosted-client-capability").write_bytes(b"C" * 32)
    (private / "hosted-probe.json").write_bytes(
        canonical_json_bytes(
            {
                "event_path": str(event),
                "ledger_path": str(ledger),
                "source_root": "/unmounted-source",
                "manager_pid": 2147483647,
                "memory_canary_address": "1",
                "campaign_hash": fixture.spec.campaign_hash,
            }
        )
    )
    (installation / "hosted-client.json").write_bytes(
        HostedClientConfiguration(
            socket_path=str(service.socket_path), policy=service.policy
        ).canonical_bytes()
    )
    before = raw_inventory(fixture.root)
    original_open, original_unlink = os.open, os.unlink
    original_replace, original_listdir = os.replace, os.listdir
    original_statvfs, original_run = os.statvfs, subprocess.run
    originals = {name: getattr(os, name) for name in ("symlink", "link", "mkfifo")}
    syscalls, child_commands = [], []

    def mapped(path):
        path = str(path)
        if path == "/install":
            return installation
        if (
            path == "/tmp"
            or path.startswith(("/tmp/import-canary", "/tmp/home/"))
            or path == "/tmp/channel-replacement"
        ):
            return private / path.removeprefix("/tmp").lstrip("/")
        return Path(path)

    def opened(path, flags, *args, **kwargs):
        text = str(path)
        if text == str(event) and allow_event_write:
            assert not flags & os.O_TRUNC
            return original_open(path, flags, *args, **kwargs)
        if text in (str(event), str(ledger)) or text.startswith(
            (
                "/authority/",
                "/install/",
                "/config/",
                "/provenance/",
                "/projection/",
                "/channel/",
                "/unmounted-source/",
                "/home/zjw/.codex/",
                "/proc/",
                "/inputs",
            )
        ):
            raise OSError(
                errno.EROFS if flags & os.O_WRONLY else errno.EACCES, "synthetic permission denial"
            )
        if text == "/tmp/hosted-service-capability-0":
            raise OSError(errno.ENOENT, "synthetic absent service capability")
        return original_open(path, flags, *args, **kwargs)

    def replace(source, target, *args, **kwargs):
        if str(source) == "/tmp/channel-replacement" and str(target) == str(service.socket_path):
            raise OSError(errno.EROFS, "synthetic channel mutation denial")
        return original_replace(source, target, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if str(path) == str(service.socket_path):
            raise OSError(errno.EROFS, "synthetic channel unlink denial")
        return original_unlink(path, *args, **kwargs)

    def mutation(name):
        def changed(*args, **kwargs):
            if any(str(value).startswith("/channel/") for value in args):
                raise OSError(errno.EROFS, "synthetic channel mutation denial")
            return originals[name](*args, **kwargs)

        return changed

    class Library:
        def syscall(self, number, *args):
            syscalls.append(number)
            if number == 434:
                return original_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
            ctypes.set_errno(errno.EPERM)
            return -1

        def prctl(self, *args):
            return 2

    def child(argv, **kwargs):
        child_commands.append(argv[0])
        assert kwargs["timeout"] == 10 and kwargs["check"] is True
        isolated = argv[0] == "/install/python-seeded"
        assert argv[0] in ("/install/python/bin/python3", "/install/python-seeded")
        return original_run(
            (sys.executable, *(("-I",) if isolated else ()), *argv[1:]),
            cwd=private,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(private / "import-canary"),
                "PYTHONUSERBASE": str(private / "home/.local"),
            },
            capture_output=True,
            timeout=10,
            check=True,
        )

    try:
        with monkeypatch.context() as patch:
            patch.setattr(probe, "Path", mapped)
            patch.setattr(probe.os, "open", opened)
            patch.setattr(probe.os, "replace", replace)
            patch.setattr(probe.os, "unlink", unlink)
            for name in originals:
                patch.setattr(probe.os, name, mutation(name))
            patch.setattr(
                probe,
                "ctypes",
                SimpleNamespace(
                    **{
                        name: getattr(ctypes, name)
                        for name in (
                            "create_string_buffer",
                            "Structure",
                            "c_void_p",
                            "c_size_t",
                            "addressof",
                            "byref",
                            "set_errno",
                            "get_errno",
                        )
                    },
                    CDLL=lambda *a, **k: Library(),
                ),
            )
            patch.setattr(probe.subprocess, "run", child)
            patch.setattr(
                probe.os,
                "listdir",
                lambda path: (
                    ["self", "thread-self"] if str(path) == "/proc" else original_listdir(path)
                ),
            )
            patch.setattr(
                probe.os,
                "statvfs",
                lambda path: (
                    SimpleNamespace(f_flag=os.ST_RDONLY)
                    if str(path) in ("/install", "/projection", "/channel", "/proc")
                    else original_statvfs(path)
                ),
            )
            probe.main()
        observed = json.loads(capsys.readouterr().out)
        records = {record["name"]: record for record in observed["results"]}
        assert observed["schema_version"] == "hosted-deployment-probe-observation/v1"
        assert "PASS" not in observed.values()
        assert records["WRITE_EVENT"]["opened"] is allow_event_write
        assert records["WRITE_LEDGER"]["opened"] is False
        assert records["READ_MANAGER_HOME"]["opened"] is False
        assert records["WRONG_CAPABILITY"]["channel_returned"] is False
        assert records["WRONG_CAMPAIGN"]["channel_returned"] is False
        assert records["AUTHORIZED_QUERY"]["channel_returned"] is True
        assert records["MANAGEMENT_API_ESCAPE"]["closed_without_reply"] is True
        assert all(records[f"CHANNEL_RACE_QUERY_{n}"]["channel_returned"] for n in range(8))
        assert records["CHANNEL_CONCURRENT_RACE"]["attempts"] == [errno.EROFS] * 128
        imports = records["IMPORT_CANARY"]
        assert imports["files_present"] and imports["unisolated_control_found"]
        assert not imports["found"] and not imports["isolated_child_found"]
        assert child_commands == ["/install/python/bin/python3", "/install/python-seeded"]
        assert syscalls == [434, 101, 310, 272, 438, 308]
        assert application.calls == ["status"] * 9
        assert raw_inventory(fixture.root) == before
        assert not (private / "hosted-client-capability").exists()
        assert event.read_bytes() == b"original immutable event canary"
        assert ledger.read_bytes() == b"original immutable ledger canary"
    finally:
        _stop(service, thread)
        pytest_socket.enable_socket()
        pytest_socket.disable_socket()
