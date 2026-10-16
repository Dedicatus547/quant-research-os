"""Tiny native-table checks for frozen finite/null semantics; no model or backtest."""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from qlib.contrib.eva.alpha import calc_ic
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged

from quantos.application import discovery_prediction as prediction
from quantos.application import discovery_prediction_batch as batch_reporting
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.discovery_prediction import PredictionEvaluationProfile


@pytest.fixture
def native_probe(tmp_path):
    dates = tuple(date(2023, 1, 2) + timedelta(days=i) for i in range(4))
    instruments = ("SH600000", "SH600001", "SZ000001")
    index = pd.MultiIndex.from_product(
        (pd.to_datetime(dates), instruments), names=("datetime", "instrument")
    )
    pred = pd.DataFrame(
        {"score": [0.0, 1.0, 2.0, 1.0, 1.0, 1.0, 0.0, 1.0, 2.0, 0.0, 1.0, 2.0]}, index=index
    )
    labels = pd.DataFrame(
        {
            "LABEL0": [
                2.0,
                0.0,
                1.0,
                2.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                float("nan"),
                float("nan"),
                float("nan"),
            ]
        },
        index=index,
    )
    root = tmp_path / "native"
    (root / "sig_analysis").mkdir(parents=True)
    pred.to_pickle(root / "pred.pkl")
    labels.to_pickle(root / "label.pkl")
    ic, rank = calc_ic(pred.iloc[:, 0], labels.iloc[:, 0])
    ic.to_pickle(root / "sig_analysis/ic.pkl")
    rank.to_pickle(root / "sig_analysis/ric.pkl")
    digest = hashlib.sha256()
    for timestamp, instrument in index:
        digest.update(canonical_json_bytes((timestamp.date(), instrument)) + b"\n")
    return SimpleNamespace(
        root=root,
        dates=dates,
        pred=pred,
        labels=labels,
        digest=digest.hexdigest(),
        membership={i: ((dates[0], dates[-1]),) for i in instruments},
    )


def analyze(p):
    return prediction._native_analysis(p.root, p.dates, p.membership, len(p.pred), p.digest)


def test_exact_qlib_statistics_keep_complete_calendar_and_constant_nulls(native_probe):
    p = native_probe
    days, keys, omitted = analyze(p)
    assert len(days) == 4 and keys == p.digest
    assert [d.rank_ic.reason for d in days] == [
        "DEFINED_FINITE_PAIRS",
        "CONSTANT_PREDICTION",
        "CONSTANT_LABEL",
        "INSUFFICIENT_FINITE_PAIRS",
    ]
    assert days[0].rank_ic.value == pytest.approx(-0.5)
    assert all(d.rank_ic.value is None for d in days[1:])
    assert days[-1].label_nan == 3 and days[-1].paired_rows == 3 and days[-1].finite_pairs == 0
    expected = hashlib.sha256()
    for timestamp, instrument in p.pred.index[-3:]:
        expected.update(canonical_json_bytes((timestamp.date(), instrument)) + b"\n")
    assert omitted == expected.hexdigest()


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("pred_nan", "NATIVE_PREDICTION_NONFINITE"),
        ("label_inf", "NATIVE_LABEL_INFINITE"),
        ("keys", "PREDICTION_LABEL_KEY_MISMATCH"),
        ("universe", "NATIVE_KEY_OUTSIDE_PIT_UNIVERSE_OR_CALENDAR"),
        ("calendar", "NATIVE_PREDICTION_CALENDAR_INCOMPLETE"),
        ("split", "ACTUAL_DATASETH_TEST_INDEX_MISMATCH"),
        ("statistic", "NATIVE_STATISTICS_NOT_REPRODUCED"),
        ("stat_dates", "NATIVE_STATISTIC_CALENDAR_MISMATCH"),
    ],
)
def test_native_corruption_is_rejected_before_ranking(native_probe, damage, reason):
    p = native_probe
    if damage == "pred_nan":
        p.pred.iloc[0, 0] = float("nan")
        p.pred.to_pickle(p.root / "pred.pkl")
    elif damage == "label_inf":
        p.labels.iloc[0, 0] = float("inf")
        p.labels.to_pickle(p.root / "label.pkl")
    elif damage == "keys":
        p.labels.iloc[::-1].to_pickle(p.root / "label.pkl")
    elif damage == "universe":
        p.membership = {}
    elif damage == "calendar":
        p.dates += (p.dates[-1] + timedelta(days=1),)
    elif damage == "split":
        p.digest = "0" * 64
    elif damage == "statistic":
        series = pd.read_pickle(p.root / "sig_analysis/ric.pkl")
        series.iloc[0] = 0.7
        series.to_pickle(p.root / "sig_analysis/ric.pkl")
    else:
        series = pd.read_pickle(p.root / "sig_analysis/ric.pkl")
        series.iloc[:-1].to_pickle(p.root / "sig_analysis/ric.pkl")
    with pytest.raises(ValueError, match=reason):
        analyze(p)


