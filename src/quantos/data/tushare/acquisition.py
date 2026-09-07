"""Deterministic Tushare request planning and resumable raw-response acquisition."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal, Protocol, Self, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, PositiveInt, field_validator, model_validator
from pyrate_limiter import Duration, Limiter, Rate  # pyright: ignore[reportMissingTypeStubs]
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import CanonicalContract
from quantos.contracts.refs import SHA256_PATTERN, validate_logical_path
from quantos.contracts.snapshot import SnapshotBuildSpec
from quantos.contracts.status import ReasonCode


class TushareQueryClient(Protocol):
    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame: ...


class AcquisitionLimiter(Protocol):
    def try_acquire(self, name: str, weight: int = 1) -> bool: ...


class TushareRequest(CanonicalContract):
    schema_version: Literal["tushare-request/v1"] = "tushare-request/v1"
    sequence: PositiveInt
    endpoint: str = Field(min_length=1)
    params: dict[str, str]
    fields: tuple[str, ...]
    primary_key: tuple[str, ...]

    @field_validator("params")
    @classmethod
    def params_are_secret_free_and_sorted(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"token", "api_key", "authorization", "auth"}
        if any(key.lower() in forbidden for key in value):
            raise ValueError("request params cannot contain credentials")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def fields_and_primary_key_are_valid(self) -> Self:
        if not self.fields or len(self.fields) != len(set(self.fields)):
            raise ValueError("request fields must be nonempty and unique")
        if not self.primary_key or not set(self.primary_key).issubset(self.fields):
            raise ValueError("request primary key must be nonempty and covered by fields")
        return self


class TushareRequestPlan(CanonicalContract):
    schema_version: Literal["tushare-request-plan/v1"] = "tushare-request-plan/v1"
    build_spec_hash: str = Field(pattern=SHA256_PATTERN)
    requests: tuple[TushareRequest, ...]

    @field_validator("requests")
    @classmethod
    def requests_are_contiguous_and_unique(
        cls, value: tuple[TushareRequest, ...]
    ) -> tuple[TushareRequest, ...]:
        if not value or [item.sequence for item in value] != list(range(1, len(value) + 1)):
            raise ValueError("request sequences must be contiguous from one")
        identities = [
            (item.endpoint, tuple(item.params.items()), item.fields, item.primary_key)
            for item in value
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("request plan cannot contain duplicate requests")
        return value


class TushareExecutionPolicy(CanonicalContract):
    schema_version: Literal["tushare-execution-policy/v1"] = "tushare-execution-policy/v1"
    policy_id: str = Field(min_length=1)
    requests_per_minute: PositiveInt
    max_attempts: PositiveInt = 3
    retry_min_seconds: float = Field(default=1.0, ge=0)
    retry_max_seconds: float = Field(default=8.0, ge=0)

    @model_validator(mode="after")
    def retry_range_is_ordered(self) -> Self:
        if self.retry_min_seconds > self.retry_max_seconds:
            raise ValueError("retry_min_seconds cannot exceed retry_max_seconds")
        return self


class RequestLedgerEntry(CanonicalContract):
    schema_version: Literal["tushare-request-ledger-entry/v1"] = "tushare-request-ledger-entry/v1"
    request_hash: str = Field(pattern=SHA256_PATTERN)
    request_sequence: PositiveInt
    endpoint: str = Field(min_length=1)
    normalized_params: dict[str, str]
    requested_fields: tuple[str, ...]
    attempt_count: PositiveInt
    started_at: datetime
    completed_at: datetime
    response_row_count: int = Field(ge=0)
    response_fields: tuple[str, ...]
    response_sha256: str = Field(pattern=SHA256_PATTERN)
    response_logical_path: str = Field(min_length=1)
    tushare_package_version: str = Field(min_length=1)
    rate_limit_outcome: Literal["ACQUIRED"] = "ACQUIRED"

    @field_validator("response_logical_path")
    @classmethod
    def response_path_is_safe(cls, value: str) -> str:
        return validate_logical_path(value)

    @model_validator(mode="after")
    def ledger_entry_is_consistent(self) -> Self:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("ledger timestamps must be timezone-aware")
        if self.started_at > self.completed_at:
            raise ValueError("ledger timestamps are reversed")
        return self


class TushareRequestLedger(CanonicalContract):
    schema_version: Literal["tushare-request-ledger/v1"] = "tushare-request-ledger/v1"
    plan_hash: str = Field(pattern=SHA256_PATTERN)
    execution_policy_hash: str = Field(pattern=SHA256_PATTERN)
    entries: tuple[RequestLedgerEntry, ...]

    @field_validator("entries")
    @classmethod
    def entries_are_contiguous(
        cls, value: tuple[RequestLedgerEntry, ...]
    ) -> tuple[RequestLedgerEntry, ...]:
        if not value or [item.request_sequence for item in value] != list(range(1, len(value) + 1)):
            raise ValueError("ledger entries must cover a contiguous completed plan")
        return value


class TushareAcquisitionError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_ENDPOINT_FIELDS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "stock_basic": (
        ("ts_code", "symbol", "name", "exchange", "list_status", "list_date", "delist_date"),
        ("ts_code",),
    ),
    "trade_cal": (("exchange", "cal_date", "is_open", "pretrade_date"), ("exchange", "cal_date")),
    "daily": (
        ("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"),
        ("ts_code", "trade_date"),
    ),
    "adj_factor": (("ts_code", "trade_date", "adj_factor"), ("ts_code", "trade_date")),
    "index_daily": (
        ("ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"),
        ("ts_code", "trade_date"),
    ),
    "index_weight": (
        ("index_code", "con_code", "trade_date", "weight"),
        ("index_code", "con_code", "trade_date"),
    ),
    "stock_st": (("ts_code", "trade_date", "type"), ("ts_code", "trade_date")),
    "suspend_d": (
        ("ts_code", "trade_date", "suspend_type", "suspend_timing"),
        ("ts_code", "trade_date", "suspend_type", "suspend_timing"),
    ),
    "stk_limit": (
        ("ts_code", "trade_date", "pre_close", "up_limit", "down_limit"),
        ("ts_code", "trade_date"),
    ),
}


def _date_string(value: date) -> str:
    return value.strftime("%Y%m%d")


def plan_tushare_requests(
    spec: SnapshotBuildSpec, open_sessions: Sequence[date]
) -> TushareRequestPlan:
    """Build an endpoint-specific, row-limit-safe plan after calendars are known."""

    sessions = sorted(set(open_sessions))
    if not sessions or sessions[0] < spec.start_date or sessions[-1] > spec.end_date:
        raise ValueError("open sessions must be nonempty and contained by the build range")
    missing_endpoints = set(spec.required_endpoints) - set(_ENDPOINT_FIELDS)
    if missing_endpoints:
        raise ValueError(f"unsupported required endpoints: {','.join(sorted(missing_endpoints))}")

    request_shapes: list[tuple[str, dict[str, str]]] = []
    for exchange in ("SSE", "SZSE"):
        request_shapes.append(
            (
                "trade_cal",
                {
                    "exchange": exchange,
                    "start_date": _date_string(spec.start_date),
                    "end_date": _date_string(spec.end_date),
                },
            )
        )
    for status in ("L", "D", "P"):
        request_shapes.append(("stock_basic", {"exchange": "", "list_status": status}))
    for year in range(spec.start_date.year, spec.end_date.year + 1):
        chunk_start = max(spec.start_date, date(year, 1, 1))
        chunk_end = min(spec.end_date, date(year, 12, 31))
        for endpoint in ("index_daily", "index_weight"):
            key = "ts_code" if endpoint == "index_daily" else "index_code"
            request_shapes.append(
                (
                    endpoint,
                    {
                        key: "000300.SH",
                        "start_date": _date_string(chunk_start),
                        "end_date": _date_string(chunk_end),
                    },
                )
            )
    for session in sessions:
        trade_date = _date_string(session)
        for endpoint in ("daily", "adj_factor", "stock_st", "suspend_d", "stk_limit"):
            request_shapes.append((endpoint, {"trade_date": trade_date}))

    required = set(spec.required_endpoints)
    filtered = [shape for shape in request_shapes if shape[0] in required]
    requests = tuple(
        TushareRequest(
            sequence=sequence,
            endpoint=endpoint,
            params=params,
            fields=_ENDPOINT_FIELDS[endpoint][0],
            primary_key=_ENDPOINT_FIELDS[endpoint][1],
        )
        for sequence, (endpoint, params) in enumerate(filtered, start=1)
    )
    return TushareRequestPlan(build_spec_hash=spec.content_hash, requests=requests)


def plan_tushare_calendar_requests(spec: SnapshotBuildSpec) -> TushareRequestPlan:
    """Create the two bootstrap requests needed to resolve the trading sessions."""

    fields, primary_key = _ENDPOINT_FIELDS["trade_cal"]
    requests = tuple(
        TushareRequest(
            sequence=sequence,
            endpoint="trade_cal",
            params={
                "exchange": exchange,
                "start_date": _date_string(spec.start_date),
                "end_date": _date_string(spec.end_date),
            },
            fields=fields,
            primary_key=primary_key,
        )
        for sequence, exchange in enumerate(("SSE", "SZSE"), start=1)
    )
    return TushareRequestPlan(build_spec_hash=spec.content_hash, requests=requests)


def _default_limiter(policy: TushareExecutionPolicy) -> AcquisitionLimiter:
    return cast(
        AcquisitionLimiter,
        Limiter(
            Rate(policy.requests_per_minute, Duration.MINUTE),
            max_delay=Duration.MINUTE,
            retry_until_max_delay=True,
        ),
    )


def _write_frame_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        pq.write_table(  # pyright: ignore[reportUnknownMemberType]
            table,
            temporary,
            compression="zstd",
            data_page_version="1.0",
            use_dictionary=False,
            version="2.6",
            write_statistics=True,
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_frame(request: TushareRequest, frame: pd.DataFrame) -> None:
    columns = tuple(str(column) for column in frame.columns)
    if columns != request.fields:
        raise TushareAcquisitionError(
            ReasonCode.SCHEMA_INVALID, "provider response columns differ from the locked request"
        )
    if bool(frame.duplicated(subset=list(request.primary_key)).any()):
        raise TushareAcquisitionError(
            ReasonCode.SCHEMA_INVALID, "provider response contains duplicate primary keys"
        )
    for field in request.primary_key:
        requested_value = request.params.get(field)
        if requested_value is not None and not frame.empty:
            returned = {str(value) for value in frame[field].tolist()}
            if returned != {requested_value}:
                raise TushareAcquisitionError(
                    ReasonCode.SCHEMA_INVALID,
                    "provider response repeats a primary key across request chunks",
                )
    date_field = next(
        (field for field in ("trade_date", "cal_date") if field in request.primary_key),
        None,
    )
    if (
        date_field is not None
        and "start_date" in request.params
        and "end_date" in request.params
        and not frame.empty
    ):
        returned_dates = frame[date_field].astype(str)
        if not bool(
            returned_dates.between(
                request.params["start_date"], request.params["end_date"], inclusive="both"
            ).all()
        ):
            raise TushareAcquisitionError(
                ReasonCode.SCHEMA_INVALID,
                "provider response repeats a primary key across request chunks",
            )


class TusharePlanExecutor:
    """Execute only an explicit request plan and persist secret-free resumable checkpoints."""

    def __init__(
        self,
        client: TushareQueryClient,
        policy: TushareExecutionPolicy,
        *,
        limiter: AcquisitionLimiter | None = None,
        now: Callable[[], datetime] | None = None,
        retryable_errors: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
    ) -> None:
        self._client = client
        self._policy = policy
        self._limiter = limiter or _default_limiter(policy)
        self._now = now or (lambda: datetime.now(UTC))
        self._retryable_errors = retryable_errors
        self._package_version = version("tushare")

    def execute(self, plan: TushareRequestPlan, staging_root: Path) -> TushareRequestLedger:
        checkpoints_root = staging_root / "checkpoints"
        entries_by_sequence: dict[int, RequestLedgerEntry] = {}
        pending: list[TushareRequest] = []
        for request in plan.requests:
            response_relative = Path("raw-requests") / f"sha256-{request.content_hash}.parquet"
            response_path = staging_root / response_relative
            checkpoint_path = checkpoints_root / f"sha256-{request.content_hash}.json"
            reused = self._load_checkpoint(request, response_path, checkpoint_path)
            if reused is not None:
                entries_by_sequence[request.sequence] = reused
            else:
                pending.append(request)

        def execute_pending(request: TushareRequest) -> RequestLedgerEntry:
            response_relative = Path("raw-requests") / f"sha256-{request.content_hash}.parquet"
            return self._execute_one(
                request,
                response_relative,
                staging_root / response_relative,
                checkpoints_root / f"sha256-{request.content_hash}.json",
            )

        workers = min(4, max(1, self._policy.requests_per_minute // 60))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="tushare-acquisition"
        ) as pool:
            for offset in range(0, len(pending), workers):
                batch = pending[offset : offset + workers]
                futures = [pool.submit(execute_pending, request) for request in batch]
                for request, future in zip(batch, futures, strict=True):
                    entries_by_sequence[request.sequence] = future.result()
        entries = [entries_by_sequence[request.sequence] for request in plan.requests]
        self._validate_cross_request_primary_keys(plan, staging_root)
        ledger = TushareRequestLedger(
            plan_hash=plan.content_hash,
            execution_policy_hash=self._policy.content_hash,
            entries=tuple(entries),
        )
        atomic_write_bytes(
            staging_root / "request-ledgers" / f"sha256-{ledger.content_hash}.json",
            ledger.canonical_bytes(),
        )
        return ledger

    @staticmethod
    def _validate_cross_request_primary_keys(plan: TushareRequestPlan, staging_root: Path) -> None:
        partitions: set[tuple[str, str, str]] = set()
        date_ranges: dict[str, list[tuple[str, str]]] = {}
        seen: dict[str, set[tuple[object, ...]]] = {}
        for request in plan.requests:
            partition: tuple[str, str, str] | None = None
            if "exchange" in request.primary_key and "exchange" in request.params:
                partition = (request.endpoint, "exchange", request.params["exchange"])
            elif "trade_date" in request.primary_key and "trade_date" in request.params:
                partition = (request.endpoint, "trade_date", request.params["trade_date"])
            if partition is not None:
                if partition in partitions:
                    raise TushareAcquisitionError(
                        ReasonCode.SCHEMA_INVALID,
                        "request plan repeats a primary-key partition",
                    )
                partitions.add(partition)
                continue
            if (
                "trade_date" in request.primary_key
                and "start_date" in request.params
                and "end_date" in request.params
            ):
                candidate = (request.params["start_date"], request.params["end_date"])
                ranges = date_ranges.setdefault(request.endpoint, [])
                if any(
                    not (candidate[1] < existing[0] or existing[1] < candidate[0])
                    for existing in ranges
                ):
                    raise TushareAcquisitionError(
                        ReasonCode.SCHEMA_INVALID,
                        "request plan has overlapping primary-key date partitions",
                    )
                ranges.append(candidate)
                continue
            response_path = staging_root / "raw-requests" / f"sha256-{request.content_hash}.parquet"
            table = pq.read_table(response_path)  # pyright: ignore[reportUnknownMemberType]
            endpoint_keys = seen.setdefault(request.endpoint, set())
            for row in table.to_pylist():
                key = tuple(row[field] for field in request.primary_key)
                if key in endpoint_keys:
                    raise TushareAcquisitionError(
                        ReasonCode.SCHEMA_INVALID,
                        "provider response repeats a primary key across request chunks",
                    )
                endpoint_keys.add(key)

    def _load_checkpoint(
        self, request: TushareRequest, response_path: Path, checkpoint_path: Path
    ) -> RequestLedgerEntry | None:
        if not checkpoint_path.exists() and not response_path.exists():
            return None
        if not checkpoint_path.is_file() or not response_path.is_file():
            raise TushareAcquisitionError(
                ReasonCode.ARTIFACT_CORRUPTED, "request checkpoint is incomplete"
            )
        try:
            entry = RequestLedgerEntry.model_validate_json(checkpoint_path.read_bytes())
            if entry.request_hash != request.content_hash:
                raise ValueError("request hash mismatch")
            verify_file(response_path, entry.response_sha256)
            table = pq.read_table(response_path)  # pyright: ignore[reportUnknownMemberType]
            if (
                tuple(table.column_names) != request.fields
                or table.num_rows != entry.response_row_count
                or table.select(list(request.primary_key))
                .group_by(list(request.primary_key))
                .aggregate([])
                .num_rows
                != table.num_rows
            ):
                raise ValueError("response metadata mismatch")
        except (OSError, ValueError, ArtifactIntegrityError):
            raise TushareAcquisitionError(
                ReasonCode.ARTIFACT_CORRUPTED, "request checkpoint failed verification"
            ) from None
        return entry

    def _execute_one(
        self,
        request: TushareRequest,
        response_relative: Path,
        response_path: Path,
        checkpoint_path: Path,
    ) -> RequestLedgerEntry:
        started_at = self._now()
        attempt_count = 0

        def query() -> pd.DataFrame:
            nonlocal attempt_count
            attempt_count += 1
            acquired = self._limiter.try_acquire("tushare-snapshot")
            if not acquired:
                raise TushareAcquisitionError(
                    ReasonCode.SOURCE_INCOMPLETE, "configured Tushare rate limit was not acquired"
                )
            return self._client.query(
                request.endpoint,
                fields=",".join(request.fields),
                **request.params,
            )

        try:
            retryer = Retrying(
                stop=stop_after_attempt(self._policy.max_attempts),
                wait=wait_exponential(
                    multiplier=self._policy.retry_min_seconds,
                    min=self._policy.retry_min_seconds,
                    max=self._policy.retry_max_seconds,
                ),
                retry=retry_if_exception_type(self._retryable_errors),
                reraise=True,
            )
            frame = retryer(query)
            _validate_frame(request, frame)
            frame = frame.sort_values(list(request.primary_key), kind="mergesort").reset_index(
                drop=True
            )
        except TushareAcquisitionError:
            raise
        except Exception:
            raise TushareAcquisitionError(
                ReasonCode.SOURCE_INCOMPLETE,
                f"Tushare request failed after {attempt_count} attempt(s); "
                "provider detail suppressed",
            ) from None

        _write_frame_atomic(frame, response_path)
        entry = RequestLedgerEntry(
            request_hash=request.content_hash,
            request_sequence=request.sequence,
            endpoint=request.endpoint,
            normalized_params=request.params,
            requested_fields=request.fields,
            attempt_count=attempt_count,
            started_at=started_at,
            completed_at=self._now(),
            response_row_count=len(frame),
            response_fields=tuple(str(column) for column in frame.columns),
            response_sha256=sha256_file(response_path),
            response_logical_path=response_relative.as_posix(),
            tushare_package_version=self._package_version,
        )
        atomic_write_bytes(checkpoint_path, entry.canonical_bytes())
        return entry


def iter_acquired_response_tables(
    plan: TushareRequestPlan,
    ledger: TushareRequestLedger,
    acquisition_root: Path,
    *,
    endpoints: frozenset[str] | None = None,
) -> Iterator[tuple[TushareRequest, RequestLedgerEntry, pa.Table]]:
    """Yield verified response tables without materializing the complete acquisition."""

    if ledger.plan_hash != plan.content_hash or len(ledger.entries) != len(plan.requests):
        raise TushareAcquisitionError(
            ReasonCode.SOURCE_INCOMPLETE, "request ledger does not cover the locked plan"
        )
    available_endpoints = {item.endpoint for item in plan.requests}
    selected_endpoints = endpoints or frozenset(available_endpoints)
    if not selected_endpoints <= available_endpoints:
        raise TushareAcquisitionError(
            ReasonCode.SOURCE_INCOMPLETE,
            "requested endpoint subset is absent from the acquisition plan",
        )
    for request, entry in zip(plan.requests, ledger.entries, strict=True):
        if (
            entry.request_hash != request.content_hash
            or entry.request_sequence != request.sequence
            or entry.endpoint != request.endpoint
            or entry.normalized_params != request.params
            or entry.requested_fields != request.fields
        ):
            raise TushareAcquisitionError(
                ReasonCode.SOURCE_INCOMPLETE, "request ledger entry differs from the locked plan"
            )
        if request.endpoint not in selected_endpoints:
            continue
        path = acquisition_root / entry.response_logical_path
        try:
            verify_file(path, entry.response_sha256)
            table = pq.read_table(path)  # pyright: ignore[reportUnknownMemberType]
        except (OSError, ArtifactIntegrityError):
            raise TushareAcquisitionError(
                ReasonCode.ARTIFACT_CORRUPTED, "acquired response failed hash verification"
            ) from None
        if (
            tuple(table.column_names) != request.fields
            or table.num_rows != entry.response_row_count
        ):
            raise TushareAcquisitionError(
                ReasonCode.SCHEMA_INVALID, "acquired response metadata differs from request ledger"
            )
        yield request, entry, table


def load_acquired_rows(
    plan: TushareRequestPlan,
    ledger: TushareRequestLedger,
    acquisition_root: Path,
    *,
    endpoints: frozenset[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Verify and materialize only the selected provider-shaped endpoint rows."""

    selected_endpoints = endpoints or frozenset(item.endpoint for item in plan.requests)
    rows_by_endpoint: dict[str, list[dict[str, str]]] = {
        endpoint: [] for endpoint in sorted(selected_endpoints)
    }
    primary_keys: dict[str, tuple[str, ...]] = {}
    for request, _entry, table in iter_acquired_response_tables(
        plan, ledger, acquisition_root, endpoints=selected_endpoints
    ):
        primary_keys[request.endpoint] = request.primary_key
        rows_by_endpoint[request.endpoint].extend(provider_table_rows(request, table))
    for endpoint, rows in rows_by_endpoint.items():
        keys = primary_keys[endpoint]
        rows.sort(key=lambda row: tuple(row[field] for field in keys))
        values = [tuple(row[field] for field in keys) for row in rows]
        if len(values) != len(set(values)):
            raise TushareAcquisitionError(
                ReasonCode.SCHEMA_INVALID,
                "acquired endpoint contains duplicate primary keys after materialization",
            )
    return rows_by_endpoint


