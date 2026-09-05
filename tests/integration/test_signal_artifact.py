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
from quantos.contracts.pit import OperatorDelayPolicy
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
