from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock

import pandas as pd
import pytest
from pydantic import ValidationError

from quantos.contracts.snapshot import (
    DEFAULT_NORMALIZER_VERSION,
    DEFAULT_SYNTHETIC_ENDPOINTS,
    SnapshotBuildSpec,
    SnapshotSourceKind,
)
from quantos.contracts.status import ReasonCode
from quantos.data.tushare import (
    TushareAcquisitionError,
    TushareExecutionPolicy,
    TusharePlanExecutor,
    TushareRequest,
    TushareRequestPlan,
    plan_tushare_requests,
)


def _spec() -> SnapshotBuildSpec:
    return SnapshotBuildSpec(
        dataset_id="hs300-a-share-daily",
        source_kind=SnapshotSourceKind.TUSHARE,
        provider="tushare-pro",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        required_endpoints=DEFAULT_SYNTHETIC_ENDPOINTS,
        normalizer_version=DEFAULT_NORMALIZER_VERSION,
        availability_policy_id="tushare-close-plus-30m/v1",
    )


def _request(sequence: int, trade_date: str) -> TushareRequest:
    return TushareRequest(
        sequence=sequence,
        endpoint="daily",
        params={"trade_date": trade_date},
        fields=("ts_code", "trade_date", "close"),
        primary_key=("ts_code", "trade_date"),
    )


class CountingLimiter:
    def __init__(self) -> None:
        self.acquisitions = 0

    def try_acquire(self, name: str, weight: int = 1) -> bool:
        assert name == "tushare-snapshot"
        assert weight == 1
        self.acquisitions += 1
        return True


class RetryOnceClient:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("transient provider detail")
        return pd.DataFrame([["000001.SZ", kwargs["trade_date"], 12.1]], columns=fields.split(","))


class FixedClock:
    def __init__(self) -> None:
        self.value = datetime(2024, 1, 4, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def _policy() -> TushareExecutionPolicy:
    return TushareExecutionPolicy(
        policy_id="offline-test/v1",
        requests_per_minute=100,
        max_attempts=2,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )


def test_request_plan_is_endpoint_specific_and_row_limit_safe() -> None:
    plan = plan_tushare_requests(_spec(), [date(2024, 1, 2), date(2024, 1, 3)])

    assert len(plan.requests) == 17
    assert [item.sequence for item in plan.requests] == list(range(1, 18))
    assert sum(item.endpoint == "stock_basic" for item in plan.requests) == 3
    assert sum(item.endpoint == "trade_cal" for item in plan.requests) == 2
    assert sum(item.endpoint == "daily" for item in plan.requests) == 2
    assert {item.primary_key for item in plan.requests if item.endpoint == "suspend_d"} == {
        ("ts_code", "trade_date", "suspend_type", "suspend_timing")
    }
    assert all("token" not in item.params for item in plan.requests)


def test_request_contract_rejects_credentials() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        TushareRequest(
            sequence=1,
            endpoint="daily",
            params={"token": "must-not-persist"},
            fields=("ts_code",),
            primary_key=("ts_code",),
        )


def test_executor_retries_transient_failure_and_resumes_verified_checkpoint(
    tmp_path: Path,
) -> None:
    plan = TushareRequestPlan(
        build_spec_hash=_spec().content_hash, requests=(_request(1, "20240102"),)
    )
    client = RetryOnceClient()
    limiter = CountingLimiter()
    executor = TusharePlanExecutor(
        client,
        _policy(),
        limiter=limiter,
        now=FixedClock(),
    )

    first = executor.execute(plan, tmp_path)
    resumed = executor.execute(plan, tmp_path)

    assert client.calls == limiter.acquisitions == 2
    assert first.entries[0].attempt_count == 2
    assert first == resumed
    assert first.entries[0].response_sha256 == resumed.entries[0].response_sha256
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*.json"))
    assert b"transient provider detail" not in persisted


def test_executor_uses_bounded_workers_under_one_shared_rate_policy(tmp_path: Path) -> None:
    class ConcurrentClient:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.lock = Lock()
            self.barrier = Barrier(3)

        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            del api_name
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            self.barrier.wait(timeout=2)
            with self.lock:
                self.active -= 1
            return pd.DataFrame(
                [["000001.SZ", kwargs["trade_date"], 12.1]], columns=fields.split(",")
            )

    plan = TushareRequestPlan(
        build_spec_hash=_spec().content_hash,
        requests=tuple(_request(sequence, f"2024010{sequence}") for sequence in range(1, 4)),
    )
    policy = TushareExecutionPolicy(
        policy_id="bounded-workers-test/v1",
        requests_per_minute=200,
        max_attempts=1,
        retry_min_seconds=0,
        retry_max_seconds=0,
    )
    client = ConcurrentClient()
    limiter = CountingLimiter()

    ledger = TusharePlanExecutor(client, policy, limiter=limiter, now=FixedClock()).execute(
        plan, tmp_path
    )

    assert len(ledger.entries) == 3
    assert client.maximum_active == 3
    assert limiter.acquisitions == 3


def test_executor_rejects_schema_drift_without_persisting_provider_detail(
    tmp_path: Path,
) -> None:
    secret = "secret-provider-message"

    class SchemaDriftClient:
        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            del api_name, fields, kwargs
            return pd.DataFrame([{"unexpected": secret}])

    plan = TushareRequestPlan(
        build_spec_hash=_spec().content_hash, requests=(_request(1, "20240102"),)
    )
    with pytest.raises(TushareAcquisitionError) as captured:
        TusharePlanExecutor(SchemaDriftClient(), _policy(), limiter=CountingLimiter()).execute(
            plan, tmp_path
        )

    assert captured.value.reason_code is ReasonCode.SCHEMA_INVALID
    assert secret not in str(captured.value)
    assert not list(tmp_path.rglob("*.parquet"))


def test_executor_rejects_duplicate_keys_across_chunks(tmp_path: Path) -> None:
    class DuplicateClient:
        def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame:
            del api_name, kwargs
            return pd.DataFrame([["000001.SZ", "20240102", 12.1]], columns=fields.split(","))

    plan = TushareRequestPlan(
        build_spec_hash=_spec().content_hash,
        requests=(_request(1, "20240102"), _request(2, "20240103")),
    )
    with pytest.raises(TushareAcquisitionError, match="across request chunks") as captured:
        TusharePlanExecutor(DuplicateClient(), _policy(), limiter=CountingLimiter()).execute(
            plan, tmp_path
        )
    assert captured.value.reason_code is ReasonCode.SCHEMA_INVALID


def test_executor_hard_rejects_corrupted_checkpoint(tmp_path: Path) -> None:
    plan = TushareRequestPlan(
        build_spec_hash=_spec().content_hash, requests=(_request(1, "20240102"),)
    )
    executor = TusharePlanExecutor(
        RetryOnceClient(), _policy(), limiter=CountingLimiter(), now=FixedClock()
    )
    ledger = executor.execute(plan, tmp_path)
    response = tmp_path / ledger.entries[0].response_logical_path
    response.write_bytes(b"tampered")

    with pytest.raises(TushareAcquisitionError) as captured:
        executor.execute(plan, tmp_path)
    assert captured.value.reason_code is ReasonCode.ARTIFACT_CORRUPTED
