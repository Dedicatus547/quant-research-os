"""Management-only child deployments for the seven finite Q06 budget recipes."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes_at,
    opened_directory,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.infrastructure.hosted_budget_cases import (
    HOSTED_BUDGET_CASES,
    derive_hosted_budget_case,
)
from quantos.infrastructure.hosted_budget_staging_paths import (
    pinned_budget_staging_parent,
    require_staging_parent_identity,
)
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_manager import (
    HostedManagedDeployment,
    read_managed_deployment,
    stage_hosted_deployment,
)
from quantos.infrastructure.hosted_storage import storage_checkpoint
from quantos.infrastructure.hosted_verification import read_relative


def budget_deployment_declaration(
    parent: HostedManagedDeployment, child: HostedManagedDeployment, case: str
) -> dict[str, str]:
    return {
        "schema_version": "hosted-budget-deployment/v1",
        "case": case,
        "parent_profile_hash": parent.profile.content_hash,
        "parent_business_inputs_hash": parent.bundle.content_hash,
        "child_profile_hash": child.profile.content_hash,
        "child_business_inputs_hash": child.bundle.content_hash,
        "exact_commit": parent.profile.exact_commit,
    }


def verify_budget_deployment_variant(
    parent: HostedManagedDeployment, child: HostedManagedDeployment, case: str
) -> None:
    """Derive B again from the trusted parent; labels cannot establish a variant."""
    if case not in HOSTED_BUDGET_CASES:
        raise ArtifactIntegrityError("unknown fixed budget deployment")
    expected = derive_hosted_budget_case(
        parent.bundle, case, input_root=parent.paths.offline_inputs
    )
    if child.bundle.canonical_bytes() != expected.canonical_bytes():
        raise ArtifactIntegrityError("budget child differs from finite parent derivation")
    fields = (
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
    if any(getattr(parent.profile, field) != getattr(child.profile, field) for field in fields):
        raise ArtifactIntegrityError("budget child installation or runtime differs from parent")
    if child.launcher_configuration != parent.launcher_configuration:
        raise ArtifactIntegrityError("budget child model configuration differs")


def stage_managed_budget_deployment(
    parent: HostedManagedDeployment,
    case: str,
    workspace: Path,
    *,
    base_python: Path,
    dependency_site: Path,
) -> HostedManagedDeployment:
    """Freeze new B→L→C→I0→D before running the native fixture, without a model call."""
    storage_checkpoint(parent.root, "matrix")
    if case not in HOSTED_BUDGET_CASES:
        raise ValueError("unknown fixed budget deployment")
    target = parent.root / "qualification-deployments/Q06" / case
    declaration = parent.root / "evidence" / f"budget-deployment-{case}.json"
    if target.exists() or target.is_symlink() or declaration.exists() or declaration.is_symlink():
        raise ArtifactIntegrityError("budget deployment requires fresh retained roots")
    workspace, base_python, dependency_site = (
        path.absolute() for path in (workspace, base_python, dependency_site)
    )
    # A separate management process owns its pinned cwd. Third-party copy/git/
    # compiler operations use relative paths beneath that inode; the main process
    # cwd and authority are never changed or reached through an ancestor alias.
    with pinned_budget_staging_parent(parent) as (staging_fd, evidence_fd):
        bounded = derive_hosted_budget_case(
            parent.bundle, case, input_root=parent.paths.offline_inputs
        )
        objects = {
            item.logical_path: read_relative(parent.paths.offline_inputs, item.logical_path)
            for item in parent.bundle.frozen_byte_objects
        }
        reader, writer = os.pipe2(os.O_CLOEXEC)
        pid: int | None = None
        reaped = False
        try:
            pid = os.fork()
            if pid == 0:
                os.close(reader)
                try:
                    os.mkdir(case, mode=0o700, dir_fd=staging_fd)
                    case_fd = os.open(
                        case, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=staging_fd
                    )
                    os.fchdir(case_fd)
                    child = stage_hosted_deployment(
                        Path("."),
                        workspace,
                        bounded,
                        objects,
                        parent.paths.offline_inputs / parent.bundle.initial_ledger_directory,
                        wheel=parent.paths.configuration
                        / f"sha256-{parent.profile.wheel_hash}.whl",
                        base_python=base_python,
                        dependency_site=dependency_site,
                        codex_binary=parent.paths.install / "codex",
                        launcher_configuration=parent.launcher_configuration,
                        prepared_root_fd=case_fd,
                    )
                    verify_budget_deployment_variant(parent, child, case)
                    info = os.fstat(case_fd)
                    os.close(case_fd)
                    os.write(
                        writer,
                        canonical_json_bytes(
                            {
                                "profile_hash": child.profile.content_hash,
                                "root_identity": [info.st_dev, info.st_ino],
                            }
                        ),
                    )
                    os._exit(0)
                except Exception as error:
                    os.write(writer, canonical_json_bytes({"error_type": type(error).__name__}))
                    os._exit(1)
            os.close(writer)
            writer = -1
            deadline = time.monotonic() + 300
            while True:
                observed, status = os.waitpid(pid, os.WNOHANG)
                if observed:
                    reaped = True
                    break
                if time.monotonic() >= deadline:
                    os.kill(pid, signal.SIGKILL)
                    observed, status = os.waitpid(pid, 0)
                    reaped = True
                    break
                time.sleep(0.02)
            encoded_result = os.read(reader, 4097)
            code = os.waitstatus_to_exitcode(status)
            result = strict_json_object(encoded_result, max_bytes=4096) if encoded_result else {}
            if code != 0:
                failure = canonical_json_bytes(
                    {
                        "schema_version": "hosted-budget-stage-failure/v1",
                        "case": case,
                        "parent_profile_hash": parent.profile.content_hash,
                        "pid": observed,
                        "exit_code": code,
                        "error_type": result.get("error_type"),
                        "qualification_eligibility": "NOT_QUALIFIED",
                    }
                )
                atomic_write_bytes_at(
                    evidence_fd, f"budget-stage-failure-{sha256_bytes(failure)}.json", failure
                )
                raise ArtifactIntegrityError("budget child staging failed; retained original root")
            digest = result.get("profile_hash")
            if not isinstance(digest, str):
                raise ArtifactIntegrityError("budget child staging profile unavailable")
            require_staging_parent_identity(parent, staging_fd)
            with opened_directory(target) as child_fd:
                info = os.fstat(child_fd)
                if result.get("root_identity") != [info.st_dev, info.st_ino]:
                    raise ArtifactIntegrityError("budget child original staging inode changed")
            child = read_managed_deployment(target, digest)
            verify_budget_deployment_variant(parent, child, case)
            _verify_child_inventory(child)
            encoded = canonical_json_bytes(budget_deployment_declaration(parent, child, case))
            atomic_write_bytes_at(evidence_fd, declaration.name, encoded)
            atomic_write_bytes_at(evidence_fd, sha256_bytes(encoded), encoded)
            return child
        finally:
            if pid is not None and pid > 0 and not reaped:
                try:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass
            os.close(reader)
            if writer >= 0:
                os.close(writer)


def _verify_child_inventory(child: HostedManagedDeployment) -> None:
    if (
        install_inventory(child.paths.install) != child.install
        or install_inventory(child.paths.provenance).content_hash
        != child.profile.provenance_inventory_hash
        or install_inventory(child.paths.projection) != child.initial_projection
    ):
        raise ArtifactIntegrityError("budget original installation or projection changed")


def read_managed_budget_deployment(
    parent: HostedManagedDeployment, case: str, profile_hash: str
) -> HostedManagedDeployment:
    """The trusted parent fixes both the source path and the separately frozen D."""
    if case not in HOSTED_BUDGET_CASES:
        raise ArtifactIntegrityError("unknown fixed budget deployment")
    child = read_managed_deployment(
        parent.root / "qualification-deployments/Q06" / case, profile_hash
    )
    verify_budget_deployment_variant(parent, child, case)
    _verify_child_inventory(child)
    encoded = canonical_json_bytes(budget_deployment_declaration(parent, child, case))
    if (
        read_relative(parent.root, f"evidence/budget-deployment-{case}.json") != encoded
        or read_relative(parent.root, f"evidence/{sha256_bytes(encoded)}") != encoded
    ):
        raise ArtifactIntegrityError("budget deployment declaration differs from original manager")
    return child
