"""Bounded personal-product boundaries and one explicitly enabled native Qlib rehearsal."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from threading import Event, Thread

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.application.personal_research import PersonalDatasetBinding, PersonalResearchService
from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.personal_research import PersonalDatasetManifest
from quantos.research.personal_qlib import compile_daily_signals

REPO = Path(__file__).resolve().parents[1]


def request(key="test"):
    return {
        "idempotency_key": key,
        "brief": "A股主板日频短线趋势, 同花顺板块, 公告辅助分析",
        "proposal": {"session_id": "engineering-fixture", "model_claim": None},
        "dataset_id": "fixture",
        "benchmark": "SH000985",
    }


def manifest():
    return PersonalDatasetManifest(
        dataset_id="fixture",
        kind="synthetic",
        snapshot_hash="a" * 64,
        qlib_view_hash="b" * 64,
        panel_sha256="c" * 64,
        pit_evidence_hash="d" * 64,
        start_date=date(2024, 2, 1),
        end_date=date(2024, 2, 16),
        all_mainboard_pit=True,
        ths_historical_membership=True,
        tradability_verified=True,
        source_vintage="synthetic",
        exposure="synthetic",
        benchmarks=("SH000985",),
        qlib_files={"calendars/day.txt": "e" * 64},
    )


def service(tmp_path, *, executor=None, authorizer=None):
    item = PersonalDatasetBinding(manifest(), tmp_path / "provider", tmp_path / "panel.parquet")
    return PersonalResearchService(
        tmp_path / "authority",
        REPO,
        catalog={"fixture": item},
        executor=executor,
        execution_authorizer=authorizer,
    )


def test_prepare_is_proposal_only_and_persistent(tmp_path):
    calls = []
    one = service(tmp_path, executor=lambda *args: calls.append(args))
    prepared = one.prepare(request())
    two = service(tmp_path)
    assert two.status(prepared["task_id"])["state"] == "PREPARED"
    assert one.prepare(request())["task_id"] == prepared["task_id"]
    assert len(two.history()["tasks"]) == 1
    assert prepared["request"]["proposal"]["model_identity_authenticated"] is False
    assert not calls
    changed = request()
    changed["brief"] = "changed direction"
    with pytest.raises(ValueError, match="idempotency"):
        one.prepare(changed)


def test_untrusted_authorization_and_paths_rejected(tmp_path):
    app = service(tmp_path)
    invalid = {**request(), "approved": True}
    with pytest.raises(ValidationError):
        app.prepare(invalid)
    invalid = request()
    invalid["proposal"]["model_identity_authenticated"] = True
    with pytest.raises(ValidationError):
        app.prepare(invalid)
    task = app.prepare(request())["task_id"]
    with pytest.raises(PermissionError, match="server-side"):
        app.execute(task)
    assert app.status(task)["state"] == "PREPARED"
    with pytest.raises(ValueError):
        app.status("../../outside")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "authority", target_is_directory=True)
    with pytest.raises(Exception, match="unsafe"):
        PersonalResearchService(alias, REPO)


def test_idempotent_execution_and_missing_full_denominator(tmp_path):
    calls = []

    def executor(prepared, root, cancelled):
        calls.append(prepared.content_hash)
        return {"run_status": "FAILED", "prepared_hash": prepared.content_hash, "receipts": []}

    app = service(tmp_path, executor=executor, authorizer=lambda prepared: prepared.content_hash)
    task = app.prepare(request())["task_id"]
    assert app.execute(task)["state"] == "FAILED"
    assert app.execute(task)["state"] == "FAILED"
    assert calls == [task]
    result = app.results(task)
    assert result["planned_denominator"] == 7
    assert result["succeeded_denominator"] == 0
    assert all(row["metrics"] is None for row in result["rows"])
    assert [row["seed"] for row in result["rows"] if row["role"] == "random"] == [
        17,
        41,
        73,
        101,
        137,
    ]


def test_unknown_never_reissues_and_failure_not_evaluated(tmp_path):
    app = service(tmp_path)
    task = app.prepare(request())["task_id"]
    app._append(task, "RUNNING", {"pid": 99999999, "process_identity": "absent"})
    assert app.status(task)["state"] == "UNKNOWN"
    assert app.execute(task)["state"] == "UNKNOWN"
    failed = service(
        tmp_path / "failed",
        executor=lambda *args: (_ for _ in ()).throw(ValueError("private")),
        authorizer=lambda prepared: "authorized-fixture-only",
    )
    task = failed.prepare(request())["task_id"]
    result = failed.execute(task)
    assert result["state"] == "FAILED"
    assert result["validation_verdict"] == "NOT_EVALUATED"
    assert "private" not in json.dumps(result)


def test_cooperative_cancellation_preserves_exit(tmp_path):
    entered, release = Event(), Event()

    def executor(prepared, root, cancelled):
        entered.set()
        assert release.wait(10)
        assert cancelled()
        return {
            "run_status": "FAILED",
            "reason": "cancelled",
            "prepared_hash": prepared.content_hash,
            "receipts": [],
        }

    app = service(tmp_path, executor=executor, authorizer=lambda prepared: "synthetic-only")
    task = app.prepare(request())["task_id"]
    worker = Thread(target=app.execute, args=(task,))
    worker.start()
    assert entered.wait(10)
    assert service(tmp_path).cancel(task)["state"] == "CANCEL_REQUESTED"
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert service(tmp_path).status(task)["state"] == "CANCELLED"
    assert app.execute(task)["state"] == "CANCELLED"


def panel():
    days = pd.bdate_range("2024-01-02", periods=45)
    rows = []
    for instrument, offset in (("SH000985", 0), ("SH600001", 1), ("SH600002", 2), ("SZ000001", 3)):
        for index, day in enumerate(days):
            close = (10 + offset) * (1.008 + offset * 0.001) ** index
            if instrument == "SH600001" and index >= 32:
                close *= 0.94 ** (index - 31)
            rows.append(
                {
                    "trade_date": day.date(),
                    "qlib_id": instrument,
                    "close": close,
                    "volume": 100000 * 1.10**index,
                    "is_mainboard": instrument != "SH000985",
                    "is_st": False,
                    "sector_momentum_5": 0.03 if instrument != "SH000985" else np.nan,
                    "available_at": day.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=16),
                }
            )
    return pd.DataFrame(rows)


def test_pit_time_and_comparison_signals(tmp_path):
    app = service(tmp_path)
    prepared_dict = app.prepare(request())
    prepared = app._prepared(prepared_dict["task_id"])
    data = panel()
    signals = compile_daily_signals(data, prepared)
    assert len(signals) == 7
    assert signals["main"].equals(compile_daily_signals(data, prepared)["main"])
    assert not signals["random-17"].equals(signals["random-41"])
    assert (
        signals["main"].index.get_level_values("datetime").max().date() < prepared.request.end_date
    )
    future = data.copy()
    future.loc[future.index[0], "available_at"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="PIT hard rejection"):
        compile_daily_signals(future, prepared)
    missing = data.drop(columns="available_at")
    with pytest.raises(ValueError, match="panel fields"):
        compile_daily_signals(missing, prepared)


def test_market_scope_cannot_be_synthetic_qualified(tmp_path):
    item = manifest().model_copy(
        update={
            "kind": "market",
            "source_vintage": "historical_non_vintage",
            "exposure": "retrospective_exploration",
            "all_mainboard_pit": False,
            "ths_historical_membership": False,
        }
    )
    app = PersonalResearchService(
        tmp_path / "authority",
        REPO,
        catalog={"fixture": PersonalDatasetBinding(item, tmp_path, tmp_path / "panel")},
    )
    result = app.prepare(request())
    assert result["readiness"] == "BLOCKED"
    assert any("index constituents cannot substitute" in gap for gap in result["gaps"])
    assert any("THS" in gap for gap in result["gaps"])
    with pytest.raises(PermissionError):
        app.execute(result["task_id"])


@pytest.mark.parametrize("attack", ["receipt", "export", "outcome"])
def test_result_originals_are_verified(tmp_path, attack):
    def executor(prepared, root, cancelled):
        directory = root / "main"
        directory.mkdir()
        atomic_write_bytes(directory / "native.parquet", b"fixture-native-export")
        receipt = {
            "prepared_hash": prepared.content_hash,
            "candidate_id": "main",
            "run_status": "FAILED",
            "metrics": None,
            "files": {"native.parquet": sha256_file(directory / "native.parquet")},
        }
        atomic_write_bytes(directory / "receipt.json", canonical_json_bytes(receipt))
        return {
            "run_status": "FAILED",
            "prepared_hash": prepared.content_hash,
            "receipts": [
                {
                    "candidate_id": "main",
                    "run_status": "FAILED",
                    "receipt_hash": sha256_file(directory / "receipt.json"),
                }
            ],
        }

    app = service(tmp_path, executor=executor, authorizer=lambda prepared: prepared.content_hash)
    task = app.prepare(request())["task_id"]
    assert app.execute(task)["state"] == "FAILED"
    result = app.results(task)
    assert result["planned_denominator"] == 7
    assert result["rows"][0]["evidence_status"] == "VERIFIED_COMMITTED"
    execution = app.root / "tasks" / task / "execution"
    if attack == "receipt":
        receipt = execution / "main/receipt.json"
        data = json.loads(receipt.read_bytes())
        data["metrics"] = {"net_total_return": 42}
        receipt.write_bytes(canonical_json_bytes(data))
    elif attack == "export":
        (execution / "main/native.parquet").unlink()
    else:
        (execution / "outcome.json").write_bytes(b"{}")
    with pytest.raises(Exception, match=r"(hash|unavailable|outcome|receipt)"):
        app.results(task)


def test_missing_observations_do_not_become_ineligible(tmp_path):
    app = service(tmp_path)
    task = app.prepare(request())["task_id"]
    prepared = app._prepared(task)
    for column in ("close", "volume", "sector_momentum_5"):
        data = panel()
        data.loc[data["qlib_id"] == "SH600001", column] = np.nan
        with pytest.raises(ValueError, match="PIT hard rejection"):
            compile_daily_signals(data, prepared)
    proposal = request("metadata")
    proposal["proposal"]["explanation"] = "A daily strategy is distinct from the intraday heuristic"
    proposal["proposal"]["public_references"] = [
        "https://qlib.readthedocs.io/en/stable/component/strategy.html"
    ]
    result = app.prepare(proposal)
    assert result["request"]["schema_version"] == "personal-study-request/v2"
    assert result["request"]["proposal"]["sdk_invocation"] is False
