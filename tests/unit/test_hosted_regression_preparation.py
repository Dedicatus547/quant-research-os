"""Real forked preparation preserves source installation and failed attempts."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_budget_staging_paths import _facts, _parent

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_deployment import MOUNT_POLICY_BYTES, install_inventory
from quantos.infrastructure.hosted_regression_capture import prepare_managed_regression
from quantos.infrastructure.hosted_regression_runtime import (
    COVERAGE_PTH,
    ci_python,
    verify_ci_declaration,
    verify_ci_runtime,
)
from quantos.infrastructure.hosted_verification import directory_inventory, raw_inventory


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantos.infrastructure import hosted_regression_capture

    # Tiny preparation fixtures do not establish a production storage quota.
    monkeypatch.setattr(hosted_regression_capture, "storage_checkpoint", lambda *_: None)


@pytest.mark.parametrize("case", ("valid", "unbound-hook", "non-native-node", "existing-root"))
def test_fixed_prefix_preparation_reaps_and_retains_original_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    original_fork = os.fork
    children: list[int] = []

    def observed_fork() -> int:
        pid = original_fork()
        if pid > 0:
            children.append(pid)
        return pid

    monkeypatch.setattr(os, "fork", observed_fork)
    root = tmp_path / "manager"
    root.mkdir()
    parent = _parent(root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lock = b"synthetic frozen lock\n"
    (workspace / "uv.lock").write_bytes(lock)
    for command in (
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Frozen fixture",
        ),
    ):
        subprocess.run(
            ("/usr/bin/git", "-C", str(workspace), *command), check=True, capture_output=True
        )
    commit = (
        subprocess.check_output(("/usr/bin/git", "-C", str(workspace), "rev-parse", "HEAD"))
        .decode()
        .strip()
    )
    parent.profile = SimpleNamespace(
        exact_commit=commit,
        lock_hash=sha256_bytes(lock),
        content_hash="d" * 64,
        mount_policy_hash=sha256_bytes(MOUNT_POLICY_BYTES),
    )
    install = parent.paths.install
    digest = (
        base64.urlsafe_b64encode(bytes.fromhex(sha256_bytes(COVERAGE_PTH))).rstrip(b"=").decode()
    )
    record = f"a1_coverage.pth,sha256={digest},{len(COVERAGE_PTH)}\n".encode()
    if case == "unbound-hook":
        record = b"a1_coverage.pth,sha256=wrong,205\n"
    atomic_write_bytes(
        install / "python/lib/python3.11/site-packages/coverage-7.16.0.dist-info/RECORD", record
    )
    atomic_write_bytes(install / "python/bin/python3.11", b"fixture interpreter, never executed")
    parent.install = install_inventory(install)
    node = tmp_path / "node"
    node.write_bytes(b"\x7fELFfixture native Node" if case != "non-native-node" else b"script Node")
    if case == "existing-root":
        (root / "qualification-checks/Q12").mkdir(parents=True)
        (root / "qualification-checks/Q12/retained-failure").write_bytes(
            b"immutable existing attempt"
        )
    before = _facts(root)
    protected = {
        role: (raw_inventory(root / role), directory_inventory(root / role))
        for role in (
            "authority",
            "install",
            "channel",
            "inputs",
            "config",
            "initial-projection",
            "provenance",
        )
    }
    if case != "valid":
        with pytest.raises(ArtifactIntegrityError):
            prepare_managed_regression(parent, workspace, node_source=node)
        # Only the fixed evidence role may receive an original failure observation.
        for role in ("authority", "install", "channel", "inputs"):
            assert (root / role / "nested/canary").read_bytes() == b"immutable protected bytes"
        assert install_inventory(install) == parent.install
        assert {
            role: (raw_inventory(root / role), directory_inventory(root / role))
            for role in protected
        } == protected
        if case == "existing-root":
            assert _facts(root) == before
            assert (
                root / "qualification-checks/Q12/retained-failure"
            ).read_bytes() == b"immutable existing attempt"
        else:
            assert len(tuple((root / "evidence").glob("ci-prepare-failure-*.json"))) == 1
        for pid in children:
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
        return
    launch = prepare_managed_regression(parent, workspace, node_source=node)
    assert launch[0] == str(ci_python(root))
    assert launch[1:3] == ("-I", "-B")
    assert "quantos.infrastructure.hosted_regression_capture" in launch
    verify_ci_runtime(root, parent.install)
    declaration = verify_ci_declaration(root, parent.install)
    assert declaration["node_hash"] == sha256_bytes(node.read_bytes())
    assert _facts(root) == before
    assert Path.cwd() != root / "qualification-checks/Q12"
    assert len(children) == 1
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0], os.WNOHANG)
