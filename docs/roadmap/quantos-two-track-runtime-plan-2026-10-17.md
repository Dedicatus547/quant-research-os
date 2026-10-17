# QuantOS：固定发布运行线与 Codex 开发线

日期：2026-10-17。状态：原件只读审计及规划；本轮未实施源码、运行测试/资格矩阵、调用研究模型、启动科学任务、安装、部署或推送。
遵守 [AGENTS.md](../../AGENTS.md) 与[实施约定](../guides/implementation-discipline.md)。历史契约、接受记录、失败及原件不变。

**后继实施核对（2026-10-17）：最小有界版的本机正常路径已完成工程接受。**
固定源码 `29fef56f303fa25ed19a82a7cc1286426d666df5` 完成两轮真实 SDK、两次科学执行、
反馈传递、预算结算与清理；D0/D1/D2 采用薄准备器/既有状态机/原 namespace helper，
D3 复用定向离线结果，并由同一次真实运行及接管原件核对覆盖正常交付路径。
完整身份、逐项完成范围与缺证条件见[完成核对](../releases/agent-runtime-bounded-v1-2026-10-17.md)。
剩余边界为本机保留环境、冻结两候选、一般恢复/跨宿主未证；反馈改善、新候选生成及 P14d-C 未取得。
以下审计、能力表和任务说明保留原规划时点，后继状态以上述核对为准；原历史失败和耗尽额度不续用。

**后续开发入口：**[有界反馈研究计划](quantos-bounded-adaptive-research-plan-2026-10-17.md)按新的明确目标，
规划科学反馈、新候选和总预算闭环，含模型/思考强度及初学者启动提示词；尚未实施，不重复 D0–D3。

## 1. 判断与首版承诺

**A1 r10 证明了专用控制器下的两步真实 SDK—科学执行—反馈传递链；没有证明它能直接迁移到正式发布入口，也没有证明反馈改变或改善了决策。**
更强的反证是任务原文已要求“首轮选一个，次轮选另一个并停止”；两次响应符合该指令。
剩余问题同时包含入口实现、部署、恢复边界与研究能力证据，不能全部称为产品化。

首个可发布目标暂定 **`agent-runtime-bounded-v1`：固定候选的有界执行版**。
独立操作者从固定提交、环境和 runbook 准备一个受支持任务，一次启动，自动推进至正常终态或明确的安全停止，交付原件与简短报告。
SDK 仅产生候选引用/停止建议；admission、PIT、Qlib、Validation、预算、恢复和报告由确定性程序执行。
这距离完整自动研究还缺反馈驱动决策的证据、SDK 新候选生成及一般异常自恢复；版本名不授予 P14d-C 资格。

| 产品假设 | 本计划的处理 | 若假设不成立 |
|---|---|---|
| 首版允许从已冻结候选开始 | 优先发布既有执行链，不扩展 DSL/family | 若必须生成新候选，首版只是阶段性交付；D0–D3 不足，需另行界定既有 Discovery 接入范围 |
| 不确定副作用允许安全停止并交接 | `UNKNOWN` / `RECOVERY_REQUIRED` 是可交付停止，不能显示为研究成功 | 若要求所有中断自动完成，现有证据不足，不能靠循环承诺 |
| 首版支持明确的一种宿主和有限任务形状 | 固定 SDK/profile、科学 profile、路径与权限条件 | 跨宿主、任意任务兼容不是本批默认义务 |
| 不以盈利或 PASS 验收 | 工程状态、科学结果与 Agent 提案分别报告 | 不改阈值、缩分母或重跑直到 PASS |

### 自动研究能力判定

“已证明”仅指表内样本及依赖范围；E1–E8 的身份和反证条件见第 2 节。

