"""One explicitly authorized confirm2 exploration; native Qlib owns the account.

This is a separate research identity, not a v3 request or a mutation of its grant.
The original prepared object is read only as the frozen execution configuration.
"""
from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import pickle
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "artifacts/hosted-evidence/hs300-eligibility-confirm2-20261103-01"
IDENTITY = "hs300-eligibility-confirm2-exploratory/20261103-v1"
CONTRACT = REPO / "docs/reviews/hs300-eligibility-successor-20261103.md"
CONTRACT_HASH = "1c1fc8fd20c725abd7597fc1ea50d3f8e34667cff403895d34f7cc78f208fb33"
ATTR = REPO / "artifacts/personal-research-product-20261103/turnover-attribution-01"
TASKS = REPO / "artifacts/personal-research-product-20261022/run-01/product/tasks"
NEW = TASKS / "5f491a287a448899c5477248dfba1aef74b4f10e9bd94247798c5aafcaaf2c6c"
OLD = TASKS / "40e4d6d4bcd1d42eab360293930608a773303e94663c036bc4c002179f16919c"
IDS = ("main", "classic", "random-17", "random-41", "random-73", "random-101", "random-137")
LIMITS = dict(new_native_accounts=1, sessions=721, workers=1, wall_seconds=900,
              new_persistent_bytes=536870912, sdk_calls=0, acquisition_calls=0,
              training=0, automatic_retries=0, parameter_search=0)
VERIFIED = {}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path, expected=None):
    path = Path(path)
    raw = path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if expected is not None and observed != expected:
        raise ValueError("INPUT_HASH_MISMATCH")
    VERIFIED[str(path)] = observed
    return raw


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                     default=str, allow_nan=False).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def bind_authorization():
    read(CONTRACT, CONTRACT_HASH)
    auth = json.loads(read(ROOT / "authorization.json"))
    assert auth["identity"] == IDENTITY and auth["contract_sha256"] == CONTRACT_HASH
    assert auth["limits"] == LIMITS
    freeze = json.loads(read(ATTR / "freeze-receipt.json", auth["proposal_freeze_receipt_sha256"]))
    for logical, expected in freeze["files"].items():
        read(REPO / logical, expected)
    return auth


def baseline_rows():
    # Retain every original tuple, including classic's distinct originating tuple.
    raw = json.loads(read(ATTR / "input-verification.json"))
    expected = {str(REPO / x["path"]): x["sha256"] for x in raw}
    prepared = json.loads(read(NEW / "prepared.json", NEW.name))
    rows = []
    for cid in IDS:
        directory = (OLD if cid == "classic" else NEW) / "execution" / cid
        path = directory / "receipt.json"
        receipt = json.loads(read(path, expected[str(path)]))
        assert receipt["run_status"] == "SUCCEEDED"
        assert receipt["prepared_hash"] == (OLD.name if cid == "classic" else NEW.name)
        assert receipt["signal_sha256"] == prepared["signal_reuse"]["signal_files"][cid]["sha256"]
        rows.append(dict(candidate_id=cid, role="PRIMARY_BASELINE" if cid == "main" else "BACKGROUND_ORIGIN",
                         prepared_hash=receipt["prepared_hash"], receipt_path=str(path),
                         receipt_sha256=digest(path), adoption="REUSED_ORIGIN_NOT_NEW_PASS",
                         run_status=receipt["run_status"], metrics=receipt["metrics"]))
    return rows


