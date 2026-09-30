"""The formal verifier's own project code must match frozen install bytes."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.contracts.base import sha256_bytes
from quantos.infrastructure import hosted_verification as verification


@pytest.mark.parametrize(
    "mutation", [None, "changed", "missing_inventory", "no_file", "symlink", "main_changed"]
)
def test_formal_verifier_cannot_use_another_checkout_or_unbound_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str | None
) -> None:
    source = tmp_path / "verifier.py"
    source.write_bytes(b"FROZEN_VERIFIER = True\n")
    digest = sha256_bytes(source.read_bytes())
    module = SimpleNamespace(__file__=str(source))
    modules = {"quantos.example": module}
    installed = [
        SimpleNamespace(
            relative_path="python/lib/python3.11/site-packages/quantos/example.py",
            bytes_hash=digest,
        )
    ]
    if mutation in ("changed", "main_changed"):
        source.write_bytes(b"FROZEN_VERIFIER = False\n")
    if mutation == "missing_inventory":
        installed = []
    elif mutation == "no_file":
        module.__file__ = None
    elif mutation == "symlink":
        alias = tmp_path / "alias.py"
        alias.symlink_to(source)
        module.__file__ = str(alias)
    elif mutation == "main_changed":
        module.__spec__ = SimpleNamespace(name="quantos.example")
        modules = {"__main__": module}
    # Test doubles only isolate the loaded-module registry. The real file hash is
    # read and no producer assertion can override a different source image.
    monkeypatch.setattr(verification, "sys", SimpleNamespace(modules=modules))
    sources = SimpleNamespace(deployment=SimpleNamespace(install=SimpleNamespace(files=installed)))

    def disk_state():
        return source.read_bytes(), tuple(
            sorted(
                (path.name, path.lstat().st_ino, path.lstat().st_mtime_ns)
                for path in tmp_path.iterdir()
            )
        )

    before = disk_state()
    if mutation is None:
        verification.verify_loaded_project_installation(sources)
    else:
        with pytest.raises(verification.HostedQualificationError):
            verification.verify_loaded_project_installation(sources)
    assert disk_state() == before
