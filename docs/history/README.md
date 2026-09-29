# 历史文档

本目录保存文档重组前的原文。历史文本中的“当前”“下一步”和报告身份，
均按其原提交与写作时点解释，不替代[当前状态](../status/README.md)。

## 2026-09-29 原文快照

来源 commit：`9e2fc41a41f2d2b253e04c67b10519e6926c79dd`。

该快照按原相对结构保存 **50 个已跟踪文档文件**，bytes 不变。
[Inventory](2026-09-29/inventory.json)记录 path、size、SHA-256 与 source commit。
它是文档迁移清单，不是新的市场证据或 qualification report。

| 原文 | 内容 |
|---|---|
| [README](2026-09-29/README.md) | 旧操作指南与状态混合页 |
| [PLAN](2026-09-29/PLAN.md) | 完整设计、P0–P14 任务、旧验收和阶段历程 |
| [Implementation status](2026-09-29/docs/implementation-status.md) | 各组件、hash、旧资格与 append-only 进展 |
| [P11 progress](2026-09-29/docs/p11-progress.md) | Typed façade / synthetic proposal E2E |
| [P12 progress](2026-09-29/docs/p12-progress.md) | 公告来源、采集与 Store 发布 |
| [P13 progress](2026-09-29/docs/p13-progress.md) | benchmark、Agent attempts、admission 与 bridge |
| [P14 progress](2026-09-29/docs/p14-progress.md) | 分切片工程、资格、RC 历程 |
| [P10–P13 refactor plan](2026-09-29/docs/P10-13-refactor-plan.md) | SDK/Code Mode 调整的历史实施计划 |

## FR-03 记录

| 类别 | 原文 |
|---|---|
| Frozen policy | [Code Mode-aware P10](2026-09-29/docs/fr03-code-mode-aware-p10.md) |
| Qualification | [SDK matrix](2026-09-29/docs/fr03-codex-sdk-qualification.md) |
| Candidate | [0.156.1](2026-09-29/docs/fr03-codex-0.156.1-requalification.md) |
| Identity | [Runtime provenance](2026-09-29/docs/fr03-codex-runtime-identity-provenance.md) |
| Routing | [Diagnostic v2](2026-09-29/docs/fr03-codex-account-routing-diagnostic-v2.md) |
| Failure isolation | [Plan](2026-09-29/docs/fr03-codex-sdk-failure-isolation-plan.md) |
| Upstream reproduction | [Record](2026-09-29/docs/fr03-codex-sdk-upstream-reproduction.md) |
| D0.6 | [Raw app-server](2026-09-29/docs/fr03-d06-raw-app-server-isolation-test.md) |
| D0.7 | [SDK boundary](2026-09-29/docs/fr03-d07-codex-sdk-test.md) |
| Issue follow-up | [46947 draft](2026-09-29/docs/fr03-codex-46947-followup-draft.md) |

这些记录不启动其旧“下一步”。当前入口固定在[FR-03 状态](../status/fr03.md)。

## 冻结原件与后继关系

契约、ADR、批准、发布、P8/P9 与 P13 freeze 原件还保留在原路径；
快照中包含它们的原始副本，便于完整追溯。
本次修改没有重写这些证据。

旧 progress/FR-03 路径保留简短入口，兼容已有链接。
历史 Markdown 中的源码与 artifact 链接保留原相对路径，按原 source tree 解读。
源码不复制进文档快照；可通过以下入口查阅本次未修改的脚本，精确旧版本以 source commit 为准：

- [Qlib feasibility](../../scripts/qlib_feasibility.py)、[工具准备](../../scripts/bootstrap_qlib_tools.py)
- [Signal feasibility](../../scripts/signal_feasibility.py)、[Backtest feasibility](../../scripts/backtest_feasibility.py)
- [Validation feasibility](../../scripts/validation_feasibility.py)
- [SDK failure isolation](../../scripts/codex_sdk_failure_isolation.py)

Artifact 是授权工作区数据，不属于文档快照，也不随此目录复制。

需要查当前资格时使用[发布索引](../releases/README.md)，而不是从归档寻找最大的日期或最新目录名。
