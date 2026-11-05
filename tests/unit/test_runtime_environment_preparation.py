"""Offline environment assembly controls with inert distributions and no installers."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.infrastructure import runtime_environment as env


@pytest.fixture
def installation(monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    scratch = repo / ".pytest_cache"
    scratch.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="environment-controls-", dir=scratch) as folder:
        root = Path(folder)
        profile_root, source, distributions = root / "profile", root / "source", root / "wheels"
        for path in (profile_root, source, distributions):
            path.mkdir()
        base, uv = root / "python", root / "uv"
        base.write_bytes(b"inert base executable")
        uv.write_bytes(b"inert installer")
        (source / "dump.py").write_text("# synthetic tools identity\n")
        packages = []
        for name in ("openai-codex", "openai-codex-cli-bin", "setuptools", "wheel"):
            filename = name + ".whl"
            raw = ("inert distribution " + name).encode()
            (distributions / filename).write_bytes(raw)
            packages.append(
                {
                    "name": name,
                    "version": "0.162.1",
                    "dependencies": [],
                    "artifact": {
                        "filename": filename,
                        "size_bytes": len(raw),
                        "sha256": sha256_bytes(raw),
                        "kind": "wheel",
                        "url": "https://files.pythonhosted.org/packages/synthetic/" + filename,
                    },
                }
            )
        versions = {p["name"]: p["version"] for p in packages}
        resolution = profile_root / "resolution.json"
        resolution.write_bytes(
            canonical_json_bytes({"resolved_versions": versions, "resolver_exit": 0})
        )
        stdlib = profile_root / "host-stdlib-inventory.json"
        stdlib.write_text("{}")
        lock = {
            "schema_version": "bounded-environment-lock/v1",
            "profile_id": "bounded-local-01621/v1",
            "packages": packages,
            "resolution": {
                "roots": ["openai-codex"],
                "independent_resolution_sha256": sha256_file(resolution),
            },
        }
        (profile_root / "lock.json").write_bytes(canonical_json_bytes(lock))
        (profile_root / "requirements.lock").write_text(
            "".join(
                f"{p['name']}=={p['version']} --hash=sha256:{p['artifact']['sha256']}\n"
                for p in packages
            )
        )
        profile = {
            "schema_version": "bounded-environment-profile/v1",
            "profile_id": lock["profile_id"],
            "lock_sha256": sha256_file(profile_root / "lock.json"),
            "requirements_sha256": sha256_file(profile_root / "requirements.lock"),
            "resolution_sha256": sha256_file(resolution),
            "growth_bytes": 4096,
            "host": {
                "base_python_sha256": sha256_file(base),
                "uv_sha256": sha256_file(uv),
                "minimum_glibc": "2.35",
                "stdlib_inventory_sha256": sha256_file(stdlib),
            },
            "qlib_tools": {"files": {"dump.py": sha256_file(source / "dump.py")}},
        }
        path = profile_root / "profile.json"
        path.write_bytes(canonical_json_bytes(profile))
        state = SimpleNamespace(
            commands=[], checkpoints=[], probes=[], downloads=[], response_extra=False, denied=False
        )

        def checkpoint(*args):
            state.checkpoints.append(args)
            if state.denied:
                raise PermissionError("synthetic capacity denial")

        def command(argv, output, step):
            state.commands.append((argv, step))
            if step == "01-venv":
                binary = output / "venv/bin/python"
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b"inert fixture interpreter")
                (output / "venv/lib").mkdir()
                (output / "venv/lib64").symlink_to("lib")
            return b""

        def probe(*args, **kwargs):
            state.probes.append((args, kwargs))
            return {"distribution_versions": versions}

        def download(url, **kwargs):
            state.downloads.append((url, kwargs))
            raw = (distributions / url.rsplit("/", 1)[-1]).read_bytes()
            return io.BytesIO(raw + (b"oversized" if state.response_extra else b""))

        monkeypatch.setattr(env, "storage_checkpoint", checkpoint)
        monkeypatch.setattr(env, "_verify_base", lambda *args: None)
        monkeypatch.setattr(env, "_command", command)
        monkeypatch.setattr(env, "_probe", probe)
        monkeypatch.setattr(env.platform, "system", lambda: "Linux")
        monkeypatch.setattr(env.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(env.platform, "libc_ver", lambda: ("glibc", "2.35"))
        monkeypatch.setattr(env.urllib.request, "urlopen", download)

        def prepare(*, network=False):
            return env.prepare_environment(
                path,
                root / "output",
                base_python=base,
                uv=uv,
                source=source,
                qlib_source=source,
                artifact_sources=() if network else (distributions,),
                download=network,
            )

        yield SimpleNamespace(
            root=root,
            profile=path,
            source=source,
            distributions=distributions,
            base=base,
            state=state,
            prepare=prepare,
        )


@pytest.mark.parametrize("network", [False, True])
def test_assembly_retains_hashes_and_only_requests_offline_hash_checked_installation(
    installation, network
):
    fixture, state = installation, installation.state
    description = env.describe_environment(fixture.profile, (fixture.distributions,))
    assert len(description["available_artifacts"]) == 4 and description["missing_artifacts"] == []
    result = fixture.prepare(network=network)
    assert result["execution"] == "SUCCEEDED" and result["qualification"] == "NOT_QUALIFIED"
    assert result["model_calls"] == result["scientific_executions"] == 0
    assert len(state.downloads) == (4 if network else 0)
    assert [step for _, step in state.commands] == ["01-venv", "02-build-tools", "03-dependencies"]
    for argv, _ in state.commands[1:]:
        assert {
            "--offline",
            "--no-index",
            "--require-hashes",
            "--no-deps",
            "--no-build-isolation",
        } <= set(argv)
        assert argv[argv.index("--link-mode") + 1] == "copy"
    output = fixture.root / "output"
    assert not (output / "venv/lib64").is_symlink()
    verified = env.verify_environment(output, fixture.profile)
    assert verified["status"] == "OFFLINE_ENVIRONMENT_VERIFIED"
    assert verified["qualification"] == "NOT_QUALIFIED"
    (output / "venv/bin/python").write_bytes(b"changed installation")
    with pytest.raises(ArtifactIntegrityError, match="inventory changed"):
        env.verify_environment(output, fixture.profile)


@pytest.mark.parametrize(
    "failure,match",
    [
        ("capacity", "capacity denial"),
        ("host", "prerequisites"),
        ("tools", "Qlib source"),
        ("missing", "unavailable"),
        ("artifact", "distribution differs"),
        ("oversize", "exceeds size"),
    ],
)
def test_failed_preparation_preserves_failure_and_never_runs_installers(
    installation, failure, match
):
    fixture, state = installation, installation.state
    if failure == "capacity":
        state.denied = True
    elif failure == "host":
        fixture.base.write_bytes(b"changed executable")
    elif failure == "tools":
        (fixture.source / "dump.py").write_text("changed tool")
    elif failure == "missing":
        (fixture.distributions / "openai-codex.whl").unlink()
    elif failure == "artifact":
        (fixture.distributions / "openai-codex.whl").write_bytes(b"changed wheel")
    else:
        state.response_extra = True
    with pytest.raises((ArtifactIntegrityError, PermissionError), match=match):
        fixture.prepare(network=failure == "oversize")
    record = json.loads((fixture.root / "output/failure.json").read_bytes())
    assert record["execution"] == "FAILED" and record["validation"] == "NOT_EVALUATED"
    assert not state.commands and not state.probes
    assert not (fixture.root / "output/result.json").exists()
