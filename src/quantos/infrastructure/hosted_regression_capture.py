"""Management-only fixed offline CI capture, without model authentication."""

from __future__ import annotations

import argparse
import errno
import os
import select
import selectors
import signal
import subprocess
import sys
import time
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path

from quantos.application.provenance import capture_runtime_fingerprint, verify_code_provenance
from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    atomic_write_bytes_at,
    opened_directory,
    sha256_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_qualification import HostedQualificationFile, HostedRawInventory
from quantos.infrastructure.hosted_budget_staging_paths import (
    pinned_budget_staging_parent,
    require_staging_parent_identity,
)
from quantos.infrastructure.hosted_deployment import KnownValueGuard, verify_install
from quantos.infrastructure.hosted_manager import (
    HostedManagedDeployment,
    capture_authority_snapshot,
    read_managed_deployment,
)
from quantos.infrastructure.hosted_regression_runtime import (
    ci_environment,
    ci_namespace_command,
    ci_python,
    expected_ci_runtime,
    native_pidfd_kill,
    native_pidfd_open,
    prepare_ci_runtime_contents,
    verify_ci_declaration,
    verify_ci_runtime,
)
from quantos.infrastructure.hosted_regression_verification import (
    CHECK_NAMES,
    CI_PACKAGES,
    CI_PREFIX,
    regression_commands,
)
from quantos.infrastructure.hosted_verification import (
    directory_inventory,
    raw_inventory,
    read_relative,
    verify_raw_inventory,
)


def tracked_regression_inventory(workspace: Path) -> HostedRawInventory:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    paths = completed.stdout.decode().split("\0")
    files: list[HostedQualificationFile] = []
    for logical in sorted(path for path in paths if path):
        data = read_relative(workspace, logical)
        files.append(
            HostedQualificationFile(
                logical_path=logical, sha256=sha256_bytes(data), size_bytes=len(data)
            )
        )
    return HostedRawInventory(files=tuple(files))


def _check(
    argv: tuple[str, ...],
    *,
    workspace: Path,
    environment: dict[str, str],
    timeout: float = 7200,
    byte_cap: int = 16_777_216,
    kernel_observations: list[dict[str, object]] | None = None,
    expected_executable_hash: str | None = None,
) -> tuple[int, int, bytes, str | None]:
    """Capture bounded bytes in RAM, then actually reap the entire fixed child group."""
    process = subprocess.Popen(
        argv,
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if kernel_observations is not None else subprocess.DEVNULL,
        start_new_session=True,
    )
    output = bytearray()
    failure: str | None = None
    deadline = time.monotonic() + timeout
    bridge_bytes = bytearray()
    bridge_complete = kernel_observations is None
    namespace_fd: int | None = None
    assert process.stdout is not None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if time.monotonic() >= deadline:
                    failure = "CHECK_TIMEOUT"
                    break
                ready = selector.select(min(1.0, max(0, deadline - time.monotonic())))
                if ready:
                    data = os.read(process.stdout.fileno(), 65536)
                    if not data:
                        if not bridge_complete:
                            failure = "CHECK_BRIDGE_UNAVAILABLE"
                            output.extend(bridge_bytes[:byte_cap])
                        break
                    if not bridge_complete:
                        bridge_bytes.extend(data)
                        if b"\n" not in bridge_bytes:
                            if len(bridge_bytes) > 65536:
                                failure = "CHECK_BRIDGE_CAP"
                                break
                            continue
                        header, _, remainder = bytes(bridge_bytes).partition(b"\n")
                        try:
                            init_pid = ci_namespace_init(process.pid)
                            namespace_fd = native_pidfd_open(init_pid)
                            observation = observe_ci_kernel(
                                header, process.pid, expected_executable_hash
                            )
                        except (ArtifactIntegrityError, OSError, ValueError, KeyError, TypeError):
                            failure = "CHECK_BRIDGE_INVALID"
                            output.extend(bridge_bytes[:byte_cap])
                            break
                        assert kernel_observations is not None and process.stdin is not None
                        kernel_observations.append(observation)
                        process.stdin.write(b"G")
                        process.stdin.flush()
                        process.stdin.close()
                        bridge_complete = True
                        data = remainder
                    if len(output) + len(data) > byte_cap:
                        failure = "CHECK_OUTPUT_CAP"
                        break
                    output.extend(data)
        if failure is not None:
            if namespace_fd is None and kernel_observations is not None:
                with suppress(ArtifactIntegrityError, OSError, ValueError):
                    namespace_fd = native_pidfd_open(ci_namespace_init(process.pid))
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            if namespace_fd is not None:
                with suppress(ProcessLookupError):
                    native_pidfd_kill(namespace_fd)
        try:
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            failure = "CHECK_TIMEOUT"
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=10)
        if namespace_fd is not None:
            if not select.select([namespace_fd], [], [], 1)[0]:
                failure = failure or "CHECK_NAMESPACE_CLEANUP_REQUIRED"
                with suppress(ProcessLookupError):
                    native_pidfd_kill(namespace_fd)
            exited = bool(select.select([namespace_fd], [], [], 10)[0])
            if kernel_observations:
                kernel_observations[0]["namespace_exit_observed"] = exited
            if not exited:
                failure = "CHECK_NAMESPACE_EXIT_UNAVAILABLE"
        return process.pid, code, bytes(output), failure
    finally:
        process.stdout.close()
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        if namespace_fd is not None:
            if not select.select([namespace_fd], [], [], 0)[0]:
                with suppress(ProcessLookupError):
                    native_pidfd_kill(namespace_fd)
                select.select([namespace_fd], [], [], 10)
            os.close(namespace_fd)


