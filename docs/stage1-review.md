# quant-research-os Agent 自动化量化研究系统架构评估与演进建议

> 文档定位：这是 2026-09-05 的架构评审快照，保留当时的问题判断和路线建议；
> 它不是当前实施状态或阶段编号的权威来源。当前计划以 [PLAN.md](../PLAN.md) v9 为准，
> 第一阶段证据以 [implementation-status.md](implementation-status.md) 为准。

## 0. 评审意见采纳状态

截至 2026-09-06，评审中对第一阶段确定性内核的判断已经由正式证据确认：P0-P7
Offline Engineering 与 DQ-01 至 DQ-06 均已完成。Data-qualified 工程发布为
`PASS / data_qualified=true`，但真实 HS300 Momentum 候选因年化换手率超过软门槛而保留为
`SUCCEEDED / REJECT`，策略状态为 `REJECTED`。这个结果符合本文对“确定性程序最终裁决”
的要求，不是工程验收失败。

本文的主要后续建议已纳入 PLAN v7，但编号和顺序在后续评审中进一步收敛：

| 评审建议 | PLAN v7 处理 |
|---|---|
| 保留 P0-P7 作为 Research Authority | 已采纳并冻结第一阶段基线 |
| Agent 接入前先收紧 capability / filesystem / secret 边界 | P8，已完成 |
| 补齐 Hypothesis、ResearchFamily、Budget 和 DSL 语义 | P9，已完成 |
| 使用 GPT + Codex，但先执行硬性 go/no-go spike | P10 |
| 只通过 typed MCP / Skills 请求确定性服务 | P11 |
| 将真实 Evidence、首个公告研究和 Ledger/有界自治分步建设 | P12、P13、P14 |

因此，本文第 16-22 节中的 P8-P13 编号只表示当时建议，不应用于下达实施任务；
实施时必须使用当前 PLAN v9 的 P8-P14 编号。

## 1. 背景与目标

`quant-research-os` 的目标不是构建一个由大模型自由生成并执行交易策略的 Agent 系统，而是构建一个可审计、可复现、可证伪的自动化量化研究系统。

核心原则为：

> **能形式化描述的规则尽可能使用形式化语言描述；LLM / Agent 只处理非形式化信息与形式化 Spec 之间的边界。**

这意味着：

- LLM / Agent 负责理解非结构化信息、提出研究假设、形式化研究意图、解释实验结果；
- 确定性程序负责数据、PIT、因子计算、模型执行、回测、Validation Gate、Registry 和最终裁决；
- Agent 输出永远只是 proposal，不能直接构成“有效策略”或“验证结论”。

系统最终目标是形成如下研究闭环：

```text
真实信息
  ↓
Evidence
  ↓
Observation
  ↓
Hypothesis
  ↓
Formal Factor / Strategy / Experiment Spec
  ↓
Deterministic Execution
  ↓
Validation
  ↓
Research Ledger
  ↓
Next Hypothesis
```

第一阶段暂不考虑实盘，只建设自动化研究系统。

---

# 2. 当前项目评估

## 2.1 总体结论

当前 `quant-research-os` 已经很好地完成了整个目标中的**确定性量化研究内核**。

现有 P0-P7 基本构成了：

```text
Immutable Snapshot
→ PIT Validation
→ Safe Expression
→ Qlib Research
→ Qlib Reference Backtest
→ OOS / Robustness / Cost Validation
→ Immutable ValidationReport
→ Append-only Registry
```

项目已经明确要求：

- Canonical 数据使用不可变 Parquet Snapshot；
- Qlib 只作为可重建的研究与回测运行时；
- canonical experiment 必须绑定显式 hash；
- PIT failure 是 hard rejection；
- LLM 不得进入 normalization、PIT、factor execution、backtest 或 validation；
- Agent output 只能是 proposal；
- rejected 和 failed experiment 同样保留为 immutable evidence。

因此，现有 P0-P7 不应重构或由 Agent runtime 替代。

更合理的定位是：

> **`quant-research-os` 已经基本具备 Quant Research OS Kernel，应在其上增加 Agent-assisted Research Layer。**

---

# 3. 已具备的核心能力

当前项目已经具备以下关键基础设施。

