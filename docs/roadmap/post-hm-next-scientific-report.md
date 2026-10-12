# 后继 Discovery 第二轮科学结果与投入报告

日期：2026-10-12。D10/B 最终比较报告。比较为基于既有候选和冻结来源的后继探索性分析；不是新的独立确认试验。

## 决策结果

12个不同候选结构来自15个已占用生成机会，每方法5个机会。共同评价日有708天（预期726天；冻结门槛为至少600天），候选coverage门槛为至少90%。9个候选通过coverage准入，3个来源缺失。LLM可比较5/5个机会、RANDOM为4/5、TEMPLATE为3/5。

主指标的LLM最高共同日 Rank IC 均值为 `0.02269698340587893`，与RANDOM并列；TEMPLATE为 `-0.007293875871142516`。LLM相对最佳基线增量为 `0.0`，低于预声明的 `0.002` 有意义增量。LLM入口耗时145.802448秒，低于300秒门槛；新科学管理耗时4084.5129645秒，低于14400秒门槛。金额费用未知，不能据此主张成本优势。

按照冻结政策与比较报告的结论，本空间的投入建议为 **`PAUSE_EXPANDING_LLM_GENERATION_IN_THIS_SPACE`**。这表示暂停在当前受限空间扩大同类LLM生成；不推出LLM普遍无效，也不是确认性结论、Registry/策略晋级或盈利判断。主指标的可比性与冻结停止门槛支持此项限定建议。

## 生成与科学结果分母

| 口径 | 观测 | 解释 |
|---|---:|---|
| 生成机会 | 15/15 | LLM、RANDOM、TEMPLATE 各5；失败、重复仍占原机会 |
| 全局不同结构 | 12 | 完整候选分母 |
| LLM每方法不同结构 | 5 | 其中两项与其他方法结构重复，按同一候选记录 |
| 基线结构并集 | 9 | LLM相对基线并集增加3个结构；不代表质量增量 |
| 后继统计coverage准入 | 9/12 | 满足冻结候选覆盖要求 |
| `SOURCE_MISSING` | 3/12 | 保留空统计；不得填零或改写为新成功 |
| 原科学裁决 | 6 `SOFT_REJECT`，6 `EXECUTION_FAILED` | Validation 与 P14c 历史状态不变 |
| 新科学执行来源 | 4 | 两个 `SOFT_REJECT`、两个 `EXECUTION_FAILED / SOURCE_INCOMPLETE`，后者触发 `SIGNAL_FINITE_WITHOUT_TRADABILITY` |
| 只读复用历史来源 | 8 | 旧来源不新增训练或receipt；旧 `std10` 根因仍 `UNKNOWN` |
| 新策略 Validation PASS | 0 | 科学执行阶段没有PASS；统计可比较不改变原裁决 |

比较机器报告中的 `science_count_scope.new.attempt_count` 和 resume count 保持 `null`，因为其请求绑定观察范围没有报告完整attempt/recovery数。独立管理观测记录4个新任务attempt、global resume 0。两者是不同统计范围，本文不把管理值写回机器报告字段。

## 全部12个候选

`target`列为比较报告 `target_subtask_hash` 前12位；完整身份及各来源hash见正式机器报告。方法括号注明同一结构在另一方法机会中的重复归属。覆盖是有效日期数/726及其比例。`common` 是708共同日期主指标，`own` 是各候选自身定义日期均值的敏感性结果；二者不可互换。