def signal_and_market(prepared, binding, signals):
    import numpy as np
    import pandas as pd
    from quantos.research.hs300_data import _hs300_sma20, _hs300_momentum5, _hs300_prior_amount5
    from quantos.research.personal_qlib import PersonalPITError

    # One panel decode. Reuse admitted full-period PIT; inspect extra-day dependencies.
    panel = pd.read_parquet(binding.panel_path)
    panel["datetime"] = pd.to_datetime(panel.trade_date)
    bench = panel.loc[panel.qlib_id.eq("SH000300")].set_index("datetime").sort_index()
    assert bench.index.is_unique
    market = bench.close > _hs300_sma20(bench.close)
    dates = list(bench.index)
    previous = {dates[i]: dates[i - 1] for i in range(1, len(dates))}
    main = signals["main"]["score"].unstack("instrument")
    assert len(main) == 721 and main.index.is_unique and main.index.is_monotonic_increasing
    first = main.index[0]
    prior = previous[first]
    offset = dates.index(prior)
    assert offset >= 19
    window = dates[offset - 19:offset + 1]
    frame = panel.loc[panel.datetime.isin(window)].copy()
    assert not frame.duplicated(["datetime", "qlib_id"]).any()
    dense = pd.MultiIndex.from_product([window, main.columns])
    assert dense.isin(frame.set_index(["datetime", "qlib_id"]).index).all()
    frame["is_member"] &= frame.is_listed
    observed = frame.close.notna() | frame.is_member | frame.qlib_id.eq("SH000300")
    availability = pd.to_datetime(frame.loc[observed, "available_at"], utc=True)
    cutoff = frame.loc[observed, "datetime"].dt.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=23, minutes=59)
    if (availability.isna().any() or (availability > cutoff).any()
            or any(pd.Timestamp(x).tzinfo is None for x in frame.loc[observed, "available_at"])):
        raise PersonalPITError("PIT_HARD_REJECTION")
    for name in ("is_member", "is_listed", "is_st", "is_suspended"):
        assert all(isinstance(x, (bool, np.bool_)) for x in frame[name])
    required = (frame.is_member & ~frame.is_suspended) | frame.qlib_id.eq("SH000300")
    numeric = frame.loc[required, ["close", "volume", "amount_cny"]]
    if (not np.isfinite(numeric).all().all() or (numeric.close <= 0).any()
            or (numeric[["volume", "amount_cny"]] < 0).any().any()):
        raise PersonalPITError("PIT_HARD_REJECTION")
    frame = frame.sort_values(["qlib_id", "datetime"], kind="mergesort")
    groups = frame.groupby("qlib_id", sort=False)
    frame["sma20"] = groups.close.transform(_hs300_sma20)
    frame["momentum5"] = groups.close.transform(_hs300_momentum5)
    frame["amount_ratio"] = frame.amount_cny / groups.amount_cny.transform(_hs300_prior_amount5)
    day = frame.loc[frame.datetime.eq(prior)].set_index("qlib_id").reindex(main.columns)
    prior_e = (day.is_member & ~day.is_st & ~day.is_suspended & bool(market.loc[prior])
               & (day.close > day.sma20) & (day.volume > 0) & (day.momentum5 > 0)
               & (day.amount_ratio >= prepared.request.profile.minimum_amount_ratio))
    extra = day[["close", "volume", "sma20", "momentum5", "amount_ratio", "is_member", "is_listed", "is_st", "is_suspended"]].copy()
    extra["original_eligibility"] = prior_e
    extra.to_parquet(ROOT / "initial-eligibility.parquet")
    eligible = main.notna()
    confirmation = eligible.copy()
    for dt in main.index:
        prev = previous[dt]
        eprev = prior_e if dt == first else eligible.loc[prev]
        confirmation.loc[dt] = eligible.loc[dt] & ((not bool(market.loc[prev])) | eprev)
    filtered = main.where(confirmation)
    # Retain the exact original index, instrument inventory and all surviving scores.
    stacked = filtered.stack(future_stack=True).rename("score").to_frame()
    signal = stacked.reindex(signals["main"].index)
    assert signal.index.equals(signals["main"].index)
    assert signal.loc[signal.score.notna()].equals(signals["main"].loc[signal.score.notna()])
    signal.to_pickle(ROOT / "signal.pkl", protocol=4)
    save(ROOT / "signal-receipt.json", dict(identity=IDENTITY, contract_sha256=CONTRACT_HASH,
        original_signal_sha256=prepared.signal_reuse.signal_files["main"].sha256,
        signal_sha256=digest(ROOT / "signal.pkl"), panel_sha256=prepared.dataset_manifest.panel_sha256,
        initial_prior_session=str(prior.date()), initial_dependency_sessions=[str(x.date()) for x in window],
        initial_eligibility_sha256=digest(ROOT / "initial-eligibility.parquet"),
        original_eligible_cells=int(eligible.sum().sum()), confirmed_cells=int(confirmation.sum().sum()),
        removed_cells=int((eligible & ~confirmation).sum().sum()), signal_sessions=len(main)))
    return signal, main, market, previous


