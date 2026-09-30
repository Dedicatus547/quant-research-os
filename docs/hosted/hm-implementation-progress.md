# HM-MVP 实施进度

日期：2026-09-30。整体状态：`NOT_QUALIFIED`，尚未完成 MVP 验收。

HM-01/02 的基线、冻结契约和独立契约审查已保存；HM-03/04/05 的版本化交接、
持久化业务编排和受限 CLI 已实现并通过组件回归。HM-06 的冻结安装、namespace、
Unix channel、可信 CLI 捕获及管理 staging 已实现；尚需正式 profile 的实际启动和 Q07。
HM-07 的只读 raw/protocol/business verifier、保存 SUBMIT 导入和 offline 管理入口正在完善；
尚未实现完整 Q01–Q12 的 scenario verdict。HM-08 的实际模型驱动已接入受限 CLI，
正式 live、receipt reuse、两个全新 Qlib 根及完整 bundle 尚未执行。HM-09/10/11 未完成。

追加独立审查 [隔离启动与回放](../reviews/hm-replay-isolation-review.md) 批准有界实施澄清，
没有授予资格。普通 `python -I` 忽略 seed 环境的冲突已通过原生 CPython 初始化设施处理。
新部署对象使用 `hosted-deployment-profile/v2`，显式绑定 seed 初始化模式和 seed 0；
旧 v1 工件没有被补写或自动升级。新 binary、源码和编译记录进入完整只读安装 inventory。

2026-09-30 用户的开发模型分配覆盖：普通 Sol/Astra 工作由当前主 agent 执行；
必须独立的 subagent 工作使用 `gpt-6.1-sol`，effort 按任务确定；HM-10 保持
`gpt-6-luna/medium`。研究 host 冻结模型仍为 `gpt-6-sol/high`。本阶段主 agent usage
未提供，因此记录 `unavailable`；新增窄审为 `gpt-6.1-sol/high`，attempt 1、usage unavailable。

已执行的新增检查：99 项 hosted protocol/campaign/inputs/launcher/CLI/qualification/replay
组件测试通过；5 项真实 CPython seed/isolation 测试通过；ruff 和严格 pyright 检查通过。
双根组件测试使用明确的测试 receipt producer，不能替代 Qlib 或 live 资格。完整 CI 与
coverage 85% 门仍需执行。wheel 已可在本地现有缓存中离线构建，未修改依赖锁文件。

禁止把本进度记录或组件测试视为 HM-09 接受记录。FR-03、P14d-C 和历史 P14-DQ 状态保留。
