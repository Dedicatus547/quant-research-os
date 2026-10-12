# 实施路线图

本页维护工作顺序与入口条件。系统设计见[架构文档](docs/architecture/overview.md)，
阶段结果见[当前状态](docs/status/README.md)，精确资格绑定见[发布记录](docs/releases/README.md)。

后续任务先读[实施与恢复约定](docs/guides/implementation-discipline.md)；
默认复用、局部影响与资源预算写在现有任务说明中，不另设开发门禁。
延误原因和改进依据见[HM-MVP 复盘](docs/hosted/hm-mvp-implementation-retrospective.md)。

## 当前落点

| 工作 | 当前范围 |
|---|---|
| P0–P7 | Offline Engineering 与 Data-qualified 工程发布完成 |
| P8–P13 | 已完成各自批准范围；不合并推导额外 Agent 能力 |
| FR-01 / FR-02 | P14 的 DSL 贯通与不可变 ResearchResult 入口已完成 |
| P14a / P14b / P14c | Ledger、有限候选枚举、有限工程选择资格完成 |
| P14d-A / P14d-B | 确定性编排与 synthetic 自主工程资格完成 |
| P14-DQ | 精确冻结输入和环境内工程资格完成；研究结果仍未进入选择 |
| P14 RC | 冻结于 `p14-rc-v1`，精确目标 `3a4a898`，生产基线 `e318dc4` |
| FR-03 / P14d-C | `NO_GO / THIN_MAINTENANCE` / `BLOCKED_UNIMPLEMENTED` |
| HM-MVP component-v2 | `FROZEN`；tag `hm-mvp-component-v2` → `59c25ac`；有界工程交付完成 |

HM-MVP 当前接受的是固定 C15 的 component-v2 工程组合；精确身份、复用范围和限制见
[发布记录](docs/releases/hm-mvp-component-v2-freeze-marker.md)。两项科学结果均为 `SOFT_REJECT`。
P14 原资格继续绑定 `e318dc4`；RC 文档复审对象及冻结身份见
[P14 发布标记](docs/releases/p14-rc-v1-freeze-marker.md)。

## 下一项工作

2026-10-12 后继 Discovery 已完成 D01–D07 实施及 D09 有范围集成；
D08 因尚无可避免成本依据而暂缓。顺序历史/恢复、覆盖基线、完整机会计数和独立预测证据接口已接入。
四份统计失败归因为常数预测，一个 signal 失败仍 UNKNOWN。
必要 Ruff、局部 strict Pyright 与旧定义 AST 核对完成；未运行测试或完整 CI，也未取得新运行资格。