def execute_native(prepared, binding, signal, run_binding):
    import qlib
    from qlib.workflow import R
    from qlib.workflow.record_temp import PortAnaRecord
    from quantos.research.personal_qlib import PersonalQlibExecutor, _metrics, _native_order_rows
    from quantos.research.qlib.workflow import _WORKFLOW_LOCK, _workflow_tracking_runtime, _flush_recorder_logs
    dest = ROOT / "main-confirm2"
    dest.mkdir()
    runtime = dest / "runtime"
    runtime.mkdir()
    # Frozen original configuration, with the new signal and new boundary output only.
    config = PersonalQlibExecutor._config(prepared, signal, binding=binding,
                                          boundary_root=dest / "native-boundaries")
    save(dest / "native-config.json", config)
    original_receipt = json.loads(read(NEW / "execution/main/receipt.json"))
    source_config = json.loads(read(NEW / "execution/main/native-config.json",
                                    original_receipt["files"]["native-config.json"]))
    comparison_config = json.loads(json.dumps(config, default=str))
    comparison_config["strategy"]["kwargs"]["boundary_root"] = source_config["strategy"]["kwargs"]["boundary_root"]
    assert comparison_config == source_config
    save(ROOT / "native-start.json", dict(identity=IDENTITY, account_invocations=1,
        at=datetime.now(UTC), run_binding_sha256=run_binding, signal_sha256=digest(ROOT / "signal.pkl")))
    with _WORKFLOW_LOCK:
        qlib.init(provider_uri=str(binding.provider_root), region="cn", kernels=1,
                  expression_cache=None, dataset_cache=None)
        assert qlib.__version__ == "0.9.7"
        with _workflow_tracking_runtime(runtime, "frozen-field-study/v1") as uri:
            with R.start(experiment_name="hs300-eligibility-confirm2-20261103-v1", uri=uri):
                recorder = R.get_recorder()
                recorder.save_objects(**{"pred.pkl": signal, "label.pkl": None})
                record = PortAnaRecord(recorder, config=config, risk_analysis_freq=[], indicator_analysis_freq=[])
                record.generate()
                _flush_recorder_logs(recorder)
                objects = {}
                for name in ("report_normal_1day.pkl", "positions_normal_1day.pkl",
                             "indicators_normal_1day.pkl", "indicators_normal_1day_obj.pkl"):
                    objects[name] = recorder.load_object("portfolio_analysis/" + name)
                    with (dest / name).open("xb") as stream:
                        pickle.dump(objects[name], stream, protocol=4)
                report = objects["report_normal_1day.pkl"]
                report.to_parquet(dest / "portfolio.parquet")
                orders = _native_order_rows(objects["indicators_normal_1day_obj.pkl"])
                orders.to_parquet(dest / "native-orders.parquet", index=False)
                metrics = _metrics(report, objects["indicators_normal_1day.pkl"])
                assert len(report) == 721
                boundaries = []
                for path in sorted((dest / "native-boundaries").glob("*.json")):
                    value = json.loads(path.read_bytes())
                    boundaries.extend(x["status"] for x in value["decisions"])
                assert boundaries and not any(x.startswith("HARD_STOP") for x in boundaries)
                receipt = dict(schema_version="hs300-eligibility-native-receipt/v1", identity=IDENTITY,
                    candidate_id="main-confirm2", run_binding_sha256=run_binding,
                    original_execution_configuration_prepared_hash=prepared.content_hash,
                    signal_sha256=digest(ROOT / "signal.pkl"), recorder_id=recorder.id,
                    run_status="SUCCEEDED", validation_verdict="NOT_EVALUATED", metrics=metrics,
                    boundary_statuses=sorted(set(boundaries)), files={
                        str(p.relative_to(dest)): digest(p) for p in sorted(dest.rglob("*"))
                        if p.is_file() and not p.is_relative_to(runtime)})
                save(dest / "receipt.json", receipt)
    return receipt


