# P14 入口复核与后续实施建议

Review date: 2026-09-11

## 1. 核验结论

当前项目总体处于 **P14 入口已批准、P14a-P14c 尚未开工** 的状态；P0-P13、FR-01/FR-02 的证据链齐全，测试与类型检查通过。对 `857aa1b` 基线的核验发现一个**会阻断 CI 的问题**：`ruff format --check` 失败。该格式问题已在本次后续修复的工作树中解决，尚待提交后改变 HEAD 状态。

| 检查项 | 结果 |
|---|---|
| Git 基线 | `main` = `857aa1b`，与 `origin/main` 同步；核验结论针对该 HEAD，本评审草稿本身不属于该基线 |
| Python / 锁文件 | Python 3.11.15；`uv lock --check` 通过（228 packages） |
| `quantos doctor` | `offline_status=READY`；Data-qualified 因无 `TUSHARE_TOKEN` 为 `BLOCKED_TOKEN_MISSING`，符合预期 |
| Ruff check | 通过 |
| Pyright | 0 errors / 0 warnings |
| Pytest | **312 passed**，28.69s；覆盖率 **85.04%**，刚高于 `fail_under=85` |
| Ruff format check | **失败，11 个文件需要格式化** |
| CI workflow | `.github/workflows/ci.yml` 包含 `uv run ruff format --check`，因此当前 HEAD 按 CI 配置会失败 |

需要格式化的文件：

```text
scripts/p13_event_signal_feasibility.py
scripts/p13_evidence_mcp_server.py
src/quantos/application/__init__.py
src/quantos/application/proposals.py
src/quantos/contracts/research.py
src/quantos/contracts/research_result.py
src/quantos/research/qlib/result.py
tests/integration/test_research_result_adapter.py
tests/unit/test_data_qualified_release.py
tests/unit/test_proposal_compiler.py
tests/unit/test_research_result.py
```

建议先执行 `uv run ruff format .` 并单独提交一个 `style:` 修复；在修复前，当前 HEAD 无法通过配置的 CI 门禁。

本次后续修复已完成 11 个文件的纯格式化，并重新通过：

- `uv lock --check`：228 packages；
- `quantos doctor`：`offline_status=READY`，`data_qualified_status=BLOCKED_TOKEN_MISSING`；
- `ruff format --check`、`ruff check`、Pyright；
- Pytest：312 passed，覆盖率 85.04%。

## 2. 阶段与证据状态

- P0-P7：Offline Engineering 与 Data-qualified DoD 均完成，M0 hash-bound 基线已冻结。
- P8-P11：Agent 边界、研究语义契约、Codex 能力 spike、typed MCP 离线提案 E2E 完成。
- P12：真实公告 Evidence Store 完成，SZSE 权限仍为 `UNKNOWN`。
- P13 v2：冻结实现 `46904c22...`，真实 Agent proposal、deterministic admission、双根离线执行全部 `SUCCEEDED / PASS`；本地在 `artifacts/qualification/p13-v2-replay-1/` 可核验。
- FR-01：已 admitted DSL 已贯通 proposal → compiler → resolution → PIT → Signal → Backtest → Validation。
- FR-02：immutable Qlib `ResearchResult` adapter 已通过，Qlib 原生 IC/Rank IC 已有资格化证据。
- `docs/reviews/p14-entry-review.md`：**GO for P14a-P14c**；P14d bounded autonomous loop 仍被阻塞。
- `README.md` 已指向 current P14 boundary 和 P14 entry review，无需为阶段状态额外修改。

## 3. P14a-P14c 关键缺口

### P14a — Ledger persistence / index / ContextPack

已有基础：

- `contracts/ledger.py`：`ResearchLedgerEvent`、`ResearchLedgerSnapshot` 及 authority 校验。
- `artifacts/store.py`：`atomic_write_bytes`、`publish_directory`、`exclusive_directory_lock`、`regular_tree_files` 等可复用原语。
- `AgentCapability.RESEARCH_SEARCH_LEDGER` 枚举已存在。

