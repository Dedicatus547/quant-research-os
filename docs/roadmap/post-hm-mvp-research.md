# QuantOS HM-MVP 后续实施指南

## 开放研究方法，保留可信裁决，控制实施总成本

| 项目 | 内容 |
|---|---|
| 编制日期 | 2026-10-11 |
| 已审阅仓库基线 | `639b3de49fe3a621bb43e636d1e43b99f3eed1b3` |
| HM-MVP 冻结版本 | `hm-mvp-component-v2`，标签目标 `59c25ac851cde4f6074d83159fd95a5351237f63` |
| 文档性质 | 后续设计与实施建议，不是新的运行资格证明或已完成声明 |
| 仓库位置 | `docs/roadmap/post-hm-mvp-research.md` |
| 适用范围 | HM-MVP 之后的研究能力扩展、原则修订与增量实施 |

**基线说明：** 本文依据仓库源码、架构文档和发布记录形成，并已按当前实现修订候选生成、执行能力、评价与成本范围。本次修订仅作静态阅读与文档整理，没有运行测试或科学任务，也没有重新核验大型运行工件。实际实施时只需核对与本次变更有关的基线差异，不因本文重新启动完整资格化、模型调用或科学执行。HM-MVP 的冻结身份与接受范围以原发布记录为准。[R1]

**实施进度（2026-10-11）：** 本轮T0–T9、O0/O1及F0/F1有界任务已结束。15个生成机会冻结为10个不同候选，源码04实际应用5交易日purge并完成后继评价；5个预测通过只读准入、5个执行失败，策略Validation PASS为0。LLM组无可分析预测，本轮不能估计其有效预测增量或单位总成本优势。完整结果与限制见[首轮研究报告](post-hm-mvp-discovery-report.md)，来源采用、实际退出和历史见[实施记录](post-hm-mvp-implementation.md)。SDK有界P10仍为NO_GO，未切换SDK；没有当前用户待办，后继触发项按独立范围处理。

---

## 1. 决策摘要

**保留 HM-MVP 的交接、隔离、预算、恢复和证据基础，扩大它能够承载的研究内容。不要重写整个核心架构，也不要通过取消 PIT、证据完整性或独立评价来获得研究自由。**

下一阶段的主要目标是：

> 在保留冻结基线的前提下，建立可比较的有限批次研究发现流程，判断 Agent 相对于简单基线是否带来单位总成本上的研究增量。

推荐实施顺序：

1. 先定义研究问题：评价对象、主指标、数据暴露边界、对照方式和成本口径。
2. 补齐冻结前提案记录、提案到候选的映射、执行能力检查与受限执行路径，复用现有交接和确定性服务；生成侧接入按第 5.5 节确定。
3. 优先使用现有字段与算子，尽早完成小规模探索性对照，报告可核验结果和实际成本。
4. 根据观察到的瓶颈，再扩展必要字段、多窗口扰动、自适应 Discovery 或正式预测选择规则。

**首轮建议研究固定 LGB 下的预测价值，交付有界探索性比较报告。** 研究设计应先回答第 8 节的评价问题和第 12 节的对照问题，再确定第 5、6 节的实现路径。正式选择、Registry 晋级、全局 LLM 执行权限修订及通用 AST 框架均不是这轮的前置交付；探索性定位仍须满足权限、PIT 和证据完整性要求。

**FR-03 可作为独立任务尽早有界重开，与研究准备并行。** 研究闭环仍是主要交付，不依赖完整 Agent runtime 恢复；首次真实生成接入前，根据资格结果选择入口。通过相关资格时优先沿原 SDK runtime 接入，受阻时停止扩大排障并继续研究路线。两项任务独立提交、独立记录完成范围，具体安排见第 5.5、13 节。

按模型能力拆分的任务、思考等级、并行依赖和额度控制见[实施任务与模型分工](post-hm-mvp-execution-plan.md)。该清单以首轮闭环为主线，长期扩展按触发条件启动；开发代理的模型选择不覆盖研究生成配置或 FR-03 冻结资格模型。

暂不优先启动任意 Python 执行、任意模型插件、多模型 Council、新 harness、第二回测引擎、实盘接口或完整通用调度平台。

### 1.1 三类约束必须区分

| 约束类别 | 典型内容 | 后续处理 |
|---|---|---|
| 可信研究不变量 | 输入身份、权限、PIT、证据完整性、预算、失败留证、评价数据暴露边界 | 保留严格约束，不由 Agent 自行覆盖 |
| 特定执行 profile 的限制 | 固定字段、固定模板、有限枚举、固定模型、固定评价流程 | 按版本扩展，不作为所有未来研究的永久禁令 |
| 工程偏好 | 优先复用 Qlib、优先简单实现、局部验证、避免重复计算 | 根据效果、总成本和风险调整 |

冻结契约对其历史运行继续有效。新原则只指导后继版本，不追溯改写原证据。

## 2. 建议采用的核心设计原则

> **QuantOS 以可信研究过程为基础，以单位总成本的研究价值为优化目标。**
>
> 系统不预设候选必须由规则、传统算法、机器学习或 LLM 产生。权限、输入身份、数据与模型的时间边界、预算、状态转换和证据完整性由明确、可审计的机制约束。
>
> 提案者可以在授权范围内提出、请求执行和优化研究方案，但不能自行修改评价规则或认证其结果。准入、执行成功、统计表现与研究晋级分别判定；失败和拒绝同样保留为研究历史。
>
> 探索允许自适应，独立评价必须控制数据暴露与选择偏差。验证结论只在其输入、方法、环境和假设范围内成立，不构成未来盈利保证。
>
> 验证与复现按风险、实际依赖和结论范围实施，优先复用可核验的既有证据，不把局部变化无理由扩大为全系统重证明。

### 2.1 形式化定义与学习求解并不对立

形式化描述解决的是“对象是什么、允许做什么、必须满足什么”，学习或搜索解决的是“怎样找到更好的候选”。一个问题可以具有严格定义，同时由机器学习求解。

因此，架构不应以“传统算法或神经网络”为主要边界，而应以以下问题为边界：

- 谁可以提出和修改候选？
- 谁可以读取哪些数据、调用哪些能力、消耗哪些资源？
- 谁负责执行、测量和作出何种范围的结论？

其中，形式化检查不能自动证明原始数据绝对真实、统计假设完全成立或未来市场表现有效。应记录无法证明的限制，而不是把它们包装为工程保证。

### 2.2 准入不等于有效性认定

研究候选不需要先证明“有用”，才能进入可信研究流程。它需要先通过安全、身份、语义和资源检查，再由实验确定是否有用。

```text
候选提案
    ↓
Admission：身份、权限、输入、语法、时间语义、适用性与资源检查
    ↓
受控执行与测量
    ↓
科学评价
    ↓
是否支持选择、确认或研究晋级
```

拒绝和失败同样进入研究历史。不能将“未通过科学阈值”解释成“无需保留该实验”，也不能将执行异常包装成科学拒绝。

### 2.3 独立验证包含三个层面

| 层面 | 要求 |
|---|---|
| 权限独立 | 提案方不能修改 evaluator、阈值、冻结输入和正式报告 |
| 证据独立 | evaluator 从绑定的输入与执行产物形成结论，不相信 Agent 自报的收益、IC、PIT 或执行状态 |
| 统计独立 | 用于独立评价的数据不能被搜索过程反复消费后仍被称为未暴露样本 |

