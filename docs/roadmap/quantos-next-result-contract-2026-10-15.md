# 后继结果契约设计（2026-10-15）

**建议暂停新科学工作包及 Workflow/ResearchResult 成功语义改造。** 若有明确的下游读取需求，
最小后继是增加日历核算与原终态展示的只读比较报告；B 已授权的 retained reader 按自身范围推进，
本文不扩大其任务。本文是设计提案，未冻结新契约、实现接口或授予资格。

依据为共同基线 `d35a529086b55a732a6fcdca54f84077654df603` 的相关源码、
[工作区交接](../../artifacts/evolution-next-20261015/coord/setup.md)、
[R1c 最终交付](../../artifacts/evolution-implementation-20261014/runtime/r1c-comparison-final.md)、
[preparation](../../artifacts/field-study/adjusted-volume-relative5-20261014-01/recovery-20261015-01/preparation/preparation.json)
的日历/标签截止字段，以及 V/P Workflow 小型 completion 原件。采用此前数据/PIT/native 核验的原范围，
本次不重核 snapshot、内嵌库存或大预测文件。

## 1. 四种日期集合

设 E 为冻结测试区间内的完整预期交易日；C 为标签窗口在冻结数据日历内有日程支持的日期；
D(s,m) 为来源 s 的指标 m 数学定义且 native 复现通过的日期；I(m) 为固定比较各必需来源的 D 的交集。

| 集合 | 含义与 R1c 事实 | 使用边界 |
|---|---|---|
| E | 测试日 2023-01-03 至 2025-12-31，共 727 日 | 覆盖分母，尾日不删除；不等于底层完整数据日历（2717 日） |
| C | 标签 `Ref($close,-1)/$close-1`，horizon=1；最后支持日为 2025-12-30，故日程上支持 726 个测试日 | 仅表示未来交易日存在；不保证每只证券未来价格存在或标签有限，不能替代 E |
| D(s,Rank IC) | 有限配对至少 2，配对上的预测与标签均非常数，且 Qlib native Rank IC 精确复现为有限值；V=726 日，P=720 日 | IC 与 Rank IC 各自报告定义域；不能从有预测或有标签推断指标已定义 |
| I(Rank IC) | V/P 共同定义日 720 日 | 主均值在相同 I 上计算；各自 D 上均值仅作敏感性结果 |

C 由冻结完整日历 F、标签表达式和 horizon h 推导：对本次 close-to-close 标签，
`C={F[i]∈E : i+h<len(F)}`；不用观察到的收益筛选。
截止日期不是逐证券标签可用性的证明；缺失配对仍须保留计数和键摘要。
原覆盖条件继续为每来源 |D|/727 ≥ 90%，共同日 ≥ ceil(0.9×727)=655；请求分母仍为 V/P 两个请求。
缺源或拒绝来源不能变成单来源固定配对比较。不得因本轮结果降低门槛、反向解释信号、换窗口或扩候选。

## 2. 未定义统计与失败分别报告

沿用 [PredictionStatistic/PredictionDay](../../src/quantos/contracts/discovery_prediction.py) 和
[独立 native reader](../../src/quantos/application/discovery_prediction.py) 的原规则：

| 情况 | 保留与呈现 | 对比较/资格的影响 |
|---|---|---|
| 尾日缺未来标签 | 保留该日和原始预测/标签键；native NaN 标签仅从有限配对计算中省略，保留省略计数/键摘要；R1c 尾日统计为 null、`INSUFFICIENT_FINITE_PAIRS` | 仍计入 727；可另注“超出冻结标签窗口支持”，不得把该注释当作缺失价格的通用解释 |
| 常数预测或常数标签 | 沿用 `CONSTANT_PREDICTION` / `CONSTANT_LABEL`，数学值 null，native 状态/值另存；有足够配对仍不等于相关系数有定义 | 不填零，不删日；P 原六个常数预测日保持未定义 |
| 数据、PIT、来源或实际模型 split 核验失败 | 报来源硬拒绝及有界原因，保留原失败证据；独立导入使用 `SOURCE_VERIFICATION_REJECTED`，不伪造成逐日统计 null | 来源不准入但请求不移出分母；PIT 硬拒绝不降级为覆盖不足；不改原执行终态 |
| 预测非有限、标签 infinity、native 统计 infinity 或无法解释/复现的 NaN | 按原 reader 谓词拒绝，不用“统计未定义”掩盖损坏 | 不通过数据/PIT/统计完整性检查 |

有限域不变：JSON 的实际数值必须 finite，null 只在明确允许的字段配合状态/原因使用，
不能把 NaN/Infinity 数字写入 canonical JSON，也不能给 v1 ResearchResult 的必填 float 填 null。
原 native bytes 不改；已有 DQ 专用 NaN-label 投影还要求完整有限日统计，不能直接推广为 field-study 成功路径。

## 3. 三类完成不能互相替代

