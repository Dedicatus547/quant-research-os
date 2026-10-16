# QuantOS：路线图审查修订与近期实施切片

版本：v0.2，审查修订与执行计划补全版  
日期：2026-10-14  
固定源码基线：`4b9961f3d3f7c58fa81424e719a10e877e96305c`  
替代范围：v0.1 的近期优先级、阶段依赖、记忆接入设计、评估设计和工作包；外部平台比较保留为背景，不作为直接验收依据。  
性质：可供 Codex 拆分实施的修订计划，不是已经实施、已经验证或已获得运行授权的证明。

## 0. 使用边界与本次核查

本次读取了 v0.1 原文件，并通过 GitHub 在上述固定 SHA 抽查 Ledger 契约与检索实现、SDK producer 与提示投影、Discovery blocker、前序 C 义务说明、历史故障归因、成本分析、P13 冻结范围、Qlib volume 转换和实施纪律；查询了原 CI job 的步骤。没有运行仓库测试、模型调用、科学实验或完整资格验证，也没有修改远端仓库。

2026-10-14 本地复审后修订：沿用上述基线及已核对材料，补清固定经验装入、冻结输入装载、配对调用身份、执行入口与 P0 完成条件，并加入提示容量和确定性对照要求。本轮仅补充计划及其证据材料，不启动所列实施或运行工作。

2026-10-14 执行材料补全：已只读核对 A1 两次真实 SDK 请求/响应、既有故障与成本原件、P12/P13 材料，以及本地 snapshot/view 的字段、时点和来源身份。形成配套的 [P1 真实案例表、R0 数据可用性结论与 R1 固定设计](quantos-evolution-p1-r0-evidence-2026-10-14.md)。本次结论是 **P1 调查完成、P2a 暂缓；R0 选择复权成交量，R1 先做字段接线与两个固定候选的离线准备**。§10 为据此确定的执行清单；不再要求下一位 Codex 从头重做 P1/R0。

本计划服从 `AGENTS.md`、当前任务授权及 `docs/guides/implementation-discipline.md`。尤其是：新增或运行测试须遵循用户已有明确授权；纯文档、格式或路径变更不自动触发科学重跑、全量矩阵或新的资格流程。本文列出的验收用例是后续获授权验证的目标，不是本轮自行启动验证的授权。[Q10]

实施时记录实际 HEAD 及与本基线的相关差异；不得仅因 HEAD 变化就否定全部历史证明。已完成内容按 originating tuple、传递依赖及适用范围复用。

## 1. 审查结论与必须修正的判断

**采纳 Codex 审查的主要结论。v0.1 的长期方向保留，但其 P2/P3 接口假设、C 条件措辞和近期依赖需要实质修订。**

| v0.1 的问题 | v0.2 的处理 |
|---|---|
| 容易把已有 Ledger 理解成接近可用的学习系统 | Ledger 是可审计基础；经验的有效性、修订、时点与实际模型输入仍有缺口。近期只验证冻结经验视图。 |
| 将记忆建设预设为近期主线 | 先判断 Agent 是否存在可用历史信息改善的真实决策；没有目标即可停止试点。 |
| P3 同时包含工具、reviewer、步骤与停止策略 | 首片只处理当前入口支持的上下文选择、提示呈现和冻结候选选择；不改变 Qlib Workflow。 |
| 要求制作“P14d-C 原 DoD 差距表” | 改为映射已有 live-runtime 义务、A1 证据及剩余组合缺口，明确后继接受范围。没有一套已冻结、完整独立的 C 场景矩阵。[Q5] |
| 经验输入组与旧 SDK 对照组可能混用接口 | 两组均使用同一后继接口与配置；先验证无经验时的业务行为兼容。 |
| P2/P3 的通用能力范围与工期不匹配 | 删除通用能力的日历承诺，按可独立完成的小切片与实测投入安排。 |
| P5 看起来是 P4 后的阶段 | 前向留证不依赖代码自修改；数据采集与事前预测分开标注。 |

当前产品事实表述为：**具备可审计研究闭环，正在验证经验复用是否有效。**“具有可验证学习能力”保留为发展目标，不能写作已经证实的现状。

### 1.1 原结果的口径更正

A1 的工程闭环能力与科学结果分开；不由 A1 自动授予完整 P14d-C 或 SDK Discovery 资格。已有价格空间观察支持暂停同类扩量，不支持“LLM 投研普遍无效”。

按用户提供的 Codex 本地原件审查，B2 完整口径为：9 个请求、6 个可比较预测来源、3 个缺源、720 个共同日；LLM 相对最佳基线的观察增量约 `-0.0008272`，组成项增量为 `null`。`null` 不是零，也不证明组合机制改善或退化。上述更精细数值在本次作为“Codex 本地核对结果”采用，没有独立读取本地完整预测原件。原报告定位为：

`artifacts/hosted-evidence/a1-b2-20261012-01/b2/prediction-followup-r6/report-bf465a3701b3a697220b059eea2f14088363173964f7a53d76796b1a3844c0b8.json`

原 CI job 中格式检查失败，后续 lint、类型检查和 pytest 跳过。本计划不把跳过写成失败或通过；修复格式问题不等于需要重新运行历史科学资格。[Q13]

## 2. 实施顺序与依赖

近期不是一条从 P0 到 P5 的线性建设链。

| 工作包 | 前置条件 | 交付与退出条件 |
|---|---|---|
| P0：集成基线与范围纠正 | 已有源码和原 CI 记录 | 修复受影响格式；预先确定且已获授权的必要检查通过后，声明对应集成基线通过；修正 C 义务映射及当前状态。 |
| P1：Agent 可影响损失与评估对象 | 历史报告可读；不必等待全量 CI 才做只读分析 | 本次调查已完成：七行真实案例及 rubric，尚无值得启动记忆比较的已证实决策损失；不启动 P2a。 |
| R0：R1 可用性审查 | 可用数据与既有资格说明 | 本次已完成路线选择：公告样本不足，选择现有 snapshot/view 中的 adjusted_volume；数据已存在，执行接线未完成。 |
| P2a：冻结经验试点 | P1 有可行动目标；接入设计与资源范围明确 | 冻结人工经验、真实输入接通、受控配对比较；只证明这类上下文处理是否有用。 |
| R1：一个新研究问题 | R0 已选择 adjusted_volume；实现与实际科学执行分别按范围授权 | R1a 字段接线、R1b 固定输入与报价、R1c 两个固定单特征候选的回顾性比较；字段工程接受与科学结果分开。 |
| P2b：自动记忆后继 | 有经验复用/维护需求及可测量增量空间 | 自动提案或局部修订相对廉价静态基线有价值；不直接建设通用知识生命周期平台。 |
| P3a：有限提示/选择优化 | P1 评估可用且存在对应瓶颈 | 改善质量或达到预声明非劣并降低总投入；不强制等待 P2b，亦不因 P2a 负结果禁止独立提示优化。 |
| P4：代码级自修改 | 明确的代码瓶颈、独立评价和回退能力 | 条件性候选，不进入近期必做清单。 |
| P5：前向留证 | 相应数据规则或决策流程已冻结 | 前向采集可先行；前向预测须在结果未知时落盘；两者不依赖 P4。 |

