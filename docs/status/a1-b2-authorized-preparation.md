# A1 / B2 完成状态

2026-10-13：本轮授权工作已完成。r10 A1两步工程闭环完成，B2完成结果复用；修复、集成准备、持久证据和使用说明已交付。用户已授权将本轮源码、测试及文档提交并推送到main；实际Git出口另行留存。

A1 campaign `876e2ecc…08079`，冻结来源 `401bf4af…`。两笔SDK均SUCCEEDED/ACCEPTED，第二请求绑定本轮第一真实trial及已核验原receipt。两轮离线Qlib科学实际exit0、原receipt核验完成，个体均 `SOFT_REJECT / SOFT_THRESHOLD_NOT_MET`。campaign终态COMPLETED/ALL_CANDIDATES_TERMINAL；科学汇总按冻结原报告为 `FAILED / NOT_EVALUATED`，选择阶段 `SOURCE_INCOMPLETE`、两候选均NONPASS_VALIDATION、无选中候选。工程完成不授研究、P14d-C、SDK Discovery或盈利资格。

控制器实际exit0（约4,413秒），外层守卫实际exit0且cleanup_verified=true；启动11:06:41Z、完成12:20:20Z，在原13:06:41Z截止前结束。仅收据对账ordinal1完成，SDK0、fresh execute BLOCKED、调用和科学预算计数不变。[实际结果与原件pins](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/actual-run-summary-01.json)。

本轮新增SDK2次、科学2次/36units；累计SDK **11/11**，A科学 **5次/90units**（含历史失败1次/18units），零重试、无failed resume、单科学worker。实际SDK输入19,665/24,129、输出134/196 tokens，观察总计input43,794/output330；不是计费或美元上限。A保留量收尾约1.394GB，低于累计4GiB；原2GiB预测、64MiB scratch、32GiB物理宿主卷底线保持。

V4实际prompt12,281B/23,942B，provider58,279B/84,579B，frame94,157B/136,664B，均在批准边界内。显式提示投影≤24KiB，捕获仍为provider256KiB/normalized64KiB/raw≤16KiB/frame512KiB；完整原请求、报告与科学verifier保留。原离线63个不同定向用例、legacy schema/reservation字节比较按原来源采用，未重跑科学或完整CI。本轮未运行类型检查，已有SDK typing限制仍保留。[开发证明](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-06/prompt-projection-development/README.md)。

B2不新增执行：原LLM3科学SOFT_REJECT，预测报告6来源、720共同日，LLM相对最佳基线无正观察增量。原崩溃有内存压力证据，准确根因未确证；恢复后的r9/r10科学已实际完成，见[原恢复报告](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-03/recovery-20261013-01/report.md)。

[本轮证据与用量](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/README.md)、[集成准备](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/integration-preparation/README.md)、[使用说明](../guides/sdk-campaign-offline.md)。原r9 cancelled/failed parent、原SDK失败和开发失败均保持原身份，[前次收尾](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-06/usage-01.md)不改写为成功。子agent复审为提案，不替代冻结科学权威。未购买/安装新包/采集/扩大外传/删除独有证据。本轮无待执行调用，不申请追加预算。
