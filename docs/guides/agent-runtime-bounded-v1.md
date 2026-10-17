# 固定候选有界运行候选版

本版是 `agent-runtime-bounded-v1-rc`。支持本机 `WIN-ZJWCOMPUTER` 的 WSL Linux、
本地保留的 `0.162.1` SDK/runtime overlay 和科学依赖、既有 `p14dq-frozen/v1` 两候选任务。
SDK 仅提出冻结候选引用和停止建议；确定性 admission、预算、PIT、Qlib、Validation 和 Ledger
继续使用原实现。资格为 `NOT_QUALIFIED`，尚待目标宿主一次真实组合与独立操作者接受。
不证明反馈改善决策、新候选生成、完整自动研究或 P14d-C。

## 准备和支持条件

固定模板及原件字节 pins 在 [operator template](../../configs/runtime/agent-runtime-bounded-v1.json)。
这是受支持形状和参考输入，不是历史额度或新运行授权。历史 A1 SDK 11/11、科学 5/90 units 已耗尽。
本次实施授权的研究模型调用和科学执行均为 **0**。

`scripts/prepare_bounded_runtime.py` 用完整 release commit、固定模板字节、源输入根、
独立输出目录、task ID 和显式时间生成 canonical spec/config/bundle。只允许 reviewed 两候选、
2 执行/36 政策 units 形状；新 campaign 使用独立 budget ID，不读取旧 controller 或 launch 计数。
保留模板污染 ancestry 和 seed Ledger，不把它宣称为新的独立科学样本。原始 bundle 和历史证明不改。
输出目录必须新建；失败原件留下，另行诊断，不能重写失败目录。准备不调用 SDK/科学。

为避免大数据副本，准备只复制小型冻结对象与 seed。`metadata/prepared.json` 给出两个只读挂载的
精确 source/target/identity；源是 immutable Parquet snapshot 和已有 derived Qlib view。
准备态明确为 `METADATA_PREPARED_INPUT_MOUNTS_NOT_VERIFIED`。目标挂载点在挂载前为空，
此时不能启动 loader 或宣称任务就绪。由宿主在独立 mount namespace 内以只读方式挂载，
保留挂载身份/权限见证；禁止可写 hardlink 或只写一个“已挂载”标记。
科学 helper 的只读根挂载继承它们。输入完整性仍由现有 loader/verifier 核验。

源码必须 clean 并与 bundle 完整 commit 相等。SDK 与科学环境本次采用独立 venv 的显式 `.pth`
连接保留的 overlay 和主科学依赖；环境依赖路径与 binary hash 在交接原件记录。
这是本机固定环境方案，跨机安装/可搬运 wheel 未接受。不要运行 `uv sync --extra agent-openai`
覆盖本环境：锁中默认 SDK 是 0.154.0，不能冒充 0.162.1。
独立运行 worktree 与环境路径由最终 release manifest 给出，不从移动的 main 导入源码。

## 正式入口

原 `start/status/replay/launch/resume/step` 接口保留。
新增 `scripts/sdk_campaign.py run` 使用同一 hash-pinned spec/config、持久输出根和 storage guard。
一次调用执行 `start` 与有界 `producer.step` 循环，最多由 spec 允许的两次 launch；无自动重试。
`run` 在整个 controller 持有单 writer lock，仍使用原 protocol/business locks。
已有科学 helper 在正式入口自动接线，不需操作者临时修改 adapter。
helper 原 bytes 保持不变，限制原 trial ordinal 1/2；每个科学 job 持久保存 request、prelaunch、
真实 process exit、child exit、completion 和 MLflow layout。
namespace `/tmp/qlib-runtime` 是持久后端的挂载，权威不以 tmp 为唯一存储。
网络 unshare、clearenv、只读根、单 worker 和存储独占 lease 沿现有实现执行。