P1 与 R0 本次只读准备已经完成，原件与核对范围保留在配套材料。P0 的稳定集成工作不应成为无关资料分析的门禁。当前执行顺序为 P0 与 R1a 的独立部分并行准备、共享改动有序集成，再完成 R1b；R1c 只在其具体运行范围获授权后执行。P2a 保持暂缓，不作为 R1 前置。

继续一个产品、最多两个短期 worktree：平台切片与研究切片。不要将原 FR-03 分支长期经营成第二个平台。共享 contracts、PIT、validator、持久状态语义的改动集中审阅；同一物理卷上的重任务遵循既有租约与合计预算。[Q5][Q10]

## 3. P0：修复当前缺项，而不是重新认证整个项目

### 接入位置与范围

格式涉及 `src/quantos/application/sdk_prompt.py` 与现有 `tests/unit/test_sdk_prompt_projection.py`，不另造重复测试文件。CI 配置位于 `.github/workflows/ci.yml`，依赖版本以实际 lock 与接受组合为准。

先修复格式、检查实际 diff；随后按已有授权和稳定里程碑所需范围运行验证。默认依赖组合与 FR-03 已接受的后继 SDK 组合分别记录。默认环境绿色不意味着所有 SDK/runtime/model 组合都通过。

C 义务映射只需在既有任务说明或状态页中形成一个短表：

`已有义务 → 原证据及 originating tuple → A1 覆盖 → 相关变更影响 → 最小缺口 → 后继接受范围`。

不得虚构原 C 场景清单，不把 A/B/HM 矩阵全部机械叠加。源码和传递依赖未变化、身份可核对的部分复用；必要补验按实际影响说明。A1 原件不改名追认为新资格。[Q5]

### 完成条件

指定提交的实际检查、跳过项、适用依赖组合和未解决项可核对；旧 V4/历史报告保持原身份与语义。不因为格式修复重跑 B2、P10/P13 或所有历史资格；本工作包不新增模型调用。

预先确定且已获授权的必要检查通过，才声明相应集成基线通过。存在未解决失败或必要项未执行时，分别报告修复进度及验证未完成，不声明绿色基线。记录齐全不等于检查通过；这一状态区分不增加测试范围或新的门禁。

## 4. P1：先证明存在 Agent 能影响的损失

### 4.1 复用材料

先读 `post-hm-next-failure-diagnosis.md` 和 `post-hm-next-cost-analysis.md`。成本报告已有 249 个阶段 completion；计时可能嵌套，不能相加或用差值臆测瓶颈。缺失用量与成本记为 unavailable，不记零。不为补齐性能表另跑一轮科学实验。[Q7][Q8]

用现有任务说明和一份小型案例表记录以下信息，不建设新的可观测性或评测服务：

| 信息 | 用途 |
|---|---|
| 原故障/决策来源与 source group | 回到原件，并防止同一案例换写法跨集合泄漏 |
| 当时可见输入和真实输出接口 | 确认不是给未来假想 Agent 做评价 |
| Agent 实际可选动作 | 区分“选择错误”和“根本无权改变” |
| 更好的历史信息可能改变哪一步 | 形成可被否定的机制假设 |
| 已知确定性修复、可用来源及成本 | 不用记忆掩盖工程缺陷或缺数据 |
| 现有确定性规则能否直接完成该决策 | 判断廉价规则是否已足够，并记录其适用范围与限制 |
| 正确答案/可接受答案集合及不确定性 | 没有未来收益金标准时不伪造标签 |

对可规则化的合规选择、停止或不适用判断，先核对已有程序规则是否足够。能直接完成时，将其作为廉价确定性对照；无需为此新增模型组或评测平台。A/S 胜出只说明上下文改善了模型表现，是否值得调用模型还需结合该对照和总成本判断。

### 4.2 三类问题的处理

**确定性缺陷**：路径错误、输出转换失败、PIT/覆盖问题、统计量无定义处理等，优先修复或正确表述其工程语义。历史经验可以帮助诊断，但没有代替修复的因果路径，不作为“记忆消除了该执行故障”的主要指标。[Q7]

**Agent 可影响的决策**：当前请求下的候选选择、停止建议或 rationale 中的证据与结论边界。只有能明确构造真实输入和可接受行为的任务，才进入 SDK 试点评价。

**尚无生产入口的能力**：工具式检索、通用故障修复、开放研究规划。可作为独立离线功能实验，但不得将其分数算成现有 SDK 生产能力；不得为了给 P2 凑评价任务先搭一个新 Agent 平台。

当前 SDK 输出为 `candidate_ref + rationale + request_stop`，要求从冻结选项选择；工具被禁用且 MCP server 为空。不能将它按能够运行修复代码的开发 Agent 来评价。[Q2]

### 4.3 P1 的决策出口

优先选择一个决策类型，而不是同时铺满所有 Agent 基准。结论允许为：

- 存在可行动目标：给出任务、输入、动作、评分与预算，进入 P2a。
- 没有可行动目标：暂停记忆系统接入，保留静态运行说明，投入确定性修复或 R1。
- 证据不足：在下一项本来就获准的执行中补充必要观察，不为证明记忆价值制造额外运行。

这些是建议报告结论，不是仓库已经存在的状态枚举。历史记录数、反复查看次数不能直接等同于能被 Agent 记忆消除的成本。

### 4.4 本次 P1 的实际出口