缺口/风险：

1. `contracts/ledger.py` 明确写着 “persistence and search arrive in P14”，目前没有 service、store、rebuild、verify。
2. 没有 `ResearchLedgerSearch*`、`ResearchContextPack`、context budget、retrieval policy 等契约。
3. `AgentCapability.RESEARCH_SEARCH_LEDGER` 未加入 `research_mcp_policy`，也未在 `ResearchMcpService` 中 dispatch，Agent 目前搜不了 ledger。
4. `ResearchLedgerEvent` 只有 `object_hash`，没有媒体类型、来源域或对象解析绑定；仅靠 hash 无法从零重建索引/ContextPack。
5. `DETERMINISTIC_VERDICT` 目前只能绑定 `VALIDATION_REPORT`，无法表达 P14c 的 `CampaignSelectionReport` verdict，建议在 P14a 一并完成 schema revision，而不是 persist 完成后再改。
6. `AgentRunManifest` 没有显式 `context_pack_hash`；至少应把 context pack hash 纳入 `input_hashes`/`input_artifact_hashes`。
7. ContextPack 必须绑定当前 campaign、ledger snapshot、检索策略和 contamination policy。允许检索 snapshot 内获授权的跨 campaign 历史（例如既往失败和相似因子），但必须拒绝当前 campaign 未获授权的 sealed 结果，并保留父子 campaign 的 contamination lineage。

### P14b — frozen-family enumeration / duplicate evidence

已有基础：`ResearchFamilySpec`、`ParameterDimension`、`ResearchBudgetSpec`、`CampaignTrial`、`ResearchCampaignGovernor.authorize_factor`。

缺口/风险：

1. `ResearchFamilySpec` 只有 `factor_template_hash`，仓库里**没有对应的 FactorTemplate 契约**，无法确定性 enumerate；这是 P14b 的第一阻塞。
2. P14 入口冻结限制要求“one named dimension per explicit template slot”；目前没有显式 named-dimension 映射，多 window family 不能靠推断。
3. 没有 `ResearchSearchPolicySpec`（枚举顺序、failure handling、stopping rule、duplicate policy、tie-breaker）。
4. 没有 canonical AST fingerprint；`SafeQlibExpressionSpec.content_hash` 绑定 node_id，无法直接做跨提案结构去重。
5. 没有 `CandidateManifest`/`DuplicateEvidence` artifact；`CampaignTrial.candidate_hash` 目前可以是任意 hash，缺少与候选集合的 membership 校验。
6. 当前没有独立的 candidate disposition 来表达“因预算未运行”等非试验终态。不能直接把未运行候选加入 `CampaignTrial`：现有 governor 会把每个 trial 计入 `max_trials`，从而扭曲预算。P14c 应由 candidate manifest 与 selection report 共同证明完整 denominator。

建议 P14b 产出：

- `ResearchFactorTemplateSpec` + 显式参数槽位；
- `ResearchSearchPolicySpec`；
- `ResearchCandidateSpec` / `CandidateEnumerationManifest`；
- 纯函数 enumerator + canonical AST fingerprint + duplicate evidence；
- 保留 trial ledger 记录实际尝试；另设 candidate-level disposition，使每个 manifest candidate 都有确定终态而不把未运行候选计作 trial；
- 严禁 mutation/crossover，P14d 之前只做 frozen-family 枚举。

### P14c — CampaignSelectionReport / selection-bias policy

已有基础：Rank IC/ICIR 的 immutable ResearchResult；`MultipleTestingPolicy.PREFROZEN_FINITE_FAMILY` 目前只是“空间有限”的标记。

缺口/风险：