def summarize(cid, directory, receipt, signal, original_main, market, previous):
    import pandas as pd
    report = pd.read_parquet(io.BytesIO(read(directory / "portfolio.parquet", receipt["files"]["portfolio.parquet"])))
    orders = pd.read_parquet(io.BytesIO(read(directory / "native-orders.parquet", receipt["files"]["native-orders.parquet"])))
    positions = pickle.loads(read(directory / "positions_normal_1day.pkl", receipt["files"]["positions_normal_1day.pkl"]))
    assert len(report) == 721 and str(report.index[0].date()) == "2023-01-09" and str(report.index[-1].date()) == "2025-12-29"
    mask = signal["score"].unstack("instrument").notna()
    main_mask = original_main.notna()
    targets = {d: set(s.dropna().rename("score").rename_axis("instrument").reset_index().sort_values(
        ["score", "instrument"], ascending=[False, True], kind="mergesort").head(10).instrument)
        for d, s in signal["score"].unstack("instrument").iterrows()}
    details = []
    for o in orders.itertuples():
        dt = pd.Timestamp(o.datetime); sd = previous[dt]
        assert sd in mask.index
        if sd in positions:
            held = positions[sd].position
        else:
            assert dt == report.index[0]
            held = {}
        amount = float(held.get(o.instrument, {}).get("amount", 0))
        filled = abs(o.deal_amount) > 0
        buy = o.trade_dir == 1
        new_entry = buy and filled and amount == 0
        observable = new_entry and dt in main_mask.index
        short = observable and bool(market.loc[dt]) and not bool(main_mask.loc[dt, o.instrument])
        cat = "UNKNOWN"
        if not filled:
            cat = "UNFILLED"
        elif not buy and amount > 0:
            if not market.loc[sd]: cat = "MARKET_OFF"
            elif not mask.loc[sd, o.instrument]: cat = "ELIGIBILITY_EXIT"
            elif o.instrument not in targets[sd]: cat = "RANK_REPLACEMENT"
            else: cat = "WEIGHT_ADJUSTMENT"
        details.append(dict(datetime=dt, signal_date=sd, instrument=o.instrument, side="BUY" if buy else "SELL",
            category=cat, value=abs(float(o.trade_value)), fee=float(o.trade_cost),
            requested=abs(o.amount) > 0, unfilled=abs(o.amount) > 0 and not filled,
            partial=0 < abs(o.deal_amount) < abs(o.amount), new_entry=new_entry,
            observable_entry=observable, short_entry=short, right_censored=new_entry and not observable))
    details = pd.DataFrame(details)
    details.to_parquet(ROOT / (cid + "-classified-orders.parquet"), index=False)
    report["fee_cny"] = report.total_cost.diff().fillna(report.total_cost.iloc[0])
    def stats(part, od):
        t = float(part.turnover.mean()); x = float((part.value / part.account).mean())
        n = int(od.observable_entry.sum()); s = int(od.short_entry.sum())
        net = part["return"] - part.cost; wealth = (1 + net).cumprod()
        sells = od.loc[od.side.eq("SELL")]
        return dict(sessions=len(part), S_numerator=s, S_denominator=n, S=s / n if n else None,
            T=t, X=x, B=t / x if x else None, fees_cny=float(part.fee_cny.sum()),
            net_return=float(wealth.iloc[-1] - 1), max_drawdown=float((wealth / wealth.cummax().clip(lower=1) - 1).min()),
            order_count=int(od.requested.sum()), unfilled_order_count=int(od.unfilled.sum()),
            unfilled_order_rate=float(od.unfilled.sum() / od.requested.sum()) if od.requested.sum() else None,
            partial_fill_order_count=int(od.partial.sum()), right_censored_entries=int(od.right_censored.sum()),
            sell_amounts_cny={cat: float(sells.loc[sells.category.eq(cat), "value"].sum())
                for cat in ("MARKET_OFF", "ELIGIBILITY_EXIT", "RANK_REPLACEMENT", "WEIGHT_ADJUSTMENT", "UNKNOWN")},
            all_side_unknown_amount_cny=float(od.loc[od.category.eq("UNKNOWN"), "value"].sum()))
    result = dict(candidate_id=cid, total=stats(report, details), yearly={
        str(year): stats(part, details.loc[details.datetime.dt.year.eq(year)])
        for year, part in report.groupby(report.index.year)})
    save(ROOT / (cid + "-diagnostics.json"), result)
    return result


