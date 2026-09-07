"""Build a rebuildable Qlib view by invoking the locked official converter."""

# PyArrow's generic compute and RecordBatch stubs do not preserve concrete array
# types through joins; runtime schemas and integration tests validate this boundary.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportArgumentType=false

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from struct import pack, unpack
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
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
requests = json.load(open(sys.argv[2], encoding="utf-8"))
qlib.init(provider_uri=sys.argv[1], region=REG_CN)
ids = sorted({item["qlib_id"] for item in requests})
dates = [item["trade_date"] for item in requests]
frame = D.features(
    ids,
    [\"$close\"],
    start_time=min(dates),
    end_time=max(dates),
    freq=\"day\",
)
wanted = {(item["qlib_id"], item["trade_date"]) for item in requests}
values = {}
for (instrument, timestamp), value in frame.iloc[:, 0].items():
    key = (instrument.upper(), timestamp.date().isoformat())
    if key in wanted:
        values[instrument.upper()] = float(value)
print(\"QUANTOS_SAMPLES=\" + json.dumps(values, allow_nan=False, sort_keys=True))
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


def _marked_keys(path: Path, marker: str) -> pa.Table:
    table = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        path, columns=["instrument_id", "trade_date"]
    )
    return table.append_column(marker, pa.array([True] * table.num_rows, type=pa.bool_()))


def _stock_market_table(snapshot_path: Path) -> pa.Table:
    """Join canonical market columns in Arrow without expanding the snapshot to Python objects."""

    canonical = snapshot_path / "canonical"
    bars = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        canonical / "bars.parquet",
        columns=[
            "instrument_id",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume_shares",
            "available_at",
        ],
    )
    factors = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        canonical / "adjustment_factors.parquet",
        columns=["instrument_id", "trade_date", "adjustment_factor"],
    )
    limits = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        canonical / "price_limits.parquet",
        columns=["instrument_id", "trade_date", "up_limit", "down_limit"],
    )
    joined = bars.join(
        factors,
        keys=["instrument_id", "trade_date"],
        join_type="left outer",
        use_threads=False,
    )
    if joined["adjustment_factor"].null_count:
        raise QlibViewBuildError(
            ReasonCode.SOURCE_INCOMPLETE, "bar does not resolve to an adjustment factor"
        )
    joined = joined.join(
        _marked_keys(canonical / "st_status.parquet", "is_st"),
        keys=["instrument_id", "trade_date"],
        join_type="left outer",
        use_threads=False,
    )
    joined = joined.join(
        _marked_keys(canonical / "suspensions.parquet", "is_suspended"),
        keys=["instrument_id", "trade_date"],
        join_type="left outer",
        use_threads=False,
    )
    joined = joined.join(
        limits,
        keys=["instrument_id", "trade_date"],
        join_type="left outer",
        use_threads=False,
    )
    joined = joined.set_column(
        joined.schema.get_field_index("is_st"),
        "is_st",
        pc.fill_null(joined["is_st"], pa.scalar(False)),
    )
    joined = joined.set_column(
        joined.schema.get_field_index("is_suspended"),
        "is_suspended",
        pc.fill_null(joined["is_suspended"], pa.scalar(False)),
    )
    return joined.sort_by([("instrument_id", "ascending"), ("trade_date", "ascending")])


def _iter_rows(table: pa.Table) -> Iterator[dict[str, object]]:
    for batch in table.to_batches(max_chunksize=32_768):
        yield from batch.to_pylist()


def _converted_rows(
    instrument_id: str, source_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    del instrument_id
    output: list[dict[str, object]] = []
    previous_close: float | None = None
    for row in source_rows:
        factor = cast(float, row["adjustment_factor"])
        if factor <= 0:
            raise QlibViewBuildError(
                ReasonCode.SCHEMA_INVALID, "adjustment factor must be positive"
            )
        trade_date = cast(date, row["trade_date"])
        suspended = cast(bool, row["is_suspended"])
        raw_close = cast(float, row["close"])
        adjusted_close = raw_close * factor
        change = (
            None
            if suspended
            else 0.0
            if previous_close is None
            else adjusted_close / previous_close - 1.0
        )
        up_limit = cast(float | None, row["up_limit"])
        down_limit = cast(float | None, row["down_limit"])
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
                "limit_buy": _format_float(float(up_limit is not None and raw_close >= up_limit)),
                "limit_sell": _format_float(
                    float(down_limit is not None and raw_close <= down_limit)
                ),
                "is_st": _format_float(float(cast(bool, row["is_st"]))),
            }
        )
        if not suspended:
            previous_close = adjusted_close
    return output


