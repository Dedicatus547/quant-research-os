# 当前状态

状态基准：2026-09-29。生产资格仍绑定既有实现提交；本次文档修订未发布新的资格。

## 工程与研究结果

| 轨道 | 工程资格 | 研究结果 / 适用范围 |
|---|---|---|
| P0–P7 Offline Engineering | 完成，基线 `f3fc768` | synthetic 确定性发布链 |
| 第一阶段 Data-qualified Release | `PASS / data_qualified=true`，基线 `f3fc768` | Validation `SUCCEEDED / REJECT`；Registry `REJECTED` |
| P13 v2 | `SUCCEEDED / PASS`，基线 `46904c2` | 单公告、批准 benchmark、已 admitted proposal 离线复用 |
| P14d-B | `QUALIFIED`，基线 `e318dc4` | 有界 synthetic 离线自主工程 |
| P14-DQ | `SUCCEEDED / PASS`，基线 `e318dc4` | 精确冻结输入和运行环境内的自主工程；研究 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` |
| P14 RC 文档 | `3a4a898` 独立 RC 复审 `APPROVE` | 待记录发布标记；批准范围为精确文档提交 |

完整 P14 哈希与权威矩阵见 [P14 状态](p14.md)及[RC 修正记录](../releases/p14-rc-v1-equality-correction.md)。
独立复审结论与实际核验范围见[复审报告](../reviews/p14-rc-3a4a898-independent-review.md)。

## 实现范围

| 阶段 | 已完成的范围 | 保留的边界 |
|---|---|---|
| P0 / P1 | 锁定环境、contracts、哈希、原子发布、不可变事件 | Contracts 不依赖 Qlib/Tushare/LLM SDK |
| P2 / P3 | 九类 endpoint 快照、官方 Qlib view、数据质量与 snapshot-bound PIT | `SINGLE_SOURCE_NON_VINTAGE` |
| P4 / P5 | safe Qlib 表达式、native ML/records、Qlib reference backtest | 无自有交易或组合会计引擎 |
| P6 / P7 | G0–G10、稳健性、OOS、不可变 ValidationReport、append-only Registry | 工程 PASS 与策略 REJECT 分别报告 |
| P8 / P9 | 有界 ingress、authority root、Evidence/proposal/admission/campaign contracts、DSL v2 | Agent 输出保持 proposal |
| P10 | 冻结 CLI 配置的历史 9/9 capability spike | 不授予当前 SDK 或自主 live Agent 资格 |
| P11 | typed application facades、三个 Skills、有界队列、synthetic proposal E2E | 该 direct-facade 证据不证明生产 transport 或真实 Agent 组合链 |
| P12 | 隔离公告 Collector、Evidence publisher、确定性抽取、双根发布 | SZSE 使用权限 `UNKNOWN`；该记录没有 admitted EventFeature |
| P13 | 批准的 v2 benchmark、只读 adapter、admission 与 native-Qlib 下游 | 单公告且提供引用位置提示；不证明通用抽取能力 |
| FR-01 / FR-02 | 已 admitted DSL 贯通；Qlib IC/Rank IC 的不可变 ResearchResult | 未资格化的指标不进入 Gate |
| P14a / P14b | Ledger/ContextPack 资格；预冻结有限候选枚举 | 无动态候选家族、mutation 或 crossover |
| P14c | Holm / circular-block-bootstrap 选择工程资格 | 有限 synthetic 范围；无市场选择或 sealed 资格 |
| P14d-A / P14d-B | Scripted/Replay 编排、预算、失败分类、restart/replay 与双根工程资格 | 无 live Agent runtime |
| P14-DQ | 既有合格数据上的完整自主工程核验 | 零个合格候选；未执行选择 |
| FR-03 / P14d-C | FR-03 离线实现完成；live SDK `NO_GO` | `THIN_MAINTENANCE` / `BLOCKED_UNIMPLEMENTED` |

## 未获得的权威

Live Agent、sealed confirmation、alpha/盈利、投资适用性、历史 vendor-vintage PIT
和无限制自主研究均未取得当前资格。P14d-B 的 synthetic `SELECTED` 与
`READY_FOR_SEALED_CONFIRMATION` 仅是工程用例。

FR-03 的候选 runtime 与重新进入条件见 [FR-03 状态](fr03.md)。

## 证据入口

- [第一阶段 Data-qualified 汇总](../../artifacts/releases/data-qualified-v0.1-f3fc768/report.json)
- [P13 v2 冻结](../p13-v2-freeze.md)
- [P14c 契约](../p14c-selection-contract.md)
- [当前 P14 RC 修正与精确绑定](../releases/p14-rc-v1-equality-correction.md)
- [旧状态页与组件哈希](../history/2026-09-29/docs/implementation-status.md)
- [旧 P14 实施与资格历程](../history/2026-09-29/docs/p14-progress.md)

这些旧记录可用于追溯各实现提交。其旧报告不替代 `e318dc4` 的当前 P14d-B/P14-DQ 报告。
