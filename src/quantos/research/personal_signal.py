"""Source/PIT-bound v7 signals; Qlib computes expressions and native execution lag."""

from __future__ import annotations

import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import qlib  # pyright: ignore[reportMissingTypeStubs]
from qlib.config import REG_CN  # pyright: ignore[reportMissingTypeStubs]
from qlib.data import D  # pyright: ignore[reportMissingTypeStubs]

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    atomic_write_bytes,
    confined_regular_file,
    exclusive_directory_lock,
    opened_directory,
    read_regular_bytes_at,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.personal_strategy import (
    PersonalExpression,
    PersonalSignalArtifact,
    PersonalSignalArtifactV2,
    PersonalStrategy,
)
from quantos.contracts.signal import SignalRow
from quantos.research.qlib.personal_expression import (
    FIELD_MAPPING,
    expression_dependencies,
    required_history,
    translate_personal_expression,
)
from quantos.research.qlib.signal import SIGNAL_SCHEMA, signal_content_hash, write_signal_table

MAX_PANEL_BYTES = 256 * 1024**2


def dataset_binding_hash(binding: Any) -> str:
    profile = getattr(binding, "field_mapping_profile", "native-bins/v1")
    if profile == "native-bins/v1":
        return str(binding.manifest.content_hash)
    if profile != "canonical-personal-fields/v1":
        raise ValueError("unknown personal field mapping profile")
    return sha256_bytes(
        canonical_json_bytes(
            {
                "schema_version": "personal-field-binding/v1",
                "dataset_manifest_hash": binding.manifest.content_hash,
                "field_mapping_profile": profile,
            }
        )
    )


def _artifact(raw: bytes) -> PersonalSignalArtifact:
    model = (
        PersonalSignalArtifactV2
        if json.loads(raw).get("schema_version") == "personal-signal-artifact/v2"
        else PersonalSignalArtifact
    )
    return model.model_validate_json(raw)


def _read(path: Path, maximum: int = MAX_PANEL_BYTES) -> bytes:
    with opened_directory(path.parent) as directory:
        return read_regular_bytes_at(directory, path.name, max_bytes=maximum)


def _valid_code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 8
        and value[:2] in {"SH", "SZ"}
        and value[2:].isdigit()
    )


def _valid_status(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_))


def _naive_time(value: Any) -> bool:
    return bool(cast(Any, pd).notna(value)) and pd.Timestamp(value).tzinfo is None


def verified_panel(binding: Any) -> pd.DataFrame:
    """Adopt the registered immutable panel/PIT originals, not model-supplied claims."""
    manifest = binding.manifest
    raw = _read(binding.panel_path)
    if sha256_bytes(raw) != manifest.panel_sha256:
        raise ValueError("canonical panel identity disagrees")
    if binding.pit_evidence_path is None:
        raise ValueError("PIT evidence missing")
    verify_file(binding.pit_evidence_path, manifest.pit_evidence_hash)
    if manifest.kind == "market":
        from quantos.research.hs300_lifecycle_data import verify_hs300_lifecycle_binding

        verify_hs300_lifecycle_binding(binding)
    for logical, digest in manifest.qlib_files.items():
        verify_file(confined_regular_file(binding.provider_root, logical), digest)
    frame: Any = pd.read_parquet(io.BytesIO(raw))
    required = {
        "trade_date",
        "qlib_id",
        "close",
        "volume",
        "is_member",
        "is_st",
        "is_suspended",
        "available_at",
    }
    if not required <= set(frame.columns) or frame.empty:
        raise ValueError("daily PIT panel fields missing or grid empty")
    dates: Any = cast(Any, pd).to_datetime(frame.trade_date, errors="coerce")
    if dates.isna().any() or dates.dt.tz is not None or not (dates == dates.dt.normalize()).all():
        raise ValueError("daily PIT panel dates must be naive session dates")
    frame["trade_date"] = dates.dt.date
    if (
        frame.duplicated(["trade_date", "qlib_id"]).any()
        or not frame.qlib_id.map(_valid_code).all()
    ):
        raise ValueError("daily PIT panel keys duplicated or instrument mapping invalid")
    for column in ("is_member", "is_st", "is_suspended", "is_listed"):
        if column in frame and not frame[column].map(_valid_status).all():
            raise ValueError("unknown PIT member, listed or trading status")
    if manifest.kind == "market" and "is_listed" not in frame:
        raise ValueError("market lifecycle panel lacks explicit listing status")
    if (
        getattr(binding, "field_mapping_profile", "native-bins/v1")
        == "canonical-personal-fields/v1"
    ):
        from quantos.research.personal_fields import augment_canonical_fields

        frame = augment_canonical_fields(binding, frame)
    return cast(pd.DataFrame, frame)


