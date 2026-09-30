# HM-01 基线审计与实施范围

日期：2026-09-29。状态：`DRAFT_FOR_HM02_REVIEW`。本记录不授予 hosted、SDK、PIT 或研究资格。
任务模型：`gpt-6-sol`；effort：`high`；attempt：1；usage：`unavailable`。

## 精确起点

| 对象 | 观测 / 绑定 |
|---|---|
| 实施起始完整 commit | `d6c77055eaa4844a2e0d9423990475ef23dce15c` |
| 历史 `p14-rc-v1` peeled commit | `3a4a898f74ce2f60a14d2a69250024e92a4378c1` |
| 历史生产资格实现 | `e318dc450e5c02f1120da7644250767bf682b6f9` |
| `uv.lock` SHA-256 | `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca` |
| 用户 roadmap SHA-256 | `0864563a656341df125cf03801cc0acd37a75e020e2b5ec703dad5cd206d6c56` |
| 用户 docs/README.md SHA-256 | `1dda1b521c04769ef9c0e81a717f4722a39e0f2e2b4743f195e9ee0a1458f9df` |

起点工作区已有 ` M docs/README.md` 与 `?? docs/roadmap/host-mediated-mvp.md`，属于用户输入。
HM-01 不覆盖这两者。新资格必须绑定后续 clean implementation commit，不能将本起点或旧资格
视为新组合已批准。`.venv` 存在；本任务只做接口审计，未跑生产资格或测试。

## 实际调用链与差异

| 实际接口 / 证据路径 | 已有行为 | hosted 所需差异 |
|---|---|---|
| `src/quantos/application/autonomous.py:AutonomousAgentDriver.run` | 同步 `request → response` | 新等待出口，不能把等待写成研究失败或无限阻塞 |
| 同文件 `AutonomousCampaignOrchestrator.run` | seed events、Ledger 对账、冻结 request、driver、exchange、trial、Ledger、P14c | request 发布前预留；等待恢复读取原 request；独立 transport ordinal |
| 同文件 `_build_agent_request` | 绑定有限 candidate options、schema、ContextPack、budget、policy、AgentRunSpec | 原请求业务绑定可复用；须持久化完整 bytes、时间锚点与读取投影 |
| `src/quantos/contracts/autonomous.py:AutonomousAgentRequest` | 不可变 v1，ContextPack 和 RunSpec 双重绑定 | hosted 独立 envelope 增加 profile/deployment/reservation/input bindings |
| 同文件 `AutonomousAgentResponse` | 必需 `AgentRunManifest(v1)`，SUCCEEDED 与 proposal bytes/hash | 独立 hosted response；缺失 usage/provenance 用 unavailable，不能填旧 manifest |
| `autonomous.py:_validate_response` | 精确检查 harness、模型、所有 policy、instruction、skill、tool 与 input hashes | 保留原 profile；独立 hosted validator 不弱化旧检查 |
| `AutonomousAgentExchangeStore` | 只保存完成 exchange；原子不覆盖、目录 flock、canonical/hash 校验 | pending、预算 reservation、提交/拒绝/冲突 receipts、取消/过期与恢复 journal |
| `_parse_candidate_proposal / _proposal_matches_candidate` | canonical bytes + safe DSL + parameters/expression/fingerprints 对冻结候选逐项比较 | 复用；candidate 可识别的 schema-invalid 形成原业务 trial；transport 错误不虚构 trial |
| `autonomous_execution.py:QuantosResearchExecutionAdapter.execute` | trial identity reservation、execution lock、已有 receipt 校验复用、PIT/Qlib/Validation | hosted execution intent 与 receipt 对账；无 receipt 的已启动执行保持不确定并停止 |
| `autonomous.py:_reconcile_ledger / _selection_handoff` | event→Ledger 补写；P14c frozen plan 与完整分母；既有终态 | 复用 authority 语义；hosted exchange 使用独立来源而非 SDK transcript |
| `artifacts/store.py:atomic_write_bytes / exclusive_directory_lock` | 临时文件 fsync、hard-link create-if-absent、目录 fsync、flock | 复用；多文件提交用 append-only journal + recovery，不能误称原子事务 |
| `src/quantos/cli.py` | Typer 子命令；无 hosted 入口 | HM-05 薄客户端；与未来 MCP 共用应用服务 |
| `contracts/agent.py:AgentUsage / AgentRunManifestV3` | 数字 usage 必需；SDK provenance 与 requested/effective 分离 | hosted 不借用 SDK v3；source-aware observation 单独契约 |

