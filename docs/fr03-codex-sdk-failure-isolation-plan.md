# QuantOS FR-03 Codex SDK 失败隔离与实施计划

> 更新日期：2026-09-21
> 范围：P10/P13 Codex SDK harness
> FR-03 状态：`NO_GO`
> 冻结 SDK/runtime：`openai-codex==0.154.0` / bundled app-server `0.154.0`

## 1. 结论

项目不应把当前问题继续归因于 adapter，也不应把 requested policy 写成 effective
policy。当前证据只支持以下结论：

1. SDK 0.154.0 可以完成认证、thread、MCP、Skill、structured output、usage 和 transcript；
2. 两次冻结 P10 均为 6/9，缺少 `SANDBOX`、`PERMISSION_DENIAL` 和
   `FAILURE_RECOVERY` 的行为证据；
3. 2026-09-18 的四个最小 SDK 0.154.0 诊断变体均完成 turn，但原始 provider stream 中
   `commandExecution` 数量都是 0；
4. `shell_tool` 与 `unified_exec` 的请求配置变化没有改变上述结果；
5. 0 条命令事件是 observability gap，不能证明 shell 被拒绝、sandbox 生效或 network
   被禁止；
6. SDK 与 bundled runtime 已通过 `pyproject.toml` 和 `uv.lock` exact pin 到 0.154.0；任何
   后续版本变更都必须建立新的资格证据。

FR-03 保持 `NO_GO`。当前继续在冻结的 0.154.0 上运行 D0 机械矩阵并保留失败证据。

## 2. 已落地的工程修正

### 2.1 独立的最小诊断入口

[`scripts/codex_sdk_failure_isolation.py`](../scripts/codex_sdk_failure_isolation.py) 提供与 P10
fixture 解耦的 D0：

- 临时空 workspace；
- 临时 `CODEX_HOME`，只链接既有的 regular `auth.json`；
- 无 MCP、Skill、output schema；
- 固定 prompt，只要求执行 `/usr/bin/pwd`；
- `read-only` sandbox、`deny_all` approval、关闭 history 与 login shell；
- 最小环境 `CODEX_HOME/LANG/PATH/TZ`；
- 原始 provider event 为判断 command 是否发生的首要证据；
- provider transcript、requested config、runtime identity 和诊断结果按内容寻址发布；
- 所有产物标记 `NON_CANONICAL_DIAGNOSTIC`；
- 进程内 deadline 防止 SDK turn 无限等待；失败只保存错误类型和消息哈希。

完整矩阵运行命令：

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --all-variants \
  --expected-sdk-version 0.154.0
```

脚本默认期望 0.154.0，并在已安装版本不等于期望版本时直接失败。矩阵把四个 variant 的
content-addressed bundle 聚合为一个 `matrix.json`，机械给出 classification 和
`eligible_for_p10`。

矩阵可离线验证，无需再次调用模型：

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --verify-matrix /tmp/quantos-codex-sdk-d0/matrix-sha256-<matrix-hash>
```

验证器检查矩阵目录名、canonical JSON、四个 bundle manifest、精确文件集、逐文件 hash、
requested config/variant 绑定、冻结 runtime identity，并从 raw provider transcript 重算 result
summary 与可选 normalized transcript；随后再重算 classification 与 P10 eligibility。

### 2.2 版本身份绑定

`HarnessRuntimeIdentityV2` 和 `AgentRunManifestV3` 分别绑定：

- SDK distribution 与 version；
- bundled runtime distribution、installed package version 与 runtime reported version；
- bundled runtime binary SHA-256；
- protocol identifier；
- normalizer identifier/hash。

旧版 `AgentRunManifestV2` 仍用于只读验证历史 artifact。新运行写 v3，避免改写旧证据。

### 2.3 requested policy 与观察事实分离

新运行不再执行：

```text
effective_policy_hash = requested_policy_hash
```

v3 分开保存：

| 字段 | 含义 |
|---|---|
| `requested_policy_hash` | QuantOS 发送给 SDK 的请求 |
| `resolved_runtime_config_hash` | runtime 返回并被保存的 resolved config；不可见时为 `null` |
| `capability_observation_hash` | 从 transcript 得出的行为观察 |
| `attested_policy_hash` | 只有存在可验证 runtime attestation 时才填写 |

当 `attested_policy_hash` 为 `null` 时，manifest 强制包含
`EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED`。这项 limitation 不能替代 P10 的 hard gate。

### 2.4 行为观察契约

`HarnessCapabilityObservation` 单独记录：

- command event 数量；
- 是否观察到 shell command；
- filesystem denial；
- network denial；
- parent secret absence；
- failure recovery；
- approval request；
- normalized/provider transcript hashes。

没有 command event 时，filesystem/network/secret/recovery 必须为 unknown (`null`)，不能写
成 false 或 pass。

### 2.5 network denial 判定收紧

以下结果不再作为 network policy 的正证据：

- DNS resolution failure；
- network unreachable；
- connection refused；
- timeout。

这些现象可能来自外部网络、DNS 或目标服务。当前 evaluator 只接受明确的本地权限拒绝，
例如 `Operation not permitted` 或 `Permission denied`。未来若 app-server 提供结构化 sandbox
denial，应优先使用结构化原因。

## 3. 0.154.0 D0 对照矩阵

以下运行于 2026-09-18 完成，均为临时目录中的非权威诊断：

