"""P10 v4-env1: fix the probe process environment before observing sockets."""

import errno
import hashlib
import json
import os
import socket
import sys

ENVIRONMENT = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}
ENV_LAUNCHER = "/usr/bin/env"
ENV_LAUNCHER_HASH = "f13fae95a6f3fcba6c0ee8787c92747089eb81e550673f135bc4bc09bfc174d1"
FIXED_ENVIRONMENT_ARGUMENT = "--environment-fixed"


def establish_environment():
    if sys.argv[1:] == [FIXED_ENVIRONMENT_ARGUMENT]:
        # Inspect the real post-exec environment; do not rewrite observation values.
        if dict(os.environ) != ENVIRONMENT:
            raise RuntimeError("probe process environment is not exact")
        return
    if sys.argv[1:]:
        raise RuntimeError("unexpected probe arguments")
    digest = hashlib.sha256()
    with open(ENV_LAUNCHER, "rb") as launcher:
        for chunk in iter(lambda: launcher.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest() != ENV_LAUNCHER_HASH:
        raise RuntimeError("probe environment launcher identity mismatch")
    # Replace this process; no extra child or alternate model-visible command.
    # This setup belongs only to the network probe, never the secret-leak probe.
    os.execve(
        ENV_LAUNCHER,
        [
            ENV_LAUNCHER,
            "-i",
            *(f"{key}={value}" for key, value in ENVIRONMENT.items()),
            "/usr/bin/python3",
            "-I",
            "-S",
            os.path.abspath(__file__),
            FIXED_ENVIRONMENT_ARGUMENT,
        ],
        {},
    )
    raise RuntimeError("probe environment exec unexpectedly returned")


def main():
    establish_environment()
    samples = []
    for family in ("AF_INET", "AF_INET6"):
        for kind in ("SOCK_STREAM", "SOCK_DGRAM"):
            # Only socket creation errors count as operation observations.
            try:
                descriptor = socket.socket(getattr(socket, family), getattr(socket, kind))
            except OSError as error:
                result, number = "ERROR", error.errno
            else:
                descriptor.close()  # A close error is a program failure, never a denial.
                result, number = "CREATED", None
            samples.append(
                {
                    "schema_version": "p10-socket-sample/v1",
                    "family": family,
                    "type": kind,
                    "operation": "socket",
                    "result": result,
                    "errno": number,
                }
            )
    with open(sys.executable, "rb") as interpreter:
        digest = hashlib.sha256()
        for chunk in iter(lambda: interpreter.read(65536), b""):
            digest.update(chunk)
        interpreter_hash = digest.hexdigest()
    environment = {name: os.environ.get(name) for name in ("LANG", "PATH", "TZ")}
    output = {
        "schema_version": "p10-socket-observation/v1",
        "context": {
            "schema_version": "p10-probe-context/v1",
            "cwd": os.getcwd(),
            "uid": os.getuid(),
            "interpreter_hash": interpreter_hash,
            "environment": environment,
        },
        "samples": samples,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if all(sample["result"] == "CREATED" for sample in samples):
        return 0
    if all(sample["result"] == "ERROR" and sample["errno"] == errno.EPERM for sample in samples):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
