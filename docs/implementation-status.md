# Implementation status

Status date: 2026-09-08

Offline Engineering and Data-qualified evidence are deliberately reported separately. A synthetic
or injected-client pass never qualifies a live-data release.

Paths under `../artifacts/` normally point to workspace-local immutable evidence and are not
distributed through Git. The synthetic P7 and P11 summary reports are explicit non-licensed
exceptions; full live-data hashes remain usable when their artifacts are available in an authorized
workspace.

| Phase | Offline Engineering | Data-qualified result |
|---|---|---|
| P0 | Python 3.11/uv lock, CI gates, doctor, bounded 12-request capability probe with immutable redacted evidence, locked Qlib source verification, and clean-checkout Git fingerprinting PASS | The 2026-09-05 live probe confirmed all 12/12 probed endpoints are available; the account-qualified acquisition policy is fixed at the verified official 200 requests/minute tier |
| P1 | Deterministic contracts/hashes, temporal types, refs, reason codes, immutable events, strict YAML loading, two-layer authoring/resolved experiment contracts, and separate engineering/research validation policies PASS | No live dependency |
| P2 | All 9 endpoint-shaped fixtures; raw/canonical Parquet; lifecycle, availability-aware bounded membership and sparse-status rules; content-addressed snapshot; exact file-set verification; resumable endpoint plans using a shared `pyrate-limiter`/`tenacity`; redacted request ledgers; injected-client live-shaped publication; scalable Arrow/PyArrow PIT, Signal and Qlib-view paths; official Qlib view with historical-universe/tradability sidecars and two independent identical builds PASS | Live acquisition completed 13,614/13,614 requests on the first attempt. The immutable snapshot passed 16/16 DQ gates; its official Qlib 0.9.7 view passed health checks, exact-file verification, and 668/668 binary32-aware semantic samples. P2 live qualification is complete |
| P3 | Canonical request selectors are bound to a verified snapshot hash; temporal lineage is loaded mechanically from Parquet; complete operator-delay policies, source windows, input lag, membership as-of, fake-hash rejection, and unbound-proposal publication denial PASS. Reports now bind the exact canonical request, expression, selectors, and decision schedule | Live PIT audit completed and retained `SINGLE_SOURCE_NON_VINTAGE`; evidence bundle `17f3a368...a71f` |
| P4 | Safe-expression translation to official Qlib syntax, historical-universe resolution, cross-section PIT evidence bundles, provenance-gated immutable SignalArtifact publication/verification, locked cost/research policies, and real `DatasetH`/`LGBModel`/Workflow/Record Template smoke PASS. Two independent real-Qlib synthetic signal builds and two purged ML runs reproduced their content hashes | Two independent live-data pipelines reproduced SignalArtifact `dba57f2a...e51e`; Rank IC/ICIR remain disabled and fail closed until an immutable ResearchResult adapter exists |
| P5 | Verified SignalArtifact-to-Qlib reference backtest, explicit Exchange/Simulator/Position/order-generator configuration, content-addressed BacktestArtifact, six arithmetic/schedule reconciliations, constraint golden cases, CLI run/verify, and clean-checkout double-run PASS | Two independent live-data pipelines reproduced BacktestArtifact `ec318505...4270` and reconciliation `c01cd819...0d1`; Qlib 0.9.7 blocked-trade evidence limitations remain explicit |
| P6 | G0-G10 deterministic validation, hard-gate short circuit, frozen OOS access events, complete cost/parameter/subperiod evidence grids, policy-driven soft thresholds, independent-output-root reproducibility comparison, runtime-bound immutable ValidationReport v2, four golden outcomes, and native-Qlib full-pipeline synthetic double-run PASS | Live Validation E2E completed: `SUCCEEDED / REJECT`; G0-G4 and G6-G10 PASS, while G5 soft-rejected annualized turnover `29.5344 > 12` |
| P7 | Self-hashed experiment manifests, imported OOS event chains, append-only strategy lifecycle, monotonic versions, rebuildable indexes, single-writer atomic publication, CLI, tamper/partial/duplicate/transition gates, and native-Qlib synthetic Release E2E double-run PASS | Live Registry/release double-run completed; engineering release `PASS / data_qualified=true`, rejected strategy immutably retained as `REJECTED` |
| P8 | Capability allowlist, bounded/secret-free JSON ingress, payload-free audit decisions, minimal Agent environment, hash-only root-confined authority resolution, symlink/special-file rejection across authority artifacts, atomic create-if-absent, and serialized Registry writers PASS. Full P0-P7 regression remains green | No live-data dependency; no Agent/LLM output is treated as evidence |
| P9 | Harness-independent Evidence/proposal/admission/AgentRun/Ledger contracts; finite-family and budget contracts; append-only campaign/OOS governance with complete attempt accounting and contamination propagation; Safe Qlib DSL v2 with five individually admitted official operators PASS. Full P0-P8 regression remains green | No live-data or Agent-runtime dependency; unknown-availability or unadmitted event labels cannot become executable features |
| P10 | Frozen `gpt-5.6-sol` + `codex-cli 0.153.4` synthetic spike: thread, read-only sandbox, single allowlisted MCP tool, repo Skill, failure recovery, bounded JSONL transcript, usage, permission denial, and exact proposal boundary all PASS (9/9), yielding Go. Spec/report/manifest/transcript are atomically retained by hash | No market-data dependency; output remains `AGENT_PROPOSAL`, model identifier is explicitly non-immutable, and P10 authorizes only the narrow P11 integration boundary |
| P11 | Three validated repo Skills; typed proposal/compiler plus dataset/resolve/execution/job/validation/registry mappings; immutable receipts/audit events; bounded durable queue with duplicate/cancel/timeout/restart/failure gates; clean-commit frozen structured-Evidence proposal E2E through two native-Qlib release pipelines PASS with exact authority hashes | Synthetic-only `data_qualified=false`; Agent and reviewer outputs remain proposals and never mutate ValidationReport or Registry verdicts |

