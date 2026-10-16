"""Controlled producer/source fixtures and real native adoption APIs; no science execution."""

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_backtest_service import _config as backtest_config
from test_backtest_service import _schedule as schedule_fixture
from test_discovery_offline_regression import durable as durable
from test_frozen_field_study import metadata as metadata

from quantos.application import autonomous_execution as execution
from quantos.application import field_study as study
from quantos.application import field_study_recovery as recovery
from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.backtest import service as backtest_service
from quantos.contracts.backtest import BacktestArtifactManifest, BacktestReconciliation
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.discovery_prediction import PredictionFileSource, PredictionImportSource
from quantos.contracts.field_study import (
    FieldStudyBaselineOrigin,
    FieldStudyRecoveryOrigin,
    FieldStudyRecoveryPreparation,
    FieldStudySourceChange,
    FrozenFieldStudyConfiguration,
)
from quantos.contracts.pit import PITGateId
from quantos.contracts.research_execution import PITCrossSectionEvidenceCollectionV3
from quantos.contracts.signal import SignalArtifactManifest, SignalRow
from quantos.research.qlib import signal as signal_service
from quantos.research.qlib.expression import translate_safe_expression
from quantos.research.qlib.pit_evidence import pit_transform_lineage_hash

ROOT = Path(__file__).resolve().parents[2]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return git(root, "rev-parse", "HEAD")


def reference(path):
    return PredictionFileSource(path=str(path), sha256=sha256_file(path))


def put(path, value):
    atomic_write_bytes(path, canonical_json_bytes(value))


def signal_fixture(task, config, view, base):
    schedule = schedule_fixture()
    expression = task.request.candidate.expression
    instant = schedule.signal_time
    temporal = dict(
        event_time=instant,
        known_at=instant,
        available_at=instant,
        observed_at=instant,
        evidence_level="CONSERVATIVE_DERIVED",
        policy_id="fixture",
    )
    authoring = execution.QuantosResearchExecutionAdapter._authoring(
        SimpleNamespace(base_authoring=config.volume), task.request
    )
    evidence = PITCrossSectionEvidenceCollectionV3.model_validate(
        dict(
            snapshot_hash=config.snapshot_hash,
            qlib_view_hash=config.qlib_view_hash,
            expression_spec_hash=expression.content_hash,
            expression=expression,
            operator_delays=execution.research_operator_delays(authoring),
            universe_index="000300.SH",
            bundles=[
                dict(
                    snapshot_hash=config.snapshot_hash,
                    expression_spec_hash=expression.content_hash,
                    universe_index="000300.SH",
                    schedule=schedule,
                    required_observations=5,
                    source_window=tuple((instant - timedelta(days=4 - i)).date() for i in range(5)),
                    members=("600000.SH",),
                    source_sets=[
                        dict(
                            table_name=table,
                            logical_field_name="adjusted_volume",
                            source_field_name=field,
                            expected_row_count=5,
                            present_row_count=5,
                            missing_row_count=0,
                            row_set_hash="c" * 64,
                            maximum_temporal=temporal,
                        )
                        for table, field in [
                            ("adjustment_factors", "adjustment_factor"),
                            ("bars", "volume_shares"),
                        ]
                    ],
                    membership_set=dict(
                        row_count=1, row_set_hash="d" * 64, maximum_temporal=temporal
                    ),
                    output_temporal=temporal,
                    gates=[
                        dict(gate_id=g, verdict="PASS", detail="controlled producer fixture")
                        for g in PITGateId
                    ],
                )
            ],
        )
    )
    resolved = execution.resolve_experiment(
        authoring,
        snapshot_hash=config.snapshot_hash,
        qlib_view_hash=config.qlib_view_hash,
        qlib_version=view.qlib_version,
        qlib_view_spec_hash=view.view_spec_hash,
        pit_audit_evidence_hash=evidence.content_hash,
        research_policy_hash=config.research_policy.content_hash,
        validation_policy_hash=config.validation_policy.content_hash,
        cost_policy_hash=config.cost_policy.content_hash,
        backtest_policy_hash=config.backtest_policy.content_hash,
        code_commit_hash=config.code_commit_hash,
        lockfile_hash=config.lockfile_hash,
    )
    staging = base / "signal-staging"
    staging.mkdir(parents=True)
    translation = translate_safe_expression(expression, execution_profile="frozen-field-study/v1")
    for name, obj in [
        ("resolved-experiment.json", resolved),
        ("pit-evidence.json", evidence),
        ("expression-translation.json", translation),
    ]:
        atomic_write_bytes(staging / name, obj.canonical_bytes())
    row = SignalRow(
        instrument_id="600000.SH",
        signal_time=instant,
        decision_time=schedule.decision_time,
        available_at=instant,
        score=0.25,
        tradable=True,
    )
    signal_service.write_signal_table((row,), staging / "signals.parquet")
    manifest = SignalArtifactManifest.create(
        resolved_experiment_hash=resolved.content_hash,
        source_expression_or_model_hash=expression.content_hash,
        snapshot_hash=config.snapshot_hash,
        qlib_version=view.qlib_version,
        qlib_view_spec_hash=view.view_spec_hash,
        qlib_view_hash=view.view_hash,
        qlib_run_id=None,
        pit_evidence_hash=evidence.content_hash,
        transform_lineage_hash=pit_transform_lineage_hash(evidence),
        expression_translation_hash=translation.content_hash,
        row_count=1,
        signal_start=instant,
        signal_end=instant,
        signal_content_hash=signal_service.signal_content_hash((row,)),
        files=signal_service._artifact_files(staging),
        created_at=datetime.now(UTC),
    )
    put(staging / "manifest.json", manifest)
    target = base / "signals" / f"sha256-{manifest.artifact_hash}"
    target.parent.mkdir()
    staging.rename(target)
    return resolved, evidence, schedule, target, manifest