换一个模型审阅只可能辅助发现问题，不能替代以上边界。现有 Agent reviewer 不自动获得科学裁决权。

## 3. 当前基础与实际限制

当前系统已经在架构和实现上分离 Agent 提案与确定性应用裁决。此次调整的重点是开放研究内容，而不是重新建立这条边界。[R2][R3]

下表省略前缀的源码路径均相对于 `src/quantos/`。

| 已审阅位置 | 当前事实 | 对后续实施的含义 |
|---|---|---|
| `src/quantos/application/hosted_campaign.py` | 管理侧注册输入，研究侧提交响应，并重新核对绑定 | 复用现有交接与权限边界，不另建平行权威通道 |
| `contracts/hosted_inputs.py`、`application/hosted_inputs.py` | execution profile 与 loader factory 固定为 `p14dq-frozen/v1`；loader 核验原两候选家族的精确哈希 | 后继 profile 需明确业务绑定，现有入口不能直接承接任意新批次或子任务 |
| `src/quantos/application/autonomous.py` | proposal 必须引用冻结 manifest 内的候选 | 当前 Agent 提出的是已有候选的执行建议；生成新 AST 需要冻结前入口 |
| `src/quantos/research/qlib/expression.py` | 字段映射只有 `adjusted_close → $close` | 研究表达能力受限，扩展字段比先增加 Agent 角色更直接 |
| `contracts/campaign.py`、`contracts/enumeration.py` | family 绑定单个模板与参数笛卡尔积；manifest 使用 `canonical-cartesian-v1`，参数槽只允许 `window` | 跨结构集合会影响 family、候选身份及其消费者，不能只替换 manifest |
| `application/data_qualified_release.py`、`application/autonomous_execution.py` | 参数扰动及执行记账要求 DAG 恰有一个带 `window` 的节点 | 已准入 DSL 不等于完整执行链可执行；首轮需限定能力范围 |
| `contracts/qlib_view.py`、`research/qlib/pit_evidence.py` | view 包含 OHLCV、不含 amount；compact PIT 只映射 close/adjusted_close | 开放已有派生字段与新增派生字段的工作不同，均需核对实际来源与 PIT 路径 |
| `src/quantos/research/qlib/workflow.py` | 单表达式特征进入固定结构的 `LGBModel` | 必须明确评价的是原始因子还是固定模型的预测 |
| `src/quantos/application/campaign_selection.py` | 要求 `PREFROZEN_FINITE_FAMILY`、原枚举 manifest 和 validation trial PASS | 预测证据可分析不等于完整策略 Validation PASS，也不等于 P14c 可选择 |
| `src/quantos/application/autonomous_execution.py` | `compute_seconds` 是确定性工作量记账单位，不是实测秒数 | 控制预算与实际成本分开报告，不修改历史 charge |

以上约束来自已审阅源码与架构说明。[R3][R4][R5][R6][R7][R8][R15][R16][R17][R18]

HM-MVP 两项科学执行均为 `SOFT_REJECT`。这能说明工程流程可以保留拒绝结果，但不足以判断拒绝来自表达能力、搜索方法、数据、评价对象或市场信号本身。不能以这两个结果为理由降低阈值。[R1]

## 4. 长期原则与按需规则修订

### 4.1 目标

确立方法中立的设计方向：一种方法尚未实现或尚未准入，不代表永久禁止。被研究的方法可以按明确的后继设计扩展，可信控制和独立裁决不交给提案者。

当前规则已经允许 LLM 在执行前生成 DSL 提案，也明确要求复用 `LGBModel`。首轮“LLM 提案 → 确定性准入 → 既有研究计算 → 独立结果分析”不需要修改 `AGENTS.md` 第 6、7 条。[R9]

### 4.2 触发条件与主要触点

实际需要 LLM 推理输出作为特征或模型产物时，再审视 `AGENTS.md` 第 6、7 条，以及 `README.md`、`docs/architecture/overview.md`、`docs/architecture/agent-and-campaign.md` 和 `PLAN.md` 中对应的原则与范围说明。

规则修订与该能力的接口、输入外传权限、模型知识时间、输出留存和下游核验一并设计。在明确的后继规则生效前，现有禁止调用的范围继续适用；本文不授予 LLM 执行权限。

### 4.3 后继设计应表达的边界

权限、输入身份、时间边界、预算记账、状态转换、指标计算和正式裁决由受控实现执行。新增研究方法通过明确接口接入，绑定输入、实现或模型标识、配置及输出，不得取得修改数据、评价规则或正式证据的权限。

Agent 输出保持提案身份。将来获准使用推理产物时，其来源和适用性由独立机制核验，不能因冻结或通过检查就被提升为原始事实来源，也不能自行认证科学结论。

### 4.4 必须保留

不可变快照、凭据保护、PIT hard rejection、执行失败与科学拒绝区分、失败留证、显式身份绑定、Qlib 派生缓存定位、不可变产物权威，以及不自建第二回测和组合会计引擎的约束。

外部模型推理不应被改造成 Validation 或回测中的任意网络调用。确有需要时，放在单独、已授权的推理阶段，检查数据外传权限并冻结输出；下游读取明确的本地工件。

**按需修订的完成条件：** 新能力的权限与证据范围明确，没有向 Agent 授予控制、权威证据写入或裁决权限；历史契约继续按原版本解释。首轮仅整理范围，不以修改全局规则作为启动条件。

## 5. 由研究问题确定受限执行 profile

### 5.1 目标

在第 8、12 节的研究设计确定后，让新研究任务复用 HM 的请求、提交、幂等、预算与恢复机制。执行 profile 的证据要求由研究问题决定，不自动继承原 P14-DQ 的全部业务流程。

### 5.2 主要触点

| 位置 | 处理方向 |
|---|---|
| `src/quantos/contracts/hosted_inputs.py` | 保留 v1；新增范围受限的后继业务输入/profile 表示 |
| `src/quantos/application/hosted_inputs.py` | 按可信管理配置加载对应 profile，复用现有输入核验 |
| `src/quantos/application/hosted_campaign.py` | 检查后继 profile 与业务绑定，不再将原固定业务组合视为唯一可能 |
| `src/quantos/application/hosted_protocol.py` | 优先复用；仅在实际协议差异需要时修改 |
| `src/quantos/contracts/hosted.py` | 仅在新增业务身份无法由现有结构表达时做版本化扩展 |

上述路径是 Hosted 侧的入口，不是完整影响清单，也不是无论选择何种生成入口都必须修改的文件清单；按第 5.5 节选定路线后核对实际依赖，候选与执行依赖见第 6.5 节。当前 loader 除固定 profile 外，还核验原两候选家族的精确身份，并构造 selection、Governor、Orchestrator 和 execution adapter。预测探索路径或多个新子任务都不能直接套用现有 loader。[R3][R4][R18]

### 5.3 实施要求

**旧 profile 原样保留。** `p14dq-frozen/v1` 继续承担旧结果回放、兼容基线和已接受行为的角色。

**首个新 profile 只支持有界研究。** 候选使用明确可执行的 DSL 子集，集合或子任务列表在评价前冻结。采用第 6.6 节中的最小组织方式，不同时引入任意 Python、任意模型和任意策略代码。

