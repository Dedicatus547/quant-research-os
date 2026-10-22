# 个人量化研究入口

当前后继是 `hs300-daily-trend-tushare-lifecycle/v1`：仅当时可获得的沪深300历史成员，Tushare Pro
为市场数据唯一来源，每日收盘后研究、下一交易日开盘执行。包括指数中的非主板股票，
不再求主板交集，也不要求同花顺。旧 `daily-mainboard-trend/v1` 合同、任务与失败原件保留。
实施与真实研究分开；完整2023–2025区间的数据准备为 **READY_FOR_AUTHORIZATION**，
实际执行仍因既有scratch硬配额挂载和未获真实研究批准而阻塞，科学 **NOT_EVALUATED**。

## 实际接线与边界

实现位于 `contracts/personal_research.py`、`application/personal_research.py`、
`application/personal_server_config.py`、`application/hs300_worker.py` 与
`research/hs300_data.py`、`research/hs300_exchange.py`、`research/personal_qlib.py`。
生命周期后继另在 `contracts/hs300_lifecycle.py`、`data/lifecycle_sources.py`、
`research/hs300_lifecycle_data.py` 与 `research/hs300_native_boundary.py`。
使用 Qlib 0.9.7 Workflow、PortAnaRecord、目标权重策略、Exchange 和 Simulator；项目不实现撮合或账户会计。

- 主策略：基准和个股收盘高于SMA20、个股5日收益为正、当日成交额／前5日均成交额至少1.2；
  按5日收益降序、代码升序选前10名，每名目标9%，不足10名保留现金。
- 经典对照：相同历史池、市场环境、目标、成本与日频计划，以close/SMA20−1排序，
  不要求成交额确认或5日收益为正。随机对照保留主策略资格，以17/41/73/101/137固定种子排序。
- 每日更新目标，失去资格或被替换后于下一交易日尝试退出；没有固定3日持有上限。
  原生未成交、受限持仓及实际暴露均保留，不能把目标退出描述为已成交退出。
- 100万元本金，买0.05%、卖0.15%、最低5元为固定全包研究成本情景，非逐日历史税费重建。
  统一200股为较粗交易单位情景，非精确分板块零股规则。每日限价采用canonical原始up/down limit，
  在原生Exchange上按开盘价约束；复权factor用于原始股数换算。
- ST限制同时禁买卖；原生目标订单预检可能在任一方向限价时双向跳过，且使用前一信号日预检。
  全天成交量10%只是日频事后容量上限，不能保证开盘或集合竞价实际流动性。
- 成员可用时间使用既有保守次交易日09:00与有界区间政策，不声称官方精确逐日生效或历史vendor vintage。
  日线不重建盘中路径。旧质量/健康/PIT证明仅按原来源及其实际采用范围复用，不改标为新策略科学PASS。

## MCP与服务端配置

Skill 在 `skills/quantos-research`，用户目录链接与原MCP安装保留。官方SDK解释器为
`.tools/personal-research-mcp-1.26.0/bin/python -B`；科学依赖使用已有环境，不新增研究SDK。
固定产品根是 `artifacts/personal-research-product-20261022/run-01/product`。

新服务共16工具：研究 `research_capabilities`、`research_data_describe`、`research_history`、
`research_retained_read`、`research_prepare`、`research_status`、`research_execute`、
`research_cancel`、`research_results`、`research_simulation_prepare`；公告六工具沿用原入口。
既有真实Codex只读连通收据复用；本轮只核对改变的本地工具表面与服务接口，没有重复安装或连通检查。
运行中的MCP进程需重启后加载新工具与配置，不能把当前旧进程说成已经热更新。

服务默认读取固定产品根下的 `server-config.json`，也支持本地启动参数 `--server-config`。
配置路径、catalog原件路径及授权文件均不属于MCP参数。配置缺省时没有数据准入或执行授权；
当前v2配置已注册完整不可变生命周期面板，`authorization_path`为null。
`approved=true`、模型自报批准和提案文字不能授予执行权。

可信本地授权必须另行绑定prepared/code/dataset/profile、完整七候选、实际批准原件hash、到期时间、
wall与宿主完整增长界限及既有storage policy。真实启动复用单重worker、宿主全局存储lease、
PID namespace和timeout。取消在候选边界生效；UNKNOWN不自动重发，终态不可续跑。
worker只读核验任务链，不在隔离PID视图内判断宿主父进程存活。PIT硬拒绝原因跨进程保留；
真实退出、失败和部分完成结果不改写。

