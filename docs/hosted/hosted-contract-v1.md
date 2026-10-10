# Host-mediated MVP 冻结契约 v1

日期：2026-09-29。状态：`FROZEN_FOR_IMPLEMENTATION`。profile：`hm-mvp/v1`。
独立审查：[HM-02](../reviews/hm02-contract-review.md)；后继决策：[ADR-0003](../adr/0003-host-mediated-mvp.md)。
本契约只批准实施入口，不授予运行时资格。HM-03 至 HM-09 须证明实际符合性。
本文与[冻结验收矩阵](hosted-acceptance-v1.md)由 `hm02-freeze-manifest.json` 固定字节；
任何语义变更都须新版本与独立审查，不能原地重签本冻结记录。

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
超大正文最多读取 frame cap+1 bytes 后关闭该 frame；只保存 observed-prefix digest、
observed_bytes、complete=false 与固定 reason，不能把前缀摘要宣称完整 response hash。
同前缀超大请求可复用一份拒绝证据，但不能获得 acceptance；绝不无限 drain 或保存任意原文。
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
同时绑定已有 ResearchBudgetSpec。响应和 proposal 的 profile 硬上限均为 262144 bytes；campaign 可以明确选择更低值。
request 的硬上限为 1048576 bytes，必须在发请求前验证；请求次数还受 campaign policy 约束。
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

合法 natural soft rejection 工程接受由 C11 的明确谓词决定；只有批准的
`G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET` 拒绝 facts 可适用，不能继承历史较宽 allowlist。
Q07 或 Q11 未执行/未通过时整体 hosted qualification `NOT_QUALIFIED`，不由 replay 替代。

## C09 HM-03 / HM-04 的实现边界

`contracts/hosted.py` 提供独立 envelope、budget、receipt、journal、execution intent 与
observation 契约；禁止依赖 runtime/SDK/Qlib/Tushare。复用 canonical primitives，所有外部
JSON 必须先检查 duplicate keys、非有限数、UTF-8、大小，再严格 schema validate 并逐字节
比较 canonical serialization；不能依靠会丢弃 duplicate keys 的普通 json.loads 判定。
proposal text 必须保持其原始 UTF-8 bytes，禁止 strip 后重新计算为另一个 proposal。

`HostedCampaignSpec` 的 campaign hash 指向已有 ResearchCampaignSpec 的 authority hash；
另有 hosted spec 自身 content hash，两个身份不能混用。Host request 同时绑定这两个身份。
允许复用完整 AutonomousAgentRequest 作为 business_request；其配置只表示请求配置，
不能因此产生旧 manifest 的有效策略声明。选择独立 business structure 时，必须等价绑定
原 request 的候选、ContextPack、budget、policy 和 input hashes，HM-07 用错绑负例验证。

Hosted exchange 是服务发布的不可变 `hosted-agent-exchange/v1` 对象，至少含：
request_hash、response_hash、proposal_hash、authenticated_principal、host_observation_hash、
provenance_kind=`HOSTED_EXCHANGE`。其 content hash 是 hosted run identity。
Accepted receipt 引用该 exchange hash，exchange 不反向引用 receipt，避免 hash cycle。
receipt 的预算前/后 hash 指向独立预算 journal facts，不能让 journal 再依赖含自身 hash 的 receipt。
Journal intent 中固定 operation payload（包含预定时间），完成事实引用已发布 artifact hashes。
所有 source authority 属于服务观察/可信 launcher，不属于 response 内自报值。

业务适配可以提取已有编排中的纯 admission、trial identity、execution request、Ledger 和
selection 逻辑，也可新增窄 hosted 编排调用这些服务；不得建设泛化 runtime 框架。
适配使用 `agent_run_hash=hosted_exchange.content_hash`，并在新 profile 的 exchange lookup、
trial 校验及报告里验证 `HOSTED_EXCHANGE` 来源。旧路径继续查旧 exchange/manifest；
不得把 hosted bytes 包成 AgentRunManifest、不得令 usage=0 通过旧 driver，
不得跳过或放宽 `_validate_response`，不得从现有 ScriptedAgentDriver 借假 manifest。
旧 Scripted fixtures 的既有显式 fixture 身份不因此改写。

应用入口最少提供 `start(spec_hash)`、`pending(campaign_hash)`、`status(campaign_hash)`、
`submit(request_hash, response_bytes, authenticated_principal)`、
`resume(campaign_hash)`、`cancel(request_hash, authenticated_principal)`。
配置/输入只能由服务预注册 hash 解析；这些入口不接受 service root、任意路径或代码。
start/resume 返回 persisted checkpoint 或完整终态；等待不是研究失败。
CLI 是这组应用接口的薄客户端，网络服务与本地受控管理工具共用校验实现。

