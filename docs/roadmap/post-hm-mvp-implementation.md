# 首轮实施记录

日期：2026-10-11。任务与边界沿用[执行计划](post-hm-mvp-execution-plan.md)和[研究指南](post-hm-mvp-research.md)。本页记录实际差异，不授予旧资格，也不把实现当作已完成研究。

完整生成分母、科学结果、失败、成本和限制见[首轮探索性研究报告](post-hm-mvp-discovery-report.md)。本轮T0–T9、O0/O1及F0/F1有界任务已结束，没有必须由用户操作的待办。

**当前状态：后继科学作业05和最终比较已完成。** 源码04对原10个候选评价得到5个SOFT_REJECT、5个EXECUTION_FAILED；5个预测通过只读比较准入，策略Validation PASS为0。报告SHA256为 `b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be`。[最终报告原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/comparison/sha256-b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be/report.json)；[管理完成](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-05/completion.json)；[guard实际退出0及清理](../../artifacts/hosted-evidence/storage-control/run-1791694245639316657-542636/exit.json)。管理完成不代表科学PASS，SDK资格仍为NO_GO。

旧科学作业04已安全停止：实际 namespace 子进程退出为 −15，controller/supervisor 退出为1，既有 supervisor 已核验清理。冻结源码03声明 purge 5 trading days，却未裁去 train/valid 的末尾样本；旧预测、失败、receipt 和 flags 保留原义，不能作为已实施 purge 的比较结果。[停止、预算与来源截止原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/unpurged-evaluation-cutoff.json)（SHA256 `c667c6340dcfc0e568941fef2a0cebbdd346c407c6de0dfbba088c66c7bc9b8c`）。

后继终态记账177单位，加旧已启动工作的保守承诺72为249，不超过原360上限；后继上限288。旧初始预留177与恢复预留18合计195继续留存，不称实际支出或退款。其中7个从未启动任务的旧计划为123单位。后继使用新实际评价代码与声明，完成原10个候选评价；下文保留旧阶段记录与当时状态。

## T0：先固定问题与路径

改动是冻结前有界生成、候选映射、合法单候选子任务、阶段恢复与只读预测比较；复用原 Parquet snapshot、Qlib view、DSL、枚举、Governor、Workflow、Record Templates、Exchange/Simulator、Validation 和 receipt。只新增首轮需要的管理入口与记录，不建设通用 AST campaign、预测专用执行器或新选择体系。

选择 `singleton-full-chain/v1`：比较批次引用每个合法的 singleton family/template/manifest，完整执行仍承担原 workload policy。历史完整 CI/矩阵与导出成本不能等同于单候选执行成本；没有同口径窄 profile 实测值，故先减少改造，并独立交付同次核验去重。[成本依据](post-hm-mvp-cost-baseline.md)

| 设计项 | 首轮决定 |
|---|---|
| 研究对象 | 单表达式特征进入固定 LGBModel 后的 prediction，不是原始因子或组合收益 |
| 主指标/方向 | Qlib `Rank IC`，每日横截面 Rank IC 的均值，最大化；缺失或不可准入结果不赋零、不排名 |
| snapshot | `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` |
| view | `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` |
| 标签 | `Ref($close,-1)/$close-1`；沿用原 label/PIT 语义，不作收益桥接 |
| train / valid / test | 2015-01-01–2019-12-31 / 2020-01-01–2022-12-31 / 2023-01-01–2025-12-30 |
| 模型/处理 | 现有 DatasetH/DataHandlerLP/QlibDataLoader、DropnaLabel；MSE、learning_rate 0.05、depth 3、leaves 7、seed 1729、threads 1、100 rounds、early stopping 20；purge 5 trading days |
| 共同候选空间 | DSL v2；adjusted_close；一个 return/rolling_mean/rolling_std/时间窗口 rank 节点；window ∈ {5,10,20}；可加 abs，或对 rolling_mean 加 divide(close,mean)，最多4节点；不添加其它字段/算子 |
| 对照 | 固定顺序模板、seed 1729 有限随机、LLM；三组共用 grammar、输入、机会及准入规则，随机重复不重抽 |
| 可见信息 | 冻结设计、DSL/grammar、明确的上下文原件及其 hash；不给本轮评价反馈；仅声明实际冻结 request 中的 input/context |
| 暴露 | 上述窗口已有历史研究消费；本会话知道历史两候选软拒绝。全部按回顾性探索解释，不称独立确认；2026 confirmation 槽沿用声明、禁止访问 |
| 模型生成建议 | `gpt-6.1-sol / high`，每个请求一次尝试，最多5次生成；配置与真实 provider 身份分别记录，外部权重快照未知 |
| 预算 | 用户同意采用建议并适当放宽：每组5次尝试，共15次；无效、重复、修订、中断占机会，不自动补足；最多360确定性工作量单位，执行报价后再核对实际资源 |
| 实际成本 | 全链 wall/CPU、生成调用/usage、重复与恢复分别记录；费用、峰值、人工未知时标 unavailable；确定性单位不是秒 |

