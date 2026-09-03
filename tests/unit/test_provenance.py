from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quantos.application import (
    ProvenanceError,
    capture_runtime_fingerprint,
    verify_code_provenance,
)
from quantos.artifacts import sha256_file
from quantos.contracts.status import ReasonCode


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "quantos-test")
    _git(repo, "config", "user.email", "quantos-test@example.invalid")
    _git(repo, "add", "uv.lock", "source.py")
    _git(repo, "commit", "--quiet", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD"), sha256_file(repo / "uv.lock")


def test_code_provenance_requires_exact_clean_commit_and_lockfile(tmp_path: Path) -> None:
    repo, commit_hash, lockfile_hash = _repository(tmp_path)

    evidence = verify_code_provenance(
        repo,
        expected_commit_hash=commit_hash,
        expected_lockfile_hash=lockfile_hash,
    )
    assert evidence.commit_hash == commit_hash
    assert evidence.lockfile_hash == lockfile_hash

    (repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ProvenanceError) as dirty:
        verify_code_provenance(
            repo,
            expected_commit_hash=commit_hash,
            expected_lockfile_hash=lockfile_hash,
        )
    assert dirty.value.reason_code is ReasonCode.REPRODUCIBILITY_MISMATCH


def test_code_provenance_rejects_non_repository_and_wrong_hashes(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceError) as absent:
        verify_code_provenance(
            tmp_path,
            expected_commit_hash="a" * 40,
            expected_lockfile_hash="b" * 64,
        )
    assert absent.value.reason_code is ReasonCode.REPRODUCIBILITY_MISMATCH

    repo, commit_hash, lockfile_hash = _repository(tmp_path)
    with pytest.raises(ProvenanceError, match="does not match Git HEAD"):
        verify_code_provenance(
            repo,
            expected_commit_hash="a" * 40,
            expected_lockfile_hash=lockfile_hash,
        )
    with pytest.raises(ProvenanceError, match="lockfile hash"):
        verify_code_provenance(
            repo,
            expected_commit_hash=commit_hash,
            expected_lockfile_hash="b" * 64,
        )


def test_runtime_fingerprint_is_complete_stable_and_secret_free() -> None:
    first = capture_runtime_fingerprint()
    second = capture_runtime_fingerprint()

    assert first == second
    assert first.content_hash == second.content_hash
    assert [item.name for item in first.packages] == sorted(item.name for item in first.packages)
    assert "TUSHARE_TOKEN" not in first.model_dump_json()
