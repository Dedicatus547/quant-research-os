"""Bounded offline wiring probes; synthetic ports grant no scientific qualification."""

import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_discovery_prediction_pit_scope import pit_probe  # noqa: F401

from quantos.application import autonomous_execution as execution
from quantos.application import discovery_prediction as prediction
from quantos.application import field_study as study
from quantos.contracts.autonomous import AutonomousExecutionResult
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.campaign import TrialOutcome
from quantos.contracts.field_study import FrozenFieldStudyConfiguration
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.infrastructure.hosted_storage import LEASE_ENV

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = ROOT
SNAPSHOT = Path(
    "/home/zjw/quant-research-os/artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
)
VIEW = Path(
    "/home/zjw/quant-research-os/artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
)


@pytest.fixture(scope="module")
def metadata():
    if not (SNAPSHOT / "manifest.json").is_file() or not (VIEW / "manifest.json").is_file():
        pytest.skip("retained small metadata originals unavailable")
    return (
        DataSnapshotManifest.model_validate_json((SNAPSHOT / "manifest.json").read_bytes()),
        QlibViewManifest.model_validate_json((VIEW / "manifest.json").read_bytes()),
    )


@pytest.fixture
def fixture(tmp_path, monkeypatch, metadata):
    source = tmp_path / "source"
    source.mkdir()
    (source / "fixture.py").write_text("fixture = True\n")
    snapshot, view = tmp_path / "snapshot", tmp_path / "view"
    snapshot.mkdir()
    (view / "calendars").mkdir(parents=True)
    calendar = tuple(
        date(2015, 1, 1) + timedelta(days=i)
        for i in range(4018)
        if (date(2015, 1, 1) + timedelta(days=i)).weekday() < 5
    )
    (view / "calendars/day.txt").write_text("\n".join(d.isoformat() for d in calendar))
    config = study.configuration_from_workspace(
        study_id="fixture-relative5",
        workspace=REPOSITORY,
        snapshot_path=snapshot,
        qlib_view_path=view,
        code_commit_hash="a" * 40,
        lockfile_hash="b" * 64,
    )
    config = FrozenFieldStudyConfiguration.model_validate(
        {**config.model_dump(), "workspace": str(source)}
    )
    monkeypatch.setattr(study, "verify_code_provenance", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        study,
        "VerifiedExecutionInputs",
        lambda *_: SimpleNamespace(snapshot=metadata[0], view=metadata[1]),
    )
    monkeypatch.setattr(study, "require_durable_execution_root", lambda *_: None)
    monkeypatch.setattr(study.subprocess, "check_output", lambda *_a, **_kw: b"fixture.py\0")
    monkeypatch.setattr(prediction, "prediction_verifier_identity", lambda: {"fixture": True})
    return config, metadata, tmp_path, calendar


def prepared(fixture):
    config, _, root, _ = fixture
    return study.prepare(config, root / "preparation", root / "execution")


@pytest.mark.parametrize("key", ["window", "lag", "data", "policy"])
def test_fixed_design_rejects_expansion(fixture, key):
    config, *_ = fixture
    values = config.model_dump(mode="python")
    if key == "window":
        values["volume"]["expression"]["nodes"][1]["window"] = 10
    elif key == "lag":
        values["price"]["expression"]["input_lag_trading_days"] = 1
    elif key == "data":
        values["snapshot_hash"] = "c" * 64
    else:
        values["validation_policy"]["parameter_windows"] = (5,)
    with pytest.raises(ValueError):
        FrozenFieldStudyConfiguration.model_validate(values)


