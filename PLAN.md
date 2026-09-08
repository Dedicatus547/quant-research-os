# A 股量化研究 Agent 系统实施计划

> 版本：v11（P11 Quant Research MCP 冻结版）<br>
> 更新日期：2026-09-08<br>
> 当前仓库状态：第一阶段 P0-P7 的 Offline Engineering 与 Data-qualified DoD 均已完成。
> 实现提交 `f3fc7684d09ac351d72d76b2a0370c58bec8589c` 上的两条独立正式流水线均通过：
> Offline Engineering 基线为 `PASS / VALIDATED`；真实 Tushare Data-qualified 发布为工程
> `PASS`，其 ValidationReport 为 `SUCCEEDED / REJECT`、策略状态为 `REJECTED`，唯一未达标的
> 候选软门是年化换手率 `29.5344 > 12`。该 REJECT 是应保留的研究事实，不是工程验收失败。
> 全部报告保留 `SINGLE_SOURCE_NON_VINTAGE`；Rank IC/ICIR 的 immutable ResearchResult adapter
> 仍未实现，不得宣称该指标已被验证。
> P8 Agent Boundary & Threat Hardening、P9 Research Semantic Contracts、P10 GPT + Codex
> Harness Capability Spike 与 P11 Quant Research MCP 已完成；当前下一实施入口为 P12。

---

# 1. 项目目标

构建一个面向 **A 股日频 / 中低频研究** 的自动化量化研究系统。

核心原则：

> **能形式化描述的规则尽可能使用形式化语言描述；LLM / Agent 只处理非形式化信息与形式化 Spec 之间的边界。**

系统职责分工：

- **LLM / Agent** 负责：
  - 阅读非结构化信息
  - 提出研究假设
  - 生成候选因子与实验建议
  - 将自然语言研究思路转换为结构化 Spec
  - 批判候选策略并提出可执行的证伪实验
  - 解释确定性程序产生的结果
- **确定性程序**负责：
  - Tushare 数据采集、快照和来源审计
  - Schema / PIT / Look-ahead 检查
  - 因子计算和 ML 训练
  - Qlib 回测
  - OOS、成本和稳健性检验
  - Validation Gate
  - Artifact / Strategy Registry

任何 LLM 输出都不能直接被视为有效策略。

---

# 2. 关键架构决策

第一阶段采用以下路线：

```text
Canonical Upstream Data     Tushare Pro
Canonical Local Format      Content-addressed Parquet Snapshot
Qlib Runtime View           Qlib dump_bin.py 生成的可重建缓存
Factor / ML Research        Qlib Workflow / qrun / Record Templates
Reference Backtest          Qlib SimulatorExecutor / Exchange
Artifact Store              Local Filesystem + Immutable Manifest
Registry                    Append-only Filesystem Registry
User Entry Point            Deterministic CLI + Python Application Service
Python                      3.11
Environment / Lock          uv + uv.lock
Primary Platform            Linux x86_64
```

本版本删除以下第一阶段依赖：

```text
RQData
RQAlpha Plus
RQFactor
RQOptimizer
任何 RQSDK 许可证或数据包
```

原因：第一阶段必须能由个人用户独立安装和运行，不能依赖当前无法获得的商业个人许可。

## 2.1 Reference Backtest 定位

第一阶段只有 Qlib 一套回测引擎，因此使用：

```text
Reference Backtest
```

而不声称：

```text
Exchange-grade Canonical Backtest
```

Qlib 提供研究级组合模拟、交易成本、涨跌停约束、交易单位和持仓结果，但第一阶段不把它描述为实盘撮合语义的完整替代品。

未来只有在个人可获得、许可证明确且能绑定冻结数据时，才增加第二套独立回测 Adapter。

---

# 3. 当前范围

第一阶段仅包含：

- A 股股票
- 日频 / 周频调仓的中低频策略
- Tushare Pro 数据快照
- 因子研究
- 基础 ML 研究链路验证
- Qlib reference backtest
- PIT / Look-ahead 防护
- OOS / Robustness / Cost Validation
- 文件系统 Artifact Store 和 Strategy Registry
- 为后续 Agent 接入准备稳定 Contracts

第一阶段不包含：

- 实盘交易、券商 API、OMS / EMS、订单路由、Live Risk Engine
- 分钟 / Tick 回测
- 期货、期权、基金、港股、美股、Crypto
- 自研回测引擎或 Agent Runtime
- MCP 或任何 Agent harness / Multi-model Council 的实现
- 财务基本面因子正式接入
- 多数据源交叉验证

---

# 4. 第一阶段成功定义

第一阶段是：

```text
P0 Bootstrap + Feasibility
P1 Foundation Contracts
P2 Tushare Snapshot
P3 Experiment-time PIT Audit
P4 Qlib Research
P5 Qlib Reference Backtest
P6 Validation E2E
P7 Registry + Deterministic MVP Release E2E
```

完成后发布：

```text
Deterministic MVP v0.1
  OFFLINE_ENGINEERING_COMPLETE
  DATA_QUALIFIED（只有真实 Tushare release gates 全部通过后）
```

两个状态分别报告；前者不能被展示成后者。

## 4.1 系统验收与策略验收分离

系统验收成功的含义是：

> 给定合法 Specs 和冻结数据快照，系统能够稳定、可审计、可复现地产生确定性 ValidationReport。

HS300 Momentum 基准即使因收益软门槛未达标而被 `REJECTED`，仍可视为系统工程验收成功。

禁止把以下条件写成工程 Definition of Done：

```text
Sharpe 必须大于某个值
策略必须盈利
基准策略必须进入 VALIDATED
```

---

# 5. 总体架构

```text
Tushare Pro API
      │
      ▼
TushareSnapshotSource
      │
      ├── Request Ledger
      ├── Rate Limiter / Retry
      └── Raw Response Capture
      │
      ▼
Normalizer + Temporal Policy
      │
      ▼
Canonical Parquet Snapshot
      │
      ├──────────────► PIT / Data Quality
      │
      ▼
Derived Qlib View Cache
      │
      ├──────────────► Qlib Workflow / Record Templates
      │
      ▼
SignalArtifact
      │
      ▼
Qlib Reference Backtest
      │
      ▼
OOS / Robustness / Cost / Reproducibility
      │
      ▼
ValidationReport
      │
      ▼
Append-only Registry
```

网络边界：

```text
snapshot build     允许访问 Tushare
snapshot verify    禁止网络
experiment run     禁止网络
validation run     禁止网络
reproducibility    禁止网络
registry           禁止网络
```

研究代码不得直接调用 Tushare API。

---

# 6. 第三方项目定位

| 项目 | 第一阶段定位 |
|---|---|
| Tushare Pro | 唯一 canonical upstream provider |
| Qlib | `dump_bin.py`、表达式执行、`DatasetH`、`LGBModel`、Workflow、Record Templates 与 reference backtest |
| MLflow | 仅由 Qlib 以本地文件后端作为运行记录器 / 调试 UI；不是事实源或 Registry |
| PyArrow / Parquet | Canonical local snapshot |
| Pydantic v2 | Contracts / validation / serialization |
| uv | Python 版本、虚拟环境与依赖锁定 |
| GPT + Codex | v0.2 的单一目标 Agent Stack；P10 capability spike 通过前不进入正式集成 |
| RD-Agent / Vibe-Trading / QuantGPT | Reference implementation / capability donor / future benchmark；不是 v0.2 产品依赖 |
| 上交所 / 深交所官方公告源 | P12 起作为首个 Evidence acquisition 候选；必须独立冻结、审计并与 Evaluation Plane 隔离 |
| AKShare 等开放源 | 未来 discovery only；不得静默替代 canonical market-data source |

长期原则：

> 优先通过 thin adapter 集成成熟能力；只有治理、PIT、provenance、validation 和 registry 属于本项目的核心实现。

---

# 7. 技术栈与环境

## 7.1 Runtime

```text
Linux x86_64
Python 3.11
uv
```

第一阶段只承诺：

> 在相同 OS / 架构、相同 `uv.lock`、相同 runtime fingerprint 下可复现。

不承诺跨 Linux / Windows / macOS 数值完全一致。

## 7.2 主要依赖

```text
pydantic >= 2
pyarrow
pandas
numpy
tushare
pyqlib
lightgbm
ruamel.yaml
typer
tenacity
pyrate-limiter
```

开发依赖：

```text
pytest
pytest-cov
hypothesis
pytest-socket
ruff
pyright
```

具体版本必须由 P0 实测后写入 `uv.lock`，不得只在文档中写宽泛版本后进行 canonical run。

第一阶段不引入 Docker、Nix、数据库、DVC、MinIO、独立工作流平台、单独部署的 MLflow 服务、MLflow Model Registry 或完整 MLOps。Tushare 官方 SDK 是唯一网络客户端；不再增加第二套 HTTP client、通用配置框架或自研限流 / 重试框架。

## 7.3 Build / Thin / Reuse Boundary

| 能力 | 直接复用 | 项目只实现 | v0.1 禁止重复实现 |
|---|---|---|---|
| Tushare 访问 | 官方 `tushare` SDK、`tenacity`、`pyrate-limiter` | endpoint plan、checkpoint、ledger、normalizer | 第二 HTTP client、自研 retry / token bucket、通用 provider framework |
| 配置 | `ruamel.yaml` safe loader | Pydantic validation、duplicate-key rejection | 通用 settings framework |
| Qlib 数据格式 | 官方 `dump_bin.py`、`check_data_health.py` | 输入准备、显式 config、manifest、语义抽样 | `.bin` writer |
| 因子 | Qlib Expression / processors | 安全白名单、配置翻译、availability propagation | 独立因子引擎、生产 momentum calculator、IC 计算器 |
| ML | `DatasetH`、`LGBModel`、Workflow | 一个 locked offline smoke 与稳定结果导出 | trainer、通用模型框架 |
| 研究记录 | `qrun`、`SignalRecord`、`SigAnaRecord`、Qlib local MLflow | required artifact export / normalization | 第二 experiment manager、MLflow Registry |
| 策略与回测 | Qlib Strategy、Exchange、Simulator、Account | Spec / cost translator；必要时最小 `WeightStrategyBase` subclass | matching、order、portfolio accounting engine |
| 结果与风险 | Qlib report / positions / indicators | 稳定 contract、5-6 个算术不变量核对 | 第二套绩效 / 风险计算平台 |
| Artifact | `hashlib`、`json`、`tempfile`、`fsync`、`os.replace` | domain hash 规则、manifest、tamper verification | 对象存储、DVC、数据库 |
| Pipeline / CI | application service、Typer、pytest、`pytest-socket` | 线性 gate orchestration、offline enforcement | Dagster / Prefect / Airflow |

只有出现第二个真实消费者或 provider，并由重复代码证明抽象收益后，才允许提取新的通用层。

P0 实测补充：`pyqlib==0.9.7` wheel 不包含 `scripts/dump_bin.py` 与
`scripts/check_data_health.py`。项目只缓存与已锁定 wheel 同版本、并校验到固定 commit 的
Qlib 官方源码来调用这两个脚本；不得复制、改写或自行维护 converter。源码缓存是工具输入，
不进入 canonical dataset。

---

# 8. 仓库结构

采用单包 `src` layout：

```text
quant-research-os/
├── README.md
├── PLAN.md
├── AGENTS.md
├── pyproject.toml
├── uv.lock
├── .gitignore
├── configs/
│   ├── tushare/snapshot.yaml
│   ├── research/hs300_momentum_v1.yaml
│   ├── validation/engineering_v1.yaml
│   └── validation/research_candidate_v1.yaml
├── src/quantos/
│   ├── contracts/
│   ├── data/tushare/
│   ├── research/qlib/
│   ├── backtest/qlib/
│   ├── validation/
│   ├── artifacts/
│   ├── registry/
│   ├── application/
│   └── cli.py
├── strategies/examples/hs300_momentum_v1/
├── artifacts/.gitkeep
└── tests/
    ├── unit/
    ├── contract/
    ├── integration/
    ├── golden/
    ├── pit/
    └── fixtures/
```

`src/quantos/contracts/` 不得依赖 Tushare、Qlib 或任何 LLM / Agent SDK。

---

# 9. Contracts 与状态模型

## 9.1 第一阶段核心 Contracts

```text
SnapshotBuildSpec
DataSnapshotRef
DataSnapshotManifest
AvailabilityPolicy
DataQualityPolicy
SafeQlibExpressionSpec
ResearchPolicy
ModelSpec
StrategySpec
CostPolicy
ExperimentSpec
ValidationPolicy
SignalArtifactRef
SignalArtifactManifest
ResearchResult
BacktestResult
GateResult
ValidationReport
ExperimentManifest
RegistryEvent
```