| 能力 | 状态 |
|---|---|
| Immutable data snapshot | 已实现 |
| Raw → canonical 数据规范化 | 已实现 |
| 数据质量检查 | 已实现 |
| Temporal semantics | 已实现 |
| PIT / look-ahead 防护 | 已实现 |
| Safe factor expression DAG | 已实现 |
| Qlib expression execution | 已实现 |
| Qlib ML workflow | 已实现 |
| Reference backtest | 已实现 |
| OOS / robustness / cost stress | 已实现 |
| Deterministic Validation Gate | 已实现 |
| Reproducibility Gate | 已实现 |
| Immutable artifacts | 已实现 |
| Append-only Strategy Registry | 已实现 |
| Rejected experiment retention | 已实现 |
| Synthetic / Data-qualified 状态隔离 | 已实现 |

README 已经实现从 Snapshot 到 ValidationReport、Registry 的完整 deterministic pipeline，并严格区分 Offline Engineering evidence 与真实数据 Data-qualified evidence。

因此，后续 Agent 层应被视为：

```text
Research Frontend
```

而现有系统继续作为：

```text
Research Authority
```

---

# 4. 当前系统距离完整目标仍缺什么

现有系统擅长回答：

> “给定一个已经形式化的研究策略，这个策略是否能够在冻结数据上被可信地验证？”

但还不能回答：

> “现实世界中最近出现了什么现象？”

> “哪些现象值得形成研究假设？”

> “过去有没有研究过类似问题？”

> “失败的实验给下一轮研究带来了什么新知识？”

因此当前最主要的缺口位于：

```text
真实世界
→ Formal Spec
```

以及：

```text
Experiment Result
→ Next Research Question
```

具体缺失如下。

## 4.1 Evidence Model

当前尚缺少统一的真实世界证据对象，例如：

```text
公告
财报
新闻
研报
论文
政策
产业事件
```

这些信息应首先转化为 immutable `EvidenceRecord`，而不是直接交给 Agent 生成策略。

---

## 4.2 Observation / Hypothesis Model

需要建立明确的语义链：

```text
Evidence
→ Observation
→ Hypothesis
```

Hypothesis 应明确：

- claim；
- mechanism；
- evidence；
- expected relation；
- confounders；
- falsification conditions。

Agent 的主要职责应是创建这些对象，而不是直接编写策略代码。

---

## 4.3 Research Ledger

当前 Strategy Registry 主要记录：

```text
Experiment
ValidationReport
Strategy lifecycle
```

未来还需要独立的 Research Ledger 保存：

```text
为什么研究
研究依据
历史相关研究
失败原因
替代解释
实验之间的继承关系
下一轮研究问题
```

Registry 和 Ledger 应分工：

```text
Registry
→ 实验事实与验证状态

Research Ledger
→ 科研知识与因果关系
```

所有失败研究都必须进入 Ledger，避免 Agent 不断重复历史上已经失败的思路。

---

# 5. Formal Spec 层需要扩展

现有架构已经具备正确的 DSL 基础。

`SafeQlibExpressionSpec` 采用安全 DAG，支持 field、ref、return、rolling mean/std、算术操作和 rank，并且强制拓扑顺序验证。

这是非常适合 Agent 系统的基础。

但当前 Authoring Spec 的研究空间仍然较窄，主要围绕：

```text
adjusted_close return
+
top-k
+
equal weight
+
weekly rebalance
```

当前 `ExperimentAuthoringSpec` 和 `StrategyAuthoringSpec` 的限制适合 P0-P7 vertical slice，但不足以承担自动研究语言。

下一阶段应继续扩展现有 Safe Expression，而不是允许 Agent 编写 Python。

第一批建议加入：

```text
delta
rolling_sum
rolling_min
rolling_max
correlation
zscore
cross_section_rank
clip
log
abs
```

未来若 Qlib 可以稳定表达，再加入：

```text
industry_neutralize
size_neutralize
```

原则始终保持：

```text
Agent
  ↓
Formal AST
  ↓
Schema validation
  ↓
PIT validation
  ↓
Qlib translation
```

而不是：

```text
Agent
  ↓
Python code
```

---

# 6. 模型不应脱离 Harness 单独接入

第一版不应采用：

```text
QuantOS
→ OpenAI API
→ GPT
```

更合理的抽象是：

