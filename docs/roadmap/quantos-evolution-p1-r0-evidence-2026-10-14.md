# QuantOS P1 真实案例与 R0 数据可用性

日期：2026-10-14。配套计划：[演进路线图 v0.2](quantos-evolution-roadmap-v0.2-2026-10-14.md)。
源码核对基线：`4b9961f3d3f7c58fa81424e719a10e877e96305c`。

本页完成路线图要求的只读调查，记录实际可取得材料、判断依据和实施选择。它不是新的科学报告、模型评测或数据资格证明。历史授权、失败与工程接受范围均按原记录解释。

## 1. 决策摘要

| 问题 | 本次结论 | 对下一步的影响 |
|---|---|---|
| P1：是否已找到值得启动记忆比较的真实决策损失？ | 尚未找到。A1 两个可直接核对的真实 SDK 响应遵守了已明示的候选、历史与停止要求；其他主要损失来自执行边界、缺证或有限研究空间。 | P1 本次调查完成，P2a 暂缓。不要为了落实路线图而先开发记忆接入或制造模型调用。 |
| R0：公告是否足以支持多公告抽取比较？ | 当前已发布、可定位的研究许可公告只有一篇，且已进入 P13 benchmark；历史 P12 的三篇 SZSE 材料权限记录为 UNKNOWN。 | 公告路线暂不进入质量比较。单篇可复用为接线材料，不能充当独立评估集。 |
| R0：一个数值字段是否有现成来源？ | 有。原 immutable snapshot 内存在 `volume_shares` 和 `adjustment_factor`，现有 Qlib view 已生成 `$volume`；DSL/PIT/来源契约尚未贯通。 | 选择 `adjusted_volume = volume_shares / adjustment_factor`。先做离线接线与固定研究输入准备，再申请实际科学执行所需的具体预算。 |
| R1：到底回答什么？ | 固定 LGBModel 下，五日相对复权成交量这一单特征，相比五日价格收益率单特征，有何回顾性预测表现与覆盖差异？ | 两个固定候选、同一数据/模型/标签/日期政策，零 LLM 生成；不宣称控制价格后的增量信息或盈利。 |

这里“暂缓 P2a”是调查结论，不是因缺少本轮调用许可而得出的负结果，也不是“记忆无效”的科学结论。

## 2. P1：真实案例表

### 2.1 案例、可见输入与可行动性

`source_group` 用于保留共同来源及暴露关系；同组中的多次请求、多个候选或多份报告不能直接作为独立样本。下列材料均已被研究/开发过程查看，本次没有建立未暴露的最终评估集。

