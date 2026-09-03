from pathlib import Path
from subprocess import CompletedProcess

import pytest

from quantos.integrations.qlib import tools


def _clean_git_result(command: list[str]) -> CompletedProcess[str]:
    if command[:3] == ["git", "rev-parse", "HEAD"]:
        output = f"{tools.QLIB_COMMIT}\n"
    elif command[:2] == ["git", "status"]:
        output = ""
    elif command[:2] in (["git", "rev-parse"], ["git", "hash-object"]):
        output = "locked-blob\n"
    else:  # pragma: no cover - guards the command contract in this test helper
        raise AssertionError(f"unexpected command: {command}")
    return CompletedProcess(command, 0, stdout=output)


def test_official_qlib_tools_verify_wheel_commit_and_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "qlib"
    (source / "scripts").mkdir(parents=True)
    (source / "scripts" / "dump_bin.py").touch()
    (source / "scripts" / "check_data_health.py").touch()
    monkeypatch.setattr(tools, "version", lambda _package: tools.QLIB_VERSION)
    monkeypatch.setattr(
        tools,
        "run_checked",
        lambda command, cwd=None: _clean_git_result(command),
    )

    verified = tools.verify_official_qlib_tools(source)
    assert verified.commit == tools.QLIB_COMMIT
    assert verified.dump_bin.name == "dump_bin.py"
    assert len(verified.dump_bin_sha256) == 64


def test_official_qlib_tools_reject_wrong_wheel_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tools, "version", lambda _package: "unexpected")
    with pytest.raises(RuntimeError, match="expected pyqlib"):
        tools.verify_official_qlib_tools(tmp_path)


def test_official_qlib_tools_reject_tracked_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "qlib"
    (source / "scripts").mkdir(parents=True)
    (source / "scripts" / "dump_bin.py").touch()
    (source / "scripts" / "check_data_health.py").touch()
    monkeypatch.setattr(tools, "version", lambda _package: tools.QLIB_VERSION)

    def dirty_result(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if command[:2] == ["git", "status"]:
            return CompletedProcess(command, 0, stdout=" M scripts/dump_bin.py\n")
        return _clean_git_result(command)

    monkeypatch.setattr(tools, "run_checked", dirty_result)
    with pytest.raises(RuntimeError, match="tracked working-tree changes"):
        tools.verify_official_qlib_tools(source)
