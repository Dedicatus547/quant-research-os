# 固定候选有界运行首版：完成核对与固定身份

2026-10-17。结论：两线计划的**最小本机有界执行版已达到正常路径工程接受范围**，可以集成源码并固定采用。
完整自动研究仍未达成；反馈改变/改善决策、新候选生成、任意异常自恢复和跨宿主安装未证明，P14d-C 不变。
这是对已完成原件的后继核对和版本登记，不改写旧失败、准备包或科学权威状态。

## 固定对象与两线

- 运行源码：`29fef56f303fa25ed19a82a7cc1286426d666df5`，保持 detached worktree
  `/home/zjw/quant-research-os/.worktrees/run-agent-runtime-29fef56f303f`。
- 开发提交链：`d754652` → `60e5760`（规划基线）→ `0b15d22`（薄准备器/运行入口）→
  `d48f5f9`（metadata 投影与失败观测）→ `29fef56`（定向验证及观测修正）。主线采用原提交，不重写运行身份。
- 环境：本机 `WIN-ZJWCOMPUTER` WSL；SDK/runtime `0.162.1`、`gpt-6.1-sol / medium`、V4、apps=false，
  原 helper hash `d9cd741fd38a3d2462b2a1987ea18b47e23fb89e24bb7e86ed82fc5d564dca21`。
  独立 Python 通过显式 `.pth` 采用保留 SDK overlay/科学依赖；`uv.lock` 默认 extra 仍为 0.154.0。
  接受仅覆盖此已绑定环境，不表示默认 `uv sync` 或可搬运安装已通过。
- campaign：`4c026b568ff28e31b9b8b42d4ac7c5dee68c8757234f0726ce10959bc8573de6`。
  持久运行根：`artifacts/hosted-evidence/agent-runtime-bounded-29fef56-20261017/task-01/`。
- 本次登记只改当前文档；运行 checkout、环境和科学政策保持原身份。开发线后续变化不自动升级运行线。

## 逐项完成与因果链

| 计划项 | 已交付及证据 | 接受边界 |
|---|---|---|
| D0 | 固定两候选模板和 metadata preparer；新 task/campaign/预算身份；真实运行采用显式只读输入挂载与固定环境 | 本机保留依赖、`p14dq-frozen/v1` 两候选形状；通用任务/新候选/跨机安装未接受 |
| D1 | 正式 `sdk_campaign.py run` 连续完成两步、持久退出和报告；`reconcile` 只对账；原协议与业务状态机复用 | 正常路径由真实原件证明；UNKNOWN/无 receipt 等停止/恢复窗口主要采用定向离线证明，不宣称全部真实故障已覆盖 |
| D2 | 正式入口接线原 namespace helper，两个科学 child/process exit、completion、receipt 对应，guard cleanup 成功 | helper、Qlib 和科学门不重建；单 worker、原宿主权限/挂载/lease 条件内 |
| D3 | 定向离线证明按依赖采用；同一次真实运行完成两轮 SDK—科学—反馈—交付，后继接管核对原件 | 无运行中源码修补记录；接管说明本身不替代原始进程和 receipt，也不证明长期可靠或所有独立操作者均可完成 |

`0b15d22` 的第一次正式入口运行在 provider 已回答后，被冻结 v2 normalizer 对
`turn/moderationMetadata` 的拒绝阻断。1 次 SDK 已消耗，科学为 0，原结论 `FAILED_NOT_ACCEPTED` 保留。
开发线增加显式 metadata 投影并保留原 provider 通知，未知事件/无效归属继续拒绝；同时记录独立 SDK 退出和失败时用量。
冻结 normalizer、秘密扫描和科学判据未被放宽。后继在两个真实回答中均遇到该通知并成功发布，支持这一修复与故障的因果关系。

后继新授权运行一次调用正式入口，2 次 SDK → 2 次离线科学/Validation → 2 份 receipt → 正常终态。
第二轮 reservation prompt 与 provider 用户消息 echo 一致，并包含同 campaign 第一轮 Validation 等原件引用；
这证明反馈传递。任务仍指定两候选依次选择，不证明反馈改变或改善决策，也不是新候选研究。
准备任务、绑定环境/授权和启动 launcher 是操作员动作；执行期间的后继请求由正式入口推进。

## 跨层原件与身份

以下相对路径均以主仓库 `artifacts/agent-runtime-bounded-20261017/` 为根。
这些本机持久原件不纳入 Git；远程源码副本本身不携带完整运行证据或依赖环境。