| ID / source_group | 实际事实与来源 | 当时可见输入 / 可用动作 | 可接受行为、确定性对照与损失判断 | P2a 处理 |
|---|---|---|---|---|
| P1-01 / `A1-r10` | 第一次请求 `d6109f…`，响应选择 `candidate-1c7ea…`，`request_stop=false`；说明尚无反馈支持候选优劣。[A1-1] | 两个冻结候选、`NO_TRIAL_YET`、明确的“两步工程任务”；只能选择候选、写 rationale 和停止建议。 | 任一尚未尝试的合法候选均可；不能虚构历史优势，第一步保持开放。当前输出符合这些可直接核对的要求。按冻结次序选首项和按步数停止即可得到候选/停止对照；没有证据证明额外经验能减少本次错误。 | 保留为开发示例，不列为已发现的决策损失。 |
| P1-02 / `A1-r10` | 第二次请求 `38b032…`，响应选择另一候选 `candidate-94a305…`，引用前次 `SOFT_REJECT`、负 OOS Sharpe/过高 turnover，并建议停止。[A1-2] | 与首步同一候选集合；实际 ContextPack 已有 `CAMPAIGN_TRIAL` 和 ValidationReport；预算剩一次。输入任务明确要求选另一候选、第二步停止。 | 不重复已尝试项；按真实历史解释，保留 proposal/工程边界。当前输出符合可核对要求；不能用后来的第二次结果倒推首步最优选择。候选与停止行为可由已有冻结选项、trial 身份和任务规则确定；自然语言解释尚未做独立盲评。 | 与 P1-01 同组，不能算两个独立泛化案例；无缺失记忆的直接证据。 |
| P1-03 / `Discovery-price-01-02` | 首轮四份 native 预测日期完整；Rank IC 无定义日分别为 6、12、12、72，均对应有限配对预测常数。两份 ratio 预测字节相同，但历史执行来源独立。[D02] | 这些诊断在失败后才形成。原生成入口只输出受限 AST，不能修改统计导出、门禁或已冻结模型。 | 保留 native 值、数学 definedness 与 null 原因；复用已完成的后继预测证据实现。由确定性统计规则处理，不能把后验根因写进原时点输入。 | 工程/统计语义案例；不把“记住 NaN 原因”计成避免原失败。 |
| P1-04 / `Discovery-price-01-02` | 旧 `std(close,10)` 在 signal 阶段 `SOURCE_INCOMPLETE`；没有 native 与首个触发键。已采样 PIT 范围发现 64 个 tradability 缺键，但缺少对应实际 score。[D02] | 原故障没有充分异常证据；Agent 无权补齐不可见分数或把未知交易状态当作可交易。 | 可接受结论是根因未确定。缺键且实际 score 有限才支持特定分支；需要在本来获准的后继执行中保留有限触发证据。既有确定性拒绝必须保留。 | 排除“猜中旧根因”型评分，不为制造标签重算原任务。 |
| P1-05 / `Discovery-price-01-02` | 第二轮两个新 signal 失败明确为 `SIGNAL_FINITE_WITHOUT_TRADABILITY`，旧 `std10` 根因仍 UNKNOWN。[D10-B] | 新失败的实际诊断可以用于解释新失败；不得逆向补成旧失败的当时证据。 | 正确区分新旧来源及失败原因。修复方向是数据覆盖/执行诊断，不是赋予模型绕过缺失交易状态的能力。 | 可作为报告解释的开放开发材料；当前 SDK 没有故障修复动作。 |
| P1-06 / `Discovery-price-01-02` | 249 个 stage completion：PIT 67、signal 82、Workflow 9、Validation 5、reproduction 5、其他 81；比较/采用独立计时与可避免成本 unavailable。[D03] | 计时嵌套，记录数不等于重复全流程执行。当前 SDK 不能改执行引擎或删验证变体。 | 不相加嵌套耗时、不把未知成本记零；沿用“暂缓 D08”。成本口径检查可以确定性完成。 | 无可归因的记忆节省量，不用这个表为 P2a 报收益。 |
| P1-07 / `Discovery-price-01-02` | 顺序生成第二轮三方法各五机会；方法内均零结构重复。有限空间 30 个结构，LLM 比基线并集多三项；后续共同日最佳值与 RANDOM 并列，增量 0。[D10-A][D10-B] | Discovery 生成入口与 SDK 冻结候选入口不同；前者看本方法此前 AST/静态状态，不看未来科学结果。 | 无放回枚举/采样已能避免方法内重复。两轮差异不能单独归因记忆；结构新增不等于预测质量改善。 | 保留原限定停止结论；不重新开展同类价格空间调用来“验证学习”。 |

以上确定性对照是根据已核对接口和规则得出的可实现对照，不声称已经新增、运行或评分了一个规则 Agent。可直接核对的 A1 事实也不代替盲评、独立样本或总体错误率估计。

### 2.2 适合保留的 rubric 与重新启动条件

若后续本来获准的任务出现新的真实决策错误，优先复用以下单步 rubric，而不是先增加记忆接口：

| 维度 | 评分依据 | 不允许的替代依据 |
|---|---|---|
| 候选合法性与不重复 | 冻结候选身份、真实已尝试 trial、任务约束；多个可接受选项均可通过 | 用未来 IC 追认某个唯一正确候选 |
| 反馈解释 | 当时实际提示中的 trial/outcome/report 能否支持陈述；未知项是否保留 | 把事后诊断当作当时已知信息；只核引用 hash 而不核语义 |
| 停止建议 | 明示任务/停止规则；建议在处理当前 trial 后才生效 | 把 `request_stop=true` 记成省掉当前执行；一律停止刷分 |
| 成本 | 同时记录确定性规则、无新增经验模型、人工整理和失败成本 | 只比较两组模型分数就认定需要模型 |

P2a 重新进入实施队列需要一条完整证据链：**实际请求与输出 → 可核对的错误/损失 → 该 Agent 确实能改变的动作 → 当时允许取得且可能改变决策的历史材料 → 简单规则不足的理由**。同时明确来源分组、开发/最终评估可见性和适用范围；少量材料只能支持开放可行性试点。新增一行满足这条链即可重新判断，不另设强制案例数量。

