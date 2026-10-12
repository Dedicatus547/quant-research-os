# 后继 Discovery 决策设计

日期：2026-10-12。D04/N5 的实施设计，沿用[任务指南](post-hm-discovery-next-steps.md)。本页不授予调用额度、外传或科学执行权限；首轮历史及接受身份保持原义。

决策问题是：在相同受限表达空间、提案机会和实际执行上限下，顺序 LLM 生成能否比简单覆盖基线更有效地分配评价机会，并产生足以抵偿额外成本的固定模型预测质量增量。先回答生成问题 A，再决定是否执行质量问题 B。

## 生成政策（供 D06/D07 实施）

保留 `adjusted_close`、窗口 5/10/20、最多四节点和共同 grammar；仅输出一个 Safe DSL AST。各方法基础请求保持固定，新增明确版本的顺序政策和每次尝试封装，不修改旧 v1 的默认行为。每方法最多五机会是本轮拟议规模，并非新增额度。失败、中断、重复、修订均占原槽位，禁止补发凑足不同候选。

第 k 次历史只来自本方法第 1…k−1 个已持久化尝试，由原 response/reservation 和固定静态提取规则重建。允许展示 AST、结构 hash、静态解析/能力准入状态；禁止评价指标、信号失败、Validation、回测、未来响应和其他方法的结果。请求区分基础上下文与历史对象并逐项绑定，恢复同 reservation 复用原历史，新的生成必须占新机会。冻结再次从原件核验所有前缀，冻结后不得追加。

模板按 return、rolling_mean、rolling_std、rank 轮转分层覆盖，各层保留原共同空间顺序；第五项返回 return 层下一结构。随机采用固定 seed 1729、在共同结构空间无放回抽样；空间耗尽即拒绝超额机会，不暗中重置。有限空间下双方都无需科学反馈即可避免方法内重复；LLM 的新增结构数不能单独证明质量优势。结构等价与经济等价分别记录，不增加一般数学化简器。

分别报告管理侧实际模型入口调用及可观察重试（提供方内部调用未知）、授予/占用候选机会、不同候选科学执行及尝试/恢复。离线导入模型响应记零实际调用；模型启动失败与纯 capture 失败不能混算。静态准入不等于预测可分析。

## 比较政策与依赖

固定已有 LGBModel、label horizon、实际交易日 purge、snapshot/view 与来源核验。若复用首轮输出，只采用实际源码04的 purge 审计及绑定原件；源码03未裁切预测不进入新比较。日期仍属于已经暴露的回顾性探索时期，不声明独立确认。

D02 先判断 N2 分支。实现/来源错误优先最小修复；仅在确认完整预测正常、统计因可核验退化机制而无定义时引入后继探索性预测证据。新 profile 保留完整预期日期、null/原因和原始分母，不改旧 Result 导出门、旧 Validation 或 P14c。统计原生值是否有限与数学上是否有定义分别记录；有效配对中的预测/标签为常数时，即使原生 Pearson 输出有限值也不能视为有定义。

实施分支已依据 D02 四份实际 purged native 记录确定为后继预测证据导入、独立核验及新只读比较；信号失败保留缺证。每候选 726 日期齐，预测全有限，217,718 原始键中 217,486 有限配对与 232 NaN 标签；Rank IC 无定义日均对应配对预测常数。上述是诊断，不代替新入口独立核验。D03 已汇总 249 个小型阶段 completion，无法隔离可避免成本与窄路径边际收益，D08 拟暂缓，不影响 N2/N3 实施。

如果采用部分日期语义，预声明同时展示各自有效日覆盖和共同有效日期结果，不按各自均值混排，不填零、不隐藏无定义日；覆盖下限与共同日期下限作为显式冻结政策参数，在新评价前给定。原件缺失或 PIT/来源不足仍拒绝，不能归为合法统计无定义。对于首轮原件的新解释明确标为后继回顾性分析。

B 的比较对象为通过来源核验及冻结覆盖规则的所有不同结构，主值是这些对象共同有效日期上的每日横截面 Rank IC 均值。方法摘要并列显示各候选、覆盖、原始机会分母及该方法的最高共同日期主值；投入增量定义为 LLM 最高共同日期主值减去模板与随机两组中较高的主值。缺少任一必要组或共同日期不足时增量为 unavailable。各自有效日期均值仅作覆盖敏感性展示，不作为同排指标；小样本探索不作方法普遍优越性检验。

## 停止规则与预算

A 只分析新获授权的生成原件：完整尝试分母、静态准入率、重复率、不同结构及可观察成本。若 LLM 仍频繁重复，或只以更高成本实现模板/随机已有覆盖，则暂停扩大生成投入；此时质量增量仍未评价。缺授权导致未运行不构成研究暂停结论。

