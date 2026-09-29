# P13 v2 qualified event freeze

2026-09-10：已批准的单公告 P13 v2 流程完成真实 Agent 抽取、确定性 admission、
离线双根执行与合并报告。Offline Engineering 和 Data-qualified 均为 `SUCCEEDED / PASS`。

## 输入与实现

- 人工批准：[审批对照](reviews/p13-benchmark-v2-review.md)。
- 冻结实现：`46904c22d039bca2da008beec8cd7d183d288fd1`，在隔离干净副本执行。
- 实现备份：`artifacts/qualification/p13-v2-implementation.bundle`，完整 Git history 已验证；
  文件 SHA256 `b8ee05e6acabbb0a2bbb30ceaac5cfbbe3a07b9095449d0913366bba891dac59`。
- Store：`4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306`。
- 市场快照：`6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`。
- Qlib view：`fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`。

## 权威产物

本地产物根为 `artifacts/qualification/p13-v2-replay-1/`。

| 产物 | Hash |
|---|---|
| Qualification bundle | `c6abe06780aa97f001049255cc0d3b34b9d014be05db6ea7d81e8ef55083d883` |
| Qualification report | `aa3f4f116f15a5ca992afe28e822960911ae288141e8a6b241e9685aa1ebd47c` |
| Agent manifest | `4ecafb334fee9ab91baf1ca72fbcf7953153a820a2cd2229166e2b9aed7c31bf` |
| Admission | `e9c9792fe19021bff372cfd5a27aedbb49f7247d7c35a9035d6be8cca330bdfd` |
| EventFeature | `6003c1b2b0fe8960b7a4f7c9e832fb6f7e61722855f2fa139660b144fe27df22` |
| EventStudy | `fc8d88c8a096e72e99cf4546d9a84d57c2b6535a5a2949574b66991738cb514b` |
| EventSignal | `54d11b120c3438643a33f2c35fdd1ca3a10189b82cf4ad9111dd9f28f820d5a5` |
| Backtest | `b9ac1cbf1f5d6507cda00512038c214fcd3efe02f9c7b2e97cee5ff4aa4b68b9` |
| Reconciliation | `29d328c2cfe963885527f5e7b1a35a3a2e47428594447bd05137e7fb0698c500` |

两根的全部主要内容 hash 一致。EventFeature 的 9 个文件、EventStudy 的 5 个文件逐字节一致。
Signal/Backtest 的 manifest 仅 `created_at` 不同（契约排除该字段）；不能把完整目录称为
逐字节一致。其余文件一致。独立复验第一根 EventFeature、EventStudy、Signal、PIT 和
Backtest 均通过；第二根由 runner 完成同样的执行后验证。

事件生效交易日为 2025-08-06，产生 1 条 signal。回测继续使用 Qlib Simulator/Exchange。
没有发布策略 `VALIDATED` 状态，也未修改 Registry 或 ValidationReport。

## 抽取与失败记录

复用的成功 proposal 为 `6aa6b80a7e375dcd5bde75de675a329b8663ffd6d18edf06f2f401f8b0735b0d`。
正式离线入口通过 `--agent-run` 校验该 run 的 Store、spec、transcript、proposal、schema、
instruction hashes 和工具交互后复用；双根下游运行没有新增模型调用。

| v2 尝试 | 结果 | 输入 / 输出 tokens |
|---|---|---|
| 沙箱内首次调用 | transcript 无效，manifest `c44b43c0…` | 无可用 usage |
| 实际抽取 | 3 个 MCP 调用、0 次重试；6/6 admission 通过；随后 dirty provenance 阻断 | 113,481 / 1,440 |
| 干净副本再次抽取 | `HARNESS_EXECUTION_FAILED`，manifest `5b287ec8…`，保留失败证据 | 244,397 / 4,021 |
| 离线复用 | 双根下游通过 | 新增 0；report 引用成功 run 的 114,921 tokens |

两个有 usage 的 v2 模型尝试合计 363,339 tokens；早期非冻结候选调试成本不包含在此数值中。
成功 proposal 的 schema/citation/admission/PIT 比率均为 1/1，重复率为 0/1。
这些是该选定 proposal 的指标，不是所有尝试的成功率，也不证明通用抽取能力。
本 benchmark 提供了引用位置提示，仅含一个公告；保留 `SINGLE_SOURCE_NON_VINTAGE`、
模型标识非不可变及来源修订历史无保证等限制。未提供货币成本估算或盈利结论。

## 验证与后续

主工作区全仓回归：305 passed，覆盖率 85.13%；Ruff、Pyright 通过。
P13 这条批准范围内的端到端资格链已完成。FR-01 与 FR-02 仍是独立的 P14 入口条件。
