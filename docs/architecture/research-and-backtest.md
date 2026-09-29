# 研究与回测

Safe expression 发布 SignalArtifact，事件桥接发布 EventSignalArtifact；
两者使用 SignalRow/v2 表结构和各自的 manifest。Native Qlib 模型服务导出 ResearchResult。
回测消费经核验的 expression/event signal 与 view，不再查询上游数据。

## Safe DSL

| 版本 | 已纳入运算 |
|---|---|
| v1 | field、ref、return、rolling_mean、rolling_std、add、subtract、multiply、divide、rank |
| v2 增量 | abs、delta、rolling_sum、rolling_min、rolling_max |

AST 经严格 schema 与 admitted compiler 翻译为锁定的官方 Qlib expressions。
任意 Python、自由 Qlib 字符串和未 admission 的算子不进入执行。

当前 field mapping 仅支持 `adjusted_close → $close`；`rank` 映射为窗口算子 `Rank(x,N)`。
字段名通过 schema 形状检查，仍需在实际
[translator](../../src/quantos/research/qlib/expression.py)中支持。

v2 的 `delta(x,N)` 需要输入窗口再增加 `N` 个观测；
rolling reductions 增加 `N-1`。PIT 要求完整窗口，并显式传播 operator delay。
官方 Qlib 的 null/rolling 行为由 golden evidence 固定；
缺失或非有限最终分数保留为 invalid，不自动变成可交易值。

`correlation / zscore / cross_section_rank / clip / log`、行业与规模中性化仍需独立 admission。
DSL v2 精确表见[冻结 P9 记录](../p9-research-semantics.md)。

## 模型与研究指标

复用 `DatasetH`、`LGBModel`、Workflow 与 Record Templates。
Features、label、train/valid/test split、seed、thread counts、rounds 和 early stopping 显式冻结。

Split purge 至少覆盖 forward-label horizon。
当前 Workflow 的 DatasetH `test` segment 取 resolved experiment 的 evaluation 区间；
`test` 是 Qlib segment 名称，P14c 另外核验该区间属于 campaign validation，不据此授予 sealed/OOS 权威。
`SignalRecord` 和 `SigAnaRecord` 生成 native Qlib 信号及研究指标。
FR-02 将 prediction、label、IC/Rank IC 序列和 IC、ICIR、Rank IC、Rank ICIR summary 导出为
hash-bound ResearchResult，并绑定已有 expression SignalArtifact、resolved spec 和 research policy。
这些指标来自 LGBModel 的 prediction/label records，不自动等同于因子原始 score 的 IC。
只有具备经验证输入证据的指标才可用于 gate 或选择。

`QlibWorkflowResearchService` 的发布结果是 ResearchResult；
现有回测输入由 expression/event signal builder 提供。
实现入口见[Workflow](../../src/quantos/research/qlib/workflow.py)。

Coverage、autocorrelation 等未取得相应证据的指标不能提前成为 authority。

### Qlib 执行生命周期

`e318dc4` 的修复在 `model.fit` 后等待异步 metric queue，并清空已停止 queue，
再执行 `SignalRecord.generate`。
它消除 metric producer/MLflow artifact consumer 的 race，
不改模型配置、研究统计、PIT 或 Validation 语义。

`QLIB_EXECUTION_FAILED` 仍然 fail-closed。
Qlib Position 的 set-order 浮点敏感性是另一问题，仍由[冻结环境范围](../status/p14.md)限制。

## SignalArtifact

Signal 表字段为 `instrument_id / signal_time / decision_time / available_at / score / score_valid / tradable`。
Expression manifest 绑定 expression、resolved experiment、snapshot/view、PIT lineage 和精确文件集合；
code/lock 通过 resolved spec 绑定。

EventSignal 使用独立 manifest，绑定 EventFeature、alignment policy 和 resolved event experiment。
RuntimeFingerprint 在 Validation/qualification 等对应 schema 中记录。
回测不能把缺失、非有限分数当作有效信号，不能绕过 membership 或 availability。

## Reference backtest

项目以 Qlib Strategy 接口表达目标权重。
Qlib Exchange、Simulator、Position 和 order generator 负责下单、执行与会计。

冻结基准为历史 HS300、top-50、周频等权。使用每周最后交易日及其下一交易日，
由已验证的 Qlib calendar 解析，上海时间如下：

| 字段 | 时间 |
|---|---|
| `signal_time` | 最后交易日 16:00 |
| `signal_available_at` | 同日 16:01 |
| `decision_time` | 同日 16:10 |
| `execution_time` | 下一交易日 09:30 |

调度实现见[schedules](../../src/quantos/application/schedules.py)。
Signal input lag 与 execution lag 是独立配置，不能重复移位。
历史 ST/停牌/涨跌停限制、100 股买入单位、无 short/leverage 与现金剩余由显式 policy 约束。

| 必须记录的设置 | 用途 |
|---|---|
| deal price、freq、settlement | 价格与执行时间语义 |
| trade unit、limit、volume constraints | 可交易性 |
| buy/sell cost、minimum commission | 成本假设 |
| initial cash、benchmark | 结果基准 |
| snapshot/view、signal 与 backtest policy hashes | 输入与规则身份 |

成本是冻结的研究假设，不代表完整历史券商规则。
公司行为、零股清仓与逐单拒绝原因等限制以
[Qlib 可行性记录](../feasibility/qlib-0.9.7.md)为准。

## Reconciliation 与稳健性

Reconciliation 对 Qlib 导出结果做资产/现金、价格、成本、交易单位和调度一致性检查。
它不运行第二套组合会计或回测引擎。

BacktestArtifact 冻结归一化结果表、Qlib provenance、trade constraints 和 reconciliation。
P13 事件桥接的回测资格不自动包含普通 `ValidationService` 或 Registry 链；
当前 P13 v2 未发布策略 `VALIDATED`，范围见[冻结记录](../p13-v2-freeze.md)。
完整 cost/parameter/subperiod grid 由版本化 policy 指定，不只报告最佳点。
[Validation](validation-and-registry.md)再判定研究结果。

- [离线操作](../guides/offline-workflows.md)
- [时间与 PIT](data-and-pit.md)
- [Campaign 选择](agent-and-campaign.md)