| 声明 | 必需条件 | 不足以支持该声明的观察 |
|---|---|---|
| 固定预测比较完成/AVAILABLE | 两个固定请求的来源、数据/PIT、split、native 指标核验通过；均达到原覆盖，I 达门槛；同标签域；不可变报告和实际退出/留证完整 | 一个来源可读、单来源均值、cohort 调用或进程 exit0 |
| 现有 Workflow 成功 | Qlib DatasetH/LGBModel、SignalRecord/SigAnaRecord 链及实际 split 核验完成；原必需汇总和导出的 ResearchResult 数值均有限；完整不可变 ResearchResult 可按原身份核验，成功 completion 与实际执行记录一致 | 训练结束、pred.pkl/label.pkl 存在、独立预测证据可用或比较 AVAILABLE |
| Validation 完成 | 按冻结 policy 运行 G0–G10，具备所需回测、参数/成本/子期间、复现与 OOS 等义务的证据；硬门拒绝时按既有规则有据短路；发布绑定输入的不可变 ValidationReport | Workflow 成功、仅有报告文件、局部 gate PASS 或独立比较通过 |

Validation 的 `SUCCEEDED / REJECT` 可以是完成的负向验证；失败尝试即使留有报告，
仍为 `FAILED / NOT_EVALUATED`。`PASS` 必须所有门通过。Workflow 成功也不代表整个科学请求成功。
规则来源：[Workflow](../../src/quantos/research/qlib/workflow.py)、
[ResearchResult 契约](../../src/quantos/contracts/research_result.py)与[导出/核验](../../src/quantos/research/qlib/result.py)、
[Workflow stage 绑定](../../src/quantos/application/autonomous_execution.py)、
[ValidationReport](../../src/quantos/contracts/validation.py)。

R1c 仅完成固定回顾性预测比较：V−P=`-0.0053130521577256385`。
原 V/P 均 `EXECUTION_FAILED / QLIB_EXECUTION_FAILED`，Workflow completion 均 FAILED；
无 ResearchResult/ValidationReport，未完成的稳健性/验证义务继续未评估。
小型 completion 只记录 `STAGE_EXCEPTION / UNCLASSIFIED`，本文不据此宣称已经证明唯一失败根因。
Validation/P14c 与资格判断保持；18+18=原36政策units，剩余科学机会0。
不作方法/机会增益、盈利或历史 vendor-vintage PIT 声明。

## 4. 需要新展示语义时的最小后继

建议候选版本为 **`prediction-evidence-comparison/v2`**，增加一个纯契约
`result-calendar-accounting/v1`。这是后继设计名，实施前须确认 B 已用名称/接口并冻结最终 schema；
不向 v1 原件追加字段，不移动旧 hash 域。`prediction-evidence/v1`、原 profile、规则和 ResearchResult v1 不变。

后继报告至少绑定原 report、preparation/profile、每来源 evidence manifest/内容及原 outcome/receipt、
Workflow completion 的精确引用；日历核算包含完整数据日历与 E 的各自身份、标签表达式/horizon/C/截止日、
逐来源逐指标 D、共同 I，以及原始/有限/NaN-label 计数和原因。新注释与原 `PredictionStatistic.reason` 并存。
comparison 状态、原 Workflow 状态、ResearchResult hash、ValidationReport hash 分字段展示；
无原报告就保持 hash=null/未评估，不伪造 ValidationReport 或成功终态。

最小影响面仅为新 contracts 模型、reader application 中的已留证输入适配与核算、CLI 的明确后继输出入口，
以及对应使用说明；复用现有 Qlib 统计和 retained evidence 来源采用机制，不增训练/回测实现。
新输出使用独立不可变目录；新 reader 有自己的源码/依赖/verifier 身份，旧证明保持 originating tuple。
来源采用仍须证明实际依赖和原核验范围可复用，文件名或总体 commit 不足以证明行为等价。

实施时最小检查范围（本轮不执行）：日历/日期排序唯一及集合关系、计数守恒、原727分母/655门槛、
共同均值算术、原 failure/null/两个请求保留、错误来源拒绝、版本分派和引用 hash/状态一致性。
使用小型构造与已有留证，不为新增展示重复训练、重建 PIT 或解析大预测文件。
contracts 继续只依赖纯契约设施；不改 Workflow/result builder、Validation gate、Registry、预算和机会账本。

若以后要求“允许原始未定义统计的 Workflow 也算成功”，必须另行设计 ResearchResult v2 及对应行/指标契约、
导出/核验器、执行 policy/请求身份与下游消费/验证支持；现有 finite v1 不兼容该要求。
不能只放宽 float 或把 FAILED 改为 SUCCEEDED。本文不选择该路线，也不为旧请求重新授予执行机会。

## 5. 是否启动下一工作包

**暂停新增科学与 ResearchResult v2 包。** 单次固定负向比较不足以支持新研究理由。
只读 reader 的复用/解释价值可以与科学效果分开评估，但实施新展示前仍缺：

- 明确的消费者及一个现有 v1 报告不能满足的使用场景；若现有报告加文档已足够，维持现状。
- B 实际 reader 交付的接口/来源采用边界，以及小型留证是否足以支撑上述日历解释；不为立项另跑一次比较。
- 受影响依赖、最小改动/检查清单及已有耗时记录支持的收益；当前基线 Pyright CI 失败是单独发布待办，不能写为已通过，也不据此追溯撤销旧证明。

未来任何科学执行另需独立于本次得分的新假设、预声明设计、明确授权/预算及真实资源依据。
本轮不启动 P2a、P14d-C 或新科学任务；不等待 B，也不以此设计产生后续自动执行队列。