第一阶段不设计通用 `EvidenceSpec`；`GateResult` 直接引用 immutable `ArtifactRef`。第二阶段已决定
引入真实公告 Evidence，因此 P9 必须先冻结 Evidence、proposal、admission、campaign 和 ledger
contracts，再允许 P12 Collector 或 P11 Agent integration 依赖它们。

Contract 不在 P1 一次性实现。P1 只冻结基础 hash、时间、snapshot / artifact ref、状态与最小事件原语；P2-P7 在各自 vertical slice 中先冻结所需 public schema，再完成对应集成。v0.1 发布时统一冻结上述 public schemas。

## 9.2 通用规则

所有 Contract：

- 使用 Pydantic v2 和 `extra = forbid`
- 必须包含 `schema_version`
- enum 字段禁止自由 magic strings
- 对象 ID 与 schema version 分离
- 日期与时间必须显式时区
- 禁止 NaN / Inf 进入 canonical JSON
- 支持稳定 serialization、canonical hash 和引用 hash 校验

Canonical hash：

```text
validated value
→ include defaults
→ exclude runtime-only fields
→ normalize enum / UTC datetime / numeric representation
→ sort keys
→ UTF-8 canonical JSON
→ sha256
```

第一阶段的 canonical JSON 是项目内确定性编码，不承诺跨语言标准。实现优先使用标准库 `json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)` 与 `hashlib`，不为此引入额外序列化框架。

`created_at`、`fetched_at`、本地绝对路径、自身 hash 不参与对象内容 hash，但必须记录在外层 manifest。

## 9.3 状态分层

```text
RunStatus:
  SUCCEEDED | FAILED

ValidationVerdict:
  PASS | REJECT | NOT_EVALUATED

StrategyStatus:
  DRAFT | CANDIDATE | VALIDATING | REJECTED | VALIDATED
```

- 网络、依赖或程序异常：`RunStatus.FAILED + ValidationVerdict.NOT_EVALUATED`
- Schema / PIT / reproducibility hard gate 失败：`ValidationVerdict.REJECT`
- 已启用软门槛未达标：`ValidationVerdict.REJECT`
- 前置失败导致后续未运行：后续 Gate 为 `NOT_EVALUATED`
- 只有 `RunStatus.SUCCEEDED + ValidationVerdict.PASS` 才能产生 `VALIDATED` strategy version

稳定 reason code：

```text
SCHEMA_INVALID
SNAPSHOT_HASH_MISMATCH
SOURCE_INCOMPLETE
LOOK_AHEAD
UNKNOWN_AVAILABILITY
QLIB_EXECUTION_FAILED
OOS_POLICY_VIOLATION
REPRODUCIBILITY_MISMATCH
SOFT_THRESHOLD_NOT_MET
ARTIFACT_CORRUPTED
```

---

# 10. 时间语义与 PIT

## 10.1 时间字段

```text
event_time       经济事件或市场数据实际发生时间
known_at         来源声称或系统能够证明该记录已被知道的时间
available_at     本系统允许研究或决策使用该记录的最早时间
observed_at      本系统实际从 Tushare 获取该记录的时间
```

任何 Feature / Signal / Order schedule 必须满足：

```text
source.event_time <= feature.available_at <= signal_time
signal_time <= signal.available_at <= decision_time < execution_time
```

否则 hard reject：`reason_code = LOOK_AHEAD`。

## 10.2 Availability 证据等级

```text
EXPLICIT_SOURCE_TIMESTAMP
DOCUMENTED_UPDATE_SCHEDULE
CONSERVATIVE_DERIVED
OBSERVED_ONLY
UNKNOWN
```

- `UNKNOWN` 不能进入 canonical experiment
- `OBSERVED_ONLY` 只能用于 observed_at 之后的研究
- `CONSERVATIVE_DERIVED` 必须绑定 versioned policy 与理由
- provider 文档中的更新时间不能偷偷转成更早的 available_at

## 10.3 两道 PIT 防线

```text
Snapshot Build-Time Temporal Validation
  - endpoint 字段和 availability policy 可解析
  - 每条记录生成 temporal metadata
  - UNKNOWN hard fail

Experiment-Time PIT Audit
  - snapshot、transform lineage、decision schedule 联合验证
  - 派生 feature / signal 的 available_at 传播
  - 任一违规 hard reject
```

派生数据默认：

```text
derived.available_at = max(input.available_at...) + operator_delay
```

每个受支持 expression / processor 必须声明时间传播规则。

## 10.4 第一阶段 PIT 保证边界

第一阶段能够证明的是：给定本次冻结的 Tushare 历史视图与 versioned conservative policy，实验不会使用该视图中“按本系统规则尚不可用”的记录。它不能证明 2015 年当时的供应商 vintage 与今天查询到的历史记录完全相同，也不能恢复 Tushare 未提供的历史修订版本。

因此每份 ValidationReport 必须明确标注：

```text
single_source = true
historical_vendor_vintage = unavailable
limitation = SINGLE_SOURCE_NON_VINTAGE
```

该限制不能被描述成完整历史 point-in-time 数据保证；未来只有引入可审计历史 vintage 或第二数据源后才能提升证据等级。

---

# 11. Tushare 数据层

## 11.1 定位

Tushare Pro 是第一阶段唯一 canonical upstream provider。

“直接使用 Tushare”指 `TushareSnapshotSource` 可直接通过官方 SDK 采集 API，不指研究、回测或验证过程在线查询 Tushare。正式研究只能读取 immutable local snapshot。

## 11.2 权限前置

根据 2026-08 官方文档：

- 日线、交易日历、复权因子、指数权重等通常至少需要 2000 积分
- 历史每日 ST 列表 `stock_st` 至少需要 3000 积分
- 接口存在每分钟频次、每日总量和单次行数限制

默认前置条件：

```text
Tushare Pro token
全部 required endpoint 的有效权限
建议至少 3000 积分
仅限许可允许的个人研究用途
```

P0 必须用权限探针实测，不能只依据积分数字推断权限。`stock_st` 是 Data-qualified Release 的 required endpoint；权限不足会阻止真实数据发布，但不阻止 synthetic fixture 上的 Offline Engineering DoD。`namechange` 只有在独立验证其历史覆盖与时间语义后才能作为显式替代方案，绝不能静默 fallback。

Token 只能通过 `TUSHARE_TOKEN` 环境变量注入。禁止写入 YAML、日志、manifest、测试快照或 Git。

## 11.3 Required Endpoints

| 数据 | Tushare API | 用途 |
|---|---|---|
| 股票基础信息 | `stock_basic` | 代码、交易所、上市/退市日期 |
| 交易日历 | `trade_cal` | SSE / SZSE 决策日历 |
| A 股未复权日线 | `daily` | raw OHLCV |
| 复权因子 | `adj_factor` | 因子收益与 adjusted view |
| 指数日线 | `index_daily` | HS300 benchmark |
| 指数成分与权重 | `index_weight` | 历史 HS300 universe |
| 每日 ST 列表 | `stock_st` | 历史风险警示状态 |
| 每日停复牌 | `suspend_d` | 可交易性 |
| 每日涨跌停价 | `stk_limit` | 买卖限制 |

第一阶段不接 `dividend`、财务报表、新闻、分钟行情和特色情绪数据。复权研究的必需输入是 `daily + adj_factor`；没有第一阶段消费者的数据不提前采集。

## 11.4 Endpoint-specific Acquisition Source

```python
class TushareSnapshotSource:
    def probe_capabilities(self) -> CapabilityReport: ...
    def execute_plan(self, plan: TushareRequestPlan) -> RequestLedger: ...
```

第一阶段不定义通用 `MarketDataProvider`、`ProviderRequest` 或 `ProviderPage`；在出现第二个真实 provider 前，抽象这些接口只会扩大维护面。`TushareSnapshotSource` 直接使用官方 SDK，并按 endpoint 定义显式 fields、日期分片 / 分页、schema 和主键。

限流复用 `pyrate-limiter`，重试复用 `tenacity`；endpoint-specific quota 在 P0 实测后锁进配置。项目只实现 request plan、checkpoint、响应去重、schema drift 检测、请求审计和 token 脱敏，不自研 token bucket 或 HTTP client。禁止无限重试。

## 11.5 Request Ledger

每次请求至少保存：

```text
endpoint
normalized params
requested fields
request sequence
attempt count
started_at / completed_at
response row count / schema / content hash
tushare package version
rate-limit outcome
```

不保存 token。

## 11.6 Raw 与 Canonical 分层

```text
Tushare API Response
→ Raw Parquet（保留供应商字段、单位和请求追溯）
→ Canonical Parquet（统一 ID、日期、时区、dtype、单位和 temporal metadata）
```

统一约定：

```text
timezone           Asia/Shanghai
instrument_id      600000.SH / 000001.SZ
price unit         CNY / share
volume unit        share
amount unit        CNY
date storage       Arrow date32
timestamp storage  timezone-aware timestamp[us]
```

Tushare 原始 `vol`、`amount` 单位必须显式转换并由 fixture 验证。

Qlib view 使用可逆代码映射：

```text
600000.SH  ↔ SH600000
000001.SZ  ↔ SZ000001
000300.SH  ↔ SH000300
```

映射表必须进入 view manifest，并测试无碰撞、可逆和 benchmark 可解析。

## 11.7 Canonical Snapshot

```text
artifacts/data/snapshots/sha256-<snapshot_hash>/
├── snapshot-build.yaml
├── request-ledger.parquet
├── raw/
├── canonical/
│   ├── instruments.parquet
│   ├── calendar.parquet
│   ├── bars/
│   ├── adjustment_factors/
│   ├── index_membership/
│   ├── benchmark_bars.parquet
│   ├── st_status/
│   ├── suspensions/
│   └── price_limits/
├── quality-report.json
└── manifest.json
```

发布流程：

```text
staging → fetch complete → normalize → quality / temporal validation
→ hash every file → atomic rename to content-addressed path
```

发布后只读。禁止 `latest`、`current`、`auto`、原地追加或原地修正。供应商历史数据修订必须生成新 snapshot 和 revision diff。

Manifest 至少保存 provider、逻辑数据集、日期范围、endpoint contracts、request hashes、fetch window、包与 normalizer 版本、availability policy hash、table schemas、row counts、min/max dates、file hashes、quality report hash 和 snapshot hash。v0.1 的 `snapshot diff` 只比较 manifest、table schema、row count、日期范围与 file hash；完整逐行 diff 不是发布硬依赖。

## 11.8 历史 HS300 Universe Policy

Tushare `index_weight` 提供月度成分和权重快照。Normalizer 必须把每次快照转换成有界 membership interval：

```text
trade_date     = 原始 index_weight.trade_date
available_from = trade_date 后的下一交易时段
effective_from = available_from（本系统可执行区间）
effective_to   = 下一快照 available_from 前一交易时段
```

如果来源没有逐条公告时间，不得假设它在原始 `trade_date` 开盘前已知。第一阶段采用
versioned conservative policy：原始日期保留为事件证据，可执行区间从下一交易时段开始；旧快照
延续到新快照可用前一交易时段，避免“旧快照已失效而新快照尚未知”的空 universe。若快照在
数据窗口结束前尚不可用，则只保留 raw 证据，不进入 canonical 可执行 membership。

禁止：

- 用当前 HS300 成分回填历史
- 把一个月内最后一次快照反向用于月初
- 在缺失月份静默使用无限期 forward-fill
- 把权重日期当作公告时间

缺口超过 policy 允许范围时必须 `SOURCE_INCOMPLETE` hard reject。由于当前快照不是历史 vendor vintage，该 policy 只能提供保守的研究时点约束，不能消除 `SINGLE_SOURCE_NON_VINTAGE` 限制。

---

# 12. Qlib Derived View

Canonical Parquet 是唯一 canonical local dataset；Qlib `.bin` 是可重建 derived view：

```text
Canonical Snapshot
→ 项目生成 Qlib 输入与显式 converter config
→ 调用 Qlib 官方 scripts/dump_bin.py
→ artifacts/data/qlib-views/sha256-<view_hash>/
```

项目不得自行实现 Qlib `.bin` writer。View manifest 保存 source snapshot hash、Qlib / converter version、converter config hash、instrument / calendar / field mapping、adjustment formula、停牌与涨跌停处理、输出 hashes 和 cache integrity hash。

由于 wheel 不携带 converter / health-check scripts，执行前必须通过
`scripts/bootstrap_qlib_tools.py` 获取与 `pyqlib==0.9.7` 对应的官方 `v0.9.7` 源码，并验证
commit `da920b7f954f48ab1bb64117c976710de198373e`。运行期不得从未验证的工作树解析脚本，
converter bootstrap 是唯一允许联网的工具准备步骤之一；实际 snapshot conversion 仍须离线。