| Target 前缀 | 方法归属 | Coverage | Common Rank IC | Own-date均值 | 原科学裁决 | 来源 |
|---|---|---:|---:|---:|---|---|
| `292de06c057d` | RANDOM（LLM重复） | 726/726 (100.000%) | 0.0215765208 | 0.0209819185 | SOFT_REJECT | old |
| `2c8425816c9e` | LLM | 726/726 (100.000%) | -0.0136615217 | -0.0127666456 | SOFT_REJECT | new |
| `39986dfb1990` | RANDOM | 714/726 (98.347%) | 0.0226969834 | 0.0233996355 | EXECUTION_FAILED / QLIB_EXECUTION_FAILED | old |
| `50ab7ccfa266` | LLM | 726/726 (100.000%) | 0.0005645084 | 0.0010046269 | SOFT_REJECT | old |
| `544dac19ad8d` | TEMPLATE | 726/726 (100.000%) | -0.0103394474 | -0.0092763334 | SOFT_REJECT | new |
| `75cc110bc009` | TEMPLATE | SOURCE_MISSING | — | — | EXECUTION_FAILED / SOURCE_INCOMPLETE | new |
| `770d62e51325` | RANDOM | SOURCE_MISSING | — | — | EXECUTION_FAILED / SOURCE_INCOMPLETE | old; `std10`根因UNKNOWN |
| `a5c836f9a81f` | LLM | 714/726 (98.347%) | 0.0226969834 | 0.0233996355 | EXECUTION_FAILED / QLIB_EXECUTION_FAILED | old |
| `b1293d8994f2` | TEMPLATE（LLM重复） | 720/726 (99.174%) | -0.0072938759 | -0.0074628844 | EXECUTION_FAILED / QLIB_EXECUTION_FAILED | old |
| `bd956c643e5b` | TEMPLATE | SOURCE_MISSING | — | — | EXECUTION_FAILED / SOURCE_INCOMPLETE | new |
| `f797c675b431` | TEMPLATE（RANDOM重复） | 726/726 (100.000%) | -0.0177207166 | -0.0172156801 | SOFT_REJECT | old |
| `ff8efad30960` | RANDOM | 726/726 (100.000%) | -0.0047650271 | -0.0033332782 | SOFT_REJECT | old |

这张表保留12项原科学裁决：coverage后继证据没有把失败候选追认为科学执行成功，也没有修改Validation/P14c。尤其旧 `std10` 的来源缺失仍为空，不能从两项新 `SIGNAL_FINITE_WITHOUT_TRADABILITY` 失败推断旧根因。

## 方法比较与成本

| 方法 | 机会 | 可比较预测 | 最高共同日 Rank IC 均值 |
|---|---:|---:|---:|
| LLM | 5 | 5 | 0.0226969834 |
| RANDOM | 5 | 4 | 0.0226969834 |
| TEMPLATE | 5 | 3 | -0.0072938759 |

LLM与最佳基线差值为0.0，低于冻结的0.002实质差异门槛。五次LLM入口wall为145.802448秒（冻结上限300秒）；新科学管理wall为4084.5129645秒（冻结上限14400秒）。二者是不同管理范围，不与其他流程时间相加。服务端实际模型身份、provider内部调用/重试和金额费用仍未知；不得把管理入口数、预算compute units或wall time当作账单。

Import-02 entrypoint wall为1093.342528秒、CPU为1101.119256秒、peak RSS为1,400,348 KiB；Compare-03 entrypoint wall为1108.463955秒、CPU为1115.604906秒、peak RSS为1,384,596 KiB。这些只描述各自进程，不是host峰值，也不与科学执行或生成管理耗时相加。生成管理job wall为461.456204秒，包含LLM入口wall 145.802448秒；两者不可相加。

统计02曾因实际 guard 退出 `-15`、`STORAGE_ESTIMATE_EXCEEDED` 中断，cleanup已核实为true，未产生producer terminal。约12分钟是该次观测时的经过时间，不是已确认的实际wall，故不伪造耗时。统计03使用原2 GiB组件包络/总6 GiB预算，复用了已完成import，未改变9项来源、verifier或coverage准入结果。此次中断不覆盖、不改写原失败证据。

## 科学计数与解释边界