```text
Agent Stack
=
Model
+ Harness
+ Instructions
+ Skills
+ Tools
+ Sandbox
+ Permissions
+ Context
+ Memory
+ Runtime Policy
```

模型本身只提供推理能力。

真正决定 Agent 能力和可靠性的还有：

- tool loop；
- context 管理；
- filesystem access；
- sandbox；
- MCP；
- instructions；
- skills；
- session/thread；
- retry；
- tracing；
- runtime lifecycle。

因此未来系统比较的对象也不应只是：

```text
GPT
Kimi
DeepSeek
```

而应该是：

```text
GPT + Codex
Kimi + Kimi Harness
DeepSeek + DeepSeek Harness
```

第一版建议只实现：

```text
GPT + Codex
```

避免一次集成多个 Agent Runtime 导致系统复杂度快速膨胀。

---

# 7. GPT + Codex 在系统中的定位

建议架构如下：

```text
                   GPT Model
                      │
                      ▼
                Codex Harness
                      │
          ┌───────────┼───────────┐
          │           │           │
      Research     Formalize    Review
       Skill         Skill       Skill
          │           │           │
          └───────────┼───────────┘
                      │
               Quant Research API
                      │
════════════════════════════════════════
            Deterministic Boundary
                      │
                      ▼
              quant-research-os
                      │
       ┌──────────────┼──────────────┐
       │              │              │
      PIT            Qlib          Registry
       │              │              │
       └──────────────┼──────────────┘
                      ▼
              ValidationReport
```

Codex 的职责是：

```text
怎么研究
怎么理解信息
怎么生成 Formal Proposal
怎么解释结果
```

QuantOS 的职责是：

```text
什么数据是真的
什么 Spec 是合法的
什么实验允许执行
是否存在 PIT 问题
实验结果是什么
Gate 是否通过
什么状态可以进入 Registry
```

因此：

> Codex 是研究员，QuantOS 是实验室与裁判。

---

# 8. 第一版不需要真正的 Multi-Agent

第一版建议只运行一个 Codex harness，通过不同 Skills 实现逻辑角色。

```text
One Codex Runtime
       │
       ├── quant-researcher
       ├── quant-formalizer
       └── quant-reviewer
```

Researcher：

```text
Evidence + Research Ledger
→ Observation
→ Hypothesis
```

Formalizer：

```text
Hypothesis
→ FactorProposal
→ ExperimentProposal
```

Reviewer：

```text
ValidationReport
+ Historical Research
→ Interpretation
→ Next Hypothesis
```

三者可以是同一个 GPT + Codex runtime 的不同 Skill。

这样可以避免：

```text
多进程 Agent
多模型同步
Agent 对话协议
Consensus
Conflict resolution
```

这些在 MVP 阶段都不是核心问题。

---

# 9. Codex 与 QuantOS 之间必须有 Capability Boundary

当前 PLAN 已经规划了 MCP Research API，并明确禁止 shell、arbitrary Python、SQL、force-pass 和修改 validation verdict。这个方向是正确的。

建议继续强化成严格的 typed capability interface。

例如：

```text
Evidence
---------
evidence.search
evidence.get

Research
--------
research.search_ledger

Dataset
-------
dataset.describe
dataset.fields

Proposal
--------
proposal.submit_hypothesis
proposal.submit_factor
proposal.submit_experiment

Execution
---------
experiment.resolve
experiment.execute

Validation
----------
validation.get

Registry
--------
registry.get
registry.search
```

禁止暴露：

```text
shell
arbitrary Python
arbitrary SQL
arbitrary path
raw artifact write
raw registry write
force pass
gate override
```

Agent 不应该直接运行 `quantos` CLI。

Agent 只应调用受控的 Research API。

---

# 10. Agent 不能直接访问 Authority Filesystem

未来 Codex runtime 应默认采用只读或隔离的 scratch workspace。

不建议直接把：

```text
data/
artifacts/
registry/
```

作为 Agent 可写目录。

Agent 看见的应该是：

```text
EvidenceRef
SnapshotRef
ExperimentRef
ValidationReport
```

而不是：

```text
/mnt/.../artifacts/...
```

安全边界应该由：

```text
Sandbox
+
MCP capability allowlist
+
Filesystem isolation
+
Domain authorization
```

实现。

`AGENTS.md` 可以规定行为原则，但它不能取代真正的权限隔离。

