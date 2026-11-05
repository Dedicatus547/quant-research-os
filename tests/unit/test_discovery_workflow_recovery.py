"""Workflow recovery adopts exact retained outputs, without re-running Qlib."""

import shutil
from types import SimpleNamespace

import pytest
from test_discovery_comparison_regression import predicted as predicted
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_discovery_variant_regression import pit_fixture

from quantos.application import autonomous_execution as native
from quantos.application.autonomous_errors import AutonomousOrchestrationError
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.research_result import ResearchResultManifest


class WorkflowChecked(Exception):
    """Stop the synthetic harness after the workflow substage under test."""


@pytest.fixture
def workflow(predicted, monkeypatch):
    f = predicted
    adapter = f.adapter
    adapter.output_root = f.prediction_adapter.output_root
    assert adapter.research_results_root == f.prediction_adapter.research_results_root
    adapter.discovery_stage_recovery = True
    adapter.research_policy = f.batch.design.research_policy
    adapter.validation_policy = f.batch.design.validation_policy
    adapter.cost_policy = f.batch.design.cost_policy
    adapter.backtest_policy = f.batch.design.backtest_policy
    adapter.snapshot_path = f.service.snapshot_path
    adapter.qlib_view_path = f.service.qlib_view_path
    adapter.field_study = None
    adapter.p14dq_v2_profile = False
    adapter.discovery_profile = None
    authoring, _, schedules = pit_fixture(f)
    monkeypatch.setattr(adapter, "_authoring", lambda _: authoring)
    monkeypatch.setattr(adapter, "_profile_arguments", lambda: {})
    monkeypatch.setattr(
        native, "resolve_weekly_decision_schedules", lambda *args, **kw: (schedules,)
    )
    baseline = SimpleNamespace(
        resolved=f.resolved,
        signal_hash=f.signal.artifact_hash,
        signal_path=f.built.path / "synthetic-signal",
    )
    monkeypatch.setattr(adapter, "_discovery_variant", lambda *args: baseline)
    manifest = ResearchResultManifest.create(
        **{
            **f.built.manifest.model_dump(exclude={"artifact_hash"}),
            "qlib_run_id": f.request.execution_identity[:32],
        }
    )
    destination = adapter.research_results_root / ("sha256-" + manifest.artifact_hash)
    shutil.copytree(f.built.path, destination)
    (destination / "manifest.json").write_bytes(canonical_json_bytes(manifest.model_dump()))
    native_root = (
        adapter.output_root
        / "executions"
        / f.request.execution_identity
        / "qlib-workflow/native-records"
        / ("sha256-" + f.request.execution_identity)
    )
    calendar = adapter.qlib_view_path / "calendars/day.txt"
    calendar.parent.mkdir(parents=True, exist_ok=True)
    calendar.write_text("2024-01-02\n2024-01-03\n")
    split = SimpleNamespace(content_hash="d" * 64)
    split_calls, builds = [], []

    def verify_split(path, **kwargs):
        assert path == native_root / "model-data-splits.json"
        assert kwargs["resolved"] == f.resolved and kwargs["source_files"] == manifest.source_files
        split_calls.append(path)
        return split

    def run(*args, **kwargs):
        builds.append(kwargs)
        return SimpleNamespace(
            build=SimpleNamespace(manifest=manifest, path=destination, export_audit_hash=None),
            model_data_split_hash=split.content_hash,
        )

    monkeypatch.setattr(native, "verify_model_data_split", verify_split)
    monkeypatch.setattr(native, "QlibWorkflowResearchService", lambda: SimpleNamespace(run=run))
    return SimpleNamespace(
        f=f,
        adapter=adapter,
        manifest=manifest,
        destination=destination,
        native_root=native_root,
        split=split,
        baseline=baseline,
        split_calls=split_calls,
        builds=builds,
    )


def stage_under_test(monkeypatch, workflow, *, build=False, edit=lambda outputs: None):
    def stage(request, name, inputs, builder, verifier, recover):
        assert name == "workflow" and inputs["signal_hash"] == workflow.baseline.signal_hash
        outputs = builder() if build else recover()
        assert outputs is not None
        edit(outputs)
        result, audit = verifier(outputs)
        assert result == workflow.manifest and audit is None
        raise WorkflowChecked

    monkeypatch.setattr(workflow.adapter, "_discovery_stage", stage)


@pytest.mark.parametrize("build", [False, True])
def test_exact_workflow_originals_are_verified_before_stage_adoption(workflow, monkeypatch, build):
    stage_under_test(monkeypatch, workflow, build=build)
    with pytest.raises(WorkflowChecked):
        workflow.adapter._execute_pipeline(workflow.f.request)
    assert len(workflow.builds) == int(build)
    assert len(workflow.split_calls) == (1 if build else 2)


@pytest.mark.parametrize(
    "attack,match",
    [
        ("baseline", "verified baseline"),
        ("native", "original native record"),
        ("split", "effective model split"),
        ("ambiguous", "ambiguous originals"),
    ],
)
def test_workflow_recovery_rejects_changed_or_ambiguous_originals(
    workflow, monkeypatch, attack, match
):
    if attack == "baseline":
        workflow.baseline.signal_hash = "e" * 64
    elif attack == "native":
        (workflow.native_root / "pred.pkl").write_bytes(b"revised prediction bytes")
    elif attack == "ambiguous":
        duplicate = workflow.adapter.research_results_root / ("sha256-" + "e" * 64)
        duplicate.mkdir()
        (duplicate / "manifest.json").write_bytes(
            canonical_json_bytes(workflow.manifest.model_dump())
        )

    def edit(outputs):
        if attack == "split":
            outputs["model_data_split_hash"] = "e" * 64

    stage_under_test(monkeypatch, workflow, edit=edit)
    with pytest.raises(AutonomousOrchestrationError, match=match):
        workflow.adapter._execute_pipeline(workflow.f.request)
    assert not workflow.builds


def test_absent_workflow_has_no_recoverable_completion(workflow, monkeypatch):
    shutil.rmtree(workflow.destination)

    def stage(request, name, inputs, build, verify, recover):
        assert name == "workflow" and recover() is None
        raise WorkflowChecked

    monkeypatch.setattr(workflow.adapter, "_discovery_stage", stage)
    with pytest.raises(WorkflowChecked):
        workflow.adapter._execute_pipeline(workflow.f.request)
    assert not workflow.builds and not workflow.split_calls
