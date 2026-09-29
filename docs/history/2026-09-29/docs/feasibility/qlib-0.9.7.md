# Qlib 0.9.7 feasibility record

Status: **PASS with explicit limitations**

Status date: 2026-09-06. This record covers the Qlib component qualification and the decisions it
forced. Overall first-stage release status is maintained in
[`docs/implementation-status.md`](../implementation-status.md).

Validated environment:

- Python 3.11.15
- pyqlib 0.9.7
- Qlib source tag `v0.9.7`, commit `da920b7f954f48ab1bb64117c976710de198373e`
- pandas 2.3.3, NumPy 2.4.6, LightGBM 4.7.0, MLflow 3.15.2

The executable spike is [`scripts/qlib_feasibility.py`](../../scripts/qlib_feasibility.py).
It uses generated synthetic data and performs no network calls. The Qlib source cache is prepared
separately by [`scripts/bootstrap_qlib_tools.py`](../../scripts/bootstrap_qlib_tools.py).

## Evidence

| Check | Result |
|---|---|
| Official `dump_bin.py`, two clean builds | PASS; 42 output files and identical per-file hashes |
| Official `check_data_health.py` | PASS; exit code 0 |
| Qlib expression query | PASS; 17 rows for `$close` and `Ref($close, 1)` |
| Qlib tiny reference backtest | PASS; 15 report rows, position snapshots, and indicator rows |
| Qlib local MLflow recorder | PASS with explicit opt-in |
| Native Qlib ML chain | `DatasetH` → `LGBModel` → `SignalRecord` → `SigAnaRecord` PASS |
| `SigAnaRecord` exported metrics | Finite long-average and LightGBM loss metrics; undefined metrics explicitly omitted |
| Recorder deletion after export | PASS; prediction and metric hashes remain verifiable |
| Canonical snapshot → official converter view | PASS; all nine endpoint-shaped fixtures feed the P2 snapshot |
| Independent canonical view rebuild | PASS; identical view hash and semantic `$close` sample |
| Complete SignalArtifact → BacktestArtifact | PASS; real Qlib execution and identical result hash on two runs |

The audited exports, read only after Qlib's async logger flushes, are:

```text
predictions.csv  a57fc7297e6365cf9186c0063c0d4c4f7ca3f643d52a8a6507cc2b49c016739a
metrics.json      089f93946c959f4984888ba78df2c8966d3a53d5070d78ea0397b40b2cca40c8
```

Both exports were reproduced in two independent runs. The one-session forward label reserves
2024-01-12 and 2024-01-18 as explicit purge sessions between train/validation/test. The tiny
synthetic model emits constant test scores, so IC, ICIR, Rank IC, Rank ICIR, and the two long-short
metrics are non-finite. They are named in `omitted_nonfinite_metric_names`, excluded from canonical
JSON, and never coerced to zero. The nine prediction rows and finite long-average/LightGBM loss
metrics remain verifiable after the disposable MLflow runtime is deleted.

Runtime reports remain under ignored `artifacts/feasibility/` and include their Qlib run ID.

The historical synthetic P2/P3 repair slice produced snapshot hash
`e5c43df461eec6fde43994ef27b740410ce74e16c7c0ca78aba84440a5196de0` and quality-report hash
`e89da0a87dff72752266e53511eda2f11f6e17e6beaf725b1c27c6682788f70b`. The earlier view hash is
superseded because the view contract now binds both official script hashes, includes historical
universe/tradability sidecars, represents suspensions as NaN OHLCV, and enforces exact manifested
file sets. Two independent real official-converter builds produced the resulting view hash
`063e04060342e81bbaadf9f878af3b37ce81c79e03cef0ccf46554b7f0256138`; all three stock/benchmark
`$close` samples and the official health check passed. These are synthetic engineering facts, not
live Tushare release evidence.

The P4 signal feasibility runner is
[`scripts/signal_feasibility.py`](../../scripts/signal_feasibility.py). From a clean temporary Git
checkout it executed the translated one-day momentum expression through Qlib against the verified
view and independently published the same content-addressed result twice on synthetic feasibility
commit `272eafb0b175b1f7a6c6f883e8cee68097c2253c`:

```text
SignalArtifact       93b565b1e61782909e99dba628ed6386ed5be298cdd0c927fcc86585b8ee8521
signal content       31b8cc11c9b5f86fb62e2f3a6f7984e721a12ae2ffec597fdf4157d69a36b85b
PIT evidence bundle  d53388be921ea723f4744091ce859385972b8f145492fa6ad840ba4c14709103
rows                 1
```

