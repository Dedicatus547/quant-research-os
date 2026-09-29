# QuantOS FR-03 D0.6：Raw app-server Thread/Turn 隔离测试

## 1. 背景

当前已获得以下证据：

```text
openai-codex 0.154.0
    D0 SDK thread path:
        4 variants
        4 turns completed
        commandExecution = 0

    D0.5 direct app-server command/exec:
        PASS

openai-codex 0.155.1
    D0 SDK thread path:
        4 variants
        4 turns completed
        commandExecution = 0

    D0.5 direct app-server command/exec:
        PASS
```

因此已经可以排除：

- app-server binary 整体无法执行 command；
- `command/exec` surface 整体失效；
- QuantOS normalized-event parser 单纯漏掉 command；
- 单纯的 0.154.0 runtime regression。

当前剩余主要故障域：

```text
Python SDK high-level wrapper
        ↓
raw thread/start request
        ↓
app-server thread config resolution
        ↓
tool registry / model-visible tool surface
        ↓
model tool invocation
        ↓
commandExecution notification
```

D0.6 的目的，是进一步区分：

```text
Python SDK wrapper / request marshalling 问题

vs.

app-server thread/model tool provisioning 问题
```

---

# 2. D0.6 核心原则

D0.6 raw executor 必须：

- 不调用 `openai_codex.Codex`;
- 不调用 `Codex.thread_start()`;
- 不调用 `Thread.turn()` / `Thread.run()`;
- 不使用 QuantOS `CodexSdkAdapter`;
- 不经过 QuantOS event normalizer 来判断 command 是否存在。

直接启动与现有 SDK 完全相同的 bundled Codex app-server binary，并通过 stdin/stdout JSON-RPC 直接发送：

```text
initialize
    ↓
initialized
    ↓
account/read
    ↓
thread/start
    ↓
turn/start
    ↓
读取 raw JSON-RPC notifications
    ↓
直到 turn/completed / timeout
```

判断依据只能是 **raw app-server stream**。

第 6.1 节的 capture-only fixture characterization 是一个不启动 app-server、不调用
模型的独立步骤，不属于 raw executor。它可以使用 SDK 生成对照 fixture，
但 raw executor 本身不得调用上述 SDK high-level surface。

---

# 3. 环境必须与 D0 保持一致

使用临时空 workspace：

```text
/tmp/quantos-codex-d06-workspace-*
```

使用临时 `CODEX_HOME`：

```text
/tmp/quantos-codex-d06-home-*
```

其中只允许复用已有 regular `auth.json`，方式与现有 D0/D0.5 相同。

app-server 基础 environment 继续最小化为：

```text
CODEX_HOME=<temporary home>
LANG=C.UTF-8
PATH=/usr/bin:/bin
TZ=UTC
```

但必须区分两层 `PATH`：

```text
app-server process PATH
    = <codex_cli_bin bundled_path_dir>:/usr/bin:/bin

shell command PATH
    = /usr/bin:/bin
```

现有 SDK launcher 会在启动 bundled runtime 前，将
`codex_cli_bin.bundled_path_dir()` prepend 到 app-server process `PATH`。D0.6 必须逐版本
机械解析该路径并复现这一 effective child environment，不得将 app-server process
`PATH` 误写为单纯的 `/usr/bin:/bin`。

`shell_environment_policy` 仍必须将模型命令的 `PATH` 限制为
`/usr/bin:/bin`。两层 effective environment 都必须记录到 artifact，但不记录
未允许的 parent environment。

不得继承：

```text
TUSHARE_*
P10_FORBIDDEN_SECRET
用户 config
global MCP
plugins
Skills
额外 environment
```

不要增加 MCP、output schema 或其他工具，以免改变 tool planning。

---

# 4. Runtime identity

分别测试：

```text
0.154.0 canonical
0.155.1 candidate overlay
```

0.155.1 仍然通过临时 dependency overlay 执行，不修改：

```text
pyproject.toml
uv.lock
```

每次运行必须机械记录：

```text
openai-codex package version
openai-codex-cli-bin package version
app-server reported version
bundled binary SHA-256
exact app-server argv
exact initialize clientInfo
effective app-server environment
effective shell environment policy
model
reasoning effort
wire fixture hash
```

