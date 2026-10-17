# 首次 STOP 后 N0–N3 离线闭合

2026-10-18。N0 任务说明与 N1/N2 后继实现完成；本地固定提交、实际定向验证、原件身份与
准备包以[本轮交付原件](../../artifacts/adaptive-closure-20261018/handoff.md)为准。
未启动 N4，研究 SDK 调用、科学执行、采集、推送和部署均为 0，仍 `NOT_QUALIFIED`。
主仓既有文档改动保留；实现位于独立 `work/adaptive-closure-20261018` 分支。

复用 AR0–AR5、其 61 个已采用用例及 originating tuple、首次 STOP 与历史失败，
不将旧测试或旧科学结果改标为新提交证明。科学契约、Qlib、grammar、TTL、预算总账及
UNKNOWN/restart 边界沿用原实现；只针对变化的历史投影、只读 capture、收尾和接线补验证。

[任务说明](../../artifacts/adaptive-closure-20261018/n0/task.md)的问题是：runtime 自主选择的
单个非退化、独立平滑收益结构，其原生 G5 换手率能否达到冻结阈值 12。
已有 G7 的 delta 窗口扰动均仍超过阈值，直接采用，不再重算。
新问题只涉及未执行的完整 AST；其均值子结构曾在 B2 组合中暴露。
结果不能证明平滑的因果效果、家族整体成败或收益改善。一次新科学足以回答单个结构问题，
前提是模型有充分理由提出该结构、科学结果完整；首问 STOP 和反馈后 STOP 均有效，
没有预填 AST 或窗口，也不预定第二次科学。B2 组成部分 null 与失败/缺证保留。

N1 的 `adaptive-local-package-recipe/v2` 使用原件路径/哈希、白名单 JSON pointer 与精确值，
拒绝未 pin batch/引用、替换来源、标量类型变化、null 填零或失败改成功。
有限投影直接成为原 spec 的 context；研究任务解释单独标为推断，不改变 runtime schema。
旧 v1 保持可读并补引用集合闭合，不反向授予旧自由文本字段投影证明。

N2 的 `scripts/adaptive_research.py closeout` 与包入口 `--closeout` 只读核对 capture、事件、
预算、receipt、反馈、真实 userMessage echo、科学及进程退出，并分别报告
`OBSERVED / NOT_OBSERVED / CONFLICTING_EVIDENCE`。读取缺件不调用 `complete()`，
不补 response、receipt 或退出，不运行 reconcile。包入口在父进程 wait 后自动收尾，
审计目录在 task authority 外；输入库存前后核对，发布结果不进入自己的分母。
科学执行失败不会被升级为完成科学检查或完整链，PIT 早拒不会补记后续阶段。
正常模型 STOP 与完成全部检查后的决策预算停止分项报告；完整结果、实际反馈后决策及
独立交付退出齐全时，合法预算终止可保留已观察的完整链，仍不等于科学 PASS。

[验证目录](../../artifacts/adaptive-closure-20261018/)保留全部定向检查、独立退出、
旧 STOP 完成库存的 replay、新反例和各阶段 checkpoint。早期非完成库存的哈希漂移、
初始局部夹具/类型检查问题均保留为原失败，再由后继输出记录修复结果。
离线模拟证明程序接线；旧真实 STOP 只证明其原首次停止分支。
真实新提案、科学执行和本任务反馈后决策、修订、长期质量仍按原件逐项缺证，P14d-C 不变。

新包使用新的任务/输出根和全新预算；仅在用户批准具体包后方可运行。
建议上限为 SDK 决策 2、新候选 2、科学执行 2；retry、UNKNOWN 重发、科学 restart 均为 0。
实际政策报价、期限、宿主卷、独占 lease、5 GiB 完整增量、环境及外发范围均写入准备包，
启动前必须用既有守卫刷新，不从终态旧包转移余额。
