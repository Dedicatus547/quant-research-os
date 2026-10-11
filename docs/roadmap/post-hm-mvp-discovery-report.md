# 首轮探索性研究报告

日期：2026-10-11。研究问题是：在同一有界 DSL、固定数据与固定 LGBModel 下，LLM 提案相对模板和有限随机是否提供可核验的预测增量，以及代价是多少。

**本轮已完成。** 15个生成机会冻结为10个不同候选，全部形成终态；其中5个预测通过只读准入，5个执行失败。没有策略Validation PASS，也没有获得可分析的LLM预测增量证据。[最终机器报告](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/comparison/sha256-b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be/report.json)的SHA256为 `b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be`；[机器报告展示](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/comparison/sha256-b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be/report.md)保留全部15条机会记录。[实施状态](post-hm-mvp-implementation.md)。

## 设计和证据边界

主指标是固定 LGBModel prediction 的每日横截面 Rank IC 均值，方向为最大化。它不代表表达式本身的 IC 或组合收益。标签为 `Ref($close,-1)/$close-1`；参数、候选空间和指标在本轮生成前固定，生成不读取本轮评价反馈。

固定 snapshot 为 `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`，view 为 `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`。数据来源是 `SINGLE_SOURCE_NON_VINTAGE`，不能声称历史供应商版本 PIT。

后继模型切分按固定 view 的交易日历实际裁去 train、valid 各末尾5个交易日：train 截止2019-12-24，valid 截止2022-12-23，test 为2023-01-03–2025-12-30。DatasetH 实际样本索引和原生输出形成独立 split 审计，其 hash 绑定后继终态证据。冻结源码03此前只声明 purge 而未应用，旧模型输出不进入本报告的后继比较。

原生成 batch 为 `162b4ec5b5108be61d95ad19dc33191d09bdb73b8f34020465ff687580c8351a`。生成来自源码03；后继评价来自实际 clean commit `3de5a5a33eb9a8d7d2235497dce2338cfd158670`，由[独立评价声明](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/evaluation-declaration.json)绑定。切分修正在部分旧执行已被观察后发生，暴露追加已经留存；候选和指标不变，不追加生成。本轮整体属于回顾性探索，不能称独立确认。

## 完整生成分母

| 方法 | 固定机会 | 准入映射 | 重复映射 | 失败 | 方法内不同候选 |
|---|---:|---:|---:|---:|---:|
| LLM | 5 | 1 | 3 | 1 | 1 |
| TEMPLATE | 5 | 5 | 0 | 0 | 5 |
| RANDOM | 5 | 4 | 1 | 0 | 5 |

RANDOM 的重复是跨方法共享候选，本组仍产生5个不同候选。全批共有10个不同可执行候选，共享候选只执行一次；失败、重复与共享来源均保留在15个机会的分母中。重复不重抽，失败不补发。[冻结原件](../../artifacts/hosted-evidence/post-hm-discovery-01/generation/frozen.json)。

LLM 的剩余4次 Hosted 机会均成功捕获；加上首次网络失败，共用完5次机会。4个成功响应归一化后只有1个不同 AST。请求配置为 `gpt-6.1-sol/high`；配置不构成实际提供方模型、权重或思考等级的证明。

## 科学结果

执行失败不赋零、不排名；预测证据可分析、原策略 Validation verdict 和 P14c 可选择分别报告。不会以盈利作为工程接受标准，也没有为取得有效分数放宽冻结导出规则。下表列出全部10个不同候选；Rank IC来自最终机器报告，显示值四舍五入，精确值与全部来源hash保留在原件中。

| 来源 | 表达式 | 实际终态 | 可分析Rank IC | 原因 |
|---|---|---|---:|---|
| LLM | `close / rolling_mean(close,10)` | EXECUTION_FAILED / NOT_EVALUATED | 不可取得 | QLIB_EXECUTION_FAILED；Rank IC有12个NaN |
| TEMPLATE | `return(close,5)` | EXECUTION_FAILED / NOT_EVALUATED | 不可取得 | QLIB_EXECUTION_FAILED；IC有2个NaN，Rank IC有6个NaN |
| TEMPLATE、RANDOM共享 | `abs(return(close,5))` | SOFT_REJECT | −0.0172156801 | 仅G5样本外阈值未通过 |
| TEMPLATE | `return(close,10)` | SOFT_REJECT | 0.0070288491 | 仅G5样本外阈值未通过 |
| TEMPLATE | `abs(return(close,10))` | EXECUTION_FAILED / NOT_EVALUATED | 不可取得 | QLIB_EXECUTION_FAILED；Rank IC有72个NaN |
| TEMPLATE | `return(close,20)` | SOFT_REJECT | 0.0010046269 | 仅G5样本外阈值未通过 |
| RANDOM | `rolling_std(close,10)` | EXECUTION_FAILED / NOT_EVALUATED | 不可取得 | SOURCE_INCOMPLETE，baseline-signal阶段；未执行模型 |
| RANDOM | `rank(close,20)` | SOFT_REJECT | −0.0033332782 | 仅G5样本外阈值未通过 |
| RANDOM | `abs(close / rolling_mean(close,10))` | EXECUTION_FAILED / NOT_EVALUATED | 不可取得 | QLIB_EXECUTION_FAILED；Rank IC有12个NaN |
| RANDOM | `close / rolling_mean(close,20)` | SOFT_REJECT | 0.0209819185 | 仅G5样本外阈值未通过 |