**profile 由管理侧选择。** 使用少量、显式注册的 profile 与解析/验证实现。不要把 `Literal[...]` 直接放宽为任意字符串，不允许 Agent 提交任意 factory、模块路径或自报契约来获得权限。

**身份与预算继续精确绑定。** 新业务组合保持 campaign、输入、候选集、policy、执行环境和预算的可核验关联。已经存在的绑定字段和基础设施优先复用，不新增一套平行身份体系。

**生成与执行分阶段。** 冻结前生成只绑定已存在的请求、输入和生成 policy；冻结后的执行任务引用生成记录与实际候选。生成重试和无效输出消耗计入预算，不能只记录成功进入执行的候选。

**探索报告具有独立的完成边界。** 如果首轮只比较预测证据，按第 8 节定义所需输入与结果核验，保留既有策略 verdict；不把 P14c 选择成功或 Registry 晋级设为完成条件。需要精简执行步骤时采用明确的后继 profile，不能在旧 profile 中静默省略冻结要求。

### 5.4 完成条件

不同于原 P14-DQ 样例的有界研究任务能够接收已绑定候选，执行或明确拒绝，恢复并保存所需证据；旧 profile 保持既有语义。新组合的接受范围单独说明，不声称自动继承旧 profile 的整套资格。

**首轮前置边界：** 不要求更换 harness、完成 FR-03 解阻或先构建 standalone worker。FR-03 按下节作为独立任务推进，其他能力仍按实际需求启动。[R10]

### 5.5 FR-03 有界重开与研究接入

**优先安排一次有界的入口判断，研究准备同步推进。** 恢复原 SDK Agent runtime 是独立工程目标；研究闭环保持主要交付地位，不等待完整 runtime 后续流程。runtime 恢复也不会自动补齐冻结前生成、候选映射、执行能力或评价设计，这些仍按第 6、8 节实施。

当前 FR-03 为 `NO_GO / THIN_MAINTENANCE`：canonical SDK/runtime `0.154.0` 的 P10 为 6/9、缺少所需 live command lifecycle；官方 candidate `0.156.1` 在 account/read preflight 失败，P10 尚未执行。账号预检通过与执行能力合格是两项不同结论；既有 CLI 成功不替代 SDK 资格证据。[R21]

| 工作线 | 与研究的安排 | 有界完成条件 |
|---|---|---|
| FR-03 重开 | 尽早核对新的官方 runtime candidate 或实质相关上游修复；只有满足既有重开条件才进入资格执行 | 核验 package、executable 与 provenance；一次最小预检，通过后再按原模型、rubric 和尝试上限执行一次 P10；任一步失败留证并停止本轮 |
| 研究准备与公共实现 | 并行明确评价问题、生成预算、提案留存、候选映射和能力检查；按第 9 节推进适用的结果核验去重 | 复用现有 AgentRun、proposal 与确定性服务边界，避免提前增加大量 Hosted 专属逻辑；不为此新建通用 runtime 切换框架 |
| SDK 后续与研究接入 | 根据资格结果选择实际接入路线，再开展首次真实生成 | P10 9/9 后才进入 P13；完成拟采用入口所需资格与有限适配后接入新研究。P14d-C 仍需独立实现与资格，不因 P10 通过自动解阻 |

**在首次真实生成接入前汇合。** 如果 FR-03 已通过相关资格，优先沿原 SDK runtime 接入新研究生成流程，并明确新组合的接受范围。如果仍受阻，停止扩大排障，研究路线使用已有可用交接能力完成必要的后继适配；既有 Hosted loader 的限制仍然适用。离线准备或回放不能作为本轮真实 LLM 生成的完成证据。不新增 CLI fallback、自动双栈或重复 prompt 排障分支。

**分开交付，避免共享状态相互影响。** 依赖与资源允许时，使用隔离的候选环境和输出目录，统一核对调用额度与 CPU、内存、存储预算；共享依赖锁、适配器、权威状态写入和同一恢复链保持有序。复用已有授权范围，正式调用仍须具备可用额度，不能续用已经耗尽的 HM campaign 额度。[R9][R12]

具体候选版本、预算、资格规则、运行证据和失败结论继续维护在 [FR-03 状态与维护入口](../status/fr03.md) 及其关联记录中，本节只维护优先级、依赖和接入条件。本次文档修订不改变 FR-03 当前资格状态，也不启动预检、模型调用或资格运行。[R21]

## 6. 冻结前生成、候选映射与执行能力

### 6.1 目标

让人工、简单搜索和 LLM 在同一允许范围内实际产生候选，再进入有界、可留证的研究流程。保留旧笛卡尔积枚举方式作为一种生成器。

当前 Orchestrator 只接受已冻结 manifest 中的候选；把已有候选交给 Agent 安排执行，不能用于证明其生成候选的能力。首版补齐冻结前入口，但不要求多轮研究反馈。[R15]

### 6.2 冻结前生成入口

优先复用现有 AgentRun、proposal、保存与编译组件。现有 compiler 也绑定 campaign、family、模板和字段，不能直接把它视为无约束 AST 入口；按实际接口依赖作有限适配。[R19]

| 要素 | 首版要求 |
|---|---|
| 生成请求 | 绑定研究问题、允许字段与算子、执行能力限制、可见上下文及其来源、生成方式与配置 |
| 生成预算 | 明确调用、尝试、输出规模和重试上限；无效提案不得无限重试直到凑足有效候选 |
| 原始记录 | 按既有安全与留存规则保存请求、响应、解析失败、准入拒绝、重复提案及可取得的实际成本 |
| 转换关系 | 原始提案、规范化 AST、能力检查结果与冻结候选逐项关联；人工编辑或自动修复形成可追踪的后继记录 |
| 冻结结果 | 列出纳入候选、未纳入项及原因，绑定评价设计、执行输入与配置 |

解析失败的提案也应能通过生成请求和响应身份留存，不要求它先获得有效 AST 或候选哈希。没有可靠身份的记录不能凭名称补造对应关系。

**身份依赖保持单向。** 生成批次由预先冻结的请求、输入和生成 policy 标识，不依赖未来输出。如果最终 campaign 身份依赖生成后的候选集，冻结前请求不得反向要求绑定该最终 campaign；由后续冻结任务引用生成记录。优先使用已有身份结构，仅补齐确实缺失的关联。

首版允许一次或有限次生成与有界格式修正，生成阶段不读取本轮候选的预测指标、回测表现等研究结果反馈。已可见的历史结果同样记录在上下文来源和数据暴露范围内。研究反馈迭代属于第 10 节的后继工作。

### 6.3 首版流程与冻结时点

```text
预先确定研究问题、数据边界、比较规则与资源上限
                ↓
冻结生成请求 → Agent / 人工 / 简单搜索算法提出候选
                ↓
保存原始提案 → 解析、规范化与独立能力检查
                ↓
记录拒绝、重复和修订 → 冻结完整候选集合或子任务列表
                ↓
绑定既定评价设计、输入、policy 与执行预算，注册受限任务
                ↓
PIT → 所需 Qlib 研究与结果核验 → 探索性比较报告
```

评价对象、主指标、方向、窗口和数据可见范围在生成前确定，最终候选名单在评价前冻结。首轮不根据评价反馈修改候选或事后挑选主指标。后续若需要正式选择，再采用对应冻结统计设计；探索报告不自动获得该权威。