def test_prepare_status_have_no_execution_side_effect(fixture, monkeypatch):
    def forbidden(*_a, **_kw):
        raise AssertionError("scientific service called")

    monkeypatch.setattr(study, "QuantosResearchExecutionAdapter", forbidden)
    monkeypatch.setattr(execution.QlibWorkflowResearchService, "run", forbidden)
    monkeypatch.setattr(execution.FactorSignalArtifactBuilder, "build", forbidden)
    first = prepared(fixture)
    assert first == prepared(fixture)
    assert len(first.tasks) == 2
    assert first.tasks[0].request.execution_identity != first.tasks[1].request.execution_identity
    assert first.prediction_profile.min_common_days == math.ceil(
        0.9 * len(first.prediction_profile.expected_dates)
    )
    assert first.effective_segments["train"].end == date(2019, 12, 24)
    assert study.status(first)["scientific_verification"] == "NOT_PERFORMED_BY_STATUS"
    assert not (Path(first.execution_root)).exists()
    loaded = study.load_preparation(
        Path(first.preparation_root) / "preparation.json", first.content_hash
    )
    assert loaded == first


def test_tampered_task_and_calendar_rejected(fixture):
    result = prepared(fixture)
    damaged = result.tasks[0].model_copy(
        update={"compute_units": result.tasks[0].compute_units - 1}
    )
    with pytest.raises(ValueError, match="budget mismatch"):
        study.status(result.model_copy(update={"tasks": (damaged, result.tasks[1])}))
    altered = result.prediction_profile.model_copy(
        update={"expected_dates": result.prediction_profile.expected_dates[:-1]}
    )
    with pytest.raises(ValueError, match="policy mismatch"):
        study.status(result.model_copy(update={"prediction_profile": altered}))


def test_profile_identity_and_adapter_request_scope(fixture, monkeypatch):
    result = prepared(fixture)
    config = result.configuration
    task = result.tasks[0]
    monkeypatch.setattr(execution, "verify_snapshot", lambda _: result.snapshot)
    monkeypatch.setattr(execution, "verify_qlib_view", lambda _: result.view)
    monkeypatch.setattr(execution, "require_durable_execution_root", lambda _: None)
    adapter = execution.QuantosResearchExecutionAdapter(
        campaign=task.campaign,
        family=task.family,
        budget=task.budget,
        template=task.template,
        manifest=task.manifest,
        bindings=task.bindings,
        snapshot_path=Path(config.snapshot_path),
        qlib_view_path=Path(config.qlib_view_path),
        base_authoring=config.volume,
        research_policy=config.research_policy,
        validation_policy=config.validation_policy,
        cost_policy=config.cost_policy,
        backtest_policy=config.backtest_policy,
        output_root=Path(result.execution_root) / "V",
        workspace=Path(config.workspace),
        field_study=config,
        discovery_stage_recovery=True,
    )
    adapter._verify_request(task.request)
    with pytest.raises(RuntimeError):
        adapter._verify_request(task.request.model_copy(update={"agent_run_hash": "f" * 64}))
    with pytest.raises(RuntimeError):
        adapter._verify_request(task.request.model_copy(update={"remaining_executions": 2}))
    legacy = execution.build_autonomous_execution_bindings(
        snapshot=result.snapshot,
        qlib_view=result.view,
        research_policy=config.research_policy,
        validation_policy=config.validation_policy,
        authoring=config.volume,
        cost_policy=config.cost_policy,
        backtest_policy=config.backtest_policy,
        code_commit_hash=config.code_commit_hash,
        lockfile_hash=config.lockfile_hash,
    )
    assert legacy.execution_policy_hash != task.bindings.execution_policy_hash
    assert legacy.pit_policy_hash != task.bindings.pit_policy_hash
    seen = {}

    def pit_stop(*_a, **kw):
        seen.update(kw)
        raise RuntimeError("PROFILE_REACHED")

    monkeypatch.setattr(
        adapter, "_discovery_stage", lambda _r, _stage, _inputs, build, *_a: build()
    )
    monkeypatch.setattr(execution.release, "build_compact_pit_evidence_collection", pit_stop)
    with pytest.raises(RuntimeError, match="PROFILE_REACHED"):
        adapter._discovery_variant(
            task.request,
            adapter._authoring(task.request),
            config.cost_policy,
            (),
            Path(result.execution_root) / "V/baseline",
            {},
            None,
        )
    assert seen["execution_profile"] == "frozen-field-study/v1"


