# First-stage implementation status

Status date: 2026-09-03

Offline Engineering and Data-qualified evidence are deliberately reported separately. A synthetic
or injected-client pass never qualifies a live-data release.

| Phase | Offline Engineering | Data-qualified / remaining work |
|---|---|---|
| P0 | Python 3.11/uv lock, CI gates, doctor, bounded 12-request capability probe with immutable redacted evidence, locked Qlib source verification, and clean-checkout Git fingerprinting PASS | Live probe hard-rejected `index_weight` as `PERMISSION_DENIED` |
| P1 | Deterministic contracts/hashes, temporal types, refs, reason codes, immutable events, strict YAML loading, two-layer authoring/resolved experiment contracts, and separate engineering/research validation policies PASS | No live dependency |
| P2 | All 9 endpoint-shaped fixtures; raw/canonical Parquet; lifecycle, bounded membership and sparse-status rules; content-addressed snapshot; exact file-set verification; resumable endpoint plans using `pyrate-limiter`/`tenacity`; redacted request ledgers; injected-client live-shaped publication; official Qlib view with historical-universe/tradability sidecars and two independent identical builds PASS | Obtain `index_weight` permission, set an account-qualified rate policy, acquire the immutable Tushare snapshot, and rebuild its derived view |
| P3 | Canonical request selectors are bound to a verified snapshot hash; temporal lineage is loaded mechanically from Parquet; complete operator-delay policies, source windows, input lag, membership as-of, fake-hash rejection, and unbound-proposal publication denial PASS. Reports now bind the exact canonical request, expression, selectors, and decision schedule | Re-run the PIT audit against the live snapshot; every report retains `SINGLE_SOURCE_NON_VINTAGE` |
| P4 | Safe-expression translation to official Qlib syntax, historical-universe resolution, cross-section PIT evidence bundles, provenance-gated immutable SignalArtifact publication/verification, locked cost/research policies, and real `DatasetH`/`LGBModel`/Workflow/Record Template smoke PASS. Two independent real-Qlib synthetic signal builds and two purged ML runs reproduced their content hashes | Re-run the complete P4 path on the live snapshot in a normal clean Git checkout; synthetic evidence is not data qualification |
| P5 | Verified SignalArtifact-to-Qlib reference backtest, explicit Exchange/Simulator/Position/order-generator configuration, content-addressed BacktestArtifact, six arithmetic/schedule reconciliations, constraint golden cases, CLI run/verify, and clean-checkout double-run PASS | Re-run against the live snapshot in a normal release checkout; Qlib 0.9.7 blocked-trade evidence limitations remain explicit |
| P6 | G0-G10 deterministic validation, hard-gate short circuit, frozen OOS access events, complete cost/parameter/subperiod evidence grids, policy-driven soft thresholds, independent-output-root reproducibility comparison, runtime-bound immutable ValidationReport v2, four golden outcomes, and native-Qlib full-pipeline synthetic double-run PASS | Rank IC/ICIR remain disabled and fail closed until an immutable Qlib ResearchResult adapter exists; re-run against the live snapshot in a normal clean Git checkout and retain the Data-qualified release-baseline rerun |
| P7 | Self-hashed experiment manifests, imported OOS event chains, append-only strategy lifecycle, monotonic versions, rebuildable indexes, single-writer atomic publication, CLI, tamper/partial/duplicate/transition gates, and native-Qlib synthetic Release E2E double-run PASS | Re-run the final release path against the live snapshot after all Data-qualified blockers are cleared |

## 轨道对齐与下一阶段入口

当前目标分为三条独立轨道：

- `Deterministic MVP v0.1`：P0-P7 Offline Engineering DoD 已完成。正式发布前仍需将当前改动
  合入 Git clean commit，并从该 commit 重跑一次 release feasibility，作为仓库级基线。
- `Data-qualified Release`：独立等待真实 Tushare 权限、quota/rate policy、2015-2025 snapshot
  及其 P3-P7 重跑；当前因 `index_weight: PERMISSION_DENIED` 保持 hard-blocked。