实验的业务事实是 `snapshot hash + converter version + converter config hash`；view hash 只是可重建缓存的完整性元数据，不是第二个 canonical 数据源。

## 12.1 复权规则

Canonical snapshot 同时保留 raw OHLCV 与 adj_factor。

```text
adjusted_close_t = raw_close_t * adj_factor_t
momentum_20d_t = adjusted_close_t / adjusted_close_{t-20} - 1
```

该比例不使用“以未来最后一天为锚点”的动态前复权序列。Qlib view 按其约定生成 adjusted OHLCV 和 factor；停牌日行情字段置为 NaN，并保留 tradability 字段。

## 12.2 View 验收

- instrument 数量、calendar 与 snapshot 一致
- 随机抽样 raw → adjusted 计算一致
- 除权日前后收益连续性
- 停牌日为 NaN
- benchmark 可查询
- 历史 HS300 universe 可按日期解析
- Qlib `check_data_health.py` 通过
- 相同锁定 converter / version 重建时 file hashes 一致
- converter 版本变化时不要求 `.bin` byte-exact；改为 snapshot 保持不变、配置与版本留证、语义抽样一致且 Qlib health check 通过

---

# 13. Data Quality Gates

Snapshot 发布前按 risk-behavior coverage matrix 检查，而不是用固定检查数量充当质量指标：

| 风险语义 | 必须覆盖的行为 |
|---|---|
| schema / dtype / primary key | 正常输入通过；漂移、重复键稳定拒绝 |
| 时间与交易日历 | 合法区间通过；越界日期、上市前 / 退市后记录稳定拒绝 |
| 行情数值 | OHLC、volume / amount、pre_close / pct_chg、adj_factor 不变量 |
| universe | 权重容差、成员代码可解析、月份缺口按 policy 拒绝 |
| 稀疏状态表 | ST / 停牌 / 涨跌停按 endpoint 语义验证覆盖，不能套用 bars 的逐行 non-null 规则 |
| 采集完整性 | 重复页、请求遗漏、raw-to-canonical reconciliation |
| 发布完整性 | manifest、row count、日期范围、file hash 与 tamper detection |

每个支持的语义 / failure mode 都必须有 positive case、negative case 和稳定 reason code。required non-null、coverage 与容忍阈值按表配置，并写入 versioned `DataQualityPolicy`。这些 build-time gates 在 P2 完成；P3 不重复实现。

---

# 14. SafeQlibExpressionSpec

`SafeQlibExpressionSpec` 是 Qlib Expression / processor 配置的安全子集，不是独立因子 DSL 或运行时。它使用 Pydantic discriminated union 表达结构化配置，禁止 arbitrary Python。

第一阶段白名单：

```text
field
ref
return
rolling_mean
rolling_std
add / subtract / multiply / divide
rank
```

项目只负责白名单校验、canonical serialization、Qlib 配置翻译与 availability 传播；类型、window、null 和数值执行复用 Qlib。每个受支持 operator 必须记录其 Qlib 映射和时间传播规则，不在项目内再实现一套生产计算器。

`winsorize` 与 cross-sectional `zscore` 不伪装成 Qlib expression operator。只有在锁定对应的
Qlib processor 配置、训练/推理 fit 边界与时间传播规则后才能加入；当前 v1 基准保持未归一化。

禁止：

```yaml
code: |
  arbitrary python
```

## 14.1 基准 SafeQlibExpressionSpec

```yaml
schema_version: qlib-expression/v1
id: momentum_20d
expression:
  type: return
  field: adjusted_close
  window: 20
input_lag_trading_days: 0
```

第一阶段没有稳定的 PIT 行业分类，因此基准不得启用行业中性化；也不得用项目自写数值逻辑
补做 winsorization 或标准化。

---

# 15. ModelSpec 与 LightGBM

LightGBM 第一阶段只保留一个 offline component smoke：

```text
ModelSpec → Qlib DatasetH → native LGBModel
→ Qlib Workflow / qrun → SignalRecord → ResearchResult
```

不实现自有 trainer 或通用 Model Adapter。该 smoke 不进入 HS300 factor 强制 E2E，也不是 Data-qualified Release blocker；其目的仅是证明原生 Qlib ML 链路可用。

必须固定 feature list、label、train / valid / test split、seed、thread count、LightGBM / Qlib version 和 early stopping policy。

forward return label 的 horizon 必须显式锁定；split 边界的 purge 交易日数不得小于 label
horizon，禁止标签跨越分区。当前 component smoke 使用 1 日 forward label，并在两个边界各留出
1 个交易日；发布研究策略仍可采用更保守的 5 日 purge。

---

# 16. SignalArtifact

Factor 和 Model 不直接调用 backtest，统一生成 `SignalArtifact`。

列：

```text
instrument_id
signal_time
decision_time
available_at
score
score_valid
tradable
```

Manifest metadata：

```text
source_expression_or_model_hash
snapshot_hash
qlib_version
qlib_view_spec_hash
qlib_view_hash
qlib_run_id
pit_evidence_hash
resolved_experiment_hash
code_commit_hash
lockfile_hash
```

Manifest 另保存 signal schema、row count、date range、input hashes、transform lineage hash、file hashes 和 signal hash。Qlib / MLflow run ID 只用于追踪执行，不替代导出的 artifact 或内容 hash；这些 metadata 不在每一行 signal 中重复存储。

Backtest 只能消费经过 schema、hash 和 PIT 验证的 SignalArtifact。

---

# 17. StrategySpec 与基准策略

```yaml
schema_version: strategy/v1
id: hs300_momentum
version: 1

universe:
  type: historical_index_membership
  index: 000300.SH

signal:
  type: factor
  ref: momentum_20d

selection:
  method: top_k
  k: 50

rebalance:
  frequency: weekly
  signal_on: week_last_trading_close
  execute_on: next_trading_open
  execution_lag_trading_sessions: 1

weighting:
  method: equal

constraints:
  exclude_st: true
  exclude_suspended: true
  respect_price_limits: true
  trade_unit: 100
  max_weight: 0.03

cost_model:
  ref: cn_equity_research_cost_v1
```

## 17.1 交易语义

- Signal 在每周最后一个交易日收盘数据完备后形成
- 最早在下一个交易日开盘执行
- `input_lag_trading_days = 0` 表示因子使用 signal_time 当日收盘数据；`execution_lag_trading_sessions = 1` 单独负责防止同期开盘执行，二者不得重复 shift
- Universe 使用 decision_time 可知的历史指数成员
- 买入遇涨停、停牌或无开盘价时不成交
- 卖出遇跌停、停牌或无开盘价时不成交
- A 股交易单位为 100 股
- 不允许卖空或杠杆
- 现金余额保留
- 退市、长期停牌和缺失价格产生显式 warning / reason

---

# 18. Qlib Research Workflow Adapter

以 Qlib `Workflow` / `qrun` 为执行入口，复用 `SignalRecord`、`SigAnaRecord` 和适用的 Record Templates。项目只实现薄层：

```python
class QlibResearchService:
    def evaluate_factor(...) -> ResearchResult: ...
    def train_model(...) -> ResearchResult: ...
    def predict(...) -> SignalArtifactRef: ...
```

必须从 Qlib recorder 导出并规范化：

```text
predictions / SignalArtifact
IC / Rank IC / ICIR / Rank ICIR
Qlib 原生提供的 long-short analysis
coverage 与运行 metadata
```

指标由 Qlib 计算，项目不重复实现 IC、Rank IC、long-short 或通用分位数组合引擎。所有启用指标的定义、频率、缺失值规则与 Qlib 版本写入 `ResearchPolicy` 并参与 hash；Qlib 当前版本没有稳定提供的指标不列为 v0.1 强制输出。

Qlib 默认的本地文件 MLflow backend 可用于运行记录与调试 UI，但 required predictions、metrics 和 logs 必须导出到 immutable experiment artifact。Registry 只信任 hashes 与 ValidationReport，不依赖 MLflow 目录长期存在，也不使用 MLflow Model Registry。

P0 锁定的 `MLflow==3.15.2` 默认拒绝创建新的 filesystem store。Qlib 本地 recorder 仅可在
experiment 子进程内显式设置 `MLFLOW_ALLOW_FILE_STORE=true`；该兼容开关不得提升本地目录的
权威性，也不得泄漏到 snapshot、validation 或 registry 进程。删除 runtime store 后，导出的
immutable predictions、metrics 与 manifest 必须仍可独立校验。

---

# 19. Qlib Reference Backtest Adapter

使用：

```text
Qlib SimulatorExecutor
Qlib Exchange
Qlib Account / Position
```

先用 P0 spike 验证 Qlib 内置 `TopkDropoutStrategy` 等 strategy 是否满足“每周全量 top-50 等权、次日开盘执行”。只有确认存在语义缺口时，项目才实现：

```text
WeightStrategyBase 的最小 subclass（只生成目标权重与调仓时点）
StrategySpec translator
Cost policy translator
BacktestResult normalizer
Independent arithmetic reconciler
```

Qlib 继续负责 order、Exchange、Simulator、Account、Position 与成本。项目不得实现 matching engine、exchange simulator、order lifecycle engine 或自有 portfolio accounting engine。

## 19.1 BacktestResult

统一输出：

```text
Qlib report / benchmark returns
portfolio value / cash
positions
indicator / trade history（以当前 Qlib 可稳定导出的字段为准）
turnover / transaction cost / risk metrics
warnings
```

P0 必须检查 Qlib 对 blocked / rejected trade 的可观察证据。如果当前版本不能稳定提供逐单拒绝原因，BacktestResult 记录 known limitation；不得为补齐原因而另造订单系统。

## 19.2 显式配置

不得使用 Qlib 隐式默认值。必须显式设置并记录：

```text
deal price
trade unit
buy / sell cost
minimum commission
limit rule
volume constraint
initial cash
benchmark
frequency
settlement assumptions
```

第一阶段成本模型是研究假设，不声称完整复制券商与历史税费制度。成本压力测试用于衡量敏感性。

## 19.3 Reconciliation

Arithmetic reconciler 只做结果核对，不执行替代回测：

- 每日资产恒等式
- 现金不为非法负值
- 持仓数量符合交易单位
- position × close 与报告市值抽样一致
- return / cost / benchmark 汇总一致
- `signal_time <= available_at <= decision_time < execution_time`

---

# 20. 双层 Experiment Spec 与 OOS 治理

人类/Agent 只能生成不含证据声明的 authoring spec：

```yaml
schema_version: experiment-authoring/v1
experiment_id: hs300-momentum-v1
evaluation_start: 2015-01-01
evaluation_end: 2025-12-31
expression:
  schema_version: expression-authoring/v1
  expression_id: momentum_20d
  operator: return
  field: adjusted_close
  window: 20
strategy:
  schema_version: strategy-authoring/v1
  universe_index: 000300.SH
  selection_method: top_k
  top_k: 50
  weighting_method: equal
  rebalance_frequency: weekly
  execution_mode: next_open
  input_lag_trading_days: 0
  execution_lag_trading_sessions: 1
```

确定性 resolver 才能生成 `resolved-experiment/v1`，并强制绑定：

```text
authoring_spec_hash
snapshot_hash
qlib_view_hash
qlib_view_spec_hash
PIT report hash
validation_policy_hash（engineering_v1 或 research_candidate_v1）
code_commit_hash / lockfile_hash
```

authoring spec 不得携带 caller-supplied temporal lineage、可变别名或 PASS 声明；resolved spec
不得使用 `latest`、`current`、`auto`。工程门与研究收益软门分属两个 versioned policy，策略
收益失败不等于系统工程失败。

规则：

- OOS 不是普通日期标签
- 首次 OOS 前冻结 SafeQlibExpressionSpec、StrategySpec、ModelSpec 和 ValidationPolicy
- 每次 OOS 访问通过 P1 的最小 immutable event writer 写 `OOSAccessed`；P7 Registry 后续导入并索引这些事件
- 看过 OOS 后调整策略必须产生新 version，并记录 contamination warning
- 不得把 OOS 结果反馈到同一版本的参数选择

---

# 21. Validation Pipeline

```text
Execution Preconditions（依赖、输入可读、Qlib 可执行）
 ↓
G0  Schema / Reference Resolution
 ↓
G1  Snapshot Integrity / Data Quality
 ↓
G2  PIT / Lineage Audit
 ↓
G3  Qlib Factor Research
 ↓
G4  Qlib Reference Backtest
 ↓
G5  Out-of-Sample Evaluation
 ↓
G6  Cost Stress
 ↓
G7  Parameter Stability
 ↓
G8  Subperiod Stability
 ↓
G9  Reproducibility
 ↓
G10 Artifact Integrity
 ↓
ValidationReport
```

## 21.1 Hard Gates

