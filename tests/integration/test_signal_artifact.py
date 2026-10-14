from __future__ import annotations

import importlib
import json
from datetime import datetime
from pathlib import Path
from struct import pack, unpack
from subprocess import CompletedProcess
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from quantos.application import resolve_experiment
from quantos.contracts.pit import OperatorDelayPolicy, SafeQlibExpressionSpec
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.contracts.research_execution import PITAuditEvidenceItem
from quantos.contracts.status import ReasonCode
from quantos.contracts.temporal import DecisionSchedule
from quantos.data import qlib_view
from quantos.data.qlib_view import QlibViewBuilder
from quantos.data.snapshot import SyntheticSnapshotBuilder
from quantos.integrations.qlib import QLIB_COMMIT, QLIB_VERSION, OfficialQlibTools
from quantos.research.qlib import (
    FactorSignalArtifactBuilder,
    QlibResearchError,
    build_compact_pit_evidence_collection,
    build_pit_evidence_collection,
    verify_compact_pit_evidence,
    verify_signal_artifact,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SIGNAL_MODULE = importlib.import_module("quantos.research.qlib.signal")


def _fake_tools(tmp_path: Path) -> OfficialQlibTools:
    source = tmp_path / "qlib-source"
    source.mkdir()
    dump = source / "dump_bin.py"
    health = source / "check_data_health.py"
    dump.touch()
    health.touch()
    return OfficialQlibTools(
        source,
        dump,
        health,
        QLIB_COMMIT,
        QLIB_VERSION,
        "a" * 64,
        "b" * 64,
    )


def _build_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    official = _fake_tools(tmp_path)
    monkeypatch.setattr(qlib_view, "verify_official_qlib_tools", lambda _path: official)

    def fake_run(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if "dump_all" in command:
            qlib_root = Path(command[command.index("--qlib_dir") + 1])
            (qlib_root / "calendars").mkdir(parents=True)
            (qlib_root / "calendars" / "day.txt").write_text(
                "2024-01-02\n2024-01-03\n2024-01-04\n2024-01-05\n",
                encoding="utf-8",
            )
            return CompletedProcess(command, 0, stdout="dumped")
        if "check_data" in command:
            return CompletedProcess(command, 0, stdout="healthy")
        if "-c" in command:
            values = {
                key: unpack("<f", pack("<f", value))[0]
                for key, value in {
                    "SZ000001": 12.1,
                    "SH000300": 3320.0,
                    "SH600000": 10.2,
                }.items()
            }
            requests = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            actual = {item["qlib_id"]: values[item["qlib_id"]] for item in requests}
            return CompletedProcess(
                command, 0, stdout=f"QUANTOS_SAMPLES={json.dumps(actual, sort_keys=True)}\n"
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    view = QlibViewBuilder().build(snapshot.path, tmp_path / "views", official.source_root)
    return snapshot, view


def _schedule() -> DecisionSchedule:
    return DecisionSchedule(
        signal_time=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
        signal_available_at=datetime(2024, 1, 5, 16, 1, tzinfo=SHANGHAI),
        decision_time=datetime(2024, 1, 5, 16, 10, tzinfo=SHANGHAI),
        execution_time=datetime(2024, 1, 8, 9, 30, tzinfo=SHANGHAI),
    )


def _authoring() -> ExperimentAuthoringSpec:
    return ExperimentAuthoringSpec.model_validate(
        {
            "experiment_id": "synthetic-signal-v1",
            "evaluation_start": "2024-01-02",
            "evaluation_end": "2024-01-05",
            "expression": {
                "expression_id": "momentum_2d",
                "operator": "return",
                "field": "adjusted_close",
                "window": 2,
            },
            "strategy": {
                "universe_index": "000300.SH",
                "top_k": 1,
            },
        }
    )


def _evidence_and_resolved(snapshot: object, view: object) -> tuple[object, object]:
    provisional = resolve_experiment(
        _authoring(),
        snapshot_hash=snapshot.manifest.snapshot_hash,
        qlib_view_hash=view.manifest.view_hash,
        qlib_version=view.manifest.qlib_version,
        qlib_view_spec_hash=view.manifest.view_spec_hash,
        pit_audit_evidence_hash="0" * 64,
        research_policy_hash="1" * 64,
        validation_policy_hash="2" * 64,
        cost_policy_hash="3" * 64,
        backtest_policy_hash="6" * 64,
        code_commit_hash="4" * 40,
        lockfile_hash="5" * 64,
    )
    evidence = build_pit_evidence_collection(
        snapshot.path,
        view.path,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=provisional.expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="qlib-return-delay-60s/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=(_schedule(),),
    )
    resolved = provisional.model_copy(update={"pit_audit_evidence_hash": evidence.content_hash})
    return evidence, resolved


def test_factor_signal_artifact_is_pit_bound_immutable_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    evidence, resolved = _evidence_and_resolved(snapshot, view)
    monkeypatch.setattr(
        SIGNAL_MODULE,
        "_execute_expression",
        lambda *_args, **_kwargs: {"SZ000001": 0.025},
    )
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)

    builder = FactorSignalArtifactBuilder()
    first = builder.build(resolved, evidence, view.path, tmp_path / "signals")
    repeated = builder.build(resolved, evidence, view.path, tmp_path / "signals")

    assert first.path == repeated.path
    assert first.manifest == verify_signal_artifact(first.path)
    assert first.manifest.pit_evidence_hash == evidence.content_hash
    rows = pq.read_table(first.path / "signals.parquet").to_pylist()
    assert rows == [
        {
            "instrument_id": "000001.SZ",
            "signal_time": _schedule().signal_time,
            "decision_time": _schedule().decision_time,
            "available_at": datetime(2024, 1, 5, 15, 31, tzinfo=SHANGHAI),
            "score": 0.025,
            "score_valid": True,
            "tradable": True,
        }
    ]

    (first.path / "signals.parquet").write_bytes(b"tampered")
    with pytest.raises(QlibResearchError) as corrupted:
        verify_signal_artifact(first.path)
    assert corrupted.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_dsl_v2_runs_through_pit_signal_and_reproducibility_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    _, provisional = _evidence_and_resolved(snapshot, view)
    expression = SafeQlibExpressionSpec.model_validate(
        {
            "schema_version": "safe-qlib-expression/v2",
            "expression_id": "v2_admitted_operator_chain",
            "nodes": [
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "price",
                    "operator": "field",
                    "field_name": "adjusted_close",
                },
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "delta",
                    "operator": "delta",
                    "inputs": ["price"],
                    "window": 2,
                },
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "sum",
                    "operator": "rolling_sum",
                    "inputs": ["delta"],
                    "window": 1,
                },
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "min",
                    "operator": "rolling_min",
                    "inputs": ["sum"],
                    "window": 1,
                },
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "max",
                    "operator": "rolling_max",
                    "inputs": ["min"],
                    "window": 1,
                },
                {
                    "schema_version": "safe-expression-node/v1",
                    "node_id": "output",
                    "operator": "abs",
                    "inputs": ["max"],
                },
            ],
            "output_node_id": "output",
        }
    )
    provisional = provisional.model_copy(update={"expression": expression})
    delays = (
        OperatorDelayPolicy(policy_id="qlib-abs-delay/v1", operator="abs"),
        OperatorDelayPolicy(policy_id="qlib-delta-delay/v1", operator="delta"),
        OperatorDelayPolicy(policy_id="qlib-max-delay/v1", operator="rolling_max"),
        OperatorDelayPolicy(policy_id="qlib-min-delay/v1", operator="rolling_min"),
        OperatorDelayPolicy(policy_id="qlib-sum-delay/v1", operator="rolling_sum"),
    )
    evidence = build_pit_evidence_collection(
        snapshot.path,
        view.path,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=expression,
        operator_delays=delays,
        schedules=(_schedule(),),
    )
    resolved = provisional.model_copy(update={"pit_audit_evidence_hash": evidence.content_hash})
    monkeypatch.setattr(
        SIGNAL_MODULE,
        "_execute_expression",
        lambda *_args, **_kwargs: {"SZ000001": 0.025},
    )
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)

    first = FactorSignalArtifactBuilder().build(
        resolved, evidence, view.path, tmp_path / "signals-v2-a"
    )
    second = FactorSignalArtifactBuilder().build(
        resolved, evidence, view.path, tmp_path / "signals-v2-b"
    )

    assert first.manifest.artifact_hash == second.manifest.artifact_hash
    assert first.manifest.signal_content_hash == second.manifest.signal_content_hash
    assert verify_signal_artifact(first.path) == first.manifest
    assert verify_signal_artifact(second.path) == second.manifest