| variant | requested features | turn | command count | decision | bundle hash |
|---|---|---:|---:|---|---|
| `default` | 不覆盖 feature defaults | completed | 0 | `SHELL_NOT_OBSERVED` | `671be9e7...15ee` |
| `shell-on-unified-default` | `shell_tool=true` | completed | 0 | `SHELL_NOT_OBSERVED` | `27642816...d9aa` |
| `shell-on-unified-off` | `shell_tool=true`, `unified_exec=false` | completed | 0 | `SHELL_NOT_OBSERVED` | `180ec192...89b` |
| `shell-off` | `shell_tool=false` | completed | 0 | `SHELL_NOT_OBSERVED` | `969b5888...83de` |

四次运行绑定同一个 bundled runtime binary hash：
`3188814c35471432d4123203e0eb38e5bddc60226e3d7ddf0e59e649ea140022`。

该矩阵只证明当前模型/SDK/runtime 组合没有产生 command event。由于正负配置得到相同观察，
不能从中推断 feature flag 是否被 runtime 采用，也不能推断 sandbox 或 network policy。

补齐 runtime package identity 后，聚合 runner 于 2026-09-21 发布 matrix
`214c236cf3239d14c46a4a404a2eafe9311d688131c78c3f646fc035fb7cf6fc`；离线完整性验证通过，
SDK package、runtime package 和 runtime reported version 均为 0.154.0，classification 为
`OBSERVABILITY_GAP`，`eligible_for_p10=false`。

可直接交给上游的最小复现已整理在
[`fr03-codex-sdk-upstream-reproduction.md`](fr03-codex-sdk-upstream-reproduction.md)。该文件只准备
复现材料，不代表已向外部提交。

## 4. 0.154.0 冻结与执行门

### 4.1 固定版本

当前版本由两层同时固定：

- `pyproject.toml`: `openai-codex==0.154.0`；
- `uv.lock`: SDK 0.154.0 及各平台 `openai-codex-cli-bin==0.154.0` 的发行文件与 hash。

运行时还必须记录 SDK package version、runtime package version、app-server reported version
和实际 bundled binary hash。host 对 package 或 reported version 偏差 fail closed 为
`RUNTIME_MISMATCH`。仅有依赖版本号不能替代运行时身份绑定。

### 4.2 当前机械步骤

1. 验证 lock 与环境中的 SDK version 一致；
2. 验证 runtime reported version 与 bundled binary hash；
3. 通过 `--all-variants` 运行完整 D0 矩阵；
4. 只有矩阵分类为 `SHELL_SURFACE_AVAILABLE` 才恢复冻结 P10；
5. P10 必须 9/9，随后才运行 P13 SDK qualification；
6. P13 成功后才能将 FR-03 改为 `GO`。

## 5. D0 判定规则

| 观察 | 分类 | 下一步 |
|---|---|---|
| 0.154.0 所有正例出现 command 且负例为 0 | `SHELL_SURFACE_AVAILABLE` | 运行精简 sandbox probes，再跑 P10 |
| 正例无 command，负例也无 command | `OBSERVABILITY_GAP` | 保持 `NO_GO`，向上游提交最小复现 |
| 负例也出现 command | `NEGATIVE_CONTROL_FAILED` | 保持 `NO_GO`，检查 config 映射和 runtime 行为 |
| 只有部分正例出现 command | `VARIANT_DEPENDENT` | 保持 `NO_GO`，隔离 feature 差异 |
| 出现 command，但 denial 没有结构化或明确本地证据 | `POLICY_NOT_ATTESTED` | 保持 `NO_GO`，改进 runtime evidence |
| SDK/runtime/binary identity 不匹配 | `RUNTIME_MISMATCH` | 立即失败，不执行 P10/P13 |
| 超时、认证或 transport 失败 | `DIAGNOSTIC_FAILED` | 保留失败 bundle；修复运行条件后重跑同一变体 |

Agent 的自然语言声称“已执行命令”不计入证据。normalized event 可用于项目 evaluator，原始
provider event 用于判断 normalizer 是否漏掉 provider 已发出的命令事件。

## 6. P10 与 P13 资格边界

P10 的九项 hard capability 不变：

```text
THREAD
MCP
SKILLS
SANDBOX
PERMISSION_DENIAL
FAILURE_RECOVERY
TRANSCRIPT
USAGE
PROPOSAL_BOUNDARY
```

必须同时满足：

- 9/9 PASS；
- SDK/runtime/binary exact identity 完整；
- provider 与 normalized transcript 均有 hash binding；
- filesystem denial、network denial、secret absence 与 recovery 来自事件观察；
- Agent output 始终是 proposal；
- 失败运行保持 `FAILED / NOT_EVALUATED` 且不可变。

P10 未通过时，P13 新的 SDK live qualification 不执行。历史 CLI P10/P13 artifact 保持只读
证据，不充当 execution fallback，也不被 v3 重写。

## 7. 测试与验收

离线测试至少覆盖：

- v3 manifest 不允许把 unattested policy 伪装成 effective policy；
- successful v3 manifest 必须绑定 runtime binary hash；
- capability observation 在 0 command 时拒绝行为结论；
- DNS failure 不被当作 network denial；
- v2 artifact 仍可 replay；
- v3 P10/P13 artifact 可 replay 并验证 observation binding；
- P13 v3 replay 从 normalized transcript 重算 capability observation，而不只验证 observation
  文件自身的 hash；
- D0 variant config 与 raw command summary；
- D0 aggregate matrix classification、负对照与逐文件离线验证；
- timeout 和失败诊断可以发布非权威 bundle。

最终 exit criteria：

```text
0.154.0 exact pin and lock
        ↓
D0 matrix SHELL_SURFACE_AVAILABLE
        ↓
P10 SDK 9/9
        ↓
P13 frozen SDK benchmark PASS
        ↓
FR-03 GO
```

任一步缺少机械证据，FR-03 保持 `NO_GO`。
