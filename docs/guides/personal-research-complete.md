# 个人研究助手：本地完整路径

本页说明 v7 可执行策略及观察/原生账户后继。旧 v6 / 沪深300 v3 的结果、七行分母、
classic 来源、失败和资格保持原身份，仍见[原使用说明](personal-research-product.md)。
本次实施进度、接受边界和原件从[唯一主交接](../../artifacts/personal-research-complete-20261104/engineering-01/handoff.md)进入。
工程检查、探索结论及正式科学状态分别记录；这份指南不授予市场运行权限。

## 从方向开始

在加载本机 `$quantos-research` Skill 的会话中直接说：

> 想研究沪深300的日频价量趋势，希望控制换手。请先读已有证据，自行设计可执行策略和
> 最少充分对照，准备研究，说明数据缺口和预算；本次不采集、不执行真实回测。

助手读取 `research_capabilities_summary`、
`research_strategy_capabilities(include_schema=true)`、`research_history` 和
`research_scope_status`，自行选择实际注册的数据身份、日期和对照。完整 v7 JSON Schema
由能力工具按需提供，用户无需填写内部哈希。准备用 `research_prepare`，不会执行。
修改说明文字或 main/control/successor 报告角色不会改变算法；算法在显式策略规格中。

新请求为 `personal-study-request/v7`，每次 1–4 候选，策略为 `personal-strategy/v1`。
例如以下评分表达式是实际 v3 grammar，窗口和输入滞后均为向后依赖：

```json
{
  "expression_id": "momentum20",
  "nodes": [
    {"node_id":"close","operator":"field","field_name":"adjusted_close"},
    {"node_id":"momentum","operator":"return","inputs":["close"],"window":20}
  ],
  "output_node_id":"momentum",
  "input_lag_trading_days":0
}
```

量价字段包括已映射的复权 OHLC、adjusted_volume 和真实 CNY 成交额 amount_cny。
常量有限；64 节点、120 会话窗口、20 会话输入滞后，翻译长度最多 65,536 字符。
比较及布尔组合保留未知值；除零、非有限值和不完整窗口不被当成有效零分。
`Rank` 是时序算子，截面选择仅对该时点合格且有限的分数排序，代码升序打破并列。
没有映射或来源不完整时 prepare 拒绝，不用 volume 或 close×volume 冒充 CNY 金额。

默认供应商复权目录采用显式 `canonical-personal-fields/v1` 注册：在核验原 snapshot 的
bars、adjustment_factors、benchmark_bars 后补齐复权 OHLC/因子与来源时钟，Qlib 的
LocalFeatureProvider 仅为 `$amount_cny` 读取真实冻结金额，价格和数量继续核对原 bin。
旧 cache、manifest 和历史账户均不修改；新字段绑定具有独立 hash，信号采用 v2 原件。
`native-bins/v1` 及旧 SignalArtifact v1 继续按原身份读取。结构性缺源保留 null/NaT，
不能为其虚构行情或来源时间。

组合支持固定 Top-K 槽位或显式目标权重、单股上限及总风险上限，不足额保留现金。
日频/每周首个实际交易日计划、资格退出、原生持仓龄上限及排名缓冲有固定优先级：
资格和持仓龄退出先于调仓日/排名缓冲。持有期与退出来自 Qlib 实际持仓；未成交或部分
卖出仍是原生持仓，下一步继续处理。周频非调仓日只尝试必需退出，不假称已实施排名目标。
输入 lag 与下一实际交易日开盘执行 lag 各施加一次，历史成员/状态/可得时间参与 PIT。

## 执行、比较和后继

`READY_FOR_AUTHORIZATION` 表示输入准备完成。只有可信本地配置才能绑定到期的
`personal-research-scope/v1`：显式数据、策略准入集合、执行政策、实际运行依赖、
次数、账户数、总墙钟和完整增量空间。模型参数 `approved` 无法授予权限。
外层会话负责提案和解释，不另起研究 SDK 或模型服务。

有适用授权后使用 `research_execute`，读取 `research_status`、
`research_results_summary` / `research_results`。Qlib Workflow 和 PortAnaRecord 执行
原生策略、Exchange、Simulator、Account；MLflow 只作运行记录，导出的 JSON/Parquet
及哈希才是结果原件。新策略不同才解释相应计算变化；完整账户复用必须同时匹配策略、
实际信号、数据、政策、资金、时期、基准和运行依赖，保留原 receipt / origin。

每个 attempt 使用原宿主 StorageGuard、独占全局 lease、有限 scratch、timeout 和 PID
namespace。scope 先保留总剩余额度，真实 supervisor wait/namespace 清理和实际计量完成后
才能结算；body 返回不冒充操作系统退出。整卷增长是守卫观测，不作为任务精确写入统计。
失败、取消和 UNKNOWN 的未用预留继续保留，不自动退款、重发或转旧额度。

用 `research_cancel` 请求候选边界取消。原件在候选完成后立即保存，完整尝试分母不消失。
`research_reconcile` 只核对已保存结果、所有权和实际退出，UNKNOWN 不自动重跑。
真正未完成工作以新 idempotency_key、`parent_task_id` 和匹配的剩余或独立新 scope 准备；
已终态父任务和旧授权不续跑。可采用已核验的独立完成账户，不能重写其原 tuple。
`research_scope_stop(kind="research", reason=...)` 是合法终点，不要求固定迭代轮数或盈利。

## 解释和历史反馈