目录布局为一个绝对 `live_root` 下的 `protocol/`、`business-locks/`、`sdk-evidence/`、
`metadata/sdk-campaign-spec.json`、`metadata/loader-config.json`；config 另绑定 `inputs/` 和
`business-runtime/`。CLI 拒绝未约定的控制路径组合。run 必须传完整 helper byte hash、
显式带时区 deadline 和完整 job 增长报价，由 `hosted_storage_guard.py --stage matrix` 包裹。
固定 `controller/<campaign_hash>/activation.json` 阻止后续调用延长窗口；不能换根、换 campaign 绕过额度。
外部 supervisor 仍负责硬截止/kill 与子进程 cleanup；CLI deadline 在派发前检查，SDK 与科学子进程各有超时。

每步 checkpoint 和 operation/exit 立即写入持久 controller 目录。
摘要分开列 engineering state、research run status/verdict、protocol/research 用量、launch intents、
pending request、report/receipt hashes 和原件根。exit 0 仅表示已到正常工程终态，科学可能 REJECT；
exit 3 表示安全停止/待交接；exit 2 表示入口失败。SIGKILL 等未观察退出只保留启动记录，不能补写 exit0。
入口 bootstrap 失败记录错误类别，不保留可能含秘密的 exception text；guard 的 prelaunch rejection
仍采用 guard 原件。`run --help` 给出全部参数；最终持久启动包提供填好路径与 pins 的命令。

## 查询、只对账和恢复

- `business-status`：查询；不推进或发起 SDK/科学。
- `reconcile`：显式可写的 receipt-only 对账；同样受 guard/lease 约束。先拒绝 accepted 尚未形成
  research step 或 PREPARED 科学步骤，防止 `resume` 先写 STARTED、占额再被拦截。之后屏蔽 fresh
  `execute`，核验已完成 receipt 并调用既有 resume；可结算 STARTED 的有效 receipt。
- `STARTED` 无 receipt：既有状态机冻结 `RECOVERY_REQUIRED / EXECUTION_UNCERTAIN`，保留占用。
  已冻结的终态不会因后来出现 receipt 自动重开。不删除 intent、不重训、不编造成功 receipt。
- SDK intent 无完整 capture：`UNKNOWN`，run 停止，不重发、不退款、不加额。
  有完整 capture 时可显式使用原 `replay` 核验并补发布同一 response，模型增量 0；这是可写恢复。
  缺 capture 或 frame 超界仍拒绝。之后执行会推进科学的 `run` 必须仍有该身份的有效授权与原 deadline。
- 已发布 response / protocol accepted：由现有幂等 submit/resume 采用原 bytes/receipt；不重复扣账。
  普通 `resume` 和 `step` 可能执行科学，不能当查询或只对账。

UNKNOWN、FAILED、无进展、步数上限、TTL/取消、预算/空间/超时触发即停止；不切通道重发。
查询或正常对账也不授予下一次真实 launch。新费用、额外空间、延长授权窗口或修改科学范围需新授权。

## 本地验证与历史采用

实际日志、源码/环境身份、冻结 metadata 和剩余组合阻断在最终 handoff，放在仓库持久 artifacts 下。
新增定向离线用例覆盖两轮推进、UNKNOWN、无进展、deadline、只对账的四种窗口与正式 CLI helper 接线。
复用已有 SDK capture、CLI、legacy tracking/Workflow 接点用例；不重跑完整资格矩阵、真实模型或科学批次。
假 harness / 假 receipt 仅证明建模窗口与接线，不能替代目标宿主的 namespace、provider、Qlib 完成到 receipt、
权限/挂载/cleanup 和独立操作者接受。
历史 r10 原件、FR-03/CI 采用保留其 originating tuple；当前 shared execution/Workflow 与 r10 有依赖差异，
不能将旧科学结果改标为本候选 PASS。新真实组合尚缺；只提出同一次 2 SDK/2 science/36 units 接受机会，
一名独立操作者从正式入口完成反馈后续和交付；失败原样留证，不补满次数。
