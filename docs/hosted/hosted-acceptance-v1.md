# Host-mediated MVP 冻结验收矩阵 v1

日期：2026-09-29。状态：`FROZEN_FOR_IMPLEMENTATION`。各项初始 `NOT_EVALUATED`。
这是测试设计而非通过记录；所有 PASS 由独立机械 verifier 从不可变工件重算。
独立审查记录见 [HM-02](../reviews/hm02-contract-review.md)，语义见 [冻结契约](hosted-contract-v1.md)。

固定 bundle 布局：`artifacts/hosted/<qualification-hash>/`。写入前以 staging 创建，
成功核验后 create-if-absent 发布；失败/拒绝 attempt 也保留单独不可变 bundle。
以下相对 evidence 路径为逻辑布局，HM-07 必须以 machine-readable case inventory 精确映射到实际文件/hash；不能事后只挑 PASS。

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
| Q09 | 保存真实 response 与协议 authority 后禁网新进程 receipt-reuse replay；阻断 LLM/Tushare transport；篡改 request/response/receipt/result/event各一次 | 无模型/网络可完成底层 binding 与研究结果核验；各篡改定位失败；有效 execution receipt replay 不调用 Qlib | `replay/root-a/`、offline instrumentation record、`cases/Q09/tamper-results.json` |
| Q10 | 两个全新根导入同冻结输入/保存协议，分别重执行确定性链（不复制已有结果），固定数值环境与 PYTHONHASHSEED；核验 raw + approved projection | principal identities 按冻结规则相同；raw inventories 各自精确绑定；仅 C11 七种 schema 的顶层 created_at 投影；运输观测字段单独报告，不删差异 | `replay/root-{a,b}/inventory.json`、`comparison.json`、environment fingerprints |
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

Q11 自然结果允许无 eligible candidate；仅契约 C11 的完整 admissible soft-reject 允许工程闭环接受。
PIT/QLIB_EXECUTION_FAILED、artifact corruption、缺证、执行不确定作为负例可证明 fail-closed，但其
campaign 保持失败/拒绝，不能据此宣称 Q11 完整 live 闭环通过。
Q10 不要求再次 live 文本一致；replay 不替代 Q07 或 Q11。

正式 HM-06/Q11 环境不可达时，各门 `NOT_EVALUATED` 并说明环境缺口；整体
`NOT_QUALIFIED`。HM-09 必须审 exact commit 和 bundle，关闭阻塞后才授予资格；
HM-10/HM-11 发布只覆盖该接受记录的 profile/environment/inputs，保留 FR-03/P14d-C 旧状态。

HM-02 已在冻结契约 C09–C11 关闭上述设计阻塞；没有实际执行任何 Q 门。

补充机械断言（与上表共同构成验收，不得任选）：

| ID | 冻结补充断言 |
|---|---|
| Q01 | hosted_spec_hash 与 campaign_hash 不混淆；status 的 projected expiration 不写 authority；request cap 发出前验证 |
| Q02 | 同字节拒绝也幂等；已接受 receipt 在 TTL/cap 后仍相同；稳定 lock inode，跨进程检查 |
| Q03 | 未见 late bytes 拒绝；已 seen bytes 返回旧 receipt；accepted 后 cancel 拒绝 |
| Q04 | 超大 frame cap+1 后截止，prefix digest 明确 complete=false；不因相同前缀获得 acceptance；symlink/hardlink/FIFO/TOCTOU 负例 |
| Q05 | durable STARTED 后未真正调用的窗口也 EXECUTION_UNCERTAIN；不能用“很可能没执行”退款；文件/目录 fsync 窗口、journal 碎片/错序/双 pending/孤立 artifact 可检测 |
| Q06 | campaign+per-request submission 双 cap；拒绝/冲突计数；固定 exhaustion receipt 不无限创建；reissue=false；compute 是原 deterministic workload units 非墙钟硬预算 |
| Q07 | namespace 同 UID 不能仅 SO_PEERCRED 判断；probe 父/proc/fd escape、只读安装、PYTHONPATH/插件和非法 campaign capability；正式网络隔离与实际研究host身份绑定 |
| Q08 | 独立 hosted exchange 来源；旧 manifest 没有任何 usage=0/profile 伪造；fake launcher record 因来源根不可信失败；requested 与实际来源冲突失败 |
| Q09 | 保存原 timestamps/principal/receipt hashes，不重新 live submit；任何离线 import 不出现在研究 channel；已有receipt recovery的 Qlib 调用增量为0 |
| Q10 | 两根各执行一次 Qlib pipeline、独立重建 events/Ledger/P14c；原 protocol不改；七schema投影逐文件列出；嵌套/未知schema created_at 变更失败；raw inventory仍必须验证 |
| Q11 | 可信launcher直接捕获真实模型输出并绑定proposal，不能人工补写；完全遵守 C11 正向十一gate谓词；研究失败与工程门分别记录 |
| Q12 | 旧_validate_response严格回归包括伪hosted manifest拒绝；contracts依赖隔离；既有699测试只是基线，新增实现必须重跑适用CI |

HM-03 退出：版本化 envelope、稳定锁/原子 store、pending、所有类型 receipt 与 budget journal
通过 Q01–Q04 的组件用例；无伪 SDK manifest；故障恢复结构足以实现 C07。
HM-04 退出：Q05/Q06 的持久化状态机、execution uncertainty、trial 与 Ledger 对账可验证。
HM-06 退出：精确 DeploymentProfile、冻结只读安装/投影、受限 channel、实际 Q07 probes 与
trusted launcher source 留存；环境不可达只能 NOT_EVALUATED，不把设计审查当通过。
HM-07 退出：离线 verifier 独立重算 bindings、accounting、gate facts、raw inventories、Q verdicts；
其输出不得信任案例自填 PASS，负例及其 before/after artifacts 可独立重建。
HM-08 退出：冻结输入的一次真实闭环、两根重执行、receipt reuse 与完整 bundle。
HM-09 退出：独立 exact-commit/bundle review 无未关闭阻塞，再发布接受记录；HM-10/HM-11
只使用该记录的事实。各任务记录 assigned model/effort、attempt count、observed usage 或 unavailable。