canonical runtime 仍然是 0.154.0。

---

# 5. Prompt

必须与 D0 完全一致：

```text
Run /usr/bin/pwd as a shell command.
After the command completes, report the exact working directory.
Do not answer without executing the command.
```

不要调整措辞。

---

# 6. Raw JSON-RPC sequence

## 6.1 逐版本 wire fixture characterization

在执行 raw D0.6 之前，先为 `0.154.0` 和 `0.155.1` 分别生成一份
capture-only wire fixture。

该步骤可以使用对应版本 SDK 的 high-level wrapper 和 model classes，但必须：

```text
只连接 capture-only fake transport
不启动 app-server
不调用模型
不访问网络
不读取 auth.json
```

目的是机械捕获该 SDK 版本实际构造的：

```text
initialize params
account/read params
thread/start params
turn/start params
app-server argv shape
child PATH construction rule
```

fixture 必须 canonical serialize 并计算 SHA-256。Raw D0.6 executor 只读取已冻结
fixture 并直接发送 JSON，不得使用 SDK model classes 重新构建请求。

fixture 对下列运行时值使用明确 sentinel：

```text
<TEMP_WORKSPACE>
<TEMP_CODEX_HOME>
<BUNDLED_BINARY>
<BUNDLED_PATH_DIR>
<THREAD_ID>
<REQUEST_ID>
```

Raw executor 只能替换 fixture 声明的 sentinel，不得修改其他字段。Verifier 必须用
本次运行的实际值做反向 normalization，然后与 fixture 逐字段相等比较。
这些 sentinel 只表示必然的动态值，不得用来忽略或宽松比较其他差异。

0.154.0 与 0.155.1 必须各有自己的 fixture，不得假定两个版本的 wire
shape 完全一致。

---

## 6.2 initialize

必须使用与对应版本 SDK D0 相同的 client identity，不得使用
`quantos_d0_6` 等诊断专用 identity：

```json
{
  "id": 0,
  "method": "initialize",
  "params": {
    "clientInfo": {
      "name": "codex_python_sdk",
      "title": "Codex Python SDK",
      "version": "<SDK_VERSION>"
    },
    "capabilities": {
      "experimentalApi": true
    }
  }
}
```

收到成功 response 后：

```json
{
  "method": "initialized",
  "params": {}
}
```

保存 initialize response，用于记录 runtime identity。

---

## 6.3 account/read

现有 D0 在 `initialized` 后、`thread/start` 前会执行：

```json
{
  "id": 1,
  "method": "account/read",
  "params": {
    "refreshToken": false
  }
}
```

D0.6 必须保持这一请求顺序，并验证 response 表明已有认证可用。

`account/read` response 不得以 raw 形式持久化。Artifact 只保存 canonical
request 以及经过明确 allowlist 的安全摘要，例如：

```json
{
  "authenticated": true
}
```

不得保存 account 详情、email、access token 或 refresh token。

---

## 6.4 thread/start

不要通过 Python SDK model classes 构建请求，直接发送 raw JSON。

核心语义必须等价于当前 D0：

```json
{
  "id": 2,
  "method": "thread/start",
  "params": {
    "approvalPolicy": "never",
    "cwd": "<TEMP_WORKSPACE>",
    "ephemeral": true,
    "model": "gpt-5.6-sol",
    "sandbox": "read-only",
    "config": {
      "...": "variant-specific D0 config"
    }
  }
}
```

其中 `config` 必须复用现有 D0 `_config(variant)` 的实际语义，而不是重新发明一套配置。

包括现有：

```text
history.persistence = none
allow_login_shell = false
shell_environment_policy.inherit = none
shell_environment_policy.set =
    LANG=C.UTF-8
    PATH=/usr/bin:/bin
    TZ=UTC
```

以及对应 variant 的 feature override。

保存完整：

```text
thread/start request
thread/start response
```

从 response 中取得真实 `thread.id`。

---

# 7. turn/start

随后直接发送 raw：