def ci_wrapper_processes(wrapper_pid: int) -> tuple[int, ...]:
    """Bounded native ancestry below the fixed wrapper, before the exec barrier."""
    pending = [wrapper_pid]
    observed: list[int] = []
    while pending:
        pid = pending.pop()
        if pid in observed or len(observed) >= 32:
            raise ArtifactIntegrityError("CI wrapper descendant bounds exceeded")
        observed.append(pid)
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text()
        if len(children) > 4096:
            raise ArtifactIntegrityError("CI wrapper descendant bytes exceeded")
        pending.extend(int(value) for value in children.split())
    return tuple(observed)


def ci_namespace_init(wrapper_pid: int) -> int:
    manager_inode = Path("/proc/self/ns/pid").stat().st_ino
    candidates: list[int] = []
    for pid in ci_wrapper_processes(wrapper_pid):
        fields = Path(f"/proc/{pid}/status").read_text().splitlines()
        namespace_pids = next(line for line in fields if line.startswith("NSpid:")).split()[1:]
        if namespace_pids[-1] == "1" and Path(f"/proc/{pid}/ns/pid").stat().st_ino != manager_inode:
            candidates.append(pid)
    if len(candidates) != 1:
        raise ArtifactIntegrityError("CI original PID namespace init is unavailable")
    return candidates[0]


def observe_ci_kernel(
    header: bytes, wrapper_pid: int, expected_executable_hash: str | None
) -> dict[str, object]:
    """Read the still-blocked native bridge directly, before permitting tool exec."""
    fact = strict_json_object(header, max_bytes=65536)
    namespace_pid = fact.get("namespace_pid")
    if type(namespace_pid) is not int or namespace_pid <= 1:
        raise ArtifactIntegrityError("CI bridge PID is invalid")
    candidates: list[int] = []
    for candidate in ci_wrapper_processes(wrapper_pid):
        fields = Path(f"/proc/{candidate}/status").read_text().splitlines()
        pids = next(line for line in fields if line.startswith("NSpid:")).split()[1:]
        if int(pids[-1]) == namespace_pid and Path(
            f"/proc/{candidate}/ns/pid"
        ).stat().st_ino == fact.get("pid_namespace_inode"):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise ArtifactIntegrityError("CI bridge original kernel PID is unavailable")
    pid = candidates[0]
    init_pid = ci_namespace_init(wrapper_pid)
    net_inode = Path(f"/proc/{pid}/ns/net").stat().st_ino
    parent_inode = Path("/proc/self/ns/net").stat().st_ino
    manager_pid_inode = Path("/proc/self/ns/pid").stat().st_ino
    executable = Path(f"/proc/{pid}/exe").resolve(strict=True)
    executable_hash = sha256_file(executable)
    chain = [pid]
    for _ in range(8):
        if chain[-1] == os.getpid():
            break
        fields = Path(f"/proc/{chain[-1]}/status").read_text().splitlines()
        parent = int(next(line for line in fields if line.startswith("PPid:")).split()[1])
        if parent <= 0 or parent in chain:
            raise ArtifactIntegrityError("CI bridge kernel ancestry is invalid")
        chain.append(parent)
    if (
        chain[-1] != os.getpid()
        or wrapper_pid not in chain
        or init_pid not in chain[1:-1]
        or fact.get("namespace_parent_pid") != 1
        or fact.get("pid_namespace_inode") == manager_pid_inode
        or fact.get("net_namespace_inode") != net_inode
        or net_inode == parent_inode
        or fact.get("executable_hash") != executable_hash
        or executable_hash != expected_executable_hash
        or fact.get("network_probe_errno") not in {errno.ENETUNREACH, errno.EPERM, errno.EACCES}
    ):
        raise ArtifactIntegrityError("CI bridge kernel isolation or executable differs")
    return {
        **fact,
        "pid": pid,
        "parent_pid": chain[1],
        "namespace_init_pid": init_pid,
        "manager_pid_namespace_inode": manager_pid_inode,
        "wrapper_pid": wrapper_pid,
        "manager_pid": os.getpid(),
        "manager_net_namespace_inode": parent_inode,
        "kernel_ancestry": chain,
        "kernel_observed_before_exec": True,
    }