### 6.4 首版可执行子集

首版优先使用现有字段、算子和固定研究配置，并限定在当前执行路径可表达的结构内。复用当前完整执行 adapter 时，DAG 必须恰有一个带 `window` 的节点；这限制的是节点数量，不是不同窗口值的数量，也不是可调参数维数。[R16]

例如，两个收益率节点相减，即使窗口值相同，也不满足该规则。单窗口仍只是必要条件：字段映射、PIT 来源、算子语义、输入长度、参数变体和评价要求均须一致。尽可能在昂贵执行前识别不支持的候选；完整 PIT 仍在执行路径中核验，不能由静态能力检查替代。

未来支持多窗口时，先定义扰动哪个节点、是否独立改变或保持比例、稳健性网格及预算记账，再增加能力。不能仅删除单窗口检查。首轮若采用更窄的预测执行路径，也需明确其实际支持范围，不能据 DSL schema 有效便承诺可执行任意结构。

### 6.5 实际依赖与兼容边界

以下是需要核对的依赖，不要求同轮全部泛化：

| 位置（均位于 `src/quantos/`） | 当前耦合与后继处理 |
|---|---|
| `contracts/campaign.py`、`contracts/enumeration.py`、`application/enumeration.py` | family、模板、参数空间、候选身份和 manifest 共同约束枚举；新增集合不能冒充旧 manifest |
| `contracts/autonomous.py`、`application/autonomous.py` | 请求、proposal 与执行请求绑定冻结候选，需衔接生成后的实际身份 |
| `application/campaigns.py`、`application/autonomous.py`、`application/autonomous_execution.py` | Governor、Orchestrator 和 execution adapter 消费并核验旧枚举；需保持完整试验、拒绝与失败记账 |
| `application/data_qualified_release.py`、`validation/service.py` | 单窗口参数扰动和稳健性证据绑定；支持范围必须与候选一致 |
| `application/autonomous_execution.py` | 执行前预算 charge 同样调用单窗口规则；预算形状与实际执行步骤共同定义 |
| Hosted contracts、loader 与 application | 管理侧输入和业务绑定需按后继 profile 适配，保留旧 profile |
| `application/campaign_selection.py` | 正式选择仍核验旧 manifest 与 PASS trial；只有任务确需新选择语义时才作后继适配 |

不能删除原 verifier 检查来接入新集合。候选结构扩展不自动扩大统计资格；旧 P14c 证明继续限定在原组合。[R5][R8][R15][R16][R18]

### 6.6 两种有限组织方式

| 方式 | 适用范围与代价 |
|---|---|
| 显式候选集合 | 与旧 `CandidateEnumerationManifest` 并存，绑定实际内容、生成来源、执行配置与集合身份；需适配选定路径的 family 和消费者，不追求通用插件框架 |
| 冻结比较批次引用多个研究子任务 | 每个子任务继续满足其 family/template 规则，批次统一绑定任务列表、提案映射、评价设计、预算与结果；只读汇总比较，可减少单 campaign 跨 AST 改造 |

按第 8 节的研究问题和实际依赖选择改动更小的路径。第二种方式也是后继设计，现有固定 HM loader 并不已支持任意新子任务；不能用它绕过管理授权或业务绑定。

拆分子任务不重置数据暴露或成本，不隐藏失败，也不缩小整体统计结论应覆盖的多重检验范围。若多个方法提出同一候选，应保留各自提案与重复记录；执行结果仅在真实依赖和身份允许时复用，并说明共享成本归属。

### 6.7 完成条件

不同方法生成的提案可追踪到实际候选，受限范围内的候选可执行，超出范围的提案有明确拒绝记录，完成步骤与失败可留存和恢复。评价前冻结集合或子任务列表；首轮交付第 8、12 节定义的探索报告，不要求通用多 AST campaign 或正式选择成功。

重复候选、schema 无效、PIT 拒绝、执行失败和科学拒绝均保留在历史与成本口径中。旧模板枚举继续可用。

**不做：** 首版不允许选择阶段 mutation/crossover，不做任意 AST 执行器，不追求识别所有数学等价表达式。

## 7. 按需求扩展字段与算子

### 7.1 目标

优先增加有研究价值的表达能力，而不是先增加 Agent 数量、角色或调用轮次。

当前字段映射只支持复权收盘价；`rank` 实际对应时间窗口算子 `Rank(x,N)`，不是横截面排名。correlation、zscore、cross-section rank 等仍未进入当前准入范围。[R6]

### 7.2 字段扩展

当前 `QlibViewSpec` 和 converter 已包含 open/high/low/close/volume，冻结字段列表不含 amount。价格按 `raw_ohlc * adj_factor` 派生，成交量按 `raw_volume / adj_factor` 派生；adjusted volume 不能被默认为原始成交量。源码能力不代替对实际使用的 snapshot/view 工件的核对。[R17]

| 扩展类型 | 需要核对的范围 |
|---|---|
| 开放已有 OHLCV 派生字段 | 实际 view 内容、proposal/compiler 字段限制、translator、PIT 来源及 typed contracts、单位、复权和时间语义 |
| 新增派生字段，例如 amount | 除上述范围外，核对 canonical snapshot 是否已有合格来源，以及 view schema、converter 和新派生产物身份；确需数据修订时创建新 snapshot |

普通 `application/pit.py` 与批量执行使用的 `research/qlib/pit_evidence.py` 都需要检查；后者的 compact PIT 目前同样只映射 close/adjusted_close，不能只修改 translator 或普通 PIT 路径。[R17][R19]

每项扩展需明确来源、可用时间、单位、复权口径及缺失值规则。不能把单位不兼容或可用时间不明的数据作为正常信号输入。

第一轮不为“数据丰富”自动引入第二 canonical provider、完整基本面系统或新的大规模采集任务。

### 7.3 算子扩展

先用已有算子回答首轮问题。确有表达能力瓶颈时再选择少量高价值算子，例如标准化、相关性或语义明确的横截面排名；同时核对第 6.4 节的执行限制，不一次性覆盖所有 Qlib 表达式。

| 需要明确的语义 | 目的 |
|---|---|
| 时间序列或横截面运算 | 避免把不同类型的排序、统计混为一谈 |
| 窗口、最少观测和 operator delay | 保持 PIT 与有效输入范围可计算 |
| 缺失值、非有限值和零分母 | 防止非法值被默认为可交易信号 |
| 历史 universe 与成分资格 | 避免横截面运算使用不适当的样本集合 |
| 输出可用时间与适用字段 | 防止语法有效却不具备正确执行语义 |

采用版本化字段/算子能力表，继续通过 admitted compiler 执行。安全 DSL 约束的是语义与权限，不应被误认为必须放弃的研究限制。

### 7.4 主要触点与完成条件

检查 `application/proposals.py`、`research/qlib/expression.py`、`contracts/pit.py`、`application/pit.py`、`research/qlib/pit_evidence.py`、相关 Qlib view 构建与 research contracts；修改范围由实际字段与算子依赖决定。

完成时，新增能力应在输入、翻译、时间语义与执行输出之间一致，并仅声明已完成的范围。获授权验证时优先使用已有受影响用例，不默认触发全套 HM 资格矩阵。

## 8. 首轮前置决策：评价对象与所需证据

### 8.1 当前问题