```text
Schema / refs
Snapshot integrity
Required data quality
PIT
Reproducibility
Artifact integrity
```

成功执行是进入 validation gates 的前置条件，不是策略 hard-reject gate。有完整证据的 hard gate 失败：`RunStatus = SUCCEEDED + ValidationVerdict = REJECT`。若依赖、程序或 Qlib 执行异常导致证据未产生，则是 `RunStatus = FAILED + ValidationVerdict = NOT_EVALUATED`，不能伪装成策略 REJECT。Agent 无法 override。

## 21.2 Soft Gates

配置化指标：

```text
OOS Sharpe
Rank IC / ICIR
Max Drawdown
Turnover
Annualized Return
Cost Sensitivity
Parameter Stability
Subperiod Stability
```

禁止在代码中写死阈值。必须通过 versioned `ValidationPolicy` 定义，policy hash 进入 ExperimentManifest。

## 21.3 Gate 执行语义

- Hard gate 默认 short-circuit
- 失败前已产生的 evidence 必须保留
- 被跳过 Gate 标记 `NOT_EVALUATED`
- 程序异常与策略被拒绝必须区分
- P7 完成后，rejected 与 failed experiment 都注册留证

---

# 22. Robustness 定义

## 22.1 Cost Stress

```text
1.0x / 1.5x / 2.0x baseline cost
```

## 22.2 Parameter Stability

```text
momentum window: 15 / 20 / 25
top_k:           40 / 50 / 60
rebalance:       weekly only in v0.1
```

禁止只报告最佳参数；必须报告完整 perturbation grid。

## 22.3 Subperiod

```text
2015-2017
2018-2020
2021-2023
2024-2025
```

并验证最少观测数。

## 22.4 Reproducibility

可复现性采用分层成本模型：

- PR CI：synthetic fixture 全链路 double-run
- release baseline：完整 HS300 基准 clean double-run
- 普通 canonical experiment：按需或抽样 rerun，不默认把完整 robustness grid 再执行一遍

比较时固定 Git commit、`uv.lock`、runtime fingerprint、Specs、ValidationPolicy、Snapshot、Qlib converter / config、seeds 和 thread counts，并清空运行 cache。

- Specs、manifests、signals：byte-exact
- 行数、ID、日期、状态：exact
- 浮点 series / metrics：字段级绝对与相对容差
- 排序：canonicalize 后比较
- 运行时间字段：排除在内容比较之外

Canonical experiment 默认拒绝 dirty worktree；开发模式可以运行，但标记 `NON_CANONICAL`。

同一锁定 converter / Qlib 版本可比较 derived-view file hashes；跨 converter 版本只要求 canonical snapshot 不变、版本与配置证据完整、语义样本一致并通过 Qlib data health，不把 `.bin` bytes 当作长期业务契约。

---

# 23. PIT / Look-ahead Regression Suite

测试按支持的 temporal failure modes 建立 coverage matrix；下列场景必须覆盖，但不以固定测试数量作为验收标准：

```text
PIT01 future daily bar
PIT02 same-close signal used at same open
PIT03 future adjustment factor
PIT04 future index membership
PIT05 current HS300 members backfilled into history
PIT06 future ST state
PIT07 future suspension state
PIT08 future price-limit state
PIT09 delisted instrument survivorship
PIT10 revised provider row overwrites old snapshot
PIT11 label crosses train/validation boundary
PIT12 feature lineage loses max available_at
```

每种支持的 temporal semantic 都必须包含合法 positive case、违规 negative case 和稳定 reason code assertion。新增 operator 或数据语义时同步扩展矩阵。

另保留 future financial report、revision leakage、announcement date misuse 的 synthetic contract tests；它们不代表已接入财务数据。

---

# 24. Artifact Storage

第一阶段使用：

```text
Filesystem + Content Hash + Immutable Manifest + Atomic Publish
```

```text
artifacts/experiments/exp-20260831-001/
├── experiment.yaml
├── resolved-specs/
├── snapshot-ref.json
├── qlib-view-cache.json
├── signal/
├── research/
├── backtest/
├── validation.json
├── events/
├── logs/
└── manifest.json
```

ExperimentManifest 至少保存 experiment_id、Git commit / dirty flag、Python / OS / architecture、`uv.lock` hash、dependency versions、所有 Spec / Policy / Snapshot / converter config / Signal / Result / Report hashes、Qlib view cache integrity hash、Qlib run ID、artifact hashes 和 created_at。

Artifact 写入使用标准库 `tempfile` staging、file `fsync`、同文件系统 `os.replace` 与 parent-directory `fsync`，并在读取时重验 hash。

v0.1 threat model 是 trusted single-user / single-writer Linux workspace。保留 atomic publish、tamper detection 与内部生成路径；通用并发写入、恶意 path traversal / symlink escape 的完整对抗测试移到 MCP 暴露前的安全加固阶段。

---

# 25. Strategy Registry

第一版使用最小 append-only filesystem registry。每个事件是 immutable hashed JSON；任何索引都可从事件与 experiment manifests 重建，不引入数据库或通用 event-sourcing framework。

```python
register_experiment()
get_experiment()
list_experiments()
register_strategy()
get_strategy()
get_strategy_versions()
append_strategy_event()
```

策略状态变化通过不可变事件记录：

```text
StrategyCreated
ValidationStarted
ValidationRejected
ValidationPassed
StrategyVersionValidated
OOSAccessed
```

禁止原地修改历史 validated artifact。

必须测试 duplicate hash 幂等、duplicate logical ID 冲突、version 单调递增、合法状态迁移、原子发布、文件篡改、manifest 重验，以及 rejected / failed experiment 留存。v0.1 明确只支持单 writer，不实现并发锁、通用查询语言或数据库事务。

第一阶段不提供 `DEPLOYED` 或 `LIVE`。

---

# 26. Deterministic CLI

```text
quantos doctor
quantos tushare probe
quantos snapshot build --spec <yaml>
quantos snapshot verify <snapshot-id>
quantos snapshot diff <old-id> <new-id>
quantos qlib-view build <snapshot-id>
quantos qlib-view verify <view-id>
quantos factor evaluate --experiment <yaml>
quantos backtest run <signal-path> <view-path> <cost-policy.yaml> <backtest-policy.yaml>
quantos backtest verify <backtest-path>
quantos experiment run <experiment.yaml>
quantos experiment verify <experiment-id>
quantos registry list
quantos registry show <id>
quantos registry verify
```

CLI 只调用 application service，不包含业务逻辑。禁止暴露 shell、arbitrary Python / SQL、修改 Gate、覆盖 Artifact 或 force-pass。

---

# 27. 第一个强制 Release E2E 案例

## HS300 Momentum V1

```text
Universe          历史沪深300成分
Canonical Data    Tushare frozen snapshot
Period            2015-01-01 至 2025-12-31
Factor            20-day adjusted momentum
Input Lag         0（使用 signal day close）
Execution Lag     1 trading session
Signal            weekly last trading close
Execution         next trading open
Selection         top 50
Weight            equal weight
Trade Unit        100 shares
Research          Qlib
Backtest          Qlib SimulatorExecutor
```

```text
Manual YAML
→ Resolve Snapshot + Qlib View
→ Schema / Hash / Data Quality
→ PIT + Lineage Audit
→ Qlib Factor Evaluation
→ SignalArtifact
→ Qlib Reference Backtest
→ OOS / Cost / Parameter / Subperiod
→ Reproducibility
→ ValidationReport
→ Append-only Registry
```

---

# 28. 第一阶段 Definition of Done

P0-P7 同时维护 offline 与 Data-qualified 两条验收轨。里程碑中未特别标注的 exit criteria 默认属于 offline；标注 `[Data-qualified]` 的项目可以因 token / 权限而保持 `BLOCKED`，但不能被跳过或冒充通过。

## 28.1 Offline Engineering DoD

在 `TUSHARE_TOKEN` 未设置、网络与所有 LLM API 禁用、任何 Agent harness 未安装时，使用 synthetic fixture 与人工编写的 `ExperimentSpec` 能完成：

```text
Snapshot / Qlib View Verify
→ PIT Validation
→ Factor Research
→ Signal Generation
→ Qlib Reference Backtest
→ OOS / Robustness
→ Reproducibility Gate
→ ValidationReport
→ Strategy Registry
```

并能由以下输入重现：

```text
Git Commit
+ uv.lock
+ Runtime Fingerprint
+ Specs
+ ValidationPolicy
+ Tushare Snapshot Hash
+ Qlib / Converter Version
+ Converter Config Hash
```

Offline Engineering checklist：

- [x] P0-P7 所有离线 exit criteria 完成
- [x] 无 token CI 等价本地质量门全绿（176 tests；Ruff；Pyright；branch coverage 85.30%）
- [x] DQ 与 PIT coverage matrix 中每个受支持语义均有 positive / negative / stable reason-code case
- [x] synthetic factor Release E2E 完成
- [x] 原生 Qlib `LGBModel + DatasetH + Workflow` offline smoke 完成（独立 component goal）
- [x] 正常、PIT reject、运行失败、软门 reject 四类 golden cases
- [x] P6 synthetic native-Qlib E2E double-run 在容差内一致
- [x] Registry tamper / partial write / duplicate / state-transition tests 完成
- [x] 工程成功不依赖 baseline 策略收益 PASS

## 28.2 Data-qualified Release DoD

真实 Tushare 数据版本发布还必须满足：

- [x] capability probe 证明全部 required endpoints（包括 `stock_st`）可用
- [x] endpoint quota / fields / schema 与许可结果已留证
- [x] 2015-2025 snapshot、quality report 与 derived Qlib view cache 发布并校验
- [x] HS300 Momentum Validation E2E 完成
- [x] release baseline clean double-run 主要内容哈希逐字节一致
- [x] ValidationReport 显式披露 `SINGLE_SOURCE_NON_VINTAGE`

2026-09-06 的 Data-qualified 权威汇总为
`artifacts/releases/data-qualified-v0.1-f3fc768/report.json`。它绑定 snapshot
`6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`、Qlib view
`fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`、SignalArtifact
`dba57f2a5db23c36a58d705ef5be0dbd94df686002c35c9bf3286218788ce51e`、BacktestArtifact
`ec318505caccead33188f909ab445acddc363334c0e96eb25af57ad05cea4270`、ValidationReport
`553d49a710d97d49af536e8950001c5f91c3d88dddce3fa2b29cb8f788d855a7` 和 Registry index
`04a276a2e8c7bd08b6b925b7b81590536269f371534fb0a2115b897215a0396a`。两条 pipeline 各产生
15 个唯一 SignalArtifact/BacktestArtifact，集合完全相同；ValidationReport 字节完全相同，
16 个 robustness cases 为 3 个 cost、9 个 parameter 和 4 个 subperiod case。

Token、积分或接口权限不足只阻止 Data-qualified Release，不阻止 Offline Engineering DoD。不得以 `namechange` 或 synthetic data 静默冒充真实 `stock_st` 证据。

---

# 29. P0 — Bootstrap + Feasibility

## 目标

消除环境、权限和 Qlib 集成风险，建立可重复开发基线。

## 任务

```text
P0-01 初始化 Git repository
P0-02 创建 pyproject.toml 与 src layout
P0-03 固定 Python 3.11
P0-04 使用 uv 创建环境并生成 uv.lock
P0-05 配置 ruff / pyright / pytest / coverage
P0-06 创建 AGENTS.md、README.md、.gitignore
P0-07 建立无 token CI
P0-08 实现 Tushare token 安全加载
P0-09 实现 required endpoint capability probe
P0-10 实测 endpoint quota；锁定 pyrate-limiter / tenacity 配置
P0-11 记录积分、频次、行数、stock_st / namechange 与许可结果
P0-12 做 tiny Tushare official SDK → Parquet spike
P0-13 调用官方 dump_bin.py + check_data_health.py spike
P0-14 做 Qlib Workflow / qrun / Record Templates + local-file MLflow spike
P0-15 比较内置 strategy 与最小 WeightStrategyBase subclass 的语义缺口
P0-16 检查 blocked / rejected trade evidence 的可观察性
P0-17 验证 network-off factor + backtest experiment 可行
```

P0 离线 spike 已确认：官方 converter 两次 clean build 在锁定版本下输出 hash 一致，health
check、expression query、Workflow recorder 与 tiny reference backtest 均可运行。内置
`TopkDropoutStrategy` 不等价于“每周全量 top-50 等权”，P5 已采用最小
`WeightStrategyBase` subclass；当前 Qlib indicator 可提供 requested / dealt amount 与成交率，
但没有稳定的逐单 rejection reason contract，因此只记录 known limitation，不扩建订单引擎。

## 交付物

```text
pyproject.toml / uv.lock
README.md / AGENTS.md / CI config
doctor command / CapabilityReport / feasibility report
tiny synthetic fixture
```

