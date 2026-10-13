# QuantOS 下一阶段：审核结论与后继实施计划

版本：v1.2；审核日期：2026-10-12；状态：审核和执行分工设计已完成，后继实现及运行未开始。

事实参考基线与本次实际 HEAD 均为 `a030af62a147d8112343f8bc26ba6998aaf6476b`。没有代码基线差异，也未重置代码；审核开始时只有本文为未跟踪文件。初次授权是审核并整理计划；后续用户要求细化模型分工、并发和自动化操作，新增安排见第6节。尚未把实施方式咨询记作已启动源码实施。本次仅修订本文；不启动仓库内真实研究/资格模型、科学执行、测试、推送或部署。v1.1交付时已检查43个本地链接目标均存在，并核对所列源码符号位置；这是文档静态核对，不是实现验收。

2026-10-12 后续实施记录：用户已按第6节授权 A0、B0/B1、子 agent 与定向离线验证；
使用与实际结果见[下一阶段索引](README.md#下一阶段离线实施)。本文其他“尚未实施／未授权”表述
保留计划制定时点，真实 A1/B2 仍未运行，旧资格不变。

2026-10-13 后续运行记录：用户另行授权 A / B 预算及具体外发后，A1 一次 SDK 启动失败并关闭，
B2 三次模型交接已完成；科学后继采用原件并在原截止时间内继续。
本段更新该计划文档的时点边界，不修改历史接受证明；当前实际结果、预算及 A1 最小追加请求见
[A1/B2 运行状态](../status/a1-b2-authorized-preparation.md)。

## 1. 审核结论与采用范围

**结论：原提案 `APPROVE_WITH_REQUIRED_FIXES`；下列计划层面的必改项已在本文修正。一个产品、两条短期工作线可以采用，源码缺口仍待实施，所有运行资格保持原状态。**

A 解决真实 SDK 接入与恢复；B 检验新的研究任务。两者共享 admission、Qlib 执行、不可变结果和反馈能力。没有必要先合并所有 transport 状态机、重写 harness、建设沙箱或反馈式搜索平台。B 的设计和离线源码准备不依赖 A；最终让同一研究工作流使用两种入口，但不把 runtime 更换混入首轮研究空间比较。

审核读取了当前 [AGENTS.md](../../AGENTS.md)、[PLAN.md](../../PLAN.md)、[实施与恢复约定](../guides/implementation-discipline.md)、[状态总览](../status/README.md)、FR-03/Hosted/Discovery 状态、[发布记录](../releases/README.md)、原接受条件及下文所列源码。原文档的总体方向可保留，以下不是设计偏好，而是会使实施走错路径或夸大资格的具体问题。

| 必须修正项 | 源码或原条件依据 | 影响与最小修正 |
|---|---|---|
| A 不能把已有 SDK capture 当成可执行 campaign | [discovery_generation.py](../../src/quantos/application/discovery_generation.py) `_agent_binding:597`、`complete:1030` 拒绝顺序 SDK capture；[discovery_execution.py](../../src/quantos/application/discovery_execution.py) `run:1111` 明确拒绝 `SDK_CAPTURE` | 首片复用已有 campaign 业务服务，由 SDK 作为明确来源的 producer 接入；Discovery 接入留作后续独立切片，不能删除 blocker 或改填 `HOSTED_HANDOFF` 来过关。 |
| “已有 driver”不是 SDK 可直接替换的证明 | [autonomous.py](../../src/quantos/application/autonomous.py) `AutonomousAgentDriver:141`、`run:679`；[autonomous contracts](../../src/quantos/contracts/autonomous.py) `AutonomousAgentResponse:362` 绑定旧 `AgentRunManifest`，SDK runner 产出 V3 | 保留 SDK V3 原件与实际 usage、attempt、runtime 身份，明确到业务 proposal 的投影；不伪造旧 manifest。直接套同步 loop 在 exchange 尚未落盘时会重新调用 driver，必须保留调用前 reservation 与未知状态对账。 |
| B 的“价格、成交量等已批准字段”不符合当前执行链 | [expression.py](../../src/quantos/research/qlib/expression.py) `_FIELD_MAPPING:11` 只有 `adjusted_close`；[pit.py](../../src/quantos/application/pit.py) `field_tables:289` 只有 close/adjusted_close | Qlib view 含 volume 不等于 safe DSL/PIT 已贯通。B 首片仅用 adjusted_close；量价研究作为后续字段链工作，不先扩数据源。 |
| B 不能仅放宽 prompt、节点数或 operator allowlist | [discovery.py](../../src/quantos/contracts/discovery.py) `DiscoveryDesign:24` 固定 v1 grammar；[discovery_admission.py](../../src/quantos/application/discovery_admission.py) `capability_rejection:30` 限单窗口并校验旧基线结构集，`_subtask:61` 只绑定一个窗口槽 | 显式后继 design/profile 同步覆盖 grammar、基线、admission、多窗口 singleton 映射、输入加载与报告读取；旧 v1/v2 原件仍按旧规则核验。 |
| “减负”需要选中真实摩擦，不能改写旧准入 | [hosted_launcher.py](../../src/quantos/infrastructure/hosted_launcher.py) `hosted_prompt:358` 要求复制 expression/parameters/hash 并输出 canonical JSON；[autonomous contracts](../../src/quantos/contracts/autonomous.py) `AutonomousCandidateProposal:338` 重复这些字段 | 新入口允许语义化候选引用，由宿主确定性派生字段与 canonical bytes，绑定原始响应和映射版本；旧错误不追认成功。Skills 本身不是强制三角色执行器，不以删除 Skills 数量为减负指标。 |
| 两线重任务不能分别占用同一卷余量 | [hosted_storage.py](../../src/quantos/infrastructure/hosted_storage.py) `supervise_storage_job:327` 使用独占 `lease.lock`，冲突为 `STORAGE_JOB_ALREADY_RUNNING` | 源码工作可并行；独立重任务按现有单租约排队，或在现有 supervisor 支持的一个作业内预留合计子任务预算。不绕锁、不另建资源调度平台。 |

这些缺口不阻止本次文档交付或未来独立源码准备；只有依赖该能力的实施/运行切片需要先解决相应项。

### 已有事实与本次原件核对

- HM-MVP component-v2 已完成并冻结；科学拒绝与工程接受分开。服务/namespace 已清理，业务额度已耗尽，不能按“已可用 Hosted”理解成当前在线服务。见 [Hosted 状态](../status/hosted.md)。
- FR-03 为 `0.162.1 + gpt-6.1-sol / medium` 确切组合 GO，已合入本地 main、尚未部署。默认 SDK/runtime pin 仍为 `0.154.0`，实际版本入口见 [versioning.py](../../src/quantos/integrations/codex/versioning.py)；命名 [profile](../../configs/qualification/fr03-sdk-01621-gpt61-medium.json) 的 `main_integrated=false` 保留接受时点事实。P14d-C 仍 `BLOCKED_UNIMPLEMENTED`。
- 第二轮 15 个机会、12 个结构、9 项可比预测、3 项缺源；共同日最佳 Rank IC 增量为 0。原科学裁决是 6 `SOFT_REJECT`、6 `EXECUTION_FAILED`，Validation PASS 为 0；比较准入不追认科学成功。暂停扩大当前空间同类生成，不推出 LLM 普遍无效。见 [科学报告](post-hm-next-scientific-report.md)。
- [合并审核](../reviews/two-worktrees-merge-20261012.md)记录 245 项定向离线测试和静态检查。原 FR-03 全量回归/覆盖率仍绑定原源码胶囊，不是当前 HEAD 的新全量证明。

本次读取并计算了三份小型原件的 bytes SHA256：HM09 接受 `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec`（28,639 bytes）、FR-03 接受 `a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb`（23,167 bytes）、第二轮比较 `0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0`（76,859 bytes），均与状态/报告引用身份一致；抽读 decision、组合、分母和增量字段一致。原件链接分别在上述状态页和科学报告中。

另读取 [既有原件及源码差异记录](../../artifacts/merge-review-20261012/retained-evidence-review.json)（17,536 bytes，SHA256 `5dee9ee1600b4758f2d20a3dcf974caa7e0664c7bfb294b30cb1d0f0cf2e63be`）。本次没有重新逐项核验其 69+8 份引用、执行 full verifier 或解析大型预测文件；上述核对只证明所读原件身份与摘要，不授新组合资格。

## 2. A 线：用已有业务链完成真实 SDK 闭环

### 首选接入点与边界

首片采用“SDK producer → 已有 host-mediated 协议/业务服务”的路径，复用其 runtime-independent 协议，不新增完整 SDK campaign 状态机。核心链为：

`HostedCampaignApplicationService.pending → SDK request/capture → 验证来源并构造 response → submit → resume → prepare_trial → QuantosResearchExecutionAdapter → finish_trial → Ledger / 新 ContextPack → 下一 request / 终态`。

实际复用点：

| 职责 | 已有源码 | 首片需补的最小工作 |
|---|---|---|
| SDK 进程、事件和实际 usage | [sdk_adapter.py](../../src/quantos/integrations/codex/sdk_adapter.py) `CodexSdkAdapter:49`；[p13_agent_runner.py](../../src/quantos/application/p13_agent_runner.py) V3 产物与来源绑定 | 复用适配器和记录方式；P13 runner 是 benchmark 专用，不能原样当通用 campaign runner。绑定新请求的 schema、ContextPack、候选与配置。 |
| 有界请求、提交、取消、TTL、幂等 | [hosted_protocol.py](../../src/quantos/application/hosted_protocol.py)；[hosted_campaign.py](../../src/quantos/application/hosted_campaign.py) `pending/submit/cancel/resume/status:196–222` | SDK 作为明确来源的 producer；复用 protocol receipt，SDK 原件须在业务提交前持久发布并关联。transport 接受不授 SDK/HM 工程资格。 |
| admission 与既有 Qlib 科学链 | [autonomous.py](../../src/quantos/application/autonomous.py) `prepare_trial:1035`、`finish_trial:1160`；[autonomous_execution.py](../../src/quantos/application/autonomous_execution.py) `QuantosResearchExecutionAdapter:316` | 使用冻结候选、完整预算、原 execution identity，不另写回测或模型执行器。 |
| 恢复与反馈 | [hosted_campaign.py](../../src/quantos/application/hosted_campaign.py) `_consume:601`、`STARTED → UNCERTAIN:724`；[autonomous_execution.py](../../src/quantos/application/autonomous_execution.py) `inspect_completed_execution:564` | completed receipt 核验后复用；缺 receipt 不推测成功、不自动重发。只读检查用 inspect；`verified_completed_execution:537` 可修复索引，不当作纯读操作并发调用。 |

这是后继接入设计，当前源码尚无此完整入口。`HostedCampaignSpec`/request 的 `hm-mvp/v1` profile 和资格谓词也必须逐项核对：语义兼容的协议能力可以复用，新增 SDK 来源或改变 proposal ingress 的部分采用明确后继版本，不给旧 HM 原件换身份。不要通过伪装 `harness_identifier`、删掉 V3 attempt/usage 字段或只保存成功输出来凑兼容。

A 不以直接实现 `AutonomousAgentDriver` 为前置。若后续改选直接 driver，必须解决旧 manifest 类型、调用前持久 reservation、失败尝试计数、未知提交和 report limitations，不能只替换 `run()`。冻结 [finalization profiles](../../src/quantos/contracts/autonomous.py) 含 Scripted/Replay、FR03_NO_GO 等旧范围说明；SDK 后继报告需显式适用身份，不全局修改旧常量使历史回放漂移。

### A 的最小实施切片

| 切片 | 具体产出 | 完成边界 |
|---|---|---|
| A0：离线接入与请求收敛 | 在现有入口增加显式 SDK producer 选择；用已批准 profile 的确切安装/隔离配置构造请求；保留原 SDK capture、V3 manifest、schema 与业务 response 映射。新语义入口接收候选引用、rationale、stop 意图，宿主从当前冻结选项派生其余字段。 | 源码可审阅、离线材料已准备；不称 live 闭环，不调用模型、不耗用旧 campaign。映射不修改研究语义、补引用或猜候选。 |
| A1：有额度时的最小真实闭环 | 用一个有界新 campaign，真实 SDK 提案经过 admission/既有执行；随后至少一个真实请求消费上一步绑定的结果/失败反馈并正确终止。对已保存响应和 receipt 做不新增调用的恢复/回放。 | 证明实际 SDK、真实反馈归属、终态与已执行的恢复场景。开发 smoke 仅覆盖该组合与场景；调用数先计入新授权，超时/未知不自动再调用。科学拒绝或零合格候选可为工程成功。 |
| A2：按需求补组合资格及 Discovery 接口 | 依下表核对缺失证明；若需要同一 B 工作流切换 SDK，再为顺序 generation/source history 与 execution entry 建立明确后继绑定。 | 不把 A1 直接标为完整 P14d-C，也不因 A1 成功放开所有 `SDK_CAPTURE`。仅在相应条件满足时替换后继入口的 blocker。 |

A0 的持久化必须先于任何 live launch：保存 reservation、请求与配置；完成后立即保存有界且脱敏的真实 capture、manifest、响应或失败。当前 SDK adapter 的临时 auth home 是隔离设施，不是持久证据出口；`execute()` 返回前进程崩溃可能没有完整 transcript，此时保留 prelaunch、已观察退出和 UNKNOWN，不虚构完成或自动重发。复用 Hosted launcher 的持久 job/launch 记录与对账方式，不再建通用任务平台。

### 原接受条件与缺口映射

原条件入口为 [历史 PLAN §40.9](../history/2026-09-29/PLAN.md)、[P14d-A](../p14d-autonomous-loop-contract.md)、[P14d-B](../p14d-qualification-contract.md)、[FR-03 原20项退出条件](../history/2026-09-29/docs/P10-13-refactor-plan.md#16-fr-03-exit-criteria)及[当前第二阶段](stage-two.md)。历史 `FR-03 NO_GO` 按当时身份读取，由当前确切组合 GO 后继记录说明，原件不改写。

**这些原文将 P14d-C 定义为独立 live runtime qualification，没有给出一份已经冻结、完整独立的 C 场景矩阵。** 下表映射已有义务和源码组合缺口，不冒充找到了一套原 C 测试清单；正式 C 接受前在现有任务说明明确其确切范围和逐项证明，无需先新建资格框架。

| 条件 | 可复用的已有证明 | 需要新增或仍然缺失 |
|---|---|---|
| 固定 runtime/model/config、P10 9/9、P13 admission/PIT、隔离及失败留证 | FR-03 确切组合原20项已接受；保留 originating tuple | campaign 新 cwd、tools、schema、输入权限等变化的实际影响证明；无差异部分不重跑 P10/P13。 |
| 实际 Agent → proposal → deterministic execution → 反馈 → 终态 | P11/P14d-B 的确定性业务语义、HM 的有限组合经验 | 新 SDK producer 的真实往返、V3 来源与业务映射、反馈读路径；这是 A1 所补的范围。 |
| 冻结有限候选与完整 attempts/trials、预算、失败分类 | governor、P14b/P14c、既有 receipt 和预算记录 | SDK transport 失败不会天然形成 trial；失败/未知 launch 仍占已预留模型机会，不能仅按成功 AgentRun 计调用。明确无自动 retry/reissue/TTL reset。 |
| 幂等、冲突、取消、预算终止、断点与 replay | 旧 Hosted/P14d-B 场景按原依赖采用 | 新 producer 在调用后/提交前崩溃及未知状态；capture 已保存时不再调用；receipt 已存在时不再执行 Qlib。按影响补相应场景，不宣称通用 exactly-once。 |
| 确定性结果复现、完整性、集成检查和报告范围 | 既有双根证明、immutable artifact、合并定向检查 | 输入/schema/映射及传递依赖变化影响哪些证明需补验；回放保存响应，不要求再次调用模型得到相同文本。无当前 HEAD 全量 CI/覆盖率证明。 |

较窄交付应写为“SDK 有界闭环接入，已验证场景为……”，保留 C 未完成状态。不得降低原冻结科学/安全谓词，亦不将旧独立矩阵机械叠加成 A0 的开发前置门禁。

## 3. B 线：以现有字段开展真正不同的组合研究

### 第一项任务与实现范围

推荐首题：**短期价格变化与较长窗口的收益波动、趋势之间的组合，是否在相称搜索机会下带来增量？** 这是待检验的市场行为假设，不是有效性预期。只用已贯通的 `adjusted_close`，例如 `Return(close,5) / Std(Return(close,1),20)` 所代表的波动归一化思路；这里是语义示意，实际执行必须使用 safe DAG 与冻结 input lag。

该例使用已有 return、rolling_std、divide，不新增 operator，也不支持 arbitrary Python。[SafeQlibOperator](../../src/quantos/contracts/pit.py) 与 [Qlib translator](../../src/quantos/research/qlib/expression.py) 已支持这些组合；[PIT `_required_observations:413`](../../src/quantos/application/pit.py) 沿 DAG 传播窗口需求。源码支持不等于这个新表达式已通过数据完整性或科学验收，PIT 仍可硬拒绝，零分母/非有限值仍按既有执行判据处理。

首片采用预声明有界组合 grammar，而不是把原30个结构增加抽样次数：限定字段、已有算子子集、窗口集、节点数/深度、嵌套和二元组合规则；模型可组合多个时间尺度而非仅从旧 menu 选一项。建议从最多8节点、深度4、窗口 `{1,5,10,20,60}` 的小配置起草，实际取值在运行前冻结；这些数字是设计起点，不是授权额度或新增全仓上限。先约束为这一研究问题所需的算子，不实现通用 grammar 框架。

`_subtask` 的最小后继是给每个窗口节点建立确定性命名的参数槽，每槽在该候选内绑定一个值，再复用 `ResearchFactorTemplateSpec → enumerate_research_family → QuantosResearchExecutionAdapter`。这一 singleton 映射只是固定候选进入现有执行链，不提供跨所有生成候选的统计选择资格。

### B 的最小实施切片

| 切片 | 具体产出 | 完成边界 |
|---|---|---|
| B0：研究设计 | 在现有研究说明格式内冻结问题、可见信息、候选空间、相称基线、完整分母、指标和停止规则；列明已有 snapshot/view/曝光历史及尚缺预算。 | 可在无模型/科学额度时完成。没有 runtime 变量、未新取数据，不复制旧五次额度或0.002门槛。 |
| B1：离线后继 profile | 修改范围限定为 Discovery design/grammar、两基线、admission、多窗口映射及对应 prepare/capture/load/report 边界。准备至少一个旧 grammar 无法表达的新 DAG 和来源绑定示例。 | 保持旧版本 reader/verifier 语义；新配置贯通到执行请求，模型与基线使用同一能力空间。此处准备不是科学运行或资格证明。 |
| B2：获准后的有界比较 | 固定一个可用入口；三方法在相同信息和评价机会下完成候选生成，冻结全部响应后再评价。复用已核验、依赖吻合的来源，其余只做新候选必要工作。 | 如无增量仍可完成，短报告回答继续/修改/停止；不得自动增加额度。Hosted 重部署需有效范围和预算，旧服务及额度不能复活。 |

B1 不需要 A2；A2 之后可将同一 B profile 接入 SDK。原 SDK 顺序捕获禁止仍有效，不能为了 B 的并行绕过它。

### 比较设计与统计边界

| 运行前需明确 | 最小要求 |
|---|---|
| 研究增量 | 除组合特征外保留其组成部分/简单规则作为对照，避免把不同训练或评价政策造成的差异算作研究空间增量。 |
| 公平基线 | 随机方法从同一新 grammar 中按声明种子、复杂度和去重规则生成；规则方法可使用同样的嵌套/交互能力。记录各自采样分布与覆盖偏好，不强称分布相同，也不让基线停留旧30结构。 |
| 可见信息 | 输入身份、字段、区间、过去报告造成的曝光历史明确；首轮仅同方法静态生成历史，不向生成阶段回灌评价分数。候选与比较政策先于本轮评价冻结。 |
| 指标与有效性 | 共同日 Rank IC 可作预测主指标；候选覆盖、共同日数、方向、缺源和选择规则预声明。完整记录机会、不同结构、schema/PIT 拒绝、执行失败、可比预测及 Validation 裁决；缺失不填零。 |
| 研究报告 | 最佳值之外报告分布、有效产出率和组成项对照；小预算结果仅作探索性投入判断。Rank IC 不证明策略可用、alpha 或盈利。 |
| 资源与停止 | 生成机会、失败/未知调用预留、科学 executions/resumes/compute units、wall/空间预算分别记录。新额度未明确前不运行；无增量或预算耗尽即按预声明停止，不自动放宽门槛。 |

**新空间不继承旧 finite-family 统计结论。** 旧 P14c 基于 trial 前冻结的完整 family、完整 trials 和特定 Holm/bootstrap 条件，见 [P14c 契约](../p14c-selection-contract.md)与 [campaign_selection.py](../../src/quantos/application/campaign_selection.py) 的 `SELECTION_LIMITATIONS:79`。逐候选 singleton 的报告不能聚合成“整个生成搜索已校正”；完整尝试记录也不能消除已暴露评价区间或自适应搜索偏差。本轮定位仍为回顾性探索，不声明 sealed confirmation、Registry 晋级或确认性显著性。

未来若引入反馈搜索，开发反馈与正式评价需采用新的预声明设计；新 campaign 名称不使旧区间重新未暴露。沙箱、独立确认及通用平台均不是 B0/B1 的前置条件。

## 4. Harness 减负与并行实施约束

### 先删实际摩擦

A0 优先处理“复制派生字段 + 手写 canonical JSON”：宿主严格解析有界新 schema，按当前请求的冻结候选唯一解析，不靠猜测修复引用；保存 raw response hash、映射版本、canonical proposal hash 和来源关联。旧 ingress 继续保持原准入和机会计数；新入口的 parse failure、未知候选和冲突仍完整留证。原始响应与 canonical proposal 不再相同时，launcher extraction、来源 verifier 和 replay 必须一起绑定这条映射，不能仅在提交前改写 JSON 后仍声称是模型原始 bytes。模型不需要自行计算 hash，宿主仍必须核验 hash。

沿用 `pending/status/submit/resume` 与既有结果读取，不另建平行粗粒度 API。固定角色提示可在适用 Skills/配置中调整，但当前实现没有要求为了每个 campaign 都运行三角色委员会，不能把消除这个假设当收益。成功标准是减少实际手工搬运、格式失败和恢复介入，利用既有记录观察，不先搭遥测平台。

重复核验优化保持后置：[成本分析](post-hm-next-cost-analysis.md)尚不能分离可避免开销，D08/N4b 暂缓。先在本来就获准的工作中记录独立阶段成本，不为测量重跑整批、不删 Validation/变体、不建设通用证明缓存。wall、CPU、compute units 和账单分别报告，未知不填零。

### 修改所有权与资源

| 范围 | 所有者与并行约束 |
|---|---|
| SDK producer、请求/响应映射、hosted 接入与后继 profile | A 主改；B 首片不修改。共享 autonomous 核心原则上复用，确需修改由 A 单独提交，B 消费合入版本。 |
| Discovery grammar、基线、admission、多窗口任务与比较设计 | B 主改；A2 等 B 的后继接口稳定后再接，不与 B 同时改 generation/execution 的共享分支。 |
| contracts、共享 launcher/protocol、状态/资格记录 | 具体文件只由一线写；独立切片先集成，再由另一线适配。不能把“可并行”理解成同时写同一 authority。 |
| 数据、输出与证据 | 输入只读共享，独立 campaign、Ledger/Registry、输出根和 checkpoint；禁止可写 hardlink 充当独立 authority。共享 authority 写与 crash→recovery→对账串行。 |
| 重任务预算 | 复用 `StorageGuard` 对实际宿主卷/VHD、Linux evidence 和 scratch 硬配额的检查；单 supervisor 租约下按输入/安装、完整中间输出、export/replay、并发子任务、失败留证和收尾计算总增长。CPU/内存也按合计预算，不按各自空闲重复承诺。 |

本次观察到主仓、`.worktrees/fr03`、`.worktrees/mainline`、`.worktrees/merge-review` 及一些已不存在 `/tmp` 工作树的 Git 登记；FR-03/mainline 跟踪修改为空，但这不证明 ignored evidence 已迁移。未来从届时明确 HEAD 建立任务分支，不 reset 旧树；不 prune 或删除独有原件。尤其保留 `.worktrees/mainline/artifacts/post-hm-next/` 的检查、管理和交接原件，见[文档索引中的持久位置](README.md#本地证据与历史路径)。

本次未启动重任务，也未核定实时宿主容量或并发 reservation；这不是“资源已够用”的证明。后续每次重任务在既有授权内核对实际环境。租约忙时继续源码/文档准备，重任务排队；不绕过锁或扩大预算。独立完成步骤及时持久保存真实退出，恢复先查 receipt/checkpoint；父失败不改标，未观察到退出则保留未知。

## 5. 实施顺序、验证与交付

本次交付为本文的审核、必改项修订和最小切片设计。**尚未实施 A0/B1，未启动 A1/B2，也未更新任何资格。** 后续获得实施授权后，先处理对应切片的真实源码阻塞，再推进可独立部分；复用已授同范围权限，不逐动作再问。

建议顺序：A0 与 B0/B1 源码工作可并行；A1/B2 仅在分别具备运行授权、额度和资源时排队推进；A2 的 Discovery 接入等待 B 接口稳定。只在变化影响相应结论时更新短状态和使用入口，保留旧失败及 originating tuple。

测试遵守当前 AGENTS 17：只有用户明确要求测试或实现验证时才新增/运行。获授权时优先复用受影响的已有 SDK import/adapter、Hosted submit/recovery、Discovery admission/baseline/recovery、PIT/表达式与来源核验用例；不足之处只补关键行为，不另设门禁。真实 smoke、科学评价、全量 CI/覆盖率各自说明实际执行范围，不能互相替代。新 overall commit、本文修订或路径整理不单独触发历史全量重跑；配置、schema、权限和传递依赖改变也不能仅靠“文件没改”推定旧证明可用。

持续保留数据、凭据、安全和证据边界：Tushare 仅 snapshot acquisition，后续离线；contracts 不依赖 Qlib/Tushare/harness/LLM SDK；确定性执行阶段无 LLM；复用 Qlib，不自建回测/会计引擎；PIT 失败硬拒绝、执行失败 `FAILED / NOT_EVALUATED`；immutable snapshots、失败、receipt 和预算不被覆盖。Agent 输出始终是 proposal，盈利不作工程接受条件。

本轮及两个首片均不要求任意代码沙箱、动态 grammar、mutation/crossover、反馈式搜索、多模型 Council、第二数据源、通用资源/证明平台或预测窄路径重构。它们只有实际任务需要时才单独界定范围。


## 6. 按套餐额度优化的 agent 分工与自动推进

2026-10-12补充：用户明确优先节省 **ChatGPT/Codex 套餐额度**，要求按能力分工、并发并尽量自动化。本轮用了两个 `gpt-6-luna / medium` 子 agent 分别只读核对 A/B 文件边界；没有运行仓库 SDK 实验、科学任务或测试。下列是后续实施安排，不是已经完成的实现或验证。

### 模型选择

推荐 `gpt-6.1-sol` 承担核心开发，`gpt-6-luna` 承担窄任务，`gpt-6-astra` 只作疑难升级。官方也建议 Sol 用于多步骤复杂工作、Luna 用于清楚且可重复的子任务；模型/推理档可在派发时明确指定，避免默认继承主控的高档设置。见[官方子 agent 说明](https://learn.chatgpt.com/docs/agent-configuration/subagents)。这是结合本仓库风险的分工判断，不是已测得的模型优劣结果。

套餐包含额度不能按 API 美元价格换算，也不能承诺某模型能多完成固定倍数任务。优先在客户端选择 Standard 速度；官方当前列明 Fast 消耗包含额度为 Standard 的2.5倍，Ultrafast为8倍。当前派发工具没有单独的速度参数，本计划不声称已经切换服务档位。实际余额与重置时间以客户端用量页为准，不自动购买 credits、切 API 付费或升级订阅。见[官方套餐与用量说明](https://learn.chatgpt.com/docs/pricing)。

| 逻辑角色 | 推荐模型与推理档 | 负责范围；明确不交给它的工作 |
|---|---|---|
| 主控/集成人 | Sol medium；仅处理复杂冲突时 high | 固定任务和接口、派发、集成、控制验证范围、短进度和交接；不反复全仓重读，不常驻轮询日志。 |
| A核心 | Sol high | SDK来源、V3映射、protocol/profile、持久 reservation、恢复和最终业务接入；单独拥有相关共享 authority 文件。 |
| A辅助 | Luna medium | A核心接口稳定后，处理一个限定入口/参数适配或只读字段对应清单；不自行改变原件提取、来源核验、权限和预算语义。 |
| B核心 | Sol medium；准入/统计边界难题升 high | 新 design/profile、有限 grammar、admission、多窗口映射及公平比较设计；拥有 `contracts/discovery.py`、`discovery_admission.py` 和首轮 grammar/基线公共逻辑。 |
| B辅助 | Luna medium | B核心接口稳定后，改一个 prepare/load 入口使其显式读取新 profile，或按既定基线接口做窄实现；不独立发明 grammar、统计判据或任意改旧版本解释。 |
| 最终独立复审 | Sol high，一次有界复审 | 阅读最终 diff、相关契约和实际验证结果，集中检查来源、恢复、统计范围；由未编写相应核心变更的 agent 执行，不要求两条线各自跑完整复审流水线。 |
| 疑难升级 | Astra medium，可选 | 仅解决已定位且 Sol 仍无法消除的跨模块歧义，提交窄问题包。无此问题不启动；不默认使用 max/ultra。 |

以上是角色，不是同时启动7个进程。当前环境总并发上限为 **4，含主控**。默认为主控 + A核心 + B核心 + 一个Luna辅助；辅助槽在 A/B 间轮转。这样 A/B 核心并行，一条线核心与辅助也可并行；不能在该上限内同时给两线各加一个辅助。空闲角色及时结束，不继续分裂子 agent。

### 分三批推进

| 批次 | 同时推进的工作 | 串行依赖与交付 |
|---|---|---|
| 第一批：确定接线与研究接口 | A核心确定 producer/映射/恢复接口；B核心确定 profile/grammar/准入接口；Luna只读整理一个指定入口的硬编码和复用点 | 主控协调共享文件归属。接口决定留在现有任务说明/源码变更中，不新建架构审批包。 |
| 第二批：实现与辅助收尾 | A核心补来源和恢复，A辅助接已定入口；随后辅助槽转B，B核心补admission/多窗口映射，B辅助接prepare/load | 基线与admission共享 `baseline_expression_space` 等逻辑，必须先确定接口再拆；公共函数只有一个writer。辅助不能宣称单个prepare脚本完成就代表capture/load/report全链贯通。 |
| 第三批：集成、定向验证、复审 | 主控集成；空出的一个Sol做独立变更复审；Luna可并行整理实际运行摘要和使用说明 | 获测试授权后，仅运行受影响已有用例及确有缺口的关键检查。按失败定位修复再补验；不重复完整矩阵。A1/B2重任务受同一存储租约约束排队。 |

每次派发只带任务摘要、可写文件、已有接口、输入身份、不可触碰边界和结束条件，不复制整个对话和所有历史报告。子 agent 交付 diff/文件位置、实际检查、未解决问题的短摘要。每个窄任务先允许一轮交付和一轮定点修正；仍解决不了就带已有诊断交给核心 agent，不让廉价模型盲目多轮尝试。此规则控制开发返工，不是允许模型实验重试。

独立文件可并行修改；需要独立分支时由主控建worktree并在任务中固定绝对路径。子 agent共享文件系统，不自动获得隔离副本；只由主控执行共享Git索引操作和最终集成。同一文件不同时写，旧worktree及独有evidence继续保留。

### 自动推进与必须人工操作的地方

实施授权内，主控自动完成源码修改、可逆修复、必要离线准备、已授权的定向验证、结果留存和使用说明，不在每个切片结束时请求继续。复用已批准的登录状态、模型配置及权限；不要求用户在多个窗口间搬运JSON、hash或agent消息。正式运行的现有reservation、receipt、checkpoint和实际退出仍是恢复依据；agent总结不是运行证据。

只有以下事项确实无法在既有授权内解决时才打断用户：

- 登录失效、必须人工SSO/2FA或系统权限：给出具体页面/命令和完成后的动作，不要求发送密码或token。
- 新的研究/工程模型调用及科学运行缺少额度，或会超出已批准上限：先完成可审阅请求与预算，再一次列清模型、调用/尝试上限、科学执行和资源范围。当前历史额度已耗尽，自动化不产生新额度。
- 宿主容量不足且不能在保留独有证据的前提下解决，或旧未知提交需要外部事实对账：保留完成部分、停止受影响副作用，继续独立源码工作；不自动重发未知调用。
- 用户另行要求推送、部署或不可逆操作且缺少明确权限：完成具体可审阅产物后才问。不把这些动作自动塞进本次“收尾”。

套餐余额不是本仓库预算器可精确读取和保证的百分比。若客户端明确限额，保存现有进展、不继续派发；恢复后从持久记录续接。不要声称能自动保证“只花剩余额度的20%”。本地执行依赖当前会话及机器可用，未配置的后台服务不会在关机后自动继续；中断后的续接依赖保存的代码和原件。

### 用户的最少操作

只需保留一个主控对话，模型建议选 Sol、Medium；若有速度选项，选Standard。无需自行开两个聊天窗口、安装新的agent平台或改全局配置。后续要启动离线实施时，可直接发送下面这一条；其明确包括测试授权，是因为仓库AGENTS第17条要求用户明确要求测试或实现验证，之前的审核授权未包含它：

> 按本文第6节开始A0、B0/B1及独立可做的离线收尾。授权按模型分工派发子agent，总并发不超过4（含主控），允许必要的定向离线测试和实现验证。自动完成可逆修复、集成准备、证据保存和使用说明；复用既有同范围许可。不要调用仓库内真实研究/资格模型，不启动科学批次，不购买额度、不自动推送部署、不删除独有证据。离线工作完成后，给我A1/B2的具体最小运行请求与预算，只有必须人工处理的事项才停下来。

这条启动语句是供用户操作的模板，目前未被记作已授权或已执行。A1仍使用确切已接受的 `gpt-6.1-sol / medium` SDK组合；开发辅助使用Luna不改变实验模型或旧资格。正式运行准备就绪后再给出真实可执行的启动、状态和恢复命令，不在入口尚未实现时虚构一键命令。