共享候选只执行一次，保留各方法的生成来源、重复分母和共享成本归属。主指标在生成前固定，结果不反向用于本轮改候选。预测证据准入、完整策略 Validation PASS 和 P14c 可选择分别呈现；不调用 P14c、Registry 或 confirmation。源仍为 `SINGLE_SOURCE_NON_VINTAGE`。

实际管理输入必须绑定完成实现的 clean code provenance 和当前 lockfile，不能把原 C15 commit 当成新代码已运行。历史接受证明保留原 originating tuple；只在实际依赖可核对的范围采用。

## T1：单向身份和所有权

`DiscoveryDesign → GenerationRequest → durable reservation → captured response/producer originals → ProposalMapping → DiscoveryBatch → singleton subtask → campaign/request/receipt → comparison report`。

生成请求没有未来 campaign 字段。解析失败不需要 AST hash；重复和修订各有原始 reservation/response。batch 在评价前一次冻结，使用原 singleton 枚举，不伪装为跨结构旧 manifest。AST 的静态能力准入不授予 PIT PASS。

后继公共契约集中于 `contracts/discovery.py`，没有 Tushare/Qlib/harness/LLM SDK 依赖；生成、准入、基线、执行、比较、展示各用独立 application 模块。`scripts/post_hm_discovery.py` 是管理侧显式入口；旧 Hosted loader/profile 不自动接受它。

## 当前进度

| 任务 | 实际交付 | 范围与限制 |
|---|---|---|
| T0/T1 | 上述研究设计及 `contracts/discovery.py` 的单向身份 | 生成绑定原03源码；后继评价声明绑定实际04源码，管理脚本另有独立身份 |
| T2/T3 | 原始响应、reservation、失败和修订持久留存；SDK 原件绑定；同一 grammar 准入、结构去重、singleton 冻结及原件复读核验 | SDK 捕获不授入口资格；Hosted 已接通管理侧单次捕获与原件核验 |
| T4 | Governor/full-chain 执行、批次预算、阶段 checkpoint 与原件恢复；失败receipt保留；split hash绑定新终态并核验 | 作业04停止保留；作业05全部10候选终态，没有重试终态实验；30份采用receipt保持原03科学来源 |
| T5 | 固定顺序模板与seed 1729有限随机；各5次机会已冻结并评价，重复不重抽 | 两组各3个可分析的不同预测，其中一个共享；全部重复、失败分母保留 |
| T6/T7 | 完成只读预测准入、Rank IC比较、原gates与全部15个机会、成本及报告导出 | 5个预测可分析，策略Validation PASS为0，P14c未评价；没有独立确认或方法优越性结论 |
| T8 | `scripts/post_hm_discovery.py` 管理侧接线；独立 `hm-discovery/v1` Hosted 请求、投影与开发来源校验 | 已采用原接受组件的 runtime/isolation 范围；新 source receipt 不授整套 HM 或 SDK 资格 |
| T9 | 15机会、10不同候选全部评价；5个SOFT_REJECT、5个执行失败；最终purged比较已交付 | LLM可分析数0，不能估计其预测增量；新177+旧保守72=249≤360，不追加生成 |
| O0/O1 | 有限成本基线与实际wall/CPU；同次结果核验复用小型已核事实，每次仍核实际文件集合/哈希 | 无同口径性能对照，不承诺加速比例；未知成本保留unavailable |
| F0/F1 | 发现官方 0.162.1，独立保留 wheel/executable/provenance 与准备失败/退出 | 0.162.1 account/read 一次 PASS；唯一 P10 7/9 NO_GO，未进入P13；canonical pin 不变 |

