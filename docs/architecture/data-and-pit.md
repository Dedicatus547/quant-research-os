# 数据与 PIT

Tushare 是市场数据的唯一已接入 canonical upstream。
研究只读取不可变本地 snapshot；Qlib view 从该 snapshot 派生。

## Required endpoints

| Endpoint | 用途 |
|---|---|
| `stock_basic` | instrument、上市/退市生命周期 |
| `trade_cal` | SSE/SZSE 日历 |
| `daily` | 未复权 OHLCV |
| `adj_factor` | 复权研究 |
| `index_daily` | HS300 benchmark |
| `index_weight` | 历史成员与权重 |
| `stock_st` | 历史风险警示 |
| `suspend_d` | 停复牌与 tradability |
| `stk_limit` | 每日买卖限制 |

权限、fields、row limit 和账号额度由 bounded probe 留证，不按积分数字推定。
Required endpoint 不可用时阻止对应 Data-qualified 发布。
不能静默用 `namechange` 或 synthetic 数据替代历史 `stock_st`。

## Raw 与 canonical

```text
API response → raw Parquet → canonical Parquet → derived Qlib view
```

| 项目 | Canonical 规则 |
|---|---|
| 时区 | `Asia/Shanghai`；时间戳显式时区 |
| 日期 / 时间存储 | Arrow `date32` / timezone-aware `timestamp[us]` |
| 股票 ID | `600000.SH`、`000001.SZ` |
| 价格 / volume / amount | CNY/share、share、CNY |
| Qlib 映射 | `600000.SH ↔ SH600000`；benchmark `000300.SH ↔ SH000300` |

保留原始供应商单位，并显式转换 `vol / amount`。
映射表进入 view manifest，验证碰撞、可逆性和 benchmark 解析。
DQ 检查主键、schema、生命周期、稀疏状态、跨 endpoint 值和完整覆盖。

## 时间语义

| 字段 | 含义 |
|---|---|
| `event_time` | 经济事件或市场记录发生时间 |
| `known_at` | 来源或系统可证明已知的时间 |
| `available_at` | policy 允许研究/决策使用的最早时间 |
| `observed_at` | 系统实际获取时间 |

```text
source.event_time <= source.known_at <= source.available_at
feature.available_at <= schedule.signal_time
schedule.signal_time <= schedule.signal_available_at <= schedule.decision_time < schedule.execution_time
SignalRow.available_at <= SignalRow.signal_time <= SignalRow.decision_time
derived.available_at = max(input.available_at...) + operator_delay
```

`SignalRow.available_at` 记录输入/派生值的可用时间；`DecisionSchedule.signal_available_at`
记录调度中的信号就绪时间。两者对应不同字段，分别由
[SignalRow](../../src/quantos/contracts/signal.py)与
[DecisionSchedule / TemporalMetadata](../../src/quantos/contracts/temporal.py)校验。

违反调度产生 `LOOK_AHEAD`；缺失 operator delay、不完整输入窗口或未知 availability 拒绝。

| Availability 等级 | 使用限制 |
|---|---|
| `EXPLICIT_SOURCE_TIMESTAMP` | 使用可核验的来源时间 |
| `DOCUMENTED_UPDATE_SCHEDULE` | 绑定文档更新规则，不倒推更早时间 |
| `CONSERVATIVE_DERIVED` | 绑定版本化保守 policy 和理由 |
| `OBSERVED_ONLY` | 只能在 observed_at 之后使用 |
| `UNKNOWN` | 不可进入 canonical experiment |

Snapshot build-time temporal validation 与 experiment-time lineage/PIT audit 分别检查。
Experiment 时间与 membership 来源从已验证 snapshot 解析，不接受调用者提交的伪证据。

## Historical universe 与价格

`index_weight` 构建有界历史 membership intervals。
月度数据按保守规则在下一交易日 09:00（上海时间）可用，旧区间止于新记录可用日前一交易日；
尚未可用的 terminal 记录只保留 raw，不进入可用 universe。
禁止拿今天成分回填历史、从月末反向填充或无界 forward-fill。
最后一个可用区间最多延伸到 snapshot 结束日。Policy 所需区间缺失时 `SOURCE_INCOMPLETE`。

同时冻结 raw OHLC 与 `adj_factor`：
`adjusted_close = raw_close × adj_factor`。
收益使用 factor ratio，不使用未来终点锚定历史。
停牌 session 的 Qlib OHLCV 为 NaN；tradability 等约束保留在 sidecar。

## Qlib view

只使用锁定官方 `dump_bin`、data-health 与可逆映射。
工具来自 Qlib 0.9.7 对应官方 source commit
`da920b7f954f48ab1bb64117c976710de198373e`。

同一 converter/config 可比较派生文件 hash。
跨 converter 版本需证明 canonical snapshot 未变、provenance 完整、语义样本一致与 health PASS；
不把长期 `.bin` 字节不变设为业务契约。
Semantic readback 对照官方转换器的 binary32 表示。

## PIT 能证明的范围

本系统证明：给定冻结的历史视图与批准 availability policy，研究不使用尚不可用的记录。
它不能恢复供应商未提供的历史修订版本，也不证明当年的 vendor vintage 与今天历史查询相同。

Validation 显式保留 `SINGLE_SOURCE_NON_VINTAGE`。
当前 vendor-vintage PIT 未资格化。

- [采集操作](../guides/acquisition.md)
- [Qlib 可行性与限制](../feasibility/qlib-0.9.7.md)
- [Contracts 与 provenance](contracts.md)
