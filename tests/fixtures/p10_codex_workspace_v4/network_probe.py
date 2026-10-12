"""Four socket-creation observations, without DNS or network traffic. No verdict."""

import errno
import hashlib
import json
import os
import socket
import sys


def main():
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