| 原件 | SHA256 / 用途 |
|---|---|
| `candidate-29fef56-01/release-manifest.json` | `9d2512029871575969ddef18ed01850cebe87a6a951ac4c695285ab1f75173c8`；准备时点的源码、输入与环境 pins，保留原待授权状态 |
| `candidate-29fef56-01/runtime-environment.json` | `b066552090cf57118f458cabe144356ae2c321b5885e36f8e7c6d379e21dc80c`；实际本机环境绑定 |
| `candidate-29fef56-01/operator-run-01/result.json` | `0a82fe37d061ec10cfb4cb42f64a491582e8f7451dd31051926cf897c83939f9`；完成结果及具体原件引用 |
| `candidate-29fef56-01/operator-run-01/evidence-audit.json` | `45e66316a80ba03a4ff5b5cd0f7030d403b2c7d58aeadb6fa344d2bb3d766c4e`；463 份小型原件库存、SDK/协议/receipt 对应 |
| `candidate-29fef56-01/takeover-review-01/evidence-comparison.json` | `16c8ec7c25b90c07c29c641ec04f7e128036d8996ba77426f9a2ef72cd26279f`；34 项接管身份核对 |
| `offline-repair-01/offline-verification-01/verification-result.json` | `9cb491520ada33a3486dda49e7804b0c4d7af08760f35c7ebe17eb398df6c431`；离线用例及各轮来源，原件包括 JUnit/真实 exit |
| `integration-review-01/review.json` | `b6f23dc6c44b95c66ed627b40be2012d7cceb0eecabf2130af6194c6ee7b645d`；本次提交前核对、采用范围与剩余边界 |

提交前检查实际读取了运行根中的 request/reservation/response/submission receipt、原 provider echo、
反馈所引 Ledger 原件、SDK process exit、两轮 science request/child exit/process exit/completion/receipt、
协议预算对象与 ValidationReport，并交叉核对 controller、operator 和独立 storage guard 的退出。
这些检查支持同一身份下的执行/发布/结算闭合；哈希一致不独立证明科学内容正确。
大型科学文件采用本次真实 helper 已完成的 receipt 验证，不重新解析或重算。

已有 JUnit 共记录 98 次 case 执行、7 次历史失败。73 个历史名称中包含一个已被替换的失败草稿；
当前采用 72 个不同通过用例，各自保留执行轮次和依赖范围，不改标为最终提交新跑的完整矩阵。
提交前第一次检查误假设全部历史名称均需最终通过，exit1；按已有 `case-history.json` 的明确替换关系
完成核对，exit0。该核对失误及原测试失败均保留，不是新增测试或科学重试。
原 main `d754652` CI 只按原身份采用；本次集成后的远端 CI 另按实际 checkout 读取。

## 结果、预算与停止条件

工程：`COMPLETED / ALL_CANDIDATES_TERMINAL`，operator/controller/guard、两轮 SDK host 和科学进程实际 exit0；
guard 观测到 waitpid、namespace 退出及 cleanup。实际耗时约 72 分 54 秒，未超过原冻结 deadline。
事件中的冻结逻辑时间不作为真实完成时间。

科学：两份 Validation 均 `SUCCEEDED / REJECT`，G5 的 Sharpe/换手率不达标；两份 receipt 均 `SOFT_REJECT`。
选择器没有 eligible series，canonical campaign 保持 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`。
工程完成不改写科学拒绝，也不授予盈利或投资适用性结论；资格仍 `NOT_QUALIFIED`。

本次实际 2/2 SDK 机会、2/2 科学、2/2 Validation、36/36 政策 units；provider 观测输入 43,857、输出 310 tokens，
自动重试/UNKNOWN 重发/历史额度复用均为 0。额度全部耗尽，token 观察不是账单或计费硬上限。
旧失败 campaign 的剩余账面上限也不能续用。

下一任务从[运行手册](../guides/agent-runtime-bounded-v1.md)准备新身份、独立持久根、具体报价和外发授权，
不执行已完成或失败的旧 launcher。UNKNOWN 不重发；STARTED 无 receipt 按既有规则保留占用并交接开发线。
若环境/输入/源码或实际依赖变化，先说明失效的具体结论及最小补证；不因总 commit 变化重跑全部历史。
本次核对未运行测试、模型、科学或部署，没有新增研究费用。