## Exit Criteria

- Python 3.11 clean environment 可 `uv sync --frozen`
- [Data-qualified] required Tushare endpoints 的权限、字段和限制已实测；缺失项明确标为 release blocker
- token 不出现在日志或文件
- synthetic fixture 可在无网络 CI 使用
- Qlib 官方 converter / health check、Workflow records 与 tiny backtest 可用
- 本地 MLflow 目录删除后，导出的 immutable artifacts 仍足以 verify experiment
- [Data-qualified] 未通过的 required endpoint 不得伪造完成，但不阻止 Offline Engineering DoD

---

# 30. P1 — Foundation Contracts

## 目标

只建立所有 vertical slices 共同依赖的最小 contract、时间语义、artifact / event 原语和 CLI 骨架。

## 任务

```text
P1-01 BaseContract / schema version policy
P1-02 canonical serialization / hash
P1-03 temporal types / availability evidence
P1-04 DataSnapshotRef / generic ArtifactRef
P1-05 RunStatus / ValidationVerdict / stable reason codes
P1-06 minimal immutable event envelope + OOSAccessed
P1-07 reference resolution
P1-08 tempfile + fsync + os.replace atomic publish primitives
P1-09 CLI skeleton / application service interfaces
P1-10 public-schema vertical-slice policy
```

## Exit Criteria

- contracts 不 import Tushare / Qlib / LLM SDK
- P1 实现的每个 Contract 有正反 schema tests
- canonical hash 有 golden vectors
- datetime / enum / numeric / defaults / key-order 行为固定
- invalid refs、unknown fields、NaN / Inf 被拒绝
- artifact atomic publish 与 hash verification 通过
- 后续阶段所需业务 contract 不在 P1 提前空实现

---

# 31. P2 — Tushare Snapshot

## 目标

从 required endpoints 构建冻结、可追溯且通过 build-time DQ / temporal gates 的 canonical snapshot，并生成 Qlib derived cache。

## 任务

```text
P2-01 SnapshotBuildSpec / DataSnapshotManifest / DataQualityPolicy
P2-02 endpoint-specific TushareSnapshotSource（官方 SDK）
P2-03 pyrate-limiter / tenacity integration
P2-04 endpoint contracts / explicit fields / capability enforcement
P2-05 resumable request plan / raw capture / request ledger
P2-06 instrument / calendar / OHLCV / adjustment-factor normalizers
P2-07 HS300 membership / benchmark normalizer
P2-08 ST / suspension / price-limit normalizer
P2-09 unit / dtype / timezone normalization
P2-10 endpoint availability policy / build-time temporal validation
P2-11 risk-behavior Data Quality coverage matrix
P2-12 content-addressed snapshot publish
P2-13 manifest-level snapshot diff / revision report
P2-14 official dump_bin.py invocation / view manifest
P2-15 check_data_health.py / semantic sample verification
```

## Exit Criteria

- fixture snapshot 可无网络重建并得到相同 hash
- [Data-qualified] live 请求可中断恢复且不重复发布
- required tables 有显式 schema / primary key
- raw-to-canonical row reconciliation 通过
- revision 产生新 snapshot 而不覆盖旧数据
- DQ / build-time temporal negative cases 稳定拒绝且有 reason code
- Qlib view cache 可从 snapshot + locked converter config 完全重建
- view 与 snapshot 的抽样价格、日历、universe 一致

截至 2026-09-05 的证据：9 个 snapshot required endpoint 均有 provider-shaped
fixture；raw/canonical Parquet、生命周期、两市日历、有界 membership interval、稀疏 ST/停牌、
实际涨跌停边界、raw-to-canonical reconciliation、内容寻址发布和精确文件集验证已闭环。
实时路径已用注入 client 验证 calendar-first planning、逐交易日/逐年分片、`pyrate-limiter`、
`tenacity` 有界重试、checkpoint/resume、跨分片去重、schema drift、脱敏 ledger 和 live-shaped
immutable snapshot publication。Qlib view 绑定干净的固定 commit 与两个官方脚本 SHA-256，
停牌日 OHLCV 为 NaN，并包含 historical-universe/tradability sidecar。真实 bounded probe 已
确认全部 12 个探针 endpoint 可用；账号执行政策按官方已验证档位锁为 200 请求/分钟。live
snapshot 已从 13,614 个全部首尝试成功的 checkpoint 发布并通过 16/16 DQ gates，snapshot
hash 为 `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`，quality report hash
为 `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8`。锁定 Qlib 0.9.7
官方 converter / health check 生成并验真的 derived view hash 为
`fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`。真实响应固定了四项规范
语义：停复牌事件以完整事件键留 raw、canonical 只把 `S` 视为停牌；涨跌停只投影到实际 daily
bar 键，且仅对空 `stk_limit.pre_close` 使用同键 `daily.pre_close`（非空值必须完全一致）；月度
成分从下一交易时段起进入可执行区间；Qlib binary32 语义样本要求与官方 `<f` 存储结果精确
一致。live P2 已完成，并已在 2026-09-06 的 DQ-04 至 DQ-06 正式发布中被再验证。

---

# 32. P3 — Experiment-time PIT Audit

## 目标

在 P2 已发布合格 snapshot 的基础上，证明派生字段、Signal 与交易计划在 decision_time 前可用；不重复实现 build-time Data Quality。

## 任务

```text
P3-01 transform lineage representation
P3-02 SafeQlibExpressionSpec availability propagation
P3-03 experiment-time PIT audit
P3-04 historical HS300 as-of consumption policy
P3-05 adjustment factor causality tests
P3-06 PIT risk-behavior coverage matrix
P3-07 stable reason codes / evidence artifacts
P3-08 SINGLE_SOURCE_NON_VINTAGE limitation propagation
```

## Exit Criteria

- 只消费 P2 中 availability_basis 非 UNKNOWN 的 canonical rows
- future price / member / ST / suspension / limit / adjustment 被拒绝
- feature lineage 丢失时 hard fail
- 每个支持的 temporal semantic 有 positive / negative / stable reason-code case
- PIT reject 产生完整 evidence 且不可 override

截至 2026-09-01 的 Offline Engineering 证据：canonical PIT request 只允许 snapshot hash、
instrument/universe selector、安全表达式、显式 versioned operator delay 和 schedule。审计器先
验证 snapshot 及精确 hash，再从 Parquet 机械解析 field rows、交易窗口和唯一 membership；调用方
不能提供 temporal evidence。伪 hash、缺失窗口、unsupported field、input lag 越界、future/
UNKNOWN input、无 operator policy 和无效 membership 均 hard REJECT。只有
`CANONICAL_SNAPSHOT_BOUND` 报告能发布；`PROPOSAL_UNBOUND` 即使计算结果为 PASS 也不能成为验证
证据。报告始终传播 `SINGLE_SOURCE_NON_VINTAGE`，live snapshot 的 PIT 证据必须在
Data-qualified run 中重新产生。2026-09-06 的正式运行已完成该要求，live PIT
evidence bundle hash 为
`17f3a368d87142dcd877f30c71587991692b19c6ff9acf68753a6cafb282a71f`。

---

# 33. P4 — Qlib Research

## 目标

完成 SafeQlibExpressionSpec → Qlib Workflow → ResearchResult / SignalArtifact，并单独验证原生 LightGBM 组件链路。

## 任务

```text
P4-01 SafeQlibExpressionSpec / ResearchPolicy contracts
P4-02 whitelist validator / Qlib expression-config translator
P4-03 availability propagation adapter
P4-04 historical HS300 universe resolver
P4-05 Qlib Workflow / qrun / SignalRecord / SigAnaRecord
P4-06 required Qlib artifact export / stable result normalization
P4-07 SignalArtifact writer / verifier
P4-08 native LGBModel + DatasetH component smoke
P4-09 split purge / deterministic seed / threads
P4-10 golden expression and model fixtures
```

## Exit Criteria

- SafeQlibExpressionSpec 无 arbitrary Python，项目没有独立因子运行时
- momentum 只在 golden fixture 与独立手算对照，生产值由 Qlib 执行
- SignalArtifact 通过 schema / hash / PIT
- Qlib required records 已导出；删除本地 MLflow runtime 后仍可验证
- 指标定义、Qlib 版本与配置参与 hash
- LightGBM offline smoke 在容差内一致；不作为 HS300 factor release blocker

截至 2026-09-02 的 Offline Engineering 证据：安全 DAG 已机械翻译成可由 Qlib 0.9.7 官方
expression provider 解析和执行的表达式；historical-universe resolver 同时执行 effective 与
available-as-of 约束。每个 cross-section member 都生成精确 request/report 配对的 canonical PIT
evidence bundle。SignalArtifact 使用锁定 Arrow schema，嵌入 resolved experiment、表达式翻译和
PIT evidence，绑定 snapshot/view/view-spec/code/lock/lineage/file hashes，并拒绝 extra file、篡改、
缺行、非有限 score 与 temporal mismatch。真实 Qlib view 上的两个独立 synthetic 构建得到相同
signal content hash `31b8cc11c9b5f86fb62e2f3a6f7984e721a12ae2ffec597fdf4157d69a36b85b`。在
P5 最终 contract 冻结后的干净 synthetic feasibility commit
`272eafb0b175b1f7a6c6f883e8cee68097c2253c` 上，原 P4 fixture 的 SignalArtifact hash 为
`93b565b1e61782909e99dba628ed6386ed5be298cdd0c927fcc86585b8ee8521`，PIT evidence
collection hash 为 `d53388be921ea723f4744091ce859385972b8f145492fa6ad840ba4c14709103`。

原生 `DatasetH + LGBModel + SignalRecord + SigAnaRecord` 使用单线程、固定 seeds、early stopping、
1 日 label 和显式 purge boundary；两次独立运行的 prediction/finite-metrics hashes 分别为
`a57fc7297e6365cf9186c0063c0d4c4f7ca3f643d52a8a6507cc2b49c016739a` 与
`089f93946c959f4984888ba78df2c8966d3a53d5070d78ea0397b40b2cca40c8`。MLflow runtime 删除后导出
仍可验证。以上均是 synthetic Offline Engineering 证据，不会被冒充为 live evidence。
2026-09-06 的正式 Data-qualified 双流水线已从显式 live snapshot 在冻结实现提交上执行，
两次得到相同 SignalArtifact hash
`dba57f2a5db23c36a58d705ef5be0dbd94df686002c35c9bf3286218788ce51e`。

---

# 34. P5 — Qlib Reference Backtest

## 目标

把 StrategySpec 和 P4 已验证的 SignalArtifact 转换成 reference backtest。adapter / normalizer 骨架可与 P4 并行开发，但最终集成以已冻结的 SignalArtifact contract 与 verifier 为前置。

## 任务

```text
P5-01 QlibBacktestService
P5-02 StrategySpec / CostPolicy / BacktestResult contracts
P5-03 reuse built-in strategy or minimal WeightStrategyBase subclass
P5-04 weekly full top-50 equal-weight / next-open schedule
P5-05 ST / suspension / price-limit Exchange config
P5-06 trade unit / cash / no-short / explicit cost translation
P5-07 Qlib report / positions / indicator-history normalizer
P5-08 five-to-six invariant arithmetic reconciler
P5-09 blocked-trade evidence mapping or explicit known limitation
P5-10 tiny golden backtests
```

## Exit Criteria

- 所有 Qlib exchange 参数显式记录
- 非调仓日不产生非预期订单
- `signal_time <= available_at <= decision_time < execution_time`
- 停牌 / 涨跌停 golden cases 行为固定
- 100 股交易单位和最低佣金测试通过
- BacktestResult 可稳定序列化与 hash
- reconciler 无资产恒等式错误

截至 2026-09-03 的 Offline Engineering 证据：`QlibBacktestService` 只负责验证上游
SignalArtifact/view/provenance、把 hash-bound policy 翻译成显式 Qlib 配置、调用 Qlib 并规范化
输出；订单生成、Exchange、Simulator 和 Position/accounting 均由 Qlib 0.9.7 执行。运行配置显式
记录 execution schedule、exchange codes、`OrderGenWOInteract`、`Position`、benchmark、现金、价格、
费用、成交量阈值、涨跌停/ST 字段和 100 股单位。六项 reconciler 会核对资产恒等式、非负现金、
持仓价值/权重、收益/费用/换手增量、PIT schedule，以及无做空、BUY 整手和绑定标的集合；
SELL 清仓保留 Qlib 对公司行为后零股持仓的整仓卖出语义。