def _iter_converter_rows(
    snapshot_path: Path, stock_market: pa.Table
) -> Iterator[tuple[str, list[dict[str, object]]]]:
    current_id: str | None = None
    current_rows: list[dict[str, object]] = []
    for row in _iter_rows(stock_market):
        instrument_id = cast(str, row["instrument_id"])
        if current_id is not None and instrument_id != current_id:
            yield current_id, _converted_rows(current_id, current_rows)
            current_rows = []
        current_id = instrument_id
        current_rows.append(row)
    if current_id is not None:
        yield current_id, _converted_rows(current_id, current_rows)

    benchmarks = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "benchmark_bars.parquet",
        columns=[
            "benchmark_id",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume_shares",
        ],
    ).sort_by([("benchmark_id", "ascending"), ("trade_date", "ascending")])
    current_id = None
    current_rows = []
    for row in _iter_rows(benchmarks):
        benchmark_id = cast(str, row.pop("benchmark_id"))
        if current_id is not None and benchmark_id != current_id:
            yield current_id, _converted_rows(current_id, current_rows)
            current_rows = []
        current_id = benchmark_id
        row.update(
            {
                "adjustment_factor": 1.0,
                "is_st": False,
                "is_suspended": False,
                "up_limit": None,
                "down_limit": None,
            }
        )
        current_rows.append(row)
    if current_id is not None:
        yield current_id, _converted_rows(current_id, current_rows)


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


def _write_snapshot_sidecars(snapshot_path: Path, staging: Path, stock_market: pa.Table) -> None:
    memberships = pq.read_table(  # pyright: ignore[reportUnknownMemberType]
        snapshot_path / "canonical" / "index_membership.parquet",
        columns=[
            "index_id",
            "instrument_id",
            "effective_from",
            "effective_to",
            "available_from",
            "weight_percent",
            "available_at",
        ],
    )
    historical_schema = pa.schema(
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
    )
    historical_universe = pa.Table.from_arrays(
        [
            memberships["index_id"],
            memberships["instrument_id"],
            pa.array(
                [_qlib_id(value.as_py()) for value in memberships["instrument_id"]],
                type=pa.string(),
            ),
            memberships["effective_from"],
            memberships["effective_to"],
            memberships["available_from"],
            memberships["weight_percent"],
            memberships["available_at"],
        ],
        schema=historical_schema,
    )
    tradability_schema = pa.schema(
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
    )
    _write_parquet(historical_universe, staging / "sidecars" / "historical-universe.parquet")
    tradability_path = staging / "sidecars" / "tradability.parquet"
    tradability_path.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(
        tradability_path,
        tradability_schema,
        compression="zstd",
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    ) as writer:
        for batch in stock_market.to_batches(max_chunksize=65_536):
            close = batch.column("close")
            up_limit = batch.column("up_limit")
            down_limit = batch.column("down_limit")
            instrument_ids = batch.column("instrument_id")
            table = pa.Table.from_arrays(
                [
                    instrument_ids,
                    pa.array([_qlib_id(value.as_py()) for value in instrument_ids]),
                    batch.column("trade_date"),
                    batch.column("is_suspended"),
                    batch.column("is_st"),
                    pc.fill_null(pc.greater_equal(close, up_limit), pa.scalar(False)),
                    pc.fill_null(pc.less_equal(close, down_limit), pa.scalar(False)),
                    up_limit,
                    down_limit,
                    batch.column("available_at"),
                ],
                schema=tradability_schema,
            )
            writer.write_table(table)


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


