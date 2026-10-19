"""Small offline counterexamples for environment identities and failure receipts."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure import runtime_environment as env

PROFILE = Path(__file__).resolve().parents[2] / "configs/runtime/bounded-local-01621/profile.json"


def test_frozen_closure_contains_sdk_pair_build_tools_and_official_sources():
    profile, lock = env.load_profile(PROFILE)
    packages = {p["name"]: p for p in lock["packages"]}
    assert packages["openai-codex"]["version"] == "0.162.1"
    assert packages["openai-codex-cli-bin"]["version"] == "0.162.1"
    assert {"setuptools", "wheel", "gym", "pyqlib", "lightgbm"} <= packages.keys()
    assert {"jsonpointer", "rfc3986-validator", "tinycss2"} <= packages.keys()
    assert profile["qlib_tools"]["commit"] == "da920b7f954f48ab1bb64117c976710de198373e"
    assert all(
        p["artifact"]["url"].startswith("https://files.pythonhosted.org/")
        for p in packages.values()
    )


def test_profile_hash_mismatch_rejected_before_storage_or_execution(tmp_path, monkeypatch):
    copied = tmp_path / "profile"
    copied.mkdir()
    for source in PROFILE.parent.iterdir():
        if source.is_file():
            (copied / source.name).write_bytes(source.read_bytes())
    (copied / "requirements.lock").write_text("openai-codex==0.154.0\n")
    guard = Mock()
    monkeypatch.setattr(env, "storage_checkpoint", guard)
    with pytest.raises(ArtifactIntegrityError, match="identities differ"):
        env.describe_environment(copied / "profile.json")
    guard.assert_not_called()


def test_declared_distribution_hash_mismatch_is_rejected(tmp_path):
    artifact = tmp_path / "fixed.whl"
    artifact.write_bytes(b"wrong")
    with pytest.raises(ArtifactIntegrityError, match="distribution differs"):
        env._verify_artifact(artifact, {"size_bytes": 5, "sha256": "0" * 64})


def test_prepare_rejects_glibc_below_declared_host_before_copying(tmp_path, monkeypatch):
    profile, lock = env.load_profile(PROFILE)
    assert profile["host"]["minimum_glibc"] == "2.35"
    base, uv = tmp_path / "python3.11", tmp_path / "uv"
    digest = env.sha256_file
    hashes = {base: profile["host"]["base_python_sha256"], uv: profile["host"]["uv_sha256"]}
    monkeypatch.setattr(env, "sha256_file", lambda p: hashes[p] if p in hashes else digest(p))
    monkeypatch.setattr(env, "load_profile", lambda _: (profile, lock))
    monkeypatch.setattr(env, "storage_checkpoint", lambda *_: None)
    monkeypatch.setattr(env.platform, "system", lambda: "Linux")
    monkeypatch.setattr(env.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(env.platform, "libc_ver", lambda: ("glibc", "2.34"))
    monkeypatch.setattr(Path, "is_relative_to", lambda *_: False)
    verify_base, command = Mock(), Mock()
    monkeypatch.setattr(env, "_verify_base", verify_base)
    monkeypatch.setattr(env, "_command", command)
    output = tmp_path / "unsupported-host"
    with pytest.raises(ArtifactIntegrityError, match="system C library is unsupported"):
        env.prepare_environment(
            PROFILE,
            output,
            base_python=base,
            uv=uv,
            source=tmp_path,
            qlib_source=tmp_path,
            artifact_sources=(),
        )
    verify_base.assert_not_called()
    command.assert_not_called()
    assert json.loads((output / "failure.json").read_bytes())["execution"] == "FAILED"


def test_prepare_failure_is_durable_and_does_not_copy_or_print_exception(tmp_path, monkeypatch):
    # The test command supplies a durable --basetemp; ordinary CI tmp fixtures are
    # synthetic scratch, so only the production /tmp rejection is bypassed here.
    monkeypatch.setattr(
        env,
        "load_profile",
        lambda _: (_ for _ in ()).throw(RuntimeError("synthetic-credential-must-not-be-saved")),
    )
    output = tmp_path / "retained-failure"
    monkeypatch.setattr(Path, "is_relative_to", lambda *_: False)
    command = Mock()
    monkeypatch.setattr(env, "_command", command)
    with pytest.raises(RuntimeError):
        env.prepare_environment(
            PROFILE,
            output,
            base_python=Path("missing"),
            uv=Path("missing"),
            source=Path("missing"),
            qlib_source=Path("missing"),
            artifact_sources=(),
        )
    failure = json.loads((output / "failure.json").read_bytes())
    assert failure["execution"] == "FAILED"
    assert failure["validation"] == "NOT_EVALUATED"
    assert "synthetic-credential" not in (output / "failure.json").read_text()
    command.assert_not_called()


def test_explicit_environment_rejects_fallback_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "verify_environment", lambda *_: {"source": str(tmp_path)})
    with pytest.raises(ArtifactIntegrityError, match="explicit prepared environment"):
        env.bind_environment(tmp_path, PROFILE, tmp_path)


def test_environment_binding_rejects_same_version_module_from_old_overlay(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    prefix = tmp_path / "venv"
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "path", [str(prefix / "lib/python3.11/site-packages")])
    # An overlay need not be named site-packages; matching versions do not grant identity.
    monkeypatch.setitem(
        sys.modules,
        "qlib",
        SimpleNamespace(
            __file__=str(tmp_path / "old-overlay/qlib/__init__.py"), __version__="0.9.7"
        ),
    )
    verify = Mock()
    monkeypatch.setattr(env, "verify_environment", verify)
    with pytest.raises(ArtifactIntegrityError, match="process imports differ"):
        env.bind_environment(tmp_path, PROFILE, tmp_path)
    verify.assert_not_called()


@pytest.mark.parametrize("field", ["profile_sha256", "inventory_sha256"])
def test_environment_rejects_tampered_binding_before_imports(tmp_path, monkeypatch, field):
    result = {
        "execution": "SUCCEEDED",
        "profile_sha256": env.sha256_file(PROFILE),
        "inventory_sha256": "0" * 64,
    }
    (tmp_path / "profile.json").write_bytes(PROFILE.read_bytes())
    (tmp_path / "inventory.json").write_text("{}")
    result[field] = "f" * 64
    (tmp_path / "result.json").write_text(json.dumps(result))
    probe = Mock()
    monkeypatch.setattr(env, "_probe", probe)
    with pytest.raises(ArtifactIntegrityError, match="preparation identity differs"):
        env.verify_environment(tmp_path, PROFILE)
    probe.assert_not_called()


def test_failed_subprocess_retains_observed_exit_without_stderr(tmp_path):
    import sys

    with pytest.raises(ArtifactIntegrityError, match="subprocess failed"):
        env._command(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys;sys.stderr.write('synthetic-secret');sys.exit(17)",
            ],
            tmp_path,
            "probe",
        )
    result = json.loads((tmp_path / "probe-exit.json").read_bytes())
    assert result["actual_exit"] == 17
    assert result["ended_at"] >= result["started_at"]
    assert not any(p.name.endswith("stderr") for p in tmp_path.iterdir())


def test_import_probe_keeps_json_parseable_when_optional_modules_print(monkeypatch, capsys):
    import importlib
    import importlib.metadata
    import site
    import sys
    from types import SimpleNamespace

    from quantos.integrations import qlib

    source = Path(__file__).resolve().parents[2]
    prefix = Path(sys.prefix).resolve()
    package_site = prefix / "lib/python3.11/site-packages"

    def noisy_import(_):
        print("optional dependency unavailable; model skipped")
        return SimpleNamespace(__file__=str(package_site / "fake.py"))

    monkeypatch.setattr(importlib, "import_module", noisy_import)
    monkeypatch.setattr(importlib.metadata, "distributions", lambda: [])
    monkeypatch.setattr(
        qlib,
        "verify_official_qlib_tools",
        lambda _: SimpleNamespace(dump_bin_sha256="1" * 64, health_check_sha256="2" * 64),
    )
    monkeypatch.setattr(site, "ENABLE_USER_SITE", False)
    monkeypatch.setattr(
        sys, "path", [p for p in sys.path if "site-packages" not in p] + [str(package_site)]
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["probe", json.dumps([str(source), str(prefix), "unused-official-checkout", {}])],
    )
    exec(env._PROBE, {})
    captured = capsys.readouterr()
    assert json.loads(captured.out)["dump_bin_sha256"] == "1" * 64
    assert "model skipped" in captured.err
