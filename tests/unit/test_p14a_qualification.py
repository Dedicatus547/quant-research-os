import importlib.util
from pathlib import Path

import pytest

from quantos.application import capture_runtime_fingerprint
from quantos.artifacts.store import ArtifactConflictError
from quantos.contracts import CodeProvenance, P14aQualificationReport, RunStatus

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p14a_qualification", ROOT / "scripts/p14a_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_p14a_qualification_is_byte_exact_and_immutable(tmp_path: Path) -> None:
    code = CodeProvenance(
        commit_hash="a" * 40,
        lockfile_hash="b" * 64,
        worktree_clean=True,
    )
    runtime = capture_runtime_fingerprint()
    output = tmp_path / "qualification"

    result = runner.qualify(
        workspace=ROOT,
        output_root=output,
        code=code,
        runtime=runtime,
    )
    path = Path(result["qualification_path"])
    report = P14aQualificationReport.model_validate_json(
        (path / "qualification-report.json").read_bytes()
    )
    assert report.status is RunStatus.SUCCEEDED
    assert report.principal_hashes_byte_exact
    assert report.context_bound_to_agent_spec
    assert report.independent_root_count == 2
    assert result["qualification_report_hash"] == report.content_hash

    repeated = runner.qualify(
        workspace=ROOT,
        output_root=output,
        code=code,
        runtime=runtime,
    )
    assert repeated == result

    (path / "qualification-report.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactConflictError):
        runner.qualify(
            workspace=ROOT,
            output_root=output,
            code=code,
            runtime=runtime,
        )