本节的研究设计先于第 5、6 节的实现选择。先确定研究问题，再确定证据和准入条件，最后选择执行 profile；不能等执行与选择适配完成后才澄清评价对象。

当前 Workflow 将单个表达式特征送入固定 `LGBModel`，导出模型 prediction/label 的 IC、Rank IC；现有回测输入则来自 expression/event signal builder。文档已明确，模型预测的 IC 不自动等于原始因子 score 的 IC。[R7]

当前 execution adapter 根据完整 ValidationReport 产生 `TrialOutcome`，只有 Validation PASS 才产生 `TrialOutcome.PASS`；P14c selection 将其余 validation trial 归为 `NONPASS_VALIDATION`。因此，预测证据完整但原始表达式组合软拒绝的候选，不会自动成为可选择候选。仅修改指标名称或报告措辞无法改变这个条件。[R8][R16]

这些是旧 profile 的范围，不构成对其历史结果的改判；后继研究必须使问题、证据与选择条件一致。

### 8.2 区分三类对象

| 评价对象 | 必须关联的产物与语义 | 不能混用的结论 |
|---|---|---|
| 原始因子分数 | expression、score、label、评价区间 | 不将固定模型预测的指标写成原始因子指标 |
| 模型预测 | 特征、训练/调参数据、模型配置、prediction、label | 不以预测指标直接证明另一个信号驱动的组合收益 |
| 组合策略表现 | 实际信号、组合规则、执行时序、成本与交易约束 | 不将与该组合无关的模型指标作为其表现证据 |

报告、gate 和后续选择须能追溯到实际被评价的对象。现有字段能表达时优先复用，确实不能表达时再增加后继 schema。

### 8.3 三种条件分别判定

| 条件 | 判断依据 | 授予的范围 |
|---|---|---|
| 预测证据可分析 | 预先指定的数据身份、PIT、训练/调参/评价划分、prediction/label 绑定与研究产物完整性均经独立核验 | 仅用于本轮明确的探索性比较，不自动形成策略 PASS |
| 完整 Validation PASS | 对应版本的完整策略链 gate 与证据要求 | 保留该 ValidationReport 的原范围，不能简化为纯预测价值结论 |
| P14c 可选择 | 既有冻结家族、完整 trial、PASS outcome 及可用 Rank IC 等条件 | 依原契约作选择，不由探索报告替代 |

不得按 `SOFT_REJECT`、`HARD_REJECT` 或失败标签一概纳入预测比较。对每项拟使用证据核对与研究问题相关的前提；数据/PIT 未通过、来源损坏、绑定不符或必要证据缺失的结果不能作为有效预测结果。未取得可用证据的尝试仍进入失败历史与成本报告，不能从比较批次中消失。

### 8.4 首轮建议：有界预测价值探索

建议首轮问题明确为：

> 在固定模型、标签、数据划分和已支持候选空间内，LLM 生成的特征相对简单基线，是否呈现值得继续投入的预测指标与成本表现？

在生成前指定主指标、方向、缺失与不适用结果的处理、模型配置、label、训练/调参/评价区间、特征处理和各方法可见信息。候选之间不暗中改变实验条件；数据是否未暴露依据实际历史判断。已有窗口已被消费时，结果按回顾性或探索性解释，不能重新命名为独立确认。

交付输入与结果来源可独立核验的探索性比较报告。保留既有策略链 verdict，不把软拒绝改标为 PASS；不要求首轮同时实现新的正式选择、sealed confirmation 或 Registry 晋级。评价设计前置不等于先建设完整的预测选择体系。

实现上可从既有完整执行中按上述条件读取 ResearchResult，并计入整条路径的实际成本；确需减少无关执行时，在明确的后继 profile 中复用 Workflow 等服务，定义所需 PIT、研究证据与失败出口。当前 loader 和 adapter 并没有可直接打开的“仅预测研究”开关；不能静默跳过旧流程的冻结步骤，也不能把新窄路径说成已经实现。

如果实际选择研究完整策略链，则在生成前改定研究问题、主指标与证据要求，复用相应完整 Validation/selection 条件，不将其结果归结为纯预测比较。

### 8.5 后续选择、桥接与模型搜索

正式预测选择有实际需求时，再定义与预测对象匹配的资格条件、多重检验范围和数据暴露规则，采用后继版本，不放宽原 P14c。研究目标转向“按模型预测交易”时，再增加经核验的 prediction-to-signal 桥接，使回测实际消费该预测信号。

将来通过受控模型配置和特征列表扩展，而不是由每个候选生成一套训练、标签处理与回测代码。模型搜索可以改变被研究的方法，不能修改评价方法的可信边界。

**完成条件：** 每份关键指标和策略结果的评价对象清楚、输入一致、来源可核验；不会出现同一报告把不同信号的表现混成一个结论。

## 9. 按实际影响控制验证、恢复与资源成本

HM-MVP 复盘指出，局部问题扩大为大范围证明失效、重复重跑、证据生命周期和资源问题，是重要延误机制。最终完整 CI 记录约为 2 小时 17 分钟，也出现过对约 2.46GB predictions/labels 的重复解析。应直接落实已有实施与恢复约定，不再建立一套平行管理流程。[R11]

### 9.1 按变更类型处理

| 变更 | 默认处理方向 |
|---|---|
| 在已支持范围内新增候选 | 运行其所需研究步骤，复用实际依赖未变的基础证明 |
| 新字段或算子 | 核对其数据、view、翻译、PIT 和执行依赖；验证受影响路径 |
| 新模型配置或模型类型 | 核对训练、推理、产物、时间语义和复现要求的变化 |
| 文档或管理路径变化 | 不以整体 commit 变化为由自动重跑科学链 |
| 权限、runtime、安装或关键依赖变化 | 根据受影响的安全/执行结论补充必要验证，不凭表面文件相同推断等价 |

“复用”不是相信旧摘要，也不是把旧 PASS 改标成新版本 PASS。保留原证明的来源身份，核对真实依赖，并在后继结果中说明采用范围。[R12]

### 9.2 执行要求

正式证据从开始进入持久目录，scratch 与缓存单独管理。独立步骤完成后立即保存结果与身份，失败后仅续做未完成或依赖已变化的部分。

重任务前核对宿主物理卷、输入/输出副本、并发预留和安全收尾空间。不得把 WSL 内部 free 当作宿主卷容量，也不得删除唯一失败证据为成功腾空间。

优先减少重复解析、大型科学重执行和重复完整核验。没有测量依据时，不把瓶颈直接归因于 CPU 或磁盘，也不为了建立统计另跑完整流程。[R12]

### 9.3 运行时优化：统一安排，分项交付

运行时优化纳入本路线图，按独立小任务和提交交付，服务于首轮研究。先确定研究问题与执行 profile，再优先处理明确的重复工作；无需先完成全部性能优化才能开展研究，也不另建长期性能工程或通用调度平台。