def worker():
    from quantos.infrastructure.hosted_storage import configured_guard
    from quantos.application.personal_server_config import make_trusted_service
    from quantos.contracts.hs300_adjusted import PreparedHS300AdjustedStudy
    from quantos.research.hs300_adjusted_runtime import verify_hs300_adjusted_binding
    from quantos.research.hs300_cash_runtime import load_reused_signals
    from quantos.artifacts.store import verify_file, regular_tree_files
    bind_authorization()
    guard = configured_guard(); guard.require_lease(); guard.require_root(ROOT)
    launch = json.loads(read(ROOT / "launch.json"))
    assert launch["implementation_sha256"] == digest(Path(__file__))
    prepared = PreparedHS300AdjustedStudy.model_validate_json(read(NEW / "prepared.json", NEW.name))
    config = REPO / "artifacts/personal-research-product-20261022/run-01/product/server-config.json"
    service = make_trusted_service(TASKS.parent, REPO, config_path=config)
    binding = service.catalog[prepared.dataset_manifest.dataset_id]
    assert binding.manifest == prepared.dataset_manifest
    verify_hs300_adjusted_binding(binding)
    observed = {str(p.relative_to(binding.provider_root)): p for p in regular_tree_files(binding.provider_root) if p.name != "manifest.json"}
    assert set(observed) == set(binding.manifest.qlib_files)
    for name, expected in binding.manifest.qlib_files.items():
        verify_file(observed[name], expected)
    signals = load_reused_signals(prepared, prepared.signal_reuse)
    rows = baseline_rows()
    signal, original_main, market, previous = signal_and_market(prepared, binding, signals)
    save(ROOT / "run-binding.json", dict(identity=IDENTITY, contract_sha256=CONTRACT_HASH,
        authorization_sha256=digest(ROOT / "authorization.json"), launch_sha256=digest(ROOT / "launch.json"),
        original_prepared_hash=prepared.content_hash, signal_sha256=digest(ROOT / "signal.pkl"),
        signal_receipt_sha256=digest(ROOT / "signal-receipt.json"), server_config_sha256=digest(config),
        runtime_source_hashes=binding.manifest.adjusted_runtime_source_hashes,
        reused_executor_helpers={str(p.relative_to(REPO)): digest(p) for p in (
            REPO / "src/quantos/research/personal_qlib.py",
            REPO / "src/quantos/research/qlib/workflow.py",
            REPO / "src/quantos/infrastructure/hosted_storage.py")},
        reused_dataset_manifest_hash=binding.manifest.content_hash, input_hashes=VERIFIED,
        limits=LIMITS, original_rows=rows, new_candidate="main-confirm2"))
    receipt = execute_native(prepared, binding, signal, digest(ROOT / "run-binding.json"))
    main_receipt = json.loads(read(NEW / "execution/main/receipt.json", rows[0]["receipt_sha256"]))
    main = summarize("main", NEW / "execution/main", main_receipt, signals["main"], original_main, market, previous)
    assert (main["total"]["S_numerator"], main["total"]["S_denominator"]) == (1088, 2340)
    successor = summarize("main-confirm2", ROOT / "main-confirm2", receipt, signal, original_main, market, previous)
    before, after = main["total"], successor["total"]
    reductions = {k: 1 - after[k] / before[k] if after[k] is not None and before[k] else None for k in ("S", "T", "B")}
    if any(v is None for v in reductions.values()): verdict = "INCONCLUSIVE"
    elif all(after[k] == before[k] for k in ("S", "T", "B")): verdict = "NO_INCREMENT"
    elif all(reductions[k] >= threshold for k, threshold in dict(S=.2, T=.1, B=.1).items()): verdict = "SUPPORTED_EXPLORATORY_ONLY"
    else: verdict = "NOT_SUPPORTED"
    rows[0]["diagnostics"] = main
    rows.append(dict(candidate_id="main-confirm2", identity=IDENTITY, receipt_sha256=digest(ROOT / "main-confirm2/receipt.json"),
                     run_status="SUCCEEDED", metrics=receipt["metrics"], diagnostics=successor))
    save(ROOT / "comparison.json", dict(identity=IDENTITY, planned_denominator=8, rows=rows,
        primary_comparison="main-confirm2 versus original main only", reductions=reductions,
        thresholds=dict(S=.2, T=.1, B=.1), exploration_verdict=verdict,
        validation_verdict="NOT_EVALUATED", independent_confirmation="NOT_ADMITTED",
        background_scope="ORIGINAL_TUPLES_NOT_SUCCESSOR_RANDOM_CONTROLS",
        S_eligibility="ORIGINAL_MAIN_E_NOT_SUCCESSOR_E2", yearly_assignment="EXECUTION_YEAR",
        unfilled_definition="requested native order with zero deal_amount; partial fills reported separately"))
    save(ROOT / "worker-exit.json", dict(status="SUCCEEDED", validation_verdict="NOT_EVALUATED",
        exploration_verdict=verdict, comparison_sha256=digest(ROOT / "comparison.json")))


