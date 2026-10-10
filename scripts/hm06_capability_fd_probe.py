#!/usr/bin/env python3
"""Non-secret bwrap FD-transfer canary; never reads or prints real credentials."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from quantos.infrastructure.hosted_deployment import (
    HostedNamespacePaths,
    namespace_command,
    private_memory_fd,
    source_seccomp_filter,
)

SERVICE_CODE = """
import json,os,stat
path='/tmp/hosted-service-capability-0'
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
data=os.read(fd,33)
os.close(fd)
os.unlink(path)
memory=os.memfd_create('canary',os.MFD_CLOEXEC)
os.write(memory,data)
os.lseek(memory,0,0)
os.dup2(memory,100)
os.close(memory)
same=os.read(100,33)==b'NON_SECRET_CAPABILITY_CANARY_001'
print(json.dumps({'fd100_matches':same,'staged_path_absent':not os.path.exists(path),
                  'service_proc_private':os.path.exists('/proc/1')},sort_keys=True))
""".strip()

HOST_CODE = """
import json,os
path='/tmp/codex/auth.json'
with open(path,'rb') as stream: same=stream.read()==b'NON_SECRET_MODEL_AUTH_CANARY_0001'
try:
    with open(path,'wb') as stream: stream.write(b'changed')
    denied=False
except OSError as error:
    denied=error.errno in (1,13,30)
print(json.dumps({'auth_canary_matches':same,'auth_write_denied':denied,
                  'host_proc_empty':not os.listdir('/proc')},sort_keys=True))
""".strip()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hm06-fd-probe-") as temporary:
        root = Path(temporary)
        for name in (
            "install",
            "projection",
            "channel",
            "authority",
            "config",
            "provenance",
            "inputs",
        ):
            (root / name).mkdir()
        paths = HostedNamespacePaths(
            *(
                root / name
                for name in (
                    "install",
                    "projection",
                    "channel",
                    "authority",
                    "config",
                    "provenance",
                    "inputs",
                )
            )
        )
        cap_fd = private_memory_fd("non-secret-capability-probe")
        auth_fd = private_memory_fd("non-secret-auth-probe")
        seccomp_fd, _ = source_seccomp_filter()
        try:
            os.write(cap_fd, b"NON_SECRET_CAPABILITY_CANARY_001")
            os.write(auth_fd, b"NON_SECRET_MODEL_AUTH_CANARY_0001")
            os.lseek(cap_fd, 0, os.SEEK_SET)
            os.lseek(auth_fd, 0, os.SEEK_SET)
            service = subprocess.run(
                namespace_command(
                    "service",
                    paths,
                    ("/usr/bin/python3", "-I", "-c", SERVICE_CODE),
                    service_capability_fds=(cap_fd,),
                ),
                pass_fds=(cap_fd,),
                capture_output=True,
                timeout=15,
                env={"PATH": "/usr/bin:/bin"},
            )
            host_command = namespace_command(
                "host",
                paths,
                ("/usr/bin/python3", "-I", "-c", HOST_CODE),
                seccomp_fd=seccomp_fd,
            )
            insertion = host_command.index("/usr/bin/python3")
            host_command = (
                *host_command[:insertion],
                "--ro-bind-data",
                str(auth_fd),
                "/tmp/codex/auth.json",
                *host_command[insertion:],
            )
            host = subprocess.run(
                host_command,
                pass_fds=(seccomp_fd, auth_fd),
                capture_output=True,
                timeout=15,
                env={"PATH": "/usr/bin:/bin"},
            )
            record = {
                "schema_version": "hm06-fd-transfer-probe/v1",
                "service_exit": service.returncode,
                "host_exit": host.returncode,
                "service": json.loads(service.stdout) if service.returncode == 0 else None,
                "host": json.loads(host.stdout) if host.returncode == 0 else None,
                "service_stderr_class": "EMPTY" if not service.stderr else "NONEMPTY",
                "host_stderr_class": "EMPTY" if not host.stderr else "NONEMPTY",
                "qualification": "PREFLIGHT_ONLY_NOT_Q07",
            }
            print(json.dumps(record, sort_keys=True, separators=(",", ":")))
        finally:
            os.close(cap_fd)
            os.close(auth_fd)
            os.close(seccomp_fd)


if __name__ == "__main__":
    main()