def _semantic_samples(
    tools: OfficialQlibTools,
    qlib_root: Path,
    expected_samples: dict[str, tuple[date, float]],
    ordered_ids: tuple[str, ...],
    work_root: Path,
) -> tuple[QlibSemanticSample, ...]:
    del (
        tools
    )  # Tool verification is a required precondition even though the query imports the wheel.
    request_path = work_root / "semantic-sample-requests.json"
    atomic_write_bytes(
        request_path,
        canonical_json_bytes(
            [
                {"qlib_id": qlib_id, "trade_date": trade_date.isoformat()}
                for qlib_id in ordered_ids
                for trade_date, _expected in (expected_samples[qlib_id],)
            ]
        ),
    )
    try:
        result = run_checked(
            [
                sys.executable,
                "-c",
                SEMANTIC_QUERY,
                str(qlib_root),
                str(request_path),
            ]
        )
        marker = next(
            line.removeprefix("QUANTOS_SAMPLES=")
            for line in result.stdout.splitlines()
            if line.startswith("QUANTOS_SAMPLES=")
        )
        actual_values = cast(dict[str, float], json.loads(marker))
    except (
        subprocess.CalledProcessError,
        StopIteration,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise QlibViewBuildError(
            ReasonCode.QLIB_EXECUTION_FAILED, "Qlib semantic query failed"
        ) from error
    if set(actual_values) != set(expected_samples):
        raise QlibViewBuildError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            "Qlib semantic query did not return every requested instrument",
        )
    # The locked official converter persists every feature with astype("<f"),
    # i.e. little-endian IEEE-754 binary32. Compare the readback to that exact
    # representation instead of applying an arbitrary magnitude-independent
    # tolerance to the canonical binary64 value.
    encoded_expected = {
        qlib_id: unpack("<f", pack("<f", expected))[0]
        for qlib_id, (_trade_date, expected) in expected_samples.items()
    }
    storage_mismatches = tuple(
        qlib_id
        for qlib_id in ordered_ids
        if float(actual_values[qlib_id]) != encoded_expected[qlib_id]
    )
    if storage_mismatches:
        raise QlibViewBuildError(
            ReasonCode.QLIB_EXECUTION_FAILED,
            f"{len(storage_mismatches)} Qlib semantic samples differ from exact binary32 "
            "converter output",
        )
    samples = tuple(
        QlibSemanticSample(
            qlib_id=qlib_id,
            trade_date=trade_date,
            field="$close",
            expected=expected,
            actual=float(actual_values[qlib_id]),
            absolute_tolerance=abs(expected - encoded_expected[qlib_id]),
            passed=True,
        )
        for qlib_id in ordered_ids
        for trade_date, expected in (expected_samples[qlib_id],)
    )
    return samples


def verify_qlib_view(path: Path) -> QlibViewManifest:
    try:
        tree_files = regular_tree_files(path)
        payload = json.loads((path / "manifest.json").read_bytes())
        manifest = QlibViewManifest.model_validate(payload)
    except (OSError, ValueError, json.JSONDecodeError, ArtifactIntegrityError) as error:
        raise QlibViewBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view manifest is invalid"
        ) from error
    if path.name != f"sha256-{manifest.view_hash}":
        raise QlibViewBuildError(
            ReasonCode.ARTIFACT_CORRUPTED, "Qlib view directory does not match view hash"
        )
    expected_paths = {item.logical_path for item in manifest.files}
    actual_paths = {
        item.relative_to(path).as_posix() for item in tree_files if item.name != "manifest.json"
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
        stock_market = _stock_market_table(snapshot_path)

        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".qlib-view-work-", dir=output_root) as temporary:
            work_root = Path(temporary)
            input_root = work_root / "input"
            input_root.mkdir()
            input_digests: list[ConverterInputDigest] = []
            expected_samples: dict[str, tuple[date, float]] = {}
            instrument_ids: list[str] = []
            seen_instrument_ids: set[str] = set()
            for instrument_id, rows in _iter_converter_rows(snapshot_path, stock_market):
                qlib_id = _qlib_id(instrument_id)
                if instrument_id in seen_instrument_ids:
                    raise QlibViewBuildError(
                        ReasonCode.SCHEMA_INVALID, "Qlib input instrument ids must be unique"
                    )
                seen_instrument_ids.add(instrument_id)
                instrument_ids.append(instrument_id)
                encoded = _csv_bytes(rows)
                atomic_write_bytes(input_root / f"{qlib_id.lower()}.csv", encoded)
                input_digests.append(
                    ConverterInputDigest(
                        qlib_id=qlib_id,
                        sha256=sha256_bytes(encoded),
                        row_count=len(rows),
                    )
                )
                first = next((row for row in rows if row["close"] is not None), None)
                if first is None:
                    raise QlibViewBuildError(
                        ReasonCode.SOURCE_INCOMPLETE,
                        f"Qlib input has no usable close values: {instrument_id}",
                    )
                expected_samples[qlib_id] = (
                    date.fromisoformat(cast(str, first["date"])),
                    float(cast(str, first["close"])),
                )
            mappings = tuple(
                InstrumentCodeMapping(instrument_id=item, qlib_id=_qlib_id(item))
                for item in sorted(instrument_ids)
            )
            spec = QlibViewSpec(
                source_snapshot_hash=snapshot.snapshot_hash,
                qlib_version=tools.version,
                qlib_source_commit=tools.commit,
                dump_bin_sha256=tools.dump_bin_sha256,
                health_check_sha256=tools.health_check_sha256,
                mappings=mappings,
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
            _write_snapshot_sidecars(snapshot_path, staging, stock_market)
            samples = _semantic_samples(
                tools,
                staging,
                expected_samples,
                tuple(mapping.qlib_id for mapping in mappings),
                work_root,
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