1. 没有 method、alpha、版本、seed、block length、assumptions 等冻结字段；当前 campaign 只绑定一个 enum。
2. 没有 `CampaignSelectionReport` 契约、service、verify、CLI、golden/E2E。
3. 没有 pre-OOS selection freeze 机制。若直接 OOS 后再选，sealed confirmation 失去独立性；建议在 `OOSAccessed` 之前新增 `SelectionFrozen` 事件，或强制 sealed trial 绑定 selection report hash。
4. 没有完整 denominator 规则：candidate manifest 必须覆盖 family 声明候选数；trial ledger 覆盖实际尝试中的 schema-invalid、PIT reject、execution failed 和 duplicate；selection report 再覆盖全部候选及未运行原因。
5. P14c 依赖的 `research/qlib/result.py`（78%）、`application/campaigns.py`（75%）当前测试覆盖偏低，选到坏分支的风险高。
6. Rank IC/ICIR 已资格化；coverage/turnover/autocorrelation 未资格化，不能拿来做 selection 依据。

## 4. 建议实施顺序与产出

### 第 0 步：先让 CI 变绿

```bash
uv run ruff format .
uv run ruff format --check
uv run ruff check
uv run pyright
env -u TUSHARE_TOKEN uv run pytest --cov=quantos --cov-report=term
```

`.github/workflows/ci.yml` 已包含 `ruff format --check`，它是当前权威 CI 门禁。暂不机械提高 `fail_under=85`；P14 新模块应随实现增加分支和负向测试，先提高实际覆盖率并留出余量，再通过独立决策调整门槛。

### P14a 实施建议

1. 先冻结 `research-ledger-event/v2`：
   - 增加 `CAMPAIGN_SELECTION_REPORT`、必要时的 `CAMPAIGN_TRIAL`/`RESEARCH_RESULT` node kind；
   - 泛化 verdict 绑定，使 campaign-level verdict 也走 `DETERMINISTIC_VERDICT`；
   - 为 object 增加可验证 binding（media type、source domain 或内部 object store）。
2. 新增 `contracts`：
   - `ResearchLedgerObjectRef`
   - `ResearchLedgerSearchRequest/Response/Index`
   - `ResearchContextPack`、`ContextSection`、`ContextBudgetPolicy`
3. 新增 `application/ledger.py`：
   - append-idempotent chain service，确定性 `uuid5` event id，调用方显式提供事件时间；
   - rebuild/project/snapshot/verify；
   - deterministic lexical + structural index，v1 不建议 embedding；
   - context pack builder：固定 tokenizer/config、item limits、序列化字节上限、tie-breaker、overflow fail-closed。
4. 新增 `research.search_ledger` MCP mapping：只读、有界，绑定 campaign、ledger snapshot、retrieval policy、授权域与 contamination filter，并返回 query/result hashes。跨 campaign 历史只有在上述绑定允许时才能进入结果。
5. CLI 增加 `quantos ledger` 组：`verify`、`context-pack`、`search` 等。

### P14b 实施建议

1. 新增 FactorTemplate/枚举/去重 contracts。
2. 纯函数 enumerator：
   - 维度按名称排序、参数按 canonical bytes 排序；
   - 生成数严格等于 `declared_candidate_count`，不一致直接失败；
   - candidate id = hash(family hash + template hash + canonical params + canonical expression fingerprint)。
3. canonical AST fingerprint：
   - 归一化 node id，保留拓扑与 operator 参数；
   - v1 不做 commutative reorder，避免改变数值语义；
   - 输出 exact/structural duplicate groups。
4. `ResearchCampaignGovernor.authorize_factor` 增强为 candidate manifest membership 校验，而不仅是 allowed operators/parameter space 子集。
5. Trial accounting 与 candidate accounting 分层：
   - trial ledger 只记录实际尝试，包含重复、schema invalid、PIT reject、execution failed、PASS、soft/hard reject；
   - candidate manifest/selection report 为全部候选记录 terminal disposition，包括 `NOT_RUN_BUDGET` 等未运行原因；
   - selection report 校验 manifest candidate、trial 和 disposition 的一一覆盖关系，未运行候选不消耗 `max_trials`。

