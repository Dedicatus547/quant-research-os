from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from quantos.contracts.snapshot import (
    DEFAULT_NORMALIZER_VERSION,
    DEFAULT_SYNTHETIC_ENDPOINTS,
    SnapshotBuildSpec,
    SnapshotSourceKind,
)
from quantos.data.snapshot import verify_snapshot
from quantos.data.tushare import (
    LiveTushareAcquisitionService,
    LiveTushareSnapshotBuilder,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    plan_tushare_requests,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_snapshot"
FILES = {
    "stock_basic": "stock_basic.csv",
    "trade_cal": "trade_cal.csv",
    "daily": "bars.csv",
    "adj_factor": "adj_factor.csv",
    "index_daily": "index_daily.csv",
    "index_weight": "index_weight.csv",
    "stock_st": "stock_st.csv",
    "suspend_d": "suspend_d.csv",
    "stk_limit": "stk_limit.csv",
}


class FixtureClient:
    def __init__(self) -> None:
        self.calls = 0
        self.frames = {
            endpoint: pd.read_csv(FIXTURE / filename, dtype=str, keep_default_na=False)
            for endpoint, filename in FILES.items()
        }

    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        self.calls += 1
        frame = self.frames[api_name]
        for parameter, value in kwargs.items():
            if parameter in frame.columns and value != "":
                frame = frame.loc[frame[parameter] == value]
        if "start_date" in kwargs:
            date_column = "cal_date" if api_name == "trade_cal" else "trade_date"
            frame = frame.loc[
                (frame[date_column] >= kwargs["start_date"])
                & (frame[date_column] <= kwargs["end_date"])
            ]
        return frame.loc[:, fields.split(",")].reset_index(drop=True)


class UnlimitedLimiter:
    def try_acquire(self, name: str, weight: int = 1) -> bool:
        del name, weight
        return True


class FixedClock:
    def __init__(self) -> None:
        self.value = datetime(2024, 1, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


def _spec() -> SnapshotBuildSpec:
    return SnapshotBuildSpec(
        dataset_id="hs300-a-share-daily",
        source_kind=SnapshotSourceKind.TUSHARE,
        provider="tushare-pro",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        required_endpoints=DEFAULT_SYNTHETIC_ENDPOINTS,
        normalizer_version=DEFAULT_NORMALIZER_VERSION,
        availability_policy_id="tushare-observed-close-plus-30m/v1",
    )


def test_acquired_responses_publish_a_live_shaped_immutable_snapshot(tmp_path: Path) -> None:
    spec = _spec()
    sessions = [date(2024, 1, day) for day in range(2, 6)]
    plan = plan_tushare_requests(spec, sessions)
    policy = TushareExecutionPolicy(
        policy_id="fixture-unlimited/v1",
        requests_per_minute=10_000,
        max_attempts=1,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )
    acquisition_root = tmp_path / "acquisition"
    ledger = TusharePlanExecutor(
        FixtureClient(), policy, limiter=UnlimitedLimiter(), now=FixedClock()
    ).execute(plan, acquisition_root)

    builder = LiveTushareSnapshotBuilder()
    first = builder.build(spec, plan, ledger, acquisition_root, tmp_path / "snapshots")
    repeated = builder.build(spec, plan, ledger, acquisition_root, tmp_path / "snapshots")

    assert first.path == repeated.path
    assert first.manifest.source_kind is SnapshotSourceKind.TUSHARE
    assert first.manifest.limitations == ("SINGLE_SOURCE_NON_VINTAGE",)
    assert first.quality_report.passed
    assert verify_snapshot(first.path) == first.manifest
    assert len(list((first.path / "raw").rglob("*.parquet"))) == len(plan.requests)
    request_ledger = pq.read_table(first.path / "request-ledger.parquet")
    assert request_ledger.num_rows == len(plan.requests)
    assert set(request_ledger["network_used"].to_pylist()) == {True}
    payload = b"".join(path.read_bytes() for path in first.path.rglob("*.json"))
    assert b"TUSHARE_TOKEN" not in payload


def test_live_empty_limit_pre_close_uses_daily_value_and_keeps_raw_empty(
    tmp_path: Path,
) -> None:
    spec = _spec()
    sessions = [date(2024, 1, day) for day in range(2, 6)]
    plan = plan_tushare_requests(spec, sessions)
    client = FixtureClient()
    mask = (client.frames["stk_limit"]["ts_code"] == "600000.SH") & (
        client.frames["stk_limit"]["trade_date"] == "20240102"
    )
    client.frames["stk_limit"].loc[mask, "pre_close"] = ""
    policy = TushareExecutionPolicy(
        policy_id="fixture-unlimited/v1",
        requests_per_minute=10_000,
        max_attempts=1,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )
    acquisition_root = tmp_path / "acquisition"
    ledger = TusharePlanExecutor(
        client, policy, limiter=UnlimitedLimiter(), now=FixedClock()
    ).execute(plan, acquisition_root)

    result = LiveTushareSnapshotBuilder().build(
        spec, plan, ledger, acquisition_root, tmp_path / "snapshots"
    )

    canonical = pq.read_table(result.path / "canonical" / "price_limits.parquet")
    row = next(item for item in canonical.to_pylist() if item["instrument_id"] == "600000.SH")
    assert row["pre_close"] == 10.0
    request = next(
        item
        for item in plan.requests
        if item.endpoint == "stk_limit" and item.params["trade_date"] == "20240102"
    )
    raw = pq.read_table(
        result.path
        / "raw"
        / "stk_limit"
        / f"{request.sequence:06d}-sha256-{request.content_hash}.parquet"
    )
    raw_row = next(item for item in raw.to_pylist() if item["ts_code"] == "600000.SH")
    assert raw_row["pre_close"] == ""


def test_calendar_first_orchestration_reuses_verified_bootstrap_responses(
    tmp_path: Path,
) -> None:
    spec = _spec()
    client = FixtureClient()
    policy = TushareExecutionPolicy(
        policy_id="fixture-unlimited/v1",
        requests_per_minute=10_000,
        max_attempts=1,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )
    executor = TusharePlanExecutor(client, policy, limiter=UnlimitedLimiter(), now=FixedClock())

    result = LiveTushareAcquisitionService(executor).acquire_and_build(
        spec, tmp_path / "acquisition", tmp_path / "snapshots"
    )

    expected_plan = plan_tushare_requests(spec, [date(2024, 1, day) for day in range(2, 6)])
    assert client.calls == len(expected_plan.requests)
    assert result.quality_report.passed


def test_suspend_and_resume_events_share_raw_date_but_only_suspend_is_canonical(
    tmp_path: Path,
) -> None:
    spec = _spec()
    sessions = [date(2024, 1, day) for day in range(2, 6)]
    plan = plan_tushare_requests(spec, sessions)
    client = FixtureClient()
    client.frames["suspend_d"] = pd.concat(
        [
            client.frames["suspend_d"],
            pd.DataFrame(
                [["000001.SZ", "20240103", "R", ""]],
                columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"],
            ),
        ],
        ignore_index=True,
    )
    policy = TushareExecutionPolicy(
        policy_id="fixture-unlimited/v1",
        requests_per_minute=10_000,
        max_attempts=1,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )
    acquisition_root = tmp_path / "acquisition"
    ledger = TusharePlanExecutor(
        client, policy, limiter=UnlimitedLimiter(), now=FixedClock()
    ).execute(plan, acquisition_root)

    result = LiveTushareSnapshotBuilder().build(
        spec, plan, ledger, acquisition_root, tmp_path / "snapshots"
    )

    canonical = pq.read_table(result.path / "canonical" / "suspensions.parquet")
    assert canonical.select(["instrument_id", "trade_date", "suspend_type"]).to_pylist() == [
        {
            "instrument_id": "000001.SZ",
            "trade_date": date(2024, 1, 3),
            "suspend_type": "S",
        }
    ]
    raw_suspend_rows = sum(
        pq.read_table(path).num_rows
        for path in (result.path / "raw" / "suspend_d").glob("*.parquet")
    )
    assert raw_suspend_rows == 2