开发检查限于必要静态接口、格式和strict类型检查，未新增/运行测试、完整CI、原HM故障矩阵或原HM科学全量验收。本轮T9实际执行10个候选，F1实际执行一次有界P10，各有独立原件；没有把历史CI/矩阵或旧Hosted接受改标为新代码PASS。用户没有要求测试，沿用实施纪律的开发验证范围。

## 管理入口与恢复

入口为 `.venv/bin/python scripts/post_hm_discovery.py --generation-root <持久目录> <command>`，所有 contract 输入必须是 canonical JSON。`prepare` 绑定 design 与三方法 request；`baselines` 消费单个 baseline request；`reserve` 在外部交接前占机会；`capture` 留存 response；`freeze` 在任何评价前一次冻结全部当前分母。冻结后禁止补写生成。

SDK capture 使用 `--agent-run`、`--agent-run-spec`、`--normalized-transcript`、`--execution-request`、`--model-configuration` 原件，逐项绑定设计、request 和具体 reservation，单次尝试、原事件、最终消息、usage 及 Safe DSL 输出。原件读取超限/非法与秘密拒绝保存安全分类 completion，不保存被拒绝原文、摘要或异常。`--offline-import` 明确表示离线导入，不可称实际模型调用。

`quote/run/resume/report` 均显式传 `--snapshot`、`--view`、`--output-root`、`--workspace`，从 generation root 复读冻结原件。`quote` 仅报价，不扫描科学数据。`run/resume` 另需 `--expected-new-bytes` 完整增长估计，并在既有 storage supervisor 的有效 lease 下执行；实际 host volume、安全 floor、并发占用和输出根由既有 guard 核对，不能直接用 WSL free 代替。没有入口资格时不能启动 SDK 科学执行。

本轮04后继另显式传 `--evaluation-declaration`，保留原03生成batch/design，绑定实际04评价代码、执行policy、purge纠正、来源采用和288单位预算。已完成的历史03原件需由其原冻结代码回放；不将04 policy域或split要求追溯加入旧receipt。最终报告是只读派生产物，不重新生成、修复或执行科学。

`run` 复用完整核验的 receipt/checkpoint；中断没有伪造 exit 或耗时。`resume` 明确授权恢复失败且没有最终 receipt 的父尝试，父失败保留；每个子任务最多一次 successor，按完整 workload 再预留，累计不超过 design 上限。阶段采用须有匹配的原 reservation 和原件核验；原父记录不重写。报告保存到内容寻址目录，batch 实测包含公共核验，子任务诊断与 batch 耗时不能相加；child CPU、峰值、费用及人工未知时标 unavailable。

Hosted 后继管理器绑定 design/request/reservation、共享上下文原件、严格 Safe DSL 输出 schema 和配置；`scripts/run_post_hm_generation.py` 每次只启动一个机会，实际 prelaunch/completion、namespace、原始输出与来源 receipt 持久保存。接收及冻结时重新核验这些原件；失败和中断不补发。来源 receipt 固定 `NOT_EVALUATED`，不授整套 HM、SDK 或科学资格。

原生成阶段采用原已接受组件的runtime/isolation设施，旧业务结论不采用。模型配置将proposal byte cap收窄到65,536，投影绑定有界上下文。生成设计与初始科学执行使用源码快照03；当时管理快照05只修改管理摘要持久出口和512MiB临时目录，依赖差异机械核对为一个脚本，复用已准备设计及基线。[阶段来源记录](../../artifacts/hosted-evidence/post-hm-discovery-01/phase-source-adoption-05.json)；[输入与基线完成记录](../../artifacts/hosted-evidence/post-hm-discovery-01/preparation-job-04/completion.json)。后续模型切分纠正使用科学源码04，见下文；早期失败与退出未改写。

FR-03 入口调查与 F1 的实际状态见[独立记录](post-hm-mvp-fr03-investigation.md)。SDK 资格、Hosted 后继接入、工程实现与真实对照研究分别记录；已有调用预算不代表入口已经合格。

## T9 实施和恢复历史

首个 Hosted 机会的实际 CLI 退出为1，`CLI_PROCESS_NOT_COMPLETED`；workspace routing discovery 失败。同一默认执行环境公开 DNS 解析失败，获准的无认证公开网络诊断能解析目的域名。失败、预留、prelaunch/completion 和实际 guard 退出均已保留在[首个机会](../../artifacts/hosted-evidence/post-hm-discovery-01/capture-opportunity-01/completion.json)，不能补足或改写。

