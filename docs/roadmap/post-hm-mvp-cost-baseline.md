# O0：HM-MVP 已有成本基线

日期：2026-10-11。用途：为 T0 评估复用完整执行提供有限的历史成本事实。仅据现有纪律、复盘、开发观测及实施/恢复摘要整理；没有重跑、测试或解析科学大文件。不同范围的观测相互重叠，不能相加成项目总耗时或据此推算提速比例。

| 已有工作 | 记录值及实际范围 | 来源与限制 |
|---|---|---|
| 完整 CI | 1909 项；pytest 7794.013 秒，CI 总计 8240.512 秒（约 2小时17分） | [实施历史](../hosted/hm-implementation-history-2026-10-10.md)；特定冻结轮次的实际结果，不代表后续增量修改成本。复盘亦记录一轮失败 CI 的 pytest 8455.50 秒/15项失败。 |
| 106 场景接续批次 | 场景 53–84 共32项，42064.124 秒（约11小时41分） | [恢复历史](../hosted/hm-recovery-history-2026-10-10.md)；一个接续批次，不是全部106项总时长。另一轮复用旧66项后只新执行40项，摘要确认范围但未给出该40项单独耗时。 |
| 完整 live campaign | driver 5035.497 秒（约1小时24分）；正式调用8/8，独立诊断2次，CLI共10/10 | [恢复历史](../hosted/hm-recovery-history-2026-10-10.md)；仅该获批 campaign。耗时不等于纯模型时间；provider model identifier、HTTP内部重试/usage/费用不可见。科学 execution 均 SOFT_REJECT。 |
| 导出与 native 核验 | 一次导出跨度约3小时03分；随后 native 核验达到7200秒上限并失败。后继 native05 用时10027.288秒（约2小时47分） | [复盘](../hosted/hm-mvp-implementation-retrospective.md)、[开发观测](../hosted/hm-development-verification.md)、[实施历史](../hosted/hm-implementation-history-2026-10-10.md)；导出跨度含复制和核验，不能当作 CPU 时间。 |
| Q05 来源核验 | 244个 phase 根；predictions/labels 各41份，总计约2.46GB；一次观察时累计 CPU 约97分钟 | [实施历史](../hosted/hm-implementation-history-2026-10-10.md)、[恢复历史](../hosted/hm-recovery-history-2026-10-10.md)；谓词重复逐行解析并重建 label projection。该 CPU 观察不等于单个完整核验的墙钟时间。 |
| 完整安装扫描 | 一次约14.32秒 | [开发观测](../hosted/hm-development-verification.md)；相对完整 CI、矩阵和 Q05 观测较小；记录没有证明缓存安装哈希能显著减少主成本。 |

## 对 T0 的含义

已有证据显示，完整执行/验证的历史成本主要落在长矩阵、完整 CI、导出/native 以及 Q05 大结果重复解析。对固定 LGB 预测探索，先评估复用身份、依赖和来源均可核验的已有执行结果及 prediction/label 证据，避免为了新总体 commit 重跑完整流程；若依赖闭包或研究所需预测不存在/变化，再界定最小必要执行。现有材料没有给出“窄 profile”完成同一研究问题的实测成本，也没有完整执行与窄 profile 的可比基准，因此不能据此声称哪条路径必然更快。复用旧结果仍须核对其实际数据、配置、schema、环境及谓词适用范围。

重复解析的优先优化线索是同一次 Q05 核验内复用已读取并核验的确定性内容；历史材料没有可核验的解析次数、I/O 字节数、峰值内存或优化后节省值。上述未提供的逐阶段 CPU/wall time、实际读取字节、资源峰值、窄 profile 成本均为 unavailable。

## 证据与资源授权线索

来源仅为仓库内的 [实施纪律](../guides/implementation-discipline.md)、[HM-MVP 复盘](../hosted/hm-mvp-implementation-retrospective.md)、[开发验证观测](../hosted/hm-development-verification.md)、[实施历史](../hosted/hm-implementation-history-2026-10-10.md)与[恢复历史](../hosted/hm-recovery-history-2026-10-10.md)。正式结果应优先沿这些记录引用的 `artifacts/hosted-evidence` 原件和绑定退出核对；本摘要不替代原件或扩展原 proof tuple。历史 guard 曾使用任务专属配额与宿主卷底线，但本材料没有当前主机可用容量、并发 reservation 或 T9 新任务预算，均为 unavailable。过去 live campaign 的授权只适用于其绑定的固定路线和调用上限，不构成新研究生成、执行或外传授权。