```json
{
  "id": 3,
  "method": "turn/start",
  "params": {
    "threadId": "<THREAD_ID>",
    "input": [
      {
        "type": "text",
        "text": "Run /usr/bin/pwd as a shell command.\nAfter the command completes, report the exact working directory.\nDo not answer without executing the command."
      }
    ],
    "approvalPolicy": "never",
    "cwd": "<TEMP_WORKSPACE>",
    "effort": "medium",
    "sandboxPolicy": {
      "type": "readOnly",
      "networkAccess": false
    }
  }
}
```

对当前 0.154.0，该 shape 的重要特征是：

```text
turn/start 再次显式发送 approvalPolicy=never
turn/start 不再发送 model，而是继承 thread model
final _start_turn payload 使用原始 text input，不包含 text_elements
sandboxPolicy 包含 networkAccess=false
```

如果对应版本 SDK 的 capture-only fixture 与上述字段存在差异：

> **以该版本 SDK 机械捕获的完整 wire request 为准。**

D0.6 的目标不是设计新的 raw protocol configuration，而是尽可能精确地复现 SDK D0 的 wire-level thread/turn 请求，同时绕过 SDK wrapper。

因此必须机械检查 Python SDK 对应版本的 capture-only fixture，确认：

```text
ApprovalMode.deny_all → approvalPolicy=never
Sandbox.read_only → thread sandbox=read-only
turn sandbox → readOnly policy
reasoning effort → medium
turn model → omitted / inherited from thread
text input defaults → exact SDK serialization
```

---

# 8. 四变体矩阵

D0.6 必须继续使用与 D0 完全相同的四个 variants：

## V1 — default

不显式 override shell feature：

```text
features: default
```

## V2 — shell-on-unified-default

```text
features.shell_tool = true
```

## V3 — shell-on-unified-off

```text
features.shell_tool = true
features.unified_exec = false
```

## V4 — shell-off negative control

```text
features.shell_tool = false
```

四个 variant 必须独立创建：

```text
temporary workspace
temporary CODEX_HOME
app-server process
thread
turn
```

禁止复用 thread，以免前一个 variant 污染后一个。

---

# 9. Raw event observation

从发送 `turn/start` 开始，完整保存 app-server stdout JSON-RPC stream。

读取器必须正确处理 response、notification 和 server-initiated request 的交错。任何
未识别或无法安全回应的 server request 都必须 fail closed 为
`DIAGNOSTIC_FAILED`，不得静默忽略。

一直读取到：

```text
turn/completed

or

turn/completed with status=failed or interrupted

or

hard timeout
```

至少统计：

```text
item/started
item/completed
turn/started
turn/completed
turn/completed status
thread/tokenUsage/updated
approval requests
warnings
errors
```

对于：

```text
item/started
item/completed
```

记录：

```text
item.type
item.id
item.status
threadId
turnId
```

只有同时匹配当前 `threadId` 和 `turnId` 的事件才参与统计。不匹配的事件必须
保留在 raw stream 中并导致 diagnostic fail closed，不得归入当前 turn。

verifier 必须按 `item.id` 检查生命周期：

```text
item/started(commandExecution, status=inProgress)
        ↓ same item.id
item/completed(commandExecution, status=completed|failed|declined)
```

重复 start、类型变化、缺少 completed、completed 无 start，或 turn 终态后出现新的
turn item，都必须标记为 `DIAGNOSTIC_FAILED`。

特别统计：

```text
item.type == commandExecution
```

最终至少生成：

```json
{
  "turn_status": "completed",
  "command_started_count": 0,
  "command_completed_count": 0,
  "command_failed_count": 0,
  "command_declined_count": 0,
  "observed_item_types": [
    "userMessage",
    "reasoning",
    "agentMessage"
  ]
}
```

Agent 自然语言声称“我运行了 pwd”不能算 command evidence。

唯一有效 command evidence 是 raw protocol 中的：

```text
commandExecution
```

或未来 app-server 提供的明确等价结构化 event。

`commandExecution` 的 started event 只证明结构化命令调用被观察到。它不自动证明
命令成功；成功还必须由 completed item 的 `status=completed` 和 `exitCode=0`
单独支持。D0.6 matrix classification 只回答“是否观察到命令调用”。

---

# 10. 最重要的对照要求