Every signal member has an exact canonical request/report pair. The report binds its expression,
snapshot, instrument, universe, and complete decision schedule. The SignalArtifact additionally
binds the clean Git commit, `uv.lock`, Qlib view/spec, translation, lineage, schema, semantic signal
hash, and all file hashes. A dirty or non-Git workspace correctly fails this provenance gate; the
cited temporary checkout is synthetic component evidence, not release provenance.

The P5 end-to-end runner is
[`scripts/backtest_feasibility.py`](../../scripts/backtest_feasibility.py). Its dedicated fixture
extends the calendar through the Friday signal, Monday next-open execution, and Tuesday closeout
session. On clean synthetic feasibility commit
`272eafb0b175b1f7a6c6f883e8cee68097c2253c`, it built and verified the complete chain twice:

```text
SnapshotArtifact      2698fdcee8d153dab005050f451b5c8cae0b11d60bd23d20ced3605785858ec4
Qlib view             b6a5220a97a6e568d9eec1e4b2fb18b928d81c1c9a777ac5893c89c44ee0bb36
PIT evidence          a0cf72099da00f993f88005975ad96fa823f6ab4909a13d40c2c6651372d83e3
SignalArtifact        1e59ee430ff69a0cfad39eca41cc95e30c49693491cfe977f8a3036eb868da8a
BacktestArtifact      0ef5a3659c4edd7b978348892589b97e71eb7af9468dd9014c4cb0703264673f
backtest config       19865770669f1684709e6d5dad3444e6aeb447c26a6d6039d5ef728c9a23dab7
reconciliation        3f442b1cdc30f87cdbee112d585ecdaee2b49833edd34e8e79e933497792d69e
```

The service used real `WeightStrategyBase`, explicitly supplied `OrderGenWOInteract`, Qlib
`Exchange`, `SimulatorExecutor`, and `Position`; it did not implement matching, orders, or portfolio
accounting. The BacktestArtifact contains one portfolio row, one position row, one aggregate trade
indicator row, one order row, and ten Qlib risk rows. Asset identity, nonnegative cash, position
value/weight, return-cost-turnover deltas, temporal schedule, and BUY-trade-unit/no-short/bound-code
checks all passed with zero maximum arithmetic error. Sell-all orders retain Qlib's required ability
to liquidate corporate-action odd lots. A separate 12-session constraint run also
passed normal-order, non-rebalance, limit-buy, ST, suspension, minimum-commission, and 100-share-lot
golden cases.

## Decisions forced by the spike

1. The pyqlib wheel omits `scripts/dump_bin.py` and `scripts/check_data_health.py`. P2 must use the
   exact verified official source cache; it must not implement a binary writer.
2. MLflow 3.15 places its filesystem backend in maintenance mode. Qlib's local recorder requires
   the process-scoped `MLFLOW_ALLOW_FILE_STORE=true` opt-in. It remains disposable runtime state;
   immutable exports are authoritative.
3. `TopkDropoutStrategy` is dropout/replacement semantics, not weekly full top-50 equal-weight
   replacement. P5 therefore uses a minimal `WeightStrategyBase` subclass that returns target
   weights only; Qlib still owns order generation and execution.
4. Qlib exposes requested/dealt amounts and fulfillment indicators, but no stable per-order
   rejection reason-code field. P5 normalizes available evidence and reports this limitation;
   it will not create an order engine.
5. Qlib imports legacy `gym` 0.26.2, which emits an upstream NumPy 2.x maintenance warning. The
   tested research/backtest path passed; RL modules remain out of scope.

## First-stage environment qualifications

- The first-stage implementation was frozen at
  `f3fc7684d09ac351d72d76b2a0370c58bec8589c`. Canonical Offline Engineering and Data-qualified
  double-runs both completed from that explicit code binding; later documentation commits do not
  change the runtime evidence.
- The token was supplied only to the 2026-09-05 acquisition process through the environment. This
  document makes no claim about whether it is currently configured. The bounded probe confirmed
  all 12/12 probed endpoints, including `index_weight` and `stock_st`; all 13,614 snapshot requests
  completed on the first attempt under the explicit 200 requests/minute policy. Live snapshot
  `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` passed 16/16 DQ gates.
- The local `.tools/qlib-0.9.7` cache used for qualification was verified at the locked commit with
  a clean tracked tree and matching official script blobs. Live derived view
  `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` passed the official health
  check and 668/668 exact binary32 readback samples.
- The resulting Data-qualified release is engineering `PASS`; its ValidationReport is
  `SUCCEEDED / REJECT` and Registry strategy state is `REJECTED`. This research rejection does not
  alter the Qlib component `PASS` recorded here.
