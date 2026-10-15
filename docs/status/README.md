# 当前状态

状态基准：2026-10-15。各轨道状态按其独立记录和精确适用范围读取。
新增 [A1/B2 授权后运行状态](a1-b2-authorized-preparation.md)：V4后继r10两步工程闭环完成，控制器/守卫exit0；本轮两科学SOFT_REJECT，科学汇总FAILED/NOT_EVALUATED。累计SDK11/11、科学5次/90units，零重试；原r9失败保留，B2已完成，无追加预算。
B2已完成并复用，新增模型和科学执行0；LLM相对最佳基线无正增量。

2026-10-15：R1c 固定比较已完成并收尾。共同720个定义日的 Rank IC 均值差
V−P=`-0.0053130521577256385`。原 V/P 科学请求均为
`EXECUTION_FAILED / QLIB_EXECUTION_FAILED`，均无 ResearchResult/ValidationReport；
V/P终态receipt各18政策units，合计36；剩余科学机会0。P2a继续暂缓。该回顾性固定比较不改变原科学终态、
Validation/P14c 或任何资格判断。见[M最终核对与收尾](../../artifacts/evolution-implementation-20261014/coord/r1c-closeout.md)
和[实际比较交付](../../artifacts/evolution-implementation-20261014/runtime/r1c-comparison-final.md)。

后继 retained reader、CI 类型及 pytest 入口修复已集成：显式 producer/reader 绑定及
[`compare-retained`](../guides/frozen-field-study.md#explicit-successor-retained-reader)，采用 B 的有界工程检查，未运行真实比较。
[结果契约设计](../roadmap/quantos-next-result-contract-2026-10-15.md)未冻结新语义或资格，建议暂停新科学工作包。
实际集成提交、CI 结论、main 合并身份与远端发布状态见
[集成交接](../../artifacts/evolution-next-20261015/coord/final.md)。

## 工程与研究结果

| 轨道 | 工程资格 | 研究结果 / 适用范围 |
|---|---|---|
| P0–P7 Offline Engineering | 完成，基线 `f3fc768` | synthetic 确定性发布链 |
| 第一阶段 Data-qualified Release | `PASS / data_qualified=true`，基线 `f3fc768` | Validation `SUCCEEDED / REJECT`；Registry `REJECTED` |
| P13 v2 | `SUCCEEDED / PASS`，基线 `46904c2` | 单公告、批准 benchmark、已 admitted proposal 离线复用 |
| P14d-B | `QUALIFIED`，基线 `e318dc4` | 有界 synthetic 离线自主工程 |
| P14-DQ | `SUCCEEDED / PASS`，基线 `e318dc4` | 精确冻结输入和运行环境内的自主工程；研究 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` |
| P14 RC v1 | `FROZEN`，tag `p14-rc-v1` → `3a4a898` | 精确文档审阅及继承资格见 [freeze marker](../releases/p14-rc-v1-freeze-marker.md) |
| HM-MVP hosted component-v2 | MVP 已完成并 `FROZEN`；`ACCEPT_COMPONENT_V2`，tag `hm-mvp-component-v2` | 两项科学执行均 `SOFT_REJECT`；组件采用范围见 [发布记录](../releases/hm-mvp-component-v2-freeze-marker.md)及 [hosted 状态](hosted.md) |
| FR-03 SDK/runtime | `0.162.1 + gpt-6.1-sol / medium` 确切组合 GO | 实现已合入本地 main、尚未部署；[接受范围与限制](fr03.md) |
| Discovery 后继研究 | 实现及源码集成完成；定向检查不授新的全流程资格 | 第二轮 9 项可比预测、3 项缺源；按冻结规则暂停扩大当前空间同类生成；[研究状态](discovery.md) |

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
| FR-03 / P14d-C | 工作线 `0.162.1 + gpt-6.1-sol / medium` 资格 `GO`；实现已合入本地 main | 确切后继接受 / `BLOCKED_UNIMPLEMENTED` |
| HM-MVP component-v2 | 真实模型交接、campaign 终态、离线回放、独立接受及 HM10/HM11 交付 | 有限候选家族；旧证明按原 tuple 采用，当前服务已清理，业务调用额度已耗尽 |

## 未获得的权威

无限制 Live Agent、sealed confirmation、alpha/盈利、投资适用性、历史 vendor-vintage PIT
和无限制自主研究均未取得当前资格。HM-MVP component-v2 的有限工程接受见[独立状态页](hosted.md)。P14d-B 的 synthetic `SELECTED` 与
`READY_FOR_SEALED_CONFIRMATION` 仅是工程用例。

FR-03 的确切组合接受与证据见 [FR-03 状态](fr03.md)。hosted component-v2 保留独立身份；
FR-03 接受不授予 P14d-C 资格，后者仍为 `BLOCKED_UNIMPLEMENTED`。
两分支的源码集成、局部验证及历史证明采用范围见[合并审核记录](../reviews/two-worktrees-merge-20261012.md)。

## 下一阶段离线工作

2026-10-12：A0、B0/B1 源码与离线集成准备完成（工作区未提交），使用与设计见
[SDK 接入](../guides/sdk-campaign-offline.md)和[有界价格组合](../roadmap/bounded-price-composition-offline.md)。
[本轮原件](../../artifacts/next-stage-offline-20261012/)与既有科学证据分开保存。
上述2026-10-12离线交接时点A1/B2未启动；后续实际结果见页首当前状态。
P14d-C与SDK Discovery资格保持原状态。

## 证据入口

- [第一阶段 Data-qualified 汇总](../../artifacts/releases/data-qualified-v0.1-f3fc768/report.json)
- [P13 v2 冻结](../p13-v2-freeze.md)
- [P14c 契约](../p14c-selection-contract.md)
- [当前 P14 RC 修正与精确绑定](../releases/p14-rc-v1-equality-correction.md)
- [HM-MVP hosted component-v2 状态](hosted.md)
- [HM-MVP 本地发布登记](../releases/hm-mvp-component-v2-freeze-marker.md)
- [旧状态页与组件哈希](../history/2026-09-29/docs/implementation-status.md)
- [旧 P14 实施与资格历程](../history/2026-09-29/docs/p14-progress.md)

这些旧记录可用于追溯各实现提交。其旧报告不替代 `e318dc4` 的当前 P14d-B/P14-DQ 报告。
