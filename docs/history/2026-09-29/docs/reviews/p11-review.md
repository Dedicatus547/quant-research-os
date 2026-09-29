# quant-research-os 与 Vibe-Trading、QuantGPT、RD-Agent 对比评估及下一阶段优化建议

> 评估日期：2026-09-08
> 评估对象：`quant-research-os` 最新 `main`、Vibe-Trading、QuantGPT、RD-Agent(Q)
> 复核口径：以仓库代码、冻结 artifact、`PLAN.md` v12 和离线质量门为准；外部项目只作为
> capability reference，不把其自述结果视为 QuantOS 的可迁移证据。
> 外部资料访问日期：2026-09-08。本文链接用于评审溯源；任何进入实现的 donor capability
> 仍须在对应 ADR 中固定 release/tag/commit，不能依赖 mutable `main`。

---

# 1. 执行摘要

截至 2026-09-08，`quant-research-os` 已经从“确定性量化研究内核”演进为具有受限 typed
application boundary 的 agent-ready research kernel。它已经具备自动研究系统所需的主要 authority
骨架，但还不能把 production MCP transport、Agent 真实生成的 proposal chain 或真实 Evidence 到
Data-qualified research 的组合运行写成已完成能力。

当前项目已经完成：

```text
P0-P7  Deterministic Research Kernel
P8     Agent Boundary & Threat Hardening
P9     Research Semantic Contracts
P10    GPT + Codex Harness Qualification
P11    Typed service facade + Proposal → Qlib → Validation → Registry E2E
```

真实 Tushare Data-qualified 链路也已经完成正式验证，但它属于 P3-P7 的独立资格轨道。P11 则在
`STRUCTURED_FIXTURE / data_qualified=false` 上实现：

```text
Evidence
→ ObservationProposal
→ HypothesisProposal
→ FactorProposal
→ ExperimentProposal
→ deterministic compiler
→ ResolvedExperiment
→ PIT
→ Qlib
→ ValidationReport
→ Registry
→ InterpretationProposal
```

并且两条独立 native-Qlib pipeline 能产生 byte-exact authority hashes。该 E2E 的 proposal 与
reviewer interpretation 由仓库代码固定构造，并直接调用 typed Python facades；P10 验证过的 stdio
MCP 是独立 mock server，不能与 P11 direct-facade E2E 拼接成 production transport 证明。

因此，项目已经回答了一个较窄但重要的问题：

```text
冻结的、已被 formal boundary 接纳的研究能否被可信执行？
```

答案是肯定的。当前尚未回答的是：

```text
如何从真实 Evidence 形成高质量 proposal？
现有 admitted DSL 能否完整穿过 proposal/compiler/execution？
如何在完整记录搜索空间后选择下一个值得研究的问题？
```

也就是说：

> **QuantOS 的“实验室”已经明显比“研究员”成熟，但实验室目前仍只开放了很窄的正式实验入口。**

对现有冻结 artifact 边界继续重复加固的边际收益会下降，但 P12 会引入新的网络、来源和 parser
攻击面，因此 provenance 与 filesystem/network isolation 仍是 P12 的核心工作。除此之外，工程资源
应开始转移到：

```text
Existing DSL end-to-end propagation
Factor-level diagnostics
Research search policy
Multiple testing
Knowledge retrieval
Factor redundancy
Factor-model joint optimization
Regime analysis
```

综合比较后，建议保持以下项目定位：

| 项目 | 最适合借鉴的能力 |
|---|---|
| `quant-research-os` | 系统主体；Evidence、PIT、Formal Spec、Validation、Authority |
| QuantGPT | 自动因子搜索、Mutation/Crossover、Anti-overfit |
| RD-Agent(Q) | Research scheduler、Factor–Model 联合优化 |
| Vibe-Trading | 金融研究工具、因子库、事件研究、数据正确性经验 |

核心原则应是：

> **借鉴其他项目的研究算法和金融方法，不复制它们的 Runtime 和 Authority Model。**

---

# 2. 当前 quant-research-os 的定位已经发生变化

早期的 `quant-research-os` 可以描述为：

```text
Deterministic Quant Research Pipeline
```

当前更准确、也更克制的定位应该是：

```text
Trusted Quant Research Authority Foundation
```

原因是它已经建立了完整的 authority hierarchy，但尚未完成真实 Evidence、Agent transport、
自主 campaign 与 factor-level research feedback。因此“Operating System”更适合作为长期目标，
不宜作为当前实现状态声明。

```text
Source Evidence
      ↓
Agent Proposal
      ↓
Deterministic Admission
      ↓
Canonical Experiment
      ↓
Execution Evidence
      ↓
Validation Verdict
```

P9 已经正式冻结：

- `EvidenceRecord`
- `ExtractedTextArtifact`
- `EvidenceCitation`
- `ObservationProposal`
- `HypothesisProposal`
- `FactorProposalSpec`
- `ExperimentProposalSpec`
- `ResearchFamilySpec`
- `ResearchBudgetSpec`
- `ResearchCampaignSpec`
- `AgentRunManifest`
- `ResearchLedgerEvent`
- `ResearchLedgerSnapshot`

并明确规定：

> Agent proposal 没有 validation authority；Agent 不能携带、创建或修改 verdict。

这与 Vibe-Trading、QuantGPT 和 RD-Agent 的根本差异在于：

