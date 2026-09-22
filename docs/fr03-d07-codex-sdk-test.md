# QuantOS FR-03 D0.7：Code Mode / Responses Lite 工具链资格诊断

> 状态：已实施；0.154.0 D0.7B1+ 为 `CODE_MODE_CHAIN_AVAILABLE`，FR-03 保持 `NO_GO`
> 更新日期：2026-09-21
> 范围：FR-03 / P10 Codex SDK qualification
> canonical SDK/runtime：`openai-codex==0.154.0` / bundled runtime `0.154.0`
> candidate control：`0.155.1`
> FR-03 决策：`NO_GO`

## 1. 决策摘要

D0.7 不直接解除 P10 阻塞，也不修改 P10 的 9/9 hard gate。它只回答两个可机械验证的
问题：

1. `gpt-5.6-sol` 在 exact release 中的 effective execution architecture 是否为
   `CodeModeOnly + Responses Lite + unified_exec`；
2. 当受控 provider 确定性返回合法的 Code Mode `exec` 调用时，冻结的本地 runtime 是否能
   完成 `exec -> tools.exec_command -> commandExecution` 链路。

D0.7 分为四个有序阶段：

| 阶段 | 作用 | 是否调用真实 provider | 是否门控下一阶段 |
|---|---|---:|---:|
| D0.7A | exact-tag source characterization | 否 | 是 |
| D0.7B0 | loopback shadow-provider 注入 preflight | 否 | 是 |
| D0.7B1 | deterministic Code Mode chain qualification | 否 | 是 |
| D0.7C | live provider observation | 是 | 否，仅定位 |

任何阶段输入、版本、来源或证据不完整时均 fail closed。D0.7C 不能反向覆盖 D0.7A/B 的机械
结论，也不能仅凭一次模型行为断言 provider defect。

## 2. 已知事实、待验证命题与依据

### 2.1 已有冻结证据

| 诊断 | 0.154.0 | 0.155.1 | 已证明 | 未证明 |
|---|---|---|---|---|
| D0 Python SDK thread/turn | completed，`commandExecution=0` | 相同 | high-level path 未观察到 command event | shell 不可用、sandbox 生效 |
| D0.5 direct `command/exec` | `/usr/bin/pwd` 成功 | 相同 | app-server direct command surface 可执行 | model tool surface 可用 |
| D0.6 raw app-server thread/turn | completed，`commandExecution=0` | 相同 | 绕过 high-level wrapper 后仍复现 | provider 或 runtime 的唯一根因 |

现有证据及 hash 见：

- [FR-03 qualification](fr03-codex-sdk-qualification.md)；
- [D0/D0.5 failure isolation](fr03-codex-sdk-failure-isolation-plan.md)；
- [D0.6 raw app-server test](fr03-d06-raw-app-server-isolation-test.md)；
- [upstream reproduction](fr03-codex-sdk-upstream-reproduction.md)。

