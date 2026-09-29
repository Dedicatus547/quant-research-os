# 验证与 Registry

Validation 消费已发布的显式产物，先核验引用，再评价完整证据。
程序执行状态、研究 verdict 和 Registry 生命周期分别记录。

## G0–G10

| Gate | 内容 | 类型 |
|---|---|---|
| G0 | Schema / reference resolution | hard |
| G1 | Snapshot integrity / data quality | hard |
| G2 | PIT / lineage | hard |
| G3 | Qlib factor research | soft |
| G4 | Reference backtest | soft |
| G5 | Out-of-sample | soft |
| G6 | Cost stress | soft |
| G7 | Parameter stability | soft |
| G8 | Subperiod stability | soft |
| G9 | Reproducibility | hard |
| G10 | Artifact integrity | hard |

当前 G3 始终核验 expression SignalArtifact；
启用 `rank_ic / icir` 阈值时，还要求 `research_result_path` 并重验 native ResearchResult 绑定。
阈值分别读取 `Rank IC / ICIR` summary。参见[ValidationService](../../src/quantos/validation/service.py)。

依赖、输入可读性和 Qlib 执行是产生证据的前提。
证据完整的 hard/soft rejection 为 `SUCCEEDED / REJECT`；
程序异常导致未完成为 `FAILED / NOT_EVALUATED`。
Hard gate 默认 short-circuit，保留之前证据，后续 gate 标记 `NOT_EVALUATED`。

阈值来自版本化 ValidationPolicy，policy hash 进入 manifest。
Agent 不能修改阈值、强制 PASS 或覆盖 gate。

## 稳健性与复现

冻结第一阶段 baseline policy 覆盖：

| 轴 | 完整网格 |
|---|---|
| Cost | baseline 的 1.0× / 1.5× / 2.0× |
| Parameters | momentum 15/20/25 × top-k 40/50/60，周频 |
| Subperiod | 2015–2017、2018–2020、2021–2023、2024–2025 |

每个 subperiod 验证最少观测数，决策与执行均落在其边界内。
其他实验按自己冻结的 policy 执行，不能套用不同网格或只选择最佳结果。

PR synthetic 与 release baseline 使用独立双运行。
普通 canonical 实验按 policy 按需复现，未默认重复整个 grid。
固定实现、lock/runtime、输入、Specs、policy、converter/config、seed 和 thread counts。

ID、日期、状态和行数 exact；数值比较按具体 schema/policy 的字段规则。
P14-DQ principal equality 不引入浮点放宽，限定在精确批准环境及 `PYTHONHASHSEED=0`。
对象内容域、原始字节域和批准投影分别比较，详见
[Contracts](contracts.md)与[RC 修正](../releases/p14-rc-v1-equality-correction.md)。

## OOS 与研究治理

Authoring spec 在 OOS 访问前冻结，resolved spec 绑定实际输入、policy 和实现。
`OOSAccessed` 持久化为不可变事件，Registry 导入并验证它的完整 lineage。

普通 Validation 的 OOS evaluation 与 campaign sealed confirmation 是不同权威域。
Campaign sealed access 的一次性规则和污染传播见[Agent 与 campaign](agent-and-campaign.md)。
实现这些治理 contracts 不等于已获得 sealed-confirmation 执行资格。

## P14-DQ admissible rejection

批准的 v3 契约允许完整执行后，在规定的研究阈值路径产生拒绝证据，
并将正确的编排与验证判为工程 PASS。

当前两个候选均为 `SUCCEEDED / REJECT` 和 `SOFT_REJECT`，
经 `G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET` 路径拒绝。
G4、PIT、artifact、来源完整性和 execution failure 不能借该例外被接纳。

因此自然研究仍为 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`：
零个合格候选，未执行 selection。工程 PASS 不构成市场结论。

## Registry

| 规则 | 行为 |
|---|---|
| Evidence registration | 重新核验 ValidationReport、来源与 OOS event |
| Strategy versions | 单调版本，逻辑身份冲突拒绝 |
| Lifecycle | 仅 `SUCCEEDED / PASS` 的合格证据可支持 `VALIDATED` |
| History | rejected 与 failed experiment 也保留 |
| Event chain | 不可变 JSON 与 hash-linked append-only events |
| Index | 可重建投影，不是 authority |
| Writes | 原子发布，串行化多文件更新，冲突 fail-closed |

相同 hash 的重复操作按契约幂等；conflicting identity 不能覆盖已有历史。
Tamper、部分写和非法状态转换拒绝。没有 `DEPLOYED / LIVE` 策略资格状态。

- [离线 CLI 工作流](../guides/offline-workflows.md)
- [状态语义](contracts.md)
- [当前工程与研究结果](../status/README.md)
