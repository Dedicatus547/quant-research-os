# 路线与研究文档索引

当前工作顺序见[根路线图](../../PLAN.md)，已完成范围见[状态总览](../status/README.md)。
本目录同时保存设计和阶段记录；其中的旧待办、模型分工与授权表述按写作时点读取。

## 下一阶段离线实施

2026-10-15：R1c 固定独立预测比较已完成并收尾。V/P均经独立核验并通过覆盖准入，自身定义日726/727与720/727；共同定义日720，Rank IC均值V为−0.012775936593236848、P为−0.00746288443551121，V−P=**−0.0053130521577256385**。这是固定候选与时期的回顾性探索比较；原V/P请求均为`EXECUTION_FAILED / QLIB_EXECUTION_FAILED`，均无ResearchResult/ValidationReport，Validation/P14c及failure/null不变，不授予任何资格。V/P终态receipt各18政策units，合计36；剩余科学机会0；P2a继续暂缓。真实退出和cleanup均已留证，无后续自动执行。见[M最终核对与收尾](../../artifacts/evolution-implementation-20261014/coord/r1c-closeout.md)及[B实际比较交付](../../artifacts/evolution-implementation-20261014/runtime/r1c-comparison-final.md)。[reader来源与恢复历史](../../artifacts/evolution-implementation-20261014/coord/r1c-observer-integration.md)、[M2交付](../../artifacts/evolution-implementation-20261014/coord/final.md)按原时点保留（持久原件位于主工作区，不随 Git 迁移）。

- [模型分工、worktree 与会话执行手册](quantos-evolution-model-worktree-plan-2026-10-14.md)：三会话、两个新增 worktree；Sol/Luna 分阶段执行，Astra 按具体疑难使用。包含共同基线、并行依赖、合并顺序与可复制提示词；原规划状态按写作时点读取。
- [演进路线图 v0.2 与 Codex 执行清单](quantos-evolution-roadmap-v0.2-2026-10-14.md)：2026-10-14 补齐 P1/R0；P2a 暂缓，近期范围为 P0 和复权成交量字段接线、固定双候选准备；实际实施与运行状态见上述最终交接。
- [P1 真实案例、R0 数据可用性与 R1 固定设计](quantos-evolution-p1-r0-evidence-2026-10-14.md)：本地原件、字节摘要、选择理由及读取范围。
- [A0 SDK 接入与使用](../guides/sdk-campaign-offline.md)
- [B0/B1 有界价格组合设计、离线示例与 B2 请求](bounded-price-composition-offline.md)
- [下一阶段策略及 agent 分工](quantos-next-stage-strategy-and-implementation.md)
- [本轮持久离线验证与交接](../../artifacts/next-stage-offline-20261012/)

A0、B0/B1离线实施完成，本轮源码、测试与文档按用户授权集成到main提交推送。2026-10-13：B2本次补跑和报告完成，
A1 V4后继r10两步工程闭环完成；个体科学均SOFT_REJECT、科学汇总FAILED/NOT_EVALUATED，累计SDK11/11、科学5/90，零重试。原r9取消及失败保留。旧资格及失败保持原身份；
[当前完成结果与用量](../status/a1-b2-authorized-preparation.md)。

## Discovery：先看结果，再查实现

| 阅读目的 | 入口 |
|---|---|
| 当前结论、完成范围与后续边界 | [Discovery 状态](../status/discovery.md) |
| 第二轮科学结果、完整候选和投入建议 | [科学报告](post-hm-next-scientific-report.md) |
| 第二轮生成多样性与成本 | [生成报告](post-hm-next-generation-report.md)；仅描述 D10/A，后续科学结果见上一行 |
| 首轮结果与失败 | [首轮报告](post-hm-mvp-discovery-report.md) |
| 实施交付与阶段来源 | [实施记录入口](post-hm-mvp-implementation.md) |
| 合入 main 的检查范围 | [两分支合并审核](../reviews/two-worktrees-merge-20261012.md) |

## Discovery：设计与接口记录

| 主题 | 文档 |
|---|---|
| 首轮问题与执行设计 | [研究指南](post-hm-mvp-research.md)、[执行计划](post-hm-mvp-execution-plan.md) |
| 后继设计与完成情况 | [后继指南入口](post-hm-discovery-next-steps.md) |
| 冻结比较政策及其后续执行 | [决策设计](post-hm-next-decision-design.md)；末节记录 B 已授权并完成，前文待授权为阶段历史 |
| 失败诊断 | [五失败归因](post-hm-next-failure-diagnosis.md) |
| 顺序历史与冻结 | [顺序生成](post-hm-next-sequential-generation.md) |
| 基线与计数 | [基线及三个分母](post-hm-next-baselines-counts.md) |
| 预测证据与方法比较 | [单来源证据接口](post-hm-next-prediction-evidence.md)、[多来源科学比较](post-hm-next-scientific-prediction.md) |
| 科学执行授权及独立预算 | [科学 authority](post-hm-next-scientific-authority.md) |
| 性能与暂缓依据 | [首轮成本](post-hm-mvp-cost-baseline.md)、[后继成本分析](post-hm-next-cost-analysis.md) |
| FR-03 首次候选调查 | [历史调查](post-hm-mvp-fr03-investigation.md)；其 7/9 NO_GO 保留，当前状态见[FR-03](../status/fr03.md) |

接口交付页里的“尚未运行”指该页交付阶段；实际后续运行及限定投入建议以第二轮科学报告为准。

## 原文归档与阶段路线

- [Discovery 完整实施历史](post-hm-mvp-implementation-history-20261012.md)
- [Discovery 原后继指南](post-hm-discovery-next-steps-history-20261012.md)
- [第一阶段 P0–P7](stage-one.md)、[第二阶段 P8–P14](stage-two.md)
- [HM-MVP 原始方案](host-mediated-mvp.md)：HM02 冻结审查输入；当前交付见[Hosted 状态](../status/hosted.md)

两份 Discovery 归档逐字节保留整理前原文，大小、SHA256 和来源提交见各自入口页。
历史契约、报告和接受记录继续保留原路径与身份。

## 本地证据与历史路径

`artifacts/` 通常不随 Git 分发。文档链接可指向原执行工作区，合并源码不会迁移运行原件。

| 原件类别 | 本工作区的持久位置 |
|---|---|
| 两轮正式生成、科学、比较及退出原件 | [主仓 hosted-evidence](../../artifacts/hosted-evidence/) 下的 `post-hm-discovery-01/` 与 `post-hm-discovery-02/` |
| Discovery 开发检查及管理交接 | [mainline worktree 的 post-hm-next](../../.worktrees/mainline/artifacts/post-hm-next/) |
| 合并检查 | [merge-review-20261012](../../artifacts/merge-review-20261012/) |

旧阶段文档中的相对 `../../artifacts/post-hm-next/...` 从原 mainline worktree 解析；
在合并后的主仓阅读时，应使用上表的原 worktree 目录。本次保留这些历史路径语义，未复制、迁移或重写证据。