def _expressions(strategy: PersonalStrategy) -> list[PersonalExpression]:
    return [
        e
        for e in (strategy.score, strategy.eligibility, strategy.market_condition)
        if e is not None
    ]


def _calendar(binding: Any) -> list[date]:
    if "calendars/day.txt" not in binding.manifest.qlib_files:
        raise ValueError("QLIB_CALENDAR_UNMAPPED")
    path = confined_regular_file(binding.provider_root, "calendars/day.txt")
    try:
        days = [date.fromisoformat(x) for x in _read(path, 1024**2).decode().splitlines()]
    except (UnicodeError, ValueError) as error:
        raise ValueError("invalid frozen Qlib daily calendar") from error
    if not days or days != sorted(set(days)):
        raise ValueError("frozen Qlib daily calendar must be unique and ordered")
    return days


def _fields(strategy: PersonalStrategy) -> list[str]:
    # Close anchors constants/nulls; native daily execution also consumes volume.
    return sorted(
        {"adjusted_close", "adjusted_volume"}
        | {field for spec in _expressions(strategy) for field in expression_dependencies(spec)}
    )


def _scope(
    binding: Any, frame: pd.DataFrame, fields: list[str], start: date, end: date, benchmark: str
) -> tuple[pd.DataFrame, list[date]]:
    calendar = [day for day in _calendar(binding) if start <= day <= end]
    if not calendar or start not in calendar or end not in calendar:
        raise ValueError("NON_SESSION_OR_UNCOVERED_DATE")
    data: Any = frame.loc[(frame.trade_date >= start) & (frame.trade_date <= end)].copy()
    if not set(data.trade_date) <= set(calendar):
        raise ValueError("PIT_HARD_REJECTION:non-session panel input")
    names = sorted(set(data.loc[data.is_member, "qlib_id"]) | {benchmark})
    if benchmark not in set(data.qlib_id):
        raise ValueError("BENCHMARK_MISSING")
    data = data.loc[data.qlib_id.isin(names)].copy()
    dense = pd.MultiIndex.from_product([names, calendar], names=["qlib_id", "trade_date"])
    if not dense.isin(data.set_index(["qlib_id", "trade_date"]).index).all():
        raise ValueError("PIT_HARD_REJECTION:dense session mapping missing")
    columns = [FIELD_MAPPING[field][1:] for field in fields]
    for field, column in zip(fields, columns, strict=True):
        if column not in data:
            raise ValueError(
                "AMOUNT_CNY_CANONICAL_FIELD_MISSING"
                if field == "amount_cny"
                else f"CANONICAL_FIELD_MISSING:{field}"
            )
        for code in names:
            if (
                field == "amount_cny"
                and getattr(binding, "field_mapping_profile", "native-bins/v1")
                == "canonical-personal-fields/v1"
            ):
                continue
            if f"features/{code.lower()}/{column}.day.bin" not in binding.manifest.qlib_files:
                raise ValueError(f"QLIB_FIELD_UNMAPPED:{field}:{code}")
    listed: Any = data.is_listed if "is_listed" in data else pd.Series(True, index=data.index)
    required = (data.is_member & listed & ~data.is_suspended) | (data.qlib_id == benchmark)
    numeric: Any = data[columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.loc[required].to_numpy(dtype=float)).all():
        raise ValueError("PIT_HARD_REJECTION:required canonical values missing or nonfinite")
    if any(
        (numeric.loc[required, column] <= 0).any()
        for column in columns
        if column not in {"volume", "amount_cny"}
    ) or any(
        (numeric.loc[required, column] < 0).any()
        for column in columns
        if column in {"volume", "amount_cny"}
    ):
        raise ValueError("PIT_HARD_REJECTION:canonical price or quantity units invalid")
    observed = data.is_member | (data.qlib_id == benchmark) | numeric.notna().any(axis=1)
    aliases = set(columns) | {
        "bar",
        "bars",
        "factor",
        "adjustment_factor",
        "member",
        "membership",
        "status",
        "is_member",
        "is_st",
        "is_suspended",
        "is_listed",
        "listed",
        "st",
        "suspension",
    }
    time_columns = [
        column
        for column in data.columns
        if column == "available_at"
        or (column.startswith("available_at_") and column[13:] in aliases)
        or (column.endswith("_available_at") and column[:-13] in aliases)
    ]
    cutoff: Any = cast(Any, pd).to_datetime(data.trade_date.astype(str)).dt.tz_localize(
        "Asia/Shanghai"
    ) + pd.Timedelta(hours=23, minutes=59)
    available: list[Any] = []
    for column in time_columns:
        timed_rows: Any = observed
        if (
            getattr(binding, "field_mapping_profile", "native-bins/v1")
            == "canonical-personal-fields/v1"
        ):
            alias = column[13:] if column.startswith("available_at_") else column[:-13]
            value_column = {"factor": "adjustment_factor"}.get(alias, alias)
            if alias in {"bar", "bars"}:
                has_source = (
                    data[
                        [
                            c
                            for c in ("open", "high", "low", "close", "volume", "amount_cny")
                            if c in data
                        ]
                    ]
                    .notna()
                    .any(axis=1)
                )
                timed_rows = observed & (required | has_source)
            elif (
                value_column
                in {"open", "high", "low", "close", "volume", "amount_cny", "adjustment_factor"}
                and value_column in data
            ):
                timed_rows = observed & (required | data[value_column].notna())
        originals: Any = data.loc[timed_rows, column]
        if not isinstance(originals.dtype, pd.DatetimeTZDtype) and any(
            _naive_time(v) for v in originals
        ):
            raise ValueError("PIT_HARD_REJECTION:source availability timezone unknown")
        stamps: Any = cast(Any, pd).to_datetime(
            data[column], utc=True, errors="coerce", format="mixed"
        )
        if (
            stamps.loc[timed_rows].isna().any()
            or (stamps.loc[timed_rows] > cutoff.loc[timed_rows]).any()
            or (stamps.loc[timed_rows] > pd.Timestamp.now(tz="UTC")).any()
        ):
            raise ValueError("PIT_HARD_REJECTION:source availability unknown or future")
        available.append(stamps)
    data["_available"] = pd.concat(available, axis=1).max(axis=1)
    return cast(pd.DataFrame, data.sort_values(["qlib_id", "trade_date"])), calendar