def test_compact_pit_evidence_recomputes_and_builds_the_same_signal_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    _, provisional = _evidence_and_resolved(snapshot, view)
    compact = build_compact_pit_evidence_collection(
        snapshot.path,
        view.path,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index=provisional.strategy.universe_index,
        expression=provisional.expression,
        operator_delays=(
            OperatorDelayPolicy(
                policy_id="qlib-return-delay-60s/v1",
                operator="return",
                delay_seconds=60,
            ),
        ),
        schedules=(_schedule(),),
    )
    verify_compact_pit_evidence(compact, snapshot.path, view.path)
    resolved = provisional.model_copy(update={"pit_audit_evidence_hash": compact.content_hash})
    monkeypatch.setattr(
        SIGNAL_MODULE,
        "_execute_expression",
        lambda *_args, **_kwargs: {"SZ000001": 0.025},
    )
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)

    result = FactorSignalArtifactBuilder().build(
        resolved, compact, view.path, tmp_path / "compact-signals"
    )

    assert verify_signal_artifact(result.path) == result.manifest
    assert compact.bundles[0].members == ("000001.SZ",)
    assert all(item.missing_row_count == 0 for item in compact.bundles[0].source_sets)
    assert pq.read_table(result.path / "signals.parquet").num_rows == 1