MVP 的 `reissue` 固定 false；不存在重新签发旧请求的管理后门。
同字节 accepted/rejected replay 必须先查原 receipt，再检查当前 TTL/cap；取消、到期、耗尽
不能让原幂等 receipt 失效。此前未见的响应才受当前接收资格/预算限制。
每个 request 发布一个固定 exhaustion receipt；campaign 总额耗尽也只有一个固定 terminal
receipt。达到上限后的新输入只返回这些 receipt，不能产生无界 authority 文件。
已接受请求的冲突响应在 allowance 内留证，超过 allowance 返回 exhaustion；原 acceptance
永久保持。transport reject 不形成 trial；完整 canonical envelope 内可识别冻结 candidate 的
proposal schema/DSL/fingerprint 错误可先接受 transport，再由 admission 形成 SCHEMA_INVALID。

所有 reservation、STARTED、receipt 的原子发布均须文件和父目录 fsync 后才可推进；
flock 文件是稳定 service-owned inode，不允许删除重建导致两把锁。
拒绝 symlink、非普通文件、hard-link authority alias、路径穿越；以目录 fd/openat 等方式
约束实际解析，不能只检查字符串后另行打开。只保证本地 POSIX 文件系统与固定 profile；
不声明敌对内核、磁盘损坏后继续运行、跨机器事务或物理 exactly-once。

## C10 HM-06 的部署与 live 来源

冻结逻辑部署 profile 为 `hm-isolated-service/v1`：服务拥有 authority/install/config，
服务网络 namespace 离线；研究宿主仅挂载冻结安装的只读客户端、只读 input projection、
受限 Unix channel 和运行必需的独立临时目录。host 模型网络仅在提案阶段。
精确 executable/install/OS/mount/namespace/channel hashes 和身份在首次运行前另以不可变
DeploymentProfile 绑定，不允许先运行再补选 profile。bwrap 或独立 UID/容器均可实现该
逻辑 profile，但每一实际组合须通过 Q07；此处没有授予 bwrap 产品通用资格。

同 UID 的 namespace 部署只有在 mount/pid/proc/fd 边界实际阻断 authority、父进程、
服务安装、sealed 与采集凭据访问时才能通过。共享 UID 的 host shell 和普通本地 CLI
不满足此条件。channel 使用服务观察的 peer credentials 加绑定该 host 实例/campaign 的
不可伪造 capability（或等价 OS 身份授权）；peer UID 相同本身不够区分容器。
capability 不是 acquisition credential，仍不得写入日志/证据；验证记录只保存脱敏身份。
必须约束 frame size、超时、连接数和 principal 的 campaign allowlist；拒绝任意路径参数。
无 authenticated identity 的请求在查询 campaign 前拒绝。

服务以冻结安装执行，不从研究宿主可写 checkout、环境 PYTHONPATH、插件目录或用户
site-packages 导入；清理继承环境、非必要 fd，限制 /proc 视图与父进程访问。
开发会话是部署管理者，不是受限研究主体；Q07 必须从实际研究主体发起 syscall/API probes。
真实 token 不进入证据；凭据 probe 使用已知非秘密 canary，或只记录路径访问被拒事实。

允许独立外部 Codex 会话使用系统 CLI 作为宿主客户端；安装探测到的 0.158.0 仅是候选，
实际版本、binary hash 和启动配置须被 DeploymentProfile 绑定。QuantOS 不因此启动或管理
LLM runtime，旧 CLI backend 不被重新启用，canonical SDK/runtime pin 0.154.0 不变。
外部可信 launcher（部署管理域，研究宿主不能写其证据根）记录：实际 executable hash/version、
模型和 effort 的请求 argv/config hash、request/input projection hash、隔离 identity、
进程启动/终止观察、provider/CLI 产生的可得模型 identity、原始输出 digest、抽取 proposal
bytes/hash、终态 exit code 与来源标记。使用 launcher's pipe 捕获输出；不能只接收宿主上传的
“可信 transcript”。固定输出提取规则需预注册并保留原始安全输出，不能人工补写 proposal。
完整 transcript 不可得时明确部分 observation；credential scanner 在任何持久化之前执行。

该可信观察只证明启动了哪个可执行文件、请求了什么、实际收到什么。它不证明 provider 内部
effective sandbox/permission policy、不证明模型 snapshot 不变、不证明隐藏模型调用次数。
自报 identity 与 launcher/CLI 实际可见 identity 冲突则 Q08/Q11 失败；只有 requested model
而没有真实模型交接来源也不能通过 Q11。研究模型默认 `gpt-6-sol/high`，替代须先记录并独立
评审新 profile，不能静默切换。usage 无可信来源时 null+reason，费用和 hidden retries 不声明硬门。

