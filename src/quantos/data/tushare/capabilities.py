"""Bounded, read-only capability probes for required Tushare endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, cast

import pandas as pd
import tushare  # pyright: ignore[reportMissingTypeStubs]
from pydantic import Field
from pyrate_limiter import Duration, Limiter, Rate  # pyright: ignore[reportMissingTypeStubs]

from quantos.contracts.base import CanonicalContract


class TushareQueryClient(Protocol):
    def query(self, api_name: str, fields: str = "", **kwargs: object) -> pd.DataFrame: ...


class EndpointProbeStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    BLOCKED = "BLOCKED"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"


class EndpointCapability(CanonicalContract):
    schema_version: Literal["endpoint-capability/v1"] = "endpoint-capability/v1"
    probe_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    status: EndpointProbeStatus
    requested_fields: tuple[str, ...]
    returned_fields: tuple[str, ...] = ()
    row_count: int = Field(ge=0, default=0)
    error_type: str | None = None
    error_message: str | None = None


class CapabilityReport(CanonicalContract):
    schema_version: Literal["tushare-capability-report/v1"] = "tushare-capability-report/v1"
    probed_at: datetime
    probe_trade_date: date | None
    request_count: int = Field(ge=0)
    request_budget: int = Field(gt=0)
    endpoints: tuple[EndpointCapability, ...]

    @property
    def all_required_available(self) -> bool:
        return bool(self.endpoints) and all(
            item.status is EndpointProbeStatus.AVAILABLE for item in self.endpoints
        )


@dataclass(frozen=True)
class EndpointSpec:
    probe_id: str
    name: str
    fields: tuple[str, ...]
    params: Mapping[str, object]
    needs_trade_date: bool = False


@dataclass(frozen=True)
class _ProbeOutcome:
    capability: EndpointCapability
    frame: pd.DataFrame | None


MAX_CAPABILITY_REQUESTS = 12


def _date_string(value: date) -> str:
    return value.strftime("%Y%m%d")


def _query_one(
    client: TushareQueryClient,
    spec: EndpointSpec,
    trade_date: date | None,
) -> _ProbeOutcome:
    if spec.needs_trade_date and trade_date is None:
        return _ProbeOutcome(
            EndpointCapability(
                probe_id=spec.probe_id,
                endpoint=spec.name,
                status=EndpointProbeStatus.BLOCKED_DEPENDENCY,
                requested_fields=spec.fields,
                error_type="TradeCalendarUnavailable",
                error_message="required trade calendar probe did not return an open date",
            ),
            None,
        )
    params = dict(spec.params)
    if spec.needs_trade_date:
        params["trade_date"] = _date_string(cast(date, trade_date))
    try:
        frame = client.query(spec.name, fields=",".join(spec.fields), **params)
    except Exception as error:  # provider exceptions do not share a stable public base class
        # Provider text is discarded: reports expose only a stable class and never risk
        # persisting tokens, URLs, account identifiers, or SDK request payloads.
        status, message = _classify_provider_error(error)
        return _ProbeOutcome(
            EndpointCapability(
                probe_id=spec.probe_id,
                endpoint=spec.name,
                status=status,
                requested_fields=spec.fields,
                error_type=type(error).__name__,
                error_message=message,
            ),
            None,
        )
    returned_fields = tuple(str(column) for column in frame.columns)
    missing = set(spec.fields) - set(returned_fields)
    capability = EndpointCapability(
        probe_id=spec.probe_id,
        endpoint=spec.name,
        status=(EndpointProbeStatus.SCHEMA_MISMATCH if missing else EndpointProbeStatus.AVAILABLE),
        requested_fields=spec.fields,
        returned_fields=returned_fields,
        row_count=len(frame),
        error_type="MissingFields" if missing else None,
        error_message=",".join(sorted(missing)) if missing else None,
    )
    return _ProbeOutcome(capability, frame)


def _classify_provider_error(
    error: Exception,
) -> tuple[EndpointProbeStatus, str]:
    raw = str(error).lower()
    if any(
        marker in raw
        for marker in (
            "每分钟",
            "每小时",
            "每天最多",
            "访问频次",
            "rate limit",
            "too many request",
            "frequency",
        )
    ):
        return (
            EndpointProbeStatus.RATE_LIMITED,
            "provider rate limit reached; raw message suppressed",
        )
    if any(
        marker in raw for marker in ("权限", "积分", "permission", "not authorized", "unauthorized")
    ):
        return (
            EndpointProbeStatus.PERMISSION_DENIED,
            "provider permission denied; raw message suppressed",
        )
    return EndpointProbeStatus.BLOCKED, "provider request failed; raw message suppressed"


def _calendar_specs(probe_day: date) -> tuple[EndpointSpec, ...]:
    calendar_start = probe_day - timedelta(days=14)
    fields = ("exchange", "cal_date", "is_open", "pretrade_date")
    return tuple(
        EndpointSpec(
            probe_id=f"trade_cal:{exchange}",
            name="trade_cal",
            fields=fields,
            params={
                "exchange": exchange,
                "start_date": _date_string(calendar_start),
                "end_date": _date_string(probe_day),
            },
        )
        for exchange in ("SSE", "SZSE")
    )


def _endpoint_specs(probe_day: date) -> tuple[EndpointSpec, ...]:
    range_start = probe_day - timedelta(days=400)
    stock_fields = (
        "ts_code",
        "symbol",
        "name",
        "exchange",
        "list_status",
        "list_date",
        "delist_date",
    )
    return (
        EndpointSpec(
            probe_id="stock_basic:L",
            name="stock_basic",
            fields=stock_fields,
            params={"exchange": "", "list_status": "L"},
        ),
        EndpointSpec(
            probe_id="daily:recent_open_session",
            name="daily",
            fields=(
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "vol",
                "amount",
            ),
            params={},
            needs_trade_date=True,
        ),
        EndpointSpec(
            probe_id="adj_factor:recent_open_session",
            name="adj_factor",
            fields=("ts_code", "trade_date", "adj_factor"),
            params={},
            needs_trade_date=True,
        ),
        EndpointSpec(
            probe_id="index_daily:hs300_recent_range",
            name="index_daily",
            fields=(
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "vol",
                "amount",
            ),
            params={
                "ts_code": "000300.SH",
                "start_date": _date_string(range_start),
                "end_date": _date_string(probe_day),
            },
        ),
        EndpointSpec(
            probe_id="index_weight:hs300_recent_range",
            name="index_weight",
            fields=("index_code", "con_code", "trade_date", "weight"),
            params={
                "index_code": "000300.SH",
                "start_date": _date_string(range_start),
                "end_date": _date_string(probe_day),
            },
        ),
        EndpointSpec(
            probe_id="stock_st:recent_open_session",
            name="stock_st",
            fields=("ts_code", "trade_date", "type"),
            params={},
            needs_trade_date=True,
        ),
        EndpointSpec(
            probe_id="suspend_d:recent_open_session",
            name="suspend_d",
            fields=("ts_code", "trade_date", "suspend_type", "suspend_timing"),
            params={},
            needs_trade_date=True,
        ),
        EndpointSpec(
            probe_id="stk_limit:recent_open_session",
            name="stk_limit",
            fields=("ts_code", "trade_date", "pre_close", "up_limit", "down_limit"),
            params={},
            needs_trade_date=True,
        ),
        *(
            EndpointSpec(
                probe_id=f"stock_basic:{status}",
                name="stock_basic",
                fields=stock_fields,
                params={"exchange": "", "list_status": status},
            )
            for status in ("D", "P")
        ),
    )


def _latest_open_date(frame: pd.DataFrame | None) -> date | None:
    if frame is None or not {"is_open", "cal_date"}.issubset(frame.columns):
        return None
    open_dates = frame.loc[frame["is_open"] == 1, "cal_date"]
    if open_dates.empty:
        return None
    try:
        return datetime.strptime(str(open_dates.max()), "%Y%m%d").date()
    except ValueError:
        return None


class TushareSnapshotSource:
    """The only first-phase network source; deliberately not a generic provider interface."""

    def __init__(self, token: str, client: TushareQueryClient | None = None) -> None:
        if not token:
            raise ValueError("Tushare token is required")
        self._client = client or cast(TushareQueryClient, tushare.pro_api(token))
        self._probe_limiters = (
            {}
            if client is not None
            else {
                endpoint: Limiter(
                    Rate(1, Duration.MINUTE),
                    max_delay=3 * Duration.MINUTE,
                    retry_until_max_delay=True,
                )
                for endpoint in ("trade_cal", "stock_basic")
            }
        )

    @property
    def client(self) -> TushareQueryClient:
        """Expose the initialized SDK client only to the snapshot acquisition layer."""

        return self._client

    def probe_capabilities(self, *, today: date | None = None) -> CapabilityReport:
        """Use a fixed request budget; no retries and no quota saturation are permitted."""

        probe_day = today or datetime.now(UTC).date()
        calendar_specs = _calendar_specs(probe_day)
        primary_calendar = self._query_probe(calendar_specs[0], trade_date=None)
        trade_date = _latest_open_date(primary_calendar.frame)
        endpoint_specs = _endpoint_specs(probe_day)
        primary_endpoints = tuple(
            self._query_probe(spec, trade_date=trade_date) for spec in endpoint_specs[:-2]
        )
        secondary_calendar = self._query_probe(calendar_specs[1], trade_date=None)
        lifecycle_endpoints = tuple(
            self._query_probe(spec, trade_date=trade_date) for spec in endpoint_specs[-2:]
        )
        calendar_outcomes = (primary_calendar, secondary_calendar)
        endpoint_outcomes = (*primary_endpoints, *lifecycle_endpoints)
        capabilities = tuple(
            outcome.capability for outcome in (*calendar_outcomes, *endpoint_outcomes)
        )
        request_count = sum(
            item.status is not EndpointProbeStatus.BLOCKED_DEPENDENCY for item in capabilities
        )
        if request_count > MAX_CAPABILITY_REQUESTS:
            raise RuntimeError("capability probe exceeded its fixed request budget")
        return CapabilityReport(
            probed_at=datetime.now(UTC),
            probe_trade_date=trade_date,
            request_count=request_count,
            request_budget=MAX_CAPABILITY_REQUESTS,
            endpoints=capabilities,
        )

    def _query_probe(self, spec: EndpointSpec, trade_date: date | None) -> _ProbeOutcome:
        limiter = self._probe_limiters.get(spec.name)
        if limiter is not None:
            limiter.try_acquire(f"capability:{spec.name}")
        return _query_one(self._client, spec, trade_date)