def test_signal_build_retains_invalid_qlib_output_and_rejects_unbound_pit_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    evidence, resolved = _evidence_and_resolved(snapshot, view)
    monkeypatch.setattr(SIGNAL_MODULE, "_execute_expression", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)

    result = FactorSignalArtifactBuilder().build(
        resolved, evidence, view.path, tmp_path / "signals"
    )
    rows = pq.read_table(result.path / "signals.parquet").to_pylist()
    assert rows[0]["score"] is None
    assert rows[0]["score_valid"] is False

    item = evidence.bundles[0].items[0]
    changed_request = item.request.model_copy(update={"instrument_id": "600000.SH"})
    with pytest.raises(ValidationError, match="does not bind"):
        PITAuditEvidenceItem(request=changed_request, report=item.report)


def _volume_expression(*, window: int = 2, lag: int = 0) -> SafeQlibExpressionSpec:
    # The tiny four-session fixture uses the same DAG with a bounded two-day window.
    return SafeQlibExpressionSpec.model_validate(
        {
            "expression_id": "volume_relative",
            "nodes": [
                {"node_id": "volume", "operator": "field", "field_name": "adjusted_volume"},
                {
                    "node_id": "mean",
                    "operator": "rolling_mean",
                    "inputs": ["volume"],
                    "window": window,
                },
                {"node_id": "ratio", "operator": "divide", "inputs": ["volume", "mean"]},
            ],
            "output_node_id": "ratio",
            "input_lag_trading_days": lag,
        }
    )


def _volume_delays(*, seconds: int = 60) -> tuple[OperatorDelayPolicy, ...]:
    return tuple(
        OperatorDelayPolicy(
            policy_id=f"fixture-{operator}-{seconds}s/v1", operator=operator, delay_seconds=seconds
        )
        for operator in ("rolling_mean", "divide")
    )


def _compact_volume(snapshot: object, view: object, **changes: object) -> object:
    values = dict(
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        expected_view_hash=view.manifest.view_hash,
        universe_index="000300.SH",
        expression=_volume_expression(),
        operator_delays=_volume_delays(),
        schedules=(_schedule(),),
        execution_profile="frozen-field-study/v1",
    )
    values.update(changes)
    return build_compact_pit_evidence_collection(snapshot.path, view.path, **values)


