"""Real fork/pinned-inode staging orchestration with an explicit tiny install double.

Derivation and installation are synthetic. Native child reaping, variant field
binding, file inventories and declaration retention remain enabled. No B/I0/D or
Q06 qualification is implied by the fixtures.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_budget_staging_paths import ROLES, _parent

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_budget_deployment as stage
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_verification import raw_inventory

BOUND_FIELDS = (
    "exact_commit",
    "lock_hash",
    "wheel_hash",
    "install_inventory_hash",
    "cli_binary_hash",
    "mount_policy_hash",
    "seccomp_bpf_hash",
    "os_inventory_hash",
    "model_configuration_hash",
    "extraction_rule_hash",
    "projection_inventory_hash",
    "operating_system",
    "kernel_release",
    "python_version",
    "libc",
    "bwrap_binary_hash",
    "bwrap_version",
    "libseccomp_binary_hash",
    "policy",
)


def _bundle(digest):
    return SimpleNamespace(
        content_hash=digest,
        frozen_byte_objects=(),
        initial_ledger_directory="nested",
        canonical_bytes=lambda: canonical_json_bytes({"synthetic_bundle": digest}),
    )


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "child_error",
        "timeout",
        "variant",
        "runtime_field",
        "model_configuration",
        "install",
        "projection",
        "provenance",
        "declaration",
    ),
)
def test_budget_staging_reaps_children_and_binds_original_inventory_and_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    parent = _parent(tmp_path)
    parent.bundle = _bundle("a" * 64)
    parent.launcher_configuration = "synthetic frozen model configuration"
    fields = {name: f"frozen-{name}" for name in BOUND_FIELDS}
    fields.update(content_hash="b" * 64, exact_commit="c" * 40, wheel_hash="d" * 64)
    parent.profile = SimpleNamespace(**fields)
    bounded = _bundle("e" * 64)
    monkeypatch.setattr(stage, "derive_hosted_budget_case", lambda *_args, **_kwargs: bounded)
    case = "request_submissions"
    target = parent.root / "qualification-deployments/Q06" / case

    def child(root):
        paths = SimpleNamespace(
            install=root / "install", projection=root / "projection", provenance=root / "provenance"
        )
        installed, projected, provenance = (
            install_inventory(paths.install),
            install_inventory(paths.projection),
            install_inventory(paths.provenance),
        )
        child_fields = {
            **vars(parent.profile),
            "content_hash": "f" * 64,
            "provenance_inventory_hash": provenance.content_hash,
        }
        if damage == "runtime_field":
            child_fields["python_version"] = "unbound runtime"
        return SimpleNamespace(
            root=root,
            paths=paths,
            profile=SimpleNamespace(**child_fields),
            bundle=_bundle("0" * 64) if damage == "variant" else bounded,
            launcher_configuration="unbound configuration"
            if damage == "model_configuration"
            else parent.launcher_configuration,
            install=installed,
            initial_projection=projected,
        )

    def freeze(root, workspace, bundle, objects, seed, **kwargs):
        assert root == Path(".") and Path.cwd() == target
        assert workspace == tmp_path and bundle is bounded and objects == {}
        assert seed == parent.paths.offline_inputs / "nested"
        assert os.fstat(kwargs["prepared_root_fd"]).st_ino == target.stat().st_ino
        if damage == "child_error":
            raise ArtifactIntegrityError("synthetic installation failure")
        if damage == "timeout":
            time.sleep(1000)  # Parent's fixed simulated deadline immediately kills this child.
        for role in ("install", "projection", "provenance"):
            shutil.copytree(parent.paths.install, Path(role))
        return child(target)

    monkeypatch.setattr(stage, "stage_hosted_deployment", freeze)

    def read(root, digest):
        assert root == target and digest == "f" * 64
        result = child(root)
        if damage in {"install", "projection", "provenance"}:
            getattr(result.paths, damage).joinpath("nested/canary").write_bytes(b"changed original")
        return result

    monkeypatch.setattr(stage, "read_managed_deployment", read)
    if damage == "timeout":
        clock = iter((0.0, 301.0))
        monkeypatch.setattr(
            stage, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=time.sleep)
        )
    before = {role: raw_inventory(parent.root / role) for role in ROLES if role != "evidence"}
    if damage in {
        "child_error",
        "timeout",
        "variant",
        "runtime_field",
        "model_configuration",
        "install",
        "projection",
        "provenance",
    }:
        with pytest.raises(ArtifactIntegrityError):
            stage.stage_managed_budget_deployment(
                parent, case, tmp_path, base_python=tmp_path, dependency_site=tmp_path
            )
        assert not (parent.root / f"evidence/budget-deployment-{case}.json").exists()
        failures = list((parent.root / "evidence").glob("budget-stage-failure-*.json"))
        if damage in {"child_error", "timeout", "variant", "runtime_field", "model_configuration"}:
            assert len(failures) == 1
            assert json.loads(failures[0].read_bytes())["exit_code"] != 0
    else:
        result = stage.stage_managed_budget_deployment(
            parent, case, tmp_path, base_python=tmp_path, dependency_site=tmp_path
        )
        assert result.root == target
        assert (
            stage.read_managed_budget_deployment(parent, case, result.profile.content_hash).bundle
            is bounded
        )
        declaration = parent.root / f"evidence/budget-deployment-{case}.json"
        assert (
            json.loads(declaration.read_bytes())["child_business_inputs_hash"]
            == bounded.content_hash
        )
        if damage == "declaration":
            declaration.write_bytes(b"untrusted declaration")
            with pytest.raises(ArtifactIntegrityError):
                stage.read_managed_budget_deployment(parent, case, result.profile.content_hash)
        with pytest.raises(ArtifactIntegrityError, match="fresh retained roots"):
            stage.stage_managed_budget_deployment(
                parent, case, tmp_path, base_python=tmp_path, dependency_site=tmp_path
            )
    assert before == {role: raw_inventory(parent.root / role) for role in before}
