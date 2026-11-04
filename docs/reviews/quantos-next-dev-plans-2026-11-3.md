核查日期：2026年11月3日。QuantOS 基线为 `f480dcb0d6cc1cf4db1e5344a77165b7c67e9105`。

**建议保留 QuantOS 的确定性执行、PIT 和证据内核，把下一阶段主线集中到三件事：让模型提交真正可执行的策略表达，让已有结果形成有用的研究反馈，让冻结策略开始积累连续的未来观察。** 当前最需要补的是研究对象的表达与产品贯通，不宜继续把大量精力投入新的 harness、资格层级或多 Agent 角色。

本次核查覆盖当前主线、关键 contracts/application/research 实现、最新 GitHub Actions 日志、已提交研究记录，以及七个对照项目的官方代码和文档。属于静态工程与研究方法评审；没有运行项目测试、调用研究模型或重跑科学实验。QuantOS 许多运行原件位于未随 Git 分发的 artifacts 目录，文中的实际研究数字按已提交报告采用，没有重新计算其底层账户。

# 核心判断

QuantOS 的相对强项是能够回答“数据与结论从哪里来、失败有没有被隐藏、这个结果究竟证明了什么”。RD-Agent、AlphaAgent 和 QuantGPT 在可探索对象、研究操作效率或反馈体验上提供了更丰富的实现。AKQuant 对订单生命周期和账户续跑有参考价值。它们的研究结果、账户口径和工程接受范围不同，没有依据直接给项目排收益名次。

当前 QuantOS 已有个人研究 Skill/MCP、真实 Qlib 账户、历史检索和摘要工具，不能继续评价为“只有治理、没有业务入口”。同样，不能说其他项目普遍没有 PIT、交易成本、测试或记忆。公平的比较是识别每个项目真正实现了什么，以及它的结果能支持多强的结论。

**下一阶段交付目标建议定义为：用户给出一个在数据覆盖范围内的研究方向，模型将其转成可审核策略，系统按明确预算完成原生研究，用户能读懂结果并决定停止或继续。** 不以盈利、击败人工或跑完指定轮数作为工程完成条件。这个目标延续仓库10月22日的个人研究产品方向。[当前路线与产品目标](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/PLAN.md)

# QuantOS 当前真实状态

## 已经形成的能力

个人入口已有20个 MCP 工具，新增能力摘要、结果摘要和边界分页读取；支持从任意本机 Codex 会话使用研究工具。个人研究 v3 在11月1日完成六个新账户各721日及一个经典账户原结果复用，全部七行保留。底层使用 Qlib 0.9.7 Workflow、PortAnaRecord、目标权重策略、Exchange 和 Simulator。原始快照、PIT、执行政策、结果和来源身份被显式绑定。[个人研究指南](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/guides/personal-research-product.md)

这套产品也明确保留当前边界：供应商复权价格与数量单位是研究情景，不是实际现金红利或税后实收账本；统一200股和固定全包费用不是完整历史交易规则；连续前瞻账户尚未资格化。展示工具实现已经合入源码，但发布记录没有把新接口重新验证、MCP进程重启或部署声明为已完成。[11月3日收尾](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/releases/personal-research-closeout-2026-11-03.md)

## 最新研究结论已经更新

11月3日新增的连续资格确认实验已经结束，不应重新列为“下一步待运行”。原主策略只在连续开市时要求相邻两个信号日都满足原资格，新增一个账户，其他结果按原 tuple 复用。

| 指标 | 原主策略 | 连续资格确认后继 | 冻结判据 |
| - | -: | -: | - |
| 短命建仓率 S | 46.50% | 52.06% | 至少相对下降20%，未达到 |
| 日均双边换手 T | 54.73% | 51.11% | 至少相对下降10%，未达到 |
| 暴露归一换手 B | 1.3650 | 1.3928 | 至少相对下降10%，未达到 |
| 平均敞口 | 40.10% | 36.69% | 辅助解释 |
| 模型内净收益 | −24.14% | −8.55% | 不属于支持该假设的主判据 |
| 累计费用 | 347545.46元 | 362379.05元 | 辅助解释 |

