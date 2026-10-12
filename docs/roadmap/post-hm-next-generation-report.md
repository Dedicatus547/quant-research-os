# 后继 Discovery 第二轮生成分析

日期：2026-10-12。D10/A 已完成；本报告只汇总冻结生成分析，不包含科学评价。

## 来源与身份

正式 report：`/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/analysis/generation-analysis/sha256-58359df633fafb477635df3a13637faad4c7eb71d2906af16a43de97256383c5/report.json`，实读字节 SHA256 为 `58359df633fafb477635df3a13637faad4c7eb71d2906af16a43de97256383c5`（25,115 bytes）。冻结 wrapper SHA256 为 `82159f9a25910f48a0f83b6184d8eea47aaafa0341125f012b25d38ba6563433`。handoff 绑定的 source capsule 原件位于 `/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/source-capsule-01/capsule.json`，实读 SHA256 为 `40c53ca5b09e014071862d1171af6068b5bd353b7702323d23271cf92e952ed8`（875 bytes）。capsule 同时声明 `actual_commit=123109e4b99500f2917b3596252d2bf964a2c76a`、`lockfile_hash=0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca`、`source_inventory_hash=b427afe3256ae435ddb364929c0752bef5e9a6a7ccae48e6bb3430233a3bd3fe`。其中 commit 是 capsule 内的 Git 身份字段；`40c53c…` 是 capsule 文件自身的字节 SHA256，两者口径不同。

## 生成观察

三组各获授并占用 5 个机会，15/15；静态能力准入均为 5/5（100%）。各方法内结构重复均为 0；冻结 grammar 下共 12 个不同结构，模板与随机基线 union 为 9，LLM 比 union 多 3 个。LLM 的 5 次管理入口均确认，未知槽位 0，可观察重试 0；提供方内部调用数为 null。模板与随机是离线基线，不产生模型入口。静态准入和结构多样性不表示预测可分析或科学质量。

LLM 管理入口 wall time 为 145.802448 秒；完整管理 job wall time 为 461.456204 秒，后者包含前者，不能相加。usage、费用未知；LLM 的模型 identifier 实际记录为 null。Sol/high 等模型配置是请求/派发配置，不能据此声称服务端实际模型身份或配置。

本轮五个 LLM 结果与首轮记录的 LLM 一个不同 AST 有描述差异；单凭这两轮描述不能把差异归因于历史政策，也不能宣称顺序方法具有优势。该结构空间有限（共 30 个结构），可直接枚举；方法内不重复本身不足以证明经济假设独立或更优。

## 评价边界与后续材料

本次只完成生成分析。科学执行状态为 `NOT_OBSERVED`，质量增量 `NOT_EVALUATED`；预测质量、收益、Validation 和 P14c 均未评估且不改变既有结论。本报告不引入盈利作为工程接受标准。

事实性投入建议：本轮相对基线 union 多产生 3 个不同静态结构，但未测质量增量，暂不扩大同类模型调用。若考虑进入科学阶段，先明确质量改善幅度、可接受额外成本、覆盖参数与科学执行上限，并取得独立后继评价授权；之后只读采用本批 proposal 原件，未知费用仍需在决策中保留。当前 A 的 `max_compute_units=1` 是不可改写的 A-only 冻结约束。未来 B 若获明确授权，须采用新的评价 authority/版本和独立预算，只读采用本批 proposal 原件；不得抬高原 cap、改变本批冻结或重发 LLM。

自动审批历史中保留两次拒绝；具体目的地授权后第三次获准，本次同范围汇总沿用既有授权。失败数 0、恢复数 0；guard exit 0 且 cleanup verified。汇总代理仅读取指定小型 report、handoff 与必要来源 capsule 字节身份，未额外调用研究模型、执行科学任务、测试或解析大文件；五次真实研究调用属于前述执行阶段。
