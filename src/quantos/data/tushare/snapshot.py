"""Publish a live Tushare acquisition as an immutable canonical snapshot."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

from quantos.artifacts.store import (
    ArtifactConflictError,
    atomic_write_bytes,
    publish_directory,
)
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.refs import DataSnapshotRef
from quantos.contracts.snapshot import (
    DEFAULT_SYNTHETIC_ENDPOINTS,
    DataQualityPolicy,
    DataSnapshotManifest,
    SnapshotBuildSpec,
    SnapshotFileManifest,
    SnapshotSourceKind,
)
from quantos.contracts.status import ReasonCode
from quantos.data.snapshot import (
    RawCanonicalReconciliation,
    SnapshotBuildError,
    SnapshotBuildResult,
    evaluate_snapshot_quality_streaming,
    normalize_tushare_endpoint_rows,
    normalize_tushare_tables,
    plain_manifest,
    table_manifest,
    verify_snapshot,
    write_parquet,
)
from quantos.data.tushare.acquisition import (
    TushareAcquisitionError,
    TusharePlanExecutor,
    TushareRequestLedger,
    TushareRequestPlan,
    iter_acquired_response_tables,
    load_acquired_rows,
    plan_tushare_calendar_requests,
    plan_tushare_requests,
    provider_table_rows,
    request_ledger_table,
)

_SMALL_ENDPOINTS = frozenset({"stock_basic", "trade_cal", "index_daily", "index_weight"})
_STREAMING_ENDPOINTS = frozenset({"daily", "adj_factor", "stock_st", "suspend_d", "stk_limit"})


def _normalize_acquired_tables(
    spec: SnapshotBuildSpec,
    plan: TushareRequestPlan,
    ledger: TushareRequestLedger,
    acquisition_root: Path,
) -> tuple[dict[str, pa.Table], RawCanonicalReconciliation]:
    """Normalize bounded response chunks without materializing all raw rows."""

    small = load_acquired_rows(plan, ledger, acquisition_root, endpoints=_SMALL_ENDPOINTS)
    base_raw = {endpoint: small.get(endpoint, []) for endpoint in DEFAULT_SYNTHETIC_ENDPOINTS}
    base_tables = normalize_tushare_tables(base_raw, spec)
    eligible = {
        cast(str, row["instrument_id"])
        for row in base_tables["index_membership"].select(["instrument_id"]).to_pylist()
    }
    chunks: dict[str, list[pa.Table]] = {
        "bars": [],
        "adjustment_factors": [],
        "st_status": [],
        "suspensions": [],
        "price_limits": [],
    }
    expected_counts = {name: table.num_rows for name, table in base_tables.items()}
    bar_pre_closes_by_trade_date: dict[str, dict[str, str]] = {}
    adjustment_dates: set[str] = set()
    for request, _entry, table in iter_acquired_response_tables(
        plan, ledger, acquisition_root, endpoints=_STREAMING_ENDPOINTS
    ):
        rows = provider_table_rows(request, table)
        scoped: list[dict[str, str]]
        if request.endpoint == "daily":
            scoped = [row for row in rows if row["ts_code"] in eligible]
            scoped.sort(key=lambda row: (row["trade_date"], row["ts_code"]))
            trade_date = request.params["trade_date"]
            bar_pre_closes_by_trade_date[trade_date] = {
                row["ts_code"]: row["pre_close"] for row in scoped
            }
        elif request.endpoint == "adj_factor":
            trade_date = request.params["trade_date"]
            try:
                bar_pre_closes = bar_pre_closes_by_trade_date[trade_date]
            except KeyError:
                raise SnapshotBuildError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "adjustment-factor chunk does not follow its daily-bar partition",
                ) from None
            scoped = [row for row in rows if row["ts_code"] in bar_pre_closes]
            scoped.sort(key=lambda row: (row["trade_date"], row["ts_code"]))
            adjustment_dates.add(trade_date)
        elif request.endpoint == "stk_limit":
            trade_date = request.params["trade_date"]
            try:
                bar_pre_closes = bar_pre_closes_by_trade_date[trade_date]
            except KeyError:
                raise SnapshotBuildError(
                    ReasonCode.SOURCE_INCOMPLETE,
                    "price-limit chunk has no corresponding daily-bar partition",
                ) from None
            scoped = []
            for row in rows:
                if row["ts_code"] not in bar_pre_closes:
                    continue
                canonical_row = dict(row)
                if canonical_row["pre_close"] == "":
                    canonical_row["pre_close"] = bar_pre_closes[row["ts_code"]]
                scoped.append(canonical_row)
            scoped.sort(key=lambda row: (row["trade_date"], row["ts_code"]))
        else:
            scoped = [row for row in rows if row["ts_code"] in eligible]
            scoped.sort(key=lambda row: (row["trade_date"], row["ts_code"]))
        canonical_name, canonical_chunk = normalize_tushare_endpoint_rows(
            request.endpoint, scoped, spec
        )
        chunks[canonical_name].append(canonical_chunk)
        expected_counts[canonical_name] += canonical_chunk.num_rows
    if set(bar_pre_closes_by_trade_date) != adjustment_dates:
        raise SnapshotBuildError(
            ReasonCode.SOURCE_INCOMPLETE,
            "daily-bar partitions are missing adjustment-factor responses",
        )
    tables = dict(base_tables)
    for name, parts in chunks.items():
        tables[name] = pa.concat_tables(parts) if parts else base_tables[name]
    raw_counts: dict[str, int] = {}
    for entry in ledger.entries:
        raw_counts[entry.endpoint] = raw_counts.get(entry.endpoint, 0) + entry.response_row_count
    return tables, RawCanonicalReconciliation(
        raw_row_counts=raw_counts,
        expected_canonical_row_counts=expected_counts,
    )


class LiveTushareSnapshotBuilder:
    """Offline publication boundary; it never owns or calls a Tushare client."""

    def __init__(self, policy: DataQualityPolicy | None = None) -> None:
        self._policy = policy or DataQualityPolicy(policy_id="default-live-tushare-dq/v1")

    def build(
        self,
        spec: SnapshotBuildSpec,
        plan: TushareRequestPlan,
        ledger: TushareRequestLedger,
        acquisition_root: Path,
        output_root: Path,
    ) -> SnapshotBuildResult:
        if spec.source_kind is not SnapshotSourceKind.TUSHARE:
            raise SnapshotBuildError(
                ReasonCode.SCHEMA_INVALID, "live snapshot requires source_kind=TUSHARE"
            )
        if set(spec.required_endpoints) != set(DEFAULT_SYNTHETIC_ENDPOINTS):
            raise SnapshotBuildError(
                ReasonCode.SOURCE_INCOMPLETE,
                "live snapshot must contain every required first-stage endpoint",
            )
        if plan.build_spec_hash != spec.content_hash:
            raise SnapshotBuildError(
                ReasonCode.SOURCE_INCOMPLETE, "request plan is not bound to the snapshot spec"
            )
        try:
            tables, reconciliation = _normalize_acquired_tables(
                spec, plan, ledger, acquisition_root
            )
        except TushareAcquisitionError as error:
            raise SnapshotBuildError(error.reason_code, str(error)) from None
        report = evaluate_snapshot_quality_streaming(reconciliation, tables, spec, self._policy)
        if not report.passed:
            reason = next(
                gate.reason_code
                for gate in report.gates
                if not gate.passed and gate.reason_code is not None
            )
            raise SnapshotBuildError(
                reason,
                "snapshot failed data-quality gates",
                quality_report=report,
            )

        output_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".snapshot-staging-", dir=output_root))
        try:
            files: list[SnapshotFileManifest] = []
            for request, entry in zip(plan.requests, ledger.entries, strict=True):
                source = acquisition_root / entry.response_logical_path
                relative = (
                    Path("raw")
                    / request.endpoint
                    / f"{request.sequence:06d}-sha256-{request.content_hash}.parquet"
                )
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                table = pq.read_table(target)  # pyright: ignore[reportUnknownMemberType]
                files.append(
                    table_manifest(
                        target,
                        staging,
                        f"raw_{request.endpoint}_{request.sequence:06d}",
                        table,
                    )
                )

            build_path = staging / "snapshot-build.json"
            atomic_write_bytes(build_path, spec.canonical_bytes())
            files.append(plain_manifest(build_path, staging, "application/json"))
            plan_path = staging / "request-plan.json"
            atomic_write_bytes(plan_path, plan.canonical_bytes())
            files.append(plain_manifest(plan_path, staging, "application/json"))
            ledger_json_path = staging / "request-ledger.json"
            atomic_write_bytes(ledger_json_path, ledger.canonical_bytes())
            files.append(plain_manifest(ledger_json_path, staging, "application/json"))
            quality_path = staging / "quality-report.json"
            atomic_write_bytes(quality_path, report.canonical_bytes())
            files.append(plain_manifest(quality_path, staging, "application/json"))

            ledger_table = request_ledger_table(ledger)
            ledger_path = staging / "request-ledger.parquet"
            write_parquet(ledger_table, ledger_path)
            files.append(table_manifest(ledger_path, staging, "request_ledger", ledger_table))

            canonical_root = staging / "canonical"
            for name in sorted(tables):
                table = tables[name]
                path = canonical_root / f"{name}.parquet"
                write_parquet(table, path)
                files.append(table_manifest(path, staging, name, table))

            manifest = DataSnapshotManifest.create(
                dataset_id=spec.dataset_id,
                source_kind=spec.source_kind,
                provider=spec.provider,
                start_date=spec.start_date,
                end_date=spec.end_date,
                build_spec_hash=spec.content_hash,
                quality_policy_hash=self._policy.content_hash,
                quality_report_hash=report.content_hash,
                normalizer_version=spec.normalizer_version,
                files=tuple(sorted(files, key=lambda item: item.logical_path)),
                limitations=("SINGLE_SOURCE_NON_VINTAGE",),
                created_at=datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )

            destination = output_root / f"sha256-{manifest.snapshot_hash}"
            if destination.exists():
                existing = verify_snapshot(destination)
                if existing.snapshot_hash != manifest.snapshot_hash:
                    raise ArtifactConflictError(
                        f"immutable destination already exists: {destination}"
                    )
                shutil.rmtree(staging)
                staging = destination
                manifest = existing
            else:
                publish_directory(staging, destination)
                staging = destination

            verified = verify_snapshot(staging)
            size_bytes = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file())
            reference = DataSnapshotRef(
                sha256=verified.snapshot_hash,
                size_bytes=size_bytes,
                media_type="application/vnd.quantos.snapshot+directory",
                logical_path=f"data/snapshots/{staging.name}",
            )
            return SnapshotBuildResult(reference, verified, report, staging)
        finally:
            if staging.exists() and staging.name.startswith(".snapshot-staging-"):
                shutil.rmtree(staging)


class LiveTushareAcquisitionService:
    """Two-stage calendar-first orchestration with one shared bounded executor."""

    def __init__(
        self,
        executor: TusharePlanExecutor,
        builder: LiveTushareSnapshotBuilder | None = None,
    ) -> None:
        self._executor = executor
        self._builder = builder or LiveTushareSnapshotBuilder()

    def acquire_and_build(
        self,
        spec: SnapshotBuildSpec,
        acquisition_root: Path,
        output_root: Path,
    ) -> SnapshotBuildResult:
        calendar_plan = plan_tushare_calendar_requests(spec)
        calendar_ledger = self._executor.execute(calendar_plan, acquisition_root)
        calendar_rows = load_acquired_rows(calendar_plan, calendar_ledger, acquisition_root)[
            "trade_cal"
        ]
        try:
            sessions = sorted(
                {
                    datetime.strptime(row["cal_date"], "%Y%m%d").date()
                    for row in calendar_rows
                    if row["is_open"] == "1"
                }
            )
        except (KeyError, ValueError):
            raise SnapshotBuildError(
                ReasonCode.SCHEMA_INVALID, "trade calendar cannot resolve open sessions"
            ) from None
        if not sessions:
            raise SnapshotBuildError(
                ReasonCode.SOURCE_INCOMPLETE, "trade calendar returned no open sessions"
            )
        plan = plan_tushare_requests(spec, sessions)
        ledger = self._executor.execute(plan, acquisition_root)
        return self._builder.build(spec, plan, ledger, acquisition_root, output_root)