| 可观察行为 | 判定 | 原件支持的行为 / 边界 |
|---|---|---|
| 准备新任务 | 部分证明 | r10 preparer 生成 spec/config/bundle，但依赖旧 campaign、人工冻结胶囊和路径。CLI `prepare` 仅准备已有 request 的 reservation（E1、E5） |
| 一次启动自动推进 | r10 已证明；正式入口未证明 | 一个 controller 循环完成两次 `producer.step`、科学结果及终态；正式 CLI 无 run 循环（E2、E4、E5） |
| 反馈进入下一次模型输入 | SDK 通知记录层已证明 | 第二 reservation prompt 与 provider 两个 echo 字段逐字一致，含本 campaign 第一 trial、Validation 和指标（E2、E3）；不是独立远端 wire/模型内部观测 |
| 模型根据反馈调整决策 | 未证明；将 A1 作为适应性证据存在反证 | 初始任务已指定第二轮选另一个；首响应预告该路径，次响应引用 G5 拒绝不能证明决策受其改变，更无改善的比较证据（E3） |
| 生成新候选 | SDK 运行线未证明且入口受阻 | response 只给冻结 `candidate_ref`，host 映射表达式；Discovery 仍有 `SDK_GENERATION_ENTRY_NOT_QUALIFIED`（E7） |
| 有限预算与停止 | 部分证明 | r10 2 次调用、2 次执行/36 units 后全部候选终态；预算越界/TTL 等有离线用例与源码，成功样本未触发所有停止路径，不证明计费硬 cap（E4、E8） |
| 中断恢复 | 部分证明 | 完整 capture 补发布、receipt 复用、未知阻断有实现/离线用例；r10 收尾只是正常终态对账，没有覆盖所有真实崩溃窗口（第 4 节） |
| 结果交付 | 样本已证明；发布入口部分证明 | 两份 Validation `SUCCEEDED / REJECT`，trial `SOFT_REJECT`；campaign 工程 `COMPLETED`、科学 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`。CLI 只打印简要状态（E4） |
| 无作者帮助的日常运行 | 未证明 | 有专用脚本、环境接线、失败后人工取消/后继准备；无独立操作者从固定发行包完成新任务的记录（E5、E6） |

## 2. 审计基线与可复核证据

### 版本、环境与工作区

- 当前 `main` 与本地 `origin/main` 均为 `d754652fd250b60c90e3e62793375c17b3e70eb6`；本轮不 fetch，远端事实采用保留的发布/CI 原件。
  开始时 `PLAN.md`、`docs/roadmap/README.md` 已修改，本文为未跟踪草稿；未发现源码工作区修改。本轮仅更新这三个文档。
- 既有 tag：`hm-mvp-component-v2` → `59c25ac851cde4f6074d83159fd95a5351237f63`；`p14-rc-v1` → `3a4a898f74ce2f60a14d2a69250024e92a4378c1`。
  `d754652` 是已合并/发布源码基线，无对应自动研究运行版 tag；旧组件接受不能替代新运行版接受。
- r10 源码胶囊 HEAD 为 `401bf4afc67fb58e235560ef2341ea88be265f31`，r9 为 `922ac5897dc843ca300f69d5c5ea996f8b7675f8`。
  本轮核对 r10 源码清单中 267 个文件的大小/字节 hash，全部相符；未将当前 HEAD 重标为历史运行源码。
- [pyproject.toml](../../pyproject.toml) 与 [uv.lock](../../uv.lock) 的可选依赖仍为 `openai-codex==0.154.0`；[命名 FR-03 profile](../../configs/qualification/fr03-sdk-01621-gpt61-medium.json) 为 `0.162.1 + gpt-6.1-sol / medium`。
  r10 `.pth` 实际叠加源码胶囊、保留的 `0.162.1` overlay 与主工作区科学 `.venv`。本轮核到两个 distribution 的 METADATA 版本及 runtime binary SHA256
  `628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1`；没有把整套 `.venv` 视为可复制的独立安装包。

### 原件定位与身份

下列缩写只是精确路径的简写，不是浮动别名。原件主要在本机保留，不随 Git 推送。
哈希均为 SHA256；`…` 是展示缩写，执行参数须使用原件中的完整值。

| 代号 | 原件位置与固定身份 |
|---|---|
| B | [A1/B2 证据根](../../artifacts/hosted-evidence/a1-b2-20261012-01/) |
| C | r10 campaign `876e2ecc8d55845935eb939b428062a37948919ba3825383bf8969b5f6c08079` |
| R | [r10 控制器输出](../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/controller/20261013T110648-de65ab289951435b8dd10b4fa72056dc/) |
| S1 | [首请求 producer 原件](../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/sdk-evidence/876e2ecc8d55845935eb939b428062a37948919ba3825383bf8969b5f6c08079/d6109f0930541146333d128797bcb9c44ba02a7488bb3b636a13f56893daf886/)；request `d6109f…af886`，response `29c856…91706` |
| S2 | [第二请求 producer 原件](../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/sdk-evidence/876e2ecc8d55845935eb939b428062a37948919ba3825383bf8969b5f6c08079/38b032194bca6b67248a7fd3d3ad8cc57714e499252de02cc4f5ed3c6f2b7509/)；request `38b032…b7509`，response `183e18…82e69` |
| P / X | `B/a1/protocol/campaigns/C/` 的 journal/objects；`B/a1/business-runtime/C/` 的 campaign-events/ledger/execution；C 替换为完整 campaign hash |
| F | [r9 第二请求失败原件](../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/sdk-evidence/22589e57e1cd7a4a77950e9cc294847aca0cbeefb8bc2f1f6034f054a59ffdba/8a897e25bead2ca04f2fba575fa0fd6ba485804b81713789e9c95e73d7c1f078/) |
| G | [r10 storage guard](../../artifacts/hosted-evidence/storage-control/run-1791889602752638344-38231/) |
| I | [main CI 原始日志](../../artifacts/evolution-next-20261015/coord/takeover-coverage-01/main-job.log)，字节 hash `07025f0693345c728d8607d659a5b76c745ba03c8af10c75b640b8c2dac2479b` |

### 结论 → 原件/身份 → 推导 → 范围 → 反证或缺证条件

| 编号 / 结论 | 原件、身份与推导 | 适用范围；反证或缺证条件 |
|---|---|---|
| E1：实现可复用，但不是现成发行包 | [capsule](../../artifacts/hosted-evidence/a1-b2-20261012-01/source-capsule-a1-prompt-v4-r10/capsule.json) `e730a823…b8e6`、[inventory](../../artifacts/hosted-evidence/a1-b2-20261012-01/source-capsule-a1-prompt-v4-r10/source-inventory.json) `f14a3e54…7dd`、[runtime binding](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/r10-source-runtime-binding.json) `6928d6c7…af3`；与当前 CLI/lock/实际 `.pth` 合读，历史运行依赖额外 overlay 和管理入口 | 固定源码/保留环境；新安装、host 和传递依赖仍须迁移核对，package version 一致不够 |
| E2：两笔 SDK 捕获与接受闭合 | S1/S2 的 request、reservation、intent、provider/normalized、raw、manifest、response、submission receipt；intent 指向 reservation，response 内嵌 reservation 与原件一致，receipt 的 `submission_bytes_hash` 等于 response 字节 hash，P accepted exchange 对应 | 不是只凭 intent 推断调用；provider 是 SDK 通知投影，不是独立远端计费/内部策略证据。缺 capture 或引用冲突即降级 |
| E3：反馈传递成立，决策改善未证明 | S2 prompt 23,942B，hash `fa084143243c30d07934ec63d586c77610d11561258ae1dc14a2c4cf914a91c2`；provider JSONL 第 2/3 行 `payload.item.content[0].text` 精确相等。投影含 trial `e48d93…b01e4`、Validation `6f7e1f…3447a`，对应 X/P 原件；raw responses 选 window=2/3 | 初始 EVIDENCE `9df525…107d8` 明令次轮选另一个并停止，首 response 已预告该选择。支持引用反馈，不能排除枚举或推断改善；不另开模型效果实验 |
| E4：工程完成、科学拒绝同时成立 | 本轮读 P 的 30 条 journal、43 个小型 objects，核字节 hash、previous 引用/publication；X 的 5 条 campaign-event 链与 R 报告一致。两轮 parent process-exit=0 对应 execution receipt/Validation/trial；研究预算 0→预留 18→结算 18→预留 36→结算 36 | 支持执行与账本关联；未重算 Parquet/预测/科学 gates。缺 receipt、退出非零或预算断链时，摘要成功不足 |
| E5：成功依赖操作员工作 | [r10 管理源码](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/r10-management-source/)、metadata/activation、F、取消记录、preparer/launcher exit；详见第 3 节 | 仅重建保留记录可见介入，不是完整终端审计。r10 两步有连续自动记录，但无从准备到交付无需作者帮助的证明 |
| E6：宿主运行性只在观测范围内成立 | G/prelaunch/policy 指向 `/mnt/c` 物理卷，namespace 记录 mnt/pid；exit 有 waitpid/namespace exit 观测、return_code=0、cleanup_verified=true。R 有 science argv、child-exit 与 parent process-exit | `--unshare-all` 是启动配置；本样本未保存科学子进程完整 UID/capabilities/net namespace 内部观测。I 的实际 label/权限与负控属可销毁 CI runner，不能补写成 A1 host 证明；SDK effective policy 仍 NOT_ATTESTED |
| E7：新候选不是本链能力 | [map_semantic_response](../../src/quantos/application/sdk_producer.py) 从 `candidate_options` 映射；[Discovery generation](../../src/quantos/application/discovery_generation.py) 与 [execution](../../src/quantos/application/discovery_execution.py) 保留 SDK 生成限制 | HM 生成历史不自动迁移 SDK；删 blocker、固定候选换名不构成生成资格 |
| E8：main CI 覆盖回归，未覆盖目标宿主新发布运行 | I checkout 为 `d754652…`；[接受记录及 run/job 身份](../../artifacts/evolution-next-20261015/coord/takeover-coverage-01/main-ci-acceptance.json) 是 38954413221 / 117153534581。原日志有 Pyright 0 errors、2523 passed/1 skipped、85.33%，含 producer/prompt/feedback/protocol/campaign 文件；skip 为旧 field-study preparation unavailable | 本轮核日志 hash、checkout 与结果，未重跑。离线夹具不证明真实 SDK/新安装/目标宿主；不混用 PR merge checkout 与 main checkout |

E3 的直接依据是 S2 prompt 中保留的任务原句：`On the second request consume the bound prior CAMPAIGN_TRIAL outcome/event and choose the other candidate, then request_stop=true.`
S1 raw response 已写明没有反馈支持候选偏好，并预告下一次选另一个；S2 raw response 才引用 G5 的负 Sharpe 与高 turnover。
这使“按指令依次枚举并解释结果”成为与现象完全相容的替代解释。

科学原件：R/science-1、2 对应 execution identity `74c16ce5…0b8c` / `d174f2bc…568b`；
receipt 字节 hash 为 `1290e25c5680b6a5bd2f657405afe791af9f758e22c982d7ed8d29ec5155bda2` /
`30512fea945ac7f6810689ca26689669a30e3b12b6337858324c2733e153ae2f`。
Validation 位于 `X/execution/validation/sha256-<report_hash>/report.json`，内容 hash 为
`6f7e1f1fe4e8a78fc404bfe24c10b5857b4a08d64fa8e98146214037f083447a` /
`0a615afd4dc9c12369bac0979721fd2b37ac92681224b1a17898710f7e1e2f60`；字节 hash 分别为
`e98d1c44f92a2215b9eca552060feada17fa325193a326a9792f8409c8132f81` /
`efe29ced100750ebf97b3bf0fdaaac8642adb1020a5e42191af15bf9b20bade6`。
本轮按 [ValidationReport](../../src/quantos/contracts/validation.py) 排除 `report_hash/created_at/oos_access_event` 的内容域也核到一致。
哈希一致不证明指标正确，报告逻辑时间也不能充当真实进程完成时间。

本轮核对[实际摘要](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/actual-run-summary-01.json)
`c2c62be6bd5002f37fbd6dff2150a7546fc9f2e6c774c2b6b7868577b1ef6a8b` 的 50 个引用大小/字节 hash，全部相符。
摘要仅作定位；关键判断还读取了请求/响应、协议事实、科学 receipt、退出、源码和 CI，没有以摘要互引替代交叉核对。

## 3. 完整执行链、人工介入与失败因果

```text
操作员冻结任务/预算、源码胶囊与环境；专用 preparer 生成 spec/config/bundle
  → root_wrapper 激活窗口、核资源、进入既有 storage guard
  → r10 controller 加载 Hosted service；start 签发 request 1
  → producer：reservation → launch-intent → SDK → 原始 capture → response
  → protocol submit：ACCEPTED → research RESERVED/STARTED
  → helper：持久 MLflow 映射、离线 namespace → Qlib → receipt → 真实退出
  → Hosted：SETTLED → trial / Ledger / ContextPack → request 2
  → 同一 controller 再次 step；重复既有确定性科学链
  → ALL_CANDIDATES_TERMINAL → campaign/selection report
  → controller 内 receipt-only reconciliation → controller exit 0 → guard exit/cleanup
  → 操作员核原件、编写采用/交接记录