def native_backtest_fixture(resolved, signal, base):
    """Typed native-shaped tiny tables, not an accounting implementation or Qlib verdict."""
    values = backtest_config().model_dump()
    values.update(
        resolved_experiment_hash=resolved.content_hash,
        signal_artifact_hash=signal.artifact_hash,
        snapshot_hash=resolved.snapshot_hash,
        qlib_view_hash=resolved.qlib_view_hash,
        cost_policy_hash=resolved.cost_policy_hash,
        backtest_policy_hash=resolved.backtest_policy_hash,
    )
    config = type(backtest_config()).model_validate(values)
    checks = [
        dict(name=name, checked_rows=0, detail="controlled fixture, no scientific qualification")
        for name in [
            "asset_identity",
            "cash_nonnegative",
            "position_value_and_weight",
            "return_cost_turnover_deltas",
            "temporal_schedule",
            "trade_unit_and_no_short",
        ]
    ]
    reconciliation = BacktestReconciliation(
        backtest_config_hash=config.content_hash,
        decision_schedule_hash=config.decision_schedule_hash,
        absolute_tolerance=1e-12,
        relative_tolerance=1e-9,
        checks=checks,
    )
    staging = base / "backtest-staging"
    staging.mkdir()
    for name, obj in [("backtest-config.json", config), ("reconciliation.json", reconciliation)]:
        atomic_write_bytes(staging / name, obj.canonical_bytes())
    tables = [
        ("portfolio", backtest_service.PORTFOLIO_SCHEMA, 1),
        ("positions", backtest_service.POSITION_SCHEMA, 0),
        ("trade-indicators", backtest_service.TRADE_INDICATOR_SCHEMA, 1),
        ("order-indicators", backtest_service.ORDER_INDICATOR_SCHEMA, 0),
        ("risk-metrics", backtest_service.RISK_METRIC_SCHEMA, 1),
    ]
    for name, schema, count in tables:
        row = {
            field.name: (
                config.start_date
                if pa.types.is_date(field.type)
                else "fixture"
                if pa.types.is_string(field.type)
                else 0.0
            )
            for field in schema
        }
        pq.write_table(
            pa.Table.from_pylist([row] * count, schema=schema), staging / f"{name}.parquet"
        )
    manifest = BacktestArtifactManifest.create(
        resolved_experiment_hash=resolved.content_hash,
        signal_artifact_hash=signal.artifact_hash,
        snapshot_hash=resolved.snapshot_hash,
        qlib_view_hash=resolved.qlib_view_hash,
        qlib_version=resolved.qlib_version,
        cost_policy_hash=resolved.cost_policy_hash,
        backtest_policy_hash=resolved.backtest_policy_hash,
        backtest_config_hash=config.content_hash,
        reconciliation_hash=reconciliation.content_hash,
        start_date=config.start_date,
        end_date=config.end_date,
        portfolio_rows=1,
        position_rows=0,
        trade_indicator_rows=1,
        order_indicator_rows=0,
        risk_metric_rows=1,
        files=backtest_service._artifact_files(staging),
        known_limitations=config.known_limitations,
        created_at=datetime.now(UTC),
    )
    put(staging / "manifest.json", manifest)
    target = base / "backtests" / f"sha256-{manifest.result_hash}"
    target.parent.mkdir()
    staging.rename(target)
    return target, manifest


