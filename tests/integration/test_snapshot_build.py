import json
import shutil
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quantos.contracts.snapshot import DataQualityRule
from quantos.contracts.status import ReasonCode
from quantos.data.snapshot import (
    SnapshotBuildError,
    SyntheticSnapshotBuilder,
    diff_snapshots,
    verify_snapshot,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
BACKTEST_FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_backtest_snapshot"


def _copy_fixture(destination: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, destination))


def test_builds_canonical_content_addressed_snapshot(tmp_path: Path) -> None:
    result = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")

    assert result.quality_report.passed
    assert result.path.name == f"sha256-{result.manifest.snapshot_hash}"
    assert result.reference.sha256 == result.manifest.snapshot_hash
    assert result.reference.logical_path.endswith(result.path.name)
    assert verify_snapshot(result.path) == result.manifest
    assert len(result.manifest.files) == 21

    bars = pq.read_table(result.path / "canonical" / "bars.parquet")
    assert bars.schema.field("trade_date").type == pa.date32()
    assert bars.schema.field("event_time").type.tz == "Asia/Shanghai"
    assert bars.schema.field("known_at").type.tz == "Asia/Shanghai"
    first = bars.to_pylist()[0]
    assert first["volume_shares"] == 100_000
    assert first["amount_cny"] == 1_020_000.0
    assert first["availability_basis"] == "CONSERVATIVE_DERIVED"
    assert first["event_time"] <= first["known_at"] <= first["available_at"]

    benchmark = pq.read_table(result.path / "canonical" / "benchmark_bars.parquet")
    instruments = pq.read_table(result.path / "canonical" / "instruments.parquet")
    calendar = pq.read_table(result.path / "canonical" / "calendar.parquet")
    assert benchmark.num_rows == 4
    assert instruments.num_rows == 2
    assert calendar.num_rows == 8
    assert {row["list_status"] for row in instruments.to_pylist()} == {"L", "D"}

    st_status = pq.read_table(result.path / "canonical" / "st_status.parquet")
    suspensions = pq.read_table(result.path / "canonical" / "suspensions.parquet")
    assert st_status.num_rows == suspensions.num_rows == 1
    assert st_status.to_pylist()[0]["type"] == "ST"
    assert suspensions.to_pylist()[0]["suspend_type"] == "S"

    memberships = pq.read_table(result.path / "canonical" / "index_membership.parquet").to_pylist()
    intervals = sorted(
        {
            (row["effective_from"], row["effective_to"])
            for row in memberships
            if row["instrument_id"] == "000001.SZ"
        }
    )
    assert intervals == [
        (date(2024, 1, 2), date(2024, 1, 3)),
        (date(2024, 1, 4), date(2024, 1, 5)),
    ]

    ledger = pq.read_table(result.path / "request-ledger.parquet").to_pylist()
    assert len(ledger) == 9
    assert all(row["network_used"] is False for row in ledger)
    assert (result.path / "raw" / "bars.csv").read_bytes() == (FIXTURE / "bars.csv").read_bytes()


def test_snapshot_hash_is_reproducible_and_publish_is_idempotent(tmp_path: Path) -> None:
    builder = SyntheticSnapshotBuilder()
    first = builder.build(FIXTURE, tmp_path / "one")
    repeated = builder.build(FIXTURE, tmp_path / "one")
    independent = builder.build(FIXTURE, tmp_path / "two")

    assert first.path == repeated.path
    assert first.manifest.snapshot_hash == independent.manifest.snapshot_hash
    assert first.manifest.created_at != independent.manifest.created_at


def test_backtest_fixture_builds_through_execution_and_closeout_session(tmp_path: Path) -> None:
    result = SyntheticSnapshotBuilder().build(BACKTEST_FIXTURE, tmp_path / "snapshots")
    bars = pq.read_table(result.path / "canonical" / "bars.parquet").to_pylist()
    memberships = pq.read_table(result.path / "canonical" / "index_membership.parquet").to_pylist()

    assert result.quality_report.passed
    assert result.manifest.end_date == date(2024, 1, 9)
    assert max(row["trade_date"] for row in bars) == date(2024, 1, 9)
    assert any(
        row["instrument_id"] == "000001.SZ"
        and row["effective_from"] == date(2024, 1, 4)
        and row["effective_to"] == date(2024, 1, 9)
        for row in memberships
    )


def test_duplicate_primary_key_is_rejected_before_publish(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path / "fixture")
    bars_path = fixture / "bars.csv"
    lines = bars_path.read_text(encoding="utf-8").splitlines()
    bars_path.write_text("\n".join([*lines, lines[1], ""]), encoding="utf-8")

    with pytest.raises(SnapshotBuildError) as captured:
        SyntheticSnapshotBuilder().build(fixture, tmp_path / "snapshots")

    assert captured.value.reason_code is ReasonCode.SCHEMA_INVALID
    assert captured.value.quality_report is not None
    primary_key_gate = next(
        gate
        for gate in captured.value.quality_report.gates
        if gate.rule is DataQualityRule.PRIMARY_KEY
    )
    assert primary_key_gate.passed is False
    assert not (tmp_path / "snapshots").exists()


def test_schema_drift_has_stable_reason_code(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path / "fixture")
    bars_path = fixture / "bars.csv"
    payload = bars_path.read_text(encoding="utf-8").replace(",vol,", ",volume,")
    bars_path.write_text(payload, encoding="utf-8")

    with pytest.raises(SnapshotBuildError) as captured:
        SyntheticSnapshotBuilder().build(fixture, tmp_path / "snapshots")
    assert captured.value.reason_code is ReasonCode.SCHEMA_INVALID