---

# 11. Discovery Plane 与 Evaluation Plane 必须分离

这是实现“自动从真实信息发现规律”最重要的架构新增之一。

现有 QuantOS 正确地要求研究、回测和验证离线执行。

但 Agent 未来又必须访问：

```text
公告
财报
新闻
论文
政策
```

因此不能简单给实验环境开放网络。

应拆成：

```text
                Discovery Plane
                 network enabled
                       │
              Real-world sources
                       │
                       ▼
               Evidence Collector
                       │
                       ▼
             Immutable Evidence
                       │
                 Freeze Boundary
══════════════════════════════════════
                       │
                       ▼
                Evaluation Plane
                  network denied
                       │
                  Hypothesis
                       │
                  FactorSpec
                       │
                ExperimentSpec
                       │
                     Qlib
                       │
                  Validation
```

这样可以同时满足：

```text
Agent 能看到真实世界
```

与：

```text
实验无法偷偷看到未来世界
```

---

# 12. Evidence 应成为一等公民

建议建立：

```yaml
schema_version: evidence-record/v1

evidence_id: EV-...

source:
  type: exchange_announcement
  publisher: SSE

entity_refs:
  - 600519.SH

published_at: ...
fetched_at: ...
available_at: ...

content:
  raw_artifact_hash: ...
  extracted_text_hash: ...

collector:
  version: ...

limitations: []
```

时间字段尤其重要：

```text
published_at
fetched_at
available_at
```

不能混为一个 timestamp。

Evidence 本身也必须：

```text
immutable
content-addressed
auditable
PIT-aware
```

---

# 13. Hypothesis 应成为 Agent 和 QuantOS 的核心接口

Agent 不应该直接生成：

```text
strategy.py
```

而应该产生类似：

```yaml
schema_version: hypothesis/v1

hypothesis_id: HYP-001

claim:
  "回购公告发布后，如果成交量明显增加但价格尚未明显上涨，
   随后20个交易日可能存在正超额收益。"

mechanism:
  "回购信号可能改变市场对公司估值的判断，但价格反应存在延迟。"

evidence_refs:
  - EV-001
  - EV-002

expected_relation:
  direction: positive

confounders:
  - market_cap
  - recent_return
  - industry

falsification:
  - rank_ic <= 0
  - top_bottom_spread <= 0
  - effect disappears after size neutralization

status: PROPOSAL
```

Agent 可以定义：

```text
什么结果能证伪它
```

但 Agent 不能决定：

```text
实验是否已经证伪它
```

后者必须由 deterministic validation 完成。

---

# 14. 自动研究系统最大的风险是自动 p-hacking

Agent 的危险不只是 hallucination。

更危险的是：

```text
提出参数
→ 回测
→ 不好
→ 改参数
→ 再回测
→ 不好
→ 再改
→ ...
→ 最终找到漂亮结果
```

即使每一次回测都是正确的，最终策略仍可能完全是数据挖掘产物。

因此 Agent research campaign 必须先绑定：

```text
ResearchFamilySpec
ResearchBudgetSpec
```

例如：

```yaml
family_id: volume-price-divergence-v1

candidate_budget: 18

allowed_parameters:
  short_window: [5, 10, 20]
  long_window: [40, 60, 120]

max_validation_rounds: 2

test_policy:
  access: final_only
```

这样搜索空间在实验前冻结。

现有项目已经有 `OOSAccessed` event，这是一个很好的基础。

未来还应逐步加入：

```text
trial accounting
factor redundancy
multiple testing
selection bias
```

后续可以进一步研究：

```text
BH-FDR
Deflated Sharpe Ratio
PBO
```

---

# 15. Research Ledger 是系统持续进化的关键

真正的“持续进化”不应该依赖 Agent 自动修改 prompt 或修改自身代码。

更可靠的持续进化来源是：

```text
越来越完整的研究知识
```

Research Ledger 应形成 DAG：

```text
Evidence
   ↓
Observation
   ↓
Hypothesis
   ↓
Factor
   ↓
Experiment
   ↓
Validation
   ↓
Interpretation
   ↓
Next Hypothesis
```

并记录：

```text
成功
失败
重复
无效
被其他因子解释
只在某些 regime 生效
参数不稳定
OOS 失效
```