@pytest.mark.parametrize(
    "value,reason",
    [
        (float("inf"), "NATIVE_STATISTIC_INFINITE"),
        (float("-inf"), "NATIVE_STATISTIC_INFINITE"),
        (float("nan"), "UNEXPLAINED_NONFINITE_STATISTIC"),
    ],
)
def test_defined_statistics_cannot_hide_nonfinite_values(value, reason):
    with pytest.raises(ValueError, match=reason):
        prediction._statistic(value, "DEFINED_FINITE_PAIRS")


def test_batch_report_preserves_shared_ownership_and_missing_nulls(staged, monkeypatch):
    f = staged
    reqs = {
        task.content_hash: f.service.task_request(task.content_hash) for task in f.batch.subtasks
    }
    bindings = f.service.evaluation_bindings
    profile = PredictionEvaluationProfile(
        verifier_identity_hash="a" * 64,
        execution_request_hashes=tuple(sorted(r.content_hash for r in reqs.values())),
        expected_dates=(date(2023, 1, 2),),
        snapshot_hash=f.batch.design.snapshot_hash,
        qlib_view_hash=f.batch.design.qlib_view_hash,
        research_policy_hash=f.batch.design.research_policy.content_hash,
        code_commit_hash=bindings.code_commit_hash,
        lockfile_hash=bindings.lockfile_hash,
        qlib_version=bindings.qlib_version,
        min_defined_fraction=1,
        min_common_days=1,
    )
    evidence = {
        r.content_hash: {
            "execution_request_hash": r.content_hash,
            "status": "SOURCE_MISSING",
            "reason": "SOURCE_MISSING",
            "primary_common_rank_ic_mean": None,
            "original_execution_outcome": "EXECUTION_FAILED",
        }
        for r in reqs.values()
    }
    first = next(iter(evidence.values()))
    first.update(status="COVERAGE_ADMITTED", primary_common_rank_ic_mean=-0.1)
    monkeypatch.setattr(
        batch_reporting,
        "compare_prediction_evidence",
        lambda *_a, **_kw: {"rows": list(evidence.values())},
    )
    report = batch_reporting.build_discovery_prediction_comparison(f.service, profile, {}, {})
    assert report["opportunity_denominator"] == 6
    assert report["occupied_opportunities"] == 3
    assert report["different_structure_denominator"] == len(f.batch.subtasks)
    assert len(report["rows"]) == 3
    assert any(r["primary_common_rank_ic_mean"] is None for r in report["rows"])
    assert report["original_validation_and_p14c"] == "UNCHANGED"
    rendered = batch_reporting.render_discovery_prediction_comparison(report)
    assert "Null is unavailable" in rendered and "EXECUTION_FAILED" in rendered
    with pytest.raises(ValueError, match="PREDICTION_COHORT_DIFFERS_FROM_FROZEN_SINGLETONS"):
        batch_reporting.build_discovery_prediction_comparison(
            f.service, profile.model_copy(update={"execution_request_hashes": ()}), {}, {}
        )
    with pytest.raises(ValueError, match="PREDICTION_PROFILE_DIFFERS_FROM_ACTUAL_EVALUATION"):
        batch_reporting.build_discovery_prediction_comparison(
            f.service, profile.model_copy(update={"snapshot_hash": "f" * 64}), {}, {}
        )