官方 Codex SDK 文档确认：Python SDK 通过 JSON-RPC 控制本地 app-server，发布包携带固定版本的
Codex runtime 依赖。因此 D0.7 必须同时绑定 SDK package、runtime package、app-server reported
version 和实际 binary，而不能只记录 Python distribution version。参见
[OpenAI Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)。
loopback provider 写入隔离 `CODEX_HOME/config.toml` 的 user-level provider section，符合官方
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) 对 custom
model provider、`base_url` 与 `requires_openai_auth` 的定义；raw runner 的 JSON-RPC 边界依据官方
[app-server protocol](https://learn.chatgpt.com/docs/app-server)。

### 2.2 已验证的 source-derived architecture

D0.7A 对 `rust-v0.154.0` 与 `rust-v0.155.1` 的 exact-tag source characterization 已机械确认：

```text
gpt-5.6-sol
  tool_mode = code_mode_only
  use_responses_lite = true
  shell_type = unified_exec
```

由此推导的候选执行链为：

```text
model
  -> model-visible Code Mode tool `exec`
  -> code-mode-host executes JavaScript
  -> JavaScript calls nested tool `tools.exec_command`
  -> unified_exec
  -> app-server commandExecution lifecycle
```

该结论绑定 release tag、peeled commit、source archive/file hash 和 parser identity；它证明
release 内的 execution architecture，不证明 live provider 在某次 turn 中一定选择 `exec`。

### 2.3 术语约束

为避免把 wire placement 与 semantic visibility 混为一谈，全文使用以下术语：

| 术语 | 含义 |
|---|---|
| `request.tools` | Responses request 的顶层 `tools` 字段 |
| `additional_tools` | Responses Lite 中承载 tool schema 的 input item |
| model-visible `exec` | 模型语义上可调用的 Code Mode 工具，不表示它位于 `request.tools` |
| nested `exec_command` | 只供 Code Mode JavaScript 调用的内部工具 |
| direct shell tool | 直接暴露给模型的 shell tool；不是本方案对 `CodeModeOnly` 的预期 |

因此，下面两项可以同时成立：

```text
request.tools is absent/null
additional_tools contains model-visible `exec`
```

`exec_command` 未作为 direct shell tool 出现也不能单独判为失败。

## 3. 核心问题与非目标

### 3.1 必须回答

1. exact release 中 `gpt-5.6-sol` 的 effective `tool_mode`、`use_responses_lite` 与
   `shell_type` 分别是什么？
2. loopback provider 收到的首个 request 是否通过 `additional_tools` 语义暴露 `exec`？
3. scripted `exec` 是否被本地 Code Mode host 接受？
4. `tools.exec_command` 是否被实际调用并产生完整 `commandExecution` lifecycle？
5. 若本地链路通过，live path 在公开可观察边界上停在哪一层？

### 3.2 非目标

D0.7 不负责：

- 证明 filesystem 或 network denial；
- attestation effective sandbox policy；
- 运行完整 P10/P13；
- 修改 P10 rubric、canonical dependency lock 或 bundled binary；
- MITM 真实 OpenAI TLS traffic；
- 根据 Agent prose 判断 tool availability；
- 把 `0 commandExecution` 自动解释为 shell failure；
- 将 shadow-provider 结果宣称为真实 ChatGPT backend 行为。

所有产物均标记为 `NON_CANONICAL_DIAGNOSTIC`。Agent 输出仍只是 proposal，不构成 validated
evidence。

## 4. D0.7A：exact-release architecture characterization

### 4.1 输入与 provenance

分别针对：

```text
rust-v0.154.0
rust-v0.155.1
```

冻结并记录：

- release tag 与解析后的 commit SHA；
- source archive 或 Git tree identity 及 SHA-256；
- 可供离线重放的最小 source fixture；fixture 保留原始 repo-relative path，不做语义改写；
- 每个被解析文件的 repo-relative path 与 SHA-256；
- parser identifier、schema version 与 parser source SHA-256；
- SDK/runtime wheel identity；
- acquisition time 只作 metadata，不参与语义判断。

禁止使用 `main`、moving branch、`latest` 或未解析到 commit 的 tag 作为证据。tag 名与 commit SHA
必须同时存在；仅保存 URL 不足以重放。

### 4.2 最小 source set

从 exact tag 中定位并绑定以下语义的实际定义文件；路径若随 release 改变，可更新 manifest，
但不得静默降级：

```text
model metadata for gpt-5.6-sol
tool-mode resolution
CodeModeOnly exposure/filtering
Responses Lite request construction
Code Mode host registration
nested shell registration
feature default and override precedence
```

已知候选路径包括：

```text
codex-rs/models-manager/models.json
codex-rs/core/src/tools/mod.rs
codex-rs/core/src/tools/spec_plan.rs
codex-rs/core/src/client.rs
codex-rs/core/src/tools/code_mode/mod.rs
codex-rs/features/src/lib.rs
```

候选路径不是验收常量。parser 必须以 manifest 中的实际路径和内容 hash 为准。

### 4.3 输出 schema

`upstream-architecture.json` 至少包含：

```json
{
  "schema_version": 1,
  "release_tag": "rust-v0.154.0",
  "release_commit": "<40-hex>",
  "model": "gpt-5.6-sol",
  "tool_mode": "code_mode_only",
  "use_responses_lite": true,
  "shell_type": "unified_exec",
  "code_mode_host_enabled_by_default": true,
  "model_metadata_overrides_feature_default": true,
  "code_mode_only_hides_nested_tools_from_direct_model_surface": true,
  "responses_lite": {
    "request_tools_expected": "absent_or_null",
    "additional_tools_expected": true
  },
  "source_manifest_sha256": "<64-hex>",
  "parser_sha256": "<64-hex>"
}
```

字段必须由机械解析或针对 exact source 的严格断言得到。不得先硬编码期望值，再把相等结果描述为
“从 source 解析”。source shape、枚举值或 precedence 无法唯一确定时，分类为：

```text
ARCHITECTURE_CHARACTERIZATION_FAILED
```

### 4.4 D0.7A exit gate

只有以下条件全部满足才进入 D0.7B0：

- 0.154.0 source provenance 完整且 verifier 可离线重算；
- 三个 execution metadata 字段均被机械建立；
- Responses Lite placement 与 Code Mode exposure 规则均有 source anchor；
- parser 对 unknown source shape fail closed；
- 0.155.1 可以暂缓，但必须记录为 `NOT_RUN`，不能写 `NOT_REQUIRED`。

## 5. D0.7B0：shadow-provider 注入 preflight

D0.7B0 是正式 chain test 之前的独立停机点。它先证明 exact app-server 可以被安全地指向
loopback provider；若该前提不成立，不继续实现复杂 scripted SSE。

### 5.1 安全边界

shadow provider 必须：

- 绑定 `127.0.0.1` 或 `::1` 的随机空闲端口，禁止 `0.0.0.0`；
- 使用新的临时 `CODEX_HOME`，不得链接或复制真实 `auth.json`；
- 配置 provider 为不需要 OpenAI auth；
- 不读取 parent credentials，也不把它们放入 child environment；
- 只接受预期 method、path、content type 和有界 body；
- 限制 request 次数、单 request bytes、总 bytes 与 wall-clock duration；
- unexpected request/path/body shape 立即 fail closed；
- runner 只配置 loopback provider endpoint；外层 sandbox 继续禁止本阶段不需要的外部网络。

如果 exact release 无法在不携带真实 credential 的情况下使用 loopback provider，分类为：

```text
SHADOW_PROVIDER_INJECTION_UNAVAILABLE
```

不得为绕过该结果而把真实 token 发送给 mock server。

### 5.2 preflight 成功条件

preflight 只返回一个固定 final assistant message，不发 tool call。成功必须同时满足：

```text
app-server initialized
thread/turn started
exact model slug observed
exactly one loopback model request accepted
fixed final message observed
turn completed
configured provider endpoint is loopback-only
zero credential material retained
```

preflight 还必须冻结 request envelope 的 allowlisted projection，以确认 D0.7B1 所需的 response
protocol 与 endpoint shape，而不是从当前文档猜测 SSE event 格式。

## 6. D0.7B1：deterministic Code Mode chain qualification

### 6.1 不变量

使用：

```text
same bundled app-server binary
same packaged codex-code-mode-host
same OS and process architecture
same empty workspace policy
same bounded child environment
same gpt-5.6-sol model slug
same release-derived execution metadata
```

唯一替换项是 provider transport：真实 provider 被 D0.7B0 已验证的 deterministic loopback
server 替代。

优先直接使用 release 内建的 `gpt-5.6-sol` metadata，不复制一份“等价模型”。只有 exact release
接口确实要求 projection 时，才允许生成 `shadow-model-metadata.json`，且必须绑定：

```text
source model metadata hash
projection schema/hash
projected metadata hash
dropped fields and a source-backed proof that they do not affect this test
```

无法证明 projection 等价时停止为 `SHADOW_MODEL_METADATA_UNPROVEN`。

### 6.2 request-surface capture

首个 model request 只保存 allowlisted projection：

```json
{
  "schema_version": 1,
  "request_ordinal": 1,
  "model": "gpt-5.6-sol",
  "request_tools_state": "ABSENT",
  "input_item_types": ["...", "additional_tools"],
  "additional_tools_count": 2,
  "model_visible_tool_names": ["exec", "wait"],
  "model_visible_tool_names_sha256": "<64-hex>",
  "tool_schemas_sha256": "<64-hex>",
  "exec_visibility": "OBSERVED_TRUE",
  "wait_visibility": "OBSERVED_TRUE",
  "raw_request_sha256": "<64-hex>",
  "extractor_sha256": "<64-hex>"
}
```

`request_tools_state` 只能为：

```text
ABSENT | NULL | NONEMPTY | EMPTY
```

不能把 absent 与 `null` 合并成一个布尔值。tool-name set 在排序后 hash；tool schema 使用项目既有
canonical JSON 规则 hash。允许出现 `exec`/`wait` 之外的工具，不得假定集合恰好只有两个。

raw request 只在内存中 hash 后丢弃。离线 verifier 能验证 retained projection 与分类，但不能
证明 extractor 没有遗漏 raw request；这一 trust boundary 必须写入最终 limitation。

### 6.3 scripted provider response #1

第一个 response 确定性返回 exact-release protocol 所要求的 custom tool call：

```text
name = exec
arguments = release-valid minimal JavaScript
```

JavaScript 与 upstream exact-tag test 同型，并使用唯一固定安全 marker：

```javascript
text(JSON.stringify(
  await tools.exec_command({
    cmd: "printf QUANTOS_D07_NESTED_EXEC_OK"
  })
));
```

实际 event names、call id、argument envelope 和结束事件必须从 exact-tag upstream tests 或
D0.7B0 捕获的协议形状派生。script fixture 自身 canonical serialize 并 hash；运行时使用的 bytes
必须与 fixture hash 一致。

### 6.4 scripted provider response #2

app-server 把 tool result 送回 provider 后，第二个 response 固定返回：

```text
DONE
```

server 必须拒绝第三个 model request。第二个 request 的 safe projection 至少证明：

- 引用了 response #1 的 call identity；
- 包含对应 tool result item；
- nested result 存在；
- `output == "QUANTOS_D07_NESTED_EXEC_OK"`；
- `exit_code == 0`；
- `chunk_id` 非空；
- item 顺序和 request ordinal 正确；
- 不包含 credential material。

projection 只保留上述布尔值、整数和枚举，不持久化第二次 request 中未经审查的 raw output。
受控 `executed-tool-metadata-on` variant 同时显式设置：

```toml
[features]
executed_tool_call_metadata = true
```

exact-tag source 证明 non-OpenAI provider name 会在第二次 request 构建时清除 internal metadata。
因此该 variant 仅把 loopback provider 的 `name` 设置为 upstream 判定值 `OpenAI`；endpoint 仍固定
为 `127.0.0.1`，`requires_openai_auth=false`，server 仍拒绝任何认证头。其 safe projection 还要求
`cell_id` 绑定 outer `exec` call id、`tool_calls_complete=true`，且恰有一个 exact-argument
`exec_command` entry，才把 L5 记为 `OBSERVED_TRUE`。

### 6.5 本地执行证据

positive run 的成功条件全部为机械断言：

```text
model-visible exec observed in request projection
scripted exec call accepted
commandExecution started count == 1
commandExecution completed count == 1
started/completed item identity matches
command status == completed
exit code == 0
stdout bytes == UTF8("QUANTOS_D07_NESTED_EXEC_OK")
stderr bytes == empty
turn completed
final assistant message == "DONE"
```

不要仅根据 `exec` 最终文本、assistant prose 或 marker 字符串出现来推断命令执行。

raw app-server runner 在 `turn/completed` 后不立即停止：它使用 250 ms quiet window 和 1 s 总
deadline 做 bounded drain。terminal 后到达的合法 item/command lifecycle event 参与同一引用与
lifecycle 校验，不再仅因到达顺序被判 integrity failure；terminal 后的重复/非法 turn event 仍
fail closed。

若 public event surface 不直接暴露 Code Mode host invocation 或 nested dispatch，这两层记录为
`UNKNOWN`；不得伪造 `false`。B1+ 则通过 nested result structural proof 与 executed-tool metadata
分别把 L4/L5 提升为 `OBSERVED_TRUE`，而不是根据 assistant prose 推断执行。

### 6.6 Code Mode host identity

至少记录：

```text
resolved path
regular-file check
executable check
SHA-256
ELF/Mach-O/PE architecture where applicable
owning distribution name/version
matching dist-info RECORD entry
runtime binary distribution/version relationship
```

不能仅因文件位于 runtime package 附近就声称它由 `openai-codex-cli-bin` 提供。必须通过
distribution file manifest/`RECORD` 机械建立 ownership。

host 缺失、不可执行、architecture 不匹配或 runtime 明确 fail closed 时分类为：

```text
CODE_MODE_HOST_UNAVAILABLE
```

### 6.7 controls：先最小 positive，再 source-gated negative

第一轮只运行 canonical 0.154.0 的一个最小 positive case。不要先复制 D0 的四变体矩阵，因为
旧矩阵针对 direct shell hypothesis，且 feature semantics 尚未建立。

positive case 可解释后，再根据 D0.7A 结果决定 controls：

| control | 运行条件 | 目的 |
|---|---|---|
| `shell_tool=false` | exact source 证明会移除 Code Mode nested shell | 验证 nested inventory negative control |
| `unified_exec=false` | exact source 唯一确定 fallback 行为 | 验证 shell backend routing，不预设成功/失败 |
| 0.155.1 candidate | 0.154.0 已得到可解释 primary classification | 判断已知 candidate 是否改变行为 |

不满足运行条件的 control 记录 `NOT_RUN_UNPROVEN_SEMANTICS`，不得写成 pass、fail 或
`NOT_REQUIRED`。

## 7. 统一观察模型

每个 pipeline layer 使用四值状态，count 单独记录：

```text
OBSERVED_TRUE
OBSERVED_FALSE
UNKNOWN
NOT_APPLICABLE
```

含义：

| 状态 | 约束 |
|---|---|
| `OBSERVED_TRUE` | 有明确结构化正证据 |
| `OBSERVED_FALSE` | 观察面被证明完整，且目标事件确实缺失 |
| `UNKNOWN` | public/retained surface 不足以判断 |
| `NOT_APPLICABLE` | 由先前 gate 决定该层未执行 |

禁止用 JSON `false` 同时表示“未发生”和“不可观察”。每项观察必须携带：

```text
status
count or null
source artifact
source event/item id or JSON pointer
derivation rule identifier
```

建议的 pipeline observation：

```text
L0 turn started
L1 first model request captured
L2 model-visible exec present
L3 scripted exec accepted
L4 Code Mode host invoked
L5 nested exec_command dispatched
L6 commandExecution started
L7 commandExecution completed
L8 second model request captured
L9 turn completed
```

## 8. 判定规则与优先级

每个阶段 bundle 或 aggregate result 只能有一个 primary classification；其他异常写入
`secondary_findings`。按以下顺序
first-match，避免同一 evidence 被不同实现分类成不同结果：

| 优先级 | 条件 | primary classification |
|---:|---|---|
| 1 | artifact schema/hash/reference/secret scan 失败 | `EVIDENCE_INVALID` |
| 2 | SDK/runtime/model/source identity 不匹配 | `RUNTIME_OR_SOURCE_MISMATCH` |
| 3 | D0.7A 无法唯一建立 architecture | `ARCHITECTURE_CHARACTERIZATION_FAILED` |
| 4 | loopback provider 无法安全注入 | `SHADOW_PROVIDER_INJECTION_UNAVAILABLE` |
| 5 | shadow model metadata 等价性无法证明 | `SHADOW_MODEL_METADATA_UNPROVEN` |
| 6 | Code Mode host 缺失、不可执行或不匹配 | `CODE_MODE_HOST_UNAVAILABLE` |
| 7 | request 完整但 model-visible `exec` 不存在 | `MODEL_VISIBLE_CODE_MODE_MISSING` |
| 8 | scripted `exec` 被 protocol/router 拒绝 | `SCRIPTED_EXEC_REJECTED` |
| 9 | positive run 中 nested shell 被结构化证明不存在 | `NESTED_SHELL_MISSING` |
| 10 | nested dispatch 已证明，bounded drain 后 command event 为 0 | `NESTED_COMMAND_EXECUTED_COMMAND_EVENT_NOT_OBSERVED` |
| 11 | nested dispatch 已证明，但 lifecycle 部分出现后断裂 | `COMMAND_LIFECYCLE_GAP` |
| 12 | lifecycle 完整但 exit/output 不符合 probe | `COMMAND_PROBE_FAILED` |
| 13 | 所有 positive assertions 满足 | `CODE_MODE_CHAIN_AVAILABLE` |
| 14 | 以上均不能机械确定 | `INCONCLUSIVE` |

`CODE_MODE_HOST_UNAVAILABLE` 的判断可以来自 preflight，也可以来自 runtime structured error；不能
只搜索一段可能变化的 stderr 文本。

negative control 单独使用：

```text
NEGATIVE_CONTROL_PASS
NEGATIVE_CONTROL_FAILED
NEGATIVE_CONTROL_INCONCLUSIVE
NOT_RUN_UNPROVEN_SEMANTICS
```

negative control 不能替换 positive run 的 primary classification。

## 9. D0.7C：live provider observation

D0.7C 只在 canonical 0.154.0 D0.7B1 得到可解释结果后运行。它使用现有 ChatGPT auth isolation
策略，不保存或代理真实 HTTP request body。

固定条件：

```text
model = gpt-5.6-sol
sandbox = read-only
approval = deny_all
prompt = D0/D0.6 frozen prompt
```

```text
Run /usr/bin/pwd as a shell command.
After the command completes, report the exact working directory.
Do not answer without executing the command.
```

### 9.1 live evidence

只从现有 public app-server event stream 和已批准的安全 event projection 生成第 7 节的 observation
层级。无法观察 model-visible `exec`、host invocation 或 nested dispatch 时填 `UNKNOWN`。

不得：

- 从 assistant prose 推断执行；
- 保存真实 provider request/response body 或完整 headers；
- 因 `commandExecution=0` 把不可观察层填成 `OBSERVED_FALSE`；
- 因 shadow chain 成功就声称 live provider 必然获得相同 semantic surface。

### 9.2 live classification

| 条件 | classification | 允许的结论 |
|---|---|---|
| 完整 `exec -> commandExecution` 引用链 | `LIVE_CODE_MODE_EXECUTED` | live path 在该次运行启动了 Code Mode command |
| turn completed、command count 为 0、exec 层未知或无正证据 | `LIVE_EXEC_NOT_OBSERVED` | 本次保留证据未观察到 execution chain 启动 |
| `exec` 有正证据、nested/command 无正证据 | `LIVE_EXEC_WITHOUT_OBSERVED_COMMAND` | failure boundary 已越过 tool exposure，但后续层仍可能未知 |
| turn/auth/transport failed | `LIVE_DIAGNOSTIC_FAILED` | 运行条件失败，不评价 tool path |
| 证据不满足以上条件 | `LIVE_INCONCLUSIVE` | 不作根因归属 |

`LIVE_EXEC_NOT_OBSERVED` 不等于“provider 没有发送 exec”，更不等于“provider bug”。它只是一条
观察结论，可与 [openai/codex#31894](https://github.com/openai/codex/issues/31894) 的 hypothesis
相关联。QuantOS 自身的 upstream reproduction 为
[openai/codex#46947](https://github.com/openai/codex/issues/46947)。

## 10. Artifact 与 retention contract

### 10.1 推荐目录

```text
d07a-<version>/source-sha256-<hash>/
  source-fixtures/<repo-relative-path>
  upstream-architecture.json
  upstream-source-manifest.json
  diagnostic-manifest.json

d07b0-<version>/shadow-preflight-sha256-<hash>/
  runtime-identity.json
  provider-config-projection.json
  request-1-surface.json
  scripted-response-final.json
  provider-events.jsonl
  result.json
  diagnostic-manifest.json

d07b1-<version>/shadow-chain-sha256-<hash>/
  runtime-identity.json
  code-mode-host-identity.json
  upstream-architecture-ref.json
  request-1-surface.json
  scripted-response-1.json
  request-2-surface.json
  scripted-response-2.json
  provider-events.jsonl
  pipeline-observation.json
  result.json
  diagnostic-manifest.json

d07c-<version>/live-sha256-<hash>/
  runtime-identity.json
  requested-config.json
  provider-events.jsonl
  pipeline-observation.json
  result.json
  diagnostic-manifest.json
```

若 metadata projection 实际需要，额外加入 `shadow-model-metadata.json`；否则禁止生成一个看似
权威但未被 runtime 使用的文件。

### 10.2 serialization 与 publication

- `.json` 使用项目既有 canonical JSON；
- `.jsonl` 的每一行使用 canonical JSON，事件顺序保持 wire order；
- manifest 绑定精确文件集合、逐文件 hash、schema version 和 cross-artifact references；
- bundle 先写入同 filesystem staging directory，完成验证与 secret scan 后 atomic publish；
- 目录 content hash 的计算规则必须与 D0/D0.6 现有规则一致或显式 version；
- rejected/failed/inconclusive run 也不可变保留，不覆盖旧 bundle。

### 10.3 禁止持久化

```text
Authorization
access token / refresh token
cookie
raw auth.json
session credential
account email or account id
complete HTTP headers
live provider raw request/response
unreviewed raw stderr
parent TUSHARE_* values
```

shadow run 不应接触 credential。即便如此，所有 candidate bytes 仍须在落盘前经过 bounded in-memory
secret scan；发现疑似 secret 时停止发布并只返回固定错误类型，不回显命中值。

stderr 只保留 bounded byte count、line count 和 SHA-256；仅当 exact allowlist 定义了安全的
structured record 时，才可保留该 record 的 projection。

## 11. Offline verifier

verifier 不调用模型、provider 或网络，并从底层 retained artifacts 重算：

```text
bundle directory hash and exact file set
canonical JSON/JSONL
manifest and cross-file references
runtime and code-mode-host identity binding
source provenance and parser binding
request surface classification
tool-name/schema hashes
scripted response fixture hashes and call identity
commandExecution lifecycle counts and references
pwd bytes and exit status
pipeline observations
primary classification and secondary findings
secret-scan result
```

不能只验证已保存的 `result.json` hash。对于未保留的 raw request，verifier 只能验证 projection
内部一致性、raw hash binding 和 extractor identity；最终报告必须明确这一 extraction trust
boundary。

## 12. Tests

至少覆盖以下测试。

### 12.1 Source characterization

- 解析 exact model metadata；
- tag 必须解析到冻结 commit；
- 拒绝 moving branch 或 tag/commit mismatch；
- 拒绝 source file/archive hash mismatch；
- 拒绝 unknown source shape、unknown enum 和 ambiguous precedence；
- 0.154.0 与 0.155.1 fixture 不得互换。

### 12.2 Shadow-provider preflight

- 只绑定 loopback；
- 不存在 `auth.json` 仍可运行；
- unexpected path、第三次 request、oversized body 与 timeout 均 fail closed；
- provider request 不携带 authorization/cookie；
- 固定 final response 能完成 turn。

### 12.3 Request surface

- 分别识别 `tools` 的 absent、null、empty 与 nonempty；
- 识别 `additional_tools`、`exec` 与 `wait`；
- tool order 不影响 set hash，schema 内容变化会改变 schema hash；
- 不把 direct `exec_command` absence 判为 Code Mode failure；
- malformed/duplicate tool definition fail closed。

### 12.4 Shadow chain

- scripted `exec -> exec_command -> commandExecution` positive path；
- call/item identity mismatch；
- duplicate started/completed、completed-before-started；
- nonzero exit、错误 stdout、非空 stderr；
- host missing/unexecutable/ownership mismatch；
- nested shell missing 与 lifecycle missing 的分类边界；
- source-gated negative control 的 pass/fail/inconclusive。

### 12.5 Security and replay

- Authorization、cookie、token-like value、account identity 与 `TUSHARE_*` 在落盘前拒绝；
- raw stderr 不落盘；
- symlink/path traversal/extra file 被 verifier 拒绝；
- tampered request projection、script fixture、provider transcript、source provenance、host hash、
  manifest 和 result 均被拒绝；
- failed/inconclusive bundle 可离线重放且不会被后续运行覆盖。

## 13. 实施位置与命令面

优先扩展：

```text
scripts/codex_sdk_failure_isolation.py
tests/unit/test_codex_sdk_failure_isolation.py
```

脚本若继续增长，将纯 diagnostic logic 拆到：

```text
scripts/_codex_diagnostics/
```

`src/quantos/` 不得依赖 diagnostic implementation，`quantos.contracts` 也不得新增 Codex SDK 或
LLM dependency。

已实现的 CLI 按阶段而不是按模糊“tool surface”命名：

```text
--characterize-code-mode-source
--shadow-provider-preflight
--shadow-code-mode-chain
--live-code-mode-observation
--verify-d07-bundle
```

source/shadow 阶段还分别要求 `--source-archive` / `--architecture-bundle`；live 阶段要求一个已
离线验证的 `--shadow-chain-bundle`。0.155.1 只通过临时 `uv --with` overlay 运行，没有修改项目锁。

## 14. 执行顺序与停机条件

严格按以下顺序：

1. 实现 D0.7A parser、fixtures 与 offline verifier；
2. 完成 canonical 0.154.0 source characterization；
3. 实现并通过 0.154.0 D0.7B0 preflight；
4. 实现并运行一个 0.154.0 D0.7B1 positive case；
5. 离线验证该 bundle；
6. 仅运行有 exact-source 语义依据的 negative controls；
7. 0.154.0 primary classification 可解释后，再运行 0.155.1 candidate control；
8. 最后执行一次 D0.7C live observation；
9. 更新 FR-03 qualification、failure-isolation plan 与 implementation status；
10. 根据结果决定 P10 execution-contract revision 或 upstream follow-up。

以下任一情况立即停止当前后续阶段：

```text
source/runtime identity mismatch
architecture characterization ambiguous
shadow provider requires real credential
non-loopback request observed
artifact secret scan failed
bundle offline verification failed
```

不要在 D0.7 完成前重新运行完整 P10。

## 15. 结果对 P10 的影响

### 15.1 若 `CODE_MODE_CHAIN_AVAILABLE`

这只证明本地 frozen runtime 的受控链路可工作，并使原 D0 的 direct-shell hypothesis 失效。
历史证据保留，但解释更新为：

> The original D0 matrix observed zero downstream `commandExecution` events, but its
> `shell_tool`-based direct-surface hypothesis does not model the `CodeModeOnly` execution
> architecture mechanically established for `gpt-5.6-sol`.

随后应修订 P10 probe 的 execution model：

```text
model-visible Code Mode exec
  -> nested exec_command
  -> commandExecution
  -> sandbox / denial / recovery evidence
```

FR-03 仍为 `NO_GO`，直到新的 CodeMode-aware P10 达到 9/9。D0.7 shadow success 本身不能证明
`SANDBOX`、`PERMISSION_DENIAL` 或 `FAILURE_RECOVERY`。

### 15.2 若 D0.7B1 在本地链路失败

保持 `NO_GO`，以 primary classification 界定 failure boundary，并把新的机械证据整理为
[openai/codex#46947](https://github.com/openai/codex/issues/46947) 的候选更新。任何外部 issue
写入必须另行明确授权；本方案只生成本地、可审阅材料。

### 15.3 若仅 D0.7C 未观察到 exec/command

保持 `NO_GO`，记录 `LIVE_EXEC_NOT_OBSERVED` 或 `LIVE_INCONCLUSIVE`。可以说明结果与
[openai/codex#31894](https://github.com/openai/codex/issues/31894) 的 hypothesis 一致，但不得写成
已证明 provider bug。

## 16. Exit criteria

D0.7 完成必须满足：

- [x] exact 0.154.0 source、commit、file hashes 与 parser identity 已绑定；
- [x] `gpt-5.6-sol` execution metadata 已机械建立；
- [x] Responses Lite placement 与 semantic visibility 已分开记录；
- [x] loopback injection preflight 在无真实 credential 条件下通过；
- [x] bundled app-server 与 code-mode-host identity/ownership 已绑定；
- [x] first request safe projection 已捕获并 hash-bound；
- [x] scripted response protocol 来自 exact-release evidence；
- [x] positive `exec` 被接受并产生相同 call id 的 tool-output request；
- [x] `commandExecution` lifecycle、exit code 和固定 marker stdout 已独立验证；
- [x] nested result 与 executed-tool metadata 已在第二次 request 的安全投影中机械验证；
- [x] post-terminal bounded drain 已实施且 late item event 不再被自动拒绝；
- [x] 所有不可观察层使用 `UNKNOWN`，没有用 `false` 代替；
- [x] pinned 0.154.0 positive case 已满足完整链路；0.155.1 control 因不再影响判定而未重跑；
- [x] offline verifier 从底层 artifacts 重算 result；
- [x] inconclusive evidence 同样不可变保留；
- [x] live observation 已完成，分类为 `LIVE_EXEC_NOT_OBSERVED`；
- [x] 没有 credential、raw live request 或未审查 stderr 被持久化；
- [x] `pyproject.toml` 与 `uv.lock` 未改变；
- [x] canonical runtime 仍为 0.154.0；
- [x] FR-03 相关文档已同步，且 P10 threshold 未降低。

最终报告必须用 artifact pointer 回答：

1. 0.154.0 的 `gpt-5.6-sol` 是否确实为 `CodeModeOnly`；
2. Responses Lite request 是否语义暴露 model-visible `exec`；
3. scripted `exec` 是否调用 nested `tools.exec_command`；
4. nested command 是否产生完整 `commandExecution` lifecycle；
5. 当前阻塞属于 runtime/source mismatch、tool exposure、host、nested shell、lifecycle、probe、
   live observation，还是 evidence insufficient。

只能根据机械 evidence 选择分类，不得为了解除 P10 阻塞而降低资格标准。

## 17. 2026-09-22 D0.7B1+ 实施结果

本轮刷新后的 0.154.0/0.155.1 source bundle 与 0.154.0 B1+ bundle 均为
`NON_CANONICAL_DIAGNOSTIC`，并已由当前 `--verify-d07-bundle` 从 retained artifacts 离线重算
通过。旧 B0/B1/C 指针保留为历史证据，不伪装成用新 parser 重新发布的 bundle。

| version / stage | classification | bundle manifest hash |
|---|---|---|
| 0.154.0 D0.7A | `ARCHITECTURE_CHARACTERIZED` | `19dd2bc8...a60c5d8` |
| 0.154.0 D0.7B1+ metadata-on | `CODE_MODE_CHAIN_AVAILABLE` | `9c20e6c5...f4ecca64` |
| 0.155.1 D0.7A source-only refresh | `ARCHITECTURE_CHARACTERIZED` | `121e7fc0...c3cb7655` |

历史两版 source 结论仍为 `CodeModeOnly + Responses Lite + unified_exec`；更新后的 0.154.0 source
bundle 还机械绑定了 non-OpenAI provider metadata stripping gate。B1+ 首个 request 顶层 `tools`
absent，`additional_tools` 明确包含 model-visible `exec` / `wait`。第二次 request 的安全投影证明：
outer call id 匹配；nested result 存在；输出精确为固定 marker；exit 为 0；chunk id 非空；executed-
tool metadata 完整且只有一个 exact-argument `exec_command`。因此 L4/L5 都是 `OBSERVED_TRUE`。

public stream 同时包含同一 item id 的一个 `commandExecution` started 和 completed，状态成功且输出
匹配 marker。它们在 `turn/completed` 前到达；bounded post-terminal drain 的 event、item 和 command
计数均为 0。这不是 lifecycle 缺失，最终分类为 `CODE_MODE_CHAIN_AVAILABLE`。0.155.1 control 没有
重跑，因为 pinned 0.154.0 已给出决定性 positive result。

live 0.154.0 历史 turn 完成但 command count 为 0；由于 live HTTP body 按安全边界未保留，结论
仍仅为 `LIVE_EXEC_NOT_OBSERVED`。B1+ 证明一般性的 Code Mode/app-server chain 可用，但没有验证
P10 所需的 sandbox、permission denial 与 recovery。P10/P13 未重跑，9/9 hard gate 未降低，FR-03
继续 `NO_GO`。