def provider_table_rows(request: TushareRequest, table: pa.Table) -> tuple[dict[str, str], ...]:
    """Convert one bounded provider response to its locked string representation."""

    return tuple(
        {field: _provider_string(row[field]) for field in request.fields}
        for row in table.to_pylist()
    )


def request_ledger_table(ledger: TushareRequestLedger) -> pa.Table:
    """Convert the secret-free request ledger to the canonical snapshot ledger table."""

    rows = [
        {
            "endpoint": entry.endpoint,
            "request_sequence": entry.request_sequence,
            "request_hash": entry.request_hash,
            "normalized_params_json": json.dumps(
                entry.normalized_params, sort_keys=True, separators=(",", ":")
            ),
            "requested_fields": ",".join(entry.requested_fields),
            "attempt_count": entry.attempt_count,
            "started_at": entry.started_at.astimezone(UTC),
            "completed_at": entry.completed_at.astimezone(UTC),
            "response_row_count": entry.response_row_count,
            "response_fields": ",".join(entry.response_fields),
            "response_sha256": entry.response_sha256,
            "tushare_package_version": entry.tushare_package_version,
            "rate_limit_outcome": entry.rate_limit_outcome,
            "network_used": True,
        }
        for entry in ledger.entries
    ]
    return pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                pa.field("endpoint", pa.string(), nullable=False),
                pa.field("request_sequence", pa.int32(), nullable=False),
                pa.field("request_hash", pa.string(), nullable=False),
                pa.field("normalized_params_json", pa.string(), nullable=False),
                pa.field("requested_fields", pa.string(), nullable=False),
                pa.field("attempt_count", pa.int32(), nullable=False),
                pa.field("started_at", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("completed_at", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("response_row_count", pa.int64(), nullable=False),
                pa.field("response_fields", pa.string(), nullable=False),
                pa.field("response_sha256", pa.string(), nullable=False),
                pa.field("tushare_package_version", pa.string(), nullable=False),
                pa.field("rate_limit_outcome", pa.string(), nullable=False),
                pa.field("network_used", pa.bool_(), nullable=False),
            ]
        ),
    )


def _provider_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.strftime("%Y%m%d")
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)