def test_run_budget_and_pins_reject_before_engine(fixture, monkeypatch):
    result = prepared(fixture)
    monkeypatch.setattr(study, "configured_guard", lambda: pytest.fail("guard reached"))
    task = result.tasks[0]
    for digest, units in [
        ("f" * 64, task.compute_units),
        (task.request.content_hash, task.compute_units - 1),
    ]:
        with pytest.raises(ValueError, match="allowance differs"):
            study.run(
                result, "V", request_hash=digest, max_compute_units=units, expected_new_bytes=100
            )


def test_explicit_recovery_reuses_identity_and_receipt(fixture, monkeypatch):
    result = prepared(fixture)
    task = result.tasks[0]
    root = Path(result.execution_root) / "V"
    lease = fixture[2] / "lease"
    lease.mkdir()
    (lease / "prelaunch.json").write_bytes(canonical_json_bytes({"expected_new_bytes": 1024}))
    monkeypatch.setenv(LEASE_ENV, str(lease))
    guard = SimpleNamespace(
        policy_hash="f" * 64,
        require_root=lambda _: None,
        require_lease=lambda: None,
        check=lambda _: None,
    )
    monkeypatch.setattr(study, "configured_guard", lambda: guard)
    calls = []
    receipt = []
    outcome = AutonomousExecutionResult(
        request_hash=task.request.content_hash,
        outcome=TrialOutcome.EXECUTION_FAILED,
        execution_requested=True,
        compute_seconds=task.compute_units,
    )

    class Port:
        def __init__(self, **kwargs):
            assert kwargs["field_study"] == result.configuration

        def verified_completed_execution(self, request):
            assert request == task.request
            return receipt[0] if receipt else None

        def execute(self, request):
            calls.append(request.content_hash)
            if len(calls) == 1:
                raise RuntimeError("fixture interrupt")
            receipt.append(outcome)
            return outcome

    monkeypatch.setattr(study, "QuantosResearchExecutionAdapter", Port)
    kwargs = dict(
        request_hash=task.request.content_hash,
        max_compute_units=task.compute_units,
        expected_new_bytes=1024,
    )
    with pytest.raises(RuntimeError, match="fixture interrupt"):
        study.run(result, "V", **kwargs)
    with pytest.raises(ValueError, match="explicit --resume"):
        study.run(result, "V", **kwargs)
    assert study.run(result, "V", resume=True, **kwargs) == outcome
    assert study.run(result, "V", **kwargs) == outcome
    assert calls == [task.request.content_hash] * 2
    assert len(list((root / "management/attempts").glob("*/returned.json"))) == 2
    assert (
        json.loads((root / "management/attempts/00000001/returned.json").read_bytes())[
            "process_exit"
        ]
        is None
    )


def test_comparison_retains_both_requests_and_null_for_missing(fixture, monkeypatch):
    result = prepared(fixture)
    task0, task1 = result.tasks

    def cohort(_profile, _sources, *, base_authorings, output_root):
        assert len(base_authorings) == 2
        return {
            "rows": [
                {
                    "execution_request_hash": task0.request.content_hash,
                    "primary_common_rank_ic_mean": 0.1,
                },
                {
                    "execution_request_hash": task1.request.content_hash,
                    "primary_common_rank_ic_mean": None,
                },
            ],
            "missing_or_rejected_requests": 1,
            "request_denominator": 2,
            "common_days": 10,
        }

    monkeypatch.setattr(prediction, "publish_prediction_cohort", cohort)
    report = study.compare(result, {}, fixture[2] / "comparison")
    assert report["volume_minus_price"] is None
    assert report["request_denominator"] == 2
    assert report["paired_comparison_status"] == "UNAVAILABLE"


