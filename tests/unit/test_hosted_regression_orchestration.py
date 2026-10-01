"""CI capture composition over a tiny frozen prefix and explicit kernel/check doubles.

No tool or namespace is executed by this fixture. It checks retained completion,
fixed command coverage, and source/authority integrity, never Q12 qualification.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_hosted_manager_client_capture import _deployment

from quantos.application.provenance import ProvenanceError, capture_code_provenance
from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure import hosted_regression_capture as capture
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_regression_runtime import (
    CI_PREFIX,
    COVERAGE_PTH,
    ci_python,
    expected_ci_runtime,
)
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory
from quantos.security import SecretArtifactRejected


@pytest.mark.parametrize(
    "damage",
    (None, "exit", "timeout", "secret", "authority", "source", "runtime", "occupied", "flags"),
)
def test_ci_capture_keeps_all_original_checks_and_rejects_changed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    deployment = _deployment(tmp_path / "manager")
    workspace = deployment.paths.provenance
    (workspace / "uv.lock").write_bytes(b"synthetic lock\n")
    (workspace / "source.py").write_bytes(b"frozen fixture\n")
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
    provenance = capture_code_provenance(workspace)
    deployment.profile.exact_commit = provenance.commit_hash
    deployment.profile.lock_hash = provenance.lockfile_hash
    relative = "lib/python3.11/site-packages/quantos/infrastructure/hosted_regression_capture.py"
    atomic_write_bytes(
        deployment.paths.install / "python/bin/python3.11",
        b"tiny interpreter identity, never executed",
    )
    atomic_write_bytes(
        deployment.paths.install / "python" / relative,
        b"tiny capture source identity, never loaded",
    )
    deployment.install = install_inventory(deployment.paths.install)
    target = deployment.root / CI_PREFIX
    target.mkdir(parents=True)
    shutil.copytree(deployment.paths.install / "python", target / ".venv")
    atomic_write_bytes(target / ".venv/lib/python3.11/site-packages/a1_coverage.pth", COVERAGE_PTH)
    expected = expected_ci_runtime(deployment.install)
    atomic_write_bytes(target / "runtime-install.json", expected.canonical_bytes())
    node = b"\x7fELFsynthetic Node identity, never executed"
    atomic_write_bytes(target / "node-bin/node", node)
    (target / "node-bin/node").chmod(0o500)
    declaration = {
        "schema_version": "hosted-management-ci-runtime/v1",
        "runtime_inventory_hash": expected.content_hash,
        "node_hash": sha256_bytes(node),
        "node_size_bytes": len(node),
        "coverage_hook_hash": sha256_bytes(COVERAGE_PTH),
    }
    atomic_write_bytes(target / "runtime-declaration.json", canonical_json_bytes(declaration))
    monkeypatch.setattr(capture, "__file__", str(target / ".venv" / relative))
    monkeypatch.setattr(
        capture,
        "sys",
        SimpleNamespace(
            executable=str(ci_python(deployment.root)),
            prefix=str(target / ".venv"),
            dont_write_bytecode=True,
            pycache_prefix=str(target / "manager-cache"),
            flags=SimpleNamespace(
                isolated=damage != "flags",
                ignore_environment=True,
                no_user_site=True,
                safe_path=True,
            ),
        ),
    )
    monkeypatch.setattr(capture, "version", lambda _name: "synthetic-tool-version")
    observed = []

    def check(argv, **kwargs):
        name = capture.CHECK_NAMES[len(observed)]
        observed.append(name)
        assert kwargs["environment"] == {"PATH": "/usr/bin:/bin"}
        assert kwargs["timeout"] == (14400 if name == "pytest" else 7200)
        assert "--unshare-net" in argv and "--unshare-pid" in argv
        kwargs["kernel_observations"].append({"synthetic_kernel_double": True})
        if name == "ruff":
            if damage == "authority":
                (deployment.paths.authority / "changed").write_bytes(b"changed authority")
            elif damage == "source":
                (workspace / "source.py").write_bytes(b"changed source")
            elif damage == "runtime":
                (target / ".venv/bin/python3.11").write_bytes(b"changed prefix")
        output = (
            deployment.capability
            if damage == "secret" and name == "ruff"
            else b"synthetic check stdout\n"
        )
        return (
            100 + len(observed),
            int(damage == "exit" and name == "ruff"),
            output,
            "TIMED_OUT" if damage == "timeout" and name == "pytest" else None,
        )

    monkeypatch.setattr(capture, "_check", check)
    before = raw_inventory(deployment.paths.authority)
    if damage == "occupied":
        (target / "run.json").write_bytes(b"immutable failed attempt")
    if damage is None:
        capture.run_managed_regression(deployment, workspace)
    else:
        with pytest.raises(
            (
                ArtifactIntegrityError,
                HostedQualificationError,
                SecretArtifactRejected,
                ProvenanceError,
            )
        ):
            capture.run_managed_regression(deployment, workspace)
    if damage in {None, "exit", "timeout"}:
        assert observed == list(capture.CHECK_NAMES)
        record = json.loads((target / "run.json").read_bytes())
        assert record["qualification_eligibility"] == "NOT_QUALIFIED"
        assert record["authority_before"] == record["authority_after"]
        assert len(record["checks"]) == 5
        for name in observed:
            assert (target / f"{name}.txt").read_bytes() == b"synthetic check stdout\n"
            assert (target / f"{name}-prelaunch.json").exists()
            assert (target / f"{name}-exit.json").exists()
    elif damage == "occupied":
        assert observed == []
        assert (target / "run.json").read_bytes() == b"immutable failed attempt"
    else:
        assert not (target / "run.json").exists()
    if damage != "authority":
        assert raw_inventory(deployment.paths.authority) == before
