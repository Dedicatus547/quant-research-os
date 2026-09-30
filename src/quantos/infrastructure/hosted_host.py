"""Fixed restricted-host CLI entrypoint; the manager supplies one-use tmpfs inputs."""

from __future__ import annotations

import os
from pathlib import Path

from quantos.artifacts.store import ArtifactIntegrityError, opened_directory, read_regular_bytes_at
from quantos.infrastructure.hosted_deployment import private_memory_fd


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
    from quantos.cli import app

    app()


if __name__ == "__main__":
    main()
