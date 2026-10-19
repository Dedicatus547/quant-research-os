"""Prepare a named offline environment from fixed public distributions.

This is installation plumbing, not a provider, scientific runner or qualification gate.
The base CPython prefix, system libraries, uv and official Qlib checkout remain explicit
host prerequisites. No existing site-packages or authentication directory is copied.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from quantos.artifacts.store import ArtifactIntegrityError, atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted_deployment import HostedInstallInventory
from quantos.infrastructure.hosted_deployment import install_inventory, verify_install
from quantos.infrastructure.hosted_storage import storage_checkpoint


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactIntegrityError("environment metadata is not a regular file")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ArtifactIntegrityError("environment metadata must be an object")
    return cast(dict[str, Any], value)


def load_profile(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the complete fixed artifact set before touching installation state."""
    profile = _read(path)
    lock_path, requirements = path.parent / "lock.json", path.parent / "requirements.lock"
    if (
        profile["schema_version"] != "bounded-environment-profile/v1"
        or profile["profile_id"] != "bounded-local-01621/v1"
        or sha256_file(lock_path) != profile["lock_sha256"]
        or sha256_file(requirements) != profile["requirements_sha256"]
        or sha256_file(path.parent / "host-stdlib-inventory.json")
        != profile["host"]["stdlib_inventory_sha256"]
        or sha256_file(path.parent / "resolution.json") != profile["resolution_sha256"]
    ):
        raise ArtifactIntegrityError("environment profile identities differ")
    lock = _read(lock_path)
    if lock["schema_version"] != "bounded-environment-lock/v1" or (
        lock["profile_id"] != profile["profile_id"]
    ):
        raise ArtifactIntegrityError("environment lock profile differs")
    packages = lock["packages"]
    names = [p["name"] for p in packages]
    if names != sorted(set(names)) or not set(lock["resolution"]["roots"]) <= set(names):
        raise ArtifactIntegrityError("environment dependency closure differs")
    for package in packages:
        artifact = package["artifact"]
        digest = artifact["sha256"]
        filename = artifact["filename"]
        if (
            not set(package["dependencies"]) <= set(names)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or Path(filename).name != filename
            or not artifact["url"].startswith("https://files.pythonhosted.org/packages/")
            or not artifact["url"].endswith("/" + filename)
            or artifact["kind"] not in {"wheel", "sdist"}
            or artifact["size_bytes"] <= 0
        ):
            raise ArtifactIntegrityError("environment artifact identity is invalid")
    expected = "".join(
        f"{p['name']}=={p['version']} --hash=sha256:{p['artifact']['sha256']}\n" for p in packages
    )
    versions = {p["name"]: p["version"] for p in packages}
    resolution = _read(path.parent / "resolution.json")
    if (
        resolution["resolved_versions"] != versions
        or resolution["resolver_exit"] != 0
        or lock["resolution"]["independent_resolution_sha256"] != profile["resolution_sha256"]
    ):
        raise ArtifactIntegrityError("independent environment resolution differs")
    if requirements.read_text() != expected or (
        versions.get("openai-codex"),
        versions.get("openai-codex-cli-bin"),
    ) != ("0.162.1", "0.162.1"):
        raise ArtifactIntegrityError("environment requirements differ")
    return profile, lock


def describe_environment(profile_path: Path, sources: tuple[Path, ...] = ()) -> dict[str, Any]:
    profile, lock = load_profile(profile_path)
    available: list[str] = []
    missing: list[str] = []
    for package in lock["packages"]:
        item = package["artifact"]
        paths = [p / item["filename"] for p in sources if (p / item["filename"]).is_file()]
        if paths:
            _verify_artifact(paths[0], item)
            available.append(item["filename"])
        else:
            missing.append(item["filename"])
    return {
        "profile_id": profile["profile_id"],
        "profile_sha256": sha256_file(profile_path),
        "distribution_count": len(lock["packages"]),
        "distribution_bytes": sum(p["artifact"]["size_bytes"] for p in lock["packages"]),
        "available_artifacts": available,
        "missing_artifacts": missing,
        "host": profile["host"],
        "qlib_tools": profile["qlib_tools"],
        "growth_bytes": profile["growth_bytes"],
        "qualification": "NOT_QUALIFIED",
        "model_calls": 0,
        "scientific_executions": 0,
    }


def _verify_artifact(path: Path, item: dict[str, Any]) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != item["size_bytes"]
        or sha256_file(path) != item["sha256"]
    ):
        raise ArtifactIntegrityError("fixed environment distribution differs")


