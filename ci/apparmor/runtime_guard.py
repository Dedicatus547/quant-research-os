"""Observe the actual non-root bwrap execution context and namespace boundaries."""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import socket
import struct
import subprocess
from pathlib import Path

BWRAP = Path("/usr/bin/bwrap")
BWRAP_SHA256 = "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71"
PROFILE = "quantos_ci_bwrap"
NS = ("user", "net", "pid")
ZERO_CAPS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


def status(pid: str = "self") -> dict[str, str]:
    return {
        key: value.strip()
        for line in Path(f"/proc/{pid}/status").read_text().splitlines()
        if (parts := line.split(":", 1)) and len(parts) == 2
        for key, value in [parts]
        if key in (*ZERO_CAPS, "NoNewPrivs", "Seccomp", "Uid", "Gid")
    }


def namespaces(pid: str = "self") -> list[str]:
    return [os.readlink(f"/proc/{pid}/ns/{name}") for name in NS]


def require_label(raw: str, expected: str) -> None:
    wanted = "unconfined" if expected == "unconfined" else f"{PROFILE} (unconfined)"
    if expected not in ("unconfined", PROFILE) or raw.strip() != wanted:
        raise RuntimeError(f"unexpected kernel execution label: {raw!r}; expected {wanted!r}")


def observe_label(expected: str) -> dict[str, object]:
    """Block the real exec in --args parsing, before namespace creation (bwrap 0.9)."""
    if os.getuid() == 0:
        raise RuntimeError("bwrap observation must run as the ordinary non-root job user")
    if hashlib.sha256(BWRAP.read_bytes()).hexdigest() != BWRAP_SHA256:
        raise RuntimeError("unreviewed bwrap bytes")
    read_fd, write_fd = os.pipe()
    try:
        with subprocess.Popen(
            [str(BWRAP), "--args", str(read_fd)],
            pass_fds=(read_fd,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        ) as proc:
            try:
                # Popen's exec-error pipe handshake has completed: this is bwrap, not
                # the pre-exec Python child. The empty argument pipe keeps it alive.
                pid = str(proc.pid)
                raw = Path(f"/proc/{pid}/attr/current").read_text()
                child_status = status(pid)
                child_ns = namespaces(pid)
                if proc.poll() is not None or child_ns != namespaces():
                    raise RuntimeError("bwrap did not remain in pre-namespace argument parsing")
                if child_status["Uid"].split() != [str(os.getuid())] * 4:
                    raise RuntimeError("bwrap changed its non-root execution identity")
                require_label(raw, expected)
                return {
                    "pid": proc.pid,
                    "label": raw,
                    "status": child_status,
                    "namespaces": child_ns,
                    "bwrap_sha256": BWRAP_SHA256,
                }
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def require_isolated(current: list[str], parent: list[str], caps: dict[str, str]) -> None:
    if len(parent) != len(NS) or any(a == b for a, b in zip(current, parent, strict=True)):
        raise RuntimeError("user/net/PID namespaces are not independently isolated")
    if any(int(caps[key], 16) != 0 for key in ZERO_CAPS) or caps["NoNewPrivs"] != "1":
        raise RuntimeError("exec capabilities or NoNewPrivs violated the existing boundary")


def namespace_command(mode: str, parent: list[str]) -> list[str]:
    return [
        str(BWRAP),
        "--unshare-user",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--size",
        "1048576",
        "--tmpfs",
        "/run",
        "/usr/bin/python3",
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        mode,
        "--parent-ns",
        *parent,
    ]


def run_child(mode: str, parent: list[str]) -> str:
    proc = subprocess.run(
        namespace_command(mode, parent), capture_output=True, text=True, timeout=30
    )
    if proc.returncode:
        raise RuntimeError(f"{mode} failed ({proc.returncode}): {proc.stderr}")
    return proc.stdout


def child(parent: list[str], nested: bool) -> dict[str, object]:
    current, caps = namespaces(), status()
    require_isolated(current, parent, caps)
    label = Path("/proc/self/attr/current").read_text()
    require_label(label, PROFILE)
    fs = os.statvfs("/run")
    size = fs.f_blocks * fs.f_frsize
    if not 0 < size <= 1048576 or not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise RuntimeError("private tmpfs size or read-only root boundary violated")
    if [name for _, name in socket.if_nameindex()] != ["lo"]:
        raise RuntimeError("network namespace exposes an unexpected interface")
    result: dict[str, object] = {
        "namespaces": current,
        "status": caps,
        "label": label,
        "private_tmpfs_bytes": size,
    }
    if nested:
        result["nested"] = run_child("child", current)
    return result


def unrelated(parent: list[str]) -> dict[str, object]:
    current = namespaces()
    if any(current[i] == parent[i] for i in (0, 1)):
        raise RuntimeError("negative control must use its own user and network namespaces")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        request = struct.pack(
            "16sH2s4s8s", b"lo", socket.AF_INET, b"\0\0", socket.inet_aton("127.0.0.1"), b"\0" * 8
        )
        try:
            fcntl.ioctl(sock, 0x8916, request)  # SIOCSIFADDR, in the private network namespace.
        except OSError as error:
            if error.errno != errno.EPERM:
                raise
            return {
                "unrelated_net_admin": "DENIED",
                "errno": error.errno,
                "label": Path("/proc/self/attr/current").read_text(),
            }
    raise RuntimeError("the unrelated executable unexpectedly acquired net_admin permission")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("label", "boundaries", "child", "nested", "unrelated"))
    parser.add_argument("--expected", choices=("unconfined", PROFILE))
    parser.add_argument("--parent-ns", nargs=3)
    args = parser.parse_args()
    result: dict[str, object]
    if args.mode == "label":
        result = observe_label(str(args.expected))
    elif args.mode == "boundaries":
        if os.getuid() == 0:
            raise RuntimeError("boundary probes must run as the ordinary non-root job user")
        parent = namespaces()
        result = {"nested_execution": run_child("nested", parent)}
        negative = subprocess.run(
            [
                "/usr/bin/unshare",
                "--user",
                "--map-root-user",
                "--net",
                "/usr/bin/python3",
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "unrelated",
                "--parent-ns",
                *parent,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        result["unrelated_execution"] = {
            "exit": negative.returncode,
            "stdout": negative.stdout,
            "stderr": negative.stderr,
        }
        if negative.returncode and "Operation not permitted" not in negative.stderr:
            raise RuntimeError(f"unrecognized negative-control failure: {negative.stderr}")
    elif args.mode == "unrelated":
        result = unrelated([str(x) for x in args.parent_ns])
    else:
        result = child([str(x) for x in args.parent_ns], args.mode == "nested")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
