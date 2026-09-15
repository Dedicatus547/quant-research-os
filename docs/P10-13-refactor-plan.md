# QuantOS P10/P13：Codex Python SDK 重构实施计划

> 版本：v2
> 日期：2026-09-14
> 状态：Implemented through M3 with offline coverage; M5 qualification is NO_GO (2026-09-15)
> 适用仓库：`Dedicatus547/quant-research-os`
> 目标范围：P10/P13 Agent harness integration
> 新增资格门：`FR-03 — Official Codex Python SDK Qualification`

## 1. 决策摘要

QuantOS 将把新的 canonical local Agent runtime 从 `codex exec --json` 迁移到官方
`openai-codex` Python SDK，但不得改变 Agent authority model。

目标状态：

```text
QuantOS application orchestration
              │
              ▼
       LocalAgentHarness port
              │
              ▼
 quantos.integrations.codex
              │
              ▼
       isolated SDK host
              │
              ▼
 openai-codex → local Codex app-server → allowlisted MCP
```

本项目尚未发布，因此本次采用破坏性重构：

- 新运行只支持 SDK，不保留可执行的 CLI backend 或 backend selector；
- 新运行直接使用 `AgentRunManifestV2` 和新的规范化事件格式；
- 旧 P10/P13 artifact、hash 和 v1 schema 保持不可变；
- 只保留最小只读 legacy decoder/verifier，不提供新的 CLI execution path；
- 不要求重新运行 CLI，也不建立长期 CLI/SDK 双栈。

FR-03 通过之前，SDK 不得成为 canonical runtime。M0 未证明的 SDK 能力不得进入稳定架构。

## 2. 已知事实与待验证假设

官方 OpenAI 文档当前明确说明：

- Python package 为 `openai-codex`；
- Python SDK 控制本地 Codex app-server；
- published SDK build 携带 pinned Codex CLI runtime dependency；
- 提供同步/异步 client、thread start/run 和 sandbox presets；
- `Sandbox.read_only` 禁止文件写入。

