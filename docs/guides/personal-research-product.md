# 个人量化研究入口

当前后继是 `hs300-daily-trend-tushare-lifecycle/v3`：仅当时可获得的沪深300历史成员，Tushare Pro
为市场数据唯一来源，每日收盘后研究、下一交易日开盘执行。包括指数中的非主板股票，
不再求主板交集，也不要求同花顺。旧 `daily-mainboard-trend/v1` 合同、任务与失败原件保留。
用户于2026-11-01明确选择供应商复权价格／数量单位场景。原价格、信号、成本、日期与七候选不变，
普通现金分红只由冻结供应商因子表达，不另加现金；不声称真实到账、精确现金再投或税后总回报。
旧两轮FAILED及权益审计按原范围保留；新任务不续跑旧终态。经典仍沿原完整721日结果复用。
当前独立任务及实际结果见 `artifacts/personal-research-product-20261101/dividend-continuation-01/`。
新任务 `5f491a28…` 已SUCCEEDED / NOT_EVALUATED：六新账户均721日，经典原tuple复用，
主策略模型收益-24.14%、经典-7.79%、基准+16.54%；单次授权已撤下。

## 实际接线与边界

实现位于 `contracts/personal_research.py`、`application/personal_research.py`、
`application/personal_server_config.py`、`application/hs300_worker.py` 与
`research/hs300_data.py`、`research/hs300_exchange.py`、`research/personal_qlib.py`。
生命周期后继另在 `contracts/hs300_lifecycle.py`、`data/lifecycle_sources.py`、
`research/hs300_lifecycle_data.py` 与 `research/hs300_native_boundary.py`。
现金运行时后继另在 `contracts/hs300_cash.py`、`contracts/cash_option_proof.py`、
`research/hs300_cash_runtime.py` 与 `research/cash_option_proof.py`。
复权单位后继另在 `contracts/hs300_adjusted.py` 与 `research/hs300_adjusted_runtime.py`。
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

后继服务共20工具（需重启MCP进程）：新增四个展示工具见下节；原16工具保留。研究原工具为 `research_capabilities`、`research_data_describe`、`research_history`、
`research_retained_read`、`research_prepare`、`research_status`、`research_execute`、
`research_cancel`、`research_results`、`research_simulation_prepare`；公告六工具沿用原入口。
既有真实Codex只读连通收据复用；11月1日的本地工具表面/服务检查按原身份采用。11月3日展示后继仅做源码阅读和格式整理，未运行接口用例、重复安装或连通检查。
运行中的MCP进程需重启后加载新工具与配置，不能把当前旧进程说成已经热更新。

服务默认读取固定产品根下的 `server-config.json`，也支持本地启动参数 `--server-config`。
配置路径、catalog原件路径及授权文件均不属于MCP参数。配置缺省时没有数据准入或执行授权；
当前v4配置保留旧catalog并注册复权单位后继，单次任务结束后`authorization_path`恢复null。
`approved=true`、模型自报批准和提案文字不能授予执行权。

可信本地授权必须另行绑定prepared/code/dataset/profile、完整七候选、实际批准原件hash、到期时间、
wall与宿主完整增长界限及既有storage policy。真实启动复用单重worker、宿主全局存储lease、
PID namespace和timeout。取消在候选边界生效；UNKNOWN不自动重发，终态不可续跑。
worker只读核验任务链，不在隔离PID视图内判断宿主父进程存活。PIT硬拒绝原因跨进程保留；
真实退出、失败和部分完成结果不改写。

v3授权另绑定现金规则/运行政策/原生源码hash、经典原始来源和七路信号复用规格。
v4再绑定复权单位政策、官方事实原文、原生加载／有效报价源码及完整后续会话的12个feature文件身份。
旧授权不能执行新模型；合并须实际持仓与订单为零、真实生成目标不涉及旧股、实际生产Exchange
及原生报价接口证实整个固定区间不可交易。条件推导不是未来收市观察或真实红利结清记录。
本次后继为六个新账户加一个 `REUSED_ORIGIN` 经典结果，固定七候选分母；
复用行展示原prepared/receipt，不能改写旧收据冒充新原生执行。
原编译输入、环境、源码与科学配置/指标实现及全部原件通过窄依赖核验后才采用。
默认没有真实科学执行权，工具参数不能授予。