- `Agent-assisted Research v0.2`：在 Offline Engineering 基线冻结后启动 P8-P11，不等待
  Data-qualified 权限；Agent 只生成 proposal、请求确定性执行和解释 ValidationReport。

后续顺序固定为：

```text
M0 基线冻结 → P8 Pre-MCP Threat Hardening → P9 Harness Capability Spike
→ P10 单一 Harness + MCP Research API → P11 Harness Integration
```

P8-P11 不得引入自有回测/交易/组合引擎，也不得让 Agent 读取 token、修改快照、覆盖 artifact、
修改 Gate verdict 或直接标记 `VALIDATED`。P9 必须用固定版本和统一 rubric 选择一个主 harness；
P10-P11 的验收对象是相同 resolved Spec 与冻结输入的确定性证据，而不是 Agent 文本的逐字一致。

## P2-P4 baseline offline evidence

```text
Synthetic snapshot  e5c43df461eec6fde43994ef27b740410ce74e16c7c0ca78aba84440a5196de0
Quality report      e89da0a87dff72752266e53511eda2f11f6e17e6beaf725b1c27c6682788f70b
Qlib source commit  da920b7f954f48ab1bb64117c976710de198373e
Qlib derived view   063e04060342e81bbaadf9f878af3b37ce81c79e03cef0ccf46554b7f0256138
Signal artifact     93b565b1e61782909e99dba628ed6386ed5be298cdd0c927fcc86585b8ee8521
Signal content      31b8cc11c9b5f86fb62e2f3a6f7984e721a12ae2ffec597fdf4157d69a36b85b
PIT evidence bundle d53388be921ea723f4744091ce859385972b8f145492fa6ad840ba4c14709103
LGB predictions     a57fc7297e6365cf9186c0063c0d4c4f7ca3f643d52a8a6507cc2b49c016739a
LGB finite metrics  089f93946c959f4984888ba78df2c8966d3a53d5070d78ea0397b40b2cca40c8
Quality suite       151 passed; Ruff PASS; Pyright 0 errors; branch coverage 85.05%
```

The P4 SignalArtifact above was regenerated after the P5 policy fields were frozen. It and the P5
evidence below bind clean synthetic feasibility commit
`272eafb0b175b1f7a6c6f883e8cee68097c2253c`; that temporary checkout is component evidence, not
release provenance for this non-Git workspace.

## P5 complete offline backtest evidence

```text
P5 snapshot          2698fdcee8d153dab005050f451b5c8cae0b11d60bd23d20ced3605785858ec4
P5 quality report    5e442119d10636080c216d4ad81378a21583a6847106c6c7af207904bc3b283a
P5 Qlib view         b6a5220a97a6e568d9eec1e4b2fb18b928d81c1c9a777ac5893c89c44ee0bb36
P5 PIT evidence      a0cf72099da00f993f88005975ad96fa823f6ab4909a13d40c2c6651372d83e3
P5 SignalArtifact    1e59ee430ff69a0cfad39eca41cc95e30c49693491cfe977f8a3036eb868da8a
P5 BacktestArtifact  0ef5a3659c4edd7b978348892589b97e71eb7af9468dd9014c4cb0703264673f
Backtest config      19865770669f1684709e6d5dad3444e6aeb447c26a6d6039d5ef728c9a23dab7
Reconciliation       3f442b1cdc30f87cdbee112d585ecdaee2b49833edd34e8e79e933497792d69e
```

The Qlib view format binds the SHA-256 of both official scripts, requires a clean locked source
tree, emits historical-universe and tradability sidecars, and rejects unmanifested files. The view
hash above was reproduced in two independent directories using the real official converter and
health check. It remains synthetic engineering evidence, not live-data release evidence.

