# HM-01 Host-mediated 契约草案

日期：2026-09-29。状态：`DRAFT_FOR_HM02_REVIEW`。profile：拟议 `hm-mvp/v1`。
本文 schema、状态和文件布局均为设计，尚未实现或资格化。模型/effort/attempt/usage 见
[基线记录](hm01-baseline.md)。批准前不能删除失败门或将限制改写为通过。

## C01 身份与 canonical bytes

每个对象使用独立 `hosted-*/v1` schema，`extra=forbid`，SHA-256 与
`CanonicalContract.canonical_bytes()`。所有大小以 UTF-8 bytes 计，不以字符数计。
响应必须是 canonical JSON，拒绝重复 JSON keys、非有限数、未知 schema、可执行代码或路径字段。
服务在读取正文前实施 frame byte cap；hash 由服务重算。request hash 对 envelope 本体取 hash，
不在被 hash 本体内放自指 request_hash。CLI 的 `--request` 是该外部 hash。

新 `HostedCampaignSpec` 冻结 campaign/family/budget/candidate manifest、initial Ledger、
snapshot、Qlib view、Evidence、selection plan、execution bindings、Context policy、
model request configuration、deployment profile、contract/acceptance hashes 与起始时间锚点。
所有路径均为服务本地配置，不接受宿主路径。起始输入全部 reverify 后才允许发请求。

## C02 请求与读取权限

`HostedAgentRequest` 绑定 schema/profile、campaign_hash、transport ordinal、
业务 `AutonomousAgentRequest`（或严格等价独立业务结构）、其 hash、ContextPack hash、
candidate manifest hash、排序 input hashes、policy hashes、budget reservation hash、
proposal schema hash、max request/response/proposal bytes、服务生成 attempt identity、
投影 object hashes allowlist、issued_at 与 expires_at。

同 campaign 仅一个 active request。transport ordinal 来自不可变 request journal，
与旧 campaign agent_run_count 分开。pending 保存原 request bytes，不因查询时钟/Ledger 重建 request。
恢复检测冻结输入或 Ledger 非法改变即拒绝；不会用新请求替换旧 ordinal。
宿主只能按 hash 读取服务导出的 request 与 ContextPack allowlist 对象，不能提交任意文件路径。
allowlist 不含 sealed 或采集凭据；完整 canonical snapshot 不必暴露给模型。

## C03 response 与来源

`HostedAgentResponse` 绑定 schema、request_hash、campaign_hash、transport ordinal、
ContextPack hash、服务生成 attempt identity、proposal UTF-8 text/hash，以及有界
`HostObservation`。request 中的 campaign/context/ordinal 不能仅由 proposal 间接绑定。
HostObservation 将 requested configuration、host reported identity/usage、
服务观察的 authenticated principal、可信外部 evidence references 与 unavailable reasons 分开。
缺失 token、成本、transcript、immutable model snapshot 时为 null + 原因，不能填 0。

宿主报称的 model、usage、permission pass 均为 `HOST_REPORTED`，不构成 attestation。
可信 source 类型须由冻结服务 verifier 支持并从宿主不能写的证据根读取；response 不能自己
宣布 `TRUSTED`。至少声明 `HOST_INTERNAL_USAGE_UNAVAILABLE`、
`HOST_EFFECTIVE_POLICY_NOT_ATTESTED` 与 `MODEL_IDENTIFIER_NOT_IMMUTABLE` 中实际适用的项。
完整 transcript 不可得时保留协议 exchange 并明确缺失理由，不称其为完整宿主 transcript。
研究 live 门需要真实 host 调用证据与可观察实际配置；token 硬门不属于默认 MVP。

独立 hosted validator 验证 response 后得到 hosted exchange/run hash，它只证明协议提案身份。
该 hash 可以作为现 execution request/trial 的 agent_run_hash，但 qualification 必须标明
它是 `HOSTED_EXCHANGE`，不称 SDK transcript。业务适配点不得伪造旧 AgentRunManifest 的
usage、policy 或 SDK runtime；原 Scripted/Replay `_validate_response` 语义保持严格。