def test_field_study_pit_roundtrip_source_mapping_and_signal_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantos.application.pit import PITAuditService
    from quantos.contracts.research_execution import CanonicalPITAuditRequestV2
    from quantos.contracts.status import ValidationVerdict
    from quantos.research.qlib.pit_evidence import (
        load_pit_artifact_evidence,
        subset_compact_pit_evidence,
    )

    snapshot, view = _build_view(tmp_path, monkeypatch)
    compact = _compact_volume(snapshot, view)
    assert compact.schema_version == "pit-cross-section-evidence-collection/v3"
    sources = compact.bundles[0].source_sets
    assert [(s.table_name, s.source_field_name) for s in sources] == [
        ("adjustment_factors", "adjustment_factor"),
        ("bars", "volume_shares"),
    ]
    request = CanonicalPITAuditRequestV2(
        snapshot_hash=snapshot.manifest.snapshot_hash,
        instrument_id="000001.SZ",
        universe_index="000300.SH",
        expression=compact.expression,
        operator_delays=compact.operator_delays,
        schedule=_schedule(),
    )
    report = PITAuditService().audit_snapshot(request, snapshot.path)
    assert report.verdict is ValidationVerdict.PASS
    assert report.canonical_request_hash == request.content_hash
    assert report.output_temporal.available_at == compact.bundles[0].output_temporal.available_at
    assert report.limitations == ("SINGLE_SOURCE_NON_VINTAGE",)
    verify_compact_pit_evidence(compact, snapshot.path, view.path)
    assert subset_compact_pit_evidence(compact, (_schedule(),)).content_hash == compact.content_hash
    payload = tmp_path / "pit-v3.json"
    payload.write_bytes(compact.canonical_bytes())
    assert load_pit_artifact_evidence(payload).content_hash == compact.content_hash

    _, old_resolved = _evidence_and_resolved(snapshot, view)
    resolved = old_resolved.model_copy(
        update={"expression": compact.expression, "pit_audit_evidence_hash": compact.content_hash}
    )
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        SIGNAL_MODULE, "_execute_expression", lambda *_args, **_kwargs: {"SZ000001": 1.25}
    )
    builder = FactorSignalArtifactBuilder()
    with pytest.raises(QlibResearchError, match="profile"):
        builder.build(resolved, compact, view.path, tmp_path / "legacy")
    result = builder.build(
        resolved,
        compact,
        view.path,
        tmp_path / "volume-signals",
        execution_profile="frozen-field-study/v1",
    )
    assert verify_signal_artifact(result.path) == result.manifest
    assert (
        json.loads((result.path / "expression-translation.json").read_bytes())["output_expression"]
        == "($volume/Mean($volume,2))"
    )
    assert pq.read_table(result.path / "signals.parquet").to_pylist()[0]["score"] == 1.25
    for raw in ([], {"schema_version": "pit-cross-section-evidence-collection/v999"}):
        payload.write_text(json.dumps(raw))
        with pytest.raises(ValueError):
            load_pit_artifact_evidence(payload)

    # Missing mappings, changed row hashes and version relabelling cannot become proofs.
    raw = compact.model_dump(mode="json")
    raw["bundles"][0]["source_sets"] = raw["bundles"][0]["source_sets"][:1]
    with pytest.raises(ValidationError, match="mapping is incomplete"):
        type(compact).model_validate(raw)
    raw = compact.model_dump(mode="json")
    raw["bundles"][0]["source_sets"][1]["source_field_name"] = "close"
    with pytest.raises(ValidationError, match="mapping is invalid"):
        type(compact).model_validate(raw)
    raw = compact.model_dump(mode="json")
    raw["bundles"][0]["source_sets"][0]["maximum_temporal"]["available_at"] = "2024-01-05T08:05:00Z"
    raw["bundles"][0]["source_sets"][0]["maximum_temporal"]["observed_at"] = "2024-01-05T08:05:00Z"
    with pytest.raises(ValidationError, match="unavailable at signal"):
        type(compact).model_validate(raw)
    raw = compact.model_dump(mode="json")
    raw["bundles"][0]["source_sets"][1]["row_set_hash"] = "a" * 64
    changed = type(compact).model_validate(raw)
    with pytest.raises(QlibResearchError, match="cannot be reproduced"):
        verify_compact_pit_evidence(changed, snapshot.path, view.path)
    raw = compact.model_dump(mode="json")
    raw["schema_version"] = "pit-cross-section-evidence-collection/v2"
    payload.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load_pit_artifact_evidence(payload)


@pytest.mark.parametrize(
    "case",
    [
        "late-bars",
        "late-factor",
        "missing-key",
        "duplicate-key",
        "wrong-date",
        "missing-field",
        "unknown-factor",
    ],
)
def test_field_study_rejects_malformed_canonical_read_projections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import pyarrow as pa

    from quantos.application.pit import PITAuditService
    from quantos.contracts.research_execution import CanonicalPITAuditRequestV2
    from quantos.contracts.status import ValidationVerdict

    snapshot, view = _build_view(tmp_path, monkeypatch)
    # Controlled reader fault injection after genuine small-file hash verification.
    # This tests rejection only; these projected rows never become canonical authority.
    original_read = pq.read_table
    target = "bars" if case == "late-bars" else "adjustment_factors"

    def fault_read(path: object, *args: object, **kwargs: object) -> pa.Table:
        table = original_read(path, *args, **kwargs)
        if Path(path).name != f"{target}.parquet":
            return table
        if case == "missing-field":
            return table.drop(["adjustment_factor"])
        rows = table.to_pylist()
        position = next(
            i
            for i, row in enumerate(rows)
            if row["instrument_id"] == "000001.SZ" and str(row["trade_date"]) == "2024-01-05"
        )
        if case.startswith("late"):
            for key in ("known_at", "available_at", "observed_at"):
                rows[position][key] = datetime(2024, 1, 5, 16, 5, tzinfo=SHANGHAI)
        elif case == "missing-key":
            del rows[position]
        elif case == "duplicate-key":
            rows.append(rows[position])
        elif case == "wrong-date":
            rows[position]["trade_date"] = _schedule().execution_time.date()
        elif case == "unknown-factor":
            rows[position]["availability_basis"] = "UNKNOWN"
        return pa.Table.from_pylist(rows, schema=table.schema)

    monkeypatch.setattr(pq, "read_table", fault_read)
    with pytest.raises((QlibResearchError, ValueError)):
        _compact_volume(snapshot, view)
    request = CanonicalPITAuditRequestV2(
        snapshot_hash=snapshot.manifest.snapshot_hash,
        instrument_id="000001.SZ",
        universe_index="000300.SH",
        expression=_volume_expression(),
        operator_delays=_volume_delays(),
        schedule=_schedule(),
    )
    assert (
        PITAuditService().audit_snapshot(request, snapshot.path).verdict is ValidationVerdict.REJECT
    )