B 必须在生成冻结后、评价前绑定实际质量改善幅度、可接受额外费用/时耗、日期覆盖规则、科学执行上限与完整成本报价。报告所有候选及失败；共享结构只执行一次并保留方法归属。未知费用、子进程 CPU、峰值及人工均记 unavailable。没有这些决策参数时不作投入优越性裁定。

首轮五次 LLM 机会已耗尽，249 单位历史承诺不是第二轮余额。用户随后明确授权第二轮仅生成阶段最多五次 LLM 调用，以及本方法此前 AST、结构hash、静态状态与其来源hash的新增外传；[范围记录](../../artifacts/post-hm-next/generation-02/authorization.json)保留原回复。该授权不包含科学批次或测试。宿主卷完整增长与 lease 按实际任务核定。禁止因源码变化重跑首轮，也不为成本统计启动科学任务。质量改善幅度与可接受额外成本尚未获用户指定，本页不凭空赋值。

## 文件与接口归属

| 工作 | 唯一写入范围 |
|---|---|
| D05 | 后继预测证据独立 contracts/application 模块、独立导入/比较管理入口；旧 result/export/comparison 默认保持不变 |
| D06 | `contracts/discovery.py`、`contracts/discovery_hosted.py`、generation/admission/hosted、launcher 和现有生成管理入口；新增顺序模块按需 |
| D07 | D06 交接后独占 `discovery_baselines.py`、生成计数模块与报告接线 |
| 主 agent | 本页、实施状态及跨接口集成；公共报告/CLI 若需要，先按依赖接入 |

子代理新增接口先报告签名及语义；不并发修改共享 authority。D03 支持的性能优化才进入 D08，不能把 N4b 当作预测证据前置。

## D10 可接续材料与尚缺输入

已完成的入口与参数见[顺序生成](post-hm-next-sequential-generation.md)、[基线与计数](post-hm-next-baselines-counts.md)和[预测证据接口](post-hm-next-prediction-evidence.md)。首轮四份 failed-native 的 source descriptor、逐项哈希及全部十个 singleton 请求位于 [run-materials.json](../../artifacts/post-hm-next/prediction/run-materials.json)，仅作后继输入材料；未发布新证据。主 agent 的批次适配入口为 [post_hm_prediction_comparison.py](../../scripts/post_hm_prediction_comparison.py)，在独立核验后保留每个原 reservation 的方法归属、共享结构与缺失分数。新预测报告附顺序生成计数；没有科学 attempt 原件时科学次数仍是 NOT_OBSERVED/null。

第二轮建议先只开展 A：三方法各五机会，最多五次 LLM 管理调用；模板/随机离线生成。新增可见载荷限本方法此前的 AST、结构 fingerprint、静态准入状态及其来源 hash，与冻结基础上下文合并；不投影首轮指标、信号错误、Validation 或其它方法。请求配置沿用研究指南的 Sol/high，而 D10 执行管理代理按队列使用 Sol/medium。provider 实际身份、内部重试和未知费用仍分列。

获得新增额度和上述历史载荷外传授权后，按已有入口接续，不能在旧 generation root 补发：

1. 固定实际代码、lock、原 snapshot/view、基础 context 与 launcher configuration；在新持久输出根运行 `prepare_post_hm_discovery.py --generation-policy sequential-v2 --max-compute-units <显式设计cap>`。该 cap 只限定未来设计，并非科学授权。
2. 用准备产物 `design.json`、三份 request 和 `sequential-policy.json` 初始化新 generation root；离线生成两个基线。真实 LLM 单槽 runner 在 launcher 之前保存 source pointer、reservation 与 history，逐次接续。没有原 launcher exit 的槽位保留未知；有完整 capture 时只执行 `recover-hosted`，不重新调用模型。
3. 冻结 wrapper；调用 `generation-analysis` 输出完整机会、静态多样性、已观察调用/usage/成本。是否继续科学评价另按预声明改善幅度、额外成本和真实报价决定；未执行 B 时明确质量增量未评价。
4. B 若获授权，在冻结批次 `quote` 后检查新的科学单位上限、真实宿主卷增量、所有并发保留、失败证据空间及既有 lease。继续旧 full-chain 和原判据，不启动未证收益的窄执行器。

首轮后继只读预测分析与第二轮科学运行是两个选择：前者也须在执行完整数据/PIT核验前冻结覆盖参数、共同日期下限、当前 verifier identity 和增量预算。批次比较需显式 `--batch-hash --profile-hash --inputs-hash`，原件来源全部通过哈希选择；同时指定 `--generation-root --snapshot --view --execution-root --workspace`，以及与原件分离的 `--report-root --operation-root --expected-new-bytes`。首轮实际评价声明必须通过 `--evaluation-declaration` 保持源码04身份，不把当前实现改标为旧来源。未取得 descriptor 的请求在输入 map 中显式保留 null，不从分母删去。