def launch():
    from quantos.infrastructure.hosted_storage import StoragePolicy, StorageGuard, supervise_storage_job
    bind_authorization()
    pre = json.loads(read(ROOT / "resource-preflight.json"))
    pp = Path(pre["policy_path"])
    p = json.loads(read(pp, pre["policy_sha256"]))
    for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file"): p[key] = Path(p[key])
    guard = StorageGuard(StoragePolicy(**p))
    guard.require_root(ROOT)
    rows = baseline_rows()
    save(ROOT / "planned-comparison.json", dict(identity=IDENTITY, planned_denominator=8,
        rows=rows + [dict(candidate_id="main-confirm2", run_status="NOT_STARTED")]))
    command = ("/usr/bin/timeout", "--signal=TERM", "--kill-after=10", "900", sys.executable,
               "-B", str(Path(__file__).resolve()), "--worker")
    save(ROOT / "launch.json", dict(identity=IDENTITY, at=datetime.now(UTC), limits=LIMITS,
        implementation_sha256=digest(Path(__file__)), authorization_sha256=digest(ROOT / "authorization.json"),
        policy_sha256=digest(pp), python_path=sys.executable, python_sha256=digest(Path(sys.executable).resolve()),
        timeout_sha256=digest(Path("/usr/bin/timeout")), argv=command,
        resources=guard.check(536870912), dependencies_changed="new eligibility filter and account path only"))
    start = time.monotonic()
    try:
        run = supervise_storage_job(guard, command, stage="matrix", expected_new_bytes=536870912)
        save(ROOT / "supervisor-exit.json", dict(status="SUCCEEDED", storage_run=str(run),
            actual_exit=json.loads((run / "exit.json").read_bytes()), actual_exit_sha256=digest(run / "exit.json"),
            wall_seconds=time.monotonic() - start))
    except Exception as error:
        owner = json.loads((guard.policy.evidence_root / "storage-control/lease.lock").read_bytes())
        run = Path(owner["run"])
        save(ROOT / "supervisor-failure.json", dict(status="FAILED", validation_verdict="NOT_EVALUATED",
            error_type=type(error).__name__, storage_run=str(run),
            actual_exit=json.loads((run / "exit.json").read_bytes()) if (run / "exit.json").is_file() else None,
            wall_seconds=time.monotonic() - start))
        raise


if __name__ == "__main__":
    try:
        worker() if sys.argv[1:] == ["--worker"] else launch()
    except Exception as error:
        path = ROOT / ("worker-failure.json" if sys.argv[1:] == ["--worker"] else "caller-failure.json")
        if not path.exists():
            save(path, dict(identity=IDENTITY, status="REJECTED" if getattr(error, "reason_code", None) == "PIT_HARD_REJECTION" else "FAILED",
                validation_verdict="NOT_EVALUATED", error_type=type(error).__name__,
                reason_code=getattr(error, "reason_code", "EXECUTION_ERROR"),
                frames=[dict(file=x.filename, line=x.lineno, function=x.name) for x in traceback.extract_tb(error.__traceback__)],
                native_started=(ROOT / "native-start.json").exists(), retries=0))
        if not (ROOT / "comparison.json").exists() and (ROOT / "planned-comparison.json").exists():
            failed = json.loads((ROOT / "planned-comparison.json").read_bytes())
            failed["rows"][-1].update(run_status="REJECTED" if getattr(error, "reason_code", None) == "PIT_HARD_REJECTION" else "FAILED",
                                      failure_receipt=str(path), metrics=None)
            failed.update(exploration_verdict="INCONCLUSIVE", validation_verdict="NOT_EVALUATED")
            save(ROOT / "comparison.json", failed)
        raise SystemExit(1)