可在MCP发出：

```text
请读取research_capabilities_summary与research_history，说明沪深300后继的
实际数据就绪状态、原生事件处理限制和固定七候选；不执行真实研究，也不采集或下载公告。
```

准备请求示例（dataset_id只使用服务端实际返回的匹配ID；无匹配时准备为BLOCKED）：

```json
{"schema_version":"personal-study-request/v6","idempotency_key":"hs300-vendor-unit-example-01","dataset_id":"hs300-vendor-adjusted-20230109-20251229-20261101-v1","brief":"沪深300复权单位研究；不另加现金分红，合并仅由实际原生零输入及有效报价证明放行","proposal":{"session_id":"outer-session"},"start_date":"2023-01-09","end_date":"2025-12-29","warmup_start":"2022-11-01"}
```

本地操作入口：

```sh
/home/zjw/quant-research-os/.tools/personal-research-mcp-1.26.0/bin/python -B \
  /home/zjw/quant-research-os/scripts/run_hs300_study.py describe-summary \
  --config /home/zjw/quant-research-os/artifacts/personal-research-product-20261022/run-01/product/server-config.json
```

将 `describe-summary` 换为 `prepare --request <明确请求文件>`，或
`status|results-summary|cancel|execute --task <明确task hash>`。未授权新任务会拒绝执行；终态返回原状态、不续跑。
后继完整数据改变时必须准备新任务，不给旧BLOCKED或终态包补换输入。

## 生命周期后继及剩余限制

2026-11-01后继明示原复权单位模型：海通2023-07-27登记、7月28日派息的每股税前0.21元
早已存在于Tushare返回及官方公告。三随机账户raw-equivalent诊断为8000/8400/7600股，
名义税前额1680/1764/1596元；这些不是到账或税基证明。除息因子已进入次日原生卖价，
因此新场景不能再独立加一笔现金。旧审计的实际付款UNKNOWN没有改成PAID。
现有收益字段只表示模型内扣交易费用的收益，不能解释为真实税后实收总收益。
新边界不处理非零持股的换股会计；非零持仓、订单、已观察独立权益或必需未知仍硬停。

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

Qlib 0.9.7没有此处所需的完整公司行动会计与可观察权益台账。v1的“全程从未涉及”政策仍保留。
v2仅对有官方连续持股必要条件的现金选择权新增严格分支：先核原生持仓/未成交单/完整历史，
再让Qlib实际生成目标和订单，确认均不涉及相关股后，在成交前保存派生现金资格0证明。
这是对指定现金权利的推导，不称原生权益台账已观测，不做现金、换股或持仓分录。
已知独立权益或必需观察缺失仍硬停；后续普通买入不恢复该项连续资格。
在保留的v2中，合并、永久停牌及退市继续使用原v1硬边界，不由现金证明自动豁免。

实际后继任务 `665334198da5d9be2edf456da98883fa67e73101521eec0608c93153e761200a`：
主策略已完成628日，到2025-08-12，8月13日停在中国重工后续合并边界；
五随机各完成499日，到2025-02-05，2月6日停在海通后续合并边界。
相比旧任务分别多完成127日和36日，失败完整区间指标仍null，不据部分区间给出完整收益优劣。

本次独立授权的Tushare定向采集取得两只股票的退市信息与停牌记录，公告接口返回权限不足；
补充采用4份交易所/官方披露平台原件。市场价格、成交额及成员来源仍只用Tushare。
采集原件、失败和来源身份留存在生命周期实施目录，MCP工具本身仍离线且不能发起采集。
本次执行前，既有64 MiB/4096 inode scratch挂载已由用户恢复并通过原StorageGuard；
不放松C盘32 GiB、Linux16 GiB安全余量或既有守卫。WSL关闭后再次启动仍需核实挂载。