可在MCP发出：

```text
请读取research_capabilities、research_data_describe与research_history，说明沪深300后继的
实际数据就绪状态、原生事件处理限制和固定七候选；不执行真实研究，也不采集或下载公告。
```

准备请求示例（dataset_id只使用服务端实际返回的匹配ID；无匹配时准备为BLOCKED）：

```json
{"schema_version":"personal-study-request/v4","idempotency_key":"hs300-lifecycle-example-01","dataset_id":"hs300-tushare-lifecycle-20230109-20251229-v1","brief":"沪深300Tushare日频趋势与成交额确认；生命周期结构分类及原生边界硬停","proposal":{"session_id":"outer-session"},"start_date":"2023-01-09","end_date":"2025-12-29","warmup_start":"2022-11-01"}
```

本地操作入口：

```sh
/home/zjw/quant-research-os/.tools/personal-research-mcp-1.26.0/bin/python -B \
  /home/zjw/quant-research-os/scripts/run_hs300_study.py describe \
  --config /home/zjw/quant-research-os/artifacts/personal-research-product-20261022/run-01/product/server-config.json
```

将 `describe` 换为 `prepare --request <明确请求文件>`，或
`status|results|cancel|execute --task <明确task hash>`。当前 `execute` 会拒绝，不能用此命令绕过阻塞或授权。
后继完整数据改变时必须准备新任务，不给旧BLOCKED或终态包补换输入。

## 生命周期后继及剩余限制

snapshot `6297a968…` / view `fc809bed…` 的原件、消费表hash与既有质量证明已核对。
`bars.amount_cny`是实际CNY成交额，不以volume代替；bar/factor/member/status可用时间参与信号截止。
旧适配在完整预热2022-11-01、评价2023-01-09至2025-12-29上曾失败：

- `600837.SH`：2025-03-04至03-31，20个成员／交易日缺bars且无suspensions。
- `601989.SH`：2025-09-05至09-30，18个成员／交易日同样缺失。

旧 `build_hs300_panel` 和失败任务按原身份保留。新面板把 `is_member`、`is_listed`、
`lifecycle_state` 分开，全部230,700条成员记录保留，38条退市后结构性空值不补零；
存续内未停牌成员缺行情仍硬拒绝。源值从实际Parquet、交易所HTML和公司公告PDF确定性重算，
不是仅相信提案、摘要或文件hash。补充官方材料只用于结构分类/账户有效性检查，
不生成提前卖出信号，不声称已取得历史vendor vintage。

Qlib 0.9.7没有此处所需的完整换股/现金选择权会计与可观察权益台账。
新薄适配在最早权益窗口起点起持续检查原生持仓、前次未成交订单、当前生成订单及完整历史。
有相关暴露或未知状态就停止该臂，保留原生部分结果；七候选完整分母不变。
仅原生状态完整且从新现金账户启动、相关股票从未持有/成交等严格条件全部成立时，
才能在权益台账不可用的情况下推导“权益未发生”，不能称台账已观测或完整公司行动会计已实现。
实际七账户暴露尚未观测，不能预先声称可以跑完整区间。

本次独立授权的Tushare定向采集取得两只股票的退市信息与停牌记录，公告接口返回权限不足；
补充采用4份交易所/官方披露平台原件。市场价格、成交额及成员来源仍只用Tushare。
采集原件、失败和来源身份留存在生命周期实施目录，MCP工具本身仍离线且不能发起采集。
既有storage policy的64 MiB/4096 inode scratch硬配额挂载仍需宿主操作员恢复，
不放松C盘32 GiB、Linux16 GiB安全余量或既有守卫。

连续前瞻账户另受原生Account完整checkpoint、初始NAV分母和reset_report清空历史约束，
未用Position字典或历史回放冒充实现。上述两次公告请求权限不足不等于全账号所有公告能力已核定；
标题/链接不等于正文或“没有利空”，不把旧27份材料或本次官方PDF改标为Tushare来源/交易特征。

本轮证据、失败、运行包、检查与唯一主入口见
`artifacts/personal-research-product-20261022/run-01/handoff.md`的2026-10-23生命周期后继链接。
