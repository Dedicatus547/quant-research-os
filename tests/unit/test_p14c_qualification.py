from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantos.application import capture_runtime_fingerprint
from quantos.application.provenance import ProvenanceError
from quantos.contracts import CodeProvenance
from quantos.contracts.campaign_selection import CampaignSelectionReport, CampaignSelectionVerdict
from quantos.contracts.p14c_qualification import (
    P14C_CANONICAL_CASES,
    P14C_NEGATIVE_CASES,
    P14cQualificationReport,
    P14cRootEvidence,
)
from quantos.contracts.status import ReasonCode, RunStatus, ValidationVerdict

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p14c_qualification_test_module", ROOT / "scripts/p14c_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _init_clean_repo(root: Path) -> None:
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True, text=True)
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "uv.lock"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=QuantOS qualification test",
            "-c",
            "user.email=qualification@example.invalid",
            "commit",
            "-m",
            "frozen test input",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_runner_binds_a_clean_checkout_and_rejects_dirty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "clean-workspace"
    _init_clean_repo(workspace)
    monkeypatch.setattr(runner, "ROOT", workspace)
    runtime = capture_runtime_fingerprint()
    monkeypatch.setattr(runner, "capture_runtime_fingerprint", lambda: runtime)
    captured: dict[str, object] = {}

    def record_provenance(**values: object) -> dict[str, object]:
        captured.update(values)
        return {"runner_invoked": True}

    monkeypatch.setattr(runner, "_qualify_from_provenance", record_provenance)
    assert runner.run(workspace=workspace, output_root=tmp_path / "out") == {"runner_invoked": True}
    code = captured["code"]
    assert isinstance(code, CodeProvenance)
    assert code.worktree_clean
    assert code.commit_hash
    assert code.lockfile_hash == runner.sha256_file(workspace / "uv.lock")

    (workspace / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    with pytest.raises(ProvenanceError):
        runner.run(workspace=workspace, output_root=tmp_path / "rejected")


def test_double_root_report_replays_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    code = CodeProvenance(
        commit_hash="a" * 40,
        lockfile_hash=runner.sha256_file(ROOT / "uv.lock"),
        worktree_clean=True,
    )
    runtime = capture_runtime_fingerprint()
    result = runner._qualify_from_provenance(
        workspace=ROOT,
        output_root=tmp_path / "qualification",
        code=code,
        runtime=runtime,
    )
    artifact = Path(str(result["qualification_path"]))
    report = runner.verify_p14c_qualification_artifact(artifact)
    assert report.qualification_hash == result["qualification_hash"]
    assert report.status is RunStatus.SUCCEEDED
    assert report.verdict is ValidationVerdict.PASS
    assert report.implementation_commit_hash == code.commit_hash
    assert report.lockfile_hash == code.lockfile_hash
    frozen_lock = artifact / "frozen" / "uv.lock"
    assert runner.sha256_file(frozen_lock) == report.lockfile_hash
    assert report.runtime_fingerprint_hash == runtime.content_hash
    assert report.principal_hashes_byte_exact
    assert report.principal_hash_summary == runner.p14c_principal_hash_summary(report.roots)
    assert report.negative_case_count == len(P14C_NEGATIVE_CASES) * 2
    assert report.roots[0].cases == report.roots[1].cases
    assert report.roots[0].negative_cases == report.roots[1].negative_cases
    assert tuple(item.outcome.case_id for item in report.roots[0].cases) == P14C_CANONICAL_CASES
    assert tuple(item.case_id for item in report.roots[0].negative_cases) == P14C_NEGATIVE_CASES
    incomplete_root = report.roots[0].model_dump(mode="python")
    incomplete_root["cases"] = incomplete_root["cases"][:-1]
    with pytest.raises(ValidationError):
        P14cRootEvidence.model_validate(incomplete_root)

    root_a = artifact / "root-A"
    selected = report.roots[0].cases[0]
    selected_dir = (
        root_a
        / "cases"
        / "selected"
        / "selection-report"
        / f"sha256-{selected.outcome.selection_report_hash}"
    )
    selected_report = CampaignSelectionReport.model_validate_json(
        (selected_dir / "report.json").read_bytes()
    )
    assert selected_report.run_status is RunStatus.SUCCEEDED
    assert selected_report.verdict is CampaignSelectionVerdict.SELECTED
    assert selected_report.selected_candidate_hash is not None
    selected_score = next(
        item
        for item in selected_report.scores
        if item.candidate_hash == selected_report.selected_candidate_hash
    )
    assert selected_score.raw_p_value == 0.0001
    assert selected_score.adjusted_p_value == 0.0002

    no_selection = report.roots[0].cases[1].outcome
    assert no_selection.run_status is RunStatus.SUCCEEDED
    assert no_selection.verdict is CampaignSelectionVerdict.NO_SELECTION
    failed = report.roots[0].cases[2].outcome
    assert failed.run_status is RunStatus.FAILED
    assert failed.verdict is CampaignSelectionVerdict.NOT_EVALUATED
    assert failed.reason_code is ReasonCode.ARTIFACT_CORRUPTED

    # Repacking the same frozen file tree must reproduce the content-addressed report.
    code_copy = CodeProvenance.model_validate_json((artifact / "code-provenance.json").read_bytes())
    runtime_copy = type(runtime).model_validate_json(
        (artifact / "runtime-fingerprint.json").read_bytes()
    )
    repeated = runner._publish_qualification(
        tmp_path / "repacked",
        code=code_copy,
        runtime=runtime_copy,
        fixture_hash=report.fixture_hash,
        roots=report.roots,
        pipeline_roots=(artifact / "root-A", artifact / "root-B"),
        policy_hashes=report.policy_hashes,
    )
    assert repeated.canonical_bytes() == report.canonical_bytes()

    forged = report.model_dump(mode="python")
    forged["verdict"] = "REJECT"
    with pytest.raises(ValidationError):
        P14cQualificationReport.model_validate(forged)

    evidence = json.loads((artifact / "qualification-report.json").read_bytes())
    assert evidence["qualification_hash"] == report.qualification_hash
    original_lock = frozen_lock.read_bytes()
    frozen_lock.write_bytes(original_lock + b"\n")
    with pytest.raises(runner.QualificationError):
        runner.verify_p14c_qualification_artifact(artifact)
    frozen_lock.write_bytes(original_lock)

    (artifact / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(runner.QualificationError):
        runner.verify_p14c_qualification_artifact(artifact)
    (artifact / "unexpected.json").unlink()

    missing_proof = artifact / "root-A" / "negative-cases" / f"{P14C_NEGATIVE_CASES[0]}.json"
    missing_proof.unlink()
    with pytest.raises(runner.QualificationError):
        runner.verify_p14c_qualification_artifact(artifact)