```

controller `run_a1_prompt_v4_r10.py` 字节 hash 为
`4e784539ff87efabfd38588cc77f8860c1f5c6bbd8e17f04e71e6719e9c5c18e`；
helper [sdk_science_namespace.py](../../scripts/sdk_science_namespace.py) 为
`d9cd741fd38a3d2462b2a1987ea18b47e23fb89e24bb7e86ed82fc5d564dca21`，后者与 HEAD 相同。

| 介入点 | 实际操作 / 原件 | 对判断的影响 |
|---|---|---|
| r9 失败后处理 | 操作员准备取消及 receipt-only 收尾；[取消 receipt](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-06/protocol-cancel-01/terminal-receipt.json) `7900a17a…2257`；[失败父 exit](../../artifacts/hosted-evidence/a1-b2-20261012-01/a1/controller/20261013T094439-8ab086bc62ca4c38b421324a943946ec/exit.json) `ffad4968…d25d` 仍 exit 1，后续收尾 CANCELLED | 操作员驱动停止/后继，不是系统自行恢复成功 |
| 提示实现调整 | r9→r10 新增 V4 bounded prompt、profile/scanner/helper 接受分支；[开发原件](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-06/prompt-projection-development/)保留失败、源码与已有测试退出 | 成功依赖代码修复；未改旧 request、扩大旧 capture 上限 |
| 新任务与额度 | preparer 绑定取消父、累计 9 次旧 launch、科学账本；wrapper 激活新的 2 次机会及 7200 秒窗口 | 后续普通任务不能依赖历史 9/11 计数及旧绝对路径；污染/预算仍须显式绑定 |
| 环境与路径 | thin Python prefix、`.pth` overlay、empty SDK cwd、guard；helper `patch.object(adapter, "execute", dispatch)`，持久目录映射至 namespace `/tmp/qlib-runtime`，避开 FileStore 的祖先名 `artifacts` 限制 | 普通 CLI step 无此接线；临时可见路径有持久后端，不允许权威仅存在 `/tmp` |
| wrapper 修补 | [prelaunch failure](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/metadata-wrapper-prelaunch-failure-01/exit.json) 记新增 `geteuid==0` gate 提前阻断，metadata/SDK/science 未派发；失败与工作 wrapper 均保留 | 多余 gate 曾阻断已有调用方式，不能把修补后完成称为干净入口一次成功 |
| r10 两步及收尾 | R/before/after-step 和两组退出；源码在一个循环中签发第二请求，并在内部完成一次禁止 fresh execute 的对账 | 未发现两步间人工签发后继请求。对账也在 controller 内；后续 adoption/summary 属操作员解释，不是科学完成本身 |

介入清单限定于 r9 失败→V4 开发→r10 准备、执行和收尾；更早尝试只沿必要的历史计数/原件引用采用，未逐次审计全部操作。
因此不作“全部历史均无人介入”或“已穷尽所有人工操作”的声明。首版独立操作验收需要记录作者是否现场提供修补。

### 主要失败样本：r9 第二次 SDK 捕获失败

F 的 reservation 字节 hash `d2dc07f8…f9fe`，完整 prompt 114,669B。
`host-transport.json` 字节 hash `49e276c9a77ee81c0d8ed55806939719227b9968b6cb6ba742aaf2948157bacb`
记录 TURN_STREAM、ValueError、stdout 263,865B、OVER_BYTE_CAP，超过 262,144B；完整 stdout/provider 未保留。
failure 为 OUTPUT_INVALID、manifest 为 FAILED/HARNESS_OUTPUT_INVALID；raw/provider 空、usage 为 0，**不能推断远端未执行、未计费或调用免费**。
该机会按 launch 记账且未重发；第一轮科学 SOFT_REJECT receipt 保留，取消/收尾不改写失败父。
本轮另核 r9 首请求 `a7d3fca4…e2dc` 的 ACCEPTED 响应、首科学进程 exit0 与 receipt `a08a6958…e055`（18 units）、最终 CANCELLED 报告；
定位和完整 pins 见 [history-inventory](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/history-inventory-01.json)。失败父不是“零成果”，成功子步骤也不使父作业变成成功。

r10 缩小模型输入，保持 V3 provider256KiB、normalized64KiB、raw16KiB、frame512KiB，显式 prompt 限 24KiB。
S1/S2 的 prompt 为 12,281/23,942B、provider58,279/84,579B、frame94,157/136,664B，均在界内。
结合 r9 首成功流及 r10 实际双 prompt echo，缩小输入是有机制依据的解释；缺 r9 第二轮完整流，不能把所有超限字节归因 prompt，也不能保证未来不超限。
因此复用 V4，不再立项扩大捕获上限，超界继续失败留证。

## 4. 副作用与中断窗口

依据：[producer](../../src/quantos/application/sdk_producer.py)、[protocol](../../src/quantos/application/hosted_protocol.py)、
[campaign](../../src/quantos/application/hosted_campaign.py)、[execution](../../src/quantos/application/autonomous_execution.py)；本轮仅阅读。
首版要求可解释且不自动重复副作用，不承诺远端调用与本地磁盘的事务性 exactly-once。

| 中断/边界 | 既有语义与证据 | 首版行为、缺口和禁止事项 |
|---|---|---|
| reservation 已写、intent 未写 | prepare 不调用模型；launch 核 TTL/版本/binary/cap，先持久 intent 再调用 harness | 原件/身份相符且仍有授权才可首次 launch；删除 intent 或换根不是恢复 |
| intent 已写，远端可能执行，capture 未齐 | status=UNKNOWN，launch 拒绝 reissue；`test_unknown_launch_never_reissues` 使用抛异常 harness | 保留机会占用并停。intent 不证明远端发生/没发生；无原件不自动退款/补发、不生成成功 response |
| capture 齐全、response 未发布 | replay 用 capture-fact/provider/normalized/raw 重建核验后补写；V3 用例覆盖删 response 窗口 | 对账后提交同一响应，模型增量 0；replay 是可写恢复，不是纯查询。缺 capture 或 frame 超限仍拒绝 |
| response 已写，提交未完成/本地 submission receipt 缺失 | protocol journal 恢复 INTENT→COMPLETE；相同 bytes 返回原 receipt，不重复 unique submission；accepted 后可 resume | 从 protocol accepted exchange 对账本地副本，不再 launch；不能只看 producer 是否有 submission receipt |
| 重复/冲突提交 | 同 bytes 幂等优先于 TTL/cancel/cap；不同响应计入有界 submission 并拒冲突 | 不改时间/包装冒充新响应。P 中 3 份无 submission bytes 的 EXHAUSTED receipt 是预制 cap 响应，不能计作 3 次真实失败/耗尽 |
| 科学 PREPARED / STARTED / 已完成但未 receipt | PREPARED 可继续；STARTED 先查 verified receipt，缺失则保留 UNCERTAIN reservation、终结为 RECOVERY_REQUIRED/EXECUTION_UNCERTAIN | 有预测或 exit0 也不自动重训/补成功 receipt。既有 `started` 注入在 execute 前，不能称覆盖真实 Qlib 完成但 receipt 缺失的全部窗口 |
| receipt 已发布，业务结算/索引未齐 | 复用 receipt；verified_completed_execution 可修复内容索引，inspect_completed_execution 只读；已有 execution_receipt/completed_intent/trial/ledger 窗口用例 | 同 identity，SDK/science 增量 0。对账模式禁止 fresh execute；普通 resume 可能执行，不能无条件当只读恢复调用 |
| 取消与 TTL | step 在 launch 前查 protocol，直接 launch 只查本地 TTL；accepted 后 cancel 被拒。调用期间过期/取消可使 submit 被拒，已用机会不撤回 | 单 controller，停下一派发并留在途原件；状态检查→launch 与取消不是同一原子操作。首版不承诺即时撤销在途任务，中止按 guard/supervisor |
| cap、无进展、失败或 guard 触发 | producer 以 durable intents 限 launch；业务先 reservation 后执行；有既有停止规则 | 终态/未知/失败/无进展即停；不循环 resume、不换 campaign 绕身份、不加额/延 TTL、不切 Hosted 补发未知请求 |

r10 `receipt-reconciliation-1.json` 仅证明正常终态对账：launch/科学计数不变、fresh execute 阻断，不替代崩溃恢复资格。
命令 exit0 不等于科学 PASS；RECOVERY_REQUIRED、CANCELLED、科学拒绝必须明确显示。
一旦 RECOVERY_REQUIRED 报告已冻结，`_advance` 会核验并返回既有报告，不会因后来出现 receipt 自动重开 campaign。
因此“安全停止”已有依据，“缺失 receipt 后自动恢复到完成”尚不能承诺。

## 5. 最小缺口、Agent 必要性与证明复用

### 按阻断程度排序

| 优先级 / 类型 | 阻止的用户行为 | 最小处理与更小替代方案 |
|---|---|---|
| G0 目标/证据 | 用户将枚举闭环理解为模型自主改进 | 先收紧能力声明；不为缺因果证据改源码或加效果实验 |
| G1 部署/证据 | 固定发行包安装并调用接受 runtime | 固定一套 overlay/解释器/锁和宿主条件，优先保留包/binary；普通 uv extra 安装 0.154.0 不能冒充 r10，无需全局升级依赖 |
| G2 入口实现 | 新任务需复制历史脚本、逐次 step | 单个支持任务模板＋薄 run 入口；通用 authoring builder、任意数据/时期装配不是首版前置 |
| G3 接线/部署/证据 | 普通 step 缺 A1 科学隔离及 MLflow 布局 | 先比较“合规持久根避开 artifacts＋既有隔离”与“参数化 helper”；guard 不允许新根时用最小 helper 接线，不先建 adapter 框架 |
| G4 恢复/易用性 | 用户混淆查询/对账/会执行的 resume，误报完成 | 复用状态机，明确有界运行/只对账语义与 deterministic summary；不建通用救援系统 |
| G5 证据 | 新组合不能证明独立操作者可用 | 同一次最小接受运行检验迁移与独立操作，不再追加作者演示或全历史重验 |

未发现需重建 protocol、Qlib、Ledger、预算引擎的依据。MLflow 路径是已知部署限制，V4 捕获问题已有修复。
缺恢复证明不等于发现重复执行缺陷，应按窗口补证，不先写新状态机。

### 依赖比较与历史证明采用

| 原证明 / 实际差异 | 可采用范围 | 需补证或禁止的推断 |
|---|---|---|
| FR-03 [接受原件](../../artifacts/hosted-evidence/fr03-01621-gpt61-apps-isolated1-p13-01/fr03-go-acceptance/sha256-a12646af8f6f1cbd518ad3d2fbce47499a73c82a430220b1a2cc2f1db56b94cb/acceptance-record.json)，字节身份 `a12646af…94cb`，源码 `ae99d787…718` | 原 exact tuple GO、安装来源与原退出记录 | 明示 deployed=false、无广义 campaign/P14d-C 资格；新环境补对应绑定，不为新 commit 重跑原 20 项 |
| r10→HEAD：CLI/helper、hosted protocol/campaign/inputs、SDK contracts/adapter、storage guard 字节相同；lock 同为 `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca` | 接口行为与原成功样本继续采用，无需重开发 V4/protocol 恢复 | 同文件不保证传递依赖等价，不能说整条链未变 |
| producer/prompt 类型/格式整理；SDK host 增 REQUEST_PARSE hash-only 脱敏；normalizer 错误事件标签归一 | 成功 capture 原件和已有测试来源继续采用 | 失败归一/秘密保护分支按当前实现核受影响用例，不能概括为纯格式 |
| autonomous_execution、research_execution contract、Qlib workflow/pit_evidence/signal/expression 已变 | 旧科学输出/失败/接受身份继续引用 | 新增 field-study profile，改 recorder 包装；legacy 默认仍在，但共享执行/Workflow 路径也变。先核实际 legacy 分支及已有用例，未闭合前不声称 A1 整体迁移 |
| HM/P14d-B/DQ 冻结资格及当前 CI | 原确定性协议、预算、负例/restart 范围与当前回归结果 | P14d verifier 第 2198 行起核精确 HEAD 并重建双根，不是轻量读 hash；DQ 另有 bundle-only。按[资格指南](../guides/qualification.md)选层，本轮均未运行 |

总体 commit 不同不要求重训全部历史任务。legacy 依赖未闭合时交付候选版并列局部缺证，不改 originating tuple，
也不无绑定地混搭新管理代码与旧科学代码。

### 哪些工作需要 Agent

准备、映射、admission、预算、状态推进、receipt 对账、科学执行和报告拼装均应复用确定性程序，无需额外模型调用。
A1 两次选择在业务上可由枚举完成；对“真实 SDK 交接”验收有用，却不证明日常枚举需要模型。
[ScriptedAgentDriver / ReplayAgentDriver](../../src/quantos/application/autonomous.py) 可承担离线编排/恢复检查，但有 fixture/replay 来源限制，不能伪装 SDK 或直接授新研究资格。
不为省两次调用另建通用 driver 平台；固定候选比较优先已有确定性路径，确需模型权衡才授权 SDK 决策。报告润色默认调用 0 次。

r10 观察 input/output 共 43,794/330 tokens，不是计费上限；两个科学子进程 wall time 1,653.66s/1,689.80s，controller 4,412.78s。
其余约 1,069s 混合加载、核验、模型与收尾，不能全归 SDK/磁盘；无逐阶段扫描/峰值数据，不为测量再跑一轮。
优先避免重复科学执行及重复全量核验。

## 6. 修订后的开发任务

保留 D0–D3 编号便于交接，**缩小 D0/D2，改变 D3 的资格承诺**。它们仍需由实际阻断检验必要性；能用文档/配置完成就不强制源码 diff。
以下是后续工作，本轮未执行。
现有操作及参数见 [SDK CLI 指南](../guides/sdk-campaign-offline.md)；下表 run/只对账属于拟交付入口，不能当成当前已有命令。

| 任务 | 缺口、复用点与最小改动 | 依赖 / 可并行 | 独立完成标准与停止条件 |
|---|---|---|---|
| D0：单任务模板与固定安装 | G1/G2；复用 SdkCampaignSpec、loader/bundle 验证、保留包。先给 canonical 模板、支持输入清单、安装/runbook；现有接口不能生成必要绑定时才加薄 preparer。删除通用准备器必做要求 | 先定 legacy 科学 profile、路径、环境、发布基线；环境清单与 D1 静态分析独立 | 新任务无旧 campaign/9 次计数/作者改脚本依赖；准备 0 SDK/科学；版本/binary 可核、全 job 资源报价有据。需放宽契约/加研究能力则停止并缩范围 |
| D1：有界推进与恢复出口 | G2/G4；CLI/application 薄 run，复用 pending/step/resume、intent/capture、journal/receipt；输出工程/科学状态、用量、停止原因及原件 | D0 定输入/目录接口后；D2 可独立分析，共享 CLI/authority 单 writer | 一次启动至终态/安全停止，无进展即停；UNKNOWN 不重发，完整 capture 可明确补发布，缺证交接。需新状态机/远端 exactly-once/通用救援则停该扩展 |
| D2：正式科学隔离接线 | G3/G1；先部署路径方案，不足才参数化 helper 并接 run。可保留两 trial 支持上限，用输入约束代替通用化；旧 helper/失败身份不改。仅既有接点不够时提取小 dispatch 接口 | 使用 D0 根目录/权限/lease；与 D1 可隔离实施，最终调用链顺序集成 | 无操作员临时注入；持久映射、只读输入、科学无网络/LLM、真实退出/cleanup 有据。若须改算法、切 SQLite/profile 或放宽宿主策略，先说明依赖变化和更小方案 |
| D3：局部接受、独立操作、发布 | G5；采用历史证明，补受影响项；同一次最小宿主运行验证正式入口和独立操作者。发布 code/env/profile/runbook 绑定，保留 exploratory/NOT_QUALIFIED 研究限制 | D0–D2 稳定后串行；接受/发布单 writer，真实调用需新有效预算 | 独立操作者无需作者现场改代码/路径/环境完成声明范围；出口可对账。缺必要原件/宿主条件/预算则交付候选版及阻断，失败不改标；不自动宣布 P14d-C 完成 |

这些任务争取交付固定候选的有界执行，不能证明完整自动研究。
P14d-C 若需正式资格，必须明确后继接受义务；B/DQ 原契约排除 live runtime，不能将 FR-03 或 A1 改名使用。
资格名称不是强迫本批扩建框架的理由；实际运行仍须明确探索范围的有效授权和工程接受。
正常无故障样本必须走完所声明的反馈后续及结果交付；故障场景可以安全停止。
不能用首次 UNKNOWN 或缺 receipt 的停止替代正常路径接受，相关失败仍按原身份保留。

## 7. 最小验收方法

哈希/契约核对证明身份与约束；进程记录证明某次启动/退出；离线测试/replay 证明建模窗口和负例处理；
目标宿主独立操作才证明发行版可按说明使用。四层不能互代，另一个 Agent 的同意不增加事实权威。

| 验收项 | 输入、工具/方法 | 预期结果 / 失败判据 | 已有范围 / 剩余不确定性 |
|---|---|---|---|
| A 身份与跨层链 | E1–E8 原件、下方只读示例；git show/diff、SHA256、标准库；按实际 schema 区分内容/字节 hash | request→reservation→capture/response→submission/exchange→trial/receipt/report 闭合；缺失/断链/误比 hash 域即失败 | 本轮已核所列身份/关系；未重算大数据、未运行完整 schema/科学 verifier |
| B 依赖迁移 | r10 胶囊、release 候选、lock/profile；第 5 节 diff 分组及已有 producer/protocol/Workflow 结果 | 每项说明采用或补证理由；共享路径变化未解释不能称等价 | 静态差异已定位；新 run/helper 及传递依赖接受待验证 |
| C 故障语义 | 既有 UNKNOWN、V3 恢复/超 frame、协议重复/取消/TTL、Hosted fresh-process 用例；新入口只补既有用例不能触达的接线 | 不增调用/执行，不重复预算；缺 capture→UNKNOWN，STARTED 无 receipt→RECOVERY_REQUIRED；tamper/错反馈被拒 | CI/V4 开发退出有已通过来源；本轮未测试。真实远端部分执行、Qlib 完成未 receipt 的全过程不能由夹具代替 |
| D 准备与只对账 | 新 task 固定输入/预算、持久根/锁定环境；preparer/runbook；假 harness 限离线 | 无历史 ID 依赖；准备/对账增量 0；不支持输入提前拒绝，对账不偷偷 fresh execute | 待 D0/D1；fixture 成功不授 live 资格 |
| E 宿主正式入口 | 新 tuple/预算、独立操作者、既有 guard/helper 观测出口 | 一次启动到终态/规定停止，进程退出与 receipt/预算吻合；实际 namespace/权限/挂载/cleanup 符合声明；现场改脚本/环境即独立操作不通过 | 待验证；CI AppArmor 例外不能作为共享宿主权限方案 |
| F 研究表述 | 原任务/prompt/raw response、候选来源与结果 | 明示有限候选/反馈传递；不自动写反馈改善、自主生成或盈利 | 已由 A1 反例收紧；若未来声明反馈改变决策，须预声明可区分决策的观察，改善还须比较设计，本批不做 |

下面是可复制的**只读原件检查示例**：不导入服务、不运行模型或解析大数据，只输出计数，不代替完整契约/科学验证。
本轮已分别完成其对应检查；代码块是复核方法，不新增验收程序。

```sh
python3 -B - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('/home/zjw/quant-research-os')
base = root / 'artifacts/hosted-evidence/a1-b2-20261012-01'
raw = (base / 'control/followup-20261013-07/actual-run-summary-01.json').read_bytes()
digest = lambda b: hashlib.sha256(b).hexdigest()
assert digest(raw) == 'c2c62be6bd5002f37fbd6dff2150a7546fc9f2e6c774c2b6b7868577b1ef6a8b'
summary = json.loads(raw)
for ref in summary['original_refs']:
    path = Path(ref['path'])
    assert path.resolve().is_relative_to(root / 'artifacts/hosted-evidence')
    assert path.stat().st_size == ref['bytes'] <= 1_048_576
    assert digest(path.read_bytes()) == ref['sha256']