当前处理是保留上述案例与 rubric，停止 P2a 接线和 A/S 调用准备。不要将这些已经写有答案的案例同时用作经验库和未见任务评估集。R1 不以 P2a 重启为前置。

## 3. R0：本地数据与适用范围

### 3.1 公告材料

| 材料 | 实际可用性 | 时间、许可与暴露 | 结论 |
|---|---|---|---|
| 已发布 Evidence store `4fb04a…` | `artifacts/evidence-stores/` 下当前一份正式 store；manifest 含一个 item：600010.SH，2025-08-05 包钢股份回购进展公告。raw PDF、抽取文本及 item/evidence 文件在该 store 可定位。 | 记录为 `RESEARCH_ALLOWED`；许可标识 `sse-legal-statement/noncommercial/2026-09-08`。日期精度为 DATE、按次交易日使用；首次采集为 2026-09-10，来源修订历史无保证。 | 可用作已暴露的单公告接线材料；不能宣称是历史原始版本或多公告抽取基准。[P13-S] |
| P13 v2 benchmark | 单个 case、两段既给定的 citation、`attributes: []`；冻结结果只有一条 signal。 | 已进入模型/开发与人工审核过程；旧许可和外传授权只适用于原范围。 | 只能复用已有有限接受，不能把 citation 定位成功写成自由抽取字段能力。[P13-B] |
| P12 三篇 SZSE 材料 | 保留 report 记 `item_count=3`、抽取成功 3、store hash `c55e9b…`；该 store 不在当前上述正式 store 根中。本轮不继续扫描其他历史/外部存储寻找副本。 | `use_permissions=[UNKNOWN]`，并记 `LICENSE_PERMISSION_NOT_RESEARCH_ALLOWED`。 | 不并入研究/模型输入，也不因曾采集而认定有许可。[P12] |

“一篇”限定于本次核对的正式 store 和相关资格记录，不是宣称全机或其他存储绝无更多文件。本轮只读取保留许可状态，不重新解释交易所法律条款，不新增抓取、联网或外发。

公告路线的具体缺口是：有来源和允许用途的多个独立公告/修订组，未经答案暴露的评价部分，目标字段及独立标注，以及新增模型输入外传范围。当前缺口不能靠复制一篇、改写文本或用 synthetic fixture 补成真实样本。未来若这些材料因另一项已授权工作到位，再重新执行 R0 的公告分支。

### 3.2 成交量材料

| 对象 | 本次读到的事实 | 可复用与限制 |
|---|---|---|
| Canonical snapshot | `6297a968…`，`cn-a-share-hs300-eval-2015-2025-v1`，来源 Tushare；manifest 日期范围 2014-11-01～2025-12-31，bars 实际范围 2014-11-03～2025-12-31。 | 已取得不可变本地输入，无需新增 Tushare 调用；保持 `SINGLE_SOURCE_NON_VINTAGE`。[SNAP] |
| `canonical/bars.parquet` | 1,596,969 行，38,815,373 bytes；`volume_shares: int64`。本轮实读 SHA256 与 manifest 对应项一致。 | normalizer 将 `vol` 乘 100 转为整数股；`amount_cny` 虽存在，但不进入本次字段范围。[BARS] |
| `canonical/adjustment_factors.parquet` | 同为 1,596,969 行，740,684 bytes；实读 SHA256 与 manifest 一致。 | 旧 quality-report 记录因子为正；两表行数相同不代替逐键和本次研究 PIT 核验。[ADJ] |
| 时点记录 | 源码与各前三行样本均为当日 15:00 事件、15:30 可用，`CONSERVATIVE_DERIVED / cn-daily-conservative/v1`；历史 `observed_at` 也由该规则生成。 | 这是快照内的保守推导语义，不是供应商逐版本发布时间或真实历史抓取时间。不得据此声称 vendor-vintage PIT。正式研究仍走现有逐来源时点核验。 |
| Qlib view | `fc809bed…` 绑定同一 snapshot，Qlib 0.9.7；manifest 列出 668 个 `volume.day.bin`，其中包含指数文件，不能理解为 668 只同期成分股。 | `$volume = volume_shares / adjustment_factor`，停牌为缺失。复用现有派生 cache；本轮未逐文件重验 668 份 volume bin，也未重跑 dump_bin/health check。[VIEW] |
| 历史质量与曝光 | snapshot quality-report 记录 16 个 gate 通过；2015–2025 已用于既有研究。 | 原 PASS 保持原 tuple；它不授予新 volume 字段链资格。只能做明确的回顾性探索，不能通过换名称恢复未见时期。[QUALITY] |