def _host_environment(scratch: str | None = None) -> dict[str, str]:
    environment = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    # Preserve only the supervisor's explicit scratch location, never user credentials.
    if scratch is not None:
        environment["TMPDIR"] = scratch
    return environment


def _command(argv: list[str], root: Path, step: str) -> bytes:
    record: dict[str, Any] = {"argv": argv, "started_at": datetime.now(UTC).isoformat()}
    atomic_write_bytes(root / f"{step}-start.json", canonical_json_bytes(record))
    try:
        result = subprocess.run(
            argv,
            env=_host_environment(os.environ.get("TMPDIR")),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        record.update(actual_exit=None, launch_error="OS_ERROR")
        raise
    else:
        record["actual_exit"] = result.returncode
        if result.returncode:
            raise ArtifactIntegrityError("offline installation subprocess failed")
        return result.stdout
    finally:
        record["ended_at"] = datetime.now(UTC).isoformat()
        atomic_write_bytes(root / f"{step}-exit.json", canonical_json_bytes(record))


_PROBE = """import sys,json,site,importlib,re,contextlib,importlib.metadata as m
from pathlib import Path
source,environment,qlib,expected=json.loads(sys.argv[1])
root=Path(environment).resolve();sp=root/'lib/python3.11/site-packages'
assert Path(sys.prefix).resolve()==root and not site.ENABLE_USER_SITE
assert all('site-packages' not in p or Path(p).resolve()==sp for p in sys.path)
for name,value in expected.items():
 assert m.version(name)==value
 d=m.distribution(name)
 assert Path(d.locate_file('')).resolve()==sp
actual={re.sub(r'[-_.]+','-',d.metadata['Name']).lower() for d in m.distributions()}
assert actual==set(expected)
sys.path.insert(0,str(Path(source)/'src'))
import quantos
assert Path(quantos.__file__).resolve()==Path(source).resolve()/'src/quantos/__init__.py'
with contextlib.redirect_stdout(sys.stderr):
 for name in ['openai_codex','qlib','qlib.workflow','qlib.data.dataset','qlib.contrib.model.gbdt']:
  module=importlib.import_module(name)
  assert Path(module.__file__).resolve().is_relative_to(sp)
 from quantos.integrations.qlib import verify_official_qlib_tools
 tools=verify_official_qlib_tools(Path(qlib))
print(json.dumps({'source':source,'python':sys.executable,'prefix':sys.prefix,
 'base_prefix':sys.base_prefix,'sys_path':sys.path,'distribution_versions':expected,
 'dump_bin_sha256':tools.dump_bin_sha256,'health_check_sha256':tools.health_check_sha256}))
"""


def _probe(
    output: Path,
    profile: dict[str, Any],
    lock: dict[str, Any],
    source: Path,
    qlib_source: Path,
    *,
    record: bool = False,
) -> dict[str, Any]:
    arguments = [
        str(source),
        str(output / "venv"),
        str(qlib_source),
        {p["name"]: p["version"] for p in lock["packages"]},
    ]
    command = [str(output / "venv/bin/python"), "-I", "-B", "-c", _PROBE, json.dumps(arguments)]
    if record:
        encoded = _command(command, output, "04-isolated-imports")
    else:
        result = subprocess.run(
            command,
            env=_host_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            raise ArtifactIntegrityError("environment isolated import or version probe failed")
        encoded = result.stdout
    observed: dict[str, Any] = json.loads(encoded)
    binary = output / "venv" / profile["sdk_binary"]["path"]
    if sha256_file(binary) != profile["sdk_binary"]["sha256"]:
        raise ArtifactIntegrityError("environment SDK runtime binary differs")
    for name, key in [
        ("scripts/dump_bin.py", "dump_bin_sha256"),
        ("scripts/check_data_health.py", "health_check_sha256"),
    ]:
        if observed[key] != profile["qlib_tools"]["files"][name]:
            raise ArtifactIntegrityError("environment official Qlib tools differ")
    return observed


def _verify_base(base: Path, profile_path: Path, profile: dict[str, Any]) -> None:
    if sha256_file(base) != profile["host"]["base_python_sha256"]:
        raise ArtifactIntegrityError("environment external base interpreter differs")
    prefix = base.parent.parent
    inventory = HostedInstallInventory.model_validate_json(
        (profile_path.parent / "host-stdlib-inventory.json").read_bytes()
    )
    verify_install(prefix / "lib/python3.11", inventory)
    for relative, digest in profile["host"]["base_shared_libraries"].items():
        if sha256_file(prefix / relative) != digest:
            raise ArtifactIntegrityError("environment external base shared library differs")


def prepare_environment(
    profile_path: Path,
    output: Path,
    *,
    base_python: Path,
    uv: Path,
    source: Path,
    qlib_source: Path,
    artifact_sources: tuple[Path, ...],
    download: bool = False,
) -> dict[str, Any]:
    """Prepare once under the existing exclusive storage supervisor; retain failures."""
    output = output.absolute()
    if output.is_relative_to(Path("/tmp")) or output.is_relative_to(Path("/var/tmp")):
        raise ArtifactIntegrityError("environment evidence requires durable storage")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    start = {
        "schema_version": "bounded-environment-preparation/v1",
        "started_at": datetime.now(UTC).isoformat(),
        "profile_path": str(profile_path),
        "implementation_sha256": sha256_file(Path(__file__)),
        "model_calls": 0,
        "scientific_executions": 0,
        "qualification": "NOT_QUALIFIED",
    }
    atomic_write_bytes(output / "preparation-start.json", canonical_json_bytes(start))
    try:
        profile, lock = load_profile(profile_path)
        # Fail closed before downloads, environment creation, copying or build execution.
        storage_checkpoint(output, "deployment", profile["growth_bytes"])
        if (platform.system(), platform.machine()) != ("Linux", "x86_64") or (
            sha256_file(base_python.resolve()) != profile["host"]["base_python_sha256"]
            or sha256_file(uv.resolve()) != profile["host"]["uv_sha256"]
        ):
            raise ArtifactIntegrityError("environment host prerequisites differ")
        libc, libc_version = platform.libc_ver()
        if libc != "glibc" or tuple(map(int, libc_version.split("."))) < tuple(
            map(int, profile["host"]["minimum_glibc"].split("."))
        ):
            raise ArtifactIntegrityError("environment system C library is unsupported")
        _verify_base(base_python.resolve(), profile_path, profile)
        for relative, digest in profile["qlib_tools"]["files"].items():
            if sha256_file(qlib_source / relative) != digest:
                raise ArtifactIntegrityError("environment official Qlib source differs")
        for name in (
            "profile.json",
            "lock.json",
            "requirements.lock",
            "host-stdlib-inventory.json",
            "resolution.json",
        ):
            atomic_write_bytes(output / name, (profile_path.parent / name).read_bytes())
        wheelhouse = output / "distributions"
        wheelhouse.mkdir()
        for package in lock["packages"]:
            storage_checkpoint(output, "deployment")
            item = package["artifact"]
            target = wheelhouse / item["filename"]
            found = next(
                (
                    p / item["filename"]
                    for p in artifact_sources
                    if (p / item["filename"]).is_file()
                ),
                None,
            )
            if found is not None:
                _verify_artifact(found, item)
                shutil.copyfile(found, target)
            elif download:
                with (
                    urllib.request.urlopen(item["url"], timeout=60) as response,
                    target.open("xb") as stream,
                ):
                    remaining = item["size_bytes"]
                    while data := response.read(min(1 << 20, remaining + 1)):
                        remaining -= len(data)
                        if remaining < 0:
                            raise ArtifactIntegrityError("fixed distribution exceeds size")
                        stream.write(data)
            else:
                raise ArtifactIntegrityError("fixed environment distribution is unavailable")
            _verify_artifact(target, item)
        _command(
            [
                str(base_python),
                "-I",
                "-B",
                "-m",
                "venv",
                "--copies",
                "--without-pip",
                str(output / "venv"),
            ],
            output,
            "01-venv",
        )
        # venv's optional lib64 alias adds no dependency; inventories reject aliases.
        alias = output / "venv/lib64"
        if alias.is_symlink() and alias.readlink() == Path("lib"):
            alias.unlink()
        bootstrap = [p for p in lock["packages"] if p["name"] in {"setuptools", "wheel"}]
        atomic_write_bytes(
            output / "bootstrap.lock",
            "".join(
                f"{p['name']}=={p['version']} --hash=sha256:{p['artifact']['sha256']}\n"
                for p in bootstrap
            ).encode(),
        )
        install = [
            str(uv),
            "--no-config",
            "--cache-dir",
            str(output / "build-cache"),
            "pip",
            "install",
            "--offline",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--require-hashes",
            "--no-deps",
            "--no-build-isolation",
            "--link-mode",
            "copy",
            "--python",
            str(output / "venv/bin/python"),
        ]
        _command([*install, "-r", str(output / "bootstrap.lock")], output, "02-build-tools")
        _command([*install, "-r", str(output / "requirements.lock")], output, "03-dependencies")
        observed = _probe(
            output, profile, lock, source.absolute(), qlib_source.absolute(), record=True
        )
        inventory = install_inventory(output / "venv")
        atomic_write_bytes(output / "inventory.json", inventory.canonical_bytes())
        result = {
            **start,
            "ended_at": datetime.now(UTC).isoformat(),
            "execution": "SUCCEEDED",
            "profile_sha256": sha256_file(output / "profile.json"),
            "inventory_sha256": sha256_file(output / "inventory.json"),
            "source": str(source.absolute()),
            "qlib_source": str(qlib_source.absolute()),
            "base_python": str(base_python.resolve()),
            "uv": str(uv.resolve()),
            "observed": observed,
            "validation": "NOT_EVALUATED",
        }
        atomic_write_bytes(output / "result.json", canonical_json_bytes(result))
        return result
    except Exception as error:
        atomic_write_bytes(
            output / "failure.json",
            canonical_json_bytes(
                {
                    **start,
                    "ended_at": datetime.now(UTC).isoformat(),
                    "execution": "FAILED",
                    "error_type": type(error).__name__,
                    "validation": "NOT_EVALUATED",
                }
            ),
        )
        raise


def verify_environment(output: Path, profile_path: Path) -> dict[str, Any]:
    """Read retained installation bytes and run only isolated offline import probes."""
    profile, lock = load_profile(profile_path)
    result = _read(output / "result.json")
    if (
        result["execution"] != "SUCCEEDED"
        or sha256_file(profile_path) != result["profile_sha256"]
        or sha256_file(output / "profile.json") != result["profile_sha256"]
        or sha256_file(output / "inventory.json") != result["inventory_sha256"]
    ):
        raise ArtifactIntegrityError("environment preparation identity differs")
    verify_install(
        output / "venv",
        HostedInstallInventory.model_validate_json((output / "inventory.json").read_bytes()),
    )
    _verify_base(Path(result["base_python"]), profile_path, profile)
    observed = _probe(output, profile, lock, Path(result["source"]), Path(result["qlib_source"]))
    return {
        "profile_id": profile["profile_id"],
        "status": "OFFLINE_ENVIRONMENT_VERIFIED",
        "python": str(output / "venv/bin/python"),
        "source": result["source"],
        "distribution_versions": observed["distribution_versions"],
        "qualification": "NOT_QUALIFIED",
        "model_calls": 0,
        "scientific_executions": 0,
    }


def bind_environment(output: Path, profile_path: Path, source: Path) -> dict[str, Any]:
    """Require an explicit prepared environment for successor package preparation."""
    prefix = (output / "venv").resolve()
    if Path(sys.prefix).resolve() != prefix:
        raise ArtifactIntegrityError("package must run in its explicit prepared environment")
    package_site = prefix / "lib/python3.11/site-packages"
    if any("site-packages" in p and Path(p).resolve() != package_site for p in sys.path):
        raise ArtifactIntegrityError("package process imports differ from explicit environment")
    critical = {
        "qlib": "pyqlib",
        "openai_codex": "openai-codex",
        "codex_cli_bin": "openai-codex-cli-bin",
        "lightgbm": "lightgbm",
        "numpy": "numpy",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "pydantic": "pydantic",
    }
    for name in critical:
        module = sys.modules.get(name)
        if module is not None:
            origin = getattr(module, "__file__", None)
            if origin is None or not Path(origin).resolve().is_relative_to(package_site):
                raise ArtifactIntegrityError(
                    "package process imports differ from explicit environment"
                )
    verified = verify_environment(output, profile_path)
    if Path(verified["source"]).resolve() != source.resolve():
        raise ArtifactIntegrityError("package must run in its explicit prepared environment")
    from importlib.metadata import distribution

    for name in critical.values():
        installed = distribution(name)
        if (
            Path(str(installed.locate_file(""))).resolve() != package_site
            or installed.version != verified["distribution_versions"][name]
        ):
            raise ArtifactIntegrityError("package process imports differ from explicit environment")
    return {
        "root": str(output.absolute()),
        "profile_path": str(profile_path.absolute()),
        "profile_sha256": sha256_file(profile_path),
        "result_sha256": sha256_file(output / "result.json"),
        "inventory_sha256": sha256_file(output / "inventory.json"),
        **verified,
    }
