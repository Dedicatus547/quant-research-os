"""Synthetic CI source fixtures exercise binding, never deployed CI qualification."""

from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from importlib.metadata import distribution, version
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from test_hosted_regression_verification import _reports

from quantos.application.provenance import capture_runtime_fingerprint
from quantos.artifacts.store import atomic_write_bytes
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationRoot,
)
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_qualification_sources import HostedVerifiedSources
from quantos.infrastructure.hosted_regression_capture import tracked_regression_inventory
from quantos.infrastructure.hosted_regression_runtime import (
    COVERAGE_PTH,
    ci_environment,
    ci_namespace_command,
    ci_python,
    expected_ci_runtime,
)
from quantos.infrastructure.hosted_regression_verification import (
    CHECK_NAMES,
    CI_PACKAGES,
    CI_PREFIX,
    regression_commands,
    verify_q12,
)
from quantos.infrastructure.hosted_verification import HostedQualificationError, raw_inventory


@pytest.mark.parametrize(
    "mutation",
    (
        None,
        "missing-check",
        "missing-source",
        "copied-log",
        "original-log",
        "exit-log",
        "prelaunch",
        "selected-tests",
        "exit-failed",
        "exit-bool",
        "wait-missing",
        "same-pid",
        "wrong-parent",
        "timeout",
        "output-hash",
        "profile",
        "commit",
        "lock",
        "runtime",
        "python",
        "tool",
        "tracked",
        "new-source",
        "snapshot",
        "directory",
        "coverage-omitted",
        "external-python",
        "external-prefix",
        "external-module",
        "runtime-prefix",
        "runtime-node",
        "runtime-inventory",
        "runtime-declaration",
        "namespace-command",
        "kernel-missing",
        "kernel-shared-network",
        "kernel-executable",
        "kernel-ancestry",
        "kernel-unobserved",
        "kernel-network-allowed",
        "kernel-shared-pid",
        "kernel-unreaped-namespace",
        "manager-non-isolated",
    ),
)
def test_exact_ci_source_and_completion_facts_fail_closed(
    tmp_path: Path, mutation: str | None
) -> None:
    manager, bundle, workspace = (tmp_path / name for name in ("manager", "bundle", "workspace"))
    workspace.mkdir()
    (workspace / "example.py").write_bytes(b"frozen source\n")
    (workspace / "uv.lock").write_text(
        "\n".join(
            f'[[package]]\nname = "{name}"\nversion = "{version(name)}"' for name in CI_PACKAGES
        )
    )
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
            "Synthetic source fixture",
        ),
    ):
        subprocess.run(
            ("/usr/bin/git", "-C", str(workspace), *command), check=True, capture_output=True
        )
    tracked = tracked_regression_inventory(workspace)
    fingerprint = capture_runtime_fingerprint()
    install = manager / "install"
    atomic_write_bytes(install / "python/bin/python3.11", b"synthetic frozen interpreter")
    for name in CI_PACKAGES:
        relative = "python/lib/python3.11/site-packages/" + name.replace("-", "_")
        relative += f"-{version(name)}.dist-info/METADATA"
        data = distribution(name).read_text("METADATA")
        assert data is not None
        atomic_write_bytes(install / relative, data.encode())
    atomic_write_bytes(
        install / "python/lib/python3.11/site-packages/quantos/example.py",
        b"fixture example source",
    )
    capture = "lib/python3.11/site-packages/quantos/infrastructure/hosted_regression_capture.py"
    atomic_write_bytes(install / "python" / capture, b"fixture capture source")
    if mutation == "coverage-omitted":
        atomic_write_bytes(
            install / "python/lib/python3.11/site-packages/quantos/omitted.py",
            b"unmeasured project source",
        )
    installation = install_inventory(install)
    deployment = SimpleNamespace(
        root=manager,
        paths=SimpleNamespace(provenance=workspace, install=install),
        profile=SimpleNamespace(
            content_hash="d" * 64,
            exact_commit="c" * 40,
            lock_hash="b" * 64,
            python_version=fingerprint.python_version,
            operating_system=fingerprint.operating_system,
            kernel_release=fingerprint.operating_system_release,
            libc=fingerprint.libc.replace("-", " "),
        ),
        bundle=SimpleNamespace(execution_bindings=SimpleNamespace(qlib_version=version("pyqlib"))),
        install=installation,
    )
    target = manager / CI_PREFIX
    python = ci_python(manager)
    shutil.copytree(install / "python", target / ".venv")
    atomic_write_bytes(target / ".venv/lib/python3.11/site-packages/a1_coverage.pth", COVERAGE_PTH)
    runtime = expected_ci_runtime(installation)
    node = b"\x7fELFsynthetic Node identity; never executed"
    atomic_write_bytes(target / "node-bin/node", node)
    (target / "node-bin/node").chmod(0o500)
    declaration = {
        "schema_version": "hosted-management-ci-runtime/v1",
        "runtime_inventory_hash": runtime.content_hash,
        "node_hash": sha256_bytes(node),
        "node_size_bytes": len(node),
        "coverage_hook_hash": sha256_bytes(COVERAGE_PTH),
    }
    installed = {file.relative_path: file.bytes_hash for file in installation.files}
    commands = regression_commands(python, workspace, target)
    records: dict[str, bytes] = {
        "runtime-fingerprint.json": fingerprint.canonical_bytes(),
        "tracked-before.json": tracked.canonical_bytes(),
        "tracked-after.json": tracked.canonical_bytes(),
        "runtime-install.json": runtime.canonical_bytes(),
        "runtime-declaration.json": canonical_json_bytes(declaration),
    }
    records["coverage.xml"], records["pytest.xml"] = _reports()
    coverage = ET.fromstring(records["coverage.xml"])
    classes = coverage.find("./packages/package/classes")
    assert classes is not None
    ET.SubElement(
        classes,
        "class",
        {
            "filename": "src/quantos/infrastructure/hosted_regression_capture.py",
        },
    )
    records["coverage.xml"] = ET.tostring(coverage)
    runs = []
    for index, name in enumerate(CHECK_NAMES):
        output = b"synthetic check log\n"
        wrapper_pid = 1000 + index
        guest_pid = 2000 + index
        namespace_argv = ci_namespace_command(
            python, workspace, target, ci_environment(python, workspace, target), commands[name]
        )
        run = {
            "name": name,
            "argv": list(commands[name]),
            "namespace_argv": list(namespace_argv),
            "kernel_observations": [
                {
                    "pid": guest_pid,
                    "parent_pid": wrapper_pid,
                    "wrapper_pid": wrapper_pid,
                    "manager_pid": 999,
                    "net_namespace_inode": 3001,
                    "manager_net_namespace_inode": 3000,
                    "network_probe_errno": 101,
                    "executable_hash": installed["python/bin/python3.11"],
                    "kernel_ancestry": [guest_pid, wrapper_pid, 999],
                    "kernel_observed_before_exec": True,
                    "namespace_pid": 2,
                    "namespace_parent_pid": 1,
                    "namespace_init_pid": wrapper_pid,
                    "pid_namespace_inode": 4001,
                    "manager_pid_namespace_inode": 4000,
                    "namespace_exit_observed": True,
                }
            ],
            "pid": wrapper_pid,
            "parent_pid": 999,
            "return_code": 0,
            "waitpid_observed": True,
            "output_hash": sha256_bytes(output),
            "failure": None,
        }
        runs.append(run)
        records[f"{name}.txt"] = output
        records[f"{name}-exit.json"] = canonical_json_bytes(run)
        records[f"{name}-prelaunch.json"] = canonical_json_bytes(
            {
                "schema_version": "hosted-manager-regression-prelaunch/v1",
                "deployment_profile_hash": "d" * 64,
                "manager_pid": 999,
                "name": name,
                "argv": commands[name],
                "namespace_argv": namespace_argv,
                "cwd": str(workspace),
                "environment_policy": "FIXED_OFFLINE_CI_NO_CREDENTIALS/v1",
            }
        )
    roots = []
    exports = {}
    for phase in ("before", "after"):
        source = manager / f"qualification-cases/Q12/{phase}"
        logical = f"cases/Q12/{phase}"
        atomic_write_bytes(source / "frozen.json", b"original authority fixture")
        atomic_write_bytes(bundle / logical / "frozen.json", b"original authority fixture")
        inventory = raw_inventory(source)
        records[f"{phase}-inventory.json"] = inventory.canonical_bytes()
        roots.append(
            HostedQualificationRoot(
                name=phase,
                logical_path=logical,
                campaign_hash="a" * 64,
                raw_inventory_path=f"cases/Q12/{phase}-inventory.json",
            )
        )
        exports[f"{logical}/frozen.json"] = HostedManagerExportFile(
            bundle_path=f"{logical}/frozen.json",
            source_path=f"qualification-cases/Q12/{phase}/frozen.json",
            sha256=sha256_bytes(b"original authority fixture"),
            size_bytes=len(b"original authority fixture"),
        )
    fact = {
        "schema_version": "hosted-manager-regression/v1",
        "deployment_profile_hash": "d" * 64,
        "exact_commit": "c" * 40,
        "lockfile_hash": "b" * 64,
        "runtime_fingerprint_hash": fingerprint.content_hash,
        "manager_pid": 999,
        "python": str(python),
        "python_prefix": str(target / ".venv"),
        "capture_module_path": str(target / ".venv" / capture),
        "workspace": str(workspace),
        "python_executable_hash": installed["python/bin/python3.11"],
        "capture_module_hash": installed["python/" + capture],
        "ci_runtime_inventory_hash": runtime.content_hash,
        "ci_runtime_declaration_hash": sha256_bytes(canonical_json_bytes(declaration)),
        "manager_cache_prefix": str(target / "manager-cache"),
        "manager_dont_write_bytecode": True,
        "manager_isolated": True,
        "manager_ignore_environment": True,
        "manager_no_user_site": True,
        "manager_safe_path": True,
        "check_cache_absent": True,
        "tool_versions": {name: version(name) for name in CI_PACKAGES},
        "tracked_inventory_hash": tracked.content_hash,
        "checks": deepcopy(runs),
        "authority_before": inventory.model_dump(mode="json"),
        "authority_after": inventory.model_dump(mode="json"),
        "authority_directories": [],
        "qualification_eligibility": "NOT_QUALIFIED",
    }
    if mutation in {"profile", "commit", "lock", "runtime", "python"}:
        key = {
            "profile": "deployment_profile_hash",
            "commit": "exact_commit",
            "lock": "lockfile_hash",
            "runtime": "runtime_fingerprint_hash",
            "python": "python_executable_hash",
        }[mutation]
        fact[key] = "0" * 64
    elif mutation == "tool":
        fact["tool_versions"]["pytest"] = "0.0"
    elif mutation == "tracked":
        records["tracked-after.json"] = b"{}"
    elif mutation == "new-source":
        (workspace / "example.py").write_bytes(b"changed frozen source")
    elif mutation == "snapshot":
        fact["authority_after"] = {"files": []}
    elif mutation == "directory":
        (bundle / "cases/Q12/after/unrecorded").mkdir()
    elif mutation == "external-python":
        fact["python"] = sys.executable
    elif mutation == "external-prefix":
        fact["python_prefix"] = sys.prefix
    elif mutation == "external-module":
        fact["capture_module_path"] = str(install / "python" / capture)
    elif mutation == "runtime-prefix":
        (target / ".venv" / capture).write_bytes(b"mutated tool dependency")
    elif mutation == "runtime-node":
        (target / "node-bin/node").chmod(0o700)
        (target / "node-bin/node").write_bytes(b"\x7fELFmutated Node")
    elif mutation in {"runtime-inventory", "runtime-declaration"}:
        name = (
            "runtime-install.json"
            if mutation == "runtime-inventory"
            else "runtime-declaration.json"
        )
        records[name] = b"{}"
    elif mutation == "namespace-command":
        fact["checks"][0]["namespace_argv"].remove("--unshare-net")
    elif mutation == "kernel-missing":
        fact["checks"][0]["kernel_observations"] = []
    elif mutation == "manager-non-isolated":
        fact["manager_isolated"] = False
    elif mutation and mutation.startswith("kernel-"):
        key, value = {
            "kernel-shared-network": ("net_namespace_inode", 3000),
            "kernel-executable": ("executable_hash", "0" * 64),
            "kernel-ancestry": ("kernel_ancestry", [2000, 1]),
            "kernel-unobserved": ("kernel_observed_before_exec", False),
            "kernel-network-allowed": ("network_probe_errno", 0),
            "kernel-shared-pid": ("pid_namespace_inode", 4000),
            "kernel-unreaped-namespace": ("namespace_exit_observed", False),
        }[mutation]
        fact["checks"][0]["kernel_observations"][0][key] = value
    elif mutation == "selected-tests":
        fact["checks"][3]["argv"] += ["-k", "one-test"]
    elif mutation in {
        "exit-failed",
        "exit-bool",
        "wait-missing",
        "same-pid",
        "wrong-parent",
        "timeout",
        "output-hash",
    }:
        key, value = {
            "exit-failed": ("return_code", 1),
            "exit-bool": ("return_code", False),
            "wait-missing": ("waitpid_observed", False),
            "same-pid": ("pid", 1001),
            "wrong-parent": ("parent_pid", 888),
            "timeout": ("failure", "CHECK_TIMEOUT"),
            "output-hash": ("output_hash", "0" * 64),
        }[mutation]
        fact["checks"][0][key] = value
    elif mutation == "exit-log":
        records["ruff-exit.json"] = b"{}"
    elif mutation == "prelaunch":
        records["pytest-prelaunch.json"] = b"{}"
    elif mutation == "missing-check":
        records.pop("ruff.txt")
    records["run.json"] = canonical_json_bytes(fact)
    evidence = []
    for name, data in records.items():
        logical = f"cases/Q12/{name}"
        # Snapshot inventories remain root metadata, outside the fixed check registry.
        source = (
            f"qualification-cases/Q12/{name}"
            if name.endswith("-inventory.json")
            else f"{CI_PREFIX}/{name}"
        )
        atomic_write_bytes(manager / source, data)
        atomic_write_bytes(bundle / logical, data)
        exports[logical] = HostedManagerExportFile(
            bundle_path=logical, source_path=source, sha256=sha256_bytes(data), size_bytes=len(data)
        )
        if not name.endswith("-inventory.json"):
            evidence.append(logical)
    case = HostedQualificationCase(
        case_id="Q12", roots=tuple(roots), evidence_paths=tuple(sorted(evidence))
    )
    if mutation == "missing-source":
        exports.pop("cases/Q12/run.json")
    elif mutation == "copied-log":
        (bundle / "cases/Q12/ruff.txt").write_bytes(b"altered copied log")
    elif mutation == "original-log":
        (manager / CI_PREFIX / "ruff.txt").write_bytes(b"altered original log")
    sources = HostedVerifiedSources(deployment, exports, "0" * 64)
    if mutation is None:
        assert verify_q12(bundle, case, sources)
    else:
        with pytest.raises((HostedQualificationError, ValueError)):
            verify_q12(bundle, case, sources)
