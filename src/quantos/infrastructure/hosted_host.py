"""Fixed restricted-host CLI entrypoint; the manager supplies one-use tmpfs inputs."""

from __future__ import annotations

import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory, read_regular_bytes_at
from quantos.infrastructure.hosted_deployment import private_memory_fd


def _read_exported_request(directory: Path) -> bytes:
    with opened_directory(directory) as parent:
        encoded = read_regular_bytes_at(parent, "hosted-request.json", max_bytes=1_048_576)
    from quantos.contracts.hosted import HostedAgentRequest, parse_hosted_contract

    parse_hosted_contract(encoded, HostedAgentRequest, max_bytes=1_048_576)
    return encoded


def main() -> None:
    with opened_directory(Path("/tmp")) as directory:
        capability = read_regular_bytes_at(directory, "hosted-client-capability", max_bytes=32)
        if len(capability) != 32:
            raise ArtifactIntegrityError("host client capability length differs")
        os.unlink("hosted-client-capability", dir_fd=directory)
    descriptor = private_memory_fd("hosted-client-capability")
    os.write(descriptor, capability)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if descriptor != 100:
        os.dup2(descriptor, 100, inheritable=False)
        os.close(descriptor)
    # Optional Qlib model discovery writes startup diagnostics to stdout. Keep the
    # CLI's stdout as one machine-readable reply; diagnostic bytes remain stderr.
    with redirect_stdout(sys.stderr):
        from quantos.cli import app

    if sys.argv[1:3] == ["hosted", "request-export"]:
        # Export to a new private tmpfs file through the existing CLI; return
        # those exact bytes to the manager's bounded capture pipe.
        with redirect_stdout(sys.stderr):
            result = app(standalone_mode=False)
        if isinstance(result, int) and result:
            raise SystemExit(result)
        sys.stdout.buffer.write(_read_exported_request(Path("/tmp")) + b"\n")
    else:
        app()


if __name__ == "__main__":
    main()