@pytest.fixture(scope="module")
def lineage_base(tmp_path_factory, metadata):
    monkeypatch = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("origin-lineage")
    if root.is_relative_to("/tmp") or root.is_relative_to("/var/tmp"):
        root = ROOT / "artifacts/test-authority" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    old_workspace = root / "old-checkout"
    old_workspace.mkdir()
    git(old_workspace, "init", "-q")
    for name, text in [
        ("uv.lock", "fixture lock\n"),
        ("src/quantos/application/field_study.py", "old = True\n"),
        ("src/quantos/research/qlib/pit_evidence.py", "unchanged_science = True\n"),
    ]:
        path = old_workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    old_commit = commit(old_workspace)
    rebuilt = root / "rebuilt-checkout"
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "-q", str(old_workspace), str(rebuilt)], check=True
    )
    new_workspace = root / "new-checkout"
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "-q", str(old_workspace), str(new_workspace)], check=True
    )
    (new_workspace / "src/quantos/application/field_study.py").write_text(
        "new_recovery_wiring = True\n"
    )
    new_commit = commit(new_workspace)
    snapshot = root / "artifacts/data/snapshots" / f"sha256-{metadata[0].snapshot_hash}"
    snapshot.mkdir(parents=True)
    view = root / "artifacts/data/qlib-views" / f"sha256-{metadata[1].view_hash}"
    (view / "calendars").mkdir(parents=True)
    calendar = tuple(datetime(2014, 11, 3).date() + timedelta(days=i) for i in range(4077))
    calendar = tuple(day for day in calendar if day.weekday() < 5)
    (view / "calendars/day.txt").write_text("\n".join(map(str, calendar)))
    old_config = study.configuration_from_workspace(
        study_id="fixture-old",
        workspace=ROOT,
        snapshot_path=snapshot,
        qlib_view_path=view,
        code_commit_hash=old_commit,
        lockfile_hash=sha256_file(old_workspace / "uv.lock"),
    )
    old_config = FrozenFieldStudyConfiguration.model_validate(
        {**old_config.model_dump(), "workspace": str(old_workspace)}
    )
    # Only data verification ports are controlled. Git, source inventories, artifact
    # verifiers, adoption services, receipts and checkpoint predicates are real.
    monkeypatch.setattr(
        study,
        "VerifiedExecutionInputs",
        lambda *_: SimpleNamespace(snapshot=metadata[0], view=metadata[1]),
    )
    old = study.prepare(old_config, root / "old-study/preparation", root / "old-study/execution")
    task = old.tasks[0]
    old_root = Path(old.execution_root) / "V"
    base = old_root / "executions" / task.request.execution_identity / "baseline"
    resolved, evidence, schedule, signal_path, signal = signal_fixture(
        task, old_config, metadata[1], base
    )
    backtest_path, backtest = native_backtest_fixture(resolved, signal, base)
    atomic_write_bytes(
        old_root / "execution-requests" / f"{task.request.execution_identity}.json",
        task.request.canonical_bytes(),
    )
    producer = object.__new__(execution.QuantosResearchExecutionAdapter)
    producer.output_root = old_root
    producer.workspace = old_workspace
    producer._discovery_runtime_hash = "a" * 64
    producer._reserve_trial_identity(task.request)
    inputs = {
        "provisional_resolved_hash": resolved.model_copy(
            update={"pit_audit_evidence_hash": "0" * 64}
        ).content_hash,
        "schedule_hash": execution.research_schedule_hash((schedule,)),
        "evidence_override_hash": None,
    }

    def checkpoint(stage, outputs, values=inputs):
        producer._discovery_stage(task.request, stage, values, lambda: outputs, lambda x: x)
        return reference(
            next(
                (old_root / "execution-checkpoints" / task.request.execution_identity / stage).glob(
                    "sha256-*.json"
                )
            )
        )

    pit_checkpoint = checkpoint("baseline-pit", {"pit_evidence_hash": evidence.content_hash})
    signal_checkpoint = checkpoint("baseline-signal", {"signal_hash": signal.artifact_hash})
    backtest_checkpoint = checkpoint(
        "baseline",
        {"backtest_hash": backtest.result_hash},
        {**inputs, "resolved_hash": resolved.content_hash, "signal_hash": signal.artifact_hash},
    )

    def failed_workflow():
        raise RuntimeError("controlled unfinished recorder")

    with pytest.raises(RuntimeError):
        producer._discovery_stage(
            task.request,
            "workflow",
            {"signal_hash": signal.artifact_hash},
            failed_workflow,
            lambda x: x,
        )
    failure = next(
        (old_root / "execution-checkpoints" / task.request.execution_identity / "workflow").rglob(
            "completion.json"
        )
    )
    control = Path(old.execution_root).parent / "storage-control"
    guard_exit = control / "run-fixture/exit.json"
    put(guard_exit.with_name("policy.json"), {"scope": "controlled guard fixture"})
    policy_hash = sha256_file(guard_exit.with_name("policy.json"))
    put(
        guard_exit.with_name("prelaunch.json"),
        {"policy_hash": policy_hash, "stage": "deployment", "expected_new_bytes": 8 << 30},
    )
    put(
        old_root / "management/attempts/00000001/intent.json",
        {
            "request_hash": task.request.content_hash,
            "lease_prelaunch_hash": sha256_file(guard_exit.with_name("prelaunch.json")),
            "storage_policy_hash": policy_hash,
            "max_compute_units": 18,
            "expected_new_bytes": 8 << 30,
        },
    )
    put(
        guard_exit,
        dict(
            cleanup_verified=True,
            waitpid_observed=True,
            namespace_exit_observed=True,
            return_code=1,
            policy_hash=policy_hash,
        ),
    )
    put(control / "lease.lock", {"run": str(guard_exit.parent), "policy_hash": policy_hash})
    global_path = snapshot.parents[2] / "hosted-evidence/storage-control/lease.lock"
    put(global_path, {"scope": "fixture lock"})
    baseline = FieldStudyBaselineOrigin(
        label="V",
        request=reference(
            old_root / "execution-requests" / f"{task.request.execution_identity}.json"
        ),
        pit=reference(signal_path / "pit-evidence.json"),
        pit_checkpoint=pit_checkpoint,
        signal_path=str(signal_path),
        signal_hash=signal.artifact_hash,
        signal_checkpoint=signal_checkpoint,
        backtest_path=str(backtest_path),
        backtest_hash=backtest.result_hash,
        backtest_checkpoint=backtest_checkpoint,
        workflow_failure=reference(failure),
        guard_exit=reference(guard_exit),
    )
    config = FrozenFieldStudyConfiguration.model_validate(
        {
            **old_config.model_dump(),
            "study_id": "fixture-successor",
            "workspace": str(new_workspace),
            "code_commit_hash": new_commit,
        }
    )
    origin = FieldStudyRecoveryOrigin(
        predecessor_preparation=reference(Path(old.preparation_root) / "preparation.json"),
        reconstructed_workspace=str(rebuilt),
        successor_configuration_hash=config.content_hash,
        source_changes=(
            FieldStudySourceChange(
                path="src/quantos/application/field_study.py",
                original_hash=sha256_file(old_workspace / "src/quantos/application/field_study.py"),
                successor_hash=sha256_file(
                    new_workspace / "src/quantos/application/field_study.py"
                ),
            ),
        ),
        baselines=(baseline,),
    )
    prepared = study.prepare(
        config,
        root / "successor-study/preparation",
        root / "successor-study/execution",
        origin=origin,
    )
    real_load = study.load_preparation
    parsed = {}

    def load_once(path, digest):
        # Test-only reuse of already parsed immutable metadata. Every access still
        # checks the complete original bytes; no PIT or producer proof is cached.
        study.read_pinned(path, digest)
        key = (path, digest)
        if key not in parsed:
            parsed[key] = real_load(path, digest)
        return parsed[key]

    monkeypatch.setattr(study, "load_preparation", load_once)
    monkeypatch.setattr(execution, "verify_snapshot", lambda _: metadata[0])
    monkeypatch.setattr(execution, "verify_qlib_view", lambda _: metadata[1])
    f = SimpleNamespace(
        root=root,
        old=old,
        prepared=prepared,
        origin=origin,
        baseline=baseline,
        metadata=metadata,
        schedule=schedule,
        resolved=resolved,
        signal=signal,
        backtest=backtest,
        old_workspace=old_workspace,
        new_workspace=new_workspace,
    )

    def forbidden(*_a, **_kw):
        pytest.fail("no PIT/signal/backtest/model computation permitted")

    monkeypatch.setattr(execution.release, "build_compact_pit_evidence_collection", forbidden)
    monkeypatch.setattr(execution.FactorSignalArtifactBuilder, "build", forbidden)
    monkeypatch.setattr(execution.QlibBacktestService, "run", forbidden)
    monkeypatch.setattr(execution, "verify_compact_pit_evidence", forbidden)
    yield f
    monkeypatch.undo()


