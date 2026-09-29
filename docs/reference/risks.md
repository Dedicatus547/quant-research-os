# 风险登记与 Go / No-Go

风险决定相应权威域的入口，不通过降低 gate、伪造 fixture 或替换历史身份解决。
当前已观察的阻塞项见[状态页](../status/README.md)。

## 数据与执行

| 风险 | 影响 | 控制 / 入口门 |
|---|---|---|
| Required endpoint / 账号额度不足 | 真实数据不完整或采集未完成 | bounded probe、显式 execution policy、request plan、续传 |
| 历史修订 / 无 vintage | 查询视图变化；历史当时版本不可证 | immutable snapshot、observed_at、`SINGLE_SOURCE_NON_VINTAGE` |
| Membership 时间证据不足 | Universe 前视或空缺 | 版本化 conservative availability、有界 intervals、PIT reject |
| 复权因子刷新 | 特征漂移 | raw + factor 同时冻结；新 revision 新 snapshot |
| 单数据源错误 | 无独立交叉证实 | 报告限制；不宣称 vendor-vintage PIT |
| Qlib 交易制度限制 | reference backtest 偏差 | 显式 Exchange policy、golden/reconciliation、known limitations |
| Async metric / MLflow race | Qlib execution failure | `e318dc4` drain/clear 生命周期修复 |
| Position set-order 浮点敏感性 | 更换 hash seed 可能产生末位差异 | 精确输入/实现/runtime/environment + `PYTHONHASHSEED=0` |
| Token / 数据许可 | 账号与数据传播风险 | acquisition-only secret、脱敏、许可留证、public fixture synthetic |

## Agent 与研究治理

| 风险 | 影响 | 控制 / 入口门 |
|---|---|---|
| LLM 抽取被当作事实 | 错误标签进入执行 | proposal-only、精确引用、admission、availability/PIT |
| Prompt injection / 外传 | authority 或秘密暴露 | Collector/Agent/Evaluation 隔离、bounded typed capability |
| Runtime / model 漂移 | provenance 与行为不可比 | 固定标识/配置、AgentRunManifest、实际权限观察 |
| Façade 被当作 transport/runtime 资格 | 未证组合能力被宣称完成 | 分开资格化 adapter、权限和真实 transcript |
| Ledger 检索漂移 | 上下文不可审计 | hash-bound snapshot/query/result/index/ContextPack |
| Adaptive family / hidden failures | 选择分母失真 | finite family、完整 trial accounting、冻结预算与 stopping |
| 多重检验与反复 OOS | 选择偏差与污染 | P14c frozen policy、access events、污染继承；sealed 仍未资格化 |
| 单实验 PASS 推导 selection | 研究权威越界 | 独立 CampaignSelectionReport 与完整 trials |
| 工程 PASS 推导盈利 | 错误市场结论 | 分别报告工程、Validation、自然研究和 non-claims |
| 当前 SDK execution 未观察到 | live Agent 组合未证 | FR-03 `NO_GO / THIN_MAINTENANCE`；不降 9/9 gate |

## 发布与证据

| 风险 | 控制 |
|---|---|
| Projection 一致误写为原始树 byte-exact | [RC 修正](../releases/p14-rc-v1-equality-correction.md)区分 principal、投影、各根 bytes |
| Bundle 核验误写为 full rebuild | [核验指南](../guides/qualification.md)明确检查层级 |
| 文档后继 commit 被当作已资格化实现 | production commit 与 docs commit 分别绑定 |
| 历史失败/blocked 被改写为当前 authority | 原始记录保持；索引说明 superseding/current 关系 |

更多原始风险与设计上下文保留在[历史 PLAN](../history/2026-09-29/PLAN.md)。
本登记不启动额外 provider、runtime 或研究能力工作。
