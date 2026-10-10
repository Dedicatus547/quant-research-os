# ADR-0003: Host-mediated MVP 的有限提案交接例外

日期：2026-09-29。状态：`ACCEPTED_FOR_IMPLEMENTATION / NOT_QUALIFIED`。
后继于 [ADR-0002](0002-official-codex-python-sdk.md)，不修改该历史文件。
独立裁决见 [HM-02 review](../reviews/hm02-contract-review.md)。

## 背景与决定

现有官方 SDK 轨道的 FR-03 仍为 NO_GO / THIN_MAINTENANCE，P14d-C 仍为
BLOCKED_UNIMPLEMENTED。Host-mediated MVP 不借用该轨道的资格，也不将 SDK 6/9
改写为 9/9。它增加独立 `hm-mvp/v1` profile，QuantOS 持久化冻结请求、接收有界提案、
验证 admission，并继续使用既有离线 PIT / Qlib / Validation / Ledger / P14c 服务。

ADR-0002 中“新 harness 使用 SDK”的要求继续适用于 QuantOS 内部模型 runtime 集成。
此处只允许**外部宿主**读取只读投影并经受限通道提交 proposal 的协议例外：QuantOS
不启动模型或 SDK，不接收任意执行命令，不把等待宿主解释为研究失败。
外部独立 Codex 会话可使用系统 CLI 作为自己的宿主客户端；本环境发现的 0.158.0 只是
待绑定/验证候选。它不是历史 CLI backend 的恢复或资格升级，不修改 canonical SDK
0.154.0 pin。版本、binary、配置、安装、来源和隔离边界必须绑定于新的部署证据。

## 不可放宽的条件

[冻结契约](../hosted/hosted-contract-v1.md)与[验收矩阵](../hosted/hosted-acceptance-v1.md)
共同规定实施门：独立 hosted evidence/envelope；旧 `_validate_response` 保持严格；
禁止构造 usage=0 的 AgentRunManifest 冒充 SDK；不信任宿主自填策略、usage、verdict。
有限预算在发请求前预留，持久化拒绝/冲突，取消/到期不自动重签。
STARTED 后无有效执行 receipt 必须保守停止，不以重复执行猜测恢复。

固定部署采用独立 OS 身份或经过实际 probe 的等效 namespace/container 边界，服务离线且
只从冻结安装运行。研究宿主不能写权威根/服务代码，不能读 sealed/采集凭据，不能借
父进程、/proc、fd 或通道绕过。开发 Codex 会话的高权限不属于研究宿主权限证明。
可信 launcher 只能证明其观察到的进程、配置和响应，不能授予 effective policy、不可变
模型快照或隐藏 token/retry 硬预算资格。真实 host/model 交接必须独立证明。

允许提取或窄适配既有业务编排，hosted exchange hash 仅标识 HOSTED_EXCHANGE 来源。
不得引入自建回测/交易/会计引擎、泛化多 runtime 框架、动态候选家族或 sealed confirmation。
MVP 只承诺有界持久化交接和可恢复 checkpoint，不承诺无人值守调度、自动宿主重连或
live 文本可复现。双根复现绑定保存响应和确定性离线输入。

## 接受与后果

零 eligible 的合法研究阈值拒绝只按冻结契约 C11 的窄 gate 谓词接受工程闭环；研究自然
结果原样保留。盈利不是工程门，PIT/执行/证据缺口不能借该例外通过。
Q07 或 Q11 不通过/不可达即 NOT_QUALIFIED；离线 replay 不能代替真实权限和模型交接。
实施后 HM-09 必须独立审查精确 clean commit 与完整 bundle，再授予仅属于该新 profile、
环境和输入的资格。历史 P14/FR-03/SDK 资格与失败记录均保持原范围。

本决策的模型为 gpt-6-astra，reasoning effort=high，attempt=1，usage=unavailable。
冻结文件 hash 位于 [hm02-freeze-manifest.json](../hosted/hm02-freeze-manifest.json)。