@pytest.fixture
def lineage(lineage_base, request):
    f = SimpleNamespace(**vars(lineage_base))
    mutable = [
        Path(f.origin.reconstructed_workspace) / "uv.lock",
        Path(f.baseline.workflow_failure.path),
        Path(f.baseline.guard_exit.path),
        *Path(f.baseline.signal_checkpoint.path).parent.rglob("completion.json"),
        *Path(f.old.execution_root).glob("V/management/attempts/*/intent.json"),
    ]
    originals = {p: p.read_bytes() for p in mutable}
    yield f
    history = f.root / "retained-fixtures" / request.node.name
    history.mkdir(parents=True, exist_ok=True)
    # These are synthetic test outputs, never scientific authority. Preserve each
    # case rather than deleting it; immutable large preparations remain shared.
    for name, path in [
        ("execution", Path(f.prepared.execution_root)),
        ("continuity", recovery.continuity_root(f.prepared.configuration)),
    ]:
        if path.exists():
            path.rename(history / name)
    for path, raw in originals.items():
        if path.read_bytes() != raw:
            saved = history / "mutated-inputs" / path.relative_to(f.root)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, saved)
            path.write_bytes(raw)


def adapter(f, **updates):
    prep = f.prepared
    config = prep.configuration
    task = prep.tasks[0]
    values = dict(
        campaign=task.campaign,
        budget=task.budget,
        family=task.family,
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
        output_root=Path(prep.execution_root) / "V",
        workspace=Path(config.workspace),
        field_study=config,
        discovery_stage_recovery=True,
        field_study_source_adoption=prep.source_adoption,
    )
    values.update(updates)
    return execution.QuantosResearchExecutionAdapter(**values)