第2次机会的网络提升请求在进程启动前被自动审批拒绝。对约6KB实际提示词和全部投影对象完成逐项核对后，重新审查仍要求用户明确授权具体载荷向 `chatgpt.com/backend-api` 出站。[实际提示词](../../artifacts/hosted-evidence/post-hm-discovery-01/outbound-review-01/first-opportunity-exact-prompt.txt)；[载荷与投影范围记录](../../artifacts/hosted-evidence/post-hm-discovery-01/outbound-review-01/review.json)。内容为DSL/schema、方法参数、日期、暴露声明及哈希，没有行情、预测、持仓、订单、个人数据或秘密。后续固定生成指令、上下文和schema不变，仅Hosted请求身份变化；现有登录认证限正常提供方认证、内存FD和有界临时目录。未绕过自动审批，也未启动第2次预留或调用。

当时等待明确外传授权期间，批次曾保持未冻结，离线管理入口与资源材料已完成。[科学管理脚本](../../scripts/run_post_hm_science.py)调用实际源码快照03的原CLI：固定输入只读、网络隔离、512MiB私有tmpfs；仅输出/job和原lease控制所需inode可写，保留独立管理脚本hash、prelaunch、实际退出及有界日志。实际退出先独立落盘，再处理日志与摘要。`run/resume`均需既有supervisor的有效完整增长lease，恢复仍由原服务执行；管理脚本没有科学PASS或资格证明。[准备记录](../../artifacts/hosted-evidence/post-hm-discovery-01/offline-science-entry-preparation-01.json)保留当时管理源码hash及局部Ruff/strict Pyright通过事实，不改标为后继脚本证明。

剩余4个LLM机会依次成功捕获，来源原件核验后统一冻结，未取得评价反馈或追加生成。[冻结与报价记录](../../artifacts/hosted-evidence/post-hm-discovery-01/freeze-and-quote-job-01/completion.json)绑定batch `162b4ec5b5108be61d95ad19dc33191d09bdb73b8f34020465ff687580c8351a`：15个机会/15条映射/10个不同可执行候选，完整报价177单位。该时点尚未执行科学，后续完整链、恢复和比较的实际结果见本页首部与研究报告。

科学增长估算为18GiB，覆盖最多15个初始任务及每任务一次失败/恢复的存储包络；计算预算仍为360单位，恢复另占完整报价，存储包络不扩大计算授权。[增长估计](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/growth-estimate.json)；[实际资源准备观测](../../artifacts/hosted-evidence/post-hm-discovery-01/science-resource-preparation-01.json)。观测时宿主卷可用约65.9GB，既有32GiB安全底线加18GiB完整增长后仍余约11.37GiB；可用内存约11GB。2GiB科学内存预留与512MiB私有tmpfs另列；实际启动必须重新核对，不能把此观测当作已获得执行lease或实际峰值。

用户已于2026-10-11明确批准上述载荷向 `chatgpt.com/backend-api` 发送、使用现有登录认证、以 `gpt-6.1-sol/high` 继续剩余最多4个生成机会。[后继授权记录](../../artifacts/hosted-evidence/post-hm-discovery-01/authorization-resolution-01.json)保留原待授权状态与拒绝历史，不改写原件。5个机会已用完，不追加调用；当前没有必须由用户操作的待办。FR-03的P10 NO_GO继续保留，主线不切换到未合格SDK入口。

科学管理作业01在记录解释器身份前失败，后继脚本改为哈希真实解释器二进制并保留虚拟环境启动路径；最初关于PYTHONPATH的未核实归因由[后继纠正观察](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-01/controller-failure-correction.json)明确纠正，原失败与错误观察未覆盖。作业02保留实际退出和 `NETLINK_ROUTE socket: Operation not permitted`，默认工具沙箱阻止创建无网络namespace；两者均未启动科学或预留workload。后继作业03获准在宿主创建同一无网络隔离，已写管理prelaunch及科学执行预留。只补管理解释器/隔离启动，不改源码快照03、设计、冻结批次或科学谓词，不重做生成和数据。