def _query(
    binding: Any,
    frame: pd.DataFrame,
    fields: list[str],
    start: date,
    end: date,
    translations: list[str] | None = None,
) -> pd.DataFrame:
    """Query raw mappings beside expressions once, then compare exact binary32 values."""
    raw_fields = [FIELD_MAPPING[field] for field in fields]
    query = list(dict.fromkeys([*(translations or []), *raw_fields]))
    options: dict[str, Any] = {}
    if (
        getattr(binding, "field_mapping_profile", "native-bins/v1")
        == "canonical-personal-fields/v1"
    ):
        options["feature_provider"] = {
            "class": "CanonicalAmountFeatureProvider",
            "module_path": "quantos.research.personal_fields",
            "kwargs": {"frame": frame, "calendar_sessions": _calendar(binding)},
        }
    cast(Any, qlib).init(
        provider_uri=str(binding.provider_root),
        region=REG_CN,
        kernels=1,
        clear_mem_cache=True,
        **options,
    )
    loaded: Any = cast(Any, D).features(
        sorted(set(frame.qlib_id)), query, start_time=str(start), end_time=str(end), freq="day"
    )
    if (
        not isinstance(loaded.index, pd.MultiIndex)
        or loaded.index.nlevels != 2
        or loaded.index.has_duplicates
        or list(loaded.columns) != query
    ):
        raise ValueError("Qlib feature grid or field mapping disagrees")
    times = pd.DatetimeIndex(loaded.index.get_level_values(1)).as_unit("ns")
    if times.tz is not None or not (times == times.normalize()).all():
        raise ValueError("Qlib features contain unknown or intraday clocks")
    loaded.index = pd.MultiIndex.from_arrays(
        [loaded.index.get_level_values(0), times], names=["instrument", "datetime"]
    )
    canonical: Any = frame.copy()
    expected_index = pd.MultiIndex.from_arrays(
        [
            canonical.qlib_id,
            pd.DatetimeIndex(cast(Any, pd).to_datetime(canonical.trade_date)).as_unit("ns"),
        ],
        names=["instrument", "datetime"],
    )
    if not loaded.index.isin(expected_index).all():
        raise ValueError("Qlib returned an unmapped instrument or session")
    loaded = loaded.reindex(expected_index)
    for field, native in zip(fields, raw_fields, strict=True):
        expected: Any = (
            cast(Any, pd).to_numeric(canonical[native[1:]], errors="coerce").to_numpy(dtype=float)
        )
        expected[canonical.is_suspended.to_numpy(dtype=bool)] = np.nan
        expected = expected.astype(np.float32).astype(float)
        actual: Any = (
            cast(Any, pd).to_numeric(loaded[native], errors="coerce").to_numpy(dtype=float)
        )
        if not np.array_equal(actual, expected, equal_nan=True):
            raise ValueError(f"PIT_HARD_REJECTION:QLIB_CANONICAL_VALUE_MISMATCH:{field}")
    return cast(pd.DataFrame, loaded)