## T9 执行前的实际复用范围

后继[依赖原件分析](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/dependency-reuse-analysis.json)只核对两个指定旧任务的小原件、AST、策略与源码bytes，未解析大预测文件。旧候选为DSL v2 `delta(close,2)`/`delta(close,3)`，本轮grammar不允许delta且仅开放window5/10/20；所有可准入新候选均与旧AST不同。旧预测还绑定旧expression/signal/resolved/recorder，不能改标为新任务结果。此缺失与总体commit变化无关。

相同hash的snapshot/view、冻结策略与已接受runtime设施可复用；`uv.lock`、Qlib Workflow、backtest service和data-qualified release的源码bytes相同，不重建或重复完整CI。新增候选需要各自一次完整PIT/signal、Qlib预测与导出/native audit，以及原workload规定的参数/成本/子期/复现/Validation；相同新候选共享执行，匹配的已完成checkpoint按原件核验复用。旧label hash相同不代表存在当前任务的合格import来源链，不套用旧audit。此分析不采用旧科学结论或授予新tuple资格。

## purge 修正的后继复用范围

后继发现原 Workflow 虽绑定 `purge_trading_days=5`，DatasetH 却使用未裁切区间。训练及验证末日标签分别依赖下一段首日；[切点诊断](../../artifacts/hosted-evidence/post-hm-discovery-01/purge-correction-01/diagnostic.json)明确受影响结论。新评价必须重新拟合模型并生成预测、IC和Rank IC，不能采用旧模型输出。

原03已独立完成15组信号及回测，其数学输入不受模型 purge 影响。[后继来源声明](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/source-adoption.json)列出可采用原件及 checkpoint；[源码差异](../../artifacts/hosted-evidence/post-hm-discovery-01/purged-evaluation-inputs-01/source-delta.json)核对原执行/验证函数 AST 与其余依赖原字节。新增 `adopt_verified` 仅导出后继身份引用和外置来源收据，保留原03科学输出，不声称新的回测执行。PIT 原件仍按现有来源谓词核对；缺失或受影响步骤继续执行。当前只声明可采用范围，不预报加速比例；最终实测和已采用数量以新阶段记录为准。

旧计划177+恢复18的预留原件保持195；实际启动4次任务尝试保守计入72，停用旧调度后新评价上限288，合计不超过360。未启动7任务的计划123不是实际消耗，也不称退款。[调度截止与对账](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/unpurged-evaluation-cutoff.json)。

## T9 后继执行的实测范围

源码04的10个候选均形成终态，批次 attempt 的 wall 为10,428.805790秒（约2小时54分），调用进程 CPU 为10,378.854340秒。该批次记录包括公共执行核验，结束于最终只读比较之前；阶段、任务与批次耗时互相覆盖，不能相加。子进程CPU、峰值资源、实际读取字节、人工投入和账单仍为 unavailable。[批次完成原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/batch-attempts/00000001/completion.json)。

后继终态receipt记账177单位，等于初始报价，没有使用额外恢复预留；加旧已启动工作的保守承诺72，共249，低于原360上限。预算单位不是实测秒数；旧195计划预留不作为实际消耗加入该数。15组旧signal/backtest全部实际采用，共30份外置收据：26份绑定第三个候选的最终结果，前两个失败候选各2份绑定已完成阶段。科学来源仍为03，后继身份引用为04；采用不称新的科学执行，原parent成功不作断言。

这轮5个完整链候选均被样本外阈值软拒绝，另5个执行失败。完整链任务各耗时约28–34分钟，但该观测包含模型、回测、复现、采用与核验，不能解释为纯训练成本。没有同口径未优化执行对照，因此不声称O1或来源采用节省了某个比例。生成及最终管理作业耗时另见[研究报告](post-hm-mvp-discovery-report.md)，不把重叠范围相加为项目总成本。

最终只读比较已导出；作业05管理总wall为11,252.084543秒，包含启动、完整批次和比较。实际退出0、guard清理核验成功，比较单独耗时未测。[管理完成](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-05/completion.json)；[guard退出](../../artifacts/hosted-evidence/storage-control/run-1791694245639316657-542636/exit.json)。该总范围与批次重叠，不能相加，也不能用两者的差代替比较的独立测量。
