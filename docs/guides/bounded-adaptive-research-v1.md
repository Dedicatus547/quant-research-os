# 有界反馈研究离线版

2026-10-18 更新。`bounded-adaptive-research/v1` 的源码与离线模拟已集成到本地 main；
固定 `5235445` 的首次真实运行正常 STOP，新候选 0、科学 0。真实生成/科学/反馈后决策组合仍待验证，
`NOT_QUALIFIED`；[具体范围与原件](../releases/bounded-adaptive-integration-2026-10-18.md)。
本机固定快照、555 个既有价格组合结构、安全 DSL、单 worker；不扩大数据、算子、科学门或 sealed 权限。
模型可首次或反馈后 STOP，不强迫继续。

入口沿用仓库 scripts CLI 形态：`scripts/adaptive_research.py` 提供 `prepare/run/status/cancel/reconcile`；
`science-child` 只接受父预留、原请求和已隔离网络的 namespace。`prepare_adaptive_package.py`
从明确 pin 的历史小型原件与实际安装生成运行包，不调用 SDK、不做科学。
本机首次运行包和提示词原件位于
`/home/zjw/quant-research-os/artifacts/bounded-adaptive-research-20261017/package-01/`。
固定提交、具体哈希和机器环境以该目录 `release-manifest.json` 为准。**该包已终态，不再执行其启动提示词。**
剩余机会保持未使用，不自动续跑或转移；新研究任务准备新身份、独立输出、具体预算及适用授权。
开发线应交付填好实际路径和命令的新提示词，不要求操作者手填哈希。

## 权威和预算

新后继契约直接接纳 `PROPOSE/STOP` 和安全 AST；旧 Discovery 三方法、静态历史与
`SDK_GENERATION_ENTRY_NOT_QUALIFIED` 不变。复用 capability admission、结构 hash、singleton
冻结/枚举、工作量报价、`QuantosResearchExecutionAdapter`、PIT、Qlib Workflow/LGBModel、
Exchange/Simulator、Validation 与 receipt。没有自建科学/回测引擎。

父任务 append-only 事件绑定决策请求、完整 SDK capture、候选、子请求、反馈、报价和停止。
子预算只能从父额度分配；新建 singleton 不重置额度。旧 execution request 的 `agent_run_hash`
在此显式承载真实 adaptive SDK response hash，不伪造 AgentRun，解释固定在 `AdaptiveChild`。
每个事件后的 checkpoint 和报告按内容 hash 保存；没有 `latest/current`。

真实包上限：2 次 SDK 决策机会、2 个准入新结构、2 次科学执行；自动 SDK retry、UNKNOWN
重发、科学 restart、sealed access、总结模型调用均 0。实际冻结 grammar 的 555 个结构中，
111 个报价 17 units、444 个报价 18 units，因此新父任务 cap 为 36；不是历史余额转移。
非法回答、失败与 UNKNOWN 均占机会，未知 side effect 保留占用；完整结果补 receipt 不新增执行。
用量可观测值、订阅/现金余额和 policy units 分开；输入/输出观测界限不是远端精确计费上限。

正式运行先验证完整 snapshot/view，并在同一 operation 中只读共享该核验；随后每次副作用前重查
期限、取消和额度。准备包只检查小型 manifest 与原件来源，不冒充新的全量数据核验。
每个子任务仍为 singleton family；父搜索是自适应回顾性探索，不继承有限家族整体校正或独立确认结论。

## 操作和中断

`launch.py --describe` 和 `--verify` 离线读取具体提案、核对源码/环境/输入 pin。
只有收到用户对具体包、外发范围、期限与预算的批准后，操作会话才能用 `--authorize` 留存原批准，
再用 `--run-approved` 启动。新生成的包不预置 authorization；描述文件不是授权。
不要执行旧 launcher、修改运行源码、升级依赖或 `uv sync`。

新任务命令的完整绝对路径均由其新包内 `runbook.md` 给出；采用对应 `startup-prompt.txt`，不复用已终态包。
运行进度不需逐轮批准。原始总期限为首次 activation 后 10800 秒；恢复不得重新计时。
包的启动批准最长有效 24 小时；收尾对账有独立 900 秒管理上限，不新增 SDK/科学机会。

| 持久边界 | 动作 |
|---|---|
| 决策预留，尚无 SDK intent | 核验父来源、原期限、取消及预算后，可启动同一请求 |
| SDK intent 后无完整 capture | UNKNOWN；不重发，不退款，不造零用量 |
| capture 完整，尚未业务提交 | 从 provider/normalized/raw/runtime/usage 原件核验并提交同一响应 |
| 子任务预留，尚未 SCIENCE_STARTED | 原额度/期限内可启动；receipt-only 不启动 |
| SCIENCE_STARTED，缺完整结果 | RECOVERY_REQUIRED；核对在途进程和真实退出，不重做科学 |
| 完整 outcome 已保存，receipt 缺失 | 显式 `retain_completed_outcome` 后继模式下，底层核验原结果/请求/charge，仅补发 receipt |
| receipt 完整，父任务未结算 | 复核后发布反馈并结算同一预留，不新增执行 |
| 取消/过期/停止 | 阻止新工作；已在途结果保留，允许只对账；未知费用不假定退款 |

`cancel` 写独立且绑定 task 的不可变取消 intent，不等待 controller writer；在途调用不假定撤销。
科学输入准备结束、写 claim 前再次检查期限/取消。SDK 独立 root lock 和父 reservation/intent
上限也约束其公开启动方法。同任务科学 history 与 authority 写串行，旧运行线从未写入。

反馈必须核对相同 request、candidate、结果与 receipt；gate 枚举、原因码、指标/null 与来源 hash
有 24 KiB 上限。科学 REJECT 保持科学拒绝；执行失败保持 FAILED/NOT_EVALUATED，不生成指标。
退出为独立管理观察，不能替代科学原件。只读 status 的保留投影明确标为需重新核验；实际后继
决策和运行报告在同 operation 中核对科学原件，避免每个 checkpoint 重复大文件解析。

真实交付必须同时读 operator 父进程 wait、guard cleanup/namespace exit、SDK capture、科学退出、
Validation/receipt、父账和报告。controller finally 只声明自身观察，不能冒充父进程 waitpid。
首次 STOP 是有效停止，仍缺新候选路径证明；第二次 STOP 可观察反馈后停止，不能声称修订路径已证明。
本轮不证明长期可靠、跨宿主安装、反馈因果改善、盈利、投资适用性或 vendor-vintage PIT。
