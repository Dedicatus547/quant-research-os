"""Canary-only deployment preflight; no protocol/API and no credential reads.

This administrator diagnostic does not grant Q07 qualification. Run it outside
the development sandbox; its only targets are disposable non-secret canaries.
"""

import hashlib
import json
import os
import platform
import socket
import subprocess
import tempfile
from pathlib import Path

CHILD = r"""
import json, os, socket, sys
checks = {}
def denied(name, path, flags):
    try:
        fd = os.open(path, flags)
    except OSError as e:
        checks[name] = {"denied": True, "errno": e.errno}
    else:
        os.close(fd)
        checks[name] = {"denied": False}
outside = os.environ["PROBE_OUTSIDE"]
denied("authority_write", outside + "/authority/canary", os.O_WRONLY)
denied("authority_read", outside + "/authority/canary", os.O_RDONLY)
denied("sealed_read", outside + "/sealed/canary", os.O_RDONLY)
denied("acquisition_canary_read", outside + "/acquisition/canary", os.O_RDONLY)
denied("launcher_evidence_write", outside + "/evidence/canary", os.O_WRONLY)
denied("frozen_install_write", "/install/canary.py", os.O_WRONLY)
denied("projection_write", "/projection/canary", os.O_WRONLY)
denied("outside_parent_proc", "/proc/" + os.environ["PROBE_PARENT_PID"] + "/root", os.O_RDONLY)
denied("proc_init_root_escape", "/proc/1/root" + outside + "/authority/canary", os.O_RDONLY)
parent_fd_path = "/proc/" + os.environ["PROBE_PARENT_PID"] + "/fd/"
denied("parent_fd_escape", parent_fd_path + os.environ["PROBE_PARENT_FD"], os.O_RDONLY)
fdtargets = {}
for name in os.listdir("/proc/self/fd"):
    if int(name) < 3:
        continue
    try:
        fdtargets[name] = os.readlink("/proc/self/fd/" + name)
    except FileNotFoundError:
        pass
checks["inherited_authority_fd_absent"] = {
    "denied": not any(outside in x for x in fdtargets.values())}
checks["python_environment_isolated"] = {
    "denied": "/projection" not in sys.path and outside not in sys.path,
    "isolated": bool(sys.flags.isolated)}
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("127.0.0.1", int(os.environ["PROBE_TCP_PORT"])))
except OSError as e:
    checks["parent_tcp_unreachable"] = {"denied": True, "errno": e.errno}
else:
    checks["parent_tcp_unreachable"] = {"denied": False}
finally:
    s.close()
print(json.dumps({
    "role": os.environ["PROBE_ROLE"], "uid": os.getuid(), "gid": os.getgid(),
    "pid": os.getpid(),
    "namespaces": {x:os.readlink("/proc/self/ns/"+x) for x in ("user","mnt","pid","net")},
    "checks": checks}, sort_keys=True))
"""

with tempfile.TemporaryDirectory(prefix="hm06-canary-") as tmp:
    root = Path(tmp)
    for name in ("authority", "sealed", "acquisition", "evidence", "install", "projection"):
        (root / name).mkdir()
        (root / name / ("canary.py" if name == "install" else "canary")).write_text(
            "NON_SECRET_HM06_CANARY\n"
        )
    parent_fd = os.open(root / "authority/canary", os.O_RDONLY)
    tcp = socket.socket()
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(1)
    port = tcp.getsockname()[1]
    rows = []
    for role, offline in (
        ("offline-service-canary", True),
        ("restricted-research-host-canary", False),
    ):
        argv = ["/usr/bin/bwrap", "--unshare-all"]
        if not offline:
            argv.append("--share-net")
        argv += [
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind",
            str(root / "install"),
            "/install",
            "--ro-bind",
            str(root / "projection"),
            "/projection",
            "--chdir",
            "/tmp",
        ]
        for key, value in {
            "PROBE_ROLE": role,
            "PROBE_OUTSIDE": str(root),
            "PROBE_PARENT_PID": str(os.getpid()),
            "PROBE_PARENT_FD": str(parent_fd),
            "PROBE_TCP_PORT": str(port),
            "PYTHONPATH": str(root),
            "HOME": "/tmp",
        }.items():
            argv += ["--setenv", key, value]
        argv += ["/usr/bin/python3", "-I", "-c", CHILD]
        result = subprocess.run(
            argv, capture_output=True, close_fds=True, timeout=15, env={"PATH": "/usr/bin:/bin"}
        )
        rows.append(
            {
                "role": role,
                "exit_code": result.returncode,
                "stderr": result.stderr.decode("utf-8"),
                "observation": json.loads(result.stdout) if result.returncode == 0 else None,
            }
        )
    os.close(parent_fd)
    tcp.close()
    payload = {
        "schema_version": "hm06-environment-preflight/v1",
        "scope": "CANARY_PREFLIGHT_ONLY_NOT_Q07_QUALIFICATION",
        "profile": "hm-isolated-service/v1",
        "model": "gpt-6-sol",
        "reasoning_effort": "high",
        "attempt_count": 1,
        "usage": "unavailable",
        "environment": {
            "kernel": platform.release(),
            "libc": platform.libc_ver(),
            "uid": os.getuid(),
            "gid": os.getgid(),
            "bwrap_version": subprocess.check_output(
                ["/usr/bin/bwrap", "--version"], text=True
            ).strip(),
            "bwrap_sha256": hashlib.sha256(Path("/usr/bin/bwrap").read_bytes()).hexdigest(),
            "controller_namespaces": {
                x: os.readlink("/proc/self/ns/" + x) for x in ("user", "mnt", "pid", "net")
            },
        },
        "probes": rows,
        "qualification_cases": {"Q07": "NOT_EVALUATED", "Q11": "NOT_EVALUATED"},
        "qualification_granted": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