本轮只做小文件读取、Parquet footer/各前三行抽样和两份 canonical 文件的一次顺序字节摘要，没有扫描全部行重算质量，也没有解析预测 pickle、执行信号或训练。数据可用性足以选择路线；运行级 PIT、信号有限性和交易状态覆盖仍由真实执行承担。

### 3.3 选择与字段语义

选择逻辑字段名 **`adjusted_volume`**，明确定义为当前 view 的 `volume_shares / adjustment_factor`，映射 `$volume`。不将它称为原始股数成交量；本次不新增原始 volume bin、不修改 snapshot/view、不引入 amount 或新的数据源。

首个研究使用同一股票自身五日均值归一化，避免直接把不同公司绝对成交量排名当作目标。该比值不能消除所有复权跳变、停牌或跨公司可比性问题，报告保留这些限制。分母零、缺失、非有限分数和交易状态不完整沿用既有拒绝/缺证语义；不偷偷加 epsilon、填零、前向填充或删除困难日期以通过运行。

新增字段的来源必须同时覆盖 `bars.volume_shares` 和 `adjustment_factors.adjustment_factor` 的窗口、主键和可用时间。只把新字段字符串加进映射，会漏掉以下现有约束：

| 接线层 | 当前实际限制 | 后继实现要求 |
|---|---|---|
| 单 instrument PIT | `application/pit.py` 的 `field_tables` 只有 close/adjusted_close | 新字段绑定两份真实来源，延续现有 hard rejection。 |
| 紧凑截面 PIT | `research/qlib/pit_evidence.py` 的 `LogicalField`、`SourceField`、`_FIELD_SOURCES` 仅价格；`contracts/research_execution.py` 的 `PITSourceSetEvidence` 和 collection validator 同样限定来源 | 增加明确后继契约/规则身份及读写分派；旧 v2 接受/拒绝行为和旧证据身份不变。不能只改 builder 而遗漏 verifier。 |
| 表达式 | `research/qlib/expression.py` 仅映射 adjusted_close | 在后继字段范围将 adjusted_volume 映射到 `$volume`；旧 profile 不因此自动获得新字段权限。 |
| 研究输入 | `ExperimentAuthoringSpec` 已接受 `SafeQlibExpressionSpec`；简写 authoring 和部分 proposal 映射仍为价格特定 | 首片直接使用显式 Safe DSL authoring；不改旧简写或伪装成 close 字段。 |
| 生成/准入 | `discovery_admission.py` 拒绝非 adjusted_close；旧 baseline grammar 和 composition profile 也是价格范围 | 首片使用事前固定的两个 singleton，不启用开放生成；独立后继字段研究范围，原 Discovery/SDK blocker 保持原义。 |
| 执行、回放和后继预测 | adapter 的 profile、PIT artifact reader、signal verification 和 `discovery_prediction.py` verifier 绑定旧来源/实现 | 贯通后继 profile、旧/新 PIT 解析及来源证明；先检查保留输入和新输入的 metadata 路径，再进入实际科学运行。 |

## 4. R1 固定研究设计

以下是本轮提出的**执行前研究参数**，不是已运行结果、已准入 proposal 或用户批准的费用额度。它们足以让 Codex 生成具体离线输入；生成后用实际 hash 冻结。运行前若必须修改，记录原因并更新整份后继设计，不能在看到结果后改主指标或候选。

