"""Historical universe resolution from a verified Qlib view sidecar."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import cast

import pyarrow.parquet as pq

from quantos.contracts.research_execution import (
    HistoricalUniverseMember,
    HistoricalUniverseResolution,
)
from quantos.contracts.status import ReasonCode
from quantos.data.qlib_view import QlibViewBuildError, verify_qlib_view


class QlibResearchError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def resolve_historical_universe(
    view_path: Path,
    *,
    expected_view_hash: str,
    expected_snapshot_hash: str,
    index_id: str,
    as_of_date: date,
    decision_time: datetime,
) -> HistoricalUniverseResolution:
    """Resolve only intervals effective and available at the requested decision time."""

    try:
        manifest = verify_qlib_view(view_path)
    except QlibViewBuildError as error:
        raise QlibResearchError(error.reason_code, str(error)) from None
    if (
        manifest.view_hash != expected_view_hash
        or manifest.source_snapshot_hash != expected_snapshot_hash
    ):
        raise QlibResearchError(
            ReasonCode.SNAPSHOT_HASH_MISMATCH,
            "Qlib view or source snapshot hash does not match the resolved experiment",
        )
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise QlibResearchError(ReasonCode.SCHEMA_INVALID, "decision_time must be timezone-aware")
    if decision_time.date() != as_of_date:
        raise QlibResearchError(
            ReasonCode.SCHEMA_INVALID, "decision_time date must equal as_of_date"
        )
    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        view_path / "sidecars" / "historical-universe.parquet"
    ).to_pylist()
    selected = [
        row
        for row in table
        if row["index_id"] == index_id
        and cast(date, row["effective_from"]) <= as_of_date <= cast(date, row["effective_to"])
        and cast(datetime, row["available_at"]) <= decision_time
    ]
    members = tuple(
        HistoricalUniverseMember(
            instrument_id=cast(str, row["instrument_id"]),
            qlib_id=cast(str, row["qlib_id"]),
            weight_percent=cast(float, row["weight_percent"]),
        )
        for row in sorted(selected, key=lambda item: cast(str, item["instrument_id"]))
    )
    if not members:
        raise QlibResearchError(
            ReasonCode.SOURCE_INCOMPLETE,
            "no historical universe is both effective and available at decision_time",
        )
    return HistoricalUniverseResolution(
        qlib_view_hash=manifest.view_hash,
        source_snapshot_hash=manifest.source_snapshot_hash,
        index_id=index_id,
        as_of_date=as_of_date,
        decision_time=decision_time,
        members=members,
    )