```text
其他系统：
Agent 是研究系统的中心

QuantOS：
Formal Contract + Deterministic Authority 是中心
Agent 是受控研究参与者
```

这是应该继续坚持的架构优势。

---

# 3. 四个系统解决的其实不是同一个问题

如果按照“功能数量”比较，Vibe-Trading 显然更丰富。

如果按照“自动因子发现”，QuantGPT 和 RD-Agent 当前更成熟。

但按照：

> **自动研究结论是否可追溯、可复现、可证伪，并且不能被 Agent 越权修改**

这一标准，QuantOS 的设计更严格。

可以将四者抽象为：

```text
QuantGPT
=
Factor Search Engine

RD-Agent
=
Autonomous R&D Engine

Vibe-Trading
=
Finance Capability Platform

QuantOS
=
Trusted Research Authority
```

因此最终系统不应试图让 QuantOS 变成另一个 Vibe-Trading。

更合理的目标是：

```text
                   QuantOS
                     │
       ┌─────────────┼─────────────┐
       │             │             │
  QuantGPT ideas   RD-Agent ideas  Vibe ideas
       │             │             │
 Factor Search   Research Policy  Finance Tools
```

---

# 4. 与 QuantGPT 对比：QuantOS 当前最大的缺口是“搜索策略”

QuantGPT 当前已经具备比较完整的因子自动搜索系统。

其公开架构包含：

```text
TrajectoryAnalyzer
        ↓
MetaEvolutionSelector
        ↓
EXPLOIT / EXPLORE / RECOMBINE / SIMPLIFY
        ↓
MutationEngine
        ↓
CrossoverEngine
        ↓
Factor Evaluation
```