def run_managed_regression(deployment: HostedManagedDeployment, workspace: Path) -> None:
    """No RPC route or caller-supplied command; every retained attempt has a fresh root."""
    workspace = workspace.absolute()
    target = deployment.root / CI_PREFIX
    installed = {item.relative_path: item.bytes_hash for item in deployment.install.files}
    capture_source = (
        "python/lib/python3.11/site-packages/quantos/infrastructure/hosted_regression_capture.py"
    )
    capture_hash = sha256_file(Path(__file__))
    if (
        installed.get(capture_source) != capture_hash
        or sha256_file(Path(sys.executable).resolve(strict=True))
        != installed.get("python/bin/python3.11")
        or not sys.dont_write_bytecode
        or sys.pycache_prefix != str(target / "manager-cache")
        or (target / "manager-cache").exists()
        or (target / "manager-cache").is_symlink()
        or Path(sys.executable).absolute() != ci_python(deployment.root)
        or Path(sys.prefix) != target / ".venv"
        or Path(__file__)
        != target
        / ".venv/lib/python3.11/site-packages/quantos/infrastructure/hosted_regression_capture.py"
        or not sys.flags.isolated
        or not sys.flags.ignore_environment
        or not sys.flags.no_user_site
        or not sys.flags.safe_path
    ):
        raise ArtifactIntegrityError(
            "CI manager requires frozen source and an empty source-only cache prefix"
        )
    verify_code_provenance(
        workspace,
        expected_commit_hash=deployment.profile.exact_commit,
        expected_lockfile_hash=deployment.profile.lock_hash,
    )
    tracked = tracked_regression_inventory(workspace)
    if tracked != tracked_regression_inventory(deployment.paths.provenance):
        raise ArtifactIntegrityError("CI source differs from frozen deployment provenance")
    verify_ci_runtime(deployment.root, deployment.install)
    declaration = verify_ci_declaration(deployment.root, deployment.install)
    if (target / "run.json").exists() or (target / "tracked-before.json").exists():
        raise ArtifactIntegrityError("CI capture requires a fresh prepared runtime")
    authority = raw_inventory(deployment.paths.authority)
    directories = directory_inventory(deployment.paths.authority)
    capture_authority_snapshot(deployment, "qualification-cases/Q12/before")
    for logical in directories:
        with opened_directory(
            deployment.root / "qualification-cases/Q12/before" / logical, create=True
        ):
            pass
    python = Path(sys.executable).absolute()
    environment = ci_environment(python, workspace, target)
    fingerprint = capture_runtime_fingerprint()
    atomic_write_bytes(target / "runtime-fingerprint.json", fingerprint.canonical_bytes())
    atomic_write_bytes(target / "tracked-before.json", tracked.canonical_bytes())
    commands = regression_commands(python, workspace, target)
    guard = KnownValueGuard((deployment.capability,))
    observations: list[dict[str, object]] = []
    for name in CHECK_NAMES:
        actual_argv = ci_namespace_command(python, workspace, target, environment, commands[name])
        prelaunch = canonical_json_bytes(
            {
                "schema_version": "hosted-manager-regression-prelaunch/v1",
                "deployment_profile_hash": deployment.profile.content_hash,
                "manager_pid": os.getpid(),
                "name": name,
                "argv": commands[name],
                "namespace_argv": actual_argv,
                "cwd": str(workspace),
                "environment_policy": "FIXED_OFFLINE_CI_NO_CREDENTIALS/v1",
            }
        )
        guard(prelaunch)
        atomic_write_bytes(target / f"{name}-prelaunch.json", prelaunch)
        kernel: list[dict[str, object]] = []
        pid, code, output, failure = _check(
            actual_argv,
            workspace=workspace,
            environment={"PATH": "/usr/bin:/bin"},
            timeout=14400 if name == "pytest" else 7200,
            kernel_observations=kernel,
            expected_executable_hash=installed["python/bin/python3.11"],
        )
        for offset in range(0, len(output), 1_048_576 - 6 * len(deployment.capability)):
            guard(output[offset : offset + 1_048_576])
        atomic_write_bytes(target / f"{name}.txt", output)
        observed: dict[str, object] = {
            "name": name,
            "argv": commands[name],
            "namespace_argv": actual_argv,
            "kernel_observations": kernel,
            "pid": pid,
            "parent_pid": os.getpid(),
            "return_code": code,
            "waitpid_observed": True,
            "output_hash": sha256_bytes(output),
            "failure": failure,
        }
        observations.append(observed)
        atomic_write_bytes(target / f"{name}-exit.json", canonical_json_bytes(observed))
    after_tracked = tracked_regression_inventory(workspace)
    verify_ci_runtime(deployment.root, deployment.install)
    if verify_ci_declaration(deployment.root, deployment.install) != declaration:
        raise ArtifactIntegrityError("CI tool declaration changed; original outputs retained")
    atomic_write_bytes(target / "tracked-after.json", after_tracked.canonical_bytes())
    verify_code_provenance(
        workspace,
        expected_commit_hash=deployment.profile.exact_commit,
        expected_lockfile_hash=deployment.profile.lock_hash,
    )
    verify_raw_inventory(deployment.paths.authority, authority)
    if after_tracked != tracked or directory_inventory(deployment.paths.authority) != directories:
        raise ArtifactIntegrityError("CI source or authority changed; original outputs retained")
    capture_authority_snapshot(deployment, "qualification-cases/Q12/after")
    for logical in directories:
        with opened_directory(
            deployment.root / "qualification-cases/Q12/after" / logical, create=True
        ):
            pass
    record = canonical_json_bytes(
        {
            "schema_version": "hosted-manager-regression/v1",
            "deployment_profile_hash": deployment.profile.content_hash,
            "exact_commit": deployment.profile.exact_commit,
            "lockfile_hash": deployment.profile.lock_hash,
            "runtime_fingerprint_hash": fingerprint.content_hash,
            "manager_pid": os.getpid(),
            "python": str(python),
            "python_prefix": sys.prefix,
            "capture_module_path": __file__,
            "python_executable_hash": sha256_file(python.resolve(strict=True)),
            "capture_module_hash": capture_hash,
            "ci_runtime_inventory_hash": expected_ci_runtime(deployment.install).content_hash,
            "ci_runtime_declaration_hash": sha256_bytes(canonical_json_bytes(declaration)),
            "manager_cache_prefix": sys.pycache_prefix,
            "manager_dont_write_bytecode": sys.dont_write_bytecode,
            "manager_isolated": bool(sys.flags.isolated),
            "manager_ignore_environment": bool(sys.flags.ignore_environment),
            "manager_no_user_site": bool(sys.flags.no_user_site),
            "manager_safe_path": sys.flags.safe_path,
            "check_cache_absent": not (target / "check-cache").exists()
            and not (target / "check-cache").is_symlink(),
            "tool_versions": {name: version(name) for name in CI_PACKAGES},
            "workspace": str(workspace),
            "tracked_inventory_hash": tracked.content_hash,
            "checks": observations,
            "authority_before": authority.model_dump(mode="json"),
            "authority_after": raw_inventory(deployment.paths.authority).model_dump(mode="json"),
            "authority_directories": list(directories),
            "qualification_eligibility": "NOT_QUALIFIED",
        }
    )
    guard(record)
    atomic_write_bytes(target / "run.json", record)
    if any(item["return_code"] != 0 or item["failure"] is not None for item in observations):
        raise ArtifactIntegrityError("offline CI failed; original check outputs retained")


