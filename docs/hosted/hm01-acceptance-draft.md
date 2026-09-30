# HM-01 Q01–Q12 验收与故障注入草案

日期：2026-09-29。状态：`DRAFT_FOR_HM02_REVIEW`。各项初始 `NOT_EVALUATED`。
这是测试设计而非通过记录；所有 PASS 由独立机械 verifier 从不可变工件重算。
模型/effort/attempt/usage 见 [基线](hm01-baseline.md)，语义见 [契约草案](hm01-contract-draft.md)。

建议 bundle root：`artifacts/hosted/<qualification-hash>/`。写入前以 staging 创建，
成功核验后 create-if-absent 发布；失败/拒绝 attempt 也保留单独不可变 bundle。
以下相对 evidence 路径在 HM-02 冻结并在 HM-07 映射到实际输出；不能事后只挑 PASS。

| ID | 驱动与故障注入 | 必须机械检查 | 最少 evidence |
|---|---|---|---|
| Q01 | start 无 response；退出进程；新进程 pending/status/resume 各两次 | 原 request bytes/hash/ordinal/ContextPack/到期时刻一致；一个 reservation；零 trial；查询不写新 artifact | `cases/Q01/{before,after}-inventory.json`、request、reservation、checkpoint |
| Q02 | 两进程 barrier 同时 submit 同 bytes；再重复；跨进程 resume | 同 receipt/hash，仅一个 accepted exchange/intent/event/trial；Qlib 调用计数无增加 | `cases/Q02/submissions.json`、receipts、execution intents/receipts、events、call-counter |
| Q03 | 独立错 campaign/ordinal/context/request hash/attempt；expired/cancelled 迟到；accepted 后不同 bytes 冲突 | 每 unique 响应拒绝 reason 与绑定/hash；原 acceptance 不覆盖；拒绝前后 deterministic root 无新增 | `cases/Q03/<case>/receipt.json`、before/after inventories、budget journal |
| Q04 | byte cap+1、UTF-8 invalid、duplicate JSON keys、unknown fields、非 canonical、unknown candidate、DSL/AST/parameters/fingerprints 越界、`../`/absolute/path/symlink/fifo | 有界读取/拒绝；sealed/projection allowlist 不扩张；已知 candidate schema-invalid 有原 accounting、未知不造 trial；credential-like reject payload 不落盘 | `cases/Q04/<case>/receipt.json`、bounded processing record、inventory、scan report |
| Q05 | 子进程在 reservation/request/checkpoint、submission/receipt/exchange、trial intent/STARTED、execution receipt、event、Ledger、STEP_COMPLETED/report 的 durable 边界退出 | 每窗口新进程恢复；有效 receipt 重用；无 receipt 的 STARTED 停止不重跑；完整分母/attempts 保留；损坏注入 fail closed | `cases/Q05/<window>/{pre,post}-inventory.json`、crash exit record、journals、receipts、call-counter |
| Q06 | 各预算分别设最小，达到 request/submission/trial/execution/compute 上限；取消 vs submit 并发；TTL 后 submit；restart | 停止边界无需模型判定；重复不收费；unique rejects 收费；cancel/expired 不退款；超过 cap 不累积无界工件；未记录 token/成本如实 unavailable | `cases/Q06/<budget>/accounting.json`、journal、termination receipt/report |
| Q07 | 在正式 host OS/container principal 中尝试写 authority/event/Ledger、读 sealed/canary credential、改 service wheel/source/config、绕 auth/campaign allowlist；symlink/race channel | 实际 syscall/API denied；记录 uid/gid/container/mount/install identity；服务仅冻结安装；同 UID 演示明确不合格 | `deployment/profile.json`、input projection inventory、`cases/Q07/probes.json`、service attestation、install inventory |
| Q08 | response 人工 model/policy_pass/usage/immutable=true；提供 fake attestation；缺 host transcript；真实 source 与 self-report不一致 | 自填字段不获 TRUSTED/qualification；schema forbid verdict；source authority不可宿主写；缺失按 null+原因/限制；没有 SDK伪manifest | `cases/Q08/observations.json`、rejection receipts、verifier provenance result |
| Q09 | 保存真实 response 后禁网新进程 replay；阻断 LLM/Tushare transport；篡改 request/response/receipt/result/event各一次 | 无模型/网络可完成底层 binding 与研究结果核验；各篡改定位失败；有效 execution receipt replay 不调用 Qlib | `replay/root-a/`、offline instrumentation record、`cases/Q09/tamper-results.json` |
| Q10 | 两个独立根复制同冻结输入和同真实 response，固定数值环境与 PYTHONHASHSEED；核验 raw + approved projection | principal identities 按冻结规则相同；raw inventories 各自精确绑定；仅批准顶层 created_at 投影；运输观测字段单独报告，不删差异 | `replay/root-{a,b}/inventory.json`、`comparison.json`、environment fingerprints |
| Q11 | 授权隔离宿主真实 model proposal→bytes submit→resume 至终态；不得 Scripted/手写 response | 至少一次真实调用来源/identity/config；完整 requests/attempts/候选分母/trials/executions/result/validation/events/Ledger/P14c；PIT/执行失败不借自然拒绝工程例外 | `live/host-observation.json`、request/response、exchange、receipt、campaign final report、P14c（适用） |
| Q12 | 旧 Scripted/Replay、PIT/Qlib/Validation/安全/contract/import regressions 与仓库 CI | 旧 profile 严格、contracts不依赖SDK/Qlib/Tushare、确定性阶段无LLM/Tushare、credential零留存；ruff/pyright/pytest禁网coverage≥85%；旧报告不自动授予新资格 | `checks/{ruff-format,ruff,pyright,pytest,diff-check}.txt`、regression report |

