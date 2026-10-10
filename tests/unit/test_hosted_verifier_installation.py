"""The formal verifier's own project code must match frozen install bytes."""

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.contracts.base import sha256_bytes
from quantos.infrastructure import hosted_verification as verification


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "changed",
        "missing_inventory",
        "no_file",
        "symlink",
        "main_changed",
        "outside_install",
        "custom_loader",
        "cache",
        "cache_prefix",
        "bytecode_inventory",
        "ordinary_interpreter",
    ],
)
def test_formal_verifier_cannot_use_another_checkout_or_unbound_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str | None
) -> None:
    installation = tmp_path / "install"
    source = installation / "python/lib/python3.11/site-packages/quantos/example.py"
    source.parent.mkdir(parents=True)
    native = installation / "python-seeded"
    native.write_bytes(b"frozen native interpreter fixture")
    source.write_bytes(b"FROZEN_VERIFIER = True\n")
    digest = sha256_bytes(source.read_bytes())
    cached = "/tmp/quantos-disabled-bytecode-cache/example.pyc"
    module = SimpleNamespace(
        __file__=str(source),
        __loader__=SourceFileLoader("quantos.example", str(source)),
        __spec__=SimpleNamespace(name="quantos.example", origin=str(source)),
        __cached__=cached,
    )
    modules = {"quantos.example": module}
    installed = [
        SimpleNamespace(
            relative_path="python-seeded", bytes_hash=sha256_bytes(native.read_bytes())
        ),
        SimpleNamespace(
            relative_path="python/lib/python3.11/site-packages/quantos/example.py",
            bytes_hash=digest,
        ),
    ]
    if mutation in ("changed", "main_changed"):
        source.write_bytes(b"FROZEN_VERIFIER = False\n")
    if mutation == "missing_inventory":
        installed = [
            SimpleNamespace(
                relative_path="python-seeded", bytes_hash=sha256_bytes(native.read_bytes())
            ),
        ]
    elif mutation == "no_file":
        module.__file__ = None
    elif mutation == "symlink":
        alias = source.parent / "alias.py"
        alias.symlink_to(source)
        module.__file__ = str(alias)
    elif mutation == "main_changed":
        module.__spec__ = SimpleNamespace(name="quantos.example", origin=str(source))
        modules = {"__main__": module}
    # Test doubles only isolate the loaded-module registry. The real file hash is
    # read and no producer assertion can override a different source image.
    state = SimpleNamespace(
        modules=modules,
        executable=str(native),
        pycache_prefix="/tmp/quantos-disabled-bytecode-cache",
        dont_write_bytecode=True,
        flags=SimpleNamespace(
            optimize=0,
            isolated=1,
            ignore_environment=1,
            no_user_site=1,
            safe_path=True,
            hash_randomization=0,
        ),
    )
    if mutation == "outside_install":
        other = tmp_path / "outside.py"
        other.write_bytes(source.read_bytes())
        module.__file__ = str(other)
    elif mutation == "custom_loader":
        module.__loader__ = SimpleNamespace(path=str(source))
    elif mutation == "cache":
        (tmp_path / "cache.pyc").write_bytes(b"stale cache")
    elif mutation == "cache_prefix":
        (tmp_path / "cache-prefix").mkdir()
    elif mutation == "bytecode_inventory":
        installed.append(
            SimpleNamespace(
                relative_path="python/lib/python3.11/site-packages/quantos/__pycache__/example.cpython-311.pyc",
                bytes_hash="a" * 64,
            )
        )
    elif mutation == "ordinary_interpreter":
        state.flags.isolated = 0
    monkeypatch.setattr(verification, "sys", state)
    monkeypatch.setattr(verification, "cache_from_source", lambda _: cached)

    def local_path(value):
        return {
            "/install": installation,
            "/tmp/quantos-disabled-bytecode-cache": tmp_path / "cache-prefix",
            cached: tmp_path / "cache.pyc",
        }.get(str(value), Path(value))

    monkeypatch.setattr(verification, "Path", local_path)
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