| 工作 | 实施安排与依据 | 完成边界 |
|---|---|---|
| 同次结果核验去重 | 独立实施、优先交付。DQ adapter、receipt 与 native audit 会嵌套核验同一 ResearchResult，重复解析和序列化 predictions/labels | 同次操作内复用已核验内容与事实，保留必要的完整性、来源及绑定检查；不减少核验谓词 |
| 阶段完成记录与恢复 | 随首轮执行 profile 实现。现有完整 execution receipt 和 Workflow recorder 已支持部分复用，但未形成覆盖各阶段的统一恢复入口 | 对实际耗时阶段保存输入身份、工件引用、完成或失败事实；恢复时复用可核验的完成步骤，仅续做缺失部分 |
| 信号与 PIT 基础数据共享 | 根据首轮记录的重复成本单独实施。现有变体复用部分 PIT evidence，仍可能重建同一表达式信号、读取市场表和建立索引 | 只共享依赖一致的数值结果、数据与索引；各候选继续核验自己的时间语义和来源，工件保持正确绑定 |
| 有限进程并行 | 减少重复工作后，按实测资源和独立阶段决定是否实施 | 输出根隔离、输入只读，统一预留 CPU、内存、实际物理卷及失败收尾空间；共享权威写入和同一恢复链保持有序 |

核验去重的主要触点是 `research/qlib/result.py` 与 `application/autonomous_execution.py`；阶段恢复涉及所选 profile 的 adapter、Workflow 和实际使用的回测服务。共享计算的触点是 `application/data_qualified_release.py`、`research/qlib/signal.py` 和 `research/qlib/pit_evidence.py`。这些路径均相对于 `src/quantos/`，是影响核对入口，不要求同轮全部修改。[R7][R16][R17][R20]

当前信号构建已批量查询整个调度区间，完整 receipt 已能避免重做完成的 execution，Workflow 也可复用完整 recorder；这些能力优先沿用。预测探索若不需要回测变体，阶段恢复按其实际研究步骤设计，不为完整策略链预建所有 checkpoint。新窄 profile 的计算范围按第 8.4 节明确，不能以优化名义省略旧 profile 的冻结要求。

### 9.4 复用、并行与效果记录的边界

**核验事实复用。** 优先合并同次操作中对已捕获、已核验内容的重复解析与语义检查。跨调用或跨进程复用必须绑定真实内容、核验实现/schema/policy、配置及相关环境依赖，并保证复用事实对应实际消费的内容。路径、mtime、只读挂载或首尾哈希相同，都不足以证明期间内容未变；保留必要的重新读取与完整性核验。大 JSON 的分块解析或增量哈希可在仍有明显成本时另行优化，保持原 canonical bytes、行数、投影和精确比较语义。

**共享计算与恢复。** 相同表达式、view、日期、universe、时间语义及可交易性条件下，成本或 top-k 变体可考虑共享因子分数，但各自发布正确绑定的工件并执行所需回测，不能直接套用旧 manifest。PIT 的基础数据和索引共享不减少候选各自的检查。阶段完成记录从开始进入持久目录；不能将父失败改标成功，也不能用缓存代替明确要求独立执行的 reproduction。

**并行实施。** Workflow 存在进程级 Qlib 状态、cwd/env 修改和全局锁，优先考虑独立进程，不能简单移除锁或加入线程池。现有 storage supervisor 使用排他作业租约，可在一个受监督作业的统一预算内组织独立子任务；不绕过租约启动多个重任务。先核对已有并行能力及实际资源，不承诺固定 worker 数或加速倍数。[R7][R20]

**效果记录与必要验证。** 下一次获授权运行时，结合既有记录保存阶段墙钟/CPU 时间、重复核验次数、解析字节量、可观察的内存/存储峰值及复用情况；无法取得的项标为 unavailable。没有可比测量前，只报告消除的重复工作及限制，不给出加速百分比。各优化任务保持独立完成条件；相关变更稳定后，在已有验证授权与真实影响范围内合并必要检查，复用完成结果，避免研究与优化两条工作线重复启动昂贵验收。不为建立性能统计另跑完整流程。

### 9.5 验证授权边界

本文描述完成目标，不自动授权新增或运行测试、模型调用、科学执行或完整资格化。

后续实施遵循当前 `AGENTS.md` 与实施约定：用户明确要求测试或实现验证时，才新增或运行相应用例；授权后的验证优先复用已有受影响用例，保持与变更风险相称。没有执行的检查必须说明，不能借“局部验证”宣称未完成的验证已通过。[R9][R12]

**目标：新候选承担新实验的成本，而不是重复承担整个系统重新证明自己的成本。**

## 10. 自适应研究的后继设计

### 10.1 数据边界

```text
Discovery：允许反馈、搜索和修改
    内部可包含训练、调参和探索性评价
                ↓
冻结候选集合、评价方法、方向与停止规则
                ↓
Selection：对搜索过程未暴露的选择数据
                ↓
冻结最终选择
                ↓
Confirmation：另行满足条件的未暴露或未来窗口
```

这是后继设计，不代表当前项目已经实现或取得上述全部能力。

### 10.2 Discovery 中允许的行为

在明确的开发数据范围内，Agent 可以读取实验反馈，提出新 AST、改变参数、组合特征并停止低价值分支。传统搜索算法使用同样的提案入口和资源边界。

保存实际执行的尝试、失败、重复、消耗和反馈来源。探索性结果可以指导下一步，但不能自动获得正式选择或确认结论。

### 10.3 Selection 与 Confirmation 的限制

候选进入独立选择前应冻结；选择反馈不能继续用于改进候选后仍保留“未暴露选择数据”的声明。

已查看的数据不会因为新的 campaign 名称、文件路径或 snapshot hash 重新变成未见数据。实际暴露与来源关系必须跨相关后继研究保留。已有窗口是否仍可用于独立评价，应依据暴露历史判断，不凭年份或文件名判断。

当前选择实现已明确记录：Holm 控制依赖有效的构成 p 值，未声明的自适应 validation 复用没有被自动防止。完整记录试验是必要的审计机制，不是自动修复选择偏差的统计方法。[R8]

必须区分三个口径：

| 口径 | 用途 |
|---|---|
| 开发阶段实际尝试历史 | 记录搜索路径、反馈和失败 |
| 资源预算 | 控制调用、执行、计算和存储消耗 |
| 独立选择集合的多重检验范围 | 由冻结的统计设计和有效性假设决定 |

三者不能机械地等同于一个“试验次数”。不得通过减少失败记录或只保留最佳结果缩小成本与历史口径。

### 10.4 当前实施取舍

先实现静态有限批次，再增加开发期反馈循环。首版不通过简单开关解除原 P14c 的 mutation/crossover 限制，不声称新搜索模式自动继承旧统计资格。

sealed confirmation 当前不在已取得的执行资格范围内。新增 Discovery 能力不自动完成 P14d-C，也不授予 confirmation、alpha 或盈利结论。[R1][R13]

## 11. 可复现性与模型知识时间

### 11.1 分层复现

| 对象 | 后继设计要求 |
|---|---|
| 请求、输入、候选、权限、policy、已发布产物 | 精确身份和完整性可核验 |
| 已捕获 Agent 输出的下游执行 | 在声明的实现、环境和规则范围内可重放 |
| 再次调用外部 LLM 生成候选 | 不承诺生成相同文本或候选 |
| 新引入的随机训练方法 | 预先声明种子、环境、数值容差或统计复现要求 |

当前文档已不承诺 LLM 输出逐字节可复现；外部 model 标识也不等于不可变权重快照。后继设计应沿用这一诚实边界。[R2]

新复现 profile 不能追溯放宽 P14-DQ 已冻结的精确一致性要求。历史结果仍按原输入、实现和批准环境解释。[R13]

### 11.2 模型知识时间