报告将财富/净收益、回撤、年度描述与现金、暴露、费用及换手并列。信号、资格、目标和
实际订单/成交分别保留；周频计划与实际动作分开，部分/未成交不被改成成功退出。
新 v7 的原生 `targets/`、`native-orders.parquet`、`portfolio.parquet` 和完整原生导出都在
候选 receipt 的哈希集合中。缺失指标保持 null，S/T/B 仅在原定义适用时引用。

新 v7 终态可用 `research_feedback_record(task_id, interpretation, recommendation, reason)`
从已核验 receipt 形成记忆；自由解释明确标为 MODEL_INTERPRETATION。
通用 `research_memory_record` 也可追加引用 JSON Pointer 的记录；修订追加后继。
`research_diagnostic_read(record_id)` 重验原件并提供支持、反例、局限和继续/停止理由。
`research_history(query, tags, as_of)` 支持结构化标签、文本和有时区的历史截止；未知或
未来可得时间不进入旧时点的记忆。详见[记忆说明](personal-research-memory.md)。

原七组、confirm2 和换手归因已作为首批带引用记录接入固定产品根。
confirm2 只表示原范围内 NOT_SUPPORTED，正式科学仍 NOT_EVALUATED；不自动重启确认搜索。
公告继续通过既有 announcement_* 工具读取和精确引用，只是有来源的辅助材料。

## 新快照、信号观察和原生连续账户

`research_snapshot_prepare(dataset_id)` 检查服务端注册的不可变 snapshot/view 与可信到达
元数据，不联网采集。元数据须绑定采集/来源可见/到达时间、实际原件、前驱及公司行动边界。
新数据接入只改本产品本地 catalog；真实采集仍只能经原 acquisition 层和另行有效授权。

`research_observation_prepare` 固定策略、政策、计划信号日和首快照；
`research_observation_observe` 记录 EMITTED / ABSTAIN / MISSING / STOPPED / FAILED。
实际 recorded_at/publication 时间与工程测试时钟分开。迟到补算追加 after_the_fact，不覆盖
原缺失日，也不能用它冒充已按时发出的信号。策略版本或历史修订另建身份。
用 observation_status / recover / stop 读、发布已保存完成记录或停止；只有 intent 而无
完成原件时保留 UNKNOWN，不重新编译。合成 ENGINEERING_REPLAY 不算真实前瞻。

`research_shadow_prepare(observation_id, start_date, end_date)` 创建从现金开始的冻结原生账户。
`research_shadow_advance` 使用前一实际信号日的记录和显式 execution_dataset_id 推进一天；
不接受用户导入 Position，也不自写现金、撮合或权益转换。未知公司行动、迟发信号、缺会话、
错误快照前驱、历史价格/成员/状态修订以及未知或改变的复权因子/单位都拒绝连续推进。
供应商复权情景不另加分红现金，不声称真实税后红利到账或完整交易所规则。
新策略历史执行同样保守拒绝账户生命周期跨越不支持的公司行动/权益窗口；
旧七组的零暴露证明不能授予新策略资格。从已完成边界之后新建的现金账户不导入旧权益。

检查点保存完整 Qlib Account、Position、累计费用/换手、历史报告、策略/执行所需状态、
最后日期、前后快照、信号/目标/订单/成交及完成收据。状态采用有界、白名单的非执行 JSON
codec，不加载外部 pickle。正常逐日状态、带仓重启、幂等重复和执行后发布前恢复均有原件。
导出已完成而发布未完成时先对账发布，不重复交易；只有 intent 的不明窗口不能盲目回放。
`research_shadow_status` 返回原生现金、最近报告、分页持仓和 checkpoint 身份，
`research_shadow_stop` 停止该账户。真实推进仍需独立的 finite forward scope，不默认定时运行。

## 本机入口和恢复

安装解释器为固定的 `.tools/personal-research-mcp-1.26.0/bin/python -B`。
默认持久产品根保持
`/home/zjw/quant-research-os/artifacts/personal-research-product-20261022/run-01/product`。
本地 CLI 示例（只读）：

```sh
/home/zjw/quant-research-os/.tools/personal-research-mcp-1.26.0/bin/python -B \
  /home/zjw/quant-research-os/scripts/personal_complete.py research_strategy_capabilities \
  --config /home/zjw/quant-research-os/artifacts/personal-research-product-20261022/run-01/product/server-config.json
```

将工具名换成实际 MCP 工具，用 `--arguments <JSON对象文件>` 传对应参数。
配置后继 v5 保留原 catalog 和默认空授权，增加 research_scope、forward_scope 和
snapshot_arrivals；见 `configs/personal-research/` 模板。配置路径和授权文件不接受 MCP 参数。
用户级安装的 `install_personal_research.py upgrade` 只升级已知 managed 前驱，保留其他设置，
并把完整配置备份存放在用户私有目录；未知手动修改会保留并拒绝覆盖。
MCP 超时上限不授予实际执行额度，实际总预算仍由 scope 和 supervisor 控制。

安装后启动新的独立客户端/本产品进程加载源码及配置；不能宣称旧连接热更新。
运行中源码变化会拒绝新准备/执行并要求重启，本地原结果仍保留。
回滚时先确认本产品没有活动任务，使用安装收据的私有 backup，恢复本产品 entry 或用
uninstall 只删除本 managed entry/Skill 链接；不删除历史 artifacts，不终止其他会话。

中断后先读本任务唯一 handoff，核对实际进程、global lease、task/job/收据和终态，
从未完成项继续。旧 721 日账户、confirm2 和正式失败不会因新 commit 而重算。
本地检查不冒充远端 CI；科学运行、真实新数据和未来观察尚未发生时必须明确说未运行。