Q05 必须用新进程退出/恢复验证磁盘事实，不能只抛 mock 异常并复用内存对象。
子进程测试点应通过显式测试 hook 注入，生产请求不能指定故障 hook、任意执行代码或命令。
Q02/Q06 竞争检查必须跨进程 flock，不能以线程内锁测试替代实际部署并发。
Q07 由真实受限研究宿主运行，开发仓库的高权限会话只部署/管理/导出证据，不当作攻击身份。
Q11 模型请求材料来自冻结 request/input projection；模型不读 authority root，也不直接跑确定性服务。

HM-07 verifier 从 inventory 底向上核验 raw bytes/hash、schema、request→response→receipt→
candidate/execution identity、events chain 与 Ledger prefix、budget reconciliation、complete trials、
ResearchResult/ValidationReport/P14c、deployment/live来源，重算每个 Q 的 verdict。
不接收 host 报称 PASS。qualification manifest 必需包括 exact commit、lock/install/OS/libc/依赖指纹、
schema/contract/policies/input hashes、完整文件清单、各失败尝试、限制与 verifier result。
输出明确区分测试 PASS、campaign run_status/verdict 和 qualification eligibility。

Q11 自然结果允许无 eligible candidate；仅契约 C08 的完整 admissible soft-reject 允许工程闭环接受。
PIT/QLIB_EXECUTION_FAILED、artifact corruption、缺证、执行不确定作为负例可证明 fail-closed，但其
campaign 保持失败/拒绝，不能据此宣称 Q11 完整 live 闭环通过。
Q10 不要求再次 live 文本一致；replay 不替代 Q07 或 Q11。

正式 HM-06/Q11 环境不可达时，各门 `NOT_EVALUATED` 并说明环境缺口；整体
`NOT_QUALIFIED`。HM-09 必须审 exact commit 和 bundle，关闭阻塞后才授予资格；
HM-10/HM-11 发布只覆盖该接受记录的 profile/environment/inputs，保留 FR-03/P14d-C 旧状态。

HM-02 需冻结的阻塞决策：独立 hosted provenance 到业务 hash 的映射、conservative execution
uncertainty stop、submission cap/拒绝留证上限、取消/到期不自动重签、双根时间规则、soft-reject
例外、真实 deployment/authentication profile 和 live identity 可观察来源。
