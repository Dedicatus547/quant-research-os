# 首轮五失败的后继只读归因（D02 / N1）

2026-10-12。原件来自主仓库 `artifacts/hosted-evidence/post-hm-discovery-01/`，后继小型证据位于当前 worktree 的 [diagnosis](../../artifacts/post-hm-next/diagnosis/)；没有修改父失败、源码或状态页，没有测试、模型调用、重训或科学重执行。本页是后继回顾性诊断，不是原执行时已生成的诊断或新科学资格。

复用指南2.3已核的最终机器报告身份 `b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be` 与五失败统计身份 `18f8ed033c3b67afd3b94af80ed3ef30aeedc17bb95488ac786a64266eceae4a`。必要补证是原生预测/标签逐日样本、常数机制及实际 purge 来源。没有复算首轮比较排名或完整 replay。

## 候选归因与最小动作

每行完整 candidate ID、表达式、execution identity、receipt/outcome/source hash、逐日分母、失败日期与原 completion 均保存在 [summary.json](../../artifacts/post-hm-next/diagnosis/summary.json) 引用的逐候选 JSON。

| 子任务前缀 / 表达式 | 原失败阶段 / code | IC NaN / Rank IC NaN（726日） | 有限配对预测常数日期 | 最小动作 |
|---|---|---:|---:|---|
| `26684cc4` / return(close,5) | Workflow / QLIB_EXECUTION_FAILED | 2 / 6 | 6 | 新 profile 表达完整日期与无定义统计；复用 native，不重训 |
| `4d91fc6c` / abs(close / mean(close,10)) | Workflow / QLIB_EXECUTION_FAILED | 0 / 12 | 12 | 同上；保留独立执行来源 |
| `9c011bc8` / std(close,10) | baseline-signal / SOURCE_INCOMPLETE | 无 native | 未知 | 保留缺证；恢复有限原异常或触发 instrument/date、score 与 status 后定向修复 |
| `a7ecf59f` / close / mean(close,10) | Workflow / QLIB_EXECUTION_FAILED | 0 / 12 | 12 | 同上；保留独立执行来源 |
| `d8f3df97` / abs(return(close,10)) | Workflow / QLIB_EXECUTION_FAILED | 0 / 72 | 72 | 同上 |

四份原生预测/标签各217,718行，原键唯一、顺序完全一致；有限配对217,486行。预测无 NaN/Inf，标签232个NaN、无Inf。逐日原行数298–300，有限配对296–300；日期完整覆盖固定日历的726日，没有缺日、重日或越界。标签有限配对没有常数日期。**每一个 Rank IC NaN 都由有限配对上的预测恰为常数解释；没有仍未知的非有限统计日期。** NaN 标签与常数机制分别记录，不把缺标签等同于样本不足。

return5 的常数日期为2024-02-19、02-20、09-27、09-30、10-08、10-09，其中前两日 IC 为NaN。其他候选完整失败日期见逐候选 `pair_summary`/`daily`。四份 native 预测按各自 split audit 核对hash；ratio10 与 abs(ratio10) 的 pred 原字节hash也相同（`ca112ca3d5d4a57bd38103b8fb0537c75423d8448b82792d5ee3d50dea1b348e`），IC/Rank IC身份已相同。各自候选和 execution 来源仍独立，没有合并历史科学执行或预算。

Qlib `calc_ic` 使用 pandas `corr`。常数输入下 return5 有4日、比值两个候选各12日、abs(return10) 有72日出现**原生 Pearson 有限，但数学上相关系数无定义**；逐日记录保留原值，并在异常日期通过相同 pandas 操作核对。此数值伪象不能用 `isfinite` 证明定义，也不能自动改原件。后继 profile 需分别保存 native 原值/finite、数学 definedness 和原因；新 IC 值在常数日须为空。严格旧出口拒绝NaN统计是充分可见的拒绝条件，但原 `STAGE_EXCEPTION` 没有保留 export 内层异常，本诊断不把静态分析伪装成当时捕获的异常。