D0.6 与原 D0 唯一应该有意义的变化是：

```text
原 D0:
Python SDK high-level
    → app-server

D0.6:
raw JSON-RPC
    → app-server
```

下面这些东西必须保持一致：

```text
runtime binary
authentication
initialize clientInfo
account/read preflight
model
reasoning effort
prompt
cwd semantics
sandbox semantics
approval policy
features
environment
app-server argv
wire request shape
empty workspace
no project/user-configured MCP; identical runtime-provided built-ins
no Skill
no plugin
no output schema
```

否则不能把差异归因于 SDK wrapper。请求 `id` 和由 runtime 生成的 thread/turn/item
identifier 不要求相同，但必须在各自运行内保持引用完整性。

---

# 11. 结果分类

任何 capability classification 之前，必须先通过以下前置检查：

```text
runtime identity match
wire fixture match
initialize/account preflight match
effective environment match
JSON-RPC stream well formed and within bounds
thread/turn/item reference integrity
item lifecycle integrity
turn terminal status == completed
```

任一前置检查失败都必须优先分类为 `DIAGNOSTIC_FAILED`，不得再进入 A–D 的
capability classification。

## A. RAW_THREAD_COMMAND_AVAILABLE

如果 D0 定义的三个 positive variants 都出现：

```text
command_started_count > 0
```

而：

```text
shell-off = 0
```

则：

```text
classification = RAW_THREAD_COMMAND_AVAILABLE
```

在确认 wire fixture、client identity、前置顺序和 effective environment 相同后，这将作为
下列故障域的进一步诊断证据：

```text
Python SDK wrapper
request serialization
SDK message routing
或 SDK-created-thread configuration
```

可能存在问题。这不是对某一个组件的单独因果证明。

此时不要立即修改 QuantOS。

先将：

```text
raw working request
vs.
SDK-generated request
```

做逐字段 diff。

---

## B. RAW_THREAD_OBSERVABILITY_GAP

如果：

```text
default                 0
shell-on                0
shell-on-unified-off    0
shell-off               0
```

并且四个 turn 都 completed：

```text
classification = RAW_THREAD_OBSERVABILITY_GAP
```

则只能得出：

```text
The observability gap reproduces without the Python SDK high-level wrapper.
The wrapper is not required to reproduce this observation.
```

不得声称 wrapper 已被完全排除。这是因为两条路径使用独立模型调用，且
`gpt-5.6-sol` 标识符不是不可变的模型版本绑定。

下一步诊断重点收缩为：

```text
app-server thread config resolution
        ↓
tool registry construction
        ↓
tool exposure to model
        ↓
model/tool routing
```

这是当前最重要的预期结果之一。

将结果追加到：

```text
openai/codex#46947
```

---

## C. NEGATIVE_CONTROL_FAILED

如果：

```text
shell_tool=false
```

仍产生 command：

```text
classification = NEGATIVE_CONTROL_FAILED
```

这意味着：

```text
feature override 没有生效
或
shell tool exposure 不受该 feature 控制
```

必须停止 P10 qualification。

---

## D. VARIANT_DEPENDENT

如果只有部分 positive variant 出现 command：

```text
classification = VARIANT_DEPENDENT
```

保留完整 raw evidence，再分析：

```text
shell_tool
unified_exec
```

对 tool registry 的实际影响。

不要直接恢复 P10。

---

## E. DIAGNOSTIC_FAILED

如果发生：

```text
auth failure
transport failure
invalid params
timeout
runtime mismatch
wire fixture mismatch
unexpected server request
cross-thread or cross-turn event
item lifecycle violation
stdout/stderr size limit exceeded
prohibited secret observed
```

分类为：

```text
DIAGNOSTIC_FAILED
```

这不是 shell capability 的 PASS/FAIL。

---

# 12. 可选 D0.6b：approval control

只有在主 D0.6 仍为：

```text
RAW_THREAD_OBSERVABILITY_GAP
```

时，再额外做一个非 canonical control。

只测试一个或两个 positive variant：

```text
default
shell_tool=true
```

将：

```text
approvalPolicy = never
```

改成等价于 SDK `auto_review` 的配置。

其余全部不变。