专用 `synthetic_backtest_snapshot` 覆盖 2024-01-05 signal、2024-01-08 next-open execution 和
2024-01-09 closeout calendar。`scripts/backtest_feasibility.py` 在干净 synthetic feasibility commit
`272eafb0b175b1f7a6c6f883e8cee68097c2253c` 上完整执行 Snapshot → 官方 converter/health check →
PIT → SignalArtifact → Qlib reference backtest → immutable BacktestArtifact，两次运行得到相同 result
hash `0ef5a3659c4edd7b978348892589b97e71eb7af9468dd9014c4cb0703264673f`；backtest config 和
reconciliation hashes 分别为 `19865770669f1684709e6d5dad3444e6aeb447c26a6d6039d5ef728c9a23dab7`
与 `3f442b1cdc30f87cdbee112d585ecdaee2b49833edd34e8e79e933497792d69e`。tiny artifact 含 1 行
portfolio、1 行 position、1 行 aggregate trade indicator、1 行 order indicator 和 10 行 Qlib risk
metrics，六项 reconciliation 均为零误差。独立 constraint golden backtest 还固定了正常成交、
非调仓日无单、涨停/ST/停牌拦截、100 股整手与最低佣金行为。CLI 已提供显式路径的
`quantos backtest run/verify`；不解析 `latest/current/auto`。以上是 synthetic 工程证据，不是 live
数据或 release provenance。2026-09-06 的正式 Data-qualified 双流水线另行重现了
BacktestArtifact
`ec318505caccead33188f909ab445acddc363334c0e96eb25af57ad05cea4270`、backtest config
`49c804a3a46bf042ad2482ecd82b4179be9f4aa9783c36ed9f190064c2682844` 和 reconciliation
`c01cd819ae4f773e4e441ed57882d05550f55959ea6445e2f897468ec7e540d1`。

---

# 35. P6 — Validation E2E

## 目标

完成 G0-G10、robustness、分层 reproducibility 和 manual YAML 到 ValidationReport 的全链路；本阶段不宣称已经完成 Registry / release E2E。

## 任务

```text
P6-01 deterministic pipeline orchestrator
P6-02 hard gate short-circuit
P6-03 OOS freeze / P1 immutable OOSAccessed event
P6-04 cost stress
P6-05 parameter perturbation
P6-06 subperiod analysis
P6-07 soft threshold evaluation
P6-08 PR double-run / release-baseline rerun / ordinary sampled compare
P6-09 ValidationReport
P6-10 normal PASS golden case
P6-11 strategy REJECT golden case
P6-12 PIT REJECT golden case
P6-13 RunStatus FAILED golden case
P6-14 synthetic Validation E2E
P6-15 HS300 Momentum 2015-2025 Validation E2E（Data-qualified）
```

## Exit Criteria

- manual YAML 可通过一条 CLI 命令执行
- experiment run 全程不访问网络
- 四类 golden outcome 可稳定区分
- 每个 Gate 有 result / severity / reason / evidence
- synthetic PR double-run 在预定义容差内一致
- [Data-qualified] release baseline 完成 clean double-run
- baseline 被软门拒绝时系统验收仍可通过

实施状态（2026-09-03）：offline synthetic 路径已完成。production `experiment run/verify` 从
严格 manual YAML 与显式 hash-addressed runtime locators 生成/校验不可变 ValidationReport；它
只验证已经发布的 evidence grid，不隐式重建上游产物。`scripts/validation_feasibility.py` 是完整
工程验收入口：在临时 clean Git checkout 中执行两套独立的 Snapshot → 官方 converter/health
check → PIT → SignalArtifact → Qlib backtest/robustness grid → G0-G10 → ValidationReport，并要求
主产物 hash 完全一致。ValidationReport v2 额外绑定 Python、OS/kernel、architecture、libc 与关键
数值依赖的 runtime fingerprint。四类 golden outcomes 留在无网络 CI；原生 Qlib runner 作为显式
component gate 运行，不要求 CI 临时下载 Qlib 源码。

Rank IC/ICIR 只在既有 Qlib Workflow component smoke 中留有输出；factor Validation E2E 尚无
immutable ResearchResult adapter，因此请求这两个软指标时会 fail closed。v0.1 的 engineering 与
research-candidate ValidationPolicy 均未启用它们。Rank IC/ICIR adapter 仍是未实现能力，
但不是 v0.1 Data-qualified 政策启用的指标，不能由 synthetic PASS 或其他指标替代。
2026-09-06 的真实数据正式运行已完成该节 P3-P6：
G0-G4、G6-G10 全部 PASS，G5 只因年化换手超过版本化候选阈值而 REJECT，运行状态为
`SUCCEEDED`，全部 16 个 robustness cases 均已评估。

最新 P6 native synthetic component evidence 绑定临时 clean commit
`54ee26fb029f024150cbafa252aa46bc18ef87f7`、runtime fingerprint
`66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321` 与 Qlib source commit
`da920b7f954f48ab1bb64117c976710de198373e`。两条独立 pipeline 的 ValidationReport v2 均为
`28e41a0c4b491990d7647cb22bacaab064a2441328f2bc8f9ce74961e3aeb813`，8 个 robustness cases 和
G0-G10 全部 PASS。仓库只保留 compact hash summary；它是 component evidence，不是 release
checkout provenance 或 Data-qualified evidence。

---

# 36. P7 — Registry + Deterministic MVP Release E2E

## 目标

实现最小不可变实验留证、策略版本和 append-only lifecycle，并完成真正包含 Registry 的 Deterministic MVP Release E2E。

## 任务

```text
P7-01 immutable hashed-JSON event layout
P7-02 rebuildable index + minimal list / get API
P7-03 experiment registration / Qlib run ID linkage
P7-04 strategy logical ID / versioning / lifecycle events
P7-05 import P6 OOSAccessed events / state transition validator
P7-06 single-writer atomic publish
P7-07 manifest re-verification / tamper detection
P7-08 duplicate / idempotence behavior
P7-09 corruption / partial-write recovery
P7-10 synthetic Deterministic MVP Release E2E
P7-11 HS300 Momentum Release E2E（Data-qualified）
```

## Exit Criteria

- rejected 与 failed experiment 同样不可变注册
- 只有 PASS 可生成 VALIDATED version
- 历史状态不得覆写
- duplicate hash 幂等、duplicate ID conflict 可判定
- 索引可从 immutable events / manifests 重建
- 损坏、部分写入和篡改测试通过；v0.1 明确拒绝多 writer
- Offline Engineering 与 Data-qualified Release 各自的最终 E2E 状态可独立报告

实施状态（2026-09-03）：offline synthetic 路径已完成。`RegistryService` 以自哈希
`RegistryExperimentManifest` 和链式 `ImmutableEvent` 为权威，索引每次都从 manifest / event
重建，不保存可变 authority。PASS、REJECT 与 FAILED / NOT_EVALUATED 报告均可登记；策略版本严格
单调，只有绑定同一 strategy spec 的 canonical `SUCCEEDED / PASS` 报告才能从 DRAFT 经
VALIDATING、CANDIDATE 推进至 VALIDATED。重复 hash 幂等，重复逻辑 ID 冲突、非法迁移、event
fork / 缺失前驱、非 canonical JSON、额外文件、manifest / event 篡改均 fail closed。P6 的
`OOSAccessed` 原始 StoredEvent 会保留文件 hash 并导入 experiment event chain；atomic writer
临时文件可显式恢复，权威 JSON 永不被 recovery 修改。v0.1 仍明确为 trusted single-user /
single-writer，不引入数据库或并发锁。

`scripts/release_feasibility.py` 已在临时 clean Git checkout 中执行两套独立真实 Qlib pipeline：
Snapshot → official converter / health check → PIT → SignalArtifact → Qlib reference backtest / grid
→ G0-G10 ValidationReport → Registry。两次 principal artifact、experiment manifest 与 registry
index hash 完全一致，最终策略状态为 VALIDATED。该证据明确标记
`OFFLINE_ENGINEERING / SYNTHETIC_FIXTURE / data_qualified=false`。2026-09-06 又在正式实现提交
`f3fc7684d09ac351d72d76b2a0370c58bec8589c` 上重跑，两条主哈希逐字节一致，最终状态仍为
`PASS / VALIDATED`。同一提交上的真实 Tushare Release E2E 也已完成；Registry 不得把
`SUCCEEDED / REJECT` 提升为 `VALIDATED`，因此真实 HS300 基线被正确保留为 `REJECTED`。

---

# 37. 实施依赖 DAG

取消“所有阶段完全串行”的僵硬约束，改为 dependency gates：

```text
P0
 │
 ▼
P1 Foundation
 │
 ├──────────────────────────┐
 ▼                          ▼
P2 Snapshot + Build DQ    P5 Backtest foundation
 │                          │
 ▼                          │
P3 Experiment PIT           │
 │                          │
 ▼                          │
P4 Qlib Research ───────────┘
 │        （P5 integration 依赖 verified SignalArtifact）
 └──────────────┬───────────┘
                ▼
       P6 Validation E2E
                │
                ▼
P7 Registry + Release E2E
```

里程碑 Gate 仍严格：后续阶段不得声称完成，除非其依赖 exit criteria 已完成。

第二阶段依赖保持单主线，Data-qualified Release 作为独立资格轨道并行：

```text
M0 Offline Engineering baseline freeze
 │
 ▼
P8 Agent boundary / threat hardening
 │
 ▼
P9 Research semantics / campaign governance / minimal DSL v2
 │
 ▼
P10 GPT + Codex capability spike (go / no-go)
 │
 ▼
P11 Quant Research MCP + offline proposal E2E
 │
 ▼
P12 Immutable real-world Evidence acquisition
 │
 ▼
P13 Qualified EventFeatureArtifact + announcement research E2E
 │
 ▼
P14 Research Ledger + bounded autonomous campaign

DQ-01 ... DQ-06 (2026-09-06 COMPLETE) ─┐
                                         └─ P13/P14 的 market-data 资格前置已满足
```

---

# 38. 测试与 CI

## 38.1 无 Token PR CI

```text
ruff format --check
ruff check
pyright
pytest unit
pytest contract
pytest pit
pytest integration --offline
pytest golden --offline
pytest-socket network deny
synthetic E2E double-run
```

Fixtures 必须人工合成、足够小、可提交到 Git、无 token、无在线依赖，并符合 Tushare 数据许可和再分发限制。

## 38.2 持 Token Job

在受保护的个人环境运行：

```text
tushare capability probe
schema drift probe
small live snapshot smoke
full snapshot build on demand
Data-qualified release baseline double-run
```

不得在许可不明确的公共 CI 上传或缓存 Tushare 数据制品。

## 38.3 测试层级

```text
Unit            pure functions / contracts / hashing
Contract        Tushare source and Qlib adapter contracts
Integration     snapshot → qlib view → qlib
PIT             temporal regression
Golden          fixed inputs / fixed normalized outputs
E2E             P6 validation pipeline / P7 release pipeline
```

测试验收看 coverage matrix 是否覆盖受支持的风险语义和 failure modes，不以测试文件或 case 的固定数量为目标。LightGBM native smoke 可作为独立 slow integration job，不拖慢每个 factor E2E。

---

# 39. 风险登记与 Go / No-Go

| 风险 | 影响 | 预防 / Gate |
|---|---|---|
| Tushare 权限不足 | 无法发布真实完整 snapshot | P0 capability probe；required endpoint 缺失只对 Data-qualified Release No-Go |
| 调用额度不足 | 全量构建失败 | request planner、限流、断点续传 |
| 历史数据修订 / 无历史 vintage | 结果漂移且 PIT 证据有限 | observed_at、immutable snapshot、manifest diff、`SINGLE_SOURCE_NON_VINTAGE` |
| 指数成员缺少精确公告时间 | Universe PIT 不确定 | conservative policy、证据等级、必要时 lag |
| 复权因子被历史刷新 | 特征漂移 | raw + factor 同时冻结；ratio 测试；新 snapshot |
| 单数据源错误 | 无法交叉证实 | Report 明示 single-source limitation；未来加第二 provider |
| Qlib 不完全复刻交易制度 | 回测偏差 | reference 定位、显式规则与 known limitations |
| OOS 被反复查看 | 研究过拟合 | campaign freeze、trial accounting、sealed confirmation、access event、后继污染传播 |
| Token 泄露 | 账号风险 | env-only、redaction tests、secret scanning |
| 数据许可限制 | 无法共享/公共 CI | P0 记录条款；fixtures 使用 synthetic data |
| LLM 抽取结果被误当事实 | 错误事件标签进入因子与验证 | 抽取永远是 proposal；必须经 admission policy 形成独立 EventFeatureArtifact |
| 网络内容 prompt injection / 数据外传 | Agent 越权、秘密泄露或 authority 受损 | Collector 与 Agent/Evaluation 进程隔离；Agent 只读冻结 Evidence 且默认无网络 |
| Harness / 模型别名漂移 | Agent provenance 不完整、行为不可比较 | 固定可获得的具体标识和配置；完整 AgentRunManifest；不声称逐字可复现 |
| Ledger 检索结果漂移 | 研究上下文不可审计 | 绑定 ledger snapshot、query/result hash；搜索索引仅为可重建缓存 |
| 自动候选搜索与多重检验 | 漂亮结果来自选择偏差 | 预冻结 ResearchFamily/Budget、完整 trial ledger、一次性 confirmation、multiple-testing policy |