下一次 Agent 开始研究前，先检索 Ledger：

```text
有没有类似研究？
以前为什么失败？
是不是已有因子的重复？
有哪些 unresolved question？
```

因此系统不是简单地：

```text
不断生成更多策略
```

而是：

```text
不断减少未知空间
```

---

# 16. 建议调整现有 P8-P11 路线

评审时项目的第二阶段路线是：

```text
P8 Pre-MCP Hardening
P9 RD-Agent / Vibe-Trading / QuantGPT Capability Spike
P10 Select One Harness + MCP
P11 Harness Integration
```

评审时的 PLAN 还要求从 RD-Agent、Vibe-Trading、QuantGPT 中选择一个主 harness。

建议调整为：

```text
M0  Deterministic MVP Freeze

P8  Agent Boundary & Threat Hardening

P9  GPT + Codex Harness Capability Spike

P10 Research Semantic Contracts
    + Formal DSL v2

P11 Quant Research MCP API
    + Codex Skills

P12 Real-world Evidence Discovery
    + Research Ledger

P13 Autonomous Research MVP E2E
```

---

# 17. P8 — Agent Boundary & Threat Hardening

目标：

在 Agent 接入前冻结权限边界。

新增：

```text
AgentCapabilityPolicy
AgentRunSpec
AgentRunManifest
ResearchBudgetSpec
```

安全负例包括：

```text
path traversal
symlink escape
malicious proposal
oversized payload
concurrent writer
artifact spoofing
token access
OOS unauthorized access
gate override
```

Agent 永远没有：

```text
WRITE_SNAPSHOT
WRITE_REGISTRY
OVERRIDE_GATE
READ_SECRET
MUTATE_AUTHORITY
```

---

# 18. P9 — GPT + Codex Harness Capability Spike

第一版直接冻结：

```text
Model: GPT
Harness: Codex
```

验证：

```text
thread start/resume
model configuration
sandbox
MCP
AGENTS.md
Skills
failure handling
transcript
usage accounting
```

每次 Agent execution 产生：

```text
AgentRunManifest
```

绑定：

```text
model
harness version
runtime version
instruction hash
skill hashes
MCP schema hash
input evidence hash
output proposal hash
```

因此研究结果未来可以回答：

> 这是哪一个模型 + 哪一个 Codex harness 配置产生的？

---

# 19. P10 — Research Semantic Contracts + DSL v2

新增核心 contracts：

```text
EvidenceRecord
ObservationSpec
HypothesisSpec
FactorProposalSpec
ExperimentProposalSpec
InterpretationArtifact
ResearchFamilySpec
ResearchBudgetSpec
```

同时扩展现有 SafeQlibExpressionSpec。

建立：

```text
Proposal
→ Schema Validation
→ Semantic Validation
→ Dataset Resolution
→ PIT Feasibility
→ ResolvedExperimentSpec
```

所有 canonical Spec 都由 deterministic compiler 生成。

Agent 不得直接创建 canonical validated object。

---

# 20. P11 — Quant Research MCP + Codex Skills

构建受限 Research API。

同时创建三个仓库级 Skill：

```text
quant-researcher
quant-formalizer
quant-reviewer
```

整体流程：

```text
Codex
→ Skill
→ MCP Proposal
→ QuantOS Compiler
→ Experiment
→ ValidationReport
```

MCP 输出必须使用：

```text
typed schema
content hash
idempotency
audit event
stable reason code
```

---

# 21. P12 — Real-world Evidence + Research Ledger

建立 network-enabled Discovery Plane。

第一批真实非结构化数据建议优先选择：

```text
上交所 / 深交所官方公告
```

随后再扩展：

```text
财报
新闻
论文
研报
政策
```

Evidence acquisition 与 Evaluation 完全隔离。

同时建立 Research Ledger，实现：

```text
similar hypothesis search
historical failure retrieval
factor redundancy lookup
unresolved question retrieval
```

---

# 22. P13 — Autonomous Research MVP

第一条完整闭环：

```text
Frozen Evidence
      ↓
Researcher
      ↓
Hypothesis
      ↓
Formalizer
      ↓
FactorProposal
      ↓
Compiler
      ↓
ExperimentSpec
      ↓
PIT
      ↓
Qlib
      ↓
Validation
      ↓
Research Ledger
      ↓
Reviewer
      ↓
Next Hypothesis
```