当前 `run_ordinal = campaign_snapshot.agent_run_count + 1`，计数来自已有 trial events。
未响应或没有可解析 candidate 的错误不能靠该计数限制 hosted 重试。新 transport 请求/提交预算
必须独立持久化，并与研究 trial/agent_run 数字分别报告。原 driver 只能在真正完成请求后返回；
独立 hosted 路径不能构造“SDK 成功”来满足旧 driver 的 manifest 条件。

执行 adapter 的有效 receipt 可避免再跑 Qlib；缺少 receipt 时现实现可能重新调用 pipeline。
新 hosted 编排须在调用前写 execution intent，并冻结 conservative stop 策略，不能推断“之前未执行”。
计算预算沿用已有 deterministic workload units，字段虽名为 compute_seconds，不声明真实墙钟硬预算。

## 实施落点与范围

新增建议文件：`contracts/hosted.py`、`application/hosted.py`、
`application/hosted_execution.py`（仅在适配需要时）、`infrastructure/hosted_service.py`、
`infrastructure/hosted_client.py`、`scripts/hosted_qualification.py`、
`scripts/verify_hosted_qualification.py`、`tests/unit/test_hosted*.py`、
`tests/integration/test_hosted*.py`。CLI 在 `src/quantos/cli.py` 接线。
HM-02 可以依据审查裁定更具体的最小文件分解；不得增加泛化多 runtime 框架。

契约保持只依赖 contracts/Pydantic/标准库；deterministic services 继续离线并复用 Qlib。
不增加数据源、开放 grammar、sealed confirmation、交易或 LLM 判定 gate。
ADR 后继记录仅允许新 `HM-MVP` profile 的 host-mediated 提案交接例外；
FR-03 `NO_GO / THIN_MAINTENANCE`、旧 SDK 9/9 门与 P14d-C `BLOCKED_UNIMPLEMENTED` 保留。

## 真实部署与 live 可达条件

HM-06 必须有独立 OS 身份或等效容器边界：服务安装和权威目录不受研究宿主写入，
输入投影只读且无 sealed/凭据，提交通道按 authenticated identity 与 campaign allowlist 授权。
同 UID 的 CLI/service 只能为功能演示。文件 hashes 不能证明权限隔离。

root 环境探测记录：`/usr/bin/bwrap` 存在；受限环境中
`--unshare-all --ro-bind / / --proc /proc --dev /dev /usr/bin/id` 被
`NETLINK_ROUTE: Operation not permitted` 拒绝；最小 `--unshare-user --unshare-pid` 探测可运行。
随后 root 经 `require_escalated` 的自动审批运行
`bwrap --unshare-all --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 --proc /proc --dev /dev /usr/bin/id`
成功，exit 0、uid 1000。此为 root 提供的环境观测，还需 HM-06 持久化 deployment probe 证据。
因此真实隔离部署可继续实施，不应先认定环境阻塞。QuantOS 服务可以采用 offline net namespace，
研究宿主使用独立 mount/pid 视图，仅挂载输入投影与受限 Unix socket，provider 网络仅在宿主侧。
同 UID namespace 方案须证明宿主无法通过 `/proc`、父进程/fd、mount 或 channel 越界；
若不满足，则采用更强身份/容器方案。此探测尚不是 Q07 正式边界通过证据。

root 还观察本机 `codex-cli 0.158.0` 可用，可评估为独立外部 hosted 客户端；
不修改 canonical SDK `0.154.0` 锁或借用其资格。baseline ruff 与 pyright 由 root 运行通过；
root 回报完整 pytest 为 `699 passed / 113 warnings / 210.22s`。
这是 root 观测，非 HM-01 执行；正式输出另存，且基线通过不授予 hosted 资格。

HM-08 的研究提案至少一次来自真实 `gpt-6-sol / high` 宿主调用，可观察身份/配置须留证；
不能用开发 agent 的口头身份、手写 response 或 Scripted fixtures 充当 live。
若服务隔离、真实模型交接或可信身份材料不可达，完成其余实现/离线验证，记录该门
`NOT_EVALUATED / deployment unavailable`；不得发布 hosted 资格，也不静默降为同 UID。

## HM-02 精确审查输入

主输入是本文件、[契约草案](hm01-contract-draft.md)、[验收草案](hm01-acceptance-draft.md)
以及 [输入清单](hm01-review-inputs.json)。对起点实际接口可只读取清单列出的代码，
不需要加载完整历史库。HM-02 输出独立 review、后继 ADR、关闭 blocking decisions 后的
冻结契约/矩阵 hash；此处提出的具体 policy 数值和恢复选择须在实施前接受。