连续前瞻账户另受原生Account完整checkpoint、初始NAV分母和reset_report清空历史约束，
未用Position字典或历史回放冒充实现。上述两次公告请求权限不足不等于全账号所有公告能力已核定；
标题/链接不等于正文或“没有利空”，不把旧27份材料或本次官方PDF改标为Tushare来源/交易特征。

## 历史合并权益逐项审计（2026-10-23，保留原口径）

新增快照层 `quantos.data.tushare.dividend_acquisition`、离线公告解析
`quantos.research.merger_entitlement_sources` 与登记日判断
`quantos.research.merger_entitlement_proof`。它们不授予执行权或清除现行合并边界。
Tushare两次采集均成功，五期实施分红日期／金额与官方原件一致；不声称返回全集或历史vintage。

两起合并均将登记日收市旧股转换为新股，尾股补成整数股；同时明确保留以前未领取的现金红利。
所以换股日空仓不能证明历史红利为空。30个账户／登记日组合中22项实际持仓0、
3项正持仓且结清未证实、5项在旧账户停止之后未观察。三项为random-17/41/73
在海通2023-07-27的持仓；公告派息日、后续卖出和复权价均不是这些模拟账户的到账凭证。
正持仓也不等于已证明未付款。现有原生路径缺该项独立支付／结清记录，研究保持BLOCKED，未新跑账户。

停牌期间零持仓保持的归纳解释仍须绑定完整原生有效报价路径；仅查到行情feature文件
在停牌前结束不等于已经运行到换股登记日，不能制造未来EOD或设置rights-empty标志。
后续若改变公司行动会计或采用明确总回报场景，必须有新的来源／语义／版本证明，不能改写旧结果。
详细原件、30项矩阵及具体剩余依赖见
`artifacts/personal-research-product-20261023/merger-entitlement-implementation-01/report.md`。

本轮证据、失败、运行包、检查与唯一主入口见
`artifacts/personal-research-product-20261022/run-01/handoff.md`的权益审计及现金运行时后继链接。

## 有界展示后继（2026-11-03）

默认先用 `research_capabilities_summary(offset=0, limit=20)`，仅返回分页的数据集ID/内容哈希、日期、来源、限制与就绪摘要；不展开manifest、Qlib文件表或历史inventory。最大100个数据集/页；注册不等于获准执行，详细manifest仍用原 `research_data_describe(dataset_id)`。

结果默认用 `research_results_summary(task_id)`：保留全部七候选及执行/证据/未评估状态、标量指标、经典origin的内容哈希与原prepared/receipt/outcome绑定、comparison哈希。失败或未运行的指标继续null，未观察边界count为null；部分原生产物不冒充完整区间收益。原comparison不在摘要中重复展开，年度/子期等完整指标仍通过原结果读取。

边界详情先用 `research_results_boundary_page(task_id, candidate_id, offset=0, limit=20)` 读取原file/sha256引用，再用 `research_results_boundary_read(task_id, candidate_id, boundary_sha256, start=0, max_chars=8000)` 读取原JSON文本片段。分页最多100引用，文本最多32000字符；返回next_offset/next_start直至null。无对应记录不生成零持仓或权益证明。

上述四个工具是明确后继；旧 `research_capabilities`、`research_data_describe`、`research_results` 以及CLI旧 `describe/results` 的完整结构保留。仓库Skill和这里的操作示例选择摘要工具作为默认，既有客户端可继续原接口；已运行的服务需重启加载。CLI对应 `describe-summary`、`results-summary --task HASH`、`boundary-page --task HASH --candidate ID --offset N --limit N`、`boundary-read --task HASH --candidate ID --boundary-sha256 HASH --start N --max-chars N`。

摘要和明细先调用原service.results，继续核验不可变outcome/comparison/receipt、经典origin与文件；正文再按receipt引用核hash。此次只改显示投影，未加核验缓存、重算信号或回测，也不承诺读取提速。原检查采用范围、本次实现验证待用户明确要求及本地集成身份见[收尾发布记录](../releases/personal-research-closeout-2026-11-03.md)。
