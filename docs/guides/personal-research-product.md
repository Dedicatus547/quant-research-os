# 个人量化研究入口

当前后继是 `hs300-daily-trend-tushare/v1`：仅当时可获得的沪深300历史成员，Tushare Pro
为市场数据唯一来源，每日收盘后研究、下一交易日开盘执行。包括指数中的非主板股票，
不再求主板交集，也不要求同花顺。旧 `daily-mainboard-trend/v1` 合同、任务与失败原件保留。
实施与真实研究分开；当前完整2023–2025区间 **BLOCKED / NOT_EVALUATED**。

## 实际接线与边界

实现位于 `contracts/personal_research.py`、`application/personal_research.py`、
`application/personal_server_config.py`、`application/hs300_worker.py` 与
`research/hs300_data.py`、`research/hs300_exchange.py`、`research/personal_qlib.py`。
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
当前配置保存具体来源阻塞项，`authorization_path`为null，不注册不完整市场面板。
`approved=true`、模型自报批准和提案文字不能授予执行权。

可信本地授权必须另行绑定prepared/code/dataset/profile、完整七候选、实际批准原件hash、到期时间、
wall与宿主完整增长界限及既有storage policy。真实启动复用单重worker、宿主全局存储lease、
PID namespace和timeout。取消在候选边界生效；UNKNOWN不自动重发，终态不可续跑。
worker只读核验任务链，不在隔离PID视图内判断宿主父进程存活。PIT硬拒绝原因跨进程保留；
真实退出、失败和部分完成结果不改写。

可在MCP发出：

```text
请读取research_capabilities、research_data_describe与research_history，说明沪深300后继的
实际来源阻塞和固定七候选；不执行真实研究，也不采集或下载公告。
```

准备请求示例（dataset_id只使用服务端实际返回的匹配ID；无匹配时准备为BLOCKED）：

```json
{"schema_version":"personal-study-request/v3","idempotency_key":"hs300-example-01","brief":"沪深300Tushare日频趋势与成交额确认","proposal":{"session_id":"outer-session"},"start_date":"2023-01-09","end_date":"2025-12-29","warmup_start":"2022-11-01"}
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

## 完整真实区间的具体缺口

snapshot `6297a968…` / view `fc809bed…` 的原件、消费表hash与既有质量证明已核对。
`bars.amount_cny`是实际CNY成交额，不以volume代替；bar/factor/member/status可用时间参与信号截止。
完整预热2022-11-01、评价2023-01-09至2025-12-29的来源适配实际失败：

- `600837.SH`：2025-03-04至03-31，20个成员／交易日缺bars且无suspensions。
- `601989.SH`：2025-09-05至09-30，18个成员／交易日同样缺失。

月度成员区间延伸到 `instruments.delist_date`之后。该表没有足够的生命周期历史可用时间及
吸并/退市持仓处置证明；不能补零、按事后metadata静默裁剪成员或自造现金结算。
`build_hs300_panel`硬拒绝，未生成可准入的完整面板，也没有运行真实策略。
需要有时点证据的生命周期输入及可复用的原生账户处置路线，再形成明确后继包。
既有storage policy的64 MiB scratch硬配额挂载也需宿主操作员恢复；保留原安全余量与守卫。

连续前瞻账户另受原生Account完整checkpoint、初始NAV分母和reset_report清空历史约束，
未用Position字典或历史回放冒充实现。公告权限UNKNOWN，标题/链接不等于正文或“没有利空”；
不新增采集、外部PDF下载，不把旧27份本地材料改标为Tushare来源或历史交易特征。

本轮证据、失败、运行包、检查与唯一主入口见
`artifacts/personal-research-product-20261022/run-01/handoff.md`的沪深300实施后继链接。