来源：[OpenAI Codex SDK](https://developers.openai.com/codex/sdk/)。

以下内容一律视为 M0 待验证能力，而不是本计划的既定事实：

- exact SDK/runtime version 的机械读取方式；
- app-server child environment 的完整控制方式；
- auth state 与 runtime config state 的隔离方式；
- 忽略用户 config、global MCP、plugins 和 experimental features 的方式；
- shell tool 完全关闭和 login shell 禁止；
- MCP enabled-tools/required 语义及实际可见工具集合；
- structured output 支持范围；
- SDK event 是否暴露 evaluator 所需的完整 command、MCP、message、usage 和 error 信息；
- timeout、interrupt、close 后进程树的终止语义；
- error taxonomy、retry hint 和 quota/overload 可观测性。

若任一安全关键能力无法机械证明，FR-03 必须 `NO_GO`；不得用 limitation 代替权限隔离。

## 3. 不变的 authority boundary

本次只替换 Agent runtime integration，不替换 QuantOS 的权威路径：

```text
Agent Proposal
      ↓
Schema → Admission → PIT → Qlib → Validation
      ↓
Campaign Selection → Registry / Research Ledger
```

SDK、app-server 和 Agent 均不得：

- 修改 `ValidationReport` 或 gate verdict；
- 修改 immutable snapshot 或既有 artifact；
- 直接注册 `VALIDATED`；
- 获取或输出 `TUSHARE_TOKEN` / `TUSHARE_*`；
- 绕过 typed application services；
- 获取 authority filesystem write；
- 为 P13 获取 shell 或网络能力；
- 直接运行任意 backtest；
- 成为 Research Ledger source of truth。

Agent 输出始终只是 proposal，绝不是 validated evidence。

## 4. 范围与非目标

本次实现：

- SDK feasibility qualification；
- transport-neutral local harness port；
- isolated SDK host；
- SDK adapter 和 provider-event normalizer；
- `AgentRunManifestV2`、attempt model 和可离线重放的规范化 transcript；
- P10 capability evaluator 迁移；
- P13 extraction runner 迁移；
- SDK-only P10/P13 qualification；
- v1 historical artifact 的只读验证。

本次不实现：

- P14 autonomous loop；
- persistent research thread、resume、fork、steer 或 subagents；
- Agents API、cloud sandbox 或其他模型 provider；
- automatic model routing 或 login；
- Research Ledger redesign。

Port 只服务已验证的 local Codex runtime。不得为了假想的未来 provider 提前设计最低公分母接口。

## 5. 包边界

```text
quantos.contracts
    AgentRunManifestV2 / HarnessAttemptRecord / canonical event contracts
    不 import openai_codex、Qlib、Tushare、Agent harness 或 LLM SDK

quantos.application
    LocalAgentHarness port
    P10/P13 request construction、evaluation、publication、replay orchestration
    不 import openai_codex，不解析 provider event

quantos.integrations.codex
    SDK host、SDK adapter、provider-event normalizer、legacy v1 verifier
    唯一允许 import openai_codex 的区域
```

建议目录：

```text
src/quantos/
├── contracts/
│   ├── agent.py
│   └── harness.py
├── application/
│   ├── agent_harness.py
│   ├── harness_spike.py
│   ├── harness_runner.py
│   └── p13_agent_runner.py
└── integrations/codex/
    ├── sdk_adapter.py
    ├── sdk_host.py
    ├── event_normalizer.py
    └── legacy_v1.py
```

## 6. Harness port

Application 层定义同步 port；SDK 的同步/异步差异不得泄漏给 P10/P13：

```python
class LocalAgentHarness(Protocol):
    def execute(self, request: HarnessExecutionRequest) -> HarnessExecutionResult: ...
```

`HarnessExecutionRequest` 至少绑定：

- resolved working directory 和 frozen input hashes；
- prompt bytes/hash；
- exact model identifier 和 reasoning effort；
- complete `RuntimePolicy`；
- exact MCP server definitions、tool allowlist 和 schema hashes；
- output schema bytes/hash；
- timeout、token 和 transcript limits。

`RuntimePolicy` 必须区分并完整表达：

```text
host process environment
app-server environment
shell environment
MCP child environment
config home / user-config isolation
sandbox mode
approval policy
shell feature policy
login-shell policy
network policy
filesystem roots
history persistence
```

环境策略必须是 exact allowlist + exact values + `inherit=none`，不能只记录变量名。
所有 policy 都必须 canonicalize 并进入 request/manifest hash。

不可变 request 不得持有可变 `Mapping`。schema/config 使用 canonical bytes 或深度不可变的
canonical contract。

## 7. SDK host 与进程隔离

canonical run 默认通过独立 `sdk_host` 进程运行 SDK，不采用同进程 SDK 作为首选路径：

```text
QuantOS parent
    │ bounded request + sanitized environment
    ▼
python -m quantos.integrations.codex.sdk_host
    │
    ▼
openai_codex → app-server → MCP children
```

原因：

- 不修改全局 `os.environ`；
- 精确控制 runtime 和 MCP 的继承环境；
- timeout 时可以终止并回收完整进程树；
- 限制 SDK/app-server 崩溃对主进程的影响；
- 为 host protocol 设置独立的 byte/time bounds。

host protocol 只传输 QuantOS-owned request/result envelope，不复制 Codex CLI JSONL protocol。
host 不得接受任意 command、任意环境变量或任意 writable root。

认证仅允许复用 operator 预先建立的 session。QuantOS 不自动打开浏览器、不触发 device login、
不读取/复制/持久化 credential。若 auth 与 isolated config 无法同时满足，FR-03 失败。

## 8. Run contracts V2 与 attempt model

新 canonical run 使用 `agent-run-spec/v2` 和 `agent-run-manifest/v2`。v1 contracts 保持冻结，
不得修改字段语义，也不要把 SDK 信息编码进一个自由格式字符串。

`AgentRunSpecV2` 在现有输入绑定之外，增加完整 requested runtime policy hash、transcript policy hash
和 attempt/retry budget hash；它不包含 provider 或 SDK object。

V2 至少包含：

```text
run_spec_hash
provider_thread_id
provider_model_identifier
model_snapshot_immutable=false

adapter_identity
sdk_distribution/version
bundled_runtime_identity/version
provider_protocol_identity
normalizer_identity/version/hash

requested_policy_hash
effective_policy_hash
sandbox_policy_hash
permission_policy_hash

attempts
aggregate_usage
interactions
input/output hashes
normalized_transcript_hash
provider_transcript_hash or explicit non-retention reason

run_status
terminal_error
limitations
timestamps
```

每次 provider invocation 建模为独立 `HarnessAttemptRecord`：

```text
attempt_index
thread_id
started_at / completed_at
event_stream_hash
usage
terminal_error
produced_proposal_hash or null
```

规则：

- attempt 顺序连续且不可删除；
- 失败 attempt 仍是不可变证据；
- 最多一个 attempt 可以产生 proposal；
- 只有最后一个成功 attempt 的 proposal 能进入 admission；
- aggregate usage 必须等于所有 attempt usage 之和；
- retry count 从 attempt 数推导，不复用含义不清的旧字段。

v1 contracts 和 decoder 保持冻结，只用于历史 artifact 验证。

## 9. 规范化 transcript

新增 `quantos-agent-event/v1`，但不得只保存 payload hash。每条事件必须包含重建 evaluator
输入所需的完整、有界 canonical payload，或引用同时持久化的 content-addressed payload blob。

最小事件集合：

```text
ATTEMPT_STARTED / ATTEMPT_COMPLETED / ATTEMPT_FAILED
THREAD_STARTED
TURN_STARTED / TURN_COMPLETED / TURN_FAILED
COMMAND_STARTED / COMMAND_COMPLETED / COMMAND_FAILED
TOOL_STARTED / TOOL_COMPLETED / TOOL_FAILED
APPROVAL_REQUESTED
AGENT_MESSAGE
USAGE
HARNESS_ERROR
```

事件 envelope 至少包含：

```json
{
  "schema_version": "quantos-agent-event/v1",
  "attempt": 1,
  "sequence": 1,
  "kind": "TOOL_COMPLETED",
  "provider_event_type": "...",
  "payload": {},
  "payload_hash": "..."
}
```

规范：

- sequence 在每个 attempt 内连续；
- payload 使用 QuantOS canonical JSON；
- command 事件保留命令、bounded output、exit status 和 denial classification；
- tool 事件保留 server/tool、arguments、result/error 和 status；
- message 事件保留用于 proposal validation 的完整 bounded message；
- usage 保留 provider 实际提供的字段，不用 `0` 伪造缺失数据；
- observation timestamp 可单独保留，但不得成为语义 payload hash 的不稳定输入；
- unknown provider event 默认 fail closed，不能静默丢弃 authority-relevant 内容。

FR-03 qualification 应保留原始 provider event stream，以便审计 normalizer。若流中检测到 credential、
`TUSHARE_*` value 或其他禁止内容，不持久化泄漏内容，只记录内存计算的 hash 和稳定失败原因，
并使资格运行失败。普通运行是否保留 provider stream 由独立 retention policy 决定。

Canonical replay 只依赖规范化 transcript、content-addressed payload 和版本化 normalizer contract，
不依赖安装中的 SDK Python object。

## 10. 错误、retry 与 timeout

内部稳定错误分类至少包括：

```text
AUTH_UNAVAILABLE
CONFIGURATION_INVALID
RUNTIME_MISMATCH
TRANSPORT_START_FAILED
TRANSPORT_CLOSED
QUOTA_EXHAUSTED
OVERLOADED
TIMEOUT
INTERRUPTED
PERMISSION_DENIED
OUTPUT_INVALID
MCP_FAILED
PROTOCOL_UNSUPPORTED
UNKNOWN
```

这些类型必须显式映射到版本化 QuantOS `ReasonCode`；不得把所有 SDK exception 压成
`HARNESS_EXECUTION_FAILED`。

仅 `OVERLOADED` 和已证明为 transient 的 startup failure 可以自动 retry。retry policy 必须包含
最大 attempt 数、总 wall-clock budget 和 backoff 上限，并进入 policy hash。schema、config、permission、
sandbox、MCP、proposal validation 和未知错误不得 retry。

timeout 是 QuantOS-owned hard deadline：

1. 请求 SDK/app-server 终止 active turn；
2. 在短暂 bounded grace period 内等待；
3. 终止整个 host process group 和所有 MCP children；
4. 验证无子进程存活；
5. 持久化失败 attempt，禁止产生 proposal authority。

仅调用 `close()` 而不验证进程树退出，不算 timeout qualification PASS。

## 11. P10 evaluator

P10 的九项 hard capability rubric 保持不变：

```text
THREAD
SANDBOX
MCP
SKILLS
FAILURE_RECOVERY
TRANSCRIPT
USAGE
PERMISSION_DENIAL
PROPOSAL_BOUNDARY
```

现有 evaluator 改为只接受规范化 `HarnessCapture`。它不得 import SDK、调用 subprocess 或解析
provider event。

SDK qualification 使用现有 frozen fixture、task、AGENTS.md、Skill、MCP、manual baseline、model、
reasoning effort 和 limits。判定要求仍为 `9/9 → GO`。

不比较历史 CLI 与 SDK 的 raw transcript、文字、thread ID 或 token 数。历史 CLI P10 report 是基线
证据，不需要重新运行。SDK 必须独立满足相同 rubric。

## 12. P13 runner

目标流程：

```text
load frozen P13 inputs
        ↓
build AgentRunSpecV2 + HarnessExecutionRequest
        ↓
LocalAgentHarness.execute()
        ↓
normalized HarnessCapture
        ↓
deterministic proposal validation
        ↓
EvidenceExtractionDraft / Proposal
        ↓
Admission → PIT → Qlib qualification
```

SDK run 必须继续满足：

- command count = 0；
- approval request count = 0；
- shell disabled，而不只是 filesystem read-only；
- Agent network disabled；
- 实际可见 MCP tools 严格等于 `evidence_get`、`evidence_cite`；
- successful MCP sequence 精确为 `get, cite, cite`；
- Store/evidence/extracted-text hash 精确匹配；
- draft schema、limitations 和 citation objects 精确匹配；
- proposal authority 为 `AGENT_PROPOSAL`；
- deterministic admission 和 PIT 均 PASS。

不要求新 proposal content hash 等于历史 CLI proposal，但不得放宽任何下游 gate。

## 13. Artifact layout

新运行使用显式 v2 layout，不通过“哪个文件存在”猜测格式：

```text
agent-run-manifest.json
agent-run-spec.json
harness-runtime.json
agent-events.jsonl
agent-event-payloads/          # 仅在 payload 外置时存在
provider-events.jsonl          # qualification 必须；普通运行按 retention policy
output-schema.json
tool-schema.json
task.md
extraction-draft.json          # 成功时
extraction-proposal.json       # 成功时
```

loader 先读取 manifest 的 `schema_version` 决定 verifier：

```text
agent-run-manifest/v1 → frozen legacy verifier
agent-run-manifest/v2 → normalized transcript verifier
other                 → fail closed
```

不得根据文件名猜格式，也不得将 SDK 结果冒充 v1 CLI artifact。

## 14. 实施阶段

### M0 — SDK feasibility qualification

在临时、非 canonical spike 中 exact-pin 一个 SDK release，实测第 2 节全部待验证项。输出一个
human-reviewable capability matrix 和原始诊断证据，但不得改动 P10/P13 authority artifacts。

Exit：

- SDK/runtime identity 可机械记录；
- auth/config 隔离可同时满足；
- exact environment、sandbox、shell、network 和 MCP surface 可机械证明；
- evaluator 所需事件完整可得；
- structured output、usage、error 和 timeout 可观测；
- 进程树可可靠回收。

任一项失败即暂停重构；不要用 CLI wrapper 模拟缺失的 SDK protocol capability。

### M1 — 冻结 v2 contracts

实现并冻结：

- `AgentRunSpecV2`；
- `AgentRunManifestV2`；
- `HarnessAttemptRecord`；
- `AgentEventV1` 和 payload contracts；
- runtime/policy identity；
- stable error/ReasonCode mapping。

同时加入 canonicalization、negative validation 和 hash tests。

### M2 — 抽取 application port

用 M0 实测结果定义 `LocalAgentHarness`、request/result 和 `HarnessCapture`。把 P10/P13 evaluator
改成 transport-neutral，但暂不切换 canonical runner。

### M3 — 实现 isolated SDK integration

新增 SDK host、adapter、event normalizer、timeout/process-tree 管理和 immutable publication。
`openai-codex` 作为 exact-pinned optional dependency：

```toml
[project.optional-dependencies]
agent-openai = ["openai-codex==<M0_QUALIFIED_VERSION>"]
```

普通离线工程环境不得安装或 import SDK。

### M4 — 离线和本地集成测试

完成第 15 节的 offline unit/local process integration 测试。所有失败 run 必须按 v2 layout 原子保留，
且不得产生 proposal hash。

### M5 — P10 SDK qualification

在 frozen configuration 上执行一次新的 SDK P10 qualification。只有 9/9 PASS 才进入 M6。

### M6 — P13 SDK qualification

运行 frozen P13 benchmark，要求 schema、citation、admission、PIT 和全部负权限断言 PASS。
失败运行保持不可变，状态为 `FAILED / NOT_EVALUATED`，不得自动改写后重试为同一 run。

### M7 — Cutover 与清理

FR-03 全部通过后：

- P10/P13 canonical execution 直接使用 SDK adapter；
- 删除 `_codex_argv`、`verify_codex_version`、CLI subprocess execution 和 backend selector；
- 将 v1 parser/decoder 移至只读 `legacy_v1`；
- 不提供 `--harness codex-cli-legacy`；
- 更新 ADR、PLAN、README 和 implementation status。

## 15. 测试策略

### Offline unit tests（默认 `pytest --disable-socket`）

- request/policy canonicalization；
- provider event → AgentEvent mapping；
- unknown/malformed/oversized event fail closed；
- attempt、usage、retry 和 error aggregation；
- secret marker 不进入持久化 payload；
- P10 evaluator 的正负 fixture；
- P13 exact tool sequence/citation/proposal validation；
- v1/v2 replay dispatch；
- partial publication 和 hash mismatch fail closed。

SDK client 通过窄 fake boundary 注入；unit test 不要求登录、网络或真实 quota。

### Local process integration

- sanitized host/app-server/MCP environment；
- no inherited `TUSHARE_*`；
- isolated config home；
- read-only write denial；
- shell-disabled P13；
- network denial；
- timeout 后无残留进程；
- MCP crash、invalid response 和 oversized payload。

### Explicit live qualification

使用单独命令和 marker，不进入普通 pytest：

- authenticated SDK startup；
- P10 9/9；
- P13 frozen benchmark；
- usage/error/runtime identity capture；
- bounded overload retry（只有可控 fault injection 或 provider 明确返回 overload 时评价）。

quota、account 和 provider availability 失败属于 external runtime failure，不得转换为 research reject。

### Full regression

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

保持现有 coverage threshold。

## 16. FR-03 exit criteria

全部满足才允许 cutover：

```text
[ ] exact SDK dependency and bundled runtime identity recorded
[ ] no SDK import in default offline environment
[ ] pre-existing auth reused without QuantOS credential persistence
[ ] user config/plugins/global MCP cannot expand effective permissions
[ ] exact host/app-server/shell/MCP environment qualified
[ ] TUSHARE_* and synthetic parent secret are invisible
[ ] read-only sandbox qualified
[ ] P13 shell and Agent network disabled
[ ] exact MCP visibility and required-server behavior qualified
[ ] structured output and complete normalized transcript qualified
[ ] normalizer version/hash bound into provenance
[ ] usage captured without fabricated zero values
[ ] timeout terminates the complete process tree
[ ] retries are bounded and represented as immutable attempts
[ ] non-transient and unknown errors fail closed
[ ] P10 9/9 PASS
[ ] P13 schema/citation/admission/PIT and negative permissions PASS
[ ] failed attempts retain immutable evidence and no proposal authority
[ ] v1 P10/P13 artifacts still verify offline
[ ] P0-P13 regression, Ruff, formatting, Pyright and coverage PASS
```

## 17. 文件改动

新增：

```text
src/quantos/application/agent_harness.py
src/quantos/integrations/codex/__init__.py
src/quantos/integrations/codex/sdk_adapter.py
src/quantos/integrations/codex/sdk_host.py
src/quantos/integrations/codex/event_normalizer.py
src/quantos/integrations/codex/legacy_v1.py
tests/unit/test_agent_harness.py
tests/unit/test_codex_event_normalizer.py
tests/unit/test_agent_run_manifest_v2.py
tests/integration/test_codex_sdk_host.py
tests/live/test_p10_codex_sdk.py
tests/live/test_p13_codex_sdk.py
docs/adr/<next-unused>-official-codex-python-sdk.md
docs/fr03-codex-sdk-qualification.md
```

修改：

```text
pyproject.toml
uv.lock
src/quantos/contracts/agent.py
src/quantos/contracts/harness.py
src/quantos/contracts/status.py
src/quantos/application/harness_runner.py
src/quantos/application/harness_spike.py
src/quantos/application/p13_agent_runner.py
scripts/codex_capability_spike.py
scripts/p13_qualification.py
PLAN.md
README.md
docs/implementation-status.md
```

删除或迁入 `legacy_v1`：

```text
codex_argv / _codex_argv
verify_codex_version
CLI subprocess execution
runtime backend selector
application 层的 CLI JSONL knowledge
```

## 18. 风险与硬性应对

| 风险 | 硬性应对 |
|---|---|
| SDK/runtime 快速变化 | exact pin；每次升级重跑 M0、P10、P13 |
| SDK API 不足 | M0 `NO_GO`；不以猜测或宽松 fallback 进入 canonical path |
| auth/config 无法隔离 | FR-03 失败，不复制 credential 到临时 config home |
| provider event 丢失语义 | unknown event fail closed；qualification 保留可审计 raw stream |
| normalizer bug | version/hash 绑定；raw-vs-normalized fixture 和 replay tests |
| timeout 留下子进程 | isolated process group；终止后机械确认 |
| subscription quota/rate limit | external runtime failure；不产生 research verdict |
| model/runtime drift | manifest 绑定 identity/policy；升级重新 qualification |
| thread 被当作研究记忆 | thread 只作 working context；Ledger 仍是 canonical memory |

## 19. Definition of Done

重构完成意味着：

1. SDK 安全能力已经实测，不是由文档或类型名推断；
2. 新 run 只有一条 SDK execution path；
3. application/contracts 不依赖 OpenAI SDK；
4. transcript 可以在未安装 SDK、无网络条件下完整重放和重新评价；
5. runtime、normalizer、policy、attempt、usage 和错误均进入可哈希 provenance；
6. P10 9/9 与 P13 frozen benchmark 全部通过；
7. 历史 v1 evidence 保持字节和 hash 不变，并可由只读 verifier 检查；
8. CLI execution code 已删除，而不是被永久保留为第二 backend；
9. Agent authority、PIT hard rejection 和 `FAILED / NOT_EVALUATED` 语义未改变；
10. 全量离线回归和显式 live qualification 均有独立、可复核的报告。

FR-03 只阻塞需要真实 Agent runtime 的 P14 bounded autonomous execution；不阻塞与 runtime 无关的
deterministic contracts、Research Ledger、frozen-family enumeration 或 campaign statistics 工作。