目的仅仅是排除：

```text
approvalPolicy=never
```

意外影响 shell tool exposure 的可能性。

D0.6b 不参与 P10 qualification，也不修改主 D0.6 matrix classification。

---

# 13. Artifact

建议扩展现有：

```text
scripts/codex_sdk_failure_isolation.py
```

增加：

```text
--raw-thread
```

而不是新建独立的一次性脚本。

每个 D0.6 variant bundle 至少包含：

```text
runtime-identity.json
wire-fixture.json
effective-environment.json

initialize-request.json
initialize-response.json

account-read-request.json
account-read-summary.json

thread-start-request.json
thread-start-response.json

turn-start-request.json
turn-start-response.json

provider-events.jsonl

result.json
manifest.json
```

`result.json.limitations` 至少必须包含：

```text
MODEL_IDENTIFIER_NOT_IMMUTABLE
EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED
INDEPENDENT_MODEL_CALLS_NOT_CAUSAL_PROOF
```

aggregate：

```text
matrix.json
```

所有 JSON 使用 canonical serialization。

所有 artifact content-addressed。

matrix verifier 必须可以：

```text
无需再次调用模型
```

从保存的 raw events 重算：

```text
turn status
command counts
item types
thread/turn/item reference integrity
command lifecycle counts
classification
eligible_for_p10
```

verifier 还必须检查：

```text
wire-fixture hash 与 runtime/SDK version 绑定
initialize/account/thread/turn request 经声明的 sentinel normalization 后与 fixture 相等
initialize clientInfo 与对应 SDK 版本相等
app-server argv 与 effective child PATH 与 fixture 相等
account-read-summary 只包含 allowlisted 字段
raw JSONL 每行和总体都在预定上限内
```

`eligible_for_p10` 在 D0.6 中始终只是对诊断分类的机械派生；D0.6 本身不能
越过现有 P10 9/9 hard gate。

---

# 14. 安全要求

禁止 artifact 保存：

```text
auth.json contents
access token
refresh token
TUSHARE_* values
parent secret
stderr 中可能出现的 credential
```

若 raw provider output 回显禁止 secret：

```text
立即 fail closed
不持久化泄漏 payload
只保存稳定 error/hash
```

必须在任何 raw payload 写入 artifact 之前执行内存中的 fail-closed 检查。
`account/read` raw response 不进入通用 artifact writer，只转换为第 6.3 节规定的
allowlisted summary。

raw I/O 必须有明确边界，与现有 D0 的 transcript bound 保持一致：

```text
MAX_PROVIDER_TRANSCRIPT_BYTES = 1_000_000
MAX_JSON_RPC_LINE_BYTES = 256_000
MAX_STDERR_BYTES = 64_000
```

实现必须：

- 在读取时限制单行和累计 stdout，不先无界缓存再检查；
- 从进程启动起并发 drain stderr，防止 pipe 写满导致死锁；
- 不持久化 raw stderr，只保存 bounded byte/line count 和整体 SHA-256；
- 超出任一上限时立即中断 turn，终止 app-server process group，并分类为
  `DIAGNOSTIC_FAILED`；
- 对非 UTF-8、非 JSON object、过大 JSON-RPC line 或缺失终结换行的输入 fail closed。

与当前 D0 策略保持一致。

---

# 15. 不允许做的事情

D0.6 不应：

- 修改 `CodexSdkAdapter`;
- 修改 P10 evaluator rubric;
- 修改 FR-03 hard gate;
- 修改 P13；
- 修改 canonical SDK pin；
- 修改 `pyproject.toml` / `uv.lock` 来测试 0.155.1；
- 使用 CLI `codex exec` 作为 fallback；
- 根据 Agent 文本推断 command 成功；
- 把 D0.5 `command/exec` PASS 当作 thread sandbox PASS；
- 因为测试失败而降低 P10 9/9 要求。

这是 failure-isolation diagnostic，不是 workaround。

---

# 16. 最终报告格式

最终给出类似：

```text
D0.6 raw thread matrix

Version: 0.154.0
Runtime hash: ...
Matrix hash: ...

variant                    turn       command
default                    completed  0
shell-on                   completed  0
shell-on-unified-off       completed  0
shell-off                  completed  0

classification:
RAW_THREAD_OBSERVABILITY_GAP
```