| 项目 | 本次固定选择 |
|---|---|
| 研究问题 | 同一固定 LGBModel 的单特征模型中，五日相对复权成交量与五日价格收益率的预测质量、有效日期覆盖和执行成本如何比较？这是替代特征比较，不是价格控制后的增量检验。 |
| V 候选 | `adjusted_volume / rolling_mean(adjusted_volume, 5)`；Safe DSL 为 field → rolling_mean(5) → divide，三个节点。 |
| P 对照 | `return(adjusted_close, 5)`；Safe DSL 为 field → return(5)，两个节点。采用常见价格基线，不按本轮结果选择“历史最佳”。 |
| 候选和机会 | 只冻结上述两个主候选，各一个 singleton family；不搜索窗口、不生成 LLM proposal，不运行 A/S；实际执行上限是两个主任务，完整子阶段/稳健性变体另按现有 quote 计入。 |
| 数据 / universe | §3.2 的固定 snapshot/view；`000300.SH` 历史有效成分，不能用当前静态成分代替。 |
| 时间 | 沿用 `configs/research/policy_v1.yaml`：train 2015–2019，validation 2020–2022，test 2023–2025；固定完整交易日历及最后可计算标签日，保留实际样本审计。全部为已暴露回顾性时期，不读取 2026 sealed 段。 |
| 采样和标签 | 两候选相同 `input_lag_trading_days=0`，在日数据可用后形成 signal，下一交易日开盘执行；标签沿用现有 `Ref($close,-1)/$close-1` 的一日研究标签，不能当作实际交易收益。train/validation 各 purge 5 个真实交易日。 |
| 模型 | 复用现有 DatasetH、LGBModel、SignalRecord、SigAnaRecord；seed=1729、num_threads=1、num_boost_round=100、early_stopping_rounds=20。每个模型仅采用对应一个候选特征，不悄悄增加 Alpha158 或多特征模型。 |
| 主比较 | 两个来源均经独立核验及覆盖准入时，在共同数学有定义日期比较模型预测的每日横截面 Rank IC 均值，报告 `V − P`。同时报告每项自身定义日、完整预期日、null 原因和原科学 outcome。 |
| 覆盖政策 | 本次建议两项各至少 90% 预期日期有定义，共同日期不少于预期日期数的 90%（向上取整）；在准备阶段据固定日历落成整数并绑定。此处是新设计的相称覆盖要求，不继承旧 600 日门槛或声称已有功效保证。 |
| 统计与解释 | 首片报告描述性差值与覆盖，不新建显著性检验平台，不宣称独立确认。两项缺任一必要来源或覆盖不满足时差值为 unavailable，不补零、不删候选。 |
| 停止 | 完成两个既定主任务及比较后结束，无论差值正负均不自动扩窗口、扩模型或开新调用。执行错误先留证和定位；有可复用 checkpoint 时恢复未完成部分，不增加新的候选机会。 |
| 成功的含义 | 工程交付是字段来源、PIT、执行/回放与报告路径可核对；科学报告允许负增量、无定义或缺源。采用该字段作为长期研究方向需另结合结果与成本决定，本片没有盈利/自动晋级门槛。 |

旧价格结果只有在表达式、数据、模型、真实 splits、来源实现及报告 policy 均兼容时才复用。历史 `return5` failed-native 可用于核对复用可能性，但不直接贴成新 P 对照；不能跨不同 profile 仅凭表达式名字比较均值。准备阶段先给出是否可复用的结论及实际依赖差异，再确定需新增一个还是两个主任务。

执行接入优先复用 `QuantosResearchExecutionAdapter`、既有 checkpoint/receipt、`QlibWorkflowResearchService`，统计复用 `publish_prediction_evidence()` 和 `compare_prediction_evidence()`；后者本身支持显式请求集合，不要求凑成 LLM/RANDOM/TEMPLATE 三组。采用窄的后继 `frozen-field-study/v1`（拟议名称，尚未实现）接通 profile/来源分派，不伪造 generation response 或沿用价格限定 profile 名义。