def adopt(f):
    engine = adapter(f)
    request = f.prepared.tasks[0].request
    authoring = engine._authoring(request)
    variant = engine._discovery_variant(
        request,
        authoring,
        f.prepared.configuration.cost_policy,
        (f.schedule,),
        Path(f.prepared.execution_root) / "V/executions" / request.execution_identity / "baseline",
        {},
        None,
    )
    return engine, variant


def test_prepare_preserves_v1_and_freezes_recovery_without_execution(lineage):
    f = lineage
    assert isinstance(f.prepared, FieldStudyRecoveryPreparation)
    assert (
        study.load_preparation(
            Path(f.old.preparation_root) / "preparation.json", f.old.content_hash
        )
        == f.old
    )
    assert (
        study.load_preparation(
            Path(f.prepared.preparation_root) / "preparation.json", f.prepared.content_hash
        )
        == f.prepared
    )
    assert sum(t.compute_units for t in f.prepared.tasks) == 36
    assert len(f.prepared.source_adoption.transfers) == 2
    assert not Path(f.prepared.execution_root).exists()
    assert not recovery.continuity_root(f.prepared.configuration).exists()
    assert study.status(f.prepared)["scientific_verification"] == "NOT_PERFORMED_BY_STATUS"


def test_real_adoption_receipts_keep_native_bytes_and_reuse_successful_stages(lineage):
    f = lineage
    old_bytes = {
        p: Path(p).read_bytes()
        for p in [
            f.baseline.pit.path,
            f.baseline.signal_checkpoint.path,
            f.baseline.backtest_checkpoint.path,
            f.baseline.workflow_failure.path,
        ]
    }
    engine, first = adopt(f)
    assert (
        first.signal_hash != f.signal.artifact_hash
        and first.backtest_hash != f.backtest.result_hash
    )
    assert (first.signal_path / "signals.parquet").read_bytes() == (
        Path(f.baseline.signal_path) / "signals.parquet"
    ).read_bytes()
    hashes = engine._native_adoption_hashes(f.prepared.tasks[0].request)
    assert len(hashes) == 2
    _, second = adopt(f)
    assert first == second
    assert old_bytes == {p: Path(p).read_bytes() for p in old_bytes}
    for path in (engine.output_root / "native-adoptions").glob("*.json"):
        receipt = json.loads(path.read_bytes())
        assert receipt["new_scientific_execution"] is False
        assert receipt["parent_execution_status"] == "NOT_ASSERTED"


def test_workflow_remains_required_after_adopting_only_the_baseline(lineage, monkeypatch):
    f = lineage
    engine = adapter(f)
    seen = []
    monkeypatch.setattr(
        execution, "resolve_weekly_decision_schedules", lambda *_a, **_kw: (f.schedule,)
    )

    def workflow(*_a, **kw):
        seen.append(kw)
        raise RuntimeError("WORKFLOW_REQUIRED")

    monkeypatch.setattr(execution.QlibWorkflowResearchService, "run", workflow)
    with pytest.raises(RuntimeError, match="WORKFLOW_REQUIRED"):
        engine._execute_pipeline(f.prepared.tasks[0].request)
    assert len(seen) == 1 and seen[0]["execution_profile"] == "frozen-field-study/v1"
    assert not (engine.output_root / "outcome.json").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "checkout",
        "delta",
        "source",
        "request_hash",
        "checkpoint_hash",
        "completion",
        "pit",
        "workflow",
        "guard",
        "science",
        "successor_request",
    ],
)
def test_origin_rejects_wrong_sources_failed_proofs_and_scientific_changes(lineage, damage):
    f = lineage
    adoption = f.prepared.source_adoption
    if damage == "checkout":
        adoption = adoption.model_copy(
            update={
                "origin": f.origin.model_copy(
                    update={"reconstructed_workspace": str(f.new_workspace)}
                )
            }
        )
    elif damage == "delta":
        adoption = adoption.model_copy(
            update={"origin": f.origin.model_copy(update={"source_changes": ()})}
        )
    elif damage == "source":
        (Path(f.origin.reconstructed_workspace) / "uv.lock").write_text("changed")
    elif damage in ["request_hash", "checkpoint_hash", "pit"]:
        key = {"request_hash": "request", "checkpoint_hash": "signal_checkpoint", "pit": "pit"}[
            damage
        ]
        baseline = f.baseline.model_copy(
            update={key: getattr(f.baseline, key).model_copy(update={"sha256": "f" * 64})}
        )
        adoption = adoption.model_copy(
            update={"origin": f.origin.model_copy(update={"baselines": (baseline,)})}
        )
    elif damage == "completion":
        path = next(Path(f.baseline.signal_checkpoint.path).parent.rglob("completion.json"))
        v = json.loads(path.read_bytes())
        v["status"] = "FAILED"
        path.write_bytes(canonical_json_bytes(v))
    elif damage == "workflow":
        path = Path(f.baseline.workflow_failure.path)
        v = json.loads(path.read_bytes())
        v["status"] = "SUCCEEDED"
        path.write_bytes(canonical_json_bytes(v))
    elif damage == "guard":
        path = Path(f.baseline.guard_exit.path)
        v = json.loads(path.read_bytes())
        v["cleanup_verified"] = False
        path.write_bytes(canonical_json_bytes(v))
    elif damage == "science":
        config = f.prepared.configuration.model_copy(
            update={"snapshot_path": str(f.root / "different")}
        )
        origin = f.origin.model_copy(update={"successor_configuration_hash": config.content_hash})
        inventory = json.loads(
            (Path(f.prepared.preparation_root) / "source-inventory.json").read_bytes()
        )
        with pytest.raises(ValueError, match="scientific inputs"):
            recovery.verify_origin_sources(origin, config, inventory)
        return
    else:
        transfer = adoption.transfers[0].model_copy(update={"successor_request_hash": "f" * 64})
        adoption = adoption.model_copy(update={"transfers": (transfer, adoption.transfers[1])})
    with pytest.raises((ValueError, RuntimeError)):
        recovery.verify_source_adoption(adoption, f.prepared.configuration, f.prepared.tasks)