## 轨道对齐与下一阶段入口

当前目标分为三条独立轨道：

- `Deterministic MVP v0.1`：P0-P7 Offline Engineering DoD 已完成，并已在实现提交
  `f3fc7684d09ac351d72d76b2a0370c58bec8589c` 上执行两条独立正式流水线；结果为
  `PASS / VALIDATED`。
- `Data-qualified Release`：DQ-01 至 DQ-06 已全部完成。工程发布为
  `PASS / data_qualified=true`；真实 HS300 Momentum 候选的研究 verdict 为
  `SUCCEEDED / REJECT`，Registry 状态为 `REJECTED`。
- `Agent-assisted Research v0.2`：P8-P11 已完成，P12-P14 继续基于已冻结的第一阶段基线实施；
  Agent 只生成 proposal、请求确定性执行和解释 ValidationReport。

后续顺序固定为：

```text
M0 基线冻结 → P8 Agent Boundary & Threat Hardening（完成）
→ P9 Research Semantic Contracts + Campaign Governance + Minimal DSL v2（完成）
→ P10 GPT + Codex Capability Spike（完成）→ P11 Quant Research MCP + Offline Proposal E2E（完成）
→ P12 Real-world Evidence Acquisition（下一入口）→ P13 Qualified Event Feature E2E
→ P14 Research Ledger + Bounded Autonomous Research MVP
```

P8-P14 不得引入自有回测/交易/组合/会计引擎，也不得让 Agent 读取 token、修改快照、覆盖
artifact、修改 Gate verdict 或直接标记 `VALIDATED`。v0.2 将 GPT + Codex 作为单一目标栈，
但 P10 必须先通过固定配置、统一 rubric 和硬性 go/no-go gate。确定性验收对象是相同 resolved
Spec 与冻结输入产生的证据，而不是 Agent 文本的逐字一致。真实公告抽取在形成经过 admission
policy 的 immutable EventFeatureArtifact 前始终只是 proposal；真实研究结论仍依赖独立的
Data-qualified market-data 轨道。详细退出条件以 `PLAN.md` v11 第 40 节为准。P9 的冻结对象、
authority 分层、campaign 状态机和 DSL v2 运算符语义见
[`p9-research-semantics.md`](p9-research-semantics.md)。

