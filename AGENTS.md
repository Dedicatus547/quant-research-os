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

## Implementation and recovery rules — effective 2026-10-10

Read [implementation discipline](docs/guides/implementation-discipline.md) before subsequent
implementation or recovery work. Its background is the
[HM-MVP retrospective](docs/hosted/hm-mvp-implementation-retrospective.md).

16. Reuse completed immutable artifacts and proofs whenever their actual dependencies and origins
    are verifiable. Before a heavy rerun, explain the changed/missing dependency, affected conclusion,
    and minimal required work. A new overall commit alone does not justify rerunning everything.
17. Do not add unnecessary development gates or tests. Add or run tests only when the user explicitly
    requests testing or implementation verification. Keep authorized verification proportional to
    the change; preserve frozen scientific and safety predicates.
18. Keep authoritative evidence, failures, exits, receipts and checkpoints in durable storage from
    the start, never solely in `/tmp`, `/var/tmp` or auto-cleaned caches. Persist independent completed
    steps promptly; resume unfinished work without rewriting failed parent runs or inventing exits.
19. Before heavy work, account for the actual host volume, complete job growth, all concurrent
    reservations and safe cleanup/evidence space. Reuse existing quotas and guards; never equate
    WSL free space with host-volume capacity or delete unique evidence to make room.
20. Verify critical external interfaces early within existing authorization and available budget.
    Development probes do not grant qualification. Measure existing costly stages before optimizing;
    avoid duplicate full verification and repeated large-file parsing.
21. Parallelize independent work when dependencies, isolated outputs and shared CPU/memory/storage
    budgets permit. Keep shared authority writes and crash/recovery chains ordered. Sub-agent use
    remains subject to the active task's authorization and higher-priority instructions.
22. Reuse existing user authorization and preferences within scope; do not repeatedly request the
    same approval. New expenditure, disclosure or irreversible scope still requires valid authority.
23. Keep current status and handoffs short and link retained history. Separate engineering acceptance,
    scientific outcomes and agent proposals. New rules do not retroactively change frozen contracts,
    historical proofs or accepted source identities.

The original 15-rule file used by HM02 is retained byte-for-byte at
[the historical rules](docs/history/2026-10-10/AGENTS.md): 1335 bytes, SHA256
`a0b0cbbc4ab9615e933b6ceca391b2d6dfaeecfdc9323a6ea561119c9fa114c7`.
This successor instruction does not alter that historical review input.