def test_supersession_retires_old_requests_and_refuses_duplicate_opportunities(lineage):
    f = lineage
    prep = f.prepared
    old = f.old
    task = prep.tasks[0]
    config = prep.configuration
    with pytest.raises(ValueError, match="supersession"):
        recovery.check_opportunity(
            config, task.request, Path(prep.execution_root) / "V", prep.source_adoption
        )
    recovery.check_opportunity(
        old.configuration, old.tasks[0].request, Path(old.execution_root) / "V", None, claim=True
    )
    study.supersede(prep)
    study.supersede(prep)
    recovery.check_opportunity(
        config, task.request, Path(prep.execution_root) / "V", prep.source_adoption, claim=True
    )
    with pytest.raises(ValueError, match="superseded"):
        recovery.check_opportunity(
            old.configuration, old.tasks[0].request, Path(old.execution_root) / "V", None
        )
    with pytest.raises(ValueError):
        recovery.check_opportunity(
            config, task.request, f.root / "duplicate/V", prep.source_adoption, claim=True
        )
    forged = prep.source_adoption.model_copy(
        update={"successor_execution_root": str(f.root / "another-execution")}
    )
    with pytest.raises(ValueError, match="different successor"):
        study.supersede(
            prep.model_copy(
                update={
                    "execution_root": str(f.root / "another-execution"),
                    "source_adoption": forged,
                }
            )
        )


def test_profile_boundaries_do_not_borrow_discovery_authority(lineage):
    f = lineage
    with pytest.raises(ValueError, match="another execution profile"):
        adapter(f, discovery_profile="singleton-full-chain/v1")
    with pytest.raises(ValueError, match="legacy/Discovery"):
        adapter(f, field_study=None)
    with pytest.raises(ValueError):
        adapter(f, field_study_source_adoption=None)


@pytest.mark.parametrize(
    "damage", ["missing", "bytes", "receipt_hash", "receipt_path", "origin_record"]
)
def test_reader_rejects_damaged_or_misplaced_native_receipts(lineage, damage):
    f = lineage
    engine, variant = adopt(f)
    paths = sorted((engine.output_root / "native-adoptions").glob("*.json"))
    if damage == "missing":
        paths[0].unlink()
    elif damage == "bytes":
        (variant.signal_path / "signals.parquet").write_bytes(b"changed")
    elif damage == "receipt_path":
        paths[0].rename(paths[0].with_name("sha256-" + "f" * 64 + ".json"))
    elif damage == "origin_record":
        raw = json.loads(paths[0].read_bytes())
        raw["source_adoption_record_hash"] = "f" * 64
        paths[0].write_bytes(canonical_json_bytes(raw))
    else:
        paths[0].write_bytes(paths[0].read_bytes() + b"\n")
    with pytest.raises((ValueError, RuntimeError)):
        recovery.verify_native_receipts(
            f.prepared.source_adoption,
            f.prepared.tasks[0].request,
            engine.output_root,
            require_complete=True,
        )


def test_prediction_origin_reader_requires_the_same_preparation_and_receipts(lineage):
    f = lineage
    engine, _ = adopt(f)
    study.supersede(f.prepared)
    root = Path(f.prepared.preparation_root)
    source = SimpleNamespace(
        research_policy=reference(root / "configuration.json"),
        source_capsule=reference(root / "source-capsule.json"),
        source_inventory=reference(root / "source-inventory.json"),
    )
    hashes = engine._native_adoption_hashes(f.prepared.tasks[0].request)
    assert (
        recovery.prediction_source_adoption(
            source, f.prepared.configuration, f.prepared.tasks[0].request, hashes
        )
        == f.prepared.source_adoption
    )
    with pytest.raises(ValueError, match="lost its adoption receipts"):
        recovery.prediction_source_adoption(
            source, f.prepared.configuration, f.prepared.tasks[0].request, ()
        )


