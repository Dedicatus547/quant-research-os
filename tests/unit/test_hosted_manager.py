"""Manager provenance and stopped-channel guards; these are component tests only."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure.hosted_manager import stop_managed_service, verify_wheel_provenance


@pytest.mark.parametrize("mutation", [None, "changed", "missing", "extra", "duplicate"])
def test_wheel_must_match_tracked_checkout(tmp_path: Path, mutation: str | None) -> None:
    workspace = tmp_path / "source"
    source = workspace / "src/quantos"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"VERSION = 'frozen'\n")
    subprocess.run(("git", "init", "--quiet", str(workspace)), check=True)
    subprocess.run(("git", "-C", str(workspace), "add", "src"), check=True)
    wheel = tmp_path / "project.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        if mutation != "missing":
            archive.writestr(
                "quantos/__init__.py",
                b"changed" if mutation == "changed" else (source / "__init__.py").read_bytes(),
            )
        if mutation == "extra":
            archive.writestr("quantos/plugin.py", b"untrusted")
        if mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("quantos/__init__.py", b"replacement")
    if mutation is None:
        verify_wheel_provenance(workspace, wheel)
    else:
        with pytest.raises(ArtifactIntegrityError, match="wheel project"):
            verify_wheel_provenance(workspace, wheel)


def test_stop_preserves_bootstrap_and_rejects_unexpected_channel_entry(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    channel.mkdir()
    (tmp_path / "evidence").mkdir()
    observation = b'{"source":"actual-service-bootstrap"}'
    (channel / "bootstrap-observation.json").write_bytes(observation)
    process = subprocess.Popen(("/bin/sleep", "60"))
    deployment = SimpleNamespace(
        paths=SimpleNamespace(channel=channel), capability=b"q" * 32, root=tmp_path
    )
    stop_managed_service(deployment, process)
    assert process.poll() is not None
    assert list(channel.iterdir()) == []
    assert [path.read_bytes() for path in (tmp_path / "evidence").iterdir()] == [observation]
    (channel / "unexpected").write_bytes(b"retain this evidence")
    process = subprocess.Popen(("/bin/sleep", "60"))
    with pytest.raises(ArtifactIntegrityError, match="unexpected"):
        stop_managed_service(deployment, process)
    assert (channel / "unexpected").read_bytes() == b"retain this evidence"