P10 的最终硬能力决策为 Go（9/9）。权威本地证据绑定 spike spec
`f9a4e15d...dc71c2`、transcript `eb8c4460...b06d7`、AgentRunManifest
`56a1588a...1ec98` 和 report `1075c195...c35b1`；完整配置、恢复记录和限制见
[`adr/0001-gpt-codex-harness.md`](adr/0001-gpt-codex-harness.md)。P11 不得继承 P10 的合成
shell probe，只能映射既有 application services 的窄 typed MCP 能力。

P11 已完成。clean implementation commit `06eda7290874e9331ec2b28ef61b34491268cc13`
上的冻结 structured synthetic Evidence proposal 经 typed MCP、compiler、有界 job、既有 native-Qlib、
ValidationReport 与 Registry 完成两条独立流水线；resolved Spec 和全部 principal authority hashes
逐字节一致。报告 payload hash 为 `4c920a51...c85baf`，完整边界、哈希和限制见
[`p11-progress.md`](p11-progress.md)。

## Current live qualification bindings

```text
Capability report       57c7d418a1eb871735813f7200ef8ab4f50ac54467aaedc493743f2d9bbf71b1
Implementation commit   f3fc7684d09ac351d72d76b2a0370c58bec8589c
Lockfile                 31ca517e4de3fc7d539a903a2a96a2ba6d92399b6f3dbda51dffca6407a008d4
Runtime fingerprint      66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
Snapshot build spec     db80037b1bc30372d4128a79381a46213a30d4c293a1056948b5249023f3742e
Execution policy        5173902191371a46f97d98097e4819f8b29bd3d1fafaa404837947ae43f4d1e4
Data-quality policy     4514dfb419071d3e6d7ae852d6cb06eb421d772f8870570de6c4a2a52091e275
Acquisition staging ID  71e560222361ce1a4ff55b7b23b05bcc0b9cd1d27b6e90fcf0cd632f0811e474
Request ledger           cb043126d2bc7663a61aa9c5a491e87b490977c9227693571625be4b4e8cacdb
Live snapshot            6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9
Live quality report      e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8
Live Qlib view           fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b
Live PIT evidence        17f3a368d87142dcd877f30c71587991692b19c6ff9acf68753a6cafb282a71f
Live SignalArtifact      dba57f2a5db23c36a58d705ef5be0dbd94df686002c35c9bf3286218788ce51e
Live signal content      9e993232d2d1d20c73031b48f31ac83562c614ddef1910e1ab8cfe273e643502
Live BacktestArtifact    ec318505caccead33188f909ab445acddc363334c0e96eb25af57ad05cea4270
Backtest config          49c804a3a46bf042ad2482ecd82b4179be9f4aa9783c36ed9f190064c2682844
Reconciliation           c01cd819ae4f773e4e441ed57882d05550f55959ea6445e2f897468ec7e540d1
ValidationReport         553d49a710d97d49af536e8950001c5f91c3d88dddce3fa2b29cb8f788d855a7
Experiment manifest      ba2c794ef8a0f96beb68f33472ca09b963a5125cb301a8b1979b6d581974e49c
Registry index           04a276a2e8c7bd08b6b925b7b81590536269f371534fb0a2115b897215a0396a
```

The capability artifact reports 12 requests and 12 `AVAILABLE` outcomes. The acquisition staging
ID identifies resumable checkpoints, not a published snapshot. The snapshot contains 672
instrument records, 1,596,969 aligned bar/factor/price-limit rows, 39,900 membership rows, and the
explicit `SINGLE_SOURCE_NON_VINTAGE` limitation. The view contains 667 effective member securities
plus the HS300 benchmark; all effective members resolve to both mappings and tradability data. Five
constituents first seen in the provider's final 2025-12-31 membership snapshot remain raw-only
because their next availability session is outside the build range.

## Formal first-stage release evidence

The workspace-local authoritative Data-qualified summary is
[`artifacts/releases/data-qualified-v0.1-f3fc768/report.json`](../artifacts/releases/data-qualified-v0.1-f3fc768/report.json).
It binds the explicit live snapshot and implementation commit above, Qlib 0.9.7 source commit
`da920b7f954f48ab1bb64117c976710de198373e`, two independent release pipelines, and exact equality
of every principal content hash. Each pipeline produced the same set of 15 SignalArtifacts and 15
BacktestArtifacts; the two ValidationReport files are byte-identical. Independent CLI verification
of both snapshots, views, baseline signals, baseline backtests, reports, and registries passed.