def test_declared_scientific_implementation_change_is_rejected(lineage):
    f = lineage
    workspace = f.root / "science-change-checkout"
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "-q", str(f.new_workspace), str(workspace)], check=True
    )
    science = "src/quantos/research/qlib/pit_evidence.py"
    (workspace / science).write_text("changed_science = True\n")
    code = commit(workspace)
    config = f.prepared.configuration.model_copy(
        update={"workspace": str(workspace), "code_commit_hash": code}
    )
    files = git(workspace, "ls-files").splitlines()
    inventory = {
        "schema_version": "frozen-field-study-source-inventory/v1",
        "files": [
            {
                "path": name,
                "bytes_hash": sha256_file(workspace / name),
                "size_bytes": (workspace / name).stat().st_size,
            }
            for name in files
        ],
    }
    changes = [
        *f.origin.source_changes,
        FieldStudySourceChange(
            path=science,
            original_hash=sha256_file(f.old_workspace / science),
            successor_hash=sha256_file(workspace / science),
        ),
    ]
    origin = f.origin.model_copy(
        update={
            "successor_configuration_hash": config.content_hash,
            "source_changes": tuple(sorted(changes, key=lambda item: item.path)),
        }
    )
    with pytest.raises(ValueError, match="scientific implementation"):
        recovery.verify_origin_sources(origin, config, inventory)


def test_partial_supersession_does_not_launch_either_successor(lineage):
    f = lineage
    study.supersede(f.prepared)
    registry = recovery.continuity_root(f.prepared.configuration)
    path = registry / (
        f.prepared.source_adoption.transfers[1].opportunity_identity + ".supersession.json"
    )
    path.rename(path.with_suffix(".retained-incomplete"))
    for task in f.prepared.tasks:
        with pytest.raises(ValueError, match="complete supersession"):
            recovery.check_opportunity(
                f.prepared.configuration,
                task.request,
                Path(f.prepared.execution_root) / task.label,
                f.prepared.source_adoption,
            )


def test_missing_original_request_intent_cannot_justify_adoption(lineage):
    f = lineage
    path = next((Path(f.old.execution_root) / "V/management/attempts").glob("*/intent.json"))
    value = json.loads(path.read_bytes())
    value["request_hash"] = "f" * 64
    path.write_bytes(canonical_json_bytes(value))
    with pytest.raises(ValueError, match="actual wait/cleanup"):
        recovery.verify_source_adoption(
            f.prepared.source_adoption, f.prepared.configuration, f.prepared.tasks
        )