后续引入文本语义特征或历史模型推理时，增加以下风险检查：

> 提供给模型的输入满足数据 PIT，并不足以证明模型参数没有包含历史决策时点之后的信息。

区分两类用途：

| 用途 | 应声明的边界 |
|---|---|
| 今天用 LLM 设计通用因子，再做历史探索 | 属于回顾性研究，不声称该方法当年已可获得 |
| 用今天的 LLM 模拟过去每天的投资判断 | 需要额外考虑模型训练知识与历史结果记忆，不能只凭公告发布时间和禁网取得严格历史有效性声明 |

记录可获得的模型标识、训练截止信息、推理时间、输入来源与用途；无法获知的项标为未知或受限。需要更强结论时，优先使用后续未暴露窗口或前向观察，而不是通过文字声明消除未知风险。

此项不阻塞首版 DSL 候选生成，但在 LLM 输出直接成为历史特征或预测时必须处理。

当前 `SINGLE_SOURCE_NON_VINTAGE` 数据限制仍然有效；新原则不使缺少历史供应商版本的数据获得 vendor-vintage PIT 资格。[R14]

## 12. 首轮对照研究与价值判断

### 12.1 研究问题

采用第 8.4 节的首轮预测探索问题，并区分两个比较目标：

| 目标 | 事先固定与报告的内容 |
|---|---|
| 搜索能力 | 相同允许空间、可见信息和候选评价机会，比较生成候选的质量；生成成本另行报告 |
| 经济性 | 明确总资源上限和分配方式，将模型、执行、验证、存储与人工成本一起考虑 |

相同评价次数不保证相同总成本，相同确定性预算单位也不保证相同实际耗时。首轮按可取得的成本信息报告观察，不在成本缺失时给出无条件的经济性优越结论。

### 12.2 对照设计

比较人工模板或现有枚举基线、同一执行能力范围内的随机搜索、LLM 候选生成。三者使用相同的数据范围、可用字段与算子、结构限制和评价对象；生成前明确候选评价机会、总资源上限及分配方式。不能把 Agent 在同一个现成清单中安排执行的结果，当成候选生成质量的比较。

生成尝试上限与停止规则预先固定，不能给 LLM 无限重试而只统计最终成功候选。人工基线的准备、干预与修复同样留存；随机搜索的随机源和实际输出可追踪。所有组保留失败、无效、重复和未执行候选及原因，并遵循第 6 节的提案映射。

生成阶段接触的历史结果从首轮开始记录。评价反馈不能再用于修改本轮候选后仍声称评价数据未暴露；下一轮继承相关暴露关系。重复查看的数据不因新任务名、子任务拆分或新文件哈希恢复独立性。

资源预算和数据窗口在实际运行前按现有授权确定。本文不预设新的调用额度，也不自动续用已耗尽的旧 campaign。

### 12.3 三类评价

| 维度 | 需要回答的问题 |
|---|---|
| 有效研究产出 | 产生多少不同且可执行的候选？多少失败来自接口问题？多少只是重复已有结果？ |
| 总成本 | 模型、Qlib、验证、存储和人工干预各消耗多少？恢复和重试带来多少额外成本？ |
| 预测指标与证据强度 | 在预定主指标上有何差异？实际数据暴露历史支持探索性、独立评价或何种更窄的解释？ |

无法取得的 token usage、调用成本或资源峰值标为不可用，不能视为零。不能事后从多个指标中选择最好看的一个充当预定目标。

第一轮是小规模探索性比较，结果不要求具备统计优越性声明的强度。研究效果与证据强度分别报告；全部无效或拒绝也可以形成完整的成本与失败分析，不能以缺少正向结果推断工程未完成。

### 12.4 成本与预算单位

| 口径 | 用途与报告方式 |
|---|---|
| 确定性预算单位 | 权限、预约、执行记账和恢复一致性；当前 `compute_seconds` 是按冻结 workload policy 计算的单位，不是 elapsed seconds |
| 实测资源消耗 | 在可取得范围内记录墙钟时间、CPU 时间、存储、模型调用与 usage；恢复、重试和验证成本一并报告 |
| 人工与一次性工程投入 | 记录准备、干预和修复；区分一次性建设成本与后续单批次运行成本，共享成本说明归属 |

当前 charge 还依赖单窗口参数扰动与验证工作量形状，后继执行路径必须与其预算语义一致。历史字段、旧 charge 和原 JSON 不因名称容易误解而迁移或重算；新报告明确单位即可。[R16]

优先读取现有运行记录并在新任务必要阶段记录成本，不为测量再跑一遍完整流程，也不因本节建设通用监控平台。[R12]

### 12.5 决策规则

如果 LLM 在候选质量和总成本上没有显示价值，不以“保持 Agent 化”为理由继续扩大调用。可以将其收缩到假设构造、研究解释或搜索空间设计，由便宜的搜索方法承担大量候选生成。

结论限定在实际研究问题、数据、预算与可执行子集内。狭窄单窗口试验不能证明 LLM 在一般因子发现中无用或普遍优越；单批次观察也不自动证明稳定增量。下一步投入依据具体瓶颈和现有证据强度决定。

盈利不作为工程验收标准；但长期没有可测量的研究增量时，应调整研究方法和投入，而不是只继续完善工程证明。

## 13. 研究问题驱动的实施顺序与完成条件

以下顺序以可回答的研究问题为起点，不采用“先改全局规则、再接通执行与选择、最后澄清评价对象”的依赖。它不是新资格体系，也不要求额外审批包、管理服务或完整门禁矩阵。

| 顺序 | 交付范围 | 完成条件 | 首轮范围边界 |
|---|---|---|---|
| 1：定义研究问题 | 评价对象、主指标、训练与调参范围、生成可见信息、评价暴露历史、对照与成本口径 | 在现有任务文档中明确能回答的问题、所需证据及结论范围 | 不以新正式选择体系或全局规则修订为前置 |
| 2：最小生成与执行闭环 | 冻结前请求/响应、提案映射、能力检查、受限 profile 或合规子任务组织及阶段恢复 | 候选由各方法实际产生，能够执行、拒绝、恢复和留证；评价前集合冻结 | 不同时泛化所有 AST、参数扰动、模型和策略 |
| 3：小规模对照 | 使用现有字段与算子，按冻结设计执行并汇总结果、成本及可取得的阶段性能记录 | 产出可核验的探索报告，保留原 verdict、失败与未知成本 | 不要求正式选择成功、Registry 晋级或盈利 |
| 4：按瓶颈扩展 | 必要字段、多窗口扰动、自适应 Discovery、正式预测选择规则，或有依据的共享计算与并行优化 | 每项工作对应已观察到的需求及明确后继范围 | 不自动引入 LLM 推理特征、任意代码、新 harness 或 sealed confirmation |

研究设计先于生成和执行，结果分析再决定后继投入。依赖、隔离输出与资源允许的实现准备可以并行；第 4 步不是必须完成的固定功能包。已有字段与算子足以回答问题时，不为阶段名称增加功能。

运行时优化按第 9.3、9.4 节穿插实施：研究问题与 profile 确定后，优先独立交付同次结果核验去重；最小闭环同步补齐所需阶段恢复；信号/PIT 共享和进程并行由后续实际成本决定。研究与优化采用独立提交和完成条件，集中安排获授权的必要验证，不把全部优化捆绑为首轮前置条件。

