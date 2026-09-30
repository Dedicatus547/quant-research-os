"""Exercise preinitialization against real CPython, never claim deployment qualification."""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def seeded_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("hosted-isolated-python") / "python-seeded"
    _compile_seeded_python(output)
    return output


def _compile_seeded_python(output: Path, cache_prefix: Path | None = None) -> None:
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("native compiler unavailable; actual deployment still requires it")
    prefix = Path(sys.base_prefix)
    subprocess.run(
        [
            compiler,
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I" + str(prefix / "include/python3.11"),
            '-DQUANTOS_PYTHON_HOME="' + str(prefix) + '"',
            *(
                ['-DQUANTOS_PYCACHE_PREFIX="' + str(cache_prefix) + '"']
                if cache_prefix is not None
                else []
            ),
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


def test_native_source_import_ignores_real_timestamp_valid_stale_cache(
    tmp_path: Path, seeded_python: Path
) -> None:
    source = tmp_path / "canary.py"
    frozen = b"MARKER = 'frozen'\n"
    stale = b"MARKER = 'staled'\n"
    assert len(frozen) == len(stale)
    source.write_bytes(stale)
    timestamp = source.stat().st_mtime_ns
    py_compile.compile(
        str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
    )
    source.write_bytes(frozen)
    os.utime(source, ns=(timestamp, timestamp))
    script = (
        "import importlib.util,json,sys; "
        f"s=importlib.util.spec_from_file_location('canary',{str(source)!r}); "
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "print(json.dumps({'marker':m.MARKER,'cache_prefix':sys.pycache_prefix,"
        "'write_bytecode':not sys.dont_write_bytecode}))"
    )
    environment = {**os.environ, "PYTHONHASHSEED": "0"}
    ordinary = subprocess.run(
        [sys.executable, "-I", "-c", script], env=environment, check=True, capture_output=True
    )
    native = subprocess.run(
        [str(seeded_python), "-c", script], env=environment, check=True, capture_output=True
    )
    assert json.loads(ordinary.stdout)["marker"] == "staled"
    assert json.loads(native.stdout) == {
        "marker": "frozen",
        "cache_prefix": "/tmp/quantos-disabled-bytecode-cache",
        "write_bytecode": False,
    }
    assert not Path("/tmp/quantos-disabled-bytecode-cache").exists()


def test_polluted_cache_prefix_stops_native_before_python_initialization(tmp_path: Path) -> None:
    # A compile-time path override isolates this fault test. Formal verification
    # still requires the fixed production prefix and native inventory hash.
    prefix = tmp_path / "cache-prefix"
    binary = tmp_path / "python-seeded"
    _compile_seeded_python(binary, cache_prefix=prefix)
    environment = {**os.environ, "PYTHONHASHSEED": "0"}
    control = subprocess.run(
        [str(binary), "-c", "print('initialized')"], env=environment, capture_output=True
    )
    assert control.returncode == 0 and control.stdout == b"initialized\n"
    assert not prefix.exists()
    prefix.mkdir()
    result = subprocess.run(
        [str(binary), "-c", "print('initialized')"], env=environment, capture_output=True
    )
    assert result.returncode == 78 and result.stdout == result.stderr == b""