五个完整链结果的 Validation 均为 `run_status=SUCCEEDED`、`verdict=REJECT`，只有G5软拒绝，其余门通过。`rank(close,20)` 是时间窗口rank，与主指标的横截面Rank IC不是同一概念。失败候选没有合格ResearchResult或Validation，不将缺失结果赋零，也不使用Qlib跳过NaN的summary。四个Qlib失败的原生统计各有726行；NaN计数仅用于解释原导出拒绝，不作为比较分数。[五个失败的只读诊断和原件hash](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-05/all-failed-native-statistic-counts.json)。

五个可分析预测均核验实际5交易日purge、数据/PIT来源、prediction/label键与完整726交易日覆盖、原生统计及label export audit。每个结果有217,486个有限预测/标签对；原生217,718对中232个NaN标签按原冻结审计规则明确省略，没有新增填补规则。全部P14c状态仍为未评价，没有调用选择服务。

| 方法 | 可分析的不同候选 | 本轮最佳观测Rank IC | 策略Validation PASS |
|---|---:|---:|---:|
| LLM | 0 | 不可取得 | 0 |
| TEMPLATE | 3 | 0.0070288491 | 0 |
| RANDOM | 3 | 0.0209819185 | 0 |

模板与随机各3个中包含同一共享候选，全批实际只有5个可分析预测。随机组的最佳观测值较高，但样本小、存在共享候选且属于回顾性探索，这不是方法优越性或经济优势证明。LLM组只有一个不同候选且执行失败，本轮不能估计其有效预测增量；不能把不可取得的分数理解为零。完整提供方费用和工程/人工成本未知，也无法给出可靠的单位总成本优势。本轮交付的是可核验的探索结果与失败证据。

## 成本

4个成功 CLI 捕获观测到 input 65,792 tokens、output 1,144 tokens，另外单列 reasoning 511，cache 0。reasoning 不与 output 相加，原事件未证明两类计数的重叠或计费语义。首次失败 usage 不可取得；提供方内部调用次数、实际账单和完整费用未知。5个生成 launcher 的 wall time 合计146.459583秒，成功部分128.409516秒。[生成观测原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/generation-observations.json)。这些值不是提供方认证的总成本。

后继终态receipt记账177单位，旧已启动工作的保守计算承诺72单位，共249，不超过原360上限；后继评价单独上限288，没有使用额外恢复预留。旧计划与恢复预留195单位不称实际支出或退款；预算单位不是实测秒数。[预算和调度截止](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/unpurged-evaluation-cutoff.json)。

15组旧信号/回测全部实际采用，共30份采用收据。第三个候选26份绑定其最终Result/receipt，前两个失败候选各2份绑定已完成阶段；原parent成功不作断言。保持原03科学来源，仅更新后继04身份引用。旧模型预测不采用；独立复现实际重新执行。不得将采用称为新的科学执行或把重复方法行的共享成本相加。[来源声明](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/source-adoption.json)；[成本基线与限制](post-hm-mvp-cost-baseline.md)。

后继批次实测wall为10,428.805790秒（约2小时54分），调用进程CPU为10,378.854340秒，涵盖公共执行核验，结束于最终比较之前。[批次完成原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/batch-attempts/00000001/completion.json)。五个完整链任务各约28–34分钟，第三个任务wall为1,703.440656秒、CPU为1,698.056858秒；这包含来源采用、模型、复现与全链核验，不是纯训练耗时。阶段、任务和批次耗时互相覆盖，不能相加；子进程CPU、资源峰值、读写字节、人工投入与账单未知。

科学管理作业05含启动、完整执行与最终比较的wall为11,252.084543秒（约3小时8分）。namespace进程实际退出0，管理状态COMPLETED，guard实际退出0并核验清理；这些是作业完成事实，不表示科学PASS。比较阶段单独耗时未测，不用管理总耗时减批次耗时冒充该测量，也不把管理总耗时与批次相加。[实际退出](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-05/process-exit.json)；[管理完成](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-05/completion.json)；[guard退出与清理](../../artifacts/hosted-evidence/storage-control/run-1791694245639316657-542636/exit.json)。

纠错成本同样留在原件中：科学管理作业02实际退出1、wall 0.029542秒，尚未启动科学；作业03实际退出1、wall 156.554365秒，已有独立信号/回测但因MLflow路径失败；作业04的namespace实际退出−15、wall 1,496.813465秒，停止于purge纠正。作业01在prelaunch前失败，完整执行耗时不可取得。这些是各管理作业的观测范围，不作为新评价成本，也不与其内部任务/阶段观测相加。[作业02](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-02/completion.json)；[作业03](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-03/completion.json)；[作业04](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-04/completion.json)。

## 工程交付和保留范围

冻结前请求、原始响应、失败和重复映射、受限准入、singleton冻结、预算执行、阶段checkpoint、显式恢复、预测原件核验及报告入口已经实现。开发检查限于必要静态和接口检查，未运行新增测试、完整CI或完整HM资格矩阵；本轮实际科学执行及SDK有界P10另按各自原件记录，不能把实现称为整套新HM/SDK资格。

FR-03 官方 SDK 0.162.1 的独立有界调查已结束：account/read 预检通过，P10 为7/9、`NO_GO`，未进入P13；canonical pin 保持原值。这不阻止本次已授权 Hosted 路线。[FR-03 记录](post-hm-mvp-fr03-investigation.md)。

没有访问 sealed confirmation、调用 P14c 或更改 Registry。正式预测选择、多字段、多窗口、自适应反馈及全局 LLM 执行权限属于研究指南的后继触发项，不属于本轮完成条件。历史03原件回放使用原03冻结代码；后继 adapter 只接受其新 policy 域，不给历史 receipt 追溯增加切分门禁。

本轮T0–T9、O0/O1及F0/F1有界任务已结束，没有必须由用户提供的输入、授权或操作。SDK正式资格仍未取得，需未来官方候选或实质修复触发独立工作；本轮没有重试P10、进入P13或切换SDK。
