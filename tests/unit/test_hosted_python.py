"""Exercise preinitialization against real CPython, never claim deployment qualification."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def seeded_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("native compiler unavailable; actual deployment still requires it")
    output = tmp_path_factory.mktemp("hosted-isolated-python") / "python-seeded"
    prefix = Path(sys.base_prefix)
    subprocess.run(
        [
            compiler,
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I" + str(prefix / "include/python3.11"),
            '-DQUANTOS_PYTHON_HOME="' + str(prefix) + '"',
            str(ROOT / "src/quantos/infrastructure/hosted_python.c"),
            "-L" + str(prefix / "lib"),
            "-lpython3.11",
            "-Wl,-rpath," + str(prefix / "lib"),
            "-o",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    return output


def test_preinitialization_has_effective_seed_and_import_isolation(
    tmp_path: Path, seeded_python: Path
) -> None:
    (tmp_path / "hosted_import_canary.py").write_text("raise RuntimeError('unsafe import')")
    script = (
        "import importlib.util,json,sys; print(json.dumps({"
        "'flags':{n:getattr(sys.flags,n) for n in "
        "('isolated','ignore_environment','no_user_site','safe_path','hash_randomization')},"
        "'hash':hash('quantos-fixed-seed'),'canary':"
        "importlib.util.find_spec('hosted_import_canary') is not None}))"
    )
    environment = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": str(tmp_path)}
    runs = [
        subprocess.run(
            [str(seeded_python), "-c", script],
            env=environment,
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        for _ in range(2)
    ]
    assert runs[0].stdout == runs[1].stdout
    result = json.loads(runs[0].stdout)
    assert result["flags"] == {
        "isolated": 1,
        "ignore_environment": 1,
        "no_user_site": 1,
        "safe_path": True,
        "hash_randomization": 0,
    }
    assert result["canary"] is False
    ordinary = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; print(sys.flags.hash_randomization)"],
        env=environment,
        check=True,
        capture_output=True,
    )
    assert ordinary.stdout == b"1\n"


@pytest.mark.parametrize("seed", [None, "1", "random", "00"])
def test_wrong_or_missing_exec_seed_stops_before_loading_code(
    tmp_path: Path, seeded_python: Path, seed: str | None
) -> None:
    marker = tmp_path / "executed"
    environment = dict(os.environ)
    environment.pop("PYTHONHASHSEED", None)
    if seed is not None:
        environment["PYTHONHASHSEED"] = seed
    result = subprocess.run(
        [str(seeded_python), "-c", f"open({str(marker)!r},'w').close()"],
        env=environment,
        capture_output=True,
    )
    assert result.returncode == 78
    assert result.stdout == result.stderr == b""
    assert not marker.exists()