FR-03 按第 5.5 节作为独立工作线尽早判断重开条件，与第 1 步及第 2 步中不依赖 live runtime 的准备并行。首次真实生成接入前按资格结果选择入口，不等待无限期排障，也不把完整 P13/P14d-C 建设捆绑为所有研究路径的前置条件。各入口仍须满足自身实际资格和接受范围；SDK 解阻、研究报告与运行时优化分别记录完成状态。

### 13.1 第一轮建议任务范围

第一轮采用第 8.4 节的固定 LGB 预测探索方向，交付以下最小闭环：

1. 在现有任务说明中确定主指标、数据与模型配置、可见信息、候选结构限制、比较规则和资源上限。
2. 补齐有界生成与候选映射，保留无效、拒绝、重复及修订记录；优先使用当前字段与算子，以及与单窗口执行规则兼容的子集。首次真实生成接入前，按第 5.5 节的 FR-03 资格结果确定入口及其适配范围。
3. 根据实际依赖选择受限显式集合或冻结批次引用子任务；复用确定性服务，按第 9 节补齐实际阶段的完成记录与恢复，明确新 profile 的真实完成范围。
4. 在实际运行授权与预算内开展小规模对照，结合本轮必要执行记录可取得的阶段性能数据，交付提案来源、可用预测证据、原 verdict、失败与成本均可追踪的探索报告。

纯实现或文档完成不等于已完成对照研究；未授权或未执行的运行明确列为未完成。正式调用、费用及外传仍按已有授权办理，旧 campaign 耗尽的额度不能续用。本文修订本身只更新设计，不启动这些运行。[R1][R9]

若首轮改为完整策略链研究，应在生成前改定研究问题和任务范围，并采用其所需证据；不能在获得结果后切换评价对象。通用候选框架、多窗口扰动、正式选择改造和全局 LLM 执行权限开放不捆绑进本轮。

开始前在现有任务记录中简短说明“改什么、复用什么、只新增什么”。结束后记录新增能力、实际执行的验证、复用范围和未解决限制。不要为这些说明再建立机器可读审批包。

### 13.2 全局完成边界

新功能能够使用，不等于具备盈利能力；工程接受不等于科学通过；新组合通过局部核验，不等于整树继承旧资格。

所有未执行的验证、未知的成本、未暴露数据不足和不可取得的历史原件均须明确保留限制。不补写历史事实，不通过放宽旧谓词或覆盖失败来制造完成状态。

### 13.3 任务派发、模型与并行安排

具体任务见[实施任务与模型分工](post-hm-mvp-execution-plan.md)：主线先完成研究设计与公共身份接口，再并行推进生成、候选准入、报告准备和适用的核验去重；执行与管理入口在公共接口稳定后接线。FR-03 独立判断重开条件，首次真实生成接入前按第 5.5 节汇合。

默认由 `gpt-6.1-sol` 承担实现，`gpt-6-luna` 承担范围明确的资料整理、基线生成器和报告展示；复杂契约、证据核验与恢复语义使用较高思考等级，`gpt-6-astra` 留给有明确疑点的困难设计或升级处理。上述分配是按本项目任务风险作出的工程建议，具体配置与依据见分工文档，不表示已经完成实施或取得资格。

通常保持一个主协调者和两个执行代理；只在输入稳定、文件所有权独立、额度与资源允许时增加第三个执行代理。共享契约、依赖锁、权威写入和恢复链保持有序。开发代理并发数不等于科学作业并发数；获授权的必要验证由主协调者合并安排，避免各代理重复启动同一昂贵流程。

## 14. 来源与基线索引

以下链接固定到已审阅提交。实施时以实际工作基线核对相关差异；本文中的后继 profile、显式候选集和自适应流程属于建议，不应被当作链接版本已经实现的能力。

- **[R1] HM-MVP 冻结身份、接受范围与科学结果**：[发布记录](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/releases/hm-mvp-component-v2-freeze-marker.md)。
- **[R2] Agent 权威边界、provenance 与 campaign 设计**：[架构总览](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/architecture/overview.md)、[Agent 与 campaign](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/architecture/agent-and-campaign.md)。
- **[R3] Hosted 管理侧注册与绑定核验**：[hosted_campaign.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/hosted_campaign.py)。
- **[R4] 固定 Hosted 业务输入与 loader profile**：[hosted_inputs.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/hosted_inputs.py)。
- **[R5] 模板参数槽与有限枚举 manifest**：[enumeration.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/enumeration.py)。
- **[R6] 字段映射、算子翻译与当前研究语义**：[expression.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/research/qlib/expression.py)、[研究与回测](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/architecture/research-and-backtest.md)。
- **[R7] 固定模型、预测研究指标与回测信号边界**：[workflow.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/research/qlib/workflow.py)、[研究与回测](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/architecture/research-and-backtest.md)。
- **[R8] 有限家族选择实现与统计限制声明**：[campaign_selection.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/campaign_selection.py)。
- **[R9] 仓库规则与实施授权边界**：[AGENTS.md](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/AGENTS.md)。
- **[R10] 当前路线图及可选后续工作**：[PLAN.md](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/PLAN.md)。
- **[R11] 成本与返工问题的观测依据**：[HM-MVP 实施复盘](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/hosted/hm-mvp-implementation-retrospective.md)。
- **[R12] 证据复用、局部验证、恢复与资源约定**：[implementation-discipline.md](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/guides/implementation-discipline.md)。
- **[R13] Validation、Registry、复现与 OOS 权威范围**：[验证与 Registry](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/architecture/validation-and-registry.md)。
- **[R14] 当前整体范围与数据限制**：[README.md](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/README.md)。
- **[R15] 冻结候选请求、提案与编排约束**：[autonomous contracts](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/autonomous.py)、[Orchestrator](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/autonomous.py)。
- **[R16] 单窗口扰动、预算单位与 Validation outcome**：[data_qualified_release.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/data_qualified_release.py)、[autonomous_execution.py](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/autonomous_execution.py)、[ValidationService](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/validation/service.py)。
- **[R17] 派生字段、复权与 PIT 来源范围**：[QlibViewSpec](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/qlib_view.py)、[view converter](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/data/qlib_view.py)、[compact PIT](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/research/qlib/pit_evidence.py)、[PIT application](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/pit.py)。
- **[R18] Family、Governor 与固定 Hosted 装配**：[campaign contracts](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/campaign.py)、[Governor](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/campaigns.py)、[Hosted loader](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/hosted_inputs.py)。
- **[R19] 现有提案结构与受限编译入口**：[Agent contracts](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/contracts/agent.py)、[proposal compiler](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/application/proposals.py)。
- **[R20] 结果核验、信号构建、回测发布与作业资源边界**：[ResearchResult verifier](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/research/qlib/result.py)、[signal builder](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/research/qlib/signal.py)、[backtest service](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/backtest/service.py)、[storage supervisor](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/src/quantos/infrastructure/hosted_storage.py)。
- **[R21] FR-03 当前资格、重开条件与 SDK 决策**：[状态与维护入口](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/status/fr03.md)、[官方 SDK ADR](https://github.com/Dedicatus547/quant-research-os/blob/639b3de49fe3a621bb43e636d1e43b99f3eed1b3/docs/adr/0002-official-codex-python-sdk.md)。
