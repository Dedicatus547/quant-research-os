"""Private capability FD transfer on real files and memfds; config is a double."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure import hosted_service as service


@pytest.mark.parametrize(
    "damage", (None, "missing", "extra", "descriptor", "short", "oversized", "alias", "transfer")
)
def test_staged_capabilities_require_exact_unique_files_and_private_fd_slots(
    tmp_path, monkeypatch, damage
):
    stage = tmp_path / "private-tmp"
    stage.mkdir()
    values = (b"A" * 32, b"B" * 32)
    names = [f"hosted-service-capability-{n}" for n in range(2)]
    for name, value in zip(names, values, strict=True):
        (stage / name).write_bytes(value)
    if damage == "missing":
        (stage / names[1]).unlink()
    elif damage == "extra":
        (stage / "hosted-service-capability-9").write_bytes(b"C" * 32)
    elif damage == "short":
        (stage / names[0]).write_bytes(b"A" * 31)
    elif damage == "oversized":
        (stage / names[0]).write_bytes(b"A" * 33)
    elif damage == "alias":
        (stage / names[0]).rename(stage / "alias-source")
        (stage / names[0]).symlink_to("alias-source")
    principals = tuple(
        SimpleNamespace(capability_fd=100 + n + (1 if damage == "descriptor" else 0))
        for n in range(2)
    )
    profile = SimpleNamespace(configuration_hash="a" * 64)
    configuration = SimpleNamespace(principals=principals)
    monkeypatch.setattr(
        service,
        "_hashed_configuration",
        lambda _root, _hash, cls: (
            profile if cls.__name__ == "HostedDeploymentProfile" else configuration
        ),
    )
    monkeypatch.setattr(service, "Path", lambda path: stage if path == "/tmp" else Path(path))
    created = []
    original_memfd = service.private_memory_fd

    def allocate(name):
        descriptor = original_memfd(name)
        created.append(descriptor)
        return descriptor

    monkeypatch.setattr(service, "private_memory_fd", allocate)
    # Retain any unrelated existing slots; the test never steals a caller FD.
    saved = {}
    for slot in (100, 101):
        try:
            saved[slot] = os.dup(slot)
        except OSError:
            saved[slot] = None
    original_dup2 = os.dup2
    if damage == "transfer":

        def reject_transfer(source, target, **kwargs):
            if target in (100, 101):
                raise OSError("synthetic private transfer failure")
            return original_dup2(source, target, **kwargs)

        monkeypatch.setattr(service.os, "dup2", reject_transfer)
    try:
        if damage is None:
            service.hydrate_service_capabilities("b" * 64)
            assert not any((stage / name).exists() for name in names)
            for slot, value in zip((100, 101), values, strict=True):
                assert os.pread(slot, 33, 0) == value
                assert not os.get_inheritable(slot)
                assert os.fstat(slot).st_nlink == 0
        else:
            with pytest.raises((ArtifactIntegrityError, OSError, ValueError)):
                service.hydrate_service_capabilities("b" * 64)
            if damage != "transfer":
                assert not created
        for descriptor in created:
            if descriptor not in (100, 101):
                with pytest.raises(OSError):
                    os.fstat(descriptor)
    finally:
        for slot, saved_descriptor in saved.items():
            if saved_descriptor is None:
                with suppress(OSError):
                    os.close(slot)
            else:
                original_dup2(saved_descriptor, slot)
                os.close(saved_descriptor)