@pytest.fixture
def import_probe(staged, native_probe, monkeypatch):
    """Real pinned metadata/native tables; snapshot/PIT/split services are synthetic ports."""
    from quantos.application.autonomous_execution import (
        AutonomousExecutionReceipt,
        QuantosResearchExecutionAdapter,
        resolve_experiment,
    )
    from quantos.artifacts.store import sha256_file
    from quantos.contracts.autonomous import AutonomousExecutionResult
    from quantos.contracts.base import sha256_bytes
    from quantos.contracts.discovery_prediction import PredictionFileSource, PredictionImportSource
    from quantos.contracts.snapshot import DataQualityReport, DataQualityRule, QualityGateResult

    f, p = staged, native_probe
    request = f.request
    base = f.batch.design.authoring
    authoring = QuantosResearchExecutionAdapter._authoring(
        SimpleNamespace(base_authoring=base), request
    )
    resolved = resolve_experiment(
        authoring,
        snapshot_hash=request.snapshot_hash,
        qlib_view_hash=request.qlib_view_hash,
        qlib_version=request.qlib_version,
        qlib_view_spec_hash="a" * 64,
        pit_audit_evidence_hash="b" * 64,
        research_policy_hash=request.research_policy_hash,
        validation_policy_hash=request.validation_policy_hash,
        cost_policy_hash=request.cost_policy_hash,
        backtest_policy_hash=request.backtest_policy_hash,
        code_commit_hash=request.code_commit_hash,
        lockfile_hash=request.lockfile_hash,
    )
    outcome = AutonomousExecutionResult(
        request_hash=request.content_hash,
        outcome="EXECUTION_FAILED",
        execution_requested=True,
        compute_seconds=18,
        failure_reason_code="QLIB_EXECUTION_FAILED",
    )
    receipt = AutonomousExecutionReceipt(request=request, outcome=outcome)
    outcome = outcome.model_copy(
        update={
            "execution_artifact_hash": receipt.content_hash,
            "evidence_hashes": (receipt.content_hash,),
        }
    )
    root = p.root.parent / "import"
    root.mkdir()

    def pin(name, value):
        path = root / name
        raw = (
            value.canonical_bytes()
            if hasattr(value, "canonical_bytes")
            else canonical_json_bytes(value)
        )
        path.write_bytes(raw)
        return PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))

    runtime = prediction.capture_runtime_fingerprint().content_hash
    inputs = {
        "resolved_hash": resolved.content_hash,
        "research_policy_hash": request.research_policy_hash,
        "signal_hash": "c" * 64,
    }
    inputs_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "request_hash": request.content_hash,
                "runtime_fingerprint_hash": runtime,
                "stage": "workflow",
                "inputs": inputs,
                "recovery_policy": "discovery-stage-original-verification/v1",
            }
        )
    )
    reservation = {
        "schema_version": "discovery-stage-reservation/v1",
        "request_hash": request.content_hash,
        "stage": "workflow",
        "inputs": inputs,
        "inputs_hash": inputs_hash,
        "runtime_fingerprint_hash": runtime,
    }
    completion = {
        "schema_version": "discovery-stage-attempt-completion/v1",
        "inputs_hash": inputs_hash,
        "status": "FAILED",
    }
    snapshot, view = root / "snapshot", root / "view"
    snapshot.mkdir()
    (view / "calendars").mkdir(parents=True)
    (view / "calendars/day.txt").write_text("\n".join(map(str, p.dates)))
    quality = DataQualityReport(
        policy_hash="a" * 64,
        passed=True,
        gates=(
            QualityGateResult(
                rule=DataQualityRule.SCHEMA,
                passed=True,
                checked_rows=0,
                detail="synthetic metadata port only",
            ),
        ),
    )
    (snapshot / "quality-report.json").write_bytes(quality.canonical_bytes())
    target = p.root.with_name("sha256-" + request.execution_identity)
    p.root.rename(target)
    p.root = target
    split = target / "model-data-splits.json"
    split.write_bytes(b"synthetic split service port")
    source = PredictionImportSource(
        request=pin("request.json", request),
        outcome=pin("outcome.json", outcome),
        receipt=pin("receipt.json", receipt),
        resolved=pin("resolved.json", resolved),
        research_policy=pin("policy.json", f.batch.design.research_policy),
        workflow_reservation=pin("reservation.json", reservation),
        workflow_completion=pin("completion.json", completion),
        management_exit=pin("exit.json", {"return_code": 1}),
        source_capsule=pin("capsule.json", {}),
        source_inventory=pin("inventory.json", {}),
        source_workspace=str(root),
        native_root=str(target),
        model_split_sha256=sha256_file(split),
        snapshot_path=str(snapshot),
        qlib_view_path=str(view),
        signal_path=str(root / "signal"),
        signal_hash="c" * 64,
    )
    verifier = sha256_bytes(canonical_json_bytes(prediction.prediction_verifier_identity()))
    profile = PredictionEvaluationProfile(
        verifier_identity_hash=verifier,
        execution_request_hashes=(request.content_hash,),
        expected_dates=p.dates,
        snapshot_hash=request.snapshot_hash,
        qlib_view_hash=request.qlib_view_hash,
        research_policy_hash=request.research_policy_hash,
        code_commit_hash=request.code_commit_hash,
        lockfile_hash=request.lockfile_hash,
        qlib_version=request.qlib_version,
        min_defined_fraction=0.9,
        min_common_days=3,
    )
    snapshot_result = SimpleNamespace(
        snapshot_hash=request.snapshot_hash, quality_report_hash=quality.content_hash
    )
    view_result = SimpleNamespace(
        view_hash=request.qlib_view_hash,
        source_snapshot_hash=request.snapshot_hash,
        view_spec_hash=resolved.qlib_view_spec_hash,
        health_check_passed=True,
    )
    monkeypatch.setattr(prediction, "_verify_source_code", lambda *_: None)
    monkeypatch.setattr(prediction, "verify_snapshot", lambda _: snapshot_result)
    monkeypatch.setattr(prediction, "verify_qlib_view", lambda _: view_result)
    monkeypatch.setattr(
        prediction, "_verify_pit", lambda *_a, **_kw: resolved.pit_audit_evidence_hash
    )
    files = tuple(
        SimpleNamespace(
            logical_path=name,
            size_bytes=(target / name).stat().st_size,
            sha256=sha256_file(target / name),
        )
        for name in ("pred.pkl", "label.pkl", "sig_analysis/ic.pkl", "sig_analysis/ric.pkl")
    )
    monkeypatch.setattr(
        prediction,
        "verify_model_data_split",
        lambda *_a, **_kw: SimpleNamespace(
            content_hash="d" * 64,
            source_files=files,
            test=SimpleNamespace(sample_rows=len(p.pred), sample_index_hash=p.digest),
        ),
    )
    monkeypatch.setattr(
        prediction, "resolve_historical_universe_spans", lambda *_a, **_kw: p.membership
    )
    return SimpleNamespace(
        source=source,
        profile=profile,
        base=base,
        native=p,
        snapshot=snapshot_result,
        view=view_result,
    )