运行入口需要薄封装的准备、状态、执行与比较出口；准备和状态默认不构造会执行科学任务的链路，不调用模型。实施工作包、输出路径和可直接交给 Codex 的指令见[路线图 §10](quantos-evolution-roadmap-v0.2-2026-10-14.md#10-给-codex-的近期任务边界)。本页不重复建立第二份任务状态表。

## 5. 原件定位与本次核对范围

下表 SHA256 是本轮实读的**文件字节摘要**；snapshot/view/store 的逻辑身份另见正文，两者不可混用。文件读取和摘要核对不等于完整历史资格重验。路径失效时，按 hash 在原持久存储定位；不得重造同名文件冒充原件。

| 来源 | 实读字节 SHA256 | 核对范围 |
|---|---|---|
| [A1-1 request][A1-1] | `d6109f0930541146333d128797bcb9c44ba02a7488bb3b636a13f56893daf886` | 冻结选项、任务、预算、ContextPack；同目录 raw-response 摘要 `bc789ec6f41967f3793fb2be9338eba6147ec12164e043ab40fcc59dc5304a67`。 |
| [A1-2 request][A1-2] | `38b032194bca6b67248a7fd3d3ad8cc57714e499252de02cc4f5ed3c6f2b7509` | 同上及 prior trial/ValidationReport；同目录 raw-response 摘要 `1f7c17c4d1b19aa7ee43ff0a46372553545b8df34577729d9d659711735a064f`。 |
| [D02 summary 原件](../../.worktrees/mainline/artifacts/post-hm-next/diagnosis/summary.json) | `f99796d3c97d031470b30104b69a4a3b884dcc2f27bbdfd8a2df4aa4bafd72d9` | 原件存在与摘要；案例事实复用已发布诊断，不再次解析 native pickle。 |
| [D03 cost 原件](../../.worktrees/mainline/artifacts/post-hm-next/cost/d03-cost-analysis.json) | `92734b7a3fb112623a3567de1abf3339b56f567366363856ac2f2fbed7b9d78b` | 原件存在与摘要；复用已发布成本口径，不重扫 249 个 completion。 |
| [D10-A 生成报告原件](../../artifacts/hosted-evidence/post-hm-discovery-02/analysis/generation-analysis/sha256-58359df633fafb477635df3a13637faad4c7eb71d2906af16a43de97256383c5/report.json) | `58359df633fafb477635df3a13637faad4c7eb71d2906af16a43de97256383c5` | counts 与限定报告，不重新调用生成器。 |
| [D10-B 科学报告原件](../../artifacts/hosted-evidence/post-hm-discovery-02/prediction-comparison-03/sha256-0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0/report.json) | `0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0` | 原件身份与既有报告，不重算共同日统计。 |
| [P13 store manifest][P13-S] | `9271437943facbabb9d6e939581425fd704134484ccc412cc6cf9456c272a026` | 一个 item、引用、许可记录、时点和局限；未重新抽取 PDF。 |
| [P12 report][P12] | `6d2496c727080bff4ed1fda515738eee988d611bd97e12723831b91371140ce5` | 三条记录及 UNKNOWN 权限，不采用其正文。 |
| [snapshot manifest][SNAP] | `9a9f7627531fef6c5fbad281d5aa58e0508acc6cf446423f9611e446388d0866` | 逻辑身份、日期、字段、指定文件摘要。 |
| [bars][BARS] | `f3d07d1ed3355058ee248394c2fef19adc060089e457f8b22953dad3d30ff674` | 全文件字节摘要；footer 与前三行字段抽样。 |
| [adjustment factors][ADJ] | `980a9e51f0eab23736433e716ca34486112c2c2c1a1dae630996b24b49c4b6af` | 同上；没有重算全表质量。 |
| [旧 quality-report][QUALITY] | `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8` | 旧 16 gate 结果；没有授予新字段资格。 |
| [view manifest][VIEW] | `2ca1bb63f827edf0cf58a7cdc49093a752514e86898b980a8ef794753d572988` | snapshot 绑定、版本、volume 文件清单数量及旧 health 记录。 |

本轮没有新增测试、模型调用、科学执行、网络获取或数据外传；没有改写任何上述原件。全文是可审阅的后继分析与计划，P1 案例结论、R0 选择及 R1 设计均不升级为机器验证的科学证据。

[A1-1]: ../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/sdk-evidence/876e2ecc8d55845935eb939b428062a37948919ba3825383bf8969b5f6c08079/d6109f0930541146333d128797bcb9c44ba02a7488bb3b636a13f56893daf886/request.json
[A1-2]: ../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/sdk-evidence/876e2ecc8d55845935eb939b428062a37948919ba3825383bf8969b5f6c08079/38b032194bca6b67248a7fd3d3ad8cc57714e499252de02cc4f5ed3c6f2b7509/request.json
[D02]: post-hm-next-failure-diagnosis.md
[D03]: post-hm-next-cost-analysis.md
[D10-A]: post-hm-next-generation-report.md
[D10-B]: post-hm-next-scientific-report.md
[P13-S]: ../../artifacts/evidence-stores/sha256-4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306/manifest.json
[P13-B]: ../../configs/research/p13_real_sse_share_repurchase_benchmark_v2.yaml
[P12]: ../../artifacts/feasibility/evidence-p12/report.json
[SNAP]: ../../artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9/manifest.json
[BARS]: ../../artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9/canonical/bars.parquet
[ADJ]: ../../artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9/canonical/adjustment_factors.parquet
[QUALITY]: ../../artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9/quality-report.json
[VIEW]: ../../artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b/manifest.json
