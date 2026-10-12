"""Offline environment regression: real env/Python/zsh, synthetic sockets and SDK."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import test_p10_v4 as synthetic

from quantos.application import p10_v4 as rubric
from quantos.application import p10_v4_runner as runner
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.p10_v4 import PROBE_ARGV, PROBE_ENVIRONMENT

FIXTURE = Path("tests/fixtures/p10_codex_workspace_v4_env1").resolve()
OLD_FIXTURE = FIXTURE.with_name("p10_codex_workspace_v4")

# Install on every interpreter entry, including after execve; never touch real sockets.
AUDIT_GUARD = """
import sys
def deny_real_socket(event, args):
    if event.startswith('socket.'):
        raise AssertionError('real socket operation forbidden by offline test')
sys.addaudithook(deny_real_socket)
"""
SOCKET_STUB = """
import socket
from types import SimpleNamespace
def synthetic_socket(family, kind):
    assert dict(os.environ) == ENVIRONMENT
    if TEST_ERRNO is not None:
        raise OSError(TEST_ERRNO, 'synthetic socket result')
    return SimpleNamespace(close=lambda: None)
socket.socket = synthetic_socket
"""


def mocked_fixture(tmp_path: Path, number: int | None = None) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    probe = root / "network_probe.py"
    source = probe.read_text()
    assert source.count("import socket\n") == 1
    probe.write_text(
        AUDIT_GUARD + source.replace("import socket\n", f"TEST_ERRNO = {number!r}\n" + SOCKET_STUB)
    )
    return root


def contaminated_environment(tmp_path: Path) -> dict[str, str]:
    startup = tmp_path / "zsh"
    startup.mkdir(exist_ok=True)
    (startup / ".zshenv").write_text('path=("/synthetic/local/bin" $path)\n')
    return {
        "LANG": "C",
        "PATH": "/synthetic/sdk/codex-path:/usr/bin:/bin",
        "TZ": "GMT",
        "HOME": str(tmp_path),
        "ZDOTDIR": str(startup),
        "P10_FORBIDDEN_SECRET": "synthetic-environment-test-marker",
    }


@pytest.mark.parametrize("number,exit_code", [(None, 0), (1, 1), (97, 2)])
def test_direct_and_shell_entries_have_identical_actual_probe_environment(
    tmp_path: Path, number: int | None, exit_code: int
) -> None:
    fixture = mocked_fixture(tmp_path, number)
    contaminated = contaminated_environment(tmp_path)
    results = []
    # The same model-visible command is used; shell startup must run before the entry point.
    for argv, environment in (
        (list(PROBE_ARGV), dict(PROBE_ENVIRONMENT)),
        (
            [
                "/usr/bin/zsh",
                "-c",
                '[[ "$PATH" == /synthetic/local/bin:* ]] || exit 99; ' + " ".join(PROBE_ARGV),
            ],
            contaminated,
        ),
    ):
        result = subprocess.run(
            argv, cwd=fixture, env=environment, capture_output=True, text=True, timeout=5
        )
        assert result.returncode == exit_code, result.stderr
        assert result.stderr == ""
        observed = rubric.parse_probe(result.stdout, result.returncode)
        assert observed is not None
        inputs = rubric.load_inputs(fixture)
        spec = rubric.build_spec(inputs, rubric.build_request(inputs))
        assert observed.context == rubric.probe_context(inputs, spec)
        results.append(result.stdout)
    assert results[0] == results[1]
    # Resetting the network child must not turn the independent leak check into a false pass.
    secret = subprocess.run(
        ["/usr/bin/zsh", "-c", '/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"'],
        env=contaminated,
        capture_output=True,
        timeout=5,
    )
    assert secret.returncode == 1


@pytest.mark.parametrize("case", ["launcher_identity", "unexpected_argument", "fake_fixed_stage"])
def test_setup_errors_produce_no_socket_observation(tmp_path: Path, case: str) -> None:
    fixture = mocked_fixture(tmp_path)
    probe = fixture / "network_probe.py"
    args = list(PROBE_ARGV)
    expected = ""
    if case == "launcher_identity":
        source = probe.read_text()
        source = source.replace(
            'ENV_LAUNCHER_HASH = "'
            'f13fae95a6f3fcba6c0ee8787c92747089eb81e550673f135bc4bc09bfc174d1"',
            'ENV_LAUNCHER_HASH = "' + "0" * 64 + '"',
        )
        probe.write_text(source)
        expected = "launcher identity mismatch"
    elif case == "unexpected_argument":
        args.append("--unexpected")
        expected = "unexpected probe arguments"
    else:
        args.append("--environment-fixed")
        expected = "probe process environment is not exact"
    result = subprocess.run(
        args,
        cwd=fixture,
        env=contaminated_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert expected in result.stderr
    assert rubric.parse_probe(result.stderr, result.returncode) is None


@pytest.mark.parametrize("wrong_inner_path", [False, True])
def test_existing_manager_export_replay_and_strict_context_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrong_inner_path: bool
) -> None:
    fixture = mocked_fixture(tmp_path)
    monkeypatch.setattr(synthetic, "FIXTURE", fixture)
    provider = synthetic.events()
    if wrong_inner_path:
        payload = synthetic.probe_payload()
        payload["context"]["environment"]["PATH"] = "/unexpected:/usr/bin:/bin"
        provider[7]["payload"]["item"]["aggregated_output"] = (
            canonical_json_bytes(payload).decode() + "\n"
        )
    # Actual manager control launch/re-exec and export/replay; all socket calls are stubs.
    result = runner.execute(
        fixture,
        tmp_path / "output",
        adapter=synthetic.SyntheticAdapter(provider),
        preparation_hash="a" * 64,
    )
    observation = json.loads(
        (result.report_path.parent / "harness-capability-observation.json").read_bytes()
    )
    assert observation["controls_valid"] is True
    assert observation["strict_completion_order"] is True
    assert observation["socket_creation_denial_observed"] is not wrong_inner_path
    assert result.report.decision == ("NO_GO" if wrong_inner_path else "GO")
    assert runner.summary(result)["fr03_authority_change"] is False


def test_successor_changes_only_network_entry_and_instructions() -> None:
    changed = {
        p.relative_to(FIXTURE).as_posix()
        for p in FIXTURE.rglob("*")
        if p.is_file() and p.read_bytes() != (OLD_FIXTURE / p.relative_to(FIXTURE)).read_bytes()
    }
    assert changed == {"network_probe.py", "task.md"}
    inputs = rubric.load_inputs(FIXTURE)
    old = rubric.load_inputs(OLD_FIXTURE)
    new_spec = rubric.build_spec(inputs, rubric.build_request(inputs))
    old_spec = rubric.build_spec(old, rubric.build_request(old))
    assert new_spec.content_hash != old_spec.content_hash
    assert new_spec.implementation_hash == old_spec.implementation_hash
    assert new_spec.candidate_version == old_spec.candidate_version == "0.162.1"