def test_export_failure_import_keeps_immutable_parent_and_raw_null_denominator(import_probe):
    p = import_probe
    before = {
        r.path: Path(r.path).read_bytes()
        for r in (p.source.outcome, p.source.receipt, p.source.request)
    }
    evidence = prediction.build_prediction_evidence(p.source, p.profile, base_authoring=p.base)
    assert evidence.original_execution_outcome == "EXECUTION_FAILED"
    assert evidence.original_failure_reason == "QLIB_EXECUTION_FAILED"
    assert evidence.original_stage_status == "FAILED"
    assert (
        evidence.original_research_result_hash is None
        and evidence.original_validation_report_hash is None
    )
    assert (
        evidence.raw_pair_count == 12
        and evidence.finite_pair_count == 9
        and evidence.omitted_nan_label_count == 3
    )
    assert (
        len(evidence.daily) == 4 and sum(d.rank_ic.value is not None for d in evidence.daily) == 1
    )
    assert before == {path: Path(path).read_bytes() for path in before}


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("data", "DATA_IDENTITY_OR_QUALITY_REJECTED"),
        ("pit", "PIT_HARD_REJECTION"),
        ("workflow", "ACTUAL_WORKFLOW_STAGE_BINDING_MISMATCH"),
        ("base", "BASE_AUTHORING_REQUIRED"),
        ("split", "MODEL_SPLIT_HASH_MISMATCH"),
    ],
)
def test_import_failures_cannot_be_converted_to_missing_statistics(
    import_probe, monkeypatch, damage, reason
):
    p = import_probe
    if damage == "data":
        p.view.health_check_passed = False
    elif damage == "pit":

        def reject(*_a, **_kw):
            raise ValueError("PIT_HARD_REJECTION")

        monkeypatch.setattr(prediction, "_verify_pit", reject)
    elif damage == "workflow":
        source = p.source.workflow_completion
        Path(source.path).write_bytes(b"{}")
        from quantos.artifacts.store import sha256_file

        p.source = p.source.model_copy(
            update={
                "workflow_completion": source.model_copy(
                    update={"sha256": sha256_file(Path(source.path))}
                )
            }
        )
    elif damage == "base":
        p.base = None
    else:
        (p.native.root / "model-data-splits.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match=reason):
        prediction.build_prediction_evidence(p.source, p.profile, base_authoring=p.base)


def test_publication_rebuild_and_replay_preserve_original_failures(import_probe, staged):
    p = import_probe
    root = staged.service.workspace / "published-predictions"
    target = prediction.publish_prediction_evidence(
        p.source, p.profile, root, base_authoring=p.base
    )
    expected = target.name.removeprefix("sha256-")
    assert (
        prediction.publish_prediction_evidence(p.source, p.profile, root, base_authoring=p.base)
        == target
    )
    verified = prediction.verify_prediction_evidence(
        target, expected_hash=expected, source=p.source, profile=p.profile, base_authoring=p.base
    )
    assert (
        verified.original_execution_outcome == "EXECUTION_FAILED"
        and verified.original_validation_report_hash is None
    )
    report = prediction.publish_prediction_cohort(
        p.profile,
        {p.source.request.sha256: p.source},
        base_authorings={p.source.request.sha256: p.base},
        output_root=root,
    )
    assert report["request_denominator"] == 1 and report["missing_or_rejected_requests"] == 1
    assert report["rows"][0]["status"] == "COVERAGE_REJECTED"
    assert report["rows"][0]["primary_common_rank_ic_mean"] is None
    (target / "evidence.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="SUCCESSOR_EVIDENCE_NOT_REPRODUCED"):
        prediction.verify_prediction_evidence(
            target,
            expected_hash=expected,
            source=p.source,
            profile=p.profile,
            base_authoring=p.base,
        )


@pytest.mark.parametrize("damage", [None, "wait", "exit", "pid", "rss", "cpu", "shape", "encoding"])
def test_retained_observer_accepts_only_exact_original_exit_protocol(tmp_path, damage):
    import json

    from quantos.contracts.base import sha256_bytes
    from quantos.contracts.discovery_prediction import PredictionFileSource

    value = {
        "schema_version": "field-study-cli-process-exit/v1",
        "actual_return_code": 1,
        "return_code": 1,
        "wait_observed": True,
        "pid": 100,
        "wall_seconds": 1.25,
        "child_user_cpu_seconds": 0.5,
        "child_system_cpu_seconds": 0.1,
        "child_peak_rss_kib": 100,
        "scope": (
            "Direct original CLI and waited children; not host peak; "
            "supervisor cleanup recorded separately."
        ),
    }
    if damage == "wait":
        value["wait_observed"] = False
    elif damage == "exit":
        value["actual_return_code"] = True
    elif damage == "pid":
        value["pid"] = 0
    elif damage == "rss":
        value["child_peak_rss_kib"] = -1
    elif damage == "cpu":
        value["child_user_cpu_seconds"] = True
    elif damage == "shape":
        value["unexpected"] = 1
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if damage == "encoding":
        raw = json.dumps(value, indent=1).encode()
    path = tmp_path / "observer.json"
    path.write_bytes(raw)
    ref = PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))
    with pytest.raises(ValueError, match="SOURCE_METADATA_NOT_CANONICAL"):
        prediction._raw_json(ref)
    if damage is None:
        assert prediction._raw_json(ref, field_study_observer=True) == value
    else:
        with pytest.raises(ValueError, match="SOURCE_METADATA_NOT_CANONICAL"):
            prediction._raw_json(ref, field_study_observer=True)