The SignalArtifact evidence was produced twice in separate output roots from a clean temporary Git
checkout. Qlib executed the safe expression; the artifact embeds the resolved experiment,
expression translation, complete member-by-member PIT evidence, and canonical Parquet signals.
Its verifier rejects extra or changed files, schema drift, temporal mismatch, missing member
evidence, non-finite/incomplete Qlib output, and mismatched snapshot/view/code/lock bindings.
Manifest creation timestamps are outer metadata and do not enter the content-hash domain.

The dedicated P5 fixture adds the session after the weekly signal, the next-open execution session,
and one closeout calendar session without changing the P2-P4 baseline fixture. The executable
[`backtest_feasibility.py`](../scripts/backtest_feasibility.py) runs the full verified artifact
chain with Qlib's real `WeightStrategyBase`, explicit `OrderGenWOInteract`, `Exchange`,
`SimulatorExecutor`, and `Position`. Two complete executions produced the same BacktestArtifact.
Its one portfolio row, one position row, one aggregate trade-indicator row, one order-indicator row,
and ten Qlib risk rows all pass the six reconciliations with zero maximum arithmetic error.

The separate multi-session constraint golden backtest fixes normal execution, no orders on
non-rebalance dates, limit-buy/ST/suspension blocking, raw 100-share lots, minimum commission, and
all six reconciliations. Qlib's conservative target-weight precheck and lack of stable per-order
rejection reason codes remain recorded limitations; no substitute order or accounting engine was
added.

The native ML smoke uses `DatasetH`, `LGBModel`, `SignalRecord`, and `SigAnaRecord`. A one-session
forward label has explicit purged boundary sessions between train/validation/test. Only finite
metrics are exported; undefined IC/long-short metrics are named as omitted and are never coerced.

## P6 validation evidence

```text
P6 component commit     54ee26fb029f024150cbafa252aa46bc18ef87f7
Runtime fingerprint     66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
Snapshot                2698fdcee8d153dab005050f451b5c8cae0b11d60bd23d20ced3605785858ec4
Qlib view               b6a5220a97a6e568d9eec1e4b2fb18b928d81c1c9a777ac5893c89c44ee0bb36
Baseline SignalArtifact 61ce5abebeac4b905adda70839566f8dbf5d3ebea93dffb5eef5e8254280c1b3
Baseline Backtest       bca07520b3014cf9794cbc1e52bc3335dcd91018d5f971f4481913f894d44864
ValidationReport v2     28e41a0c4b491990d7647cb22bacaab064a2441328f2bc8f9ce74961e3aeb813
Robustness cases        8
Independent pipelines  2; principal hashes byte-exact
```

The compact retained summary is
[`artifacts/feasibility/validation-p6/report.json`](../artifacts/feasibility/validation-p6/report.json).
The full component artifacts were generated under temporary output roots and are not represented
as release provenance or Data-qualified evidence.

The validation layer consumes Qlib-produced artifacts and does not implement another backtest,
exchange, order, or portfolio-accounting engine. Production `quantos experiment run` validates an
explicit, already-published evidence grid; it does not hide upstream generation behind locator
resolution. G0-G10 reopen every content-addressed input, and runtime locator YAML cannot assert
PASS. Cost stress requires the complete 1.0x/1.5x/2.0x grid, parameter stability requires the
policy Cartesian grid, and subperiod analysis requires every frozen interval and its minimum
observation count. OOS metrics reuse Qlib risk analysis; turnover uses the explicitly versioned
annualization factor.

The executable [`validation_feasibility.py`](../scripts/validation_feasibility.py) runs two complete
pipelines from a clean temporary Git checkout. Each run rebuilds the synthetic snapshot and view
with Qlib's locked official converter/health check, executes snapshot-bound PIT and Qlib factor
expressions, runs Qlib reference backtests for all cost/parameter/subperiod cases, performs an
independent baseline reproduction, and publishes a G0-G10 report. The two runs must reproduce the
snapshot, view, baseline signal, baseline backtest, and ValidationReport content hashes exactly.
The fast CI E2E retains controlled adapter doubles to fix failure semantics without downloading
the official Qlib source.