@pytest.mark.parametrize(
    ("filename", "old", "new", "expected_rule"),
    [
        ("bars.csv", "10.00,10.30,9.90", "10.00,9.00,9.90", DataQualityRule.OHLC),
        (
            "bars.csv",
            "10.00,1000,1020",
            "10.00,-1,1020",
            DataQualityRule.NONNEGATIVE_TRADING_VALUES,
        ),
        (
            "adj_factor.csv",
            "600000.SH,20240102,1.0000",
            "600000.SH,20240102,0.0000",
            DataQualityRule.POSITIVE_ADJUSTMENT_FACTOR,
        ),
        (
            "index_weight.csv",
            "600000.SH,20240102,50.0",
            "600000.SH,20240102,40.0",
            DataQualityRule.INDEX_WEIGHT_TOTAL,
        ),
        (
            "adj_factor.csv",
            "600000.SH,20240102,1.0000",
            "999999.SH,20240102,1.0000",
            DataQualityRule.INSTRUMENT_REFERENCE,
        ),
        (
            "trade_cal.csv",
            "SSE,20240102,1,20231229",
            "SSE,20240102,0,20231229",
            DataQualityRule.CALENDAR_REFERENCE,
        ),
        (
            "stock_basic.csv",
            "D,19991110,20240104",
            "D,19991110,20240103",
            DataQualityRule.INSTRUMENT_LIFECYCLE,
        ),
        (
            "stock_st.csv",
            "20240103,ST",
            "20240103,UNKNOWN",
            DataQualityRule.SPARSE_STATUS_SEMANTICS,
        ),
        (
            "suspend_d.csv",
            "20240103,S,",
            "20240103,X,",
            DataQualityRule.SPARSE_STATUS_SEMANTICS,
        ),
        (
            "stk_limit.csv",
            "10.00,11.00,9.00",
            "10.00,9.00,11.00",
            DataQualityRule.PRICE_LIMIT_BOUNDS,
        ),
        (
            "bars.csv",
            "600000.SH,20240102",
            "600000.SH,20231229",
            DataQualityRule.DATE_RANGE,
        ),
    ],
)
def test_risk_behavior_quality_matrix_rejects_invalid_inputs(
    tmp_path: Path,
    filename: str,
    old: str,
    new: str,
    expected_rule: DataQualityRule,
) -> None:
    fixture = _copy_fixture(tmp_path / "fixture")
    source = fixture / filename
    payload = source.read_text(encoding="utf-8")
    assert old in payload
    source.write_text(payload.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(SnapshotBuildError) as captured:
        SyntheticSnapshotBuilder().build(fixture, tmp_path / "snapshots")
    assert captured.value.quality_report is not None
    failed_rules = {gate.rule for gate in captured.value.quality_report.gates if not gate.passed}
    assert expected_rule in failed_rules


def test_missing_factor_row_fails_raw_canonical_reconciliation(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path / "fixture")
    source = fixture / "adj_factor.csv"
    lines = source.read_text(encoding="utf-8").splitlines()
    source.write_text("\n".join([lines[0], *lines[2:], ""]), encoding="utf-8")

    with pytest.raises(SnapshotBuildError) as captured:
        SyntheticSnapshotBuilder().build(fixture, tmp_path / "snapshots")
    assert captured.value.quality_report is not None
    reconciliation = next(
        gate
        for gate in captured.value.quality_report.gates
        if gate.rule is DataQualityRule.RAW_CANONICAL_RECONCILIATION
    )
    assert reconciliation.passed is False
    assert reconciliation.reason_code is ReasonCode.SOURCE_INCOMPLETE


def test_tamper_detection_and_manifest_diff(tmp_path: Path) -> None:
    builder = SyntheticSnapshotBuilder()
    first = builder.build(FIXTURE, tmp_path / "one")
    changed_fixture = _copy_fixture(tmp_path / "fixture")
    bars_path = changed_fixture / "bars.csv"
    bars_path.write_text(
        bars_path.read_text(encoding="utf-8").replace("1020", "1021", 1), encoding="utf-8"
    )
    second = builder.build(changed_fixture, tmp_path / "two")
    difference = diff_snapshots(first.manifest, second.manifest)
    assert "canonical/bars.parquet" in difference.changed_paths
    assert "raw/bars.csv" in difference.changed_paths
    assert difference.row_count_changes == ()
    assert difference.schema_changes == ()

    bars_file = first.path / "canonical" / "bars.parquet"
    bars_file.write_bytes(b"tampered")
    with pytest.raises(SnapshotBuildError) as captured:
        verify_snapshot(first.path)
    assert captured.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_manifest_json_retains_runtime_metadata_outside_snapshot_hash(tmp_path: Path) -> None:
    result = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    payload = json.loads((result.path / "manifest.json").read_bytes())
    assert payload["snapshot_hash"] == result.manifest.snapshot_hash
    assert payload["created_at"].endswith("Z")


def test_snapshot_verifier_rejects_unmanifested_files(tmp_path: Path) -> None:
    result = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    (result.path / "unexpected.txt").write_text("not in manifest", encoding="utf-8")

    with pytest.raises(SnapshotBuildError) as captured:
        verify_snapshot(result.path)
    assert captured.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