@pytest.mark.parametrize("case", ["wrong-snapshot", "window", "delay", "legacy-field", "lag"])
def test_field_study_window_identity_delay_and_legacy_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from quantos.application.pit import PITAuditService
    from quantos.contracts.pit import CanonicalPITAuditRequest
    from quantos.contracts.research_execution import CanonicalPITAuditRequestV2
    from quantos.contracts.status import ValidationVerdict

    snapshot, view = _build_view(tmp_path, monkeypatch)
    changes = {
        "wrong-snapshot": {"expected_snapshot_hash": "a" * 64},
        "window": {"expression": _volume_expression(window=5)},
        "delay": {"operator_delays": _volume_delays(seconds=1800)},
        "legacy-field": {"execution_profile": "legacy-price/v2"},
        "lag": {"expression": _volume_expression(lag=1)},
    }[case]
    if case == "lag":
        evidence = _compact_volume(snapshot, view, **changes)
        assert [str(day) for day in evidence.bundles[0].source_window] == [
            "2024-01-03",
            "2024-01-04",
        ]
        verify_compact_pit_evidence(evidence, snapshot.path, view.path)
        return
    with pytest.raises(QlibResearchError):
        _compact_volume(snapshot, view, **changes)
    cls = CanonicalPITAuditRequest if case == "legacy-field" else CanonicalPITAuditRequestV2
    request = cls(
        snapshot_hash=changes.get("expected_snapshot_hash", snapshot.manifest.snapshot_hash),
        instrument_id="000001.SZ",
        universe_index="000300.SH",
        expression=changes.get("expression", _volume_expression()),
        operator_delays=changes.get("operator_delays", _volume_delays()),
        schedule=_schedule(),
    )
    assert (
        PITAuditService().audit_snapshot(request, snapshot.path).verdict is ValidationVerdict.REJECT
    )


@pytest.mark.parametrize("score", [None, float("nan"), float("inf")])
def test_field_study_signal_keeps_nonfinite_and_requires_tradability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, score: float | None
) -> None:
    snapshot, view = _build_view(tmp_path, monkeypatch)
    evidence = _compact_volume(snapshot, view)
    _, old_resolved = _evidence_and_resolved(snapshot, view)
    resolved = old_resolved.model_copy(
        update={"expression": evidence.expression, "pit_audit_evidence_hash": evidence.content_hash}
    )
    monkeypatch.setattr(SIGNAL_MODULE, "verify_code_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        SIGNAL_MODULE,
        "_execute_expression",
        lambda *_args, **_kwargs: {} if score is None else {"SZ000001": score},
    )
    original_tradability = SIGNAL_MODULE._load_tradability

    def suspended_status(*args: object, **kwargs: object) -> object:
        rows = original_tradability(*args, **kwargs)
        for status in rows.values():
            status["is_suspended"] = True
        return rows

    monkeypatch.setattr(SIGNAL_MODULE, "_load_tradability", suspended_status)
    result = FactorSignalArtifactBuilder().build(
        resolved,
        evidence,
        view.path,
        tmp_path / "invalid",
        execution_profile="frozen-field-study/v1",
    )
    row = pq.read_table(result.path / "signals.parquet").to_pylist()[0]
    assert row["score"] is None and row["score_valid"] is False
    assert row["tradable"] is False
    monkeypatch.setattr(
        SIGNAL_MODULE, "_execute_expression", lambda *_args, **_kwargs: {"SZ000001": 1.0}
    )
    monkeypatch.setattr(SIGNAL_MODULE, "_load_tradability", lambda *_args, **_kwargs: {})
    with pytest.raises(QlibResearchError, match="tradability"):
        FactorSignalArtifactBuilder().build(
            resolved,
            evidence,
            view.path,
            tmp_path / "missing-status",
            execution_profile="frozen-field-study/v1",
        )
