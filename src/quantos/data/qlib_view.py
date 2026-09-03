"""Build a rebuildable Qlib view by invoking the locked official converter."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.qlib_view import (
    ConverterInputDigest,
    InstrumentCodeMapping,
    QlibSemanticSample,
    QlibViewFile,
    QlibViewManifest,
    QlibViewSpec,
)
from quantos.contracts.refs import ArtifactRef
from quantos.contracts.status import ReasonCode
from quantos.data.snapshot import verify_snapshot
from quantos.integrations.qlib import OfficialQlibTools, run_checked, verify_official_qlib_tools

SEMANTIC_QUERY = """
import json
import sys
import qlib
from qlib.config import REG_CN
from qlib.data import D
qlib.init(provider_uri=sys.argv[1], region=REG_CN)
frame = D.features(
    [sys.argv[2]],
    [\"$close\"],
    start_time=sys.argv[3],
    end_time=sys.argv[3],
    freq=\"day\",
)
value = float(frame.iloc[0, 0])
print(\"QUANTOS_SAMPLE=\" + json.dumps(value, allow_nan=False))
"""


class QlibViewBuildError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class QlibViewBuildResult:
    reference: ArtifactRef
    manifest: QlibViewManifest
    path: Path


def _qlib_id(instrument_id: str) -> str:
    if len(instrument_id) != 9 or instrument_id[6] != "." or instrument_id[-2:] not in {"SH", "SZ"}:
        raise QlibViewBuildError(ReasonCode.SCHEMA_INVALID, "unsupported canonical instrument_id")
    return f"{instrument_id[-2:]}{instrument_id[:6]}"


def _format_float(value: float) -> str:
    return format(value, ".17g")


def _csv_bytes(rows: list[dict[str, object]]) -> bytes:
    fields = (
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "factor",
        "change",
        "limit_buy",
        "limit_sell",
        "is_st",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)  # pyright: ignore[reportArgumentType]
    return stream.getvalue().encode("utf-8")


def _converter_rows(snapshot_path: Path) -> dict[str, list[dict[str, object]]]:
    bars = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "bars.parquet"
    ).to_pylist()
    factors = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "adjustment_factors.parquet"
    ).to_pylist()
    benchmarks = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "benchmark_bars.parquet"
    ).to_pylist()
    st_status = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "st_status.parquet"
    ).to_pylist()
    suspensions = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "suspensions.parquet"
    ).to_pylist()
    price_limits = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "price_limits.parquet"
    ).to_pylist()
    factor_by_key = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])): cast(
            float, row["adjustment_factor"]
        )
        for row in factors
    }
    st_keys = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])) for row in st_status
    }
    suspension_keys = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])) for row in suspensions
    }
    limits_by_key = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])): row
        for row in price_limits
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in bars:
        instrument_id = cast(str, row["instrument_id"])
        trade_date = cast(date, row["trade_date"])
        key = (instrument_id, trade_date)
        if key not in factor_by_key:
            raise QlibViewBuildError(
                ReasonCode.SOURCE_INCOMPLETE, "bar does not resolve to an adjustment factor"
            )
        grouped.setdefault(instrument_id, []).append(
            {**row, "factor": factor_by_key[key], "canonical_id": instrument_id}
        )
    for row in benchmarks:
        benchmark_id = cast(str, row["benchmark_id"])
        grouped.setdefault(benchmark_id, []).append(
            {**row, "factor": 1.0, "canonical_id": benchmark_id}
        )

    converted: dict[str, list[dict[str, object]]] = {}
    for instrument_id, source_rows in grouped.items():
        source_rows.sort(key=lambda row: cast(date, row["trade_date"]))
        output: list[dict[str, object]] = []
        previous_close: float | None = None
        for row in source_rows:
            factor = cast(float, row["factor"])
            if factor <= 0:
                raise QlibViewBuildError(
                    ReasonCode.SCHEMA_INVALID, "adjustment factor must be positive"
                )
            trade_date = cast(date, row["trade_date"])
            key = (instrument_id, trade_date)
            suspended = key in suspension_keys
            raw_close = cast(float, row["close"])
            adjusted_close = raw_close * factor
            change = (
                None
                if suspended
                else 0.0
                if previous_close is None
                else adjusted_close / previous_close - 1.0
            )
            limit = limits_by_key.get(key)
            limit_buy = limit is not None and raw_close >= cast(float, limit["up_limit"])
            limit_sell = limit is not None and raw_close <= cast(float, limit["down_limit"])
            output.append(
                {
                    "date": trade_date.isoformat(),
                    "open": None if suspended else _format_float(cast(float, row["open"]) * factor),
                    "high": None if suspended else _format_float(cast(float, row["high"]) * factor),
                    "low": None if suspended else _format_float(cast(float, row["low"]) * factor),
                    "close": None if suspended else _format_float(adjusted_close),
                    "volume": None
                    if suspended
                    else _format_float(cast(int, row["volume_shares"]) / factor),
                    "factor": _format_float(factor),
                    "change": None if change is None else _format_float(change),
                    "limit_buy": _format_float(float(limit_buy)),
                    "limit_sell": _format_float(float(limit_sell)),
                    "is_st": _format_float(float(key in st_keys)),
                }
            )
            if not suspended:
                previous_close = adjusted_close
        converted[instrument_id] = output
    return converted


def _write_parquet(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(  # pyright: ignore[reportUnknownMemberType]
        table,
        path,
        compression="zstd",
        data_page_version="1.0",
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )


def _write_snapshot_sidecars(snapshot_path: Path, staging: Path) -> None:
    memberships = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "index_membership.parquet"
    ).to_pylist()
    bars = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "bars.parquet"
    ).to_pylist()
    st_status = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "st_status.parquet"
    ).to_pylist()
    suspensions = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "suspensions.parquet"
    ).to_pylist()
    price_limits = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "price_limits.parquet"
    ).to_pylist()

    historical_universe = pa.Table.from_pylist(
        [
            {
                "index_id": row["index_id"],
                "instrument_id": row["instrument_id"],
                "qlib_id": _qlib_id(cast(str, row["instrument_id"])),
                "effective_from": row["effective_from"],
                "effective_to": row["effective_to"],
                "available_from": row["available_from"],
                "weight_percent": row["weight_percent"],
                "available_at": row["available_at"],
            }
            for row in memberships
        ],
        schema=pa.schema(
            [
                pa.field("index_id", pa.string(), nullable=False),
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("qlib_id", pa.string(), nullable=False),
                pa.field("effective_from", pa.date32(), nullable=False),
                pa.field("effective_to", pa.date32(), nullable=False),
                pa.field("available_from", pa.date32(), nullable=False),
                pa.field("weight_percent", pa.float64(), nullable=False),
                pa.field(
                    "available_at",
                    pa.timestamp("us", tz="Asia/Shanghai"),
                    nullable=False,
                ),
            ]
        ),
    )

    st_keys = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])) for row in st_status
    }
    suspension_keys = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])) for row in suspensions
    }
    limits_by_key = {
        (cast(str, row["instrument_id"]), cast(date, row["trade_date"])): row
        for row in price_limits
    }
    tradability_rows: list[dict[str, object]] = []
    for row in bars:
        instrument_id = cast(str, row["instrument_id"])
        trade_date = cast(date, row["trade_date"])
        key = (instrument_id, trade_date)
        limit = limits_by_key.get(key)
        close = cast(float, row["close"])
        tradability_rows.append(
            {
                "instrument_id": instrument_id,
                "qlib_id": _qlib_id(instrument_id),
                "trade_date": trade_date,
                "is_suspended": key in suspension_keys,
                "is_st": key in st_keys,
                "limit_buy": limit is not None and close >= cast(float, limit["up_limit"]),
                "limit_sell": limit is not None and close <= cast(float, limit["down_limit"]),
                "up_limit": None if limit is None else limit["up_limit"],
                "down_limit": None if limit is None else limit["down_limit"],
                "available_at": row["available_at"],
            }
        )
    tradability = pa.Table.from_pylist(
        tradability_rows,
        schema=pa.schema(
            [
                pa.field("instrument_id", pa.string(), nullable=False),
                pa.field("qlib_id", pa.string(), nullable=False),
                pa.field("trade_date", pa.date32(), nullable=False),
                pa.field("is_suspended", pa.bool_(), nullable=False),
                pa.field("is_st", pa.bool_(), nullable=False),
                pa.field("limit_buy", pa.bool_(), nullable=False),
                pa.field("limit_sell", pa.bool_(), nullable=False),
                pa.field("up_limit", pa.float64(), nullable=True),
                pa.field("down_limit", pa.float64(), nullable=True),
                pa.field(
                    "available_at",
                    pa.timestamp("us", tz="Asia/Shanghai"),
                    nullable=False,
                ),
            ]
        ),
    )
    _write_parquet(historical_universe, staging / "sidecars" / "historical-universe.parquet")
    _write_parquet(tradability, staging / "sidecars" / "tradability.parquet")


def _view_files(root: Path) -> tuple[QlibViewFile, ...]:
    return tuple(
        QlibViewFile(
            logical_path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "manifest.json"
    )


def _semantic_sample(
    tools: OfficialQlibTools,
    qlib_root: Path,
    qlib_id: str,
    trade_date: date,
    expected: float,
) -> QlibSemanticSample:
    del (
        tools
    )  # Tool verification is a required precondition even though the query imports the wheel.
    try:
        result = run_checked(
            [
                sys.executable,
                "-c",
                SEMANTIC_QUERY,
                str(qlib_root),
                qlib_id,
                trade_date.isoformat(),
            ]
        )
        marker = next(
            line.removeprefix("QUANTOS_SAMPLE=")
            for line in result.stdout.splitlines()
            if line.startswith("QUANTOS_SAMPLE=")
        )
        actual = float(json.loads(marker))
    except (
        subprocess.CalledProcessError,
        StopIteration,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise QlibViewBuildError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib semantic query failed"
        ) from error
    tolerance = 1e-5
    return QlibSemanticSample(
        qlib_id=qlib_id,
        trade_date=trade_date,
        field="$close",
        expected=expected,
        actual=actual,
        absolute_tolerance=tolerance,
        passed=abs(expected - actual) <= tolerance,
    )


def verify_qlib_view(path: Path) -> QlibViewManifest:
    try:
        payload = json.loads((path / "manifest.json").read_bytes())
        manifest = QlibViewManifest.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise QlibViewBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view manifest is invalid"
        ) from error
    if path.name != f"sha256-{manifest.view_hash}":
        raise QlibViewBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view directory does not match view hash"
        )
    expected_paths = {item.logical_path for item in manifest.files}
    actual_paths = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    if actual_paths != expected_paths:
        raise QlibViewBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view file set does not match manifest"
        )
    for item in manifest.files:
        try:
            verify_file(path / item.logical_path, item.sha256)
        except (OSError, ArtifactIntegrityError) as error:
            raise QlibViewBuildError(
                ReasonCode.ARTIFACT_CORRUPTED,
                f"Qlib view file failed verification: {item.logical_path}",
            ) from error
    return manifest


class QlibViewBuilder:
    """Thin adapter over Qlib's official dump and health-check scripts."""

    def build(
        self,
        snapshot_path: Path,
        output_root: Path,
        qlib_source_root: Path,
    ) -> QlibViewBuildResult:
        snapshot = verify_snapshot(snapshot_path)
        try:
            tools = verify_official_qlib_tools(qlib_source_root)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            raise QlibViewBuildError(
                ReasonCode.QLIB_EXECUTION_FAILED, "official Qlib tools failed verification"
            ) from error
        rows_by_instrument = _converter_rows(snapshot_path)
        mappings = tuple(
            InstrumentCodeMapping(instrument_id=item, qlib_id=_qlib_id(item))
            for item in sorted(rows_by_instrument)
        )
        spec = QlibViewSpec(
            source_snapshot_hash=snapshot.snapshot_hash,
            qlib_version=tools.version,
            qlib_source_commit=tools.commit,
            dump_bin_sha256=tools.dump_bin_sha256,
            health_check_sha256=tools.health_check_sha256,
            mappings=mappings,
        )

        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".qlib-view-work-", dir=output_root) as temporary:
            work_root = Path(temporary)
            input_root = work_root / "input"
            input_root.mkdir()
            input_digests: list[ConverterInputDigest] = []
            expected_samples: dict[str, tuple[date, float]] = {}
            for mapping in mappings:
                rows = rows_by_instrument[mapping.instrument_id]
                encoded = _csv_bytes(rows)
                atomic_write_bytes(input_root / f"{mapping.qlib_id.lower()}.csv", encoded)
                input_digests.append(
                    ConverterInputDigest(
                        qlib_id=mapping.qlib_id,
                        sha256=sha256_bytes(encoded),
                        row_count=len(rows),
                    )
                )
                first = next(row for row in rows if row["close"] is not None)
                expected_samples[mapping.qlib_id] = (
                    date.fromisoformat(cast(str, first["date"])),
                    float(cast(str, first["close"])),
                )

            staging = work_root / "qlib"
            try:
                run_checked(
                    [
                        sys.executable,
                        str(tools.dump_bin),
                        "dump_all",
                        "--data_path",
                        str(input_root),
                        "--qlib_dir",
                        str(staging),
                        "--freq",
                        spec.frequency,
                        "--max_workers",
                        "1",
                        "--date_field_name",
                        "date",
                        "--include_fields",
                        ",".join(spec.include_fields),
                    ]
                )
                health = run_checked(
                    [
                        sys.executable,
                        str(tools.check_data_health),
                        "--qlib_dir",
                        str(staging),
                        "check_data",
                    ]
                )
            except subprocess.CalledProcessError as error:
                raise QlibViewBuildError(
                    ReasonCode.QLIB_EXECUTION_FAILED, "official Qlib conversion failed"
                ) from error

            atomic_write_bytes(staging / "view-spec.json", spec.canonical_bytes())
            _write_snapshot_sidecars(snapshot_path, staging)
            samples = tuple(
                _semantic_sample(
                    tools, staging, mapping.qlib_id, *expected_samples[mapping.qlib_id]
                )
                for mapping in mappings
            )
            files = _view_files(staging)
            manifest = QlibViewManifest.create(
                source_snapshot_hash=snapshot.snapshot_hash,
                view_spec_hash=spec.content_hash,
                qlib_version=tools.version,
                qlib_source_commit=tools.commit,
                dump_bin_sha256=tools.dump_bin_sha256,
                health_check_sha256=tools.health_check_sha256,
                converter_inputs=tuple(sorted(input_digests, key=lambda item: item.qlib_id)),
                files=files,
                health_check_passed=health.returncode == 0,
                semantic_samples=samples,
                created_at=datetime.now(UTC),
            )
            atomic_write_bytes(
                staging / "manifest.json", canonical_json_bytes(manifest.model_dump(mode="python"))
            )
            destination = output_root / f"sha256-{manifest.view_hash}"
            if destination.exists():
                published = verify_qlib_view(destination)
            else:
                publish_directory(staging, destination)
                published = verify_qlib_view(destination)

        size_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
        reference = ArtifactRef(
            kind="qlib_view",
            sha256=published.view_hash,
            size_bytes=size_bytes,
            media_type="application/vnd.qlib.binary-directory",
            logical_path=f"data/qlib-views/{destination.name}",
        )
        return QlibViewBuildResult(reference=reference, manifest=published, path=destination)