def test_cli_help_has_only_explicit_commands():
    spec = importlib.util.spec_from_file_location(
        "field_study_cli", REPOSITORY / "scripts/frozen_field_study.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as error:
        module.main(["--help"])
    assert error.value.code == 0


def test_prediction_v3_dispatch_requires_profile(pit_probe, monkeypatch):  # noqa: F811
    source, request, resolved, _, calls, legacy = pit_probe

    class VolumeEvidence(legacy):
        pass

    monkeypatch.setattr(prediction, "PITCrossSectionEvidenceCollectionV3", VolumeEvidence)
    monkeypatch.setattr(prediction, "load_pit_artifact_evidence", lambda _: VolumeEvidence())
    request.pit_policy_hash = execution.field_study_pit_policy_hash()
    assert prediction._verify_pit(source, request, resolved) == "evidence"
    assert calls["reproduction"] == 1
    request.pit_policy_hash = "a" * 64
    with pytest.raises(ValueError, match="PIT_EXECUTION_PROFILE_MISMATCH"):
        prediction._verify_pit(source, request, resolved)


def test_cohort_verifies_each_original_once_and_uses_each_authoring(fixture, monkeypatch):
    result = prepared(fixture)
    calls = []
    source_map = {
        t.request.content_hash: SimpleNamespace(
            request=SimpleNamespace(sha256=t.request.content_hash)
        )
        for t in result.tasks
    }
    bases = {
        result.tasks[0].request.content_hash: result.configuration.volume,
        result.tasks[1].request.content_hash: result.configuration.price,
    }

    def build(source, profile, *, base_authoring):
        digest = source.request.sha256
        assert base_authoring == bases[digest]
        calls.append(digest)
        value = 0.2 if base_authoring == result.configuration.volume else 0.1
        return SimpleNamespace(
            daily=[
                SimpleNamespace(trade_date=d, rank_ic=SimpleNamespace(value=value))
                for d in profile.expected_dates
            ],
            native_sources=[SimpleNamespace(path="label.pkl", sha256="e" * 64)],
            structural_expression_hash=digest,
            original_execution_outcome="SOFT_REJECT",
            original_failure_reason=None,
            original_validation_report_hash=None,
        )

    monkeypatch.setattr(prediction, "build_prediction_evidence", build)
    monkeypatch.setattr(prediction, "validate_prediction_output_root", lambda *_: None)
    monkeypatch.setattr(
        prediction, "_publish_built_prediction_evidence", lambda *_: Path("sha256-" + ("f" * 64))
    )
    report = prediction.publish_prediction_cohort(
        result.prediction_profile,
        source_map,
        base_authorings=bases,
        output_root=fixture[2] / "output",
    )
    assert sorted(calls) == sorted(source_map)
    assert report["missing_or_rejected_requests"] == 0
    means = {r["execution_request_hash"]: r["primary_common_rank_ic_mean"] for r in report["rows"]}
    assert means[result.tasks[0].request.content_hash] - means[
        result.tasks[1].request.content_hash
    ] == pytest.approx(0.1)


def test_workflow_passes_profile_and_rejects_legacy_pit(monkeypatch):
    from quantos.research.qlib import workflow

    class V3:
        content_hash = "pit"
        expression = "expr"
        snapshot_hash = "snapshot"
        qlib_view_hash = "view"

    resolved = SimpleNamespace(
        pit_audit_evidence_hash="pit",
        expression="expr",
        snapshot_hash="snapshot",
        qlib_view_hash="view",
    )
    monkeypatch.setattr(workflow, "PITCrossSectionEvidenceCollectionV3", V3)
    monkeypatch.setattr(workflow, "load_pit_artifact_evidence", lambda _: V3())
    seen = []

    def translate(_expression, *, execution_profile):
        seen.append(execution_profile)
        raise RuntimeError("BEFORE_MODEL")

    monkeypatch.setattr(workflow, "translate_safe_expression", translate)
    args = (resolved, None, Path("/fixture/signal"), Path("/fixture/view"), Path("/fixture/out"))
    kwargs = dict(
        execution_identity="a" * 64,
        research_result_root=Path("/fixture/result"),
        workspace=Path("/fixture/source"),
        execution_profile="frozen-field-study/v1",
    )
    with pytest.raises(RuntimeError, match="BEFORE_MODEL"):
        workflow.QlibWorkflowResearchService().run(*args, **kwargs)
    assert seen == ["frozen-field-study/v1"]
    monkeypatch.setattr(workflow, "load_pit_artifact_evidence", lambda _: object())
    with pytest.raises(ValueError, match="PIT binding differs"):
        workflow.QlibWorkflowResearchService().run(*args, **kwargs)