### P14c 实施建议

建议先完成统计方法资格化，再冻结 v1。`Holm + block bootstrap` 可作为首个候选方案，但当前描述不足以直接成为权威默认值：

- **primary statistic**：必须在 mean Rank IC、Rank ICIR 或明确的 studentized statistic 中冻结一个；Rank IC series 是输入序列，不与统计量混称；
- **candidate correction**：若采用 `HOLM_BLOCK_BOOTSTRAP_V1`，必须冻结零假设构造（包括必要的中心化）、block 类型、block-length 规则、重采样次数、seed、Monte Carlo p-value、极值/并列处理及适用假设，再用 Holm step-down；
- **fail closed**：候选集不完整、样本不足、缺失/非有限值、输入损坏或统计流程无法执行 → `NOT_EVALUATED`；只有完整且有效地执行冻结选择流程、但没有候选通过时才是 `NO_SELECTION`；
- 暂不采用 BH-FDR、Deflated Sharpe、PBO，除非先单独冻结输入假设并做 golden/negative tests；
- redundancy：exact + structural 由 P14b 给出；empirical signal correlation 必须绑定共同 universe、日期区间、coverage 和缺失值策略后才能进入报告。

建议新增：

```text
MultipleTestingPolicySpec
SelectionPolicySpec
CampaignTrialEvidenceBinding
CampaignSelectionReport
```

并新增 `application/campaign_selection.py`、`quantos campaign selection-report/verify`、独立双根 E2E runner。报告需包含：

- campaign/family/budget/candidate-manifest/trial-event 全部 hash；
- 完整 denominator 和每个候选的 disposition；
- 校正方法、版本、assumptions、alpha、seed；
- adjusted p-values、redundancy clusters、tie-breaker；
- `SELECTED / NO_SELECTION / NOT_EVALUATED`；
- pre-OOS selection binding；sealed confirmation 之后再做最终 `CONFIRMED / REJECTED`。

## 5. 最重要的风险与建议决策

| 决策点 | 建议 |
|---|---|
| P14c 统计方法 | 先资格化并冻结统计量、零假设与重采样细节；Holm + block bootstrap 仅作为首个候选，未通过 golden/negative/E2E 前不赋予权威 |
| Selection 时点 | `OOSAccessed` 前必须冻结选中的 candidate；新增 `SelectionFrozen` 事件最清晰 |
| Ledger object 解析 | 不要只存 `object_hash`；补充 object binding 或内部 content-addressed object store |
| 检索方式 | v1 用确定性 lexical + structural，不上 LLM/embedding；否则必须冻结 model/tokenizer/config |
| Ledger schema | 在 P14a 一次改成 v2；否则 P14c 的 CampaignSelectionReport 无法进入 ledger verdict |
| Token budget | 若没有冻结 tokenizer，改用 `max_items + max_serialized_bytes`，不要声称 token 级可复现 |

## 6. 下一步行动清单

1. 已完成 `uv run ruff format .`，并通过与 CI 一致的 format、lint、类型和测试门禁；提交前 HEAD 仍保持原基线状态。
2. 保持 README 当前 P14 boundary 表述；无需重复更新阶段状态。
3. 先补 `contracts/ledger.py`、`contracts/campaign.py`、`application/campaigns.py` 的负向测试，提高实际覆盖率；暂不机械提高覆盖率门槛。
4. 冻结 P14a ledger v2 与 ContextPack 契约，实现 append/rebuild/search index/context pack，并加授权范围、contamination、MCP、double-root/reproducibility 测试。
5. 再做 P14b 的 template/enumerator/fingerprint，以及相互分离的 trial accounting 与 candidate disposition。
6. P14c 先资格化统计方法和失败语义，再实现 multiple-testing policy + CampaignSelectionReport；完成前不要开放 P14d。