## C11 Q09 / Q10 时间与终态规则

Q09 在已有完整执行 receipt 的保存根中验证和恢复：不得再调用 Qlib，不得调用网络/模型。
Q10 在两个全新 authority 根中使用同一冻结 inputs 与**保存的** live 协议 authority bytes，
各运行一次确定性研究 pipeline，独立重建 execution/results/events/Ledger/P14c/report。
两个根不得复制已有结果当作重执行。第三个模式是 Q09 receipt reuse；两种模式分别报告。
离线重建导入已验证原 request/response/exchange/receipt/journal 序列，保留原 issued_at、
expires_at、submission time、principal 和 budget identity；它不是重新 live submit，不绕过
线上 TTL/auth 门。只能由离线 verifier 的受控导入使用，不能暴露研究 channel replay-import。

业务事件时间沿用冻结 campaign anchor 与既有 deterministic event ordering；原 transport
时间逐字节保留。重建耗时、运行时间和当前 replay OS principal 属于单独 observation，不得
替换保存的 authenticated principal。环境固定 `PYTHONHASHSEED=0` 且进程入口验证
hash_randomization disabled，绑定相同依赖/数值环境；进程启动后 setenv 不算符合。

每根首先 raw inventory 精确验证，比较时仅如下已解析且 authority hash 校验成功的 schema
允许去除 JSON **顶层** `created_at`：`signal-artifact-manifest/v2`、
`backtest-artifact-manifest/v1`、`research-result-manifest/v1`、`qlib-view-manifest/v1`、
`data-snapshot-manifest/v1`、`research-ledger-snapshot/v1`、`event-signal-artifact-manifest/v1`。
该规则仅用于这些 authority 对象的 inventory comparison projection，并记录每个实际投影
path、schema、raw hashes 和 projected hash；原始文件不改写，不能仅凭同名字段匹配。
这七种 schema 既有 content-hash 算法本就排除 created_at；source input 仍须 raw input hash
匹配。其他 JSON（尤其 hosted request/receipt）、nested timestamp、身份、输入、verdict、
预算、路径、事件和输出数据一律不投影。未知 schema/额外差异 fail closed，不能运行后新增
忽略字段。qualification observation/runtime inventories 不纳入 principal equality，但仍由
各自完整 qualification manifest 绑定；清单路径、root-specific runtime 记录须显式区分。

Q11 正常接受要求全冻结候选恰好一个完成的自然研究 trial（额外无效/重复 attempts 全部另计），
每候选有 bottom-up verified execution receipt、ResearchResult、ValidationReport 和完整
适用 sidecars，最终 P14c 与全量分母、Ledger 对账。存在 eligible 时保留 P14c 原结果。
零 eligible 的工程例外只允许每份 ValidationReport run_status=SUCCEEDED、verdict=REJECT，
冻结的十一 gate 顺序/集合/严重性完全一致；G0/G1/G2/G9/G10 HARD 均 PASS、G4 PASS，
无 NOT_EVALUATED，**唯一可 REJECT 的 gate 是 G5_OUT_OF_SAMPLE、severity=SOFT、
reason=SOFT_THRESHOLD_NOT_MET，且至少有一个该拒绝**，其余 gate PASS。
每候选 P14c disposition=NONPASS_VALIDATION、无 eligible score；P14c 真实自然终态保持
FAILED/NOT_EVALUATED/SOURCE_INCOMPLETE，selection_performed=false，不得改成 NO_SELECTION。
若一个或多个候选 PASS、其余符合上述窄拒绝谓词，可按原 P14c 规则选择。
任何 artifact/PIT/execution/source/sidecar/预算缺口、未完成候选、sealed 访问、不确定执行
都不适用例外。不得按 trial aggregate SOFT_REJECT 一项判定，也不得改写任何历史失败。

HM-02 的冻结批准不是 HM-09 的资格批准。Q01–Q12 每项真实通过、精确 clean commit 与
完整 bundle 独立审查接受后，才可发布这个 profile/environment/input 范围内的 HM-MVP 资格。

HM-03 仅实现 protocol contracts/store/journal，不先实现完整研究编排；HM-04 接入业务。
现 `QuantosResearchExecutionAdapter.execute` 在无 receipt 时可运行 pipeline，不能用它
探测 STARTED 的完成状态。HM-04 应增加窄 public `verified_completed_execution(request)`
或等效接口：只验证/返回已完成 receipt，不执行模型/Qlib，不制造缺失 receipt；若底层
读取需要补 content-addressed 索引，其可恢复 mutation 必须显式记录，不能假称纯读取。
不存在有效 receipt 时按 C07 停止；不要让 hosted 层猜测调用私有 `_read_receipt` 的副作用。