@pytest.mark.parametrize("damage", [None, "capsule", "inventory", "duplicate", "bytes"])
def test_source_inventory_binds_real_clean_checkout(tmp_path, damage):
    import subprocess

    from quantos.artifacts.store import sha256_file
    from quantos.contracts.base import sha256_bytes
    from quantos.contracts.discovery_prediction import PredictionFileSource

    workspace = tmp_path / "source"
    workspace.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(workspace), *args], text=True).strip()

    git("init", "-q")
    (workspace / "uv.lock").write_bytes(b"synthetic lock\n")
    (workspace / "source.py").write_bytes(b"fixture = True\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = git("rev-parse", "HEAD")
    files = [
        {
            "path": name,
            "size_bytes": (workspace / name).stat().st_size,
            "bytes_hash": sha256_file(workspace / name),
        }
        for name in ("source.py", "uv.lock")
    ]
    if damage == "inventory":
        files = []
    elif damage == "duplicate":
        files += files[:1]
    elif damage == "bytes":
        files[0]["bytes_hash"] = "0" * 64

    def pin(name, value):
        raw = canonical_json_bytes(value)
        path = tmp_path / name
        path.write_bytes(raw)
        return PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))

    inventory = pin("inventory.json", {"files": files})
    lock = sha256_file(workspace / "uv.lock")
    capsule = pin(
        "capsule.json",
        {
            "actual_commit": commit if damage != "capsule" else "0" * 40,
            "lockfile_hash": lock,
            "source_inventory_hash": inventory.sha256,
            "workspace": str(workspace),
        },
    )
    source = SimpleNamespace(
        source_capsule=capsule, source_inventory=inventory, source_workspace=str(workspace)
    )
    request = SimpleNamespace(code_commit_hash=commit, lockfile_hash=lock)
    if damage is None:
        prediction._verify_source_code(source, request)
    else:
        with pytest.raises(ValueError, match="ORIGINAL_SOURCE_"):
            prediction._verify_source_code(source, request)