已完成[七行真实案例及来源分组](quantos-evolution-p1-r0-evidence-2026-10-14.md#2-p1真实案例表)。A1 两次请求属于同一来源组，输入已经明确给出两步候选/停止规则，模型实际使用了前次 trial 并保留结论边界；本次未发现需要额外经验修复的错误。四份常数预测失败、旧 signal 缺证、新 signal 诊断、嵌套成本和有限空间生成分别保留其实际原因及可行动性，不能凑成七个独立 Agent 失败样本。

**当前出口：P1 调查完成，P2a 暂缓。** 已有材料可以做解释与开放开发示例，不能支持未见任务泛化或记忆节省结论。以后只有新增真实案例能连起“实际错误—可改变动作—当时允许取得的历史—简单规则不足”这条链，才重新决定 P2a；不设强制样本数，不为填案例启动调用。§5–6 保留为条件触发后的设计，不属于下一轮默认实施。

## 5. P2a：冻结经验视图与输入接通

执行状态：**暂缓**，原因见 §4.4。本节是保留的条件性设计；当前不要修改 Ledger、SDK profile 或 loader 来提前实现它。

### 5.1 首片明确不做什么

不实现通用市场/版本/双时间搜索过滤，不实现跨任意知识对象的 supersede 图、自动撤回传播、冲突仲裁或通用“当前有效知识”解析层；不增加向量数据库；不建立新 Registry。

现有 Ledger 具备节点类型、authority、campaign 与 sealed 访问边界；检索采用词频与稳定哈希排序；`parent_object_hashes` 是来源关系，不能当成修订生命周期机制。`search()` 重建索引，`build_context_pack()` 再次搜索复核，存在重复路径，但尚不能据此认定为主瓶颈或取消复核。[Q3][Q6][Q15]

### 5.2 冻结经验的表达

首片使用少量人工审核、带来源的经验条目，形成一个固定快照。复用 `HUMAN_REVIEW_STATEMENT / HUMAN_REVIEWED` 语义及其真实审核绑定；模型草拟但未获人工审核的内容仍属于 proposal，不得由程序伪造人工审核。

条目至少表达：陈述、适用任务/版本/市场范围、来源对象引用、整理时间，以及与本试点相关的时间/污染限制。字段可以复用现有字段或采用一个窄的 typed statement payload，不为字段名重构 Ledger。

冻结时完成本试点所需的来源、适用范围、时间和集合隔离检查，并保存显式允许条目集合。运行时只消费这个已冻结集合，不调用不存在的通用有效性解析器。存在未知时间且影响任务有效性的条目不进入相应评价；首片不宣称支持任意历史 as-of 查询。

这里的经验对象允许列表是本切片需要接通的约束，不是声称当前 Ledger 已有该过滤字段：若不能用现有完整快照与 policy 恰好表达，则在明确的后继搜索策略中增加仅针对经验对象的冻结 hash allowlist，并使 `search()` 与 `build_context_pack()` 的重建核验消费同一绑定。原有必要证据不受该经验 allowlist 排除。不得在搜索后手工删改结果，再伪装成原 policy 生成的 ContextPack，也不得从完整 ledger event chain 中任意删事件冒充合法快照。此窄约束不扩展为通用时间/状态过滤引擎。

允许使用不等于保证装入：当前搜索只返回词频得分大于零且进入 `max_results` 的对象。S 组须由明确的后继上下文构造规则按冻结顺序完整装入约定经验集合，不依赖查询命中或与基础证据竞争排名；按任务检索的差异留给 R 组。A/S 配对请求的基础证据内容、相对顺序及必需 trial 历史须一致，经验使用单独预留的条目和字节空间。以实际进入提示的原对象 hash、内容和顺序核对这种一致性；请求及分组身份本身可以不同。装入规则必须参与同一重建核验，不能在搜索结果或 prompt 生成后手工追加。[Q3]

已有错误经验通过新快照移除或纠正，旧快照仅保留作历史解释/回放，不静默覆盖。当前启用快照由既有配置显式绑定；冻结经验版本在一次比较中不改变。此范围不等于完成自动撤回传播。

**机器验证只认证引用与结构，不认证自然语言归纳为真。** `HUMAN_REVIEWED` 也不自动变成 `DETERMINISTIC_EVIDENCE`。即使每条陈述都有正确来源引用，仍需评价来源是否支持该陈述及其适用范围。[Q6]

### 5.3 真实源码路径与最小变化

| 接入环节 | 既有源码/符号 | 首片应做的变化 |
|---|---|---|
| 身份、authority 和来源 | `src/quantos/contracts/ledger.py`：`ResearchLedgerEventV2`、`ResearchLedgerObjectRef` | 保留既有 authority 语义；定义或复用窄的人工经验 payload。不把经验伪装成 EVIDENCE。 |
| 检索与完整上下文 | `src/quantos/application/ledger.py`：`search()`、`build_context_pack()` | 复用已有源对象、权限及可复现核验；绑定冻结经验 allowlist、S 组固定装入与基础证据保留规则，采用明确后继策略及相同重建路径。不改旧策略语义或引入通用生命周期。 |
| 冻结业务输入包与 loader | `src/quantos/contracts/hosted_inputs.py`：`HostedFrozenBusinessInputs`；`src/quantos/application/hosted_inputs.py`：装载与 orchestrator 构造 | 核对后继搜索策略解析、经验原件及真实审核绑定、初始 Ledger inventory/snapshot，并贯通向 orchestrator 的传递。现有输入包直接绑定旧搜索策略类型；只在直接函数调用中可用不算接通。[Q16] |
| 投影契约 | `src/quantos/contracts/sdk_prompt.py` | 增加明确的后继投影标识、policy 与 hash；旧 policy、前缀及字节边界保持历史身份。 |
| 投影实现 | `src/quantos/application/sdk_prompt.py`：`prompt_projection()`、`bounded_prompt()` | 新分支只接受约定的经验 schema，保留原对象 hash、authority、来源及限制；未知类型或字段继续拒绝。 |
| SDK profile/request 身份 | `src/quantos/contracts/sdk_producer.py` 及实际 version dispatch | 显式绑定后继 profile/投影/冻结输入；检查影响到的 serializer、verifier 与 CLI 解析。不全局放宽旧 V4。 |
| 实际模型入口 | `src/quantos/application/sdk_producer.py`：`model_configuration()`、`build_reservation()` | 后继请求确实使用相应投影；reservation、配置、输入 hash、真实 capture 可相互追溯；保留现有工具与输出权限。 |
| 现有受影响验证 | 原 SDK prompt projection、producer、Ledger 用例 | 获授权时复用受影响用例并补最小反例；不默认重跑全部科学资格。 |

现有 V4 仅允许 `EVIDENCE`、`CAMPAIGN_TRIAL`、`VALIDATION_REPORT`、`RESEARCH_RESULT`，其他类型直接拒绝。因此“Ledger 写入成功”不构成 P2a 接入完成。[Q1][Q9]

后继版本名称由仓库版本约定确定，不能直接改旧常量再声称原 V4 回放未变。也不能仅增加一个 node-kind allowlist 项就允许任意 JSON 进入模型输入；窄 payload 必须有明确验证和来源语义。

### 5.4 贯通与归因要求

在任何试点模型调用前，用已保存材料或合成夹具核对：

`源证据 → 审核陈述/冻结集合 → 初始 Ledger 与策略的冻结业务输入包 → loader / orchestrator → 检索与 ContextPack → SDK 完整 request → 后继提示投影 → launch reservation`。

获授权进行实际比较时，利用原有 capture/manifest 出口保存足以核对实际输入的身份；只出现一个 memory 文件、只通过 Ledger 测试或只在文档示例 prompt 中出现条目，均不算接通。

对照组和经验组必须使用**同一后继 SDK 接口、投影实现、模型配置与权限**。对照组仅关闭新增经验，保留原本必须的 Evidence/ContextPack/trial 历史。先核对后继空经验与旧 V4 的候选集合、业务绑定和权限语义兼容；不要求新旧 schema/hash 的原始字节相同。旧 V4 原件仍按旧实现解释。

原 V4 最大提示为 24,576 UTF-8 bytes，并有明确溢出拒绝策略。首片默认不改变这个已知边界；新增经验须有预分配空间，不挤掉必须保留的证据或悄悄截断。需要变更上限时，作为明确后继配置与资源变化测量，而不是自动翻倍。[Q9]

A1 第二次实际提示为 23,942 bytes，距原上限仅余 634 bytes；不能据此假定剩余容量足以容纳带 authority、来源 hash 和限制的经验包。调用前复用保留请求，核对代表性及已知较长请求的后继完整投影字节数，包含经验元数据开销；同时保留既有捕获与响应 frame 边界。容量不足时，在最终比较前缩小经验范围，或明确设计后继投影/预算变化。评价任务及容量规则须事前确定；已冻结任务的超限按失败规则留证，不临时删除较长案例来改善分数。[Q19]

### 5.5 获授权验收时覆盖的最小性质

检查 S 组约定条目完整进入实际提示，A/S 基础证据及其相对顺序一致，冻结业务输入能够经 loader 接通；无效引用、未知 schema、错误 authority、越权/受污染来源、错误快照及超限内容被拒绝；经验文字不能扩大工具、预算、可见数据或停止权限。历史 V4 仍保持原接受与拒绝行为；同一冻结输入可重建相同后继投影；恢复不重新调用模型。

自动检查结构和权限；自然语言结论的证据支持度由明示 rubric 和盲评/审核处理，不宣称能用 hash 证明。

## 6. 配对评估：先回答“小改动是否有用”

### 6.1 先两组，再按需要扩展

| 组别 | 输入/方法 | 能回答的问题 |
|---|---|---|
| A：现有行为基线 | 相同后继接口；没有新增经验；保留既有必需历史 | 当前方法表现如何 |
| S：静态经验基线 | 保留 A 的基础证据，按冻结顺序完整装入人工审核的经验集合；不按查询筛选或在评价期间更新 | 这种整理后上下文是否有帮助 |
| R：条件性检索组 | 从同一冻结经验库按任务检索；沿用相同输入上限与权限 | 当库变大/静态包不合适时，检索是否值得增加 |
| U：后续自动更新组 | 明示反馈范围下自动提案/更新；与 S 或 R 比较 | 自动化维护是否有额外质量或成本价值 |

先做 A/S，不一次性执行完整 2×2 或四组搜索。S 胜出只说明“这套人工整理上下文有用”，不能写成“自动持续学习有效”；S 无增量也不证明所有未来记忆设计无效。A 与 S 的源材料宇宙和权限应相同，但 S 含人工归纳，这种额外劳动与知识加工必须计入成本和结论。需要隔离摘要加工与原始历史增量时，再增加同预算原始材料对照，不作为首片默认负担。

如果静态经验足够好、维护又便宜，长期保留静态方案是合格的产品决策，不必为了“自进化”名义继续自动化。

### 6.2 评价对象与指标

P1 选定一个主任务和主指标。下面是可选 rubric，不要求本轮把所有类型都实现。

| 任务 | 评价单位 | 主要指标 | 错误/拒答处理 |
|---|---|---|---|
| 检索组件 | 一个来源分组中的查询及可接受 evidence 集合 | 固定条目/字节预算下的必要证据覆盖和错误引用 | 未检得与检得错误分开；这是组件评价，不伪称 SDK 工具能力 |
| 已有 SDK 候选决策 | 一个冻结 request 与约束决定的可接受候选集合 | 合规、非明显受支配/不适用决策的比例；仅使用可核对规则 | 无法预知最佳未来 IC 时不制造“最优候选”标签；rationale 的虚假确定性单独计分 |
| 停止建议/结论边界 | 一个具有明示停止规则或证据限制的 request | 与原规则相符的建议及限制表述 | 不通过一律停止刷分；保持 `candidate_ref` 必填及处理当前 trial 后才判断停止的语义，不当作跳过本次执行，不擅自增加 null/拒答输出协议 |
| 诊断能力实验 | 一个故障来源组的可见输入与可支持原因 | 原因分类、证据支持度、未知项保留 | 根因证据不足时允许“不足以判断”；不能把猜中未提供答案当可靠诊断，也不算已接入能力 |

错误分为：权限/证据完整性破坏；有来源却结论不成立；合法但无效或无帮助。不要把这些混成“任务完成率”。存在多个合理答案时，使用预声明可接受集合或按 rubric 盲评，不强制模型复制人工原句。

### 6.3 配对、重复与分母

冻结任务集合、源材料、模型标识与可观测版本、reasoning 配置、候选次序策略、输入上限、工具权限、重复次数、超时/失败处理和停止规则。

同一任务下各组配对执行，顺序随机或交错，独立会话，禁止跨组历史残留。重复次数在看本轮比较结果前确定；每次都留存，不“重试直到得到满意答案”。API 不能固定随机种子时明确记录，不把相同 temperature 当作确定性保证。

首轮 A/S 默认评价单步响应：使用新建且明确绑定的试点 request/spec，复用 `prepare → launch → capture/manifest → 离线评分`。已有请求的内容可作为来源材料；不得原样重启已完成、过期或取消的请求。`step()` 会执行 `launch → submit → resume` 并可能触发 Qlib，因此不作为单步评测的默认入口；只有另行定义并获授权的闭环评价才提交业务 proposal 或调用 `step/resume`。单步分数不代表已经实现科学执行节省或完整 campaign 改善。[Q17]

在运行方案中将“任务来源组 × A/S 组别 × 预声明重复序号”映射到有效且独立的请求、调用身份、持久输出和预算记录，保留共同任务输入的绑定。现有 attempt identity 绑定 campaign 与 transport ordinal；同一 request 再次 `launch` 会复用已有响应，存在未对账 launch intent 时拒绝重发。新的预声明重复须使用满足冻结契约的新身份并占用相应额度；不能靠另开进程或换目录冒充独立重复，不能改写旧 request、重置 TTL、删除 intent 或把失败重试改名成重复。失败与 UNKNOWN 按原规则留证和计数；恢复/回放不算新样本。[Q2][Q17]

停止建议按真实生效点评分：业务服务先处理当前 trial，再在策略允许时接受 `request_stop`。不能把 `true` 的输出计为免除当前候选执行的节省；若后续研究的是闭环成本，需按实际 trial、receipt 与预算事实测量。[Q18]

对一个来源组先汇总其重复输出的组间差异，再以来源组为基本单位报告效果与不确定性。相同问题运行三次、改写三遍，不等于三个独立案例。样本不足时报告范围和不确定性，不强行声称统计显著。

新统计代码不应成为先建平台的理由；可以先输出配对案例表、差值分布和盲评结论。需要区间时，预声明适用的来源分组 bootstrap 或配对随机化方法；不得把金融时序 block bootstrap 原样用来证明 Agent 泛化。主分析与探索性分组分开。

30–50 个案例至多是开发工作量起点，不是强制规模或统计功效承诺。P1 若只有少量真实独立问题，应诚实做可行性试点或暂缓，不靠合成改写填满数量。

### 6.4 开发集、最终评估集与可见性

以原事件/故障及近重复来源家族分组；原日志、诊断、总结和改写案例继承同组。人工经验库不得包含最终任务的答案性总结。必须区分“历史病例检索测试”与“对未见病例的泛化测试”；前者可以有原病例记录，但不能借此宣称后者的能力。

开发/优化会话可读取开发任务、答案及反馈。最终任务在执行时仅向被评估 Agent 提供声明输入；最终答案、逐题评分和未发布结果由独立评估流程/人员保管，不挂载给优化会话，也不进入其日志或记忆源。文件只读不等于保密。[E1]

固定候选和所有预定重复提交完成后，再发布最终比较结果。发布后继续调参，则该集合成为已暴露开发资料；再次宣称最终独立评估必须使用新的未暴露资料。对人工也是同样规则。无法隔离时，报告为开放开发基准，不包装为 held-out 验证。

不要求一个新权限平台：在现有隔离能力中只挂载该角色应见材料，结合独立会话与结果释放纪律即可；若当前机制做不到，先降低结论强度，不声称已隔离。

### 6.5 成本与采用决策

分别记录部署时消耗与总投入：模型输入/输出、失败调用、检索/提示构建、人工整理/审核、维护、流程搜索及所需验证成本。复用已有 cost report；新缺项在本来获准的执行中轻量测量。不同预算的结果不可直接归因方法优劣。

晋级规则在最终比较前写明：主指标的最小值得改善幅度，或非劣界限与最低成本改善；它们应由实际任务价值和预算确定，不能由看见的分数反推。

允许四种结论：采用；保留静态方案但不自动化；无值得继续的增量；证据不足。后两种不扩大无止境搜索。模型自评“这条记忆有用”只能作诊断信号，不是唯一效果证明。ACE 的上下文更新实验支持研究这种机制，而不是为 QuantOS 的实际收益提供先验认证。[E2]

## 7. R0/R1：一个新的、可回答的研究问题

### 7.1 R0 的选择规则

核对现有数据覆盖、许可与可外发范围、时间/修订语义、所需工程变化和对照方法；选一条，而不是同时扩大公告与量价平台。

本次已按该规则完成选择，详见[数据可用性结论](quantos-evolution-p1-r0-evidence-2026-10-14.md#3-r0本地数据与适用范围)：正式 Evidence store 只有一篇已暴露的 P13 公告；P12 另有三篇历史记录，但权限为 UNKNOWN。公告路线暂不开展多公告质量比较。

数值路线选择 `adjusted_volume = volume_shares / adjustment_factor`，复用 snapshot `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` 和 view `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`。两份 canonical 来源各 1,596,969 行，文件字节摘要与 manifest 相符；这足以确定接线方向，不替代新字段的运行级 PIT。无需为 R0 新采集 Tushare 数据或重建 view。

选择不依赖 P2a 是否成功，也不为了让记忆显得有价值选题。

### 7.2 公告路线：抽取与市场预测分开

本路线当前为候选储备。只有新增允许用途明确、来源分组独立且有可用评价标注的材料后才重启；单篇 P13 与权限未知的 P12 不构成现成多公告数据集。

现有 `docs/p13-v2-freeze.md` 的资格只有单公告、带引用位置提示，产生一条 signal；它证明该组合下的接线与来源边界，不构成多公告质量基线。[Q12]

第一步仅比较规则抽取与 LLM 抽取：同一允许文档集、同等引用提示条件、同一字段/实体/时间定义、相同数据权限。按公告/修订来源组划分开发和评估，包含字段缺失、歧义和应拒答样本。指标分别覆盖引用定位、实体归属、发布日期/事件日期、字段精确性及不应抽取时的拒答。

采用既有 P13/Evidence admission 与下游接口的可复用部分；P13 runner 的 benchmark 限制按实际源码核对，不能当通用 runner 原样复制。不要为了首轮抽取质量评估先解阻 SDK Discovery，或先跑完整市场回测。

第二步仅在抽取产物质量和样本/时间覆盖足以回答问题时设计市场研究：冻结事件特征与基线，再评估市场增量、覆盖与成本。抽取胜出与市场增量都允许负结果；无市场增量不抹除抽取工具的工程价值。

### 7.3 数值路线：先选择一个 volume 含义

已有 Qlib view 的 `volume` 是 `volume_shares / adjustment_factor`，停牌时为缺失；不是直接的原始股数成交量。[Q11]

本次已选择按该约定变换后的成交量，逻辑名为 `adjusted_volume`。保持单位、复权因子来源和时点、停牌/零值/缺失的区别，以及跨公司可比性限制；不将 UNKNOWN 时点当作 PIT 安全，不将 `CONSERVATIVE_DERIVED` 解释为历史供应商版本证明。

随后贯通 canonical 字段 → PIT 可用性 → safe DSL 字段类型/允许范围 → `src/quantos/research/qlib/expression.py` 映射 → Qlib view → 新设计/候选范围与报告。只有 `$volume` 存在或新增字段字符串不算贯通。不得静默改变既有 close-only profile 的语义。[Q5][Q11]

获授权后先核对所选字段的转换与时间语义，再做单一研究问题及传统对照；不同时扩大操作符、家族、模型和 runtime。保留完整候选/机会/失败分母。

本次固定的研究问题与参数见[配套材料 §4](quantos-evolution-p1-r0-evidence-2026-10-14.md#4-r1-固定研究设计)：比较五日相对复权成交量和五日价格收益率两个单特征 LGBModel，使用同一数据、模型、label、实际 purge 与共同有定义日期。它是替代特征的回顾性比较，不能写成控制价格后的新增信息、未见时期确认或盈利检验。无需 LLM 生成，也无需先解阻 SDK Discovery。

除单 instrument PIT 和 Qlib 映射外，实施必须覆盖紧凑 PIT 的 `PITSourceSetEvidence`、collection source-map validator、`pit_evidence.py` 的字段来源以及后继预测核验器。旧契约/price profile 继续按原版本接受和拒绝；新字段通过明确后继身份接入。仅增加 `$volume` 映射不算 R1a 完成。

### 7.4 SDK Discovery 独立处理

`src/quantos/application/discovery_execution.py` 对 `SDK_CAPTURE` 仍明确返回 `SDK_GENERATION_ENTRY_NOT_QUALIFIED`。R1 不得绕过该检查、伪装 `HOSTED_HANDOFF` 或以 A1 成功作为删除 blocker 的理由。[Q14]

只有 R1 的实际运行入口需要 SDK Discovery 时，才列出相应最小后继接入：生成来源、顺序历史、执行身份、receipt/恢复与报告读取。否则优先使用该任务已有的适用入口，不把所有 transport 统一作为研究前置。

## 8. P2b/P3/P4：按证据启动的后继

### P2b：先比较自动化维护，不急于自动认证知识

只有经验使用有可见价值、人工维护成本或静态方案遗漏已成为实际问题时，先实现“自动生成候选经验 → 人工审核 → 冻结下一快照”。明确 source group、来源、适用范围和否定/修订关系；只在 campaign/评估轮次之间更新。

先相对 S/R 测质量与人工维护成本。机器 admission 继续只验证结构、来源与规则，不给自然语言归纳授予确定性真值身份。更复杂的冲突/撤回传播只由真实案例触发；未使用的通用能力不先建。

### P3a：限定在当前 Agent 入口，而非 Qlib Workflow

允许优化检索内容/顺序、经验和原始证据的呈现、提示措辞及冻结候选选择的指导策略；保留相同权限、数据、候选集合与资源上限。每次只改变少量可归因变量。

首版不引入 reviewer、多工具编排、任意代码或开放因子生成。后继需要它们时，分别声明新增接口与授权，而不是写成“改配置”。P3a 可以在不增加长期记忆时独立实验，不要求 P2b 先完成。

变更分层按实际权限，不按文件扩展名：更改 YAML 中的预算上限、硬停止、可见数据或工具权限，仍属受保护变更；在原规则内提出 `request_stop` 建议才属于有限策略空间。禁止候选改变评估答案、baseline、完整分母、费用记录或科学判据来通过自身评价。

### P4：不是近期主线

明确代码瓶颈出现后，才在隔离 worktree 中生成辅助代码补丁，复用原 PR/测试/发布机制。实现与评价分离、结果可复现且可回退；不因“能够改代码”而声称持续改进。

普通确定性修复无需等待 P4。需要一个修复，并不自动构成建设自动代码进化平台的理由。

## 9. P5：从能冻结的部分开始前向留证

**前向采集**：数据来源、采集字段、可用时间和持久记录规则确定后，可以在平台改进期间保存新到材料。它只证明未来研究有事前原始输入，不能证明当时已经生成预测。

**前向预测**：研究问题、实际执行流程、模型/配置、经验快照与输入规则冻结后，在结果可知之前保存真实预测/决策及其身份；之后再附加结果。补算历史预测明确标为回顾性执行，不能冒充事前预测。

每个前向 cohort 使用固定版本；途中改变提示、知识或模型时开启新的版本分组，不事后混为一个固定流程的验证。可以在开发侧继续改进，但不将新版本追溯套用旧 cohort。

不需要等待 P4，也不需要等到所有知识管理能力齐全。没有 live/外发/采集授权时，只完成配置与持久记录设计，不自行开始运行。既有已暴露时期和 sealed 数据边界保留，不能靠重命名恢复独立性。不涉及实盘资金，不凭短观察期宣称稳定 alpha。

## 10. 给 Codex 的近期任务边界

### 10.1 本次状态与后续队列

本轮用户授权是补齐材料与执行计划。本节的实现、定向验证及运行任务供后续执行使用，不表示本次已经实施或运行。优先读取[配套材料](quantos-evolution-p1-r0-evidence-2026-10-14.md)，不重复展开大型原件。

2026-10-14 模型与并行规划已补齐：[三会话、两 worktree 执行手册](quantos-evolution-model-worktree-plan-2026-10-14.md)。按该手册将 §10 的任务分配给 Sol/Luna，定义文件所有权、接口交接、共同基线、合并顺序和可复制提示词；Astra 仅作具体疑难的条件性复审。本轮未实际创建 worktree、提交或派发实施。

| 工作包 | 本次状态 / 依赖 | 下一位 Codex 的具体工作 | 完成与退出 |
|---|---|---|---|
| P1 | 只读调查完成 | 复用七行真实案例、source group、确定性对照及 rubric；仅有新证据时追加。 | 当前选择为暂缓 P2a，不再以“补案例”为理由调用模型。 |
| R0 | 路线选择完成 | 复用公告不足结论与成交量来源表；旧质量证明保持原 tuple。 | 选定 adjusted_volume；不重新抓取公告/Tushare，不重建未变化 snapshot/view。 |
| P0 | 待实施；独立于新字段研究 | 修复两个已定位文件的格式；在现有状态页补短 C 义务映射，按已授权范围完成必要检查。 | 满足 §3 才声明对应集成基线通过；失败/跳过如实保留，不重跑历史科学。 |
| R1a | 待实施；R0 已满足 | 按 §10.2 接通新字段、版本化 PIT、来源核验与后继字段研究 profile；保持旧路径语义。 | 新字段在真实执行路径有明确来源和拒绝边界，旧原件仍可按原规则读取；仅有字段字符串或函数示例不算完成。 |
| R1b | 待离线准备；依赖 R1a 的契约/接口确定 | 按固定设计准备两个 singleton、请求与比较政策，接通薄 CLI 的 prepare/status/run/compare，先完成 prepare 和具体运行报价。 | 可审阅的固定输入、实际 hashes、复用结论、完整执行预算和命令齐全；准备阶段新增科学/模型调用为零。 |
| R1c | 尚未运行；依赖 R1b 及明确科学执行授权/资源 | 执行有必要新增的主任务，复用可核验原件；按冻结比较政策出报告。 | 两候选完整分母与 failure/null 保留；报告工程状态、科学 outcome、共同日差值及成本后停止。负结果同样可完成研究报告。 |
| P2a/P2b/P3/P4 | 条件性后继，不在默认队列 | 只有 §4.4 的新证据或独立真实瓶颈才重新立项。 | 不提前建设 memory/reviewer/自动代码平台。P5 仅在其自身来源与运行范围具备时推进。 |

P0 与 R1a 可在独立文件范围内推进；contracts、PIT reader/writer 和共享执行身份的修改顺序集成。默认一个科学 worker、模型 num_threads=1，不从 CPU 核数推导并发。子代理仍服从实际任务授权，不由本计划自动派发。

### 10.2 R1a 的源码切片

下表是修改边界与检查目标，不是要求每个文件都无条件改动。优先复用已有 dispatch，新增内容限定于一个字段和两个固定候选。

| 切片 / 源码 | 要实现的行为 | 保留与失败语义 |
|---|---|---|
| 来源契约：`contracts/research_execution.py`；相关 PIT artifact 解析点 | 为 adjusted_volume 的 bars.volume_shares + adjustment_factor 来源建立明确后继身份，补 source-set/collection 完整性约束及旧/新分派。 | 旧 `pit-source-set-evidence/v2`、旧 collection 和已接受证明按原语义；未知字段、缺来源、错 hash 拒绝。 |
| PIT 构建与核验：`application/pit.py`、`research/qlib/pit_evidence.py` | 单 instrument 与紧凑截面路径使用同一两来源语义；核对窗口、键、日期、可用时间和算子延迟。 | PIT failure 硬拒绝；不能仅在 builder 扩字段而放过 source-map verifier；不得把因子当作不需时点的常量。 |
| 表达式与 signal：`research/qlib/expression.py`、`research/qlib/signal.py` 及其读取点 | 后继范围将 adjusted_volume 映射 `$volume`，贯通既有 signal builder；两份 Safe DSL authoring 使用同一明确 lag。 | converter 的除因子和停牌缺失语义不变；旧 close-only profile 不获得新增字段权限；非有限分数/缺交易状态继续按既有规则处理。 |
| 固定研究范围：`contracts/research.py` 的现成 Safe DSL authoring、`contracts/enumeration.py` 和 `application/enumeration.py` | 为 V/P 各生成一个合法 singleton family/manifest；新范围只接纳预先绑定的两个表达式，不引入开放生成。必要的研究配置置于窄的 typed 后继输入。 | 不改旧简写 authoring，不改旧 Discovery grammar；不伪造 HUMAN_REVIEWED、Agent proposal 或 generation response。 |
| 执行接线：`application/autonomous_execution.py` 及实际 profile/身份检查点 | 采用明确后继 `frozen-field-study/v1`（拟议名称），复用 adapter、stage checkpoint、真实退出及 receipt；保证新字段的完整执行/恢复路径。 | 不冒用原价格 profile 或既有科学授权；保留完整验证/稳健性子阶段，不为了便宜静默删 gate。 |
| 结果接线：`application/discovery_prediction.py`、其源码身份/PIT reader 与相关 contracts | 实际后继 metadata 能被 `publish_prediction_evidence()` 和 `compare_prediction_evidence()` 独立核验；用两请求 cohort 比较，保留 constant/null/原 outcome。 | 先核对 profile、来源 capsule、workflow reservation/completion、split audit 与新 PIT 的兼容。旧导入规则不静默放宽；缺证时保留 unavailable。 |

不要修改 Tushare acquisition、Qlib 模型/回测/会计实现或冻结历史文件。若发现现有 view 字节与 manifest 不符，先定位唯一缺失/变化依赖；不能直接重新采集或重冻全部数据。若新字段需要超出本表的通用平台改造，先交付可审阅的具体接口差异和最小后继方案，继续完成不受影响部分。

### 10.3 R1b 的文件、入口和交付

拟新增的文件明确标为**待实现**，不能把下列接口当作现在已经存在的 CLI：

| 位置 | 内容 / 接口约定 |
|---|---|
| `configs/research/adjusted_volume_relative5_v1/`（拟新增） | V/P 的显式 Safe DSL authoring、共同固定研究参数和字段范围；从配套材料 §4 生成，不增加候选/窗口。既有 model/cost/backtest/validation 配置按实际字节引用，不无理由复制全部配置。 |
| `scripts/frozen_field_study.py`（拟新增薄入口） | `prepare`：构造/绑定研究输入、独立请求和报价；`status`：只读已留存状态；`run`：显式执行单个冻结主任务；`compare`：只读原件、导入和比较。prepare/status 不启动科学阶段、模型或外部服务。 |
| `artifacts/field-study/<显式 study-id>/preparation/`（未来持久输出） | 固定设计、两个 candidate/family/manifest/request、比较 policy、引用原件的路径与 hash、是否复用 P 对照的理由、运行命令与预算。`<显式 study-id>` 在 prepare 时给定并固定，不能使用 latest/current/auto。 |
| 同一 study 根的 `execution/`、`comparison/`、`management/` | 各主任务隔离输出、真实 receipt/checkpoint、比较报告、进程退出和资源记录。prepare 输入库存与这些运行输出分开，避免输出改变输入身份。 |

CLI 的具体参数必须绑定 study/config hash、snapshot/view hash、源码与 lock 身份、独立输出根；`run` 另需实际执行的 task/request hash 及预算/资源约束，`compare` 绑定两个请求与实际 source descriptors。实施时在 `--help` 和 preparation 交接中给出**实际可执行命令**；本文不编造尚未存在的 flags 或填入虚假 runtime hash。

prepare 必须完成以下内容才交付运行请求：

1. 按配套设计冻结 V/P、共同模型参数、完整交易日历、真实 purge、覆盖分母和 `ceil(0.9 × 预期日期数)` 的共同日下限；两主请求均保留在比较分母。
2. 核对旧 return5 来源能否按实际依赖和 splits 复用；可复用则保持原 execution/receipt 身份，不能重写成新运行。不可复用时说明具体差异及其影响。
3. 对需要新增的任务，用 `quote_autonomous_workload()` 及最终 validation policy 给出**完整** compute units，包括稳健性、成本、复现及验证阶段；不能把“两候选”写成“两次训练”或实际秒数。相关实现/配置未确定前，不假报 36/72 units 为已完成报价。
4. 使用既有宿主卷映射、storage guard/lease 核算输入、完整增长、并发预留及失败收尾空间；成本参考已有记录，无法观测的项目记 unavailable。只读报价不启动科学执行来测耗时。
5. 保留新旧 PIT/profile/source reader 的接线说明，以及实际校验覆盖；若必要验证尚未获授权/执行，标记“离线输入已准备、验证未完成”，不得声称运行已就绪。

如果旧价格对照需要独立来源采用适配，先复用已有 adoption/预测证据路径完成这一小片；不为节省一个任务而改写旧 source capsule、取出裸 pickle 绕过准入，或删去 P 对照。

### 10.4 相称验证与恢复

本次文档补全没有运行测试。后续只有执行任务已明确授权测试或实现验证时，才使用下列现有受影响用例；不因这里列了目标就自动执行：

- P0：两个已定位文件的格式；lint/type 与集成范围遵循 §3，默认组合与 FR-03 后继组合分开报告。
- R1a：复用 `tests/contract/test_pit_contracts.py`、`tests/contract/test_research_contracts.py`、`tests/integration/test_pit_audit.py`、`tests/unit/test_qlib_research.py`、`tests/integration/test_signal_artifact.py` 和相关 prediction PIT 用例中实际受影响部分。必要反例限两来源完整性、晚到/缺键、错字段/快照、停牌与非有限、旧 schema 拒绝行为；不是默认运行这些文件全部测试。
- R1b：核对 prepare/status 不调用执行；固定双候选/分母/来源可重建；run 受明确任务与预算约束；恢复复用原 checkpoint/receipt、不增加机会；新旧 metadata 能通过对应 reader。优先使用保留小原件和合成夹具，不以真实科学批次代替接口检查。

验证通过后不为“再放心一点”重复完整检查。科学运行失败时先读有界 stage/exit 记录，从明确缺失部分恢复；不删失败根、不重置原 TTL/预算、不伪造 UNKNOWN 的退出。共享 authority 与 crash→recovery 链始终有序。

### 10.5 R1c 的最终交付

只有在 R1b 已产出具体可审阅的输入、最小新增任务与完整报价，且相应科学执行已获授权时才运行。本文与旧 A1/B2 已耗尽额度均不授予新运行额度；无需为 R1申请模型调用，因为设计中模型生成次数为零。

最终报告至少保留：两个候选及来源、复用/新增执行分母、每项科学 outcome 与 null 原因、完整预期/各自定义/共同日期数、共同日 Rank IC 和 `V − P`、实际成本及未知项、工程接线的有限接受范围。任何一项缺源/覆盖不满足，仍报告两个候选且差值为 unavailable。收益或显著正差不是工程完成条件；完成这一比较后停止，不自动追加任何候选、模型或时期。

每个已完成小片及时写入既有状态/交接体系，链接详细原件；不在多个状态页重复历史。源码完成、验证完成、科学执行完成和科学结论分开记录。

### 10.6 按模型拆分的执行入口

后续默认采用[执行手册 §5–6](quantos-evolution-model-worktree-plan-2026-10-14.md#5-用户实际操作顺序)的多会话方式：M 协调集成、A 负责 PIT 核心、B 负责独立收尾和执行/CLI；先 M0，再 A/B 并行，接口交接后继续并行，最后集中集成和 prepare。模型、思考强度、实际目录、CLI 启动方式与各阶段完整提示词均在手册中，不在此复制第二套可能漂移的分工。

该手册里的实施/验证授权只在用户实际发出对应提示词后生效；当前仍是规划完成状态。用户后续直接授权科学执行时，复用该次具体范围继续 R1c，不重复申请已获得的同范围许可。

## 11. 来源、定位和可复核性

仓库来源以下述固定 SHA 的永久链接定位，行号仅用于便利；实施核对以文件内容和实际符号为准。

- [Q1 SDK 提示投影实现](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/sdk_prompt.py)：本次读取全文件；四类节点与未知类型拒绝。
- [Q2 SDK producer](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/sdk_producer.py#L90-L280)：语义输出、候选映射、工具权限、请求和 reservation。
- [Q3 Ledger 检索与上下文](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/ledger.py#L629-L790)：词频/哈希排序、权限、build_context_pack 再复核。
- [Q5 前序实施与 C 义务说明](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/roadmap/quantos-next-stage-strategy-and-implementation.md#L70-L91)：没有已冻结完整独立 C 矩阵；既有 SDK/字段/并发边界。
- [Q6 Ledger authority 与对象契约](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/contracts/ledger.py#L19-L181)：节点、审核和 proposal 身份、来源绑定。
- [Q7 历史故障归因](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/roadmap/post-hm-next-failure-diagnosis.md)：已有可复用案例、无定义统计与缺证限制。
- [Q8 历史成本分析](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/roadmap/post-hm-next-cost-analysis.md)：249 completion、嵌套计时与 unavailable 项。
- [Q9 SDK 提示投影契约](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/contracts/sdk_prompt.py)：policy/hash、24,576 bytes、严格拒绝与展示非权威。
- [Q10 实施纪律](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/guides/implementation-discipline.md)：授权、验证范围、复用、资源和并行。
- [Q11 Qlib volume 转换](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/data/qlib_view.py#L197-L243)：原始股数除以 adjustment_factor，停牌缺失。
- [Q12 P13 v2 冻结](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/p13-v2-freeze.md)：单公告、引用位置提示、一条 signal、资格与成本范围。
- [Q13 原 GitHub Actions run](https://github.com/Dedicatus547/quant-research-os/actions/runs/38403772672/job/115317884164)：本次读取 job 步骤，格式失败、其余检查跳过；两文件定位同时依据用户提供的 Codex 审查。
- [Q14 Discovery execution blocker](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/discovery_execution.py#L1181-L1195)：SDK_CAPTURE 的明确拒绝。
- [Q15 Ledger 搜索与访问策略](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/contracts/ledger.py#L321-L386)：现有过滤和资源范围，不包含通用知识有效性解析。
- [Q16 冻结业务输入契约](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/contracts/hosted_inputs.py#L73-L105)与[loader](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/hosted_inputs.py#L185-L198)：搜索策略类型、初始 Ledger inventory/snapshot 核验；同一 loader 后续构造 orchestrator 并传入策略。
- [Q17 SDK launch 与 step](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/sdk_producer.py#L928-L1179)：已有响应回放、未知 intent 禁止重发、TTL/额度检查，以及 step 的 submit/resume 副作用。
- [Q18 Hosted 停止处理顺序](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/src/quantos/application/hosted_campaign.py#L538-L578)：先消费当前 trial，再依策略处理停止建议。
- [Q19 A1 实际提示容量](https://github.com/Dedicatus547/quant-research-os/blob/4b9961f3d3f7c58fa81424e719a10e877e96305c/docs/guides/sdk-campaign-offline.md#L22-L26)：V4 边界为 24,576 bytes，r10 两次提示为 12,281/23,942 bytes；这里只采用已有运行披露，不新增调用。
- [Q20 本次 P1/R0 原件核对与固定研究设计](quantos-evolution-p1-r0-evidence-2026-10-14.md)：真实案例、数据可用性、实读文件摘要、读取限制与下一步选择；这是本地后继材料，不伪造为上述历史 SHA 中已存在的文件。
- [E1 Dwork 等：Generalization in Adaptive Data Analysis and Holdout Reuse，v2](https://arxiv.org/abs/1506.02629v2)：自适应复用评估结果可能造成 holdout 过拟合；本文的具体隔离与释放流程是实施建议，不宣称复现该论文的差分隐私算法。
- [E2 ACE：Agentic Context Engineering，v3](https://arxiv.org/html/2510.04618v3)：上下文更新、经验整理与外部反馈的研究依据；不直接推导 QuantOS 收益或必须建设记忆系统。

v0.1 的外部仓库比较不作为本次接口或验收依据。未记录当时 commit 的 README 功能描述不能在 v0.2 中补造历史 SHA；后续真正采用某项功能时，补上该次读取的确切 commit、文件与依赖版本。论文引用使用明确版本。这样修正可复核性，不用重新开展一轮与近期工作无关的平台普查。

---

当前近期目标：**完成集成收尾、复权成交量字段接线和两个固定候选的研究准备；按具体授权完成回顾性比较。** 记忆试点等待新的真实决策损失证据，前向留证按自身条件独立推进。自我进化是经比较后可能采用的能力，不是预设必须完成的架构。