比较机器报告将科学 `attempt_count` 与 `resume_count` 留作 `null`；它们只统计报告自身的请求绑定证据范围。管理层独立观察到4个新任务attempt、0 global resume。本文并列说明两个口径，不把管理层统计反写为机器报告中的科学字段，也不把prepare/import/compare管理失败算作科学attempt。科学新任务预算初始预留72 compute units、cap 90、科学任务resume 0；统计比较中断后的统计工作resume计数为1，属于不同管理范围。

本结果支持按冻结规则暂停扩大当前空间的同类LLM生成。有限结构空间中与基线的共同日最高值并列且未达到预声明增量门槛，当前没有质量增量理由支持扩大投入；这不构成LLM一般能力评估。策略裁决、P14c、sealed confirmation、Registry权限和工程验收保持各自边界，均不由这份探索性报告改写。

## 来源与身份

- 正式比较报告：[report.json](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/prediction-comparison-03/sha256-0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0/report.json)；文件名所示SHA256为 `0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0`，并与原始字节校验一致。
- 报告绑定 cohort-02 `d518a9f4c5d3eed56fe3ecce575efc133c8d828bb55e34ed82b3b665a5be8e7b`、repair `939a6b12450ae1eff643b882d9e5368ec6e26beda245b721b7381fa95e355856` 及比较policy `a49f6862c349167cdb0504b48015f770688ea6a6cfb17bfbca3a86a6b7a28a60`。Repair只更新verifier身份与profile hash，原来源、评价日期、分母和科学参数未变。
- 后继统计source commit `1657c2286f3bcfbcb1bb5e0b5d40ced56557d8dd`；[statistics source capsule](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/statistics-source-capsule-01/capsule.json) SHA256 `5740dcd872ea4afeb5b57ff0cb75028a6e7169678255feaf5fed4374dcce24b9`。原科学commit仍为 `33b0ed0463a9154c33bbbd7073eb1afb1c1743f6`。
- [正式管理final handoff](/home/zjw/quant-research-os/.worktrees/mainline/artifacts/post-hm-next/science-02/management/final-handoff.json)，SHA256 `f938bbd252261f176533855f75a363c7f1db08275c86e00be2b86c9935e2b85b`；[独立main review](/home/zjw/quant-research-os/.worktrees/mainline/artifacts/post-hm-next/science-02/main-review.json)，SHA256 `b39320b777247b8bc7a884fbb5537e8ca048ef532eb43af7aa3dc72887329e01`。Review核对小型原件身份与绑定，没有第二次raw解析。
- Compare-03三层退出：[guard exit](/home/zjw/quant-research-os/artifacts/hosted-evidence/storage-control/run-1791789240303385805-768922/exit.json)（实际0，cleanup、waitpid及namespace exit均确认；SHA256 `b2bdaa044c33880b2dfa46d1bc6c9b3c09d8996626440ed20a2623bd0bcc0429`）、[observer exit](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/prediction-compare-observer-03/process-exit.json)（实际0；SHA256 `530a76cde922eec693940eb3e7b9471574e0dafef41b4b7531925e431c4ddc64`）、[producer completion](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/prediction-compare-job-03/completion.json)（entrypoint 0；SHA256 `0dba7b112253e3ff2841f7f446acac70a5de13a11d98aaa55e09173d51aabc74`）。
- 本次汇总读取正式比较报告、小型handoff/review与退出/完成原件；没有第二次解析raw预测或label、重新读取大型metrics，也没有展开数百日的 `common_dates` 数组。科学比较本身的输入处理由正式producer完成，摘要读取范围不表示科学评价未读取相关输入。
- [D10/A生成分析报告](post-hm-next-generation-report.md)记录完整generation manager wall 461.456204秒，其中包含五次LLM入口wall 145.802448秒；不能相加。此scope对应的[生成正式报告](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-discovery-02/analysis/generation-analysis/sha256-58359df633fafb477635df3a13637faad4c7eb71d2906af16a43de97256383c5/report.json)保持独立引用。