## C04 收据与并发

服务为每个 bounded unique submission 发布 `HostedSubmissionReceipt`：request_hash、
submission bytes hash、attempt identity、ACCEPTED/REJECTED/CONFLICT、reason、
accepted exchange hash（若有）、预算前后 journal hashes、固定服务时间与 authenticated principal。
同 request 的同字节重复响应，包括已留存拒绝，返回原 receipt、无新计数/业务效果。
不同字节重复已接受 request 为 CONFLICT；保存有界 hash/receipt，不覆盖先前 acceptance。
response 被接受仅表示 transport 绑定通过；proposal admission 与研究 gate 独立。

每个 campaign 采用稳定真实目录 flock；create-if-absent 与 canonical hash verification；
所有 authority artifacts 不覆盖。append-only journal 使用 sequence/previous-hash 和
operation id，构成 committed facts；可重建 index 不作为单独权威。多文件写入不声称事务。
每次 mutation/recovery 核验序号连续、hash/路径、symlink、重复 ordinal 与 campaign 单 pending。
同服务 root 支持并发进程；不声明 NFS/跨机器锁或可损坏文件系统的 durability。

未认证/不授权 channel 请求在解析/读取 campaign 前拒绝，rate/frame bounded，不产生研究 trial。
对已授权 request 在 submission cap 以内，schema/hash/绑定/候选错误都有 immutable receipt。
达到 cap 后返回预先发布的 EXHAUSTED receipt，不继续累积无限拒绝文件。
超大正文只保存 streaming digest/observed byte bound/固定 reason，绝不留任意原始内容。
拒绝 evidence 不留明文 credential-like payload；沿用 credential zero-output/zero-retention scanner。

## C05 状态与 accounting

| Transport state | 权威事实与业务影响 |
|---|---|
| REQUEST_READY | reservation 与完整请求已发布；不产生 trial |
| WAITING_FOR_AGENT | checkpoint 已发布，进程可退出；status/pending 只读 |
| RESPONSE_ACCEPTED | receipt/exchange 完成；还未承诺 admission 或 Validation PASS |
| EXECUTION_PENDING | 冻结 candidate/trial intent 与 execution identity 已发布 |
| STEP_COMPLETED | receipt、trial event、Ledger 全部对账，可下一 request |
| CANCELLED / EXPIRED | 请求不再接收；记录 reservation，拒绝迟到响应；不虚构 trial |
| RECOVERY_REQUIRED / FAILED | authority 损坏或执行不确定，停止推进，保留原证据 |

候选在冻结 manifest 且可独立解析时，schema/DSL/fingerprint 错误沿用 SCHEMA_INVALID trial；
重复候选沿用 DUPLICATE_CANDIDATE；合法 proposal 调现执行 adapter。未知候选/无 candidate
属于 transport/admission 拒绝，无 research trial，但消耗 unique submission allowance。
PIT 为硬拒绝；执行失败为 `FAILED / NOT_EVALUATED`；failed/rejected attempts 留存。
完整候选分母不能因拒绝、预算停止或取消消失，最终报告列出 attempted/remaining 全量候选。
不完整闭环不得借用合法软拒绝例外，不能称工程 SUCCEEDED。

## C06 预算、取消、过期

默认冻结 `HostedBudgetPolicy`：正整数 max_requests、max_unique_submissions（campaign 总额）、
max_submissions_per_request、max_response_bytes、max_proposal_bytes、request_ttl_seconds；
同时绑定已有 ResearchBudgetSpec。建议 bytes cap 262144，request cap 沿用 campaign policy。
具体次数与 TTL 在 campaign input 中显式给出，禁止 mutable/default auto resolution。

发 request 前原子 reservation 消耗一次 request allowance，不能取消/过期后退款。
请求自身由服务分配一次 attempt identity；该 reservation 只约束协议请求，不证明内部模型调用次数。
unique submissions 接收前预留一次；重复 bytes 复用原 reservation。rejected/conflict 计数保留。
status/pending/restart 不收费。execution/trial/compute 各按现业务 policy 与 intent 预留/结算，
无法证明未执行的失败 intent 不退款；预算达到上限停止，不重置。

