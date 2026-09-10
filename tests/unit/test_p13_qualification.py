import importlib.util
import json
from pathlib import Path

import pytest

from quantos.artifacts.store import ArtifactConflictError
from quantos.contracts import P13BenchmarkBinding, P13QualificationBundle, P13QualificationReport

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "p13_qualification", ROOT / "scripts/p13_qualification.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_missing_store_does_not_bind_an_unrelated_agent_run(tmp_path: Path) -> None:
    agent_root = tmp_path / "agents"
    stale = agent_root / ("sha256-" + "a" * 64)
    stale.mkdir(parents=True)
    (stale / "agent-run-manifest.json").write_text("{}")
    result = runner.run(
        workspace=ROOT,
        store_path=tmp_path / "missing",
        output_root=tmp_path / "reports",
        agent_output_root=agent_root,
        snapshot_path=tmp_path / "unused",
        qlib_source=tmp_path / "unused",
        offline_report_path=None,
        candidate=False,
    )
    assert result["agent_run_manifest_hash"] is None
    assert result["data_qualified_reason"] == "SOURCE_INCOMPLETE"
    path = Path(result["bundle_path"])
    refs = json.loads((path / "references.json").read_bytes())
    assert refs["agent_attempted"] is False
    binding = P13BenchmarkBinding.model_validate_json(
        (path / "benchmark-binding.json").read_bytes()
    )
    report = P13QualificationReport.model_validate_json(
        (path / "qualification-report.json").read_bytes()
    )
    bundle = P13QualificationBundle.model_validate_json((path / "bundle.json").read_bytes())
    assert runner._publish_bundle(path.parent, binding, report, bundle, refs) == path
    (path / "qualification-report.json").write_text("{}")
    with pytest.raises(ArtifactConflictError):
        runner._publish_bundle(path.parent, binding, report, bundle, refs)