def strategy_gaps(
    binding: Any,
    strategy: PersonalStrategy,
    start: date,
    end: date,
    warmup: date,
    benchmark: str,
    *,
    panel: pd.DataFrame | None = None,
) -> tuple[list[str], dict[str, Any]]:
    expressions = _expressions(strategy)
    fields = _fields(strategy)
    required = max(required_history(e) for e in expressions) + 1
    detail: dict[str, Any] = {
        "fields": fields,
        "required_prior_sessions": required,
        "actual_prior_sessions": 0,
        "raw_mapping": "exact canonical binary32; suspended cache values null",
        "next_session_lag": "native once",
        "source_validation": "not_yet_completed",
    }
    try:
        translations = [translate_personal_expression(e) for e in expressions]
        from quantos.research.personal_native import require_supported_market_period

        require_supported_market_period(binding, str(end), start=str(start))
        detail["compiled_expressions"] = translations
        frame = verified_panel(binding) if panel is None else panel
        relevant, sessions = _scope(binding, frame, fields, warmup, end, benchmark)
        if start not in sessions:
            raise ValueError("NON_SESSION_OR_UNCOVERED_DATE")
        prior = [s for s in sessions if s < start]
        detail.update(actual_prior_sessions=len(prior), sessions=len(sessions))
        gaps = (
            []
            if len(prior) >= required
            else [f"WARMUP_INSUFFICIENT: need {required} preceding sessions"]
        )
        _query(binding, relevant, fields, warmup, end)
        detail["source_validation"] = "VERIFIED_PANEL_PIT_AND_RAW_CACHE_VALUES"
        return gaps, detail
    except (ValueError, ArtifactIntegrityError) as error:
        return [str(error)], detail