首轮结果见[探索性研究报告](docs/roadmap/post-hm-mvp-discovery-report.md)；后继调度、具体交付与检查原件见
[实施记录](docs/roadmap/post-hm-mvp-implementation.md#后继实施调度2026-10-12)。
D10/A 已完成五次顺序模型调用、两组baseline、冻结与来源重建生成分析：各组5个不同结构、方法内重复0，
全局12个结构，LLM相对两基线并集新增3个。生成/分析/守卫均实际退出0，清理已核验，调用额度已耗尽。
事实、成本和继续投入限制见[后继生成报告](docs/roadmap/post-hm-next-generation-report.md)；当前建议暂不扩大生成。
B 已在独立v2评价authority下采用八个旧origin并完成四个新任务：两项SOFT_REJECT、
两项SOURCE_INCOMPLETE执行失败，新策略Validation PASS为0，未恢复或重训旧任务。
新预算72加全局一次失败恢复18、cap90；科学管理实际退出0、清理已核验，wall约68.1分钟。
后继统计来源已冻结，独立导入及正式比较03完成：9项可比预测、3项缺源，共同日期708天。
比较02被存储守卫中止，−15退出与清理原件保留；03采用原2GiB预测组件包络，
完整增长6GiB及原宿主安全底线保持。LLM与随机最佳共同日Rank IC均为0.0226969834，
增量0低于事前0.002，按冻结规则暂停扩大当前空间的同类生成；
[后继科学报告](docs/roadmap/post-hm-next-scientific-report.md)保留完整分母、失败、成本和探索性限制。
[事前比较政策与实际接续](docs/roadmap/post-hm-next-decision-design.md#d10b-科学授权后的实际接续)已记录；
科学结果尚未发布。A的cap1不改，新科学预算独立冻结，旧额度均不作余额，不重新生成。

HM-MVP 实施与发布交接已完成，目前没有必须重跑的验收或待完成的 HM09–HM11。
使用入口为[快速上手](docs/hosted/hm-mvp-quickstart.md)和[故障恢复](docs/hosted/hm-mvp-recovery.md)。
已完成 campaign 的调用额度已耗尽，后续运行需要新的授权与额度。

MCP 封装、standalone worker、其他 harness 或 SDK 重资格属于可选后续工作，
见[原始方案第9节](docs/roadmap/host-mediated-mvp.md#9-发布回退与后续工作)，由具体需求决定是否启动。
FR-03 继续遵守 [THIN_MAINTENANCE 政策](docs/status/fr03.md)；
P14 主线的重开条件沿用其[发布标记](docs/releases/p14-rc-v1-freeze-marker.md)。

## 实施依赖

```mermaid
flowchart LR
    P0 --> P1 --> P2 --> P3 --> P4 --> P6 --> P7
    P1 --> P5 --> P6
    P4 --> P5
    P7 --> P8 --> P9 --> P10 --> P11 --> P12 --> P13 --> P14
    FR01["FR-01 / FR-02"] --> P14
    DQ["独立 Data-qualified 轨道"] --> P13
    DQ --> P14
```

实现可以按依赖并行推进；阶段完成声明必须满足依赖的验收条件。

| 路线 | 详细验收条件 |
|---|---|
| P0–P7：确定性数据、研究、回测、验证与 Registry | [第一阶段](docs/roadmap/stage-one.md) |
| P8–P14：Evidence、proposal、admission 与有界 campaign | [第二阶段](docs/roadmap/stage-two.md) |
| FR-03：官方 Codex SDK/runtime | [冻结维护政策与重资格入口](docs/status/fr03.md) |
| HM-MVP：有界 Codex-hosted 工作流 | [当前交付与接受范围](docs/hosted/hm-implementation-progress.md)；[2026-09-29 原始方案](docs/roadmap/host-mediated-mvp.md) |

原始方案已作为 HM02 的历史审查输入绑定哈希，保留原字节。
其中“尚未实施”和模型分配属于2026-09-29提案时点，当前事实以发布记录和交付页为准。

## 范围约束

目标是 A 股日频 / 中低频研究。实盘交易、券商接口、分钟与 Tick 数据、
第二 canonical provider、基本面正式接入、动态 grammar、mutation/crossover 和多模型 Council
需要独立立项与资格门，均不由当前路线自动授权。

工程验收考察可审计执行与证据复现。收益软门拒绝可以是正确研究结果，盈利不是工程 DoD。

## 规则与设计依据

| 主题 | 规范入口 |
|---|---|
| 仓库硬性规则 | [AGENTS.md](AGENTS.md) |
| 后续实施、复用与恢复 | [实施约定](docs/guides/implementation-discipline.md) |
| Contracts、状态、哈希与不可变产物 | [Contracts 与 provenance](docs/architecture/contracts.md) |
| 采集、快照、时间语义与 PIT | [数据与 PIT](docs/architecture/data-and-pit.md) |
| Qlib、Signal、ResearchResult 与回测 | [研究与回测](docs/architecture/research-and-backtest.md) |
| Gate、稳健性、OOS 与 Registry | [验证与 Registry](docs/architecture/validation-and-registry.md) |
| Agent、Evidence、预算与 campaign | [Agent 与 campaign](docs/architecture/agent-and-campaign.md) |
| Go / No-Go 风险 | [风险登记](docs/reference/risks.md) |
| 历次 ADR | [决策索引](docs/adr/README.md) |

原 v14 的完整任务编号、阶段记述和旧验收结果保存在
[2026-09-29 文档快照](docs/history/2026-09-29/PLAN.md)。
该快照中的阶段状态按原提交解释。