## 信号阶段的缺证边界

[signal-static.json](../../artifacts/post-hm-next/diagnosis/signal-static.json) 对保留的153个PIT截面核对 mapping 与 tradability 日期覆盖，明确这是 sampled PIT 范围，不是重执行信号。45,900个PIT member/date键均有mapping；tradability原件1,596,969行中找到45,836个相应键，64键缺失，已存在键无晚于signal time的available_at。原 PIT 七类 gates 均PASS；来源文件与静态结果的hash另存。原失败只有 `SOURCE_INCOMPLETE`，没有可确定触发 instrument/date 或实际分数的有限异常；原 Workflow/native 不存在，不能追溯贴上后继 `SIGNAL_FINITE_WITHOUT_TRADABILITY` 标签。

缺失 tradability 只有在该键实际 score 有限时才触发相关分支。静态发现的缺口不能单独证明旧根因；不将缺证默认为可交易，不调用 Qlib 重算分数猜测首个触发键。

## 采用 purge 来源及 N2 前提

[origin.json](../../artifacts/post-hm-next/diagnosis/origin.json) 核对独立 `source-capsule-04/workspace` 的真实Git HEAD `3de5a5a33eb9a8d7d2235497dce2338cfd158670`、inventory hash与capsule一致，Workflow/model_split/result/signal/contract/lockfile关键字节与inventory一致。该独立仓库的源码不要求位于主仓同名Git树；未发现本范围内来源绑定错误。

四份 split audit 将各自 native 文件、request来源、workflow reservation resolved hash和固定完整日历绑定。源码确将 effective segments 传给实际 DatasetH，审计保留实际样本session/index hash：train为2015-01-05至2019-12-24（348,545行），valid为2020-01-02至2022-12-23（216,589行），test为2023-01-03至2025-12-30（217,718行）。train/valid各去尾5个交易日；一日forward label最后分别2019-12-25、2022-12-26，早于下一段起日2020-01-02、2023-01-03。没有采用source03未执行purge的旧模型预测，也没有重新构建train/valid帧；原sample audit保留其实际核对范围。

**四个 native 候选满足 N2 新语义设计的诊断前提；signal候选不满足。** 后继受控导入仍须独立核验 snapshot/view、signal/PIT、actual splits、native来源与键/日历；本诊断中的布尔值不授予导入资格。caller须显式冻结完整评价日期、各自覆盖要求、共同日期与敏感性口径，不能事后按优势选日或凭空设改善门槛。旧 ResearchResult、P14c 与原FAILED/NOT_EVALUATED保持各自原域；新证据不要求旧Result成功，也不称新PASS。

## 实际执行、恢复及限制

[read-plan.json](../../artifacts/post-hm-next/diagnosis/read-plan.json) 从开始持久化范围：native约18MB，单进程、有限输出20MiB，非重任务，没有把WSL free作为宿主余量。完成诊断wall 3.20秒、CPU 3.79秒、peak RSS247,944KiB。相同hash的pickle在成功尝试中只解析一次；独立已完成候选逐项写出。

诊断attempt1因 NumPy bool 的JSON序列化失败，真实退出1和日志保留；修复诊断序列化后attempt2真实退出0（[退出记录](../../artifacts/post-hm-next/diagnosis/attempt-02-exit.json)）。没有更改父失败。原science-job-05管理进程退出0仅表明管理批次完成；五个候选仍EXECUTION_FAILED，stage completion为FAILED/STAGE_EXCEPTION。没有为候选编造进程退出码。必要静态signal检查退出另存。

未知项：signal首个触发键与实际score、模型为何在这些日期映射为相同分数（未读取模型/feature重新训练）、旧export内层异常、未重建的train/valid帧及本次未完整重验数据/PIT。后继导入接口需承担独立准入核验，完整重跑五任务不由本诊断支持。