def prepare_managed_regression(
    deployment: HostedManagedDeployment, workspace: Path, *, node_source: Path
) -> tuple[str, ...]:
    """Pin a new tool prefix before publishing the fixed source-only manager launch."""
    verify_code_provenance(
        workspace,
        expected_commit_hash=deployment.profile.exact_commit,
        expected_lockfile_hash=deployment.profile.lock_hash,
    )
    verify_install(deployment.paths.install, deployment.install)
    target = deployment.root / CI_PREFIX
    if target.exists() or target.is_symlink():
        raise ArtifactIntegrityError("CI preparation requires a new retained root")
    expected = expected_ci_runtime(deployment.install)
    node_source = node_source.absolute()
    with pinned_budget_staging_parent(deployment, family="Q12") as (parent_fd, evidence_fd):
        reader, writer = os.pipe2(os.O_CLOEXEC)
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            try:
                os.mkdir("Q12", mode=0o700, dir_fd=parent_fd)
                case_fd = os.open(
                    "Q12", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                os.fchdir(case_fd)
                declaration = prepare_ci_runtime_contents(
                    deployment.paths.install, expected, node_source
                )
                info = os.fstat(case_fd)
                os.write(
                    writer,
                    canonical_json_bytes(
                        {
                            "root_identity": [info.st_dev, info.st_ino],
                            "declaration_hash": sha256_bytes(canonical_json_bytes(declaration)),
                        }
                    ),
                )
                os._exit(0)
            except Exception as error:
                os.write(writer, canonical_json_bytes({"error_type": type(error).__name__}))
                os._exit(1)
        os.close(writer)
        reaped = False
        try:
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
            code = os.waitstatus_to_exitcode(status)
            result_bytes = os.read(reader, 4097)
            result = strict_json_object(result_bytes, max_bytes=4096) if result_bytes else {}
            if code != 0:
                failure = canonical_json_bytes(
                    {
                        "schema_version": "hosted-management-ci-prepare-failure/v1",
                        "deployment_profile_hash": deployment.profile.content_hash,
                        "pid": observed,
                        "exit_code": code,
                        "error_type": result.get("error_type"),
                        "qualification_eligibility": "NOT_QUALIFIED",
                    }
                )
                atomic_write_bytes_at(
                    evidence_fd, f"ci-prepare-failure-{sha256_bytes(failure)}.json", failure
                )
                raise ArtifactIntegrityError("CI preparation failed; original root retained")
            require_staging_parent_identity(deployment, parent_fd, family="Q12")
            with opened_directory(target) as target_fd:
                info = os.fstat(target_fd)
                if result.get("root_identity") != [info.st_dev, info.st_ino]:
                    raise ArtifactIntegrityError("CI preparation original root changed")
            declaration = read_relative(target, "runtime-declaration.json")
            if sha256_bytes(declaration) != result.get("declaration_hash"):
                raise ArtifactIntegrityError("CI preparation original declaration changed")
            verify_ci_runtime(deployment.root, deployment.install)
            verify_ci_declaration(deployment.root, deployment.install)
        finally:
            os.close(reader)
            if not reaped:
                with suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
    return (
        str(ci_python(deployment.root)),
        "-I",
        "-B",
        "-X",
        f"pycache_prefix={target / 'manager-cache'}",
        "-m",
        "quantos.infrastructure.hosted_regression_capture",
        "--manager-root",
        str(deployment.root),
        "--profile-hash",
        deployment.profile.content_hash,
        "--workspace",
        str(workspace.absolute()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-root", type=Path, required=True)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    deployment = read_managed_deployment(arguments.manager_root, arguments.profile_hash)
    run_managed_regression(deployment, arguments.workspace)


if __name__ == "__main__":
    main()