def test_cli_passes_origin_hash_and_separate_supersession(lineage, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "origin_cli_probe", ROOT / "scripts/frozen_field_study.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    f = lineage
    seen = []
    monkeypatch.setattr(module, "load_configuration", lambda *_: f.prepared.configuration)
    monkeypatch.setattr(
        module, "load_recovery_origin", lambda path, digest: seen.append((path, digest)) or f.origin
    )
    monkeypatch.setattr(module, "prepare", lambda *_a, **kw: seen.append(kw) or f.prepared)
    monkeypatch.setattr(module, "load_preparation", lambda *_: f.prepared)
    monkeypatch.setattr(module, "supersede", lambda value: seen.append(value))
    common = [
        "prepare",
        "--config",
        "input.json",
        "--config-sha256",
        "a" * 64,
        "--output-root",
        str(f.root / "unused"),
        "--execution-root",
        str(f.root / "unused-execution"),
    ]
    assert (
        module.main([*common, "--origin", "origin.json", "--origin-sha256", f.origin.content_hash])
        == 0
    )
    assert seen[0] == (Path("origin.json"), f.origin.content_hash) and seen[1]["origin"] == f.origin
    assert module.main([*common, "--origin", "origin.json"]) == 1
    assert (
        module.main(
            [
                "supersede",
                "--preparation",
                "prepared.json",
                "--preparation-sha256",
                f.prepared.content_hash,
            ]
        )
        == 0
    )
    assert seen[-1] == f.prepared


def test_retained_production_v1_preparation_keeps_its_exact_identity():
    path = Path(
        "/home/zjw/quant-research-os/artifacts/field-study/adjusted-volume-relative5-20261014-01/preparation/preparation.json"
    )
    if not path.exists():
        pytest.skip("retained preparation unavailable")
    digest = "6f7a22724a4b4fd9654f499637bca3c33a68929ed6e5cbb9d7ceeb09a0000fc6"
    old = study.load_preparation(path, digest)
    assert old.content_hash == digest
    assert tuple(t.compute_units for t in old.tasks) == (18, 18)


def retained_failure(f):
    from quantos.contracts.status import ReasonCode
    from quantos.research.qlib.universe import QlibResearchError

    engine, variant = adopt(f)
    task = f.prepared.tasks[0]

    def failed():
        raise QlibResearchError(ReasonCode.QLIB_EXECUTION_FAILED, "controlled undefined statistic")

    with pytest.raises(QlibResearchError):
        engine._discovery_stage(
            task.request,
            "workflow",
            {
                "resolved_hash": variant.resolved.content_hash,
                "signal_hash": variant.signal_hash,
                "research_policy_hash": f.prepared.configuration.research_policy.content_hash,
            },
            failed,
            lambda _: pytest.fail("no completed Workflow"),
            lambda: None,
        )
    failed_outcome = engine._failure_outcome(
        task.request,
        ReasonCode.QLIB_EXECUTION_FAILED,
        failure_kind="EXECUTION_FAILED",
        compute_seconds=18,
    )
    outcome = engine._publish_receipt(task.request, failed_outcome)
    root = engine.output_root
    atomic_write_bytes(root / "outcome.json", outcome.canonical_bytes())
    completion = next(root.glob("execution-checkpoints/*/workflow/*/attempts/*/completion.json"))
    prep = Path(f.prepared.preparation_root)
    config = f.prepared.configuration
    source = PredictionImportSource(
        request=reference(prep / "V/request.json"),
        outcome=reference(root / "outcome.json"),
        receipt=reference(
            root / "execution-record-artifacts" / f"sha256-{outcome.execution_artifact_hash}.json"
        ),
        resolved=reference(variant.signal_path / "resolved-experiment.json"),
        research_policy=reference(prep / "configuration.json"),
        workflow_reservation=reference(completion.with_name("reservation.json")),
        workflow_completion=reference(completion),
        management_exit=f.baseline.guard_exit,
        source_capsule=reference(prep / "source-capsule.json"),
        source_inventory=reference(prep / "source-inventory.json"),
        source_workspace=config.workspace,
        native_root=str(root / "native-placeholder"),
        model_split_sha256="a" * 64,
        snapshot_path=config.snapshot_path,
        qlib_view_path=config.qlib_view_path,
        signal_path=str(variant.signal_path),
        signal_hash=variant.signal_hash,
    )
    return engine, source, outcome


def test_retained_failed_outcome_keeps_its_original_receipt_and_adoption_chain(lineage):
    f = lineage
    engine, source, outcome = retained_failure(f)
    study.supersede(f.prepared)
    originals = {p: p.read_bytes() for p in (Path(source.outcome.path), Path(source.receipt.path))}
    assert not set(engine._native_adoption_hashes(f.prepared.tasks[0].request)) <= set(
        outcome.evidence_hashes
    )
    assert (
        recovery.prediction_source_adoption(
            source, f.prepared.configuration, f.prepared.tasks[0].request, outcome.evidence_hashes
        )
        == f.prepared.source_adoption
    )
    assert all(p.read_bytes() == raw for p, raw in originals.items())


@pytest.mark.parametrize(
    "damage",
    [
        "outcome_hash",
        "receipt_hash",
        "foreign_outcome_path",
        "success_completion",
        "foreign_reservation",
        "failure_evidence",
        "evidence_argument",
    ],
)
def test_retained_failure_exception_requires_actual_failure_authority(lineage, damage):
    f = lineage
    _, source, outcome = retained_failure(f)
    evidence = outcome.evidence_hashes
    if damage in {"outcome_hash", "receipt_hash"}:
        name = damage.removesuffix("_hash")
        source = source.model_copy(
            update={name: getattr(source, name).model_copy(update={"sha256": "0" * 64})}
        )
    elif damage == "foreign_outcome_path":
        path = Path(source.outcome.path).with_name("foreign-outcome.json")
        path.write_bytes(Path(source.outcome.path).read_bytes())
        source = source.model_copy(update={"outcome": reference(path)})
    elif damage == "success_completion":
        path = Path(source.workflow_completion.path)
        value = json.loads(path.read_bytes())
        value["status"] = "SUCCEEDED"
        path.write_bytes(canonical_json_bytes(value))
        source = source.model_copy(update={"workflow_completion": reference(path)})
    elif damage == "foreign_reservation":
        path = Path(source.workflow_reservation.path)
        value = json.loads(path.read_bytes())
        value["request_hash"] = "0" * 64
        path.write_bytes(canonical_json_bytes(value))
        source = source.model_copy(update={"workflow_reservation": reference(path)})
    elif damage == "failure_evidence":
        next((Path(f.prepared.execution_root) / "V/execution-failures").glob("*.json")).write_bytes(
            b"{}"
        )
    else:
        evidence = ()
    with pytest.raises(ValueError):
        recovery._verify_retained_workflow_failure(
            source, f.prepared.tasks[0].request, Path(f.prepared.execution_root) / "V", evidence
        )


def test_new_failed_outcome_retains_verified_native_adoption_hashes(lineage, monkeypatch):
    from quantos.contracts.status import ReasonCode
    from quantos.research.qlib.universe import QlibResearchError

    f = lineage
    engine, _ = adopt(f)
    study.supersede(f.prepared)

    def failed(_):
        raise QlibResearchError(
            ReasonCode.QLIB_EXECUTION_FAILED, "controlled failure after adoption"
        )

    monkeypatch.setattr(engine, "_execute_pipeline", failed)
    result = engine.execute(f.prepared.tasks[0].request)
    assert str(result.outcome) == "EXECUTION_FAILED"
    assert result.research_result_hash is None
    assert set(engine._native_adoption_hashes(f.prepared.tasks[0].request)) <= set(
        result.evidence_hashes
    )
