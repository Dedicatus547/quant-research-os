# Repository rules

1. Do not implement a custom backtest, exchange, order, or portfolio accounting engine.
2. Tushare may only be called by the snapshot acquisition layer. All later stages are offline.
3. Never commit, persist, print, or log `TUSHARE_TOKEN`.
4. Reuse Qlib `dump_bin`, data-health checks, Workflow, Record Templates, `DatasetH`, `LGBModel`,
   Exchange, and Simulator before adding project code.
5. `quantos.contracts` must not depend on Tushare, Qlib, an Agent harness, or an LLM SDK.
6. No LLM call is allowed in normalization, PIT validation, factor/model execution, backtest,
   or validation gates.
7. Agent output is a proposal, never validated evidence.
8. Canonical runs bind explicit hashes and never use `latest`, `current`, `auto`, or mutable data.
9. PIT failure is a hard rejection; execution failure is `FAILED / NOT_EVALUATED`.
10. Qlib `.bin` is a derived cache. Canonical data is the immutable Parquet snapshot.
11. MLflow is a Qlib runtime recorder only. Exported immutable artifacts and hashes are authority.
12. Data revisions create new snapshots and never overwrite old snapshots.
13. Profitability is not an engineering acceptance criterion.
14. Rejected and failed experiments remain immutable evidence.
15. Do not claim historical vendor-vintage PIT when the source does not provide vintages.
