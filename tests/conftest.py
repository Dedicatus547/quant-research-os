"""Run offline management probes in clean interpreters, as deployment does."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if pyfuncitem.get_closest_marker("fresh_offline_process") is None:
        return None
    if os.environ.get("QUANTOS_TEST_OFFLINE_NODE") == pyfuncitem.nodeid:
        return None
    # Collection of unrelated tests imports the agent SDK. Forking that session
    # cannot establish a clean offline runtime. Execute this exact test in a new
    # interpreter; retain the native probe's SDK/module and network guards.
    environment = os.environ.copy()
    environment["QUANTOS_TEST_OFFLINE_NODE"] = pyfuncitem.nodeid
    temporary = pyfuncitem.funcargs["tmp_path"]
    assert isinstance(temporary, Path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            pyfuncitem.nodeid,
            "-q",
            "--basetemp",
            str(temporary / "fresh-interpreter"),
        ],
        cwd=pyfuncitem.config.rootpath,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=1800,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout.decode("utf-8", errors="replace")
    return True
