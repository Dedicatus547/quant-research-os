"""Freeze real synthetic filesystem bytes without executing Python or CLI doubles."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest
from test_hosted_deployment import _policy

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.hosted_deployment import HostedClientConfiguration
from quantos.infrastructure.hosted_deployment import freeze_python_install, install_inventory
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.mark.parametrize(
    "damage", (None, "occupied", "absolute", "traversal", "symlink", "missing", "channel")
)
def test_install_uses_wheel_and_removes_editable_and_import_hook_sources(
    tmp_path: Path, damage: str | None
) -> None:
    base = tmp_path / "base-python"
    base_site = base / "lib/python3.11/site-packages"
    base_site.mkdir(parents=True)
    (base_site / "old-base-hook.pth").write_bytes(b"synthetic forbidden old hook")
    (base / "bin").mkdir()
    (base / "bin/python3").write_bytes(b"synthetic Python, never executed")
    dependencies = tmp_path / "dependencies/lib/python3.11/site-packages"
    dependencies.mkdir(parents=True)
    (dependencies / "kept-package").mkdir()
    (dependencies / "kept-package/__init__.py").write_bytes(b"synthetic package bytes")
    (dependencies / "kept-single.py").write_bytes(b"synthetic module bytes")
    (dependencies / "unsafe.pth").write_bytes(b"synthetic forbidden hook")
    for name in ("quantos", "quant_research_os-editable", "_quant_research_os-editable"):
        (dependencies / name).mkdir()
        (dependencies / name / "canary").write_bytes(b"synthetic editable source")
    codex = tmp_path / "codex"
    codex.write_bytes(b"synthetic CLI bytes, never executed")
    wheel = tmp_path / "synthetic.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        if damage != "missing":
            archive.writestr("quantos/__init__.py", b"synthetic frozen wheel bytes")
        if damage in ("absolute", "traversal", "symlink"):
            member = zipfile.ZipInfo(
                "/outside-canary"
                if damage == "absolute"
                else "../outside-canary"
                if damage == "traversal"
                else "quantos/alias"
            )
            if damage == "symlink":
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, b"synthetic unsafe member")
    configuration = HostedClientConfiguration(
        socket_path="/wrong-channel" if damage == "channel" else "/channel/quantos.sock",
        policy=_policy(),
    )
    source_before = (raw_inventory(base), raw_inventory(dependencies), wheel.read_bytes())
    target = tmp_path / "frozen"
    if damage == "occupied":
        target.mkdir()
        (target / "retained").write_bytes(b"original retained root")
    arguments = dict(
        wheel=wheel,
        base_python=base,
        dependency_site=dependencies,
        codex_binary=codex,
        client_configuration=configuration,
    )
    if damage is None:
        inventory = freeze_python_install(target, **arguments)
        assert inventory == install_inventory(target)
        site = target / "python/lib/python3.11/site-packages"
        assert {path.name for path in site.iterdir()} == {
            "kept-package",
            "kept-single.py",
            "quantos",
        }
        assert (site / "quantos/__init__.py").read_bytes() == b"synthetic frozen wheel bytes"
        assert (target / "codex").read_bytes() == codex.read_bytes()
        assert (target / "hosted-client.json").read_bytes() == configuration.canonical_bytes()
    else:
        with pytest.raises(ArtifactIntegrityError):
            freeze_python_install(target, **arguments)
        assert not (target / "hosted-client.json").exists()
        if damage == "occupied":
            assert (target / "retained").read_bytes() == b"original retained root"
    assert not (tmp_path / "outside-canary").exists()
    assert source_before == (raw_inventory(base), raw_inventory(dependencies), wheel.read_bytes())