The release outcome deliberately separates engineering qualification from research acceptance:

```text
Release                         PASS / DATA_QUALIFIED / data_qualified=true
Validation execution           SUCCEEDED
Validation verdict             REJECT
Registry strategy status       REJECTED
Hard and structural gates      G0-G4, G6-G10 PASS
Soft-gate result               G5 REJECT: annualized_turnover 29.53442815294007 > 12
Robustness evidence            3 cost + 9 parameter + 4 subperiod = 16 cases
Limitation                     SINGLE_SOURCE_NON_VINTAGE
```

The baseline annualized return was `0.034215151782246364`, OOS Sharpe
`0.21195024879335697`, and maximum drawdown `0.2902119289878075`; these research metrics are
reported evidence, not engineering acceptance criteria. A prior candidate report
`b40fa4b122c174ff82e78768a23a113f266899a84b571cab4f51c98bf8200ff7` remains immutable evidence of
a valid G8 rejection: its last decision in a frozen subperiod executed in the next subperiod. The
implementation now includes a schedule only when both decision and execution dates lie inside the
frozen interval. The corrected four execution ranges end on 2017-12-25, 2020-12-28, 2023-12-25,
and 2025-12-29 respectively, and G8 passes.

The companion formal M0 rerun on the same implementation commit completed two independent
`OFFLINE_ENGINEERING / SYNTHETIC_FIXTURE` pipelines with byte-exact principal hashes. It produced
snapshot `4ae0b2ed...55fb`, Qlib view `82b584bc...4d23d`, SignalArtifact `0264d742...ceab`,
BacktestArtifact `4cacc90e...43af`, ValidationReport `7651525b...c51a`, experiment manifest
`1e86919a...50ba`, and Registry index `962f41d9...271e`; its strategy status is `VALIDATED`.

## Historical P2-P4 offline component evidence

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
Quality suite       Historical v1 evidence: 151 passed; Ruff PASS; Pyright 0 errors; branch coverage 85.05%
```

The implementation commit passes 176 tests, Ruff, Pyright with zero errors, and the 85% coverage
gate (85.30%). The hashes below are retained historical synthetic component evidence; they must not
be interpreted as hashes for the revised live-data semantics or as Data-qualified evidence.

The P4 SignalArtifact above was regenerated after the P5 policy fields were frozen. It and the P5
evidence below bind clean synthetic feasibility commit
`272eafb0b175b1f7a6c6f883e8cee68097c2253c`; that temporary checkout is component evidence, not
release provenance for the formal first-stage baseline.

## Historical P5 offline backtest component evidence

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
non-rebalance dates, limit-buy/ST/suspension blocking, raw 100-share BUY lots, Qlib sell-all
corporate-action odd-lot liquidation, minimum commission, and all six reconciliations. Qlib's
conservative target-weight precheck and lack of stable per-order
rejection reason codes remain recorded limitations; no substitute order or accounting engine was
added.

The native ML smoke uses `DatasetH`, `LGBModel`, `SignalRecord`, and `SigAnaRecord`. A one-session
forward label has explicit purged boundary sessions between train/validation/test. Only finite
metrics are exported; undefined IC/long-short metrics are named as omitted and are never coerced.

## Historical P6 validation component evidence

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

## Historical P7 registry and release component evidence

```text
P7 component commit      4889f9c66782187b4796d0432f3948b2f899c2f2
Runtime fingerprint      66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
Snapshot                 2698fdcee8d153dab005050f451b5c8cae0b11d60bd23d20ced3605785858ec4
Qlib view                b6a5220a97a6e568d9eec1e4b2fb18b928d81c1c9a777ac5893c89c44ee0bb36
SignalArtifact           4923c72f1cdf88c85aa2d4065869b9367e82c1284c67e41e2b49e0c52e956b1b
BacktestArtifact         07dfdd6143cfca96c47ba7a1a46cd6596e1bf0869bf212a5ef3b57d76f2e8bf1
ValidationReport v2      80694135b35676aeab885ceffb26993d3043839634dffa0bed5591fdb3433853
Experiment manifest      8796366ad940af53461116aaa746209fe146753030f31d63f057c99ead266aee
Registry index           80678c9466fa53321d45bd5bc5f899200a544050ffcf43ff062d971de6d50598
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
