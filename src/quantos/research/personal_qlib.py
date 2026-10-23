"""Finite rule signals and Qlib-native Workflow/Record/Exchange/Simulator execution.

No fills, orders, positions or account balances are computed by project code.
Market execution requires the separately bound HS300 successor dataset and trusted
server authorization. This module never grants scientific execution authority.
"""

from __future__ import annotations

import importlib
import math
import pickle
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from quantos.artifacts.store import (
    atomic_write_bytes,
    confined_regular_file,
    regular_tree_files,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hs300_cash import ClassicOriginReuse, PreparedHS300CashStudy
from quantos.contracts.hs300_lifecycle import PreparedHS300LifecycleStudy
from quantos.contracts.personal_research import PreparedHS300Study, PreparedStudy

PANEL_COLUMNS = (
    "trade_date",
    "qlib_id",
    "close",
    "volume",
    "is_mainboard",
    "is_st",
    "sector_momentum_5",
    "available_at",
)


class PersonalPITError(ValueError):
    reason_code = "PIT_HARD_REJECTION"


def _rolling20(values: Any) -> Any:
    return values.rolling(20, min_periods=20).mean()


def _momentum5(values: Any) -> Any:
    return values / values.shift(5) - 1


def _prior_volume5(values: Any) -> Any:
    return values.shift(1).rolling(5, min_periods=5).mean()


def compile_daily_signals(panel: pd.DataFrame, prepared: PreparedStudy) -> dict[str, pd.DataFrame]:
    """Compile predeclared rule ranks, with one availability cutoff per signal bar."""
    if set(panel.columns) != set(PANEL_COLUMNS):
        raise ValueError("panel fields must match personal daily panel/v1")
    frame: Any = panel.copy()
    frame["datetime"] = pd.to_datetime(frame.pop("trade_date"))
    if frame.duplicated(["datetime", "qlib_id"]).any():
        raise ValueError("duplicate daily observations")
    if frame.empty or frame["datetime"].dt.tz is not None:
        raise ValueError("daily dates must be nonempty timezone-naive session dates")
    # All fields, including board/sector membership, must be available at signal time.
    # Missing or naive timestamps are rejected rather than silently assuming a timezone.
    for row in frame.itertuples():
        available = pd.Timestamp(row.available_at)
        if pd.isna(available) or available.tzinfo is None:
            raise ValueError("PIT availability must be explicit and timezone-aware")
        cutoff = pd.Timestamp(row.datetime).tz_localize("Asia/Shanghai") + pd.Timedelta(
            hours=23, minutes=59
        )
        if available > cutoff or available > pd.Timestamp.now(tz="UTC"):
            raise PersonalPITError("PIT hard rejection: an input was unavailable at signal time")
    if frame[["is_mainboard", "is_st"]].isna().any().any():
        raise ValueError("unknown PIT membership/ST status cannot be admitted")
    if not all(
        isinstance(value, (bool, np.bool_))
        for column in ("is_mainboard", "is_st")
        for value in frame[column]
    ):
        raise ValueError("membership/ST fields must be booleans")
    required = frame["is_mainboard"] | (frame["qlib_id"] == prepared.request.benchmark)
    for column in ("close", "volume"):
        if not np.isfinite(
            cast(Any, pd.to_numeric(frame.loc[required, column], errors="coerce"))
        ).all():
            raise PersonalPITError(
                "PIT hard rejection: required price/volume is missing or nonfinite"
            )
    if not np.isfinite(
        cast(
            Any,
            pd.to_numeric(frame.loc[frame["is_mainboard"], "sector_momentum_5"], errors="coerce"),
        )
    ).all():
        raise PersonalPITError(
            "PIT hard rejection: required THS sector value is missing or nonfinite"
        )
    if (frame.loc[required, "close"] <= 0).any() or (frame.loc[required, "volume"] < 0).any():
        raise PersonalPITError("PIT hard rejection: invalid price/volume")
    frame = frame.sort_values(["qlib_id", "datetime"], kind="mergesort")
    groups = frame.groupby("qlib_id", sort=False)
    frame["sma20"] = groups["close"].transform(_rolling20)
    frame["momentum5"] = groups["close"].transform(_momentum5)
    frame["volume_ratio"] = frame["volume"] / groups["volume"].transform(_prior_volume5)
    benchmark = frame[frame["qlib_id"] == prepared.request.benchmark].set_index("datetime")
    if benchmark.empty:
        raise ValueError("benchmark panel is missing")
    regime = benchmark["close"] > benchmark["sma20"]
    frame["regime"] = frame["datetime"].map(regime).fillna(False).astype(bool)
    basic = (
        frame["is_mainboard"]
        & ~frame["is_st"]
        & frame["regime"]
        & (frame["volume"] > 0)
        & (frame["close"] > 0)
    )
    trend = basic & (frame["close"] > frame["sma20"])
    main = (
        trend
        & (frame["momentum5"] > 0)
        & (frame["volume_ratio"] >= prepared.request.profile.minimum_volume_ratio)
        & (frame["sector_momentum_5"] > 0)
    )
    dates = sorted(frame["datetime"].unique())
    request = prepared.request
    if request.start_date is None or request.end_date is None:
        raise ValueError("execution dates were not bound")
    execution_dates = [
        day for day in dates if request.start_date <= pd.Timestamp(day).date() <= request.end_date
    ]
    if not execution_dates:
        raise ValueError("no execution sessions")
    date_positions = {day: index for index, day in enumerate(dates)}
    if any(date_positions[day] == 0 for day in execution_dates):
        raise ValueError("execution needs a prior signal session")
    signal_dates = {dates[date_positions[day] - 1] for day in execution_dates}
    # Require 20 complete sessions before first signal, not merely 20 available records.
    if min(date_positions[day] for day in signal_dates) < 19:
        raise ValueError("insufficient trend warmup")
    instruments = sorted(frame.loc[frame["is_mainboard"], "qlib_id"].unique())
    expected = pd.MultiIndex.from_product(
        [sorted(signal_dates), instruments], names=["datetime", "instrument"]
    )
    if len(expected) == 0:
        raise ValueError("no mainboard universe")
    observed = frame.set_index(["datetime", "qlib_id"]).index
    if not expected.isin(observed).all():
        raise ValueError(
            "daily PIT panel is incomplete; absent rows cannot imply delisting or ineligibility"
        )
    outputs: dict[str, pd.DataFrame] = {}
    score: Any
    for candidate in prepared.candidates:
        if candidate.role == "classic":
            score = (frame["close"] / frame["sma20"] - 1).where(trend)
        elif candidate.role == "main":
            score = (
                frame["momentum5"] + request.profile.sector_weight * frame["sector_momentum_5"]
            ).where(main)
        else:
            score = pd.Series(
                [
                    int(
                        sha256_bytes(
                            canonical_json_bytes((candidate.seed, row.datetime.date(), row.qlib_id))
                        )[:13],
                        16,
                    )
                    / 16**13
                    for row in frame.itertuples()
                ],
                index=frame.index,
            ).where(main)
        values = pd.Series(
            score.to_numpy(),
            index=pd.MultiIndex.from_arrays(
                [frame["datetime"], frame["qlib_id"]], names=["datetime", "instrument"]
            ),
        )
        output = values.reindex(expected).rename("score").to_frame()
        # NaN explicitly means ineligible and empty selection liquidates via native target weights.
        if np.isinf(output["score"]).any():
            raise ValueError("nonfinite signal")
        outputs[candidate.candidate_id] = output
    return outputs


def _finite(value: object) -> float | None:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _metrics(report: pd.DataFrame, indicators: pd.DataFrame) -> dict[str, Any]:
    if report.empty or report[["return", "cost", "account", "bench"]].isna().any().any():
        raise ValueError("native Qlib report is incomplete")
    native_report: Any = report
    native_indicators: Any = indicators
    net: Any = native_report["return"] - native_report["cost"]
    wealth = (1 + net).cumprod()
    # Metrics summarize Qlib output; Qlib remains the only account/position authority.
    return {
        "net_total_return": _finite(wealth.iloc[-1] - 1),
        "benchmark_total_return": _finite((1 + native_report["bench"]).prod() - 1),
        "excess_total_return": _finite(wealth.iloc[-1] - (1 + native_report["bench"]).prod()),
        "max_drawdown": _finite((wealth / wealth.cummax().clip(lower=1) - 1).min()),
        "total_cost_cny": _finite(native_report["total_cost"].iloc[-1]),
        "total_turnover": _finite(native_report["turnover"].sum()),
        "order_count": _finite(native_indicators["count"].sum(min_count=1))
        if "count" in indicators
        else None,
        "mean_risk_exposure": _finite((native_report["value"] / native_report["account"]).mean()),
        "sessions": len(report),
        "yearly_net_returns": {
            str(year): _finite((1 + part).prod() - 1) for year, part in net.groupby(net.index.year)
        },
        "actual_exposure": {
            "mean": _finite((native_report["value"] / native_report["account"]).mean()),
            "minimum": _finite((native_report["value"] / native_report["account"]).min()),
            "maximum": _finite((native_report["value"] / native_report["account"]).max()),
        },
        "subperiod_net_returns": [
            {
                "start": str(part.index[0].date()),
                "end": str(part.index[-1].date()),
                "net_return": _finite((1 + part).prod() - 1),
            }
            for part in (net.iloc[: max(1, len(net) // 2)], net.iloc[max(1, len(net) // 2) :])
            if len(part)
        ],
    }


def _native_order_rows(indicator: Any) -> pd.DataFrame:
    """Export Qlib's observed orders/fills, without reconstructing executions."""
    parts: list[pd.DataFrame] = []
    for session, order_indicator in indicator.order_indicator_his.items():
        # Qlib 0.9.7's SingleData.to_series passes its custom Index directly to
        # pandas, which newer pandas rejects. Its public to_dict export preserves
        # the exact same observed metric values without modifying Qlib objects.
        values = {
            metric: pd.Series(order_indicator.get_index_data(metric).to_dict(), dtype=float)
            for metric in (
                "amount",
                "deal_amount",
                "trade_dir",
                "trade_price",
                "trade_value",
                "trade_cost",
            )
        }
        if not values:
            continue
        frame = pd.DataFrame(values).rename_axis("instrument").reset_index()
        frame["datetime"] = session
        parts.append(frame)
    if not parts:
        return pd.DataFrame(
            columns=["datetime", "instrument", "amount", "deal_amount", "trade_dir"]
        )
    return pd.concat(parts, ignore_index=True)


class PersonalQlibExecutor:
    def __init__(self, catalog: Mapping[str, Any]) -> None:
        self.catalog = dict(catalog)

    def __call__(
        self,
        prepared: PreparedStudy | PreparedHS300Study | PreparedHS300LifecycleStudy,
        root: Path,
        cancelled: Callable[[], bool],
    ) -> dict[str, Any]:
        # Qlib/MLflow switches cwd while recording. Every authority output must
        # remain bound to the caller's root across that context switch.
        root = root.absolute()
        qlib = cast(Any, importlib.import_module("qlib"))
        D = cast(Any, importlib.import_module("qlib.data")).D
        R = cast(Any, importlib.import_module("qlib.workflow")).R
        PortAnaRecord = cast(
            Any, importlib.import_module("qlib.workflow.record_temp")
        ).PortAnaRecord

        from quantos.research.qlib.workflow import (
            _WORKFLOW_LOCK,  # pyright: ignore[reportPrivateUsage]
            _flush_recorder_logs,  # pyright: ignore[reportPrivateUsage]
            _workflow_tracking_runtime,  # pyright: ignore[reportPrivateUsage]
        )

        manifest = prepared.dataset_manifest
        cash_runtime = isinstance(prepared, PreparedHS300CashStudy)
        lifecycle = isinstance(prepared, PreparedHS300LifecycleStudy)
        hs300 = isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy))
        if manifest is None or (manifest.kind != "synthetic" and not hs300):
            raise PermissionError("real-market successor PIT/cost adapter is not yet qualified")
        if qlib.__version__ != "0.9.7":
            raise RuntimeError("personal native adapter requires Qlib 0.9.7")
        binding = self.catalog[manifest.dataset_id]
        if binding.manifest != manifest:
            raise ValueError("server catalog changed after prepare")
        if cash_runtime:
            from quantos.research.hs300_cash_runtime import verify_hs300_cash_binding

            verify_hs300_cash_binding(binding)
        elif lifecycle:
            from quantos.research.hs300_lifecycle_data import verify_hs300_lifecycle_binding

            verify_hs300_lifecycle_binding(binding)
        elif hs300:
            from quantos.research.hs300_data import verify_hs300_binding

            verify_hs300_binding(binding)
        if binding.pit_evidence_path is None:
            raise ValueError("PIT evidence original is missing")
        verify_file(binding.pit_evidence_path, manifest.pit_evidence_hash)
        import json

        pit = json.loads(binding.pit_evidence_path.read_bytes())
        if not hs300 and (
            pit.get("panel_sha256") != manifest.panel_sha256
            or pit.get("snapshot_hash") != manifest.snapshot_hash
            or pit.get("kind") != "synthetic"
        ):
            raise ValueError("PIT evidence bindings disagree")
        verify_file(binding.panel_path, manifest.panel_sha256)
        observed = {
            path.relative_to(binding.provider_root).as_posix(): path
            for path in regular_tree_files(binding.provider_root)
            if not (hs300 and manifest.kind == "market" and path.name == "manifest.json")
        }
        if set(observed) != set(manifest.qlib_files):
            raise ValueError("Qlib cache file inventory changed")
        for logical, digest in manifest.qlib_files.items():
            verify_file(confined_regular_file(binding.provider_root, logical), digest)
        panel = pd.read_parquet(binding.panel_path)
        if cash_runtime and prepared.signal_reuse is not None:
            from quantos.research.hs300_cash_runtime import load_reused_signals

            signals = load_reused_signals(prepared, prepared.signal_reuse)
        elif lifecycle:
            from quantos.research.hs300_lifecycle_data import compile_hs300_lifecycle_signals

            signals = compile_hs300_lifecycle_signals(panel, prepared)
        elif hs300:
            from quantos.research.hs300_data import compile_hs300_daily_signals

            signals = compile_hs300_daily_signals(panel, prepared)
        else:
            signals = compile_daily_signals(panel, prepared)
        receipts: list[dict[str, Any]] = []
        origins: dict[str, dict[str, Any]] = {}
        origin_by_id: dict[str, ClassicOriginReuse] = {}
        origin_reuse: list[dict[str, Any]] = []
        if cash_runtime:
            from quantos.research.hs300_cash_runtime import verify_classic_origin

            for origin in prepared.origin_reuse:
                origins[origin.candidate_id] = verify_classic_origin(prepared, origin)
                origin_by_id[origin.candidate_id] = origin
                origin_reuse.append(
                    {
                        "candidate_id": origin.candidate_id,
                        "origin_hash": origin.content_hash,
                        "origin": origin.model_dump(mode="json"),
                    }
                )
        receipt: dict[str, Any]
        with _WORKFLOW_LOCK:
            qlib.init(
                provider_uri=str(binding.provider_root.absolute()),
                region="cn",
                kernels=1,
                expression_cache=None,
                dataset_cache=None,
            )
            # Check canonical panel prices/volumes against the derived Qlib cache before execution.
            features: Any = D.features(
                sorted(panel["qlib_id"].unique()),
                ["$close", "$volume"],
                pd.to_datetime(panel["trade_date"]).min(),
                pd.to_datetime(panel["trade_date"]).max(),
            )
            indexed = panel.assign(datetime=pd.to_datetime(panel["trade_date"])).set_index(
                ["qlib_id", "datetime"]
            )
            aligned = features.reindex(indexed.index)
            # The immutable view intentionally masks suspended OHLCV as NaN.
            if hs300:
                indexed = indexed.loc[~indexed["is_suspended"]]
                aligned = aligned.reindex(indexed.index)
            for column, native in (("close", "$close"), ("volume", "$volume")):
                if not np.allclose(
                    indexed[column], aligned[native], rtol=1e-6, atol=1e-6, equal_nan=True
                ):
                    raise ValueError("canonical panel and derived Qlib cache disagree")
            for candidate in prepared.candidates:
                if cancelled():
                    break
                if candidate.candidate_id in origins:
                    continue
                destination = root / candidate.candidate_id
                destination.mkdir(parents=True, exist_ok=True)
                runtime = destination / "runtime"
                runtime.mkdir()
                try:
                    if cash_runtime and prepared.signal_reuse is not None:
                        from quantos.research.hs300_cash_runtime import reused_signal_bytes

                        signal_bytes = reused_signal_bytes(
                            prepared.signal_reuse, candidate.candidate_id
                        )
                    else:
                        signal_bytes = pickle.dumps(signals[candidate.candidate_id], protocol=4)
                    atomic_write_bytes(destination / "signal.pkl", signal_bytes)
                    config = self._config(
                        prepared,
                        signals[candidate.candidate_id],
                        binding=binding,
                        boundary_root=destination / "native-boundaries",
                    )
                    atomic_write_bytes(
                        destination / "native-config.json", canonical_json_bytes(config)
                    )
                    with _workflow_tracking_runtime(runtime, "frozen-field-study/v1") as uri:  # noqa: SIM117
                        with R.start(
                            experiment_name="personal-hs300-cash-v2"
                            if cash_runtime
                            else "personal-hs300-lifecycle-v1"
                            if lifecycle
                            else "personal-hs300-v1"
                            if hs300
                            else "personal-synthetic-v1",
                            uri=uri,
                        ):
                            recorder = R.get_recorder()
                            recorder.save_objects(
                                **{"pred.pkl": signals[candidate.candidate_id], "label.pkl": None}
                            )
                            record = PortAnaRecord(
                                recorder,
                                config=config,
                                risk_analysis_freq=[],
                                indicator_analysis_freq=[],
                            )
                            record.generate()
                            _flush_recorder_logs(recorder)
                            exports = {"signal.pkl": sha256_bytes(signal_bytes)}
                            objects: dict[str, Any] = {}
                            for name in (
                                "report_normal_1day.pkl",
                                "positions_normal_1day.pkl",
                                "indicators_normal_1day.pkl",
                                "indicators_normal_1day_obj.pkl",
                            ):
                                value = recorder.load_object(f"portfolio_analysis/{name}")
                                objects[name] = value
                                encoded = pickle.dumps(value, protocol=4)
                                atomic_write_bytes(destination / name, encoded)
                                exports[name] = sha256_bytes(encoded)
                            report = objects["report_normal_1day.pkl"]
                            from io import BytesIO

                            stream = BytesIO()
                            report.to_parquet(stream)
                            atomic_write_bytes(destination / "portfolio.parquet", stream.getvalue())
                            exports["portfolio.parquet"] = sha256_file(
                                destination / "portfolio.parquet"
                            )
                            exports["native-config.json"] = sha256_file(
                                destination / "native-config.json"
                            )
                            metrics = _metrics(report, objects["indicators_normal_1day.pkl"])
                            if hs300:
                                orders = _native_order_rows(
                                    objects["indicators_normal_1day_obj.pkl"]
                                )
                                stream = BytesIO()
                                orders.to_parquet(stream, index=False)
                                atomic_write_bytes(
                                    destination / "native-orders.parquet", stream.getvalue()
                                )
                                exports["native-orders.parquet"] = sha256_file(
                                    destination / "native-orders.parquet"
                                )
                                metrics["native_order_count"] = int(
                                    orders["amount"].fillna(0).ne(0).sum()
                                )
                                metrics["native_filled_order_count"] = int(
                                    orders["deal_amount"].fillna(0).ne(0).sum()
                                )
                                metrics["native_unfilled_order_count"] = int(
                                    (
                                        orders["amount"].fillna(0).ne(0)
                                        & orders["deal_amount"].fillna(0).eq(0)
                                    ).sum()
                                )
                            receipt = {
                                "schema_version": "personal-native-receipt/v1",
                                "prepared_hash": prepared.content_hash,
                                "candidate_id": candidate.candidate_id,
                                "run_status": "SUCCEEDED",
                                "validation_verdict": "NOT_EVALUATED",
                                "evidence_kind": manifest.kind,
                                "exposure": manifest.exposure,
                                "qlib_version": qlib.__version__,
                                "recorder_id": recorder.id,
                                "metrics": metrics,
                                "files": exports,
                                "signal_sha256": sha256_bytes(signal_bytes),
                            }
                except Exception as error:
                    receipt = {
                        "schema_version": "personal-native-receipt/v1",
                        "prepared_hash": prepared.content_hash,
                        "candidate_id": candidate.candidate_id,
                        "run_status": "FAILED",
                        "validation_verdict": "NOT_EVALUATED",
                        "error_type": type(error).__name__,
                        "metrics": None,
                        "files": {},
                    }
                if cash_runtime:
                    # Bind attempted inputs even when a boundary stops before
                    # Qlib's terminal report/export stage.
                    for name in ("signal.pkl", "native-config.json"):
                        path = destination / name
                        if path.is_file():
                            receipt["files"][name] = sha256_file(path)
                    if "signal.pkl" in receipt["files"]:
                        receipt["signal_sha256"] = receipt["files"]["signal.pkl"]
                if lifecycle:
                    boundary_root = destination / "native-boundaries"
                    boundary_receipts: list[dict[str, str]] = []
                    partial: dict[str, str] = {}
                    statuses: list[str] = []
                    if boundary_root.exists():
                        for path in regular_tree_files(boundary_root):
                            logical = path.relative_to(destination).as_posix()
                            digest = sha256_file(path)
                            receipt["files"][logical] = digest
                            if path.suffix == ".json":
                                boundary_receipts.append({"file": logical, "sha256": digest})
                                value = json.loads(path.read_bytes())
                                statuses.extend(item["status"] for item in value["decisions"])
                            else:
                                partial[logical] = digest
                    receipt.update(
                        {
                            "native_boundary_status": "HARD_STOP_EXPOSURE"
                            if "HARD_STOP_EXPOSURE" in statuses
                            else (
                                "HARD_STOP_UNKNOWN"
                                if "HARD_STOP_UNKNOWN" in statuses
                                else (
                                    "CLEARED_DERIVED_CASH_INELIGIBILITY"
                                    if "CLEARED_DERIVED_CASH_INELIGIBILITY" in statuses
                                    else "CLEARED_ZERO_EXPOSURE"
                                    if statuses
                                    else "NOT_REACHED"
                                )
                            ),
                            "boundary_receipts": boundary_receipts,
                            "native_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
                            "partial_native_artifacts": partial,
                        }
                    )
                atomic_write_bytes(destination / "receipt.json", canonical_json_bytes(receipt))
                receipts.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "receipt_hash": sha256_file(destination / "receipt.json"),
                        "run_status": receipt["run_status"],
                    }
                )
        outcome = {
            "schema_version": "personal-native-outcome/v1",
            "prepared_hash": prepared.content_hash,
            "run_status": "SUCCEEDED"
            if len(receipts) + len(origin_reuse) == len(prepared.candidates)
            and all(item["run_status"] == "SUCCEEDED" for item in receipts)
            else "FAILED",
            "validation_verdict": "NOT_EVALUATED",
            "planned_denominator": len(prepared.candidates),
            "receipts": receipts,
            **({"origin_reuse": origin_reuse} if cash_runtime else {}),
        }
        if hs300:
            by_id = {item["candidate_id"]: item for item in receipts}
            for candidate_id in origins:
                by_id[candidate_id] = {
                    "candidate_id": candidate_id,
                    "receipt_hash": origin_by_id[candidate_id].receipt.sha256,
                    "run_status": "REUSED_ORIGIN",
                }
            comparison = {
                "schema_version": "hs300-native-comparison/v1",
                "prepared_hash": prepared.content_hash,
                "planned_denominator": len(prepared.candidates),
                "validation_verdict": "NOT_EVALUATED",
                "comparison_scope": prepared.comparison_scope,
                "rows": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "role": candidate.role,
                        "seed": candidate.seed,
                        "run_status": by_id.get(candidate.candidate_id, {}).get(
                            "run_status", "MISSING"
                        ),
                        "receipt_hash": by_id.get(candidate.candidate_id, {}).get("receipt_hash"),
                        "metrics": origins[candidate.candidate_id].get("metrics")
                        if candidate.candidate_id in origins
                        else json.loads(
                            (root / candidate.candidate_id / "receipt.json").read_bytes()
                        ).get("metrics")
                        if candidate.candidate_id in by_id
                        else None,
                        **(
                            {
                                key: origins[candidate.candidate_id].get(key)
                                if candidate.candidate_id in origins
                                else json.loads(
                                    (root / candidate.candidate_id / "receipt.json").read_bytes()
                                ).get(key)
                                if candidate.candidate_id in by_id
                                else None
                                for key in (
                                    "native_boundary_status",
                                    "boundary_receipts",
                                    "native_rights_observability",
                                    "partial_native_artifacts",
                                )
                            }
                            if lifecycle
                            else {}
                        ),
                        **(
                            {"origin": origin_by_id[candidate.candidate_id].model_dump(mode="json")}
                            if candidate.candidate_id in origins
                            else {}
                        ),
                    }
                    for candidate in prepared.candidates
                ],
                "limits": prepared.limits,
            }
            atomic_write_bytes(root / "comparison.json", canonical_json_bytes(comparison))
            outcome["comparison_sha256"] = sha256_file(root / "comparison.json")
        return outcome

    @staticmethod
    def _config(
        prepared: PreparedStudy | PreparedHS300Study | PreparedHS300LifecycleStudy,
        signal: pd.DataFrame,
        *,
        binding: Any = None,
        boundary_root: Path | None = None,
    ) -> dict[str, Any]:
        profile: Any = prepared.request.profile
        manifest: Any = prepared.dataset_manifest
        assert manifest is not None
        config: dict[str, Any] = {
            "strategy": {
                "class": "FullReplacementTopKStrategy",
                "module_path": "quantos.backtest.strategy",
                "kwargs": {
                    "signal": "<PRED>",
                    "topk": profile.top_k,
                    "max_weight": profile.max_weight,
                    "risk_degree": profile.risk_degree,
                },
            },
            "executor": {
                "class": "SimulatorExecutor",
                "module_path": "qlib.backtest.executor",
                "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
            },
            "backtest": {
                "start_time": str(prepared.request.start_date),
                "end_time": str(prepared.request.end_date),
                "account": profile.initial_cash_cny,
                "benchmark": prepared.request.benchmark,
                "exchange_kwargs": {
                    "freq": "day",
                    "codes": sorted(
                        set(signal.index.get_level_values("instrument"))
                        | {prepared.request.benchmark}
                    ),
                    "start_time": str(signal.index.get_level_values("datetime").min().date()),
                    "end_time": str(manifest.end_date),
                    "deal_price": "$open",
                    "trade_unit": 100,
                    "open_cost": profile.buy_cost,
                    "close_cost": profile.sell_cost,
                    "min_cost": profile.minimum_cost_cny,
                    "limit_threshold": ("$limit_buy+$is_st", "$limit_sell+$is_st"),
                    "volume_threshold": ("current", f"$volume*{profile.volume_participation}"),
                },
            },
        }
        if isinstance(prepared, (PreparedHS300Study, PreparedHS300LifecycleStudy)):
            native = config["backtest"]["exchange_kwargs"]
            native["trade_unit"] = profile.trade_unit_shares
            if manifest.kind == "market" or (
                binding is not None
                and binding.snapshot_path is not None
                and "canonical/price_limits.parquet" in manifest.source_files
            ):
                if binding is None or binding.snapshot_path is None:
                    raise ValueError("HS300 native execution requires canonical daily limits")
                native["subscribe_fields"] = ["$is_st"]
                config["backtest"]["exchange_kwargs"] = {
                    "exchange": {
                        "class": "HS300OpenLimitExchange",
                        "module_path": "quantos.research.hs300_exchange",
                        "kwargs": {
                            **native,
                            "price_limits_path": str(
                                (
                                    binding.snapshot_path / "canonical/price_limits.parquet"
                                ).absolute()
                            ),
                            "price_limits_sha256": manifest.source_files[
                                "canonical/price_limits.parquet"
                            ],
                        },
                    },
                }
        if isinstance(prepared, PreparedHS300LifecycleStudy):
            if binding is None or binding.lifecycle_path is None or boundary_root is None:
                raise ValueError(
                    "native lifecycle execution requires bound facts and boundary output"
                )
            config["strategy"]["class"] = "LifecycleBoundaryTopKStrategy"
            config["strategy"]["module_path"] = "quantos.research.hs300_native_boundary"
            config["strategy"]["kwargs"].update(
                {
                    "lifecycle_path": str(binding.lifecycle_path.absolute()),
                    "lifecycle_manifest_hash": manifest.lifecycle_manifest_hash,
                    "boundary_root": str(boundary_root.absolute()),
                    "expected_initial_cash_cny": profile.initial_cash_cny,
                }
            )
            if isinstance(prepared, PreparedHS300CashStudy):
                config["strategy"]["class"] = "CashRuntimeBoundaryTopKStrategy"
                config["strategy"]["module_path"] = "quantos.research.hs300_cash_runtime"
                config["strategy"]["kwargs"].update(
                    {
                        "cash_rules": [
                            rule.model_dump(mode="json") for rule in manifest.cash_rules
                        ],
                        "native_source_hashes": manifest.native_source_hashes,
                    }
                )
        return config