并提供 8 类定向 mutation、60+ factor operators、anti-overfit 测试和 walk-forward validation
（[QuantGPT README](https://github.com/Miasyster/QuantGPT/blob/main/README.md)）。

这说明 QuantGPT 已经不仅解决：

```text
如何验证一个因子
```

而且解决了一部分：

```text
验证完成以后，下一个候选怎么产生
```

这恰恰是 QuantOS P14 将面临的问题。

---

# 5. 为什么不能简单让 GPT 自己决定“下一步研究什么”

一种最简单的 P14 实现可能是：

```text
Research Ledger
      ↓
GPT Reviewer
      ↓
“我认为下一步应该尝试 X”
      ↓
new experiment
```

这种方法看起来很自然，但存在一个严重问题：

> 它把“研究搜索算法”重新退化成了不可审计的自然语言推理。

如果 Agent 不断：

```text
修改窗口
修改组合
增加过滤条件
修改股票池
重新解释失败结果
```

系统实际上会逐渐形成一个自动 p-hacking loop。

即使：

```text
每个单独 experiment 都 PIT-safe
每个 backtest 都正确
每个 ValidationReport 都真实
```

最终被选中的 candidate 仍然可能只是：

```text
大量试验后的幸运赢家
```

因此 QuantOS 下一阶段最值得从 QuantGPT 借鉴的不是它的 parser，而是：

> **显式 Search Policy。**

---

# 6. 建议新增 SearchPolicySpec

Research search 本身应该成为 Formal Spec。

但它必须与当前预冻结 `ResearchFamilySpec` 兼容。第一版 SearchPolicy 只负责有限 family 内的
枚举顺序、资源调度和选择规则，不允许通过 mutation 临时扩大候选空间。例如：

```yaml
schema_version: research-search-policy/v1
family_hash: ...
candidate_enumeration: canonical_parameter_product
candidate_order: canonical_hash_ascending
failure_handling: count_and_continue
tie_breaker: canonical_candidate_hash
selection_policy_hash: ...

selection:
  novelty_weight: 0.20
  factor_quality_weight: 0.30
  robustness_weight: 0.30
  complexity_penalty: 0.10
  redundancy_penalty: 0.10
```

系统变成：

```text
LLM
负责：
研究含义、经济解释、非形式化假设

SearchPolicy
负责：
允许怎么搜索

ResearchBudget
负责：
最多搜索多少

Validation
负责：
单个结果是否成立

CampaignSelectionReport
负责：
完整搜索后是否选中候选
```

这非常符合 QuantOS 最初的核心原则：

> **能形式化的规则尽量形式化。**

搜索策略本身显然是可以形式化的，因此不应完全留给 Agent。

Mutation/crossover 会改变 AST 结构，与当前要求准确 `declared_candidate_count` 的 finite-family
contract 存在直接张力。只有未来 family v2 预先冻结有限 grammar、最大深度、候选身份、随机种子、
枚举顺序、tie-breaker 和 failure handling 后，结构搜索才能进入正式 campaign。

---

# 7. 不建议复制 QuantGPT 的自研 Expression Runtime

QuantGPT 的 expression parser 支持 60+ operators，并作为系统的重要基础设施
（[QuantGPT README](https://github.com/Miasyster/QuantGPT/blob/main/README.md)）。

但 QuantOS 不应该因此建设：

```text
QuantOS Factor Engine
```

因为当前架构已经选择：

```text
Formal AST
    ↓
admission
    ↓
Qlib official semantics
```

这条路线更适合 QuantOS。

原因有三个。

第一，自研 parser/runtime 会产生第二套数值语义。

最终需要证明：

```text
QuantOS evaluator
=
Qlib evaluator
```

这会增加大量维护和验证成本。

第二，Factor engine 会逐渐变成另一个 Qlib。

这违反项目当前：

> 优先 thin adapter、避免重复建设 quant infrastructure

的原则。

第三，QuantOS 真正的竞争力不是表达式计算速度，而是：

```text
PIT
Provenance
Authority
Campaign Governance
Validation
Research Memory
```

因此正确做法不是复制 QuantGPT parser，而是**扩充现有 SafeQlibExpressionSpec**。

---

# 8. 先打通现有 DSL，再扩张 operator

当前 P9 新增的正式 operators 只有：

```text
abs
delta
rolling_sum
rolling_min
rolling_max
```

而以下操作仍然被明确排除：

```text
correlation
zscore
cross_section_rank
clip
log
industry neutralization
size neutralization
```



P9 阶段的这种保守策略是合理的，因为当时主要目标是验证 operator qualification 机制。仓库实际
还有 `ref`、`return`、`rolling_mean`、`rolling_std`、时间序列 `rank` 与基础算术等
已 admitted operator；当前更窄的限制来自 P11 compiler，而不是 public enum：

```text
proposal compiler
= only adjusted_close → return(window)

Qlib field mapping
= only adjusted_close → $close
```

因此首要任务不是再向 enum 添加名字，而是让已有 operator 与 registered fields 通过
proposal/compiler/resolution/PIT/Signal/Validation 全链路。完成后再扩展经典量价因子需要的：

```text
Corr(price, volume)
Rank(...)
ZScore(...)
Log(volume)
```

RD-Agent 的 Qlib 场景同样依赖更丰富的 factor/model research surface
（[RD-Agent Quant documentation](https://github.com/microsoft/RD-Agent/blob/main/docs/scens/quant_agent_fin.rst)）。

因此建议优先扩展：

```text
Phase A
existing admitted DAG end-to-end propagation
registered field mapping

Phase B
correlation
log
clip

Phase C
cross_section_rank
zscore

Phase D
decay
weighted_mean

Phase E
industry_neutralize
size_neutralize
```

仍然保持现有规则：

> 每新增一个 operator，都必须单独证明 Qlib semantics、PIT requirements、NaN semantics、delay semantics 和 reproducibility。

这样既扩展研究能力，又不会牺牲 QuantOS 的可信性。

---

# 9. 建议进一步把 Factor IR 分层

当前可以继续使用 DAG，但长期最好将：

```text
时间序列计算
横截面变换
中性化
```

区分开。

例如：

```yaml
factor:

  time_series:
    expression:
      delta:
        field: close
        window: 20

  cross_section:
    - winsorize
    - zscore
    - rank

  neutralization:
    - industry
    - log_market_cap
```

而不是全部表达成：

```text
rank(
  zscore(
    neutralize(
      delta(close,20)
    )
  )
)
```

这样做的好处不是语法美观，而是能够建立更强的 type system。

例如：

```text
delta
输入：TimeSeries
输出：TimeSeries

cross_section_rank
输入：CrossSection
输出：CrossSection

neutralize
输入：CrossSection + ExposureMatrix
输出：CrossSection
```

这会使很多语义错误在运行前就被拒绝。

---

# 10. P14 前最重要的并行基础：Immutable ResearchResult

当前正式 Data-qualified pipeline 已经可以验证：

```text
Return
Sharpe
Drawdown
Turnover
Robustness
Cost sensitivity
```

但 Rank IC / ICIR 当前仍明确属于：

```text
NOT CLAIMED
```

原因是缺少 immutable Qlib `ResearchResult` adapter。

这在 P0-P11 阶段不是严重问题。

因为之前主要任务是证明：

```text
Experiment → Strategy → Backtest → Validation
```

能够正确运行。

但是进入 P14 automatic factor search 后，它会成为明显缺陷。

---

# 11. 为什么自动 Factor Search 必须优先拥有 IC/ICIR

因子发现阶段和策略验证阶段不是同一个问题。

一个 factor 的 portfolio Sharpe 会受到：

```text
Top-K
权重
换手
交易成本
持仓数
rebalance frequency
benchmark
```

大量策略参数影响。

因此如果自动 research loop 把：

```text
Sharpe
```

作为主要 feedback signal，会导致 Agent 同时优化：

```text
Factor
+
Portfolio Construction
```

搜索噪声非常大。

而 Factor research 更适合先看：

```text
Rank IC
IC mean
ICIR
IC distribution
IC positive ratio
Top-bottom spread
Coverage
Signal autocorrelation
Factor turnover
```

Vibe-Trading 的 Alpha Zoo benchmark 也使用 IC、IR 和 alive/reversed/dead 分类作为 factor-level
diagnostic（[Vibe-Trading releases](https://github.com/HKUDS/Vibe-Trading/releases)）。

因此建议建立与 P12/P13 并行、但不改变主线编号的前置工作：

```text
FR-02
Minimal Immutable Qlib ResearchResult
```

第一版至少导出：

```text
prediction / label / split / expression lineage
IC and Rank IC series
IC / Rank IC / ICIR / Rank ICIR summaries
Qlib long-short series when enabled and qualified
```

Qlib `SignalRecord` / `SigAnaRecord` 可以提供上述核心序列和汇总。Coverage、factor turnover、
signal autocorrelation 与自定义 top-bottom spread 并非都由这两个 Record Template 直接提供；
它们必须逐项冻结定义、比较域、缺失值语义和实现来源，不能在第一版中笼统写成“Qlib 原生产物”。

QuantOS 只负责：

```text
normalize
serialize
hash
verify
gate
```

不要重新实现 IC engine。

---

# 12. 与 QuantGPT 对比后，第二个必须补齐的是 Anti-overfit

QuantGPT 已经显式提供：

```text
anti-overfit tests
walk-forward validation
independent validation
```

来源：[QuantGPT README](https://github.com/Miasyster/QuantGPT/blob/main/README.md)。


而 QuantOS P9 目前已经正确解决了第一层问题：

```text
search family 必须 pre-freeze
attempt 必须计数
OOS access 必须一次性
contamination 必须传播
```

但 P9 文档自己也非常准确地指出：

> `PREFROZEN_FINITE_FAMILY` 只能证明搜索空间事先声明，并没有统计修正 selection bias。

这意味着：

```text
搜索了 100 个因子
最后一个 Sharpe 2.0
```

不能简单理解为：

```text
这是一个真正 Sharpe 2.0 的因子
```

---

# 13. 建议增加独立的 CampaignSelectionReport

当前 G0-G10 判断单个 experiment 及其证据；trial accounting、multiple testing 和跨候选
redundancy 判断整个 campaign。二者不应共享同一层级。建议形成：

```text
Experiment ValidationReport
        ↓
Immutable CampaignSelectionReport
        ↓
selected candidate / no selection
```

Placebo 与 purged/embargoed walk-forward 可以生成 experiment-level evidence；
CampaignSelectionReport 则必须消费：

```text
complete trial accounting
all candidate results and failures
pre-frozen selection policy
qualified multiple-testing correction
cross-candidate redundancy evidence
```

Vibe-Trading 已经拥有 factor-analysis、IC benchmark、look-ahead guard 和 PIT-safe
fundamental-factor 经验；其大规模 Alpha Zoo 也说明 research space 扩大后 search correctness
会迅速成为核心问题（[Vibe-Trading changelog](https://github.com/HKUDS/Vibe-Trading/blob/main/CHANGELOG.md)）。

这里有一个重要原则：

> multiple-testing correction 属于 deterministic validation，不属于 Agent Reviewer。

Agent 可以解释为什么一个 candidate 失败。

但：

```text
p-value
FDR
Deflated Sharpe
```

必须由程序计算。但 BH/FDR、Deflated Sharpe Ratio 与 PBO 的输入假设和适用对象不同，第一版
不应把它们当成可以同时勾选的“anti-overfit 套餐”；只实现与冻结 family 和 metric semantics
匹配、且有 golden/E2E 证据的方法。

---

# 14. 与 RD-Agent 对比：未来必须考虑 Factor–Model 联合搜索

RD-Agent(Q) 最大的特色并不是 multi-agent。

其真正值得借鉴的是：

> **factor-model co-optimization。**

RD-Agent 官方将 `fin_quant` 定义为 coordinated factor-model joint evolution，并分别提供：

```text
fin_factor
fin_model
fin_quant
```

三个研究 loop（[RD-Agent README](https://github.com/microsoft/RD-Agent/blob/main/README.md)）。

官方报告的自身实验结果显示，其联合优化方案相对 benchmark factor libraries 达到约 2× ARR，
同时使用超过 70% 更少 factors。这个结果应视为 RD-Agent 作者报告的实验结果，而不是对所有市场
和系统的普适保证（[R&D-Agent-Quant paper](https://arxiv.org/abs/2505.15155)）。

但它说明了一个合理的研究问题：

```text
固定 LGBModel
+
不断找 Factor
```

可能不是最终最优路线。

---

# 15. 为什么暂时不应该马上做 Factor–Model Joint Search

虽然这个方向重要，但不建议现在进入 P12-P14 的关键路径。

原因是联合优化会让搜索空间从：

```text
Factor
```

扩大为：

```text
Factor × Model × Hyperparameters
```

这会使 multiple-testing 和 search-budget 问题指数级放大。

因此正确顺序应该是：

```text
先把：
Factor autonomous research
做可信

再把：
Model family
加入 search space
```

建议未来新增：

```text
P15 Factor–Model Joint Research
```

但仍保持 Formal Spec：

```yaml
model_family:

  allowed_models:
    - LGBModel
    - Linear
    - MLP

  hyperparameters:

    num_leaves:
      - 16
      - 32
      - 64

    learning_rate:
      - 0.01
      - 0.05
```

Agent 不能：

```text
随便写一个 neural_network.py
```

而只能：

```text
提出 ModelProposal
        ↓
ModelFamilySpec admission
        ↓
Qlib execution
```

这样可以借鉴 RD-Agent 的联合优化思想，而不复制 arbitrary code generation。

---

# 16. RD-Agent 还值得借鉴一个更基础的思想：Research Scheduler

自动科研不能永远让 Reviewer Agent 自己决定：

```text
下一步研究哪个方向
```

更合理的是建立：

```text
Research Direction Scheduler
```

将不同研究方向视为不同 arms：

```text
momentum
reversal
volume
volatility
event
fundamental
cross-factor
```

每个方向获得 deterministic score，例如：

```text
ResearchScore
=
novelty
+ factor quality
+ robustness
+ OOS survival
- complexity
- redundancy
- compute cost
```

然后：

```text
Agent
提出新的 semantic hypothesis

Scheduler
决定资源往哪里分配
```

这比：

```text
LLM 自己说“我觉得接下来应该研究成交量”
```

更符合 QuantOS 的设计哲学。

---

# 17. 与 Vibe-Trading 对比：最值得借的是 Research Tooling

Vibe-Trading 当前已经成为非常大的金融研究平台。

其公开版本当前包括：

- 462 Alpha Zoo；
- 多个 backtest engines；
- 90 左右金融 skills；
- 30 multi-agent swarm presets；
- 大量市场数据源；
- factor analysis；
- correlation regime；
- Strategy Development Manager；
- hypothesis registry；
- scheduled research（[Vibe-Trading releases](https://github.com/HKUDS/Vibe-Trading/releases)）。

但大多数能力不应该直接进入 QuantOS。

真正值得借鉴的部分是：

```text
Factor Diagnostics
Event Study
Multiple Testing
Cross Validation
Regime Analysis
Research Paper Workflow
Factor Decay Monitoring
```

---

# 18. 为什么不要模仿 Vibe-Trading 的“能力广度”

Vibe-Trading 同时维护大量：

```text
Markets
Data Providers
Backtest Engines
Broker Connectors
Agents
Skills
Alpha Families
```

这带来了非常高的 semantic surface。

例如 Vibe-Trading 在 2026 年持续修复大量数据和回测 correctness 问题，包括：

- A 股 fallback provider 之间 volume unit 不一致会造成约 100× 量级跳变；
- partial market-data fallback 可能静默缩小 universe；
- portfolio optimizer look-ahead；
- source-specific data corruption；
- provider semantics 不一致（[Vibe-Trading changelog](https://github.com/HKUDS/Vibe-Trading/blob/main/CHANGELOG.md)）。

这不是 Vibe-Trading 特有的问题。

它说明一个更普遍的工程事实：

> **每增加一个 provider、market、engine 或 fallback path，都在增加新的隐式语义。**

因此 QuantOS 当前：

```text
Canonical A-share market data
=
Tushare

Other data
=
Discovery / Evidence only
```

的策略应该继续保持。

---

# 19. P12 Evidence Acquisition 应吸收 Vibe 的 correctness 经验

P12 是 Agent-assisted Research 轨道第一个接入真实非结构化 Evidence 的模块；这不否定
P2-P7 已完成的真实 Tushare market-data 资格轨道。

这意味着它会第一次面对：

```text
发布时间不确定
文档 revision
source fallback
网页变更
parser 错误
缺失字段
source identity
```

因此 Evidence acquisition 的 exit criteria 应比普通“能下载公告”严格得多。

首先是时间语义。

如果公告源只能证明：

```text
2026-09-08
```

但不能证明：

```text
2026-09-08 10:32:18
```

系统不能推断：

```text
10:00 已经可以知道
```

日频策略更安全的规则应该是：

```text
unknown publication time
→ next eligible trading session
```

除非 source 提供可验证的 timestamp。

其次是完整性。

不能仅凭：

```text
expected evidence = 0
actual evidence = 0
→ PASS
```

就断言完整。零结果在官方源提供可验证 total/count、完整分页边界或等价 completeness witness
时可以合法 PASS；否则才应该是：

```text
SOURCE_INCOMPLETE
```

第三是 dependency propagation。

如果 EventFeature 依赖：

```text
event_type
amount
announcement_time
entity
```

只要任何 required field 缺失：

```text
Feature = invalid
```

而不能让某个计算路径碰巧产生 finite value 就继续执行。

---

# 20. P12 后建议优先加入 Literature Evidence

P12 第一种 Evidence Source 选择：

```text
SSE / SZSE announcements
```

非常合理。

但第二种 Evidence Source 我建议优先选择：

```text
Academic Papers
```

而不是首先扩大新闻源。

原因是论文天然包含：

```text
明确 claim
变量定义
机制
公式
历史实验
可证伪条件
```

非常适合：

```text
Paper
 ↓
EvidenceRecord
 ↓
HypothesisProposal
 ↓
Formal Factor
 ↓
A-share replication
```

RD-Agent 已经展示了从 financial reports 生成 factor hypothesis、实现 factor 并通过 Qlib 验证的
workflow（[RD-Agent README](https://github.com/microsoft/RD-Agent/blob/main/README.md)）。

Vibe-Trading 也已经将 academic factors 和 research-to-strategy workflow 纳入其研究工具
（[Vibe-Trading changelog](https://github.com/HKUDS/Vibe-Trading/blob/main/CHANGELOG.md)）。

对于 QuantOS 而言，论文 replication 比新闻情绪预测更符合：

> Formalizable Research

这一长期定位。

---

# 21. Research Ledger 不应该只是一个普通 RAG

P9 已经建立 `ResearchLedgerEvent` 和 `ResearchLedgerSnapshot`。

但 P14 真正实现 searchable Research Ledger 时，不建议只做：

```text
embedding search
```

因为两条研究可能：

```text
自然语言完全不同
```

但计算出来：

```text
signal correlation = 0.96
```

这实际上是同一个研究方向。

因此建议 Research retrieval 至少包含三种 similarity：

```text
Semantic Similarity
+
Structural Similarity
+
Empirical Similarity
```

Semantic：

```text
Hypothesis embedding
```

Structural：

```text
Canonical AST fingerprint
```

Empirical：

```text
Signal correlation
```

三种相似度的 authority 必须区分。Semantic embedding 只能是可重建检索缓存；若使用模型，
必须冻结 model/tokenizer/config、输入 hash、归一化、tie-breaker 与网络策略。Empirical
correlation 必须绑定共同 universe、date range、coverage filter 和 missing-value policy，
不能把任意两个不重合信号的相关系数当成稳定 fingerprint。

这样系统才能识别真正重要的：

```text
Pseudo Novelty
```

即：

> Agent 看起来提出了一个新想法，但实际上只是已有 factor 的变体。

---

# 22. 建议增加 Factor Registry

目前 QuantOS 已经有成熟的：

```text
Strategy Registry
```

Research Ledger 则负责科研过程。

长期可以再增加：

```text
Factor Registry
```

第一版不建议立即建立第三套独立 authority。更安全的做法是先把 Factor Registry 实现为从
immutable FactorSpec、ResearchResult、ValidationReport 与 Research Ledger 重建的 projection；
只有出现无法由既有 authority 表达的生命周期事务后，才升级为独立 append-only registry。

三者职责分别为：

```text
Research Ledger
=
为什么研究、如何演进

Factor Registry
=
研究对象到底是什么

Strategy Registry
=
最终策略生命周期
```

Factor Registry 保存：

```text
FactorSpec hash
AST fingerprint
Hypothesis lineage
Evidence lineage
signal fingerprint
signal correlation
IC history
regime performance
decay history
validation history
status
failure reasons
```

这是后续：

```text
Factor redundancy
Factor reuse
Factor combination
Model feature selection
```

的基础。

---

# 23. Regime Analysis 应进入长期路线

当前 QuantOS robustness 主要使用：

```text
calendar subperiod
```

例如：

```text
2015-2017
2018-2020
2021-2023
2024-2025
```

这是必要的，但不足以回答：

> “为什么这个 factor 在某一时期失效？”

QuantGPT 已经加入 bull/bear/sideways stress 思路，而 Vibe-Trading 也提供 correlation regime
分析（[QuantGPT README](https://github.com/Miasyster/QuantGPT/blob/main/README.md)，
[Vibe-Trading changelog](https://github.com/HKUDS/Vibe-Trading/blob/main/CHANGELOG.md)）。

因此长期可以增加：

```yaml
RegimeSpec:

  trend:
    - bull
    - bear
    - neutral

  volatility:
    - low
    - normal
    - high

  liquidity:
    - loose
    - tight
```

但最重要的是：

> Regime definition 必须在实验前冻结。

不能允许 Agent 看见结果以后说：

```text
“这个因子其实只在
低波动 + 中等趋势 + 某类年份有效。”
```

否则 Regime Analysis 本身又会成为 p-hacking 工具。

---

# 24. GPT + Codex 暂时不需要升级为 Multi-Agent Swarm

Vibe-Trading 发布记录列出 30 个 swarm presets
（[Vibe-Trading releases](https://github.com/HKUDS/Vibe-Trading/releases)）。

QuantGPT 强调 dual-model cross-review
（[QuantGPT README](https://github.com/Miasyster/QuantGPT/blob/main/README.md)）。

RD-Agent 本身采用 multi-agent R&D。

但是 QuantOS 当前没有必要因此增加：

```text
Researcher model
Critic model
Risk model
Judge model
```

原因是 QuantOS 已经拥有它们缺少或较弱的：

```text
Deterministic Compiler
PIT Gate
Validation Gate
Campaign Governance
```

因此第二个 LLM 在：

```text
“判断这个结果是否正确”
```

方面的边际价值没有那么高。

当前的单 Runtime + 三个 logical-role Skill 已足够继续做边界和 E2E 工程：

```text
GPT + Codex
+
quant-researcher Skill
+
quant-formalizer Skill
+
quant-reviewer Skill
```

但 P10 只证明 Harness capability，P11 只证明代码内固定 proposal 的 direct-facade E2E；
它们尚未证明 researcher/formalizer/reviewer 的真实研究质量。第一次质量结论应来自 P13 的冻结
真实 Evidence benchmark，而不是从 9/9 capability 或 synthetic hash reproduction 推导。



未来只有通过 benchmark 证明：

```text
Independent Critic
```

显著改善：

```text
Novel hypothesis rate
PIT-valid rate
Duplicate rate
OOS survival
Research cost
```

以后，才值得增加第二模型。

---

# 25. Agent Context Budget 应成为 P14 的正式治理对象

P10 capability spike 已经说明 Agent context 本身会产生可观成本。

未来 autonomous research loop 可能涉及：

```text
Evidence
+
Research Ledger
+
Factor Registry
+
Past Failures
+
Validation Reports
+
MCP schemas
```

如果每次 Agent Run 都直接输入全部历史信息，随着研究累积：

```text
context cost
≈ monotonically increasing
```

最终研究成本会失控。

因此建议新增：

```text
ResearchContextPack
```

例如：

```yaml
schema_version: research-context-pack/v1

question_hash: ...
ledger_snapshot_hash: ...
retrieval_policy_hash: ...
index_build_hash: ...
tokenizer_hash: ...
tie_breaker: canonical_object_hash

relevant_rules:
  max_items: 10

related_failures:
  max_items: 10

similar_factors:
  max_items: 10

relevant_evidence:
  max_items: 20

unresolved_questions:
  max_items: 5

token_budget: 20000
```

由 deterministic retrieval 生成：

```text
ResearchContextPack
        ↓
Codex
```

而不是：

```text
Entire Research Database
        ↓
Codex
```

每个 `AgentRunManifest` 再绑定：

```text
context_pack_hash
```

`token_budget` 只有在 tokenizer/model configuration、截断顺序与溢出失败语义被冻结后才可审计；
否则相同 item limit 仍可能生成不同上下文。ContextPack 是 immutable Agent input，不是 evidence
或 verdict authority。

这样能够同时改善：

```text
Cost
Auditability
Context Stability
Reproducibility
```

---

# 26. 建议调整后的路线图

综合四个项目的经验，我建议在当前：

```text
P12
P13
P14
```

基础上细化，而不改变主线编号：

```text
P12
Real-world Evidence Acquisition

FR-01 / FR-02（与 P12/P13 并行）
Existing DSL E2E + Immutable Factor ResearchResult

P13
Qualified Event Feature + Event Study E2E

P14a
Ledger persistence + ResearchContextPack

P14b
Frozen-family enumeration + duplicate evidence

P14c
CampaignSelectionReport

P14d
Bounded autonomous loop

P15
Factor–Model Joint Research

P16
Regime-aware Research Lifecycle
+ Alternative Agent Stack Benchmark
```

---

# 27. P12 — Real-world Evidence Acquisition

保留当前方向。

重点新增：

```text
publisher identity
publication-time semantics
revision lineage
availability policy
source completeness
parser provenance
missing-field propagation
```

第一数据源：

```text
SSE / SZSE official announcements
```

第二数据源建议：

```text
Academic literature
```

不要急着建设大规模：

```text
News crawler
Social media crawler
Alternative-data platform
```

---

# 28. FR-01 / FR-02 — Factor Research Foundation

这是与 P12/P13 并行、并在 P14 前必须完成的前置工作，不单独改变 P12-P14 编号。

目标：

```text
Existing admitted SafeQlibExpressionSpec
        ↓
general proposal/compiler/execution propagation

Qlib Factor Evaluation
        ↓
Immutable ResearchResultArtifact
```

ResearchResult 第一版至少包含：

```text
prediction / label / split / expression lineage
IC and Rank IC series
IC / Rank IC / ICIR / Rank ICIR summaries
qualified Qlib long-short series
```

原因：

> P14 的 autonomous factor search 必须有 factor-level feedback，而不能主要依赖 portfolio Sharpe。

Coverage、factor turnover、signal autocorrelation 和其他 diagnostics 在定义与实现来源单独
资格化后增量加入，不作为第一版退出条件。

---

# 29. P13 — Qualified Event Feature E2E

目标保持：

```text
Announcement
      ↓
Evidence
      ↓
ExtractionProposal
      ↓
Admission
      ↓
EventFeatureArtifact
      ↓
Factor
      ↓
SignalArtifact
      ↓
Backtest

FR-02 ready 时并行产生
Immutable ResearchResult
```

P13 不因 FR-02 自动阻塞；只有冻结的 P13 acceptance metrics 要求 Rank IC/ICIR 时，
ResearchResult 才成为其前置。

建议增加 deterministic：

```text
Event Study primitives
```

例如：

```text
event window return
abnormal return
CAR
pre-event drift
post-event drift
event count
cross-sectional event conditioning
```

这样大量 Event Hypothesis 可以通过 Formal Spec 表达，而不是每次让 Agent 写自定义代码。

---

# 30. P14 — Bounded Autonomous Factor Research

这是 QuantOS 真正开始拥有“发现能力”的阶段。

不建议在一个阶段中同时完成全部搜索能力，应拆成依赖明确的四个 slice：

```text
P14a
Research Ledger persistence/rebuild
deterministic ResearchContextPack

P14b
pre-frozen family enumeration
canonical AST fingerprint
duplicate / redundancy evidence

P14c
immutable CampaignSelectionReport
qualified multiple-testing policy

P14d
bounded autonomous loop
optional grammar-bounded mutation/crossover
```

Agent 的职责变成：

```text
提出语义研究方向
解释 experiment result
提出 mechanism
提出新的 Formal Proposal
```

而 deterministic research engine 负责：

```text
candidate enumeration
search budget
mutation constraints
duplicate detection
statistical correction
selection
```

P14 首版应停留在 frozen-family enumeration。Mutation/crossover 只有在 family v2 能证明有限
grammar、最大深度、候选身份和 selection denominator 后才进入 P14d；否则继续生成新 proposal，
但不得在原 campaign 中冒充已预冻结候选。

---

# 31. P15 — Factor–Model Joint Research

参考 RD-Agent，但保持 QuantOS Formal Spec。

流程：

```text
Factor Family
      ↕
Model Family
      ↓
Qlib
      ↓
Validation
```

Model search 也必须：

```text
finite
prefrozen
typed
budgeted
audited
```

不允许 arbitrary model code generation。

---

# 32. P16 — Regime-aware Lifecycle

增加：

```text
Factor decay
Regime performance
Structural break
Correlation change
Validity lifecycle
```

Factor 可以拥有：

```text
CANDIDATE
VALIDATED
MONITORING
DECAYING
DEAD
REVERSED
```

但状态转换必须来自：

```text
deterministic evidence
```

而不是 Agent 判断。

Vibe-Trading 当前 Strategy Development Manager 已经开始跟踪 IC/Sharpe decay，这说明“研究发现
之后如何持续监测失效”本身也是独立的重要能力
（[Vibe-Trading changelog](https://github.com/HKUDS/Vibe-Trading/blob/main/CHANGELOG.md)）。

---

# 33. 哪些能力明确不建议复制

## Vibe-Trading

不建议复制：

```text
几十个 canonical providers
大量 fallback chains
多个 backtest engines
30-agent swarm
broker integrations
multi-market infrastructure
```

原因：

> 这些都会扩大 QuantOS 最希望控制的 semantic surface。

---

## QuantGPT

不建议复制：

```text
custom 60+ operator evaluator
custom backtest authority
Cloud validation as canonical dependency
```

原因：

> 会产生第二套 factor/backtest truth。

---

## RD-Agent

不建议复制：

```text
Agent-generated arbitrary factor code
Agent-generated arbitrary model implementation
Agent-controlled experiment code mutation
```

原因：

> 这些能力直接跨越 QuantOS 的 Formal Specification Boundary。

---

# 34. 最值得吸收的三套能力

最终应该形成：

```text
QuantGPT
   ↓
Search / Evolution

RD-Agent
   ↓
Research Scheduling
Factor–Model Joint Search

Vibe-Trading
   ↓
Finance Diagnostics
Event Study
Multiple Testing
Regime / Decay
```

但最终都进入：

```text
QuantOS Formal Contracts
+
Deterministic Services
```

而不是：

```text
QuantOS
→ 调用另外三个 Agent Runtime
```

---

# 35. 建议的最终架构

```text
                  REAL WORLD
                      │
             Discovery Plane
                      │
             Evidence Store
                      │
═══════════════ FREEZE ═══════════════
                      │
                      ▼
                GPT + Codex
                      │
          semantic interpretation
                      │
                      ▼
               HypothesisSpec
                      │
                      ▼
              Formal Research IR
                      │
         ┌────────────┼────────────┐
         │            │            │
         ▼            ▼            ▼
 Factor Search   Event Research   Model Search
 QuantGPT-like                   RD-Agent-like
         │            │            │
         └────────────┼────────────┘
                      │
                      ▼
                    Qlib
                      │
                      ▼
          Immutable ResearchResult
                      │
         ┌────────────┼────────────┐
         │            │            │
      IC/IR       Backtest      Regime
         │            │            │
         └────────────┼────────────┘
                      ▼
              Validation Gates
                      │
                      ▼
          Experiment ValidationReport
                      │
                      ▼
           CampaignSelectionReport
                      │
                      ▼
   Factor Projection / Strategy Registry
                      │
                      ▼
               Research Ledger
                      │
                      ▼
               Search Scheduler
                      │
                      └────→ Next Research
```

---

# 36. 最终建议与优先级

如果把未来开发资源分成三个等级，我建议：

## 第一优先级

```text
P12 Evidence
FR-01 existing DSL end-to-end propagation
FR-02 minimal ResearchResult / IC
```

理由：

> 没有真实 Evidence，就没有“现实世界发现”；现有 DSL 尚未贯通 proposal 链时，继续添加
> operator 不会扩大正式研究空间；没有 IC/ICIR，就没有高质量 factor feedback。

---

## 第二优先级

```text
P13 real-Evidence Agent benchmark
P14a Ledger / ResearchContextPack
P14b frozen-family enumeration / duplicate evidence
P14c CampaignSelectionReport
```

理由：

> 这些决定 autonomous research 是真正的科学搜索，还是自动 p-hacking。

---

## 第三优先级

```text
Grammar-bounded Mutation / Crossover
Factor–Model Joint Search
Regime Lifecycle
Second Agent Stack
```

理由：

> 这些可以明显提高最终研究能力，但只有在 factor discovery 本身已经可信之后才有意义。

---

# 37. 结论

最新版本的 `quant-research-os` 已经在工程上肯定回答：

> “冻结且被 formal boundary 接纳的研究，能否由 Agent-facing service 请求并可信执行？”

但 P8-P11 尚未回答 production MCP transport、真实 Agent proposal 质量或真实 Evidence 到
Data-qualified verdict 的组合问题。因此当前系统应定位为 trusted authority foundation，而不是
已经完成的 autonomous research operating system。

接下来真正的问题是：

> **在不破坏现有可信边界的前提下，如何让系统拥有足够强的科研搜索能力？**

对比三个项目后，最合理的演进方向不是把 QuantOS 扩张成一个大而全金融平台，而是形成明确分工：

```text
QuantOS
提供可信性

QuantGPT
提供 Search 思想

RD-Agent
提供 R&D Optimization 思想

Vibe-Trading
提供 Finance Research Tooling 思想
```

从长期来看，QuantOS 最重要的差异化不应该是：

```text
有多少 Agent
支持多少市场
拥有多少数据源
内置多少策略
```

而应该是：

> **任何一个由 Agent 提出的研究结论，都能够回答：它来自什么真实证据、使用了什么形式化假设、搜索过多少候选、是否访问过 OOS、经历了哪些统计校正、使用了什么冻结数据和代码、为什么最终被接受或拒绝。**

如果这一点能够长期保持，同时吸收 QuantGPT 的搜索能力、RD-Agent 的联合优化方法和 Vibe-Trading 的金融研究工具，那么 `quant-research-os` 将不只是另一个“AI 量化 Agent”，而更接近：

> **一个由 Agent 驱动、但由形式化规则和可验证证据统治的自动化量化科研系统。**
