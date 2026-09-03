from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from quantos.contracts.status import ReasonCode
from quantos.data import qlib_view
from quantos.data.qlib_view import QlibViewBuilder, QlibViewBuildError, verify_qlib_view
from quantos.data.snapshot import SyntheticSnapshotBuilder
from quantos.integrations.qlib import QLIB_COMMIT, QLIB_VERSION, OfficialQlibTools
from quantos.research.qlib import QlibResearchError, resolve_historical_universe

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"


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


def _semantic_output(command: list[str]) -> str:
    values = {"SZ000001": 12.1, "SH000300": 3320.0, "SH600000": 10.2}
    return f"QUANTOS_SAMPLE={values[command[-2]]}\n"


def test_view_builder_uses_verified_official_tool_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    official = _fake_tools(tmp_path)
    monkeypatch.setattr(qlib_view, "verify_official_qlib_tools", lambda _path: official)

    def fake_run(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if "dump_all" in command:
            qlib_root = Path(command[command.index("--qlib_dir") + 1])
            (qlib_root / "calendars").mkdir(parents=True)
            (qlib_root / "calendars" / "day.txt").write_text("2024-01-02\n", encoding="utf-8")
            return CompletedProcess(command, 0, stdout="dumped")
        if "check_data" in command:
            return CompletedProcess(command, 0, stdout="healthy")
        if "-c" in command:
            return CompletedProcess(command, 0, stdout=_semantic_output(command))
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    builder = QlibViewBuilder()
    first = builder.build(snapshot.path, tmp_path / "views", official.source_root)
    repeated = builder.build(snapshot.path, tmp_path / "views", official.source_root)

    assert first.path == repeated.path
    assert first.manifest.source_snapshot_hash == snapshot.manifest.snapshot_hash
    assert first.manifest.health_check_passed
    assert len(first.manifest.semantic_samples) == 3
    assert all(sample.passed for sample in first.manifest.semantic_samples)
    assert verify_qlib_view(first.path) == first.manifest
    assert (first.path / "view-spec.json").is_file()
    universe = pq.read_table(first.path / "sidecars" / "historical-universe.parquet")
    tradability = pq.read_table(first.path / "sidecars" / "tradability.parquet")
    assert universe.num_rows == 3
    suspended = [row for row in tradability.to_pylist() if row["is_suspended"]]
    assert [(row["instrument_id"], str(row["trade_date"])) for row in suspended] == [
        ("000001.SZ", "2024-01-03")
    ]
    resolution = resolve_historical_universe(
        first.path,
        expected_view_hash=first.manifest.view_hash,
        expected_snapshot_hash=snapshot.manifest.snapshot_hash,
        index_id="000300.SH",
        as_of_date=datetime(2024, 1, 3).date(),
        decision_time=datetime(2024, 1, 3, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert [member.instrument_id for member in resolution.members] == [
        "000001.SZ",
        "600000.SH",
    ]

    with pytest.raises(QlibResearchError) as unavailable:
        resolve_historical_universe(
            first.path,
            expected_view_hash=first.manifest.view_hash,
            expected_snapshot_hash=snapshot.manifest.snapshot_hash,
            index_id="000300.SH",
            as_of_date=datetime(2024, 1, 2).date(),
            decision_time=datetime(2024, 1, 2, 16, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    assert unavailable.value.reason_code is ReasonCode.SOURCE_INCOMPLETE


def test_view_verifier_detects_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    official = _fake_tools(tmp_path)
    monkeypatch.setattr(qlib_view, "verify_official_qlib_tools", lambda _path: official)

    def fake_run(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if "dump_all" in command:
            qlib_root = Path(command[command.index("--qlib_dir") + 1])
            qlib_root.mkdir()
            (qlib_root / "data.bin").write_bytes(b"valid")
            return CompletedProcess(command, 0, stdout="dumped")
        if "-c" in command:
            return CompletedProcess(command, 0, stdout=_semantic_output(command))
        return CompletedProcess(command, 0, stdout="healthy")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    result = QlibViewBuilder().build(snapshot.path, tmp_path / "views", official.source_root)
    (result.path / "data.bin").write_bytes(b"tampered")
    with pytest.raises(QlibViewBuildError) as captured:
        verify_qlib_view(result.path)
    assert captured.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED


def test_view_verifier_rejects_unmanifested_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = SyntheticSnapshotBuilder().build(FIXTURE, tmp_path / "snapshots")
    official = _fake_tools(tmp_path)
    monkeypatch.setattr(qlib_view, "verify_official_qlib_tools", lambda _path: official)

    def fake_run(command: list[str], *, cwd: Path | None = None) -> CompletedProcess[str]:
        del cwd
        if "dump_all" in command:
            qlib_root = Path(command[command.index("--qlib_dir") + 1])
            qlib_root.mkdir()
            (qlib_root / "data.bin").write_bytes(b"valid")
            return CompletedProcess(command, 0, stdout="dumped")
        if "-c" in command:
            return CompletedProcess(command, 0, stdout=_semantic_output(command))
        return CompletedProcess(command, 0, stdout="healthy")

    monkeypatch.setattr(qlib_view, "run_checked", fake_run)
    result = QlibViewBuilder().build(snapshot.path, tmp_path / "views", official.source_root)
    (result.path / "unexpected.txt").write_text("not in manifest", encoding="utf-8")

    with pytest.raises(QlibViewBuildError) as captured:
        verify_qlib_view(result.path)
    assert captured.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