for row in summary['SDK']:
    folder = base / 'a1/sdk-evidence' / summary['campaign_hash'] / row['request_hash']
    request = json.loads((folder / 'request.json').read_bytes())
    reservation = json.loads((folder / 'reservation.json').read_bytes())
    response_bytes = (folder / 'response.json').read_bytes()
    response = json.loads(response_bytes)
    receipt = json.loads((folder / 'submission-receipt.json').read_bytes())
    assert response['request_hash'] == row['request_hash']
    assert response['reservation'] == reservation
    assert receipt['submission_bytes_hash'] == digest(response_bytes)
    prompt = reservation['execution_request']['prompt']
    events = [json.loads(x) for x in (folder / 'provider-transcript.jsonl').read_text().splitlines()]
    assert all(events[i]['payload']['item']['content'][0]['text'] == prompt for i in (1, 2))
    assert request['campaign_hash'] == summary['campaign_hash']
print('matched references:', len(summary['original_refs']), '; SDK links:', len(summary['SDK']))
PY
```

获后续实现验证授权时，从以下命令选择**受影响节点**，并非每次变化都整组运行；本轮全部未运行：

```sh
.venv/bin/python -B -m pytest -q \
  tests/unit/test_sdk_campaign_producer.py::test_unknown_launch_never_reissues \
  tests/unit/test_sdk_campaign_producer.py::test_tampered_source_rejected_without_new_call \
  tests/unit/test_sdk_capture_v3.py::test_v3_publication_submit_replay_recovery_and_full_original \
  tests/unit/test_sdk_capture_v3.py::test_v3_escaping_can_exceed_frame_bound_and_recovery_cannot_publish \
  tests/unit/test_hosted_protocol.py::test_acceptance_same_bytes_precedes_expiry_cap_and_cancel \
  tests/unit/test_hosted_protocol.py::test_faulted_submit_recovers_original_bytes_timestamp_and_budget \
  tests/unit/test_hosted_campaign.py::test_durable_windows_recover_in_fresh_process