作业03的首task已完成baseline-signal、baseline-pit与baseline回测，Workflow随后抛出 `MlflowException`；原task/batch attempt均为FAILED，没有终态receipt。根因为当前MLflow FileStore拒绝任意祖先目录名为 `artifacts` 的run，并非缺失run文件。[原目录与接口原因](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-03/mlflow-cause.json)；[隔离只读alias接口读取成功](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-03/mlflow-alias-interface-02.json)。第一次alias接口因只读根不能新建mount目标失败，后继将目标设于既有私有tmpfs内；接口检查未新建实验或执行科学。

作业04只在namespace内覆盖Workflow管理目录视图：原失败MLflow目录在原处不动；新的非权威runtime由既有guard下持久目录bind到 `/tmp/qlib-runtime/<execution_identity>`，该路径实际写入持久mount而非临时存储。相邻native-records仍bind原持久目录，导出、request、checkpoint、失败与冻结科学源码03均不变。各task按execution identity隔离，保留管理layout和prelaunch身份；不把runtime fingerprint当成挂载等价证明。[管理layout](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-04/mlflow-layout.json)；[后继prelaunch](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-04/prelaunch.json)。原信号/PIT/基线checkpoint机械核原件后采用，失败parent不改写；恢复按完整workload另预留，仍受360单位上限约束。

作业04已核验复用原首task信号/PIT/基线checkpoint并越过MLflow路径异常。该候选随后因原生每日Rank IC含12个NaN（726日）未通过冻结导出规则，发布 `EXECUTION_FAILED` receipt，科学状态NOT_EVALUATED；普通IC无非有限值，不把原生summary分数用于比较。[只读原件诊断](../../artifacts/hosted-evidence/post-hm-discovery-01/science-job-04/first-native-statistic-counts.json)。第2个候选同样形成终态执行失败，均不重跑；第3个已完成原生预测及审计导出，继续原成本/参数/子期/复现/Validation全链。恢复额外预留18单位，累计195/360，未扩大生成次数或修改科学谓词。

作业04随后因声明的purge未实施而停止，原03输出不准入purged比较。固定view日历上的后继effective train截止2019-12-24、valid截止2022-12-23、test起于2023-01-03；实际DatasetH样本索引形成独立split审计，hash进入新终态receipt并由只读入口核验。[诊断与切点](../../artifacts/hosted-evidence/post-hm-discovery-01/purge-correction-01/diagnostic.json)。源码快照04实际commit为 `3de5a5a33eb9a8d7d2235497dce2338cfd158670`，inventory hash为 `c7d0738843576cf7d6de0cf41923a7804ace5f4fbc4fa981949ff3caa041031a`；评价声明hash为 `9bd79eafcdd641a7d52c10877db445ecb276c5a94ad4df2264e49032befdb734`。[评价声明](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/evaluation-declaration.json)。

15组已完成signal/backtest保留原03科学bytes及实际来源；`adopt_verified`仅更新后继metadata引用并留独立采用receipt，不采用旧模型预测或转移旧资格。采用receipt绑定实际outcome，缺失receipt拒绝复用。[来源采用原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/source-adoption.json)；[源码依赖差异](../../artifacts/hosted-evidence/post-hm-discovery-01/purged-evaluation-inputs-01/source-delta.json)。

科学作业05在既有guard `run-1791694245639316657-542636` 下运行。实际prelaunch观测宿主卷可用66,739,363,840 bytes、内存可用10,728,423,424 bytes，cgroup上限unavailable；18GiB完整增长、固定安全底线、2GiB科学内存预留及512MiB私有tmpfs沿用，不把启动观测当成实际峰值或完成结果。[guard启动原件](../../artifacts/hosted-evidence/storage-control/run-1791694245639316657-542636/prelaunch.json)。

作业05随后全部完成，2026-10-11 07:58:22 UTC观察到namespace实际退出0；管理完成wall为11,252.084543秒，guard实际退出0、清理核验成功。批次执行wall为10,428.805790秒、调用进程CPU为10,378.854340秒，最终比较另在管理总耗时内，没有独立计时。所有10个receipt核验完成，5个预测准入；30份来源采用receipt对账一致，旧模型未采用。[批次完成原件](../../artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/batch-attempts/00000001/completion.json)。本轮到此结束，后继功能仅按执行计划的触发条件另立范围，不构成当前用户待办。
