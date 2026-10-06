"""Staging graph binding over real clean Git, wheel, Parquet and native launcher bytes.

The Python/CLI installation is an explicit tiny copy double, never executed.
These fixtures cannot establish installed service, actual model or MVP qualification.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from test_hosted_input_bootstrap import _inputs
from test_hosted_launcher import _configuration

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.contracts.hosted_inputs import HostedFrozenInputFile
from quantos.infrastructure import hosted_manager as manager
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_verification import raw_inventory


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic graph fixtures cannot prove a mounted production storage quota.
    monkeypatch.setattr(manager, "storage_checkpoint", lambda *_: None)


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "occupied",
        "configuration",
        "missing_object",
        "object_bytes",
        "seed",
        "wheel",
        "provenance",
    ),
)
def test_staging_binds_clean_checkout_and_exact_frozen_bytes_before_any_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    input_root = tmp_path / "inputs"
    bundle, _arguments = _inputs(input_root, monkeypatch)
    workspace = input_root / "provenance"
    for name, source in (
        ("snapshot", bundle.snapshot_directory),
        ("view", bundle.qlib_view_directory),
    ):
        shutil.copytree(input_root / source, workspace / "artifacts" / name)
    configuration = _configuration()
    model_data = configuration.canonical_bytes()
    objects = {
        item.logical_path: (input_root / item.logical_path).read_bytes()
        for item in bundle.frozen_byte_objects
    }
    objects["model.json"] = model_data
    bundle = bundle.model_copy(
        update={
            "snapshot_directory": "artifacts/snapshot",
            "qlib_view_directory": "artifacts/view",
            "agent_run_policy": bundle.agent_run_policy.model_copy(
                update={"requested_model_configuration_hash": configuration.content_hash}
            ),
            "hosted_recipe": bundle.hosted_recipe.model_copy(
                update={"requested_model_configuration_hash": configuration.content_hash}
            ),
            "frozen_byte_objects": tuple(
                HostedFrozenInputFile(
                    logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
                )
                for path, data in sorted(objects.items())
            ),
        }
    )
    wheel = tmp_path / "synthetic-quantos.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in sorted((workspace / "src/quantos").rglob("*")):
            if path.is_file():
                archive.writestr(
                    path.relative_to(workspace / "src").as_posix(),
                    path.read_bytes()
                    + (
                        b"wrong source"
                        if damage == "wheel" and path.name == "hosted_python.c"
                        else b""
                    ),
                )
    codex = tmp_path / "codex"
    codex.write_bytes(b"synthetic CLI identity, never executed")
    frozen_calls = []

    def freeze(root, **kwargs):
        frozen_calls.append(root)
        assert kwargs["wheel"] == wheel and kwargs["codex_binary"] == codex
        (root / "python/lib").mkdir(parents=True)
        shutil.copyfile(
            Path(sys.base_prefix) / "lib/libpython3.11.so.1.0", root / "python/lib/libpython3.11.so"
        )
        shutil.copyfile(codex, root / "codex")
        return install_inventory(root)

    monkeypatch.setattr(manager, "freeze_python_install", freeze)
    target = tmp_path / "deployment"
    if damage == "occupied":
        target.mkdir()
        (target / "retained").write_bytes(b"original failed root")
    elif damage == "configuration":
        configuration = _configuration(runtime_timeout_seconds=3)
    elif damage == "missing_object":
        objects.pop("model.json")
    elif damage == "object_bytes":
        objects["model.json"] += b"changed"
    elif damage == "seed":
        (input_root / "ledger" / bundle.initial_ledger_files[0].logical_path).write_bytes(
            b"changed seed"
        )
    elif damage == "provenance":
        (workspace / "src/quantos/cli.py").write_bytes(b"changed source")
    before = raw_inventory(input_root / "ledger")
    arguments = dict(
        wheel=wheel,
        base_python=Path(sys.base_prefix),
        dependency_site=tmp_path,
        codex_binary=codex,
        launcher_configuration=configuration,
    )
    if damage is None:
        deployment = manager.stage_hosted_deployment(
            target, workspace, bundle, objects, input_root / "ledger", **arguments
        )
        assert len(deployment.capability) == 32
        assert tuple(deployment.paths.authority.iterdir()) == ()
        assert tuple(deployment.paths.channel.iterdir()) == ()
        assert deployment.install == install_inventory(deployment.paths.install)
        assert deployment.profile.exact_commit == bundle.code_provenance.commit_hash
        assert deployment.profile.model_configuration_hash == configuration.content_hash
        assert (deployment.paths.install / "python-seeded").read_bytes().startswith(b"\x7fELF")
        assert deployment.spec.deployment_profile_hash == deployment.profile.content_hash
        restored = manager.read_managed_deployment(target, deployment.profile.content_hash)
        assert restored.profile == deployment.profile and restored.bundle == bundle
    else:
        from quantos.application.provenance import ProvenanceError

        with pytest.raises((ArtifactIntegrityError, ProvenanceError)):
            manager.stage_hosted_deployment(
                target, workspace, bundle, objects, input_root / "ledger", **arguments
            )
        assert frozen_calls == []
        if damage == "occupied":
            assert (target / "retained").read_bytes() == b"original failed root"
    assert before == raw_inventory(input_root / "ledger")