每一个 autonomous research campaign 都必须冻结：

```text
Research Question
Evidence Snapshot
Candidate Budget
Parameter Space
Compute Budget
Agent Budget
Validation Budget
OOS Policy
Stopping Rule
```

工程成功不要求找到盈利策略。

成功标准仍然是：

```text
Auditable
Reproducible
PIT-safe
Bounded
Fail-closed
```

---

# 23. 第一个真实研究 vertical slice 建议

第一条 Agent E2E 不建议选择宽泛的“新闻选股”。

更适合的是：

> **A 股公司公告事件研究**

第一版甚至只选择：

```text
股份回购公告
```

原因：

- 原始信息是非结构化文本，能够验证 LLM 的真实价值；
- 公告发布时间明确，便于严格 PIT；
- 事件属性容易形式化；
- 后续价格和成交量数据已经是结构化数据；
- 可以形成明确的 falsification；
- 工程验证难度可控。

例如：

```text
回购公告
   ↓
EvidenceRecord
   ↓
Agent 提取事件
   ↓
Hypothesis
   ↓
FactorSpec
   ↓
Qlib
   ↓
OOS / Robustness
   ↓
ACCEPT / REJECT
   ↓
Research Ledger
```

无论结果是否存在 alpha，这条 E2E 本身都能够证明：

> **系统已经能够从真实非结构化信息自动形成可验证的量化研究。**

---

# 24. RD-Agent / Vibe-Trading / QuantGPT 的新定位

这些项目不再作为第一版正式 runtime。

它们应降级为：

```text
Reference Implementation
Capability Donor
Benchmark Agent
```

例如未来可以使用相同 frozen dataset 比较：

```text
GPT + Codex
vs
RD-Agent
```

然后统一通过 QuantOS 验证候选。

比较指标可以包括：

```text
Novel hypothesis rate
Schema-valid rate
PIT-valid rate
Duplicate rate
Validation survival rate
Experiment cost
Token cost
```

这样第三方 Agent 框架不再成为核心系统依赖。

---

# 25. 最终推荐架构

最终系统应形成：

```text
                      Real World
                          │
                  Discovery Plane
                          │
                    Evidence Store
                          │
══════════════════ Freeze Boundary ══════════════════
                          │
                          ▼
                       GPT
                          │
                    Codex Harness
                          │
          ┌───────────────┼───────────────┐
          │               │               │
      Researcher      Formalizer       Reviewer
          │               │               │
          └───────────────┼───────────────┘
                          │
                   Quant Research API
                          │
══════════════ Deterministic Boundary ═══════════════
                          │
                          ▼
                 quant-research-os
                          │
         ┌────────────────┼────────────────┐
         │                │                │
        PIT              Qlib           Ledger
         │                │                │
         └────────────────┼────────────────┘
                          │
                  Validation Gates
                          │
                          ▼
                    Registry
```

三个系统角色应始终保持清晰：

```text
GPT
→ 理解和推理

Codex Harness
→ 组织研究过程、上下文、Skills 和 Tools

QuantOS
→ 维护事实、规则、实验和裁决
```

---

# 26. 核心结论

当前 `quant-research-os` 不需要重新设计。

它已经较好完成了整个系统中最应该确定化的部分：

```text
Data
PIT
Formal Expression
Qlib
Backtest
Validation
Reproducibility
Registry
```

下一阶段应重点建设：

```text
Evidence
Hypothesis
Research Ledger
Formalization Boundary
Codex Harness
MCP Capability Boundary
Autonomous Research Loop
```

第一版 Agent Stack 推荐固定为：

```text
GPT + Codex
```

而不是直接接入裸模型，也不是同时集成多个 Agent Framework。

系统长期应坚持以下原则：

> **Agent 可以提出研究，但不能定义事实；可以设计实验，但不能决定实验结论；可以解释结果，但不能修改 Validation Verdict。**

最终 `quant-research-os` 应成为一个：

> **以不可变真实数据和 Evidence 为事实基础，以 Formal Spec 为研究语言，以 GPT + Codex 为智能研究前端，以 Qlib 和确定性程序为实验执行器，以 Validation Gate 为裁判，以 Research Ledger 为长期知识记忆的自动化量化科研系统。**