因此，运行 `SUCCEEDED`、探索结论 `NOT_SUPPORTED`、正式科学验证 `NOT_EVALUATED` 可以同时成立。收益改善不能覆盖三项主条件全部失败；总费用也没有因为 NAV 归一换手下降而下降。这只否定该规则在本次问题和范围中获得支持，不否定一切资格稳定方法，也不否定整个 Agent 研究方向。[完整结果与指标定义](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/reviews/hs300-eligibility-result-20261103.md)

原七组结果中，主策略−24.14%、classic−7.79%、基准+16.54%；主策略平均暴露约40%，不是同暴露收益比较。原路径费用前结果也不能当作零费用重执行；2023年和2025年费用前已经亏损，不能把全部亏损归因交易费。已有归因显示，主策略卖出金额中69.06%与资格退出对应，排名替换为11.53%。这支持关注资格与持仓路径，却没有确证哪个筛选条件是经济原因。[换手归因](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/reviews/hs300-turnover-attribution-20261103.md)

## 当前 CI 的直接故障

最新运行 `41605070797` 在 AppArmor/bwrap 环境检查失败，后续 uv sync、Ruff、Pyright、pytest 全部跳过。日志实际镜像版本是 `20261025.353.1`，工作流却要求 `20261012.334.1`，并同时固定宿主内核和工具版本。它是明确的环境身份不匹配，不能描述成业务测试失败，也不能继续引用旧 CI 通过证明当前主线全绿。