当前实现的[verifier identity 原件](../../artifacts/post-hm-next/integration/prediction-verifier-identity.json)已持久保存，入口实际退出0；仅记录源码/数值环境依赖，不是预测核验资格。冻结profile前须核对该实现与环境仍相同。

本次A的实际 `max_compute_units=1` 在生成前已经绑定，是只生成任务的冻结约束，不是可随科学授权改写的占位值。当前v1评价声明仍要求后继上限不超过原design cap，故本次batch不能原样启动B。若以后明确授权B，应使用显式后继评价authority/版本、独立冻结新预算及实际来源并只读采用本次proposal原件；不得改本批cap、绕过旧门或重新调用LLM。这一科学接入未在本次生成授权内实施。

生成阶段的五次调用与历史载荷外传已授权，D10/A 自动接续；实际 provider 内部调用与费用未知时保留 unavailable。B 仍缺新科学额度、覆盖下限、共同日期下限、具有实际意义的质量改善幅度和可接受额外成本。容量与 lease 在实际输入、完整增长估计和所有并发任务确定后核对，不能在当前空任务状态替未来作业预报 PASS。B 保留待办，不把未授权科学执行写成研究暂停或整体完成。

## D10/B 科学授权后的实际接续

用户随后明确指示“继续科学阶段，我直接授权了”。本次离线科学范围据此接续，五次生成原件、A cap1和冻结wrapper不变；不新增研究LLM或确认期访问。[科学authority说明](post-hm-next-scientific-authority.md)采用独立v2声明、实际用户授权hash、新预算/来源与固定采用分区，旧v1 cap限制及科学/安全判据保持原义。

十二个结构中八个在source04已留原结果：四个SOFT_REJECT、三个完整native但旧QLIB export失败、一个SOURCE_INCOMPLETE无native。采用前核原request/outcome/receipt和科学依赖，七个表达完全同，另一个仅节点别名不同且官方Qlib翻译/output name/lag相同；最终预测导入/消费仍从数据/PIT/split/native机械重建，不把metadata采用当新科学PASS。四个真正新结构执行原full-chain，每项报价18，本次新工作72、全局一个失败任务一次恢复另18，新cap90；完整cohort参考报价213，旧249/360不作余额。

主代理在新科学结果出现前固定[后继比较政策](../../artifacts/post-hm-next/science-02/authorized-comparison-policy-02.json)：数学defined日期覆盖至少90%，全部可准入对象共同日期至少600日；方法最高共同日Rank IC及LLM减较高基线为主比较，各自日期均值只作敏感性。Rank IC增量0.002、五次LLM入口wall300秒和新科学管理wall14,400秒为探索性投入参考；这些参数由主代理在当前授权内选定，非用户逐数字指定，旧Validation门不变。完整费用仍未知，不能宣称货币成本优势或一般方法优势。

原20GiB容量草案保留；依据旧十任务实际逻辑总576,469,643字节、最大完整任务112,173,818字节及既有512MiB/完整attempt包络，本次四新加一次恢复只需五包络2.5GiB。再保留独立预测导入/核验/比较2GiB、管理/runtime/logs512MiB及未知/安全空间1GiB，完整新增长6GiB；sourcefreeze约46MiB另作业，科学2GiB RAM与512MiB tmpfs另核，不与磁盘混算。宿主32GiB底线和原全局lease保持。已有其他守卫作业独占期间只推进独立源码/输入准备，不抢锁或清理其证据；实际启动前刷新宿主容量与清理状态。

最终统计代码可独立冻结来源，但不得依据新metrics调coverage或分母；实际请求/cohort映射、数学规则、预算、日期和采用分区事前固定，首次质量消费前绑定统计verifier identity。新增科学工作与原已完成来源各自保留actual code/lock/QLib tuple，比较使用独立cross-origin接口，不扩大旧single-code profile含义。

## D10/B 完成后的投入决定

主代理采用[正式科学报告](post-hm-next-scientific-report.md)与[小原件核对](../../artifacts/post-hm-next/science-02/main-review.json)：完整12候选/15机会中9项可比、3项缺源，共同日期708天，超过事前600天下限。LLM、RANDOM和TEMPLATE分别有5、4、3项可比预测。LLM与RANDOM的最佳共同日固定LGBModel Rank IC均为0.02269698340587893，TEMPLATE为−0.007293875871142516；LLM相对最佳基线增量为0，未满足事前0.002。

五入口wall145.802448秒与新科学管理wall4084.5129645秒均满足各自事前参考上限，货币费用仍未知。结构新增3项和LLM可评价率改善已观察到，但本轮没有达到扩大投入所需的质量增量。因此暂停扩大当前受限空间的同类LLM生成；本批科学与统计任务完成，不追加机会或运行。该决定仅针对本次后继探索性比较，不推导LLM普遍无效、确认性研究、收益或策略晋级。原失败、SOFT_REJECT、无定义日期及缺源均保留；后继若研究新问题，应另设有依据的范围与声明，而非重复本轮。