```

prompt/反馈变化才选 `test_sdk_prompt_projection.py`、`test_sdk_feedback_projection.py`；CLI/Workflow 变化才选对应既有用例。
UNKNOWN 用例证明异常后不再调用 harness，未模拟 provider 已收费而本地丢数据的全部情形。
P14d full verifier 不作为默认门禁；确有冻结资格相关变化时，先说明受影响结论、历史 checkout/输入/资源，再按[指南](../guides/qualification.md)选层。

### 真实组合运行的必要性与上限

旧证据不覆盖新发行安装、正式 run/helper 接线和目标宿主组合，假 harness 不能独立证明这些接口。
先完成 A–D 并复用历史结果，只对尚缺组合提出**最多一个新 campaign、2 次 SDK 机会、2 次科学执行、单 worker、零自动重试**的请求。
仅缺安装/首请求交接时缩至 1 次，已有原件/离线方法足以覆盖时 0 次。两次证明从首结果自动继续，不证明决策改善；失败即留证停止，不自动补满上限。
同 execution identity 有效 receipt 可采用，不能改 code/请求身份套用旧 receipt。

同 A1 工作量每次 18 政策 units、两次 36；新输入由既有 quote 重新计算，不与 wall seconds 混用。
原 SDK profile 每次 900s、250,000 input/4,096 output token 接受界不是 provider 计费硬 cap。
新任务须明确 TTL、外发字段、全 job 增长、物理卷余量与并发 reservation，沿既有 guard/lease，不以 WSL free 代替宿主容量。
独立操作者使用同一次接受机会，避免重复演示。A1 历史 SDK11/11、A 科学 5 次/90units 已耗尽；本轮不执行、不复用旧额度。

## 8. 两线规则与启动提示词

| 项目 | 固定发布运行线 | Codex 开发线 |
|---|---|---|
| 版本 | 接受后 detached 至 release 完整 commit，tag 不移动；campaign 显式冻结 code/lock/profile/输入 hash | 从 d754652 或含本文且已核源码差异的后继 main 建短期 feature worktree；main 集成 |
| 环境 | 独立固定 SDK/runtime 与科学环境，记录 host/bwrap/权限/binary 及可变 model alias 限制 | 独立开发环境，不升级运行线 venv；不读取/输出秘密，业务离线段无 LLM |
| 数据/原件 | snapshot/view 只读，campaign 自开始即持久保存成功/失败/退出/receipt，不能只放临时缓存 | 开发输出隔离；复用但不改历史 bytes、失败、接受身份 |
| 故障交接 | 短记录：commit/env、campaign/request/execution identity、阶段、真实退出、原件、已耗额度与允许下一步 | 原件定位、最小修复、局部验证；运行会话不现场修源码或重冻旧任务 |
| 升级/发布 | campaign 不跟随 main 升级；未知调用不换通道重发 | 稳定检查后按实际授权合入/发布/部署；新 tag 绑定提交、安装清单、profile、接受原件、runbook/恢复命令及限制 |

建议开发 worktree `.worktrees/dev-agent-runtime-20261017`，运行 `.worktrees/run-agent-runtime-<commit12>`；持久运行数据独立于可删除 worktree。
旧 worktree、胶囊和 origin/reader 绑定保留，两条线是职责，不要求磁盘只剩两个目录。
D0 环境核对、D1/D2 独立分析可并行；实施隔离文件所有权与 CPU/内存/存储预算。
子 Agent 需当次明确授权，不因本计划自动启动；共享 authority 写入、crash→recovery 链与发布串行，重任务沿既有独占 lease。

开发会话：

> 按 docs/roadmap/quantos-two-track-runtime-plan-2026-10-17.md 实施最小有界运行版。
> 先核 HEAD/工作区及历史证明依赖，在新开发 worktree 完成 D0 单任务模板和环境绑定，再做必要 D1/D2 及 D3 离线部分。
> 授权必要的定向离线实现验证；采用已有通过结果与受影响节点，不重跑资格矩阵或大数据流水线。
> 通用准备器和 adapter 重构不是必做，配置/runbook 足够就不加代码。
> 不调用真实研究模型、不启动新科学批次、不推送/部署，不改冻结契约、历史失败或接受记录。
> 交付可审阅 diff、实际验证范围、支持条件和停止语义；对已有证据未覆盖的部署差异给出一个具体最小真实运行请求与新预算。
> 不将有限候选、反馈引用或 Agent 赞同写成反馈改善、新候选研究或 P14d-C 资格。

运行会话：

> 负责固定发布运行线。读取 docs/roadmap/quantos-two-track-runtime-plan-2026-10-17.md 及所选 release/runbook，
> 核精确 commit、安装/profile、目标宿主、接受范围和剩余额度；用独立 detached worktree 和持久根，不修改运行源码/环境。
> 首版尚未接受时，只准备受支持任务输入/预算并报告阻断，不启动历史已耗尽 campaign。
> 版本与具体新任务有有效授权后，仅用发布入口运行至终态或规定停止，分别交付工程状态、科学结果、用量、退出和原件。
> UNKNOWN 或 STARTED 无 receipt 时留占用并交接；只对账不得新增 SDK/科学，普通 resume 可能执行，不能混用。
> 需现场修代码、路径或环境时留短缺陷记录转开发线，不重发、重训、加额或绕过 guard。

首版后按实际阻断修复；SDK 新候选生成需明确研究需求/预算后接既有 Discovery admission、安全 DSL 与完整分母，不能删 blocker 冒充完成。
继续暂缓长期记忆、Council、通用调度平台、多模型路线、无限循环、自动加额及无关研究任务。
