# AR0–AR5 离线交付

2026-10-17。**源码实现与定向模拟完成；真实组合待授权及验证。**
固定开发提交和新任务身份见本机持久
`/home/zjw/quant-research-os/artifacts/bounded-adaptive-research-20261017/package-01/release-manifest.json`。
只提交独立 `work/bounded-adaptive-research-20261017`；没有推送、部署、模型研究调用、科学执行或采集。
主仓三处用户文档改动与未跟踪计划原件保持原样；本分支纳入其计划原文，按规划时点保留。
使用说明见[操作手册](../guides/bounded-adaptive-research-v1.md)。

| 范围 | 交付 |
|---|---|
| AR0 | ec8087e 起点、独立 worktree、用户文件 SHA 保全；D0–D3 五份索引原件哈希相符，原 tuple 采用；旧 CI 39041958415 终态读不到，不假定 PASS |
| AR1 | 显式 adaptive 父任务/总预算/决策/子任务/事件契约；来源、反馈前缀、父提案、结构去重；不改旧契约 |
| AR2 | 新 AST SDK producer，保留原通知与真实 host 退出/用量；复用 singleton admission/freeze/quote 与原执行 port；旧 SDK Discovery blocker 保留 |
| AR3 | 验证 receipt/Validation/失败原件后投影有限反馈；确定性报告、null 和独立退出观察；零总结调用 |
| AR4 | 单 writer、SDK 父预留、父总账、独立 cancel、固定 deadline、完整响应补提交、完整结果补 receipt；UNKNOWN/不完整科学停止且保留占用 |
| AR5 | scripts CLI、既有 storage guard/bwrap/MLflow 挂载布局、固定本机运行包和无需手填哈希的提示词 |

原件目录：`artifacts/bounded-adaptive-research-20261017/`（主仓绝对路径），从开始即持久保存。
`coord/ar0.json` 是起点；`coord/retained-adoption.json` 核对旧发布、环境、完成结果、463 项审计索引、
接管核对以及未变 transport/normalizer/namespace helper/lockfile。两份已保存真实 SDK 通知逐字节
回放通过；它只证明原通知标准化复用，不证明新 schema 的真实响应。原 stdout 的可选依赖提示与
JSON 提取说明分开保留，没有为整理记录重做科学。

科学计算组件和门按原身份采用，`autonomous_execution.py` 的新增完整结果记录开关默认关闭；
新的 receipt-only 方法不进入 pipeline，现有完整底层核验仍决定能否采用。历史科学拒绝和失败
不改写为新提交通过；本次不重算大科学文件，不声称旧 PASS 已迁移为 adaptive tuple PASS。

离线验证按来源采用：`targeted-verification-05` 为 58 passed；其后受审查修复影响的
`review-window-verification-07` 为 2 passed、`preflight-verification-08` 为 6 passed。
这些包含重复用例，不相加称独立用例数。最后一轮覆盖完整结果补 receipt 的显式开关与最终模型
输入接线，实际结果在 `coord/final-verification.json` 汇总。Ruff 与受影响生产模块 strict Pyright
原件也在该根。没有全量 CI、完整资格矩阵或真实科学任务。

失败原件保留：feedback 初轮 typed fixture 失败、runtime 01–03 秘密扫描/usage 接线失败、
一次错误 nodeid 的 collection exit4、初轮类型检查环境参数错误。普通问题已局部修复；未扩大
模型次数、重发 UNKNOWN、改冻结 scanner 或放宽科学门。每个 checkpoint/实际退出与 JUnit 按轮保存。

新运行包重新计算 555 个结构的 17/18 units 报价，首次新额度 cap 36；SDK/科学各至多 2，
新候选至多 2，retry/reissue/restart/sealed 均 0，3 小时固定 deadline，5 GiB 完整增长预算，
现有宿主卷 floor/硬 scratch quota 和独占 lease 不变。授权前没有占用这笔额度或预留长期 lease。
包中的来源、外发字段、环境、命令与新任务路径完整填写；只有具体包完成后才向用户申请批准。

开发任务实际使用 Astra / High 的有限协议设计和最终边界审查、Sol / Medium 的独立反馈/报告；
最多两个子任务并行，归属分离。子代理意见不是验收原件。主会话自身模型由客户端设置，工具没有
切换或独立核验主会话模型的接口，未将提示词名称当作实际切换证明。

仍未证明：新 schema 的真实 SDK 来源→新 AST 执行→真实反馈后决策组合、真实修订分支、长期恢复
可靠性、跨宿主安装、反馈改善研究质量、sealed/盈利和历史 vendor-vintage PIT。原 FR-03 接受及
固定候选 `29fef56` 本机工程接受各按原范围保留；P14d-C 与新组合资格不变。