ValidationReport v2 includes an immutable runtime fingerprint for Python, implementation,
OS/kernel, architecture, libc, and the exact versions of the critical numeric/runtime packages.
Contract and golden tests separately fix normal PASS, soft-threshold REJECT, PIT hard REJECT, and
execution `FAILED / NOT_EVALUATED`. Policy, runtime fingerprint, or report tampering is rejected.
Every report discloses `SINGLE_SOURCE_NON_VINTAGE`; synthetic evidence is still not Data-qualified
evidence.

Rank IC/ICIR are intentionally not claimed by the factor validation path. The Qlib Workflow smoke
proves those upstream metrics can be produced, but no immutable ResearchResult adapter currently
binds them into G3. A policy requesting either metric is rejected as `SOURCE_INCOMPLETE`; neither
shipped v0.1 validation policy enables them.

Runtime timestamps and OOS event references are retained but excluded from their documented
content-hash domains. Every referenced payload is individually hashed, and verifiers reject
missing, changed, or additional files.

## P7 registry and release evidence

```text
P7 component commit      bac2356bcf2d23744e27de928f8d1702d7ff7760
Runtime fingerprint      66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
Snapshot                 2698fdcee8d153dab005050f451b5c8cae0b11d60bd23d20ced3605785858ec4
Qlib view                b6a5220a97a6e568d9eec1e4b2fb18b928d81c1c9a777ac5893c89c44ee0bb36
SignalArtifact           be1c09cfbbfd0cb88bc4b9dd20f49db4ca236ca82792c8c4a7c214bab6f069c5
BacktestArtifact         ce13f2146c2ef3e37d049c6a7bee46f7c4fda465c24ce87727dacc70920908c9
ValidationReport v2      9fab806f7ff638fd3c6b7ba1afe104139b49cbc66ed95e436175bb56028afe83
Experiment manifest      d7ba614941a48792ac0769c7e14686d4408ab6d664aaeda37a7f119d3bfd1ba4
Registry index           9ab2ebe79a7334c3db9c9751316f5f4fbf1c6d3d79588f73124910f5523d0005
Final strategy status    VALIDATED
Independent pipelines   2; all principal hashes byte-exact
Release track            OFFLINE_ENGINEERING; SYNTHETIC_FIXTURE; data_qualified=false
```

The retained compact result is
[`artifacts/feasibility/release-p7/report.json`](../artifacts/feasibility/release-p7/report.json).
The runner uses Qlib's locked official converter/health check, expression provider, Exchange and
Simulator; registry code only verifies and indexes the published P6 evidence. Experiment manifests
bind code/lock/runtime, policies, snapshot/view, signal, backtest, ValidationReport, optional Qlib
run ID, limitations, and the imported OOS event. Registry indexes exclude wall-clock generation
time from their content domain and reproduce exactly from immutable authority files.

The experiment and strategy event chains reject missing predecessors, forks, backward timestamps,
invalid payloads and state transitions. REJECT and FAILED / NOT_EVALUATED reports remain registered
evidence, while only canonical SUCCEEDED / PASS can produce a VALIDATED strategy version. This is
synthetic component evidence, not live Tushare qualification.

## Deliberate reuse boundaries

- Tushare's official SDK is the only network client and is reachable only through acquisition.
- `pyrate-limiter` and `tenacity` supply rate limiting and bounded retries; project code only owns
  endpoint plans, checkpoints, schema/duplicate checks, and redacted ledgers.
- PyArrow/Parquet is the canonical local data layer.
- Qlib's official converter, health check, expression engine, recorder, model, exchange, and
  simulator are reused.
- MLflow filesystem state remains a disposable Qlib runtime recorder; exported immutable
  artifacts are authoritative.
- No generic provider framework, custom `.bin` writer, factor engine, experiment manager,
  matching engine, or portfolio accounting engine was added.