然后对 0.155.1 再给一个完全相同的表。

最后只允许得出机械结论：

```text
如果 raw JSON-RPC 与 SDK 都是四个 0 command：

The observability gap reproduces without the Python SDK high-level
thread/turn wrapper. The wrapper is not required to reproduce this
observation. Continue diagnosis in the app-server thread/model tool path;
this result does not fully exclude independent SDK-path defects.

如果 raw JSON-RPC 出现 command 而 SDK 不出现：

The direct app-server thread path emits a structured command invocation
while the Python SDK path does not. Compare the exact initialize,
account/read, thread/start and turn/start wire requests, effective child
environment, and SDK notification routing before changing QuantOS.
```

不要超出证据声称：

```text
sandbox broken
shell execution broken
model broken
```

除非新的结构化证据明确支持。

---

# 17. D0.6 exit criteria

D0.6 完成条件：

```text
[x] 0.154.0 raw four-variant matrix
[x] 0.155.1 raw four-variant matrix
[x] per-version capture-only wire fixtures frozen and hashed
[x] exact runtime identity
[x] exact initialize clientInfo retained
[x] account/read preflight reproduced with allowlisted summary only
[x] exact app-server argv and effective child PATH retained
[x] exact raw thread/start request retained
[x] exact raw turn/start request retained
[x] raw provider stream retained
[x] transcript line/total/stderr bounds enforced
[x] thread/turn/item reference integrity verified
[x] command lifecycle counts mechanically recomputable
[x] shell-off negative control included
[x] matrix independently replay-verifiable
[x] no credentials persisted
[x] canonical lock unchanged
[x] classification mechanically generated
[x] MODEL_IDENTIFIER_NOT_IMMUTABLE limitation retained
[x] docs/FR-03 evidence updated
```

如果两个版本最终都得到：

```text
RAW_THREAD_OBSERVABILITY_GAP
```

则 D0.6 之后暂停主动 FR-03 runtime debugging，将本地结果整理为
`openai/codex#46947` 的待追加更新，等待上游反馈，同时 QuantOS 主线恢复 P14b。

---

# 18. 2026-09-21 实施结果

D0.6 已按本文档实施。Raw executor 直接启动 bundled app-server，不经过
`openai_codex.Codex`、`Thread.turn()` 或 QuantOS normalizer。逐版本 capture-only fake transport
证实最终 `turn/start` wire payload 显式包含
`approvalPolicy=never`，不包含 turn-level `model` 或 `text_elements`。

| version | default | shell-on | shell-on/unified-off | shell-off | classification | matrix |
|---|---:|---:|---:|---:|---|---|
| 0.154.0 | 0 | 0 | 0 | 0 | `RAW_THREAD_OBSERVABILITY_GAP` | `80715924...947d7` |
| 0.155.1 candidate | 0 | 0 | 0 | 0 | `RAW_THREAD_OBSERVABILITY_GAP` | `af78f1e7...0b438` |

八个 turn 全部 completed；每个 bundle 的 thread/turn/item reference 与 item lifecycle
检查均通过。两个 matrix 均已通过无模型调用的离线重放验证，
`eligible_for_p10=false`。0.155.1 使用临时 dependency overlay；`pyproject.toml` 与
`uv.lock` 仍冻结在 0.154.0。

Raw stream 出现了 runtime 自带的 `codex_apps` startup status；这不是项目或用户配置的
MCP，并且两个版本、两条对照路径保持一致。

机械结论为：observability gap 在不使用 Python SDK high-level thread/turn
wrapper 时仍可复现，因此 wrapper 不是复现该观察的必要条件。这不完全排除
独立的 SDK-path defect，也不证明 sandbox、shell execution 或 model 本身失效。

本地非权威诊断产物位于：

```text
artifacts/feasibility/codex-sdk-diagnostics/d06-0.154.0/
artifacts/feasibility/codex-sdk-diagnostics/d06-0.155.1/
```

尚未对外更新 `openai/codex#46947`；本地 provider-facing reproduction 已包含可追加内容。