def _lineage(
    binding: Any, strategy: PersonalStrategy, translations: list[str], benchmark: str
) -> dict[str, Any]:
    result = {
        "schema_version": "personal-signal-lineage/v1",
        "strategy_hash": strategy.content_hash,
        "dataset_hash": dataset_binding_hash(binding),
        "panel_sha256": binding.manifest.panel_sha256,
        "pit_evidence_hash": binding.manifest.pit_evidence_hash,
        "translation_hash": sha256_bytes(canonical_json_bytes(translations)),
        "expressions": [e.model_dump(mode="json") for e in _expressions(strategy)],
        "dependencies": [expression_dependencies(e) for e in _expressions(strategy)],
        "benchmark": benchmark,
        "rule": "backward dependency availability; input lag once; native execution lag once",
    }
    if (
        getattr(binding, "field_mapping_profile", "native-bins/v1")
        == "canonical-personal-fields/v1"
    ):
        result.update(
            schema_version="personal-signal-lineage/v2",
            field_mapping_profile="canonical-personal-fields/v1",
        )
    return result


def compile_strategy_signal(
    binding: Any,
    strategy: PersonalStrategy,
    start: date,
    end: date,
    destination: Path,
    runtime_hash: str,
    *,
    benchmark: str = "SH000300",
) -> tuple[PersonalSignalArtifact, pd.DataFrame]:
    frame = verified_panel(binding)
    fields = _fields(strategy)
    expressions = _expressions(strategy)
    calendar = _calendar(binding)
    if start not in calendar:
        raise ValueError("NON_SESSION_OR_UNCOVERED_DATE")
    # Publication range and dependency context are different. A one-day forward
    # signal still consumes its complete backward window; it emits only that day.
    history = max(required_history(e) for e in expressions)
    context_start = calendar[max(0, calendar.index(start) - history)]
    relevant, sessions = _scope(binding, frame, fields, context_start, end, benchmark)
    translations = [translate_personal_expression(e) for e in expressions]
    if (destination / "manifest.json").exists():
        existing = _artifact(_read(confined_regular_file(destination, "manifest.json"), 128_000))
        artifact, native_frame = load_strategy_signal(destination, existing.content_hash)
        expected = {
            "strategy_hash": strategy.content_hash,
            "dataset_hash": dataset_binding_hash(binding),
            "snapshot_hash": binding.manifest.snapshot_hash,
            "qlib_view_hash": binding.manifest.qlib_view_hash,
            "panel_sha256": binding.manifest.panel_sha256,
            "pit_evidence_hash": binding.manifest.pit_evidence_hash,
            "runtime_hash": runtime_hash,
            "start_date": start,
            "end_date": end,
            "source_vintage": binding.manifest.source_vintage,
        }
        if any(getattr(artifact, key) != value for key, value in expected.items()) or _read(
            confined_regular_file(destination, "lineage.json"), 1024**2
        ) != canonical_json_bytes(_lineage(binding, strategy, translations, benchmark)):
            raise ValueError("immutable signal reuse dependency binding changed")
        return artifact, native_frame
    features = _query(binding, relevant, fields, context_start, end, translations)
    features = features.loc[
        (features.index.get_level_values("datetime") >= pd.Timestamp(start))
        & (features.index.get_level_values("datetime") <= pd.Timestamp(end))
    ]
    panel: Any = relevant.set_index(["qlib_id", "trade_date"])
    dependencies = [expression_dependencies(e) for e in expressions]
    rows: list[SignalRow] = []
    native: list[dict[str, Any]] = []
    day_index = {day: index for index, day in enumerate(sessions)}
    for (code, stamp), values in cast(Any, features).iterrows():
        day = pd.Timestamp(stamp).date()
        source: Any = panel.loc[(code, day)]
        if pd.isna(source["_available"]):
            # No observed source and no membership: omit, never invent availability.
            continue
        signal_time = pd.Timestamp(day).tz_localize("Asia/Shanghai") + pd.Timedelta(
            hours=23, minutes=59
        )
        available = pd.Timestamp(source["_available"])
        tradable = bool(
            code != benchmark
            and source.is_member
            and source.get("is_listed", True)
            and not source.is_st
            and not source.is_suspended
        )
        score = float(values[translations[0]])
        valid = tradable and math.isfinite(score)
        for index, dependency in enumerate(dependencies):
            is_market = strategy.market_condition is not None and index == len(expressions) - 1
            source_code = benchmark if is_market else code
            for offsets in dependency.values():
                for offset in offsets:
                    previous = day_index[day] - offset
                    if previous < 0:
                        valid = False
                        continue
                    dependency_time = panel.loc[(source_code, sessions[previous]), "_available"]
                    if pd.isna(dependency_time):
                        valid = False
                    else:
                        available = max(available, pd.Timestamp(dependency_time))
            if index > 0:
                predicate: Any = cast(Any, features).loc[(source_code, stamp), translations[index]]
                valid = (
                    valid
                    and bool(cast(Any, pd).notna(predicate))
                    and math.isfinite(float(predicate))
                    and float(predicate) != 0
                )
        # Arrow/SignalRow use microseconds; round source availability upward so
        # serialization never claims a source was known before its actual timestamp.
        available = available.ceil("us")
        if available > signal_time:
            raise ValueError("PIT_HARD_REJECTION:dependency unavailable at signal cutoff")
        rows.append(
            SignalRow(
                instrument_id=f"{code[2:]}.{code[:2]}",
                signal_time=signal_time.to_pydatetime(),
                decision_time=signal_time.to_pydatetime(),
                available_at=available.to_pydatetime(),
                score=score if valid else None,
                score_valid=valid,
                tradable=tradable,
            )
        )
        native.append(
            {
                "datetime": pd.Timestamp(stamp).as_unit("ns"),
                "instrument": code,
                "score": score if valid else np.nan,
            }
        )
    if not rows:
        raise ValueError("signal grid is empty")
    destination.mkdir(parents=True, exist_ok=True)
    with exclusive_directory_lock(destination):
        if any(destination.iterdir()):
            raise ValueError("immutable signal destination already contains artifacts")
        path = destination / "signals.parquet"
        temporary = io.BytesIO()
        write_signal_table(tuple(rows), cast(Any, temporary))
        encoded_signals = temporary.getvalue()
        if len(encoded_signals) > MAX_PANEL_BYTES:
            raise ValueError("signal Parquet exceeds bounded artifact size")
        atomic_write_bytes(path, encoded_signals)
        lineage = _lineage(binding, strategy, translations, benchmark)
        encoded_lineage = canonical_json_bytes(lineage)
        atomic_write_bytes(destination / "lineage.json", encoded_lineage)
        artifact_model = (
            PersonalSignalArtifactV2
            if getattr(binding, "field_mapping_profile", "native-bins/v1")
            == "canonical-personal-fields/v1"
            else PersonalSignalArtifact
        )
        artifact = artifact_model(
            strategy_hash=strategy.content_hash,
            dataset_hash=dataset_binding_hash(binding),
            snapshot_hash=binding.manifest.snapshot_hash,
            qlib_view_hash=binding.manifest.qlib_view_hash,
            panel_sha256=binding.manifest.panel_sha256,
            pit_evidence_hash=binding.manifest.pit_evidence_hash,
            runtime_hash=runtime_hash,
            expression_translation_hash=lineage["translation_hash"],
            transform_lineage_hash=sha256_bytes(encoded_lineage),
            signal_content_hash=signal_content_hash(tuple(rows)),
            signals_parquet_sha256=sha256_file(path),
            start_date=start,
            end_date=end,
            row_count=len(rows),
            source_vintage=binding.manifest.source_vintage,
        )
        atomic_write_bytes(destination / "manifest.json", artifact.canonical_bytes())
        atomic_write_bytes(destination / "strategy.json", strategy.canonical_bytes())
    return artifact, pd.DataFrame(native).set_index(["datetime", "instrument"]).sort_index()