任何 Data-qualified Release No-Go 不允许通过降低测试或伪造 fixture 绕过；Offline Engineering 状态必须单独报告。

---

# 40. 第二阶段路线

第二阶段目标是 **Agent-assisted Research v0.2**，不是自动交易系统。它只在 M0 正式冻结后
开始；Data-qualified Release 作为独立资格轨道并行，不阻塞 Agent 工程，但任何真实市场结论
必须继承其资格状态。Synthetic fixture、真实公告或 Agent proposal 都不能替代 Data-qualified
market-data evidence。截至 2026-09-07，M0、DQ-01 至 DQ-06 与 P8 均已完成；
因此当前下一实施入口是 P9，而不是重跑第一阶段或提前接入 Harness。

后续主线固定为：

```text
M0  Deterministic MVP v0.1 Offline Engineering baseline freeze
P8  Agent Boundary & Threat Hardening
P9  Research Semantic Contracts + Campaign Governance + Minimal DSL v2
P10 GPT + Codex Harness Capability Spike
P11 Quant Research MCP + Codex Skills + Offline Proposal E2E
P12 Real-world Evidence Acquisition
P13 Qualified Event Feature + Announcement Research E2E
P14 Research Ledger + Bounded Autonomous Research MVP
```

`GPT + Codex` 是 v0.2 的范围决策，不是已经证明优于其他 Harness 的事实。P10 仍是严格的
go / no-go capability spike；如果硬性能力不满足，则停止 P11，记录 ADR 和 blocker，不得通过
扩大权限、降低验证要求或静默替换另一套 Harness 继续推进。RD-Agent、Vibe-Trading、QuantGPT
只作为 reference implementation、capability donor 或未来 benchmark。

## 40.1 Authority、网络与文件系统边界

三层信任域必须分离：

```text
Discovery Plane（network enabled）
  deterministic collector → bounded acquisition staging
  无 QuantOS authority 写权限，无 TUSHARE_TOKEN，无 LLM
        │
        ▼
Evidence Publisher（network denied）
  verify exact-file set → publish raw bytes / metadata / content hashes
        │
        ▼
Immutable Evidence Store
  raw source evidence + deterministic derived parser artifacts
        │
        ├──────── Freeze Boundary ────────┐
        ▼                                ▼
Agent Workspace（network denied）     Evaluation Plane（network denied）
  read-only typed refs                  PIT / Qlib / Validation / Registry
  proposal / interpretation only       deterministic authority
```

规则：

- 网络 Collector 只写有界 staging，不调用 LLM，不运行研究、回测或 Validation；network-denied
  Evidence Publisher 重新验证来源 metadata、原始字节和 exact-file set 后才发布 immutable Evidence；
- Agent 默认无网络、无秘密、无 authority filesystem 路径，只通过 typed capability 读取冻结对象；
- Agent 不得直接运行 `quantos` CLI，也不得直接写 snapshot、artifact、event chain 或 Registry；
- MCP server 可以代表 Agent 接收 proposal 或发起受限执行请求，但 authority 写入只能由现有
  deterministic application service 在重新验证全部输入后完成；
- 外部文档是“来源声称的可审计记录”，不是天然正确的事实；QuantOS 维护来源、完整性、资格、
  lineage 和 deterministic verdict，不宣称验证了来源内容的现实真实性；
- `AGENTS.md` 是行为约束，不是安全边界；Sandbox、进程隔离、capability allowlist、root
  confinement 和 domain authorization 才是强制边界。

P12 引入新的网络采集面是明确的第二阶段架构变更。实现前必须有 ADR 固定进程边界、网络
allowlist、用户代理、重试/限流、数据许可、原文保留政策、失败语义和审计格式；不得把它隐藏在
研究或 Evaluation 进程中，也不得破坏“Tushare 只由 market snapshot acquisition 调用”的规则。

## 40.2 MCP Capability Boundary

MCP 只暴露面向领域对象的窄接口，名称在 P9 contract freeze 后最终确定。目标能力为：

```text
Evidence（P12 后）
  evidence.search
  evidence.get

Research（P14 后）
  research.search_ledger

Dataset
  dataset.describe
  dataset.fields

Proposal
  proposal.submit_hypothesis
  proposal.submit_factor
  proposal.submit_experiment

Execution
  experiment.resolve
  experiment.request_execution
  job.get

Validation
  validation.get

Registry
  registry.get
  registry.search
```

接口只能接收 schema-valid logical IDs、content hashes、枚举和有界 payload；不得接收任意本地
路径。每次写请求必须绑定 idempotency key、AgentRun、ResearchCampaign、预算、input hashes，
并产生 append-only audit event 和稳定 reason code。异步执行必须提供有界队列、状态查询、取消、
超时和重复请求语义；`request_execution` 只请求执行，绝不表示 PASS 或 Registry 准入。

禁止暴露：

```text
shell / arbitrary process
arbitrary Python / SQL / Qlib expression text
arbitrary path or filesystem traversal
raw snapshot / artifact / registry write
secret or environment access
validation verdict mutation / force-pass / gate override
direct VALIDATED transition
unbudgeted recursive execution
```

## 40.3 Research semantic contracts 与证据等级

P9 先冻结与 Harness 无关的 contracts。最小对象集合：

```text
EvidenceRecord
ExtractedTextArtifact
ObservationProposal
HypothesisProposal
FactorProposalSpec
ExperimentProposalSpec
ResearchFamilySpec
ResearchBudgetSpec
ResearchCampaignSpec
AgentCapabilityPolicy
AgentRunSpec
AgentRunManifest
EvidenceExtractionProposal
EventFeatureAdmissionRecord
EventFeatureArtifact
InterpretationProposal
ResearchLedgerEvent
ResearchLedgerSnapshot
```

对象权威等级固定为：

```text
raw publisher bytes / metadata  → immutable source evidence
deterministic parsed text       → derived evidence with parser provenance
LLM observation / extraction   → proposal
admitted event feature         → qualified input artifact with admission evidence
Qlib / Validation output       → deterministic experiment evidence
LLM interpretation            → proposal, never a verdict
```

Contract 规则：

- immutable payload 与 lifecycle 分离；`status` 通过 append-only events 和可重建 projection 表达，
  不在不可变 Hypothesis payload 中原地修改；
- Evidence 至少绑定 source locator、publisher、retrieval request/response metadata、raw byte hash、
  media type、encoding、published/fetched/observed/available time、时区、availability policy、
  revision/supersession/retraction、collector/parser version、许可与 limitations；
- `available_at` 只能由冻结 policy 确定，不能由 Agent 自行声明；无法证明时使用保守时间或
  `UNKNOWN_AVAILABILITY`，并按 PIT hard rejection 处理；
- Agent 抽取必须引用原文 EvidenceRef 和页码/字符区间；schema、实体代码和时间可确定性校验，
  但语义正确性必须通过预先冻结的 admission policy；
- EventFeatureArtifact 必须绑定 Evidence、抽取 proposal、admission evidence、实体/交易日 resolver、
  availability policy、代码和 runtime hashes；没有该 artifact，公告标签不得进入因子执行；
- Research Ledger 中的 source assertion、Agent interpretation、human-reviewed statement 和
  deterministic verdict 必须显式区分；语义搜索索引只是可重建缓存，AgentRun 绑定实际 ledger
  snapshot、query 和 result hashes。

`quantos.contracts` 继续保持纯领域依赖，不依赖 Tushare、Qlib、Codex 或任何 LLM SDK。

## 40.4 Safe DSL v2 扩展规则

继续扩展 `SafeQlibExpressionSpec`，绝不允许 Agent 提交 Python 或任意 Qlib expression string。
候选操作符包括：

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

每个操作符必须逐个通过以下 admission gate 后才能进入 public enum：

```text
明确 arity / window / time-series or cross-section 语义
明确 null / non-finite / zero denominator / minimum-period 语义
明确 availability propagation 与 versioned operator delay
使用锁定官方 Qlib 路径实现并有 translation golden tests
在完整 PIT、SignalArtifact、reproducibility E2E 中通过
只引用已在 verified Qlib view / FeatureArtifact 中注册的字段
```

当前带 `window` 的 `rank` 与未来 `cross_section_rank` 不得混为同一语义；`zscore` 也必须区分
时序与截面版本。`correlation`、`zscore` 和截面算子若无法由锁定 Qlib 路径稳定表达，则保持
NOT_IMPLEMENTED / fail-closed。`industry_neutralize`、`size_neutralize` 推迟到 Qlib 官方能力、
输入行业/市值字段、PIT 和缺失值语义全部验证之后，不进入 P9 最小退出条件。

## 40.5 Research campaign、OOS 与自动 p-hacking 治理

每个 research campaign 在第一次执行前冻结：

```text
research question / family
evidence snapshot / ledger snapshot
dataset and feature hashes
development / validation / sealed-confirmation periods
candidate and parameter space
compute / Agent / execution / validation budgets
multiple-testing policy
stopping rule
```

数据访问分层：

```text
development       允许在冻结预算内迭代
validation        只允许预先声明的有限轮次
sealed confirmation  每个 campaign 最多一次
```

所有执行尝试，包括 schema-invalid、PIT reject、execution failed、soft reject 和重复候选，都进入
trial accounting。访问 sealed confirmation 时写入 `OOSAccessed`；访问后 campaign 关闭，基于该
结果生成的任何 next hypothesis 都继承 contamination，不能再声称独立确认。需要新的确认只能使用
事先未暴露的新时间窗/新冻结数据，并创建新的 campaign lineage。

ResearchBudget 只是上限，不是统计修正。P14 前必须选择并冻结适合当前搜索空间的
multiple-testing / selection-bias policy；BH-FDR、Deflated Sharpe Ratio、PBO 等仅在输入假设和
实现验证后采用，不因名字出现就声称风险已经解决。

## 40.6 GPT + Codex Harness 定位与 AgentRun provenance

v0.2 只运行一个 Codex Runtime，通过三个仓库级 Skills 表达逻辑角色：

```text
quant-researcher  → frozen Evidence + optional Ledger（P14 后）→ Observation/Hypothesis proposal
quant-formalizer  → Hypothesis → Factor/Experiment proposal
quant-reviewer    → ValidationReport + history → Interpretation/Next-Hypothesis proposal
```

不实现多进程 Agent、Agent 间 consensus、冲突仲裁或多模型 Council。三个角色共享同一 authority
boundary；Reviewer 不能覆盖 Gate，也不能绕过 40.5 的 sealed-confirmation 规则。

每次 Agent execution 产生 immutable `AgentRunManifest`，至少绑定：

```text
provider-returned model identifier and model configuration
harness / runtime version or build identifier
sandbox / permission / runtime policy hashes
complete instruction / AGENTS.md / skill hashes
MCP tool schema hash
tool request and response hashes
Evidence / Ledger / Campaign input hashes
output proposal / transcript hashes
retry / failure / usage accounting
```

若 provider 不提供不可变模型快照标识，必须记录该 limitation。Manifest 提供可追溯 provenance，
不承诺 LLM 文本或 proposal byte-for-byte 可复现；确定性验收对象始终是同一个 resolved Spec 与
冻结输入产生的 QuantOS artifacts 和 verdict。

## 40.7 M0：Deterministic MVP v0.1 基线冻结

P0-P7 Offline Engineering 基线的固定流程是：

```text
当前改动合入正式 Git commit
→ clean checkout 运行 release_feasibility.py
→ 固化 commit / uv.lock / runtime fingerprint / principal artifact hashes
→ verify registry rebuild and exact-file sets
→ 标记 v0.1.0-oe（或等价 Offline Engineering 基线）
```

M0 不要求真实 Tushare 权限，也不要求策略收益通过。2026-09-06 已在 clean
implementation commit `f3fc7684d09ac351d72d76b2a0370c58bec8589c` 上执行
`scripts/release_feasibility.py`；两条 `OFFLINE_ENGINEERING / SYNTHETIC_FIXTURE` pipeline 主哈希
逐字节一致，ValidationReport 为
`7651525b68c7b865ff49590caeecec6d25a2b3e7f7acb3fc4e7b3190f126c51a`，Registry index 为
`962f41d948a7667e38b127e354bc43a2b0b6273f9d82692cee12cb0a89d5271e`，策略状态为 `VALIDATED`。
这是 M0 的等价 hash-bound 正式基线；是否创建 Git tag 是发布管理选择，不改变该证据状态。