修复应让普通代码反馈与特定隔离环境资格独立呈现，同时保留需要隔离的测试前置条件。不要只把旧日期换成新日期，也不要关闭 AppArmor 或全局禁用安全检查。容器镜像本身不能固定宿主内核。[工作流](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/.github/workflows/ci.yml) · [实际运行](https://github.com/Dedicatus547/quant-research-os/actions/runs/41605070797)

# 对照项目与版本

| 项目 | 本次检查版本 | 定位 |
| - | - | - |
| QuantOS | f480dcb，2026年11月3日 | 可审计 A股研究与个人助手 |
| RD-Agent | 484776c，2026年9月23日 | 因子与模型研究自动化 |
| AlphaAgent 当前 main | b42cb397，2026年7月3日 | Tushare 离线面板与因子挖掘 |
| AlphaAgent 论文分支 | legacy-main 的 1da96e94 | KDD 2025 论文实现 |
| Miasyster/QuantGPT | 90e7f3db，2026年11月1日 | MCP 驱动表达式因子研究 |
| AKQuant | 269fab31，2026年10月30日 | Rust/Python 事件驱动回测与执行 |
| Qlib | 54355232，2026年10月8日 | 数据、预测、组合与回测底座 |
| TradingAgents | c4544913，2026年10月27日 | 市场分析、决策与反馈记忆 |
| Kronos | master 的 67b630e6，2026年4月13日 | K线预测基础模型 |

这些版本仅用于定位本次证据。QuantOS 当前依赖的 Qlib 0.9.7 不等于上表检查的 Qlib 主线。项目论文的效果没有在共同数据、预算、成本和交易时钟下复现，因此不作为项目优劣排名。

## RD-Agent

RD-Agent 的强项是完整的研究循环：提出假设、生成实验、实现、运行、反馈，再将历史经验交给下一轮；还能在因子和模型方向交替。CoSTEER 实现经验检索包含相似成功任务、失败轨迹和修复反馈，已经接入后续实现过程。默认量化配置有数据划分和扣费回测，不能概括成“只生成因子”。[研究循环](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/app/qlib_rd_loop/quant.py) · [提案读取历史](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/scenarios/qlib/proposal/quant_proposal.py) · [知识复用](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/components/coder/CoSTEER/knowledge_management.py)

对 QuantOS 的启示是区分两类记忆：研究事实与假设结论，以及代码实现与修复经验。前者防止重复研究，后者降低实现成本。仓库已经有 Ledger、ContextPack、adaptive feedback，不需要再引入第二套知识权威。

局限是整体框架涵盖很多任务和调度组件，迁入成本高；反复用于反馈的回测区间，在统计意义上属于开发信息。论文或默认配置中名为 test 的区间，不自动构成未被研究过程触碰的最终确认样本。因子 runner 的数值去重也是局部方法，不代表全方位经济独立性。[去重实现](https://github.com/microsoft/RD-Agent/blob/484776c211e4fbbeef03e0ec00d6bbee7362a4f4/rdagent/scenarios/qlib/developer/factor_runner.py)

建议借鉴反馈内容和经验检索方式，先让一个真实任务受益；不整体替换现有 Codex/MCP 外层，也不默认加入 bandit、知识图谱或多研究循环调度。

## AlphaAgent

同一官方仓库存在两个需要分开的版本。论文实现保存在 legacy-main，含 AST 正则、复杂度与原创性约束；当前 main 已转成 Tushare、DSL、FactorZoo 和 AgentScope 框架。当前主线的能力包括基本面和行业面板、train/val 评估、相关去重、月度稳定性、分组报告，以及财报披露后下一交易日生效的 PIT 代码和测试。因此，PIT 并非 QuantOS 独有。[当前实现介绍](https://github.com/RndmVariableQ/AlphaAgent/blob/b42cb397025510da44355db9dcf278304321f589/README.md) · [PIT 测试](https://github.com/RndmVariableQ/AlphaAgent/blob/b42cb397025510da44355db9dcf278304321f589/tests/test_data/test_fundamental_pit.py)

它的三个核心研究工具比庞大的编排接口更接近薄 harness。值得学习的是紧凑的表达、评价与相似因子反馈。复杂度和相似性适合用来减少重复计算、提示改进，不应被升格为另一套“一票否决所有创新”的规则。

当前主线也有具体边界：prompt 要求 train/val 分别满足更丰富的条件，submit 实际强制的是合并区间的若干指标；因子截面自相关被用作低换手代理，不能替代实际账户成交和净收益。基本面采集对修订版本与多报表披露时间仍需额外核对，不能只凭一个 next-day 测试认定完整 vendor-vintage PIT。[实际入库检查](https://github.com/RndmVariableQ/AlphaAgent/blob/b42cb397025510da44355db9dcf278304321f589/alphaagent/factor/mining/submit.py) · [提示规则](https://github.com/RndmVariableQ/AlphaAgent/blob/b42cb397025510da44355db9dcf278304321f589/alphaagent/factor/mining/prompts.py)

许可证也要按分支判断：legacy 有 MIT，当前 main 未见明确 LICENSE 文件，不能把论文分支许可自动覆盖所有新代码。先借鉴设计，直接复用前核清许可。

## Miasyster QuantGPT

QuantGPT 的优势是围绕研究者的操作体验：表达式工具、回测、失败诊断、滚动评价、候选迭代、知识卡片和结果展示接得比较连贯。突变、重组和轨迹选择有代码；rules/findings/failures 的轻量知识组织值得借鉴。开源知识库说明同时明确：只公开样例，不是完整长期知识库。[项目说明](https://github.com/Miasyster/QuantGPT/blob/90e7f3db59b62c06f33e76735591eacfee99a177/README.md) · [知识库范围](https://github.com/Miasyster/QuantGPT/blob/90e7f3db59b62c06f33e76735591eacfee99a177/docs/knowledge/INDEX.md)

当前 QuantOS 已有 MCP，所以工具数量或有无聊天入口不再是主要差距。真正差距是模型能否根据方向产生可执行研究对象，能否读懂失败并避免无意义重复。

不建议迁入其整套评价口径。固定版本 `rolling_validator.py` 的 Sharpe 使用测试股票池 daily_ret 的按日均值，而非该因子组合持仓收益，却进入综合评分。回测代码有费用，但收盘收益计算与“T+1开盘建仓”注释存在需要复核的时点差异。MCP 数据入口在起始日取一次成分池，也不等于逐日历史成员。它有部分 pubDate 对齐措施，不能说完全不做 PIT；这些措施也不能替代完整时间和账户核验。[滚动评价](https://github.com/Miasyster/QuantGPT/blob/90e7f3db59b62c06f33e76735591eacfee99a177/quantgpt/rolling_validator.py) · [回测](https://github.com/Miasyster/QuantGPT/blob/90e7f3db59b62c06f33e76735591eacfee99a177/quantgpt/backtest.py) · [市场数据](https://github.com/Miasyster/QuantGPT/blob/90e7f3db59b62c06f33e76735591eacfee99a177/quantgpt/market_data.py)

Cloud 独立验证在开源部分可确认的是客户端调用，不能据此确认远端全部规则和未曝光样本。建议借研究交互、诊断和知识组织，保留 QuantOS 的来源、时间、账户与结果语义。

## AKQuant

AKQuant 是下游引擎候选，其价值在事件与订单生命周期、交易限制、状态保存和恢复。已有 T+1、交易单位、成交量限制和停牌相关实现与测试；checkpoint 可以保存引擎、策略及历史状态，分段结果可以合并。不能只以“Rust更快”概括它，也没有 QuantOS 工作负载上的实测加速倍数。[项目入口](https://github.com/akfamily/akquant/blob/269fab31a389a607da5c5d4872ef6b54390de6d4/README.md) · [Checkpoint](https://github.com/akfamily/akquant/blob/269fab31a389a607da5c5d4872ef6b54390de6d4/python/akquant/checkpoint.py)

需要保留三个限制：默认 run_backtest 为零费用且不开 T+1；默认撮合没有覆盖所有板块、ST和历史时期的动态涨跌停规则表；MiniQMT/PTrade 在当前官方矩阵里仍是占位适配和联调骨架。接入不会自动解决数据 PIT、公司行动、复权单位或生产券商能力。[A股建模说明](https://github.com/akfamily/akquant/blob/269fab31a389a607da5c5d4872ef6b54390de6d4/docs/zh/textbook/06_stock_a.md) · [Broker 能力矩阵](https://github.com/akfamily/akquant/blob/269fab31a389a607da5c5d4872ef6b54390de6d4/docs/zh/advanced/broker_capability_matrix.md)

适当路径是先判断 Qlib 是否满足下一项实际需要。如果完整账户连续性确实成为 blocker，再做小型适配验证。导出相同数据、信号或目标权重、时间和成本情景，比较实际成交、现金、持仓与净值；不要为改善收益同时改引擎和政策。采用 checkpoint 时保留配置、引擎版本与源输入身份，不能把 pickle 本身当研究账本。

## Qlib TradingAgents 与 Kronos

Qlib 是 QuantOS 已在使用的研究底座，已有 PIT 数据设计、模型与组合接口、费用和成交约束。QuantOS 的增量应体现在研究意图、数据和结果身份、可审核决策的连接上。升级依赖时应绑定具体版本，现有正式发布与主线的制品加载和配置安全限制不能混用。[Qlib PIT](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/docs/advanced/PIT.rst) · [Exchange](https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/backtest/exchange.py)

TradingAgents 当前版本已有决策保存、结果结算、反思与时间过滤记忆，SEC 数据按披露时点选版本；应修正“只有多角色辩论”的旧印象。其决策评价主要是股票×日期格子的方向与价格超额，不是完整扣费组合账户。值得借鉴已知结果何时进入记忆，以及研究结果如何转成简洁用户反馈，无须复制所有角色。[历史记忆](https://github.com/TauricResearch/TradingAgents/blob/c4544913a14ed3df5f1ed7b9e8483270ce20682a/tradingagents/memory/log.py) · [结果结算](https://github.com/TauricResearch/TradingAgents/blob/c4544913a14ed3df5f1ed7b9e8483270ce20682a/tradingagents/memory/settlement.py) · [评价边界](https://github.com/TauricResearch/TradingAgents/blob/c4544913a14ed3df5f1ed7b9e8483270ce20682a/tradingagents/backtest.py)

Kronos 是可选预测器，提供 OHLCVA 数值预测、批量推理与 Qlib 示例。它能在未来扩展研究范式，但不替代研究管理、PIT或账户执行。只在真实问题需要新的量价表征时，冻结模型与输入，经已有预测/信号适配进入 QuantOS；暂不新建基础模型训练平台。[Kronos](https://github.com/shiyu-coder/Kronos/blob/67b630e67f6a18c9e9be918d9b4337c960db1e9a/README.md) · [Qlib 示例](https://github.com/shiyu-coder/Kronos/blob/67b630e67f6a18c9e9be918d9b4337c960db1e9a/finetune/qlib_test.py)

# 优势与最关键的短板

## 应保留的优势

**结果诚实且可追溯。** 工程完成、策略拒绝、来源不足、科学未评估被明确区分；失败和未运行候选不会从分母消失。今日 confirm2 没有因收益更好而改变冻结结论，这比展示一条漂亮曲线更有长期研究价值。

**真实执行与模型提案分离。** Agent 不能自行把提案改成验证证据。冻结快照、available_at、signal/decision/execution 时点、成本、原生账户与输出绑定有明确实现。旧实验可按真实依赖复用，整体提交变动不自动导致全流程重跑。[仓库规则](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/AGENTS.md)

**自主程度能够受预算约束。** 当前外层 Codex 会话可以调用工具，研究和公告接口不必再套一层内部模型。预算、终态与恢复机制已有，不需要再造通用 Agent 平台。

这些是相对优势，仍不意味着已取得真实 vendor-vintage PIT、最终样本外 alpha 或生产交易资格。其他项目也有局部同类机制；QuantOS 的价值在组合、实施深度与明确边界。

## 首要短板是策略表达与执行耦合

当前个人入口的 brief/proposal 会进入任务身份，保存来源与说明，但不决定新的信号算法。`_prepare_hs300()` 固定产生 main、classic和五个随机种子；profile 把20日趋势、5日动量、1.2成交额门槛、Top10、权重与费用等锁定；信号编译按候选 role 分派固定公式。[个人契约](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/contracts/personal_research.py) · [准备服务](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/application/personal_research.py) · [信号与原生执行](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/research/personal_qlib.py)

因此，“模型能够设计策略”目前只在固定支持范围内成立。新想法容易要求新增 profile、prepared 类型、信号代码与手工后继脚本。研发成本被消耗在让想法进入执行链，而不是比较想法本身。

已有 Safe DSL 可以复用，但 legacy 只映射 adjusted_close，显式 field-study 后继再开放 adjusted_volume；rank 是时序 Rank，不是截面排名。比较、布尔过滤、自由常量、成交额、行业中性化等不能假装已经支持。个人执行目前消费内部 DataFrame，核心 SignalArtifact 则带独立来源与 PIT lineage；适配不能丢这些语义。[DSL translator](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/research/qlib/expression.py) · [研究架构](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/architecture/research-and-backtest.md)

建议在新后继中分开“研究表达”和“市场执行政策”的身份；候选 main/classic/random 只表达报告角色，算法由明确的信号描述决定。旧 v3 的七候选、signal_reuse、classic origin 和历史证据保持原身份。不能拿新的信号继续冒用旧复用绑定。

## 第二个短板是研究反馈仍需整理

已有 adaptive_feedback 与历史工具，不应从零造记忆系统。但个人 history 当前主要是显式目录和 record_id/label 检索，成果尚需人工从报告中整理为可用于下一次研究的结论。[历史入口](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/application/personal_history.py) · [既有反馈](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/application/adaptive_feedback.py)

补齐方式是派生一个简洁反馈视图：假设及预期现象、实际观察、与预期的差异、证据引用、适用范围、尚未回答的问题、继续或停止的理由。事实、模型解释和工程修复经验分开。记忆先服务真实任务；用户没有研究“记忆是否有因果增益”时，不强制建立无记忆/有记忆竞赛。

## 第三个短板是执行模型与持续观察

当前指南已经承认 ST 双向限制、原生预检可能因任一方向限价双向跳过、前一信号日预检、统一200股、固定费用、全日容量约束等情景限制。它们必须在用户能理解的结果中出现。应先看哪些限制真实影响本次持仓和成本，再决定引擎或政策改造，不必一次覆盖所有交易所细节。

连续前瞻账户还有实际阻塞：初始 NAV 分母、完整 Account 状态、reset_report 与新快照衔接。已有 simulation_prepare 如实返回缺口。[模拟准备实现](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/src/quantos/application/personal_research.py)

可以先从冻结日起记录未来信号和可见信息；账户能力未完成前，明确称为前瞻信号观察。新增数据或修改策略各自留版本，不能回填成连续业绩。未来账户由成熟引擎维护，QuantOS 不自建撮合或组合会计。

## 第四个短板是可持续交付

AppArmor 镜像身份漂移令全部代码反馈中断，是当前最具体的维护问题。多份身份与版本材料还有必要性，但展示层、开发反馈和历史资格不应相互拖累。摘要工具方向正确，不过源码已说明它仍调用原完整核验路径，不能据输出变短就声称读取加速；只在实测存在重复成本时再优化。

公开复现也有边界：多数市场原件不随 Git 分发，新克隆只能运行 synthetic 示例；pyproject 当前标记 Proprietary，仓库没有明确开放许可证。若目标包括开源协作，应单独明确许可、提供可再分发的小型样例和可读报告。个人使用优先时，这不是阻挡研究工作的前置项目。[安装与证据范围](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/README.md) · [项目元数据](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/pyproject.toml)

# 建议架构边界

继续使用现有外层 Codex 和 MCP。外层负责理解用户方向、形成假设、解释反馈、选择继续或停止；QuantOS负责将明确研究对象转为可执行输入，控制数据时间与运行身份；Qlib或明确接受的其他引擎负责持仓、成交和会计。

| 可由模型灵活决定 | 应由系统稳定执行 |
| - | - |
| 研究问题、经济解释、候选想法 | 数据来源、可获得时间、输入身份 |
| 在支持范围内的表达式与组合方案 | 因子和模型计算、下单时点与原生执行 |
| 查哪些历史证据、怎样解释反例 | 成本口径、失败与缺失状态、完整结果分母 |
| 下一步是否值得做、合法 STOP | 权限、预算、不可变结果与科学状态 |
| 提出工作流或代码改进 | 独立修改版本、受影响检查与接受记录 |

“薄 harness”优先体现在：减少硬编码研究问题、重复角色、无必要的阶段和文件搬运；用户只需理解研究方案、成本和证据。它不要求削弱 PIT 或允许模型直接改结果。

第一版策略后继可只包含评分表达式、少量显式筛选、现有Top-K/目标权重配置和冻结执行政策。若已有 DSL 能表达就直接复用；缺什么才补什么。将来遇到表达式不适合的研究，评估隔离的候选代码或模型输出，经已有 SignalArtifact/预测适配进入执行，而非无限扩展一门自制语言。此扩展需要明确的新能力范围，不能绕过现有规则。

# 分阶段开发计划

下列为规划估计，按一名熟悉仓库的开发者配合 Agent 的工程人日计，不含数据权限等待、用户研究决策及真实前瞻观察期。具体任务应先核对工作区与当前分支，避免重复已完成项。当前请求是评审和规划，本轮不实施代码修改或启动研究。

| 阶段 | 建议量级 | 交付内容 | 完成条件 |
| - | - | - | - |
| A 当前交付可用性 | 2–4人日 | CI反馈分离、当前展示接口验证、状态入口收敛 | 明确哪些检查通过；无重复科研运行 |
| B 可执行策略表达 | 5–8人日 | 个人入口最小策略后继及原生执行适配 | 支持的新方向真正改变计算，不再只改说明 |
| C 反馈与轻量记忆 | 2–4人日，可与B部分并行 | 诊断摘要、知识卡与现有历史入口贯通 | 下一次真实研究能找到相关事实和反例 |
| D 新数据与前瞻信号 | 2–4人日，条件具备即可早启 | 新快照、冻结策略的信号观察记录 | 当时可见信息、缺失与弃权完整保留 |
| E 连续影子账户 | 5–10人日或先限时可行性调查 | 原生完整账户恢复和逐日推进 | 分段与全程一致、重启幂等、权益边界明确 |
| 按需扩展 | 独立估算 | 公告、基本面、行业、预测模型或第二引擎 | 对一个实际研究问题有明确增量 |

## A 当前交付可用性

入口为 `.github/workflows/ci.yml`、`ci/apparmor/`、`application/personal_projection.py` 和 `personal_research_mcp.py`。

将静态检查及确实不依赖隔离环境的检查独立输出；需要 namespace/AppArmor 的测试仍受原安全前置条件约束。环境身份变化按实际依赖复核，保留具体运行指纹，不扩大成新的全库资格工程。只有所有要求的检查确实运行并通过，才能称完整CI恢复。

对已有四个展示后继做定向兼容检查：旧工具结构保留；缺失指标继续null；classic来源不被伪装成新运行；原件身份不符仍拒绝。新进程加载与只读连通按实际环境记录。本阶段不需要重复721日科学回测，也不为提高覆盖率写镜像式测试。

## B 可执行策略表达

优先复用 `contracts/personal_research.py`、`contracts/pit.py`、`application/personal_research.py`、`research/qlib/expression.py`、`research/qlib/signal.py`、`research/hs300_data.py` 与 `research/personal_qlib.py`。

首个后继由下一项真实用户研究触发，开放足以表达该问题的范围。将研究描述和执行政策分别绑定；新增信号有独立身份，新账户不借用旧 signal_reuse。已有经典账户只在实际依赖不变时复用。不要重写全部历史Prepared类型，也不把固定七行协议推广成所有任务永久必须七行。

验收行为：

1. 在同一数据和执行政策下，两个确实不同的支持方案产生不同表达式、身份及预期信号；改brief不伪装成改算法。

2. 未来引用、缺失字段和不支持的盘中策略在prepare阶段返回具体缺口，不静默退回固定main；信号lag与执行lag不重复移位。

3. 原生执行输出能回到当前会话，解释筛选机会、未成交、敞口、换手和费用；旧结果仍能按原身份读取。

首次工程验证使用小型确定性样例，不以全历史回测或盈利作为接口完成条件。合理的复合策略不因“一次一维”默认建议被无条件禁止。

## C 反馈与轻量记忆

复用 `personal_projection.py`、`personal_history.py`、`adaptive_feedback.py` 和已有Ledger。将今日 S/T/B、年度表现、费用、敞口与卖出路径作为有来源的派生展示，不改原report或receipt。

知识卡最小内容为：适用股票池和时期、执行/成本情景、假设、观察、支持与反例原件、解释与不确定性、失效条件。先用现有历史目录或简单索引；只有检索质量真的成为瓶颈时再考虑向量检索。

将“连续资格确认在本次范围内未获支持”写为有边界的经验，不写成“连续确认永远无效”。模型意见应能追溯至证据，过期判断可追加修订。

衡量产品改进：从方向到可执行方案的人工干预数、获得可解释结论所需时间、重复已否定提案数量、无效请求和执行失败率、工具输出体积。未测量前不设新的硬门槛，也不为了计时再运行实验。

## D 新数据与前瞻信号

历史2023–2025已反复参与选择，早期区间是否未参与选择仍UNKNOWN。不能因日期更早就命名盲测；采集2026数据也不自动证明它对研究者或模型未曝光。记录研究选择历史、数据可见时间与模型/提示版本，真正的未来观察从方案冻结后开始。[当前确认边界](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/reviews/hs300-eligibility-successor-20261103.md)

只要明确策略版本及采集范围，可先建立最小前瞻信号记录：每日保存当时已知快照、输入截止、策略/模型身份、信号及弃权原因。采集只走既有快照层，不让研究MCP临时联网取数。后续换策略另开版本；缺失日不回填成当时已发信号。

这一阶段验证时间与数据流程，不声称真实交易账户或独立确认成功。积累一个月观察可以检查运行质量，但不足以证明盈利。

## E 连续影子账户

先核实 Qlib 原生账户完整状态能否支持。只用Position字典不足以证明初始NAV、可卖持仓、未结订单、费用和历史报告连续性。最低验收是同一受支持输入上的完整回放与分段逐日推进一致，重启不会重复执行，新增快照衔接不回看未来，未知公司行动保持明确停止。

如果Qlib确实缺少成本可接受的路径，给AKQuant适配一个小额可行性任务。先匹配现有成交时钟、复权单位、交易单位、费用和限制，输出差异归因；再决定是否承接账户续跑。不能把第二引擎算出的更高收益作为迁移理由。

研究可靠性不要求先找到盈利策略才能做影子账户；但实盘券商、实时行情和分钟级系统应晚于连续状态正确性。

# 对下一项研究工作的具体建议

今天的confirm2按既定条件结束，不继续搜索1日、3日、5日确认，不因净收益改善追加机会。已有持仓缓冲和同空间生成的历史停止结论也不自动重启。

若用户希望继续研究当前规则族，最省成本的下一步是限时只读拆解原资格条件：动量转负、成交额确认消失、价格均线过滤、成员或状态变化分别在何处出现，机会存续、进场延迟和持仓路径有何关系。它只能产生描述性解释与新假设，不能当因果证明；没有信息价值就结束。它不是接收用户新研究方向的必经门禁。

任何后继比较都应保留实际账户净收益，并同时解释现金、暴露、择时、持仓与费用。T与B是诊断指标，不能用暴露归一化代替用户真实财富结果。经典对照同时改变筛选和排名；五随机只控制原资格下的排序，不能自动拿来检验改变资格后的策略。新问题按需要选择最少而充分的对照。

策略选择需要覆盖完整尝试历史；重复、失败、停止与参数变体都保留。相关性去重可节省资源，但高相关不自动说明没有增量贡献。多重比较措施按实际试验规模采用，优先复用既有实现，不预先搭建全套统计平台。

# 公告和其他扩展何时做

公告试点不能简单总结为“模型0分”。冻结记录中值匹配为76/80，对照41/80，但严格整份引用组匹配均为0/16；后续人工判断是事后复核，不回写旧分。这里提示值抽取、引用定位和语义判断需要分别看。[公告试点记录](https://github.com/Dedicatus547/quant-research-os/blob/f480dcb0d6cc1cf4db1e5344a77165b7c67e9105/docs/releases/announcement-understanding-pilot-2026-10-22.md)

下一步先让公告作为有引用的辅助研究材料可用。只有具体问题确实需要事件特征，才做新任务的新材料、相应时间/权限准入与语义评价；不要把未知发布时间或不完整来源包装成历史可交易特征。

行业、基本面、相关/标准化/截面排名等算子按真实需要逐项增加字段及时间语义。Kronos或其他模型先作为预测信号候选；新数据、新模型、新Agent和新引擎不宜同时变更，否则无法判断增量来自哪里。

流程自我改进可以先从模型提出一个具体Skill、提示或代码修改开始，说明将改善哪个可观察问题，形成独立变更并做受影响检查。不要授予模型自行改动历史结果、评价标准或数据权限的权力，也不必先建设通用自我进化平台。

# 并行开发与停止范围

建议保留两个活动worktree：一条做CI、展示兼容和维护收敛；一条做策略表达、反馈与下一真实研究问题。共享contracts、profile和结果schema指定一条写入主线，另一条按固定接口消费。研究运行、宿主空间和共享证据写入仍使用已有全局预算与串行约束。独立工作可以并行，不等于多个重型资格任务或市场回测同时开跑。

FR-03已不是默认主瓶颈；P14d-C是否完成应由实际用户功能和所需接受范围决定，不再作为必须先补完的历史里程碑。暂缓整体迁移RD-Agent、通用多Agent委员会、广泛mutation/crossover、知识图谱、自动自改进框架、重写回测会计和券商实盘接入。

**建议下一次实施范围选为A阶段加B阶段的最小接口设计，并把C阶段接入现有结果阅读。** 交付应能说明当前主线哪些工程检查可信、用户新方向将怎样改变执行、下一次研究会读取哪些已有证据。随后再按一个真正值得回答的问题启动研究，而不是为证明系统能循环而消耗预算。