def load_strategy_signal(
    directory: Path, expected_hash: str
) -> tuple[PersonalSignalArtifact, pd.DataFrame]:
    manifest_raw = _read(confined_regular_file(directory, "manifest.json"), 128_000)
    artifact = _artifact(manifest_raw)
    if artifact.content_hash != expected_hash or artifact.canonical_bytes() != manifest_raw:
        raise ValueError("signal artifact identity changed")
    signal_raw = _read(confined_regular_file(directory, "signals.parquet"))
    if sha256_bytes(signal_raw) != artifact.signals_parquet_sha256:
        raise ValueError("signal Parquet identity changed")
    strategy_raw = _read(confined_regular_file(directory, "strategy.json"), 128_000)
    strategy = PersonalStrategy.model_validate_json(strategy_raw)
    lineage_raw = _read(confined_regular_file(directory, "lineage.json"), 1024**2)
    if (
        strategy.content_hash != artifact.strategy_hash
        or strategy.canonical_bytes() != strategy_raw
        or sha256_bytes(lineage_raw) != artifact.transform_lineage_hash
    ):
        raise ValueError("signal strategy or lineage changed")
    parsed_lineage = json.loads(lineage_raw)
    if not isinstance(parsed_lineage, dict):
        raise ValueError("signal lineage must be an object")
    lineage = cast(dict[str, Any], parsed_lineage)
    translations = [translate_personal_expression(e) for e in _expressions(strategy)]
    if (
        lineage.get("strategy_hash") != artifact.strategy_hash
        or lineage.get("dataset_hash") != artifact.dataset_hash
        or lineage.get("panel_sha256") != artifact.panel_sha256
        or lineage.get("pit_evidence_hash") != artifact.pit_evidence_hash
        or lineage.get("translation_hash") != artifact.expression_translation_hash
        or artifact.expression_translation_hash != sha256_bytes(canonical_json_bytes(translations))
        or lineage.get("expressions") != [e.model_dump(mode="json") for e in _expressions(strategy)]
        or lineage.get("dependencies")
        != json.loads(
            canonical_json_bytes([expression_dependencies(e) for e in _expressions(strategy)])
        )
        or lineage.get("schema_version")
        != (
            "personal-signal-lineage/v2"
            if isinstance(artifact, PersonalSignalArtifactV2)
            else "personal-signal-lineage/v1"
        )
        or (
            isinstance(artifact, PersonalSignalArtifactV2)
            and lineage.get("field_mapping_profile") != artifact.field_mapping_profile
        )
        or lineage.get("rule")
        != "backward dependency availability; input lag once; native execution lag once"
        or set(lineage)
        != (
            {
                "schema_version",
                "strategy_hash",
                "dataset_hash",
                "panel_sha256",
                "pit_evidence_hash",
                "translation_hash",
                "expressions",
                "dependencies",
                "benchmark",
                "rule",
            }
            | (
                {"field_mapping_profile"}
                if isinstance(artifact, PersonalSignalArtifactV2)
                else set()
            )
        )
        or not _valid_code(lineage.get("benchmark"))
    ):
        raise ValueError("signal lineage dependency binding changed")
    table: Any = cast(Any, pq).read_table(io.BytesIO(signal_raw))
    if not table.schema.equals(SIGNAL_SCHEMA, check_metadata=False):
        raise ValueError("signal Arrow schema changed")
    frame: Any = table.to_pandas()
    decoded = tuple(
        SignalRow.model_validate(
            {
                **r,
                "score": float(r["score"]) if pd.notna(r["score"]) else None,
                "schema_version": "signal-row/v2",
            }
        )
        for r in frame.to_dict("records")
    )
    if (
        len(decoded) != artifact.row_count
        or signal_content_hash(decoded) != artifact.signal_content_hash
        or frame.duplicated(["signal_time", "instrument_id"]).any()
    ):
        raise ValueError("signal semantic bytes or row denominator changed")
    times = pd.DatetimeIndex(frame.signal_time).as_unit("ns").tz_convert("Asia/Shanghai")
    if (
        not (times == times.normalize() + pd.Timedelta(hours=23, minutes=59)).all()
        or not (frame.signal_time == frame.decision_time).all()
        or times.min().date() != artifact.start_date
        or times.max().date() != artifact.end_date
        or (frame.score_valid & ~frame.tradable).any()
    ):
        raise ValueError("signal clocks, coverage or tradability changed")
    frame["datetime"] = times.tz_localize(None).normalize().as_unit("ns")
    frame["instrument"] = frame.instrument_id.str[-2:] + frame.instrument_id.str[:6]
    return artifact, cast(
        pd.DataFrame, frame.set_index(["datetime", "instrument"])[["score"]].sort_index()
    )