## 40.8 Data-qualified 独立轨道

该轨道可与 P8-P14 工程实施并行，但状态不得被 Offline Engineering、真实公告或 Agent proposal
掩盖：

```text
DQ-01 重新探测全部 required endpoints（尤其 index_weight / stock_st）
DQ-02 固化账号 quota、rate policy 与数据许可
DQ-03 构建不可变 2015-2025 snapshot、DQ report、Qlib view
DQ-04 在正式 clean checkout 重跑 P3-P6
DQ-05 执行 P7 registry / release double-run
DQ-06 显式报告 SUCCEEDED/PASS、SUCCEEDED/REJECT 或 FAILED/NOT_EVALUATED，
      并保留 SINGLE_SOURCE_NON_VINTAGE
```

截至 2026-09-06：DQ-01 至 DQ-06 已全部完成。正式命令在 clean commit
`f3fc7684d09ac351d72d76b2a0370c58bec8589c` 上从显式 snapshot hash 运行两条独立 P3-P7 pipeline；
顶层发布状态为 `PASS / data_qualified=true`，Validation 为 `SUCCEEDED / REJECT`，Registry 策略
状态为 `REJECTED`，限制为 `SINGLE_SOURCE_NON_VINTAGE`。两条 pipeline 的 snapshot、view、
baseline signal、baseline backtest、ValidationReport、experiment manifest 和 registry index 主哈希均一致。

任何 required endpoint 权限不足都是 Data-qualified Release 的 hard blocker；不得静默改用
`namechange`、synthetic data、公告数据或其他未验证来源。P13/P14 可以先取得明确标记的
Offline Engineering E2E，但只有 DQ-01 至 DQ-06 完成后才能发布真实市场研究 verdict。

## 40.9 P8-P14 实施内容与退出条件

| 阶段 | 实施重点 | 退出条件 |
|---|---|---|
| P8 | root-confined 输入、path traversal / symlink escape、恶意/超大/深层 payload、artifact spoofing、secret/OOS 越权、并发 writer、资源预算和审计边界 | 不可信输入不能越过 authority roots、读取 token、覆盖/分叉历史或改变 verdict；安全负例、无 token、现有 P0-P7 regression 全通过 |
| P9 | 冻结 40.3 contracts、campaign/OOS 状态机、stable reason codes、admission policy 接口；按 40.4 gate 实现最小 DSL v2 | Contract/golden/PIT 测试固定 proposal 与 canonical object 的分界；sealed confirmation 和污染传播 fail-closed；未验证 operator 不进入 enum |
| P10 | 对 GPT + Codex 固定当时可获得的具体版本/配置，使用 frozen synthetic task 和人工 proposal baseline 验证 thread、sandbox、MCP、Skills、失败恢复、transcript、usage 和 permission denial | 输出 ADR 与 AgentRunManifest 样例；所有硬性 capability 通过才 Go，任何关键边界失败则 No-Go；不以模型输出质量或盈利替代安全门 |
| P11 | 将 MCP 映射到现有 application services；实现三个 Codex Skills；使用冻结 structured synthetic Evidence 完成 proposal → compiler → Qlib → ValidationReport → Registry/explanation | 相同 resolved Spec 与冻结输入产生相同 deterministic evidence；Agent 文本无需逐字相同；无 shell/path/secret/gate override/direct VALIDATED，幂等、预算、失败语义和负向权限测试通过 |
| P12 | 隔离的 SSE/SZSE 公告 Collector、raw Evidence Store、deterministic text extraction、availability/revision/license policy | 原始字节与派生文本可按 hash 验证和重建；published/fetched/observed/available 不混用；Collector 无 LLM、无 authority 写权；Evaluation 和 Agent 仍无网络 |
| P13 | 冻结公告抽取 benchmark；EvidenceExtractionProposal、admission policy、EventFeatureArtifact、事件到交易日/PIT 对齐；首个股份回购公告研究 vertical slice | 未通过 admission 的 LLM 标签不能执行；feature artifact 可追溯到原文位置与全部 policy/hash；支持的指标才可进入 Gate；分别报告 Offline Engineering 和 Data-qualified 状态，使用正式状态语义而非 ACCEPT |
| P14 | append-only Research Ledger DAG、可重建检索索引、相似/失败/重复研究检索、完整 trial accounting、bounded campaign loop | Ledger 区分来源/提案/人工判断/确定性 verdict；AgentRun 绑定检索输入；预算和停止规则强制执行；sealed confirmation 一次性且污染传播通过 E2E；成功标准不含盈利 |

P8 已于 2026-09-07 完成。冻结实现包括 capability allowlist、有界且不记录正文的请求审计、
最小 Agent 环境、只接受 domain + content hash 的 authority root resolver、规范 logical path、全权威
artifact tree 的 symlink/special-file 拒绝、atomic create-if-absent，以及 Registry 多文件写串行化。
安全负例和完整 P0-P7 regression 均通过。P8 只冻结 pre-integration 边界，不宣称某个 Harness 已经
被沙箱隔离，也不提前冻结 P9 contracts；详细边界与剩余 P10 证明义务见
[`docs/p8-security.md`](docs/p8-security.md)。

P9 已于 2026-09-07 完成。冻结实现包括 Evidence/Proposal/Admission/AgentRun/Ledger contracts、
有限 ResearchFamily 与预算、append-only campaign/OOS 状态机、sealed-confirmation 一次访问与污染
传播，以及只纳入 `abs`、`delta`、`rolling_sum`、`rolling_min`、`rolling_max` 的 Safe Qlib DSL v2。
全部新算子绑定锁定官方 Qlib 语义、完整 PIT window、显式 operator delay、SignalArtifact 与独立输出
hash 重现；未通过 gate 的候选算子不进入 enum。详细冻结边界见
[`docs/p9-research-semantics.md`](docs/p9-research-semantics.md)。

P10 已于 2026-09-07 完成。冻结 `gpt-5.6-sol`、`codex-cli 0.153.4`、medium reasoning、
read-only sandbox、`approval_policy=never`、禁用 login shell、固定最小 shell 环境、单一 read-only
MCP tool、repo Skill、structured output 和人工 proposal baseline。最终真实 JSONL transcript 的
thread、sandbox、MCP、Skills、失败恢复、transcript、usage、permission denial 与 proposal authority
九项硬能力全部通过，决策为 Go；模型标识不可作为 immutable weights snapshot 的限制保持显式。
详细配置、失败恢复过程、哈希和 AgentRunManifest 样例见
[`docs/adr/0001-gpt-codex-harness.md`](docs/adr/0001-gpt-codex-harness.md)。

P11 已于 2026-09-08 完成。三个 repo Skills 均通过结构校验；11 个 MCP capability 被拆分为
3 个 typed proposal ingress 与 8 个 existing-service mapping，不暴露 shell、路径、秘密或 verdict
控制。写请求绑定 idempotency、AgentRun、Campaign、Budget、input hashes 与 append-only audit；
执行队列具备容量、查询、取消、超时、重启和稳定失败语义。clean implementation commit
`06eda7290874e9331ec2b28ef61b34491268cc13` 上的 frozen structured synthetic proposal 经 compiler
进入既有 native-Qlib/Validation/Registry 双管线，两次 resolved Spec、PIT、signal、backtest、
ValidationReport 与 Registry manifest 哈希逐字节一致。最终报告 payload hash 为
`4c920a513705dc0125f4f2d2e4886e6599cb15f91901c700b7ded4dba4c85baf`；解释仍是 proposal，
且 `data_qualified=false`。详细证据见 [`docs/p11-progress.md`](docs/p11-progress.md)。当前下一入口为 P12。

Rank IC/ICIR immutable ResearchResult adapter、第二 canonical market-data provider、基本面因子和
实盘交易不自动进入这条关键路径。若 P13 的批准验收指标需要 Rank IC/ICIR，必须单独完成 adapter
contract、artifact、PIT 和验证测试后才能启用；否则继续 `SOURCE_INCOMPLETE` fail-closed。

---

# 41. AGENTS.md 核心规则

真实 `AGENTS.md` 是仓库执行规则的 authority；本节与当前文件保持同步，PLAN 中其他建议不得
放宽这些规则：

```text
1. Do not implement a custom backtest, exchange, order, or portfolio accounting engine.

2. Tushare may only be called by the snapshot acquisition layer.
   All later stages are offline.

3. Never commit, persist, print, or log TUSHARE_TOKEN.

4. Reuse Qlib dump_bin, data-health checks, Workflow, Record Templates,
   DatasetH, LGBModel, Exchange, and Simulator before adding project code.

5. quantos.contracts must not depend on Tushare, Qlib, an Agent harness,
   or an LLM SDK.

6. No LLM call is allowed in normalization, PIT validation, factor/model
   execution, backtest, or validation gates.

7. Agent output is a proposal, never validated evidence.

8. Canonical runs bind explicit hashes and never use latest, current,
   auto, or mutable data.

9. PIT failure is a hard rejection; execution failure is
   FAILED / NOT_EVALUATED.

10. Qlib .bin is a derived cache. Canonical data is the immutable
    Parquet snapshot.

11. MLflow is a Qlib runtime recorder only. Exported immutable artifacts
    and hashes are authority.

12. Data revisions create new snapshots and never overwrite old snapshots.

13. Profitability is not an engineering acceptance criterion.

14. Rejected and failed experiments remain immutable evidence.

15. Do not claim historical vendor-vintage PIT when the source does not
    provide vintages.
```

---

# 42. 核心工程原则

本项目长期只维护：

```text
1. Minimal Quant Contracts / safe Qlib configuration IR
2. Endpoint-specific Tushare source / Qlib Thin Adapters
3. Snapshot / PIT / Provenance Rules
4. Validation Gates
5. Artifact / Strategy Registry
6. Immutable Evidence records / admission boundary（第二阶段）
7. Research campaign / Ledger governance（第二阶段）
8. MCP Capability Boundary（第二阶段）
```

其他能力尽可能复用：

```text
Canonical upstream data    → Tushare Pro
Data view conversion       → Qlib dump_bin.py / check_data_health.py
Factor / ML                → Qlib Expression / DatasetH / LGBModel / Workflow
Research records           → Qlib SignalRecord / SigAnaRecord
Reference backtest         → Qlib Strategy / Exchange / Simulator
Runtime recorder UI        → Qlib local-file MLflow backend
Agent Harness              → GPT + Codex（P10 go/no-go 通过后）
Other Agent frameworks     → reference / donor / future benchmark
```

项目的核心竞争力不是重新实现数据平台、ML 框架或回测引擎，而是：

> **把研究思想转换为可审计的形式化假设，并用冻结数据和确定性程序严格证伪、验证和重现。**

系统边界必须始终保持：

```text
LLM / Agent
    ↓
Formal Specification
    ↓
Deterministic Verification
```

禁止形成：

```text
Deterministic Core
    ↓
Ask LLM what result should pass
```

---

# 43. 实施依据与官方文档

以下资料在 2026-09-01 核查；P0 必须执行 bounded capability probe，文档不能替代实际账号权限与返回 schema。

Tushare：

- [积分、频次与个人权限](https://tushare.pro/document/1?doc_id=290)
- [数据服务协议](https://tushare.pro/document/1?doc_id=405)
- [Python SDK 与 Token 使用](https://tushare.pro/document/1?doc_id=131)
- [股票基础信息 `stock_basic`](https://tushare.pro/document/1?doc_id=25)
- [交易日历 `trade_cal`](https://tushare.pro/document/2?doc_id=26)
- [A 股日线 `daily`](https://tushare.pro/document/1?doc_id=27)
- [复权因子 `adj_factor`](https://tushare.pro/document/2?doc_id=28)
- [指数权重 `index_weight`](https://tushare.pro/document/2?doc_id=96)
- [每日停复牌 `suspend_d`](https://tushare.pro/document/2?doc_id=214)
- [历史 ST 列表 `stock_st`](https://tushare.pro/document/2?doc_id=397)

Qlib：

- [自有 CSV / Parquet 转换为 Qlib 数据格式](https://github.com/microsoft/qlib/blob/main/docs/component/data.rst)
- [Qlib Workflow Recorder / Record Templates](https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst)
- [Qlib Strategy 与 Backtest](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)
- [Qlib Exchange 参数与交易约束](https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py)
- [Qlib 项目与 RD-Agent 入口](https://github.com/microsoft/qlib/blob/main/README.md)

Agent Harness、模型和官方公告源的具体版本、接口、许可与能力证据由 P10/P12 ADR 固定；本节不以
网页描述代替实际 capability probe、冻结配置或本地验证。

这些链接只用于记录设计依据。Canonical experiment 仍必须绑定实际安装版本、`uv.lock` 和本地输入 hashes。
