# 第一阶段：确定性研究与发布

目标：从冻结 snapshot 到 ValidationReport 和 Registry，完成可审计离线链。
工程验收与真实数据资格分别报告。阶段现状见[当前状态](../status/README.md)。

## P0–P7 验收

| 阶段 | 交付与退出条件 |
|---|---|
| P0 Bootstrap / feasibility | Python/lock 环境、bounded capability probe、官方 Qlib 组件证据、账号与许可限制 |
| P1 Contracts / artifacts | 最小 schema、canonical hash、严格配置、原子发布、不可变事件、状态分层 |
| P2 Data snapshot / view | 九类 endpoint、请求计划与续传、raw/canonical、单位/时间/ID、DQ、官方转换与 health |
| P3 PIT | build-time + experiment-time audit；完整 lineage/window、membership、availability 与稳定拒绝原因 |
| P4 Research / Signal | safe Qlib expression、historical universe、native ML/records、purged split、immutable signal |
| P5 Backtest | native Qlib reference path、显式执行/成本、约束 golden cases、结果表与 reconciliation |
| P6 Validation | G0–G10、policy 网格、OOS events、独立复现、immutable ValidationReport |
| P7 Registry / release | append-only history、monotonic versions、状态机、可重建索引、失败留证、双运行 release |

细化任务编号和原始验收 checklist 保留在
[第一阶段原计划](../history/2026-09-29/PLAN.md)。

## M0 Offline Engineering DoD

- P0–P7 支持的语义具备 positive/negative 与稳定 reason-code 证据。
- 无 token、禁网 synthetic 全链路以及 native Qlib ML smoke 完成。
- 正常、PIT reject、execution failure、soft threshold reject 正确区分。
- Registry tamper、partial write、duplicate 与非法状态转换拒绝。
- 实现、lock/runtime、输入、policy 和主要输出可核验。
- 工程成功不要求 baseline 盈利或研究 Validation PASS。

## 独立 Data-qualified DoD

| 条件 | 要求 |
|---|---|
| Account / source | required endpoints、schema、额度和许可实际留证 |
| Snapshot / view | 真实授权快照、DQ、官方 Qlib health 与语义核验 |
| End-to-end | HS300 研究/回测/Validation/Registry 完整执行 |
| Reproducibility | 干净实现、双根主要内容 hash 与精确文件清单核验 |
| Limitation | 明示 `SINGLE_SOURCE_NON_VINTAGE` |
| Outcome | 工程结果与研究 verdict、Registry 状态分别报告 |

Token/权限不足仅阻止这条真实数据轨道，不能由 fixture 或降低 gate 绕过。
真实上游完成后仍不自动具备 vendor-vintage PIT 或市场结论。

## 已完成的基线

第一阶段发布实现为 `f3fc7684d09ac351d72d76b2a0370c58bec8589c`。
[Data-qualified 汇总](../../artifacts/releases/data-qualified-v0.1-f3fc768/report.json)保留：

- 工程 `PASS / data_qualified=true`；
- Validation `SUCCEEDED / REJECT`；
- Registry `REJECTED`。

这是独立的既有发布。当前 P14 的 `e318dc4` 资格不改写它的历史绑定。

## 后续入口

M0 完成后进入 [P8–P14](stage-two.md)。
架构规则统一见[架构目录](../architecture/overview.md)，实际命令见[离线指南](../guides/offline-workflows.md)。
