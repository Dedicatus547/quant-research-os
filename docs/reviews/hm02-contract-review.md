# HM-02 独立契约与部署边界审查

日期：2026-09-29。结论：`APPROVED_FOR_IMPLEMENTATION / NOT_QUALIFIED`。
模型：`gpt-6-astra`；reasoning effort：`high`；attempt：1；usage：`unavailable`。
该独立审查只覆盖固定设计输入与必要实际接口；不执行 HM-03–HM-11，不授予 runtime 资格。

## 固定输入与方法

HM-01 输入清单 `docs/hosted/hm01-review-inputs.json` SHA-256：
`5b5460065cda5f15c3cae2377b7fee7c26ca29623cfaa1f7011e624eca5522e4`。
其 25 项文件的 size/hash 已逐一通过本地重算；起始 commit 为
`d6c77055eaa4844a2e0d9423990475ef23dce15c`。审查输入保持原样，另发布冻结 v1，
不修改历史 ADR-0002、用户 docs/README.md 或用户 roadmap。

审查读取三份 HM-01 文档及 AGENTS/roadmap，核对 `_validate_response`、
AgentUsage/AgentRunManifest、AutonomousExecutionRequest、proposal admission、trial/hash、
Ledger reconcile 与 deterministic adapter 边界；另核对 P14-DQ gate 谓词及已记录的
principal-equality created_at 语义。新增实际读取文件单独记录在冻结清单 supplemental_inputs。
基线 699 tests、ruff、pyright 和 bwrap/CLI 可达性为 root 提供的观测；本审查没有复跑，
不会把它们称为正式 Q07/Q11 证据。

## 阻塞发现与关闭裁决

| 项 | 初稿风险 | 冻结裁决 / 关闭证据 |
|---|---|---|
| B01 | 旧 AgentRunManifest 必需 usage，直接复用 driver 会伪造来源 | C03/C09 独立 envelope/exchange；HOSTED_EXCHANGE hash 经窄业务适配；禁止假 manifest/usage=0，旧 validator 严格；Q08/Q12 |
| B02 | 多文件操作、重试/过期/cap 可能破坏幂等 | C04/C09 journal intent/complete、稳定 flock+fsync、先查旧 receipt、固定 exhaustion；Q02/Q03/Q05/Q06 |
| B03 | execute 无 receipt 会再次启动 pipeline | C07 STARTED 无有效 receipt 保守停止；C11 后窄 public completed-execution verifier；Q05 |
| B04 | 超大请求的无限 streaming digest 或拒绝文件可能无界 | cap+1 截止、prefix complete=false、有界 receipt/reservation、双提交 cap；Q04/Q06 |
| B05 | 同 UID / namespace、可信来源或系统 CLI 边界含糊 | C10 受限 host 身份+mount/pid/proc/fd probes、authenticated channel、冻结安装；外部 CLI 仅host客户端；ADR-0003；Q07/Q08/Q11 |
| B06 | 自报模型配置会被误称 actual policy，缺 transcript 却宣称 live | C10 管理域可信launcher直接观察输出并绑定proposal；明确 source/缺失与限制，不证明effective policy/snapshot；Q08/Q11 |
| B07 | 双根时间投影不够精确，可误删协议权威字段 | C11 区分receipt reuse和全新根重执行；保存协议时间/principal原字节；七schema顶层created_at allowlist，其他差异拒绝；Q09/Q10 |
| B08 | soft-reject适用性未裁定，易借自然失败掩盖工程缺口 | C11 正向十一gate完整谓词，只允许G5 SOFT_THRESHOLD_NOT_MET，完整全候选/sidecar/P14c分母，研究结果原样保留；Q11 |
| B09 | 自动重签可重置预算或修改原请求 | C06/C09 reissue=false，cancel/expiry不退款，resume停止，原attempt保留；Q06 |

上述属于设计阻塞，已通过窄化与明确规范关闭；实现与部署门仍待真实执行。
root 已明确同意独立hosted业务来源、conservative stop、窄G5例外、双根两种模式和外部CLI
例外的裁决。接受范围不包含未实现接口的 correctness、权限已强制或真实模型已运行声明。

## 冻结与实施交接

- [hosted-contract-v1.md](../hosted/hosted-contract-v1.md)：C01–C11 与窄恢复接口。
- [hosted-acceptance-v1.md](../hosted/hosted-acceptance-v1.md)：Q01–Q12、必备工件和机械断言。
- [ADR-0003](../adr/0003-host-mediated-mvp.md)：明确外部宿主例外和保留的历史边界。
- [hm02-freeze-manifest.json](../hosted/hm02-freeze-manifest.json)：输入、补充读取及本次冻结文件 hashes。

HM-03 从 contracts/hosted.py 和 protocol pending/receipt/journal store 开始，只实现 C01–C04、
C06 的协议部分与 C09，不提前复制完整 business orchestrator。HM-04 接既有 deterministic
execution / admission / Ledger / P14c，用独立来源适配；不能靠假旧 response 过门。
HM-06 与 HM-03 契约协同：先冻结安装/projection/channel/deployment inventory，再从真实
研究主体执行 Q07，trusted launcher 留存真实来源。具体内部文件组织由实施者决定，不能
改变冻结语义。HM-07 完成全矩阵机械 verifier 后，HM-08 才运行固定真实闭环。

更改已冻结字段含义、source authority、预算/恢复/资格谓词或投影集合须发布后继版本与
独立审查，保留本次 bytes；不能运行后重签同名契约。实现可以增加非权威索引或内部辅助
结构，但不能新增绕门入口。未通过 Q07/Q11 或独立 HM-09 时整体保持 NOT_QUALIFIED。