cancel 仅在未 accepted 的请求由 authorized caller 发布不可变取消 receipt，和 submit 争锁，
赢家决定状态；accepted 后 cancel 拒绝，不暗中撤销 authority。到期时刻冻结在 request 中，
可信服务时钟判断；submit/resume 可以发布 EXPIRED，status 保持只读并报告 projected expiration。
重新签发是新 ordinal/request reservation，不改变原请求；MVP 不自动重签，显式 resume
按冻结 `reissue=false` 停止 campaign 并记录 CANCELLED/EXPIRED 终止原因。

## C07 崩溃窗口与恢复

| 崩溃后证据 | 必需恢复动作 |
|---|---|
| reservation 有、request 未完成 | 由已冻结 operation payload 补齐相同 request；若无法证明 bytes 则停止，不退款 |
| request 有、checkpoint 缺失 | 复用 request，补 checkpoint；不创建新 ordinal |
| submission intent 有、receipt/exchange 片段 | 校验保留 response；补相同 immutable artifact/receipt，不能接受第二响应 |
| accepted exchange 有、trial intent 缺失 | admission 按冻结 candidate 身份运行，写 trial/execution intent |
| execution intent 为 PREPARED、未写 STARTED | 可开始一次执行；STARTED 必须先 durable，再调用 execution_port |
| STARTED 有、有效 execution receipt 有 | bottom-up verify，复用 outcome，禁止再跑 Qlib；补 event/Ledger |
| STARTED 有、无有效 receipt | `RECOVERY_REQUIRED / EXECUTION_UNCERTAIN`，保留 reservation 与 intent，默认不重跑 |
| event 有、Ledger 缺少节点 | 已有 reconcile 补相同 deterministic object/event；不新增 trial |
| Ledger 完成、step/final report 缺失 | 基于已验证 facts 补相同 completion/report |

exec STARTED 后未调用就崩溃也按不确定停止，这一保守选择会牺牲可用性，避免无证据重复执行。
不承诺物理恰好一次。所有时间来自 frozen campaign/event anchor 与原始 stored timestamps，
重启时钟不重写 principal evidence。损坏、缺失、双重事件、Ledger 冲突均 fail closed。

## C08 部署、replay 与工程接受

固定服务部署 profile 绑定服务 OS/container identity、wheel/source-install/lock hashes、
只读安装位置、权限、input projection inventory、authority roots 与 channel authentication。
服务不从研究宿主可改的 checkout 执行；不接收 arbitrary command/Python/plugin/path。
HM-06 真实 host 身份执行越权读写/修改/绕入口 probes，实际拒绝并绑定环境记录。
credential probe 使用非秘密 canary 或 inode/path-access 检查，不读取真实 token 值。
隔离 host 不能读取真正 sealed object；projection 本身不含 sealed，deterministic service 也不开放此入口。

默认 live 首次 profile 使用 `gpt-6-sol / high`，host 与开发任务分别记录角色。
保存真实 response 的 replay 无 LLM/网络；第二独立根绑定同冻结输入/时间与 response bytes。
principal evidence（请求/response/receipts/预算/执行/事件/Ledger/result/report）按冻结规则一致。
不投影身份、输入、verdict、预算或任意路径；仅明确允许的 manifest 顶层 created_at 可投影。
raw inventories 各自保留，protocol submission time 等 transport observation 若不同须独立列出。

合法 natural soft rejection 工程接受拟沿用 P14-DQ v3 的严格条件：全候选、完整 execution/
ResearchResult/ValidationReport/receipt、只有批准 `G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET`
facts，未触 sealed，无 artifact/PIT/execution/source 缺口。HM-02 必须明确批准其 hosted 适用范围。
Q07 或 Q11 未执行/未通过时整体 hosted qualification `NOT_QUALIFIED`，不由 replay 替代。
