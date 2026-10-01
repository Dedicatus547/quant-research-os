"""Actual bounded CLI capture and native wait/reap controls, without model calls."""

import os
import select
import sys
import threading
import time
from pathlib import Path

import pytest

from quantos.artifacts.store import sha256_file
from quantos.infrastructure.hosted_regression_capture import _check
from quantos.infrastructure.hosted_regression_runtime import ci_namespace_command, native_pidfd_open


def test_native_command_output_and_exit_are_captured_and_reaped(tmp_path: Path) -> None:
    pid, code, output, failure = _check(
        (sys.executable, "-c", "print('offline-check'); raise SystemExit(7)"),
        workspace=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
    )
    assert code == 7 and output == b"offline-check\n" and failure is None
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


@pytest.mark.parametrize("kind", ("timeout", "output"))
def test_timeout_or_large_output_retains_bounded_bytes_and_actual_exit(
    tmp_path: Path, kind: str
) -> None:
    command = "import time; time.sleep(60)" if kind == "timeout" else "print('x' * 8192)"
    pid, code, output, failure = _check(
        (sys.executable, "-c", command),
        workspace=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
        timeout=0.2,
        byte_cap=1024,
    )
    assert failure == ("CHECK_TIMEOUT" if kind == "timeout" else "CHECK_OUTPUT_CAP")
    assert code in (-9, 0) and len(output) <= 1024
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def test_closed_output_does_not_end_the_execution_deadline(tmp_path: Path) -> None:
    started = time.monotonic()
    pid, code, output, failure = _check(
        (
            sys.executable,
            "-c",
            "import os,time; print('original',flush=True); "
            "os.close(1); os.close(2); time.sleep(60)",
        ),
        workspace=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
        timeout=0.2,
    )
    assert failure == "CHECK_TIMEOUT" and code == -9 and output == b"original\n"
    assert time.monotonic() - started < 5
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


@pytest.mark.parametrize("identity", ("frozen", "wrong-hash"))
def test_kernel_bridge_checks_native_network_and_executable_before_exec(
    tmp_path: Path, identity: str
) -> None:
    target = tmp_path / "ci"
    (target / ".venv").mkdir(parents=True)
    (target / "node-bin").mkdir()
    python = Path(sys.executable).absolute()
    environment = {"PATH": "/usr/bin:/bin"}
    command = (str(python), "-I", "-B", "-c", "print('native-offline-check')")
    kernel: list[dict[str, object]] = []
    pid, code, output, failure = _check(
        ci_namespace_command(python, tmp_path, target, environment, command),
        workspace=tmp_path,
        environment=environment,
        timeout=10,
        kernel_observations=kernel,
        expected_executable_hash=sha256_file(python.resolve())
        if identity == "frozen"
        else "0" * 64,
    )
    if identity == "frozen":
        assert code == 0 and failure is None and output == b"native-offline-check\n"
        assert len(kernel) == 1
        assert kernel[0]["kernel_observed_before_exec"] is True
        assert kernel[0]["net_namespace_inode"] != kernel[0]["manager_net_namespace_inode"]
        assert kernel[0]["wrapper_pid"] == pid
    else:
        assert code == -9 and failure == "CHECK_BRIDGE_INVALID" and not kernel
        assert b"native-offline-check" not in output
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def test_invalid_bridge_output_keeps_original_bounded_bytes_and_reaps(tmp_path: Path) -> None:
    pid, code, output, failure = _check(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import time; print('x'*8192,flush=True); time.sleep(60)",
        ),
        workspace=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
        timeout=2,
        byte_cap=1024,
        kernel_observations=[],
        expected_executable_hash="0" * 64,
    )
    assert code == -9 and failure == "CHECK_BRIDGE_INVALID" and len(output) == 1024
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


@pytest.mark.parametrize("completion", ("timeout", "eof-timeout", "success"))
def test_pid_namespace_exit_stops_real_detached_descendants(
    tmp_path: Path, completion: str
) -> None:
    target = tmp_path / "ci"
    (target / ".venv").mkdir(parents=True)
    (target / "node-bin").mkdir()
    python = Path(sys.executable).absolute()
    child = "import os,time; os.close(1); os.close(2); time.sleep(60)"
    program = (
        "import os,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-I','-B','-c',{child!r}],start_new_session=True); "
        "print('spawned',flush=True); "
    )
    if completion == "eof-timeout":
        program += "os.close(1); os.close(2); time.sleep(60)"
    else:
        program += "time.sleep(0.5)" if completion == "success" else "time.sleep(60)"
    kernel: list[dict[str, object]] = []
    descendants: list[tuple[int, int]] = []
    stop = threading.Event()

    def observe_descendant() -> None:
        while not stop.wait(0.005):
            if not kernel:
                continue
            tool = kernel[0]["pid"]
            try:
                children = Path(f"/proc/{tool}/task/{tool}/children").read_text().split()
                if children:
                    pid = int(children[0])
                    descriptor = native_pidfd_open(pid)
                    inode = Path(f"/proc/{pid}/ns/pid").stat().st_ino
                    if inode == kernel[0]["pid_namespace_inode"]:
                        descendants.append((pid, descriptor))
                        return
                    os.close(descriptor)
            except (OSError, ValueError):
                continue

    watcher = threading.Thread(target=observe_descendant)
    watcher.start()
    try:
        pid, code, output, failure = _check(
            ci_namespace_command(
                python,
                tmp_path,
                target,
                {"PATH": "/usr/bin:/bin"},
                (str(python), "-I", "-B", "-c", program),
            ),
            workspace=tmp_path,
            environment={"PATH": "/usr/bin:/bin"},
            timeout=3,
            kernel_observations=kernel,
            expected_executable_hash=sha256_file(python.resolve()),
        )
        assert output == b"spawned\n"
        assert (code, failure) == ((0, None) if completion == "success" else (-9, "CHECK_TIMEOUT"))
        assert len(descendants) == 1 and len(kernel) == 1
        assert kernel[0]["namespace_exit_observed"] is True
        assert kernel[0]["pid_namespace_inode"] != kernel[0]["manager_pid_namespace_inode"]
        # The actual parent opened this pidfd while the detached child was alive.
        assert select.select([descendants[0][1]], [], [], 0)[0]
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
    finally:
        stop.set()
        watcher.join(timeout=5)
        for _, descriptor in descendants:
            os.close(descriptor)
